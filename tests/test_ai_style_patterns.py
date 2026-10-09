#!/usr/bin/env python3
"""v1.1.1: AI文体ウォッチの指摘（Grok Botのメモ）への lint の対応。

どれも見直し候補であり、働きを担う表現や定着した用法は書き手の判断で残す。
"""

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402


def findings(text):
    return yomiyasu_lint.lint_text(text)["findings"]


def rules(text):
    return [finding["rule"] for finding in findings(text)]


class LintCase(unittest.TestCase):
    def assert_rule(self, text, rule, severity=None, count=None):
        hits = [f for f in findings(text) if f["rule"] == rule]
        self.assertTrue(hits, f"{rule} not found in {text!r}: {rules(text)}")
        if severity:
            self.assertTrue(all(f["severity"] == severity for f in hits), hits)
        if count is not None:
            self.assertEqual(len(hits), count, hits)

    def assert_no_rule(self, text, rule):
        self.assertNotIn(rule, rules(text), text)


class TestFillerBySentence(LintCase):
    """高-2: 前置き・結びは行の頭と終わりではなく、文の頭と終わりで見る。"""

    def test_prefix_inside_a_line(self):
        self.assert_rule("前置きです。結論から言うと、完了します。\n", "meta_filler", "warn")
        self.assert_rule("設定です。ここで重要なのは、順序です。\n", "meta_filler", "warn")

    def test_closing_inside_a_line(self):
        self.assert_rule("以上です。いかがでしたか？参考になれば幸いです。\n", "meta_filler", "warn", count=2)

    def test_evaluation_in_the_middle_is_not_a_prefix(self):
        self.assert_no_rule("この順序が重要なのは、設定を先に読むからです。\n", "meta_filler")


class TestPrefixesAndClosings(LintCase):
    def test_conclusion_first_variants(self):
        for text in ("結論から言うね。それ、正解。\n", "結論から言います。\n", "結論からいえば、採用しません。\n", "結論から申し上げますと、延期します。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "meta_filler")

    def test_self_labels(self):
        for text in ("大切なのは、続けることです。\n", "大事なのは、順序です。\n", "ポイントは、設定を先に読むことです。\n",
                     "ここが一番見落とされがちなポイントです。\n", "まさにそこがポイントです。\n", "本音を言うと、迷っています。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "meta_filler")

    def test_stock_closings(self):
        for text in ("お役に立てれば幸いです。\n", "ぜひご活用ください。\n", "まずは小さく始めましょう。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "meta_filler")

    def test_polite_request_is_not_a_stock_closing(self):
        self.assert_no_rule("ご確認いただけると幸いです。\n", "meta_filler")

    def test_stock_intro_and_chat_leftovers(self):
        for text in ("ご質問ありがとうございます。\n", "それでは見ていきましょう。\n", "この仕組みを深掘りしていきます。\n",
                     "必要なら次に、運用手順まで落とし込みます。\n", "ご希望があれば、続けて例を用意します。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "meta_filler")

    def test_article_self_reference_is_info(self):
        self.assert_rule("本記事では、uvの使い方を紹介します。\n", "meta_intro", "info")


class TestRestatementAndCounts(LintCase):
    def test_restating_summary(self):
        self.assert_rule("まとめると、設定を見直すことが大切です。\n", "summary_restatement", "info")
        self.assert_rule("総じて、よい結果でした。\n", "summary_restatement", "info")

    def test_common_connectives_are_kept(self):
        self.assert_no_rule("要するに、勝っても負けても同じです。\n", "summary_restatement")
        self.assert_no_rule("結局のところ、費用は変わりません。\n", "summary_restatement")

    def test_summary_heading_in_a_short_document(self):
        text = "## 設定\n\n" + "設定を見直しました。" * 20 + "\n\n## まとめ\n\n設定を見直しました。\n"
        self.assert_rule(text, "short_summary_heading", "info")

    def test_summary_heading_in_a_long_document_is_kept(self):
        text = "## 設定\n\n" + "設定の値を一つずつ見直して記録しました。" * 120 + "\n\n## まとめ\n\n以上です。\n"
        self.assert_no_rule(text, "short_summary_heading")

    def test_count_declaration(self):
        for text in ("重要なポイントは3つです。\n", "理由は三つあります。\n", "以下の3つの観点から説明します。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "count_declaration", "info")


class TestFragmentsAndNegation(LintCase):
    def test_fragment_run(self):
        self.assert_rule("効く。重い。安い。\n", "fragment_run", "info")
        self.assert_rule("速い。ラク。早い。\n", "fragment_run", "info")

    def test_short_pairs_quotes_and_single_words_are_kept(self):
        for text in ("速い。ラク。\n", "「うん。うん。そう。」と彼は言った。\n", "はい。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "fragment_run")

    def test_three_step_negation(self):
        for text in ("車でも、家でもない。有頂天だ。\n", "これは車ではない。家でもない。有頂天だ。\n",
                     "努力ではない。才能でもない。仕組みだ。\n", "これは努力じゃない、仕組みです。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "negative_parallelism", "info")

    def test_adjective_negation_is_kept(self):
        self.assert_no_rule("それは正しくない。間違いでもない。\n", "negative_parallelism")

    def test_many_contrasts_in_one_document(self):
        text = "\n".join(f"{n}番目は速さではなく正確さです。" for n in range(1, 4)) + "\n"
        self.assert_rule(text, "negative_parallelism_density", "info", count=1)
        self.assert_no_rule("速さではなく正確さです。\n", "negative_parallelism_density")


class TestLabelsHeadingsAndWords(LintCase):
    def test_bold_label_list(self):
        text = "- **特徴**: 高速に動きます\n- **互換性**: そのまま使えます\n- **管理**: まとめて扱えます\n"
        self.assert_rule(text, "bold_label_list", "info", count=1)

    def test_short_fact_labels_are_kept(self):
        self.assert_no_rule("- 日時：10時\n- 場所：本社\n- 担当：佐藤\n", "bold_label_list")
        self.assert_no_rule("- **特徴**: 高速に動きます\n- **互換性**: そのまま使えます\n", "bold_label_list")

    def test_heading_with_toha_colon(self):
        self.assert_rule("## uvとは：仕組みと使い方\n", "heading_colon", "warn")
        self.assert_no_rule("## 障害報告書：決済の遅延\n", "heading_colon")

    def test_vague_os_and_essence(self):
        for text, word in (("これは思考のOSです。\n", "OS"), ("組織OSを作ります。\n", "OS"), ("その言語化は、かなり本質を突いています。\n", "本質を突")):
            with self.subTest(text=text):
                hits = [f for f in findings(text) if f["rule"] == "slop_vocabulary"]
                self.assertTrue(hits)
                self.assertIn(word, hits[0]["message"])

    def test_real_operating_systems_are_kept(self):
        for text in ("iOSとmacOSで確認しました。\n", "社内のOSを更新します。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "slop_vocabulary")


class TestDashInsertionAndCap(LintCase):
    def test_inserted_supplement(self):
        self.assert_rule("今日——正確には昨日——連絡しました。\n", "dash_insertion", "warn")

    def test_dash_findings_are_capped_per_document(self):
        text = "".join(f"{n}行目です——念のため。\n" for n in range(1, 7))
        dash = [r for r in rules(text) if r.startswith("dash_")]
        self.assertEqual(len(dash), 3)


class TestShortMochiron(LintCase):
    """人間の評価: 「もちろん、〇〇。」の短文は先回りの認めに見える。"""

    def test_short_concession_is_info(self):
        for text in ("もちろん、失敗もする。\n", "前置きです。もちろん、課題もあります。\n", "勿論、眠い。\n"):
            with self.subTest(text=text):
                self.assert_rule(text, "short_mochiron", "info", count=1)

    def test_other_uses_are_kept(self):
        for text in ("もちろんです。\n", "平日はもちろん、休日も出かける。\n", "「もちろん、行くよ。」と答えた。\n",
                     "使ってもいいですか？もちろん、構いません。\n", "使ってもいいですか？\nもちろん、使えます。\n",
                     "もちろん、障害が疑われる場合は、これまでどおり担当に連絡してください。\n",
                     "もちろん、すべてがうまくいったわけではない。\n"):
            with self.subTest(text=text):
                self.assert_no_rule(text, "short_mochiron")


class TestNegationAlso(LintCase):
    """人間の評価: 「AではなくBでもある」は元の言い方のまま残す。"""

    def test_negation_with_also_is_not_flagged(self):
        self.assert_no_rule("雑談は仕事の妨げではなく、相談のきっかけでもある。\n", "negative_parallelism")
        text = "\n".join(["雑談は妨げではなく、きっかけでもある。"] * 3) + "\n"
        self.assert_no_rule(text, "negative_parallelism_density")

    def test_plain_contrast_is_still_flagged(self):
        self.assert_rule("速さではなく正確さです。\n", "negative_parallelism", "info")
        self.assert_rule("妨げではなく、きっかけでもある。速さではなく正確さです。\n", "negative_parallelism")

    def test_extra_negation_message_allows_short_reply(self):
        hits = [f for f in findings("努力ではない。才能でもない。仕組みだ。\n") if f["rule"] == "negative_parallelism"]
        self.assertIn("どちらでもない", hits[0]["message"])


class TestSentenceEnds(LintCase):
    def test_repeated_deshou(self):
        self.assert_rule("これは有効でしょう。あれも有効でしょう。それも有効でしょう。\n", "sentence_end_repetition", "warn")

    def test_repeated_desune(self):
        self.assert_rule("速いですね。軽いですね。安いですね。\n", "sentence_end_repetition", "warn")


if __name__ == "__main__":
    unittest.main()
