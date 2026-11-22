"""Task-scoped handoff bindings for projects adopting consistency checks."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from harness_common import (
    atomic_write_bytes, fail, load_config, plan_snapshot, project_root, rel,
    resolve_item_plan, safe_item_id_problem,
)


PREFIX = "<!-- exharness-handoff "


def enabled(config=None):
    config = load_config() if config is None else config
    coverage = config.get("coverage")
    if coverage is None:
        return False
    from consistency_core import CoverageError, load_coverage
    try:
        parsed = load_coverage(config)
    except CoverageError as exc:
        # Disabled legacy projects keep existing workflow behavior. Explicit
        # consistency commands still report not-configured, never passed.
        if isinstance(coverage, dict) and coverage.get("enabled") is False:
            return False
        fail(f"handoff coverage configuration: {exc}")
    return parsed.get("handoff", True)


def packet_path(item):
    if safe_item_id_problem(item.get("id")):
        fail("handoff requires a safe task id")
    plan = resolve_item_plan(item, require_exists=True)
    return plan.parent / f"handoff-{item['id']}.md"


def write_bound_packet(item, checklist, path, body):
    """A derived packet may replace only its own earlier derived bytes."""
    protected = [resolve_item_plan(other, require_exists=False)
                 for other in checklist.get("items", [])]
    config = load_config()
    for group in config.get("coverage", {}).get("groups", []):
        locator = group.get("record", {}).get("path")
        if locator:
            protected.append(project_root() / locator)
    if any(path.resolve() == record.resolve() for record in protected):
        fail("handoff packet destination is a canonical record; choose a distinct task artifact")
    if path.is_symlink():
        fail("handoff packet destination must not be a symlink")
    data = body.encode("utf-8")
    if path.exists():
        try:
            previous = parse_binding(path.read_bytes())
        except (OSError, ValueError):
            fail("handoff destination contains unrelated content; preserve it and choose another task artifact")
        if previous.get("item") != item["id"]:
            fail("handoff destination belongs to another task")
        atomic_write_bytes(path, data)
    else:
        # Exclusive creation cannot truncate a file introduced after the check.
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())


def _binding(item, target, plan_bytes, plan_locator, snapshot, coverage):
    from consistency_core import scope_digest, source_excludes
    groups = []
    for group in coverage["groups"]:
        record = group["record"]
        if record.get("item") != item["id"] and record.get("path") != plan_locator:
            continue
        groups.append({"group": group["id"],
                       "scope_digest": scope_digest(group, coverage),
                       "source_digest": snapshot.digest(
                           group["sources"], source_excludes(group, coverage, plan_locator))})
    state = item.get("workflow", {}).get("status")
    if not groups and (item.get("status") == "doing" or state in {
        "running", "review_requested", "review_approved", "closeout_requested"
    }):
        fail("implementation handoff has no coverage group bound to this task; "
             "declare its existing record/item source scope first")
    entry = snapshot.entries.get(plan_locator)
    return {"version": 1, "item": item["id"], "target": target,
            "plan": plan_locator, "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "plan_object": entry.oid if entry else None,
            "sources": groups}


def render_binding(item, target, *, previous=None):
    from consistency_core import load_coverage
    from consistency_snapshot import GitRepo
    config = load_config()
    if config.get("deployment_profile", "standalone") != "standalone":
        fail("managed handoff must use the existing Coordinate lifecycle entry point")
    coverage = load_coverage(config)
    plan = resolve_item_plan(item, require_exists=True)
    binding = _binding(item, target, plan.read_bytes(), rel(plan),
                       GitRepo(project_root()).worktree(), coverage)
    if previous is not None:
        current = {g["group"]: g["scope_digest"] for g in binding["sources"]}
        for group in previous.get("sources", []):
            if current.get(group.get("group")) != group.get("scope_digest"):
                fail("handoff refresh cannot remove or redefine its original source scope; "
                     "review the scope migration before issuing a new handoff")
    return PREFIX + json.dumps(binding, ensure_ascii=False, sort_keys=True) + " -->\n\n"


def parse_binding(data):
    text = data.decode("utf-8")
    if not text.startswith(PREFIX):
        raise ValueError("legacy/unbound handoff; refresh this task's packet")
    line = text.splitlines()[0]
    if not line.endswith(" -->") or text.count(PREFIX) != 1:
        raise ValueError("malformed or duplicate handoff binding")
    binding = json.loads(line[len(PREFIX):-len(" -->")])
    if not isinstance(binding, dict) or binding.get("version") != 1:
        raise ValueError("unsupported handoff binding")
    return binding


def binding_problems(item, target, binding, expected):
    problems = []
    for key in ("version", "item", "target", "plan", "sources"):
        if binding.get(key) != expected.get(key):
            problems.append(f"handoff {key} differs from the current task/target/plan/source")
    same_bytes = binding.get("plan_sha256") == expected.get("plan_sha256")
    same_object = binding.get("plan_object") and binding["plan_object"] == expected.get("plan_object")
    if not same_bytes and not same_object:
        problems.append("handoff plan_sha256 differs from the selected canonical plan")
    if item.get("workflow", {}).get("handoff_target") != target:
        problems.append("handoff target does not match the accepting owner")
    return problems


def body_problems(raw, plan_bytes):
    rendered = plan_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").rstrip()
    if plan_snapshot(raw.decode("utf-8")) != rendered:
        return ["handoff canonical plan snapshot differs from its bound source bytes"]
    return []


def accept_problems(item, owner):
    if not enabled() or item.get("workflow", {}).get("status") != "handoff_requested":
        return []
    from consistency_core import load_coverage
    from consistency_snapshot import GitRepo, SnapshotError
    if load_config().get("deployment_profile", "standalone") != "standalone":
        return ["managed handoff acceptance must use the existing Coordinate lifecycle entry point"]
    raw = item.get("artifacts", {}).get("handoff_packet")
    if not isinstance(raw, str) or not raw or ".." in Path(raw).parts:
        return ["handoff packet locator is missing/invalid; refresh this task's packet"]
    path = Path(raw) if Path(raw).is_absolute() else project_root() / raw
    try:
        raw = path.read_bytes()
        binding = parse_binding(raw)
        plan = resolve_item_plan(item, require_exists=True)
        plan_bytes = plan.read_bytes()
        expected = _binding(item, owner, plan_bytes, rel(plan),
                            GitRepo(project_root()).worktree(), load_coverage(load_config()))
        return binding_problems(item, owner, binding, expected) + body_problems(raw, plan_bytes)
    except (OSError, ValueError, UnicodeError, SnapshotError) as exc:
        return [f"handoff binding unavailable: {exc}; refresh or decline the handoff"]


def snapshot_problems(snapshot, checklist, coverage, harness_path, resolve_record, resolve_artifact=None):
    """Read the selected objects, never the checkout, during staged/CI lint.

    resolve_record(item) returns (canonical locator, exact bytes) using the
    caller's selected snapshot/external-evidence policy.
    """
    problems = []
    for item in checklist.get("items", []):
        workflow = item.get("workflow", {})
        if workflow.get("status") != "handoff_requested":
            continue
        path = item.get("artifacts", {}).get("handoff_packet", "")
        try:
            if not path or ".." in Path(path).parts:
                raise ValueError("handoff packet is not available in selected repository snapshot")
            raw = resolve_artifact(path) if resolve_artifact else snapshot.read(path)
            if raw is None:
                raise ValueError("handoff packet missing from selected snapshot")
            binding = parse_binding(raw)
            locator, data = resolve_record(item)
            expected = _binding(item, workflow.get("handoff_target"), data, locator, snapshot, coverage)
            for message in binding_problems(item, workflow.get("handoff_target"), binding, expected) + body_problems(raw, data):
                problems.append(("handoff-stale", "error", item["id"], path, message))
        except (OSError, ValueError, UnicodeError) as exc:
            problems.append(("handoff-unavailable", "incomplete", item.get("id"), path, str(exc)))
    return problems
