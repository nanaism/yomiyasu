#!/usr/bin/env python3
"""v1.1.1の公開前レビューで見つかった誤検知・取りこぼし・処理時間の回帰テスト。"""

from pathlib import Path
import sys
import time
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402


def findings(text):
    return yomiyasu_lint.lint_text(text)["findings"]


def rules(text):
    return [finding["rule"] for finding in findings(text)]


class LintCase(unittest.TestCase):
    def assert_rule(self, text, rule):
        self.assertIn(rule, rules(text), text)

    def assert_no_rule(self, text, rule):
        self.assertNotIn(rule, rules(text), text)


class TestVocabularyFalsePositives(LintCase):
    def test_gate_loanwords_are_kept(self):
        for text in ("画面間をナビゲートする処理を追加した。\n", "文字列はサロゲートペアを含む。\n", "C#のデリゲートを使う。\n",
                     "高輪ゲートウエイ駅で降りた。\n", "搭乗ゲートは5番に変わりました。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "slop_vocabulary")

    def test_review_gates_are_still_flagged(self):
        for text in ("レビューゲートを通してから公開します。\n", "リリースゲートを設けた。\n", "承認ゲートを通す。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "slop_vocabulary")

    def test_defined_closures_and_ledgers_are_kept(self):
        for text in ("閉包演算の性質を確かめる。\n", "対称閉包と凸閉包を求める。\n", "会計台帳を更新しました。\n",
                     "行政の台帳を照合します。\n", "土地台帳と家屋台帳を照合した。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "slop_vocabulary")

    def test_oss_is_not_a_vague_os(self):
        self.assert_no_rule("チームのOSS活動を紹介します。\n", "slop_vocabulary")
        self.assert_rule("これは組織のOSです。\n", "slop_vocabulary")

    def test_compound_ban_and_everyday_regression_are_kept(self):
        for text in ("日本語版を更新しました。\n", "PDF版を更新しました。\n", "第2版を更新しました。\n",
                     "ファッションでは原点回帰が起きている。\n", "平均への回帰が起こるため、極端な値は戻りやすい。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "translated_term")
        for text in ("次に版を上げます。\n", "版を上げる前に確認します。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "translated_term")


class TestFillerFalsePositives(LintCase):
    def test_business_offers_and_plans_are_kept(self):
        for text in ("よろしければ、この後の打ち合わせで詳しくご説明します。\n", "必要なら、次に経理へ回してください。\n",
                     "まずは小さく始めて、3か月後に全社へ広げる計画です。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "meta_filler")

    def test_chat_leftovers_note_the_exceptions(self):
        hits = [f for f in findings("ご質問ありがとうございます。\n") if f["rule"] == "meta_filler"]
        self.assertIn("返信そのもの", hits[0]["message"])


class TestNegationFalsePositives(LintCase):
    def test_idioms_and_conjunctions_are_kept(self):
        for text in ("いいじゃない、まだ時間はあるし。\n", "それでも、誰のせいでもない。\n", "疲れているわけじゃない。何でもない。\n",
                     "簡単ではない。不可能でもない。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "negative_parallelism")

    def test_everywhere_is_not_also(self):
        self.assert_rule("これは特別な事例ではなく、どこにでもある失敗だ。\n", "negative_parallelism")
        self.assert_rule("問題は人ではなく、誰にでもある思い込みだ。\n", "negative_parallelism")


class TestBoldLabelForms(LintCase):
    def test_colon_inside_bold_and_numbered_lists(self):
        for text in ("- **特徴：** 高速に動きます\n- **互換性：** そのまま使えます\n- **管理：** まとめて扱えます\n",
                     "1. **特徴**: 高速に動きます\n2. **互換性**: そのまま使えます\n3. **管理**: まとめて扱えます\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "bold_label_list")


class TestMochironAnswers(LintCase):
    def test_answers_after_quotes_blank_lines_and_headings(self):
        for text in ("「手伝ってくれる？」\nもちろん、手伝う。\n", "使ってもいいですか？\n\nもちろん、使えます。\n",
                     "### 個人でも使えますか？\n\nもちろん、使えます。\n", "**Q. 無料プランでも使えますか？**\n\nもちろん、使えます。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "short_mochiron")

    def test_concession_after_a_statement_is_still_flagged(self):
        self.assert_rule("毎朝、歩いて帰っている。\n\nもちろん、迷う日もある。\n", "short_mochiron")


class TestFragmentQuotes(LintCase):
    def test_quoted_values_are_not_fragments(self):
        for text in ("1位は「田中」。2位は「鈴木」。3位は「佐藤」。\n", "晴れは「○」。雨は「×」。曇りは「△」。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "fragment_run")


class TestDashForms(LintCase):
    def test_list_ending_is_judged_per_sentence(self):
        self.assertEqual(rules("速さ、軽さ、静けさ──。それが魅力だ。\n"), ["dash_list_ending"])
        self.assertNotIn("dash_list_ending", rules("彼は、振り返った——\n"))

    def test_attribution_ranges_and_ornamented_dividers_are_kept(self):
        for text in ("―― 夏目漱石『こころ』\n", "東京―大阪間の運賃です。\n", "――◆――\n", "◇―――◇\n"):
            with self.subTest(text=text):
                self.assertFalse([r for r in rules(text) if r.startswith("dash_")], text)


class TestLongLines(unittest.TestCase):
    def test_long_lines_finish_quickly(self):
        cases = ("、".join(f"項目{i}" for i in range(4000)) + " — 以上\n",
                 "あ、" * 50000 + "—あ\n",
                 "Note — " + "The parser splits the input and handles each part. " * 2000 + "\n",
                 "「あ" * 50000 + "\n",
                 "本文です" + " " * 50000 + "もちろん、眠い。\n")
        for text in cases:
            with self.subTest(length=len(text)):
                started = time.perf_counter()
                yomiyasu_lint.lint_text(text)
                self.assertLess(time.perf_counter() - started, 3.0)


if __name__ == "__main__":
    unittest.main()
