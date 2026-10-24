#!/usr/bin/env python3
"""v2.0.0: diff の全文差分、状態の3分け、レポートの形、引数、決定性、性能（設計 2章、6.3）。

v1.1.2 の diff() は9キーだけを返し、レポートは「（候補なし）」で終わるので、v2.0.0 の振る舞いを見る試験はすべて失敗する。
docstring に「（v1.1.2 でも通る後戻り防止）」と書いた試験は v1.1.2 でも通り、v2.0.0 で壊さないことを見張る。
文はすべてこのファイルで作った合成の文。コーパスの組は tests/corpus を読むだけで、書き換えない。
"""

from pathlib import Path
from unittest import mock
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DIFF = SCRIPTS / "yomiyasu_diff.py"
CORPUS = ROOT / "tests" / "corpus"
FIXTURE = ROOT / "tests" / "fixtures" / "diff_v112_existing_keys.json"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import yomiyasu_diff  # noqa: E402
from portable import run_text  # noqa: E402


NINE_KEYS = ["markers", "new_words", "lost_words", "structure", "spans", "logic", "bold", "endings", "type_changes"]
# 10.6 B1: --fail-on=meaning-risk が数える件数（fail_on_meaning_risk_count）を meaning_risk_count のすぐ後ろに足す
# G7（種類と読者の設計 9.4、10.1）: not_judged の次に context を足す（キーを足すだけで、形式2のまま）
# diff の詰め（追加文書 2.4、勢いの文書 3.3）: 文体の硬化の検査（stiffness）と勢いの検査（tone）を full_diff のあとに足す
# diff の詰めの直し（反証で見つけた例）: 気持ちの語の一覧の出どころ（feeling）を最後に足す
TOP_KEYS = (["format", "format_version", "tool_version", "status", "changed", "candidate_count", "meaning_risk_count",
             "fail_on_meaning_risk_count", "not_judged", "context", "meaning_risks"] + NINE_KEYS
            + ["full_diff", "stiffness", "tone", "feeling", "hedges", "immutable", "politeness", "register"])
FIRST_LINE = "差分の検査を実行しました。"
# v2.1.1: v1.1.2 の合成20組のうち、見出しを変えた組で structure の後ろに足す見出しの変化の文
HEADING_ADDED = {"heading_and_code": ["見出しの段を変えた（元1行目 段2「## 手順」→ 後1行目 段3「### 手順」）"]}
DISCLAIMER = ("全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。"
              "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。")
NO_CANDIDATE_STATUS = "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更"
# 10.2 D9: 改行コード、BOM、末尾の改行だけが違う（hunk がない）ときの状態の行と、全文差分の見出し
ZERO_HUNK_STATUS = "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 0か所。改行コード・BOM・末尾の改行だけが違う）"
ZERO_HUNK_HEADING = "■ 全文差分（変更 0か所。省略していません）"
BOM = "\ufeff"  # 見えない文字なので、ソースには直接書かない
# 性能の試験の子プロセスの上限（秒）。遅い実装でも試験全体を止めない。遅い機械で測り直しても収まるよう、v2.0.2 で30秒から延ばした
CHILD_TIMEOUT = 60

# 2.7 の例A〜D（一字一句）
A_OLD, A_NEW = "保存期間は3日です。\n", "保存期間は30日です。\n"
EXAMPLE_A = """差分の検査を実行しました。
状態: 変更あり（1か所）。見直し候補 1件、うち意味が変わる恐れ 1件
全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。この検査では、意味の保持と読者にとっての分かりやすさは判定していません。

■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）
- 数値が変わった（1行目）: 3日 → 30日
  元: 保存期間は3日です。
  後: 保存期間は30日です。

■ 全文差分（変更 1か所。省略していません）
@ 元1行目 → 後1行目（本文）
  元: 保存期間は3日です。
  後: 保存期間は30日です。
  差: 保存期間は3{+0+}日です。

状態: 変更あり（1か所）。見直し候補 1件、うち意味が変わる恐れ 1件"""
FAIL_LINE_A = "終了コード1: --fail-on=meaning-risk の条件に当たりました（意味が変わる恐れ 1件）。"

B_OLD, B_NEW = "田中が佐藤を承認した。\n", "佐藤が田中を承認した。\n"
EXAMPLE_B = """差分の検査を実行しました。
状態: 変更あり（1か所）。見直し候補 1件、うち意味が変わる恐れ 1件
全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。この検査では、意味の保持と読者にとっての分かりやすさは判定していません。

■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）
- 「が」「を」などが入れ替わった（1行目）: 田中 が→を、佐藤 を→が
  元: 田中が佐藤を承認した。
  後: 佐藤が田中を承認した。

■ 全文差分（変更 1か所。省略していません）
@ 元1行目 → 後1行目（本文）
  元: 田中が佐藤を承認した。
  後: 佐藤が田中を承認した。

状態: 変更あり（1か所）。見直し候補 1件、うち意味が変わる恐れ 1件"""

# 例C の入力（understand/run1/diff.md 2.3 の rich_a.md と rich_b.md。各ファイルの末尾に改行あり）
C_OLD = ("# 設定の手順\n\n- 設定ファイルを開きます。\n- 値を変更してください。\n- 保存期間は3日です。\n\n"
         "原因は設定ミスだとされる。これは重要です。\n")
C_NEW = ("# 設定の手順\n\n設定ファイルを開き、値を変更しましょう。保存期間は30日です。\n\n"
         "原因は設定ミスだ。しかし、**「キャッシュ」**も確認するべきです。\n")
EXAMPLE_C = """差分の検査を実行しました。
状態: 変更あり（2か所）。見直し候補 16件、うち意味が変わる恐れ 3件
全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。この検査では、意味の保持と読者にとっての分かりやすさは判定していません。

■ 意味が変わる恐れ（3件。原文と資料に照らして確かめる）
- 数値が変わった（元5行目 → 後3行目）: 3日 → 30日
  元: 保存期間は3日です。
  後: 保存期間は30日です。
- 文の種類の印が変わった: 2件（下の「■ 文の種類の印が変わった文」を見る）

■ 規則の見直し候補（15件）
■ 言い回しの種類の増減（意味が変わりやすいところ）
- 依頼: 1 → 0（元: てください／後: なし）
- 勧誘: 0 → 1（元: なし／後: ましょう）
- 義務: 0 → 1（元: なし／後: べき）
- 評価: 1 → 0（元: 重要／後: なし）
- つなぎ: 0 → 1（元: なし／後: しかし）
■ 元の文にない語: キャッシュ、確認
■ 消えた語: 重要
■ 箇条書きを地の文にした。各項目の文末（指示・説明・評価）が元と同じか見る
■ 文の数が変わった（6 → 5）
■ つながりを確かめる場所（書き直した文。何と何をつないでいるか言えるか）
- 文頭のつなぎ: しかし、「キャッシュ」も確認するべきです。
■ 文末の種類が変わった文（立場に合う向きか見る）
- 動作（〜します）・箇条書き → 勧め: 設定ファイルを開き、値を変更しましょう。
■ 文の種類の印が変わった文（伝聞・推量・意見・例え・依頼が、元の文と同じか見る）
- 元: 値を変更してください。
  後: 設定ファイルを開き、値を変更しましょう。
  消えた印: 依頼・決まり（てください）
- 元: 原因は設定ミスだとされる。これは重要です。
  後: 原因は設定ミスだ。しかし、「キャッシュ」も確認するべきです。
  消えた印: 伝聞（とされる）
  増えた印: 依頼・決まり（べき）
■ 文末の立場が混ざっている候補（立場を決めてから見る）
- 敬体の文の中に、常体の文がある。そろえるときは「する → します」と形だけで変えず、立場に合う形にする
  ・原因は設定ミスだ。
■ 太字にならない書き方（書き直した文。GitHub などで ** がそのまま表示されることがある。表示可否と案の範囲を確認して直す）
- 5行目: しかし、**「キャッシュ」**も確認す → しかし、「**キャッシュ**」も確認す（かっこの内側だけを太字にする）

■ 全文差分（変更 2か所。省略していません）
@ 元3-5行目 → 後3行目（箇条書き → 本文）
  元: - 設定ファイルを開きます。
  元: - 値を変更してください。
  元: - 保存期間は3日です。
  後: 設定ファイルを開き、値を変更しましょう。保存期間は30日です。
@ 元7行目 → 後5行目（本文）
  元: 原因は設定ミスだとされる。これは重要です。
  後: 原因は設定ミスだ。しかし、**「キャッシュ」**も確認するべきです。

状態: 変更あり（2か所）。見直し候補 16件、うち意味が変わる恐れ 3件"""

EXAMPLE_D = """差分の検査を実行しました。
状態: 変更なし
全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。この検査では、意味の保持と読者にとっての分かりやすさは判定していません。

■ 全文差分: 変わった箇所はありません。

状態: 変更なし"""

# 指示書2.2の組3の補助の行（2.7 の例の下の文）
PAIR3_OLD, PAIR3_NEW = "データを保存します。\n", "データを保存しません。\n"
PAIR3_DIFF_LINE = "  差: データを保存しま[-す-]{+せん+}。"

# 2.8 の meaning_risks の要素の例（例A の入力）
EXAMPLE_A_RISK_FOR_PARTS = {"kind": "number", "subkind": "replaced", "old_line": 1, "new_line": 1,
                            "old": "保存期間は3日です。", "new": "保存期間は30日です。",
                            "detail": {"removed": ["3日"], "added": ["30日"]}, "basis": None}

# 2.8 の full_diff の例の hunk（例A の入力）
EXAMPLE_A_HUNK = {"index": 1, "tag": "replace",
                  "old_start": 1, "old_end": 1, "new_start": 1, "new_end": 1,
                  "old_blocks": ["paragraph"], "new_blocks": ["paragraph"],
                  "whitespace_only": False, "notes": [], "moved_to": None, "moved_from": None,
                  "old_lines": ["保存期間は3日です。"], "new_lines": ["保存期間は30日です。"],
                  "segments": [["=", "保存期間は3"], ["+", "0"], ["=", "日です。"]],
                  "segments_omitted": None}

# 完全さの試験に使う合成の文書と、6.3 の表に挙がった書き換え
BASE = (
    "# 設定の手順\n"
    "\n"
    "## 準備\n"
    "\n"
    "設定ファイルを開きます。**必ず**保存してから閉じます。\n"
    "期限は  3日です。\n"
    "行末に空白がある行です。  \n"
    "\n"
    "- 手順書を読む。\n"
    "- 値を変える。\n"
    "\n"
    "> 引用の中の期限は3日です。\n"
    "\n"
    "| 項目 | 期間 |\n"
    "|---|---|\n"
    "| 保存 | 3日 |\n"
    "\n"
    "`retention=3` を指定する。\n"
    "\n"
    "```sh\n"
    "retention=3\n"
    "```\n"
    "\n"
    "最後の段落です。ここで終わります。\n"
)
REWRITTEN_ALL = (
    "# 手順のまとめ\n"
    "\n"
    "設定は最初に開いて、値を確かめてから保存する。\n"
    "期限は来週の金曜とする。\n"
    "1. 資料を読む。\n"
    "2. 値を直す。\n"
    "> 期限は守る。\n"
    "終わりです。"
)


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise AssertionError("合成の書き換えの元が1か所ではない: " + old)
    return text.replace(old, new)


def synthetic_rewrites():
    """(名前, 元, 後)。6.3 の「完全さ」の行に挙がった書き換え。"""
    moved = replace_once(BASE, "最後の段落です。ここで終わります。\n", "")
    moved = replace_once(moved, "## 準備\n\n", "## 準備\n\n最後の段落です。ここで終わります。\n\n")
    return [
        ("見出しの段", BASE, replace_once(BASE, "## 準備\n", "### 準備\n")),
        ("太字を外す", BASE, replace_once(BASE, "**必ず**", "必ず")),
        ("空行を消す", BASE, replace_once(BASE, "  \n\n- 手順書", "  \n- 手順書")),
        ("空白2つを1つに", BASE, replace_once(BASE, "期限は  3日", "期限は 3日")),
        ("行末の空白2つを消す", BASE, replace_once(BASE, "行です。  \n", "行です。\n")),
        ("コード", BASE, replace_once(BASE, "retention=3\n```", "retention=30\n```")),
        ("インラインのコード", BASE, replace_once(BASE, "`retention=3`", "`retention=30`")),
        ("引用", BASE, replace_once(BASE, "> 引用の中の期限は3日です。", "> 引用の中の期限は30日です。")),
        ("表のセル", BASE, replace_once(BASE, "| 保存 | 3日 |", "| 保存 | 30日 |")),
        ("箇条書きを地の文に", BASE, replace_once(BASE, "- 手順書を読む。\n- 値を変える。\n", "手順書を読み、値を変える。\n")),
        ("段落を分ける", BASE, replace_once(BASE, "開きます。**必ず**", "開きます。\n\n**必ず**")),
        ("行の移動", BASE, moved),
        ("末尾の改行を消す", BASE, BASE.rstrip("\n")),
        ("CRLF → LF", BASE.replace("\n", "\r\n"), BASE),
        ("BOM を外す", BOM + BASE, BASE),
        ("全面の書き換え", BASE, REWRITTEN_ALL),
    ]


def corpus_pairs():
    """yomiyasu_rewritten の48組（元は raw_ai か blacklist_ai。tools/existing_keys_check.py と同じ組み方）。"""
    pairs = []
    for name in sorted(os.listdir(CORPUS / "yomiyasu_rewritten")):
        if not name.endswith(".md"):
            continue
        if name.endswith("_bl.md"):
            source = CORPUS / "blacklist_ai" / (name[:-6] + ".md")
        else:
            source = CORPUS / "raw_ai" / name
        pairs.append((source, CORPUS / "yomiyasu_rewritten" / name))
    return pairs


def read_exact(path):
    """改行を変えずに読む（read_text は CRLF を LF にするので使わない）。"""
    return path.read_bytes().decode("utf-8")


def split_lines(text):
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def run_diff(args, stdin=None, env=None):
    """標準入力を渡さないときは空にする（親の標準入力を受け継ぐと、誤って読む実装が端末でだけ timeout まで止まる）。
    渡す文字列は、改行を変えずに UTF-8 のバイト列で渡す（portable.run_text）。"""
    feed = {"stdin": subprocess.DEVNULL} if stdin is None else {"input": stdin}
    return run_text(
        [sys.executable, "-B", str(DIFF)] + [str(a) for a in args],
        encoding="utf-8", capture_output=True, timeout=30, env=env, **feed
    )


def full_diff_section(report):
    lines = report.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("■ 全文差分"):
            return lines[index:]
    raise AssertionError("レポートに「■ 全文差分」の節がない:\n" + report)


def sentences_of(length, seed, sentences):
    """seed ごとに違う文を並べ、つなぐと length 字以上の1行になる文のリストを返す。"""
    parts, index = [], 0
    while len("".join(parts)) < length:
        parts.append(sentences[index % len(sentences)].format(n=seed, k=index))
        index += 1
    return parts


def changed_middle(old, new):
    """前と後ろの同じ部分を外したあとに残る、両側の字数の合計。"""
    head = len(os.path.commonprefix([old, new]))
    tail = len(os.path.commonprefix([old[head:][::-1], new[head:][::-1]]))
    return len(old) + len(new) - 2 * (head + tail)


# 性能の試験の上限を壁時計の秒数だけにすると、実装が同じでも遅い機械で落ちる。そこで v2.0.2 から、次の2つを見る。
# 1つ目は時間の伸びで、同じ形で4分の1の大きさの文書も同じ子プロセスで測り、本来の大きさの時間がその GROWTH_LIMIT 倍未満で
# あることを見る。文書の大きさに比例する処理なら約4倍、大きさの2乗で伸びる処理なら約16倍になる。同じプロセスの中の比なので、
# 機械の速さによらない。2つ目は時間そのもので、v2.0.1 と同じ秒数の上限を、基準の処理（CHILD_TIMER の pace）が PACE_SECONDS 秒で
# 終わる機械での上限とする。同じ子プロセスで測った pace がそれより遅い機械では、遅い比の分だけ上限を延ばす。速い機械でも上限は縮めない。
GROWTH_LIMIT = 8
# pace の CPU 時間。Apple M5 Pro の Python 3.14.5 で、ほかの処理が少ないときに子プロセスで測った最小（0.059秒。v2.0.2）。
# ほかの処理が多いときは 0.08〜0.10秒になる。pace の中身を変えたら測り直す
PACE_SECONDS = 0.060

# 性能の試験で、測る処理だけを子プロセスで動かす。時間は CPU 時間で測る（ほかのプロセスに CPU を譲って待った時間を入れない）。
# pace と、測る文書（4分の1の大きさの文書があればそれも）を交互に測り、それぞれの最も速い値を返す。上限を満たせばそこでやめ、
# 満たさなければ最大5回まで測り直す。
CHILD_TIMER = r'''
import difflib
import gc
import json
import re
import sys
import time
from bisect import bisect_left
from collections import Counter

sys.path.insert(0, sys.argv[1])
import yomiyasu_diff

with open(sys.argv[2], encoding="utf-8") as handle:
    task = json.load(handle)
# Windows の CPU 時間は刻みが粗い（約16ミリ秒）ので、壁時計で測る
clock = time.perf_counter if sys.platform == "win32" else time.process_time


def full_rewrite(pairs):
    orig, rewrite = pairs[0]
    full = yomiyasu_diff.full_diff(orig, rewrite)
    # 9キーの分析（type_changes）は測らない（2.11の1）。空のリストを渡し、中で作らせない
    yomiyasu_diff.meaning_risks(orig, rewrite, full=full, type_changes=[])
    return None


def small_fix(pairs):
    orig, rewrite = pairs[0]
    return len(yomiyasu_diff.full_diff(orig, rewrite)["hunks"])


def corpus(pairs):
    for orig, rewrite in pairs:
        yomiyasu_diff.diff(orig, rewrite)
    return len(pairs)


def ground(pairs):
    orig, rewrite = pairs[0]
    yomiyasu_diff.ground(rewrite, [orig], original=orig)
    return None


def extract(pairs):
    orig, rewrite = pairs[0]
    return len(yomiyasu_diff.extract_numbers(orig))


# pace は yomiyasu を使わない、量の決まった計算。diff の処理に近い種類（difflib の照合、正規表現で文と数を拾って数える、
# 関数の呼び出しの多い走査、dict と二分探索）を同じくらいずつ動かし、機械と Python の速さを測る
PACE_OLD = "".join("第%d項の値は%d件です。" % (i, i * 7 % 1000) for i in range(100))
PACE_NEW = "".join("第%d項の値は%d件でした。" % (i, i * 11 % 1000) for i in range(100))
PACE_TEXT = "".join("設定ファイル%dの値は%d件です。担当者は%d番目の結果を残し、会議で共有します。" % (i, i * 3, i % 97)
                    for i in range(1500))
PACE_SENTENCE = re.compile(r"[^。]*。")
PACE_NUMBER = re.compile(r"[0-9]+(?P<unit>件|番目)?")
PACE_WORDS = ["語%d" % (i * 7919 % 5000) for i in range(30000)]


class PaceRow(tuple):
    __slots__ = ()
    start = property(lambda self: self[1])


PACE_ROWS = [PaceRow((i, i * 5, i * 5 + 5)) for i in range(1000)]


def pace():
    total = len(difflib.SequenceMatcher(None, PACE_OLD, PACE_NEW, autojunk=False).get_opcodes())
    for _ in range(6):
        counts = Counter()
        for sentence in PACE_SENTENCE.finditer(PACE_TEXT):
            for number in PACE_NUMBER.finditer(sentence.group()):
                counts[(number.group(), number.group("unit"))] += 1
        total += len(counts)
    for k in range(1000):
        total += next(row for row in PACE_ROWS if row.start <= k * 5 + 2 < row[2])[0]
    for _ in range(6):
        seen = {}
        for i, word in enumerate(PACE_WORDS):
            seen.setdefault(word, []).append(i)
        starts = sorted(len(places) * 100000 + k for k, places in enumerate(seen.values()))
        total += sum(bisect_left(starts, x) for x in range(0, 30000, 3))
    return total


def sample(work, repeat):
    # work を repeat 回動かした1回あたりの時間と、最後の戻り値。前に作ったものを先に片付けておく
    gc.collect()
    started = clock()
    for _ in range(repeat):
        value = work()
    return (clock() - started) / repeat, value


run = {"full_rewrite": full_rewrite, "small_fix": small_fix, "corpus": corpus, "ground": ground,
       "extract": extract}[task["run"]]
inputs, limit, growth = task["inputs"], task["limit"], task["growth"]
deadline = time.perf_counter() + task["deadline"]
values, repeats = [None] * len(inputs), [1] * len(inputs)
if len(inputs) == 2:
    # 小さい文書で一度動かし、初めの1回だけの準備（一覧の読み込みなど）を測る前に済ませる。短い処理は、1つの標本が
    # 0.05秒を超えるまで繰り返す（時計の刻みと割り込みの揺れを薄める）。本来の大きさは小さい文書の4倍の時間と見積もる
    once = sample(lambda: run(inputs[0]), 1)[0]
    if once < 0.05:
        once = sample(lambda: run(inputs[0]), 1)[0]
    repeats = [int(0.05 / max(once, 1e-6)) + 1, int(0.05 / max(4 * once, 1e-6)) + 1]
best, best_pace = [None] * len(inputs), None
for rounds in range(1, 6):
    round_started = time.perf_counter()
    elapsed = sample(pace, 1)[0]
    best_pace = elapsed if best_pace is None else min(best_pace, elapsed)
    for k, pairs in enumerate(inputs):
        elapsed, values[k] = sample(lambda: run(pairs), repeats[k])
        best[k] = elapsed if best[k] is None else min(best[k], elapsed)
    budget = limit * max(1.0, best_pace / task["pace_seconds"])
    if best[-1] < budget and (growth is None or best[-1] < growth * best[0]):
        break
    if 2 * time.perf_counter() - round_started > deadline:
        break
print(json.dumps({"best": best[-1], "quarter": best[0] if len(inputs) == 2 else None, "pace": best_pace,
                  "rounds": rounds, "value": values[-1], "quarter_value": values[0] if len(inputs) == 2 else None}))
'''


SECTION_SENTENCES = ("第{n}節の{k}項では、設定の値を記録の表と照らします。", "担当者は{k}番目の結果を残し、会議で共有します。",
                     "古い値は消さずに、変えた理由を横に書き足します。", "止まった手順は、最初の段から{k}回目として進め直します。")
REWRITE_SENTENCES = ("{n}番目の節の{k}項で、記録した値を会議の前に読み直しました。", "変えた値の理由を短く添え、古い設定は外しています。",
                     "止まった手順は、はじめの段からもう一度進めました。", "確かめた人の名前と日付も{k}行目に足しています。")


# 10.2 D16: 約65字の短い段落を900個ほど並べた6万字の文書（空行が多く、行の対応が遅くなりやすい形）
SHORT_SENTENCES = ("第{n}段の{k}項では、設定の値を記録の表と照らし、違いを残します。", "担当者は{k}番目の結果を残し、翌週の会議で全員に共有します。",
                   "古い値は消さずに、変えた理由を横の欄に短く書き足しておきます。", "止まった手順は、最初の段から{k}回目として順に進め直します。")
SHORT_REWRITE_SENTENCES = ("{n}段目の{k}項で記録した値を、次の会議の前にもう一度読み直しました。",
                           "変えた値の理由を短く添えて、古い設定は表からすべて外しています。",
                           "止まった手順は、いちばんはじめの段からもう一度だけ進め直しました。",
                           "確かめた人の名前と日付を、{k}行目の右の欄に足しておきました。")


def long_document(sentences, paragraphs=None, min_chars=60000, sentences_per_paragraph=10):
    """空行で区切った段落の並び（各段落は違う文を10文）。paragraphs を省くと min_chars 字以上になるまで足す。"""
    blocks, size = [], 0
    while (size < min_chars) if paragraphs is None else (len(blocks) < paragraphs):
        n = len(blocks)
        blocks.append("".join(sentences[(n + k) % len(sentences)].format(n=n, k=k) for k in range(sentences_per_paragraph)))
        size += len(blocks[-1]) + 2
    return "\n\n".join(blocks) + "\n", len(blocks)


class DiffCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-v200-diff-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, name, data):
        """文字列は UTF-8 にし、改行を変えずにそのまま書く。"""
        path = self.root / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def v2(self, result):
        for key in ("status", "candidate_count", "meaning_risks", "full_diff"):
            self.assertTrue(key in result, "v2.0.0 の diff() は %s を返す（設計 2.8）。今のキー: %s"
                            % (key, list(result)))
        return result

    def need_v2_diff(self):
        """subTest で同じ失敗を何十回も出さないよう、v2.0.0 の diff() かを先に1回だけ確かめる。"""
        self.v2(yomiyasu_diff.diff("会議は3時に始まります。\n", "会議は4時に始まります。\n"))

    def diff2(self, orig, rewrite, stance=None):
        return self.v2(yomiyasu_diff.diff(orig, rewrite, stance))

    def report(self, result):
        text = yomiyasu_diff.report(result)
        self.assertNotEqual(text, "（候補なし）", "v2.0.0 の report() は「（候補なし）」を返さない（2.10）")
        return text.rstrip("\n")

    def need_function(self, name):
        self.assertTrue(callable(getattr(yomiyasu_diff, name, None)),
                        "v2.0.0 の yomiyasu_diff は %s() を公開する（設計 2.10）" % name)
        return getattr(yomiyasu_diff, name)

    def time_in_child(self, run, pairs, limit, quarter=None):
        """CHILD_TIMER の run を子プロセスで動かし、{"best": 秒, "quarter": 秒, "pace": 秒, "rounds": 回数, "value": 戻り値,
        "quarter_value": 戻り値} を返す。quarter（pairs と同じ形で4分の1の大きさの組）を渡すと、その時間も測る。
        時間は子の中で測る。CHILD_TIMEOUT 秒で終わらなければ失敗にする（同じプロセスで動かすと timeout が効かない）。"""
        inputs = ([quarter] if quarter is not None else []) + [pairs]
        task = self.write("timing-%s.json" % run, json.dumps(
            {"run": run, "inputs": inputs, "limit": limit, "growth": GROWTH_LIMIT if quarter is not None else None,
             "pace_seconds": PACE_SECONDS, "deadline": CHILD_TIMEOUT / 2}, ensure_ascii=False))
        timed_out = False
        try:
            process = subprocess.run([sys.executable, "-B", "-c", CHILD_TIMER, str(SCRIPTS), str(task)],
                                     stdin=subprocess.DEVNULL, encoding="utf-8", capture_output=True, timeout=CHILD_TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
        if timed_out:
            self.fail("%s が %d 秒で終わらない（上限 %s 秒）" % (run, CHILD_TIMEOUT, limit))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def assert_fast(self, run, pairs, limit, quarter=None, message=""):
        """run の時間が上限（limit 秒を、pace の遅さの比で延ばした値）未満で、quarter を渡したときは、4分の1の大きさからの
        時間の伸びが GROWTH_LIMIT 倍未満であることを確かめ、time_in_child の結果を返す。"""
        timing = self.time_in_child(run, pairs, limit, quarter)
        scale = max(1.0, timing["pace"] / PACE_SECONDS)
        detail = ("%s: %.3f秒。上限 %.3f秒（%s秒 × この機械の遅さ %.2f。基準の処理 %.3f秒）。%d回測った最も速い値"
                  % (run, timing["best"], limit * scale, limit, scale, timing["pace"], timing["rounds"]))
        if quarter is not None:
            detail += "。4分の1の大きさでは %.4f秒（%.1f倍）" % (timing["quarter"], timing["best"] / timing["quarter"])
        self.assertLess(timing["best"], limit * scale, (message + "\n" if message else "") + detail)
        if quarter is not None:
            self.assertLess(timing["best"], GROWTH_LIMIT * timing["quarter"],
                            "文書を4倍にすると時間が %d倍以上に伸びる（大きさの2乗で伸びる処理の疑い）\n%s" % (GROWTH_LIMIT, detail))
        return timing

    def assert_status_lines(self, report, status_line):
        lines = report.split("\n")
        self.assertEqual(lines[0], FIRST_LINE, report)
        self.assertEqual(lines[2], DISCLAIMER, report)
        self.assertTrue(lines[1].startswith(status_line), report)
        self.assertEqual(lines[-1], lines[1], "状態の行を最後にもう一度出す（2.7の8）\n" + report)

    def assert_complete(self, orig, rewrite, full):
        """2.3 の完全さの約束: equal と hunk をつなぐと前後の文に1字も違わずに戻る。segments も同じ。"""
        hunks = sorted(full["hunks"], key=lambda h: h["index"])
        self.assertEqual([h["index"] for h in hunks], list(range(1, len(hunks) + 1)))
        self.assertEqual(full["final_newline"], {"old": orig.endswith("\n"), "new": rewrite.endswith("\n")})
        old_lines, new_lines = split_lines(orig), split_lines(rewrite)
        rebuilt_new, rebuilt_old = [], []
        old_pos = new_pos = 0
        for hunk in hunks:
            self.assertIn(hunk["tag"], ("replace", "delete", "insert"))
            self.assertEqual(hunk["old_end"] - hunk["old_start"] + 1, len(hunk["old_lines"]), hunk)
            self.assertEqual(hunk["new_end"] - hunk["new_start"] + 1, len(hunk["new_lines"]), hunk)
            old_at, new_at = hunk["old_start"] - 1, hunk["new_start"] - 1
            self.assertEqual(old_lines[old_pos:old_at], new_lines[new_pos:new_at], "hunk の間は変わらない行")
            self.assertEqual(old_lines[old_at:old_at + len(hunk["old_lines"])], hunk["old_lines"])
            self.assertEqual(new_lines[new_at:new_at + len(hunk["new_lines"])], hunk["new_lines"])
            rebuilt_new += old_lines[old_pos:old_at] + hunk["new_lines"]
            rebuilt_old += new_lines[new_pos:new_at] + hunk["old_lines"]
            old_pos, new_pos = old_at + len(hunk["old_lines"]), new_at + len(hunk["new_lines"])
            if hunk["segments"] is not None:
                self.assertEqual("".join(text for tag, text in hunk["segments"] if tag in ("=", "-")),
                                 "\n".join(hunk["old_lines"]))
                self.assertEqual("".join(text for tag, text in hunk["segments"] if tag in ("=", "+")),
                                 "\n".join(hunk["new_lines"]))
                self.assertTrue(set(tag for tag, _ in hunk["segments"]) <= {"=", "-", "+"})
            elif hunk["tag"] == "replace":
                self.assertIn(hunk["segments_omitted"], ("too_large", "budget"))
        self.assertEqual(old_lines[old_pos:], new_lines[new_pos:], "最後の hunk のあとは変わらない行")
        rebuilt_new += old_lines[old_pos:]
        rebuilt_old += new_lines[new_pos:]
        self.assertEqual("\n".join(rebuilt_new) + ("\n" if full["final_newline"]["new"] else ""), rewrite)
        self.assertEqual("\n".join(rebuilt_old) + ("\n" if full["final_newline"]["old"] else ""), orig)


class TestCompleteness(DiffCase):
    """6.3 完全さ: 元に hunk を当てると後になる。segments の「= と -」が元、「= と +」が後。"""

    def test_corpus_48_pairs(self):
        pairs = corpus_pairs()
        self.assertEqual(len(pairs), 48)
        self.need_v2_diff()
        for source, rewritten in pairs:
            with self.subTest(pair=rewritten.name):
                orig, rewrite = read_exact(source), read_exact(rewritten)
                self.assert_complete(orig, rewrite, self.diff2(orig, rewrite)["full_diff"])

    def test_synthetic_rewrites(self):
        rewrites = synthetic_rewrites()
        self.assertEqual(len(rewrites), 16)
        self.need_v2_diff()
        for name, orig, rewrite in rewrites:
            with self.subTest(rewrite=name):
                result = self.diff2(orig, rewrite)
                self.assertIs(result["changed"], True)
                if name != "末尾の改行を消す":
                    # 末尾の改行だけの違いは行が同じなので、hunk を作るかは設計で決まっていない（final_newline には出る）
                    self.assertTrue(result["full_diff"]["hunks"], "変わった箇所が全文差分に出る")
                self.assert_complete(orig, rewrite, result["full_diff"])


class TestStatus(DiffCase):
    """6.3 状態: no_change、changed_without_candidates の分け方（2.6）。"""

    def test_same_text_is_no_change_and_report_is_example_d(self):
        text = "会議は3時に始まります。\n"
        result = self.diff2(text, text)
        self.assertEqual(result["status"], "no_change")
        self.assertIs(result["changed"], False)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["full_diff"]["hunks"], [])
        self.assertEqual(self.report(result), EXAMPLE_D)

    def test_same_file_on_cli_prints_example_d(self):
        text = "会議は3時に始まります。\n"
        process = run_diff([self.write("a.md", text), self.write("b.md", text)])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(process.stdout.rstrip("\n"), EXAMPLE_D)

    def test_whitespace_only_change(self):
        result = self.diff2("設定を確認します。\n", "設定を 確認します。\n")
        self.assertEqual(result["status"], "changed_without_candidates")
        self.assertEqual(result["candidate_count"], 0)
        [hunk] = result["full_diff"]["hunks"]
        self.assertIs(hunk["whitespace_only"], True)
        self.assertEqual(hunk["notes"], [{"kind": "whitespace_only"}], "10.2 D10 の注記の形")
        report = self.report(result)
        self.assert_status_lines(report, NO_CANDIDATE_STATUS)
        section = full_diff_section(report)
        self.assertIn("@ 元1行目 → 後1行目（本文、空白だけ）", section)
        self.assertIn("  差: 設定を{+〔空白〕+}確認します。", section)
        self.assertFalse([line for line in section if line.startswith(("  元: ", "  後: "))],
                         "空白だけが違う行の組は差だけを出す（2.4）")

    def test_sentence_order_swap_is_changed_without_candidates(self):
        result = self.diff2("まず設定する。次に保存する。\n", "次に保存する。まず設定する。\n")
        self.assertEqual(result["status"], "changed_without_candidates")
        self.assertIs(result["changed"], True)
        self.assertEqual(result["candidate_count"], 0)
        report = self.report(result)
        self.assert_status_lines(report, NO_CANDIDATE_STATUS)
        self.assertNotIn("（候補なし）", report)

    def test_cli_line_endings_or_bom_only(self):
        cases = (
            ("改行コード", "会議は3時に始まります。\r\n".encode("utf-8"), "会議は3時に始まります。\n".encode("utf-8"),
             {"kind": "eol", "old": "crlf", "new": "lf"}, "- 改行コード: CRLF → LF（行ごとの差には出していません）"),
            ("BOM", (BOM + "会議は3時に始まります。\n").encode("utf-8"), "会議は3時に始まります。\n".encode("utf-8"),
             {"kind": "bom", "old": True, "new": False}, "- 先頭のBOM: あり → なし"),
        )
        for name, before, after, note, line in cases:
            with self.subTest(only=name):
                paths = [self.write(name + "-a.md", before), self.write(name + "-b.md", after)]
                process = run_diff(["--json"] + paths)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = self.v2(json.loads(process.stdout))
                self.assertEqual(result["status"], "changed_without_candidates")
                self.assertEqual(result["full_diff"]["encoding_notes"], [note])
                self.assertEqual(result["full_diff"]["hunks"], [], "行ごとの差には出さない（2.2）")
                process = run_diff(paths)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                report = process.stdout.rstrip("\n")
                self.assert_status_lines(report, NO_CANDIDATE_STATUS)
                self.assertIn(line, report.split("\n"))
                # 10.2 D9: hunk のない変化の状態の行と、全文差分の見出しのすぐ下の注記の行
                lines = report.split("\n")
                self.assertEqual(lines[1], ZERO_HUNK_STATUS, report)
                self.assertEqual(full_diff_section(report)[:2], [ZERO_HUNK_HEADING, line], report)
                process = run_diff(["--fail-on=meaning-risk"] + paths)
                self.assertEqual(process.returncode, 0, "改行コードや BOM だけの違いは意味が変わる恐れにしない")

    def test_final_newline_only(self):
        """10.2 D9、D9b: 末尾の改行だけが違うときは hunk を作らず、状態の行と文書全体の注記の行で知らせる。"""
        result = self.diff2("会議は3時に始まります。\n", "会議は3時に始まります。")
        self.assertEqual(result["status"], "changed_without_candidates")
        self.assertIs(result["changed"], True)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(result["full_diff"]["hunks"], [])
        self.assertEqual(result["full_diff"]["final_newline"], {"old": True, "new": False})
        report = self.report(result)
        self.assertEqual(report.split("\n")[1], ZERO_HUNK_STATUS, report)
        self.assert_status_lines(report, ZERO_HUNK_STATUS)
        self.assertEqual(full_diff_section(report), [ZERO_HUNK_HEADING, "- 末尾の改行: あり → なし", "", ZERO_HUNK_STATUS])

    def test_zero_hunk_change_hides_rewritten_only_candidates(self):
        """10.2 D9: 行の差がない変化（末尾の改行だけ）では、書き直した文だけを見る候補（太字、つながり）を数えず、出さない。
        変えていない文章に直しを促さないため（2.6 の no_change と同じ考え方）。9キーの中身は変えない。"""
        text = TestRewrittenOnlyCandidates.TEXT
        result = self.diff2(text, text.rstrip("\n"))
        self.assertEqual(result["status"], "changed_without_candidates")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["bold"], TestRewrittenOnlyCandidates.V112_BOLD)
        report = self.report(result)
        self.assertNotIn("太字にならない書き方", report)
        self.assertNotIn("つながりを確かめる場所", report)
        self.assertNotIn("■ 規則の見直し候補", report)

    def test_status_lines_count_hunks_and_candidates(self):
        """2.6 の状態の行の数え方: 変更の数は hunk の数、見直し候補は candidate_count、意味が変わる恐れは meaning_risk_count。"""
        result = self.diff2("設定を確認します。\n\n手順を読みます。\n", "設定を 確認します。\n\n手順を 読みます。\n")
        self.assertEqual(len(result["full_diff"]["hunks"]), 2)
        report = self.report(result)
        self.assertEqual(report.split("\n")[1], NO_CANDIDATE_STATUS + " 2か所）", report)
        self.assertEqual(full_diff_section(report)[0], "■ 全文差分（変更 2か所。省略していません）")


class TestRewrittenOnlyCandidates(DiffCase):
    """6.3 書き直した文だけの候補: 変えていない文章では logic、bold、endings.flags をレポートに出さない（2.6）。"""

    TEXT = "これは**「重要」**です。\n"
    # v1.1.2 の diff(TEXT, TEXT) が返した値（v2.0.0 も9キーの中身は変えない）
    V112_BOLD = [{"line": 1, "found": "これは**「重要」**です。", "suggest": "これは「**重要**」です。",
                  "how": "かっこの内側だけを太字にする"}]
    V112_LOGIC = [{"kind": "文頭の指示語", "sentence": "これは「重要」です。"}]

    def test_same_text_with_unrendered_bold(self):
        result = self.diff2(self.TEXT, self.TEXT)
        self.assertEqual(result["status"], "no_change")
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["bold"], self.V112_BOLD)
        self.assertEqual(result["logic"], self.V112_LOGIC)
        report = self.report(result)
        self.assertNotIn("太字にならない書き方", report)
        self.assertNotIn("つながりを確かめる場所", report)
        self.assertEqual(report, EXAMPLE_D)


class TestPresentation(DiffCase):
    """6.3 見せ方: 2.7 の例A、B、C と完全に同じ。例B に差がない。組3の差の行。"""

    def test_example_a_report(self):
        self.assertEqual(self.report(self.diff2(A_OLD, A_NEW)), EXAMPLE_A)

    def test_example_a_cli_exit_codes(self):
        paths = [self.write("a.md", A_OLD), self.write("b.md", A_NEW)]
        process = run_diff(paths)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(process.stdout.rstrip("\n"), EXAMPLE_A)
        for option in (["--fail-on=meaning-risk"], ["--fail-on", "meaning-risk"]):
            with self.subTest(option=option):
                process = run_diff(option + paths)
                self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "", "終了コード1でも標準エラーは空（0.4）")
                self.assertTrue(process.stdout.startswith(EXAMPLE_A + "\n"), process.stdout)
                self.assertEqual(process.stdout[len(EXAMPLE_A):].strip("\n"), FAIL_LINE_A)
                # 10.2 D11: lint と同じく、空行1つのあとに出す。最後の行のあとに改行1つ（10.1 L3）
                self.assertEqual(process.stdout, EXAMPLE_A + "\n\n" + FAIL_LINE_A + "\n")
        with self.subTest(option="--json --fail-on"):
            process = run_diff(["--json", "--fail-on=meaning-risk"] + paths)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertEqual(process.stderr, "")
            self.assertEqual(json.loads(process.stdout)["meaning_risk_count"], 1, "--json のときは JSON だけを出す")

    def test_example_b_report_has_no_diff_line(self):
        report = self.report(self.diff2(B_OLD, B_NEW))
        self.assertEqual(report, EXAMPLE_B)
        self.assertFalse([line for line in report.split("\n") if line.startswith("  差: ")])

    def test_example_c_report(self):
        self.assertEqual(self.report(self.diff2(C_OLD, C_NEW)), EXAMPLE_C)

    def test_report_parts_make_the_report(self):
        """2.10: report() は report_parts() の節（risks、rules、full_diff）を並べたもの。ない節は空の文字列。
        check は節ごとに使い、照合の unsupported も同じ形の行にする（3.5 の例3）。
        diff の詰めで、文体の硬化の検査と勢いの検査の節（stiffness、tone）を rules と full_diff の間に足した（候補がなければ空）。"""
        report_parts = self.need_function("report_parts")
        result = self.diff2(C_OLD, C_NEW)
        parts = report_parts(result)
        self.assertEqual(sorted(parts), ["full_diff", "hedges", "immutable", "politeness", "register", "risks", "rules", "stiffness", "tone"])
        status = self.report(result).split("\n")[1]
        body = [part for part in (parts["risks"], parts["rules"], parts["stiffness"], parts["tone"], parts["full_diff"])
                if part]
        self.assertEqual(self.report(result), "\n".join([FIRST_LINE, status, DISCLAIMER]) + "\n\n" + "\n\n".join(body)
                         + "\n\n" + status)
        self.assertTrue(parts["rules"].startswith("■ 規則の見直し候補（"), parts["rules"])
        self.assertTrue(parts["full_diff"].startswith("■ 全文差分（変更 2か所。省略していません）"), parts["full_diff"])
        same = report_parts(self.diff2(A_OLD, A_OLD))
        self.assertEqual(same, {"risks": "", "rules": "", "stiffness": "", "tone": "", "hedges": "", "immutable": "", "politeness": "", "register": "",
                                "full_diff": "■ 全文差分: 変わった箇所はありません。"})
        unsupported = {"kind": "unsupported", "subkind": "number", "old_line": None, "new_line": 4, "old": None,
                       "new": "再試行は最大3回です。", "detail": {"text": "3回", "value": "3", "unit": "回"}, "basis": None}
        name = dict(unsupported, subkind="name", new_line=2, new="移行先はMySQLです。", detail={"text": "MySQL"})
        merged = dict(result, meaning_risks=[unsupported, name])
        self.assertEqual(report_parts(merged)["risks"].split("\n"), [
            "■ 意味が変わる恐れ（2件。原文と資料に照らして確かめる）",
            "- 資料にない数値（後4行目）: 3回",
            "  後: 再試行は最大3回です。",
            "- 資料にない名前（後2行目）: MySQL",
            "  後: 移行先はMySQLです。",
        ])
        material = dict(EXAMPLE_A_RISK_FOR_PARTS, basis="material")
        self.assertIn("- 数値が変わった（1行目）: 3日 → 30日（資料にある値）",
                      report_parts(dict(result, meaning_risks=[material]))["risks"].split("\n"))

    def test_pair3_diff_line(self):
        report = self.report(self.diff2(PAIR3_OLD, PAIR3_NEW))
        self.assertIn(PAIR3_DIFF_LINE, full_diff_section(report))


class TestFailOnScope(DiffCase):
    """10.6 B1（目標の D-2）: --fail-on=meaning-risk が数えるのは、kind が number、negation、swap、
    sentence_type（marks と question）の意味が変わる恐れだけ。変えない箇所（protected）は意味が変わる恐れの節に出すが、
    条件には数えない。JSON の fail_on_meaning_risk_count は数える種類の件数、meaning_risk_count は今までどおり全件。"""

    COUNTED = (
        ("保存期間は3日です。\n", "保存期間は30日です。\n", "number"),
        ("田中が佐藤を承認した。\n", "佐藤が田中を承認した。\n", "swap"),
        ("データを保存します。\n", "データを保存しません。\n", "negation"),
        ("この設定で動くでしょうか。\n", "この設定で動きます。\n", "sentence_type"),
        ("原因は設定ミスかもしれない。\n", "原因は設定ミスだ。\n", "sentence_type"),
    )
    PROTECTED = (
        ("強制するには `--force` を付ける。\n", "強制するには `--forced` を付ける。\n"),
        ("[手順書](https://example.com/guide-a) を読む。\n", "[手順書](https://example.com/guide-b) を読む。\n"),
        ("手順です。\n\n```sh\nretry --count 3\n```\n", "手順です。\n\n```sh\nretry --count 5\n```\n"),
        ("> 締め切りは金曜です。\n", "> 締め切りは月曜です。\n"),
    )

    def test_counted_kinds_exit_1(self):
        self.need_v2_diff()
        for before, after, kind in self.COUNTED:
            with self.subTest(before=before):
                result = self.diff2(before, after)
                self.assertIn(kind, [risk["kind"] for risk in result["meaning_risks"]])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)
                self.assertEqual(result["fail_on_meaning_risk_count"], result["meaning_risk_count"])
                paths = [self.write("a.md", before), self.write("b.md", after)]
                process = run_diff(["--fail-on=meaning-risk"] + paths)
                self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")

    def test_protected_only_is_shown_but_not_counted(self):
        self.need_v2_diff()
        for before, after in self.PROTECTED:
            with self.subTest(before=before):
                result = self.diff2(before, after)
                self.assertEqual([risk["kind"] for risk in result["meaning_risks"]], ["protected"], result["meaning_risks"])
                self.assertEqual(result["meaning_risk_count"], 1)
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)
                self.assertEqual(result["status"], "has_candidates")
                self.assertIn("■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）", self.report(result))
                paths = [self.write("a.md", before), self.write("b.md", after)]
                for option in (["--fail-on=meaning-risk"], ["--json", "--fail-on=meaning-risk"]):
                    process = run_diff(option + paths)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertEqual(process.stderr, "")
                    self.assertNotIn("終了コード1", process.stdout)

    def test_mixed_line_names_the_counted_number(self):
        """数える種類と数えない種類が混ざるときは、最後の行に全件と数えた件数の両方を書く（数が合わないと読み違えるため）。"""
        before = "保存期間は3日です。\n\n強制するには `--force` を付ける。\n"
        after = "保存期間は30日です。\n\n強制するには `--forced` を付ける。\n"
        result = self.diff2(before, after)
        self.assertEqual([risk["kind"] for risk in result["meaning_risks"]], ["number", "protected"])
        self.assertEqual((result["meaning_risk_count"], result["fail_on_meaning_risk_count"]), (2, 1))
        process = run_diff(["--fail-on=meaning-risk", self.write("a.md", before), self.write("b.md", after)])
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        self.assertTrue(process.stdout.endswith(
            "\n\n終了コード1: --fail-on=meaning-risk の条件に当たりました"
            "（意味が変わる恐れ 2件のうち、数値・否定・入れ替え・文の種類 1件）。\n"), process.stdout)


class TestJsonShape(DiffCase):
    """2.8 の --json（形式2）。キーの順、例A の full_diff、CLI と API が同じこと。"""

    def test_top_level_keys_and_values(self):
        result = self.diff2(A_OLD, A_NEW)
        self.assertEqual(list(result), TOP_KEYS)
        self.assertEqual(result["format"], "yomiyasu-diff")
        self.assertEqual(result["format_version"], 2)
        self.assertEqual(result["status"], "has_candidates")
        self.assertIs(result["changed"], True)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["meaning_risk_count"], 1)
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        self.assertEqual(result["not_judged"], ["meaning_equivalence", "reader_comprehension"])

    def test_example_a_full_diff(self):
        full = self.diff2(A_OLD, A_NEW)["full_diff"]
        self.assertEqual(full["hunks"], [EXAMPLE_A_HUNK])
        self.assertEqual(full["final_newline"], {"old": True, "new": True})
        # 10.2 D13: API の diff() に encoding_notes を渡さなければ空のリスト
        self.assertEqual(full["encoding_notes"], [], "API の diff() に encoding_notes を渡さなければ [] （10.2 D13）")
        self.assertEqual(list(full), ["encoding_notes", "final_newline", "limits_applied", "hunks"])
        self.assertEqual(list(full["hunks"][0]), list(EXAMPLE_A_HUNK), "hunk のキーの順は 2.8 の例のとおり")
        self.assertEqual(full["limits_applied"], [])

    def test_encoding_notes_keyword(self):
        """2.8、2.10: diff() と full_diff() は keyword 引数 encoding_notes を受け、full_diff にそのまま入れる。"""
        notes = [{"kind": "eol", "old": "crlf", "new": "lf"}]
        self.assertEqual(self.diff2(A_OLD, A_NEW)["full_diff"]["encoding_notes"], [])
        result = yomiyasu_diff.diff(A_OLD, A_NEW, None, encoding_notes=notes)
        self.assertEqual(result["full_diff"]["encoding_notes"], notes)
        full_diff = self.need_function("full_diff")
        self.assertEqual(full_diff(A_OLD, A_NEW)["encoding_notes"], [])
        self.assertEqual(full_diff(A_OLD, A_NEW, encoding_notes=notes)["encoding_notes"], notes)
        self.assertEqual(full_diff(A_OLD, A_NEW)["hunks"], [EXAMPLE_A_HUNK])
        # 同じ文字列で注記だけがあるときは no_change にしない（2.6）
        same = yomiyasu_diff.diff(A_OLD, A_OLD, None, encoding_notes=notes)
        self.assertEqual(same["status"], "changed_without_candidates")
        self.assertIs(same["changed"], True)

    def test_cli_json_is_the_api_result(self):
        process = run_diff(["--json", self.write("a.md", A_OLD), self.write("b.md", A_NEW)])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(process.stdout.isascii(), "--json は ASCII だけ（ensure_ascii=True）")
        from_cli = json.loads(process.stdout)
        from_api = json.loads(json.dumps(yomiyasu_diff.diff(A_OLD, A_NEW), ensure_ascii=True))
        self.assertEqual(list(from_cli), TOP_KEYS)
        # 同じ改行コードで BOM のない2つのファイルなので、CLI の注記も空のリスト（API の既定と同じ。10.2 D13）。
        # 注記の中身は test_cli_line_endings_or_bom_only が見る
        self.assertEqual(from_cli["full_diff"]["encoding_notes"], [], "改行コードも BOM も同じなら注記はない")
        self.assertEqual(from_cli, from_api)
        # 出力は json.dumps(..., ensure_ascii=True, indent=1) と同じ（2.8）
        self.assertEqual(process.stdout, json.dumps(from_cli, ensure_ascii=True, indent=1) + "\n")


class TestBlockKinds(DiffCase):
    """6.3 ブロックの種類: コード、引用、表、見出しの段（2.3の5と7、2.5.7）。"""

    def kinds(self, result):
        return [(risk["kind"], risk.get("subkind")) for risk in result["meaning_risks"]]

    def test_code_block(self):
        result = self.diff2("手順です。\n\n```sh\nx = 1\n```\n", "手順です。\n\n```sh\nx = 2\n```\n")
        [hunk] = result["full_diff"]["hunks"]
        self.assertEqual((hunk["old_blocks"], hunk["new_blocks"]), (["code"], ["code"]))
        self.assertIn("@ 元4行目 → 後4行目（コード）", full_diff_section(self.report(result)))
        self.assertIn(("protected", "code"), self.kinds(result))
        self.assertNotIn("number", [kind for kind, _ in self.kinds(result)], "コードの数は数値の候補にしない（2.5.2）")

    def test_quote(self):
        result = self.diff2("> 期限は3日です。\n", "> 期限は30日です。\n")
        [hunk] = result["full_diff"]["hunks"]
        self.assertEqual((hunk["old_blocks"], hunk["new_blocks"]), (["quote"], ["quote"]))
        self.assertIn("@ 元1行目 → 後1行目（引用）", full_diff_section(self.report(result)))
        self.assertIn("number", [kind for kind, _ in self.kinds(result)])
        self.assertIn(("protected", "quote"), self.kinds(result))

    def test_table_cell(self):
        result = self.diff2("| 項目 | 期間 |\n|---|---|\n| 保存 | 3日 |\n", "| 項目 | 期間 |\n|---|---|\n| 保存 | 30日 |\n")
        [hunk] = result["full_diff"]["hunks"]
        self.assertEqual((hunk["old_blocks"], hunk["new_blocks"]), (["table"], ["table"]))
        self.assertIn("@ 元3行目 → 後3行目（表）", full_diff_section(self.report(result)))
        self.assertIn("number", [kind for kind, _ in self.kinds(result)])

    def test_heading_level(self):
        result = self.diff2("## 手順\n\n本文です。\n", "### 手順\n\n本文です。\n")
        [hunk] = result["full_diff"]["hunks"]
        self.assertEqual((hunk["old_blocks"], hunk["new_blocks"]), (["heading"], ["heading"]))
        self.assertEqual(hunk["notes"], [{"kind": "heading_level", "old": 2, "new": 3}], "10.2 D10 の注記の形")
        self.assertIn("@ 元1行目 → 後1行目（見出し、見出しの段 2 → 3）", full_diff_section(self.report(result)))


class TestLongLine(DiffCase):
    """6.3 長い行: 160字を超える行も元と後は丸ごと、差は変わった文だけ（2.4、0.2の7）。"""

    SENTENCES = (
        "朝の打ち合わせで今週の予定を確かめた。", "担当の割り振りは前の週と同じにした。", "新しい依頼は二件あり、どちらも急ぎではない。",
        "古い資料は共有のフォルダから外した。", "報告は金曜の午後にまとめて送る。", "会議室の予約は総務の窓口に頼んだ。",
        "手順書の誤字は見つけた人が直す。", "来月の研修は希望者だけが受ける。", "備品の注文は月末にまとめて出す。",
        "鍵の当番は名簿の順に回す。", "質問は掲示板に書いてもらう。", "夜間の作業は前の日までに知らせる。",
        "共有の予定表は毎朝見直す。", "休みの連絡は前の日の夕方までに出す。", "窓の鍵は帰る前に確かめる。",
        "掃除の当番表は入口に貼る。", "郵便物は昼までに仕分ける。", "会議の記録は翌日までに残す。", "片付けは最後に残った人が行う。",
    )

    def test_long_line_shows_whole_lines_and_short_diff(self):
        old_line = "".join(self.SENTENCES)
        self.assertGreaterEqual(len(old_line), 300)
        new_line = replace_once(old_line, "報告は金曜", "報告は木曜")
        report = self.report(self.diff2(old_line + "\n", new_line + "\n"))
        section = full_diff_section(report)
        self.assertIn("  元: " + old_line, section, "元は省かずに丸ごと出す")
        self.assertIn("  後: " + new_line, section, "後は省かずに丸ごと出す")
        [diff_line] = [line for line in section if line.startswith("  差: ")]
        self.assertIn("報告は[-金-]{+木+}曜の午後にまとめて送る。", diff_line)
        self.assertTrue(diff_line.endswith("（変わらない文は省略。元と後は上に全文）"), diff_line)
        self.assertIn("…", diff_line)
        self.assertNotIn(self.SENTENCES[0], diff_line)
        self.assertNotIn(self.SENTENCES[-1], diff_line)

    def test_long_line_without_sentence_breaks_has_no_omission_note(self):
        """反証レビュー E11: 160字を超える行でも、文の切れ目がなく何も省かなかったときは「（変わらない文は省略。…）」を付けない。"""
        old_line = "あ" * 100 + "い" + "う" * 100
        new_line = "あ" * 100 + "え" + "う" * 100
        section = full_diff_section(self.report(self.diff2(old_line + "\n", new_line + "\n")))
        self.assertIn("  差: " + "あ" * 100 + "[-い-]{+え+}" + "う" * 100, section)

    def test_invisible_format_characters_are_named(self):
        """反証レビュー F12・E10: 印の中の幅のない見えない文字（Unicode の分類 Cf。U+200B、U+00AD など）は
        〔U+200B〕の形で書く（2.4「印の中の見えない文字は名前で書く」）。印の外は書き換えない。"""
        for char, name in (("​", "〔U+200B〕"), ("­", "〔U+00AD〕"), ("⁠", "〔U+2060〕")):
            with self.subTest(char="U+%04X" % ord(char)):
                result = self.diff2("設定を変更します。\n", "設定を" + char + "変更します。\n")
                section = full_diff_section(self.report(result))
                self.assertIn("  差: 設定を{+" + name + "+}変更します。", section)
                self.assertIn("  後: 設定を" + char + "変更します。", section)


class TestMovedLinesAndFinalNewline(DiffCase):
    """6.3 移した行と末尾の改行（2.3の8と9、2.8の行番号の決まり）。"""

    def test_moved_line_pairs_moved_to_and_moved_from(self):
        orig = "一行目の文です。\n二行目の文です。\n三行目の文です。\n四行目の文です。\n"
        rewrite = "二行目の文です。\n三行目の文です。\n四行目の文です。\n一行目の文です。\n"
        result = self.diff2(orig, rewrite)
        deleted, inserted = result["full_diff"]["hunks"]
        self.assertEqual((deleted["tag"], inserted["tag"]), ("delete", "insert"))
        self.assertEqual(deleted["moved_to"], inserted["index"])
        self.assertEqual(inserted["moved_from"], deleted["index"])
        self.assertEqual((deleted["old_start"], deleted["old_end"], deleted["new_start"], deleted["new_end"]), (1, 1, 1, 0))
        self.assertEqual((inserted["old_start"], inserted["old_end"], inserted["new_start"], inserted["new_end"]), (5, 4, 4, 4))
        section = full_diff_section(self.report(result))
        self.assertIn("@ 元1行目を削除（本文、移した行。後4行目へ）", section)
        # 10.2 D12: 追加の側の注記
        self.assertIn("@ 後4行目を追加（本文、移した行。元1行目から）", section)
        # 10.2 D10: 注記はオブジェクトの並び。hunk は相手の hunk の番号、line は相手の側の行番号
        self.assertEqual(deleted["notes"], [{"kind": "moved_to", "hunk": inserted["index"], "line": 4}])
        self.assertEqual(inserted["notes"], [{"kind": "moved_from", "hunk": deleted["index"], "line": 1}])
        self.assert_complete(orig, rewrite, result["full_diff"])

    def test_final_newline_note(self):
        """10.2 D9b（10.4 S17）: 末尾の改行の注記は hunk の注記ではなく、文書全体の注記の行。JSON は final_newline だけに入れる。"""
        orig, rewrite = "最初の行です。\n最後の行です。\n", "最初の行です。\n最後の行を直しました。"
        result = self.diff2(orig, rewrite)
        self.assertEqual(result["full_diff"]["final_newline"], {"old": True, "new": False})
        [hunk] = result["full_diff"]["hunks"]
        self.assertEqual(hunk["notes"], [], "末尾の改行は hunk の notes に入れない")
        section = full_diff_section(self.report(result))
        self.assertEqual(section[:3], ["■ 全文差分（変更 1か所。省略していません）", "- 末尾の改行: あり → なし",
                                       "@ 元2行目 → 後2行目（本文）"])
        self.assertNotIn("末尾の改行 あり → なし", "\n".join(section), "hunk の見出しには付けない")
        self.assert_complete(orig, rewrite, result["full_diff"])


class TestBudget(DiffCase):
    """6.3 上限: 文字の対応にかける字数の予算（両側の合計200,000字）を超えても、完全さは保つ（2.3の4）。

    2.3の4は「文字の対応にかける字数」の数え方（行の全体か、前と後ろの同じ部分を外した残りか）を決めていない。
    どちらの数え方でも予算を超えるよう、各段落の最初の文と最後の文を書き換える。"""

    SENTENCES = ("第{n}節の{k}番目の記録では、値を表と照らして確かめる。", "担当者は{k}回目の結果を残し、翌週に共有する。",
                 "古い値は消さず、変えた理由を横に書く。")

    def test_budget_is_applied_and_completeness_is_kept(self):
        """diff の詰めで、塊をそのまま文字で対応させる上限を2,000字から500字にした
        （_BLOCK_ALIGN_LIMIT。500字を超える塊は文の断片に分け、変わった断片だけを対応させる）。前の入力（1,000字の段落120個）は
        変わった断片だけでは予算に届かなくなったので、500字以下の段落を250個にした（予算の仕組みと完全さを見る狙いは同じ）。"""
        full_diff = self.need_function("full_diff")
        old_blocks, new_blocks, middle = [], [], 0
        for n in range(250):
            parts = sentences_of(440, n, self.SENTENCES)
            old_paragraph = "".join(parts)
            new_paragraph = "".join([replace_once(parts[0], "確かめる", "確かめた")] + parts[1:-1]
                                    + [parts[-1][:-1] + "ことにした。"])
            middle += changed_middle(old_paragraph, new_paragraph)
            old_blocks.append("## 節%d\n%s" % (n, old_paragraph))
            new_blocks.append("## 節%d\n%s" % (n, new_paragraph))
        orig, rewrite = "\n".join(old_blocks) + "\n", "\n".join(new_blocks) + "\n"
        self.assertGreater(len(orig) + len(rewrite), 200000)
        self.assertGreater(middle, 200000, "前と後ろの同じ部分を外して数えても予算を超える")
        self.assertLessEqual(max(len(block.split("\n")[1]) for block in old_blocks + new_blocks), 500)
        full = full_diff(orig, rewrite)
        self.assertEqual(len(full["hunks"]), 250)
        omitted = [hunk for hunk in full["hunks"] if hunk["segments_omitted"] == "budget"]
        self.assertTrue(omitted, "予算を超えた hunk は segments_omitted が budget")
        for hunk in omitted:
            self.assertIsNone(hunk["segments"])
        self.assertIn("budget", full["limits_applied"])
        self.assert_complete(orig, rewrite, full)

    def test_budget_counts_joined_hunk_text_of_both_sides(self):
        """10.4 S6: 予算は「文字の対応にかける文字列（行をつないだもの）の長さの、両側の合計」で数え、200,000字まで（ちょうどは含む）。
        1行が500字の段落の1字を変えた hunk（1つ1,000字）を201個並べると、200個目まではちょうど200,000字で対応を取り、
        201個目は予算を超えるので segments が null、segments_omitted が budget になる。予算を超えた hunk のあとも完全さは保つ。
        diff の詰めで、塊をそのまま文字で対応させる上限を500字にしたので、前の入力（1,000字の行を
        101個）から、500字の行を201個に変えた（数え方を見る狙いは同じ）。"""
        full_diff = self.need_function("full_diff")
        old_blocks, new_blocks = [], []
        for n in range(201):
            line = "".join(sentences_of(500, n, self.SENTENCES))[:500]
            middle = line.index("番目") - 1
            changed = line[:middle] + ("壱" if line[middle] != "壱" else "弐") + line[middle + 1:]
            self.assertEqual((len(line), len(changed)), (500, 500))
            old_blocks.append("## 節%d\n%s" % (n, line))
            new_blocks.append("## 節%d\n%s" % (n, changed))
        orig, rewrite = "\n".join(old_blocks) + "\n", "\n".join(new_blocks) + "\n"
        full = full_diff(orig, rewrite)
        self.assertEqual(len(full["hunks"]), 201)
        for hunk in full["hunks"][:200]:
            self.assertIsNotNone(hunk["segments"], hunk["index"])
            self.assertIsNone(hunk["segments_omitted"])
        last = full["hunks"][200]
        self.assertIsNone(last["segments"])
        self.assertEqual(last["segments_omitted"], "budget")
        self.assert_complete(orig, rewrite, full)

    def test_too_large_hunk(self):
        """1つの hunk の文字の対応だけで予算（200,000字）を超えるときは segments_omitted が too_large で、
        limits_applied に too_large が入る。完全さは保つ（反証レビュー spec 3章の6）。"""
        full_diff = self.need_function("full_diff")
        orig = "".join("第{}の文では値を{}回確かめる。".format(n, n % 7) for n in range(9000)) + "\n"
        rewrite = "".join("{}番目の文で値を{}度見直した。".format(n, n % 5) for n in range(9000)) + "\n"
        self.assertGreater(len(orig) + len(rewrite), 200000)
        full = full_diff(orig, rewrite)
        [hunk] = full["hunks"]
        self.assertIsNone(hunk["segments"])
        self.assertEqual(hunk["segments_omitted"], "too_large")
        self.assertEqual(full["limits_applied"], ["too_large"])
        self.assert_complete(orig, rewrite, full)

    def test_long_fragment(self):
        """2,000字を超える1文（文の断片）の組は、文字の対応を省いて丸ごと削除と追加にし、limits_applied に long_fragment が入る。
        segments は作るので、segments_omitted は null。完全さは保つ（反証レビュー spec 3章の6）。"""
        full_diff = self.need_function("full_diff")
        sentence = "、".join("項目{}の値を記録する".format(n) for n in range(250)) + "。"
        self.assertGreater(len(sentence), 2000)
        orig = "前の段落です。\n" + sentence + "\n"
        rewrite = "前の段落です。\n" + sentence.replace("項目100の", "項目101の") + "\n"
        full = full_diff(orig, rewrite)
        [hunk] = full["hunks"]
        self.assertIsNotNone(hunk["segments"])
        self.assertIsNone(hunk["segments_omitted"])
        self.assertEqual(full["limits_applied"], ["long_fragment"])
        self.assert_complete(orig, rewrite, full)


class TestExistingKeys(DiffCase):
    """6.3 既存の9キー: v1.1.2 で作った合成20組（BOM なし）の9キーと同じ（v1.1.2 でも通る後戻り防止）。"""

    def test_nine_keys_match_v112_fixture(self):
        """合成20組の9キーが v1.1.2 の fixture と同じ（v1.1.2 でも通る後戻り防止）。v2.1.1 で structure の後ろに足した
        見出しの変化の文は除いて比べ、足した文は HEADING_ADDED と照らす。"""
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["keys"], NINE_KEYS)
        self.assertEqual(len(data["cases"]), 20)
        for case in data["cases"]:
            with self.subTest(case=case["id"]):
                self.assertNotIn(BOM, case["orig"] + case["rewrite"])
                result = yomiyasu_diff.diff(case["orig"], case["rewrite"], case["stance"])
                self.assertEqual([key for key in result if key in NINE_KEYS], NINE_KEYS, "9キーの間の順を保つ（2.8）")
                actual = json.loads(json.dumps({key: result[key] for key in NINE_KEYS}, ensure_ascii=False))
                # v2.1.1 で structure の後ろに見出しの変化の文を足した。v1.1.2 の文は前にそのまま並び、足した文は見出しの文だけ
                added = actual["structure"][len(case["expected"]["structure"]):]
                actual["structure"] = actual["structure"][:len(case["expected"]["structure"])]
                self.assertEqual(actual, case["expected"])
                self.assertEqual(added, HEADING_ADDED.get(case["id"], []))


class TestArguments(DiffCase):
    """6.3 引数（2.1。argparse、使い方の誤りは2）。"""

    def setUp(self):
        super().setUp()
        self.before = self.write("a.md", "この方式は速いと思う。\n")
        self.after = self.write("b.md", "この方式は速い。\n")

    def json_of(self, process):
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_stance_with_space_works(self):
        spaced = self.json_of(run_diff(["--json", "--stance", "説明", self.before, self.after]))
        joined = self.json_of(run_diff(["--json", "--stance=説明", self.before, self.after]))
        self.assertEqual(spaced["endings"]["stance"], "説明")
        self.assertEqual(spaced, joined)

    def test_unknown_stance_is_usage_error(self):
        for option in (["--stance=不明"], ["--stance", "不明"]):
            with self.subTest(option=option):
                process = run_diff(option + [self.before, self.after])
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)

    def test_help_exits_zero(self):
        process = run_diff(["-h"])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(process.stdout.strip())

    def test_missing_file(self):
        process = run_diff([self.root / "none.md", self.after])
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertTrue(process.stderr.startswith("Error opening file"), process.stderr)
        self.assertNotIn("Traceback", process.stderr)

    def test_one_positional_argument(self):
        process = run_diff([self.before])
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)

    def test_unknown_option(self):
        process = run_diff(["--nope", self.before, self.after])
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)

    def test_abbreviations_are_not_accepted(self):
        """10.7: argparse の省略形を受けない（allow_abbrev=False。lint、diff、check の3本でそろえる）。"""
        for args in (["--js"], ["--fail", "meaning-risk"], ["--stan", "説明"], ["--end"]):
            with self.subTest(args=args):
                process = run_diff(args + [self.before, self.after])
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn("unrecognized arguments", process.stderr)
                self.assertEqual(process.stderr.rstrip("\n").split("\n")[-1],
                                 "引数の誤りです。yomiyasu_diff.py -h で使い方を確かめてください。")

    def test_endings_with_json(self):
        process = run_diff(["--endings", self.before, "--json"])
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn("--endings は --json に対応していません", process.stderr)

    def test_dash_reads_stdin(self):
        from_files = self.json_of(run_diff(["--json", self.before, self.after]))
        from_stdin = self.json_of(run_diff(["--json", "-", self.after], stdin="この方式は速いと思う。\n"))
        self.assertEqual(from_stdin, from_files)
        self.assertIn("full_diff", from_stdin)


class TestDeterminism(DiffCase):
    """6.3 決定性: PYTHONHASHSEED が違っても --json の出力が同じ（v1.1.2 でも通る後戻り防止）。"""

    def test_json_does_not_depend_on_hash_seed(self):
        """コーパス10組の --json が PYTHONHASHSEED 0 と 1 で同じ（v1.1.2 でも通る後戻り防止）。"""
        for source, rewritten in corpus_pairs()[:10]:
            with self.subTest(pair=rewritten.name):
                outputs = []
                for seed in ("0", "1"):
                    env = dict(os.environ, PYTHONHASHSEED=seed)
                    process = run_diff(["--json", source, rewritten], env=env)
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    outputs.append(process.stdout)
                self.assertEqual(outputs[0], outputs[1])


class TestPerformance(DiffCase):
    """6.3 性能（2.11 の約束の1と、tests に置く緩い上限）。

    測る処理は子プロセスで動かし（CHILD_TIMEOUT 秒で打ち切る）、基準の処理と交互に最大5回測った最も速い値を上限と比べる。
    上限の秒数は v2.0.1 と同じで、基準の処理が遅い機械ではその比の分だけ延ばす（くわしくは GROWTH_LIMIT の前の注釈）。
    同じ形で4分の1の大きさの文書も測り、時間の伸びが文書の大きさの2乗に近づかないことも見る。"""

    def test_full_rewrite_of_60000_chars(self):
        """6万字の全面書き換えで full_diff() と meaning_risks() の合計が3秒未満。
        9キーの分析（type_changes）は測らない（2.11の1）。meaning_risks() には type_changes=[] を渡す。"""
        self.need_function("full_diff")
        self.need_function("meaning_risks")

        def pair(min_chars):
            orig, count = long_document(SECTION_SENTENCES, min_chars=min_chars)
            return [orig, long_document(REWRITE_SENTENCES, paragraphs=count)[0]]

        orig, rewrite = full = pair(60000)
        self.assertGreaterEqual(len(orig), 60000)
        self.assertGreaterEqual(len(rewrite), 60000)
        self.assert_fast("full_rewrite", [full], 3.0, [pair(15000)],
                         "6万字の全面書き換えで full_diff() と meaning_risks() の合計が3秒未満")

    def test_small_fix_in_60000_chars(self):
        self.need_function("full_diff")

        def pair(min_chars, section):
            orig, _ = long_document(SECTION_SENTENCES, min_chars=min_chars)
            middle = orig.index("第%d節の" % section)
            return [orig, orig[:middle] + "第%d節の" % (section + 1) + orig[middle + len("第%d節の" % section):]]

        orig, rewrite = full = pair(60000, 200)
        self.assertEqual(len(rewrite), len(orig))
        timing = self.assert_fast("small_fix", [full], 0.5, [pair(15000, 50)], "6万字の小さな修正で full_diff() が0.5秒未満")
        self.assertEqual([timing["value"], timing["quarter_value"]], [1, 1], "hunk は1つ")

    def short_paragraphs(self, min_chars=60000):
        orig, count = long_document(SHORT_SENTENCES, min_chars=min_chars, sentences_per_paragraph=2)
        self.assertGreaterEqual(len(orig), min_chars)
        self.assertTrue(850 * min_chars // 60000 <= count <= 1000 * min_chars // 60000, count)
        self.assertTrue(55 <= len(orig) / count - 2 <= 75, len(orig) / count)
        return orig, count

    def test_full_rewrite_of_short_paragraphs(self):
        """10.2 D16: 約65字の段落900個（6万字）の全面書き換えでも、full_diff() と meaning_risks() の合計が3秒未満。"""
        self.need_function("full_diff")
        self.need_function("meaning_risks")

        def pair(min_chars):
            orig, count = self.short_paragraphs(min_chars)
            return [orig, long_document(SHORT_REWRITE_SENTENCES, paragraphs=count, sentences_per_paragraph=2)[0]]

        full = pair(60000)
        self.assertGreaterEqual(len(full[1]), 60000)
        self.assert_fast("full_rewrite", [full], 3.0, [pair(15000)],
                         "短い段落の6万字の全面書き換えで full_diff() と meaning_risks() の合計が3秒未満")

    def test_small_fixes_at_both_ends_of_short_paragraphs(self):
        """10.2 D16: 短い段落900個の文書で、最初と最後の段落を1字ずつ直しても full_diff() が0.5秒未満（前後の同じ行を外すだけでは
        速くならない形）。hunk は2つ。"""
        self.need_function("full_diff")

        def pair(min_chars):
            orig, _ = self.short_paragraphs(min_chars)
            first, last = orig.index("第0段の"), orig.rindex("段の")
            return [orig, orig[:first] + "第一段の" + orig[first + len("第0段の"):last] + "節の" + orig[last + len("段の"):]]

        timing = self.assert_fast("small_fix", [pair(60000)], 0.5, [pair(15000)],
                                  "短い段落の6万字の両端の小さな修正で full_diff() が0.5秒未満")
        self.assertEqual([timing["value"], timing["quarter_value"]], [2, 2], "hunk は2つ")

    def test_corpus_48_pairs_diff_total_under_one_second(self):
        """コーパス48組の diff() 合計が1秒未満（v1.1.2 でも通る後戻り防止）。コーパスは大きさを変えられないので、伸びは見ない。"""
        pairs = [[read_exact(source), read_exact(rewritten)] for source, rewritten in corpus_pairs()]
        self.assertEqual(len(pairs), 48)
        timing = self.assert_fast("corpus", pairs, 1.0)
        self.assertEqual(timing["value"], 48)


class TestPerformanceEdges(DiffCase):
    """反証レビューで見つかった、2.11 の約束（6万字の全面書き換えで full_diff() と meaning_risks() の合計が3秒未満、
    6万字の小さな修正で full_diff() が0.5秒未満）を超えた形。測り方は TestPerformance と同じ（子プロセスで、基準の処理と交互に
    最大5回。同じ形で4分の1の大きさの文書からの伸びも見る）。"""

    def test_full_rewrite_with_many_numbers(self):
        """反証レビュー F5: 値の違う数値を6,000個あまり含む文書の全面書き換え（文が組にならない）。"""
        def pair(count):
            return ["\n\n".join("第{}項の値は{}件です。".format(i, i) for i in range(count)) + "\n",
                    "\n\n".join("別の書き方で{}回と書く。".format(i + 50000) for i in range(count)) + "\n"]

        full = pair(4200)
        self.assertGreaterEqual(len(full[0]), 60000)
        self.assert_fast("full_rewrite", [full], 3.0, [pair(1050)])

    def test_deleting_a_document_with_many_numbers(self):
        """反証レビュー E6: 数値を1万個含む6万字弱の1行を「なし。」にする（文書全体の数値の比べ）。
        v2.0.1 までは、値ごとにその行の文を前から順に見ていて、1行の文の数と値の数の積で時間が伸びた（4倍の大きさで約13倍）。"""
        def pair(count):
            return ["".join("{}件。".format(i) for i in range(count)) + "\n", "なし。\n"]

        self.assert_fast("full_rewrite", [pair(10000)], 3.0, [pair(2500)])

    def long_code_line(self, options=2300):
        line = " ".join("--opt%d=value%d" % (i, i) for i in range(options))
        orig = "設定の例です。\n\n```\n" + line + "\n```\n\n保存期間は3日です。\n"
        self.assertGreater(len(line), 40000 * options // 2300)
        return [orig, orig.replace("3日です", "30日です")]

    def test_long_code_line_with_a_small_fix(self):
        """反証レビュー regress 1: コードの囲みの中に4万字の1行がある文書で、本文の数値を1つ変える。
        意味が変わる恐れ、資料との照合、数値の取り出しが、どれも0.5秒未満（数値を取る前に伏せた長い空白の行で、
        番号つき箇条書きの番号の正規表現が2乗の時間にならない）。"""
        full, quarter = self.long_code_line(), self.long_code_line(575)
        for run in ("full_rewrite", "ground", "extract"):
            with self.subTest(run=run):
                self.assert_fast(run, [full], 0.5, [quarter])

    def test_long_line_without_japanese_periods(self):
        """反証レビュー E3・regress 2: 「。！？!?」のない6万字の1行（「．」で区切った文）の1語の直しで、full_diff() が0.5秒未満、
        meaning_risks() との合計が3秒未満（2,000字を超える断片と文に difflib の ratio() をかけない）。"""
        words = ("設定ファイル", "サーバー", "利用者", "管理者", "キャッシュ", "ログ", "画面", "手順書")
        verbs = ("を開きます", "を確認します", "が止まります", "を保存します", "が増えます", "を消します", "を送ります")

        def line(chars):
            parts, size, i = [], 0, 0
            while size < chars:
                parts.append("{}{}は{}{}．".format(words[i % 8], i, words[i * 3 % 8], verbs[i % 7]))
                size += len(parts[-1])
                i += 1
            return "".join(parts) + "\n"

        def pair(chars):
            orig = line(chars)
            return [orig, orig.replace("サーバー", "サーバ", 1)]

        def negated(chars):
            orig = line(60000)[:chars].rsplit("．", 1)[0] + "．\n"
            return [orig, orig.replace("を保存します", "を保存しません", 1)]

        full = pair(60000)
        timing = self.assert_fast("small_fix", [full], 0.5, [pair(15000)])
        self.assertEqual([timing["value"], timing["quarter_value"]], [1, 1])
        self.assert_fast("full_rewrite", [full], 3.0, [pair(15000)])
        self.assert_fast("full_rewrite", [negated(40000)], 3.0, [negated(10000)])

    def test_one_line_json_in_code_with_a_small_fix(self):
        """反証レビュー regress 2: コードの囲みの中の1行の JSON（約2.8万字）で1語だけ変える。full_diff() が0.5秒未満。"""
        def pair(items):
            data = json.dumps([{"id": i, "name": "item%d" % i, "tags": ["a", "b"], "ok": True} for i in range(items)])
            orig = "設定の例です。\n\n```json\n" + data + "\n```\n"
            return [orig, orig.replace('"item100"', '"item100x"')]

        self.assert_fast("small_fix", [pair(440)], 0.5, [pair(110)])

    def test_full_rewrite_of_long_lines_with_full_width_periods(self):
        """反証レビュー F6: 1行（段落）が2,000字を超える「．」の文書の全面書き換え。各文を少しずつ言い換える。
        4分の1の大きさの文書は、行の数をそろえて1行を750字にする（1行の長さに対する伸びを見る）。"""
        old_sentences = ("設定ファイル{n}の値を確かめ，記録の表と照らします．", "担当者は{n}番目の結果を残し，会議で共有します．",
                         "古い値は消さずに，変えた理由を横に書き足します．")
        new_sentences = ("設定ファイル{n}の値を見直し，記録の表と比べます．", "担当者は{n}番目の結果を記録し，会議で伝えます．",
                         "古い値は残したまま，変えた理由を横に足します．")

        def document(sentences, chars, width):
            lines, n = [], 0
            while sum(len(line) + 2 for line in lines) < chars:
                line = ""
                while len(line) < width:
                    line += sentences[n % 3].format(n=n)
                    n += 1
                lines.append(line)
            return "\n\n".join(lines) + "\n"

        def pair(chars, width):
            return [document(old_sentences, chars, width), document(new_sentences, chars, width)]

        self.assert_fast("full_rewrite", [pair(60000, 3000)], 3.0, [pair(15000, 750)])


# ---- CLI の約束（0.4、2.1、2.9、10.5）。lint の試験（test_v200_lint_output.py）と同じ型 ----

DIFF_HELP_DESCRIPTION = ("元の文と書き直した文を比べ、変わった箇所をすべて出し、意味が変わる恐れと規則の見直し候補を挙げます。"
                         "全文差分は意味が同じだという証明ではありません。意味が同じかどうかは判定しません。")
# 10.6 B1: 数える種類を書く。変えない箇所（コード、URL、引用など）は数えない
# diff の詰めの直し（反証で見つけた例）: 否定対比の主張の逆転と気持ちの語も数えないことを足した
# v2.1.0: 許可の言い方の変化と、事実や仕様を述べる種類で数える2つ（「場合がある」の言い切り、「必ず」などの足し）を足した。
# 能力の言い方の消えは、どの種類でも数えないことを書いた
# v2.1.1: 関連・相関の文に因果の言い方を足した書き換えと、選ぶ範囲（どれか一つ ↔ 全部）が入れ替わった書き換え、数に付いた概数や範囲の印の
# 消えと足しを数えることを足した
DIFF_HELP_FAIL_ON = ("意味が変わる恐れのうち、数値、否定、主語と目的語の入れ替え、文の種類（問いと平叙、文の種類の印）、引用の印の変化、"
                     "確度を強めた書き換え（かもしれない → 見込み、見込み → 予定、と思われる → 断定など）、"
                     "原文の状態の語（未定、未確認、調査中など）が消えた書き換え、原文にない書き手の約束・保証・再発防止の誓いの足しが"
                     "1件でもあれば、終了コード1で終わります。許可の言い方（してよい、してもよい、構わない）が消えたか増えた書き換えも数えます。"
                     "事実や仕様を述べる種類（--doc-type が pr、article、incident、proposal、manual、formal、paper）では、"
                     "「場合がある」「ことがある」を消して言い切った書き換えと、断定に「必ず」「確実に」などを足した書き換えも数えます"
                     "（ほかの種類と種類なしでは数えません）。能力の言い方（できる、可能だ）が消えた書き換えは、どの種類でも数えません。"
                     "コード・URL・引用ブロックなど変えない箇所の変化は、意味が変わる恐れとして出しますが、"
                     "この条件には数えません。否定対比の主張の逆転と、元にない気持ちの語も数えません。確度を弱めた書き換え、"
                     "数えない語だけの確度の変化、予定の言い切り（する予定です → します）、かぎかっこの中の言葉の変化も数えません。"
                     "推量の印が同じ強さの慎重な言い方に替わっただけの文（かもしれません → 恐れがあります、と思われます → 見込みです）も数えません。"
                     "原文にない因果のつながりの足しと、書き手の行為と読む印（いたします、今後・改めて、"
                     "弊社などの主語）のない「〜します」の足し（説明や手順の文かもしれないもの）も数えません。"
                     "ただし、関連・相関を述べた原文の文に因果の言い方（因果、原因、引き起こす など）を足した書き換えと、"
                     "選ぶ範囲が入れ替わった書き換え（または・どちらか → 両方・すべて、またはその逆）、"
                     "同じ数に付いた概数や範囲の印（約、ほど、以上、未満 など）が消えたか増えた書き換えは数えます。"
                     "候補は確かめる場所で、意味が変わったという判定ではありません。"
                     "条件に当たらなくても、意味が同じだという証明にはなりません。")
UNKNOWN_FAIL_ON = "--fail-on に使えない値です: {}。diff で使えるのは meaning-risk です。"
UNKNOWN_STANCE = "--stance に使えない値です: {}。使えるのは 勧め、読み手に勧める、決まり、手順、説明、報告、体験 です。"
OPEN_ERROR = re.compile(r"^Error opening file (?P<path>.*): ファイルを開けません（(?P<reason>.+)）\n$")
NOT_UTF8_FILE = "Error opening file {}: UTF-8 として読めません\n"
NOT_UTF8_STDIN = "Error reading stdin: UTF-8 として読めません\n"
NO_STDIN = "Error reading stdin: 標準入力を読めません（標準入力がありません）\n"
USAGE_HINT = "引数の誤りです。yomiyasu_diff.py -h で使い方を確かめてください。"
CLOSED_PIPE = "yomiyasu_diff.py: 出力先が閉じられたため、結果を最後まで書けませんでした。"

NO_STDIN_WORKER = (
    "import runpy, sys\n"
    "script = sys.argv[1]\n"
    "sys.stdin = None\n"
    "sys.argv = [script] + sys.argv[2:]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)
INTERNAL_ERROR_WORKER = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import markdown_visibility\n"
    "def broken(*args, **kwargs):\n"
    "    raise RuntimeError('synthetic failure for the test')\n"
    "markdown_visibility.analyze_markdown = broken\n"
    "script = sys.argv[2]\n"
    "sys.argv = [script] + sys.argv[3:]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)
# 古い版（v1.1.2）の markdown_visibility の代わり。decode_source だけがない。
OLD_VISIBILITY_STUB = "".join(
    "def {}(*args, **kwargs):\n    raise AssertionError('old markdown_visibility')\n\n\n".format(name)
    for name in ("analyze_markdown", "line_visible_text", "range_overlaps_protected",
                 "inline_protected_spans", "unicode_whitespace")
)
LOAD_DIFF_WORKER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('_diff_under_test', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "try:\n"
    "    spec.loader.exec_module(module)\n"
    "except ImportError as error:\n"
    "    print('ImportError', 'decode_source' in str(error))\n"
    "else:\n"
    "    print('loaded', module.diff('a\\n', 'b\\n')['status'])\n"
)


def run_diff_cp932(args, stdin=b""):
    """Windows の日本語環境と同じ標準入出力（cp932、surrogateescape）で diff を動かし、バイト列のまま返す。"""
    env = dict(os.environ, PYTHONIOENCODING="cp932:surrogateescape")
    env.pop("PYTHONUTF8", None)
    return subprocess.run([sys.executable, "-B", str(DIFF)] + [str(a) for a in args],
                          input=stdin, capture_output=True, env=env, timeout=30)


def run_diff_bytes_stdin(args, data):
    """標準入力にバイト列をそのまま渡す（BOM や UTF-8 でないバイト列のため）。"""
    return subprocess.run([sys.executable, "-B", str(DIFF)] + [str(a) for a in args],
                          input=data, capture_output=True, timeout=30)


class TestCliContract(DiffCase):
    """0.4、2.1、2.9、10.5 の CLI の約束（終了コード、誤りの文、--fail-on の値、標準入力、main(argv)）。"""

    def setUp(self):
        super().setUp()
        self.a_old = self.write("a.md", A_OLD)
        self.a_new = self.write("b.md", A_NEW)

    def test_fail_on_unknown_values_exit_2(self):
        for value, shown in (("warn", "warn"), ("nope", "nope"), ("", "（空）"), (" , ", "（空）")):
            with self.subTest(value=value):
                process = run_diff(["--fail-on=" + value, self.a_old, self.a_new])
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr, UNKNOWN_FAIL_ON.format(shown) + "\n")

    def test_fail_on_values_ignore_case_underscore_commas_and_repeats(self):
        """10.5 M5、2.9: 大文字と小文字、「_」と「-」を区別しない。何度でも、カンマ区切りでも受ける。"""
        for option in (["--fail-on=MEANING_RISK"], ["--fail-on", "Meaning_Risk"], ["--fail-on= meaning-risk "],
                       ["--fail-on=meaning-risk,meaning-risk"], ["--fail-on=meaning-risk", "--fail-on=meaning_risk"]):
            with self.subTest(option=option):
                process = run_diff(option + [self.a_old, self.a_new])
                self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertEqual(process.stdout, EXAMPLE_A + "\n\n" + FAIL_LINE_A + "\n")

    def test_unknown_stance_message(self):
        """空の値と空白だけの値は、--fail-on と同じく「（空）」と書く（反証レビュー F13・E12）。"""
        for option, shown in ((["--stance=不明"], "不明"), (["--stance", "不明"], "不明"), (["--stance="], "（空）"),
                              (["--stance", ""], "（空）"), (["--stance= "], "（空）")):
            with self.subTest(option=option):
                process = run_diff(option + [self.a_old, self.a_new])
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertEqual(process.stderr, UNKNOWN_STANCE.format(shown) + "\n")

    def test_stance_is_normalized_on_the_cli(self):
        """2.1: --stance の値は STANCES のキーで受け、CLI で3つの立場に正規化する（API の diff() は変換しない）。"""
        for value, stance in (("読み手に勧める", "勧め"), ("手順", "決まり"), ("体験", "説明"), ("説明", "説明")):
            with self.subTest(value=value):
                process = run_diff(["--json", "--stance", value, self.a_old, self.a_new])
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(json.loads(process.stdout)["endings"]["stance"], stance)

    def test_argparse_errors_end_with_a_japanese_hint(self):
        """10.5 M2: 使い方の行と argparse の英語の行のあとに日本語の案内を1行。終了コード2、標準出力は空。"""
        cases = (["--nope", self.a_old, self.a_new], ["--stance"], [self.a_old], [self.a_old, self.a_new, self.a_new],
                 ["-", "-"], ["--endings", self.a_old, self.a_new], ["--endings", self.a_old, "--json"],
                 ["--endings", self.a_old, "--fail-on=meaning-risk"], ["--endings"], [])
        for args in cases:
            with self.subTest(args=[str(arg) for arg in args]):
                process = run_diff(args)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertTrue(process.stderr.startswith("使い方: yomiyasu_diff.py"), process.stderr)
                lines = process.stderr.rstrip("\n").split("\n")
                self.assertIn("yomiyasu_diff.py: error: ", lines[-2])
                self.assertEqual(lines[-1], USAGE_HINT)
                self.assertNotIn("Traceback", process.stderr)

    def test_endings_mode_still_works(self):
        """--endings は1つのファイルの文末だけを見る（v1.1.2 と同じ出力。--stance も受ける）。"""
        path = self.write("e.md", "設定を開きます。値を変えてください。\n")
        for args in (["--endings", path], [path, "--endings"], ["--endings", "--stance", "説明", path]):
            with self.subTest(args=[str(arg) for arg in args]):
                process = run_diff(args)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertTrue(process.stdout.startswith("■ 文末の種類（表を除く）: "), process.stdout)

    def test_input_errors(self):
        """2.1 と 10.1 L11、10.5 M1・M3: 開けないファイル、UTF-8 でないファイルと標準入力、空のパス、標準入力がない。"""
        cp932 = self.write("cp932.md", "設定を変更します。\n".encode("cp932"))
        missing = self.root / "missing.md"
        with self.subTest(case="missing-first"):
            process = run_diff([missing, self.a_new])
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertEqual(process.stdout, "")
            match = OPEN_ERROR.match(process.stderr)
            self.assertIsNotNone(match, process.stderr)
            self.assertEqual(match.group("path"), str(missing))
        with self.subTest(case="missing-second"):
            process = run_diff([self.a_old, missing])
            self.assertEqual(process.returncode, 2)
            self.assertEqual(OPEN_ERROR.match(process.stderr).group("path"), str(missing))
        with self.subTest(case="empty-path"):
            process = run_diff(["", self.a_new])
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertEqual(OPEN_ERROR.match(process.stderr).group("path"), "")
        with self.subTest(case="not-utf8-file"):
            process = run_diff([self.a_old, cp932])
            self.assertEqual(process.returncode, 2)
            self.assertEqual(process.stdout, "")
            self.assertEqual(process.stderr, NOT_UTF8_FILE.format(cp932))
        with self.subTest(case="not-utf8-stdin"):
            process = run_diff_bytes_stdin(["-", self.a_new], "設定を変更します。\n".encode("cp932"))
            self.assertEqual(process.returncode, 2)
            self.assertEqual(process.stdout, b"")
            self.assertEqual(process.stderr.decode("utf-8"), NOT_UTF8_STDIN)
        with self.subTest(case="no-stdin"):
            process = subprocess.run(
                [sys.executable, "-B", "-c", NO_STDIN_WORKER, str(DIFF), "-", str(self.a_new)],
                stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            self.assertEqual(process.stdout, "")
            self.assertEqual(process.stderr, NO_STDIN)

    def test_stdin_with_bom_and_crlf(self):
        """2.2: CLI は読むときに BOM を外し改行を LF にして、違いを encoding_notes に出す（標準入力も同じ）。"""
        data = (BOM + A_OLD.replace("\n", "\r\n")).encode("utf-8")
        process = run_diff_bytes_stdin(["--json", "-", self.a_new], data)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout.decode("ascii"))
        self.assertEqual(result["full_diff"]["encoding_notes"],
                         [{"kind": "eol", "old": "crlf", "new": "lf"}, {"kind": "bom", "old": True, "new": False}])
        self.assertEqual(result["full_diff"]["hunks"], [EXAMPLE_A_HUNK])
        process = run_diff_bytes_stdin(["-", self.a_new], data)
        section = full_diff_section(process.stdout.decode("utf-8").rstrip("\n"))
        self.assertEqual(section[:3], ["■ 全文差分（変更 1か所。省略していません）",
                                       "- 改行コード: CRLF → LF（行ごとの差には出していません）", "- 先頭のBOM: あり → なし"])

    def test_internal_error_exits_3(self):
        process = subprocess.run(
            [sys.executable, "-B", "-c", INTERNAL_ERROR_WORKER, str(SCRIPTS), str(DIFF), str(self.a_old), str(self.a_new)],
            stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        self.assertIn("yomiyasu_diff.py: 内部エラー: RuntimeError: synthetic failure for the test", process.stderr)
        self.assertIn("Traceback", process.stderr)

    def test_mismatched_markdown_visibility_is_an_internal_error(self):
        """隣の markdown_visibility.py が古い版（decode_source がない）とき、スクリプトとしては終了コード3（1にしない）。
        モジュールとして読むときは ImportError のまま。"""
        partial = self.root / "partial"
        partial.mkdir()
        (partial / "yomiyasu_diff.py").write_bytes(DIFF.read_bytes())
        (partial / "markdown_visibility.py").write_bytes(OLD_VISIBILITY_STUB.encode("utf-8"))
        with self.subTest(case="script"):
            process = subprocess.run(
                [sys.executable, "-B", str(partial / "yomiyasu_diff.py"), "--fail-on=meaning-risk", str(self.a_old), str(self.a_new)],
                stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
            self.assertEqual(process.stdout, "")
            first_line = process.stderr.split("\n")[0]
            self.assertTrue(first_line.startswith("yomiyasu_diff.py: 内部エラー: ImportError: "), process.stderr)
            self.assertIn("decode_source", first_line)
        with self.subTest(case="module"):
            process = subprocess.run(
                [sys.executable, "-B", "-c", LOAD_DIFF_WORKER, str(partial / "yomiyasu_diff.py")],
                stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertEqual((process.returncode, process.stdout), (0, "ImportError True\n"), process.stderr)
        with self.subTest(case="sibling"):
            # 同じプロセスで古い版がすでに読まれていても、spec_from_file_location で読んだ diff は隣のファイルを使う
            old = self.root / "old"
            old.mkdir()
            (old / "markdown_visibility.py").write_bytes(OLD_VISIBILITY_STUB.encode("utf-8"))
            worker = "import sys\nsys.path.insert(0, sys.argv[2])\nimport markdown_visibility\nsys.argv = sys.argv[:2]\n" + LOAD_DIFF_WORKER
            process = subprocess.run(
                [sys.executable, "-B", "-c", worker, str(DIFF), str(old)],
                stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertEqual((process.returncode, process.stdout), (0, "loaded changed_without_candidates\n"), process.stderr)

    def test_missing_or_broken_markdown_visibility_is_an_internal_error(self):
        """反証レビュー regress 3: 隣に markdown_visibility.py がない、または読めない（構文の誤り）ときも、スクリプトとしては
        終了コード3（1は --fail-on に当たったときだけ）。モジュールとして読むときは ImportError。"""
        for case, content in (("missing", None), ("syntax-error", "def broken(:\n")):
            folder = self.root / case
            folder.mkdir()
            (folder / "yomiyasu_diff.py").write_bytes(DIFF.read_bytes())
            if content is not None:
                (folder / "markdown_visibility.py").write_bytes(content.encode("utf-8"))
            with self.subTest(case=case, run="script"):
                process = subprocess.run(
                    [sys.executable, "-B", str(folder / "yomiyasu_diff.py"), "--fail-on=meaning-risk",
                     str(self.a_old), str(self.a_new)],
                    stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                    cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                first_line = process.stderr.split("\n")[0]
                self.assertTrue(first_line.startswith("yomiyasu_diff.py: 内部エラー: ImportError: "), process.stderr)
                self.assertIn("markdown_visibility.py", first_line)
            with self.subTest(case=case, run="module"):
                process = subprocess.run(
                    [sys.executable, "-B", "-c", LOAD_DIFF_WORKER, str(folder / "yomiyasu_diff.py")],
                    stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                    cwd=str(self.root), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertTrue(process.stdout.startswith("ImportError"), process.stdout)

    def test_closed_output_pipe_exits_3_without_traceback(self):
        """10.5 M4: 読む側が先に閉じたときは、トレースバックを出さずに終了コード3。"""
        big = self.write("big.md", "重要なのは、テストを書くことです。\n" * 5000)
        for name, args in (("small", [self.a_old, self.a_new]), ("large", [self.a_old, big])):
            with self.subTest(size=name):
                process = subprocess.Popen([sys.executable, "-B", str(DIFF)] + [str(a) for a in args],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                process.stdout.close()
                process.stdout = None
                _, err = process.communicate(timeout=60)
                message = err.decode("utf-8")
                self.assertEqual(process.returncode, 3, message)
                self.assertIn(CLOSED_PIPE, message)
                self.assertNotIn("Traceback", message)

    def test_stderr_is_utf8_in_a_cp932_environment(self):
        """0.4: 標準入出力が cp932 の環境でも、標準エラーは UTF-8 で書く。JSON は ASCII だけ。"""
        process = run_diff_cp932(["--fail-on=なし🚀", self.a_old, self.a_new])
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(process.stdout, b"")
        self.assertEqual(process.stderr.decode("utf-8"), UNKNOWN_FAIL_ON.format("なし🚀") + "\n")
        process = run_diff_cp932(["--nope"])
        self.assertEqual(process.returncode, 2)
        self.assertTrue(process.stderr.decode("utf-8").startswith("使い方: yomiyasu_diff.py"))
        process = run_diff_cp932(["--json", self.a_old, self.a_new])
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(process.stdout.isascii())
        process = run_diff_cp932([self.a_old, self.a_new])
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.decode("utf-8").replace("\r\n", "\n"), EXAMPLE_A + "\n")

    def test_help_texts_and_exit_code_table(self):
        """2.1 と 2.9 のヘルプの文、最後に終了コードの表（0〜3）。終了コード0、標準エラーは空。"""
        env = dict(os.environ, COLUMNS="2000", NO_COLOR="1")
        env.pop("FORCE_COLOR", None)
        env.pop("PYTHON_COLORS", None)
        for option in ("-h", "--help"):
            with self.subTest(option=option):
                process = run_diff([option], env=env)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr, "")
                self.assertIn(DIFF_HELP_DESCRIPTION, process.stdout)
                self.assertIn(DIFF_HELP_FAIL_ON, process.stdout)
                self.assertTrue(process.stdout.startswith("使い方: yomiyasu_diff.py"), process.stdout)
                tail = process.stdout.rstrip("\n").split("\n")[-5:]
                self.assertEqual(tail[0], "終了コード:", process.stdout)
                for code, line in zip("0123", tail[1:]):
                    self.assertRegex(line, r"^  {}  \S".format(code))

    def call_main(self, argv, stdin_text=None, stdout=None, stderr=None):
        out = io.StringIO() if stdout is None else stdout
        err = io.StringIO() if stderr is None else stderr
        patches = [mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err)]
        if stdin_text is not None:
            patches.append(mock.patch.object(sys, "stdin", io.StringIO(stdin_text)))
        for patch in patches:
            patch.start()
        try:
            try:
                code = yomiyasu_diff.main(argv)
            except SystemExit as stop:
                code = stop.code
        finally:
            for patch in reversed(patches):
                patch.stop()
        return code, (out.getvalue() if out is not None else None), (err.getvalue() if err is not None else None)

    def test_main_returns_exit_codes(self):
        """2.1: main(argv=None) は終了コードを返す（CLI は sys.exit(main()) の形）。"""
        self.assertTrue(callable(getattr(yomiyasu_diff, "main", None)), "main がない")
        self.assertIn("argv", inspect.signature(yomiyasu_diff.main).parameters)
        self.assertEqual(self.call_main(["--version"]), (0, "yomiyasu_diff.py 2.3.0 (JSON format 2)\n", ""))
        self.assertEqual(self.call_main([str(self.a_old), str(self.a_new)]), (0, EXAMPLE_A + "\n", ""))
        self.assertEqual(self.call_main(["--fail-on=meaning-risk", str(self.a_old), str(self.a_new)]),
                         (1, EXAMPLE_A + "\n\n" + FAIL_LINE_A + "\n", ""))
        self.assertEqual(self.call_main(["--fail-on=nope", str(self.a_old), str(self.a_new)]),
                         (2, "", UNKNOWN_FAIL_ON.format("nope") + "\n"))
        code, out, err = self.call_main(["--json", "-", str(self.a_new)],
                                        stdin_text=BOM + A_OLD.replace("\n", "\r\n"))
        self.assertEqual((code, err), (0, ""))
        expected = yomiyasu_diff.diff(A_OLD, A_NEW, None, encoding_notes=[
            {"kind": "eol", "old": "crlf", "new": "lf"}, {"kind": "bom", "old": True, "new": False}])
        self.assertEqual(json.loads(out), json.loads(json.dumps(expected)))

    def test_missing_streams_keep_messages_off_the_other_stream(self):
        """標準エラーがないときの使い方の誤りは2で標準出力に書かない。標準出力がないときの -h は0で標準エラーに書かない。"""
        for argv in (["--nope"], ["--fail-on"], ["--fail-on=nope", str(self.a_old), str(self.a_new)]):
            with self.subTest(argv=argv, missing="stderr"):
                code, text, _ = self._call_without(argv, "stderr")
                self.assertEqual(code, 2)
                self.assertEqual(text, "")
        with self.subTest(argv=["-h"], missing="stdout"):
            code, _, err = self._call_without(["-h"], "stdout")
            self.assertEqual(code, 0)
            self.assertEqual(err, "")

    def _call_without(self, argv, missing):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", None if missing == "stdout" else out), \
                mock.patch.object(sys, "stderr", None if missing == "stderr" else err):
            try:
                code = yomiyasu_diff.main(argv)
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue()


if __name__ == "__main__":
    unittest.main()
