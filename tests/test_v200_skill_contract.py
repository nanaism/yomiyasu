#!/usr/bin/env python3
"""v2.0.0: SKILL.md と道具の食い違いを防ぐ試験（DESIGN-interfaces.md 6.7、5章）。

SKILL.md に書いた check の手順が実際に動くこと、古い手順と古い表示の文が残っていないことを確かめる。
check はまだない（v1.1.2）ので、子プロセスで動かし、先にファイルの有無を確かめる。
check の子プロセスは、作業ディレクトリと YOMIYASU_STATE_DIR を一時フォルダの中に向ける。
v1.1.2 では、文字数を書き出す試験（後戻り防止の印を付けた）のほかはすべて失敗する。
"""

from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "skills" / "yomiyasu"
SKILL_MD = PACKAGE / "SKILL.md"
CHECK = ROOT / "scripts" / "yomiyasu_check.py"

# 6.7 の1つ目: SKILL.md に含む文字列
REQUIRED = (
    "yomiyasu_check.py run",
    "yomiyasu_check.py verify",
    "--source",
    "--final",
    "--material",
    "--stdin",
    "<<<yomiyasu:final>>>",
    "1回まで",
    "### 確認の記録",
    "実行した検査",
    "実行しなかった検査",
    "not_run",
    "no_python",
)
# 6.7 の1つ目の最後「本文だけの指定の扱いの文」。5.2 の文「…本文だけを返す指定があるときは付けない…」の要の語。
BODY_ONLY_RULE = re.compile(r"本文だけ[^。\n]*付けない")
# 6.7 の2つ目: SKILL.md に含まない文字列
FORBIDDEN_IN_SKILL = (
    "フルモード",
    "スクリプトの再実行を繰り返す往復は行いません",
    "修正の試行は最大2回",
    "yomiyasu_lint.py <対象ファイル>",
)
# 6.7 の4つ目: SKILL.md、references、README に含まない表示（CHANGELOG の移行の表は除く）
OLD_REPORT_MARKERS = ("AIっぽさ 検査レポート", "[PASS]", "（候補なし）")
SUBCOMMANDS = ("run", "verify", "start")
# サブコマンドを書かない最上位のオプション（3.2 の `yomiyasu_check.py --version`）。run とはみなさない。
TOP_LEVEL_OPTIONS = ("--version", "--help", "-h")
TOP_LEVEL = ""
OPTION = re.compile(r"(?<![\w-])--[A-Za-z][A-Za-z0-9-]*")


def code_segments(text):
    """Markdown のコード（フェンスの中の各行と、行の中のバッククォートの範囲）を順に返す。"""
    segments = []
    fence = None
    for line in text.split("\n"):
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence is None and marker:
            fence = marker.group(1)[0] * len(marker.group(1))
            continue
        if fence is not None:
            if stripped.startswith(fence) and stripped.strip(fence[0]) == "":
                fence = None
            else:
                segments.append(line)
            continue
        for match in re.finditer(r"(`+)(.+?)\1", line):
            segments.append(match.group(2))
    return segments


def check_commands(segments):
    """コードに出る check のサブコマンドとオプション。

    `yomiyasu_check.py <サブコマンド> …` と、サブコマンドの名前で始まるコード（`run --stdin`）は、
    そのサブコマンドのオプションとして集める。サブコマンドを省いた形は run とみなす（3.2）。
    ただし `yomiyasu_check.py --version` のように最上位のオプションで始まるものは、
    最上位（TOP_LEVEL）のオプションとして集め、`yomiyasu_check.py --help` に出るかで確かめる。
    オプションと値だけのコード（`--material 資料`）は、どのサブコマンドのものか書いていないので、
    どれかのサブコマンドのヘルプに出ればよいものとして別に集める。
    """
    by_command = {}
    loose = set()
    for segment in segments:
        text = segment.strip()
        match = re.search(r"yomiyasu_check\.py", text)
        if match:
            rest = text[match.end():]
            words = rest.split()
            if words and words[0] in TOP_LEVEL_OPTIONS:
                name = TOP_LEVEL
            elif words and words[0] in SUBCOMMANDS:
                name = words[0]
            else:
                name = "run"
            by_command.setdefault(name, set()).update(OPTION.findall(rest))
            continue
        first = text.split()[0] if text.split() else ""
        if first in SUBCOMMANDS and OPTION.search(text):
            by_command.setdefault(first, set()).update(OPTION.findall(text))
            continue
        if re.match(r"^--[A-Za-z][A-Za-z0-9-]*(?:[ =]\S+)?$", text):
            loose.update(OPTION.findall(text))
    return by_command, loose


def line_of(text, phrase):
    """失敗したときに文書全体を出さず、行番号だけを示す。"""
    position = text.find(phrase)
    return text.count("\n", 0, position) + 1 if position != -1 else None


def documents():
    """SKILL.md、ルートと skills の references、README.md。"""
    paths = [SKILL_MD, ROOT / "README.md"]
    for base in (ROOT / "references", PACKAGE / "references"):
        paths.extend(sorted(path for path in base.rglob("*.md") if path.is_file()))
    return paths


class SkillContractCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v200-contract-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.text = SKILL_MD.read_text(encoding="utf-8")

    def run_check(self, args):
        env = dict(os.environ, YOMIYASU_STATE_DIR=str(self.root / "state"), COLUMNS="200", NO_COLOR="1")
        env.pop("FORCE_COLOR", None)
        env.pop("PYTHON_COLORS", None)
        return subprocess.run(
            [sys.executable, "-B", str(CHECK)] + [str(a) for a in args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            cwd=str(self.root),
            env=env,
        )


class TestSkillText(SkillContractCase):
    """SKILL.md の文。"""

    def test_contains_the_check_procedure(self):
        """SKILL.md に check の run と verify、引数、ヒアドキュメントの区切り、確認の記録の欄の語がある。"""
        for phrase in REQUIRED:
            with self.subTest(phrase=phrase):
                self.assertTrue(phrase in self.text, "SKILL.md に「{}」がない".format(phrase))

    def test_states_the_body_only_rule(self):
        """本文だけの指定では確認の記録の欄を付けない、という扱いの文がある（5.2）。"""
        self.assertIsNotNone(BODY_ONLY_RULE.search(self.text), "SKILL.md に本文だけの指定の扱いの文がない")

    def test_drops_the_old_procedure(self):
        """フルモード、往復しない文、修正の試行は最大2回、lint を単に呼ぶ手順が残っていない。"""
        for phrase in FORBIDDEN_IN_SKILL:
            with self.subTest(phrase=phrase):
                self.assertFalse(phrase in self.text, "SKILL.md の{}行目に「{}」がある".format(line_of(self.text, phrase), phrase))

    def test_skill_md_length_is_reported(self):
        """SKILL.md の文字数を出力に書く。上限は設けず、合否には使わない（指示書1章）。（v1.1.2 でも通る後戻り防止）"""
        count = len(self.text)
        sys.stderr.write("\n[test_v200_skill_contract] SKILL.md: {:,}字（{}）\n".format(count, SKILL_MD.relative_to(ROOT)))
        self.assertGreater(count, 0)


class TestCommandsInSkillWork(SkillContractCase):
    """SKILL.md のコードに出る check のサブコマンドとオプションが、ヘルプに出る（書いた手順が実際に動く）。"""

    def test_commands_in_code_are_in_help(self):
        self.assertTrue(CHECK.is_file(), "scripts/yomiyasu_check.py がない")
        by_command, loose = check_commands(code_segments(self.text))
        # 5.1 の手順は run と verify を使う。見つからなければ照らす対象がないので失敗にする。
        self.assertTrue({"run", "verify"} <= set(by_command), sorted(by_command))
        helps = {}
        for name in sorted(by_command):
            label = name if name != TOP_LEVEL else "(最上位)"
            process = self.run_check([name, "--help"] if name != TOP_LEVEL else ["--help"])
            with self.subTest(command=label):
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            helps[name] = process.stdout
            for option in sorted(by_command[name]):
                with self.subTest(command=label, option=option):
                    self.assertIn(option, process.stdout)
        for option in sorted(loose):
            with self.subTest(option=option, where="loose"):
                self.assertTrue(any(option in text for text in helps.values()),
                                "{} がどのサブコマンドのヘルプにもない".format(option))


class TestOldReportMarkers(SkillContractCase):
    """古い表示を文書に残さない。"""

    def test_documents_do_not_show_old_report_markers(self):
        """SKILL.md、references、README に「AIっぽさ 検査レポート」「[PASS]」「（候補なし）」がない。"""
        for path in documents():
            text = path.read_text(encoding="utf-8")
            for marker in OLD_REPORT_MARKERS:
                with self.subTest(document=str(path.relative_to(ROOT)), marker=marker):
                    self.assertFalse(marker in text, "{}行目に「{}」がある".format(line_of(text, marker), marker))


if __name__ == "__main__":
    unittest.main()
