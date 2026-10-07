#!/usr/bin/env python3
"""Do not treat Japanese/Latin spacing alone as a prose defect."""

import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "yomiyasu_lint.py"
sys.path.insert(0, str(SCRIPT.parent))
import yomiyasu_lint


class TestSpacingPolicy(unittest.TestCase):
    def test_japanese_latin_spacing_alone_has_no_findings_or_penalty(self):
        cases = (
            "この README は設定を説明します。",
            "保存した savedFlag は true のままです。",
            "期間は 24 です。",
            "期限は 24 時間です。",
            "このREADMEは設定を説明します。",
        )
        for text in cases:
            with self.subTest(text=text):
                result = yomiyasu_lint.lint_text(text)
                self.assertEqual(result["findings"], [])
                self.assertEqual(result["score"], 100)
                self.assertTrue(result["is_clean"])

    def test_spacing_does_not_suppress_a_real_trailing_colon(self):
        text = "この README は設定を説明します。\n補足："
        result = yomiyasu_lint.lint_text(text)
        self.assertEqual([f["rule"] for f in result["findings"]], ["trailing_colon"])
        self.assertEqual(result["findings"][0]["line"], 2)
        self.assertEqual(result["findings"][0]["snippet"], "補足：")
        self.assertEqual(result["score"], 95)
        self.assertFalse(result["is_clean"])

    def test_markdown_significant_whitespace_remains_checked(self):
        problems = yomiyasu_lint.bold_problems("これは** 必須 **です。")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["suggest"], "これは**必須**です。")
        self.assertEqual(
            [f["rule"] for f in yomiyasu_lint.lint_text("これは** 必須 **です。")["findings"]],
            ["bold_not_rendered"],
        )
        rendered = yomiyasu_lint.lint_text("この **「用語」** は説明です。")
        self.assertEqual(rendered["findings"], [])
        self.assertEqual(rendered["score"], 100)

    def test_cli_strict_accepts_spaced_prose_with_unchanged_json_shape(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--json", "--strict"],
            input="この README は設定を説明します。",
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {"score", "is_clean", "metrics", "findings"})
        self.assertEqual(payload["findings"], [])
        self.assertTrue(payload["is_clean"])
        self.assertEqual(payload["score"], 100)


if __name__ == "__main__":
    unittest.main()
