#!/usr/bin/env python3
"""Activate a checklist item with owner/session/lease protection.

This is the compatibility entrypoint behind `harnessctl start`. It keeps the
legacy todo -> doing behavior, while adding dependency checks, lease checks,
workflow metadata, artifacts, and append-only events.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness_common import (
    active_lease,
    append_event,
    branch_for,
    claim_lease,
    checklist_runtime_problems,
    fail,
    harness_root,
    item_has_plan_locator,
    lease_is_expired,
    load_checklist,
    mutate_checklist,
    rel,
    require_force_reason,
    require_item,
    resolve_item_plan,
    safe_item_id_problem,
    today,
    unfinished_dependencies,
    utc_now,
    validate_checklist,
    ensure_artifacts,
    ensure_review,
    ensure_workflow,
)


PLAN_TEMPLATE = """# {title}

## Item

- Checklist item: `{item_id}`
- Owner: `{owner}`
- Session: `{session}`
- Updated at: `{today}`

## Goal

{acceptance}

## In Scope

- 待补充。

## Out Of Scope

- 待补充。

## Acceptance Mapping

- Current item acceptance: "{acceptance}"
- This plan satisfies it by:
  - 待补充。

## Boundary Review

- Scope non-goals checked:
- Architecture boundaries checked:
- Domain-model decisions checked:
- Potential overlap with other items:

## Steps

1.
2.
3.

## Verification

- verification target: "{verification}"
- local commands:

## Exit Criteria

- 待补充。

## Handoff

- 如果本轮未完成，下一轮从这里继续。
"""


def ensure_plan_file(item: dict, owner: str, session: str) -> Path:
    id_problem = safe_item_id_problem(item["id"])
    if id_problem:
        fail(f"cannot scaffold plan: {id_problem}")
    tasks_dir = harness_root() / "tasks" / item["id"]
    tasks_dir.mkdir(parents=True, exist_ok=True)
    plan_path = tasks_dir / "plan.md"

    if not plan_path.exists():
        plan_path.write_text(
            PLAN_TEMPLATE.format(
                item_id=item["id"],
                title=item["title"],
                owner=owner,
                session=session,
                today=today(),
                acceptance=item.get("acceptance", "待补充"),
                verification=item.get("verification", "待补充"),
            ),
            encoding="utf-8",
        )
        print(f"Created canonical plan: {plan_path}")

    return plan_path


def update_current_pointer(item: dict, plan_path: Path) -> None:
    current_dir = harness_root() / "current"
    current_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = current_dir / "task_plan.md"

    content = f"""# Current Task Pointer

- Checklist item: `{item['id']}`
- Title: {item['title']}
- Status: doing
- Owner: `{item['owner']}`
- Session: `{item['selected_in_session']}`
- Canonical plan: `{rel(plan_path)}`

> This file is a pointer. Full plan content lives in the canonical plan above.
"""
    pointer_path.write_text(content, encoding="utf-8")
    print(f"Updated current pointer: {pointer_path}")


def assert_can_start(
    checklist: dict,
    item: dict,
    *,
    owner: str,
    force: bool,
    reason: str | None,
) -> None:
    require_force_reason(force, reason)

    if item.get("status") == "done":
        fail(f"item '{item['id']}' is already done")

    if item.get("status") == "blocked" and not force:
        fail(f"item '{item['id']}' is blocked; use --force --reason only after an explicit unblock decision")

    unfinished = unfinished_dependencies(checklist, item)
    if unfinished and not force:
        fail(f"item '{item['id']}' has unfinished dependencies: {', '.join(unfinished)}")

    lease = active_lease(item, utc_now())
    if lease:
        lease_owner = lease.get("owner")
        lease_session = lease.get("session")
        if lease_owner != owner and not force:
            fail(
                f"item '{item['id']}' has active lease owned by {lease_owner} "
                f"({lease_session}); use --force --reason to override"
            )

    existing_owner = item.get("owner")
    if existing_owner and existing_owner != owner and not force and not lease and not lease_is_expired(item):
        fail(
            f"item '{item['id']}' already has owner {existing_owner}; "
            "release it first or use --force --reason"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Activate a checklist item (todo -> doing).")
    parser.add_argument("--item", required=True, help="Checklist item ID (e.g. mvp-003).")
    parser.add_argument("--owner", required=True, help="Owner of this item.")
    parser.add_argument("--session", required=True, help="Session identifier.")
    parser.add_argument("--actor", default=None, help="Actor creating the start event. Defaults to owner.")
    parser.add_argument("--lease-minutes", type=int, default=None, help="Lease TTL override.")
    parser.add_argument("--force", action="store_true", help="Override dependency/status/lease checks.")
    parser.add_argument("--reason", default=None, help="Required reason for --force.")
    args = parser.parse_args()

    checklist = load_checklist()
    # Validate the complete current checklist BEFORE any plan scaffold /
    # mkdir / file write: an invalid current document must fail closed with
    # zero side effects, not after the default plan was already created.
    schema_errors, _ = validate_checklist(checklist)
    if schema_errors:
        fail(
            f"current checklist is invalid; refusing to start:\n"
            + "\n".join(f"  - {error}" for error in schema_errors[:8])
        )
    runtime_problems = checklist_runtime_problems(checklist)
    if runtime_problems:
        fail(
            f"current checklist has runtime authority problems; refusing to start:\n"
            + "\n".join(f"  - {problem}" for problem in runtime_problems)
        )
    item = require_item(checklist, args.item)
    assert_can_start(
        checklist,
        item,
        owner=args.owner,
        force=args.force,
        reason=args.reason,
    )

    # Plan resolution: with no locator at all, activation may scaffold the
    # default plan; an existing locator whose file is missing fails closed
    # instead of silently scaffolding over it.
    has_locator = item_has_plan_locator(item)
    plan_path = resolve_item_plan(item, require_exists=has_locator)
    if not has_locator:
        plan_path = ensure_plan_file(item, args.owner, args.session)

    def callback(candidate: dict) -> None:
        item = require_item(candidate, args.item)
        workflow = ensure_workflow(item)
        artifacts = ensure_artifacts(item)
        ensure_review(item)
        artifacts.setdefault("plan", rel(plan_path))
        branch = branch_for(args.owner, args.item)
        artifacts["branch"] = branch

        item["status"] = "doing"
        item["owner"] = args.owner
        item["selected_in_session"] = args.session
        item["updated_at"] = today()
        workflow["status"] = "running"
        workflow["updated_at"] = today()
        workflow["branch"] = branch
        claim_lease(item, args.owner, args.session, args.lease_minutes)

    committed = mutate_checklist(callback)
    committed_item = require_item(committed, args.item)
    update_current_pointer(committed_item, plan_path)

    status = "forced_takeover" if args.force else "running"
    append_event(
        "ACCEPT",
        task=args.item,
        actor=args.actor or args.owner,
        target=args.owner,
        status=status,
        branch=branch_for(args.owner, args.item),
        artifacts=[rel(plan_path)],
        summary=f"{args.owner} started {args.item}",
        metadata={"session": args.session, "force_reason": args.reason},
    )

    print("")
    print(f"Updated checklist: {args.item} -> doing")
    print(f"Canonical plan: {plan_path}")
    print(f"Current pointer: {harness_root() / 'current' / 'task_plan.md'}")
    print("")
    print("Next: implement the plan steps, then run closeout when ready for review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
