#!/usr/bin/env python3
"""Deterministic session bootstrap.

Runs: state refresh -> checklist validation -> configured regression checks.
Commands come from harness-config.json when present, with package.json fallback
in build_harness_state.py.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from build_harness_state import build_state, write_state
from harness_common import load_config, project_root


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
    print(f"Harness state refreshed: {state_path}", flush=True)
    print("", flush=True)

    failures: list[str] = []
    root = project_root()
    commands = state.get("commands", {})
    config = load_config()

    if not args.skip_checklist:
        checklist_command = (
            f"{sys.executable} {{SCRIPTS_DIR}}/validate_checklist.py "
            "{{HARNESS_ROOT}}/mvp-checklist.json"
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
