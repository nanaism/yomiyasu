#!/usr/bin/env python3
"""v2.1.1: metaphor_verb の比喩の「効く」を、前に副詞がなくても拾う。

- 「効いてくる」「効いてきます」「効いてきた」「効いてくれる」「効き始める」のような、効き目がだんだん表れる形は、
  主語が分からなくても拾う。ただし、同じ文、同じ行の前の文、前の3行に文字どおりの語（服用、飲んで、サプリ、エアコン など）が
  あるときと、同じ文に「30分ほど」のような分や時間の長さがあるときは拾わない。
- 「効く」「効いた」は、見直し、工夫、改善、施策 などの手順や取り組みを主語にしたときに拾う（「設定」は主語の語に入れない）。
- 「効く」の主語や対象の位置に、薬、冷房や暖房、ブレーキ、調味料や味、圧縮や最適化のような、文字どおり効き目が出るものの語が
  あれば、どの形でも拾わない。語は、あとに漢字やカタカナが続く所（「塩谷さん」「製剤チーム」）では語とみなさない。
- v2.1.0 から拾っている「地味に」「よく」「じわじわ」の直後の「効く」は、文字どおりの語が主語のときだけ拾わない。
- 新しく足した形の打ち消し（「効かない」「効いていない」「効いてこない」）は拾わない。
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
        """手順の語を主語にした「効いてくる」は、前の文に文字どおりの語があっても拾う。"""
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


# v2.1.0 の形 (地味に|よく|じわじわ)効[かきくけいた]。この形に当たる文は、文字どおりのものを除いて今までどおり拾う。
V210_KIKU = re.compile(r"(地味に|よく|じわじわ)効[かきくけいた]")
V210_EXAMPLES = ("地味に効く。\n", "# 地味に効く設定\n", "この方法はよく効く。\n", "じわじわ効いてくる。\n",
                 "地味に効きます。\n", "後から効く工夫だ。\n")


class MedicineAndReviewTest(unittest.TestCase):
    """薬やサプリ、飲み物、冷房の説明の「効いてくる」は、前の行に語があっても拾わない。"""

    LITERAL = (
        "1回1錠を服用してください。30分ほどで効いてきます。\n",
        "食後に1錠飲んでください。30分ほどで効いてきます。\n",
        "飲んで30分ほどで効いてきます。\n",
        "服用後、30分ほどで効いてきます。\n",
        "効き目は個人差がありますが、通常は1時間以内に効いてきます。\n",
        "効いてくるまで30分ほどかかります。\n",
        "1時間後に効いてきます。\n",
        "飲み始めて3日ほどで効いてきました。\n",
        "レビュー：飲み始めて3日ほどで効いてきました。リピートします。\n",
        "サプリを飲み始めて1か月、ようやく効いてきた気がする。\n",
        "このサプリ、後から効いてくるタイプです。\n",
        "花粉症の症状に効いてきた。\n",
        "コーヒーが効いてきた。\n",
        "カフェインが効いてきた。\n",
        "この薬は飲んでから30分ほどで効いてきます。\n",
        "エアコンをつけて10分ほどで効いてきた。\n",
        "湯船につかると、体の芯まで効いてくる。\n",
        "マッサージの後、じんわり効いてきた。\n",
        "- 頭痛薬：30分ほどで効いてきます。\n",
    )
    MULTILINE = (
        "この薬の飲み方\n\n食後に飲んでください。30分ほどで効いてきます。\n",
        "花粉症の薬を飲み始めた。\n2週間ほどで効いてきた。\n",
        "エアコンを入れた。\n10分ほどで効いてきた。\n",
        "## 用法・用量\n\n1回1錠を服用してください。\n30分ほどで効いてきます。\n",
        "用法・用量の見出しのあと\n\n## 用法・用量\n\n1回1錠を服用してください。\n30分ほどで効いてきます。\n",
        "| 薬 | 効き始め |\n|---|---|\n| A | 30分ほどで効いてきます |\n",
        "## 飲み方\n\nようやく効いてきた。\n",
        "エアコンを入れた。\n\n窓を閉めた。\nようやく効いてきた。\n",
    )

    def test_literal_gradual_forms_do_not_fire(self):
        for text in self.LITERAL + self.MULTILINE:
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])

    def test_gradual_forms_without_literal_context_still_fire(self):
        for text in ("この3つは、最初の数回の改善から効いてきます。\n", "この工夫は後から効いてきます。\n",
                     "最近になって、ようやく効いてきた。\n", "毎日の積み重ねが、半年ほどで効いてくる。\n",
                     "この3つは、最初の数回の改善から効いてくるはずです。\n", "この3つは最初の数回の改善から効いてくる。\n",
                     "この3つは、最初の数回の改善から、効いてきます。\n", "この工夫が、後から効いてきます。\n",
                     "この3つは、最初の数回の改善から効いてきそうです。\n", "この差が効いてくる。\n",
                     "これが後で効いてくる。\n", "最初の設計が、後になって効いてくる。\n",
                     "飲み会での雑談が、後から効いてきた。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(kiku_hits(text)), 1)

    def test_window_is_three_lines(self):
        """文字どおりの語は前の3行までしか見ない。4行より前の語では、主語のない「効いてきた」を拾う。"""
        self.assertEqual(kiku_hits("エアコンを入れた。\n一つ目。\n二つ目。\nようやく効いてきた。\n"), [])
        self.assertEqual([f["line"] for f in kiku_hits("エアコンを入れた。\n一つ目。\n二つ目。\n三つ目。\nようやく効いてきた。\n")],
                         [5])

    def test_window_does_not_hide_v210_or_abstract_forms(self):
        """前の行の語で抑えるのは、効き目がだんだん表れる形だけ。v2.1.0 の形と、手順を主語にした形は拾う。"""
        for text in ("1回1錠を服用してください。\n地味に効く。\n", "エアコンを入れた。\nこの工夫は後から効いてきます。\n",
                     "薬を飲んだ。設定の見直しが効いた。\n", "冷房がよく効いた部屋。地味に効く。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(kiku_hits(text)), 1)


class V210RegressionTest(unittest.TestCase):
    """v2.1.0 が拾っていた比喩は、人名や別の語の一部に文字どおりの語があっても拾う。"""

    METAPHORS = (
        "塩谷さんの工夫が地味に効いてきた。\n", "塩田さんの提案は地味に効く。\n", "酒井さんの見直しが地味に効いた。\n",
        "居酒屋での雑談が、地味に効いてくる。\n", "気の毒だが、この施策は地味に効く。\n",
        "毒舌なレビューが、じわじわ効いてきた。\n", "製剤チームの改善が地味に効いた。\n",
        "治療方針の議論で、この一言がじわじわ効いてきた。\n", "説明の香りづけ程度の工夫だが、地味に効いた。\n",
        "要点のツボを押さえた設計が地味に効く。\n", "このキャッシュ戦略は地味に効く。\n",
        "インデックス投資の積み重ねが、じわじわ効いてくる。\n",
        "日々の開発に**地味に効いてきます**。\n", "そこで**地味に効いてくる**のが、以下の3つの原則です。\n",
    )
    # v2.1.0 も拾っていたが、文字どおりの語が「効く」の主語や対象なので、v2.1.1 では拾わない文
    LITERAL = (
        "この薬はよく効く。\n", "目薬がよく効く。\n", "肩こりによく効くと評判です。\n", "下り坂ではエンジンブレーキがよく効く。\n",
        "わさびがよく効いた寿司。\n", "圧縮がよく効くデータです。\n", "殺虫剤がよく効く。\n", "このサプリ、じわじわ効いてきます。\n",
        "冷房がよく効いた部屋で作業した。\n", "ブレーキがよく効く。\n", "辛子がよく効いた。\n", "車内はエアコンがよく効いている。\n",
    )

    def test_v210_metaphors_still_fire(self):
        for text in self.METAPHORS:
            with self.subTest(text=text):
                self.assertTrue(V210_KIKU.search(text.replace("*", "")))
                self.assertEqual(len(kiku_hits(text)), 1)

    def test_v210_literal_uses_are_dropped(self):
        for text in self.LITERAL:
            with self.subTest(text=text):
                self.assertTrue(V210_KIKU.search(text))
                self.assertEqual(kiku_hits(text), [])

    def test_every_v210_sentence_here_is_kept_unless_literal(self):
        """このファイルの例文のうち v2.1.0 の形に当たる文は、文字どおりのものと慣用句を除いてすべて拾う。"""
        literal = set(self.LITERAL) | set(LiteralUsesTest.LITERAL) | set(MedicineAndReviewTest.LITERAL)
        examples = (self.METAPHORS + V210_EXAMPLES + CloseVariantsTest.FIRE
                    + MedicineAndReviewTest.LITERAL + LiteralUsesTest.LITERAL + self.LITERAL)
        for text in examples:
            if V210_KIKU.search(text.replace("*", "")) and text not in literal:
                with self.subTest(text=text):
                    self.assertEqual(len(kiku_hits(text)), 1)

    def test_v210_adverb_form_keeps_its_negation(self):
        """v2.1.0 の形は打ち消しでも拾っていたので、今までどおり拾う（新しく足した形の打ち消しは拾わない）。"""
        self.assertEqual(len(kiku_hits("地味に効かない。\n")), 1)


class TechnicalLiteralTest(unittest.TestCase):
    """圧縮、最適化、JIT、設定の反映のような、仕組みの決まった文字どおりの「効く」は拾わない。"""

    LITERAL = (
        "圧縮が効いてくる。\n", "最適化が効いてくる。\n", "データが増えるほど圧縮が効いてくる。\n",
        "コンパイラの最適化が効いてくれる。\n", "-O2を付けると最適化が効いてくれる。\n", "JITが効いてくると速くなる。\n",
        "ウォームアップのあと、JITの最適化が効いてくる。\n", "プリフェッチが効いてくる。\n", "GCのチューニングが効いてきた。\n",
        "タイヤが温まってくるとグリップが効いてくる。\n", "この設定は再起動後に効きます。\n", "設定の変更は再起動後に効く。\n",
        "この設定が効くのはログイン後です。\n", "ファイアウォールの設定が効いた。\n", "環境変数の設定が効いていない。\n",
        "フィルタの設定が効いていない。\n", "キャッシュが効いている。\n", "インデックスが効く。\n",
        "インデックスが効いてくるのは件数が増えてからです。\n", "クエリにインデックスが効いていない。\n",
        "エアコンの温度設定の変更が効いた。\n", "暖房の設定が効いた。\n", "空調の設定が効いていない。\n",
    )

    def test_technical_literal_uses_do_not_fire(self):
        for text in self.LITERAL:
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])

    def test_settei_is_not_an_abstract_subject(self):
        self.assertNotIn("設定", yomiyasu_lint._KIKU_ABSTRACT)
        # 依頼の「設定の見直しが効いた。」は「見直し」を主語にして拾う
        self.assertEqual(len(kiku_hits("設定の見直しが効いた。\n")), 1)


class CloseVariantsTest(unittest.TestCase):
    """依頼の3文に近い言い方も拾う。"""

    FIRE = (
        "設定の見直しが、効いた。\n", "この3つは、最初の数回の改善から効きます。\n", "この工夫は、後になって効き始めます。\n",
        "この工夫は効き始める。\n", "改善の効き目が出るのは数回後です。\n", "見直しの効き目が出てきた。\n",
        "設定を見直したのが効いた。\n", "設定を見直したことが効いた。\n", "見直したことが効いた。\n",
        "レビューの手順を見直したのが、結果的に一番効いた。\n", "これが後で効く。\n", "後で効く。\n", "これが後々効く。\n",
        "設計の段階での判断が、あとで効く。\n", "この見直しが、チームの開発速度にじわっと効いてくる。\n",
        "見直しが効いています。\n", "見直しは確実に効きました。\n", "この工夫が効く場面は多い。\n",
        "レビューの見直しが本当に効いたと感じています。\n", "小さな工夫の積み重ねが、確実に効いてきます。\n",
        "経験が効いてくる。\n", "じわじわと効く。\n",
    )
    # 主語の分からない「効き目が出る」と、手順でない語を主語にした「効く」「効いた」は拾わない
    NOT_FIRE = (
        "この差が効く。\n", "その差が後半に効いた。\n", "効き目が出るまで30分ほどかかります。\n", "効き目が出てきた。\n",
        "地味だけど効く。\n",
    )

    def test_close_variants_fire(self):
        for text in self.FIRE:
            with self.subTest(text=text):
                self.assertEqual(len(kiku_hits(text)), 1)

    def test_decided_not_to_fire(self):
        for text in self.NOT_FIRE:
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])


class NegationTest(unittest.TestCase):
    """新しく足した形の打ち消しは拾わない。"""

    def test_negations_do_not_fire(self):
        for text in ("この工夫は効かない。\n", "設定が効かない。\n", "この工夫は効いていない。\n", "対策が全然効いていない。\n",
                     "設定が効いていない。\n", "この施策は効いてこない。\n", "見直しが効いてない。\n", "この工夫は効きません。\n",
                     "見直しが効かなかった。\n", "この工夫は後から効いてこなかった。\n", "改善が効いてくれない。\n",
                     "この工夫は効き始めない。\n"):
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])


class FoodTest(unittest.TestCase):
    """料理の味や辛さの「効く」は拾わない。"""

    def test_food_does_not_fire(self):
        for text in ("後からじわじわ辛さが効いてくる。\n", "辛さが後から効いてくる。\n", "辛さがあとから効いてくる。\n",
                     "食べ進めるうちに、後から辛さが効いてきます。\n", "味の調整が効いた。\n", "塩加減の調整が効いた。\n",
                     "甘さが後から効いてくる。\n", "酸っぱさがじわじわ効いてくる。\n", "カレーのスパイスが効いてくる。\n",
                     "あとから辛みが効いてくるタイプのカレーです。\n"):
            with self.subTest(text=text):
                self.assertEqual(kiku_hits(text), [])

    def test_mi_inside_another_word_is_not_food(self):
        """「意味」「地味」の「味」は味の語とみなさない。"""
        for text in ("意味の見直しが効いた。\n", "地味な工夫が効いた。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(kiku_hits(text)), 1)


class ScanPathAfterFixTest(unittest.TestCase):
    """前の行を見るようにしても、速い経路とすべての文に当てる経路で同じ候補になる。"""

    def test_narrowed_and_full_scan_agree(self):
        texts = (MedicineAndReviewTest.LITERAL + MedicineAndReviewTest.MULTILINE + V210RegressionTest.METAPHORS
                 + V210RegressionTest.LITERAL + TechnicalLiteralTest.LITERAL + CloseVariantsTest.FIRE
                 + CloseVariantsTest.NOT_FIRE
                 + ("エアコンを入れた。\n一つ目。\n二つ目。\n三つ目。\nようやく効いてきた。\n",
                    "# 飲み方\n\n薬を飲んだ。\n\nこの工夫は後から効いてきます。\nようやく効いてきた。\n"))
        for text in texts:
            with self.subTest(text=text):
                fast = yomiyasu_lint.lint_text(text)
                with mock.patch.object(yomiyasu_lint, "_document_tables", return_value=None):
                    full = yomiyasu_lint.lint_text(text)
                self.assertEqual(fast["findings"], full["findings"])

    def test_hint_still_covers_every_candidate(self):
        """表の正規表現は「効」を含む形だけに当たる（手がかりの語「効」で落とさない）。"""
        pattern = re.compile(yomiyasu_lint._KIKU_PATTERN)
        for text in CloseVariantsTest.FIRE + V210RegressionTest.METAPHORS:
            with self.subTest(text=text):
                match = pattern.search(text.replace("*", ""))
                self.assertIsNotNone(match)
                self.assertIn("効", match.group())

    def test_many_candidates_on_one_line_stay_fast(self):
        for text in ("わさびが後から効いてきた、" * 5000 + "\n", "見直しが効いていない、" * 5000 + "\n",
                     "\n".join(["薬の話。" * 300] * 50 + ["後から効いてきた。" * 2000]) + "\n"):
            with self.subTest(length=len(text)):
                start = time.perf_counter()
                yomiyasu_lint.lint_text(text)
                self.assertLess(time.perf_counter() - start, 5.0)


if __name__ == "__main__":
    unittest.main()
