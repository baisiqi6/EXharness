"""Behavior tests for the read-only workspace inventory script.

Only Python standard library. Each test builds throwaway Git repositories under a
temporary directory and never touches the real checkout.
"""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "check_workspace_state.py"


def load_script():
    spec = importlib.util.spec_from_file_location("check_workspace_state", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_git(cwd, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def init_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    run_git(repo, "config", "commit.gpgsign", "false")
    (repo / "data.txt").write_text("one\n", encoding="utf-8")
    run_git(repo, "add", "data.txt")
    run_git(repo, "commit", "-q", "-m", "one")
    run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


class WorkspaceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exharness-workspace-"))
        self.module = load_script()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_canonical_has_no_warnings(self):
        repo = init_repo(self.tmp)
        report = self.module.collect(repo, "main", "origin")
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["worktree_count"], 1)
        canonical = report["canonical"]
        self.assertEqual(canonical["branch"], "main")
        self.assertEqual(canonical["tracked_changes"], 0)
        self.assertEqual(canonical["untracked_files"], 0)
        self.assertIsNone(canonical["error"])
        self.assertEqual(report["remote_ref_sha"], report["local_integration_sha"])

    def test_canonical_on_feature_branch_is_reported(self):
        repo = init_repo(self.tmp)
        run_git(repo, "switch", "-q", "-c", "feature/work")
        report = self.module.collect(repo, "main", "origin")
        self.assertIn("canonical_not_integration", report["warnings"])
        self.assertEqual(report["canonical"]["branch"], "feature/work")

    def test_dirty_canonical_is_reported(self):
        repo = init_repo(self.tmp)
        (repo / "untracked.txt").write_text("local only\n", encoding="utf-8")
        (repo / "data.txt").write_text("changed\n", encoding="utf-8")
        report = self.module.collect(repo, "main", "origin")
        self.assertIn("canonical_has_changes", report["warnings"])
        self.assertEqual(report["canonical"]["tracked_changes"], 1)
        self.assertEqual(report["canonical"]["untracked_files"], 1)

    def test_local_main_behind_cached_remote(self):
        repo = init_repo(self.tmp)
        (repo / "second.txt").write_text("two\n", encoding="utf-8")
        run_git(repo, "add", "second.txt")
        run_git(repo, "commit", "-q", "-m", "two")
        run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        run_git(repo, "reset", "-q", "--hard", "HEAD~1")
        report = self.module.collect(repo, "main", "origin")
        self.assertIn("local_integration_behind", report["warnings"])
        self.assertEqual(report["local_integration"], {"ahead": 0, "behind": 1})

    def test_local_main_ahead_of_cached_remote(self):
        repo = init_repo(self.tmp)
        (repo / "second.txt").write_text("two\n", encoding="utf-8")
        run_git(repo, "add", "second.txt")
        run_git(repo, "commit", "-q", "-m", "two")
        report = self.module.collect(repo, "main", "origin")
        self.assertIn("local_integration_ahead", report["warnings"])
        self.assertEqual(report["local_integration"], {"ahead": 1, "behind": 0})

    def test_linked_worktree_locates_primary_checkout(self):
        repo = init_repo(self.tmp)
        worktree = self.tmp / "linked-task"
        run_git(repo, "worktree", "add", "-q", "-b", "feature/task", str(worktree), "main")
        report = self.module.collect(worktree, "main", "origin")
        self.assertEqual(Path(report["canonical"]["path"]), repo.resolve())
        self.assertEqual(report["worktree_count"], 2)
        rows = {Path(row["path"]).name: row for row in report["worktrees"]}
        self.assertIn("linked-task", rows)
        self.assertEqual(rows["linked-task"]["branch"], "feature/task")
        self.assertTrue(rows["linked-task"]["head_in_integration"])
        self.assertIsNone(rows["linked-task"]["error"])

    def test_missing_cached_remote_ref_is_disclosed_not_guessed(self):
        repo = init_repo(self.tmp)
        run_git(repo, "update-ref", "-d", "refs/remotes/origin/main")
        report = self.module.collect(repo, "main", "origin")
        self.assertIn("cached_remote_ref_missing", report["warnings"])
        self.assertIsNone(report["remote_ref_sha"])
        self.assertEqual(report["canonical"]["head_in_integration"], None)

    def test_submodule_commit_change_is_a_tracked_change_without_scanning_its_files(self):
        repo = init_repo(self.tmp)
        source_base = self.tmp / "submodule-source"
        source_base.mkdir()
        source = init_repo(source_base)
        run_git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "child")
        run_git(repo, "commit", "-q", "-m", "track child")
        child = repo / "child"
        run_git(child, "config", "user.email", "test@example.com")
        run_git(child, "config", "user.name", "Test User")
        run_git(child, "config", "commit.gpgsign", "false")
        (child / "data.txt").write_text("new child commit\n", encoding="utf-8")
        run_git(child, "add", "data.txt")
        run_git(child, "commit", "-q", "-m", "advance child")
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    run_git(repo, "add", "child")
                report = self.module.collect(repo, "main", "origin")
                self.assertEqual(report["canonical"]["tracked_changes"], 1)
                self.assertIn("canonical_has_changes", report["warnings"])

        # Restore the superproject pointer to the current child commit. Internal
        # tracked/untracked file changes alone stay outside this report's scope.
        run_git(repo, "commit", "-q", "-m", "accept child pointer")
        (child / "data.txt").write_text("internal edit\n", encoding="utf-8")
        (child / "untracked.txt").write_text("internal only\n", encoding="utf-8")
        report = self.module.collect(repo, "main", "origin")
        self.assertEqual(report["canonical"]["tracked_changes"], 0)
        self.assertNotIn("canonical_has_changes", report["warnings"])

    def test_external_git_filter_blocks_clean_claim(self):
        repo = init_repo(self.tmp)
        (repo / ".gitattributes").write_text("*.evil filter=evil\n", encoding="utf-8")
        (repo / "sample.evil").write_text("payload\n", encoding="utf-8")
        run_git(repo, "add", ".gitattributes", "sample.evil")
        run_git(repo, "commit", "-q", "-m", "add filtered file")
        run_git(repo, "config", "filter.evil.clean", "cat")
        report = self.module.collect(repo, "main", "origin")
        self.assertEqual(
            report["canonical"]["error"], "external_git_filter_not_assessed"
        )
        self.assertIn("canonical_unreadable", report["warnings"])

    def test_inventory_does_not_mutate_repository(self):
        repo = init_repo(self.tmp)
        before_head = run_git(repo, "rev-parse", "HEAD")
        before_status = run_git(repo, "status", "--porcelain")
        self.module.collect(repo, "main", "origin")
        self.module.collect(repo, "main", "origin")
        self.assertEqual(run_git(repo, "rev-parse", "HEAD"), before_head)
        self.assertEqual(run_git(repo, "status", "--porcelain"), before_status)

    def test_invalid_repository_returns_git_read_error(self):
        missing = self.tmp / "not-a-repo"
        missing.mkdir()
        with self.assertRaises(self.module.GitReadError):
            self.module.collect(missing, "main", "origin")


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exharness-workspace-cli-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_json_output_is_structured(self):
        repo = init_repo(self.tmp)
        result = self.run_cli("--repo", str(repo), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["integration_branch"], "main")
        self.assertIn("canonical", report)
        self.assertIn("worktrees", report)
        self.assertEqual(report["warnings"], [])

    def test_invalid_repo_exits_2(self):
        missing = self.tmp / "missing"
        missing.mkdir()
        result = self.run_cli("--repo", str(missing), "--json")
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertIn("error", report)

    def test_human_output_mentions_no_authorization(self):
        repo = init_repo(self.tmp)
        result = self.run_cli("--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no cleanup", result.stdout)


if __name__ == "__main__":
    unittest.main()
