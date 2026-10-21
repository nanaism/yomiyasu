"""v2.1.2: 状態フォルダに書き込めないときに、check が一時ファイルの名前を試し続けて終わらなくならないこと、
書き込みを拒まれたときに、ユーザーごとに別の状態フォルダを指定する案内を出すことを確かめる。

Windows の tempfile（Python 3.12 まで）は、ACL で書き込みを拒まれたフォルダで os.open が PermissionError を出すと、
同じ名前のフォルダがあるとみなして、約21億回まで次の名前を試す。check は tempfile.mkstemp と mkdtemp を使わず、
名前を試すのを100回までにした _mkstemp と _mkdtemp で一時ファイルと一時フォルダを作る。Windows の動きは、
os.open と「名前がフォルダか」の判定を差し替えて再現する。
"""
from pathlib import Path
from unittest import mock
import contextlib
import importlib.util
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "yomiyasu_check.py"


def load_check():
    before = sys.dont_write_bytecode
    try:
        spec = importlib.util.spec_from_file_location("_yomiyasu_check_v212", str(CHECK))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


check = load_check()


def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = check.main(argv)
    return code, out.getvalue(), err.getvalue()


def denied(prefix, real_open):
    """prefix の下の一時ファイルを開こうとすると PermissionError を出す os.open（Windows の ACL の拒否のまね）。"""
    def fake_open(path, flags, mode=0o777, *args, **kwargs):
        if str(path).startswith(prefix) and os.path.basename(str(path)).startswith(".tmp-"):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, mode, *args, **kwargs)
    return fake_open


class MkstempTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="yomiyasu-v212-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))

    def test_creates_private_file_like_tempfile(self):
        handle, path = check._mkstemp(self.folder)
        os.close(handle)
        self.assertTrue(os.path.isabs(path))
        self.assertEqual(os.path.dirname(path), os.path.abspath(self.folder))
        self.assertTrue(os.path.basename(path).startswith(".tmp-"))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_permission_error_on_a_plain_name_stops_at_once(self):
        """書き込みを拒まれ、その名前がフォルダでもないときは、次の名前を試さずにすぐ PermissionError を出す。"""
        calls = []

        def fake_open(path, flags, mode=0o777):
            calls.append(path)
            raise PermissionError(13, "Permission denied", path)
        with mock.patch.object(check.os, "open", fake_open), \
                mock.patch.object(check, "_temporary_name_taken", lambda path: os.path.isdir(path)):
            with self.assertRaises(PermissionError):
                check._mkstemp(self.folder)
        self.assertEqual(len(calls), 1)

    def test_names_taken_by_folders_are_tried_only_up_to_the_limit(self):
        """拒まれた名前が本当にフォルダのときだけ次を試し、試すのは _TEMPORARY_TRIES 回まで。"""
        calls = []

        def fake_open(path, flags, mode=0o777):
            calls.append(path)
            raise PermissionError(13, "Permission denied", path)
        with mock.patch.object(check.os, "open", fake_open), \
                mock.patch.object(check, "_temporary_name_taken", lambda path: True):
            with self.assertRaises(FileExistsError):
                check._mkstemp(self.folder)
        self.assertEqual(len(calls), check._TEMPORARY_TRIES)
        self.assertEqual(check._TEMPORARY_TRIES, 100)

    def test_existing_names_are_tried_only_up_to_the_limit(self):
        calls = []

        def fake_open(path, flags, mode=0o777):
            calls.append(path)
            raise FileExistsError(17, "File exists", path)
        with mock.patch.object(check.os, "open", fake_open):
            with self.assertRaises(FileExistsError):
                check._mkstemp(self.folder)
        self.assertEqual(len(calls), check._TEMPORARY_TRIES)

    def test_name_taken_only_for_folders_on_windows(self):
        with mock.patch.object(check.os, "name", "nt"):
            self.assertTrue(check._temporary_name_taken(self.folder))
            self.assertFalse(check._temporary_name_taken(os.path.join(self.folder, ".tmp-none")))
        if os.name != "nt":
            self.assertFalse(check._temporary_name_taken(self.folder))


class MkdtempTest(unittest.TestCase):
    def test_creates_private_folder(self):
        path = check._mkdtemp("yomiyasu-v212-")
        self.addCleanup(lambda: os.rmdir(path))
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(os.path.basename(path).startswith("yomiyasu-v212-"))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

    def test_folder_names_are_tried_only_up_to_the_limit(self):
        calls = []

        def fake_mkdir(path, mode=0o777):
            calls.append(path)
            raise PermissionError(13, "Permission denied", path)
        with mock.patch.object(check.os, "mkdir", fake_mkdir), \
                mock.patch.object(check, "_temporary_name_taken", lambda path: True):
            with self.assertRaises(FileExistsError):
                check._mkdtemp("yomiyasu-v212-")
        self.assertEqual(len(calls), check._TEMPORARY_TRIES)

    def test_check_no_longer_uses_tempfile_to_make_names(self):
        """記録を残さない run（一時フォルダに写しを置く）も、tempfile の名前を試す関数を使わない。"""
        with tempfile.TemporaryDirectory(prefix="yomiyasu-v212-") as folder:
            a, b = os.path.join(folder, "a.md"), os.path.join(folder, "b.md")
            Path(a).write_text("設定を更新します。\n", encoding="utf-8")
            Path(b).write_text("設定を更新しました。\n", encoding="utf-8")
            boom = mock.Mock(side_effect=AssertionError("tempfile の名前を試す関数は使わない"))
            with mock.patch.object(check.tempfile, "mkstemp", boom), \
                    mock.patch.object(check.tempfile, "mkdtemp", boom), \
                    mock.patch.object(check.tempfile, "TemporaryDirectory", boom):
                code, out, err = call(["run", "--no-record", "--source", a, "--final", b])
            self.assertEqual(code, 0, err)
            self.assertIn("yomiyasu-check: unrecorded", out)


class RunEndsWhenStateIsNotWritableTest(unittest.TestCase):
    """状態フォルダの一時ファイルを Windows のように拒まれても、run はすぐに reason=not_writable で終わる。"""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="yomiyasu-v212-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))
        self.state = os.path.join(self.folder, "state")
        os.mkdir(self.state)
        self.a, self.b = os.path.join(self.folder, "a.md"), os.path.join(self.folder, "b.md")
        Path(self.a).write_text("test.\n", encoding="utf-8")
        Path(self.b).write_text("test.\n", encoding="utf-8")

    def run_denied(self, taken):
        started = time.monotonic()
        with mock.patch.object(check.os, "open", denied(self.state, os.open)), \
                mock.patch.object(check, "_temporary_name_taken", taken):
            code, out, err = call(["run", "--source", self.a, "--final", self.b, "--state-dir", self.state])
        return code, out, err, time.monotonic() - started

    def test_denied_folder_ends_with_not_writable(self):
        code, out, err, seconds = self.run_denied(lambda path: os.path.isdir(path))
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn("reason=not_writable", lines[1])
        # 書き込みを拒まれたときは、ほかの OS ユーザーが作った状態フォルダかもしれないことと、分ける方法を出す
        self.assertIn(check._DENIED_STATE_NOTE, lines[0])
        self.assertIn("--state-dir か YOMIYASU_STATE_DIR で自分が書ける場所を指定して", lines[0])
        # 書けなかったのは一時ファイルの名前ではなく、状態フォルダとして示す
        self.assertRegex(lines[0], "（" + re.escape(self.state) + r"[^（）]* に書けません: Permission denied）")
        self.assertNotIn(".tmp-", lines[0])
        self.assertLess(seconds, 30)

    def test_even_if_every_name_looks_taken_run_ends(self):
        """拒まれた名前をすべてフォルダとみなす最悪の場合も、100回で止まって reason=not_writable で終わる。"""
        code, out, err, seconds = self.run_denied(lambda path: True)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn("reason=not_writable", lines[1])
        # 名前を決められなかった（拒まれたのではない）ので、ユーザーを分ける案内は足さない
        self.assertNotIn(check._DENIED_STATE_NOTE, lines[0])
        self.assertIn("--state-dir に書ける場所を指定して", lines[0])
        self.assertLess(seconds, 30)


@unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                 "書き込みの権限を外したフォルダで試す（Windows と root では権限で拒めない）")
class StartWithUnwritableStateTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="yomiyasu-v212-")
        self.state = os.path.join(self.folder, "state")
        os.mkdir(self.state)
        os.chmod(self.state, 0o500)

        def cleanup():
            os.chmod(self.state, 0o700)
            __import__("shutil").rmtree(self.folder, ignore_errors=True)
        self.addCleanup(cleanup)
        self.source = os.path.join(self.folder, "a.md")
        Path(self.source).write_text("原稿です。\n", encoding="utf-8")
        self.final = os.path.join(self.folder, "b.md")
        Path(self.final).write_text("原稿を直しました。\n", encoding="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(CHECK)] + list(args) + ["--state-dir", self.state],
                              cwd=self.folder, capture_output=True, timeout=60)

    def test_start_explains_instead_of_traceback(self):
        result = self.cli("start", "--source", self.source)
        stderr = result.stderr.decode("utf-8")
        self.assertEqual(result.returncode, 3, stderr)
        self.assertRegex(stderr, "原稿を登録できませんでした（" + re.escape(self.state) + r"[^（）]* に書けません: Permission denied）")
        self.assertNotIn(".tmp-", stderr)
        self.assertIn(check._DENIED_STATE_NOTE, stderr)
        self.assertIn("--state-dir か YOMIYASU_STATE_DIR で自分が書ける場所を指定して", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(result.stdout, b"")

    def test_run_ends_with_not_writable(self):
        result = self.cli("run", "--source", self.source, "--final", self.final)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        lines = result.stdout.decode("utf-8").splitlines()
        self.assertIn("reason=not_writable", lines[1])
        self.assertIn(check._DENIED_STATE_NOTE, lines[0])


if __name__ == "__main__":
    unittest.main()
