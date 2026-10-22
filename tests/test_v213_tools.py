#!/usr/bin/env python3
"""v2.1.3: Windows で、標準出力と標準エラーの改行、閉じた出力先、並行実行のロックと記録の読み取りを確かめる。

1. lint、diff、check、フックは、標準出力と標準エラーに OS によらず "\\n" で書く（Windows の既定は "\\r\\n"）。
   POSIX では、Windows と同じく "\\n" を "\\r\\n" に変える流れを sitecustomize で作り、子プロセスでも試す。
2. Windows では、読む側が閉じたパイプに書くと、BrokenPipeError ではなく errno が EINVAL の OSError になる。
   os.name を "nt" にして、BrokenPipeError と同じ案内と終了コード3になること、POSIX では内部エラーのままであることを試す。
3. Windows では、ほかのプロセスが消している途中のロックや、入れ替えている途中の記録を開くと PermissionError になる。
   os.name を "nt" にして、待ち直すこと、POSIX では今までどおりすぐに出すことを試す。

文はすべて合成。
"""

import contextlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
LINT = SCRIPTS / "yomiyasu_lint.py"
DIFF = SCRIPTS / "yomiyasu_diff.py"
CHECK = SCRIPTS / "yomiyasu_check.py"
HOOK = SCRIPTS / "yomiyasu_hook.py"
CLOSED = "出力先が閉じられたため、結果を最後まで書けませんでした。"

SOURCE_TEXT = "本記事では、設計の本質に迫ります。\n\n重要なのは、テストを書くことです。\n保存期間は3日です。\n"
FINAL_TEXT = "この記事では、設計を説明します。\n\nテストを書いてください。\n保存期間は30日です。\n"

# Windows の標準出力と標準エラーと同じく、書いた "\n" を "\r\n" に変える流れに差し替える
CRLF_SITECUSTOMIZE = '''
import io
import sys


def _crlf(name):
    stream = getattr(sys, name, None)
    if stream is None or not hasattr(stream, "buffer"):
        return
    encoding, errors = stream.encoding, stream.errors
    line_buffering = stream.line_buffering
    write_through = getattr(stream, "write_through", False)
    stream.flush()
    wrapped = io.TextIOWrapper(stream.detach(), encoding=encoding, errors=errors, newline="\\r\\n",
                               line_buffering=line_buffering, write_through=write_through)
    setattr(sys, name, wrapped)
    setattr(sys, "__{}__".format(name), wrapped)


_crlf("stdout")
_crlf("stderr")
'''


def load(path, name):
    saved = sys.dont_write_bytecode
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


lint = load(LINT, "_v213_tools_lint")
diff = load(DIFF, "_v213_tools_diff")
check = load(CHECK, "_v213_tools_check")
hook = load(HOOK, "_v213_tools_hook")


class _RecordingStream(object):
    def __init__(self):
        self.calls = []

    def reconfigure(self, **options):
        self.calls.append(options)


class UseUtf8NewlineTests(unittest.TestCase):
    """_use_utf8 は、文字コードと一緒に改行を "\\n" に決める。"""

    def test_reconfigure_passes_newline(self):
        for module in (lint, diff, check):
            with self.subTest(module=module.__name__):
                stream = _RecordingStream()
                module._use_utf8(stream)
                module._use_utf8(stream, errors="backslashreplace")
                self.assertEqual(stream.calls, [{"encoding": "utf-8", "newline": "\n"},
                                                {"encoding": "utf-8", "newline": "\n", "errors": "backslashreplace"}])

    def test_crlf_stream_writes_lf_after_use_utf8(self):
        for module in (lint, diff, check):
            with self.subTest(module=module.__name__):
                raw = io.BytesIO()
                stream = io.TextIOWrapper(raw, encoding="cp932", newline="\r\n")
                module._use_utf8(stream)
                stream.write("一行目\n二行目\n")
                stream.flush()
                self.assertEqual(raw.getvalue(), "一行目\n二行目\n".encode("utf-8"))

    def test_streams_without_reconfigure_are_left_alone(self):
        for module in (lint, diff, check):
            with self.subTest(module=module.__name__):
                module._use_utf8(None)
                module._use_utf8(io.StringIO())


class CrlfConsoleCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v213-tools-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        site = self.root / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(CRLF_SITECUSTOMIZE, encoding="utf-8")
        self.source = self.root / "source.md"
        self.final = self.root / "final.md"
        self.source.write_bytes(SOURCE_TEXT.encode("utf-8"))
        self.final.write_bytes(FINAL_TEXT.encode("utf-8"))
        self.state = self.root / "state"
        base = dict(os.environ)
        for name in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID", "CLAUDE_PROJECT_DIR",
                     "PYTHONIOENCODING", "PYTHONUTF8"):
            base.pop(name, None)
        base["HOME"] = str(self.root)
        self.plain_env = dict(base)
        self.crlf_env = dict(base, PYTHONPATH=os.pathsep.join(
            [str(site)] + ([base["PYTHONPATH"]] if base.get("PYTHONPATH") else [])))

    def run_tool(self, args, crlf=True, stdin=None):
        return subprocess.run([sys.executable, "-B"] + [str(arg) for arg in args], cwd=str(self.root),
                              input=stdin, capture_output=True, timeout=60,
                              env=self.crlf_env if crlf else self.plain_env)

    def assert_lf_only(self, data, label):
        self.assertTrue(data, label + " が空です")
        self.assertNotIn(b"\r", data, label)


class CrlfConsoleTests(CrlfConsoleCase):
    """"\\n" を "\\r\\n" に変える標準出力と標準エラーでも、4本は "\\n" だけを書く。"""

    def test_simulated_console_turns_lf_into_crlf(self):
        # この試験の前提: sitecustomize が子プロセスの標準出力と標準エラーを差し替えている
        process = self.run_tool(["-c", "import sys; print('a'); print('b', file=sys.stderr)"])
        self.assertEqual((process.stdout, process.stderr), (b"a\r\n", b"b\r\n"))

    def test_lint_and_diff_outputs(self):
        cases = {
            "lint": [LINT, self.final],
            "lint --json": [LINT, "--json", self.final],
            "lint --help": [LINT, "--help"],
            "diff": [DIFF, self.source, self.final],
            "diff --json": [DIFF, "--json", self.source, self.final],
            "diff --help": [DIFF, "--help"],
            "check --help": [CHECK, "run", "--help"],
        }
        for label, args in cases.items():
            with self.subTest(case=label):
                crlf = self.run_tool(args)
                self.assertEqual(crlf.returncode, 0, crlf.stderr)
                self.assert_lf_only(crlf.stdout, label)
                # 改行を変えない流れのときと同じバイト列
                self.assertEqual(crlf.stdout, self.run_tool(args, crlf=False).stdout)

    def test_stdin_input_is_read_as_before(self):
        crlf = self.run_tool([LINT, "--json"], stdin="一行目です。\r\n二行目です。\n".encode("utf-8"))
        plain = self.run_tool([LINT, "--json"], crlf=False, stdin="一行目です。\r\n二行目です。\n".encode("utf-8"))
        self.assertEqual(crlf.returncode, 0, crlf.stderr)
        self.assertEqual(crlf.stdout, plain.stdout)
        self.assertNotIn(b"\r", crlf.stdout)

    def test_error_messages_on_stderr(self):
        cases = {
            "lint usage": ([LINT, "--nope"], 2),
            "lint fail-on": ([LINT, "--fail-on", "nope", self.final], 2),
            "lint missing": ([LINT, self.root / "missing.md"], 2),
            "diff usage": ([DIFF, "--nope"], 2),
            "diff missing": ([DIFF, self.source, self.root / "missing.md"], 2),
            "check usage": ([CHECK, "run", "--nope"], 2),
            "check fail-on": ([CHECK, "run", "--source", self.source, "--final", self.final, "--fail-on", "nope"], 2),
            "hook print-config": ([HOOK, "--print-config", "nope"], 2),
        }
        for label, (args, code) in cases.items():
            with self.subTest(case=label):
                crlf = self.run_tool(args)
                self.assertEqual(crlf.returncode, code, crlf.stderr)
                self.assert_lf_only(crlf.stderr, label)
                self.assertEqual(crlf.stderr, self.run_tool(args, crlf=False).stderr)

    def test_hook_outputs(self):
        for label, args in (("help", [HOOK, "--help"]), ("config", [HOOK, "--print-config", "claude-code"]),
                            ("version", [HOOK, "--version"])):
            with self.subTest(case=label):
                crlf = self.run_tool(args)
                self.assertEqual(crlf.returncode, 0, crlf.stderr)
                self.assert_lf_only(crlf.stdout, label)
                self.assertEqual(crlf.stdout, self.run_tool(args, crlf=False).stdout)

    def test_check_outputs_and_records_match_the_cli(self):
        """記録の .json は CLI の --json の出力と、.txt は通常の出力と同じバイト列（改行を変える流れでも）。"""
        lines = None
        for label, extra in (("text", []), ("json", ["--json", "--new-run"])):
            with self.subTest(case=label):
                process = self.run_tool([CHECK, "run", "--source", self.source, "--final", self.final,
                                         "--state-dir", self.state] + extra)
                self.assertIn(process.returncode, (0, 1), process.stderr)
                self.assert_lf_only(process.stdout, label)
                if label == "text":
                    lines = process.stdout.decode("utf-8").split("\n")
        record_line = [line for line in lines if line.startswith("記録: ")][0]
        record = json.loads(Path(record_line[len("記録: "):]).read_text(encoding="utf-8"))
        commands = {"lint": ([LINT, "--json", self.final], [LINT, self.final]),
                    "diff": ([DIFF, "--json", self.source, self.final], [DIFF, self.source, self.final])}
        for name, (json_args, text_args) in commands.items():
            with self.subTest(check=name):
                entry = [item for item in record["checks"] if item["name"] == name][0]
                as_json = self.run_tool(json_args)
                as_text = self.run_tool(text_args)
                self.assertEqual((self.state / entry["report"]).read_bytes(), as_json.stdout)
                self.assertEqual((self.state / entry["text"]).read_bytes(), as_text.stdout)
                self.assertNotIn(b"\r", (self.state / entry["report"]).read_bytes())


class _ClosedOnWindows(io.TextIOBase):
    """書けるが、書き出すと Windows の閉じたパイプと同じ OSError（errno EINVAL）を出す標準出力。"""

    def __init__(self, error=None):
        super().__init__()
        self.error = error or OSError(errno.EINVAL, "Invalid argument")

    def writable(self):
        return True

    def write(self, text):
        return len(text)

    def flush(self):
        raise self.error

    def close(self):
        # 後片付けでは書き出さない（試験の外で例外を出さない）
        pass


class ClosedOutputTests(unittest.TestCase):
    """Windows の閉じたパイプ（errno EINVAL の OSError）は、BrokenPipeError と同じ案内と終了コード3にする。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v213-tools-")
        self.addCleanup(folder.cleanup)
        source, final = Path(folder.name) / "source.md", Path(folder.name) / "final.md"
        source.write_bytes(SOURCE_TEXT.encode("utf-8"))
        final.write_bytes(FINAL_TEXT.encode("utf-8"))
        # lint と diff は結果を書いたあとに、check は版の行を書いたあとに書き出す
        self.TOOLS = ((lint, "yomiyasu_lint.py", [str(final)]), (diff, "yomiyasu_diff.py", [str(source), str(final)]),
                      (check, "yomiyasu_check.py", ["--version"]))

    def run_main(self, module, args, os_name, error=None):
        stdout, stderr = _ClosedOnWindows(error), io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr), \
                mock.patch.object(os, "name", os_name):
            code = module.main(args)
        return code, stderr.getvalue()

    def test_einval_on_windows_is_a_closed_output(self):
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                code, message = self.run_main(module, args, "nt")
                self.assertEqual(code, 3)
                self.assertEqual(message, "{}: {}\n".format(name, CLOSED))
                self.assertNotIn("Traceback", message)

    def test_einval_message_matches_broken_pipe(self):
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                broken = self.run_main(module, args, "posix", BrokenPipeError(errno.EPIPE, "Broken pipe"))
                self.assertEqual(self.run_main(module, args, "nt"), broken)

    def test_einval_on_posix_is_still_an_internal_error(self):
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                code, message = self.run_main(module, args, "posix")
                self.assertEqual(code, 3)
                self.assertIn("{}: 内部エラー: OSError: [Errno {}]".format(name, errno.EINVAL), message)
                self.assertIn("Traceback", message)
                self.assertNotIn(CLOSED, message)

    def test_other_errors_on_windows_are_still_internal_errors(self):
        others = (OSError(errno.EINVAL, "Invalid argument", "名前:に使えない字.md"),
                  OSError(errno.EIO, "Input/output error"),
                  ValueError("I/O operation on closed file."))
        for module, name, args in self.TOOLS:
            for error in others:
                with self.subTest(tool=name, error=repr(error)):
                    code, message = self.run_main(module, args, "nt", error)
                    self.assertEqual(code, 3)
                    self.assertIn("内部エラー", message)
                    self.assertNotIn(CLOSED, message)

    def test_closed_output_silences_stdout(self):
        """インタプリタの終わりでもう一度書き出しに失敗しないように、_silence_stdout を通してから案内を出す。"""
        for module, name, args in self.TOOLS:
            with self.subTest(tool=name):
                stdout, stderr = _ClosedOnWindows(), io.StringIO()
                with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr), \
                        mock.patch.object(os, "name", "nt"), \
                        mock.patch.object(module, "_silence_stdout") as silence:
                    code = module.main(args)
                self.assertEqual(code, 3)
                silence.assert_called_once_with()
                self.assertEqual(stderr.getvalue(), "{}: {}\n".format(name, CLOSED))

    def test_hook_stays_silent(self):
        for os_name in ("nt", "posix"):
            with self.subTest(os_name=os_name):
                stdout, stderr = _ClosedOnWindows(), io.StringIO()
                with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr), \
                        mock.patch.object(os, "name", os_name):
                    code = hook.main(["--version"])
                self.assertEqual(code, 0)
                self.assertEqual(stderr.getvalue(), "")


class _StateCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v213-tools-")
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name) / "state"
        (self.state / "armed").mkdir(parents=True)
        self.run_id = "20261022T000000Z-0123456789ab"
        self.assertIsNone(check._run_id_problem(self.run_id))
        self.lock = self.state / "armed" / (self.run_id + ".lock")


class ArmedLockTests(_StateCase):
    """ロックを O_EXCL で作るときの PermissionError。Windows では使用中として待ち直し、POSIX ではすぐ出す。"""

    def pending_open(self, times, keep_name=True):
        """times 回だけ、消している途中のロックと同じ PermissionError を出す os.open。"""
        real_open = os.open
        calls = []

        def fake(path, flags, *args):
            if str(path) == str(self.lock) and len(calls) < times:
                calls.append(path)
                if keep_name:
                    self.lock.write_bytes(b"")
                raise PermissionError(errno.EACCES, "Permission denied", str(path))
            if str(path) == str(self.lock) and keep_name and self.lock.exists() and not os.path.getsize(str(self.lock)):
                # 消している途中だったロックが、消し終わった
                os.unlink(str(self.lock))
            return real_open(path, flags, *args)
        return fake, calls

    def test_windows_waits_for_a_lock_being_deleted(self):
        fake, calls = self.pending_open(3)
        with mock.patch.object(os, "open", fake), mock.patch.object(os, "name", "nt"):
            with check._ArmedLock(str(self.state), self.run_id) as lock:
                self.assertTrue(self.lock.exists())
                self.assertIsNotNone(lock.identity)
        self.assertEqual(len(calls), 3)
        self.assertFalse(self.lock.exists())

    def test_posix_raises_permission_error_at_once(self):
        fake, calls = self.pending_open(3)
        with mock.patch.object(os, "open", fake), mock.patch.object(os, "name", "posix"):
            with self.assertRaises(PermissionError):
                with check._ArmedLock(str(self.state), self.run_id):
                    pass
        self.assertEqual(len(calls), 1)

    def test_windows_folder_that_refuses_writes_raises_soon(self):
        """ロックの名前がないのに拒まれ続けるときは、締切（12秒）まで待たずに PermissionError を出す。"""
        fake, calls = self.pending_open(1000, keep_name=False)
        begin = time.monotonic()
        with mock.patch.object(os, "open", fake), mock.patch.object(os, "name", "nt"):
            with self.assertRaises(PermissionError):
                with check._ArmedLock(str(self.state), self.run_id):
                    pass
        self.assertEqual(len(calls), check._REPLACE_TRIES)
        self.assertLess(time.monotonic() - begin, 2)
        self.assertFalse(self.lock.exists())

    def test_windows_lock_name_that_is_a_folder_raises_soon(self):
        self.lock.mkdir()
        real_open = os.open
        calls = []

        def fake(path, flags, *args):
            if str(path) == str(self.lock):
                calls.append(path)
                raise PermissionError(errno.EACCES, "Permission denied", str(path))
            return real_open(path, flags, *args)
        begin = time.monotonic()
        with mock.patch.object(os, "open", fake), mock.patch.object(os, "name", "nt"):
            with self.assertRaises(PermissionError):
                with check._ArmedLock(str(self.state), self.run_id):
                    pass
        self.assertEqual(len(calls), check._REPLACE_TRIES)
        self.assertLess(time.monotonic() - begin, 2)

    def test_existing_lock_still_waits_and_times_out(self):
        self.lock.write_bytes(b"")
        lock = check._ArmedLock(str(self.state), self.run_id, budget=time.monotonic() + 0.1)
        with mock.patch.object(os, "name", "nt"):
            with self.assertRaises(TimeoutError):
                lock.__enter__()
        self.assertTrue(self.lock.exists())


class RecordReadTests(_StateCase):
    """入れ替えの途中で記録を開けないとき（Windows の PermissionError）は読み直す。POSIX では読み直さない。"""

    def flaky_open(self, path, times):
        real_open = open
        calls = []

        def fake(file, *args, **kwargs):
            if str(file) == str(path) and len(calls) < times:
                calls.append(file)
                raise PermissionError(errno.EACCES, "Permission denied", str(file))
            return real_open(file, *args, **kwargs)
        return fake, calls

    def write_record(self):
        path = self.state / "armed" / (self.run_id + ".json")
        path.write_bytes(json.dumps({"format": "例", "値": 1}).encode("utf-8"))
        return path

    def test_windows_reads_again(self):
        path = self.write_record()
        fake, calls = self.flaky_open(path, 2)
        with mock.patch.object(check, "open", fake, create=True), mock.patch.object(os, "name", "nt"):
            self.assertEqual(check._read_record_status(str(path)), ("ok", {"format": "例", "値": 1}))
        self.assertEqual(len(calls), 2)

    def test_windows_gives_up_after_the_retries(self):
        path = self.write_record()
        fake, calls = self.flaky_open(path, 1000)
        with mock.patch.object(check, "open", fake, create=True), mock.patch.object(os, "name", "nt"):
            self.assertEqual(check._read_record_status(str(path)), ("bad", None))
        self.assertEqual(len(calls), check._REPLACE_TRIES)

    def test_posix_does_not_read_again(self):
        path = self.write_record()
        fake, calls = self.flaky_open(path, 1)
        with mock.patch.object(check, "open", fake, create=True), mock.patch.object(os, "name", "posix"):
            self.assertEqual(check._read_record_status(str(path)), ("bad", None))
        self.assertEqual(len(calls), 1)

    def test_armed_entries_keep_a_registration_being_replaced(self):
        """登録を読み飛ばすと、run は登録のない原稿として検査し、上限を超えて動く。Windows では読み直して数える。"""
        path = self.write_record()
        fake, calls = self.flaky_open(path, 1)
        with mock.patch.object(check, "open", fake, create=True), mock.patch.object(os, "name", "nt"), \
                mock.patch.object(check, "_armed_valid", lambda value, run_id: run_id == self.run_id):
            entries = check.armed_entries(str(self.state))
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(calls), 1)


class ManagedRunCountTests(unittest.TestCase):
    """登録の run の回数。Windows で記録を確かめられないときは、使った回として数える。POSIX は今までどおり。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v213-tools-")
        self.addCleanup(folder.cleanup)
        self.run_dir = Path(folder.name)
        self.record = self.run_dir / "attempt-1.json"
        self.record.write_bytes(b"{}\n")

    def stat_failing(self, times):
        real_stat = os.stat
        calls = []

        def fake(path, *args, **kwargs):
            if str(path) == str(self.record) and len(calls) < times:
                calls.append(path)
                raise PermissionError(errno.EACCES, "Permission denied", str(path))
            return real_stat(path, *args, **kwargs)
        return fake, calls

    def test_counts(self):
        cases = (("nt", 2, 1, 3), ("nt", 1000, 1, check._REPLACE_TRIES), ("posix", 1000, 0, 1), ("posix", 0, 1, 0))
        for os_name, failures, expected, tries in cases:
            with self.subTest(os_name=os_name, failures=failures):
                fake, calls = self.stat_failing(failures)
                with mock.patch.object(os, "stat", fake), mock.patch.object(os, "name", os_name):
                    count = check._managed_run_count(str(self.run_dir))
                self.assertEqual(count, expected)
                self.assertEqual(len(calls), min(failures, tries))


if __name__ == "__main__":
    unittest.main()
