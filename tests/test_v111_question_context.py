#!/usr/bin/env python3
"""短い「もちろん」の疑問文判定と、直前の文脈の回帰テスト。"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402


def mochiron_findings(text):
    return [finding for finding in yomiyasu_lint.lint_text(text)["findings"]
            if finding["rule"] == "short_mochiron"]


class TestQuestionContext(unittest.TestCase):
    def assert_kept(self, text):
        self.assertEqual(mochiron_findings(text), [], text)

    def assert_flagged(self, text, line):
        hits = mochiron_findings(text)
        self.assertEqual([(hit["line"], hit["severity"]) for hit in hits],
                         [(line, "info")], text)

    def test_adjectives_and_nouns_ending_in_ka_are_not_questions(self):
        for lead in ("部屋はとても静か", "暮らしは豊か", "海辺は穏やか", "記憶は確か",
                     "残りはわずか", "方法はこのほか", "選択肢はいくつか"):
            for wrapper in ("{}", "## {}", "- {}"):
                for ending in ("", "。"):
                    with self.subTest(lead=lead, wrapper=wrapper, ending=ending):
                        self.assert_flagged(wrapper.format(lead + ending) + "\n\nもちろん、欠点もある。\n", 3)

    def test_plain_and_polite_question_suffixes_keep_answers(self):
        for question in ("個人でも使えるか", "個人でも使えるか。", "手伝ってくれるか。",
                         "個人でも使えますか", "個人でも使えますか。", "同じ形式ですか。",
                         "個人でも使えるでしょうか", "個人でも使えるだろうか。",
                         "個人でも使えるのか", "個人では使えないか。", "個人でも使える？"):
            with self.subTest(question=question):
                self.assert_kept(question + "\nもちろん、使える。\n")

    def test_question_headings_and_bold_keep_adjacent_answers(self):
        for question in ("### 個人でも使えますか？", "### 個人でも使えるか",
                         "**Q. 個人でも使えますか？**", "__個人でも使えますか？__",
                         "### __個人でも使えますか？__", "「個人でも使えますか？」",
                         "**「個人でも使えますか？」**"):
            with self.subTest(question=question):
                self.assert_kept(question + "\n\nもちろん、使えます。\n")

    def test_wh_questions_do_not_exempt_a_short_concession(self):
        for question in ("## なぜ今、生成AIなのか", "では、なぜこの方法を選んだのか。",
                         "どうしてこの方法を選んだのか？", "どのように運用しますか？",
                         "どこで使いますか？", "いつ使いますか？", "誰が使いますか？",
                         "何を使いますか？", "どれを使いますか？", "どの方法を使いますか？"):
            with self.subTest(question=question):
                self.assert_flagged(question + "\n\nもちろん、課題もある。\n", 3)

    def test_indefinite_expressions_do_not_make_yes_no_questions_wh_questions(self):
        for question in ("いつでも使えますか？", "どこでも使えますか？", "誰でも使えますか？",
                         "何でも使えますか？", "どれでも使えますか？", "どの端末でも使えますか？",
                         "どうしても必要ですか？", "何か問題がありますか？", "誰か手伝えますか？", "いつか使えますか？"):
            with self.subTest(question=question):
                self.assert_kept(question + "\n\nもちろん、使えます。\n")

    def test_intervening_content_ends_the_question_context(self):
        for middle in ("別の話題です。", "## 別の話題", "```text\n設定例です\n```",
                       "<div>設定例です</div>", "---", "| 項目 | 値 |\n| --- | --- |\n| A | B |"):
            with self.subTest(middle=middle):
                text = "個人でも使えますか？\n\n" + middle + "\n\nもちろん、課題もある。\n"
                self.assert_flagged(text, len(text.splitlines()))

    def test_block_quote_does_not_supply_unquoted_answer_context(self):
        self.assert_flagged("> 本当に必要なのか？\n\nもちろん、課題もある。\n", 3)

    def test_only_the_last_sentence_supplies_question_context(self):
        for separator in ("", "\n", "\n\n"):
            with self.subTest(separator=separator):
                self.assert_kept("なぜ使うのか？個人でも使えますか？" + separator + "もちろん、使えます。\n")
                text = "個人でも使えますか？確認済みです。" + separator + "もちろん、課題もある。\n"
                self.assert_flagged(text, len(text.splitlines()))

    def test_answer_does_not_exempt_the_next_concession(self):
        self.assert_flagged("個人でも使えますか？もちろん、使えます。もちろん、課題もある。\n", 1)
        self.assert_flagged("個人でも使えますか？\nもちろん、使えます。\nもちろん、課題もある。\n", 3)

    def test_existing_short_mochiron_scope_is_preserved(self):
        for text in ("もちろんです。\n", "もちろん、構いません。\n", "平日はもちろん、休日も出かける。\n",
                     "「もちろん、行くよ。」と答えた。\n",
                     "もちろん、障害が疑われる場合は、これまでどおり担当に連絡してください。\n"):
            with self.subTest(text=text):
                self.assert_kept(text)
        self.assert_flagged("もちろん、失敗もする。\n", 1)


class TestQuestionContextCost(unittest.TestCase):
    def test_question_checks_do_not_rescan_growing_sentence_prefixes(self):
        # Sum the input inspected by the question checker: runtime alone can
        # hide quadratic work on a fast machine or fail on a busy machine.
        text = "いい？\n" + "?勿論、眠い。" * 1500 + "\n"
        original = yomiyasu_lint._ends_with_question
        inspected = 0

        def measured(sentence):
            nonlocal inspected
            inspected += len(sentence)
            return original(sentence)

        with patch.object(yomiyasu_lint, "_ends_with_question", measured):
            self.assertEqual(mochiron_findings(text), [])
        self.assertLessEqual(inspected, len(text) * 8)

    def test_alternating_closers_and_whitespace_finish_quickly(self):
        text = "いい？" + "」 " * 400000 + "」"
        started = time.perf_counter()
        self.assertTrue(yomiyasu_lint._ends_with_question(text))
        self.assertLess(time.perf_counter() - started, 3.0)


if __name__ == "__main__":
    unittest.main()
