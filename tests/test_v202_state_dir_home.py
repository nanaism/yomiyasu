#!/usr/bin/env python3
"""v2.0.2: 状態フォルダの値の頭の ~ をホームフォルダに置き換える（check とフックで同じ規則）。

--state-dir と環境変数 YOMIYASU_STATE_DIR の値が「~」だけか「~/」で始まるとき（Windows では「~\\」も）だけ、
os.path.expanduser でホームフォルダに置き換える。シェルの引用符の中、エージェントの設定ファイルの環境変数、
Claude Code のフックの args では ~ が展開されないまま届き、2.0.1 までは作業ディレクトリの下に「~」という名前の
フォルダを作っていた。「~user/x」「~x」、途中に ~ がある値、絶対パス、ほかの相対パス、空白だけの値、${ を含む環境変数は
2.0.1 と同じに扱う。HOME がなく利用者の情報からも決まらないとき、ホームフォルダが空かルートだけのとき（HOME が
空の文字列のとき expanduser は「~/x」を「/x」にする）、expanduser が例外を出したときも、値をそのまま使う。

check とフックは同じフォルダを見つける必要があるので、両方の _home_path を同じ表で比べ、subprocess で
フックが登録した原稿を check が見つけること、check が登録した原稿をフックが見つけることを確かめる。
試験の HOME は一時フォルダにする（利用者のホームフォルダには書かない）。文はすべて合成。
"""

import contextlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "yomiyasu_check.py"
HOOK = ROOT / "scripts" / "yomiyasu_hook.py"

# 2.0.1 と同じに扱う値（頭が「~」だけでも「~/」でもない）
KEPT_VALUES = ("~user/state", "~x", "~~/state", "~.", "~state", "./~/state", "sub/~", "sub/~/state", " ~/state",
               "state", "../state", ".", "${HOME}/state", "~${HOME}", "~\\state" if os.sep == "/" else "~x\\state")


def load(path, name):
    """スクリプトを同じプロセスで読む。フックが書き換える sys.dont_write_bytecode は元に戻す。"""
    before = sys.dont_write_bytecode
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


class HomePathRule(unittest.TestCase):
    """_home_path の決まりを、check とフックで同じ表で比べる（同じプロセス）。"""

    @classmethod
    def setUpClass(cls):
        cls.check = load(CHECK, "_yomiyasu_check_home_path")
        cls.hook = load(HOOK, "_yomiyasu_hook_home_path")

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-home-")
        self.addCleanup(folder.cleanup)
        self.home = os.path.realpath(folder.name)
        patcher = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("YOMIYASU_STATE_DIR", "CLAUDE_PROJECT_DIR"):
            os.environ.pop(name, None)

    def both(self, value):
        result = self.check._home_path(value)
        self.assertEqual(self.hook._home_path(value), result, repr(value))
        return result

    def test_tilde_alone_and_tilde_slash_become_home(self):
        self.assertEqual(self.both("~"), self.home)
        self.assertEqual(self.both("~/state"), os.path.join(self.home, "state"))
        self.assertEqual(self.both("~/a/b"), os.path.join(self.home, "a", "b"))
        self.assertEqual(os.path.normpath(self.both("~/")), self.home)
        self.assertEqual(os.path.normpath(self.both("~//state")), os.path.join(self.home, "state"))

    def test_other_values_are_kept(self):
        """「~user/x」「~x」などは、その名前の利用者がいても置き換えない（root はたいていの機械にいる）。"""
        for value in KEPT_VALUES + ("~root/state", "~root", "/abs/state", ""):
            with self.subTest(value=value):
                self.assertEqual(self.both(value), value)

    def test_non_string_is_kept(self):
        for value in (None, Path("~/state")):
            with self.subTest(value=value):
                self.assertIs(self.check._home_path(value), value)
                self.assertIs(self.hook._home_path(value), value)

    @unittest.skipIf(os.name != "posix", "pwd がない")
    def test_without_home_the_user_database_is_used(self):
        """HOME がないときは expanduser と同じく、利用者の情報のホームフォルダ（ここでは読むだけで書かない）。"""
        import pwd
        try:
            expected = pwd.getpwuid(os.getuid()).pw_dir
        except KeyError:
            self.skipTest("利用者の情報がない")
        with mock.patch.dict(os.environ):
            os.environ.pop("HOME", None)
            self.assertEqual(self.both("~/state"), expected.rstrip("/") + "/state")

    def test_unknown_home_keeps_the_value(self):
        """ホームフォルダが決まらない（expanduser が値をそのまま返す）か、expanduser が例外を出したときは、
        2.0.1 と同じく値をそのまま使う。"""
        def unchanged(path):
            return path

        def broken(path):
            raise ImportError("pwd")

        for replacement in (unchanged, broken, lambda path: "~" + path):
            with self.subTest(replacement=replacement):
                with mock.patch("os.path.expanduser", replacement):
                    self.assertEqual(self.both("~/state"), "~/state")
                    self.assertEqual(self.both("~"), "~")

    @unittest.skipIf(os.name != "posix", "HOME を読むのは POSIX の expanduser")
    def test_empty_or_root_home_keeps_the_value(self):
        """HOME が空の文字列のとき、expanduser は「~/state」を「/state」に、「~」を「/」にする。状態フォルダを
        ファイルシステムのルートに置かないよう、ホームフォルダが空、空白だけ、ルートだけのときは値をそのまま使う
        （2.0.1 と同じく作業ディレクトリからの相対パス）。HOME が「/」のときも expanduser の結果は同じ。"""
        for home in ("", "/", "//", "  "):
            for value in ("~", "~/state", "~/", "~//state"):
                with self.subTest(home=home, value=value):
                    with mock.patch.dict(os.environ, {"HOME": home}):
                        self.assertEqual(self.both(value), value)

    def test_windows_empty_or_root_profile_keeps_the_value(self):
        """Windows（ntpath）でも、USERPROFILE が空かドライブのルートだけなら値をそのまま使う。"""
        for profile in ("", "C:\\", "C:", "\\"):
            with self.subTest(profile=profile):
                with mock.patch.dict(os.environ, {"USERPROFILE": profile}), mock.patch("os.sep", "\\"), \
                        mock.patch("os.path.expanduser", ntpath.expanduser), \
                        mock.patch("os.path.splitdrive", ntpath.splitdrive):
                    for value in ("~", "~\\state", "~/state"):
                        self.assertEqual(self.both(value), value)

    def test_windows_separators(self):
        """Windows（ntpath）では「~\\」でも置き換え、「~x」は置き換えない（ntpath の expanduser は ~x を
        C:\\Users\\x にするので、決まりの側で外す）。"""
        profile = "C:\\Users\\me"
        with mock.patch.dict(os.environ, {"USERPROFILE": profile}), \
                mock.patch("os.sep", "\\"), mock.patch("os.path.expanduser", ntpath.expanduser):
            self.assertEqual(self.both("~\\state"), "C:\\Users\\me\\state")
            self.assertEqual(ntpath.normpath(self.both("~/state")), "C:\\Users\\me\\state")
            self.assertEqual(self.both("~"), profile)
            for value in ("~x", "~x\\state", "sub\\~\\state", "C:\\state"):
                with self.subTest(value=value):
                    self.assertEqual(self.both(value), value)

    def test_check_and_hook_choose_the_same_first_folder(self):
        """state_dir_for（check）と _states の1つ目（フック）が、--state-dir と環境変数のどの組でも同じ。
        ~ の決まりに当たらない値は、2.0.1 の式（os.path.abspath(os.path.join(cwd, 値))）のまま。"""
        cwd = os.path.join(self.home, "work")
        os.mkdir(cwd)
        values = ("~", "~/state", "~/") + KEPT_VALUES + (os.path.join(self.home, "abs"),)
        for option in (None,) + values:
            for environment in (None, " ", "${CLAUDE_PROJECT_DIR}/x") + values:
                with self.subTest(option=option, environment=environment):
                    with mock.patch.dict(os.environ):
                        if environment is None:
                            os.environ.pop("YOMIYASU_STATE_DIR", None)
                        else:
                            os.environ["YOMIYASU_STATE_DIR"] = environment
                        chosen = self.check.state_dir_for(cwd, option)
                        self.assertEqual(self.hook._states(cwd, "codex", option)[0], chosen)
                        given = option or (environment if environment and environment.strip()
                                           and "${" not in environment else None)
                        self.assertEqual(self.check._state_dir_given(option), bool(given))
                        self.assertEqual(self.hook._state_given(option), bool(given))
                        if given is None:
                            self.assertEqual(chosen, os.path.join(cwd, ".yomiyasu"))
                        elif given == "~" or given.startswith("~/"):
                            self.assertEqual(chosen, os.path.normpath(os.path.join(self.home, given[2:])))
                        else:
                            self.assertEqual(chosen, os.path.abspath(os.path.join(cwd, given)))


class HomeStateFolder(unittest.TestCase):
    """subprocess で、check（run、verify、start、end）とフックが ~ の値から同じフォルダを見つける。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-home-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.home = self.root / "home"
        self.home.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        (self.work / "a.md").write_bytes("保存期間は3日です。\n".encode("utf-8"))
        (self.work / "b.md").write_bytes("保存期間は30日です。\n".encode("utf-8"))

    def env(self, **extra):
        env = dict(os.environ)
        for name in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID", "CLAUDE_PROJECT_DIR"):
            env.pop(name, None)
        env["HOME"] = str(self.home)
        env["USERPROFILE"] = str(self.home)
        env.update(extra)
        return env

    def check(self, *args, env=None, code=0):
        process = subprocess.run([sys.executable, "-B", str(CHECK)] + [str(a) for a in args], cwd=str(self.work),
                                 env=env or self.env(), capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
        return process

    def hook(self, prompt, *options, env=None):
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "A", "cwd": str(self.work), "prompt": prompt}
        process = subprocess.run([sys.executable, "-B", str(HOOK), "--host", "claude-code"] + list(options),
                                 input=json.dumps(payload).encode("utf-8"), cwd=str(self.work), env=env or self.env(),
                                 capture_output=True, timeout=25)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, b"")
        return process.stdout.decode("utf-8")

    def armed(self, state):
        folder = state / "armed"
        if not folder.is_dir():
            return {}
        return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in folder.glob("*.json")}

    def assert_no_tilde_folder(self):
        self.assertEqual(sorted(path.name for path in self.work.iterdir()), ["a.md", "b.md"])

    def test_run_and_verify_with_tilde_in_the_environment_and_the_option(self):
        """run の記録はホームフォルダの下にでき、verify も同じ記録を見つける。作業ディレクトリに ~ を作らない。"""
        cases = (("environment", (), {"YOMIYASU_STATE_DIR": "~/state-env"}, "state-env"),
                 ("option", ("--state-dir", "~/state-option"), {}, "state-option"))
        for label, option, variables, name in cases:
            with self.subTest(label=label):
                env = self.env(**variables)
                state = self.home / name
                process = self.check("run", "--source", "a.md", "--final", "b.md", *option, env=env)
                lines = process.stdout.splitlines()
                self.assertTrue(lines[1].startswith("yomiyasu-check: executed "), process.stdout)
                self.assertTrue(lines[4].startswith("記録: " + str(state / "runs") + os.sep), lines[4])
                self.assertIn('verify --state-dir "{}"'.format(state), lines[0])
                verify = self.check("verify", "--final", "b.md", *option, env=env)
                self.assertTrue(verify.stdout.splitlines()[1].startswith("yomiyasu-check: executed via=verify "),
                                verify.stdout)
                self.assert_no_tilde_folder()

    def test_quoted_tilde_and_shell_expanded_path_are_the_same_folder(self):
        """引用符の中の ~（展開されない）と、シェルが展開した絶対パスは同じフォルダ（2回目の run が attempt=2 になる）。"""
        state = self.home / "shared"
        self.check("run", "--source", "a.md", "--final", "b.md", "--state-dir", str(state))
        process = self.check("run", "--source", "a.md", "--final", "b.md", "--state-dir", "~/shared")
        self.assertIn(" attempt=2 ", process.stdout.splitlines()[1])
        self.assert_no_tilde_folder()

    def test_hook_registration_is_found_by_check(self):
        """フックが ~ の値で登録した原稿を、check の end が同じフォルダで見つけて終える。フックの --state-dir は
        Claude Code の args のように展開されずに届き、check にはシェルが展開した絶対パスを渡す組も見る。"""
        cases = (("environment", (), {"YOMIYASU_STATE_DIR": "~/hook-env"}, (), "hook-env"),
                 ("option", ("--state-dir", "~/hook-option"), {}, ("--state-dir", "~/hook-option"), "hook-option"),
                 ("mixed", ("--state-dir", "~/hook-mixed"), {}, ("--state-dir", str(self.home / "hook-mixed")),
                  "hook-mixed"))
        for label, hook_option, variables, check_option, name in cases:
            with self.subTest(label=label):
                env = self.env(**variables)
                state = self.home / name
                output = self.hook("/yomiyasu a.md を直して", *hook_option, env=env)
                self.assertIn("登録しました", output)
                entries = self.armed(state)
                self.assertEqual(len(entries), 1, entries)
                self.check("end", "--source", "a.md", *check_option, env=env)
                self.assertEqual([entry["status"] for entry in self.armed(state).values()], ["ended"])
                self.assert_no_tilde_folder()

    def test_check_registration_is_found_by_hook(self):
        """check の start が ~ の値で登録した原稿は、フックも同じフォルダで見つけ、二重に登録しない。"""
        env = self.env(YOMIYASU_STATE_DIR="~/start-env")
        state = self.home / "start-env"
        process = self.check("start", "--source", "a.md", "--session", "A", "--host", "claude-code", "--json", env=env)
        run_id = json.loads(process.stdout)["run_id"]
        self.assertEqual(list(self.armed(state)), [run_id])
        self.assertNotIn("登録しました", self.hook("/yomiyasu a.md を直して", env=env))
        self.assertEqual(list(self.armed(state)), [run_id])
        self.assert_no_tilde_folder()

    def test_values_outside_the_rule_behave_as_before(self):
        """「./~/x」「~x」「sub/~」のような値は、2.0.1 と同じく作業ディレクトリからの相対パス（check もフックも）。"""
        for value in ("./~/kept", "~kept", "sub/~"):
            with self.subTest(value=value):
                env = self.env(YOMIYASU_STATE_DIR=value)
                state = Path(os.path.abspath(os.path.join(str(self.work), value)))
                process = self.check("run", "--source", "a.md", "--final", "b.md", env=env)
                self.assertTrue(process.stdout.splitlines()[4].startswith("記録: " + str(state / "runs") + os.sep),
                                process.stdout)
                self.assertIn("登録しました", self.hook("/yomiyasu b.md を直して", env=env))
                self.assertEqual(len(self.armed(state)), 1)
                self.assertFalse((self.home / "kept").exists())
                top = [part for part in value.split("/") if part not in ("", ".")][0]
                shutil.rmtree(str(self.work / top))
                self.assert_no_tilde_folder()

    @unittest.skipIf(os.name != "posix", "HOME を読むのは POSIX の expanduser")
    def test_empty_home_keeps_the_value_in_check_and_hook(self):
        """HOME が空の文字列の環境では、~ の値を 2.0.1 と同じく作業ディレクトリからの相対パスとして使い、
        ファイルシステムのルートに状態フォルダを作らない（check の run と verify、フックで同じフォルダ）。"""
        env = self.env(HOME="", YOMIYASU_STATE_DIR="~/state-empty-home")
        state = self.work / "~" / "state-empty-home"
        process = self.check("run", "--source", "a.md", "--final", "b.md", env=env)
        self.assertTrue(process.stdout.splitlines()[4].startswith("記録: " + str(state / "runs") + os.sep),
                        process.stdout)
        verify = self.check("verify", "--final", "b.md", env=env)
        self.assertTrue(verify.stdout.splitlines()[1].startswith("yomiyasu-check: executed via=verify "),
                        verify.stdout)
        self.assertIn("登録しました", self.hook("/yomiyasu b.md を直して", env=env))
        self.assertEqual(len(self.armed(state)), 1)
        shutil.rmtree(str(self.work / "~"))
        self.assert_no_tilde_folder()

    @unittest.skipIf(os.name != "posix" or shutil.which("sh") is None, "sh がない")
    def test_tilde_works_without_a_working_directory_like_an_absolute_path(self):
        """~ を置き換えた値は絶対パスなので、作業ディレクトリが消えていても verify が記録を見つける（絶対パスと同じ）。"""
        env = self.env(YOMIYASU_STATE_DIR="~/state-gone")
        self.check("run", "--source", "a.md", "--final", "b.md", env=env)
        gone = self.root / "gone"
        gone.mkdir()
        process = subprocess.run(["sh", "-c", 'cd "$1" && rmdir "$1" && shift && exec "$@"', "sh", str(gone),
                                  sys.executable, "-B", str(CHECK), "verify", "--final", str(self.work / "b.md")],
                                 cwd=str(self.root), env=env, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(process.stdout.splitlines()[1].startswith("yomiyasu-check: executed via=verify "))


if __name__ == "__main__":
    unittest.main()
