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
            # 地の文1,000字未満、warn 1件の重み2で95。
            self.assertEqual(result["rule_penalty_score"], 95)

    def test_malformed_lexical_rows_are_not_inspected_without_visible_prose(self):
        for name in ("SLOP_WORD_PATTERNS", "TRANSLATED_TERM_PATTERNS"):
            with self.subTest(table=name), patch.object(yomiyasu_lint, name, [None]):
                result = yomiyasu_lint.lint_text("")
                self.assertEqual(result["findings"], [])
                self.assertEqual(result["rule_penalty_score"], 100)
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
        self.assertEqual(result["rule_penalty_score"], 100)
        self.assertTrue(result["no_rule_findings"])
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
                # 地の文1,000字未満、info 1件の重み1で98。
                self.assertEqual(result["rule_penalty_score"], 98)
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
        # 地の文1,000字未満、warn 7件の重み14で74。
        self.assertEqual(result["rule_penalty_score"], 74)

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
        # 地の文1,000字未満、warn 1件と info 1件の重み3で93。
        self.assertEqual(result["rule_penalty_score"], 93)
        self.assertEqual(yomiyasu_lint.lint_text(text)["findings"], [])

    def test_many_broken_bold_in_one_paragraph_do_linear_repair_work(self):
        # 1つの段落に直せる崩れが多いとき、案を確かめるたびに段落全体を解析し直すと、崩れの数の2乗の仕事になる
        # （v2.0.1 では、1段落に3,000組で数十秒かかった）。解析した字数と、印の前後を調べた回数を数える。
        unit = "これは **「重要」**です。"
        work = {}
        for count in (40, 80, 160):
            text = unit * count
            with patch.object(yomiyasu_lint, "analyze_markdown", wraps=yomiyasu_lint.analyze_markdown) as analyzed, \
                    patch.object(yomiyasu_lint, "_roles", wraps=yomiyasu_lint._roles) as roles:
                findings = yomiyasu_lint.bold_problems(text)
            self.assertEqual(len(findings), 2 * count - 1)
            self.assertEqual([item["how"] for item in findings[:3]],
                             ["かっこの内側だけを太字にする", "手で直す", "かっこの内側だけを太字にする"])
            self.assertEqual(findings[-1]["found"], "これは **「重要」**です。")
            self.assertEqual(findings[-1]["suggest"], "これは 「**重要**」です。")
            work[count] = (sum(len(call.args[0]) for call in analyzed.call_args_list), roles.call_count)
            # 段落全体を解析し直すのは、決まった回数まで（元の文書と、表を作る前に解析し直す2回と、表の1回）。
            self.assertLessEqual(work[count][0], 6 * len(text))
        for count in (80, 160):
            with self.subTest(count=count):
                # 組の数を2倍にしたとき、仕事が3倍未満で済む（2乗なら4倍になる）。
                self.assertLess(work[count][0], 3 * work[count // 2][0])
                self.assertLess(work[count][1], 3 * work[count // 2][1])

    def test_bold_repairs_from_the_original_parse_match_full_reparse(self):
        # 元の解析から決めた案が、案ごとに段落全体を解析し直したときと同じになる。崩れを3組以上並べて、
        # 表を使う道を通す。行頭、コード、リンク、URL、エスケープ、ASCII のかっこなどの近くも含める。
        units = (
            "これは **「重要」**です。",
            "**「重要」**です。\n",
            "> **「重要」**です。\n",
            "- 項目\n  **「重要」**です。\n",
            "これは **「`code`」**です。",
            "これは [リンク](https://example.com) **「重要」**です。",
            "これは https://example.com **「重要」**です。",
            "これは **「重要」**です。ここは **太字** です。",
            "これは **(重要)**です。",
            "これは **[重要]**(x)です。",
            "これは!**[重要]**です。",
            "これは **重要!**[a](b)です。",
            "これは **重要。**です",
            "これは \\**「重要」**です。",
            "これは **「重要」**\\です。",
            "これは**「重要」**です。 **ok**、",
            "、**「重要」**です。*x*",
            "# **「重要」**です。\n",
            "**「重要」**www.example.com です。",
            "これは **「www.example.com」** です。",
            "a**b」**c **「d**e。",
        )
        texts = [unit * 4 for unit in units] + ["".join(units), "\n".join(units)]
        for text in texts:
            with self.subTest(text=text):
                expected_lint = yomiyasu_lint.lint_text(text)
                with patch.object(yomiyasu_lint, "_bold_repair_index", return_value=None):
                    self.assertEqual(yomiyasu_lint.lint_text(text), expected_lint)

    def test_repair_table_is_built_only_when_enough_pairs_remain(self):
        # 表を作る手間は段落全体を解析し直す1回分とほぼ同じなので、案を確かめる組が残り3組未満のときに作ると、
        # 作る手間のほうが省ける手間より大きい。直せる崩れが3つの段落では表を作らず、4つ以上なら段落ごとに1回作る。
        unit = "これは **「重要」**です。"
        for count, built in ((3, 0), (4, 1), (40, 1)):
            with self.subTest(count=count):
                text = "\n\n".join([unit * count] * 3) + "\n"
                with patch.object(yomiyasu_lint, "_BoldRepairIndex", wraps=yomiyasu_lint._BoldRepairIndex) as index:
                    findings = yomiyasu_lint.bold_problems(text)
                self.assertEqual(index.call_count, 3 * built)
                self.assertEqual(len(findings), 3 * (2 * count - 1))
                with patch.object(yomiyasu_lint, "_bold_repair_index", return_value=None):
                    self.assertEqual(yomiyasu_lint.bold_problems(text), findings)

    def test_forced_repair_table_declines_where_a_full_reparse_differs(self):
        # 最初の案から表で決めさせても、案ごとに段落全体を解析し直したときと同じ答えになる。表を使う前の確かめを
        # 1つ外すと答えが食い違う文を3つ選んだ。1つめは GFM の規則で閉じる相手を探した下限より後ろに (1, False) の
        # 開ける印が残る形、2つめはブロックに「<」がある形（動かした「]」で CDATA の終わりの「]]>」ができる）、
        # 3つめは「(」を動かすと「]」と隣り合ってリンクの「](」ができる形。
        cases = (
            (" *a *b **「。x」**→ y*z w** ", True),
            ("前 <![CDATA[ a**[x]**]> **[y]**c **[z]**c", False),
            ("x **x!** [b]**(x)**a", True),
        )
        original_scan = yomiyasu_lint._bold_scan_context
        original_decide = yomiyasu_lint._BoldRepairIndex.decide
        verdicts = []

        def scan(block_text, runs):
            result = original_scan(block_text, runs)
            result[3]["slow_tries"] = 2
            yomiyasu_lint._bold_repair_index(block_text, result[3])  # 残りの組の数によらず、表を先に作る
            return result

        def decide(index, i, j, shape, middle):
            verdict = original_decide(index, i, j, shape, middle)
            verdicts.append(verdict)
            return verdict

        for text, decided in cases:
            with self.subTest(text=text):
                with patch.object(yomiyasu_lint, "_bold_repair_index", return_value=None):
                    expected = yomiyasu_lint.bold_problems(text)
                del verdicts[:]
                with patch.object(yomiyasu_lint, "_bold_scan_context", side_effect=scan), \
                        patch.object(yomiyasu_lint._BoldRepairIndex, "decide", decide):
                    self.assertEqual(yomiyasu_lint.bold_problems(text), expected)
                # 表から決めた案があるか（「<」のあるブロックでは表を作らないので、1つもない）
                self.assertEqual(any(verdict is not None for verdict in verdicts), decided)


if __name__ == "__main__":
    unittest.main()
