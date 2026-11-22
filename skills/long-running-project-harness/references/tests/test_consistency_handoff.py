from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_runtime_scripts as fixtures


class ConsistencyHandoffTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.HarnessRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.project, self.harness = self.f.project, self.f.harness
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.f.write_checklist([fixtures.base_item("task-a"), fixtures.base_item("task-b")])
        for item in ("task-a", "task-b"):
            self.f.write_plan(f"tasks/{item}/plan.md", f"# {item}\n\nOriginal plan.\n")
            source = self.project / "src" / f"{item}.py"
            source.parent.mkdir(exist_ok=True)
            source.write_text("value = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "adoption")
        config = json.loads((self.harness / "harness-config.json").read_text())
        config["coverage"] = {
            "version": 1, "enabled": True, "adopted_at": self.git("rev-parse", "HEAD").strip(),
            "source_roots": ["src/**"], "exclude": [],
            "defaults": {"warn_at": 1, "block_at": 3},
            "groups": [{"id": item, "sources": [f"src/{item}.py"],
                        "record": {"item": item}, "rules": ["record", "review"]}
                       for item in ("task-a", "task-b")],
        }
        fixtures.write_json(self.harness / "harness-config.json", config)

    def git(self, *args):
        p = subprocess.run(["git", *args], cwd=self.project, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, str(self.f.script_dir / script), *args],
                              cwd=self.project, capture_output=True, text=True)

    def handoff(self, item="task-a", *extra):
        result = self.run_script("prepare_handoff_packet.py", "--item", item,
                                 "--target", "receiver", "--actor", "operator", *extra)
        self.assertEqual(result.returncode, 0, result.stderr)

    def accept(self, item="task-a", owner="receiver"):
        return self.run_script("workflow_transition.py", "accept", "--item", item,
                               "--owner", owner, "--session", "receiver-1")

    def state(self):
        return (self.harness / "mvp-checklist.json").read_bytes()

    def test_plan_changed_after_handoff_accept_is_readonly_failure(self):
        self.handoff()
        self.f.write_plan("tasks/task-a/plan.md", "# Changed after handoff\n")
        before = self.state()
        events = (self.harness / "events.jsonl").read_bytes()
        result = self.accept()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("handoff", result.stderr.lower())
        self.assertEqual(self.state(), before)
        self.assertEqual((self.harness / "events.jsonl").read_bytes(), events)

    def test_two_pending_handoffs_use_task_scoped_packets(self):
        self.handoff()
        item = self.f.read_checklist()["items"][0]
        first = item["artifacts"]["handoff_packet"]
        first_bytes = (self.project / first).read_bytes()
        self.handoff("task-b")
        other = self.f.read_checklist()["items"][1]["artifacts"]["handoff_packet"]
        self.assertNotEqual(first, other)
        self.assertEqual((self.project / first).read_bytes(), first_bytes)
        self.assertEqual(self.accept().returncode, 0)

    def test_refresh_has_no_assignment_or_lease_replay(self):
        self.handoff()
        before = self.f.read_checklist()["items"][0]
        events = (self.harness / "events.jsonl").read_bytes()
        self.f.write_plan("tasks/task-a/plan.md", "# Refreshed plan\n")
        self.handoff("task-a", "--refresh")
        after = self.f.read_checklist()["items"][0]
        self.assertEqual(before.get("lease"), after.get("lease"))
        self.assertEqual(before["workflow"], after["workflow"])
        self.assertEqual((self.harness / "events.jsonl").read_bytes(), events)
        self.assertEqual(self.accept().returncode, 0)

    def test_source_changed_after_handoff_is_rejected(self):
        self.handoff()
        (self.project / "src/task-a.py").write_text("value = 2\n")
        before = self.state()
        result = self.accept()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state(), before)

    def test_wrong_target_cannot_force_through_binding(self):
        self.handoff()
        result = self.accept(owner="different-agent")
        self.assertNotEqual(result.returncode, 0)

    def test_shared_progress_observation_does_not_stale_handoff(self):
        self.handoff()
        (self.harness / "progress.md").write_text("# Another task advanced\n")
        self.assertEqual(self.accept().returncode, 0)

    @unittest.skipIf(os.name == "nt", "Bash wrapper smoke; Python checks run natively")
    def test_legacy_validate_remains_warning_only(self):
        self.handoff()
        self.f.write_plan("tasks/task-a/plan.md", "# Changed\n")
        result = self.f.run_harness("validate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_snapshot_locator_reuses_resolver_with_explicit_roots(self):
        common = self.f.load_harness_common()
        expected = self.project / "another-root/tasks/task-a/plan.md"
        actual = common.resolve_item_plan({"id": "task-a"}, require_exists=False,
                                         project=self.project, harness=self.project / "another-root")
        self.assertEqual(actual, expected)

    @unittest.skipIf(os.name == "nt", "Bash wrapper smoke; Python CLI runs natively")
    def test_four_entrypoints_are_routed_to_same_python_cli(self):
        for command in ("drift", "remind", "baseline", "reconcile"):
            result = self.f.run_harness(command, "--help")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage:", result.stdout)

    def test_packet_from_other_task_cannot_be_accepted(self):
        self.handoff()
        self.handoff("task-b")
        checklist = self.f.read_checklist()
        checklist["items"][0]["artifacts"]["handoff_packet"] = checklist["items"][1]["artifacts"]["handoff_packet"]
        fixtures.write_json(self.harness / "mvp-checklist.json", checklist)
        before = self.state()
        self.assertNotEqual(self.accept().returncode, 0)
        self.assertEqual(self.state(), before)

    def test_crlf_packet_header_preserves_plan_byte_binding(self):
        plan = self.harness / "tasks/task-a/plan.md"
        plan.write_bytes(b"# Plan\r\n\r\nExact CRLF.\r\n")
        self.handoff()
        locator = self.f.read_checklist()["items"][0]["artifacts"]["handoff_packet"]
        packet = self.project / locator
        packet.write_bytes(packet.read_bytes().replace(b" -->\n", b" -->\r\n", 1))
        self.assertEqual(self.accept().returncode, 0)

    def test_managed_handoff_never_mutates_local_export(self):
        config_path = self.harness / "harness-config.json"
        config = json.loads(config_path.read_text())
        config["deployment_profile"] = "coordinate-managed"
        fixtures.write_json(config_path, config)
        before = self.state()
        result = self.run_script("prepare_handoff_packet.py", "--item", "task-a", "--target", "receiver")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state(), before)

    def test_managed_pending_accept_never_mutates_local_export(self):
        self.handoff()
        path = self.harness / "harness-config.json"
        config = json.loads(path.read_text())
        config["deployment_profile"] = "coordinate-managed"
        fixtures.write_json(path, config)
        before = self.state()
        events = (self.harness / "events.jsonl").read_bytes()
        result = self.accept()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state(), before)
        self.assertEqual((self.harness / "events.jsonl").read_bytes(), events)

    def test_refresh_cannot_drop_original_source_groups(self):
        self.handoff()
        path = self.harness / "harness-config.json"
        config = json.loads(path.read_text())
        config["coverage"]["groups"] = config["coverage"]["groups"][1:]
        fixtures.write_json(path, config)
        before = self.state()
        result = self.run_script("prepare_handoff_packet.py", "--item", "task-a", "--target", "receiver", "--refresh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state(), before)

    def test_external_canonical_plan_handoff_can_be_diagnosed(self):
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        plan = Path(external.name) / "plan.md"
        plan.write_text("# External authoritative plan\n", encoding="utf-8")
        checklist = self.f.read_checklist()
        checklist["items"][0]["plan_path"] = str(plan)
        fixtures.write_json(self.harness / "mvp-checklist.json", checklist)
        self.handoff()
        result = self.run_script("consistency_cli.py", "drift", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_handoff_plan_snapshot_handles_nested_review_fences(self):
        plan = self.harness / "tasks/task-a/plan.md"
        plan.write_text('# Plan\n\n```example\n{"nested": true}\n```\n', encoding="utf-8")
        self.handoff()
        self.assertEqual(self.accept().returncode, 0)

    def test_tampered_packet_body_is_rejected_even_with_current_metadata(self):
        self.handoff()
        locator = self.f.read_checklist()["items"][0]["artifacts"]["handoff_packet"]
        packet = self.project / locator
        packet.write_bytes(packet.read_bytes().replace(b"Original plan.", b"Misleading old plan.", 1))
        before = self.state()
        self.assertNotEqual(self.accept().returncode, 0)
        self.assertEqual(self.state(), before)

    def test_observation_append_never_replaces_late_editor_content(self):
        common = self.f.load_harness_common()
        path = self.harness / "tasks/task-a/plan.md"
        original = path.read_bytes()
        real_write = os.write

        def concurrent_edit(fd, body):
            path.write_bytes(b"# Concurrent editor content\n")
            return real_write(fd, body)

        with mock.patch.object(common.os, "write", side_effect=concurrent_edit):
            with self.assertRaises(ValueError):
                common.append_observation_bytes(path, original, b"\nObservation.\n")
        self.assertTrue(path.read_bytes().startswith(b"# Concurrent editor content\n"))

    @unittest.skipIf(os.name == "nt", "POSIX open-inode replacement fixture")
    def test_observation_append_preserves_atomic_editor_replacement(self):
        common = self.f.load_harness_common()
        path = self.harness / "tasks/task-a/plan.md"
        original = path.read_bytes()
        real_write = os.write

        def concurrent_replace(fd, body):
            replacement = path.with_suffix(".new")
            replacement.write_bytes(b"# Concurrent replacement\n")
            replacement.replace(path)
            return real_write(fd, body)

        with mock.patch.object(common.os, "write", side_effect=concurrent_replace):
            with self.assertRaises(ValueError):
                common.append_observation_bytes(path, original, b"\nObservation.\n")
        self.assertEqual(path.read_bytes(), b"# Concurrent replacement\n")

    def test_staged_gate_reads_bound_plan_from_index(self):
        self.handoff()
        self.git("add", ".")
        self.git("commit", "-qm", "pending handoff")
        self.f.write_plan("tasks/task-a/plan.md", "# Unstaged changed plan\n")
        args = ("drift", "--snapshot", "staged", "--format", "json")
        old = self.run_script("consistency_cli.py", *args)
        self.assertEqual(old.returncode, 0, old.stdout + old.stderr)
        self.git("add", "docs/project-harness/tasks/task-a/plan.md")
        changed = self.run_script("consistency_cli.py", *args)
        self.assertEqual(changed.returncode, 1, changed.stdout + changed.stderr)
        self.assertIn("handoff-stale", changed.stdout)

    def test_clean_autocrlf_handoff_uses_git_record_identity_in_staged_gate(self):
        self.git("config", "core.autocrlf", "true")
        plan_path = "docs/project-harness/tasks/task-a/plan.md"
        (self.project / plan_path).unlink()
        self.git("checkout-index", "--", plan_path)
        self.assertIn(b"\r\n", (self.project / plan_path).read_bytes())
        self.handoff()
        self.git("add", ".")
        result = self.run_script("consistency_cli.py", "drift", "--snapshot", "staged", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_packet_destination_cannot_overwrite_canonical_plan(self):
        relative = "docs/project-harness/tasks/task-a/handoff-task-a.md"
        path = self.project / relative
        path.write_bytes(b"# Original canonical plan\n")
        checklist = self.f.read_checklist()
        checklist["items"][0]["plan_path"] = relative
        fixtures.write_json(self.harness / "mvp-checklist.json", checklist)
        before = self.state()
        result = self.run_script("prepare_handoff_packet.py", "--item", "task-a", "--target", "receiver")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), b"# Original canonical plan\n")
        self.assertEqual(self.state(), before)
        self.assertFalse((self.harness / "events.jsonl").exists())

    def test_packet_destination_cannot_overwrite_unrelated_existing_file(self):
        path = self.harness / "tasks/task-a/handoff-task-a.md"
        path.write_bytes(b"# Unrelated original notes\n")
        before = self.state()
        result = self.run_script("prepare_handoff_packet.py", "--item", "task-a", "--target", "receiver")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), b"# Unrelated original notes\n")
        self.assertEqual(self.state(), before)


if __name__ == "__main__":
    unittest.main()
