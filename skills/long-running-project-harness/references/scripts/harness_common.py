#!/usr/bin/env python3
"""Shared helpers for the long-running project harness runtime templates."""
from __future__ import annotations

import hashlib
import errno
import json
import os
import re
import stat as stat_module
import sys
import tempfile
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from validate_checklist import validate_checklist


DEFAULT_LEASE_TTL_MINUTES = 120

CHECKLIST_NEW_NAME = "harness-checklist.json"
CHECKLIST_LEGACY_NAME = "mvp-checklist.json"
ALLOWED_DEPLOYMENT_PROFILES = {"standalone", "coordinate-managed"}

# errno values that unambiguously mean "this platform cannot open/fsync a
# directory fd". Ordinary I/O errors (EACCES, EIO, EBADF, ENOENT, ...) must
# NOT be treated as unsupported: they propagate.
_DIR_FSYNC_UNSUPPORTED_ERRNOS = frozenset(
    candidate
    for candidate in (
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "EINVAL", None),
    )
    if candidate is not None
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[{{PROJECT_ROOT_DEPTH}}]


def harness_root() -> Path:
    return project_root() / "{{HARNESS_ROOT}}"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(project_root()))
    except ValueError:
        return str(path)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def today() -> str:
    return utc_now().date().isoformat()


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ResolvedChecklist:
    """The single active checklist file for a given purpose.

    Only carries the actual path and whether it is the new or legacy
    filename. It is not a new persistent entity.
    """

    path: Path
    kind: Literal["new", "legacy"]


def checklist_candidates() -> dict[str, Path]:
    """Both possible checklist filenames; used by doctor for diagnosis only."""
    return {
        "new": harness_root() / CHECKLIST_NEW_NAME,
        "legacy": harness_root() / CHECKLIST_LEGACY_NAME,
    }


def resolve_checklist(*, purpose: str) -> ResolvedChecklist:
    """Resolve the single active checklist file.

    purpose semantics:
      read/mutation : new-only -> new, legacy-only -> legacy, none/both fail closed
      migrate       : legacy-only -> legacy (candidate for rename); anything else fails
    """
    if purpose not in {"read", "mutation", "migrate"}:
        raise ValueError(f"unknown checklist purpose: {purpose!r}")
    candidates = checklist_candidates()
    has_new = candidates["new"].is_file()
    has_legacy = candidates["legacy"].is_file()

    if has_new and has_legacy:
        fail(
            f"dual checklist authority: both {CHECKLIST_NEW_NAME} and "
            f"{CHECKLIST_LEGACY_NAME} exist; refusing to pick either. "
            "Manually compare both files and keep exactly one authority "
            "(delete or move the superseded file). Only after the legacy file "
            "is the sole remaining checklist may you run migrate-checklist "
            "to rename it."
        )
    if purpose == "migrate":
        if has_new:
            fail(
                f"cannot migrate: {CHECKLIST_NEW_NAME} already exists; "
                "migration only accepts a legacy-only checklist."
            )
        if not has_legacy:
            fail(f"cannot migrate: {CHECKLIST_LEGACY_NAME} does not exist.")
        return ResolvedChecklist(candidates["legacy"], "legacy")
    if has_new:
        return ResolvedChecklist(candidates["new"], "new")
    if has_legacy:
        return ResolvedChecklist(candidates["legacy"], "legacy")
    fail(
        f"no checklist found: neither {CHECKLIST_NEW_NAME} nor "
        f"{CHECKLIST_LEGACY_NAME} exists. Initialize the harness first."
    )


def checklist_path() -> Path:
    """Thin proxy over the resolver; never hardcodes a filename."""
    return resolve_checklist(purpose="read").path


def load_checklist() -> dict[str, Any]:
    return read_json(resolve_checklist(purpose="read").path)


def deployment_profile(config: dict[str, Any] | None = None) -> str:
    cfg = config if config is not None else load_config()
    profile = cfg.get("deployment_profile", "standalone")
    if not isinstance(profile, str) or profile not in ALLOWED_DEPLOYMENT_PROFILES:
        fail(
            f"invalid deployment_profile {profile!r}; must be one of "
            f"{sorted(ALLOWED_DEPLOYMENT_PROFILES)}"
        )
    return profile


def require_standalone_mutation(config: dict[str, Any] | None = None) -> None:
    """Bare add/update-item mutations fail closed under coordinate-managed."""
    if deployment_profile(config) != "standalone":
        fail(
            "add-item/update-item are disabled under "
            "deployment_profile=coordinate-managed; register or update "
            "checklist items through the Coordinate entry point."
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(directory: Path) -> None:
    """Fsync a directory so a rename is durable.

    Both the open and the fsync stage apply the same policy: errno values
    that mean "directory fds are unsupported on this platform" hit the
    controlled fallback; ordinary I/O errors (EACCES, EIO, ...) propagate.
    The directory fd is always closed.
    """
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        if exc.errno in _DIR_FSYNC_UNSUPPORTED_ERRNOS or (
            os.name == "nt" and exc.errno == errno.EACCES
        ):
            return  # controlled fallback: platform cannot open a directory fd
        raise
    try:
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            if exc.errno in _DIR_FSYNC_UNSUPPORTED_ERRNOS:
                return  # controlled fallback: platform cannot fsync a dir fd
            raise
    finally:
        os.close(dir_fd)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Crash-safe single-writer write: unique temp, flush+fsync, mode
    preserved, os.replace, parent fsync, temp cleanup on failure.

    Before the commit point (os.replace) any failure leaves the original
    bytes untouched.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    if mode is None and path.exists():
        mode = stat_module.S_IMODE(path.stat().st_mode)
    fd: int | None = None
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(directory)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(data)
            handle.flush()
            if mode is not None:
                # Apply mode before fsync so a single fsync covers data and
                # mode metadata (no second fsync needed).
                os.chmod(tmp_path, mode)
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
        _fsync_dir(directory)
    finally:
        if fd is not None:
            os.close(fd)
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def atomic_write_json(path: Path, data: Any) -> None:
    """Atomic JSON writer for derived state (not checklist authority)."""
    body = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    atomic_write_bytes(path, body.encode("utf-8"))


def mutate_checklist(
    callback: Any, *, purpose: str = "mutation"
) -> dict[str, Any]:
    """Single mutation pipeline: resolve -> read -> validate current ->
    deepcopy -> callback -> update updated_at -> validate candidate ->
    atomic write. Any failure before the commit point leaves the original
    bytes untouched.
    """
    resolved = resolve_checklist(purpose=purpose)
    original_bytes = resolved.path.read_bytes()
    try:
        current = json.loads(original_bytes)
    except json.JSONDecodeError as exc:
        fail(f"checklist {resolved.path} is not valid JSON: {exc}")
    if not isinstance(current, dict):
        fail(f"checklist {resolved.path} root must be a JSON object")

    errors, _ = validate_checklist(current)
    if errors:
        fail(
            f"current checklist is invalid; refusing to mutate: {resolved.path}\n"
            + "\n".join(f"  - {error}" for error in errors[:8])
        )

    candidate = deepcopy(current)
    callback(candidate)
    candidate["updated_at"] = today()

    errors, _ = validate_checklist(candidate)
    if errors:
        fail(
            f"candidate checklist is invalid after mutation; nothing written:\n"
            + "\n".join(f"  - {error}" for error in errors[:8])
        )
    locator_problems = checklist_runtime_problems(candidate)
    if locator_problems:
        fail(
            "candidate checklist has runtime authority problems; nothing written:\n"
            + "\n".join(f"  - {problem}" for problem in locator_problems)
        )

    mode = (
        stat_module.S_IMODE(resolved.path.stat().st_mode)
        if resolved.path.exists()
        else None
    )
    body = json.dumps(candidate, indent=2, ensure_ascii=False) + "\n"
    atomic_write_bytes(resolved.path, body.encode("utf-8"), mode=mode)
    return candidate


def safe_item_id_problem(item_id: Any) -> str | None:
    """Minimal shared safe item id rule.

    A safe id is a non-empty (not whitespace-only) string that is a single
    safe path component: no path separators, not exactly '.' or '..', and
    no Unicode C* characters (control/format/surrogate/private-use, e.g.
    newline or bidi controls). Normal visible Unicode (CJK, kana, emoji,
    accented letters) is allowed as a path component.
    """
    if not isinstance(item_id, str):
        return f"item id must be a string, got {type(item_id).__name__}"
    if not item_id.strip():
        return "item id must be a non-empty string"
    if item_id in (".", ".."):
        return f"item id {item_id!r} is not a safe path component"
    if "/" in item_id or "\\" in item_id:
        return f"item id {item_id!r} contains a path separator"
    for char in item_id:
        if unicodedata.category(char).startswith("C"):
            return (
                f"item id {item_id!r} contains a control/format/surrogate "
                f"character (U+{ord(char):04X})"
            )
    return None


def item_locator_type_problems(item: dict[str, Any]) -> list[str]:
    """plan_path / artifacts.plan must be absent, null, or a string.

    A present non-string field (list/int/object/bool) is a problem, never
    silently treated as an absent locator. Blank strings are treated as no
    locator by item_plan_locator_fields, which is allowed.
    """
    problems: list[str] = []
    label = f"item {item.get('id')!r}"
    plan_path = item.get("plan_path")
    if plan_path is not None and not isinstance(plan_path, str):
        problems.append(
            f"{label} plan_path must be a string or null, got {type(plan_path).__name__}"
        )
    artifacts = item.get("artifacts")
    if isinstance(artifacts, dict) and "plan" in artifacts:
        artifacts_plan = artifacts["plan"]
        if artifacts_plan is not None and not isinstance(artifacts_plan, str):
            problems.append(
                f"{label} artifacts.plan must be a string or null, "
                f"got {type(artifacts_plan).__name__}"
            )
    return problems


def item_plan_locator_fields(item: dict[str, Any]) -> list[tuple[str, str]]:
    """Non-empty plan_path / artifacts.plan locators on an item."""
    fields: list[tuple[str, str]] = []
    for key, value in (
        ("plan_path", item.get("plan_path")),
        ("artifacts.plan", (item.get("artifacts") or {}).get("plan")),
    ):
        if isinstance(value, str) and value.strip():
            fields.append((key, value.strip()))
    return fields


def item_has_plan_locator(item: dict[str, Any]) -> bool:
    return bool(item_plan_locator_fields(item))


def checklist_runtime_problems(checklist: dict[str, Any]) -> list[str]:
    """Shared runtime authority check for every checklist item.

    Covers: safe item ids (single safe path component), locator field
    types (plan_path / artifacts.plan must be string-or-null), lexical '..'
    in every locator, and dual-locator conflicts. Used by mutation, state
    derivation and harnessctl validate; project-context rules live here
    (harness_common), never in the canonical schema validator. A repair via
    update-item --plan happens inside the mutation callback, so this
    precheck never locks the repair path.
    """
    problems: list[str] = []
    for item in checklist.get("items", []):
        if not isinstance(item, dict):
            continue
        id_problem = safe_item_id_problem(item.get("id"))
        if id_problem:
            problems.append(id_problem)
        problems.extend(item_locator_type_problems(item))
        fields = item_plan_locator_fields(item)
        norms: set[str] = set()
        for key, raw in fields:
            path = Path(raw)
            if ".." in path.parts:
                problems.append(
                    f"item {item.get('id')!r} {key} locator contains '..': {raw!r}"
                )
                continue
            resolved = path if path.is_absolute() else project_root() / path
            norms.add(os.path.normpath(str(resolved)))
        if len(norms) > 1:
            details = "; ".join(f"{key}={raw!r}" for key, raw in fields)
            problems.append(
                f"item {item.get('id')!r} has conflicting plan locators: {details}"
            )
    return problems


def _interpret_plan_locator(key: str, raw: str) -> Path:
    path = Path(raw)
    if ".." in path.parts:
        fail(f"{key} locator must not contain '..': {raw!r}")
    if path.is_absolute():
        return path
    return project_root() / path


def resolve_item_plan(item: dict[str, Any], *, require_exists: bool) -> Path:
    """Single semantic answer for an item's canonical plan.

    Rules: non-empty plan_path / artifacts.plan are read; fields that exist
    with a non-string type fail closed instead of being treated as absent;
    if both locators exist and normalize differently the call fails closed;
    with neither, the default <harness_root>/tasks/<id>/plan.md is used
    (guarded by the shared safe item id rule before any mkdir/write).
    Relative locators resolve against project root; absolute locators are
    allowed for operator-chosen external task artifact roots in Standalone
    (lexical/regular-file checks only, not containment security).
    """
    type_problems = item_locator_type_problems(item)
    if type_problems:
        fail("; ".join(type_problems))
    fields = item_plan_locator_fields(item)
    resolved: list[tuple[str, Path]] = [
        (key, _interpret_plan_locator(key, raw)) for key, raw in fields
    ]

    unique: dict[str, tuple[str, Path]] = {}
    for key, path in resolved:
        unique.setdefault(os.path.normpath(str(path)), (key, path))
    if len(unique) > 1:
        details = "; ".join(f"{key}={raw!r}" for key, raw in fields)
        fail(
            f"conflicting plan locators on item {item.get('id')!r}: {details}. "
            "Keep only one of plan_path / artifacts.plan, or make them equal."
        )

    if unique:
        path = next(iter(unique.values()))[1]
    else:
        item_id = item.get("id")
        id_problem = safe_item_id_problem(item_id)
        if id_problem:
            fail(f"cannot resolve default plan: {id_problem}")
        path = harness_root() / "tasks" / str(item_id) / "plan.md"

    if require_exists and not (path.is_file() and os.access(path, os.R_OK)):
        fail(f"plan file not found or not readable: {path}")
    return path


def config_path() -> Path:
    return harness_root() / "harness-config.json"


def default_config() -> dict[str, Any]:
    return {
        "deployment_profile": "standalone",
        "commands": {},
        "runtime": {
            "session_init_commands": ["typecheck", "test"],
            "lease_ttl_minutes": DEFAULT_LEASE_TTL_MINUTES,
        },
        "git": {
            "base_branch": "main",
            "branch_namespace": "agent/{owner}/{item_id}",
        },
        "message_bus": {
            "event_log": "{{HARNESS_ROOT}}/events.jsonl",
            "visible_bus": "discord-or-kook",
        },
    }


def load_config() -> dict[str, Any]:
    """Load harness-config.json.

    A missing file, or an object without deployment_profile, stays on the
    standalone default. A present-but-malformed file (invalid JSON or a
    non-object root) fails loud instead of silently downgrading to
    standalone.
    """
    config = default_config()
    config_file = config_path()
    if not config_file.exists():
        return config
    try:
        user_config = json.loads(config_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        fail(f"harness-config.json is not valid JSON: {exc}")
    if not isinstance(user_config, dict):
        fail("harness-config.json root must be a JSON object")
    for key, value in user_config.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def configured_commands(config: dict[str, Any] | None = None) -> dict[str, str]:
    raw = (config or load_config()).get("commands", {})
    if not isinstance(raw, dict):
        return {}
    commands: dict[str, str] = {}
    for name, command in raw.items():
        if isinstance(command, str) and command.strip():
            commands[name] = command.strip()
    return commands


def event_log_path(config: dict[str, Any] | None = None) -> Path:
    message_bus = (config or load_config()).get("message_bus", {})
    configured = "{{HARNESS_ROOT}}/events.jsonl"
    if isinstance(message_bus, dict) and isinstance(message_bus.get("event_log"), str):
        configured = message_bus["event_log"]
    return project_root() / configured


def find_item(checklist: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    return next((entry for entry in checklist.get("items", []) if entry.get("id") == item_id), None)


def require_item(checklist: dict[str, Any], item_id: str) -> dict[str, Any]:
    item = find_item(checklist, item_id)
    if item is None:
        raise SystemExit(f"Checklist item not found: {item_id}")
    return item


def default_workflow_status(item: dict[str, Any]) -> str:
    status = item.get("status")
    if status == "doing":
        return "running"
    if status == "done":
        return "closed"
    if status == "blocked":
        return "blocked"
    return "todo"


def ensure_workflow(item: dict[str, Any]) -> dict[str, Any]:
    workflow = item.get("workflow")
    if not isinstance(workflow, dict):
        workflow = {}
        item["workflow"] = workflow
    workflow.setdefault("status", default_workflow_status(item))
    workflow.setdefault("updated_at", iso_z())
    return workflow


def ensure_artifacts(item: dict[str, Any]) -> dict[str, Any]:
    artifacts = item.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
        item["artifacts"] = artifacts
    return artifacts


def ensure_review(item: dict[str, Any]) -> dict[str, Any]:
    review = item.get("review")
    if not isinstance(review, dict):
        review = {}
        item["review"] = review
    review.setdefault("decision", None)
    return review


def active_lease(item: dict[str, Any], now: datetime | None = None) -> dict[str, Any] | None:
    lease = item.get("lease")
    if not isinstance(lease, dict):
        return None
    if lease.get("released_at"):
        return None
    expires_at = parse_time(lease.get("expires_at"))
    if expires_at is None:
        return lease
    if expires_at > (now or utc_now()):
        return lease
    return None


def lease_is_expired(item: dict[str, Any], now: datetime | None = None) -> bool:
    lease = item.get("lease")
    if not isinstance(lease, dict) or lease.get("released_at"):
        return False
    expires_at = parse_time(lease.get("expires_at"))
    return expires_at is not None and expires_at <= (now or utc_now())


def claim_lease(item: dict[str, Any], owner: str, session: str, ttl_minutes: int | None = None) -> dict[str, Any]:
    configured_ttl = load_config().get("runtime", {}).get("lease_ttl_minutes", DEFAULT_LEASE_TTL_MINUTES)
    try:
        ttl = int(ttl_minutes or configured_ttl or DEFAULT_LEASE_TTL_MINUTES)
    except (TypeError, ValueError):
        ttl = DEFAULT_LEASE_TTL_MINUTES
    acquired = utc_now()
    lease = {
        "owner": owner,
        "session": session,
        "acquired_at": iso_z(acquired),
        "expires_at": iso_z(acquired + timedelta(minutes=ttl)),
        "ttl_minutes": ttl,
    }
    item["lease"] = lease
    return lease


def release_lease(item: dict[str, Any]) -> None:
    lease = item.get("lease")
    if isinstance(lease, dict) and not lease.get("released_at"):
        lease["released_at"] = iso_z()
    item["lease"] = lease if isinstance(lease, dict) else None


def current_task_pointer_path() -> Path:
    return harness_root() / "current" / "task_plan.md"


def current_task_item_id() -> str | None:
    text = read_text(current_task_pointer_path())
    match = re.search(r"- Checklist item: `([^`]+)`", text)
    return match.group(1).strip() if match else None


def clear_current_pointer(item_id: str, reason: str) -> None:
    pointer_path = current_task_pointer_path()
    if current_task_item_id() != item_id:
        return
    body = f"""# Current Task Pointer

- Checklist item: null
- Status: none
- Cleared at: {iso_z()}
- Reason: {reason}

> No active task is currently selected. Use harnessctl state or assign/start a new item.
"""
    write_text(pointer_path, body)


def unfinished_dependencies(checklist: dict[str, Any], item: dict[str, Any]) -> list[str]:
    items_by_id = {entry.get("id"): entry for entry in checklist.get("items", [])}
    missing: list[str] = []
    for dep_id in item.get("dependencies", []):
        dep = items_by_id.get(dep_id)
        if not dep or dep.get("status") != "done":
            missing.append(dep_id)
    return missing


def branch_for(owner: str, item_id: str, config: dict[str, Any] | None = None) -> str:
    namespace = (config or load_config()).get("git", {}).get(
        "branch_namespace", "agent/{owner}/{item_id}"
    )
    if not isinstance(namespace, str) or not namespace.strip():
        namespace = "agent/{owner}/{item_id}"
    return namespace.format(owner=owner, item_id=item_id)


def append_event(
    event_type: str,
    *,
    task: str | None = None,
    actor: str | None = None,
    target: str | None = None,
    status: str | None = None,
    parent: str | None = None,
    branch: str | None = None,
    pr: str | None = None,
    artifacts: list[str] | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or []
    event = {
        "schema_version": 1,
        "id": event_id or f"evt-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
        "type": event_type,
        "created_at": iso_z(),
        "idempotency_key": f"{event_type}:{task or 'none'}:{status or 'none'}:{actor or 'none'}",
        "causation_id": parent,
        "task": task,
        "actor": actor,
        "target": target,
        "status": status,
        "parent": parent,
        "branch": branch,
        "pr": pr,
        "artifacts": artifacts,
        "summary": summary,
        "metadata": metadata or {},
        "visible_header": None,
        "publish_status": "local_only",
    }
    event["visible_header"] = format_event_header(event)
    path = event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    print(event["visible_header"])
    return event


def format_event_header(event: dict[str, Any]) -> str:
    parts = [
        f"id={event.get('id')}",
        f"task={event.get('task')}",
        f"actor={event.get('actor')}",
    ]
    if event.get("target"):
        parts.append(f"target={event.get('target')}")
    if event.get("status"):
        parts.append(f"status={event.get('status')}")
    if event.get("branch"):
        parts.append(f"branch={event.get('branch')}")
    if event.get("pr"):
        parts.append(f"pr={event.get('pr')}")
    artifacts = event.get("artifacts") or []
    if artifacts:
        parts.append("artifacts=" + ",".join(artifacts))
    return f"[{event.get('type')}] " + " ".join(parts)


def require_force_reason(force: bool, reason: str | None) -> None:
    if force and not (reason or "").strip():
        raise SystemExit("--force requires --reason so the override is auditable")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Shared harness runtime helpers.")
    parser.add_argument(
        "--resolved-checklist",
        action="store_true",
        help="Print the resolved active checklist path (empty + exit 1 on none/dual).",
    )
    parser.add_argument(
        "--check-locators",
        metavar="PATH",
        help="Run the shared runtime locator authority check on a checklist file.",
    )
    parser.add_argument(
        "--doctor-doing-plan",
        metavar="PATH",
        help=(
            "Print the unique doing item's canonical plan for doctor: NONE "
            "(no doing item), AMBIGUOUS (several), or two lines <item-id> "
            "and <resolved plan path>. Fails loud on unreadable checklist "
            "or unresolvable plan locators."
        ),
    )
    args = parser.parse_args()
    if args.resolved_checklist:
        try:
            resolved = resolve_checklist(purpose="read")
        except SystemExit:
            return 1
        print(resolved.path)
        return 0
    if args.check_locators:
        try:
            with open(args.check_locators, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: could not read checklist: {exc}", file=sys.stderr)
            return 2
        problems = checklist_runtime_problems(data)
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1 if problems else 0
    if args.doctor_doing_plan:
        try:
            with open(args.doctor_doing_plan, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: could not read checklist: {exc}", file=sys.stderr)
            return 2
        doing = [
            item
            for item in data.get("items", [])
            if isinstance(item, dict) and item.get("status") == "doing"
        ]
        if not doing:
            print("NONE")
            return 0
        if len(doing) > 1:
            print("AMBIGUOUS")
            return 0
        try:
            plan_path = resolve_item_plan(doing[0], require_exists=False)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
        print(doing[0].get("id"))
        print(plan_path)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
