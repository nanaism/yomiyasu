#!/usr/bin/env python3
"""Issue #4: コードの値を削って文末コロンを作らないことを確認する。"""

import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "yomiyasu_lint.py"
sys.path.insert(0, str(SCRIPT.parent))
import yomiyasu_lint


ISSUE4_DOCUMENT = """# CIの作業手順

### 生成物の更新忘れをCIで止める

APIの定義だけを更新して、クライアントの再生成を忘れても、CIが通ってしまいます。

- 場所：`.github/workflows/test.yml`
- やること：再生成したあとに差分が出ないかを検査する
- 規模：S

追加するstepの例です。

```yaml
- name: Check generated client is up to date
  run: |
    pnpm run generate
    git diff --exit-code -- src/generated
```"""


class TestTrailingColon(unittest.TestCase):
    def test_issue4_full_document_has_no_findings(self):
        result = yomiyasu_lint.lint_text(ISSUE4_DOCUMENT)
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["is_clean"])
        self.assertEqual(result["score"], 100)

    def test_label_values_do_not_become_trailing_colons(self):
        cases = (
            "- 場所：`.github/workflows/test.yml`",
            "- 場所: `.github/workflows/test.yml`",
            "- 場所： `.github/workflows/test.yml`",
            "- 場所：設定ファイル",
            "- 値：` `",
            "- 値：``",
            "- 値：``key:value``",
            "- 値：``a`b``",
            "- 値：```key:value```",
        )
        for text in cases:
            with self.subTest(text=text):
                findings = yomiyasu_lint.lint_text(text)["findings"]
                self.assertEqual([f for f in findings if f["rule"] == "trailing_colon"], [])

    def test_colons_inside_closed_inline_code_are_not_reported(self):
        cases = ("`key:value`", "値は`value:`", "値は``value:``", "値は``a`b:``")
        for text in cases:
            with self.subTest(text=text):
                findings = yomiyasu_lint.lint_text(text)["findings"]
                self.assertEqual([f for f in findings if f["rule"] == "trailing_colon"], [])

    def test_real_trailing_colons_keep_their_line_and_snippet(self):
        cases = (
            ("確認事項：", "確認事項："),
            ("確認事項:", "確認事項:"),
            ("値は`value`：", "値は`value`："),
            ("値は`value:`:", "値は`value:`:"),
            ("値は``a`b``：", "値は``a`b``："),
            ("値は`key:", "値は`key:"),
            ("確認事項：  ", "確認事項："),
        )
        for line, expected_snippet in cases:
            with self.subTest(line=line):
                findings = yomiyasu_lint.lint_text("本文です。\n" + line)["findings"]
                trailing = [f for f in findings if f["rule"] == "trailing_colon"]
                self.assertEqual(len(trailing), 1)
                self.assertEqual(trailing[0]["line"], 2)
                self.assertEqual(trailing[0]["snippet"], expected_snippet)
                self.assertEqual(trailing[0]["severity"], "warn")

    def test_existing_url_exclusion_is_preserved(self):
        cases = ("https://example.com/endpoint:", "`参考`https://example.com/endpoint:")
        for text in cases:
            with self.subTest(text=text):
                findings = yomiyasu_lint.lint_text(text)["findings"]
                self.assertEqual([f for f in findings if f["rule"] == "trailing_colon"], [])

    def test_other_findings_remain_on_a_line_with_a_code_value(self):
        text = "本文です。\n時間を溶かした。値：`x`"
        findings = yomiyasu_lint.lint_text(text)["findings"]
        self.assertEqual([f["rule"] for f in findings], ["metaphor_verb"])
        self.assertEqual(findings[0]["line"], 2)
        self.assertEqual(findings[0]["snippet"], "時間を溶かした。値：`x`")

    def test_excluded_markdown_blocks_are_not_reported(self):
        text = """---
title: サンプル:
---
# 見出し：
> 引用：
| 値： |
<aside>見出し：</aside>
```yaml
key:
```
~~~yaml
another:
~~~"""
        findings = yomiyasu_lint.lint_text(text)["findings"]
        self.assertEqual([f for f in findings if f["rule"] == "trailing_colon"], [])

    def test_cli_strict_accepts_the_issue4_document(self):
        process = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--json", "--strict"],
            input=ISSUE4_DOCUMENT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        result = json.loads(process.stdout)
        self.assertEqual(set(result), {"score", "is_clean", "metrics", "findings"})
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["is_clean"])
        self.assertEqual(result["score"], 100)

    def test_cli_json_warning_and_strict_exit_contract(self):
        for strict, expected_exit in ((False, 0), (True, 1)):
            with self.subTest(strict=strict):
                command = [sys.executable, "-B", str(SCRIPT), "--json"]
                if strict:
                    command.append("--strict")
                process = subprocess.run(
                    command,
                    input="本文です。\n確認事項：",
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    timeout=10,
                )
                self.assertEqual(process.returncode, expected_exit, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                result = json.loads(process.stdout)
                self.assertEqual(set(result), {"score", "is_clean", "metrics", "findings"})
                self.assertFalse(result["is_clean"])
                self.assertEqual(result["score"], 95)
                self.assertEqual(len(result["findings"]), 1)
                finding = result["findings"][0]
                self.assertEqual(set(finding), {"rule", "line", "severity", "message", "snippet"})
                self.assertEqual(finding["rule"], "trailing_colon")
                self.assertEqual(finding["line"], 2)
                self.assertEqual(finding["snippet"], "確認事項：")
                self.assertEqual(finding["severity"], "warn")
                self.assertIsInstance(finding["message"], str)


if __name__ == "__main__":
    unittest.main()
