#!/usr/bin/env python3
"""Prepare a handoff packet for transferring a checklist item between agents."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness_common import (
    append_event,
    harness_root,
    load_checklist,
    mutate_checklist,
    project_root,
    render_plan_snapshot,
    read_text,
    rel,
    release_lease,
    require_item,
    resolve_item_plan,
    iso_z,
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
    parser.add_argument("--date", default=None, help="Machine timestamp override (default: current UTC ISO-8601)")
    parser.add_argument("--refresh", action="store_true", help="Refresh an existing pending handoff without replaying assignment or lease release")
    args = parser.parse_args()

    root = harness_root()
    checklist = load_checklist()
    item = require_item(checklist, args.item)
    original_item = json.dumps(item, sort_keys=True)
    workflow = ensure_workflow(item)
    previous_owner = item.get("owner")
    previous_session = item.get("selected_in_session")

    from consistency_handoff import (
        enabled, packet_path as task_packet_path, render_binding, parse_binding, write_bound_packet,
    )
    strict = enabled()
    if args.refresh and not strict:
        raise SystemExit("--refresh requires an adopted consistency contract")
    if args.refresh and (workflow.get("status") != "handoff_requested" or
                         workflow.get("handoff_target") != args.target):
        raise SystemExit("refresh requires this same pending item and target")

    plan_path = resolve_item_plan(item, require_exists=True)
    progress_path = root / "progress.md"
    blocker_path = root / "current" / "blocker.md"
    packet_path = task_packet_path(item) if strict else root / "current" / "handoff-packet.md"
    previous = None
    if args.refresh:
        raw = item.get("artifacts", {}).get("handoff_packet")
        if raw:
            old = Path(raw)
            old = old if old.is_absolute() else project_root() / old
            try:
                previous = parse_binding(old.read_bytes())
            except OSError:
                raise SystemExit("existing handoff unreadable; inspect before migrating")
            except ValueError:
                # An explicit refresh can adopt a legacy packet. Malformed
                # new bindings cannot be silently treated as legacy.
                if old.read_bytes().startswith(b"<!-- exharness-handoff "):
                    raise SystemExit("existing handoff binding malformed; inspect before migrating")
    binding = render_binding(item, args.target, previous=previous) if strict else ""

    body = f"""# Handoff Packet

## Subject

- Checklist item: `{item["id"]}`
- From: `{item.get("owner")}`
- To: `{args.target}`
- Requested by: `{args.actor}`
- Updated at: `{args.date or iso_z()}`
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

{render_plan_snapshot(read_text(plan_path))}

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

    if strict:
        write_bound_packet(item, checklist, packet_path, binding + body + "\n")
    else:
        write_text(packet_path, body + "\n")

    def callback(candidate: dict) -> None:
        item = require_item(candidate, args.item)
        if json.dumps(item, sort_keys=True) != original_item:
            raise SystemExit("task changed during handoff generation; retry from current task")
        workflow = ensure_workflow(item)
        artifacts = ensure_artifacts(item)
        artifacts["handoff_packet"] = rel(packet_path)
        if args.refresh:
            return
        workflow["status"] = "handoff_requested"
        workflow["handoff_from"] = previous_owner
        workflow["handoff_target"] = args.target
        workflow["updated_at"] = iso_z()
        release_lease(item)
        item["status"] = "todo"
        item["owner"] = None
        item["selected_in_session"] = None
        item["updated_at"] = iso_z()

    mutate_checklist(callback)

    if args.refresh:
        print(f"Refreshed handoff packet: {packet_path}")
        return 0

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
