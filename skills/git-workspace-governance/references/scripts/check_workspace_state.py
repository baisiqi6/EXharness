#!/usr/bin/env python3
"""Read-only local Git workspace inventory.

Standard library only. Never fetches, never repairs, never mutates the repository.
It reports local Git facts and uses the locally cached remote ref as its reference,
so a stale cache is disclosed instead of silently treated as remote truth.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

GIT_TIMEOUT_SECONDS = 10


class GitReadError(Exception):
    """Stable diagnostic code; Git stderr is never echoed (it may contain URLs)."""


def git(repo, *args, missing_ok=False, input_data=None):
    """Run one bounded read-only Git command and return raw stdout."""
    env = {
        **os.environ,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "LC_ALL": "C",
    }
    command = [
        "git",
        "--no-optional-locks",
        "-c", "core.fsmonitor=false",
        "-c", "core.untrackedCache=false",
        "-c", "maintenance.auto=false",
        "-c", "gc.auto=0",
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            env=env,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            input=input_data,
        )
    except subprocess.TimeoutExpired:
        raise GitReadError("git_read_timeout") from None
    except OSError:
        raise GitReadError("git_unavailable") from None
    if missing_ok and result.returncode == 1:
        return None
    if result.returncode:
        raise GitReadError("git_read_failed")
    return result.stdout


def text(raw):
    return os.fsdecode(raw).strip()


def ref(repo, name):
    raw = git(repo, "rev-parse", "--verify", "--quiet", name, missing_ok=True)
    return text(raw) if raw is not None else None


def change_counts(raw):
    """Count tracked/untracked entries from NUL-delimited porcelain v1 output."""
    tracked = untracked = 0
    parts = raw.split(b"\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry:
            continue
        if entry[:2] == b"??":
            untracked += 1
            continue
        tracked += 1
        if entry[:1] in (b"R", b"C") or entry[1:2] in (b"R", b"C"):
            index += 1  # porcelain -z renames carry a second pathname
    return tracked, untracked


def divergence(repo, head, base):
    if not head or not base:
        return None
    ahead, behind = text(
        git(repo, "rev-list", "--left-right", "--count", f"{head}...{base}")
    ).split()
    return {"ahead": int(ahead), "behind": int(behind)}


def has_active_external_filter(repo):
    """Detect configured Git content filters without executing them.

    Only configuration/attribute names are read. A filter that is configured and
    actually wired to tracked files means `status` may run external code, so the
    workspace cannot be declared clean by this read-only inventory.
    """
    keys = git(
        repo,
        "config",
        "--name-only",
        "--get-regexp",
        r"^filter\..*\.(clean|process)$",
        missing_ok=True,
    )
    if keys is None:
        return False
    names = {line[len(b"filter."):].rsplit(b".", 1)[0] for line in keys.splitlines()}
    paths = git(repo, "ls-files", "-z")
    attrs = git(repo, "check-attr", "-z", "--stdin", "filter", input_data=paths)
    return any(value in names for value in attrs.split(b"\0")[2::3])


def parse_worktrees(repo):
    raw = git(repo, "worktree", "list", "--porcelain", "-z")
    records = []
    for block in raw.split(b"\0\0"):
        record = {}
        for line in block.split(b"\0"):
            if not line:
                continue
            key, _, value = line.partition(b" ")
            record[os.fsdecode(key)] = os.fsdecode(value)
        if record:
            records.append(record)
    if not records:
        raise GitReadError("worktree_inventory_empty")
    return records


def collect(repo_path, integration_branch, remote):
    repo = Path(repo_path).resolve()
    common = Path(
        text(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    ).resolve()
    if text(git(repo, "rev-parse", "--is-bare-repository")) == "true":
        raise GitReadError("bare_repository_unsupported")

    records = parse_worktrees(repo)
    remote_ref = f"refs/remotes/{remote}/{integration_branch}"
    local_integration_ref = f"refs/heads/{integration_branch}"
    remote_ref_sha = ref(repo, remote_ref)
    local_integration_sha = ref(repo, local_integration_ref)

    rows = []
    for record in records:
        path = Path(record["worktree"])
        branch = record.get("branch")
        row = {
            "path": str(path),
            "branch": (
                branch.removeprefix("refs/heads/") if branch else None
            ),
            "head": record.get("HEAD"),
            "locked": "locked" in record,
            "prunable": "prunable" in record,
            "tracked_changes": None,
            "untracked_files": None,
            "head_in_integration": None,
            "last_commit_date": None,
            "error": None,
        }
        try:
            if not path.is_dir():
                raise GitReadError("worktree_unavailable")
            actual_common = Path(
                text(
                    git(
                        path,
                        "rev-parse",
                        "--path-format=absolute",
                        "--git-common-dir",
                    )
                )
            ).resolve()
            if actual_common != common:
                raise GitReadError("worktree_repository_mismatch")
            if ref(path, "HEAD") != row["head"]:
                raise GitReadError("worktree_head_changed_during_scan")
            if has_active_external_filter(path):
                raise GitReadError("external_git_filter_not_assessed")
            raw = git(
                path,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=all",
            )
            row["tracked_changes"], row["untracked_files"] = change_counts(raw)
            diff = divergence(path, row["head"], remote_ref_sha)
            row["head_in_integration"] = diff["ahead"] == 0 if diff else None
            row["last_commit_date"] = text(
                git(path, "show", "-s", "--format=%cI", row["head"])
            )
        except GitReadError as exc:
            row["error"] = str(exc)
        rows.append(row)

    # Git lists the primary checkout first, even when invoked inside a linked worktree.
    canonical = rows[0]
    warnings = []
    if canonical["error"]:
        warnings.append("canonical_unreadable")
    if canonical["branch"] != integration_branch:
        warnings.append("canonical_not_integration")
    if canonical["tracked_changes"] or canonical["untracked_files"]:
        warnings.append("canonical_has_changes")
    if not local_integration_sha:
        warnings.append("local_integration_missing")
    if not remote_ref_sha:
        warnings.append("cached_remote_ref_missing")
    integration_diff = divergence(repo, local_integration_sha, remote_ref_sha)
    if integration_diff:
        if integration_diff["behind"]:
            warnings.append("local_integration_behind")
        if integration_diff["ahead"]:
            warnings.append("local_integration_ahead")

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "reference_scope": (
            f"local cached {remote}/{integration_branch}; no fetch or network"
        ),
        "status_scope": "listed worktrees only; submodule internals not scanned",
        "integration_branch": integration_branch,
        "remote": remote,
        "remote_ref": remote_ref,
        "remote_ref_sha": remote_ref_sha,
        "local_integration_sha": local_integration_sha,
        "local_integration": integration_diff,
        "canonical": canonical,
        "worktree_count": len(rows),
        "warnings": warnings,
        "worktrees": rows,
    }


def render_human(report):
    if "error" in report:
        print("Workspace inventory unavailable:", report["error"])
        return
    canonical = report["canonical"]
    print("Canonical:", json.dumps(canonical["path"], ensure_ascii=False))
    print("Reference:", report["reference_scope"])
    print("Scope:", report["status_scope"])
    print(
        f"Local {report['integration_branch']} ahead/behind:",
        report["local_integration"],
    )
    print(
        "Worktrees:",
        report["worktree_count"],
        "Warnings:",
        ", ".join(report["warnings"]) or "none",
    )
    for row in report["worktrees"]:
        print(
            json.dumps(row["path"], ensure_ascii=False),
            f'branch={row["branch"] or "(detached)"}',
            f'tracked={row["tracked_changes"]}',
            f'untracked={row["untracked_files"]}',
            f'head_in_integration={row["head_in_integration"]}',
            f'last_commit={row["last_commit_date"]}',
            f'locked={row["locked"]}',
            f'prunable={row["prunable"]}',
            f'error={row["error"] or "none"}',
        )
    print(
        "Report only: no owner/PR/runtime/ignored-asset audit; "
        "no cleanup, merge or release authorization."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Read-only local Git workspace inventory. "
            "Never fetches, never repairs, never mutates state."
        )
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="repository or any of its linked worktrees (default: current directory)",
    )
    parser.add_argument(
        "--integration-branch",
        default="main",
        help="local integration branch name (default: main)",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="remote name used for the cached reference (default: origin)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print structured diagnostics"
    )
    args = parser.parse_args(argv)

    try:
        report = collect(args.repo, args.integration_branch, args.remote)
    except GitReadError as exc:
        report = {"error": str(exc)}

    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        render_human(report)

    # 0 = a report was produced (warnings are leads, not gates).
    # 2 = the repository itself could not be read, so no report is trustworthy.
    return 2 if "error" in report else 0


if __name__ == "__main__":
    sys.exit(main())
