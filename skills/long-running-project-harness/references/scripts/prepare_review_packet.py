#!/usr/bin/env python3
"""Prepare a review packet for a checklist item.

Reads checklist + canonical plan, writes current/review-packet.md, updates the
item workflow to review_requested, and appends a visible event.
"""
from __future__ import annotations

import argparse

from harness_common import (
    append_event,
    harness_root,
    load_checklist,
    read_text,
    rel,
    require_item,
    save_checklist,
    today,
    ensure_artifacts,
    ensure_review,
    ensure_workflow,
    write_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a review packet for a checklist item.")
    parser.add_argument("--item", required=True, help="Checklist item id, e.g. mvp-003")
    parser.add_argument("--reviewer", default="TBD", help="Reviewer label")
    parser.add_argument("--date", default=today(), help="ISO date override")
    args = parser.parse_args()

    root = harness_root()
    checklist = load_checklist()
    item = require_item(checklist, args.item)
    workflow = ensure_workflow(item)
    artifacts = ensure_artifacts(item)
    ensure_review(item)

    plan_path = root / "tasks" / args.item / "plan.md"
    packet_path = root / "current" / "review-packet.md"

    body = f"""# Review Packet

## Subject

- Checklist item: `{item["id"]}`
- Reviewer: `{args.reviewer}`
- Updated at: `{args.date}`
- Canonical plan path: `{rel(plan_path)}`

## Item Snapshot

- Title: {item["title"]}
- Status: {item["status"]}
- Workflow status: {workflow.get("status")}
- Priority: {item["priority"]}
- Owner: {item.get("owner")}
- Session: {item.get("selected_in_session")}
- Dependencies: {", ".join(item["dependencies"]) if item["dependencies"] else "None"}

## Acceptance

{item["acceptance"]}

## Verification

{item["verification"]}

## Handoff

{item["handoff"]}

## Review Inputs

- Scope: `{{HARNESS_ROOT}}/scope.md`
- Architecture: `{{HARNESS_ROOT}}/architecture.md`
- Domain model: `{{HARNESS_ROOT}}/domain-model.md`
- Progress: `{{HARNESS_ROOT}}/progress.md`
- Review output target: `{{HARNESS_ROOT}}/current/review.md`

## Canonical Plan Content

```md
{read_text(plan_path).rstrip()}
```

## Review Focus

1. 当前计划或结果是否覆盖 acceptance
2. 是否越过 scope non-goals
3. 是否越过 architecture 模块边界
4. 是否偷偷吸收了未来 checklist item 的工作
5. 当前验证方式是否足以支持结束本轮
"""

    write_text(packet_path, body + "\n")
    artifacts["review_packet"] = rel(packet_path)
    workflow["status"] = "review_requested"
    workflow["updated_at"] = today()
    item["updated_at"] = today()
    save_checklist(checklist)

    append_event(
        "REVIEW",
        task=args.item,
        actor=item.get("owner") or "operator",
        target=args.reviewer,
        status="requested",
        artifacts=[rel(packet_path)],
        summary=f"Review requested for {args.item}",
    )
    print(f"Wrote review packet: {packet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
