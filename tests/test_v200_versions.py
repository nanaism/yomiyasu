#!/usr/bin/env python3
"""v2.0.0: 版の文字列をすべてそろえる試験（設計 4章の7項目）。

スクリプトは import せず、ast と正規表現で読む。CLI は子プロセスで動かす。
v1.1.2 には metadata.version、__version__、CHANGELOG.md、--version がないので、それらの試験は失敗する。
manifest どうしの一致と frontmatter のキーの試験は v1.1.2 でも通るので、
docstring に「（v1.1.2 でも通る後戻り防止）」と書いて分けた。
"""

from datetime import datetime
from pathlib import Path
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "skills" / "yomiyasu"
SCRIPT_NAMES = ("yomiyasu_lint.py", "yomiyasu_diff.py", "yomiyasu_check.py", "markdown_visibility.py")
SCRIPT_DIRS = (ROOT / "scripts", PACKAGE / "scripts")
LINT = ROOT / "scripts" / "yomiyasu_lint.py"
DIFF = ROOT / "scripts" / "yomiyasu_diff.py"
CHECK = ROOT / "scripts" / "yomiyasu_check.py"

# 4章の5: skill-creator の quick_validate.py が許す最上位のキー（skill-creator には依存しない）
ALLOWED_FRONTMATTER_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
# 4章の2つ目: 出力の形の版の定数と、設計が決めた値
FORMAT_CONSTANTS = (
    "LINT_FORMAT_VERSION", "DIFF_FORMAT_VERSION", "MATERIALS_FORMAT_VERSION",
    "RECORD_FORMAT_VERSION", "RESULT_FORMAT_VERSION",
)
FORMAT_VERSIONS = {
    "LINT_FORMAT_VERSION": 2,
    "DIFF_FORMAT_VERSION": 2,
    "MATERIALS_FORMAT_VERSION": 1,
    "RECORD_FORMAT_VERSION": 1,
    "RESULT_FORMAT_VERSION": 1,
}
# 10.1 L2: 形式の版の定数を置くファイル（1つのファイルにだけ置き、ほかは import して使う）
FORMAT_CONSTANT_HOMES = {
    "LINT_FORMAT_VERSION": "yomiyasu_lint.py",
    "DIFF_FORMAT_VERSION": "yomiyasu_diff.py",
    "MATERIALS_FORMAT_VERSION": "yomiyasu_diff.py",
    "RECORD_FORMAT_VERSION": "yomiyasu_check.py",
    "RESULT_FORMAT_VERSION": "yomiyasu_check.py",
}
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")  # 先行版（2.0.0-beta）も版の形に数える（目標の D-3）


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_version():
    """4章の1の基準: ルートの .claude-plugin/plugin.json の version。"""
    return read_json(ROOT / ".claude-plugin" / "plugin.json")["version"]


def frontmatter_lines(path):
    """SKILL.md の先頭の --- から次の --- までの行（YAML のライブラリを使わない）。"""
    lines = path.read_text(encoding="utf-8").split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r") == "---":
            return [line.rstrip("\r") for line in lines[1:index]]
    return None


def top_level_keys(lines):
    keys = []
    for line in lines:
        match = re.match(r"^([A-Za-z0-9_-]+)\s*:", line)
        if match:
            keys.append(match.group(1))
    return keys


def metadata_version(lines):
    """`metadata:` の次の字下げした行の `version:` を取る（4章の check と同じ読み方）。"""
    inside = False
    for line in lines:
        if re.match(r"^metadata\s*:\s*$", line):
            inside = True
            continue
        if inside:
            if line and not line[0].isspace():
                break
            match = re.match(r"^\s+version\s*:\s*[\"']?([^\"'\s]+)[\"']?\s*$", line)
            if match:
                return match.group(1)
    return None


def module_constants(path):
    """モジュールの最上位で定数（str、int）を代入した名前と値の組を、出てくる順に返す。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pairs = []
    for node in tree.body:
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, (str, int)):
            for target in targets:
                if isinstance(target, ast.Name):
                    pairs.append((target.id, value.value, node))
    return tree, pairs


def names_assigned_from_version(tree):
    """最上位で、右辺に __version__ を使って代入した名前（`VERSION = __version__`、`"%s" % __version__` など）。"""
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(child, ast.Name) and child.id == "__version__" for child in ast.walk(value)):
            continue
        for target in targets:
            for child in ast.walk(target):
                if isinstance(child, ast.Name) and child.id != "__version__":
                    names.append(child.id)
    return names


def script_version(path):
    _, pairs = module_constants(path)
    values = [value for name, value, _ in pairs if name == "__version__"]
    return values[0] if len(values) == 1 else None


def run_cli(script, args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, "-B", str(script)] + [str(a) for a in args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        cwd=cwd,
        env=env,
    )


class TestVersionStrings(unittest.TestCase):
    """4章の1〜6。"""

    def test_manifest_versions_agree(self):
        """1. ルートの plugin.json と marketplace.json の version が同じ。（v1.1.2 でも通る後戻り防止）"""
        version = manifest_version()
        self.assertRegex(version, SEMVER)
        plugin = read_json(ROOT / ".claude-plugin" / "plugin.json")
        marketplace = read_json(ROOT / ".claude-plugin" / "marketplace.json")
        self.assertEqual(plugin["version"], version)
        self.assertEqual(marketplace["plugins"][0]["version"], version)

    def test_skill_metadata_version(self):
        """2. SKILL.md の frontmatter の metadata.version が manifest の版と同じ。"""
        lines = frontmatter_lines(PACKAGE / "SKILL.md")
        self.assertIsNotNone(lines, "SKILL.md に frontmatter がない")
        self.assertEqual(metadata_version(lines), manifest_version())

    def test_script_versions(self):
        """3. ルートと skills の scripts の4本の __version__ が manifest の版と同じ。"""
        version = manifest_version()
        for directory in SCRIPT_DIRS:
            for name in SCRIPT_NAMES:
                path = directory / name
                with self.subTest(script=str(path.relative_to(ROOT))):
                    self.assertTrue(path.is_file(), "{} がない".format(path.relative_to(ROOT)))
                    self.assertEqual(script_version(path), version)

    def test_version_follows_docstring_without_alias(self):
        """__version__ は docstring の直後に1行で置き、版の文字列を別名の定数に持たせない（4章の1つ目）。"""
        for directory in SCRIPT_DIRS:
            for name in SCRIPT_NAMES:
                path = directory / name
                with self.subTest(script=str(path.relative_to(ROOT))):
                    self.assertTrue(path.is_file(), "{} がない".format(path.relative_to(ROOT)))
                    tree, pairs = module_constants(path)
                    self.assertGreaterEqual(len(tree.body), 2)
                    docstring = tree.body[0]
                    self.assertIsInstance(docstring, ast.Expr)
                    self.assertIsInstance(docstring.value, ast.Constant)
                    self.assertIsInstance(docstring.value.value, str)
                    statement = tree.body[1]
                    self.assertIsInstance(statement, ast.Assign)
                    self.assertEqual([getattr(t, "id", None) for t in statement.targets], ["__version__"])
                    self.assertEqual(statement.lineno, statement.end_lineno)
                    self.assertIsInstance(statement.value, ast.Constant, "__version__ の値が文字列の定数でない")
                    version = statement.value.value
                    self.assertIsInstance(version, str, "__version__ の値が文字列でない")
                    # 同じ文字列を持つ定数と、__version__ から作った定数の両方を別名として数える。
                    aliases = [n for n, value, _ in pairs if value == version and n != "__version__"]
                    aliases += names_assigned_from_version(tree)
                    self.assertEqual(aliases, [], "__version__ の別名の定数がある")

    def test_changelog_first_heading(self):
        """4. CHANGELOG.md の最初の `## ` 見出しが `## 2.0.0 - YYYY-MM-DD` の形で、manifest の版と同じ（版のあとに「-」と印の付いた形も受ける）。"""
        path = ROOT / "CHANGELOG.md"
        self.assertTrue(path.is_file(), "CHANGELOG.md がない")
        headings = [line.rstrip("\r") for line in path.read_text(encoding="utf-8").split("\n") if line.startswith("## ")]
        self.assertTrue(headings, "CHANGELOG.md に ## の見出しがない")
        match = re.match(r"^## (\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?) - (\d{4}-\d{2}-\d{2})$", headings[0])
        self.assertIsNotNone(match, headings[0])
        self.assertEqual(match.group(1), manifest_version())
        datetime.strptime(match.group(2), "%Y-%m-%d")

    def test_frontmatter_top_level_keys_are_allowed(self):
        """5. SKILL.md の frontmatter の最上位のキーが許された6つの中だけ。compatibility と allowed-tools は入れない。（v1.1.2 でも通る後戻り防止）"""
        lines = frontmatter_lines(PACKAGE / "SKILL.md")
        self.assertIsNotNone(lines, "SKILL.md に frontmatter がない")
        keys = top_level_keys(lines)
        self.assertTrue(keys)
        self.assertEqual(sorted(set(keys) - ALLOWED_FRONTMATTER_KEYS), [])
        self.assertNotIn("compatibility", keys)
        self.assertNotIn("allowed-tools", keys)

    def test_codex_manifest_has_only_the_name(self):
        """6. skills/yomiyasu/.codex-plugin/plugin.json は名前だけを持つ（Codex の .agents/skills で yomiyasu:yomiyasu の名前にするため。版を持たないので、版を上げるときに変えない）。skills/yomiyasu には .claude-plugin を置かない（Claude のプラグインの設定は、ルートの .claude-plugin の1組だけにする）。"""
        self.assertEqual(read_json(PACKAGE / ".codex-plugin" / "plugin.json"), {"name": read_json(ROOT / ".claude-plugin" / "plugin.json")["name"]})
        self.assertFalse((PACKAGE / ".claude-plugin").exists())


class TestCliVersions(unittest.TestCase):
    """4章の7: 各 CLI の --version と JSON の tool_version が __version__ と同じ。形式の版の定数と JSON の format_version が同じ。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v200-versions-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def version_of(self, path):
        self.assertTrue(path.is_file(), "{} がない".format(path.relative_to(ROOT)))
        version = script_version(path)
        self.assertIsInstance(version, str, "{} に __version__ がない".format(path.name))
        return version

    def format_constant(self, constant):
        """形式の版の定数1つを、ルートの4本のうち、あるファイルから探す。

        ここでは値だけを見る。どのファイルに置くか（10.1 L2）は test_format_constants_live_in_one_file で見る。
        まだないスクリプト（作業の途中の check など）に、lint と diff の版の試験が引きずられないようにする。
        """
        values = set()
        for name in SCRIPT_NAMES:
            path = ROOT / "scripts" / name
            if not path.is_file():
                continue
            _, pairs = module_constants(path)
            values.update(value for found, value, _ in pairs if found == constant)
        self.assertTrue(values, "{} がどのスクリプトにもない".format(constant))
        self.assertEqual(len(values), 1, "{} の値がファイルごとに違う: {}".format(constant, sorted(values, key=repr)))
        value = next(iter(values))
        self.assertIsInstance(value, int, "{} が整数でない".format(constant))
        return value

    def format_constants(self):
        """形式の版の定数5つを、ルートの4本がそろった上で集める。"""
        for name in SCRIPT_NAMES:
            self.assertTrue((ROOT / "scripts" / name).is_file(), "scripts/{} がない".format(name))
        return {constant: self.format_constant(constant) for constant in FORMAT_CONSTANTS}

    def check_env(self):
        env = dict(os.environ, YOMIYASU_STATE_DIR=str(self.root / "state"))
        env.pop("YOMIYASU_SESSION", None)
        return env

    def assert_first_keys(self, result):
        # 0.4: 最上位の最初の3キーは format、format_version（整数）、tool_version
        self.assertEqual(list(result)[:3], ["format", "format_version", "tool_version"])

    def test_format_constants_are_defined(self):
        """出力の形の版の定数5つが、スクリプトに整数で1つずつの値で定義され、値が4章のとおり。"""
        self.assertEqual(self.format_constants(), FORMAT_VERSIONS)

    def test_format_constants_live_in_one_file(self):
        """10.1 L2: 形式の版の定数は決まった1つのファイルにだけ最上位で定義する（ほかのファイルは import して使う）。"""
        # まだないスクリプト（作業の途中の check など）は見ない。置くべきファイルがなければ失敗にする。
        for constant, home in sorted(FORMAT_CONSTANT_HOMES.items()):
            with self.subTest(constant=constant):
                self.assertTrue((ROOT / "scripts" / home).is_file(), "scripts/{} がない".format(home))
                homes = []
                for name in SCRIPT_NAMES:
                    path = ROOT / "scripts" / name
                    if not path.is_file():
                        continue
                    _, pairs = module_constants(path)
                    if any(found == constant for found, _, _ in pairs):
                        homes.append(name)
                self.assertEqual(homes, [home])

    def test_lint_version_line(self):
        """lint の --version は `yomiyasu_lint.py <__version__> (JSON format <LINT_FORMAT_VERSION>)` の1行で0。"""
        version = self.version_of(LINT)
        format_version = self.format_constant("LINT_FORMAT_VERSION")
        process = run_cli(LINT, ["--version"])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stdout, "yomiyasu_lint.py {} (JSON format {})\n".format(version, format_version))
        # 10.1 L1: 完全一致
        self.assertEqual(process.stdout, "yomiyasu_lint.py 2.0.2 (JSON format 2)\n")
        self.assertEqual(process.stderr, "")

    def test_diff_and_check_version_lines(self):
        """diff と check の --version は 10.1 L1 の1行（完全一致）で0。"""
        # diff `yomiyasu_diff.py 2.0.2 (JSON format 2)`、
        # check `yomiyasu_check.py 2.0.2 (record format 1, result format 1, materials format 1)`。
        expected = {
            DIFF: lambda version: "yomiyasu_diff.py {} (JSON format {})".format(
                version, self.format_constant("DIFF_FORMAT_VERSION")),
            CHECK: lambda version: "yomiyasu_check.py {} (record format {}, result format {}, materials format {})".format(
                version, self.format_constant("RECORD_FORMAT_VERSION"), self.format_constant("RESULT_FORMAT_VERSION"),
                self.format_constant("MATERIALS_FORMAT_VERSION")),
        }
        literal = {
            DIFF: "yomiyasu_diff.py 2.0.2 (JSON format 2)",
            CHECK: "yomiyasu_check.py 2.0.2 (record format 1, result format 1, materials format 1)",
        }
        for script in (DIFF, CHECK):
            with self.subTest(script=script.name):
                version = self.version_of(script)
                process = run_cli(script, ["--version"], cwd=str(self.root), env=self.check_env())
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stdout, expected[script](version) + "\n")
                self.assertEqual(process.stdout, literal[script] + "\n")
                self.assertEqual(process.stderr, "")

    def test_lint_and_diff_json_versions(self):
        """lint と diff の --json の tool_version が __version__、format_version が形式の版の定数と同じ。"""
        before = self.write("before.md", "保存期間は3日です。\n")
        after = self.write("after.md", "保存期間は30日です。\n")
        for script, args, constant in ((LINT, [after, "--json"], "LINT_FORMAT_VERSION"),
                                       (DIFF, [before, after, "--json"], "DIFF_FORMAT_VERSION")):
            with self.subTest(script=script.name):
                version = self.version_of(script)
                process = run_cli(script, args)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assert_first_keys(result)
                self.assertEqual(result.get("tool_version"), version)
                self.assertEqual(result.get("format_version"), self.format_constant(constant))

    def test_check_json_versions(self):
        """check の run --json と記録の tool_version、format_version が、__version__ と形式の版の定数と同じ。"""
        constants = self.format_constants()
        version = self.version_of(CHECK)
        lint_version = self.version_of(LINT)
        diff_version = self.version_of(DIFF)
        source = self.write("source.md", "保存期間は3日です。\n")
        final = self.write("final.md", "保存期間は30日です。\n")
        material = self.write("material.md", "保存期間は30日に変更した。\n")
        process = run_cli(CHECK, ["run", "--source", source, "--final", final, "--material", material, "--json"],
                          cwd=str(self.root), env=self.check_env())
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assert_first_keys(result)
        self.assertEqual(result.get("format"), "yomiyasu-check-result")
        self.assertEqual(result.get("tool_version"), version)
        self.assertEqual(result.get("format_version"), constants["RESULT_FORMAT_VERSION"])
        with self.subTest(part="lint"):
            self.assertIsInstance(result.get("lint"), dict, "run --json の lint がない")
            self.assertEqual(result["lint"].get("tool_version"), lint_version)
            self.assertEqual(result["lint"].get("format_version"), constants["LINT_FORMAT_VERSION"])
        with self.subTest(part="diff"):
            self.assertIsInstance(result.get("diff"), dict, "run --json の diff がない")
            self.assertEqual(result["diff"].get("tool_version"), diff_version)
            self.assertEqual(result["diff"].get("format_version"), constants["DIFF_FORMAT_VERSION"])
        with self.subTest(part="materials"):
            self.assertIsInstance(result.get("materials"), dict, "run --json の materials がない")
            self.assertEqual(result["materials"].get("format"), "yomiyasu-materials")
            self.assertEqual(result["materials"].get("format_version"), constants["MATERIALS_FORMAT_VERSION"])
        with self.subTest(part="record"):
            # JSON の record_path が絶対パスか相対パスかは設計に書いていない（questions-lint.md の12）。
            # そのため記録は、3.6 の置き場所（YOMIYASU_STATE_DIR の runs/<実行ID>/attempt-<n>.json）から探す。
            record_path = result.get("record_path")
            self.assertIsInstance(record_path, str, "run --json に record_path（記録のパス）がない")
            self.assertEqual(Path(record_path).name, "attempt-1.json", record_path)
            records = sorted((self.root / "state").glob("runs/*/attempt-1.json"))
            self.assertEqual(len(records), 1, "YOMIYASU_STATE_DIR の中に記録が1つない: {}".format(records))
            record = json.loads(records[0].read_text(encoding="utf-8"))
            self.assertEqual(record.get("format"), "yomiyasu-check-record")
            self.assertEqual(record.get("format_version"), constants["RECORD_FORMAT_VERSION"])


if __name__ == "__main__":
    unittest.main()
