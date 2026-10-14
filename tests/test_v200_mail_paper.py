"""メール・論文の道具の契約。仕様6章の七例と追加検査・互換性の境界。"""
from pathlib import Path
from unittest import mock
import contextlib
import io
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import yomiyasu_diff as diff
import yomiyasu_lint as lint
import yomiyasu_check as check
import markdown_visibility as visibility


def call(main, args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main([str(a) for a in args])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class SpecExamples(unittest.TestCase):
    def test_four_preserved_examples(self):
        for kind, text in (
            ('mail', 'お手数ですが、10月20日までにご確認いただけますでしょうか。'),
            ('mail', 'それ明日でもいいかも、確認しときます'),
            ('paper', 'この結果は、AとBの間に関係がある可能性を示唆する。'),
            ('paper', '平均は12.4（SD = 3.1, p < .05）であった [3]。'),
        ):
            with self.subTest(text=text):
                result = diff.diff(text, text, doc_type=kind)
                self.assertEqual(result['status'], 'no_change')
                self.assertEqual(result['meaning_risks'], [])
                for key in diff.NEW_REVIEW_SECTIONS:
                    self.assertEqual(result[key]['candidate_count'], 0)
                self.assertEqual(lint.lint_text(text, doc_type=kind)['findings'], [])

    def test_honorific_correction_belongs_to_agent(self):
        # lint は二重敬語や使役の妥当性を判定する規則を持たない。許可・恩恵の文脈判断はエージェント側。
        text = 'ご確認させていただきましたところ、問題ございませんでした。'
        self.assertEqual(lint.lint_text(text, doc_type='mail')['findings'], [])

    def test_hedge_example_uses_existing_speculation_candidate(self):
        result = diff.diff('関係があると考えられる', '関係がある')
        marks = [r for r in result['meaning_risks'] if r['kind'] == 'sentence_type']
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0]['detail']['lost'][0]['kind'], '推量')
        self.assertEqual(result['hedges']['candidate_count'], 0)  # 同じ文に重ねない
        self.assertIn('と考えられる', diff.report(result))

    def test_date_example_is_meaning_risk(self):
        result = diff.diff('10月20日まで', '10月中旬まで')
        self.assertTrue(any(r['kind'] == 'number' for r in result['meaning_risks']))
        self.assertGreater(result['fail_on_meaning_risk_count'], 0)


class DocTypes(unittest.TestCase):
    def test_types_and_mirrors(self):
        self.assertEqual(len(visibility.DOC_TYPES), 12)
        self.assertEqual(visibility.normalize_doc_type(' ＭＡＩＬ '), 'mail')
        for name in ('markdown_visibility.py', 'yomiyasu_lint.py', 'yomiyasu_diff.py', 'yomiyasu_check.py'):
            self.assertEqual((ROOT/'scripts'/name).read_bytes(), (ROOT/'skills/yomiyasu/scripts'/name).read_bytes())
        self.assertEqual((ROOT/'references/lists/hedges.txt').read_bytes(),
                         (ROOT/'skills/yomiyasu/references/lists/hedges.txt').read_bytes())

    def test_mail_filters_only_replies_and_closings(self):
        phrases = ['ご質問ありがとうございます。', '必要なら次に説明します。', 'いかがでしたでしょうか。',
                   'ぜひ試してみてください。', '参考になれば幸いです。']
        for phrase in phrases:
            self.assertTrue(any(f['rule'] == 'meta_filler' for f in lint.lint_text(phrase)['findings']), phrase)
            result = lint.lint_text(phrase, doc_type='mail')
            self.assertFalse(any(f['rule'] == 'meta_filler' for f in result['findings']), phrase)
            self.assertEqual(result['context']['skipped_by_doc_type']['meta_filler'], 1)
        self.assertTrue(any(f['rule'] == 'meta_filler' for f in lint.lint_text('正直に言うと、簡単です。', doc_type='mail')['findings']))
        self.assertEqual(lint.DOC_TYPE_SKIP_RULES['paper'], ())
        for phrase in ['田中様\nお世話になっております。\nよろしくお願いいたします。\n株式会社青空 山田',
                       '恐れ入りますが、ご確認ください。', 'お手数ですが、ご返信ください。']:
            self.assertEqual(lint.lint_text(phrase, doc_type='mail')['findings'], [])

    def test_paper_info_mail_review(self):
        for kind, level in [('paper', 'info'), ('mail', 'review')]:
            result = diff.diff('本当にありがとう！😀', 'ありがとう。', doc_type=kind)
            self.assertTrue(result['tone']['candidates'])
            self.assertTrue(all(c['level'] == level for c in result['tone']['candidates']))
        self.assertEqual(diff.diff('', '', doc_type='paper')['stiffness']['level'], 'info')
        self.assertFalse(lint.lint_text('ありがとう！😀', doc_type='mail')['findings'])

    def test_cli_types_and_japanese_help(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder)/'old.md', Path(folder)/'new.md'
            old.write_text('確認します。', encoding='utf-8')
            new.write_text('確認します。', encoding='utf-8')
            for kind in ('mail', 'paper'):
                for main, args in [(lint.main, [new]), (diff.main, [old, new]),
                                   (check.main, ['run', '--source', old, '--final', new, '--no-record'])]:
                    code, output, error = call(main, args + ['--doc-type', kind, '--json'])
                    self.assertEqual((code, error), (0, ''), output)
                    self.assertIn(kind, output)
            for main, args in [(lint.main, ['-h']), (diff.main, ['-h']), (check.main, ['run', '-h'])]:
                code, output, error = call(main, args)
                self.assertEqual(code, 0)
                self.assertIn('mail（メール・チャット）', output.replace('\n', '').replace(' ', ''))
                self.assertIn('paper（論文・研究レポート）', output.replace('\n', '').replace(' ', ''))


class Hedges(unittest.TestCase):
    def test_new_hedge_and_fail_on(self):
        result = diff.diff('結果は関連を示唆する。', '結果は関連を示す。')
        self.assertEqual(result['hedges']['candidate_count'], 1)
        item = result['hedges']['candidates'][0]
        self.assertEqual((item['old_line'], item['new_line']), (1, 1))
        self.assertEqual(item['detail']['removed'], ['示唆する'])
        self.assertEqual(result['fail_on_meaning_risk_count'], 0)
        self.assertIn('■ 慎重な言い方', diff.report(result))

    def test_same_line_distinct_sentences(self):
        result = diff.diff('関係があると考えられる。結果は関連を示唆する。', '関係がある。結果は関連を示す。')
        self.assertEqual(result['hedges']['candidate_count'], 1)
        self.assertIn('示唆する', result['hedges']['candidates'][0]['old'])

    def test_split_moved_deleted_and_protected(self):
        for old, new in [('対象を調べ、この結果は関連を示唆する。', '対象を調べた。この結果は関連を示唆する。'),
                         ('結果は関連を示唆する。\n別の説明。', '別の説明。\n結果は関連を示唆する。'),
                         ('`示唆する`', '`示す`'), ('# 示唆する\n説明。', '# 示す\n説明。')]:
            self.assertEqual(diff.diff(old,new)['hedges']['candidate_count'], 0, (old, new))
        self.assertEqual(diff.diff('関連を示唆する。', '')['hedges']['candidate_count'], 1)

    def test_list_loader(self):
        def load(data=None, error=None):
            with mock.patch.object(diff, '_LIST_CACHE', {}), mock.patch.object(diff, '_LIST_PROBLEMS', {}):
                opener = mock.mock_open(read_data=data) if error is None else mock.Mock(side_effect=error)
                with mock.patch('builtins.open', opener):
                    items, source = diff._load_list('hedges')
                    info = diff._list_info('hedges')
                    result = diff.diff('関係があるように思える。', '関係がある。')
                return items, source, info, result
        words, source, info, result = load('\ufeff# 一覧\r\n\n ように思える \r\n'.encode('utf-8'))
        self.assertEqual(words, ['ように思える'])
        self.assertEqual(result['hedges']['candidate_count'], 1)
        self.assertEqual(source, 'references/lists/hedges.txt')
        for error in (FileNotFoundError(), NotADirectoryError()):
            words, source, info, _ = load(error=error)
            self.assertEqual(tuple(words), diff.BUILTIN_LISTS['hedges'])
            self.assertIsNone(info['list_problem'])
            self.assertEqual(source, 'builtin')
        for args in ({'data': b'\xff'}, {'error': PermissionError('denied')}):
            words, source, info, result = load(**args)
            self.assertEqual(source, 'builtin')
            self.assertTrue(info['list_problem'])
            self.assertIn('hedges.txt を読めなかった', diff.report(result))
        self.assertEqual(load(b'# empty\n')[0], [])


class ImmutableValues(unittest.TestCase):
    def test_citation_forms_and_number_dedup(self):
        for marker in ['[1]', '[1, 3]', '(山田 2020)', '（山田, 2020）', '(Smith et al., 2019)']:
            for old, new in [('既報 '+marker+'。', '既報。'), ('既報。', '既報 '+marker+'。')]:
                result = diff.diff(old, new)
                self.assertGreater(result['fail_on_meaning_risk_count'], 0, marker)
                self.assertTrue(any(r['kind'] in ('number','citation') for r in result['meaning_risks']))
            self.assertEqual(diff.diff(marker, marker)['meaning_risks'], [])
        result = diff.diff('既報 [1]。', '既報 [2]。')
        self.assertEqual(len([r for r in result['meaning_risks'] if r['kind'] in ('number', 'citation')]), 1)
        ordered = diff.diff('[1, 3]', '[3, 1]')
        self.assertEqual(len([r for r in ordered['meaning_risks'] if r['kind'] in ('number', 'citation')]), 1)
        result = diff.diff('既報 (山田 2020)。', '既報 (佐藤 2020)。')
        self.assertEqual([r['kind'] for r in result['meaning_risks']], ['citation'])
        self.assertEqual(result['fail_on_meaning_risk_count'], 1)
        self.assertIn('引用の印が変わった', diff.report(result))
        self.assertTrue(any(r['kind'] == 'citation' for r in diff.meaning_risks('(山田 2020)', '(佐藤 2020)')))

    def test_not_citations_and_moved(self):
        for marker in ['[注]', '[TODO]', '[文字](https://example.com)', '[1](https://example.com)',
                       '`[1]`', '```\n[1]\n```', '(予算 100)', '（2020）']:
            self.assertFalse(any(r['kind'] == 'citation' for r in diff.diff(marker, '')['meaning_risks']), marker)
        self.assertFalse(any(r['kind'] == 'citation' for r in diff.diff('前 [1]。\n後 [2]。', '後 [2]。\n前 [1]。')['meaning_risks']))

    def test_citation_punctuation_and_repetition(self):
        result = diff.diff('既報 [1, 3]。', '既報 [1] [3]。')
        self.assertTrue(any(r['kind'] == 'citation' for r in result['meaning_risks']))
        result = diff.diff('既報 (山田 2020) (山田 2020)。', '既報 (山田 2020)。')
        self.assertGreater(result['fail_on_meaning_risk_count'], 0)

    def test_addresses_email_and_existing_protected(self):
        for old, new, kind in [('田中様', '佐藤さん', 'addressee'), ('〇〇様', 'さくらさん', 'addressee'), ('田中様、佐藤様', '田中様、鈴木様', 'addressee'), ('株式会社青空様', '', 'addressee'),
                               ('', 'Smithさん', 'addressee'), ('連絡先はa@example.comです。', '連絡先はb@example.comです。', 'email')]:
            result = diff.diff(old, new)
            self.assertEqual([c['subkind'] for c in result['immutable']['candidates']], [kind])
            self.assertEqual(result['fail_on_meaning_risk_count'], 0)
        for text in ['皆さん、おはよう。', '様々な課題。', '逆さんかく。', 'たくさん。', 'お父さん、ありがとう。', 'お疲れ様！', 'Webhook受信のリトライ制御とDLQ仕様', '雲の模様。']:
            self.assertEqual(diff.diff(text, '')['immutable']['candidate_count'], 0)
        for old,new in [('<a@example.com>', '<b@example.com>'), ('https://example.com/a', 'https://example.com/b'),
                        ('[連絡](mailto:a@example.com)', '[連絡](mailto:b@example.com)')]:
            result=diff.diff(old,new)
            self.assertTrue(any(r['kind']=='protected' for r in result['meaning_risks']))
            self.assertEqual(result['immutable']['candidate_count'],0)

    def test_scientific_number_and_unit_gaps(self):
        for old,new in [('12.4 mg','12.4 g'), ('p < .05','p < .01'), ('10:20','10:30'), ('1200円','1300円'), ('p < .05','p > .05'), ('平均は-1.2です。','平均は1.2です。'), ('p < -0.05','p < 0.05')]:
            self.assertGreater(diff.diff(old,new)['fail_on_meaning_risk_count'],0,(old,new))


class ImmutableReviewFixes(unittest.TestCase):
    """反証で見つけた例の直し（同じ値のくり返し、引用でない括弧と書き方だけの違い、範囲のハイフン、宛名、値の検査の数え方）。"""

    def risks(self, old, new):
        return [(r['kind'], r['subkind'], r['old_line'], r['new_line']) for r in diff.diff(old, new)['meaning_risks']]

    def test_repeated_values_stay_on_changed_line(self):
        for sep in ('\n', ''):
            old = sep.join(['手法Aは精度が高い [1]。', '手法Bは速い [2]。', '手法Aは軽い [1]。'])
            new = old.replace('[1]', '[3]', 1)
            result = diff.diff(old, new)
            self.assertEqual(result['fail_on_meaning_risk_count'], 1, sep)
            self.assertEqual([(r['old_line'], r['new_line']) for r in result['meaning_risks']], [(1, 1)])
        result = diff.diff('同じ値は-5だった。\n別の値も-5だった。', '同じ値は5だった。\n別の値も-5だった。')
        self.assertEqual([(r['kind'], r['old_line'], r['new_line'], r['old']) for r in result['meaning_risks']],
                         [('number', 1, 1, '同じ値は-5だった。')])

    def test_not_citation_parentheses_and_notation(self):
        for old, new in [('対応 (Windows 2000)。', '対応 Windows 2000。'), ('規格 (RFC 2119)。', '規格 RFC 2119。'),
                         ('既報 (山田 2020)。', '既報 （山田 2020）。'), ('既報 [1, 2]。', '既報 [1,2]。'),
                         ('既報 [1-3]。', '既報 [1–3]。'), ('既報 （山田, 2020）。', '既報 (山田,  2020)。')]:
            result = diff.diff(old, new)
            self.assertEqual(result['fail_on_meaning_risk_count'], 0, (old, new))
            self.assertFalse(any(r['kind'] == 'citation' for r in result['meaning_risks']), (old, new))
        for marker in ['(Smith, 2019)', '(Smith et al. 2019)', '(Smith & Jones, 2019)']:
            self.assertGreater(diff.diff('既報 (山田 2020)。', '既報 '+marker+'。')['fail_on_meaning_risk_count'], 0, marker)

    def test_range_hyphen_is_not_sign(self):
        for old, new in [('期間は10月-12月。', '期間は10月から12月。'), ('9時-17時。', '9時〜17時。'),
                         ('1万円-2万円。', '1万円〜2万円。'), ('前年比-5%。', '前年比5%減。')]:
            self.assertEqual(diff.diff(old, new)['fail_on_meaning_risk_count'], 0, (old, new))
        self.assertGreater(diff.diff('値は -5 です。', '値は 5 です。')['fail_on_meaning_risk_count'], 0)

    def test_addressee_false_positives(self):
        for old, new in [('今日の当番は田中さん。', '今日の当番は田中さんです。'), ('お婆さん、ありがとう。', ''),
                         ('娘さん、元気？', ''), ('母さん、行ってきます。', '')]:
            self.assertEqual(diff.diff(old, new)['immutable']['candidate_count'], 0, (old, new))
        self.assertEqual(diff.diff('田中さん、お疲れさまです。', '佐藤さん、お疲れさまです。')['immutable']['candidate_count'], 1)

    def test_value_line_counts_meaning_risks_and_order(self):
        result = diff.diff('対応は1行目。\n既報 (山田 2020)。\n値は-5だった。', '対応は1行目。\n既報 (佐藤 2020)。\n値は5だった。')
        self.assertEqual(result['immutable']['meaning_risk_count'], 2)
        self.assertEqual(diff.detector_summary(result, 'immutable'), '意味が変わる恐れ 2件')
        lines = [r['old_line'] for r in result['meaning_risks']]
        self.assertEqual(lines, sorted(lines))
        self.assertEqual(diff.detector_summary(diff.diff('田中様', '佐藤様'), 'immutable'), '候補1件')
        self.assertEqual(diff.detector_summary(diff.diff('同じ。', '同じ。'), 'immutable'), '候補なし')


class Politeness(unittest.TestCase):
    def test_mail_only_and_two_directions(self):
        old,new='ご確認いただきます。内容は確かです。','確認する。内容は確かである。'
        for a,b in [(old,new),(new,old)]:
            result=diff.diff(a,b,doc_type='mail')['politeness']
            self.assertEqual(result['candidate_count'],2)
        for kind in (None,'paper','article'):
            self.assertEqual(diff.diff(old,new,doc_type=kind)['politeness']['candidate_count'],0)

    def test_inflections_longest_match(self):
        text='させていただきました。いただけますか。くださった。申し上げました。存じます。'
        info=diff.diff(text,text,doc_type='mail')['politeness']['metrics']['old']
        self.assertEqual(info['honorific_count'],5)
        self.assertEqual(set(info['honorifics'].values()),{1})

    def test_threshold_and_no_denominator(self):
        for count,expected in [(5,1),(6,0)]:
            old='確認いただきます。'+'確認します。'*(count-1)
            new='確認します。'*count
            self.assertEqual(diff.diff(old,new,doc_type='mail')['politeness']['candidate_count'],expected)
        self.assertEqual(diff.diff('確認しとく','確認しときます',doc_type='mail')['politeness']['candidate_count'],0)
        self.assertEqual(diff.diff('`いただく`','`行う`',doc_type='mail')['politeness']['candidate_count'],0)


class CheckIntegration(unittest.TestCase):
    def test_record_summary_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); old,new=root/'old.md',root/'new.md'; state=root/'state'
            old.write_text('田中様\n結果は関連を示唆する。確認いただきます。',encoding='utf-8')
            new.write_text('佐藤様\n結果は関連を示す。確認する。',encoding='utf-8')
            code,out,err=call(check.main,['run','--source',old,'--final',new,'--state-dir',state,'--doc-type','mail','--json'])
            self.assertEqual((code,err),(0,''),out)
            data=json.loads(out)
            for key in diff.NEW_REVIEW_SECTIONS:
                self.assertIn(key+'_check',data)
            records=list(state.rglob('attempt-*.json'))
            record=next(json.loads(p.read_text()) for p in records if 'checks' in json.loads(p.read_text()))
            self.assertIn('references/lists/hedges.txt', record['tools'])
            summary=next(e['summary'] for e in record['checks'] if e['name']=='diff')
            for key in diff.NEW_REVIEW_SECTIONS:
                self.assertGreater(summary[key+'_candidate_count'],0)
            code,out,err=call(check.main,['verify','--final',new,'--source',old,'--state-dir',state,'--replay','--json'])
            self.assertEqual((code,err),(0,''),out)

    def test_fail_on_citation_only(self):
        with tempfile.TemporaryDirectory() as folder:
            old,new=Path(folder)/'old.md',Path(folder)/'new.md'
            for a,b,expected in [('既報 (山田 2020)。','既報 (佐藤 2020)。',1),
                                 ('関連を示唆する。','関連を示す。',0),('田中様','佐藤さん',0)]:
                old.write_text(a,encoding='utf-8');new.write_text(b,encoding='utf-8')
                for main,args in [(diff.main,[old,new]),(check.main,['run','--source',old,'--final',new,'--no-record'])]:
                    code,out,err=call(main,args+['--fail-on','meaning-risk'])
                    self.assertEqual(code,expected,out)
                    self.assertEqual(call(main,args)[0],0)


if __name__ == '__main__':
    unittest.main()
