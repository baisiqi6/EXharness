#!/usr/bin/env python3
"""Prepare a handoff packet for transferring a checklist item between agents."""
from __future__ import annotations

import argparse

from harness_common import (
    append_event,
    harness_root,
    load_checklist,
    mutate_checklist,
    read_text,
    rel,
    release_lease,
    require_item,
    resolve_item_plan,
    today,
    ensure_artifacts,
    ensure_workflow,
    write_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a handoff packet for a checklist item.")
    parser.add_argument("--item", required=True, help="Checklist item id, e.g. mvp-003")
    parser.add_argument("--target", required=True, help="Target owner/agent label")
    parser.add_argument("--actor", default="operator", help="Actor requesting the handoff")
    parser.add_argument("--reason", default="", help="Why the handoff is needed")
    parser.add_argument("--date", default=today(), help="ISO date override")
    args = parser.parse_args()

    root = harness_root()
    checklist = load_checklist()
    item = require_item(checklist, args.item)
    workflow = ensure_workflow(item)
    previous_owner = item.get("owner")
    previous_session = item.get("selected_in_session")

    plan_path = resolve_item_plan(item, require_exists=True)
    progress_path = root / "progress.md"
    blocker_path = root / "current" / "blocker.md"
    packet_path = root / "current" / "handoff-packet.md"

    body = f"""# Handoff Packet

## Subject

- Checklist item: `{item["id"]}`
- From: `{item.get("owner")}`
- To: `{args.target}`
- Requested by: `{args.actor}`
- Updated at: `{args.date}`
- Reason: {args.reason or "Not specified."}
- Canonical plan path: `{rel(plan_path)}`

## Item Snapshot

- Title: {item["title"]}
- Status: {item["status"]}
- Workflow status: {workflow.get("status")}
- Priority: {item["priority"]}
- Current owner: {previous_owner}
- Current session: {previous_session}

## Acceptance

{item["acceptance"]}

## Current Handoff

{item.get("handoff") or "No handoff recorded."}

## Canonical Plan Content

```md
{read_text(plan_path).rstrip()}
```

## Recent Progress

```md
{read_text(progress_path).rstrip()[-3000:]}
```

## Current Blocker

```md
{read_text(blocker_path).rstrip()}
```

## Expected Next Action

- Target agent should accept, decline, or raise a blocker explicitly.
- If accepted, target agent should run `{{SCRIPTS_DIR}}/harnessctl accept {args.item} {args.target} <session-id>`.
"""

    write_text(packet_path, body + "\n")

    def callback(candidate: dict) -> None:
        item = require_item(candidate, args.item)
        workflow = ensure_workflow(item)
        artifacts = ensure_artifacts(item)
        artifacts["handoff_packet"] = rel(packet_path)
        workflow["status"] = "handoff_requested"
        workflow["handoff_from"] = previous_owner
        workflow["handoff_target"] = args.target
        workflow["updated_at"] = today()
        release_lease(item)
        item["status"] = "todo"
        item["owner"] = None
        item["selected_in_session"] = None
        item["updated_at"] = today()

    mutate_checklist(callback)

    append_event(
        "ASSIGN",
        task=args.item,
        actor=args.actor,
        target=args.target,
        status="handoff_requested",
        artifacts=[rel(packet_path)],
        summary=args.reason or f"Handoff requested for {args.item}",
    )
    print(f"Wrote handoff packet: {packet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
