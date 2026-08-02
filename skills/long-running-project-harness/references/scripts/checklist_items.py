#!/usr/bin/env python3
"""Checklist item management commands: add-item, update-item, migrate-checklist.

These are the only dynamic node mutation entry points in the Standalone
harness. Every mutation goes through the common pipeline
(harness_common.mutate_checklist): resolve -> validate current -> deepcopy
-> callback -> validate candidate -> atomic write.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from harness_common import (
    CHECKLIST_NEW_NAME,
    CHECKLIST_LEGACY_NAME,
    fail,
    find_item,
    harness_root,
    mutate_checklist,
    project_root,
    require_item,
    resolve_checklist,
    safe_item_id_problem,
    today,
    deployment_profile,
    require_standalone_mutation,
    validate_checklist,
    _fsync_dir,
)


def validate_plan_argument(raw: str) -> str:
    """Validate --plan: no lexical '..' anywhere in the raw path, file must
    exist, returns stored form.

    Standalone keeps the operator's explicit choice of an external absolute
    plan locator; this is a lexical/regular-file check, not containment
    security. Coordinate-managed rejects the whole command earlier.
    """
    raw_parts = Path(raw).parts
    if ".." in raw_parts:
        fail(f"--plan must not contain '..': {raw!r}")
    path = os.path.normpath(raw)
    candidate = path if os.path.isabs(path) else os.path.join(str(project_root()), path)
    if not (os.path.isfile(candidate) and os.access(candidate, os.R_OK)):
        fail(f"--plan file not found or not readable: {candidate}")
    return path if os.path.isabs(path) else os.path.relpath(candidate, str(project_root()))


def _set_plan_locator(item: dict, stored: str) -> None:
    """Write a single plan locator, repairing every locator field that
    exists.

    Repair is keyed on field presence, not on whether the current value is
    valid: when both plan_path and artifacts.plan keys exist (even if one or
    both carry a bad type/value), both are written to `stored` so the
    candidate passes the shared runtime check; only a single present field
    is updated; with neither present, plan_path is created. Other artifact
    keys and unknown compatible fields are preserved.
    """
    artifacts = item.get("artifacts")
    artifacts_dict = artifacts if isinstance(artifacts, dict) else {}
    plan_path_exists = "plan_path" in item
    artifacts_plan_exists = "plan" in artifacts_dict

    if plan_path_exists and artifacts_plan_exists:
        item["plan_path"] = stored
        item.setdefault("artifacts", {})["plan"] = stored
    elif plan_path_exists:
        item["plan_path"] = stored
    elif artifacts_plan_exists:
        item.setdefault("artifacts", {})["plan"] = stored
    else:
        item["plan_path"] = stored


def do_add_item(args: argparse.Namespace) -> int:
    require_standalone_mutation()
    # Validate the raw id BEFORE normalization: edge control characters
    # (newline, tab) must not be silently stripped away. Ordinary leading /
    # trailing spaces still follow the legacy .strip() normalization.
    id_problem = safe_item_id_problem(args.item_id)
    if id_problem:
        fail(f"cannot add item: {id_problem}")
    item_id = args.item_id.strip()

    stored_plan = validate_plan_argument(args.plan) if args.plan else None

    def callback(checklist: dict) -> None:
        if find_item(checklist, item_id) is not None:
            fail(f"checklist item already exists: {item_id}")

        dependencies = list(args.dependency or [])
        for dep in dependencies:
            if dep == item_id:
                fail(f"item {item_id!r} cannot depend on itself")
            if find_item(checklist, dep) is None:
                fail(f"dependency item not found: {dep}")

        item = {
            "id": item_id,
            "title": args.title,
            "status": "todo",
            "priority": args.priority,
            "owner": None,
            "selected_in_session": None,
            "updated_at": today(),
            "dependencies": dependencies,
            "blocked_by": [],
            "blocked_reason": None,
            "acceptance": args.acceptance,
            "verification": "",
            "handoff": args.handoff or "",
        }
        if stored_plan is not None:
            item["plan_path"] = stored_plan
        checklist.setdefault("items", []).append(item)

    mutate_checklist(callback)
    print(f"Added checklist item: {item_id} (status=todo, priority={args.priority})")
    return 0


def do_update_item(args: argparse.Namespace) -> int:
    require_standalone_mutation()
    # Same raw-before-normalize rule as add-item.
    id_problem = safe_item_id_problem(args.item_id)
    if id_problem:
        fail(f"cannot update item: {id_problem}")
    item_id = args.item_id.strip()

    simple_fields = [
        (field, getattr(args, field))
        for field in ("title", "acceptance", "priority", "verification", "handoff")
        if getattr(args, field) is not None
    ]
    stored_plan = validate_plan_argument(args.plan) if args.plan is not None else None
    add_dependencies = list(args.add_dependency or [])
    remove_dependencies = list(args.remove_dependency or [])

    if (
        not simple_fields
        and stored_plan is None
        and not add_dependencies
        and not remove_dependencies
    ):
        fail("update-item requires at least one modification flag")

    def callback(checklist: dict) -> None:
        item = require_item(checklist, item_id)

        for field, value in simple_fields:
            if field in ("title", "acceptance", "verification", "handoff"):
                if not (isinstance(value, str) and value.strip()):
                    fail(f"--{field.replace('_', '-')} must be a non-empty string")
            item[field] = value

        current_dependencies = list(item.get("dependencies") or [])
        if remove_dependencies:
            missing = [dep for dep in remove_dependencies if dep not in current_dependencies]
            if missing:
                fail(f"cannot remove missing dependencies: {', '.join(missing)}")
            current_dependencies = [dep for dep in current_dependencies if dep not in remove_dependencies]
        for dep in add_dependencies:
            if dep == item_id:
                fail(f"item {item_id!r} cannot depend on itself")
            if dep in current_dependencies:
                fail(f"dependency already present: {dep}")
            if find_item(checklist, dep) is None:
                fail(f"dependency item not found: {dep}")
            current_dependencies.append(dep)
        if add_dependencies or remove_dependencies:
            item["dependencies"] = current_dependencies

        if stored_plan is not None:
            _set_plan_locator(item, stored_plan)

    mutate_checklist(callback)
    print(f"Updated checklist item: {item_id}")
    return 0


def do_migrate(args: argparse.Namespace) -> int:
    if deployment_profile() != "standalone" and not args.ack_managed_profile:
        fail(
            "migrate-checklist under deployment_profile=coordinate-managed "
            "requires --ack-managed-profile. Note: this flag is an "
            "acknowledgement against accidental runs, not a deploy/migration "
            "authority token."
        )

    resolved = resolve_checklist(purpose="migrate")
    old_path = resolved.path
    new_path = harness_root() / CHECKLIST_NEW_NAME

    try:
        data = json.loads(old_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{CHECKLIST_LEGACY_NAME} could not be read as JSON: {exc}")
    errors, _ = validate_checklist(data)
    if errors:
        fail(
            f"{CHECKLIST_LEGACY_NAME} is invalid; fix it before migrating:\n"
            + "\n".join(f"  - {error}" for error in errors[:8])
        )

    try:
        os.replace(old_path, new_path)
    except OSError as exc:
        fail(f"migrate-checklist failed to rename {CHECKLIST_LEGACY_NAME}: {exc}")
    try:
        _fsync_dir(harness_root())
    except OSError as exc:
        fail(
            f"migrate-checklist rename succeeded but directory fsync failed: {exc}; "
            "the new filename is the single authority, re-run doctor to confirm"
        )
    print(
        f"Migrated {CHECKLIST_LEGACY_NAME} -> {CHECKLIST_NEW_NAME} "
        "(bytes unchanged, no git operation performed)"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage checklist items (add/update) and migrate the checklist filename."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-item", help="Add a new todo checklist item.")
    add.add_argument("item_id", metavar="ID", help="Unique item id (e.g. mvp-004).")
    add.add_argument("--title", required=True, help="Item title.")
    add.add_argument("--acceptance", required=True, help="Objective acceptance text.")
    add.add_argument("--priority", choices=("p0", "p1", "p2"), default="p1")
    add.add_argument("--plan", default=None, help="Canonical plan locator (file must exist).")
    add.add_argument("--dependency", action="append", default=[], help="Existing dependency id. Repeatable.")
    add.add_argument("--handoff", default=None, help="Handoff note for the next session.")
    add.set_defaults(func=do_add_item)

    update = sub.add_parser(
        "update-item",
        help="Update allowed fields of an existing item (never status/owner/lease/workflow/review).",
    )
    update.add_argument("item_id", metavar="ID")
    update.add_argument("--title", default=None)
    update.add_argument("--acceptance", default=None)
    update.add_argument("--priority", choices=("p0", "p1", "p2"), default=None)
    update.add_argument("--plan", default=None, help="Canonical plan locator (file must exist).")
    update.add_argument("--verification", default=None)
    update.add_argument("--handoff", default=None)
    update.add_argument("--add-dependency", action="append", default=[])
    update.add_argument("--remove-dependency", action="append", default=[])
    update.set_defaults(func=do_update_item)

    migrate = sub.add_parser(
        "migrate-checklist",
        help="Rename mvp-checklist.json to harness-checklist.json (same-directory rename).",
    )
    migrate.add_argument(
        "--ack-managed-profile",
        action="store_true",
        help="Acknowledge running under coordinate-managed (acknowledgement only).",
    )
    migrate.set_defaults(func=do_migrate)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
