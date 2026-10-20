#!/usr/bin/env python3
"""
yomiyasu_check.py - 最終稿に lint、原文と最終稿に diff（新規作成では資料との照合）をまとめて実行し、記録を残す。

標準ライブラリだけで動く。モデルは呼ばない。外へ通信しない。
  run     lint と diff を子プロセスで動かし（時間の上限つき）、資料があればプロセスの中で照らし、
          入力の写し、レポート、記録を状態フォルダ（既定は git の最上位の .yomiyasu/）に書く。
  verify  最終稿のハッシュを記録と照らす（読むだけで、何も書かない）。
mail（メール・チャット）と paper（論文・研究レポート）も指定できる。慎重表現・値・敬語の追加検査は
硬化・勢いと同じく件数を表示・記録する。敬語は mail だけ。引用の印は meaning-risk の対象、宛名・敬語は対象外。
返す状態は「検査を実行した」で、意味の保持や読みやすさの合格ではない。
同じ権限で原稿と記録の両方を書き換えられる環境では、記録は実行漏れを見つけるためのもので、
改ざんの防止や人の承認の証明にはならない。
"""
__version__ = "2.1.1"

import sys

# lint と diff を読み込む前に、.pyc を書かないようにする（スキルのフォルダに __pycache__ を作らない）。
# 子プロセスは -B で動かす。
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
import unicodedata  # noqa: E402
from collections import Counter, OrderedDict  # noqa: E402
_VISIBILITY_NAMES = ("decode_source", "DOC_TYPES", "READER_LEVELS", "normalize_doc_type", "normalize_reader")
try:
    try:
        if __package__:
            from .markdown_visibility import decode_source, DOC_TYPES, READER_LEVELS, normalize_doc_type, normalize_reader
        else:
            from markdown_visibility import decode_source, DOC_TYPES, READER_LEVELS, normalize_doc_type, normalize_reader
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
        _missing = [name for name in _VISIBILITY_NAMES if not hasattr(_visibility_module, name)]
        if _missing:
            raise ImportError(
                "{} に {} がありません。yomiyasu_check.py と同じ版の markdown_visibility.py を置いてください。".format(
                    _visibility_spec.origin, "、".join(_missing)),
                name=expected)
        decode_source = _visibility_module.decode_source
        DOC_TYPES = _visibility_module.DOC_TYPES
        READER_LEVELS = _visibility_module.READER_LEVELS
        normalize_doc_type = _visibility_module.normalize_doc_type
        normalize_reader = _visibility_module.normalize_reader
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
# 記録の tools に足す一覧のファイル（diff が scripts の隣の ../references/lists/<名前>.txt から読む。名前は yomiyasu_diff.py の
# BUILTIN_LISTS と同じ）。ファイルがあるときだけ "references/lists/<名前>.txt" のキーで SHA-256 を入れ、verify で比べて、
# 変わっていれば tool_changed にする（diff の詰めの直し。反証で見つけた例）
_LIST_NAMES = ("nominalization", "intensifiers", "feelings", "hedges")
_LIST_KEYS = tuple("references/lists/{}.txt".format(name) for name in _LIST_NAMES)
# 事実の穴の候補の一覧（--fact-gaps を付けた run の記録の tools にだけ入る）。入った記録は、ほかの4つと同じく verify で比べ、
# 変わっていれば tool_changed にする（前は --replay だけで比べ、通常の verify は executed のままだった）
_FACT_GAPS_KEY = "references/lists/fact-gaps.txt"
# ファイルがないとみなす誤り（yomiyasu_diff.py の _LIST_ABSENT と同じ）
_LIST_ABSENT = (FileNotFoundError, NotADirectoryError)
# 外から渡す実行IDの形。状態フォルダの外を指せないようにする
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ATTEMPT_FILE = re.compile(r"^attempt-([0-9]+)\.json$")
_BY_PATH_ENTRY = re.compile(r"^([0-9]{8}T[0-9]{6}Z)\.(.+)\.([0-9]+)$")
_TOOL_VERSION = re.compile(r"^__version__\s*=\s*[\"']([^\"']+)[\"']\s*$", re.M)
_DEFAULT_TIMEOUT = 90          # 子プロセスの検査に使える秒数の合計の既定（Claude Code の Bash の既定の上限120秒より短い）
# 子を待つ秒数がこれを超えたら、上限なしで待つ。とても大きな --timeout（約25日を超える値）は、OS の待ち方の時間の形を超えて
# OverflowError になるため（反証で見つけた例）。約11.6日なので、上限なしとみなしても違いは出ない
_WAIT_LIMIT = 1000000
_MATERIALS_VERSION_LINE = re.compile(r"^MATERIALS_FORMAT_VERSION\s*=\s*([0-9]+)\s*(?:#.*)?$", re.M)
# 人が読む文に書く検査名（完了報告の4語）。状態の行の checks= と failed= は名前のまま
_CHECK_LABELS = {"lint": "lint", "diff": "diff", "materials": "資料との照合"}
# 意味が変わる恐れを出す検査。これが最後まで動かなかったときは meaning_risk= を出さない（0件と読めるため）
_RISK_CHECKS = ("diff", "materials")
# 子の JSON で check が読むキーと型（形が違っても落ちずに、その検査を error にする。反証で見つけた例）
_REPORT_KEYS = {
    "lint": (("candidate_count", int), ("counts", dict), ("findings", list), ("context", dict)),
    "diff": (("status", str), ("candidate_count", int), ("meaning_risk_count", int),
             ("fail_on_meaning_risk_count", int), ("meaning_risks", list), ("full_diff", dict), ("new_words", list),
             ("context", dict)),
}
_LINK_SECONDS = 6 * 60 * 60     # 前の記録につなぐのは6時間以内
_STDERR_LIMIT = 2000            # 記録に残す子の標準エラーの字数
_REPLACE_TRIES = 6              # os.replace を PermissionError のあと50ミリ秒待って5回まで書き直す
_REPLACE_WAIT = 0.05
_ATTEMPT_TRIES = 100            # 回の番号を確保するのは100回まで
_NOT_JUDGED = ["meaning_preservation", "reader_comprehension"]

_GITIGNORE = "# yomiyasu の検査記録。git に入れない。\n*\n"
_DISCLAIMER = "この記録は検査を実行したことを示すだけで、意味が保たれたことや読みやすさの合格を示すものではありません。"
_MATERIALS_DISCLAIMER = ("照らしたのは数値、名前、語、確度の語だけです。主張、条件、担当が資料どおりかは判定していません。"
                         "資料と読み比べてください。")
# 記録を書かないときの4行目（記録がないので「この結果は」）
_UNRECORDED_DISCLAIMER = "この結果は検査を実行したことを示すだけで、意味が保たれたことや読みやすさの合格を示すものではありません。"
_SAME_FILE_ERROR = ("原文と最終稿が同じファイルです。書き直す前の原文を別のファイルに残し、最終稿を別のファイルに保存してから"
                    "実行してください。原文を上書きしてしまったときは、git などで元の版を取り出して --source に渡してください。"
                    "元の版を取り出せないときは、最終稿を写して --source に渡さず、完了報告の「実行しなかった検査」に"
                    "「diff（原文を上書きしたため）」と書いてください。")
# 資料と最終稿が同じ中身（同じファイルを含む）のとき。照合が空回りするので2にする
_SAME_AS_FINAL_ERROR = ("資料と最終稿が同じ中身です。資料には、利用者から受け取った資料を渡してください。"
                        "書き直す前の文章なら --source に渡してください。")
# 空の最終稿（空白だけの本文も同じ）
_EMPTY_FINAL_ERROR = "最終稿が空です。書き終えた最終稿を渡してください。"
# 1行目の {仕上げ}。verify の executed は、本文だけを返す指定もあるので「完了報告を付けるときは」とする。
# --stdin も、ファイルと同じく返す直前の verify を案内する（本文だけを返す依頼で verify が抜けたため）。
# --no-record は「直さないなら」に続けて読めるように並べ替えた
_FINALIZE_FILE = "提出の直前に、本文を変えずに verify を1回実行してください。"
_FINALIZE_STATE_DIR = "提出の直前に、本文を変えずに verify --state-dir {} を1回実行してください。"
_FINALIZE_STDIN = "提出の直前に、本文を変えずに、最終稿だけを標準入力から verify --final - に渡して1回実行してください。"
_FINALIZE_STDIN_STATE_DIR = ("提出の直前に、本文を変えずに、最終稿だけを標準入力から verify --state-dir {} --final - に渡して"
                             "1回実行してください。")
_FINALIZE_NO_RECORD = ("完了報告の「実行しなかった検査」に「最終稿の照合（記録を残さない指定のため）」と書いてください"
                       "（記録を残さない指定なので verify はできません）。")
_FAILED_NAMES = {"timeout": "時間切れ", "error": "内部エラー"}
# partial の1行目の最後
_PARTIAL_TAIL = "verify は実行せず、完了報告にこの出力の2行目を写してください。"
# 検査の途中で最終稿が変わったとき。正しい次の行動は run のやり直し
_FINAL_CHANGED_LINE = "最終稿が検査の途中で変わりました。変え終えてから yomiyasu_check.py run をもう一度実行してください。"
_FINAL_CHANGED_SUMMARY = "実行した検査: なし（途中で最終稿が変わったため）"
# 原文から本文が変わっていないとき
_NO_CHANGE_LINE = "検査を実行しました。原文から変更はありません{}。書き直したのに変更なしと出たときは、原文を上書きしていないか確かめてください。"
_TEXT_SAME_NOTE = "（改行コード、BOM、末尾の改行だけが違います）"
# 原文が、前に最終稿として検査した本文と同じとき（2にはしない）
_SOURCE_WAS_FINAL_NOTE = ("原文が、前に最終稿として検査した本文と同じです。続けて直す依頼でなければ、原文を上書きしたか、"
                          "原文と最終稿を逆に渡していないか確かめてください。")
# 資料を原文とみなす扱い: 新規作成で、資料の1つが最終稿とよく似ているとき、その資料を原文とみなして diff も実行する。
# 似かたは、NFKC にして空白を除いた文字列の2字組（隣り合う2文字）の重なり。重なった2字組の数を最終稿の2字組の数で割った値と、
# 資料の2字組の数で割った値の小さいほう（片側だけで決めると、大きな資料に短い最終稿の2字組がほとんど含まれてしまう）。
# しきい値は、tests/corpus の推敲の48組（最小 0.577）と、正しい新規作成の組（最大 0.495）で測って決めた
# （tests/test_v200_check_harden.py）
_SIMILAR_TO_SOURCE = 0.53
_TREATED_NOTE = "資料の1つが最終稿とよく似ているので、原文とみなして diff も実行しました。書き直す前の文章なら --source に渡してください。"
# 同じ実行の前の回で原文とみなした資料を、この回も原文とみなしたとき（似かたがしきい値を下回っても、直しを重ねて diff が
# 外れないようにする。反証で見つけた例）
_TREATED_INHERITED_NOTE = ("前の回で原文とみなした資料を、この回も原文とみなして diff も実行しました。"
                           "書き直す前の文章なら --source に渡してください。")
# diff が最後まで動かなかった partial では「実行しました」と書かない（partial の文の前に置く。反証で見つけた例）
_TREATED_PENDING_NOTE = ("資料の1つが最終稿とよく似ているので、原文とみなして diff も必要な検査に入れました。"
                         "書き直す前の文章なら --source に渡してください。")
_TREATED_INHERITED_PENDING_NOTE = ("前の回で原文とみなした資料を、この回も原文とみなして diff も必要な検査に入れました。"
                                   "書き直す前の文章なら --source に渡してください。")
# 記録の inputs.materials[].treated_by の値（似かたで決めたか、同じ実行の前の回から引き継いだか）
_TREATED_BY = ("similarity", "previous_attempt")
_SPACES = re.compile(r"\s+")
# 外から渡す実行IDのうち、Windows で作れないか別の名前になるもの（末尾の「.」と予約された名前）
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.I)
_RUN_ID_ERROR = ("--run-id に使えない値です: {}。英数字で始まり、英数字と「.」「_」「-」だけの64字までにしてください。"
                 "末尾の「.」と、Windows で使えない名前（CON、NUL、COM1 など）は使えません。")

# 標準入力を分ける区切りの行（行全体がこの文字列。行末の \r は無視する）
_MARKERS = OrderedDict(((b"<<<yomiyasu:original>>>", "source"), (b"<<<yomiyasu:material>>>", "material"),
                        (b"<<<yomiyasu:final>>>", "final")))
_STDIN_FORM = ("<<<yomiyasu:original>>>\n（書き直す前の原文）\n<<<yomiyasu:final>>>\n（最終稿）\n"
               "新規作成では <<<yomiyasu:original>>> の代わりに、資料ごとに <<<yomiyasu:material>>> の行と資料を書きます。")
# 区切りの行の書き損じ（「<<<yomiyasu:」で始まるが、上の3つと一字一句同じでない行。前後の空白と大文字も書き損じに数える）。
# 区切りと認めずに前の部分へ黙ってつなぐと、資料が原文に入るので、2で止める
_MARKER_HEAD = "<<<yomiyasu:"
_MARKER_SHOWN = 60              # 案内に写す行の字数の上限
_BAD_MARKER_KEY = "決まった区切りの行と一字一句同じではありません"
_BAD_MARKER = "{}行目の「{}」が、" + _BAD_MARKER_KEY + "。資料は <<<yomiyasu:material 出典>>>（出典は200字まで）、原文と最終稿は出典なしで書いてください"
_BAD_MARKER_TAIL = ("本文に <<<yomiyasu: で始まる行があるときは、ファイルに保存して --source（新規作成では --material）と"
                    " --final で渡してください。")


# ---- 小さな道具 ----

def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _text_sha256(text):
    """記録の text_sha256。decode_source のあとの文字列から、末尾の改行をすべて外して改行を1つ付ける（空なら空）。"""
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
    """作業ディレクトリが消えている、または読めない（入力の誤りとして終了コード2。反証で見つけた例）。"""


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
    """人が読む文に書く検査名（完了報告の語）。"""
    return _CHECK_LABELS.get(name, name)


def _disk_path(path):
    """パスの比べと by-path のキーに使う綴り。realpath のあと、macOS では開いたファイルの F_GETPATH で
    ディスク上の綴りを取る。大文字と小文字を区別しないファイルシステムで、大文字と小文字や NFC と NFD の違う綴りで同じファイルを
    渡しても、同じ綴りになる。
    macOS では、取った綴りを NFC にそろえ、大文字と小文字を区別しないファイルシステムでは casefold もする。ファイルを消して
    別の綴りで作り直すと（git restore、Finder で作った NFD の名前を NFC で打って作り直す）、ディスク上の綴りが変わり、
    前の回につながらなくなるため（反証で見つけた例）。"""
    real = os.path.realpath(path)
    if sys.platform != "darwin":
        return real
    found = ""
    try:
        import fcntl
        # パイプなどでも止まらないように O_NONBLOCK で開く（読むだけで、中身は読まない）
        handle = os.open(real, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except (ImportError, OSError):
        handle = None
    if handle is not None:
        try:
            # F_GETPATH は macOS の値 50（Python 3.9 から fcntl.F_GETPATH がある）
            found = os.fsdecode(fcntl.fcntl(handle, getattr(fcntl, "F_GETPATH", 50), bytes(1024)).split(b"\0", 1)[0])
        except (OSError, ValueError):
            found = ""
        finally:
            os.close(handle)
    spelled = unicodedata.normalize("NFC", found or real)
    return spelled.casefold() if _case_insensitive(found or real) else spelled


def _case_insensitive(path):
    """path（なければ、あるところまでさかのぼったフォルダ）のファイルシステムが、大文字と小文字を区別しないか。
    大文字と小文字を入れ替えた綴りで同じファイルを開けるかで確かめる（Python には問い合わせる関数がない）。"""
    current = path
    while not os.path.lexists(current):
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent
    swapped = current.swapcase()
    if swapped == current:
        return False
    try:
        mine, other = os.stat(current), os.stat(swapped)
    except OSError:
        return False
    return (mine.st_dev, mine.st_ino) == (other.st_dev, other.st_ino)


def _place(path):
    """パスを比べるための文字列（_disk_path と normcase）。"""
    return os.path.normcase(_disk_path(_abspath(path)))


def _same_path(a, b):
    return _place(a) == _place(b)


def _run_id_problem(run_id):
    """外から渡す実行IDの誤りの文（なければ None）。実行IDの形に加えて、Windows で作れないか別の名前になるもの（末尾の「.」、
    CON、NUL、COM1 などの予約された名前。拡張子を付けても同じ）を断る。"""
    if (not _RUN_ID.match(run_id) or run_id.endswith(".")
            or _WINDOWS_RESERVED.match(run_id.split(".", 1)[0])):
        return _RUN_ID_ERROR.format(run_id if run_id.strip() else "（空）")
    return None


def _run_id_case_problem(state, run_id):
    """runs/ に、大文字と小文字だけが違う実行IDのフォルダがあるときの誤りの文（なければ None）。大文字と小文字を区別しない
    ファイルシステムでは同じフォルダに入ってしまう。"""
    try:
        names = os.listdir(os.path.join(state, "runs"))
    except OSError:
        return None
    for name in sorted(names):
        if name != run_id and name.casefold() == run_id.casefold():
            return ("--run-id {} は、すでにある実行ID {} と大文字と小文字だけが違います。同じ綴りで指定するか、"
                    "別の実行IDにしてください。".format(run_id, name))
    return None


def _compact(text):
    """資料と最終稿の似かたと、同じ本文かの比べの下ごしらえ。NFKC にし、空白（改行を含む）と書式の文字（一般カテゴリ Cf。ゼロ幅の空白、
    ソフトハイフン、BOM など）を除く（反証で見つけた例。文字の間に書式の文字を挟むと似かたが0になるため）。"""
    text = _SPACES.sub("", unicodedata.normalize("NFKC", text))
    if text.isascii():
        return text  # ASCII に書式の文字はない
    category = unicodedata.category
    marks = [ord(char) for char in set(text) if category(char) == "Cf"]
    return text.translate(dict.fromkeys(marks)) if marks else text


def _bigram_counts(text, compacted=False):
    """似かたの下ごしらえ。_compact の文字列の2字組を数える（compacted なら text はもう _compact したもの）。"""
    if not compacted:
        text = _compact(text)
    return Counter(text[index:index + 2] for index in range(len(text) - 1))


def _similarity_of_counts(material, final):
    total_material, total_final = sum(material.values()), sum(final.values())
    if not total_material or not total_final:
        return 0.0
    common = sum((material & final).values())
    return min(common / total_material, common / total_final)


def _similarity(material, final):
    """資料と最終稿の似かた（0 から 1）。重なった2字組の数を、最終稿の2字組の数で割った値と、資料の2字組の数で割った値の小さいほう。
    文字数に比例する時間で求める（6万字で約0.04秒）。"""
    return _similarity_of_counts(_bigram_counts(material), _bigram_counts(final))


def _source_like(material_texts, final_text, compacted=False):
    """資料ごとの似かたの並びと、原文とみなす資料の番号（1から。しきい値以上でいちばん似ているもの。同じなら若い番号。
    なければ None）。compacted なら、渡す文字列はもう _compact したもの（run が同じ本文かの比べと同じ文字列を使い回す）。"""
    final = _bigram_counts(final_text, compacted)
    values = [_similarity_of_counts(_bigram_counts(text, compacted), final) for text in material_texts]
    best = None
    for index, value in enumerate(values, 1):
        if value >= _SIMILAR_TO_SOURCE and (best is None or value > values[best - 1]):
            best = index
    return best, values


def _same_file(a, b):
    """同じファイルか（パスの比べと、あれば samefile。大文字と小文字を区別しないファイルシステムやハードリンクのため）。"""
    if _same_path(a, b):
        return True
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _host_value(value):
    """記録に入れる環境の値。空や、展開されなかった ${…} を含む値は null にする。"""
    if not value or "${" in value:
        return None
    return value


def _chmod(path, mode):
    # 原稿の写しを含むので、POSIX ではフォルダを 0o700、ファイルを 0o600 にする。chmod は POSIX のときだけ
    if os.name == "posix":
        os.chmod(path, mode)


def _replace(source, target):
    """os.replace。ほかのプロセスがファイルを開いているときの PermissionError は、50ミリ秒待って5回まで書き直す
    （Windows を考えたもの。OS によらず書き直す）。"""
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(_REPLACE_WAIT)


def _write_atomic(path, data):
    """同じフォルダの一時ファイルに書いてから入れ替える（読む側が書きかけを見ない）。"""
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


def _still_placed(path, info):
    """path が、info（os.fstat の結果）と同じファイルのままか。"""
    try:
        now = os.lstat(path)
    except OSError:
        return False
    return (now.st_dev, now.st_ino) == (info.st_dev, info.st_ino)


def _place_new_file(path, data):
    """data を書いたファイルを path に置く。path にすでに何か（壊れたリンクを含む）があれば、置かずに False を返す
    （上書きしない）。同じフォルダの一時ファイルに書いてから os.link で置くので、読む側は書きかけを見ない。
    ハードリンクを作れないファイルシステムでは、O_EXCL で作ってから書く。書けなかったときは、ここで作ったファイル
    だけを消して例外を出す（ほかのプロセスが同じ名前に置き直したファイルは消さない）。"""
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        _chmod(temporary, 0o600)
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            pass  # ハードリンクを作れない（FAT など）。下の O_EXCL に進む
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        handle = os.open(path, flags, 0o600)
    except FileExistsError:
        return False
    info = None
    try:
        info = os.fstat(handle)
        with os.fdopen(handle, "wb") as stream:
            handle = None
            stream.write(data)
        _chmod(path, 0o600)
    except BaseException:
        if handle is not None:
            try:
                os.close(handle)
            except OSError:
                pass
        if info is not None and _still_placed(path, info):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    return True


def _write_state_files(state):
    """状態フォルダに .gitignore を置き、そのあと state.json を置く。どちらも、その名前にまだ何もないときだけ置く。

    .gitignore の名前にすでに何かあれば、並列の run か利用者が先に置いたものとして、state.json も置かずに戻る。
    書けなかったときは例外を出す。置けた .gitignore は、あとの state.json を書けなくても消さない（無視の規則だけの
    ファイルで、残せば、並列の run がそのあいだにこのフォルダに書いた写しも git status に出ない。反証で見つけた例）。"""
    if not _place_new_file(os.path.join(state, ".gitignore"), _GITIGNORE.encode("utf-8")):
        return
    state_json = json.dumps({"format": "yomiyasu-state", "format_version": 1}, ensure_ascii=True) + "\n"
    _place_new_file(os.path.join(state, "state.json"), state_json.encode("ascii"))


def _add_state_files(state, default_place):
    """すでにある状態フォルダに、作ったときと同じ2つを足すか決めて足す。

    足すのは、default_place が真（--state-dir と環境変数 YOMIYASU_STATE_DIR のどちらでも決めず、state_dir_for の3か4で
    決めた .yomiyasu/）で、フォルダそのものがリンクでなく、state.json も .gitignore もない（壊れたリンクもない）ときだけ。
    モデルなどが先に mkdir した .yomiyasu/ に .gitignore なしで原文の全文の写しを書くと、git status に出てコミットされる
    おそれがあるため（反証で見つけた例）。ほかのファイルとフォルダの権限には触れず、書けなかったときもフォルダは消さない。
    state.json だけ、.gitignore だけがあるフォルダ（利用者が消したか書いたのかもしれない）、リンクの先のフォルダ（ほかの
    場所に書くことになる）、--state-dir や環境変数で決めたフォルダは今のまま。"""
    if not default_place or os.path.islink(state):
        return
    if os.path.lexists(os.path.join(state, ".gitignore")) or os.path.lexists(os.path.join(state, "state.json")):
        return
    _write_state_files(state)


def _ensure_state(state, default_place=False):
    """状態フォルダを用意する。作ったときは .gitignore と state.json を書く。すでにあるフォルダは _add_state_files の
    決まりのときだけ2つを足す。

    作ったフォルダに .gitignore を書けなかったときは、作りかけのフォルダを消す。残すと次の run が「すでにある
    フォルダ」として .gitignore なしで書き続け、git status に出る（反証で見つけた例）。"""
    if os.path.isdir(state):
        _add_state_files(state, default_place)
        return
    parent = os.path.dirname(state)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    try:
        os.mkdir(state, 0o700)
    except FileExistsError:
        if os.path.isdir(state):
            # 並列の run が作ったばかりのフォルダ。その run が .gitignore を置く前に写しを書かないよう、
            # すでにあるフォルダと同じ決まりで、自分でも2つを置きにいく（先に置かれていれば何もしない）
            _add_state_files(state, default_place)
            return
        raise
    try:
        _chmod(state, 0o700)
        _write_state_files(state)
    except BaseException:
        try:
            os.rmdir(state)  # 中に何かあれば（置けた .gitignore、並列の run の写し）空でないので消えない
        except OSError:
            pass
        raise


def _home_path(value):
    """--state-dir と環境変数 YOMIYASU_STATE_DIR の値の頭の ~ を、ホームフォルダに置き換える（フックの _home_path と同じ）。

    置き換えるのは、値が「~」だけのときと、「~/」で始まるとき（Windows では「~\\」も）だけで、os.path.expanduser で
    展開する。シェルの引用符の中や、エージェントの設定ファイルの環境変数では、~ が展開されないまま届くため。
    「~user/x」や「~x」は置き換えない（その名前の利用者が機械にいるかどうかで、場所が変わらないように）。
    HOME がなければ expanduser と同じく利用者の情報から探す。それでも決まらないとき（結果がまだ ~ で始まるか、
    expanduser が例外を出したとき）は、値をそのまま返す（これまでと同じく、作業ディレクトリからの相対パス）。
    ホームフォルダが空か空白だけ、またはルート（「/」、Windows では「C:\\」など）だけのときも、決まらないものとして
    値をそのまま返す。HOME が空の文字列のとき expanduser は「~/x」を「/x」に、「~」を「/」にするので、状態フォルダを
    ファイルシステムのルートに置かないため（HOME が「/」のときも expanduser の結果は同じで、見分けられない）。"""
    if isinstance(value, str) and (value == "~" or value[:2] in ("~/", "~" + os.sep)):
        try:
            home = os.path.expanduser("~")
            expanded = os.path.expanduser(value)
        except Exception:  # pwd を読めない環境など
            return value
        if (not home.startswith("~") and os.path.splitdrive(home)[1].strip().strip("/" + os.sep)
                and not expanded.startswith("~")):
            return expanded
    return value


def state_dir_for(cwd, option=None):
    """状態フォルダの決め方（run、verify、フックで同じ規則）。

    1 --state-dir、2 環境変数 YOMIYASU_STATE_DIR、3 作業ディレクトリから上へたどり、.git（フォルダでもファイルでもよい）が
    ある最初のフォルダの .yomiyasu/、4 作業ディレクトリの .yomiyasu/。ここではフォルダを作らない。
    環境変数が空白だけのときと、展開されなかった ${…} を含むときは、ないものとして3と4に進む（--session の ${ と同じ扱い。
    作業フォルダに「${CLAUDE_PROJECT_DIR}」のようなフォルダを作らない。反証で見つけた例）。
    1と2の値の頭の ~ は、_home_path の決まりでホームフォルダに置き換える。"""
    if option:
        return os.path.abspath(os.path.join(cwd, _home_path(option)))
    environment = os.environ.get("YOMIYASU_STATE_DIR")
    if environment and environment.strip() and "${" not in environment:
        return os.path.abspath(os.path.join(cwd, _home_path(environment)))
    cwd = os.path.abspath(cwd)
    current = cwd
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return os.path.join(current, ".yomiyasu")
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.join(cwd, ".yomiyasu")
        current = parent


def _state_dir(option):
    # Absolute overrides must still work when the process cwd has disappeared.
    environment = os.environ.get("YOMIYASU_STATE_DIR")
    selected = option or (environment if environment and environment.strip() and "${" not in environment else None)
    if selected:
        selected = _home_path(selected)
    if selected and os.path.isabs(selected):
        return os.path.normpath(selected)
    return state_dir_for(_getcwd(), option)


def _state_dir_given(option):
    """状態フォルダを --state-dir か環境変数 YOMIYASU_STATE_DIR で決めたか（_state_dir の1か2）。"""
    if option:
        return True
    environment = os.environ.get("YOMIYASU_STATE_DIR")
    return bool(environment and environment.strip() and "${" not in environment)


def _record_digest(record):
    """記録の record_digest。record_digest を除いて、キーを並べ替え、区切りを詰めた JSON の SHA-256。"""
    body = dict((key, value) for key, value in record.items() if key != "record_digest")
    text = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + _sha256(text.encode("ascii"))


def _status_line(state, via, run_id=None, attempt=None, final=None, expected=None, mode=None, checks=None,
                 meaning_risk=None, replay=None, failed=None, reason=None, doc_type=None, reader=None):
    """状態の行。キーの順は固定で、値に空白を入れない。読む側の正規表現は
    ^yomiyasu-check: ([a-z_]+)((?: [a-z_]+=\\S+)*)$
    doc_type と reader は mode の次に、付けたときだけ出す。"""
    fields = [("via", via), ("run", run_id or "-"), ("attempt", str(attempt) if attempt else "-"), ("final", final or "-")]
    for key, value in (("expected", expected), ("mode", mode), ("doc_type", doc_type), ("reader", reader),
                       ("checks", checks), ("meaning_risk", meaning_risk),
                       ("replay", replay), ("failed", failed), ("reason", reason)):
        if value is not None:
            fields.append((key, str(value)))
    return "yomiyasu-check: " + state + "".join(" {}={}".format(key, value) for key, value in fields)


def _read_record_status(path):
    """記録を読む。("missing", None)、("bad", None)、("ok", 記録の dict) のどれかを返す。
    大きさ0のファイルは書いている途中とみなし、50ミリ秒待って1回だけ読み直す。"""
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


def _tool_versions(fact_gaps=False):
    """記録の tools（4本の版の文字列と SHA-256）。スクリプトは読み込まず、バイト列から読む。
    references/lists/ の一覧のファイルがあれば、"references/lists/<名前>.txt" のキーで {"version": null, "sha256"} を足す
    （開けないときは sha256 も null。ないときはキーを作らない）。"""
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
    names = _LIST_NAMES + (("fact-gaps",) if fact_gaps else ())
    for name in names:
        key = "references/lists/{}.txt".format(name)
        try:
            with open(os.path.join(_HERE, os.pardir, "references", "lists", name + ".txt"), "rb") as handle:
                tools[key] = {"version": None, "sha256": _sha256(handle.read())}
        except _LIST_ABSENT:
            continue
        except OSError:
            tools[key] = {"version": None, "sha256": None}
    return tools


def _list_sha256(tools, key):
    """tools の一覧のファイルの SHA-256（キーがなければ "absent"。開けなかったときは None）。"""
    entry = tools.get(key)
    return entry.get("sha256") if isinstance(entry, dict) else "absent"


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
    """scripts の1つ上に SKILL.md があるときだけ埋める（リポジトリのルートの scripts から動かすと found は偽）。"""
    skill_dir = os.path.dirname(_HERE)
    path = os.path.join(skill_dir, "SKILL.md")
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return {"found": False, "dir": None, "skill_md_sha256": None, "version": None}
    return {"found": True, "dir": skill_dir, "skill_md_sha256": _sha256(data), "version": _skill_version(data)}


# ---- lint と diff の読み込み（run と verify --replay の中だけ）----

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
        self.label = None
        self.role = role                      # "source"、"material"、"final"
        self.index = index                    # 資料は1から、ほかは0
        self.path = path                      # 絶対パス。標準入力なら None
        self.via = "file" if path is not None else "stdin"
        self.data = data
        self.sha256 = _sha256(data)
        self.text, info = decode_source(data)  # UTF-8 でなければ UnicodeDecodeError
        self.bom = info["bom"]
        self.eol = info["eol"]
        self.text_sha256 = _text_sha256(self.text)
        self.similarity = None                # 資料だけ: 最終稿との似かた（新規作成のとき）
        self.treated_as_source = False        # 資料だけ: 原文とみなして diff を実行したか
        self.treated_by = None                # 資料だけ: 原文とみなした決め方（_TREATED_BY のどちらか）

    def snapshot(self):
        return "inputs/" + self.sha256 + ".bin"

    def token(self):
        """状態の行の final=。標準入力は本文のハッシュで照らすので text-sha256: を付ける。"""
        if self.via == "stdin":
            return "text-sha256:" + self.text_sha256[:12]
        return "sha256:" + self.sha256[:12]

    def record(self):
        record = OrderedDict((("role", self.role), ("index", self.index), ("path", self.path), ("via", self.via),
                              ("bytes", len(self.data)), ("sha256", self.sha256), ("text_sha256", self.text_sha256),
                              ("bom", self.bom), ("eol", self.eol), ("snapshot", self.snapshot())))
        if self.role == "material":
            # 資料を原文とみなした印。似かたは小数第3位まで（新規作成でないときは null）。treated_by は、似かたで決めたか（similarity）、
            # 同じ実行の前の回から引き継いだか（previous_attempt）。印がなければ null（反証で見つけた例）
            record["label"] = self.label
            record["treated_as_source"] = self.treated_as_source
            record["similarity"] = round(self.similarity, 3) if self.similarity is not None else None
            record["treated_by"] = self.treated_by
        return record


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
        # StringIO のようにバイト列を読めないときは、読んだ文字列を UTF-8 にしてから同じように扱う
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

    最終稿は検査のあとで読み直すので、通常のファイルでないもの（/dev/stdin、<(…) などのパイプ）は2にして
    --final - を案内する。読み直すと空になり、変わっていない最終稿を「途中で変わった」と報告するため（反証で見つけた例）。"""
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



_MATERIAL_MARKER = re.compile(r"^<<<yomiyasu:material(?:[ \t]+(.+?))?>>>[ \t]*$")


def _material_marker(bare):
    try:
        text = bare.decode("utf-8")
    except UnicodeDecodeError:
        return None
    match = _MATERIAL_MARKER.fullmatch(text)
    if match is None:
        return None
    label = match.group(1)
    if label is not None and (len(label) > 200 or ">>>" in label):
        return None
    return (label,)


def _split_material(item, first_index):
    """区切りは資料の本文に含めない。区切りなしの入力のバイト列はそのまま保存する。"""
    data = item.data[3:] if item.data.startswith(b"\xef\xbb\xbf") else item.data
    rows = data.splitlines(True)
    markers = {}
    first = next((i for i, row in enumerate(rows) if row.strip()), None)
    for i, row in enumerate(rows):
        bare = row.rstrip(b"\r\n")
        marker = _material_marker(bare)
        if marker is not None:
            markers[i] = marker[0]
        elif bare.decode("utf-8").strip().lower().startswith(_MARKER_HEAD):
            return None, _BAD_MARKER.format(i + 1, bare.decode("utf-8")[:_MARKER_SHOWN])
    if first not in markers:
        item.index = first_index
        return [item], None
    blocks = []
    starts = sorted(markers)
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(rows)
        body = b"".join(rows[start + 1:end])
        block, problem = _make_input("material", first_index + n, item.path, body)
        if problem:
            return None, problem
        block.label = markers[start]
        blocks.append(block)
    return blocks, None

_LINE_END = re.compile(b"\r\n|\r|\n")


def _split_stdin(data, with_labels=False):
    """区切りの行で標準入力を分ける。([(役割, バイト列)], None) か (None, 理由)。

    各部分は、区切りの行の次のバイトから、次の区切りの行の先頭まで（末尾の改行を含む）。先頭の BOM は1つ外す。
    行の終わりは、ファイル入力の decode_source と同じく LF、CRLF、CR のどれでもよい。各部分のバイト列は書き換えない
    （CRLF と LF の入力の記録は前と同じになり、CR だけの入力はファイルで渡したときと同じ eol "cr" になる）。"""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    parts = []
    current = None
    position = 0
    number = 0
    while position < len(data):
        match = _LINE_END.search(data, position)
        following = len(data) if match is None else match.end()
        number += 1
        bare = data[position:following if match is None else match.start()]
        role = _MARKERS.get(bare)
        label = None
        material = _material_marker(bare)
        if material is not None:
            role, label = "material", material[0]
        if role is None and b"<<<" in bare:
            text = bare.decode("utf-8", "replace")
            if text.strip().lower().startswith(_MARKER_HEAD):
                shown = text if len(text) <= _MARKER_SHOWN else text[:_MARKER_SHOWN] + "…"
                return None, _BAD_MARKER.format(number, shown)
        if role is not None:
            if current is not None:
                parts.append(current)
            current = [role, following, following, label]
        elif current is None:
            if bare.strip():
                return None, "空白以外の最初の行が区切りの行ではありません"
        else:
            current[2] = following
        position = following
    if current is not None:
        parts.append(current)
    roles = [part[0] for part in parts]
    if roles.count("final") == 0:
        return None, "<<<yomiyasu:final>>> の行がありません"
    if roles.count("final") > 1:
        return None, "<<<yomiyasu:final>>> の行が2つ以上あります"
    if roles.count("source") > 1:
        return None, "<<<yomiyasu:original>>> の行が2つ以上あります"
    if "source" not in roles and "material" not in roles:
        return None, "<<<yomiyasu:original>>> の行も <<<yomiyasu:material>>> の行もありません"
    if with_labels:
        return [(role, data[start:end], label) for role, start, end, label in parts], None
    return [(role, data[start:end]) for role, start, end, _ in parts], None


def _read_inputs(args):
    """原文、資料、最終稿を1回ずつ読む。((原文 or None, [資料], 最終稿), None) か (None, 誤りの文)。"""
    if args.stdin:
        data, problem = _read_stdin_bytes()
        if problem:
            return None, problem
        pieces, problem = _split_stdin(data, with_labels=True)
        if problem:
            message = "--stdin の本文の区切りが正しくありません（{}）。行全体が区切りになるように、次の形で渡してください。\n{}".format(
                problem, _STDIN_FORM)
            if _BAD_MARKER_KEY in problem:
                message += "\n" + _BAD_MARKER_TAIL
            return None, message
        source, materials, final = None, [], None
        for role, piece, label in pieces:
            index = len(materials) + 1 if role == "material" else 0
            item, problem = _make_input(role, index, None, piece)
            if problem:
                return None, problem
            item.label = label
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
        blocks, problem = _split_material(item, len(materials) + 1)
        if problem:
            return None, problem
        materials.extend(blocks)
    final, problem = _read_named("final", 0, args.final[0], stdin_data)
    if problem:
        return None, problem
    return (source, materials, final), None


# ---- 実行IDと回（フックの登録と start は、フックを作るときに足す）----

def _new_run_id(state, moment):
    """新しい実行ID（UTC の時刻と os.urandom(4) の16進）。"""
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
    """同じモードで、同じ原文と同じ資料の集まり（新規作成では同じ資料の集まり）の記録か。推敲でも資料の集まりを比べる
    （資料つきの run のあと、資料を外して run し直したときに同じ実行につながないため）。"""
    inputs = record.get("inputs")
    if record.get("mode") != mode or not isinstance(inputs, dict):
        return False
    if mode == "rewrite" and not _same_inputs([inputs.get("source")], [source]):
        return False
    return _same_inputs(inputs.get("materials"), materials)


def _latest_record(run_dir):
    """実行の中で読める最新の記録（大きい回から探す）。"""
    for number in reversed(_attempt_numbers(run_dir)):
        record = _read_record(os.path.join(run_dir, "attempt-{}.json".format(number)))
        if record is not None:
            return record
    return None


def _path_key(final, source, materials):
    """index/by-path のキー。ファイルは最終稿の実際のパス、標準入力は原文（新規作成では資料）の本文のハッシュ。"""
    if final.via == "file":
        base = _place(final.path)
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
    """index/by-path/<キー>/ の最新の記録。(実行ID, 記録) か None。最新の1件だけを見る。"""
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
            return None, ("別の原文の実行IDです（--run-id {}）。この実行の記録は、モード、原文、資料の集まりのどれかが違います。"
                          "この原文で検査するときは、--run-id を外すか、別の実行IDを指定してください。".format(run_id))
        numbers = _attempt_numbers(run_dir)
        return {"run_id": run_id, "attempt": (numbers[-1] + 1) if numbers else 1}, None
    if not new_run:
        armed = _armed_for_source(state, source)
        if armed is not None:
            numbers = _attempt_numbers(os.path.join(runs, armed["run_id"]))
            return {"run_id": armed["run_id"], "attempt": numbers[-1] + 1 if numbers else 1}, None
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


def _previous_treated(state, run_id, attempt):
    """同じ実行の、attempt より前の読める最新の記録が、原文とみなした資料（記録の Input の dict）。なければ None
    （その記録が新規作成でないか、印がないときも None）。run と verify で同じ決め方にする（反証で見つけた例）。"""
    run_dir = os.path.join(state, "runs", run_id)
    for number in reversed(_attempt_numbers(run_dir)):
        if attempt is not None and number >= attempt:
            continue
        record = _read_record(os.path.join(run_dir, "attempt-{}.json".format(number)))
        if not isinstance(record, dict):
            continue
        if record.get("mode") != "compose":
            return None
        return _record_treated(record)
    return None


def _was_checked_final(state, source):
    """原文の本文が、前に最終稿として検査した本文と同じか（index/by-text に読める記録がある。読むだけ）。
    その記録の原文も同じ本文なら（原文から変えずに検査した回）、取り違えではないので数えない。"""
    for item in _index_found(state, "by-text", source.text_sha256):
        final = item.final()
        if item.status != "ok" or final is None or final.get("text_sha256") != source.text_sha256:
            continue
        inputs = item.record.get("inputs") if isinstance(item.record, dict) else None
        recorded = inputs.get("source") if isinstance(inputs, dict) else None
        if isinstance(recorded, dict) and recorded.get("text_sha256") == source.text_sha256:
            continue
        return True
    return False


# ---- 検査 ----

def _wait_seconds(remaining):
    """子を待つ秒数。_WAIT_LIMIT を超える値は上限なし（None）にする（OverflowError を避ける。反証で見つけた例）。"""
    return None if remaining > _WAIT_LIMIT else remaining


class _Children(object):
    """lint と diff の子プロセスを、同じ締め切り（開始から --timeout 秒）で並べて動かす。

    check が外から止められたとき（SIGTERM、SIGHUP、Ctrl+C）は、呼ぶ側が stop() で動いている子を止める。止めないと、
    子は親を失ったまま最後まで動き続ける（反証で見つけた例）。"""

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
    (値, None) か (None, 理由)。形が違えば、その検査を error にする（check は落ちない。反証で見つけた例）。"""
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


def _material_number_keys(diff_module, item):
    """照合の項目を diff の候補に結び付ける。照合だけで読むミリ秒・msec も、diff が読む形で引けるようにする。"""
    keys = {(item.get("value"), item.get("unit"))}
    keys.update((number["value"], number["unit"]) for number in diff_module.extract_numbers(item["text"]))
    return keys


def _with_basis(diff_module, risks, materials_result):
    """推敲で資料があるとき、diff の数値の候補に basis を入れた写しを作る。
    足した値が資料にもどこにもなければ "none"、資料にあれば "material"（どちらも混ざれば "none" を先にする）。"""
    if materials_result is None:
        return [dict(risk) for risk in risks]
    classes = {}
    for item in materials_result.get("items", []):
        # 資料にあって最終稿にない数値（not_in_final。diff の詰めで足した参考の項目）は、最終稿の値の分類ではないので使わない
        if item.get("kind") == "number" and item.get("classification") != "not_in_final":
            for key in _material_number_keys(diff_module, item):
                # diff が同じ形で読む別の値が混ざれば、資料にない値を優先する。
                if classes.get(key) != "not_in_sources":
                    classes[key] = item.get("classification")
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
    """「■ 資料との照合」の節の行。推敲の行にするか新規作成の行にするかは、照合の JSON の mode で決める
    （新規作成で資料を原文とみなしたときは、照合を推敲として行うので推敲の行。反証で見つけた例）。"""
    result = ctx.materials_result
    items = result.get("items", [])
    rewrite = result.get("mode") == "rewrite"
    lines = ["■ 資料との照合（資料{}件）".format(len(ctx.materials))]
    if rewrite:
        supplements = [item["text"] for item in items if item.get("classification") == "from_materials"]
        if supplements:
            lines.append("- 資料に基づく補足の候補: " + "、".join(supplements))
    def shown(item, key):
        evidence = item.get(key) or []
        places = "、".join("資料{}の{}行目「{}」".format(index, line, text[:40]) for index, line, text in evidence)
        return item["text"] + ("（" + places + "）" if places else "")
    backed = [item for item in items if item.get("evidence")]
    if backed:
        lines.append("- 資料に基づく補足の候補（該当行）: " + "、".join(shown(item, "evidence") for item in backed[:5]))
    bare = [item for item in items if item.get("bare_in")]
    if bare:
        lines.append("- 単位のない数とだけ一致（資料にない数値に数えています。根拠の行か読み比べてください）: "
                     + "、".join(shown(item, "bare_in") for item in bare[:5]))
    words = [item["text"] for item in items
             if item.get("kind") == "word" and item.get("classification") == "not_in_sources"]
    if rewrite and ctx.diff_result is not None:
        # 推敲では diff の「元の文にない語」と重なる語を除く
        new_words = set(ctx.diff_result.get("new_words") or [])
        words = [word for word in words if word not in new_words]
    if words:
        lines.append("- 資料にない語: " + "、".join(words))
    dropped = [item["text"] + ("（{}の文）".format("、".join(item["values"])) if item.get("values") else "")
               for item in items if item.get("classification") == "dropped_certainty"]
    if dropped:
        lines.append("- 資料にあった確度の語が最終稿にない: " + "、".join(dropped))
    if not rewrite:
        # 資料にあって最終稿にない数値は「参考」の1行（要約で省くのは正しいことが多いので候補にしない）。照合の items の
        # not_in_final から作る（diff の詰め。記録の照合の JSON だけから作り直せる）
        reference = [item["text"] for item in items if item.get("classification") == "not_in_final"]
        if reference:
            lines.append("- 参考: 資料にあって最終稿にない数値: " + "、".join(reference))
    lines.append("- " + _MATERIALS_DISCLAIMER)
    return lines


def _mode_checks(mode, materials, treated=False):
    """モードと資料の有無で決まる必要な検査。新規作成で資料の1つを原文とみなしたとき（treated）は
    diff も要る（並びは推敲の資料つきと同じ lint、diff、materials）。"""
    if mode == "rewrite":
        return ["lint", "diff"] + (["materials"] if materials else [])
    return ["lint", "diff", "materials"] if treated else ["lint", "materials"]


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
        self.source_lint_result = None  # 表示用だけ。必要な検査と記録には入れない
        self.source_lint_status = None
        self.diff_result = None      # 子の JSON そのもの
        self.materials_result = None
        self.fact_gaps = None
        self.risks = []              # 意味が変わる恐れ（diff の basis 入りの写しと、照合の unsupported）
        self.diff_risks = None       # diff の basis 入りの写し
        self.texts = {}              # 人が読む形（.txt に書く文。lint と diff は子の JSON から作ったもの）
        self.lint_findings = None    # lint の render_findings() の文
        self.diff_parts = None       # diff の report_parts()
        self.final_changed = False
        self.no_record = False
        self.fail_on = []
        self.fail_on_hits = []
        self.treated = None              # 原文とみなした資料（新規作成）
        self.source_was_final = False    # 原文が、前に最終稿として検査した本文と同じ
        self.state_dir_option = None     # --state-dir で決めた状態フォルダ（{仕上げ} に書く）
        self.doc_type = None             # 文書の種類と読者（正規化した値。lint と diff に渡し、記録と状態の行に残す）
        self.reader = None

    @property
    def diff_source(self):
        """diff の原文（推敲では原文、新規作成では原文とみなした資料）。"""
        return self.source if self.source is not None else self.treated

    def text_unchanged(self):
        """原文と最終稿の本文（text_sha256）が同じか（改行コード、BOM、末尾の改行だけが違うときも真）。"""
        return self.source is not None and self.source.text_sha256 == self.final.text_sha256

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
        """意味が変わる恐れを出す検査（diff、資料との照合）がすべて最後まで動き、途中で最終稿が変わっていないか。そうでなければ、
        件数は出さない（状態の行の meaning_risk= を0件と読ませない。反証で見つけた例。変わる前の版の件数を今の最終稿の件数と読ませない）。"""
        return not self.final_changed and all(
            self.entries[name]["status"] == "ran" for name in self.required if name in _RISK_CHECKS)

    def candidate_total(self):
        """1回目の「候補あり／なし」は、lint、diff、資料との照合の候補の合計で決める。"""
        total = self.fact_gaps["count"] if self.fact_gaps else 0
        for result in (self.lint_result, self.diff_result, self.materials_result):
            if result is not None:
                total += int(result.get("candidate_count") or 0)
        return total


def _context_arguments(doc_type, reader):
    """子の lint と diff に渡す種類と読者の引数（付けたときだけ）。"""
    arguments = []
    if doc_type is not None:
        arguments += ["--doc-type", doc_type]
    if reader is not None:
        arguments += ["--reader", reader]
    return arguments


def _context_problem(parsed, doc_type, reader):
    """子の JSON の context が、渡した種類と読者と合わないときの理由（合えば None）。lint の外した件数は整数に限る
    （3行目に合計を書くため）。"""
    context = parsed["context"]
    if context.get("doc_type") != doc_type or context.get("reader") != reader:
        return "子の JSON の context が、渡した種類と読者と違います"
    skipped = context.get("skipped_by_doc_type", {})
    if parsed.get("format") == "yomiyasu-lint" and not (
            isinstance(skipped, dict) and all(type(value) is int and value >= 0 for value in skipped.values())):
        return "子の JSON の context.skipped_by_doc_type の形が違います"
    return None


def _run_checks(ctx, snapshots, stance, timeout):
    """lint と diff を子プロセスで（並べて）動かし、資料があればプロセスの中で照らす。"""
    lint_module, diff_module = _lint_module(), _diff_module()
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    final_snapshot = snapshots[id(ctx.final)]
    context = _context_arguments(ctx.doc_type, ctx.reader)
    commands = OrderedDict()
    commands["lint"] = ([sys.executable, "-B", os.path.join(_HERE, "yomiyasu_lint.py"), "--json"] + context
                        + [final_snapshot])
    if "diff" in ctx.required:
        command = [sys.executable, "-B", os.path.join(_HERE, "yomiyasu_diff.py"), "--json"]
        if stance is not None:
            command += ["--stance", stance]
        commands["diff"] = command + context + [snapshots[id(ctx.diff_source)], final_snapshot]
    if ctx.diff_source is not None:
        commands["source_lint"] = ([sys.executable, "-B", os.path.join(_HERE, "yomiyasu_lint.py"), "--json"]
                                   + context + [snapshots[id(ctx.diff_source)]])
    targets = {"lint": OrderedDict((("final", ctx.final.sha256),))}
    if ctx.diff_source is not None:
        targets["diff"] = OrderedDict((("source", ctx.diff_source.sha256), ("final", ctx.final.sha256)))
    material_target = OrderedDict()
    if ctx.diff_source is not None:
        # 新規作成で資料を原文とみなしたときも、照合はその資料を原文として行う（推敲の扱い。反証で見つけた例）
        material_target["source"] = ctx.diff_source.sha256
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
                # 原文とみなした資料は原文として渡す。資料にない数値は diff の数値の候補の basis "none" で出し、
                # 照合の意味が変わる恐れに重ねない（同じ値を二重に出さない。反証で見つけた例）
                ctx.materials_result = diff_module.ground(
                    ctx.final.text, [item.text for item in ctx.materials],
                    ctx.diff_source.text if ctx.diff_source is not None else None,
                    labels=[item.label for item in ctx.materials])
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
    if "source_lint" in commands:
        status, code, stdout, stderr, elapsed, error = results["source_lint"]
        ctx.source_lint_status = status
        if status == "ran":
            parsed, problem = _parse_report(stdout, "lint", versions["lint"])
            if parsed is not None:
                problem = _context_problem(parsed, ctx.doc_type, ctx.reader)
            if problem is None:
                ctx.source_lint_result = parsed
            else:
                ctx.source_lint_status = "error"
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
        if parsed is not None:
            problem = _context_problem(parsed, ctx.doc_type, ctx.reader)
            if problem is not None:
                parsed = None
        try:
            if parsed is not None:
                # 人が読む形をここで作っておく。子の JSON の形が違って作れなければ、その検査を error にする（反証で見つけた例）
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
            # diff の詰め: 文体の硬化の検査と勢いの検査の件数と level（完了報告の確認の記録に写す値のもと）。
            # candidate_count は参考（level が info の候補）を含む数なので、見直し候補（level が review）の数も残す。記録だけを
            # 読む使い方でも、見直し候補と参考が混ざった結果（「候補2件、参考1件」）が分かるようにする（反証で見つけた例）
            for key in ("stiffness", "tone", "hedges", "immutable", "politeness", "register"):
                section = parsed.get(key)
                if isinstance(section, dict):
                    entry["summary"][key + "_candidate_count"] = section.get("candidate_count")
                    entry["summary"][key + "_level"] = section.get("level")
                    entry["summary"][key + "_review_count"] = _review_count(section)
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


def _review_count(section):
    """diff の硬化の検査か勢いの検査の結果（section）の、見直し候補（level が review の候補）の数。候補の並びがなければ None
    （反証で見つけた例。記録の summary と verify の照らしで使う）。"""
    candidates = section.get("candidates") if isinstance(section, dict) else None
    if not isinstance(candidates, list):
        return None
    return sum(1 for candidate in candidates if isinstance(candidate, dict) and candidate.get("level") == "review")


def _fail_on_hits(ctx, diff_module):
    """--fail-on に当たった値（指定した順）。meaning-risk は diff の FAIL_ON_KINDS（数値・否定・入れ替え・文の種類・引用の印・
    確度の強まり・状態の語の消え・書き手の約束の足し・許可の言い方の変化・選ぶ範囲の入れ替え・関連から因果への強まり）と、新規作成の資料にない数値、warn と error は
    lint の候補で決める。diff の数え方は --doc-type で変わる（事実や仕様を述べる種類では、確度の2つも数える）。"""
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

def _finalize_text(ctx):
    """1行目の {仕上げ}。--state-dir か環境変数 YOMIYASU_STATE_DIR で状態フォルダを決めて記録したときは、
    verify にも同じ状態フォルダを渡すよう書く（呼び出しごとに環境変数が引き継がれないシェルで、
    案内どおりの verify が別のフォルダを探さないように。反証で見つけた例）。"""
    if ctx.no_record:
        return _FINALIZE_NO_RECORD
    if ctx.final.via == "stdin":
        if ctx.state_dir_option is not None:
            return _FINALIZE_STDIN_STATE_DIR.format('"{}"'.format(ctx.state_dir_option))
        return _FINALIZE_STDIN
    if ctx.state_dir_option is not None:
        return _FINALIZE_STATE_DIR.format('"{}"'.format(ctx.state_dir_option))
    return _FINALIZE_FILE


def _treated_note(ctx):
    """資料を原文とみなしたときの注記。似かたで決めたか前の回から引き継いだかと、diff が最後まで動いたか
    （動かなければ「必要な検査に入れました」）で文を選ぶ（どちらも反証で見つけた例）。"""
    inherited = ctx.treated.treated_by == "previous_attempt"
    if ctx.entries.get("diff", {}).get("status") == "ran":
        return _TREATED_INHERITED_NOTE if inherited else _TREATED_NOTE
    return _TREATED_INHERITED_PENDING_NOTE if inherited else _TREATED_PENDING_NOTE


def _decide(ctx, recorded, problem=None, attempt=None, run_id=None, fix_count=0, same_as_previous=False):
    """状態、1行目、next、状態の行を決める（1行目の表を上から当てはめる）。"""
    finalize = _finalize_text(ctx)
    failed = ctx.failed
    if ctx.final_changed:
        # 検査は読んだときの写しに対して動いたが、今の最終稿に対しては実行していない。正しい次の行動は、
        # 変え終えてからの run のやり直し
        line, following = _FINAL_CHANGED_LINE, "rerun"
    elif failed:
        groups = OrderedDict()
        items = []
        for name, status in failed:
            if name == "final":
                continue
            # 完了報告の「実行しなかった検査」に写す文なので、検査名は完了報告の語にする（反証で見つけた例）
            groups.setdefault(_FAILED_NAMES[status], []).append(_label(name))
            items.append("{}（{}）".format(_label(name), _FAILED_NAMES[status]))
        clauses = ["{}が{}".format("、".join(names), reason) for reason, names in groups.items()]
        # partial のあとは verify をせず、run の2行目と止まった検査を完了報告に書く
        line = ("検査の一部を実行できませんでした（{}）。完了報告の「実行しなかった検査」に「{}」と書いてください。".format(
            "、".join(clauses), "、".join(items)) + _PARTIAL_TAIL)
        following = "report_partial"
    elif not recorded and not ctx.no_record:
        line = ("検査を実行しましたが、記録を書けませんでした（{0}）。--state-dir に書ける場所を指定してもう一度実行するか、"
                "完了報告の「実行しなかった検査」に「記録（{0}）」と書いてください。".format(problem))
        following = "report_unrecorded"
    else:
        if ctx.text_unchanged() or (ctx.source is not None and ctx.diff_result is not None
                                    and ctx.diff_result.get("status") == "no_change"):
            # 本文（text_sha256）が原文と同じ。改行コード、BOM、末尾の改行だけが違うときはそう添える
            note = _TEXT_SAME_NOTE if ctx.source.sha256 != ctx.final.sha256 else ""
            line, following = _NO_CHANGE_LINE.format(note) + finalize, "finalize"
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
        elif _detector_reviews(ctx):
            # 文体の硬化と勢いの見直し候補（level review）は1行目の「候補あり／なし」に数えないが、「候補はない」だけ
            # だと節を見落とす（diff の詰めの直し。反証で見つけた例）。参考（info）だけなら添えない
            line = ("検査を実行しました（1回目）。規則に当たる候補はありませんが、文体の硬化と勢いの見直し候補が{}件あります。"
                    "その節を原文と照らし、全文差分で意図しない変更がないかを確かめ、直すなら1回まで、直さないなら".format(
                        _detector_reviews(ctx)) + finalize)
            following = "review"
        else:
            line = ("検査を実行しました（1回目）。規則に当たる候補はありません。全文差分で意図しない変更がないかを確かめ、"
                    "直すなら1回まで、直さないなら" + finalize)
            following = "review"
        if ctx.diff_result and any((ctx.diff_result.get(key) or {}).get("candidate_count", 0)
                                   for key in ("hedges", "immutable", "politeness", "register")):
            label = "文体の硬化・勢い・慎重表現・値・敬語"
            if (ctx.diff_result.get("register") or {}).get("candidate_count", 0):
                label += "・文体の切り替え"
            line = line.replace("文体の硬化と勢いの見直し候補", label + "の見直し候補")
        if ctx.no_record:
            following = "report_unrecorded"
    if ctx.treated is not None and not ctx.final_changed:
        # 資料の1つを原文とみなして diff も実行した。partial では、partial の案内（「…と書いてください。verify は
        # 実行せず…」）で1行目が終わるように、注記を前に置く（反証で見つけた例）
        note = _treated_note(ctx)
        line = note + line if failed else line + note
    if ctx.source_was_final:
        # 原文を上書きしたか、原文と最終稿を逆に渡した恐れ（2にはしない）
        line = _SOURCE_WAS_FINAL_NOTE + line
    if ctx.fail_on_hits and not failed:
        line = "--fail-on={} の条件に当たりました（終了コード1）。".format(",".join(ctx.fail_on_hits)) + line
    if failed:
        status = "partial"
    else:
        status = "executed" if recorded else "unrecorded"
    reason = None
    if not recorded:
        # --no-record の理由は verify の状態の名前 no_record と重ならない語にする
        reason = "no_record_option" if ctx.no_record else "not_writable"
    token = _status_line(status, "run", run_id if recorded else None, attempt if recorded else None, ctx.final.token(),
                         mode=ctx.mode, doc_type=ctx.doc_type, reader=ctx.reader, checks=",".join(ctx.required),
                         meaning_risk=len(ctx.risks) if ctx.risks_complete() else None,
                         failed=",".join("{}({})".format(name, why) for name, why in failed) or None, reason=reason)
    return status, line, following, token


def _unsupported_count(result, diff_risks=None, diff_module=None):
    """3行目の q（資料にない数値・名前の数）。出力に示した候補と同じ条件で数える（1行目の候補あり・なしと
    食い違わないため。反証で見つけた例）。
    - 名前と、新規作成の数値: 照合の意味が変わる恐れ（unsupported）の数。照合の items の not_in_sources の名前と、数量を
      主張しない「一つ」だけの値を除いた数値の数と同じ。新規作成では照合の meaning_risk_count と同じ数になる。
    - 推敲の数値（原文があるとき、資料を原文とみなしたとき）: 資料にない数値は diff の数値の候補の basis "none" で出し、照合の
      meaning_risks に入れないので、照合の items の not_in_sources の数値のうち、basis "none" の diff の数値の候補に出た
      値の数（反証で見つけた例）。diff_risks は check が basis を入れた diff の候補（diff が最後まで動かなかったときは None で、そのときは
      items の not_in_sources の数値をすべて数える）。"""
    risks = result.get("meaning_risks") or []
    if result.get("mode") != "rewrite":
        return sum(1 for risk in risks if risk.get("kind") == "unsupported" and risk.get("subkind") in ("number", "name"))
    names = sum(1 for risk in risks if risk.get("kind") == "unsupported" and risk.get("subkind") == "name")
    numbers = [item for item in result.get("items", [])
               if item.get("kind") == "number" and item.get("classification") == "not_in_sources"]
    if diff_risks is None or diff_module is None:
        return names + len(numbers)
    shown = set()
    for risk in diff_risks:
        if risk.get("kind") == "number" and risk.get("basis") == "none":
            for text in (risk.get("detail") or {}).get("added") or []:
                shown.update((number["value"], number["unit"]) for number in diff_module.extract_numbers(text))
    return names + sum(1 for item in numbers if _material_number_keys(diff_module, item) & shown)


def _summary_line(ctx, diff_module=None):
    """3行目（実行した検査の要約。完了報告の「実行した検査」に対応する）。最後まで動かなかった検査は並べない
    （1行目で「実行しなかった検査」に書くよう案内する。反証で見つけた例）。1つもなければ「なし」。途中で最終稿が変わったときは、
    今の最終稿に対して実行した検査はない。"""
    if ctx.final_changed:
        return _FINAL_CHANGED_SUMMARY
    parts = []
    failed = dict(ctx.failed)
    if "lint" not in failed:
        where = "最終稿"
        if ctx.doc_type is not None:
            # 種類を付けたときだけ、種類と外した候補の数を書く。読者は検査を変えないので書かない（状態の行にはある）
            skipped = ctx.lint_result["context"].get("skipped_by_doc_type") or {}
            where += "、種類 {}、外した候補{}件".format(ctx.doc_type, sum(skipped.values()))
        parts.append("lint（{}）候補{}件".format(where, ctx.lint_result.get("candidate_count", 0)))
    if "diff" in ctx.required and "diff" not in failed:
        result = ctx.diff_result
        # 新規作成で資料を原文とみなしたときは、どの資料と比べたかを書く
        where = "原文→最終稿" if ctx.source is not None else "資料{}→最終稿".format(ctx.treated.index)
        unchanged = ctx.text_unchanged() or result.get("status") == "no_change"
        parts.append("diff（{}）{} 候補{}件（うち意味が変わる恐れ{}件）".format(
            where, "変更なし" if unchanged else "変更あり", result.get("candidate_count", 0),
            result.get("meaning_risk_count", 0)))
    if "materials" in ctx.required and "materials" not in failed:
        where = "資料{}件".format(len(ctx.materials)) if ctx.mode == "rewrite" else "資料{}件→最終稿".format(len(ctx.materials))
        diff_done = "diff" in ctx.required and "diff" not in failed and ctx.diff_risks is not None
        parts.append("資料との照合（{}）資料にない数値・名前{}件".format(
            where, _unsupported_count(ctx.materials_result, ctx.diff_risks if diff_done else None, diff_module)))
    summary = "実行した検査: " + ("、".join(parts) if parts else "なし")
    if ctx.fact_gaps is not None:
        if ctx.fact_gaps["skipped"]:
            summary += "、事実の穴の候補（種類 {} では出していません）".format(ctx.fact_gaps["skipped"])
        else:
            summary += "、事実の穴の候補{}件".format(ctx.fact_gaps["count"])
    return summary


# 頭の一覧で、検査ごとに並べる候補の数の上限（残りは「ほかN件」）
_HEAD_LIMIT = 3
# 候補があるときに、頭の一覧のすぐ下に置く文（出力の頭だけを読んで、下の節を読まずに終えないため）
_HEAD_NOTE = "候補の中身は下の節にあります。出力を切らずに読んでください。"
# diff の規則の見直し候補の、頭の一覧での名前（行番号を持たない候補。同じ名前はまとめて件数を付ける）
_HEAD_RULE_NAMES = (("structure", "構造"), ("logic", "つながり"), ("endings.changes", "文末の種類"),
                    ("type_changes", "文の種類の印"), ("endings.flags", "文末の立場"), ("bold", "太字"))


def _head_where(old_line, new_line):
    """頭の一覧の行番号（最終稿の行があれば「後N行目」、消えた行なら「元N行目」）。行がなければ空。"""
    if new_line is not None:
        return "後{}行目 ".format(new_line)
    if old_line is not None:
        return "元{}行目 ".format(old_line)
    return ""


def _head_part(label, entries, total):
    """頭の一覧の1つの検査の分（「lint の候補: 」に「L」と行番号と規則の名前を並べ、残りを「（ほか2件）」とする形）。
    entries は（表示、件数）の並び。上限を超えた分と、並べられない候補は「ほかN件」にする。"""
    shown = entries[:_HEAD_LIMIT]
    rest = total - sum(weight for _, weight in shown)
    if not shown:
        return "{}: {}件".format(label, total)
    text = "{}: {}".format(label, "、".join(name for name, _ in shown))
    if rest > 0:
        text += "（ほか{}件）".format(rest)
    return text


def _head_lines(ctx, diff_module):
    """run の3行目のすぐあとに足す行（候補の短い一覧と、下の節を読む案内の2行）。出力の頭だけを読んでも、どの行の
    どの規則に当たったかが分かるようにする。候補がない、または途中で最終稿が変わったときは何も足さない。
    lint、diff（意味が変わる恐れと規則の見直し候補）、文体の硬化などの見直し候補、資料との照合、事実の穴の順に並べ、
    数え方は下の節と同じにする（diff の候補の数は3行目の「候補N件」と同じ）。"""
    if ctx.final_changed:
        return []
    parts = []
    lint = ctx.lint_result
    if lint is not None and lint.get("candidate_count"):
        entries = [("L{} {}".format(finding.get("line"), finding.get("rule")), 1)
                   for finding in lint.get("findings") or []]
        parts.append(_head_part("lint の候補", entries, lint["candidate_count"]))
    result = ctx.diff_result
    if result is not None and ctx.diff_parts is not None:
        entries = []
        risks = ctx.diff_risks if ctx.diff_risks is not None else result.get("meaning_risks") or []
        for risk in risks:
            if (risk.get("kind"), risk.get("subkind")) == ("sentence_type", "marks"):
                continue
            entries.append((_head_where(risk.get("old_line"), risk.get("new_line")) + str(risk.get("kind")), 1))
        for marker in result.get("markers") or []:
            entries.append(("{}の増減".format(marker.get("kind")), 1))
        if result.get("new_words"):
            entries.append(("元の文にない語", 1))
        if result.get("lost_words"):
            entries.append(("消えた語", 1))
        rewritten_only = diff_module._shows_rewritten_only(result)
        endings = result.get("endings") or {}
        for key, name in _HEAD_RULE_NAMES:
            if key in ("logic", "endings.flags", "bold") and not rewritten_only:
                continue
            items = endings.get(key.split(".")[1]) if key.startswith("endings.") else result.get(key)
            if items:
                entries.append((name + ("{}件".format(len(items)) if len(items) > 1 else ""), len(items)))
        total = sum(weight for _, weight in entries)
        if total:
            parts.append(_head_part("diff の候補", entries, total))
        entries = []
        for key in ("stiffness", "tone", "hedges", "immutable", "politeness", "register"):
            section = result.get(key)
            if not isinstance(section, dict) or not isinstance(section.get("candidates"), list):
                continue
            for candidate in section["candidates"]:
                if isinstance(candidate, dict) and candidate.get("level") == "review":
                    entries.append((_head_where(candidate.get("old_line"), candidate.get("new_line")) + key, 1))
        if entries:
            parts.append(_head_part("文体などの候補", entries, len(entries)))
    materials = ctx.materials_result
    if materials is not None and materials.get("candidate_count"):
        names = {"number": "資料にない数値", "name": "資料にない名前"}
        entries = [(_head_where(risk.get("old_line"), risk.get("new_line"))
                    + names.get(risk.get("subkind"), str(risk.get("kind"))), 1)
                   for risk in materials.get("meaning_risks") or []]
        parts.append(_head_part("資料との照合の候補", entries, materials["candidate_count"]))
    gaps = ctx.fact_gaps
    if gaps is not None and not gaps["skipped"] and gaps["count"]:
        entries = [("後{}行目「{}」".format(item["line"], item["match"]), 1) for item in gaps["items"]]
        parts.append(_head_part("事実の穴の候補", entries, gaps["count"]))
    if not parts:
        return []
    return ["。".join(parts), _HEAD_NOTE]


def _detector_value(ctx, diff_module, key):
    """硬化の検査（stiffness）と勢いの検査（tone）の結果の値（「候補なし」「候補{n}件」「参考{n}件」）。diff が最後まで
    動かなかったとき（新規作成で diff を実行しない、diff が止まった、途中で最終稿が変わった）は None。"""
    if ctx.final_changed or ctx.diff_result is None or "diff" not in ctx.required:
        return None
    if ctx.entries.get("diff", {}).get("status") != "ran":
        return None
    summary = getattr(diff_module, "detector_summary", None)
    return summary(ctx.diff_result, key) if summary is not None else None


def _detector_reviews(ctx):
    """文体の硬化と勢いの見直し候補（level review）の数。diff が最後まで動かなかったときは0（_detector_value と同じ条件）。
    数え方は yomiyasu_diff.py の detector_review_count と同じ（diff を読み込まずに数える）。"""
    if ctx.final_changed or ctx.diff_result is None or "diff" not in ctx.required:
        return 0
    if ctx.entries.get("diff", {}).get("status") != "ran":
        return 0
    count = 0
    for key in ("stiffness", "tone", "hedges", "immutable", "politeness", "register"):
        section = ctx.diff_result.get(key)
        if isinstance(section, dict) and isinstance(section.get("candidates"), list):
            count += sum(1 for candidate in section["candidates"]
                         if isinstance(candidate, dict) and candidate.get("level") == "review")
    return count


def _detector_lines(ctx, diff_module):
    """run の5行目のあとに足す行（硬化、勢い、慎重表現、値、敬語の検査。敬語の検査は mail のときだけ）。完了報告に
    「硬化の検査：候補なし」または候補の件数を書くため、確認の記録にそのまま写せる形。値の検査は、意味が変わる恐れに
    入れた引用の印と数値の補いの候補も数える。diff を実行しなかったときは出さない。"""
    lines = []
    for key, label in (("stiffness", "硬化の検査"), ("tone", "勢いの検査"),
                       ("hedges", "慎重表現の検査"), ("immutable", "値の検査"), ("politeness", "敬語の検査"),
                       ("register", "文体の検査")):
        if key == "register" and not (ctx.diff_result or {}).get("register", {}).get("candidate_count", 0):
            continue
        value = _detector_value(ctx, diff_module, key)
        if value is not None:
            lines.append("{}: {}".format(label, value))
    return lines


_CHANGED_WINDOW = 60
_CHANGED_CONTEXT = 30
_CHANGED_LIMIT = 10
# 件数を点数のように読ませない添え書き。増えても同じでも悪くなった印ではない（反証で見つけた例）
_COUNT_NOTE = "lint の規則に当たった数で、点数ではありません。増えても減っても読みやすさの良し悪しは示しません"
_COMPOSE_COUNT_NOTE = "新規作成なので原文の件数はありません。lint の規則に当たった数で、点数ではありません"


def _candidate_counts(ctx):
    source = ctx.source_lint_result if not ctx.final_changed else None
    return OrderedDict((
        ("basis", "lint"), ("source", source["candidate_count"] if source is not None else None),
        ("final", ctx.lint_result["candidate_count"] if ctx.lint_result is not None else None),
        ("source_kind", "original" if ctx.source is not None else "material" if ctx.treated is not None else None),
        ("source_index", ctx.diff_source.index if ctx.diff_source is not None else None),
        ("source_status", ctx.source_lint_status if not ctx.final_changed else None),
        ("source_counts", source["counts"] if source is not None else None)))


def _candidate_lines(ctx, counts):
    if ctx.final_changed or counts["final"] is None:
        return []
    if counts["source_kind"] is None:
        return ["見直し候補: 最終稿 {}件（{}）".format(counts["final"], _COMPOSE_COUNT_NOTE)]
    label = "原文" if counts["source_kind"] == "original" else "資料{}（原文とみなした資料）".format(counts["source_index"])
    number = ("{}件".format(counts["source"]) if counts["source"] is not None
              else "数えられず（{}）".format(_FAILED_NAMES[counts["source_status"]]))
    return ["見直し候補: {} {} → 最終稿 {}件（{}）".format(label, number, counts["final"], _COUNT_NOTE)]


def _joined_lines(lines):
    return "〔改行〕".join(line for line in lines if line.strip()) or "〔空行〕"


def _change_window_start(old, new):
    """共通の頭から、変わり始めた文の頭（遠ければ読点か30字前）へ戻る。"""
    prefix = 0
    for before, after in zip(old, new):
        if before != after:
            break
        prefix += 1
    # 片側が相手の頭そのもの（段落の最後の文を足した・消した）なら、短い側の最後の文から見せる。
    # 共通の頭の終わりまで進めると、短い側が「…」だけになる（反証で見つけた例）
    shorter = min(len(old), len(new))
    if shorter and prefix >= shorter:
        prefix = shorter - 1
    start = 0
    for boundary in re.finditer(r"[。！？!?]|〔改行〕", old[:prefix]):
        start = boundary.end()
    if prefix - start > _CHANGED_CONTEXT:
        comma = old.rfind("、", prefix - _CHANGED_CONTEXT, prefix)
        start = comma + 1 if comma >= 0 else prefix - _CHANGED_CONTEXT
    return start


def _window_text(text, start, other=""):
    end = min(len(text), start + _CHANGED_WINDOW)
    # 表示用の印は分断しない。開始位置を戻すときは相手側にもそろえる。
    # 拡張前の末尾は保ち、広げた分は60字を超えてよい。
    starts = list(re.finditer(r"〔(?:改行|空行)〕", text))
    starts.extend(re.finditer(r"〔(?:改行|空行)〕", other))
    while True:
        expanded = min([start] + [marker.start() for marker in starts
                                 if marker.start() < start < marker.end()])
        if expanded == start:
            break
        start = expanded
    for marker in re.finditer(r"〔(?:改行|空行)〕", text):
        if marker.start() < end < marker.end():
            end = marker.end()
    clipped = start > 0 or end < len(text)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else ""), clipped


def _changed_places(ctx, diff_module, recorded):
    """全文差分と同じ組の短い表示と、JSON 用の件数を返す。"""
    if ctx.final_changed or "diff" not in ctx.required or ctx.diff_result is None:
        return [], None
    full = ctx.diff_result["full_diff"]
    hunks = full["hunks"]
    count = len(hunks)
    shown = min(count, _CHANGED_LIMIT)
    summary = OrderedDict((("count", count), ("shown", shown), ("omitted", count - shown), ("clipped", False)))
    lines = ["■ 直した箇所（{}か所。元と後）".format(count)]
    uneven = False
    if not hunks:
        newline = full["final_newline"]
        if full.get("encoding_notes") or newline["old"] != newline["new"]:
            lines.append("- 行の中身は変わっていません。改行コード、BOM、末尾の改行のどれかだけが違います（下の「■ 全文差分」）。")
        else:
            lines.append("- 原文から変わった箇所はありません。")
        return ["\n".join(lines)], summary
    for hunk in hunks[:_CHANGED_LIMIT]:
        lines.append(diff_module._hunk_heading(hunk))
        tag = hunk["tag"]
        if tag == "replace" and hunk["whitespace_only"]:
            lines.append("  （空白だけの変更。下の「■ 全文差分」の「差:」で見られます）")
            continue
        old, new = _joined_lines(hunk["old_lines"]), _joined_lines(hunk["new_lines"])
        if tag == "replace" and old == new:
            # 空行の数や、本文の「〔改行〕」の字だけが違うと、つないだ形が同じになる（反証で見つけた例）
            lines.append("  （この形では元と後が同じに見えます。空行や「〔改行〕」の字の違いは、下の「■ 全文差分」で見られます）")
            continue
        if tag == "replace" and (sum(1 for line in hunk["old_lines"] if line.strip())
                                 != sum(1 for line in hunk["new_lines"] if line.strip())):
            uneven = True
        windowed_replace = tag == "replace" and max(len(old), len(new)) > _CHANGED_WINDOW
        start = _change_window_start(old, new) if windowed_replace else 0
        for label, value, other, present in (("元", old, new, tag != "insert"),
                                             ("後", new, old, tag != "delete")):
            if present:
                excerpt, clipped = _window_text(value, start, other if windowed_replace else "")
                summary["clipped"] = summary["clipped"] or clipped
                lines.append("  {}: {}".format(label, excerpt))
    guide = ""
    if summary["clipped"]:
        guide += "長い所は、変わり始めの少し前からおよそ60字だけを出しています（「…」は省いた所）。"
    if uneven:
        # 全文差分は空行を手がかりに行を組むので、見出しを足すなどで段落の数が変わると別の段落どうしが並ぶ
        guide += "元と後で行の数が違う所は、別の段落どうしが並んでいることがあります。"
    if summary["omitted"]:
        guide += "初めの10か所だけを出しました（ほか{}か所）。".format(summary["omitted"])
    guide += "省いていない元と後は下の「■ 全文差分」"
    if recorded:
        guide += "と、記録と同じフォルダの {} ".format(ctx.entries["diff"]["text"].split("/")[-1])
    lines.append("- " + guide + "にあります。")
    return ["\n".join(lines)], summary


def _sections(ctx, lint_module, diff_module):
    """run の出力の節（候補が0件の節は出さない。照合の節は照合したときは必ず出す）。"""
    sections = []
    base = ctx.diff_result if ctx.diff_result is not None else diff_module.diff("", "")
    if ctx.risks:
        sections.append(diff_module.report_parts(dict(base, meaning_risks=ctx.risks))["risks"])
    parts = ctx.diff_parts
    if parts is not None and parts["rules"]:
        rules = parts["rules"]
        sections.append(rules.replace("■ 規則の見直し候補（", "■ 差分の見直し候補（diff、", 1))
    # diff の詰め: 文体の硬化の検査と勢いの検査の節（候補があるときだけ）
    for key in ("stiffness", "tone", "hedges", "immutable", "politeness", "register"):
        if parts is not None and parts.get(key):
            sections.append(parts[key])
    if ctx.lint_result is not None and ctx.lint_result.get("candidate_count"):
        sections.append("■ 表現・書式の見直し候補（lint、最終稿、{}件）\n".format(ctx.lint_result["candidate_count"])
                        + ctx.lint_findings)
    if ctx.materials_result is not None:
        sections.append("\n".join(_materials_lines(diff_module, ctx)))
    if ctx.fact_gaps is not None and not ctx.fact_gaps["skipped"]:
        advice = ("この種類では補わず、必要なら書き手への問いにしてください" if ctx.doc_type in ("formal", "paper")
                  else "根拠に中身が書かれているときだけ補い、なければ残すか、書き手への問いにしてください")
        rows = ["■ 事実の穴の候補（{}件。比喩や程度の語だけで、中身や値が書かれていないかもしれない所です。{}。候補は一部だけです）".format(
            ctx.fact_gaps["count"], advice)]
        for item in ctx.fact_gaps["items"][:10]:
            rows.append("- 後{}行目（{}がない「{}」）: {}".format(item["line"], item["need"], item["match"], item["sentence"]))
        if ctx.fact_gaps["count"] > 10:
            rows.append("- ほか{}件".format(ctx.fact_gaps["count"] - 10))
        problem = diff_module._LIST_PROBLEMS.get("fact-gaps")
        if problem:
            rows.append("- 一覧を読めなかったので、内蔵の一覧を使いました（{}）。".format(problem))
        sections.append("\n".join(rows))
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
    """runs/<実行ID>/attempt-<n>.<検査>.json と .txt を書き、Check に名前とハッシュを入れる。
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
    """回の番号を O_CREAT | O_EXCL で確保する。取れなければ1つ増やす（100回まで）。"""
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
    """同じ実行の前の回から、previous、fix_count、前回と同じ最終稿か、を求める。

    previous は直前の読める回（状態によらない）。前回との比べと修正の回数は、最後まで動いた回（result.status が partial で
    ない回）だけで行う（partial の回は候補を出していないことがあるので、そのあとの回を「前回と同じ最終稿」にしない）。
    最終稿は本文のハッシュ（text_sha256）で比べ、改行コード、BOM、末尾の改行だけの違いは修正に数えない。
    fix_count は、最後まで動いた回と今の回を順に並べたとき、本文が1つ前の回と違った回の数（A → B → A は2）。"""
    texts = []
    previous = None
    for number in _attempt_numbers(run_dir):
        if number >= attempt:
            continue
        record = _read_record(os.path.join(run_dir, "attempt-{}.json".format(number)))
        recorded = ((record or {}).get("inputs") or {}).get("final")
        if not isinstance(recorded, dict):
            continue
        previous = OrderedDict((("attempt", number), ("final_sha256", recorded.get("sha256"))))
        result = record.get("result")
        if isinstance(result, dict) and result.get("status") == "partial":
            continue
        texts.append(str(recorded.get("text_sha256")))
    same = bool(texts) and texts[-1] == final.text_sha256
    texts.append(final.text_sha256)
    fix_count = sum(1 for index in range(1, len(texts)) if texts[index] != texts[index - 1])
    return previous, fix_count, same


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
    """回を確保し、レポート、記録、索引を書く。(回, 記録のパス, fix_count, 決めたこと) を返す。
    書けなければ OSError を出す（確保した回のファイルは消す）。"""
    run_id = link["run_id"]
    run_dir = _ensure_dir(state, "runs", run_id)
    attempt, record_path = link.get("reserved") or _reserve_attempt(run_dir, link["attempt"])
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
        # unicode_version は、似かた（NFKC と一般カテゴリ）を求めた Unicode の版。verify は、今の版と違えば似かたを求め直さない
        # （書き換えていない記録を、別の版の Python で invalid_record にしない。反証で見つけた例）
        record["python"] = OrderedDict((("version", platform.python_version()),
                                        ("implementation", platform.python_implementation()),
                                        ("unicode_version", unicodedata.unidata_version)))
        record["inputs"] = OrderedDict((("source", ctx.source.record() if ctx.source is not None else None),
                                        ("materials", [item.record() for item in ctx.materials]),
                                        ("final", ctx.final.record())))
        record["options"] = options
        record["required_checks"] = list(ctx.required)
        record["checks"] = [ctx.entries[name] for name in ctx.required]
        record["materials_summary"] = summary
        record["fact_gaps"] = ctx.fact_gaps
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
        # 索引を残すと、次の回がこの番号を使い直したときに、別の最終稿の記録を指す（反証で見つけた例）
        for path in [record_path] + created:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
    return attempt, record_path, fix_count, decision


# ---- run ----

def _fail_on(values):
    """--fail-on の値を確かめる。(値の並び, None) か (None, 誤りの文)。大文字と小文字、「_」と「-」は区別しない。"""
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
    # Managed runs reserve their attempt under the armed lock before any checks.
    # Remove an unfinished reservation on every exception/signal/early return.
    args._armed_reservation = None
    try:
        return _run_impl(args, parser)
    finally:
        reservation = args._armed_reservation
        if reservation is not None:
            try:
                if os.path.getsize(reservation[1]) == 0:
                    os.unlink(reservation[1])
            except FileNotFoundError:
                pass


def _run_impl(args, parser):
    # 1. 引数を確かめる。ここから入力を読み終えるまで、状態フォルダには何も書かない
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
    try:
        # 種類と読者。状態フォルダに何かを書く前に確かめる
        doc_type, reader = normalize_doc_type(args.doc_type), normalize_reader(args.reader)
    except ValueError as error:
        _error(str(error))
        return 2
    timeout, problem = _timeout(args.timeout)
    if problem:
        _error(problem)
        return 2
    problem = _run_id_problem(args.run_id) if args.run_id is not None else None
    if problem:
        _error(problem)
        return 2
    # 作業ディレクトリは記録の cwd に入れる。消えていれば、何も書かずに2（_run_cli が受ける。反証で見つけた例）
    cwd = _getcwd()
    lint_module, diff_module = _lint_module(), _diff_module()
    stance = None
    if args.stance is not None:
        stance = diff_module.STANCES.get(args.stance)
        if stance is None:
            shown = args.stance if args.stance.strip() else "（空）"
            _error("--stance に使えない値です: {}。使えるのは {} です。".format(shown, "、".join(diff_module.STANCES)))
            return 2
    original_snapshot = None
    snapshot_id = None
    if (not args.stdin and args.source and "-" not in (args.source[0], args.final[0])
            and _same_file(args.source[0], args.final[0])):
        state_for_start = _state_dir(args.state_dir)
        if (not args.new_run and not args.no_record
                and os.path.isdir(os.path.join(state_for_start, "armed"))):
            current_source, source_problem = _read_named("source", 0, args.source[0], None)
            if source_problem:
                _error(source_problem)
                return 2
            armed = _armed_for_source(state_for_start, current_source, args.run_id)
            snapshot_id, original_snapshot = _start_snapshot(
                state_for_start, args.source[0], args.run_id or (armed["run_id"] if armed else None), cwd)
        if original_snapshot is None:
            _error(_SAME_FILE_ERROR)
            return 2
    loaded, problem = _read_inputs(args)
    if problem:
        _error(problem)
        return 2

    ctx = _Context()
    ctx.source, ctx.materials, ctx.final = loaded
    if original_snapshot is not None:
        ctx.source = original_snapshot
    ctx.doc_type, ctx.reader = doc_type, reader
    if not ctx.final.text.strip():
        # 空の最終稿（空白と改行だけの本文も同じ）は検査しない
        _error(_EMPTY_FINAL_ERROR)
        return 2
    final_compact = _compact(ctx.final.text) if ctx.materials else ""
    compacts = [_compact(item.text) for item in ctx.materials]
    if any((item.text_sha256 == ctx.final.text_sha256 or (final_compact and compact == final_compact))
           and not (ctx.source is not None and item.label is not None)
           for item, compact in zip(ctx.materials, compacts)):
        # 資料と最終稿が同じファイルか同じ本文なら、照合が空回りする（推敲でも新規作成でも2）。空白、全角と半角、
        # 書式の文字だけが違う写しも同じ本文とみなす（似かたと同じ下ごしらえ。反証で見つけた例）。
        # 推敲で、出典つきの区切りの資料（抜き書き）だけは除く。短い原稿を根拠の文どおりに直すと、根拠の文と
        # 最終稿が同じになることがあるため（載せ替えの反証で見つけた例）
        _error(_SAME_AS_FINAL_ERROR)
        return 2
    ctx.mode = "rewrite" if ctx.source is not None else "compose"
    if ctx.mode == "compose":
        # 資料の1つが最終稿とよく似ていれば、その資料を原文とみなして diff も実行する
        best, values = _source_like(compacts, final_compact, compacted=True)
        for item, value in zip(ctx.materials, values):
            item.similarity = value
        if best is not None:
            ctx.treated = ctx.materials[best - 1]
            ctx.treated.treated_as_source = True
            ctx.treated.treated_by = "similarity"
    ctx.no_record = args.no_record
    ctx.fail_on = fail_on
    moment = _utc_now()
    session = args.session if args.session is not None else os.environ.get("YOMIYASU_SESSION")
    host = OrderedDict((("session", _host_value(session)),
                        ("codex_thread_id", _host_value(os.environ.get("CODEX_THREAD_ID"))),
                        ("armed_by", None)))
    tools = _tool_versions(args.fact_gaps)
    # doc_type と reader は、文書の種類と読者のオプションを足したときに後ろに足した（キーを足すだけなので RECORD_FORMAT_VERSION は1のまま）
    options = OrderedDict((("stance", stance), ("fail_on", list(fail_on)), ("timeout", timeout),
                           ("doc_type", doc_type), ("reader", reader), ("fact_gaps", args.fact_gaps)))

    # 2. 実行IDと回を決める（読むだけ。別の原文の実行IDなら、何も書かずに2）
    state = None if args.no_record else _state_dir(args.state_dir)
    link = None
    path_key = _path_key(ctx.final, ctx.source, ctx.materials)
    if state is not None:
        problem = _run_id_case_problem(state, args.run_id) if args.run_id is not None else None
        if problem is None:
            link, problem = _link(state, args.run_id or snapshot_id, args.new_run, ctx.mode, ctx.source, ctx.materials, ctx.final,
                                  moment, cwd)
        if problem:
            _error(problem)
            return 2
        managed = _armed_for_source(state, ctx.source, args.run_id, args.new_run)
        if managed is not None and managed["run_id"] == link["run_id"]:
            if _managed_limit(state, managed, ctx, args, link):
                return 1
            host["armed_by"] = "armed/" + managed["run_id"] + ".json"
            if host["session"] is None:
                host["session"] = managed["session_id"]
        if _state_dir_given(args.state_dir):
            ctx.state_dir_option = state
        ctx.source_was_final = ctx.source is not None and _was_checked_final(state, ctx.source)
        if ctx.mode == "compose" and ctx.treated is None:
            # 同じ実行の前の回が原文とみなした資料は、似かたがしきい値を下回っても原文とみなす（直しを重ねて diff が外れない
            # ように。同じ実行は資料の集まりが同じ。反証で見つけた例）
            marked = _previous_treated(state, link["run_id"], link["attempt"])
            for item in ctx.materials if isinstance(marked, dict) else ():
                if item.text_sha256 == marked.get("text_sha256"):
                    ctx.treated = item
                    item.treated_as_source = True
                    item.treated_by = "previous_attempt"
                    break
    ctx.required = _mode_checks(ctx.mode, ctx.materials, treated=ctx.treated is not None)
    if args.fact_gaps:
        # 事実の穴の候補は、管理の上限で止まる run では探さない（上限の判定のあとに置く。載せ替えの反証で見つけた例）
        ctx.fact_gaps = diff_module.fact_gaps(ctx.final.text, doc_type)

    # 3. 入力の写しを置き、検査はこの写しに対して行う。記録を書かないとき（--no-record、書けない）は、
    #    消す前提の一時フォルダに写しを置き、終わったら消す。ほかの場所に記録を逃がさない
    recording = state is not None
    write_problem = None
    inputs = ([ctx.source] if ctx.source is not None else []) + list(ctx.materials) + [ctx.final]
    temporary = None
    try:
        snapshots = None
        if recording:
            try:
                _ensure_state(state, default_place=not _state_dir_given(args.state_dir))
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

    # 6. 出力する。意味が変わる恐れを出す検査が最後まで動かなかったときは、件数を null にする（反証で見つけた例）
    complete = ctx.risks_complete()
    candidate_counts = _candidate_counts(ctx)
    changed_sections, changed_places = _changed_places(ctx, diff_module, recording)
    if status == "partial":
        # 終了コード3のときは標準エラーにも出す（止まった検査と、子の標準エラーの先頭）。標準出力より先に書き、
        # 2>&1 でまとめて読んだときも、パイプと端末のどちらでも最後の行が状態の行になるようにする
        _error("yomiyasu_check.py: " + line)
        for name, entry in ctx.entries.items():
            if entry["status"] != "ran":
                _error("{}: {}".format(name, entry["error"] or entry["status"]))
                if entry["stderr"]:
                    _error(entry["stderr"].rstrip("\n"))
        if sys.stderr is not None:
            try:
                sys.stderr.flush()
            except (OSError, ValueError):
                pass
    if args.json:
        diff_result = None
        if ctx.diff_result is not None:
            diff_result = dict(ctx.diff_result, meaning_risks=ctx.diff_risks)
        result = OrderedDict((
            ("format", "yomiyasu-check-result"), ("format_version", RESULT_FORMAT_VERSION), ("tool_version", __version__),
            ("command", "run"), ("status", status), ("status_line", token), ("message", line), ("next", following),
            ("run_id", link["run_id"] if recording else None), ("attempt", attempt), ("fix_count", fix_count),
            ("mode", ctx.mode), ("context", OrderedDict((("doc_type", ctx.doc_type), ("reader", ctx.reader)))),
            ("record_path", record_path), ("fail_on_hit", bool(ctx.fail_on_hits)),
            ("meaning_risk_count", len(ctx.risks) if complete else None),
            ("fail_on_meaning_risk_count", diff_module.fail_on_count(ctx.risks) if complete else None),
            ("stiffness_check", _detector_value(ctx, diff_module, "stiffness")),
            ("tone_check", _detector_value(ctx, diff_module, "tone")),
            ("hedges_check", _detector_value(ctx, diff_module, "hedges")),
            ("immutable_check", _detector_value(ctx, diff_module, "immutable")),
            ("politeness_check", _detector_value(ctx, diff_module, "politeness")),
            ("lint", ctx.lint_result), ("diff", diff_result), ("materials", ctx.materials_result),
            ("candidate_counts", candidate_counts), ("changed_places", changed_places),
            ("fact_gaps", ctx.fact_gaps)))
        print(json.dumps(result, ensure_ascii=True, indent=1))
    else:
        if recording:
            record_line = "記録: " + record_path
        else:
            record_line = "記録: なし（{}）".format("--no-record" if ctx.no_record else write_problem)
        sections = changed_sections + _sections(ctx, lint_module, diff_module)
        # 記録を書かないときの断りの行（候補がなければ4行目）は「この結果は」（記録がないため）
        disclaimer = _DISCLAIMER if recording else _UNRECORDED_DISCLAIMER
        # 候補があるときは、3行目のすぐあとに候補の短い一覧と案内を足す（2行目の状態の行と3行目は動かさない）
        text = "\n".join([line, token, _summary_line(ctx, diff_module)] + _head_lines(ctx, diff_module)
                         + [disclaimer, record_line]
                         + _detector_lines(ctx, diff_module) + _candidate_lines(ctx, candidate_counts)) + "\n\n"
        if sections:
            text += "\n\n".join(sections) + "\n\n"
        print(text + line + "\n" + token)
    if sys.stdout is not None:
        sys.stdout.flush()
    if status == "partial":
        return 3
    return 1 if ctx.fail_on_hits else 0


# ---- verify（読むだけで、何も書かない。--replay なしでは lint と diff を読み込まない）----

_VERIFY_LINES = {
    # 本文だけを返す指定では確認の記録を付けないので「完了報告を付けるときは」
    "executed": "この最終稿に必要な検査（{}）を実行した記録があり、最終稿のハッシュが記録と合いました。"
                "合格の判定ではありません。完了報告を付けるときは、この出力の2行目を写してください。",
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
# 一覧のファイルが変わったときの tool_changed の1行目（diff の詰めの直し。スクリプトは変えていないのに「スクリプト」と言うと、
# 原因を探しにくい。反証で見つけた例）。{} は変わった一覧のパスを「、」でつないだもの
_LIST_CHANGED_LINE = "記録のあとで、検査に使う語の一覧（{}）が変わりました。yomiyasu_check.py run をもう一度実行してください。"
_SCRIPT_AND_LIST_CHANGED_LINE = ("記録のあとで、検査スクリプトと、検査に使う語の一覧（{}）が変わりました。"
                                 "yomiyasu_check.py run をもう一度実行してください。")


def _tool_changed_line(problems):
    """tool_changed の1行目。変わったのがスクリプトだけなら決まった文、一覧も変わっていれば一覧の名前を書く。"""
    changed = [detail for code, detail in problems if code == "tool_changed"]
    lists = [key for key in _LIST_KEYS + (_FACT_GAPS_KEY,) if key in changed]
    if not lists:
        return _VERIFY_LINES["tool_changed"]
    if len(lists) == len(changed):
        return _LIST_CHANGED_LINE.format("、".join(lists))
    return _SCRIPT_AND_LIST_CHANGED_LINE.format("、".join(lists))


# --replay の作り直しが時間切れのとき（状態は incomplete）。記録が欠けたわけではないので、別の文にする
_REPLAY_TIMEOUT_LINE = ("記録のレポートを作り直す途中で時間切れになりました（{}）。--timeout を長くして verify --replay を"
                        "もう一度実行してください。")
_LINE_ENDINGS_NOTE = "改行コードだけが違います（git の autocrlf やエディタの設定で変わることがあります）。"
# 本文（text_sha256）は記録と同じで、BOM か末尾の改行も違うとき（32 の only_line_endings_differ を広げた）
_TEXT_SAME_VERIFY_NOTE = "本文は記録と同じで、改行コード、BOM、末尾の改行だけが違います。run をもう一度実行しても修正には数えません。"
# 同じ最終稿に、原文は同じで資料の集まりが違う記録が複数あるとき（--source では絞れない）
_AMBIGUOUS_MATERIALS_LINE = ("同じ最終稿に、資料の集まりが違う記録が複数あります。どの検査の記録を使うかを決められないので、"
                             "--run-id を付けて verify を実行してください。")
# このパスの最新の記録と、ハッシュで見つけた記録の原文が違うとき（この最終稿の記録は1つでもある。
# 「同じ最終稿に…複数」の文は事実と合わないので分ける。反証で見つけた例）
_AMBIGUOUS_PLACE_LINE = ("この最終稿の記録と、このパスで最後に検査した記録とで、原文が違います。どちらの記録を使うかを"
                         "決められないので、--run-id か --source を付けて verify を実行してください。")
# 最終稿のパスに別の原文の記録があるかを確かめるときに、記録の原文をさかのぼって調べる記録の数の上限（続けて直す依頼が何回も重なっても、verify を速く保つ）
_LINEAGE_LIMIT = 20
# 記録の検査が時間切れか内部エラーで終わっていたとき（run の partial の扱いに合わせる）
_VERIFY_PARTIAL_LINE = ("記録の {}で終わっています。run をもう一度実行しても同じなら、完了報告に run の出力の2行目を写し、"
                        "「実行しなかった検査」に「{}」と書いてください。")
# 空の最終稿（記録を探さずに no_record）
_VERIFY_EMPTY_LINE = "最終稿が空です。書き終えた最終稿を渡してください。"
_VERIFY_EMPTY_RECORD_LINE = "記録: なし（最終稿が空のため、探していません）"
# no_record の3行目
_NO_RECORD_LINE = "記録: なし（探した状態フォルダ: {}）"
# 見つけた記録の実行に、あとで別の本文を検査した回があるとき（状態は executed のまま）
_NEWER_ATTEMPT_NOTE = "この実行には、あとで検査した別の本文があります。直しが失われていないか確かめてください。"
# --final に渡した本文が、記録では原文か資料として使われているとき
_RECORDED_SOURCE_NOTE = "渡した本文は、記録では原文か資料として使われています。--final には最終稿を渡してください。"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_INDEX_ENTRY = re.compile(r"^(.+)\.([0-9]+)$")
_SINCE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:[.,][0-9]+)?"
                    r"([Zz]|[+-][0-9]{2}:?[0-9]{2})$")
_CHECK_NAMES = ("lint", "diff", "materials")
_EOLS = ("lf", "crlf", "cr", "mixed", "none")
# 記録の必須のキー（記録、Input、Check）
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
        """状態の行の final=。ファイルはバイト列の SHA-256、標準入力は本文のハッシュ。"""
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
    """index/by-final/<sha256>/ か index/by-text/<text_sha256>/ が指す記録（ファイルがないものは飛ばす）。"""
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
    """記録の原文と資料の集まり（新規作成では資料の集まり）。曖昧さを決めるのに使う。形がわからなければ None。
    推敲でも資料の集まりを含める（資料つきの記録と資料なしの記録のどちらの検査を使うかを決められないため）。
    (モード, 原文の本文のハッシュか None, 資料の本文のハッシュの並び)。"""
    if not isinstance(record, dict) or not isinstance(record.get("inputs"), dict):
        return None
    mode, inputs = record.get("mode"), record["inputs"]
    materials = inputs.get("materials")
    if not isinstance(materials, list) or not all(
            isinstance(item, dict) and isinstance(item.get("text_sha256"), str) for item in materials):
        return None
    material_key = tuple(sorted(item["text_sha256"] for item in materials))
    if mode == "rewrite":
        source = inputs.get("source")
        if isinstance(source, dict) and isinstance(source.get("text_sha256"), str):
            return ("rewrite", source["text_sha256"], material_key)
        return None
    if mode == "compose" and materials:
        return ("compose", None, material_key)
    return None


def _final_matches(final_record, final):
    """記録の最終稿と、今の最終稿のハッシュが同じか（ファイルはバイト列、標準入力は本文のハッシュ）。"""
    if not isinstance(final_record, dict):
        return False
    if final.via == "file":
        return final_record.get("sha256") == final.sha256
    return final.text_sha256 is not None and final_record.get("text_sha256") == final.text_sha256


def _record_treated(record):
    """記録で原文とみなした資料（inputs.materials[] の treated_as_source が真の最初のもの）。なければ None。"""
    inputs = record.get("inputs") if isinstance(record, dict) else None
    materials = inputs.get("materials") if isinstance(inputs, dict) else None
    if not isinstance(materials, list):
        return None
    for item in materials:
        if isinstance(item, dict) and item.get("treated_as_source") is True:
            return item
    return None


def _source_matches(record, source):
    """記録の原文と --source が同じか。どちらもファイルならバイト列、標準入力が絡むなら本文のハッシュで比べる。
    新規作成で資料を原文とみなした記録は、その資料と比べる（フックや採点器が原文を知っていて --source を付けるため）。"""
    inputs = record.get("inputs") if isinstance(record, dict) else None
    recorded = inputs.get("source") if isinstance(inputs, dict) else None
    if recorded is None and isinstance(record, dict) and record.get("mode") == "compose":
        recorded = _record_treated(record)
    if not isinstance(recorded, dict):
        return False
    if recorded.get("via") == "file" and source.via == "file":
        return recorded.get("sha256") == source.sha256
    return source.text_sha256 is not None and recorded.get("text_sha256") == source.text_sha256


def _expected_token(final_record, final):
    """final_changed の expected=。今の最終稿と同じ種類のハッシュで出す（標準入力は text-sha256:）。"""
    if final.via == "stdin":
        value = final_record.get("text_sha256")
        return "text-sha256:" + value[:12] if isinstance(value, str) and _HEX64.match(value) else None
    value = final_record.get("sha256")
    return "sha256:" + value[:12] if isinstance(value, str) and _HEX64.match(value) else None


def _normalize_eol(data):
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _only_line_endings(state, final_record, final):
    """記録の最終稿の写しと、今の最終稿が、改行コードだけ違うか（両方を LF にそろえると同じ）。"""
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
    """記録の最終稿と今の最終稿が同じ場所か（パスが null どうしは同じとみなす）。"""
    recorded = final_record.get("path")
    if final.path is None or recorded is None:
        return final.path is None and recorded is None
    return isinstance(recorded, str) and _same_path(recorded, final.path)


def _ambiguity(items, kind=None):
    """ambiguous の値。(実行IDの並び（新しい順、重なりなし）, 曖昧さの種類)。種類は "materials"（原文は同じで資料の集まり
    だけが違う）、"source"（原文が違う）、"place"（このパスに別の原文の記録がある。kind で渡す）。"""
    ordered = sorted(items, key=lambda item: item.order(), reverse=True)
    run_ids = []
    for item in ordered:
        if item.run_id not in run_ids:
            run_ids.append(item.run_id)
    if kind is None:
        origins = set(_origin(item.record) for item in items)
        materials_only = None not in origins and len(set(origin[:2] for origin in origins)) == 1 \
            and all(origin[0] == "rewrite" for origin in origins)
        kind = "materials" if materials_only else "source"
    return run_ids, kind


def _place_origin(record):
    """最終稿のパスの記録どうしで比べる原文。推敲は原文、新規作成で原文とみなした資料はその資料（どちらも ("text", 本文のハッシュ)）、
    原文とみなした資料のない新規作成は資料の集まり（新規作成では資料を原文とする）。推敲の資料の集まりは比べない
    （原文が同じなら今のまま。反証で見つけた例）。形がわからなければ None。"""
    if not isinstance(record, dict) or not isinstance(record.get("inputs"), dict):
        return None
    inputs = record["inputs"]
    if record.get("mode") == "rewrite":
        item = inputs.get("source")
    elif record.get("mode") == "compose":
        item = _record_treated(record)
        if item is None:
            materials = inputs.get("materials")
            if not isinstance(materials, list) or not materials or not all(
                    isinstance(entry, dict) and isinstance(entry.get("text_sha256"), str) for entry in materials):
                return None
            return ("materials", tuple(sorted(entry["text_sha256"] for entry in materials)))
    else:
        return None
    if isinstance(item, dict) and isinstance(item.get("text_sha256"), str):
        return ("text", item["text_sha256"])
    return None


def _continues_to(state, record, target):
    """記録の原文（原文とみなした資料を含む）から、その本文を最終稿として検査した記録へさかのぼり（_LINEAGE_LIMIT
    件まで）、本文のハッシュ target に行き着くか。同じ文書を続けて直し、前の最終稿の場所（推敲の原文の場所）へ写した流れ
    （原文の場所に写す手順。反証で見つけた例）。"""
    pending = [record]
    seen = set()
    looked = 0
    while pending and looked < _LINEAGE_LIMIT:
        origin = _place_origin(pending.pop(0))
        looked += 1
        if origin is None or origin[0] != "text" or origin[1] in seen:
            continue
        if origin[1] == target:
            return True
        seen.add(origin[1])
        pending.extend(item.record for item in _index_found(state, "by-text", origin[1]) if item.status == "ok")
    return False


def _other_origin_at_place(state, final, found):
    """今の最終稿のパスの by-path の最新の記録が、ハッシュで見つけた記録と別の原文なら、その記録（_Found）。
    原文が同じか、見つけた記録の原文をさかのぼるとその記録の最終稿に行き着く（続けて直して原文の場所へ写した）か、
    パスの記録がないか、読めなければ None（検査ずみの最終稿を別のファイルの場所へ写す流れと、原文の場所へ写す流れは今のまま）。"""
    if final.via != "file":
        return None
    mine = _place_origin(found.record)
    if mine is None:
        return None
    key = _sha256(_place(final.path).encode("utf-8", "surrogateescape"))
    for found_id, number in _by_path_entries(state, key):
        item = _Found(state, found_id, number)
        theirs = _place_origin(item.record) if item.status == "ok" else None
        if theirs is None:
            continue
        if theirs == mine:
            return None
        target = (item.final() or {}).get("text_sha256")
        if isinstance(target, str) and _continues_to(state, found.record, target):
            return None
        return item
    return None


def _find(state, final, run_id, source):
    """記録を探す。("found", _Found) か ("ambiguous", [実行ID]) か ("final_changed" | "wrong_file", _Found)
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
            pool = narrowed or pool  # 絞れなければ最新の記録を使い、あとの照らしで other_source にする
        origins = set(_origin(item.record) for item in pool)
        if len(origins) > 1:
            return "ambiguous", _ambiguity(pool)
        best = max(pool, key=lambda item: item.order())
        if source is None:
            # 検査ずみの最終稿を、別の原文の記録があるパスへ写したときは、どちらの記録かを決められない
            other = _other_origin_at_place(state, final, best)
            if other is not None:
                return "ambiguous", _ambiguity([best, other], kind="place")
        return "found", best

    # ハッシュで見つからないとき、同じ場所の記録があれば final_changed
    if final.via == "file":
        place = _place(final.path)
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



def _fact_gaps_shape(gaps):
    if not isinstance(gaps, dict) or set(gaps) != {"count", "skipped", "by_kind", "items"}:
        return False
    count, skipped, kinds, items = (gaps[key] for key in ("count", "skipped", "by_kind", "items"))
    if (type(count) is not int or count < 0 or skipped not in (None, "essay", "promo")
            or not isinstance(kinds, dict) or not isinstance(items, list) or len(items) != min(count, 20)):
        return False
    if any(kind not in ("degree", "change", "effect", "figure") or type(n) is not int or n <= 0
           for kind, n in kinds.items()) or sum(kinds.values()) != count:
        return False
    if skipped and (count or kinds or items):
        return False
    return all(isinstance(item, dict) and item.get("kind") in kinds
               and type(item.get("line")) is int and item["line"] >= 1
               and all(isinstance(item.get(key), str) for key in ("sentence", "match", "need"))
               and len(item["sentence"]) <= 80 for item in items)

def _record_shape(record):
    """記録の必須のキーと型。食い違ったキーの名前の並び（空なら形は合っている）。"""
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
        if role == "material":
            label = item.get("label")
            need(label is None or (is_text(label) and len(label) <= 200 and ">>>" not in label
                                  and "\n" not in label and "\r" not in label), name + ".label")
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
    # 一覧のファイルのキー（diff の詰めの直し）は、あるときだけ形を確かめる（このキーを足す前の記録にはない）
    need(isinstance(tools, dict) and all(
        isinstance(tools.get(name), dict) and text_or_null(tools[name].get("version"))
        and text_or_null(tools[name].get("sha256")) for name in _TOOL_NAMES) and all(
        isinstance(tools[key], dict) and tools[key].get("version") is None and text_or_null(tools[key].get("sha256"))
        for key in _LIST_KEYS + (_FACT_GAPS_KEY,) if key in tools), "tools")
    python = record.get("python")
    # unicode_version は、このキーを足す前の記録にはないので、あるときだけ型を確かめる（反証で見つけた例）
    need(isinstance(python, dict) and is_text(python.get("version")) and is_text(python.get("implementation"))
         and ("unicode_version" not in python or is_text(python["unicode_version"])), "python")
    inputs = record.get("inputs")
    if need(isinstance(inputs, dict) and all(key in inputs for key in ("source", "materials", "final")), "inputs"):
        if mode == "rewrite" or inputs["source"] is not None:
            check_input(inputs["source"], "inputs.source", "source", 0)
        materials = inputs["materials"]
        if need(isinstance(materials, list) and (mode != "compose" or bool(materials)), "inputs.materials"):
            for number, item in enumerate(materials, 1):
                name = "inputs.materials[{}]".format(number)
                check_input(item, name, "material", number)
                if isinstance(item, dict):
                    # 資料を原文とみなした印（このキーを足す前の記録にはないので、あるときだけ型を確かめる）。印は新規作成の1つだけ
                    treated = item.get("treated_as_source", False)
                    similarity = item.get("similarity")
                    need(type(treated) is bool and (mode == "compose" or treated is False), name + ".treated_as_source")
                    need(similarity is None or (type(similarity) in (int, float) and 0 <= similarity <= 1),
                         name + ".similarity")
                    # 決め方（反証で見つけた例。このキーを足す前の記録にはない）。印があれば決め方があり、なければ null
                    if "treated_by" in item:
                        treated_by = item["treated_by"]
                        need((treated_by in _TREATED_BY) if treated is True else (treated_by is None),
                             name + ".treated_by")
            need(sum(1 for item in materials if isinstance(item, dict) and item.get("treated_as_source") is True) <= 1,
                 "inputs.materials.treated_as_source")
        check_input(inputs["final"], "inputs.final", "final", 0)
        if mode == "compose":
            need(inputs["source"] is None, "inputs.source")
    options = record.get("options")
    # doc_type と reader は、このキーを足す前の記録にはないので、ないときは値なしとして読む。あるときは正規化した値か null
    need(isinstance(options, dict) and text_or_null(options.get("stance"))
         and isinstance(options.get("fail_on"), list) and all(is_text(value) for value in options["fail_on"])
         and type(options.get("timeout")) in (int, float)
         and _known_value(options.get("doc_type"), DOC_TYPES) and _known_value(options.get("reader"), READER_LEVELS),
         "options")
    if isinstance(options, dict):
        need(type(options.get("fact_gaps", False)) is bool, "options.fact_gaps")
        gaps = record.get("fact_gaps")
        if options.get("fact_gaps"):
            need(_fact_gaps_shape(gaps), "fact_gaps")
        else:
            need(gaps is None, "fact_gaps")
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
        # モードと資料の有無で決まる検査の外にある項目は、run が書かない形。新規作成の記録に diff の項目が
        # あると、--replay が原文のない記録の diff を作り直そうとして落ちる（反証で見つけた例）
        # 新規作成で資料を原文とみなした記録には diff がある
        if mode in ("rewrite", "compose") and isinstance(inputs, dict) and isinstance(inputs.get("materials"), list):
            allowed = _mode_checks(mode, inputs["materials"], treated=_record_treated(record) is not None)
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


def _known_value(value, rows):
    """記録の options の種類か読者が、値なし（null）か、正規化した使える値か。"""
    return value is None or (isinstance(value, str) and any(row[0] == value for row in rows))


def _record_context(record):
    """記録の options の種類と読者（このキーを足す前の記録は値なし）。"""
    options = record["options"]
    return options.get("doc_type"), options.get("reader")


def _required_for(record, treated=None):
    """必要な検査（モードと資料の有無で決まる）と、記録の required_checks を合わせたもの。新規作成で資料を原文と
    みなしたときは diff も要る。treated を渡さなければ記録の印で決める。"""
    if treated is None:
        treated = _record_treated(record) is not None
    expected = _mode_checks(record["mode"], record["inputs"]["materials"], treated=treated)
    return expected + [name for name in record["required_checks"] if name not in expected]


def _diff_source_item(record):
    """記録の diff の原文の Input（推敲では原文、新規作成では原文とみなした資料）。なければ None。"""
    source = record["inputs"]["source"]
    if isinstance(source, dict):
        return source
    return _record_treated(record)


def _expected_target(record, name):
    """各検査の target に入るはずのハッシュ（run の _run_checks と同じ形）。"""
    inputs = record["inputs"]
    final = inputs["final"]["sha256"]
    # diff と照合の原文（推敲では原文、新規作成では原文とみなした資料。反証で見つけた例）
    item = _diff_source_item(record)
    source = item["sha256"] if item is not None else None
    if name == "lint":
        return {"final": final}
    if name == "diff":
        return {"source": source, "final": final}
    target = {"materials": [entry["sha256"] for entry in inputs["materials"]], "final": final}
    if source is not None:
        target["source"] = source
    return target


def _snapshot_text(state, item):
    """記録の Input の写しを読んで、decode_source の本文を返す。読めないか、ハッシュが合わないか、UTF-8 でなければ None。"""
    try:
        with open(os.path.join(state, "inputs", item["sha256"] + ".bin"), "rb") as handle:
            data = handle.read()
    except (OSError, KeyError, TypeError):
        return None
    if _sha256(data) != item.get("sha256"):
        return None
    try:
        return decode_source(data)[0]
    except UnicodeDecodeError:
        return None


def _treated_again(state, record, run_id, attempt):
    """新規作成の記録の写しから、原文とみなす資料の番号と決め方を求め直す（印を消した記録を見つけるため）。
    似かたがしきい値に届かなければ、同じ実行の前の回の記録の印を引き継ぐ（run と同じ決め方。反証で見つけた例）。
    (求められたか, 番号 or None, 決め方 or None)。推敲の記録と、写しを読めないときは (False, None, None)。"""
    if record["mode"] != "compose":
        return False, None, None
    inputs = record["inputs"]
    final = _snapshot_text(state, inputs["final"])
    materials = [_snapshot_text(state, item) for item in inputs["materials"]]
    if final is None or any(text is None for text in materials):
        return False, None, None
    best = _source_like(materials, final)[0]
    if best is not None:
        return True, best, "similarity"
    marked = _previous_treated(state, run_id, attempt)
    if isinstance(marked, dict):
        for index, item in enumerate(inputs["materials"], 1):
            if item.get("text_sha256") == marked.get("text_sha256"):
                return True, index, "previous_attempt"
    return True, None, None


def _treated_label(index, treated_by):
    """problems の詳しくに書く、原文とみなす資料（「資料1」「資料1（前の回から引き継ぎ）」「なし」）。"""
    if index is None:
        return "なし"
    return "資料{}{}".format(index, "（前の回から引き継ぎ）" if treated_by == "previous_attempt" else "")


def _recheck_problem(record, current_tools):
    """verify が、原文とみなす資料を写しから求め直してよいか。よければ None。記録を作ったときと Unicode の版（NFKC と一般
    カテゴリの結果が変わる）か check（しきい値と測り方）が違えば、その理由（"unicode" か "tool"）を返し、記録の印を使う
    （印は record_digest で守られている。check が違うときは tool_changed になる。反証で見つけた例）。
    unicode_version のない記録（このキーを足す前のもの）は求め直す。"""
    version = record["python"].get("unicode_version")
    if version is not None and version != unicodedata.unidata_version:
        return "unicode"
    if record["tools"]["yomiyasu_check.py"].get("sha256") != current_tools["yomiyasu_check.py"]["sha256"]:
        return "tool"
    return None


def _report_value(state, entry):
    """ハッシュを確かめた検査のレポート（.json）の値。読めないか、ハッシュが合わないか、JSON のオブジェクトでなければ None
    （そのときは、あとの照らしで report の食い違いにする）。"""
    report = entry.get("report")
    if not isinstance(report, str) or not report.startswith("runs/"):
        return None
    try:
        with open(os.path.join(state, *report.split("/")), "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if _sha256(data) != entry.get("report_sha256"):
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _summary_problems(state, record, required):
    """記録の件数（checks[].summary、materials_summary、result）を、ハッシュを確かめたレポートの件数と
    照らす（--replay なしでも。lint と diff は読み込まない）。食い違ったものの名前の並び。result の件数は、必要な検査
    （required）のレポートがすべて読めたときだけ照らす（欠けた検査は、別の照らしで incomplete にする）。"""
    wrong = []
    reports = {}
    for entry in record["checks"]:
        if entry["status"] == "ran":
            value = _report_value(state, entry)
            if value is not None:
                reports[entry["name"]] = (entry, value)

    def compare(name, recorded, expected):
        if recorded != expected or type(recorded) is not type(expected):
            wrong.append(name)

    risks = 0
    fail_on = 0
    context = list(_record_context(record))
    for name in ("lint", "diff", "materials"):
        if name not in reports:
            continue
        entry, value = reports[name]
        summary = entry["summary"] if isinstance(entry["summary"], dict) else {}
        if name in ("lint", "diff"):
            # 記録の種類と読者（options）を、レポートの context と照らす（digest を計算し直して種類を書き換えた記録を、
            # --replay なしでも見つける。context のないレポートは種類と読者のオプションを足す前のもので、値なしとして読む）
            found = value.get("context") if isinstance(value.get("context"), dict) else {}
            compare(name + ".context", context, [found.get("doc_type"), found.get("reader")])
        if name == "lint":
            compare("lint.candidate_count", summary.get("candidate_count"), value.get("candidate_count"))
            compare("lint.counts", summary.get("counts"), value.get("counts"))
        elif name == "diff":
            full = value.get("full_diff")
            hunks = (full.get("hunks") or []) if isinstance(full, dict) else None
            for key in ("status", "candidate_count", "meaning_risk_count", "fail_on_meaning_risk_count"):
                compare("diff." + key, summary.get(key), value.get(key))
            # 硬化の検査と勢いの検査（diff の詰めで足した。このキーを足す前の記録にはないので、あるときだけ照らす）。
            # 見直し候補の数（review_count）は、2回目の反証の直し（反証で見つけた例）で足した
            for key in ("stiffness", "tone", "hedges", "immutable", "politeness", "register"):
                section = value.get(key) if isinstance(value.get(key), dict) else {}
                for field in ("candidate_count", "level"):
                    name = "{}_{}".format(key, field)
                    if name in summary:
                        compare("diff." + name, summary.get(name), section.get(field))
                name = key + "_review_count"
                if name in summary:
                    compare("diff." + name, summary.get(name), _review_count(section))
            compare("diff.hunk_count", summary.get("hunk_count"), len(hunks) if isinstance(hunks, list) else None)
            found = value.get("meaning_risks")
            risks += len(found) if isinstance(found, list) else 0
            fail_on += value.get("fail_on_meaning_risk_count") if type(value.get("fail_on_meaning_risk_count")) is int else 0
        else:
            items = value.get("items") if isinstance(value.get("items"), list) else []
            classes = [item.get("classification") for item in items if isinstance(item, dict)]
            for key in ("candidate_count", "meaning_risk_count"):
                compare("materials." + key, summary.get(key), value.get(key))
            for key in ("from_materials", "not_in_sources", "dropped_certainty"):
                compare("materials." + key, summary.get(key), classes.count(key))
                recorded = record["materials_summary"] if isinstance(record["materials_summary"], dict) else {}
                compare("materials_summary." + key, recorded.get(key), classes.count(key))
            found = value.get("meaning_risks") if isinstance(value.get("meaning_risks"), list) else []
            risks += len(found)
            # 照合の意味が変わる恐れは kind unsupported だけで、--fail-on=meaning-risk が数えるのは数値
            fail_on += sum(1 for risk in found if isinstance(risk, dict) and risk.get("subkind") == "number")
    if all(name in reports for name in required):
        result = record["result"]
        compare("result.meaning_risk_count", result.get("meaning_risk_count"), risks)
        if "fail_on_meaning_risk_count" in result:
            compare("result.fail_on_meaning_risk_count", result.get("fail_on_meaning_risk_count"), fail_on)
    return wrong


class _Material(object):
    """--replay で照合の .txt を作り直すときの資料（_materials_lines が text を読む）。"""

    def __init__(self, text):
        self.text = text


class _ReplayError(Exception):
    """--replay で子プロセスを起動できない、待てない、またはシグナルで止まった。記録の食い違いではないので、
    not_reproducible にせず、verify の内部の誤り（終了コード3）にする（反証で見つけた例）。"""


def _replay(state, record, timeout):
    """写しに対して記録と同じ引数で lint と diff を子プロセスで動かし、照合はプロセスの中で作り直して、
    レポート（.json と .txt）のハッシュを記録と比べる。[(問題のコード, 詳しく)] と replay の値を返す。
    子を動かせなかったときは _ReplayError を出す。"""
    lint_module, diff_module = _lint_module(), _diff_module()
    inputs = record["inputs"]
    entries = OrderedDict((entry["name"], entry) for entry in record["checks"] if entry["status"] == "ran")

    def snapshot(item):
        return os.path.join(state, "inputs", item["sha256"] + ".bin")

    # 記録と同じ種類と読者を付ける（付けないと lint のレポートが合わない）
    context = _context_arguments(*_record_context(record))
    commands = OrderedDict()
    if "lint" in entries:
        commands["lint"] = ([sys.executable, "-B", os.path.join(_HERE, "yomiyasu_lint.py"), "--json"] + context
                            + [snapshot(inputs["final"])])
    if "diff" in entries:
        command = [sys.executable, "-B", os.path.join(_HERE, "yomiyasu_diff.py"), "--json"]
        if record["options"].get("stance") is not None:
            command += ["--stance", record["options"]["stance"]]
        # 新規作成で資料を原文とみなした記録は、その資料の写しと比べる
        commands["diff"] = command + context + [snapshot(_diff_source_item(record)), snapshot(inputs["final"])]
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
                # 照合の原文は run と同じ（推敲では原文、新規作成では原文とみなした資料。反証で見つけた例）
                source_item = _diff_source_item(record)
                source_text = text_of(source_item) if source_item is not None else None
                material_texts = [text_of(item) for item in inputs["materials"]]
                final_text = text_of(inputs["final"])
                rebuilt["materials"] = (diff_module.ground(final_text, material_texts, source_text,
                    labels=[item.get("label") for item in inputs["materials"]]), material_texts)
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

    if record["options"].get("fact_gaps"):
        # 一覧は通常の verify の 9 でも比べる（変われば tool_changed で、ここには来ない）。ここでは念のため、候補が偶然同じでも、
        # 別の一覧による再現を一致とはしない。
        key = _FACT_GAPS_KEY
        if _list_sha256(_tool_versions(True), key) != _list_sha256(record["tools"], key):
            problems.append(("replay_mismatch", key))
        try:
            with open(snapshot(inputs["final"]), "rb") as handle:
                gap_text = decode_source(handle.read())[0]
            gaps = diff_module.fact_gaps(gap_text, record["options"].get("doc_type"))
            if gaps != record.get("fact_gaps"):
                problems.append(("replay_mismatch", "fact_gaps"))
        except Exception as error:
            problems.append(("replay_error", "fact_gaps: {}".format(error)))

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


def _newer_attempt(state, found, record):
    """見つけた記録より後の回で、別の本文（text_sha256）を検査した回の番号（いちばん新しいもの）。なければ None。"""
    mine = record["inputs"]["final"].get("text_sha256")
    for number in reversed(_attempt_numbers(os.path.join(state, "runs", found.run_id))):
        if number <= found.attempt:
            break
        later = _read_record(os.path.join(state, "runs", found.run_id, "attempt-{}.json".format(number)))
        inputs = later.get("inputs") if isinstance(later, dict) else None
        recorded = inputs.get("final") if isinstance(inputs, dict) else None
        if isinstance(recorded, dict) and recorded.get("text_sha256") != mine:
            return number
    return None


def _recorded_as_input(state, final):
    """--final に渡した本文が、記録では原文か資料として使われているか。最終稿の記録が見つからなかった
    ときにだけ呼ぶ。inputs/ に写しがあり、読める記録の inputs.source か inputs.materials にこのハッシュがあるときだけ真。
    写しだけを見ると、記録を書けなかった run が置いた最終稿の写しで誤って案内する（反証で見つけた例）。"""
    if not os.path.isfile(os.path.join(state, "inputs", final.sha256 + ".bin")):
        return False
    runs = os.path.join(state, "runs")
    try:
        run_ids = sorted(name for name in os.listdir(runs) if _RUN_ID.match(name))
    except OSError:
        return False
    for run_id in run_ids:
        run_dir = os.path.join(runs, run_id)
        for number in _attempt_numbers(run_dir):
            record = _read_record(os.path.join(run_dir, "attempt-{}.json".format(number)))
            inputs = record.get("inputs") if isinstance(record, dict) else None
            if not isinstance(inputs, dict):
                continue
            items = [inputs.get("source")] + (inputs.get("materials") if isinstance(inputs.get("materials"), list) else [])
            if any(isinstance(item, dict) and item.get("sha256") == final.sha256 for item in items):
                return True
    return False


def _verify_record(state, found, final, source, since, replay, timeout):
    """見つけた記録を確かめる。(状態, [(コード, 詳しく)], replay の値, 形を確かめられたか)。
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
    # 新規作成の記録は、写しから原文とみなす資料を求め直す。印を消して diff を外した記録を完了と扱わない
    fact_gaps_recorded = isinstance(record.get("options"), dict) and record["options"].get("fact_gaps") is True
    current_tools = _tool_versions(fact_gaps_recorded)
    recorded_treated = _record_treated(record)
    treated = recorded_treated is not None
    reason = _recheck_problem(record, current_tools) if record["mode"] == "compose" else None
    if reason is None:
        known, again, again_by = _treated_again(state, record, found.run_id, found.attempt)
    else:
        known, again, again_by = False, None, None
        if reason == "unicode":
            fail(None, "treated_not_rechecked", "Unicode の版が記録（{}）と今（{}）で違うので、原文とみなす資料を写しから"
                 "求め直していません".format(record["python"].get("unicode_version"), unicodedata.unidata_version))
    if known:
        recorded_by = recorded_treated.get("treated_by", again_by) if recorded_treated is not None else None
        if (again is None) != (recorded_treated is None) or (
                again is not None and (recorded_treated.get("index") != again or recorded_by != again_by)):
            fail("invalid_record", "treated_as_source",
                 "写しから求め直すと、原文とみなす資料は{}です（記録は{}）".format(
                     _treated_label(again, again_by),
                     _treated_label(recorded_treated.get("index"), recorded_by) if recorded_treated is not None else "なし"))
        treated = again is not None
    # 記録の件数を、ハッシュを確かめたレポートの件数と照らす
    mismatched = _summary_problems(state, record, _required_for(record, treated=treated))
    if mismatched:
        fail("invalid_record", "summary_mismatch", "記録の件数がレポートと合いません: " + ", ".join(mismatched))
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
    for name in _required_for(record, treated=treated):
        entry = entries.get(name)
        if entry is None or entry["status"] != "ran":
            fail(None, "missing_check", name if entry is None else "{}（{}）".format(name, entry["status"]))
            missing.append(name)
        elif entry["target"] != _expected_target(record, name):
            fail(None, "check_target", "{} の target が inputs と違います".format(name))
            missing.append(name)
    if missing:
        # 記録の項目があり、時間切れか内部エラーで終わっていた検査だけなら、partial の記録
        stopped = [(name, entries[name]["status"]) for name in missing
                   if name in entries and entries[name]["status"] in _FAILED_NAMES]
        if len(stopped) == len(missing):
            states.append(("stopped", stopped))
        else:
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
    # 9. スクリプトと一覧のファイルと SKILL.md。一覧は、記録のときにあったか、今あるか、中身が同じかを比べる（diff の詰めの直し。
    # 一覧は diff の結果を変える入力なので、変われば tool_changed。反証で見つけた例）。fact-gaps.txt は、--fact-gaps を付けた
    # run の記録だけで比べる（付けなかった run の結果は、この一覧で変わらない）
    for name in _TOOL_NAMES:
        if current_tools[name]["sha256"] != record["tools"][name]["sha256"]:
            fail("tool_changed", "tool_changed", name)
    for key in _LIST_KEYS + ((_FACT_GAPS_KEY,) if fact_gaps_recorded else ()):
        if _list_sha256(current_tools, key) != _list_sha256(record["tools"], key):
            fail("tool_changed", "tool_changed", key)
    if _skill_info()["skill_md_sha256"] != record["skill"]["skill_md_sha256"]:
        fail(None, "skill_changed", "SKILL.md のハッシュが記録と違います")
    # 同じ実行に、あとで別の本文を検査した回があれば知らせる（状態は変えない）
    if trusted:
        newer = _newer_attempt(state, found, record)
        if newer is not None:
            fail(None, "newer_attempt_differs", "{}回目で別の本文を検査しています".format(newer))
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


def _record_summary_count(record, name, key):
    if record is not None:
        for entry in record["checks"]:
            if entry["name"] == name:
                value = (entry.get("summary") or {}).get(key)
                return value if type(value) is int else None
    return None


def _verified_contents_line(final_count, changed_count, required):
    final = "{}件".format(final_count) if final_count is not None else "不明"
    line = "記録の中身: 見直し候補 最終稿 " + final
    if "diff" in required:
        changed = "{}か所".format(changed_count) if changed_count is not None else "不明"
        return line + "、直した箇所 " + changed + "（原文の件数と元と後は run の出力にあります）"
    return line + "（新規作成）"


def _verify(args, parser, _final=None, _return=False):
    # 1. 引数を確かめ、最終稿のハッシュを先に計算する。誤りなら2で、何も書かない
    if args.state_dir is not None and not args.state_dir.strip():
        parser.error("--state-dir に空の値は使えません")
    if args.final == "-" and args.source == "-":
        parser.error("標準入力（-）は1か所だけに使えます")
    problem = _run_id_problem(args.run_id) if args.run_id is not None else None
    if problem:
        _error(problem)
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
    if _final is None and "-" in (args.final, args.source):
        stdin_data, problem = _read_stdin_bytes()
        if problem:
            _error(problem)
            return 2
    final, problem = (_final, None) if _final is not None else _read_target(args.final, stdin_data)
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
    if args.run_id is not None and os.path.isdir(state):
        # 大文字と小文字だけが違う実行IDは、大文字と小文字を区別しないファイルシステムで同じフォルダになる
        problem = _run_id_case_problem(state, args.run_id)
        if problem:
            _error(problem)
            return 2
    found = None
    run_ids = []
    ambiguity = None
    expected = None
    problems = []
    replayed = "skipped"
    trusted = False
    empty = final.data == b"" or (final.text_sha256 is not None and not decode_source(final.data)[0].strip())
    if empty:
        # 空の最終稿（空白と改行だけの本文も同じ）は、記録があっても executed にしない
        status = "no_record"
        problems.append(("empty_final", "最終稿が空です"))
    elif not os.path.isdir(state):
        status = "no_record"
        problems.append(("no_state_dir", "状態フォルダがありません: " + state))
    else:
        # 3. 記録を探す
        kind, value = _find(state, final, args.run_id, source)
        if kind == "no_record":
            status = "no_record"
            problems.append(("no_record", "この最終稿の記録が見つかりません"))
            if _recorded_as_input(state, final):
                problems.append(("is_recorded_source", "この本文は記録で原文か資料として使われています"))
        elif kind == "ambiguous":
            status, (run_ids, ambiguity) = "ambiguous", value
            problems.append(("ambiguous", "{}: {}".format(
                {"materials": "資料の集まりの違う実行", "source": "原文の違う実行",
                 "place": "このパスで最後に検査した記録と原文の違う実行"}[ambiguity], ", ".join(run_ids))))
        elif kind in ("final_changed", "wrong_file"):
            status, found = kind, value
            expected = _expected_token(found.final(), final) if kind == "final_changed" else None
            problems.append((kind, "記録 {} の最終稿は {}".format(
                found.path, _expected_token(found.final(), final) or "（ハッシュなし）")))
            if kind == "final_changed":
                if _only_line_endings(state, found.final(), final):
                    problems.append(("only_line_endings_differ", "両方の改行を LF にそろえると同じです"))
                elif final.text_sha256 is not None and found.final().get("text_sha256") == final.text_sha256:
                    # 本文は同じで、BOM か末尾の改行も違う（32 の範囲を広げた）
                    problems.append(("only_line_endings_differ", "本文（text_sha256）は記録と同じです"))
        else:
            found = value
            try:
                status, found_problems, replayed, trusted = _verify_record(
                    state, found, final, source, since, args.replay, timeout)
            except _ReplayError as error:
                # 子を動かせなかったのは記録の食い違いではない。状態を決めず、内部の誤りとして3で終える
                _error("yomiyasu_check.py: 内部エラー: --replay で検査を動かせません（{}）。記録の食い違いではありません。"
                       "子プロセスを動かせる環境で verify --replay をもう一度実行してください。".format(error))
                return 3
            problems.extend(found_problems)
            if trusted and final.via == "file":
                recorded = found.record["inputs"]["final"].get("path")
                if recorded is not None and not _same_path(recorded, final.path):
                    problems.append(("final_path_differs", "記録の最終稿のパス: " + recorded))

    # 4. 出力する（1行目に次の行動、2行目に状態の行、3行目に記録のパス。executed だけ4行目に件数）
    # 記録の mode、checks、meaning_risk を出すのは、記録の形と digest を確かめられたときだけ。
    # meaning_risk は、意味が変わる恐れを出す検査（diff、資料との照合）がすべて ran のときだけ出す（0件と読ませない。反証で見つけた例）
    # 人が読む1行目の検査名は完了報告の語にする（materials は「資料との照合」。反証で見つけた例）
    record = found.record if found is not None and found.status == "ok" else None
    shown = trusted
    meaning = None
    if shown:
        statuses = dict((entry["name"], entry["status"]) for entry in record["checks"])
        if all(statuses.get(name) == "ran" for name in _required_for(record) if name in _RISK_CHECKS):
            meaning = record["result"]["meaning_risk_count"]
    codes = [code for code, _ in problems]
    if isinstance(status, tuple):
        reason, names = status
        if reason == "stopped":
            # 記録の検査が時間切れか内部エラーで終わっていた（partial の記録）
            groups = OrderedDict()
            for name, why in names:
                groups.setdefault(_FAILED_NAMES[why], []).append(_label(name))
            status, line = "incomplete", _VERIFY_PARTIAL_LINE.format(
                "、".join("{} は{}".format("、".join(labels), why) for why, labels in groups.items()),
                "、".join("{}（{}）".format(_label(name), _FAILED_NAMES[why]) for name, why in names))
        elif reason == "incomplete":
            status, line = "incomplete", _VERIFY_LINES["incomplete"].format("、".join(_label(name) for name in names))
        else:
            status, line = "incomplete", _REPLAY_TIMEOUT_LINE.format("、".join(_label(name) for name in names))
    elif status == "executed":
        line = _VERIFY_LINES["executed"].format("、".join(_label(name) for name in _required_for(record)))
        if "newer_attempt_differs" in codes:
            line += _NEWER_ATTEMPT_NOTE
    elif status == "no_record" and "empty_final" in codes:
        line = _VERIFY_EMPTY_LINE
    elif status == "ambiguous" and ambiguity == "materials":
        line = _AMBIGUOUS_MATERIALS_LINE
    elif status == "ambiguous" and ambiguity == "place":
        line = _AMBIGUOUS_PLACE_LINE
    elif status == "tool_changed":
        line = _tool_changed_line(problems)
    else:
        line = _VERIFY_LINES[status]
        if status == "final_changed" and "only_line_endings_differ" in codes:
            line += _LINE_ENDINGS_NOTE if _only_line_endings(state, found.final(), final) else _TEXT_SAME_VERIFY_NOTE
        if status == "no_record" and "is_recorded_source" in codes:
            line += _RECORDED_SOURCE_NOTE
    required = _required_for(record) if shown else None
    # 記録の種類と読者（状態の行と JSON に出す。記録の形を確かめられたときだけ）
    doc_type, reader = _record_context(record) if shown else (None, None)
    replay_field = None
    if status == "executed" or status == "not_reproducible" or replayed == "timeout":
        replay_field = replayed
    token = _status_line(
        status, "verify", found.run_id if found is not None else None, found.attempt if found is not None else None,
        final.token(), expected=expected, mode=record["mode"] if shown else None, doc_type=doc_type, reader=reader,
        checks=",".join(required) if shown else None,
        meaning_risk=meaning, replay=replay_field)
    if found is not None:
        record_line = "記録: " + found.path
    elif run_ids:
        record_line = "記録: 複数あります（実行ID {}）".format("、".join(run_ids))
    elif "empty_final" in codes:
        record_line = _VERIFY_EMPTY_RECORD_LINE
    else:
        # 探した状態フォルダを書く（--state-dir で記録したのに付け忘れたときに気づけるように）
        record_line = _NO_RECORD_LINE.format(state)
    final_count = _record_summary_count(record if shown else None, "lint", "candidate_count")
    changed_count = _record_summary_count(record if shown else None, "diff", "hunk_count")
    if args.json or _return:
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
            ("mode", record["mode"] if shown else None),
            ("context", OrderedDict((("doc_type", doc_type), ("reader", reader))) if shown else None),
            ("required_checks", required), ("checks", checks),
            ("meaning_risk_count", meaning), ("replay", replayed),
            ("problems", [OrderedDict((("code", code), ("detail", detail))) for code, detail in problems]),
            ("final_candidate_count", final_count), ("changed_place_count", changed_count)))
        if _return:
            result["_record_line"] = record_line
            return result
        print(json.dumps(result, ensure_ascii=True, indent=1))
    else:
        lines = [line, token, record_line]
        if status == "executed":
            lines.append(_verified_contents_line(final_count, changed_count, required))
        print("\n".join(lines))
    return 0 if status == "executed" else 1


# ---- 任意の登録。start を使わない限り armed/ は作らない ----

_ARMED_STATUSES = ("active", "checked", "unverified", "ended")
_DEFAULT_LIMITS = {"max_stop_blocks": 2, "max_runs": 3, "deadline_min": 30}
_MANAGED_BYTES = 2 * 1024 * 1024


def _armed_place(path):
    return os.path.normcase(os.path.realpath(path))


def _armed_valid(entry, run_id):
    try:
        return (entry["format"] == "yomiyasu-armed" and type(entry["format_version"]) is int
                and entry["format_version"] == 1 and entry["run_id"] == run_id
                and _run_id_problem(run_id) is None and entry["status"] in _ARMED_STATUSES
                and _parse_iso(entry["created_at"]) is not None and _parse_iso(entry["deadline"]) is not None
                and isinstance(entry["targets"]["source"]["path"], str)
                and all(isinstance(entry["targets"]["source"][key], str) for key in ("sha256", "text_sha256", "snapshot"))
                and (entry["targets"]["final"] is None or isinstance(entry["targets"]["final"], str))
                and all(type(entry["limits"][key]) is int for key in _DEFAULT_LIMITS)
                and type(entry["counters"]["stop_blocks"]) is int and isinstance(entry["log"], list))
    except (KeyError, TypeError):
        return False


def armed_entries(state):
    """読める登録だけ返す。壊れたファイルは飛ばす。フォルダは作らない。"""
    folder = os.path.join(state, "armed")
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return []
    entries = []
    for name in names:
        if not name.endswith(".json") or _run_id_problem(name[:-5]):
            continue
        entry = _read_record(os.path.join(folder, name))
        if entry is not None and _armed_valid(entry, name[:-5]):
            entries.append(entry)
    return entries


_ARMED_STALE = 10          # これより古いロックは、落ちたプロセスの残りとみなして取り直す（秒）
_ARMED_WAIT_HOOK = 2.0     # フックが待つ上限（秒。フックの予算の中で）
_ARMED_WAIT_CLI = _ARMED_STALE + 2.0   # check の start、run、end が待つ上限。残ったロックを取り直せるように古さの上限より長くする


class _ArmedLock(object):
    """budget は time.monotonic() による締切（フック。2秒まで待つ）。None は check のコマンドで、12秒まで待つ。"""
    def __init__(self, state, run_id, budget=None, source=False):
        if _run_id_problem(run_id):
            raise ValueError("run_id")
        self.path = os.path.join(state, "armed", (".source-" if source else "") + run_id + ".lock")
        self.deadline = (min(time.monotonic() + _ARMED_WAIT_HOOK, budget) if budget is not None
                         else time.monotonic() + _ARMED_WAIT_CLI)
        self.identity = None

    def __enter__(self):
        while time.monotonic() < self.deadline:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    info = os.fstat(fd)
                    self.identity = (info.st_dev, info.st_ino)
                    os.close(fd)
                except BaseException:
                    # 作った直後に止められても（フックの時間切れなど）、ロックを残さない
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    try:
                        os.unlink(self.path)
                    except OSError:
                        pass
                    raise
                return self
            except FileExistsError:
                try:
                    if time.time() - os.stat(self.path).st_mtime > _ARMED_STALE:
                        os.unlink(self.path)
                        continue
                except FileNotFoundError:
                    continue
                time.sleep(min(0.02, max(0, self.deadline - time.monotonic())))
        raise TimeoutError("armed_lock")

    def __exit__(self, *unused):
        try:
            info = os.stat(self.path)
            if (info.st_dev, info.st_ino) == self.identity:
                os.unlink(self.path)
        except FileNotFoundError:
            pass


def _armed_write(state, entry):
    entry["log"] = entry["log"][-50:]
    _write_atomic(os.path.join(state, "armed", entry["run_id"] + ".json"),
                  (json.dumps(entry, ensure_ascii=True, indent=1) + "\n").encode("ascii"))


def _armed_log(entry, event, result, ms=0):
    entry["log"].append({"at": _iso(_utc_now()), "event": event, "result": result, "ms": ms})
    entry["log"] = entry["log"][-50:]


def armed_update(state, run_id, change, budget=None):
    """ロック内で読み直す。change が False を返したら書かない。"""
    with _ArmedLock(state, run_id, budget):
        entry = _read_record(os.path.join(state, "armed", run_id + ".json"))
        if entry is None or not _armed_valid(entry, run_id):
            raise ValueError("armed_record")
        if change(entry) is not False:
            if budget is not None and time.monotonic() >= budget:
                raise TimeoutError("armed_budget")
            _armed_write(state, entry)
        return entry


def _managed_input(path):
    if path == "-" or not os.path.isfile(path):
        raise ValueError("通常の原文ファイルを渡してください（標準入力は使えません）。")
    with open(path, "rb") as stream:
        data = stream.read(_MANAGED_BYTES + 1)
    if len(data) > _MANAGED_BYTES:
        raise ValueError("原文は2 MiBまでです。")
    return _Input("source", 0, os.path.abspath(path), data)


def start_run(state, source_path, final_path=None, run_id=None, session=None, host=None, by="start",
              limits=None, cwd=None, moment=None, default_place=False):
    """入力の確認をすべて済ませてから、写し・start の記録・登録を書く。default_place は _ensure_state と同じ
    （state を --state-dir と環境変数で決めず、既定の規則で決めたときに真）。"""
    started = time.monotonic()
    cwd = cwd or _getcwd()
    moment = moment or _utc_now()
    limits = dict(_DEFAULT_LIMITS if limits is None else limits)
    for key, low, high in (("max_stop_blocks", 0, 5), ("max_runs", 1, 10), ("deadline_min", 1, 240)):
        if type(limits.get(key)) is not int or not low <= limits[key] <= high:
            raise ValueError("{} は{}〜{}です。".format(key, low, high))
    source = _managed_input(os.path.join(cwd, source_path) if source_path != "-" else "-")
    if final_path == "-":
        raise ValueError("--final に標準入力は使えません。")
    final_path = os.path.abspath(os.path.join(cwd, final_path)) if final_path is not None else None
    run_id = run_id or _new_run_id(state, moment)
    problem = _run_id_problem(run_id) or _run_id_case_problem(state, run_id)
    if problem:
        raise ValueError(problem)
    if os.path.lexists(os.path.join(state, "runs", run_id)) or os.path.lexists(os.path.join(state, "armed", run_id + ".json")):
        raise ValueError("すでにある実行IDです。")
    session = _host_value(session)
    entry = {"format": "yomiyasu-armed", "format_version": 1, "run_id": run_id,
             "created_at": _iso(moment), "deadline": _iso(moment + datetime.timedelta(minutes=limits["deadline_min"])),
             "by": by, "host": host, "session_id": session, "bound_at": _iso(moment) if session and host else None,
             "cwd": cwd, "targets": {"source": {key: source.record()[key] for key in
                                                   ("path", "sha256", "text_sha256", "snapshot")}, "final": final_path},
             "limits": limits, "counters": {"stop_blocks": 0}, "status": "active", "status_reason": None,
             "verified": None, "notified": False, "log": []}
    record = {"format": "yomiyasu-check-start", "format_version": 1, "run_id": run_id,
              "created_at": _iso(moment), "cwd": cwd, "mode": "rewrite",
              "inputs": {"source": source.record(), "materials": []}}
    record["record_digest"] = _record_digest(record)
    _ensure_state(state, default_place)
    _ensure_dir(state, "armed")
    # 同じ原文の start を直列にする。登録用のロックも同じ方式で取得する。UTF-8 で読めないバイトを含むファイル名
    # （'\udcff' として届く）でも止まらないように、ほかのキーと同じく surrogateescape でバイト列にする
    source_lock = _sha256(_armed_place(source.path).encode("utf-8", "surrogateescape"))
    with _ArmedLock(state, source_lock, source=True):
        with _ArmedLock(state, run_id):
            if os.path.lexists(os.path.join(state, "runs", run_id)) or os.path.lexists(os.path.join(state, "armed", run_id + ".json")):
                raise ValueError("すでにある実行IDです。")
            folder = _ensure_dir(state, "runs")
            run_dir = os.path.join(folder, run_id)
            os.mkdir(run_dir, 0o700)
            _put_snapshots(_ensure_dir(state, "inputs"), [source])
            _write_atomic(os.path.join(run_dir, "start.json"),
                          (json.dumps(record, ensure_ascii=True, indent=1) + "\n").encode("ascii"))
            key = _sha256(_place(source.path).encode("utf-8", "surrogateescape"))
            _touch(_ensure_dir(state, "index", "starts", key), _stamp(moment) + "." + run_id)
            for old in armed_entries(state):
                if old["status"] != "ended" and _armed_place(old["targets"]["source"]["path"]) == _armed_place(source.path):
                    def end_old(current):
                        if current["status"] == "ended":
                            return False
                        current["status"], current["status_reason"] = "ended", "superseded"
                        _armed_log(current, "start", "ended:superseded")
                    armed_update(state, old["run_id"], end_old)
            _armed_log(entry, "start", "started", int((time.monotonic() - started) * 1000))
            _armed_write(state, entry)
    return entry


def _armed_for_source(state, source, run_id=None, new_run=False):
    if new_run or source is None or not state or not os.path.isdir(os.path.join(state, "armed")):
        return None
    candidates = []
    for entry in armed_entries(state):
        if entry["status"] == "ended":
            continue
        if run_id is not None:
            matches = entry["run_id"] == run_id
        else:
            target = entry["targets"]["source"]
            matches = ((source.path and _armed_place(source.path) == _armed_place(target["path"]))
                       or source.sha256 == target["sha256"])
        if matches:
            candidates.append(entry)
    return candidates[0] if len(candidates) == 1 else None


def _start_snapshot(state, source_path, run_id=None, cwd=None):
    """同じファイルを直すときの原文。start の digest と写しも照らす。"""
    ids = [run_id] if run_id else []
    if not run_id:
        key = _sha256(_place(source_path).encode("utf-8", "surrogateescape"))
        folder = os.path.join(state, "index", "starts", key)
        try:
            names = sorted(os.listdir(folder), reverse=True)
        except OSError:
            names = []
        ids = [name.split(".", 1)[1] for name in names if "." in name]
    for candidate in ids:
        if _run_id_problem(candidate):
            continue
        record = _read_record(os.path.join(state, "runs", candidate, "start.json"))
        if not record or record.get("format") != "yomiyasu-check-start" or record.get("record_digest") != _record_digest(record):
            continue
        created = _parse_iso(record.get("created_at"))
        if not run_id and (created is None or (_utc_now() - created).total_seconds() > _LINK_SECONDS
                           or not _same_path(record.get("cwd", ""), cwd)):
            continue
        item = record.get("inputs", {}).get("source")
        if not isinstance(item, dict) or not _same_path(item.get("path", ""), source_path):
            continue
        digest = item.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            continue
        try:
            with open(os.path.join(state, "inputs", digest + ".bin"), "rb") as stream:
                data = stream.read(_MANAGED_BYTES + 1)
            if _sha256(data) == digest:
                return candidate, _Input("source", 0, _abspath(source_path), data)
        except OSError:
            continue
    return None, None


def _limit_label(entry):
    return {"deadline": "期限{}分".format(entry["limits"]["deadline_min"]),
            "run_limit": "run {}回まで".format(entry["limits"]["max_runs"])}.get(
                entry["status_reason"], "続けさせる回数の上限")


_RESERVATION_SECONDS = 600   # 中身の無い予約を「検査の途中」とみなす時間（秒。--timeout の既定90秒より十分長い）


def _managed_run_count(run_dir):
    """登録の run の回数。書き終えた記録と、10分以内の中身の無い予約（ほかの run が検査の途中）を数える。

    止められて finally を通らなかった run の空の予約が、いつまでも回数を使い切らないようにする。"""
    count = 0
    now = time.time()
    for number in _attempt_numbers(run_dir):
        try:
            info = os.stat(os.path.join(run_dir, "attempt-{}.json".format(number)))
        except OSError:
            continue
        if info.st_size > 0 or now - info.st_mtime < _RESERVATION_SECONDS:
            count += 1
    return count


def _managed_limit(state, entry, ctx, args, link):
    final = ctx.final
    def check(current):
        reason = current["status_reason"] if current["status"] == "unverified" else None
        if current["status"] == "ended":
            return False
        if reason is None and _utc_now() > _parse_iso(current["deadline"]):
            reason = "deadline"
        if reason is None and _managed_run_count(os.path.join(state, "runs", current["run_id"])) >= current["limits"]["max_runs"]:
            reason = "run_limit"
        if reason is None:
            folder = _ensure_dir(state, "runs", current["run_id"])
            reservation = _reserve_attempt(folder, link["attempt"])
            args._armed_reservation = reservation
            link["reserved"] = reservation
            return False
        current["status"], current["status_reason"] = "unverified", reason
        _armed_log(current, "run", "unverified:" + reason)
    entry = armed_update(state, entry["run_id"], check)
    if entry["status"] != "unverified":
        return False
    message = ("この原稿の管理の上限を超えたので、検査を実行しませんでした（{}）。本文はもう変えず、"
               "完了報告の「実行しなかった検査」に「最終稿の照合（管理の上限）」と書いてください。"
               "利用者から新しい依頼があれば、start で登録し直せます。").format(_limit_label(entry))
    token = _status_line("unverified", "run", entry["run_id"], final=final.token(), reason=entry["status_reason"])
    path = os.path.join(state, "armed", entry["run_id"] + ".json")
    result = {"format": "yomiyasu-check-result", "format_version": 1, "tool_version": __version__, "command": "run",
              "status": "unverified", "status_line": token, "message": message, "run_id": entry["run_id"],
              "attempt": None, "record_path": None, "reason": entry["status_reason"], "armed_path": path,
              "next": "report_unverified", "fix_count": None, "mode": ctx.mode,
              "context": {"doc_type": ctx.doc_type, "reader": ctx.reader}, "fail_on_hit": False,
              "meaning_risk_count": None, "fail_on_meaning_risk_count": None,
              "lint": None, "diff": None, "materials": None,
              "stiffness_check": None, "tone_check": None, "hedges_check": None,
              "immutable_check": None, "politeness_check": None, "fact_gaps": None}
    print(json.dumps(result, ensure_ascii=True, indent=1) if args.json else "\n".join((message, token, "登録: " + path)))
    return True


def text_sha256_of(data):
    return _text_sha256(decode_source(data)[0])


def run_known_texts(state, run_id):
    if _run_id_problem(run_id):
        raise ValueError("run_id")
    texts, paths = set(), set()
    folder = os.path.join(state, "runs", run_id)
    names = ["start.json"] + ["attempt-{}.json".format(n) for n in _attempt_numbers(folder)]
    for name in names:
        record = _read_record(os.path.join(folder, name))
        if record is None or not isinstance(record.get("inputs"), dict):
            continue
        for role in ("source", "final"):
            item = record["inputs"].get(role)
            if isinstance(item, dict):
                digest = item.get("text_sha256")
                if isinstance(digest, str):
                    texts.add(digest)
                if role == "final" and isinstance(item.get("path"), str):
                    paths.add(item["path"])
    return texts, paths


def latest_final_path(state, run_id):
    if _run_id_problem(run_id):
        raise ValueError("run_id")
    record = _latest_record(os.path.join(state, "runs", run_id))
    if record is not None:
        item = record.get("inputs", {}).get("final")
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            return item["path"]
    return None


def _verification(state, final, run_id=None, since=None, source=None):
    args = argparse.Namespace(state_dir=state, final=final.path or "-", source=source,
                              run_id=run_id, since=since, timeout=None, replay=False, json=True)
    return _verify(args, _ArgumentParser(allow_abbrev=False), _final=final, _return=True)


def verify_quick(state, final_path=None, final_bytes=None, run_id=None, since=None):
    """verify の同じ処理を出力なしで使う。lint と diff は import しない。"""
    if final_bytes is None:
        with open(final_path, "rb") as stream:
            final_bytes = stream.read()
    target = _Target(_abspath(final_path) if final_path is not None else None, final_bytes)
    result = _verification(state, target, run_id, since)
    return {"status": result["status"], "attempt": result["attempt"], "final_sha256": target.sha256,
            "text_sha256": target.text_sha256, "problems": result["problems"],
            "record_path": result["record_path"], "message": result["message"]}


def _management(command, args, parser):
    if args.state_dir is not None and not args.state_dir.strip():
        parser.error("--state-dir に空の値は使えません")
    if args.run_id is not None and _run_id_problem(args.run_id):
        parser.error(_run_id_problem(args.run_id))
    if args.source == "-" or getattr(args, "final", None) == "-":
        parser.error("標準入力（-）は使えません")
    state = _state_dir(args.state_dir)
    if command == "start":
        limits = {key: getattr(args, key) for key in _DEFAULT_LIMITS}
        # 読む失敗は入力の誤り。書く失敗は main の内部エラー（3）。
        try:
            _managed_input(args.source)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        try:
            entry = start_run(state, args.source, args.final, args.run_id,
                              args.session if args.session is not None else os.environ.get("YOMIYASU_SESSION"),
                              args.host, "start", limits, _getcwd(), _utc_now(),
                              default_place=not _state_dir_given(args.state_dir))
        except ValueError as error:
            parser.error(str(error))
        run_id = entry["run_id"]
        message = ("原稿を登録しました（上限: 続けさせる{max_stop_blocks}回、run {max_runs}回、{deadline_min}分）。"
                   "この原稿で run と verify を実行すると、記録がこの登録につながります。").format(**limits)
        token = "yomiyasu-check: started via=start run={} attempt=- source=sha256:{}".format(
            run_id, entry["targets"]["source"]["sha256"][:12])
        path = os.path.join(state, "armed", run_id + ".json")
        result = {"format": "yomiyasu-check-result", "format_version": 1, "tool_version": __version__,
                  "command": "start", "status": "started", "status_line": token, "message": message,
                  "run_id": run_id, "armed_path": path, "start_path": os.path.join(state, "runs", run_id, "start.json"),
                  "source": {key: entry["targets"]["source"][key] for key in ("path", "sha256", "text_sha256")},
                  "final_path": args.final and entry["targets"]["final"], "limits": limits, "deadline": entry["deadline"]}
        print(json.dumps(result, ensure_ascii=True, indent=1) if args.json else "\n".join((message, token, "登録: " + path)))
        return 0
    if command == "end":
        count = 0
        for entry in armed_entries(state):
            if entry["status"] == "ended":
                continue
            if not (entry["run_id"] == args.run_id if args.run_id is not None else
                    _armed_place(entry["targets"]["source"]["path"]) == _armed_place(args.source)):
                continue
            def finish(current):
                if current["status"] == "ended":
                    return False
                current["status"], current["status_reason"] = "ended", "end_command"
                _armed_log(current, "end", "ended:end_command")
            armed_update(state, entry["run_id"], finish)
            count += 1
        message = "登録を終えました（{}件）。この原稿のフックによる照合と投稿の確かめは行いません。".format(count) if count else "登録が見つかりません。"
        token = "yomiyasu-check: ended via=end run={} count={}".format(args.run_id or "-", count)
        result = {"format": "yomiyasu-check-result", "format_version": 1, "tool_version": __version__, "command": "end",
                  "status": "ended", "message": message, "status_line": token, "run_id": args.run_id, "count": count}
        print(json.dumps(result, ensure_ascii=True, indent=1) if args.json else message + "\n" + token)
        return 0 if count else 1
    final, problem = _read_target(args.final, None)
    if problem:
        parser.error(problem)
    result = _verification(state, final, args.run_id, source=args.source)
    if not isinstance(result, dict):
        return result
    result["command"], result["export_path"] = "export", None
    result["status_line"] = result["status_line"].replace("via=verify", "via=export", 1)
    record_line = result.pop("_record_line")
    if result["status"] == "executed":
        extension = os.path.splitext(args.final)[1]
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", extension):
            extension = ".txt"
        folder = _ensure_dir(state, "exports", result["run_id"])
        path = os.path.join(folder, "attempt-{}-{}{}".format(result["attempt"], final.sha256[:12], extension))
        if not os.path.isfile(path) or _file_sha256(path) != final.sha256:
            _write_atomic(path, final.data)
        _chmod(path, 0o444)
        if _file_sha256(path) != final.sha256:
            os.unlink(path)
            raise OSError("export_hash")
        result["status"], result["export_path"] = "exported", path
        result["status_line"] = result["status_line"].replace("executed via=", "exported via=", 1)
        result["message"] = ("検査した最終稿と同じ内容の写しを書き出しました。投稿や送信には、この写しのパスを渡してください"
                             "（例 gh pr create --body-file <写し>）。合格の判定ではありません。")
        record_line = "写し: " + path
    print(json.dumps(result, ensure_ascii=True, indent=1) if args.json else
          "\n".join((result["message"], result["status_line"], record_line)))
    return 0 if result["status"] == "exported" else 1


# ---- CLI ----

_DESCRIPTION = ("最終稿に lint、原文と最終稿に diff（新規作成では資料との照合）をまとめて実行し、記録を残します。"
                "結果は『検査を実行した』で、意味の保持や読みやすさの合格ではありません。")
_RECORD_NOTE = ("記録はこのコマンドだけが作ります。同じ権限で原稿と記録の両方を書き換えられる環境では、記録は実行漏れを"
                "見つけるためのもので、改ざんの防止や人の承認の証明にはなりません。")
_EXIT_CODES = """終了コード:
  0  run: 検査を最後まで実行し、--fail-on の条件に当たらなかった（状態 executed か unrecorded。候補の有無によらない）。verify: 記録と照合が合った（executed）。-h と --version も0。start: 登録した（started）。export: 写しを書いた（exported）。end: 登録を終えた（ended）
  1  run: --fail-on の条件に当たった（記録は残す）。verify: 記録がない、または記録と合わない（理由は2行目の状態の行と --json の problems）。run: 登録の上限で実行しなかった（unverified）。export: 照合が合わない。end: 登録がない
  2  使い方か入力の誤り（ファイルを開けない、UTF-8 として読めない、区切りの誤り、使えない値、原文と最終稿が同じファイル、資料と最終稿が同じ中身、空の最終稿、別の原文の実行ID）。何も書かない（状態 not_run）
  3  検査の一部を実行できなかった（lint か diff が内部の誤りか時間切れで終わらなかった、途中で最終稿が変わった。状態 partial）か、check の予期しない内部の誤り、出力先が閉じられて結果を最後まで書けなかった"""
_USAGE = ("yomiyasu_check.py run --final 最終稿 (--source 原文 | --material 資料) [オプション]\n"
          "       yomiyasu_check.py run --stdin [オプション]\n"
          "       yomiyasu_check.py verify --final 最終稿|- [オプション]\n"
          "       yomiyasu_check.py start --source 原文 [オプション]\n"
          "       yomiyasu_check.py export --final 最終稿 [オプション]\n"
          "       yomiyasu_check.py end (--run-id ID | --source 原文) [オプション]\n"
          "       yomiyasu_check.py --version")
_RUN_USAGE = ("yomiyasu_check.py run --final 最終稿 (--source 原文 | --material 資料) [--material 資料 …]\n"
              "           [--stance 立場] [--doc-type 種類] [--reader 読者] [--fail-on meaning-risk|warn|error …] [--timeout 秒]\n"
              "           [--run-id ID | --new-run] [--session ID] [--state-dir DIR] [--no-record] [--fact-gaps] [--json]\n"
              "       yomiyasu_check.py run --stdin [上と同じオプション]")
_VERIFY_USAGE = ("yomiyasu_check.py verify --final 最終稿|- [--run-id ID] [--source 原文] [--since ISO8601]\n"
                 "           [--replay] [--timeout 秒] [--state-dir DIR] [--json]")
_FAIL_ON_HELP = ("指定した条件に当たれば、記録を残したうえで終了コード1で終わります。何度でも、カンマ区切りでも指定できます。"
                 "meaning-risk: 意味が変わる恐れのうち、数値、否定、主語と目的語の入れ替え、文の種類（問いと平叙、文の種類の印）の"
                 "変化、引用の印の変化、確度を強めた書き換え（見込み → 予定、と思われる → 断定など）、原文の状態の語（未定、未確認、"
                 "調査中など）が消えた書き換え、原文にない書き手の約束・保証・再発防止の誓いの足し、許可の言い方（してよい、"
                 "してもよい、構わない）が消えたか増えた書き換え、関連・相関を述べた原文の文に因果の言い方（因果、原因、引き起こす など）を"
                 "足した書き換え、選ぶ範囲が入れ替わった書き換え（または・どちらか → 両方・すべて、またはその逆）、"
                 "--doc-type が pr、article、incident、proposal、manual、formal、paper の"
                 "ときは「場合がある」の言い切りと「必ず」などの足し（ここまでは diff の "
                 "--fail-on=meaning-risk と同じ）と、新規作成で資料にない数値。コード・URL・引用ブロックなど変えない箇所の変化と、資料にない名前は数えません。"
                 "否定対比の主張の逆転と、元にない気持ちの語も数えません。確度を弱めた書き換え、数えない語だけの確度の変化、予定の言い切り（する予定です → します）、"
                 "かぎかっこの中の言葉の変化も数えません。原文にない因果のつながりの足しと、書き手の行為と読む印（いたします、今後・改めて、"
                 "弊社などの主語）のない「〜します」の足しと、事実の穴の候補（--fact-gaps）も数えません。"
                 "warn: lint の warn か error の候補。error: lint の error の候補。"
                 "条件に当たらなくても、意味が同じだという証明にはなりません。")


class _ArgumentParser(argparse.ArgumentParser):
    # argparse は、書く先の流れがない（None の）とき、もう一方の流れに書く。3.10 までは標準エラーがないと
    # 使い方の誤りで AttributeError になる。pythonw や 2>&- のときも、書く先がなければ何も書かずに同じ終了コードで終える。

    def error(self, message):
        stream = sys.stderr
        if stream is None:
            self.exit(2)
        # 使い方の行と argparse の英語の行のあとに、日本語の案内を1行足す（lint、diff と同じ形）
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
    """(全体の parser, run の parser, verify の parser)。省略形は受けない（allow_abbrev=False）。"""
    parser = _ArgumentParser(prog="yomiyasu_check.py", usage=_USAGE, description=_DESCRIPTION + "\n" + _RECORD_NOTE,
                             epilog=_EXIT_CODES, formatter_class=_HelpFormatter, add_help=False, allow_abbrev=False)
    top = parser.add_argument_group("オプション")
    top.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
    top.add_argument("--version", action="store_true", help="版を表示して終わります。")
    commands = parser.add_subparsers(dest="command", title="サブコマンド（省くと run）", metavar="{run,verify,start,export,end}")

    run = commands.add_parser(
        "run", prog="yomiyasu_check.py run", usage=_RUN_USAGE, epilog=_EXIT_CODES, formatter_class=_HelpFormatter,
        add_help=False, allow_abbrev=False, help="検査を実行して記録を残します。最終稿ができたら1回、直したらもう一度実行します。",
        description=(_DESCRIPTION + "\n--source があれば推敲（lint と diff。資料があれば資料との照合も）、"
                     "なくて --material があれば新規作成（lint と資料との照合）です。新規作成で資料の1つが最終稿とよく似ていれば、"
                     "その資料を原文とみなして diff も実行します（同じ実行のあとの回も、その資料を原文とみなします）。\n"
                     + _RECORD_NOTE))
    inputs = run.add_argument_group("入力")
    inputs.add_argument("--final", action="append", metavar="最終稿",
                        help="検査する最終稿のファイル（UTF-8）。- を渡すと標準入力を読みます。")
    inputs.add_argument("--source", "--original", dest="source", action="append", metavar="原文",
                        help="推敲で、書き直す前の原文のファイル。最終稿と別のファイルにしてください。")
    inputs.add_argument("--material", "--materials", dest="materials", action="append", metavar="資料",
                        help="提供された資料のファイル。何度でも指定できます。最終稿の数値、名前、語、確度の語を資料と照らします。")
    inputs.add_argument("--stdin", action="store_true",
                        help="ファイルを作らない対話のため、原文（か資料）と最終稿を標準入力から読みます。"
                             "行全体が <<<yomiyasu:original>>>、<<<yomiyasu:material 出典>>>、<<<yomiyasu:final>>> の行で区切ります。出典は省略可、200字まで（>>> を含めない）。--material のファイルと - の中身も同じ資料の区切りを使えます。"
                             "区切りの行は一字一句このとおりに書きます（<<<yomiyasu: で始まるほかの行があれば、終了コード2で止めます）。")
    options = run.add_argument_group("オプション")
    options.add_argument("--fact-gaps", action="store_true",
                         help="事実の穴の候補の一部を表示します（失敗条件には含めません。essay・promo では出しません）")
    options.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
    options.add_argument("--stance", metavar="立場",
                         help="文書の立場（diff と同じ）。勧め（読み手に勧める）、決まり（手順）、説明（報告、体験）のどれか。")
    options.add_argument("--doc-type", metavar="種類",
                         help="文書の種類。lint と diff に渡し、記録と状態の行に残します。lint は、その種類で普通な書き方を"
                              "候補にする規則を外します（yomiyasu_lint.py -h の一覧）。差分（意味が変わる恐れと規則の見直し候補）の"
                              "見つけ方と、資料との照合の判定は変わりません。"
                              # yomiyasu_diff.py の _counted_doc_type_help() と同じ文（diff を読み込まずにヘルプを出すため、ここに書く）
                              "pr、article、incident、proposal、manual、formal、paper（事実や仕様を述べる種類）では、"
                              "「場合がある」「ことがある」を消した言い切りと、断定に「必ず」などを足した書き換えを --fail-on に数えます"
                              "（意味の検査で種類によって変わるのはこの2つだけです）。"
                              # yomiyasu_diff.py の _detector_level_help() と同じ文（diff を読み込まずにヘルプを出すため、ここに書く。
                              # tests/test_v200_check_infra.py が一致を見張る。反証で見つけた例）
                              "文体の硬化の検査は incident、formal、paper のとき、勢いの検査は pr、article、incident、manual、formal、paper "
                              "のとき、候補を参考として出します。promo と mail 以外の種類を指定すると、勢いの検査の絵文字の候補も参考として"
                              "出し、promo、minutes、mail 以外では見出しの候補も参考として出します。promo では、番号つき項目の行と"
                              "太字だけの行も勢いの検査の見出しに数えます。mail だけ敬語の度合いを検査します。値: "
                              + "、".join("{}（{}）".format(row[0], row[1]) for row in DOC_TYPES) + "。")
    options.add_argument("--reader", metavar="読者",
                         help="想定する読者の知識。lint と diff に渡し、記録と状態の行に残します。判定は変わりません。")
    options.add_argument("--fail-on", action="append", dest="fail_on", metavar="meaning-risk|warn|error",
                         help=_FAIL_ON_HELP)
    options.add_argument("--timeout", metavar="秒",
                         help="子プロセスの検査（lint と diff）に使える秒数の合計。既定は90。超えたら止めて、状態を partial にします。")
    options.add_argument("--run-id", metavar="ID",
                         help="記録をつなぐ実行ID（英数字で始まり、英数字と「.」「_」「-」だけの64字まで。末尾の「.」と、"
                              "Windows で使えない名前（CON、NUL、COM1 など）は使えません）。フックや CI が自分で決めるときに使います。")
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
    additions = {}
    usages = {
        "start": "yomiyasu_check.py start --source 原文 [--final 最終稿] [--run-id ID] [--session ID] [--host claude-code|codex]\n"
                 "                        [--max-stop-blocks N] [--max-runs N] [--deadline-min N] [--state-dir DIR] [--json]",
        "export": "yomiyasu_check.py export --final 最終稿 [--run-id ID] [--source 原文] [--state-dir DIR] [--json]",
        "end": "yomiyasu_check.py end (--run-id ID | --source 原文) [--state-dir DIR] [--json]",
    }
    descriptions = {
        "start": "書き直す前の原文の写しを取り、フックで照合する原稿を登録します。",
        "export": "照合が合った最終稿と同じバイト列の写しを、状態フォルダの exports/（既定は .yomiyasu/exports/）に読み取り専用で書き出します。"
                  "投稿そのものは行わず、合格の判定ではありません。",
        "end": "原稿の登録を終え、フックによる照合と投稿の確かめを終了します。--run-id か --source のどちらか1つを指定してください。",
    }
    for name, help_text in (("start", "原文の写しを取り、原稿を登録します。"),
                            ("export", "照合の合う最終稿の写しを書き出します。"),
                            ("end", "原稿の登録を終えます。")):
        sub = commands.add_parser(name, prog="yomiyasu_check.py " + name, usage=usages[name],
                                  add_help=False, allow_abbrev=False, help=help_text, description=descriptions[name],
                                  epilog=_EXIT_CODES, formatter_class=_HelpFormatter)
        inputs = sub.add_argument_group("入力")
        options = sub.add_argument_group("オプション")
        options.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
        options.add_argument("--state-dir", metavar="DIR", help="登録や記録を置く状態フォルダ（run と同じ決め方）。")
        options.add_argument("--json", action="store_true", help="結果をJSON（結果の形式1）で出します。")
        if name == "end":
            group = inputs.add_mutually_exclusive_group(required=True)
            group.add_argument("--run-id", metavar="ID", help="この実行IDの登録を終えます（--source とどちらか1つ）。")
            group.add_argument("--source", metavar="原文", help="この原文のパスの登録を終えます（--run-id とどちらか1つ）。")
        else:
            options.add_argument("--run-id", metavar="ID", help=("登録に使う新しい実行ID。" if name == "start" else
                                                                  "この実行IDの記録だけを照らします。"))
            inputs.add_argument("--source", required=name == "start", metavar="原文",
                                help=("書き直す前の原文のファイル（UTF-8、2 MiBまで。標準入力は使えません）。" if name == "start" else
                                      "記録の原文がこのファイルかも確かめます。"))
            inputs.add_argument("--final", required=name == "export", metavar="最終稿",
                                help=("最終稿を書くファイルのパス。まだ存在しなくても指定できます。" if name == "start" else
                                      "照らして写しを書き出す最終稿のファイル（標準入力は使えません）。"))
        if name == "start":
            options.add_argument("--session", metavar="ID", help="結び付けるセッションの識別子。省くと環境変数 YOMIYASU_SESSION。")
            options.add_argument("--host", choices=("claude-code", "codex"), metavar="ホスト",
                                 help="結び付けるホスト。値: claude-code、codex。")
            options.add_argument("--max-stop-blocks", type=int, default=2, metavar="回数",
                                 help="Stop で続けさせる回数の上限（既定2、0〜5）。")
            options.add_argument("--max-runs", type=int, default=3, metavar="回数",
                                 help="run の回数の上限（既定3、1〜10）。")
            options.add_argument("--deadline-min", type=int, default=30, metavar="分",
                                 help="登録からの期限（既定30分、1〜240）。")
        additions[name] = sub
    parser._hook_commands = additions
    return parser, run, verify


def _materials_format_version():
    """照合の JSON の版（MATERIALS_FORMAT_VERSION）。定数は yomiyasu_diff.py にだけ置くが、--version では
    diff を読み込まず、ファイルの行から読む（lint と diff の import は run と verify --replay の中だけ。
    diff が壊れていても版の行を出せる。反証で見つけた例）。"""
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
    # サブコマンドを省くと run とみなす（yomiyasu_check.py --source a --final b も動く）
    if not argv or argv[0] not in ("run", "verify", "start", "export", "end", "-h", "--help", "--version"):
        argv.insert(0, "run")
    parser, run, verify = _build_parser()
    # サブコマンドの引数は、そのサブコマンドの parser で読む（知らない引数の誤りを「yomiyasu_check.py run: error:」の形で出す）
    if argv[0] in ("run", "verify", "start", "export", "end"):
        try:
            if argv[0] == "run":
                code = _run(run.parse_args(argv[1:]), run)
            elif argv[0] == "verify":
                code = _verify(verify.parse_args(argv[1:]), verify)
            else:
                sub = parser._hook_commands[argv[0]]
                code = _management(argv[0], sub.parse_args(argv[1:]), sub)
        except _NoWorkingDirectory as error:
            # 作業ディレクトリが消えている（run は何も書く前に確かめる）。入力の誤りとして2（反証で見つけた例）
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
    一時フォルダの写しを消す、書きかけの記録を消す）を通して main まで戻す（反証で見つけた例）。"""

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
