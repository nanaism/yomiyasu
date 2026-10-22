"""v2.1.3: 状態フォルダの中の名前が、あるのにフォルダか確かめられない（Windows で一覧や属性の読み取りを拒まれた）とき、
run と start が、状態フォルダをユーザーごとに分ける案内を出すことを確かめる。

Windows では、`.yomiyasu/` の一覧を拒まれていても `.gitignore` は見え、`inputs` は属性を読めないことがある。そのとき
os.mkdir は FileExistsError を出し、os.path.isdir は False になる。2.1.2 はこの FileExistsError をそのまま出したので、
書き込みを拒まれたときの案内が出なかった。Windows の動きは os.mkdir、os.path.isdir、os.lstat を差し替えて再現する。
"""
from pathlib import Path
from unittest import mock
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "yomiyasu_check.py"


def load_check():
    before = sys.dont_write_bytecode
    try:
        spec = importlib.util.spec_from_file_location("_yomiyasu_check_v213_hidden", str(CHECK))
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


class HiddenNameTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="yomiyasu-v213-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))
        self.state = os.path.join(self.folder, "state")
        os.mkdir(self.state)
        # ほかのユーザーが作った状態フォルダ。.gitignore と state.json は見える
        check._write_state_files(self.state)
        self.a, self.b = os.path.join(self.folder, "a.md"), os.path.join(self.folder, "b.md")
        Path(self.a).write_bytes("これは確かめ用の原文です。\n".encode("utf-8"))
        Path(self.b).write_bytes("これは確かめ用の最終稿です。\n".encode("utf-8"))

    def hidden(self, name):
        """状態フォルダの中の name が、あるのにフォルダか確かめられない（属性の読み取りを拒まれた）状態をまねる。"""
        hidden = os.path.join(self.state, name)
        real_mkdir, real_isdir, real_lstat = os.mkdir, os.path.isdir, os.lstat

        def fake_mkdir(path, *args, **kwargs):
            if str(path) == hidden:
                raise FileExistsError(17, "File exists", str(path))
            return real_mkdir(path, *args, **kwargs)

        def fake_isdir(path):
            return False if str(path) == hidden else real_isdir(path)

        def fake_lstat(path, *args, **kwargs):
            if str(path) == hidden:
                raise PermissionError(13, "Permission denied", str(path))
            return real_lstat(path, *args, **kwargs)
        return [mock.patch.object(check.os, "mkdir", fake_mkdir),
                mock.patch.object(check.os.path, "isdir", fake_isdir),
                mock.patch.object(check.os, "lstat", fake_lstat)]

    def run_with(self, patches, argv):
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return call(argv)

    def test_run_shows_the_separate_state_guidance(self):
        code, out, err = self.run_with(self.hidden("inputs"),
                                       ["run", "--source", self.a, "--final", self.b, "--state-dir", self.state])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn("reason=not_writable", lines[1])
        self.assertIn(check._DENIED_STATE_NOTE, lines[0])
        self.assertIn("に書けません: Permission denied", lines[0])

    def test_start_shows_the_separate_state_guidance(self):
        code, out, err = self.run_with(self.hidden("runs"), ["start", "--source", self.a, "--state-dir", self.state])
        self.assertEqual(code, 3)
        self.assertIn(check._DENIED_STATE_NOTE, err)
        self.assertNotIn("Traceback", err)

    def test_a_file_in_the_way_is_still_file_exists(self):
        """名前がフォルダでなくファイルとして見えるとき（確かめられる）は、今までどおり FileExistsError のまま。"""
        Path(os.path.join(self.state, "inputs")).write_bytes(b"")
        code, out, err = call(["run", "--source", self.a, "--final", self.b, "--state-dir", self.state])
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn("reason=not_writable", lines[1])
        self.assertNotIn(check._DENIED_STATE_NOTE, lines[0])

    def test_the_state_folder_itself_hidden(self):
        """状態フォルダそのものが、あるのにフォルダか確かめられないときも、拒否として案内する。"""
        hidden = os.path.join(self.folder, "other")
        real_mkdir, real_isdir, real_lstat = os.mkdir, os.path.isdir, os.lstat

        def fake_mkdir(path, *args, **kwargs):
            if str(path) == hidden:
                raise FileExistsError(17, "File exists", str(path))
            return real_mkdir(path, *args, **kwargs)
        patches = [mock.patch.object(check.os, "mkdir", fake_mkdir),
                   mock.patch.object(check.os.path, "isdir", lambda path: False if str(path) == hidden else real_isdir(path)),
                   mock.patch.object(check.os, "lstat", lambda path, *a, **k: (_ for _ in ()).throw(
                       PermissionError(13, "Permission denied", str(path))) if str(path) == hidden else real_lstat(path, *a, **k))]
        code, out, err = self.run_with(patches, ["run", "--source", self.a, "--final", self.b, "--state-dir", hidden])
        self.assertEqual(code, 0, err)
        self.assertIn(check._DENIED_STATE_NOTE, out.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
