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
    iso_z,
    deployment_profile,
    require_standalone_mutation,
    validate_checklist,
    ensure_workflow,
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


def _apply_mode_transition(item: dict, new_mode: str) -> None:
    """D2: the single mode transition rule set for update-item --mode.

    Allowed:
    - explicit `ordinary` -> `high-risk` (any non-done status);
    - legacy missing mode -> explicit `high-risk`;
    - legacy missing mode on an item that has not started (coarse `todo`,
      workflow status missing or `todo`) -> explicit `ordinary`.

    Rejected (all keep the original bytes untouched):
    - explicit `high-risk` -> `ordinary` (downgrade);
    - started/released/blocked/review/closed legacy item -> `ordinary`;
    - same explicit mode (no-op);
    - any transition on a `done` item.

    A mode mutation always refreshes the item `updated_at` (caller does it);
    `workflow.updated_at` is refreshed only when the workflow already carries
    a lifecycle `status`. A mode-only workflow keeps exactly `{mode}` - no
    timestamp/status is invented; the first lifecycle entry is initialized
    by the existing ensure_workflow. Unknown compatible workflow fields are
    preserved. This is a monotonic upgrade boundary, not a risk engine.
    """
    label = f"item {item.get('id')!r}"
    if item.get("status") == "done":
        fail(f"{label} is done; workflow mode cannot be changed")
    workflow = item.get("workflow")
    workflow_dict = workflow if isinstance(workflow, dict) else {}
    explicit_mode = workflow_dict.get("mode")
    explicit = "mode" in workflow_dict
    if explicit and explicit_mode == new_mode:
        fail(
            f"{label} workflow.mode is already {new_mode!r}; "
            "no-op mode transitions are rejected"
        )
    if new_mode == "ordinary":
        if explicit:
            fail(
                f"{label} has explicit workflow.mode {explicit_mode!r}; "
                "downgrade from high-risk to ordinary is not allowed"
            )
        workflow_status = workflow_dict.get("status")
        if item.get("status") != "todo" or (
            workflow_status is not None and workflow_status != "todo"
        ):
            fail(
                f"{label} is a legacy item without an explicit mode that has "
                "already started; only items that have not started (coarse "
                "todo, workflow status missing or todo) can be classified "
                "ordinary"
            )
    if not workflow_dict:
        workflow_dict = {}
        item["workflow"] = workflow_dict
    workflow_dict["mode"] = new_mode
    if "status" in workflow_dict:
        workflow_dict["updated_at"] = iso_z()
    elif item.get("status") != "todo":
        # A legacy item already inside the lifecycle (e.g. doing with no
        # workflow at all) must not end up as a mode-only workflow - that
        # shape is only legal for coarse todo. Initialize the lifecycle
        # fields through the shared helper so the candidate stays valid.
        ensure_workflow(item)


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
            "updated_at": iso_z(),
            "dependencies": dependencies,
            "blocked_by": [],
            "blocked_reason": None,
            "acceptance": args.acceptance,
            "verification": "",
            "handoff": args.handoff or "",
        }
        if stored_plan is not None:
            item["plan_path"] = stored_plan
        if args.mode is not None:
            # D2: explicit pre-start classification writes a mode-only
            # workflow ({mode}); the lifecycle starts later via
            # ensure_workflow. Without --mode the legacy shape (no workflow)
            # is kept and the effective mode stays high-risk.
            item["workflow"] = {"mode": args.mode}
        checklist.setdefault("items", []).append(item)

    mutate_checklist(callback)
    mode_note = f", mode={args.mode}" if args.mode is not None else ""
    print(
        f"Added checklist item: {item_id} "
        f"(status=todo, priority={args.priority}{mode_note})"
    )
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
        and args.mode is None
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

        # --mode is the only workflow mutation allowed here (D2): it never
        # touches status/owner/lease/review, and every rejection leaves the
        # original bytes untouched via the mutation pipeline.
        if args.mode is not None:
            _apply_mode_transition(item, args.mode)

        # The callback only runs when at least one modification flag was
        # passed (pre-checked above), so the item content always changed;
        # refresh its machine evidence timestamp.
        item["updated_at"] = iso_z()

    mutate_checklist(callback)
    mode_note = f" (workflow.mode={args.mode})" if args.mode is not None else ""
    print(f"Updated checklist item: {item_id}{mode_note}")
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
    add.add_argument(
        "--mode",
        choices=("ordinary", "high-risk"),
        default=None,
        help="Explicit workflow mode: writes a mode-only workflow ({mode}) for pre-start classification.",
    )
    add.set_defaults(func=do_add_item)

    update = sub.add_parser(
        "update-item",
        help="Update allowed fields of an existing item (never status/owner/lease/workflow/review; --mode is the sole workflow.mode transition).",
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
    update.add_argument(
        "--mode",
        choices=("ordinary", "high-risk"),
        default=None,
        help=(
            "Workflow mode transition (D2): upgrade explicit ordinary to high-risk, "
            "or classify a not-yet-started legacy item (no mode) as ordinary/high-risk; "
            "downgrades, no-ops, and done items are rejected."
        ),
    )
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
