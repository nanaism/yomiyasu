#!/usr/bin/env python3
"""Issue #11: 標準入出力が cp932 の環境でも、UTF-8 で読み書きすることを確認する。

PYTHONIOENCODING で Windows の日本語環境と同じ標準入出力（cp932、surrogateescape）を作るので、
macOS や Linux でも同じ条件で確かめられる。
"""

import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


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
        self.assertEqual(len(from_stdin["findings"]), 3)

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
        self.assertIn("再起動", report.stdout.decode("utf-8"))

    def test_diff_report_with_emoji_without_crashing(self):
        # 文末が変わった文はレポートにそのまま出るので、cp932 で表せない文字を含めて確かめる。
        before = self.write("before.md", "設定を更新します。\n")
        after = self.write("after.md", "設定を🚀更新しました。\n")
        report = run_cp932([DIFF, before, after])
        self.assertEqual(report.returncode, 0, report.stderr.decode("utf-8", "replace"))
        self.assertIn("🚀", report.stdout.decode("utf-8"))


_KEEP = object()


def run_in_process(script, args, stdin=_KEEP, stdout=_KEEP):
    """標準入出力を TextIOWrapper 以外（StringIO や None）に差し替えて、スクリプトを __main__ として実行する。"""
    patches = [mock.patch.object(sys, "argv", [str(script)] + [str(a) for a in args])]
    if stdin is not _KEEP:
        patches.append(mock.patch.object(sys, "stdin", stdin))
    # Never let the script reconfigure the test runner's own stdout.
    patches.append(mock.patch.object(sys, "stdout", io.StringIO() if stdout is _KEEP else stdout))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as stop:
            return stop.code or 0
    return 0


class TestStreamsWithoutReconfigure(unittest.TestCase):
    """IDLE や pythonw、プロセス内での実行のように、reconfigure() を持たない標準入出力でも動く。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-stdio-")
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "sample.md"
        self.path.write_text(SAMPLE, encoding="utf-8")

    def test_lint_writes_json_to_string_stdout(self):
        out = io.StringIO()
        self.assertEqual(run_in_process(LINT, [self.path, "--json"], stdout=out), 0)
        self.assertEqual(len(json.loads(out.getvalue())["findings"]), 3)

    def test_lint_reads_string_stdin(self):
        out = io.StringIO()
        self.assertEqual(run_in_process(LINT, ["--json"], stdin=io.StringIO(SAMPLE), stdout=out), 0)
        self.assertEqual(json.loads(out.getvalue())["metrics"]["char_count"], 35)

    def test_lint_runs_without_stdout(self):
        self.assertEqual(run_in_process(LINT, [self.path], stdout=None), 0)

    def test_lint_rejects_missing_stdin_with_exit_code_2(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run_in_process(LINT, ["--json"], stdin=None, stdout=io.StringIO())
        self.assertEqual(code, 2)
        self.assertIn("Error reading stdin", stderr.getvalue())

    def test_diff_writes_json_to_string_stdout(self):
        after = self.path.with_name("after.md")
        after.write_text("本記事では、設計の本質に迫りました。\n", encoding="utf-8")
        out = io.StringIO()
        self.assertEqual(run_in_process(DIFF, [self.path, after, "--json"], stdout=out), 0)
        self.assertIsInstance(json.loads(out.getvalue()), dict)


if __name__ == "__main__":
    unittest.main()
