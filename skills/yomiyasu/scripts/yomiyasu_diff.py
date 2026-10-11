#!/usr/bin/env python3
"""
yomiyasu_diff.py - 元の文と書き直した文を比べ、語句・文末・構造の変化を見直す候補を出す。

標準ライブラリだけで動く。モデルは呼ばない。
拾うのは「意味が変わりやすい」ものだけに絞る。
  1. 文末や言い回しの種類（依頼・勧誘・義務・評価・可能・推量・念押し・意志・条件・説明化・つなぎ）の数の増減
  2. 元の文にない語（漢字2字以上、カタカナ2字以上、英数字2字以上）と、書き直した文から消えた語
  3. 箇条書きをやめたかどうか、段落をまとめたかどうか
  4. 書き直した文の中で、つながりを確かめるべき場所（文頭のつなぎ、主題の「も」、予告だけの文、文頭の指示語）
  5. 文末の種類（勧め・依頼・動作の「〜します」・評価・常体など）と、文書の立場が混ざっている候補
  6. 書き直した文の中で、太字にならない書き方（GitHub などで ** がそのまま表示されることがある箇所）と、直し方の案
言い換えかどうか、つながりが合っているか、文末が立場に合っているかの最終判断は、この結果を見たモデル（または人）がする。
"""
import re
import sys
import json
import difflib
import unicodedata
from bisect import bisect_left, bisect_right
try:
    if __package__:
        from .markdown_visibility import analyze_markdown, inline_protected_spans, unicode_whitespace
    else:
        from markdown_visibility import analyze_markdown, inline_protected_spans, unicode_whitespace
except ModuleNotFoundError as error:
    # A direct spec_from_file_location loader need not put this file's directory
    # on sys.path. Resolve this internal resource beside the actual source file.
    expected = (__package__ + ".markdown_visibility") if __package__ else "markdown_visibility"
    parent = __package__.split(".")[0] if __package__ else "markdown_visibility"
    if error.name not in (expected, parent):
        raise
    import importlib.util
    from pathlib import Path
    _visibility_spec = importlib.util.spec_from_file_location(
        "_yomiyasu_markdown_visibility", Path(__file__).with_name("markdown_visibility.py"))
    _visibility_module = importlib.util.module_from_spec(_visibility_spec)
    _visibility_spec.loader.exec_module(_visibility_module)
    analyze_markdown = _visibility_module.analyze_markdown
    inline_protected_spans = _visibility_module.inline_protected_spans
    unicode_whitespace = _visibility_module.unicode_whitespace
from collections import Counter, OrderedDict

# 文末や言い回しの種類。数が増えた・減ったものを候補にする
MARKERS = {
    "依頼": r"(?:て|で)ください",
    "勧誘": r"ましょう",
    "義務": r"なければ(?:なりません|ならない)|なくては(?:なりません|ならない)|ねばならない|必要があ(?:ります|る)|べき",
    "評価": r"大切|重要|大事|不可欠|欠かせ|肝心|肝要",
    "可能": r"でき(?:ます|る|ません|ない)|(?<![しさ])(?:ら|れ)(?:ます|ません)(?=[。、がけし]|$)|(?<=[作使書読言防守残伝送続進])(?:れ|え|け|め|せ)(?:ます|る)(?=[。、がけし]|$)",
    "推量": r"でしょう|だろう|かもしれ|はず|と思(?:います|う)|ようです|らしい|おそれ|たいところ",
    "念押し": r"のです|んです|こそ|まさに|必ず|絶対|常に",
    "意志": r"(?:に|ように|ことに)し(?:ます|ている|ています)",
    "条件": r"(?<!例)(?<!たと)(?:れ|え|け|せ|て|ね|め|べ)ば(?![かり])|なら(?=[、。]|$|\s)|たら(?=[、。]|$|\s)|場合",
    "説明化": r"ことが挙げられ|ということ|ことです|ことになります",
    "つなぎ": r"まず|また(?!は)|そして|さらに|次に|最後に|ただし|しかし|つまり|そのため|ので(?!す)|によって|ことで|ことにより",
}

# 文の種類を示す印。推敲の前後で対応する範囲を比べ、印が消えた・増えたものを候補にする。
# 種類と関係のない用法（様子の「降りそうだ」、目的の「使えるように」、「という名前」、「素晴らしい」、
# 受身の「見落とされた」、問いの「〜でしょうか」、評価の「驚くべき」など）は拾わない。
_END = r"(?=[。、！!？?よねがけのかし]|です|$)"
# 印の文字列を先頭に置き、直前の文字の確かめ（後読み）はその後ろに書く。正規表現が当たる見込みのない位置を飛ばせるので速い。
_TYPE_PATTERNS = (
    ("伝聞", r"そう(?:(?<=[るうくすつぬぶむぐ]そう)|(?<=だそう)|(?<=ったそう)|(?<=んだそう)|(?<=ないそう))"
           r"(?:だ|です|でした|だった|で(?=、))(?=[。、！!よね]|$)"
           r"|とされ(?<!落とされ)(?<!必要とされ)(?:る|ている|ています|ており|た|ます|ました|てきた)"
           r"|という(?=[。！!]|$)|といいます(?<=[るうくすつぬぶむぐただ]といいます)(?=[。！!]|$)|とのこと(?<!あとのこと)(?<!後とのこと)"
           r"|によ(?<!場合によ)(?:ると|れば)|と(?:言|い)われ(?:る|ている|ています|ており|た|ます|ました|てきた)"
           r"|と聞(?<!かと聞)(?:いた|いて(?:いる|います|おり)|きました)"),
    ("推量", r"らし(?<=[るうくすつぬぶむぐいた]らし)(?:い|かった|く(?=、))" + _END
           # 名詞のあとの「らしい」は、文の終わりにあるときだけ推量と数える（「春らしい陽気」「素晴らしい」は除く）。
           + r"|らし(?<!素晴らし)(?<!すばらし)(?<!めずらし)(?<!わざとらし)(?<!可愛らし)(?<!かわいらし)(?<!憎らし)(?<!馬鹿らし)"
             r"(?<!ばからし)(?<!男らし)(?<!女らし)(?<!子供らし)(?<!子どもらし)(?<!いやらし)(?<!汚らし)(?<!春らし)(?<!夏らし)(?<!秋らし)"
             r"(?<!冬らし)(?<!彼らし)(?:い|かった)(?=[。！!]|です|でした|$)"
           + r"|よう(?<!次のよう)(?<!以下のよう)(?<!下記のよう)(?<!上記のよう)(?<!左記のよう)(?<!このよう)(?<!そのよう)"
             r"(?:だ|です|でした|だった|である|であった|で(?=、))" + _END
           + r"|みたい(?:だ|です|でした|だった)(?=[。！!よね]|$)"
           r"|かも(?:しれ|知れ)(?:ない|ません|ず)|可能性があ(?:る|ります|った|りました)"
           r"|だろう(?<!でだろう)(?!か)|であろう|でしょう(?!か)|ではない(?:でしょう|だろう)か|はず(?:だ|です|で|でした|だった)"
           r"|と(?:見|み)られ(?:る|ている|ています|ており|た|ます)|と(?:思|おも)われ(?:る|ます|た)|と考えられ(?:る|ます|た)"),
    ("意見", r"と(?:(?:私|僕|筆者|我々|われわれ|当社|弊社|私たち)は)?(?:思|おも)(?:う|い(?:ます|ました)|った|って(?:いる|います|いた|いました|おり))"
           r"|と(?:(?:私|僕|筆者|我々|われわれ|当社|弊社|私たち)は)?(?:考え|感じ)(?:る(?!と)|ます|ました|た|て(?:いる|います|いた|いました|おり))"
           r"|ように(?:思|感じ)(?:う|います|いました|られ)"),
    ("例え", r"まるで|あたかも|さながら|(?:ごと|如)(?<!前述のごと)(?<!上記のごと)(?<!周知のごと)(?<!以下のごと)(?<!次のごと)"
           r"(?<!前述の如)(?<!上記の如)(?<!周知の如)(?<!以下の如)(?<!次の如)[くき]"),
    ("依頼・決まり", r"(?:て|で)(?:ください|下さい)|を(?:ください|下さい)|(?:ご|お)[一-龥ぁ-んァ-ヴー]{1,8}(?:ください|下さい)"
                 r"|お願い(?<!よろしくお願い)(?<!宜しくお願い)(?:します|いたします|致します|申し上げます|できますか|できますでしょうか)"
                 r"|て(?:いただけ|もらえ)(?:ますか|ませんか)|てほしい|てもらいたい|ていただきたい"
                 r"|べき(?<!しかるべき)(?<!然るべき)(?<!驚くべき)(?<!恐るべき)(?<!来るべき)(?<!特筆すべき)(?<!注目すべき)(?!乗)"
                 r"|なければ(?:ならない|なりません|いけない|いけません)|なくては(?:ならない|なりません|いけない|いけません)"
                 r"|ないといけ(?:ない|ません)|(?:て|で)は(?:いけ|なら)(?:ない|ません)|ねばならない"
                 r"|必要があ(?:る|ります)|必要(?:です|だ)(?=[。！!]|$)"),
)
TYPE_MARKERS = OrderedDict((kind, re.compile(pattern, re.M)) for kind, pattern in _TYPE_PATTERNS)
# 種類ごとに、印の正規表現が当たるために必ず含まれる文字列。どれも含まない文章では、その種類の正規表現を当てない。
_TYPE_LITERALS = {
    "伝聞": ("そう", "とされ", "という", "といいます", "とのこと", "によると", "によれば", "われ", "と聞"),
    "推量": ("らし", "よう", "みたい", "かも", "可能性", "だろう", "であろう", "でしょう", "はず", "られ", "われ"),
    "意見": ("と思", "とおも", "と考え", "と感じ", "は思", "はおも", "は考え", "は感じ", "ように思", "ように感じ"),
    "例え": ("まるで", "あたかも", "さながら", "ごと", "如"),
    "依頼・決まり": ("ください", "下さい", "お願い", "いただけ", "もらえ", "ほしい", "もらいた", "いただきた", "べき", "なければ",
                 "なくては", "ないといけ", "はいけ", "はなら", "ねばならない", "必要"),
}
# 「まるで〜のようだ」のように例えの語がある文では、「よう」「みたい」を推量ではなく例えの印として数える。
_SIMILE_YOU = re.compile(r"よう(?:だ|な|に|です|でした|だった|である)|みたい(?:だ|な|に|です|でした)")
_SENTENCE_PIECE = re.compile(r"[^。！？!?\n]+[。！？!?]*")


def _mark_positions(text: str):
    """文章全体に印の正規表現を1回ずつ当て、(開始位置, 種類, 印) を位置の順に返す。"""
    found = [(m.start(), kind, m.group(0)) for kind, pattern in TYPE_MARKERS.items()
             if any(literal in text for literal in _TYPE_LITERALS[kind]) for m in pattern.finditer(text)]
    if "よう" in text or "みたい" in text:
        found += [(m.start(), "_よう", m.group(0)) for m in _SIMILE_YOU.finditer(text)]
    found.sort(key=lambda item: item[0])
    return found


def _marks_in(positions, spans):
    """範囲（開始, 終了）に入る印を {種類: [印, ...]} にまとめる。例えの語がある範囲では「よう」「みたい」を例えに数える。"""
    keys = [item[0] for item in positions]
    marks = OrderedDict()
    for start, end in spans:
        for _, kind, hit in positions[bisect_left(keys, start):bisect_left(keys, end)]:
            hits = marks.setdefault(kind, [])
            if hit not in hits:
                hits.append(hit)
    similes = marks.pop("_よう", [])
    if "例え" in marks:
        marks["例え"] += [hit for hit in similes if hit not in marks["例え"]]
        guesses = [hit for hit in marks.pop("推量", ()) if not _SIMILE_YOU.fullmatch(hit)]
        if guesses:
            marks["推量"] = guesses
    return OrderedDict((kind, marks[kind]) for kind in TYPE_MARKERS if kind in marks)


def type_marks(sentence: str):
    """文や範囲に含まれる文の種類の印。{種類: [印の文字列, ...]}（同じ印は1回だけ）"""
    return _marks_in(_mark_positions(sentence), [(0, len(sentence))])


def _sentence_spans(t: str):
    """正規化した文章を文に分け、(開始, 終了) を返す。コードブロックと表の行は飛ばす。"""
    spans, offset, in_code = [], 0, False
    for line in t.split("\n"):
        head = line.strip()
        if head.startswith("```"):
            in_code = not in_code
        elif not in_code and head and not head.startswith("|"):
            for m in _SENTENCE_PIECE.finditer(line):
                if m.group(0).strip():
                    spans.append((offset + m.start(), offset + m.end()))
        offset += len(line) + 1
    return spans


def _type_changes(o: str, r: str, opcodes):
    """元の各文が、文字単位の対応で書き直した文章のどの範囲に当たるかをたどり、範囲ごとに印を比べる。
    文を分けても、つないでも、範囲の中で比べるので、移っただけの印は変化として出ない。
    範囲が重なる元の文はまとめて比べる。丸ごと消えた文は比べず、丸ごと移した文は同じ文を探して比べる。"""
    if not opcodes:
        return []
    starts = [op[1] for op in opcodes]

    def map_start(i):
        tag, i1, i2, j1, j2 = opcodes[max(0, bisect_right(starts, i) - 1)]
        if tag == "equal":
            return j1 + min(i - i1, j2 - j1)
        return j2 if tag == "insert" else j1

    def map_end(e):
        tag, i1, i2, j1, j2 = opcodes[max(0, bisect_left(starts, e) - 1)]
        return j1 + min(e - i1, j2 - j1) if tag == "equal" else j2

    def kept(i, j):
        k = max(0, bisect_right(starts, i) - 1)
        while k < len(opcodes) and opcodes[k][1] < j:
            if opcodes[k][0] in ("equal", "replace") and opcodes[k][2] > i:
                return True
            k += 1
        return False

    o_marks, r_marks = _mark_positions(o), _mark_positions(r)
    if not o_marks and not r_marks:
        return []
    groups, moved = [], []
    for s, e in _sentence_spans(o):
        text = o[s:e].strip()
        if not kept(s, e):
            at = r.find(text)
            if at != -1:
                moved.append(([text], [(s, e)], at, at + len(text)))
            continue
        a, b = map_start(s), map_end(e)
        if b <= a or not r[a:b].strip("。！？!?、 \n"):
            continue
        if groups and a < groups[-1][3]:
            groups[-1][0].append(text)
            groups[-1][1].append((s, e))
            groups[-1][3] = max(groups[-1][3], b)
        else:
            groups.append([[text], [(s, e)], a, b])
    out = []
    for texts, spans, a, b in [tuple(g) for g in groups] + moved:
        before = _marks_in(o_marks, spans)
        after = _marks_in(r_marks, [(a, b)])
        lost = [{"kind": kind, "hits": hits} for kind, hits in before.items() if kind not in after]
        added = [{"kind": kind, "hits": hits} for kind, hits in after.items() if kind not in before]
        if lost or added:
            left = max(r.rfind(ch, 0, a) for ch in "。！？!?\n") + 1
            right = b if b and r[b - 1] in "。！？!?" else min([i for i in (r.find(ch, b) for ch in "。！？!?\n") if i != -1] + [len(r)])
            right = right + 1 if right < len(r) and r[right] in "。！？!?" else right
            out.append({"orig": "".join(texts), "rewrite": r[left:right].strip(), "lost": lost, "added": added})
    return out


CONTENT = re.compile(r"[一-龥々〆ヵヶ]{2,}|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9_.+#/-]+")


def normalize(t: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)          # 太字
    t = re.sub(r"(?m)^\s*(?:[*\-・]|\d+[.)])\s+", "", t)  # 箇条書きの印
    t = re.sub(r"(?m)^#+\s*", "", t)                 # 見出し
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def has_list(t: str) -> bool:
    return bool(re.search(r"(?m)^\s*(?:[*\-・]|\d+[.)])\s+\S", t))


def sentences(t: str):
    return [s for s in re.split(r"(?<=[。！？!?])|\n+", t) if s.strip()]


def paragraphs(t: str):
    """段落の数を数える。続いた箇条書きは1つの段落とみなす"""
    blocks, prev_list = [], False
    for line in t.split("\n"):
        if not line.strip():
            prev_list = False
            continue
        is_list = bool(re.match(r"\s*(?:[*\-・]|\d+[.)])\s+", line))
        if is_list and prev_list:
            continue
        blocks.append(line)
        prev_list = is_list
    return blocks


LOGIC = [
    ("文頭のつなぎ", re.compile(r"^(?:ただし|しかし|一方|また|さらに|つまり|そのため|したがって|だから|それでも|なお|そこで|ところが)")),
    ("主題の「も」", re.compile(r"^(?!それで)[^、。]{0,17}[^、。てでり]も、")),
    ("予告だけの文", re.compile(r"^.{0,28}(?:が|も)あります。$|次の(?:点|こと|とおり|通り)です|以下の(?:点|こと|とおり|通り)")),
    ("文頭の指示語", re.compile(r"^(?:これ|それ(?!でも|から)|こう(?:した|して|する|いう)|そう(?:した|して|する|いう)|この|その)(?!して)")),
]


def logic_points(t: str):
    pts = []
    for s in sentences(normalize(t)):
        s2 = s.strip()
        for name, pat in LOGIC:
            if pat.search(s2):
                pts.append({"kind": name, "sentence": s2})
    return pts


# ---- 文末の種類と、文書の立場 ----
# 立場は3つ。勧め = 読み手に勧める・頼む、決まり = 決まり・手順を伝える、説明 = 事実・結果・考えを伝える
STANCES = {"勧め": "勧め", "読み手に勧める": "勧め", "決まり": "決まり", "手順": "決まり", "説明": "説明", "報告": "説明", "体験": "説明"}

# 状態や性質を表す「〜ます」の語幹（動作ではないもの）
STATIVE = ("なり", "あり", "おり", "でき", "分かり", "わかり", "つながり", "変わり", "起き", "起こり", "生じ",
           "増え", "減り", "見え", "聞こえ", "残り", "続き", "終わり", "始まり", "決まり", "進み", "遅れ",
           "下回り", "上回り", "異なり", "違い", "限り", "足り", "合い", "当たり", "向き", "似", "伝わり",
           "高まり", "下がり", "上がり", "広がり", "強まり", "弱まり", "落ち", "壊れ", "崩れ", "外れ", "漏れ",
           "そろい", "揃い", "思え", "感じられ", "止まり", "消え", "困り", "迷い", "助かり")
# 可能の形（「防げます」など）。一段動詞と見分けられないので、よく出るものだけ並べる
POTENTIAL = ("防げ", "書け", "読め", "使え", "言え", "選べ", "話せ", "待て", "探せ", "直せ", "残せ", "減らせ", "増やせ",
             "守れ", "作れ", "取れ", "気づけ", "見つけられ", "続けられ", "避けられ", "変えられ", "決められ", "伝えられ")
EVAL_END = r"(?:重要|最重要|大切|大事|不可欠|肝心|肝要|欠かせません|鍵|カギ|最優先|必要)(?:です|でした|だ|である)?$"


def bare_end(s: str) -> str:
    """文末の判定に使う形。太字や記号、文末のかっこ書き（「〜」の例など）を外す"""
    t = re.sub(r"\*\*|`", "", s).strip().rstrip("。．.！!？?").strip()
    end = len(t)
    while end and t[end - 1] in "）)":
        start = end - 2
        while start >= 0 and t[start] not in "（）()":
            start -= 1
        if start < 0 or t[start] not in "（(":
            break
        end = start
        while end and t[end - 1].isspace():
            end -= 1
    return t[:end].rstrip("」』）)")


def register(s: str) -> str:
    """敬体か常体か。体言止めなどは空を返す"""
    t = bare_end(s)
    if re.search(r"(?:です|ます|ません|ました|でした|ましょう|ください|でしょう)$", t):
        return "敬体"
    if re.search(r"(?:だ|である|ではない|でない)$", t) or (re.search(r"[るうくすつぬぶむぐたい]$", t) and not re.search(r"[ァ-ヴー一-龥A-Za-z0-9]$", t)):
        return "常体"
    return ""


def ending_kind(s: str) -> str:
    t = bare_end(s)
    if not t:
        return ""
    if re.search(r"ください(?:ね)?$|(?:て|で)はいけません$|(?:て|で)はなりません$|ていただきます$|ていただけます$", t):
        return "依頼"
    if re.search(r"ましょう$|とよいです$|といいです$|をおすすめします$|をお勧めします$", t):
        return "勧め"
    if re.search(r"(?:でしょう|だろう|かもしれません|かもしれない|と思います|と考えます|と感じます|はずです|ようです|気がします)$", t):
        return "推量・考え"
    if re.search(r"(?:なければなりません|なくてはなりません|必要があります|べきです)$", t):
        return "義務"
    if re.search(EVAL_END, t):
        return "評価"
    if re.search(r"(?:ました|でした|ませんでした)$", t):
        return "過去"
    if re.search(r"(?:ます|ません)$", t):
        stem = re.sub(r"(?:ます|ません)$", "", t)
        if re.search(r"(?:て|で)い$", stem):
            return "説明（〜ています）"
        if re.search(r"(?:られ|[^しさ]れ)$", stem) or stem.endswith(STATIVE) or stem.endswith(POTENTIAL):
            return "説明（〜ます）"
        return "動作（〜します）"
    if re.search(r"です$", t):
        return "断定（〜です）"
    if re.search(r"(?:だ|である|ではない|でない)$", t):
        return "常体"
    if re.search(r"[るうくすつぬぶむぐたい]$", t) and not re.search(r"[ァ-ヴー一-龥A-Za-z0-9]$", t):
        return "常体"
    return "体言止めなど"


def ending_units(t: str, markdown: bool = False):
    """文末を見る単位。箇条書きの1項目も1文。ダッシュの前も1つの区切りとして見る。
    markdown=True のときは、コードブロック・先頭の設定部分・表の区切り行を飛ばし、表のセルは「表」として扱う"""
    out = []
    lines = t.split("\n")
    if markdown and lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
            lines = lines[end + 1:]
        except ValueError:
            pass
    in_code = False
    for line in lines:
        l = line.strip()
        if markdown and l.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not l or l.startswith("#") or l == "---":
            continue
        if l.startswith("|"):
            if not markdown or set(l) <= set("|-: "):
                continue
            where, parts_src = "表", [c.strip() for c in l.strip("|").split("|")]
        elif re.match(r"^(?:[*\-・]|\d+[.)])\s+", l):
            where, parts_src = "箇条書き", [re.sub(r"^(?:[*\-・]|\d+[.)])\s+", "", l)]
        else:
            where, parts_src = "地の文", [l]
        for src in parts_src:
            for s in re.split(r"(?<=[。！？!?])", src):
                s = s.strip()
                if not s:
                    continue
                full = bool(re.search(r"[。！？!?]$", s))
                parts = [p.strip() for p in re.split(r"[—―]{1,2}", s)]
                for n, p in enumerate(parts):
                    if not p:
                        continue
                    k = ending_kind(p)
                    last = n == len(parts) - 1
                    if not k or (not last and k == "体言止めなど"):
                        continue
                    out.append({"where": where, "sentence": p, "kind": k, "full": full or not last})
    return out


def stance_flags(t: str, stance=None, markdown: bool = False):
    rows = ending_units(t, markdown)
    act = [r for r in rows if r["kind"] == "動作（〜します）" and r["where"] != "表"]
    ask = [r for r in rows if r["kind"] in ("勧め", "依頼") and r["where"] != "表"]
    rec = [r for r in ask if r["kind"] == "勧め"]
    ev = [r for r in rows if r["kind"] == "評価" and r["where"] != "表"]
    flags = []
    if stance == "勧め":
        if act:
            flags.append(("勧めの文書に、動作を表す「〜します」がある。書き手の予定や手順・道具の説明か、読み手への依頼かを原文と文脈から確認する", act))
    elif stance == "決まり":
        if rec or ev:
            flags.append(("決まり・手順の文書に、勧めや評価の文末がある。決まりそのものなら決まりの形（〜します）にする。決まりの理由や前提を述べる文なら残す。「〜してください」はそのままでよい", rec + ev))
    elif stance == "説明":
        body = [r for r in ask if r is not rows[-1]] if rows else ask
        if body:
            flags.append(("事実・結果・考えの文書に、読み手への勧めや頼みがある（最後の1文を除く）。立場が合っているか見る", body))
    else:
        if act and ask:
            flags.append(("動作の「〜します」と、勧め・依頼が同じ文章にある。「〜します」が書き手の側の予定・決まった手順なのか、読み手にしてほしい行動なのかを見る", act + ask))
        elif act and ev:
            flags.append(("動作の「〜します」と、評価（〜が重要です など）が同じ文章にある。各文の働きと原文の強さが保たれているか確認する", act + ev))
    # 敬体と常体。文として書かれた単位（。で終わるもの、ダッシュの前）だけを数える。表と、。のない箇条書きは数えない
    full = [r for r in rows if r["where"] != "表" and r["full"]]
    jotai = [r for r in full if register(r["sentence"]) == "常体"]
    keitai = [r for r in full if register(r["sentence"]) == "敬体"]
    if jotai and len(keitai) > len(jotai):
        flags.append(("敬体の文の中に、常体の文がある。そろえるときは「する → します」と形だけで変えず、立場に合う形にする", jotai))
    elif keitai and len(jotai) > len(keitai):
        flags.append(("常体の文の中に、敬体の文がある", keitai))
    return rows, flags


class _ExactSequenceMatcher(difflib.SequenceMatcher):
    """Exact whole-input containment shortcut; otherwise use the standard matcher."""

    def find_longest_match(self, alo=0, ahi=None, blo=0, bhi=None):
        if self.isjunk is not None or self.autojunk or not isinstance(self.a, str) or not isinstance(self.b, str):
            return super().find_longest_match(alo, ahi, blo, bhi)
        a, b = self.a, self.b
        ahi = len(a) if ahi is None else ahi
        bhi = len(b) if bhi is None else bhi
        if alo != 0 or blo != 0 or ahi != len(a) or bhi != len(b):
            return super().find_longest_match(alo, ahi, blo, bhi)
        a_len, b_len = ahi - alo, bhi - blo
        if not a_len or not b_len:
            return difflib.Match(alo, blo, 0)

        # Containment attains the maximum possible size; find preserves first ties.
        if a_len <= b_len:
            j = b.find(a[alo:ahi], blo, bhi)
            if j != -1:
                return difflib.Match(alo, j, a_len)
        else:
            i = a.find(b[blo:bhi], alo, ahi)
            if i != -1:
                return difflib.Match(i, blo, b_len)

        return super().find_longest_match(alo, ahi, blo, bhi)


def ending_changes(o: str, r: str):
    """書き直しで文末の種類が変わった文。似ている元の文と組にして比べる"""
    return _ending_changes_from_units(ending_units(o), ending_units(r))


def _ending_changes_from_units(ou, ru):
    """Reuse already parsed rows within diff; keep standalone parsing unchanged."""
    # 同じ文の最初の出現を保つ。同点では元の文の順番が優先される。
    originals = OrderedDict()
    for y in ou:
        originals.setdefault(y["sentence"], y)
    postings = None
    matches = {}
    changes = []
    for x in ru:
        sentence = x["sentence"]
        if sentence not in matches:
            best, score = None, 0.0
            if sentence in originals:
                # 完全一致の類似度は1。これより高い候補は存在しない。
                best, score = originals[sentence], 1.0
            else:
                matcher = difflib.SequenceMatcher(None, "", sentence, autojunk=False)
                if postings is None:
                    postings = {}
                    for i, original in enumerate(originals):
                        for ch, n in Counter(original).items():
                            postings.setdefault(ch, []).append((i, n))
                overlaps = [0] * len(originals)
                for ch, n in Counter(sentence).items():
                    for i, original_n in postings.get(ch, ()):
                        overlaps[i] += min(n, original_n)
                rewrite_len = len(sentence)
                for i, (original, y) in enumerate(originals.items()):
                    total_len = len(original) + rewrite_len
                    length_bound = 2.0 * min(len(original), rewrite_len) / total_len if total_len else 1.0
                    if length_bound < 0.45 or length_bound <= score:
                        continue
                    overlap_bound = 2.0 * overlaps[i] / total_len if total_len else 1.0
                    if overlap_bound < 0.45 or overlap_bound <= score:
                        continue
                    matcher.set_seq1(original)
                    sc = matcher.ratio()
                    if sc > score:
                        best, score = y, sc
            matches[sentence] = best, score
        best, score = matches[sentence]
        if best and score >= 0.45 and best["kind"] != x["kind"]:
            changes.append({"orig": best["sentence"], "orig_kind": best["kind"] + ("・箇条書き" if best["where"] == "箇条書き" else ""),
                            "rewrite": x["sentence"], "rewrite_kind": x["kind"]})
    return changes


# ---- 太字が表示されるか（GitHub などの Markdown）----
# GitHub の Markdown などでは、** のすぐ内側が記号（「」（）` など）で、すぐ外側が文字だと、** を太字の印として読まず、
# ** がそのまま表示されることがある。CommonMark（記号に Unicode の P や S も入る）でも、GitHub の GFM（半角句読記号と P だけ）でも
# 公開仕様に基づく限定された区切り判定を検査し、表示全体の保証ではない。直し方の案は、かっこの内側だけを太字にする → 句読点を太字の外に出す
# → 文字に接する側に半角スペースを入れる、の順に試す。
BOLD_ASCII_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
BOLD_BRACKETS = {"「": "」", "『": "』", "（": "）", "(": ")", "【": "】", "〔": "〕", "［": "］", "[": "]",
                 "〈": "〉", "《": "》", "“": "”", "‘": "’", "＜": "＞"}


def _bold_ws(ch: str) -> bool:
    return unicode_whitespace(ch)


def _bold_punct_gfm(ch: str) -> bool:
    return ch != "" and (ch in BOLD_ASCII_PUNCT or unicodedata.category(ch).startswith("P"))


def _bold_punct_new(ch: str) -> bool:
    return ch != "" and unicodedata.category(ch)[0] in "PS"


def _bold_can_open(prev: str, nxt: str) -> bool:
    return all(not _bold_ws(nxt) and (not p(nxt) or _bold_ws(prev) or p(prev)) for p in (_bold_punct_gfm, _bold_punct_new))


def _bold_can_close(prev: str, nxt: str) -> bool:
    return all(not _bold_ws(prev) and (not p(prev) or _bold_ws(nxt) or p(nxt)) for p in (_bold_punct_gfm, _bold_punct_new))


def _bold_code_spans(text: str):
    """Inline code ranges, with escapes recognized outside code only."""
    return [(left, right) for left, right, kind in inline_protected_spans(text)
            if kind == "inline_code"]


def _bold_pairs(text: str):
    """後方互換用: テキスト内の太字ペアを返す"""
    return _bold_pairs_in_block(text)


def _direct_escape(text, position):
    start = position
    while start > 0 and text[start - 1] == "\\":
        start -= 1
    return (position - start) % 2 == 1


def _star_runs(text):
    analysis = analyze_markdown(text, skip_frontmatter=False)
    return _runs_from_masks(text, analysis["mask_spans"])


def _runs_from_masks(text, masked):
    runs = []
    mask_index = 0
    for match in re.finditer(r"\*+", text):
        position, finish = match.span()
        while position < finish:
            while mask_index < len(masked) and masked[mask_index][1] <= position:
                mask_index += 1
            if mask_index < len(masked) and masked[mask_index][0] <= position:
                position = min(finish, masked[mask_index][1])
                continue
            end = finish
            if mask_index < len(masked):
                end = min(end, masked[mask_index][0])
            if end > position:
                runs.append((position, end))
            position = end
    return runs


def _roles(text, start, end, punct):
    prev = text[start - 1] if start else ""
    nxt = text[end] if end < len(text) else ""
    can_open = not _bold_ws(nxt) and (not punct(nxt) or _bold_ws(prev) or punct(prev))
    can_close = not _bold_ws(prev) and (not punct(prev) or _bold_ws(nxt) or punct(nxt))
    return can_open, can_close


def _strong_parse(text, punct, runs=None):
    """Asterisk delimiter-stack matching with the multiple-of-three condition."""
    pairs, consumed, _ = _delimiter_parse(text, punct, runs)
    return pairs, consumed


def _delimiter_parse(text, punct, runs=None):
    """Same nearest-compatible opener, indexed by the six rule-3 classes."""
    if runs is None:
        runs = _star_runs(text)
    openers = []
    buckets = {(mod, closes): [] for mod in range(3) for closes in (False, True)}
    # cmark-gfm's published implementation shares failed-search lower bounds
    # by mod3. Modern cmark separates closers that can also open. These are
    # asterisk-emphasis profiles, not two complete Markdown renderers.
    gfm_bounds = punct is _bold_punct_gfm
    bottoms = {}
    pairs = []
    emphasis = []
    consumed = set()
    for start, end in runs:
        can_open, can_close = _roles(text, start, end, punct)
        closer = {"start": start, "head": 0, "remaining": end - start, "length": end - start,
                  "can_open": can_open, "can_close": can_close}
        while can_close and closer["remaining"]:
            opener = None
            closer_mod = closer["length"] % 3
            bottom_key = (closer_mod, None if gfm_bounds else can_open)
            bottom = bottoms.get(bottom_key, -1)
            for (mod, closes), bucket in buckets.items():
                blocked = ((can_open or closes) and (mod + closer_mod) % 3 == 0
                           and (mod != 0 or closer_mod != 0))
                if bucket and not blocked and bucket[-1]["start"] >= bottom:
                    candidate = bucket[-1]
                    if opener is None or candidate["stack_index"] > opener["stack_index"]:
                        opener = candidate
            if opener is None:
                bottoms[bottom_key] = start
                break
            used = 2 if opener["remaining"] >= 2 and closer["remaining"] >= 2 else 1
            left = opener["start"] + opener["head"] + opener["remaining"] - used
            right = closer["start"] + closer["head"]
            if used == 2:
                pairs.append((left, right))
            emphasis.append((left, right, used))
            consumed.update(range(left, left + used))
            consumed.update(range(right, right + used))
            # An opener removed from the ordered stack is removed from its
            # class stack exactly once; remaining opener indices never move.
            while openers[-1] is not opener:
                removed = openers.pop()
                buckets[(removed["length"] % 3, removed["can_close"])].pop()
            buckets[(opener["length"] % 3, opener["can_close"])].pop()
            opener["remaining"] -= used
            closer["head"] += used
            closer["remaining"] -= used
            if not opener["remaining"]:
                openers.pop()
            else:
                buckets[(opener["length"] % 3, opener["can_close"])].append(opener)
        if can_open and closer["remaining"]:
            closer["stack_index"] = len(openers)
            openers.append(closer)
            buckets[(closer["length"] % 3, closer["can_close"])].append(closer)
    return pairs, consumed, emphasis


def _star_extent(text, position):
    left = position
    while left > 0 and text[left - 1] == "*" and not _direct_escape(text, left - 1):
        left -= 1
    right = position
    while right < len(text) and text[right] == "*":
        right += 1
    return left, right


def _local_pair_ok(text, i, j):
    left_start, left_end = _star_extent(text, i)
    right_start, right_end = _star_extent(text, j)
    for punct in (_bold_punct_gfm, _bold_punct_new):
        left_open, left_close = _roles(text, left_start, left_end, punct)
        right_open, right_close = _roles(text, right_start, right_end, punct)
        if not left_open or not right_close:
            return False
        left_n, right_n = left_end - left_start, right_end - right_start
        if ((right_open or left_close) and (left_n + right_n) % 3 == 0
                and (left_n % 3 != 0 or right_n % 3 != 0)):
            return False
    return True


def _bold_pairs_in_block(block_text: str):
    if "**" not in block_text:
        return []
    runs = _star_runs(block_text)
    return _bold_pairs_from_runs(block_text, runs)


def _bold_pairs_from_runs(block_text, runs):
    return _bold_scan_runs(block_text, runs)[0]


def _bold_scan_runs(block_text, runs):
    return _bold_scan_context(block_text, runs)[:3]


def _bold_scan_context(block_text, runs):
    gfm, used_gfm, emphasis_gfm = _delimiter_parse(block_text, _bold_punct_gfm, runs)
    common, used_common, emphasis_common = _delimiter_parse(block_text, _bold_punct_new, runs)
    pairs = set(gfm + common)
    used = used_gfm | used_common
    # Invalid delimiter pairs can shift a later real match. Diagnose the
    # directly bad adjacent pair, not every secondary symptom of that shift.
    next_double = [None] * len(runs)
    later = None
    for index in range(len(runs) - 1, -1, -1):
        next_double[index] = later
        if runs[index][1] - runs[index][0] >= 2:
            later = index
    for index, (start, end) in enumerate(runs):
        if end - start < 2 or any(position in used for position in range(start, end)):
            continue
        later = next_double[index]
        if later is None:
            continue
        later_start, later_end = runs[later]
        if (end < later_start and _bold_ws(block_text[end])
                and any(position in used for position in range(later_start, later_end))):
            continue
        if not _local_pair_ok(block_text, start, later_start):
            pairs.add((start, later_start))
    return (sorted(pairs), set(gfm), set(common),
            {"runs": runs, "gfm": emphasis_gfm, "common": emphasis_common, "opaque": None})


def _bold_pair_ok(text: str, i: int, j: int) -> bool:
    # Backward-compatible local predicate; main findings use actual matchsets.
    return _local_pair_ok(text, i, j)


def _bold_close_of(s: str) -> int:
    """s の先頭のかっこに対応する閉じかっこの位置（なければ -1）"""
    o, c, depth = s[0], BOLD_BRACKETS[s[0]], 0
    for k, x in enumerate(s):
        if x == o:
            depth += 1
        elif x == c:
            depth -= 1
            if depth == 0:
                return k
    return -1


def _bold_fix(text: str, i: int, j: int, k: int):
    """k 番目の太字（i と j の **）の直し方の案。(直したあとの部分, 直し方) を返す"""
    return _bold_fix_checked(text, i, j, k, known_pair=False)


def _bold_fix_checked(text: str, i: int, j: int, k: int, known_pair: bool):
    """Verify the intended repaired pair under both renderers; do not trust ordinal alone."""
    return _bold_fix_with_context(text, i, j, k, known_pair, _repair_context(text))


def _repair_context(text, runs=None):
    if runs is None:
        runs = _star_runs(text)
    return {"runs": runs,
            "gfm": _delimiter_parse(text, _bold_punct_gfm, runs)[2],
            "common": _delimiter_parse(text, _bold_punct_new, runs)[2],
            "opaque": [(kind, text[left:right])
                       for left, right, kind in inline_protected_spans(text)]}


def _preserves_other_emphasis(original, repaired, i, j, delta):
    """Every existing outside/enclosing delimiter pair keeps its source match."""
    repaired = set(repaired)
    for left, right, width in original:
        if (left, right, width) == (i, j, 2):
            continue  # The reported target may work in only one profile.
        if i <= left < j + 2 or i <= right < j + 2:
            return False  # A crossing/inner match is too ambiguous to rewrite.
        moved_left = left + (delta if left >= j + 2 else 0)
        moved_right = right + (delta if right >= j + 2 else 0)
        if (moved_left, moved_right, width) not in repaired:
            return False
    return True


def _bold_fix_with_context(text, i, j, k, known_pair, context):
    """Only a proved target repair is suggested; ambiguous star runs stay manual."""
    open_start, open_end = _star_extent(text, i)
    close_start, close_end = _star_extent(text, j)
    if open_end - open_start != 2 or close_end - close_start != 2:
        return None, "手で直す"
    if (i, i + 2) not in context["runs"] or (j, j + 2) not in context["runs"]:
        return None, "手で直す"
    inner = text[i + 2:j]
    if "*" in inner:
        return None, "手で直す"
    # In a multi-run paragraph a whitespace-only flanking symptom does not
    # identify the intended pair. Avoid both unsafe guesswork and N reparses.
    if len(context["runs"]) > 2 and (_bold_ws(inner[:1]) or _bold_ws(inner[-1:])):
        return None, "手で直す"
    # Any existing pair touching these delimiter characters must be the
    # reported target itself. Otherwise preservation necessarily fails, no
    # matter which replacement is tried. Index this once for repeated cases.
    if "delimiter_matches" not in context:
        matches = {}
        for pair in context["gfm"] + context["common"]:
            left, right, width = pair
            for position in tuple(range(left, left + width)) + tuple(range(right, right + width)):
                matches.setdefault(position, set()).add(pair)
        context["delimiter_matches"] = matches
    target_pair = (i, j, 2)
    if any(pair != target_pair for position in (i, i + 1, j, j + 1)
           for pair in context["delimiter_matches"].get(position, ())):
        return None, "手で直す"
    if context["opaque"] is None:
        context["opaque"] = [(kind, text[left:right])
                             for left, right, kind in inline_protected_spans(text)]
    tries = []
    if len(inner) >= 3 and inner[0] in BOLD_BRACKETS and _bold_close_of(inner) == len(inner) - 1:
        tries.append((inner[0] + "**" + inner[1:-1] + "**" + inner[-1], "かっこの内側だけを太字にする"))
    if len(inner) >= 2 and inner[-1] in "。、．，！？!?":
        tries.append(("**" + inner[:-1] + "**" + inner[-1], "句読点を太字の外に出す"))
    ch = lambda position: text[position] if 0 <= position < len(text) else ""
    body_start, body_end = 0, len(inner)
    while body_start < body_end and _bold_ws(inner[body_start]): body_start += 1
    while body_end > body_start and _bold_ws(inner[body_end - 1]): body_end -= 1
    body = inner[body_start:body_end]
    left = "" if _bold_can_open(ch(i - 1), body[:1]) else " "
    right = "" if _bold_can_close(body[-1:], ch(j + 2)) else " "
    tries.append((left + "**" + body + "**" + right, "太字の内側の空白を取る" if body != inner and not (left or right)
                  else "文字に接する側に半角スペースを入れる"))
    for middle, how in tries:
        candidate = text[:i] + middle + text[j + 2:]
        target = (i + middle.find("**"), i + middle.rfind("**"))
        runs = _star_runs(candidate)
        opaque = [(kind, candidate[left:right])
                  for left, right, kind in inline_protected_spans(candidate)]
        if opaque != context["opaque"]:
            continue
        # With exactly two visible 2-star runs, local flanking is sufficient:
        # no competing delimiter exists, and 2+2 cannot violate rule 3. There
        # is no other source emphasis to change. This proof is deliberately
        # narrower than the retired old known_pair performance shortcut.
        if len(runs) == len(context["runs"]) == 2:
            if (runs == [(target[0], target[0] + 2), (target[1], target[1] + 2)]
                    and _local_pair_ok(candidate, *target)):
                return middle, how
            continue
        gfm, _, emphasis_gfm = _delimiter_parse(candidate, _bold_punct_gfm, runs)
        common, _, emphasis_common = _delimiter_parse(candidate, _bold_punct_new, runs)
        delta = len(candidate) - len(text)
        if (target in gfm and target in common
                and _preserves_other_emphasis(context["gfm"], emphasis_gfm, i, j, delta)
                and _preserves_other_emphasis(context["common"], emphasis_common, i, j, delta)):
            return middle, how
    return None, "手で直す"


def _line_containers(line: str):
    """行のコンテナ（リストマーカー、引用の深さ）と、内部のコンテンツを簡易解析する"""
    is_list = False
    m_list = re.match(r"^\s{0,3}(?:[*+-]|\d+[.)])\s+", line)
    if m_list:
        is_list = True
        rem = line[m_list.end():]
    else:
        rem = line

    depth = 0
    p = 0
    while True:
        m_sp = re.match(r"^\s{0,3}", rem[p:])
        if m_sp:
            p += m_sp.end()
        if p < len(rem) and rem[p] == ">":
            depth += 1
            p += 1
            if p < len(rem) and rem[p] == " ":
                p += 1
        else:
            break
    content = rem[p:]
    return is_list, depth, content


def bold_problems(text: str, skip_frontmatter: bool = True):
    """Inspect visible leaf blocks; code, destinations and HTML atoms are protected."""
    if "**" not in text:
        return []
    analysis = analyze_markdown(text, skip_frontmatter)
    return _bold_problems_with_analysis(text, analysis)


def _bold_problems_with_analysis(text, analysis):
    """Internal reuse for the combined lint; preserve the public two-arg API."""
    if "**" not in text:
        return []
    out = []
    masks = analysis["mask_spans"]
    mask_index = 0
    for block in analysis["blocks"]:
        if block["kind"] in ("code", "frontmatter", "html_block", "reference_definition"):
            continue
        rows = block["lines"]
        begin = rows[0]["start"]
        finish = rows[-1]["start"] + len(rows[-1]["raw"])
        block_text = text[begin:finish]
        if "**" not in block_text:
            continue
        offsets = [row["start"] - begin for row in rows]
        while mask_index < len(masks) and masks[mask_index][1] <= begin:
            mask_index += 1
        block_masks = []
        for index in range(mask_index, len(masks)):
            left, right = masks[index]
            if left >= finish:
                break
            block_masks.append((max(left, begin) - begin, min(right, finish) - begin))
        runs = _runs_from_masks(block_text, block_masks)
        pairs, gfm_pairs, common_pairs, context = _bold_scan_context(block_text, runs)
        for ordinal, (i, j) in enumerate(pairs):
            if (i, j) in gfm_pairs and (i, j) in common_pairs:
                continue
            middle, how = _bold_fix_with_context(block_text, i, j, ordinal, True, context)
            pre, post = block_text[max(0, i - 4):i], block_text[j + 2:j + 6]
            found = pre + _bold_short(block_text[i:j + 2]) + post
            suggest = pre + _bold_short(middle) + post if middle is not None else ""
            line_index = bisect_right(offsets, i) - 1
            out.append({"line": rows[line_index]["line"], "found": found, "suggest": suggest, "how": how})
    return out


def _bold_short(s: str) -> str:
    """長い太字は、直すところ（両端）だけを見せる"""
    return s if len(s) <= 30 else s[:12] + "…" + s[-12:]


def count(pat: str, t: str) -> int:
    return len(re.findall(pat, t))


def context(t: str, i: int, j: int, width: int = 18) -> str:
    a, b = max(0, i - width), min(len(t), j + width)
    return t[a:i] + "［" + t[i:j] + "］" + t[j:b]


def diff(orig_raw: str, rw_raw: str, stance=None) -> dict:
    o, r = normalize(orig_raw), normalize(rw_raw)
    out = {"markers": [], "new_words": [], "lost_words": [], "structure": [], "spans": [], "logic": logic_points(rw_raw),
           "bold": bold_problems(rw_raw)}
    rw_units, flags = stance_flags(rw_raw, stance)
    orig_units, orig_flags = stance_flags(orig_raw, stance)
    out["endings"] = {"stance": stance, "changes": _ending_changes_from_units(orig_units, rw_units),
                      "flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in flags],
                      "orig_flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in orig_flags]}
    opcodes = _ExactSequenceMatcher(None, o, r, autojunk=False).get_opcodes() if o != r else []
    out["type_changes"] = _type_changes(o, r, opcodes)

    # 1. 種類ごとの数の増減
    for name, pat in MARKERS.items():
        a, b = count(pat, o), count(pat, r)
        if a != b:
            hits_r = [m.group(0) for m in re.finditer(pat, r)]
            hits_o = [m.group(0) for m in re.finditer(pat, o)]
            out["markers"].append({"kind": name, "orig": a, "rewrite": b,
                                   "orig_hits": hits_o, "rewrite_hits": hits_r})

    # 2. 元にない語・消えた語（語の単位で、文のどこかに出てくるかを見る）
    o_words = set(CONTENT.findall(o))
    r_words = set(CONTENT.findall(r))
    out["new_words"] = sorted(w for w in r_words if w not in o)
    out["lost_words"] = sorted(w for w in o_words if w not in r)

    # 3. 構造
    if has_list(orig_raw) and not has_list(rw_raw):
        out["structure"].append("箇条書きを地の文にした。各項目の文末（指示・説明・評価）が元と同じか見る")
    po, pr = len(paragraphs(orig_raw)), len(paragraphs(rw_raw))
    if pr < po:
        out["structure"].append(f"段落をまとめた（{po} → {pr}）。まとめた段落の話題が1つか見る")
    if len(sentences(r)) != len(sentences(o)):
        out["structure"].append(f"文の数が変わった（{len(sentences(o))} → {len(sentences(r))}）")

    # 4. 足した部分（文字単位の差分）。種類か新しい語に当たるものだけ残す
    if o != r:
        for tag, i1, i2, j1, j2 in opcodes:
            if tag in ("insert", "replace"):
                seg = r[j1:j2]
                kinds = [n for n, p in MARKERS.items() if re.search(p, r[max(0, j1 - 3):j2 + 3])]
                words = [w for w in CONTENT.findall(seg) if w not in o]
                if kinds or words:
                    out["spans"].append({"added": seg, "was": o[i1:i2], "kinds": kinds, "new_words": words,
                                         "where": context(r, j1, j2)})
    return out


def bold_head(where: str = "") -> str:
    return f"■ 太字にならない書き方（{where}GitHub などで ** がそのまま表示されることがある。表示可否と案の範囲を確認して直す）"


def bold_lines(problems):
    return [f"- {p['line']}行目: {p['found']} → {p['suggest'] or '（手で直す）'}（{p['how']}）" for p in problems]


def report(d: dict) -> str:
    lines = []
    if d["markers"]:
        lines.append("■ 言い回しの種類の増減（意味が変わりやすいところ）")
        for m in d["markers"]:
            lines.append(f"- {m['kind']}: {m['orig']} → {m['rewrite']}（元: {'、'.join(m['orig_hits']) or 'なし'}／後: {'、'.join(m['rewrite_hits']) or 'なし'}）")
    if d["new_words"]:
        lines.append("■ 元の文にない語: " + "、".join(d["new_words"]))
    if d["lost_words"]:
        lines.append("■ 消えた語: " + "、".join(d["lost_words"]))
    for s in d["structure"]:
        lines.append("■ " + s)
    if d.get("logic"):
        lines.append("■ つながりを確かめる場所（書き直した文。何と何をつないでいるか言えるか）")
        for p in d["logic"]:
            sent = p["sentence"] if len(p["sentence"]) <= 44 else p["sentence"][:44] + "…"
            lines.append(f"- {p['kind']}: {sent}")
    e = d.get("endings") or {}
    if e.get("changes"):
        lines.append("■ 文末の種類が変わった文（立場に合う向きか見る）")
        for c in e["changes"]:
            sent = c["rewrite"] if len(c["rewrite"]) <= 44 else c["rewrite"][:44] + "…"
            lines.append(f"- {c['orig_kind']} → {c['rewrite_kind']}: {sent}")
    if d.get("type_changes"):
        lines.append("■ 文の種類の印が変わった文（伝聞・推量・意見・例え・依頼が、元の文と同じか見る）")
        for c in d["type_changes"]:
            lines.append(f"- 元: {c['orig'] if len(c['orig']) <= 60 else c['orig'][:60] + '…'}")
            lines.append(f"  後: {c['rewrite'] if len(c['rewrite']) <= 60 else c['rewrite'][:60] + '…'}")
            for label, side in (("消えた印", "lost"), ("増えた印", "added")):
                if c[side]:
                    lines.append(f"  {label}: " + "、".join(f"{m['kind']}（{'、'.join(m['hits'])}）" for m in c[side]))
    if e.get("flags"):
        head = f"■ 文末の立場（{e['stance']}の文書として見た）" if e.get("stance") else "■ 文末の立場が混ざっている候補（立場を決めてから見る）"
        lines.append(head)
        for f in e["flags"]:
            lines.append(f"- {f['note']}")
            for s in f["sentences"]:
                lines.append(f"  ・{s if len(s) <= 44 else s[:44] + '…'}")
    if d.get("bold"):
        lines.append(bold_head("書き直した文。"))
        lines.extend(bold_lines(d["bold"]))
    return "\n".join(lines) if lines else "（候補なし）"


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stance = None
    for a in sys.argv[1:]:
        if a.startswith("--stance="):
            stance = STANCES.get(a.split("=", 1)[1])
    if "--endings" in sys.argv and args:
        # 1つのファイルの文末だけを見る（マークダウンのコードブロックや表の区切りは飛ばす）
        t = read_text(args[0])
        rows, flags = stance_flags(t, stance, markdown=True)
        from collections import Counter
        c = Counter(r["kind"] for r in rows if r["where"] != "表")
        print("■ 文末の種類（表を除く）: " + "、".join(f"{k} {v}" for k, v in c.most_common()))
        for n, fr in flags:
            print(f"■ {n}")
            for r in fr:
                print(f"  ・{r['sentence'] if len(r['sentence']) <= 60 else r['sentence'][:60] + '…'}")
        bp = bold_problems(t)
        if bp:
            print(bold_head())
            print("\n".join(bold_lines(bp)))
        sys.exit(0)
    if len(args) < 2:
        print("使い方: python3 yomiyasu_diff.py 元の文.txt 書き直した文.txt [--stance=勧め|決まり|説明] [--json]")
        print("　　　  python3 yomiyasu_diff.py --endings ファイル [--stance=勧め|決まり|説明]")
        sys.exit(1)
    o = read_text(args[0])
    r = read_text(args[1])
    d = diff(o, r, stance)
    print(json.dumps(d, ensure_ascii=True, indent=1) if "--json" in sys.argv else report(d))
