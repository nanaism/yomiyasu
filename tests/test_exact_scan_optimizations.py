"""Protect outputs and work bounds of the small exact scan optimizations."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import markdown_visibility
import yomiyasu_diff


class ExactScanTests(unittest.TestCase):
    def test_bare_end_preserves_existing_parenthesis_rules(self):
        examples = {
            "確認します（注）（補足）。": "確認します",
            "確認します（注) (補足）": "確認します",
            "確認します（外（内））": "確認します（外（内",
            "確認します（未完": "確認します（未完",
            "確認します）": "確認します",
            "確認します(注)。まだ続きます": "確認します(注)。まだ続きます",
            "確認します(注。)": "確認します",
            "確認します。(注)": "確認します。",
        }
        for original, expected in examples.items():
            with self.subTest(original=original):
                self.assertEqual(yomiyasu_diff.bare_end(original), expected)

    def test_many_trailing_notes_finish_quickly(self):
        text = "確認します" + "(注) " * 20_000
        started = time.perf_counter()
        self.assertEqual(yomiyasu_diff.bare_end(text), "確認します")
        self.assertLess(time.perf_counter() - started, 3.0)

    def test_impossible_www_starts_do_not_validate_all_remaining_domains(self):
        repetitions = 2_000
        with patch.object(markdown_visibility.re, "fullmatch", wraps=markdown_visibility.re.fullmatch) as match:
            self.assertEqual(markdown_visibility.inline_protected_spans("www." * repetitions), [])
        self.assertLessEqual(match.call_count, repetitions + 10)

    def test_valid_url_boundaries_and_adjacent_prose_are_kept(self):
        for text, expected in (
            ("www.example.com", [(0, 15, "bare_url")]),
            ("awww.example.com", []),
            ("(www.example.com/path)", [(1, 21, "bare_url")]),
            ("文www.example.com", []),
        ):
            with self.subTest(text=text):
                self.assertEqual(markdown_visibility.inline_protected_spans(text), expected)

    def test_independent_tables_keep_line_kinds_and_finish_quickly(self):
        count = 12_000
        text = "| 項目 | 値 |\n|---|---|\n| A | B |\n\n" * count
        started = time.perf_counter()
        result = markdown_visibility.analyze_markdown(text)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertEqual(sum(row["kind"] == "table" for row in result["lines"]), count * 3)
        self.assertEqual(len(result["lines"]), count * 4 + 1)
