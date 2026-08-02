#!/usr/bin/env python3
"""Build machine-readable harness state from source-of-truth files.

Reads: the resolved checklist (harness-checklist.json or legacy
mvp-checklist.json), progress.md, current/task_plan.md, events.jsonl,
optional harness-config.json.
Writes: harness-state.json (atomically, only after semantic validation
of the current checklist; failures fail closed without writing state).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from harness_common import (
    active_lease,
    atomic_write_json,
    checklist_runtime_problems,
    configured_commands,
    event_log_path,
    fail,
    harness_root,
    load_config,
    project_root,
    read_text,
    rel,
    resolve_checklist,
    resolve_item_plan,
    sha256_bytes,
    utc_now,
    validate_checklist,
)


def extract_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            break

    if start is None:
        return ""

    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("#"):
            end = index
            break

    section_lines = [line.rstrip() for line in lines[start:end]]
    return "\n".join(line for line in section_lines if line.strip()).strip()


def compact_text(text: str) -> str:
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


def extract_inline_value(text: str, label: str) -> str | None:
    patterns = [
        rf"- {re.escape(label)}: `([^`]+)`",
        rf"- {re.escape(label)}: (.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _locate_item(checklist: dict[str, Any], current_text: str) -> dict[str, Any] | None:
    item_id = extract_inline_value(current_text, "Checklist item")
    active_workflow_statuses = {
        "assigned",
        "accepted",
        "running",
        "handoff_requested",
        "review_requested",
        "ready_for_review",
        "closeout_requested",
        "review_approved",
        "changes_requested",
        "blocked",
        "unblocked",
    }

    def is_active(entry: dict[str, Any]) -> bool:
        if entry.get("status") == "done":
            return False  # terminal items never masquerade as current
        workflow = entry.get("workflow")
        workflow_status = workflow.get("status") if isinstance(workflow, dict) else None
        return entry.get("status") in {"doing", "blocked"} or workflow_status in active_workflow_statuses

    if not item_id:
        running_items = [
            item
            for item in checklist["items"]
            if is_active(item)
        ]
        if len(running_items) == 1:
            return running_items[0]
        return None

    if item_id == "null":
        return None
    item = next((entry for entry in checklist["items"] if entry["id"] == item_id), None)
    if item is None or not is_active(item):
        return None
    return item


def detect_current_item(checklist: dict[str, Any], current_text: str) -> dict[str, Any] | None:
    item = _locate_item(checklist, current_text)
    if item is None:
        return None

    # The plan locator authority is the checklist (via the unified resolver);
    # the pointer only helps locate the item and must not override it.
    plan_path = rel(resolve_item_plan(item, require_exists=False))

    return {
        "id": item["id"],
        "title": item["title"],
        "status": item["status"],
        "owner": item.get("owner"),
        "selected_in_session": item.get("selected_in_session"),
        "updated_at": item.get("updated_at"),
        "workflow": item.get("workflow"),
        "lease": item.get("lease"),
        "active_lease": active_lease(item, utc_now()),
        "artifacts": item.get("artifacts", {}),
        "review": item.get("review", {}),
        "plan_path": plan_path,
    }


def checklist_summary(checklist: dict[str, Any]) -> dict[str, int]:
    counts = Counter(item.get("status", "unknown") for item in checklist["items"])
    return {
        "todo": counts.get("todo", 0),
        "doing": counts.get("doing", 0),
        "done": counts.get("done", 0),
        "blocked": counts.get("blocked", 0),
    }


def workflow_summary(checklist: dict[str, Any]) -> dict[str, int]:
    statuses: Counter[str] = Counter()
    for item in checklist["items"]:
        workflow = item.get("workflow")
        if isinstance(workflow, dict) and isinstance(workflow.get("status"), str):
            statuses[workflow["status"]] += 1
    return dict(sorted(statuses.items()))


def detect_commands(resolved_checklist_path: Path | None = None) -> dict[str, str]:
    commands = {
        "state": "{{SCRIPTS_DIR}}/harnessctl state",
        "session_init": "{{SCRIPTS_DIR}}/harnessctl session-init",
        "validate_checklist": (
            "python3 {{SCRIPTS_DIR}}/validate_checklist.py "
            + (
                rel(resolved_checklist_path)
                if resolved_checklist_path is not None
                else "{{HARNESS_ROOT}}/harness-checklist.json"
            )
        ),
    }

    config_commands = configured_commands()
    if config_commands:
        commands.update(config_commands)
        return commands

    package_path = project_root() / "package.json"
    if not package_path.exists():
        return commands

    package = json.loads(package_path.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    package_manager = "pnpm" if (project_root() / "pnpm-lock.yaml").exists() else "npm run"
    if "typecheck" in scripts:
        commands["typecheck"] = f"{package_manager} typecheck"
    if "test" in scripts:
        commands["test"] = f"{package_manager} test"
    if "build" in scripts:
        commands["build"] = f"{package_manager} build"
    return commands


def detect_open_risks(progress_text: str, checklist: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    blockers = compact_text(extract_section(progress_text, "## Blockers"))
    if blockers and blockers not in {"None.", "- None."}:
        risks.append(blockers)

    for item in checklist.get("items", []):
        if item.get("status") == "blocked":
            reason = item.get("blocked_reason") or item.get("handoff") or "blocked"
            risks.append(f"{item.get('id')}: {reason}")
    return risks


def recent_events(limit: int = 8) -> list[dict[str, Any]]:
    path = event_log_path()
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            events.append({"invalid": line})
        else:
            events.append(parsed)
    return events


def build_state() -> dict[str, Any]:
    root = harness_root()
    # Resolve once, read once: the parsed/validated bytes are exactly the
    # bytes the digest is computed from.
    resolved = resolve_checklist(purpose="read")
    original_bytes = resolved.path.read_bytes()
    try:
        checklist = json.loads(original_bytes)
    except json.JSONDecodeError as exc:
        fail(f"checklist {resolved.path} is not valid JSON: {exc}")
    errors, _ = validate_checklist(checklist)
    if errors:
        fail(
            f"checklist is invalid; refusing to derive state: {resolved.path}\n"
            + "\n".join(f"  - {error}" for error in errors[:8])
        )
    runtime_problems = checklist_runtime_problems(checklist)
    if runtime_problems:
        fail(
            f"checklist has runtime authority problems; refusing to derive state: {resolved.path}\n"
            + "\n".join(f"  - {problem}" for problem in runtime_problems)
        )
    resolved_checklist_path = resolved.path
    checklist_sha256 = sha256_bytes(original_bytes)
    progress_text = read_text(root / "progress.md")
    current_text = read_text(root / "current" / "task_plan.md")
    current_item = detect_current_item(checklist, current_text)
    config = load_config()

    return {
        "project": checklist.get("project", project_root().name),
        "harness_root": checklist.get("harness_root", "{{HARNESS_ROOT}}"),
        "generated_at": utc_now().isoformat().replace("+00:00", "Z"),
        "source": {
            "checklist_path": rel(resolved_checklist_path),
            "checklist_sha256": checklist_sha256,
        },
        "current_status": compact_text(extract_section(progress_text, "## Current Status")),
        "current_item": current_item,
        "checklist_summary": checklist_summary(checklist),
        "workflow_summary": workflow_summary(checklist),
        "paths": {
            "scope": "{{HARNESS_ROOT}}/scope.md",
            "architecture": "{{HARNESS_ROOT}}/architecture.md",
            "domain_model": "{{HARNESS_ROOT}}/domain-model.md",
            "checklist": rel(resolved_checklist_path),
            "progress": "{{HARNESS_ROOT}}/progress.md",
            "runbook": "{{HARNESS_ROOT}}/runbook.md",
            "config": "{{HARNESS_ROOT}}/harness-config.json",
            "events": rel(event_log_path(config)),
            "current_task_plan": "{{HARNESS_ROOT}}/current/task_plan.md",
        },
        "commands": detect_commands(resolved_checklist_path),
        "runtime": config.get("runtime", {}),
        "git": config.get("git", {}),
        "message_bus": config.get("message_bus", {}),
        "open_risks": detect_open_risks(progress_text, checklist),
        "recent_events": recent_events(),
    }


def write_state(state: dict[str, Any]) -> Path:
    output_path = harness_root() / "harness-state.json"
    atomic_write_json(output_path, state)
    return output_path


def main() -> int:
    state = build_state()
    output_path = write_state(state)
    print(f"Wrote harness state: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
