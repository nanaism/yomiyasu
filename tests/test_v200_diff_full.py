#!/usr/bin/env python3
"""v2.0.0: diff の全文差分、状態の3分け、レポートの形、引数、決定性、性能（DESIGN-interfaces.md 2章、6.3）。

v1.1.2 の diff() は9キーだけを返し、レポートは「（候補なし）」で終わるので、v2.0.0 の振る舞いを見る試験はすべて失敗する。
docstring に「（v1.1.2 でも通る後戻り防止）」と書いた試験は v1.1.2 でも通り、v2.0.0 で壊さないことを見張る。
文はすべてこのファイルで作った合成の文。コーパスの組は tests/corpus を読むだけで、書き換えない。
"""

from pathlib import Path
import json
import os
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

import yomiyasu_diff  # noqa: E402


NINE_KEYS = ["markers", "new_words", "lost_words", "structure", "spans", "logic", "bold", "endings", "type_changes"]
TOP_KEYS = (["format", "format_version", "tool_version", "status", "changed", "candidate_count", "meaning_risk_count",
             "not_judged", "meaning_risks"] + NINE_KEYS + ["full_diff"])
FIRST_LINE = "差分の検査を実行しました。"
DISCLAIMER = ("全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。"
              "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。")
NO_CANDIDATE_STATUS = "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更"
BOM = "\ufeff"  # 見えない文字なので、ソースには直接書かない
CHILD_TIMEOUT = 30  # 性能の試験の子プロセスの上限（秒）。遅い実装でも試験全体を止めない

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
    """標準入力を渡さないときは空にする（親の標準入力を受け継ぐと、誤って読む実装が端末でだけ timeout まで止まる）。"""
    feed = {"stdin": subprocess.DEVNULL} if stdin is None else {"input": stdin}
    return subprocess.run(
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


# 性能の試験で、測る処理だけを子プロセスで動かす。最大3回測り、最も速い値を返す（上限より速ければそこでやめる）。
CHILD_TIMER = r'''
import json
import sys
import time

sys.path.insert(0, sys.argv[1])
import yomiyasu_diff

with open(sys.argv[2], encoding="utf-8") as handle:
    task = json.load(handle)
pairs, limit = task["pairs"], task["limit"]


def full_rewrite():
    orig, rewrite = pairs[0]
    full = yomiyasu_diff.full_diff(orig, rewrite)
    # 9キーの分析（type_changes）は測らない（2.11の1）。空のリストを渡し、中で作らせない
    yomiyasu_diff.meaning_risks(orig, rewrite, full=full, type_changes=[])
    return None


def small_fix():
    orig, rewrite = pairs[0]
    return len(yomiyasu_diff.full_diff(orig, rewrite)["hunks"])


def corpus():
    for orig, rewrite in pairs:
        yomiyasu_diff.diff(orig, rewrite)
    return len(pairs)


run = {"full_rewrite": full_rewrite, "small_fix": small_fix, "corpus": corpus}[task["run"]]
best = value = None
for _ in range(3):
    started = time.perf_counter()
    value = run()
    elapsed = time.perf_counter() - started
    best = elapsed if best is None else min(best, elapsed)
    if best < limit:
        break
print(json.dumps({"best": best, "value": value}))
'''


SECTION_SENTENCES = ("第{n}節の{k}項では、設定の値を記録の表と照らします。", "担当者は{k}番目の結果を残し、会議で共有します。",
                     "古い値は消さずに、変えた理由を横に書き足します。", "止まった手順は、最初の段から{k}回目として進め直します。")
REWRITE_SENTENCES = ("{n}番目の節の{k}項で、記録した値を会議の前に読み直しました。", "変えた値の理由を短く添え、古い設定は外しています。",
                     "止まった手順は、はじめの段からもう一度進めました。", "確かめた人の名前と日付も{k}行目に足しています。")


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
            self.assertTrue(key in result, "v2.0.0 の diff() は %s を返す（DESIGN-interfaces.md 2.8）。今のキー: %s"
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
                        "v2.0.0 の yomiyasu_diff は %s() を公開する（DESIGN-interfaces.md 2.10）" % name)
        return getattr(yomiyasu_diff, name)

    def time_in_child(self, run, pairs, limit):
        """CHILD_TIMER の run を子プロセスで動かし、{"best": 秒, "value": 戻り値} を返す。
        時間は子の中で測る。CHILD_TIMEOUT 秒で終わらなければ失敗にする（同じプロセスで動かすと timeout が効かない）。"""
        task = self.write("timing-%s.json" % run, json.dumps({"run": run, "pairs": pairs, "limit": limit}, ensure_ascii=False))
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

    def test_example_b_report_has_no_diff_line(self):
        report = self.report(self.diff2(B_OLD, B_NEW))
        self.assertEqual(report, EXAMPLE_B)
        self.assertFalse([line for line in report.split("\n") if line.startswith("  差: ")])

    def test_example_c_report(self):
        self.assertEqual(self.report(self.diff2(C_OLD, C_NEW)), EXAMPLE_C)

    def test_pair3_diff_line(self):
        report = self.report(self.diff2(PAIR3_OLD, PAIR3_NEW))
        self.assertIn(PAIR3_DIFF_LINE, full_diff_section(report))


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
        self.assertEqual(result["not_judged"], ["meaning_equivalence", "reader_comprehension"])

    def test_example_a_full_diff(self):
        full = self.diff2(A_OLD, A_NEW)["full_diff"]
        self.assertEqual(full["hunks"], [EXAMPLE_A_HUNK])
        self.assertEqual(full["final_newline"], {"old": True, "new": True})
        # 渡さなかったときの値（[]、null、キーなし）は設計で決まっていない（questions-diff.md 13）。注記がないことだけを見る
        self.assertFalse(full.get("encoding_notes"), "API の diff() に encoding_notes を渡さなければ注記はない（2.8）")
        self.assertEqual(full["limits_applied"], [])

    def test_cli_json_is_the_api_result(self):
        process = run_diff(["--json", self.write("a.md", A_OLD), self.write("b.md", A_NEW)])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(process.stdout.isascii(), "--json は ASCII だけ（ensure_ascii=True）")
        from_cli = json.loads(process.stdout)
        from_api = json.loads(json.dumps(yomiyasu_diff.diff(A_OLD, A_NEW), ensure_ascii=True))
        self.assertEqual(list(from_cli), TOP_KEYS)
        # encoding_notes は CLI だけが渡す（2.8）。渡さないときの形が決まっていないので、両方から外して比べる。
        # 同じ改行コードで BOM のない2つのファイルなので、CLI の注記も空。注記の中身は test_cli_line_endings_or_bom_only が見る
        cli_notes = from_cli["full_diff"].pop("encoding_notes", None)
        from_api["full_diff"].pop("encoding_notes", None)
        self.assertFalse(cli_notes, "改行コードも BOM も同じなら注記はない")
        self.assertEqual(from_cli, from_api)


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
        self.assertIn("@ 元1行目を削除（本文、移した行。後4行目へ）", full_diff_section(self.report(result)))
        self.assert_complete(orig, rewrite, result["full_diff"])

    def test_final_newline_note(self):
        orig, rewrite = "最初の行です。\n最後の行です。\n", "最初の行です。\n最後の行を直しました。"
        result = self.diff2(orig, rewrite)
        self.assertEqual(result["full_diff"]["final_newline"], {"old": True, "new": False})
        self.assertIn("末尾の改行 あり → なし", "\n".join(full_diff_section(self.report(result))))
        self.assert_complete(orig, rewrite, result["full_diff"])


class TestBudget(DiffCase):
    """6.3 上限: 文字の対応にかける字数の予算（両側の合計200,000字）を超えても、完全さは保つ（2.3の4）。

    2.3の4は「文字の対応にかける字数」の数え方（行の全体か、前と後ろの同じ部分を外した残りか）を決めていない。
    どちらの数え方でも予算を超えるよう、各段落の最初の文と最後の文を書き換える。"""

    SENTENCES = ("第{n}節の{k}番目の記録では、値を表と照らして確かめる。", "担当者は{k}回目の結果を残し、翌週に共有する。",
                 "古い値は消さず、変えた理由を横に書く。")

    def test_budget_is_applied_and_completeness_is_kept(self):
        full_diff = self.need_function("full_diff")
        old_blocks, new_blocks, middle = [], [], 0
        for n in range(120):
            parts = sentences_of(1000, n, self.SENTENCES)
            old_paragraph = "".join(parts)
            new_paragraph = "".join([replace_once(parts[0], "確かめる", "確かめた")] + parts[1:-1]
                                    + [parts[-1][:-1] + "ことにした。"])
            middle += changed_middle(old_paragraph, new_paragraph)
            old_blocks.append("## 節%d\n%s" % (n, old_paragraph))
            new_blocks.append("## 節%d\n%s" % (n, new_paragraph))
        orig, rewrite = "\n".join(old_blocks) + "\n", "\n".join(new_blocks) + "\n"
        self.assertGreater(len(orig) + len(rewrite), 200000)
        self.assertGreater(middle, 200000, "前と後ろの同じ部分を外して数えても予算を超える")
        full = full_diff(orig, rewrite)
        self.assertEqual(len(full["hunks"]), 120)
        omitted = [hunk for hunk in full["hunks"] if hunk["segments_omitted"] == "budget"]
        self.assertTrue(omitted, "予算を超えた hunk は segments_omitted が budget")
        for hunk in omitted:
            self.assertIsNone(hunk["segments"])
        self.assert_complete(orig, rewrite, full)


class TestExistingKeys(DiffCase):
    """6.3 既存の9キー: v1.1.2 で作った合成20組（BOM なし）の9キーと同じ（v1.1.2 でも通る後戻り防止）。"""

    def test_nine_keys_match_v112_fixture(self):
        """合成20組の9キーが v1.1.2 の fixture と同じ（v1.1.2 でも通る後戻り防止）。"""
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(data["keys"], NINE_KEYS)
        self.assertEqual(len(data["cases"]), 20)
        for case in data["cases"]:
            with self.subTest(case=case["id"]):
                self.assertNotIn(BOM, case["orig"] + case["rewrite"])
                result = yomiyasu_diff.diff(case["orig"], case["rewrite"], case["stance"])
                self.assertEqual([key for key in result if key in NINE_KEYS], NINE_KEYS, "9キーの間の順を保つ（2.8）")
                actual = json.loads(json.dumps({key: result[key] for key in NINE_KEYS}, ensure_ascii=False))
                self.assertEqual(actual, case["expected"])


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

    測る処理は子プロセスで動かし（CHILD_TIMEOUT 秒で打ち切る）、最大3回のうち最も速い値を上限と比べる。"""

    def test_full_rewrite_of_60000_chars(self):
        """6万字の全面書き換えで full_diff() と meaning_risks() の合計が3秒未満。
        9キーの分析（type_changes）は測らない（2.11の1）。meaning_risks() には type_changes=[] を渡す。"""
        self.need_function("full_diff")
        self.need_function("meaning_risks")
        orig, count = long_document(SECTION_SENTENCES)
        rewrite, _ = long_document(REWRITE_SENTENCES, paragraphs=count)
        self.assertGreaterEqual(len(orig), 60000)
        self.assertGreaterEqual(len(rewrite), 60000)
        timing = self.time_in_child("full_rewrite", [[orig, rewrite]], 3.0)
        self.assertLess(timing["best"], 3.0, "6万字の全面書き換えで full_diff() と meaning_risks() の合計が3秒未満")

    def test_small_fix_in_60000_chars(self):
        self.need_function("full_diff")
        orig, _ = long_document(SECTION_SENTENCES)
        middle = orig.index("第200節の")
        rewrite = orig[:middle] + "第201節の" + orig[middle + len("第200節の"):]
        self.assertEqual(len(rewrite), len(orig))
        timing = self.time_in_child("small_fix", [[orig, rewrite]], 0.5)
        self.assertLess(timing["best"], 0.5, "6万字の小さな修正で full_diff() が0.5秒未満")
        self.assertEqual(timing["value"], 1, "hunk は1つ")

    def test_corpus_48_pairs_diff_total_under_one_second(self):
        """コーパス48組の diff() 合計が1秒未満（v1.1.2 でも通る後戻り防止）。"""
        pairs = [[read_exact(source), read_exact(rewritten)] for source, rewritten in corpus_pairs()]
        self.assertEqual(len(pairs), 48)
        timing = self.time_in_child("corpus", pairs, 1.0)
        self.assertEqual(timing["value"], 48)
        self.assertLess(timing["best"], 1.0)


if __name__ == "__main__":
    unittest.main()
