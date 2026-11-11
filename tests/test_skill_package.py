"""Keep the distribution discoverable without duplicate skill definitions."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "skills" / "yomiyasu"

# Characters that take no space on screen: zero-width and word-joiner characters, invisible operators,
# bidirectional controls, variation selectors (the emoji selector U+FE0F is left out), soft hyphen,
# annotation markers, deprecated formatting characters and tag characters. Inclusive ranges.
HIDDEN_RANGES = (
    (0x00AD, 0x00AD), (0x061C, 0x061C), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2064), (0x2066, 0x206F),
    (0xFE00, 0xFE0E), (0xFFF9, 0xFFFB), (0xE0001, 0xE007F), (0xE0100, 0xE01EF),
)
BYTE_ORDER_MARK = 0xFEFF


def hidden_characters(text):
    """(line, "U+XXXX") for each hidden character in text. A byte order mark counts everywhere except as the
    first character of the text, where it is the usual way to mark a file's encoding."""
    found = []
    for line_number, line in enumerate(text.split("\n"), 1):
        for column, character in enumerate(line):
            code = ord(character)
            if code == BYTE_ORDER_MARK:
                hidden = not (line_number == 1 and column == 0)
            else:
                hidden = any(low <= code <= high for low, high in HIDDEN_RANGES)
            if hidden:
                found.append((line_number, "U+{:04X}".format(code)))
    return found


class SkillPackageTests(unittest.TestCase):
    def test_single_discoverable_entrypoint(self):
        entries = sorted(ROOT.rglob("SKILL.md"))
        self.assertEqual(entries, [PACKAGE / "SKILL.md"])

    def test_plugin_points_to_skill_parent(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        skills_directory = ROOT / manifest["skills"]
        self.assertEqual(skills_directory.resolve(), PACKAGE.parent.resolve())
        self.assertTrue((skills_directory / "yomiyasu" / "SKILL.md").is_file())

    def test_only_root_plugin_manifest(self):
        # Layout rule of this repository: the plugin manifests exist once, in the root .claude-plugin/,
        # and the marketplace's only plugin is the whole repository ("./"). Codex installs the repository as
        # a plugin from the same two files, so the root has no .codex-plugin/ (a name-only manifest there
        # would be read first and leave the Codex plugin without a version). The root has no bin/ folder.
        manifests = sorted(path for path in ROOT.rglob("*.json")
                           if path.parent.name == ".claude-plugin" and ".git" not in path.relative_to(ROOT).parts)
        self.assertEqual(manifests, [ROOT / ".claude-plugin" / "marketplace.json", ROOT / ".claude-plugin" / "plugin.json"])
        marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["source"] for entry in marketplace["plugins"]], ["./"])
        self.assertFalse((ROOT / "bin").exists())
        self.assertFalse((ROOT / ".codex-plugin").exists())

    def test_skill_folder_is_a_plain_skill(self):
        # 3.1.0 (issue #61): the skill folder holds no plugin manifest. Installers that copy only this folder
        # and then look at what they copied (apm 0.35.0 and later) take any of these files as "this folder
        # is a plugin" before they look at SKILL.md; with .codex-plugin/plugin.json, apm refused to install
        # the skill into a project. Codex also puts the manifest's name in front of the skill's name
        # ("yomiyasu:yomiyasu" instead of "yomiyasu") when the folder is copied into .agents/skills/.
        for relative in (".codex-plugin", ".claude-plugin", ".cursor-plugin", ".github/plugin", "plugin.json"):
            with self.subTest(path=relative):
                self.assertFalse((PACKAGE / relative).exists())

    def test_installed_resources_are_self_contained(self):
        for relative in (
            "references/gemini-syntax.md",
            "references/slop-catalog.md",
            "references/domains/tech.md",
            "references/domains/business.md",
            "references/domains/essay.md",
            "scripts/yomiyasu_lint.py",
            "scripts/yomiyasu_diff.py",
            "scripts/yomiyasu_check.py",
            "scripts/markdown_visibility.py",
            "LICENSE",
            "UNICODE-LICENSE.txt",
        ):
            with self.subTest(resource=relative):
                self.assertTrue((PACKAGE / relative).is_file())

    def test_distributed_scripts_are_only_the_skill_tools(self):
        # Corpus and setup scripts stay at the repository root and out of the release ZIP.
        names = sorted(path.name for path in (PACKAGE / "scripts").glob("*.py"))
        self.assertEqual(names, ["markdown_visibility.py", "yomiyasu_check.py", "yomiyasu_diff.py", "yomiyasu_hook.py", "yomiyasu_lint.py"])

    def test_root_copies_match_distributed_skill(self):
        # Tests import the root copies, so a drift would leave the distributed files untested.
        for name in ("yomiyasu_lint.py", "yomiyasu_diff.py", "yomiyasu_check.py", "yomiyasu_hook.py", "markdown_visibility.py"):
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

    def test_distributed_text_has_no_hidden_characters(self):
        # 3.1.0: tools that scan a skill for hidden characters (apm does, before it installs one) count these
        # as warnings, and tools that strip hidden characters from a file (apm audit --file <path> --strip)
        # remove them. Stripping one out of code changes what the code does:
        # text.startswith("<byte order mark>") turns into text.startswith(""), which is always true, and the
        # word lists then lose their first character. In code, write such a character as an escape
        # ("\ufeff"), which no scanner touches.
        checked = 0
        for path in sorted(PACKAGE.rglob("*")):
            relative = path.relative_to(PACKAGE)
            if not path.is_file() or "__pycache__" in relative.parts or any(part.startswith(".") for part in relative.parts):
                continue
            if path.suffix == ".png":
                continue
            text = path.read_text(encoding="utf-8")  # every other distributed file is UTF-8 text
            checked += 1
            with self.subTest(path=str(relative)):
                self.assertEqual(hidden_characters(text), [])
        self.assertGreater(checked, 30)

    def test_hidden_character_check_finds_what_it_looks_for(self):
        self.assertEqual(hidden_characters("first\nab\ufeffc\n"), [(2, "U+FEFF")])
        self.assertEqual(hidden_characters("\ufefffirst\n"), [])
        self.assertEqual(hidden_characters("a\u200bb\u200d\n\u202e\n\U000e0041"), [(1, "U+200B"), (1, "U+200D"), (2, "U+202E"), (3, "U+E0041")])
        # Visible or ordinary characters stay: ideographic space, emoji with its selector, no-break space.
        self.assertEqual(hidden_characters("\u3000全角の空白 \u2728\ufe0f \u00a0"), [])
        # An escape in source code is plain ASCII text.
        self.assertEqual(hidden_characters('text.startswith("\\ufeff")'), [])


if __name__ == "__main__":
    unittest.main()
