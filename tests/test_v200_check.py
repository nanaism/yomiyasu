#!/usr/bin/env python3
"""v2.0.0: lint と diff をまとめて実行し、記録を残して照らす yomiyasu_check.py（run と verify）の試験。

期待値は DESIGN-interfaces.md の 3章と 6.5 の表（K1〜K38。start の K19 と、フックの登録の K34 は
2番目の作業で作らないので除く）と、試験づくりで決めたこと（10.3）から取った。文はすべて合成。

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
import subprocess
import sys
import tempfile
import time
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
FIELD_ORDER = ("via", "run", "attempt", "final", "source", "expected", "mode", "checks",
               "meaning_risk", "replay", "failed", "reason")
RUN_ID = r"\d{8}T\d{6}Z-[0-9a-f]{8}"
# 6.5 K1 の2行目
K1_STATUS = re.compile(r"^yomiyasu-check: executed via=run run=" + RUN_ID
                       + r" attempt=1 final=sha256:[0-9a-f]{12} mode=rewrite checks=lint,diff meaning_risk=\d+$")

# 3.5 run の出力の1行目（{仕上げ} の前まで）と、決まった行
FINALIZE_FILE = "提出の直前に、本文を変えずに verify を1回実行してください。"
FINALIZE_STDIN = "本文はこのままで返答し、完了報告にこの出力の2行目を写してください。"
RUN_REWRITE_FIRST = ("検査を実行しました（1回目）。下の候補を原文と資料に照らして確かめてください。"
                     "直すのは1回までです。直したら同じコマンドをもう一度実行し、直さないなら")
RUN_REWRITE_FIRST_NO_CANDIDATES = ("検査を実行しました（1回目）。規則に当たる候補はありません。"
                                   "全文差分で意図しない変更がないかを確かめ、直すなら1回まで、直さないなら")
RUN_COMPOSE_FIRST = ("検査を実行しました（新規作成、1回目）。資料にない数値と名前を確かめ、"
                     "主張・条件・担当・未確認の事項を資料と読み比べてください。直すのは1回までです。"
                     "直したら同じコマンドをもう一度実行し、直さないなら")
RUN_AFTER_FIX = "検査を実行しました（修正後の検査）。本文はもう変えず、残った候補は完了報告に書いてください。"
RUN_SAME_FINAL = "検査を実行しました（前回と同じ最終稿）。"
RUN_NO_CHANGE = "検査を実行しました。原文から変更はありません。"
RUN_OVER_LIMIT = ("検査を実行しました（修正{n}回目のあと）。修正は1回までの決まりを超えています（このコマンドは止めません）。"
                  "利用者から新しい依頼がない限り本文はもう変えず、残った候補は完了報告に書いてください。")
RUN_PARTIAL_HEAD = "検査の一部を実行できませんでした（"
RUN_UNRECORDED_PART = "記録を書けませんでした"
RUN_DISCLAIMER = "この記録は検査を実行したことを示すだけで、意味が保たれたことや読みやすさの合格を示すものではありません。"
FAIL_ON_HEAD = "--fail-on={} の条件に当たりました（終了コード1）。"
MATERIALS_DISCLAIMER = ("照らしたのは数値、名前、語、確度の語だけです。主張、条件、担当が資料どおりかは判定していません。"
                        "資料と読み比べてください。")
SAME_FILE_ERROR = ("原文と最終稿が同じファイルです。書き直す前の原文を別のファイルに残し、最終稿を別のファイルに保存してから"
                   "実行してください。原文を上書きしてしまったときは、git などで元の版を取り出して --source に渡してください。")
GITIGNORE_LINES = ["# yomiyasu の検査記録。git に入れない。", "*"]

# 3.9 verify の出力の1行目
VERIFY_LINE1 = {
    "executed": "この最終稿に必要な検査（{checks}）を実行した記録があり、最終稿のハッシュが記録と合いました。"
                "合格の判定ではありません。完了報告にこの出力の2行目を写してください。",
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
LINE_ENDINGS_NOTE = "改行コードだけが違います（git の autocrlf やエディタの設定で変わることがあります）"

RECORD_KEYS = ("format", "format_version", "run_id", "attempt", "fix_count", "previous", "created_at", "mode",
               "cwd", "host", "skill", "tools", "python", "inputs", "options", "required_checks", "checks",
               "materials_summary", "result", "record_digest")
INPUT_KEYS = ("role", "index", "path", "via", "bytes", "sha256", "text_sha256", "bom", "eol", "snapshot")
CHECK_KEYS = ("name", "status", "exit_code", "duration_ms", "target", "report", "report_sha256", "text",
              "text_sha256", "summary", "stderr", "error")
RESULT_KEYS = ("status", "token", "next", "fail_on_hit", "meaning_risk_count", "final_unchanged_during_run",
               "not_judged")
RUN_JSON_KEYS = ("format", "format_version", "tool_version", "command", "status", "status_line", "message",
                 "next", "run_id", "attempt", "fix_count", "mode", "record_path", "fail_on_hit", "lint", "diff",
                 "materials")
VERIFY_JSON_KEYS = ("format", "format_version", "tool_version", "command", "status", "status_line", "message",
                    "run_id", "attempt", "record_path", "final", "record_final_sha256", "mode", "required_checks",
                    "checks", "meaning_risk_count", "replay", "problems")
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


def inject_cli_exit_3(path):
    """スクリプトとして動かしたときだけ終了コード3で終わるようにする（import の振る舞いは変えない）。

    差し込む場所は最上位の `if __name__ == "__main__":` の直前（定義と __version__ はすべてそのまま）。
    その形がなければ、docstring、`from __future__`、`__version__` の代入のあと。"""
    source = path.read_text(encoding="utf-8")
    body = ast.parse(source).body
    lines = source.splitlines(True)
    guards = [node for node in body if is_main_guard(node)]
    if guards:
        at = guards[-1].lineno - 1
    else:
        index = 0
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            index = 1
        while index < len(body) and (assigns_version(body[index]) or (
                isinstance(body[index], ast.ImportFrom) and body[index].module == "__future__")):
            index += 1
        at = body[index].lineno - 1 if index < len(body) else len(lines)
    snippet = ("import sys as _yomiyasu_test_sys\n"
               "if __name__ == \"__main__\":\n"
               "    _yomiyasu_test_sys.stderr.write(\"internal error injected by test_v200_check\\n\")\n"
               "    _yomiyasu_test_sys.exit(3)\n")
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

    def record_from(self, lines):
        self.assertTrue(lines[4].startswith("記録: "), lines[:5])
        path = Path(lines[4][len("記録: "):])
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
        self.assertEqual(len(lines), 3, lines)
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
        line1 = RUN_REWRITE_FIRST + FINALIZE_FILE
        line2 = ("yomiyasu-check: executed via=run run={} attempt=1 final=sha256:{} mode=rewrite "
                 "checks=lint,diff meaning_risk=1").format(fields["run"], sha256_file(b)[:12])
        record = self.state / "runs" / fields["run"] / "attempt-1.json"
        expected = [
            line1,
            line2,
            "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更あり 候補1件（うち意味が変わる恐れ1件）",
            RUN_DISCLAIMER,
            "記録: " + str(record),
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
        self.assertEqual(set(record["tools"]), set(TOOL_NAMES))
        for name in TOOL_NAMES:
            self.assertEqual(record["tools"][name], {"version": "2.0.0", "sha256": sha256_file(SCRIPTS / name)})
        self.assertEqual(record["python"], {"version": platform.python_version(),
                                            "implementation": platform.python_implementation()})
        self.assertEqual(set(record["inputs"]), {"source", "materials", "final"})
        self.assertEqual(record["inputs"]["materials"], [])
        for role, file in (("source", a), ("final", b)):
            item = record["inputs"][role]
            for key in INPUT_KEYS:
                self.assertIn(key, item)
            self.assertEqual(item["role"], role)  # DESIGN-interfaces 10.3 C1
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
        self.assertEqual(record["options"], {"stance": None, "fail_on": [], "timeout": 90})
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
                         ("yomiyasu-check-result", 1, "2.0.0", "run"))
        self.assertEqual(result["status"], "executed")
        self.assertRegex(result["status_line"], K1_STATUS)
        self.assertEqual(result["message"], RUN_REWRITE_FIRST + FINALIZE_FILE)
        self.assertEqual(result["next"], "review")
        self.assertEqual((result["attempt"], result["fix_count"], result["mode"]), (1, 0, "rewrite"))
        self.assertIs(result["fail_on_hit"], False)
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
        バイト列（DESIGN-interfaces 10.3 B5。末尾の改行を含む）。"""
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
                                        common + "skipped", lines[4]])
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
                         ("yomiyasu-check-result", 1, "2.0.0", "verify"))
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
        # 状態フォルダがないときは 3.9 の1で止まり、2（ハッシュの計算）に進まない実装もありうる。
        # 3.10 の文法は final=- を許すので、どちらも受ける（questions-check.md の D1）
        self.assertIn(fields["final"], ("-", "sha256:" + sha256_file(b)[:12]))
        self.assertEqual(lines[2], "記録: なし")
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
        self.assertEqual(again[0], RUN_AFTER_FIX + FINALIZE_FILE)
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
        line1 = RUN_AFTER_FIX + FINALIZE_FILE
        line2 = ("yomiyasu-check: executed via=run run={} attempt=2 final=sha256:{} mode=rewrite "
                 "checks=lint,diff meaning_risk=0").format(run_id, sha256_file(b)[:12])
        self.assertEqual(again, [
            line1,
            line2,
            "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更あり 候補1件（うち意味が変わる恐れ0件）",
            RUN_DISCLAIMER,
            "記録: " + str(record),
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
        self.assertEqual(result["message"], RUN_OVER_LIMIT.format(n=2) + FINALIZE_FILE)
        self.assertEqual(result["next"], "finalize_over_limit")
        self.assertEqual((result["attempt"], result["fix_count"]), (3, 2))

    def test_k10_same_final_again_is_not_a_fix(self):
        a, b, lines = self.run_pair("保存期間は3日です。\n", "保存期間は30日です。\n")
        run_id = self.status(lines[1])[1]["run"]
        process, again = self.check_ok("run", "--source", a, "--final", b)
        self.assertIn("前回と同じ最終稿", again[0])
        self.assertEqual(again[0], RUN_SAME_FINAL + FINALIZE_FILE)
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
        crafted = (json.dumps(report, ensure_ascii=True, indent=1) + "\n").encode("ascii")
        (self.state / entry["report"]).write_bytes(crafted)
        entry["report_sha256"] = sha256_bytes(crafted)
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
        self.assertEqual(lines[0], RUN_NO_CHANGE + FINALIZE_FILE)
        self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更なし 候補0件（うち意味が変わる恐れ0件）")
        result = self.check_json("run", "--source", a, "--final", b)  # 表は上から当てはめる（変更なしが先）
        self.assertEqual((result["message"], result["next"]), (RUN_NO_CHANGE + FINALIZE_FILE, "finalize"))

    def test_first_rewrite_without_candidates(self):
        """3.5 の表の「推敲の1回目、候補なし」。読点を1つ足しただけの組（6.1 と同じ）。"""
        a, b, lines = self.run_pair("会議は3時に始まります。\n", "会議は、3時に始まります。\n")
        self.assertEqual(lines[0], RUN_REWRITE_FIRST_NO_CANDIDATES + FINALIZE_FILE)
        self.assertEqual(self.status(lines[1])[1]["meaning_risk"], "0")
        self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更あり 候補0件（うち意味が変わる恐れ0件）")
        self.assertEqual(self.record_from(lines)[1]["result"]["next"], "review")


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
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_FILE)
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
        self.assertEqual(lines[4], "記録: " + str(other / "runs" / run_id / "attempt-1.json"))
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
        line1 = RUN_COMPOSE_FIRST + FINALIZE_FILE
        line2 = ("yomiyasu-check: executed via=run run={} attempt=1 final=sha256:{} mode=compose "
                 "checks=lint,materials meaning_risk=1").format(run_id, sha256_file(f)[:12])
        self.assertEqual(lines, [
            line1,
            line2,
            "実行した検査: lint（最終稿）候補0件、資料との照合（資料2件→最終稿）資料にない数値・名前1件",
            RUN_DISCLAIMER,
            "記録: " + str(self.state / "runs" / run_id / "attempt-1.json"),
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
        self.assertEqual(lines[0], RUN_COMPOSE_FIRST + FINALIZE_FILE)
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
        self.assertIn(MATERIALS_DISCLAIMER, process.stdout)
        process = self.check("run", "--source", a, "--material", m, "--final", b, "--new-run",
                             "--fail-on=meaning-risk")
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)

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
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_STDIN)
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
        """K24 の「1字違えば final_changed」（DESIGN-interfaces 10.3 A1）。標準入力にはパスがないので、
        --run-id か --source があるときだけ final_changed、どちらもなければ no_record。"""
        process, lines = self.check_ok("run", "--stdin", stdin=self.BODY)
        run_id = self.status(lines[1])[1]["run"]
        changed = "保存期間は300日です。\n"
        lines, fields = self.assert_verify(self.check("verify", "--final", "-", stdin=changed), "no_record")
        self.assertEqual(lines[0], VERIFY_LINE1["no_record"])
        source = self.write("a.md", "保存期間は3日です。\n")  # 標準入力で渡した原文と同じ本文
        for extra in (["--run-id", run_id], ["--source", source]):
            with self.subTest(extra=extra[0]):
                lines, fields = self.assert_verify(self.check("verify", "--final", "-", *extra, stdin=changed),
                                                  "final_changed")
                self.assertEqual(lines[0], VERIFY_LINE1["final_changed"])

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
        self.assertTrue(lines[4].startswith("記録: なし"), lines[4])
        result = self.check_json("run", "--source", a, "--final", b, env=env)
        self.assertEqual((result["status"], result["next"]), ("unrecorded", "report_unrecorded"))
        self.assertIsNone(result["record_path"])  # 10.3 L12
        self.assertEqual(list(system_tmp.iterdir()), [], "一時フォルダに逃がさない")
        self.assertEqual(tree_listing(self.root), before)

    def test_k27_no_record_option(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--no-record")
        self.assertEqual(self.status(lines[1])[0], "unrecorded")
        self.assertTrue(lines[4].startswith("記録: なし"), lines[4])
        result = self.check_json("run", "--source", a, "--final", b, "--no-record")
        self.assertEqual(result["status"], "unrecorded")
        self.assertIsNone(result["record_path"])  # 10.3 L12
        self.assertFalse(self.state.exists(), "状態フォルダに何も作らない")
        self.assertEqual(tree_listing(self.root), ["a.md", "b.md"])

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
        path, record = self.record_from(lines)
        self.assertEqual(record["result"]["status"], "partial")
        self.assertEqual(record["result"]["next"], "report_partial")
        self.assertEqual((self.check_entry(record, "diff")["status"], self.check_entry(record, "diff")["exit_code"]),
                         ("error", 3))
        self.assertEqual(self.check_entry(record, "lint")["status"], "ran")


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
        書き直しは OS によらず行う（DESIGN-interfaces 10.3 B4）。"""
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


class TestRecordsOnlyFromCheck(unittest.TestCase):
    """（v1.1.2 でも通る後戻り防止）記録は yomiyasu_check.py だけが作る（DESIGN-interfaces 3.1）。"""

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
