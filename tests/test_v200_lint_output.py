#!/usr/bin/env python3
"""v2.0.0: lint の人が読む出力、JSON（形式2）、--strict と --fail-on、終了コード、入力の読み方。

期待値は設計の 1.1〜1.6 と 6.2 の表に従う（例1・例2の出力は一字一句）。
v1.1.2 では、v2.0.0 の振る舞いを確かめる試験はすべて失敗する。
v1.1.2 でも通る試験は、docstring に「（v1.1.2 でも通る後戻り防止）」と書いて分けた。
"""

from pathlib import Path
from unittest import mock
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
LINT = SCRIPTS_DIR / "yomiyasu_lint.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import run_text  # noqa: E402


# 1.1 の例1（候補なし）
EXAMPLE1_INPUT = "会議は3時に始まります。\n"
EXAMPLE1_LINES = [
    "表現・書式の検査を実行しました。",
    "見直し候補: 0件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
]

# 1.1 の例2（候補あり）。--strict なしの出力。
# 4つの message は v1.1.2 の lint の message と同じ（1.7: 規則と message は9章の作業で変える）。
# 9章で message や規則を変えたら、設計の例2と一緒にここを直す。
EXAMPLE2_INPUT = (
    "重要なのは、テストを書くことです。\n"
    "本記事では、設計の解像度を上げる方法を紹介します。\n"
    "これは**「重要」**です。\n"
)
EXAMPLE2_LINES = [
    "表現・書式の検査を実行しました。",
    "見直し候補: 4件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
    "",
    "内訳: error 1件、warn 2件、info 1件",
    "",
    "L1 [WARN] meta_filler: 前置フィラー「重要なのは」が検出されました。単なる前置きや不要な飾りであれば削り、本題から書いてください。ただし、「何が大事か」という評価や主張そのものを担っている場合は、述語に移すなどして意味を残してください。",
    "  > 重要なのは、テストを書くことです。",
    "",
    "L2 [WARN] slop_vocabulary: AI頻出語彙「解像度」が含まれています。文脈上必要のない比喩や大げさな装飾であれば、ふだん使う自然な表現に置き換えてください。ただし、文字どおりの意味や必要な文脈を担っている場合は残してかまいません。",
    "  > 本記事では、設計の解像度を上げる方法を紹介します。",
    "",
    "L2 [INFO] meta_intro: 「本記事では」で始まる案内が検出されました。続く本文と同じ内容を予告しているだけなら削り、長い文書の目次的な案内なら残してください。",
    "  > 本記事では、設計の解像度を上げる方法を紹介します。",
    "",
    "L3 [ERROR] bold_not_rendered: 太字の記号（**）について、太字として表示されない可能性のある書き方が見つかりました。GitHub などで太字にならず ** がそのまま表示されることがあります。直し方: かっこの内側だけを太字にする。",
    "  > これは**「重要」**です。 →",
    "  > これは「**重要**」です。",
]
# --strict 付きでは、最後に空行と次の1行が足される。
EXAMPLE2_STRICT_TAIL = [
    "",
    "終了コード1: --strict の条件（warn か error の候補が1件以上）に当たりました（error 1件、warn 2件）。",
]

# 1.3 のキーと順
# G7（種類と読者の設計 9.3、10.1）: not_judged の次に context を足す（キーを足すだけで、形式2のまま）
JSON_KEYS = [
    "format", "format_version", "tool_version", "candidate_count", "counts",
    "no_rule_findings", "rule_penalty_score", "not_judged", "context", "metrics", "findings",
]
NOT_JUDGED = ["meaning_preservation", "reader_comprehension"]
FINDING_KEYS = {"rule", "line", "severity", "message", "snippet"}

# 候補の重さごとの1文（v1.1.2 の lint で確かめた合成の文）
# 「info だけ」「warn だけ」「error だけ」という前提は、試験の中でも lint --json で確かめる
# （assert_input_severities）。9章で規則を足して前提が崩れたら、文を選び直す。
INFO_ONLY = "本記事では、設計の方法を紹介します。\n"          # meta_intro（info）だけ
WARN_ONLY = "重要なのは、テストを書くことです。\n"            # meta_filler（warn）だけ
ERROR_ONLY = "これは**「重要」**です。\n"                     # bold_not_rendered（error）だけ
SINGLE_SEVERITY_INPUTS = (("info", INFO_ONLY), ("warn", WARN_ONLY), ("error", ERROR_ONLY))

STRICT_LINE = "終了コード1: --strict の条件（warn か error の候補が1件以上）に当たりました（error {e}件、warn {w}件）。"

# 10.1 L4: 終了コード1の行の {条件}。当たった条件を指定した順に「、」でつなぐ（同じ文は1回）。
COND_STRICT = "--strict の条件（warn か error の候補が1件以上）"
COND_WARN = "--fail-on=warn の条件（warn か error の候補が1件以上）"
COND_ERROR = "--fail-on=error の条件（error の候補が1件以上）"
EXIT1_LINE = "終了コード1: {conditions}に当たりました（error {e}件、warn {w}件）。"

# 10.1 L5: 知らない --fail-on の値
UNKNOWN_FAIL_ON = "--fail-on に使えない値です: {}。lint で使えるのは warn と error です。"

# 10.1 L11: 誤りの文の日本語。OSError の理由は OS が決めるので、かっこの中は問わない。
OPEN_ERROR = re.compile(r"^Error opening file (?P<path>.+): ファイルを開けません（(?P<reason>.+)）\n$")
NOT_UTF8_FILE = "Error opening file {}: UTF-8 として読めません\n"
NOT_UTF8_STDIN = "Error reading stdin: UTF-8 として読めません\n"
STDIN_ERROR = re.compile(r"^Error reading stdin: 標準入力を読めません（.+）\n$")

MEANING_RISK_MESSAGE = (
    "--fail-on=meaning-risk は lint では使えません。lint は1つの文章だけを見るので、意味の変化は判定できません。"
    "原文と比べる yomiyasu_diff.py か yomiyasu_check.py に付けてください。"
)

# 先頭の設定（frontmatter）を含む入力。BOM があると v1.1.2 では先頭の設定として読まれない。
FRONTMATTER_TEXT = "---\ntitle: 設定の手順\ntags: 例\n---\n本記事では、設定を紹介します。\n"

JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龥]")

# プロセスの中で markdown_visibility.analyze_markdown を例外を出すものに差し替え、runpy で lint を動かす。
# lint_text の差し替えは runpy がファイルを読み直すので効かない（設計 0.1 の表、判定2 F7）。
# 標準入力がない（None の）ときの誤りの文を見るための実行用コード。
NO_STDIN_WORKER = (
    "import runpy, sys\n"
    "script = sys.argv[1]\n"
    "sys.stdin = None\n"
    "sys.argv = [script] + sys.argv[2:]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)

# 1.4 のヘルプの文（説明、file、--strict、--fail-on、--json、--version）
HELP_TEXTS = {
    "description": ("日本語の表現とMarkdownの書式を、決まった規則で点検します。結果は見直し候補です。"
                    "候補の数や点数は、文章の品質、意味の保持、読者にとっての分かりやすさの合否ではありません。"),
    "file": "検査するファイル（UTF-8）。省略するか - を渡すと標準入力を読みます。",
    "--strict": ("warn か error の候補が1件でもあれば、終了コード1で終わります。"
                 "info の候補と点数は使いません（--fail-on=warn と同じです）。"),
    "--fail-on": ("指定した中身の候補があれば、終了コード1で終わります。warn: warn か error の候補。"
                  "error: error の候補（太字が表示されない書き方）。何度でも、カンマ区切りでも指定できます。"
                  "点数は条件に使えません。meaning-risk は2つの文章を比べないと判定できないので、"
                  "yomiyasu_diff.py か yomiyasu_check.py に付けてください。"),
    "--json": ("結果をJSON（形式2）で出します。日本語は \\uXXXX の形で出します。"
               "rule_penalty_score は、候補の多さを地の文の長さで割った目安です（下の式）。合否には使わないでください。"),
    "--version": "バージョンを表示して終わります。",
}

# 古い版（v1.1.2）の markdown_visibility の代わり。decode_source だけがない。
OLD_VISIBILITY_STUB = "".join(
    "def {}(*args, **kwargs):\n    raise AssertionError('old markdown_visibility')\n\n\n".format(name)
    for name in ("analyze_markdown", "line_visible_text", "range_overlaps_protected",
                 "inline_protected_spans", "unicode_whitespace")
)

# lint をモジュールとして spec_from_file_location で読み、読めたかどうかを標準出力に書く。
# 使い方: python -B -c LOAD_LINT_WORKER <lint のパス> [先に sys.path に足して import markdown_visibility するフォルダ]
LOAD_LINT_WORKER = (
    "import importlib.util, sys\n"
    "if len(sys.argv) > 2:\n"
    "    sys.path.insert(0, sys.argv[2])\n"
    "    import markdown_visibility\n"
    "spec = importlib.util.spec_from_file_location('_lint_under_test', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "try:\n"
    "    spec.loader.exec_module(module)\n"
    "except ImportError as error:\n"
    "    print('ImportError', 'decode_source' in str(error))\n"
    "else:\n"
    "    print('loaded', module.lint_text(sys.stdin.read())['candidate_count'])\n"
)

INTERNAL_ERROR_WORKER = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import markdown_visibility\n"
    "def broken(*args, **kwargs):\n"
    "    raise RuntimeError('synthetic failure for the test')\n"
    "markdown_visibility.analyze_markdown = broken\n"
    "script = sys.argv[2]\n"
    "sys.argv = [script] + sys.argv[3:]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)


def run_lint(args, stdin=None, env=None, cwd=None):
    """lint を子プロセスで動かす（test_trailing_colon.py:129-136 の型）。stdin がなければ空の入力を渡す。"""
    kwargs = {}
    if stdin is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin
    return subprocess.run(
        [sys.executable, "-B", str(LINT)] + [str(a) for a in args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
        cwd=cwd,
        **kwargs
    )


def run_lint_bytes_stdin(args, stdin_path):
    """標準入力にファイルのバイト列をそのまま渡す（BOM や UTF-8 でないバイト列のため）。"""
    with open(str(stdin_path), "rb") as handle:
        return subprocess.run(
            [sys.executable, "-B", str(LINT)] + [str(a) for a in args],
            stdin=handle,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )


def run_lint_cp932(args, stdin=b"", cwd=None):
    """Windows の日本語環境と同じ標準入出力（cp932、surrogateescape）で lint を動かし、バイト列のまま返す
    （tests/test_stdio_encoding.py の run_cp932 と同じ型）。"""
    env = dict(os.environ, PYTHONIOENCODING="cp932:surrogateescape")
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, "-B", str(LINT)] + [str(a) for a in args],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=30,
        cwd=cwd,
    )


def utf8_text(data):
    """バイト列を UTF-8 として厳密に読む（読めなければ UnicodeDecodeError で試験が落ちる）。改行は LF にそろえる。"""
    return data.decode("utf-8").replace("\r\n", "\n")


def output_lines(process):
    """標準出力を行に分ける。末尾の改行の数は test_stdout_ends_with_one_newline で見る（10.1 L3）。"""
    return process.stdout.rstrip("\n").split("\n")


class LintCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v200-lint-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def write_bytes(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def lint_json(self, args, stdin=None):
        process = run_lint(list(args) + ["--json"], stdin=stdin)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        return json.loads(process.stdout)

    def assert_input_severities(self, *severities):
        """試験の入力の前提: INFO_ONLY などの候補の重さが、その1種類だけ。"""
        for severity, text in SINGLE_SEVERITY_INPUTS:
            if severity not in severities:
                continue
            found = sorted({finding.get("severity") for finding in self.lint_json([], stdin=text)["findings"]})
            self.assertEqual(found, [severity],
                             "入力の前提が崩れた（{} だけのはずの文の候補の重さが {}）。"
                             "規則を変えたら文を選び直す".format(severity, found))


class TestHumanReport(LintCase):
    """1.1 の人が読む通常の出力。"""

    def test_example1_no_candidates_exact(self):
        """候補なしの全文が 1.1 の例1と完全に同じ。"""
        process = run_lint([], stdin=EXAMPLE1_INPUT)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(output_lines(process), EXAMPLE1_LINES)

    def test_example2_with_candidates_exact(self):
        """候補ありの全文が 1.1 の例2（--strict なし）と完全に同じ。終了コード0。"""
        process = run_lint([], stdin=EXAMPLE2_INPUT)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(output_lines(process), EXAMPLE2_LINES)

    def test_example2_strict_adds_two_lines(self):
        """--strict 付きは最後の2行（空行と終了コード1の行）が足され、終了コード1、標準エラーは空。"""
        process = run_lint(["--strict"], stdin=EXAMPLE2_INPUT)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(output_lines(process), EXAMPLE2_LINES + EXAMPLE2_STRICT_TAIL)

    def test_stdout_ends_with_one_newline(self):
        """最後の行のあとに改行が1つ（10.1 L3）。候補なし、候補あり、--strict に当たったとき。"""
        cases = (
            ("example1", [], EXAMPLE1_INPUT, EXAMPLE1_LINES, 0),
            ("example2", [], EXAMPLE2_INPUT, EXAMPLE2_LINES, 0),
            ("example2-strict", ["--strict"], EXAMPLE2_INPUT, EXAMPLE2_LINES + EXAMPLE2_STRICT_TAIL, 1),
        )
        for name, args, text, lines, code in cases:
            with self.subTest(case=name):
                process = run_lint(args, stdin=text)
                self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "\n".join(lines) + "\n")

    def test_render_functions_match_the_cli(self):
        """render_report() は通常の出力の全体、render_findings() は内訳と候補の並びだけ。どちらも末尾に改行を付けない（1.7、10.1 L3）。"""
        for name in ("render_report", "render_findings"):
            self.assertTrue(callable(getattr(yomiyasu_lint, name, None)), "yomiyasu_lint.{} がない".format(name))
        for name, text, lines in (("example1", EXAMPLE1_INPUT, EXAMPLE1_LINES),
                                  ("example2", EXAMPLE2_INPUT, EXAMPLE2_LINES)):
            with self.subTest(case=name):
                result = yomiyasu_lint.lint_text(text)
                self.assertEqual(yomiyasu_lint.render_report(result), "\n".join(lines))
                self.assertEqual(yomiyasu_lint.render_findings(result), "\n".join(lines[4:]))
                # JSON（形式2）を読み直した辞書でも同じ出力になる（check が記録から作り直すときのため）。
                reloaded = json.loads(json.dumps(result, ensure_ascii=True))
                self.assertEqual(yomiyasu_lint.render_report(reloaded), "\n".join(lines))
        self.assertEqual(yomiyasu_lint.render_findings(yomiyasu_lint.lint_text(EXAMPLE1_INPUT)), "")

    def test_removed_markers_are_gone(self):
        """[PASS]、[NOTICE]、スコア、/100、文字数:、===== を含まない。"""
        cases = (
            ("example1", [], EXAMPLE1_INPUT),
            ("example2", [], EXAMPLE2_INPUT),
            ("example2-strict", ["--strict"], EXAMPLE2_INPUT),
        )
        for name, args, text in cases:
            with self.subTest(case=name):
                process = run_lint(args, stdin=text)
                self.assertIn(process.returncode, (0, 1), process.stderr)
                # 新しい出力の1行目があることを先に確かめる（出力が空のまま通らないように）。
                self.assertEqual(output_lines(process)[0], "表現・書式の検査を実行しました。")
                for marker in ("[PASS]", "[NOTICE]", "スコア", "/100", "文字数:", "====="):
                    self.assertNotIn(marker, process.stdout)


class TestJsonFormat2(LintCase):
    """1.3 の --json（形式2）と、lint_text() の戻り値。"""

    def version(self):
        value = getattr(yomiyasu_lint, "__version__", None)
        self.assertIsInstance(value, str, "yomiyasu_lint.__version__ がない")
        return value

    def test_keys_and_order_api_and_cli(self):
        """list(result) が 1.3 の10キーと順まで同じ（lint_text() と CLI の --json）。"""
        self.assertEqual(list(yomiyasu_lint.lint_text(EXAMPLE2_INPUT)), JSON_KEYS)
        self.assertEqual(list(self.lint_json([], stdin=EXAMPLE2_INPUT)), JSON_KEYS)

    def test_cli_json_layout(self):
        """--json は字下げ2、ensure_ascii、末尾の改行1つ（0.4、10.1 L3）。"""
        process = run_lint(["--json"], stdin=EXAMPLE2_INPUT)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(process.stdout.startswith('{\n  "format": "yomiyasu-lint",\n  "format_version": 2,'),
                        process.stdout[:80])
        self.assertTrue(process.stdout.isascii())
        self.assertEqual(process.stdout, json.dumps(json.loads(process.stdout), ensure_ascii=True, indent=2) + "\n")

    def test_format_and_versions(self):
        """format、format_version == 2、tool_version == __version__、not_judged。"""
        version = self.version()
        for source, result in (("api", yomiyasu_lint.lint_text(EXAMPLE2_INPUT)),
                               ("cli", self.lint_json([], stdin=EXAMPLE2_INPUT))):
            with self.subTest(source=source):
                self.assertEqual(result.get("format"), "yomiyasu-lint")
                self.assertEqual(result.get("format_version"), 2)
                self.assertIsInstance(result.get("format_version"), int)
                self.assertEqual(result.get("tool_version"), version)
                self.assertEqual(result.get("not_judged"), NOT_JUDGED)

    def test_example2_score_and_counts(self):
        """例2の入力で rule_penalty_score 83、candidate_count 4、counts、no_rule_findings は偽。"""
        result = self.lint_json([], stdin=EXAMPLE2_INPUT)
        # 地の文56字、error 1件・warn 2件・info 1件の重み8で83。
        self.assertEqual(result.get("rule_penalty_score"), 83)
        self.assertEqual(result.get("candidate_count"), 4)
        self.assertEqual(result.get("counts"), {"error": 1, "warn": 2, "info": 1})
        self.assertIs(result.get("no_rule_findings"), False)
        self.assertNotIn("score", result)
        self.assertNotIn("is_clean", result)
        # 1.3 の例の metrics（今と同じ6キー）
        self.assertEqual(result.get("metrics"), {
            "char_count": 56, "total_lines": 3, "list_lines": 0,
            "list_ratio": 0.0, "bold_count": 1, "bold_per_1000": 17.86,
        })

    def test_example1_zero_counts(self):
        """counts の3つのキーは0件でも必ず出る。候補なしなら no_rule_findings は真、rule_penalty_score は100。"""
        result = self.lint_json([], stdin=EXAMPLE1_INPUT)
        self.assertEqual(result.get("candidate_count"), 0)
        self.assertEqual(result.get("counts"), {"error": 0, "warn": 0, "info": 0})
        self.assertIs(result.get("no_rule_findings"), True)
        self.assertEqual(result.get("rule_penalty_score"), 100)
        self.assertNotIn("score", result)
        self.assertNotIn("is_clean", result)

    def test_findings_shape_and_order_are_kept(self):
        """各要素のキーが5つちょうどで、JSON の findings の順が v1.1.2 と同じ（人の出力は行の順でも、JSON の順は変えない）。（v1.1.2 でも通る後戻り防止）"""
        expected_order = ["bold_not_rendered", "meta_filler", "slop_vocabulary", "meta_intro"]
        for source, result in (("api", yomiyasu_lint.lint_text(EXAMPLE2_INPUT)),
                               ("cli", self.lint_json([], stdin=EXAMPLE2_INPUT))):
            with self.subTest(source=source):
                findings = result["findings"]
                self.assertEqual([f["rule"] for f in findings], expected_order)
                self.assertEqual([f["line"] for f in findings], [3, 1, 2, 2])
                for finding in findings:
                    self.assertEqual(set(finding), FINDING_KEYS)


class TestStrictAndFailOn(LintCase):
    """1.4 の --strict と --fail-on、1.1 の終了コード1の行。"""

    def test_strict_exit_codes(self):
        """--strict: info だけ → 0、warn → 1、error だけ → 1。1のとき標準エラーは空。（v1.1.2 でも通る後戻り防止）"""
        self.assert_input_severities("info", "warn", "error")
        for name, text, expected in (("info", INFO_ONLY, 0), ("warn", WARN_ONLY, 1), ("error", ERROR_ONLY, 1)):
            with self.subTest(case=name):
                process = run_lint(["--strict"], stdin=text)
                self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")

    def test_strict_reports_the_condition_on_stdout(self):
        """--strict に当たると、最後に空行と「終了コード1: …」の1行を標準出力に出す。当たらなければ出さない。"""
        self.assert_input_severities("info", "warn", "error")
        cases = (
            ("warn", WARN_ONLY, 1, STRICT_LINE.format(e=0, w=1)),
            ("error", ERROR_ONLY, 1, STRICT_LINE.format(e=1, w=0)),
            ("info", INFO_ONLY, 0, None),
        )
        for name, text, expected, last_line in cases:
            with self.subTest(case=name):
                process = run_lint(["--strict"], stdin=text)
                self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                lines = output_lines(process)
                self.assertEqual(lines[0], "表現・書式の検査を実行しました。")
                if last_line is None:
                    self.assertNotIn("終了コード1", process.stdout)
                else:
                    self.assertEqual(lines[-2:], ["", last_line])

    def test_strict_with_json_keeps_json_only(self):
        """--json のときは終了コード1の行を出さず、JSON（形式2）の形を変えない。"""
        self.assert_input_severities("warn")
        process = run_lint(["--json", "--strict"], stdin=WARN_ONLY)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertNotIn("終了コード1", process.stdout)
        result = json.loads(process.stdout)
        self.assertEqual(result.get("format_version"), 2)
        self.assertEqual(list(result), JSON_KEYS)

    def assert_fail_on_hit(self, process, conditions, errors, warns):
        """最後に空行と、当たった条件を指定した順に「、」でつないだ1行（10.1 L4）。件数は0件でも書く。"""
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        lines = output_lines(process)
        self.assertEqual(lines[0], "表現・書式の検査を実行しました。")
        self.assertEqual(lines[-2:], ["", EXIT1_LINE.format(conditions="、".join(conditions), e=errors, w=warns)])

    def assert_fail_on_pass(self, process):
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(output_lines(process)[0], "表現・書式の検査を実行しました。")
        self.assertNotIn("終了コード1", process.stdout)

    def test_fail_on_error(self):
        """--fail-on=error: warn だけ → 0、error → 1。"""
        self.assert_input_severities("warn", "error")
        self.assert_fail_on_pass(run_lint(["--fail-on=error"], stdin=WARN_ONLY))
        self.assert_fail_on_hit(run_lint(["--fail-on=error"], stdin=ERROR_ONLY), [COND_ERROR], 1, 0)
        self.assert_fail_on_hit(run_lint(["--fail-on", "error"], stdin=EXAMPLE2_INPUT), [COND_ERROR], 1, 2)

    def test_fail_on_warn_is_same_as_strict(self):
        """--fail-on=warn は --strict と同じ: info だけ → 0、warn → 1、error だけ → 1。"""
        self.assert_input_severities("info", "warn", "error")
        self.assert_fail_on_pass(run_lint(["--fail-on=warn"], stdin=INFO_ONLY))
        self.assert_fail_on_hit(run_lint(["--fail-on=warn"], stdin=WARN_ONLY), [COND_WARN], 0, 1)
        self.assert_fail_on_hit(run_lint(["--fail-on=warn"], stdin=ERROR_ONLY), [COND_WARN], 1, 0)

    def test_fail_on_accepts_commas_and_repeats(self):
        """カンマ区切り（error,warn）と、何度でも付ける形。どれか1つに当たれば1。"""
        self.assert_input_severities("info", "warn")
        self.assert_fail_on_hit(run_lint(["--fail-on=error,warn"], stdin=WARN_ONLY), [COND_WARN], 0, 1)
        self.assert_fail_on_pass(run_lint(["--fail-on=error,warn"], stdin=INFO_ONLY))
        self.assert_fail_on_hit(run_lint(["--fail-on=error", "--fail-on=warn"], stdin=WARN_ONLY), [COND_WARN], 0, 1)

    def test_fail_on_combines_with_strict(self):
        """--strict と --fail-on の両方があれば合わせて扱う（warn だけの文に --strict --fail-on=error → 1）。"""
        self.assert_input_severities("warn")
        self.assert_fail_on_hit(run_lint(["--strict", "--fail-on=error"], stdin=WARN_ONLY), [COND_STRICT], 0, 1)

    def test_hit_conditions_keep_the_given_order_once_each(self):
        """当たった条件は指定した順に並べ、同じ文は1回だけ書く（10.1 L4）。--strict と --fail-on の間の順も保つ。"""
        cases = (
            (["--fail-on=error,warn", "--strict", "--fail-on=warn"], [COND_ERROR, COND_WARN, COND_STRICT]),
            (["--fail-on=warn", "--strict"], [COND_WARN, COND_STRICT]),
            (["--strict", "--fail-on=warn", "--fail-on=error"], [COND_STRICT, COND_WARN, COND_ERROR]),
            (["--strict", "--strict", "--fail-on=error,error"], [COND_STRICT, COND_ERROR]),
        )
        for args, conditions in cases:
            with self.subTest(args=args):
                self.assert_fail_on_hit(run_lint(args, stdin=EXAMPLE2_INPUT), conditions, 1, 2)

    def test_fail_on_with_json_keeps_json_only(self):
        """--json --fail-on=error でも終了コード1の行を出さず、JSON（形式2）の形を変えない（1.1）。"""
        self.assert_input_severities("error")
        process = run_lint(["--json", "--fail-on=error"], stdin=ERROR_ONLY)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertNotIn("終了コード1", process.stdout)
        result = json.loads(process.stdout)
        self.assertEqual(list(result), JSON_KEYS)

    def test_fail_on_unknown_value_exits_2(self):
        """知らない値（nope）は終了コード2で、標準エラーは 10.1 L5 の文だけ。知らない引数の誤りにはしない。"""
        for args in (["--fail-on=nope"], ["--fail-on", "nope"], ["--fail-on=warn,nope"], ["--strict", "--fail-on=nope"]):
            with self.subTest(args=args):
                process = run_lint(args, stdin=WARN_ONLY)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr, UNKNOWN_FAIL_ON.format("nope") + "\n")

    def test_fail_on_empty_values_show_an_empty_marker(self):
        """値の要素がすべて空（空、空白だけ、カンマだけ）なら、L5 の文の値の欄を「（空）」にする（目に見えない値を書かない）。"""
        for value in ("", " ", ",", " , "):
            with self.subTest(value=value):
                process = run_lint(["--fail-on=" + value], stdin=WARN_ONLY)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr, UNKNOWN_FAIL_ON.format("（空）") + "\n")

    def test_fail_on_meaning_risk_is_rejected_with_guidance(self):
        """--fail-on=meaning-risk は終了コード2、標準出力は空、標準エラーで diff か check を案内する。"""
        for args in (["--fail-on=meaning-risk"], ["--fail-on", "meaning-risk"]):
            with self.subTest(args=args):
                process = run_lint(args, stdin=WARN_ONLY)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn("yomiyasu_diff.py", process.stderr)
                self.assertIn("yomiyasu_check.py", process.stderr)
                self.assertEqual(process.stderr, MEANING_RISK_MESSAGE + "\n")

    def test_fail_on_meaning_risk_mixed_with_other_values_exits_2(self):
        """meaning-risk をカンマ区切りや繰り返しでほかの値と混ぜても、黙って捨てずに終了コード2、標準出力は空。
        標準エラーは 1.4 の文をそのまま出す（10.1 L14）。"""
        # warn だけの文を渡すので、meaning-risk を捨てて warn だけで動くと終了コード1になり、区別できる。
        for args in (["--fail-on=warn,meaning-risk"], ["--fail-on=warn", "--fail-on=meaning-risk"],
                     ["--strict", "--fail-on=meaning-risk,error"]):
            with self.subTest(args=args):
                process = run_lint(args, stdin=WARN_ONLY)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertNotIn("unrecognized arguments", process.stderr)
                self.assertIn("yomiyasu_diff.py", process.stderr)
                self.assertIn("yomiyasu_check.py", process.stderr)
                self.assertEqual(process.stderr, MEANING_RISK_MESSAGE + "\n")


class TestErrors(LintCase):
    """1.5 の終了コード2と3。"""

    def test_internal_error_exits_3(self):
        """analyze_markdown が例外を出すと終了コード3、標準エラーに「内部エラー」とトレースバック。"""
        path = self.write("sample.md", "設定を変更します。\n")
        process = subprocess.run(
            [sys.executable, "-B", "-c", INTERNAL_ERROR_WORKER, str(SCRIPTS_DIR), str(LINT), str(path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            cwd=str(self.root),
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        self.assertIn("内部エラー", process.stderr)
        self.assertIn("yomiyasu_lint.py: 内部エラー: RuntimeError: synthetic failure for the test", process.stderr)
        self.assertIn("Traceback", process.stderr)

    def test_input_errors_keep_english_prefix(self):
        """ないファイル → 2 で標準エラーが Error opening file で始まる。UTF-8 でない標準入力 → Error reading stdin。トレースバックは出さない。（v1.1.2 でも通る後戻り防止）"""
        missing = self.root / "missing.md"
        process = run_lint([missing])
        self.assertEqual(process.returncode, 2)
        self.assertTrue(process.stderr.startswith("Error opening file"), process.stderr)
        self.assertNotIn("Traceback", process.stderr)

        cp932 = self.write_bytes("cp932.txt", "設定を変更します。\n".encode("cp932"))
        process = run_lint_bytes_stdin(["--json"], cp932)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn("Error reading stdin", process.stderr)
        self.assertNotIn("Traceback", process.stderr)

    def test_error_messages_continue_in_japanese(self):
        """英語の書き出しのあとに日本語の説明が続く（0.4、1.5）。ない・ディレクトリ・UTF-8 でないファイルと、UTF-8 でない標準入力。"""
        cp932 = self.write_bytes("cp932.md", "設定を変更します。\n".encode("cp932"))
        folder = self.root / "folder"
        folder.mkdir()
        for name, path in (("missing", self.root / "missing.md"), ("directory", folder), ("not-utf8", cp932)):
            with self.subTest(case=name):
                process = run_lint([path])
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                prefix = "Error opening file {}: ".format(path)
                self.assertTrue(process.stderr.startswith(prefix), process.stderr)
                # 理由の文にパスが入ることがある（v1.1.2 の [Errno 2] … '<パス>'）。
                # 一時フォルダのパスに仮名や漢字があっても通らないよう、パスを除いてから探す。
                remainder = process.stderr[len(prefix):]
                for text in (str(path), str(path.resolve())):
                    remainder = remainder.replace(text, "")
                self.assertRegex(remainder, JAPANESE)
        with self.subTest(case="stdin"):
            process = run_lint_bytes_stdin([], cp932)
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertTrue(process.stderr.startswith("Error reading stdin: "), process.stderr)
            self.assertRegex(process.stderr[len("Error reading stdin: "):], JAPANESE)

    def test_error_messages_follow_10_1_l11(self):
        """誤りの文は 10.1 L11 の形。開けないファイルは「ファイルを開けません（理由）」、UTF-8 でないときは
        「UTF-8 として読めません」（ファイルも標準入力も）、標準入力がないときは「標準入力を読めません（理由）」。
        標準出力は空で、トレースバックは出さない。"""
        cp932 = self.write_bytes("cp932.md", "設定を変更します。\n".encode("cp932"))
        folder = self.root / "folder"
        folder.mkdir()
        for name, path in (("missing", self.root / "missing.md"), ("directory", folder)):
            with self.subTest(case=name):
                process = run_lint([path])
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                match = OPEN_ERROR.match(process.stderr)
                self.assertIsNotNone(match, process.stderr)
                self.assertEqual(match.group("path"), str(path))
                # 理由は OS の文。パスを繰り返さない（strerror を使う）。
                self.assertNotIn(str(path), match.group("reason"))
        with self.subTest(case="not-utf8-file"):
            process = run_lint([cp932])
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertEqual(process.stdout, "")
            self.assertEqual(process.stderr, NOT_UTF8_FILE.format(cp932))
        for name, args in (("not-utf8-stdin", []), ("not-utf8-dash", ["-"])):
            with self.subTest(case=name):
                process = run_lint_bytes_stdin(args, cp932)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr, NOT_UTF8_STDIN)
        with self.subTest(case="no-stdin"):
            process = subprocess.run(
                [sys.executable, "-B", "-c", NO_STDIN_WORKER, str(LINT), "--json"],
                stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertEqual(process.stdout, "")
            self.assertRegex(process.stderr, STDIN_ERROR)

    def test_argparse_usage_errors_exit_2(self):
        """argparse の使い方の誤り（知らない引数、値のない --fail-on、値を取らない --strict に値）は終了コード2（1.5）。
        標準出力は空で、内部エラーの行やトレースバックは出さない。"""
        for args in (["--nope"], ["--fail-on"], ["--strict=yes"]):
            with self.subTest(args=args):
                process = run_lint(args, stdin=WARN_ONLY)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertTrue(process.stderr.startswith("使い方: yomiyasu_lint.py"), process.stderr)
                self.assertNotIn("内部エラー", process.stderr)
                self.assertNotIn("Traceback", process.stderr)
        self.assertIn("--nope", run_lint(["--nope"], stdin=WARN_ONLY).stderr)

    def test_stderr_is_utf8_in_a_cp932_environment(self):
        """標準入出力が cp932 の環境でも、標準エラーは UTF-8 で書く（0.4。errors="backslashreplace"）。
        L5、L11、1.4 の文と、argparse の使い方の誤り。"""
        missing = self.root / "なし🚀.md"
        cases = (
            ("L5", ["--fail-on=なし🚀"], b"", UNKNOWN_FAIL_ON.format("なし🚀") + "\n"),
            ("L14", ["--fail-on=meaning-risk"], b"", MEANING_RISK_MESSAGE + "\n"),
            ("L11-stdin", [], "設定を変更します。\n".encode("cp932"), NOT_UTF8_STDIN),
        )
        for name, args, stdin, expected in cases:
            with self.subTest(case=name):
                process = run_lint_cp932(args, stdin=stdin)
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertEqual(process.stdout, b"")
                self.assertEqual(utf8_text(process.stderr), expected)
        with self.subTest(case="L11-file"):
            process = run_lint_cp932([missing])
            self.assertEqual(process.returncode, 2, process.stderr)
            self.assertEqual(process.stdout, b"")
            match = OPEN_ERROR.match(utf8_text(process.stderr))
            self.assertIsNotNone(match, process.stderr)
            self.assertEqual(match.group("path"), str(missing))
        with self.subTest(case="argparse"):
            process = run_lint_cp932(["--nope"])
            self.assertEqual(process.returncode, 2, process.stderr)
            self.assertEqual(process.stdout, b"")
            text = utf8_text(process.stderr)
            self.assertTrue(text.startswith("使い方: yomiyasu_lint.py"), text)
            self.assertIn("unrecognized arguments: --nope\n", text)

    def test_mismatched_markdown_visibility_is_an_internal_error(self):
        """隣の markdown_visibility.py が古い版（decode_source がない）とき、スクリプトとしては終了コード3と
        内部エラーの行（1.5）。終了コード1（条件に当たった）にしない。モジュールとして読むときは ImportError のまま。"""
        partial = self.root / "partial"
        partial.mkdir()
        (partial / "yomiyasu_lint.py").write_bytes(LINT.read_bytes())
        (partial / "markdown_visibility.py").write_bytes(OLD_VISIBILITY_STUB.encode("utf-8"))
        sample = self.write("warn.md", WARN_ONLY)
        with self.subTest(case="script"):
            process = subprocess.run(
                [sys.executable, "-B", str(partial / "yomiyasu_lint.py"), "--fail-on=error", str(sample)],
                stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
            self.assertEqual(process.stdout, "")
            first_line = process.stderr.split("\n")[0]
            self.assertTrue(first_line.startswith("yomiyasu_lint.py: 内部エラー: ImportError: "), process.stderr)
            self.assertIn("decode_source", first_line)
            self.assertIn("Traceback", process.stderr)
        with self.subTest(case="module"):
            process = run_text(
                [sys.executable, "-B", "-c", LOAD_LINT_WORKER, str(partial / "yomiyasu_lint.py")],
                input=WARN_ONLY, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            self.assertEqual((process.returncode, process.stdout), (0, "ImportError True\n"), process.stderr)

    def test_loads_the_sibling_when_an_old_markdown_visibility_is_imported(self):
        """同じプロセスで古い版の markdown_visibility がすでに読まれていても、spec_from_file_location で読んだ lint は
        ファイルの隣の markdown_visibility.py を使う（7.2 の読み込みの型。名前が足りない ImportError でも隣に戻る）。"""
        old = self.root / "old"
        old.mkdir()
        (old / "markdown_visibility.py").write_bytes(OLD_VISIBILITY_STUB.encode("utf-8"))
        process = run_text(
            [sys.executable, "-B", "-c", LOAD_LINT_WORKER, str(LINT), str(old)],
            input=EXAMPLE2_INPUT, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        self.assertEqual((process.returncode, process.stdout), (0, "loaded 4\n"), process.stderr)


class TestMainFunction(LintCase):
    """1.5: main(argv=None) は終了コードを返す（CLI は sys.exit(main()) の形）。"""

    def setUp(self):
        super().setUp()
        self.assertIn("argv", inspect.signature(yomiyasu_lint.main).parameters, "main(argv=None) の形でない")

    def call_main(self, argv, stdin_text=None):
        out, err = io.StringIO(), io.StringIO()
        patches = [mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err)]
        if stdin_text is not None:
            patches.append(mock.patch.object(sys, "stdin", io.StringIO(stdin_text)))
        for patch in patches:
            patch.start()
        try:
            code = yomiyasu_lint.main(argv)
        finally:
            for patch in reversed(patches):
                patch.stop()
        return code, out.getvalue(), err.getvalue()

    def test_main_returns_exit_codes(self):
        path = self.write("warn.md", WARN_ONLY)
        self.assertEqual(self.call_main(["--version"]), (0, "yomiyasu_lint.py 3.0.0 (JSON format 2)\n", ""))
        code, out, err = self.call_main([str(path)])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.split("\n")[0], "表現・書式の検査を実行しました。")
        code, out, err = self.call_main(["--strict", str(path)])
        self.assertEqual((code, err), (1, ""))
        code, out, err = self.call_main(["--fail-on=nope", str(path)])
        self.assertEqual((code, out, err), (2, "", UNKNOWN_FAIL_ON.format("nope") + "\n"))
        code, out, err = self.call_main(["-", "--json"], stdin_text="\ufeff" + EXAMPLE2_INPUT.replace("\n", "\r\n"))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), yomiyasu_lint.lint_text(EXAMPLE2_INPUT))

    def call_main_with_streams(self, argv, stdout, stderr):
        """\u6a19\u6e96\u51fa\u529b\u304b\u6a19\u6e96\u30a8\u30e9\u30fc\u3092 None\uff08pythonw \u3084\u30012>&- \u3067\u9589\u3058\u305f\u3068\u304d\uff09\u306b\u3057\u3066 main \u3092\u547c\u3076\u3002argparse \u306e\u7d42\u308f\u308a\u65b9\u3082\u62fe\u3046\u3002"""
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr), \
                mock.patch.object(sys, "stdin", io.StringIO(WARN_ONLY)):
            try:
                return yomiyasu_lint.main(argv)
            except SystemExit as stop:
                return stop.code

    def test_missing_streams_keep_messages_off_the_other_stream(self):
        """\u6a19\u6e96\u30a8\u30e9\u30fc\u304c\u306a\u3044\u3068\u304d\u306e\u4f7f\u3044\u65b9\u306e\u8aa4\u308a\u306f\u7d42\u4e86\u30b3\u30fc\u30c92\u3067\u3001\u4f7f\u3044\u65b9\u3092\u6a19\u6e96\u51fa\u529b\u306b\u66f8\u304b\u306a\u3044\uff081.5\u30010.4\uff09\u3002
        \u6a19\u6e96\u51fa\u529b\u304c\u306a\u3044\u3068\u304d\u306e -h \u306f\u7d42\u4e86\u30b3\u30fc\u30c90\u3067\u3001\u30d8\u30eb\u30d7\u3092\u6a19\u6e96\u30a8\u30e9\u30fc\u306b\u66f8\u304b\u306a\u3044\uff080.4: 0\u306e\u3068\u304d\u6a19\u6e96\u30a8\u30e9\u30fc\u306f\u7a7a\uff09\u3002"""
        for argv in (["--nope"], ["--fail-on"], ["--fail-on=nope"]):
            with self.subTest(argv=argv, missing="stderr"):
                out = io.StringIO()
                self.assertEqual(self.call_main_with_streams(argv, out, None), 2)
                self.assertEqual(out.getvalue(), "")
        with self.subTest(argv=["-h"], missing="stdout"):
            err = io.StringIO()
            self.assertEqual(self.call_main_with_streams(["-h"], None, err), 0)
            self.assertEqual(err.getvalue(), "")


class TestDecodeSource(unittest.TestCase):
    """0.4: markdown_visibility.decode_source(data) -> (text, info)。"""

    def setUp(self):
        self.assertTrue(callable(getattr(markdown_visibility, "decode_source", None)),
                        "markdown_visibility.decode_source がない")

    def test_bom_and_line_endings(self):
        cases = (
            (b"a\nb\n", "a\nb\n", False, "lf"),
            (b"a\r\nb\r\n", "a\nb\n", False, "crlf"),
            (b"a\rb\r", "a\nb\n", False, "cr"),
            (b"a\r\nb\nc\r", "a\nb\nc\n", False, "mixed"),
            (b"a\r\nb\n", "a\nb\n", False, "mixed"),
            (b"abc", "abc", False, "none"),
            (b"", "", False, "none"),
            (b"\xef\xbb\xbf---\r\nx: 1\r\n---\r\n", "---\nx: 1\n---\n", True, "crlf"),
            # BOM は先頭の1つだけ外す
            (b"\xef\xbb\xbf\xef\xbb\xbfa", "\ufeffa", True, "none"),
            # 先頭以外の U+FEFF は外さない
            ("a\ufeffb".encode("utf-8"), "a\ufeffb", False, "none"),
        )
        for data, text, bom, eol in cases:
            with self.subTest(data=data):
                self.assertEqual(markdown_visibility.decode_source(data), (text, {"bom": bom, "eol": eol}))

    def test_string_input_skips_decoding(self):
        """標準入力が StringIO のときは read() した文字列を渡す。BOM と改行の処理だけをする。"""
        self.assertEqual(markdown_visibility.decode_source("\ufeffa\r\nb"), ("a\nb", {"bom": True, "eol": "crlf"}))

    def test_strict_utf8(self):
        for data in ("設定".encode("cp932"), b"\xed\xa0\x80", b"\xff"):
            with self.subTest(data=data):
                with self.assertRaises(UnicodeDecodeError):
                    markdown_visibility.decode_source(data)


class TestInput(LintCase):
    """1.6 と 0.4 の入力の読み方。"""

    def test_dash_reads_stdin(self):
        """位置引数 - で標準入力を読む。ファイルで渡したときと同じ結果。"""
        path = self.write("sample.md", EXAMPLE2_INPUT)
        from_file = self.lint_json([path])
        from_dash = self.lint_json(["-"], stdin=EXAMPLE2_INPUT)
        self.assertEqual(from_dash, from_file)
        self.assertEqual(from_dash.get("candidate_count"), 4)

    def test_bom_does_not_change_frontmatter_result(self):
        """先頭の設定を含む入力で、BOM あり・なしの findings と metrics が同じ（ファイルと標準入力）。"""
        plain = self.write_bytes("plain.md", FRONTMATTER_TEXT.encode("utf-8"))
        bom = self.write_bytes("bom.md", b"\xef\xbb\xbf" + FRONTMATTER_TEXT.encode("utf-8"))
        expected = self.lint_json([plain])
        with self.subTest(via="file"):
            result = self.lint_json([bom])
            self.assertEqual(result["findings"], expected["findings"])
            self.assertEqual(result["metrics"], expected["metrics"])
        with self.subTest(via="stdin"):
            process = run_lint_bytes_stdin(["--json"], bom)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["findings"], expected["findings"])
            self.assertEqual(result["metrics"], expected["metrics"])

    def test_crlf_file_and_stdin_agree(self):
        """CRLF の入力で、ファイル経由と標準入力経由の JSON が同じ。（v1.1.2 でも通る後戻り防止）"""
        text = "重要なのは、テストを書くことです。\n確認事項：\n- 項目です。\n"
        data = text.replace("\n", "\r\n").encode("utf-8")
        path = self.write_bytes("crlf.md", data)
        from_file = self.lint_json([path])
        process = run_lint_bytes_stdin(["--json"], path)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout), from_file)
        self.assertTrue(from_file["findings"])


class TestHelpAndVersion(LintCase):
    """1.4 のヘルプと 0.4 の --version。"""

    def help_env(self):
        # 折り返しで語が切れないよう幅を広げ、色を付けない。
        env = dict(os.environ, COLUMNS="200", NO_COLOR="1")
        env.pop("FORCE_COLOR", None)
        env.pop("PYTHON_COLORS", None)
        return env

    def test_strict_help_mentions_info_and_score(self):
        """--strict の help に「info」と「点数」を含む。"""
        process = run_lint(["-h"], env=self.help_env())
        self.assertEqual(process.returncode, 0, process.stderr)
        text = process.stdout
        start = text.find("\n  --strict")
        self.assertNotEqual(start, -1, text)
        ends = [position for position in (text.find("\n  -", start + 1), text.find("\n\n", start + 1)) if position != -1]
        block = text[start:min(ends)] if ends else text[start:]
        self.assertIn("info", block)
        self.assertIn("点数", block)

    def test_help_texts_and_exit_code_table(self):
        """-h に 1.4 のヘルプの6つの文がそのまま入り、最後に終了コードの表（0〜3）がある（0.4 の epilog）。"""
        env = dict(self.help_env(), COLUMNS="2000")
        process = run_lint(["-h"], env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        for name, text in HELP_TEXTS.items():
            with self.subTest(part=name):
                self.assertIn(text, process.stdout)
        tail = process.stdout.rstrip("\n").split("\n")[-5:]
        self.assertEqual(tail[0], "終了コード:", process.stdout)
        for code, line in zip("0123", tail[1:]):
            self.assertRegex(line, r"^  {}  \S".format(code))

    def test_version_line(self):
        """--version は `yomiyasu_lint.py 3.0.0 (JSON format 2)`、終了コード0。"""
        process = run_lint(["--version"])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stdout.strip("\n"), "yomiyasu_lint.py 3.0.0 (JSON format 2)")
        self.assertEqual(process.stderr, "")



class TestMainDecisions(LintCase):
    """設計 10.5（lint の段で決めたこと）。"""

    def test_argparse_errors_end_with_a_japanese_hint(self):
        """argparse の使い方の誤りは、英語の行のあとに日本語の案内を1行足し、終了コード2。"""
        for args in (["--nope"], ["--strict=yes"], ["a.md", "b.md"]):
            with self.subTest(args=args):
                process = run_lint(args, stdin="")
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertEqual(process.stdout, "")
                lines = process.stderr.rstrip("\n").split("\n")
                self.assertIn("yomiyasu_lint.py: error: ", lines[-2])
                self.assertEqual(lines[-1], "引数の誤りです。yomiyasu_lint.py -h で使い方を確かめてください。")

    def test_fail_on_values_ignore_case_and_underscore(self):
        """--fail-on の値は、大文字と小文字、「_」と「-」を区別しない。"""
        self.assert_input_severities("error")
        for value in ("ERROR", "Error", " error "):
            with self.subTest(value=value):
                process = run_lint(["--fail-on=" + value], stdin=ERROR_ONLY)
                self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
        for value in ("MEANING-RISK", "meaning_risk", "Meaning_Risk"):
            with self.subTest(value=value):
                process = run_lint(["--fail-on=" + value], stdin="x\n")
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr.rstrip("\n"), MEANING_RISK_MESSAGE)

    def test_abbreviations_are_not_accepted(self):
        """10.7: argparse の省略形を受けない（allow_abbrev=False。lint、diff、check の3本でそろえる）。"""
        for args in (["--js"], ["--stri"], ["--fail", "warn"], ["--vers"]):
            with self.subTest(args=args):
                process = run_lint(args, stdin="x\n")
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn("unrecognized arguments", process.stderr)
                self.assertEqual(process.stderr.rstrip("\n").split("\n")[-1],
                                 "引数の誤りです。yomiyasu_lint.py -h で使い方を確かめてください。")

    def test_missing_or_broken_markdown_visibility_is_an_internal_error(self):
        """10.7: 隣に markdown_visibility.py がない、または読めない（構文の誤り）ときも、diff と同じく、スクリプトとしては
        終了コード3（1は --strict と --fail-on に当たったときだけ）。モジュールとして読むときは ImportError。"""
        sample = self.write("warn.md", WARN_ONLY)
        for case, content in (("missing", None), ("syntax-error", "def broken(:\n")):
            folder = self.root / case
            folder.mkdir()
            (folder / "yomiyasu_lint.py").write_bytes(LINT.read_bytes())
            if content is not None:
                (folder / "markdown_visibility.py").write_bytes(content.encode("utf-8"))
            with self.subTest(case=case, run="script"):
                process = subprocess.run(
                    [sys.executable, "-B", str(folder / "yomiyasu_lint.py"), "--fail-on=warn", str(sample)],
                    stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                    cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                first_line = process.stderr.split("\n")[0]
                self.assertTrue(first_line.startswith("yomiyasu_lint.py: 内部エラー: ImportError: "), process.stderr)
                self.assertIn("markdown_visibility.py", first_line)
            with self.subTest(case=case, run="module"):
                process = run_text(
                    [sys.executable, "-B", "-c", LOAD_LINT_WORKER, str(folder / "yomiyasu_lint.py")],
                    input=WARN_ONLY, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                    cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertTrue(process.stdout.startswith("ImportError"), process.stdout)

    def test_closed_output_pipe_exits_3_without_traceback(self):
        """読む側が先に閉じたときは、トレースバックを出さずに終了コード3（出力の大きさによらない）。"""
        big = "重要なのは、テストを書くことです。\n" * 20000
        for name, text in (("small", "あ\n"), ("large", big)):
            with self.subTest(size=name):
                process = subprocess.Popen(
                    [sys.executable, "-B", str(LINT)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                process.stdout.close()
                process.stdout = None
                _, err = process.communicate(text.encode("utf-8"), timeout=30)
                self.assertEqual(process.returncode, 3, err.decode("utf-8", "replace"))
                message = err.decode("utf-8")
                self.assertIn("出力先が閉じられたため、結果を最後まで書けませんでした。", message)
                self.assertNotIn("Traceback", message)


if __name__ == "__main__":
    unittest.main()
