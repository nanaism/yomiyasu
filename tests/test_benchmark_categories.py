"""Regression coverage for reporting current detector categories, not prose style."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_corpus.py"
SPEC = importlib.util.spec_from_file_location("benchmark_categories_under_test", SOURCE)
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class BenchmarkCategoryTests(unittest.TestCase):
    def measure(self, documents):
        with tempfile.TemporaryDirectory(prefix="yomiyasu-category-report-") as folder:
            root = Path(folder)
            group = root / "human"
            group.mkdir()
            for index, text in enumerate(documents):
                (group / (str(index) + ".md")).write_text(text, encoding="utf-8")
            target = root / "results.json"
            with patch.object(BENCHMARK, "CORPUS_DIR", str(root)), patch.object(BENCHMARK, "RESULTS_PATH", str(target)):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = BENCHMARK.benchmark_corpus()
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), result)
            self.assertEqual(result["total_files"], len(documents))
            return result["summary"]["human"]

    def test_symbol_counts_include_current_colon_emoji_and_bracket_rules(self):
        summary = self.measure(["補足：", "確認しました。🔍", "# 記録（概要）", "この API を使います。"])
        self.assertEqual(summary["total_lookaround_findings"], 3)
        self.assertEqual(summary["symbols"], 3)
        self.assertEqual(summary["formatting"], 0)

    def test_formatting_counts_include_current_bold_list_and_contrast_rules(self):
        # Density rules deliberately skip documents of 300 characters or less.
        bold_document = "**前提**と**対象**を確認します。" + "a" * 320
        list_document = "- " + "a" * 160 + "\n- " + "b" * 160
        summary = self.measure([bold_document, list_document, "これは結果ではなく理由です。"])
        self.assertEqual(summary["total_lookaround_findings"], 3)
        self.assertEqual(summary["formatting"], 3)
        self.assertEqual(summary["symbols"], 0)

    def test_metaphor_counts_remain_separate_from_symbol_and_format_counts(self):
        summary = self.measure(["仕様が壊れます。"])
        self.assertEqual(summary["total_lookaround_findings"], 1)
        self.assertEqual(summary["metaphor_verbs"], 1)
        self.assertEqual(summary["symbols"], 0)
        self.assertEqual(summary["formatting"], 0)


if __name__ == "__main__":
    unittest.main()
