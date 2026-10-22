#!/usr/bin/env python3
"""v2.0.0: 指示書2.2の3組（主語と目的語の入れ替え、数値、否定）を、API と CLI で再現する試験。

v1.1.2 では、3組とも lint は前後100点、diff は「（候補なし）」になり、変わった箇所が出なかった。
v2.0.0 では、変わった箇所が全文差分に出て、意味が変わる恐れの候補になり、意味を保ったとは判定しない。
期待値は設計の 6.1 の表、2.6〜2.8、1.1、1.3 に従う。
v1.1.2 では、この試験はすべて失敗する。
"""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
LINT = SCRIPTS_DIR / "yomiyasu_lint.py"
DIFF = SCRIPTS_DIR / "yomiyasu_diff.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402


# 指示書2.2の3組と、6.1 で期待する meaning_risks の kind
PAIRS = (
    ("田中が佐藤を承認した。", "佐藤が田中を承認した。", "swap"),
    ("保存期間は3日です。", "保存期間は30日です。", "number"),
    ("データを保存します。", "データを保存しません。", "negation"),
)
PAIR2_SEGMENTS = [["=", "保存期間は3"], ["+", "0"], ["=", "日です。"]]

# 読点だけを足した組（6.1）
COMMA_PAIR = ("会議は3時に始まります。", "会議は、3時に始まります。")

DIFF_FIRST_LINE = "差分の検査を実行しました。"
DISCLAIMER = (
    "全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。"
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。"
)
LINT_HEADER_ZERO = [
    "表現・書式の検査を実行しました。",
    "見直し候補: 0件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
]
LINT_NOT_JUDGED = ["meaning_preservation", "reader_comprehension"]
DIFF_NOT_JUDGED = ["meaning_equivalence", "reader_comprehension"]
# 6.1「passed、meaning_preserved のようなキー」。3.9 が使わないとする ok、passed、clean と、1.2 で消す is_clean も見る。
FORBIDDEN_KEYS = ("passed", "pass", "meaning_preserved", "is_clean", "clean", "ok")
FORBIDDEN_PHRASES = ("意味を保った", "合格", "問題ありません")


def run_cli(script, args, stdin=None):
    """CLI を子プロセスで動かす。stdin がなければ空の入力を渡す。"""
    kwargs = {}
    if stdin is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin
    return subprocess.run(
        [sys.executable, "-B", str(script)] + [str(a) for a in args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        **kwargs
    )


def as_json(value):
    """API の戻り値を JSON と同じ形（タプルはリスト）にそろえて比べる。"""
    return json.loads(json.dumps(value, ensure_ascii=True))


def all_keys(value):
    """入れ子の dict のキーをすべて集める。"""
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys |= all_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= all_keys(child)
    return keys


class PairCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v200-pairs-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def pair_files(self, index, before, after):
        return (self.write("pair{}-before.md".format(index), before + "\n"),
                self.write("pair{}-after.md".format(index), after + "\n"))

    def cli_text(self, script, args, stdin=None):
        """CLI を動かし、終了コード0で標準エラーが空であることを確かめてから標準出力を返す。"""
        process = run_cli(script, args, stdin=stdin)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        return process.stdout

    def cli_json(self, script, args, stdin=None):
        """--json の出力を、終了コードと標準エラーを確かめてから読む。"""
        return json.loads(self.cli_text(script, list(args) + ["--json"], stdin=stdin))


class TestPairsApi(PairCase):
    """API の diff() と report()。"""

    def test_status_and_meaning_risk_kinds(self):
        """3組とも status が has_candidates。meaning_risks の kind は順に swap、number、negation。"""
        for before, after, kind in PAIRS:
            with self.subTest(before=before):
                result = yomiyasu_diff.diff(before + "\n", after + "\n")
                self.assertEqual(result.get("status"), "has_candidates")
                risks = result.get("meaning_risks")
                self.assertIsInstance(risks, list, "meaning_risks がない")
                self.assertEqual([risk.get("kind") for risk in risks], [kind])

    def test_number_detail_of_pair2(self):
        """組2の number の detail は removed ["3日"]、added ["30日"]。"""
        before, after, _ = PAIRS[1]
        risks = yomiyasu_diff.diff(before + "\n", after + "\n").get("meaning_risks") or []
        numbers = [risk for risk in risks if risk.get("kind") == "number"]
        self.assertEqual(len(numbers), 1, risks)
        detail = as_json(numbers[0].get("detail"))
        self.assertEqual(detail.get("removed"), ["3日"])
        self.assertEqual(detail.get("added"), ["30日"])

    def test_full_diff_has_one_hunk_with_whole_lines(self):
        """全文差分の hunk が1つで、old_lines == [元]、new_lines == [後]。"""
        for before, after, _ in PAIRS:
            with self.subTest(before=before):
                full = yomiyasu_diff.diff(before + "\n", after + "\n").get("full_diff")
                self.assertIsInstance(full, dict, "full_diff がない")
                hunks = full.get("hunks")
                self.assertEqual(len(hunks), 1, hunks)
                self.assertEqual(as_json(hunks[0].get("old_lines")), [before])
                self.assertEqual(as_json(hunks[0].get("new_lines")), [after])

    def test_full_diff_segments_of_pair2(self):
        """組2の segments が [["=","保存期間は3"],["+","0"],["=","日です。"]]。"""
        before, after, _ = PAIRS[1]
        full = yomiyasu_diff.diff(before + "\n", after + "\n").get("full_diff")
        self.assertIsInstance(full, dict, "full_diff がない")
        self.assertEqual(as_json(full["hunks"][0].get("segments")), PAIR2_SEGMENTS)

    def test_report_states_the_check_and_the_disclaimer(self):
        """レポートは「（候補なし）」を含まず、1行目が「差分の検査を実行しました。」で、断りの文を含む。"""
        for before, after, _ in PAIRS:
            # 6.1 の API の呼び方と、再現スクリプト（reproduce.py）の呼び方の両方
            for call, result in (("api", yomiyasu_diff.diff(before + "\n", after + "\n")),
                                 ("reproduce", yomiyasu_diff.diff(before, after, "説明"))):
                with self.subTest(before=before, call=call):
                    report = yomiyasu_diff.report(result)
                    self.assertNotIn("（候補なし）", report)
                    self.assertEqual(report.split("\n")[0], DIFF_FIRST_LINE)
                    self.assertIn(DISCLAIMER, report)

    def test_report_of_pair2_shows_the_number(self):
        """組2のレポートは「3日 → 30日」を含む。"""
        before, after, _ = PAIRS[1]
        report = yomiyasu_diff.report(yomiyasu_diff.diff(before + "\n", after + "\n"))
        self.assertIn("3日 → 30日", report)


class TestPairsCli(PairCase):
    """CLI の yomiyasu_diff.py。"""

    def test_json_status_matches_api(self):
        """3組をファイルにして --json の status が API と同じ has_candidates。終了コード0。"""
        for index, (before, after, _) in enumerate(PAIRS, 1):
            with self.subTest(before=before):
                old, new = self.pair_files(index, before, after)
                process = run_cli(DIFF, [old, new, "--json"])
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertEqual(json.loads(process.stdout).get("status"), "has_candidates")

    def test_fail_on_meaning_risk_exits_1(self):
        """--fail-on=meaning-risk で終了コード1、標準エラーは空（= の形と空白区切りの形）。"""
        for index, (before, after, _) in enumerate(PAIRS, 1):
            old, new = self.pair_files(index, before, after)
            for option in (["--fail-on=meaning-risk"], ["--fail-on", "meaning-risk"]):
                with self.subTest(before=before, option=option):
                    process = run_cli(DIFF, [old, new] + option)
                    self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                    self.assertEqual(process.stderr, "")

    def test_without_fail_on_exits_0(self):
        """--fail-on を付けなければ終了コード0。出力は新しいレポート（1行目と断り）。"""
        for index, (before, after, _) in enumerate(PAIRS, 1):
            with self.subTest(before=before):
                old, new = self.pair_files(index, before, after)
                process = run_cli(DIFF, [old, new])
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertEqual(process.stdout.split("\n")[0], DIFF_FIRST_LINE)
                self.assertIn(DISCLAIMER, process.stdout)

    def test_comma_only_change_is_changed_without_candidates(self):
        """読点を1つ足した組は status が changed_without_candidates で、--fail-on=meaning-risk でも0。"""
        before, after = COMMA_PAIR
        self.assertEqual(yomiyasu_diff.diff(before + "\n", after + "\n").get("status"),
                         "changed_without_candidates")
        old, new = self.pair_files(0, before, after)
        process = run_cli(DIFF, [old, new, "--json", "--fail-on=meaning-risk"])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(json.loads(process.stdout).get("status"), "changed_without_candidates")


class TestLintOfPairSentences(PairCase):
    """6つの文（3組の前後）の lint の表示。"""

    def sentences(self):
        for before, after, _ in PAIRS:
            yield before
            yield after

    def test_first_three_lines_follow_instruction_3_1(self):
        """通常の出力の1〜3行目が指示書3.1と同じ（0件）。「スコア」「/100」「[PASS]」を含まない。"""
        for sentence in self.sentences():
            with self.subTest(sentence=sentence):
                process = run_cli(LINT, [], stdin=sentence + "\n")
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stdout.split("\n")[:3], LINT_HEADER_ZERO)
                for marker in ("スコア", "/100", "[PASS]"):
                    self.assertNotIn(marker, process.stdout)

    def test_json_has_rule_penalty_score_and_no_score(self):
        """JSON に score がなく、rule_penalty_score == 100。"""
        for sentence in self.sentences():
            with self.subTest(sentence=sentence):
                process = run_cli(LINT, ["--json"], stdin=sentence + "\n")
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assertNotIn("score", result)
                self.assertEqual(result.get("rule_penalty_score"), 100)


class TestNoMeaningJudgement(PairCase):
    """意味の判定をしないこと。"""

    def test_json_has_not_judged(self):
        """diff と lint の JSON に not_judged がある。"""
        for index, (before, after, _) in enumerate(PAIRS, 1):
            with self.subTest(before=before):
                old, new = self.pair_files(index, before, after)
                diff_json = self.cli_json(DIFF, [old, new])
                self.assertEqual(diff_json.get("not_judged"), DIFF_NOT_JUDGED)
                for sentence in (before, after):
                    lint_json = self.cli_json(LINT, [], stdin=sentence + "\n")
                    self.assertEqual(lint_json.get("not_judged"), LINT_NOT_JUDGED)
                self.assertEqual(yomiyasu_diff.diff(before + "\n", after + "\n").get("not_judged"), DIFF_NOT_JUDGED)
                self.assertEqual(yomiyasu_lint.lint_text(after + "\n").get("not_judged"), LINT_NOT_JUDGED)

    def test_json_has_no_pass_keys(self):
        """diff と lint の JSON に passed、meaning_preserved のようなキーがない（入れ子も見る）。"""
        for index, (before, after, _) in enumerate(PAIRS, 1):
            with self.subTest(before=before):
                old, new = self.pair_files(index, before, after)
                diff_json = self.cli_json(DIFF, [old, new])
                lint_json = self.cli_json(LINT, [], stdin=after + "\n")
                # 形式2の JSON であることを先に確かめる（キーがないまま通らないように）。
                self.assertEqual(diff_json.get("format_version"), 2)
                self.assertEqual(lint_json.get("format_version"), 2)
                for key in FORBIDDEN_KEYS:
                    self.assertNotIn(key, all_keys(diff_json))
                    self.assertNotIn(key, all_keys(lint_json))

    def test_outputs_do_not_claim_meaning_or_pass(self):
        """どの出力（lint と diff の通常の出力と JSON）にも「意味を保った」「合格」「問題ありません」がない。"""
        for index, (before, after, _) in enumerate(PAIRS, 1):
            with self.subTest(before=before):
                old, new = self.pair_files(index, before, after)
                diff_report = self.cli_text(DIFF, [old, new])
                outputs = [diff_report, json.dumps(self.cli_json(DIFF, [old, new]), ensure_ascii=False)]
                for sentence in (before, after):
                    outputs.append(self.cli_text(LINT, [], stdin=sentence + "\n"))
                    outputs.append(json.dumps(self.cli_json(LINT, [], stdin=sentence + "\n"), ensure_ascii=False))
                # 新しい出力であることを先に確かめる（空の出力や古い出力で通らないように）。
                self.assertEqual(diff_report.split("\n")[0], DIFF_FIRST_LINE)
                for text in outputs:
                    for phrase in FORBIDDEN_PHRASES:
                        self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
