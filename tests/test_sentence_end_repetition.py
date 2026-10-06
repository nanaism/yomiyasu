#!/usr/bin/env python3
"""Issue #5: 文末の連続を段落内で数え、元の行番号を保つ回帰テスト。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint


class TestSentenceEndRepetition(unittest.TestCase):
    def assert_repetitions(self, text, expected):
        findings = [
            finding
            for finding in yomiyasu_lint.lint_text(text)["findings"]
            if finding["rule"] == "sentence_end_repetition"
        ]
        self.assertEqual(
            [(finding["line"], finding["snippet"]) for finding in findings],
            expected,
        )
        for finding in findings:
            self.assertEqual(finding["severity"], "warn")

    def test_issue5_separate_paragraphs_do_not_form_a_run(self):
        text = (
            "# 起動手順\n\n"
            "設定ファイルを読みます。\n\n"
            "次にサーバーを起動します。\n\n"
            "最後に画面を確認します。"
        )
        self.assert_repetitions(text, [])

    def test_blank_lines_reset_a_two_sentence_run(self):
        cases = [
            ("LF", "設定を読みます。起動します。\n\n画面を確認します。"),
            ("CRLF", "設定を読みます。起動します。\r\n\r\n画面を確認します。"),
            ("空白のみ", "設定を読みます。起動します。\n \t\n画面を確認します。"),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assert_repetitions(text, [])

    def test_excluded_blocks_do_not_join_body_paragraphs(self):
        cases = [
            ("見出し", "設定を読みます。起動します。\n## 次の手順\n画面を確認します。"),
            ("箇条書き", "設定を読みます。起動します。\n- 確認する項目\n画面を確認します。"),
            ("番号付きリスト", "設定を読みます。起動します。\n1. 確認する項目\n画面を確認します。"),
            ("引用", "設定を読みます。起動します。\n> 参照する説明\n画面を確認します。"),
            ("表", "設定を読みます。起動します。\n| 確認項目 |\n画面を確認します。"),
            ("HTML", "設定を読みます。起動します。\n<div>説明</div>\n画面を確認します。"),
            ("画像", "設定を読みます。起動します。\n![説明](sample.png)\n画面を確認します。"),
            ("コードフェンス", "設定を読みます。起動します。\n```text\nコード例です。\n```\n画面を確認します。"),
            ("インデントしたコード", "設定を読みます。起動します。\n\n    コード例です。\n\n画面を確認します。"),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assert_repetitions(text, [])

    def test_three_sentences_on_one_line_still_warn(self):
        text = "設定を読みます。起動します。画面を確認します。"
        self.assert_repetitions(text, [(1, "画面を確認します。")])

    def test_soft_line_breaks_do_not_reset_the_run(self):
        text = "設定を読みます。\n起動します。\n画面を確認します。"
        self.assert_repetitions(text, [(3, "画面を確認します。")])

    def test_long_inline_code_keeps_the_original_warning_snippet(self):
        sentence = "本文`" + "code" * 5000 + "`です。"
        self.assert_repetitions("\n".join([sentence] * 3), [(3, sentence)])

    def test_masked_code_before_final_punctuation_preserves_endings(self):
        for length in (100, 20000):
            for prefix in ("本文", "本文です"):
                sentence = prefix + "`" + "x" * length + "`。"
                expected = [(3, sentence)] if prefix.endswith("です") else []
                with self.subTest(length=length, prefix=prefix):
                    self.assert_repetitions("\n".join([sentence] * 3), expected)

    def test_public_helper_preserves_unicode_suffixes_and_scan_boundaries(self):
        for length in (0, 1, 62, 63, 64, 65, 66, 127, 128, 129, 4096):
            suffix = ("。！？\t\r\n\x1c\x85\u00a0\u2003\u3000" * (length + 1))[:length]
            sentence = "本文です" + suffix
            with self.subTest(length=length):
                findings = yomiyasu_lint.check_sentence_end_repetitions(
                    [(line, sentence) for line in (1, 2, 3)]
                )
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0]['line'], 3)
                self.assertEqual(findings[0]['snippet'], sentence)
                self.assertEqual(findings[0]['rule'], 'sentence_end_repetition')

    def test_suffix_trimming_keeps_nonwhitespace_zero_width_characters(self):
        for sentence in ("本文です\u200b。", "本文です\ufeff\r\n", "", "。！？ \t" * 100):
            with self.subTest(sentence=sentence):
                self.assertEqual(
                    yomiyasu_lint.check_sentence_end_repetitions(
                        [(line, sentence) for line in (1, 2, 3)]
                    ),
                    [],
                )

    def test_crlf_preserves_the_third_sentence_line(self):
        text = "設定を読みます。\r\n起動します。\r\n画面を確認します。"
        self.assert_repetitions(text, [(3, "画面を確認します。")])

    def test_a_new_paragraph_starts_counting_from_one(self):
        text = (
            "設定を読みます。起動します。\n\n"
            "画面を確認します。\n終了します。\n結果を記録します。"
        )
        self.assert_repetitions(text, [(5, "結果を記録します。")])

    def test_each_paragraph_can_have_its_own_warning(self):
        text = (
            "設定を読みます。起動します。画面を確認します。\n\n"
            "結果を記録します。終了します。画面を閉じます。"
        )
        self.assert_repetitions(
            text,
            [(1, "画面を確認します。"), (3, "画面を閉じます。")],
        )

    def test_four_same_endings_still_produce_one_warning(self):
        text = "設定を読みます。起動します。画面を確認します。終了します。"
        self.assert_repetitions(text, [(1, "画面を確認します。")])

    def test_a_different_ending_resets_the_run(self):
        text = "設定を読みます。起動します。準備は完了です。画面を確認します。終了します。"
        self.assert_repetitions(text, [])

    def test_frontmatter_is_not_counted_and_body_line_numbers_are_preserved(self):
        text = (
            "---\n"
            "description: 設定を読みます。起動します。画面を確認します。\n"
            "---\n\n"
            "設定を読みます。\n起動します。\n画面を確認します。"
        )
        self.assert_repetitions(text, [(7, "画面を確認します。")])

    def test_frontmatter_alone_does_not_warn(self):
        text = "---\ndescription: 設定を読みます。起動します。画面を確認します。\n---"
        self.assert_repetitions(text, [])

    def test_fenced_code_sentences_are_not_counted(self):
        cases = [
            ("backtick", "```text\n設定を読みます。起動します。画面を確認します。\n```"),
            ("tilde", "~~~text\n設定を読みます。起動します。画面を確認します。\n~~~"),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assert_repetitions(text, [])

    def test_a_shorter_fence_does_not_end_a_longer_code_fence(self):
        text = "````text\n```\n設定を読みます。起動します。画面を確認します。\n````"
        self.assert_repetitions(text, [])

    def test_a_different_fence_kind_does_not_end_the_code_block(self):
        text = "```text\n~~~\n設定を読みます。起動します。画面を確認します。\n```"
        self.assert_repetitions(text, [])

    def test_a_fence_with_trailing_text_does_not_end_the_code_block(self):
        text = "```text\n```not-a-closer\n設定を読みます。起動します。画面を確認します。\n```"
        self.assert_repetitions(text, [])

    def test_an_unclosed_fence_keeps_following_code_out_of_the_count(self):
        text = "```text\n設定を読みます。起動します。画面を確認します。"
        self.assert_repetitions(text, [])

    def test_closed_fences_allow_body_repetition_after_code(self):
        cases = [
            ("backtick", "```text\nコード例です。\n```\n設定を読みます。\n起動します。\n画面を確認します。"),
            ("tilde", "~~~text\nコード例です。\n~~~\n設定を読みます。\n起動します。\n画面を確認します。"),
            ("開始より長い閉じフェンス", "````text\nコード例です。\n`````\n設定を読みます。\n起動します。\n画面を確認します。"),
            ("CRLFと閉じフェンス後の空白", "```text\r\nコード例です。\r\n``` \t\r\n設定を読みます。\r\n起動します。\r\n画面を確認します。"),
        ]
        for name, text in cases:
            with self.subTest(name=name):
                self.assert_repetitions(text, [(6, "画面を確認します。")])

    def test_extraction_keeps_two_element_tuples_and_original_lines(self):
        text = "# 手順\n\n設定を読みます。起動します。\n\n画面を確認します。"
        self.assertEqual(
            yomiyasu_lint.extract_plain_sentences(text),
            [(3, "設定を読みます。"), (3, "起動します。"), (5, "画面を確認します。")],
        )

    def test_public_cli_strict_accepts_the_issue5_input(self):
        text = "設定を読みます。\n\n起動します。\n\n画面を確認します。"
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS_DIR / "yomiyasu_lint.py"), "--json", "--strict"],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["score"], 100)
        self.assertTrue(report["is_clean"])

    def test_public_cli_strict_still_rejects_three_in_one_paragraph(self):
        text = "設定を読みます。\n起動します。\n画面を確認します。"
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS_DIR / "yomiyasu_lint.py"), "--json", "--strict"],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(len(report["findings"]), 1)
        finding = report["findings"][0]
        self.assertEqual(finding["rule"], "sentence_end_repetition")
        self.assertEqual(finding["severity"], "warn")
        self.assertEqual(finding["line"], 3)
        self.assertEqual(finding["snippet"], "画面を確認します。")
        self.assertEqual(set(finding), {"rule", "line", "severity", "message", "snippet"})
        self.assertEqual(report["score"], 95)
        self.assertFalse(report["is_clean"])


if __name__ == "__main__":
    unittest.main()
