#!/usr/bin/env python3
"""v2.0.0（G7）: lint、diff、check run の文書の種類（--doc-type）と読者（--reader）。

期待値は種類と読者の設計の9章（道具のオプション）と 10.1 の表（A〜E）、末尾の追記（2026-10-13 19時。種類に
formal を足して9つにする。lint で外す規則はなし）と、diff の詰めで足した promo（10個目。lint で emoji_prohibited を外す。
2026-10-14 朝の作者の判断で fragment_run も外す）から取った。文はすべてこのファイルで作った合成の文。コーパスは読むだけ。

- 指定しないときの出力（9章の不変の条件、10.1 の A）は、tests/fixtures/g7_unchanged_outputs.json と照らす。
  lint、diff、check の人が読む出力、終了コード、標準エラー、check の状態の行（と、context を除いた JSON）を、コーパスの
  全ファイルと全組で比べる。fixture の行は出どころが違う（fixture の generated_by、source_commit、source_sha256 の
  lint、diff、check）。
  - lint の行は G7 を入れる前の作業ツリー（45a5885 に check の固めを入れたもの）の出力で、作り直していない。
    指定しないときの lint の出力が G7 の前と1字も違わないことを見る。
  - diff と check の行は、diff の詰め（文体の硬化、勢い、否定対比の逆転、気持ちの語の検査と、意味が変わる恐れの判定の詰め）
    とその直し（反証で見つけた例の直しを3回）のあとの出力で作り直したもので、G7 の前の出力とは違う。そのあとの変更で出力が
    変わらないことを見る。G7 の前からの変化（足した節とキー、判定が変わった組、--fail-on の終了コードが変わった組と理由）は
    fixture の updates に書いた。
  lint、diff、check の出力をわざと変えたときは、fixture の generated_by に書いた作り方（このファイルの unchanged_diff() と
  unchanged_check() の値で diff と check の行を作り直し、lint の行は作り直さず、unchanged_lint() と1字も違わないことを
  確かめる）で作り直し、作り直した理由と、終了コードが変わった組を updates と報告に書く（条件をゆるめて通さない）。
  fixture の説明の欄（description、generated_by、source_commit、updates）には、手元の記録と道具の名前を書かない
  （test_v200_fix_round3.PrivatePathTest が見張る）。
- SkillFilesTest（10.1 の C3、C4 と C5 の SKILL.md の部分）は、SKILL.md と references を入れる段までは失敗する。
"""

from pathlib import Path
from unittest import mock
import copy
import contextlib
import hashlib
import inspect
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CORPUS = ROOT / "tests" / "corpus"
FIXTURES = ROOT / "tests" / "fixtures"
UNCHANGED = FIXTURES / "g7_unchanged_outputs.json"
PACKAGE = ROOT / "skills" / "yomiyasu"
sys.path.insert(0, str(SCRIPTS))

import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402
import yomiyasu_diff  # noqa: E402
import yomiyasu_check  # noqa: E402


# ---- 9.1 と追記: 値、名前、外す規則 ----

# 既存10種類の互換性と references の試験はこの集合を維持する。mail/paper は test_v200_mail_paper.py。
# diff の詰め（目標の D-5、勢いの文書2章）: promo（紹介記事・宣伝文）を足して10にした
DOC_TYPE_VALUES = ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal", "promo")
DOC_TYPE_NAMES = {"pr": "PR説明", "article": "技術記事", "incident": "障害報告", "proposal": "提案書", "minutes": "議事録",
                  "manual": "マニュアル", "slides": "スライド", "essay": "エッセイ・小説",
                  "formal": "公用文、規程、契約書、仕様書", "promo": "紹介記事・宣伝文"}
DOC_TYPE_DOMAINS = {"pr": ("business.md",), "article": ("tech.md",), "incident": ("business.md",),
                    "proposal": ("business.md",), "minutes": ("business.md",), "manual": ("tech.md", "business.md"),
                    "slides": ("tech.md", "business.md"), "essay": ("essay.md",), "formal": ("business.md", "tech.md"),
                    "promo": ("essay.md", "business.md")}
READER_VALUES = ("expert", "informed", "general")
READER_NAMES = {"expert": "同じ分野の専門家", "informed": "分野は違うが技術に詳しい人", "general": "専門知識のない人"}
SKIP_RULES = {
    "pr": ("excess_list",),
    "article": (),
    "incident": ("excess_list",),
    "proposal": (),
    "minutes": ("bold_label_list", "excess_list", "sentence_end_repetition"),
    "manual": ("excess_list",),
    "slides": ("bold_label_list", "count_declaration", "excess_list", "short_summary_heading"),
    "essay": (),
    "formal": (),
    # D-5: promo では書き手の絵文字を残す（勢いの検査は絵文字が減ると候補にするので、lint の絵文字の候補と食い違わせない）。
    # diff の詰めで測って決めた。fragment_run（「安い。うまい。早い。」の型）も
    # 外す（作者の判断、2026-10-14 朝。紹介記事・宣伝文では評価の語を短く重ねる型も勢いとして残す）
    "promo": ("emoji_prohibited", "fragment_run"),
}
# 5.3「外さない規則と理由」。どの種類でも外さない。ただし fragment_run は promo だけ外す（作者の判断、2026-10-14 朝。
# 5.3 の理由はスライドの話で、紹介記事・宣伝文では評価の語を短く重ねる型を勢いとして残すと決めた）
NEVER_SKIPPED_EXCEPT = {"fragment_run": ("promo",)}
NEVER_SKIPPED = ("bold_not_rendered", "fragment_run", "meta_intro", "metaphor_verb", "trailing_colon", "excess_bold",
                 "dash_list_ending", "dash_insertion", "dash_decoration")

NEW_DOC_TYPES = (("mail", "メール・チャット", ("business.md",)), ("paper", "論文・研究レポート", ("tech.md",)))
NEW_SKIP_RULES = {"mail": ("emoji_prohibited",), "paper": ()}
DOC_TYPE_CHOICES = "、".join("{}（{}）".format(value, DOC_TYPE_NAMES[value]) for value in DOC_TYPE_VALUES) + "、" + "、".join("{}（{}）".format(row[0], row[1]) for row in NEW_DOC_TYPES)
READER_CHOICES = "、".join("{}（{}）".format(value, READER_NAMES[value]) for value in READER_VALUES)
# 9.1 の文どおり、値の一覧の閉じ括弧と「です」の間に空白を入れない（反証レビュー spec 6）
DOC_TYPE_ERROR = "--doc-type に使えない値です: {}。使えるのは " + DOC_TYPE_CHOICES + "です。"
READER_ERROR = "--reader に使えない値です: {}。使えるのは " + READER_CHOICES + "です。"
# 9.1: diff で --endings と一緒に付けたとき（--endings と --json の組と同じ形の使い方の誤り）
ENDINGS_ERROR = "yomiyasu_diff.py: error: --endings は --doc-type と --reader に対応していません"

# 9.6 ヘルプの文（formal と promo を足した値の並び）
LINT_DOC_TYPE_HELP = ("文書の種類。指定すると、その種類で普通な書き方を候補にする規則（下の一覧）の候補を外し、外した件数を出します。"
                      "外した候補の中身は、指定せずに実行すると見られます。省くと、すべての規則を当てます（今までどおり）。"
                      "値: " + DOC_TYPE_CHOICES + "。")
LINT_READER_HELP = "想定する読者の知識。表示と JSON に残すだけで、候補は変えません。値: " + READER_CHOICES + "。"
LINT_HELP_LIST = "\n".join([
    "文書の種類ごとに外す規則（--doc-type）:",
    "  pr        excess_list",
    "  article   なし",
    "  incident  excess_list",
    "  proposal  なし",
    "  minutes   bold_label_list、excess_list、sentence_end_repetition",
    "  manual    excess_list",
    "  slides    bold_label_list、count_declaration、excess_list、short_summary_heading",
    "  essay     なし",
    "  formal    なし",
    "  promo     emoji_prohibited、fragment_run",
    "  mail      emoji_prohibited",
    "  paper     なし",
    "mail は meta_filler の返信・結びの5型だけも外します（ご質問ありがとうございます、必要なら次に〜します、いかがでしたでしょうか、ぜひ〜してみてください、参考になれば幸いです等）。宛名・挨拶・署名を削る専用規則はありません。paper は慎重表現を削る規則がないため除外なし。",
    "外した候補は、見直し候補の件数と --strict、--fail-on の判定に入れません。",
])
# diff の詰め: 文体の硬化の検査と勢いの検査は、種類で参考（info）にするかが決まるので、その文を足した。diff の詰めの直し
# で、硬化の参考に incident を足し、promo 以外の種類で勢いの絵文字と見出しを参考にした文を足した
# 1回目の反証の直し（反証で見つけた例）: 変わらないものを「規則の見直し候補」に絞り、
# minutes の見出しと promo の見出しの数え方を書いた
_DETECTOR_HELP = ("文体の硬化の検査は incident、formal、paper のとき、勢いの検査は pr、article、incident、manual、formal、paper のとき、"
                  "候補を参考として出します。promo と mail 以外の種類を指定すると、勢いの検査の絵文字の候補も参考として出し、"
                  "promo、minutes、mail 以外では見出しの候補も参考として出します。promo では、番号つき項目の行と太字だけの行も"
                  "勢いの検査の見出しに数えます。")
# 2回目の反証の直し（反証で見つけた例）: 種類で硬化と勢いの level と promo の見出しの数え方が
# 変わるので、冒頭の「残すだけで」を「残し、」にした
DIFF_DOC_TYPE_HELP = ("文書の種類（値は yomiyasu_lint.py と同じ）。表示と JSON に残し、差分、意味が変わる恐れ、規則の見直し候補、"
                      "--fail-on は変わりません（意味の検査はどの種類でも同じに行います）。" + _DETECTOR_HELP + "mail だけ敬語の度合いを検査します。値: " + DOC_TYPE_CHOICES + "。")
DIFF_READER_HELP = "想定する読者の知識（値は yomiyasu_lint.py と同じ）。表示と JSON に残すだけで、判定は変わりません。"
# diff の詰めの直し（反証で見つけた例）: diff と同じ、硬化と勢いを参考にする種類の文を足した
CHECK_DOC_TYPE_HELP = ("文書の種類。lint と diff に渡し、記録と状態の行に残します。lint は、その種類で普通な書き方を候補にする規則を"
                       "外します（yomiyasu_lint.py -h の一覧）。差分（意味が変わる恐れと規則の見直し候補）と資料との照合の判定は"
                       "変わりません。" + _DETECTOR_HELP + "mail だけ敬語の度合いを検査します。値: " + DOC_TYPE_CHOICES + "。")
CHECK_READER_HELP = "想定する読者の知識。lint と diff に渡し、記録と状態の行に残します。判定は変わりません。"

# 9.3 と 9.4 の1行
LINT_NO_SKIP = "この種類で外す規則はありません。"
LINT_READER_NOTE = "読者では候補を変えていません。"
DIFF_CONTEXT_TAIL = "差分と意味が変わる恐れは、種類と読者によらず同じ規則で出しています。"
LINT_HEADER = [
    "表現・書式の検査を実行しました。",
    "見直し候補: {}件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
]

# ---- 合成の文: 外す規則ごとに、その規則だけに当たる文書（10.1 の B2、B4、B5）----

EXCESS_LIST_ONLY = ("今週の作業の記録を残します。担当者は各自の作業を確認してから、来週の予定を決めてください。\n\n"
                    + "".join("- 第{}工程の部品を棚から出して、検品の台に並べた上で数を数える。\n".format(number)
                              for number in range(1, 10)))
SENTENCE_END_ONLY = "今日は雨です。明日は晴れです。週末は曇りです。\n"
BOLD_LABEL_ONLY = "- **日時**: 10月1日\n- **場所**: 本社3階\n- **担当**: 田中\n"
COUNT_DECLARATION_ONLY = "ポイントは3つです。順に説明します。\n"
SUMMARY_HEADING_ONLY = "# 報告\n\n作業は終わりました。\n\n## まとめ\n\n作業は予定どおり終わりました。\n"
BOLD_ERROR_ONLY = "これは**「重要」**です。\n"
EMOJI_ONLY = "新作のケーキが並びました\U0001F370\n"
FRAGMENT_RUN_ONLY = "安い。うまい。早い。\n"
RULE_SAMPLES = {
    "emoji_prohibited": EMOJI_ONLY,
    "fragment_run": FRAGMENT_RUN_ONLY,
    "excess_list": EXCESS_LIST_ONLY,
    "sentence_end_repetition": SENTENCE_END_ONLY,
    "bold_label_list": BOLD_LABEL_ONLY,
    "count_declaration": COUNT_DECLARATION_ONLY,
    "short_summary_heading": SUMMARY_HEADING_ONLY,
}
# スライドの例: bold_label_list と short_summary_heading（外す）と、emoji_prohibited（外さない warn）に当たる
SLIDES_SAMPLE = ("# 新しい検索の仕組み\n\n- **対象**: 社内の文書\n- **期間**: 10月から\n- **担当**: 検索チーム\n\n"
                 "## まとめ\n\n検索が速くなります\U0001F600\n")
SLIDES_LINE = ("文書の種類: スライド（slides）、読者: 指定なし。種類に合わせて外した候補 2件（bold_label_list 1件、"
               "count_declaration 0件、excess_list 0件、short_summary_heading 1件）。")

# 指示書2.2の3組（合成の文）
PAIRS_22 = (("田中が佐藤を承認した。\n", "佐藤が田中を承認した。\n"),
            ("保存期間は3日です。\n", "保存期間は30日です。\n"),
            ("データを保存します。\n", "データを保存しません。\n"))
STATUS_LINE = re.compile(r"^yomiyasu-check: ([a-z_]+)((?: [a-z_]+=\S+)*)$")


# ---- 補助 ----

def call(main, argv, stdin=None):
    """main(argv) をプロセスの中で動かし、(終了コード, 標準出力, 標準エラー) を返す。stdin はバイト列。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "stdout", out))
        stack.enter_context(mock.patch.object(sys, "stderr", err))
        if stdin is not None:
            stack.enter_context(mock.patch.object(
                sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")))
        try:
            code = main([str(item) for item in argv])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


def corpus_files():
    """tests/corpus の .md（コーパスのフォルダからの相対パス、/ 区切り）。"""
    return sorted(path.relative_to(CORPUS).as_posix() for path in CORPUS.rglob("*.md"))


def corpus_pairs():
    """diff の組（tools/existing_keys_check.py と同じ136組）。推敲の48組が先。"""
    pairs = []
    for name in sorted(os.listdir(str(CORPUS / "yomiyasu_rewritten"))):
        source = ("blacklist_ai", name[:-6] + ".md") if name.endswith("_bl.md") else ("raw_ai", name)
        pairs.append(("/".join(source), "yomiyasu_rewritten/" + name))
    for folder in ("edge_cases", "human", "raw_ai"):
        names = sorted(os.listdir(str(CORPUS / folder)))
        pairs.extend((folder + "/" + a, folder + "/" + b) for a, b in zip(names, names[1:]))
    return pairs


def _fixture_tool_version():
    """fixture を作ったときの版（目標の D-3 で版の文字列を 2.0.0-beta に変えたので、比べるときに読み替える）。"""
    path = FIXTURES / "g7_unchanged_outputs.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("tool_version")
    except (OSError, ValueError):
        return None


def _digest(*parts):
    """出力をつないだものの SHA-256 の先頭16字。今の版の文字列は、fixture を作ったときの版に読み替えてから数える
    （版の文字列を変えただけで、G7 の不変の条件の試験が落ちないように。出力のほかの字はそのまま比べる）。"""
    data = "\x00".join(str(part) for part in parts)
    current, recorded = yomiyasu_lint.__version__, _fixture_tool_version()
    if recorded and current != recorded:
        data = data.replace(current, recorded)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


def _masked(text, state):
    """check の出力から、一時の状態フォルダのパスと実行IDを伏せる（パスの区切りは / にそろえる）。"""
    if state is not None:
        for spelling in sorted(set((state, os.path.realpath(state))), key=len, reverse=True):
            text = text.replace(spelling, "<STATE>")
        text = re.sub(r"<STATE>[^\s\"」）]*", lambda match: match.group(0).replace("\\", "/"), text)
    return _RUN_ID.sub("<RUN>", text)


def _masked_value(value, state):
    if isinstance(value, str):
        return _masked(value, state)
    if isinstance(value, list):
        return [_masked_value(item, state) for item in value]
    if isinstance(value, dict):
        return dict((key, _masked_value(item, state)) for key, item in value.items())
    return value


def _without_context(text, indent):
    """JSON の文字列から context のキーを除き、同じ形で書き直す（G7 の前の JSON と比べるため）。"""
    value = json.loads(text)
    value.pop("context", None)
    return json.dumps(value, ensure_ascii=True, indent=indent)


def _stdin_form(source, final):
    return (b"<<<yomiyasu:original>>>\n" + source + (b"" if source.endswith(b"\n") else b"\n")
            + b"<<<yomiyasu:final>>>\n" + final)


def unchanged_lint():
    """lint（と diff --endings）の出力の要約。キーはコーパスの相対パス。"""
    rows = {}
    for relative in corpus_files():
        path = str(CORPUS / relative)
        data = (CORPUS / relative).read_bytes()
        row = {}
        for name, argv in (("plain", [path]), ("strict", ["--strict", path]), ("fail_error", ["--fail-on", "error", path])):
            row[name] = _digest(*call(yomiyasu_lint.main, argv))
        code, out, err = call(yomiyasu_lint.main, ["--json", path])
        row["json"] = _digest(code, _without_context(out, 2), err)
        row["stdin"] = _digest(*call(yomiyasu_lint.main, [], stdin=data))
        row["diff_endings"] = _digest(*call(yomiyasu_diff.main, ["--endings", path]))
        rows[relative] = row
    return rows


def unchanged_diff():
    """diff の出力の要約。キーは「元|後」。"""
    rows = {}
    for a, b in corpus_pairs():
        old, new = str(CORPUS / a), str(CORPUS / b)
        row = {}
        for name, argv in (("plain", [old, new]), ("stance", ["--stance", "説明", old, new]),
                           ("fail_on", ["--fail-on", "meaning-risk", old, new])):
            row[name] = _digest(*call(yomiyasu_diff.main, argv))
        code, out, err = call(yomiyasu_diff.main, ["--json", old, new])
        row["json"] = _digest(code, _without_context(out, 1), err)
        row["stdin"] = _digest(*call(yomiyasu_diff.main, ["-", new], stdin=(CORPUS / a).read_bytes()))
        rows[a + "|" + b] = row
    return rows


def _check_row(argv, state=None, stdin=None):
    code, out, err = call(yomiyasu_check.main, argv + (["--state-dir", state] if state is not None else []), stdin)
    return _digest(code, _masked(out, state), _masked(err, state))


def unchanged_check():
    """check の出力の要約。キーは「元|後」。全組で run と verify、推敲の48組ではほかの使い方も。"""
    rows = {}
    pairs = corpus_pairs()
    rewritten = set(pair for pair in pairs if pair[1].startswith("yomiyasu_rewritten/"))
    for a, b in pairs:
        old, new = str(CORPUS / a), str(CORPUS / b)
        row = {}
        with tempfile.TemporaryDirectory(prefix="yomiyasu-g7-") as state:
            row["run"] = _check_row(["run", "--source", old, "--final", new], state)
            row["verify"] = _check_row(["verify", "--final", new], state)
            if (a, b) in rewritten:
                row["replay"] = _check_row(["verify", "--final", new, "--replay"], state)
                row["rerun"] = _check_row(["run", "--source", old, "--final", new], state)
        if (a, b) in rewritten:
            data_a, data_b = (CORPUS / a).read_bytes(), (CORPUS / b).read_bytes()
            for name, argv, stdin in (
                    ("compose", ["run", "--material", old, "--final", new], None),
                    ("stdin", ["run", "--stdin"], _stdin_form(data_a, data_b)),
                    ("fail_on", ["run", "--fail-on", "meaning-risk,warn", "--source", old, "--final", new], None)):
                with tempfile.TemporaryDirectory(prefix="yomiyasu-g7-") as state:
                    row[name] = _check_row(argv, state, stdin)
            row["no_record"] = _check_row(["run", "--no-record", "--source", old, "--final", new])
            with tempfile.TemporaryDirectory(prefix="yomiyasu-g7-") as state:
                code, out, err = call(yomiyasu_check.main, ["run", "--json", "--source", old, "--final", new,
                                                            "--state-dir", state])
                value = json.loads(out)
                value.pop("context", None)
                for key in ("lint", "diff"):
                    if isinstance(value.get(key), dict):
                        value[key].pop("context", None)
                row["json"] = _digest(code, json.dumps(_masked_value(value, state), ensure_ascii=True, indent=1),
                                      _masked(err, state))
        rows[a + "|" + b] = row
    return rows


class DocTypeCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-doc-type-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.state = self.root / ".yomiyasu"

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def lint(self, *argv, stdin=None):
        return call(yomiyasu_lint.main, argv, stdin)

    def diff(self, *argv, stdin=None):
        return call(yomiyasu_diff.main, argv, stdin)

    def check(self, *argv, stdin=None):
        """check を状態フォルダ self.state で動かす（ホームやリポジトリに書かない）。"""
        return call(yomiyasu_check.main, list(argv) + ["--state-dir", self.state], stdin)

    def status_fields(self, line):
        match = STATUS_LINE.match(line)
        self.assertIsNotNone(match, line)
        return match.group(1), [part.split("=", 1) for part in match.group(2).split()]

    def record(self, lines):
        self.assertTrue(lines[4].startswith("記録: "), lines[:5])
        path = Path(lines[4][len("記録: "):])
        return path, json.loads(path.read_text(encoding="utf-8"))


# ---- A. 指定しないときは変わらない ----

class UnchangedOutputTest(unittest.TestCase):
    """9章の不変の条件: 指定しないときの lint、diff、check の人が読む出力、終了コード、状態の行が fixture と1字も違わない。
    lint は G7 の前の出力と、diff と check は diff の詰めとその直しのあとの出力と照らす（このファイルの冒頭の説明と、
    fixture の description、updates）。"""

    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(UNCHANGED.read_text(encoding="utf-8"))

    def compare(self, name, current):
        expected = self.fixture[name]
        self.assertEqual(sorted(current), sorted(expected), "{} の対象が fixture と違う".format(name))
        changed = ["{} {}".format(key, variant) for key in sorted(expected) for variant in sorted(expected[key])
                   if current[key].get(variant) != expected[key][variant]]
        self.assertEqual(changed, [], "{} の出力が fixture と違う（行の出どころは fixture の source_commit）".format(name))

    def test_fixture_covers_the_whole_corpus(self):
        self.assertEqual(len(corpus_files()), 163)
        self.assertEqual(len(corpus_pairs()), 136)
        self.assertEqual(sorted(self.fixture["lint"]), corpus_files())
        self.assertEqual(sorted(self.fixture["diff"]), sorted(a + "|" + b for a, b in corpus_pairs()))

    def test_lint_outputs_match_before_g7(self):
        """lint の行は G7 の前（45a5885 の作業ツリー）の出力のまま。"""
        self.compare("lint", unchanged_lint())

    def test_diff_outputs_match_before_g7(self):
        """名前は G7 の前と照らしていたときのまま。diff の行は diff の詰めとその直しのあとの出力（fixture の source_commit）。"""
        self.compare("diff", unchanged_diff())

    def test_check_outputs_match_before_g7(self):
        """名前は G7 の前と照らしていたときのまま。check の行は diff の詰めとその直しのあとの出力（fixture の source_commit）。"""
        self.compare("check", unchanged_check())


class DefaultsTest(DocTypeCase):
    def test_a1_lint_text_without_options_is_the_same(self):
        """A1: lint_text(t) と lint_text(t, doc_type=None, reader=None) が同じ。人が読む出力に「文書の種類:」の行がない。"""
        texts = [(CORPUS / relative).read_text(encoding="utf-8") for relative in corpus_files()]
        texts += [case["text"] for case in json.loads((FIXTURES / "bold_regressions.json").read_text(encoding="utf-8"))]
        for text in texts:
            plain = yomiyasu_lint.lint_text(text)
            given = yomiyasu_lint.lint_text(text, doc_type=None, reader=None)
            self.assertEqual(plain, given)
            self.assertNotIn("文書の種類:", yomiyasu_lint.render_report(plain))

    def test_a2_lint_context_is_null_without_options(self):
        """A2: JSON の context は値なしで、not_judged の次、metrics の前。"""
        result = yomiyasu_lint.lint_text(SLIDES_SAMPLE)
        self.assertEqual(result["context"], {"doc_type": None, "reader": None, "skipped_by_doc_type": {}})
        keys = list(result)
        self.assertEqual(keys[keys.index("not_judged") + 1], "context")
        self.assertEqual(keys[keys.index("context") + 1], "metrics")
        code, out, err = self.lint("--json", stdin=SLIDES_SAMPLE.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["context"], {"doc_type": None, "reader": None, "skipped_by_doc_type": {}})

    def test_a3_diff_context_is_null_without_options(self):
        """A3: diff の context は null の2つで、not_judged の次、meaning_risks の前。レポートに「文書の種類:」の行がない。"""
        result = yomiyasu_diff.diff(*PAIRS_22[1])
        self.assertEqual(result["context"], {"doc_type": None, "reader": None})
        keys = list(result)
        self.assertEqual(keys[keys.index("not_judged") + 1], "context")
        self.assertEqual(keys[keys.index("context") + 1], "meaning_risks")
        self.assertNotIn("文書の種類:", yomiyasu_diff.report(result))

    def test_a4_check_without_options(self):
        """A4: 記録の options.doc_type と options.reader は null で、状態の行に doc_type= と reader= がない。
        run と verify の JSON の context は mode の次。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", PAIRS_22[1][1])
        code, out, err = self.check("run", "--source", a, "--final", b)
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        self.assertNotIn("doc_type=", lines[1])
        self.assertNotIn("reader=", lines[1])
        _, record = self.record(lines)
        self.assertEqual(list(record["options"]), ["stance", "fail_on", "timeout", "doc_type", "reader"])
        self.assertEqual((record["options"]["doc_type"], record["options"]["reader"]), (None, None))
        self.assertEqual(lines[2].split("、")[0], "実行した検査: lint（最終稿）候補0件")
        for argv in (("run", "--source", a, "--final", b), ("verify", "--final", b)):
            code, out, err = self.check(*(argv + ("--json",)))
            result = json.loads(out)
            keys = list(result)
            self.assertEqual(keys[keys.index("mode") + 1], "context", argv[0])
            self.assertEqual(result["context"], {"doc_type": None, "reader": None}, argv[0])
            self.assertNotIn("doc_type=", result["status_line"])


# ---- B. lint の種類ごとの外し方 ----

class LintSkipTest(DocTypeCase):
    def test_b1_findings_with_a_type_are_the_plain_findings_minus_the_table(self):
        """B1: コーパスの全ファイルと10の種類で、種類つきの候補は、種類なしの候補から表の規則を除いたもの（順も同じ）。"""
        for relative in corpus_files():
            text = (CORPUS / relative).read_text(encoding="utf-8")
            plain = yomiyasu_lint.lint_text(text)["findings"]
            for value in DOC_TYPE_VALUES:
                result = yomiyasu_lint.lint_text(text, doc_type=value)
                kept = [finding for finding in plain if finding["rule"] not in SKIP_RULES[value]]
                self.assertEqual(result["findings"], kept, (relative, value))
                skipped = result["context"]["skipped_by_doc_type"]
                self.assertEqual(list(skipped), list(SKIP_RULES[value]), (relative, value))
                self.assertEqual(sum(skipped.values()), len(plain) - len(kept), (relative, value))
                for rule, count in skipped.items():
                    self.assertEqual(count, sum(1 for finding in plain if finding["rule"] == rule), (relative, rule))

    def test_b2_each_skipped_rule_is_real_and_skipped_only_for_its_types(self):
        """B2: 外す規則ごとに、その規則だけに当たる文書で、種類なしでは出て、外す種類では出ず、外さない種類では出る。"""
        rules = sorted(set(rule for value in DOC_TYPE_VALUES for rule in SKIP_RULES[value]))
        self.assertEqual(sorted(RULE_SAMPLES), rules)
        for rule, text in RULE_SAMPLES.items():
            plain = yomiyasu_lint.lint_text(text)["findings"]
            self.assertEqual([finding["rule"] for finding in plain], [rule], rule)
            for value in DOC_TYPE_VALUES:
                found = [finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type=value)["findings"]]
                self.assertEqual(found, [] if rule in SKIP_RULES[value] else [rule], (rule, value))

    def test_b3_counts_and_scores_come_from_the_kept_findings(self):
        """B3: 外したあとの counts、candidate_count、no_rule_findings、rule_penalty_score は、残った候補から計算した値。
        metrics は変えない。"""
        for text in list(RULE_SAMPLES.values()) + [SLIDES_SAMPLE, EXCESS_LIST_ONLY + BOLD_ERROR_ONLY]:
            plain = yomiyasu_lint.lint_text(text)
            for value in DOC_TYPE_VALUES:
                result = yomiyasu_lint.lint_text(text, doc_type=value)
                findings = result["findings"]
                counts = {"error": 0, "warn": 0, "info": 0}
                for finding in findings:
                    counts[finding["severity"]] += 1
                self.assertEqual(result["counts"], counts, value)
                self.assertEqual(result["candidate_count"], len(findings), value)
                self.assertEqual(result["no_rule_findings"], not findings, value)
                penalty = sum(5 if finding["severity"] in ("warn", "error") else 2 for finding in findings)
                self.assertEqual(result["rule_penalty_score"], max(0, 100 - penalty), value)
                self.assertEqual(result["metrics"], plain["metrics"], value)

    def test_b4_strict_uses_the_kept_findings(self):
        """B4: excess_list だけに当たる文書の --strict は、種類なしと外さない種類で1、外す種類で0。"""
        path = self.write("list.md", EXCESS_LIST_ONLY)
        code, _, _ = self.lint("--strict", path)
        self.assertEqual(code, 1)
        for value in DOC_TYPE_VALUES:
            code, out, err = self.lint("--strict", "--doc-type", value, path)
            self.assertEqual(code, 0 if "excess_list" in SKIP_RULES[value] else 1, value)
            self.assertEqual(err, "")
            self.assertEqual("終了コード1:" in out, code == 1, value)

    def test_b5_bold_not_rendered_is_never_skipped(self):
        """B5: bold_not_rendered だけに当たる文書の --fail-on=error は、10の種類すべてで1。"""
        path = self.write("bold.md", BOLD_ERROR_ONLY)
        for value in DOC_TYPE_VALUES:
            code, out, _ = self.lint("--fail-on=error", "--doc-type", value, path)
            self.assertEqual(code, 1, value)
            self.assertTrue(out.endswith("終了コード1: --fail-on=error の条件（error の候補が1件以上）に当たりました"
                                         "（error 1件、warn 0件）。\n"), out)

    def test_b6_reader_does_not_change_findings(self):
        """B6: 3つの読者のどれでも、候補は読者なしと同じ。"""
        for text in list(RULE_SAMPLES.values()) + [SLIDES_SAMPLE]:
            plain = yomiyasu_lint.lint_text(text)
            for reader in READER_VALUES:
                result = yomiyasu_lint.lint_text(text, reader=reader)
                self.assertEqual(result["findings"], plain["findings"], reader)
                self.assertEqual(result["counts"], plain["counts"], reader)
                self.assertEqual(result["context"], {"doc_type": None, "reader": reader, "skipped_by_doc_type": {}})

    def test_b7_fourth_line(self):
        """B7: 4行目は付けたときだけ。外す規則あり、外す規則なし、読者だけ、種類と読者の形。"""
        path = self.write("slides.md", SLIDES_SAMPLE)
        code, out, err = self.lint("--doc-type", "slides", path)
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        self.assertEqual(lines[:3], [LINT_HEADER[0], LINT_HEADER[1].format(1), LINT_HEADER[2]])
        self.assertEqual(lines[3], SLIDES_LINE)
        self.assertEqual(lines[4:6], ["", "内訳: error 0件、warn 1件、info 0件"])
        cases = (
            (("--doc-type", "article", "--reader", "expert"),
             "文書の種類: 技術記事（article）、読者: 同じ分野の専門家（expert）。" + LINT_NO_SKIP + LINT_READER_NOTE),
            (("--reader", "general"), "文書の種類: 指定なし、読者: 専門知識のない人（general）。" + LINT_READER_NOTE),
            (("--doc-type", "formal"), "文書の種類: 公用文、規程、契約書、仕様書（formal）、読者: 指定なし。" + LINT_NO_SKIP),
            (("--doc-type", "pr", "--reader", "informed"),
             "文書の種類: PR説明（pr）、読者: 分野は違うが技術に詳しい人（informed）。種類に合わせて外した候補 0件"
             "（excess_list 0件）。" + LINT_READER_NOTE),
        )
        for argv, expected in cases:
            code, out, err = self.lint(*(argv + (path,)))
            self.assertEqual(out.split("\n")[3], expected, argv)
        # 候補が0件でも、4行目は出る（そのあとに内訳はない）
        empty = self.write("empty.md", "会議は3時に始まります。\n")
        code, out, err = self.lint("--doc-type", "minutes", empty)
        self.assertEqual(out, "\n".join([LINT_HEADER[0], LINT_HEADER[1].format(0), LINT_HEADER[2],
                                         "文書の種類: 議事録（minutes）、読者: 指定なし。種類に合わせて外した候補 0件"
                                         "（bold_label_list 0件、excess_list 0件、sentence_end_repetition 0件）。"]) + "\n")
        # render_findings は変えない（check の節が使う）
        result = yomiyasu_lint.lint_text(SLIDES_SAMPLE, doc_type="slides")
        self.assertNotIn("文書の種類", yomiyasu_lint.render_findings(result))

    def test_b7_strict_tail_counts_the_kept_findings(self):
        """9.3: 2行目の件数、内訳、終了コード1の最後の行の件数は、外したあとの候補で数える。"""
        path = self.write("both.md", EXCESS_LIST_ONLY + "\n" + BOLD_ERROR_ONLY)
        code, out, _ = self.lint("--strict", "--doc-type", "manual", path)
        lines = out.split("\n")
        self.assertEqual(code, 1)
        self.assertEqual(lines[1], "見直し候補: 1件")
        self.assertEqual(lines[3], "文書の種類: マニュアル（manual）、読者: 指定なし。種類に合わせて外した候補 1件（excess_list 1件）。")
        self.assertEqual(lines[-2], "終了コード1: --strict の条件（warn か error の候補が1件以上）に当たりました（error 1件、warn 0件）。")

    def test_b8_type_only_rules(self):
        """B8: DOC_TYPE_ONLY_RULES の規則は、種類なしとほかの種類では除かれ、指定した種類でだけ残る。"""
        self.assertEqual(yomiyasu_lint.DOC_TYPE_ONLY_RULES, {})
        text = COUNT_DECLARATION_ONLY
        with mock.patch.object(yomiyasu_lint, "DOC_TYPE_ONLY_RULES", {"count_declaration": ("article",)}):
            self.assertEqual(yomiyasu_lint.lint_text(text)["findings"], [])
            self.assertEqual([finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type="article")["findings"]],
                             ["count_declaration"])
            for value in DOC_TYPE_VALUES:
                if value != "article":
                    self.assertEqual(yomiyasu_lint.lint_text(text, doc_type=value)["findings"], [], value)

    def test_lint_text_takes_keyword_only_options(self):
        """9.2: lint_text(text, *, doc_type=None, reader=None)。値は中で正規化し、使えない値は ValueError。"""
        parameters = inspect.signature(yomiyasu_lint.lint_text).parameters
        for name in ("doc_type", "reader"):
            self.assertEqual(parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
            self.assertIsNone(parameters[name].default)
        self.assertEqual(yomiyasu_lint.lint_text(SLIDES_SAMPLE, doc_type=" ＳＬＩＤＥＳ ", reader="General")["context"],
                         {"doc_type": "slides", "reader": "general",
                          "skipped_by_doc_type": {"bold_label_list": 1, "count_declaration": 0, "excess_list": 0,
                                                  "short_summary_heading": 1}})
        with self.assertRaises(ValueError):
            yomiyasu_lint.lint_text(SLIDES_SAMPLE, doc_type="tech")
        with self.assertRaises(ValueError):
            yomiyasu_lint.lint_text(SLIDES_SAMPLE, reader="")

    def test_json_keeps_finding_keys_and_format(self):
        """9.3: findings の各要素は5キーのまま。外した候補の中身は JSON に入れない。形式2のまま。"""
        code, out, _ = self.lint("--json", "--doc-type", "slides", self.write("s.md", SLIDES_SAMPLE))
        result = json.loads(out)
        self.assertEqual(result["format_version"], 2)
        self.assertEqual([finding["rule"] for finding in result["findings"]], ["emoji_prohibited"])
        for finding in result["findings"]:
            self.assertEqual(set(finding), {"rule", "line", "severity", "message", "snippet"})
        self.assertNotIn("bold_label_list", json.dumps(result["findings"]))


# ---- C. 表と文書の食い違いを防ぐ（道具の部分）----

class TableTest(unittest.TestCase):
    def test_c1_tables(self):
        """C1: DOC_TYPE_SKIP_RULES のキーは DOC_TYPES の10と同じで順も同じ。READER_LEVELS は3つ。"""
        self.assertEqual(tuple(row[0] for row in markdown_visibility.DOC_TYPES), DOC_TYPE_VALUES + ("mail", "paper"))
        self.assertEqual(dict((row[0], row[1]) for row in markdown_visibility.DOC_TYPES), dict(DOC_TYPE_NAMES, **{r[0]: r[1] for r in NEW_DOC_TYPES}))
        self.assertEqual(dict((row[0], tuple(row[2])) for row in markdown_visibility.DOC_TYPES), dict(DOC_TYPE_DOMAINS, **{r[0]: r[2] for r in NEW_DOC_TYPES}))
        self.assertEqual(tuple(markdown_visibility.READER_LEVELS),
                         tuple((value, READER_NAMES[value]) for value in READER_VALUES))
        self.assertEqual(list(yomiyasu_lint.DOC_TYPE_SKIP_RULES), list(DOC_TYPE_VALUES) + ["mail", "paper"])
        self.assertEqual(dict((key, tuple(value)) for key, value in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items()), dict(SKIP_RULES, **NEW_SKIP_RULES))
        for value, rules in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items():
            self.assertEqual(list(rules), sorted(set(rules)), value)

    def test_c2_rules_that_are_never_skipped(self):
        """C2: bold_not_rendered（error）と、5.3 で外さないとした規則は、どの種類の表にもない（fragment_run の promo を除く）。"""
        for value, rules in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items():
            for rule in NEVER_SKIPPED:
                if value in NEVER_SKIPPED_EXCEPT.get(rule, ()):
                    continue
                self.assertNotIn(rule, rules, value)

    def test_c6_lint_help_lists_the_table(self):
        """C6: lint の --help の一覧が、DOC_TYPE_SKIP_RULES から作った文と同じ（終了コードの表の前）。"""
        built = ["文書の種類ごとに外す規則（--doc-type）:"]
        for value, rules in yomiyasu_lint.DOC_TYPE_SKIP_RULES.items():
            built.append("  {:<10}{}".format(value, "、".join(rules) if rules else "なし"))
        built.append(LINT_HELP_LIST.split("\n")[-2])
        built.append("外した候補は、見直し候補の件数と --strict、--fail-on の判定に入れません。")
        self.assertEqual("\n".join(built), LINT_HELP_LIST)
        code, out, _ = call(yomiyasu_lint.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertIn(LINT_HELP_LIST + "\n\n終了コード:", out)

    def test_help_texts(self):
        """9.6 のヘルプの文。check は run だけが受け、verify は受けない。"""
        def helps(parser):
            return dict((option, action.help) for action in parser._actions for option in action.option_strings)
        lint_help = helps(yomiyasu_lint._build_parser())
        self.assertEqual((lint_help["--doc-type"], lint_help["--reader"]), (LINT_DOC_TYPE_HELP, LINT_READER_HELP))
        diff_help = helps(yomiyasu_diff._build_parser())
        self.assertEqual((diff_help["--doc-type"], diff_help["--reader"]), (DIFF_DOC_TYPE_HELP, DIFF_READER_HELP))
        _, run, verify = yomiyasu_check._build_parser()
        run_help = helps(run)
        self.assertEqual((run_help["--doc-type"], run_help["--reader"]), (CHECK_DOC_TYPE_HELP, CHECK_READER_HELP))
        self.assertNotIn("--doc-type", helps(verify))
        self.assertNotIn("--reader", helps(verify))
        for main, argv in ((yomiyasu_check.main, ["run", "--help"]), (yomiyasu_diff.main, ["--help"]),
                           (yomiyasu_lint.main, ["--help"])):
            code, out, _ = call(main, argv)
            self.assertEqual(code, 0)
            self.assertIn("--doc-type", out)
            self.assertIn("--reader", out)
        code, out, _ = call(yomiyasu_check.main, ["verify", "--help"])
        self.assertNotIn("--doc-type", out)


class VisibilityApiTest(unittest.TestCase):
    """9.2: markdown_visibility の正規化と、lint と diff の1行の頭。"""

    def test_normalize(self):
        for raw, expected in (("SLIDES", "slides"), (" slides ", "slides"), ("ｓｌｉｄｅｓ", "slides"),
                              ("　Formal　", "formal"), ("pr", "pr"), (None, None)):
            self.assertEqual(markdown_visibility.normalize_doc_type(raw), expected, raw)
        for raw, expected in (("EXPERT", "expert"), ("ｇｅｎｅｒａｌ", "general"), (None, None)):
            self.assertEqual(markdown_visibility.normalize_reader(raw), expected, raw)
        for raw, shown in (("tech", "tech"), ("", "（空）"), ("  ", "（空）"), ("スライド", "スライド"), ("none", "none")):
            with self.assertRaises(ValueError) as caught:
                markdown_visibility.normalize_doc_type(raw)
            self.assertEqual(str(caught.exception), DOC_TYPE_ERROR.format(shown))
        with self.assertRaises(ValueError) as caught:
            markdown_visibility.normalize_reader("beginner")
        self.assertEqual(str(caught.exception), READER_ERROR.format("beginner"))

    def test_context_label(self):
        self.assertEqual(markdown_visibility.context_label("slides", None), "文書の種類: スライド（slides）、読者: 指定なし。")
        self.assertEqual(markdown_visibility.context_label(None, "general"),
                         "文書の種類: 指定なし、読者: 専門知識のない人（general）。")
        self.assertEqual(markdown_visibility.context_label("essay", "expert"),
                         "文書の種類: エッセイ・小説（essay）、読者: 同じ分野の専門家（expert）。")


# ---- D. オプションと記録 ----

class OptionTest(DocTypeCase):
    def test_d1_normalized_in_every_tool(self):
        """D1: 大文字、前後の空白、全角を正規化する。--doc-type=値 と --doc-type 値 の両方。lint、diff、check で同じ。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", SLIDES_SAMPLE)
        for form in (["--doc-type=SLIDES", "--reader= General "], ["--doc-type", "ｓｌｉｄｅｓ", "--reader", "GENERAL"]):
            code, out, _ = self.lint(*(form + ["--json", b]))
            self.assertEqual(json.loads(out)["context"]["doc_type"], "slides", form)
            self.assertEqual(json.loads(out)["context"]["reader"], "general", form)
            code, out, _ = self.diff(*(form + ["--json", a, b]))
            self.assertEqual(json.loads(out)["context"], {"doc_type": "slides", "reader": "general"}, form)
            code, out, _ = self.check(*(["run", "--json", "--new-run", "--source", a, "--final", b] + form))
            result = json.loads(out)
            self.assertEqual(result["context"], {"doc_type": "slides", "reader": "general"}, form)
            self.assertIn(" doc_type=slides reader=general ", result["status_line"])

    def test_d1_last_value_wins(self):
        """9.1: 同じオプションを2回付けたら最後の値を使う。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", SLIDES_SAMPLE)
        _, out, _ = self.lint("--doc-type", "pr", "--doc-type", "slides", "--json", b)
        self.assertEqual(json.loads(out)["context"]["doc_type"], "slides")
        _, out, _ = self.diff("--reader", "expert", "--reader", "general", "--json", a, b)
        self.assertEqual(json.loads(out)["context"]["reader"], "general")
        _, out, _ = self.check("run", "--json", "--source", a, "--final", b, "--doc-type", "pr", "--doc-type", "essay")
        self.assertEqual(json.loads(out)["context"]["doc_type"], "essay")

    def test_d2_bad_values_are_usage_errors(self):
        """D2: 使えない値と空の文字列で終了コード2。標準エラーに 9.1 の文、標準出力は空。check は状態フォルダに何も書かない。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", PAIRS_22[1][1])
        cases = ((["--doc-type", "tech"], DOC_TYPE_ERROR.format("tech")),
                 (["--doc-type="], DOC_TYPE_ERROR.format("（空）")),
                 (["--doc-type", "スライド"], DOC_TYPE_ERROR.format("スライド")),
                 (["--reader", "beginner"], READER_ERROR.format("beginner")),
                 (["--reader", " "], READER_ERROR.format("（空）")))
        for option, message in cases:
            for name, main, argv in (("lint", yomiyasu_lint.main, option + [b]),
                                     ("diff", yomiyasu_diff.main, option + [a, b]),
                                     ("check", yomiyasu_check.main,
                                      ["run", "--source", a, "--final", b, "--state-dir", self.state] + option)):
                code, out, err = call(main, argv)
                self.assertEqual((code, out, err), (2, "", message + "\n"), (name, option))
                self.assertFalse(self.state.exists(), (name, option))
        # check の --stdin でも、標準入力を読む前に断り、何も書かない
        code, out, err = self.check("run", "--stdin", "--doc-type", "x", stdin=_stdin_form(b"a\n", b"b\n"))
        self.assertEqual((code, out, err), (2, "", DOC_TYPE_ERROR.format("x") + "\n"))
        self.assertFalse(self.state.exists())

    def test_d2_verify_does_not_take_the_options(self):
        """9.1: check の verify は受けない（記録の値を使う）。"""
        b = self.write("b.md", PAIRS_22[1][1])
        for option in ("--doc-type", "--reader"):
            code, out, err = self.check("verify", "--final", b, option, "pr")
            self.assertEqual((code, out), (2, ""), option)
            self.assertIn("unrecognized arguments", err)

    def test_d3_diff_endings_with_the_options(self):
        """D3: diff の --endings と --doc-type（--reader）の組は終了コード2。"""
        b = self.write("b.md", SLIDES_SAMPLE)
        for option in (["--doc-type", "slides"], ["--reader", "general"]):
            code, out, err = self.diff(*(["--endings"] + option + [b]))
            self.assertEqual((code, out), (2, ""), option)
            self.assertIn(ENDINGS_ERROR + "\n", err)
            self.assertTrue(err.startswith("使い方: yomiyasu_diff.py"), err)

    def test_d4_diff_judgement_does_not_change(self):
        """D4: 指示書2.2の3組と推敲の48組で、種類と読者を付けても、context 以外の JSON と --fail-on の終了コードは同じ。
        diff の詰めで足した文体の硬化の検査（stiffness）と勢いの検査（tone）だけは、種類で level（見直し候補 review か
        参考 info）が変わる（追加文書 2.4、勢いの文書 3.3）。候補と値は同じなので、level を除いて比べ、level は表のとおりか見る。
        diff の詰めの直しで、硬化の参考に incident を足し、promo 以外の種類では勢いの
        絵文字と見出しを参考にした（候補ごとの level）。promo では、番号つき項目の行と太字だけの行も勢いの見出しの字数に数える
        （反証で見つけた例）ので、promo だけは見出しの字数と見出しの候補を除いて比べ、違いがそこだけであることを見る。"""
        pairs = list(PAIRS_22) + [((CORPUS / a).read_text(encoding="utf-8"), (CORPUS / b).read_text(encoding="utf-8"))
                                  for a, b in corpus_pairs()[:48]]
        options = ({"doc_type": "slides", "reader": "general"}, {"doc_type": "essay", "reader": "expert"},
                   {"doc_type": "pr", "reader": "informed"}, {"doc_type": "formal", "reader": None},
                   {"doc_type": "incident", "reader": None}, {"doc_type": "promo", "reader": None})
        reference = {"stiffness": ("incident", "formal"), "tone": ("pr", "article", "incident", "manual", "formal")}

        def expected_level(key, doc_type, subkind):
            if doc_type in reference[key]:
                return "info"
            if key == "tone" and doc_type not in (None, "promo") and subkind in ("emoji", "heading"):
                return "info"
            return "review"

        def without_level(result, promo=False):
            for key in ("stiffness", "tone"):
                section = dict(result[key])
                section.pop("level")
                section["candidates"] = [dict((k, v) for k, v in item.items() if k != "level")
                                         for item in section["candidates"]
                                         if not (promo and key == "tone" and item["subkind"] == "heading")]
                if promo and key == "tone":
                    section["candidate_count"] = len(section["candidates"])
                    section["counts"] = dict((side, dict((k, v) for k, v in counts.items() if k != "heading_chars"))
                                             for side, counts in section["counts"].items())
                result[key] = section
            return result
        for old, new in pairs:
            plain = yomiyasu_diff.diff(old, new)
            plain.pop("context")
            for given in options:
                result = yomiyasu_diff.diff(old, new, **given)
                self.assertEqual(result.pop("context"), given)
                for key in reference:
                    for item in result[key]["candidates"]:
                        self.assertEqual(item["level"], expected_level(key, given["doc_type"], item["subkind"]), (key, given))
                    levels = set(item["level"] for item in result[key]["candidates"])
                    if levels:
                        self.assertEqual(result[key]["level"], "review" if "review" in levels else "info", (key, given))
                    else:
                        self.assertEqual(result[key]["level"], expected_level(key, given["doc_type"], None), (key, given))
                promo = given["doc_type"] == "promo"
                self.assertEqual(without_level(result, promo), without_level(copy.deepcopy(plain), promo), given)
        for number, (old, new) in enumerate(PAIRS_22):
            a = self.write("a{}.md".format(number), old)
            b = self.write("b{}.md".format(number), new)
            code, _, _ = self.diff("--fail-on=meaning-risk", a, b)
            for given in options:
                argv = ["--fail-on=meaning-risk", "--doc-type", given["doc_type"]]
                argv += ["--reader", given["reader"]] if given["reader"] else []
                self.assertEqual(self.diff(*(argv + [a, b]))[0], code, given)

    def test_diff_human_output_line(self):
        """9.4: 指定したときだけ、断りの行のすぐあとに1行。最後の状態の行は変えない。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", PAIRS_22[1][1])
        _, plain, _ = self.diff(a, b)
        code, out, err = self.diff("--doc-type", "incident", a, b)
        self.assertEqual((code, err), (0, ""))
        lines, plain_lines = out.split("\n"), plain.split("\n")
        self.assertEqual(lines[:3], plain_lines[:3])
        self.assertEqual(lines[3], "文書の種類: 障害報告（incident）、読者: 指定なし。" + DIFF_CONTEXT_TAIL)
        self.assertEqual(lines[4:], plain_lines[3:])
        _, out, _ = self.diff("--reader", "general", a, b)
        self.assertEqual(out.split("\n")[3], "文書の種類: 指定なし、読者: 専門知識のない人（general）。" + DIFF_CONTEXT_TAIL)
        parameters = inspect.signature(yomiyasu_diff.diff).parameters
        self.assertEqual(list(parameters)[:3], ["orig_raw", "rw_raw", "stance"])
        for name in ("encoding_notes", "doc_type", "reader"):
            self.assertEqual(parameters[name].kind, inspect.Parameter.KEYWORD_ONLY, name)

    def test_d5_check_passes_the_values_to_the_children(self):
        """D5: check run は子の lint と diff に正規化した値を渡す。新規作成では lint だけ（原文とみなした資料があれば diff にも）。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", SLIDES_SAMPLE)
        code, out, err = self.check("run", "--source", a, "--final", b, "--doc-type", "SLIDES", "--reader", "General")
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        path, record = self.record(lines)
        folder = path.parent
        lint = json.loads((folder / "attempt-1.lint.json").read_text(encoding="utf-8"))
        diff = json.loads((folder / "attempt-1.diff.json").read_text(encoding="utf-8"))
        self.assertEqual(lint["context"], {"doc_type": "slides", "reader": "general",
                                           "skipped_by_doc_type": {"bold_label_list": 1, "count_declaration": 0,
                                                                   "excess_list": 0, "short_summary_heading": 1}})
        self.assertEqual(diff["context"], {"doc_type": "slides", "reader": "general"})
        # 子の .lint.txt には lint の4行目が入る
        self.assertEqual((folder / "attempt-1.lint.txt").read_text(encoding="utf-8").split("\n")[3],
                         SLIDES_LINE.replace("読者: 指定なし。", "読者: 専門知識のない人（general）。") + LINT_READER_NOTE)
        # 新規作成（資料が最終稿と似ていない）: lint だけに渡す
        material = self.write("memo.md", "検索の仕組みを10月から変える。対象は社内の文書。担当は検索チーム。\n")
        code, out, err = self.check("run", "--material", material, "--final", b, "--doc-type", "slides")
        lines = out.split("\n")
        self.assertIn(" mode=compose doc_type=slides checks=lint,materials", lines[1])
        path, record = self.record(lines)
        self.assertEqual(json.loads((path.parent / "attempt-1.lint.json").read_text(encoding="utf-8"))["context"]["doc_type"],
                         "slides")
        self.assertFalse((path.parent / "attempt-1.diff.json").exists())
        # 新規作成で資料を原文とみなしたとき（10.8 C-44）は diff にも渡す
        similar = self.write("similar.md", SLIDES_SAMPLE.replace("速くなります", "速くなる予定です"))
        code, out, err = self.check("run", "--material", similar, "--final", b, "--doc-type", "slides", "--reader", "expert")
        lines = out.split("\n")
        self.assertIn(" mode=compose doc_type=slides reader=expert checks=lint,diff,materials", lines[1])
        path, record = self.record(lines)
        self.assertEqual(json.loads((path.parent / "attempt-1.diff.json").read_text(encoding="utf-8"))["context"],
                         {"doc_type": "slides", "reader": "expert"})

    def test_d6_record_status_line_and_json(self):
        """D6: 記録の options、状態の行の doc_type= と reader=（mode= の次、付けたときだけ）、3行目、verify の状態の行と JSON。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", SLIDES_SAMPLE)
        code, out, err = self.check("run", "--source", a, "--final", b, "--doc-type", "slides", "--reader", "general")
        lines = out.split("\n")
        state, fields = self.status_fields(lines[1])
        keys = [key for key, _ in fields]
        self.assertEqual(keys, ["via", "run", "attempt", "final", "mode", "doc_type", "reader", "checks", "meaning_risk"])
        self.assertEqual(dict(fields)["doc_type"], "slides")
        self.assertEqual(dict(fields)["reader"], "general")
        self.assertTrue(lines[2].startswith("実行した検査: lint（最終稿、種類 slides、外した候補2件）候補1件、diff（原文→最終稿）"),
                        lines[2])
        self.assertEqual(lines[-2:], [lines[1], ""])
        _, record = self.record(lines)
        self.assertEqual(list(record["options"]), ["stance", "fail_on", "timeout", "doc_type", "reader"])
        self.assertEqual((record["options"]["doc_type"], record["options"]["reader"]), ("slides", "general"))
        self.assertEqual(record["result"]["token"], lines[1])
        # verify は記録の値を状態の行と JSON に出す
        code, out, err = self.check("verify", "--final", b)
        self.assertEqual(code, 0, out + err)
        verify_lines = out.split("\n")
        self.assertIn(" mode=rewrite doc_type=slides reader=general checks=lint,diff ", verify_lines[1])
        code, out, err = self.check("verify", "--final", b, "--json")
        result = json.loads(out)
        keys = list(result)
        self.assertEqual(keys[keys.index("mode") + 1], "context")
        self.assertEqual(result["context"], {"doc_type": "slides", "reader": "general"})
        # 読者だけ: 3行目は変えない（読者は検査を変えないので書かない）。状態の行には reader= だけ
        c = self.write("c.md", SLIDES_SAMPLE + "追記です。\n")
        code, out, err = self.check("run", "--new-run", "--source", a, "--final", c, "--reader", "expert")
        lines = out.split("\n")
        self.assertTrue(lines[2].startswith("実行した検査: lint（最終稿）候補3件、"), lines[2])
        self.assertIn(" mode=rewrite reader=expert checks=lint,diff ", lines[1])
        # 種類だけ（外す規則がない種類）: 外した候補0件
        d = self.write("d.md", SLIDES_SAMPLE + "追記2です。\n")
        code, out, err = self.check("run", "--new-run", "--source", a, "--final", d, "--doc-type", "formal")
        lines = out.split("\n")
        self.assertTrue(lines[2].startswith("実行した検査: lint（最終稿、種類 formal、外した候補0件）候補3件、"), lines[2])
        self.assertIn(" mode=rewrite doc_type=formal checks=lint,diff ", lines[1])
        # 状態の行は読む側の正規表現にそのまま当たる
        self.assertIsNotNone(STATUS_LINE.match(lines[1]))

    def test_d6_stdin_run(self):
        """9.5: run --stdin でも同じ。"""
        code, out, err = self.check("run", "--stdin", "--doc-type", "minutes",
                                    stdin=_stdin_form(PAIRS_22[1][0].encode("utf-8"), SENTENCE_END_ONLY.encode("utf-8")))
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        self.assertIn(" mode=rewrite doc_type=minutes checks=lint,diff ", lines[1])
        self.assertTrue(lines[2].startswith("実行した検査: lint（最終稿、種類 minutes、外した候補1件）候補0件、"), lines[2])

    def test_d6_same_run_may_change_the_type(self):
        """9.5: 同じ実行IDの2回目で種類か読者を変えてもよい（回ごとの記録に残る）。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", SLIDES_SAMPLE)
        _, out1, _ = self.check("run", "--source", a, "--final", b, "--doc-type", "slides")
        _, out2, _ = self.check("run", "--source", a, "--final", b, "--doc-type", "article")
        first, second = self.record(out1.split("\n"))[1], self.record(out2.split("\n"))[1]
        self.assertEqual((first["run_id"], first["attempt"]), (second["run_id"], 1))
        self.assertEqual(second["attempt"], 2)
        self.assertEqual((first["options"]["doc_type"], second["options"]["doc_type"]), ("slides", "article"))

    def test_d7_replay_and_tampered_records(self):
        """D7: 種類を付けた記録で verify --replay が replay=ok。記録の options.doc_type を書き換えると invalid_record。
        digest を計算し直しても、使えない値か、レポートの context と違う値なら invalid_record。"""
        a = self.write("a.md", PAIRS_22[1][0])
        b = self.write("b.md", SLIDES_SAMPLE)
        code, out, err = self.check("run", "--source", a, "--final", b, "--doc-type", "slides", "--reader", "general")
        path, record = self.record(out.split("\n"))
        code, out, err = self.check("verify", "--final", b, "--replay")
        self.assertEqual(code, 0, out + err)
        self.assertIn(" doc_type=slides reader=general ", out.split("\n")[1])
        self.assertTrue(out.split("\n")[1].endswith(" replay=ok"), out)
        original = path.read_bytes()

        def rewrite(change, digest):
            value = json.loads(original.decode("utf-8"))
            change(value)
            if digest:
                value["record_digest"] = yomiyasu_check._record_digest(value)
            path.write_text(json.dumps(value, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")

        rewrite(lambda value: value["options"].update(doc_type="pr"), False)
        code, out, err = self.check("verify", "--final", b)
        self.assertEqual((code, out.split("\n")[1].split()[1]), (1, "invalid_record"), out)
        for bad in ("foo", "SLIDES", 3):
            rewrite(lambda value: value["options"].update(doc_type=bad), True)
            code, out, err = self.check("verify", "--final", b)
            self.assertEqual((code, out.split("\n")[1].split()[1]), (1, "invalid_record"), (bad, out))
        rewrite(lambda value: value["options"].update(reader="beginner"), True)
        code, out, err = self.check("verify", "--final", b)
        self.assertEqual(out.split("\n")[1].split()[1], "invalid_record", out)
        # digest を計算し直して別の種類にした記録は、ハッシュを確かめたレポートの context と合わないので、--replay なしでも
        # invalid_record（記録の件数の照らしと同じ）
        for change in ({"doc_type": "pr"}, {"doc_type": None}, {"reader": None}, {"reader": "expert"}):
            rewrite(lambda value: value["options"].update(change), True)
            code, out, err = self.check("verify", "--final", b)
            self.assertEqual((code, out.split("\n")[1].split()[1]), (1, "invalid_record"), (change, out))
            code, out, err = self.check("verify", "--final", b, "--json")
            problems = json.loads(out)["problems"]
            self.assertIn("summary_mismatch", [problem["code"] for problem in problems], change)
            self.assertIn("lint.context", json.dumps(problems), change)
            self.assertIn("diff.context", json.dumps(problems), change)
        # このキーを足す前の記録（options に doc_type と reader がない）は、値なしとして読む
        c = self.write("c.md", PAIRS_22[1][1])
        code, out, err = self.check("run", "--source", a, "--final", c)
        path_c, record_c = self.record(out.split("\n"))
        for key in ("doc_type", "reader"):
            record_c["options"].pop(key)
        record_c["record_digest"] = yomiyasu_check._record_digest(record_c)
        path_c.write_text(json.dumps(record_c, ensure_ascii=True, indent=1) + "\n", encoding="utf-8")
        code, out, err = self.check("verify", "--final", c)
        self.assertEqual((code, out.split("\n")[1].split()[1]), (0, "executed"), out)
        self.assertNotIn("doc_type=", out)

    def test_d8_versions_do_not_change(self):
        """D8: --version と形式の版は変えない（9.7）。"""
        self.assertEqual(call(yomiyasu_lint.main, ["--version"])[1], "yomiyasu_lint.py 2.0.0-beta (JSON format 2)\n")
        self.assertEqual(call(yomiyasu_diff.main, ["--version"])[1], "yomiyasu_diff.py 2.0.0-beta (JSON format 2)\n")
        self.assertEqual(call(yomiyasu_check.main, ["--version"])[1],
                         "yomiyasu_check.py 2.0.0-beta (record format 1, result format 1, materials format 1)\n")


# ---- E. 速さ ----

class SpeedTest(unittest.TestCase):
    def test_e1_long_document(self):
        """E1: 6万字の文書で、--doc-type slides の lint が指定なしの時間＋0.2秒以内。"""
        block = SLIDES_SAMPLE + EXCESS_LIST_ONLY + SENTENCE_END_ONLY + COUNT_DECLARATION_ONLY + "\n"
        text = block * (60000 // len(block) + 1)
        self.assertGreaterEqual(len(text), 60000)

        def best(**options):
            times = []
            for _ in range(3):
                started = time.perf_counter()
                yomiyasu_lint.lint_text(text, **options)
                times.append(time.perf_counter() - started)
            return min(times)

        plain = best()
        typed = best(doc_type="slides")
        self.assertLessEqual(typed, plain + 0.2, (plain, typed))


# ---- C3、C4、C5: SKILL.md と references（SKILL.md と references を入れる段までは失敗する）----

class SkillFilesTest(unittest.TestCase):
    def test_c3_doc_type_files(self):
        """C3: 12の references/doc-types/<値>.md がルートと skills/yomiyasu にあり、4行目が表と同じ。3行目の domains がある。
        mail と paper は、4行目の規則 ID が DOC_TYPE_SKIP_RULES と DOC_TYPE_SKIP_PATTERNS（一部の型だけ外す規則）の和と同じ。"""
        for base in (ROOT / "references", PACKAGE / "references"):
            for value in DOC_TYPE_VALUES + tuple(row[0] for row in NEW_DOC_TYPES):
                path = base / "doc-types" / (value + ".md")
                self.assertTrue(path.is_file(), str(path))
                lines = path.read_text(encoding="utf-8").split("\n")
                rules = yomiyasu_lint.DOC_TYPE_SKIP_RULES[value]
                if value in DOC_TYPE_VALUES:
                    self.assertEqual(lines[3], "lint で外す規則: " + ("、".join(rules) if rules else "なし"), str(path))
                else:
                    self.assertTrue(lines[3].startswith("lint で外す規則: "), str(path))
                    partial = tuple(yomiyasu_lint.DOC_TYPE_SKIP_PATTERNS.get(value, {}))
                    self.assertEqual(set(re.findall(r"[a-z][a-z_]+", lines[3][len("lint で外す規則: "):])), set(rules + partial), str(path))
                    if not rules and not partial:
                        self.assertEqual(lines[3], "lint で外す規則: なし", str(path))
                self.assertTrue(lines[2].startswith("あわせて読む: "), str(path))
                named = re.findall(r"domains/([a-z]+\.md)", lines[2])
                self.assertTrue(named, str(path))
                for name in named:
                    self.assertTrue((base / "domains" / name).is_file(), (str(path), name))

    def test_c4_audience_table(self):
        """C4: audience.md の種類と外す規則の表の規則ID が DOC_TYPE_SKIP_RULES と同じ。"""
        for base in (ROOT / "references", PACKAGE / "references"):
            path = base / "audience.md"
            self.assertTrue(path.is_file(), str(path))
            rows = {}
            column = None
            for line in path.read_text(encoding="utf-8").split("\n"):
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")] if line.startswith("|") else None
                if cells is None:
                    column = None
                    continue
                if "lint で外す規則" in cells:
                    column = cells.index("lint で外す規則")
                    continue
                if column is not None and (cells[0] in DOC_TYPE_VALUES or cells[0] in NEW_SKIP_RULES):
                    # mail の meta_filler は一部の型だけを外す（「meta_filler（返信と結びの5つの型だけ）」）。括弧の中は読まない
                    rows[cells[0]] = tuple(re.sub(r"（[^）]*）", "", rule) for rule in re.split(r"[、,]\s*", cells[column])
                                           if rule and rule != "なし")
            expected = dict(SKIP_RULES)
            for value, rules in NEW_SKIP_RULES.items():
                expected[value] = rules + tuple(yomiyasu_lint.DOC_TYPE_SKIP_PATTERNS.get(value, {}))
            self.assertEqual(rows, expected, str(path))

    def test_c5_skill_md(self):
        """C5: SKILL.md の種類の表に12の値がちょうど1回ずつあり、3つの読者の値、「ここに説明が必要です」、--doc-type、
        --reader がある（--doc-type と --reader が check run の --help にあることは TableTest.test_help_texts）。"""
        text = (PACKAGE / "SKILL.md").read_text(encoding="utf-8")
        found = re.findall(r"^[ \t]*\|\s*([a-z]+)（", text, re.M)
        self.assertEqual(sorted(found), sorted(DOC_TYPE_VALUES + tuple(row[0] for row in NEW_DOC_TYPES)))
        for word in READER_VALUES + ("ここに説明が必要です", "--doc-type", "--reader"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
