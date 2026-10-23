"""G15 段2: 出典、照合の該当行、任意の穴候補、記録の再現。すべて合成の文。"""
import ast
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import yomiyasu_check as check
import yomiyasu_diff as diff
sys.path.insert(0, str(ROOT / 'tests'))
from portable import paced_limit, timing_clock  # noqa: E402


class G15CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=str(ROOT), prefix='.g15-test-')
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.env = dict(os.environ, TMPDIR=str(self.folder), PYTHONDONTWRITEBYTECODE='1')
        for key in ('YOMIYASU_STATE_DIR', 'YOMIYASU_SESSION', 'CODEX_THREAD_ID'):
            self.env.pop(key, None)
        self.state = self.folder / 'state'
        self.script = ROOT / 'scripts/yomiyasu_check.py'

    def write(self, name, text):
        path = self.folder / name
        path.write_bytes(text.encode('utf-8'))
        return str(path)

    def cli(self, *args, **kw):
        stdin = kw.get('stdin')
        return subprocess.run([sys.executable, '-B', str(self.script)] + list(args),
                              input=stdin.encode() if stdin is not None else None,
                              capture_output=True, cwd=str(self.folder), env=self.env, timeout=60)

    def json_run(self, *args, **kw):
        result = self.cli('run', *args, '--state-dir', str(self.state), '--json', **kw)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return json.loads(result.stdout)

    def test_labels_all_input_routes_and_replay(self):
        material = ('\ufeff\r\n<<<yomiyasu:material 利用者の発言（3回目の依頼）>>>\t\r\n保持は30日。\r\n'
                    '<<<yomiyasu:material 出力 git diff（retry.py）>>>\r\n+WAIT = 0.5\r\n')
        final = '保存は30日、間隔は0.5秒、上限は3回です。\n'
        f = self.write('final.txt', final)
        m = self.write('material.txt', material)
        for route in ('file', 'dash', 'stdin'):
            with self.subTest(route=route):
                if route == 'stdin':
                    result = self.json_run('--stdin', '--new-run', stdin=material+'<<<yomiyasu:final>>>\r\n'+final)
                else:
                    result = self.json_run('--material', m if route == 'file' else '-', '--final', f, '--new-run',
                                           stdin=material if route == 'dash' else None)
                record = json.loads(Path(result['record_path']).read_text(encoding='utf-8'))
                labels = ['利用者の発言（3回目の依頼）', '出力 git diff（retry.py）']
                self.assertEqual([r['label'] for r in record['inputs']['materials']], labels)
                self.assertEqual([r['label'] for r in result['materials']['sources']], labels)
                for entry in record['inputs']['materials']:
                    body = (self.state / entry['snapshot']).read_text(encoding='utf-8')
                    self.assertNotIn('<<<', body)
                    self.assertNotIn('3回目', body)
                three = next(i for i in result['materials']['items'] if i['text'] == '3回')
                self.assertEqual(three['classification'], 'not_in_sources')
                replay = self.cli('verify', '--final', f, '--state-dir', str(self.state), '--run-id', result['run_id'], '--replay', '--json')
                self.assertEqual(replay.returncode, 0, replay.stdout.decode()+replay.stderr.decode())
                self.assertEqual(json.loads(replay.stdout)['replay'], 'ok')

    def test_bad_markers_never_write_records(self):
        f = self.write('final.txt', '最大3回です。\n')
        bad = ['<<<yomiyasu:materials 3回目>>>', '<<<yomiyasu:materia>>>',
               '<<<YOMIYASU:material>>>', ' <<<yomiyasu:material>>>',
               '<<<yomiyasu:material '+('あ'*201)+'>>>', '<<<yomiyasu:material a>>>b>>>',
               '<<<yomiyasu:material', '<<<yomiyasu:original>>>']
        for marker in bad:
            for prefix in ('', '普通の資料\n', '<<<yomiyasu:material 一番目>>>\n保持は30日。\n'):
                body = prefix+marker+'\n保持は5日。\n'
                m = self.write('material.txt', body)
                for route in ('file', 'dash'):
                    with self.subTest(marker=marker, prefix=prefix, route=route):
                        result = self.cli('run', '--material', m if route == 'file' else '-', '--final', f,
                                          '--state-dir', str(self.state), stdin=body if route == 'dash' else None)
                        self.assertEqual(result.returncode, 2, result.stdout)
                        self.assertIn(b'<<<yomiyasu:material', result.stderr)
                        self.assertFalse(self.state.exists())

    def test_marker_limits_unlabelled_and_plain_material(self):
        for label in (None, 'a'*200):
            marker = '<<<yomiyasu:material'+(' '+label if label else '')+'>>>\t'
            pieces, error = check._split_stdin((marker+'\n値は30日。\n<<<yomiyasu:final>>>\n保存します。').encode(), True)
            self.assertIsNone(error)
            self.assertEqual(pieces[0][2], label)
        item = check._Input('material', 1, None, b'plain\n<<<yomiyasu:material label>>>\nbody\n')
        blocks, problem = check._split_material(item, 1)
        self.assertIsNone(problem)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].data, item.data)
        self.assertIsNone(blocks[0].label)

    def test_gaps_output_fail_on_and_record_replay(self):
        source = self.write('source.txt', '処理を変えました。\n')
        final = self.write('final.txt', '再試行の間隔を短くしました。\n')
        plain = self.cli('run', '--source', source, '--final', final, '--no-record')
        flagged = self.cli('run', '--source', source, '--final', final, '--no-record', '--fact-gaps', '--fail-on=meaning-risk')
        self.assertEqual(flagged.returncode, plain.returncode)
        a, b = plain.stdout.decode().splitlines(), flagged.stdout.decode().splitlines()
        self.assertEqual(a[1], b[1])
        self.assertIn('、事実の穴の候補1件', b[2])
        self.assertIn('■ 事実の穴の候補', flagged.stdout.decode())
        result = self.json_run('--source', source, '--final', final, '--fact-gaps')
        record_path = Path(result['record_path']); record = json.loads(record_path.read_text(encoding='utf-8'))
        self.assertEqual(record['fact_gaps'], result['fact_gaps'])
        self.assertTrue(record['options']['fact_gaps'])
        self.assertEqual(record['required_checks'], ['lint', 'diff'])
        replay = self.cli('verify', '--final', final, '--state-dir', str(self.state), '--replay', '--json')
        self.assertEqual(replay.returncode, 0, replay.stdout.decode())
        self.assertNotIn('fact_gaps', json.loads(replay.stdout))
        record['fact_gaps']['items'][0]['sentence'] = '書き換え'
        record_path.write_bytes(json.dumps(record).encode('utf-8'))
        bad = self.cli('verify', '--final', final, '--state-dir', str(self.state), '--json')
        self.assertEqual(json.loads(bad.stdout)['status'], 'invalid_record')
        record['record_digest'] = check._record_digest(record)
        record_path.write_bytes(json.dumps(record).encode('utf-8'))
        bad = self.cli('verify', '--final', final, '--state-dir', str(self.state), '--replay', '--json')
        self.assertEqual(json.loads(bad.stdout)['status'], 'not_reproducible')

    def test_gaps_doctype_and_display_limits(self):
        source = self.write('source.txt', '処理を変えました。')
        final = self.write('final.txt', '間隔を短くしました。\n'*25)
        for kind in ('essay', 'promo', 'formal', 'paper'):
            result = self.cli('run', '--source', source, '--final', final, '--doc-type', kind, '--fact-gaps', '--no-record')
            self.assertEqual(result.returncode, 0, result.stderr)
            text = result.stdout.decode()
            if kind in ('essay', 'promo'):
                self.assertNotIn('■ 事実の穴の候補', text)
                self.assertIn('事実の穴の候補（種類 '+kind+' では出していません）', text.splitlines()[2])
            else:
                self.assertIn('この種類では補わず', text)
                section = text.split('■ 事実の穴の候補')[1].split('\n\n')[0]
                self.assertEqual(section.count('\n- 後'), 10)
                self.assertIn('ほか15件', section)
        result = self.json_run('--source', source, '--final', final, '--fact-gaps')
        self.assertEqual(result['fact_gaps']['count'], 25)
        self.assertEqual(len(result['fact_gaps']['items']), 20)
        final = self.write('final.txt', '間隔を短くしました。\n'*24)
        again = self.json_run('--source', source, '--final', final, '--fact-gaps')
        self.assertEqual(again['fix_count'], 1)
        self.assertEqual(again['fact_gaps']['count'], 24)

    def test_external_list_change_is_tool_changed(self):
        """--fact-gaps を付けた記録は、ほかの4つの一覧と同じく、記録のあとで fact-gaps.txt を変えると verify も
        verify --replay も tool_changed で、1行目が一覧の名前を言う（前は通常の verify が executed のままで、
        --replay だけが not_reproducible だった）。付けなかった記録は、fact-gaps.txt を変えても executed。"""
        scripts = self.folder / 'scripts'; shutil.copytree(str(ROOT/'scripts'), str(scripts))
        self.script = scripts/'yomiyasu_check.py'
        lists = self.folder/'references/lists'; lists.mkdir(parents=True)
        pattern = lists/'fact-gaps.txt'; pattern.write_bytes('change\t短くしました\n'.encode('utf-8'))
        source = self.write('source.txt', '処理を変えました。')
        final = self.write('final.txt', '間隔を短くしました。')
        plain_final = self.write('plain.txt', '処理の間隔を短くしました。')
        result = self.json_run('--source', source, '--final', final, '--fact-gaps')
        self.assertEqual(result['fact_gaps']['count'], 1)
        self.assertIn('references/lists/fact-gaps.txt', json.loads(Path(result['record_path']).read_text(encoding='utf-8'))['tools'])
        plain = self.json_run('--source', source, '--final', plain_final, '--new-run')
        self.assertNotIn('references/lists/fact-gaps.txt', json.loads(Path(plain['record_path']).read_text(encoding='utf-8'))['tools'])
        pattern.write_bytes('# 候補が同じでも一覧の変更を検出する\nchange\t短くしました\n'.encode('utf-8'))
        expected = ('記録のあとで、検査に使う語の一覧（references/lists/fact-gaps.txt）が変わりました。'
                    'yomiyasu_check.py run をもう一度実行してください。')
        for extra in ([], ['--replay']):
            with self.subTest(extra=extra):
                process = self.cli('verify', '--final', final, '--state-dir', str(self.state), '--json', *extra)
                self.assertEqual(process.returncode, 1, process.stdout.decode())
                data = json.loads(process.stdout)
                self.assertEqual(data['status'], 'tool_changed')
                self.assertIn({'code': 'tool_changed', 'detail': 'references/lists/fact-gaps.txt'}, data['problems'])
                self.assertEqual(data['message'], expected)
                text = self.cli('verify', '--final', final, '--state-dir', str(self.state), *extra)
                self.assertEqual(text.stdout.decode().splitlines()[0], expected)
        ordinary = self.cli('verify', '--final', plain_final, '--state-dir', str(self.state), '--json')
        self.assertEqual(json.loads(ordinary.stdout)['status'], 'executed')

    def test_managed_limit_result_has_the_same_keys_as_run(self):
        """start で登録した原稿が上限を超えたときの run --json も、ふつうの run と同じく fact_gaps のキーを持つ（値は null）。"""
        source = self.write('source.txt', '処理は大幅に速くなりました。\n')
        final = self.write('final.txt', '処理はかなり速くなりました。\n')
        started = self.cli('start', '--source', source, '--state-dir', str(self.state), '--max-runs', '1', '--json')
        self.assertEqual(started.returncode, 0, started.stderr.decode())
        normal = self.json_run('--source', source, '--final', final, '--fact-gaps')
        self.assertEqual(normal['fact_gaps']['count'], 1)
        blocked = self.cli('run', '--source', source, '--final', final, '--fact-gaps', '--state-dir', str(self.state), '--json')
        self.assertEqual(blocked.returncode, 1, blocked.stderr.decode())
        limit = json.loads(blocked.stdout)
        self.assertEqual(limit['reason'], 'run_limit')
        self.assertIn('fact_gaps', limit)
        self.assertIsNone(limit['fact_gaps'])

    def test_managed_limit_does_not_look_for_gaps(self):
        """管理の上限で止まる run は、事実の穴の候補を探さない（探す処理が誤っても、上限の結果を返す）。"""
        source = self.write('source.txt', '処理は大幅に速くなりました。\n')
        final = self.write('final.txt', '処理はかなり速くなりました。\n')
        started = self.cli('start', '--source', source, '--state-dir', str(self.state), '--max-runs', '1', '--json')
        self.assertEqual(started.returncode, 0, started.stderr.decode())
        self.json_run('--source', source, '--final', final, '--fact-gaps')
        worker = ("import importlib.util, sys\n"
                  "spec = importlib.util.spec_from_file_location('_check_under_test', sys.argv[1])\n"
                  "check = importlib.util.module_from_spec(spec)\n"
                  "spec.loader.exec_module(check)\n"
                  "def broken(*args, **kwargs):\n"
                  "    raise RuntimeError('fact_gaps was called')\n"
                  "check._diff_module().fact_gaps = broken\n"
                  "sys.exit(check.main(sys.argv[2:]))\n")
        blocked = subprocess.run([sys.executable, '-B', '-c', worker, str(self.script), 'run', '--source', source,
                                  '--final', final, '--fact-gaps', '--state-dir', str(self.state), '--json'],
                                 capture_output=True, cwd=str(self.folder), env=self.env, timeout=60)
        self.assertEqual(blocked.returncode, 1, blocked.stderr.decode())
        self.assertNotIn('fact_gaps was called', blocked.stderr.decode())
        limit = json.loads(blocked.stdout)
        self.assertEqual(limit['reason'], 'run_limit')
        self.assertIsNone(limit['fact_gaps'])

    def test_labelled_extract_may_equal_the_final_in_a_rewrite(self):
        """推敲で、出典つきの区切りの抜き書きが最終稿と同じ本文でも止めない（根拠の文どおりに短い原稿を直した場合）。
        出典のない資料と、新規作成は今までどおり2。"""
        source = self.write('source.txt', '毎日2時に削除されます。\n')
        final = self.write('final.txt', '毎日3時に削除されます。\n')
        labelled = self.write('final.material.txt', '<<<yomiyasu:material 利用者の発言（2回目の依頼）>>>\n毎日3時に削除されます。\n')
        plain = self.write('plain.txt', '毎日3時に削除されます。\n')
        bare = self.write('bare.txt', '<<<yomiyasu:material>>>\n毎日3時に削除されます。\n')
        result = self.json_run('--source', source, '--final', final, '--material', labelled, '--fact-gaps', '--new-run')
        self.assertEqual(result['mode'], 'rewrite')
        self.assertIsNotNone(result['materials'])
        stdin = ('<<<yomiyasu:original>>>\n毎日2時に削除されます。\n'
                 '<<<yomiyasu:material 利用者の発言（2回目の依頼）>>>\n毎日3時に削除されます。\n'
                 '<<<yomiyasu:final>>>\n毎日3時に削除されます。\n')
        self.assertEqual(self.json_run('--stdin', '--new-run', stdin=stdin)['mode'], 'rewrite')
        refused = (['--source', source, '--final', final, '--material', plain],
                   ['--source', source, '--final', final, '--material', bare],
                   ['--final', final, '--material', labelled])
        for args in refused:
            with self.subTest(args=[Path(x).name for x in args]):
                process = self.cli('run', *args, '--state-dir', str(self.folder / 'refused'))
                self.assertEqual(process.returncode, 2, process.stderr.decode())
                self.assertIn(check._SAME_AS_FINAL_ERROR, process.stderr.decode())
                self.assertFalse((self.folder / 'refused').exists())

    def test_byte_and_json_compatibility_fixed_cases(self):
        rows = json.loads((ROOT/'tests/fixtures/g15_unchanged_outputs.json').read_text(encoding='utf-8'))
        for row in rows:
            self.write('source.txt', row['source']); self.write('final.txt', row['final'])
            for scripts in (ROOT/'scripts', ROOT/'skills/yomiyasu/scripts'):
                with self.subTest(tool=row['tool'], case=row['case'], material=bool(row.get('material')), scripts=str(scripts.relative_to(ROOT))):
                    command = [sys.executable, '-B', str(scripts/('yomiyasu_'+row['tool']+'.py'))]+row['args']
                    stdin = row['stdin'].encode() if row['stdin'] else None
                    p = subprocess.run(command, input=stdin, capture_output=True, cwd=str(self.folder), env=self.env)
                    self.assertEqual(p.returncode, row['code'])
                    self.assertEqual(p.stderr, row['stderr'].encode())
                    def without_material(text):
                        return re.sub(r'■ 資料との照合[^\n]*\n(?:[^\n]+\n)*', '', text)
                    if row.get('material'):
                        self.assertEqual(without_material(p.stdout.decode()).encode(), without_material(row['stdout']).encode())
                    else:
                        self.assertEqual(p.stdout, row['stdout'].encode())
                    p = subprocess.run(command+['--json'], input=stdin, capture_output=True, cwd=str(self.folder), env=self.env)
                    data = json.loads(p.stdout)
                    def strip_added(obj):
                        if isinstance(obj, dict):
                            return {k:strip_added(v) for k,v in obj.items() if k not in ('label','found_in','evidence','bare_in','values','fact_gaps','kept_marks')}
                        if isinstance(obj,list): return [strip_added(v) for v in obj]
                        return obj
                    self.assertEqual(strip_added(data), row['json'])


class G15Ground(unittest.TestCase):
    def number(self, result, text):
        return next(i for i in result['items'] if i['kind']=='number' and i['text']==text)

    def test_evidence_indices_limits_and_names(self):
        material = '\n間隔は1.0sです。'+('長'*80)+'\n間隔は1秒です。\n間隔は1秒です。\n間隔は1秒です。'
        r = diff.ground('間隔は1秒です。PostgreSQLです。', [material, 'Postgre SQLです。間隔は1secsです。'], '', ['設定','記録'])
        n = self.number(r,'1秒')
        self.assertEqual(n['found_in'], [1,2])
        self.assertEqual([i[:2] for i in n['evidence']], [[1,2],[1,3],[1,4]])
        self.assertEqual(len(n['evidence'][0][2]),60)
        name = next(i for i in r['items'] if i['kind']=='name')
        self.assertEqual(name['evidence'], [[2,1,'Postgre SQLです。間隔は1secsです。']])
        original = diff.ground('間隔は1秒です。',[material],'間隔は1秒です。')
        self.assertNotIn('evidence',self.number(original,'1秒'))

    def test_bare_settings_are_only_hints(self):
        for line,value in (('+RETRY_INTERVAL_SECONDS = 0.5','0.5秒'),('-WAIT = 1.0','1秒'),('limit: 3 # 回数','3回'),('EXIT_ROLLBACK_FAILED = 4','4回')):
            r=diff.ground('値は'+value+'です。',[line])
            n=self.number(r,value)
            self.assertEqual(n['classification'],'not_in_sources')
            self.assertEqual(n['bare_in'],[[1,1,line]])
            self.assertGreater(r['meaning_risk_count'],0)
        for line,value in (('time = 02:00:16','16秒'),('date: 2026-10-01','2026回'),('path: 3/file','3回'),('version=1.2.0','1.2秒'),('request_id=job_13','13回'),('retry_wait=0.50','0.5秒'),('wait = 3sec','3回'),('build = 3-beta','3回')):
            self.assertNotIn('bare_in', self.number(diff.ground('値は'+value+'です。',[line]),value),line)

    def test_certainty_values_and_old_count(self):
        words=('予定','たぶん','多分','おそらく','恐らく','きっと','と思う','と思います','気がする','記憶では','方向で','検討して','まだ決まって','確かめていない')
        for word in words:
            final='保存は30日です。別の公開は'+word+'。'
            r=diff.ground(final,['保存は30日、'+word+'。'])
            item=next(i for i in r['items'] if i['classification']=='dropped_certainty')
            self.assertEqual(item['values'],['30日'])
            self.assertEqual(r['meaning_risk_count'],0)
        r=diff.ground('保存は30日です。',['たぶん30日です。'],'保存は30日です。')
        self.assertEqual(r['candidate_count'],0)
        for final in ('保存はたぶん30日です。','保存は30日でしょう。'):
            r=diff.ground(final,['たぶん30日です。'])
            self.assertFalse(any(i.get('values') for i in r['items']))


class G15Gaps(unittest.TestCase):
    def test_prototype_positive_and_keep_cases(self):
        cases=json.loads((ROOT/'tests/fixtures/g15_gaps_cases.json').read_text(encoding='utf-8'))
        for row in cases['flag']:
            with self.subTest(text=row['text']): self.assertGreater(diff.fact_gaps(row['text'])['count'],0)
        for row in cases['keep']:
            with self.subTest(text=row['text']): self.assertEqual(diff.fact_gaps(row['text'])['count'],0)

    def test_intentional_omission_vagueness_and_resolutions(self):
        for prefix in ('詳細は省きますが、','詳細は省略し、','社名は伏せ、','社外秘のため、','値は非公開ですが、','別途お伝えしますが、','詳細は控え、','数社で','数件について','複数の場所で','今後、','これからも、','引き続き、'):
            self.assertEqual(diff.fact_gaps(prefix+'性能を大幅に改善しました。')['count'],0,prefix)
        for suffix in ('改善してまいります。','改善していきます。','改善していきたい。','改善を続けます。','改善に向けて努力します。'):
            self.assertEqual(diff.fact_gaps('信頼性の土台づくりを'+suffix)['count'],0,suffix)
        for text in ('# 大幅に改善しました。','> 大幅に改善しました。','```\n大幅に改善しました。\n```','| 大幅に改善しました。 |\n|---|', '大幅に改善しました。時間は3秒です。','仮に失敗すれば、大幅に減らします。','たぶん大幅に減らします。','本体より短くしました。', '「大幅に改善しました。」と書かれています。', '`大幅に改善しました。` と表示します。', '性能を大幅に改善した場合には利用します。', '大幅に改善されることはありません。'):
            self.assertEqual(diff.fact_gaps(text)['count'],0,text)

    def test_summary_limits_and_shape(self):
        text=('あ'*100+'間隔を短くしました。\n')*25
        r=diff.fact_gaps(text)
        self.assertEqual(r['count'],25); self.assertEqual(r['by_kind'],{'change':25})
        self.assertEqual(len(r['items']),20); self.assertEqual(len(r['items'][0]['sentence']),80)
        self.assertTrue(check._fact_gaps_shape(r))
        for kind in ('essay','promo'):
            self.assertEqual(diff.fact_gaps(text,kind),{'count':0,'skipped':kind,'by_kind':{},'items':[]})

    def test_candidate_total_is_independent_of_fail_on(self):
        ctx=check._Context(); ctx.fact_gaps=diff.fact_gaps('間隔を短くしました。')
        self.assertEqual(ctx.candidate_total(),1)
        ctx.fact_gaps=None; self.assertEqual(ctx.candidate_total(),0)

    def test_sixty_thousand_chars_under_half_second(self):
        text = ('再試行の間隔を短くしました。\n' * 4000)[:60000]
        # 0.5秒の上限は、Windows の遅い機械では基準の処理の遅さの比で延ばす（portable.paced_limit）。時間は CPU 時間で測る
        clock = timing_clock()
        started = clock()
        result = diff.fact_gaps(text)
        elapsed = clock() - started
        self.assertEqual(len(text), 60000)
        self.assertGreater(result['count'], 1000)
        limit, detail = paced_limit(0.5, elapsed)
        self.assertLess(elapsed, limit, detail)

    def test_python38_and_mirrors(self):
        for name in ('yomiyasu_check.py','yomiyasu_diff.py'):
            content=(ROOT/'scripts'/name).read_bytes()
            self.assertEqual(content,(ROOT/'skills/yomiyasu/scripts'/name).read_bytes())
            ast.parse(content,feature_version=(3,8))


if __name__=='__main__':
    unittest.main()
