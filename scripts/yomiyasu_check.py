#!/usr/bin/env python3
"""
yomiyasu_check.py - 最終稿に lint、原文と最終稿に diff（新規作成では資料との照合）をまとめて実行し、記録を残す。

標準ライブラリだけで動く。モデルは呼ばない。外へ通信しない。
  run     lint と diff を子プロセスで動かし（時間の上限つき）、資料があればプロセスの中で照らし、
          入力の写し、レポート、記録を状態フォルダ（既定は git の最上位の .yomiyasu/）に書く。
  verify  最終稿のハッシュを記録と照らす（読むだけで、何も書かない）。
返す状態は「検査を実行した」で、意味の保持や読みやすさの合格ではない。
同じ権限で原稿と記録の両方を書き換えられる環境では、記録は実行漏れを見つけるためのもので、
改ざんの防止や人の承認の証明にはならない。
"""
__version__ = "2.0.0"

import sys

# lint と diff を読み込む前に、.pyc を書かないようにする（スキルのフォルダに __pycache__ を作らない。
# DESIGN-interfaces.md 3.4）。子プロセスは -B で動かす。
sys.dont_write_bytecode = True

import os  # noqa: E402
import re  # noqa: E402
import json  # noqa: E402
import stat  # noqa: E402
import time  # noqa: E402
import signal  # noqa: E402
import hashlib  # noqa: E402
import argparse  # noqa: E402
import datetime  # noqa: E402
import platform  # noqa: E402
import tempfile  # noqa: E402
import importlib  # noqa: E402
import importlib.util  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
import subprocess  # noqa: E402
from collections import OrderedDict  # noqa: E402
try:
    try:
        if __package__:
            from .markdown_visibility import decode_source
        else:
            from markdown_visibility import decode_source
    except SyntaxError as error:
        # 隣の markdown_visibility.py が壊れている。ほかの読めないときと同じく ImportError にする（スクリプトでは終了コード3）。
        raise ImportError(
            "{} を読めません（SyntaxError: {}）。yomiyasu_check.py と同じ版の markdown_visibility.py を置いてください。".format(
                error.filename or "markdown_visibility.py", error.msg),
            name=(__package__ + ".markdown_visibility") if __package__ else "markdown_visibility") from error
    except ImportError as error:
        # spec_from_file_location や runpy で直接読まれると、このファイルのフォルダが sys.path にないことがある。
        # 別の版の markdown_visibility がすでに読まれていて、decode_source がないこともある。
        # どちらのときも、このファイルの隣にある markdown_visibility.py を読む（lint、diff と同じ形）。
        expected = (__package__ + ".markdown_visibility") if __package__ else "markdown_visibility"
        parent = __package__.split(".")[0] if __package__ else "markdown_visibility"
        if error.name not in (expected, parent):
            raise
        _visibility_spec = importlib.util.spec_from_file_location(
            "_yomiyasu_markdown_visibility",
            os.path.join(os.path.dirname(os.path.realpath(__file__)), "markdown_visibility.py"))
        _visibility_module = importlib.util.module_from_spec(_visibility_spec)
        try:
            _visibility_spec.loader.exec_module(_visibility_module)
        except (OSError, SyntaxError) as _load_error:
            raise ImportError(
                "{} を読めません（{}: {}）。yomiyasu_check.py と同じ版の markdown_visibility.py を同じフォルダに置いてください。".format(
                    _visibility_spec.origin, type(_load_error).__name__, _load_error),
                name=expected) from _load_error
        if not hasattr(_visibility_module, "decode_source"):
            raise ImportError(
                "{} に decode_source がありません。yomiyasu_check.py と同じ版の markdown_visibility.py を置いてください。".format(
                    _visibility_spec.origin),
                name=expected)
        decode_source = _visibility_module.decode_source
except ImportError as _import_error:
    # スクリプトとして動かしたときは、main() が内部エラー（終了コード3）として出す。
    # モジュールとして読むときは、そのまま ImportError を出す。
    if __name__ != "__main__":
        raise
    _IMPORT_ERROR = _import_error
else:
    _IMPORT_ERROR = None


# 出力の形の版。キーを足すだけなら上げない。キーの意味や型を変えたときに上げる。
# 照合の JSON の版（MATERIALS_FORMAT_VERSION）は yomiyasu_diff.py にある（ground() が diff にあるため）。
RECORD_FORMAT_VERSION = 1   # 記録（runs/<実行ID>/attempt-<n>.json）
RESULT_FORMAT_VERSION = 1   # run と verify の --json

# このファイルのフォルダ。lint と diff は、ここにある同じ版のファイルを使う。
_HERE = os.path.dirname(os.path.realpath(__file__))
# 記録の tools に入れる4本（名前を決めたファイルだけを数える。__pycache__ は数えない）
_TOOL_NAMES = ("yomiyasu_check.py", "yomiyasu_lint.py", "yomiyasu_diff.py", "markdown_visibility.py")
# 外から渡す実行IDの形（3.7）。状態フォルダの外を指せないようにする
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ATTEMPT_FILE = re.compile(r"^attempt-([0-9]+)\.json$")
_BY_PATH_ENTRY = re.compile(r"^([0-9]{8}T[0-9]{6}Z)\.(.+)\.([0-9]+)$")
_TOOL_VERSION = re.compile(r"^__version__\s*=\s*[\"']([^\"']+)[\"']\s*$", re.M)
_DEFAULT_TIMEOUT = 90          # 子プロセスの検査に使える秒数の合計の既定（Claude Code の Bash の既定の上限120秒より短い）
# 子を待つ秒数がこれを超えたら、上限なしで待つ。とても大きな --timeout（約25日を超える値）は、OS の待ち方の時間の形を超えて
# OverflowError になるため（反証レビュー spec F1、robust R6）。約11.6日なので、上限なしとみなしても違いは出ない
_WAIT_LIMIT = 1000000
_MATERIALS_VERSION_LINE = re.compile(r"^MATERIALS_FORMAT_VERSION\s*=\s*([0-9]+)\s*(?:#.*)?$", re.M)
# 人が読む文に書く検査名（5.2 の完了報告の4語）。状態の行の checks= と failed= は名前のまま
_CHECK_LABELS = {"lint": "lint", "diff": "diff", "materials": "資料との照合"}
# 意味が変わる恐れを出す検査。これが最後まで動かなかったときは meaning_risk= を出さない（0件と読めるため）
_RISK_CHECKS = ("diff", "materials")
# 子の JSON で check が読むキーと型（3.4 の4: 形が違っても落ちずに、その検査を error にする。robust R5）
_REPORT_KEYS = {
    "lint": (("candidate_count", int), ("counts", dict), ("findings", list)),
    "diff": (("status", str), ("candidate_count", int), ("meaning_risk_count", int),
             ("fail_on_meaning_risk_count", int), ("meaning_risks", list), ("full_diff", dict), ("new_words", list)),
}
_LINK_SECONDS = 6 * 60 * 60     # 前の記録につなぐのは6時間以内（3.8 の5）
_STDERR_LIMIT = 2000            # 記録に残す子の標準エラーの字数
_REPLACE_TRIES = 6              # os.replace を PermissionError のあと50ミリ秒待って5回まで書き直す（3.12、10.3 B4）
_REPLACE_WAIT = 0.05
_ATTEMPT_TRIES = 100            # 回の番号を確保するのは100回まで（3.12）
_NOT_JUDGED = ["meaning_preservation", "reader_comprehension"]

_GITIGNORE = "# yomiyasu の検査記録。git に入れない。\n*\n"
_DISCLAIMER = "この記録は検査を実行したことを示すだけで、意味が保たれたことや読みやすさの合格を示すものではありません。"
_MATERIALS_DISCLAIMER = ("照らしたのは数値、名前、語、確度の語だけです。主張、条件、担当が資料どおりかは判定していません。"
                         "資料と読み比べてください。")
_SAME_FILE_ERROR = ("原文と最終稿が同じファイルです。書き直す前の原文を別のファイルに残し、最終稿を別のファイルに保存してから"
                    "実行してください。原文を上書きしてしまったときは、git などで元の版を取り出して --source に渡してください。")
# 1行目の {仕上げ}（3.5、10.4 S11）
_FINALIZE_FILE = "提出の直前に、本文を変えずに verify を1回実行してください。"
_FINALIZE_STDIN = "本文はこのままで返答し、完了報告にこの出力の2行目を写してください。"
_FINALIZE_NO_RECORD = ("記録を残さない指定なので verify はできません。完了報告の「実行しなかった検査」に"
                       "「最終稿の照合（記録を残さない指定のため）」と書いてください。")
_FAILED_NAMES = {"timeout": "時間切れ", "error": "内部エラー"}

# 3.11 の区切りの行（行全体がこの文字列。行末の \r は無視する）
_MARKERS = OrderedDict(((b"<<<yomiyasu:original>>>", "source"), (b"<<<yomiyasu:material>>>", "material"),
                        (b"<<<yomiyasu:final>>>", "final")))
_STDIN_FORM = ("<<<yomiyasu:original>>>\n（書き直す前の原文）\n<<<yomiyasu:final>>>\n（最終稿）\n"
               "新規作成では <<<yomiyasu:original>>> の代わりに、資料ごとに <<<yomiyasu:material>>> の行と資料を書きます。")


# ---- 小さな道具 ----

def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _text_sha256(text):
    """3.7 の text_sha256。decode_source のあとの文字列から、末尾の改行をすべて外して改行を1つ付ける（空なら空）。"""
    body = text.rstrip("\n")
    if body:
        body += "\n"
    return _sha256(body.encode("utf-8", "surrogatepass"))


def _file_sha256(path):
    with open(path, "rb") as handle:
        return _sha256(handle.read())


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(moment):
    """ファイル名に使う時刻（コロンを含まない。Windows でも作れる）。"""
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _parse_iso(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


class _NoWorkingDirectory(Exception):
    """作業ディレクトリが消えている、または読めない（入力の誤りとして終了コード2。robust R11）。"""


def _getcwd():
    try:
        return os.getcwd()
    except OSError as error:
        raise _NoWorkingDirectory("yomiyasu_check.py: 作業ディレクトリを読めません（{}）。存在するフォルダに移ってから"
                                  "実行してください。".format(getattr(error, "strerror", None) or error))


def _abspath(path):
    """os.path.abspath と同じ。相対パスのときだけ作業ディレクトリを読む（読めなければ _NoWorkingDirectory）。"""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(_getcwd(), path))


def _label(name):
    """人が読む文に書く検査名（5.2）。"""
    return _CHECK_LABELS.get(name, name)


def _same_path(a, b):
    return os.path.normcase(os.path.realpath(_abspath(a))) == os.path.normcase(os.path.realpath(_abspath(b)))


def _same_file(a, b):
    """同じファイルか（パスの比べと、あれば samefile。大文字と小文字を区別しないファイルシステムやハードリンクのため）。"""
    if _same_path(a, b):
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _host_value(value):
    """記録に入れる環境の値。空や、展開されなかった ${…} を含む値は null にする（3.2）。"""
    if not value or "${" in value:
        return None
    return value


def _chmod(path, mode):
    # 原稿の写しを含むので、POSIX ではフォルダを 0o700、ファイルを 0o600 にする（3.6）。chmod は POSIX のときだけ（3.12）
    if os.name == "posix":
        os.chmod(path, mode)


def _replace(source, target):
    """os.replace。ほかのプロセスがファイルを開いているときの PermissionError は、50ミリ秒待って5回まで書き直す
    （Windows を考えたもの。OS によらず書き直す。3.12、10.3 B4）。"""
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(_REPLACE_WAIT)


def _write_atomic(path, data):
    """同じフォルダの一時ファイルに書いてから入れ替える（読む側が書きかけを見ない。3.12）。"""
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        _chmod(temporary, 0o600)
        _replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _touch(folder, name):
    """空のファイルを作る（索引。すでにあればそのまま）。"""
    path = os.path.join(folder, name)
    handle = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(handle)
    _chmod(path, 0o600)


def _ensure_dir(base, *parts):
    """base の下にフォルダを1段ずつ作る（作ったフォルダだけ 0o700 にする）。作ったフォルダのパスを返す。"""
    path = base
    for part in parts:
        path = os.path.join(path, part)
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            if not os.path.isdir(path):
                raise
            continue
        _chmod(path, 0o700)
    return path


def _ensure_state(state):
    """状態フォルダを用意する。作ったときだけ .gitignore と state.json を書く。すでにあるフォルダには足さない（10.3 B2）。

    .gitignore と state.json を書けなかったときは、作りかけのフォルダを消す。残すと次の run が「すでにあるフォルダ」として
    .gitignore なしで書き続け、git status に出る（3.6。反証レビュー robust R3）。"""
    if os.path.isdir(state):
        return
    parent = os.path.dirname(state)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    try:
        os.mkdir(state, 0o700)
    except FileExistsError:
        if os.path.isdir(state):
            return
        raise
    written = []
    try:
        _chmod(state, 0o700)
        state_json = json.dumps({"format": "yomiyasu-state", "format_version": 1}, ensure_ascii=True) + "\n"
        for name, data in ((".gitignore", _GITIGNORE.encode("utf-8")), ("state.json", state_json.encode("ascii"))):
            path = os.path.join(state, name)
            written.append(path)
            _write_atomic(path, data)
    except BaseException:
        for path in written:
            try:
                os.unlink(path)
            except OSError:
                pass
        try:
            os.rmdir(state)  # 並列の run が中に書き始めていれば空でないので消えない（そのまま使われる）
        except OSError:
            pass
        raise


def _state_dir(option):
    """状態フォルダの決め方（3.6。run、verify、フックで同じ規則）。

    1 --state-dir、2 環境変数 YOMIYASU_STATE_DIR、3 作業ディレクトリから上へたどり、.git（フォルダでもファイルでもよい）が
    ある最初のフォルダの .yomiyasu/、4 作業ディレクトリの .yomiyasu/。ここではフォルダを作らない。
    環境変数が空白だけのときと、展開されなかった ${…} を含むときは、ないものとして3と4に進む（--session の ${ と同じ扱い。
    作業フォルダに「${CLAUDE_PROJECT_DIR}」のようなフォルダを作らない。反証レビュー robust R10）。"""
    if option:
        return _abspath(option)
    environment = os.environ.get("YOMIYASU_STATE_DIR")
    if environment and environment.strip() and "${" not in environment:
        return _abspath(environment)
    cwd = _getcwd()
    current = cwd
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return os.path.join(current, ".yomiyasu")
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.join(cwd, ".yomiyasu")
        current = parent


def _record_digest(record):
    """3.7 の record_digest。record_digest を除いて、キーを並べ替え、区切りを詰めた JSON の SHA-256。"""
    body = dict((key, value) for key, value in record.items() if key != "record_digest")
    text = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + _sha256(text.encode("ascii"))


def _status_line(state, via, run_id=None, attempt=None, final=None, expected=None, mode=None, checks=None,
                 meaning_risk=None, replay=None, failed=None, reason=None):
    """状態の行（3.10）。キーの順は固定で、値に空白を入れない。読む側の正規表現は
    ^yomiyasu-check: ([a-z_]+)((?: [a-z_]+=\\S+)*)$"""
    fields = [("via", via), ("run", run_id or "-"), ("attempt", str(attempt) if attempt else "-"), ("final", final or "-")]
    for key, value in (("expected", expected), ("mode", mode), ("checks", checks), ("meaning_risk", meaning_risk),
                       ("replay", replay), ("failed", failed), ("reason", reason)):
        if value is not None:
            fields.append((key, str(value)))
    return "yomiyasu-check: " + state + "".join(" {}={}".format(key, value) for key, value in fields)


def _read_record_status(path):
    """記録を読む。("missing", None)、("bad", None)、("ok", 記録の dict) のどれかを返す。
    大きさ0のファイルは書いている途中とみなし、50ミリ秒待って1回だけ読み直す（3.9 の4、3.12）。"""
    data = b""
    for attempt in range(2):
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except FileNotFoundError:
            return "missing", None
        except OSError:
            return "bad", None
        if data:
            break
        if attempt == 0:
            time.sleep(0.05)
    if not data:
        return "bad", None
    try:
        record = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return "bad", None
    return ("ok", record) if isinstance(record, dict) else ("bad", None)


def _read_record(path):
    """記録を読む。読めなければ（ない、空、JSON でない、dict でない）None。"""
    return _read_record_status(path)[1]


def _attempt_numbers(run_dir):
    """実行のフォルダにある attempt-<n>.json の n（大きさ0の書きかけも含む）。"""
    try:
        names = os.listdir(run_dir)
    except OSError:
        return []
    numbers = []
    for name in names:
        match = _ATTEMPT_FILE.match(name)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def _tool_versions():
    """記録の tools（4本の版の文字列と SHA-256）。スクリプトは読み込まず、バイト列から読む。"""
    tools = OrderedDict()
    for name in _TOOL_NAMES:
        try:
            with open(os.path.join(_HERE, name), "rb") as handle:
                data = handle.read()
        except OSError:
            tools[name] = {"version": None, "sha256": None}
            continue
        match = _TOOL_VERSION.search(data.decode("utf-8", "replace"))
        tools[name] = {"version": match.group(1) if match else None, "sha256": _sha256(data)}
    return tools


def _skill_version(data):
    """SKILL.md の frontmatter の metadata.version（YAML のライブラリなしで、metadata: の次の字下げした行から取る。4章）。"""
    try:
        lines = data.decode("utf-8").lstrip("﻿").split("\n")
    except UnicodeDecodeError:
        return None
    if not lines or lines[0].rstrip("\r") != "---":
        return None
    inside = False
    for line in lines[1:]:
        line = line.rstrip("\r")
        if line == "---":
            break
        if re.match(r"^metadata\s*:\s*$", line):
            inside = True
            continue
        if inside:
            if line and not line[0].isspace():
                inside = False
                continue
            match = re.match(r"^\s+version\s*:\s*[\"']?([^\"'\s]+)[\"']?\s*$", line)
            if match:
                return match.group(1)
    return None


def _skill_info():
    """scripts の1つ上に SKILL.md があるときだけ埋める（リポジトリのルートの scripts から動かすと found は偽。3.7）。"""
    skill_dir = os.path.dirname(_HERE)
    path = os.path.join(skill_dir, "SKILL.md")
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return {"found": False, "dir": None, "skill_md_sha256": None, "version": None}
    return {"found": True, "dir": skill_dir, "skill_md_sha256": _sha256(data), "version": _skill_version(data)}


# ---- lint と diff の読み込み（run と verify --replay の中だけ。3.4、3.13 の2）----

_MODULES = {}


def _load_tool(name, required):
    """隣の <name>.py を読み込む。通常の import で読めないか、読めたものが隣のファイルでないか、要る名前がないときは、
    隣のファイルを spec_from_file_location で読む（lint と diff の markdown_visibility の読み方と同じ形）。"""
    if name in _MODULES:
        return _MODULES[name]
    path = os.path.join(_HERE, name + ".py")
    expected = (__package__ + "." + name) if __package__ else name
    module = None
    try:
        module = importlib.import_module(expected)
    except SyntaxError as error:
        raise ImportError("{} を読めません（SyntaxError: {}）。yomiyasu_check.py と同じ版の {}.py を置いてください。".format(
            error.filename or path, error.msg, name), name=expected) from error
    except ImportError as error:
        parent = __package__.split(".")[0] if __package__ else name
        if error.name not in (expected, parent):
            raise
    if module is not None:
        found = getattr(module, "__file__", None)
        if not found or not _same_path(found, path) or any(not hasattr(module, item) for item in required):
            module = None
    if module is None:
        spec = importlib.util.spec_from_file_location("_yomiyasu_check_" + name, path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except (OSError, SyntaxError) as error:
            raise ImportError("{} を読めません（{}: {}）。yomiyasu_check.py と同じ版の {}.py を同じフォルダに置いてください。".format(
                path, type(error).__name__, error, name), name=expected) from error
        missing = [item for item in required if not hasattr(module, item)]
        if missing:
            raise ImportError("{} に {} がありません。yomiyasu_check.py と同じ版の {}.py を置いてください。".format(
                path, "、".join(missing), name), name=expected)
    _MODULES[name] = module
    return module


def _lint_module():
    return _load_tool("yomiyasu_lint", ("render_report", "render_findings", "LINT_FORMAT_VERSION"))


def _diff_module():
    return _load_tool("yomiyasu_diff", ("diff", "ground", "report", "report_parts", "fail_on_count", "extract_numbers",
                                        "STANCES", "MATERIALS_FORMAT_VERSION"))


# ---- 入力 ----

class _Input(object):
    """入力1つ（原文、資料、最終稿）。バイト列を1回だけ読み、ハッシュと、decode_source でそろえた本文を持つ。"""

    def __init__(self, role, index, path, data):
        self.role = role                      # "source"、"material"、"final"（10.3 C1）
        self.index = index                    # 資料は1から、ほかは0
        self.path = path                      # 絶対パス。標準入力なら None
        self.via = "file" if path is not None else "stdin"
        self.data = data
        self.sha256 = _sha256(data)
        self.text, info = decode_source(data)  # UTF-8 でなければ UnicodeDecodeError
        self.bom = info["bom"]
        self.eol = info["eol"]
        self.text_sha256 = _text_sha256(self.text)

    def snapshot(self):
        return "inputs/" + self.sha256 + ".bin"

    def token(self):
        """状態の行の final=。標準入力は本文のハッシュで照らすので text-sha256:（3.10、10.4 S14）。"""
        if self.via == "stdin":
            return "text-sha256:" + self.text_sha256[:12]
        return "sha256:" + self.sha256[:12]

    def record(self):
        return OrderedDict((("role", self.role), ("index", self.index), ("path", self.path), ("via", self.via),
                            ("bytes", len(self.data)), ("sha256", self.sha256), ("text_sha256", self.text_sha256),
                            ("bom", self.bom), ("eol", self.eol), ("snapshot", self.snapshot())))


def _read_stdin_bytes():
    """標準入力をバイト列で読む。(バイト列, None) か (None, 誤りの文)。"""
    stream = sys.stdin
    if stream is None:
        return None, "Error reading stdin: 標準入力を読めません（標準入力がありません）"
    try:
        buffer = getattr(stream, "buffer", None)
        data = buffer.read() if buffer is not None else stream.read()
    except UnicodeDecodeError:
        return None, "Error reading stdin: UTF-8 として読めません"
    except (OSError, ValueError) as error:
        reason = getattr(error, "strerror", None) or error
        return None, "Error reading stdin: 標準入力を読めません（{}）".format(reason)
    if isinstance(data, str):
        # StringIO のようにバイト列を読めないときは、読んだ文字列を UTF-8 にしてから同じように扱う（0.4）
        data = data.encode("utf-8", "surrogatepass")
    return data, None


def _make_input(role, index, path, data):
    try:
        return _Input(role, index, path, data), None
    except UnicodeDecodeError:
        if path is None:
            return None, "Error reading stdin: UTF-8 として読めません"
        return None, "Error opening file {}: UTF-8 として読めません".format(path)


def _read_named(role, index, given, stdin_data):
    """ファイル（または - なら標準入力）を読んで _Input にする。

    最終稿は検査のあとで読み直す（3.4 の6）ので、通常のファイルでないもの（/dev/stdin、<(…) などのパイプ）は2にして
    --final - を案内する。読み直すと空になり、変わっていない最終稿を「途中で変わった」と報告するため（robust R8）。"""
    if given == "-":
        return _make_input(role, index, None, stdin_data)
    try:
        with open(given, "rb") as handle:
            if role == "final" and not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None, ("Error opening file {}: 通常のファイルではありません（パイプなど。検査のあとで読み直せません）。"
                              "標準入力から渡すときは --final - を使ってください".format(given))
            data = handle.read()
    except (OSError, ValueError) as error:
        reason = getattr(error, "strerror", None) or error
        return None, "Error opening file {}: ファイルを開けません（{}）".format(given, reason)
    item, problem = _make_input(role, index, _abspath(given), data)
    if problem:
        return None, "Error opening file {}: UTF-8 として読めません".format(given)
    return item, None


def _split_stdin(data):
    """3.11 の区切りの行で標準入力を分ける。([(役割, バイト列)], None) か (None, 理由)。

    各部分は、区切りの行の次のバイトから、次の区切りの行の先頭まで（末尾の改行を含む）。先頭の BOM は1つ外す。"""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    parts = []
    current = None
    position = 0
    while position < len(data):
        end = data.find(b"\n", position)
        following = len(data) if end < 0 else end + 1
        bare = data[position:following].rstrip(b"\n")
        if bare.endswith(b"\r"):
            bare = bare[:-1]
        role = _MARKERS.get(bare)
        if role is not None:
            if current is not None:
                parts.append(current)
            current = [role, following, following]
        elif current is None:
            if bare.strip():
                return None, "空白以外の最初の行が区切りの行ではありません"
        else:
            current[2] = following
        position = following
    if current is not None:
        parts.append(current)
    roles = [role for role, _, _ in parts]
    if roles.count("final") == 0:
        return None, "<<<yomiyasu:final>>> の行がありません"
    if roles.count("final") > 1:
        return None, "<<<yomiyasu:final>>> の行が2つ以上あります"
    if roles.count("source") > 1:
        return None, "<<<yomiyasu:original>>> の行が2つ以上あります"
    if "source" not in roles and "material" not in roles:
        return None, "<<<yomiyasu:original>>> の行も <<<yomiyasu:material>>> の行もありません"
    return [(role, data[start:end]) for role, start, end in parts], None


def _read_inputs(args):
    """原文、資料、最終稿を1回ずつ読む。((原文 or None, [資料], 最終稿), None) か (None, 誤りの文)。"""
    if args.stdin:
        data, problem = _read_stdin_bytes()
        if problem:
            return None, problem
        pieces, problem = _split_stdin(data)
        if problem:
            return None, "--stdin の本文の区切りが正しくありません（{}）。行全体が区切りになるように、次の形で渡してください。\n{}".format(
                problem, _STDIN_FORM)
        source, materials, final = None, [], None
        for role, piece in pieces:
            index = len(materials) + 1 if role == "material" else 0
            item, problem = _make_input(role, index, None, piece)
            if problem:
                return None, problem
            if role == "source":
                source = item
            elif role == "material":
                materials.append(item)
            else:
                final = item
        return (source, materials, final), None
    given = [args.final[0]] + list(args.source or []) + list(args.materials or [])
    stdin_data = None
    if "-" in given:
        stdin_data, problem = _read_stdin_bytes()
        if problem:
            return None, problem
    source = None
    if args.source:
        source, problem = _read_named("source", 0, args.source[0], stdin_data)
        if problem:
            return None, problem
    materials = []
    for index, path in enumerate(args.materials or [], 1):
        item, problem = _read_named("material", index, path, stdin_data)
        if problem:
            return None, problem
        materials.append(item)
    final, problem = _read_named("final", 0, args.final[0], stdin_data)
    if problem:
        return None, problem
    return (source, materials, final), None


# ---- 実行IDと回（3.8。3 の登録と 4 の start はフックの段で作る）----

def _new_run_id(state, moment):
    """新しい実行ID（UTC の時刻と os.urandom(4) の16進。3.7）。"""
    while True:
        run_id = _stamp(moment) + "-" + os.urandom(4).hex()
        if not os.path.exists(os.path.join(state, "runs", run_id)):
            return run_id


def _same_inputs(recorded, current):
    """記録の Input の並びと、今の入力の並びが同じか（順によらない）。"""
    if not isinstance(recorded, list) or len(recorded) != len(current):
        return False
    if any(not isinstance(item, dict) for item in recorded):
        return False
    if all(item.get("via") == "file" for item in recorded) and all(item.via == "file" for item in current):
        return sorted(str(item.get("sha256")) for item in recorded) == sorted(item.sha256 for item in current)
    return sorted(str(item.get("text_sha256")) for item in recorded) == sorted(item.text_sha256 for item in current)


def _same_origin(record, mode, source, materials):
    """同じモードで、同じ原文（新規作成では同じ資料の集まり）の記録か。"""
    inputs = record.get("inputs")
    if record.get("mode") != mode or not isinstance(inputs, dict):
        return False
    if mode == "rewrite":
        return _same_inputs([inputs.get("source")], [source])
    return _same_inputs(inputs.get("materials"), materials)


def _latest_record(run_dir):
    """実行の中で読める最新の記録（大きい回から探す）。"""
    for number in reversed(_attempt_numbers(run_dir)):
        record = _read_record(os.path.join(run_dir, "attempt-{}.json".format(number)))
        if record is not None:
            return record
    return None


def _path_key(final, source, materials):
    """index/by-path のキー（3.6）。ファイルは最終稿の実際のパス、標準入力は原文（新規作成では資料）の本文のハッシュ。"""
    if final.via == "file":
        base = os.path.normcase(os.path.realpath(final.path))
    elif source is not None:
        base = "stdin:" + source.text_sha256
    else:
        base = "stdin:" + "".join(sorted(item.text_sha256 for item in materials))
    return _sha256(base.encode("utf-8", "surrogateescape"))


def _by_path_entries(state, key):
    """index/by-path/<キー>/ の索引を新しい順に並べる（時刻、作った順、回）。[(実行ID, 回)]。"""
    folder = os.path.join(state, "index", "by-path", key)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    entries = []
    for name in names:
        match = _BY_PATH_ENTRY.match(name)
        if not match or not _RUN_ID.match(match.group(2)):
            continue
        try:
            made = os.stat(os.path.join(folder, name)).st_mtime_ns
        except OSError:
            continue
        entries.append(((match.group(1), made, int(match.group(3))), match.group(2), int(match.group(3))))
    entries.sort(reverse=True)
    return [(run_id, number) for _, run_id, number in entries]


def _latest_by_path(state, key):
    """index/by-path/<キー>/ の最新の記録。(実行ID, 記録) か None。最新の1件だけを見る（questions.md の19）。"""
    entries = _by_path_entries(state, key)
    if not entries:
        return None
    run_id, number = entries[0]
    record = _read_record(os.path.join(state, "runs", run_id, "attempt-{}.json".format(number)))
    return (run_id, record) if record is not None else None


def _link(state, run_id, new_run, mode, source, materials, final, moment, cwd):
    """実行IDと、次に確保を試す回を決める（読むだけ）。({"run_id", "attempt"}, None) か (None, 誤りの文)。"""
    runs = os.path.join(state, "runs")
    if run_id is not None:
        run_dir = os.path.join(runs, run_id)
        latest = _latest_record(run_dir)
        if latest is not None and not _same_origin(latest, mode, source, materials):
            return None, ("別の原文の実行IDです（--run-id {}）。この実行の記録はモードか原文（新規作成では資料）が違います。"
                          "この原文で検査するときは、--run-id を外すか、別の実行IDを指定してください。".format(run_id))
        numbers = _attempt_numbers(run_dir)
        return {"run_id": run_id, "attempt": (numbers[-1] + 1) if numbers else 1}, None
    if not new_run:
        found = _latest_by_path(state, _path_key(final, source, materials))
        if found is not None:
            found_id, record = found
            created = _parse_iso(record.get("created_at"))
            recorded_cwd = record.get("cwd")
            if (created is not None and (moment - created).total_seconds() <= _LINK_SECONDS
                    and isinstance(recorded_cwd, str) and _same_path(recorded_cwd, cwd)
                    and _same_origin(record, mode, source, materials)):
                numbers = _attempt_numbers(os.path.join(runs, found_id))
                return {"run_id": found_id, "attempt": (numbers[-1] + 1) if numbers else 1}, None
    return {"run_id": _new_run_id(state, moment), "attempt": 1}, None


# ---- 検査 ----

def _wait_seconds(remaining):
    """子を待つ秒数。_WAIT_LIMIT を超える値は上限なし（None）にする（OverflowError を避ける。spec F1、robust R6）。"""
    return None if remaining > _WAIT_LIMIT else remaining


class _Children(object):
    """lint と diff の子プロセスを、同じ締め切り（開始から --timeout 秒）で並べて動かす。

    check が外から止められたとき（SIGTERM、SIGHUP、Ctrl+C）は、呼ぶ側が stop() で動いている子を止める。止めないと、
    子は親を失ったまま最後まで動き続ける（3.13 の7。反証レビュー robust R1、agent 12）。"""

    def __init__(self, timeout, environment):
        self.deadline = time.monotonic() + timeout
        self.environment = environment
        self.lock = threading.Lock()
        self.processes = []
        self.stopped = False
        self.threads = []
        self.results = {}

    def start(self, name, command):
        thread = threading.Thread(target=self._run, args=(name, command))
        thread.daemon = True
        thread.start()
        self.threads.append(thread)

    def _run(self, name, command):
        """子を1つ動かし、results[name] に (状態, 終了コード, 標準出力, 標準エラー, ミリ秒, 誤り) を入れる。
        終了コードが None の error は、子を起動できなかったか、待てなかったとき。どの道でも結果を必ず残す。"""
        try:
            self._run_one(name, command)
        except Exception as error:  # 子を止める途中の誤りなど
            self.results.setdefault(name, ("error", None, None, "", 0, "子プロセスを動かせません（{}: {}）".format(
                type(error).__name__, error)))

    def _run_one(self, name, command):
        started = time.monotonic()

        def elapsed():
            return int((time.monotonic() - started) * 1000)

        def cannot(error):
            return ("error", None, None, "", elapsed(), "子プロセスを動かせません（{}: {}）".format(
                type(error).__name__, error))

        remaining = self.deadline - started
        if remaining <= 0:
            self.results[name] = ("timeout", None, None, "", 0, "時間切れ（--timeout の秒数を使い切った）")
            return
        try:
            with self.lock:
                if self.stopped:
                    self.results[name] = ("error", None, None, "", 0, "子プロセスを動かす前に止められました")
                    return
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, env=self.environment)
                self.processes.append(process)
        except Exception as error:  # 起動できない。結果を必ず残し、状態を partial にする
            self.results[name] = cannot(error)
            return
        try:
            stdout, stderr = process.communicate(timeout=_wait_seconds(remaining))
        except subprocess.TimeoutExpired as expired:
            # subprocess.run と同じ止め方（POSIX では、ここまでの出力が expired に入っている）
            process.kill()
            late = b""
            if os.name == "nt":
                _, late = process.communicate()
            else:
                process.wait()
            stderr = (expired.stderr or late or b"").decode("utf-8", "replace")[:_STDERR_LIMIT]
            self.results[name] = ("timeout", None, None, stderr, elapsed(), "時間切れ（--timeout の秒数を超えた）")
            return
        except Exception as error:  # 待てない。子を止めてから、結果を残す
            process.kill()
            process.wait()
            self.results[name] = cannot(error)
            return
        stderr = (stderr or b"").decode("utf-8", "replace")[:_STDERR_LIMIT]
        if process.returncode != 0:
            self.results[name] = ("error", process.returncode, None, stderr, elapsed(),
                                  "終了コード{}".format(process.returncode))
            return
        self.results[name] = ("ran", 0, stdout, stderr, elapsed(), None)

    def wait(self):
        for thread in self.threads:
            thread.join()
        return self.results

    def stop(self):
        """動いている子を止める（これから起動する子も起動しない）。"""
        with self.lock:
            self.stopped = True
            processes = list(self.processes)
        for process in processes:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=5)
            except Exception:
                pass


def _parse_report(stdout, name, version):
    """子の標準出力（lint か diff の --json）を読み、形式の名前と版、check が読むキーと型を確かめる。
    (値, None) か (None, 理由)。形が違えば、その検査を error にする（3.4 の4。check は落ちない。robust R5）。"""
    expected_format = "yomiyasu-" + name
    try:
        value = json.loads(stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, "子の標準出力を JSON として読めません"
    if not isinstance(value, dict) or value.get("format") != expected_format:
        return None, "子の標準出力が {} の JSON ではありません".format(expected_format)
    if type(value.get("format_version")) is not int or value["format_version"] != version:
        return None, "子の JSON の形式の版が {} ではありません（yomiyasu_check.py と同じ版の yomiyasu_{}.py を置いてください）".format(
            version, name)
    wrong = [key for key, kind in _REPORT_KEYS[name]
             if not isinstance(value.get(key), kind) or (kind is int and isinstance(value.get(key), bool))]
    if wrong:
        return None, "子の JSON に {} がないか、型が違います".format("、".join(wrong))
    return value, None


def _check_entry(name, target):
    return OrderedDict((("name", name), ("status", "error"), ("exit_code", None), ("duration_ms", 0),
                        ("target", target), ("report", None), ("report_sha256", None), ("text", None),
                        ("text_sha256", None), ("summary", None), ("stderr", ""), ("error", None)))


def _with_basis(diff_module, risks, materials_result):
    """推敲で資料があるとき、diff の数値の候補に basis を入れた写しを作る（3.3、10.3 B3）。
    足した値が資料にもどこにもなければ "none"、資料にあれば "material"（どちらも混ざれば "none" を先にする）。"""
    if materials_result is None:
        return [dict(risk) for risk in risks]
    classes = {}
    for item in materials_result.get("items", []):
        if item.get("kind") == "number":
            classes[(item.get("value"), item.get("unit"))] = item.get("classification")
    out = []
    for risk in risks:
        risk = dict(risk)
        if risk.get("kind") == "number":
            found = set()
            for text in (risk.get("detail") or {}).get("added") or []:
                for number in diff_module.extract_numbers(text):
                    found.add(classes.get((number["value"], number["unit"])))
            if "not_in_sources" in found:
                risk["basis"] = "none"
            elif "from_materials" in found:
                risk["basis"] = "material"
        out.append(risk)
    return out


def _materials_lines(diff_module, ctx):
    """「■ 資料との照合」の節の行（3.3、3.5 の例3）。"""
    result = ctx.materials_result
    items = result.get("items", [])
    lines = ["■ 資料との照合（資料{}件）".format(len(ctx.materials))]
    if ctx.mode == "rewrite":
        supplements = [item["text"] for item in items if item.get("classification") == "from_materials"]
        if supplements:
            lines.append("- 資料に基づく補足の候補: " + "、".join(supplements))
    words = [item["text"] for item in items
             if item.get("kind") == "word" and item.get("classification") == "not_in_sources"]
    if ctx.mode == "rewrite" and ctx.diff_result is not None:
        # 推敲では diff の「元の文にない語」と重なる語を除く（3.3）
        new_words = set(ctx.diff_result.get("new_words") or [])
        words = [word for word in words if word not in new_words]
    if words:
        lines.append("- 資料にない語: " + "、".join(words))
    dropped = [item["text"] for item in items if item.get("classification") == "dropped_certainty"]
    if dropped:
        lines.append("- 資料にあった確度の語が最終稿にない: " + "、".join(dropped))
    if ctx.mode == "compose":
        # 資料にあって最終稿にない数値は「参考」の1行（要約で省くのは正しいことが多いので候補にしない）
        in_final = set((item.get("value"), item.get("unit")) for item in items if item.get("kind") == "number")
        reference = OrderedDict()
        for material in ctx.materials:
            for number in diff_module.extract_numbers(material.text):
                key = (number["value"], number["unit"])
                if key not in in_final and key not in reference:
                    reference[key] = number["text"]
        if reference:
            lines.append("- 参考: 資料にあって最終稿にない数値: " + "、".join(reference.values()))
    lines.append("- " + _MATERIALS_DISCLAIMER)
    return lines


def _mode_checks(mode, materials):
    """3.3 の表: モードと資料の有無で決まる必要な検査。"""
    if mode == "rewrite":
        return ["lint", "diff"] + (["materials"] if materials else [])
    return ["lint", "materials"]


class _Context(object):
    """run の1回分の入力と結果。"""

    def __init__(self):
        self.mode = None
        self.source = None
        self.materials = []
        self.final = None
        self.required = []
        self.entries = OrderedDict()
        self.outputs = {}            # 子の標準出力のバイト列（lint、diff）
        self.lint_result = None
        self.diff_result = None      # 子の JSON そのもの
        self.materials_result = None
        self.risks = []              # 意味が変わる恐れ（diff の basis 入りの写しと、照合の unsupported）
        self.diff_risks = None       # diff の basis 入りの写し
        self.texts = {}              # 人が読む形（.txt に書く文。lint と diff は子の JSON から作ったもの）
        self.lint_findings = None    # lint の render_findings() の文
        self.diff_parts = None       # diff の report_parts()
        self.final_changed = False
        self.no_record = False
        self.fail_on = []
        self.fail_on_hits = []

    @property
    def failed(self):
        failed = [(name, entry["status"]) for name, entry in self.entries.items() if entry["status"] != "ran"]
        if self.final_changed:
            failed.append(("final", "changed"))
        return failed

    @property
    def partial(self):
        return bool(self.failed)

    def risks_complete(self):
        """意味が変わる恐れを出す検査（diff、資料との照合）がすべて最後まで動いたか。動いていなければ、件数は出さない
        （状態の行の meaning_risk= を0件と読ませない。agent 4）。"""
        return all(self.entries[name]["status"] == "ran" for name in self.required if name in _RISK_CHECKS)

    def candidate_total(self):
        """1回目の「候補あり／なし」は、lint、diff、資料との照合の候補の合計で決める（10.3 B7）。"""
        total = 0
        for result in (self.lint_result, self.diff_result, self.materials_result):
            if result is not None:
                total += int(result.get("candidate_count") or 0)
        return total


def _run_checks(ctx, snapshots, stance, timeout):
    """lint と diff を子プロセスで（並べて）動かし、資料があればプロセスの中で照らす（3.4 の4と5）。"""
    lint_module, diff_module = _lint_module(), _diff_module()
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    final_snapshot = snapshots[id(ctx.final)]
    commands = OrderedDict()
    commands["lint"] = [sys.executable, "-B", os.path.join(_HERE, "yomiyasu_lint.py"), "--json", final_snapshot]
    if "diff" in ctx.required:
        command = [sys.executable, "-B", os.path.join(_HERE, "yomiyasu_diff.py"), "--json"]
        if stance is not None:
            command += ["--stance", stance]
        commands["diff"] = command + [snapshots[id(ctx.source)], final_snapshot]
    targets = {"lint": OrderedDict((("final", ctx.final.sha256),))}
    if ctx.source is not None:
        targets["diff"] = OrderedDict((("source", ctx.source.sha256), ("final", ctx.final.sha256)))
    material_target = OrderedDict()
    if ctx.source is not None:
        material_target["source"] = ctx.source.sha256
    material_target["materials"] = [item.sha256 for item in ctx.materials]
    material_target["final"] = ctx.final.sha256
    targets["materials"] = material_target
    for name in ctx.required:
        ctx.entries[name] = _check_entry(name, targets[name])

    children = _Children(timeout, environment)
    try:
        for name, command in commands.items():
            children.start(name, command)
        if "materials" in ctx.required:
            entry = ctx.entries["materials"]
            started = time.monotonic()
            try:
                ctx.materials_result = diff_module.ground(
                    ctx.final.text, [item.text for item in ctx.materials],
                    ctx.source.text if ctx.source is not None else None)
                entry["status"] = "ran"
            except Exception as error:  # 照合の例外は記録に残し、状態を partial にする
                entry["error"] = "{}: {}".format(type(error).__name__, error)
                entry["stderr"] = traceback.format_exc()[-_STDERR_LIMIT:]
            entry["duration_ms"] = int((time.monotonic() - started) * 1000)
        results = children.wait()
    except BaseException:
        # 外から止められた（SIGTERM など）。動いている子を止めてから戻る
        children.stop()
        raise

    versions = {"lint": lint_module.LINT_FORMAT_VERSION, "diff": diff_module.DIFF_FORMAT_VERSION}
    for name in ("lint", "diff"):
        if name not in commands:
            continue
        status, code, stdout, stderr, elapsed, error = results[name]
        entry = ctx.entries[name]
        entry.update((("status", status), ("exit_code", code), ("duration_ms", elapsed), ("stderr", stderr),
                      ("error", error)))
        if status != "ran":
            continue
        parsed, problem = _parse_report(stdout, name, versions[name])
        try:
            if parsed is not None:
                # 人が読む形をここで作っておく。子の JSON の形が違って作れなければ、その検査を error にする（robust R5）
                if name == "lint":
                    text = lint_module.render_report(parsed) + "\n"
                    findings = lint_module.render_findings(parsed)
                else:
                    text = diff_module.report(parsed) + "\n"
                    parts = diff_module.report_parts(parsed)
                    risks = _with_basis(diff_module, parsed["meaning_risks"], ctx.materials_result)
        except Exception as error:
            parsed, problem = None, "子の JSON から人が読む形を作れません（{}: {}）".format(type(error).__name__, error)
        if parsed is None:
            entry["status"] = "error"
            entry["error"] = problem
            continue
        ctx.outputs[name] = stdout
        ctx.texts[name] = text
        if name == "lint":
            ctx.lint_result = parsed
            ctx.lint_findings = findings
            entry["summary"] = OrderedDict((("candidate_count", parsed["candidate_count"]), ("counts", parsed["counts"])))
        else:
            ctx.diff_result = parsed
            ctx.diff_parts = parts
            ctx.diff_risks = risks
            entry["summary"] = OrderedDict((
                ("status", parsed["status"]), ("candidate_count", parsed["candidate_count"]),
                ("meaning_risk_count", parsed["meaning_risk_count"]),
                ("fail_on_meaning_risk_count", parsed["fail_on_meaning_risk_count"]),
                ("hunk_count", len(parsed["full_diff"].get("hunks") or []))))
    if ctx.materials_result is not None:
        result = ctx.materials_result
        classes = [item.get("classification") for item in result.get("items", [])]
        ctx.entries["materials"]["summary"] = OrderedDict((
            ("candidate_count", result.get("candidate_count")), ("meaning_risk_count", result.get("meaning_risk_count")),
            ("from_materials", classes.count("from_materials")), ("not_in_sources", classes.count("not_in_sources")),
            ("dropped_certainty", classes.count("dropped_certainty"))))

    if ctx.diff_result is not None:
        ctx.risks.extend(ctx.diff_risks)
    if ctx.materials_result is not None:
        ctx.risks.extend(ctx.materials_result.get("meaning_risks") or [])
    return lint_module, diff_module


def _fail_on_hits(ctx, diff_module):
    """--fail-on に当たった値（指定した順）。meaning-risk は数値・否定・入れ替え・文の種類と資料にない数値（10.6 B1）、
    warn と error は lint の候補で決める。"""
    hits = []
    counts = (ctx.lint_result or {}).get("counts") or {}
    for value in ctx.fail_on:
        if value == "meaning-risk":
            hit = diff_module.fail_on_count(ctx.risks) > 0
        elif value == "warn":
            hit = bool(counts.get("warn") or counts.get("error"))
        else:
            hit = bool(counts.get("error"))
        if hit and value not in hits:
            hits.append(value)
    return hits


# ---- 出力 ----

def _decide(ctx, recorded, problem=None, attempt=None, run_id=None, fix_count=0, same_as_previous=False):
    """状態、1行目、next、状態の行を決める（3.5 の1行目の表を上から当てはめる、3.10）。"""
    if ctx.no_record:
        finalize = _FINALIZE_NO_RECORD
    elif ctx.final.via == "stdin":
        finalize = _FINALIZE_STDIN
    else:
        finalize = _FINALIZE_FILE
    failed = ctx.failed
    if failed:
        groups = OrderedDict()
        items = []
        for name, status in failed:
            if name == "final":
                continue
            # 完了報告の「実行しなかった検査」に写す文なので、検査名は 5.2 の語にする（agent 15）
            groups.setdefault(_FAILED_NAMES[status], []).append(_label(name))
            items.append("{}（{}）".format(_label(name), _FAILED_NAMES[status]))
        clauses = ["{}が{}".format("、".join(names), reason) for reason, names in groups.items()]
        if ctx.final_changed:
            # 検査は写しに対して最後まで動いたが、今の最終稿に対しては実行していない（3.4 の6）
            clauses.append("途中で最終稿が変わった")
            items.append("{}（途中で最終稿が変わった）".format("、".join(_label(name) for name in ctx.required)))
        line = "検査の一部を実行できませんでした（{}）。完了報告の「実行しなかった検査」に「{}」と書いてください。".format(
            "、".join(clauses), "、".join(items))
        following = "report_partial"
    elif not recorded and not ctx.no_record:
        line = ("検査を実行しましたが、記録を書けませんでした（{0}）。--state-dir に書ける場所を指定してもう一度実行するか、"
                "完了報告の「実行しなかった検査」に「記録（{0}）」と書いてください。".format(problem))
        following = "report_unrecorded"
    else:
        if ctx.diff_result is not None and ctx.diff_result.get("status") == "no_change":
            line, following = "検査を実行しました。原文から変更はありません。" + finalize, "finalize"
        elif same_as_previous:
            line, following = "検査を実行しました（前回と同じ最終稿）。" + finalize, "finalize"
        elif fix_count >= 2:
            line = ("検査を実行しました（修正{}回目のあと）。修正は1回までの決まりを超えています（このコマンドは止めません）。"
                    "利用者から新しい依頼がない限り本文はもう変えず、残った候補は完了報告に書いてください。".format(fix_count)
                    + finalize)
            following = "finalize_over_limit"
        elif fix_count == 1:
            line = "検査を実行しました（修正後の検査）。本文はもう変えず、残った候補は完了報告に書いてください。" + finalize
            following = "finalize"
        elif ctx.mode == "compose":
            line = ("検査を実行しました（新規作成、1回目）。資料にない数値と名前を確かめ、主張・条件・担当・未確認の事項を"
                    "資料と読み比べてください。直すのは1回までです。直したら同じコマンドをもう一度実行し、直さないなら" + finalize)
            following = "review"
        elif ctx.candidate_total():
            line = ("検査を実行しました（1回目）。下の候補を原文と資料に照らして確かめてください。直すのは1回までです。"
                    "直したら同じコマンドをもう一度実行し、直さないなら" + finalize)
            following = "review"
        else:
            line = ("検査を実行しました（1回目）。規則に当たる候補はありません。全文差分で意図しない変更がないかを確かめ、"
                    "直すなら1回まで、直さないなら" + finalize)
            following = "review"
        if ctx.no_record:
            following = "report_unrecorded"
    if ctx.fail_on_hits and not failed:
        line = "--fail-on={} の条件に当たりました（終了コード1）。".format(",".join(ctx.fail_on_hits)) + line
    if failed:
        status = "partial"
    else:
        status = "executed" if recorded else "unrecorded"
    reason = None
    if not recorded:
        reason = "no_record" if ctx.no_record else "not_writable"
    token = _status_line(status, "run", run_id if recorded else None, attempt if recorded else None, ctx.final.token(),
                         mode=ctx.mode, checks=",".join(ctx.required),
                         meaning_risk=len(ctx.risks) if ctx.risks_complete() else None,
                         failed=",".join("{}({})".format(name, why) for name, why in failed) or None, reason=reason)
    return status, line, following, token


def _unsupported_count(result):
    """3.5 の3行目の q（資料にない数値・名前の数）。照合の items のうち、数値と名前で not_in_sources のもの。
    推敲の資料にない数値は diff の候補の basis "none" で出し、照合の meaning_risks に入れない（3.3）ので、
    meaning_risk_count ではなく items から数える（spec F3）。新規作成では meaning_risk_count と同じ数になる。"""
    return sum(1 for item in result.get("items", [])
               if item.get("kind") in ("number", "name") and item.get("classification") == "not_in_sources")


def _summary_line(ctx):
    """3行目（実行した検査の要約。完了報告の「実行した検査」に対応する）。最後まで動かなかった検査は並べない
    （1行目で「実行しなかった検査」に書くよう案内する。agent 4）。1つもなければ「なし」（5.2）。"""
    parts = []
    failed = dict(ctx.failed)
    if "lint" not in failed:
        parts.append("lint（最終稿）候補{}件".format(ctx.lint_result.get("candidate_count", 0)))
    if "diff" in ctx.required and "diff" not in failed:
        result = ctx.diff_result
        parts.append("diff（原文→最終稿）{} 候補{}件（うち意味が変わる恐れ{}件）".format(
            "変更なし" if result.get("status") == "no_change" else "変更あり", result.get("candidate_count", 0),
            result.get("meaning_risk_count", 0)))
    if "materials" in ctx.required and "materials" not in failed:
        where = "資料{}件".format(len(ctx.materials)) if ctx.mode == "rewrite" else "資料{}件→最終稿".format(len(ctx.materials))
        parts.append("資料との照合（{}）資料にない数値・名前{}件".format(where, _unsupported_count(ctx.materials_result)))
    return "実行した検査: " + ("、".join(parts) if parts else "なし")


def _sections(ctx, lint_module, diff_module):
    """3.5 の節（候補が0件の節は出さない。照合の節は照合したときは必ず出す）。"""
    sections = []
    base = ctx.diff_result if ctx.diff_result is not None else diff_module.diff("", "")
    if ctx.risks:
        sections.append(diff_module.report_parts(dict(base, meaning_risks=ctx.risks))["risks"])
    parts = ctx.diff_parts
    if parts is not None and parts["rules"]:
        rules = parts["rules"]
        sections.append(rules.replace("■ 規則の見直し候補（", "■ 差分の見直し候補（diff、", 1))
    if ctx.lint_result is not None and ctx.lint_result.get("candidate_count"):
        sections.append("■ 表現・書式の見直し候補（lint、最終稿、{}件）\n".format(ctx.lint_result["candidate_count"])
                        + ctx.lint_findings)
    if ctx.materials_result is not None:
        sections.append("\n".join(_materials_lines(diff_module, ctx)))
    if parts is not None and parts["full_diff"]:
        sections.append(parts["full_diff"])
    return sections


def _materials_text(ctx, diff_module):
    """attempt-<n>.materials.txt（照合の意味が変わる恐れと、照合の節）。"""
    blocks = []
    risks = ctx.materials_result.get("meaning_risks") or []
    if risks:
        blocks.append(diff_module.report_parts(dict(diff_module.diff("", ""), meaning_risks=risks))["risks"])
    blocks.append("\n".join(_materials_lines(diff_module, ctx)))
    return "\n\n".join(blocks)


# ---- 記録 ----

def _write_reports(state, ctx, run_id, attempt, diff_module, created):
    """runs/<実行ID>/attempt-<n>.<検査>.json と .txt を書き、Check に名前とハッシュを入れる（3.4 の7、3.7）。
    書いたファイルのパスを created に足す（保存が途中で失敗したときに消すため）。"""
    for name in ctx.required:
        entry = ctx.entries[name]
        if entry["status"] != "ran":
            continue
        if name in ("lint", "diff"):
            data = ctx.outputs[name]
            text = ctx.texts[name]
        else:
            data = json.dumps(ctx.materials_result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
            text = _materials_text(ctx, diff_module) + "\n"
        text_data = text.encode("utf-8")
        report = "runs/{}/attempt-{}.{}.json".format(run_id, attempt, name)
        report_text = "runs/{}/attempt-{}.{}.txt".format(run_id, attempt, name)
        for path, content in ((report, data), (report_text, text_data)):
            created.append(os.path.join(state, *path.split("/")))
            _write_atomic(created[-1], content)
        entry["report"] = report
        entry["report_sha256"] = _sha256(data)
        entry["text"] = report_text
        entry["text_sha256"] = _sha256(text_data)


def _reserve_attempt(run_dir, first):
    """回の番号を O_CREAT | O_EXCL で確保する。取れなければ1つ増やす（100回まで。3.12）。"""
    number = max(1, first)
    for _ in range(_ATTEMPT_TRIES):
        path = os.path.join(run_dir, "attempt-{}.json".format(number))
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            number += 1
            continue
        os.close(handle)
        _chmod(path, 0o600)
        return number, path
    raise OSError("回の番号を確保できません（{} に attempt-{}.json まで）".format(run_dir, number))


def _history(run_dir, attempt, final):
    """同じ実行の前の回から、previous、fix_count、前回と同じ最終稿か、を求める（3.7、3.8）。

    最終稿の比べは、どの回もファイルならバイト列のハッシュ、標準入力が混ざるなら本文のハッシュで行う。
    fix_count は、同じ実行の記録に出てくる最終稿のハッシュの種類の数から1を引いた数。"""
    finals = []
    for number in _attempt_numbers(run_dir):
        if number >= attempt:
            continue
        record = _read_record(os.path.join(run_dir, "attempt-{}.json".format(number)))
        recorded = ((record or {}).get("inputs") or {}).get("final")
        if isinstance(recorded, dict):
            finals.append((number, recorded))
    all_files = final.via == "file" and all(recorded.get("via") == "file" for _, recorded in finals)
    key = "sha256" if all_files else "text_sha256"
    current = final.sha256 if all_files else final.text_sha256
    identities = set(str(recorded.get(key)) for _, recorded in finals)
    identities.add(current)
    fix_count = len(identities) - 1
    if not finals:
        return None, fix_count, False
    number, recorded = finals[-1]
    previous = OrderedDict((("attempt", number), ("final_sha256", recorded.get("sha256"))))
    return previous, fix_count, str(recorded.get(key)) == current


def _put_snapshots(folder, inputs):
    """入力の写しを folder/<sha256>.bin に置く（同じ中身の写しがあれば書かない）。{id(入力): 写しの絶対パス} を返す。"""
    paths = {}
    for item in inputs:
        path = os.path.join(folder, item.sha256 + ".bin")
        try:
            current = _file_sha256(path) if os.path.isfile(path) else None
        except OSError:
            current = None
        if current != item.sha256:
            _write_atomic(path, item.data)
        paths[id(item)] = path
    return paths


def _write_problem(state, error):
    """記録を書けなかった理由の文（1行目と5行目に入れる）。"""
    where = getattr(error, "filename", None) or state
    reason = getattr(error, "strerror", None) or str(error) or type(error).__name__
    return "{} に書けません: {}".format(where, reason)


def _save(state, ctx, link, moment, cwd, host, tools, options, path_key, lint_module, diff_module):
    """回を確保し、レポート、記録、索引を書く（3.4 の7、3.6、3.7、3.12）。(回, 記録のパス, fix_count, 決めたこと) を返す。
    書けなければ OSError を出す（確保した回のファイルは消す）。"""
    run_id = link["run_id"]
    run_dir = _ensure_dir(state, "runs", run_id)
    attempt, record_path = _reserve_attempt(run_dir, link["attempt"])
    created = []
    try:
        previous, fix_count, same = _history(run_dir, attempt, ctx.final)
        decision = _decide(ctx, True, attempt=attempt, run_id=run_id, fix_count=fix_count, same_as_previous=same)
        status, _, following, token = decision
        _write_reports(state, ctx, run_id, attempt, diff_module, created)
        summary = None
        if ctx.materials_result is not None:
            classes = [item.get("classification") for item in ctx.materials_result.get("items", [])]
            summary = OrderedDict((("from_materials", classes.count("from_materials")),
                                   ("not_in_sources", classes.count("not_in_sources")),
                                   ("dropped_certainty", classes.count("dropped_certainty"))))
        record = OrderedDict()
        record["format"] = "yomiyasu-check-record"
        record["format_version"] = RECORD_FORMAT_VERSION
        record["run_id"] = run_id
        record["attempt"] = attempt
        record["fix_count"] = fix_count
        record["previous"] = previous
        record["created_at"] = _iso(moment)
        record["mode"] = ctx.mode
        record["cwd"] = cwd
        record["host"] = host
        record["skill"] = _skill_info()
        record["tools"] = tools
        record["python"] = OrderedDict((("version", platform.python_version()),
                                        ("implementation", platform.python_implementation())))
        record["inputs"] = OrderedDict((("source", ctx.source.record() if ctx.source is not None else None),
                                        ("materials", [item.record() for item in ctx.materials]),
                                        ("final", ctx.final.record())))
        record["options"] = options
        record["required_checks"] = list(ctx.required)
        record["checks"] = [ctx.entries[name] for name in ctx.required]
        record["materials_summary"] = summary
        record["result"] = OrderedDict((
            ("status", status), ("token", token), ("next", following), ("fail_on_hit", bool(ctx.fail_on_hits)),
            ("meaning_risk_count", len(ctx.risks)), ("fail_on_meaning_risk_count", diff_module.fail_on_count(ctx.risks)),
            ("final_unchanged_during_run", not ctx.final_changed), ("not_judged", list(_NOT_JUDGED))))
        record["record_digest"] = _record_digest(record)
        _write_atomic(record_path, (json.dumps(record, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
        name = "{}.{}".format(run_id, attempt)
        for kind, key, entry_name in (("by-final", ctx.final.sha256, name), ("by-text", ctx.final.text_sha256, name),
                                      ("by-path", path_key, _stamp(moment) + "." + name)):
            folder = _ensure_dir(state, "index", kind, key)
            created.append(os.path.join(folder, entry_name))
            _touch(folder, entry_name)
    except BaseException:
        # 記録を書けなかった回は残さない（verify が書きかけとして待たないように）。この回のレポートと索引も消す。
        # 索引を残すと、次の回がこの番号を使い直したときに、別の最終稿の記録を指す（robust R7）
        for path in [record_path] + created:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    return attempt, record_path, fix_count, decision


# ---- run ----

def _fail_on(values):
    """--fail-on の値を確かめる。(値の並び, None) か (None, 誤りの文)。大文字と小文字、「_」と「-」は区別しない（10.5 M5）。"""
    found = []
    for value in values:
        pieces = [piece.strip().lower().replace("_", "-") for piece in value.split(",") if piece.strip()]
        if not pieces:
            return None, "--fail-on に使えない値です: （空）。check で使えるのは meaning-risk、warn、error です。"
        for piece in pieces:
            if piece not in ("meaning-risk", "warn", "error"):
                return None, "--fail-on に使えない値です: {}。check で使えるのは meaning-risk、warn、error です。".format(piece)
            if piece not in found:
                found.append(piece)
    return found, None


def _timeout(raw):
    """--timeout の秒数。(数, None) か (None, 誤りの文)。0より大きい有限の数だけ受ける。"""
    if raw is None:
        return _DEFAULT_TIMEOUT, None
    try:
        value = float(raw)
    except ValueError:
        value = None
    if value is None or not (0 < value < float("inf")):
        return None, "--timeout には0より大きい秒数を渡してください: {}".format(raw if raw.strip() else "（空）")
    return (int(value) if value.is_integer() else value), None


def _run(args, parser):
    # 1. 引数を確かめる。ここから入力を読み終えるまで、状態フォルダには何も書かない（3.4 の1、10.3 C4）
    if args.stdin and (args.final or args.source or args.materials):
        parser.error("--stdin のときは --final、--source、--material を使えません"
                     "（原文か資料と最終稿は、標準入力の区切りの行で渡します）")
    if not args.stdin:
        if not args.final:
            parser.error("最終稿のファイルを --final で渡してください（ファイルを作らないときは --stdin）")
        if len(args.final) > 1:
            parser.error("--final は1つだけ渡してください")
        if args.source and len(args.source) > 1:
            parser.error("原文（--source）は1つだけ渡してください")
        if not args.source and not args.materials:
            parser.error("原文（--source）か資料（--material）を渡してください。推敲では書き直す前の原文を --source に、"
                         "新規作成では資料を --material に渡します")
        if (args.final + list(args.source or []) + list(args.materials or [])).count("-") > 1:
            parser.error("標準入力（-）は1か所だけに使えます")
    if args.run_id is not None and args.new_run:
        parser.error("--run-id と --new-run は一緒に使えません")
    if args.state_dir is not None and not args.state_dir.strip():
        parser.error("--state-dir に空の値は使えません")
    fail_on, problem = _fail_on(args.fail_on)
    if problem:
        _error(problem)
        return 2
    timeout, problem = _timeout(args.timeout)
    if problem:
        _error(problem)
        return 2
    if args.run_id is not None and not _RUN_ID.match(args.run_id):
        _error("--run-id に使えない値です: {}。英数字で始まり、英数字と「.」「_」「-」だけの64字までにしてください。".format(
            args.run_id if args.run_id.strip() else "（空）"))
        return 2
    # 作業ディレクトリは記録の cwd に入れる。消えていれば、何も書かずに2（_run_cli が受ける。robust R11）
    cwd = _getcwd()
    lint_module, diff_module = _lint_module(), _diff_module()
    stance = None
    if args.stance is not None:
        stance = diff_module.STANCES.get(args.stance)
        if stance is None:
            shown = args.stance if args.stance.strip() else "（空）"
            _error("--stance に使えない値です: {}。使えるのは {} です。".format(shown, "、".join(diff_module.STANCES)))
            return 2
    if (not args.stdin and args.source and "-" not in (args.source[0], args.final[0])
            and _same_file(args.source[0], args.final[0])):
        # start（原文の写しを先に取る任意のコマンド）はフックの段で作る。今は同じファイルなら必ず2
        _error(_SAME_FILE_ERROR)
        return 2
    loaded, problem = _read_inputs(args)
    if problem:
        _error(problem)
        return 2

    ctx = _Context()
    ctx.source, ctx.materials, ctx.final = loaded
    ctx.mode = "rewrite" if ctx.source is not None else "compose"
    if ctx.mode == "rewrite":
        ctx.required = _mode_checks("rewrite", ctx.materials)
    else:
        ctx.required = _mode_checks("compose", ctx.materials)
    ctx.no_record = args.no_record
    ctx.fail_on = fail_on
    moment = _utc_now()
    session = args.session if args.session is not None else os.environ.get("YOMIYASU_SESSION")
    host = OrderedDict((("session", _host_value(session)),
                        ("codex_thread_id", _host_value(os.environ.get("CODEX_THREAD_ID"))),
                        ("armed_by", None)))
    tools = _tool_versions()
    options = OrderedDict((("stance", stance), ("fail_on", list(fail_on)), ("timeout", timeout)))

    # 2. 実行IDと回を決める（読むだけ。別の原文の実行IDなら、何も書かずに2）
    state = None if args.no_record else _state_dir(args.state_dir)
    link = None
    path_key = _path_key(ctx.final, ctx.source, ctx.materials)
    if state is not None:
        link, problem = _link(state, args.run_id, args.new_run, ctx.mode, ctx.source, ctx.materials, ctx.final,
                              moment, cwd)
        if problem:
            _error(problem)
            return 2

    # 3. 入力の写しを置き、検査はこの写しに対して行う。記録を書かないとき（--no-record、書けない）は、
    #    消す前提の一時フォルダに写しを置き、終わったら消す（10.4 S12）。ほかの場所に記録を逃がさない
    recording = state is not None
    write_problem = None
    inputs = ([ctx.source] if ctx.source is not None else []) + list(ctx.materials) + [ctx.final]
    temporary = None
    try:
        snapshots = None
        if recording:
            try:
                _ensure_state(state)
                snapshots = _put_snapshots(_ensure_dir(state, "inputs"), inputs)
            except OSError as error:
                recording, write_problem = False, _write_problem(state, error)
        if snapshots is None:
            temporary = tempfile.TemporaryDirectory(prefix="yomiyasu-check-")
            snapshots = _put_snapshots(temporary.name, inputs)
        _run_checks(ctx, snapshots, stance, timeout)
    finally:
        if temporary is not None:
            temporary.cleanup()

    # 4. 最終稿のファイルを読み直し、検査の途中で変わっていないかを確かめる（標準入力なら省く）
    if ctx.final.via == "file":
        try:
            with open(ctx.final.path, "rb") as handle:
                ctx.final_changed = _sha256(handle.read()) != ctx.final.sha256
        except OSError:
            ctx.final_changed = True
    ctx.fail_on_hits = _fail_on_hits(ctx, diff_module)

    # 5. レポート、記録、索引を書く
    attempt = record_path = fix_count = None
    decision = None
    if recording:
        try:
            attempt, record_path, fix_count, decision = _save(state, ctx, link, moment, cwd, host, tools, options,
                                                              path_key, lint_module, diff_module)
        except OSError as error:
            recording, write_problem = False, _write_problem(state, error)
    if not recording:
        decision = _decide(ctx, False, problem=write_problem)
    status, line, following, token = decision

    # 6. 出力する（3.5）。意味が変わる恐れを出す検査が最後まで動かなかったときは、件数を null にする（agent 4）
    complete = ctx.risks_complete()
    if args.json:
        diff_result = None
        if ctx.diff_result is not None:
            diff_result = dict(ctx.diff_result, meaning_risks=ctx.diff_risks)
        result = OrderedDict((
            ("format", "yomiyasu-check-result"), ("format_version", RESULT_FORMAT_VERSION), ("tool_version", __version__),
            ("command", "run"), ("status", status), ("status_line", token), ("message", line), ("next", following),
            ("run_id", link["run_id"] if recording else None), ("attempt", attempt), ("fix_count", fix_count),
            ("mode", ctx.mode), ("record_path", record_path), ("fail_on_hit", bool(ctx.fail_on_hits)),
            ("meaning_risk_count", len(ctx.risks) if complete else None),
            ("fail_on_meaning_risk_count", diff_module.fail_on_count(ctx.risks) if complete else None),
            ("lint", ctx.lint_result), ("diff", diff_result), ("materials", ctx.materials_result)))
        print(json.dumps(result, ensure_ascii=True, indent=1))
    else:
        if recording:
            record_line = "記録: " + record_path
        else:
            record_line = "記録: なし（{}）".format("--no-record" if ctx.no_record else write_problem)
        sections = _sections(ctx, lint_module, diff_module)
        text = "\n".join([line, token, _summary_line(ctx), _DISCLAIMER, record_line]) + "\n\n"
        if sections:
            text += "\n\n".join(sections) + "\n\n"
        print(text + line + "\n" + token)
    if status == "partial":
        # 0.4: 終了コード3のときは標準エラーにも出す（止まった検査と、子の標準エラーの先頭）
        _error("yomiyasu_check.py: " + line)
        for name, entry in ctx.entries.items():
            if entry["status"] != "ran":
                _error("{}: {}".format(name, entry["error"] or entry["status"]))
                if entry["stderr"]:
                    _error(entry["stderr"].rstrip("\n"))
    if sys.stdout is not None:
        sys.stdout.flush()
    if status == "partial":
        return 3
    return 1 if ctx.fail_on_hits else 0


# ---- verify（3.9。読むだけで、何も書かない。--replay なしでは lint と diff を読み込まない）----

_VERIFY_LINES = {
    "executed": "この最終稿に必要な検査（{}）を実行した記録があり、最終稿のハッシュが記録と合いました。"
                "合格の判定ではありません。完了報告にこの出力の2行目を写してください。",
    "no_record": "この最終稿の検査記録がありません。yomiyasu_check.py run を実行してください。"
                 "実行できないときは、完了報告に実行しなかった検査として書いてください。",
    "final_changed": "最終稿が、最後に検査した本文と違います。本文を変えたなら yomiyasu_check.py run をもう一度実行し、"
                     "そのあと verify を実行してください。",
    "wrong_file": "この実行IDの記録は別のファイルのものです。この最終稿で yomiyasu_check.py run を実行してください。",
    "other_source": "記録の原文が、指定した原文と違います。正しい原文で yomiyasu_check.py run を実行してください。",
    "ambiguous": "同じ最終稿に、別の原文で作った記録が複数あります。--run-id か --source を付けて verify を実行してください。",
    "invalid_record": "記録の形が正しくありません（手で書いた記録や壊れた記録は使えません）。"
                      "yomiyasu_check.py run を実行してください。",
    "stale_record": "指定した時刻より前の記録です。yomiyasu_check.py run をもう一度実行してください。",
    "incomplete": "記録に {} の結果がありません。yomiyasu_check.py run をもう一度実行してください。",
    "tool_changed": "記録のあとで検査スクリプトが変わりました。yomiyasu_check.py run をもう一度実行してください。",
    "not_reproducible": "記録のレポートを今のスクリプトで作り直せません。yomiyasu_check.py run をもう一度実行してください。",
}
# --replay の作り直しが時間切れのとき（状態は incomplete。3.9 の10）。記録が欠けたわけではないので、別の文にする
_REPLAY_TIMEOUT_LINE = ("記録のレポートを作り直す途中で時間切れになりました（{}）。--timeout を長くして verify --replay を"
                        "もう一度実行してください。")
_LINE_ENDINGS_NOTE = "改行コードだけが違います（git の autocrlf やエディタの設定で変わることがあります）。"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_INDEX_ENTRY = re.compile(r"^(.+)\.([0-9]+)$")
_SINCE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:[.,][0-9]+)?"
                    r"([Zz]|[+-][0-9]{2}:?[0-9]{2})$")
_CHECK_NAMES = ("lint", "diff", "materials")
_EOLS = ("lf", "crlf", "cr", "mixed", "none")
# 3.7 の必須のキー（記録、Input、Check）
_RECORD_KEYS = ("format", "format_version", "run_id", "attempt", "fix_count", "previous", "created_at", "mode", "cwd",
                "host", "skill", "tools", "python", "inputs", "options", "required_checks", "checks",
                "materials_summary", "result", "record_digest")
_INPUT_KEYS = ("role", "index", "path", "via", "bytes", "sha256", "text_sha256", "bom", "eol", "snapshot")
_CHECK_KEYS = ("name", "status", "exit_code", "duration_ms", "target", "report", "report_sha256", "text", "text_sha256",
               "summary", "stderr", "error")


def _since(raw):
    """--since の時刻（時差つきの ISO 8601）。(UTC の時刻 or None, None) か (None, 誤りの文)。

    秒より細かい部分は切り捨てる。記録の created_at は秒までなので、同じ秒に作った記録を古いとみなさない。"""
    if raw is None:
        return None, None
    problem = ("--since には時差つきの ISO 8601 の時刻を渡してください（例 2026-10-13T01:45:00Z、"
               "2026-10-13T10:45:00+09:00）: {}".format(raw if raw.strip() else "（空）"))
    match = _SINCE.match(raw.strip())
    if not match:
        return None, problem
    zone = match.group(7)
    minutes = 0
    if zone not in ("Z", "z"):
        digits = zone[1:].replace(":", "")
        if int(digits[2:]) >= 60:
            return None, problem
        minutes = int(digits[:2]) * 60 + int(digits[2:])
        if zone[0] == "-":
            minutes = -minutes
    try:
        moment = datetime.datetime(*[int(match.group(number)) for number in range(1, 7)],
                                   tzinfo=datetime.timezone(datetime.timedelta(minutes=minutes)))
        return moment.astimezone(datetime.timezone.utc), None
    except (ValueError, OverflowError):
        return None, problem


class _Target(object):
    """verify で照らす入力（最終稿、--source）。バイト列のハッシュと、UTF-8 として読めれば本文のハッシュ。"""

    def __init__(self, path, data):
        self.path = path                       # 絶対パス。標準入力なら None
        self.via = "file" if path is not None else "stdin"
        self.data = data
        self.sha256 = _sha256(data)
        try:
            text, _ = decode_source(data)
        except UnicodeDecodeError:
            text = None
        self.text_sha256 = _text_sha256(text) if text is not None else None

    def token(self):
        """状態の行の final=。ファイルはバイト列の SHA-256、標準入力は本文のハッシュ（3.9 の2、10.4 S14）。"""
        if self.via == "stdin":
            return "text-sha256:" + self.text_sha256[:12]
        return "sha256:" + self.sha256[:12]

    def as_json(self):
        return OrderedDict((("path", self.path), ("via", self.via), ("sha256", self.sha256),
                            ("text_sha256", self.text_sha256)))


def _read_target(given, stdin_data):
    """verify の --final と --source を読む。(_Target, None) か (None, 誤りの文)。"""
    if given == "-":
        target = _Target(None, stdin_data)
        if target.text_sha256 is None:
            return None, "Error reading stdin: UTF-8 として読めません"
        return target, None
    try:
        with open(given, "rb") as handle:
            data = handle.read()
    except (OSError, ValueError) as error:
        reason = getattr(error, "strerror", None) or error
        return None, "Error opening file {}: ファイルを開けません（{}）".format(given, reason)
    return _Target(_abspath(given), data), None


class _Found(object):
    """見つけた記録1つ（実行ID と回はファイルの場所から取る）。"""

    def __init__(self, state, run_id, attempt):
        self.run_id = run_id
        self.attempt = attempt
        self.path = os.path.join(state, "runs", run_id, "attempt-{}.json".format(attempt))
        self.status, self.record = _read_record_status(self.path)
        try:
            self.made = os.stat(self.path).st_mtime_ns
        except OSError:
            self.made = 0

    def order(self):
        """「最新」の並べ方（記録の created_at、書いた時刻、回）。"""
        created = (self.record or {}).get("created_at")
        return (created if isinstance(created, str) and _parse_iso(created) else "", self.made, self.attempt)

    def final(self):
        inputs = (self.record or {}).get("inputs")
        final = inputs.get("final") if isinstance(inputs, dict) else None
        return final if isinstance(final, dict) else None


def _index_found(state, kind, key):
    """index/by-final/<sha256>/ か index/by-text/<text_sha256>/ が指す記録（ファイルがないものは飛ばす。questions.md の15）。"""
    try:
        names = os.listdir(os.path.join(state, "index", kind, key))
    except OSError:
        return []
    found = []
    for name in sorted(names):
        match = _INDEX_ENTRY.match(name)  # 実行IDに「.」が入りうるので、最後の「.」で分ける
        if not match or not _RUN_ID.match(match.group(1)):
            continue
        item = _Found(state, match.group(1), int(match.group(2)))
        if item.status != "missing":
            found.append(item)
    return found


def _origin(record):
    """記録の原文（新規作成では資料の集まり）。曖昧さを決めるのに使う。形がわからなければ None。"""
    if not isinstance(record, dict) or not isinstance(record.get("inputs"), dict):
        return None
    mode, inputs = record.get("mode"), record["inputs"]
    if mode == "rewrite":
        source = inputs.get("source")
        if isinstance(source, dict) and isinstance(source.get("text_sha256"), str):
            return ("rewrite", source["text_sha256"])
        return None
    if mode == "compose":
        materials = inputs.get("materials")
        if (isinstance(materials, list) and materials
                and all(isinstance(item, dict) and isinstance(item.get("text_sha256"), str) for item in materials)):
            return ("compose",) + tuple(sorted(item["text_sha256"] for item in materials))
    return None


def _final_matches(final_record, final):
    """記録の最終稿と、今の最終稿のハッシュが同じか（ファイルはバイト列、標準入力は本文のハッシュ）。"""
    if not isinstance(final_record, dict):
        return False
    if final.via == "file":
        return final_record.get("sha256") == final.sha256
    return final.text_sha256 is not None and final_record.get("text_sha256") == final.text_sha256


def _source_matches(record, source):
    """記録の原文と --source が同じか。どちらもファイルならバイト列、標準入力が絡むなら本文のハッシュで比べる（10.3 A1）。"""
    inputs = record.get("inputs") if isinstance(record, dict) else None
    recorded = inputs.get("source") if isinstance(inputs, dict) else None
    if not isinstance(recorded, dict):
        return False
    if recorded.get("via") == "file" and source.via == "file":
        return recorded.get("sha256") == source.sha256
    return source.text_sha256 is not None and recorded.get("text_sha256") == source.text_sha256


def _expected_token(final_record, final):
    """final_changed の expected=。今の最終稿と同じ種類のハッシュで出す（標準入力は text-sha256:。10.4 S14）。"""
    if final.via == "stdin":
        value = final_record.get("text_sha256")
        return "text-sha256:" + value[:12] if isinstance(value, str) and _HEX64.match(value) else None
    value = final_record.get("sha256")
    return "sha256:" + value[:12] if isinstance(value, str) and _HEX64.match(value) else None


def _normalize_eol(data):
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _only_line_endings(state, final_record, final):
    """記録の最終稿の写しと、今の最終稿が、改行コードだけ違うか（両方を LF にそろえると同じ。3.9 の注記）。"""
    if final.via != "file":
        return False  # 標準入力は本文のハッシュで照らすので、改行コードの違いでは食い違わない
    value = final_record.get("sha256")
    if not isinstance(value, str) or not _HEX64.match(value):
        return False
    try:
        with open(os.path.join(state, "inputs", value + ".bin"), "rb") as handle:
            recorded = handle.read()
    except OSError:
        return False
    return recorded != final.data and _normalize_eol(recorded) == _normalize_eol(final.data)


def _same_final_place(final_record, final):
    """記録の最終稿と今の最終稿が同じ場所か（パスが null どうしは同じとみなす。10.3 A1）。"""
    recorded = final_record.get("path")
    if final.path is None or recorded is None:
        return final.path is None and recorded is None
    return isinstance(recorded, str) and _same_path(recorded, final.path)


def _find(state, final, run_id, source):
    """3.9 の3。記録を探す。("found", _Found) か ("ambiguous", [実行ID]) か ("final_changed" | "wrong_file", _Found)
    か ("invalid", _Found) か ("no_record", None)。"""
    if run_id is not None:
        run_dir = os.path.join(state, "runs", run_id)
        items = [_Found(state, run_id, number) for number in _attempt_numbers(run_dir)]
        items = [item for item in items if item.status != "missing"]
        if not items:
            return "no_record", None
        matching = [item for item in items if item.status == "ok" and _final_matches(item.final(), final)]
        if matching:
            return "found", max(matching, key=lambda item: item.attempt)
        readable = [item for item in items if item.status == "ok"]
        latest = max(readable or items, key=lambda item: item.attempt)
        if latest.final() is None:
            return "invalid", latest
        return ("final_changed" if _same_final_place(latest.final(), final) else "wrong_file"), latest

    kind, key = ("by-text", final.text_sha256) if final.via == "stdin" else ("by-final", final.sha256)
    candidates = _index_found(state, kind, key)
    if candidates:
        known = [item for item in candidates if item.status == "ok" and _origin(item.record) is not None]
        pool = known or candidates
        if source is not None:
            narrowed = [item for item in pool if _source_matches(item.record, source)]
            pool = narrowed or pool  # 絞れなければ最新の記録を使い、3.9 の5 で other_source にする
        origins = set(_origin(item.record) for item in pool)
        if len(origins) > 1:
            ordered = sorted(pool, key=lambda item: item.order(), reverse=True)
            run_ids = []
            for item in ordered:
                if item.run_id not in run_ids:
                    run_ids.append(item.run_id)
            return "ambiguous", run_ids
        return "found", max(pool, key=lambda item: item.order())

    # ハッシュで見つからないとき、同じ場所の記録があれば final_changed（3.9 の3、10.3 A1）
    if final.via == "file":
        place = os.path.normcase(os.path.realpath(final.path))
    elif source is not None and source.text_sha256 is not None:
        place = "stdin:" + source.text_sha256
    else:
        return "no_record", None
    for found_id, number in _by_path_entries(state, _sha256(place.encode("utf-8", "surrogateescape"))):
        item = _Found(state, found_id, number)
        if item.status == "ok" and item.final() is not None:
            if _final_matches(item.final(), final):
                return "found", item  # 最終稿の索引だけがないとき
            return "final_changed", item
    return "no_record", None


def _record_shape(record):
    """3.9 の4: 3.7 の必須のキーと型。食い違ったキーの名前の並び（空なら形は合っている）。"""
    wrong = []

    def need(condition, name):
        if not condition:
            wrong.append(name)
        return condition

    def is_int(value, low=0):
        return type(value) is int and value >= low

    def is_text(value):
        return isinstance(value, str)

    def text_or_null(value):
        return value is None or isinstance(value, str)

    def is_hex(value):
        return isinstance(value, str) and bool(_HEX64.match(value))

    def check_input(item, name, role, index):
        if not need(isinstance(item, dict) and all(key in item for key in _INPUT_KEYS), name):
            return
        need(item.get("role") == role, name + ".role")
        need(item.get("index") == index and type(item.get("index")) is int, name + ".index")
        via = item.get("via")
        need(via in ("file", "stdin"), name + ".via")
        need((item.get("path") is None) == (via == "stdin") and text_or_null(item.get("path")), name + ".path")
        need(is_int(item.get("bytes")), name + ".bytes")
        need(is_hex(item.get("sha256")), name + ".sha256")
        need(is_hex(item.get("text_sha256")), name + ".text_sha256")
        need(type(item.get("bom")) is bool, name + ".bom")
        need(item.get("eol") in _EOLS, name + ".eol")
        need(item.get("snapshot") == "inputs/{}.bin".format(item.get("sha256")), name + ".snapshot")

    for key in _RECORD_KEYS:
        need(key in record, key)
    if wrong:
        return wrong
    need(is_text(record.get("run_id")) and bool(_RUN_ID.match(record["run_id"])), "run_id")
    need(is_int(record.get("attempt"), 1), "attempt")
    need(is_int(record.get("fix_count")), "fix_count")
    previous = record.get("previous")
    need(previous is None or (isinstance(previous, dict) and is_int(previous.get("attempt"), 1)
                              and text_or_null(previous.get("final_sha256"))), "previous")
    need(is_text(record.get("created_at")) and _parse_iso(record["created_at"]) is not None, "created_at")
    mode = record.get("mode")
    need(mode in ("rewrite", "compose"), "mode")
    need(is_text(record.get("cwd")), "cwd")
    host = record.get("host")
    need(isinstance(host, dict) and all(key in host and text_or_null(host[key])
                                        for key in ("session", "codex_thread_id", "armed_by")), "host")
    skill = record.get("skill")
    need(isinstance(skill, dict) and type(skill.get("found")) is bool
         and all(key in skill and text_or_null(skill[key]) for key in ("dir", "skill_md_sha256", "version")), "skill")
    tools = record.get("tools")
    need(isinstance(tools, dict) and all(
        isinstance(tools.get(name), dict) and text_or_null(tools[name].get("version"))
        and text_or_null(tools[name].get("sha256")) for name in _TOOL_NAMES), "tools")
    python = record.get("python")
    need(isinstance(python, dict) and is_text(python.get("version")) and is_text(python.get("implementation")),
         "python")
    inputs = record.get("inputs")
    if need(isinstance(inputs, dict) and all(key in inputs for key in ("source", "materials", "final")), "inputs"):
        if mode == "rewrite" or inputs["source"] is not None:
            check_input(inputs["source"], "inputs.source", "source", 0)
        materials = inputs["materials"]
        if need(isinstance(materials, list) and (mode != "compose" or bool(materials)), "inputs.materials"):
            for number, item in enumerate(materials, 1):
                check_input(item, "inputs.materials[{}]".format(number), "material", number)
        check_input(inputs["final"], "inputs.final", "final", 0)
        if mode == "compose":
            need(inputs["source"] is None, "inputs.source")
    options = record.get("options")
    need(isinstance(options, dict) and text_or_null(options.get("stance"))
         and isinstance(options.get("fail_on"), list) and all(is_text(value) for value in options["fail_on"])
         and type(options.get("timeout")) in (int, float), "options")
    required = record.get("required_checks")
    need(isinstance(required, list) and all(name in _CHECK_NAMES for name in required)
         and len(set(required)) == len(required), "required_checks")
    checks = record.get("checks")
    if need(isinstance(checks, list), "checks"):
        names = []
        for number, entry in enumerate(checks):
            name = "checks[{}]".format(number)
            if not need(isinstance(entry, dict) and all(key in entry for key in _CHECK_KEYS), name):
                continue
            names.append(entry.get("name"))
            need(entry.get("name") in _CHECK_NAMES, name + ".name")
            need(entry.get("status") in ("ran", "error", "timeout"), name + ".status")
            need(entry.get("exit_code") is None or type(entry.get("exit_code")) is int, name + ".exit_code")
            need(is_int(entry.get("duration_ms")), name + ".duration_ms")
            need(isinstance(entry.get("target"), dict), name + ".target")
            for key in ("report", "text", "error"):
                need(text_or_null(entry[key]), "{}.{}".format(name, key))
            for key in ("report_sha256", "text_sha256"):
                need(entry[key] is None or is_hex(entry[key]), "{}.{}".format(name, key))
            need(entry["summary"] is None or isinstance(entry["summary"], dict), name + ".summary")
            need(is_text(entry.get("stderr")), name + ".stderr")
        need(len(set(names)) == len(names), "checks.name")
        # モードと資料の有無で決まる検査（3.3 の表）の外にある項目は、run が書かない形。新規作成の記録に diff の項目が
        # あると、--replay が原文のない記録の diff を作り直そうとして落ちる（反証レビュー spec F6、robust R12）
        if mode in ("rewrite", "compose") and isinstance(inputs, dict) and isinstance(inputs.get("materials"), list):
            allowed = _mode_checks(mode, inputs["materials"])
            need(all(name in allowed for name in names), "checks.name")
            need(not isinstance(required, list) or all(name in allowed for name in required), "required_checks")
    summary = record["materials_summary"]
    need(summary is None or isinstance(summary, dict), "materials_summary")
    result = record.get("result")
    need(isinstance(result, dict) and result.get("status") in ("executed", "partial") and is_text(result.get("token"))
         and is_text(result.get("next")) and type(result.get("fail_on_hit")) is bool
         and is_int(result.get("meaning_risk_count")) and type(result.get("final_unchanged_during_run")) is bool
         and isinstance(result.get("not_judged"), list), "result")
    need(is_text(record.get("record_digest")), "record_digest")
    return wrong


def _required_for(record):
    """必要な検査（3.3 の表。モードと資料の有無で決まる）と、記録の required_checks を合わせたもの。"""
    expected = _mode_checks(record["mode"], record["inputs"]["materials"])
    return expected + [name for name in record["required_checks"] if name not in expected]


def _expected_target(record, name):
    """各検査の target に入るはずのハッシュ（3.7。run の _run_checks と同じ形）。"""
    inputs = record["inputs"]
    final = inputs["final"]["sha256"]
    source = inputs["source"]["sha256"] if isinstance(inputs["source"], dict) else None
    if name == "lint":
        return {"final": final}
    if name == "diff":
        return {"source": source, "final": final}
    target = {"materials": [item["sha256"] for item in inputs["materials"]], "final": final}
    if source is not None:
        target["source"] = source
    return target


class _Material(object):
    """--replay で照合の .txt を作り直すときの資料（_materials_lines が text を読む）。"""

    def __init__(self, text):
        self.text = text


class _ReplayError(Exception):
    """--replay で子プロセスを起動できない、待てない、またはシグナルで止まった。記録の食い違いではないので、
    not_reproducible にせず、verify の内部の誤り（終了コード3）にする（3.10。反証レビュー spec F1、robust R2）。"""


def _replay(state, record, timeout):
    """3.9 の10。写しに対して記録と同じ引数で lint と diff を子プロセスで動かし、照合はプロセスの中で作り直して、
    レポート（.json と .txt）のハッシュを記録と比べる。[(問題のコード, 詳しく)] と replay の値を返す。
    子を動かせなかったときは _ReplayError を出す。"""
    lint_module, diff_module = _lint_module(), _diff_module()
    inputs = record["inputs"]
    entries = OrderedDict((entry["name"], entry) for entry in record["checks"] if entry["status"] == "ran")

    def snapshot(item):
        return os.path.join(state, "inputs", item["sha256"] + ".bin")

    commands = OrderedDict()
    if "lint" in entries:
        commands["lint"] = [sys.executable, "-B", os.path.join(_HERE, "yomiyasu_lint.py"), "--json",
                            snapshot(inputs["final"])]
    if "diff" in entries:
        command = [sys.executable, "-B", os.path.join(_HERE, "yomiyasu_diff.py"), "--json"]
        if record["options"].get("stance") is not None:
            command += ["--stance", record["options"]["stance"]]
        commands["diff"] = command + [snapshot(inputs["source"]), snapshot(inputs["final"])]
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    children = _Children(timeout, environment)
    problems = []
    rebuilt = {}
    try:
        for name, command in commands.items():
            children.start(name, command)
        if "materials" in entries:
            try:
                def text_of(item):
                    with open(snapshot(item), "rb") as handle:
                        return decode_source(handle.read())[0]
                source_text = text_of(inputs["source"]) if isinstance(inputs["source"], dict) else None
                material_texts = [text_of(item) for item in inputs["materials"]]
                final_text = text_of(inputs["final"])
                rebuilt["materials"] = (diff_module.ground(final_text, material_texts, source_text), material_texts)
            except Exception as error:  # 照合を作り直せない（写しが読めない、例外）
                problems.append(("replay_error", "materials: {}: {}".format(type(error).__name__, error)))
        results = children.wait()
    except BaseException:
        # 外から止められた（SIGTERM など）。動いている子を止めてから戻る
        children.stop()
        raise
    for name in commands:
        status, code, _, _, _, error = results[name]
        if status == "error" and (code is None or code < 0):
            # 起動できない、待てない（終了コードなし）、シグナルで止まった（負の終了コード）
            raise _ReplayError("{}: {}".format(name, error if code is None else "シグナル{}で止まりました".format(-code)))

    timed_out = []
    parsed = {}
    versions = {"lint": lint_module.LINT_FORMAT_VERSION, "diff": diff_module.DIFF_FORMAT_VERSION}
    for name in ("lint", "diff"):
        if name not in commands:
            continue
        status, code, stdout, stderr, elapsed, error = results[name]
        if status == "timeout":
            timed_out.append(name)
            continue
        if status != "ran":
            problems.append(("replay_error", "{}: {}".format(name, error)))
            continue
        if _sha256(stdout) != entries[name]["report_sha256"]:
            problems.append(("replay_mismatch", "{}.json".format(name)))
        value, problem = _parse_report(stdout, name, versions[name])
        if value is None:
            problems.append(("replay_error", "{}: {}".format(name, problem)))
            continue
        try:
            text = (lint_module.render_report(value) if name == "lint" else diff_module.report(value)) + "\n"
        except Exception as error:
            problems.append(("replay_error", "{}: 人が読む形を作れません（{}: {}）".format(name, type(error).__name__, error)))
            continue
        parsed[name] = value
        if _sha256(text.encode("utf-8")) != entries[name]["text_sha256"]:
            problems.append(("replay_mismatch", "{}.txt".format(name)))
    if "materials" in rebuilt:
        result, material_texts = rebuilt["materials"]
        data = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        if _sha256(data) != entries["materials"]["report_sha256"]:
            problems.append(("replay_mismatch", "materials.json"))
        if "diff" not in entries or "diff" in parsed:
            # 照合の .txt は diff の「元の文にない語」を使うので、diff を作り直せたときだけ比べる
            ctx = _Context()
            ctx.mode = record["mode"]
            ctx.materials = [_Material(text) for text in material_texts]
            ctx.diff_result = parsed.get("diff")
            ctx.materials_result = result
            text = _materials_text(ctx, diff_module) + "\n"
            if _sha256(text.encode("utf-8")) != entries["materials"]["text_sha256"]:
                problems.append(("replay_mismatch", "materials.txt"))
    for name in timed_out:
        problems.append(("replay_timeout", name))
    if any(code in ("replay_mismatch", "replay_error") for code, _ in problems):
        return problems, "mismatch"
    if timed_out:
        return problems, "timeout"
    return problems, "ok"


def _verify_record(state, found, final, source, since, replay, timeout):
    """3.9 の4〜11。見つけた記録を確かめる。(状態, [(コード, 詳しく)], replay の値, 形を確かめられたか)。
    最初に当てはまった状態を返し、見つかった食い違いはすべて problems に入れる。"""
    problems = []
    states = []

    def fail(state_name, code, detail):
        problems.append((code, detail))
        if state_name is not None:
            states.append(state_name)

    record = found.record
    if found.status != "ok":
        fail("invalid_record", "unreadable_record", "JSON のオブジェクトとして読めません")
        return "invalid_record", problems, "skipped", False
    if record.get("format") != "yomiyasu-check-record" or record.get("format_version") != RECORD_FORMAT_VERSION \
            or type(record.get("format_version")) is not int:
        fail("invalid_record", "record_format", "format と format_version が yomiyasu-check-record の形式{}ではありません"
             .format(RECORD_FORMAT_VERSION))
        return "invalid_record", problems, "skipped", False
    wrong = _record_shape(record)
    if wrong:
        fail("invalid_record", "record_shape", "キーか型が違います: " + ", ".join(wrong))
        return "invalid_record", problems, "skipped", False
    # 4. 場所、digest、最終稿のハッシュ
    if record["run_id"] != found.run_id or record["attempt"] != found.attempt:
        fail("invalid_record", "record_location", "run_id と attempt が記録のファイルの場所（{}、{}回目）と合いません".format(
            found.run_id, found.attempt))
    if record["record_digest"] != _record_digest(record):
        fail("invalid_record", "record_digest", "record_digest が記録の中身と合いません")
    if not _final_matches(record["inputs"]["final"], final):
        fail("invalid_record", "final_hash", "記録の inputs.final のハッシュが今の最終稿と合いません")
    trusted = not states
    # 5. 原文
    if source is not None and not _source_matches(record, source):
        fail("other_source", "other_source", "記録の原文と --source のハッシュが違います")
    # 6. 時刻
    if since is not None and _parse_iso(record["created_at"]) < since:
        fail("stale_record", "stale_record", "記録の created_at {} が --since より前です".format(record["created_at"]))
    # 7. 必要な検査がすべて ran で、target が inputs と同じか
    entries = dict((entry["name"], entry) for entry in record["checks"])
    missing = []
    for name in _required_for(record):
        entry = entries.get(name)
        if entry is None or entry["status"] != "ran":
            fail(None, "missing_check", name if entry is None else "{}（{}）".format(name, entry["status"]))
            missing.append(name)
        elif entry["target"] != _expected_target(record, name):
            fail(None, "check_target", "{} の target が inputs と違います".format(name))
            missing.append(name)
    if missing:
        states.append(("incomplete", missing))
    # 8. 写しとレポートのファイル
    run_part = "runs/{}/attempt-{}".format(found.run_id, found.attempt)
    inputs = record["inputs"]
    items = ([("source", inputs["source"])] if inputs["source"] is not None else []) \
        + [("material[{}]".format(item["index"]), item) for item in inputs["materials"]] + [("final", inputs["final"])]
    for label, item in items:
        try:
            ok = _file_sha256(os.path.join(state, "inputs", item["sha256"] + ".bin")) == item["sha256"]
        except OSError:
            ok = False
        if not ok:
            fail("invalid_record", "snapshot", "{} の写し {} がないか、ハッシュが合いません".format(label, item["snapshot"]))
    for name, entry in entries.items():
        if entry["status"] != "ran":
            continue
        for key, suffix, digest in (("report", ".json", "report_sha256"), ("text", ".txt", "text_sha256")):
            expected = "{}.{}{}".format(run_part, name, suffix)
            if entry[key] != expected:
                fail("invalid_record", "report", "{} の {} が {} ではありません".format(name, key, expected))
                continue
            try:
                ok = _file_sha256(os.path.join(state, *expected.split("/"))) == entry[digest]
            except OSError:
                ok = False
            if not ok:
                fail("invalid_record", "report", "{} がないか、ハッシュが記録と合いません".format(expected))
    # 9. スクリプトと SKILL.md
    current = _tool_versions()
    for name in _TOOL_NAMES:
        if current[name]["sha256"] != record["tools"][name]["sha256"]:
            fail("tool_changed", "tool_changed", name)
    if _skill_info()["skill_md_sha256"] != record["skill"]["skill_md_sha256"]:
        fail(None, "skill_changed", "SKILL.md のハッシュが記録と違います")
    # 10. 作り直し（ここまでで食い違いがないときだけ）
    replayed = "skipped"
    if replay and not states:
        found_problems, replayed = _replay(state, record, timeout)
        for code, detail in found_problems:
            problems.append((code, detail))
        if replayed == "mismatch":
            states.append("not_reproducible")
        elif replayed == "timeout":
            states.append(("replay_timeout", [detail for code, detail in found_problems if code == "replay_timeout"]))
    if not states:
        return "executed", problems, replayed, trusted
    return states[0], problems, replayed, trusted


def _verify(args, parser):
    # 1. 引数を確かめ、最終稿のハッシュを先に計算する（10.4 S10）。誤りなら2で、何も書かない
    if args.state_dir is not None and not args.state_dir.strip():
        parser.error("--state-dir に空の値は使えません")
    if args.final == "-" and args.source == "-":
        parser.error("標準入力（-）は1か所だけに使えます")
    if args.run_id is not None and not _RUN_ID.match(args.run_id):
        _error("--run-id に使えない値です: {}。英数字で始まり、英数字と「.」「_」「-」だけの64字までにしてください。".format(
            args.run_id if args.run_id.strip() else "（空）"))
        return 2
    since, problem = _since(args.since)
    if problem:
        _error(problem)
        return 2
    timeout, problem = _timeout(args.timeout)
    if problem:
        _error(problem)
        return 2
    stdin_data = None
    if "-" in (args.final, args.source):
        stdin_data, problem = _read_stdin_bytes()
        if problem:
            _error(problem)
            return 2
    final, problem = _read_target(args.final, stdin_data)
    if problem:
        _error(problem)
        return 2
    source = None
    if args.source is not None:
        source, problem = _read_target(args.source, stdin_data)
        if problem:
            _error(problem)
            return 2

    # 2. 状態フォルダがなければ no_record（フォルダは作らない）
    state = _state_dir(args.state_dir)
    found = None
    run_ids = []
    expected = None
    problems = []
    replayed = "skipped"
    trusted = False
    if not os.path.isdir(state):
        status = "no_record"
        problems.append(("no_state_dir", "状態フォルダがありません: " + state))
    else:
        # 3. 記録を探す
        kind, value = _find(state, final, args.run_id, source)
        if kind == "no_record":
            status = "no_record"
            problems.append(("no_record", "この最終稿の記録が見つかりません"))
        elif kind == "ambiguous":
            status, run_ids = "ambiguous", value
            problems.append(("ambiguous", "原文の違う実行: " + ", ".join(run_ids)))
        elif kind in ("final_changed", "wrong_file"):
            status, found = kind, value
            expected = _expected_token(found.final(), final) if kind == "final_changed" else None
            problems.append((kind, "記録 {} の最終稿は {}".format(
                found.path, _expected_token(found.final(), final) or "（ハッシュなし）")))
            if kind == "final_changed" and _only_line_endings(state, found.final(), final):
                problems.append(("only_line_endings_differ", "両方の改行を LF にそろえると同じです"))
        else:
            found = value
            try:
                status, found_problems, replayed, trusted = _verify_record(
                    state, found, final, source, since, args.replay, timeout)
            except _ReplayError as error:
                # 子を動かせなかったのは記録の食い違いではない。状態を決めず、内部の誤りとして3で終える（3.10）
                _error("yomiyasu_check.py: 内部エラー: --replay で検査を動かせません（{}）。記録の食い違いではありません。"
                       "子プロセスを動かせる環境で verify --replay をもう一度実行してください。".format(error))
                return 3
            problems.extend(found_problems)
            if trusted and final.via == "file":
                recorded = found.record["inputs"]["final"].get("path")
                if recorded is not None and not _same_path(recorded, final.path):
                    problems.append(("final_path_differs", "記録の最終稿のパス: " + recorded))

    # 4. 出力する（3行。1行目に次の行動、2行目に状態の行、3行目に記録のパス）
    # 記録の mode、checks、meaning_risk を出すのは、記録の形と digest を確かめられたときだけ。
    # meaning_risk は、意味が変わる恐れを出す検査（diff、資料との照合）がすべて ran のときだけ出す（0件と読ませない。agent 4）
    # 人が読む1行目の検査名は 5.2 の語にする（materials は「資料との照合」。agent 15）
    record = found.record if found is not None and found.status == "ok" else None
    shown = trusted
    meaning = None
    if shown:
        statuses = dict((entry["name"], entry["status"]) for entry in record["checks"])
        if all(statuses.get(name) == "ran" for name in _required_for(record) if name in _RISK_CHECKS):
            meaning = record["result"]["meaning_risk_count"]
    if isinstance(status, tuple):
        reason, names = status
        labels = "、".join(_label(name) for name in names)
        if reason == "incomplete":
            status, line = "incomplete", _VERIFY_LINES["incomplete"].format(labels)
        else:
            status, line = "incomplete", _REPLAY_TIMEOUT_LINE.format(labels)
    elif status == "executed":
        line = _VERIFY_LINES["executed"].format("、".join(_label(name) for name in _required_for(record)))
    else:
        line = _VERIFY_LINES[status]
        if status == "final_changed" and any(code == "only_line_endings_differ" for code, _ in problems):
            line += _LINE_ENDINGS_NOTE
    required = _required_for(record) if shown else None
    replay_field = None
    if status == "executed" or status == "not_reproducible" or replayed == "timeout":
        replay_field = replayed
    token = _status_line(
        status, "verify", found.run_id if found is not None else None, found.attempt if found is not None else None,
        final.token(), expected=expected, mode=record["mode"] if shown else None,
        checks=",".join(required) if shown else None,
        meaning_risk=meaning, replay=replay_field)
    if found is not None:
        record_line = "記録: " + found.path
    elif run_ids:
        record_line = "記録: 複数あります（実行ID {}）".format("、".join(run_ids))
    else:
        record_line = "記録: なし"
    if args.json:
        final_record = found.final() if found is not None else None
        recorded_sha = final_record.get("sha256") if isinstance(final_record, dict) else None
        checks = None
        if shown:
            entries = dict((entry["name"], entry["status"]) for entry in record["checks"])
            checks = OrderedDict((name, entries.get(name, "missing")) for name in required)
        result = OrderedDict((
            ("format", "yomiyasu-check-result"), ("format_version", RESULT_FORMAT_VERSION), ("tool_version", __version__),
            ("command", "verify"), ("status", status), ("status_line", token), ("message", line),
            ("run_id", found.run_id if found is not None else None),
            ("attempt", found.attempt if found is not None else None),
            ("record_path", found.path if found is not None else None), ("final", final.as_json()),
            ("record_final_sha256", recorded_sha if isinstance(recorded_sha, str) else None),
            ("mode", record["mode"] if shown else None), ("required_checks", required), ("checks", checks),
            ("meaning_risk_count", meaning), ("replay", replayed),
            ("problems", [OrderedDict((("code", code), ("detail", detail))) for code, detail in problems])))
        print(json.dumps(result, ensure_ascii=True, indent=1))
    else:
        print("\n".join([line, token, record_line]))
    return 0 if status == "executed" else 1


# ---- CLI ----

_DESCRIPTION = ("最終稿に lint、原文と最終稿に diff（新規作成では資料との照合）をまとめて実行し、記録を残します。"
                "結果は『検査を実行した』で、意味の保持や読みやすさの合格ではありません。")
_RECORD_NOTE = ("記録はこのコマンドだけが作ります。同じ権限で原稿と記録の両方を書き換えられる環境では、記録は実行漏れを"
                "見つけるためのもので、改ざんの防止や人の承認の証明にはなりません。")
_EXIT_CODES = """終了コード:
  0  run: 検査を最後まで実行し、--fail-on の条件に当たらなかった（状態 executed か unrecorded。候補の有無によらない）。verify: 記録と照合が合った（executed）。-h と --version も0
  1  run: --fail-on の条件に当たった（記録は残す）。verify: 記録がない、または記録と合わない（理由は2行目の状態の行と --json の problems）
  2  使い方か入力の誤り（ファイルを開けない、UTF-8 として読めない、区切りの誤り、使えない値、原文と最終稿が同じファイル、別の原文の実行ID）。何も書かない（状態 not_run）
  3  検査の一部を実行できなかった（lint か diff が内部の誤りか時間切れで終わらなかった、途中で最終稿が変わった。状態 partial）か、check の予期しない内部の誤り、出力先が閉じられて結果を最後まで書けなかった"""
_USAGE = ("yomiyasu_check.py run --final 最終稿 (--source 原文 | --material 資料) [オプション]\n"
          "       yomiyasu_check.py run --stdin [オプション]\n"
          "       yomiyasu_check.py verify --final 最終稿|- [オプション]\n"
          "       yomiyasu_check.py --version")
_RUN_USAGE = ("yomiyasu_check.py run --final 最終稿 (--source 原文 | --material 資料) [--material 資料 …]\n"
              "           [--stance 立場] [--fail-on meaning-risk|warn|error …] [--timeout 秒]\n"
              "           [--run-id ID | --new-run] [--session ID] [--state-dir DIR] [--no-record] [--json]\n"
              "       yomiyasu_check.py run --stdin [上と同じオプション]")
_VERIFY_USAGE = ("yomiyasu_check.py verify --final 最終稿|- [--run-id ID] [--source 原文] [--since ISO8601]\n"
                 "           [--replay] [--timeout 秒] [--state-dir DIR] [--json]")
_FAIL_ON_HELP = ("指定した条件に当たれば、記録を残したうえで終了コード1で終わります。何度でも、カンマ区切りでも指定できます。"
                 "meaning-risk: 意味が変わる恐れのうち、数値、否定、主語と目的語の入れ替え、文の種類（問いと平叙、文の種類の印）の"
                 "変化と、資料にない数値。コード・URL・引用など変えない箇所の変化と、資料にない名前は数えません。"
                 "warn: lint の warn か error の候補。error: lint の error の候補。"
                 "条件に当たらなくても、意味が同じだという証明にはなりません。")


class _ArgumentParser(argparse.ArgumentParser):
    # argparse は、書く先の流れがない（None の）とき、もう一方の流れに書く。3.10 までは標準エラーがないと
    # 使い方の誤りで AttributeError になる。pythonw や 2>&- のときも、書く先がなければ何も書かずに同じ終了コードで終える。

    def error(self, message):
        stream = sys.stderr
        if stream is None:
            self.exit(2)
        # 使い方の行と argparse の英語の行のあとに、日本語の案内を1行足す（10.5 M2。lint、diff と同じ形）
        _use_utf8(stream, errors="backslashreplace")
        self.print_usage(stream)
        stream.write("{}: error: {}\n".format(self.prog, message))
        stream.write("引数の誤りです。{} -h で使い方を確かめてください。\n".format(self.prog))
        self.exit(2)

    def print_help(self, file=None):
        if file is None:
            file = sys.stdout
        if file is not None:
            super().print_help(file)


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = "使い方: "
        return super().add_usage(usage, actions, groups, prefix)


def _build_parser():
    """(全体の parser, run の parser, verify の parser)。省略形は受けない（10.7 の allow_abbrev=False）。"""
    parser = _ArgumentParser(prog="yomiyasu_check.py", usage=_USAGE, description=_DESCRIPTION + "\n" + _RECORD_NOTE,
                             epilog=_EXIT_CODES, formatter_class=_HelpFormatter, add_help=False, allow_abbrev=False)
    top = parser.add_argument_group("オプション")
    top.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
    top.add_argument("--version", action="store_true", help="版を表示して終わります。")
    commands = parser.add_subparsers(dest="command", title="サブコマンド（省くと run）", metavar="{run,verify}")

    run = commands.add_parser(
        "run", prog="yomiyasu_check.py run", usage=_RUN_USAGE, epilog=_EXIT_CODES, formatter_class=_HelpFormatter,
        add_help=False, allow_abbrev=False, help="検査を実行して記録を残します。最終稿ができたら1回、直したらもう一度実行します。",
        description=(_DESCRIPTION + "\n--source があれば推敲（lint と diff。資料があれば資料との照合も）、"
                     "なくて --material があれば新規作成（lint と資料との照合）です。\n" + _RECORD_NOTE))
    inputs = run.add_argument_group("入力")
    inputs.add_argument("--final", action="append", metavar="最終稿",
                        help="検査する最終稿のファイル（UTF-8）。- を渡すと標準入力を読みます。")
    inputs.add_argument("--source", "--original", dest="source", action="append", metavar="原文",
                        help="推敲で、書き直す前の原文のファイル。最終稿と別のファイルにしてください。")
    inputs.add_argument("--material", "--materials", dest="materials", action="append", metavar="資料",
                        help="提供された資料のファイル。何度でも指定できます。最終稿の数値、名前、語、確度の語を資料と照らします。")
    inputs.add_argument("--stdin", action="store_true",
                        help="ファイルを作らない対話のため、原文（か資料）と最終稿を標準入力から読みます。"
                             "行全体が <<<yomiyasu:original>>>、<<<yomiyasu:material>>>、<<<yomiyasu:final>>> の行で区切ります。")
    options = run.add_argument_group("オプション")
    options.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
    options.add_argument("--stance", metavar="立場",
                         help="文書の立場（diff と同じ）。勧め（読み手に勧める）、決まり（手順）、説明（報告、体験）のどれか。")
    options.add_argument("--fail-on", action="append", dest="fail_on", metavar="meaning-risk|warn|error",
                         help=_FAIL_ON_HELP)
    options.add_argument("--timeout", metavar="秒",
                         help="子プロセスの検査（lint と diff）に使える秒数の合計。既定は90。超えたら止めて、状態を partial にします。")
    options.add_argument("--run-id", metavar="ID",
                         help="記録をつなぐ実行ID（英数字で始まり、英数字と「.」「_」「-」だけの64字まで）。"
                              "フックや CI が自分で決めるときに使います。")
    options.add_argument("--new-run", action="store_true",
                         help="前の実行につながず、新しい実行IDで記録します。")
    options.add_argument("--session", metavar="ID",
                         help="記録に入れるセッションの識別子（入れるだけ）。省くと環境変数 YOMIYASU_SESSION。")
    options.add_argument("--state-dir", metavar="DIR",
                         help="記録を書く状態フォルダ。省くと環境変数 YOMIYASU_STATE_DIR、なければ git の最上位"
                              "（なければ作業ディレクトリ）の .yomiyasu/。書けないときもほかへ逃がしません。")
    options.add_argument("--no-record", action="store_true",
                         help="記録を書きません（状態 unrecorded）。利用者が記録も作らないよう頼んだときだけ使います。")
    options.add_argument("--json", action="store_true",
                         help="結果をJSON（結果の形式1）で出します。日本語は \\uXXXX の形で出します。")
    run.set_defaults(fail_on=[])

    verify = commands.add_parser(
        "verify", prog="yomiyasu_check.py verify", usage=_VERIFY_USAGE, epilog=_EXIT_CODES,
        formatter_class=_HelpFormatter, add_help=False, allow_abbrev=False,
        help="提出の直前に、最終稿のハッシュを記録と照らします（読むだけで、何も書きません）。",
        description=("最終稿に必要な検査を実行した記録があり、最終稿のハッシュが記録と合うかを確かめます。"
                     "合格の判定ではありません。読むだけで、何も書きません。\n" + _RECORD_NOTE))
    checked = verify.add_argument_group("引数")
    checked.add_argument("--final", required=True, metavar="最終稿|-",
                         help="照らす最終稿のファイル。- を渡すと標準入力の本文を、本文のハッシュで照らします。")
    options = verify.add_argument_group("オプション")
    options.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
    options.add_argument("--run-id", metavar="ID", help="この実行IDの記録だけを照らします。")
    options.add_argument("--source", "--original", dest="source", metavar="原文",
                         help="記録の原文がこのファイルかも確かめます。同じ最終稿に原文の違う記録があるときは、"
                              "これで絞ります。- を渡すと標準入力を読みます（--final と合わせて1か所だけ）。")
    options.add_argument("--since", metavar="ISO8601",
                         help="この時刻より前に作った記録は使いません。時差つきで書きます（例 2026-10-13T01:45:00Z、"
                              "2026-10-13T10:45:00+09:00）。秒より細かい部分は切り捨てます。")
    options.add_argument("--replay", action="store_true",
                         help="記録の写しに対して lint と diff を動かし直し、資料との照合も作り直して、"
                              "レポート（.json と .txt）が記録と同じになるかも確かめます。lint と diff の時間がかかります。")
    options.add_argument("--timeout", metavar="秒", help="--replay で lint と diff を並べて動かす時間の上限（秒）。既定は90。")
    options.add_argument("--state-dir", metavar="DIR", help="記録を探す状態フォルダ（run と同じ決め方）。")
    options.add_argument("--json", action="store_true", help="結果をJSON（結果の形式1）で出します。")
    return parser, run, verify


def _materials_format_version():
    """照合の JSON の版（MATERIALS_FORMAT_VERSION）。定数は yomiyasu_diff.py にだけ置く（10.1 L2）が、--version では
    diff を読み込まず、ファイルの行から読む（3.4: lint と diff の import は run と verify --replay の中だけ。
    diff が壊れていても版の行を出せる。反証レビュー spec F5）。"""
    path = os.path.join(_HERE, "yomiyasu_diff.py")
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as error:
        raise ImportError("{} を読めません（{}）。yomiyasu_check.py と同じ版の yomiyasu_diff.py を同じフォルダに置いてください。"
                          .format(path, getattr(error, "strerror", None) or error), name="yomiyasu_diff")
    match = _MATERIALS_VERSION_LINE.search(data.decode("utf-8", "replace"))
    if not match:
        raise ImportError("{} に MATERIALS_FORMAT_VERSION の行がありません。yomiyasu_check.py と同じ版の yomiyasu_diff.py を"
                          "置いてください。".format(path), name="yomiyasu_diff")
    return int(match.group(1))


def _version_line():
    return "yomiyasu_check.py {} (record format {}, result format {}, materials format {})".format(
        __version__, RECORD_FORMAT_VERSION, RESULT_FORMAT_VERSION, _materials_format_version())


def _use_utf8(stream, **options):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", **options)


def _error(message):
    """標準エラーに書く。標準エラーがないとき（pythonw など）は何もしない。"""
    stream = sys.stderr
    if stream is None:
        return
    try:
        _use_utf8(stream, errors="backslashreplace")
        print(message, file=stream)
    except (OSError, ValueError):
        # 標準エラーも閉じられているときは、書かずに終える。
        pass


def _run_cli(argv):
    argv = list(sys.argv[1:] if argv is None else argv)
    # サブコマンドを省くと run とみなす（3.2。yomiyasu_check.py --source a --final b も動く）
    if not argv or argv[0] not in ("run", "verify", "-h", "--help", "--version"):
        argv.insert(0, "run")
    parser, run, verify = _build_parser()
    # サブコマンドの引数は、そのサブコマンドの parser で読む（知らない引数の誤りを「yomiyasu_check.py run: error:」の形で出す）
    if argv[0] in ("run", "verify"):
        try:
            if argv[0] == "run":
                code = _run(run.parse_args(argv[1:]), run)
            else:
                code = _verify(verify.parse_args(argv[1:]), verify)
        except _NoWorkingDirectory as error:
            # 作業ディレクトリが消えている（run は何も書く前に確かめる）。入力の誤りとして2（robust R11）
            _error(str(error))
            code = 2
    else:
        args = parser.parse_args(argv)
        if not args.version:
            parser.error("サブコマンド（run か verify）を指定してください")
        print(_version_line())
        code = 0
    # 書き出しの失敗（読む側が先に閉じたなど）を、ここで BrokenPipeError として受けられるようにする。
    if sys.stdout is not None:
        sys.stdout.flush()
    return code


def _silence_stdout():
    """標準出力を os.devnull に向け直す。インタプリタの終わりでもう一度書き出しに失敗しないようにする。"""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        pass


class _Stopped(BaseException):
    """SIGTERM か SIGHUP で止められた。BaseException にして、途中の except Exception で受けずに、finally（子を止める、
    一時フォルダの写しを消す、書きかけの記録を消す）を通して main まで戻す（robust R1、agent 12）。"""

    def __init__(self, number):
        super().__init__(number)
        self.number = number


def _stop_handler(number, frame):
    raise _Stopped(number)


def _install_stop_handlers():
    """POSIX で SIGTERM と SIGHUP を受けるようにする。元の扱いの並びを返す（main の終わりで戻す）。
    無視する設定（nohup など）はそのままにする。主スレッドでないときは何もしない。"""
    previous = []
    if os.name != "posix":
        return previous
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            current = signal.getsignal(number)
            if current is signal.SIG_IGN:
                continue
            signal.signal(number, _stop_handler)
        except (ValueError, OSError, RuntimeError):
            continue
        previous.append((number, current))
    return previous


def _restore_handlers(previous):
    for number, handler in previous:
        try:
            signal.signal(number, handler if handler is not None else signal.SIG_DFL)
        except (ValueError, OSError, RuntimeError, TypeError):
            pass


def _signal_name(number):
    try:
        return signal.Signals(number).name
    except (ValueError, AttributeError):
        return "シグナル{}".format(number)


def main(argv=None):
    """CLI。終了コードを返す（0: executed か unrecorded で条件に当たらない、1: --fail-on に当たった・verify が合わない、
    2: 使い方か入力の誤り、3: 検査の一部を実行できなかった・内部の誤り、128+シグナルの番号: 外から止められた）。"""
    previous = _install_stop_handlers()
    try:
        if _IMPORT_ERROR is not None:
            raise _IMPORT_ERROR
        _use_utf8(sys.stdout)
        return _run_cli(argv)
    except _Stopped as stop:
        # 動いていた子は止め、一時フォルダの写しは消してある（_Children.stop と finally）
        _error("yomiyasu_check.py: 止められました（{}）。動いていた検査を止めて終わります。".format(_signal_name(stop.number)))
        return 128 + stop.number
    except KeyboardInterrupt:
        _error("yomiyasu_check.py: 止められました（SIGINT）。動いていた検査を止めて終わります。")
        return 128 + 2
    except BrokenPipeError:
        # 出力先（パイプの読む側）が先に閉じた。check の不具合ではないので、トレースバックは出さない。
        # 結果を最後まで書けなかったので、終了コードは3にする（記録はすでに書いてある）。
        _silence_stdout()
        _error("yomiyasu_check.py: 出力先が閉じられたため、結果を最後まで書けませんでした。")
        return 3
    except Exception as error:
        _error("yomiyasu_check.py: 内部エラー: {}: {}".format(type(error).__name__, error))
        _error(traceback.format_exc().rstrip("\n"))
        return 3
    finally:
        _restore_handlers(previous)


if __name__ == "__main__":
    sys.exit(main())
