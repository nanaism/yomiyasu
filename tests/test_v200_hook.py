"""G8 H1,H2,H6–H10,H12–H20: real subprocess hooks, no host or network calls."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import unittest

from test_v200_check_start import ManagedCase, ROOT, CHECK
from portable import paced_limit

HOOK = ROOT / 'scripts' / 'yomiyasu_hook.py'
HOSTS = ('claude-code', 'codex')
EVENTS = ('UserPromptExpansion', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop', 'SessionEnd', 'Unknown')


class HookTests(ManagedCase):
    def hook(self, event='Stop', host='claude-code', session='A', raw=None, script=HOOK, **data):
        payload = dict(hook_event_name=event, session_id=session, cwd=str(self.root))
        payload.update(data)
        result = subprocess.run([sys.executable, '-B', str(script), '--host', host],
                                input=raw if raw is not None else json.dumps(payload).encode('utf-8'),
                                cwd=str(self.root), env=self.env, capture_output=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'')
        return result.stdout.decode('utf-8')

    def bound(self, host='claude-code', final=True, **kwargs):
        args = ['--session', 'A', '--host', host]
        if final:
            args += ['--final', str(self.final)]
        for key, value in kwargs.items():
            args += ['--' + key.replace('_', '-'), str(value)]
        return self.start(*args)['run_id']

    def pre(self, command, host='claude-code', **kwargs):
        return self.hook('PreToolUse', host, tool_name='Bash', tool_input={'command': command}, **kwargs)

    def test_h1_no_registration_no_import_no_writes(self):
        # A check that raises on import proves the no-armed fast path does not load it.
        scripts = self.root / 'scripts'
        scripts.mkdir()
        copied = scripts / 'yomiyasu_hook.py'
        shutil.copyfile(str(HOOK), str(copied))
        (scripts / 'yomiyasu_check.py').write_bytes("raise RuntimeError('must not import')\n".encode('utf-8'))
        for existing in (False, True):
            if existing:
                self.state.mkdir()
            before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
            for host in HOSTS:
                for event in EVENTS:
                    self.assertEqual(self.hook(event, host, script=copied, prompt='日本語の会話です。',
                                               tool_name='Bash', tool_input={'command': 'ls'}), '')
            self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def test_h2_bad_input_is_silent(self):
        for host in HOSTS:
            for raw in (b'', b'{', b'[]', b'null', b'\xff', b' ' * (4 * 1024 * 1024 + 1),
                        b'{"hook_event_name":"Stop"}', b'{"session_id":4}'):
                self.assertEqual(self.hook(host=host, raw=raw), '')
            self.assertEqual(self.hook(host=host, session=''), '')
        self.assertFalse(self.state.exists())

    def test_h6_stop_lifecycle_both_hosts(self):
        for host in HOSTS:
            with self.subTest(host=host):
                run_id = self.bound(host, final=False)
                self.assertEqual(self.hook(host=host), '')
                self.assertEqual(self.entry(run_id)['counters']['stop_blocks'], 0)
                self.run_check()
                self.assertEqual(self.hook(host=host), '')
                self.assertEqual(self.entry(run_id)['status'], 'checked')
                self.final.write_bytes('最終稿を変更しました。\n'.encode('utf-8'))
                for remaining in (1, 0):
                    response = json.loads(self.hook(host=host, stop_hook_active=True))
                    self.assertEqual(response['decision'], 'block')
                    self.assertIn('あと {} 回'.format(remaining), response['reason'])
                    self.assertNotIn('投稿', response['reason'])
                response = json.loads(self.hook(host=host))
                self.assertEqual(set(response), {'systemMessage'})
                self.assertEqual(self.entry(run_id)['status_reason'], 'stop_limit')
                self.assertEqual(self.hook(host=host), '')
                self.assertEqual(self.entry(run_id)['counters']['stop_blocks'], 2)
                self.final.write_bytes('担当者が原稿を確認しました。\n'.encode('utf-8'))

    def test_h6_in_place_no_record_and_missing_files(self):
        run_id = self.bound(final=False)
        self.source.write_bytes('原稿をその場で直しました。\n'.encode('utf-8'))
        response = json.loads(self.hook())
        self.assertIn('--source draft.md --final draft.md', response['reason'])
        self.source.unlink()
        self.assertEqual(self.hook(), '')
        self.assertEqual(self.entry(run_id)['log'][-1]['result'], 'source_missing')
        self.source.write_bytes('復元した原稿。'.encode('utf-8'))
        run_id = self.bound()
        self.final.unlink()
        self.assertEqual(self.hook(), '')
        self.assertEqual(self.entry(run_id)['log'][-1]['result'], 'final_missing')

    def test_h6_stop_retains_verify_semantics_for_large_final(self):
        self.bound()
        self.final.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        cli = json.loads(self.cli('verify', '--final', str(self.final), '--json', code=1).stdout)
        self.assertEqual(cli['status'], 'no_record')
        response = json.loads(self.hook())
        self.assertEqual(response['decision'], 'block')
        self.assertIn('検査記録がありません', response['reason'])

    def test_h7_deadline_matching_and_unmatched(self):
        for host in HOSTS:
            run_id = self.bound(host)
            self.run_check()
            self.update(run_id, deadline='2000-01-01T00:00:00Z')
            self.assertEqual(self.hook(host=host), '')
            self.assertEqual(self.entry(run_id)['status'], 'checked')
            self.final.write_bytes('期限を過ぎてから変わった本文。'.encode('utf-8'))
            response = json.loads(self.hook(host=host))
            self.assertIn('期限30分', response['systemMessage'])
            self.assertNotIn('decision', response)
            self.assertEqual(self.hook(host=host), '')
            self.assertEqual(self.entry(run_id)['status_reason'], 'deadline')
            self.final.write_bytes('担当者が原稿を確認しました。\n'.encode('utf-8'))

    def test_h8_session_and_host_binding(self):
        run_id = self.start()['run_id']
        self.assertEqual(self.hook('UserPromptSubmit'), '')
        self.assertEqual(self.entry(run_id)['session_id'], 'A')
        before = self.entry(run_id)
        self.assertEqual(self.hook(session='B'), '')
        self.assertEqual(self.pre('gh pr create --body-file draft.md', session='B'), '')
        self.assertEqual(self.entry(run_id), before)
        run_id = self.start('--host', 'codex')['run_id']
        self.hook('UserPromptSubmit')
        self.assertIsNone(self.entry(run_id)['session_id'])
        self.hook('PostToolUse', 'codex')
        self.assertEqual(self.entry(run_id)['host'], 'codex')
        run_id = self.start()['run_id']
        self.update(run_id, deadline='2000-01-01T00:00:00Z')
        self.hook('UserPromptSubmit')
        self.assertIsNone(self.entry(run_id)['session_id'])

    def test_h9_registration_routes_and_deduplication(self):
        for command in ('yomiyasu', 'yomiyasu:yomiyasu'):
            output = self.hook('UserPromptExpansion', command_name=command, command_args='@draft.md を直して')
            if command == 'yomiyasu':
                self.assertIn('原稿 draft.md を登録しました', output)
            else:
                self.assertEqual(output, '')
        self.assertEqual(self.hook('UserPromptSubmit', prompt='/yomiyasu:yomiyasu draft.md を直して'), '')
        self.assertEqual(len(list((self.state / 'armed').glob('*.json'))), 1)
        for event, fields in [('UserPromptExpansion', dict(command_name='other', command_args='draft.md')),
                              ('UserPromptExpansion', dict(command_name='yomiyasu', command_args='missing.md')),
                              ('UserPromptSubmit', dict(prompt='yomiyasu で draft.md を直して')),
                              ('PreToolUse', dict(tool_name='Skill', tool_input={'skill': 'yomiyasu', 'args': 'draft.md'}))]:
            self.assertEqual(self.hook(event, **fields), '')
        for host, prompt in [('claude-code', '/yomiyasu draft.md'), ('codex', '$yomiyasu draft.md'),
                             ('codex', '直して $yomiyasu:yomiyasu draft.md')]:
            self.cli('end', '--source', str(self.source))
            self.assertIn('登録しました', self.hook('UserPromptSubmit', host, prompt=prompt))
        self.assertEqual(len(list((self.state / 'armed').glob('*.json'))), 4)

    def test_h9_quoted_paths_first_file_only_and_invalid_utf8(self):
        paths = []
        for n in range(7):
            path = self.root / ('draft {}.md'.format(n))
            path.write_bytes('原稿です。'.encode('utf-8'))
            paths.append(path)
        output = self.hook('UserPromptExpansion', command_name='yomiyasu', command_args=' '.join(shlex.quote(p.name) for p in paths))
        self.assertEqual(output.count('登録しました'), 1)
        self.assertIn('原稿 draft 0.md を登録しました', output)
        entries = [json.loads(p.read_text(encoding='utf-8')) for p in (self.state / 'armed').glob('*.json')]
        self.assertEqual([os.path.basename(e['targets']['source']['path']) for e in entries], ['draft 0.md'])
        bad = self.root / 'bad.md'
        bad.write_bytes(b'\xff')
        self.assertEqual(self.hook('UserPromptExpansion', command_name='yomiyasu', command_args='bad.md'), '')

    def test_h9_only_the_manuscript_is_registered(self):
        # The final, notes and references named later in the request are not registered.
        notes = self.root / 'notes.md'
        notes.write_bytes('言い回しのメモ。'.encode('utf-8'))
        output = self.hook('UserPromptExpansion', command_name='yomiyasu',
                           command_args='draft.md を直して、結果は final.md に上書きして')
        self.assertIn('原稿 draft.md を登録しました', output)
        self.assertNotIn('final.md', output)
        self.cli('end', '--source', str(self.source))
        output = self.hook('UserPromptExpansion', command_name='yomiyasu',
                           command_args='「draft.md」を直して final.md に書いて')
        self.assertIn('原稿 draft.md を登録しました', output)
        self.cli('end', '--source', str(self.source))
        output = self.hook('UserPromptSubmit', 'codex', prompt='$yomiyasu draft.md を直して。言い回しは notes.md を参考に')
        self.assertIn('原稿 draft.md を登録しました', output)
        active = [json.loads(p.read_text(encoding='utf-8')) for p in (self.state / 'armed').glob('*.json')]
        active = [e for e in active if e['status'] != 'ended']
        self.assertEqual([os.path.basename(e['targets']['source']['path']) for e in active], ['draft.md'])
        self.assertEqual(self.pre('gh issue comment 3 --body-file notes.md', 'codex'), '')
        self.assertEqual(self.hook('Stop', 'codex'), '')

    def test_h8_shared_state_does_not_bind_other_projects(self):
        # A state folder shared by YOMIYASU_STATE_DIR: a terminal start in project A is not bound by B's session.
        project_a, project_b = self.root / 'a', self.root / 'b'
        for folder in (project_a, project_b):
            folder.mkdir()
            (folder / '.git').mkdir()
        source = project_a / 'draft.md'
        source.write_bytes('担当者は原稿を確認しました。\n'.encode('utf-8'))
        result = subprocess.run([sys.executable, '-B', str(CHECK), 'start', '--source', 'draft.md', '--json'],
                                cwd=str(project_a), env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        run_id = json.loads(result.stdout)['run_id']
        source.write_bytes('担当者が原稿を確認しました。\n'.encode('utf-8'))
        for event in ('UserPromptSubmit', 'PreToolUse', 'Stop'):
            self.assertEqual(self.hook(event, session='B', cwd=str(project_b), tool_name='Bash',
                                       tool_input={'command': 'ls'}), '')
        entry = self.entry(run_id)
        self.assertIsNone(entry['session_id'])
        self.assertEqual([row['result'] for row in entry['log']], ['started'])
        nested = project_a / 'docs'
        nested.mkdir()
        self.assertEqual(self.hook('UserPromptSubmit', session='A', cwd=str(nested)), '')
        self.assertEqual(self.entry(run_id)['session_id'], 'A')

    def test_h10_gh_by_absolute_path(self):
        for host in HOSTS:
            if host == 'codex':
                self.cli('end', '--source', str(self.source))
            self.bound(host)
            for command in ('/opt/homebrew/bin/gh pr create --body-file draft.md',
                            'env X=1 /usr/local/bin/gh issue comment 1 --body-file draft.md'):
                with self.subTest(command=command, host=host):
                    response = json.loads(self.pre(command, host))
                    self.assertEqual(response['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(self.pre('/opt/homebrew/bin/ghq get x', 'codex'), '')

    def test_h10_publication_bodies_and_exports_both_hosts(self):
        other = self.root / 'other.md'
        other.write_bytes('別の用件です。'.encode('utf-8'))
        for host in HOSTS:
            run_id = self.bound(host)
            self.run_check()
            export = json.loads(self.cli('export', '--final', str(self.final), '--json').stdout)['export_path']
            self.assertEqual(self.pre('gh pr create --body-file ' + shlex.quote(export), host), '')
            self.final.write_bytes('検査のあとで変えた最終稿。'.encode('utf-8'))
            for command in ('gh pr create --body-file other.md', 'git commit -m 文', 'ls', 'curl example.invalid',
                            'gh pr create --body "別の投稿です"', 'gh pr create --body-file - <<EOF\n別件\nEOF'):
                self.assertEqual(self.pre(command, host), '')
            for command in ('gh pr create --body-file final.md', 'gh issue comment 1 -F final.md',
                            'gh pr review 1 --body=' + shlex.quote(self.final.read_text(encoding='utf-8')),
                            ['bash', '-lc', 'gh release create v1 --notes-file final.md'],
                            ['gh', 'pr', 'edit', '--body-file', 'final.md']):
                output = self.pre(command, host)
                decision = json.loads(output)['hookSpecificOutput']
                self.assertEqual(decision['hookEventName'], 'PreToolUse')
                self.assertEqual(decision['permissionDecision'], 'deny')
                self.assertNotIn('allow', output)
            output = self.hook('PreToolUse', host, tool_name='mcp__service__post',
                               tool_input={'payload': {'body': self.final.read_text(encoding='utf-8')}})
            self.assertEqual(json.loads(output)['hookSpecificOutput']['permissionDecision'], 'deny')
            command = 'gh pr create --body "$(cat final.md)"'
            self.assertEqual(json.loads(self.pre(command, host))['hookSpecificOutput']['permissionDecision'],
                             'ask' if host == 'claude-code' else 'deny')
            for command in ('gh pr create --body $(cat final.md)',
                            'gh pr create --body $(ls | cat final.md)'):
                self.assertEqual(json.loads(self.pre(command, host))['hookSpecificOutput']['permissionDecision'],
                                 'ask' if host == 'claude-code' else 'deny')
            command = 'gh pr create --body-file - <<EOF\nfinal.md\nEOF'
            self.assertEqual(json.loads(self.pre(command, host))['hookSpecificOutput']['permissionDecision'],
                             'ask' if host == 'claude-code' else 'deny')
            self.final.write_bytes('担当者が原稿を確認しました。\n'.encode('utf-8'))

    def test_h10_body_file_reason_uses_registered_final_path(self):
        other = self.root / 'copy.md'
        for host in HOSTS:
            for explicit_final in (True, False):
                with self.subTest(host=host, explicit_final=explicit_final):
                    self.final.write_bytes('担当者が原稿を確認しました。\n'.encode('utf-8'))
                    run_id = self.bound(host, final=explicit_final)
                    self.run_check()
                    export = json.loads(self.cli('export', '--final', str(self.final), '--json').stdout)['export_path']
                    self.assertEqual(self.pre('gh pr create --body-file final.md', host), '')
                    # Body matching still accepts an equivalent text with different line endings.
                    self.final.write_bytes(self.final.read_bytes().replace(b'\n', b'\r\n'))
                    self.assertEqual(self.pre('gh pr create --body-file final.md', host), '')
                    self.final.write_bytes('検査のあとで変えた最終稿。'.encode('utf-8'))
                    other.write_bytes(self.final.read_bytes())
                    for path, status in (('final.md', 'final_changed'), ('copy.md', 'wrong_file')):
                        decision = json.loads(self.pre('gh pr create --body-file ' + path, host))['hookSpecificOutput']
                        self.assertEqual(decision['permissionDecision'], 'deny')
                        self.assertIn('（' + status + '）', decision['permissionDecisionReason'])
                        self.assertEqual(self.entry(run_id)['log'][-1]['result'], 'deny:' + status)
                    self.assertEqual(self.pre('gh pr create --body-file ' + shlex.quote(export), host), '')

    def test_h10_fixed_command_list_api_and_shell_segments(self):
        self.bound()
        for prefix, flag in [('gh pr ' + op, '--body-file') for op in ('create', 'edit', 'comment', 'review')] + [
                            ('gh issue ' + op, '--body-file') for op in ('create', 'edit', 'comment')] + [
                            ('gh release ' + op, '--notes-file') for op in ('create', 'edit')]:
            self.assertEqual(json.loads(self.pre(prefix + ' ' + flag + '=final.md'))['hookSpecificOutput']['permissionDecision'], 'deny')
        for command in ('gh api repos/a/b/issues -F body=@final.md',
                        'gh api repos/a/b/issues --field=text=@final.md',
                        'gh api repos/a/b/issues -f ' + shlex.quote('notes=' + self.final.read_text(encoding='utf-8')),
                        'gh api repos/a/b/issues --input final.md',
                        'ls; env X=1 command gh pr create --body-file final.md',
                        'ls && sudo gh pr create --body-file final.md',
                        'ls\ngh pr create --body-file final.md'):
            self.assertIn('hookSpecificOutput', json.loads(self.pre(command)), command)
        for command in ('gh pr view --body-file final.md', 'gh api something -f unrelated=final.md',
                        'gh api something --input other.json',
                        'gh pr create --body-file missing.md; cat final.md',
                        'gh pr create --body other; echo "$(cat final.md)"',
                        'gh pr create --body "$(cat other.md)"; cat final.md',
                        'gh pr create --body $(cat other.md) && cat final.md'):
            self.assertEqual(self.pre(command), '')
        self.assertEqual(self.hook('PreToolUse', tool_name='mcp__service__post',
                                  tool_input={'a': {'b': {'body': self.final.read_text(encoding='utf-8')}}}), '')

    def test_h12_session_end_and_ended_exclusion(self):
        for host in HOSTS:
            run_id = self.bound(host)
            self.assertEqual(self.hook('SessionEnd', host, session='B'), '')
            self.assertEqual(self.entry(run_id)['status'], 'active')
            self.assertEqual(self.hook('SessionEnd', host), '')
            self.assertEqual(self.entry(run_id)['status_reason'], 'session_end')
            self.assertEqual(self.hook(host=host), '')
            self.assertEqual(self.pre('gh pr create --body-file final.md', host), '')

    def test_h13_no_body_in_any_event_or_errors(self):
        marker = 'ZQX本文の目印ZQX'
        self.source.write_bytes((marker + ' 原文です。').encode('utf-8'))
        self.final.write_bytes((marker + ' 最終稿です。').encode('utf-8'))
        outputs = []
        for host in HOSTS:
            run_id = self.bound(host)
            self.run_check()
            self.final.write_bytes((marker + ' 検査後の変更です。').encode('utf-8'))
            for event in EVENTS:
                outputs.append(self.hook(event, host, prompt='/yomiyasu draft.md ' + marker,
                                         command_name='yomiyasu', command_args='draft.md ' + marker,
                                         tool_name='mcp__post', tool_input={'body': self.final.read_text(encoding='utf-8')},
                                         transcript_path=marker, last_assistant_message=marker))
            self.assertEqual(self.hook(host=host), '')
        (self.state / 'armed' / 'bad.json').write_bytes(('{"secret":' + marker).encode('utf-8'))
        outputs.append(self.hook())
        (self.state / 'armed' / 'bad.json').unlink()
        for text in outputs + [p.read_text(encoding='utf-8') for p in (self.state / 'armed').glob('*') if p.is_file()] + [
                (self.state / 'hook-errors.log').read_text(encoding='utf-8')]:
            self.assertNotIn(marker, text)
            self.assertNotIn('ZQX\\u672c', text)

    def test_h14_latency(self):
        measurements = []
        for host in HOSTS:
            samples = []
            for _ in range(7):
                begin = time.perf_counter()
                self.hook(host=host)
                samples.append(time.perf_counter() - begin)
            median = statistics.median(samples)
            # 上限の秒数は、Windows の遅い機械では基準の処理の遅さの比で延ばす（portable.paced_limit）
            limit, detail = paced_limit(0.3, median)
            self.assertLess(median, limit, detail)
            measurements.append('{} fast={:.4f}s'.format(host, median))
        for host in HOSTS:
            self.bound(host)
            self.run_check()
            samples = []
            for _ in range(5):
                begin = time.perf_counter()
                self.hook(host=host)
                samples.append(time.perf_counter() - begin)
            limit, detail = paced_limit(1.0, max(samples))
            self.assertLess(max(samples), limit, detail)
            measurements.append('{} Stop median={:.4f}s max={:.4f}s'.format(host, statistics.median(samples), max(samples)))
        print('\nH14 Python {}: {}'.format(sys.version.split()[0], ', '.join(measurements)), flush=True)

    def test_h15_parallel_stop_pretool_and_stale_lock(self):
        run_id = self.bound()
        processes = []
        for _ in range(20):
            for event in ('Stop', 'PreToolUse'):
                data = dict(hook_event_name=event, session_id='A', cwd=str(self.root),
                            tool_name='Bash', tool_input={'command': 'gh pr create --body-file final.md'})
                p = subprocess.Popen([sys.executable, '-B', str(HOOK), '--host', 'claude-code'],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     cwd=str(self.root), env=self.env)
                p.stdin.write(json.dumps(data).encode('utf-8'))
                p.stdin.close()
                p.stdin = None
                processes.append((event, p))
        blocks, notices, denies = 0, 0, 0
        for event, p in processes:
            out, err = p.communicate(timeout=25)
            self.assertEqual(p.returncode, 0)
            self.assertEqual(err, b'')
            if out:
                result = json.loads(out)
                blocks += result.get('decision') == 'block'
                notices += 'systemMessage' in result
                denies += 'hookSpecificOutput' in result
        self.assertEqual((blocks, notices, denies), (2, 1, 20))
        entry = self.entry(run_id)
        self.assertEqual(entry['counters']['stop_blocks'], 2)
        self.assertEqual(entry['status'], 'unverified')
        self.assertEqual(sum(row['result'].startswith('deny:') for row in entry['log']), 20)
        self.assertLessEqual(len(entry['log']), 50)
        lock = self.state / 'armed' / (run_id + '.lock')
        lock.touch()
        os.utime(str(lock), (time.time() - 11, time.time() - 11))
        self.hook('SessionEnd')
        self.assertFalse(lock.exists())
        self.assertEqual(self.entry(run_id)['status'], 'ended')

    def test_h16_config_only_stdout_and_version(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        for host in HOSTS:
            result = subprocess.run([sys.executable, '-B', str(HOOK), '--print-config', host],
                                    cwd=str(self.root), env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=5)
            self.assertEqual(result.returncode, 0)
            config = json.loads(result.stdout)
            expected = {'UserPromptSubmit', 'PreToolUse', 'Stop', 'SessionEnd',
                        'UserPromptExpansion' if host == 'claude-code' else 'PostToolUse'}
            self.assertEqual(set(config['hooks']), expected)
            for event, rows in config['hooks'].items():
                handler = rows[0]['hooks'][0]
                self.assertEqual(handler['type'], 'command')
                command = [handler['command']] + handler['args'] if host == 'claude-code' else shlex.split(handler['command'])
                self.assertEqual(command, [sys.executable, '-B', str(HOOK), '--host', host])
                expected_timeout = {'Stop': 30, 'PreToolUse': 10, 'PostToolUse': 10,
                                    'SessionEnd': 1 if host == 'claude-code' else 2}.get(event, 5)
                self.assertEqual(handler['timeout'], expected_timeout)
            self.assertNotIn('Skill', result.stdout)
            self.assertNotIn('allow', result.stdout)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))
        result = subprocess.run([sys.executable, '-B', str(HOOK), '--version'], cwd=str(self.root),
                                env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=5)
        self.assertEqual(result.stdout, 'yomiyasu_hook.py 2.5.0\n')

    def test_h16b_help_and_print_config_errors(self):
        """--help に引数、環境変数、終了コードがあり、--print-config の値の誤りだけが終了コード2。
        フックとして呼ぶ形（--host）と知らない引数は、ホストを止めないよう今までどおり何も出さずに0。"""
        def run(*args):
            return subprocess.run([sys.executable, '-B', str(HOOK)] + list(args), cwd=str(self.root), env=self.env,
                                  capture_output=True, text=True, encoding='utf-8', timeout=10, stdin=subprocess.DEVNULL)
        before = sorted(str(p) for p in self.root.rglob('*'))
        shown = run('--help')
        self.assertEqual((shown.returncode, shown.stderr), (0, ''))
        for text in ('使い方: yomiyasu_hook.py --host claude-code|codex [--state-dir DIR]', '終了コード:',
                     'YOMIYASU_STATE_DIR', 'CLAUDE_PROJECT_DIR', 'hook-errors.log', '知らない引数も無視します'):
            self.assertIn(text, shown.stdout)
        self.assertEqual(run('-h').stdout, shown.stdout)
        for args in (['--print-config', 'cursor'], ['--print-config']):
            with self.subTest(args=args):
                result = run(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertEqual(result.stderr, '--print-config には claude-code か codex を渡してください。\n')
        for args in (['--bogus'], ['--host'], ['--host', 'cursor'], ['--host', 'claude-code', '--bogus']):
            with self.subTest(args=args):
                result = run(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))

    def test_h18_no_hook_declarations(self):
        self.assertEqual(list(ROOT.rglob('SKILL.md')), [ROOT / 'skills' / 'yomiyasu' / 'SKILL.md'])
        front = (ROOT / 'skills' / 'yomiyasu' / 'SKILL.md').read_text(encoding='utf-8').split('---')[1]
        self.assertNotIn('hooks:', front)
        for path in (ROOT / 'hooks', ROOT / 'skills' / 'yomiyasu' / 'hooks', ROOT / '.codex-plugin'):
            self.assertFalse(path.exists())
        manifests = list((ROOT / '.claude-plugin').glob('*.json')) + list((ROOT / 'skills' / 'yomiyasu' / '.codex-plugin').glob('*.json'))
        for path in manifests:
            self.assertNotIn('hooks', json.loads(path.read_text(encoding='utf-8')))

    def test_h19_python38_syntax_and_stdlib(self):
        for path in (CHECK, HOOK):
            tree = ast.parse(path.read_text(encoding='utf-8'), feature_version=(3, 8))
            self.assertIsInstance(tree, ast.Module)
        text = HOOK.read_text(encoding='utf-8')
        for forbidden in ('import requests', 'import socket', 'subprocess.', 'urlopen', 'removeprefix(', 'functools.cache', 'import fcntl'):
            self.assertNotIn(forbidden, text)

    def test_h20_corrupt_unreadable_busy_lock_and_log_redaction(self):
        run_id = self.bound()
        path = self.state / 'armed' / (run_id + '.json')
        valid = path.read_bytes()
        for bad in (b'{broken secret', b'', b'[]'):
            path.write_bytes(bad)
            self.assertEqual(self.hook(), '')
            log = (self.state / 'hook-errors.log').read_text(encoding='utf-8')
            self.assertNotIn('secret', log)
            self.assertIn('ValueError', log)
        path.write_bytes(valid)
        path.chmod(0)
        try:
            self.assertEqual(self.hook(), '')
        finally:
            path.chmod(0o600)
        lock = self.state / 'armed' / (run_id + '.lock')
        lock.touch()
        begin = time.perf_counter()
        self.assertEqual(self.hook(), '')
        self.assertLess(time.perf_counter() - begin, 3)
        self.assertIn('TimeoutError', (self.state / 'hook-errors.log').read_text(encoding='utf-8'))
        self.assertEqual(self.entry(run_id)['counters']['stop_blocks'], 0)
        self.assertTrue(lock.exists())
        log = self.state / 'hook-errors.log'
        log.write_bytes(('2000-01-01T00:00:00Z Stop ValueError x.py:1\n' * 2000).encode('utf-8'))
        self.hook()
        self.assertLessEqual(log.stat().st_size, 65536)
        if os.name != 'nt':  # Windows では権限を変えないので、POSIX だけで確かめる
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_h20_exception_message_and_time_budget(self):
        run_id = self.bound()
        scripts = self.root / 'isolated-scripts'
        scripts.mkdir()
        copied = scripts / 'yomiyasu_hook.py'
        shutil.copyfile(str(HOOK), str(copied))
        fake = scripts / 'yomiyasu_check.py'
        marker = 'ZQX本文の目印ZQX'
        fake.write_bytes(('import sys; print(' + repr(marker) + '); print(' + repr(marker) + ', file=sys.stderr); raise RuntimeError(' + repr(marker) + ')').encode('utf-8'))
        self.assertEqual(self.hook(script=copied), '')
        log = (self.state / 'hook-errors.log').read_text(encoding='utf-8')
        self.assertIn('RuntimeError', log)
        self.assertNotIn(marker, log)
        if os.name == 'posix':
            fake.write_bytes('import time; time.sleep(3)'.encode('utf-8'))
            begin = time.perf_counter()
            self.assertEqual(self.hook('SessionEnd', script=copied), '')
            self.assertLess(time.perf_counter() - begin, 1.5)
            self.assertEqual(self.entry(run_id)['status'], 'active')
            self.assertFalse(any(row['result'] == 'timeout' for row in self.entry(run_id)['log']))

            # Time out while checking a known registration, after acquiring its lock.
            copied.write_bytes(HOOK.read_text(encoding='utf-8').replace(
                "budget = started + _BUDGETS[event]", "budget = started + 0.3").encode('utf-8'))
            for dependency in CHECK.parent.glob('*.py'):
                if dependency.name not in (HOOK.name, CHECK.name):
                    shutil.copyfile(str(dependency), str(scripts / dependency.name))
            fake.write_bytes((CHECK.read_text(encoding='utf-8') +
                              '\ndef verify_quick(*args, **kwargs):\n    time.sleep(3)\n').encode('utf-8'))
            unrelated = self.root / 'unrelated.md'
            unrelated.write_bytes('別の原稿。'.encode('utf-8'))
            other_id = json.loads(self.cli('start', '--source', str(unrelated), '--session', 'B',
                                           '--host', 'claude-code', '--json').stdout)['run_id']
            other_before = self.entry(other_id)
            for event, data in (('Stop', {}), ('PreToolUse', {
                    'tool_name': 'Bash', 'tool_input': {'command': 'gh pr create --body-file final.md'}})):
                with self.subTest(event=event):
                    before = self.entry(run_id)
                    begin = time.perf_counter()
                    self.assertEqual(self.hook(event, script=copied, **data), '')
                    self.assertLess(time.perf_counter() - begin, 1.5)
                    after = self.entry(run_id)
                    row = after['log'][-1]
                    self.assertEqual(row['event'], event)
                    self.assertEqual(row['result'], 'timeout')
                    self.assertGreaterEqual(row['ms'], 250)
                    self.assertIn('at', row)
                    self.assertEqual(after['log'][:-1], before['log'])
                    self.assertEqual(dict(after, log=[]), dict(before, log=[]))
                    self.assertEqual(self.entry(other_id), other_before)
                    self.assertEqual(list((self.state / 'armed').glob('*.lock')), [])

            # A busy lock is left untouched, and the best-effort log must not delay the host.
            lock = self.state / 'armed' / (run_id + '.lock')
            lock.touch()
            before = self.entry(run_id)
            begin = time.perf_counter()
            self.assertEqual(self.hook(script=copied), '')
            self.assertLess(time.perf_counter() - begin, 1.5)
            self.assertEqual(self.entry(run_id), before)
            self.assertTrue(lock.exists())
            self.assertIn('TimeoutError', (self.state / 'hook-errors.log').read_text(encoding='utf-8'))

    def test_h20_closed_host_pipe_still_exits_zero(self):
        self.bound()
        process = subprocess.Popen([sys.executable, '-B', str(HOOK), '--host', 'claude-code'],
                                   cwd=str(self.root), env=self.env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdout.close()
        process.stdout = None
        _, error = process.communicate(json.dumps(dict(hook_event_name='Stop', session_id='A',
                                                       cwd=str(self.root))).encode('utf-8'), timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(error, b'')

    def test_state_candidates_and_partial_session_binding(self):
        # Keep default state discovery local even when the temporary directory
        # is inside another Git worktree (for example, via TMPDIR).
        (self.root / '.git').mkdir()
        run_id = self.start('--session', 'A')['run_id']
        self.hook('UserPromptSubmit', 'codex')
        self.assertEqual(self.entry(run_id)['host'], 'codex')
        self.env['YOMIYASU_STATE_DIR'] = '${UNEXPANDED}'
        self.assertEqual(self.hook('SessionEnd', 'codex'), '')
        self.assertEqual(self.entry(run_id)['status'], 'ended')
        run_id = self.start('--host', 'claude-code')['run_id']
        nested = self.root / 'nested'
        nested.mkdir()
        self.env['CLAUDE_PROJECT_DIR'] = str(self.root)
        self.hook('UserPromptSubmit', cwd=str(nested))
        self.assertEqual(self.entry(run_id)['session_id'], 'A')



if __name__ == '__main__':
    unittest.main()
