#!/usr/bin/env python3
"""v2.1.1: metaphor_verb の比喩の「効く」を、前に副詞がなくても拾う。

- 「効いてくる」「効いてきます」「効いてきた」「効いてくれる」のような、効き目がだんだん表れる形は、主語が分からなくても拾う。
- 「効く」「効いた」は、見直し、工夫、改善、施策、設定 などの手順や取り組みを主語にしたときだけ拾う。
- 同じ文か直前の文に、薬、冷房や暖房、ブレーキ、調味料や味のような、文字どおり効き目が出るものの語があれば拾わない。
- 「融通が効く」「気が効く」のような「利く」の慣用句は、ぼやけた比喩ではないので拾わない。
- 規則の名前、警告の文、速い経路の手がかりの語（「効」）は変えない。

例文は、依頼にある3文と、このファイルで作った合成の文。
"""

from pathlib import Path
from unittest import mock
import re
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_lint  # noqa: E402


KIKU = "比喩動詞「効く」の過剰使用"
KIKU_MESSAGE = (KIKU + "が検出されました。不自然な比喩動詞であれば、ふだん使う動詞や客観的な表現に書き直してください。"
                "ただし、文字どおりの動作や状態変化を表している場合は無理に言い換える必要はありません。")


def kiku_hits(text, **kwargs):
    return [f for f in yomiyasu_lint.lint_text(text, **kwargs)["findings"]
            if f["rule"] == "metaphor_verb" and f["message"].startswith(KIKU)]


class RequestSentencesTest(unittest.TestCase):
    """依頼にある3文は、それぞれ見直し候補になる。"""

    def test_three_request_sentences_fire(self):
        for text in ("この3つは、最初の数回の改善から効いてきます。\n",
                     "この工夫は後から効いてきます。\n",
                     "設定の見直しが効いた。\n"):
            with self.subTest(text=text):
                hits = kiku_hits(text)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["line"], 1)
                self.assertEqual(hits[0]["severity"], "warn")
                self.assertEqual(hits[0]["message"], KIKU_MESSAGE)

    def test_request_sentences_fire_inside_a_document(self):
        text = ("# 返信\n\nご確認ありがとうございます。\n\n"
                "この3つは、最初の数回の改善から効いてきます。\n\n詳しくは来週お送りします。\n")
        self.assertEqual([f["line"] for f in kiku_hits(text)], [5])

    def test_request_sentences_fire_for_each_doc_type(self):
        for doc_type in (None, "article", "mail", "promo"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(len(kiku_hits("この工夫は後から効いてきます。\n", doc_type=doc_type)), 1)


class GradualFormsTest(unittest.TestCase):
    """効き目がだんだん表れる形は、主語が分からなくても拾う。"""

    def test_gradual_forms_fire(self):
        for text in ("毎日の積み重ねが、半年ほどで効いてくる。\n",
                     "この差は、運用を続けるうちに効いてきます。\n",
                     "最近になって、ようやく効いてきた。\n",
                     "小さな手順の違いが、あとで効いてくれる。\n",
                     "その一言が、会議の後半に効いてきて、話がまとまった。\n",
                     "この考え方は、規模が大きくなるほど効いてきそうだ。\n",
                     "ここで決めた順番が、障害の対応で効いてくれました。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(kiku_hits(text)), 1)

    def test_abstract_subjects_fire(self):
        for text in ("毎週の振り返りの習慣が効いた。\n", "この施策は効く。\n", "対策が効いて、問い合わせが落ち着いた。\n",
                     "仕組みの変更が効いたのだと思う。\n", "地道な努力も効いた。\n", "ルールの見直しが効けば、手戻りは減る。\n",
                     "チームでの取り組みが確実に効いた。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(kiku_hits(text)), 1)

    def test_adverb_forms_still_fire(self):
        for text in ("地味に効く。\n", "# 地味に効く設定\n", "この方法はよく効く。\n", "じわじわ効いてくる。\n",
                     "後から効く工夫だ。\n", "地味に効きます。\n", "じわじわと効く。\n",
                     "日々の開発に**地味に効いてきます**。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(kiku_hits(text)), 1)

    def test_one_finding_per_line(self):
        text = "この工夫は後から効いてきます。設定の見直しも効いた。地味に効く。\n"
        self.assertEqual(len(kiku_hits(text)), 1)

    def test_later_sentence_on_the_same_line_fires(self):
        text = "昼は会議だった。夜は資料を読んだ。この工夫は後から効いてきます。\n"
        self.assertEqual(len(kiku_hits(text)), 1)


class LiteralUsesTest(unittest.TestCase):
    """文字どおりの「効く」では、見直し候補を出さない。"""

    LITERAL = (
        # 薬
        "この薬はよく効く。\n", "薬が効いてきた。\n", "風邪薬が効いてきて、熱が下がった。\n",
        "鎮痛剤が効いてくるまで、横になって待った。\n", "抗生物質が効かない菌もある。\n",
        "ワクチンが効いてくるまで2週間ほどかかる。\n", "注射が効いて、痛みが引いた。\n",
        "点滴が効いてきたのか、顔色が戻った。\n", "麻酔が効いてくる。\n", "目薬がよく効く。\n",
        # 冷房、暖房
        "冷房がよく効いた部屋で作業した。\n", "暖房が効いてきて、部屋が暖まった。\n", "エアコンが効いてくる。\n",
        "クーラーが効いてきた。\n", "車内はエアコンがよく効いている。\n", "空調が効いてきた。\n",
        # ブレーキ
        "ブレーキがよく効く。\n", "雨の日はブレーキが効きにくい。\n", "ブレーキが効いて、車はすぐ止まった。\n",
        # 調味料、味
        "わさびが効いた寿司を食べた。\n", "塩が効いている。\n", "塩気が効いたおにぎり。\n", "胡椒が効いたスープ。\n",
        "スパイスが効いてくる。\n", "辛子がよく効いた。\n", "出汁が効いた煮物だった。\n", "生姜が効いて体が温まる。\n",
        "山椒が効いてきた。\n", "隠し味が効いている。\n",
        # そのほかの文字どおりの効き目
        "HTTPキャッシュが効きにくい。\n", "N+1問題への対策が必要になり、HTTPキャッシュも効きにくい。\n",
        "インデックスが効いてくる。\n", "お酒が効いてきた。\n", "毒が効いてきた。\n",
    )

    def test_literal_examples_do_not_fire(self):
        for text in self.LITERAL:
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])

    def test_literal_word_in_the_previous_sentence(self):
        """直前の文に文字どおりの語があれば、主語のない「効いてきた」は拾わない。"""
        for text in ("薬を飲んだ。30分ほどで効いてきた。\n", "冷房を入れた。しばらくして効いてきた。\n",
                     "わさびを多めに入れた。あとから効いてくる。\n"):
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])

    def test_literal_word_two_sentences_before_does_not_hide(self):
        """2文前の語は見ない。間に別の文があれば、主語のない「効いてくる」は今までどおり拾う。"""
        text = "薬の棚を片づけた。午後は企画書を直した。この工夫は後から効いてきます。\n"
        self.assertEqual(len(kiku_hits(text)), 1)

    def test_plain_kiku_without_abstract_subject_does_not_fire(self):
        """主語が分からない「効く」「効いた」と、手順でない主語の「効く」は拾わない。"""
        for text in ("もう一つ効いたのは、聞き方の習慣だ。\n", "その一言が効いた。\n", "ブラウザの側の確かめは効きません。\n",
                     "効率を上げた。\n", "この対策は効き目が薄い。\n", "設定の見直しが効かなかった。\n",
                     "効く、効かないの話ではない。\n", "比喩的な動詞（壊れる、倒す、効くなど）を言い換えます。\n",
                     "同じプロセスで動かすと timeout が効かない。\n"):
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])

    def test_abstract_subject_does_not_reach_across_comma(self):
        """手順の語のあと、読点をまたいだ先の「効く」は、その語を主語とみなさない。"""
        self.assertEqual(kiku_hits("対策が必要になり、別の手段も効きにくい。\n"), [])


class IdiomTest(unittest.TestCase):
    """「利く」と書くべき慣用句を「効く」と書いた場合は拾わない（表記の違いはこの規則では扱わない）。"""

    def test_idioms_do_not_fire(self):
        for text in ("融通が効く人だ。\n", "鼻が効く。\n", "気が効く後輩だ。\n", "気の効いた返事をする。\n",
                     "目が効く。\n", "口が効けないほど驚いた。\n", "小回りが効く車だ。\n", "応用が効く。\n",
                     "機転が効いた返しだった。\n", "この設定は応用が効く。\n", "この工夫は融通が効く。\n",
                     "保存が効く食べ物。\n", "無理が効く年齢ではない。\n", "気を効かせてくれた。\n"):
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])

    def test_kiku_written_as_riku_is_not_taken(self):
        for text in ("融通が利く。\n", "気が利く。\n", "この工夫は後から利いてきます。\n"):
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])


class CodeAndQuoteTest(unittest.TestCase):

    def test_inline_code_is_not_taken(self):
        self.assertEqual(kiku_hits("比喩の動詞（`地味に効いてくる`、`効いてきます`）を言い換えました。\n"), [])

    def test_code_block_is_not_taken(self):
        self.assertEqual(kiku_hits("```\nこの工夫は後から効いてきます。\n```\n"), [])


class ScanPathTest(unittest.TestCase):
    """語の表で文を絞る速い経路と、すべての文に当てる経路で、同じ候補になる。"""

    TEXTS = (
        "この3つは、最初の数回の改善から効いてきます。\n",
        "この工夫は後から効いてきます。設定の見直しが効いた。\n",
        "薬が効いてきた。冷房がよく効いた部屋。昼は会議だった。地味に効く。\n",
        "# 地味に効く設定\n\n- 融通が効く\n- 施策が効いた\n",
        "薬を飲んだ。30分ほどで効いてきた。仕組みの変更が効いた。\n",
    )

    def test_narrowed_and_full_scan_agree(self):
        for text in self.TEXTS + tuple(LiteralUsesTest.LITERAL):
            with self.subTest(text=text):
                fast = yomiyasu_lint.lint_text(text)
                with mock.patch.object(yomiyasu_lint, "_document_tables", return_value=None):
                    full = yomiyasu_lint.lint_text(text)
                self.assertEqual(fast["findings"], full["findings"])
        for text in self.TEXTS:
            with self.subTest(text=text):
                self.assertTrue(kiku_hits(text))

    def test_hint_is_the_literal_kiku(self):
        hints = yomiyasu_lint._PATTERN_LITERAL_HINTS
        self.assertEqual(hints[yomiyasu_lint._KIKU_PATTERN], ("効",))
        self.assertNotIn(r"(地味に|よく|じわじわ)効[かきくけいた]", hints)
        self.assertIsNotNone(yomiyasu_lint._document_tables())
        # 手がかりの語は、拾う文のどれにも入っている（速い経路で落とさない）
        pattern = re.compile(yomiyasu_lint._KIKU_PATTERN)
        for text in ScanPathTest.TEXTS:
            for line in text.splitlines():
                if pattern.search(line.replace("**", "")):
                    self.assertIn("効", line)

    def test_rule_name_and_description_unchanged(self):
        self.assertEqual([desc for pattern, desc in yomiyasu_lint.METAPHOR_VERB_PATTERNS
                          if pattern == yomiyasu_lint._KIKU_PATTERN], [KIKU])
        self.assertEqual(yomiyasu_lint.METAPHOR_VERB_PATTERNS[0][1], KIKU)

    def test_long_lines_stay_fast(self):
        for text in (("この工夫は" + "あ" * 20000 + "効いてくる") * 3 + "\n",
                     "見直しが" * 5000 + "\n", "効" * 20000 + "\n",
                     ("薬" + "あ" * 3000 + "。効いてきた。") * 20 + "\n"):
            with self.subTest(length=len(text)):
                start = time.perf_counter()
                yomiyasu_lint.lint_text(text)
                self.assertLess(time.perf_counter() - start, 5.0)


if __name__ == "__main__":
    unittest.main()
