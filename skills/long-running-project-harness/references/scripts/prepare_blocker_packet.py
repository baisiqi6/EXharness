#!/usr/bin/env python3
"""Prepare a blocker packet and move a checklist item to blocked."""
from __future__ import annotations

import argparse

from harness_common import (
    append_event,
    harness_root,
    load_checklist,
    read_text,
    rel,
    release_lease,
    require_item,
    save_checklist,
    today,
    ensure_artifacts,
    ensure_workflow,
    write_text,
)


def compact_reason(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip("- ").strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:240]
    return "Blocked; see current/blocker.md."


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a blocker packet for a checklist item.")
    parser.add_argument("--item", required=True, help="Checklist item id, e.g. mvp-003")
    parser.add_argument("--actor", default=None, help="Actor raising the blocker. Defaults to item owner.")
    parser.add_argument("--reason", default=None, help="Human-readable blocker reason override.")
    parser.add_argument("--unblock-owner", default="human", help="Who must decide how to unblock this item.")
    parser.add_argument("--date", default=today(), help="ISO date override")
    args = parser.parse_args()

    root = harness_root()
    checklist = load_checklist()
    item = require_item(checklist, args.item)
    workflow = ensure_workflow(item)
    artifacts = ensure_artifacts(item)

    plan_path = root / "tasks" / args.item / "plan.md"
    blocker_path = root / "current" / "blocker.md"
    packet_path = root / "current" / "blocker-packet.md"
    blocker_text = read_text(blocker_path).rstrip()
    reason = args.reason or compact_reason(blocker_text)

    body = f"""# Blocker Packet

## Subject

- Checklist item: `{item["id"]}`
- Owner: `{item.get("owner")}`
- Session: `{item.get("selected_in_session")}`
- Updated at: `{args.date}`
- Canonical plan path: `{rel(plan_path)}`
- Unblock owner: `{args.unblock_owner}`

## Item Snapshot

- Title: {item["title"]}
- Status: blocked
- Workflow status: blocked
- Priority: {item["priority"]}
- Dependencies: {", ".join(item["dependencies"]) if item["dependencies"] else "None"}

## Acceptance

{item["acceptance"]}

## Verification

{item["verification"]}

## Canonical Plan Content

```md
{read_text(plan_path).rstrip()}
```

## Current Blocker Content

```md
{blocker_text}
```

## Handoff Focus

1. 当前最可能的根因是什么
2. 前三次尝试为什么没有推进
3. 下一位 agent 最值得先验证什么
4. unblock owner 应该是谁：human、architect、implementer 或 reviewer
"""

    write_text(packet_path, body + "\n")
    artifacts["blocker_packet"] = rel(packet_path)
    item["status"] = "blocked"
    item["blocked_reason"] = reason
    item["owner"] = None
    item["selected_in_session"] = None
    item["updated_at"] = today()
    workflow["status"] = "blocked"
    workflow["unblock_owner"] = args.unblock_owner
    workflow["updated_at"] = today()
    release_lease(item)
    save_checklist(checklist)

    append_event(
        "BLOCKER",
        task=args.item,
        actor=args.actor or item.get("owner") or "operator",
        target="human",
        status="blocked",
        artifacts=[rel(packet_path)],
        summary=reason,
    )
    print(f"Wrote blocker packet: {packet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
