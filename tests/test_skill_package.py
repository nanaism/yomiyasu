"""Keep the distribution discoverable without duplicate skill definitions."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "skills" / "yomiyasu"


class SkillPackageTests(unittest.TestCase):
    def test_single_discoverable_entrypoint(self):
        entries = sorted(ROOT.rglob("SKILL.md"))
        self.assertEqual(entries, [PACKAGE / "SKILL.md"])

    def test_plugin_points_to_skill_parent(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        skills_directory = ROOT / manifest["skills"]
        self.assertEqual(skills_directory.resolve(), PACKAGE.parent.resolve())
        self.assertTrue((skills_directory / "yomiyasu" / "SKILL.md").is_file())

    def test_installed_resources_are_self_contained(self):
        for relative in (
            "references/gemini-syntax.md",
            "references/slop-catalog.md",
            "references/domains/tech.md",
            "references/domains/business.md",
            "references/domains/essay.md",
            "scripts/yomiyasu_lint.py",
            "scripts/yomiyasu_diff.py",
            "scripts/markdown_visibility.py",
            "LICENSE",
            "UNICODE-LICENSE.txt",
        ):
            with self.subTest(resource=relative):
                self.assertTrue((PACKAGE / relative).is_file())

    def test_distributed_scripts_are_only_the_skill_tools(self):
        # Corpus and setup scripts stay at the repository root and out of the release ZIP.
        names = sorted(path.name for path in (PACKAGE / "scripts").glob("*.py"))
        self.assertEqual(names, ["markdown_visibility.py", "yomiyasu_diff.py", "yomiyasu_lint.py"])

    def test_root_copies_match_distributed_skill(self):
        # Tests import the root copies, so a drift would leave the distributed files untested.
        for name in ("yomiyasu_lint.py", "yomiyasu_diff.py", "markdown_visibility.py"):
            with self.subTest(script=name):
                self.assertEqual((ROOT / "scripts" / name).read_bytes(), (PACKAGE / "scripts" / name).read_bytes())
        root_references = ROOT / "references"
        package_references = PACKAGE / "references"

        def documents(base):
            # Skip dotfiles such as the .DS_Store that Finder leaves behind (ignored by git).
            return sorted(path.relative_to(base) for path in base.rglob("*")
                          if path.is_file() and not any(part.startswith(".") for part in path.relative_to(base).parts))

        relatives = documents(package_references)
        self.assertEqual(documents(root_references), relatives)
        for relative in relatives:
            with self.subTest(reference=str(relative)):
                self.assertEqual((root_references / relative).read_bytes(), (package_references / relative).read_bytes())


if __name__ == "__main__":
    unittest.main()
