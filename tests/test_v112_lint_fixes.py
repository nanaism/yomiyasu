#!/usr/bin/env python3
"""v1.1.2: 書き間違えたパターン、「溶かす」の活用、必須文字列の表の整合。"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_lint  # noqa: E402


def rules(text):
    return [finding["rule"] for finding in yomiyasu_lint.lint_text(text)["findings"]]


class TestMisspelledPatterns(unittest.TestCase):
    def test_hoka_naranai_without_wave_dash(self):
        for text in ("これは設計の失敗に他なりません。\n", "これは設計の失敗にほかなりません。\n"):
            with self.subTest(text=text):
                self.assertIn("meta_filler", rules(text))

    def test_zehi_try_and_refer(self):
        for text in ("このツールをぜひ試してみてください。\n", "ぜひ試してください。\n", "ぜひ参考にしてみてください。\n",
                     "ぜひ参考にしてください。\n", "ぜひ活用してみてください。\n"):
            with self.subTest(text=text):
                self.assertIn("meta_filler", rules(text))

    def test_other_requests_are_kept(self):
        for text in ("ぜひ一度お越しください。\n", "ぜひ設定を見直してください。\n"):
            with self.subTest(text=text):
                self.assertNotIn("meta_filler", rules(text))


class TestMeltingTimeConjugations(unittest.TestCase):
    def test_all_conjugations_of_melting_time(self):
        for text in ("設定で時間を溶かさない。\n", "時間を溶かさずに済んだ。\n", "時間を溶かして調べた。\n",
                     "昨日は設定で時間を溶かした。\n", "時間を溶かす。\n", "時間を溶かそうとは思わない。\n"):
            with self.subTest(text=text):
                self.assertIn("metaphor_verb", rules(text))

    def test_literal_melting_stays_clean(self):
        for number in range(21, 29):
            path = ROOT / "tests" / "corpus" / "edge_cases" / f"edge_tokasu_{number}.md"
            with self.subTest(path=path.name):
                self.assertEqual(yomiyasu_lint.lint_text(path.read_text(encoding="utf-8"))["score"], 100)


class TestLiteralHints(unittest.TestCase):
    """パターンを書き換えたら、必須文字列の表のキーも同じに直す（ずれると毎回すべての文を調べて遅くなる）。"""

    def test_every_pattern_has_a_hint(self):
        families = ((yomiyasu_lint.SLOP_WORD_PATTERNS, 1), (yomiyasu_lint.METAPHOR_VERB_PATTERNS, 0),
                    (yomiyasu_lint.TRANSLATED_TERM_PATTERNS, 0), (yomiyasu_lint.FILLER_PATTERNS, 0),
                    (yomiyasu_lint.INFO_SENTENCE_PATTERNS, 0))
        for rows, index in families:
            for row in rows:
                with self.subTest(pattern=row[index]):
                    self.assertIn(row[index], yomiyasu_lint._PATTERN_LITERAL_HINTS)

    def test_hints_are_needed_by_their_patterns(self):
        import re
        samples = {
            r"に(?:他|ほか)なりません": "失敗に他なりません",
            r"ぜひ(?:参考にして|試して|活用して)(?:みて)?ください[！!。]?": "ぜひ試してください",
            r"時間[をに]溶か[さしすせそ]": "時間を溶かさない",
        }
        for pattern, sample in samples.items():
            with self.subTest(pattern=pattern):
                self.assertTrue(re.search(pattern, sample))
                hints = yomiyasu_lint._PATTERN_LITERAL_HINTS[pattern]
                self.assertTrue(any(hint in sample for hint in hints))

    def test_literal_narrowing_stays_on(self):
        self.assertIsNotNone(yomiyasu_lint._document_tables())


if __name__ == "__main__":
    unittest.main()
