#!/usr/bin/env python3
"""v2.1.1: 文末に固定した lint の規則が、文の終わりの後ろの飾り（絵文字、空白、☆♪のような記号、閉じかっこ、
対のない閉じ引用符）で外れないことを確かめる。絵文字そのものは emoji_prohibited で別に拾う。

句点、感嘆符、疑問符は飾りに数えない。対になった閉じかぎと引用符（」』）は、語への言及や会話の終わりなので飾りに数えない。
例文は、このファイルで作った合成の文。
"""

from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_lint  # noqa: E402


def lint(text):
    return yomiyasu_lint.lint_text(text)["findings"]


def rules(text):
    return [f["rule"] for f in lint(text)]


def without_emoji(text):
    """emoji_prohibited を除いた候補（規則、行、重さ、警告文）。snippet は飾りを含むので比べない。"""
    return [(f["rule"], f["line"], f["severity"], f["message"]) for f in lint(text) if f["rule"] != "emoji_prohibited"]


def messages(text, rule):
    return [f["message"] for f in lint(text) if f["rule"] == rule]


# 飾りの例: 空白つき、空白なし、全角空白、ZWJ の並び、肌の色、異体字セレクタ、キーキャップ、旗、記号
DECORATIONS = (" 🚀", "🚀", "　🎉", " 👨\u200d💻", "👍🏽", " ❤\ufe0f", " 1\ufe0f\u20e3", " 🇯🇵", " ✨✨", "♪", " ☆")


class DecoratedEqualsPlainMixin:
    def assert_same_as_plain(self, plain, decorated, rule):
        """飾りつきの文が、飾りのない文と同じ候補になり、その規則に当たり、絵文字なら emoji_prohibited も出る。"""
        self.assertIn(rule, rules(plain), plain)
        self.assertEqual(without_emoji(decorated), without_emoji(plain), decorated)
        if yomiyasu_lint._emoji_matches(decorated):
            self.assertIn("emoji_prohibited", rules(decorated), decorated)


class StripEndDecorationTest(unittest.TestCase):
    """文末の後ろの飾りを除く関数の振る舞い。"""

    def test_no_decoration_returns_same_object(self):
        for text in ("参考になれば幸いです。", "いかがでしたか？", "ABC", "", "見出し）"):
            self.assertIs(yomiyasu_lint._strip_end_decoration(text), text)

    def test_marks_are_kept_in_order(self):
        strip = yomiyasu_lint._strip_end_decoration
        self.assertEqual(strip("見ていきましょう🚀！"), "見ていきましょう！")
        self.assertEqual(strip("見ていきましょう？🚀"), "見ていきましょう？")
        self.assertEqual(strip("幸いです！🎉！"), "幸いです！！")
        self.assertEqual(strip("幸いです 　🎉"), "幸いです")

    def test_emoji_sequences(self):
        strip = yomiyasu_lint._strip_end_decoration
        for decoration in DECORATIONS:
            self.assertEqual(strip("幸いです" + decoration), "幸いです", repr(decoration))
        # キーキャップは数字ごと除く。数字だけなら除かない
        self.assertEqual(strip("手順は3つ 3\ufe0f\u20e3"), "手順は3つ")
        self.assertIs(strip("手順は3"), "手順は3")

    def test_closers_only_when_asked(self):
        strip = yomiyasu_lint._strip_end_decoration
        self.assertIs(strip("（見ていきましょう）"), "（見ていきましょう）")
        self.assertEqual(strip("（見ていきましょう）", yomiyasu_lint._END_CLOSERS), "（見ていきましょう")
        # 閉じかぎと引用符は、閉じかっことしても除かない
        for text in ("「いかがでしたか」", "『見ていきましょう』", '"見ていきましょう"', "[見ていきましょう]"):
            self.assertIs(strip(text, yomiyasu_lint._END_CLOSERS), text)


class MetaFillerEndTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """meta_filler の文末に固定した型（〜と言っても過言ではありません、いかがでしたか、見ていきましょう など）。"""

    PLAIN = (
        "それが真理と言っても過言ではありません",
        "それが答えと言っても過言ではないでしょう",
        "いかがでしたか",
        "いかがでしたでしょうか",
        "それでは、詳しく見ていきましょう",
        "必要なら、次に手順をまとめます",
        "まずは小さく始めましょう",
    )

    def test_issue_example(self):
        plain = "それが真理と言っても過言ではありません"
        self.assertIn("meta_filler", rules(plain))
        decorated = plain + " 🚀"
        self.assertIn("meta_filler", rules(decorated))
        self.assertIn("emoji_prohibited", rules(decorated))
        self.assertEqual(messages(decorated, "meta_filler"), messages(plain, "meta_filler"))

    def test_each_pattern_with_each_decoration(self):
        for plain in self.PLAIN:
            for decoration in DECORATIONS:
                self.assert_same_as_plain(plain, plain + decoration, "meta_filler")
            # 句点の前の飾りと、句点のあとの飾り
            self.assert_same_as_plain(plain + "。", plain + "🚀。", "meta_filler")
            self.assert_same_as_plain(plain + "。", plain + "。🚀", "meta_filler")

    def test_closing_parenthesis_is_skipped(self):
        # 文頭に固定した「必要なら」は、開きかっこで文頭が変わるので除く（文頭の飾りは読み飛ばさない）
        for plain in self.PLAIN:
            if plain.startswith("必要なら"):
                continue
            self.assert_same_as_plain(plain, "（" + plain + "）", "meta_filler")
            self.assert_same_as_plain(plain, "【" + plain + "】", "meta_filler")

    def test_question_mark_is_not_decoration(self):
        # 「見ていきましょう？」は、飾りを除いても疑問符が残るので、今までどおり当てない
        self.assertNotIn("meta_filler", rules("見ていきましょう？"))
        self.assertNotIn("meta_filler", rules("見ていきましょう？🚀"))
        self.assertNotIn("meta_filler", rules("見ていきましょう🚀？"))
        # 「いかがでしたか！」も今までどおり当てない
        self.assertNotIn("meta_filler", rules("いかがでしたか！"))
        self.assertNotIn("meta_filler", rules("いかがでしたか🚀！"))

    def test_quoted_mention_is_not_decoration(self):
        # 語への言及（閉じかぎで終わる文）は、飾りを除く前と同じく当てない
        for text in ("記事の結びの定番は「いかがでしたか」", "NG例：「見ていきましょう」 🚀",
                     "よくある書き方は『まずは小さく始めましょう』✨"):
            self.assertNotIn("meta_filler", rules(text), text)

    def test_code_and_url_are_not_prose(self):
        # コードと URL の中の語は、飾りを除いても文として読まない
        for text in ("表示する文字列は `いかがでしたか` 🚀",
                     "結びの例は `見ていきましょう）` です 🚀",
                     "参照先: https://example.com/いかがでしたか 🚀",
                     "```\nいかがでしたか 🚀\n```"):
            self.assertNotIn("meta_filler", rules(text), text)

    def test_continued_sentence_is_not_end(self):
        # 飾りのあとに文が続くなら文末ではない
        self.assertNotIn("meta_filler", rules("それが真理と言っても過言ではありません 🚀 という言い方"))
        self.assertNotIn("meta_filler", rules("いかがでしたか🚀という結び"))


class NegationEndTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """negative_parallelism の「Aじゃない、Bです。」と「AでもBでもない。Cだ。」。"""

    def test_janai_with_decoration(self):
        plain = "これは努力じゃない、仕組みです"
        for decoration in DECORATIONS:
            self.assert_same_as_plain(plain, plain + decoration, "negative_parallelism")
        self.assert_same_as_plain(plain + "。", plain + "💪。", "negative_parallelism")

    def test_extra_negation_with_decoration_before_period(self):
        plain = "車でも、家でもない。有頂天だ。"
        self.assert_same_as_plain(plain, "車でも、家でもない。有頂天だ🎉。", "negative_parallelism")
        self.assert_same_as_plain(plain, "車でも、家でもない。有頂天だ 🎉。", "negative_parallelism")

    def test_extra_negation_negative_conclusion_stays_excluded(self):
        # 言い切る文がまた否定なら当てない。飾りがあっても同じ
        self.assertNotIn("negative_parallelism", rules("車でも、家でもない。有頂天ではない。"))
        self.assertNotIn("negative_parallelism", rules("車でも、家でもない。有頂天ではない🎉。"))

    def test_extra_negation_needs_period(self):
        # 句点のない「有頂天だ🎉」は、折り返した文の途中でありうるので、今までどおり当てない
        self.assertNotIn("negative_parallelism", rules("車でも、家でもない。有頂天だ"))
        self.assertNotIn("negative_parallelism", rules("車でも、家でもない。有頂天だ🎉"))


class ShortMochironEndTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """short_mochiron の「もちろん、〜。」（数語だけの短い文）。"""

    def test_decoration_before_period_is_not_counted(self):
        plain = "もちろん、時には失敗もあります。"
        self.assert_same_as_plain(plain, "もちろん、時には失敗もあります🎉。", "short_mochiron")
        self.assert_same_as_plain(plain, "もちろん、時には失敗もあります 👨\u200d💻。", "short_mochiron")
        self.assert_same_as_plain(plain, "もちろん、時には失敗もあります。🎉", "short_mochiron")

    def test_period_is_still_required(self):
        self.assertNotIn("short_mochiron", rules("もちろん、時には失敗もあります"))
        self.assertNotIn("short_mochiron", rules("もちろん、時には失敗もあります🎉"))

    def test_decorated_question_before_is_a_question(self):
        # 直前の問いの後ろに飾りがあっても、問いへの答えとして当てない
        plain = "これで動きますか\nもちろん、動きます。"
        decorated = "これで動きますか🤔\nもちろん、動きます。"
        self.assertNotIn("short_mochiron", rules(plain))
        self.assertNotIn("short_mochiron", rules(decorated))
        self.assertNotIn("short_mochiron", rules("これで動きますか？ 🤔\nもちろん、動きます。"))


class CleftListEndTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """cleft_list_ending の「〜のは、A、B、C。」。"""

    def test_with_decoration(self):
        plain = "今回の改修で増えたのは、画面、帳票、通知"
        for decoration in (" 🚀", "🚀", " ✨✨", "♪"):
            self.assert_same_as_plain(plain, plain + decoration, "cleft_list_ending")
        self.assert_same_as_plain(plain + "。", plain + "🚀。", "cleft_list_ending")
        self.assert_same_as_plain(plain + "。", plain + "。🚀", "cleft_list_ending")

    def test_predicate_after_decoration_is_not_list(self):
        self.assertNotIn("cleft_list_ending", rules("今回の改修で増えたのは、画面、帳票、通知 🚀 の3つです。"))


class InstructionResidueEndTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """instruction_residue の書く行為の予告と、範囲の除外の予告。"""

    def test_with_decoration(self):
        for plain in ("この記事では、専門用語を使わずに説明します", "本記事では、細かな設定は扱いません"):
            for decoration in (" 🙌", "🙏", "　✨"):
                self.assert_same_as_plain(plain, plain + decoration, "instruction_residue")
            self.assert_same_as_plain(plain + "。", plain + "🙏。", "instruction_residue")

    def test_reference_still_exempts(self):
        self.assertNotIn("instruction_residue", rules("本記事では、細かな設定は扱いません 🙏\n詳しくは付録を参照してください。"))


class SummaryHeadingEndTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """short_summary_heading の「## まとめ」。"""

    def test_with_decoration(self):
        plain = "## まとめ\n\n短い本文です。\n"
        for decoration in (" 🎉", "✨", "　📝"):
            self.assert_same_as_plain(plain, "## まとめ" + decoration + "\n\n短い本文です。\n", "short_summary_heading")
            self.assert_same_as_plain("## おわりに\n\n短い本文です。\n",
                                      "## おわりに" + decoration + "\n\n短い本文です。\n", "short_summary_heading")

    def test_other_words_after_heading_still_not_summary(self):
        self.assertNotIn("short_summary_heading", rules("## まとめ 🎉 と次の一歩\n\n短い本文です。\n"))
        self.assertNotIn("short_summary_heading", rules("## まとめ（全体）\n\n短い本文です。\n"))


class DashListEndingTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """dash_list_ending の「速さ、軽さ、静けさ──。」。"""

    def test_with_decoration(self):
        plain = "速さ、軽さ、静けさ──"
        for decoration in (" ✨", "✨", "🌙"):
            self.assert_same_as_plain(plain, plain + decoration, "dash_list_ending")
        self.assert_same_as_plain(plain + "。", plain + "✨。", "dash_list_ending")

    def test_dash_with_following_text_stays_decoration(self):
        found = rules("速さ、軽さ、静けさ── ✨ そして明日へ")
        self.assertNotIn("dash_list_ending", found)
        self.assertIn("dash_decoration", found)


class MomentEndTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """metaphor_verb の「〜した瞬間だった」で文を結ぶ形。"""

    def test_with_decoration(self):
        plain = "それは彼が決断した瞬間だった"
        for decoration in (" 🌟", "🌟", " ✨✨", "♪"):
            self.assert_same_as_plain(plain, plain + decoration, "metaphor_verb")
        self.assert_same_as_plain(plain + "。", plain + "🌟。", "metaphor_verb")

    def test_continued_sentence_is_not_end(self):
        self.assertNotIn("metaphor_verb", rules("それは彼が決断した瞬間だった 🌟 と記録にある"))
        self.assertNotIn("metaphor_verb", rules("答えたのは、彼が決断した瞬間でした🌟。"))


class SentenceEndRepetitionTest(unittest.TestCase):
    """sentence_end_repetition の語尾。飾りつきの文を、飾りのない文と同じ語尾として数える。"""

    def test_decorated_endings_count_like_plain(self):
        plain = "設定を変えます\n画面を開きます\n保存します\n"
        self.assertIn("sentence_end_repetition", rules(plain))
        for decorated in ("設定を変えます🚀\n画面を開きます✨\n保存します🎉\n",
                          "設定を変えます 🚀\n画面を開きます　✨\n保存します 👍🏽\n"):
            self.assertEqual(without_emoji(decorated), without_emoji(plain), decorated)
            self.assertIn("emoji_prohibited", rules(decorated))
        one_line = "設定を変えます。画面を開きます。保存します。\n"
        self.assertIn("sentence_end_repetition", rules(one_line))
        decorated = "設定を変えます🚀。画面を開きます✨。保存します🎉。\n"
        self.assertEqual(without_emoji(decorated), without_emoji(one_line))

    def test_mixed_decorated_and_plain(self):
        text = "設定を変えます。画面を開きます🚀。保存します。\n"
        self.assertEqual(without_emoji(text), without_emoji("設定を変えます。画面を開きます。保存します。\n"))
        self.assertIn("sentence_end_repetition", rules(text))

    def test_different_endings_stay_different(self):
        self.assertNotIn("sentence_end_repetition", rules("設定を変えます🚀\n画面を開いた🎉\n保存します✨\n"))
        # 疑問符で終わる文は、飾りがあっても「ます」に数えない（今までどおり）
        self.assertNotIn("sentence_end_repetition", rules("設定を変えます🚀\n画面を開きます!🎉\n保存します✨\n"))

    def test_quotes_are_not_decoration(self):
        # 会話の「行きます」が並ぶ形は、閉じかぎを飾りに数えないので、今までどおり当てない
        text = "「行きます」\n「来ます」\n「見ます」\n"
        self.assertNotIn("sentence_end_repetition", rules(text))
        self.assertNotIn("sentence_end_repetition", rules("「行きます」🚀\n「来ます」✨\n「見ます」🎉\n"))

    def test_snippet_keeps_original_text(self):
        found = [f for f in lint("設定を変えます🚀\n画面を開きます✨\n保存します🎉\n") if f["rule"] == "sentence_end_repetition"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["snippet"], "保存します🎉")


class UnchangedRulesTest(unittest.TestCase):
    """飾りを読み飛ばさない規則と、規則の名前・警告文。"""

    def test_trailing_colon_value_emoji_is_not_colon_end(self):
        # 「状態：✅」の絵文字は値のことがあるので、文末のコロンとしては拾わない（今までどおり）
        self.assertNotIn("trailing_colon", rules("状態：✅"))
        self.assertIn("trailing_colon", rules("手順は次のとおりです："))

    def test_emoji_still_reported_once_per_line(self):
        found = [f for f in lint("それが真理と言っても過言ではありません 🚀✨") if f["rule"] == "emoji_prohibited"]
        self.assertEqual(len(found), 1)
        self.assertIn("🚀", found[0]["message"])

    def test_rule_names_and_messages_are_the_same(self):
        pairs = (("それが真理と言っても過言ではありません", " 🚀"),
                 ("これは努力じゃない、仕組みです", "💪"),
                 ("今回の改修で増えたのは、画面、帳票、通知", " 🚀"),
                 ("この記事では、専門用語を使わずに説明します", "🙌"),
                 ("速さ、軽さ、静けさ──", "✨"),
                 ("それは彼が決断した瞬間だった", "🌟"))
        for plain, decoration in pairs:
            self.assertTrue(without_emoji(plain))
            self.assertEqual(without_emoji(plain + decoration), without_emoji(plain))


def _emoji_sequences():
    """emoji_prohibited が絵文字として拾う1字（と異体字セレクタつきの字）を、全部の字を回して集める。"""
    found = []
    for code in range(0x80, 0x30000):
        char = chr(code)
        if 0xD800 <= code <= 0xDFFF:
            continue
        for sequence in (char, char + "\ufe0f"):
            if yomiyasu_lint.EMOJI_PATTERN.fullmatch(sequence):
                found.append(sequence)
                break
    return found


class EmojiDecorationCoverageTest(unittest.TestCase):
    """飾りの字は emoji_prohibited の絵文字の表から作るので、絵文字として拾う字はどれも文末の飾りとして除く。"""

    @classmethod
    def setUpClass(cls):
        cls.sequences = _emoji_sequences()

    def test_every_emoji_is_stripped(self):
        strip = yomiyasu_lint._strip_end_decoration
        self.assertGreater(len(self.sequences), 1000)
        missed = [sequence for sequence in self.sequences if strip("幸いです" + sequence) != "幸いです"]
        self.assertEqual(missed, [])

    def test_every_emoji_is_in_the_regex_run(self):
        run = re.compile(yomiyasu_lint._END_DECORATION_RUN)
        missed = [sequence for sequence in self.sequences if not run.fullmatch(sequence)]
        self.assertEqual(missed, [])

    def test_sequences_and_reviewer_examples(self):
        strip = yomiyasu_lint._strip_end_decoration
        # レビューで漏れていた字（異体字セレクタあり・なし）と、旗、キーキャップ、ZWJ の並び
        examples = ("‼\ufe0f", "‼", "⁉\ufe0f", "▶\ufe0f", "◀\ufe0f", "™\ufe0f", "©\ufe0f",
                    "®\ufe0f", "↔\ufe0f", "↩\ufe0f", "⤴\ufe0f", "▪\ufe0f", "◻\ufe0f",
                    "⬆\ufe0f", "ℹ\ufe0f", "Ⓜ\ufe0f", "〰\ufe0f", "〽\ufe0f", "⌨\ufe0f",
                    "⏏\ufe0f", "\U0001f1ef\U0001f1f5", "#\ufe0f\u20e3", "\U0001f468\u200d\U0001f4bb",
                    "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f")
        for sequence in examples:
            self.assertEqual(strip("見ていきましょう" + sequence), "見ていきましょう", repr(sequence))
            self.assertEqual(strip("見ていきましょう " + sequence + "。"), "見ていきましょう。", repr(sequence))


class ReviewerEmojiRuleTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """絵文字の表の字（‼\ufe0f ⁉\ufe0f ▶\ufe0f ™\ufe0f など）で、規則ごとに飾りのない文と同じ候補になる。"""

    MARKS = ("‼\ufe0f", "‼", "⁉\ufe0f", "▶\ufe0f", "◀\ufe0f", "™\ufe0f", "®",
             "⬆\ufe0f", "◻\ufe0f", "↩\ufe0f")

    def test_meta_filler(self):
        for plain in ("それが真理と言っても過言ではありません", "以上、新機能の紹介でした。いかがでしたか",
                      "それでは本題を見ていきましょう", "参考になれば幸いです"):
            for mark in self.MARKS:
                self.assert_same_as_plain(plain, plain + mark, "meta_filler")

    def test_metaphor_verb_moment(self):
        plain = "チームの空気が一変した瞬間だった"
        for mark in self.MARKS:
            self.assert_same_as_plain(plain, plain + mark, "metaphor_verb")

    def test_negation_and_cleft_and_residue(self):
        for plain, rule in (("これは努力じゃない、仕組みです", "negative_parallelism"),
                            ("今回の改修で増えたのは、画面、帳票、通知", "cleft_list_ending"),
                            ("この記事では、専門用語を使わずに説明します", "instruction_residue")):
            for mark in self.MARKS:
                self.assert_same_as_plain(plain, plain + mark, rule)

    def test_sentence_end_repetition(self):
        plain = "これはAです\nこれはBです\nこれはCです\n"
        for mark in self.MARKS:
            decorated = "これはAです{0}\nこれはBです{0}\nこれはCです{0}\n".format(mark)
            self.assertIn("sentence_end_repetition", rules(decorated), repr(mark))
            self.assertEqual(without_emoji(decorated), without_emoji(plain), repr(mark))

    def test_dash_list_and_summary_heading(self):
        for mark in self.MARKS:
            self.assert_same_as_plain("速さ、軽さ、静けさ──", "速さ、軽さ、静けさ──" + mark, "dash_list_ending")
            self.assert_same_as_plain("## まとめ\n\n短い本文です。\n", "## まとめ " + mark + "\n\n短い本文です。\n",
                                      "short_summary_heading")


class ClosingQuoteDecorationTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """対の開きがない閉じかぎと閉じ引用符（」』”’"'）は、文の型を見る規則で飾りとして除く。"""

    QUOTES = ("」", "』", "”", "’", '"', "'")

    def test_unpaired_closing_quote_each_rule(self):
        for plain, rule in (("それが真理と言っても過言ではありません", "meta_filler"),
                            ("いかがでしたか", "meta_filler"),
                            ("それでは、詳しく見ていきましょう", "meta_filler"),
                            ("これは努力じゃない、仕組みです", "negative_parallelism"),
                            ("今回の改修で増えたのは、画面、帳票、通知", "cleft_list_ending"),
                            ("この記事では、専門用語を使わずに説明します", "instruction_residue")):
            for quote in self.QUOTES:
                self.assert_same_as_plain(plain, plain + quote, rule)
                self.assert_same_as_plain(plain, plain + quote + " 🚀", rule)

    def test_unpaired_quote_short_mochiron(self):
        plain = "もちろん、時には失敗もあります。"
        for quote in self.QUOTES:
            self.assert_same_as_plain(plain, "もちろん、時には失敗もあります。" + quote, "short_mochiron")

    def test_paired_quote_mentions_do_not_fire(self):
        # 語への言及（箇条書き、表、段落の中の引用、コード）は、閉じかぎを除かないので今までどおり当てない
        for text in ("- 「いかがでしたか」\n- 「〜と言っても過言ではありません」\n",
                     "- NG例：『見ていきましょう』\n",
                     "| 例 | 「いかがでしたか」 |\n|---|---|\n| NG | 「見ていきましょう」 |\n",
                     "避けたい結びは「いかがでしたか」\n",
                     "避けたい結びは“見ていきましょう”\n",
                     "避けたい結びは‘見ていきましょう’\n",
                     '避けたい結びは"見ていきましょう"\n',
                     "避けたい結びは'見ていきましょう'\n",
                     "表示する文字列は `いかがでしたか」` です\n",
                     "「いかがでしたか😊 次回も」\n"):
            self.assertNotIn("meta_filler", rules(text), text)

    def test_quote_opened_on_earlier_line_of_the_paragraph(self):
        # 同じ段落の前の行で開いた会話の終わりは、飾りとして除かない
        for text in ("「そうか。\nそれが真理と言っても過言ではありません」\n",
                     "“そうか。\nそれでは、詳しく見ていきましょう”\n",
                     "\"そうか.\nそれでは、詳しく見ていきましょう\"\n"):
            self.assertNotIn("meta_filler", rules(text), text)

    def test_apostrophe_keeps_ascii_quote(self):
        # 英語のアポストロフィがある行の ' は、対があるかが分からないので除かない
        self.assertNotIn("meta_filler", rules("Let's try. いかがでしたか'\n"))
        self.assertIn("meta_filler", rules("Let’s try. いかがでしたか’\n"))

    def test_quotes_not_skipped_for_sentence_end_repetition(self):
        self.assertNotIn("sentence_end_repetition", rules("行きます」\n来ます」\n見ます」\n"))

    def test_link_bracket_is_not_decoration(self):
        self.assertNotIn("meta_filler", rules("[いかがでしたか](https://example.com)\n"))
        self.assertIs(yomiyasu_lint._strip_end_decoration("[見ていきましょう]", yomiyasu_lint._END_CLOSERS + "」"),
                      "[見ていきましょう]")


class BracketOpenerTest(unittest.TestCase):
    """閉じかっこは、対の開きかっこが文の頭（か句点の直後）にあるときだけ除く。"""

    def test_whole_sentence_in_brackets(self):
        for text in ("（見ていきましょう）", "【見ていきましょう】", "(見ていきましょう)", "前置き。（見ていきましょう）"):
            core = yomiyasu_lint._strip_end_decoration(text, yomiyasu_lint._END_CLOSERS)
            self.assertTrue(core.endswith("見ていきましょう"), text)
        self.assertIn("meta_filler", rules("（見ていきましょう）\n"))
        self.assertIn("meta_filler", rules("🚀（見ていきましょう）\n"))

    def test_aside_after_predicate(self):
        # 述語のあとのかっこ書きの文は、かっこの中で文を結んでいるので除く
        for text in ("設定の詳細は付録にまとめました（後半で実際の画面を見ていきましょう）。\n",
                     "第3章では認証の流れを扱います（具体的なコードは第4章で見ていきましょう）\n",
                     "第3章では認証の流れを扱います（具体的なコードは第4章で見ていきましょう）🚀\n"):
            self.assertIn("meta_filler", rules(text), text)

    def test_subtitle_in_brackets_does_not_fire(self):
        # 目次の副題や、前の語を補うかっこ書きは、文の頭のかっこではないので除かない
        text = "## 連載の目次\n\n- 第1回 環境構築（まずは小さく始めましょう）\n- 第2回 実践編（実際のコードを見ていきましょう）\n- 第3回 まとめ\n"
        self.assertNotIn("meta_filler", rules(text))
        self.assertNotIn("meta_filler", rules("詳細は前回の記事（第2回：いかがでしたか）\n"))
        self.assertNotIn("meta_filler", rules("詳細は前回の記事（いかがでしたか）🚀\n"))

    def test_unpaired_closer_is_kept(self):
        self.assertIs(yomiyasu_lint._strip_end_decoration("見ていきましょう）", yomiyasu_lint._END_CLOSERS),
                      "見ていきましょう）")


class ArrowAndWaveTest(DecoratedEqualsPlainMixin, unittest.TestCase):
    """矢印（←↑→↓）と波線（〜～）は、文の型を見る規則でだけ飾りとして除く。語尾を数える規則では除かない。"""

    def test_meta_filler(self):
        plain = "では、具体的な手順を見ていきましょう"
        for mark in ("↓", "→", "←", "↑", "〜", "～", "〜♪", " ↓", "↓🚀"):
            self.assert_same_as_plain(plain, plain + mark, "meta_filler")

    def test_not_for_sentence_end_repetition(self):
        # 「〜です〜」の伸ばしや手順の矢印は、語尾の種類を変えないので今までどおり数えない
        for text in ("設定を変えます→\n画面を開きます→\n保存します→\n", "楽しいです〜\nうれしいです〜\nおいしいです〜\n"):
            self.assertNotIn("sentence_end_repetition", rules(text), text)

    def test_arrow_is_not_emoji(self):
        self.assertNotIn("emoji_prohibited", rules("では、具体的な手順を見ていきましょう↓\n"))


class EmojiInsteadOfPeriodTest(unittest.TestCase):
    """句点の代わりに絵文字を置いて、同じ行で次の文を続けた形。"""

    def test_meta_filler(self):
        for text in ("いかがでしたか😊 次回もお楽しみに！\n",
                     "以上、新機能の紹介でした。いかがでしたか✨ 次回は設定編です。\n",
                     "では早速見ていきましょう👇 まずはインストールからです。\n",
                     "それが真理と言っても過言ではありません🚀次に設定を見ます。\n",
                     "参考になれば幸いです‼\ufe0f また書きます。\n"):
            self.assertIn("meta_filler", rules(text), text)
            self.assertIn("emoji_prohibited", rules(text), text)
            plain = text.replace("😊 ", "。").replace("✨ ", "。").replace("👇 ", "。").replace("🚀", "。")
            plain = plain.replace("‼\ufe0f ", "。")
            self.assertEqual(messages(text, "meta_filler"), messages(plain, "meta_filler"), text)

    def test_negation_and_residue(self):
        self.assertIn("negative_parallelism", rules("これは努力じゃない、仕組みです💪 次は手順です。\n"))
        self.assertIn("instruction_residue", rules("本記事では、細かな設定は扱いません🙏 次に手順を見ます。\n"))
        # 次の文が参照なら、今までどおり外す
        self.assertNotIn("instruction_residue", rules("本記事では、細かな設定は扱いません🙏 詳しくは付録を参照してください。\n"))

    def test_sentence_end_repetition_one_line(self):
        plain = "これはAです。これはBです。これはCです。\n"
        self.assertIn("sentence_end_repetition", rules(plain))
        for text in ("これはAです🚀これはBです🚀これはCです🚀\n", "これはAです🚀 これはBです✨ これはCです🎉\n"):
            self.assertIn("sentence_end_repetition", rules(text), text)
            self.assertEqual(without_emoji(text), without_emoji(plain), text)

    def test_other_endings_still_break_the_run(self):
        # 数えない語尾の文（「〜ある」「〜ない」）も分ける。分けないと次の文の語尾を引き継いで、続きを誤って数える
        plain = "比較した観点は三つある。一つ目は多様性だ。項目が大きく違うわけではない。二つ目は運用コストだ。三つ目は学習コストだ。\n"
        decorated = plain.replace("。", "😊 ").rstrip() + "\n"
        self.assertEqual(without_emoji(decorated), without_emoji(plain))
        plain = "問題は三つです。第一に、テストを書けません。第二に、修正につながります。第三に、追いにくくなっています。\n"
        decorated = plain.replace("。", "😊 ", 3)
        self.assertEqual(without_emoji(decorated), without_emoji(plain))

    def test_continued_sentence_is_not_split(self):
        # 絵文字のあとに助詞が続く、絵文字が語の代わりになる、かっこや引用の中では文を分けない
        for text in ("いかがでしたか🚀という結び\n", "それが真理と言っても過言ではありません 🚀 という言い方\n",
                     "見ていきましょう🚀と書く\n", "「いかがでしたか😊 次回もお楽しみに」\n",
                     "（見ていきましょう🚀 次は設定）\n"):
            self.assertNotIn("meta_filler", rules(text), text)
        # 絵文字のあとがかっこや記号なら、前の文の補足とみて分けない
        self.assertIsNone(yomiyasu_lint._decoration_breaks("楽しかったです♪（笑）また行きます"))
        self.assertIsNone(yomiyasu_lint._decoration_breaks("いかがでしたか😊 (次回は設定編)"))
        self.assertNotIn("sentence_end_repetition", rules("設定は⚙\ufe0fボタンから開きます。画面は📱アプリです。通知は🔔です。\n"))
        self.assertEqual(yomiyasu_lint._decoration_breaks("設定は⚙\ufe0fボタンから開きます"), None)

    def test_bold_after_emoji_is_a_new_sentence(self):
        self.assertIn("sentence_end_repetition", rules("これはAです🚀 **これは**Bです🚀 これはCです🚀\n"))

    def test_breaks_keep_text(self):
        pieces = yomiyasu_lint._decoration_breaks("いかがでしたか😊 次回もお楽しみに！")
        self.assertEqual(pieces, ["いかがでしたか😊 ", "次回もお楽しみに！"])
        self.assertEqual("".join(pieces), "いかがでしたか😊 次回もお楽しみに！")
        self.assertIsNone(yomiyasu_lint._decoration_breaks("いかがでしたか😊"))
        self.assertIsNone(yomiyasu_lint._decoration_breaks("飾りのない文です。"))

    def test_snippet_is_the_split_sentence(self):
        found = [f for f in lint("これはAです🚀これはBです🚀これはCです🚀\n") if f["rule"] == "sentence_end_repetition"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["snippet"], "これはCです🚀")


if __name__ == "__main__":
    unittest.main()
