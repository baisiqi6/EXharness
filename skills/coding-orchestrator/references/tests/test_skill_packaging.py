"""The orchestrator must work as an independently copied skill."""

from pathlib import Path
import re
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


class SkillPackagingTests(unittest.TestCase):
    def test_discovery_metadata(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        fields = dict(
            line.split(": ", 1)
            for line in text.split("---", 2)[1].splitlines()
            if ": " in line and not line.startswith(" ")
        )
        self.assertEqual(fields["name"], ROOT.name)
        self.assertTrue(fields["description"].startswith("Use when "))
        self.assertLessEqual(len(fields["description"]), 500)

    def test_single_directory_copy_has_reachable_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / ROOT.name
            shutil.copytree(ROOT, copied)
            pending = [copied / "SKILL.md"]
            visited = set()
            while pending:
                doc = pending.pop().resolve()
                if doc in visited:
                    continue
                visited.add(doc)
                self.assertTrue(doc.is_file(), str(doc))
                self.assertTrue(doc.is_relative_to(copied.resolve()), str(doc))
                for raw in LINK.findall(doc.read_text(encoding="utf-8")):
                    target = raw.split("#", 1)[0]
                    if not target or target.startswith(("https://", "http://", "mailto:")):
                        continue
                    with self.subTest(document=doc.name, target=target):
                        self.assertFalse(Path(target).is_absolute())
                        resolved = (doc.parent / target).resolve()
                        self.assertTrue(resolved.is_relative_to(copied.resolve()))
                        self.assertTrue(resolved.is_file())
                        if resolved.suffix == ".md":
                            pending.append(resolved)
            bundled = {p.resolve() for p in (copied / "references").rglob("*.md")}
            self.assertTrue(bundled, "Bundled extension guidance is missing")
            self.assertTrue(bundled.issubset(visited), "Unreachable bundled guidance")

    def test_published_docs_do_not_contain_machine_paths(self):
        docs = [ROOT / "SKILL.md", *sorted((ROOT / "references").rglob("*.md"))]
        for doc in docs:
            with self.subTest(document=doc.name):
                self.assertNotRegex(
                    doc.read_text(encoding="utf-8"),
                    r"/Users/|/home/|(?<![A-Za-z0-9_])[A-Za-z]:[\\/]",
                )

    def test_agent_metadata_is_packaged(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("display_name:", metadata)
        self.assertIn("short_description:", metadata)


if __name__ == "__main__":
    unittest.main()
