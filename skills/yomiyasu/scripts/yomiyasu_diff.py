#!/usr/bin/env python3
"""
yomiyasu_diff.py - 元の文と書き直した文を比べ、変わった箇所をすべて出し、意味が変わる恐れと規則の見直し候補を挙げる。

標準ライブラリだけで動く。モデルは呼ばない。外へ通信しない。
出すものは3つ。
  1. 全文差分: 変わった箇所を省略せずに出す（太字、見出しの段、空白、空行、字下げ、コード、引用、表の変化も残す）。
     変わった箇所を示すだけで、意味が同じだという証明ではない。
  2. 意味が変わる恐れ: 数値、否定、主語と目的語の入れ替え、問いと平叙、文の種類の印、コード・URL・引用など変えない箇所の変化。
     どれも確かめる場所で、意味が変わったという判定ではない。
  3. 規則の見直し候補（v1.1.2 からの9つの点検）:
     文末や言い回しの種類の数の増減、元の文にない語と消えた語、箇条書きや段落の変化、つながりを確かめる場所、
     文末の種類と文書の立場、文の種類の印、太字にならない書き方と直し方の案。
意味が同じかどうか、つながりが合っているか、文末が立場に合っているかの最終判断は、この結果を見たモデル（または人）がする。
"""
__version__ = "2.0.0"

import os
import re
import sys
import json
import argparse
import difflib
import traceback
import unicodedata
from bisect import bisect_left, bisect_right
_VISIBILITY_NAMES = ("analyze_markdown", "inline_protected_spans", "unicode_whitespace", "decode_source")
try:
    try:
        if __package__:
            from .markdown_visibility import analyze_markdown, inline_protected_spans, unicode_whitespace, decode_source
        else:
            from markdown_visibility import analyze_markdown, inline_protected_spans, unicode_whitespace, decode_source
    except SyntaxError as error:
        # 隣の markdown_visibility.py が壊れている。ほかの読めないときと同じく ImportError にする（スクリプトでは終了コード3）。
        raise ImportError(
            "{} を読めません（SyntaxError: {}）。yomiyasu_diff.py と同じ版の markdown_visibility.py を置いてください。".format(
                error.filename or "markdown_visibility.py", error.msg),
            name=(__package__ + ".markdown_visibility") if __package__ else "markdown_visibility") from error
    except ImportError as error:
        # spec_from_file_location で直接読まれると、このファイルのフォルダが sys.path にないことがある。
        # 別の版の markdown_visibility がすでに読まれていて、要る名前がないこともある。
        # どちらのときも、このファイルの隣にある markdown_visibility.py を読む。
        expected = (__package__ + ".markdown_visibility") if __package__ else "markdown_visibility"
        parent = __package__.split(".")[0] if __package__ else "markdown_visibility"
        if error.name not in (expected, parent):
            raise
        import importlib.util
        from pathlib import Path
        _visibility_spec = importlib.util.spec_from_file_location(
            "_yomiyasu_markdown_visibility", Path(__file__).with_name("markdown_visibility.py"))
        _visibility_module = importlib.util.module_from_spec(_visibility_spec)
        try:
            _visibility_spec.loader.exec_module(_visibility_module)
        except (OSError, SyntaxError) as _load_error:
            # 隣に markdown_visibility.py がない、または壊れている。ImportError にして、スクリプトでは終了コード3にする
            # （OSError と SyntaxError のままだと外の except で受けられず、トレースバックと終了コード1になる）。
            raise ImportError(
                "{} を読めません（{}: {}）。yomiyasu_diff.py と同じ版の markdown_visibility.py を同じフォルダに置いてください。".format(
                    _visibility_spec.origin, type(_load_error).__name__, _load_error),
                name=expected) from _load_error
        _missing = [name for name in _VISIBILITY_NAMES if not hasattr(_visibility_module, name)]
        if _missing:
            raise ImportError(
                "{} に {} がありません。yomiyasu_diff.py と同じ版の markdown_visibility.py を置いてください。".format(
                    _visibility_spec.origin, "、".join(_missing)),
                name=expected)
        analyze_markdown = _visibility_module.analyze_markdown
        inline_protected_spans = _visibility_module.inline_protected_spans
        unicode_whitespace = _visibility_module.unicode_whitespace
        decode_source = _visibility_module.decode_source
except ImportError as _import_error:
    # スクリプトとして動かしたときは、main() が内部エラー（終了コード3）として出す。
    # 終了コード1は --fail-on の条件に当たったときだけに使う。
    # モジュールとして読むときは、そのまま ImportError を出す。
    if __name__ != "__main__":
        raise
    _IMPORT_ERROR = _import_error
else:
    _IMPORT_ERROR = None
from collections import Counter, OrderedDict


# --json の出力の形の版。キーを足すだけなら上げない。キーの意味や型を変えたときに上げる。
# v1.1.2 までの形（9キーだけ）を1とみなす。
DIFF_FORMAT_VERSION = 2
# 資料との照合（ground()。yomiyasu_check.py が使う）の出力の形の版。
MATERIALS_FORMAT_VERSION = 1

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
           r"(?:(?:だ|です|でした|だった|で(?=、))(?=[。、！!よね]|$)|な(?=の(?:で|に|だ|です)))"
           r"|とされ(?<!落とされ)(?<!必要とされ)(?:る|ている|ています|ており|た|ます|ました|てきた)"
           r"|という(?=[。！!]|が、|$)|といいます(?<=[るうくすつぬぶむぐただ]といいます)(?=[。！!]|$)|とのこと(?<!あとのこと)(?<!後とのこと)"
           r"|によ(?<!場合によ)(?:ると|れば)|と(?:言|い)われ(?:る|ている|ています|ており|た|ます|ました|てきた)"
           r"|と聞(?<!かと聞)(?:いた|いて(?:いる|います|おり)|きました)"),
    ("推量", r"らし(?<=[るうくすつぬぶむぐいた]らし)(?:い|かった|く(?=、))" + _END
           # 名詞のあとの「らしい」は、文の終わりにあるときだけ推量と数える（「春らしい陽気」「素晴らしい」は除く）。
           + r"|らし(?<!素晴らし)(?<!すばらし)(?<!めずらし)(?<!わざとらし)(?<!可愛らし)(?<!かわいらし)(?<!憎らし)(?<!馬鹿らし)"
             r"(?<!ばからし)(?<!男らし)(?<!女らし)(?<!子供らし)(?<!子どもらし)(?<!いやらし)(?<!汚らし)(?<!春らし)(?<!夏らし)(?<!秋らし)"
             r"(?<!冬らし)(?<!彼らし)"
             # 「人間らしいが」「自分らしいけど」のような典型の言い方は、文末でないときだけ除く（「犯人は学生らしい。」は推量）。
             r"(?:い(?=[。！!]|です|でした|$|(?<!人間らしい)(?<!自分らしい)(?<!大人らしい)(?<!プロらしい)(?<!学生らしい)(?:が(?!ん)|けど|けれど))"
             r"|かった(?=[。！!]|です|でした|$|が(?!ん)|けど|けれど))"
           + r"|よう(?<!次のよう)(?<!以下のよう)(?<!下記のよう)(?<!上記のよう)(?<!左記のよう)(?<!このよう)(?<!そのよう)(?<!あのよう)(?<!どのよう)"
             r"(?:(?:だ|です|でした|だった|である|であった|で(?=、))" + _END + r"|な(?=の(?:で|に|だ|です)))"
           + r"|みたい(?:(?:だ|です|でした|だった)(?=[。！!よね]|$)|な(?=の(?:で|に|だ|です)))"
           r"|かも(?:しれ|知れ)(?:ない|ません|ず)|可能性があ(?:る|ります|った|りました)"
           r"|だろう(?<!でだろう)(?!か)|であろう|でしょう(?!か)|ではない(?:でしょう|だろう)か|はず(?:だ|です|で|でした|だった)"
           r"|と(?:見|み)られ(?:る|ている|ています|ており|た|ます)|と(?:思|おも)われ(?:る|ます|た)|と考えられ(?:る|ます|た)"),
    ("意見", r"と(?:(?:私|僕|筆者|我々|われわれ|当社|弊社|私たち)は)?(?:思|おも)(?:う|い(?:ます|ました|(?=、))|った|って(?:いる|います|いた|いました|おり))"
           r"|と(?:(?:私|僕|筆者|我々|われわれ|当社|弊社|私たち)は)?(?:考え|感じ)(?:る(?!と)|ます|ました|た|て(?:いる|います|いた|いました|おり)"
           # 「1日100件と考え、」のような数の見積もりの仮定は、連用の形のときだけ除く。
           r"|(?<![0-9０-９][件人円個回倍割%％]と考え)(?<![0-9０-９][件人円個回倍割%％]と感じ)(?=、))"
           r"|ように(?:思|感じ)(?:う|います|いました|られ)"),
    ("例え", r"まるで|あたかも|さながら|(?:ごと|如)(?<!前述のごと)(?<!上記のごと)(?<!周知のごと)(?<!以下のごと)(?<!次のごと)"
           r"(?<!前述の如)(?<!上記の如)(?<!周知の如)(?<!以下の如)(?<!次の如)[くき]"),
    ("依頼・決まり", r"(?:て|で)(?:ください|下さい)|を(?:ください|下さい)|(?:ご|お)[一-龥ぁ-んァ-ヴー]{1,8}(?:ください|下さい)"
                 r"|お願い(?<!よろしくお願い)(?<!宜しくお願い)(?:します|いたします|致します|申し上げます|できますか|できますでしょうか)"
                 r"|て(?:いただけ|もらえ)(?:ますか|ませんか)|てほしい|てもらいたい|ていただきたい"
                 r"|べき(?<!しかるべき)(?<!然るべき)(?<!驚くべき)(?<!恐るべき)(?<!来るべき)(?<!特筆すべき)(?<!注目すべき)(?!乗)"
                 r"|なければ(?:ならない|なりません|ならず|いけない|いけません)|なくては(?:ならない|なりません|ならず|いけない|いけません)"
                 r"|ないといけ(?:ない|ません)|(?:て|で)は(?:いけ|なら)(?:ない|ません)|ねばなら(?:ない|ず)"
                 r"|必要(?<!不必要)(?:があ(?:る|ります|り(?=、))|(?:です|だ)(?=[。！!]|$)"
                 r"|[にと]な(?:る(?!まで)|ります|り(?=、)|った(?!ら(?!し))|りました))"),
)
TYPE_MARKERS = OrderedDict((kind, re.compile(pattern, re.M)) for kind, pattern in _TYPE_PATTERNS)
# 種類ごとに、印の正規表現が当たるために必ず含まれる文字列。どれも含まない文章では、その種類の正規表現を当てない。
_TYPE_LITERALS = {
    "伝聞": ("そう", "とされ", "という", "といいます", "とのこと", "によると", "によれば", "われ", "と聞"),
    "推量": ("らし", "よう", "みたい", "かも", "可能性", "だろう", "であろう", "でしょう", "はず", "られ", "われ"),
    "意見": ("と思", "とおも", "と考え", "と感じ", "は思", "はおも", "は考え", "は感じ", "ように思", "ように感じ"),
    "例え": ("まるで", "あたかも", "さながら", "ごと", "如"),
    "依頼・決まり": ("ください", "下さい", "お願い", "いただけ", "もらえ", "ほしい", "もらいた", "いただきた", "べき", "なければ",
                 "なくては", "ないといけ", "はいけ", "はなら", "ねばなら", "必要"),
}
# 「まるで〜のようだ」の「よう」「みたい」は、推量ではなく例えの印として数える。
# 対にするのは、同じ文の中で「まるで」「あたかも」「さながら」のあとに最初に出てくる1つだけ。
_SIMILE_HEADS = ("まるで", "あたかも", "さながら")
_SIMILE_LIKE = re.compile(r"(?:よう|みたい)(?:であった|である|だった|でした|です|だ|な|に|で)?")
_STOPS = "。！？!?\n"
_STOP = re.compile("[" + _STOPS + "]")
# 文の中身の文字数を数えるときに除く文字（句読点・かっこ・空白）
_NOT_BODY = set("。、，！？!?「」『』（）() \n\u3000")
_SENTENCE_PIECE = re.compile(r"[^。！？!?\n]+[。！？!?]*[」』）)]*")


def _mark_positions(text: str):
    """文章全体に印の正規表現を1回ずつ当て、(開始位置, 種類, 印) を位置の順に返す。"""
    found = [(m.start(), kind, m.group(0)) for kind, pattern in TYPE_MARKERS.items()
             if any(literal in text for literal in _TYPE_LITERALS[kind]) for m in pattern.finditer(text)]
    heads = [(start, hit) for start, kind, hit in found if kind == "例え" and hit in _SIMILE_HEADS]
    if heads:
        guesses = {start: i for i, (start, kind, _) in enumerate(found) if kind == "推量"}
        paired = set()
        for start, hit in heads:
            stop = _STOP.search(text, start)
            like = _SIMILE_LIKE.search(text, start + len(hit), stop.start() if stop else len(text))
            if like and like.start() not in paired:
                paired.add(like.start())
                # 推量として拾った「ようだ」なら、その印のまま例えに移す。意見の「ように思う」などはそのまま残し、例えの印を別に足す。
                i = guesses.get(like.start())
                if i is None:
                    found.append((like.start(), "例え", like.group(0)))
                else:
                    found[i] = (like.start(), "例え", found[i][2])
    found.sort(key=lambda item: item[0])
    return found


def _marks_in(positions, spans):
    """範囲（開始, 終了）の中から始まる印を {種類: [印, ...]} にまとめる。"""
    keys = [item[0] for item in positions]
    marks = OrderedDict()
    for start, end in spans:
        for _, kind, hit in positions[bisect_left(keys, start):bisect_left(keys, end)]:
            hits = marks.setdefault(kind, [])
            if hit not in hits:
                hits.append(hit)
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


def _slide_to_sentence_edges(opcodes, o: str, r: str):
    """文字単位の対応では、足した文や消した文が文の境目からずれることがある。
    句点1文字ぶん前にずれた「。足した文」や、次の文と同じ書き出しの分だけ後ろにずれた「消した文の後半。次の文の書き出し」の形である。
    前後の一致と同じ文字の分だけずらせるときは、句点や改行の直後から始まる位置に、ずらす量の少ないほうへずらす。"""
    ops = [list(op) for op in opcodes]
    for k in range(1, len(ops) - 1):
        tag, prev, nxt = ops[k][0], ops[k - 1], ops[k + 1]
        if tag not in ("insert", "delete") or prev[0] != "equal" or nxt[0] != "equal":
            continue
        if tag == "insert":
            text, a, b, left, right = r, ops[k][3], ops[k][4], prev[4] - prev[3], nxt[4] - nxt[3]
        else:
            text, a, b, left, right = o, ops[k][1], ops[k][2], prev[2] - prev[1], nxt[2] - nxt[1]
        if text[a - 1] in _STOPS:
            continue
        shifts = []
        step = 0
        while step < min(b - a, right - 1) and text[a + step] == text[b + step]:
            step += 1
            if text[a + step - 1] in _STOPS:
                shifts.append(step)
                break
        step = 0
        while step < min(b - a, left - 1) and text[a - 1 - step] == text[b - 1 - step]:
            step += 1
            if text[a - step - 1] in _STOPS:
                shifts.append(-step)
                break
        if shifts:
            shift = min(shifts, key=abs)
            prev[2] += shift
            prev[4] += shift
            ops[k][1:] = [ops[k][1] + shift, ops[k][2] + shift, ops[k][3] + shift, ops[k][4] + shift]
            nxt[1] += shift
            nxt[3] += shift
    return [tuple(op) for op in ops]


def _bigrams(text: str):
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _type_changes(o: str, r: str, opcodes):
    """元の各文が、文字単位の対応で書き直した文章のどの範囲に当たるかをたどり、範囲ごとに印を比べる。
    文を分けても、つないでも、範囲の中で比べるので、移っただけの印は変化として出ない。
    範囲が重なる元の文はまとめて比べる。丸ごと消えた文は比べない。丸ごと移した文は同じ文を探し、
    移したうえで書き換えた文は、字面の近い文を書き直した文章から探して比べる。"""
    if not opcodes:
        return []
    opcodes = _slide_to_sentence_edges(opcodes, o, r)
    starts = [op[1] for op in opcodes]

    def bare(op):
        """句点も改行も含まない挿入。文の頭や、句点のない文の末尾に足した語句として、その文に含める。"""
        return op[0] == "insert" and not any(ch in _STOPS for ch in r[op[3]:op[4]])

    def map_start(i):
        k = max(0, bisect_right(starts, i) - 1)
        tag, i1, i2, j1, j2 = opcodes[k]
        if i1 == i and k and opcodes[k - 1][1] == i and bare(opcodes[k - 1]):
            return opcodes[k - 1][3]
        if tag == "equal":
            return j1 + min(i - i1, j2 - j1)
        return j2 if tag == "insert" else j1

    def map_end(e):
        k = bisect_left(starts, e)
        if k < len(opcodes) and opcodes[k][1] == e and o[e - 1] not in _STOPS and bare(opcodes[k]):
            return opcodes[k][4]
        tag, i1, i2, j1, j2 = opcodes[max(0, k - 1)]
        return j1 + min(e - i1, j2 - j1) if tag == "equal" else j2

    def aligned(i, j):
        """元の [i, j) のうち、書き直した文章と対応する文字の数。句読点・かっこ・空白は数えない。
        置き換えの部分は、置き換え先が短いほど少なく数える（消した文を含む長い部分が、短い語句に置き換わった場合など）。"""
        k, count = max(0, bisect_right(starts, i) - 1), 0
        while k < len(opcodes) and opcodes[k][1] < j:
            tag, i1, i2, j1, j2 = opcodes[k]
            if tag in ("equal", "replace"):
                chars = sum(ch not in _NOT_BODY for ch in o[max(i, i1):min(j, i2)])
                count += chars if tag == "equal" else chars * min(1.0, (j2 - j1) / (i2 - i1))
            k += 1
        return count

    o_marks, r_marks = _mark_positions(o), _mark_positions(r)
    if not o_marks and not r_marks:
        return []
    r_spans = _sentence_spans(r)
    r_starts = [a for a, _ in r_spans]

    def owns_sentence(i, j):
        """元の [i, j) が対応する範囲が、それが入っている書き直した文の中身の6割以上を占めるか。"""
        a, b = map_start(i), map_end(j)
        k = bisect_right(r_starts, a) - 1
        if b <= a or k < 0 or r_spans[k][1] <= a:
            return False
        ra, rb = r_spans[k]
        whole = sum(ch not in _NOT_BODY for ch in r[ra:rb])
        part = sum(ch not in _NOT_BODY for ch in r[max(a, ra):min(b, rb)])
        return whole > 0 and part * 5 >= whole * 3
    # 丸ごと移した文は、書き直した文章の中で1文として見つかるものに限る（見出しなどの短い文が、別の文の一部に当たるのを除く）。
    whole = {}
    for a, b in r_spans:
        whole.setdefault(r[a:b].strip(), (a, b))
    groups, moved, gone, found = [], [], [], []
    for s, e in _sentence_spans(o):
        text = o[s:e].strip()
        body = sum(ch not in _NOT_BODY for ch in text)
        # 対応する文字が少なすぎる文は、残った文とみなさない。消した文の文末の数文字が、隣の文に足した印の中の文字と
        # 一致しただけの場合などで、その文を比べると、隣の文の印の変化をこの文の変化として出してしまう。
        # ただし、対応する範囲が書き直した文の大半を占めるときは、短く書き直した文として残った文とみなす。
        if aligned(s, e) < min(body, max(3, -(-body // 4))) and not owns_sentence(s, e):
            if text in whole:
                a, b = whole.pop(text)
                found.append((a, b))
                moved.append(([text], [(s, e)], a, b))
            else:
                gone.append((text, s, e))
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
    # 丸ごと移した文の位置に重なる範囲は、文字の対応がその文に引きずられたもの。移した文の部分を除き、残りの長いほうで比べる。
    for fa, fb in found:
        for g in groups:
            if g[2] < fb and fa < g[3]:
                left, right = r[g[2]:max(g[2], fa)], r[min(g[3], fb):g[3]]
                if len(left.strip("。！？!?、 \n")) >= len(right.strip("。！？!?、 \n")):
                    g[3] = max(g[2], fa)
                else:
                    g[2] = min(g[3], fb)
    groups = [g for g in groups if r[g[2]:g[3]].strip("。！？!?、 \n")]
    if gone:
        groups = _pair_gone_sentences(o, r, opcodes, groups, moved, gone, r_spans)
    _widen_to_sentences(groups, moved, r_spans)
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


def _pair_gone_sentences(o, r, opcodes, groups, moved, gone, r_spans):
    """比べずに飛ばした元の文（同じ文が書き直した文章にないもの）を、字面が重なる書き直した文と組にする。

    組にできるのは、次をどちらも満たすときだけ。消しただけの文を、残したほかの文と組にしないため。
    - 短いほうの文の2文字の組の半分以上（かつ4組以上。短いほうの組が6つ以下なら3組以上）が共通している。
    - 共通する組のうち同じ数以上が、その書き直した文に範囲が掛かっている元の文（そのまま残った文、丸ごと移した文）では説明できない。
    組は字面の近い順（Dice係数）に、どちらの文も1回だけ使って決める。
    書き直した文が1つの元の文の範囲だけでできていて、その元の文の字面が遠い（Dice係数0.6未満で、消えた文より遠い）ときは、その範囲は比べない。
    書き直した文が2文以上にまたがる範囲の端にあるときは、その範囲から外す。"""
    def dice(x, y):
        return 2 * len(x & y) / ((len(x) + len(y)) or 1)

    r_grams = [_bigrams(r[a:b].strip()) for a, b in r_spans]
    owners = [[g for g in groups if g[2] < b and a < g[3]] for a, b in r_spans]
    owner_grams = [set().union(*[_bigrams("".join(g[0])) for g in gs + [m for m in moved if m[2] < b and a < m[3]]])
                   for gs, (a, b) in zip(owners, r_spans)]
    candidates = []
    for gi, (text, _, _) in enumerate(gone):
        grams = _bigrams(text)
        for idx, (a, b) in enumerate(r_spans):
            shared = grams & r_grams[idx]
            least = 3 if min(len(grams), len(r_grams[idx])) <= 6 else 4
            if len(shared) < least or len(shared) < 0.5 * min(len(grams), len(r_grams[idx])):
                continue
            if len(shared - owner_grams[idx]) < least:
                continue
            candidates.append((dice(grams, r_grams[idx]), gi, idx))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_gone, used_r, drop = set(), {}, set()
    for score, gi, idx in candidates:
        if gi in used_gone:
            continue
        text, s, e = gone[gi]
        if idx in used_r:
            # 改行で折り返した文の前半と後半が同じ文の相手になるときは、まとめて比べる。前半は句点で終わっていない。
            entry = used_r[idx]
            first, last = entry[1][0], entry[1][-1]
            after = o[last[1]:s].strip() == "" and o[last[0]:last[1]].rstrip()[-1:] not in "。！？!?"
            before = o[e:first[0]].strip() == "" and text[-1:] not in "。！？!?"
            if not (after or before):
                continue
            used_gone.add(gi)
            entry[1].append((s, e))
            entry[1].sort()
            entry[0][:] = [o[x:y].strip() for x, y in entry[1]]
            continue
        used_gone.add(gi)
        a, b = r_spans[idx]
        moved.append(([text], [(s, e)], a, b))
        used_r[idx] = moved[-1]
        for g in owners[idx]:
            if a <= g[2] and g[3] <= b + 1:
                if dice(_bigrams("".join(g[0])), r_grams[idx]) < min(score, 0.6):
                    drop.add(id(g))
            elif g[2] < a < g[3] <= b + 1:
                g[3] = a
            elif a <= g[2] < b < g[3]:
                g[2] = b
    return [g for g in groups if id(g) not in drop]


def _widen_to_sentences(groups, moved, r_spans):
    """範囲を、それが入っている書き直した文の端まで広げる。ほかの元の文の範囲に掛かるところには広げない。
    消した文の文末の数文字に引きずられて、隣の文に足した印が範囲の外に出るのを防ぐ。"""
    if not groups:
        return
    r_starts, r_ends = [a for a, _ in r_spans], [b for _, b in r_spans]
    claimed = sorted([(g[2], g[3]) for g in groups] + [(m[2], m[3]) for m in moved])
    for g in groups:
        a, b = g[2], g[3]
        i = bisect_right(r_starts, a) - 1
        j = bisect_left(r_ends, b)
        left = r_starts[i] if 0 <= i < len(r_spans) and r_ends[i] > a else a
        right = r_ends[j] if j < len(r_spans) and r_starts[j] < b else b
        for ca, cb in claimed:
            if (ca, cb) == (a, b):
                continue
            if cb <= a:
                left = max(left, cb)
            elif ca >= b:
                right = min(right, ca)
        g[2], g[3] = min(a, left), max(b, right)


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


def _rule_candidates(orig_raw: str, rw_raw: str, stance=None) -> dict:
    """v1.1.2 の diff() の9つの点検（markers から type_changes まで）。中身は v1.1.2 と1字も変えない。"""
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




# ---- 全文差分（v2.0.0。DESIGN-interfaces.md 2.3、2.4）----
# 生の文を行で対応させ、変わった塊の中を文字で対応させる。normalize() は通さない。

_CHAR_ALIGN_LIMIT = 2000        # 塊（または文の断片）をそのまま文字で対応させる、片側の字数の上限
_CHAR_BUDGET = 200000           # 文書全体で文字の対応にかける字数（対応させる文字列の長さの、両側の合計）
_PAIR_WINDOW = 4                # 文や断片を組にするとき、直前の組の次から見る数
_PAIR_RATIO = 0.45              # 組にする似かたの下限（difflib の ratio）
_LONG_LINE = 160                # これを超える行の「差:」は、変わった文のまわりだけを出す
_FRAGMENT = re.compile(r"[^。！？!?\n]*[。！？!?]*[」』）)]*\n?")
_SENTENCE_END = re.compile(r"[。！？!?]+[」』）)]*")
_SPACES = re.compile("[\\s\ufeff]+")
_ATX = re.compile(r"^( {0,3})(#{1,6})((?:[ \t].*)?)$")
_BLOCK_NAMES = {
    "paragraph": "本文", "list": "箇条書き", "quote": "引用", "heading": "見出し", "heading_underline": "見出し",
    "table": "表", "code": "コード", "frontmatter": "先頭の設定", "html_block": "HTML",
    "reference_definition": "リンクの定義", "blank": "空行", "thematic_break": "区切り線",
}
_VISIBLE = {" ": "〔空白〕", "\u3000": "〔全角空白〕", "\t": "〔タブ〕", "\n": "〔改行〕", "\ufeff": "〔BOM〕"}
_EOL_NAMES = {"lf": "LF", "crlf": "CRLF", "cr": "CR", "mixed": "混在"}
# 全文差分の hunk に付ける「limits_applied」の名前（文書全体で1回ずつ、この順）
_LIMIT_NAMES = ("long_fragment", "too_large", "budget")


def _split_lines(text):
    """行に分ける。文字列が改行で終わるときは、最後の空の要素を除く（末尾の改行の有無は final_newline に記録する）。"""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def _line_starts(lines):
    starts, position = [], 0
    for line in lines:
        starts.append(position)
        position += len(line) + 1
    return starts


def _is_blank(line):
    return not line.strip()


def _analyze(text):
    """analyze_markdown を、行の分け方を "\\n" だけにそろえてかける（"\\r" は同じ長さの空白に置き換える）。
    行番号と位置が全文差分の行と1対1に対応する。

    空白で区切らない URL（bare_url）は、GFM の自動リンクと同じく次の空白まで続く範囲で返ってくる
    （「https://example.com/guideにあり、保存期間は3日です。」の全体）。数値を伏せる範囲と、変えない箇所を判定する範囲には、
    頭から URL に使える ASCII の字が続くところまでを使う（URL のあとの本文の数値と変化を伏せないため）。"""
    analysis = analyze_markdown(text.replace("\r", " ") if "\r" in text else text)
    spans, changed = [], False
    for left, right, kind in analysis["protected_spans"]:
        if kind == "bare_url":
            end = _URL_CHARS.match(text, left).end()
            if left < end < right:
                right, changed = end, True
        spans.append((left, right, kind))
    if changed:
        analysis = dict(analysis)
        analysis["protected_spans"] = spans
    return analysis


# URL に使える ASCII の字（RFC 3986 の unreserved、reserved と %）
_URL_CHARS = re.compile(r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*")


def _align(old, new, similar=False):
    """2つの並び（行か文の断片）を対応させ、組 (i, j, 中身が同じか) の並びを返す（i と j はどちらも増える）。

    difflib.SequenceMatcher を並び全体にかけると、空行やコードの囲みのように同じ要素が何度も出る文書で、
    時間が要素の数の2乗から3乗で伸びる（10.2 D16。短い段落900個の6万字で10秒あまり）。そこで次の順に対応させる。
    1. 前と後ろの同じ要素を外す。
    2. 両方に1回ずつだけ出る空白だけでない要素を組の候補にし、順番を保つ最長の並び（patience diff の考え方）を組にする。
       組と組の間を、同じ手順でたどる。
    3. 残った間が小さい（両側の要素の数の積が400以下）なら、difflib.SequenceMatcher で同じ要素を組にする。
       大きいなら、前から順に、近く（8つ先まで）にある同じ中身の要素を組にする。8つより先でも、そこまでに飛ばす要素のうち
       元の側にもある中身のものが8つ未満（飛ばすのはほぼ足した塊）なら組にする。
    4. similar が真なら、残った要素を 2.5.1 の方法（直前の組の次から4つ、ratio が0.45以上で最大のもの）で組にする。
       この組は中身が同じとは限らない。
    どの手順も入力だけで決まる（時間で打ち切らない）。"""
    pairs = []
    _align_range(old, new, 0, len(old), 0, len(new), similar, pairs, 0)
    return pairs


_SMALL_GAP = 400        # 残った間を difflib.SequenceMatcher で対応させる大きさの上限（両側の要素の数の積）
_GAP_WINDOW = 8         # 大きな間で、同じ中身の要素を探す先の長さ
_ALIGN_DEPTH = 64       # 手順2をたどる深さの上限


def _align_range(old, new, i1, i2, j1, j2, similar, out, depth):
    while i1 < i2 and j1 < j2 and old[i1] == new[j1]:
        out.append((i1, j1, True))
        i1, j1 = i1 + 1, j1 + 1
    tail = []
    while i1 < i2 and j1 < j2 and old[i2 - 1] == new[j2 - 1]:
        i2, j2 = i2 - 1, j2 - 1
        tail.append((i2, j2, True))
    if i1 < i2 and j1 < j2:
        anchors = _unique_anchors(old, new, i1, i2, j1, j2) if depth < _ALIGN_DEPTH else []
        if anchors:
            previous_i, previous_j = i1, j1
            for i, j in anchors:
                _align_range(old, new, previous_i, i, previous_j, j, similar, out, depth + 1)
                out.append((i, j, True))
                previous_i, previous_j = i + 1, j + 1
            _align_range(old, new, previous_i, i2, previous_j, j2, similar, out, depth + 1)
        else:
            out.extend(_fill_gap(old, new, i1, i2, j1, j2, similar))
    out.extend(reversed(tail))


def _unique_anchors(old, new, i1, i2, j1, j2):
    """old[i1:i2] と new[j1:j2] の両方に1回ずつだけ出る、空白だけでない要素の組のうち、順番を保つ最長の並び。"""
    count_old = Counter(old[i1:i2])
    count_new = Counter(new[j1:j2])
    where = {}
    for j in range(j1, j2):
        item = new[j]
        if count_new[item] == 1 and count_old.get(item) == 1 and not _is_blank(item):
            where[item] = j
    candidates = [(i, where[old[i]]) for i in range(i1, i2) if old[i] in where]
    # 最長増加部分列（new の位置が増える並び）。同じ長さなら先に見つけたものを使う。
    tails, tail_values, previous = [], [], [None] * len(candidates)
    for index, (_, j) in enumerate(candidates):
        position = bisect_left(tail_values, j)
        if position:
            previous[index] = tails[position - 1]
        if position == len(tails):
            tails.append(index)
            tail_values.append(j)
        else:
            tails[position] = index
            tail_values[position] = j
    chain = []
    index = tails[-1] if tails else None
    while index is not None:
        chain.append(candidates[index])
        index = previous[index]
    return chain[::-1]


def _fill_gap(old, new, i1, i2, j1, j2, similar):
    """1回ずつだけ出る要素で組にできなかった間（old[i1:i2] と new[j1:j2]）で、組を作る。"""
    if i1 >= i2 or j1 >= j2:
        return []
    found = []
    if (i2 - i1) * (j2 - j1) <= _SMALL_GAP:
        matcher = difflib.SequenceMatcher(None, old[i1:i2], new[j1:j2], autojunk=False)
        for a, b, size in matcher.get_matching_blocks():
            found.extend((i1 + a + k, j1 + b + k, True) for k in range(size))
    else:
        positions = {}
        for j in range(j1, j2):
            positions.setdefault(new[j], []).append(j)
        # 後の側の各位置までに、元の側にもある中身の要素がいくつあるか（飛ばしてよいかの判断に使う）
        in_old = set(old[i1:i2])
        shared = [0]
        for j in range(j1, j2):
            shared.append(shared[-1] + (new[j] in in_old))
        k = j1
        for i in range(i1, i2):
            places = positions.get(old[i])
            if not places:
                continue
            index = bisect_left(places, k)
            if index == len(places):
                continue
            place = places[index]
            # 近く（8つ先まで）にあれば組にする。遠くても、そこまでに飛ばす要素が後の側にだけある中身（足した塊）なら組にする
            # （全面書き換えの途中に空行のない9行の箇条書きを足しても、そのあとの空行が組になり、段落ごとの hunk になる。
            # 飛ばす要素に元の側にもある中身が8つ以上あるときは、遠くの同じ中身と組にせず、ずれを防ぐ）
            if place - k < _GAP_WINDOW or shared[place - j1] - shared[k - j1] < _GAP_WINDOW:
                found.append((i, place, True))
                k = place + 1
    if not similar:
        return found
    # 同じ中身の組を区切りにして、その間の要素を似ているもので組にする
    pairs = []
    previous_i, previous_j = i1, j1
    for i, j, same in found + [(i2, j2, None)]:
        for x, y in _pair_similar(old, new, previous_i, i, previous_j, j):
            pairs.append((x, y, old[x] == new[y]))
        if same is not None:
            pairs.append((i, j, same))
        previous_i, previous_j = i + 1, j + 1
    return pairs


def _common_affix(a, b):
    """2つの文字列の、前の同じ字の数と後ろの同じ字の数（重ならない）。切り出した文字列どうしを比べて二分探索する
    （1字ずつ比べるより速い）。"""
    limit = min(len(a), len(b))
    low, high = 0, limit
    while low < high:
        middle = (low + high + 1) // 2
        if a[:middle] == b[:middle]:
            low = middle
        else:
            high = middle - 1
    head = low
    low, high = 0, limit - head
    while low < high:
        middle = (low + high + 1) // 2
        if a[len(a) - middle:] == b[len(b) - middle:]:
            low = middle
        else:
            high = middle - 1
    return head, low


def _affix_ratio(a, b):
    """前後の同じ字の数から求めた似かた（2×(前の同じ字＋後ろの同じ字)÷両側の字数）。difflib の ratio() より小さいか同じ。"""
    if not a and not b:
        return 1.0
    head, tail = _common_affix(a, b)
    return 2.0 * (head + tail) / (len(a) + len(b))


def _pair_similar(old, new, i1, i2, j1, j2):
    """2.5.1 の組み方。old[i1:i2] の各要素について、直前に組にした new の要素の次から4つの範囲で、
    quick_ratio が0.45以上のものを候補にし、ratio が最大で0.45以上なら組にする（順番を保つ）。

    どちらかが2,000字（_CHAR_ALIGN_LIMIT）を超える組には difflib の ratio() をかけず、前後の同じ字の数から求めた似かた
    （_affix_ratio）を使う。ratio() は長さのおよそ2乗の時間がかかり（「。」のない6万字の1行で十数秒）、2.11 の時間の約束を
    守れない。2,000字を超える断片の組は全文差分では文字で対応させない（2.3 の4）ので、組にするかの判断にだけ使われる。"""
    pairs = []
    start = j1
    matcher = difflib.SequenceMatcher(None, "", "", autojunk=False)
    for i in range(i1, i2):
        if start >= j2:
            break
        matcher.set_seq2(old[i])
        best, best_ratio = None, 0.0
        for j in range(start, min(start + _PAIR_WINDOW, j2)):
            matcher.set_seq1(new[j])
            if matcher.real_quick_ratio() < _PAIR_RATIO or matcher.quick_ratio() < _PAIR_RATIO:
                continue
            if len(old[i]) > _CHAR_ALIGN_LIMIT or len(new[j]) > _CHAR_ALIGN_LIMIT:
                ratio = _affix_ratio(old[i], new[j])
            else:
                ratio = matcher.ratio()
            if ratio >= _PAIR_RATIO and ratio > best_ratio:
                best, best_ratio = j, ratio
        if best is not None:
            pairs.append((i, best))
            start = best + 1
    return pairs


def _opcodes(pairs, n, m):
    """組の並びから、equal 以外の塊 (tag, i1, i2, j1, j2) を作る。"""
    blocks = []
    i = j = 0
    for x, y, _ in pairs + [(n, m, True)]:
        if x > i or y > j:
            tag = "replace" if x > i and y > j else ("delete" if x > i else "insert")
            blocks.append((tag, i, x, j, y))
        i, j = x + 1, y + 1
    return blocks


def _merge_segments(segments):
    merged = []
    for tag, text in segments:
        if not text:
            continue
        if merged and merged[-1][0] == tag:
            merged[-1][1] += text
        else:
            merged.append([tag, text])
    return merged


def _char_segments(a, b):
    """2つの文字列を文字で対応させ、[["=", 同じ文字], ["-", 消した文字], ["+", 足した文字], ...] を返す。
    前と後ろの同じ文字を先に外してから、残りを _ExactSequenceMatcher で対応させる。"""
    limit = min(len(a), len(b))
    head = 0
    while head < limit and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < limit - head and a[len(a) - 1 - tail] == b[len(b) - 1 - tail]:
        tail += 1
    middle_a, middle_b = a[head:len(a) - tail], b[head:len(b) - tail]
    segments = [["=", a[:head]]]
    if middle_a and middle_b:
        for tag, i1, i2, j1, j2 in _ExactSequenceMatcher(None, middle_a, middle_b, autojunk=False).get_opcodes():
            if tag == "equal":
                segments.append(["=", middle_a[i1:i2]])
            else:
                segments.append(["-", middle_a[i1:i2]])
                segments.append(["+", middle_b[j1:j2]])
    else:
        segments.append(["-", middle_a])
        segments.append(["+", middle_b])
    segments.append(["=", a[len(a) - tail:]])
    return _merge_segments(segments)


def _fragments(text):
    """文の断片に分ける。断片は「句点までの文と、続く閉じかっこと改行」。すべての断片をつなぐと元の文字列に戻る。"""
    pieces, position, size = [], 0, len(text)
    while position < size:
        end = _FRAGMENT.match(text, position).end()
        if end == position:
            end = position + 1
        pieces.append(text[position:end])
        position = end
    return pieces


def _plan_segments(a, b):
    """塊の文字の対応の計画。(費用, 作る関数, 長い断片を省いたか) を返す。費用は文字の対応にかける文字列の長さの、両側の合計。"""
    if len(a) <= _CHAR_ALIGN_LIMIT and len(b) <= _CHAR_ALIGN_LIMIT:
        return len(a) + len(b), lambda: _char_segments(a, b), False
    old, new = _fragments(a), _fragments(b)
    pairs = _align(old, new, similar=True)
    cost, long_fragment = 0, False
    for i, j, same in pairs:
        if same:
            continue
        if len(old[i]) > _CHAR_ALIGN_LIMIT or len(new[j]) > _CHAR_ALIGN_LIMIT:
            long_fragment = True
        else:
            cost += len(old[i]) + len(new[j])

    def build():
        segments = []
        i = j = 0
        for x, y, same in pairs + [(len(old), len(new), None)]:
            segments.append(["-", "".join(old[i:x])])
            segments.append(["+", "".join(new[j:y])])
            if same is None:
                break
            if same:
                segments.append(["=", old[x]])
            elif len(old[x]) > _CHAR_ALIGN_LIMIT or len(new[y]) > _CHAR_ALIGN_LIMIT:
                segments.append(["-", old[x]])
                segments.append(["+", new[y]])
            else:
                segments.extend(_char_segments(old[x], new[y]))
            i, j = x + 1, y + 1
        return _merge_segments(segments)
    return cost, build, long_fragment


def _kinds(analysis, first, last):
    """行 first から last の手前まで（0から数える）の行の種類を、重ねずに出てきた順に集める。"""
    kinds = []
    rows = analysis["lines"]
    for index in range(first, last):
        kind = rows[index]["kind"] if index < len(rows) else "paragraph"
        # 引用の中の行は、箇条書きの続きとして読まれても引用として出す（変えない箇所の引用と見方をそろえる）
        if kind in ("paragraph", "list") and index < len(rows) and rows[index]["quote_depth"]:
            kind = "quote"
        if kind not in kinds:
            kinds.append(kind)
    return kinds


def _encoding_notes(old_info, new_info):
    """decode_source の情報2つから、全文差分の注記（改行コード、BOM）を作る。どちらかに改行がないときは改行コードを比べない。"""
    notes = []
    if old_info["eol"] != new_info["eol"] and "none" not in (old_info["eol"], new_info["eol"]):
        notes.append({"kind": "eol", "old": old_info["eol"], "new": new_info["eol"]})
    if old_info["bom"] != new_info["bom"]:
        notes.append({"kind": "bom", "old": old_info["bom"], "new": new_info["bom"]})
    return notes


class _Sides:
    """全文差分と意味が変わる恐れで使う、元と後のそれぞれの行、行の位置、Markdown の解析。"""

    def __init__(self, orig, rw):
        self.texts = (orig, rw)
        self.lines = (_split_lines(orig), _split_lines(rw))
        self.starts = (_line_starts(self.lines[0]), _line_starts(self.lines[1]))
        self.analyses = (_analyze(orig), _analyze(rw))
        self._normalized = [None, None]
        self._numbers = [None, None]

    def line_of(self, side, position):
        """文字の位置（0から）を行番号（1から）にする。"""
        return max(1, bisect_right(self.starts[side], position))

    def normalized_lines(self, side):
        if self._normalized[side] is None:
            self._normalized[side] = [normalize(line) for line in self.lines[side]]
        return self._normalized[side]

    def numbers(self, side):
        """2.5.2 の取り出し方で取った数値（位置の順）と、その始まりの位置の並び。"""
        if self._numbers[side] is None:
            found = _find_numbers(self.texts[side], self.analyses[side])
            self._numbers[side] = (found, [number.start for number in found])
        return self._numbers[side]

    def all_keys(self, side):
        """伏せる前の数値（コード、URL、先頭の設定、HTML の中も含む）の (数, 単位) の集合。「文書のどこにもない」の判定に使う。"""
        cache = self.__dict__.setdefault("_all_keys", {})
        if side not in cache:
            cache[side] = set(number.key for number in _find_numbers(self.texts[side], self.analyses[side], ()))
        return cache[side]


def full_diff(orig, rw, encoding_notes=None):
    """元の文と書き直した文の全文差分（DESIGN-interfaces.md 2.3、2.8 の full_diff）。

    渡された文字列をそのまま比べる（BOM を外したり、改行をそろえたりしない）。encoding_notes は CLI と check が
    decode_source の情報から作って渡す注記で、そのまま入れる（渡さなければ []）。"""
    return _build_full_diff(orig, rw, encoding_notes)[0]


def _build_full_diff(orig, rw, encoding_notes):
    sides = _Sides(orig, rw)
    old_lines, new_lines = sides.lines
    limits = set()
    hunks = []
    if old_lines != new_lines:
        pairs = _align(old_lines, new_lines)
        for tag, i1, i2, j1, j2 in _opcodes(pairs, len(old_lines), len(new_lines)):
            hunks.append(_make_hunk(len(hunks) + 1, tag, i1, i2, j1, j2, sides))
    _mark_moved(hunks)
    budget = _CHAR_BUDGET
    for hunk in hunks:
        if hunk["tag"] != "replace":
            continue
        cost, build, long_fragment = _plan_segments("\n".join(hunk["old_lines"]), "\n".join(hunk["new_lines"]))
        if cost > _CHAR_BUDGET:
            hunk["segments_omitted"] = "too_large"
        elif cost > budget:
            hunk["segments_omitted"] = "budget"
        else:
            budget -= cost
            hunk["segments"] = build()
            if long_fragment:
                limits.add("long_fragment")
        if hunk["segments_omitted"]:
            limits.add(hunk["segments_omitted"])
    full = {
        "encoding_notes": [dict(note) for note in (encoding_notes or [])],
        "final_newline": {"old": orig.endswith("\n"), "new": rw.endswith("\n")},
        "limits_applied": [name for name in _LIMIT_NAMES if name in limits],
        "hunks": hunks,
    }
    return full, sides


def _make_hunk(index, tag, i1, i2, j1, j2, sides):
    old_part, new_part = sides.lines[0][i1:i2], sides.lines[1][j1:j2]
    old_blocks, new_blocks = _kinds(sides.analyses[0], i1, i2), _kinds(sides.analyses[1], j1, j2)
    whitespace_only = _SPACES.sub("", "\n".join(old_part)) == _SPACES.sub("", "\n".join(new_part))
    notes = []
    if whitespace_only:
        notes.append({"kind": "whitespace_only"})
    if len(old_part) == 1 and len(new_part) == 1 and old_blocks == ["heading"] and new_blocks == ["heading"]:
        old_match, new_match = _ATX.match(old_part[0]), _ATX.match(new_part[0])
        if (old_match and new_match and old_match.group(1, 3) == new_match.group(1, 3)
                and len(old_match.group(2)) != len(new_match.group(2))):
            notes.append({"kind": "heading_level", "old": len(old_match.group(2)), "new": len(new_match.group(2))})
    return {"index": index, "tag": tag,
            "old_start": i1 + 1, "old_end": i2, "new_start": j1 + 1, "new_end": j2,
            "old_blocks": old_blocks, "new_blocks": new_blocks,
            "whitespace_only": whitespace_only, "notes": notes, "moved_to": None, "moved_from": None,
            "old_lines": old_part, "new_lines": new_part,
            "segments": None, "segments_omitted": None}


def _mark_moved(hunks):
    """消した空白だけでない行と中身が完全に同じ行が、ほかの hunk で足されていれば、2つの hunk を対にする（2.3 の8）。
    1つの hunk の相手は1つだけ（最初に見つかったもの）。"""
    added = {}
    for hunk in hunks:
        for offset, line in enumerate(hunk["new_lines"]):
            if not _is_blank(line):
                added.setdefault(line, []).append((hunk, hunk["new_start"] + offset))
    if not added:
        return
    for hunk in hunks:
        for offset, line in enumerate(hunk["old_lines"]):
            if hunk["moved_to"] is not None or _is_blank(line):
                continue
            for other, line_no in added.get(line, ()):
                if other is hunk or other["moved_from"] is not None:
                    continue
                hunk["moved_to"] = other["index"]
                hunk["notes"].append({"kind": "moved_to", "hunk": other["index"], "line": line_no})
                other["moved_from"] = hunk["index"]
                other["notes"].append({"kind": "moved_from", "hunk": hunk["index"], "line": hunk["old_start"] + offset})
                break


# ---- 意味が変わる恐れ（v2.0.0。DESIGN-interfaces.md 2.5）----
# どれも確かめる場所で、意味が変わったという判定ではない。ここに出なかった変化も全文差分には必ず出る。

# 行頭の印（引用の >、箇条書きの印、見出しの #）。match(行, 位置) で位置から当てるので ^ は付けない
_LINE_PREFIX = re.compile(r"(?:[ \t]{0,3}>[ \t]?|[ \t]*(?:[-*+・]|\d+[.)])[ \t]+|[ \t]{0,3}#{1,6}(?:[ \t]+|$))")
# 文に分けない行の種類（中の変化は「変えない箇所」で見る）
_NO_SENTENCE_KINDS = ("code", "frontmatter", "html_block")
# protected_spans の種類 → subkind（10.2 D6）。引用はブロック（行の quote_depth と、遅延継続の行の kind）で見る。
# リンクの定義と画像のパスも、リンク先（link_destination）と同じく link にする（数値の取り出しでは伏せるので、ここで
# 出さないとどの判定からも漏れる。反証レビュー risk 5）。画像は ( ) の中のパスだけを見る（代わりの文は本文）
_PROTECTED_SPANS = {"inline_code": "inline_code", "code": "code", "autolink": "url", "bare_url": "url",
                    "link_destination": "link", "reference_definition": "link", "image": "link",
                    "frontmatter": "frontmatter", "html_block": "html", "html_token": "html"}
# 追加と削除の塊は行の種類で決める
_PROTECTED_LINES = {"code": "code", "frontmatter": "frontmatter", "html_block": "html"}
_PROTECTED_LABELS = {"code": "コード", "inline_code": "インラインのコード", "url": "URL", "link": "リンク先",
                     "frontmatter": "先頭の設定", "html": "HTML", "quote": "引用"}
# 同じ塊の中で並べる順
_RISK_ORDER = {"number": 0, "negation": 1, "swap": 2, "sentence_type": 3, "protected": 4}
# --fail-on=meaning-risk が数える kind（10.6 B1。beta 文書 2.2「数値・否定・主語と目的語の入れ替え・文の種類の変化」）。
# 変えない箇所（protected）は意味が変わる恐れの節に出すが数えない。check は資料にない数値（unsupported/number）も数える
FAIL_ON_KINDS = ("number", "negation", "swap", "sentence_type")


def fail_on_count(risks):
    """意味が変わる恐れのうち、--fail-on=meaning-risk が数えるもの（kind が FAIL_ON_KINDS か、unsupported/number）の数。"""
    return sum(1 for risk in risks
               if risk["kind"] in FAIL_ON_KINDS or (risk["kind"], risk.get("subkind")) == ("unsupported", "number"))


def _risk(kind, subkind, old_line, new_line, old, new, detail):
    return {"kind": kind, "subkind": subkind, "old_line": old_line, "new_line": new_line,
            "old": old, "new": new, "detail": detail, "basis": None}


class _Sentence(tuple):
    """文1つ。text は行頭の印（箇条書き、見出し、引用）を外した文、line は行番号（1から）、start は文書の中の位置。"""
    __slots__ = ()

    def __new__(cls, text, line, start):
        return tuple.__new__(cls, (text, line, start))

    text = property(lambda self: self[0])
    line = property(lambda self: self[1])
    start = property(lambda self: self[2])


def _line_sentences(sides, side, first, last):
    """行 first から last の手前まで（0から数える）を文に分ける。行頭の箇条書きの印、見出しの #、引用の > を外す。
    コード、先頭の設定、HTML の行は分けない（2.5.7 で見る）。"""
    sentences = []
    rows = sides.analyses[side]["lines"]
    for index in range(first, last):
        if index < len(rows) and rows[index]["kind"] in _NO_SENTENCE_KINDS:
            continue
        line = sides.lines[side][index]
        offset = 0
        while True:
            match = _LINE_PREFIX.match(line, offset)
            if not match or match.end() == offset:
                break
            offset = match.end()
        for match in _SENTENCE_PIECE.finditer(line, offset):
            text = match.group(0).strip()
            if text:
                start = match.start() + (len(match.group(0)) - len(match.group(0).lstrip()))
                sentences.append(_Sentence(text, index + 1, sides.starts[side][index] + start))
    return sentences


def _sentence_pairs(sides, full):
    """2.5.1 の文の組（共通の下ごしらえ）。hunk ごとに
    {"hunk": hunk, "old": [文], "new": [文], "pairs": [(元の文の番号, 後の文の番号)]} を返す。
    replace の塊だけ文を組にする。追加と削除の塊の文は、すべて組にならない文（足した文、消した文）。

    組み方は、中身が同じ文を先に組にしてから、その間の文を 2.5.1 の窓（直前の組の次から4文、ratio 0.45以上で最大）で
    組にする（全文差分の文の断片と同じ _align）。長い塊の途中に4文以上を足しても、その後ろの文が組になる。"""
    groups = []
    for hunk in full["hunks"]:
        old = _line_sentences(sides, 0, hunk["old_start"] - 1, hunk["old_end"])
        new = _line_sentences(sides, 1, hunk["new_start"] - 1, hunk["new_end"])
        pairs = []
        if hunk["tag"] == "replace" and old and new:
            pairs = [(i, j) for i, j, _ in _align([s.text for s in old], [s.text for s in new], similar=True)]
        groups.append({"hunk": hunk, "old": old, "new": new, "pairs": pairs})
    return groups


# ---- 数値（2.5.2。extract_numbers() と ground() も同じ取り出し方を使う）----

# 全角の英数字と記号（U+FF01〜U+FF5E）と全角空白を半角にする。NFKC と同じ結果で、文字数を変えない（位置をそのまま使える）
_HALF_WIDTH = dict((code, code - 0xFEE0) for code in range(0xFF01, 0xFF5F))
_HALF_WIDTH[0x3000] = 0x20
# 算用数字。英字や数字、「_」の直後と、「数字と . か ,」の直後からは始めない（v2、IPv6、x_3、1.2.3 の途中を数にしない）。
# 「，」「．」（半角にしたもの）の直後の数は取る（「3日，5日」「参加者は，30人」。反証レビュー F2）
_ARABIC = re.compile(r"(?<![A-Za-z0-9_])(?<![0-9][.,])[0-9]+(?:[.,][0-9]+)*")
# 数と単位の間の強調の記号（「**3**日」）。読み飛ばして単位を付ける（太字の有無は書式だけの違い。反証レビュー F3）
_EMPHASIS = re.compile(r"\*+")
_THOUSANDS = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?")
_UNITS = ("週間", "時間", "か月", "ヶ月", "カ月", "ヵ月", "TB", "GB", "MB", "KB", "ms", "px", "%",
          "年", "月", "日", "時", "分", "秒", "件", "個", "人", "名", "回", "円", "倍", "割", "度", "点",
          "本", "枚", "台", "社", "週", "歳", "字", "行")
_UNIT = re.compile("|".join(re.escape(unit) for unit in sorted(_UNITS, key=len, reverse=True)))
# 月の数え方の表記の違い（か月、ヶ月、カ月、ヵ月）は値を比べるときにそろえる（表記だけの違い）
_SAME_UNIT = {"ヶ月": "か月", "カ月": "か月", "ヵ月": "か月"}
# 漢数字は、意味が1つに決まる助数詞が続くときだけ取る
_KANJI_COUNTERS = ("週間", "時間", "か月", "ヶ月", "カ月", "ヵ月",
                   "年", "日", "件", "個", "人", "名", "回", "円", "倍", "割", "本", "枚", "台", "社", "歳")
_KANJI_NUMBER = re.compile("(?<![〇一二三四五六七八九十百千])([〇一二三四五六七八九十百千]+)("
                           + "|".join(sorted(_KANJI_COUNTERS, key=len, reverse=True)) + ")")
_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_UNITS = {"十": 10, "百": 100, "千": 1000}
# 漢数字の直前が漢字なら取らない。ただし直前がこの字なら取る（「最大三回」「後二週間」「第三回」）
_KANJI_BEFORE = set("約後計全第毎各残大小長短")
_KANJI = re.compile(r"[一-龥々〆ヵヶ]")
# 漢数字を含むが数ではない語
_KANJI_EXCLUDED = re.compile(r"一時(?!間)|一度|一部|一方|一般|一緒|一切|一応|一番|一定|一致|一意|一括|一本化|一日中|一年中|"
                             r"一人ひとり|一人一人|一回り|一枚岩|十分|十人十色|万一")
# 番号つき箇条書きの番号（行頭の「1.」「2)」。引用の中も）。数値ではなく並びの印。
# 隣り合う2つの [ \t]* が同じ空白を取り合う形にすると、伏せて空白だけになった長い行で2乗の時間になる（反証レビュー regress 1）
_LIST_NUMBER = re.compile(r"^[ \t]*(?:>[ \t]*)*[0-9]{1,9}[.)](?=[ \t]|$)", re.M)
# 数値を取り出す前に同じ長さの空白で伏せる protected_spans の種類（コードと URL の数は 2.5.7 に任せる）。
# 設計の一覧（code、inline_code、autolink、bare_url、link_destination、frontmatter、html_block）に、
# HTML のタグ（html_token）とリンクの定義（reference_definition）を足した。画像は ( ) の中のパスだけを伏せる
_NUMBER_MASKED = ("code", "inline_code", "autolink", "bare_url", "link_destination", "frontmatter", "html_block",
                  "html_token", "reference_definition", "image")


def _image_path_start(text, left, right):
    """画像の protected_spans（![代わりの文](パス)）の、パスの始まりの位置。パスがなければ right。"""
    middle = text.find("](", left, right)
    return right if middle < 0 else middle + 2


class _Number(tuple):
    """取り出した数値1つ。start と end は文書の中の位置、key は比べるときの (数, 単位)。"""
    __slots__ = ()

    def __new__(cls, start, end, value, unit):
        return tuple.__new__(cls, (start, end, value, unit))

    start = property(lambda self: self[0])
    end = property(lambda self: self[1])
    value = property(lambda self: self[2])
    unit = property(lambda self: self[3])
    key = property(lambda self: (self[2], self[3]))


def _plain_number(digits):
    """算用数字の文字列の頭の0を外す（「03」→「3」、「0.5」はそのまま）。"""
    whole, dot, fraction = digits.partition(".")
    whole = whole.lstrip("0") or "0"
    return whole + dot + fraction


def _kanji_value(text):
    """漢数字を整数にする。十・百・千を使う書き方（十二、百二十、三千）と、位取りの書き方（二〇二六）を読む。
    読めない並び（二三、十十）は None。"""
    if not any(ch in _KANJI_UNITS for ch in text):
        return int("".join(str(_KANJI_DIGITS[ch]) for ch in text))
    total, current, last = 0, None, 10000
    for ch in text:
        if ch in _KANJI_UNITS:
            unit = _KANJI_UNITS[ch]
            if unit >= last:
                return None
            total += (1 if current is None else current) * unit
            current, last = None, unit
        else:
            if current is not None or ch == "〇":
                return None
            current = _KANJI_DIGITS[ch]
    return total + (current or 0)


def _number_mask(text, analysis, masked_kinds=_NUMBER_MASKED):
    """数値を取り出す文字列。全角を半角にし、伏せる範囲（コード、URL など）と番号つき箇条書きの番号を同じ長さの空白にする。"""
    chars = list(text.translate(_HALF_WIDTH))
    for left, right, kind in analysis["protected_spans"]:
        if kind == "image" and kind in masked_kinds:
            # 画像は代わりの文の数を残し、( ) の中のパスだけを伏せる
            left = _image_path_start(text, left, right)
        elif kind not in masked_kinds:
            continue
        for index in range(left, min(right, len(chars))):
            if chars[index] != "\n":
                chars[index] = " "
    masked = "".join(chars)
    return _LIST_NUMBER.sub(lambda match: " " * len(match.group(0)), masked)


def _find_numbers(text, analysis, masked_kinds=_NUMBER_MASKED):
    """2.5.2 の取り出し方で、文書の中の数値を位置の順に返す（_Number の並び）。

    英字が続く数（3D、5G、30s、8GiB）は、一覧の単位が続かなければ単位なしの数として取る（2.5.2。反証レビュー F1）。
    数と単位の間の強調の記号（**）は読み飛ばす。masked_kinds は伏せる protected_spans の種類（() なら伏せない）。"""
    masked = _number_mask(text, analysis, masked_kinds)
    found = []
    for match in _ARABIC.finditer(masked):
        digits = match.group(0)
        unit = _UNIT.match(masked, match.end())
        if unit is None:
            emphasis = _EMPHASIS.match(masked, match.end())
            if emphasis is not None:
                unit = _UNIT.match(masked, emphasis.end())
        unit_text = unit.group(0) if unit else ""
        follow = unit.end() if unit else match.end()
        if "," in digits and not _THOUSANDS.fullmatch(digits):
            # 3桁区切りでないカンマは、数の区切り（「1,2,3」）。単位は最後の数に付ける
            pieces, offset = digits.split(","), match.start()
            for index, piece in enumerate(pieces):
                last = index == len(pieces) - 1
                end = follow if last else offset + len(piece)
                found.append(_Number(offset, end, _plain_number(piece), _SAME_UNIT.get(unit_text, unit_text) if last else ""))
                offset += len(piece) + 1
            continue
        found.append(_Number(match.start(), follow, _plain_number(digits.replace(",", "")),
                             _SAME_UNIT.get(unit_text, unit_text)))
    kanji_text = _KANJI_EXCLUDED.sub(lambda match: "＃" * len(match.group(0)), masked)
    for match in _KANJI_NUMBER.finditer(kanji_text):
        before = kanji_text[match.start() - 1] if match.start() else ""
        if before and _KANJI.match(before) and before not in _KANJI_BEFORE:
            continue
        value = _kanji_value(match.group(1))
        if value is None:
            continue
        counter = match.group(2)
        found.append(_Number(match.start(), match.end(), str(value), _SAME_UNIT.get(counter, counter)))
    found.sort()
    return found


def extract_numbers(text):
    """文の中の数値を取り出す（DESIGN-interfaces.md 2.5.2）。位置の順に
    {"text": 書かれた形, "value": 数（算用数字、3桁区切りなし）, "unit": 単位（なければ ""）, "start": 位置, "end": 位置}
    の並びを返す。コード、インラインのコード、URL、リンク先、先頭の設定、HTML の中の数は取らない。引用と表の中の数は取る。
    表記だけの違い（全角と半角、3桁区切りの有無、漢数字と算用数字、か月とヶ月）は value と unit が同じになる。"""
    return [{"text": text[number.start:number.end], "value": number.value, "unit": number.unit,
             "start": number.start, "end": number.end} for number in _find_numbers(text, _analyze(text))]


def _sentence_numbers(sides, side, sentence):
    """文の中の数値（位置の順）。"""
    numbers, starts = sides.numbers(side)
    end = sentence.start + len(sentence.text)
    return numbers[bisect_left(starts, sentence.start):bisect_left(starts, end)]


# 数値の結び付きの手がかり（数値のあとから読点・句点までの語）
_CLAUSE_END = re.compile(r"[、，,。．！？!?]")
_CONTEXT_WORD = re.compile(r"[一-龥々〆ヵヶ]+|[ァ-ヴー]+|[A-Za-z]+")


def _number_contexts(sides, side, sentence, numbers):
    """数値ごとの (結び付きの手がかり, 値) の多重集合。節を入れ替えただけで、語と数値の結び付きが同じなら、元と後で同じになる
    （「上限は20、応答は504」→「応答は504、上限は20」は並びの変化にしない。「Aは3日、Bは5日」→「Aは5日、Bは3日」はする）。

    手がかりは、数値の直前の2字（文頭と読点の直後は同じ「節の頭」とみなす。節を入れ替えると、文頭の数値が読点の直後に移るため）と、
    数値のあとから読点・句点（か次の数値）までの最初の2語（漢字、片仮名、英字の並び）。節の頭の数値を入れ替えた
    「10時から設計レビュー、14時からテスト」→「14時から設計レビュー、10時からテスト」を並びの変化にするため（反証レビュー risk 3）。
    表の行では、直前の字がどのセルでも「|」なので、何列目か（前にある「|」の数）を手がかりにする（反証レビュー E5）。"""
    found = Counter()
    text = sentence.text
    rows = sides.analyses[side]["lines"]
    table = sentence.line - 1 < len(rows) and rows[sentence.line - 1]["kind"] == "table"
    for index, number in enumerate(numbers):
        at = number.start - sentence.start
        if table:
            context = ("|", text.count("|", 0, at))
        else:
            head = text[:at].rstrip(" \t　")
            head = "" if not head or head[-1] in "、，," else head[-2:]
            end = numbers[index + 1].start - sentence.start if index + 1 < len(numbers) else len(text)
            tail = _CLAUSE_END.split(text[number.end - sentence.start:end], 1)[0]
            context = (head, tuple(_CONTEXT_WORD.findall(tail)[:2]))
        found[(context, number.key)] += 1
    return found


def _number_texts(sides, side, numbers, keys):
    """numbers のうち、keys（Counter）に入る値の書かれた形を、位置の順に、数えた回数だけ返す。"""
    keys = Counter(keys)
    texts = []
    for number in numbers:
        if keys[number.key] > 0:
            keys[number.key] -= 1
            texts.append(sides.texts[side][number.start:number.end])
    return texts


def _number_risks(sides, full, groups):
    """2.5.2 数値（kind number）。(hunk の番号, 塊の中の順, risk) の並びを返す。

    組になった文で比べる（replaced、added、lost、order）。そのあと、文書全体で後にだけある値と元にだけある値のうち、
    組の文で出していないもの（足した文、消した文の中の値）を、値の集合で added と lost にする（10.4 S4）。
    replaced に入れた値は added と lost に重ねない（10.1 L13）。

    「元の文書のどこにもない」「後の文書のどこにもない」は、伏せる前の数値（コードや URL の中も含む）で見る。
    文書全体の比べで出すのは、hunk の行の中にある値だけ（2.5 の前書き「対象は全文差分で変わった塊の中だけ」）。
    変わっていない行をコードの囲みに入れただけで、その行の値を「消えた数値」にしないため（反証レビュー E4）。"""
    out = []
    old_all, new_all = sides.all_keys(0), sides.all_keys(1)
    shown_removed, shown_added = set(), set()
    order = 0
    for group in groups:
        index = group["hunk"]["index"]
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            if old.text == new.text:
                continue
            old_numbers = _sentence_numbers(sides, 0, old)
            new_numbers = _sentence_numbers(sides, 1, new)
            old_count = Counter(number.key for number in old_numbers)
            new_count = Counter(number.key for number in new_numbers)
            removed, added = old_count - new_count, new_count - old_count
            risk = None
            if removed and added:
                risk = _risk("number", "replaced", old.line, new.line, old.text, new.text,
                             {"removed": _number_texts(sides, 0, old_numbers, removed),
                              "added": _number_texts(sides, 1, new_numbers, added)})
                shown_removed.update(removed)
                shown_added.update(added)
            elif added:
                fresh = Counter(dict((key, count) for key, count in added.items() if key not in old_all))
                if fresh:
                    risk = _risk("number", "added", old.line, new.line, old.text, new.text,
                                 {"removed": [], "added": _number_texts(sides, 1, new_numbers, fresh)})
                    shown_added.update(fresh)
            elif removed:
                gone = Counter(dict((key, count) for key, count in removed.items() if key not in new_all))
                if gone:
                    risk = _risk("number", "lost", old.line, new.line, old.text, new.text,
                                 {"removed": _number_texts(sides, 0, old_numbers, gone), "added": []})
                    shown_removed.update(gone)
            elif ([number.key for number in old_numbers] != [number.key for number in new_numbers]
                  and _number_contexts(sides, 0, old, old_numbers) != _number_contexts(sides, 1, new, new_numbers)):
                risk = _risk("number", "order", old.line, new.line, old.text, new.text,
                             {"old_order": [sides.texts[0][n.start:n.end] for n in old_numbers],
                              "new_order": [sides.texts[1][n.start:n.end] for n in new_numbers]})
            if risk is not None:
                out.append((index, order, risk))
                order += 1
    # 文書全体の比べ（足した文、消した文、組にならなかった文の中の値）
    old_keys = set(number.key for number in sides.numbers(0)[0])
    new_keys = set(number.key for number in sides.numbers(1)[0])
    for side, keys, subkind in ((0, old_keys - new_all - shown_removed, "lost"),
                                (1, new_keys - old_all - shown_added, "added")):
        if not keys:
            continue
        sentence_at, hunk_at = _sentence_finder(sides, side, groups), _hunk_finder(full, side)
        first = OrderedDict()
        for number in sides.numbers(side)[0]:
            if number.key in keys and number.key not in first:
                hunk = hunk_at(sides.line_of(side, number.start))
                if hunk is not None:
                    first[number.key] = (number, hunk)
        by_sentence = OrderedDict()
        for number, hunk in first.values():
            sentence = sentence_at(number.start)
            by_sentence.setdefault((hunk, sentence), []).append(sides.texts[side][number.start:number.end])
        for (hunk, (line, start, text)), texts in by_sentence.items():
            detail = {"removed": texts, "added": []} if side == 0 else {"removed": [], "added": texts}
            risk = (_risk("number", subkind, line, None, text, None, detail) if side == 0
                    else _risk("number", subkind, None, line, None, text, detail))
            out.append((hunk, 1000000 + start, risk))
    return out


def _sentence_finder(sides, side, groups):
    """位置を含む文 (行番号, 文書の中の位置, 文) を返す関数。hunk の文になければ、その行を丸ごと使う。
    文の始まりの位置の並びを1回だけ作り、二分探索で引く（値ごとに全部の文を前から見ると、値の数×文の数の時間になる。
    反証レビュー F5、E6）。"""
    key = "old" if side == 0 else "new"
    sentences = [sentence for group in groups for sentence in group[key]]
    starts = [sentence.start for sentence in sentences]

    def find(position):
        index = bisect_right(starts, position) - 1
        if index >= 0 and position < sentences[index].start + len(sentences[index].text):
            sentence = sentences[index]
            return (sentence.line, sentence.start, sentence.text)
        line = sides.line_of(side, position)
        return (line, sides.starts[side][line - 1], sides.lines[side][line - 1].strip())
    return find


def _hunk_finder(full, side):
    """その側の行番号を含む hunk の番号を返す関数（含む hunk がなければ None）。hunk の始まりの行で二分探索する。"""
    first, last = ("old_start", "old_end") if side == 0 else ("new_start", "new_end")
    hunks = full["hunks"]
    starts = [hunk[first] for hunk in hunks]

    def find(line):
        index = bisect_right(starts, line) - 1
        if index >= 0 and hunks[index][first] <= line <= hunks[index][last]:
            return hunks[index]["index"]
        return None
    return find


# ---- 否定（2.5.3）----

# 否定の印。「ず」は直後が「に」「、」「。」か文末のときだけ（必ず、はず、まず は除く。読まず のように漢字に続く まず は取る）
_NEGATION = re.compile(
    r"しないで|ません|なかっ|なけれ|ない|なく|禁止"
    r"|(?<!必)(?<!は)ず(?=[に、。]|$)"
    r"|ぬ(?=[。、]|$)"
    r"|未(?=[一-龥])"
    r"|不(?=要|可|明|正|足|在|備|具合|適|十分|一致|安定|許可|採用|使用|参加)"
    r"|非(?=公開|対応|表示|推奨|同期|互換|同意)"
    r"|無(?=効|料|視|関係|制限|断)")
# 数える前に伏せるもの（同じ長さの「＃」にする）。
# 義務の二重否定、否定の形をした別の働き、否定対比（「AではなくB」を外すのは yomiyasu のよくある正しい直し）
_NEGATION_MASKED = re.compile(
    r"なければ(?:ならない|なりません|ならず|いけない|いけません)|なくては(?:ならない|なりません|いけない|いけません)"
    r"|ないと(?:いけない|いけません)|ざるを得(?:ない|ません)|ねば(?:ならない|なりません)"
    r"|かもしれ(?:ない|ません)|に違い(?:ない|ありません)|とは限(?:らない|りません)|わけでは(?:ない|ありません)"
    r"|に(?:すぎ|過ぎ)(?:ない|ません)|しか(?:ない|ありません)|ほか(?:ない|ありません)|問題(?:ない|なく|ありません)|有無"
    r"|(?:では|じゃ|でも)な(?=[いくかけ])|(?:では|じゃ)ありません")
# 否定の形をした語の一部（少ない、危ない など）。「な」を伏せれば、ない・なく・なかっ・なけれ のどれにも当たらない
_NEGATION_WORDS = re.compile(r"(?:少|危|切|仕方|間違い|もったい|つまら|くだら|たまら|情け|頼り|あっけ|はか|ぎこち|さりげ|味気|素っ気)"
                             r"(な)(?=[いくかけ])")
# 「まず」の「ず」は、直前が漢字でなければ副詞（「まず、」）として除く
_ADVERB_MAZU = re.compile(r"(?<![一-龥々])まず")
_NEGATION_LIMIT = 2         # 変わった文字のうち、否定の印でない文字の数の上限（両側の合計。agent の試作の LIMIT）
# 句点の前の規則（10.2 D1。コーパス48組で測って入れると決めた。step2-diff/measure.md）。変わった箇所が元と後の両方で
# 文末（句点と閉じかっこの前。句点のない箇条書きの項目などは文の終わり）の直前5字の中に収まり、印の数が違えば数える
# （「設定する → 設定しない」のように語幹の仮名が変わる形のため）
_NEGATION_END_RULE = True
_END_WINDOW = 5             # 句点の前の規則の範囲（文末の直前の字数）
_PLACE_GAP = 1              # 変わった箇所をまとめる、間の同じ文字の数の上限
_SENTENCE_TAIL = re.compile(r"[。！？!?]*[」』）)]*$")
_HIRAGANA = re.compile(r"[ぁ-ゖ]")
_WORD_CHAR = re.compile(r"[一-龥々〆ヵヶァ-ヴー]")


def _negation_marks(text):
    """否定の印の範囲 [(始め, 終わり)]。伏せるものを伏せてから数える。"""
    masked = _NEGATION_MASKED.sub(lambda match: "＃" * len(match.group(0)), text)
    masked = _NEGATION_WORDS.sub(lambda match: match.group(0)[:-1] + "＃", masked)
    masked = _ADVERB_MAZU.sub("＃＃", masked)
    return [(match.start(), match.end()) for match in _NEGATION.finditer(masked)]


def _char_opcodes(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def _widen(text, left, right):
    """変わった箇所 [left, right) を語の切れ目まで広げる（10.2 D7）。左へは平仮名を4字まで、そのあと続く漢字・片仮名の並び全部。
    右へは平仮名を3字まで。句読点と空白で止める。変わった箇所の頭が漢字か片仮名なら、左の平仮名（助詞）は取らず、
    右へは続く漢字・片仮名の並びを先に取る（「有効 → 無効」を「有効です → 無効です」にする）。"""
    head = text[left] if left < len(text) else ""
    starts_with_word = bool(head) and bool(_WORD_CHAR.match(head))
    if not starts_with_word:
        count = 0
        while left > 0 and count < 4 and _HIRAGANA.match(text[left - 1]):
            left -= 1
            count += 1
    while left > 0 and _WORD_CHAR.match(text[left - 1]):
        left -= 1
    while starts_with_word and right < len(text) and _WORD_CHAR.match(text[right]):
        right += 1
    count = 0
    while right < len(text) and count < 3 and _HIRAGANA.match(text[right]):
        right += 1
        count += 1
    return text[left:right]


def _covered(left, right, marks):
    return sum(max(0, min(right, b) - max(left, a)) for a, b in marks)


def _changed_places(old, new):
    """2つの文の変わった箇所 [(i1, i2, j1, j2)]。文字の対応の equal が1字だけで切れた箇所は1つにまとめる
    （「不能な → できない」で、「な」だけが同じとされて「い」の挿入が否定の印に見えるのを防ぐ）。

    どちらかが2,000字（_CHAR_ALIGN_LIMIT）を超える文は、前後の同じ字を外した残りだけを対応させる。残りも2,000字を超えるときは、
    残り全体を1つの箇所にする（印でない字が多いので否定には数えない）。長い文の文字の対応は長さのおよそ2乗の時間がかかる
    （「。」のない4万字の1行で十数秒。反証レビュー E3）。"""
    if len(old) > _CHAR_ALIGN_LIMIT or len(new) > _CHAR_ALIGN_LIMIT:
        head, tail = _common_affix(old, new)
        old_end, new_end = len(old) - tail, len(new) - tail
        if old_end - head > _CHAR_ALIGN_LIMIT or new_end - head > _CHAR_ALIGN_LIMIT:
            return [(head, old_end, head, new_end)]
        opcodes = [(tag, i1 + head, i2 + head, j1 + head, j2 + head)
                   for tag, i1, i2, j1, j2 in _char_opcodes(old[head:old_end], new[head:new_end])]
    else:
        opcodes = _char_opcodes(old, new)
    places = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        if places and i1 - places[-1][1] <= _PLACE_GAP and j1 - places[-1][3] <= _PLACE_GAP:
            places[-1] = (places[-1][0], i2, places[-1][2], j2)
        else:
            places.append((i1, i2, j1, j2))
    return places


def _negation_flip(old, new):
    """組になった2つの文で、否定の有無が変わった最初の箇所の (元の語, 後の語) を返す。なければ None。

    変わった箇所に重なる印だけを数える（10.2 D8）。重なりは文字の範囲が重なるときだけで、挿入した位置の前後の字は数えない。
    文全体の否定の印の数が元と後で同じときは、印の数が同じまま言い回しだけを変えた推敲を拾わないよう、ふつうは出さない。
    ただし、LIMIT か句点の前の規則に当たる箇所が2つ以上あり、その中に印が増えた箇所と減った箇所の両方があれば出す
    （「Aは対応しているが、Bは対応していない」→「Aは対応していないが、Bは対応している」のように、1つの文の中で
    2つの否定を入れ替えた形。反証レビュー F9、risk 2）。"""
    old_marks, new_marks = _negation_marks(old), _negation_marks(new)
    same_total = len(old_marks) == len(new_marks)
    if same_total and not old_marks:
        return None
    old_end = len(old) - len(_SENTENCE_TAIL.search(old).group(0))
    new_end = len(new) - len(_SENTENCE_TAIL.search(new).group(0))
    found, directions = None, set()
    for i1, i2, j1, j2 in _changed_places(old, new):
        old_hits = [(a, b) for a, b in old_marks if a < i2 and b > i1]
        new_hits = [(a, b) for a, b in new_marks if a < j2 and b > j1]
        if len(old_hits) == len(new_hits):
            continue
        rest = (i2 - i1 - _covered(i1, i2, old_hits)) + (j2 - j1 - _covered(j1, j2, new_hits))
        near_end = (_NEGATION_END_RULE and i1 >= old_end - _END_WINDOW and i2 <= old_end
                    and j1 >= new_end - _END_WINDOW and j2 <= new_end)
        if rest <= _NEGATION_LIMIT or near_end:
            flip = _widen(old, i1, i2), _widen(new, j1, j2)
            if not same_total:
                return flip
            found = found or flip
            directions.add(len(new_hits) > len(old_hits))
    if len(directions) == 2:
        return found
    return None


def _negation_risks(sides, groups):
    """2.5.3 否定（kind negation）。組になった文を文字で対応させ、変わった箇所ごとに、その箇所に重なる否定の印の数を
    元と後で比べる。数が違い、変わった文字のうち印でない文字が両側合わせて2字以下なら出す（句点の前の規則は D1）。"""
    out = []
    order = 0
    for group in groups:
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            if old.text == new.text:
                continue
            flip = _negation_flip(old.text, new.text)
            if flip is not None:
                out.append((group["hunk"]["index"], order, _risk("negation", None, old.line, new.line, old.text, new.text,
                                                                 {"old": flip[0], "new": flip[1]})))
                order += 1
    return out


# ---- 主語と目的語の入れ替え（2.5.4）----

_CASE_WORD = re.compile(r"[一-龥々ァ-ヴーA-Za-z0-9０-９・]{1,12}")


def _case_map(text):
    """「語と助詞」の組。語ごとに最初の1つ（OrderedDict）。語は最長の並びで、直後の さん、様、氏、くん、ちゃん を外す。"""
    found = OrderedDict()
    for match in _CASE_WORD.finditer(text):
        word, end = match.group(0), match.end()
        honorific = re.match(r"さん|くん|ちゃん", text[end:end + 3])
        if honorific:
            end += len(honorific.group(0))
        elif len(word) > 2 and word[-1] in "様氏":
            # 「田中様」「佐藤氏」の敬称を外す。2字の語（仕様、同様、彼氏）は外さない
            word = word[:-1]
        particle = re.match(r"から|より|が|を|に|は|へ", text[end:end + 2])
        if particle and word not in found:
            found[word] = particle.group(0)
    return found


def _swap_risks(sides, groups):
    """2.5.4 主語と目的語の入れ替え（kind swap）。両方の文にある2つの語 A と B で、元で A が p、B が q（p と q は違う）、
    後で A が q、B が p なら出す。助詞は が、を、に、は、から、へ、より（「と」は入れない）。"""
    out = []
    order = 0
    for group in groups:
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            if old.text == new.text:
                continue
            before, after = _case_map(old.text), _case_map(new.text)
            common = [word for word in before if word in after]
            words = []
            for x, a in enumerate(common):
                for b in common[x + 1:]:
                    if before[a] != before[b] and after[a] == before[b] and after[b] == before[a]:
                        for word in (a, b):
                            if word not in words:
                                words.append(word)
            if words:
                words.sort(key=common.index)
                pairs = [{"word": word, "old": before[word], "new": after[word]} for word in words]
                out.append((group["hunk"]["index"], order, _risk("swap", None, old.line, new.line, old.text, new.text,
                                                                 {"pairs": pairs})))
                order += 1
    return out


# ---- 問い（2.5.5）----

_QUESTION = re.compile(r"(?:[？?]|か[。？?])[」』）)]*$")


def _is_question(text):
    return bool(_QUESTION.search(text.rstrip()))


def _question_risks(sides, groups):
    """2.5.5 問い（kind sentence_type、subkind question）。組になった文の片方だけが問いの文（文末が ？、?、か。、か？）なら出す。
    句点のない「…か」で終わる文は問いに数えない（10.2 D5）。"""
    out = []
    order = 0
    for group in groups:
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            old_question, new_question = _is_question(old.text), _is_question(new.text)
            if old_question != new_question:
                out.append((group["hunk"]["index"], order, _risk(
                    "sentence_type", "question", old.line, new.line, old.text, new.text,
                    {"old_is_question": old_question, "new_is_question": new_question})))
                order += 1
    return out

def _is_quote_row(row):
    """引用の行か。「>」のない引用の続きの行（遅延継続。kind は quote、quote_depth は0）も引用とする（反証レビュー F10）。"""
    return bool(row["quote_depth"]) or row["kind"] == "quote"


def _protected_spans(sides, side):
    """変えない箇所の範囲 [(始め, 終わり, 種類)]（位置の順）と、始まりの位置の並び。画像はパスだけを範囲にする。"""
    found = []
    text = sides.texts[side]
    for left, right, kind in sides.analyses[side]["protected_spans"]:
        if kind not in _PROTECTED_SPANS:
            continue
        if kind == "image":
            left = _image_path_start(text, left, right)
            if left >= right:
                continue
        elif kind == "reference_definition" and right > left and text[right - 1:right] == "\n":
            right -= 1
        found.append((left, right, kind))
    found.sort()
    return found, [left for left, _, _ in found]


def _protected_risks(sides, full):
    """2.5.7 変えない箇所（kind protected）。変わった文字の範囲が protected_spans（inline_code、autolink、link_destination、
    bare_url、code、frontmatter、html_block、html_token、リンクの定義、画像のパス）か引用のブロックに重なれば出す。
    空白だけの変更でも出す。追加と削除の塊は行の種類で決める。hunk と subkind ごとに1つ。
    文字の対応を省いた置き換えの塊（予算）は、変えない箇所の中身を種類ごとに両側で並べて比べ、違う種類だけを出す
    （インラインのコードやリンク先は行の種類に出ないため。反証レビュー E8）。

    行番号は、元と後のそれぞれで最初に当たった行。片側だけで当たったときは、1行が1行に変わった塊なら相手の行を、
    そうでなければ None を入れる（大きな書き換えで、関係のない行を相手として出さないため）。"""
    spans = [_protected_spans(sides, 0), _protected_spans(sides, 1)]
    out = []
    for hunk in full["hunks"]:
        found = OrderedDict()

        def hit(subkind, block, side, line_no):
            entry = found.setdefault(subkind, [block, [None, None]])
            if entry[1][side] is None:
                entry[1][side] = line_no

        if hunk["segments"] is not None:
            bases = (sides.starts[0][hunk["old_start"] - 1], sides.starts[1][hunk["new_start"] - 1])
            offsets = [0, 0]
            for tag, text in hunk["segments"]:
                if tag == "=":
                    offsets[0] += len(text)
                    offsets[1] += len(text)
                    continue
                side = 0 if tag == "-" else 1
                left = bases[side] + offsets[side]
                for subkind, block, line_no in _protected_hits(sides, side, left, left + len(text), spans[side]):
                    hit(subkind, block, side, line_no)
                offsets[side] += len(text)
        elif hunk["tag"] == "replace":
            contents = [_protected_contents(sides, side, hunk, spans[side]) for side in (0, 1)]
            for subkind in OrderedDict((key, None) for key in list(contents[0]) + list(contents[1])):
                old_items, new_items = contents[0].get(subkind, []), contents[1].get(subkind, [])
                if [text for _, text, _ in old_items] == [text for _, text, _ in new_items]:
                    continue
                for side, items in ((0, old_items), (1, new_items)):
                    other = new_items if side == 0 else old_items
                    for position, (block, text, line_no) in enumerate(items):
                        if position >= len(other) or other[position][1] != text:
                            hit(subkind, block, side, line_no)
                            break
                    else:
                        if items:
                            hit(subkind, items[0][0], side, items[0][2])
        else:
            for side, first, last in ((0, hunk["old_start"], hunk["old_end"]), (1, hunk["new_start"], hunk["new_end"])):
                rows = sides.analyses[side]["lines"]
                for line_no in range(first, last + 1):
                    row = rows[line_no - 1]
                    subkind = _PROTECTED_LINES.get(row["kind"]) or ("quote" if _is_quote_row(row) else None)
                    if subkind is not None:
                        hit(subkind, row["kind"] if subkind != "quote" else "quote", side, line_no)
        one_to_one = (hunk["tag"] == "replace" and hunk["old_start"] == hunk["old_end"]
                      and hunk["new_start"] == hunk["new_end"])
        for order, (subkind, (block, (old_line, new_line))) in enumerate(found.items()):
            if one_to_one:
                old_line, new_line = hunk["old_start"], hunk["new_start"]
            old = sides.lines[0][old_line - 1] if old_line else None
            new = sides.lines[1][new_line - 1] if new_line else None
            out.append((hunk["index"], order, _risk("protected", subkind, old_line, new_line, old, new, {"block": block})))
    return out


def _protected_contents(sides, side, hunk, spans):
    """hunk のその側の行の中の、変えない箇所の中身。{subkind: [(種類, 中身, 行番号)]}（位置の順）。
    範囲が hunk の外にまたがるときは、hunk の中の部分だけを中身にする。引用は行ごと。"""
    first, last = ("old_start", "old_end") if side == 0 else ("new_start", "new_end")
    if hunk[last] < hunk[first]:
        return {}
    text = sides.texts[side]
    low = sides.starts[side][hunk[first] - 1]
    high = sides.starts[side][hunk[last] - 1] + len(sides.lines[side][hunk[last] - 1])
    found = OrderedDict()
    span_list, lefts = spans
    index = max(0, bisect_right(lefts, low) - 1)
    while index < len(span_list) and span_list[index][0] < high:
        left, right, kind = span_list[index]
        if right > low:
            start = max(left, low)
            found.setdefault(_PROTECTED_SPANS[kind], []).append(
                (kind, text[start:min(right, high)], sides.line_of(side, start)))
        index += 1
    rows = sides.analyses[side]["lines"]
    for line_no in range(hunk[first], hunk[last] + 1):
        if line_no - 1 < len(rows) and _is_quote_row(rows[line_no - 1]):
            found.setdefault("quote", []).append(("quote", sides.lines[side][line_no - 1], line_no))
    return found


def _protected_hits(sides, side, left, right, spans):
    """文字の範囲 [left, right) に重なる、変えない箇所の (subkind, 種類, 行番号) を返す。行番号は重なりが始まる行。"""
    found, lefts = spans
    hits = []
    index = max(0, bisect_right(lefts, left) - 1)
    while index < len(found) and found[index][0] < right:
        span_left, span_right, kind = found[index]
        if span_right > left:
            hits.append((_PROTECTED_SPANS[kind], kind, sides.line_of(side, max(left, span_left))))
        index += 1
    rows = sides.analyses[side]["lines"]
    for line_no in range(sides.line_of(side, left), sides.line_of(side, right - 1) + 1):
        if line_no - 1 < len(rows) and _is_quote_row(rows[line_no - 1]):
            hits.append(("quote", "quote", line_no))
            break
    return hits


def _find_line(sides, side, text):
    """9キーの分析（正規化した文）の文が、生の文の何行目にあるか。最初の文の頭（20字まで）を、行ごとに正規化した文から探す。
    見つからなければ None。"""
    head = text.split("\n")[0]
    end = _SENTENCE_END.search(head)
    head = (head[:end.end()] if end else head).strip()[:20]
    if not head:
        return None
    for index, line in enumerate(sides.normalized_lines(side)):
        if head in line:
            return index + 1
    return None


def _marks_risks(sides, type_changes):
    """2.5.6 文の種類の印（kind sentence_type、subkind marks）。type_changes の各項目をそのまま数える（判定は変えない）。"""
    return [_risk("sentence_type", "marks", _find_line(sides, 0, change["orig"]), _find_line(sides, 1, change["rewrite"]),
                  change["orig"], change["rewrite"], {"lost": change["lost"], "added": change["added"]})
            for change in (type_changes or [])]


def meaning_risks(orig, rw, full=None, type_changes=None):
    """意味が変わる恐れ（DESIGN-interfaces.md 2.5、2.8 の meaning_risks）。

    full は full_diff(orig, rw) の戻り値（渡さなければ作る）。type_changes は diff() の type_changes で、
    None か [] なら文の種類の印（sentence_type/marks）を含めない。この関数の中で9キーの分析は作らない。"""
    if full is None:
        full = full_diff(orig, rw)
    return _meaning_risks(_Sides(orig, rw), full, type_changes)


def _meaning_risks(sides, full, type_changes):
    groups = _sentence_pairs(sides, full)
    found = (_number_risks(sides, full, groups) + _negation_risks(sides, groups) + _swap_risks(sides, groups)
             + _question_risks(sides, groups) + _protected_risks(sides, full))
    found.sort(key=lambda item: (item[0], _RISK_ORDER.get(item[2]["kind"], 9), item[1]))
    return [risk for _, _, risk in found] + _marks_risks(sides, type_changes)


# ---- 資料との照合（DESIGN-interfaces.md 3.3。yomiyasu_check.py がプロセスの中で呼ぶ）----
# 照らすのは数値、名前、語、確度の語だけ。主張、条件、担当が資料どおりかは判定しない。

# 名前（製品名や識別子）。NFKC のあとの英数字2字以上
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.+#/-]*[A-Za-z0-9]")
# URL の頭（https:// など）は名前にしない（残りの example.com/guide を1つの名前として照らす）。
# 頭の長さに上限を置く（「a.b.c.d…」のような長い並びで2乗の時間にしない）
_URL_SCHEME = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{0,31}://")
# 語（CONTENT のうち、漢字2字以上と片仮名2字以上）
_GROUND_WORD = re.compile(r"[一-龥々〆ヵヶ]{2,}|[ァ-ヴー]{2,}")
# 確度の語。「はず」は「はずれ」「はずす」の頭を除く
_CERTAINTY_WORDS = ("未確認", "未定", "予定", "検討中", "調査中", "見込み", "可能性", "かもしれ", "はず", "確認済み", "確定", "暫定")
_CERTAINTY = re.compile("|".join(re.escape(word) + ("(?![れさしすせ])" if word == "はず" else "")
                                 for word in sorted(_CERTAINTY_WORDS, key=len, reverse=True)))
# 名前と語を取る前に伏せる protected_spans の種類（Markdown や HTML の書き方の語を拾わない）
_GROUND_MASKED = ("frontmatter", "html_block", "html_token")
_GROUND_NOT_JUDGED = ["claims", "conditions", "assignees", "meaning_equivalence"]
_GROUND_KIND_ORDER = {"number": 0, "name": 1, "word": 2, "certainty": 3}


class _Doc(_Sides):
    """1つの文書の行、行の位置、Markdown の解析、数値（_Sides の片側だけ）。"""

    def __init__(self, text):
        self.texts = (text,)
        self.lines = (_split_lines(text),)
        self.starts = (_line_starts(self.lines[0]),)
        self.analyses = (_analyze(text),)
        self._normalized = [None]
        self._numbers = [None]
        self._sentences = None

    def sentence_at(self, position):
        """位置を含む文（2.5.1 と同じ分け方）を返す。文に分けない行（コードなど）なら、その行を丸ごと返す。"""
        if self._sentences is None:
            found = _line_sentences(self, 0, 0, len(self.lines[0]))
            self._sentences = (found, [sentence.start for sentence in found])
        found, starts = self._sentences
        index = bisect_right(starts, position) - 1
        if index >= 0 and position < found[index].start + len(found[index].text):
            return found[index].text
        return self.lines[0][self.line_of(0, position) - 1].strip()


def _squash(text):
    """「ある」の判定に使う形（NFKC にして空白と強調の記号「*」を除く）。資料で「**本番**環境」と太字で分かれた語も、
    最終稿の「本番環境」と同じとみなす（太字の有無は書式だけの違い。反証レビュー F3）。"""
    return _SQUASHED.sub("", unicodedata.normalize("NFKC", text))


_SQUASHED = re.compile(r"[\s*]+")


def _ground_mask(text, analysis):
    """名前と語を取り出す文字列。全角を半角にし、先頭の設定と HTML を同じ長さの空白にする（位置は変えない）。"""
    chars = list(text.translate(_HALF_WIDTH))
    for left, right, kind in analysis["protected_spans"]:
        if kind in _GROUND_MASKED:
            for index in range(left, min(right, len(chars))):
                if chars[index] != "\n":
                    chars[index] = " "
    masked = "".join(chars)
    return _URL_SCHEME.sub(lambda match: " " * len(match.group(0)), masked)


def _ground_items(doc):
    """最終稿の項目を取り出す。{(kind, 比べる形): {"kind", "text", "value", "unit", "lines", "start", "key"}} を出てきた順に。"""
    text = doc.texts[0]
    found = OrderedDict()

    def add(kind, key, start, end, value=None, unit=None):
        line = doc.line_of(0, start)
        entry = found.get((kind, key))
        if entry is None:
            found[(kind, key)] = {"kind": kind, "text": text[start:end], "value": value, "unit": unit,
                                  "lines": [line], "start": start, "key": key}
        elif entry["lines"][-1] != line:
            entry["lines"].append(line)

    for number in doc.numbers(0)[0]:
        add("number", number.key, number.start, number.end, number.value, number.unit)
    masked = _ground_mask(text, doc.analyses[0])
    for match in _NAME.finditer(masked):
        add("name", _squash(match.group(0)), match.start(), match.end())
    for match in _CERTAINTY.finditer(text):
        add("certainty", match.group(0), match.start(), match.end())
    certainty = set(_CERTAINTY_WORDS)
    for match in _GROUND_WORD.finditer(masked):
        if match.group(0) not in certainty:
            add("word", match.group(0), match.start(), match.end())
    return found


class _Source:
    """照らす文（原文か資料）の、比べる形（数値の (数, 単位) の集合と、NFKC にして空白を除いた文）。"""

    def __init__(self, text):
        self.text = text
        analysis = _analyze(text)
        self.numbers = set(number.key for number in _find_numbers(text, analysis))
        self.squashed = _squash(text)
        # 同じ取り出し方で取った名前と語の集合。項目ごとに資料の全文を探すと「項目の数×資料の字数」の時間になるので、
        # まず集合で引き、ないときだけ部分文字列を探す（結果は部分文字列で探すのと同じ。反証レビュー F14）
        masked = _ground_mask(text, analysis)
        self.words = set(_squash(match.group(0)) for match in _NAME.finditer(masked))
        self.words.update(match.group(0) for match in _GROUND_WORD.finditer(masked))
        self.words.update(match.group(0) for match in _CERTAINTY.finditer(text))

    def has(self, kind, key):
        if kind == "number":
            return key in self.numbers
        return key in self.words or key in self.squashed


def ground(final, materials, original=None):
    """資料との照合（DESIGN-interfaces.md 3.3、10.3 C1・C2）。final は最終稿、materials は資料の文字列の並び、
    original は原文（推敲のとき。なければ新規作成）。照合の JSON（attempt-<n>.materials.json の形）を返す。

    取る項目は数値（2.5.2 の取り出し方、(数, 単位) で比べる）、名前（英数字2字以上）、語（漢字2字以上と片仮名2字以上）、
    確度の語。名前と語と確度の語は、NFKC にして空白を除いた文字列の部分文字列かで「ある」とみなす。
    分類は in_original（原文にある）、from_materials（原文になく資料にある）、not_in_sources（どちらにもない）、
    dropped_certainty（資料にある確度の語が最終稿にない）。

    意味が変わる恐れ（kind unsupported）に入れるもの: 新規作成で資料にない数値（subkind number）と、両方のモードで資料にない
    名前（subkind name）。推敲の数値は diff の数値の候補の basis で扱う（check が "material" か "none" を入れる）ので入れない。
    candidate_count は、意味が変わる恐れの数に、照合の節の見直し候補の行（新規作成の「資料にない語」、確度の語、
    推敲の「資料に基づく補足の候補」）を1行ずつ足したもの。「参考」の行は数えない。"""
    mode = "rewrite" if original is not None else "compose"
    materials = list(materials)
    doc = _Doc(final)
    original_source = _Source(original) if original is not None else None
    material_sources = [_Source(text) for text in materials]
    sources = []
    if original is not None:
        sources.append({"role": "source", "index": 1, "chars": len(original)})
    for index, text in enumerate(materials, 1):
        sources.append({"role": "material", "index": index, "chars": len(text)})

    items, risks = [], []
    found = _ground_items(doc)
    for (kind, key), entry in sorted(found.items(), key=lambda pair: (_GROUND_KIND_ORDER[pair[0][0]], pair[1]["start"])):
        if original_source is not None and original_source.has(kind, key):
            classification = "in_original"
        elif any(source.has(kind, key) for source in material_sources):
            classification = "from_materials"
        else:
            classification = "not_in_sources"
        items.append({"kind": kind, "text": entry["text"], "value": entry["value"], "unit": entry["unit"],
                      "final_lines": entry["lines"], "classification": classification})
        if classification != "not_in_sources":
            continue
        if kind == "number" and mode == "compose":
            detail = {"text": entry["text"], "value": entry["value"], "unit": entry["unit"]}
        elif kind == "name":
            detail = {"text": entry["text"]}
        else:
            continue
        risks.append((entry["start"], _risk("unsupported", kind, None, entry["lines"][0], None,
                                            doc.sentence_at(entry["start"]), detail)))
    final_certainty = set(key for kind, key in found if kind == "certainty")
    dropped = OrderedDict()
    for source in material_sources:
        for match in _CERTAINTY.finditer(source.text):
            if match.group(0) not in final_certainty and match.group(0) not in dropped:
                dropped[match.group(0)] = None
    for word in dropped:
        items.append({"kind": "certainty", "text": word, "value": None, "unit": None, "final_lines": [],
                      "classification": "dropped_certainty"})

    risks = [risk for _, risk in sorted(risks, key=lambda pair: pair[0])]
    lines = 0
    if mode == "compose" and any(item["kind"] == "word" and item["classification"] == "not_in_sources" for item in items):
        lines += 1
    if dropped:
        lines += 1
    if mode == "rewrite" and any(item["classification"] == "from_materials" for item in items):
        lines += 1
    return {"format": "yomiyasu-materials", "format_version": MATERIALS_FORMAT_VERSION, "tool_version": __version__,
            "mode": mode, "sources": sources, "items": items, "meaning_risks": risks,
            "candidate_count": len(risks) + lines, "meaning_risk_count": len(risks),
            "not_judged": list(_GROUND_NOT_JUDGED)}


# ---- diff() ----

def diff(orig_raw: str, rw_raw: str, stance=None, *, encoding_notes=None) -> dict:
    """元の文と書き直した文を比べる（DESIGN-interfaces.md 2.8 の形式2）。

    渡された文字列をそのまま使う（BOM を外したり、改行をそろえたりしない。CLI と check は読むときに decode_source で
    そろえ、違いを encoding_notes で渡す）。stance は STANCES の値（勧め、決まり、説明）か None。"""
    rules = _rule_candidates(orig_raw, rw_raw, stance)
    full, sides = _build_full_diff(orig_raw, rw_raw, encoding_notes)
    risks = _meaning_risks(sides, full, rules["type_changes"])
    if orig_raw == rw_raw and not full["encoding_notes"]:
        status, count = "no_change", 0
    else:
        count = sum(1 for risk in risks if (risk["kind"], risk["subkind"]) != ("sentence_type", "marks"))
        count += _rule_count(rules, bool(full["hunks"]))
        status = "has_candidates" if count else "changed_without_candidates"
    out = {"format": "yomiyasu-diff", "format_version": DIFF_FORMAT_VERSION, "tool_version": __version__,
           "status": status, "changed": status != "no_change", "candidate_count": count,
           "meaning_risk_count": len(risks), "fail_on_meaning_risk_count": fail_on_count(risks),
           "not_judged": ["meaning_equivalence", "reader_comprehension"], "meaning_risks": risks}
    out.update(rules)
    out["full_diff"] = full
    return out


def _shows_rewritten_only(d):
    """書き直した文だけを見る候補（logic、bold、endings.flags）を数え、出すか。
    変更がない（no_change）か、行の差がない（改行コード、BOM、末尾の改行だけが違う）ときは出さない（2.6、10.2 D9）。"""
    return d.get("status") != "no_change" and bool(d["full_diff"]["hunks"])


def _rule_count(d, rewritten_only):
    """規則の見直し候補の数（レポートの行の数に合わせる。2.6）。"""
    e = d.get("endings") or {}
    count = (len(d["markers"]) + bool(d["new_words"]) + bool(d["lost_words"]) + len(d["structure"])
             + len(e.get("changes") or []) + len(d.get("type_changes") or []))
    if rewritten_only:
        count += len(d.get("logic") or []) + len(e.get("flags") or []) + len(d.get("bold") or [])
    return count



# ---- 人が読む出力（v2.0.0。DESIGN-interfaces.md 2.4、2.7）----

_REPORT_FIRST_LINE = "差分の検査を実行しました。"
_REPORT_DISCLAIMER = ("全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。"
                      "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。")


def _status_line(d):
    """状態の行（2.6）。変更の数は hunk の数。"""
    if d["status"] == "no_change":
        return "状態: 変更なし"
    places = len(d["full_diff"]["hunks"])
    if d["status"] == "changed_without_candidates":
        if not places:
            return "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 0か所。改行コード・BOM・末尾の改行だけが違う）"
        return "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 {}か所）".format(places)
    return "状態: 変更あり（{}か所）。見直し候補 {}件、うち意味が変わる恐れ {}件".format(
        places, d["candidate_count"], d["meaning_risk_count"])


def _where(old_line, new_line):
    if old_line is not None and new_line is not None:
        return "（{}行目）".format(old_line) if old_line == new_line else "（元{}行目 → 後{}行目）".format(old_line, new_line)
    if old_line is not None:
        return "（元{}行目）".format(old_line)
    if new_line is not None:
        return "（後{}行目）".format(new_line)
    return ""


def _risk_line(risk):
    """意味が変わる恐れの1行（先頭の「- 」は付けない）。"""
    kind, subkind, detail = risk["kind"], risk.get("subkind"), risk.get("detail") or {}
    old_line, new_line = risk.get("old_line"), risk.get("new_line")
    where = _where(old_line, new_line)
    if kind == "number":
        if subkind == "lost":
            text = "消えた数値{}: {}".format(_where(old_line, None) if old_line is not None else where,
                                          "、".join(detail.get("removed", [])))
        elif subkind == "added":
            text = "元にない数値{}: {}".format(_where(None, new_line) if new_line is not None else where,
                                          "、".join(detail.get("added", [])))
        elif subkind == "order":
            text = "数値の並びが変わった{}: {} → {}".format(where, "、".join(detail.get("old_order", [])),
                                                    "、".join(detail.get("new_order", [])))
        else:
            text = "数値が変わった{}: {} → {}".format(where, "、".join(detail.get("removed", [])),
                                                "、".join(detail.get("added", [])))
        if risk.get("basis") == "material":
            text += "（資料にある値）"
        return text
    if kind == "negation":
        return "否定の有無が変わった{}: {} → {}".format(where, detail.get("old", ""), detail.get("new", ""))
    if kind == "swap":
        return "「が」「を」などが入れ替わった{}: {}".format(
            where, "、".join("{} {}→{}".format(pair["word"], pair["old"], pair["new"]) for pair in detail.get("pairs", [])))
    if kind == "sentence_type" and subkind == "question":
        if detail.get("old_is_question"):
            return "問いの文が問いでなくなった{}".format(where)
        return "問いでない文が問いになった{}".format(where)
    if kind == "protected":
        return "{}が変わった{}".format(_PROTECTED_LABELS.get(subkind, subkind), where)
    if kind == "unsupported":
        # 資料との照合（3.3。check が ground() の結果を同じ節に並べる）。最終稿の側の行だけを書く
        label = "資料にない数値" if subkind == "number" else "資料にない名前"
        return "{}{}: {}".format(label, _where(None, new_line) if new_line is not None else where, detail.get("text", ""))
    return "{}{}".format(kind + ("/" + subkind if subkind else ""), where)


def _risk_section(d):
    risks = d.get("meaning_risks") or []
    if not risks:
        return ""
    lines = ["■ 意味が変わる恐れ（{}件。原文と資料に照らして確かめる）".format(len(risks))]
    marks = 0
    for risk in risks:
        if (risk["kind"], risk.get("subkind")) == ("sentence_type", "marks"):
            marks += 1
            continue
        lines.append("- " + _risk_line(risk))
        if risk.get("old") is not None:
            lines.append("  元: " + risk["old"])
        if risk.get("new") is not None:
            lines.append("  後: " + risk["new"])
    if marks:
        lines.append("- 文の種類の印が変わった: {}件（下の「■ 文の種類の印が変わった文」を見る）".format(marks))
    return "\n".join(lines)


def _rule_lines(d, rewritten_only=True):
    """規則の見直し候補の行（v1.1.2 の report() と同じ見出し、順、文）。rewritten_only が偽なら、書き直した文だけを見る
    候補（つながり、文末の立場、太字）を出さない。"""
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
    if rewritten_only and d.get("logic"):
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
    if rewritten_only and e.get("flags"):
        head = f"■ 文末の立場（{e['stance']}の文書として見た）" if e.get("stance") else "■ 文末の立場が混ざっている候補（立場を決めてから見る）"
        lines.append(head)
        for f in e["flags"]:
            lines.append(f"- {f['note']}")
            for s in f["sentences"]:
                lines.append(f"  ・{s if len(s) <= 44 else s[:44] + '…'}")
    if rewritten_only and d.get("bold"):
        lines.append(bold_head("書き直した文。"))
        lines.extend(bold_lines(d["bold"]))
    return lines


def _rule_section(d):
    rewritten_only = _shows_rewritten_only(d)
    lines = _rule_lines(d, rewritten_only)
    if not lines:
        return ""
    return "■ 規則の見直し候補（{}件）\n".format(_rule_count(d, rewritten_only)) + "\n".join(lines)


def _visible(text):
    """「差:」の印の中の見えない文字を名前にする。空白（〔空白〕、〔空白 U+00A0〕など）と、幅のない書式の字
    （Unicode の分類 Cf。ゼロ幅スペース U+200B、ソフトハイフン U+00AD など。〔U+200B〕の形）。"""
    out = []
    for ch in text:
        if ch in _VISIBLE:
            out.append(_VISIBLE[ch])
        elif ch.isspace():
            out.append("〔空白 U+{:04X}〕".format(ord(ch)))
        elif unicodedata.category(ch) == "Cf":
            out.append("〔U+{:04X}〕".format(ord(ch)))
        else:
            out.append(ch)
    return "".join(out)


def _marked(tag, text):
    return ("[-" + _visible(text) + "-]") if tag == "-" else ("{+" + _visible(text) + "+}")


def _show_line(line):
    """「元:」「後:」の行の中身。空の行は〔空行〕、空白だけの行は見える名前にする。ほかは丸ごとそのまま。"""
    if line == "":
        return "〔空行〕"
    if _is_blank(line):
        return _visible(line)
    return line


def _diff_rows(segments):
    """segments を行ごとの「差:」の文字列にする。印の外の改行で行を分ける（印の中の改行は〔改行〕）。"""
    rows = [""]
    for tag, text in segments:
        if tag == "=":
            pieces = text.split("\n")
            rows[-1] += pieces[0]
            rows.extend(pieces[1:])
        else:
            rows[-1] += _marked(tag, text)
    return rows


def _short_diff(segments):
    """長い行の「差:」。印の外の文の切れ目で文に分け、変わった文だけを残して、変わらない文の並びは「…」にする。"""
    units = [[False, ""]]
    for tag, text in segments:
        if tag != "=":
            units[-1][0] = True
            units[-1][1] += _marked(tag, text)
            continue
        position = 0
        for match in _SENTENCE_END.finditer(text):
            units[-1][1] += text[position:match.end()]
            units.append([False, ""])
            position = match.end()
        units[-1][1] += text[position:]
    out, skipped, omitted = [], False, False
    for changed, text in units:
        if not text:
            continue
        if changed:
            out.append(text)
            skipped = False
        elif not skipped:
            out.append("…")
            skipped = omitted = True
    if not omitted:
        # 文の切れ目がなく、何も省かなかった（行の全体を出した）ときは、省略の添え書きを付けない
        return "".join(out)
    return "".join(out) + "（変わらない文は省略。元と後は上に全文）"


def _diff_line(hunk):
    """1行が1行に変わった塊の「差:」（補助の行）。出さないときは None。"""
    segments = hunk["segments"]
    if hunk["tag"] != "replace" or segments is None or len(hunk["old_lines"]) != 1 or len(hunk["new_lines"]) != 1:
        return None
    places, inside, changed = 0, False, 0
    for tag, text in segments:
        if tag == "=":
            inside = False
            continue
        if not inside:
            places += 1
            inside = True
        changed += len(text)
    old_line, new_line = hunk["old_lines"][0], hunk["new_lines"][0]
    # 変わった箇所が5か所以上か、消した文字と足した文字の合計が元の行の半分を超えるときは、元と後で読むほうが速い
    if places >= 5 or changed > len(old_line) / 2:
        return None
    if len(old_line) > _LONG_LINE or len(new_line) > _LONG_LINE:
        return _short_diff(segments)
    return _diff_rows(segments)[0]


def _range(start, end):
    return str(start) if start == end else "{}-{}".format(start, end)


def _hunk_heading(hunk):
    old_kinds = "・".join(OrderedDict((_BLOCK_NAMES.get(k, "その他"), None) for k in hunk["old_blocks"]))
    new_kinds = "・".join(OrderedDict((_BLOCK_NAMES.get(k, "その他"), None) for k in hunk["new_blocks"]))
    if hunk["tag"] == "insert":
        head, kinds = "@ 後{}行目を追加".format(_range(hunk["new_start"], hunk["new_end"])), new_kinds
    elif hunk["tag"] == "delete":
        head, kinds = "@ 元{}行目を削除".format(_range(hunk["old_start"], hunk["old_end"])), old_kinds
    else:
        head = "@ 元{}行目 → 後{}行目".format(_range(hunk["old_start"], hunk["old_end"]), _range(hunk["new_start"], hunk["new_end"]))
        kinds = old_kinds if old_kinds == new_kinds else "{} → {}".format(old_kinds, new_kinds)
    notes = [kinds]
    for note in hunk["notes"]:
        if note["kind"] == "whitespace_only":
            notes.append("空白だけ")
        elif note["kind"] == "heading_level":
            notes.append("見出しの段 {} → {}".format(note["old"], note["new"]))
        elif note["kind"] == "moved_to":
            notes.append("移した行。後{}行目へ".format(note["line"]))
        elif note["kind"] == "moved_from":
            notes.append("移した行。元{}行目から".format(note["line"]))
    return head + "（" + "、".join(notes) + "）"


def _yes(value):
    return "あり" if value else "なし"


def _full_diff_section(d):
    full = d["full_diff"]
    hunks = full["hunks"]
    notes = []
    for note in full.get("encoding_notes") or []:
        if note["kind"] == "eol":
            notes.append("- 改行コード: {} → {}（行ごとの差には出していません）".format(
                _EOL_NAMES.get(note["old"], note["old"]), _EOL_NAMES.get(note["new"], note["new"])))
        elif note["kind"] == "bom":
            notes.append("- 先頭のBOM: {} → {}".format(_yes(note["old"]), _yes(note["new"])))
    if full["final_newline"]["old"] != full["final_newline"]["new"]:
        notes.append("- 末尾の改行: {} → {}".format(_yes(full["final_newline"]["old"]), _yes(full["final_newline"]["new"])))
    if not hunks and not notes:
        return "■ 全文差分: 変わった箇所はありません。"
    lines = ["■ 全文差分（変更 {}か所。省略していません）".format(len(hunks))] + notes
    for hunk in hunks:
        lines.append(_hunk_heading(hunk))
        if hunk["whitespace_only"] and hunk["tag"] == "replace" and hunk["segments"] is not None:
            # 空白だけが違う行の組は、元と後が同じに見えるので、差だけを出す（5か所・半分の条件を当てない）
            lines.extend("  差: " + row for row in _diff_rows(hunk["segments"]))
            continue
        lines.extend("  元: " + _show_line(line) for line in hunk["old_lines"])
        lines.extend("  後: " + _show_line(line) for line in hunk["new_lines"])
        row = _diff_line(hunk)
        if row is not None:
            lines.append("  差: " + row)
    return "\n".join(lines)


def report_parts(d: dict) -> dict:
    """レポートの3つの節の文字列（{"risks", "rules", "full_diff"}）。ない節は空の文字列。末尾に改行は付けない。"""
    return {"risks": _risk_section(d), "rules": _rule_section(d), "full_diff": _full_diff_section(d)}


def report(d: dict) -> str:
    """人が読むレポート（2.7）。1行目、状態の行、断り、意味が変わる恐れ、規則の見直し候補、全文差分、状態の行の順。
    末尾に改行は付けない。"""
    status = _status_line(d)
    parts = report_parts(d)
    body = [part for part in (parts["risks"], parts["rules"], parts["full_diff"]) if part]
    return "\n".join([_REPORT_FIRST_LINE, status, _REPORT_DISCLAIMER]) + "\n\n" + "\n\n".join(body) + "\n\n" + status


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ---- CLI ----

_EXIT_CODES = """終了コード:
  0  比べ終わり、--fail-on の条件に当たらなかった（候補の有無によらない）。--endings の正常終了、-h と --version も0
  1  --fail-on=meaning-risk の条件に当たった（数値、否定、主語と目的語の入れ替え、文の種類の恐れが1件以上）
  2  使い方か入力の誤り（ファイルを開けない、UTF-8 として読めない、標準入力を読めない、使えない --stance や --fail-on の値、ファイルの数の誤り）
  3  予期しない内部の誤り（標準エラーにトレースバックを出す）か、出力先が閉じられて結果を最後まで書けなかった"""
_USAGE = ("yomiyasu_diff.py [--stance 立場] [--json] [--fail-on meaning-risk] 元の文 書き直した文\n"
          "       yomiyasu_diff.py --endings ファイル [--stance 立場]\n"
          "       yomiyasu_diff.py --version")
_FAIL_ON_HELP = ("意味が変わる恐れのうち、数値、否定、主語と目的語の入れ替え、文の種類（問いと平叙、文の種類の印）の変化が"
                 "1件でもあれば、終了コード1で終わります。コード・URL・引用など変えない箇所の変化は、意味が変わる恐れとして出しますが、"
                 "この条件には数えません。候補は確かめる場所で、意味が変わったという判定ではありません。"
                 "条件に当たらなくても、意味が同じだという証明にはなりません。")


class _ArgumentParser(argparse.ArgumentParser):
    # argparse は、書く先の流れがない（None の）とき、もう一方の流れに書く（使い方が標準出力に、
    # ヘルプが標準エラーに出る）。3.10 までは標準エラーがないと使い方の誤りで AttributeError になる。
    # pythonw や 2>&- のときも、書く先がなければ何も書かずに同じ終了コードで終える。

    def error(self, message):
        stream = sys.stderr
        if stream is None:
            self.exit(2)
        # 使い方の誤りを標準エラーに書く前に、ほかの誤りの文と同じく UTF-8 にする。
        # argparse の英語の行のあとに、日本語の案内を1行足す（10.5 M2）。
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
    parser = _ArgumentParser(
        prog="yomiyasu_diff.py",
        usage=_USAGE,
        description=("元の文と書き直した文を比べ、変わった箇所をすべて出し、意味が変わる恐れと規則の見直し候補を挙げます。"
                     "全文差分は意味が同じだという証明ではありません。意味が同じかどうかは判定しません。"),
        epilog=_EXIT_CODES,
        formatter_class=_HelpFormatter,
        add_help=False,
        # 省略形（--js など）は受けない。lint、diff、check の3本でそろえる（DESIGN-interfaces.md 10.7）
        allow_abbrev=False,
    )
    arguments = parser.add_argument_group("引数")
    arguments.add_argument("files", nargs="*", metavar="ファイル",
                           help="比べる2つのファイル（UTF-8）。元の文、書き直した文の順に渡します。"
                                "どちらか1つに - を渡すと標準入力を読みます。--endings のときは1つだけ渡します。")
    options = parser.add_argument_group("オプション")
    options.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
    options.add_argument("--stance", metavar="立場",
                         help="文書の立場。勧め（読み手に勧める）、決まり（手順）、説明（報告、体験）のどれか。"
                              "文末の見直し候補の出し方が変わります。")
    options.add_argument("--json", action="store_true",
                         help="結果をJSON（形式2）で出します。日本語は \\uXXXX の形で出します。")
    options.add_argument("--fail-on", action="append", dest="fail_on", metavar="meaning-risk",
                         help=_FAIL_ON_HELP + "何度でも、カンマ区切りでも指定できます。")
    options.add_argument("--endings", action="store_true",
                         help="1つのファイルの文末の種類と、立場の混ざりだけを見ます（--json と --fail-on は使えません）。")
    options.add_argument("--version", action="store_true", help="版を表示して終わります。")
    parser.set_defaults(fail_on=[])
    return parser


def _version_line():
    return "yomiyasu_diff.py {} (JSON format {})".format(__version__, DIFF_FORMAT_VERSION)


def _use_utf8(stream, **options):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", **options)


def _error(message):
    """標準エラーに1行書く。標準エラーがないとき（pythonw など）は何もしない。"""
    stream = sys.stderr
    if stream is None:
        return
    try:
        _use_utf8(stream, errors="backslashreplace")
        print(message, file=stream)
    except (OSError, ValueError):
        # 標準エラーも閉じられているときは、書かずに終える。
        pass


def _fail_on(values):
    """--fail-on の値を確かめる。(meaning-risk を指定したか, 誤りの文か None) を返す。"""
    hit = False
    for value in values:
        # 大文字と小文字、「_」と「-」は区別しない（MEANING_RISK も受ける。10.5 M5）。
        pieces = [piece.strip().lower().replace("_", "-") for piece in value.split(",") if piece.strip()]
        if not pieces:
            # 空、空白だけ、カンマだけの値は、目に見えないので「（空）」と書く。
            return False, "--fail-on に使えない値です: （空）。diff で使えるのは meaning-risk です。"
        for piece in pieces:
            if piece != "meaning-risk":
                return False, "--fail-on に使えない値です: {}。diff で使えるのは meaning-risk です。".format(piece)
            hit = True
    return hit, None


def _fail_on_line(total, counted):
    """--fail-on=meaning-risk に当たったときの最後の行。数えない種類（変えない箇所）が混ざるときは、全件と数えた件数を書く。"""
    if total == counted:
        return "終了コード1: --fail-on=meaning-risk の条件に当たりました（意味が変わる恐れ {}件）。".format(counted)
    return ("終了コード1: --fail-on=meaning-risk の条件に当たりました"
            "（意味が変わる恐れ {}件のうち、数値・否定・入れ替え・文の種類 {}件）。".format(total, counted))


def _read_input(path):
    """ファイルか標準入力（-）を読み、(文字列, decode_source の情報, None) か (None, None, 誤りの文) を返す。"""
    if path != "-":
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except (OSError, ValueError) as error:
            reason = getattr(error, "strerror", None) or error
            return None, None, "Error opening file {}: ファイルを開けません（{}）".format(path, reason)
        try:
            text, info = decode_source(data)
        except UnicodeDecodeError:
            return None, None, "Error opening file {}: UTF-8 として読めません".format(path)
        return text, info, None
    stream = sys.stdin
    if stream is None:
        return None, None, "Error reading stdin: 標準入力を読めません（標準入力がありません）"
    try:
        buffer = getattr(stream, "buffer", None)
        data = buffer.read() if buffer is not None else stream.read()
    except UnicodeDecodeError:
        return None, None, "Error reading stdin: UTF-8 として読めません"
    except (OSError, ValueError) as error:
        reason = getattr(error, "strerror", None) or error
        return None, None, "Error reading stdin: 標準入力を読めません（{}）".format(reason)
    try:
        text, info = decode_source(data)
    except UnicodeDecodeError:
        return None, None, "Error reading stdin: UTF-8 として読めません"
    return text, info, None


def _endings_report(text, stance):
    """--endings: 1つのファイルの文末だけを見る（マークダウンのコードブロックや表の区切りは飛ばす）。v1.1.2 と同じ出力。"""
    lines = []
    rows, flags = stance_flags(text, stance, markdown=True)
    c = Counter(r["kind"] for r in rows if r["where"] != "表")
    lines.append("■ 文末の種類（表を除く）: " + "、".join(f"{k} {v}" for k, v in c.most_common()))
    for n, fr in flags:
        lines.append(f"■ {n}")
        for r in fr:
            lines.append(f"  ・{r['sentence'] if len(r['sentence']) <= 60 else r['sentence'][:60] + '…'}")
    bp = bold_problems(text)
    if bp:
        lines.append(bold_head())
        lines.append("\n".join(bold_lines(bp)))
    return "\n".join(lines)


def _run(argv):
    parser = _build_parser()
    args = parser.parse_intermixed_args(argv)
    if args.version:
        print(_version_line())
        return 0
    files = args.files
    if args.endings:
        if args.json:
            parser.error("--endings は --json に対応していません")
        if args.fail_on:
            parser.error("--endings は --fail-on に対応していません")
        if len(files) != 1:
            parser.error("--endings のときは、ファイルを1つだけ渡してください（渡されたのは{}つ）".format(len(files)))
    elif len(files) != 2:
        parser.error("元の文と書き直した文の2つのファイルを渡してください（渡されたのは{}つ）".format(len(files)))
    if files.count("-") > 1:
        parser.error("標準入力（-）は1か所だけに使えます")
    fail_on, problem = _fail_on(args.fail_on)
    if problem:
        _error(problem)
        return 2
    stance = None
    if args.stance is not None:
        stance = STANCES.get(args.stance)
        if stance is None:
            # 空や空白だけの値は、目に見えないので「（空）」と書く（--fail-on と同じ）。
            shown = args.stance if args.stance.strip() else "（空）"
            _error("--stance に使えない値です: {}。使えるのは {} です。".format(shown, "、".join(STANCES)))
            return 2
    texts, infos = [], []
    for path in files:
        text, info, problem = _read_input(path)
        if problem:
            _error(problem)
            return 2
        texts.append(text)
        infos.append(info)

    if args.endings:
        print(_endings_report(texts[0], stance))
        code = 0
    else:
        result = diff(texts[0], texts[1], stance, encoding_notes=_encoding_notes(infos[0], infos[1]))
        counted = result["fail_on_meaning_risk_count"]
        hit = fail_on and counted > 0
        if args.json:
            print(json.dumps(result, ensure_ascii=True, indent=1))
        else:
            print(report(result))
            if hit:
                print()
                print(_fail_on_line(result["meaning_risk_count"], counted))
        code = 1 if hit else 0
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


def main(argv=None):
    """CLI。終了コードを返す（0: 条件に当たらない、1: --fail-on に当たった、2: 使い方か入力の誤り、3: 内部の誤り）。"""
    try:
        if _IMPORT_ERROR is not None:
            raise _IMPORT_ERROR
        _use_utf8(sys.stdout)
        return _run(argv)
    except BrokenPipeError:
        # 出力先（パイプの読む側）が先に閉じた。diff の不具合ではないので、トレースバックは出さない。
        # 結果を最後まで書けなかったので、終了コードは3にする。
        _silence_stdout()
        _error("yomiyasu_diff.py: 出力先が閉じられたため、結果を最後まで書けませんでした。")
        return 3
    except Exception as error:
        _error("yomiyasu_diff.py: 内部エラー: {}: {}".format(type(error).__name__, error))
        _error(traceback.format_exc().rstrip("\n"))
        return 3


if __name__ == "__main__":
    sys.exit(main())
