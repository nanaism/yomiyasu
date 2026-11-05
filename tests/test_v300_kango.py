"""v3.0.0: 漢語を和語に開きすぎない決まり（利用者の指摘「確認→確かめ、使用する→使う、停止→止める、現在→今」）。

SKILL.md の「直訳語、漢語の詰まり、連用形名詞」の段落と、和語へ寄せる書き方を条件つきにした references の4ファイル
（rephrase-test.md、domains/tech.md、slop-catalog.md、gemini-syntax.md）を確かめる。和語の側の例（確かめる、使う、止める）は
禁じる振る舞いを呼ぶおそれがあるので、SKILL.md には漢語の側だけを書く。
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "yomiyasu" / "SKILL.md"
REF_COPIES = [ROOT / "references", ROOT / "skills" / "yomiyasu" / "references"]


def text(path):
    return path.read_text(encoding="utf-8")


def section(body, heading):
    start = body.index(heading)
    rest = body[start + len(heading):]
    match = re.search(r"\n#{2,3} ", rest)
    return heading + (rest[:match.start()] if match else rest)


class KangoSkillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = text(SKILL)
        cls.part = section(cls.skill, "### 直訳語、漢語の詰まり、連用形名詞")

    def test_paragraph_keeps_the_original_choice(self):
        """漢語と和語の選び方を原文のままにし、文書でふつうに使う漢語を和語の言い方に替えない。"""
        for words in ("漢語と和語の選び方は原文のままにします。",
                      "その文書でふつうに使う漢語（確認する、使用する、停止する、動作する、現在、現時点）は和語の言い方に替えず",
                      "報告書の「発生」も残します。",
                      "新規作成でも、資料の漢語を和語の言い方に替えません。"):
            with self.subTest(words=words):
                self.assertIn(words, self.part)

    def test_what_may_still_change(self):
        """和語に替えてよいのは、ほかの決まりで直す所だけ。そこでも意味の幅を変えない（2.5.0 の決まりを戻した）。"""
        for words in ("中身のない硬い漢語（多角的、包括的、活用する。`references/slop-catalog.md` 7章）",
                      "名詞化の言い回し（〜を実施する、〜することが可能です）",
                      "ほかの決まりで直す所だけです。",
                      "和語の動詞に替えるのは目的語が文の中で追え、意味の幅が同じときだけにします（「確認する」は「見る」にしません）。",
                      "書き直した所に、原文にない漢語や名詞化の言い回し（担保、〜の実施）を足しません。"):
            with self.subTest(words=words):
                self.assertIn(words, self.part)

    def test_persona_and_general_reader_stay_outside(self):
        """ペルソナで敬語を上げる言い換えと、general の読み手の言い換えは、この決まりの外（大賀さんの最後の A/B の H07）。"""
        self.assertIn("ペルソナで敬語を上げる言い換え（同じこと → 同様のこと）と、読み手を general に指定されたときの言い換え"
                      "（`references/audience.md` 8章）は、この決まりの外です。", self.part)

    def test_no_wago_examples_in_skill(self):
        """和語の側の例は書かない（禁じる振る舞いを呼ばないため）。2.6.0 の「発生」「担保」の文は、この段落にまとめた。"""
        for words in ("「確かめる」に", "「使う」に", "「止める」に", "「今」に", "「今のところ」に"):
            with self.subTest(words=words):
                self.assertNotIn(words, self.part)
        self.assertNotIn("「発生」「担保」のような硬い漢語を不要に重ねず", self.skill)


class KangoReferencesTest(unittest.TestCase):
    def test_wago_preference_is_conditional(self):
        """和語へ寄せる書き方を、文書でふつうに使う漢語には当てない形にした（2つの写しの両方）。"""
        for refs in REF_COPIES:
            rephrase = text(refs / "rephrase-test.md")
            tech = text(refs / "domains" / "tech.md")
            slop = text(refs / "slop-catalog.md")
            gemini = text(refs / "gemini-syntax.md")
            with self.subTest(copy=str(refs.relative_to(ROOT))):
                self.assertNotIn("和語の短い言い回しで書けるなら、そちらを採る", rephrase)
                self.assertIn("反対に、原文が文書でふつうに使う漢語（確認する、使用する、停止する）なら、ほかの決まりで直す所でなければ、"
                              "和語にする案は採らない", rephrase)
                self.assertNotIn("難しい漢語が続く箇所は、ふだん使う言葉や動詞に直します", tech)
                self.assertNotIn("漢字の割合は20%前後を目安にします。", tech)
                self.assertIn("技術文書でふつうに使う漢語は、和語の言い方に替えません", tech)
                self.assertIn("硬い漢語として扱わず、和語の言い方に替えない", slop)
                self.assertIn("「使用する」は「使う」にしない", slop)
                self.assertNotIn("意図しない動き方", gemini)
                self.assertIn("平易にするためだけに和語の言い方に替えない", gemini)


if __name__ == "__main__":
    unittest.main()
