"""G8 H3–H5, H11, H12: optional check registration, confined to temporary homes."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / 'scripts' / 'yomiyasu_check.py'


class ManagedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / '.yomiyasu'
        self.env = dict(os.environ, HOME=str(self.root), YOMIYASU_STATE_DIR=str(self.state))
        for name in ('YOMIYASU_SESSION', 'CODEX_THREAD_ID', 'CLAUDE_PROJECT_DIR'):
            self.env.pop(name, None)
        self.source = self.root / 'draft.md'
        self.final = self.root / 'final.md'
        self.source.write_text('担当者は原稿を確認しました。\n', encoding='utf-8')
        self.final.write_text('担当者が原稿を確認しました。\n', encoding='utf-8')

    def cli(self, *args, **kwargs):
        result = subprocess.run([sys.executable, '-B', str(CHECK)] + list(args), cwd=str(self.root),
                                env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, kwargs.get('code', 0), result.stderr + result.stdout)
        return result

    def start(self, *args):
        return json.loads(self.cli('start', '--source', str(self.source), '--json', *args).stdout)

    def run_check(self, *args, **kwargs):
        return json.loads(self.cli('run', '--source', str(self.source), '--final', str(self.final),
                                   '--json', *args, **kwargs).stdout)

    def entry(self, run_id):
        return json.loads((self.state / 'armed' / (run_id + '.json')).read_text())

    def update(self, run_id, **changes):
        path = self.state / 'armed' / (run_id + '.json')
        entry = self.entry(run_id)
        entry.update(changes)
        path.write_text(json.dumps(entry), encoding='utf-8')


class StartTests(ManagedCase):
    def test_h3_management_help_is_japanese(self):
        arguments = {
            'start': ('--source', '--final', '--run-id', '--session', '--host',
                      '--max-stop-blocks', '--max-runs', '--deadline-min', '--state-dir', '--json'),
            'export': ('--final', '--run-id', '--source', '--state-dir', '--json'),
            'end': ('--run-id', '--source', '--state-dir', '--json'),
        }
        for command, names in arguments.items():
            with self.subTest(command=command):
                result = self.cli(command, '--help')
                self.assertEqual(result.stderr, '')
                self.assertNotIn('show this help message', result.stdout)
                self.assertNotIn('options:', result.stdout)
                for text in names + ('-h, --help', 'このヘルプを表示して終わります。',
                                     '入力:', 'オプション:', '使い方: yomiyasu_check.py ' + command):
                    self.assertIn(text, result.stdout)
                error = self.cli(command, '--unknown', code=2)
                self.assertIn('yomiyasu_check.py ' + command + ': error:', error.stderr)
                self.assertIn('引数の誤りです。', error.stderr)
        self.assertFalse(self.state.exists())

    def test_h3_start_shape_and_superseded(self):
        result = self.start('--session', 'A', '--host', 'codex')
        entry = self.entry(result['run_id'])
        self.assertEqual(entry['session_id'], 'A')
        self.assertEqual(entry['limits'], dict(max_stop_blocks=2, max_runs=3, deadline_min=30))
        self.assertRegex(result['status_line'], r'^yomiyasu-check: started(?: [a-z_]+=\S+)+$')
        start = json.loads(Path(result['start_path']).read_text())
        self.assertEqual(start['format'], 'yomiyasu-check-start')
        self.assertEqual((self.state / entry['targets']['source']['snapshot']).read_bytes(), self.source.read_bytes())
        self.assertEqual(len(list((self.state / 'index' / 'starts').glob('*/*'))), 1)
        self.assertEqual(Path(result['armed_path']).stat().st_mode & 0o777, 0o600)
        self.start()
        self.assertEqual(self.entry(result['run_id'])['status_reason'], 'superseded')

    def test_h3_invalid_arguments_leave_no_state(self):
        cases = [[], ['--source', '-'], ['--source', 'missing'], ['--source', str(self.source), '--max-runs', '0'],
                 ['--source', str(self.source), '--max-stop-blocks', '6'],
                 ['--source', str(self.source), '--deadline-min', '241'], ['--sour', str(self.source)]]
        for args in cases:
            with self.subTest(args=args):
                self.cli('start', *args, code=2)
                self.assertFalse(self.state.exists())
        self.source.write_bytes(b'\xff')
        self.cli('start', '--source', str(self.source), code=2)
        self.assertFalse(self.state.exists())
        self.source.write_bytes(b'a' * (2 * 1024 * 1024 + 1))
        self.cli('start', '--source', str(self.source), code=2)
        self.assertFalse(self.state.exists())

    def test_h3_duplicate_id_and_unexpanded_session(self):
        result = self.start('--run-id', 'fixed', '--session', '${SESSION}')
        before = {str(p): p.read_bytes() for p in self.state.rglob('*') if p.is_file()}
        self.cli('start', '--source', str(self.source), '--run-id', 'fixed', code=2)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.state.rglob('*') if p.is_file()})
        self.assertIsNone(self.entry(result['run_id'])['session_id'])

    def test_h4_link_and_in_place_snapshot(self):
        started = self.start('--session', 'A')
        run = self.run_check()
        self.assertEqual(run['run_id'], started['run_id'])
        record = json.loads(Path(run['record_path']).read_text())
        self.assertEqual(record['host']['armed_by'], 'armed/' + run['run_id'] + '.json')
        self.assertEqual(record['host']['session'], 'A')
        self.source.write_text('担当者が確認しました。\n', encoding='utf-8')
        self.final = self.source
        run = self.run_check()
        record = json.loads(Path(run['record_path']).read_text())
        self.assertEqual(record['inputs']['source']['sha256'], started['source']['sha256'])
        self.assertNotEqual(record['inputs']['source']['sha256'], record['inputs']['final']['sha256'])

    def test_h4_hash_copy_and_ambiguous_registration(self):
        first = self.start()
        copy = self.root / 'copy.md'
        copy.write_bytes(self.source.read_bytes())
        original = self.source
        self.source = copy
        self.assertEqual(self.run_check()['run_id'], first['run_id'])
        second = self.start()
        run = self.run_check('--new-run')
        self.assertNotIn(run['run_id'], [first['run_id'], second['run_id']])
        self.final = self.root / 'different-final.md'
        self.final.write_text('確認を終えました。\n', encoding='utf-8')
        run = self.run_check()
        self.assertNotIn(run['run_id'], [first['run_id'], second['run_id']])
        record = json.loads(Path(run['record_path']).read_text())
        self.assertIsNone(record['host']['armed_by'])
        self.source = original

    def test_h5_run_limit_and_deadline(self):
        result = self.start()
        for _ in range(3):
            self.run_check()
        folder = self.state / 'runs' / result['run_id']
        before = sorted(p.name for p in folder.iterdir())
        blocked = self.run_check(code=1)
        self.assertEqual(blocked['reason'], 'run_limit')
        self.assertEqual(before, sorted(p.name for p in folder.iterdir()))
        self.assertEqual(self.entry(result['run_id'])['log'][-1]['result'], 'unverified:run_limit')
        result = self.start()
        self.update(result['run_id'], deadline='2000-01-01T00:00:00Z')
        self.assertEqual(self.run_check(code=1)['reason'], 'deadline')
        self.assertEqual(list((self.state / 'runs' / result['run_id']).glob('attempt-*.json')), [])

    def test_h3_source_lock_cannot_collide_with_run_id(self):
        import hashlib
        digest = hashlib.sha256(os.path.normcase(os.path.realpath(str(self.source))).encode('utf-8')).hexdigest()
        self.start('--run-id', 'source-' + digest[:48])
        self.assertEqual(list((self.state / 'armed').glob('*.lock')), [])

    def test_h3_parallel_starts_keep_one_active_registration(self):
        processes = [subprocess.Popen([sys.executable, '-B', str(CHECK), 'start', '--source', str(self.source), '--json'],
                                     cwd=str(self.root), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(4)]
        for process in processes:
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, err)
            self.assertEqual(json.loads(out)['status'], 'started')
        entries = [json.loads(p.read_text()) for p in (self.state / 'armed').glob('*.json')]
        self.assertEqual(sum(e['status'] == 'active' for e in entries), 1)
        self.assertEqual(sum(e['status_reason'] == 'superseded' for e in entries), 3)

    def test_h5_parallel_runs_reserve_attempt_before_checks(self):
        run_id = self.start('--max-runs', '1')['run_id']
        processes = [subprocess.Popen([sys.executable, '-B', str(CHECK), 'run', '--source', str(self.source),
                                      '--final', str(self.final), '--json'], cwd=str(self.root), env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(6)]
        statuses = []
        for process in processes:
            out, err = process.communicate(timeout=20)
            self.assertIn(process.returncode, (0, 1), err)
            statuses.append(json.loads(out)['status'])
        self.assertEqual(statuses.count('executed'), 1)
        self.assertEqual(statuses.count('unverified'), 5)
        records = list((self.state / 'runs' / run_id).glob('attempt-*.json'))
        attempts = [p for p in records if re.fullmatch(r'attempt-[0-9]+\.json', p.name)]
        self.assertEqual(len(attempts), 1)
        self.assertTrue(attempts[0].read_bytes())

    def test_h5_in_place_growth_does_not_bypass_the_deadline_result(self):
        run_id = self.start()['run_id']
        self.source.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        self.final = self.source
        self.update(run_id, deadline='2000-01-01T00:00:00Z')
        self.assertEqual(self.run_check(code=1)['reason'], 'deadline')

    def test_h5_left_lock_is_reclaimed_by_commands(self):
        # A lock left by a hook that was cut off is taken over after 10 seconds, not an internal error (3).
        run_id = self.start()['run_id']
        lock = self.state / 'armed' / (run_id + '.lock')
        for command in ('run', 'end'):
            with self.subTest(command=command):
                lock.touch()
                os.utime(str(lock), (time.time() - 7, time.time() - 7))
                begin = time.monotonic()
                if command == 'run':
                    self.assertEqual(self.run_check()['status'], 'executed')
                else:
                    self.cli('end', '--run-id', run_id)
                self.assertGreater(time.monotonic() - begin, 2)
                self.assertFalse(lock.exists())

    def test_h5_left_empty_reservations_do_not_use_up_runs(self):
        # Empty attempt files of runs killed before cleanup count only while they may still be running.
        run_id = self.start()['run_id']
        self.run_check()
        folder = self.state / 'runs' / run_id
        old = time.time() - 11 * 60
        for number in (2, 3):
            path = folder / 'attempt-{}.json'.format(number)
            path.touch()
            os.utime(str(path), (old, old))
        self.assertEqual(self.run_check()['status'], 'executed')
        (folder / 'attempt-9.json').touch()
        self.assertEqual(self.run_check(code=1)['reason'], 'run_limit')

    def test_h11_export_exact_read_only_and_idempotent(self):
        run = self.run_check()
        self.assertFalse((self.state / 'armed').exists())
        result = json.loads(self.cli('export', '--final', str(self.final), '--json').stdout)
        export = Path(result['export_path'])
        self.assertEqual(export.read_bytes(), self.final.read_bytes())
        self.assertEqual(export.stat().st_mode & 0o777, 0o444)
        before = export.stat().st_mtime_ns
        self.cli('export', '--final', str(self.final))
        self.assertEqual(before, export.stat().st_mtime_ns)
        self.final.write_text('変更しました。', encoding='utf-8')
        result = json.loads(self.cli('export', '--final', str(self.final), '--json', code=1).stdout)
        self.assertIsNone(result['export_path'])
        self.assertEqual(len(list((self.state / 'exports').glob('*/*'))), 1)
        self.cli('export', '--final', '-', code=2)

    def test_h12_end_id_source_and_limits_inactive(self):
        for option in ('--run-id', '--source'):
            result = self.start('--max-runs', '1')
            self.run_check()
            value = result['run_id'] if option == '--run-id' else str(self.source)
            self.cli('end', option, value)
            self.assertEqual(self.entry(result['run_id'])['status'], 'ended')
            self.run_check()
            self.cli('end', option, value, code=1)

    def test_verify_quick_matches_cli_without_lint_diff_import(self):
        self.run_check()
        worker = '''import importlib.util,json,sys
s=importlib.util.spec_from_file_location('check',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=m.verify_quick(sys.argv[2],final_path=sys.argv[3]);assert not any(x.endswith(('yomiyasu_lint','yomiyasu_diff')) for x in sys.modules)
print(json.dumps(r))'''
        for data in (self.final.read_bytes(), b'changed'):
            self.final.write_bytes(data)
            cli = json.loads(self.cli('verify', '--final', str(self.final), '--json', code=0 if data != b'changed' else 1).stdout)
            r = subprocess.run([sys.executable, '-B', '-c', worker, str(CHECK), str(self.state), str(self.final)],
                               cwd=str(self.root), env=self.env, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 0, r.stderr)
            quick = json.loads(r.stdout)
            self.assertEqual(quick['status'], cli['status'])
            self.assertEqual(quick['problems'], cli['problems'])


if __name__ == '__main__':
    unittest.main()
