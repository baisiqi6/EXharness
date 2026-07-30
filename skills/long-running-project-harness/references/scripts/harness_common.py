#!/usr/bin/env python3
"""Shared helpers for the long-running project harness runtime templates."""
from __future__ import annotations

import json
import sys
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_LEASE_TTL_MINUTES = 120


def project_root() -> Path:
    return Path(__file__).resolve().parents[{{PROJECT_ROOT_DEPTH}}]


def harness_root() -> Path:
    return project_root() / "{{HARNESS_ROOT}}"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(project_root()))
    except ValueError:
        return str(path)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def today() -> str:
    return utc_now().date().isoformat()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def checklist_path() -> Path:
    return harness_root() / "mvp-checklist.json"


def load_checklist() -> dict[str, Any]:
    return read_json(checklist_path())


def save_checklist(checklist: dict[str, Any]) -> None:
    checklist["updated_at"] = today()
    write_json(checklist_path(), checklist)


def config_path() -> Path:
    return harness_root() / "harness-config.json"


def default_config() -> dict[str, Any]:
    return {
        "commands": {},
        "runtime": {
            "session_init_commands": ["typecheck", "test"],
            "lease_ttl_minutes": DEFAULT_LEASE_TTL_MINUTES,
        },
        "git": {
            "base_branch": "main",
            "branch_namespace": "agent/{owner}/{item_id}",
        },
        "message_bus": {
            "event_log": "{{HARNESS_ROOT}}/events.jsonl",
            "visible_bus": "discord-or-kook",
        },
    }


def load_config() -> dict[str, Any]:
    config = default_config()
    user_config = read_json(config_path(), default={})
    if not isinstance(user_config, dict):
        return config
    for key, value in user_config.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def configured_commands(config: dict[str, Any] | None = None) -> dict[str, str]:
    raw = (config or load_config()).get("commands", {})
    if not isinstance(raw, dict):
        return {}
    commands: dict[str, str] = {}
    for name, command in raw.items():
        if isinstance(command, str) and command.strip():
            commands[name] = command.strip()
    return commands


def event_log_path(config: dict[str, Any] | None = None) -> Path:
    message_bus = (config or load_config()).get("message_bus", {})
    configured = "{{HARNESS_ROOT}}/events.jsonl"
    if isinstance(message_bus, dict) and isinstance(message_bus.get("event_log"), str):
        configured = message_bus["event_log"]
    return project_root() / configured


def find_item(checklist: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    return next((entry for entry in checklist.get("items", []) if entry.get("id") == item_id), None)


def require_item(checklist: dict[str, Any], item_id: str) -> dict[str, Any]:
    item = find_item(checklist, item_id)
    if item is None:
        raise SystemExit(f"Checklist item not found: {item_id}")
    return item


def default_workflow_status(item: dict[str, Any]) -> str:
    status = item.get("status")
    if status == "doing":
        return "running"
    if status == "done":
        return "closed"
    if status == "blocked":
        return "blocked"
    return "todo"


def ensure_workflow(item: dict[str, Any]) -> dict[str, Any]:
    workflow = item.get("workflow")
    if not isinstance(workflow, dict):
        workflow = {}
        item["workflow"] = workflow
    workflow.setdefault("status", default_workflow_status(item))
    workflow.setdefault("updated_at", iso_z())
    return workflow


def ensure_artifacts(item: dict[str, Any]) -> dict[str, Any]:
    artifacts = item.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        item["artifacts"] = artifacts
    return artifacts


def ensure_review(item: dict[str, Any]) -> dict[str, Any]:
    review = item.get("review")
    if not isinstance(review, dict):
        review = {}
        item["review"] = review
    review.setdefault("decision", None)
    return review


def active_lease(item: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    lease = item.get("lease")
    if not isinstance(lease, dict):
        return None
    if lease.get("released_at"):
        return None
    expires_at = parse_time(lease.get("expires_at"))
    if expires_at is None:
        return lease
    if expires_at > (now or utc_now()):
        return lease
    return None


def lease_is_expired(item: dict[str, Any], now: datetime | None = None) -> bool:
    lease = item.get("lease")
    if not isinstance(lease, dict) or lease.get("released_at"):
        return False
    expires_at = parse_time(lease.get("expires_at"))
    return expires_at is not None and expires_at <= (now or utc_now())


def claim_lease(item: dict[str, Any], owner: str, session: str, ttl_minutes: int | None = None) -> dict[str, Any]:
    configured_ttl = load_config().get("runtime", {}).get("lease_ttl_minutes", DEFAULT_LEASE_TTL_MINUTES)
    try:
        ttl = int(ttl_minutes or configured_ttl or DEFAULT_LEASE_TTL_MINUTES)
    except (TypeError, ValueError):
        ttl = DEFAULT_LEASE_TTL_MINUTES
    acquired = utc_now()
    lease = {
        "owner": owner,
        "session": session,
        "acquired_at": iso_z(acquired),
        "expires_at": iso_z(acquired + timedelta(minutes=ttl)),
        "ttl_minutes": ttl,
    }
    item["lease"] = lease
    return lease


def release_lease(item: dict[str, Any]) -> None:
    lease = item.get("lease")
    if isinstance(lease, dict) and not lease.get("released_at"):
        lease["released_at"] = iso_z()
    item["lease"] = lease if isinstance(lease, dict) else None


def current_task_pointer_path() -> Path:
    return harness_root() / "current" / "task_plan.md"


def current_task_item_id() -> str | None:
    text = read_text(current_task_pointer_path())
    match = re.search(r"- Checklist item: `([^`]+)`", text)
    return match.group(1).strip() if match else None


def clear_current_pointer(item_id: str, reason: str) -> None:
    pointer_path = current_task_pointer_path()
    if current_task_item_id() != item_id:
        return
    body = f"""# Current Task Pointer

- Checklist item: null
- Status: none
- Cleared at: {iso_z()}
- Reason: {reason}

> No active task is currently selected. Use harnessctl state or assign/start a new item.
"""
    write_text(pointer_path, body)


def unfinished_dependencies(checklist: dict[str, Any], item: dict[str, Any]) -> list[str]:
    items_by_id = {entry.get("id"): entry for entry in checklist.get("items", [])}
    missing: list[str] = []
    for dep_id in item.get("dependencies", []):
        dep = items_by_id.get(dep_id)
        if not dep or dep.get("status") != "done":
            missing.append(dep_id)
    return missing


def branch_for(owner: str, item_id: str, config: dict[str, Any] | None = None) -> str:
    namespace = (config or load_config()).get("git", {}).get(
        "branch_namespace", "agent/{owner}/{item_id}"
    )
    if not isinstance(namespace, str) or not namespace.strip():
        namespace = "agent/{owner}/{item_id}"
    return namespace.format(owner=owner, item_id=item_id)


def append_event(
    event_type: str,
    *,
    task: str | None = None,
    actor: str | None = None,
    target: str | None = None,
    status: str | None = None,
    parent: str | None = None,
    branch: str | None = None,
    pr: str | None = None,
    artifacts: list[str] | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or []
    event = {
        "schema_version": 1,
        "id": event_id or f"evt-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
        "type": event_type,
        "created_at": iso_z(),
        "idempotency_key": f"{event_type}:{task or 'none'}:{status or 'none'}:{actor or 'none'}",
        "causation_id": parent,
        "task": task,
        "actor": actor,
        "target": target,
        "status": status,
        "parent": parent,
        "branch": branch,
        "pr": pr,
        "artifacts": artifacts,
        "summary": summary,
        "metadata": metadata or {},
        "visible_header": None,
        "publish_status": "local_only",
    }
    event["visible_header"] = format_event_header(event)
    path = event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    print(event["visible_header"])
    return event


def format_event_header(event: dict[str, Any]) -> str:
    parts = [
        f"id={event.get('id')}",
        f"task={event.get('task')}",
        f"actor={event.get('actor')}",
    ]
    if event.get("target"):
        parts.append(f"target={event.get('target')}")
    if event.get("status"):
        parts.append(f"status={event.get('status')}")
    if event.get("branch"):
        parts.append(f"branch={event.get('branch')}")
    if event.get("pr"):
        parts.append(f"pr={event.get('pr')}")
    artifacts = event.get("artifacts") or []
    if artifacts:
        parts.append("artifacts=" + ",".join(artifacts))
    return f"[{event.get('type')}] " + " ".join(parts)


def require_force_reason(force: bool, reason: str | None) -> None:
    if force and not (reason or "").strip():
        raise SystemExit("--force requires --reason so the override is auditable")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)
