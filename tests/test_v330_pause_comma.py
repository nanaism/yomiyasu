#!/usr/bin/env python3
"""v3.3.0: lint の pause_comma（短い主語や主題、目的語のすぐあとの読点）。

- 1章: 読点のあとの別の主語と主題は、読点のあと12字の中にあるときだけ数える（3.2.3 までは60字）。
  主題の「Yは」の外し方（で・に・と・て などのあとの「は」）は 3.2.3 と同じ。
- 2章: 句の中に節がある主題を外すのは、句が14字を超えるときだけ（3.2.3 までは10字）。
- 3章: 条件や場面の枠を外すのは、句が7字を超えるときだけ（3.2.3 までは長さによらず外していた）。
- 4章: は・が・も で終わる接続の語、副詞、挨拶（ところが、あるいは、こんにちは など10語）を拾わない。
- 5章: 拾う句の長さを15字から20字にし、並べの最後の項目（A、B、Cは、）も拾う。
- 6章: 種類を指定しないときも当てる。promo と script では今までどおり出さない。目的語の「を、」も種類なしで拾う。
- 7章: message は自分の読点の形に当たらず、残すときの条件を3.2.3 と同じだけ書く。

文はすべてこのファイルで作った合成の文。3.2.3 と当たり方が違う文には、試験の説明にそのことを書いた。
"""
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint as lint  # noqa: E402

TYPES = ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal", "mail", "paper")


def hits(text):
    """1行の当て方で拾った句（助詞まで）を、位置の順に返す。"""
    found = sorted(lint._pause_comma_hits(text) + lint._pause_comma_object_hits(text))
    return [phrase + chunk for _, chunk, phrase in found]


def pauses(text, **options):
    return [f for f in lint.lint_text(text + "\n", **options)["findings"] if f["rule"] == "pause_comma"]


class NearSubjectTest(unittest.TestCase):
    def test_far_subject_or_topic_does_not_keep_the_comma(self):
        """読点のあと12字より先の主語と主題では残さない（3.2.3 はどの文も拾わなかった）。"""
        for text in ("この方式は、外部のサービスを呼ぶたびに通信の量が増える。",
                     "この方式は、外部のサービスを呼ぶ回数が少ない。",
                     "この方式は、外部のサービスを呼ぶ回数は少ない。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), ["この方式は"])

    def test_near_subject_or_topic_keeps_the_comma(self):
        for text in ("この方式は、回数が少ない。",
                     "会議では、担当者が説明しました。",
                     "今回は、第三段は小ネタ集です。",
                     "今回は、資料の束は机に置きます。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [])

    def test_topic_after_a_particle_is_not_counted(self):
        """「東京では」のように で・に・と などのあとの「は」は、近くにあっても別の主題に数えない（3.2.3 と同じ）。"""
        self.assertEqual(hits("今回は、東京では雨でした。"), ["今回は"])

    def test_object_commas_keep_the_wider_window(self):
        """目的語の「を、」は、読点のあと60字の中の主語を見るまま。"""
        self.assertEqual(hits("設定を、外部のサービスを呼ぶたびに通信の量が増えるので変えます。"), [])
        self.assertEqual(hits("設定を、変更したときに確かめます。"), ["設定を"])


class ClauseTopicTest(unittest.TestCase):
    def test_clause_topics_up_to_fourteen_characters_are_found(self):
        """節を含む13字の主題は拾う（3.2.3 は10字を超えると外していた）。"""
        self.assertEqual(hits("先週の会議で決めた新しい案は、来月から試します。"), ["先週の会議で決めた新しい案は"])
        self.assertEqual(hits("昨日届いた荷物は、棚に置きます。"), ["昨日届いた荷物は"])

    def test_longer_clause_topics_are_kept(self):
        self.assertEqual(hits("先週の定例の会議で決めた新しい案は、来月から試します。"), [])
        self.assertEqual(hits("昨日の夕方に倉庫へ届いた大きな荷物は、棚に置きます。"), [])


class ShortFrameTest(unittest.TestCase):
    def test_short_frames_are_found(self):
        """7字以下の条件や場面の枠は拾う（3.2.3 はどれも拾わなかった）。"""
        for text, phrase in (("そのときは、窓口に電話します。", "そのときは"),
                             ("この利点を得るには、設定を一つ変えます。", "この利点を得るには"),
                             ("働き始めたころは、毎朝六時に起きていた。", "働き始めたころは"),
                             ("雨の降るあいだは、外に出ません。", "雨の降るあいだは")):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [phrase])

    def test_longer_frames_are_kept(self):
        for text in ("申請を出したあとは、画面で状況を確かめられます。",
                     "集合に遅れそうな場合は、電話で知らせてください。",
                     "それでも開かないときは、窓口に電話してください。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [])


class ConnectiveTest(unittest.TestCase):
    WORDS = ("ところが", "あるいは", "または", "もしくは", "というのも", "じつは", "ときには", "時には", "こんにちは", "こんばんは")

    def test_connectives_and_greetings_are_in_the_table(self):
        for word in self.WORDS:
            with self.subTest(word=word):
                self.assertIn(word, lint._PAUSE_CONNECTIVE)

    def test_connectives_and_greetings_are_not_found(self):
        """3.2.3 は「ところが、」「あるいは、」「時には、」「こんにちは、」「こんばんは、」の文を拾っていた。"""
        for text in ("ところが、翌週にはもう売り切れていた。",
                     "あるいは、来週に延ばします。",
                     "または、紙の申込書で受け付けます。",
                     "もしくは、窓口で受け付けます。",
                     "というのも、去年の記録が残っていないからだ。",
                     "じつは、明日から受付を始めます。",
                     "ときには、遠回りして帰ります。",
                     "時には、遠回りして帰ります。",
                     "こんにちは、今日も暑いですね。",
                     "こんばんは、今夜も冷えますね。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [])
                self.assertEqual(pauses(text), [])

    def test_only_the_whole_phrase_is_skipped(self):
        """表の語は句全体のときだけ外す。句の一部なら、ほかの決まりで決める。"""
        self.assertEqual(hits("お店では、ときには、遠回りして帰ります。"), ["お店では"])


class LengthAndListTest(unittest.TestCase):
    def test_phrases_up_to_twenty_characters_are_found(self):
        """16字と20字の句は拾う（3.2.3 は15字を超えると外していた）。21字は外す。"""
        self.assertEqual(hits("古い倉庫の北側の通用口の予備の鍵は、事務所で預かります。"), ["古い倉庫の北側の通用口の予備の鍵は"])
        self.assertEqual(hits("市役所の古い倉庫の北側の通用口の予備の鍵は、事務所で預かります。"),
                         ["市役所の古い倉庫の北側の通用口の予備の鍵は"])
        self.assertEqual(hits("市役所の古い倉庫の北側の通用口の予備の合鍵は、事務所で預かります。"), [])
        self.assertEqual(lint._PAUSE_MAX_LEN, 20)

    def test_last_item_of_a_list_is_found(self):
        """並べの最後の項目の読点は拾う（3.2.3 は並べの1つとして外していた）。"""
        self.assertEqual(hits("東京の倉庫、大阪の倉庫、名古屋の倉庫は、来月に閉じます。"), ["名古屋の倉庫は"])
        self.assertEqual(hits("机、椅子、棚は、来月に入れ替えます。"), ["棚は"])
        self.assertFalse(hasattr(lint, "_pause_comma_list_before"))

    def test_other_list_rules_are_kept(self):
        """同じ助詞の句が並ぶ文、句の中の「AとB」、直前の「と、」は今までどおり外す。"""
        for text in ("東京も、大阪も、朝から雨でした。",
                     "平日と祝日は、このノートに書きます。",
                     "前半は、受付の流れを、後半は、集計の方法を説明します。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [])


class DefaultOnTest(unittest.TestCase):
    TEXT = "回覧板は、木曜の朝に回します。"

    def test_found_without_a_document_type(self):
        found = pauses(self.TEXT)
        self.assertEqual(len(found), 1)
        self.assertEqual(found, pauses(self.TEXT, doc_type="article"))
        self.assertEqual(pauses(self.TEXT, reader="general"), found)

    def test_every_type_but_promo_and_script(self):
        for value in TYPES:
            with self.subTest(doc_type=value):
                self.assertEqual(len(pauses(self.TEXT, doc_type=value)), 1)
        for value in ("promo", "script"):
            with self.subTest(doc_type=value):
                result = lint.lint_text(self.TEXT + "\n", doc_type=value)
                self.assertEqual([f for f in result["findings"] if f["rule"] == "pause_comma"], [])
                # 出さない種類では、外した候補にも数えない（3.2.3 と同じ）
                self.assertNotIn("pause_comma", result["context"]["skipped_by_doc_type"])

    def test_promo_and_script_do_not_run_the_detection(self):
        with mock.patch.object(lint, "_pause_comma_hits", side_effect=AssertionError("検出を呼ばない")), \
                mock.patch.object(lint, "_pause_comma_object_hits", side_effect=AssertionError("検出を呼ばない")):
            for value in ("promo", "script"):
                with self.subTest(doc_type=value):
                    self.assertEqual(pauses(self.TEXT, doc_type=value), [])

    def test_objects_are_found_without_a_type_but_not_in_essay(self):
        """目的語の「を、」は種類なしでも拾う（種類なしは article と同じ）。essay では今までどおり拾わない。"""
        text = "設定を、変更したときに確かめます。"
        found = pauses(text)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["message"].startswith("短い主語や主題、目的語のすぐあとに読点があります（「設定を、」）。"))
        self.assertEqual(found, pauses(text, doc_type="article"))
        self.assertEqual(pauses(text, doc_type="essay"), [])

    def test_command_line_without_a_type(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(
                sys, "stdin", io.TextIOWrapper(io.BytesIO((self.TEXT + "\n").encode("utf-8")), encoding="utf-8")):
            code = lint.main(["-"])
        self.assertEqual((code, err.getvalue()), (0, ""))
        self.assertIn("L1 [INFO] pause_comma: ", out.getvalue())
        self.assertIn("見直し候補: 1件", out.getvalue())

    def test_help_says_where_the_rule_is_off(self):
        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(SystemExit):
                lint.main(["--help"])
        help_text = out.getvalue()
        self.assertIn("種類によって出さない規則: pause_comma（promo、script では出しません。種類を指定しないときとほかの11種類では当てます）",
                      help_text)
        self.assertNotIn("pause_comma（promo、script を除く11種類。種類を指定しないときは出しません）", help_text)


class MessageTest(unittest.TestCase):
    TEXT = "回覧板は、木曜の朝に回します。"

    def messages(self):
        topic = pauses(self.TEXT)[0]["message"]
        objects = pauses("設定を、変更したときに確かめます。")[0]["message"]
        framed = pauses("この記事では、新しい表計算アプリを毎日の集計作業に取り入れる手順を紹介します。")[0]["message"]
        self.assertTrue(framed.endswith(lint._PAUSE_FRAME_NOTE))
        return topic, objects, framed

    def test_messages_keep_every_condition(self):
        topic, objects, framed = self.messages()
        for message in (topic, objects, framed):
            with self.subTest(message=message):
                for part in ("読点のすぐあとに別の主語や主題が来るとき", "長い条件や場面の枠を区切るとき", "語を並べているとき",
                             "外すと語がつながったり掛かり先が変わったりするとき",
                             "小説や随筆で書き手が間として置いた読点も残してかまいません",
                             "読点だけを外し、語順と述語は変えないでください"):
                    self.assertIn(part, message)
        self.assertIn("外すと区切りが見えにくくなるなら残してかまいません", framed)

    def test_messages_do_not_trigger_the_comma_rules_on_themselves(self):
        """message の文を lint に通しても、pause_comma と calque は出ない（3.2.3 の message は「間を作るだけの読点は、」に当たった）。"""
        text = "\n\n".join(self.messages()) + "\n\n" + lint._doc_type_table() + "\n"
        for options in ({}, {"doc_type": "article"}):
            with self.subTest(options=options):
                rules = [f["rule"] for f in lint.lint_text(text, **options)["findings"]]
                self.assertNotIn("pause_comma", rules)
                self.assertNotIn("calque", rules)


if __name__ == "__main__":
    unittest.main()
