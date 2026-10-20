#!/usr/bin/env python3
"""v2.1.1: 壊れた文字や UTF-8 で読めないファイル名、CR だけの改行で、フックと check が止まらないことの試験。

- フックの投稿の本文の欄に、対になっていないサロゲート（JSON の "\\ud800"）が入っていても、フック全体が判定を出さずに
  終わらない（2.1.0 は UnicodeEncodeError で何も出さず、ホストは許可とみなしていた）。ほかの欄の本文はいつもどおり
  確かめて deny を出し、壊れた欄そのものは登録した原稿と照合できない本文として扱う。
- UTF-8 として読めないバイトを含むファイル名（Python には '\\udcff' として届く）の原稿を、start とフックで登録でき、
  start、run、verify、フックが同じ登録を見つける（2.1.0 は start が引数の誤りで終わり、フックは黙って登録しなかった）。
  そういう名前を作れないファイルシステム（macOS の APFS など）と Windows では、ファイルを使う試験を飛ばす。
  名前を作らずに済む関数の試験は、どこでも動く。
- run --stdin は、ファイル入力と同じく LF、CRLF、CR のどの改行でも区切りの行を見つける（2.1.0 は CR だけの入力を
  区切りの誤りとして止めていた）。CRLF と LF の入力は、各部分のバイト列も記録も前と同じ。

文はすべて合成。
"""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts" / "yomiyasu_check.py"
HOOK = ROOT / "scripts" / "yomiyasu_hook.py"

SOURCE_TEXT = "登録した原稿です。\n"
FINAL_TEXT = "登録した原稿を少し直しました。\n"
BAD_NAME = "bad-\udcff.md"


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


class _Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v211-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.project = self.root / "p"
        (self.project / ".git").mkdir(parents=True)
        self.state = self.root / "st"
        self.env = dict(os.environ, HOME=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        for name in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID", "CLAUDE_PROJECT_DIR"):
            self.env.pop(name, None)

    def check(self, *args, **kwargs):
        stdin = kwargs.pop("stdin", None)
        state = kwargs.pop("state", self.state)
        command = [sys.executable, "-B", str(CHECK)] + list(args) + ["--state-dir", str(state)]
        return subprocess.run(command, cwd=str(self.project), env=self.env, input=stdin,
                              capture_output=True, timeout=60)

    def hook(self, payload, state=None):
        data = dict(session_id="s1", cwd=str(self.project))
        data.update(payload)
        result = subprocess.run([sys.executable, "-B", str(HOOK), "--host", "claude-code",
                                 "--state-dir", str(state or self.state)],
                                input=json.dumps(data).encode("ascii"), cwd=str(self.project), env=self.env,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        return result.stdout.decode("utf-8")

    def errors_log(self, state=None):
        path = Path(str(state or self.state)) / "hook-errors.log"
        return path.read_text(encoding="ascii") if path.exists() else ""


class HookBrokenFieldTests(_Case):
    """フックの本文の欄に対になっていないサロゲートがあっても、ほかの欄の本文を確かめる。"""

    def setUp(self):
        super().setUp()
        (self.project / "s.md").write_text(SOURCE_TEXT, encoding="utf-8")
        (self.project / "f.md").write_text(FINAL_TEXT, encoding="utf-8")
        result = self.check("start", "--source", "s.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        # 時間切れで検査を終えられない回にする（登録した原稿の最終稿が、検査記録と照合できない状態）
        self.check("run", "--source", "s.md", "--final", "f.md", "--timeout", "0.000001")

    def pre(self, tool_name, tool_input):
        return self.hook({"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input})

    def decision(self, output):
        return json.loads(output)["hookSpecificOutput"]["permissionDecision"] if output else None

    def test_broken_field_does_not_hide_registered_body(self):
        """壊れた欄が先にあっても、同じ tool_input の登録した本文で deny が出る（2.1.0 は空の出力＝許可）。"""
        self.assertEqual(self.decision(self.pre("mcp__post", {"body": FINAL_TEXT})), "deny")
        for tool_input in ({"description": "\ud800", "body": FINAL_TEXT},
                           {"body": FINAL_TEXT, "notes": "途中で切れた\udfff"},
                           {"text": "\udcff", "inner": {"content": FINAL_TEXT}}):
            with self.subTest(tool_input=sorted(tool_input)):
                self.assertEqual(self.decision(self.pre("mcp__post", tool_input)), "deny")
        self.assertNotIn("UnicodeEncodeError", self.errors_log())
        self.assertEqual(self.errors_log(), "")

    def test_broken_field_alone_is_not_an_error(self):
        """壊れた欄だけの入力は、登録した原稿と照合できない本文として扱い、例外を出さない。"""
        for value in ("\ud800", FINAL_TEXT.rstrip("\n") + "\ud800", "\udcff\udcfe"):
            with self.subTest(value=ascii(value)):
                self.assertEqual(self.pre("mcp__post", {"description": value}), "")
        self.assertEqual(self.errors_log(), "")

    def test_broken_bash_body_does_not_hide_registered_body(self):
        """gh の --body に壊れた文字があっても、ほかのコマンドの本文で deny が出る。"""
        body = FINAL_TEXT.rstrip("\n")
        command = "gh issue comment 1 --body '\ud800'; gh pr comment 1 --body '{}'".format(body)
        self.assertEqual(self.decision(self.pre("Bash", {"command": command})), "deny")
        self.assertEqual(self.pre("Bash", {"command": "gh pr comment 1 --body '\ud800'"}), "")
        self.assertEqual(self.errors_log(), "")

    def test_bodies_keep_broken_field_as_non_utf8_bytes(self):
        """_bodies は壊れた欄を UTF-8 として読めないバイト列にし、ほかの欄はいつもの UTF-8 にする。"""
        hook = load(HOOK, "_yomiyasu_hook_v211_textsafety")
        check = load(CHECK, "_yomiyasu_check_v211_textsafety_hook")
        bodies = hook._bodies({"tool_name": "mcp__post",
                               "tool_input": {"description": "\ud800", "body": FINAL_TEXT}}, str(self.project))
        self.assertEqual([item[0] for item in bodies], [b"\xed\xa0\x80", FINAL_TEXT.encode("utf-8")])
        with self.assertRaises(UnicodeError):
            check.text_sha256_of(bodies[0][0])
        self.assertEqual(check.text_sha256_of(bodies[1][0]), check.text_sha256_of(FINAL_TEXT.encode("utf-8")))


class NonUtf8NameKeyTests(unittest.TestCase):
    """UTF-8 で読めないファイル名を、ファイルを作らずに関数で確かめる（どの OS でも動く）。"""

    @classmethod
    def setUpClass(cls):
        cls.check = load(CHECK, "_yomiyasu_check_v211_textsafety")

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v211-")
        self.addCleanup(folder.cleanup)
        self.root = os.path.realpath(folder.name)
        self.state = os.path.join(self.root, "st")
        self.real = os.path.join(self.root, "draft.md")
        with open(self.real, "w", encoding="utf-8") as stream:
            stream.write(SOURCE_TEXT)
        self.name = os.path.join(self.root, BAD_NAME)
        check, real, original = self.check, self.real, self.check._managed_input

        def managed_input(path):
            # 中身は作れる名前のファイルから読み、パスだけ読めない名前にする
            if path == self.name:
                item = original(real)
                item.path = os.path.abspath(path)
                return item
            return original(path)
        check._managed_input = managed_input
        self.addCleanup(setattr, check, "_managed_input", original)

    def test_start_registers_and_run_finds_same_registration(self):
        """start が登録でき、run が使う2つの探し方（登録と start の索引）が同じ登録を見つける。"""
        entry = self.check.start_run(self.state, self.name, cwd=self.root)
        self.assertEqual(entry["targets"]["source"]["path"], self.name)
        source = self.check._managed_input(self.name)
        found = self.check._armed_for_source(self.state, source)
        self.assertIsNotNone(found)
        self.assertEqual(found["run_id"], entry["run_id"])
        run_id, snapshot = self.check._start_snapshot(self.state, self.name, cwd=self.root)
        self.assertEqual(run_id, entry["run_id"])
        self.assertEqual(snapshot.data, SOURCE_TEXT.encode("utf-8"))
        # 同じ名前の2回目の start は、同じロックを取り、前の登録を終える
        second = self.check.start_run(self.state, self.name, cwd=self.root)
        statuses = {e["run_id"]: e["status"] for e in self.check.armed_entries(self.state)}
        self.assertEqual(statuses, {entry["run_id"]: "ended", second["run_id"]: "active"})
        self.assertEqual([name for name in os.listdir(os.path.join(self.state, "armed")) if name.endswith(".lock")], [])

    def test_keys_match_filesystem_bytes(self):
        """登録のロックと索引のキーは、ファイルシステムのバイト列と同じ surrogateescape のバイト列から作る。"""
        place = self.check._armed_place(self.name)
        self.assertEqual(place.encode("utf-8", "surrogateescape"),
                         os.path.normcase(os.path.realpath(self.name)).encode("utf-8", "surrogateescape"))
        self.assertTrue(place.encode("utf-8", "surrogateescape").endswith(b"bad-\xff.md")
                        or os.name == "nt")


_REGISTRATION_WRAPPER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('_yomiyasu_hook_wrapper', sys.argv[1])
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
hook._process = lambda *args, **kwargs: '原稿 ' + sys.argv[3].encode('ascii').decode('unicode_escape') + ' を登録しました。'
sys.exit(hook.main(['--host', 'claude-code', '--state-dir', sys.argv[2]]))
"""


class HookRegistrationOutputTests(_Case):
    """登録の知らせ（平文）に UTF-8 で読めない名前が入っても、フックが書き出しで止まらない。"""

    def test_registration_text_with_lone_surrogate_is_written(self):
        (self.project / "s.md").write_text(SOURCE_TEXT, encoding="utf-8")
        self.assertEqual(self.check("start", "--source", "s.md").returncode, 0)
        payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": str(self.project),
                              "prompt": "/yomiyasu " + BAD_NAME})
        result = subprocess.run([sys.executable, "-B", "-c", _REGISTRATION_WRAPPER, str(HOOK), str(self.state),
                                 "bad-\\udcff.md"], input=payload.encode("ascii"), cwd=str(self.project),
                                env=self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode("utf-8"), "原稿 bad-\\udcff.md を登録しました。\n")
        self.assertEqual(self.errors_log(), "")


def _make_bad_name(folder):
    """UTF-8 で読めない名前のファイルを作る。作れなければ None。"""
    if os.name == "nt":
        return None
    path = os.path.join(str(folder), BAD_NAME)
    try:
        with open(path, "wb") as stream:
            stream.write("原稿です。\n".encode("utf-8"))
    except (OSError, UnicodeError):
        return None
    if BAD_NAME not in os.listdir(str(folder)):
        return None
    return path


class NonUtf8NameEndToEndTests(_Case):
    """UTF-8 で読めない名前のファイルを実際に作り、start、run、verify、フックを動かす。"""

    def setUp(self):
        super().setUp()
        if _make_bad_name(self.project) is None:
            self.skipTest("このファイルシステムでは UTF-8 で読めないファイル名を作れません")
        (self.project / "f.md").write_text("原稿を直しました。\n", encoding="utf-8")

    def test_start_run_verify_share_registration(self):
        result = self.check("start", "--source", BAD_NAME, "--json")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        run_id = json.loads(result.stdout)["run_id"]
        result = self.check("run", "--source", BAD_NAME, "--final", "f.md", "--json")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(json.loads(result.stdout)["run_id"], run_id)
        result = self.check("verify", "--source", BAD_NAME, "--final", "f.md", "--json")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        verified = json.loads(result.stdout)
        self.assertEqual((verified["status"], verified["run_id"]), ("executed", run_id))

    def test_hook_registers_and_run_finds_it(self):
        output = self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "/yomiyasu " + BAD_NAME})
        self.assertIn("additionalContext", output)
        self.assertEqual(self.errors_log(), "")
        armed = self.state / "armed"
        entries = [json.loads(p.read_text(encoding="ascii")) for p in armed.glob("*.json")]
        self.assertEqual(len(entries), 1)
        self.assertEqual(os.path.basename(entries[0]["targets"]["source"]["path"]), BAD_NAME)
        result = self.check("run", "--source", BAD_NAME, "--final", "f.md", "--json")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(json.loads(result.stdout)["run_id"], entries[0]["run_id"])


class StdinLineEndTests(_Case):
    """run --stdin とファイル入力が、LF、CRLF、CR のどれでも同じ結果になる。"""

    SOURCE = ("設定を更新します。", "", "つまり、要するに、値を確認します。")
    FINAL = ("設定を更新しました。", "", "つまり、要するに、値を確認しました。")

    def outputs(self, eol):
        source = eol.join(self.SOURCE) + eol
        final = eol.join(self.FINAL) + eol
        (self.root / "s.md").write_bytes(source.encode("utf-8"))
        (self.root / "f.md").write_bytes(final.encode("utf-8"))
        stdin = eol.join(["<<<yomiyasu:original>>>", source + "<<<yomiyasu:final>>>", final]).encode("utf-8")
        piped = self.check("run", "--stdin", "--json", stdin=stdin, state=self.root / ("st-in-" + str(len(eol))))
        filed = self.check("run", "--source", str(self.root / "s.md"), "--final", str(self.root / "f.md"), "--json",
                           state=self.root / ("st-file-" + str(len(eol)) + eol.replace("\r", "r").replace("\n", "n")))
        return piped, filed

    def test_same_status_and_counts_for_each_line_end(self):
        summaries = []
        for eol in ("\n", "\r\n", "\r"):
            with self.subTest(eol=ascii(eol)):
                piped, filed = self.outputs(eol)
                self.assertEqual(piped.returncode, 0, piped.stderr.decode("utf-8", "replace"))
                self.assertEqual(filed.returncode, 0, filed.stderr.decode("utf-8", "replace"))
                a, b = json.loads(piped.stdout), json.loads(filed.stdout)
                keys = ("status", "candidate_counts", "meaning_risk_count", "changed_places")
                self.assertEqual([a[k] for k in keys], [b[k] for k in keys])
                self.assertEqual(a["status"], "executed")
                summaries.append([a[k] for k in keys])
        self.assertEqual(summaries[0], summaries[1])
        self.assertEqual(summaries[0], summaries[2])

    def test_split_keeps_piece_bytes(self):
        """各部分のバイト列は書き換えない。CRLF と LF は2.1.0と同じ部分になり、CR だけの部分もファイルと同じバイト列。"""
        check = load(CHECK, "_yomiyasu_check_v211_textsafety_stdin")
        for eol in ("\n", "\r\n", "\r"):
            with self.subTest(eol=ascii(eol)):
                source = ("設定を更新します。" + eol + eol + "値を確かめます。" + eol).encode("utf-8")
                final = ("設定を更新しました。" + eol).encode("utf-8")
                data = (b"\xef\xbb\xbf<<<yomiyasu:original>>>" + eol.encode("ascii") + source
                        + b"<<<yomiyasu:final>>>" + eol.encode("ascii") + final)
                pieces, problem = check._split_stdin(data)
                self.assertIsNone(problem)
                self.assertEqual(pieces, [("source", source), ("final", final)])

    def test_bad_marker_line_number_with_cr(self):
        """CR だけの入力でも、区切りに似た誤った行は、その行の番号で知らせる。"""
        check = load(CHECK, "_yomiyasu_check_v211_textsafety_marker")
        data = "<<<yomiyasu:original>>>\r設定を更新します。\r<<<yomiyasu:fianl>>>\r設定を更新しました。\r".encode("utf-8")
        pieces, problem = check._split_stdin(data)
        self.assertIsNone(pieces)
        self.assertIn("3行目", problem)


if __name__ == "__main__":
    unittest.main()
