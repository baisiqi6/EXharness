from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
        write_json(
            self.harness / "mvp-checklist.json",
            {
                "project": "fixture-project",
                "harness_root": "docs/project-harness",
                "updated_at": "2026-05-12",
                "items": items,
            },
        )

    def read_checklist(self) -> dict:
        return json.loads((self.harness / "mvp-checklist.json").read_text(encoding="utf-8"))

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
        self.assertEqual(item["workflow"]["status"], "declined")
        self.assertIsNone(item["owner"])
        events = self.read_events()
        self.assertEqual(events[-1]["type"], "DECLINE")

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


if __name__ == "__main__":
    unittest.main()
