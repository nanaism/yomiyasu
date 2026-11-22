#!/usr/bin/env python3
"""v3.2.0: lint の直し（指示書の1、2、4、6、7章）。

- 1章: pause_comma で、読点のあとの句の動詞の中の「が」（つながる、ながら）を別の主語と読まない。
  直前が漢字の「が」（広がる）は見分けない（限界）。
- 2章: pause_comma で、文頭の「実は、」「要は、」を前置きとして扱い、拾わない。
- 3章: pause_comma で、定義の「〜とは、」を拾わない（仕様の変更。「uv とは、」を KEEP へ移したのは
  tests/test_v200_pause_comma.py）。ここでは、同じ文のほかの主題を今までどおり拾うことを見る。
- 4章: pause_comma で、文頭の場面の枠（「この記事では、」）のあとで文が長い行は、指摘を続けたうえで、残してよい場合を
  message の最後に1文足す。
- 6章: ai_phrase に「多岐にわたる」「が求められている」を足す（info。点数、--strict、--fail-on に入らない。allow.txt で外せる）。
- 7章: slop_vocabulary で、文字どおりの「装置」（装置の中で動く、装置に組み込む、装置を制御する）を拾わない。
文はすべてこのファイルで作った類例。指示書の再現の欄で投稿や記事から引いた文は入れない。
"""
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock
import io
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402
from markdown_visibility import resolve_words  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import working_folder  # noqa: E402
from test_v200_pause_comma import MESSAGE  # noqa: E402


def pauses(text, doc_type="article"):
    result = yomiyasu_lint.lint_text(text if text.endswith("\n") else text + "\n", doc_type=doc_type)
    return [f for f in result["findings"] if f["rule"] == "pause_comma"]


def phrases(*names):
    return "".join("「" + name + "、」" for name in names)


class VerbGaTest(unittest.TestCase):
    """1章: 読点のあとの「つながります」「ながら」の中の「が」は、別の主語の「が」ではない。"""

    REMOVE = (
        ("小さな工夫が、やがて大きな変化につながります。", "小さな工夫が"),
        ("画面が、ゆっくり切り替わりながら表示されます。", "画面が"),
        ("地道な点検が、次の事故を防ぐことにつながる。", "地道な点検が"),
        ("古い設定が、新しい画面の表示とつながらない。", "古い設定が"),
        ("二つの部屋が、廊下でつながっています。", "二つの部屋が"),
        ("担当者が、記録を見ながら説明します。", "担当者が"),
    )
    # 読点のあとに本当に別の主語が来る文。「子どもたちが」は直前が名詞の終わり（たち）なので、すぐあとが「り」でも主語に数える
    KEEP = (
        "説明会では、担当者が手順を紹介しました。",
        "この画面では、利用者が自分で予約を取り消せます。",
        "週末は、子どもたちがりんごを並べます。",
    )
    # 限界: 直前が漢字の「が」（広がる、上がる）は動詞の中の「が」と見分けず、今までどおり別の主語に数える
    LIMIT = (
        "毎日の練習が、少しずつ自信に広がっていきます。",
        "今年の売上は、少しずつ上がっていきます。",
    )

    def test_verb_ga_does_not_hide_the_comma(self):
        for text, phrase in self.REMOVE:
            with self.subTest(text=text):
                found = pauses(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], MESSAGE.format(phrases=phrases(phrase)))

    def test_another_subject_still_keeps_the_comma(self):
        for text in self.KEEP:
            with self.subTest(text=text):
                self.assertEqual(pauses(text), [])

    def test_kanji_before_ga_is_a_known_limit(self):
        for text in self.LIMIT:
            with self.subTest(text=text):
                self.assertEqual(pauses(text), [])

    def test_line_hits_have_the_same_phrase(self):
        """1行の当て方（_pause_comma_hits）も、同じ句と「が」を返す。"""
        for text, phrase in self.REMOVE:
            with self.subTest(text=text):
                self.assertEqual([(hit[1], hit[2]) for hit in yomiyasu_lint._pause_comma_hits(text)],
                                 [(phrase[-1], phrase[:-1])])


class LeadAdverbTest(unittest.TestCase):
    """2章: 文頭の副詞の「実は」「要は」は主題ではないので、あとの読点を拾わない。句全体がこの語のときだけ外す。"""

    KEEP = (
        "実は、明日から受付を始めます。",
        "要は、手順を一つ減らせば足ります。",
        "- 実は、明日から受付を始めます。",
        "新しい棚は、実は、来月に入れ替えます。",
    )
    # 句の一部に「実は」「要は」を含むだけの主題と、ほかの短い主題は今までどおり拾う
    REMOVE = (
        ("事実は、記録の中にあります。", "事実は"),
        ("概要は、次のページにまとめます。", "概要は"),
        ("今は、紙の帳簿で数えています。", "今は"),
    )

    def test_lead_adverbs_are_not_topics(self):
        for text in self.KEEP:
            with self.subTest(text=text):
                self.assertEqual(pauses(text), [])

    def test_other_short_topics_are_still_found(self):
        for text, phrase in self.REMOVE:
            with self.subTest(text=text):
                found = pauses(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], MESSAGE.format(phrases=phrases(phrase)))

    def test_whole_phrase_only(self):
        self.assertIn("実は", yomiyasu_lint._PAUSE_CONNECTIVE)
        self.assertIn("要は", yomiyasu_lint._PAUSE_CONNECTIVE)
        self.assertNotIn("事実は", yomiyasu_lint._PAUSE_CONNECTIVE)


class DefinitionTopicTest(unittest.TestCase):
    """3章: 定義の「〜とは、」は拾わない。同じ行や同じ文のほかの短い主題の読点は、今までどおり拾う
    （拾わない文と、uv の文を KEEP に移したことは tests/test_v200_pause_comma.py）。"""

    ONLY_OTHERS = (
        ("この章では、ブランチとは、作業の流れを分けて記録する仕組みだと説明します。", ["この章では"]),
        ("ブランチとは、作業の流れを分ける仕組みです。新しい棚は、来月に入れ替えます。", ["新しい棚は"]),
        # 「ことは、」「あとは、」は「は」のかたまり（定義の「とは」ではない）
        ("大事なことは、毎日続けることです。", ["大事なことは"]),
        ("あとは、来週の棚に並べます。", ["あとは"]),
    )

    def test_only_the_other_topics_are_found(self):
        for text, names in self.ONLY_OTHERS:
            with self.subTest(text=text):
                found = pauses(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], MESSAGE.format(phrases=phrases(*names)))


class FrameNoteTest(unittest.TestCase):
    """4章: 文頭の句に続く「では、」「には、」のあと、次の読点か文末までが20字以上ある行では、指摘を続けたうえで、
    残してよい場合を message の最後に1文足す。ほかの行の message は 3.1.0 と1字も変えない。"""

    # 3.3.0: 文を言い換えた（残してよいのは、枠のあとの句が長く、外すと区切りが見えにくくなるとき。3.2.0 と同じ）
    NOTE = "文頭の場面の枠（「この記事では、」など）のあとの句が長く、読点を外すと区切りが見えにくくなるなら残してかまいません。"
    WITH_NOTE = (
        ("この記事では、新しい表計算アプリを毎日の集計作業に取り入れる手順を紹介します。", ["この記事では"], [1]),
        ("この画面には、先月から受け付けた申込みを日付の順に並べて表示します。", ["この画面には"], [1]),
        ("- この記事では、新しい表計算アプリを毎日の集計作業に取り入れる手順を紹介します。", ["この記事では"], [1]),
        # 段落の中で改行した文は、つないだ文で字数を数える（候補は助詞のある行に出す）
        ("この記事では、新しい表計算アプリを\n毎日の集計作業に取り入れる手順を紹介します。", ["この記事では"], [1]),
        # 行の2つ目の文の頭も文頭
        ("集計の手順は三回に分けて書きます。この記事では、新しい表計算アプリを毎日の集計作業に取り入れる手順を紹介します。",
         ["この記事では"], [1]),
        # かっこの中の読点では区切らない
        ("この記事では、「新しい表計算、古い表計算」の二つを比べて集計の手順を並べます。", ["この記事では"], [1]),
        # 読点のあとがちょうど20字（表計算アプリで毎日の集計を速く片づけます）
        ("この記事では、表計算アプリで毎日の集計を速く片づけます。", ["この記事では"], [1]),
        # 同じ行のほかの読点が短くても、1つが条件に当たれば足す
        ("この冊子では、植木の植え替えの手順をまとめます。この画面には、先月から受け付けた申込みを日付の順に並べて表示します。",
         ["この冊子では", "この画面には"], [1]),
    )
    WITHOUT_NOTE = (
        # 次の読点か文末までが20字未満（3.1.0 の試験の文と、19字の文）
        ("この冊子では、植木の植え替えの手順をまとめます。", ["この冊子では"]),
        ("新しい手順では、名簿を紙から画面に移し、印刷は必要なときだけにします。", ["新しい手順では"]),
        ("この記事では、表計算アプリで毎日の集計を早く終えます。", ["この記事では"]),
        # 字数は空白を除いて数える（空白を除くと19字）
        ("この記事では、Calc で毎日の集計を素早く片づけます。", ["この記事では"]),
        # 文頭でない「では、」
        ("なお、この記事では、新しい表計算アプリを毎日の集計作業に取り入れる手順を紹介します。", ["この記事では"]),
        # 「では、」「には、」でない主題と主語
        ("新しい表計算アプリは、毎日の集計作業に無理なく取り入れられる道具として使えます。", ["新しい表計算アプリは"]),
        ("新しい表計算アプリが、毎日の集計作業に無理なく取り入れられる道具になります。", ["新しい表計算アプリが"]),
        ("来年からは、新しい表計算アプリを毎日の集計作業に取り入れる手順を広めます。", ["来年からは"]),
    )

    def test_note_is_added_to_long_frames(self):
        for text, names, lines in self.WITH_NOTE:
            with self.subTest(text=text):
                found = pauses(text)
                self.assertEqual([f["line"] for f in found], lines)
                self.assertEqual(found[0]["message"], MESSAGE.format(phrases=phrases(*names)) + self.NOTE)

    def test_other_messages_are_unchanged(self):
        for text, names in self.WITHOUT_NOTE:
            with self.subTest(text=text):
                found = pauses(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], MESSAGE.format(phrases=phrases(*names)))

    def test_boundary_lengths(self):
        """試験の文の字数（読点のあとから句点の前まで、空白を除く）を確かめる。"""
        for text, count in (("この記事では、表計算アプリで毎日の集計を速く片づけます。", 20),
                            ("この記事では、表計算アプリで毎日の集計を早く終えます。", 19),
                            ("この記事では、Calc で毎日の集計を素早く片づけます。", 19)):
            with self.subTest(text=text):
                after = text.split("、", 1)[1].rstrip("。").replace(" ", "")
                self.assertEqual(len(after), count)

    def test_only_the_message_changes(self):
        """件数、行、severity、snippet と、ほかの規則の候補は、1文を足さないときと同じ。"""
        text = "\n\n".join(text for text, _, _ in self.WITH_NOTE) + "\n"
        for doc_type in ("article", "essay", "slides", "pr"):
            with self.subTest(doc_type=doc_type):
                with_note = yomiyasu_lint.lint_text(text, doc_type=doc_type)
                with mock.patch.object(yomiyasu_lint, "_PAUSE_FRAME_NOTE", ""):
                    without = yomiyasu_lint.lint_text(text, doc_type=doc_type)
                self.assertEqual(len(with_note["findings"]), len(without["findings"]))
                for found, plain in zip(with_note["findings"], without["findings"]):
                    if found["rule"] == "pause_comma":
                        self.assertEqual(found["message"], plain["message"] + self.NOTE)
                        found = dict(found, message=plain["message"])
                    self.assertEqual(found, plain)
                self.assertEqual(with_note["rule_penalty_score"], without["rule_penalty_score"])

    def test_without_a_type_nothing_is_found(self):
        """3.3.0 から pause_comma は種類を指定しないときも出て、1文を足した message も article と同じ。promo では出ない
        （名前は 3.2.3 までのまま）。"""
        text = self.WITH_NOTE[0][0]
        found = pauses(text, doc_type=None)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["message"].endswith(self.NOTE))
        self.assertEqual(found, pauses(text, doc_type="article"))
        self.assertEqual(pauses(text, doc_type="promo"), [])


def ai(text, **options):
    result = yomiyasu_lint.lint_text(text if text.endswith("\n") else text + "\n", **options)
    return [f for f in result["findings"] if f["rule"] == "ai_phrase"]


class AiPhraseTest(unittest.TestCase):
    """6章: ai_phrase に「多岐にわたる」「が求められている」を足す。段落の文だけに当て、script と essay では外す。
    何が多いのか、誰が何を求めているのかを確かめる候補で、message に置き換え先の語は出さない。"""

    TARGETS = (
        ("取り組むべき課題は多岐にわたります。", "多岐にわたる"),
        ("確かめる項目は多岐に渡り、一日では終わりません。", "多岐にわたる"),
        ("相談の内容は多岐にわたっていました。", "多岐にわたる"),
        ("現場では、手順をそろえることが求められています。", "が求められている"),
        ("窓口には、早い返事が求められており、人を増やします。", "が求められている"),
        ("新しい窓口には、短い待ち時間が求められていた。", "が求められている"),
        ("取り組むべき課題は多岐にわたります。まず、手順をそろえることが求められています。", "多岐にわたる、が求められている"),
    )
    KEEPS = (
        # カギ括弧と引用、見出し、箇条書き、表
        "「課題は多岐にわたります」と書かれていた。",
        "> 課題は多岐にわたります。",
        "# 課題は多岐にわたる",
        "- 現場では、手順をそろえることが求められています。",
        "| 課題は多岐にわたります。 |\n|---|\n| a |",
        # ほかの形
        "担当者は、上司から早い返事を求められています。",
        "これからは、早い返事が求められる。",
        "課題は多岐です。",
    )

    def test_targets_get_one_finding(self):
        for text, words in self.TARGETS:
            with self.subTest(text=text):
                found = ai(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["severity"], "info")
                self.assertEqual(found[0]["message"], yomiyasu_lint._AI_PHRASE_MESSAGE.format(words))

    def test_keeps_have_no_findings(self):
        for text in self.KEEPS:
            with self.subTest(text=text):
                self.assertEqual(ai(text), [])
                self.assertEqual(ai(text, doc_type="article"), [])

    def test_document_types(self):
        text = "取り組むべき課題は多岐にわたります。まず、手順をそろえることが求められています。\n"
        for doc_type in (None, "article", "pr", "manual", "slides", "minutes", "promo", "formal", "mail", "paper"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(len(ai(text, doc_type=doc_type)), 1)
        for doc_type in ("essay", "script"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(ai(text, doc_type=doc_type), [])
                self.assertNotIn("ai_phrase", yomiyasu_lint.lint_text(text, doc_type=doc_type)["context"]["skipped_by_doc_type"])

    def test_existing_forms_keep_their_order(self):
        names = [name for name, _ in yomiyasu_lint._AI_PHRASE_FORMS]
        self.assertEqual(names, ["見立てです", "潜む", "が招く", "欠かせない存在", "という挙動を排除", "なんよ", "て形の体言止め",
                                 "多岐にわたる", "が求められている"])
        found = ai("この設計は、運用時にリスクが潜む構造で、確かめる項目は多岐にわたります。")
        self.assertEqual(found[0]["message"], yomiyasu_lint._AI_PHRASE_MESSAGE.format("潜む、多岐にわたる"))

    def test_existing_forms_do_not_depend_on_the_new_words(self):
        """3.2.0 の語が同じ行にあっても、2.5.0 からの7つの形の当たり方は変わらない（強調の記号を挟んだ「を**改善**。」は、
        3.1.0 と同じく「て形の体言止め」にしない）。"""
        message = yomiyasu_lint._AI_PHRASE_MESSAGE.format
        found = ai("手順をそろえることが求められています。設定を見直して、速度を**改善**。")
        self.assertEqual([f["message"] for f in found], [message("が求められている")])
        found = ai("課題は多岐にわたります。見直して、速度を*改善*。")
        self.assertEqual([f["message"] for f in found], [message("多岐にわたる")])
        self.assertEqual(ai("設定を見直して、速度を**改善**。"), [])
        # 2.5.0 の手掛かりが当たる行では、今までどおり両方を出す
        found = ai("手順をそろえることが求められています。設定を見直して、速度を改善。")
        self.assertEqual([f["message"] for f in found], [message("が求められている、て形の体言止め")])

    def test_allow_words_remove_the_finding(self):
        text = "取り組むべき課題は多岐にわたります。まず、手順をそろえることが求められています。\n"
        with tempfile.TemporaryDirectory() as folder:
            words_dir = Path(folder) / ".yomiyasu-words"
            words_dir.mkdir()
            (words_dir / "allow.txt").write_bytes("多岐にわたる\n".encode("utf-8"))
            result = yomiyasu_lint.lint_text(text, words=resolve_words(folder, str(words_dir)))
            found = [f for f in result["findings"] if f["rule"] == "ai_phrase"]
            self.assertEqual([f["message"] for f in found], [yomiyasu_lint._AI_PHRASE_MESSAGE.format("が求められている")])
            (words_dir / "allow.txt").write_bytes("多岐にわたる\nが求められている\n".encode("utf-8"))
            result = yomiyasu_lint.lint_text(text, words=resolve_words(folder, str(words_dir)))
            self.assertEqual([f for f in result["findings"] if f["rule"] == "ai_phrase"], [])
            self.assertEqual(result["context"]["words"]["allow_removed"]["ai_phrase"], 1)

    def test_not_in_score_strict_or_fail_on(self):
        text = "取り組むべき課題は多岐にわたります。\n"
        result = yomiyasu_lint.lint_text(text)
        self.assertEqual([f["rule"] for f in result["findings"]], ["ai_phrase"])
        self.assertEqual(result["rule_penalty_score"], 100)
        with tempfile.TemporaryDirectory() as folder, working_folder(folder):
            path = Path(folder) / "a.md"
            path.write_bytes(text.encode("utf-8"))
            for args in (["--strict"], ["--fail-on", "warn"], ["--fail-on", "error"]):
                with self.subTest(args=args):
                    out, err = io.StringIO(), io.StringIO()
                    with redirect_stdout(out), redirect_stderr(err):
                        try:
                            code = yomiyasu_lint.main(args + ["--no-words", str(path)])
                        except SystemExit as stop:
                            code = stop.code
                    self.assertEqual(code, 0, out.getvalue() + err.getvalue())
                    self.assertIn("ai_phrase", out.getvalue())


def slop_words(text):
    found = yomiyasu_lint.lint_text(text if text.endswith("\n") else text + "\n")["findings"]
    return [f["message"].split("「", 1)[1].split("」", 1)[0] for f in found if f["rule"] == "slop_vocabulary"]


class LiteralDeviceTest(unittest.TestCase):
    """7章: すぐあとが「の中で動」「内で動」「に組み込」「を制御」「の制御」の「装置」は、文字どおりの機器なので拾わない。
    比喩の「装置」と定着した複合語の扱い（tests/test_v211_lint.py）は変えない。"""

    LITERAL = (
        "装置の中で動くソフトウェアを開発しています。",
        "装置内で動くプログラムを書き換えます。",
        "新しいセンサーは、装置に組み込む前に確かめます。",
        "画面から装置を制御する手順をまとめます。",
        "装置の制御に使う基板を替えます。",
    )
    # すぐあとでない語や、ほかの語が続く比喩の「装置」は今までどおり拾う
    METAPHOR = (
        "SNSは承認欲求の増幅装置だ。",
        "この町は、記憶を呼び起こす装置として機能している。",
        "物語は、記憶を呼び起こす装置の中で特別な位置を占める。",
    )

    def test_literal_devices_do_not_fire(self):
        for text in self.LITERAL:
            with self.subTest(text=text):
                self.assertEqual([word for word in slop_words(text) if word == "装置"], [])

    def test_metaphors_still_fire(self):
        for text in self.METAPHOR:
            with self.subTest(text=text):
                self.assertEqual(slop_words(text), ["装置"])


if __name__ == "__main__":
    unittest.main()
