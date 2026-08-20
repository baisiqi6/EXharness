#!/usr/bin/env python3
"""Sync current/task_plan.md from a canonical item plan.

Extracts key sections from the canonical plan and writes a
summary pointer to current/task_plan.md.
"""
from __future__ import annotations

import argparse

from harness_common import (
    current_task_pointer_path,
    iso_z,
    load_checklist,
    read_text,
    rel,
    render_freshness_metadata,
    require_item,
    resolve_item_plan,
    sha256_bytes,
)


def extract_section(text: str, heading: str, next_heading: str | None = None) -> str:
    lines = text.splitlines()
    start = None
    end = None

    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break

    if start is None:
        return ""

    if next_heading is not None:
        for i in range(start, len(lines)):
            if lines[i].strip() == next_heading:
                end = i
                break

    chunk = lines[start:end] if end is not None else lines[start:]
    return "\n".join(chunk).strip()


def extract_bullets(section_text: str, limit: int = 3) -> list[str]:
    bullets: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
        elif stripped.startswith(("1. ", "2. ", "3. ", "4. ", "5. ")):
            bullets.append(stripped[3:].strip())
        if len(bullets) >= limit:
            break
    return bullets


def compact_paragraph(section_text: str) -> str:
    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    return " ".join(lines)


def build_current_pointer(
    item: dict,
    canonical_rel_path: str,
    goal: str,
    in_scope: list[str],
    steps: list[str],
    exit_criteria: list[str],
    source_plan_sha256: str,
) -> str:
    scope_lines = "\n".join(f"- {entry}" for entry in in_scope) if in_scope else "- (from canonical plan)"
    step_lines = "\n".join(f"- {entry}" for entry in steps) if steps else "- (from canonical plan)"
    exit_lines = "\n".join(f"- {entry}" for entry in exit_criteria) if exit_criteria else "- (from canonical plan)"

    metadata = render_freshness_metadata(
        {
            "generated_at": iso_z(),
            "source_plan_sha256": source_plan_sha256,
            "canonical_plan_path": canonical_rel_path,
            "checklist_item": item["id"],
        }
    )

    return f"""# Active Task Plan Pointer

{metadata}## Current Item

- Checklist item: `{item["id"]}`
- Title: `{item["title"]}`
- Owner: `{item["owner"]}`
- Session: `{item["selected_in_session"]}`
- Status: `{item["status"]}`
- Workflow: `{(item.get('workflow') or {}).get('status', 'legacy')}`
- Updated at: `{item["updated_at"]}`

## Canonical Plan

- Active plan path: `{canonical_rel_path}`

## Goal Summary

{goal or "(from canonical plan)"}

## In Scope Summary

{scope_lines}

## Current Step Hints

{step_lines}

## Exit Criteria Summary

{exit_lines}

## Notes

- Canonical plan lives at `{canonical_rel_path}`
- This file is a pointer/summary, not the full plan
- Re-run sync after significant canonical plan changes
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync current/task_plan.md from a canonical item plan.")
    parser.add_argument("--item", required=True, help="Checklist item id, e.g. mvp-003")
    args = parser.parse_args()

    checklist = load_checklist()
    item = require_item(checklist, args.item)

    plan_path = resolve_item_plan(item, require_exists=True)
    if not plan_path.is_file():
        raise SystemExit(f"Canonical plan not found: {plan_path}")

    text = read_text(plan_path)
    goal = compact_paragraph(extract_section(text, "## Goal", "## In Scope"))
    in_scope = extract_bullets(extract_section(text, "## In Scope", "## Out Of Scope"), limit=4)
    steps = extract_bullets(extract_section(text, "## Steps", "## Verification"), limit=4)
    exit_criteria = extract_bullets(extract_section(text, "## Exit Criteria", "## Handoff"), limit=4)

    current_path = current_task_pointer_path()
    current_path.parent.mkdir(parents=True, exist_ok=True)
    body = build_current_pointer(
        item=item,
        canonical_rel_path=rel(plan_path),
        goal=goal,
        in_scope=in_scope,
        steps=steps,
        exit_criteria=exit_criteria,
        source_plan_sha256=sha256_bytes(plan_path.read_bytes()),
    )
    current_path.write_text(body, encoding="utf-8")

    print(f"Synced current task pointer from {plan_path}")
    print(f"- current pointer: {current_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
