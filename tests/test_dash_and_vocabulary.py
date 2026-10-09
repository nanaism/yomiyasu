#!/usr/bin/env python3
"""v1.1.1: ダッシュ類（罫線を含む）と、役割を確かめる語・英語直訳の語の検出。

X上の指摘（「A、B、C──。」構文、「閉包」「ゲート」「台帳」「版」「回帰」）への対応。
どれも見直し候補（warn）であり、定着した用法や記号の正当な使い方は検出しない。
"""

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402


def rules(text):
    return [finding["rule"] for finding in yomiyasu_lint.lint_text(text)["findings"]]


def messages(text):
    return [finding["message"] for finding in yomiyasu_lint.lint_text(text)["findings"]]


class TestDashDetection(unittest.TestCase):
    def test_inserted_dash_pair_is_flagged(self):
        self.assertEqual(rules("重要な機能――とりわけ認証周り――は慎重に。\n"), ["dash_insertion"])

    def test_em_dash_is_flagged(self):
        self.assertEqual(rules("設定を更新しました — 再起動してください。\n"), ["dash_decoration"])

    def test_listing_closed_with_box_drawing_dash(self):
        for text in ("速さ、軽さ、静けさ──。\n", "設計、実装、検証—。\n", "- 速さ、軽さ、静けさ━━\n"):
            with self.subTest(text=text):
                self.assertEqual(rules(text), ["dash_list_ending"])
                self.assertIn("列挙", messages(text)[0])

    def test_one_finding_per_line(self):
        self.assertEqual(rules("A――B――C――D。\n"), ["dash_insertion"])

    def test_dash_outside_quote_and_link_is_still_flagged(self):
        self.assertEqual(rules("記号「—」の後で、設定を変えました——念のため。\n"), ["dash_decoration"])
        self.assertEqual(rules("[記事](https://example.com/a)を読みました——とても参考になります。\n"), ["dash_decoration"])

    def test_heading_dash_is_flagged(self):
        self.assertEqual(rules("## 設計 — 実装\n"), ["dash_decoration"])

    def test_non_decorative_marks_are_not_flagged(self):
        for text in (
            "サーバーの設定をコピーしました。\n",          # 長音記号（ー）
            "対象は1–3章です。\n",                         # en dash の範囲
            "10時〜12時に作業します。\n",                   # 波ダッシュ
            "前半と後半を分けます。\n\n---\n\n後半です。\n",  # 水平線
        ):
            with self.subTest(text=text):
                self.assertNotIn("dash_decoration", rules(text))
                self.assertNotIn("dash_list_ending", rules(text))

    def test_code_tables_quotes_and_diagrams_are_not_flagged(self):
        for text in (
            "```text\nsrc/\n├── main.py\n└── util.py\n──────\n```\n",  # コードブロック内の罫線
            "値は `a—b` の形式で渡します。\n",                         # インラインコード
            "| 項目 | 値 |\n|---|---|\n| 備考 | — |\n",                # 表のセル（該当なしの記号）
            "> 彼は言った――もう遅い、と。\n",                          # 引用
            "src/\n├── main.py\n└── util.py\n",                        # コードブロック外の木構造
            "──────────\n",                                            # 区切り線だけの行
            "「もう遅い――」と彼は言った。\n",                          # 会話文の中
            "記号「—」と「──」は使いません。\n",                       # 記号への言及
            "- [記事の題名](https://example.com/a) — 著者氏\n",         # リンクの後ろの出典表記
            "- [生成AIの平易化―やさしい日本語―](https://example.com/b), 論文誌\n",  # 題名の中の副題
        ):
            with self.subTest(text=text):
                self.assertNotIn("dash_decoration", rules(text))
                self.assertNotIn("dash_list_ending", rules(text))


class TestVocabulary(unittest.TestCase):
    def assert_flagged(self, text, rule, word):
        findings = [f for f in yomiyasu_lint.lint_text(text)["findings"] if f["rule"] == rule]
        self.assertTrue(findings, text)
        self.assertIn(word, findings[0]["message"])
        self.assertEqual(findings[0]["severity"], "warn")

    def assert_not_flagged(self, text, rule):
        self.assertNotIn(rule, rules(text), text)

    def test_role_words_are_review_candidates(self):
        self.assert_flagged("依存の閉包を取ってから実行します。\n", "slop_vocabulary", "閉包")
        self.assert_flagged("レビューゲートを通してから公開します。\n", "slop_vocabulary", "ゲート")
        self.assert_flagged("変更は作業台帳に記録します。\n", "slop_vocabulary", "台帳")

    def test_gateway_is_not_a_gate(self):
        self.assert_not_flagged("APIゲートウェイの設定を変えました。\n", "slop_vocabulary")

    def test_defined_closure_and_ledgers_are_kept(self):
        for text in ("依存グラフの推移閉包を求めます。\n", "固定資産台帳を更新しました。\n", "会計の台帳は経理が管理しています。\n"):
            with self.subTest(text=text):
                self.assert_not_flagged(text, "slop_vocabulary")

    def test_version_as_ban(self):
        for text in ("この版では読み込みを速くしました。\n", "新しい版で設定の形式が変わりました。\n", "版を上げる前に確認します。\n"):
            with self.subTest(text=text):
                self.assert_flagged(text, "translated_term", "版")

    def test_established_ban_is_kept(self):
        for text in ("日本語版を公開しました。\n", "第2版で章を追加しました。\n", "無料版と有料版があります。\n", "改訂版を配布します。\n"):
            with self.subTest(text=text):
                self.assert_not_flagged(text, "translated_term")

    def test_regression_as_kaiki(self):
        for text in ("前回のリリースで回帰が出ました。\n", "この変更が回帰を起こしました。\n", "回帰が発生したので戻しました。\n"):
            with self.subTest(text=text):
                self.assert_flagged(text, "translated_term", "回帰")

    def test_established_kaiki_is_kept(self):
        for text in ("回帰テストを追加しました。\n", "線形回帰で予測します。\n", "回帰分析の結果です。\n", "原点に回帰する設計です。\n"):
            with self.subTest(text=text):
                self.assert_not_flagged(text, "translated_term")


if __name__ == "__main__":
    unittest.main()
