"""Self-containment checks for this skill.

A published skill must work when its directory is copied alone. These tests guard
three things:

1. Every relative Markdown link resolves inside the skill directory (no dangling
   or sibling-skill links, no machine-specific absolute paths).
2. Frontmatter and routing are coherent: the name matches the directory, the
   description carries trigger conditions, and every reference file is routed
   from SKILL.md.
3. A single-directory copy still passes the link checks and the bundled checker
   is runnable from that copy.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL_ROOT = Path(__file__).resolve().parents[3]
SKILL_FILE = SKILL_ROOT / "SKILL.md"
SCRIPT = SKILL_ROOT / "references" / "scripts" / "check_workspace_state.py"
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
ABSOLUTE_PATH_PATTERN = re.compile(r"(/Users/|/home/|\bC:\\\\)")


def markdown_files(root: Path):
    yield root / "SKILL.md"
    yield from sorted((root / "references").rglob("*.md"))


def broken_links(root: Path):
    broken = []
    for markdown in markdown_files(root):
        content = markdown.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(content):
            target = raw_target.strip().split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("/"):
                broken.append((markdown.relative_to(root), raw_target, "absolute path"))
                continue
            resolved = (markdown.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                broken.append((markdown.relative_to(root), raw_target, "escapes skill"))
                continue
            if not resolved.exists():
                broken.append((markdown.relative_to(root), raw_target, "missing target"))
    return broken


def frontmatter():
    content = SKILL_FILE.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise AssertionError("SKILL.md must start with YAML frontmatter")
    block, _, _ = content[4:].partition("\n---\n")
    fields = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, content


def copy_skill(destination: Path) -> Path:
    target = destination / "git-workspace-governance"
    shutil.copytree(SKILL_ROOT, target)
    return target


class SelfContainmentTests(unittest.TestCase):
    def test_no_broken_or_external_links(self):
        self.assertEqual(broken_links(SKILL_ROOT), [])

    def test_no_machine_specific_absolute_paths(self):
        offenders = []
        for markdown in markdown_files(SKILL_ROOT):
            content = markdown.read_text(encoding="utf-8")
            if ABSOLUTE_PATH_PATTERN.search(content):
                offenders.append(str(markdown.relative_to(SKILL_ROOT)))
        self.assertEqual(offenders, [])

    def test_no_sibling_skill_reference_paths(self):
        offenders = []
        for markdown in markdown_files(SKILL_ROOT):
            content = markdown.read_text(encoding="utf-8")
            for target in LINK_PATTERN.findall(content):
                if "../" in target or target.startswith(".."):
                    offenders.append((str(markdown.relative_to(SKILL_ROOT)), target))
        self.assertEqual(offenders, [])

    def test_frontmatter_contract(self):
        fields, content = frontmatter()
        self.assertEqual(fields.get("name"), SKILL_ROOT.name)
        description = fields.get("description", "")
        self.assertTrue(description.startswith("Use when"), description)
        self.assertLessEqual(len(content.split("---\n", 2)[1]), 1024)
        self.assertIn("## 可选集成", content)
        self.assertIn("不要求、不检查、也不调用任何其他 skill", content)

    def test_every_reference_file_is_routed_from_skill_md(self):
        content = SKILL_FILE.read_text(encoding="utf-8")
        targets = {Path(raw.split("#", 1)[0]).name for raw in LINK_PATTERN.findall(content)}
        reference_files = sorted((SKILL_ROOT / "references").glob("*.md"))
        missing = [path.name for path in reference_files if path.name not in targets]
        self.assertEqual(missing, [])

    def test_script_has_no_network_or_mutation_commands(self):
        content = SCRIPT.read_text(encoding="utf-8")
        forbidden = [
            "git fetch",
            "git pull",
            "git push",
            "git clean",
            "reset --hard",
            "checkout --",
            "worktree remove",
            "urllib",
            "http.client",
            "socket",
        ]
        found = [token for token in forbidden if token in content]
        self.assertEqual(found, [])

    def test_openai_agent_metadata_exists(self):
        metadata = SKILL_ROOT / "agents" / "openai.yaml"
        self.assertTrue(metadata.is_file())
        text = metadata.read_text(encoding="utf-8")
        self.assertIn("display_name", text)


class SingleDirectoryCopyTests(unittest.TestCase):
    def test_copied_skill_still_passes_checks_and_script_runs(self):
        with tempfile.TemporaryDirectory(prefix="exharness-skill-copy-") as tmp:
            copy = copy_skill(Path(tmp))
            self.assertEqual(broken_links(copy), [])
            metadata = copy / "agents" / "openai.yaml"
            self.assertTrue(metadata.is_file())

            script = copy / "references" / "scripts" / "check_workspace_state.py"
            help_result = subprocess.run(
                [sys.executable, str(script), "--help"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("--integration-branch", help_result.stdout)

            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-q", "-b", "main"], cwd=repo, check=True, timeout=60
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo,
                check=True,
                timeout=60,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo,
                check=True,
                timeout=60,
            )
            (repo / "file.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "file.txt"], cwd=repo, check=True, timeout=60
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "one"],
                cwd=repo,
                check=True,
                timeout=60,
            )
            report_result = subprocess.run(
                [sys.executable, str(script), "--repo", str(repo), "--json"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(report_result.returncode, 0, report_result.stderr)
            report = json.loads(report_result.stdout)
            self.assertIn("canonical", report)


if __name__ == "__main__":
    unittest.main()
