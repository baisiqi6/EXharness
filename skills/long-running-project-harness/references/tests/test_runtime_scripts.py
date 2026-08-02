from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


REFERENCES_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = REFERENCES_DIR.parent
SCRIPTS_DIR = REFERENCES_DIR / "scripts"


def replace_placeholders(text: str) -> str:
    return (
        text.replace("{{PROJECT_ROOT_DEPTH}}", "2")
        .replace("{{HARNESS_ROOT}}", "docs/project-harness")
        .replace("{{SCRIPTS_DIR}}", "scripts/harness")
        .replace("{{PROJECT_NAME}}", "fixture-project")
    )


def base_item(item_id: str, status: str = "todo", **overrides: object) -> dict:
    item = {
        "id": item_id,
        "title": f"Item {item_id}",
        "status": status,
        "priority": "p0",
        "owner": None,
        "selected_in_session": None,
        "updated_at": "2026-05-12",
        "dependencies": [],
        "blocked_by": [],
        "blocked_reason": None,
        "acceptance": "Acceptance is objective.",
        "verification": "Run configured tests.",
        "handoff": "Continue from the current plan.",
    }
    item.update(overrides)
    return item


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class HarnessRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.project = Path(self.tempdir.name)
        self.script_dir = self.project / "scripts" / "harness"
        self.harness = self.project / "docs" / "project-harness"
        self.script_dir.mkdir(parents=True)
        self.harness.mkdir(parents=True)
        (self.harness / "current").mkdir()
        (self.harness / "tasks").mkdir()

        for source in SCRIPTS_DIR.iterdir():
            if not source.is_file() or source.suffix == ".pyc":
                continue
            target = self.script_dir / source.name
            body = replace_placeholders(source.read_text(encoding="utf-8"))
            target.write_text(body, encoding="utf-8")
            if source.name == "harnessctl":
                target.chmod(target.stat().st_mode | 0o111)

        (self.harness / "progress.md").write_text(
            "# Progress\n\n## Current Status\n\nFixture ready.\n\n## Blockers\n\n- None.\n",
            encoding="utf-8",
        )
        write_json(
            self.harness / "harness-config.json",
            {
                "commands": {},
                "runtime": {
                    "session_init_commands": ["typecheck", "test"],
                    "lease_ttl_minutes": 120,
                },
                "git": {
                    "base_branch": "main",
                    "branch_namespace": "agent/{owner}/{item_id}",
                },
                "message_bus": {
                    "event_log": "docs/project-harness/events.jsonl",
                    "visible_bus": "discord-or-kook",
                },
            },
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_harness(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.script_dir / "harnessctl"), *args],
            cwd=self.project,
            text=True,
            capture_output=True,
        )

    def write_checklist(self, items: list[dict]) -> None:
        self.write_checklist_file("mvp-checklist.json", items)

    def write_checklist_file(self, filename: str, items: list[dict]) -> None:
        write_json(
            self.harness / filename,
            {
                "project": "fixture-project",
                "harness_root": "docs/project-harness",
                "updated_at": "2026-05-12",
                "items": items,
            },
        )

    def write_plan(self, relative_path: str, body: str) -> Path:
        plan = self.harness / relative_path
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(body, encoding="utf-8")
        return plan

    def read_checklist(self) -> dict:
        return json.loads((self.harness / "mvp-checklist.json").read_text(encoding="utf-8"))

    def read_checklist_file(self, filename: str) -> dict:
        return json.loads((self.harness / filename).read_text(encoding="utf-8"))

    def load_harness_common(self):
        """Load the instantiated harness_common module in-process (for
        failpoint tests); the script directory is on sys.path only during load."""
        sys.path.insert(0, str(self.script_dir))
        try:
            spec = importlib.util.spec_from_file_location(
                "hc_under_test", self.script_dir / "harness_common.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(self.script_dir))

    def load_checklist_items(self):
        """Load the instantiated checklist_items module in-process."""
        sys.path.insert(0, str(self.script_dir))
        try:
            spec = importlib.util.spec_from_file_location(
                "checklist_items_under_test", self.script_dir / "checklist_items.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        finally:
            sys.path.remove(str(self.script_dir))

    def read_events(self) -> list[dict]:
        path = self.harness / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_legacy_checklist_still_validates(self) -> None:
        checklist = {
            "project": "legacy",
            "harness_root": "docs/project-harness",
            "updated_at": "2026-05-12",
            "items": [base_item("mvp-001")],
        }
        path = self.project / "legacy.json"
        write_json(path, checklist)

        result = subprocess.run(
            [sys.executable, str(SKILL_DIR / "scripts" / "validate-checklist.py"), str(path)],
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extended_checklist_validates(self) -> None:
        checklist = {
            "project": "extended",
            "harness_root": "docs/project-harness",
            "updated_at": "2026-05-12",
            "items": [
                base_item(
                    "mvp-001",
                    "doing",
                    owner="codex",
                    selected_in_session="codex-1",
                    workflow={"status": "running", "updated_at": "2026-05-12"},
                    lease={
                        "owner": "codex",
                        "session": "codex-1",
                        "acquired_at": "2026-05-12T00:00:00Z",
                        "expires_at": "2099-01-01T00:00:00Z",
                        "ttl_minutes": 120,
                    },
                    artifacts={"plan": "docs/project-harness/tasks/mvp-001/plan.md"},
                    review={"decision": None},
                )
            ],
        }
        path = self.project / "extended.json"
        write_json(path, checklist)

        result = subprocess.run(
            [sys.executable, str(SKILL_DIR / "scripts" / "validate-checklist.py"), str(path)],
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_start_rejects_unfinished_dependency(self) -> None:
        self.write_checklist(
            [
                base_item("mvp-001", "todo"),
                base_item("mvp-002", dependencies=["mvp-001"]),
            ]
        )

        result = self.run_harness("start", "mvp-002", "codex", "codex-1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unfinished dependencies", result.stderr)

    def test_start_rejects_blocked_item(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    "blocked",
                    blocked_reason="Needs human decision.",
                    handoff="Ask human.",
                )
            ]
        )

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is blocked", result.stderr)

    def test_start_rejects_active_foreign_lease(self) -> None:
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    "doing",
                    owner="claude",
                    selected_in_session="claude-1",
                    lease={
                        "owner": "claude",
                        "session": "claude-1",
                        "acquired_at": "2026-05-12T00:00:00Z",
                        "expires_at": expires,
                        "ttl_minutes": 120,
                    },
                )
            ]
        )

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active lease", result.stderr)

    def test_expired_lease_can_be_taken_over_and_writes_event(self) -> None:
        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    "doing",
                    owner="claude",
                    selected_in_session="claude-1",
                    lease={
                        "owner": "claude",
                        "session": "claude-1",
                        "acquired_at": "2026-05-12T00:00:00Z",
                        "expires_at": expired,
                        "ttl_minutes": 120,
                    },
                )
            ]
        )

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")

        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["owner"], "codex")
        self.assertEqual(item["lease"]["owner"], "codex")
        events = self.read_events()
        self.assertEqual(events[-1]["type"], "ACCEPT")
        self.assertEqual(events[-1]["task"], "mvp-001")
        self.assertEqual(events[-1]["schema_version"], 1)
        self.assertEqual(events[-1]["publish_status"], "local_only")
        self.assertIn("[ACCEPT]", events[-1]["visible_header"])

    def test_same_owner_can_renew_lease_and_branch_artifact_is_set(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)
        first_item = self.read_checklist()["items"][0]
        first_expiry = first_item["lease"]["expires_at"]
        self.assertEqual(first_item["workflow"]["branch"], "agent/codex/mvp-001")
        self.assertEqual(first_item["artifacts"]["branch"], "agent/codex/mvp-001")

        renew = self.run_harness("renew-lease", "mvp-001", "codex", "codex-1", "--lease-minutes", "240")
        self.assertEqual(renew.returncode, 0, renew.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["lease"]["owner"], "codex")
        self.assertEqual(item["lease"]["ttl_minutes"], 240)
        self.assertNotEqual(item["lease"]["expires_at"], first_expiry)
        events = self.read_events()
        self.assertEqual(events[-1]["type"], "LEASE")
        self.assertEqual(events[-1]["status"], "renewed")

    def test_session_init_uses_configured_commands_without_pnpm(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        write_json(
            self.harness / "harness-config.json",
            {
                "commands": {
                    "typecheck": f"{sys.executable} -c \"print('TYPECHECK_OK')\"",
                    "test": f"{sys.executable} -c \"print('TEST_OK')\"",
                },
                "runtime": {"session_init_commands": ["typecheck", "test"]},
                "message_bus": {"event_log": "docs/project-harness/events.jsonl"},
            },
        )

        result = self.run_harness("session-init")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TYPECHECK_OK", result.stdout)
        self.assertIn("TEST_OK", result.stdout)
        self.assertNotIn("pnpm", result.stdout)

    def test_closeout_requires_approved_review_before_mark_done(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)

        closeout = self.run_harness("closeout", "mvp-001", "reviewer")
        self.assertEqual(closeout.returncode, 0, closeout.stderr)

        denied = self.run_harness("mark-done", "mvp-001", "operator")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("requires review.decision == approved", denied.stderr)

        approved = self.run_harness(
            "review-result",
            "mvp-001",
            "reviewer",
            "approved",
            "--summary",
            "Acceptance and verification pass.",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)

        done = self.run_harness("mark-done", "mvp-001", "operator")
        self.assertEqual(done.returncode, 0, done.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["workflow"]["status"], "closed")

    def test_handoff_target_can_accept_without_force(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)

        handoff = self.run_harness(
            "handoff",
            "mvp-001",
            "claude",
            "--actor",
            "codex",
            "--reason",
            "Claude should finish the implementation.",
        )
        self.assertEqual(handoff.returncode, 0, handoff.stderr)
        handed_off = self.read_checklist()["items"][0]
        self.assertIsNone(handed_off["owner"])
        self.assertIsNotNone(handed_off["lease"].get("released_at"))
        self.assertEqual(handed_off["workflow"]["handoff_target"], "claude")

        accepted = self.run_harness("accept", "mvp-001", "claude", "claude-1")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["owner"], "claude")
        self.assertEqual(item["lease"]["owner"], "claude")
        self.assertEqual(item["workflow"]["status"], "running")

    def test_handoff_target_can_decline_without_force(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)
        handoff = self.run_harness("handoff", "mvp-001", "claude", "--actor", "codex")
        self.assertEqual(handoff.returncode, 0, handoff.stderr)

        declined = self.run_harness("decline", "mvp-001", "claude", "--summary", "Not available.")
        self.assertEqual(declined.returncode, 0, declined.stderr)
        item = self.read_checklist()["items"][0]
        # U1 contract: declined items return to unowned todo with a released
        # workflow (validator rejects the old 'declined' status); the DECLINE
        # evidence is preserved in events and workflow fields.
        self.assertEqual(item["workflow"]["status"], "released")
        self.assertEqual(item["workflow"]["declined_by"], "claude")
        self.assertIsNotNone(item["workflow"].get("decline_reason"))
        self.assertEqual(item["status"], "todo")
        self.assertIsNone(item["owner"])
        events = self.read_events()
        self.assertEqual(events[-1]["type"], "DECLINE")
        self.assertEqual(events[-1]["status"], "declined")

    def test_mark_done_requires_closeout_review_not_plan_review(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)

        approved = self.run_harness(
            "review-result",
            "mvp-001",
            "reviewer",
            "approved",
            "--summary",
            "Plan looks fine, but this is not a closeout review.",
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)

        denied = self.run_harness("mark-done", "mvp-001", "operator")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("approved review of a closeout request", denied.stderr)

    def test_mark_done_clears_stale_current_item_in_state(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)
        closeout = self.run_harness("closeout", "mvp-001", "reviewer")
        self.assertEqual(closeout.returncode, 0, closeout.stderr)
        approved = self.run_harness("review-result", "mvp-001", "reviewer", "approved")
        self.assertEqual(approved.returncode, 0, approved.stderr)
        done = self.run_harness("mark-done", "mvp-001", "operator")
        self.assertEqual(done.returncode, 0, done.stderr)

        state = self.run_harness("state")
        self.assertEqual(state.returncode, 0, state.stderr)
        data = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))
        self.assertIsNone(data["current_item"])
        item = self.read_checklist()["items"][0]
        self.assertIsNone(item["owner"])
        self.assertIsNone(item["selected_in_session"])

    def test_blocker_releases_lease_and_unblock_restores_claimable_item(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)
        (self.harness / "current" / "blocker.md").write_text(
            "# Blocker\n\n## Problem\n\nNeed human decision.\n",
            encoding="utf-8",
        )

        blocked = self.run_harness(
            "blocker",
            "mvp-001",
            "--actor",
            "codex",
            "--unblock-owner",
            "human",
            "--reason",
            "Need human decision.",
        )
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        blocked_item = self.read_checklist()["items"][0]
        self.assertEqual(blocked_item["status"], "blocked")
        self.assertIsNone(blocked_item["owner"])
        self.assertIsNotNone(blocked_item["lease"].get("released_at"))
        self.assertEqual(blocked_item["workflow"]["unblock_owner"], "human")

        still_blocked = self.run_harness("accept", "mvp-001", "claude", "claude-1")
        self.assertNotEqual(still_blocked.returncode, 0)
        self.assertIn("is blocked", still_blocked.stderr)

        unblocked = self.run_harness(
            "unblock",
            "mvp-001",
            "human",
            "--decision",
            "Proceed with Claude after narrowing scope.",
        )
        self.assertEqual(unblocked.returncode, 0, unblocked.stderr)
        accepted = self.run_harness("accept", "mvp-001", "claude", "claude-1")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["owner"], "claude")
        self.assertEqual(item["status"], "doing")

    def test_harness_state_is_repeatably_derived(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        first = self.run_harness("state")
        self.assertEqual(first.returncode, 0, first.stderr)
        state_one = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))

        second = self.run_harness("state")
        self.assertEqual(second.returncode, 0, second.stderr)
        state_two = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))

        state_one["generated_at"] = "<generated>"
        state_two["generated_at"] = "<generated>"
        self.assertEqual(state_one, state_two)

    # ------------------------------------------------------------------
    # U1: resolver / migration matrix
    # ------------------------------------------------------------------

    def test_new_only_checklist_is_active(self) -> None:
        self.write_checklist_file("harness-checklist.json", [base_item("mvp-001")])

        result = self.run_harness("add-item", "mvp-002", "--title", "Two", "--acceptance", "Two works.")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.read_checklist_file("harness-checklist.json")
        self.assertIn("mvp-002", [entry["id"] for entry in data["items"]])
        self.assertFalse((self.harness / "mvp-checklist.json").exists())

        validate = self.run_harness("validate")
        self.assertEqual(validate.returncode, 0, validate.stderr)
        self.assertIn("harness-checklist.json", validate.stdout)

    def test_new_only_checklist_full_lifecycle(self) -> None:
        self.write_checklist_file("harness-checklist.json", [base_item("mvp-001")])

        start = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(start.returncode, 0, start.stderr)
        data = self.read_checklist_file("harness-checklist.json")
        self.assertEqual(data["items"][0]["status"], "doing")

        state = self.run_harness("state")
        self.assertEqual(state.returncode, 0, state.stderr)
        state_data = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state_data["source"]["checklist_path"], "docs/project-harness/harness-checklist.json")

    def test_none_checklist_mutation_fails_closed(self) -> None:
        result = self.run_harness("add-item", "mvp-001", "--title", "One", "--acceptance", "One.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no checklist found", result.stderr)
        self.assertFalse((self.harness / "harness-checklist.json").exists())

        state = self.run_harness("state")
        self.assertNotEqual(state.returncode, 0)
        self.assertIn("no checklist found", state.stderr)

    def test_both_checklists_fail_closed(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        self.write_checklist_file("harness-checklist.json", [base_item("mvp-001")])

        add = self.run_harness("add-item", "mvp-002", "--title", "Two", "--acceptance", "Two.")
        self.assertNotEqual(add.returncode, 0)
        self.assertIn("dual checklist authority", add.stderr)

        state = self.run_harness("state")
        self.assertNotEqual(state.returncode, 0)
        self.assertIn("dual checklist authority", state.stderr)

        validate = self.run_harness("validate")
        self.assertNotEqual(validate.returncode, 0)

        doctor = self.run_harness("doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("dual authority", doctor.stdout)
        self.assertIn("Skipped: no single active checklist", doctor.stdout)

    def _write_current_pointer(self, item_id: str) -> None:
        (self.harness / "current" / "task_plan.md").write_text(
            f"# Current Task Pointer\n\n- Checklist item: `{item_id}`\n",
            encoding="utf-8",
        )

    def test_doctor_doing_item_relative_custom_locator_not_false_positive(self) -> None:
        self.write_plan("custom/rel/plan.md", "# Plan\n")
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    status="doing",
                    plan_path="docs/project-harness/custom/rel/plan.md",
                )
            ]
        )
        self._write_current_pointer("mvp-001")

        doctor = self.run_harness("doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("Current item: mvp-001", doctor.stdout)
        self.assertIn("custom/rel/plan.md", doctor.stdout)
        self.assertNotIn("has no canonical plan", doctor.stdout)

    def test_doctor_doing_item_absolute_custom_locator_not_false_positive(self) -> None:
        external = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(external, ignore_errors=True))
        plan = external / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        self.write_checklist([base_item("mvp-001", status="doing", plan_path=str(plan))])
        self._write_current_pointer("mvp-001")

        doctor = self.run_harness("doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("Current item: mvp-001", doctor.stdout)
        self.assertNotIn("has no canonical plan", doctor.stdout)

    def test_doctor_doing_item_missing_locator_warns_without_silent_default(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    status="doing",
                    plan_path="docs/project-harness/custom/missing/plan.md",
                )
            ]
        )
        self._write_current_pointer("mvp-001")

        doctor = self.run_harness("doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("has no canonical plan", doctor.stdout)
        self.assertIn("custom/missing/plan.md", doctor.stdout)
        # the hardcoded default path must not be silently substituted
        self.assertNotIn("tasks/mvp-001/plan.md", doctor.stdout)

    def test_doctor_doing_item_locator_conflict_fails_loud(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    status="doing",
                    plan_path="docs/project-harness/a/plan.md",
                    artifacts={"plan": "docs/project-harness/b/plan.md"},
                )
            ]
        )
        self._write_current_pointer("mvp-001")

        doctor = self.run_harness("doctor")
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn("conflicting plan locators", doctor.stderr)
        self.assertIn("ERROR: could not resolve doing item plan", doctor.stdout)
        self.assertNotIn("Current item:", doctor.stdout)

    def test_migrate_keeps_bytes_and_removes_old(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        old_bytes = (self.harness / "mvp-checklist.json").read_bytes()

        result = self.run_harness("migrate-checklist")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.harness / "harness-checklist.json").exists())
        self.assertFalse((self.harness / "mvp-checklist.json").exists())
        self.assertEqual((self.harness / "harness-checklist.json").read_bytes(), old_bytes)

        again = self.run_harness("migrate-checklist")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already exists", again.stderr)

    def test_migrate_refuses_existing_destination(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        self.write_checklist_file("harness-checklist.json", [])

        result = self.run_harness("migrate-checklist")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dual checklist authority", result.stderr)
        self.assertTrue((self.harness / "mvp-checklist.json").exists())

    def test_migrate_refuses_invalid_old(self) -> None:
        (self.harness / "mvp-checklist.json").write_text("{invalid json", encoding="utf-8")

        result = self.run_harness("migrate-checklist")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not be read as JSON", result.stderr)
        self.assertTrue((self.harness / "mvp-checklist.json").exists())
        self.assertFalse((self.harness / "harness-checklist.json").exists())

    def test_coordinate_managed_blocks_bare_add_update(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        write_json(self.harness / "harness-config.json", {"deployment_profile": "coordinate-managed"})

        add = self.run_harness("add-item", "mvp-002", "--title", "Two", "--acceptance", "Two.")
        self.assertNotEqual(add.returncode, 0)
        self.assertIn("coordinate-managed", add.stderr)

        update = self.run_harness("update-item", "mvp-001", "--title", "Renamed")
        self.assertNotEqual(update.returncode, 0)
        self.assertIn("coordinate-managed", update.stderr)

        # lifecycle commands stay callable (HarnessAdapter controlled path)
        state = self.run_harness("state")
        self.assertEqual(state.returncode, 0, state.stderr)

    def test_migrate_requires_ack_under_managed_profile(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        write_json(self.harness / "harness-config.json", {"deployment_profile": "coordinate-managed"})

        denied = self.run_harness("migrate-checklist")
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("--ack-managed-profile", denied.stderr)
        self.assertTrue((self.harness / "mvp-checklist.json").exists())

        acked = self.run_harness("migrate-checklist", "--ack-managed-profile")
        self.assertEqual(acked.returncode, 0, acked.stderr)
        self.assertTrue((self.harness / "harness-checklist.json").exists())
        self.assertFalse((self.harness / "mvp-checklist.json").exists())

    def test_invalid_deployment_profile_fails_closed(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        write_json(self.harness / "harness-config.json", {"deployment_profile": "bogus"})

        result = self.run_harness("add-item", "mvp-002", "--title", "Two", "--acceptance", "Two.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid deployment_profile", result.stderr)

    # ------------------------------------------------------------------
    # U1: add-item / update-item schema and plan locators
    # ------------------------------------------------------------------

    def test_add_item_rejects_duplicate_id(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        result = self.run_harness("add-item", "mvp-001", "--title", "Dup", "--acceptance", "A.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(len(self.read_checklist()["items"]), 1)

    def test_add_item_rejects_unknown_and_self_dependency(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        unknown = self.run_harness("add-item", "mvp-002", "--title", "T", "--acceptance", "A.", "--dependency", "ghost")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("dependency item not found", unknown.stderr)

        self_dep = self.run_harness("add-item", "mvp-002", "--title", "T", "--acceptance", "A.", "--dependency", "mvp-002")
        self.assertNotEqual(self_dep.returncode, 0)
        self.assertIn("cannot depend on itself", self_dep.stderr)

        self.assertEqual(len(self.read_checklist()["items"]), 1)

    def test_add_item_rejects_invalid_priority_and_missing_args(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        bad_priority = self.run_harness("add-item", "mvp-002", "--title", "T", "--acceptance", "A.", "--priority", "p9")
        self.assertNotEqual(bad_priority.returncode, 0)

        no_title = self.run_harness("add-item", "mvp-002", "--acceptance", "A.")
        self.assertNotEqual(no_title.returncode, 0)
        self.assertEqual(len(self.read_checklist()["items"]), 1)

    def test_add_item_requires_existing_plan_file(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        result = self.run_harness(
            "add-item", "mvp-002", "--title", "T", "--acceptance", "A.",
            "--plan", "docs/project-harness/tasks/mvp-002/plan.md",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr)
        self.assertEqual(len(self.read_checklist()["items"]), 1)

    def test_add_item_rejects_plan_locator_with_dotdot(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        result = self.run_harness(
            "add-item", "mvp-002", "--title", "T", "--acceptance", "A.",
            "--plan", "../outside/plan.md",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not contain '..'", result.stderr)

    def test_add_item_writes_plan_path_locator_only(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        self.write_plan("tasks/mvp-002/plan.md", "# Plan\n")

        result = self.run_harness(
            "add-item", "mvp-002", "--title", "T", "--acceptance", "A.",
            "--plan", "docs/project-harness/tasks/mvp-002/plan.md",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        item = next(entry for entry in self.read_checklist()["items"] if entry["id"] == "mvp-002")
        self.assertEqual(item["plan_path"], "docs/project-harness/tasks/mvp-002/plan.md")
        self.assertNotIn("plan", item.get("artifacts") or {})
        self.assertEqual(item["status"], "todo")
        self.assertEqual(item["priority"], "p1")

    def test_external_absolute_plan_locator_supported(self) -> None:
        external_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(external_dir, ignore_errors=True))
        external_plan = external_dir / "plan.md"
        external_plan.write_text("# External plan\n", encoding="utf-8")
        self.write_checklist([base_item("mvp-001")])

        result = self.run_harness(
            "add-item", "mvp-002", "--title", "T", "--acceptance", "A.",
            "--plan", str(external_plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        item = next(entry for entry in self.read_checklist()["items"] if entry["id"] == "mvp-002")
        self.assertEqual(item["plan_path"], str(external_plan))

    def test_update_item_requires_change_and_rejects_forbidden(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        noop = self.run_harness("update-item", "mvp-001")
        self.assertNotEqual(noop.returncode, 0)
        self.assertIn("at least one modification", noop.stderr)

        missing = self.run_harness("update-item", "ghost", "--title", "X")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("not found", missing.stderr)

        forbidden = self.run_harness("update-item", "mvp-001", "--status", "done")
        self.assertNotEqual(forbidden.returncode, 0)

    def test_update_item_preserves_unknown_compatible_fields(self) -> None:
        self.write_checklist([base_item("mvp-001", future_extension={"a": 1})])

        result = self.run_harness("update-item", "mvp-001", "--title", "Renamed")
        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["title"], "Renamed")
        self.assertEqual(item["future_extension"], {"a": 1})

    def test_update_item_dependency_management(self) -> None:
        self.write_checklist([base_item("mvp-001"), base_item("mvp-002")])

        add = self.run_harness("update-item", "mvp-002", "--add-dependency", "mvp-001")
        self.assertEqual(add.returncode, 0, add.stderr)
        self.assertEqual(self.read_checklist()["items"][1]["dependencies"], ["mvp-001"])

        dup = self.run_harness("update-item", "mvp-002", "--add-dependency", "mvp-001")
        self.assertNotEqual(dup.returncode, 0)
        self.assertIn("already present", dup.stderr)

        remove = self.run_harness("update-item", "mvp-002", "--remove-dependency", "mvp-001")
        self.assertEqual(remove.returncode, 0, remove.stderr)
        self.assertEqual(self.read_checklist()["items"][1]["dependencies"], [])

    def test_plan_locator_conflict_fails_closed(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    plan_path="docs/project-harness/tasks/mvp-001/plan.md",
                    artifacts={"plan": "docs/project-harness/other.md"},
                )
            ]
        )
        self.write_plan("tasks/mvp-001/plan.md", "# P\n")
        (self.harness / "other.md").write_text("# P2\n", encoding="utf-8")

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicting plan locators", result.stderr)

    def test_plan_locator_both_equal_is_accepted(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    plan_path="docs/project-harness/tasks/mvp-001/plan.md",
                    artifacts={"plan": "docs/project-harness/tasks/mvp-001/plan.md"},
                )
            ]
        )
        self.write_plan("tasks/mvp-001/plan.md", "# P\n")

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plan_path_only_used_without_scaffold(self) -> None:
        self.write_checklist(
            [base_item("mvp-001", plan_path="docs/project-harness/tasks/mvp-001/plan.md")]
        )
        plan = self.write_plan("tasks/mvp-001/plan.md", "# Custom plan\n")
        before = plan.read_text(encoding="utf-8")

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(plan.read_text(encoding="utf-8"), before)

    def test_artifacts_plan_only_used(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    artifacts={"plan": "docs/project-harness/tasks/mvp-001/plan.md"},
                )
            ]
        )
        self.write_plan("tasks/mvp-001/plan.md", "# P\n")

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_start_with_missing_locator_fails_closed_without_scaffold(self) -> None:
        self.write_checklist(
            [base_item("mvp-001", plan_path="docs/project-harness/tasks/mvp-001/plan.md")]
        )

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plan file not found", result.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["status"], "todo")
        self.assertFalse((self.harness / "tasks" / "mvp-001" / "plan.md").exists())

    def test_start_scaffolds_default_plan_when_no_locator(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        result = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = self.harness / "tasks" / "mvp-001" / "plan.md"
        self.assertTrue(plan.exists())
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["artifacts"]["plan"], "docs/project-harness/tasks/mvp-001/plan.md")

    def test_update_item_plan_syncs_both_fields(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    plan_path="docs/project-harness/tasks/mvp-001/plan.md",
                    artifacts={"plan": "docs/project-harness/other.md"},
                )
            ]
        )
        self.write_plan("tasks/mvp-001/plan.md", "# P\n")

        result = self.run_harness(
            "update-item", "mvp-001", "--plan", "docs/project-harness/tasks/mvp-001/plan.md"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["plan_path"], "docs/project-harness/tasks/mvp-001/plan.md")
        self.assertEqual(item["artifacts"]["plan"], "docs/project-harness/tasks/mvp-001/plan.md")

    # ------------------------------------------------------------------
    # U1: lifecycle verification contract
    # ------------------------------------------------------------------

    def test_mark_done_requires_verification(self) -> None:
        self.write_checklist([base_item("mvp-001", verification="")])

        result = self.run_harness("mark-done", "mvp-001", "operator", "--force", "--reason", "human override")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verification", result.stderr)
        item = self.read_checklist()["items"][0]
        self.assertNotEqual(item["status"], "done")

    def test_mark_done_with_explicit_verification_writes_it(self) -> None:
        self.write_checklist([base_item("mvp-001", verification="")])

        result = self.run_harness(
            "mark-done", "mvp-001", "operator", "--force", "--reason", "human override",
            "--verification", "Manual check passed.",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["verification"], "Manual check passed.")

    def test_mark_done_with_existing_verification_passes(self) -> None:
        self.write_checklist([base_item("mvp-001", verification="Run the configured tests.")])

        result = self.run_harness("mark-done", "mvp-001", "operator", "--force", "--reason", "human override")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_checklist()["items"][0]["status"], "done")

    def test_help_usage_shows_mark_done_verification_flag(self) -> None:
        # External usage assertion: the top-level help must surface the
        # same-mutation --verification TEXT capability next to --force --reason.
        result = self.run_harness("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "mark-done <item-id> [actor] [--verification TEXT] [--force --reason TEXT]",
            result.stdout,
        )

    # ------------------------------------------------------------------
    # U1: validator parity
    # ------------------------------------------------------------------

    def test_validator_wrapper_parity(self) -> None:
        valid = {
            "project": "p",
            "harness_root": "docs/project-harness",
            "updated_at": "2026-05-12",
            "items": [base_item("mvp-001")],
        }
        cases = [
            ("valid.json", valid),
            ("invalid.json", {"project": 1, "items": []}),
            ("dup.json", {"project": "p", "harness_root": "h", "updated_at": "d", "items": [base_item("a"), base_item("a")]}),
        ]
        for filename, content in cases:
            path = self.project / filename
            write_json(path, content)
            wrapper = subprocess.run(
                [sys.executable, str(SKILL_DIR / "scripts" / "validate-checklist.py"), str(path)],
                text=True,
                capture_output=True,
            )
            canonical = subprocess.run(
                [sys.executable, str(self.script_dir / "validate_checklist.py"), str(path)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(wrapper.returncode, canonical.returncode, filename)
            self.assertEqual(wrapper.stdout, canonical.stdout, filename)
            self.assertEqual(wrapper.stderr, canonical.stderr, filename)

    # ------------------------------------------------------------------
    # U1: atomicity / freshness
    # ------------------------------------------------------------------

    def test_atomic_replace_failure_preserves_original_bytes(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        original = (self.harness / "mvp-checklist.json").read_bytes()
        hc = self.load_harness_common()

        with mock.patch.object(hc.os, "replace", side_effect=OSError("injected replace failure")):
            with self.assertRaises(OSError):
                hc.mutate_checklist(lambda cand: cand.__setitem__("project", "changed"))

        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), original)
        leftovers = [p for p in self.harness.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_atomic_fsync_failure_preserves_original_bytes(self) -> None:
        path = self.harness / "probe.json"
        path.write_text("old", encoding="utf-8")
        hc = self.load_harness_common()

        with mock.patch.object(hc.os, "fsync", side_effect=OSError("injected fsync failure")):
            with self.assertRaises(OSError):
                hc.atomic_write_bytes(path, b"new content")

        self.assertEqual(path.read_text(encoding="utf-8"), "old")
        leftovers = [p for p in self.harness.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_atomic_parent_fsync_failure_propagates_after_commit(self) -> None:
        path = self.harness / "probe2.json"
        hc = self.load_harness_common()

        with mock.patch.object(hc, "_fsync_dir", side_effect=OSError("injected parent fsync failure")):
            with self.assertRaises(OSError):
                hc.atomic_write_bytes(path, b"new content")

        # commit point (os.replace) already passed; the error is not swallowed
        self.assertEqual(path.read_text(encoding="utf-8"), "new content")
        leftovers = [p for p in self.harness.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_mutation_preserves_checklist_mode(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        (self.harness / "mvp-checklist.json").chmod(0o600)

        result = self.run_harness("add-item", "mvp-002", "--title", "T", "--acceptance", "A.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            stat.S_IMODE((self.harness / "mvp-checklist.json").stat().st_mode), 0o600
        )

    def test_state_source_digest_matches_actual_bytes(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        expected = hashlib.sha256((self.harness / "mvp-checklist.json").read_bytes()).hexdigest()

        result = self.run_harness("state")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))
        self.assertEqual(data["source"]["checklist_sha256"], expected)
        self.assertEqual(data["source"]["checklist_path"], "docs/project-harness/mvp-checklist.json")
        self.assertEqual(data["paths"]["checklist"], "docs/project-harness/mvp-checklist.json")

    def test_state_digest_changes_when_checklist_changes(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        self.run_harness("state")
        first = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))["source"]["checklist_sha256"]

        data = self.read_checklist()
        data["project"] = "changed"
        write_json(self.harness / "mvp-checklist.json", data)
        self.run_harness("state")
        second = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))["source"]["checklist_sha256"]

        self.assertNotEqual(first, second)

    def test_state_write_failure_keeps_old_state(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        self.run_harness("state")
        old = (self.harness / "harness-state.json").read_bytes()
        hc = self.load_harness_common()

        with mock.patch.object(hc.os, "replace", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                hc.atomic_write_json(self.harness / "harness-state.json", {"x": 1})

        self.assertEqual((self.harness / "harness-state.json").read_bytes(), old)
        leftovers = [p for p in self.harness.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_done_item_never_reported_as_current(self) -> None:
        self.write_checklist([base_item("mvp-001", "done", verification="Verified.")])
        (self.harness / "current").mkdir(exist_ok=True)
        (self.harness / "current" / "task_plan.md").write_text(
            "# Current Task Pointer\n\n- Checklist item: `mvp-001`\n",
            encoding="utf-8",
        )

        result = self.run_harness("state")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))
        self.assertIsNone(data["current_item"])

    # ------------------------------------------------------------------
    # U1 Round 3: reviewer-finding regressions
    # ------------------------------------------------------------------

    def test_fsync_dir_unsupported_errno_falls_back(self) -> None:
        hc = self.load_harness_common()
        with mock.patch.object(
            hc.os, "open", side_effect=OSError(errno.ENOTSUP, "unsupported")
        ):
            hc._fsync_dir(self.harness)  # must not raise

    def test_fsync_dir_ordinary_error_propagates(self) -> None:
        hc = self.load_harness_common()
        with mock.patch.object(
            hc.os, "open", side_effect=OSError(errno.EACCES, "permission denied")
        ):
            with self.assertRaises(OSError) as ctx:
                hc._fsync_dir(self.harness)
        self.assertEqual(ctx.exception.errno, errno.EACCES)

    def test_add_item_rejects_internal_dotdot_locator(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        result = self.run_harness(
            "add-item", "mvp-002", "--title", "T", "--acceptance", "A.",
            "--plan", "docs/project-harness/../other/plan.md",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not contain '..'", result.stderr)
        self.assertEqual(len(self.read_checklist()["items"]), 1)

    def test_assign_preserves_existing_plan_path_locator(self) -> None:
        self.write_checklist(
            [base_item("mvp-001", plan_path="docs/project-harness/tasks/mvp-001/plan.md")]
        )

        assigned = self.run_harness("assign", "mvp-001", "codex", "codex-1")
        self.assertEqual(assigned.returncode, 0, assigned.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["plan_path"], "docs/project-harness/tasks/mvp-001/plan.md")
        self.assertNotIn("plan", item.get("artifacts") or {})

        self.write_plan("tasks/mvp-001/plan.md", "# P\n")
        sync = self.run_harness("sync", "mvp-001")
        self.assertEqual(sync.returncode, 0, sync.stderr)
        state = self.run_harness("state")
        self.assertEqual(state.returncode, 0, state.stderr)

    def test_state_fails_closed_on_invalid_checklist(self) -> None:
        (self.harness / "mvp-checklist.json").write_text(
            json.dumps({"project": "incomplete"}), encoding="utf-8"
        )

        result = self.run_harness("state")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checklist is invalid", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.harness / "harness-state.json").exists())

    def test_session_init_fails_closed_on_invalid_checklist(self) -> None:
        (self.harness / "mvp-checklist.json").write_text(
            json.dumps({"project": "incomplete"}), encoding="utf-8"
        )

        result = self.run_harness("session-init")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checklist is invalid", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_state_fails_closed_on_plan_locator_conflict(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001", "doing", owner="codex", selected_in_session="codex-1",
                    plan_path="docs/project-harness/a.md",
                    artifacts={"plan": "docs/project-harness/b.md"},
                )
            ]
        )
        (self.harness / "current").mkdir(exist_ok=True)
        (self.harness / "current" / "task_plan.md").write_text(
            "# P\n\n- Checklist item: `mvp-001`\n", encoding="utf-8"
        )

        result = self.run_harness("state")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicting plan locators", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.harness / "harness-state.json").exists())

    def test_state_current_item_plan_path_comes_from_resolver(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001", "doing", owner="codex", selected_in_session="codex-1",
                    plan_path="docs/project-harness/tasks/mvp-001/plan.md",
                )
            ]
        )
        (self.harness / "current").mkdir(exist_ok=True)
        (self.harness / "current" / "task_plan.md").write_text(
            "# Active Task Plan Pointer\n\n"
            "- Checklist item: `mvp-001`\n"
            "- Active plan path: `docs/project-harness/STALE.md`\n",
            encoding="utf-8",
        )

        result = self.run_harness("state")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.harness / "harness-state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            data["current_item"]["plan_path"], "docs/project-harness/tasks/mvp-001/plan.md"
        )

    def test_malformed_config_root_fails_closed(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        (self.harness / "harness-config.json").write_text(
            '"just a string"', encoding="utf-8"
        )
        before = (self.harness / "mvp-checklist.json").read_bytes()

        result = self.run_harness("add-item", "mvp-002", "--title", "T", "--acceptance", "A.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("harness-config.json", result.stderr)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)

    def test_invalid_config_json_fails_closed(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        (self.harness / "harness-config.json").write_text("{broken", encoding="utf-8")

        result = self.run_harness("state")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("harness-config.json", result.stderr)

    def test_mutation_rejects_conflicting_locators(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    plan_path="docs/project-harness/a.md",
                    artifacts={"plan": "docs/project-harness/b.md"},
                )
            ]
        )
        before = (self.harness / "mvp-checklist.json").read_bytes()

        result = self.run_harness("update-item", "mvp-001", "--title", "Renamed")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicting plan locators", result.stderr)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)

    def test_update_plan_repairs_existing_conflict(self) -> None:
        self.write_checklist(
            [
                base_item(
                    "mvp-001",
                    plan_path="docs/project-harness/a.md",
                    artifacts={"plan": "docs/project-harness/b.md"},
                )
            ]
        )
        (self.harness / "a.md").write_text("# A\n", encoding="utf-8")

        result = self.run_harness(
            "update-item", "mvp-001", "--plan", "docs/project-harness/a.md"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["plan_path"], "docs/project-harness/a.md")
        self.assertEqual(item["artifacts"]["plan"], "docs/project-harness/a.md")

    def test_migrate_replace_failure_keeps_old_usable(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        old_bytes = (self.harness / "mvp-checklist.json").read_bytes()
        ci = self.load_checklist_items()
        args = argparse.Namespace(ack_managed_profile=False)

        with mock.patch.object(
            ci.os, "replace", side_effect=OSError(errno.EIO, "injected rename failure")
        ):
            with self.assertRaises(SystemExit):
                ci.do_migrate(args)

        self.assertTrue((self.harness / "mvp-checklist.json").exists())
        self.assertFalse((self.harness / "harness-checklist.json").exists())
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), old_bytes)

    def test_migrate_fsync_failure_leaves_single_authority(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        old_bytes = (self.harness / "mvp-checklist.json").read_bytes()
        ci = self.load_checklist_items()
        args = argparse.Namespace(ack_managed_profile=False)

        with mock.patch.object(
            ci, "_fsync_dir", side_effect=OSError(errno.EIO, "injected fsync failure")
        ):
            with self.assertRaises(SystemExit):
                ci.do_migrate(args)

        self.assertTrue((self.harness / "harness-checklist.json").exists())
        self.assertFalse((self.harness / "mvp-checklist.json").exists())
        self.assertEqual((self.harness / "harness-checklist.json").read_bytes(), old_bytes)

    def test_templates_default_to_harness_checklist(self) -> None:
        """New-project docs default to harness-checklist.json; the legacy name
        only appears as a compatibility note."""
        config_template = (
            SKILL_DIR / "references" / "harness-config-template.json"
        ).read_text(encoding="utf-8")
        self.assertIn('"deployment_profile": "standalone"', config_template)

        planning_template = (
            SKILL_DIR / "references" / "planning-files-template.md"
        ).read_text(encoding="utf-8")
        self.assertIn("harness-checklist.json", planning_template)
        self.assertIn("mvp-checklist.json", planning_template)  # legacy as compatibility only
        self.assertIn("migrate-checklist", planning_template)

    def test_dual_authority_message_keeps_exactly_one(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        self.write_checklist_file("harness-checklist.json", [base_item("mvp-001")])

        result = self.run_harness("add-item", "mvp-002", "--title", "T", "--acceptance", "A.")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dual checklist authority", result.stderr)
        self.assertIn("keep exactly one authority", result.stderr)

    # ------------------------------------------------------------------
    # U1 Round 4: reviewer-finding regressions
    # ------------------------------------------------------------------

    def test_single_locator_dotdot_rejected_then_repairable(self) -> None:
        self.write_checklist(
            [base_item("mvp-001", plan_path="docs/project-harness/../escape/plan.md")]
        )
        before = (self.harness / "mvp-checklist.json").read_bytes()

        # a single locator containing '..' must block any unrelated mutation
        result = self.run_harness("update-item", "mvp-001", "--title", "Renamed")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains '..'", result.stderr)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)

        # update-item --plan repairs the locator inside the callback
        self.write_plan("clean/plan.md", "# P\n")
        repaired = self.run_harness(
            "update-item", "mvp-001", "--plan", "docs/project-harness/clean/plan.md"
        )
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        item = self.read_checklist()["items"][0]
        self.assertEqual(item["plan_path"], "docs/project-harness/clean/plan.md")

    def test_non_current_locator_conflict_blocks_state_and_validate(self) -> None:
        self.write_checklist(
            [
                base_item("mvp-001"),
                base_item(
                    "mvp-002",
                    plan_path="docs/project-harness/a.md",
                    artifacts={"plan": "docs/project-harness/b.md"},
                ),
            ]
        )
        (self.harness / "a.md").write_text("# A\n", encoding="utf-8")
        (self.harness / "b.md").write_text("# B\n", encoding="utf-8")

        state = self.run_harness("state")
        self.assertNotEqual(state.returncode, 0)
        self.assertIn("conflicting plan locators", state.stderr)
        self.assertFalse((self.harness / "harness-state.json").exists())

        validate = self.run_harness("validate")
        self.assertNotEqual(validate.returncode, 0)
        self.assertIn("conflicting plan locators", validate.stderr)

        repair = self.run_harness("update-item", "mvp-002", "--plan", "docs/project-harness/a.md")
        self.assertEqual(repair.returncode, 0, repair.stderr)

        state_ok = self.run_harness("state")
        self.assertEqual(state_ok.returncode, 0, state_ok.stderr)
        validate_ok = self.run_harness("validate")
        self.assertEqual(validate_ok.returncode, 0, validate_ok.stderr)

    def test_fsync_dir_fsync_unsupported_errno_falls_back(self) -> None:
        hc = self.load_harness_common()
        with mock.patch.object(
            hc.os, "fsync", side_effect=OSError(errno.EINVAL, "unsupported")
        ):
            hc._fsync_dir(self.harness)  # must not raise

    def test_fsync_dir_fsync_ordinary_error_propagates_and_closes_fd(self) -> None:
        hc = self.load_harness_common()
        closed: list[int] = []
        original_close = hc.os.close

        def tracking_close(fd: int) -> None:
            closed.append(fd)
            return original_close(fd)

        with mock.patch.object(hc.os, "close", side_effect=tracking_close):
            with mock.patch.object(
                hc.os, "fsync", side_effect=OSError(errno.EIO, "io error")
            ):
                with self.assertRaises(OSError) as ctx:
                    hc._fsync_dir(self.harness)
                self.assertEqual(ctx.exception.errno, errno.EIO)
        self.assertEqual(len(closed), 1)  # directory fd is always closed

    # ------------------------------------------------------------------
    # U1 Round 5: safe item ids, locator types, EBADF
    # ------------------------------------------------------------------

    def test_add_item_rejects_traversal_id(self) -> None:
        self.write_checklist([base_item("mvp-001")])
        before = (self.harness / "mvp-checklist.json").read_bytes()
        project_entries_before = sorted(path.name for path in self.project.iterdir())

        result = self.run_harness(
            "add-item", "../../escape", "--title", "T", "--acceptance", "A."
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path separator", result.stderr)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.project.iterdir()), project_entries_before)

    def test_hand_edited_traversal_id_blocked_everywhere(self) -> None:
        self.write_checklist(
            [base_item("mvp-001"), base_item("sub/evil")]
        )

        validate = self.run_harness("validate")
        self.assertNotEqual(validate.returncode, 0)
        self.assertIn("path separator", validate.stderr)

        state = self.run_harness("state")
        self.assertNotEqual(state.returncode, 0)
        self.assertIn("path separator", state.stderr)
        self.assertFalse((self.harness / "harness-state.json").exists())

        before = (self.harness / "mvp-checklist.json").read_bytes()
        mutation = self.run_harness("update-item", "sub/evil", "--title", "X")
        self.assertNotEqual(mutation.returncode, 0)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)

        start = self.run_harness("start", "sub/evil", "codex", "codex-1")
        self.assertNotEqual(start.returncode, 0)
        self.assertFalse((self.harness / "tasks" / "sub").exists())
        self.assertFalse((self.harness / "tasks" / "evil").exists())

        # safe existing ids keep working on a clean checklist
        self.write_checklist([base_item("mvp-001")])
        ok = self.run_harness("update-item", "mvp-001", "--title", "Fine")
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_locator_type_problems_blocked_and_repairable(self) -> None:
        self.write_plan("clean/plan.md", "# P\n")
        clean_plan = "docs/project-harness/clean/plan.md"

        # bad plan_path type
        self.write_checklist([base_item("mvp-001", plan_path=123)])
        validate = self.run_harness("validate")
        self.assertNotEqual(validate.returncode, 0)
        self.assertIn("plan_path must be a string or null", validate.stderr)
        state = self.run_harness("state")
        self.assertNotEqual(state.returncode, 0)
        self.assertIn("plan_path must be a string or null", state.stderr)
        before = (self.harness / "mvp-checklist.json").read_bytes()
        mutation = self.run_harness("update-item", "mvp-001", "--title", "X")
        self.assertNotEqual(mutation.returncode, 0)
        self.assertIn("plan_path must be a string or null", mutation.stderr)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)
        repaired = self.run_harness("update-item", "mvp-001", "--plan", clean_plan)
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(self.read_checklist()["items"][0]["plan_path"], clean_plan)
        self.assertEqual(self.run_harness("validate").returncode, 0)

        # bad artifacts.plan type
        self.write_checklist([base_item("mvp-002", artifacts={"plan": ["list"]})])
        validate = self.run_harness("validate")
        self.assertNotEqual(validate.returncode, 0)
        self.assertIn("artifacts.plan must be a string or null", validate.stderr)
        state = self.run_harness("state")
        self.assertNotEqual(state.returncode, 0)
        self.assertIn("artifacts.plan must be a string or null", state.stderr)
        before = (self.harness / "mvp-checklist.json").read_bytes()
        mutation = self.run_harness("update-item", "mvp-002", "--title", "X")
        self.assertNotEqual(mutation.returncode, 0)
        self.assertIn("artifacts.plan must be a string or null", mutation.stderr)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)
        repaired = self.run_harness("update-item", "mvp-002", "--plan", clean_plan)
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(self.read_checklist()["items"][0]["artifacts"]["plan"], clean_plan)
        self.assertEqual(self.run_harness("validate").returncode, 0)
        self.assertEqual(self.run_harness("state").returncode, 0)

    def test_fsync_dir_ebadf_propagates_and_closes_fd(self) -> None:
        hc = self.load_harness_common()
        closed: list[int] = []
        original_close = hc.os.close

        def tracking_close(fd: int) -> None:
            closed.append(fd)
            return original_close(fd)

        with mock.patch.object(hc.os, "close", side_effect=tracking_close):
            with mock.patch.object(
                hc.os, "fsync", side_effect=OSError(errno.EBADF, "bad fd")
            ):
                with self.assertRaises(OSError) as ctx:
                    hc._fsync_dir(self.harness)
                self.assertEqual(ctx.exception.errno, errno.EBADF)
        self.assertEqual(len(closed), 1)

        with mock.patch.object(
            hc.os, "open", side_effect=OSError(errno.EBADF, "bad fd")
        ):
            with self.assertRaises(OSError) as ctx:
                hc._fsync_dir(self.harness)
            self.assertEqual(ctx.exception.errno, errno.EBADF)

    # ------------------------------------------------------------------
    # U1 Round 6: visible Unicode ids, presence-keyed locator repair
    # ------------------------------------------------------------------

    def test_unicode_safe_ids_accepted_and_control_ids_rejected(self) -> None:
        self.write_checklist([base_item("mvp-001")])

        # visible Unicode (CJK) is a safe id and works end to end
        add = self.run_harness("add-item", "任务-001", "--title", "任务", "--acceptance", "可验证。")
        self.assertEqual(add.returncode, 0, add.stderr)
        update = self.run_harness("update-item", "任务-001", "--title", "更新后")
        self.assertEqual(update.returncode, 0, update.stderr)

        # control/format ids are rejected with bytes unchanged (NUL cannot
        # cross a subprocess boundary, so it is covered in-process below)
        for bad_id in ("bad\nid", "bad\u202eid"):
            with self.subTest(bad_id=bad_id):
                self.write_checklist([base_item("mvp-001")])
                before = (self.harness / "mvp-checklist.json").read_bytes()
                result = self.run_harness(
                    "add-item", bad_id, "--title", "T", "--acceptance", "A."
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("control/format/surrogate", result.stderr)
                self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)

        hc = self.load_harness_common()
        self.assertIsNotNone(hc.safe_item_id_problem("bad\x00id"))
        self.assertIsNone(hc.safe_item_id_problem("任务-001"))

    def test_update_plan_repairs_all_locator_fields(self) -> None:
        self.write_plan("clean/plan.md", "# P\n")
        clean_plan = "docs/project-harness/clean/plan.md"

        cases = [
            ("neither", {}),
            ("both-bad", {"plan_path": 123, "artifacts": {"plan": ["list"]}}),
            ("plan-good-artifacts-bad", {"plan_path": "docs/project-harness/old.md", "artifacts": {"plan": ["list"]}}),
            ("plan-bad-artifacts-good", {"plan_path": 123, "artifacts": {"plan": "docs/project-harness/old.md"}}),
            ("artifacts-only", {"artifacts": {"plan": ["list"]}}),
        ]
        for label, overrides in cases:
            with self.subTest(label=label):
                self.write_checklist([base_item("mvp-001", **overrides)])
                result = self.run_harness("update-item", "mvp-001", "--plan", clean_plan)
                self.assertEqual(result.returncode, 0, result.stderr)
                item = self.read_checklist()["items"][0]
                artifacts = item.get("artifacts") or {}
                if not overrides or "plan_path" in overrides:
                    self.assertEqual(item.get("plan_path"), clean_plan)
                if isinstance(overrides.get("artifacts"), dict) and "plan" in overrides["artifacts"]:
                    self.assertEqual(artifacts.get("plan"), clean_plan)
                validate = self.run_harness("validate")
                self.assertEqual(validate.returncode, 0, validate.stderr)
                state = self.run_harness("state")
                self.assertEqual(state.returncode, 0, state.stderr)

    # ------------------------------------------------------------------
    # U1 Round 7: raw id validated before normalization; start validates
    # the current checklist before scaffolding
    # ------------------------------------------------------------------

    def test_raw_control_ids_rejected_before_normalization(self) -> None:
        for bad_id in ("item\n", "\titem", "item\u202e", "  "):
            with self.subTest(bad_id=bad_id):
                self.write_checklist([base_item("mvp-001")])
                before = (self.harness / "mvp-checklist.json").read_bytes()
                result = self.run_harness(
                    "add-item", bad_id, "--title", "T", "--acceptance", "A."
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR", result.stderr)
                self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)

        # ordinary surrounding spaces still follow legacy normalization
        self.write_checklist([base_item("mvp-001")])
        spaced = self.run_harness("add-item", "  mvp-002  ", "--title", "T", "--acceptance", "A.")
        self.assertEqual(spaced.returncode, 0, spaced.stderr)
        self.assertIn("mvp-002", [entry["id"] for entry in self.read_checklist()["items"]])

    def test_start_fails_before_scaffold_on_invalid_checklist(self) -> None:
        # schema-invalid current checklist: item with empty acceptance
        self.write_checklist([base_item("mvp-001", acceptance="")])
        before = (self.harness / "mvp-checklist.json").read_bytes()
        result = self.run_harness("start", "mvp-001", "codex", "codex-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checklist is invalid", result.stderr)
        self.assertEqual((self.harness / "mvp-checklist.json").read_bytes(), before)
        self.assertFalse((self.harness / "tasks" / "mvp-001").exists())

        # runtime-invalid current checklist: unsafe id item without locator
        self.write_checklist([base_item("sub/evil")])
        result = self.run_harness("start", "sub/evil", "codex", "codex-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime authority problems", result.stderr)
        self.assertFalse((self.harness / "tasks" / "sub").exists())
        self.assertFalse((self.harness / "tasks" / "evil").exists())


if __name__ == "__main__":
    unittest.main()
