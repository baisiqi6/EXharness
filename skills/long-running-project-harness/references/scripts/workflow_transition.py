#!/usr/bin/env python3
"""Explicit multi-agent workflow transitions for harness checklist items."""
from __future__ import annotations

import argparse

from harness_common import (
    active_lease,
    append_event,
    branch_for,
    claim_lease,
    clear_current_pointer,
    fail,
    item_has_plan_locator,
    lease_is_expired,
    load_checklist,
    mutate_checklist,
    rel,
    release_lease,
    require_force_reason,
    require_item,
    resolve_item_plan,
    today,
    unfinished_dependencies,
    utc_now,
    ensure_artifacts,
    ensure_review,
    ensure_workflow,
)


APPROVAL_DECISIONS = {"approved", "changes_requested", "blocked"}


def is_handoff_target(item: dict, owner: str) -> bool:
    workflow = item.get("workflow")
    return (
        isinstance(workflow, dict)
        and workflow.get("status") == "handoff_requested"
        and workflow.get("handoff_target") == owner
    )


def assert_not_done(item: dict) -> None:
    if item.get("status") == "done":
        fail(f"item '{item['id']}' is already done")


def assert_claimable(
    checklist: dict,
    item: dict,
    *,
    owner: str,
    force: bool,
    reason: str | None,
) -> None:
    require_force_reason(force, reason)
    assert_not_done(item)

    if item.get("status") == "blocked" and not force:
        fail(f"item '{item['id']}' is blocked")

    unfinished = unfinished_dependencies(checklist, item)
    if unfinished and not force:
        fail(f"item '{item['id']}' has unfinished dependencies: {', '.join(unfinished)}")

    lease = active_lease(item, utc_now())
    if lease and lease.get("owner") != owner and not force and not is_handoff_target(item, owner):
        fail(
            f"item '{item['id']}' has active lease owned by {lease.get('owner')} "
            f"({lease.get('session')})"
        )

    existing_owner = item.get("owner")
    if (
        existing_owner
        and existing_owner != owner
        and not force
        and not lease
        and not lease_is_expired(item)
        and not is_handoff_target(item, owner)
    ):
        fail(f"item '{item['id']}' already has owner {existing_owner}")


def do_assign(args: argparse.Namespace) -> int:
    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        assert_claimable(checklist, item, owner=args.owner, force=args.force, reason=args.reason)

        workflow = ensure_workflow(item)
        artifacts = ensure_artifacts(item)
        ensure_review(item)
        branch = args.branch or branch_for(args.owner, args.item)

        # The plan locator answer comes from the unified resolver. When the
        # item already carries a locator (plan_path or artifacts.plan), never
        # write a different default into the other field; only a locator-less
        # item gets the default artifacts.plan.
        plan_path = resolve_item_plan(item, require_exists=False)
        if not item_has_plan_locator(item):
            artifacts.setdefault("plan", rel(plan_path))

        item["owner"] = args.owner
        item["selected_in_session"] = args.session
        item["updated_at"] = today()
        workflow["status"] = "assigned"
        workflow["updated_at"] = today()
        workflow["branch"] = branch
        artifacts["branch"] = branch
        claim_lease(item, args.owner, args.session, args.lease_minutes)

    committed = mutate_checklist(callback)
    committed_item = require_item(committed, args.item)
    committed_plan = resolve_item_plan(committed_item, require_exists=False)
    append_event(
        "ASSIGN",
        task=args.item,
        actor=args.actor,
        target=args.owner,
        status="assigned",
        branch=committed_item.get("workflow", {}).get("branch"),
        artifacts=[rel(committed_plan)],
        summary=args.summary or f"{args.actor} assigned {args.item} to {args.owner}",
        metadata={"session": args.session, "force_reason": args.reason},
    )
    return 0


def do_accept(args: argparse.Namespace) -> int:
    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        assert_claimable(checklist, item, owner=args.owner, force=args.force, reason=args.reason)

        workflow = ensure_workflow(item)
        branch = args.branch or workflow.get("branch") or branch_for(args.owner, args.item)
        artifacts = ensure_artifacts(item)
        item["status"] = "doing"
        item["owner"] = args.owner
        item["selected_in_session"] = args.session
        item["updated_at"] = today()
        workflow["status"] = "running"
        workflow.pop("handoff_target", None)
        workflow["updated_at"] = today()
        workflow["branch"] = branch
        artifacts["branch"] = branch
        claim_lease(item, args.owner, args.session, args.lease_minutes)

    committed = mutate_checklist(callback)
    committed_item = require_item(committed, args.item)
    append_event(
        "ACCEPT",
        task=args.item,
        actor=args.owner,
        target=args.owner,
        status="running",
        branch=committed_item.get("workflow", {}).get("branch"),
        summary=args.summary or f"{args.owner} accepted {args.item}",
        metadata={"session": args.session, "force_reason": args.reason},
    )
    return 0


def do_decline(args: argparse.Namespace) -> int:
    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        workflow = ensure_workflow(item)

        target = workflow.get("handoff_target") or item.get("owner")
        if target and target != args.actor and not args.force:
            fail(
                f"item '{args.item}' is targeted at {target}; "
                "use --force --reason to decline as another actor"
            )
        require_force_reason(args.force, args.reason)

        # Declined items return to the unowned todo queue and release the
        # workflow; the DECLINE evidence (event + declined_by + decline_reason)
        # is preserved so the override stays auditable.
        item["status"] = "todo"
        item["owner"] = None
        item["selected_in_session"] = None
        item["updated_at"] = today()
        workflow["status"] = "released"
        workflow["declined_by"] = args.actor
        workflow["decline_reason"] = args.reason or args.summary or "Declined."
        workflow["updated_at"] = today()
        release_lease(item)

    mutate_checklist(callback)
    append_event(
        "DECLINE",
        task=args.item,
        actor=args.actor,
        status="declined",
        summary=args.summary or args.reason or "Declined.",
        metadata={"force_reason": args.reason},
    )
    return 0


def do_renew_lease(args: argparse.Namespace) -> int:
    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        lease = active_lease(item, utc_now())
        if lease and lease.get("owner") != args.owner and not args.force:
            fail(f"item '{args.item}' has active lease owned by {lease.get('owner')}")
        if item.get("owner") and item.get("owner") != args.owner and not args.force:
            fail(f"item '{args.item}' is owned by {item.get('owner')}")
        require_force_reason(args.force, args.reason)

        item["owner"] = args.owner
        item["selected_in_session"] = args.session
        item["updated_at"] = today()
        claim_lease(item, args.owner, args.session, args.lease_minutes)

    mutate_checklist(callback)
    append_event(
        "LEASE",
        task=args.item,
        actor=args.owner,
        target=args.owner,
        status="renewed",
        summary=args.summary or f"{args.owner} renewed lease for {args.item}",
        metadata={"session": args.session, "force_reason": args.reason},
    )
    return 0


def do_release(args: argparse.Namespace) -> int:
    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        require_force_reason(args.force, args.reason)

        owner = item.get("owner")
        if owner and args.actor != owner and not args.force:
            fail(
                f"item '{args.item}' is owned by {owner}; "
                "use --force --reason to release as another actor"
            )

        workflow = ensure_workflow(item)
        if item.get("status") == "doing":
            item["status"] = "todo"
        item["owner"] = None
        item["selected_in_session"] = None
        item["updated_at"] = today()
        workflow["status"] = "released"
        workflow["updated_at"] = today()
        release_lease(item)

    mutate_checklist(callback)
    clear_current_pointer(args.item, "released")
    append_event(
        "RELEASE",
        task=args.item,
        actor=args.actor,
        status="released",
        summary=args.summary or f"{args.actor} released {args.item}",
        metadata={"force_reason": args.reason},
    )
    return 0


def do_unblock(args: argparse.Namespace) -> int:
    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        workflow = ensure_workflow(item)
        review = ensure_review(item)

        if item.get("status") != "blocked":
            fail(f"item '{args.item}' is not blocked")

        unblock_owner = workflow.get("unblock_owner")
        if unblock_owner and unblock_owner != args.actor and not args.force:
            fail(
                f"item '{args.item}' is assigned to unblock owner {unblock_owner}; "
                "use --force --reason only for explicit override"
            )

        require_force_reason(args.force, args.reason)
        item["status"] = "todo"
        item["blocked_reason"] = None
        item["blocked_by"] = []
        item["updated_at"] = today()
        workflow["status"] = "unblocked"
        workflow["unblocked_by"] = args.actor
        workflow["unblock_decision"] = args.decision
        workflow["updated_at"] = today()
        review["decision"] = None
        release_lease(item)

    mutate_checklist(callback)
    clear_current_pointer(args.item, "unblocked")
    append_event(
        "UNBLOCK",
        task=args.item,
        actor=args.actor,
        status="unblocked",
        summary=args.decision,
        metadata={"force_reason": args.reason},
    )
    return 0


def do_review_result(args: argparse.Namespace) -> int:
    if args.decision not in APPROVAL_DECISIONS:
        fail(f"review decision must be one of: {', '.join(sorted(APPROVAL_DECISIONS))}")

    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        review = ensure_review(item)
        workflow = ensure_workflow(item)
        previous_workflow_status = workflow.get("status")

        review["decision"] = args.decision
        review["reviewer"] = args.reviewer
        review["phase"] = previous_workflow_status
        review["updated_at"] = today()
        if args.summary:
            review["summary"] = args.summary
        if args.artifact:
            review["artifact"] = args.artifact

        if args.decision == "approved":
            workflow["status"] = "review_approved"
        elif args.decision == "changes_requested":
            workflow["status"] = "changes_requested"
        else:
            item["status"] = "blocked"
            item["blocked_reason"] = args.summary or "Reviewer blocked this item."
            workflow["status"] = "blocked"
        workflow["updated_at"] = today()
        item["updated_at"] = today()

    committed = mutate_checklist(callback)
    committed_item = require_item(committed, args.item)
    append_event(
        "REVIEW",
        task=args.item,
        actor=args.reviewer,
        target=committed_item.get("owner"),
        status=args.decision,
        artifacts=[args.artifact] if args.artifact else [],
        summary=args.summary or f"{args.reviewer} marked {args.item} {args.decision}",
    )
    return 0


def do_mark_done(args: argparse.Namespace) -> int:
    checklist = load_checklist()
    item = require_item(checklist, args.item)
    if item.get("status") == "done":
        print(f"Item already done: {args.item}")
        return 0

    def callback(checklist: dict) -> None:
        item = require_item(checklist, args.item)
        require_force_reason(args.force, args.reason)

        review = ensure_review(item)
        workflow = ensure_workflow(item)
        if not args.force:
            if review.get("decision") != "approved":
                fail("mark-done requires review.decision == approved; use --force --reason only for explicit human override")
            if review.get("phase") != "closeout_requested":
                fail("mark-done requires approved review of a closeout request; use --force --reason only for explicit human override")

        existing_verification = item.get("verification")
        if not ((isinstance(existing_verification, str) and existing_verification.strip()) or args.verification):
            fail(
                "mark-done requires an existing non-empty verification or "
                "an explicit --verification TEXT written in the same mutation; "
                "no placeholder text is generated"
            )
        if args.verification:
            item["verification"] = args.verification

        item["status"] = "done"
        item["updated_at"] = today()
        workflow["status"] = "closed"
        workflow["updated_at"] = today()
        release_lease(item)
        item["owner"] = None
        item["selected_in_session"] = None

    committed = mutate_checklist(callback)
    committed_item = require_item(committed, args.item)
    clear_current_pointer(args.item, "closed")
    append_event(
        "CLOSE",
        task=args.item,
        actor=args.actor,
        target=committed_item.get("owner"),
        status="done",
        artifacts=[args.artifact] if args.artifact else [],
        summary=args.summary or f"{args.actor} closed {args.item}",
        metadata={"force_reason": args.reason},
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply explicit harness workflow transitions.")
    sub = parser.add_subparsers(dest="command", required=True)

    assign = sub.add_parser("assign", help="Assign an item without starting implementation.")
    assign.add_argument("--item", required=True)
    assign.add_argument("--owner", required=True)
    assign.add_argument("--session", required=True)
    assign.add_argument("--actor", default="operator")
    assign.add_argument("--branch", default=None)
    assign.add_argument("--lease-minutes", type=int, default=None)
    assign.add_argument("--summary", default=None)
    assign.add_argument("--force", action="store_true")
    assign.add_argument("--reason", default=None)
    assign.set_defaults(func=do_assign)

    accept = sub.add_parser("accept", help="Accept an assigned item and move it to running.")
    accept.add_argument("--item", required=True)
    accept.add_argument("--owner", required=True)
    accept.add_argument("--session", required=True)
    accept.add_argument("--branch", default=None)
    accept.add_argument("--lease-minutes", type=int, default=None)
    accept.add_argument("--summary", default=None)
    accept.add_argument("--force", action="store_true")
    accept.add_argument("--reason", default=None)
    accept.set_defaults(func=do_accept)

    release = sub.add_parser("release", help="Release ownership and lease for an item.")
    release.add_argument("--item", required=True)
    release.add_argument("--actor", required=True)
    release.add_argument("--summary", default=None)
    release.add_argument("--force", action="store_true")
    release.add_argument("--reason", default=None)
    release.set_defaults(func=do_release)

    decline = sub.add_parser("decline", help="Decline an assigned or handed-off item.")
    decline.add_argument("--item", required=True)
    decline.add_argument("--actor", required=True)
    decline.add_argument("--summary", default=None)
    decline.add_argument("--force", action="store_true")
    decline.add_argument("--reason", default=None)
    decline.set_defaults(func=do_decline)

    renew = sub.add_parser("renew-lease", help="Renew an active lease for the current owner/session.")
    renew.add_argument("--item", required=True)
    renew.add_argument("--owner", required=True)
    renew.add_argument("--session", required=True)
    renew.add_argument("--lease-minutes", type=int, default=None)
    renew.add_argument("--summary", default=None)
    renew.add_argument("--force", action="store_true")
    renew.add_argument("--reason", default=None)
    renew.set_defaults(func=do_renew_lease)

    unblock = sub.add_parser("unblock", help="Move a blocked item back to the todo queue.")
    unblock.add_argument("--item", required=True)
    unblock.add_argument("--actor", required=True)
    unblock.add_argument("--decision", required=True)
    unblock.add_argument("--force", action="store_true")
    unblock.add_argument("--reason", default=None)
    unblock.set_defaults(func=do_unblock)

    review = sub.add_parser("review-result", help="Record reviewer decision.")
    review.add_argument("--item", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--decision", required=True)
    review.add_argument("--summary", default=None)
    review.add_argument("--artifact", default=None)
    review.set_defaults(func=do_review_result)

    done = sub.add_parser("mark-done", help="Close an item after approved review.")
    done.add_argument("--item", required=True)
    done.add_argument("--actor", default="operator")
    done.add_argument("--summary", default=None)
    done.add_argument("--artifact", default=None)
    done.add_argument(
        "--verification",
        default=None,
        help="Verification text written in the same mutation when the item has none.",
    )
    done.add_argument("--force", action="store_true")
    done.add_argument("--reason", default=None)
    done.set_defaults(func=do_mark_done)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
