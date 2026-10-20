#!/usr/bin/env python3
"""v2.1.1: diff の選ぶ範囲（どれか一つ ↔ 全部）と、関連から因果への言い方の変化の試験。

「AまたはBのどちらか」を「AとBの両方」に書き換えて文の真偽が逆になっても、意味が変わる恐れが0件になっていた不具合と、
「関連がある」「相関がある」を「因果関係がある」「原因である」「引き起こす」に強めても、語の差分にしか出なかった不具合を防ぐ。
どちらも --fail-on=meaning-risk に数える。同じ側の中の言い換え（または → か、どちらか → いずれか、両方 → どちらも）、
原文にもともと因果の言い方がある文、「関連」→「関係」の言い換え、関連の言い方のない原文では出さない。
例の文は、このファイルで作った合成の文。
"""

from pathlib import Path
from unittest import mock
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


NEW_KINDS = ("choice", "causality")


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


def kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"]]


def new_kinds(result):
    return [k for k in kinds(result) if k[0] in NEW_KINDS]


# 検出すべき例: (元, 後, (kind, subkind))
SHOULD_DETECT = [
    # 依頼の組（どれか一つ → 全部）と、その逆
    ("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。", ("choice", "one_to_all")),
    ("AとBの両方を選ぶ必要がある。", "AまたはBのどちらかを選ぶ必要がある。", ("choice", "all_to_one")),
    ("AとBの両方を選ぶ。", "AかBを選ぶ。", ("choice", "all_to_one")),
    ("申請書か委任状のどちらかを提出する。", "申請書と委任状をどちらも提出する。", ("choice", "one_to_all")),
    ("いずれかの条件を満たせば通知する。", "すべての条件を満たせば通知する。", ("choice", "one_to_all")),
    ("すべての条件を満たせば通知する。", "いずれかの条件を満たせば通知する。", ("choice", "all_to_one")),
    ("メールもしくは電話で連絡する。", "メールと電話の双方で連絡する。", ("choice", "one_to_all")),
    ("どちらかの鍵が使えない。", "どちらの鍵も使えない。", ("choice", "one_to_all")),
    ("AとBはともに必須だ。", "AかBが必須だ。", ("choice", "all_to_one")),
    # 依頼の3組（関連・相関 → 因果）
    ("この施策と売上の増加には関連がある。", "この施策と売上の増加には因果関係がある。", ("causality", "relation_to_cause")),
    ("この施策と売上の増加には関連がある。", "この施策が売上の増加の原因である。", ("causality", "relation_to_cause")),
    ("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。", ("causality", "relation_to_cause")),
    ("気温と来店数は関係している。", "気温の変化によって来店数の増減が生じる。", ("causality", "relation_to_cause")),
    ("睡眠時間と集中力は結びついている。", "睡眠不足のせいで集中力が落ちる。", ("causality", "relation_to_cause")),
]

# 検出してはいけない例（種類なしでも formal でも、選ぶ範囲と因果の候補を出さない）
SHOULD_NOT_DETECT = [
    # 同じ側の中の言い換え
    ("AまたはBを選ぶ。", "AかBを選ぶ。"),
    ("どちらかを選ぶ。", "いずれかを選ぶ。"),
    ("AまたはBのどちらかを選ぶ。", "AかBのいずれか一方を選ぶ。"),
    ("両方を選ぶ。", "どちらも選ぶ。"),
    ("いずれの項目も確認する。", "すべての項目を確認する。"),
    ("AとBの両方を選ぶ。", "AもBも選ぶ。"),
    # 両方の言い方を並べた書き換え
    ("AまたはBを選ぶ。", "AかBのどちらか、または両方を選ぶ。"),
    # 問いの「か」、何か、数のあとの「か月」、「どちらかといえば」は、どれか一つの言い方にしない
    ("どの設定が必要か確認する。", "すべての設定を確認する。"),
    ("何か問題があれば連絡する。", "すべての問題を連絡する。"),
    ("3か月ごとに見直す。", "すべての項目を3か月ごとに見直す。"),
    ("どちらかといえば速い。", "どれも速い。"),
    ("どの値が正しいか判断が必要だ。", "すべての値を確かめる必要がある。"),
    # 原文にもともと因果の言い方がある
    ("この施策と売上の増加には関連があり、増加の原因と考えられている。", "この施策が売上の増加の原因と考えられている。"),
    ("設定の誤りと障害には関連があり、障害は設定の誤りが原因だった。", "障害は設定の誤りが原因だった。"),
    ("喫煙と肺がんには因果関係がある。", "喫煙は肺がんの原因になる。"),
    # 「関連」→「関係」の言い換え
    ("この施策と売上の増加には関連がある。", "この施策と売上の増加には関係がある。"),
    ("気温と来店数には相関がある。", "気温と来店数には相関関係がある。"),
    # 原文に関連の言い方がない
    ("この施策の後に売上が増えた。", "この施策が売上の増加の原因である。"),
    ("関連する設定を変更すると、表示が崩れた。", "関連する設定の変更が、表示の崩れの原因だった。"),
    # 因果を弱めた向きは出さない
    ("喫煙が肺がんを引き起こす。", "喫煙と肺がんには相関がある。"),
]


class DetectTest(unittest.TestCase):
    def test_should_detect(self):
        for before, after, expected in SHOULD_DETECT:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    result = run(before, after, doc_type)
                    self.assertIn(expected, new_kinds(result), kinds(result))
                    self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_should_not_detect(self):
        for before, after in SHOULD_NOT_DETECT:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    self.assertEqual(new_kinds(run(before, after, doc_type)), [])

    def test_choice_ka_hits(self):
        """「AかB」の「か」は語と語の間の選ぶ「か」だけを拾い、問い・回数・期間の「か」は拾わない。"""
        def hits(text):
            return [(kind, hit) for _, kind, hit in yomiyasu_diff._logic_positions(text) if kind == "どれか一つ"]
        for text in ("支払いはカードかコンビニで選ぶ。", "木曜か金曜に確認する。", "管理画面かCLIから再送する。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [("どれか一つ", "か")])
        for text in ("何度か夜中に呼び出された。", "数回か試した。", "3か月ごとに見直す。", "必要か確認する。", "有効か否かを返す。",
                     "何か問題があれば連絡する。", "どちらかといえば速い。", "どの値が正しいか判断が必要だ。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [])

    def test_request_pair_counts_as_meaning_risk(self):
        """依頼の組は、意味が変わる恐れ1件以上で、そのうち選ぶ範囲の1件を --fail-on に数える。"""
        result = run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。")
        self.assertEqual(new_kinds(result), [("choice", "one_to_all")])
        self.assertGreaterEqual(result["meaning_risk_count"], 1)
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        self.assertEqual(result["status"], "has_candidates")

    def test_detail(self):
        risk = [r for r in run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。")["meaning_risks"]
                if r["kind"] == "choice"][0]
        self.assertEqual(risk["detail"], {"from": "どれか一つ", "to": "全部", "old_hits": ["または", "どちらか"],
                                          "new_hits": ["両方"]})
        self.assertEqual((risk["old_line"], risk["new_line"]), (1, 1))
        risk = [r for r in run("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。")["meaning_risks"]
                if r["kind"] == "causality"][0]
        self.assertEqual(risk["detail"], {"from": "関連", "to": "因果", "old_hits": ["相関"], "new_hits": ["引き起こす"]})
        self.assertEqual(risk["old"], "喫煙と肺がんには相関がある。")
        self.assertEqual(risk["new"], "喫煙が肺がんを引き起こす。")

    def test_split_sentence_compares_the_corresponding_range(self):
        """文を分けても、元の文に当たる範囲で比べる。別の文の「すべて」は、どれか一つの言い方の消えと組にしない。"""
        result = run("申請書か委任状のどちらかを提出し、窓口で確認を受ける。",
                     "申請書と委任状の両方を提出する。窓口で確認を受ける。")
        self.assertEqual(new_kinds(result), [("choice", "one_to_all")])
        result = run("AまたはBを選ぶ。すべての設定を保存する。", "AやBを選ぶ。すべての設定を保存する。")
        self.assertEqual(new_kinds(result), [])

    def test_human_lines(self):
        report = yomiyasu_diff.report(run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。"))
        self.assertIn("- 選ぶ範囲が「どれか一つ」から「全部」に変わった（1行目）: どれか一つ（または、どちらか） → 全部（両方）。",
                      report)
        report = yomiyasu_diff.report(run("AとBの両方を選ぶ。", "AかBを選ぶ。"))
        self.assertIn("- 選ぶ範囲が「全部」から「どれか一つ」に変わった（1行目）: 全部（両方） → どれか一つ（か）。", report)
        report = yomiyasu_diff.report(run("この施策と売上の増加には関連がある。", "この施策が売上の増加の原因である。"))
        self.assertIn("- 関連の言い方が因果の言い方に変わった（1行目）: 関連（関連がある） → 因果（原因）。", report)
        result = run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。")
        risks = result["meaning_risks"]
        self.assertIn("・選ぶ範囲", yomiyasu_diff._fail_on_line(len(risks) + 1, yomiyasu_diff.fail_on_count(risks), risks))
        result = run("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。")
        risks = result["meaning_risks"]
        self.assertIn("・因果", yomiyasu_diff._fail_on_line(len(risks) + 1, yomiyasu_diff.fail_on_count(risks), risks))


class CliTest(unittest.TestCase):
    def test_cli_exit_codes(self):
        rows = [("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。", 1),
                ("この施策と売上の増加には関連がある。", "この施策と売上の増加には因果関係がある。", 1),
                ("この施策と売上の増加には関連がある。", "この施策が売上の増加の原因である。", 1),
                ("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。", 1),
                ("AまたはBを選ぶ。", "AかBを選ぶ。", 0),
                ("この施策と売上の増加には関連がある。", "この施策と売上の増加には関係がある。", 0)]
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old.md", Path(folder) / "new.md"
            for before, after, code in rows:
                old.write_text(before + "\n", encoding="utf-8")
                new.write_text(after + "\n", encoding="utf-8")
                for flags in ([], ["--doc-type", "formal"]):
                    with self.subTest(before=before, after=after, flags=flags):
                        process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/yomiyasu_diff.py"), "--fail-on",
                                                  "meaning-risk"] + flags + [str(old), str(new)], capture_output=True, text=True,
                                                 encoding="utf-8")
                        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                        if code:
                            self.assertIn("終了コード1: --fail-on=meaning-risk の条件に当たりました", process.stdout)


class ContractsTest(unittest.TestCase):
    def test_kinds_and_fail_on(self):
        """新しい kind は数える側に足し、既存の kind の並びはそのまま残す。"""
        self.assertEqual(yomiyasu_diff.FAIL_ON_KINDS[:9], ("number", "negation", "swap", "sentence_type", "citation",
                                                          "certainty", "state", "promise", "modality"))
        self.assertIn("choice", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertIn("causality", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertLess(yomiyasu_diff._RISK_ORDER["modality_review"], yomiyasu_diff._RISK_ORDER["choice"])
        self.assertIn("causality", yomiyasu_diff._RISK_ORDER)

    def test_public_function_matches_diff(self):
        """type_changes を渡した meaning_risks() は、選ぶ範囲と因果の候補を含めて diff() と同じ。None なら足さず、範囲も作らない。"""
        documents = (("AまたはBのどちらかを選ぶ。外部APIは遅れるかもしれない。\n", "AとBの両方を選ぶ。外部APIは遅れる。\n"),
                     ("喫煙と肺がんには相関がある。\n", "喫煙が肺がんを引き起こす。\n"),
                     ("この値は変更してよい。AまたはBを選ぶ。\n", "この値は変更できる。AとBの両方を選ぶ。\n"))
        for before, after in documents:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, doc_type=doc_type):
                    result = yomiyasu_diff.diff(before, after, doc_type=doc_type)
                    self.assertTrue(new_kinds(result))
                    self.assertIsNone(yomiyasu_diff._LAST_TYPE_RANGES[0])
                    found = yomiyasu_diff.meaning_risks(before, after, type_changes=result["type_changes"], doc_type=doc_type)
                    self.assertEqual(found, result["meaning_risks"])
                    self.assertIsNone(yomiyasu_diff._LAST_TYPE_RANGES[0])
        with mock.patch.object(yomiyasu_diff, "_type_ranges", side_effect=AssertionError("範囲を作った")):
            found = yomiyasu_diff.meaning_risks("AまたはBを選ぶ。\n", "AとBの両方を選ぶ。\n")
        self.assertFalse([r for r in found if r["kind"] in NEW_KINDS])

    def test_ranges_are_made_once_in_diff(self):
        """diff() は、文の種類の印の範囲を、許可・能力の比べでも選ぶ範囲・因果の比べでも作り直さない。"""
        documents = (("AまたはBを選ぶ。外部APIは遅れるかもしれない。\n", "AとBの両方を選ぶ。外部APIは遅れる。\n"),
                     ("この値は変更してよい。AまたはBを選ぶ。\n", "この値は変更できる。AとBの両方を選ぶ。\n"),
                     ("AまたはBを選ぶ。\n", "AとBの両方を選ぶ。\n"))
        for before, after in documents:
            with self.subTest(before=before):
                with mock.patch.object(yomiyasu_diff, "_type_ranges", wraps=yomiyasu_diff._type_ranges) as ranges:
                    result = yomiyasu_diff.diff(before, after)
                self.assertEqual(ranges.call_count, 1)
                self.assertIn(("choice", "one_to_all"), kinds(result))
        # 選ぶ範囲と因果の印がどちらの側にもそろわない文章では、範囲を作らない
        with mock.patch.object(yomiyasu_diff, "_type_ranges", wraps=yomiyasu_diff._type_ranges) as ranges:
            yomiyasu_diff.diff("設定を保存する。\n", "設定を保存した。\n")
        self.assertEqual(ranges.call_count, 0)

    def test_help_names_the_new_counted_kinds(self):
        """--fail-on の説明と終了コードの表に、選ぶ範囲と因果を数えることを書く。"""
        helps = {action.dest: action.help for action in yomiyasu_diff._build_parser()._actions}
        self.assertIn("選ぶ範囲が入れ替わった書き換え", helps["fail_on"])
        self.assertIn("因果の言い方（因果、原因、引き起こす など）を足した書き換え", helps["fail_on"])
        self.assertIn("許可の言い方・選ぶ範囲・因果の恐れが1件以上", yomiyasu_diff._EXIT_CODES)

    def test_twin_scripts_are_identical(self):
        self.assertEqual((ROOT / "scripts" / "yomiyasu_diff.py").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_diff.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
