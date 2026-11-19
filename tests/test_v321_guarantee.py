#!/usr/bin/env python3
"""v3.2.1: diff の「原文にない保証」（kind promise、subkind guarantee）の試験（issue #64）。

推敲後の文の保証の句は、原文に根拠の語（_ADD_GUARANTEE_FAM。保証、約束、まま、無料 など）があれば原文にある保証として外す。
3.2.0 までは、この語に「担保」「引き続き」などがなく、原文と同じ保証の句を残して文の別の所だけを変えた推敲でも候補を出していた。
3.2.1 からは、原文の本文に同じ名前の保証の句が推敲後と同じ数以上あるときも外す。推敲後のほうが多いとき（足した句があるとき）は
今までどおり出す。名詞の「担保」だけの原文、問いや引用の中の句は、原文の保証の句に数えない。
issue #64 の組のほかの文は、このファイルで作った合成の文。
"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402


def run(before, after):
    return yomiyasu_diff.diff(before + "\n", after + "\n")


def kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"]]


def guarantee_names(text):
    return {name for sub, name, *_ in yomiyasu_diff._addition_promise_clauses(text) if sub == "guarantee"}


# 出さない組（原文の本文に、同じ名前の保証の句が推敲後と同じ数以上ある）: (元, 後, 推敲後の保証の句の名前)
KEPT = [
    # issue #64 の表の3組
    ("Delta Lake においては信頼性が担保されます。", "Delta Lake では信頼性が担保されます。", "保証"),
    ("特に、信頼性が担保されます。", "特に信頼性が担保されます。", "保証"),
    ("これで信頼性が担保されます。", "これにより信頼性が担保されます。", "保証"),
    # 「担保」のほかの形
    ("なお、品質は担保します。", "品質は担保します。", "保証"),
    ("なお、品質は担保する。", "品質は担保する。", "保証"),
    ("なお、品質は担保される。", "品質は担保される。", "保証"),
    ("信頼性が担保されます。", "信頼性 が担保されます。", "保証"),
    # 同じ名前の句への言い換え
    ("品質は担保されます。", "品質は保証されます。", "保証"),
    # 根拠の語にない、ほかの名前の句
    ("なお、新しい画面でも引き続きご利用いただけます。", "新しい画面でも引き続きご利用いただけます。", "まま使える"),
    ("なお、追加の費用は発生いたしません。", "追加の費用は発生いたしません。", "費用はかからない"),
    ("なお、追加の費用はございません。", "追加の費用はございません。", "費用はかからない"),
    ("なお、お客様にご負担いただくことは一切ございません。", "お客様にご負担いただくことは一切ございません。", "ことはない"),
    # 文の順を入れ替えた
    ("品質は担保されます。詳しくは次の章で説明します。", "詳しくは次の章で説明します。品質は担保されます。", "保証"),
    # 2文を1文にまとめた（推敲後のほうが少ない）
    ("A は担保されます。B も担保されます。", "A と B は担保されます。", "保証"),
]

# 出す組（推敲後に足した保証）: (元, 後, 理由)
ADDED = [
    ("データを保存します。", "データの信頼性が担保されます。", "issue #64 の表。原文に保証の句がない"),
    ("データの整合性の担保が課題です。", "データの整合性が担保されます。", "名詞の「担保」だけでは原文の保証の句にしない"),
    ("品質は担保されますか。", "品質は担保されます。", "問いの文の句は数えない"),
    ("「品質は担保されます」と書いてありました。", "品質は担保されます。", "かぎかっこの中の句は数えない"),
    ("品質は担保されました。", "品質は担保されます。", "済んだことの報告は保証の句にしない"),
    ("引き続き調査します。", "引き続き調査します。新しい画面でも引き続きご利用いただけます。", "別の文の「引き続き」"),
    ("A は担保されます。", "A は担保されます。B も担保されます。", "推敲後のほうが多い"),
    ("A と B は担保されます。", "A は担保されます。B も担保されます。", "1文を2文に分けて両方に書いた（3.2.0 と同じく出す）"),
]


class KeptGuaranteeTest(unittest.TestCase):
    def test_kept(self):
        for before, after, name in KEPT:
            with self.subTest(before=before, after=after):
                # 推敲後の文に保証の句があること（試験が保証の句の道を通ること）
                self.assertIn(name, guarantee_names(after))
                result = run(before, after)
                self.assertNotIn("promise", [kind for kind, _ in kinds(result)], result["meaning_risks"])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_issue_table_unchanged_rows(self):
        """issue #64 の表の残りの2組は、3.2.0 と同じ。"""
        self.assertEqual(kinds(run("品質を保証します。", "品質を保証します。今日は晴天です。")), [])
        self.assertEqual(kinds(run("品質を保証します。", "必ず品質を保証します。")), [("certainty_review", "strengthened")])

    def test_only_added_name_is_reported(self):
        """原文にある名前の句は外し、足した名前の句だけを出す。"""
        result = run("なお、追加の費用は発生いたしません。", "追加の費用は発生いたしません。引き続きご利用いただけます。")
        found = [risk for risk in result["meaning_risks"] if risk["kind"] == "promise"]
        self.assertEqual([(risk["subkind"], risk["detail"]["names"]) for risk in found], [("guarantee", ["まま使える"])])


class AddedGuaranteeTest(unittest.TestCase):
    def test_added(self):
        for before, after, reason in ADDED:
            with self.subTest(before=before, after=after, reason=reason):
                result = run(before, after)
                self.assertIn(("promise", "guarantee"), kinds(result), result["meaning_risks"])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_counts(self):
        """原文と推敲後の本文の保証の句を、同じ関数で名前ごとに数える。"""
        before = "A は担保されます。B は無料でご利用いただけます。「C も担保されます」と聞きました。"
        after = "A は担保されます。B も担保されます。"
        sides = yomiyasu_diff._Sides(before + "\n", after + "\n")
        masks = [yomiyasu_diff._Masker(sides, side) for side in (0, 1)]
        doc = yomiyasu_diff._AdditionDocument(sides, masks, [])
        self.assertEqual(dict(doc.guarantee_counts(0)), {"保証": 1, "費用はかからない": 1})
        self.assertEqual(dict(doc.guarantee_counts(1)), {"保証": 2})


if __name__ == "__main__":
    unittest.main()
