#!/usr/bin/env python3
"""v3.2.2: diff の「原文にない保証」と「原文にない再発防止の誓い」の、同じ言い方の比べ（3.2.1）の直しの試験。

3.2.1 は、句の直前の助詞が外す一覧にないもの（のみ、だけ、なら、に限り など）だと、句の前の語が原文と推敲後の両方で空になり、
保証の相手を替えた推敲（旧プランのみ → 新プランのみ）を同じ言い方として外していた。3.2.2 からは、重ねて付いた助詞も外し、
それでも語が取れないときは、句の前の「、」か「。」からの字の並びを比べる（語の字がないときだけ空にする）。
また 3.2.1 は、漢字で書いた補助動詞などのひらがなの形へのそろえを原文の側だけで行っていたので、推敲が漢字の形を残すと
（ご負担頂くことは一切ございません）、原文と同じ句でも候補を出していた。3.2.2 からは両方の側をそろえ、「一致」などの語の
「致」はそろえない。文はすべてこのファイルで作った合成の文（公開のあとの確かめで見つかった形）。
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


def promise_kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"] if risk["kind"] == "promise"]


# 出す組（句の前の語が違う。3.2.0 も出していた）: (元, 後)
CHANGED_WORD = [
    ("旧プランのみ引き続きご利用いただけます。", "新プランのみ引き続きご利用いただけます。"),
    ("旧プランのみ、引き続きご利用いただけます。", "旧プランと新プランのみ、引き続きご利用いただけます。"),
    ("旧プランだけ、追加の費用は発生いたしません。", "新プランだけ、追加の費用は発生いたしません。"),
    ("法人会員に限り、引き続きご利用いただけます。", "個人会員に限り、引き続きご利用いただけます。"),
    ("本体のみ担保されます。", "付属品のみ担保されます。"),
    ("品質だけは担保されます。", "性能だけは担保されます。"),
    ("品質だけは担保されます。", "品質と性能だけは担保されます。"),
    ("旧プランなら引き続きご利用いただけます。", "新プランなら引き続きご利用いただけます。"),
    ("旧プランでのみ引き続きご利用いただけます。", "新プランでのみ引き続きご利用いただけます。"),
    ("法人会員を除き、引き続きご利用いただけます。", "個人会員を除き、引き続きご利用いただけます。"),
    # 一覧にない言い方（を含めて）のあとは、句の前の字の並びで比べる
    ("旧プランを含めて引き続きご利用いただけます。", "新プランを含めて引き続きご利用いただけます。"),
]

# 出さない組（同じ言い方の句を残した）: (元, 後)
KEPT = [
    # 推敲が漢字の形を残した
    ("なお、お客様にご負担頂くことは一切ございません。", "お客様にご負担頂くことは一切ございません。"),
    ("なお、お預かり致しましたデータが外部に送信されることは一切ございません。", "お預かり致しましたデータが外部に送信されることは一切ございません。"),
    ("なお、ご提供頂きましたデータが第三者に渡ることは一切ございません。", "ご提供頂きましたデータが第三者に渡ることは一切ございません。"),
    ("なお、ご記入頂く事項が増えることは一切ございません。", "ご記入頂く事項が増えることは一切ございません。"),
    ("なお、新しい画面でも引き続き出来る限り同じ操作でご利用いただけます。", "新しい画面でも引き続き出来る限り同じ操作でご利用いただけます。"),
    # 「一致」の「致」はそろえない
    ("なお、引き続き一致した設定でご利用いただけます。", "引き続き一致した設定でご利用いただけます。"),
    # 重ねて付いた助詞と一覧の助詞のあとで、句の前の語が同じ
    ("旧プランのみ、引き続きご利用いただけます。", "旧プランのみ引き続きご利用いただけます。"),
    ("法人会員に限り、追加の費用は発生いたしません。", "法人会員に限り追加の費用は発生いたしません。"),
    # 句の前に語の字がない（なお、）ときは空どうしで比べる
    ("なお、追加の費用は発生いたしません。", "追加の費用は発生いたしません。"),
]


class ChangedWordTest(unittest.TestCase):
    def test_changed_word_is_reported(self):
        for before, after in CHANGED_WORD:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertIn(("promise", "guarantee"), promise_kinds(result), result["meaning_risks"])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)


class KeptTest(unittest.TestCase):
    def test_kept_is_not_reported(self):
        for before, after in KEPT:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(promise_kinds(result), [], result["meaning_risks"])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)


class WordingTest(unittest.TestCase):
    def wording(self, text):
        return [yomiyasu_diff._addition_promise_wording(text, pos, key, name)
                for sub, name, key, pos, _ in yomiyasu_diff._addition_promise_clauses(text) if sub in ("guarantee", "prevention")]

    def test_stacked_particles(self):
        """重ねて付いた助詞（だけは、でのみ）も外して、句の前の語を取る。"""
        self.assertEqual(self.wording("品質だけは担保されます。"), [("品質", "担保されます")])
        self.assertEqual(self.wording("旧プランでのみ引き続きご利用いただけます。"), [("旧プラン", "引き続きご利用いただけます")])

    def test_fallback_to_text(self):
        """語が取れず、句の前に語の字があるときは、句の前の字の並びを使う。語の字がないときは空。"""
        self.assertEqual(self.wording("旧プランを含めて引き続きご利用いただけます。"), [("旧プランを含めて", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("旧プランでさえも引き続きご利用いただけます。"), [("旧プラン", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("なお、追加の費用は発生いたしません。"), [("", "追加の費用は発生いたしません")])

    def test_kana_map(self):
        """漢字の形をそろえた文と、元の文の位置からの対応。「一致」の「致」はそろえない。"""
        kana, mapping = yomiyasu_diff._addition_kana_map("ご負担頂く事は一致します")
        self.assertEqual(kana, "ご負担いただくことは一致します")
        self.assertEqual(len(mapping), len("ご負担頂く事は一致します") + 1)
        self.assertEqual(mapping[-1], len(kana))
        self.assertEqual(kana[mapping[4]], "く")
        self.assertEqual(yomiyasu_diff._addition_kana_map("発生致しません")[0], "発生いたしません")


if __name__ == "__main__":
    unittest.main()
