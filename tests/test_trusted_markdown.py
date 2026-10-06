"""Known Markdown false positives and positive controls, without model calls."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import yomiyasu_lint
import yomiyasu_diff


class TrustedMarkdownTests(unittest.TestCase):
    def rules(self, text):
        return [item['rule'] for item in yomiyasu_lint.lint_text(text)['findings']]

    def test_code_values_do_not_become_prose(self):
        cases = (
            '値は`😀 正本 仕様が静かに壊れる`です。',
            '値は``a`😀 正本 仕様が静かに壊れる``です。',
            '値は``a\n仕様が静かに壊れる😀``です。',
            '````\n```\n仕様が静かに壊れる😀\n````',
            '~~~~\n~~~\n仕様が静かに壊れる😀\n~~~~',
            '    仕様が静かに壊れる😀',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.rules(text), [])

    def test_escaped_unmatched_and_visible_code_neighbors_remain_prose(self):
        cases = (
            r'\`仕様が静かに壊れる\`',
            '``仕様が静かに壊れる`',
            '`値`仕様が静かに壊れる。',
            '本文です。\n    仕様が静かに壊れる。',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn('metaphor_verb', self.rules(text))

    def test_technical_symbols_are_not_emoji(self):
        self.assertEqual(self.rules('⌘ ⌥ ⌀ ⌈ ⌊ ⏎ ⎋ 🜂 🠀 ♭ ♯ ♔ ♕'), [])
        self.assertEqual(self.rules('© ™ ® # * 1'), [])
        self.assertEqual(self.rules('❤\ufe0e'), [])
        for glyph in ('😀', '1️⃣', '#️⃣', '*️⃣', '🇯🇵', '🇺🇸', '©️'):
            with self.subTest(glyph=glyph):
                self.assertEqual(self.rules('本文です。' + glyph), ['emoji_prohibited'])

    def test_destination_title_and_reference_data_are_not_prose(self):
        cases = (
            '[参照](https://example.invalid/正本/😀)',
            '[参照](https://example.invalid/guide "手触り\n見出し")',
            '[ref]: https://example.invalid/guide\n  "手触り"',
            '[ref]:\n  https://example.invalid/guide\n  "手触り"',
            '<https://example.invalid/正本/😀>',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.rules(text), [])
        self.assertIn('slop_vocabulary', self.rules('[手触り](https://example.invalid)'))
        self.assertIn('slop_vocabulary', self.rules('本文です。\n[ref]: /url "手触り"'))
        self.assertIn('slop_vocabulary', self.rules('[ref]: /url "title" 手触り'))

    def test_only_actual_final_prose_colons_are_reported(self):
        self.assertEqual(self.rules('- 値：``a`b:``'), [])
        self.assertEqual(self.rules('確認事項\\:'), ['trailing_colon'])
        self.assertEqual(self.rules('確認事項 `値`：'), ['trailing_colon'])
        report = yomiyasu_lint.lint_text('本文です。\n確認事項 `値`：')
        self.assertEqual(report['findings'][0]['line'], 2)
        self.assertEqual(report['findings'][0]['snippet'], '確認事項 `値`：')

    def test_inline_code_is_not_a_paragraph_boundary(self):
        text = '第一の説明です。\n`datum\npayload\ndatum`\n第二の説明です。\n第三の説明です。'
        report = yomiyasu_lint.lint_text(text)
        repeats = [item for item in report['findings'] if item['rule'] == 'sentence_end_repetition']
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0]['line'], 6)
        self.assertEqual(repeats[0]['snippet'], '第三の説明です。')
        self.assertEqual(self.rules('第一の説明です。\n\n第二の説明です。\n第三の説明です。'), [])

    def test_table_setext_and_literal_pipe_have_distinct_boundaries(self):
        self.assertEqual(self.rules('| 項目 | 注記 |\n| --- | --- |\n| 手触り | 終端： |'), [])
        self.assertEqual(self.rules('手触りです。\n-'), [])
        self.assertEqual(self.rules('| 手触り：'), ['trailing_colon', 'slop_vocabulary'])
        self.assertIn('slop_vocabulary', self.rules('| 手触り | 項目 | 注記 |\n| --- | --- |'))

    def test_quoted_lists_and_headings_keep_the_lexical_exemption(self):
        for text in ('> - 手触り：', '> 1. 地味に効きます。', '> ## 見出し（詳細）'):
            with self.subTest(text=text):
                self.assertEqual(self.rules(text), [])
        self.assertIn('slop_vocabulary', self.rules('- 手触りを確かめる'))
        self.assertIn('redundant_bracket', self.rules('## 見出し（詳細）'))
        self.assertEqual(self.rules('> 引用😀'), ['emoji_prohibited'])

    def test_valid_html_atoms_are_opaque_and_invalid_tags_stay_visible(self):
        self.assertEqual(self.rules('本文 <audit-item title="手触り">です。'), [])
        self.assertIn('slop_vocabulary', self.rules('本文 <audit-item ^=手触り>です。'))
        self.assertIn('slop_vocabulary', self.rules('本文 <!-- 手触り'))
        self.assertGreater(yomiyasu_lint.analyze_markdown_metrics('<audit-item ^=note> 本文です。')['char_count'], 0)

    def test_linked_images_keep_metadata_and_real_prose_separate(self):
        badge = '[![badge](https://example.invalid/image)](https://example.invalid/link)'
        metrics = yomiyasu_lint.lint_text(badge)['metrics']
        self.assertEqual(metrics['total_lines'], 0)
        self.assertEqual(metrics['char_count'], 0)
        self.assertEqual(self.rules(badge + '終端：'), ['trailing_colon'])
        self.assertEqual(yomiyasu_lint.lint_text(badge + '本文です。')['metrics']['total_lines'], 1)
        self.assertEqual(yomiyasu_lint.lint_text(badge + '[]')['metrics']['total_lines'], 1)

    def test_nested_bold_code_and_destinations_match_in_lint_and_diff(self):
        cases = (
            '**foo,**bar**baz**',
            '**foo「**bar**baz**',
            r'\` `a**「x」**b`',
            '    a**「x」**b',
            '[参照](https://example.invalid/a**「x」**b)',
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(yomiyasu_lint.bold_problems(text), [])
                self.assertEqual(yomiyasu_diff.bold_problems(text), [])
        for text in ('foo\\\n**「x」**bar', 'a***「x」***b', r'\`a**「x」**b\`'):
            with self.subTest(text=text):
                actual = yomiyasu_lint.bold_problems(text)
                self.assertTrue(actual)
                self.assertEqual(actual, yomiyasu_diff.bold_problems(text))
        self.assertEqual(yomiyasu_lint.bold_problems('a***「x」***b')[0]['suggest'], '')

    def test_main_reuses_original_analysis_and_preserves_custom_patterns(self):
        original = yomiyasu_lint.analyze_markdown
        with patch.object(yomiyasu_lint, 'analyze_markdown', wraps=original) as observed:
            report = yomiyasu_lint.lint_text('本文**説明**続き。\n値は``a`b``です。')
        self.assertEqual(report['findings'], [])
        self.assertEqual(observed.call_count, 1)
        import re
        custom = re.compile('custom-token')
        with patch.object(yomiyasu_lint, 'EMOJI_PATTERN', custom):
            self.assertEqual(self.rules('custom-token'), ['emoji_prohibited'])


if __name__ == '__main__':
    unittest.main()
