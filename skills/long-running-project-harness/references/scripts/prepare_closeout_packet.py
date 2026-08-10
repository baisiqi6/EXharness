#!/usr/bin/env python3
"""Prepare a closeout packet for a checklist item.

Closeout requests do not mark the item done. They move workflow status to
closeout_requested and require reviewer approval before `mark-done`.
"""
from __future__ import annotations

import argparse

from harness_common import (
    append_event,
    harness_root,
    load_checklist,
    mutate_checklist,
    read_text,
    rel,
    require_item,
    resolve_item_plan,
    today,
    ensure_artifacts,
    ensure_review,
    ensure_workflow,
    write_text,
)


def tail_session_log(progress_text: str, limit: int = 3) -> str:
    headings = [idx for idx, line in enumerate(progress_text.splitlines()) if line.startswith("### ")]
    if not headings:
        return progress_text.strip()

    lines = progress_text.splitlines()
    starts = headings[-limit:]
    chunks: list[str] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(lines)
        chunks.append("\n".join(lines[start:end]).rstrip())
    return "\n\n".join(chunks).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a closeout packet for a checklist item.")
    parser.add_argument("--item", required=True, help="Checklist item id, e.g. mvp-003")
    parser.add_argument("--reviewer", default="TBD", help="Reviewer label")
    parser.add_argument("--date", default=today(), help="ISO date override")
    args = parser.parse_args()

    root = harness_root()
    checklist = load_checklist()
    item = require_item(checklist, args.item)
    workflow = ensure_workflow(item)

    plan_path = resolve_item_plan(item, require_exists=True)
    progress_path = root / "progress.md"
    review_path = root / "current" / "review.md"
    packet_path = root / "current" / "closeout-packet.md"

    progress_text = read_text(progress_path)
    recent_progress = tail_session_log(progress_text)

    body = f"""# Closeout Packet

## Subject

- Checklist item: `{item["id"]}`
- Reviewer: `{args.reviewer}`
- Updated at: `{args.date}`
- Canonical plan path: `{rel(plan_path)}`

## Item Snapshot

- Title: {item["title"]}
- Status: {item["status"]}
- Workflow status: closeout_requested
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

## Recent Progress Context

```md
{recent_progress}
```

## Current Review Content

```md
{read_text(review_path).rstrip()}
```

## Closeout Questions

1. 当前实现是否已经覆盖 acceptance
2. verification 是否足以支持从 `doing` 进入 `done`
3. 还有没有阻止 closeout 的高优先级问题
4. 如果不能 done，最关键的剩余工作是什么
"""

    write_text(packet_path, body.rstrip() + "\n")

    def callback(candidate: dict) -> None:
        item = require_item(candidate, args.item)
        workflow = ensure_workflow(item)
        artifacts = ensure_artifacts(item)
        review = ensure_review(item)
        artifacts["closeout_packet"] = rel(packet_path)
        workflow["status"] = "closeout_requested"
        workflow["updated_at"] = today()
        review["decision"] = None
        review["reviewer"] = args.reviewer
        item["updated_at"] = today()

    mutate_checklist(callback)

    append_event(
        "RESULT",
        task=args.item,
        actor=item.get("owner") or "operator",
        target=args.reviewer,
        status="closeout_requested",
        artifacts=[rel(packet_path)],
        summary=f"Closeout requested for {args.item}",
    )
    print(f"Wrote closeout packet: {packet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
