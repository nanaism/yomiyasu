#!/usr/bin/env python3
"""Deterministic work budgets keep impossible expensive scans out of lint.

The recording wrapper delegates every call to the real regular expression;
no lint result or regex match is replaced. Timings belong in benchmarks.
"""

from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402
import markdown_visibility  # noqa: E402


class RecordingRegex:
    def __init__(self, pattern):
        self._compiled = pattern
        self.scanned_characters = 0
        self.matches = 0

    def __getattr__(self, name):
        return getattr(self._compiled, name)

    def search(self, text, *args):
        self.scanned_characters += len(text)
        match = self._compiled.search(text, *args)
        self.matches += match is not None
        return match

    def match(self, text, *args):
        self.scanned_characters += len(text)
        match = self._compiled.match(text, *args)
        self.matches += match is not None
        return match

    def finditer(self, text, *args):
        self.scanned_characters += len(text)
        for match in self._compiled.finditer(text, *args):
            self.matches += 1
            yield match


class TestLintPerformanceRegressions(unittest.TestCase):
    def test_plain_markdown_line_does_not_scan_an_impossible_container_marker(self):
        recording = RecordingRegex(markdown_visibility._CONTAINER_MARKER)
        with patch.object(markdown_visibility, "_CONTAINER_MARKER", recording), patch.object(
            markdown_visibility, "_CONTAINER_MARKER_DEFAULT", recording, create=True,
        ):
            self.assertEqual(markdown_visibility._containers("普通の文章をそのまま表示します。"), (0, 0, False))
        self.assertEqual(recording.scanned_characters, 0)

    def test_container_prefix_keeps_unicode_digits_and_custom_markers(self):
        cases = (
            ("> 本文", (2, 1, False)),
            ("> - 本文", (4, 1, True)),
            ("１. 項目", (3, 0, True)),
            ("². 項目", (0, 0, False)),
            ("*text*", (0, 0, False)),
            ("_ 本文", (0, 0, False)),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(markdown_visibility._containers(text), expected)
        with patch.object(markdown_visibility, "_CONTAINER_MARKER", re.compile(r"X\s+")):
            self.assertEqual(markdown_visibility._containers("X 本文"), (2, 0, True))

    def test_one_shot_lexical_rules_are_consumed_by_the_original_line_scan(self):
        text = "追加候補です。\n追加候補です。"
        cases = (
            ("SLOP_WORDS", ("追加候補",), "slop_vocabulary"),
            ("SLOP_WORD_PATTERNS", (("追加した語", r"追加候補"),), "slop_vocabulary"),
            ("TRANSLATED_TERM_PATTERNS", ((r"追加候補", "追加した用語"),), "translated_term"),
        )
        for name, values, rule in cases:
            with self.subTest(table=name), patch.object(yomiyasu_lint, name, iter(values)):
                result = yomiyasu_lint.lint_text(text)
            self.assertEqual([(item["rule"], item["line"]) for item in result["findings"]], [(rule, 1)])
            self.assertEqual(result["score"], 95)

    def test_malformed_lexical_rows_are_not_inspected_without_visible_prose(self):
        for name in ("SLOP_WORD_PATTERNS", "TRANSLATED_TERM_PATTERNS"):
            with self.subTest(table=name), patch.object(yomiyasu_lint, name, [None]):
                result = yomiyasu_lint.lint_text("")
                self.assertEqual(result["findings"], [])
                self.assertEqual(result["score"], 100)
                with self.assertRaises(TypeError):
                    yomiyasu_lint.lint_text("普通の文章です。")

    def test_invalid_compiled_family_keeps_first_pattern_error(self):
        with patch.object(yomiyasu_lint, "METAPHOR_VERB_PATTERNS", [(r"[", "無効な規則"), None]):
            with self.assertRaises(re.error):
                yomiyasu_lint.lint_text("")

    def test_ordinary_prose_does_no_impossible_repeated_negation_scan(self):
        text = "担当者が入力内容を確認しました。\n保存した値は翌日に読み込みます。"
        recording = RecordingRegex(yomiyasu_lint._NEGATION_EXTRA)
        with patch.object(yomiyasu_lint, "_NEGATION_EXTRA", recording):
            result = yomiyasu_lint.lint_text(text)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["score"], 100)
        self.assertTrue(result["is_clean"])
        self.assertEqual(
            recording.scanned_characters, 0,
            "Repeated-negation regex work is impossible without its mandatory literal.",
        )

    def test_real_negation_matches_keep_order_and_soft_break_source_line(self):
        cases = (
            ("# 観察\n\n努力ではない。才能でもない。仕組みだ。", 3, "努力ではない。才能でもない。仕組みだ。"),
            ("# 観察\n\n努力ではない。\n才能でもない。仕組みだ。", 3, "努力ではない。"),
            ("# 観察\n\n車でも、家でもない。\n有頂天だった。", 3, "車でも、家でもない。"),
        )
        for text, line, snippet in cases:
            with self.subTest(text=text):
                recording = RecordingRegex(yomiyasu_lint._NEGATION_EXTRA)
                with patch.object(yomiyasu_lint, "_NEGATION_EXTRA", recording):
                    result = yomiyasu_lint.lint_text(text)
                self.assertEqual(
                    [(item["rule"], item["severity"], item["line"], item["snippet"])
                     for item in result["findings"]],
                    [("negative_parallelism", "info", line, snippet)],
                )
                self.assertEqual(result["score"], 98)
                self.assertGreater(recording.scanned_characters, 0)
                self.assertGreater(recording.matches, 0)

    def test_positive_vocabulary_and_translation_keep_count_and_rule_order(self):
        text = "ゲートと閉包、台帳、思考のOS、本質を突いた。\nこの版では版を上げると回帰が発生します。"
        result = yomiyasu_lint.lint_text(text)
        self.assertEqual(
            [(item["rule"], item["severity"], item["line"]) for item in result["findings"]],
            [("slop_vocabulary", "warn", 1)] * 5 + [("translated_term", "warn", 2)] * 2,
        )
        messages = [item["message"] for item in result["findings"]]
        for message, word in zip(messages[:5], ("ゲート", "閉包", "台帳", "〜のOS", "本質を突く")):
            self.assertTrue(message.startswith(f"AI頻出語彙「{word}」"), message)
        self.assertIn("「版」（version）", messages[5])
        self.assertIn("「回帰」（regression）", messages[6])
        self.assertEqual(result["score"], 65)

    def test_new_pattern_after_warmup_keeps_full_search_fallback(self):
        text = "追加候補について説明します。"
        self.assertEqual(yomiyasu_lint.lint_text(text)["findings"], [])
        filler = yomiyasu_lint.FILLER_PATTERNS + [(r"^追加候補", "追加した見直し候補")]
        info = yomiyasu_lint.INFO_SENTENCE_PATTERNS + [(r"^追加候補", "added_info", "追加した説明")]
        with patch.object(yomiyasu_lint, "FILLER_PATTERNS", filler), patch.object(
            yomiyasu_lint, "INFO_SENTENCE_PATTERNS", info,
        ):
            result = yomiyasu_lint.lint_text(text)
        self.assertEqual(
            [(item["rule"], item["severity"], item["line"]) for item in result["findings"]],
            [("meta_filler", "warn", 1), ("added_info", "info", 1)],
        )
        self.assertIn("追加した見直し候補", result["findings"][0]["message"])
        self.assertEqual(result["findings"][1]["message"], "追加した説明")
        self.assertEqual(result["score"], 93)
        self.assertEqual(yomiyasu_lint.lint_text(text)["findings"], [])


if __name__ == "__main__":
    unittest.main()
