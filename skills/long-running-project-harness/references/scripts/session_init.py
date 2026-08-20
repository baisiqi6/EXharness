#!/usr/bin/env python3
"""Deterministic session bootstrap.

Runs: state refresh -> checklist validation -> configured regression checks.
Commands come from harness-config.json when present, with package.json fallback
in build_harness_state.py.

Also performs a read-only `git worktree list --porcelain -z` discovery
(issue #12): when the current item carries a workflow.branch, the session
prints the unique available worktree for that branch, or explicit WARNINGs
for zero/multiple/prunable-only matches. Discovery is ephemeral diagnostic
output only: it never gates, never mutates Git or state, and never creates
or switches worktrees.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from build_harness_state import build_state, write_state
from harness_common import load_config, project_root, rel, resolve_checklist

BRANCH_PREFIX = "refs/heads/"


@dataclass(frozen=True)
class WorktreeEntry:
    """One `git worktree list --porcelain -z` stanza, parsed.

    ``branch`` is the short name with exactly the ``refs/heads/`` prefix
    stripped; detached/bare entries have no branch. ``prunable_reason`` and
    ``locked_reason`` are None unless the corresponding valueless-or-valued
    key was present (a valueless key maps to an empty-string reason).
    """

    path: str
    head: str | None = None
    branch: str | None = None
    detached: bool = False
    bare: bool = False
    prunable_reason: str | None = None
    locked_reason: str | None = None

    @property
    def prunable(self) -> bool:
        return self.prunable_reason is not None

    @property
    def locked(self) -> bool:
        return self.locked_reason is not None


def short_branch_name(value: str) -> str:
    """Strip exactly the ``refs/heads/`` prefix; anything else stays as-is."""
    if value.startswith(BRANCH_PREFIX):
        return value[len(BRANCH_PREFIX):]
    return value


def _field_reason(raw: str | bool | None) -> str | None:
    """prunable/locked value: str reason, or empty string for a valueless key."""
    if raw is None:
        return None
    return "" if raw is True else str(raw)


def _entry_from_fields(fields: dict[str, str | bool]) -> WorktreeEntry:
    head = fields.get("HEAD")
    branch = fields.get("branch")
    return WorktreeEntry(
        path=str(fields.get("worktree", "")),
        head=head if isinstance(head, str) else None,
        branch=short_branch_name(branch) if isinstance(branch, str) else None,
        detached=bool(fields.get("detached")),
        bare=bool(fields.get("bare")),
        prunable_reason=_field_reason(fields.get("prunable")),
        locked_reason=_field_reason(fields.get("locked")),
    )


def parse_worktree_porcelain(raw: str) -> list[WorktreeEntry]:
    """Parse NUL-separated porcelain output into stanzas.

    Each stanza is a run of fields terminated by an empty field; each field
    splits on its FIRST space only, so valueless keys (``detached``,
    ``bare``) and space-containing values/paths survive intact.
    """
    entries: list[WorktreeEntry] = []
    fields: dict[str, str | bool] = {}
    for field in raw.split("\x00"):
        if field == "":
            if fields:
                entries.append(_entry_from_fields(fields))
                fields = {}
            continue
        key, sep, value = field.partition(" ")
        fields[key] = value if sep else True
    if fields:
        entries.append(_entry_from_fields(fields))
    return entries


def _normcase(path: str) -> str:
    """Separated so tests can mock Windows-style case folding on POSIX."""
    return os.path.normcase(path)


def canonical_path(path: str) -> str:
    """Symlink-resolved, normalized, case-folded absolute path."""
    return _normcase(os.path.normpath(str(Path(path).resolve(strict=False))))


def discover_worktrees(root: Path) -> tuple[list[WorktreeEntry] | None, str]:
    """Read-only ``git worktree list --porcelain -z`` discovery.

    Returns (entries, "") on success and (None, reason) on any discovery
    failure: missing git binary, non-repo directory, non-zero exit, or a
    read error. Discovery is never a failure gate for session-init.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return None, (proc.stderr or f"git exited {proc.returncode}").strip()
    return parse_worktree_porcelain(proc.stdout), ""


def _display_path(entry: WorktreeEntry) -> str:
    """Path with the locked annotation appended when present."""
    if not entry.locked:
        return entry.path
    reason = entry.locked_reason
    return f"{entry.path} (locked: {reason})" if reason else f"{entry.path} (locked)"


def worktree_report_lines(
    entries: list[WorktreeEntry],
    item_branch: str | None,
    root: Path,
    base_branch: str | None,
) -> list[str]:
    """Ephemeral diagnostic lines for the current Git worktree context.

    Current worktree identity compares canonical (resolve/normpath/normcase)
    paths. An item branch match must be an exact short-branch-name match on
    an available entry (not prunable, path exists); prunable or unavailable
    entries are never called active, locked candidates are annotated but
    still locatable. Zero/multiple matches are explicit WARNINGs that never
    pick a path.
    """
    lines: list[str] = []
    root_canonical = canonical_path(str(root))
    current = next(
        (e for e in entries if canonical_path(e.path) == root_canonical), None
    )
    if current is not None:
        flags = ["current"]
        if current.branch:
            flags.append(f"branch={current.branch}")
        elif current.detached:
            flags.append("detached")
        elif current.bare:
            flags.append("bare")
        if base_branch:
            flags.append(f"base={base_branch}")
        lines.append(f"Worktree: {current.path} ({', '.join(flags)})")

    if not item_branch:
        return lines

    def available(entry: WorktreeEntry) -> bool:
        return not entry.prunable and Path(entry.path).exists()

    matches = [e for e in entries if e.branch == item_branch]
    candidates = [e for e in matches if available(e)]
    unavailable = [e for e in matches if not available(e)]

    if len(candidates) == 1:
        entry = candidates[0]
        lines.append(f"Active item worktree: {_display_path(entry)}")
        if canonical_path(entry.path) != root_canonical:
            lines.append(f"Recommendation: switch to {entry.path}")
    elif len(candidates) > 1:
        lines.append(
            "WARNING: multiple worktrees for branch "
            f"'{item_branch}': {', '.join(_display_path(e) for e in candidates)}"
        )
        lines.append("Refusing to choose between them.")
    elif unavailable:
        lines.append(
            "WARNING: branch "
            f"'{item_branch}' only matches a prunable/unavailable worktree "
            f"({', '.join(_display_path(e) for e in unavailable)}); it is not active"
        )
    else:
        lines.append(f"WARNING: no worktree for branch '{item_branch}'")
    return lines


def worktree_report(root: Path, item_branch: str | None, config: dict) -> list[str]:
    """Full discovery + decision pipeline; empty when Git is unavailable."""
    entries, reason = discover_worktrees(root)
    if entries is None:
        return []
    git_config = config.get("git")
    base_branch = git_config.get("base_branch") if isinstance(git_config, dict) else None
    return worktree_report_lines(entries, item_branch, root, base_branch)


def run_step(label: str, command: str | list[str], cwd: Path) -> int:
    print(f"--- {label} ---", flush=True)
    if isinstance(command, str):
        print("$ " + command, flush=True)
        result = subprocess.run(command, cwd=cwd, shell=True)
    else:
        print("$ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=cwd)
    print("", flush=True)
    return result.returncode


def print_summary(state: dict) -> None:
    current_item = state.get("current_item") or {}
    summary = state.get("checklist_summary", {})
    workflow_summary = state.get("workflow_summary", {})

    print("=== Session Init ===", flush=True)
    print(f"Project root: {project_root()}", flush=True)
    print(f"Harness root: {project_root() / state['harness_root']}", flush=True)
    print(f"Current status: {state.get('current_status') or 'Unavailable'}", flush=True)
    print(
        "Checklist summary: "
        f"todo={summary.get('todo', 0)} "
        f"doing={summary.get('doing', 0)} "
        f"done={summary.get('done', 0)} "
        f"blocked={summary.get('blocked', 0)}",
        flush=True,
    )
    if workflow_summary:
        print(f"Workflow summary: {workflow_summary}", flush=True)
    if current_item:
        workflow = current_item.get("workflow") or {}
        lease = current_item.get("active_lease") or current_item.get("lease") or {}
        print(
            "Current item: "
            f"{current_item.get('id')} "
            f"({current_item.get('status')}, workflow={workflow.get('status')}, "
            f"owner={current_item.get('owner')})",
            flush=True,
        )
        if lease:
            print(
                "Lease: "
                f"owner={lease.get('owner')} session={lease.get('session')} "
                f"expires_at={lease.get('expires_at')}",
                flush=True,
            )
        print(f"Canonical plan: {current_item.get('plan_path')}", flush=True)
    else:
        print("Current item: none detected", flush=True)
    print("", flush=True)


def command_order(config: dict, commands: dict[str, str]) -> list[str]:
    configured = config.get("runtime", {}).get("session_init_commands")
    if isinstance(configured, list):
        return [entry for entry in configured if isinstance(entry, str) and entry in commands]
    return [entry for entry in ("typecheck", "test") if entry in commands]


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic session bootstrap for {{PROJECT_NAME}}.")
    parser.add_argument("--skip-checklist", action="store_true", help="Skip checklist validation.")
    parser.add_argument("--skip-typecheck", action="store_true", help="Skip configured typecheck command.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip configured test command.")
    parser.add_argument(
        "--skip-command",
        action="append",
        default=[],
        help="Skip a named command from harness-config.json. Can be repeated.",
    )
    args = parser.parse_args()

    state = build_state()
    state_path = write_state(state)
    print_summary(state)
    root = project_root()
    config = load_config()
    current_item = state.get("current_item") or {}
    workflow = current_item.get("workflow") or {}
    item_branch = workflow.get("branch") if isinstance(workflow, dict) else None
    worktree_lines = worktree_report(root, item_branch, config)
    if worktree_lines:
        print("--- Worktree Discovery (read-only) ---", flush=True)
        for line in worktree_lines:
            print(line, flush=True)
    print("", flush=True)
    print(f"Harness state refreshed: {state_path}", flush=True)
    print("", flush=True)

    failures: list[str] = []
    commands = state.get("commands", {})

    if not args.skip_checklist:
        resolved = resolve_checklist(purpose="read")
        checklist_command = (
            f"{sys.executable} {{SCRIPTS_DIR}}/validate_checklist.py "
            f"{rel(resolved.path)}"
        )
        if run_step("Checklist Validation", checklist_command, root) != 0:
            failures.append("checklist validation failed")

    skips = set(args.skip_command)
    if args.skip_typecheck:
        skips.add("typecheck")
    if args.skip_tests:
        skips.add("test")

    for name in command_order(config, commands):
        if name in skips:
            print(f"--- {name} skipped ---", flush=True)
            print("", flush=True)
            continue
        if run_step(name, commands[name], root) != 0:
            failures.append(f"{name} failed")

    if failures:
        print("Session init finished with failures:", flush=True)
        for failure in failures:
            print(f"- {failure}", flush=True)
        return 1

    print("Session init finished cleanly.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
