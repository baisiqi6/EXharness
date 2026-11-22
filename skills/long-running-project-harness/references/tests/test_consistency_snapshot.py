"""Real Git fixtures for frozen consistency input snapshots."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "consistency_snapshot.py"
spec = importlib.util.spec_from_file_location("consistency_snapshot", SCRIPT)
snapshots = None
if SCRIPT.exists():
    snapshots = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = snapshots
    spec.loader.exec_module(snapshots)


@unittest.skipUnless(shutil.which("git"), "Git is required")
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(snapshots, "Git snapshot capability has not been implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env_patch = mock.patch.dict(os.environ, env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.root = Path(self.temp.name) / "工程 repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "snapshot@example.invalid")
        self.git("config", "user.name", "Snapshot Fixture")
        self.git("config", "core.autocrlf", "false")
        self.write("src/app.py", b"original\n")
        self.base = self.commit()
        self.repo = snapshots.GitRepo(self.root)

    def git(self, *args, env=None, check=True):
        result = subprocess.run(["git", *args], cwd=self.root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and result.returncode:
            self.fail(result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_partial_stage_reads_index_bytes_and_freezes_all_views(self):
        self.write("src/app.py", b"staged\n")
        self.git("add", "src/app.py")
        self.write("src/app.py", b"unstaged\n")
        historical = self.repo.snapshot(self.base)
        staged = self.repo.index()
        working = self.repo.worktree()
        self.write("src/app.py", b"later\n")
        self.assertEqual(historical.read("src/app.py"), b"original\n")
        self.assertEqual(staged.read("src/app.py"), b"staged\n")
        self.assertEqual(working.read("src/app.py"), b"unstaged\n")
        self.assertEqual(historical.changed(staged), ["src/app.py"])
        self.assertEqual(historical.revision, self.base)
        self.assertEqual(self.repo.head(), self.base)
        self.assertIsNone(staged.revision)
        self.assertIsNone(staged.read("missing"))

    def test_clean_autocrlf_checkout_has_index_identity_and_exact_physical_read(self):
        self.git("config", "core.autocrlf", "true")
        (self.root / "src/app.py").unlink()
        self.git("checkout", "--", "src/app.py")
        self.assertEqual(self.git("status", "--short"), "")
        staged = self.repo.index()
        working = self.repo.worktree()
        self.assertEqual(working.read("src/app.py"), b"original\r\n")
        self.assertEqual(staged.read("src/app.py"), b"original\n")
        self.assertEqual(staged.changed(working), [])
        self.assertEqual(staged.digest(["src/**"]), working.digest(["src/**"]))
        self.write("src/app.py", b"changed\r\n")
        changed = self.repo.worktree()
        self.assertNotEqual(changed.digest(["src/**"]), staged.digest(["src/**"]))
        self.git("add", "src/app.py")
        self.assertEqual(changed.digest(["src/**"]), self.repo.index().digest(["src/**"]))
        self.assertEqual(changed.read("src/app.py"), b"changed\r\n")

    def test_attributes_eol_crlf_normalizes_identity_with_autocrlf_disabled(self):
        self.write(".gitattributes", b"src/** text eol=crlf\n")
        self.commit()
        (self.root / "src/app.py").unlink()
        self.git("checkout", "--", "src/app.py")
        self.assertEqual(self.git("status", "--short"), "")
        working = self.repo.worktree()
        self.assertEqual(working.read("src/app.py"), b"original\r\n")
        self.assertEqual(working.digest(["src/**"]), self.repo.index().digest(["src/**"]))

    def test_explicit_binary_crlf_bytes_are_not_normalized(self):
        self.write(".gitattributes", b"src/** -text\n")
        self.write("src/app.py", b"binary-looking text\r\n")
        self.commit()
        self.git("config", "core.autocrlf", "true")
        staged = self.repo.index()
        working = self.repo.worktree()
        self.assertEqual(staged.read("src/app.py"), b"binary-looking text\r\n")
        self.assertEqual(staged.changed(working), [])
        self.write("src/app.py", b"binary-looking text\n")
        self.assertNotEqual(staged.digest(["src/**"]), self.repo.worktree().digest(["src/**"]))

    def test_text_auto_handles_mixed_text_and_binary_like_git_add(self):
        self.write(".gitattributes", b"src/** text=auto\n")
        self.write("src/app.py", b"first\r\nsecond\n")
        self.write("src/binary", b"first\r\n\0second\n")
        self.write("src/lone-cr", b"first\r\nsecond\rthird\n")
        working = self.repo.worktree()
        self.git("add", "-A")
        staged = self.repo.index()
        self.assertEqual(staged.read("src/app.py"), b"first\nsecond\n")
        self.assertEqual(staged.read("src/binary"), b"first\r\n\0second\n")
        self.assertEqual(staged.read("src/lone-cr"), b"first\r\nsecond\rthird\n")
        self.assertEqual(working.digest(["src/**"]), staged.digest(["src/**"]))
        self.assertEqual(working.read("src/app.py"), b"first\r\nsecond\n")

    def test_text_auto_keeps_existing_crlf_index_blob_as_git_does(self):
        self.write("src/app.py", b"already tracked\r\n")
        self.commit()
        self.write(".gitattributes", b"src/** text=auto\n")
        self.git("config", "core.autocrlf", "true")
        self.write("src/app.py", b"tracked with change\r\n")
        working = self.repo.worktree()
        self.git("add", "-A")
        staged = self.repo.index()
        self.assertEqual(staged.read("src/app.py"), b"tracked with change\r\n")
        self.assertEqual(working.digest(["src/**"]), staged.digest(["src/**"]))

    def test_worktree_info_attributes_override_repository_attributes(self):
        self.write(".gitattributes", b"src/** -text\n")
        self.commit()
        gitdir = Path(self.git("rev-parse", "--absolute-git-dir"))
        (gitdir / "info" / "attributes").write_bytes(b"src/** text eol=crlf\n")
        (self.root / "src/app.py").unlink()
        self.git("checkout", "--", "src/app.py")
        self.assertEqual((self.root / "src/app.py").read_bytes(), b"original\r\n")
        self.assertEqual(self.repo.worktree().digest(["src/**"]), self.repo.index().digest(["src/**"]))

    def test_custom_filter_commands_never_run_and_unknown_transform_is_incomplete(self):
        marker = Path(self.temp.name) / "filter-ran"
        helper = Path(self.temp.name) / "filter.py"
        helper.write_text("import pathlib,sys\npathlib.Path(sys.argv[1]).write_text('ran')\n"
                          "sys.stdout.buffer.write(sys.stdin.buffer.read())\n", encoding="utf-8")
        command = f'"{sys.executable}" "{helper}" "{marker}"'
        self.write(".gitattributes", b"src/** text filter=unsafe\n")
        for setting in ("clean", "process"):
            for required in ("false", "true"):
                with self.subTest(setting=setting, required=required):
                    self.git("config", "filter.unsafe." + setting, command)
                    self.git("config", "filter.unsafe.required", required)
                    with self.assertRaises(snapshots.SnapshotError):
                        self.repo.worktree()
                    self.assertFalse(marker.exists())
                    self.git("config", "--unset", "filter.unsafe." + setting)
        self.assertEqual(self.repo.index().read("src/app.py"), b"original\n")

    def test_unconfigured_optional_filter_is_noop_but_required_filter_is_incomplete(self):
        self.write(".gitattributes", b"src/** text filter=missing\n")
        self.write("src/app.py", b"original\r\n")
        working = self.repo.worktree()
        self.assertEqual(working.digest(["src/**"]), self.repo.index().digest(["src/**"]))
        self.git("config", "filter.missing.required", "true")
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.worktree()

    def test_tree_ref_and_commit_share_projection_but_keep_revision_kind(self):
        commit = self.repo.snapshot(self.base)
        tree_oid = self.git("rev-parse", "HEAD^{tree}")
        tree = self.repo.snapshot(tree_oid)
        self.assertEqual(tree.tree, tree_oid)
        self.assertEqual(commit.tree, tree_oid)
        self.assertIsNone(tree.revision)
        self.assertEqual(commit.digest(["**"]), tree.digest(["**"]))
        self.assertEqual(commit.digest(["**"]), self.repo.index().digest(["**"]))
        self.assertEqual(commit.changed(tree), [])
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.snapshot("missing-ref")

    def test_alternate_index_is_the_actual_candidate_and_is_not_written(self):
        alternate = Path(self.temp.name) / "alternate index"
        self.git("read-tree", self.base, env={**os.environ, "GIT_INDEX_FILE": str(alternate)})
        self.write("src/app.py", b"alternate candidate\n")
        self.git("add", "src/app.py", env={**os.environ, "GIT_INDEX_FILE": str(alternate)})
        before = alternate.read_bytes()
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": str(alternate)}):
            candidate = snapshots.GitRepo(self.root).index()
        self.assertEqual(candidate.read("src/app.py"), b"alternate candidate\n")
        self.assertEqual(self.repo.index().read("src/app.py"), b"original\n")
        self.assertEqual(alternate.read_bytes(), before)

    def test_worktree_tracks_deletion_untracked_unicode_and_ignored_files(self):
        self.write(".gitignore", b"ignored/\n")
        self.commit()
        old = self.repo.snapshot(self.repo.head())
        (self.root / "src/app.py").unlink()
        self.write("src/带 空格.py", b"new bytes\r\n")
        self.write("ignored/cache", b"not source")
        current = self.repo.worktree()
        self.assertIsNone(current.read("src/app.py"))
        self.assertEqual(current.read("src/带 空格.py"), b"new bytes\r\n")
        self.assertNotIn("ignored/cache", current.entries)
        self.assertEqual(old.changed(current), ["src/app.py", "src/带 空格.py"])
        self.assertFalse(any(".git" in Path(path).parts for path in current.entries))

    @unittest.skipIf(os.name == "nt", "POSIX executable and symlink modes")
    def test_modes_symlink_target_and_gitlink_are_part_of_projection(self):
        script = self.write("run.sh", b"#!/bin/sh\n")
        script.chmod(0o755)
        os.symlink("src/app.py", self.root / "link")
        self.git("add", "run.sh", "link")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},vendor")
        (self.root / "vendor").mkdir()
        staged = self.repo.index()
        self.assertEqual(staged.entries["run.sh"].mode, "100755")
        self.assertEqual(staged.entries["link"].mode, "120000")
        self.assertEqual(staged.read("link"), b"src/app.py")
        self.assertEqual(staged.entries["vendor"].kind, "commit")
        self.assertIsNone(staged.read("vendor"))
        working = self.repo.worktree()
        self.assertEqual(working.entries["vendor"].oid, self.base)
        script.chmod(0o644)
        (self.root / "link").unlink()
        os.symlink("run.sh", self.root / "link")
        self.assertEqual(staged.changed(self.repo.worktree()), ["link", "run.sh"])

    def test_globs_are_posix_and_recursive_double_star_matches_root(self):
        expected = [("src/a.py", "src/*.py", True),
                    ("src/nested/a.py", "src/*.py", False),
                    ("src/nested/a.py", "src/**/*.py", True),
                    ("src/a.py", "src/**/*.py", True),
                    ("a.py", "**/*.py", True),
                    ("src/A.py", "src/a.py", False),
                    ("src/a.txt", "src/[ab].txt", True)]
        for path, pattern, wanted in expected:
            with self.subTest(path=path, pattern=pattern):
                self.assertEqual(snapshots.match_path(path, [pattern]), wanted)
        historical = self.repo.snapshot(self.base)
        self.write("notes.md", b"unrelated")
        working = self.repo.worktree()
        self.assertEqual(historical.digest(["src/**"]), working.digest(["src/**"]))
        self.assertEqual(historical.digest(["**"], exclude=["src/**"]),
                         working.digest(["**"], exclude=["src/**", "notes.md"]))

    def test_rename_and_deletion_change_projection_and_changed_paths(self):
        before = self.repo.snapshot(self.base)
        (self.root / "src/app.py").rename(self.root / "src/moved.py")
        after = self.repo.worktree()
        self.assertEqual(before.changed(after), ["src/app.py", "src/moved.py"])
        self.assertNotEqual(before.digest(["src/**"]), after.digest(["src/**"]))

    def test_conflicted_index_is_incomplete(self):
        branch = self.git("symbolic-ref", "--short", "HEAD")
        self.git("checkout", "-qb", "other")
        self.write("src/app.py", b"other\n")
        self.commit()
        self.git("checkout", "-q", branch)
        self.write("src/app.py", b"main\n")
        self.commit()
        self.git("merge", "other", check=False)
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.index()

    def test_intent_to_add_is_incomplete_instead_of_empty_staged_content(self):
        self.write("src/new.py", b"not actually staged\n")
        self.git("add", "-N", "src/new.py")
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.index()

    def test_index_race_is_detected(self):
        original = self.repo._run
        changed = False

        def mutate_after_listing(args, *pos, **kwargs):
            nonlocal changed
            result = original(args, *pos, **kwargs)
            if args[0] == "ls-files" and not changed:
                changed = True
                self.write("src/app.py", b"concurrent staged update\n")
                self.git("add", "src/app.py")
            return result

        with mock.patch.object(self.repo, "_run", side_effect=mutate_after_listing):
            with self.assertRaises(snapshots.SnapshotError):
                self.repo.index()

    def test_split_index_freezes_blobs_without_refreshing_shared_index(self):
        self.git("update-index", "--split-index")
        gitdir = Path(self.git("rev-parse", "--absolute-git-dir"))
        shared = {path: path.read_bytes() for path in gitdir.glob("sharedindex.*")}
        index_bytes = (gitdir / "index").read_bytes()
        self.assertEqual(self.repo.index().read("src/app.py"), b"original\n")
        self.assertEqual((gitdir / "index").read_bytes(), index_bytes)
        self.assertEqual({path: path.read_bytes() for path in shared}, shared)
        stamps = {path: (path.stat().st_mtime_ns, path.stat().st_ctime_ns) for path in shared}
        self.repo.worktree()
        self.assertEqual({path: (path.stat().st_mtime_ns, path.stat().st_ctime_ns)
                          for path in shared}, stamps)

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_symlink_replacing_directory_does_not_follow_cached_children(self):
        external = Path(self.temp.name) / "external"
        external.mkdir()
        (external / "app.py").write_bytes(b"must not appear as src/app.py\n")
        (self.root / "src/app.py").unlink()
        (self.root / "src").rmdir()
        os.symlink(external, self.root / "src")
        working = self.repo.worktree()
        self.assertNotIn("src/app.py", working.entries)
        self.assertEqual(working.entries["src"].mode, "120000")

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_filemode_false_does_not_hide_symlink_replaced_by_regular_file(self):
        os.symlink("src/app.py", self.root / "link")
        self.commit()
        self.git("config", "core.filemode", "false")
        self.git("config", "core.symlinks", "true")
        (self.root / "link").unlink()
        self.write("link", b"src/app.py")
        working = self.repo.worktree()
        self.assertEqual(working.entries["link"].mode, "100644")
        self.assertEqual(self.repo.snapshot(self.repo.head()).changed(working), ["link"])

    def test_missing_sparse_worktree_content_is_not_reported_as_deletion(self):
        self.git("update-index", "--skip-worktree", "src/app.py")
        (self.root / "src/app.py").unlink()
        self.assertEqual(self.repo.index().read("src/app.py"), b"original\n")
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.worktree()

    def test_first_parent_excludes_side_history_and_refuses_unproven_start(self):
        self.write("src/app.py", b"first\n")
        first = self.commit()
        branch = self.git("symbolic-ref", "--short", "HEAD")
        self.git("checkout", "-qb", "side")
        self.write("side.py", b"side\n")
        side = self.commit()
        self.git("checkout", "-q", branch)
        self.write("notes.md", b"main\n")
        second = self.commit()
        self.git("merge", "--no-ff", "-qm", "merge", "side")
        tip = self.repo.head()
        self.assertEqual(self.repo.first_parent(self.base, tip), [first, second, tip])
        self.assertEqual(self.repo.parent(tip), second)
        self.assertEqual(self.repo.parents(tip), [second, side])
        self.assertIsNone(self.repo.parent(self.base))
        self.assertTrue(self.repo.is_ancestor(side, tip))
        self.assertFalse(self.repo.is_ancestor(tip, side))
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.first_parent(side, tip)
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.first_parent(self.base, tip, limit=2)

    def test_missing_blob_is_incomplete_and_prior_snapshot_stays_frozen(self):
        frozen = self.repo.snapshot(self.base)
        oid = frozen.entries["src/app.py"].oid
        gitdir = Path(self.git("rev-parse", "--absolute-git-dir"))
        missing = gitdir / "objects" / oid[:2] / oid[2:]
        missing.chmod(0o600)  # Git objects carry the read-only attribute on Windows.
        missing.unlink()
        self.assertEqual(frozen.read("src/app.py"), b"original\n")
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.GitRepo(self.root).snapshot(self.base)

    def test_shallow_history_does_not_turn_boundary_into_root(self):
        self.write("src/app.py", b"second\n")
        tip = self.commit()
        clone = Path(self.temp.name) / "shallow"
        self.git("clone", "-q", "--depth=1", self.root.as_uri(), str(clone))
        shallow = snapshots.GitRepo(clone)
        self.assertEqual(shallow.snapshot(tip).read("src/app.py"), b"second\n")
        with self.assertRaises(snapshots.SnapshotError):
            shallow.parent(tip)
        with self.assertRaises(snapshots.SnapshotError):
            shallow.first_parent(self.base, tip)

    def test_absent_commit_object_is_incomplete_without_fetch_or_zero_history(self):
        self.write("src/app.py", b"second\n")
        tip = self.commit()
        self.write("src/app.py", b"third\n")
        latest = self.commit()
        gitdir = Path(self.git("rev-parse", "--absolute-git-dir"))
        missing = gitdir / "objects" / self.base[:2] / self.base[2:]
        missing.chmod(0o600)
        missing.unlink()
        self.assertEqual(self.repo.snapshot(tip).read("src/app.py"), b"second\n")
        self.assertEqual(self.repo.first_parent(tip, tip), [])
        self.assertEqual(self.repo.first_parent(tip, latest), [latest])
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.parent(tip)
        with self.assertRaises(snapshots.SnapshotError):
            self.repo.first_parent(self.base, tip)

    def test_sha256_repository_uses_matching_git_blob_identity_for_worktree(self):
        second = Path(self.temp.name) / "sha256"
        result = subprocess.run(["git", "init", "-q", "--object-format=sha256", str(second)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            self.skipTest("Git lacks SHA-256 repositories")
        subprocess.run(["git", "-C", str(second), "config", "core.autocrlf", "false"], check=True)
        (second / "file").write_bytes(b"same source\r\n")
        subprocess.run(["git", "-C", str(second), "add", "file"], check=True)
        repo = snapshots.GitRepo(second)
        staged = repo.index()
        working = repo.worktree()
        self.assertEqual(len(staged.entries["file"].oid), 64)
        self.assertEqual(staged.changed(working), [])

    def test_initialized_gitlink_observes_submodule_head_without_entering_its_files(self):
        child = self.root / "vendor"
        child.mkdir()
        for arguments in [("init", "-q"), ("config", "user.name", "Child"),
                          ("config", "user.email", "child@example.invalid")]:
            subprocess.run(["git", "-C", str(child), *arguments], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (child / "internal").write_bytes(b"first\n")
        subprocess.run(["git", "-C", str(child), "add", "internal"], check=True)
        subprocess.run(["git", "-C", str(child), "commit", "-qm", "first"], check=True)
        first = subprocess.check_output(["git", "-C", str(child), "rev-parse", "HEAD"]).decode().strip()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{first},vendor")
        staged = self.repo.index()
        (child / "internal").write_bytes(b"second\n")
        subprocess.run(["git", "-C", str(child), "commit", "-qam", "second"], check=True)
        second = subprocess.check_output(["git", "-C", str(child), "rev-parse", "HEAD"]).decode().strip()
        working = self.repo.worktree()
        self.assertEqual(working.entries["vendor"].oid, second)
        self.assertEqual(staged.changed(working), ["vendor"])
        self.assertNotIn("vendor/internal", working.entries)

    def test_worktree_root_is_physical_linked_worktree_not_canonical(self):
        linked = Path(self.temp.name) / "linked worktree"
        self.git("worktree", "add", "-qb", "linked", str(linked))
        (linked / "src/app.py").write_bytes(b"linked only\n")
        local = snapshots.GitRepo(linked / "src")
        self.assertEqual(local.root, linked.resolve())
        self.assertEqual(local.worktree().read("src/app.py"), b"linked only\n")
        self.assertEqual(self.repo.worktree().read("src/app.py"), b"original\n")

    def test_snapshot_calls_do_not_change_index_objects_refs_or_metadata(self):
        gitdir = Path(self.git("rev-parse", "--absolute-git-dir"))

        def state():
            return {str(path.relative_to(gitdir)): path.read_bytes()
                    for path in gitdir.rglob("*") if path.is_file()}

        before = state()
        self.repo.snapshot(self.base)
        self.repo.index()
        self.repo.worktree()
        self.repo.first_parent(self.base, self.base)
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
