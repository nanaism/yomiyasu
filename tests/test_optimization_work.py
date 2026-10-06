"""Observable work reductions with the real matching and bold algorithms."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import yomiyasu_diff
import yomiyasu_lint


def alignment_work(original, rewrite):
    base = yomiyasu_diff.difflib.SequenceMatcher
    counts = {'indexes': 0, 'ratios': 0}

    class CountedMatcher(base):
        def set_seq2(self, sequence):
            if sequence is not self.b:
                counts['indexes'] += 1
            return super().set_seq2(sequence)

        def ratio(self):
            counts['ratios'] += 1
            return super().ratio()

    with patch.object(yomiyasu_diff.difflib, 'SequenceMatcher', CountedMatcher):
        output = yomiyasu_diff.ending_changes(original, rewrite)
    return counts, output


class OptimizationWorkTests(unittest.TestCase):
    def test_full_diff_reuses_each_inputs_sentence_analysis(self):
        original = '設定を確認します。結果を保存します。'
        rewrite = '設定を確認してください。結果を保存してください。'
        with patch.object(yomiyasu_diff, 'ending_units', wraps=yomiyasu_diff.ending_units) as parsed:
            output = yomiyasu_diff.diff(original, rewrite)
        self.assertEqual(
            [(row['orig'], row['rewrite'], row['rewrite_kind'])
             for row in output['endings']['changes']],
            [('設定を確認します。', '設定を確認してください。', '依頼'),
             ('結果を保存します。', '結果を保存してください。', '依頼')],
        )
        self.assertLessEqual(parsed.call_count, 2)

    def test_repeated_exact_sentences_do_not_build_matcher_indexes(self):
        text = '担当者は設定を確認します。\n' * 18
        counts, output = alignment_work(text, text)
        self.assertEqual(output, [])
        self.assertEqual(counts, {'indexes': 0, 'ratios': 0})

    def test_provably_disjoint_candidates_need_no_exact_ratio(self):
        original = '\n'.join(chr(0x4E00 + i) * 15 + 'です。' for i in range(18))
        rewrite = '\n'.join(chr(0x5200 + i) * 15 + 'してください。' for i in range(18))
        counts, output = alignment_work(original, rewrite)
        self.assertEqual(output, [])
        self.assertEqual(counts['ratios'], 0)

    def test_correspondence_reuses_each_rewrite_index(self):
        original = '\n'.join(f'担当者{i}は設定{i}を確認します。' for i in range(18))
        rewrite = '\n'.join(f'担当者{i}は設定{i}を確認してください。' for i in range(18))
        counts, output = alignment_work(original, rewrite)
        self.assertEqual(len(output), 18)
        self.assertLessEqual(counts['indexes'], 18)
        self.assertEqual(output[0]['orig'], '担当者0は設定0を確認します。')
        self.assertEqual(output[-1]['rewrite'], '担当者17は設定17を確認してください。')

    def test_independent_bold_repairs_reuse_the_original_analysis(self):
        # Concatenating these fragments creates valid cross-fragment strong
        # matches. Separate paragraphs are forty actual independent failures.
        text = '\n\n'.join(['文**「語句」**続き'] * 40)
        original = yomiyasu_lint.analyze_markdown
        analyzed = []

        def counted(value, *args, **kwargs):
            analyzed.append(value)
            return original(value, *args, **kwargs)

        with patch.object(yomiyasu_lint, 'analyze_markdown', counted):
            findings = yomiyasu_lint.bold_problems(text)
        self.assertEqual(len(findings), 40)
        self.assertEqual(analyzed.count(text), 1)
        self.assertLessEqual(len(analyzed), 41)
        self.assertEqual(findings[0]['how'], 'かっこの内側だけを太字にする')

    def test_concatenated_fragments_are_not_forty_broken_pairs(self):
        # Actual GFM renders 39 intervening strong regions for this source.
        # Keep this adjudicated correctness delta separate from a speed claim.
        findings = yomiyasu_lint.bold_problems('文**「語句」**続き ' * 40)
        self.assertEqual(len(findings), 1)


if __name__ == '__main__':
    unittest.main()
