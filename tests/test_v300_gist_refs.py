"""3.0.0: references の直し（「前提が崩れる」の問い、繰り返しは定着の根拠にしない、型5と型4の新しい字、
漢語の決まりと直訳語の呼び名のすり合わせ）が、2つの写しに同じ字で入っていること。
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "references"
SKILL_REFS = ROOT / "skills" / "yomiyasu" / "references"
FILES = ("calques.md", "slop-catalog.md", "rephrase-test.md", "domains/business.md")


def chapter(text, number):
    match = re.search(r"^## {}\. .*?(?=^## |\Z)".format(number), text, re.M | re.S)
    return match.group(0) if match else ""


class GistReferencesTest(unittest.TestCase):
    def test_copies_are_identical(self):
        for name in FILES:
            with self.subTest(name=name):
                self.assertEqual((REFS / name).read_bytes(), (SKILL_REFS / name).read_bytes())

    def test_slop_catalog_chapter10_asks_for_premise(self):
        text = (REFS / "slop-catalog.md").read_text(encoding="utf-8")
        part = chapter(text, 10)
        self.assertIn("`metaphor_verb`（warn）の「前提が崩れる」で候補に出すもの", part)
        self.assertIn("| 「前提が崩れる」「基盤が崩れる」", part)
        self.assertIn("中身が前後の文になければ、「成り立たない」「当てはまらない」に替えるだけにせず、本文を残して尋ねる。", part)
        self.assertIn("尋ねるのは、確かめたい点の最大3点の中で、読み手の手順が変わるものから。", part)
        self.assertNotIn("→", part)
        self.assertNotIn("言い換えの候補", part)
        self.assertEqual(re.findall(r"^## (\d+)\.", text, re.M)[-1], "10")

    def test_calques_chapters(self):
        text = (REFS / "calques.md").read_text(encoding="utf-8")
        self.assertIn("## 1. 5つの型", text)
        self.assertIn("- 型5: 英語の術語に当てた2字以上の名詞", chapter(text, 1))
        self.assertIn("同じ文書や、同じリポジトリのほかの文書で繰り返し使っていることは、1つ目に「はい」と答える根拠にしない",
                      chapter(text, 2))
        self.assertIn("依頼、allow.txt、書き手が文書の中で定義した呼び名は、繰り返しとは別に扱い、それに従う。", chapter(text, 2))
        self.assertIn("ただし、lint の型4・型5に当たった語と flag.txt の語は、辞書の訳語でもこの例外に入らない（git の文書の「枝」）。",
                      chapter(text, 3))
        self.assertIn("型4と型5の語をその分野の呼び名に替えるのは", chapter(text, 4))
        self.assertIn("原文にない漢語を足さない決まりは", chapter(text, 4))
        # 2通りに読める動詞の章（gist の案6）は、測った条件に届かなかったので入れていない（3.0.0 の CHANGELOG）
        self.assertNotIn("2通りに読める動詞", text)
        self.assertEqual(re.findall(r"^## (\d+)\.", text, re.M), ["1", "2", "3", "4", "5"])

    def test_rephrase_test_points_to_calques(self):
        text = (REFS / "rephrase-test.md").read_text(encoding="utf-8")
        self.assertIn("直訳語をその分野で定着した呼び名に替えるのは、calques.md 4章のとおりこれに当たらない", text)

    def test_business_row_with_added_kango_is_gone(self):
        text = (REFS / "domains" / "business.md").read_text(encoding="utf-8")
        self.assertNotIn("全体の設計に問題が生じやすくなります", text)

    def test_skill_points_to_calques(self):
        text = (ROOT / "skills" / "yomiyasu" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("（型と例は `references/calques.md`）", text)
        self.assertNotIn("2通りに読める動詞", text)


if __name__ == "__main__":
    unittest.main()
