#!/usr/bin/env python3
"""Issue #11: 標準入出力が cp932 の環境でも、UTF-8 で読み書きすることを確認する。

PYTHONIOENCODING で Windows の日本語環境と同じ標準入出力（cp932、surrogateescape）を作るので、
macOS や Linux でも同じ条件で確かめられる。
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
LINT = SCRIPTS_DIR / "yomiyasu_lint.py"
DIFF = SCRIPTS_DIR / "yomiyasu_diff.py"

SAMPLE = "本記事では、手触りのある設計の本質に迫ります。いかがでしたでしょうか。\n"


def run_cp932(args, stdin=None):
    env = dict(os.environ, PYTHONIOENCODING="cp932:surrogateescape")
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, "-B"] + [str(a) for a in args],
        input=stdin,
        capture_output=True,
        env=env,
        timeout=10,
    )


class TestStdioEncoding(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-stdio-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def assert_ascii_json(self, process):
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        self.assertTrue(process.stdout.isascii(), "--json の出力は ASCII だけにする")
        return json.loads(process.stdout.decode("ascii"))

    def test_lint_reads_utf8_stdin_like_a_file(self):
        path = self.write("sample.md", SAMPLE)
        from_file = self.assert_ascii_json(run_cp932([LINT, path, "--json"]))
        from_stdin = self.assert_ascii_json(run_cp932([LINT, "--json"], SAMPLE.encode("utf-8")))
        self.assertEqual(from_stdin, from_file)
        self.assertEqual(from_stdin["metrics"]["char_count"], 35)
        self.assertEqual(len(from_stdin["findings"]), 2)

    def test_lint_strict_exit_code_from_utf8_stdin(self):
        process = run_cp932([LINT, "--strict"], SAMPLE.encode("utf-8"))
        self.assertEqual(process.returncode, 1, process.stderr.decode("utf-8", "replace"))
        self.assertEqual(process.stderr, b"")

    def test_lint_rejects_non_utf8_stdin_with_exit_code_2(self):
        process = run_cp932([LINT, "--json"], SAMPLE.encode("cp932"))
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, b"")
        self.assertIn(b"Error reading stdin", process.stderr)

    def test_lint_reports_emoji_without_crashing(self):
        path = self.write("emoji.md", "🚀 設定ファイルを更新しました。\n")
        report = run_cp932([LINT, path])
        self.assertEqual(report.returncode, 0, report.stderr.decode("utf-8", "replace"))
        self.assertIn("🚀", report.stdout.decode("utf-8"))
        result = self.assert_ascii_json(run_cp932([LINT, path, "--json"]))
        self.assertIn("🚀", result["findings"][0]["message"])

    def test_lint_reports_em_dash_snippet_without_crashing(self):
        path = self.write("dash.md", "手触りのある設計です — いかがでしたでしょうか。\n")
        report = run_cp932([LINT, path])
        self.assertEqual(report.returncode, 0, report.stderr.decode("utf-8", "replace"))
        self.assertIn("—", report.stdout.decode("utf-8"))
        result = self.assert_ascii_json(run_cp932([LINT, path, "--json"]))
        self.assertIn("—", result["findings"][0]["snippet"])

    def test_diff_json_with_em_dash(self):
        before = self.write("before.md", "設定を更新します。\n")
        after = self.write("after.md", "設定を更新しました — 再起動してください。\n")
        self.assert_ascii_json(run_cp932([DIFF, before, after, "--json"]))
        report = run_cp932([DIFF, before, after])
        self.assertEqual(report.returncode, 0, report.stderr.decode("utf-8", "replace"))
        report.stdout.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
