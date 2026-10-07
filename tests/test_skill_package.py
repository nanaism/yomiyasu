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


if __name__ == "__main__":
    unittest.main()
