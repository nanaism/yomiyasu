"""Distinguish decorative dashes from quotations, credits and routes."""
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from yomiyasu_lint import lint_text


def dash_rules(text):
    return [f["rule"] for f in lint_text(text)["findings"] if f["rule"].startswith("dash_")]


class TestDashRegressions(unittest.TestCase):
    def test_common_nouns_are_not_routes(self):
        for text in ("AIの仕事—人間の役割は変わる。", "大事なのは集中—時間の使い方が変わる。",
                     "この経験—目線が変わった。", "判断—作業時間を短くした。"):
            with self.subTest(text=text):
                self.assertEqual(dash_rules(text), ["dash_decoration"])

    def test_real_routes_keep_the_separator(self):
        for text in ("東京―大阪間の運賃です。", "東京―大阪線を利用します。", "東京―大阪便に乗ります。",
                     "津―堺間の距離です。", "東京―大阪区間を調べます。",
                     "東京―大阪線運休のお知らせ", "東京―大阪間直通列車に乗ります。"):
            with self.subTest(text=text):
                self.assertEqual(dash_rules(text), [])

    def test_short_decorative_lines_are_not_credits(self):
        for text in ("—— ここからが本題", "——そう、これが答えだ", "— 速度が2倍になった"):
            with self.subTest(text=text):
                self.assertEqual(dash_rules(text), ["dash_decoration"])

    def test_credits_use_source_markers_not_a_length_cutoff(self):
        for text in ("―― 夏目漱石『こころ』", "―― ピーター・F・ドラッカー『マネジメント』（上田惇生訳、ダイヤモンド社、2001年）",
                     "> Stay hungry, stay foolish.\n\n― Steve Jobs, Stanford Commencement Address, 2005",
                     "> 引用文。\n\n— Albert Einstein, letter to Max Born, 1926",
                     "— Martin Fowler, *Refactoring*, 2nd ed., 2018", "―― 出典：調査報告書（2025年）"):
            with self.subTest(text=text):
                self.assertEqual(dash_rules(text), [])

    def test_nested_quotations_are_masked_but_outside_dash_is_not(self):
        for text in ("「その——「普通」っていうのが、私には分からない」", "『彼は「待って——」と言った』"):
            with self.subTest(text=text):
                self.assertEqual(dash_rules(text), [])
        self.assertEqual(dash_rules("「その——「普通」っていうのが分からない」——そう言った。"), ["dash_decoration"])
        self.assertEqual(dash_rules("『作品名』を読みました——参考になりました。"), ["dash_decoration"])

    def test_book_reference_does_not_hide_following_prose(self):
        self.assertEqual(dash_rules("―― 夏目漱石『こころ』を読みました——参考になりました。"), ["dash_insertion"])
        self.assertEqual(dash_rules("— Martin Fowler, Refactoring — 読みました。"), ["dash_decoration"])

    def test_unbalanced_different_quote_mark_does_not_break_outer_quote(self):
        self.assertEqual(dash_rules("「半角の[を入力して——」と説明した。"), [])
        self.assertEqual(dash_rules("『開きかっこ「を入力——』と説明した。"), [])

    def test_list_spacing_preserves_the_specific_finding(self):
        for text in ("設計、実装、検証 ──。", "設計、 実装、 検証　──。", "- 設計、実装、検証 ──"):
            with self.subTest(text=text):
                self.assertEqual(dash_rules(text), ["dash_list_ending"])
        self.assertEqual(dash_rules("彼は、振り返った——"), ["dash_decoration"])


class TestDashScanCost(unittest.TestCase):
    def test_long_noun_and_nested_quotes_finish(self):
        for text in ("漢" * 100_000 + "—", "漢" * 100_000 + "—大阪間", "作業—" + "人間" * 50_000,
                     "「" * 20_000 + "待って——" + "」" * 20_000):
            with self.subTest(length=len(text)):
                started = time.perf_counter()
                lint_text(text)
                self.assertLess(time.perf_counter() - started, 3.0)
