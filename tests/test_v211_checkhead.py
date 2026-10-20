#!/usr/bin/env python3
"""v2.1.1: check run の人が読む出力の頭に、候補の短い一覧と、下の節を読む案内を置く。

出力を head や sed -n '1,3p' で切って読むと、「■ 表現・書式の見直し候補」などの節が落ち、どの行のどの規則に当たったかが
分からなかった。候補があるときだけ、3行目（実行した検査の要約）のすぐあとに、検査ごとの短い一覧（「lint の候補: …」
「diff の候補: …」。並べるのは検査ごとに3件までで、残りは「ほかN件」）と、「候補の中身は下の節にあります。
出力を切らずに読んでください。」の2行を足す。候補がないときは何も足さない。2行目の状態の行と3行目は変えない。
--json、記録のファイル、verify の出力は変えない。文はすべて合成の文。
"""

from pathlib import Path
from unittest import mock
import contextlib
import importlib.util
import io
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import CHECK, CheckCase, RUN_DISCLAIMER, RUN_HEAD_NOTE, split_lines  # noqa: E402

STATUS_HEAD = "yomiyasu-check: "
# lint の meta_filler が4件当たる推敲（一覧には3件までを出し、残りを「ほか1件」にする）
FILLER = ("テストを書くことが大切です。\n\nログを残すことが大切です。\n\n設定を見直すことが大切です。\n\n"
          "手順を記録することが大切です。\n",
          "重要なのは、テストを書くことです。\n\n重要なのは、ログを残すことです。\n\n重要なのは、設定を見直すことです。\n\n"
          "重要なのは、手順を記録することです。\n")
# 数値が変わった推敲（意味が変わる恐れ。最終稿の1行目）
NUMBER = ("保存期間は3日です。\n", "保存期間は30日です。\n")
# 読点を1つ足しただけの推敲（候補なし）
PLAIN = ("会議は3時に始まります。\n", "会議は、3時に始まります。\n")
# 勢いの見直し候補だけの推敲（lint と diff の規則の候補はない）
TONE = ("最強のお土産です！\n", "最強のお土産です。\n")


def load_check():
    spec = importlib.util.spec_from_file_location("_yomiyasu_check_head", str(CHECK))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(main, argv, stdin=None):
    """main(argv) をプロセスの中で動かし、(終了コード, 標準出力, 標準エラー) を返す。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "stdout", out))
        stack.enter_context(mock.patch.object(sys, "stderr", err))
        if stdin is not None:
            stack.enter_context(mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")))
        try:
            code = main([str(item) for item in argv])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class HeadLinesTest(CheckCase):
    def assert_head(self, lines):
        """候補があるときの頭の5行: 1行目の案内、2行目の状態の行、3行目の要約、4行目の一覧、5行目の案内。"""
        self.assertTrue(lines[1].startswith(STATUS_HEAD), lines[:5])
        self.assertTrue(lines[2].startswith("実行した検査: "), lines[:5])
        self.assertEqual(lines[4], RUN_HEAD_NOTE, lines[:5])
        self.assertEqual(lines[5], RUN_DISCLAIMER)
        self.assertTrue(lines[6].startswith("記録: "), lines[:7])
        # 最後の2行は1行目と状態の行のまま
        self.assertEqual(lines[-2:], lines[:2])

    def test_lint_rules_and_line_numbers_are_in_the_first_five_lines(self):
        """head -5 で読んでも、lint の規則の名前と行番号と、下の節を読む案内が分かる。"""
        a, b, lines = self.run_pair(*FILLER)
        self.assert_head(lines)
        self.assertTrue(lines[2].startswith("実行した検査: lint（最終稿）候補4件、"), lines[2])
        self.assertTrue(lines[3].startswith("lint の候補: L1 meta_filler、L3 meta_filler、L5 meta_filler（ほか1件）。"),
                        lines[3])
        self.assertIn("diff の候補: ", lines[3])
        # 一覧に出した候補は、下の節にそのまま出ている
        self.assertIn("■ 表現・書式の見直し候補（lint、最終稿、4件）", lines)
        for number in (1, 3, 5, 7):
            self.assertTrue(any(line.startswith("L{} [WARN] meta_filler:".format(number)) for line in lines), number)

    def test_meaning_risk_line_number_is_in_the_head(self):
        a, b, lines = self.run_pair(*NUMBER)
        self.assert_head(lines)
        self.assertEqual(lines[3], "diff の候補: 後1行目 number")
        self.assertIn("- 数値が変わった（1行目）: 3日 → 30日", lines)

    def test_detector_reviews_are_listed(self):
        """lint と diff の規則の候補がなく、勢いの見直し候補だけがあるときも、節の行を一覧に出す。"""
        a, b, lines = self.run_pair(*TONE)
        self.assertIn("規則に当たる候補はありませんが", lines[0])
        self.assert_head(lines)
        self.assertEqual(lines[3], "文体などの候補: 後1行目 tone")

    def test_no_candidates_adds_nothing(self):
        a, b, lines = self.run_pair(*PLAIN)
        self.assertIn("規則に当たる候補はありません", lines[0])
        self.assertTrue(lines[1].startswith(STATUS_HEAD), lines[:5])
        self.assertEqual(lines[3], RUN_DISCLAIMER)
        self.assertTrue(lines[4].startswith("記録: "), lines[:5])
        self.assertNotIn(RUN_HEAD_NOTE, lines)
        self.assertFalse([line for line in lines if line.startswith(("lint の候補:", "diff の候補:", "文体などの候補:"))])

    def test_second_attempt_stdin_and_no_record_have_the_same_head(self):
        """2回目（直したあと）、--stdin、--no-record の出力も、同じ位置に同じ一覧を出す。"""
        a, b, first = self.run_pair(*FILLER)
        process, again = self.check_ok("run", "--source", a, "--final", b, "--no-record")
        self.assertEqual(again[3:5], first[3:5])
        b.write_bytes(FILLER[1].replace("ログを残す", "ログを保存する").encode("utf-8"))
        process, second = self.check_ok("run", "--source", a, "--final", b)
        self.assertEqual(self.status(second[1])[1]["attempt"], "2")
        self.assertTrue(second[3].startswith("lint の候補: L1 meta_filler、L3 meta_filler、L5 meta_filler（ほか1件）。"),
                        second[3])
        self.assertEqual(second[4], RUN_HEAD_NOTE)
        stdin = "<<<yomiyasu:original>>>\n" + NUMBER[0] + "<<<yomiyasu:final>>>\n" + NUMBER[1]
        process, lines = self.check_ok("run", "--stdin", stdin=stdin)
        self.assert_head(lines)
        self.assertEqual(lines[3], "diff の候補: 後1行目 number")

    def test_compose_lists_the_materials_candidates(self):
        material = self.write("m.md", "最大5回まで再試行する。\n")
        final = self.write("f.md", "再試行は最大3回です。\n")
        process, lines = self.check_ok("run", "--material", material, "--final", final)
        self.assert_head(lines)
        self.assertEqual(lines[3], "資料との照合の候補: 後1行目 資料にない数値")

    def test_json_record_and_verify_do_not_carry_the_head(self):
        """--json、記録のファイル、verify の出力には、一覧と案内を入れない（機械が読む形は変えない）。"""
        a, b, lines = self.run_pair(*FILLER)
        path, record = self.record_from(lines)
        for report in sorted(path.parent.iterdir()):
            text = report.read_text(encoding="utf-8")
            self.assertNotIn("候補の中身は下の節", text, report.name)
            self.assertNotIn("lint の候補:", text, report.name)
        verify = self.check("verify", "--final", b)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertNotIn(RUN_HEAD_NOTE, verify.stdout)
        result = self.check_json("run", "--source", a, "--final", b, "--no-record")
        dumped = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("候補の中身は下の節", dumped)
        self.assertNotIn("lint の候補:", dumped)
        self.assertEqual(result["status_line"], split_lines(self.check("run", "--source", a, "--final", b,
                                                                       "--no-record").stdout)[1])


class OnlyTheTwoLinesTest(CheckCase):
    """一覧を作る関数を空にした出力と比べ、違いが足した2行だけで、--json は1字も変わらないことを確かめる。"""

    def outputs(self, module, argv, stdin=None):
        human = call(module.main, argv, stdin)
        data = call(module.main, argv + ["--json"], stdin)
        with mock.patch.object(module, "_head_lines", return_value=[]):
            plain = call(module.main, argv, stdin)
            plain_data = call(module.main, argv + ["--json"], stdin)
        return human, data, plain, plain_data

    def test_head_is_the_only_difference(self):
        module = load_check()
        cases = (FILLER, NUMBER, PLAIN, TONE)
        for index, (before, after) in enumerate(cases):
            with self.subTest(case=index):
                a = self.write("a{}.md".format(index), before)
                b = self.write("b{}.md".format(index), after)
                argv = ["run", "--no-record", "--source", a, "--final", b]
                human, data, plain, plain_data = self.outputs(module, argv)
                self.assertEqual(data, plain_data)
                self.assertEqual((human[0], human[2]), (plain[0], plain[2]))
                lines, plain_lines = human[1].split("\n"), plain[1].split("\n")
                if before == PLAIN[0]:
                    self.assertEqual(lines, plain_lines)
                else:
                    self.assertEqual(lines[:3] + lines[5:], plain_lines)
                    self.assertEqual(lines[4], RUN_HEAD_NOTE)


if __name__ == "__main__":
    unittest.main()
