#!/usr/bin/env python3
"""v3.2.0: lint の直し（指示書の1、2、4、6、7章）。

- 1章: pause_comma で、読点のあとの句の動詞の中の「が」（つながる、ながら）を別の主語と読まない。
  直前が漢字の「が」（広がる）は見分けない（限界）。

3章（「〜とは、」を指摘しない）の試験は tests/test_v200_pause_comma.py にある。
文はすべてこのファイルで作った類例。指示書の再現の欄で投稿や記事から引いた文は入れない。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
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
        "今年の目標は、売上が上がることです。",
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


if __name__ == "__main__":
    unittest.main()
