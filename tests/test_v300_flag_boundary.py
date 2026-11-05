"""3.0.0: 語の一覧の flag.txt の語のうち、漢字と仮名を両方含む語（根の、の木）は、漢字の端の前後に漢字が続く所
（大根の、の木構造、栃木の）では数えない。漢字だけの語と仮名だけの語、英数字の端の決まりは前のまま。
語の一覧なしの出力は変わらない。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402


def project_terms(text, flag, allow=()):
    words = {"path": "/x", "allow": tuple(allow), "flag": tuple(flag), "allow_lines": len(allow),
             "flag_lines": len(flag), "allow_sha256": None, "flag_sha256": "0" * 64}
    result = yomiyasu_lint.lint_text(text, words=words)
    return [f for f in result["findings"] if f["rule"] == "project_term"]


def hit(text, word):
    return bool(project_terms(text, (word,)))


class FlagBoundaryTest(unittest.TestCase):
    def test_mixed_word_skips_kanji_compounds(self):
        self.assertFalse(hit("大根の煮物を作りました。", "根の"))
        self.assertFalse(hit("箱根の宿に泊まりました。", "根の"))
        self.assertTrue(hit("木の根の張り方を調べます。", "根の"))
        self.assertFalse(hit("データの木構造で持ちます。", "の木"))
        self.assertTrue(hit("構文の木を作ってから、型を調べます。", "の木"))
        self.assertFalse(hit("栃木の工場に送ります。", "木の"))
        self.assertFalse(hit("作業木の中で直します。", "木の"))
        self.assertTrue(hit("庭の木の枝を切りました。", "木の"))

    def test_kanji_only_and_kana_only_unchanged(self):
        self.assertTrue(hit("非公開鍵の扱いを決めます。", "公開鍵"))
        self.assertTrue(hit("次のスプリントレビューで決めます。", "スプリント"))
        self.assertTrue(hit("大根おろしを添えます。", "根"))

    def test_ascii_edges_unchanged(self):
        self.assertFalse(hit("変数 milestone_id を使います。", "milestone"))
        self.assertTrue(hit("次の milestone を決めます。", "milestone"))
        self.assertTrue(hit("API呼び出しの数を数えます。", "API呼び出し"))

    def test_message_words_allow_unchanged(self):
        found = project_terms("木の根のそばと、大根の畑。", ("根の",))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["message"], yomiyasu_lint._PROJECT_TERM_MESSAGE.format("根の"))
        self.assertEqual(project_terms("木の根のそば。", ("根の",), allow=("根の",)), [])

    def test_no_words_no_project_term(self):
        """一覧なしの出力が前と同じことは、tests/fixtures/g7_unchanged_outputs.json の試験で確かめる。"""
        text = "大根の煮物と、木の根の話です。\n"
        self.assertNotIn("project_term", [f["rule"] for f in yomiyasu_lint.lint_text(text)["findings"]])

    def test_pattern_is_built_once_per_list(self):
        pattern = yomiyasu_lint._flag_pattern(("根の", "公開鍵", "milestone"))
        self.assertEqual([m.group(0) for m in pattern.finditer("大根の 木の根の 非公開鍵 milestone")],
                         ["根の", "公開鍵", "milestone"])
        self.assertIsNone(yomiyasu_lint._flag_pattern(()))
        self.assertTrue(markdown_visibility.WORDS_FILES)


if __name__ == "__main__":
    unittest.main()
