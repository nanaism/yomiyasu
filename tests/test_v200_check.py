#!/usr/bin/env python3
"""v2.0.0: lint と diff をまとめて実行し、記録を残して照らす yomiyasu_check.py（run と verify）の試験。

期待値は設計の 3章と 6.5 の表（K1〜K38。start の K19 と、フックの登録の K34 は
2番目の作業で作らないので除く）と、試験づくりで決めたこと（10章。10.3、10.4 の S10〜S16、10.5、10.6 B1、10.7）から
取った。10章に合わせて強めた試験は、check の段で実装の前に足した。文はすべて合成。

- yomiyasu_check.py は v1.1.2 にないので、import せず subprocess で動かす。CheckCase の setUp で
  ファイルの有無を確かめ、v1.1.2 では skip ではなく失敗にする。
- 試験は一時フォルダを作業ディレクトリにし、YOMIYASU_STATE_DIR をその中の .yomiyasu に向ける。
  ホームやリポジトリには書かない。スクリプトを書き換える試験は、一時フォルダに写したものを書き換える。
"""

import ast
import contextlib
import datetime
import hashlib
import io
import json
import os
import pathlib
from pathlib import Path
import platform
import re
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CHECK = SCRIPTS / "yomiyasu_check.py"
LINT = SCRIPTS / "yomiyasu_lint.py"
DIFF = SCRIPTS / "yomiyasu_diff.py"
SKILL_MD = ROOT / "skills" / "yomiyasu" / "SKILL.md"
TOOL_NAMES = ("yomiyasu_check.py", "yomiyasu_lint.py", "yomiyasu_diff.py", "markdown_visibility.py")

# 3.10 状態の行の文法と、読む側の正規表現
STATUS_LINE = re.compile(r"^yomiyasu-check: ([a-z_]+)((?: [a-z_]+=\S+)*)$")
# G7（種類と読者の設計 9.5）: mode の次に、付けたときだけ doc_type と reader
FIELD_ORDER = ("via", "run", "attempt", "final", "source", "expected", "mode", "doc_type", "reader", "checks",
               "meaning_risk", "replay", "failed", "reason")
RUN_ID = r"\d{8}T\d{6}Z-[0-9a-f]{8}"
# 6.5 K1 の2行目
K1_STATUS = re.compile(r"^yomiyasu-check: executed via=run run=" + RUN_ID
                       + r" attempt=1 final=sha256:[0-9a-f]{12} mode=rewrite checks=lint,diff meaning_risk=\d+$")

# 3.5 run の出力の1行目（{仕上げ} の前まで）と、決まった行
FINALIZE_FILE = "提出の直前に、本文を変えずに verify を1回実行してください。"
# check の固め（勧め55、反証レビュー spec 3）: --state-dir か YOMIYASU_STATE_DIR で状態フォルダを決めたときの {仕上げ}。
# 試験は YOMIYASU_STATE_DIR で状態フォルダを決めるので、ふつうはこちら（CheckCase.finalize_file）
FINALIZE_STATE_DIR = "提出の直前に、本文を変えずに verify --state-dir {} を1回実行してください。"
# --stdin のときの {仕上げ}。本文だけを返す依頼で verify が抜けたので、ファイルと同じく返す直前の verify を案内する。
# 状態フォルダを決めたときは verify にも同じ --state-dir を付ける（CheckCase.finalize_stdin）
FINALIZE_STDIN = "提出の直前に、本文を変えずに、最終稿だけを標準入力から verify --final - に渡して1回実行してください。"
FINALIZE_STDIN_STATE_DIR = ("提出の直前に、本文を変えずに、最終稿だけを標準入力から verify --state-dir {} --final - に渡して"
                            "1回実行してください。")
# 10.4 S11: --no-record のときの {仕上げ}
# check の固め（勧め59）: 「直さないなら」に続けて読めるように並べ替えた
FINALIZE_NO_RECORD = ("完了報告の「実行しなかった検査」に「最終稿の照合（記録を残さない指定のため）」と書いてください"
                      "（記録を残さない指定なので verify はできません）。")
RUN_REWRITE_FIRST = ("検査を実行しました（1回目）。下の候補を原文と資料に照らして確かめてください。"
                     "直すのは1回までです。直したら同じコマンドをもう一度実行し、直さないなら")
RUN_REWRITE_FIRST_NO_CANDIDATES = ("検査を実行しました（1回目）。規則に当たる候補はありません。"
                                   "全文差分で意図しない変更がないかを確かめ、直すなら1回まで、直さないなら")
RUN_COMPOSE_FIRST = ("検査を実行しました（新規作成、1回目）。資料にない数値と名前を確かめ、"
                     "主張・条件・担当・未確認の事項を資料と読み比べてください。直すのは1回までです。"
                     "直したら同じコマンドをもう一度実行し、直さないなら")
RUN_AFTER_FIX = "検査を実行しました（修正後の検査）。本文はもう変えず、残った候補は完了報告に書いてください。"
RUN_SAME_FINAL = "検査を実行しました（前回と同じ最終稿）。"
# check の固め（勧め58）: 書き直したのに変更なしと出たときの確かめを添える
RUN_NO_CHANGE = ("検査を実行しました。原文から変更はありません。書き直したのに変更なしと出たときは、"
                 "原文を上書きしていないか確かめてください。")
RUN_OVER_LIMIT = ("検査を実行しました（修正{n}回目のあと）。修正は1回までの決まりを超えています（このコマンドは止めません）。"
                  "利用者から新しい依頼がない限り本文はもう変えず、残った候補は完了報告に書いてください。")
RUN_PARTIAL_HEAD = "検査の一部を実行できませんでした（"
# check の固め（勧め42の1）: partial の1行目の最後に足す文（5.3）
PARTIAL_TAIL = "verify は実行せず、完了報告にこの出力の2行目を写してください。"
RUN_UNRECORDED_PART = "記録を書けませんでした"
RUN_DISCLAIMER = "この記録は検査を実行したことを示すだけで、意味が保たれたことや読みやすさの合格を示すものではありません。"
# 候補があるときに、3行目のあとの候補の一覧に続けて出る案内（その2行のぶん、4行目からあとの行が2行下がる）
RUN_HEAD_NOTE = "候補の中身は下の節にあります。出力を切らずに読んでください。"
FAIL_ON_HEAD = "--fail-on={} の条件に当たりました（終了コード1）。"
MATERIALS_DISCLAIMER = ("照らしたのは数値、名前、語、確度の語だけです。主張、条件、担当が資料どおりかは判定していません。"
                        "資料と読み比べてください。")
SAME_FILE_ERROR = ("原文と最終稿が同じファイルです。書き直す前の原文を別のファイルに残し、最終稿を別のファイルに保存してから"
                   "実行してください。原文を上書きしてしまったときは、git などで元の版を取り出して --source に渡してください。")
GITIGNORE_LINES = ["# yomiyasu の検査記録。git に入れない。", "*"]

# 3.9 verify の出力の1行目
VERIFY_LINE1 = {
    "executed": "この最終稿に必要な検査（{checks}）を実行した記録があり、最終稿のハッシュが記録と合いました。"
                "合格の判定ではありません。完了報告を付けるときは、この出力の2行目を写してください。",
    "no_record": "この最終稿の検査記録がありません。yomiyasu_check.py run を実行してください。"
                 "実行できないときは、完了報告に実行しなかった検査として書いてください。",
    "final_changed": "最終稿が、最後に検査した本文と違います。本文を変えたなら yomiyasu_check.py run をもう一度実行し、"
                     "そのあと verify を実行してください。",
    "wrong_file": "この実行IDの記録は別のファイルのものです。この最終稿で yomiyasu_check.py run を実行してください。",
    "other_source": "記録の原文が、指定した原文と違います。正しい原文で yomiyasu_check.py run を実行してください。",
    "ambiguous": "同じ最終稿に、別の原文で作った記録が複数あります。--run-id か --source を付けて verify を実行してください。",
    "invalid_record": "記録の形が正しくありません（手で書いた記録や壊れた記録は使えません）。yomiyasu_check.py run を実行してください。",
    "stale_record": "指定した時刻より前の記録です。yomiyasu_check.py run をもう一度実行してください。",
    "tool_changed": "記録のあとで検査スクリプトが変わりました。yomiyasu_check.py run をもう一度実行してください。",
    "not_reproducible": "記録のレポートを今のスクリプトで作り直せません。yomiyasu_check.py run をもう一度実行してください。",
}
VERIFY_INCOMPLETE_TAIL = " の結果がありません。yomiyasu_check.py run をもう一度実行してください。"
# check の固め（勧め42の2）: 記録の検査が時間切れか内部エラーで終わっていたとき
VERIFY_PARTIAL_LINE = ("記録の {}で終わっています。run をもう一度実行しても同じなら、完了報告に run の出力の2行目を写し、"
                       "「実行しなかった検査」に「{}」と書いてください。")
# check の固め（勧め55）: verify の no_record の3行目に、探した状態フォルダを書く
NO_RECORD_LINE3 = "記録: なし（探した状態フォルダ: {}）"
LINE_ENDINGS_NOTE = "改行コードだけが違います（git の autocrlf やエディタの設定で変わることがあります）"

RECORD_KEYS = ("format", "format_version", "run_id", "attempt", "fix_count", "previous", "created_at", "mode",
               "cwd", "host", "skill", "tools", "python", "inputs", "options", "required_checks", "checks",
               "materials_summary", "fact_gaps", "result", "record_digest")
INPUT_KEYS = ("role", "index", "path", "via", "bytes", "sha256", "text_sha256", "bom", "eol", "snapshot")
CHECK_KEYS = ("name", "status", "exit_code", "duration_ms", "target", "report", "report_sha256", "text",
              "text_sha256", "summary", "stderr", "error")
RESULT_KEYS = ("status", "token", "next", "fail_on_hit", "meaning_risk_count", "final_unchanged_during_run",
               "not_judged")
# G7（種類と読者の設計 9.5、10.1）: run と verify の JSON の mode の次に context
RUN_JSON_KEYS = ("format", "format_version", "tool_version", "command", "status", "status_line", "message",
                 "next", "run_id", "attempt", "fix_count", "mode", "context", "record_path", "fail_on_hit", "lint", "diff",
                 "materials")
VERIFY_JSON_KEYS = ("format", "format_version", "tool_version", "command", "status", "status_line", "message",
                    "run_id", "attempt", "record_path", "final", "record_final_sha256", "mode", "context", "required_checks",
                    "checks", "meaning_risk_count", "replay", "problems", "final_candidate_count", "changed_place_count")
FILE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# 指示書2.2の3組（合成の文）
PAIRS_22 = (("田中が佐藤を承認した。", "佐藤が田中を承認した。"),
            ("保存期間は3日です。", "保存期間は30日です。"),
            ("データを保存します。", "データを保存しません。"))

# 3.12 などで、試験の外への書き込みを見張る小さな実行用コード（tests/test_setup_corpus_static.py の型E）
AUDIT_WORKER = r'''
import atexit
import os
import runpy
import sys

allowed = os.path.realpath(sys.argv[1])
script = sys.argv[2]
blocked = []
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
PATH_EVENTS = {
    "os.rename": (0, 1), "os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,), "os.link": (0, 1),
    "os.symlink": (1,), "os.truncate": (0,), "os.chmod": (0,), "os.chown": (0,), "os.utime": (0,),
    "shutil.copyfile": (1,), "shutil.copymode": (1,), "shutil.copystat": (1,), "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
}

def outside(path):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    real = os.path.realpath(os.fsdecode(path))
    if real == os.path.realpath(os.devnull):
        return False
    return real != allowed and not real.startswith(allowed + os.sep)

def guard(event, args):
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writing = isinstance(flags, int) and bool(flags & WRITE_FLAGS)
        if isinstance(mode, str) and any(ch in mode for ch in "wax+"):
            writing = True
        targets = [args[0]] if writing else []
    elif event in PATH_EVENTS:
        targets = [args[i] for i in PATH_EVENTS[event] if i < len(args)]
    else:
        return
    for target in targets:
        if outside(target):
            blocked.append((event, os.fsdecode(target)))
            raise PermissionError("blocked by the test: " + event)

def report():
    if blocked:
        sys.stderr.write("BLOCKED-WRITES " + repr(blocked) + "\n")

atexit.register(report)
sys.addaudithook(guard)
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
'''

# 3.13 の2、K32: lint と diff を読み込んだか（モジュールの名前によらず）を見張る小さな実行用コード。
# モジュールのコードを実行すると監査イベント exec が起きる（spec_from_file_location で別の名前で読んでも、
# runpy や exec でも）。そのコードのファイル名が見張るファイルなら、読み込んだと数える。ast.parse は数えない。
# 使い方: python -B -c LOAD_WORKER <見張るフォルダ> <動かすスクリプト> [引数…]
LOAD_WORKER = r'''
import atexit
import os
import runpy
import sys

watch_dir = sys.argv[1]
script = sys.argv[2]

def key(path):
    return os.path.normcase(os.path.realpath(path))

watched = {key(os.path.join(watch_dir, name)): name for name in ("yomiyasu_lint.py", "yomiyasu_diff.py")}
loaded = set()

def mark(path):
    if isinstance(path, (str, bytes, os.PathLike)):
        name = watched.get(key(os.fsdecode(path)))
        if name:
            loaded.add(name)

def guard(event, args):
    if event == "exec" and args:
        mark(getattr(args[0], "co_filename", None))

def report():
    for module in list(sys.modules.values()):
        mark(getattr(module, "__file__", None))
    sys.stderr.write("LOADED-SCRIPTS [" + ",".join(sorted(loaded)) + "]\n")

atexit.register(report)
sys.addaudithook(guard)
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
'''

# LOAD_WORKER が働くことを確かめる合成のスクリプト（lint を別の名前で読み込む）
LOAD_UNDER_OTHER_NAME = (
    "import importlib.util\n"
    "import sys\n"
    "spec = importlib.util.spec_from_file_location('_renamed_lint_for_test', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def text_sha256(data):
    """3.7 の text_sha256。decode_source（BOM を1つ外し、CRLF と CR を LF に）のあと、末尾の改行をすべて外して1つ付ける。"""
    text = data.decode("utf-8")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if text:
        text += "\n"
    return sha256_bytes(text.encode("utf-8"))


def record_digest(record):
    """3.7 の record_digest。"""
    body = {key: value for key, value in record.items() if key != "record_digest"}
    text = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + sha256_bytes(text.encode("utf-8"))


def split_lines(stdout):
    return stdout.rstrip("\n").split("\n")


def tree_listing(root, skip=None):
    names = []
    for path in sorted(Path(root).rglob("*")):
        if skip is not None and (path == skip or skip in path.parents):
            continue
        names.append(path.relative_to(root).as_posix())
    return names


def tree_digest(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        key = path.relative_to(root).as_posix()
        result[key] = sha256_file(path) if path.is_file() else "<dir>"
    return result


def utc_text(delta_days):
    moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=delta_days)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_main_guard(node):
    """最上位の `if __name__ == "__main__":` か。"""
    test = getattr(node, "test", None)
    return (isinstance(node, ast.If) and isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def assigns_version(node):
    targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
    return isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
        isinstance(target, ast.Name) and target.id == "__version__" for target in targets)


def main_insertion_point(source):
    """差し込む行の位置。最上位の `if __name__ == "__main__":` の直前（定義と __version__ はすべてそのまま）。
    その形がなければ、docstring、`from __future__`、`__version__` の代入のあと。"""
    body = ast.parse(source).body
    lines = source.splitlines(True)
    guards = [node for node in body if is_main_guard(node)]
    if guards:
        return guards[-1].lineno - 1
    index = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        index = 1
    while index < len(body) and (assigns_version(body[index]) or (
            isinstance(body[index], ast.ImportFrom) and body[index].module == "__future__")):
        index += 1
    return body[index].lineno - 1 if index < len(body) else len(lines)


def inject_cli_exit_3(path):
    """スクリプトとして動かしたときだけ終了コード3で終わるようにする（import の振る舞いは変えない）。"""
    inject_cli_code(path, ("import sys as _yomiyasu_test_sys",
                           "_yomiyasu_test_sys.stderr.write(\"internal error injected by test_v200_check\\n\")",
                           "_yomiyasu_test_sys.exit(3)"))


def inject_cli_code(path, code_lines):
    """スクリプトとして動かしたときだけ、code_lines（字下げなしの行）を最初に実行する（import の振る舞いは変えない）。
    差し込む場所は main_insertion_point()。"""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(True)
    at = main_insertion_point(source)
    snippet = "if __name__ == \"__main__\":\n" + "".join("    " + line + "\n" for line in code_lines)
    path.write_text("".join(lines[:at]) + snippet + "".join(lines[at:]), encoding="utf-8")


class CheckCase(unittest.TestCase):
    """一時フォルダの用意と、check を動かす補助（tests/test_stdio_encoding.py:41-49 の型）。"""

    def setUp(self):
        self.assertTrue(CHECK.is_file(), "scripts/yomiyasu_check.py がない（v2.0.0 で足す）")
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-check-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.state = self.root / ".yomiyasu"

    # --- 準備 ---

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def finalize_file(self):
        """ファイルのときの {仕上げ}。試験は YOMIYASU_STATE_DIR で状態フォルダを決めるので、verify にも同じ状態フォルダを
        付けるよう案内する（勧め55。反証レビュー spec 3）。"""
        return FINALIZE_STATE_DIR.format('"{}"'.format(self.state))

    def finalize_stdin(self):
        """--stdin（--final - を含む）のときの {仕上げ}。試験は YOMIYASU_STATE_DIR で状態フォルダを決めるので、
        verify --final - にも同じ状態フォルダを付けるよう案内する。"""
        return FINALIZE_STDIN_STATE_DIR.format('"{}"'.format(self.state))

    def env(self, **extra):
        env = dict(os.environ)
        for name in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID"):
            env.pop(name, None)
        env["YOMIYASU_STATE_DIR"] = str(self.state)
        env.update(extra)
        return env

    def skill_copy(self):
        """4本のスクリプトと SKILL.md を一時フォルダに写す（K14、K29、K33）。"""
        scripts = self.root / "skill" / "scripts"
        scripts.mkdir(parents=True)
        for name in TOOL_NAMES:
            shutil.copyfile(str(SCRIPTS / name), str(scripts / name))
        shutil.copyfile(str(SKILL_MD), str(scripts.parent / "SKILL.md"))
        return scripts

    # --- 実行 ---

    def check(self, *args, stdin=None, script=None, env=None, cwd=None, flags=("-B",)):
        return subprocess.run(
            [sys.executable] + list(flags) + [str(script or CHECK)] + [str(a) for a in args],
            input=stdin, cwd=str(cwd or self.root), env=env or self.env(),
            capture_output=True, encoding="utf-8", timeout=30,
        )

    def check_ok(self, *args, **kwargs):
        process = self.check(*args, **kwargs)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        return process, split_lines(process.stdout)

    def check_json(self, *args, code=0, **kwargs):
        process = self.check(*(list(args) + ["--json"]), **kwargs)
        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
        self.assertTrue(process.stdout.isascii(), "--json の出力は ASCII だけにする")
        return json.loads(process.stdout)

    def run_pair(self, before, after, *extra, names=("a.md", "b.md")):
        a = self.write(names[0], before)
        b = self.write(names[1], after)
        process, lines = self.check_ok("run", "--source", a, "--final", b, *extra)
        return a, b, lines

    # --- 読み取り ---

    def status(self, line):
        """状態の行を正規表現で読み、キーの順が 3.10 のとおりかを確かめる。"""
        match = STATUS_LINE.match(line)
        self.assertIsNotNone(match, line)
        pairs = [part.split("=", 1) for part in match.group(2).split()]
        keys = [key for key, _ in pairs]
        self.assertEqual(keys[:4], ["via", "run", "attempt", "final"], line)
        for key in keys:
            self.assertIn(key, FIELD_ORDER, line)
        positions = [FIELD_ORDER.index(key) for key in keys]
        self.assertEqual(positions, sorted(set(positions)), line)
        return match.group(1), dict(pairs)

    def record_index(self, lines):
        """run の出力の記録の行の位置。記録の行は5行目で、候補があるときは、3行目のあとに候補の一覧と案内の2行が入るので7行目。"""
        index = 6 if len(lines) > 6 and lines[4] == RUN_HEAD_NOTE else 4
        self.assertTrue(lines[index].startswith("記録: "), lines[:index + 1])
        return index

    def record_from(self, lines):
        index = self.record_index(lines)
        path = Path(lines[index][len("記録: "):])
        self.assertTrue(path.is_file(), str(path))
        return path, json.loads(path.read_text(encoding="utf-8"))

    def save_record(self, path, record):
        path.write_text(json.dumps(record, ensure_ascii=True, indent=1), encoding="utf-8")

    def check_entry(self, record, name):
        entries = [entry for entry in record["checks"] if entry["name"] == name]
        self.assertEqual(len(entries), 1, record["checks"])
        return entries[0]

    def assert_verify(self, process, state, code=1):
        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
        if code in (0, 1):
            self.assertEqual(process.stderr, "")
        lines = split_lines(process.stdout)
        self.assertEqual(len(lines), 4 if state == "executed" else 3, lines)
        if state == "executed":
            record = json.loads(Path(lines[2][len("記録: "):]).read_text(encoding="utf-8"))
            summaries = {entry["name"]: entry["summary"] for entry in record["checks"]}
            expected = "記録の中身: 見直し候補 最終稿 {}件".format(summaries["lint"]["candidate_count"])
            if "diff" in record["required_checks"]:
                expected += "、直した箇所 {}か所（原文の件数と元と後は run の出力にあります）".format(summaries["diff"]["hunk_count"])
            else:
                expected += "（新規作成）"
            self.assertEqual(lines[3], expected)
        status, fields = self.status(lines[1])
        self.assertEqual(status, state, lines)
        self.assertEqual(fields["via"], "verify")
        return lines, fields


class TestK1RecordAndOutput(CheckCase):
    """K1 記録の全項目、3.5 の出力の形（例1）、3.6 の状態フォルダ。"""

    def test_k1_run_output_matches_example_1(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        self.assertRegex(lines[1], K1_STATUS)
        status, fields = self.status(lines[1])
        self.assertEqual(status, "executed")
        line1 = RUN_REWRITE_FIRST + self.finalize_file()
        line2 = ("yomiyasu-check: executed via=run run={} attempt=1 final=sha256:{} mode=rewrite "
                 "checks=lint,diff meaning_risk=1").format(fields["run"], sha256_file(b)[:12])
        record = self.state / "runs" / fields["run"] / "attempt-1.json"
        expected = [
            line1,
            line2,
            "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更あり 候補1件（うち意味が変わる恐れ1件）",
            # 候補があるときは、3行目のあとに候補の短い一覧と、下の節を読む案内を出す
            "diff の候補: 後1行目 number",
            RUN_HEAD_NOTE,
            RUN_DISCLAIMER,
            "記録: " + str(record),
            # diff の詰め: 記録の行のあとに硬化の検査と勢いの検査の結果（完了報告の確認の記録に写す2行）
            "硬化の検査: 候補なし",
            "勢いの検査: 候補なし",
            "慎重表現の検査: 候補なし",
            "値の検査: 候補なし",
            "見直し候補: 原文 0件 → 最終稿 0件（lint の規則に当たった数で、点数ではありません。増えても減っても読みやすさの良し悪しは示しません）",
            "",
            "■ 直した箇所（1か所。元と後）",
            "@ 元1行目 → 後1行目（本文）",
            "  元: 保存期間は3日です。",
            "  後: 保存期間は30日です。",
            "- 省いていない元と後は下の「■ 全文差分」と、記録と同じフォルダの attempt-1.diff.txt にあります。",
            "",
            "■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）",
            "- 数値が変わった（1行目）: 3日 → 30日",
            "  元: 保存期間は3日です。",
            "  後: 保存期間は30日です。",
            "",
            "■ 全文差分（変更 1か所。省略していません）",
            "@ 元1行目 → 後1行目（本文）",
            "  元: 保存期間は3日です。",
            "  後: 保存期間は30日です。",
            "  差: 保存期間は3{+0+}日です。",
            "",
            line1,
            line2,
        ]
        self.assertEqual(lines[-2:], lines[:2])
        self.assertEqual(lines, expected)

    def test_k1_record_has_every_key_with_the_designed_types(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        status, fields = self.status(lines[1])
        path, record = self.record_from(lines)
        self.assertEqual(path, self.state / "runs" / fields["run"] / "attempt-1.json")
        for key in RECORD_KEYS:
            self.assertIn(key, record)
        self.assertEqual(record["format"], "yomiyasu-check-record")
        self.assertIs(type(record["format_version"]), int)
        self.assertEqual(record["format_version"], 1)
        self.assertRegex(record["run_id"], "^" + RUN_ID + "$")
        self.assertEqual(record["run_id"], fields["run"])
        self.assertIs(type(record["attempt"]), int)
        self.assertIs(type(record["fix_count"]), int)
        self.assertEqual((record["attempt"], record["fix_count"], record["previous"]), (1, 0, None))
        self.assertRegex(record["created_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(record["mode"], "rewrite")
        self.assertTrue(os.path.isabs(record["cwd"]))
        self.assertEqual(os.path.realpath(record["cwd"]), str(self.root))
        self.assertEqual(record["host"], {"session": None, "codex_thread_id": None, "armed_by": None})
        self.assertEqual(set(record["skill"]), {"found", "dir", "skill_md_sha256", "version"})
        self.assertIs(record["skill"]["found"], False)  # ルートの scripts から動かすと偽
        # 3.7: scripts の1つ上に SKILL.md があるときだけ埋める
        self.assertEqual((record["skill"]["dir"], record["skill"]["skill_md_sha256"], record["skill"]["version"]),
                         (None, None, None))
        # diff の詰めの直し（反証で見つけた例）: scripts の隣の
        # references/lists/ にある一覧のファイルの SHA-256 も tools に入れる（ルートの scripts の隣には3つともある）
        lists = ROOT / "references" / "lists"
        list_keys = ["references/lists/{}.txt".format(name) for name in ("nominalization", "intensifiers", "feelings", "hedges")]
        self.assertEqual(set(record["tools"]), set(TOOL_NAMES) | set(list_keys))
        for name in TOOL_NAMES:
            self.assertEqual(record["tools"][name], {"version": "2.1.1", "sha256": sha256_file(SCRIPTS / name)})
        for key in list_keys:
            self.assertEqual(record["tools"][key], {"version": None, "sha256": sha256_file(ROOT / key)})
        # unicode_version は check の固め（反証レビュー compat 4）で足した。似かたを求めた Unicode の版
        self.assertEqual(record["python"], {"version": platform.python_version(),
                                            "implementation": platform.python_implementation(),
                                            "unicode_version": unicodedata.unidata_version})
        self.assertEqual(set(record["inputs"]), {"source", "materials", "final"})
        self.assertEqual(record["inputs"]["materials"], [])
        for role, file in (("source", a), ("final", b)):
            item = record["inputs"][role]
            for key in INPUT_KEYS:
                self.assertIn(key, item)
            self.assertEqual(item["role"], role)  # 設計 10.3 C1
            data = file.read_bytes()
            self.assertEqual(item["index"], 0)
            self.assertEqual(os.path.realpath(item["path"]), str(file))
            self.assertEqual(item["via"], "file")
            self.assertEqual(item["bytes"], len(data))
            self.assertEqual(item["sha256"], sha256_bytes(data))
            self.assertEqual(item["text_sha256"], text_sha256(data))
            self.assertEqual((item["bom"], item["eol"]), (False, "lf"))
            self.assertEqual(item["snapshot"], "inputs/{}.bin".format(sha256_bytes(data)))
            self.assertEqual((self.state / item["snapshot"]).read_bytes(), data)
        # G7（種類と読者の設計 9.5、10.1）: options に doc_type と reader を足す（付けなければ null）
        self.assertEqual(record["options"], {"stance": None, "fail_on": [], "timeout": 90, "doc_type": None, "reader": None, "fact_gaps": False})
        self.assertEqual(record["required_checks"], ["lint", "diff"])
        self.assertEqual(sorted(entry["name"] for entry in record["checks"]), ["diff", "lint"])
        source_sha = sha256_file(a)
        final_sha = sha256_file(b)
        for entry in record["checks"]:
            for key in CHECK_KEYS:
                self.assertIn(key, entry)
            name = entry["name"]
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"], entry["error"]),
                             ("ran", 0, "", None))
            self.assertIsInstance(entry["duration_ms"], int)
            self.assertEqual(entry["report"], "runs/{}/attempt-1.{}.json".format(record["run_id"], name))
            self.assertEqual(entry["text"], "runs/{}/attempt-1.{}.txt".format(record["run_id"], name))
            self.assertEqual(entry["report_sha256"], sha256_file(self.state / entry["report"]))
            # .txt は CLI の標準出力と同じバイト列（10.3 B5。末尾の改行1つ）なので、バイト列のハッシュと
            # 3.7 の Input の text_sha256 の作り方のどちらで読んでも同じ値になる
            self.assertEqual(entry["text_sha256"], sha256_file(self.state / entry["text"]))
            self.assertEqual(entry["target"].get("final"), final_sha)
        self.assertEqual(self.check_entry(record, "diff")["target"], {"source": source_sha, "final": final_sha})
        lint_summary = self.check_entry(record, "lint")["summary"]
        self.assertEqual((lint_summary["candidate_count"], lint_summary["counts"]),
                         (0, {"error": 0, "warn": 0, "info": 0}))
        diff_summary = self.check_entry(record, "diff")["summary"]
        self.assertEqual({key: diff_summary[key] for key in ("status", "candidate_count", "meaning_risk_count",
                                                              "hunk_count")},
                         {"status": "has_candidates", "candidate_count": 1, "meaning_risk_count": 1,
                          "hunk_count": 1})
        self.assertIsNone(record["materials_summary"])
        for key in RESULT_KEYS:
            self.assertIn(key, record["result"])
        self.assertEqual(record["result"]["status"], "executed")
        self.assertEqual(record["result"]["token"], lines[1])
        self.assertEqual(record["result"]["next"], "review")
        self.assertIs(record["result"]["fail_on_hit"], False)
        self.assertEqual(record["result"]["meaning_risk_count"], 1)
        self.assertIs(record["result"]["final_unchanged_during_run"], True)
        self.assertEqual(record["result"]["not_judged"], ["meaning_preservation", "reader_comprehension"])
        self.assertEqual(record["record_digest"], record_digest(record))

    def test_k1_hashes_are_taken_from_raw_bytes_with_bom_and_crlf(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.root / "b.md"
        raw = b"\xef\xbb\xbf" + "保存期間は30日です。\r\n".encode("utf-8")
        b.write_bytes(raw)
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        status, fields = self.status(lines[1])
        self.assertEqual(fields["final"], "sha256:" + sha256_bytes(raw)[:12])
        path, record = self.record_from(lines)
        final = record["inputs"]["final"]
        self.assertEqual(final["sha256"], sha256_bytes(raw))
        self.assertEqual(final["bytes"], len(raw))
        self.assertEqual(final["text_sha256"], sha256_bytes("保存期間は30日です。\n".encode("utf-8")))
        self.assertEqual((final["bom"], final["eol"]), (True, "crlf"))
        self.assertEqual((self.state / final["snapshot"]).read_bytes(), raw)

    def test_k1_state_folder_has_gitignore_and_state_json(self):
        """3.6: 状態フォルダを作るときに .gitignore（2行）と state.json を書く。"""
        self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        gitignore = (self.state / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*", gitignore.splitlines())
        self.assertEqual(gitignore.rstrip("\n").split("\n"), GITIGNORE_LINES)
        self.assertEqual(json.loads((self.state / "state.json").read_text(encoding="utf-8")),
                         {"format": "yomiyasu-state", "format_version": 1})

    @unittest.skipIf(os.name == "nt", "POSIX だけ（3.6）")
    def test_state_folder_and_files_are_private_on_posix(self):
        """3.6: POSIX では、フォルダを 0o700、ファイルを 0o600 にする（原稿の写しを含むため）。"""
        self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        for path in [self.state] + sorted(self.state.rglob("*")):
            mode = path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o700 if path.is_dir() else 0o600, str(path))

    def test_run_json_has_the_result_shape(self):
        """3.5: --json は人向けの文を出さず、結果を1つの JSON で出す。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        result = self.check_json("run", "--source", a, "--final", b)
        for key in RUN_JSON_KEYS:
            self.assertIn(key, result)
        self.assertEqual(list(result)[:3], ["format", "format_version", "tool_version"])
        self.assertEqual((result["format"], result["format_version"], result["tool_version"], result["command"]),
                         ("yomiyasu-check-result", 1, "2.1.1", "run"))
        self.assertEqual(result["status"], "executed")
        self.assertRegex(result["status_line"], K1_STATUS)
        self.assertEqual(result["message"], RUN_REWRITE_FIRST + self.finalize_file())
        self.assertEqual(result["next"], "review")
        self.assertEqual((result["attempt"], result["fix_count"], result["mode"]), (1, 0, "rewrite"))
        self.assertIs(result["fail_on_hit"], False)
        # 10.6 B1: 全件の数と、--fail-on=meaning-risk が数える種類の数
        self.assertEqual((result["meaning_risk_count"], result["fail_on_meaning_risk_count"]), (1, 1))
        self.assertEqual(result["lint"]["format"], "yomiyasu-lint")
        self.assertEqual(result["diff"]["format"], "yomiyasu-diff")
        self.assertIsNone(result["materials"])
        # 10.3 L12: record_path は人の出力の5行目と同じ絶対パス
        self.assertTrue(os.path.isabs(result["record_path"]), result["record_path"])
        self.assertEqual(Path(result["record_path"]), self.state / "runs" / result["run_id"] / "attempt-1.json")
        record = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["run_id"], result["run_id"])
        self.assertEqual(record["result"]["token"], result["status_line"])


class TestK2SameAsCli(CheckCase):
    def test_k2_reports_are_the_cli_outputs(self):
        """K2: 記録のレポートは lint と diff の CLI（--json）の出力のバイト列と同じ。.txt は通常の出力と同じ
        バイト列（設計 10.3 B5。末尾の改行を含む）。"""
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        path, record = self.record_from(lines)
        cli_env = self.env(PYTHONIOENCODING="utf-8")
        commands = {"lint": ([LINT, "--json", b], [LINT, b]), "diff": ([DIFF, "--json", a, b], [DIFF, a, b])}
        for name, (json_args, text_args) in commands.items():
            with self.subTest(check=name):
                entry = self.check_entry(record, name)
                as_json = subprocess.run([sys.executable, "-B"] + [str(x) for x in json_args], cwd=str(self.root),
                                         capture_output=True, env=cli_env, timeout=30)
                self.assertEqual(as_json.returncode, 0, as_json.stderr)
                self.assertEqual((self.state / entry["report"]).read_bytes(), as_json.stdout)
                as_text = subprocess.run([sys.executable, "-B"] + [str(x) for x in text_args], cwd=str(self.root),
                                         capture_output=True, env=cli_env, timeout=30)
                self.assertEqual(as_text.returncode, 0, as_text.stderr)
                self.assertEqual((self.state / entry["text"]).read_bytes(), as_text.stdout)


class TestRunThenVerify(CheckCase):
    """K3〜K16、K20 と 3.5 の1行目の表、3.9 の verify。"""

    def test_k3_verify_after_run(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        status, fields = self.status(lines[1])
        common = ("yomiyasu-check: executed via=verify run={} attempt=1 final=sha256:{} mode=rewrite "
                  "checks=lint,diff meaning_risk=1 replay=").format(fields["run"], sha256_file(b)[:12])
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertEqual(verify_lines, [VERIFY_LINE1["executed"].format(checks="lint、diff"),
                                        common + "skipped", lines[self.record_index(lines)],
                                        "記録の中身: 見直し候補 最終稿 0件、直した箇所 1か所（原文の件数と元と後は run の出力にあります）"])
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, "--replay"), "executed", code=0)
        self.assertEqual(verify_lines[1], common + "ok")

    def test_k3_verify_json_has_the_result_shape(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        path, record = self.record_from(lines)
        result = self.check_json("verify", "--final", b)
        for key in VERIFY_JSON_KEYS:
            self.assertIn(key, result)
        self.assertEqual(list(result)[:3], ["format", "format_version", "tool_version"])
        self.assertEqual((result["format"], result["format_version"], result["tool_version"], result["command"]),
                         ("yomiyasu-check-result", 1, "2.1.1", "verify"))
        self.assertEqual(result["status"], "executed")
        self.assertEqual(self.status(result["status_line"])[0], "executed")
        self.assertEqual(result["message"], VERIFY_LINE1["executed"].format(checks="lint、diff"))
        self.assertEqual((result["run_id"], result["attempt"]), (record["run_id"], 1))
        self.assertEqual(Path(result["record_path"]), path)
        self.assertEqual(set(result["final"]), {"path", "via", "sha256", "text_sha256"})
        self.assertEqual(result["final"]["sha256"], record["inputs"]["final"]["sha256"])
        self.assertEqual(result["record_final_sha256"], record["inputs"]["final"]["sha256"])
        self.assertEqual((result["mode"], result["required_checks"]), ("rewrite", ["lint", "diff"]))
        self.assertEqual(result["checks"], {"lint": "ran", "diff": "ran"})
        self.assertEqual((result["meaning_risk_count"], result["replay"], result["problems"]), (1, "skipped", []))

    def test_k4_lint_alone_leaves_no_record(self):
        """K4（事例の形）: lint の CLI だけを実行し、check を使わなければ記録はない。"""
        b = self.write("b.md", "保存期間は30日です。\n")
        lint = subprocess.run([sys.executable, "-B", str(LINT), str(b)], cwd=str(self.root), env=self.env(),
                              capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(lint.returncode, 0, lint.stderr)
        lines, fields = self.assert_verify(self.check("verify", "--final", b), "no_record")
        self.assertEqual(lines[0], VERIFY_LINE1["no_record"])
        self.assertEqual((fields["run"], fields["attempt"]), ("-", "-"))
        # 10.4 S10: 状態フォルダがないときも、先にハッシュを計算して final= に出す（フックや採点器が読む値をそろえる）
        self.assertEqual(fields["final"], "sha256:" + sha256_file(b)[:12])
        self.assertEqual(lines[2], NO_RECORD_LINE3.format(self.state))
        self.assertFalse(self.state.exists(), "verify は状態フォルダを作らない")

    def test_k5_record_without_a_required_check_is_incomplete(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        path, record = self.record_from(lines)
        record["checks"] = [entry for entry in record["checks"] if entry["name"] != "diff"]
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "incomplete")
        # 10.3 C3: {足りない検査} は検査名を「、」でつなぐ。ここで足りないのは diff だけ
        self.assertEqual(verify_lines[0], "記録に diff" + VERIFY_INCOMPLETE_TAIL)

    def test_k6_record_of_another_file(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        run_id = self.status(lines[1])[1]["run"]
        c = self.write("c.md", "保存期間は7日です。\n")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", c), "no_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["no_record"])
        verify_lines, _ = self.assert_verify(self.check("verify", "--run-id", run_id, "--final", c), "wrong_file")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["wrong_file"])
        c.write_bytes(b.read_bytes())  # 検査した最終稿を別の場所に写す
        for extra in ([], ["--run-id", run_id]):
            with self.subTest(extra=extra):
                self.assert_verify(self.check("verify", "--final", c, *extra), "executed", code=0)
                result = self.check_json("verify", "--final", c, *extra)
                self.assertEqual(result["status"], "executed")
                self.assertIn("final_path_differs", [problem["code"] for problem in result["problems"]])

    def test_k7_edit_after_run_then_run_again(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        run_id = self.status(lines[1])[1]["run"]
        first_path, first = self.record_from(lines)
        old_sha = sha256_file(b)
        b.write_bytes("保存期間は300日です。\n".encode("utf-8"))  # 1字足す
        new_sha = sha256_file(b)
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b), "final_changed")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["final_changed"])
        self.assertEqual(fields["expected"], "sha256:" + old_sha[:12])
        self.assertEqual(fields["final"], "sha256:" + new_sha[:12])
        process, again = self.check_ok("run", "--source", a, "--final", b)
        status, fields = self.status(again[1])
        self.assertEqual((status, fields["run"], fields["attempt"]), ("executed", run_id, "2"))
        self.assertEqual(again[0], RUN_AFTER_FIX + self.finalize_file())
        path, record = self.record_from(again)
        self.assertEqual(path, first_path.parent / "attempt-2.json")
        self.assertEqual(record["fix_count"], 1)
        self.assertEqual(record["previous"], {"attempt": 1, "final_sha256": first["inputs"]["final"]["sha256"]})
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertEqual((fields["run"], fields["attempt"]), (run_id, "2"))

    def test_example_2_after_fix_and_verify(self):
        """3.5 の例2（直したあとの2回目と、提出の直前の verify）。"""
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        run_id = self.status(lines[1])[1]["run"]
        b.write_bytes("データの保存期間は3日です。\n".encode("utf-8"))
        process, again = self.check_ok("run", "--source", a, "--final", b)
        record = self.state / "runs" / run_id / "attempt-2.json"
        line1 = RUN_AFTER_FIX + self.finalize_file()
        line2 = ("yomiyasu-check: executed via=run run={} attempt=2 final=sha256:{} mode=rewrite "
                 "checks=lint,diff meaning_risk=0").format(run_id, sha256_file(b)[:12])
        self.assertEqual(again, [
            line1,
            line2,
            "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更あり 候補1件（うち意味が変わる恐れ0件）",
            "diff の候補: 元の文にない語",
            RUN_HEAD_NOTE,
            RUN_DISCLAIMER,
            "記録: " + str(record),
            "硬化の検査: 候補なし",
            "勢いの検査: 候補なし",
            "慎重表現の検査: 候補なし",
            "値の検査: 候補なし",
            "見直し候補: 原文 0件 → 最終稿 0件（lint の規則に当たった数で、点数ではありません。増えても減っても読みやすさの良し悪しは示しません）",
            "",
            "■ 直した箇所（1か所。元と後）",
            "@ 元1行目 → 後1行目（本文）",
            "  元: 保存期間は3日です。",
            "  後: データの保存期間は3日です。",
            "- 省いていない元と後は下の「■ 全文差分」と、記録と同じフォルダの attempt-2.diff.txt にあります。",
            "",
            "■ 差分の見直し候補（diff、1件）",
            "■ 元の文にない語: データ",
            "",
            "■ 全文差分（変更 1か所。省略していません）",
            "@ 元1行目 → 後1行目（本文）",
            "  元: 保存期間は3日です。",
            "  後: データの保存期間は3日です。",
            "  差: {+データの+}保存期間は3日です。",
            "",
            line1,
            line2,
        ])
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertEqual(verify_lines, [
            VERIFY_LINE1["executed"].format(checks="lint、diff"),
            ("yomiyasu-check: executed via=verify run={} attempt=2 final=sha256:{} mode=rewrite checks=lint,diff "
             "meaning_risk=0 replay=skipped").format(run_id, sha256_file(b)[:12]),
            "記録: " + str(record),
            "記録の中身: 見直し候補 最終稿 0件、直した箇所 1か所（原文の件数と元と後は run の出力にあります）",
        ])

    def test_k8_only_line_endings_changed(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        b.write_bytes(b.read_bytes().replace(b"\n", b"\r\n"))
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "final_changed")
        self.assertIn(VERIFY_LINE1["final_changed"], verify_lines[0])
        self.assertIn(LINE_ENDINGS_NOTE, verify_lines[0])
        result = self.check_json("verify", "--final", b, code=1)
        self.assertEqual(result["status"], "final_changed")
        self.assertIn("only_line_endings_differ", [problem["code"] for problem in result["problems"]])

    def test_k9_second_fix_is_over_the_limit_but_not_stopped(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        b.write_bytes("保存期間は300日です。\n".encode("utf-8"))
        self.check_ok("run", "--source", a, "--final", b)
        b.write_bytes("保存期間は3000日です。\n".encode("utf-8"))
        result = self.check_json("run", "--source", a, "--final", b)
        self.assertEqual(result["status"], "executed")
        self.assertIn("修正は1回までの決まりを超えています（このコマンドは止めません）", result["message"])
        self.assertEqual(result["message"], RUN_OVER_LIMIT.format(n=2) + self.finalize_file())
        self.assertEqual(result["next"], "finalize_over_limit")
        self.assertEqual((result["attempt"], result["fix_count"]), (3, 2))

    def test_k10_same_final_again_is_not_a_fix(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        run_id = self.status(lines[1])[1]["run"]
        process, again = self.check_ok("run", "--source", a, "--final", b)
        self.assertIn("前回と同じ最終稿", again[0])
        self.assertEqual(again[0], RUN_SAME_FINAL + self.finalize_file())
        status, fields = self.status(again[1])
        self.assertEqual((fields["run"], fields["attempt"]), (run_id, "2"))
        path, record = self.record_from(again)
        self.assertEqual(record["fix_count"], 0)
        self.assertEqual(record["result"]["next"], "finalize")

    def test_k11_hand_written_record_is_invalid(self):
        b = self.write("b.md", "保存期間は30日です。\n")
        run_dir = self.state / "runs" / "x"
        run_dir.mkdir(parents=True)
        (run_dir / "attempt-1.json").write_text('{"reviewed": true}', encoding="utf-8")
        index = self.state / "index" / "by-final" / sha256_file(b)
        index.mkdir(parents=True)
        (index / "x.1").write_bytes(b"")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "invalid_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["invalid_record"])

    def test_k12_record_edited_without_digest_is_invalid(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        path, record = self.record_from(lines)
        self.check_entry(record, "lint")["report_sha256"] = "0" * 64
        self.save_record(path, record)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "invalid_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["invalid_record"])

    def test_k13_crafted_record_is_found_only_by_replay(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        path, record = self.record_from(lines)
        entry = self.check_entry(record, "diff")
        report = json.loads((self.state / entry["report"]).read_text(encoding="utf-8"))
        report["meaning_risks"] = []  # 意味が変わる恐れを隠したレポートに作り替える
        report["meaning_risk_count"] = 0
        report["fail_on_meaning_risk_count"] = 0
        crafted = (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii")
        (self.state / entry["report"]).write_bytes(crafted)
        entry["report_sha256"] = sha256_bytes(crafted)
        # check の固め（勧め49）: 記録の件数もレポートに合わせて作り込む（件数だけの食い違いは --replay なしでも見つかる）
        entry["summary"]["meaning_risk_count"] = 0
        entry["summary"]["fail_on_meaning_risk_count"] = 0
        record["result"]["meaning_risk_count"] = 0
        record["result"]["fail_on_meaning_risk_count"] = 0
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, "--replay"), "not_reproducible")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["not_reproducible"])

    def test_k14_script_changed_after_the_record(self):
        scripts = self.skill_copy()
        script = scripts / "yomiyasu_check.py"
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b, script=script)
        path, record = self.record_from(lines)
        self.assertIs(record["skill"]["found"], True)
        self.assertEqual(os.path.realpath(record["skill"]["dir"]), str(scripts.parent))
        self.assertEqual(record["skill"]["skill_md_sha256"], sha256_file(scripts.parent / "SKILL.md"))
        for name in TOOL_NAMES:
            self.assertEqual(record["tools"][name]["sha256"], sha256_file(scripts / name))
        self.assert_verify(self.check("verify", "--final", b, script=script), "executed", code=0)
        with open(str(scripts / "yomiyasu_lint.py"), "ab") as handle:
            handle.write(b"# changed after the record by test_v200_check\n")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, script=script), "tool_changed")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["tool_changed"])

    def test_k15_record_older_than_since_is_stale(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, "--since", utc_text(1)),
                                             "stale_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["stale_record"])
        self.assert_verify(self.check("verify", "--final", b, "--since", "2000-01-01T00:00:00Z"), "executed", code=0)

    def test_k16_same_final_from_two_sources_is_ambiguous(self):
        a1 = self.write("a1.md", "保存期間は3日です。\n")
        a2 = self.write("a2.md", "保存期間は5日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        first = self.status(self.check_ok("run", "--source", a1, "--final", b)[1][1])[1]["run"]
        second = self.status(self.check_ok("run", "--source", a2, "--final", b)[1][1])[1]["run"]
        self.assertNotEqual(first, second)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "ambiguous")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["ambiguous"])
        _, fields = self.assert_verify(self.check("verify", "--final", b, "--run-id", first), "executed", code=0)
        self.assertEqual(fields["run"], first)
        _, fields = self.assert_verify(self.check("verify", "--final", b, "--source", a2), "executed", code=0)
        self.assertEqual(fields["run"], second)

    def test_verify_with_other_source(self):
        """3.9 の5: --source のハッシュが記録の原文と違えば other_source。"""
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        other = self.write("other.md", "保存期間は5日です。\n")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, "--source", other), "other_source")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["other_source"])

    def test_k20_final_same_as_source(self):
        a, b, lines = self.run_pair("保存期間は30日です。\n", "保存期間は30日です。\n")
        self.assertIn("原文から変更はありません", lines[0])
        self.assertEqual(lines[0], RUN_NO_CHANGE + self.finalize_file())
        self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更なし 候補0件（うち意味が変わる恐れ0件）")
        result = self.check_json("run", "--source", a, "--final", b)  # 表は上から当てはめる（変更なしが先）
        self.assertEqual((result["message"], result["next"]), (RUN_NO_CHANGE + self.finalize_file(), "finalize"))

    def test_first_rewrite_without_candidates(self):
        """3.5 の表の「推敲の1回目、候補なし」。読点を1つ足しただけの組（6.1 と同じ）。"""
        a, b, lines = self.run_pair("会議は3時に始まります。\n", "会議は、3時に始まります。\n")
        self.assertEqual(lines[0], RUN_REWRITE_FIRST_NO_CANDIDATES + self.finalize_file())
        self.assertEqual(self.status(lines[1])[1]["meaning_risk"], "0")
        self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更あり 候補0件（うち意味が変わる恐れ0件）")
        self.assertEqual(self.record_from(lines)[1]["result"]["next"], "review")


class TestVerifyDetails(CheckCase):
    """3.9 の verify の細部（6.5 の表にない形）。check の段の後半で、verify を作る前に足した。"""

    def run_record(self, before="保存期間は3日です。\n", after="保存期間は30日です。\n", *extra):
        a, b, lines = self.run_pair(before, after, *extra)
        path, record = self.record_from(lines)
        return a, b, lines, path, record

    def test_usage_errors_write_nothing(self):
        """3.10: verify の使い方と入力の誤りは2。標準出力は空で、状態フォルダを作らない。"""
        b = self.write("b.md", "保存期間は30日です。\n")
        missing = self.root / "missing.md"
        cases = (
            (["--final", missing], "Error opening file {}: ファイルを開けません（".format(missing)),
            (["--final", b, "--source", missing], "Error opening file {}: ファイルを開けません（".format(missing)),
            (["--final", b, "--run-id", "../x"], "--run-id に使えない値です: ../x。"),
            (["--final", b, "--run-id", ""], "--run-id に使えない値です: （空）。"),
            (["--final", b, "--since", "yesterday"], "--since"),
            (["--final", b, "--since", "2026-10-13T01:45:00"], "--since"),  # 時差のない時刻は受けない（UTC か現地時刻か決められない）
            (["--final", b, "--timeout", "0"], "--timeout"),
            (["--final", b, "--state-dir", ""], "--state-dir"),
            (["--final", "-", "--source", "-"], "標準入力（-）は1か所だけ"),
            (["--final", b, "--nope"], "引数の誤りです。yomiyasu_check.py verify -h で使い方を確かめてください。"),
            (["--final", b, "--rep"], "引数の誤りです。"),  # 10.7: 省略形を受けない
            (["--final", b, "--json", "extra.md"], "引数の誤りです。"),
        )
        for args, message in cases:
            with self.subTest(args=[str(x) for x in args]):
                process = self.check("verify", *args, stdin="")
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn(message, process.stderr)
                self.assertFalse(self.state.exists())

    def test_non_utf8_stdin_is_an_input_error(self):
        """3.9 の2: --final - は標準入力の本文のハッシュで照らすので、UTF-8 として読めなければ2。"""
        process = subprocess.run([sys.executable, "-B", str(CHECK), "verify", "--final", "-"],
                                 input="保存期間は30日です。\n".encode("cp932"), cwd=str(self.root), env=self.env(),
                                 capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 2, process.stderr.decode("utf-8", "replace"))
        self.assertEqual(process.stdout, b"")
        self.assertIn("Error reading stdin: UTF-8 として読めません", process.stderr.decode("utf-8"))

    def test_no_record_json_shape(self):
        """3.9 の --json: 記録が見つからないときも同じキーを出す。記録から取る値は null。"""
        b = self.write("b.md", "保存期間は30日です。\n")
        result = self.check_json("verify", "--final", b, code=1)
        for key in VERIFY_JSON_KEYS:
            self.assertIn(key, result)
        self.assertEqual(list(result)[:3], ["format", "format_version", "tool_version"])
        self.assertEqual((result["status"], result["command"], result["message"]),
                         ("no_record", "verify", VERIFY_LINE1["no_record"]))
        self.assertEqual(result["final"], {"path": str(b), "via": "file", "sha256": sha256_file(b),
                                           "text_sha256": text_sha256(b.read_bytes())})
        for key in ("run_id", "attempt", "record_path", "record_final_sha256", "mode", "required_checks", "checks",
                    "meaning_risk_count"):
            self.assertIsNone(result[key], key)
        self.assertEqual(result["replay"], "skipped")
        self.assertTrue(result["problems"])
        for problem in result["problems"]:
            self.assertEqual(set(problem), {"code", "detail"})
        self.assertFalse(self.state.exists())

    def test_two_runs_with_the_same_source_are_not_ambiguous(self):
        """3.9 の3: 見つかった記録の原文が同じなら、曖昧にせず最新の記録を使う。"""
        a, b, lines, path, record = self.run_record()
        process, again = self.check_ok("run", "--source", a, "--final", b, "--new-run")
        second = self.status(again[1])[1]["run"]
        self.assertNotEqual(second, record["run_id"])
        _, fields = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertEqual((fields["run"], fields["attempt"]), (second, "1"))

    def test_unknown_run_id_is_no_record(self):
        a, b, lines, path, record = self.run_record()
        lines, fields = self.assert_verify(self.check("verify", "--final", b, "--run-id", "no-such-run"), "no_record")
        self.assertEqual(lines[2], NO_RECORD_LINE3.format(self.state))

    def test_final_changed_with_run_id_for_a_file(self):
        """3.9 の3: --run-id があり、その実行の最新の記録の最終稿のパスが今のパスと同じなら final_changed。"""
        a, b, lines, path, record = self.run_record()
        old = sha256_file(b)
        b.write_bytes("保存期間は31日です。\n".encode("utf-8"))
        verify_lines, fields = self.assert_verify(
            self.check("verify", "--final", b, "--run-id", record["run_id"]), "final_changed")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["final_changed"])
        self.assertEqual((fields["run"], fields["attempt"], fields["expected"]),
                         (record["run_id"], "1", "sha256:" + old[:12]))
        self.assertEqual(verify_lines[2], "記録: " + str(path))

    def test_ambiguous_lists_the_run_ids(self):
        """ambiguous の3行目には、選べる実行IDを並べる（--run-id に渡せるように）。JSON の record_path は null。"""
        a1 = self.write("a1.md", "保存期間は3日です。\n")
        a2 = self.write("a2.md", "保存期間は5日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        first = self.status(self.check_ok("run", "--source", a1, "--final", b)[1][1])[1]["run"]
        second = self.status(self.check_ok("run", "--source", a2, "--final", b)[1][1])[1]["run"]
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b), "ambiguous")
        self.assertTrue(verify_lines[2].startswith("記録: "), verify_lines[2])
        self.assertIn(first, verify_lines[2])
        self.assertIn(second, verify_lines[2])
        self.assertEqual((fields["run"], fields["attempt"]), ("-", "-"))
        result = self.check_json("verify", "--final", b, code=1)
        self.assertEqual((result["status"], result["record_path"], result["run_id"]), ("ambiguous", None, None))

    def test_record_moved_to_another_attempt_is_invalid(self):
        """3.9 の4: run_id と attempt がファイルの場所と合わない記録は invalid_record。"""
        a, b, lines, path, record = self.run_record()
        moved = path.parent / "attempt-2.json"
        moved.write_bytes(path.read_bytes())
        path.unlink()
        index = self.state / "index" / "by-final" / sha256_file(b)
        for entry in list(index.iterdir()):
            entry.unlink()
        (index / "{}.2".format(record["run_id"])).write_bytes(b"")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "invalid_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["invalid_record"])

    def test_broken_and_empty_records_are_invalid(self):
        """3.9 の4: JSON として読めない記録、中身が空の記録（50ミリ秒待って読み直しても空）は invalid_record。"""
        for number, data in enumerate((b"{", b"[1, 2]", b"")):
            with self.subTest(data=data):
                b = self.write("b{}.md".format(number), "保存期間は{}0日です。\n".format(number + 1))
                run_dir = self.state / "runs" / "hand-{}".format(number)
                run_dir.mkdir(parents=True)
                (run_dir / "attempt-1.json").write_bytes(data)
                index = self.state / "index" / "by-final" / sha256_file(b)
                index.mkdir(parents=True)
                (index / "hand-{}.1".format(number)).write_bytes(b"")
                self.assert_verify(self.check("verify", "--final", b), "invalid_record")

    def test_missing_snapshot_or_changed_reports_are_invalid(self):
        """3.9 の8: 写し（inputs）とレポート（.json と .txt）のファイルがあり、ハッシュが記録と同じか。"""
        cases = ("source snapshot removed", "diff text changed", "lint report removed", "final snapshot changed")
        for number, case in enumerate(cases):
            with self.subTest(case=case):
                a = self.write("a{}.md".format(number), "設定{}の保存期間は3日です。\n".format(number))
                b = self.write("b{}.md".format(number), "設定{}の保存期間は30日です。\n".format(number))
                process, lines = self.check_ok("run", "--source", a, "--final", b)
                path, record = self.record_from(lines)
                if case == "source snapshot removed":
                    (self.state / record["inputs"]["source"]["snapshot"]).unlink()
                elif case == "diff text changed":
                    with open(str(self.state / self.check_entry(record, "diff")["text"]), "ab") as handle:
                        handle.write("書き足した行\n".encode("utf-8"))
                elif case == "lint report removed":
                    (self.state / self.check_entry(record, "lint")["report"]).unlink()
                else:
                    (self.state / record["inputs"]["final"]["snapshot"]).write_bytes(b"changed\n")
                verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "invalid_record")
                self.assertEqual(verify_lines[0], VERIFY_LINE1["invalid_record"])

    def test_required_checks_follow_the_mode(self):
        """3.3 と 3.9 の7: 推敲の記録は、required_checks から diff を消して digest を作り直しても incomplete。
        検査の target のハッシュが inputs と違うときも incomplete。"""
        a, b, lines, path, record = self.run_record()
        original = json.loads(path.read_text(encoding="utf-8"))
        record["checks"] = [entry for entry in record["checks"] if entry["name"] != "diff"]
        record["required_checks"] = ["lint"]
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b), "incomplete")
        self.assertEqual(verify_lines[0], "記録に diff" + VERIFY_INCOMPLETE_TAIL)
        record = original
        self.check_entry(record, "diff")["target"]["source"] = "0" * 64
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "incomplete")
        self.assertEqual(verify_lines[0], "記録に diff" + VERIFY_INCOMPLETE_TAIL)

    def test_partial_record_is_incomplete(self):
        """K28 の記録（時間切れ）を verify すると incomplete。止まった検査を1行目に「、」でつなぐ（10.3 C3）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", b, "--timeout", "0.001")
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        failed = self.status(split_lines(process.stdout)[1])[1]["failed"]
        names = [item.split("(")[0] for item in failed.split(",")]
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b), "incomplete")
        self.assertEqual(verify_lines[0], VERIFY_PARTIAL_LINE.format(
            "、".join(names) + " は時間切れ", "、".join(name + "（時間切れ）" for name in names)))
        self.assertEqual((fields["mode"], fields["checks"]), ("rewrite", "lint,diff"))

    def test_replay_timeout_is_incomplete(self):
        """3.9 の10: --replay の作り直しが時間切れなら incomplete（problems に replay_timeout、replay=timeout）。"""
        a, b, lines, path, record = self.run_record()
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b, "--replay", "--timeout", "0.001"),
                                                  "incomplete")
        self.assertEqual(fields["replay"], "timeout")
        self.assertIn("時間切れ", verify_lines[0])
        self.assertIn("--timeout", verify_lines[0])
        result = self.check_json("verify", "--final", b, "--replay", "--timeout", "0.001", code=1)
        self.assertEqual((result["status"], result["replay"]), ("incomplete", "timeout"))
        self.assertIn("replay_timeout", [problem["code"] for problem in result["problems"]])

    def test_skill_md_change_is_only_a_problem(self):
        """3.9 の9: SKILL.md のハッシュだけが違うときは、problems に skill_changed を入れるだけ（executed）。"""
        scripts = self.skill_copy()
        script = scripts / "yomiyasu_check.py"
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b, script=script)
        with open(str(scripts.parent / "SKILL.md"), "ab") as handle:
            handle.write("\n<!-- changed after the record by test_v200_check -->\n".encode("utf-8"))
        self.assert_verify(self.check("verify", "--final", b, script=script), "executed", code=0)
        result = self.check_json("verify", "--final", b, script=script)
        self.assertEqual(result["status"], "executed")
        self.assertIn("skill_changed", [problem["code"] for problem in result["problems"]])

    def test_compose_record_verifies_and_replays(self):
        """新規作成の記録も verify と --replay で照らせる（照合はプロセスの中で作り直す）。"""
        m = self.write("m.md", "最大5回まで再試行する。\n")
        f = self.write("f.md", "再試行は最大3回です。\n")
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        path, record = self.record_from(lines)
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", f), "executed", code=0)
        # 5.2: 人が読む文の検査名は「lint、diff、資料との照合、最終稿の照合」の語（状態の行の checks= は名前のまま）
        self.assertEqual(verify_lines[0], VERIFY_LINE1["executed"].format(checks="lint、資料との照合"))
        self.assertEqual((fields["mode"], fields["checks"], fields["meaning_risk"], fields["replay"]),
                         ("compose", "lint,materials", "1", "skipped"))
        _, fields = self.assert_verify(self.check("verify", "--final", f, "--replay"), "executed", code=0)
        self.assertEqual(fields["replay"], "ok")
        # 照合の中身を作り替えて report_sha256 と digest を合わせても、--replay で見つける（K13 の照合の版）
        entry = self.check_entry(record, "materials")
        report = json.loads((self.state / entry["report"]).read_text(encoding="utf-8"))
        report["meaning_risks"] = []
        report["meaning_risk_count"] = 0
        crafted = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        (self.state / entry["report"]).write_bytes(crafted)
        entry["report_sha256"] = sha256_bytes(crafted)
        # check の固め（勧め49）: 記録の件数もレポートに合わせて作り込む
        entry["summary"]["meaning_risk_count"] = 0
        record["result"]["meaning_risk_count"] = 0
        record["result"]["fail_on_meaning_risk_count"] = 0
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", f), "executed", code=0)
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", f, "--replay"), "not_reproducible")
        self.assertEqual(fields["replay"], "mismatch")

    def test_replay_finds_a_crafted_text_report(self):
        """--replay は人が読む .txt も作り直して比べる（候補を消した .txt を見つける）。"""
        a, b, lines, path, record = self.run_record()
        entry = self.check_entry(record, "diff")
        crafted = "状態: 変更はあるが、専用の規則に当たる見直し候補はない\n".encode("utf-8")
        (self.state / entry["text"]).write_bytes(crafted)
        entry["text_sha256"] = sha256_bytes(crafted)
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assert_verify(self.check("verify", "--final", b, "--replay"), "not_reproducible")

    def test_rewrite_with_material_on_stdin_replays(self):
        body = ("<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:material>>>\n保存期間は30日に変更した。\n"
                "<<<yomiyasu:final>>>\n保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--stdin", stdin=body)
        self.assertEqual(self.status(lines[1])[1]["checks"], "lint,diff,materials")
        _, fields = self.assert_verify(self.check("verify", "--final", "-", "--replay", stdin="保存期間は30日です。\n"),
                                       "executed", code=0)
        self.assertEqual((fields["checks"], fields["replay"]), ("lint,diff,materials", "ok"))

    def test_index_entry_without_record_is_skipped(self):
        """索引が指す記録のファイルがないときは、その索引を飛ばす。"""
        b = self.write("b.md", "保存期間は30日です。\n")
        index = self.state / "index" / "by-final" / sha256_file(b)
        index.mkdir(parents=True)
        (index / "ghost-run.1").write_bytes(b"")
        self.assert_verify(self.check("verify", "--final", b), "no_record")
        a = self.write("a.md", "保存期間は3日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        _, fields = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertEqual(fields["run"], self.status(lines[1])[1]["run"])

    def test_text_index_finds_a_file_record(self):
        """3.6 の by-text はファイルで渡した記録にも書く。返答の本文を verify --final - で照らせる。"""
        a, b, lines, path, record = self.run_record()
        _, fields = self.assert_verify(self.check("verify", "--final", "-", stdin="保存期間は30日です。\n\n"),
                                       "executed", code=0)
        self.assertEqual(fields["final"], "text-sha256:" + text_sha256(b.read_bytes())[:12])
        self.assertEqual(fields["run"], record["run_id"])
        result = self.check_json("verify", "--final", "-", stdin="保存期間は30日です。")
        self.assertEqual((result["final"]["path"], result["final"]["via"]), (None, "stdin"))

    def test_since_forms(self):
        """3.9 の6: --since は時差つきの ISO 8601。同じ秒の記録は古いとみなさない（記録の時刻は秒まで）。"""
        a, b, lines, path, record = self.run_record()
        created = record["created_at"]
        for value in ("2000-01-01T00:00:00Z", "2000-01-01T09:00:00+09:00", "2000-01-01T00:00:00.250Z",
                      created, created[:-1] + ".999Z", created[:-1] + "+00:00"):
            with self.subTest(since=value):
                self.assert_verify(self.check("verify", "--final", b, "--since", value), "executed", code=0)
        later = (datetime.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ") + datetime.timedelta(seconds=1))
        for value in (later.strftime("%Y-%m-%dT%H:%M:%SZ"), later.strftime("%Y-%m-%dT%H:%M:%S") + "-00:00",
                      (later + datetime.timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"):
            with self.subTest(since=value):
                self.assert_verify(self.check("verify", "--final", b, "--since", value), "stale_record")

    def test_help_of_verify(self):
        env = self.env(COLUMNS="2000", NO_COLOR="1")
        process = self.check("verify", "-h", env=env)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertIn("読むだけで、何も書きません", process.stdout)
        tail = process.stdout.rstrip("\n").split("\n")[-5:]
        self.assertEqual(tail[0], "終了コード:", process.stdout)


class TestRunOptions(CheckCase):
    """3.2 と 3.8 の引数（K18、K35 と、表にない引数の誤り）。"""

    def test_k18_same_file_without_start_is_a_usage_error(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        process = self.check("run", "--source", a, "--final", a)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn("別のファイル", process.stderr)
        self.assertIn(SAME_FILE_ERROR, process.stderr)
        self.assertFalse(self.state.exists(), "2 のときは何も書かない")

    def test_mode_needs_source_or_material(self):
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--final", b)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertNotEqual(process.stderr, "")
        self.assertFalse(self.state.exists())

    def test_unknown_stance_is_a_usage_error(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", b, "--stance", "知らない立場")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertFalse(self.state.exists())
        # STANCES のキーは受け、記録の options.stance には正規化した値を入れる（10.3 C5）
        for given, normalized in (("説明", "説明"), ("報告", "説明"), ("手順", "決まり")):
            with self.subTest(stance=given):
                process, lines = self.check_ok("run", "--source", a, "--final", b, "--new-run", "--stance", given)
                self.assertEqual(self.record_from(lines)[1]["options"]["stance"], normalized)

    def test_verify_without_final_is_a_usage_error(self):
        process = self.check("verify")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertNotEqual(process.stderr, "")

    def test_k35_default_subcommand_and_aliases(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("--original", a, "--final", b)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields["via"], fields["mode"]), ("executed", "run", "rewrite"))
        m = self.write("m.md", "最大5回まで再試行する。\n")
        f = self.write("f.md", "再試行は最大5回です。\n")
        process, lines = self.check_ok("--materials", m, "--final", f)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields["via"], fields["mode"]), ("executed", "run", "compose"))

    def test_run_id_new_run_and_other_source(self):
        """3.8 の1と2: --run-id と --new-run。別の原文で同じ実行IDを使うと2。"""
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n", "--run-id", "ci-run.1")
        self.assertEqual(self.status(lines[1])[1]["run"], "ci-run.1")
        self.assertTrue((self.state / "runs" / "ci-run.1" / "attempt-1.json").is_file())
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--new-run")
        status, fields = self.status(lines[1])
        self.assertNotEqual(fields["run"], "ci-run.1")
        self.assertRegex(fields["run"], "^" + RUN_ID + "$")
        self.assertEqual(fields["attempt"], "1")
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + self.finalize_file())
        other = self.write("other.md", "保存期間は5日です。\n")
        before = tree_digest(self.state)
        process = self.check("run", "--source", other, "--final", b, "--run-id", "ci-run.1")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn("別の原文の実行IDです", process.stderr)
        # 10.3 C4: 終了コード2の確かめは、状態フォルダへ何かを書く前に済ませる（写しも置かない）
        self.assertEqual(tree_digest(self.state), before)

    def test_run_id_outside_the_pattern_is_rejected(self):
        """3.7: 外から渡す実行IDは ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ だけ。状態フォルダの外に書かせない。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", b, "--run-id", "../../escaped")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertFalse((self.root / "escaped").exists())
        self.assertEqual(tree_listing(self.root, skip=self.state), ["a.md", "b.md"])
        self.assertFalse(self.state.exists(), "実行IDの形の誤りは、状態フォルダに書く前に確かめる（10.3 C4）")

    def test_state_dir_option_comes_before_the_environment(self):
        """3.2 と 3.6 の1: --state-dir は YOMIYASU_STATE_DIR より先に使う（run も verify も）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        other = self.root / "other-state"
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--state-dir", other)
        run_id = self.status(lines[1])[1]["run"]
        self.assertEqual(lines[self.record_index(lines)], "記録: " + str(other / "runs" / run_id / "attempt-1.json"))
        self.assertTrue((other / "runs" / run_id / "attempt-1.json").is_file())
        self.assertFalse(self.state.exists(), "YOMIYASU_STATE_DIR の場所には書かない")
        _, fields = self.assert_verify(self.check("verify", "--final", b, "--state-dir", other), "executed", code=0)
        self.assertEqual(fields["run"], run_id)
        self.assert_verify(self.check("verify", "--final", b), "no_record")
        self.assertFalse(self.state.exists(), "verify は状態フォルダを作らない")

    def test_session_option_and_environment(self):
        """3.2: --session は記録に入れるだけ。省くと YOMIYASU_SESSION。${ を含む値は null。"""
        cases = (
            (["--session", "s-1"], {}, "s-1"),
            ([], {"YOMIYASU_SESSION": "s-2"}, "s-2"),
            (["--session", "${CLAUDE_SESSION_ID}"], {}, None),
            ([], {"YOMIYASU_SESSION": "${CLAUDE_SESSION_ID}"}, None),
        )
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        for extra, env, expected in cases:
            with self.subTest(extra=extra, env=env):
                process, lines = self.check_ok("run", "--source", a, "--final", b, "--new-run", *extra,
                                               env=self.env(**env))
                self.assertEqual(self.record_from(lines)[1]["host"]["session"], expected)

    def test_fail_on_lint_severity(self):
        """3.2: --fail-on の warn と error は lint の候補で決める。何度でも、カンマ区切りも受ける。"""
        a = self.write("a.md", "テストを書くことが大切です。\n")
        b = self.write("b.md", "重要なのは、テストを書くことです。\n")  # lint の warn（meta_filler）が1件
        cases = ((["--fail-on=warn"], 1), (["--fail-on", "error"], 0), (["--fail-on=error,warn"], 1),
                 (["--fail-on", "error", "--fail-on", "warn"], 1), ([], 0))
        for extra, code in cases:
            with self.subTest(extra=extra):
                process = self.check("run", "--source", a, "--final", b, "--new-run", *extra)
                self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
        process = self.check("run", "--source", a, "--final", b, "--new-run", "--fail-on=warn")
        self.assertTrue(split_lines(process.stdout)[0].startswith(FAIL_ON_HEAD.format("warn")), process.stdout)
        process = self.check("run", "--source", a, "--final", b, "--new-run", "--fail-on=nope")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)


class TestComposeAndMaterials(CheckCase):
    """K21〜K23、3.3 の資料との照合、3.5 の例3。"""

    def test_example_3_compose(self):
        m1 = self.write("m1.md", "接続の再試行は未確認です。ログは14日残す。\n")
        m2 = self.write("m2.md", "一度に送るのは最大10件です。\n")
        f = self.write("f.md", "接続の再試行について書く。\n\n再試行は自動で行う。\n再試行は最大3回です。\n")
        process, lines = self.check_ok("run", "--material", m1, "--material", m2, "--final", f)
        run_id = self.status(lines[1])[1]["run"]
        line1 = RUN_COMPOSE_FIRST + self.finalize_file()
        line2 = ("yomiyasu-check: executed via=run run={} attempt=1 final=sha256:{} mode=compose "
                 "checks=lint,materials meaning_risk=1").format(run_id, sha256_file(f)[:12])
        self.assertEqual(lines, [
            line1,
            line2,
            "実行した検査: lint（最終稿）候補0件、資料との照合（資料2件→最終稿）資料にない数値・名前1件",
            "資料との照合の候補: 後4行目 資料にない数値、資料にない語、最終稿にない確度の語",
            RUN_HEAD_NOTE,
            RUN_DISCLAIMER,
            "記録: " + str(self.state / "runs" / run_id / "attempt-1.json"),
            "見直し候補: 最終稿 0件（新規作成なので原文の件数はありません。lint の規則に当たった数で、点数ではありません）",
            "",
            "■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）",
            "- 資料にない数値（後4行目）: 3回",
            "  後: 再試行は最大3回です。",
            "",
            "■ 資料との照合（資料2件）",
            "- 資料にない語: 自動",
            "- 資料にあった確度の語が最終稿にない: 未確認",
            "- 参考: 資料にあって最終稿にない数値: 14日、10件",
            "- " + MATERIALS_DISCLAIMER,
            "",
            line1,
            line2,
        ])

    def test_k21_number_not_in_materials(self):
        m = self.write("m.md", "最大5回まで再試行する。\n")
        f = self.write("f.md", "再試行は最大3回です。\n")
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        self.assertEqual(lines[0], RUN_COMPOSE_FIRST + self.finalize_file())
        status, fields = self.status(lines[1])
        self.assertEqual((fields["mode"], fields["checks"], fields["meaning_risk"]),
                         ("compose", "lint,materials", "1"))
        self.assertIn("- 資料にない数値（後1行目）: 3回", lines)
        self.assertIn("  後: 再試行は最大3回です。", lines)
        path, record = self.record_from(lines)
        self.assertEqual((record["mode"], record["required_checks"]), ("compose", ["lint", "materials"]))
        self.assertIsNone(record["inputs"]["source"])
        self.assertEqual([item["index"] for item in record["inputs"]["materials"]], [1])
        self.assertEqual([item["role"] for item in record["inputs"]["materials"]], ["material"])  # 10.3 C1
        result = self.check_json("run", "--material", m, "--final", f, "--new-run")
        unsupported = [risk for risk in result["materials"]["meaning_risks"] if risk["kind"] == "unsupported"]
        self.assertEqual([(risk["kind"], risk["subkind"]) for risk in unsupported], [("unsupported", "number")])
        # 10.3 C2: unsupported の detail と、照合の items の text（最終稿に書かれた形）
        self.assertEqual(unsupported[0]["detail"], {"text": "3回", "value": "3", "unit": "回"})
        self.assertIn(("number", "3回", "not_in_sources"),
                      [(item["kind"], item["text"], item["classification"]) for item in result["materials"]["items"]])
        self.assertEqual([source["role"] for source in result["materials"]["sources"]], ["material"])
        process = self.check("run", "--material", m, "--final", f, "--new-run", "--fail-on=meaning-risk")
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertTrue(split_lines(process.stdout)[0].startswith(FAIL_ON_HEAD.format("meaning-risk")))

    def test_k21_number_found_in_materials(self):
        m = self.write("m.md", "最大5回まで再試行する。\n")
        f = self.write("f.md", "再試行は最大5回です。\n")
        result = self.check_json("run", "--material", m, "--final", f)
        self.assertEqual([risk for risk in result["materials"]["meaning_risks"] if risk["kind"] == "unsupported"], [])
        self.assertEqual(self.status(result["status_line"])[1]["meaning_risk"], "0")
        process = self.check("run", "--material", m, "--final", f, "--new-run", "--fail-on=meaning-risk")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_k22_correction_based_on_material(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        m = self.write("m.md", "保存期間は30日に変更した。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        result = self.check_json("run", "--source", a, "--material", m, "--final", b)
        # 10.3 B3: run --json の diff.meaning_risks に basis を入れた写しを出す
        risks = result["diff"]["meaning_risks"]
        self.assertTrue(any(risk["kind"] == "number" and risk["subkind"] == "replaced"
                            and risk["basis"] == "material" for risk in risks), risks)
        self.assertEqual(self.status(result["status_line"])[1]["checks"], "lint,diff,materials")
        record = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["required_checks"], ["lint", "diff", "materials"])
        self.assertGreaterEqual(record["materials_summary"]["from_materials"], 1)
        # 10.3 C1: 照合の JSON の sources[].role は "source" と "material"
        self.assertEqual(sorted(source["role"] for source in result["materials"]["sources"]), ["material", "source"])
        # 子の出力そのもの（attempt-<n>.diff.json）は変えない。diff の basis は常に null（2.8）
        child = json.loads((self.state / self.check_entry(record, "diff")["report"]).read_text(encoding="utf-8"))
        numbers = [risk for risk in child["meaning_risks"] if risk["kind"] == "number"]
        self.assertTrue(numbers, child["meaning_risks"])
        self.assertEqual([risk["basis"] for risk in numbers], [None] * len(numbers))
        process, lines = self.check_ok("run", "--source", a, "--material", m, "--final", b, "--new-run")
        self.assertIn("（資料にある値）", process.stdout)
        self.assertIn("- 数値が変わった（1行目）: 3日 → 30日（資料にある値）", lines)
        self.assertIn(MATERIALS_DISCLAIMER, process.stdout)
        # 3.5 の3行目（推敲で資料があるとき）と、3.3 の「資料に基づく補足の候補」の1行
        self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更あり 候補1件（うち意味が変わる恐れ1件）"
                                   "、資料との照合（資料1件）資料にない数値・名前0件")
        self.assertIn("■ 資料との照合（資料1件）", lines)
        self.assertIn("- 資料に基づく補足の候補: 30日", lines)
        self.assertEqual(lines[lines.index("■ 資料との照合（資料1件）") + 1:][:3],
                         ["- 資料に基づく補足の候補: 30日",
                          "- 資料に基づく補足の候補（該当行）: 30日（資料1の1行目「保存期間は30日に変更した。」）",
                          "- " + MATERIALS_DISCLAIMER])
        process = self.check("run", "--source", a, "--material", m, "--final", b, "--new-run",
                             "--fail-on=meaning-risk")
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)

    def test_materials_report_files_in_the_record(self):
        """3.4 の7、3.7: 照合のレポートは正規化した JSON（report_sha256 は sort_keys と区切りを詰めた形のハッシュ）と
        人が読む .txt。target には照らした入力のハッシュを入れる。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        m = self.write("m.md", "保存期間は30日に変更した。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        result = self.check_json("run", "--source", a, "--material", m, "--final", b)
        record = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        entry = self.check_entry(record, "materials")
        self.assertEqual((entry["status"], entry["exit_code"], entry["error"]), ("ran", None, None))
        self.assertEqual(entry["report"], "runs/{}/attempt-1.materials.json".format(record["run_id"]))
        self.assertEqual(entry["text"], "runs/{}/attempt-1.materials.txt".format(record["run_id"]))
        canonical = json.dumps(result["materials"], ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        self.assertEqual(entry["report_sha256"], sha256_bytes(canonical.encode("ascii")))
        self.assertEqual((self.state / entry["report"]).read_bytes(), canonical.encode("ascii"))
        self.assertEqual(entry["text_sha256"], sha256_file(self.state / entry["text"]))
        text = (self.state / entry["text"]).read_text(encoding="utf-8")
        self.assertIn("■ 資料との照合（資料1件）", text)
        self.assertIn(MATERIALS_DISCLAIMER, text)
        self.assertEqual(entry["target"], {"source": sha256_file(a), "materials": [sha256_file(m)],
                                           "final": sha256_file(b)})
        self.assertEqual(entry["summary"]["meaning_risk_count"], 0)
        self.assertEqual(record["materials_summary"], {"from_materials": 1, "not_in_sources": 0, "dropped_certainty": 0})
        self.assertEqual(record["inputs"]["materials"][0]["role"], "material")
        self.assertEqual(record["inputs"]["materials"][0]["index"], 1)
        self.assertEqual(record["record_digest"], record_digest(record))

    def test_k23_certainty_and_words_are_review_lines_only(self):
        m = self.write("m.md", "再試行の回数は未確認です。\n")
        f = self.write("f.md", "再試行の回数は自動で決まります。\n")
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        self.assertIn("■ 資料との照合（資料1件）", lines)
        self.assertIn("- 資料にあった確度の語が最終稿にない: 未確認", lines)
        self.assertIn("- 資料にない語: 自動", lines)
        self.assertIn(MATERIALS_DISCLAIMER, process.stdout)
        self.assertNotIn("■ 意味が変わる恐れ", process.stdout)
        self.assertEqual(self.status(lines[1])[1]["meaning_risk"], "0")
        path, record = self.record_from(lines)
        self.assertGreaterEqual(record["materials_summary"]["dropped_certainty"], 1)
        result = self.check_json("run", "--material", m, "--final", f, "--new-run")
        self.assertEqual(result["materials"]["meaning_risks"], [])
        process = self.check("run", "--material", m, "--final", f, "--new-run", "--fail-on=meaning-risk")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


class TestStdin(CheckCase):
    """K24、K25、3.11 のファイルを作らない対話。"""

    BODY = "<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:final>>>\n保存期間は30日です。\n"

    def test_k24_stdin_run_and_verify_by_text_hash(self):
        process, lines = self.check_ok("run", "--stdin", stdin=self.BODY)
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + self.finalize_stdin())
        status, fields = self.status(lines[1])
        expected_hash = text_sha256("保存期間は30日です。\n".encode("utf-8"))
        self.assertEqual((status, fields["final"], fields["mode"], fields["checks"]),
                         ("executed", "text-sha256:" + expected_hash[:12], "rewrite", "lint,diff"))
        path, record = self.record_from(lines)
        self.assertEqual(record["inputs"]["final"]["via"], "stdin")
        self.assertIsNone(record["inputs"]["final"]["path"])
        self.assertEqual(record["inputs"]["final"]["text_sha256"], expected_hash)
        for body in ("保存期間は30日です。\n", "保存期間は30日です。\n\n\n", "保存期間は30日です。"):
            with self.subTest(body=body):
                _, verify_fields = self.assert_verify(self.check("verify", "--final", "-", stdin=body),
                                                      "executed", code=0)
                self.assertEqual(verify_fields["final"], "text-sha256:" + expected_hash[:12])

    def test_k24_one_character_changed_on_stdin(self):
        """K24 の「1字違えば final_changed」（設計 10.3 A1）。標準入力にはパスがないので、
        --run-id か --source があるときだけ final_changed、どちらもなければ no_record。"""
        process, lines = self.check_ok("run", "--stdin", stdin=self.BODY)
        run_id = self.status(lines[1])[1]["run"]
        changed = "保存期間は300日です。\n"
        lines, fields = self.assert_verify(self.check("verify", "--final", "-", stdin=changed), "no_record")
        self.assertEqual(lines[0], VERIFY_LINE1["no_record"])
        source = self.write("a.md", "保存期間は3日です。\n")  # 標準入力で渡した原文と同じ本文
        recorded = text_sha256("保存期間は30日です。\n".encode("utf-8"))
        for extra in (["--run-id", run_id], ["--source", source]):
            with self.subTest(extra=extra[0]):
                lines, fields = self.assert_verify(self.check("verify", "--final", "-", *extra, stdin=changed),
                                                  "final_changed")
                self.assertEqual(lines[0], VERIFY_LINE1["final_changed"])
                # 10.4 S14: 標準入力の照合は本文のハッシュで行うので、final= と expected= は text-sha256: の形
                self.assertEqual(fields["final"], "text-sha256:" + text_sha256(changed.encode("utf-8"))[:12])
                self.assertEqual(fields["expected"], "text-sha256:" + recorded[:12])

    def test_delimiters_with_bom_crlf_and_materials(self):
        """3.11: 行末の \\r は無視する。先頭の BOM は1つ外す。material は何回でも書ける（新規作成）。区切りの前の空行は読み飛ばす。"""
        body = ("﻿\r\n<<<yomiyasu:material>>>\r\n最大5回まで再試行する。\r\n<<<yomiyasu:material>>>\r\n"
                "ログは14日残す。\r\n<<<yomiyasu:final>>>\r\n再試行は最大3回です。\r\n")
        process = subprocess.run([sys.executable, "-B", str(CHECK), "run", "--stdin", "--json"],
                                 input=body.encode("utf-8"), cwd=str(self.root), env=self.env(),
                                 capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        result = json.loads(process.stdout.decode("ascii"))
        self.assertEqual((result["mode"], result["status"]), ("compose", "executed"))
        self.assertEqual(self.status(result["status_line"])[1]["checks"], "lint,materials")
        record = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual([item["index"] for item in record["inputs"]["materials"]], [1, 2])
        self.assertEqual([item["via"] for item in record["inputs"]["materials"]], ["stdin", "stdin"])
        self.assertEqual(record["inputs"]["materials"][0]["eol"], "crlf")
        self.assertEqual(record["inputs"]["final"]["text_sha256"],
                         text_sha256("再試行は最大3回です。\n".encode("utf-8")))
        self.assertEqual([(risk["kind"], risk["subkind"]) for risk in result["materials"]["meaning_risks"]],
                         [("unsupported", "number")])

    def test_k25_wrong_delimiters_are_usage_errors(self):
        cases = {
            "区切りがない": "保存期間は3日です。\n保存期間は30日です。\n",
            "final が2つ": "<<<yomiyasu:original>>>\nA\n<<<yomiyasu:final>>>\nB\n<<<yomiyasu:final>>>\nC\n",
            "original も material もない": "<<<yomiyasu:final>>>\n保存期間は30日です。\n",
            "original が2つ": "<<<yomiyasu:original>>>\nA\n<<<yomiyasu:original>>>\nA2\n<<<yomiyasu:final>>>\nB\n",
            "final がない": "<<<yomiyasu:original>>>\n保存期間は3日です。\n",
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                process = self.check("run", "--stdin", stdin=body)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                # 3.11: 正しい書き方を標準エラーに出す（final の区切りの行を含む）
                self.assertIn("<<<yomiyasu:final>>>", process.stderr)
                self.assertFalse(self.state.exists())


class TestRecordingFailures(CheckCase):
    """K26〜K29: 記録を書けない、書かない、時間切れ、内部の誤り。"""

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "chmod で書けなくできない環境（root と Windows）")
    def test_k26_unwritable_state_folder(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        system_tmp = self.root / "tmp"
        system_tmp.mkdir()
        self.state.mkdir()
        os.chmod(str(self.state), 0o500)
        self.addCleanup(os.chmod, str(self.state), 0o700)
        before = tree_listing(self.root)
        env = self.env(TMPDIR=str(system_tmp), TEMP=str(system_tmp), TMP=str(system_tmp))
        process, lines = self.check_ok("run", "--source", a, "--final", b, env=env)
        status, fields = self.status(lines[1])
        self.assertEqual(status, "unrecorded")
        self.assertIn(RUN_UNRECORDED_PART, lines[0])
        # 3.5 の表の「記録を書けなかった」の行（{理由} は実装の文）
        match = re.match(r"^検査を実行しましたが、記録を書けませんでした（(.+)）。--state-dir に書ける場所を指定して"
                         r"もう一度実行するか、完了報告の「実行しなかった検査」に「記録（(.+)）」と書いてください。$", lines[0])
        self.assertIsNotNone(match, lines[0])
        self.assertEqual(match.group(1), match.group(2))
        self.assertEqual(lines[self.record_index(lines)], "記録: なし（{}）".format(match.group(1)))
        self.assertEqual((fields["run"], fields["attempt"], fields.get("reason")), ("-", "-", "not_writable"))
        self.assertEqual(lines[-2:], lines[:2])
        self.assertIn("■ 全文差分（変更 1か所。省略していません）", lines)  # 検査は実行した
        result = self.check_json("run", "--source", a, "--final", b, env=env)
        self.assertEqual((result["status"], result["next"]), ("unrecorded", "report_unrecorded"))
        self.assertIsNone(result["record_path"])  # 10.3 L12
        self.assertEqual(list(system_tmp.iterdir()), [], "一時フォルダに逃がさない")
        self.assertEqual(tree_listing(self.root), before)

    def test_k27_no_record_option(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--no-record")
        status, fields = self.status(lines[1])
        self.assertEqual(status, "unrecorded")
        # 10.4 S11: 1行目は表のとおりの文で、{仕上げ} を --no-record の文にする。記録の行（候補がなければ5行目）は「記録: なし（--no-record）」
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_NO_RECORD)
        self.assertEqual(lines[self.record_index(lines)], "記録: なし（--no-record）")
        self.assertEqual(lines[-2:], lines[:2])
        # 記録がないので実行IDと回は「-」。理由は reason= に書く
        # check の固め（勧め59）: verify の状態の名前 no_record と重ならない値にした
        self.assertEqual((fields["run"], fields["attempt"], fields.get("reason")), ("-", "-", "no_record_option"))
        self.assertEqual((fields["mode"], fields["checks"], fields["meaning_risk"]), ("rewrite", "lint,diff", "1"))
        self.assertEqual(fields["final"], "sha256:" + sha256_file(b)[:12])
        result = self.check_json("run", "--source", a, "--final", b, "--no-record")
        self.assertEqual(result["status"], "unrecorded")
        self.assertEqual((result["message"], result["next"]), (RUN_REWRITE_FIRST + FINALIZE_NO_RECORD, "report_unrecorded"))
        self.assertEqual(result["status_line"], lines[1])
        self.assertIsNone(result["record_path"])  # 10.3 L12
        self.assertEqual((result["run_id"], result["attempt"]), (None, None))
        self.assertEqual(result["diff"]["format"], "yomiyasu-diff")
        self.assertFalse(self.state.exists(), "状態フォルダに何も作らない")
        self.assertEqual(tree_listing(self.root), ["a.md", "b.md"])

    def test_no_record_uses_a_temporary_copy_and_removes_it(self):
        """10.4 S12: 記録を書かないときは、消す前提の一時フォルダに写しを置いて子に渡し、終わったら消す。
        標準入力（--stdin）でも、記録を書かずに lint と diff を動かせる。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        system_tmp = self.root / "tmp"
        system_tmp.mkdir()
        env = self.env(TMPDIR=str(system_tmp), TEMP=str(system_tmp), TMP=str(system_tmp))
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--no-record", env=env)
        self.assertEqual(self.status(lines[1])[0], "unrecorded")
        self.assertIn("■ 全文差分（変更 1か所。省略していません）", lines)
        self.assertEqual(list(system_tmp.iterdir()), [], "一時フォルダに写しが残った")
        process, lines = self.check_ok("run", "--stdin", "--no-record", stdin=TestStdin.BODY, env=env)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields["checks"], fields["meaning_risk"]), ("unrecorded", "lint,diff", "1"))
        self.assertEqual(fields["final"], "text-sha256:" + text_sha256("保存期間は30日です。\n".encode("utf-8"))[:12])
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_NO_RECORD)
        self.assertIn("- 数値が変わった（1行目）: 3日 → 30日", lines)
        self.assertEqual(list(system_tmp.iterdir()), [], "一時フォルダに写しが残った")
        self.assertFalse(self.state.exists())

    def test_k28_timeout_is_partial(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", b, "--timeout", "0.001")
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        status, fields = self.status(lines[1])
        self.assertEqual(status, "partial")
        # 10.3 B6: 複数の検査が止まったときは failed=lint(timeout),diff(timeout) のようにカンマでつなぐ
        self.assertRegex(fields.get("failed", ""),
                         r"^(lint\(timeout\)|diff\(timeout\)|lint\(timeout\),diff\(timeout\))$")
        self.assertTrue(lines[0].startswith(RUN_PARTIAL_HEAD), lines[0])
        self.assertIn("時間切れ", lines[0])  # 3.5 の partial の行
        # 10.4 S13: 複数の検査が止まったときは「、」でつなぐ（lint、diffが時間切れ）
        names = [failed.split("(")[0] for failed in fields["failed"].split(",")]
        self.assertEqual(lines[0], "検査の一部を実行できませんでした（{}が時間切れ）。完了報告の「実行しなかった検査」に"
                                   "「{}」と書いてください。".format("、".join(names),
                                                                "、".join(name + "（時間切れ）" for name in names))
                         + PARTIAL_TAIL)
        self.assertEqual(lines[-2:], lines[:2])
        path, record = self.record_from(lines)
        self.assertEqual(record["result"]["status"], "partial")
        self.assertEqual(record["result"]["next"], "report_partial")
        for failed in fields["failed"].split(","):
            self.assertEqual(self.check_entry(record, failed.split("(")[0])["status"], "timeout")

    def test_k29_internal_error_of_diff_is_partial(self):
        scripts = self.skill_copy()
        inject_cli_exit_3(scripts / "yomiyasu_diff.py")
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", b, script=scripts / "yomiyasu_check.py")
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields.get("failed")), ("partial", "diff(error)"))
        self.assertTrue(lines[0].startswith(RUN_PARTIAL_HEAD + "diffが内部エラー）。"), lines[0])  # 3.5 の partial の行
        self.assertEqual(lines[0], RUN_PARTIAL_HEAD + "diffが内部エラー）。完了報告の「実行しなかった検査」に"
                                                      "「diff（内部エラー）」と書いてください。" + PARTIAL_TAIL)
        # 0.4: 終了コード3のときは標準エラーに出す（子の誤りの文を含む）
        self.assertIn("internal error injected by test_v200_check", process.stderr)
        path, record = self.record_from(lines)
        self.assertEqual(record["result"]["status"], "partial")
        self.assertEqual(record["result"]["next"], "report_partial")
        self.assertEqual((self.check_entry(record, "diff")["status"], self.check_entry(record, "diff")["exit_code"]),
                         ("error", 3))
        # 3.4 の4: 子の標準エラーの先頭（2,000字まで）を記録に残す。レポートは作れないので null
        diff_entry = self.check_entry(record, "diff")
        self.assertIn("internal error injected by test_v200_check", diff_entry["stderr"])
        self.assertLessEqual(len(diff_entry["stderr"]), 2000)
        self.assertEqual((diff_entry["report"], diff_entry["report_sha256"], diff_entry["text"], diff_entry["summary"]),
                         (None, None, None, None))
        self.assertEqual(self.check_entry(record, "lint")["status"], "ran")
        self.assertEqual(record["record_digest"], record_digest(record))


    def test_final_changed_during_the_run_is_partial(self):
        """3.4 の6: 検査のあとで最終稿を読み直し、ハッシュが変わっていれば partial（failed=final(changed)）。
        検査は写しに対して動いたので、記録は残す（最終稿のハッシュは読んだときのもの）。"""
        worker = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('_check_under_test', sys.argv[1])\n"
            "check = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(check)\n"
            "original = check._run_checks\n"
            "def wrapped(*args, **kwargs):\n"
            "    result = original(*args, **kwargs)\n"
            "    with open(sys.argv[2], 'ab') as handle:\n"
            "        handle.write('追記した文です。\\n'.encode('utf-8'))\n"
            "    return result\n"
            "check._run_checks = wrapped\n"
            "sys.exit(check.main(sys.argv[3:]))\n"
        )
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        checked = sha256_file(b)
        process = subprocess.run([sys.executable, "-B", "-c", worker, str(CHECK), str(b),
                                  "run", "--source", str(a), "--final", str(b)],
                                 cwd=str(self.root), env=self.env(), capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields["failed"], fields["final"]), ("partial", "final(changed)", "sha256:" + checked[:12]))
        # check の固め（勧め42の3）: 正しい次の行動は run のやり直しなので、その案の文にした
        self.assertEqual(lines[0], "最終稿が検査の途中で変わりました。変え終えてから yomiyasu_check.py run を"
                                   "もう一度実行してください。")
        self.assertEqual(lines[2], "実行した検査: なし（途中で最終稿が変わったため）")
        path, record = self.record_from(lines)
        self.assertEqual((record["result"]["status"], record["result"]["next"]), ("partial", "rerun"))
        self.assertIs(record["result"]["final_unchanged_during_run"], False)
        self.assertEqual(record["inputs"]["final"]["sha256"], checked)
        self.assertEqual([entry["status"] for entry in record["checks"]], ["ran", "ran"])
        self.assertEqual(record["record_digest"], record_digest(record))


class TestPairsAndEncoding(CheckCase):
    """K30、K31。"""

    def test_k30_section_2_2_pairs_fail_on_meaning_risk(self):
        for number, (before, after) in enumerate(PAIRS_22):
            with self.subTest(before=before):
                a = self.write("p{}a.md".format(number), before + "\n")
                b = self.write("p{}b.md".format(number), after + "\n")
                process = self.check("run", "--source", a, "--final", b, "--fail-on=meaning-risk")
                self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                lines = split_lines(process.stdout)
                self.assertTrue(lines[0].startswith(FAIL_ON_HEAD.format("meaning-risk")), lines[0])
                self.assertEqual(self.status(lines[1])[0], "executed")

    def test_k31_cp932_streams(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        env = self.env(PYTHONIOENCODING="cp932:surrogateescape")
        env.pop("PYTHONUTF8", None)

        def run(*args):
            return subprocess.run([sys.executable, "-B", str(CHECK)] + [str(x) for x in args],
                                  cwd=str(self.root), env=env, capture_output=True, timeout=30)

        for args, token in ((["run", "--source", a, "--final", b], "yomiyasu-check: executed via=run"),
                            (["verify", "--final", b], "yomiyasu-check: executed via=verify")):
            with self.subTest(args=args[0]):
                process = run(*args)
                self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
                text = process.stdout.decode("utf-8")  # UTF-8 として読める
                self.assertIn(token, text)
                self.assertIn("この記録は" if args[0] == "run" else "完了報告", text)
        for args in (["run", "--source", a, "--final", b, "--new-run", "--json"], ["verify", "--final", b, "--json"]):
            with self.subTest(args=args[0] + " --json"):
                process = run(*args)
                self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
                self.assertTrue(process.stdout.isascii(), "--json の出力は ASCII だけにする")
                self.assertEqual(json.loads(process.stdout.decode("ascii"))["status"], "executed")


class TestReadOnlyAndWrites(CheckCase):
    """K32、K33: verify は読むだけで速い。run は状態フォルダの外に書かない。"""

    def test_k32_verify_does_not_load_lint_or_diff_and_is_fast(self):
        """K32: --replay なしの verify は1秒未満で、-X importtime の標準エラーに lint と diff の名前が出ない。
        ただし -X importtime は import 文の経路だけを出し、check が使う importlib.import_module() と
        spec_from_file_location() の読み込みは出さないので、後半の2行は見張りとして弱い（反証レビュー spec F7）。
        読み込みの見張りは、監査イベント exec で見る test_k32_verify_does_not_load_lint_or_diff_under_any_name が担う。"""
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        started = time.perf_counter()
        process = self.check("verify", "--final", b)
        elapsed = time.perf_counter() - started
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertLess(elapsed, 1.0)
        process = self.check("verify", "--final", b, flags=("-B", "-X", "importtime"))
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertNotIn("yomiyasu_lint", process.stderr)
        self.assertNotIn("yomiyasu_diff", process.stderr)

    def test_k32_verify_does_not_load_lint_or_diff_under_any_name(self):
        """3.13 の2: --replay なしの verify は lint と diff を読み込まない。名前を変えて読み込んでも見つける。
        写したスキルで動かす（__pycache__ がなく、モジュールのコードは必ずソースから実行される）。"""
        scripts = self.skill_copy()
        script = scripts / "yomiyasu_check.py"

        def loaded(*args):
            process = subprocess.run([sys.executable, "-B", "-c", LOAD_WORKER, str(scripts)] + [str(x) for x in args],
                                     cwd=str(self.root), env=self.env(), capture_output=True, encoding="utf-8",
                                     timeout=30)
            found = re.findall(r"^LOADED-SCRIPTS \[(.*)\]$", process.stderr, flags=re.M)
            self.assertEqual(len(found), 1, process.stderr)
            return process, [name for name in found[0].split(",") if name]

        # 見張りが働くこと: lint を別の名前で読み込む合成のスクリプトで、読み込みを見つける
        probe = self.root / "probe" / "load_renamed.py"
        probe.parent.mkdir()
        probe.write_text(LOAD_UNDER_OTHER_NAME, encoding="utf-8")
        process, names = loaded(probe, scripts / "yomiyasu_lint.py")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(names, ["yomiyasu_lint.py"])
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b, script=script)
        process, names = loaded(script, "verify", "--final", b)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(self.status(split_lines(process.stdout)[1])[0], "executed")
        self.assertEqual(names, [], "--replay なしの verify が lint か diff を読み込んだ")

    def test_k32_verify_reads_only(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        before = tree_digest(self.state)
        for extra in ([], ["--replay"]):
            with self.subTest(extra=extra):
                self.assert_verify(self.check("verify", "--final", b, *extra), "executed", code=0)
                self.assertEqual(tree_digest(self.state), before)

    def test_k33_run_writes_only_inside_the_state_folder(self):
        a = self.write("docs/a.md", "保存期間は3日です。\n")
        b = self.write("docs/b.md", "保存期間は30日です。\n")
        drafts = {a: a.read_bytes(), b: b.read_bytes()}
        before = tree_listing(self.root, skip=self.state)
        process = subprocess.run(
            [sys.executable, "-B", "-c", AUDIT_WORKER, str(self.state), str(CHECK),
             "run", "--source", str(a), "--final", str(b)],
            cwd=str(self.root), env=self.env(), capture_output=True, encoding="utf-8", timeout=30,
        )
        self.assertNotIn("BLOCKED-WRITES", process.stderr)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(self.status(split_lines(process.stdout)[1])[0], "executed")
        for path, data in drafts.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(tree_listing(self.root, skip=self.state), before)

    def test_k33_no_pycache_in_the_skill_scripts(self):
        """3.4: check は冒頭で sys.dont_write_bytecode を真にする。確かめるため、この試験だけ -B を付けずに、
        一時フォルダに写したスキルで動かす（リポジトリの scripts には書かない）。.pyc の置き場所
        （PYTHONPYCACHEPREFIX）も一時フォルダの中に向け、そこにも4本の .pyc ができないことを見る。"""
        scripts = self.skill_copy()
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        prefix = self.root / "pyc"
        env = self.env(PYTHONPYCACHEPREFIX=str(prefix))
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        script = scripts / "yomiyasu_check.py"
        process, lines = self.check_ok("run", "--source", a, "--final", b, script=script, env=env, flags=())
        self.assert_verify(self.check("verify", "--final", b, "--replay", script=script, env=env, flags=()),
                           "executed", code=0)
        self.assertFalse((scripts / "__pycache__").exists())
        stems = tuple(name[:-len(".py")] + "." for name in TOOL_NAMES)
        written = [path.name for path in prefix.rglob("*.pyc") if path.name.startswith(stems)]
        self.assertEqual(written, [], "スキルのスクリプトの .pyc ができた")


class TestParallelAndFiles(CheckCase):
    """K17、K36、K37、K38。"""

    def test_k17_parallel_runs(self):
        finals = []
        processes = []
        outputs = []
        try:
            for number in range(4):
                a = self.write("a{}.md".format(number), "設定{}の保存期間は3日です。\n".format(number))
                b = self.write("b{}.md".format(number), "設定{}の保存期間は30日です。\n".format(number))
                finals.append(b)
                for _ in range(2):  # 同じファイルを2回（10.3 B1: 4つのファイルをそれぞれ2回、8プロセス）
                    processes.append(subprocess.Popen(
                        [sys.executable, "-B", str(CHECK), "run", "--source", str(a), "--final", str(b)],
                        cwd=str(self.root), env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8"))
            deadline = time.monotonic() + 60
            for process in processes:
                stdout, stderr = process.communicate(timeout=max(1.0, deadline - time.monotonic()))
                outputs.append((process.returncode, stdout + stderr))
        finally:
            for process in processes:  # 失敗しても子プロセスを残さない（一時フォルダの片付けと競合させない）
                if process.poll() is None:
                    process.kill()
                process.wait()
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
        for code, output in outputs:
            self.assertEqual(code, 0, output)
        records = [path for path in self.state.rglob("*.json") if re.match(r"^attempt-\d+\.json$", path.name)]
        self.assertEqual(len(records), 8)
        keys = set()
        for path in records:
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(path.parent.name, record["run_id"])
            self.assertEqual(path.name, "attempt-{}.json".format(record["attempt"]))
            keys.add((record["run_id"], record["attempt"]))
        self.assertEqual(len(keys), 8)
        for b in finals:
            with self.subTest(final=b.name):
                self.assert_verify(self.check("verify", "--final", b), "executed", code=0)

    @unittest.skipIf(shutil.which("git") is None, "git がない")
    def test_k36_git_status_does_not_show_the_state_folder(self):
        """K36。YOMIYASU_STATE_DIR で指定した状態フォルダでも、作るときに .gitignore を書く（10.3 B2）。"""
        repo = self.root / "repo"
        repo.mkdir()
        empty = self.root / "empty.gitconfig"
        empty.write_bytes(b"")
        # git のフックの中などで動かしたとき、GIT_DIR などが本物のリポジトリを指さないように外す
        git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        git_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty))
        subprocess.run(["git", "init", "-q", str(repo)], env=git_env, capture_output=True, timeout=30, check=True)
        a = self.write("repo/a.md", "保存期間は3日です。\n")
        b = self.write("repo/b.md", "保存期間は30日です。\n")
        self.state = repo / ".yomiyasu"
        self.check_ok("run", "--source", a, "--final", b, cwd=repo)
        self.assertTrue((self.state / "runs").is_dir())
        for args in (["status", "--porcelain"], ["status", "--porcelain", "--untracked-files=all"]):
            with self.subTest(args=args):
                status = subprocess.run(["git"] + args, cwd=str(repo), env=git_env, capture_output=True,
                                        encoding="utf-8", timeout=30)
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertNotIn(".yomiyasu", status.stdout)

    def test_k37_file_names_are_portable(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        m = self.write("m.md", "保存期間は30日に変更した。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--material", m, "--final", b)
        self.check_ok("run", "--material", m, "--final", b)
        self.check_ok("run", "--stdin", stdin=TestStdin.BODY)
        names = tree_listing(self.state)
        self.assertTrue(any(name.startswith("index/by-text/") for name in names), names)
        for name in names:
            for part in name.split("/"):
                self.assertRegex(part, FILE_NAME)

    def test_k38_os_replace_is_retried_after_permission_errors(self):
        """K38: os.replace の最初の2回を PermissionError にしても記録が書ける（プロセスの中で動かす）。
        書き直しは OS によらず行う（設計 10.3 B4）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        real_replace = os.replace
        calls = []

        def flaky_replace(src, dst, *args, **kwargs):
            calls.append(os.fspath(dst))
            if len(calls) <= 2:
                raise PermissionError(13, "試験で起こした共有違反", os.fspath(dst))
            return real_replace(src, dst, *args, **kwargs)

        names = ("yomiyasu_check", "yomiyasu_lint", "yomiyasu_diff", "markdown_visibility")
        saved_modules = {name: sys.modules.get(name) for name in names}
        saved_module_names = set(sys.modules)
        saved_flag = sys.dont_write_bytecode
        saved_path = list(sys.path)
        saved_cwd = os.getcwd()
        saved_umask = os.umask(0o022)  # 今の値を取る（すぐ戻す）
        os.umask(saved_umask)
        scripts_dir = os.path.realpath(str(SCRIPTS))
        out = io.StringIO()
        err = io.StringIO()
        code = None
        os.chdir(str(self.root))
        try:
            sys.path.insert(0, str(SCRIPTS))
            # 試験を -B なしで動かしても、リポジトリの scripts に .pyc を書かない（__pycache__ は K33 で見る）
            sys.dont_write_bytecode = True
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, {"YOMIYASU_STATE_DIR": str(self.state)}))
                stack.enter_context(mock.patch.object(
                    sys, "argv", [str(CHECK), "run", "--source", str(a), "--final", str(b)]))
                stack.enter_context(mock.patch.object(sys, "stdout", out))
                stack.enter_context(mock.patch.object(sys, "stderr", err))
                stack.enter_context(mock.patch.object(os, "replace", side_effect=flaky_replace))
                if hasattr(pathlib, "_normal_accessor"):
                    # Python 3.10 以前の pathlib は os.replace を読み込みのときに束ねるので、Path.replace() も差し替える
                    stack.enter_context(mock.patch.object(pathlib._normal_accessor, "replace",
                                                          side_effect=flaky_replace))
                try:
                    runpy.run_path(str(CHECK), run_name="__main__")
                    code = 0
                except SystemExit as stop:
                    code = stop.code or 0
        finally:
            os.chdir(saved_cwd)
            os.umask(saved_umask)
            sys.path[:] = saved_path
            sys.dont_write_bytecode = saved_flag
            for name in set(sys.modules) - saved_module_names:  # check が読み込んだスキルのモジュールを外す
                module_file = getattr(sys.modules.get(name), "__file__", None)
                if module_file and os.path.dirname(os.path.realpath(module_file)) == scripts_dir:
                    sys.modules.pop(name, None)
            for name, module in saved_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        lines = split_lines(out.getvalue())
        status, fields = self.status(lines[1])
        self.assertEqual(status, "executed")
        self.assertTrue((self.state / "runs" / fields["run"] / "attempt-1.json").is_file())
        self.assertGreaterEqual(len(calls), 3, "PermissionError のあとに書き直していない")


class TestStateFolderPlace(CheckCase):
    """10.4 S16: 3.6 の3（作業ディレクトリから上へたどり、.git がある最初のフォルダの .yomiyasu/）と4（作業ディレクトリの
    .yomiyasu/）。一時フォルダの中に .git を作り、その下のフォルダを作業ディレクトリにして、YOMIYASU_STATE_DIR なしで run する。
    本物のリポジトリに書かないよう、一時フォルダの外への書き込みを止めて見張る（AUDIT_WORKER）。"""

    def run_without_state_env(self, allowed, cwd, *args):
        env = self.env()
        env.pop("YOMIYASU_STATE_DIR", None)
        return subprocess.run(
            [sys.executable, "-B", "-c", AUDIT_WORKER, str(allowed), str(CHECK)] + [str(a) for a in args],
            cwd=str(cwd), env=env, capture_output=True, encoding="utf-8", timeout=30)

    def test_git_folder_or_file_above_the_working_directory(self):
        for kind in ("dir", "file"):  # worktree では .git がファイル
            with self.subTest(git=kind):
                top = self.root / kind
                deep = top / "docs" / "deep"
                deep.mkdir(parents=True)
                if kind == "dir":
                    (top / ".git").mkdir()
                else:
                    (top / ".git").write_text("gitdir: /nonexistent/worktree\n", encoding="utf-8")
                a = self.write(kind + "/docs/a.md", "保存期間は3日です。\n")
                b = self.write(kind + "/docs/b.md", "保存期間は30日です。\n")
                process = self.run_without_state_env(top, deep, "run", "--source", a, "--final", b)
                self.assertNotIn("BLOCKED-WRITES", process.stderr)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                lines = split_lines(process.stdout)
                status, fields = self.status(lines[1])
                self.assertEqual(status, "executed")
                expected = top / ".yomiyasu" / "runs" / fields["run"] / "attempt-1.json"
                self.assertEqual(lines[self.record_index(lines)], "記録: " + str(expected))
                self.assertTrue(expected.is_file())
                self.assertEqual((top / ".yomiyasu" / ".gitignore").read_text(encoding="utf-8").rstrip("\n").split("\n"),
                                 GITIGNORE_LINES)
                self.assertFalse((deep / ".yomiyasu").exists())
                self.assertFalse((top / "docs" / ".yomiyasu").exists())

    def test_working_directory_without_git(self):
        if any((parent / ".git").exists() for parent in self.root.parents):
            self.skipTest("一時フォルダの上に .git がある（3.6 の4を試せない）")
        work = self.root / "work"
        work.mkdir()
        a = self.write("work/a.md", "保存期間は3日です。\n")
        b = self.write("work/b.md", "保存期間は30日です。\n")
        process = self.run_without_state_env(self.root, work, "run", "--source", a, "--final", b)
        self.assertNotIn("BLOCKED-WRITES", process.stderr)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        run_id = self.status(lines[1])[1]["run"]
        self.assertEqual(lines[self.record_index(lines)], "記録: " + str(work / ".yomiyasu" / "runs" / run_id / "attempt-1.json"))


class TestCommonPromises(CheckCase):
    """0.4、10.5、10.6 B1、10.7: 3本に共通の約束を check にも当てる。"""

    def pair(self):
        return self.write("a.md", "保存期間は3日です。\n"), self.write("b.md", "保存期間は30日です。\n")

    def test_argparse_errors_end_with_a_japanese_hint(self):
        """10.5 M2: 使い方の行と英語の行のあとに、日本語の案内を1行足す。終了コード2で、何も書かない。"""
        a, b = self.pair()
        for args in (["run", "--nope"], ["--source", a, "--final", b, "--nope"],
                     ["run", "--source", a, "--final", b, "--timeout"], ["run", "--source", a]):
            with self.subTest(args=[str(x) for x in args]):
                process = self.check(*args)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                lines = process.stderr.rstrip("\n").split("\n")
                self.assertTrue(lines[0].startswith("使い方: yomiyasu_check.py run"), process.stderr)
                self.assertIn("yomiyasu_check.py run: error: ", lines[-2])
                self.assertEqual(lines[-1], "引数の誤りです。yomiyasu_check.py run -h で使い方を確かめてください。")
                self.assertFalse(self.state.exists())

    def test_abbreviations_are_not_accepted(self):
        """10.7: argparse の省略形を受けない（allow_abbrev=False）。"""
        a, b = self.pair()
        for args in (["run", "--sour", a, "--final", b], ["run", "--source", a, "--fin", b],
                     ["run", "--source", a, "--final", b, "--js"], ["run", "--source", a, "--final", b, "--no-rec"],
                     ["run", "--source", a, "--final", b, "--fail", "warn"]):
            with self.subTest(args=[str(x) for x in args]):
                process = self.check(*args)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertIn("引数の誤りです。", process.stderr)
                self.assertFalse(self.state.exists())

    def test_fail_on_values_ignore_case_and_underscore(self):
        """10.5 M5: --fail-on の値は、大文字と小文字、「_」と「-」を区別しない。知らない値は2。"""
        a, b = self.pair()
        for value in ("MEANING_RISK", "Meaning_Risk", " meaning-risk ", "meaning-risk,WARN"):
            with self.subTest(value=value):
                process = self.check("run", "--source", a, "--final", b, "--new-run", "--fail-on=" + value)
                self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertTrue(split_lines(process.stdout)[0].startswith(FAIL_ON_HEAD.format("meaning-risk")),
                                process.stdout)
        for value, shown in (("nope", "nope"), ("", "（空）"), (" , ", "（空）")):
            with self.subTest(value=value):
                state = self.root / ("state-" + str(len(value)))
                process = self.check("run", "--source", a, "--final", b, "--fail-on=" + value,
                                     env=self.env(YOMIYASU_STATE_DIR=str(state)))
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr.rstrip("\n"),
                                 "--fail-on に使えない値です: {}。check で使えるのは meaning-risk、warn、error です。".format(shown))
                self.assertFalse(state.exists())

    def test_fail_on_meaning_risk_counts_only_the_designed_kinds(self):
        """10.6 B1: --fail-on=meaning-risk が数えるのは、数値、否定、入れ替え、文の種類と、資料にない数値だけ。
        変えない箇所（protected）と資料にない名前（unsupported/name）は、意味が変わる恐れに出すが数えない。"""
        a = self.write("code-a.md", "設定は `retry=3` です。\n")
        b = self.write("code-b.md", "設定は `retry=5` です。\n")
        process = self.check("run", "--source", a, "--final", b, "--fail-on=meaning-risk")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        self.assertEqual(self.status(lines[1])[1]["meaning_risk"], "1")
        self.assertIn("■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）", lines)
        self.assertFalse(lines[0].startswith("--fail-on="), lines[0])
        result = self.check_json("run", "--source", a, "--final", b, "--new-run")
        self.assertEqual((result["meaning_risk_count"], result["fail_on_meaning_risk_count"]), (1, 0))
        m = self.write("m.md", "再試行は最大5回です。\n")
        f = self.write("f.md", "再試行はPostgreSQLで最大5回です。\n")
        process = self.check("run", "--material", m, "--final", f, "--fail-on=meaning-risk")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        self.assertEqual(self.status(lines[1])[1]["meaning_risk"], "1")
        self.assertIn("- 資料にない名前（後1行目）: PostgreSQL", lines)

    def test_closed_output_pipe_exits_3_without_traceback(self):
        """10.5 M4: 読む側が先に閉じたときは、トレースバックを出さずに終了コード3。"""
        a, b = self.pair()
        process = subprocess.Popen([sys.executable, "-B", str(CHECK), "run", "--source", str(a), "--final", str(b)],
                                   cwd=str(self.root), env=self.env(), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdout.close()
        _, err = process.communicate(timeout=30)
        message = err.decode("utf-8")
        self.assertEqual(process.returncode, 3, message)
        self.assertIn("yomiyasu_check.py: 出力先が閉じられたため、結果を最後まで書けませんでした。", message)
        self.assertNotIn("Traceback", message)

    def test_help_has_the_description_and_exit_code_table(self):
        """3.2 のヘルプの説明と、0.4 の終了コードの表（最後に置く）。"""
        description = ("最終稿に lint、原文と最終稿に diff（新規作成では資料との照合）をまとめて実行し、記録を残します。"
                       "結果は『検査を実行した』で、意味の保持や読みやすさの合格ではありません。")
        env = self.env(COLUMNS="2000", NO_COLOR="1")
        env.pop("FORCE_COLOR", None)
        env.pop("PYTHON_COLORS", None)
        for args in (["-h"], ["run", "-h"]):
            with self.subTest(args=args):
                process = self.check(*args, env=env)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertIn(description, process.stdout)
                tail = process.stdout.rstrip("\n").split("\n")[-5:]
                self.assertEqual(tail[0], "終了コード:", process.stdout)
                for code, line in zip("0123", tail[1:]):
                    self.assertRegex(line, r"^  {}  \S".format(code))
        self.assertFalse(self.state.exists())

    def test_missing_neighbours_are_internal_errors(self):
        """0.4、10.7: 隣の markdown_visibility.py、yomiyasu_lint.py、yomiyasu_diff.py がない、または壊れているときは、
        内部エラー（終了コード3）。状態フォルダには何も書かない。"""
        a, b = self.pair()
        cases = (("visibility-missing", ("yomiyasu_lint.py", "yomiyasu_diff.py"), None, "markdown_visibility.py"),
                 ("visibility-broken", ("yomiyasu_lint.py", "yomiyasu_diff.py"), ("markdown_visibility.py", "def x(:\n"),
                  "markdown_visibility.py"),
                 ("lint-missing", ("markdown_visibility.py", "yomiyasu_diff.py"), None, "yomiyasu_lint"),
                 ("diff-broken", ("markdown_visibility.py", "yomiyasu_lint.py"), ("yomiyasu_diff.py", "def x(:\n"),
                  "yomiyasu_diff"))
        for name, copies, broken, mentioned in cases:
            with self.subTest(case=name):
                folder = self.root / name
                folder.mkdir()
                shutil.copyfile(str(CHECK), str(folder / "yomiyasu_check.py"))
                for copy in copies:
                    shutil.copyfile(str(SCRIPTS / copy), str(folder / copy))
                if broken:
                    (folder / broken[0]).write_text(broken[1], encoding="utf-8")
                process = self.check("run", "--source", a, "--final", b, script=folder / "yomiyasu_check.py")
                self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                first = process.stderr.split("\n")[0]
                self.assertTrue(first.startswith("yomiyasu_check.py: 内部エラー: "), process.stderr)
                self.assertIn(mentioned, process.stderr)
                self.assertFalse(self.state.exists())

    def test_dash_reads_one_input_from_stdin(self):
        """0.4: ファイル名の代わりに - を書くと標準入力を読む。1つのコマンドで1か所だけ。"""
        a, b = self.pair()
        process, lines = self.check_ok("run", "--source", a, "--final", "-", stdin="保存期間は30日です。\n")
        status, fields = self.status(lines[1])
        self.assertEqual(fields["final"], "text-sha256:" + text_sha256("保存期間は30日です。\n".encode("utf-8"))[:12])
        path, record = self.record_from(lines)
        self.assertEqual((record["inputs"]["final"]["via"], record["inputs"]["final"]["path"]), ("stdin", None))
        self.assertEqual(record["inputs"]["source"]["via"], "file")
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + self.finalize_stdin())
        for args in (["run", "--source", "-", "--final", "-"], ["run", "--stdin", "--final", b],
                     ["run", "--stdin", "--source", a], ["run", "--stdin", "--material", a]):
            with self.subTest(args=[str(x) for x in args]):
                process = self.check(*args, stdin=TestStdin.BODY, env=self.env(YOMIYASU_STATE_DIR=str(self.root / "s2")))
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertFalse((self.root / "s2").exists())

    def test_input_errors_write_nothing(self):
        """10.3 C4 と 0.4: 入力の誤り（開けない、UTF-8 でない、時間の値、実行IDの指定）は、何も書かずに2。"""
        a, b = self.pair()
        missing = self.root / "missing.md"
        cp932 = self.root / "cp932.md"
        cp932.write_bytes("保存期間は30日です。\n".encode("cp932"))
        cases = (
            (["--source", missing, "--final", b], "Error opening file {}: ファイルを開けません（".format(missing)),
            (["--source", a, "--final", cp932], "Error opening file {}: UTF-8 として読めません".format(cp932)),
            (["--source", a, "--final", b, "--timeout", "0"], "--timeout"),
            (["--source", a, "--final", b, "--timeout", "-1"], "--timeout"),
            (["--source", a, "--final", b, "--timeout", "abc"], "--timeout"),
            (["--source", a, "--final", b, "--timeout", "nan"], "--timeout"),
            (["--source", a, "--final", b, "--run-id", "x", "--new-run"], "--new-run"),
            (["--source", a, "--final", b, "--stance", ""], "--stance に使えない値です: （空）。"),
            (["--source", a, "--final", b, "--state-dir", ""], "--state-dir"),
            (["--source", "", "--final", b], "Error opening file : ファイルを開けません（"),
            (["--source", a, "--final", b, "--run-id", ""], "--run-id に使えない値です: （空）。"),
        )
        for args, message in cases:
            with self.subTest(args=[str(x) for x in args]):
                process = self.check("run", *args)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn(message, process.stderr)
                self.assertFalse(self.state.exists())


class TestReviewFixes(CheckCase):
    """check の段の反証レビューで見つかった食い違いの試験。
    直す前に落ちることを確かめてから、実装を直した。文はすべて合成。"""

    def pair(self):
        return self.write("a.md", "保存期間は3日です。\n"), self.write("b.md", "保存期間は30日です。\n")

    def copy_scripts(self, name):
        """4本と SKILL.md を一時フォルダの name/scripts に写す（skill_copy と同じ。複数の写しを作れる）。"""
        scripts = self.root / name / "scripts"
        scripts.mkdir(parents=True)
        for tool in TOOL_NAMES:
            shutil.copyfile(str(SCRIPTS / tool), str(scripts / tool))
        shutil.copyfile(str(SKILL_MD), str(scripts.parent / "SKILL.md"))
        return scripts

    def run_in_process(self, argv, patches=()):
        """check をこのプロセスの中で動かす（K38 と同じ片付け）。patches は (対象, 名前, 置き換え) の並び。
        (終了コード, 標準出力, 標準エラー) を返す。"""
        names = ("yomiyasu_check", "yomiyasu_lint", "yomiyasu_diff", "markdown_visibility")
        saved_modules = {name: sys.modules.get(name) for name in names}
        saved_module_names = set(sys.modules)
        saved_flag = sys.dont_write_bytecode
        saved_path = list(sys.path)
        saved_cwd = os.getcwd()
        saved_umask = os.umask(0o022)  # 今の値を取る（すぐ戻す）
        os.umask(saved_umask)
        scripts_dir = os.path.realpath(str(SCRIPTS))
        out = io.StringIO()
        err = io.StringIO()
        code = None
        os.chdir(str(self.root))
        try:
            sys.path.insert(0, str(SCRIPTS))
            sys.dont_write_bytecode = True
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, {"YOMIYASU_STATE_DIR": str(self.state)}))
                stack.enter_context(mock.patch.object(sys, "argv", [str(CHECK)] + [str(x) for x in argv]))
                stack.enter_context(mock.patch.object(sys, "stdout", out))
                stack.enter_context(mock.patch.object(sys, "stderr", err))
                for target, name, value in patches:
                    stack.enter_context(mock.patch.object(target, name, value))
                try:
                    runpy.run_path(str(CHECK), run_name="__main__")
                    code = 0
                except SystemExit as stop:
                    code = stop.code or 0
        finally:
            os.chdir(saved_cwd)
            os.umask(saved_umask)
            sys.path[:] = saved_path
            sys.dont_write_bytecode = saved_flag
            for name in set(sys.modules) - saved_module_names:
                module_file = getattr(sys.modules.get(name), "__file__", None)
                if module_file and os.path.dirname(os.path.realpath(module_file)) == scripts_dir:
                    sys.modules.pop(name, None)
            for name, module in saved_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        return code, out.getvalue(), err.getvalue()

    # --- spec F1、robust R6、R2: 時間の上限と、--replay で子を動かせないとき ---

    def test_large_timeout_means_no_limit(self):
        """--timeout に子の待ち方の上限を超える大きな値を渡しても、内部エラーにせず、上限なしとして最後まで動かす
        （0.4: 終了コード3は内部の誤りか時間切れだけ。spec F1、robust R6）。"""
        a, b = self.pair()
        for value in ("2200000", "1e308"):
            with self.subTest(timeout=value):
                process, lines = self.check_ok("run", "--source", a, "--final", b, "--timeout", value)
                self.assertEqual(self.status(lines[1])[0], "executed")
        _, fields = self.assert_verify(self.check("verify", "--final", b, "--replay", "--timeout", "9999999"),
                                       "executed", code=0)
        self.assertEqual(fields["replay"], "ok")

    def test_replay_that_cannot_start_a_child_is_an_internal_error(self):
        """3.9 の10 と 3.10: --replay で子プロセスを起動できないのは記録の食い違いではない。not_reproducible にせず、
        verify の内部の誤り（終了コード3、標準エラーに理由）にする（spec F1 の後半、robust R2）。"""
        worker = (
            "import importlib.util, subprocess, sys\n"
            "spec = importlib.util.spec_from_file_location('_check_under_test', sys.argv[1])\n"
            "check = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(check)\n"
            "def refuse(*args, **kwargs):\n"
            "    raise BlockingIOError(35, 'Resource temporarily unavailable (test)')\n"
            "subprocess.Popen = refuse\n"
            "sys.exit(check.main(sys.argv[2:]))\n"
        )
        a, b = self.pair()
        self.check_ok("run", "--source", a, "--final", b)
        process = subprocess.run([sys.executable, "-B", "-c", worker, str(CHECK), "verify", "--final", str(b), "--replay"],
                                 cwd=str(self.root), env=self.env(), capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertNotIn("not_reproducible", process.stdout + process.stderr)
        self.assertIn("yomiyasu_check.py: 内部エラー: ", process.stderr)
        self.assertIn("BlockingIOError", process.stderr)
        # 子を起動できる環境では、同じ記録が作り直せる
        self.assert_verify(self.check("verify", "--final", b, "--replay"), "executed", code=0)

    # --- spec F3、F8: 推敲で資料があるときの3行目と照合 ---

    def test_rewrite_counts_numbers_not_in_sources_in_the_third_line(self):
        """3.5 の3行目「資料にない数値・名前{q}件」は、推敲でも資料にない数値を数える（spec F3）。
        推敲の資料にない数値は diff の候補の basis "none" で出し、照合の meaning_risks には入れない（3.3。spec F8）。
        推敲では「参考: 資料にあって最終稿にない数値」の行を出さない（3.3 の表）。"""
        a = self.write("r_a.md", "再試行は最大3回です。\n")
        m = self.write("r_m.md", "再試行の上限は資料で確かめる。ログは14日残す。\n")
        b = self.write("r_b.md", "再試行は最大5回です。\n")
        process, lines = self.check_ok("run", "--source", a, "--material", m, "--final", b)
        self.assertTrue(lines[2].endswith("、資料との照合（資料1件）資料にない数値・名前1件"), lines[2])
        self.assertFalse(any(line.startswith("- 参考:") for line in lines), lines)
        self.assertIn("- 数値が変わった（1行目）: 3回 → 5回", lines)
        result = self.check_json("run", "--source", a, "--material", m, "--final", b, "--new-run")
        numbers = [risk for risk in result["diff"]["meaning_risks"] if risk["kind"] == "number"]
        self.assertEqual([risk["basis"] for risk in numbers], ["none"])
        self.assertEqual([risk for risk in result["materials"]["meaning_risks"]
                          if (risk["kind"], risk["subkind"]) == ("unsupported", "number")], [])
        self.assertIn(("number", "5回", "not_in_sources"),
                      [(item["kind"], item["text"], item["classification"]) for item in result["materials"]["items"]])

    # --- spec F5: --version ---

    def test_version_does_not_load_lint_or_diff(self):
        """3.4: lint と diff の import は run と verify --replay の中だけ。--version は読み込まず、
        diff の形式の版（MATERIALS_FORMAT_VERSION）はファイルの行から読む。diff が壊れていても版の行を出す（spec F5）。"""
        scripts = self.copy_scripts("skill-version")
        script = scripts / "yomiyasu_check.py"
        expected = "yomiyasu_check.py 2.1.1 (record format 1, result format 1, materials format 1)\n"
        process = subprocess.run([sys.executable, "-B", "-c", LOAD_WORKER, str(scripts), str(script), "--version"],
                                 cwd=str(self.root), env=self.env(), capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, expected)
        self.assertEqual(re.findall(r"^LOADED-SCRIPTS \[(.*)\]$", process.stderr, flags=re.M), [""], process.stderr)
        with open(str(scripts / "yomiyasu_diff.py"), "a", encoding="utf-8") as handle:
            handle.write("\ndef broken_by_test(:\n")
        process = self.check("--version", script=script)
        self.assertEqual((process.returncode, process.stdout, process.stderr), (0, expected, ""))

    # --- spec F6、robust R12: モードに合わない検査の項目 ---

    def test_compose_record_with_a_diff_check_is_invalid(self):
        """3.9 の4: 新規作成の記録に diff の項目（ran）がある記録は、モードに合わない形なので invalid_record。
        --replay でも内部エラーにしない（spec F6、robust R12）。"""
        m = self.write("cm.md", "最大5回まで再試行する。\n")
        f = self.write("cf.md", "再試行は最大5回です。\n")
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        path, record = self.record_from(lines)
        lint = self.check_entry(record, "lint")
        crafted = dict(lint, name="diff", report=lint["report"].replace(".lint.", ".diff."),
                       text=lint["text"].replace(".lint.", ".diff."))
        shutil.copyfile(str(self.state / lint["report"]), str(self.state / crafted["report"]))
        shutil.copyfile(str(self.state / lint["text"]), str(self.state / crafted["text"]))
        record["checks"].append(crafted)
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        for extra in ([], ["--replay"]):
            with self.subTest(extra=extra):
                verify_lines, _ = self.assert_verify(self.check("verify", "--final", f, *extra), "invalid_record")
                self.assertEqual(verify_lines[0], VERIFY_LINE1["invalid_record"])

    # --- spec F8: 試験のなかった決まり ---

    def test_existing_state_folder_is_left_as_it_is(self):
        """10.3 B2: YOMIYASU_STATE_DIR で決めたすでにある状態フォルダには .gitignore と state.json を足さない（中身を書き換え
        ない）。既定の規則（.yomiyasu/）で決めたフォルダの扱いは test_v200_state_gitignore.py で見る。"""
        self.state.mkdir()
        note = self.state / "note.txt"
        note.write_bytes("利用者のメモです。\n".encode("utf-8"))
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        self.assertTrue((self.state / "runs").is_dir())
        self.assertFalse((self.state / ".gitignore").exists())
        self.assertFalse((self.state / "state.json").exists())
        self.assertEqual(note.read_bytes(), "利用者のメモです。\n".encode("utf-8"))

    def test_k2_reports_with_candidates_stance_and_special_text(self):
        """K2、10.3 B5: lint の候補がある組、--stance、BOM・CRLF・コード・URL を含む組でも、記録の .json と .txt が
        CLI の出力と同じバイト列（spec F8）。"""
        cases = (
            ("lint", "テストを書くことが大切です。\n".encode("utf-8"),
             "重要なのは、テストを書くことです。\n".encode("utf-8"), []),
            ("stance", "保存期間は3日です。\n".encode("utf-8"), "保存期間は30日です。\n".encode("utf-8"),
             ["--stance", "説明"]),
            ("special", "﻿設定は `retry=3` です。\r\n詳しくは https://example.com/a を見る。\r\n".encode("utf-8"),
             "﻿設定は `retry=5` です。\r\n詳しくは https://example.com/b を見ます。\r\n".encode("utf-8"), []),
        )
        cli_env = self.env(PYTHONIOENCODING="utf-8")
        for name, before, after, extra in cases:
            with self.subTest(case=name):
                a = self.root / (name + "-a.md")
                b = self.root / (name + "-b.md")
                a.write_bytes(before)
                b.write_bytes(after)
                process, lines = self.check_ok("run", "--source", a, "--final", b, *extra)
                path, record = self.record_from(lines)
                if name == "lint":
                    self.assertGreater(self.check_entry(record, "lint")["summary"]["candidate_count"], 0)
                commands = {"lint": ([LINT, "--json", b], [LINT, b]),
                            "diff": ([DIFF, "--json"] + extra + [a, b], [DIFF] + extra + [a, b])}
                for check, (json_args, text_args) in commands.items():
                    entry = self.check_entry(record, check)
                    for args, key in ((json_args, "report"), (text_args, "text")):
                        cli = subprocess.run([sys.executable, "-B"] + [str(x) for x in args], cwd=str(self.root),
                                             capture_output=True, env=cli_env, timeout=30)
                        self.assertEqual(cli.returncode, 0, cli.stderr)
                        self.assertEqual((self.state / entry[key]).read_bytes(), cli.stdout, (check, key))

    @unittest.skipIf(shutil.which("git") is None, "git がない")
    def test_k36_default_place_in_a_real_git_repository(self):
        """K36 と 3.6 の3: git init した一時フォルダの下位で、YOMIYASU_STATE_DIR なしで run すると、記録は git の最上位の
        .yomiyasu/ にでき、git status に出ない（spec F8。一時フォルダの外への書き込みは止めて見張る）。"""
        repo = self.root / "repo"
        docs = repo / "docs"
        docs.mkdir(parents=True)
        empty = self.root / "empty.gitconfig"
        empty.write_bytes(b"")
        git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        git_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty))
        subprocess.run(["git", "init", "-q", str(repo)], env=git_env, capture_output=True, timeout=30, check=True)
        a = self.write("repo/docs/a.md", "保存期間は3日です。\n")
        b = self.write("repo/docs/b.md", "保存期間は30日です。\n")
        env = self.env()
        env.pop("YOMIYASU_STATE_DIR", None)
        process = subprocess.run([sys.executable, "-B", "-c", AUDIT_WORKER, str(repo), str(CHECK),
                                  "run", "--source", str(a), "--final", str(b)],
                                 cwd=str(docs), env=env, capture_output=True, encoding="utf-8", timeout=30)
        self.assertNotIn("BLOCKED-WRITES", process.stderr)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        run_id = self.status(lines[1])[1]["run"]
        self.assertEqual(lines[self.record_index(lines)], "記録: " + str(repo / ".yomiyasu" / "runs" / run_id / "attempt-1.json"))
        self.assert_verify(self.check("verify", "--final", b, cwd=docs, env=env), "executed", code=0)
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=str(repo),
                                env=git_env, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(sorted(status.stdout.split("\n")[:-1]), ["?? docs/a.md", "?? docs/b.md"])

    # --- robust R1、agent 12: 外から止められたとき ---

    @unittest.skipIf(os.name != "posix", "SIGTERM で止める試験は POSIX だけ")
    def test_terminated_check_stops_its_children_and_removes_the_copies(self):
        """3.13 の7、10.4 S12: check が SIGTERM で止められたら、動いている子（diff）も止め、--no-record の一時フォルダの
        写しも消してから終わる（robust R1、agent 12）。"""
        scripts = self.copy_scripts("skill-slow")
        pid_file = self.root / "diff.pid"
        inject_cli_code(scripts / "yomiyasu_diff.py", (
            "import os as _t_os, time as _t_time",
            "with open({!r}, 'w') as _t_handle:".format(str(pid_file) + ".tmp"),
            "    _t_handle.write(str(_t_os.getpid()))",
            "_t_os.replace({!r}, {!r})".format(str(pid_file) + ".tmp", str(pid_file)),
            "_t_time.sleep(30)",
        ))
        a, b = self.pair()
        system_tmp = self.root / "tmp"
        system_tmp.mkdir()
        env = self.env(TMPDIR=str(system_tmp), TEMP=str(system_tmp), TMP=str(system_tmp))
        process = subprocess.Popen([sys.executable, "-B", str(scripts / "yomiyasu_check.py"), "run", "--source", str(a),
                                    "--final", str(b), "--no-record"],
                                   cwd=str(self.root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child = None
        try:
            deadline = time.monotonic() + 20
            while child is None:
                if pid_file.exists():
                    child = int(pid_file.read_text(encoding="utf-8"))
                    break
                self.assertIsNone(process.poll(), "check が先に終わった")
                self.assertLess(time.monotonic(), deadline, "diff の子が始まらない")
                time.sleep(0.05)
            process.send_signal(signal.SIGTERM)
            _, err = process.communicate(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        try:
            message = err.decode("utf-8", "replace")
            self.assertEqual(process.returncode, 128 + signal.SIGTERM, message)
            self.assertIn("yomiyasu_check.py: 止められました（SIGTERM）。", message)
            self.assertNotIn("Traceback", message)
            stopped = False
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    stopped = True
                    break
                time.sleep(0.05)
            self.assertTrue(stopped, "diff の子が動き続けている")
            self.assertEqual(list(system_tmp.iterdir()), [], "一時フォルダに写しが残った")
        finally:
            try:
                os.kill(child, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, TypeError):
                pass

    # --- robust R3: 状態フォルダの作りかけ ---

    def test_state_folder_is_not_left_half_made(self):
        """3.6、K36: 状態フォルダを作る途中で .gitignore を書けなかったら、作りかけのフォルダを残さない（次の run が
        「すでにあるフォルダ」として .gitignore なしで書き続けないように。robust R3）。"""
        a, b = self.pair()
        real_link, real_open = os.link, os.open

        # .gitignore は一時ファイルから os.link で置く（リンクを作れなければ O_EXCL の os.open で作る）ので、両方を断る
        def refuse_gitignore(src, dst, *args, **kwargs):
            if os.path.basename(os.fspath(dst)) == ".gitignore":
                raise PermissionError(13, "試験で起こした共有違反", os.fspath(dst))
            return real_link(src, dst, *args, **kwargs)

        def refuse_gitignore_open(path, flags, *args, **kwargs):
            if os.path.basename(os.fspath(path)) == ".gitignore":
                raise PermissionError(13, "試験で起こした共有違反", os.fspath(path))
            return real_open(path, flags, *args, **kwargs)

        code, out, err = self.run_in_process(["run", "--source", a, "--final", b],
                                             patches=[(os, "link", refuse_gitignore), (os, "open", refuse_gitignore_open)])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.status(split_lines(out)[1])[0], "unrecorded")
        self.assertFalse(self.state.exists(), "作りかけの状態フォルダが残った")
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        self.assertEqual(self.status(lines[1])[0], "executed")
        self.assertEqual((self.state / ".gitignore").read_text(encoding="utf-8").rstrip("\n").split("\n"),
                         GITIGNORE_LINES)

    # --- robust R5: 子の JSON の形 ---

    def test_child_json_without_the_needed_keys_is_a_partial_run(self):
        """3.4 の4: 子が形式の名前だけ合った JSON を返しても check は落ちない。その検査を error にして partial
        （終了コード3）にし、記録を残す（robust R5）。"""
        cases = (("diff", '{"format": "yomiyasu-diff", "format_version": 2}'),
                 ("lint", '{"format": "yomiyasu-lint", "format_version": 2, "candidate_count": "x"}'))
        a, b = self.pair()
        for name, output in cases:
            with self.subTest(check=name):
                scripts = self.copy_scripts("skill-" + name)
                inject_cli_code(scripts / "yomiyasu_{}.py".format(name),
                                ("print({!r})".format(output), "raise SystemExit(0)"))
                process = self.check("run", "--source", a, "--final", b, "--new-run",
                                     script=scripts / "yomiyasu_check.py")
                self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
                self.assertNotIn("Traceback", process.stderr)
                lines = split_lines(process.stdout)
                status, fields = self.status(lines[1])
                self.assertEqual((status, fields.get("failed")), ("partial", name + "(error)"))
                path, record = self.record_from(lines)
                self.assertEqual(self.check_entry(record, name)["status"], "error")
                self.assertEqual(record["record_digest"], record_digest(record))

    # --- robust R7: 保存の失敗で残った索引 ---

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "chmod で書けなくできない環境（root と Windows）")
    def test_failed_save_leaves_no_index_entries(self):
        """3.12、3.9 の3: 記録の保存が途中で失敗したら、その回の索引（by-final、by-text）とレポートを残さない。
        残すと、次の回が同じ番号を使い直したときに別の最終稿の記録を指す（robust R7）。"""
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        run_id = self.status(lines[1])[1]["run"]
        folders = list((self.state / "index" / "by-path").iterdir())
        self.assertEqual(len(folders), 1)
        os.chmod(str(folders[0]), 0o500)
        self.addCleanup(os.chmod, str(folders[0]), 0o700)
        b.write_bytes("保存期間は31日です。\n".encode("utf-8"))
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        self.assertEqual(self.status(lines[1])[0], "unrecorded")
        for kind, key in (("by-final", sha256_file(b)), ("by-text", text_sha256(b.read_bytes()))):
            folder = self.state / "index" / kind / key
            self.assertEqual(sorted(path.name for path in folder.iterdir()) if folder.exists() else [], [], kind)
        self.assertEqual(sorted(path.name for path in (self.state / "runs" / run_id).iterdir()
                                if path.name.startswith("attempt-2")), [])

    # --- robust R8: パイプの --final ---

    @unittest.skipIf(os.name != "posix" or not os.path.exists("/dev/stdin"), "/dev/stdin がない")
    def test_final_given_as_a_pipe_path_is_an_input_error(self):
        """3.4 の6: 最終稿は検査のあとで読み直すので、読み直せないパイプのパス（/dev/stdin、<(…)）は2にして、
        --final - を案内する（変わっていない最終稿を「途中で変わった」と報告しない。robust R8）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        process = self.check("run", "--source", a, "--final", "/dev/stdin", stdin="保存期間は30日です。\n")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertIn("Error opening file /dev/stdin: ", process.stderr)
        self.assertIn("--final -", process.stderr)
        self.assertFalse(self.state.exists())

    # --- robust R10: YOMIYASU_STATE_DIR の空白と、展開されなかった ${…} ---

    def test_blank_or_unexpanded_state_dir_variable_is_ignored(self):
        """3.6 の2 と 3.2 の ${ の扱い: YOMIYASU_STATE_DIR が空白だけか、展開されなかった ${…} を含むときは、
        ないものとして 3.6 の3と4の規則に進む（作業フォルダに変な名前のフォルダを作らない。robust R10）。"""
        top = self.root / "top"
        docs = top / "docs"
        docs.mkdir(parents=True)
        (top / ".git").mkdir()
        a = self.write("top/docs/a.md", "保存期間は3日です。\n")
        b = self.write("top/docs/b.md", "保存期間は30日です。\n")
        for value in ("${CLAUDE_PROJECT_DIR}/.yomiyasu", " "):
            with self.subTest(value=value):
                env = self.env(YOMIYASU_STATE_DIR=value)
                process = subprocess.run([sys.executable, "-B", "-c", AUDIT_WORKER, str(top), str(CHECK),
                                          "run", "--source", str(a), "--final", str(b), "--new-run"],
                                         cwd=str(docs), env=env, capture_output=True, encoding="utf-8", timeout=30)
                self.assertNotIn("BLOCKED-WRITES", process.stderr)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                lines = split_lines(process.stdout)
                self.assertTrue(lines[self.record_index(lines)].startswith("記録: " + str(top / ".yomiyasu" / "runs") + os.sep), lines[self.record_index(lines)])
                self.assertEqual(sorted(path.name for path in docs.iterdir()), ["a.md", "b.md"])

    # --- robust R11: 作業ディレクトリがない ---

    @unittest.skipIf(os.name != "posix" or shutil.which("sh") is None, "sh がない")
    def test_missing_working_directory_is_an_input_error(self):
        """3.4 の1: 作業ディレクトリが消えているときは、トレースバックで落ちずに、理由の分かる文で2にする（robust R11）。"""
        a, b = self.pair()
        state = self.root / "state"
        for args, keep_state_env in ((["run", "--source", a, "--final", b, "--state-dir", state], True),
                                     (["verify", "--final", b], False)):
            with self.subTest(command=args[0]):
                gone = self.root / ("gone-" + args[0])
                gone.mkdir()
                env = self.env()
                if not keep_state_env:
                    env.pop("YOMIYASU_STATE_DIR", None)
                process = subprocess.run(["sh", "-c", 'cd "$1" && rmdir "$1" && shift && exec "$@"', "sh", str(gone),
                                          sys.executable, "-B", str(CHECK)] + [str(x) for x in args],
                                         cwd=str(self.root), env=env, capture_output=True, encoding="utf-8", timeout=30)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn("作業ディレクトリ", process.stderr)
                self.assertNotIn("Traceback", process.stderr)
        self.assertFalse(state.exists())

    # --- agent 4: partial の状態の行と3行目 ---

    def test_partial_run_does_not_report_risks_of_checks_that_did_not_run(self):
        """3.10 と 3.5: diff を実行できなかった partial では、状態の行に meaning_risk= を出さない（0件と読めるため）。
        3行目は完了報告の「実行した検査」に対応するので、実行できた検査だけを並べる（agent 4）。"""
        scripts = self.copy_scripts("skill-broken-diff")
        inject_cli_exit_3(scripts / "yomiyasu_diff.py")
        script = scripts / "yomiyasu_check.py"
        a, b = self.pair()
        process = self.check("run", "--source", a, "--final", b, script=script)
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields.get("failed")), ("partial", "diff(error)"))
        self.assertNotIn("meaning_risk", fields)
        self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件")
        self.assertEqual(lines[-2:], lines[:2])
        result = self.check_json("run", "--source", a, "--final", b, "--new-run", code=3, script=script)
        self.assertIsNone(result["meaning_risk_count"])
        self.assertIsNone(result["fail_on_meaning_risk_count"])
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b, script=script), "incomplete")
        self.assertNotIn("meaning_risk", fields)
        self.assertEqual(verify_lines[0], VERIFY_PARTIAL_LINE.format("diff は内部エラー", "diff（内部エラー）"))
        # 時間切れで両方が止まったときは「実行した検査: なし」
        process = self.check("run", "--source", a, "--final", b, "--new-run", "--timeout", "0.001")
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        status, fields = self.status(lines[1])
        self.assertNotIn("meaning_risk", fields)
        if fields["failed"] == "lint(timeout),diff(timeout)":
            self.assertEqual(lines[2], "実行した検査: なし")
        else:
            self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件")

    # --- agent 15: 人が読む文の検査名 ---

    def test_materials_is_called_by_its_report_name_in_human_lines(self):
        """5.2: 完了報告の検査名は lint、diff、資料との照合、最終稿の照合。run の partial の1行目と verify の1行目は
        materials を「資料との照合」と書く（状態の行の checks= と failed= は名前のまま。agent 15）。"""
        worker = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('_check_under_test', sys.argv[1])\n"
            "check = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(check)\n"
            "def boom(*args, **kwargs):\n"
            "    raise RuntimeError('ground failed for test')\n"
            "check._diff_module().ground = boom\n"
            "sys.exit(check.main(sys.argv[2:]))\n"
        )
        m = self.write("m.md", "最大5回まで再試行する。\n")
        f = self.write("f.md", "再試行は最大5回です。\n")
        process = subprocess.run([sys.executable, "-B", "-c", worker, str(CHECK), "run", "--material", str(m),
                                  "--final", str(f)],
                                 cwd=str(self.root), env=self.env(), capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields["checks"], fields.get("failed")), ("partial", "lint,materials", "materials(error)"))
        self.assertEqual(lines[0], RUN_PARTIAL_HEAD + "資料との照合が内部エラー）。完了報告の「実行しなかった検査」に"
                                                      "「資料との照合（内部エラー）」と書いてください。" + PARTIAL_TAIL)
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", f), "incomplete")
        self.assertEqual(verify_lines[0], VERIFY_PARTIAL_LINE.format("資料との照合 は内部エラー", "資料との照合（内部エラー）"))
        self.assertEqual(fields["checks"], "lint,materials")


class TestRecordsOnlyFromCheck(unittest.TestCase):
    """（v1.1.2 でも通る後戻り防止）記録は yomiyasu_check.py だけが作る（設計 3.1）。"""

    def test_lint_and_diff_cli_do_not_create_a_state_folder(self):
        """（v1.1.2 でも通る後戻り防止）lint と diff の CLI を動かしても、状態フォルダもほかのファイルもできない。"""
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-check-")
        self.addCleanup(folder.cleanup)
        root = Path(os.path.realpath(folder.name))
        a = root / "a.md"
        b = root / "b.md"
        a.write_bytes("保存期間は3日です。\n".encode("utf-8"))
        b.write_bytes("保存期間は30日です。\n".encode("utf-8"))
        env = dict(os.environ, YOMIYASU_STATE_DIR=str(root / ".yomiyasu"))
        for args in ([LINT, b], [LINT, "--json", b], [DIFF, a, b], [DIFF, "--json", a, b]):
            process = subprocess.run([sys.executable, "-B"] + [str(x) for x in args], cwd=str(root), env=env,
                                     capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(sorted(path.name for path in root.iterdir()), ["a.md", "b.md"])


if __name__ == "__main__":
    unittest.main()
