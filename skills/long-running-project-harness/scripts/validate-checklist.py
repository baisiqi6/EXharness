#!/usr/bin/env python3
"""Validate a long-running-project-harness mvp-checklist.json file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {"todo", "doing", "done", "blocked"}
ALLOWED_PRIORITIES = {"p0", "p1", "p2"}
ALLOWED_WORKFLOW_STATUSES = {
    "todo",
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
    "released",
    "closed",
}
ALLOWED_REVIEW_DECISIONS = {None, "approved", "changes_requested", "blocked"}

TOP_REQUIRED = {
    "project",
    "harness_root",
    "updated_at",
    "items",
}

ITEM_REQUIRED = {
    "id",
    "title",
    "status",
    "priority",
    "owner",
    "selected_in_session",
    "updated_at",
    "dependencies",
    "blocked_by",
    "blocked_reason",
    "acceptance",
    "verification",
    "handoff",
}


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def item_label(item: Any, index: int) -> str:
    if isinstance(item, dict) and is_non_empty_string(item.get("id")):
        return f"item {item['id']!r}"
    return f"item at index {index}"


def validate_optional_workflow(item: dict[str, Any], label: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    workflow = item.get("workflow")
    if workflow is None:
        return errors, warnings
    if not isinstance(workflow, dict):
        return [f"{label} optional field 'workflow' must be an object when present"], warnings

    status = workflow.get("status")
    if status not in ALLOWED_WORKFLOW_STATUSES:
        errors.append(
            f"{label} workflow.status must be one of "
            f"{sorted(ALLOWED_WORKFLOW_STATUSES)}, got {status!r}"
        )

    coarse = item.get("status")
    if coarse == "done" and status != "closed":
        warnings.append(f"{label} is done but workflow.status is not 'closed'")
    if coarse == "blocked" and status != "blocked":
        warnings.append(f"{label} is blocked but workflow.status is not 'blocked'")
    if status == "closed" and coarse != "done":
        warnings.append(f"{label} workflow.status is closed but coarse status is not done")
    if status == "running" and coarse != "doing":
        warnings.append(f"{label} workflow.status is running but coarse status is not doing")
    return errors, warnings


def validate_optional_lease(item: dict[str, Any], label: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    lease = item.get("lease")
    if lease is None:
        return errors, warnings
    if not isinstance(lease, dict):
        return [f"{label} optional field 'lease' must be an object or null"], warnings

    for field in ("owner", "session", "acquired_at", "expires_at"):
        if not is_non_empty_string(lease.get(field)):
            errors.append(f"{label} lease.{field} must be a non-empty string")

    if "ttl_minutes" in lease and not isinstance(lease.get("ttl_minutes"), int):
        errors.append(f"{label} lease.ttl_minutes must be an integer when present")

    owner = item.get("owner")
    if owner and is_non_empty_string(lease.get("owner")) and lease.get("owner") != owner:
        warnings.append(f"{label} owner and lease.owner differ")
    return errors, warnings


def validate_optional_artifacts(item: dict[str, Any], label: str) -> list[str]:
    artifacts = item.get("artifacts")
    if artifacts is None:
        return []
    if not isinstance(artifacts, dict):
        return [f"{label} optional field 'artifacts' must be an object when present"]

    errors: list[str] = []
    for key, value in artifacts.items():
        if not is_non_empty_string(key):
            errors.append(f"{label} artifacts keys must be non-empty strings")
        if isinstance(value, list):
            if not all(is_non_empty_string(entry) for entry in value):
                errors.append(f"{label} artifacts.{key} list entries must be non-empty strings")
        elif not is_non_empty_string(value):
            errors.append(f"{label} artifacts.{key} must be a string or list of strings")
    return errors


def validate_optional_review(item: dict[str, Any], label: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    review = item.get("review")
    if review is None:
        return errors, warnings
    if not isinstance(review, dict):
        return [f"{label} optional field 'review' must be an object when present"], warnings

    decision = review.get("decision")
    if decision not in ALLOWED_REVIEW_DECISIONS:
        errors.append(
            f"{label} review.decision must be one of "
            f"{sorted(d for d in ALLOWED_REVIEW_DECISIONS if d is not None)} or null"
        )

    workflow = item.get("workflow")
    has_extended_workflow = isinstance(workflow, dict)
    if item.get("status") == "done" and has_extended_workflow and decision != "approved":
        warnings.append(f"{label} is done under extended workflow but review.decision is not approved")
    return errors, warnings


def validate_checklist(data: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return ["root must be a JSON object"], warnings

    for field in sorted(TOP_REQUIRED):
        if field not in data:
            errors.append(f"root missing required field: {field}")

    for field in ("project", "harness_root", "updated_at"):
        if field in data and not is_non_empty_string(data.get(field)):
            errors.append(f"root field '{field}' must be a non-empty string")

    if "items" in data and not isinstance(data["items"], list):
        errors.append("root field 'items' must be an array")
        return errors, warnings

    items = data.get("items", [])
    if not isinstance(items, list):
        return errors, warnings

    seen_ids: set[str] = set()

    for index, item in enumerate(items):
        label = item_label(item, index)

        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue

        for field in sorted(ITEM_REQUIRED):
            if field not in item:
                errors.append(f"{label} missing required field: {field}")

        item_id = item.get("id")
        if not is_non_empty_string(item_id):
            errors.append(f"{label} field 'id' must be a non-empty string")
        elif item_id in seen_ids:
            errors.append(f"{label} has duplicate id")
        else:
            seen_ids.add(item_id)

        for field in ("title", "updated_at", "acceptance"):
            if field in item and not is_non_empty_string(item.get(field)):
                errors.append(f"{label} field '{field}' must be a non-empty string")

        status = item.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(
                f"{label} field 'status' must be one of "
                f"{sorted(ALLOWED_STATUSES)}, got {status!r}"
            )

        priority = item.get("priority")
        if priority not in ALLOWED_PRIORITIES:
            errors.append(
                f"{label} field 'priority' must be one of "
                f"{sorted(ALLOWED_PRIORITIES)}, got {priority!r}"
            )

        dependencies = item.get("dependencies")
        if "dependencies" in item and not isinstance(dependencies, list):
            errors.append(f"{label} field 'dependencies' must be an array")

        blocked_by = item.get("blocked_by")
        if "blocked_by" in item and not isinstance(blocked_by, list):
            errors.append(f"{label} field 'blocked_by' must be an array")

        if "blocked_reason" in item and item.get("blocked_reason") is not None:
            if not isinstance(item.get("blocked_reason"), str):
                errors.append(f"{label} field 'blocked_reason' must be a string or null")

        if status == "doing":
            if not is_non_empty_string(item.get("owner")):
                errors.append(f"{label} with status 'doing' must have non-empty owner")
            if not is_non_empty_string(item.get("selected_in_session")):
                errors.append(
                    f"{label} with status 'doing' must have non-empty "
                    "selected_in_session"
                )

        if status == "done" and not is_non_empty_string(item.get("verification")):
            errors.append(f"{label} with status 'done' must have non-empty verification")

        if status == "blocked":
            if isinstance(blocked_by, list) and not blocked_by:
                warnings.append(
                    f"{label} with status 'blocked' should list blocked_by item ids "
                    "when another checklist item is the blocker"
                )
            if not is_non_empty_string(item.get("blocked_reason")):
                warnings.append(
                    f"{label} with status 'blocked' should include blocked_reason"
                )
            if not is_non_empty_string(item.get("handoff")):
                warnings.append(f"{label} with status 'blocked' should include handoff")

        workflow_errors, workflow_warnings = validate_optional_workflow(item, label)
        errors.extend(workflow_errors)
        warnings.extend(workflow_warnings)

        lease_errors, lease_warnings = validate_optional_lease(item, label)
        errors.extend(lease_errors)
        warnings.extend(lease_warnings)

        errors.extend(validate_optional_artifacts(item, label))

        review_errors, review_warnings = validate_optional_review(item, label)
        errors.extend(review_errors)
        warnings.extend(review_warnings)

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        label = item_label(item, index)
        dependencies = item.get("dependencies")
        if not isinstance(dependencies, list):
            continue

        for dep_index, dep_id in enumerate(dependencies):
            if not is_non_empty_string(dep_id):
                errors.append(
                    f"{label} dependencies[{dep_index}] must be a non-empty string"
                )
            elif dep_id not in seen_ids:
                errors.append(f"{label} dependency {dep_id!r} does not exist")

        blocked_by = item.get("blocked_by")
        if not isinstance(blocked_by, list):
            continue

        for blocked_index, blocked_id in enumerate(blocked_by):
            if not is_non_empty_string(blocked_id):
                errors.append(
                    f"{label} blocked_by[{blocked_index}] must be a non-empty string"
                )
            elif blocked_id not in seen_ids:
                errors.append(f"{label} blocked_by item {blocked_id!r} does not exist")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a long-running-project-harness mvp-checklist.json file."
    )
    parser.add_argument(
        "checklist",
        nargs="?",
        default="mvp-checklist.json",
        help="Path to mvp-checklist.json. Defaults to ./mvp-checklist.json.",
    )
    args = parser.parse_args()

    path = Path(args.checklist)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {path}: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: could not read {path}: {exc}", file=sys.stderr)
        return 2

    errors, warnings = validate_checklist(data)

    for warning in warnings:
        print(f"WARN: {warning}")

    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors:
        print(
            f"Checklist validation failed: {len(errors)} error(s), "
            f"{len(warnings)} warning(s).",
            file=sys.stderr,
        )
        return 1

    print(f"Checklist validation passed: {path} ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
