"""3.0.0: lint、diff、check は、コマンドラインで名前を渡されたファイルのうち、作業フォルダの外のファイルと、作業フォルダからの
道筋に点で始まる部分（.env、.git/config、sub/.secret/x.md など）を含むパスを読まない。

断るのは入力の誤り（終了コード2）で、何も書かない（check は状態フォルダも記録も作らない）。標準入力（- と check run --stdin）は
いつでも読める。作業フォルダの中のファイルの出力は前と同じ（ライブラリの関数の値と比べる）。道具が自分で探すフォルダ（状態
フォルダ、語の一覧、references/lists/）と --words のフォルダは、この決まりに当たらない。
文はすべて合成の文。ファイルは一時フォルダの中にだけ作る。
"""
from pathlib import Path
from unittest import mock
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import markdown_visibility  # noqa: E402
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402

LINT = SCRIPTS / "yomiyasu_lint.py"
DIFF = SCRIPTS / "yomiyasu_diff.py"
CHECK = SCRIPTS / "yomiyasu_check.py"

OUTSIDE = markdown_visibility.INPUT_PATH_OUTSIDE
HIDDEN = markdown_visibility.INPUT_PATH_HIDDEN
LINT_HINT = "このファイルを検査するときは、標準入力から渡してください（ファイルの名前の代わりに - を渡すか、省きます）"
DIFF_HINT = "このファイルを渡すときは、標準入力から渡してください（ファイルの名前の代わりに - を渡します。1か所だけ）"
RUN_HINT = ("このファイルを検査するときは、--stdin の区切りの行（<<<yomiyasu:original>>>、<<<yomiyasu:final>>> など）で"
            "標準入力から渡すか、ファイルの名前の代わりに - を渡してください（- は1か所だけ）")
VERIFY_HINT = "このファイルを照らすときは、ファイルの名前の代わりに - を渡して、標準入力から渡してください（--final と --source で1か所だけ）"
START_HINT = "start は標準入力を使えません。作業フォルダの中の、名前が点で始まらないファイルを渡してください"
EXPORT_HINT = ("export は標準入力を使えません。作業フォルダの中の、名前が点で始まらないファイルを渡すか、"
               "verify --final - で照らしてください")

SOURCE = "新しい手順を来週から試します。\n担当は三人です。\n"
FINAL = "新しい手順を来週から試します。\n担当は3人です。\n"
# 読ませたくないファイルの中身。断ったときに、標準出力にも標準エラーにも出ないことを確かめる
SECRET = "秘密の合言葉は青い鳥です。\n"
SECRET_WORD = "青い鳥"


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8"))
    return path


def message(path, reason, hint):
    return "Error opening file {}: {}。{}".format(path, reason, hint)


class PathCase(unittest.TestCase):
    """作業フォルダ work（.git があるので状態フォルダは work/.yomiyasu）と、その外の outside.md を一時フォルダに作る。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.work = self.root / "work"
        (self.work / ".git").mkdir(parents=True)
        (self.work / "a").mkdir()
        write(self.work / "source.md", SOURCE)
        write(self.work / "final.md", FINAL)
        write(self.work / "docs" / "note.md", FINAL)
        self.outside = write(self.root / "outside.md", SECRET)
        for name in (".env", ".git/config", "sub/.secret/x.md", ".hidden.md"):
            write(self.work / name, SECRET)
        self.env = dict(os.environ, HOME=str(self.root), PYTHONIOENCODING="utf-8")
        for name in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID", "CLAUDE_PROJECT_DIR"):
            self.env.pop(name, None)

    def run_tool(self, script, *args, stdin=None, cwd=None):
        return subprocess.run([sys.executable, "-B", str(script)] + [str(arg) for arg in args],
                              cwd=str(cwd or self.work), env=self.env, capture_output=True, timeout=120,
                              input=(stdin.encode("utf-8") if stdin is not None else None),
                              stdin=(subprocess.DEVNULL if stdin is None else None))

    def assertRefused(self, process, expected, usage=False):
        stdout = process.stdout.decode("utf-8")
        stderr = process.stderr.decode("utf-8")
        self.assertEqual(process.returncode, 2, stderr)
        self.assertEqual(stdout, "")
        if usage:
            # start と export は、ほかの読めないファイルと同じく使い方の誤りの形（使い方、error の行、案内の行）で出す
            self.assertIn(": error: " + expected + "\n", stderr)
        else:
            self.assertEqual(stderr, expected + "\n")
        self.assertNotIn(SECRET_WORD, stdout + stderr)

    def assertNothingWritten(self):
        self.assertFalse((self.work / ".yomiyasu").exists())


REFUSED = (
    # (渡すパスの作り方, 理由)
    (lambda case: case.outside, OUTSIDE),
    (lambda case: "../outside.md", OUTSIDE),
    (lambda case: ".env", HIDDEN),
    (lambda case: ".git/config", HIDDEN),
    (lambda case: "sub/.secret/x.md", HIDDEN),
    (lambda case: "a/../.env", HIDDEN),
    (lambda case: case.work / ".env", HIDDEN),
    (lambda case: ".hidden.md", HIDDEN),
)


class HelperTest(PathCase):
    def call(self, path):
        current = os.getcwd()
        os.chdir(str(self.work))
        try:
            return markdown_visibility.input_path_problem(str(path))
        finally:
            os.chdir(current)

    def test_refused_paths(self):
        for make, reason in REFUSED:
            path = make(self)
            with self.subTest(path=path):
                self.assertEqual(self.call(path), reason)

    def test_allowed_paths(self):
        for path in ("-", "final.md", "./final.md", self.work / "final.md", "docs/note.md", "docs/../final.md",
                     "missing.md", ""):
            with self.subTest(path=path):
                self.assertIsNone(self.call(path))

    def test_other_drive_is_outside(self):
        # Windows でドライブが違うと commonpath が ValueError を出す。同じフォルダもたどれないので、外のファイルとして断る
        with mock.patch.object(markdown_visibility.os.path, "commonpath", side_effect=ValueError("drives")):
            self.assertEqual(self.call(self.outside), OUTSIDE)
            self.assertEqual(self.call("../outside.md"), OUTSIDE)

    def test_unknown_place_is_outside(self):
        # NUL のほかの理由で realpath が場所を決められないときは、読まずに外とみなす
        real = os.path.realpath

        def realpath(path):
            if path == os.getcwd():
                return real(path)
            raise OSError("realpath")

        with mock.patch.object(markdown_visibility.os.path, "realpath", side_effect=realpath):
            self.assertEqual(self.call("final.md"), OUTSIDE)
        self.assertIsNone(self.call("final\0.md"))

    def test_same_folder_other_spelling(self):
        # macOS などで、大文字と小文字だけ、または日本語の名前の NFC と NFD だけが違うパスは、同じフォルダなら中とみなす。
        # 点で始まる部分と外のファイルは、同じように断る
        import unicodedata
        folder = self.work / unicodedata.normalize("NFD", "ガイド資料")
        write(folder / "a.md", FINAL)
        write(folder / ".env", SECRET)
        nfc = str(self.work / unicodedata.normalize("NFC", "ガイド資料"))
        if not os.path.exists(os.path.join(nfc, "a.md")):
            self.skipTest("このファイルシステムは NFC と NFD を別の名前として扱います")
        current = os.getcwd()
        os.chdir(str(folder))
        try:
            self.assertIsNone(markdown_visibility.input_path_problem(os.path.join(nfc, "a.md")))
            self.assertIsNone(markdown_visibility.input_path_problem(os.path.join(nfc, "missing.md")))
            self.assertEqual(markdown_visibility.input_path_problem(os.path.join(nfc, ".env")), HIDDEN)
            self.assertEqual(markdown_visibility.input_path_problem(str(self.outside)), OUTSIDE)
            upper = str(folder / "a.md").upper()
            if os.path.exists(upper):
                self.assertIsNone(markdown_visibility.input_path_problem(upper))
                self.assertEqual(markdown_visibility.input_path_problem(str(folder / ".ENV").upper()), HIDDEN)
            process = self.run_tool(LINT, "--no-words", os.path.join(nfc, "a.md"), cwd=folder)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        finally:
            os.chdir(current)

    def test_windows_paths(self):
        # Windows のパスの書き方（ntpath）で、作業フォルダ C:\Users\Me\Work から見た中と外。ファイルは開かない
        import ntpath
        import types
        work = "C:\\Users\\Me\\Work"

        def no_stat(path):
            raise OSError("no stat")

        # realpath は作業フォルダからつないで整えるだけにする（Windows で動かしても、本物の作業フォルダを見ない）
        path_module = types.SimpleNamespace(
            normcase=ntpath.normcase, commonpath=ntpath.commonpath, relpath=ntpath.relpath, split=ntpath.split,
            samestat=ntpath.samestat, realpath=lambda path: ntpath.normpath(ntpath.join(work, path)))
        fake = types.SimpleNamespace(path=path_module, sep="\\", curdir=".", getcwd=lambda: work, stat=no_stat)
        cases = (
            ("final.md", None), ("sub\\note.md", None), ("sub/note.md", None), (".\\final.md", None),
            (work + "\\final.md", None), ("c:\\users\\me\\work\\FINAL.md", None),
            (".env", HIDDEN), ("sub\\.secret\\x.md", HIDDEN), ("sub/.secret/x.md", HIDDEN),
            (work + "\\.git\\config", HIDDEN), ("C:\\Users\\Me\\.ssh\\id_rsa", OUTSIDE),
            ("..\\..\\.ssh\\id_rsa", OUTSIDE), ("D:\\Work\\final.md", OUTSIDE),
            ("\\\\server\\share\\x.md", OUTSIDE), ("C:\\Users\\Me\\Workshop\\a.md", OUTSIDE),
        )
        with mock.patch.object(markdown_visibility, "os", fake):
            for path, expected in cases:
                with self.subTest(path=path):
                    self.assertEqual(markdown_visibility.input_path_problem(path), expected)

    def test_symlink_inside_pointing_outside(self):
        link = self.work / "link.md"
        hidden_link = self.work / "hidden-link.md"
        try:
            os.symlink(str(self.outside), str(link))
            os.symlink(str(self.work / ".env"), str(hidden_link))
        except (OSError, NotImplementedError) as error:
            self.skipTest("シンボリックリンクを作れません（{}）".format(error))
        self.assertEqual(self.call("link.md"), OUTSIDE)
        self.assertEqual(self.call("hidden-link.md"), HIDDEN)


class LintTest(PathCase):
    def test_refused(self):
        for make, reason in REFUSED:
            path = make(self)
            with self.subTest(path=path):
                self.assertRefused(self.run_tool(LINT, path), message(path, reason, LINT_HINT))
                self.assertRefused(self.run_tool(LINT, "--json", path), message(path, reason, LINT_HINT))

    def test_symlink_refused(self):
        link = self.work / "link.md"
        try:
            os.symlink(str(self.outside), str(link))
        except (OSError, NotImplementedError) as error:
            self.skipTest("シンボリックリンクを作れません（{}）".format(error))
        self.assertRefused(self.run_tool(LINT, "link.md"), message("link.md", OUTSIDE, LINT_HINT))

    def test_inside_output_unchanged(self):
        expected = json.dumps(yomiyasu_lint.lint_text(FINAL), ensure_ascii=True, indent=2) + "\n"
        for path in ("final.md", "./final.md", self.work / "final.md", "-", None):
            with self.subTest(path=path):
                args = ["--json", "--no-words"] + ([path] if path is not None else [])
                process = self.run_tool(LINT, *args, stdin=FINAL if path in ("-", None) else None)
                self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
                self.assertEqual(process.stdout.decode("utf-8"), expected)

    def test_hidden_content_through_stdin(self):
        # 点で始まるファイルの中身も、標準入力からなら検査できる
        process = self.run_tool(LINT, "--json", "--no-words", "-", stdin=SECRET)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout.decode("utf-8")), yomiyasu_lint.lint_text(SECRET))

    def test_words_folder_outside_still_read(self):
        # --words のフォルダは読むファイルの名前が決まっている（allow.txt、flag.txt、flag-patterns.txt）ので、この決まりに当てない
        words = self.root / "shared-words"
        write(words / "flag.txt", "三人\n")
        process = self.run_tool(LINT, "--json", "--words", "../shared-words", "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["context"]["words"]["path"], str(words))

    def test_default_words_folder_from_subfolder(self):
        # 自分で探す .yomiyasu-words/ は、作業フォルダの上（git の最上位）にあって名前が点で始まっても、前と同じく読む
        write(self.work / ".yomiyasu-words" / "flag.txt", "三人\n")
        process = self.run_tool(LINT, "--json", "note.md", cwd=self.work / "docs")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["context"]["words"]["path"],
                         str(self.work / ".yomiyasu-words"))


def library_diff(old, new, materials=()):
    old_text, old_info = markdown_visibility.decode_source(old.encode("utf-8"))
    new_text, new_info = markdown_visibility.decode_source(new.encode("utf-8"))
    result = yomiyasu_diff.diff(old_text, new_text, None, encoding_notes=yomiyasu_diff._encoding_notes(old_info, new_info),
                                words=None, materials=list(materials))
    return json.dumps(result, ensure_ascii=True, indent=1) + "\n"


class DiffTest(PathCase):
    def test_refused_either_file(self):
        for make, reason in REFUSED:
            path = make(self)
            with self.subTest(path=path):
                expected = message(path, reason, DIFF_HINT)
                self.assertRefused(self.run_tool(DIFF, path, "final.md"), expected)
                self.assertRefused(self.run_tool(DIFF, "--json", "source.md", path), expected)

    def test_refused_material(self):
        for make, reason in REFUSED:
            path = make(self)
            with self.subTest(path=path):
                self.assertRefused(self.run_tool(DIFF, "--material", path, "source.md", "final.md"),
                                   message(path, reason, DIFF_HINT))

    def test_refused_before_reading_any(self):
        # 読める組と一緒でも、どれかが断るパスなら何も出さない（先のファイルの差分も出さない）
        self.assertRefused(self.run_tool(DIFF, "source.md", "final.md", "--material", ".env"),
                           message(".env", HIDDEN, DIFF_HINT))

    def test_refused_endings(self):
        for make, reason in REFUSED:
            path = make(self)
            with self.subTest(path=path):
                self.assertRefused(self.run_tool(DIFF, "--endings", path), message(path, reason, DIFF_HINT))

    def test_inside_output_unchanged(self):
        expected = library_diff(SOURCE, FINAL)
        for old, new, stdin in (("source.md", "final.md", None), ("./source.md", self.work / "final.md", None),
                                ("-", "final.md", SOURCE), ("source.md", "-", FINAL)):
            with self.subTest(old=old, new=new):
                process = self.run_tool(DIFF, "--json", "--no-words", old, new, stdin=stdin)
                self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
                self.assertEqual(process.stdout.decode("utf-8"), expected)

    def test_inside_material_output_unchanged(self):
        write(self.work / "material.md", "担当は3人と決めました。\n")
        process = self.run_tool(DIFF, "--json", "--no-words", "--material", "material.md", "source.md", "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertEqual(process.stdout.decode("utf-8"), library_diff(SOURCE, FINAL, ["担当は3人と決めました。\n"]))
        process = self.run_tool(DIFF, "--json", "--no-words", "--material", "-", "source.md", "final.md",
                                stdin="担当は3人と決めました。\n")
        self.assertEqual(process.stdout.decode("utf-8"), library_diff(SOURCE, FINAL, ["担当は3人と決めました。\n"]))

    def test_endings_inside_unchanged(self):
        expected = yomiyasu_diff._endings_report(FINAL, None) + "\n"
        for path, stdin in (("final.md", None), ("-", FINAL)):
            process = self.run_tool(DIFF, "--endings", path, stdin=stdin)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
            self.assertEqual(process.stdout.decode("utf-8"), expected)


class CheckRunTest(PathCase):
    def test_refused_source_final_material(self):
        for make, reason in REFUSED:
            path = make(self)
            expected = message(path, reason, RUN_HINT)
            for args in (("--source", path, "--final", "final.md"), ("--source", "source.md", "--final", path),
                         ("--material", path, "--final", "final.md"),
                         ("--source", "source.md", "--material", path, "--final", "final.md")):
                with self.subTest(args=args):
                    self.assertRefused(self.run_tool(CHECK, "run", *args), expected)
                    self.assertRefused(self.run_tool(CHECK, "run", "--json", *args), expected)
                    self.assertNothingWritten()

    def test_refused_without_subcommand(self):
        # サブコマンドを省いた形（run とみなす）も同じ
        self.assertRefused(self.run_tool(CHECK, "--source", "../outside.md", "--final", "final.md"),
                           message("../outside.md", OUTSIDE, RUN_HINT))
        self.assertNothingWritten()

    def test_refused_with_state_dir_writes_nothing(self):
        state = self.work / "state"
        self.assertRefused(self.run_tool(CHECK, "run", "--state-dir", state, "--source", ".env", "--final", "final.md"),
                           message(".env", HIDDEN, RUN_HINT))
        self.assertFalse(state.exists())
        self.assertNothingWritten()

    def test_inside_runs_and_replays(self):
        # 子の lint と diff は、写しのフォルダ（.yomiyasu/inputs/）を作業フォルダにして動く
        process = self.run_tool(CHECK, "run", "--json", "--source", "source.md", "--final", "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        result = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual(result["status"], "executed")
        record = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual([entry["status"] for entry in record["checks"]], ["ran"] * len(record["checks"]))
        # 子の lint と diff のレポートは、ライブラリの関数の値と一字も同じ
        reports = {entry["name"]: (self.work / ".yomiyasu" / entry["report"]).read_bytes().decode("utf-8")
                   for entry in record["checks"] if entry["name"] in ("lint", "diff")}
        self.assertEqual(reports["lint"], json.dumps(yomiyasu_lint.lint_text(FINAL), ensure_ascii=True, indent=2) + "\n")
        self.assertEqual(reports["diff"], library_diff(SOURCE, FINAL))
        process = self.run_tool(CHECK, "verify", "--json", "--replay", "--final", "final.md", "--source", "source.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        verified = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual(verified["status"], "executed")
        self.assertNotEqual(verified["replay"], "skipped")

    def test_inside_absolute_and_dot_paths(self):
        process = self.run_tool(CHECK, "run", "--no-record", "--source", "./source.md", "--final", self.work / "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertIn("unrecorded via=run", process.stdout.decode("utf-8"))

    def test_stdin_accepted(self):
        body = "<<<yomiyasu:original>>>\n" + SECRET + "<<<yomiyasu:final>>>\n" + SECRET.replace("青い鳥", "青い小鳥")
        process = self.run_tool(CHECK, "run", "--stdin", "--no-record", stdin=body)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertIn("unrecorded via=run", process.stdout.decode("utf-8"))
        process = self.run_tool(CHECK, "run", "--source", "-", "--final", "final.md", "--no-record", stdin=SOURCE)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))


class CheckOtherCommandsTest(PathCase):
    def test_verify_refused(self):
        for make, reason in REFUSED:
            path = make(self)
            expected = message(path, reason, VERIFY_HINT)
            for args in (("--final", path), ("--final", "final.md", "--source", path), ("--final", "-", "--source", path)):
                with self.subTest(args=args):
                    self.assertRefused(self.run_tool(CHECK, "verify", *args, stdin=FINAL), expected)
                    self.assertRefused(self.run_tool(CHECK, "verify", "--json", *args, stdin=FINAL), expected)
                    self.assertNothingWritten()

    def test_verify_stdin_accepted(self):
        process = self.run_tool(CHECK, "verify", "--json", "--final", "-", stdin=FINAL)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["status"], "no_record")

    def test_start_refused(self):
        for make, reason in REFUSED:
            path = make(self)
            expected = message(path, reason, START_HINT)
            for args in (("--source", path), ("--source", "source.md", "--final", path)):
                with self.subTest(args=args):
                    self.assertRefused(self.run_tool(CHECK, "start", *args), expected, usage=True)
                    self.assertNothingWritten()

    def test_export_refused(self):
        for make, reason in REFUSED:
            path = make(self)
            expected = message(path, reason, EXPORT_HINT)
            for args in (("--final", path), ("--final", "final.md", "--source", path)):
                with self.subTest(args=args):
                    self.assertRefused(self.run_tool(CHECK, "export", *args), expected, usage=True)
                    self.assertNothingWritten()

    def test_start_run_export_inside(self):
        process = self.run_tool(CHECK, "start", "--json", "--source", "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        process = self.run_tool(CHECK, "run", "--source", "source.md", "--final", "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        process = self.run_tool(CHECK, "export", "--json", "--final", "final.md")
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["status"], "exported")

    def test_end_source_is_not_read(self):
        # end の --source は登録のパスと比べるだけで読まないので、この決まりに当てない
        process = self.run_tool(CHECK, "end", "--source", "../outside.md")
        self.assertEqual(process.returncode, 1, process.stderr.decode("utf-8"))
        self.assertNotIn(SECRET_WORD, process.stdout.decode("utf-8") + process.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
