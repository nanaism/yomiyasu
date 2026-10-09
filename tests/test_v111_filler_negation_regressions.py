#!/usr/bin/env python3
"""v1.1.1再レビュー: 定型の申し出・結びと否定構文の取りこぼし。"""

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402


def rule_findings(text, rule):
    return [item for item in yomiyasu_lint.lint_text(text)["findings"] if item["rule"] == rule]


class TestChatOfferEndings(unittest.TestCase):
    def test_questions_particles_and_exclamations_are_review_candidates(self):
        for text in (
            "必要なら次に、テスト手順も作りますか？",
            "必要なら次に、具体的なコードも書けますよ。",
            "必要なら次に、設定例も用意できますね。",
            "ご希望があれば、続けて例を用意します！",
            "よろしければ、続けて実装例も示しましょうか？",
        ):
            with self.subTest(text=text):
                hits = rule_findings(text, "meta_filler")
                self.assertEqual(len(hits), 1, hits)
                self.assertEqual(hits[0]["severity"], "warn")
                self.assertIn("実際に申し出ている案内", hits[0]["message"])

    def test_parenthetical_supplement_keeps_the_offer_visible(self):
        text = "必要なら次に、READMEの英語版も用意できます（数分で終わります）。"
        self.assertEqual(len(rule_findings(text, "meta_filler")), 1)

    def test_real_procedural_requests_and_specific_business_offer_are_kept(self):
        for text in (
            "必要なら、次に経理へ回してください。",
            "必要なら次に、担当者へ確認してください。",
            "ご希望があれば、続けて申請書を提出してください。",
            "よろしければ、この後の打ち合わせで詳しくご説明します。",
        ):
            with self.subTest(text=text):
                self.assertEqual(rule_findings(text, "meta_filler"), [])


class TestSmallStartClosings(unittest.TestCase):
    def test_invitation_and_recommendation_variants_are_review_candidates(self):
        for text in (
            "まずは小さく始めてみてはいかがでしょうか。",
            "まずは小さく始めてみませんか？",
            "まずは小さく始めることが大切です。",
            "まずは小さく始めるのがおすすめです。",
            "まずは小さくはじめてみませんか？",
            "まずは小さく始めましょう！",
            "まずは小さく始めてみてください。",
        ):
            with self.subTest(text=text):
                hits = rule_findings(text, "meta_filler")
                self.assertEqual(len(hits), 1, hits)
                self.assertIn("実際に勧めている内容", hits[0]["message"])

    def test_plans_and_reports_are_kept(self):
        for text in (
            "まずは小さく始めて、3か月後に全社へ広げる計画です。",
            "まずは小さく始める計画です。",
            "まずは小さく始めました。",
            "まずは小さく始めて、結果を確かめてから人数を増やします。",
        ):
            with self.subTest(text=text):
                self.assertEqual(rule_findings(text, "meta_filler"), [])


class TestRepeatedNegationConclusion(unittest.TestCase):
    def test_conclusion_does_not_require_present_copula(self):
        for conclusion in (
            "仕組みだ。",
            "仕組みでした。",
            "仕組みだった。",
            "習慣にある。",
            "プロセスにあります。",
            "この街の道を、自分の足で覚えたかった。",
            "この街の道を、自分の足で覚えたいと思っている。",
            "焼きたての音が聞きたいだけ。",
        ):
            with self.subTest(conclusion=conclusion):
                text = "これは努力ではない。才能でもない。" + conclusion
                hits = rule_findings(text, "negative_parallelism")
                self.assertEqual(len(hits), 1, hits)
                self.assertEqual(hits[0]["severity"], "info")
                self.assertIn("どちらでもない", hits[0]["message"])

    def test_compact_negation_pair_allows_a_past_conclusion(self):
        hits = rule_findings("車でも、家でもない。有頂天だった。", "negative_parallelism")
        self.assertEqual(len(hits), 1, hits)

    def test_regular_verb_and_adjective_conclusions_are_review_candidates(self):
        for conclusion in ("毎日続ける。", "記録をつけた。", "毎日が楽しい。"):
            with self.subTest(conclusion=conclusion):
                text = "努力ではない。才能でもない。" + conclusion
                self.assertEqual(len(rule_findings(text, "negative_parallelism")), 1)

    def test_another_negation_or_question_is_not_an_affirmative_conclusion(self):
        for conclusion in ("続けないのだ。", "続けませんでした。", "続けますか。"):
            with self.subTest(conclusion=conclusion):
                text = "努力ではない。才能でもない。" + conclusion
                self.assertEqual(rule_findings(text, "negative_parallelism"), [])

    def test_explanatory_and_polite_negative_endings_keep_affirmative_controls(self):
        for conclusion, expected_count in (
            ("続けないでしょう。", 0),
            ("続けないだろう。", 0),
            ("続けないのである。", 0),
            ("続けませんでした。", 0),
            ("毎日続ける。", 1),
            ("記録をつけた。", 1),
            ("毎日が楽しい。", 1),
        ):
            with self.subTest(conclusion=conclusion):
                text = "努力ではない。才能でもない。" + conclusion
                self.assertEqual(len(rule_findings(text, "negative_parallelism")), expected_count)

    def test_soft_line_breaks_preserve_the_construction_and_source_line(self):
        for body in (
            "努力ではない。才能でもない。\n仕組みだ。",
            "努力ではない。\n才能でもない。仕組みでした。",
            "努力ではない。\n才能でもない。\n習慣にある。",
            "車でも、家でもない。\n有頂天だった。",
        ):
            with self.subTest(body=body):
                hits = rule_findings("# 観察\n\n" + body, "negative_parallelism")
                self.assertEqual(len(hits), 1, hits)
                self.assertEqual(hits[0]["line"], 3)

    def test_unrelated_blocks_do_not_supply_a_missing_conclusion(self):
        for separator in (
            "\n\n",
            "\n\n## 別の話題\n\n",
            "\n\n```text\n例\n```\n\n",
            "\n\n> 別の話題です。\n\n",
        ):
            with self.subTest(separator=separator):
                text = "簡単ではない。不可能でもない。" + separator + "仕組みだ。"
                self.assertEqual(rule_findings(text, "negative_parallelism"), [])

    def test_idioms_and_a_pair_without_conclusion_are_kept(self):
        for text in (
            "それでも、誰のせいでもない。",
            "疲れているわけじゃない。何でもない。",
            "疲れているわけじゃない。何でもない。今日は早く寝る。",
            "簡単ではない。不可能でもない。",
            "簡単ではない。\n不可能でもない。",
        ):
            with self.subTest(text=text):
                self.assertEqual(rule_findings(text, "negative_parallelism"), [])


class TestJanaiConjunctionsAndParticles(unittest.TestCase):
    def test_conjunctions_and_final_particles_are_review_candidates(self):
        for text in (
            "でも、これは努力じゃない、仕組みです。",
            "つまり、これは才能じゃない、仕組みだ。",
            "しかし、AIは魔法じゃない、道具です。",
            "これは努力じゃない、仕組みなんですよ。",
            "これは才能じゃない、努力だよ。",
            "これは才能じゃない、努力だよね。",
        ):
            with self.subTest(text=text):
                hits = rule_findings(text, "negative_parallelism")
                self.assertEqual(len(hits), 1, hits)

    def test_idiomatic_janai_is_not_a_contrast(self):
        for text in (
            "いいじゃない、まだ時間はあるし。",
            "いいじゃない、明日は休みだ。",
            "すごいじゃない、これは君の成果だ。",
            "でも、いいじゃない、明日は休みだよ。",
        ):
            with self.subTest(text=text):
                self.assertEqual(rule_findings(text, "negative_parallelism"), [])


class TestHumanAdoptedNegationAlso(unittest.TestCase):
    def test_also_remains_exempt_including_past_and_polite_forms(self):
        for ending in ("ある", "あります", "あった", "ありました"):
            with self.subTest(ending=ending):
                text = f"雑談は仕事の妨げではなく、相談のきっかけでも{ending}。"
                self.assertEqual(rule_findings(text, "negative_parallelism"), [])
                self.assertEqual(rule_findings("\n".join([text] * 3), "negative_parallelism_density"), [])

    def test_everywhere_and_everyone_are_not_additive_also(self):
        for text in (
            "これは特別な事例ではなく、どこにでもある失敗だ。",
            "問題は人ではなく、誰にでもある思い込みだ。",
        ):
            with self.subTest(text=text):
                self.assertEqual(len(rule_findings(text, "negative_parallelism")), 1)


if __name__ == "__main__":
    unittest.main()
