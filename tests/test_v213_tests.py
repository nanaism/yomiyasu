"""v2.1.3: 試験の一式が Windows でも POSIX と同じことを確かめるための決まりと道具（tests/portable.py）の試験。

- 子プロセスに渡す標準入力と、試験が書くファイルは、改行を変えずにバイト列で渡す。text モードの標準入力と
  Path.write_text、open(..., "w") は、Windows では「\\n」を「\\r\\n」に、「\\r\\n」を「\\r\\r\\n」にする。
  text モードで出力を読むときと read_text は、ロケールによらないよう encoding を書く（Windows の既定は UTF-8 でない）。
  この決まりは tests/ のソースを構文木で調べて見張る（macOS と Linux の CI でも、決まりを破れば落ちる）。
- POSIX の権限ビットの確かめは、Windows では行わない（check とフックは POSIX のときだけ chmod する）。
- 開いているファイルへの os.replace は、Windows では PermissionError になる。O_EXCL で作ったあとの片付けの試験は、
  置き直す前にファイルを閉じる。Windows の動きは os.replace を差し替えて再現する。
- 子プロセスを使わない性能の試験の上限は、遅い機械では基準の処理の遅さの比で延ばす（portable.paced_limit）。

文はすべて合成の文。
"""
from pathlib import Path
from unittest import mock
import ast
import importlib.util
import ntpath
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
CHECK = ROOT / "scripts" / "yomiyasu_check.py"
HOOK = ROOT / "scripts" / "yomiyasu_hook.py"
sys.path.insert(0, str(TESTS))
import portable  # noqa: E402

TEXT_MODE_KEYWORDS = ("text", "encoding", "errors", "universal_newlines")
SUBPROCESS_CALLS = ("subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call",
                    "subprocess.call")
# 子の標準入力と標準出力をそのまま写す、試験の子のプログラム
ECHO_STDIN = "import sys\ndata = sys.stdin.buffer.read()\nsys.stdout.buffer.write(data)\nsys.stdout.buffer.flush()\n"
WRITE_BYTES = "import sys\nsys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))\nsys.stdout.buffer.flush()\n"


def load(path, name):
    before = sys.dont_write_bytecode
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = before
    return module


def read_test_sources():
    """tests/ の Python のソース（このファイルを含む）。(名前, ソース, 構文木) の並び。"""
    rows = []
    for path in sorted(TESTS.glob("*.py")):
        source = path.read_bytes().decode("utf-8")
        rows.append((path.name, source, ast.parse(source)))
    return rows


def calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def call_name(node):
    func = node.func
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def keywords(node):
    return {k.arg: k.value for k in node.keywords if k.arg}


def constant(node):
    return node.value if isinstance(node, ast.Constant) else None


class SourceRulesTest(unittest.TestCase):
    """tests/ のソースが、Windows で改行やロケールの違いを持ち込む書き方をしていない。"""

    @classmethod
    def setUpClass(cls):
        cls.sources = read_test_sources()

    def found(self, check):
        rows = []
        for name, source, tree in self.sources:
            for node in calls(tree):
                if check(node):
                    rows.append("{}:{}: {}".format(name, node.lineno, ast.get_source_segment(source, node)[:100]))
        return rows

    def test_no_write_text(self):
        """Path.write_text は Windows で改行を変える（Python 3.9 には newline の引数もない）。write_bytes を使う。"""
        self.assertEqual(self.found(lambda node: isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"),
                         [])

    def test_text_mode_open_for_writing_keeps_newlines(self):
        """書くための open は、バイナリか newline="" にする。"""
        def bad(node):
            if call_name(node) not in ("open", "io.open"):
                return False
            mode = constant(node.args[1]) if len(node.args) > 1 else constant(keywords(node).get("mode"))
            if not isinstance(mode, str) or not any(letter in mode for letter in "wax+") or "b" in mode:
                return False
            return constant(keywords(node).get("newline")) != ""
        self.assertEqual(self.found(bad), [])

    def test_no_text_input_to_child_processes(self):
        """text モードの子に文字列の input を渡さない（portable.run_text を使う）。"""
        def bad(node):
            named = keywords(node)
            return (call_name(node) in SUBPROCESS_CALLS and "input" in named
                    and any(name in named for name in TEXT_MODE_KEYWORDS))
        self.assertEqual(self.found(bad), [])

    def test_text_mode_children_name_the_encoding(self):
        """text モードで子の出力を読むときは encoding を書く（Windows の既定のロケールは UTF-8 でない）。"""
        def bad(node):
            named = keywords(node)
            return (call_name(node) in SUBPROCESS_CALLS and ("text" in named or "universal_newlines" in named)
                    and "encoding" not in named)
        self.assertEqual(self.found(bad), [])

    def test_read_text_names_the_encoding(self):
        def bad(node):
            return (isinstance(node.func, ast.Attribute) and node.func.attr == "read_text" and not node.args
                    and "encoding" not in keywords(node))
        self.assertEqual(self.found(bad), [])

    def test_permission_bits_are_checked_only_on_posix(self):
        """st_mode の権限ビットを比べる確かめは、os.name を見る if の中か、Windows を外す skipIf のある試験に置く。"""
        rows = []
        for name, source, tree in self.sources:
            parents = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node
            for node in calls(tree):
                if not (isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert")
                        and any(isinstance(part, ast.Attribute) and part.attr == "st_mode" for part in ast.walk(node))):
                    continue
                text = ast.get_source_segment(source, node)
                if "st_mode" not in text or ("0o7" not in text and "0o6" not in text and "0o4" not in text):
                    continue
                guarded, current = False, node
                while current in parents and not guarded:
                    current = parents[current]
                    if isinstance(current, ast.If) and "os.name" in ast.get_source_segment(source, current.test):
                        guarded = True
                    if isinstance(current, (ast.FunctionDef, ast.ClassDef)):
                        guarded = guarded or any("os.name" in ast.get_source_segment(source, d)
                                                 for d in current.decorator_list)
                if not guarded:
                    rows.append("{}:{}: {}".format(name, node.lineno, text[:100]))
        self.assertEqual(rows, [])

    def test_rules_find_the_old_forms(self):
        """見張りが働くこと: 決まりを破る合成のソースを、それぞれの決まりが見つける。"""
        samples = (
            ("test_no_write_text", "Path('a.md').write_text('一行目\\n', encoding='utf-8')\n"),
            ("test_text_mode_open_for_writing_keeps_newlines", "open('a.md', 'w', encoding='utf-8').write('文\\n')\n"),
            ("test_no_text_input_to_child_processes",
             "subprocess.run(['x'], input='文\\n', encoding='utf-8', capture_output=True)\n"),
            ("test_text_mode_children_name_the_encoding", "subprocess.run(['x'], text=True, capture_output=True)\n"),
            ("test_read_text_names_the_encoding", "Path('a.md').read_text()\n"),
            ("test_permission_bits_are_checked_only_on_posix",
             "def test_x(self):\n    self.assertEqual(p.stat().st_mode & 0o777, 0o600)\n"),
        )
        for test_name, sample in samples:
            with self.subTest(rule=test_name):
                case = SourceRulesTest(test_name)
                case.sources = [("sample.py", sample, ast.parse(sample))]
                with self.assertRaises(AssertionError):
                    getattr(case, test_name)()


class RunTextTest(unittest.TestCase):
    """portable.run_text は、subprocess.run の text モードと同じ結果を、標準入力の改行を変えずに返す。"""

    def test_input_reaches_the_child_byte_for_byte(self):
        text = "一行目\n二行目\r\n三行目\r四行目"
        process = portable.run_text([sys.executable, "-B", "-c", ECHO_STDIN], input=text, capture_output=True,
                                    timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        # 出力は text モードと同じ読み方（CRLF と CR を LF）
        self.assertEqual(process.stdout, "一行目\n二行目\n三行目\n四行目")
        raw = subprocess.run([sys.executable, "-B", "-c", ECHO_STDIN], input=text.encode("utf-8"), capture_output=True,
                             timeout=30)
        self.assertEqual(raw.stdout, text.encode("utf-8"))

    def test_subprocess_gets_bytes_and_no_text_mode(self):
        """Windows で改行を変える text モードの標準入力を使わない（subprocess.run を差し替えて渡した値を見る）。"""
        seen = {}

        def fake_run(command, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(command, 0, b"\xe6\x96\x87\r\n", b"")

        with mock.patch.object(portable.subprocess, "run", fake_run):
            process = portable.run_text(["x"], input="文\n", capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(seen["input"], "文\n".encode("utf-8"))
        self.assertFalse(set(seen) & set(TEXT_MODE_KEYWORDS), seen)
        self.assertEqual((process.stdout, process.stderr), ("文\n", ""))

    def test_output_is_the_same_as_text_mode(self):
        for data in (b"a\r\nb\rc\n", "見出し\r\n\r\n本文です。\n".encode("utf-8"), b"\xff\xfe\n"):
            with self.subTest(data=data):
                command = [sys.executable, "-B", "-c", WRITE_BYTES, data.hex()]
                expected = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                                          stdin=subprocess.DEVNULL, timeout=30)
                got = portable.run_text(command, capture_output=True, encoding="utf-8", errors="replace",
                                        stdin=subprocess.DEVNULL, timeout=30)
                self.assertEqual((got.returncode, got.stdout, got.stderr),
                                 (expected.returncode, expected.stdout, expected.stderr))

    def test_strict_decoding_still_fails(self):
        command = [sys.executable, "-B", "-c", WRITE_BYTES, "ff"]
        with self.assertRaises(UnicodeDecodeError):
            portable.run_text(command, capture_output=True, stdin=subprocess.DEVNULL, timeout=30)


class PacedLimitTest(unittest.TestCase):
    def test_fast_result_keeps_the_limit_without_measuring(self):
        with mock.patch.object(portable, "pace_scale", side_effect=AssertionError("pace を測った")):
            limit, detail = portable.paced_limit(0.3, 0.12)
        self.assertEqual(limit, 0.3)
        self.assertIn("0.120秒", detail)

    def test_slow_result_is_compared_with_the_scaled_limit(self):
        with mock.patch.object(portable, "pace_scale", return_value=4.0):
            limit, detail = portable.paced_limit(0.3, 0.5)
        self.assertAlmostEqual(limit, 1.2)
        self.assertIn("この機械の遅さ 4.00", detail)
        # 速い機械（比が1）では、上限を超えた結果はそのまま落ちる
        with mock.patch.object(portable, "pace_scale", return_value=1.0):
            self.assertEqual(portable.paced_limit(0.3, 3.0)[0], 0.3)

    def test_scale_never_shrinks_the_limit(self):
        with mock.patch.object(portable, "_pace", return_value=(10.0, lambda: None)):
            self.assertEqual(portable.pace_scale(), 1.0)

    def test_pace_is_read_from_the_diff_tests(self):
        """pace と PACE_SECONDS は test_v200_diff_full から読む（片方だけを変えないように）。"""
        source = (TESTS / "test_v200_diff_full.py").read_bytes().decode("utf-8")
        seconds, run = portable._pace()
        self.assertEqual(seconds, float(re.search(r"^PACE_SECONDS = ([0-9.]+)$", source, re.M).group(1)))
        self.assertIsInstance(run(), int)
        self.assertGreaterEqual(portable.pace_scale(rounds=1), 1.0)

    def test_clock(self):
        with mock.patch.object(portable.sys, "platform", "win32"):
            self.assertIs(portable.timing_clock(), time.perf_counter)
        with mock.patch.object(portable.sys, "platform", "linux"):
            self.assertIs(portable.timing_clock(), time.process_time)


class ReplaceOpenFileTest(unittest.TestCase):
    """O_EXCL で作ったあとに書けなかったときの片付けを、Windows の os.replace（開いているファイルへの置き直しを
    PermissionError にする）で確かめる。test_v200_state_gitignore の TestPlaceNewFile と同じ形。"""

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v213-tests-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.check = load(CHECK, "_yomiyasu_check_v213_tests")

    def scenario(self, close_first):
        check, folder = self.check, self.folder
        path = folder / ("target-" + str(close_first))
        real_link, real_fdopen = check.os.link, check.os.fdopen
        opened = []

        def windows_replace(source, target):
            if any(not stream.closed for stream in opened):
                raise PermissionError(13, "別のプロセスが使用中のため、アクセスできません")
            os.replace(source, target)

        def no_link(src, dst, *args, **kwargs):
            raise OSError(1, "リンクを作れない")

        def failing_fdopen(handle, mode="r", *args, **kwargs):
            stream = real_fdopen(handle, mode, *args, **kwargs)
            if mode == "wb" and os.path.lexists(str(path)) and os.path.getsize(str(path)) == 0:
                opened.append(stream)
                if close_first:
                    stream.close()
                other = folder / "other.tmp"
                other.write_bytes(b"other\n")
                try:
                    windows_replace(str(other), str(path))
                finally:
                    stream.close()
                raise OSError(28, "試験で起こした書き込みの失敗")
            return stream

        check.os.link, check.os.fdopen = no_link, failing_fdopen
        try:
            with self.assertRaises(OSError) as caught:
                check._place_new_file(str(path), b"data\n")
        finally:
            check.os.link, check.os.fdopen = real_link, real_fdopen
        return path, caught.exception

    def test_closing_before_replace_keeps_the_other_file(self):
        path, error = self.scenario(close_first=True)
        self.assertEqual(error.errno, 28)
        self.assertEqual(path.read_bytes(), b"other\n")

    def test_replacing_an_open_file_fails_on_windows(self):
        """閉じる前に置き直すと、Windows では置き直しが起きず、作ったファイルが消える（2.1.2 の試験の落ち方）。"""
        path, error = self.scenario(close_first=False)
        self.assertIsInstance(error, PermissionError)
        self.assertFalse(os.path.lexists(str(path)))


class HomePathCompareTest(unittest.TestCase):
    """Windows の「~/state」は「C:\\...\\me/state」になる。区切りが違っても同じ場所なので、両方を normpath して比べる。"""

    def test_windows_shape(self):
        check = load(CHECK, "_yomiyasu_check_v213_tests_home")
        hook = load(HOOK, "_yomiyasu_hook_v213_tests_home")
        profile = "C:\\Users\\試験"
        with mock.patch.dict(os.environ, {"USERPROFILE": profile}), \
                mock.patch("os.sep", "\\"), mock.patch("os.path.expanduser", ntpath.expanduser):
            for value, parts in (("~/state", ("state",)), ("~/a/b", ("a", "b")), ("~//state", ("state",))):
                with self.subTest(value=value):
                    result = check._home_path(value)
                    self.assertEqual(hook._home_path(value), result)
                    self.assertEqual(ntpath.normpath(result), ntpath.normpath(ntpath.join(profile, *parts)))
            self.assertNotEqual(check._home_path("~/state"), ntpath.join(profile, "state"))


if __name__ == "__main__":
    unittest.main()
