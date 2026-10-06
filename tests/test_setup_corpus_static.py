"""Corpus setup uses explicit inputs and keeps all test I/O in a fixture."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/setup_corpus_static.py'
WORKER = r'''
import importlib.util
import os
from pathlib import Path
import runpy
import sys
import sysconfig

root = Path(sys.argv[1]).resolve()
stdlib = Path(sysconfig.get_path('stdlib')).resolve()
mode, script = sys.argv[2:4]

def guard(event, arguments):
    if event == 'open' and isinstance(arguments[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(arguments[0])).resolve()
        if path != root and root not in path.parents and path != stdlib and stdlib not in path.parents:
            raise PermissionError('File access outside the test fixture is blocked')

sys.addaudithook(guard)
sys.argv = [script] + sys.argv[4:]
if mode == 'import':
    spec = importlib.util.spec_from_file_location('corpus_setup_under_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
else:
    runpy.run_path(script, run_name='__main__')
'''


class CorpusSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yomiyasu-corpus-setup-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.script = self.root / 'scripts/setup_corpus_static.py'
        self.script.parent.mkdir()
        self.script.write_bytes(SOURCE.read_bytes())
        self.default_output = self.root / 'tests/corpus'

    def run_script(self, *arguments, mode='cli'):
        return subprocess.run(
            [sys.executable, '-B', '-c', WORKER, str(self.root), mode,
             str(self.script)] + list(arguments),
            cwd=str(self.root), capture_output=True, text=True, timeout=10,
        )

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def assert_static_outputs(self, output):
        self.assertEqual(
            sorted(path.name for path in (output / 'human').glob('human_doc_*.md')),
            ['human_doc_09.md', 'human_doc_10.md', 'human_doc_11.md', 'human_doc_12.md',
             'human_doc_13.md', 'human_doc_14.md', 'human_doc_15.md', 'human_doc_16.md'],
        )
        self.assertEqual(len(list((output / 'edge_cases').glob('*.md'))), 48)
        self.assertEqual(
            (output / 'edge_cases/edge_nigiru_01.md').read_text(encoding='utf-8'),
            '# 境界値検証: edge_nigiru_01\n\n'
            'お昼休みにコンビニでお握りを買って食べました。鮭のお握りが一番好きです。\n',
        )

    def test_import_does_not_create_output_directories(self):
        self.assert_success(self.run_script(mode='import'))
        self.assertFalse(self.default_output.exists())

    def test_help_exits_without_reading_source_or_creating_output(self):
        result = self.run_script('--help', '--source-html', 'missing.html',
                                 '--output-dir', 'custom-output')
        self.assert_success(result)
        self.assertIn('--source-html', result.stdout)
        self.assertIn('--output-dir', result.stdout)
        self.assertFalse(self.default_output.exists())
        self.assertFalse((self.root / 'custom-output').exists())

    def test_default_run_generates_static_documents_without_article_excerpts(self):
        self.assert_success(self.run_script())
        self.assert_static_outputs(self.default_output)
        self.assertEqual(list((self.default_output / 'human').glob('human_oga_*.md')), [])

    def test_output_option_preserves_existing_excerpts_when_source_is_omitted(self):
        output = self.root / 'custom-output'
        existing = output / 'human/human_oga_01.md'
        existing.parent.mkdir(parents=True)
        saved = b'Existing excerpt\r\n\xff'
        existing.write_bytes(saved)
        self.assert_success(self.run_script('--output-dir', str(output)))
        self.assertEqual(existing.read_bytes(), saved)
        self.assertEqual(list((output / 'human').glob('human_oga_*.md')), [existing])
        self.assert_static_outputs(output)
        self.assertFalse(self.default_output.exists())

    def test_explicit_html_extracts_the_first_eight_eligible_sections(self):
        body = 'この段落は指定した入力から抽出するための記録です。' * 12
        html = '<h2>Zenn navigation</h2><p>' + body + '</p>'
        html += ''.join('<h2>Section ' + str(number) + '</h2><p>' + body + '</p>'
                        for number in range(1, 10))
        source = self.root / 'source.html'
        source.write_text(html, encoding='utf-8')
        output = self.root / 'selected-output'
        self.assert_success(self.run_script('--source-html', str(source),
                                            '--output-dir', str(output)))
        self.assert_static_outputs(output)
        self.assertEqual(len(list((output / 'human').glob('human_oga_*.md'))), 8)
        for number in (1, 8):
            self.assertEqual(
                (output / 'human' / ('human_oga_%02d.md' % number)).read_text(encoding='utf-8'),
                '# 大賀愛一郎 実務エッセイ 抜粋 ' + str(number) + '\n\nSection '
                + str(number) + '\n\n' + body,
            )
        self.assertFalse(self.default_output.exists())

    def test_missing_source_is_a_cli_error_before_any_output_write(self):
        output = self.root / 'missing-source-output'
        result = self.run_script('--source-html', str(self.root / 'absent.html'),
                                 '--output-dir', str(output))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('error:', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertFalse(output.exists())
        self.assertFalse(self.default_output.exists())

    def test_invalid_utf8_is_a_cli_error_and_preserves_existing_output(self):
        source = self.root / 'invalid.html'
        source.write_bytes(b'\xff\xfe')
        output = self.root / 'existing-output'
        existing = output / 'human/human_doc_09.md'
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'Keep this existing document\n')
        result = self.run_script('--source-html', str(source), '--output-dir', str(output))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('error:', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(existing.read_bytes(), b'Keep this existing document\n')
        self.assertEqual([path.relative_to(output).as_posix() for path in output.rglob('*')],
                         ['human', 'human/human_doc_09.md'])
        self.assertFalse(self.default_output.exists())


if __name__ == '__main__':
    unittest.main()
