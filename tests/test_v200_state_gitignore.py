#!/usr/bin/env python3
"""v2.0.0: 既定の規則で決めた状態フォルダ（.yomiyasu/）がすでにあるときの .gitignore と state.json。

yomiyasu_check.py の状態フォルダは、--state-dir、環境変数 YOMIYASU_STATE_DIR、.git のあるフォルダの .yomiyasu/、
作業ディレクトリの .yomiyasu/ の順で決める（state_dir_for の1〜4）。3と4で決めたフォルダがすでにあり、state.json も
.gitignore もないときは、作ったときと同じ中身の2つを書く（ほかのファイルには触れない）。.yomiyasu/ を先に作られると
.gitignore がないまま原文と最終稿の全文の写し（inputs）が書かれ、git status に出てコミットされるおそれがあるため。
--state-dir と環境変数で決めたフォルダ、state.json があって .gitignore がないフォルダ（利用者が消したかもしれない）は
今のまま足さない。run、start、フックの登録（start_run）で同じ決まりにする。

試験は一時フォルダの中に .git を作るか（3）、.git のない一時フォルダを作業ディレクトリにして（4）、
YOMIYASU_STATE_DIR なしで subprocess で動かす。文はすべて合成。
"""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "yomiyasu_check.py"
HOOK = ROOT / "scripts" / "yomiyasu_hook.py"
GITIGNORE_BYTES = "# yomiyasu の検査記録。git に入れない。\n*\n".encode("utf-8")
STATE_JSON_BYTES = b'{"format": "yomiyasu-state", "format_version": 1}\n'
NOTE_BYTES = "利用者のメモです。\n".encode("utf-8")

# check を、ファイルの置き方を1つだけ変えて動かす（書けなかったときの片付けと、並列の run の割り込みを見る）。
# refuse: 名前が name のファイルを置けない（os.link も、リンクを作れないときの O_EXCL の os.open も失敗する）
# nolink: ハードリンクを作れないファイルシステム（os.link がいつも EPERM。O_EXCL で作る道を通る）
# race: 名前が name のファイルを置く直前に、ほかの run か利用者が同じ名前に別の中身のファイルを置く
# mkdir_race: 状態フォルダ（名前が name）の os.mkdir の直前に、並列の run が同じフォルダを作る
WORKER = r'''
import errno, os, runpy, sys
mode, name, script = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.dirname(script))
real_link, real_open, real_mkdir = os.link, os.open, os.mkdir
def link(src, dst, *args, **kwargs):
    if mode == "nolink":
        raise OSError(errno.EPERM, "試験で起こしたリンクの失敗", os.fspath(dst))
    if os.path.basename(os.fspath(dst)) == name:
        if mode == "refuse":
            raise PermissionError(13, "試験で起こした書き込みの失敗", os.fspath(dst))
        if mode == "race":
            with open(os.fspath(dst), "wb") as stream:
                stream.write(b"# other\n")
    return real_link(src, dst, *args, **kwargs)
def open_(path, flags, *args, **kwargs):
    if mode == "refuse" and os.path.basename(os.fspath(path)) == name:
        raise PermissionError(13, "試験で起こした書き込みの失敗", os.fspath(path))
    return real_open(path, flags, *args, **kwargs)
def mkdir(path, *args, **kwargs):
    if mode == "mkdir_race" and os.path.basename(os.fspath(path)) == name:
        real_mkdir(path, 0o755)
        raise FileExistsError(errno.EEXIST, "試験で起こした並列の mkdir", os.fspath(path))
    return real_mkdir(path, *args, **kwargs)
os.link, os.open, os.mkdir = link, open_, mkdir
sys.argv = [script] + sys.argv[4:]
runpy.run_path(script, run_name="__main__")
'''


def tree(folder):
    """フォルダの中のファイルとフォルダ（相対パス → (種類, 中身, 権限, 更新時刻)）。"""
    result = {}
    for path in sorted(Path(folder).rglob("*")):
        info = path.lstat()
        key = str(path.relative_to(folder))
        if path.is_dir():
            result[key] = ("dir", None, stat.S_IMODE(info.st_mode), None)
        else:
            result[key] = ("file", path.read_bytes(), stat.S_IMODE(info.st_mode), info.st_mtime_ns)
    return result


class StateGitignoreCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CHECK.is_file())
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-gitignore-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))

    def env(self, **extra):
        env = dict(os.environ)
        for name in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID", "CLAUDE_PROJECT_DIR"):
            env.pop(name, None)
        env["HOME"] = str(self.root)
        env.update(extra)
        return env

    def project(self, name="project", git=True):
        """.git のあるフォルダ（3）か、ないフォルダ（4）。作業ディレクトリは3では1段下の docs、4ではそのフォルダ。"""
        top = self.root / name
        work = top / "docs" if git else top
        work.mkdir(parents=True)
        if git:
            (top / ".git").mkdir()
        (work / "a.md").write_bytes("保存期間は3日です。\n".encode("utf-8"))
        (work / "b.md").write_bytes("保存期間は30日です。\n".encode("utf-8"))
        return top, work

    def no_git_above(self):
        if any((parent / ".git").exists() for parent in self.root.parents):
            self.skipTest("一時フォルダの上に .git がある（規則の4を試せない）")

    def check(self, cwd, *args, env=None, worker=None):
        """worker は (mode, name)。WORKER の決めで、ファイルの置き方を1つだけ変えて動かす。"""
        command = [sys.executable, "-B"]
        command += ["-c", WORKER, worker[0], worker[1], str(CHECK)] if worker else [str(CHECK)]
        return subprocess.run(command + [str(a) for a in args], cwd=str(cwd), env=env or self.env(),
                              capture_output=True, encoding="utf-8", timeout=60)

    def run_ok(self, cwd, *extra, env=None, expected="executed", worker=None):
        process = self.check(cwd, "run", "--source", "a.md", "--final", "b.md", *extra, env=env, worker=worker)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        line = process.stdout.splitlines()[1]
        self.assertTrue(line.startswith("yomiyasu-check: " + expected + " "), process.stdout)
        return process

    def assert_state_files(self, state):
        self.assertEqual((state / ".gitignore").read_bytes(), GITIGNORE_BYTES)
        self.assertEqual((state / "state.json").read_bytes(), STATE_JSON_BYTES)
        if os.name == "posix":
            for name in (".gitignore", "state.json"):
                self.assertEqual(stat.S_IMODE((state / name).stat().st_mode), 0o600, name)

    def assert_no_state_files(self, state):
        self.assertFalse(os.path.lexists(str(state / ".gitignore")))
        self.assertFalse(os.path.lexists(str(state / "state.json")))

    def existing(self, state, mode=0o755):
        """すでにある状態フォルダ（中身は別のファイルと別のフォルダだけ）。前の様子を返す。"""
        state.mkdir()
        (state / "note.txt").write_bytes(NOTE_BYTES)
        (state / "own").mkdir()
        (state / "own" / "keep.md").write_bytes("下書きの控えです。\n".encode("utf-8"))
        if os.name == "posix":
            os.chmod(str(state), mode)
        return tree(state)

    def assert_others_unchanged(self, state, before):
        after = tree(state)
        for key, value in before.items():
            self.assertEqual(after.get(key), value, key)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o755, "すでにあるフォルダの権限を変えた")


class TestDefaultRuleExistingFolder(StateGitignoreCase):
    def test_a_existing_folder_with_other_files_gets_gitignore_and_state_json(self):
        """(a) 既定の規則（3: .git のあるフォルダ、4: 作業ディレクトリ）で、すでにあって中身が別のファイルだけのフォルダ。
        run のあと .gitignore と state.json ができ、別のファイルは中身・権限・更新時刻とも変わらない。"""
        for git in (True, False):
            with self.subTest(git=git):
                if not git:
                    self.no_git_above()
                top, work = self.project("git" if git else "plain", git=git)
                state = top / ".yomiyasu"
                before = self.existing(state)
                self.run_ok(work)
                self.assert_state_files(state)
                self.assert_others_unchanged(state, before)
                self.assertTrue((state / "inputs").is_dir())
                if git:
                    self.assertFalse((work / ".yomiyasu").exists())

    def test_a_empty_existing_folder(self):
        """(a) mkdir -p .yomiyasu だけされた空のフォルダでも同じ（モデルが記録の前にフォルダを作った形）。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        state.mkdir()
        self.run_ok(work)
        self.assert_state_files(state)

    def test_a_second_run_does_not_rewrite(self):
        """書いたあとの run は、すでに2つあるので書き直さない（更新時刻が変わらない）。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        self.existing(state)
        self.run_ok(work)
        stamps = [(state / name).stat().st_mtime_ns for name in (".gitignore", "state.json")]
        self.run_ok(work)
        self.assertEqual(stamps, [(state / name).stat().st_mtime_ns for name in (".gitignore", "state.json")])

    def test_a_no_record_writes_nothing(self):
        """--no-record では、すでにあるフォルダにも何も書かない（今のまま）。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        before = self.existing(state)
        self.run_ok(work, "--no-record", expected="unrecorded")
        self.assertEqual(tree(state), before)

    def test_a_write_failure_keeps_the_folder_and_a_placed_gitignore(self):
        """書けなかったら例外にして記録は書かない（unrecorded）。フォルダと別のファイルは残す。.gitignore を置けなかった
        ときは何も残さず、次の run で2つを書く。state.json を置けなかったときは、置けた .gitignore を残す（並列の run が
        そのあいだに書いた写しも git status に出ないように）。そのあとの run は .gitignore だけがあるフォルダとして扱う。"""
        for refused in ("state.json", ".gitignore"):
            with self.subTest(refused=refused):
                top, work = self.project("fail-" + refused.strip("."))
                state = top / ".yomiyasu"
                before = self.existing(state)
                self.run_ok(work, expected="unrecorded", worker=("refuse", refused))
                self.assertTrue(state.is_dir())
                after = tree(state)
                if refused == ".gitignore":
                    self.assertEqual(after, before)
                else:
                    self.assertEqual((state / ".gitignore").read_bytes(), GITIGNORE_BYTES)
                    self.assertEqual({k: v for k, v in after.items() if k != ".gitignore"}, before)
                self.assertEqual([n for n in os.listdir(str(state)) if n.startswith(".tmp-")], [])
                self.run_ok(work)
                if refused == ".gitignore":
                    self.assert_state_files(state)
                else:
                    self.assertEqual((state / ".gitignore").read_bytes(), GITIGNORE_BYTES)
                    self.assertFalse(os.path.lexists(str(state / "state.json")))
                self.assert_others_unchanged(state, before)

    def test_a_new_folder_write_failure(self):
        """新しく作ったフォルダでも同じ: .gitignore を置けなければフォルダごと消し、state.json を置けなければ
        .gitignore の入ったフォルダを残す（どちらも記録は書かない）。"""
        for refused in ("state.json", ".gitignore"):
            with self.subTest(refused=refused):
                top, work = self.project("newfail-" + refused.strip("."))
                state = top / ".yomiyasu"
                self.run_ok(work, expected="unrecorded", worker=("refuse", refused))
                if refused == ".gitignore":
                    self.assertFalse(os.path.lexists(str(state)))
                else:
                    self.assertEqual(sorted(os.listdir(str(state))), [".gitignore"])

    def test_a_gitignore_placed_by_someone_else_is_not_overwritten(self):
        """2つがないことを確かめてから置くまでのあいだに、ほかの run か利用者が .gitignore を置いたら、上書きせず、
        state.json も足さない（その .gitignore を置いた側の決まりに任せる）。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        before = self.existing(state)
        self.run_ok(work, worker=("race", ".gitignore"))
        self.assertEqual((state / ".gitignore").read_bytes(), b"# other\n")
        self.assertFalse(os.path.lexists(str(state / "state.json")))
        self.assert_others_unchanged(state, before)

    def test_a_state_json_placed_by_someone_else_is_not_overwritten(self):
        """.gitignore を置いたあと、state.json を置く前に別の state.json が置かれても、上書きも削除もしない。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        self.existing(state)
        self.run_ok(work, worker=("race", "state.json"))
        self.assertEqual((state / ".gitignore").read_bytes(), GITIGNORE_BYTES)
        self.assertEqual((state / "state.json").read_bytes(), b"# other\n")

    def test_a_without_hard_links(self):
        """ハードリンクを作れないファイルシステムでは O_EXCL で作る。中身と権限は同じで、一時ファイルを残さない。"""
        for existing in (True, False):
            with self.subTest(existing=existing):
                top, work = self.project("nolink-" + str(existing))
                state = top / ".yomiyasu"
                if existing:
                    before = self.existing(state)
                self.run_ok(work, worker=("nolink", ""))
                self.assert_state_files(state)
                if existing:
                    self.assert_others_unchanged(state, before)
                self.assertEqual([n for n in os.listdir(str(state)) if n.startswith(".tmp-")], [])

    def test_a_folder_made_by_a_parallel_run(self):
        """os.mkdir の直前に並列の run が同じ .yomiyasu/ を作ったときも、既定の規則なら自分で2つを置きにいく
        （作った側が置く前に写しを書かないように）。--state-dir で渡したフォルダには足さない（今のまま）。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        self.run_ok(work, worker=("mkdir_race", ".yomiyasu"))
        self.assert_state_files(state)
        given = self.root / "given-race"
        self.run_ok(work, "--state-dir", str(given), worker=("mkdir_race", "given-race"))
        self.assert_no_state_files(given)
        self.assertTrue((given / "runs").is_dir())

    def test_a_linked_state_folder_is_left_as_it_is(self):
        """.yomiyasu そのものがほかのフォルダへのリンクなら、リンクの先に2つを足さない（ほかの場所に書かないように）。"""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink がない")
        top, work = self.project()
        target = self.root / "linked-target"
        before = self.existing(target)
        try:
            os.symlink(str(target), str(top / ".yomiyasu"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink を作れない")
        self.run_ok(work)
        self.assert_no_state_files(target)
        self.assert_others_unchanged(target, before)


class TestGivenOrUserFolder(StateGitignoreCase):
    def test_b_state_dir_option_existing_folder_is_left_as_it_is(self):
        """(b) --state-dir で渡したすでにあるフォルダには書かない（既定の規則と同じ場所を渡したときも）。"""
        top, work = self.project()
        for place in (top / ".yomiyasu", self.root / "shared-state"):
            with self.subTest(place=place.name):
                before = self.existing(place)
                self.run_ok(work, "--state-dir", str(place))
                self.assert_no_state_files(place)
                self.assert_others_unchanged(place, before)
                self.assertTrue((place / "runs").is_dir())

    def test_c_environment_existing_folder_is_left_as_it_is(self):
        """(c) 環境変数 YOMIYASU_STATE_DIR で決めたすでにあるフォルダにも書かない。"""
        top, work = self.project()
        for place in (top / ".yomiyasu", self.root / "shared-state"):
            with self.subTest(place=place.name):
                before = self.existing(place)
                self.run_ok(work, env=self.env(YOMIYASU_STATE_DIR=str(place)))
                self.assert_no_state_files(place)
                self.assert_others_unchanged(place, before)
                self.assertTrue((place / "runs").is_dir())

    def test_c_unexpanded_environment_falls_back_to_the_default_rule(self):
        """展開されなかった ${…} の環境変数はないものとして扱うので、既定の規則のフォルダとして2つを書く。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        before = self.existing(state)
        self.run_ok(work, env=self.env(YOMIYASU_STATE_DIR="${CLAUDE_PROJECT_DIR}/.yomiyasu"))
        self.assert_state_files(state)
        self.assert_others_unchanged(state, before)

    def test_d_state_json_without_gitignore_is_left_as_it_is(self):
        """(d) state.json があって .gitignore がないフォルダ（利用者が消したかもしれない）には書かない。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        state.mkdir()
        (state / "state.json").write_bytes(STATE_JSON_BYTES)
        self.run_ok(work)
        self.assertFalse(os.path.lexists(str(state / ".gitignore")))
        self.assertEqual((state / "state.json").read_bytes(), STATE_JSON_BYTES)

    def test_d_gitignore_without_state_json_is_left_as_it_is(self):
        """.gitignore だけがあるフォルダ（利用者が書いたかもしれない）も、どちらもないときに当たらないので書かない。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        state.mkdir()
        own = "# 利用者の設定\ninputs/\n".encode("utf-8")
        (state / ".gitignore").write_bytes(own)
        self.run_ok(work)
        self.assertEqual((state / ".gitignore").read_bytes(), own)
        self.assertFalse(os.path.lexists(str(state / "state.json")))

    def test_d_dangling_link_counts_as_present(self):
        """.gitignore がリンク（先がない）でも「ある」とみなし、リンクの先に書かない。"""
        if not hasattr(os, "symlink"):
            self.skipTest("symlink がない")
        top, work = self.project()
        state = top / ".yomiyasu"
        state.mkdir()
        target = self.root / "elsewhere.txt"
        try:
            os.symlink(str(target), str(state / ".gitignore"))
        except (OSError, NotImplementedError):
            self.skipTest("symlink を作れない")
        self.run_ok(work)
        self.assertFalse(target.exists())
        self.assertTrue(os.path.islink(str(state / ".gitignore")))
        self.assertFalse(os.path.lexists(str(state / "state.json")))


class TestNewFolder(StateGitignoreCase):
    def test_e_new_folder_is_made_as_before(self):
        """(e) 新しく作るときは今と同じ: フォルダ 0o700、.gitignore と state.json は同じ中身で 0o600。"""
        for git in (True, False):
            with self.subTest(git=git):
                if not git:
                    self.no_git_above()
                top, work = self.project("new-git" if git else "new-plain", git=git)
                state = top / ".yomiyasu"
                self.run_ok(work)
                self.assert_state_files(state)
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o700)

    def test_e_existing_and_new_write_the_same_bytes(self):
        """すでにあるフォルダに書いた2つと、作ったフォルダに書いた2つは、バイトで同じ。"""
        top1, work1 = self.project("one")
        top2, work2 = self.project("two")
        self.existing(top1 / ".yomiyasu")
        self.run_ok(work1)
        self.run_ok(work2)
        for name in (".gitignore", "state.json"):
            self.assertEqual((top1 / ".yomiyasu" / name).read_bytes(), (top2 / ".yomiyasu" / name).read_bytes(), name)


class TestStartAndHook(StateGitignoreCase):
    def test_start_uses_the_same_rule(self):
        """start も run と同じ: 既定の規則のすでにあるフォルダには2つを書き、--state-dir で渡したフォルダには書かない。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        before = self.existing(state)
        process = self.check(work, "start", "--source", "a.md", "--json")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assert_state_files(state)
        self.assert_others_unchanged(state, before)
        given = self.root / "given-state"
        before = self.existing(given)
        process = self.check(work, "start", "--source", "b.md", "--state-dir", str(given), "--json")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assert_no_state_files(given)
        self.assert_others_unchanged(given, before)

    def test_start_with_environment_or_unexpanded_environment(self):
        """start も、環境変数で決めたすでにあるフォルダには書かず、展開されなかった ${…} なら既定の規則として2つを書く。"""
        top, work = self.project()
        given = self.root / "env-state"
        before = self.existing(given)
        process = self.check(work, "start", "--source", "a.md", "--json", env=self.env(YOMIYASU_STATE_DIR=str(given)))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assert_no_state_files(given)
        self.assert_others_unchanged(given, before)
        state = top / ".yomiyasu"
        before = self.existing(state)
        process = self.check(work, "start", "--source", "b.md", "--json",
                             env=self.env(YOMIYASU_STATE_DIR="${CLAUDE_PROJECT_DIR}/.yomiyasu"))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assert_state_files(state)
        self.assert_others_unchanged(state, before)

    def hook(self, work, prompt, *options, env=None):
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "A", "cwd": str(work), "prompt": prompt}
        process = subprocess.run([sys.executable, "-B", str(HOOK), "--host", "claude-code"] + list(options),
                                 input=json.dumps(payload).encode("utf-8"), cwd=str(work), env=env or self.env(),
                                 capture_output=True, timeout=25)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, b"")
        return process.stdout.decode("utf-8")

    def test_hook_registration_uses_the_same_rule(self):
        """フックの登録（start_run）も同じ決まりを通る: 既定の規則なら2つを書き、フックの --state-dir と環境変数で
        決めたフォルダには書かない。"""
        cases = (("default", (), None), ("option", ("--state-dir",), None), ("environment", (), "YOMIYASU_STATE_DIR"))
        for label, option, variable in cases:
            with self.subTest(label=label):
                top, work = self.project("hook-" + label)
                state = top / ".yomiyasu" if label == "default" else self.root / ("hook-state-" + label)
                before = self.existing(state)
                options = list(option) + [str(state)] if option else []
                env = self.env(**{variable: str(state)}) if variable else None
                output = self.hook(work, "/yomiyasu a.md を直して", *options, env=env)
                self.assertIn("登録しました", output)
                self.assertTrue((state / "armed").is_dir())
                if label == "default":
                    self.assert_state_files(state)
                else:
                    self.assert_no_state_files(state)
                self.assert_others_unchanged(state, before)


    def test_hook_with_unexpanded_environment_uses_the_default_rule(self):
        """フックでも、展開されなかった ${…} の環境変数はないものとして、既定の規則のフォルダに2つを書く。"""
        top, work = self.project()
        state = top / ".yomiyasu"
        before = self.existing(state)
        output = self.hook(work, "/yomiyasu a.md を直して", env=self.env(YOMIYASU_STATE_DIR="${CLAUDE_PROJECT_DIR}/x"))
        self.assertIn("登録しました", output)
        self.assert_state_files(state)
        self.assert_others_unchanged(state, before)

    def test_hook_error_log_is_not_written_into_a_bare_folder(self):
        """フックが失敗したとき、.gitignore も state.json もないフォルダ（check が用意していない .yomiyasu/）には
        hook-errors.log を書かない（git status に出ないように）。2つのどちらかがあれば今のまま書く。"""
        scripts = self.root / "isolated-scripts"
        scripts.mkdir()
        copied = scripts / "yomiyasu_hook.py"
        shutil.copyfile(str(HOOK), str(copied))
        (scripts / "yomiyasu_check.py").write_text("raise RuntimeError('x')\n", encoding="utf-8")
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "A", "prompt": "/yomiyasu a.md を直して"}
        for prepared in ("bare", "gitignore", "state.json"):
            with self.subTest(prepared=prepared):
                top, work = self.project("hookerr-" + prepared.strip("."))
                state = top / ".yomiyasu"
                state.mkdir()
                if prepared == "gitignore":
                    (state / ".gitignore").write_bytes(GITIGNORE_BYTES)
                elif prepared == "state.json":
                    (state / "state.json").write_bytes(STATE_JSON_BYTES)
                process = subprocess.run([sys.executable, "-B", str(copied), "--host", "claude-code"],
                                         input=json.dumps(dict(payload, cwd=str(work))).encode("utf-8"), cwd=str(work),
                                         env=self.env(), capture_output=True, timeout=25)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stdout, b"")
                log = state / "hook-errors.log"
                if prepared == "bare":
                    self.assertEqual(os.listdir(str(state)), [])
                else:
                    self.assertIn("RuntimeError", log.read_text(encoding="utf-8"))


class TestPlaceNewFile(StateGitignoreCase):
    """_place_new_file の片付け（同じプロセスで呼ぶ）。"""

    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_yomiyasu_check_place", str(CHECK))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_cleanup_does_not_remove_a_file_put_by_someone_else(self):
        """O_EXCL で作ってから書けなかったときに、そのあいだに同じ名前へ別のファイルが置き直されていたら消さない。
        置き直されていなければ、自分が作ったファイルを消す。"""
        check = self.load()
        folder = self.root / "place"
        folder.mkdir()
        real_link, real_fdopen = check.os.link, check.os.fdopen
        for replaced in (True, False):
            with self.subTest(replaced=replaced):
                path = folder / ("target-" + str(replaced))

                def no_link(src, dst, *args, **kwargs):
                    raise OSError(1, "リンクを作れない")

                def failing_fdopen(handle, mode="r", *args, **kwargs):
                    stream = real_fdopen(handle, mode, *args, **kwargs)
                    if mode == "wb" and os.path.lexists(str(path)) and os.path.getsize(str(path)) == 0:
                        if replaced:
                            other = folder / "other.tmp"
                            other.write_bytes(b"other\n")
                            os.replace(str(other), str(path))
                        stream.close()
                        raise OSError(28, "試験で起こした書き込みの失敗")
                    return stream

                check.os.link, check.os.fdopen = no_link, failing_fdopen
                try:
                    with self.assertRaises(OSError):
                        check._place_new_file(str(path), b"data\n")
                finally:
                    check.os.link, check.os.fdopen = real_link, real_fdopen
                if replaced:
                    self.assertEqual(path.read_bytes(), b"other\n")
                else:
                    self.assertFalse(os.path.lexists(str(path)))
                self.assertEqual([n for n in os.listdir(str(folder)) if n.startswith(".tmp-")], [])


class TestGitStatus(StateGitignoreCase):
    def git(self, cwd, *args):
        env = self.env(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        process = subprocess.run(["git"] + list(args), cwd=str(cwd), env=env, capture_output=True,
                                 encoding="utf-8", timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return process.stdout

    def test_f_git_status_does_not_show_inputs(self):
        """(f) 一時の git リポジトリで、.yomiyasu/ を先に作ってから run しても、git status に inputs が出ない。"""
        if shutil.which("git") is None:
            self.skipTest("git がない")
        top = self.root / "repo"
        work = top / "docs"
        work.mkdir(parents=True)
        self.git(top, "init", "-q")
        (work / "a.md").write_bytes("保存期間は3日です。\n".encode("utf-8"))
        (work / "b.md").write_bytes("保存期間は30日です。\n".encode("utf-8"))
        self.git(top, "add", "docs")
        self.git(top, "commit", "-q", "-m", "docs")
        state = top / ".yomiyasu"
        state.mkdir()
        self.run_ok(work)
        self.assertTrue(any((state / "inputs").glob("*.bin")), "inputs に写しがない（試験の前提）")
        status = self.git(top, "status", "--porcelain", "--untracked-files=all", "--ignored=no")
        self.assertEqual([line for line in status.splitlines() if ".yomiyasu" in line], [], status)
        ignored = self.git(top, "status", "--porcelain", "--untracked-files=all", "--ignored")
        self.assertTrue(any(line.startswith("!! .yomiyasu/") for line in ignored.splitlines()), ignored)

    def test_f_git_status_after_state_json_failure(self):
        """state.json を置けなかった run のあとも .gitignore が残るので、次の run の写しは git status に出ない。"""
        if shutil.which("git") is None:
            self.skipTest("git がない")
        top = self.root / "repo2"
        work = top / "docs"
        work.mkdir(parents=True)
        self.git(top, "init", "-q")
        (work / "a.md").write_bytes("保存期間は3日です。\n".encode("utf-8"))
        (work / "b.md").write_bytes("保存期間は30日です。\n".encode("utf-8"))
        state = top / ".yomiyasu"
        state.mkdir()
        self.run_ok(work, expected="unrecorded", worker=("refuse", "state.json"))
        self.run_ok(work)
        self.assertTrue(any((state / "inputs").glob("*.bin")), "inputs に写しがない（試験の前提）")
        status = self.git(top, "status", "--porcelain", "--untracked-files=all", "--ignored=no")
        self.assertEqual([line for line in status.splitlines() if ".yomiyasu" in line], [], status)


if __name__ == "__main__":
    unittest.main()
