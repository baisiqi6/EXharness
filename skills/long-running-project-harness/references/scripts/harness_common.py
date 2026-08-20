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
WORKFLOW_MODES = {"ordinary", "high-risk"}

# Derived-artifact freshness contract (issue #7): verdict packets and the
# current pointer carry this fixed metadata section at the top, before the
# first fenced plan snapshot. The verifier only ever parses that bounded
# section; a canonical plan body that happens to contain a lookalike header
# inside its snapshot must not change the result.
FRESHNESS_HEADING = "## Freshness Metadata"
FRESHNESS_FIELDS = (
    "generated_at",
    "source_plan_sha256",
    "canonical_plan_path",
    "checklist_item",
)

# Verdict packet plan section (issue #9): high-risk embeds the full plan
# snapshot; ordinary omits the plan body and points at the canonical
# locator. Both review and closeout packets must share this single helper.
PLAN_SECTION_HEADING = "## Canonical Plan Content"

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


def render_freshness_metadata(metadata: dict[str, str]) -> str:
    """Deterministic freshness block (D1) for packet/pointer generators.

    Callers place it at the artifact top, before the first fenced plan
    snapshot, and must supply every FRESHNESS_FIELDS key.
    """
    lines = [FRESHNESS_HEADING, ""]
    for field in FRESHNESS_FIELDS:
        lines.append(f"- {field}: `{metadata[field]}`")
    return "\n".join(lines) + "\n"


def parse_freshness_metadata(text: str) -> tuple[dict[str, str], list[str]]:
    """Bounded parse of the fixed `## Freshness Metadata` section.

    Only the region before the first fenced code block is scanned, so a
    canonical plan body containing a fake freshness header inside its
    snapshot cannot change the result. Returns (metadata, duplicate_keys);
    a repeated key is reported instead of silently last-winning, so verdicts
    fail closed and validate can warn. Callers must require all four
    FRESHNESS_FIELDS.
    """
    prefix = text
    fence = re.search(r"^```", text, re.MULTILINE)
    if fence is not None:
        prefix = text[: fence.start()]
    metadata: dict[str, str] = {}
    duplicate_keys: list[str] = []
    lines = prefix.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != FRESHNESS_HEADING:
            continue
        for entry in lines[index + 1 :]:
            stripped = entry.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("```"):
                break
            match = re.match(r"^- ([A-Za-z0-9_]+): `(.*)`$", stripped)
            if match is None:
                break
            key = match.group(1)
            if key in metadata:
                duplicate_keys.append(key)
            else:
                metadata[key] = match.group(2)
        break
    return metadata, duplicate_keys


def render_plan_snapshot(plan_text: str) -> str:
    """Deterministic plan snapshot framing for verdict packets (addendum 1).

    The fence is one backtick longer than the longest consecutive backtick
    run in the rendered plan, so a plan containing its own ``` fences can
    never break the snapshot framing; the render keeps the established
    `rstrip()` semantics of the packet generators.
    """
    rendered = plan_text.rstrip()
    max_run = 0
    run = 0
    for char in rendered:
        if char == "`":
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    fence = "`" * max(3, max_run + 1)
    return f"{fence}md\n{rendered}\n{fence}"


def render_packet_plan_section(item: dict[str, Any], plan_text: str) -> str:
    """Shared verdict-packet plan section (issue #9): high-risk embeds the
    deterministic full snapshot; ordinary deliberately omits the plan body
    and points the reviewer at the canonical plan (metadata carries the
    locator). The packet always states the effective mode separately."""
    if effective_workflow_mode(item) == "ordinary":
        return (
            f"{PLAN_SECTION_HEADING}\n\n"
            "plan body omitted (workflow.mode=ordinary); read the canonical "
            "plan at the locator above before reviewing.\n"
        )
    return f"{PLAN_SECTION_HEADING}\n\n{render_plan_snapshot(plan_text)}"


# Sentinel returned by plan_snapshot for an ambiguous canonical-plan
# section: more than one ## Canonical Plan Content heading in the packet
# body. Callers must fail closed (never treat it as "no snapshot").
PLAN_SECTION_DUPLICATE = object()


def plan_snapshot(text: str) -> str | None | object:
    """Content of the canonical plan snapshot inside a verdict packet.

    The unique `## Canonical Plan Content` heading is located first (only
    headings OUTSIDE fenced blocks count, so a plan body inside the snapshot
    cannot create a fake second section). More than one such heading returns
    PLAN_SECTION_DUPLICATE. The scan then stays inside that one section:
    body prose (the ordinary lightweight note) is skipped, and the FIRST
    fenced block within the section - before the next `## ` heading - is
    parsed as the snapshot, so a stale fence appended after the note is
    still validated. The scan never crosses into a following H2 section.
    Fenced blocks before the heading are never mistaken for the snapshot;
    inner plan fences shorter than the framing fence never truncate it.
    None means the section carries no fenced snapshot (legitimate for
    ordinary lightweight packets, fail-closed for high-risk).
    """
    lines = text.splitlines()

    # Pass 1: heading lines outside fenced blocks, with fence-state tracking
    # that honors the framing fence run (inner plan fences cannot reopen).
    headings: list[int] = []
    in_fence = False
    fence_run = 0
    for index, line in enumerate(lines):
        if in_fence:
            if line == "`" * fence_run:
                in_fence = False
            continue
        if line.startswith("```"):
            in_fence = True
            fence_run = len(line) - len(line.lstrip("`"))
            continue
        if line.strip() == PLAN_SECTION_HEADING:
            headings.append(index)
    if not headings:
        return None
    if len(headings) > 1:
        return PLAN_SECTION_DUPLICATE
    heading = headings[0]

    # Pass 2: first fenced block inside the section (heading .. next H2
    # outside a fence); prose in between is skipped.
    in_fence = False
    fence_run = 0
    fence_start = -1
    for index in range(heading + 1, len(lines)):
        line = lines[index]
        if in_fence:
            if line == "`" * fence_run:
                return "\n".join(lines[fence_start + 1 : index])
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            return None
        if line.startswith("```"):
            fence_start = index
            fence_run = len(line) - len(line.lstrip("`"))
            in_fence = True
            continue
    return None


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
    candidate["updated_at"] = iso_z()

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


def packet_artifact_key(workflow_status: str | None) -> str | None:
    """Unique packet artifact bound to a workflow phase (D3).

    review_requested binds the review packet; closeout_requested and the
    post-approval review_approved phase bind the closeout packet. Any other
    phase has no packet to verify against and verdicts fail closed.
    """
    return {
        "review_requested": "review_packet",
        "closeout_requested": "closeout_packet",
        "review_approved": "closeout_packet",
    }.get(workflow_status)


def bound_packet_path(item: dict[str, Any], workflow_status: str | None) -> Path | None:
    """Resolve the phase-bound packet locator under the shared path policy.

    Returns None when the phase has no packet, the artifact field is
    missing/blank, or the locator is unsafe ('..'); the caller fails closed.
    """
    key = packet_artifact_key(workflow_status)
    if key is None:
        return None
    artifacts = item.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    raw = artifacts.get(key)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return _interpret_plan_locator(f"artifacts.{key}", raw.strip())
    except SystemExit:
        return None


def packet_freshness_problems(
    *,
    item: dict[str, Any],
    workflow_status: str | None,
    reviewer_hash: str | None = None,
) -> list[str]:
    """Shared verdict-packet freshness checks (D2-D5, issue #9 mode-aware).

    Checks the phase-bound packet locator, readability, exact-bytes binding
    when `reviewer_hash` is provided, the bounded freshness metadata, item
    and plan locator identity, source plan hash, and the embedded plan
    snapshot render. The snapshot is required for high-risk (missing fails
    closed, so an ordinary lightweight packet fails after an upgrade);
    ordinary allows a missing snapshot but still validates one that is
    present anywhere inside the canonical-plan section. Duplicate
    canonical-plan headings fail closed in both modes. Returns problems
    (empty means fresh); never mutates the checklist. `reviewer_hash` is
    the hash the reviewer computed over the exact packet bytes they read;
    None skips byte binding (validate).
    """
    label = f"item {item.get('id')!r}"
    if reviewer_hash is not None and re.fullmatch(r"[0-9a-fA-F]{64}", reviewer_hash) is None:
        return ["--reviewed-packet-sha256 must be exactly 64 hex characters"]

    packet_path = bound_packet_path(item, workflow_status)
    if packet_path is None:
        return [
            f"{label} has no packet bound to workflow phase {workflow_status!r}; "
            "regenerate the review/closeout packet"
        ]
    if not packet_path.is_file():
        return [f"{label} packet is not a readable file: {packet_path}"]
    try:
        packet_bytes = packet_path.read_bytes()
        packet_text = packet_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{label} packet is not a readable UTF-8 file: {packet_path}: {exc}"]

    if reviewer_hash is not None:
        actual = sha256_bytes(packet_bytes)
        if reviewer_hash.lower() != actual:
            return [
                f"{label} --reviewed-packet-sha256 {reviewer_hash} does not match "
                f"the current packet bytes (sha256 {actual}); the packet changed "
                "since review - regenerate it and re-review"
            ]

    metadata, duplicate_keys = parse_freshness_metadata(packet_text)
    if duplicate_keys:
        return [
            f"{label} packet freshness metadata has duplicate keys: "
            f"{', '.join(sorted(set(duplicate_keys)))}"
        ]
    if not metadata:
        return [
            f"{label} packet is legacy: no {FRESHNESS_HEADING} section; "
            "regenerate the packet and re-review"
        ]
    missing = [field for field in FRESHNESS_FIELDS if not metadata.get(field)]
    if missing:
        return [f"{label} packet freshness metadata missing: {', '.join(missing)}"]

    problems: list[str] = []
    if metadata["checklist_item"] != str(item.get("id")):
        problems.append(
            f"{label} packet checklist_item {metadata['checklist_item']!r} "
            f"does not match item {item.get('id')!r}"
        )
    try:
        plan_path = resolve_item_plan(item, require_exists=True)
        packet_plan_path = _interpret_plan_locator(
            "packet canonical_plan_path", metadata["canonical_plan_path"]
        )
        plan_bytes = plan_path.read_bytes()
        plan_render = plan_path.read_text(encoding="utf-8").rstrip()
    except SystemExit as exc:
        return [f"{label} cannot resolve canonical plan: {exc}"]
    except OSError as exc:
        return [f"{label} canonical plan cannot be read: {plan_path}: {exc}"]

    if packet_plan_path.resolve() != plan_path.resolve():
        problems.append(
            f"{label} packet canonical_plan_path {metadata['canonical_plan_path']!r} "
            f"does not match the resolved plan {rel(plan_path)}"
        )
    if metadata["source_plan_sha256"].lower() != sha256_bytes(plan_bytes):
        problems.append(
            f"{label} packet source_plan_sha256 does not match the current "
            "canonical plan; the plan changed after packet generation"
        )
    snapshot = plan_snapshot(packet_text)
    if snapshot is PLAN_SECTION_DUPLICATE:
        problems.append(
            f"{label} packet has duplicate {PLAN_SECTION_HEADING} sections; "
            "regenerate the packet and re-review"
        )
    elif effective_workflow_mode(item) == "high-risk":
        if snapshot is None:
            problems.append(f"{label} packet has no fenced canonical plan snapshot")
        elif snapshot != plan_render:
            problems.append(
                f"{label} packet plan snapshot does not match the current canonical "
                "plan render; the plan changed after packet generation"
            )
    elif snapshot is not None and snapshot != plan_render:
        # ordinary lightweight packets legitimately omit the plan body; the
        # snapshot is optional. A snapshot that IS present (including one
        # appended after the note, inside the same section) is still
        # checked, so a stale/wrong snapshot in an ordinary packet never
        # passes.
        problems.append(
            f"{label} packet plan snapshot does not match the current canonical "
            "plan render; the plan changed after packet generation"
        )
    return problems


def derived_freshness_warnings(checklist: dict[str, Any]) -> list[str]:
    """D6: warning-only derived-artifact checks for `harnessctl validate`.

    Legacy artifacts and drift only warn and keep validate successful;
    missing derived files are not upgraded to schema errors. Verdict and
    closeout gates fail closed separately via packet_freshness_problems.
    """
    warnings: list[str] = []

    for item in checklist.get("items", []):
        if not isinstance(item, dict):
            continue
        workflow_status = (item.get("workflow") or {}).get("status")
        if workflow_status not in ("review_requested", "closeout_requested", "review_approved"):
            continue
        packet_path = bound_packet_path(item, workflow_status)
        if packet_path is None or not packet_path.is_file():
            continue  # missing derived file is not a freshness schema error
        warnings.extend(
            packet_freshness_problems(item=item, workflow_status=workflow_status)
        )

    pointer_path = current_task_pointer_path()
    if pointer_path.is_file():
        pointer_text = read_text(pointer_path)
        if re.search(r"^- Checklist item: null$", pointer_text, re.MULTILINE):
            # cleared pointer: clear_current_pointer writes the value bare
            return warnings
        body_match = re.search(r"- Checklist item: `([^`]+)`", pointer_text)
        if body_match is None or not body_match.group(1).strip():
            warnings.append(
                f"{rel(pointer_path)} has no parseable '- Checklist item:' in its "
                "current item section; re-run sync"
            )
            return warnings
        body_item = body_match.group(1).strip()
        if body_item == "null":
            # cleared pointer (hand-written backticked form): nothing to check
            return warnings
        metadata, duplicate_keys = parse_freshness_metadata(pointer_text)
        if duplicate_keys:
            warnings.append(
                f"{rel(pointer_path)} freshness metadata has duplicate keys: "
                f"{', '.join(sorted(set(duplicate_keys)))}"
            )
        if not metadata:
            warnings.append(
                f"{rel(pointer_path)} is legacy: no {FRESHNESS_HEADING} section; re-run sync"
            )
            return warnings
        if body_item != metadata.get("checklist_item"):
            warnings.append(
                f"{rel(pointer_path)} body checklist item {body_item!r} differs "
                f"from freshness metadata {metadata.get('checklist_item')!r}; re-run sync"
            )
        missing = [field for field in FRESHNESS_FIELDS if not metadata.get(field)]
        if missing:
            warnings.append(
                f"{rel(pointer_path)} freshness metadata missing: {', '.join(missing)}"
            )
            return warnings
        pointer_item = find_item(checklist, metadata["checklist_item"])
        if pointer_item is None:
            warnings.append(
                f"{rel(pointer_path)} references unknown checklist item "
                f"{metadata['checklist_item']!r}"
            )
            return warnings
        try:
            plan_path = resolve_item_plan(pointer_item, require_exists=True)
            packet_plan_path = _interpret_plan_locator(
                "pointer canonical_plan_path", metadata["canonical_plan_path"]
            )
            plan_bytes = plan_path.read_bytes()
        except SystemExit as exc:
            warnings.append(f"{rel(pointer_path)}: {exc}")
        except OSError as exc:
            warnings.append(f"{rel(pointer_path)}: canonical plan unreadable: {exc}")
        else:
            if packet_plan_path.resolve() != plan_path.resolve():
                warnings.append(
                    f"{rel(pointer_path)} canonical_plan_path "
                    f"{metadata['canonical_plan_path']!r} does not match the "
                    f"resolved plan {rel(plan_path)}; re-run sync"
                )
            if metadata["source_plan_sha256"].lower() != sha256_bytes(plan_bytes):
                warnings.append(
                    f"{rel(pointer_path)} source_plan_sha256 does not match the "
                    "current canonical plan; re-run sync"
                )
    return warnings


# Explicit item reference lint (issue #10): `harnessctl validate` scans
# canonical .md files under the harness root for explicit references to
# checklist items and warns (never fails) on unknown ids. The V1 grammar is
# deliberately finite and low-noise: `item:<id>` inline code spans (spaces
# allowed), bare item:<token> (non-whitespace, trailing sentence punctuation
# stripped), and tasks/<id>/plan.md path segments (spaces allowed). Bare
# prose ids and fenced code examples are never guessed. Placeholder forms
# (`item:<id>` / `tasks/<id>/plan.md`) are skipped.
# Trailing Markdown punctuation stripped from bare candidates: sentence
# punctuation plus the '*' emphasis marker, so *item:mvp-001* and
# **item:mvp-001** do not swallow the emphasis chars into the id.
# Underscore emphasis is deliberately outside the V1 grammar: a trailing
# '_' stays part of the candidate, so bare ids like mvp_001_ resolve
# normally (only the inline code span promises punctuation-exact ids).
_ITEM_REF_TRAILING_PUNCT = ".,;:!?)]}\"'*"

_ITEM_REF_KIND_LABELS = {
    "inline": "inline item reference",
    "bare": "bare item reference",
    "path": "plan path reference",
}


def _is_item_ref_placeholder(candidate: str) -> bool:
    """Angle-bracket forms (<id>, <item-id>) are examples, not references."""
    return candidate.startswith("<") and candidate.endswith(">")


def _strip_fenced_blocks(text: str) -> str:
    """Remove backtick and tilde fenced code blocks (content is not project
    fact). A closing fence needs the same char with at least the opening
    run length and no info string; fence content cannot reopen a fence."""
    lines = text.splitlines()
    out: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in lines:
        stripped = line.strip()
        if fence_char is None:
            if stripped.startswith("```"):
                fence_char = "`"
                fence_len = len(stripped) - len(stripped.lstrip("`"))
                continue
            if stripped.startswith("~~~"):
                fence_char = "~"
                fence_len = len(stripped) - len(stripped.lstrip("~"))
                continue
            out.append(line)
            continue
        if stripped.startswith(fence_char):
            run = len(stripped) - len(stripped.lstrip(fence_char))
            if run >= fence_len and (not stripped[run:] or stripped[run:].isspace()):
                fence_char = None
        # lines inside a fence are dropped
    return "\n".join(out)


def _item_ref_candidates(text: str) -> list[tuple[str, str]]:
    """Explicit item reference candidates in markdown text as
    (candidate, kind) pairs; kind is inline (code span), bare (prose
    token), or path (tasks/<id>/plan.md)."""
    candidates: list[tuple[str, str]] = []
    unfenced = _strip_fenced_blocks(text)

    # inline code span: the backtick is the terminator, so safe ids with
    # spaces/punctuation are representable
    for match in re.finditer(r"`item:([^`]*)`", unfenced):
        candidate = match.group(1).strip()
        if candidate and not _is_item_ref_placeholder(candidate):
            candidates.append((candidate, "inline"))

    # bare token: non-whitespace, sentence punctuation stripped; spans are
    # masked so an `item:x` span never also fires the bare scanner
    no_spans = re.sub(r"`[^`]*`", "", unfenced)
    for match in re.finditer(r"(?<![A-Za-z0-9_/])item:([^\s`]+)", no_spans):
        raw = match.group(1)
        if _is_item_ref_placeholder(raw):
            continue
        candidate = raw.rstrip(_ITEM_REF_TRAILING_PUNCT)
        if candidate and not _is_item_ref_placeholder(candidate):
            candidates.append((candidate, "bare"))

    # canonical task path: the fixed /plan.md terminator ends the id
    # segment, so ids with spaces are representable; bare and
    # harness-prefixed (docs/project-harness/tasks/...) forms both match.
    # The preceding boundary excludes word chars and '-', so
    # my-tasks/<id>/plan.md is not a canonical task path.
    for match in re.finditer(r"(?<![A-Za-z0-9_-])tasks/([^/\n]*?)/plan\.md", unfenced):
        candidate = match.group(1).strip()
        if candidate and not _is_item_ref_placeholder(candidate):
            candidates.append((candidate, "path"))

    return candidates


def explicit_item_reference_warnings(checklist: dict[str, Any], root: Path) -> list[str]:
    """Issue #10: warning-only lint for explicit checklist item references
    in canonical markdown under the harness root.

    Known ids come from the checklist; unknown explicit references warn with
    (relative path, candidate, kind). Symlinks are never followed; a file
    that cannot be read as UTF-8 yields at most one bounded warning and no
    candidate guessing; unexpected (non-I/O) failures propagate so the
    caller exits nonzero.
    """
    known_ids = {
        str(item["id"])
        for item in checklist.get("items", [])
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item["id"].strip()
    }
    findings: set[tuple[str, str, str]] = set()
    if not root.is_dir():
        return []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(dirnames)
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            full = Path(dirpath) / name
            if full.is_symlink():
                continue  # never follow symlinked markdown
            try:
                if not stat_module.S_ISREG(full.stat().st_mode):
                    continue
            except OSError:
                findings.add((rel(full), "", ""))
                continue
            try:
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                findings.add((rel(full), "", ""))
                continue
            for candidate, kind in _item_ref_candidates(text):
                if candidate not in known_ids:
                    findings.add((rel(full), candidate, kind))
    warnings: list[str] = []
    for rel_path, candidate, kind in sorted(findings):
        if kind == "":
            warnings.append(f"{rel_path}: unreadable, skipped")
        else:
            warnings.append(
                f"{rel_path}: unknown {_ITEM_REF_KIND_LABELS[kind]} {candidate!r}"
            )
    return warnings


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


def effective_workflow_mode(item: dict[str, Any]) -> str:
    """Single effective-mode answer (issue #9): only an explicit
    workflow.mode == 'ordinary' classifies as ordinary; a missing workflow,
    a missing mode, or any other value fails closed to high-risk. Runtime
    never guesses a third mode."""
    workflow = item.get("workflow")
    if isinstance(workflow, dict) and workflow.get("mode") == "ordinary":
        return "ordinary"
    return "high-risk"


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
        "--check-derived-freshness",
        metavar="PATH",
        help=(
            "Warning-only derived-artifact freshness check (current pointer and "
            "phase-bound packets) for harnessctl validate; always exits 0 on "
            "readable checklists."
        ),
    )
    parser.add_argument(
        "--check-item-refs",
        metavar="PATH",
        help=(
            "Warning-only explicit item reference lint (issue #10) over "
            "canonical .md files under the harness root; unknown refs print "
            "WARN and always exit 0 on readable checklists."
        ),
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
    if args.check_derived_freshness:
        try:
            with open(args.check_derived_freshness, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: could not read checklist: {exc}", file=sys.stderr)
            return 2
        for warning in derived_freshness_warnings(data):
            print(f"WARN: {warning}")
        return 0
    if args.check_item_refs:
        try:
            with open(args.check_item_refs, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: could not read checklist: {exc}", file=sys.stderr)
            return 2
        root = harness_root()
        if Path(args.check_item_refs).resolve().parent != root.resolve():
            print(
                f"WARN: checklist {rel(Path(args.check_item_refs))} is not "
                f"directly under the harness root {rel(root)}; skipping "
                "markdown reference lint"
            )
            return 0
        for warning in explicit_item_reference_warnings(data, root):
            print(f"WARN: {warning}")
        return 0
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
