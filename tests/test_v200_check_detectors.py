#!/usr/bin/env python3
"""v2.0.0（diff の詰め）: check の出力と記録に、硬化の検査と勢いの検査の結果を足す（追加文書 2.4、勢いの文書 3.3）。

- run の人が読む出力は、5行目（記録）のすぐあとに「硬化の検査: …」「勢いの検査: …」の2行を足す。値は「候補なし」か
  「候補{n}件」（参考だけなら「参考{n}件」）。完了報告の確認の記録の2行にそのまま写せる形。diff を実行しなかったとき
  （新規作成で資料を原文とみなさないとき、diff が止まったとき）は出さない。1〜5行目の位置は変えない。
- 記録の checks の diff の summary に、stiffness_candidate_count、stiffness_level、tone_candidate_count、tone_level を足す。
- run --json に stiffness_check と tone_check（上と同じ文字列。diff を実行しなかったときは null）を足す。
- 硬化と勢いの候補は節（■ 文体の硬化、■ 勢い）に出す。1行目の「候補あり／なし」と --fail-on には数えない。
文はすべて合成の文。
"""

from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import CheckCase, RUN_DISCLAIMER  # noqa: E402

STIFF = ("ログを見れば、時間を溶かさずに原因がわかります。\n", "ログの参照により、迅速な原因究明が可能です。\n")
TONE = ("最強のお土産です！\n", "最強のお土産です。\n")
PLAIN = ("保存期間は3日です。\n", "保存期間は30日です。\n")
# 新規作成の資料と最終稿（似ていないので、資料を原文とみなさない。diff は動かない）
MEMO = "- 定例: 木曜 10:00〜\n- 議題: 予算、人員、来期の採用、備品の購入、席替え\n- 欠席: 山田（出張）\n"
COMPOSED = "来週の定例は木曜の10時からです。\n"


class RunLinesTest(CheckCase):
    def detector_lines(self, lines):
        self.assertTrue(lines[4].startswith("記録: "), lines[:6])
        return lines[5:7]

    def test_no_candidates(self):
        a, b, lines = self.run_pair(*PLAIN)
        self.assertEqual(lines[3], RUN_DISCLAIMER)
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 候補なし", "勢いの検査: 候補なし"])
        self.assertEqual(lines[7:10], ["慎重表現の検査: 候補なし", "値の検査: 候補なし", ""])

    def test_stiffness_candidate(self):
        a, b, lines = self.run_pair(*STIFF)
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 候補1件", "勢いの検査: 候補なし"])
        self.assertIn("■ 文体の硬化（見直し候補 1件。硬い言い方に寄っていないか確かめる）", lines)

    def test_stiffness_formal_is_reference(self):
        a, b, lines = self.run_pair(*STIFF, "--doc-type", "formal")
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 参考1件", "勢いの検査: 候補なし"])

    def test_tone_candidate_and_reference(self):
        a, b, lines = self.run_pair(*TONE)
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 候補なし", "勢いの検査: 候補1件"])
        self.assertIn("■ 勢い（見直し候補 1件。書き手の勢いを落としていないか確かめる）", lines)
        a, b, lines = self.run_pair(*TONE, "--doc-type", "incident", names=("c.md", "d.md"))
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 候補なし", "勢いの検査: 参考1件"])

    def test_detectors_do_not_change_the_first_line_or_fail_on(self):
        """勢いの候補だけの推敲は、1行目が「規則に当たる候補はありません」のままで、--fail-on=meaning-risk でも0。"""
        a = self.write("a.md", TONE[0])
        b = self.write("b.md", TONE[1])
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--fail-on", "meaning-risk")
        self.assertIn("規則に当たる候補はありません", lines[0])

    def test_compose_without_diff_has_no_detector_lines(self):
        material = self.write("memo.md", MEMO)
        final = self.write("final.md", COMPOSED)
        process, lines = self.check_ok("run", "--material", material, "--final", final)
        self.assertTrue(lines[4].startswith("記録: "))
        self.assertEqual(lines[5], "")
        self.assertFalse([line for line in lines if line.startswith(("硬化の検査:", "勢いの検査:"))])


class RecordTest(CheckCase):
    def test_summary_has_detector_counts(self):
        a, b, lines = self.run_pair(*STIFF)
        path, record = self.record_from(lines)
        summary = self.check_entry(record, "diff")["summary"]
        self.assertEqual((summary["stiffness_candidate_count"], summary["stiffness_level"]), (1, "review"))
        self.assertEqual((summary["tone_candidate_count"], summary["tone_level"]), (0, "review"))
        verify = self.check("verify", "--final", b)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_changed_summary_is_invalid(self):
        """記録の件数を書き換えて digest を作り直しても、レポートの件数と照らして見つける。"""
        import importlib.util
        a, b, lines = self.run_pair(*STIFF)
        path, record = self.record_from(lines)
        self.check_entry(record, "diff")["summary"]["stiffness_candidate_count"] = 0
        spec = importlib.util.spec_from_file_location("check_module", str(Path(__file__).resolve().parent.parent
                                                                          / "scripts" / "yomiyasu_check.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        record["record_digest"] = module._record_digest(record)
        self.save_record(path, record)
        verify = self.check("verify", "--final", b)
        self.assertNotEqual(verify.returncode, 0, verify.stdout)
        self.assertIn("invalid_record", verify.stdout)

    def test_json_has_detector_results(self):
        a = self.write("a.md", STIFF[0])
        b = self.write("b.md", STIFF[1])
        result = self.check_json("run", "--source", a, "--final", b)
        self.assertEqual((result["stiffness_check"], result["tone_check"]), ("候補1件", "候補なし"))
        self.assertEqual(result["diff"]["stiffness"]["candidate_count"], 1)
        material = self.write("memo.md", MEMO)
        final = self.write("final.md", COMPOSED)
        result = self.check_json("run", "--material", material, "--final", final)
        self.assertEqual((result["stiffness_check"], result["tone_check"]), (None, None))


if __name__ == "__main__":
    unittest.main()
