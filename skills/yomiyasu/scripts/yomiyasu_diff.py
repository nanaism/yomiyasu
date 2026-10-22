#!/usr/bin/env python3
"""
yomiyasu_diff.py - 元の文と書き直した文を比べ、変わった箇所をすべて出し、意味が変わる恐れと規則の見直し候補を挙げる。

標準ライブラリだけで動く。モデルは呼ばない。外へ通信しない。
出すものは8つ。
  1. 全文差分: 変わった箇所を省略せずに出す（太字、見出しの段、空白、空行、字下げ、コード、引用、表の変化も残す）。
     変わった箇所を示すだけで、意味が同じだという証明ではない。
  2. 意味が変わる恐れ: 数値、否定、主語と目的語の入れ替え、問いと平叙、文の種類の印、許可・能力の言い方（してよい、できる）、
     コード・URL・引用など変えない箇所の変化、否定対比の主張の逆転、元の文書にない気持ちの語。
     どれも確かめる場所で、意味が変わったという判定ではない。
  3. 規則の見直し候補（v1.1.2 からの9つの点検）:
     文末や言い回しの種類の数の増減、元の文にない語と消えた語、箇条書きや段落の変化、つながりを確かめる場所、
     文末の種類と文書の立場、文の種類の印、太字にならない書き方と直し方の案。
  4. 文体の硬化の検査: 漢字の割合、名詞化の言い回し、「の」の連続が推敲で増えた所（見直し候補だけで、件数と合否に入れない）。
  5. 勢いの検査: 「！」「？」、絵文字、強める語が減った所と、見出しが大きく縮んだ所（同じく見直し候補だけ）。
  6. 慎重表現の減り: 同じ文の推量印の候補と重ねず、hedges の節に出す（合否には入れない）。
  7. 動かしてはいけない値: 引用の印は meaning_risks（citation、合否の対象）、宛名と裸のメールは immutable（合否の対象外）。
     数字・単位とURLは既存検査を使い、空白つきの科学単位・数値の符号・統計値の比較記号の抜けだけ補う。引用の数値だけの変化が number で出たら重ねない。
  8. 敬語の度合い: mail だけ。敬語の数/文数と敬体文末の割合の差が0.20以上なら politeness の節に出す。
  paper の硬化と勢いは参考。mail の勢い（絵文字を含む）は見直し候補。
  名詞化の言い回し、強める語、気持ちの語、慎重表現の一覧は ../references/lists/ から読み、なければ内蔵の一覧を使う。
意味が同じかどうか、つながりが合っているか、文末が立場に合っているかの最終判断は、この結果を見たモデル（または人）がする。
"""
__version__ = "2.2.0"

import os
import errno
import re
import sys
import json
import argparse
import difflib
import traceback
import unicodedata
from array import array
from bisect import bisect_left, bisect_right
_VISIBILITY_NAMES = ("analyze_markdown", "inline_protected_spans", "unicode_whitespace", "decode_source",
                     "normalize_doc_type", "normalize_reader", "context_label", "DOC_TYPES",
                     "WordsError", "resolve_words", "current_directory", "words_context", "words_label")
try:
    try:
        if __package__:
            from .markdown_visibility import analyze_markdown, inline_protected_spans, unicode_whitespace, decode_source
            from .markdown_visibility import normalize_doc_type, normalize_reader, context_label, DOC_TYPES
            from .markdown_visibility import WordsError, resolve_words, current_directory, words_context, words_label
        else:
            from markdown_visibility import analyze_markdown, inline_protected_spans, unicode_whitespace, decode_source
            from markdown_visibility import normalize_doc_type, normalize_reader, context_label, DOC_TYPES
            from markdown_visibility import WordsError, resolve_words, current_directory, words_context, words_label
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
        normalize_doc_type = _visibility_module.normalize_doc_type
        normalize_reader = _visibility_module.normalize_reader
        context_label = _visibility_module.context_label
        DOC_TYPES = _visibility_module.DOC_TYPES
        WordsError = _visibility_module.WordsError
        resolve_words = _visibility_module.resolve_words
        current_directory = _visibility_module.current_directory
        words_context = _visibility_module.words_context
        words_label = _visibility_module.words_label
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

# MARKERS をコンパイルしたもの（_rule_candidates で使う。並びは MARKERS と同じ。diff の詰めの直し、速さ）
_MARKER_REGEXES = tuple((name, re.compile(pattern)) for name, pattern in MARKERS.items())

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


def _marks_in(positions, spans, kinds=TYPE_MARKERS, keys=None):
    """範囲（開始, 終了）の中から始まる印を {種類: [印, ...]} にまとめる。並びは kinds の順（既定は文の種類の印）。
    keys は positions の開始位置の並び（範囲ごとに作り直さないよう、呼ぶ側が1回だけ作って渡してよい）。"""
    if keys is None:
        keys = [item[0] for item in positions]
    marks = OrderedDict()
    for start, end in spans:
        for _, kind, hit in positions[bisect_left(keys, start):bisect_left(keys, end)]:
            hits = marks.setdefault(kind, [])
            if hit not in hits:
                hits.append(hit)
    return OrderedDict((kind, marks[kind]) for kind in kinds if kind in marks)


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


# 直近の _type_changes の入力と範囲（元, 後, 文字の対応, 範囲か None, 元の印の位置, 後の印の位置）。許可・能力の比べ
# （_modality_changes）が、同じ文章なら範囲を作り直さずに使う（範囲づくりは数十万字の文書で重いため）。
# _rule_candidates の引数と戻り値を変えずに渡すため、ここに1件だけ置く。文章が違えば使わずに作り直す。diff() は使い終えたら
# None に戻す（比べ終えた文章の全文と範囲を、処理が終わるまで持ち続けないため）。
_LAST_TYPE_RANGES = [None]


def _type_changes(o: str, r: str, opcodes):
    """元の各文が、文字単位の対応で書き直した文章のどの範囲に当たるかをたどり、範囲ごとに印を比べる。
    文を分けても、つないでも、範囲の中で比べるので、移っただけの印は変化として出ない。
    範囲が重なる元の文はまとめて比べる。丸ごと消えた文は比べない。丸ごと移した文は同じ文を探し、
    移したうえで書き換えた文は、字面の近い文を書き直した文章から探して比べる。範囲は _type_ranges が作る。"""
    if not opcodes:
        return []
    o_marks, r_marks = _mark_positions(o), _mark_positions(r)
    if not o_marks and not r_marks:
        _LAST_TYPE_RANGES[0] = (o, r, opcodes, None, o_marks, r_marks)
        return []
    ranges = _type_ranges(o, r, opcodes)
    _LAST_TYPE_RANGES[0] = (o, r, opcodes, ranges, o_marks, r_marks)
    o_keys, r_keys = [item[0] for item in o_marks], [item[0] for item in r_marks]
    out = []
    for texts, spans, a, b in ranges:
        before = _marks_in(o_marks, spans, keys=o_keys)
        after = _marks_in(r_marks, [(a, b)], keys=r_keys)
        lost = [{"kind": kind, "hits": hits} for kind, hits in before.items() if kind not in after]
        added = [{"kind": kind, "hits": hits} for kind, hits in after.items() if kind not in before]
        if lost or added:
            out.append({"orig": "".join(texts), "rewrite": _range_sentences(r, a, b), "lost": lost, "added": added})
    return out


def _range_sentences(r, a, b):
    """書き直した文章の範囲 [a, b) を、前後の文の切れ目（句点・改行）まで広げた文。"""
    left = max(r.rfind(ch, 0, a) for ch in "。！？!?\n") + 1
    right = b if b and r[b - 1] in "。！？!?" else min([i for i in (r.find(ch, b) for ch in "。！？!?\n") if i != -1] + [len(r)])
    right = right + 1 if right < len(r) and r[right] in "。！？!?" else right
    return r[left:right].strip()


def _type_ranges(o: str, r: str, opcodes):
    """元の各文が、文字単位の対応（opcodes）で書き直した文章のどの範囲に当たるか。
    [(元の文の並び, 元の文の範囲の並び, 書き直した文章の始め, 終わり)] を返す（範囲が重なる元の文は1つにまとめる。丸ごと
    消えた文は入れない）。文の種類の印（_type_changes）と許可・能力の言い方（_modality_changes）が同じ範囲で比べる。"""
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
    return [tuple(g) for g in groups] + moved


def _overlapping(items, spans):
    """各範囲 (a, b) について、items のうち x[2] < b かつ a < x[3] のもの（items の順のまま）の一覧。
    [[x for x in items if x[2] < b and a < x[3]] for a, b in spans] と同じ。items を始まりの順に並べ、前からの終わりの最大を持っておき、
    b より前に始まるものを後ろから、そこまでの終わりの最大が a 以下になる（それより前に a より後で終わるものがない）所まで見る。"""
    order = sorted(range(len(items)), key=lambda k: items[k][2])
    starts = [items[k][2] for k in order]
    reach, top = [], None
    for k in order:
        end = items[k][3]
        top = end if top is None or end > top else top
        reach.append(top)
    out = []
    for a, b in spans:
        q = bisect_left(starts, b) - 1
        found = []
        while q >= 0 and reach[q] > a:
            k = order[q]
            if items[k][3] > a:
                found.append(k)
            q -= 1
        found.sort()
        out.append([items[k] for k in found])
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

    # v2.0.0 までは、書き直した文ごとにすべての範囲を見て owners を作り、消えた文と書き直した文のすべての組で共通の組を数えていた
    # （どちらも数の2乗）。同じものを、範囲の始まりの順の並びと、2文字の組から書き直した文を引く表で求める（結果は同じ）。
    r_grams = [_bigrams(r[a:b].strip()) for a, b in r_spans]
    owners = _overlapping(groups, r_spans)
    moved_over = _overlapping(moved, r_spans)
    group_grams = {}

    def grams_of(g):
        grams = group_grams.get(id(g))
        if grams is None:
            grams = group_grams[id(g)] = _bigrams("".join(g[0]))
        return grams
    owner_grams = [set().union(*[grams_of(g) for g in gs + ms]) for gs, ms in zip(owners, moved_over)]
    spans_with = {}
    for idx, grams in enumerate(r_grams):
        for gram in grams:
            spans_with.setdefault(gram, []).append(idx)
    candidates = []
    for gi, (text, _, _) in enumerate(gone):
        grams = _bigrams(text)
        # shared_counts[idx] は len(grams & r_grams[idx])。共通の組が1つもない文は、下の least（3以上）に届かないので数えなくてよい。
        shared_counts = Counter()
        for gram in grams:
            found = spans_with.get(gram)
            if found:
                shared_counts.update(found)
        for idx in sorted(shared_counts):
            shared_count = shared_counts[idx]
            least = 3 if min(len(grams), len(r_grams[idx])) <= 6 else 4
            if shared_count < least or shared_count < 0.5 * min(len(grams), len(r_grams[idx])):
                continue
            shared = grams & r_grams[idx]
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
    消した文の文末の数文字に引きずられて、隣の文に足した印が範囲の外に出るのを防ぐ。

    ほかの範囲 (ca, cb) で止める所は、左が「a 以前に終わる範囲の終わり cb の最大」、右が「b 以後に始まる範囲の始まり ca の最小」。
    v2.0.0 までは範囲ごとにすべての範囲を見ていた（範囲の数の2乗。数十万字の文書で十数秒）。終わりと始まりを並べておき、二分探索で引く。
    a < b で、どの範囲も ca <= cb なら、ca >= b の範囲は cb > a なので、2つの条件は同時に成り立たない。(a, b) 自身（と同じ範囲）は
    どちらの条件にも当たらないので、飛ばさなくても同じになる。よって、すべての範囲を順に見たときと同じ端になる。
    それ以外の形（a >= b の範囲、ca > cb の範囲があるとき）は、前と同じく、すべての範囲を順に見る。"""
    if not groups:
        return
    r_starts, r_ends = [a for a, _ in r_spans], [b for _, b in r_spans]
    claimed = sorted([(g[2], g[3]) for g in groups] + [(m[2], m[3]) for m in moved])
    ordered = all(ca <= cb for ca, cb in claimed)
    claimed_starts = [ca for ca, _ in claimed]          # claimed は始まりの順に並んでいる
    claimed_ends = sorted(cb for _, cb in claimed)
    for g in groups:
        a, b = g[2], g[3]
        i = bisect_right(r_starts, a) - 1
        j = bisect_left(r_ends, b)
        left = r_starts[i] if 0 <= i < len(r_spans) and r_ends[i] > a else a
        right = r_ends[j] if j < len(r_spans) and r_starts[j] < b else b
        if ordered and a < b:
            k = bisect_right(claimed_ends, a)
            if k:
                left = max(left, claimed_ends[k - 1])
            k = bisect_left(claimed_starts, b)
            if k < len(claimed_starts):
                right = min(right, claimed_starts[k])
        else:
            for ca, cb in claimed:
                if (ca, cb) == (a, b):
                    continue
                if cb <= a:
                    left = max(left, cb)
                elif ca >= b:
                    right = min(right, ca)
        g[2], g[3] = min(a, left), max(b, right)


# ---- 許可・能力の言い方 ----
# 仕様書では「〜してよい」（許可）と「〜できる」（能力）、「〜する」（説明）と「必ず〜する」「〜を保証する」（保証）の違いが、
# そのまま仕様の違いになる。文の種類の印（TYPE_MARKERS）とは別の表に置き、文の種類の印と同じ範囲（_type_ranges）で、
# 種類があるかないかを比べる（同じ種類の中の言い換え「することができる → できる」「してもよい → してよい」は変化にしない）。
# 数えるのは許可が消えた・増えた範囲だけ。能力（強い印）が消えて能力の弱い印も許可も増えていない範囲は、どの文書の種類でも
# 数えない候補（modality_review）にとどめる（推敲の言い換えで、できることの意味が残る書き換えが多いため）。能力が増えただけの
# 範囲は正しい直し（名詞の句を動詞に開いた「〜できることを確認」など）が多いので出さない。「しなくてよい」「不要」「必要はない」は
# 許可と分けて「不要」の種類にし、その変化は候補にしない。義務・禁止・保証・不要の印は、変化の相手の名前（detail の to と from）を
# 書くためだけに使う（義務・禁止の変化は文の種類の印、保証の足しは約束の候補、「必ず」は確度が受け持つ）。
# 「て」のあとの許可から外す形: とても、にとって、と言っても、全て・すべて、極めて、初めて、改めて、あえて、かつて、せめて、決して、
# 総じて、概して、として、によって、について、「くて」（安くてよい、しなくてよい）、依頼の「いただいても（よろしい・いい）」。
# 「で」のあとは、「ん」「い」の後ろ（読んでよい、急いでよい）か、「でも」の形（何でもよい、PDF でも構わない）だけ。「どうでも」
# 「くらいで」「しないで」は外す。「これでよい」のような名詞のあとの「でよい」と、「とよい」「ばよい」（勧め）は当てない。
# 「よく」は読点が続くとき（してもよく、）だけ、「よい」「良い」はすぐあとに名詞が続かないときだけ（よい結果、良い経験は評価）、
# 「いい」は文末や、です・でしょう・と・が・の などが続くときだけ当てる。
# 能力の弱い印の語尾。過去の形（使えた、減らせました、得られなかった）も、消えた強い印を吸う側に入れる。
_MODALITY_ENDS = r"(?:る|ます|ない|ません|た|ました|なかった)"
# 「結構」は、です・だ・句点などが続くとき（結構です）だけ許可の言い方にする（「結構大変」の副詞は当てない）
_PERMISSION_END = r"(?=です|だ|でござ|[。、！!]|$)"
_PERMISSION_TAIL = (r"(?:も?(?:(?:よい|良い)(?![一-龥々〆ヵヶァ-ヴーA-Za-z0-9])|よろし|(?:よ|良)く(?=、)"
                    r"|いい(?=[。、]|です|でしょう|だろう|と|が|し|か|けど|よ|ね|の|$)"
                    r"|構(?:わな|いませ)|かま(?:わな|いませ)|差し?支え(?:な|あり|ござ))"
                    r"|も(?:問題(?:は)?(?:な|あり|ござ)|大丈夫|結構" + _PERMISSION_END + r"))")
_MODALITY_PATTERNS = (
    ("許可", r"(?:て(?<!とて)(?<!とって)(?<!言って)(?<!いって)(?<!全て)(?<!すべて)(?<!極めて)(?<!きわめて)(?<!初めて)(?<!改めて)"
           r"(?<!あえて)(?<!かつて)(?<!せめて)(?<!決して)(?<!総じて)(?<!概して)(?<!として)(?<!によって)(?<!について)(?<!くて)"
           r"(?!(?:(?<=いただいて)|(?<=頂いて)|(?<=もらって))も(?:よろし|いい))"
           r"|で(?<!ないで)(?<!らいで)(?:(?<=[んい]で)|(?<=[^。、！？!?\n「『（(\s]で)(?<!どうで)(?=も)))" + _PERMISSION_TAIL
           + r"|(?:れ|け)ば(?:結構" + _PERMISSION_END + r"|差し?支え(?:な|あり|ござ))|で結構" + _PERMISSION_END
           + r"|形で差し?支え(?:な|あり|ござ)"
           + r"|許可(?:する|される|します|されます)(?=[。！!]|$)"),
    # 能力の強い印。「できるだけ」「できる限り」と「可能な限り」は除く。打ち消しの形（できない、できず、できていない、不可能だ）も
    # 同じ種類にし、打ち消しの印だけが消えた範囲は能力の消えにしない（_ABILITY_NEGATIVE）。連用の「でき、」「できて」も入れる
    # （「準備ができている」のような出来上がりの意味と分けるため、「ことが」以外の「が」のすぐあとでは数えない）。
    # 過去の形（できた、できました、できなかった、できていた）は、弱い印として吸う側だけに入れる（確認できました → 確認しました
    # のような報告の直しを、能力の消えにしない）。
    ("能力", r"(?:でき|出来)(?:る(?!だけ|限り|かぎり)|ます|ない|ません|なく(?=て|な)|ず|て(?:い|おり|お)?(?:な|ませ|らず)"
           r"|(?:(?<!ができ)(?<!が出来)|(?<=ことができ)|(?<=ことが出来))(?:て(?!(?:い|おり)(?:た|ました))|(?=、)))"
           r"|不?可能(?:です|だ|である|な(?!限|かぎ)|に|(?=[。、]|$|と|で))"),
    # 能力の弱い印（消えた強い印を吸うだけに使う）。能力の過去の形（「準備ができた」のような出来上がりの意味と分けるため、
    # 「ことが」以外の「が」のすぐあとの「できた」「できました」は除く）、一段の可能（含められる、進められる。漢字1字の
    # 見・得・来・寝・着・居も）、使役の可能（休ませられる、させられる）、いただける、得る・うる・える（あり得る、なりうる、
    # ありえる）、五段の可能（使える、防げる、書ける、たどり着ける など）。五段の可能は「続ける」「伝える」のような動詞と
    # 取り違えないよう、語の頭を一覧で絞る。受身の「〜られる」も当たるが、強い印の消えを吸うだけなので害は小さい。
    ("能力（弱い印）", r"(?:でき|出来)(?:なかった|て(?:い|おり)(?:た|ました)|(?:(?<!ができ)(?<!が出来)|(?<=ことができ)|(?<=ことが出来))"
                  r"(?:た|ました))"
                  + r"|られ(?:(?<=[一-龥][めけえせてねべれげじみきちにひびりいぎ]られ)|(?<=[見得来寝着居]られ)|(?<=せられ))"
                  + _MODALITY_ENDS
                  + r"|(?:いただけ|頂け)" + _MODALITY_ENDS
                  + r"|得(?<=[しりきちびみいにぎじ]得)" + _MODALITY_ENDS + r"|うる(?<=[しりきちびみいにぎじ]うる)"
                  + r"|え(?:(?<=[使言払買会扱担補賄笑洗歌行]え)|(?<=[しりきちびみいにぎじ]え))" + _MODALITY_ENDS
                  + r"|け(?<=[書聞行置解動引築描歩磨裁省着]け)" + _MODALITY_ENDS
                  + r"|げ(?<=[防稼急泳脱研]げ)" + _MODALITY_ENDS
                  + r"|せ(?:(?<=[出話直消残戻外試探示移返回流隠渡通壊倒許貸押]せ)"
                    r"|(?<=減らせ|増やせ|動かせ|生かせ|活かせ|果たせ|満たせ|冷やせ|延ばせ|伸ばせ|飛ばせ|起こせ))" + _MODALITY_ENDS
                  + r"|て(?<=[待持保勝打放]て)" + _MODALITY_ENDS
                  + r"|べ(?<=[選運呼学飛遊結喜]べ)" + _MODALITY_ENDS
                  + r"|め(?:(?<=[読飲頼望掴組住]め)|(?<=楽しめ))" + _MODALITY_ENDS
                  + r"|れ(?<=[守作取送乗帰撮登通走語測計図]れ)" + _MODALITY_ENDS),
    # しなくてよい、しないでいい、不要、必要はない（する必要がないこと。許可とは別の種類にし、その変化は候補にしない）
    ("不要", r"(?:なくて|ないで)" + _PERMISSION_TAIL + r"|不必?要|必要(?:は|が|も)?(?:な(?:い|く|し)|ありません|ございません)"),
    ("義務", r"なければ(?:ならない|なりません|いけない|いけません)|なくては(?:ならない|なりません|いけない|いけません)"
           r"|ないといけ(?:ない|ません)|ねばなら(?:ない|ず)"
           r"|必要(?<!不必要)(?:があ(?:る|ります)|(?:に|と)(?:なる|なります)|(?:です|だ)(?=[。！!]|$))"
           r"|べき(?<!しかるべき)(?<!然るべき)(?<!驚くべき)(?<!恐るべき)(?<!来るべき)(?<!特筆すべき)(?<!注目すべき)(?!乗)"
           r"|ものと(?:する|します)|必須"),
    ("禁止", r"(?:て|で)は(?:いけ|なら)(?:ない|ません)|禁止"),
    ("保証", r"保証(?:する|します|される|されます|いたします|致します|(?:して|されて)(?:いる|います))(?=[。、]|$)"
           r"|担保(?:する|します|される|されます)(?=[。、]|$)|必ず(?!しも)|確実に"
           r"|ことは(?:ない|ありません|ございません)(?=[。]|$)"),
)
MODALITY_MARKERS = OrderedDict((kind, re.compile(pattern, re.M)) for kind, pattern in _MODALITY_PATTERNS)
# 種類ごとに、印の正規表現が当たるために必ず含まれる文字列（_TYPE_LITERALS と同じ使い方）。能力の弱い印は語の頭が多いので、
# 前もって絞らずに当てる。
_MODALITY_LITERALS = {
    "許可": ("てよ", "でよ", "て良", "で良", "もよ", "も良", "いい", "構", "かま", "支え", "結構", "問題", "大丈夫", "許可"),
    "能力": ("でき", "出来", "可能"),
    "能力（弱い印）": ("",),
    "不要": ("なくて", "ないで", "不要", "不必要", "必要"),
    "義務": ("なければ", "なくては", "ないといけ", "ねばなら", "必要", "べき", "ものと", "必須"),
    "禁止": ("はいけ", "はなら", "禁止"),
    "保証": ("保証", "担保", "必ず", "確実に", "ことは"),
}
# 能力の強い印のうち、打ち消しの形（できない、できません、できず、できていない、できておりません、不可能だ）。打ち消しの印だけが消えた範囲
# （判別できません → 分かりません、接続できない場合は → 接続に失敗したときは）は、能力の消えにしない。
_ABILITY_NEGATIVE = re.compile(r"(?:でき|出来)(?:な|ませ|ず|て(?:い|おり|お)?(?:な|ませ|らず))|不可能")
# 変化の相手の名前に使う種類と、その並び。能力の弱い印は「能力」と書く。
_MODALITY_NAMES = (("能力", ("能力", "能力（弱い印）")), ("不要", ("不要",)), ("義務", ("義務",)), ("禁止", ("禁止",)),
                   ("保証", ("保証",)))
# --fail-on=meaning-risk が確度の2つ（「場合がある」「ことがある」を消した言い切りと、断定に「必ず」などを足した書き換え）を
# 数える文書の種類（事実や仕様を述べる種類）。並びは DOC_TYPES の順。
# essay、promo、mail、minutes、slides と種類なしは、これまでどおり数えない候補にとどめる。
COUNTED_TYPES = ("pr", "article", "incident", "proposal", "manual", "formal", "paper")


def _modality_positions(text):
    """文章全体に許可・能力などの印の正規表現を1回ずつ当て、(開始位置, 種類, 印) を位置の順に返す。"""
    found = [(m.start(), kind, m.group(0)) for kind, pattern in MODALITY_MARKERS.items()
             if any(literal in text for literal in _MODALITY_LITERALS[kind]) for m in pattern.finditer(text)]
    found.sort(key=lambda item: item[0])
    return found


def _modality_names(kinds, fallback):
    """種類の並び（印の種類の名前）を、変化の相手の名前（能力・不要・義務・禁止・保証の順、「・」でつなぐ）にする。"""
    names = [name for name, members in _MODALITY_NAMES if any(member in kinds for member in members)]
    return "・".join(names) if names else fallback


def _shared_ranges(o: str, r: str):
    """文の種類の印と同じ範囲（_type_ranges）と、元と後の文の種類の印の位置。直前の _type_changes か、この関数が同じ文章で
    作った範囲があれば使い回し、なければ作って _LAST_TYPE_RANGES に置く（許可・能力の比べと、選ぶ範囲・因果の比べが
    同じ範囲を作り直さないため。diff() と meaning_risks() は使い終えたら空に戻す）。"""
    last = _LAST_TYPE_RANGES[0]
    if last is not None and last[0] == o and last[1] == r:
        opcodes, ranges, o_marks, r_marks = last[2:]
    else:
        opcodes = _ExactSequenceMatcher(None, o, r, autojunk=False).get_opcodes()
        ranges, o_marks, r_marks = None, _mark_positions(o), _mark_positions(r)
    if ranges is None:
        ranges = _type_ranges(o, r, opcodes)
        _LAST_TYPE_RANGES[0] = (o, r, opcodes, ranges, o_marks, r_marks)
    return ranges, o_marks, r_marks


def _modality_changes(o: str, r: str):
    """許可・能力の言い方が変わった範囲。正規化した元と後の文章を受け取り、
    [{"orig", "rewrite", "subkind", "from", "to", "lost", "added"}] を返す（subkind は permission_lost、permission_added、
    ability_lost）。範囲は文の種類の印と同じ（_type_ranges）。直前の _type_changes が同じ文章で作った範囲があれば使い回す
    （diff() は使い終えたら _LAST_TYPE_RANGES を空に戻す）。「不要」の種類の変化だけの範囲は出さない。
    同じ範囲で依頼・決まりの印が消えたか増えたときは、文の種類の印の候補に任せて出さない（「してよい → しなければならない」は
    文の種類の印の候補1件のまま）。"""
    if o == r:
        return []
    o_pos, r_pos = _modality_positions(o), _modality_positions(r)
    if not any(kind in ("許可", "能力") for _, kind, _ in o_pos) and not any(kind == "許可" for _, kind, _ in r_pos):
        return []
    ranges, o_marks, r_marks = _shared_ranges(o, r)
    keys = [item[0] for item in o_pos], [item[0] for item in r_pos]
    type_keys = [item[0] for item in o_marks], [item[0] for item in r_marks]
    out = []
    for texts, spans, a, b in ranges:
        before = _marks_in(o_pos, spans, MODALITY_MARKERS, keys[0])
        after = _marks_in(r_pos, [(a, b)], MODALITY_MARKERS, keys[1])
        lost = [kind for kind in before if kind not in after]
        added = [kind for kind in after if kind not in before]
        found = []
        if "許可" in lost:
            found.append(("permission_lost", "許可", _modality_names(added, "断定")))
        if "許可" in added:
            found.append(("permission_added", _modality_names(lost, "断定"), "許可"))
        # 打ち消しの能力（できない、できません）だけが消えた範囲は出さない（言い換えた「分からない」「失敗したとき」は、
        # できないことの意味を残していることが多い）
        if ("能力" in lost and "能力（弱い印）" not in added and "許可" not in added
                and any(not _ABILITY_NEGATIVE.match(hit) for hit in before["能力"])):
            found.append(("ability_lost", "能力", _modality_names(added, "断定")))
        if not found:
            continue
        rule_before = "依頼・決まり" in _marks_in(o_marks, spans, keys=type_keys[0])
        if rule_before != ("依頼・決まり" in _marks_in(r_marks, [(a, b)], keys=type_keys[1])):
            continue
        orig, rewrite = "".join(texts), _range_sentences(r, a, b)
        for subkind, source, target in found:
            out.append({"orig": orig, "rewrite": rewrite, "subkind": subkind, "from": source, "to": target,
                        "lost": [{"kind": kind, "hits": before[kind]} for kind in lost],
                        "added": [{"kind": kind, "hits": after[kind]} for kind in added]})
    return out


# ---- 選ぶ範囲と因果の言い方 ----
# 「AまたはBのどちらか」（どれか一つを選ぶ）と「AとBの両方」（全部を含む）は、入れ替わると文の真偽が逆になる。「関連がある」
# 「相関がある」を「因果関係がある」「原因である」に変えると、関わりを述べた文が原因と結果を述べる文に強まる。どちらも
# 許可・能力の言い方と同じく、文の種類の印とは別の表に置き、文の種類の印と同じ範囲（_type_ranges）で比べる
# （語の抽出の CONTENT は平仮名だけの「または」「どちらか」を拾わないので、決まった語の対で見る）。
# 選ぶ範囲（kind choice）は、元の範囲にどれか一つの言い方があり、後の範囲で全部の言い方が元より多く、どれか一つの言い方が
# 残っていないとき（one_to_all）と、元の範囲に全部の言い方があってどれか一つの言い方がなく、後の範囲にどれか一つの言い方が
# あって全部の言い方が残っていないとき（all_to_one）に出す。同じ側の中の言い換え（または → か、どちらか → いずれか、
# 両方 → どちらも）は出さない。one_to_all は範囲の中の数で比べるので、変わらずに残る「すべてを保存し」のような全部の言い方は
# 打ち消し合う。「どちらでも」「どちらからでも」「AでもBでも」（どれを選んでもよい）は、どれか一つの側に残った言い方として扱う。
# 因果（kind causality）は、元の範囲に関連・相関の言い方があって因果の言い方がなく、後の範囲に因果の言い方があるとき
# （relation_to_cause）に出す。元の範囲の因果は広く見る（〜による、影響する、〜で起きた、〜のため、理由 など。_LOGIC_PATTERNS の
# 「因果（広い）」）。どちらも --fail-on に数える。
# 因果は、範囲のすぐあとに足した文（原文のどの文にも対応しない文。同じ行の2文まで）も後の範囲に含める（文を分けて、原因を
# 2文目に書いた書き換え）。選ぶ範囲は含めない（足した文の「どちらも無料です」のような全部の言い方と分けられないため）。
# 「AかB」の「か」は、漢字・片仮名・英字の語の間にあり、あとの語に助詞が続くものだけを当てる。問いの「か」（必要か確認する、
# 原因か調べる、設定が有効か管理者に確認する、各端末が最新版か担当者に聞く）、何か・誰か・何度か・数回か、「か否か」、数のあとの
# 「か月」「か所」は当てない。「どちらかといえば」「いずれから」「どれから」、「双方向」「両方向」、「Aとともに」も当てない。
# 「ともに」は「は」「が」「も」のすぐあと（AとBはともに）だけにする。全部の言い方には「AもBも」「AにもBにも」「どちらの鍵も」
# 「二つとも」の形も入れる。「すべて」「全て」「全部」は、選ぶものを指す形（AとBのすべて、すべてを、すべてに）だけを当て、
# 別の名詞に掛かる「すべての項目」は、原文の「いずれかの項目」のように同じ名詞を選ぶ言い方があるときだけ全部の言い方にする
# （「全項目」は「すべての項目」と同じ側）。「かつ」「および」は入れない。
# 関連の言い方は、関わりがあると述べる形（関連がある、関連している、相関がある、関係がある、結びついている、関わりがある、
# AとBは関連する）だけにし、打ち消し（関係はありません、相関は見られなかった）、問い（関係があるか調べる）、
# 名詞を修飾する形（関係のある部署、関連性の高い記事、関連する設定、関連記事、相関係数）と、「成果に結びつく」
# 「成果に結びついている」（因果に近い）は当てない。「因果関係がある」は関連の言い方にも当たるが、因果の言い方もあるので、
# 元の範囲にあれば出さない。
_CHOICE_NOUN = r"[一-龥々ァ-ヴーA-Za-zＡ-Ｚａ-ｚ0-9０-９]"
# 「AもBも」の項（「の」でつないだ名詞句。「住民票の写し」のように、漢字のあとの送りがな1字も含める）
_CHOICE_ITEM = (_CHOICE_NOUN + r"{1,15}(?:[しりきみちえけせてめれ](?<=[一-龥][しりきみちえけせてめれ])(?=[もの]))?")
_CHOICE_PHRASE = _CHOICE_ITEM + r"(?:の" + _CHOICE_ITEM + r"){0,2}"
# 「AもBも」の最初の「も」の前（名詞の字か、漢字のあとの送りがな）
_CHOICE_BEFORE = r"(?:(?<=" + _CHOICE_NOUN + r")|(?<=[一-龥][しりきみちえけせてめれ]))"
# 関連の言い方の述語。打ち消し（ありません、見られなかった、認められない）、問い（関係があるか調べる）、名詞を修飾する形
# （関係がある部署）は当てない。「かもしれない」は当てる。
_RELATION_END = r"(?![一-龥々ァ-ヴー]|か(?!も)|とは(?:言|い)え|とは限ら|わけでは)"
_RELATION_PRED = (r"(?:が|は|も)?(?:ある" + _RELATION_END + r"|あり(?!ませ|えな)|あった" + _RELATION_END
                  + r"|(?:見られ|みられ|認められ|指摘され|示され|確認され)(?!な|ず|ませ)"
                  + r"|(?:強い|深い|高い)" + _RELATION_END + r")")
_RELATION_STATE = r"(?:(?:いる|いた)" + _RELATION_END + r"|います|おり|いました)"
# 「〜につながる」の前（漢字か片仮名の語。サーバーやネットワーク、回線などにつながる、ひとつにつながる、のような
# 接続の意味は除く）
_CAUSE_LEAD = (r"(?<=[一-龥々ァ-ヴー])"
               + "".join(r"(?<!{})".format(word) for word in ("サーバー", "ネット", "ネットワーク", "回線", "電源", "環境", "端末",
                                                             "ホスト", "ポート", "ノード", "機器", "拠点", "外部", "社内",
                                                             "電話", "窓口", "担当")))
_LOGIC_PATTERNS = (
    ("どれか一つ", r"または|もしくは|あるいは|どちらか(?!ら|と(?:いえば|言えば|いうと|言うと))|いずれか(?!ら)|どれか(?!ら)"
                 r"|片方(?:だけ|のみ)|択一"
                 r"|か(?<=[一-龥々ァ-ヴーA-Za-zＡ-Ｚａ-ｚ]か)(?<![何誰数幾]か)(?<![何数幾][一-龥]か)(?<![0-9０-９一二三四五六七八九十百千]か)"
                 r"(?!所|箇所|ヵ所|月|国|条|年|日|否|確|判|検|調|評|決|点|把|見極|吟味|試|迷|問|尋|分か|明|心配|不安|気)"
                 r"(?=" + _CHOICE_NOUN + r"{1,15}(?:[をがでにのはもと、。]|か|$))"),
    # どれを選んでもよい言い方（どちらでも、いずれからでも、AでもBでも）。どれか一つの側に残った言い方として、one_to_all を止める
    ("どれでも", r"(?:どちら|いずれ|どれ)(?:から|で|に|を)?でも"
               r"|" + _CHOICE_BEFORE + r"(?:で|から)も、?" + _CHOICE_PHRASE + r"(?:で|から)も"),
    # 名詞を修飾する「いずれかの条件」（同じ名詞の「すべての条件」と組にするため）
    ("どれか一つ（連体）", r"(?:いずれ|どれ|どちら)か(?:一つ|ひとつ|1つ|１つ|一方)?の" + _CHOICE_NOUN + r"{1,10}"),
    ("全部", r"両方(?!向)|双方(?!向)|どちらも|いずれも|どれも|両者とも|[二三2-3２-３]つとも"
           r"|どちらとも(?!言|い|取|と|つ|決|判|限|不|評)|(?:どちら|いずれ|どれ)(?:に|へ)も"
           r"|(?<=の)(?:すべて|全て|全部)(?!の)|(?:すべて|全て|全部)(?=[をがも]|に(?!おい|わた|渡))"
           r"|ともに(?<=[はがも]ともに)|共に(?<=[はがも]共に)|(?:どちら|いずれ|どれ)の" + _CHOICE_NOUN + r"{1,10}も(?![のう])"
           r"|" + _CHOICE_BEFORE + r"(?:に|と|へ)?も、?" + _CHOICE_PHRASE + r"(?:に|と|へ)?も(?![のう])"),
    # 名詞を修飾する「すべての条件」「全項目」（原文に同じ名詞の「いずれかの条件」があるときだけ全部の言い方にする）
    ("全部（連体）", r"(?:すべて|全て|全部)の" + _CHOICE_NOUN + r"{1,10}|(?<![一-龥々])全(?!部)[一-龥々ァ-ヴー]{1,8}"),
    ("関連", r"相関(?=(?:関係|性)?" + _RELATION_PRED + r"|して" + _RELATION_STATE + r")"
           + r"|関連(?:性)?" + _RELATION_PRED + r"|関連して" + _RELATION_STATE
           + r"|関係(?:性)?" + _RELATION_PRED + r"|関係して" + _RELATION_STATE
           + r"|(?<=[とは])(?<!には)関(?:連|係)(?:する|します)(?=[。！!]|$|と(?:され|考えられ|いわれ|言われ|みられ|見られ))"
           r"|結び(?<!に結び)(?:つ|付)いて" + _RELATION_STATE
           + r"|(?:関わり|かかわり)(?:が|は|も)?(?:ある" + _RELATION_END + r"|あり(?!ませ)|あった" + _RELATION_END
           + r"|(?:深い|強い)" + _RELATION_END + r")"),
    ("因果", r"因果|原因|起因|要因|引き起こ[すしさせそ]|ひき起こ[すしさせそ]|もたら[すしさ]|誘発"
           r"|(?:によって|により|ことで)[^。、]{0,12}?(?:生じ|起こ|起き|発生|増え(?:る|た|て)|増加(?:し|す)|減(?:る|った|って|り)"
           r"|減少(?:し|す)|伸び(?:る|た|て)|向上(?:し|す)|改善(?:し|す)|低下(?:し|す)|上昇(?:し|す)|悪化(?:し|す))"
           r"|せい(?<=のせい|たせい|るせい|いせい)(?:で|だ|です|である)|おかげ(?:で|だ|です|である)"
           r"|影響を(?:与え|及ぼ)|" + _CAUSE_LEAD + r"につなが(?:る|り|った|ります|りました)|(?<![者師客様人員長氏家生方])を招(?:く|き|いた)"
           r"|(?<![査析験討認議論測定計証審票断索選較トそこあ])の結果、"),
    # 元の範囲の因果を広く見る言い方（元の範囲にあれば relation_to_cause を出さない。後の範囲では使わない）
    ("因果（広い）", r"によ(?:る|り|って)|影響|で(?:起き|起こ|生じ|発生)|から(?:生じ|起き|起こ|来)|ため|理由|せい|おかげ|結果"
                  r"|につなが|招|由来|きっかけ|引き金|(?<!も)ので(?![はす])|だから|ゆえ|故に"
                  r"|で[^。、]{0,8}?(?:増え|減っ|減り|増加|減少|伸び|落ち|下が|上が)"),
)
LOGIC_MARKERS = OrderedDict((kind, re.compile(pattern, re.M)) for kind, pattern in _LOGIC_PATTERNS)
# 種類ごとに、印の正規表現が当たるために必ず含まれる文字列（_TYPE_LITERALS と同じ使い方）
_LOGIC_LITERALS = {
    "どれか一つ": ("または", "もしくは", "あるいは", "どちらか", "いずれか", "どれか", "片方", "択一", "か"),
    "どれでも": ("でも", "も"),
    "どれか一つ（連体）": ("かの", "一つの", "ひとつの", "1つの", "１つの", "一方の"),
    "全部": ("両方", "双方", "どちらも", "いずれも", "どれも", "両者とも", "つとも", "どちらとも", "すべて", "全て", "全部", "ともに",
           "共に", "も"),
    "全部（連体）": ("すべての", "全ての", "全部の", "全"),
    "関連": ("相関", "関連", "関係", "結び", "関わり", "かかわり"),
    "因果": ("因果", "原因", "起因", "要因", "起こ", "もたら", "誘発", "生じ", "起き", "発生", "増", "減", "伸び", "向上", "改善", "低下",
           "上昇", "悪化", "せい", "おかげ", "影響を", "つなが", "招", "結果"),
    "因果（広い）": ("によ", "影響", "で", "から", "ため", "理由", "せい", "おかげ", "結果", "つなが", "招", "由来", "きっかけ", "引き金",
                "ので", "だから", "ゆえ", "故に"),
}
# 変化の向き → (subkind, kind, 元の種類, 後の種類)
_LOGIC_CHANGES = (("one_to_all", "choice", "どれか一つ", "全部"), ("all_to_one", "choice", "全部", "どれか一つ"),
                  ("relation_to_cause", "causality", "関連", "因果"))
# 問いの「か」: 「設定が有効か管理者に確認する」「各端末が最新版か担当者に聞く」。「か」の左が「が＋語」か状態を表す語で、
# 右の語のあとに確かめる・聞く言い方が続くもの。「木曜か金曜に確認する」「上長か人事部に確認する」は選ぶ「か」として残す。
_QUESTION_KA_LEFT = re.compile(r"(?:が" + _CHOICE_NOUN + r"{1,15}|有効|無効|正常|異常|最新版?|必要|不要|可能|不可|適切|妥当|正確"
                               r"|完了|対象|該当|安全|十分|問題|適用|OK|NG)$")
_QUESTION_KA_RIGHT = re.compile(_CHOICE_PHRASE + r"(?:に|へ|で|が|から|まで)?(?:確認|問い合わせ|問合せ|聞|尋|相談|確か|照会|伺|質問"
                                r"|判断|判定|調べ|調査|検証|点検|チェック|見極|報告|連絡|回答)")
# 「AもBも」の印を、人が読む行で「AもBも」と出すため、最初の項を左に広げる字（名詞の字と、名詞をつなぐ「の」、送りがな）
_CHOICE_NOUN_CHAR = re.compile(_CHOICE_NOUN)
_CHOICE_HEAD = re.compile(r"(?:に|と|へ|で|から)?も")


def _choice_item_start(text, start):
    """「AもBも」の印の開始位置 start（最初の「も」か、その前の助詞）から、最初の項 A の頭まで戻った位置。"""
    i, floor = start, max(0, start - 30)
    while i > floor:
        ch = text[i - 1]
        if _CHOICE_NOUN_CHAR.match(ch):
            i -= 1
        elif ch == "の" and i < start and i - 2 >= 0 and _CHOICE_NOUN_CHAR.match(text[i - 2]):
            i -= 1
        elif ch in "しりきみちえけせてめれ" and i == start and i - 2 >= 0 and "一" <= text[i - 2] <= "龥":
            i -= 1
        else:
            break
    return i


def _logic_positions(text):
    """文章全体に選ぶ範囲と因果の印の正規表現を1回ずつ当て、(開始位置, 種類, 印) を位置の順に返す。
    問いの「か」は除き、「AもBも」「AでもBでも」の印は最初の項から書く（開始位置は変えない）。"""
    found = []
    for kind, pattern in LOGIC_MARKERS.items():
        if not any(literal in text for literal in _LOGIC_LITERALS[kind]):
            continue
        for m in pattern.finditer(text):
            start, hit = m.start(), m.group(0)
            if kind == "どれか一つ" and hit == "か":
                if (_QUESTION_KA_LEFT.search(text, max(0, start - 16), start)
                        and _QUESTION_KA_RIGHT.match(text, start + 1)):
                    continue
            elif kind in ("全部", "どれでも") and _CHOICE_HEAD.match(hit) and start and not hit.startswith("とも"):
                head = _choice_item_start(text, start)
                if head < start:
                    hit = text[head:start] + hit
            found.append((start, kind, hit))
    found.sort(key=lambda item: item[0])
    return found


def _logic_hits(positions, spans, keys):
    """範囲（開始, 終了）の中から始まる印を {種類: [印, ...]} にまとめる（同じ印も数の分だけ並べる）。"""
    marks = {}
    for start, end in spans:
        for _, kind, hit in positions[bisect_left(keys, start):bisect_left(keys, end)]:
            marks.setdefault(kind, []).append(hit)
    return marks


def _logic_tails(r, ranges):
    """各範囲のすぐあとに足した文（書き直した文章のどの範囲にも重ならない文。同じ行の2文まで）の (開始, 終了) の並び。"""
    spans = _sentence_spans(r)
    starts = [s for s, _ in spans]
    owned = [False] * len(spans)
    for _, _, a, b in ranges:
        k = max(0, bisect_right(starts, a) - 1)
        while k < len(spans) and spans[k][0] < b:
            if spans[k][1] > a:
                owned[k] = True
            k += 1
    tails = []
    for _, _, a, b in ranges:
        extra, k, end = [], bisect_left(starts, b), b
        while k < len(spans) and len(extra) < 2 and not owned[k] and "\n" not in r[end:spans[k][0]]:
            extra.append(spans[k])
            end = spans[k][1]
            k += 1
        tails.append(extra)
    return tails


def _adnominal_noun(hit):
    """「いずれかの条件」「すべての条件」「全項目」の名詞（条件、項目）。"""
    return hit[hit.index("の") + 1:] if "の" in hit else hit[1:]


def _unique(hits):
    out = []
    for hit in hits:
        if hit not in out:
            out.append(hit)
    return out


def _logic_changes(o: str, r: str):
    """選ぶ範囲（どれか一つ ↔ 全部）と、関連から因果への言い方が変わった範囲。正規化した元と後の文章を受け取り、
    [{"orig", "rewrite", "kind", "subkind", "from", "to", "old_hits", "new_hits"}] を返す（kind は choice か causality、
    subkind は one_to_all、all_to_one、relation_to_cause。old_hits は元の範囲の from の印、new_hits は後の範囲で増えた to の印）。
    範囲は文の種類の印と同じ（_type_ranges）で、作った範囲があれば使い回す。因果の後の範囲には、そのすぐあとに足した文も含める。"""
    if o == r:
        return []
    o_pos, r_pos = _logic_positions(o), _logic_positions(r)
    o_kinds, r_kinds = {kind for _, kind, _ in o_pos}, {kind for _, kind, _ in r_pos}
    if "全部（連体）" in o_kinds:
        o_kinds.add("全部")
    if "全部（連体）" in r_kinds:
        r_kinds.add("全部")
    if not any(source in o_kinds and target in r_kinds for _, _, source, target in _LOGIC_CHANGES):
        return []
    ranges = _shared_ranges(o, r)[0]
    keys = [item[0] for item in o_pos], [item[0] for item in r_pos]
    # 因果の比べに使う、範囲のすぐあとに足した文（関連と因果の印がそろう文章でだけ作る）
    tails = _logic_tails(r, ranges) if "関連" in o_kinds and "因果" in r_kinds else [[] for _ in ranges]
    out = []
    for (texts, spans, a, b), extra in zip(ranges, tails):
        before = _logic_hits(o_pos, spans, keys[0])
        after = _logic_hits(r_pos, [(a, b)], keys[1])
        # 名詞を修飾する「すべての条件」は、もう一方の側に同じ名詞の「いずれかの条件」があり、同じ側に同じ名詞の全部の言い方
        # （すべての条件、全条件）がないときだけ、全部の言い方として数える（印は「すべて」「全条件」と書く）
        nouns = {side: {_adnominal_noun(hit) for hit in hits.get("どれか一つ（連体）", ())}
                 for side, hits in (("o", before), ("r", after))}
        alls = {side: {_adnominal_noun(hit) for hit in hits.get("全部（連体）", ())} for side, hits in (("o", before), ("r", after))}
        promoted = {side: [hit.split("の")[0] if "の" in hit else hit for hit in hits.get("全部（連体）", ())
                           if _adnominal_noun(hit) in nouns[other] and _adnominal_noun(hit) not in alls[other]]
                    for side, other, hits in (("o", "r", before), ("r", "o", after))}
        alls = {"o": before.get("全部", []) + promoted["o"], "r": after.get("全部", []) + promoted["r"]}
        for subkind, kind, source, target in _LOGIC_CHANGES:
            end = b
            if subkind == "one_to_all":
                # どれか一つの言い方が後の範囲から消え（どれでもよい言い方も残らず）、全部の言い方が元より増えたとき。
                # 変わらずに残る「すべてを保存し」のような全部の言い方は、数で打ち消し合う
                old = before.get(source, [])
                if (not old or len(alls["r"]) <= len(alls["o"]) or source in after or "どれでも" in after):
                    continue
                new_hits = [hit for hit in _unique(alls["r"]) if hit not in alls["o"]] or _unique(alls["r"])
            elif subkind == "all_to_one":
                # 全部の言い方が後の範囲から消え、元の範囲になかったどれか一つの言い方が現れたとき（元の範囲にどれか一つの言い方が
                # あれば、「CかD → CかDのいずれか」のような言い換えと分けられないので出さない）
                old = alls["o"]
                if not old or target not in after or target in before or alls["r"]:
                    continue
                new_hits = _unique(after[target])
            else:
                # 因果は、範囲のすぐあとに足した文も後の範囲に含める
                tail = _logic_hits(r_pos, extra, keys[1]) if extra else {}
                found = after.get(target, []) + tail.get(target, [])
                old = before.get(source, [])
                if not old or not found or target in before or "因果（広い）" in before:
                    continue
                new_hits = _unique(found)
                end = b if target in after else extra[-1][1]
            out.append({"orig": "".join(texts), "rewrite": _range_sentences(r, a, end), "kind": kind, "subkind": subkind,
                        "from": source, "to": target, "old_hits": _unique(old), "new_hits": new_hits})
    return out


CONTENT = re.compile(r"[一-龥々〆ヵヶ]{2,}|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9_.+#/-]+")


# v1.1.2 から引き継いだ点検（9つのキー）で使う正規表現。v1.1.2 は関数の中で re.sub(文字列, …) と書いていたが、呼ぶたびに
# re のキャッシュを引く手間がかかるので、モジュールで1回だけコンパイルする（中身は同じ。diff の詰めの直しで、速さのため）
_NORMALIZE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_NORMALIZE_LIST = re.compile(r"(?m)^\s*(?:[*\-・]|\d+[.)])\s+")
_NORMALIZE_HEADING = re.compile(r"(?m)^#+\s*")
_NORMALIZE_SPACES = re.compile(r"[ \t]+")
_HAS_LIST = re.compile(r"(?m)^\s*(?:[*\-・]|\d+[.)])\s+\S")
_SENTENCES_SPLIT = re.compile(r"(?<=[。！？!?])|\n+")
_LIST_ITEM_HEAD = re.compile(r"\s*(?:[*\-・]|\d+[.)])\s+")


def normalize(t: str) -> str:
    t = _NORMALIZE_BOLD.sub(r"\1", t)          # 太字
    t = _NORMALIZE_LIST.sub("", t)              # 箇条書きの印
    t = _NORMALIZE_HEADING.sub("", t)           # 見出し
    t = _NORMALIZE_SPACES.sub(" ", t)
    return t.strip()


def has_list(t: str) -> bool:
    return bool(_HAS_LIST.search(t))


def sentences(t: str):
    return [s for s in _SENTENCES_SPLIT.split(t) if s.strip()]


def paragraphs(t: str):
    """段落の数を数える。続いた箇条書きは1つの段落とみなす"""
    blocks, prev_list = [], False
    for line in t.split("\n"):
        if not line.strip():
            prev_list = False
            continue
        is_list = bool(_LIST_ITEM_HEAD.match(line))
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


# 文末の種類と敬体・常体の正規表現（v1.1.2 の ending_kind と register の中の文字列と同じ。モジュールで1回だけコンパイルする）
_BARE_MARKS = re.compile(r"\*\*|`")
_KEITAI_END = re.compile(r"(?:です|ます|ません|ました|でした|ましょう|ください|でしょう)$")
_JOTAI_END = re.compile(r"(?:だ|である|ではない|でない)$")
_PLAIN_VERB_END = re.compile(r"[るうくすつぬぶむぐたい]$")
_NOUNISH_END = re.compile(r"[ァ-ヴー一-龥A-Za-z0-9]$")
_REQUEST_END = re.compile(r"ください(?:ね)?$|(?:て|で)はいけません$|(?:て|で)はなりません$|ていただきます$|ていただけます$")
_SUGGEST_END = re.compile(r"ましょう$|とよいです$|といいです$|をおすすめします$|をお勧めします$")
_GUESS_END = re.compile(r"(?:でしょう|だろう|かもしれません|かもしれない|と思います|と考えます|と感じます|はずです|ようです|気がします)$")
_DUTY_END = re.compile(r"(?:なければなりません|なくてはなりません|必要があります|べきです)$")
_EVAL_END = re.compile(EVAL_END)
_PAST_END = re.compile(r"(?:ました|でした|ませんでした)$")
_MASU_END = re.compile(r"(?:ます|ません)$")
_TEIRU_STEM = re.compile(r"(?:て|で)い$")
_PASSIVE_STEM = re.compile(r"(?:られ|[^しさ]れ)$")
_DESU_END = re.compile(r"です$")


def bare_end(s: str) -> str:
    """文末の判定に使う形。太字や記号、文末のかっこ書き（「〜」の例など）を外す"""
    t = _BARE_MARKS.sub("", s).strip().rstrip("。．.！!？?").strip()
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
    if _KEITAI_END.search(t):
        return "敬体"
    if _JOTAI_END.search(t) or (_PLAIN_VERB_END.search(t) and not _NOUNISH_END.search(t)):
        return "常体"
    return ""


def ending_kind(s: str) -> str:
    t = bare_end(s)
    if not t:
        return ""
    if _REQUEST_END.search(t):
        return "依頼"
    if _SUGGEST_END.search(t):
        return "勧め"
    if _GUESS_END.search(t):
        return "推量・考え"
    if _DUTY_END.search(t):
        return "義務"
    if _EVAL_END.search(t):
        return "評価"
    if _PAST_END.search(t):
        return "過去"
    if _MASU_END.search(t):
        stem = _MASU_END.sub("", t)
        if _TEIRU_STEM.search(stem):
            return "説明（〜ています）"
        if _PASSIVE_STEM.search(stem) or stem.endswith(STATIVE) or stem.endswith(POTENTIAL):
            return "説明（〜ます）"
        return "動作（〜します）"
    if _DESU_END.search(t):
        return "断定（〜です）"
    if _JOTAI_END.search(t):
        return "常体"
    if _PLAIN_VERB_END.search(t) and not _NOUNISH_END.search(t):
        return "常体"
    return "体言止めなど"


# ending_units の正規表現（v1.1.2 と同じ文字列。ダッシュは U+2014 と U+2015）
_UNIT_LIST_HEAD = re.compile(r"^(?:[*\-・]|\d+[.)])\s+")
_UNIT_SPLIT = re.compile(r"(?<=[。！？!?])")
_UNIT_FULL_END = re.compile(r"[。！？!?]$")
_UNIT_DASH = re.compile("[\u2014\u2015]{1,2}")


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
        elif _UNIT_LIST_HEAD.match(l):
            where, parts_src = "箇条書き", [_UNIT_LIST_HEAD.sub("", l)]
        else:
            where, parts_src = "地の文", [l]
        for src in parts_src:
            for s in _UNIT_SPLIT.split(src):
                s = s.strip()
                if not s:
                    continue
                full = bool(_UNIT_FULL_END.search(s))
                parts = [p.strip() for p in _UNIT_DASH.split(s)]
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


# ---- difflib と同じ答えを、少ない計算で求める照合（v2.0.1 の速さの直し）----
# difflib.SequenceMatcher(None, a, b, autojunk=False) を文書全体に1文字ずつかけると、同じ字が何度も出る文書では
# find_longest_match の繰り返しが文書の大きさの3乗近くで重くなる（3万字の全面書き換えで2分あまり。数十万字の文書では、直しが数十か所でも
# 10分近くかかった）。
# _ExactSequenceMatcher は、文字列どうしで、捨てる要素（isjunk と autojunk の popular）がないときだけ、difflib と同じ答えを別の求め方で出す。
# それ以外（文字列でない並び、捨てる要素があるとき）は difflib にそのまま任せる。
# 下の定数は、どの求め方を選ぶかだけを決める。どの求め方も同じ値を求めるので、定数を変えても時間が変わるだけで、答えは変わらない。
_MATCH_SMALL_AREA = 2048          # 範囲の両側の字数の積がこれ以下なら、difflib と同じ DP で解く（小さい範囲では、ほかの手より速い）
_MATCH_PROBE_MAX = 64             # 上限の長さちょうどの一致を、その長さの部分文字列の表で探す、長さの上限
_MATCH_SEED_SHORT = 12            # 長い一致を種（短い部分文字列）で探すときの、種の長さ（_MATCH_SAMPLE_MIN 以下にする）
_MATCH_SEED_LONG = 40             # 探す長さが種の2倍以上の段で使う、長い種（定型の文が多い文書で、種の候補が増えすぎないようにする）
_MATCH_SAMPLE_MIN = 24            # 種で探す段の、一致の長さの下限（これより短い一致は DP か接尾辞オートマトンで求める）
_MATCH_SAMPLE_BUDGET_DIV = 4      # 種で探す1つの段で調べてよい候補の数（範囲の両側の字数の和をこれで割った数）。超えたら次の手に回す
_MATCH_SAM_FACTOR = 24            # 接尾辞オートマトンの1字の手間が、DP の内側の1回の何倍か（DP とどちらで解くかの見積もりにだけ使う）
_MATCH_WHOLE_INDEX_MIN = 4096     # b の範囲がこれより長いときは、b 全体の部分文字列の表を作って、ほかの範囲でも使い回す
_MATCH_PROBE_CACHE = 2            # 長さちょうどの一致を探す b 全体の表を、いくつの長さの分まで残すか（最近使った順に残す）
_MATCH_LOCAL_DIV = 8              # b 全体の表がまだない長さで、範囲の両側の字数の和が len(b) をこれで割った数以下なら、表を作らずその範囲だけで探す
_MATCH_AUTOMATON_MAX = 1 << 16    # 接尾辞オートマトンを作る b の範囲の長さの上限（1字あたり約450バイト使う。これより長い範囲は二分探索で解く）
_MATCH_ROLLING_MIN = 256          # 長さの二分探索で、部分文字列を切り出して hash を取る代わりに、1字ずつずらして求める hash を使う長さの下限
_ROLLING_MOD = (1 << 61) - 1      # 1字ずつずらして求める hash（多項式の hash）の法（素数）
_ROLLING_BASE = 1000000007        # 同じ hash の底（字の番号の最大 0x10FFFF より大きくする）


def _common_prefix_len(a, i, b, j, limit):
    """a[i:i+n] == b[j:j+n] となる最大の n（limit 以下）。1字ずつ比べず、切り出した文字列どうしを比べる（C の速さで比べられる）。
    8字から倍々に伸ばして違いの出る幅を見つけ、その幅を二分探索で詰める。"""
    if limit <= 0:
        return 0
    if a[i:i + limit] == b[j:j + limit]:
        return limit
    low, high = 0, limit          # a[i:i+low] は同じ、a[i:i+high] は違う
    step = 8
    while step < high and a[i:i + step] == b[j:j + step]:
        low = step
        step *= 2
    if step < high:
        high = step
    while high - low > 1:
        middle = (low + high) // 2
        if a[i + low:i + middle] == b[j + low:j + middle]:
            low = middle
        else:
            high = middle
    return low


def _common_suffix_len(a, i, b, j, limit):
    """a[i-n:i] == b[j-n:j] となる最大の n（limit 以下）。_common_prefix_len の後ろ向き。"""
    if limit <= 0:
        return 0
    if a[i - limit:i] == b[j - limit:j]:
        return limit
    low, high = 0, limit
    step = 8
    while step < high and a[i - step:i] == b[j - step:j]:
        low = step
        step *= 2
    if step < high:
        high = step
    while high - low > 1:
        middle = (low + high) // 2
        if a[i - middle:i - low] == b[j - middle:j - low]:
            low = middle
        else:
            high = middle
    return low


def _automaton_longest(a, alo, ahi, b, blo, bhi, cap):
    """a[alo:ahi] と b[blo:bhi] のいちばん長い共通の部分（同じ長さなら a で前、それも同じなら b で前）を、
    b[blo:bhi] の接尾辞オートマトンで求める。cap は答えの長さの上限（証明済み）で、そこに届いたら読むのをやめる。

    各状態に、その状態の文字列が b で最初に終わる位置（first）を持たせる（同じ状態の文字列は、終わる位置の集まりが同じ）。
    a を前から1字ずつ読み、今の位置で終わる、b にある最も長い文字列の長さを更新する。長さが今までの最大を超えたときだけ記録するので、
    最大の長さに最初に届いた a の位置が残る（a で最も前）。b の位置は、その状態の first から求める（b で最も前）。"""
    link = [-1]
    length = [0]
    trans = [{}]
    first = [-1]
    last = 0
    for pos in range(blo, bhi):
        c = b[pos]
        cur = len(length)
        length.append(length[last] + 1)
        link.append(0)
        trans.append({})
        first.append(pos)
        p = last
        while p != -1 and c not in trans[p]:
            trans[p][c] = cur
            p = link[p]
        if p != -1:
            q = trans[p][c]
            if length[p] + 1 == length[q]:
                link[cur] = q
            else:
                clone = len(length)
                length.append(length[p] + 1)
                link.append(link[q])
                trans.append(trans[q].copy())
                first.append(first[q])
                while p != -1 and trans[p].get(c) == q:
                    trans[p][c] = clone
                    p = link[p]
                link[q] = clone
                link[cur] = clone
        last = cur
    state = size = best = 0
    best_end = best_state = -1
    for pos in range(alo, ahi):
        c = a[pos]
        while state and c not in trans[state]:
            state = link[state]
            size = length[state]
        target = trans[state].get(c)
        if target is None:
            state = size = 0
            continue
        state = target
        size += 1
        if size > best:
            best, best_end, best_state = size, pos, state
            if best >= cap:
                break
    if not best:
        return difflib.Match(alo, blo, 0)
    return difflib.Match(best_end - best + 1, first[best_state] - best + 1, best)


def _gram_index(b, q):
    """b の長さ q の部分文字列を引く表。各位置 j について、b[j:j+q] の hash の下位ビットと j を1つの整数にまとめ、小さい順に並べた配列。

    部分文字列そのものを鍵にした辞書は、数十万字の b で1つ数十MB になる（鍵の文字列と位置の一覧の分）。整数の配列なら1位置8バイトで済む。
    同じ hash の位置は j の小さい順に続くので、ある範囲の中の位置を二分探索で引ける。hash が同じでも中身の違う部分文字列があるので、
    引いた位置は必ず b を切り出して比べる（hash は表を引く手がかりにだけ使い、答えには使わない。実行ごとに hash の値が変わっても同じ答えになる）。"""
    shift = len(b).bit_length()           # 位置の分のビット数
    keep = (1 << (63 - shift)) - 1        # 残す hash のビット（まとめた整数が符号つき64ビットに収まるように）
    keys = sorted([((hash(b[j:j + q]) & keep) << shift) | j for j in range(len(b) - q + 1)])
    return array("q", keys), shift, keep, (1 << shift) - 1


def _rolling_hashes(codes, size):
    """codes（字の番号の配列）の、長さ size の部分ごとの多項式の hash を、位置の順に出す（部分がなければ何も出さない）。
    1字ずつずらして求めるので、1つの部分の手間は size によらない。同じ並びは必ず同じ値になる。違う並びが同じ値になることも
    まれにあるので、使う側は値が同じ所を必ず切り出して比べる（hash は手がかりにだけ使い、答えには使わない）。"""
    if size <= 0 or len(codes) < size:
        return
    mod, base = _ROLLING_MOD, _ROLLING_BASE
    top = pow(base, size - 1, mod)
    value = 0
    for code in codes[:size]:
        value = (value * base + code) % mod
    yield value
    for old, new in zip(codes, codes[size:]):
        value = ((value - old * top) * base + new) % mod
        yield value


class _ExactSequenceMatcher(difflib.SequenceMatcher):
    """difflib.SequenceMatcher と同じ答えを返す照合。文字列どうしで捨てる要素がないときだけ、速い求め方を使う。

    difflib の find_longest_match(alo, ahi, blo, bhi) が返すのは、a[alo:ahi] と b[blo:bhi] の中でいちばん長い共通の部分 (i, j, k) のうち、
    i が最も小さいもの、それも同じなら j が最も小さいもの（共通の部分がなければ (alo, blo, 0)）。DP が i の小さい順、同じ i では j の小さい順に
    見て、今までの最大を超えたときだけ記録するため。捨てる要素がなければ、difflib の最後の「一致を前後に広げる」処理は何もしない
    （広げられるなら、それより長い共通の部分があることになり、いちばん長いことに反する）。
    このクラスは同じ値を、次のどれかで求める。どれも「いちばん長く、a で最も前、b で最も前」を求めるので、どれを選んでも答えは同じ。
      1. 上限の長さが片方の範囲の長さと同じなら、str.find でその範囲がもう片方に含まれるかを見る（find は最も前の位置を返す）。
      2. 上限が _MATCH_PROBE_MAX 以下なら、上限の長さちょうどの一致を、その長さの部分文字列の表で a の前から探す。
         見つかれば答え。見つからなければ、答えの長さは上限 -1 以下と分かる。
      3. 長い一致は種で探す（_seeded）。長さ L 以上の一致がなければ、答えは L より短いと分かるので、L を半分にして続ける。
      4. 残りは、difflib と同じ DP（b の位置のうち範囲の中のものだけをたどる）か、接尾辞オートマトン（_automaton_longest）で求める。
         b の範囲がとても長いときは、オートマトンの代わりに答えの長さを二分探索で決める（_bisect_length。記憶を多く使わないため）。

    get_matching_blocks は difflib と同じ順に範囲を分け、分けた範囲に答えの長さの上限を渡す。上限は見積もりではなく、次のとおり必ず成り立つ。
    範囲の答えを (i, j, k) とすると、
      - 右の範囲 [i+k, ahi) × [j+k, bhi) の一致は、元の範囲の中の一致でもあるので、長さは k 以下。
      - 左の範囲 [alo, i) × [blo, j) に長さ k の一致があれば、元の範囲の中で i より前から始まる長さ k の一致になり、
        答えが「a で最も前」であることに反する。よって長さは k-1 以下。

    使い回す表（_seed_indexes、_probe_indexes、_collision_rate）は、要るときに作って self.__dict__ に置き、並びを替えたら捨てる。
    difflib の __init__ は途中で set_seq1 と set_seq2 を呼ぶので、そのときはまだ表の属性がない。ないときも同じに扱えるよう、
    getattr でなく self.__dict__ の get、setdefault、pop で読み書きする（__init__ を上書きしなくて済む）。"""

    def set_seq1(self, a):
        if a is not self.__dict__.get("a"):
            self.__dict__.pop("_collision_rate", None)          # a と b の両方で決まる
        difflib.SequenceMatcher.set_seq1(self, a)

    def set_seq2(self, b):
        if b is not self.__dict__.get("b"):
            for key in ("_collision_rate", "_seed_indexes", "_probe_indexes"):   # b で決まる
                self.__dict__.pop(key, None)
        difflib.SequenceMatcher.set_seq2(self, b)

    def _fast(self):
        """速い求め方を使えるか。文字列どうしで、捨てる要素がないときだけ（それ以外は difflib に任せる）。"""
        return (self.isjunk is None and not self.bjunk and not self.bpopular
                and type(self.a) is str and type(self.b) is str)

    def get_matching_blocks(self):
        if self.matching_blocks is not None:
            return self.matching_blocks
        if not self._fast():
            return difflib.SequenceMatcher.get_matching_blocks(self)
        # difflib の get_matching_blocks と同じ。分けた範囲に答えの長さの上限を足しただけ。
        la, lb = len(self.a), len(self.b)
        queue = [(0, la, 0, lb, min(la, lb))]
        matching_blocks = []
        while queue:
            alo, ahi, blo, bhi, bound = queue.pop()
            i, j, k = x = self._longest(alo, ahi, blo, bhi, bound)
            if k:
                matching_blocks.append(x)
                if alo < i and blo < j:
                    queue.append((alo, i, blo, j, k - 1))
                if i + k < ahi and j + k < bhi:
                    queue.append((i + k, ahi, j + k, bhi, k))
        matching_blocks.sort()
        i1 = j1 = k1 = 0
        non_adjacent = []
        for i2, j2, k2 in matching_blocks:
            if i1 + k1 == i2 and j1 + k1 == j2:
                k1 += k2
            else:
                if k1:
                    non_adjacent.append((i1, j1, k1))
                i1, j1, k1 = i2, j2, k2
        if k1:
            non_adjacent.append((i1, j1, k1))
        non_adjacent.append((la, lb, 0))
        self.matching_blocks = list(map(difflib.Match._make, non_adjacent))
        return self.matching_blocks

    def find_longest_match(self, alo=0, ahi=None, blo=0, bhi=None):
        ahi = len(self.a) if ahi is None else ahi
        bhi = len(self.b) if bhi is None else bhi
        # 範囲が文字列の外にはみ出す呼び方（負の位置など）と、位置が int でない呼び方（True など）も、difflib に任せて同じふるまいにする
        # （difflib は、一致があれば位置を足し引きして int で返し、なければ渡された alo と blo をそのまま返す）
        if not (self._fast() and type(alo) is int and type(ahi) is int and type(blo) is int and type(bhi) is int
                and 0 <= alo <= ahi <= len(self.a) and 0 <= blo <= bhi <= len(self.b)):
            return difflib.SequenceMatcher.find_longest_match(self, alo, ahi, blo, bhi)
        return self._longest(alo, ahi, blo, bhi, min(ahi - alo, bhi - blo))

    def _longest(self, alo, ahi, blo, bhi, bound):
        """find_longest_match(alo, ahi, blo, bhi) と同じ値。bound は答えの長さの上限（証明済み）。"""
        a, b = self.a, self.b
        la, lb = ahi - alo, bhi - blo
        cap = min(bound, la, lb)
        if cap <= 0:
            return difflib.Match(alo, blo, 0)
        if la * lb <= _MATCH_SMALL_AREA:
            return self._dp(alo, ahi, blo, bhi)
        # 1と2. 上限の長さちょうどの一致を探す。見つかれば、a で最も前（同じ a なら b で最も前）のものが答え。
        # 見つからなければ、答えは上限 -1 以下。
        if cap == la:
            j = b.find(a[alo:ahi], blo, bhi)
            if j != -1:
                return difflib.Match(alo, j, cap)
            cap -= 1
        elif cap == lb:
            i = a.find(b[blo:bhi], alo, ahi)
            if i != -1:
                return difflib.Match(i, blo, cap)
            cap -= 1
        elif cap <= _MATCH_PROBE_MAX:
            found = self._probe(alo, ahi, blo, bhi, cap)
            if found is not None:
                return found
            cap -= 1
        if cap <= 0:
            return difflib.Match(alo, blo, 0)
        # 3. 長い一致を種で探す。長さ L 以上の一致がなければ答えは L より短いので、L を半分にして続ける。
        length = cap
        while length >= _MATCH_SAMPLE_MIN:
            found = self._seeded(alo, ahi, blo, bhi, length, (la + lb) // _MATCH_SAMPLE_BUDGET_DIV)
            if found is None:                # 候補が多すぎて調べきれない。何も決めずに次の手に回す
                break
            if found is not False:
                return found
            cap = length - 1
            length //= 2
        # 4. 残り。DP の手間（範囲の中の同じ字の組の数の見込み）が小さければ DP、大きければ接尾辞オートマトン。
        # b の範囲がとても長いときは、オートマトンの代わりに答えの長さを二分探索で決める（使う記憶を抑える）。
        if la * lb * self._collision() <= _MATCH_SAM_FACTOR * (la + lb):
            return self._dp(alo, ahi, blo, bhi)
        if lb <= _MATCH_AUTOMATON_MAX:
            return _automaton_longest(a, alo, ahi, b, blo, bhi, cap)
        return self._bisect_length(alo, ahi, blo, bhi, cap)

    def _bisect_length(self, alo, ahi, blo, bhi, cap):
        """答えの長さを二分探索で決めて、_longest と同じ値を返す（cap は答えの長さの上限）。
        長さ m の共通の部分があれば、その端を1字削った長さ m-1 の共通の部分もあるので、「長さ m ちょうどの一致があるか」は m について単調。
        最後に見つかった長さが答えの長さで、そのとき _first_of_length が返す一致（a で最も前、同じ a なら b で最も前）が答えになる。
        この道を通るのは、b の範囲が _MATCH_AUTOMATON_MAX より長く、種で探す段が候補の多さで止まったとき（1字や短い周期の
        くり返しが長く続く文字列）だけ。段の数は cap の対数で、1段の手間は _first_of_length のとおり。"""
        low, high, found = 0, cap, None
        codes = []          # 長い長さの段で使う、範囲の字の番号の配列（段をまたいで使い回す）
        while low < high:
            middle = (low + high + 1) // 2
            match = self._first_of_length(alo, ahi, blo, bhi, middle, codes)
            if match is None:
                high = middle - 1
            else:
                low, found = middle, match
        return found if found is not None else difflib.Match(alo, blo, 0)

    def _first_of_length(self, alo, ahi, blo, bhi, size, codes):
        """長さ size ちょうどの共通の部分のうち、a で最も前、同じ a なら b で最も前のもの。なければ None（_probe と同じ値）。
        b[blo:bhi] の長さ size の部分ごとの hash を集め、a の位置を前から見て、hash が集まりにあるときだけ実際の字で確かめる。
        同じ字の並びの hash は必ず同じなので、hash が集まりにない a の位置には、b[blo:bhi] に同じ並びがない。
        段ごとに作り直し、残さない（b 全体の表を長さごとに残す _probe と違い、記憶を使い続けない）。

        size が _MATCH_ROLLING_MIN より短いときは、部分を切り出して hash を取り、確かめは str.find（b[blo:bhi] の中で最も前の位置を
        返し、hash が偶然同じなだけなら -1）で行う。1段の手間は（a と b の範囲の字数の和）× size だが、切り出しと hash は C の速さ。
        それ以上の長さでは、切り出す手間が size に比例して重くなる（1字のくり返し10万字で、二分探索の全体が30秒あまりかかった）ので、
        1字ずつずらして求める hash（_rolling_hashes）を使う。1段の手間は字数の和に比例し、size によらない。
        b の側は hash ごとに最も前の位置を残す。その位置の字が a の部分と同じなら、同じ並びのもっと前の位置は同じ hash になり
        そちらが残るはずなので、それが最も前の位置になる。違えば（hash だけが同じ、まれ）、str.find で最も前の位置を探し直す。"""
        a, b = self.a, self.b
        if size < _MATCH_ROLLING_MIN:
            seen = {hash(b[j:j + size]) for j in range(blo, bhi - size + 1)}
            for i in range(alo, ahi - size + 1):
                gram = a[i:i + size]
                if hash(gram) in seen:
                    j = b.find(gram, blo, bhi)
                    if j != -1:
                        return difflib.Match(i, j, size)
            return None
        if not codes:
            codes.append(array("l", map(ord, a[alo:ahi])))
            codes.append(array("l", map(ord, b[blo:bhi])))
        first = {}
        for offset, value in enumerate(_rolling_hashes(codes[1], size)):
            if value not in first:
                first[value] = blo + offset
        get = first.get
        for offset, value in enumerate(_rolling_hashes(codes[0], size)):
            j = get(value)
            if j is not None:
                i = alo + offset
                gram = a[i:i + size]
                if b[j:j + size] != gram:
                    j = b.find(gram, blo, bhi)
                    if j == -1:
                        continue
                return difflib.Match(i, j, size)
        return None

    def _probe(self, alo, ahi, blo, bhi, size):
        """長さ size ちょうどの共通の部分のうち、a で最も前、同じ a なら b で最も前のもの。なければ None。
        a の位置を前から順に見て、その位置の size 字が b[blo:bhi] のどこに最初にあるかを表で引く。"""
        a, b = self.a, self.b
        if bhi - blo <= _MATCH_WHOLE_INDEX_MIN:
            first = {}
            for j in range(bhi - size, blo - 1, -1):      # 後ろから入れて、同じ部分文字列は最も前の位置を残す
                first[b[j:j + size]] = j
            get = first.get
            for i in range(alo, ahi - size + 1):
                j = get(a[i:i + size])
                if j is not None:
                    return difflib.Match(i, j, size)
            return None
        # b の範囲が長いときは、b 全体の表を長さごとに作って使い回す（右の範囲が続くと、同じ長さで何度も引くため）。
        # 表は最近使った順に _MATCH_PROBE_CACHE 個まで残す。表のない長さで、範囲が b 全体より十分小さいときは、表を作らずに
        # その範囲だけで探す（字の種類の少ない文字列では、範囲ごとに上限の長さがばらばらで、b 全体の表を作り直し続けることがある）。
        cache = self.__dict__.setdefault("_probe_indexes", {})
        index = cache.pop(size, None)
        if index is None:
            if (ahi - alo) + (bhi - blo) <= len(b) // _MATCH_LOCAL_DIV:
                return self._probe_local(alo, ahi, blo, bhi, size)
            while cache and len(cache) >= _MATCH_PROBE_CACHE:
                del cache[next(iter(cache))]                # いちばん前に使った長さの表を捨てる
            index = _gram_index(b, size)
        cache[size] = index                                 # 使った表を最後に置く（dict は入れた順を保つ）
        keys, shift, keep, low = index
        count = len(keys)
        last = bhi - size
        for i in range(alo, ahi - size + 1):
            gram = a[i:i + size]
            base = (hash(gram) & keep) << shift
            p = bisect_left(keys, base | blo)
            end = base | last
            while p < count and keys[p] <= end:
                j = keys[p] & low
                if b[j:j + size] == gram:
                    return difflib.Match(i, j, size)
                p += 1
        return None

    def _probe_local(self, alo, ahi, blo, bhi, size):
        """_probe と同じ値を、範囲の中だけの表で求める（短いほうの側の部分文字列の表を作り、もう片方を前から見る）。
        b の側の表なら、a の位置を前から見て最初に見つかったものが答え（_probe の短い範囲と同じ）。
        a の側の表（部分文字列ごとに最も前の a の位置）なら、b の位置を前から見て、引けた a の位置がそれまでより前のときだけ残す。
        同じ a の位置は、b で最も前の位置で最初に引けるので、残ったものが a で最も前、同じ a なら b で最も前になる。"""
        a, b = self.a, self.b
        if bhi - blo <= ahi - alo:
            first = {}
            for j in range(bhi - size, blo - 1, -1):
                first[b[j:j + size]] = j
            get = first.get
            for i in range(alo, ahi - size + 1):
                j = get(a[i:i + size])
                if j is not None:
                    return difflib.Match(i, j, size)
            return None
        first = {}
        for i in range(ahi - size, alo - 1, -1):
            first[a[i:i + size]] = i
        get = first.get
        best = None
        for j in range(blo, bhi - size + 1):
            i = get(b[j:j + size])
            if i is not None and (best is None or i < best[0]):
                best = (i, j)
                if i == alo:
                    break
        return None if best is None else difflib.Match(best[0], best[1], size)

    def _seeded(self, alo, ahi, blo, bhi, length, budget):
        """長さ length 以上の共通の部分のうち、いちばん長く、a で最も前、同じ a なら b で最も前のもの。
        なければ False（答えは length-1 以下と分かる）。調べる候補が budget を超えたら None（何も決めない）。

        種の長さを q、格子の間隔を s = length-q+1 とし、a の格子の位置 t を alo+s-1 から s おきにとる。長さ length 以上の
        共通の部分が a[x:x+length] を含むとき、区間 [x, x+length-q]（s 個の連続した位置。x >= alo なので alo+s-1 以上の格子の位置が入る）
        には格子の位置 t が必ず1つあり、その共通の部分は種 a[t:t+q] を含む。そこで、格子の位置の種が b[blo:bhi] に現れる所をすべて引き、
        そこから範囲の中で前後に伸ばせるだけ伸ばした一致を集め、いちばん長く、a で最も前、b で最も前のものを選ぶ。
        答え（いちばん長い共通の部分）は、それ以上伸ばせないので、伸ばした一致のどれかとして必ず集まる。"""
        a, b = self.a, self.b
        q = _MATCH_SEED_LONG if length >= 2 * _MATCH_SEED_LONG else _MATCH_SEED_SHORT
        indexes = self.__dict__.setdefault("_seed_indexes", {})
        index = indexes.get(q)
        if index is None:
            index = indexes[q] = _gram_index(b, q)
        keys, shift, keep, low = index
        count = len(keys)
        step = length - q + 1
        last = bhi - q
        seeds = []
        total = 0
        for t in range(alo + step - 1, ahi - q + 1, step):
            gram = a[t:t + q]
            base = (hash(gram) & keep) << shift
            p = bisect_left(keys, base | blo)
            end = base | last
            while p < count and keys[p] <= end:
                u = keys[p] & low
                if b[u:u + q] == gram:
                    seeds.append((t, u))
                    total += 1
                    if total > budget:
                        return None
                p += 1
        best = None
        for t, u in seeds:
            back = _common_suffix_len(a, t, b, u, min(t - alo, u - blo))
            size = back + q + _common_prefix_len(a, t + q, b, u + q, min(ahi - t, bhi - u) - q)
            if size >= length:
                candidate = (-size, t - back, u - back)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            return False
        return difflib.Match(best[1], best[2], -best[0])

    def _collision(self):
        """a の1字と b の1字が同じである割合（DP の手間の見積もりにだけ使う）。"""
        rate = self.__dict__.get("_collision_rate")
        if rate is None:
            count_a, count_b = Counter(self.a), Counter(self.b)
            same = sum(n * count_b.get(ch, 0) for ch, n in count_a.items())
            rate = self._collision_rate = same / float(max(1, len(self.a) * len(self.b)))
        return rate

    def _dp(self, alo, ahi, blo, bhi):
        """difflib の find_longest_match の DP と同じ。b の字の位置の一覧（b2j）のうち、[blo, bhi) の中の位置だけをたどる
        （difflib は範囲の外の位置を continue と break で飛ばすので、たどる位置も、記録する値も同じ）。"""
        a, b2j = self.a, self.b2j
        besti, bestj, bestsize = alo, blo, 0
        j2len = {}
        for i in range(alo, ahi):
            positions = b2j.get(a[i])
            newj2len = {}
            if positions:
                get = j2len.get
                for j in positions[bisect_left(positions, blo):bisect_left(positions, bhi)]:
                    k = newj2len[j] = get(j - 1, 0) + 1
                    if k > bestsize:
                        besti, bestj, bestsize = i - k + 1, j - k + 1, k
            j2len = newj2len
        return difflib.Match(besti, bestj, bestsize)


def ending_changes(o: str, r: str):
    """書き直しで文末の種類が変わった文。似ている元の文と組にして比べる"""
    return _ending_changes_from_units(ending_units(o), ending_units(r))


# 文末の種類の比べで、元の文と書き直した文の字数の積がこれを超える組は、ratio を _ExactSequenceMatcher で求める（答えは difflib と同じ）。
# difflib の ratio は長い文の組で長さの2乗の時間がかかる（「。」のない2万字の1文で20秒あまり）。短い文の組では difflib のほうが速い。
_ENDING_EXACT_AREA = 160000


def _ending_changes_from_units(ou, ru):
    """Reuse already parsed rows within diff; keep standalone parsing unchanged."""
    # 同じ文の最初の出現を保つ。同点では元の文の順番が優先される。
    originals = OrderedDict()
    for y in ou:
        originals.setdefault(y["sentence"], y)
    items = lengths = at_least = None
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
                exact = None
                if at_least is None:
                    # at_least[ch][t] は、字 ch を t+1 回以上含む元の文の番号の一覧（番号の順）
                    items = list(originals.items())
                    lengths = [len(original) for original, _ in items]
                    at_least = {}
                    for i, (original, _) in enumerate(items):
                        for ch, n in Counter(original).items():
                            levels = at_least.setdefault(ch, [])
                            while len(levels) < n:
                                levels.append([])
                            for t in range(n):
                                levels[t].append(i)
                # overlaps[i] は、字ごとの min(この文の数, 元の文 i の数) の和（字の多重集合の重なり。ratio の上限に使う）。
                # min(n, c) は「c >= t となる t（1..n）の数」なので、字ごとに at_least の最初の n 段を数え足す。
                # v2.0.0 は字ごとに、その字を含む元の文の数だけ Python で min を足していた。数え足しを Counter.update（C の速さ）に
                # しただけで、値は同じ。手間の大きさは変わっていない。「。」や「の」はほとんどの元の文にあるので、この数え足しと下の
                # 元の文ごとの確かめは「書き直した文の数 × 元の文の数」に近い回数になる（全面書き換えでは文の数の2乗。速くなったのは
                # 1回あたりの手間だけ）。
                overlaps = Counter()
                for ch, n in Counter(sentence).items():
                    levels = at_least.get(ch)
                    if levels:
                        for indexes in levels[:n]:
                            overlaps.update(indexes)
                rewrite_len = len(sentence)
                # 共通の字が1つもない元の文は、overlap_bound が0で下の条件に届かないので、見なくても同じ（total_len が0になるのは
                # この文と元の文がどちらも空のときだけで、そのときは上の完全一致で決まっている）。
                # 残りは前と同じ番号の順に、同じ条件で見る。
                for i in sorted(overlaps):
                    original, y = items[i]
                    total_len = lengths[i] + rewrite_len
                    length_bound = 2.0 * min(lengths[i], rewrite_len) / total_len if total_len else 1.0
                    if length_bound < 0.45 or length_bound <= score:
                        continue
                    overlap_bound = 2.0 * overlaps[i] / total_len if total_len else 1.0
                    if overlap_bound < 0.45 or overlap_bound <= score:
                        continue
                    if lengths[i] * rewrite_len > _ENDING_EXACT_AREA:
                        if exact is None:
                            exact = _ExactSequenceMatcher(None, "", sentence, autojunk=False)
                        exact.set_seq1(original)
                        sc = exact.ratio()
                    else:
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


_ASTERISKS = re.compile(r"\*+")


def _runs_from_masks(text, masked):
    runs = []
    mask_index = 0
    for match in _ASTERISKS.finditer(text):
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


def _delimiter_parse(text, punct, runs=None, state=None, stop=None):
    """Same nearest-compatible opener, indexed by the six rule-3 classes.

    state（_DelimiterStack）を渡すと、その状態の続きから runs[state.index:stop] だけを処理し、state を書き換える。
    """
    if runs is None:
        runs = _star_runs(text)
    if state is None:
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
    else:
        openers, buckets, gfm_bounds, bottoms = state.openers, state.buckets, state.gfm_bounds, state.bottoms
        pairs, emphasis, consumed = state.pairs, state.emphasis, state.consumed
        runs, state.index = runs[state.index:stop], stop
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


class _DelimiterStack:
    """_delimiter_parse の途中の状態。advance(stop) で、runs[stop] の手前まで進める。

    直し方の案を確かめるときに、ある印の手前の状態を読むために使う。進め方は _delimiter_parse と同じ処理を通る。
    """
    __slots__ = ("text", "punct", "runs", "index", "openers", "buckets", "gfm_bounds",
                 "bottoms", "pairs", "emphasis", "consumed")

    def __init__(self, text, punct, runs):
        self.text = text
        self.punct = punct
        self.runs = runs
        self.index = 0
        self.openers = []
        self.buckets = {(mod, closes): [] for mod in range(3) for closes in (False, True)}
        self.gfm_bounds = punct is _bold_punct_gfm
        self.bottoms = {}
        self.pairs = []
        self.emphasis = []
        self.consumed = set()

    def advance(self, stop):
        if stop > self.index:
            _delimiter_parse(self.text, self.punct, self.runs, self, stop)

    def finds_opener(self, closer_length, can_open):
        """今の状態で、長さ closer_length の閉じられる印が、組む相手を1つでも見つけるか。状態は変えない。

        advance の中で opener が None のままになるかどうかと同じ条件を見る。
        """
        closer_mod = closer_length % 3
        bottom = self.bottoms.get((closer_mod, None if self.gfm_bounds else can_open), -1)
        for (mod, closes), bucket in self.buckets.items():
            blocked = ((can_open or closes) and (mod + closer_mod) % 3 == 0
                       and (mod != 0 or closer_mod != 0))
            if bucket and not blocked and bucket[-1]["start"] >= bottom:
                return True
        return False


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


# ---- 1つの段落に崩れた太字が多いときの、直し方の案の確かめ ----
# 案を1つ試すたびにブロック全体を書き換えて解析し直すと、1つの段落の中の崩れの数の2乗で時間がかかる。
# そこで、書き換えが近くの数文字だけを動かすことを使い、ブロック全体を解析し直したときと同じ答えになると
# 言える場合に限って、元の解析の結果から答えを出す。言えない場合は、今までどおり解析し直す。
# 案の書き換えは次の3通りで、どれも ** を内側の1文字の向こうへ動かすか、** の外側に半角スペースを1つ入れるだけ。
#   かっこ: **「X」** → 「**X**」、句読点: **X。** → **X**。、スペース: **X** → **X** の外側に空白
# 同じ答えになることは、次の3段で確かめる。
#   1. 行の種類とブロックの分かれ方が変わらない（行頭の印を読む処理が、変わる位置より前で止まる）
#   2. インラインの保護範囲（コード、エスケープ、リンク、URL など）が、位置のずれを除いて変わらない
#   3. 印の組み合わせ（2つの表示の規則）で、狙いの組ができ、ほかの組がすべて残る
# 3は、書き換えた位置より前の状態を元の解析から読み、書き換えた2つの印だけをその上で処理して決める。
# 元の段落で相手のない印（書き換え前の2つの印）は、それより後で一度も相手に選ばれないので、なくなっても
# 後ろの組み合わせは変わらない。閉じる相手が見つからなかった位置の記録（bottoms）が食い違う場合だけ、
# 手前の印の位置と比べて、後ろの組み合わせが変わりえないかを確かめる。
_LINE_START_MARKS = frozenset(" \t>-+*.)#`~[")
_REFERENCE_START = re.compile(r" {0,3}\[")
_URL_START = re.compile(r"(?=https?://|www\.)")
_WHITESPACE_CHAR = re.compile(r"\s")
_LINK_DESTINATION_START = re.compile(r"\]\(")


def _line_start_stopper(ch):
    """行頭の印（コンテナ、見出し、コードの柵など）を読む処理が、そこで必ず止まる文字か。

    行頭を読む処理が受ける文字は、半角スペース、タブ、> - + * . ) # ` ~ [ と数字だけ（数字は isdigit で広めにとる）。
    """
    return ch != "" and ch not in _LINE_START_MARKS and not ch.isdigit()


def _merged_intervals(spans):
    merged = []
    for left, right in sorted((left, right) for left, right, _ in spans):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged, [right for _, right in merged]


def _interval_overlaps(intervals, ends, left, right):
    index = bisect_right(ends, left)
    return index < len(intervals) and intervals[index][0] < right


def _interval_covers(intervals, ends, position):
    index = bisect_right(ends, position)
    return index < len(intervals) and intervals[index][0] <= position


def _interval_splits(intervals, ends, position):
    """position の直前と直後の文字が、同じ範囲（つながった範囲）に入るか。"""
    index = bisect_right(ends, position)
    return index < len(intervals) and intervals[index][0] < position


def _bold_run_index(context):
    """context のランから、ランの番号を引く表を作る（1回だけ）。"""
    run_index = context.get("run_index")
    if run_index is None:
        run_index = context["run_index"] = {run: number for number, run in enumerate(context["runs"])}
    return run_index


def _bold_repair_index(text, context):
    """ブロックごとに1回だけ作る。速く確かめられないブロックでは None を返す（今までどおり解析し直す）。"""
    if "repair_index" in context:
        return context["repair_index"]
    index = None
    # 「<」があると、HTML の組み立てと自動リンクが遠くまで読むので、近くだけを見る確かめができない。
    if "<" not in text:
        analysis = analyze_markdown(text, skip_frontmatter=False)
        if (_runs_from_masks(text, analysis["mask_spans"]) == context["runs"]
                and not any(row["kind"] == "reference_definition" for row in analysis["lines"])
                and not any(block["kind"] in ("paragraph", "list", "quote", "heading")
                            and _REFERENCE_START.match(block["lines"][0]["content"])
                            for block in analysis["blocks"])):
            index = _BoldRepairIndex(text, context, analysis)
    context["repair_index"] = index
    return index


class _BoldRepairIndex:
    """1つのブロックの、案の確かめに使う元の解析の結果。"""

    def __init__(self, text, context, analysis):
        self.text = text
        self.runs = context["runs"]
        self.run_index = _bold_run_index(context)
        rows = analysis["lines"]
        self.line_starts = [row["start"] for row in rows]
        self.content_starts = [row["content_start"] for row in rows]
        self.line_ends = [row["start"] + len(row["raw"]) for row in rows]
        self.first_stoppers = {}
        spans = context.get("opaque_spans")
        if spans is None:
            spans = inline_protected_spans(text)
        self.raw, self.raw_ends = _merged_intervals(spans)
        self.masks, self.mask_ends = analysis["mask_spans"], analysis["mask_ends"]
        self.url_starts = [match.start() for match in _URL_START.finditer(text)]
        self.spaces = [match.start() for match in _WHITESPACE_CHAR.finditer(text)]
        # リンクの行き先を読んで失敗した「](」は、どこまで読んだか分からない。手前にあれば確かめない。
        self.unsure_links = [match.start() for match in _LINK_DESTINATION_START.finditer(text)
                             if not (_interval_covers(self.raw, self.raw_ends, match.start() + 1)
                                     and _interval_covers(self.masks, self.mask_ends, match.start() + 1))]
        self.parsers = {}
        self.emphasis = {_bold_punct_gfm: set(context["gfm"]), _bold_punct_new: set(context["common"])}

    def _first_stopper(self, line):
        position = self.first_stoppers.get(line)
        if position is None:
            text, position, end = self.text, self.line_starts[line], self.line_ends[line]
            while position < end and not _line_start_stopper(text[position]):
                position += 1
            self.first_stoppers[line] = position
        return position

    def _line_start_kept(self, edit, inserted, char_after):
        """edit より前を変えない書き換えで、その行の行頭の読み方が変わらないか。"""
        line = bisect_right(self.line_starts, edit) - 1
        if line < 0 or edit < self.content_starts[line]:
            return False
        if self._first_stopper(line) < edit:
            return True  # 行頭を読む処理は、edit より前の文字で止まる
        # 中身の頭（行頭の印のあと、半角スペースとタブのあと）が ** なら、行頭を読む処理は2つめの * で止まる。
        text, lead = self.text, self.content_starts[line]
        while lead < edit and text[lead] in " \t":
            lead += 1
        if text[lead:lead + 2] == "**" and edit >= lead + 2:
            return True
        if edit == lead and not inserted:
            before = text[edit:edit + 2] == "**" or _line_start_stopper(text[edit])
            after = char_after(edit) + char_after(edit + 1) == "**" or _line_start_stopper(char_after(edit))
            return before and after
        return False

    def _parser(self, punct, index):
        parser = self.parsers.get(punct)
        if parser is None or parser.index > index:
            parser = self.parsers[punct] = _DelimiterStack(self.text, punct, self.runs)
        parser.advance(index)
        return parser

    def decide(self, i, j, shape, middle):
        """案で直した文がもとの確かめを通るなら True、通らないなら False、ここで決められないなら None。"""
        text = self.text
        before = self.run_index.get((i, i + 2))
        if before is None or self.run_index.get((j, j + 2)) != before + 1:
            return None
        if shape == "bracket":
            # ASCII のかっこを動かすと、隣り合う「](」と「![」が生まれることがある（リンクと画像の記法）
            if text[i + 2] == "(" and text[i - 1:i] == "]":
                return None
            if text[i + 2] == "[" and (text[i - 1:i] == "!" or text[j + 2:j + 3] == "("):
                return None
            changed, gaps = ((i, i + 3), (j - 1, j + 2)), ()
            edits = ((i, False), (j - 1, False))
            first, second, delta = i + 1, j - 1, 0
        elif shape == "punct":
            if text[j - 1] == "!" and text[j + 2:j + 3] == "[":
                return None  # 「!」が「[」の前に来ると画像の記法になる
            changed, gaps = ((j - 1, j + 2),), ()
            edits = ((j - 1, False),)
            first, second, delta = i, j - 1, 0
        else:
            left = len(middle) - len(middle.lstrip(" "))
            right = len(middle) - len(middle.rstrip(" "))
            if (left > 1 or right > 1 or len(middle) != left + right + j - i + 2
                    or middle[left:len(middle) - right] != text[i:j + 2]):
                return None
            changed = ()
            gaps = tuple(position for position, size in ((i, left), (j + 2, right)) if size)
            edits = tuple((position, True) for position in gaps)
            first, second, delta = i + left, j + left, left + right
        end = i + len(middle)

        def char_after(position):
            """書き換えたあとの文字（範囲の外は空の文字列）。"""
            if position < 0:
                return ""
            if position < i:
                return text[position]
            if position < end:
                return middle[position - i]
            position -= delta
            return text[position] if position < len(text) else ""

        if changed or gaps:
            if (shape == "bracket" or (gaps and gaps[0] == i)) and i and text[i - 1] == "\\":
                return None
            if shape in ("bracket", "punct") and text[j - 2] == "\\":
                return None
            for left, right in changed:
                if (_interval_overlaps(self.raw, self.raw_ends, left, right)
                        or _interval_overlaps(self.masks, self.mask_ends, left, right)):
                    return None
            for position in gaps:
                if (_interval_splits(self.raw, self.raw_ends, position)
                        or _interval_splits(self.masks, self.mask_ends, position)):
                    return None
            if self.unsure_links and self.unsure_links[0] <= j + 2:
                return None
            space = bisect_right(self.spaces, i - 1) - 1
            word_start = self.spaces[space] if space >= 0 else -1
            url = bisect_right(self.url_starts, word_start)
            if url < len(self.url_starts) and self.url_starts[url] <= j + 3:
                return None
            checked_lines = set()
            for position, inserted in edits:
                line = bisect_right(self.line_starts, position) - 1
                if line in checked_lines:
                    continue  # 同じ行の左の書き換えで、行頭の読み方は決まっている
                checked_lines.add(line)
                if not self._line_start_kept(position, inserted, char_after):
                    return None

        verdict = True
        for punct in (_bold_punct_gfm, _bold_punct_new):
            open_a, close_a = _roles(text, i, i + 2, punct)
            open_b, close_b = _roles(text, j, j + 2, punct)
            prev, nxt = char_after(first - 1), char_after(first + 2)
            open_first, close_first = _roles(prev + "**" + nxt, len(prev), len(prev) + 2, punct)
            prev, nxt = char_after(second - 1), char_after(second + 2)
            open_second, close_second = _roles(prev + "**" + nxt, len(prev), len(prev) + 2, punct)
            if not open_first or not close_second:
                return False
            state = self._parser(punct, before)
            if close_first and state.finds_opener(2, open_first):
                return False
            if close_a and state.finds_opener(2, open_a):
                return None  # 元の解析と食い違う（起きないはずの形）
            # 閉じる相手が見つからなかった位置の記録（bottoms）を、書き換えの前と後で比べる。
            # failed には、相手が見つからなかった閉じの印を (記録の鍵, 開けられるか, そのときの下限) で集める。
            gfm_bounds = punct is _bold_punct_gfm
            original, repaired, failed = {}, {}, []
            if close_a:
                key = (2, None if gfm_bounds else open_a)
                failed.append((key, open_a, state.bottoms.get(key, -1)))
                original[key] = i
            if close_b and (i, j, 2) not in self.emphasis[punct]:
                key = (2, None if gfm_bounds else open_b)
                failed.append((key, open_b, original.get(key, state.bottoms.get(key, -1))))
                original[key] = j
            if close_first:
                key = (2, None if gfm_bounds else open_first)
                failed.append((key, open_first, state.bottoms.get(key, -1)))
                repaired[key] = first
            for key in set(original) | set(repaired):
                kept = state.bottoms.get(key, -1)
                if original.get(key, kept) == repaired.get(key, kept) or min(original.get(key, kept),
                                                                              repaired.get(key, kept)) >= i:
                    continue  # 同じ値か、どちらも手前のどの印よりも後ろ
                # 片方だけが kept のまま。手前の印のうち kept 以降のものが、後ろの閉じの印から選ばれうると食い違う。
                if not state.openers or state.openers[-1]["start"] < kept:
                    continue
                # この鍵で kept を下限に相手を探して見つからなかった閉じの印があれば、そのとき選べた組の印は
                # どれも kept より前にある。CommonMark の規則では、同じ鍵の閉じの印はいつも同じ組を選べるので、
                # 食い違わない。GFM の規則では、開けられる閉じの印が選べない (1, False) の組だけが残る。
                proofs = [opens for failed_key, opens, bottom in failed if failed_key == key and bottom == kept]
                if proofs and (not gfm_bounds or not all(proofs)):
                    continue
                bucket = state.buckets[(1, False)]
                if proofs and (not bucket or bucket[-1]["start"] < kept):
                    continue
                verdict = None
        return verdict


def _bold_fix_with_context(text, i, j, k, known_pair, context):
    """Only a proved target repair is suggested; ambiguous star runs stay manual."""
    open_start, open_end = _star_extent(text, i)
    close_start, close_end = _star_extent(text, j)
    if open_end - open_start != 2 or close_end - close_start != 2:
        return None, "手で直す"
    # ランの多いブロックでは、ランの一覧の中を探すとランの数に比例して時間がかかる。番号の表を1回作って引く。
    runs = context["runs"]
    several = len(runs) > 2
    if len(runs) > 16:
        runs = _bold_run_index(context)
    if (i, i + 2) not in runs or (j, j + 2) not in runs:
        return None, "手で直す"
    inner = text[i + 2:j]
    if "*" in inner:
        return None, "手で直す"
    # In a multi-run paragraph a whitespace-only flanking symptom does not
    # identify the intended pair. Avoid both unsafe guesswork and N reparses.
    if several and (_bold_ws(inner[:1]) or _bold_ws(inner[-1:])):
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
        spans = inline_protected_spans(text)
        context["opaque_spans"] = spans
        context["opaque"] = [(kind, text[left:right]) for left, right, kind in spans]
    tries = []
    if len(inner) >= 3 and inner[0] in BOLD_BRACKETS and _bold_close_of(inner) == len(inner) - 1:
        tries.append((inner[0] + "**" + inner[1:-1] + "**" + inner[-1], "かっこの内側だけを太字にする", "bracket"))
    if len(inner) >= 2 and inner[-1] in "。、．，！？!?":
        tries.append(("**" + inner[:-1] + "**" + inner[-1], "句読点を太字の外に出す", "punct"))
    ch = lambda position: text[position] if 0 <= position < len(text) else ""
    body_start, body_end = 0, len(inner)
    while body_start < body_end and _bold_ws(inner[body_start]): body_start += 1
    while body_end > body_start and _bold_ws(inner[body_end - 1]): body_end -= 1
    body = inner[body_start:body_end]
    left = "" if _bold_can_open(ch(i - 1), body[:1]) else " "
    right = "" if _bold_can_close(body[-1:], ch(j + 2)) else " "
    tries.append((left + "**" + body + "**" + right, "太字の内側の空白を取る" if body != inner and not (left or right)
                  else "文字に接する側に半角スペースを入れる", "space"))
    # 3つ以上の印があるブロックで、解析し直した案が2つを超えたら、元の解析から決められる案を先に決める
    # （決められないときだけ解析し直す）。表を作る手間は、解析し直す1回分とほぼ同じなので、案の少ない
    # ブロックでは作らない。案を確かめる組がこのブロックに残り3組未満（いまの組を含む）のときも、表を作る
    # 手間を取り戻せないので作らない。すでに作った表があれば使う。
    for middle, how, shape in tries:
        if several and context.get("slow_tries", 0) >= 2 and ("repair_index" in context
                                                             or context.get("remaining", 3) >= 3):
            repair = _bold_repair_index(text, context)
            if repair is not None:
                verdict = repair.decide(i, j, shape, middle)
                if verdict is not None:
                    if verdict:
                        return middle, how
                    continue
        if several:
            context["slow_tries"] = context.get("slow_tries", 0) + 1
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


_CONTAINER_LIST = re.compile(r"^\s{0,3}(?:[*+-]|\d+[.)])\s+")
_CONTAINER_INDENT = re.compile(r"^\s{0,3}")


def _line_containers(line: str):
    """行のコンテナ（リストマーカー、引用の深さ）と、内部のコンテンツを簡易解析する"""
    is_list = False
    m_list = _CONTAINER_LIST.match(line)
    if m_list:
        is_list = True
        rem = line[m_list.end():]
    else:
        rem = line

    depth = 0
    p = 0
    while True:
        m_sp = _CONTAINER_INDENT.match(rem[p:])
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
        # このブロックで直し方の案を確かめる組の残りの数（表を作るかどうかを決める目安）
        remaining = sum(1 for pair in pairs if not (pair in gfm_pairs and pair in common_pairs))
        for ordinal, (i, j) in enumerate(pairs):
            if (i, j) in gfm_pairs and (i, j) in common_pairs:
                continue
            context["remaining"] = remaining
            remaining -= 1
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
    """v1.1.2 の diff() の9つの点検（markers から type_changes まで）。結果は v1.1.2 と1字も変えない。
    v2.0.1 で、語が原文にあるかを、同じ語ごとに1度だけ原文全体から探すようにした（値は同じ。足した部分の多い数十万字の文書で、
    同じ語を足した部分ごとに原文全体から探し直して重かった）。"""
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
    for name, pat in _MARKER_REGEXES:
        a, b = len(pat.findall(o)), len(pat.findall(r))
        if a != b:
            hits_r = [m.group(0) for m in pat.finditer(r)]
            hits_o = [m.group(0) for m in pat.finditer(o)]
            out["markers"].append({"kind": name, "orig": a, "rewrite": b,
                                   "orig_hits": hits_o, "rewrite_hits": hits_r})

    # 2. 元にない語・消えた語（語の単位で、文のどこかに出てくるかを見る）
    o_words = set(CONTENT.findall(o))
    r_words = set(CONTENT.findall(r))
    absent = {}

    def not_in_o(w):
        """w not in o と同じ。o から取った語は o にあるので探さず、ほかの語も、同じ語は o 全体から探し直さない。"""
        found = absent.get(w)
        if found is None:
            found = absent[w] = w not in o_words and w not in o
        return found
    out["new_words"] = sorted(w for w in r_words if not_in_o(w))
    out["lost_words"] = sorted(w for w in o_words if w not in r_words and w not in r)

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
                around = r[max(0, j1 - 3):j2 + 3]
                kinds = [n for n, p in _MARKER_REGEXES if p.search(around)]
                words = [w for w in CONTENT.findall(seg) if not_in_o(w)]
                if kinds or words:
                    out["spans"].append({"added": seg, "was": o[i1:i2], "kinds": kinds, "new_words": words,
                                         "where": context(r, j1, j2)})
    return out


def bold_head(where: str = "") -> str:
    return f"■ 太字にならない書き方（{where}GitHub などで ** がそのまま表示されることがある。表示可否と案の範囲を確認して直す）"


def bold_lines(problems):
    return [f"- {p['line']}行目: {p['found']} → {p['suggest'] or '（手で直す）'}（{p['how']}）" for p in problems]




# ---- 全文差分（v2.0.0）----
# 生の文を行で対応させ、変わった塊の中を文字で対応させる。normalize() は通さない。

_CHAR_ALIGN_LIMIT = 2000        # 文の断片をそのまま文字で対応させる、片側の字数の上限
# 塊をそのまま文字で対応させる、片側の字数の上限。これを超える塊は文の断片に分けてから対応させる（diff の詰め。
# 1行が1,500〜2,000字の文書の全面書き換えで、塊ごとの文字の対応が重かった）
_BLOCK_ALIGN_LIMIT = 500
_CHAR_BUDGET = 200000           # 文書全体で文字の対応にかける字数（対応させる文字列の長さの、両側の合計）
_PAIR_WINDOW = 4                # 文や断片を組にするとき、直前の組の次から見る数
_PAIR_RATIO = 0.45              # 組にする似かたの下限（difflib の ratio）
_LONG_LINE = 160                # これを超える行の「差:」は、変わった文のまわりだけを出す
# 文の断片。句点（。！？!?）のほか、「．」と、空白か行末が続く「.」（英語の文）でも切る
# （「．」の文と英語の文は、前は1行が1つの断片になり、長い文字列の対応が重かった）。3.14 のような数の中の「.」では切らない
_FRAGMENT = re.compile(r"(?:[^。！？!?．.\n]|\.(?![ \t\n]|$))*(?:[。！？!?．]+|\.+(?=[ \t\n]|$))?[」』）)]*[ \t]*\n?")
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
    時間が要素の数の2乗から3乗で伸びる（測った例: 短い段落900個の6万字で10秒あまり）。そこで次の順に対応させる。
    1. 前と後ろの同じ要素を外す。
    2. 両方に1回ずつだけ出る空白だけでない要素を組の候補にし、順番を保つ最長の並び（patience diff の考え方）を組にする。
       組と組の間を、同じ手順でたどる。
    3. 残った間が小さい（両側の要素の数の積が400以下）なら、difflib.SequenceMatcher で同じ要素を組にする。
       大きいなら、前から順に、近く（8つ先まで）にある同じ中身の要素を組にする。8つより先でも、そこまでに飛ばす要素のうち
       元の側にもある中身のものが8つ未満（飛ばすのはほぼ足した塊）なら組にする。
    4. similar が真なら、残った要素を文の組み方（_pair_similar。直前の組の次から4つ、ratio が0.45以上で最大のもの）で組にする。
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
    """文や断片の組み方。old[i1:i2] の各要素について、直前に組にした new の要素の次から4つの範囲で、
    quick_ratio が0.45以上のものを候補にし、ratio が最大で0.45以上なら組にする（順番を保つ）。

    どちらかが2,000字（_CHAR_ALIGN_LIMIT）を超える組には difflib の ratio() をかけず、前後の同じ字の数から求めた似かた
    （_affix_ratio）を使う。ratio() は長さのおよそ2乗の時間がかかり（「。」のない6万字の1行で十数秒）、処理時間の約束を
    守れない。2,000字を超える断片の組は全文差分では文字で対応させない（_CHAR_ALIGN_LIMIT）ので、組にするかの判断にだけ使われる。"""
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
            # real_quick_ratio と quick_ratio は ratio（と _affix_ratio）の上限。下限に届かないか、それまでの最大を超えられない
            # 候補は ratio を求めずに飛ばす（最大を超えたときだけ組を替えるので、結果は同じ。速さの直し）
            upper = matcher.real_quick_ratio()
            if upper < _PAIR_RATIO or upper <= best_ratio:
                continue
            upper = matcher.quick_ratio()
            if upper < _PAIR_RATIO or upper <= best_ratio:
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
    # 続く同じ印の文字列は、部品を集めてから1回でつなぐ（リストの要素に += でつなぐと、長い行でつなぐたびに全体を写し直し、
    # 部品の数と行の長さの積の時間になる）
    merged = []
    for tag, text in segments:
        if not text:
            continue
        if merged and merged[-1][0] == tag:
            merged[-1][1].append(text)
        else:
            merged.append([tag, [text]])
    return [[tag, parts[0] if len(parts) == 1 else "".join(parts)] for tag, parts in merged]


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
    if len(a) <= _BLOCK_ALIGN_LIMIT and len(b) <= _BLOCK_ALIGN_LIMIT:
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
                # 長い断片の組は文字で対応させないが、前と後ろの同じ字は外す（時間は字数に比例するだけ）。
                # 変えていないインラインのコードやリンク先を「変わった」と出さず、「差:」も出せる
                head, tail = _common_affix(old[x], new[y])
                segments.append(["=", old[x][:head]])
                segments.append(["-", old[x][head:len(old[x]) - tail]])
                segments.append(["+", new[y][head:len(new[y]) - tail]])
                segments.append(["=", old[x][len(old[x]) - tail:]])
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
        self.quiet_marks = []

    def line_of(self, side, position):
        """文字の位置（0から）を行番号（1から）にする。"""
        return max(1, bisect_right(self.starts[side], position))

    def normalized_lines(self, side):
        if self._normalized[side] is None:
            self._normalized[side] = [normalize(line) for line in self.lines[side]]
        return self._normalized[side]

    def numbers(self, side):
        """数値の取り出し方（_find_numbers）で取った数値（位置の順）と、その始まりの位置の並び。"""
        if self._numbers[side] is None:
            found = _find_numbers(self.texts[side], self.analyses[side])
            self._numbers[side] = (found, [number.start for number in found])
        return self._numbers[side]

    def all_keys(self, side):
        """伏せる前の数値（コード、URL、先頭の設定、HTML の中も含む）の (数, 単位) の集合と、数ごとの単位、範囲・日付・時刻の
        まとまり（_KeySet）。「文書のどこにもない」の判定に使う。"""
        cache = self.__dict__.setdefault("_all_keys", {})
        if side not in cache:
            cache[side] = _KeySet(_find_numbers(self.texts[side], self.analyses[side], ()))
        return cache[side]


def full_diff(orig, rw, encoding_notes=None):
    """元の文と書き直した文の全文差分（JSON の full_diff）。

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
    """消した空白だけでない行と中身が完全に同じ行が、ほかの hunk で足されていれば、2つの hunk を対にする（動かした行）。
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


# 見出しの変化（「構造」の見直し候補の文。意味が変わる恐れには入れず、--fail-on にも数えない）。見出しの数の増減と、
# 行ごとの変化（太字だけの行や本文の行を見出しにした、見出しを本文の行にした、見出しの段を変えた）を見る。行ごとの変化は、
# 全文差分の hunk の中の行（変わった行）で、印（#、太字、末尾のコロン）と空白を除いた文字が同じ行の組だけを見る（文字の違う行は、
# 見出しを足したか消したかで、見出しの数の増減に出る）。同じ置き換えの hunk の中の見出しどうしは、文字が少し違っても似ていれば組にする。
_HEADING_SHOWN = 3              # 1つの文に挙げる行の組の数（ほかは「ほか N か所」）
_HEADING_LINE_WIDTH = 30        # 行を挙げるときの字数の上限（超えたら「…」で切る）


def _heading_rows(analysis):
    """見出しのブロックごとの {最初の行の位置（0から）: (段, 印と空白を除いた文字)} と、見出しのブロックの行の位置から
    その見出しの最初の行の位置への対応（setext の下線の行を含む）。段は ATX なら # の数、setext なら = は1、- は2。"""
    rows = analysis["lines"]
    heads, inside = {}, {}
    for block in analysis["blocks"]:
        if block["kind"] != "heading":
            continue
        first = block["lines"][0]
        indexes = [row["line"] - 1 for row in block["lines"]]
        match = _ATX.match(first["content"]) if len(block["lines"]) == 1 else None
        if match:
            level = len(match.group(2))
        else:
            after = indexes[-1] + 1
            if after >= len(rows) or rows[after]["kind"] != "heading_underline":
                continue
            # 箇条書きの項目のあとの、字下げのない「-」「---」は次の項目か区切り線で、下線ではない（数えない）
            if rows[after]["content_start"] - rows[after]["start"] < first["content_start"] - first["start"]:
                continue
            indexes.append(after)
            level = 1 if rows[after]["content"].strip().startswith("=") else 2
        inside.update(dict.fromkeys(indexes, indexes[0]))
        text = "".join(row["content"] for row in block["lines"])
        heads[indexes[0]] = (level, _heading_key(text))
    return heads, inside


def _bold_only(content):
    """段落の行の全体が1つの太字なら、その中の文字。そうでなければ None（「**a** と **b**」は1つの太字でない）。"""
    match = _BOLD_ONLY_LINE.match(content)
    if match and "**" not in match.group(1) and "__" not in match.group(1):
        return match.group(1)
    return None


def _heading_key(text):
    """見出しと本文の行を比べる文字（見出しの #、全体の太字、空白、末尾のコロンを除く）。"""
    text = _ATX_MARKERS.sub("", text.strip())
    inner = _bold_only(text)
    return _SPACES.sub("", inner if inner is not None else text).rstrip("：:")


def _heading_shown(line):
    line = line.strip()
    return line if len(line) <= _HEADING_LINE_WIDTH else line[:_HEADING_LINE_WIDTH] + "…"


def _heading_counterpart(hunks, side, index):
    """hunk の外の行（side の側の位置 index、0から）が、相手の側で何行目（0から）に当たるか。"""
    start, end = ("old_start", "old_end") if side == 0 else ("new_start", "new_end")
    other_end = "new_end" if side == 0 else "old_end"
    found = index
    for hunk in hunks:
        if hunk[start] - 1 > index:
            break
        found = hunk[other_end] + (index - hunk[end])
    return found


def _heading_structure(sides, hunks):
    """見出しの変化を、「構造」の見直し候補の文の並びにする（_rule_candidates の structure の後ろに足す）。"""
    (old_heads, old_inside), (new_heads, new_inside) = _heading_rows(sides.analyses[0]), _heading_rows(sides.analyses[1])
    out = []
    if len(old_heads) != len(new_heads):
        out.append("見出しの数が変わった（{} → {}）。節の分け方が元と同じでよいか見る".format(len(old_heads), len(new_heads)))

    def role(side, index):
        """行の (種類, 段, 比べる文字)。種類は heading（見出しの最初の行）、bold（太字だけの本文の行）、body（ほかの本文の行）。
        見出しの続きの行、引用の中の本文、本文でない行、比べる文字のない行は None。"""
        heads, inside = (old_heads, old_inside) if side == 0 else (new_heads, new_inside)
        if index in heads:
            return ("heading",) + heads[index] if heads[index][1] else None
        rows = sides.analyses[side]["lines"]
        row = rows[index] if index < len(rows) else None
        if index in inside or row is None or row["kind"] != "paragraph" or row["quote_depth"]:
            return None
        key = _heading_key(row["content"])
        return (("bold" if _bold_only(row["content"]) is not None else "body"), None, key) if key else None

    # 変わった行（hunk の中の行）だけを見る。見出しの行と、相手の側の見出しと同じ文字の本文の行を、両側の順を保って組にする
    # （行の対応がずれて、太字の行と見出しが別の hunk に入ることがある）
    changed = ([], [])
    for hunk in hunks:
        if hunk["tag"] in ("replace", "delete"):
            changed[0].extend(range(hunk["old_start"] - 1, hunk["old_end"]))
        if hunk["tag"] in ("replace", "insert"):
            changed[1].extend(range(hunk["new_start"] - 1, hunk["new_end"]))
    # setext の下線の行だけが変わったときは、見出しの最初の行（変わっていない行）と、相手の側でそれに当たる行も見る
    # （下線を消して太字の行に戻したとき、- を = にして段を変えたとき）
    hunk_set = (set(changed[0]), set(changed[1]))
    for side in (0, 1):
        inside = old_inside if side == 0 else new_inside
        for index in list(changed[side]):
            first = inside.get(index)
            if first is None or first in hunk_set[side]:
                continue
            other = _heading_counterpart(hunks, side, first)
            for target, at in ((side, first), (1 - side, other)):
                if at not in hunk_set[target]:
                    hunk_set[target].add(at)
                    changed[target].append(at)
    changed = (sorted(hunk_set[0]), sorted(hunk_set[1]))
    rows = ([], [])
    for side in (0, 1):
        for index in changed[side]:
            found = role(side, index)
            if found is not None:
                rows[side].append((index, found))
    pairs, paired_old, paired_new = [], set(), set()

    def pair_rows(old_rows, new_rows, heading_only):
        """2つの並びを、比べる文字が同じ行どうしで順を保って組にする（見出しを含む組だけを残す）。heading_only なら見出しの行だけ。
        相手の側に同じ文字の行がない行は外す（本文の行は、相手の側に同じ文字の見出しがあるときだけ残す。組にする並びを短くする）。"""
        both = [old_rows, new_rows]
        if heading_only:
            both = [[(i, r) for i, r in side_rows if r[0] == "heading"] for side_rows in both]
        heading_keys = [{r[2] for _, r in side_rows if r[0] == "heading"} for side_rows in both]
        all_keys = [{r[2] for _, r in side_rows} for side_rows in both]
        for side in (0, 1):
            other = 1 - side
            both[side] = [(i, r) for i, r in both[side]
                          if r[2] in (all_keys[other] if r[0] == "heading" else heading_keys[other])]
        found = []
        matcher = difflib.SequenceMatcher(None, [r[2] for _, r in both[0]], [r[2] for _, r in both[1]], autojunk=False)
        for a, b, size in matcher.get_matching_blocks():
            for k in range(size):
                (i, old), (j, new) = both[0][a + k], both[1][b + k]
                if "heading" in (old[0], new[0]):
                    found.append((i, old, j, new))
        return found

    def take(found):
        for i, old, j, new in found:
            pairs.append((i, old, j, new))
            paired_old.add(i)
            paired_new.add(j)

    def between_pairs(heading_only):
        """すでにある組の間ごとに、組になっていない行を組にする（組どうしが交差しないようにする）。"""
        bounds = sorted((i, j) for i, _, j, _ in pairs)
        bounds = [(-1, -1)] + bounds + [(len(sides.lines[0]), len(sides.lines[1]))]
        rest = ([(i, r) for i, r in rows[0] if i not in paired_old], [(j, r) for j, r in rows[1] if j not in paired_new])
        at_old = at_new = 0
        found = []
        for (_, _), (hi_i, hi_j) in zip(bounds, bounds[1:]):
            seg_old, seg_new = [], []
            while at_old < len(rest[0]) and rest[0][at_old][0] < hi_i:
                seg_old.append(rest[0][at_old])
                at_old += 1
            while at_new < len(rest[1]) and rest[1][at_new][0] < hi_j:
                seg_new.append(rest[1][at_new])
                at_new += 1
            if seg_old and seg_new:
                found.extend(pair_rows(seg_old, seg_new, heading_only))
        take(found)

    # 見出しどうしの組を先に作る（相手の側に同じ文字の太字の行と見出しがあれば、見出しと組にして段の変化を見る）。
    # 同じ hunk の中の見出しどうし、文書の中の見出しどうし、残った行（本文の行や太字の行と見出し）の順に組にする
    found = []
    row_at = ([i for i, _ in rows[0]], [j for j, _ in rows[1]])
    for hunk in hunks:
        if hunk["tag"] != "replace":
            continue
        hunk_old = rows[0][bisect_left(row_at[0], hunk["old_start"] - 1):bisect_left(row_at[0], hunk["old_end"])]
        hunk_new = rows[1][bisect_left(row_at[1], hunk["new_start"] - 1):bisect_left(row_at[1], hunk["new_end"])]
        if hunk_old and hunk_new:
            found.extend(pair_rows(hunk_old, hunk_new, True))
    take(found)
    between_pairs(True)
    between_pairs(False)
    # 同じ置き換えの hunk の中で組にならなかった見出しは、両側の数が同じなら順に組にする（段と文字を一緒に変えた見出し。
    # 文字の変化は語の候補と全文差分に出る）。文字が似ていないときは、hunk の中の行が両側とも見出しと空行だけで、
    # 次の空行でない行が両側とも変わっていない（節の本文を変えていない）、文書の中で何番目の見出しかが両側で同じ組だけにする
    # （行の対応がずれて別の節の見出しどうしが同じ hunk に入ったときや、節の中身ごと書き換えたときは組にしない）
    ordinal = ({at: n for n, at in enumerate(sorted(old_heads))}, {at: n for n, at in enumerate(sorted(new_heads))})

    def local_heading_hunk(hunk):
        for side, lo, hi in ((0, hunk["old_start"] - 1, hunk["old_end"]), (1, hunk["new_start"] - 1, hunk["new_end"])):
            lines, inside = sides.lines[side], (old_inside if side == 0 else new_inside)
            if not all(_is_blank(lines[at]) or at in inside for at in range(lo, hi)):
                return False
            after = hi
            while after < len(lines) and _is_blank(lines[after]):
                after += 1
            if after < len(lines) and after in hunk_set[side]:
                return False
        return True

    for hunk in hunks:
        if hunk["tag"] != "replace":
            continue
        headings_only = local_heading_hunk(hunk)
        rest_old = [(i, role(0, i)) for i in range(hunk["old_start"] - 1, hunk["old_end"]) if i not in paired_old]
        rest_new = [(j, role(1, j)) for j in range(hunk["new_start"] - 1, hunk["new_end"]) if j not in paired_new]
        rest_old = [(i, r) for i, r in rest_old if r is not None and r[0] == "heading"]
        rest_new = [(j, r) for j, r in rest_new if r is not None and r[0] == "heading"]
        if rest_old and len(rest_old) == len(rest_new):
            for (i, old), (j, new) in zip(rest_old, rest_new):
                if ((headings_only and ordinal[0][i] == ordinal[1][j])
                        or difflib.SequenceMatcher(None, old[2], new[2], autojunk=False).ratio() >= 0.5):
                    pairs.append((i, old, j, new))
    groups = OrderedDict((("bold", []), ("body", []), ("to_body", []), ("level", [])))
    for i, old, j, new in sorted(pairs, key=lambda pair: pair[0]):
        if old[0] == "heading" and new[0] == "heading":
            if old[1] != new[1]:
                groups["level"].append((i, j, old[1], new[1]))
        elif new[0] == "heading":
            groups[old[0]].append((i, j, None, None))
        else:
            groups["to_body"].append((i, j, None, None))
    labels = {"bold": "太字の行を見出しにした", "body": "本文の行を見出しにした", "to_body": "見出しを本文の行にした",
              "level": "見出しの段を変えた"}
    for name, items in groups.items():
        if not items:
            continue
        shown = []
        for i, j, old_level, new_level in items[:_HEADING_SHOWN]:
            old_text, new_text = _heading_shown(sides.lines[0][i]), _heading_shown(sides.lines[1][j])
            if name == "level":
                shown.append("元{}行目 段{}「{}」→ 後{}行目 段{}「{}」".format(i + 1, old_level, old_text, j + 1, new_level, new_text))
            else:
                old_desc, new_desc = "元{}行目「{}」".format(i + 1, old_text), "後{}行目「{}」".format(j + 1, new_text)
                if old_text == new_text:
                    # 文字の行は同じで、setext の下線だけを足したか消した。下線の行も挙げる
                    side, at = (0, i) if name == "to_body" else (1, j)
                    inside = old_inside if side == 0 else new_inside
                    last = at
                    while inside.get(last + 1) == at:
                        last += 1
                    if last != at:
                        underline = "と{}行目「{}」".format(last + 1, _heading_shown(sides.lines[side][last]))
                        old_desc, new_desc = (old_desc + underline, new_desc) if side == 0 else (old_desc, new_desc + underline)
                shown.append("{}→ {}".format(old_desc, new_desc))
        if len(items) > _HEADING_SHOWN:
            shown.append("ほか{}か所".format(len(items) - _HEADING_SHOWN))
        out.append("{}（{}）".format(labels[name], "、".join(shown)))
    return out


# ---- 意味が変わる恐れ（v2.0.0）----
# どれも確かめる場所で、意味が変わったという判定ではない。ここに出なかった変化も全文差分には必ず出る。

# 行頭の印（引用の >、箇条書きの印、見出しの #）。match(行, 位置) で位置から当てるので ^ は付けない
_LINE_PREFIX = re.compile(r"(?:[ \t]{0,3}>[ \t]?|[ \t]*(?:[-*+・]|\d+[.)])[ \t]+|[ \t]{0,3}#{1,6}(?:[ \t]+|$)"
                          # 「(1)」「（１）」「1）」の番号（diff の詰め）。後ろの空白はなくてもよい
                          r"|[ \t]*(?:[(（]\d{1,9}[)）]|\d{1,9}）)[ \t　]*)")
# 意味が変わる恐れの文の区切り。9キーの _SENTENCE_PIECE は変えず、句点（。！？!?）のほか「．」と、空白か行末が続く「.」でも切る
# （「．」の文と英語の文で、1行が1つの文になって判定が長い文字列にかかるのを防ぐ）
_RISK_SENTENCE_PIECE = re.compile(r"(?:[^。！？!?．.\n]|\.(?![ \t]|$))+(?:[。！？!?．]+|\.+(?=[ \t]|$))?[」』）)]*")
# 文に分けない行の種類（中の変化は「変えない箇所」で見る）
_NO_SENTENCE_KINDS = ("code", "frontmatter", "html_block")
# protected_spans の種類 → subkind。引用はブロック（行の quote_depth と、遅延継続の行の kind）で見る。
# リンクの定義と画像のパスも、リンク先（link_destination）と同じく link にする（数値の取り出しでは伏せるので、ここで
# 出さないとどの判定からも漏れる。反証で見つけた例）。画像は ( ) の中のパスだけを見る（代わりの文は本文）
_PROTECTED_SPANS = {"inline_code": "inline_code", "code": "code", "autolink": "url", "bare_url": "url",
                    "link_destination": "link", "reference_definition": "link", "image": "link",
                    "frontmatter": "frontmatter", "html_block": "html", "html_token": "html"}
# 追加と削除の塊は行の種類で決める
_PROTECTED_LINES = {"code": "code", "frontmatter": "frontmatter", "html_block": "html"}
_PROTECTED_LABELS = {"code": "コード", "inline_code": "インラインのコード", "url": "URL", "link": "リンク先",
                     "frontmatter": "先頭の設定", "html": "HTML", "quote": "引用"}
# 同じ塊の中で並べる順
_RISK_ORDER = {"number": 0, "negation": 1, "swap": 2, "sentence_type": 3, "protected": 4, "contrast_reversal": 5,
               "feeling": 6, "certainty": 7, "certainty_review": 8, "quote": 9, "state": 10, "promise": 11, "claim": 12,
               "promise_review": 13, "modality": 14, "modality_review": 15, "choice": 16, "causality": 17,
               "number_qualifier": 18}
# 状態の語の消え（state）と約束の足し（promise）も数える。因果の足し（claim）と、書き手の印のない
# 「〜します」の足し（promise_review。説明や手順の文かもしれない）は数えない。
# --fail-on=meaning-risk が数える kind（数値、否定、主語と目的語の入れ替え、文の種類、引用の印の変化、確度の強まり）。
# 変えない箇所（protected）は意味が変わる恐れの節に出すが数えない。check は資料にない数値（unsupported/number）も数える。
# diff の詰めで足した否定対比の主張の逆転（contrast_reversal）と気持ちの創作（feeling）も数えない（どちらも
# 見直しの候補を出すだけで、点数や合否には使わない）
# 許可の言い方の変化（modality）も数える。能力の言い方の消え（modality_review）は、どの文書の種類でも数えない。
# 選ぶ範囲の入れ替え（choice。どれか一つ ↔ 全部）と、関連から因果への強まり（causality）も数える。
# 数に付いた概数と範囲の印の増減（number_qualifier。約120人 → 120人、100人以上 → 100人）も、数値の恐れとして数える。
FAIL_ON_KINDS = ("number", "negation", "swap", "sentence_type", "citation", "certainty", "state", "promise", "modality",
                 "choice", "causality", "number_qualifier")


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
    コード、先頭の設定、HTML の行は分けない（変えない箇所の検査で見る）。"""
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
        for match in _RISK_SENTENCE_PIECE.finditer(line, offset):
            text = match.group(0).strip()
            if text:
                start = match.start() + (len(match.group(0)) - len(match.group(0).lstrip()))
                sentences.append(_Sentence(text, index + 1, sides.starts[side][index] + start))
    return sentences


def _sentence_pairs(sides, full):
    """意味が変わる恐れの文の組（共通の下ごしらえ）。hunk ごとに
    {"hunk": hunk, "old": [文], "new": [文], "pairs": [(元の文の番号, 後の文の番号)]} を返す。
    replace の塊だけ文を組にする。追加と削除の塊の文は、すべて組にならない文（足した文、消した文）。

    組み方は、中身が同じ文を先に組にしてから、その間の文を同じ窓（直前の組の次から4文、ratio 0.45以上で最大）で
    組にする（全文差分の文の断片と同じ _align）。長い塊の途中に4文以上を足しても、その後ろの文が組になる。

    diff の詰めで2つ足した。
    - 1行対1行の置き換えの塊で、両側が1文ずつなら、似かたによらず組にする（行の対応で同じ場所と分かっているため。
      「動くでしょうか。→ 動きます。」「3日 → 3週間」のような短い文が組にならず、問い・否定・数値を取りこぼしていた）。
    - 空白だけの行しか挟まない hunk の並び（全面書き換えの段落の並び）で、元と後の空白でない行の数が違う（段落を分けたか
      合わせた）ときは、並び全体の文をまとめて組にする（"hunks" に並びの hunk を入れる）。行の対応は空行を順に組にするので、
      段落を1つ分けると後ろの段落がすべて1つずれて別の段落と組になり、数値の誤検知と否定の取りこぼしが出ていた。"""
    groups = []
    hunks = full["hunks"]
    index = 0
    while index < len(hunks):
        run = [hunks[index]]
        while index + len(run) < len(hunks) and _blank_between(sides, run[-1], hunks[index + len(run)]):
            run.append(hunks[index + len(run)])
        if len(run) > 1 and _run_shifted(sides, run):
            old, new = [], []
            for hunk in run:
                old.extend(_line_sentences(sides, 0, hunk["old_start"] - 1, hunk["old_end"]))
                new.extend(_line_sentences(sides, 1, hunk["new_start"] - 1, hunk["new_end"]))
            pairs = []
            if old and new:
                pairs = [(i, j) for i, j, _ in _align([s.text for s in old], [s.text for s in new], similar=True)]
            merged = dict(run[0])
            merged["tag"] = "replace"
            groups.append({"hunk": merged, "hunks": run, "old": old, "new": new, "pairs": pairs})
        else:
            for hunk in run:
                groups.append(_hunk_group(sides, hunk))
        index += len(run)
    return groups


def _hunk_group(sides, hunk):
    old = _line_sentences(sides, 0, hunk["old_start"] - 1, hunk["old_end"])
    new = _line_sentences(sides, 1, hunk["new_start"] - 1, hunk["new_end"])
    pairs = []
    if hunk["tag"] == "replace" and old and new:
        if (len(old) == 1 and len(new) == 1 and hunk["old_end"] == hunk["old_start"]
                and hunk["new_end"] == hunk["new_start"]):
            pairs = [(0, 0)]
        else:
            pairs = [(i, j) for i, j, _ in _align([s.text for s in old], [s.text for s in new], similar=True)]
    return {"hunk": hunk, "old": old, "new": new, "pairs": pairs}


def _blank_between(sides, first, second):
    """2つの hunk の間の、変わっていない行が両側とも空白だけか（間に行がなくても真）。"""
    for side, end_key, start_key in ((0, "old_end", "old_start"), (1, "new_end", "new_start")):
        for line in sides.lines[side][first[end_key]:second[start_key] - 1]:
            if not _is_blank(line):
                return False
    return True


def _run_shifted(sides, run):
    """空白だけの行しか挟まない hunk の並びが、段落を分けたか合わせたためにずれて組になった形か。段落（空行で区切った
    空白でない行のまとまり）の数が元と後で違う hunk があり、置き換えの hunk がほかにもあるときに真。
    1つの hunk の中で行の数だけが違う（段落を空行のない箇条書きにした。反証で見つけた例）なら、段落の数は同じで、
    行の対応は合っているので偽。"""
    differs = False
    replaced = 0
    for hunk in run:
        old, new = _paragraph_count(hunk["old_lines"]), _paragraph_count(hunk["new_lines"])
        if old != new:
            differs = True
        if hunk["tag"] == "replace" and old and new:
            replaced += 1
    return differs and replaced >= 2


def _paragraph_count(lines):
    count, inside = 0, False
    for line in lines:
        blank = _is_blank(line)
        if not blank and not inside:
            count += 1
        inside = not blank
    return count


def _group_index(group, sentence=None, side=1):
    """risk を並べる hunk の番号。まとめた並びの組では、文のある hunk の番号（見つからなければ並びの最初）。"""
    hunks = group.get("hunks")
    if not hunks or sentence is None:
        return group["hunk"]["index"]
    start, end = ("new_start", "new_end") if side == 1 else ("old_start", "old_end")
    for hunk in hunks:
        if hunk[start] <= sentence.line <= hunk[end]:
            return hunk["index"]
    return group["hunk"]["index"]


# ---- 数値（extract_numbers() と ground() も同じ取り出し方を使う）----

# 全角の英数字と記号（U+FF01〜U+FF5E）と全角空白を半角にする。NFKC と同じ結果で、文字数を変えない（位置をそのまま使える）
_HALF_WIDTH = dict((code, code - 0xFEE0) for code in range(0xFF01, 0xFF5F))
_HALF_WIDTH[0x3000] = 0x20
# 算用数字。英字や数字、「_」の直後と、「数字と . か ,」の直後からは始めない（v2、IPv6、x_3、1.2.3 の途中を数にしない）。
# 「，」「．」（半角にしたもの）の直後の数は取る（「3日，5日」「参加者は，30人」。反証で見つけた例）
_ARABIC = re.compile(r"(?<![A-Za-z0-9_])(?<![0-9][.,])[0-9]+(?:[.,][0-9]+)*")
# 数と単位の間の強調の記号（「**3**日」）。読み飛ばして単位を付ける（太字の有無は書式だけの違い。反証で見つけた例）
_EMPHASIS = re.compile(r"\*+")
_THOUSANDS = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?")
_UNITS = ("週間", "時間", "か月", "ヶ月", "カ月", "ヵ月", "TB", "GB", "MB", "KB", "ms", "px", "%",
          "年", "月", "日", "時", "分", "秒", "件", "個", "人", "名", "回", "円", "倍", "割", "度", "点",
          "本", "枚", "台", "社", "週", "歳", "字", "行",
          # diff の詰め: 漢数字の助数詞とそろえる
          "か所", "カ所", "ヶ所", "箇所", "種類", "章", "節", "項", "つ",
          # diff の詰めの直し（反証で見つけた例）: 第3条、第2号、3階
          "条", "号", "階")
# 単位にしない続き（「3階層」「3条件」の「階」「条」は助数詞ではない。diff の詰めの直しで、反証で見つけた例から足した単位のため）
_UNIT_NOT_BEFORE = {"階": "層", "条": "件"}


def _unit_pattern(units):
    return "|".join(re.escape(unit) + ("(?!" + _UNIT_NOT_BEFORE[unit] + ")" if unit in _UNIT_NOT_BEFORE else "")
                    for unit in sorted(units, key=len, reverse=True))


_UNIT = re.compile(_unit_pattern(_UNITS))
# 英字の単位と % は、前に半角か全角の空白が1つあってもよい（「16 GB」「95 %」）
_SPACED_UNIT = re.compile(r"[ \u3000](TB|GB|MB|KB|ms|px|%)(?![A-Za-z])")
# 一覧にない英字の並び（5字まで）は単位として取る（「30s」「100Mbps」「8GiB」）
_LETTER_UNIT = re.compile(r"[A-Za-z]{1,5}(?![A-Za-z])")
# 「2千件」の「千」（千倍した1つの値にする。万と億は限界のまま）
_THOUSAND = re.compile(r"千")
# 月の数え方の表記の違い（か月、ヶ月、カ月、ヵ月）は値を比べるときにそろえる（表記だけの違い）
_SAME_UNIT = {"ヶ月": "か月", "カ月": "か月", "ヵ月": "か月", "カ所": "か所", "ヶ所": "か所", "箇所": "か所"}
# 漢数字は、意味が1つに決まる助数詞が続くときだけ取る
_KANJI_COUNTERS = ("週間", "時間", "か月", "ヶ月", "カ月", "ヵ月",
                   "年", "日", "件", "個", "人", "名", "回", "円", "倍", "割", "本", "枚", "台", "社", "歳",
                   # diff の詰め: 二つ、三か所、三種類、第三章、十二月など
                   "か所", "カ所", "ヶ所", "箇所", "種類", "章", "節", "項", "月", "つ",
                   # diff の詰めの直し（反証で見つけた例）: 第三条、第二号、三階、三十分（「十分」は _KANJI_EXCLUDED で除く）
                   "条", "号", "階", "分",
                   # 十時、十二時（「一時」は _KANJI_EXCLUDED で除く。「十一時」は除かない）
                   "時")
_KANJI_NUMBER = re.compile("(?<![〇一二三四五六七八九十百千])([〇一二三四五六七八九十百千]+)("
                           + _unit_pattern(_KANJI_COUNTERS) + ")")
_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_UNITS = {"十": 10, "百": 100, "千": 1000}
# 漢数字の直前が漢字なら取らない（「統一」「一般」のような語の中の漢数字）。ただし直前がこの字なら取る（「最大三回」「後二週間」
# 「第三回」と、頻度の「年二回」「月一回」「週三日」「一日三回」）
_KANJI_BEFORE = set("約後計全第毎各残大小長短年月週日")
# 直前がこの2字なら取る（「午前九時」と元号の年。反証で見つけた例: 「午前九時 → 午前9時」「令和七年 → 令和7年」を元にない数値にし、
# 「午前九時 → 午前十時」を見逃していた）。1字の「前」「和」「成」にせず、語で見る
_KANJI_BEFORE_WORDS = frozenset(("午前", "令和", "平成", "昭和", "大正", "明治"))
# 時刻を言う語（朝九時、夜十時、夕方五時、毎朝八時、深夜一時）。このあとの漢数字は、助数詞が「時」のときだけ取る（「夜一人で」の
# 人数は今までどおり取らない。反証で見つけた例: 「朝九時 → 朝9時」「深夜一時 → 深夜1時」を元にない数値にし、「朝九時 → 朝十時」を
# 見逃していた）。「一時」は、このあと（と「午前」「午後」と漢数字）のときだけ時刻として取る（_kanji_excluded）
_TIME_OF_DAY_WORDS = frozenset(("午前", "午後", "深夜", "未明", "早朝", "夕方", "毎朝", "今朝", "明朝", "毎晩", "今晩",
                                "今夜", "毎夜", "夜中"))
_TIME_OF_DAY_CHARS = frozenset("朝夜晩昼")
# 時刻の「一時」のすぐあとに続いてよい字（一時十分、一時半、一時頃、一時過ぎ。「一時的」「一時金」の「一時」は時刻にしない）
_ICHIJI_HOUR_NEXT = frozenset("〇一二三四五六七八九十百半頃過前")
_KANJI = re.compile(r"[一-龥々〆ヵヶ]")
# 期間の語のあとの、同じ期間の漢数字の「一日」「一年」「一か月」「一週間」（今日一日、本日一日、去年一年、今週一週間）は、その
# 期間の全体を言い、数量を主張しない。前に漢字のない「日一日と」「年一年と」（日ごとに、年ごとに）も同じ。どちらも数量を主張しない
# 「一つ」と同じ weak の値として取る（_drop_weak が、相手の側に同じ単位の値がないときだけ比べから外す。反証で見つけた例:
# 頻度の年・月・週・日のあとの漢数字を取るようにしたため、「今日一日 → 今日は」「日一日と → 日ごとに」が消えた数値になった）。
# 値が1のときだけ（「今年二年目」「今月三日」は数）。「毎年一年分」の「毎年」はこの語に入れない（数）。1日しかない日（当日、前日、
# 翌日、初日、元日、日曜日などの「曜日」）のあとの「一日」も同じ（反証で見つけた例: 「当日一日限り → 当日のみ」）。「休日一日」
# 「平日一日」は「休日のうち一日」とも読めるので入れない。
# 算用数字の「1日」「1年」（今日1日、去年1年）は、いつも数として取る。1回目の直しでは取らないようにしたが、「本日1日は → 本日は
# 1日」のように助詞を足しただけの推敲が片側だけの値になり、「今日1日 → 今日から数日」を見逃した（反証で見つけた例）。漢数字の
# 「今日一日」を weak の値として取るので、「今日一日 → 今日1日」は値が同じで候補にならない
_WHOLE_PERIOD_WORDS = frozenset(("今日", "本日", "昨日", "明日", "終日", "当日", "前日", "翌日", "初日", "元日", "曜日",
                                 "今年", "去年", "昨年", "来年", "今月", "先月", "来月", "今週", "先週", "来週"))
_SAME_PERIOD = {"日": ("日",), "年": ("年",), "月": ("月", "か月", "ヶ月", "カ月", "ヵ月"), "週": ("週間",)}
# 直前が、漢数字に続いた助数詞（十時三十分、一時間三十分、二週間三日）なら取る（日付と時刻、時間の2つ目の数）。年・月・日は
# _KANJI_BEFORE にある。どれも、漢数字を算用数字にしただけの書き換えを元にない数値にし、漢数字どうしの値の変化（年二回 →
# 年一回、十月十三日 → 十月十五日）を見逃していた（反証で見つけた例。コーパス、誤検出の組、must・keep で、正しい推敲への新しい
# 候補が増えないことを測って入れた）
# 「人」「名」「回」「件」「個」「枚」は、反証で見つけた例（「一人一回 → 1人1回」「一回三十分 → 1回30分」を元にない数値にし、
# 「一人一回 → 一人三回」「一件三百円 → 一件五百円」を見逃していた）で足した。「一枚一枚」の2つ目も値として取るが、同じ値が推敲後の
# 文書にあれば消えた数値にはならない（コーパス、誤検出の組、must・keep で、正しい推敲への新しい候補が増えないことを測って入れた）
_KANJI_CHAIN = re.compile("[〇一二三四五六七八九十百千]+(?:時間|週間|時|分|人|名|回|件|個|枚)$")
# 「十分」の直前の、漢数字に続いた「時」（十時十分）と、「時間」「人」「名」「回」「件」「個」「枚」「日」（一時間十分、一人十分、
# 一日十分）と「毎日」（毎日十分）。反証で見つけた例
_KANJI_HOUR_BEFORE = re.compile("[〇一二三四五六七八九十百千]+(?:時|(時間|人|名|回|件|個|枚|日))$|(毎日)$")
# 「時間」「人」などのあとの「十分」は、時間の量に続く字が続くときだけ取る（「一時間十分かかった」「一人十分とする」「一時間十分の
# 遅れ」）。「七時間十分眠れば」「八時間十分とる」「二時間十分に眠った」「一回十分です」の「十分」（じゅうぶん）は取らない
# （反証で見つけた例。1回目の直しでは に・な・だ・で が続くときだけ除いたので、「七時間十分眠れば」を時間にした）
_JIPPUN_AFTER = ("の", "、", "。", "，", "．", ",", ".", ")", "）", "」", "』", "\n", "ほど", "くらい", "ぐらい", "程度",
                 "前", "後", "以", "未満", "まで", "から", "かか", "を", "も", "が", "は", "強", "弱", "余", "ずつ", "ごと",
                 "おき", "とす", "とし", "だけ")
# 「で」も時間の量に続く字（一人十分で行う、毎日十分で終える）。ただし「十分です」「十分できる」「十分でしょう」はじゅうぶん
# （反証で見つけた例）
_JIPPUN_DE = "で"
_JIPPUN_DE_NOT = ("です", "でき", "でし")
# 前に漢数字も時刻を言う語もない「一時」（一時的に、の意味にも読める）のあとの「十分」は、時刻に続く字が続くときだけ取る
# （「受付は一時十分まで → 一時まで」を見逃さない。「景気は一時十分に回復した」の「十分に」は取らない。反証で見つけた例）
_ICHIJI_JIPPUN_AFTER = ("まで", "から", "前", "後", "過ぎ", "すぎ", "ごろ", "頃", "以", "。", ")", "）", "」")
_KANJI_CHAIN_REACH = 12         # 直前を見る字数（「千九百九十九時間」のような長い漢数字と助数詞が収まる）
# 漢数字を含むが数ではない語。「十分」は、直前が漢数字でなく「十分間」でもないときだけ除く（「三十分」「十分間」は時間。
# 「十分に確かめた」「数十分」は数にしない。反証で見つけた例。正規表現の中で後読みにすると遅くなるので _kanji_excluded で見る）
_KANJI_EXCLUDED = re.compile(r"一時(?!間)|一度|一部|一方|一般|一緒|一切|一応|一番|一定|一致|一意|一括|一本化|一日中|一年中|一日も|"
                             r"一人ひとり|一人一人|一回り|一枚岩|十分|十人十色|万一|四六時中")
_KANJI_NUMERALS = frozenset("〇一二三四五六七八九十百千")
# 漢数字の「分」「条」で、数量を言わないことのある慣用句（反証で見つけた例）。正規表現の後読みや先読みにすると、まとめた
# 漢数字の正規表現が遅くなる（48組で約2%）ので、取った語のあとの字を _find_numbers の繰り返しの中で見る。
# 1回目の直しでは取り出しから外したが、同じ形が時間の「二分しか」「二分すぎ」「十二分に縮めた」「五分位（くらい）」にも当たり、
# 算用数字にした推敲の「2分」だけが元にない数値になった（反証で見つけた例）。外さずに取り、数量を主張しない「一つ」と同じ
# weak の印を付ける（_drop_weak が、相手の側に同じ単位の値がないときだけ比べから外す。「二分した → 分かれた」は出さず、
# 「二分しか → 5分しか」は数値が変わった候補）。
# 「分」のあとが分数（三分の一）、率（百分率）、位（四分位）、五分五分、九分九厘
_BUN_NOT_BEFORE = ("の一", "の二", "の三", "の四", "の五", "の六", "の七", "の八", "の九", "の十", "の百", "の千",
                   "率", "位", "五分", "九厘")
# 「二分する」「二分した」「二分され」「二分化」
_NIBUN_NOT_BEFORE = ("し", "す", "さ", "化")
# 「十二分に」「十二分な」（じゅうにぶん）
_JUNIBUN_NOT_BEFORE = ("に", "な")
# 「一条の光」「一条の煙」
_JOU_NOT_BEFORE = ("の光", "の煙")
# 範囲や並べの前の漢数字（三〜五日、三から五日、三、四日、三・四日 の「三」）。助数詞が続かないので _KANJI_NUMBER では取らないが、
# 算用数字の「3〜5日」の「3」と同じく、単位なしの数として取る（漢数字の範囲を算用数字にしただけの書き換えを、元にない数値に
# しない。反証で見つけた例。表記だけの違いは候補にしない）。助数詞の付いた漢数字の直前だけを見る
_KANJI_RANGE_HEAD = re.compile(r"(?<![〇一二三四五六七八九十百千])([〇一二三四五六七八九十百千]+)"
                               r"(?:[ \t]*(?:[~\u301c]|から)[ \t]*|[、・])$")
_KANJI_RANGE_REACH = 16
# 範囲・日付・時刻のまとまりをつなぐ字（数と数の間がこれだけなら、同じまとまり。3〜5日、3から5日、3-5日、2026-10-13、
# 2026/10/13、10:30。反証で見つけた例）。全角の「～」「－」「／」「：」は半角にしてから見る
_NOTATION_JOIN = re.compile(r"[ \t]*(?:[~\u301c]|から)[ \t]*|[-/:\u2010-\u2013\u2212]")
# つなぎの字の種類（_join_kind）。範囲（〜、から）、日付（/、-）、時刻（:）。字がなければ（10時30、2026年10月13日）adjacent
_JOIN_RANGE = re.compile(r"[~\u301c]|から")
# 日付と時刻の単位の並び（範囲・日付・時刻のまとまりの表記の違いを、単位の並びで確かめる。反証で見つけた例）
_DATE_UNITS = ("年", "月", "日")
_TIME_UNITS = ("時", "分", "秒")
# まとまりの中で、単位のある数のすぐあとの単位なしの数が持つ単位（10時30 の 30 は分、10月13 の 13 は日）
_NEXT_UNIT = {"年": "月", "月": "日", "時": "分", "分": "秒"}
# 単位なしの数のあとの空白（3 日、3 s。単位の前の空白だけの違いを表記の違いとみなす。反証で見つけた例）
_NOTATION_SPACE = re.compile(r"[ \t]+")
# 数量を主張しない「一つ」（一つの、一つずつ、もう一つ）。強めた否定の「一つも」と、「どれも順に」の「一つひとつ」「一つ一つ」も
# 数量を主張しない（「一つもらう」の「も」は除く）。「一つも」は、同じ文のあとに打ち消し（ない、なく、なし、ません、ず、ぬ、無）が
# あるときだけ（強めた否定）。「一つもしくは二つ」「一つもって」の「も」は別の語なので、数量を主張する値のまま。
# 算用数字の「1つ」と平仮名の「ひとつ」も、漢数字の「一つ」と同じ扱い（もう1つ、1つの、1つずつ、1つ1つ、1つも〜ない）。
# 前は算用数字の「1つ」を数として数えていたが、「もう1つの利点は → 〜も利点です」「1つずつ → 順に」のような正しい推敲に
# 候補が出たので、書き方で結果が分かれないようにそろえた（測って決めた。「理由がある → もう1つ理由がある」は拾わなくなる）。
# 「一つのみ」は数を限る言い方なので、数量を主張しない値にしない（反証で見つけた例: 「一つのみ → 複数でもかまわない」を
# 見逃していた）
_WEAK_ONE_AFTER = ("ひとつ", "一つ", "1つ")
_WEAK_ONE_BEFORE = "もう"
_WEAK_ONE_REPEATED = ("一つ", "1つ")
_WEAK_ONE_MO = re.compile(r"も(?!ら|しく|って)(?=[^。！？!?\n]*?(?:な[いくかしけ]|ません|ず|ぬ|無))")
# 「一つの」「一つずつ」は、組の相手の文に数を言う語（_QUANTITY_WORDS）が新しく出れば比べに残す（_drop_weak。「一つずつ →
# まとめて」「一つの → 複数の」を見逃さない）。その印（weak の値）
_WEAK_ONE_PAIRED = ("の", "ずつ")
_WEAK_ONE_ONLY = "のみ"
_WEAK_SINGLE = "single"       # 一つの
_WEAK_EACH = "each"           # 一つずつ
# 平仮名の数（ひとつ〜ここのつ、ひとり、ふたり）。小説やエッセイで漢数字を平仮名にした書き換え（一人 → ひとり、1つ → ひとつ）を
# 候補にしないため、値と単位（つ、人）を持つ、数量を主張しない値として取る（_drop_weak が、相手の側に同じ単位の値がないときだけ
# 比べから外す。「ひとつ → ふたつ」「3人 → ひとり」は数が変わった候補）。「ひとつのみ」は数を限る言い方なので数として数える。
# 数でない語（ひとつまみ、ひとつかみ、ひとつぶ、ひとつながり、ひとつき、ひとりでに、ひとりごと、ひとりよがり、やっつける、
# むっつり）は、あとの字（_KANA_NUMBER_NOT_NEXT）で除く（「ひとつきり」は取る）。「いつつ」「ここのつ」は「思いつつ」「いつ
# つくる」「ここのつくり」と分けにくいので、前が漢字・片仮名でなく（平仮名なら助詞の字）、あとが平仮名でないか決まった並び
# （_KANA_NUMBER_NEXT_STRICT）のときだけ取る。「一人ひとり」は除く語（_KANJI_EXCLUDED）で伏せるので取らない。「とお」は
# 「通る」「遠い」と分けられないので取らない。「に」「で」のすぐあとの「いつつ」で、あとが読点・漢字・「も」なら「いる」と
# 「つつ」（家にいつつ、元気でいつつ働く、家にいつつも）とみなして取らない（反証で見つけた例。「箱にいつつ入れる」の数も
# 取らなくなるが、平仮名の数は数量を主張しない値なので、見逃しても比べから外れるだけ）。「ひとり言」の「ひとり」も取らない
# （_KANA_NUMBER_NOT_KANJI_NEXT。あとが漢字の語。反証で見つけた例）
_KANA_NUMBERS = {"ひとつ": ("1", "つ"), "ふたつ": ("2", "つ"), "みっつ": ("3", "つ"), "よっつ": ("4", "つ"),
                 "いつつ": ("5", "つ"), "むっつ": ("6", "つ"), "ななつ": ("7", "つ"), "やっつ": ("8", "つ"),
                 "ここのつ": ("9", "つ"), "ひとり": ("1", "人"), "ふたり": ("2", "人")}
_KANA_NUMBER = re.compile("ここのつ|ひとつ|ふたつ|みっつ|よっつ|いつつ|むっつ|ななつ|やっつ|ひとり|ふたり")
_KANA_NUMBER_NOT_NEXT = re.compile("まみ|かみ|ぶ(?!ん)|ながり|づき|き(?!り)|でに|ごと|よがり|け|り")
_KANA_NUMBER_NEXT_STRICT = ("の", "を", "が", "は", "も", "に", "で", "と", "だ", "め", "ずつ", "しか", "ほど", "まで", "くらい",
                            "ぐらい", "さえ", "こそ", "じゃ", "あ")
_KANA_NUMBER_STRICT = frozenset(("いつつ", "ここのつ"))
_KANA_NUMBER_NOT_KANJI_NEXT = {"ひとり": "言"}
_KANA_NUMBER_BEFORE = frozenset("をがはもにでとのやへ")
_KANA_NUMBER_KATAKANA = re.compile(r"[ァ-ヴー]")
_HIRAGANA_CHAR = re.compile(r"[ぁ-ゖ]")
_KANA_ONLY = "のみ"
# 数を言う語（「一つの」「一つずつ」の相手の文で見る。反証で見つけた例と、それを言い換えた合成の組で決めた）。書き方の違いは
# そろえてから比べる（_QUANTITY_SAME。「複数 → いくつも」「一括 → まとめて」を新しく出た語にしない。反証で見つけた例）。
# 一斉、一気に、いっぺんに、同時、並列、並行、一括、一度に は、どれも「まとめて」とそろえる（「結果はまとめて送る → 結果は
# 一斉に送る」のような同じ組の語どうしの言い換えを、新しく出た語にしない。反証で見つけた例）。
# 「いくつ」は「いくつか」「いくつも」「いくつでも」だけ（「いくつになっても」の年齢は数を言う語にしない。反証で見つけた例）。
# 「すべて」と語の頭の「各」は、相手の文のどこに出ても数える語にはせず、「一つの」の名詞のすぐ前（すべての窓口、各窓口）だけで
# 見る（_QUANTITY_CHANGE_BEFORE。「一つの表にまとめ、行ごとに… → 表にまとめ、各行に…」「関係者各位」「表にすべての項目を」は、
# 「一つの」の名詞を複数にしていない。反証で見つけた例）
_QUANTITY_WORDS = re.compile(r"一斉|一気に|いっぺんに|別々|まとめて|一括|一度に|並列|並行|同時|複数|上限|無制限|いくつ(?=[かもで])")
_QUANTITY_SAME = {"一括": "まとめて", "一度に": "まとめて", "並行": "まとめて", "並列": "まとめて", "同時": "まとめて",
                  "一斉": "まとめて", "一気に": "まとめて", "いっぺんに": "まとめて", "いくつ": "複数"}
# 形ごとに、数の主張が変わったとみなす語（そろえたあとの語）。「一つずつ」は一つずつ処理するのと逆の語、「一つの」は一つで
# あるのと逆の語。「一つの表に整理 → 表にまとめて整理」は同じことを言うので、「まとめて」を「一つの」に数えない（反証で
# 見つけた例）。「一つずつ」の 複数・いくつでも・いくつも と、「一つの」の 別々 は、相手の文のどこに出ても数える語にはせず、
# 「一つずつ」の動詞・「一つの」の名詞のすぐ前だけで見る（_QUANTITY_CHANGE_BEFORE。「一つずつ選ぶ → 複数選ぶ」「一つの
# ファイル → 別々のファイル」は拾い、「ファイルを一つずつ開き、何か所も直す → ファイルを開く。複数の箇所を直す」「一つの部屋で、
# … → 部屋で、…別々の時間に」は数の主張を変えていない。反証で見つけた例）。
# ただし、すぐ前だけで見ると、前に拾えていた形を見逃した（反証で見つけた例）ので、次の2つは今までどおり数える
# （_QUANTITY_CLAUSE_WORDS。_quantity_changed）。(1)「ずつ」「の」のあとに動詞・名詞が取れないとき（質問は一つずつどうぞ →
# いくつでもどうぞ、添付は一つずつにしてください → 複数でもかまいません）は、複数・いくつ・別々 を相手の文のどこに出ても
# 数える。(2) 相手が1つの文で、動詞・名詞の出る節（_head_clauses）に「複数」（一つずつ）か「別々に」（一つの。副詞の形だけ）が
# あれば数える（送れるファイルは複数です、二人は部屋を別々に使う）
_QUANTITY_CLAUSE_WORDS = {_WEAK_EACH: frozenset(("複数",)), _WEAK_SINGLE: frozenset(("別々",))}
_QUANTITY_FOR = {_WEAK_EACH: frozenset(("まとめて",)),
                 _WEAK_SINGLE: frozenset(("複数", "上限", "無制限"))}
# (3) 相手が1つの文で、「一つずつ」の動詞・「一つの」の名詞がその文に出ない（言い換えた）ときも、(1) と同じく、複数・いくつ・
# 別々 を相手の文のどこに出ても数える（質問は一つずつ受け付けます → 質問は複数でも構いません、設定は一つのファイルに書きます →
# 設定は別々の場所に置きます。反証で見つけた例）。ただし、相手の文に数の主張が同じ語（_QUANTITY_KEEP_ANY。打ち消していないもの）が
# あれば、この3つの語は数えない（申請は一つずつ審査します → 申請は順番に見て、複数の担当で確かめます）。「一つずつ」の
# 「複数の〜」「いくつかの〜」は、〜が元の文にない名詞なら数えない（ファイルを一つずつ確認する → ファイルを見て、複数の誤りを
# 探す。_QUANTITY_OTHER_NOUN）。前から数えていた語（_QUANTITY_FOR）は今までどおり数える。「順に」は、すぐ前が漢字の「手順に」
# 「語順に」を除く
_QUANTITY_KEEP_ANY = {_WEAK_SINGLE: re.compile("同じ|同一|単一"),
                      _WEAK_EACH: re.compile("(?<![㐀-䶿一-鿿豈-﫿々〆])順(?:番)?に|個別に|一件ずつ|一つずつ|ひとつずつ")}
_QUANTITY_OTHER_NOUN = re.compile("(?:複数|いくつか|いくつも)の([㐀-䶿一-鿿豈-﫿々〆ァ-ヴーA-Za-z0-9]{1,12})")
# (4) (3) で数える 複数・いくつ・別々 は、元の文の主題（文頭の「〜は」「〜が」。_QUANTITY_TOPIC）と違う主語（名詞＋が・は。
# _QUANTITY_SUBJECT）を持つ節にあれば数えない（申請は一つずつ審査し、何人かの担当者が確かめます → 申請は逐一見て、複数の担当者が
# 確かめます。「複数」は担当者の数で、申請の数の主張は変わっていない。反証で見つけた例）。その節に主題の語が出れば数える（申請は
# 一つずつ審査します → 担当者は複数の申請を見ます）。主語は漢字・片仮名の並びと、そのあとの送り仮名1字まで（誤りが、揺れが）。
# 主題と同じ語の主語（似た質問が）、主語のない節（版ごとに別々の名前を付けます）、送り仮名の途中で切れる主語（問い合わせが）は
# 見分けない（限界）
_QUANTITY_TOPIC = re.compile(r"\s*([^、。はがを]{1,20}?)(?:は|が)")
_QUANTITY_SUBJECT = re.compile("([㐀-䶿一-鿿豈-﫿々〆ァ-ヴーA-Za-z0-9]{1,12}[りれえけげせめみいきしち]?)(?:が|は)")
# 数を言う語の打ち消し（並列にせず、複数に分けない、まとめて受け付けず、並列ではなく、分けることなく）。打ち消した語は数えない
# （「一つずつ → 並列にせず、順に」は数の主張が同じ。反証で見つけた例）。見るのは、数を言う語のあとから、その語がかかる述語の
# 終わりまで（_QUANTITY_SCOPE_END。「複数の窓口で受け付けるので待ちません」「まとめて送って取りこぼしがない」の打ち消しは別の
# 述語のもの。反証で見つけた例）。語のすぐあとの「して」「にして」（並行して、並列にして）は読み飛ばしてから探す。
# 許す言い方（かまいません、問題ない、差し支えない）と、義務や条件の言い方（なければならない、ないといけない、ないと間に合わない、
# ざるを得ない、しかない、ほかない、かもしれない）は打ち消しにしない（_QUANTITY_NOT_NEG。否定の検査が伏せる言い方と同じ向き）。
# 平仮名の動詞（おこなう、まかなう、ともなう、おはなし、みなす、こなす）の「な」と、「少ない」「危ない」なども打ち消しにしない。
# 「上限」は逆で、上限そのものを打ち消したとき（上限はない、上限なし、上限を設けない、上限をなくす、上限を撤廃する）だけ数える
# （_QUANTITY_LIMIT_OFF。「部屋ごとの上限の十人を超えない」の打ち消しは「超える」のもの。反証で見つけた例）。
# 打ち消しの「ず」は _negative_zu で見る（「一つずつ」「必ず」「まず」を打ち消しにしない）
_QUANTITY_CLAUSE_END = re.compile(r"[、。，．,.！？!?\n]")
_QUANTITY_NEG = re.compile(r"(?<!かまわ)(?<!構わ)(?<!問題)(?<!差し支え)(?<!少)ない|なかっ|なし|(?:では|でも|じゃ|で|ことは?)なく"
                           r"|(?<!かまい)(?<!構い)(?<!問題あり)(?<!差し支えあり)ません")
_QUANTITY_LEAD = re.compile(r"(?:に|で)?して(?![もは])")
_QUANTITY_SCOPE_END = re.compile(r"ので(?!き)|のに|(?<!あら)ため|けど|けれど|(?<=[ぁ-ゖ])ても|(?<=[んい])でも"
                                 r"|(?<=[うくぐすつぬぶむるたい])から"
                                 r"|(?<=[いきぎしちびみりっえけげせねべめれ])て(?=[㐀-䶿一-鿿豈-﫿々〆ァ-ヴ])"
                                 r"|(?<=ん)で(?=[㐀-䶿一-鿿豈-﫿々〆ァ-ヴ])")
_QUANTITY_NOT_NEG = re.compile(
    r"なければ(?:なら|なりませ|いけ|だめ)[ぁ-ゖ]{0,4}|なくては(?:なら|なりませ|いけ|だめ)[ぁ-ゖ]{0,4}|ねば(?:なら|なりませ)[ぁ-ゖ]{0,4}"
    r"|ないと(?!し[たてま]|する).*|ざるを(?:得|え)[ぁ-ゖ]{0,4}|かもしれ[ぁ-ゖ]{0,4}|に違い(?:ない|ありません)"
    r"|(?:しか|ほか|ほかは)(?:ない|なかっ|ありません)"
    r"|(?:おこ|まか|とも)な(?=[いうえわっ])|(?<=お)はな(?=[しすさせ])|(?:み|こ)な(?=[しすさせ])")
_QUANTITY_LIMIT_OFF = re.compile(
    r"上限(?:[はがもをの]|について(?:は)?)?(?:特に)?(?:な[いくしかけ]|無[いくし]|ありません"
    r"|(?:設け|定め|決め|置か|置い)[ぁ-ゖ]{0,4}?(?:ない|なかっ|ず|ません)"
    r"|なく[さしすせなっ]|撤廃|廃止|外[さしすせ]|はず[さしすせ]|取り払|取り除|取り外|解除)")
# 1つの文の中で、読点で区切った節。助詞で終わる節（窓口は、部屋で、）は、述語のある次の節と1つにして見る
_QUANTITY_SENTENCE_END = re.compile(r"[。！？!?\n]")
_QUANTITY_CLAUSE_SPLIT = re.compile(r"[、，,]")
_QUANTITY_PARTICLE_END = re.compile(r"(?:[はもがをにでとへや]|には|では|とは|からは|までは)$")
# 「一つの」の名詞、「一つずつ」の動詞（「の」「ずつ」のすぐあとの、漢字・片仮名・英数字の並び）
_QUANTITY_HEAD = re.compile("[" + "㐀-䶿一-鿿豈-﫿々〆" + "ァ-ヴーA-Za-z0-9]{1,12}")
# その名詞・動詞のすぐ前の、数の主張が同じ語（同じ窓口、順に確認）と、変わった語（複数のファイル、まとめて実行）。相手の文で
# 「一つの」の名詞や「一つずつ」の動詞にかかる語だけを見る（別の述語にかかる語（結果はまとめて共有）は、同じ語でも数の主張を
# 変えない。2つの文をまとめた推敲で、元の隣の文の語が「一つの」の名詞に移った「複数のファイル」は、数の主張が変わった形。
# 反証で見つけた例）
_QUANTITY_KEEP_BEFORE = {_WEAK_SINGLE: "(?:同じ|同一の?|単一の?)",
                         _WEAK_EACH: "(?:順に|順番に|個別に|一件ずつ|一つずつ|ひとつずつ)"}
# 「一つの」の名詞のすぐ前の「各」（各窓口）と「〜ごとの」「〜ごとに別の」（機能ごとのファイル、画面ごとに別のファイル）も、
# 数の主張が変わった形（反証で見つけた例。「すべて」を相手の文のどこに出ても数える語から外したので、ここで見る）。「別の」
# （別のファイル）は数の主張を変えていない。「一つずつ」の動詞のすぐ前の「複数」「複数件」「複数の〜を」「いくつでも」「いくつも」
# （複数選ぶ、複数件受け付ける、いくつでも開ける）も変わった形（相手の文のどこに出ても数える語から外したので、ここで見る）。
# 「一つずつ」の語と動詞のあいだの目的語（まとめてファイルを確認）は挟んでよい（同じ組の語をそろえたので、元の文の別の節に
# 「同時に」があると、相手の文のどこかの語では見分けられない。測って足した）。「複数でも」（候補は複数でも選べる）も変わった形
# （反証で見つけた例）。「一つの」の名詞のすぐあとの「を・は・が・も別々」（窓口を別々にする）は _quantity_changed で見る
_QUANTITY_CHANGE_BEFORE = {_WEAK_SINGLE: "(?:(?:複数|すべて|全て|全部|別々|いくつか|いくつも)の?|各|ごと[にの](?:別々?の)?)",
                           _WEAK_EACH: "(?:まとめて|一括(?:で|して)?|一度に|並列(?:で|に|して)?|並行(?:で|に|して)?|同時(?:に|で)?"
                                       "|一斉に|一気に|いっぺんに|複数(?:件|個|の[^、。]{1,6})?(?:を|でも)?|いくつでも|いくつも)"
                                       "(?:[^、。]{1,8}?を)?"}
# 番号つき箇条書きの番号（行頭の「1.」「2)」、diff の詰めで足した「(1)」「（１）」。引用の中も）。数値ではなく並びの印。
# 隣り合う2つの [ \t]* が同じ空白を取り合う形にすると、伏せて空白だけになった長い行で2乗の時間になる（反証で見つけた例）
_LIST_NUMBER = re.compile(r"^[ \t]*(?:>[ \t]*)*(?:[0-9]{1,9}[.)](?=[ \t]|$)|\([0-9]{1,9}\))", re.M)
# 数値を取り出す前に同じ長さの空白で伏せる protected_spans の種類（コードと URL の数は変えない箇所の検査に任せる）。
# はじめの一覧（code、inline_code、autolink、bare_url、link_destination、frontmatter、html_block）に、
# HTML のタグ（html_token）とリンクの定義（reference_definition）を足した。画像は ( ) の中のパスだけを伏せる
_NUMBER_MASKED = ("code", "inline_code", "autolink", "bare_url", "link_destination", "frontmatter", "html_block",
                  "html_token", "reference_definition", "image")


def _image_path_start(text, left, right):
    """画像の protected_spans（![代わりの文](パス)）の、パスの始まりの位置。パスがなければ right。"""
    middle = text.find("](", left, right)
    return right if middle < 0 else middle + 2


class _Number(tuple):
    """取り出した数値1つ。start と end は文書の中の位置、key は比べるときの (数, 単位)。

    cluster は範囲・日付・時刻のまとまり（3〜5日、3日から5日、2026-10-13、2026年10月13日、10:30、10時30分。数と数の間が
    なにもないか、〜・から・-・/・: だけの並び）の数の (数, 単位) の並び（2つ以上のときだけ。ほかは None）。
    notation は単位なしの数の書き方の手がかり（単位つきの数と、手がかりのない単位なしの数は None）。(まとまり, 続く字, 形) の組で、
    まとまりは cluster の中の単位なしの数の値の並び（まとまりがなければ ()）、続く字は数のあとの空白に続く字（3 日 の「日」から
    8字まで。空白がなければ ""）、形はまとまりの (数と数の間のつなぎの字の種類の並び, 単位の並び, この数の位置)（まとまりがなければ None。
    _notation_match が単位を確かめるのに使う。反証で見つけた例）。weak は数量を主張しない「一つ」。"""
    __slots__ = ()

    def __new__(cls, start, end, value, unit, notation=None, weak=False, cluster=None):
        return tuple.__new__(cls, (start, end, value, unit, notation, weak, cluster))

    start = property(lambda self: self[0])
    end = property(lambda self: self[1])
    value = property(lambda self: self[2])
    unit = property(lambda self: self[3])
    key = property(lambda self: (self[2], self[3]))
    notation = property(lambda self: self[4])
    weak = property(lambda self: self[5])
    cluster = property(lambda self: self[6])


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


def _find_numbers(text, analysis, masked_kinds=_NUMBER_MASKED, unit_pattern=_UNIT):
    """数値の取り出し方で、文書の中の数値を位置の順に返す（_Number の並び）。

    英字が続く数（3D、5G、30s、8GiB）は、一覧の単位が続かなければ単位なしの数として取る（反証で見つけた例）。
    数と単位の間の強調の記号（**）は読み飛ばす。masked_kinds は伏せる protected_spans の種類（() なら伏せない）。"""
    masked = _number_mask(text, analysis, masked_kinds)
    found = []
    taken = []      # 算用数字と「千」で取った範囲（「2千件」の「千件」を漢数字としてもう一度取らない）
    for match in _ARABIC.finditer(masked):
        digits = match.group(0)
        after = match.end()
        thousand = _THOUSAND.match(masked, after) if "," not in digits and "." not in digits else None
        if thousand is not None:
            after = thousand.end()
        unit = unit_pattern.match(masked, after)
        if unit is None:
            emphasis = _EMPHASIS.match(masked, after)
            if emphasis is not None:
                unit = unit_pattern.match(masked, emphasis.end())
        if unit is None and thousand is None:
            unit = _SPACED_UNIT.match(masked, after)
        if unit is None and thousand is None:
            unit = _LETTER_UNIT.match(masked, after)
        unit_text = (unit.group(unit.lastindex) if unit.lastindex else unit.group(0)) if unit else ""
        follow = unit.end() if unit else after
        if thousand is not None:
            taken.append((match.start(), follow))
            found.append(_Number(match.start(), follow, str(int(digits) * 1000), _SAME_UNIT.get(unit_text, unit_text)))
            continue
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
    kanji_text = _KANJI_EXCLUDED.sub(_kanji_excluded, masked)
    for match in _KANJI_NUMBER.finditer(kanji_text):
        if not _kanji_before_ok(kanji_text, match.start()) and not (
                match.group(2) == "時" and _hour_word_before(kanji_text, match.start())):
            continue
        if any(left <= match.start() < right for left, right in taken):
            continue
        value = _kanji_value(match.group(1))
        if value is None:
            continue
        counter = match.group(2)
        # 今日一日、去年一年、日一日と（期間の全体を言う。反証で見つけた例）は、数量を主張しない値として取る
        idiom = value == 1 and _whole_period(kanji_text, match.start(), counter)
        if counter == "分":
            word = match.group(0)
            # 分数、率、四分位、二分する、十二分に、五分五分、九分九厘（反証で見つけた例）。数量を主張しない値として取る
            # （反証で見つけた例）
            idiom = (kanji_text.startswith(_BUN_NOT_BEFORE, match.end())
                     or (word == "二分" and kanji_text.startswith(_NIBUN_NOT_BEFORE, match.end()))
                     or (word == "十二分" and kanji_text.startswith(_JUNIBUN_NOT_BEFORE, match.end()))
                     or (word == "五分" and kanji_text.endswith("五分", 0, match.start())))
        elif counter == "条":
            idiom = kanji_text.startswith(_JOU_NOT_BEFORE, match.end())     # 一条の光
        head = _KANJI_RANGE_HEAD.search(kanji_text, max(0, match.start() - _KANJI_RANGE_REACH), match.start())
        if head is not None and _kanji_head_ok(kanji_text, head, taken, found):
            # 「三〜五日」「三から五日」「三、四日」の前の漢数字（反証で見つけた例）
            found.append(_Number(head.start(1), head.end(1), str(_kanji_value(head.group(1))), ""))
        found.append(_Number(match.start(), match.end(), str(value), _SAME_UNIT.get(counter, counter), None, idiom))
    for match in _KANA_NUMBER.finditer(kanji_text):
        if _kana_number_ok(kanji_text, match):
            value, unit = _KANA_NUMBERS[match.group(0)]
            weak = not kanji_text.startswith(_KANA_ONLY, match.end())
            found.append(_Number(match.start(), match.end(), value, unit, None, weak))
    found.sort(key=lambda number: (number.start, number.end))
    return _with_notation(masked, found)


def _kana_number_ok(text, match):
    """_KANA_NUMBER に当たった平仮名の数を、前後の字で数として取るか（_KANA_NUMBERS の前の注記）。"""
    word, end = match.group(0), match.end()
    strict = word in _KANA_NUMBER_STRICT
    if strict and match.start():
        before = text[match.start() - 1]
        if _KANJI.match(before) or _KANA_NUMBER_KATAKANA.match(before) or (
                _HIRAGANA_CHAR.match(before) and before not in _KANA_NUMBER_BEFORE):
            return False
    if word == "いつつ" and match.start() and text[match.start() - 1] in "にで" and (
            end == len(text) or text[end] == "も" or not _HIRAGANA_CHAR.match(text[end])):
        return False      # 家にいつつ、元気でいつつ働く（いる + つつ）
    if end < len(text) and text[end] == _KANA_NUMBER_NOT_KANJI_NEXT.get(word):
        return False      # ひとり言
    if end == len(text) or not _HIRAGANA_CHAR.match(text[end]):
        return True
    if _KANA_NUMBER_NOT_NEXT.match(text, end) is not None:
        return False
    return not strict or text.startswith(_KANA_NUMBER_NEXT_STRICT, end)


def _kanji_head_ok(kanji_text, head, taken, found):
    """_KANJI_RANGE_HEAD に当たった、範囲や並べの前の漢数字を数として取るか。直前の字は、助数詞の付いた漢数字と同じ決まり
    （直前が漢字なら取らない。ただし _KANJI_BEFORE の字なら取る）。算用数字と「千」で取った範囲と、取った漢数字に重なれば
    取らない。読めない並び（二三）は取らない。"""
    start = head.start(1)
    if not _kanji_before_ok(kanji_text, start):
        return False
    if any(left <= start < right for left, right in taken):
        return False
    if any(number.start <= start < number.end for number in found):
        return False
    return _kanji_value(head.group(1)) is not None


def _kanji_before_ok(kanji_text, start):
    """kanji_text の start から始まる漢数字を、直前の字で数として取るか。直前が漢字でないか、_KANJI_BEFORE の字か、
    直前の2字が _KANJI_BEFORE_WORDS の語か、漢数字に続いた助数詞（_KANJI_CHAIN）なら取る。"""
    before = kanji_text[start - 1] if start else ""
    if not before or not _KANJI.match(before) or before in _KANJI_BEFORE:
        return True
    if kanji_text[max(0, start - 2):start] in _KANJI_BEFORE_WORDS:
        return True
    return _KANJI_CHAIN.search(kanji_text, max(0, start - _KANJI_CHAIN_REACH), start) is not None


def _whole_period(kanji_text, start, counter):
    """start から始まる漢数字（値が1）が、期間の語のあとの同じ期間の数（今日一日、去年一年、今週一週間）か、前に漢字のない
    「日一日」「年一年」（日一日と、年一年と）なら真。"""
    if not start or counter not in _SAME_PERIOD.get(kanji_text[start - 1], ()):
        return False
    if kanji_text[max(0, start - 2):start] in _WHOLE_PERIOD_WORDS:
        return True
    return counter in ("日", "年") and (start < 2 or not _KANJI.match(kanji_text[start - 2]))


def _kanji_excluded(match):
    """_KANJI_EXCLUDED に当たった語を同じ長さの「＃」にする。「十分」は、直前が漢数字（三十分）か、あとが「間」（十分間）なら残す。
    ただし「十分間に合う」（十分 間に合う）の「間」は十分間にしない（反証で見つけた例）。"""
    text = match.group(0)
    if text == "十分":
        start = match.start()
        if (start and match.string[start - 1] in _KANJI_NUMERALS) or (match.string.startswith("間", match.end())
                                                                       and not match.string.startswith("間に合", match.end())):
            return text
        # 十時十分、一時間十分、一人十分（漢数字に続いた「時」「時間」「人」などのあと。反証で見つけた例）。「時」は、前に漢数字のない
        # 「一時」（一時的に）を除く（「一時」を数にしない決まりとそろえる。「景気は一時十分に回復した」）。「時間」「人」などのあとは、
        # 時間の量に続く字が続くときだけ（_JIPPUN_AFTER）
        hour = _KANJI_HOUR_BEFORE.search(match.string, max(0, start - _KANJI_CHAIN_REACH), start)
        if hour is not None:
            end = match.end()
            if hour.group(1) is None and hour.group(2) is None:
                # 「時」のあと。前に漢数字も時刻を言う語もない「一時」は、時刻に続く字が続くときだけ
                if (hour.group(0) != "一時" or _hour_word_before(match.string, hour.start())
                        or match.string.startswith(_ICHIJI_JIPPUN_AFTER, end)):
                    return text
            elif (end == len(match.string) or match.string.startswith(_JIPPUN_AFTER, end)
                  or (match.string.startswith(_JIPPUN_DE, end) and not match.string.startswith(_JIPPUN_DE_NOT, end))):
                return text
    if text == "一時" and match.start() and (
            match.string[match.start() - 1] in _KANJI_NUMERALS
            or (_hour_word_before(match.string, match.start())
                and (match.end() == len(match.string) or not _KANJI.match(match.string[match.end()])
                     or match.string[match.end()] in _ICHIJI_HOUR_NEXT))):
        return text       # 十一時、二十一時、午前一時、深夜一時（「一時的」「一時保存」の「一時」ではない）
    return "＃" * len(text)


def _hour_word_before(text, start):
    """text の start の直前が、時刻を言う語（午前、午後、深夜、朝、夜 など。_TIME_OF_DAY_WORDS と _TIME_OF_DAY_CHARS）なら真。"""
    return text[max(0, start - 2):start] in _TIME_OF_DAY_WORDS or (start > 0 and text[start - 1] in _TIME_OF_DAY_CHARS)


def _join_kind(between):
    """まとまりの数と数の間の字の種類（"adjacent"、"range"、"colon"、"slash"、"dash"）。"""
    if not between:
        return "adjacent"
    if _JOIN_RANGE.search(between):
        return "range"
    if ":" in between:
        return "colon"
    if "/" in between:
        return "slash"
    return "dash"


def _with_notation(masked, found):
    """数値の並びに、範囲・日付・時刻のまとまり（cluster）、単位なしの数の書き方の手がかり（notation）、数量を主張しない
    「一つ」の印（weak）を付ける。"""
    groups = list(range(len(found)))
    joins = {}
    for index in range(1, len(found)):
        between = masked[found[index - 1].end:found[index].start]
        if "\n" not in between and (not between or _NOTATION_JOIN.fullmatch(between)):
            groups[index] = groups[index - 1]
            joins.setdefault(groups[index], []).append(_join_kind(between))
    members = {}
    for index, number in enumerate(found):
        members.setdefault(groups[index], []).append(number)
    out = []
    for index, number in enumerate(found):
        cluster = members[groups[index]]
        keys = tuple(member.key for member in cluster) if len(cluster) > 1 else None
        notation, weak = None, number.weak
        if not number.unit:
            group = tuple(member.value for member in cluster if not member.unit) if keys else ()
            space = _NOTATION_SPACE.match(masked, number.end)
            follow = masked[space.end():space.end() + 8].split("\n", 1)[0] if space else ""
            if group or follow:
                frame = None
                if group:
                    frame = (tuple(joins.get(groups[index], ())), tuple(member.unit for member in cluster),
                             next(at for at, member in enumerate(cluster) if member is number))
                notation = (group, follow, frame)
        elif number.key == ("1", "つ"):
            if (masked.startswith(_WEAK_ONE_AFTER, number.end) or _WEAK_ONE_MO.match(masked, number.end) is not None
                    or masked[max(0, number.start - 2):number.start] in _WEAK_ONE_REPEATED
                    or masked[max(0, number.start - len(_WEAK_ONE_BEFORE)):number.start] == _WEAK_ONE_BEFORE):
                weak = True
            elif (masked.startswith(_WEAK_ONE_PAIRED, number.end)
                  and not masked.startswith(_WEAK_ONE_ONLY, number.end)):
                weak = _WEAK_EACH if masked.startswith("ずつ", number.end) else _WEAK_SINGLE
        out.append(_Number(number.start, number.end, number.value, number.unit, notation, weak, keys)
                   if notation is not None or weak or keys else number)
    return out


def extract_numbers(text):
    """文の中の数値を取り出す。位置の順に
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
    「10時から設計レビュー、14時からテスト」→「14時から設計レビュー、10時からテスト」を並びの変化にするため（反証で見つけた例）。
    表の行では、直前の字がどのセルでも「|」なので、何列目か（前にある「|」の数）を手がかりにする（反証で見つけた例）。"""
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
    """数値（kind number）。(hunk の番号, 塊の中の順, risk) の並びを返す。

    組になった文で比べる（replaced、added、lost、order）。そのあと、文書全体で後にだけある値と元にだけある値のうち、
    組の文で出していないもの（足した文、消した文の中の値）を、値の集合で added と lost にする。
    replaced に入れた値は added と lost に重ねない。

    「元の文書のどこにもない」「後の文書のどこにもない」は、伏せる前の数値（コードや URL の中も含む）で見る。
    文書全体の比べで出すのは、hunk の行の中にある値だけ（意味が変わる恐れの対象は、全文差分で変わった塊の中だけ）。
    変わっていない行をコードの囲みに入れただけで、その行の値を「消えた数値」にしないため（反証で見つけた例）。

    数量を主張しない「一つ」（一つの、一つずつ、もう一つ）は、単独では元にない数値・消えた数値にしない（反証で見つけた例）。
    組の文の added と lost で、範囲・日付・時刻のまとまりの部品の値は、文書全体ではなく組の相手の文と、そのすぐ前とすぐあとの
    組にならなかった文の中だけで「ある」を見る（_cluster_partners、_unpaired_around。反証で見つけた例）。"""
    out = []
    old_all, new_all = sides.all_keys(0), sides.all_keys(1)
    shown_removed, shown_added = set(), set()
    order = 0
    for group in groups:
        paired_old = set(i for i, _ in group["pairs"])
        paired_new = set(j for _, j in group["pairs"])
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            if old.text == new.text:
                continue
            index = _group_index(group, new)
            old_numbers = _sentence_numbers(sides, 0, old)
            new_numbers = _sentence_numbers(sides, 1, new)
            old_count = Counter(number.key for number in old_numbers)
            new_count = Counter(number.key for number in new_numbers)
            raw_removed, raw_added = old_count - new_count, new_count - old_count
            # 文を2つに分けた・2つを合わせた推敲（組の文のすぐあとに、組にならなかった文が続く）。組の文で消えた値が続く文に
            # あれば（数と単位が同じ）、移しただけとみなして比べから外す。「…30秒のタイムアウトに達し、ゲートウェイが504を返した。」
            # →「…30秒のタイムアウトに達した。ゲートウェイは…504を返した。」で、504 を「変わった数値」にしない（diff の詰めの
            # 組み方で組になった分割の文）。続く文のほかの値は、組の文の値と打ち消さず（表記の違いの打ち消しも
            # しない）、文書全体の比べに回す。別の文の「3」と「3日」を打ち消し合わせて取りこぼしたり、値のない文を示したり
            # しないため（diff の詰めの直し。反証で見つけた例）
            # 続く文に移ったとみなすのは、組の文の反対の側に同じ単位の値が増えて（減って）いない値だけ。「移行は3日で終える。」→
            # 「移行は5日で終える。予備として3日を見込む。」は、3日が続く文にあっても、組の文で3日が5日に変わっている
            # （反証で見つけた例）。ただし続く文のほうが組の相手の文によく似ていれば（文を動かした推敲で、組が1つずれた
            # とき）、今までどおり移しただけとみなす（_moved_keys）
            extra_old = _following_unpaired(sides, 0, group["old"], i, paired_old)
            extra_new = _following_unpaired(sides, 1, group["new"], j, paired_new)
            moved_removed = _moved_keys(extra_new, raw_added, old.text, new.text) if extra_new else None
            moved_added = _moved_keys(extra_old, raw_removed, new.text, old.text) if extra_old else None
            if moved_removed:
                raw_removed -= moved_removed
            if moved_added:
                raw_added -= moved_added
            removed, added = _cancel_notation(raw_removed, raw_added, old_numbers, new_numbers)
            # 表記の違いとして打ち消した値は、文書全体の比べでもう一度出さない
            shown_removed.update(raw_removed - removed)
            shown_added.update(raw_added - added)
            old_text, new_text = old.text, new.text
            if any(number.weak in _QUANTITY_FOR for number in old_numbers) or any(
                    number.weak in _QUANTITY_FOR for number in new_numbers):
                # 2つの文をまとめた・分けた推敲では、組にならなかった隣の文の語も相手の文の語として見る（反証で見つけた例:
                # 「一つずつ確認します。すべての確認が…」→「順に確認し、すべて済んだら…」を、新しく出た「すべて」とみなしていた）。
                # つなぐときは _quantity_text の決まりで
                old_text = _quantity_text(group["old"], i, paired_old, old, old_numbers, new_numbers, sides.texts[1])
                new_text = _quantity_text(group["new"], j, paired_new, new, new_numbers, old_numbers, sides.texts[0])
            removed, added = _drop_weak(removed, added, old_numbers, new_numbers, old_text, new_text,
                                        sides.texts[0], sides.texts[1])
            risk = None
            if removed and added:
                risk = _risk("number", "replaced", old.line, new.line, old.text, new.text,
                             {"removed": _number_texts(sides, 0, old_numbers, removed),
                              "added": _number_texts(sides, 1, new_numbers, added)})
                shown_removed.update(removed)
                shown_added.update(added)
            elif added:
                partners = _cluster_partners(new_numbers, raw_added - added, old_numbers)
                pair_set = (_KeySet(list(old_numbers) + _unpaired_around(sides, 0, group["old"], i, paired_old))
                            if partners else None)
                fresh = Counter(dict((key, count) for key, count in added.items()
                                     if not _present(key, _notation_index(new_numbers),
                                                     pair_set if key in partners else old_all)))
                if fresh:
                    risk = _risk("number", "added", old.line, new.line, old.text, new.text,
                                 {"removed": [], "added": _number_texts(sides, 1, new_numbers, fresh)})
                    shown_added.update(fresh)
            elif removed:
                partners = _cluster_partners(old_numbers, raw_removed - removed, new_numbers)
                pair_set = (_KeySet(list(new_numbers) + _unpaired_around(sides, 1, group["new"], j, paired_new))
                            if partners else None)
                gone = Counter(dict((key, count) for key, count in removed.items()
                                    if not _present(key, _notation_index(old_numbers),
                                                    pair_set if key in partners else new_all)))
                if gone:
                    risk = _risk("number", "lost", old.line, new.line, old.text, new.text,
                                 {"removed": _number_texts(sides, 0, old_numbers, gone), "added": []})
                    shown_removed.update(gone)
            elif (old_count == new_count and not any(numbers for _, numbers in extra_old)
                  and not any(numbers for _, numbers in extra_new)
                  and _order_changed(sides, old, old_numbers, new, new_numbers)):
                # 並びは、値と単位の多重集合がまったく同じときだけ見る（表記の違いだけを打ち消した組は並びに数えない）。
                # どの並びを候補にするかは _order_changed
                risk = _risk("number", "order", old.line, new.line, old.text, new.text,
                             {"old_order": [sides.texts[0][n.start:n.end] for n in old_numbers],
                              "new_order": [sides.texts[1][n.start:n.end] for n in new_numbers]})
            if risk is not None:
                out.append((index, order, risk))
                order += 1
    # 文書全体の比べ（足した文、消した文、組にならなかった文の中の値）
    for side, shown, other, subkind in ((0, shown_removed, new_all, "lost"), (1, shown_added, old_all, "added")):
        found = sides.numbers(side)[0]
        notation = _notation_index(found)
        keys = set(key for key in set(number.key for number in found) - shown if not _present(key, notation, other))
        if not keys:
            continue
        sentence_at, hunk_at = _sentence_finder(sides, side, groups), _hunk_finder(full, side)
        first = OrderedDict()
        for number in found:
            # 数量を主張しない「一つ」は、単独では出さない（反証で見つけた例）
            if number.key in keys and number.key not in first and not number.weak:
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


def _order_changed(sides, old, old_numbers, new, new_numbers):
    """組の文の数値の並びが変わり、数と語の結び付きも変わったか（数値の並びの候補）。

    値の並びが違い、結び付きの手がかり（_number_contexts）も違う組のうち、次のどちらかに当たるものだけを候補にする。
    1. 同じ単位の数どうしの並びが変わった（_unit_orders。「部屋にふたり、廊下に3人 → 部屋に3人、廊下にふたり」）。違う単位の
       数の前後を入れ替えただけの「ひとりで2時間歩いた → 2時間、ひとりで歩いた」は、値も語との結び付きも変わっていない
       （反証で見つけた例）。
    2. 同じ語句に付く値が、元と後で2つ以上の語句について変わった（_number_phrases）。単位の違う数の入れ替え（設計は3日、試験は
       2人 → 設計は2人、試験は3日）と、同じ量の違う単位の入れ替え（準備に2時間、本番に30分 → 準備に30分、本番に2時間）を
       拾うため（1 だけにしたら見逃した。反証で見つけた例）。変わった語句が1つだけの「会議は3回、2時間ずつ行う → 会議は
       2時間ずつ、3回行う」は、同じ語に付く2つの数の語順を変えた言い換えなので数えない。
    3. 1 と 2 に当たらなくても、数量を言う値（数量を主張しない「一つ」などを除く）と、その数の直前の2字の組が入れ替わった
       （_strong_swapped）。言い回しを変えて語句が一致しなくなった単位の違う入れ替え（まず設計に3日、次に試験に5時間 → 設計に
       5時間、試験に3日）を拾うため（反証で見つけた例）。"""
    if [number.key for number in old_numbers] == [number.key for number in new_numbers]:
        return False
    if _number_contexts(sides, 0, old, old_numbers) == _number_contexts(sides, 1, new, new_numbers):
        return False
    if _unit_orders(old_numbers) != _unit_orders(new_numbers):
        return True
    if _strong_swapped(sides.texts[0], old, old_numbers, sides.texts[1], new, new_numbers):
        return True
    for olds, news in zip(_number_phrases(sides, 0, old, old_numbers), _number_phrases(sides, 1, new, new_numbers)):
        if sum(1 for phrase in set(olds) & set(news) if olds[phrase] != news[phrase]) >= 2:
            return True
    return False


# 数のすぐ前の、どの数にも付く修飾語（_lead で飛ばす。長い語から見る）
_LEAD_MODIFIERS = ("合計", "最大", "最小", "最短", "最長", "およそ", "約", "計")


def _lead(text, sentence, number):
    """数 number の直前の2字（文 sentence の中だけ）。文頭か読点の直後なら "^"。数のすぐ前の共通の修飾語（約、計、最大 など。
    _LEAD_MODIFIERS）は飛ばしてから取る（「移行は約2週間、検証で約3日 → 検証は約3日、移行で約2週間」の直前の2字が「は約」
    「で約」になり、語順だけの推敲が入れ替えに見える。反証で見つけた例）。"""
    end = number.start
    for word in _LEAD_MODIFIERS:
        if text.endswith(word, max(sentence.start, end - len(word)), end):
            end -= len(word)
            break
    before = text[max(sentence.start, end - 2):end]
    return "^" if not before or before.endswith(("、", "，", ",")) else before


def _strong_swapped(old_text, old, old_numbers, new_text, new, new_numbers):
    """数量を言う値（weak でない値）と、その数の直前の2字（_lead）の組を元と後で比べ、値の並びが変わり、値の多重集合と直前の
    2字の多重集合はどちらも同じなのに、組の多重集合が違えば真（値と直前の語の結び付きが入れ替わった）。直前が文頭か読点の数は
    組に入れない（「会議は3回、2時間ずつ行う → 会議は2時間ずつ、3回行う」は同じ語に付く2つの数の語順だけの言い換え。入れると
    候補になる。反証で見つけた例）。"""
    olds = [(n.key, _lead(old_text, old, n)) for n in old_numbers if not n.weak]
    news = [(n.key, _lead(new_text, new, n)) for n in new_numbers if not n.weak]
    olds = [pair for pair in olds if pair[1] != "^"]
    news = [pair for pair in news if pair[1] != "^"]
    if Counter(k for k, _ in olds) != Counter(k for k, _ in news):
        return False
    if Counter(c for _, c in olds) != Counter(c for _, c in news):
        return False
    return [k for k, _ in olds] != [k for k, _ in news] and Counter(olds) != Counter(news)


def _unit_orders(numbers):
    """数値の並び（numbers）を、単位ごとの値の並びにした辞書（{単位: [(値, 単位), ...]}）。「部屋にふたり、廊下に3人 →
    部屋に3人、廊下にふたり」（人 の並びが変わった）は違い、「ひとつの鍋で3品 → 3品を、ひとつの鍋で」は同じになる。"""
    out = {}
    for number in numbers:
        out.setdefault(number.unit, []).append(number.key)
    return out


def _number_phrases(sides, side, sentence, numbers):
    """数値の前に付く語句ごとの値（Counter）の辞書を2つ返す。1つ目の語句は節の頭（文頭か読点の直後）からその数の前までの字、
    2つ目は前の数のあと（同じ節に前の数がなければ節の頭）からその数の前までの字（「設計は3日、試験は2人」の 3日 は「設計は」、
    「管理者3人と閲覧者20名」の 20名 は「管理者3人と閲覧者」と「と閲覧者」）。節の頭の数（語句が空）と表の行は見ない。"""
    rows = sides.analyses[side]["lines"]
    if sentence.line - 1 < len(rows) and rows[sentence.line - 1]["kind"] == "table":
        return {}, {}
    text = sentence.text
    clause, near = {}, {}
    previous = 0
    for number in numbers:
        at = number.start - sentence.start
        start = max(text.rfind(mark, 0, at) for mark in "、，,") + 1
        for found, begin in ((clause, start), (near, max(start, previous))):
            phrase = text[begin:at].strip(" \t　")
            if phrase:
                found.setdefault(phrase, Counter())[number.key] += 1
        previous = number.end - sentence.start
    return clause, near


def _cluster_partners(numbers, cancelled, others):
    """組の文の数値（numbers）のうち、範囲・日付・時刻のまとまりの部品として、文書全体ではなく組の相手の文のまわりだけで
    「ある」を見る値の集合（_unpaired_around）。単位なしの数を持つまとまりと、表記の違いとして打ち消した値（cancelled）を含む
    まとまりのうち、値の一部が組の相手の文（others）に残るか打ち消したもの（範囲の片方の端だけを残した）の、すべての値。
    「移行は3〜5日で終える。」→「移行は5日で終える。」で、消えた 3 を文書の別の段落の「予備日は3日」で「ある」とすると、範囲を
    1つの値に縮めた書き換えを見逃す（反証で見つけた例。逆向きの、範囲に広げた書き換えも同じ）。まとまりの値が相手の文に
    1つも残らないとき（範囲を含む文を丸ごと動かした推敲）は、今までどおり文書全体で見る。"""
    partners = set()
    kept = None
    for number in numbers:
        cluster = number.cluster
        if cluster is None or not (number.key in cancelled or (not number.unit and number.notation)):
            continue
        if kept is None:
            kept = set(other.key for other in others)
        if any(key in kept or key in cancelled for key in cluster):
            partners.update(cluster)
    return partners


def _moved_keys(extra, opposite, source, partner):
    """続く文（extra。_following_unpaired の (文, 数値の並び) の並び）の数値のうち、組の文から移った値とみなすものの Counter。

    source は値が消えた（増えた）側の組の文、partner は続く文と同じ側の組の文、opposite は partner の側の増減（Counter）。
    続く文が partner より source に似ていれば（文を動かして組が1つずれた）、その文の値はすべて移した値。そうでなければ、
    opposite に同じ単位の値がない値だけを移した値とする（反証で見つけた例）。"""
    units = set(unit for (_, unit), count in opposite.items() if count > 0)
    moved = Counter()
    pair_ratio = None
    for sentence, numbers in extra:
        if not numbers:
            continue
        if units and any(number.unit in units for number in numbers):
            if pair_ratio is None:
                pair_ratio = _text_ratio(source, partner)
            # ratio の上限（quick_ratio）が組の似かた以下なら、ratio も超えないので求めない（結果は同じ）。長く繰り返しの多い文が
            # 組にならずに続く文書で、ratio が2乗に近い時間になるのを避ける（反証で見つけた例）
            if _ratio_bound(source, sentence.text) > pair_ratio and _text_ratio(source, sentence.text) > pair_ratio:
                moved.update(number.key for number in numbers)
                continue
        moved.update(number.key for number in numbers if number.unit not in units)
    return moved


def _text_ratio(a, b):
    """2つの文の似かた（_pair_similar と同じく、2,000字を超えれば前後の同じ字の数から求める）。"""
    if len(a) > _CHAR_ALIGN_LIMIT or len(b) > _CHAR_ALIGN_LIMIT:
        return _affix_ratio(a, b)
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _ratio_bound(a, b):
    """_text_ratio の上限。2,000字以下なら quick_ratio（字の多重集合の重なり。ratio 以上）。超えれば 1.0（_text_ratio は前後の
    同じ字から求めるので速く、絞らなくてよい）。"""
    if len(a) > _CHAR_ALIGN_LIMIT or len(b) > _CHAR_ALIGN_LIMIT:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).quick_ratio()


def _unpaired_around(sides, side, sentences, index, paired):
    """組の文 sentences[index] のすぐ前とすぐあとに続く、組にならなかった文の数値（前と次の組の文の手前まで）。文をまとめた・
    分けた推敲（「発生日時：…」と「影響：…」を1文にまとめた）では、組にならなかった文の値も組の文の値として見る
    （_cluster_partners。コーパスの blacklist_ai/02_incident_report_sonnet_casual → _bl）。"""
    found = []
    position = index - 1
    while position >= 0 and position not in paired:
        found.extend(_sentence_numbers(sides, side, sentences[position]))
        position -= 1
    position = index + 1
    while position < len(sentences) and position not in paired:
        found.extend(_sentence_numbers(sides, side, sentences[position]))
        position += 1
    return found


def _quantity_text(sentences, index, paired, own, own_numbers, other_numbers, other_doc):
    """「一つの」「一つずつ」の相手の文の語を見るときの、組の文（own）の側の文字列。2つの文をまとめた・分けた推敲では、組の文の
    すぐ前とすぐあとの組にならなかった文もつなぐ（_with_unpaired_text）。ただし、つなぐのは次のときだけ（反証で見つけた例:
    文を分けた推敲の「各行に時刻 → すべての行に時刻」を、ファイルの数の変化にしていた）。
    (a) 自分の側に「一つの」「一つずつ」がある（まとめた推敲で、隣の文にもともとあった語を新しく出た語にしない）。
    (b) 相手の側に「一つずつ」がある（分けた推敲の「ただし並列で動かす」）。
    (c) 相手の側の「一つの」の名詞が、つなぐ隣の文に出る（分けた推敲の「ファイルは複数に分けてよい」）。"""
    joined = _with_unpaired_text(sentences, index, paired)
    if joined == own.text:
        return joined
    if any(number.weak in _QUANTITY_FOR for number in own_numbers):
        return joined
    if any(number.weak == _WEAK_EACH for number in other_numbers):
        return joined
    rest = joined.replace(own.text, "", 1)
    if any(number.weak == _WEAK_SINGLE and _weak_head(other_doc, number) in rest
           for number in other_numbers if _weak_head(other_doc, number)):
        return joined
    return own.text


def _weak_head(doc, number):
    """「一つの」の名詞、「一つずつ」の動詞（doc の中の number のすぐあとの「の」「ずつ」に続く、漢字・片仮名・英数字の並び）。
    なければ ""。"""
    skip = 1 if number.weak == _WEAK_SINGLE else 2
    match = _QUANTITY_HEAD.match(doc, number.end + skip) if doc else None
    return match.group(0) if match else ""


def _quantity_negated(text, position):
    """text の position からの数を言う語の打ち消しがあれば真（_QUANTITY_NEG と打ち消しの「ず」）。見るのは節の終わりまでのうち、
    語がかかる述語の終わり（_QUANTITY_SCOPE_END）まで。義務や条件の言い方と平仮名の動詞の「な」（_QUANTITY_NOT_NEG）、「少ない」
    などの語（_NEGATION_WORDS）は伏せてから探す。"""
    end = _QUANTITY_CLAUSE_END.search(text, position)
    rest = text[position:end.start() if end else len(text)]
    lead = _QUANTITY_LEAD.match(rest)
    stop = _QUANTITY_SCOPE_END.search(rest, lead.end() if lead else 0)
    if stop is not None:
        rest = rest[:stop.start()]
    rest = _QUANTITY_NOT_NEG.sub(lambda match: "＃" * len(match.group(0)), rest)
    rest = _NEGATION_WORDS.sub(lambda match: match.group(0)[:-1] + "＃", rest)
    return _QUANTITY_NEG.search(rest) is not None or _negative_zu(rest)


def _head_clauses(text, head):
    """相手の文 text が1つの文で、「一つの」の名詞か「一つずつ」の動詞（head）が出るなら、head の出る節（読点で区切る。助詞で
    終わる節は次の節も）をつないだ文字列。2つ以上の文（まとめた・分けた推敲でつないだ文）か、head が出なければ None。"""
    body = text.rstrip(" \t\n。！？!?」』）)")
    if head not in body or _QUANTITY_SENTENCE_END.search(body):
        return None
    clauses = _QUANTITY_CLAUSE_SPLIT.split(body)
    picked = []
    for index, clause in enumerate(clauses):
        if head not in clause:
            continue
        picked.append(clause)
        while _QUANTITY_PARTICLE_END.search(clauses[index].strip()) and index + 1 < len(clauses):
            index += 1
            picked.append(clauses[index])
    return "、".join(picked)


def _one_sentence_without(text, head):
    """相手の文 text が1つの文で、「一つの」の名詞か「一つずつ」の動詞（head）が出ないなら真（言い換えた推敲）。"""
    body = text.rstrip(" \t\n。！？!?」』）)")
    return head not in body and not _QUANTITY_SENTENCE_END.search(body)


def _other_subject_masked(own_text, partner_text):
    """partner_text の節（読点で区切る）のうち、own_text の主題（_QUANTITY_TOPIC）と違う主語（_QUANTITY_SUBJECT）を持ち、その主語の
    ほかに主題の語が出ない節（合鍵は各自が別々に持つ。主題は「鍵」）を伏せた文字列。助詞で終わる節（申請は、）は次の節と1つにして
    見る。主題が取れなければ partner_text のまま。"""
    topic = _QUANTITY_TOPIC.match(own_text)
    topic = topic.group(1).strip() if topic else ""
    if not topic:
        return partner_text
    clauses = []
    for clause in _QUANTITY_CLAUSE_SPLIT.split(partner_text):
        if clauses and _QUANTITY_PARTICLE_END.search(clauses[-1].strip()):
            clauses[-1] += "、" + clause      # 「申請は、担当者が複数を見ます」の「申請は」は次の節と1つにして見る
        else:
            clauses.append(clause)
    out = []
    for clause in clauses:
        subject = _QUANTITY_SUBJECT.search(clause)
        if (subject and subject.group(1) not in topic
                and topic not in clause[:subject.start(1)] + "＃" + clause[subject.end(1):]):
            clause = "＃" * len(clause)
        out.append(clause)
    return "、".join(out)


def _quantity_changed(number, doc, own_text, partner_text, partner_words):
    """weak の値 number（「一つの」「一つずつ」）の数の主張が、相手の文（partner_text）で変わったか。
    1. 相手の文で、「一つの」の名詞や「一つずつ」の動詞のすぐ前に数の主張が変わった語（複数のファイル、まとめて実行）があり、
       自分の文にその形がなければ変わった（2つの文をまとめた推敲で、元の隣の文の「複数」が「一つの」の名詞に移った形を見逃さない）。
       同じ文の別の節に 2 の形（返却は同じ窓口で）があっても変わった（反証で見つけた例）。
    2. すぐ前に数の主張が同じ語（同じ窓口、順に確認）があれば変わっていない。
    3. ほかは、相手の文に新しく出た数を言う語（partner_words）が、その形の語（_QUANTITY_FOR）であれば変わった。相手の文が1つの
       文で「一つの」の名詞や「一つずつ」の動詞が出るなら、その語のある節の語だけを見る（「議題を確認し、結果はまとめて共有する」の
       「まとめて」は別の述語にかかる。反証で見つけた例）。文を分けた推敲（ただし並列で動かす）は、つないだ文のどこの語も見る。
    4. 1 のほか、「一つの」の名詞のすぐあとに「を・は・が・も別々」があれば変わった（窓口を別々にする）。3 のほか、相手が1つの
       文で名詞・動詞の節に「複数」（一つずつ）か「別々に」（一つの）があれば変わった。名詞・動詞が取れないときは、複数・いくつ・
       別々 も相手の文のどこに出ても数える（_QUANTITY_CLAUSE_WORDS の前の注記）。
    5. 相手が1つの文で、名詞・動詞がその文に出ないときは、3 の語のほか、複数・いくつ・別々 も相手の文のどこに出ても数える。
       ただし、数の主張が同じ語（順番に、同じ）がその文にあるときと、「一つずつ」の「複数の〜」の〜が元の文にない名詞のときは、
       この3つの語を数えない（_QUANTITY_KEEP_ANY の前の注記）。元の文の主題と違う主語の節にある語も数えない
       （_QUANTITY_TOPIC の前の注記）。
    どれも打ち消した語は見ない。"""
    words = _QUANTITY_FOR.get(number.weak)
    if words is None:
        return False
    head = _weak_head(doc, number)
    if head:
        for match in re.finditer(_QUANTITY_CHANGE_BEFORE[number.weak] + re.escape(head), partner_text):
            if match.group(0) not in own_text and not _quantity_negated(partner_text, match.end()):
                return True
        if number.weak == _WEAK_SINGLE:
            for match in re.finditer(re.escape(head) + "(?:を|は|が|も)?別々", partner_text):
                if match.group(0) not in own_text and not _quantity_negated(partner_text, match.end()):
                    return True
        for match in re.finditer(_QUANTITY_KEEP_BEFORE[number.weak] + re.escape(head), partner_text):
            if not _quantity_negated(partner_text, match.end()):
                return False
        scope = _head_clauses(partner_text, head)
        if scope is None and _one_sentence_without(partner_text, head):
            if partner_words & words:
                return True
            if any(not _quantity_negated(partner_text, match.end())
                   for match in _QUANTITY_KEEP_ANY[number.weak].finditer(partner_text)):
                return False
            extra = partner_words & _QUANTITY_CLAUSE_WORDS[number.weak]
            if extra:
                extra &= _quantity_words(_other_subject_masked(own_text, partner_text))
            if extra and number.weak == _WEAK_EACH:
                masked = _QUANTITY_OTHER_NOUN.sub(
                    lambda match: match.group(0) if match.group(1) in own_text else "＃" * len(match.group(0)), partner_text)
                extra &= _quantity_words(masked)
            return bool(extra)
        if scope is not None and partner_words & words:
            partner_words = partner_words & _quantity_words(scope)
        if scope is not None and partner_words & _QUANTITY_CLAUSE_WORDS[number.weak]:
            if _QUANTITY_CLAUSE_WORDS[number.weak] & _quantity_words(scope) and (
                    number.weak != _WEAK_SINGLE or "別々に" in scope):
                return True
        return bool(partner_words & words)
    return bool(partner_words & (words | _QUANTITY_CLAUSE_WORDS[number.weak]))


def _with_unpaired_text(sentences, index, paired):
    """組の文 sentences[index] と、そのすぐ前とすぐあとに続く組にならなかった文（前と次の組の文の手前まで）をつないだ文字列。"""
    first = index
    while first > 0 and first - 1 not in paired:
        first -= 1
    last = index
    while last + 1 < len(sentences) and last + 1 not in paired:
        last += 1
    return "".join(sentence.text for sentence in sentences[first:last + 1])


def _following_unpaired(sides, side, sentences, index, paired):
    """組の文 sentences[index] のすぐあとに続く、組にならなかった文と、その数値の並び（次の組の文の手前まで）。"""
    found = []
    position = index + 1
    while position < len(sentences) and position not in paired:
        found.append((sentences[position], _sentence_numbers(sides, side, sentences[position])))
        position += 1
    return found


def _cancel_notation(removed, added, old_numbers, new_numbers):
    """組の文の数値の比べで、同じ数の「単位なし」と「単位あり」を表記の違いとして打ち消す。
    打ち消すのは、単位なしの側が範囲・日付・時刻のまとまりの部品で、まとまりの中の単位なしの数がすべて相手の側の1つのまとまりに
    そろって出てくるとき（「3〜5日 → 3日から5日」「2026-10-13 → 2026年10月13日」「10:30 → 10時30分」。「12:25 → 25分」、
    「10:30 → 10時に始め、30分休む」は打ち消さない。_notation_match）と、
    単位なしの数のあとの空白に、相手の側の単位が続くとき（「3 日 → 3日」「3 s → 3s」）だけ。「手順3 → 3日」「3回 → 3」
    「5 → 5GB」は打ち消さない（diff の詰めの直し。反証で見つけた例）。単位どうしが違う組（3日 → 3週間）は残す。
    old_numbers と new_numbers は組の文の数値（_Number の並び。notation を見る）。"""
    if not removed or not added:
        return removed, added
    removed, added = Counter(removed), Counter(added)
    for mine, other, numbers, others in ((removed, added, old_numbers, new_numbers),
                                         (added, removed, new_numbers, old_numbers)):
        other_set = None
        for number in numbers:
            if number.unit or number.notation is None or mine[number.key] <= 0:
                continue
            if other_set is None:
                other_set = _KeySet(others)
            units = sorted(unit for (value, unit), count in other.items() if value == number.value and unit and count > 0)
            match = next((unit for unit in units if _notation_match(number, other_set, unit)), None)
            if match is not None:
                mine[number.key] -= 1
                other[(number.value, match)] -= 1
    return +removed, +added


def _quantity_words(text):
    """text の数を言う語（_QUANTITY_WORDS。書き方の違いをそろえた語）の集合（_quantity_word_counts の語）。"""
    return set(_quantity_word_counts(text))


def _quantity_word_counts(text):
    """text の数を言う語（_QUANTITY_WORDS。書き方の違いをそろえた語）ごとの出た数（Counter）。打ち消した語は数えない（「上限」は
    上限そのものを打ち消したとき（_QUANTITY_LIMIT_OFF）だけ数える）。"""
    counts = Counter()
    for match in _QUANTITY_WORDS.finditer(text):
        word = _QUANTITY_SAME.get(match.group(0), match.group(0))
        if word == "上限":
            if _QUANTITY_LIMIT_OFF.match(text, match.start()) is not None:
                counts[word] += 1
        elif not _quantity_negated(text, match.end()):
            counts[word] += 1
    return counts


def _drop_weak(removed, added, old_numbers, new_numbers, old_text="", new_text="", old_doc="", new_doc=""):
    """数量を主張しない「一つ」（一つの、一つずつ、もう一つ）を、相手の側に同じ単位の値がなければ比べから外す
    （単独では元にない数値・消えた数値にしない。「二つの → 一つの」「一つの → 三つの」は数が変わったので残す）。
    「一つの」「一つずつ」は、相手の文（old_text と new_text は組の元と後の文と、まとめた・分けた推敲の隣の文。_quantity_text）で
    数の主張が変わっていれば（_quantity_changed。「一つずつ → まとめて」「一つの → 複数の」）外さない。old_doc と new_doc は
    元と後の文書（「一つの」の名詞、「一つずつ」の動詞を見る）。
    相手の文で新しく出た数を言う語は、語ごとの数の差で見る（元の文の別の節に「まとめて」があっても、推敲で足した「同時に」
    「並列で」を新しく出た語とみなす。反証で見つけた例。「まとめて → 一斉に」のような同じ組の言い換えは数が同じなので出ない）。"""
    old_words, new_words = _quantity_word_counts(old_text), _quantity_word_counts(new_text)
    for mine, other, numbers, partner_words, doc, own_text, partner_text in (
            (removed, added, old_numbers, set(new_words - old_words), old_doc, old_text, new_text),
            (added, removed, new_numbers, set(old_words - new_words), new_doc, new_text, old_text)):
        weak = Counter(number.key for number in numbers
                       if number.weak and not _quantity_changed(number, doc, own_text, partner_text, partner_words))
        for key, count in weak.items():
            if mine[key] > 0 and not any(count_other > 0 and unit == key[1]
                                         for (value, unit), count_other in other.items() if (value, unit) != key):
                mine[key] -= min(count, mine[key])
    return +removed, +added


class _KeySet(object):
    """文書の数値（_Number の並び）の (数, 単位) の集合、数ごとの単位の集合（単位なしは ""）、範囲・日付・時刻のまとまり
    （数ごとに、その数を含むまとまりの (数, 単位) の並びの並び）。"""

    def __init__(self, numbers):
        self.keys = set()
        self.units = {}
        self.clusters = {}
        for number in numbers:
            self.keys.add(number.key)
            self.units.setdefault(number.value, set()).add(number.unit)
            if number.cluster is not None:
                self.clusters.setdefault(number.value, set()).add(number.cluster)
        for value, found in self.clusters.items():
            self.clusters[value] = sorted(found)


def _notation_index(numbers):
    """単位なしの数のうち、書き方の手がかり（notation）のあるものを (数, "") ごとにまとめる。"""
    index = {}
    for number in numbers:
        if number.notation is not None:
            index.setdefault(number.key, []).append(number)
    return index


def _notation_match(number, other, unit=None):
    """単位なしの数 number と、相手の側（_KeySet）の同じ数の単位つきの値を、表記の違いとみなせるか（_cancel_notation と
    同じ条件。反証で見つけた例）。unit を渡せば、その単位の値だけを見る。

    みなすのは2つの形だけ。(1) 数のあとの空白に、相手の側の単位が続く（3 日 → 3日、3 s → 3s）。(2) 数が範囲・日付・時刻の
    まとまりの部品で、単位がまとまりの形に合う（反証で見つけた例）。
    - まとまりの中の単位なしの数がこの数だけ（3〜5日 の 3、10時30 の 30）なら、相手の側の単位が、まとまりのほかの数の単位
      （3〜5日 なら日）か、直前の数の単位に続く単位（10時30 なら分、10月13 なら日）のときだけ。「2〜3か月 → 2週間から3か月」の
      2 はみなさない。
    - 2つ以上なら、まとまりの中の単位なしの数がすべて、相手の側の1つのまとまりに同じ順にそろって出てきて、この数と同じ位置の
      単位が相手の単位で、その単位の並びがつなぎの字に合うときだけ（「3/4 → 4月3日」はみなさない。反証で見つけた例）。
      「:」は時・分・秒、「/」と「-」は年・月・日の順の単位（10:30 → 10時30分、2026-10-13 → 2026年10月13日）。
      「〜」「から」は1種類の単位（5〜10 → 5人から10人）。「10/30 → 10時30分」「10:30 → 10月30日」「手順3-5 → 3日から5日」は
      みなさない。「12:25」と、別の所の「20:12」「25分」もみなさない。"""
    if number.unit or number.notation is None:
        return False
    units = other.units.get(number.value, ())
    if unit is not None:
        candidates = [unit] if unit and unit in units else []
    else:
        candidates = [candidate for candidate in units if candidate]
    if not candidates:
        return False
    group, follow, frame = number.notation
    if follow and any(follow.startswith(candidate) for candidate in candidates):
        return True
    if not group:
        return False
    joins, own_units, at = frame
    if len(group) == 1:
        allowed = set(own for own in own_units if own)
        if at and own_units[at - 1] in _NEXT_UNIT:
            allowed.add(_NEXT_UNIT[own_units[at - 1]])
        return any(candidate in allowed for candidate in candidates)
    # 相手の側のまとまりの中の、group と同じ数が同じ順に続いた並び（2026年10月13日10時30分 の中の 10時30分）ごとに見る。
    # この数（まとまりの単位なしの数のうち mine 番目）は、並びの同じ位置の単位がその単位のときだけみなす。順と位置を見ないと、
    # 「3/4 → 4月3日」「10:30〜11:15 → 10時15分から11時30分」の月と日、時と分の入れ替えを表記の違いとして打ち消す
    # （反証で見つけた例）
    mine = [position for position, own in enumerate(own_units) if not own].index(at)
    size = len(group)
    for cluster in other.clusters.get(number.value, ()):
        for start in range(len(cluster) - size + 1):
            picked = cluster[start:start + size]
            if tuple(value for value, _ in picked) != group:
                continue
            if picked[mine][1] not in candidates:
                continue
            if _units_fit(joins, [cluster_unit for _, cluster_unit in picked]):
                return True
    return False


def _units_fit(joins, units):
    """範囲・日付・時刻のまとまり（数と数の間のつなぎの字の種類の並び joins）の単位なしの数に、相手の側のまとまりの単位の並び
    units が合うか（_notation_match）。範囲だけなら1種類の単位。日付と時刻は、単位の並びが前から後ろへ進む（年→月→日、
    時→分→秒）。範囲と日付・時刻が混ざる（10:30〜11:15、10/13〜10/15）ときは、範囲のつなぎの字の数だけ並びが頭に戻ってよい。"""
    kinds = set(joins) - set(("adjacent",))
    named = [unit for unit in units if unit]
    if kinds == set(("range",)):
        return len(set(named)) == 1
    if not named or len(named) != len(units):
        return False
    rest = kinds - set(("range",))
    if rest and rest <= set(("colon",)):
        order = _TIME_UNITS
    elif rest and rest <= set(("slash", "dash")):
        order = _DATE_UNITS
    else:
        order = _DATE_UNITS + _TIME_UNITS
    if any(unit not in order for unit in units):
        return False
    positions = [order.index(unit) for unit in units]
    resets = sum(1 for left, right in zip(positions, positions[1:]) if left >= right)
    return resets <= list(joins).count("range")


def _present(key, notation, other):
    """(数, 単位) が相手の文書の値（_KeySet）にあるか。同じ数と単位が
    あれば「ある」。単位なしの値は、この側の同じ値（notation は _notation_index の形）が範囲・日付・時刻の部品か、空白のあとに
    単位が続く形で、相手の側に同じ数の単位つきの値があれば「ある」（2026-10-13 → 2026年10月13日）。単位つきの値は、同じ数と
    単位があるときだけ「ある」（diff の文書全体の比べで単位つきの値まで単位なしの値で打ち消すと、「BFFを1枚挟む」の「1枚」が
    消えたことを、別の行の「N+1」で見落とすため）。"""
    if key in other.keys:
        return True
    if key[1]:
        return False
    return any(_notation_match(number, other) for number in notation.get(key, ()))


def _sentence_finder(sides, side, groups):
    """位置を含む文 (行番号, 文書の中の位置, 文) を返す関数。hunk の文になければ、その行を丸ごと使う。
    文の始まりの位置の並びを1回だけ作り、二分探索で引く（値ごとに全部の文を前から見ると、値の数×文の数の時間になる。
    反証で見つけた例）。"""
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


# ---- 否定 ----

# 否定の印。「ず」は直後が「に」「、」「。」か文末のときだけ（必ず、はず、まず は除く。読まず のように漢字に続く まず は取る）
_NEGATION = re.compile(
    r"しないで|ません|なかっ|なけれ|ない|なく|禁止"
    r"|(?<!必)(?<!は)ず(?=[に、。]|$)"
    r"|ぬ(?=[。、]|$)"
    r"|未(?![来明])(?=[一-龥])"
    r"|不(?=要|可|明|正|足|在|備|具合|適|十分|一致|安定|許可|採用|使用|参加)"
    r"|非(?=公開|対応|表示|推奨|同期|互換|同意)"
    r"|無(?=効|料|視|関係|制限|断)")
# 数える前に伏せるもの（同じ長さの「＃」にする）。
# 義務の二重否定、否定の形をした別の働き、否定対比（「AではなくB」を外すのは yomiyasu のよくある正しい直し）
_NEGATION_MASKED = re.compile(
    r"なければ(?:ならない|なりません|ならず|いけない|いけません)|なくては(?:ならない|なりません|いけない|いけません)"
    r"|ないと(?:いけない|いけません)|ざるを得(?:ない|ません)|ねば(?:ならない|なりません)"
    r"|かもしれ(?:ない|ません)|に違い(?:ない|ありません)|とは限(?:らない|りません)|わけでは(?:ない|ありません)"
    r"|に(?:すぎ|過ぎ)(?:ない|ません)|しか(?:ない|ありません)|ほか(?:ない|ありません)|問題(?:は|が|も)?(?:ない|なく|ありません)|有無"
    r"|(?:では|じゃ|でも)な(?=[いくかけ])|(?:では|じゃ)ありません")
# 否定の形をした語の一部（少ない、危ない など）。「な」を伏せれば、ない・なく・なかっ・なけれ のどれにも当たらない
_NEGATION_WORDS = re.compile(r"(?:少|危|切|仕方|間違い|もったい|つまら|くだら|たまら|情け|頼り|あっけ|はか|ぎこち|さりげ|味気|素っ気)"
                             r"(な)(?=[いくかけ])")
# 「まず」の「ず」は、直前が漢字でなければ副詞（「まず、」）として除く
_ADVERB_MAZU = re.compile(r"(?<![一-龥々])まず")
_NEGATION_LIMIT = 2         # 変わった文字のうち、否定の印でない文字の数の上限（両側の合計。試作の LIMIT）
# 句点の前の規則（コーパス48組で測って入れると決めた）。変わった箇所が元と後の両方で
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


# 否定の detail を右へ広げる平仮名の字数の上限（はじめは3字。diff の詰めで、句読点か漢字・片仮名の直前まで、
# 上限6字にした。「変更してくださ → 変更しないでくださ」のように語の途中で切れていた）
_WIDEN_RIGHT = 6


def _widen(text, left, right):
    """変わった箇所 [left, right) を語の切れ目まで広げる。左へは平仮名を4字まで、そのあと続く漢字・片仮名の並び全部。
    右へは平仮名を6字まで。句読点と空白で止める。変わった箇所の頭が漢字か片仮名なら、左の平仮名（助詞）は取らず、
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
    while right < len(text) and count < _WIDEN_RIGHT and _HIRAGANA.match(text[right]):
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
    （「。」のない4万字の1行で十数秒。反証で見つけた例）。"""
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


def _unmarked_letters(text, left, right, hits):
    """text[left:right] のうち、否定の印 hits に重ならない、平仮名でない字（漢字、片仮名など）の並び。"""
    return "".join(text[position] for position in range(left, right)
                   if not any(a <= position < b for a, b in hits) and not _HIRAGANA.match(text[position]))


# 文の途中の「する → しない」「せずに ↔ して」。語幹の仮名だけが変わる形で、LIMIT に収まらなかった
_ZU_TO_TE = (frozenset(("さずに", "せずに", "さず", "せず")), frozenset(("して", "し")))


def _verb_stem_change(old_part, new_part):
    """変わった箇所が仮名だけで、「す」で始まる側と「し」で始まる側の組（する → しない）なら2を、「さずに・せずに」と「して」の組
    なら、印でない字の数を消す分（印の「ず」以外の字の数）を返す。印でない字の数から引く。それ以外は0。"""
    if not old_part or not new_part or not all(_HIRAGANA.match(ch) for ch in old_part + new_part):
        return 0
    pair = (old_part, new_part)
    for first, second in (pair, pair[::-1]):
        if first in _ZU_TO_TE[0] and second in _ZU_TO_TE[1]:
            return len(first) - 1 + len(second)
    if (old_part[0], new_part[0]) in (("す", "し"), ("し", "す")):
        return 2
    return 0


def _negation_flip(old, new):
    """組になった2つの文で、否定の有無が変わった最初の箇所の (元の語, 後の語) を返す。なければ None。

    変わった箇所に重なる印だけを数える。重なりは文字の範囲が重なるときだけで、挿入した位置の前後の字は数えない。
    文全体の否定の印の数が元と後で同じときは、印の数が同じまま言い回しだけを変えた推敲を拾わないよう、ふつうは出さない。
    ただし、LIMIT か句点の前の規則に当たる箇所が2つ以上あり、その中に印が増えた箇所と減った箇所の両方があれば出す
    （「Aは対応しているが、Bは対応していない」→「Aは対応していないが、Bは対応している」のように、1つの文の中で
    2つの否定を入れ替えた形。反証で見つけた例）。"""
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
        old_part, new_part = old[i1:i2], new[j1:j2]
        rest = (i2 - i1 - _covered(i1, i2, old_hits)) + (j2 - j1 - _covered(j1, j2, new_hits))
        rest -= _verb_stem_change(old_part, new_part)
        near_end = (_NEGATION_END_RULE and i1 >= old_end - _END_WINDOW and i2 <= old_end
                    and j1 >= new_end - _END_WINDOW and j2 <= new_end
                    # 句点の前の規則は、印でない字の違いが平仮名だけ（漢字・片仮名は両側で同じ）のときに限る
                    # （「変わらない → 同じだ」「欠かせない → 重要だ」のような言い換えを否定に出さない。「設定する → 設定しない」
                    # 「この変更で直る → この変更では直らない」は残る）
                    and _unmarked_letters(old, i1, i2, old_hits) == _unmarked_letters(new, j1, j2, new_hits))
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
    """否定（kind negation）。組になった文を文字で対応させ、変わった箇所ごとに、その箇所に重なる否定の印の数を
    元と後で比べる。数が違い、変わった文字のうち印でない文字が両側合わせて2字以下なら出す（句点の前の規則にも当たれば出す。_NEGATION_END_RULE）。"""
    out = []
    order = 0
    for group in groups:
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            if old.text == new.text:
                continue
            flip = _negation_flip(old.text, new.text)
            if flip is not None:
                out.append((_group_index(group, new), order, _risk("negation", None, old.line, new.line, old.text, new.text,
                                                                 {"old": flip[0], "new": flip[1]})))
                order += 1
    return out


# ---- 主語と目的語の入れ替え ----

_CASE_WORD = re.compile(r"[一-龥々ァ-ヴーA-Za-z0-9０-９・]{1,12}")


_HONORIFIC = re.compile(r"さん|くん|ちゃん")
_CASE_PARTICLE = re.compile(r"から|より|が|を|に|は|へ")


def _case_map(text):
    """「語と助詞」の組。語ごとに最初の1つ（OrderedDict）。語は最長の並びで、直後の さん、様、氏、くん、ちゃん を外す。"""
    found = OrderedDict()
    for match in _CASE_WORD.finditer(text):
        word, end = match.group(0), match.end()
        honorific = _HONORIFIC.match(text, end, end + 3)
        if honorific:
            end += len(honorific.group(0))
        elif len(word) > 2 and word[-1] in "様氏":
            # 「田中様」「佐藤氏」の敬称を外す。2字の語（仕様、同様、彼氏）は外さない
            word = word[:-1]
        particle = _CASE_PARTICLE.match(text, end, end + 2)
        if particle and word not in found:
            found[word] = particle.group(0)
    return found


# 受け身の形（される、された、されて、られる、られた など）
_PASSIVE = re.compile(r"(?:さ|ら)れ(?:る|た|て|ます|ました|ない)")


def _passive_rewrite(old_text, new_text, before, after, words):
    """「に」をとる動詞の受け身への書き換え（この変更がユーザーに影響する → ユーザーがこの変更に影響される）か。片側だけに
    受け身の形があり、入れ替えた助詞の組がすべて「が」と「に」なら真（受け身への書き換えは出さない）。"""
    if bool(_PASSIVE.search(old_text)) == bool(_PASSIVE.search(new_text)):
        return False
    return all(set((before[word], after[word])) == set(("が", "に")) for word in words)


def _swap_risks(sides, groups):
    """主語と目的語の入れ替え（kind swap）。両方の文にある2つの語 A と B で、元で A が p、B が q（p と q は違う）、
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
            if words and _passive_rewrite(old.text, new.text, before, after, words):
                words = []
            if words:
                words.sort(key=common.index)
                pairs = [{"word": word, "old": before[word], "new": after[word]} for word in words]
                out.append((_group_index(group, new), order, _risk("swap", None, old.line, new.line, old.text, new.text,
                                                                 {"pairs": pairs})))
                order += 1
    return out


# ---- 問い ----

_QUESTION = re.compile(r"(?:[？?]|か[。？?])[」』）)]*$")
# 「か。」で終わっても問いでない語（形容動詞の語幹と「ほか」。原因は明らか。→ 原因は明らかだ）
_NOT_QUESTION_KA = re.compile(r"(?:明ら|確|わず|僅|静|豊|ほ|速や|穏や|鮮や|細や|爽や|健や|和や|緩や|賑や|にぎや|華や|"
                              r"密|愚|疎|おろ|遥|はる|ほの|柔ら|滑ら|なめら|清ら|朗ら|安ら|大ま)か。[」』）)]*$")


def _is_question(text):
    text = text.rstrip()
    return bool(_QUESTION.search(text)) and not _NOT_QUESTION_KA.search(text)


# 台詞の最後の「。」（閉じ括弧の前）。2.2.0 の台詞・脚本の推敲は、この「。」だけを外す
_FINAL_PERIOD_IN_QUOTE = re.compile(r"。(?=[」』]+$)")


def _only_final_period_removed(old, new):
    """片方の文から台詞の最後の「。」を外すと、もう片方と同じになるか（「見たのか。」→「見たのか」）。"""
    old, new = old.rstrip(), new.rstrip()
    return _FINAL_PERIOD_IN_QUOTE.sub("", old) == new or _FINAL_PERIOD_IN_QUOTE.sub("", new) == old


def _question_risks(sides, groups):
    """問い（kind sentence_type、subkind question）。組になった文の片方だけが問いの文（文末が ？、?、か。、か？）なら出す。
    句点のない「…か」で終わる文は問いに数えない。"""
    out = []
    order = 0
    for group in groups:
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            old_question, new_question = _is_question(old.text), _is_question(new.text)
            # 台詞の最後の「。」だけを外した組は、問いのまま読めるので出さない
            if old_question != new_question and not _only_final_period_removed(old.text, new.text):
                out.append((_group_index(group, new), order, _risk(
                    "sentence_type", "question", old.line, new.line, old.text, new.text,
                    {"old_is_question": old_question, "new_is_question": new_question})))
                order += 1
    return out

def _is_quote_row(row):
    """引用の行か。「>」のない引用の続きの行（遅延継続。kind は quote、quote_depth は0）も引用とする（反証で見つけた例）。"""
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
    """変えない箇所（kind protected）。変わった文字の範囲が protected_spans（inline_code、autolink、link_destination、
    bare_url、code、frontmatter、html_block、html_token、リンクの定義、画像のパス）か引用のブロックに重なれば出す。
    空白だけの変更でも出す。追加と削除の塊は行の種類で決める。hunk と subkind ごとに1つ。
    文字の対応を省いた置き換えの塊（予算）は、変えない箇所の中身を種類ごとに両側で並べて比べ、違う種類だけを出す
    （インラインのコードやリンク先は行の種類に出ないため。反証で見つけた例）。

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
    """文の種類の印（kind sentence_type、subkind marks）。type_changes の各項目をそのまま数える（判定は変えない）。"""
    return [_risk("sentence_type", "marks", _find_line(sides, 0, change["orig"]), _find_line(sides, 1, change["rewrite"]),
                  change["orig"], change["rewrite"], {"lost": change["lost"], "added": change["added"]})
            for change in (type_changes or [])]


def _modality_risks(sides, changes):
    """許可・能力の言い方の変化（_modality_changes の各項目）を候補にする。許可が消えた・増えたものは kind modality（数える）。
    能力が消えたものは、どの文書の種類でも modality_review（数えない）。detail は文の種類の印と同じ形の lost と added に、
    from と to（許可、能力、不要、義務、禁止、保証、断定）を足したもの。"""
    out = []
    for change in changes or ():
        out.append(_risk("modality_review" if change["subkind"] == "ability_lost" else "modality", change["subkind"],
                         _find_line(sides, 0, change["orig"]), _find_line(sides, 1, change["rewrite"]),
                         change["orig"], change["rewrite"],
                         {"lost": change["lost"], "added": change["added"], "from": change["from"], "to": change["to"]}))
    return out


def _logic_risks(sides, changes):
    """選ぶ範囲と因果の言い方の変化（_logic_changes の各項目）を候補にする。kind は choice か causality（どちらも数える）。
    detail は from と to（どれか一つ、全部、関連、因果）と、元の範囲の from の印（old_hits）、後の範囲の to の印（new_hits）。"""
    return [_risk(change["kind"], change["subkind"], _find_line(sides, 0, change["orig"]), _find_line(sides, 1, change["rewrite"]),
                  change["orig"], change["rewrite"],
                  {"from": change["from"], "to": change["to"], "old_hits": change["old_hits"], "new_hits": change["new_hits"]})
            for change in changes or ()]


# ---- 数に付いた概数と範囲の印（kind number_qualifier）----
# 同じ数（値と単位が同じ。_find_numbers の key）の前後の印が、組の文で消えたり増えたりしたら出す。「約120人 → 120人」は概数を
# 数えた数に、「100人以上 → 100人」は範囲を1つの数に変える。印は家族に分ける。概数（約、およそ、ほど、程度、前後、
# くらい、ごろ など）、下限（以上、以降、超）、上限（以下、以内、以前、未満）、動詞の範囲の言い方（を超える、を上回る、を下回る。
# 下限と上限のどちらとも同じとみなす）。同じ家族の中の言い換え（約120人 → 120人ほど、3日以内 → 3日以下）は出さない。
# 下限と上限は、その数を含むか（以上・以下・以内・以降・以前）含まないか（超、未満）も比べ、入れ替わったら（以上 → 超、
# 以下 → 未満）出す。下限と上限の入れ替わり（以上 → 以下）も出す。数と印はすぐ隣り合うものだけを見る（約束、程度の差、前後関係、文末の「以上です」、
# 「以下のとおり」「以上の3点」のような、数に付かない語は見ない）。数の前の「約」は、「約」で終わる語（契約3件、予約2件）の
# 「約」なら見ない（利用者約120人、人口約120万人の「約」は見る）。
# 範囲（3〜5日、3日から5日）と、万・億・兆を挟んだ数（1万5000人、2億3000万円、3万〜5万円）は、まとまりの数の印を合わせて
# 1つにする（約3〜5日 → 3〜5日程度、約1万5000人 → 1万5000人ほど を同じ概数にする）。
# 相手の側の、同じ数のすぐ隣の、印に近い語（まで、最大、上限、少なくとも、最低、規模、に満たない、より前 など）と、相手の文の、
# 見積もりを言う語（推定、推計、概算、見込み、目安、想定、と見られる など）は、その家族の印があるとみなす（消えた・増えたにしない）。
# 数量を主張しない「一つ」（weak の値）と、元と後で同じ数の数が違う値（数値の候補 number が扱う）は見ない。
_QUALIFIER_JOIN = re.compile(r"[ \t]*(?:[~〜]|から)[ \t]*|[-/:‐-–−]")
# 数のあとに読み飛ばすもの（強調の記号、万・億・兆と単位、「3日間」の「間」、片仮名の単位）
_QUALIFIER_SKIP = re.compile(r"\*{0,2}(?:[万億兆](?:" + _unit_pattern(_UNITS) + r")?)?間?")
# 人が読む数の書き方に含める、数のあとの万・億・兆と単位（10万円、3億円）
_QUALIFIER_SHOWN = re.compile(r"[万億兆](?:" + _unit_pattern(_UNITS) + r")?")
_QUALIFIER_KATAKANA_UNIT = re.compile(r"[ァ-ヴー]{1,6}")
# 単位のある数のあとの、時期と半端を言う語（10月中旬ごろ、15時半ごろ、3月末ごろ、2年半ほど）。読み飛ばしてから印を見る
_QUALIFIER_PART = re.compile(r"上旬|中旬|下旬|初旬|半ば|半|末")
# 数のすぐあとの印。名前は 家族_含むか（approx は概数、lower は下限、upper は上限。in は含む、ex は含まない）。
# 弱・強・余は、あとに続けて語を作る字（弱点、強化、強制、余裕、余計）と、動詞の活用（弱い、強める、余る、余ります）なら
# 印にしない（5分弱かかる、1時間弱要した、3年余働いた は印）
_QUALIFIER_AFTER = re.compile(
    r"[ 　]?(?:"
    r"(?P<approx>ほど|程度|程(?![度遠])|前後(?!関係|左右|不覚|逆|差|し|の関係|の文脈)|ぐらい|くらい|位(?![置相階牌取])|ごろ|頃"
    r"|余り(?!ま[すしせ]|そう)|余(?![裕計地分白剰談韻波興震熱力命暇生罪念儀所程技病勢光香情弊禄話聞部事日人りるっすせられさし])"
    r"|あまり(?![にな良よ多]|ま[すしせ]|そう)|近く|足らず|内外|かそこら|やそこら"
    r"|弱(?![点化体者小気音酸腰冷火毒視肉虫電震いさみめまるりっ]|く(?!らい))"
    r"|強(?![化制調度力固烈硬気行豪盗敵者風弱靭要引奪迫権大国健壮打欲情いさみめまるりっ]|く(?!らい)))"
    r"|(?P<upper_in>以下|以内|以前)|(?P<lower_in>以上|以降|以後)"
    r"|(?P<lower_ex>超え|超(?![過一-龥々〆]))|(?P<upper_ex>未満)"
    r"|(?P<bound_verb>を超[えすさし]|を上回|を下回))")
# 単位のある数にだけ付ける印（ベスト4強、16強、震度5弱、震度は6強、3位 の 強・弱・位 は印ではない）
_QUALIFIER_UNIT_ONLY = frozenset(("弱", "強", "位"))
# 文書の中の場所を言う単位のあとの「以下」は「それより後」（第3章以下、第5条以下）。下限として読む
_QUALIFIER_PLACE_UNITS = frozenset(("章", "節", "項", "条", "号"))
# 版の数（v2.0前後、バージョン2.0前後）のあとの「前後」は「その版の前と後」。印にしない
_QUALIFIER_VERSION_BEFORE = re.compile(r"(?:[vV]|[Vv]er\.?|[Vv]ersion|バージョン)[ 　]?$")
# 動詞の言い方（を超える、を上回る、を下回る）は、範囲の印があることだけを見る（bound の家族）。下限か上限かは、あとの打ち消し
# （を超えて使えません、を下回らない）で入れ替わり、印のすぐ隣だけでは決まらないので、下限と上限のどちらとも同じとみなす。
# 含むかも比べない（「2秒を超え → 2秒以上かかり」のように、文章では含むかを気にせずに言い換えることが多い。測って決めた）
# 数のすぐ前の印（直前の字を見る範囲は _QUALIFIER_BEFORE_REACH）
_QUALIFIER_BEFORE = re.compile(r"(?:(?P<approx>約|およそ|おおよそ|凡そ|概ね|おおむね|ほぼ|推定|大体|だいたい))"
                               r"(?:で|、)?[ 　]*\*{0,2}$")
_QUALIFIER_BEFORE_REACH = 8
# 「約」で終わる語（契約3件、予約2件、要約3行）。この語の「約」は印にしない。人口、取引先 のほうが多いので 口約、先約 は入れない
_QUALIFIER_YAKU_WORDS = frozenset(("契約", "予約", "集約", "要約", "節約", "制約", "公約", "条約", "特約", "規約", "確約",
                                   "誓約", "倹約", "婚約", "盟約", "協約", "密約", "違約", "解約", "成約", "新約", "旧約",
                                   "黙約", "簡約", "縮約", "締約"))
# 上の語の頭の字で終わる名詞（所要約30分、主要約10社、作成約3時間、体制約50人、募集約50名）。この「約」は印にする
_QUALIFIER_YAKU_NOUNS = frozenset(("所要", "必要", "主要", "需要", "重要", "作成", "構成", "完成", "達成", "形成", "編成",
                                   "生成", "結成", "更新", "最新", "刷新", "体制", "募集", "収集", "編集", "結婚", "猶予"))
# 相手の側の、同じ数のすぐ隣の、印に近い語（消えた・増えたの比べで、その家族の印があるとみなす。家族だけを見る）。
# より古い、より新しい は、版（3.9より古い）なら上限、日数（90日より古い）なら下限なので、下限と上限のどちらともみなす
_QUALIFIER_NEAR_AFTER = re.compile(
    r"[ 　]?(?:(?P<both>より古|より新)"
    r"|(?P<upper>まで|より(?:少|前|下|短|低|早|小|手前|若)|に満たな|に届かな|を切[りっるらろれ]|を割[りっるらろれ]|のうちに"
    r"|を上限|が上限|を限度|を最大)"
    r"|(?P<lower>から|より|を下限|が下限|を最低|でも|過ぎ|すぎ|はかか|は必要|は要)"
    r"|(?P<approx>規模|見当|ちょっと|ちょい|そこそこ|ばかり|に迫|に近))")
_QUALIFIER_NEAR_BEFORE = re.compile(r"(?:(?P<upper>最大|最長|最高|最多|多くて|多くとも|多い時で|上限|最大限)"
                                    r"|(?P<lower>最低|最小|最短|少なくとも|少なくて|下限)|(?P<approx>ざっと|およそ))"
                                    r"(?:で|は|、)?[ 　]*\*{0,2}$")
# 相手の文のどこかにあれば、その家族の印があるとみなす語。概数は見積もりを言う語。下限と上限は、範囲の語と、指す語で数を受けた
# 言い方（タイムアウトは30秒で、待ちがこれを超えた → 待ちが30秒を超えた。測って決めた）
_QUALIFIER_SENTENCE = {
    "approx": re.compile(r"推定|推計|概算|見込|見積|目安|想定|概数|大まか|おおまか|ざっと|と見られ|とみられ"),
    "lower": re.compile(r"以上|以降|超え|超す|超し|超過|上回|少なくとも|最低|下限"),
    "upper": re.compile(r"以下|以内|未満|下回|上限|最大|最長|超えな|超えず|超えませ|まで|満たな"),
}
_QUALIFIER_FAMILIES = ("approx", "lower", "upper", "bound")
_QUALIFIER_BOUNDS = frozenset(("lower", "upper", "bound"))
_QUALIFIER_LABELS = {"approx": "概数", "lower_in": "その数を含む下限", "lower_ex": "その数を含まない下限",
                     "upper_in": "その数を含む上限", "upper_ex": "その数を含まない上限",
                     "bound_verb": "動詞で言う範囲"}
_QUALIFIER_STRICT = frozenset(("lower_in", "lower_ex", "upper_in", "upper_ex"))


def _qualifier_yaku_ok(text, start, at):
    """text の at の「約」（文は start から）を概数の印として読むか。直前の字と合わせて「約」で終わる語（契約、予約）なら読まない。
    ただし、その頭の字で終わる名詞（所要、主要、作成）のあとなら読む。"""
    if at <= start or text[at - 1:at + 1] not in _QUALIFIER_YAKU_WORDS:
        return True
    return at - 2 >= start and text[at - 2:at] in _QUALIFIER_YAKU_NOUNS


def _qualifier_tail(text, number, end):
    """数 number のあとの、読み飛ばす続き（強調の記号、万・億・兆と単位、「間」、片仮名の単位）の終わりと、単位があるかを返す。"""
    at = _QUALIFIER_SKIP.match(text, number.end, end).end()
    unit = bool(number.unit) or any(char in "万億兆" for char in text[number.end:at])
    if not number.unit and at == number.end:
        katakana = _QUALIFIER_KATAKANA_UNIT.match(text, at, end)
        if katakana is not None:
            at, unit = katakana.end(), True
    return at, unit


def _qualifier_shown_end(text, number, end):
    """人が読む数の書き方の終わり（10万円、3億円、5パーセント、10月中旬、15時半。強調の記号と「間」は含めない）。"""
    at, unit = number.end, bool(number.unit)
    shown = _QUALIFIER_SHOWN.match(text, at, end)
    if shown is not None:
        at, unit = shown.end(), True
    elif not number.unit:
        katakana = _QUALIFIER_KATAKANA_UNIT.match(text, at, end)
        if katakana is not None:
            at, unit = katakana.end(), True
    part = _QUALIFIER_PART.match(text, at, end) if unit else None
    return part.end() if part is not None else at


def _qualifier_after(text, at, end, number, unit, names, words):
    """数のあとの印を2つまで読み、names と words に足す。終わりの位置を返す。数と印の間の「前」「後」は読み飛ばす
    （3年前ぐらい、1時間前ほど は 3年ぐらい前、1時間ほど前 と同じ概数）。"""
    if unit:
        part = _QUALIFIER_PART.match(text, at, end)
        if part is not None:
            at = part.end()
    for _ in range(2):
        found = _QUALIFIER_AFTER.match(text, at, end)
        if found is None and text.startswith(("前", "後"), at) and at + 1 < end:
            found = _QUALIFIER_AFTER.match(text, at + 1, end)
        if found is None:
            break
        at = found.end()
        name, word = found.lastgroup, found.group(found.lastgroup)
        if word in _QUALIFIER_UNIT_ONLY and not unit:
            continue      # ベスト4強、16強、震度5弱、震度は6強、3位（印ではなく、順位や段階の名前）
        if word == "前後" and not unit and _QUALIFIER_VERSION_BEFORE.search(text, 0, number.start):
            continue      # v2.0前後、バージョン2.0前後（その版の前と後）
        if word == "近く" and number.unit == "号":
            continue      # 国道1号近く（場所）
        if word == "以下" and number.unit in _QUALIFIER_PLACE_UNITS:
            name = "lower_in"     # 第3章以下（第3章から後）
        names.add(name)
        words.append(word)
    return at


def _qualifier_marks(text, start, end, number):
    """文 text（[start, end) が文の範囲）の数 number に付いた印。(印の名前の集合, 印の語の並び, 隣の語の家族の集合) を返す。
    印の名前は _QUALIFIER_AFTER と _QUALIFIER_BEFORE の名前（approx、lower_in、lower_ex、upper_in、upper_ex）。"""
    names, words, near = set(), [], set()
    head = text[max(start, number.start - _QUALIFIER_BEFORE_REACH):number.start]
    before = _QUALIFIER_BEFORE.search(head)
    if before is not None:
        at = number.start - len(head) + before.start()
        word = before.group("approx")
        if word != "約" or _qualifier_yaku_ok(text, start, at):
            names.add("approx")
            words.append(word)
    near_before = _QUALIFIER_NEAR_BEFORE.search(head)
    if near_before is not None:
        near.add(near_before.lastgroup)
    at, unit = _qualifier_tail(text, number, end)
    at = _qualifier_after(text, at, end, number, unit, names, words)
    near_after = _QUALIFIER_NEAR_AFTER.match(text, at, end)
    if near_after is not None:
        near.update(("lower", "upper") if near_after.lastgroup == "both" else (near_after.lastgroup,))
    return names, words, near


def _qualifier_joined(text, previous, number, end):
    """前の数 previous と数 number が1つのまとまり（範囲の 3〜5日、3日から5日、3万円程度から5万円程度、万・億・兆を挟んだ
    1万5000人、2億3000万円、3万〜5万円）か。前の数のあとの万・億・兆と単位と印を読み飛ばし、残りがなにもないか、つなぎ
    （〜、から、-、/、:）だけなら真。"""
    if previous.end == number.start:
        return True
    at, unit = _qualifier_tail(text, previous, number.start)
    compound = any(char in "万億兆" for char in text[previous.end:at])
    at = _qualifier_after(text, at, number.start, previous, unit, set(), [])
    between = text[at:number.start].translate(_HALF_WIDTH)
    if not between:
        return compound or at == previous.end
    return "\n" not in between and _QUALIFIER_JOIN.fullmatch(between) is not None


# 数が文の範囲を越えたときに、範囲を延ばす先の文の終わり。全角の小数点（３．５）で切れた文の終わり
_QUALIFIER_SENTENCE_STOP = re.compile(r"[。！？!?\n]")
_QUALIFIER_SPLIT_DECIMAL = re.compile(r"[0-9０-９]．$")


def _qualifier_reach(sides, side, sentence, numbers):
    """数の印を読む範囲の文字列（ふだんは文そのもの）。全角の小数点（３．５）は文の区切りにも読まれるので、数が文の範囲を
    越えることがある。そのときは、その数を含む文の終わり（次の句点か改行）までを範囲にして、数のあとの印も読む。"""
    text = sides.texts[side]
    start, end = sentence.start, sentence.start + len(sentence.text)
    reach = max([end] + [number.end for number in numbers])
    if reach > end:
        stop = _QUALIFIER_SENTENCE_STOP.search(text, reach)
        end = stop.end() if stop is not None else len(text)
    return text[start:end]


def _qualifier_states(sides, side, sentence, numbers):
    """組の文の数ごとの (key, 印の名前の集合, 印の語の並び, 隣の語の家族の集合, 書かれた形) の並び。範囲・日付・時刻の
    まとまり（3〜5日、3日から5日）と、万・億・兆を挟んだ数（1万5000人）は、まとまりの数の印を合わせて1つにする（key は数の
    並びと最後の単位）。数量を主張しない値（weak）は入れない。"""
    text = sides.texts[side]
    start = sentence.start
    end = start + len(_qualifier_reach(sides, side, sentence, numbers))
    marks = [_qualifier_marks(text, start, end, number) for number in numbers]
    groups = list(range(len(numbers)))
    for index in range(1, len(numbers)):
        if _qualifier_joined(text, numbers[index - 1], numbers[index], end):
            groups[index] = groups[index - 1]
    merged = OrderedDict()
    for index, (names, words, near) in enumerate(marks):
        if numbers[index].weak:
            continue
        members, names_all, words_all, near_all = merged.setdefault(groups[index], ([], set(), [], set()))
        members.append(numbers[index])
        names_all.update(names)
        words_all.extend(words)
        near_all.update(near)
    out = []
    for members, names, words, near in merged.values():
        # まとまりは1つの値にする。key は数の並びと最後の単位（3〜5日 と 3日から5日 を同じにする）
        key = members[0].key if len(members) == 1 else (tuple(m.value for m in members), members[-1].unit)
        shown = text[members[0].start:_qualifier_shown_end(text, members[-1], end)].replace("**", "")
        out.append((key, frozenset(names), tuple(words), frozenset(near), shown))
    return out


def _qualifier_change(old_names, new_names, old_near, new_near, old_words, new_words):
    """1つの数の印の比べ。(消えた家族, 増えた家族, 含むかが変わった家族) を返す。相手の側の隣の語（near）と、相手の文の
    その家族の語（old_words と new_words。_QUALIFIER_SENTENCE が当たった家族の集合）があれば、その家族は消えた・増えたに
    しない。動詞の言い方（bound）は下限と上限のどちらとも同じとみなす。含むかは、元と後の両方がその家族の名詞の印（以上、超、
    以下、未満 など）1つずつのときだけ比べる。"""
    def families(names):
        return set(name.split("_")[0] for name in names)

    def present(family, fams, near, words):
        has = fams | near | words
        if family == "bound":
            return bool(has & _QUALIFIER_BOUNDS)
        return family in has or (family in _QUALIFIER_BOUNDS and "bound" in fams)
    old_f, new_f = families(old_names), families(new_names)
    lost = [f for f in _QUALIFIER_FAMILIES if f in old_f and not present(f, new_f, new_near, new_words)]
    added = [f for f in _QUALIFIER_FAMILIES if f in new_f and not present(f, old_f, old_near, old_words)]
    strict = []
    for family in ("lower", "upper"):
        olds = set(name for name in old_names if name.startswith(family))
        news = set(name for name in new_names if name.startswith(family))
        if len(olds) == 1 and len(news) == 1 and olds != news and (olds | news) <= _QUALIFIER_STRICT:
            strict.append(family)
    return lost, added, strict


def _qualifier_risks(sides, groups):
    """数に付いた概数と範囲の印の変化（kind number_qualifier。--fail-on に数える）。組の文で、同じ値と単位の数が元と後に
    同じ数だけあり、その印の家族が消えたか（lost）、増えたか（added）、家族や含むかが入れ替わったか（changed）を見る。
    detail は old_number と new_number（数の書かれた形）、from と to（印の名前の並び。印がなければ空）、old_markers と new_markers（印の語）。"""
    out = []
    for group in groups:
        for i, j in group["pairs"]:
            old, new = group["old"][i], group["new"][j]
            if old.text == new.text and not _QUALIFIER_SPLIT_DECIMAL.search(old.text):
                continue
            old_numbers = _sentence_numbers(sides, 0, old)
            if not old_numbers:
                continue
            new_numbers = _sentence_numbers(sides, 1, new)
            if not new_numbers:
                continue
            if old.text == new.text and (_qualifier_reach(sides, 0, old, old_numbers)
                                         == _qualifier_reach(sides, 1, new, new_numbers)):
                continue  # 全角の小数点で切れた文で、数を含む文の終わりまで見ても同じ
            olds = _qualifier_states(sides, 0, old, old_numbers)
            news = _qualifier_states(sides, 1, new, new_numbers)
            old_count = Counter(state[0] for state in olds)
            new_count = Counter(state[0] for state in news)
            words = [None, None]
            for key in old_count:
                if old_count[key] != new_count.get(key):
                    continue
                old_states = [state for state in olds if state[0] == key]
                new_states = [state for state in news if state[0] == key]
                if Counter(s[1] for s in old_states) == Counter(s[1] for s in new_states):
                    continue
                if len(old_states) > 1:
                    # 同じ値が2つ以上あるときは、印の名前が同じものを先に外し、残りを位置の順に組にする
                    rest = Counter(s[1] for s in new_states)
                    kept_old = []
                    for state in old_states:
                        if rest[state[1]] > 0:
                            rest[state[1]] -= 1
                        else:
                            kept_old.append(state)
                    rest = Counter(s[1] for s in old_states)
                    kept_new = []
                    for state in new_states:
                        if rest[state[1]] > 0:
                            rest[state[1]] -= 1
                        else:
                            kept_new.append(state)
                    old_states, new_states = kept_old, kept_new
                for before, after in zip(old_states, new_states):
                    if words[0] is None:
                        words = [set(f for f, regex in _QUALIFIER_SENTENCE.items() if regex.search(old.text)),
                                    set(f for f, regex in _QUALIFIER_SENTENCE.items() if regex.search(new.text))]
                    lost, added, strict = _qualifier_change(before[1], after[1], before[3], after[3], words[0], words[1])
                    if not (lost or added or strict):
                        continue
                    subkind = "lost" if lost and not added and not strict else (
                        "added" if added and not lost and not strict else "changed")
                    out.append(_risk("number_qualifier", subkind, old.line, new.line, old.text, new.text,
                                     {"old_number": before[4], "new_number": after[4], "from": sorted(before[1]), "to": sorted(after[1]),
                                      "old_markers": list(before[2]), "new_markers": list(after[2])}))
    return out


def meaning_risks(orig, rw, full=None, type_changes=None, *, doc_type=None):
    """意味が変わる恐れ（JSON の meaning_risks）。

    full は full_diff(orig, rw) の戻り値（渡さなければ作る）。type_changes は diff() の type_changes で、
    None か [] なら文の種類の印（sentence_type/marks）を含めない。この関数の中で9キーの分析は作らない。
    type_changes を渡したとき（[] も含む）は、diff() と同じく許可・能力の言い方の候補（modality、modality_review）と、
    選ぶ範囲・因果の言い方の候補（choice、causality）も足すので、
    同じ文章の diff() の type_changes を渡せば diff() の meaning_risks と同じになる。そのときだけ、許可・能力の印があれば
    文字の対応と範囲をこの関数の中で作る。None なら許可・能力の候補を足さない。
    doc_type は diff() と同じ文書の種類（事実や仕様を述べる種類では、確度の2つの強まりを数える側に入れる）。"""
    doc_type = normalize_doc_type(doc_type)
    if full is None:
        full = full_diff(orig, rw)
    modality = logic = None
    if type_changes is not None:
        try:
            o, r = normalize(orig), normalize(rw)
            modality = _modality_changes(o, r)
            logic = _logic_changes(o, r)
        finally:
            _LAST_TYPE_RANGES[0] = None
    return _meaning_risks(_Sides(orig, rw), full, type_changes, doc_type=doc_type, modality=modality, logic=logic)


def _meaning_risks(sides, full, type_changes, groups=None, doc_type=None, modality=None, logic=None):
    """意味が変わる恐れを集める。doc_type は正規化した文書の種類、modality は _modality_changes の戻り値、logic は
    _logic_changes の戻り値（diff() と meaning_risks() が渡す）。"""
    if groups is None:
        groups = _sentence_pairs(sides, full)
    found = (_number_risks(sides, full, groups) + _negation_risks(sides, groups) + _swap_risks(sides, groups)
             + _question_risks(sides, groups) + _protected_risks(sides, full) + _contrast_risks(sides, groups)
             + _feeling_risks(sides, groups))
    found.sort(key=lambda item: (item[0], _RISK_ORDER.get(item[2]["kind"], 9), item[1]))
    all_marks = _marks_risks(sides, type_changes)
    quiet, delegated = [], []
    for mark in all_marks:
        classification = _classify_hedge_marks(mark["old"], mark["new"], mark["detail"]["lost"], mark["detail"]["added"])
        if classification in ("same", "strengthen"):
            quiet.append(mark)
            if classification == "strengthen":
                delegated.append(mark)
    quiet_ids = {id(mark) for mark in quiet}
    risks = [risk for _, _, risk in found] + [mark for mark in all_marks if id(mark) not in quiet_ids]
    sides.immutable, citations = _immutable_values(sides, risks, groups)
    # 足した候補は既存の候補の後ろに、行の順で並べる（既存の並びは変えない。反証で見つけた例）
    citations.sort(key=lambda r: (r["old_line"] if r["old_line"] is not None else r["new_line"] or 0,
                                  r["new_line"] if r["new_line"] is not None else 0))
    risks += citations
    masks = (_Masker(sides, 0), _Masker(sides, 1))
    certainty = _certainty_risks(sides, groups, risks, masks, doc_type=doc_type)
    # 強める向きでも、同じ原文の文に数える確度が出なければ印を戻す。
    strengthened = [(r["old_line"], normalize(r["old"] or "").strip()) for r in certainty
                    if (r["kind"], r["subkind"]) == ("certainty", "strengthened")]
    restored_ids = set()
    for mark in delegated:
        old = normalize(mark["old"] or "").strip()
        # _same_review_sentence と同じく、行と文の含み合いの両方で照らす（別の行の同じ文で戻すのを止めない。反証で見つけた例）
        if not any(old and text and (old in text or text in old)
                   and (mark["old_line"] is None or line == mark["old_line"]) for line, text in strengthened):
            restored_ids.add(id(mark))
    if restored_ids:
        quiet_ids -= restored_ids
        risks = ([risk for _, _, risk in found]
                 + [mark for mark in all_marks if id(mark) not in quiet_ids] + citations)
        certainty = _certainty_risks(sides, groups, risks, masks, doc_type=doc_type)
    sides.quiet_marks = [mark for mark in quiet if id(mark) in quiet_ids]
    # 許可・能力の言い方の候補と、選ぶ範囲・因果の言い方の候補、数に付いた概数と範囲の印の候補も、確度とかぎかっこの候補と同じく、
    # 既存の候補の後ろに行の順で並べる。
    added = (certainty + _quote_risks(sides, groups, masks) + _modality_risks(sides, modality) + _logic_risks(sides, logic)
             + _qualifier_risks(sides, groups))
    added.sort(key=lambda r: (r["old_line"] if r["old_line"] is not None else r["new_line"] or 0,
                              r["new_line"] if r["new_line"] is not None else 0))
    risks += added
    # 出力から外した印も、状態・約束の候補を重ねない決めには使う。
    additions = _addition_risks(sides, groups, risks + sides.quiet_marks, masks)
    # 状態の候補に写した確度の見直しだけを取り除く。数える確度は残す。
    lost = [_Body('', r['old'], r['old_line'], 0) for r in additions if r['kind'] == 'state']
    risks = [r for r in risks if r['kind'] != 'certainty_review'
             or not any(_same_review_sentence(body, r) for body in lost)]
    additions.sort(key=lambda r: (r['old_line'] if r['old_line'] is not None else r['new_line'] or 0,
                                  r['new_line'] if r['new_line'] is not None else 0))
    return risks + additions


# ---- 一覧のファイル（diff の詰め）----
# 名詞化の言い回し、強める語、気持ちの語、慎重表現の一覧は references/lists/ に置き、足し引きできるようにする。diff はスクリプトの隣の
# ../references/lists/<名前>.txt を読み、ないとき（配布 ZIP に入っていない、ZIP の中から読み込まれた）や読めないとき
# （UTF-8 でない、正規表現の誤り）は、ここに置いた内蔵の一覧で動く。どちらを使ったかは JSON の "list" に出す。
# 書き方: 1行に1つ。空行と「#」で始まる行は読み飛ばす。名詞化の言い回しと気持ちの語は「名前<TAB>正規表現」、強める語と慎重表現は語だけ。
# 気持ちの語は3つ目の欄を置いてよい（「名前<TAB>正規表現<TAB>原文の言い方の正規表現」。原文にこの言い方があれば、その家族の
# 気持ちは原文にあるとみなす。お詫び → 申し訳、ありがとう → 感謝。diff の詰めの直し、反証で見つけた例）。

BUILTIN_LISTS = {
    "hedges": ("と考えられる", "と思われる", "可能性がある", "示唆する", "推測される", "の範囲では", "かもしれない"),
    # 和語の言い回しを名詞化した決まった形の11個と、試作で測って足した「不可能」
    "nominalization": (
        ("が可能", "が可能(?:です|でした|だ|である|となり|となる|となっ|になり|になる|になっ|な|に|で|。|、)"),
        ("することが可能", "することが可能"),
        ("の実施", "の実施"),
        ("を実施", "を実施(?:し|す|さ)"),
        ("を担保", "を担保"),
        ("を図る", "を図(?:る|り|っ|ら|れ)"),
        ("に資する", "に資(?:する|し|さ)"),
        ("につながる", "につなが(?:る|り|っ|ら)"),
        ("の観点から", "の観点(?:から|で|では)"),
        ("に関して", "に関(?:して|し|する)"),
        ("を行う", "を行(?:う|い|っ|わ|え)"),
        ("不可能", "(?:は|が)不可能"),
    ),
    # 量や気持ちを強める語と、評価を強める語の9個と、紹介記事で勢いを出す語の「パンチ」「ずらり」（diff の詰めで測って足した）
    "intensifiers": ("本当に", "とても", "すごく", "ぜひ", "絶対", "最強", "抜群", "イチオシ", "大活躍", "パンチ", "ずらり"),
    # 気持ちの語（試作の辞書を、語の家族ごとにまとめた）。diff の詰めの直し
    # （反証で見つけた例）で、心配・満足・落ち込むの気持ちでない言い方を除き、
    # 感謝と申し訳に原文の言い方の欄を足し、苦しい〜胸が の8つの家族を足した
    "feelings": (
        ("ほっと", "ほっと(?=し|す|で|一息|ひと息|息)"),
        ("安堵", "安堵"),
        ("安心", "安心"),
        ("肩の荷", "肩の荷"),
        ("胸をなで", "胸をなで"),
        ("うれしい", "嬉し|うれし"),
        ("喜ぶ", "喜ん|喜び|喜ば|よろこ[んびば]"),
        ("楽しい", "楽し|たのし"),
        ("面白い", "面白|おもしろ"),
        ("悔しい", "悔し|くやし"),
        ("残念", "残念"),
        ("悲しい", "悲し|かなし"),
        ("寂しい", "寂し|淋し|さびし|さみし"),
        ("がっかり", "がっかり|落胆"),
        ("驚く", "驚[いきくか]|おどろ[いきくか]|びっくり"),
        ("不安", "不安(?!定)"),
        # 「心配はありません」「心配いりません」「心配無用」「心配なく」は、恐れがないことを言う決まった言い方
        # 「心配は要りません」「ご心配には及びません」も同じ（反証で見つけた例）
        ("心配", "心配(?!り)(?!(?:は|も)?(?:ありません|ない|いりません|いらない|要りません|要らない|無用|ご無用|なく)"
                 "|(?:に)?は及(?:びません|ばない))"),
        ("怖い", "怖[いかくがさ]|恐ろし|こわ(?:い|かっ|く(?!し|ず|れ))"),
        ("焦る", "焦っ|焦り|焦る|あせっ|あせり|あせる"),
        ("恥ずかしい", "恥ずかし|はずかし"),
        ("誇らしい", "誇らし|ほこらし"),
        ("感動", "感動"),
        ("感激", "感激"),
        ("もやもや", "もやもや|モヤモヤ"),
        ("いらいら", "いらいら|イライラ|苛立"),
        ("うんざり", "うんざり"),
        ("わくわく", "わくわく|ワクワク"),
        ("どきどき", "どきどき|ドキドキ"),
        # 「条件を満足する」「満足する場合」は満たすの意味
        ("満足", "満足(?!度)(?<!を満足)(?!する(?:場合|とき|こと|もの))"),
        # 原文の言い方の「礼を」は「失礼を」「無礼を」「非礼を」の中に当てない（反証で見つけた例）
        ("感謝", "感謝", "ありがと|お礼|(?<![失無非])礼を|謝意"),
        ("ありがたい", "ありがた|有難|有り難"),
        ("申し訳", "申し訳", "すみません|すいません|お詫び|おわび|詫び|ごめん|陳謝|謝罪"),
        ("幸せ", "幸せ|しあわせ"),
        ("腹が立つ", "怒っ|怒り|腹が立|腹立"),
        ("後悔", "後悔"),
        ("戸惑う", "戸惑|とまど"),
        ("懐かしい", "懐かし|なつかし"),
        ("憂鬱", "憂鬱|ゆううつ"),
        # 「売上が落ち込む」「数が落ち込む」は数の減り（先に「落ち込」を探してから前を見る。前を先に見ると遅い）。数の減りを言う
        # 名詞（売り上げ、件数、率、量、額、残高、需要、業績、景気、利益、株価）の終わりの字と「が」「は」「の」のあと（件数の
        # 落ち込み）と、「半分に落ち込む」（数が下がった先）を除く（反証で見つけた例。名詞を1つずつ並べると後読みが48個に
        # なるので、終わりの字で見る）。「上」「ト」「ク」「ス」で終わる数の名詞（売上、コスト、レート、リクエスト、スループット、
        # トラフィック、アクセス、パフォーマンス、ペース、セールス）は語ごとに除く。終わりの字で除くと、苗字（井上、村上）、
        # 片仮名の名前（マーク、ルーカス）、呼び名（母上、ゲスト）のあとの気持ちの語を見逃す（反証で見つけた例）
        ("落ち込む", "落ち込(?<!に落ち込)(?<![げ数率量額高要績気益価][がはの]落ち込)(?<!売上[がはの]落ち込)(?<!コスト[がはの]落ち込)"
                    "(?<!レート[がはの]落ち込)(?<!リクエスト[がはの]落ち込)(?<!スループット[がはの]落ち込)(?<!トラフィック[がはの]落ち込)"
                    "(?<!アクセス[がはの]落ち込)(?<!パフォーマンス[がはの]落ち込)(?<!ペース[がはの]落ち込)(?<!セールス[がはの]落ち込)"),
        ("つらい", "つら(?:い|かっ|く)"),
        ("切ない", "切な(?:い|かっ|く)|せつな(?:い|かっ|く)"),
        ("涙", "涙"),
        ("緊張", "緊張(?!感のある|状態|関係)"),
        # 物事の様子を言う「堅苦しい」「見苦しい」「重苦しい」「暑苦しい」は除く（後読みを「苦し」の前に置くと遅い。
        # 反証で見つけた例）
        ("苦しい", "苦し(?<![堅見重暑]苦し)(?:い|かっ|く|さ|み|そう)"),
        ("恐怖", "恐怖"),
        ("嫌だ", "嫌(?:な(?:気|思い|予感)|だっ|気が|になっ)"),
        ("愛おしい", "愛おし|いとおし"),
        ("心細い", "心細"),
        ("情けない", "情けな"),
        ("むなしい", "むなし|虚し"),
        ("胸が", "胸が(?:痛|熱|締め|苦し|躍|高鳴|詰ま|いっぱい)"),
    ),
}
# 一覧の書き方（True は「名前<TAB>正規表現」）
_LIST_PATTERNS = {"nominalization": True, "intensifiers": False, "feelings": True, "hedges": False}
# 3つ目の欄（原文の言い方）を置ける一覧
_LIST_THIRD_COLUMN = frozenset(("feelings",))
_LIST_CACHE = {}
# 一覧のファイルがあるのに読めなかった理由（なければ None）。人が読む出力の硬化と勢いの節に1行出し、JSON の list_problem に
# 入れる（diff の詰めの直し。反証で見つけた例）。ファイルがないとき（配布 ZIP、
# スクリプトだけの置き方）は理由にしない
_LIST_PROBLEMS = {}
# ファイルがないとみなす誤り（ZIP の中から読み込まれたときは、ZIP のパスの下を開こうとして NotADirectoryError になる）
_LIST_ABSENT = (FileNotFoundError, NotADirectoryError)
_LIST_PROBLEM_WIDTH = 40        # 理由に写す行の字数の上限


def parse_list(text, pattern=False):
    """一覧のファイルの中身を読む。pattern が真なら [(名前, 正規表現の文字列)]、偽なら [語]。空行と「#」で始まる行は読み飛ばす。
    pattern が真で3つ目の欄（タブのあと）がある行は (名前, 正規表現, 3つ目の欄) にする（気持ちの語の「原文の言い方」）。
    先頭の BOM（U+FEFF）は外す（Windows のメモ帳の「UTF-8（BOM 付き）」。反証で見つけた例）。
    正規表現の誤りはここでは確かめない（_load_list が確かめ、誤りがあれば内蔵の一覧にする）。"""
    if text.startswith("﻿"):
        text = text[1:]
    out = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if pattern:
            name, _, regex = line.partition("\t")
            regex, _, third = regex.partition("\t")
            if not regex.strip():
                shown = line if len(line) <= _LIST_PROBLEM_WIDTH else line[:_LIST_PROBLEM_WIDTH] + "…"
                raise ValueError("「名前<TAB>正規表現」の形でない行があります: " + shown)
            if third.strip():
                out.append((name.strip(), regex.strip(), third.strip()))
            else:
                out.append((name.strip(), regex.strip()))
        else:
            out.append(line.strip())
    return out


def _compile_item(item):
    """(名前, 正規表現[, 3つ目の欄]) の正規表現をコンパイルする。"""
    return (item[0],) + tuple(re.compile(regex) for regex in item[1:])


_ANY_OF_CACHE = {}


def _any_of(items):
    """正規表現の並び（項目は正規表現か、2つ目が正規表現のタプル）のどれかが当たるかを1回で調べる正規表現。どれも当たらない
    文を先に飛ばすのに使う。作れないとき（捕まえる組や、文書全体にかかる印 (?i) などがあって、つなぐと意味が変わりうる。
    コンパイルできない）は None（呼ぶ側は1つずつ調べる）。並びのオブジェクトごとに1回だけ作る（一覧は _load_list が
    1回だけ読むので、同じオブジェクトが渡される）。"""
    cached = _ANY_OF_CACHE.get(id(items))
    if cached is not None and cached[0] is items:
        return cached[1]
    regexes = [item if hasattr(item, "pattern") else item[1] for item in items]
    combined = None
    if regexes and all(regex.groups == 0 and regex.flags == re.UNICODE and isinstance(regex.pattern, str)
                       for regex in regexes):
        # 「|」は正規表現でいちばん弱い結び付きなので、1つずつコンパイルできた正規表現を「|」でつないだものは、どれかが
        # 当たる位置で当たる。(?:…) で囲むと、re が先頭の字の候補で位置を飛ばす工夫を使えず、1つずつ調べるより遅くなる
        try:
            combined = re.compile("|".join(regex.pattern for regex in regexes))
        except re.error:
            combined = None
    if len(_ANY_OF_CACHE) >= 32:      # 一覧のほかの並びを渡されつづけても大きくしない
        _ANY_OF_CACHE.clear()
    _ANY_OF_CACHE[id(items)] = (items, combined)
    return combined


def _list_problem_text(error):
    """一覧のファイルを読めなかった理由（人が読む出力と JSON の list_problem に入れる文）。"""
    if isinstance(error, UnicodeDecodeError):
        return "UTF-8 として読めません"
    if isinstance(error, re.error):
        return "正規表現の誤り（{}）".format(error)
    if isinstance(error, OSError):
        return "ファイルを開けません（{}）".format(getattr(error, "strerror", None) or error)
    if isinstance(error, ValueError):
        return str(error)
    return "{}: {}".format(type(error).__name__, error)


def _load_list(name):
    """一覧を読む。(項目, 出どころ) を返す。出どころは "references/lists/<名前>.txt" か "builtin"。
    pattern の一覧の項目は (名前, コンパイルした正規表現)。強める語と慎重表現の項目は語。
    ファイルがあるのに読めなかったとき（UTF-8 でない、書き方や正規表現の誤り、開けない）は、内蔵の一覧で動き、理由を
    _LIST_PROBLEMS に残す（_list_info）。BOM つきの UTF-8 も読む（utf-8-sig。反証で見つけた例）。"""
    if name in _LIST_CACHE:
        return _LIST_CACHE[name]
    pattern = _LIST_PATTERNS[name]
    items, source, problem = None, "builtin", None
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "references", "lists", name + ".txt")
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except _LIST_ABSENT:    # ない（配布 ZIP、スクリプトだけの置き方）。知らせずに内蔵の一覧で動く
        data = None
    except OSError as error:
        data, problem = None, _list_problem_text(error)
    if data is not None:
        try:
            parsed = parse_list(data.decode("utf-8-sig"), pattern=pattern)
            if pattern and name not in _LIST_THIRD_COLUMN and any(len(item) > 2 for item in parsed):
                raise ValueError("3つ目の欄はこの一覧では使えません")
            if name == "fact-gaps" and any(item[0] not in ("degree", "change", "effect", "figure") for item in parsed):
                raise ValueError("事実の穴の種類は degree、change、effect、figure です")
            items = [_compile_item(item) for item in parsed] if pattern else parsed
            source = "references/lists/{}.txt".format(name)
        except Exception as error:  # UTF-8 でない、書き方や正規表現の誤り。止めずに内蔵の一覧で動く
            items, problem = None, _list_problem_text(error)
    if items is None:
        builtin = BUILTIN_LISTS[name]
        items = [_compile_item(item) for item in builtin] if pattern else list(builtin)
        source = "builtin"
    _LIST_CACHE[name] = (items, source)
    _LIST_PROBLEMS[name] = problem
    return _LIST_CACHE[name]


def _list_info(name):
    """JSON に出す一覧の出どころと、読めなかった理由（{"list": 出どころ, "list_problem": 理由か None}）。"""
    _, source = _load_list(name)
    return {"list": source, "list_problem": _LIST_PROBLEMS.get(name)}


# ---- 本文として数える文（硬化、否定対比の逆転、気持ちの語、勢いの検査で共通）----

# 文として数えない行の種類（コード、URL、表、見出しなど）
_BODY_SKIP_KINDS = frozenset(("code", "frontmatter", "html_block", "table", "heading", "heading_underline",
                              "reference_definition", "thematic_break", "blank"))
# 文の中で伏せる範囲（インラインのコード、URL、リンク先、画像、HTML のタグ）
_BODY_MASK_KINDS = frozenset(("inline_code", "autolink", "bare_url", "link_destination", "image", "html_token"))
_K = "㐀-䶿一-鿿豈-﫿々〆"          # 漢字（々 と 〆 を含む）
_STIFF_KANJI = re.compile("[" + _K + "]")
# 文の長さに数える句読点とかっこ（記号と空白は数えない。文字と数字は数える）
_LENGTH_PUNCT = frozenset("、。，．！？!?「」『』（）()…・")


class _Body(tuple):
    """数える文。text は伏せる範囲を除いた文、raw は元の文（行頭の印を外したもの）、line は行番号、start は位置。"""
    __slots__ = ()

    def __new__(cls, text, raw, line, start):
        return tuple.__new__(cls, (text, raw, line, start))

    text = property(lambda self: self[0])
    raw = property(lambda self: self[1])
    line = property(lambda self: self[2])
    start = property(lambda self: self[3])


class _Masker:
    """1つの側の、数えない行と伏せる範囲。文（_Sentence）を _Body にする。"""

    def __init__(self, sides, side, skip_kinds=_BODY_SKIP_KINDS):
        analysis = sides.analyses[side]
        self.rows = analysis["lines"]
        self.skip_kinds = skip_kinds
        spans = sorted((left, right) for left, right, kind in analysis["protected_spans"] if kind in _BODY_MASK_KINDS)
        self.lefts = [left for left, _ in spans]
        self.spans = spans

    def mask(self, text, start):
        """位置 start から始まる text から、伏せる範囲を除いた文字列。"""
        end = start + len(text)
        first = max(0, bisect_right(self.lefts, start) - 1)
        pieces, cursor = [], start
        spans = self.spans
        # self.spans[first:] と切り出すと、文ごとに残りの範囲をすべて写すことになる（伏せる範囲の多い文書で2乗）。番号でたどる。
        for index in range(first, len(spans)):
            left, right = spans[index]
            if left >= end:
                break
            if right <= start:
                continue
            if left > cursor:
                pieces.append(text[cursor - start:left - start])
            cursor = max(cursor, right)
        if cursor == start:
            return text
        if cursor < end:
            pieces.append(text[cursor - start:])
        return "".join(pieces)

    def kind(self, sentence):
        """文の行の種類（paragraph、heading など）。行がなければ None。"""
        index = sentence.line - 1
        return self.rows[index]["kind"] if index < len(self.rows) else None

    def body(self, sentence):
        index = sentence.line - 1
        if index < len(self.rows) and self.rows[index]["kind"] in self.skip_kinds:
            return None
        return _Body(self.mask(sentence.text, sentence.start), sentence.text, sentence.line, sentence.start)


def _all_bodies(sides, side, masker=None):
    """文書全体の数える文（コード、表、見出しなどを除き、伏せる範囲を除いたもの）。"""
    masker = masker or _Masker(sides, side)
    sentences = _line_sentences(sides, side, 0, len(sides.lines[side]))
    return [body for body in (masker.body(sentence) for sentence in sentences) if body is not None and body.text.strip()]


# ---- 否定対比の主張の逆転（kind contrast_reversal）----
# 原文の変わった塊の文から、否定対比の節（「Aではなく」「Aではない」「Aじゃない」など）の名詞を取り出す。推敲後の文（変わった文
# だけ）で、その名詞が否定のない節に出て、重みを置く語（目的、狙い、重要、まず、第一に など）と同じ文にあれば候補にする。
# 試作を移した。拾えない形があってもよい。
# diff の詰めの直し（反証で見つけた例）で、重みの語がなくても
# A を並べて肯定する形（「Aだけでなく」「Aに加え」「AとB」）を拾い、比べて下げる形（「Aの代わりに」「Aを書く前に」「Aは後にする」
# 「Aは見送る」など）と、原文の同じ文に A がもともと肯定で出る形を出さないようにした。

# 否定対比の印（「Aではなく」「Aではない」「Aじゃない」「Aでもなく」「Aでなく」「Aではありません」と、diff の詰めの直しで
# 足した「Aは使わず」「Aはせず」（反証で見つけた例。正しい推敲の組で誤検出が増えないことを測って足した）
_CONTRAST = re.compile(r"(?:では|じゃ|でも)(?:なく(?:て)?|ない|なかっ|ありません)|でなく(?:て)?|は(?:使わ|せ)ずに?")
# 「Aは使わず」「Aはせず」の印
_ZU_MARK = re.compile(r"は(?:使わ|せ)ず")
# 「Aだけでなく」「Aばかりではなく」「Aのみでなく」（A に加えて B も）。否定対比の印のすぐ前がこれなら、A を否定していない
_NOT_ONLY = ("だけ", "ばかり", "のみ")
# 反語と推量（「キャッシュではないか」「〜ではないでしょうか」）は否定にしない
_RHETORICAL = re.compile(r"(?:ない|ありません)(?:か|でしょうか|だろうか|かと|のか)")
# 「ではない」のあとの理由や条件の節（「まだ本番環境ではないので、まず検証環境で試します」）。対比ではないので名詞を取らない
_SUBORDINATE = re.compile(r"(?:た)?(?:ので|から|ため|場合|とき|時|なら|限り|かぎり)")
# 節の切れ目（表のセルの区切りの「|」も切れ目にする。見出しと表の中の否定対比も見るため）
_CLAUSE_BREAK = re.compile(r"[、。，,．！？!?「」『』（）()：:\n|｜]")
# 主題の「は」（直前が仮名でない、直前が の・に・と・で、または直後が仮名でない）。否定の節はこのあとから数える
_TOPIC = re.compile(r"(?:(?<=[^ぁ-ゖ])|(?<=[のにとで]))は|は(?=[^ぁ-ゖ])")
_OKURI_MID = "りきけしみえちびれげせじつ"
_OKURI_TAIL = "りきけしみえちびれげせじ"
# 否定対比の名詞では、平仮名の入る和語の名詞（見た目、使い方、締め切り、言い方）も取る（反証で見つけた例: 「見た目ではなく」を
# 「見た目と」にした逆転を見逃していた。誤検出の組と合成の組で、正しい推敲への候補が増えないことを測って入れた）。硬化の名詞の
# 数え方（_NOUN、_KANGO）は変えない
_TOKEN_OKURI_MID = _OKURI_MID + "たいめわ"
# 名詞（2字以上の漢字の並び、送り仮名を挟む漢字の語、2字以上の片仮名、英字の語）
_TOKEN = re.compile("[" + _K + "]+(?:[" + _TOKEN_OKURI_MID + "][" + _K + "]+)*(?:[" + _OKURI_TAIL + "]|(?<=[" + _K + "])[さみ](?![ぁ-ゖ]))?"
                    "|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9_.+#-]+")
# 重みを置く語。はじめの5つ（目的、狙い、重要、まず、第一に）に、似た働きの語を足したもの（試作で、5つだけでは逆転の30組中21組しか拾えなかった）
CONTRAST_WEIGHTS = ("目的", "狙い", "重要", "まず", "第一に", "ねらい", "狙っ", "狙う", "主眼", "主目的", "主な", "最優先",
                    "優先", "何より", "最も", "一番", "重視", "重点", "大事", "大切", "目指", "筆頭", "中心")
# 名詞として数えない語（重みの語と、どこにでも出る語）
_STOP_TOKENS = frozenset(CONTRAST_WEIGHTS + ("場合", "部分", "程度", "意味", "自体", "以上", "以下", "全部", "全体", "一部",
                                             "問題", "必要", "ところ", "もの", "こと"))
# 名詞のあとから節の終わりまでに、これがあれば「否定のある節」とみなす（否定、除外、比べて下げる）。
# 下げる語の その次、二番手、二番目、脇に置く、脇役、添え物、おまけ、どうでも、そのあとに回す は、A を下げたまま言い換えた
# 正しい推敲（品質が最優先で、締め切りはその次です）を逆転の候補にしていたので足した（反証で見つけた例。本当の逆転を
# 見逃さないことを測って入れた）。すぐ前が は・も・が・を のときだけ（Aはその次、Aを脇に置く。_DEMOTE_WORD）。「Aを重視して
# その次に Bを見る」の「その次」は A を下げていない。A のあとから下げる語の前までの字が、別の名詞に は・も・が・を が続く形で
# 終われば、下げたのは A でない（_DEMOTE_WORD_OTHER。「品質を最優先にして速度はその次にする」「最優先は速度で品質はその次」
# 「品質を第一に速度はその次」「見た目は大事だが中身はおまけだ」「品質を最優先にしてほかはその次」は A の逆転。反証で見つけた例）。
# 別の名詞とみなすのは、で・て・にし・し のあとの名詞（「の〜」の句を挟んでよい）と、に・が・けど・から・ので のあとの名詞
# （「の〜」を挟まない。「コストが原因の不具合はその次」の「原因」を別の名詞にしないため）。名詞は漢字・片仮名・英数字の並びと、
# ほか・それ・あと・これ。A の句の中の動詞の活用や「で」の句（見た目の話し合いはその次、見た目で悩むのはその次）は別の名詞に
# しない（反証で見つけた例）。読点を挟んだ「Aは、その次に」は見ない
_NEG_AFTER = re.compile(r"(?:では|じゃ|でも)な|でな[くい]|ではありません|ない|なく|なかっ|ません"
                        r"|以外|を除|を除い|抜き|不要|二の次|後回し")
_DEMOTE_WORD = re.compile(r"(?<=[はもがを])(?:その次|二番手|二番目|脇に置|脇役|添え物|おまけ|どうでも|そのあとに回)")
_OTHER_NOUN = "(?:[" + _K + "ァ-ヴーA-Za-z0-9]+|ほか|それ|あと|これ)"
_DEMOTE_WORD_OTHER = re.compile("(?:(?:で|て|にし|し)" + _OTHER_NOUN + "(?:の[^、。はもがを]{1,12})?"
                                "|(?:に|が|けど|から|ので)" + _OTHER_NOUN + ")[はもがを]$")
# 語で否定した節（AとBは対象外、Aは非対応、Aは範囲外 など）も否定のある節にする（反証で見つけた例）。ただし、A と並べた
# 別の名詞の句の語（「AとXの廃止」の「廃止」は X のもの。A のすぐあとが並べる語で、語の直前が「の」、間に「は」「も」「が」が
# ない）は数えない（反証で見つけた例。「性能改善と古いAPIの廃止」）。_neg_after
_LEXICAL_NEG = re.compile(r"対象外|範囲外|適用外|非対応|未対応|無効|廃止|禁止|除外|据え置")
_COORD_HEAD = re.compile(r"と|や|及び|および|並びに|ならびに|・")
_TOPIC_MARKS = re.compile(r"[はもが]")
# 打ち消しの「ず」（狙わず、使わずに、せず、求めずに）。直前は動詞の未然形の仮名、直後は読点・句点・文末・「に」・漢字・片仮名・
# 英字。副詞の「まず」、「必ず」、「とりあえず」「かならず」、「少しずつ」「わずか」「はず」は打ち消しにしない
_ZU_PREV = frozenset("わかさたなまらがばぱせけげてでねべめれえきぎしじちにびみりい")
_ZU_NEXT = re.compile("[、。，．" + _K + "ァ-ヴA-Za-zＡ-Ｚａ-ｚ]|に")
# 比べて下げる形（名詞のあとから節の終わりまでにあれば、A を下げたとみなす）。「Aより」と、diff の詰めの直しで足した
# 「Aの代わりに」「Aに代わり」「Aに替えて」「Aから B に切り替え・移行・置き換え」「Aを書く前に」「Aの前に」「Aは後にする」
# 「Aはあとで」「Aは後日」「Aは次回」「Aは見送る」「Aは保留」「Aを控える」「Aを避ける」「Aをやめる」「Aを止める」。
# 「前に」は動詞の終止形か「の」のあとだけにする（「Aを前に進める」「Aを前に出す」は A を進める形）。「後に」「後で」「あとに」
# 「あとで」は「Aは後に」「Aを後で」「（Aはあと）」の形だけにする（「Aを出した後に」は A を先にする形）。「次回も」は A を続ける形
# なので除く。
# diff の詰めの直しのあとの反証（反証で見つけた例）で、動詞・名詞の下げる語の形を狭めた: 「止め」は複合動詞の「突き止め」
# 「食い止め」「受け止め」「引き止め」と「歯止め」を除く。「やめ」は「はやめに」（早めに）を除く。「控え」は「来週に控え」（間近に
# 迫る）を除く。「次回」は「次回から」（A を次回から始める）を除く。ただし「次回からにする」「次回からとする」（A を次回に回す）は
# 下げる形のまま（反証で見つけた例）。「Aは後に」は「後にする」「後に回す」の形だけにする（副詞の「後に（のちに）」を除く）。
# さらに _DEMOTE_ANCHORED の語は、下げたのが A でないと分かる形を除く（_demoted）。
# 「Aは減らす」（打ち合わせは減らす）は、反証で見つけた例で足した。「Aを減らすことを最優先にする」の「を減ら」は、A が目的の
# 主題なので下げた形にしない（「は減ら」だけにした）。「は減ら」は A のすぐあと（送り仮名2字まで）だけで見る（「Aを最優先にして
# 文書は減らす」の「は減ら」は別の語のもの。反証で見つけた例）。「Aは減らすことを最優先にする」「Aは減らすことが目的だ」のように、
# 同じ節の「は減ら」のあとに重みの語があれば、A を減らすことを主張しているので下げた形にしない（_demoted。反証で見つけた例）。
# 「Aを B に置き換える・切り替える・移す・移行する・乗り換える・置換する・入れ替える・差し替える・変更する・改める・転換する」
# 「Aを B で置き換える」と、「Aは」「Aも」の同じ形も下げた形（「まず、外部の認証を自前の認証に置き換える」「## 最優先は、
# 手作業を自動化に置き換えること」「まず、手作業は自動化に置き換える」。反証で見つけた例）。A のすぐあと（「Aの〜」の句と、
# 「グローバル変数」の「変数」のように A に続く語の字を挟んでよい）の「を」「は」「も」から見る。「B を A に置き換える」の A は
# 置き換えた先なので当たらない。ただし、置き換え先が A を前に出す先（_PROMOTE_TO。本番、有効、先頭、上位、既定 など）のときと、
# 「を」「は」「も」のすぐあとが A を使う句（_USE_A。Aを使う構成に、Aを中心にした運用へ、Aを軸にした契約へ）のときは、A を採る
# 形なので下げた形にしない（「まず、新機能を本番に移す」「最優先は、クラウドを使う構成に移行することだ」は逆転。反証で見つけた例）。
# 置き換え先を言わない「Aを自動化する」「Aを減らす」「Aを絞る」は、A を目的にする言い方と分けられないので入れていない。
# 読点を挟んだ「Aを、B に置き換える」と「Aを B に変える」も入れていない
_PROMOTE_TO = "".join("(?<!" + word + ")" for word in ("本番", "有効", "先頭", "上位", "主力", "正式", "標準", "既定", "中心",
                                                       "主軸", "前面", "最初", "一番", "トップ", "優先", "オン"))
_USE_A = "(?!使|用い|中心|基本|軸|前提|主体|活か|生か|ベース|重視|優先)"
_DEMOTE_REDUCE = "は減ら"
_DEMOTE = re.compile(r"(?<!に)より|の代わり|に代わ|に替え|から[^、。]{0,12}?(?:切り替|切替|移行|移し|乗り換|置き換)"
                     "|^[" + _K + "ァ-ヴーA-Za-z0-9]{0,8}(?:[ぁ-ゖ]{0,2}|の[^、。をはもがでにへと]{0,12})[をはも]" + _USE_A
                     + "[^、。を]{1,12}?(?:" + _PROMOTE_TO + "[にへ](?:切り替|切替|移行|移[しす]|乗り換|置き換|置換|入れ替|差し替"
                     "|変更|改め|転換)|で置き換)"
                     r"|(?:[うくぐすつぬぶむる]|の)前に|[はをも](?:後|あと)(?:に(?:し|す|回|まわ)|で|$)|後日|後回し"
                     r"|次回(?!も|から(?![にと]))|見送|保留|(?<!に)控え|避け|(?<!は)やめ|はやめ(?!に)"
                     r"|(?<!突き)(?<!食い)(?<!受け)(?<!引き)(?<!歯)止め|^(?:[ぁ-ゖ]{0,2}|の(?:数|回数|件数|時間|量|頻度|割合))は減ら")
# 「Aは減らすこと」「Aは減らすのが」（A を減らすことそのものを言う形）。このときだけ、あとの重みの語を「減らす」の重みとみなす
_REDUCE_ITSELF = re.compile(r"[ぁ-ゖ]{0,5}?(?:こと|の(?=[がはを]))")
# 動詞・名詞の下げる語（見送る、保留、控える、避ける、やめる、止める、次回、後日、Aは後にする）。A と下げる語の間に、別の名詞に
# 付いた「を」があれば、下げたのは A ではない（「移行で障害を避ける」「移行は障害を避ける」。反証で見つけた例）。A の句
# （「Aの追加」「Aの〜」）のあとの最初の助詞より後ろの「を」だけを見る。「ことを」「のを」は A の句の続きなので見ない。
# 1回目の直しでは、A の句に「を」「は」「も」と短い語が続く形に丸ごと当たるときだけ数えたが、「新機能は今回のリリースでは見送り」
# 「契約社員への適用は見送る」「原因に関する調査は後日」「キャッシュを本番で使うのは避け」のように、A を下げたままの言い換えを
# 逆転の候補にした（反証で見つけた例）ので、下げたのが A でないと分かる形だけを除く形にした（_other_object）。
# 「より」「の代わり」「に代わ」「に替え」「から〜切り替」「前に」は A のすぐあとに出る形なので、この条件をかけない
_DEMOTE_ANCHORED = re.compile(r"見送|保留|控え|避け|やめ|止め|次回|後日|[はをも](?:後|あと)")
_A_PHRASE = re.compile(r"の[^、。をはもがでにへと]{0,12}")
_OTHER_OBJECT = re.compile(r"(?<!こと)(?<!の)を")
# 「XをAに替える」「XがAに代わる」の A は置き換えた先（下げた形でない）。A のすぐあとの「に替え」「に代わ」で、節の A より前に
# 「を」「が」「から」があれば、下げた形とみなさない
_SWITCH_TO = re.compile(r"に(?:替え|代わ)")
_SWITCH_FROM = re.compile(r"[をが]|から")
# 否定対比の逆転で文として数えない行の種類。硬化の数え方（_BODY_SKIP_KINDS）と違い、見出しと表の中も見る（反証で見つけた例。
# 技術記事やスライドの見出しの「AではなくB」。コーパス48組、keep の組、正しい推敲の組で誤検出が増えないことを測って入れた）
_CONTRAST_SKIP_KINDS = _BODY_SKIP_KINDS - frozenset(("heading", "table"))
# 推敲後で A のすぐあとがこれなら、A を B と並べて肯定している（重みの語がなくても候補にする）
_ALSO_AFTER = re.compile(r"(?:だけ|ばかり|のみ)(?:では|で|じゃ)なく|のみならず|に加え|に限らず|のほか")
# 推敲後で A のすぐあとの並べる語。引用・言い換え・比べの「と」（という、として、とは、との、と同じ、と違う、となる、
# とする、と呼ぶ、と考える など）は並べる語にしない
_COORD_AFTER = re.compile(r"及び|および|並びに|ならびに|や|・"
                          r"|と(?!い[うっ]|して|しては|は|の|同|違|異|比|な[るりっれ]|す[るれ]|し[たてま]|呼|言|考|思|見|感|聞)")
# 並べた2つを比べた・調べた・選んだ形（「AとBの両方を調べた」「AとBのうち」）。この節にあれば、並べる語の形では候補にしない。
# 「試し」「試す」「試み」は、反証で見つけた残る恐れ（AとBを並べて試した形）を見て、この段で足した。
# 「確かめ」「確認」は、確かめた結果を言う「AとBだと確認」「AとBであることを確認」（結論の言い方）を除く（反証で見つけた例）。1回目の直しでは「を」「の」のすぐあとだけを比べた形にしたが、「AとBを順に確認し」「AとBを再確認した」「AとBも確認し」
# 「AとBは確認済み」「AとBが正しいか確認し」を逆転の候補にした（反証で見つけた例）ので、結論の言い方のほうを除く形にした。
# 「AとBについて確認」も比べた形になる（A を肯定していない文なので、逆転の候補にしない）。「だと再確認」は結論の言い方
_COMPARE_CLAUSE = re.compile(r"のうち|から選|比べ|比較|両方|どちら|いずれ|調べ|(?<!と)(?<!ことを)(?<!ことが)(?<!ことも)(?<!再)再?(?:確かめ|確認)"
                             r"|検討|検証|候補|試[しすみ]")
# 仮説の言い方（「キャッシュを疑ったが」「書き込みが遅いと考えていたが」）。名詞の節にあれば、肯定の主張とみなさない。
# 障害報告で結論を言う決まった言い方の「〜と考えられます」「〜と考えられる」は仮説にしない（反証で見つけた例）
_HYPOTHESIS = re.compile(r"疑|考え(?!られ(?:ます|る))|思っ|思い|予想|想定|見込|仮説|推測|睨")
# 逆接で終わる節（「〜したが、」「〜だけど、」）
_ADVERSATIVE_END = re.compile(r"(?:が|けど|けれど|けれども|ものの|のに|ても|でも)$")
_WEIGHT_PATTERN = re.compile("|".join(r"(?<![" + _K + r"])まず(?!い)" if word == "まず" else re.escape(word)
                                      for word in CONTRAST_WEIGHTS))
# 重みの語だけの句（まず、第一に、何よりも、最優先で、一番に）。見出しと「Aは使わず」「Aはせず」で、A の節の前の節がこれなら、
# A の節の重みとして見る（「## まず、手作業で回す」。反証で見つけた例。前の節に名詞がある「## まず習慣、ツールはその次」は
# 数えない）
_WEIGHT_ONLY_CLAUSE = re.compile(r"^#*\s*(?:まず(?:は)?|第一に|何より(?:も)?|最優先(?:で|として)|一番に)$")


def _neg_after(after, token=""):
    """名詞 token のあと（after。節の終わりまで）が否定のある節か（_NEG_AFTER と、語で否定する語）。
    A のすぐあとの「外」（「対象外」の「対象」を A として取ったとき）は、A が「内」で終わる（国内外、社内外）なら数えない。
    語で否定する語は、A と並べた別の名詞の句の語（「AとXの廃止」）なら数えない（反証で見つけた例）。
    下げる語（_DEMOTE_WORD）は、A のあとから下げる語の前までが別の名詞の句で終わらないときだけ数える。"""
    if _NEG_AFTER.search(after):
        return True
    for found in _DEMOTE_WORD.finditer(after):
        if not _DEMOTE_WORD_OTHER.search(after, 0, found.start()):
            return True
    if after.startswith("外") and not token.endswith("内"):
        return True
    coordinated = _COORD_HEAD.match(after) is not None
    for found in _LEXICAL_NEG.finditer(after):
        if (coordinated and after.endswith("の", 0, found.start())
                and not _TOPIC_MARKS.search(after, 0, found.start())):
            continue
        return True
    return False


def _negative_zu(text):
    """text に打ち消しの「ず」があれば真。"""
    start = 0
    while True:
        i = text.find("ず", start)
        if i < 0:
            return False
        start = i + 1
        prev = text[i - 1] if i > 0 else ""
        if prev not in _ZU_PREV:
            continue
        if prev == "ま" and not (i >= 2 and _STIFF_KANJI.match(text[i - 2])):
            continue          # 副詞の「まず」
        if text[max(0, i - 4):i + 1].endswith(("あえず", "かならず")):
            continue
        if i + 1 == len(text) or _ZU_NEXT.match(text, i + 1):
            return True


def _clause_bounds(text, position):
    """position を含む節の [始め, 終わり)。"""
    left = 0
    for match in _CLAUSE_BREAK.finditer(text, 0, position):
        left = match.end()
    match = _CLAUSE_BREAK.search(text, position)
    return left, (match.start() if match else len(text))


_KATAKANA_HEAD = re.compile(r"[ァ-ヴー]")
_LATIN_HEAD = re.compile(r"[A-Za-z]")


def _is_token(token):
    if token in _STOP_TOKENS:
        return False
    if _KATAKANA_HEAD.match(token) or _LATIN_HEAD.match(token):
        return len(token) >= 2
    if len(token) == 2 and token[1] in "さみ":
        return True     # 速さ、強み（1字の漢字と、名詞を作る さ・み）
    return len(_STIFF_KANJI.findall(token)) >= 2


# 漢字1字の形容詞と名詞（高い品質、長い説明、古い仕組み）。送り仮名に「い」を許したので1つの語として取る（_TOKEN_OKURI_MID）。
# 送り仮名の「い」「た」「め」のあとに2字以上の漢字が続く語（支払い期限、見習い期間、立ち会い検査、得た知識、褒め言葉）も、
# あとの名詞を見る（反証で見つけた例）
_ADJ_NOUN = re.compile("^[" + _K + "]い([" + _K + "].*)$|^.*[いため]([" + _K + "]{2,}.*)$")


def _negated_tokens(sentence):
    """1つの文の否定対比の節から名詞を取り出す。[(名詞, 否定の印, 印の終わりの位置)]。"""
    out = []
    for match in _CONTRAST.finditer(sentence):
        if match.group(0).startswith(("では", "じゃ")) and _RHETORICAL.match(sentence, match.start() + 2):
            continue
        if _SUBORDINATE.match(sentence, match.end()):
            continue
        if sentence[:match.start()].endswith(_NOT_ONLY):
            continue      # 「Aだけでなく」「Aばかりでなく」「Aのみでなく」: A を否定していない
        left = 0
        for brk in _CLAUSE_BREAK.finditer(sentence, 0, match.start()):
            left = brk.end()
        span = sentence[left:match.start()]
        topic_cut = 0
        for topic in _TOPIC.finditer(span):
            topic_cut = topic.end()
        raw_tokens = _TOKEN.findall(span[topic_cut:])
        tokens = [token for token in raw_tokens if _is_token(token)]
        if topic_cut and raw_tokens and all(token in CONTRAST_WEIGHTS for token in raw_tokens):
            # 「共通化は目的ではなく」: は のあとが重みの語だけなら、主題の名詞を取る
            tokens = [token for token in _TOKEN.findall(span[:topic_cut]) if _is_token(token)]
        for token in tokens:
            out.append((token, match.group(0), match.end()))
            noun = _ADJ_NOUN.match(token)
            noun_text = (noun.group(1) or noun.group(2)) if noun is not None else None
            if noun_text is not None and _is_token(noun_text):
                # 「高い品質」「支払い期限」の「品質」「期限」も否定された語として見る（推敲後に名詞だけを肯定した逆転を見逃さない。
                # 反証で見つけた例）
                out.append((noun_text, match.group(0), match.end()))
    return out


# 否定対比の逆転の候補で示す語の送り仮名（取った語のすぐあとから否定の印までの平仮名1〜2字。助詞で始まるものと、2字の助詞
# （など、まで、ほど、しか、さえ、こそ）は除く。ただし「も」「が」に送り仮名の字が続く2字（見積もり、出来上がり）は送り仮名。
# どれも反証で見つけた例）
_SHOWN_TAIL = re.compile("[ぁ-ゖ]{1,2}$")
_SHOWN_TAIL_NOT_HEAD = frozenset("はがをのにとでもへやかよ")
_SHOWN_TAIL_PARTICLES = frozenset(("など", "まで", "ほど", "しか", "さえ", "こそ"))
_SHOWN_TAIL_MO_GA = frozenset("もが")


def _shown_word(text, token, mark_start):
    """候補で示す語。原文の否定の文（text）で、token のすぐあとから否定の印（mark_start）までが送り仮名なら足す
    （「問い合わせ」を「問い合」、「見積もり」を「見積」と途中で切って示さない。「会議など」の「など」は足さない。反証で見つけた例）。
    比べに使う語は token のまま。"""
    head = text[:mark_start]
    tail = _SHOWN_TAIL.search(head)
    if tail is None or not head.endswith(token, 0, tail.start()):
        return token
    kana = tail.group(0)
    if kana in _SHOWN_TAIL_PARTICLES:
        return token
    if kana[0] not in _SHOWN_TAIL_NOT_HEAD or (len(kana) == 2 and kana[0] in _SHOWN_TAIL_MO_GA and kana[1] in _OKURI_TAIL):
        return token + kana
    return token


def _demoted(text, left, position, after):
    """名詞（text の position から）のあと（after。節の終わりまで）に比べて下げる形があれば真。"""
    for match in _DEMOTE.finditer(after):
        if match.start() == 0 and _SWITCH_TO.match(after) and _SWITCH_FROM.search(text, left, position):
            continue      # 「XをAに替える」: A は置き換えた先
        if (match.group(0).endswith(_DEMOTE_REDUCE) and _REDUCE_ITSELF.match(after, match.end()) is not None
                and _WEIGHT_PATTERN.search(after, match.end())):
            continue      # 「Aは減らすことを最優先にする」: A を減らすことが主張（反証で見つけた例）
        if _DEMOTE_ANCHORED.search(match.group(0)) and _other_object(after[:match.start()]):
            continue      # A と下げる語の間に別の目的語がある: 下げたのは A でない（反証で見つけた例）
        return True
    return False


def _other_object(segment):
    """A のあとから下げる語の前まで（segment）に、A の句のあとの最初の助詞より後ろで別の名詞に付いた「を」があれば真
    （「移行で障害を避ける」「移行は障害を避ける」）。「については」「への適用は」「を本番で使うのは」は偽（反証で見つけた例）。"""
    head = _A_PHRASE.match(segment)
    rest = segment[head.end():] if head else segment
    return _OTHER_OBJECT.search(rest, 1) is not None


def _affirmed_with_weight(text, token, clause_only=False, affirmed_side=()):
    """text の中で token が否定のない節に出ていて、重みの語と同じ文にあれば、その位置を返す。なければ None。
    clause_only が真なら、重みの語が token の節そのものか、その節のすぐ前の主題の句（「最優先は、」「一番大事なのは、」。
    節の前の区切りの直前が「は」）か、すぐ前の重みの語だけの句（「まず、」「第一に、」。_WEIGHT_ONLY_CLAUSE）にあるときだけ
    （文のどこかの「まず」では数えない。主題の句と重みの語だけの句は反証で見つけた例）。
    affirmed_side は原文で肯定した側（AではなくBの B）の語。重みの語だけの句から重みを取ったときだけ使い、B の語が同じ節の
    A より後ろに肯定で出れば（_side_affirmed）、A を B に変えた推敲とみなして数えない（「## 手作業ではなく自動化で回す」→
    「## まず、手作業の手順を自動化する」。反証で見つけた例）。"""
    if not _WEIGHT_PATTERN.search(text):
        return None
    start = 0
    while True:
        position = text.find(token, start)
        if position < 0:
            return None
        start = position + 1
        left, right = _clause_bounds(text, position)
        after = text[position + len(token):right]
        clause = text[left:right]
        if _neg_after(after, token) or _negative_zu(after):
            continue
        if _demoted(text, left, position, after):
            continue      # 「Aより」「Aの代わりに」「Aは後にする」などは比べて下げた形
        clause_weight = bool(_WEIGHT_PATTERN.search(clause))
        own_weight = clause_weight
        topic_weight = False
        if clause_only and not clause_weight and left >= 2 and text[left - 2] == "は":
            # 「最優先は、Aを使うことだ」: A の節のすぐ前の主題の句の重みの語も、A の節の重みとして見る
            clause_weight = bool(_WEIGHT_PATTERN.search(text, _clause_bounds(text, left - 2)[0], left - 1))
            topic_weight = clause_weight
        if clause_only and not clause_weight and left >= 2:
            # 「まず、Aで回す」「第一に、Aを使う」: A の節のすぐ前の節が重みの語だけの句なら、A の節の重みとして見る
            clause_weight = _WEIGHT_ONLY_CLAUSE.match(text[_clause_bounds(text, left - 2)[0]:left - 1].strip()) is not None
        if (clause_only and clause_weight and not own_weight and not topic_weight
                and _side_affirmed(text, position, token, right, affirmed_side)):
            continue      # 「## まず、Aの手順をBにする」: 重みの語だけの句のあとで、A を B に変えた
        if clause_only and not clause_weight:
            continue
        if _HYPOTHESIS.search(clause):
            continue      # 「まずAを疑いましたが」: 検証で外れた仮説
        if not clause_weight and _ADVERSATIVE_END.search(clause):
            continue      # 「Aもできますが、目的は…」
        return position


# B の語のすぐあとの、B を置き換えられる側にする言い方（「まず、外部のツールで社内のツールを置き換える」の「社内」。B を肯定した
# のではない。反証で見つけた例）
_SIDE_REPLACED = re.compile("(?:の[^、。をはもがでにへと]{0,12})?を(?:置き換|置換|差し替|入れ替|切り替|切替)")
# B の語のすぐあとの、B を退ける言い方（「まず、手作業で回して自動化を中止する」「まず、会議で決めて文書は省く」の「自動化」「文書」。
# B を肯定したのではない。反証で見つけた例）。B のすぐあとの「を・は・も」に続くときだけ見る（「自動化の漏れを減らす」は B を
# 退けていない）
_SIDE_REJECTED = re.compile("[をはも](?:中止|減ら|省|捨て|廃止|控え|見送|禁止|やめ|止め|取りやめ|なく[さしすせ]|削)")


def _side_affirmed(text, position, token, right, words):
    """text の position にある A（token）の節で、原文で肯定した側の語（words）のどれかが、A より後ろ（節の終わり right まで）に
    肯定で出れば真。「Aの」のすぐあとの語（外部の認証の「認証」）は A の句の一部として見ない。B の語のすぐあとが「も」「にも」
    「でも」のとき（A で回して B も試す）、否定や下げる形のとき、B を置き換えられる側にしたとき（_SIDE_REPLACED）と、B を退ける
    言い方のとき（_SIDE_REJECTED。A で回して B を中止する）は数えない。"""
    for word in words:
        start = position + len(token)
        while True:
            at = text.find(word, start, right)
            if at < 0:
                break
            start = at + 1
            if text[position + len(token):at] == "の":
                continue
            after = text[at + len(word):right]
            if after.startswith(("も", "にも", "でも")):
                continue
            if _neg_after(after, word) or _negative_zu(after) or _demoted(text, position, at, after):
                continue
            if _SIDE_REPLACED.match(after) or _SIDE_REJECTED.match(after):
                continue
            return True
    return False


def _affirmed_plain(text, token, others):
    """重みの語がなくても、text の中で token（A）を B と並べて肯定している位置を返す。なければ None。
    1. A のすぐあとが「だけでなく」「ばかりでなく」「のみならず」「に加え」「に限らず」「のほか」（そのあとに否定がない）。
    2. A のすぐあとが並べる語（と、や、及び、並びに、・）で、原文の同じ文の A 以外の名詞（others）が A より後ろに出る。
       節に否定、比べて下げる形、仮説の言い方、比べた・調べた形（のうち、比べ、両方、調べ、確認、検討 など）があるか、
       節が逆接で終わる（「AとBを試したが、」）なら数えない。"""
    start = 0
    while True:
        position = text.find(token, start)
        if position < 0:
            return None
        start = position + 1
        end = position + len(token)
        left, right = _clause_bounds(text, position)
        after = text[end:right]
        clause = text[left:right]
        if _HYPOTHESIS.search(clause):
            continue
        also = _ALSO_AFTER.match(after)
        if also is not None:
            rest = after[also.end():]
            if not (_neg_after(rest) or _negative_zu(rest)):
                return position
            continue
        if not _COORD_AFTER.match(after) or not any(other in text[end:] for other in others):
            continue
        if (_neg_after(after, token) or _negative_zu(after) or _demoted(text, left, position, after)
                or _COMPARE_CLAUSE.search(clause) or _ADVERSATIVE_END.search(clause)):
            continue
        return position


def _original_affirms(text, token, mark_end, mark_start):
    """原文の否定の文（text）で、名詞 token がもともと肯定で出ているか。重みの語と一緒に否定のない節に出るか、
    否定の印より後ろ（B の側）にも出れば真（「新たに事業を始める者ではなく、既に事業を営んでいる者」の「事業」）。

    B の側の同じ名詞が、どれも直後が「の」（「道具ではなく、道具の使い方」の「道具の」）なら、B の名詞を修飾しているだけで
    A そのものは否定されているので、B の側に出たことでは真にしない。そのときの「重みの語と一緒に肯定で出る」は、否定の節より
    前の所だけで見る（B の側の「道具の使い方だ」と文頭の「大事」を結び付けない。反証で見つけた例）。"""
    rest = text[mark_end:]
    positions = [found.start() for found in re.finditer(re.escape(token), rest)]
    # B の側で、ほかの語に続く複合語の一部（「既存施設の長寿命化」の「施設」）か、直後が「の」でなければ、B の主な語として出る
    if any(not rest.startswith("の", position + len(token)) or _continues_word(rest, position, token)
           for position in positions):
        return True
    if positions:
        left, _ = _clause_bounds(text, max(0, mark_start - 1))
        return _affirmed_with_weight(text[:left], token) is not None
    return _affirmed_with_weight(text, token) is not None


def _continues_word(text, position, token):
    """text の position にある token が、直前の字と続けて1つの語になっているか（直前の字が token の頭の字と同じ字の種類。
    「既存施設」の「施設」、「新ツール」の「ツール」）。"""
    if not position:
        return False
    before, head = text[position - 1], token[0]
    for pattern in (_STIFF_KANJI, _KATAKANA_HEAD, _LATIN_HEAD):
        if pattern.match(head):
            return bool(pattern.match(before))
    return False


def _b_side_phrases(text, token, mark_end):
    """原文の否定の印より後ろ（B の側）の「Aの<名詞>」の句（道具の使い方 の「道具の使」）。推敲後の文でこの句を伏せてから
    A を探す（推敲後も B の側の「道具の使い方」を主張しているだけの文を、A の逆転にしない。反証で見つけた例）。"""
    out = []
    rest = text[mark_end:]
    start = 0
    while True:
        index = rest.find(token + "の", start)
        if index < 0:
            return out
        start = index + 1
        follow = _TOKEN.match(rest, index + len(token) + 1)
        if follow is not None:
            out.append(token + "の" + follow.group(0))


def _head_clue(head):
    """B の側の「Aの<語>」の<語>の手がかり。「使い方」「淹れ方」のような「〜方」は頭の1字（使、淹）、ほかは語そのもの（質）。
    推敲後の文に「Aの<語>」が残っていなくても、手がかりがあれば B の句を言い換えたとみなす（「道具の使い方」→「道具をどう
    使うか」、「データの質」→「質の高いデータ」。反証で見つけた例）。"""
    return head[0] if len(head) >= 2 and head.endswith("方") else head


def _contrast_risks(sides, groups):
    """否定対比の主張の逆転（kind contrast_reversal。--fail-on=meaning-risk には数えない）。

    推敲後の文を探す範囲: 原文の否定の文に組があれば、組になった推敲後の文だけ。組がなければ（文を割った、まとめた）、
    同じ塊の変わった文すべて。原文と同じ文は見ない。推敲後の文と組になった原文の文で、同じ名詞がもともと重みの語と一緒に
    肯定で出ていれば出さない（もともとの主張）。原文の否定の文そのものの中でも同じ（重みの語と肯定で出るか、B の側にも出る）。
    推敲後の文では、重みの語と同じ文で否定のない節に出るか（_affirmed_with_weight）、重みの語がなくても B と並べて肯定する
    形（_affirmed_plain）なら候補にする。"""
    out = []
    order = 0
    maskers = None
    for group in groups:
        if group["hunk"]["tag"] == "insert" or not group["old"] or not group["new"]:
            continue
        if not any(_CONTRAST.search(sentence.text) for sentence in group["old"]):
            continue
        if maskers is None:
            maskers = (_Masker(sides, 0, skip_kinds=_CONTRAST_SKIP_KINDS), _Masker(sides, 1, skip_kinds=_CONTRAST_SKIP_KINDS))
        new_for_old, old_for_new = {}, {}
        for i, j in group["pairs"]:
            new_for_old.setdefault(i, []).append(j)
            old_for_new[j] = i
        old_texts = set(sentence.text for sentence in group["old"])
        seen = set()
        for i, sentence in enumerate(group["old"]):
            body = maskers[0].body(sentence)
            if body is None:
                continue
            heading = maskers[0].kind(sentence) == "heading"
            tokens = [item for item in _negated_tokens(body.text)
                      if not _original_affirms(body.text, item[0], item[2], item[2] - len(item[1]))]
            if not tokens:
                continue
            negated = set(token for token, _, _ in tokens)
            others = [token for token in _TOKEN.findall(body.text) if token not in negated and _is_token(token)]
            targets = new_for_old[i] if i in new_for_old else range(len(group["new"]))
            for j in targets:
                new_sentence = group["new"][j]
                new_body = maskers[1].body(new_sentence)
                if new_body is None or new_body.raw in old_texts:
                    continue
                for token, mark, mark_end in tokens:
                    probe = new_body.text
                    phrases = _b_side_phrases(body.text, token, mark_end)
                    if any(phrase not in probe and _head_clue(phrase[len(token) + 1:]) in probe for phrase in phrases):
                        continue      # 「道具の使い方」→「道具をどう使うか」: B の句の言い換え（反証で見つけた例）
                    for phrase in phrases:
                        probe = probe.replace(phrase, "\uff3f" * len(phrase))
                    # 見出しの行と「Aは使わず」「Aはせず」から取った名詞は、A の節そのものの重みの語だけを見る（文のどこかの
                    # 「まず」では数えない。「## ツールではなく習慣から変える」→「## まず習慣、ツールはその次」。反証で見つけた例）
                    narrow = heading or _ZU_MARK.match(mark) is not None
                    # 原文で肯定した側（否定の印より後ろ）の語。重みの語だけの句のあとで A を B に変えた推敲を見分ける
                    side = [word for word in _TOKEN.findall(body.text[mark_end:]) if _is_token(word) and word not in negated]
                    if (_affirmed_with_weight(probe, token, narrow, side) is None
                            and _affirmed_plain(probe, token, others) is None):
                        continue
                    paired = old_for_new.get(j)
                    if paired is not None and paired != i:
                        other = maskers[0].body(group["old"][paired])
                        if other is not None and _affirmed_with_weight(other.text, token) is not None:
                            continue
                    key = (body.line, new_body.line, token)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((_group_index(group, new_sentence), order, _risk(
                        "contrast_reversal", None, body.line, new_body.line, body.raw, new_body.raw,
                        {"word": _shown_word(body.text, token, mark_end - len(mark)), "mark": mark})))
                    order += 1
    return out


# ---- 気持ちの創作（kind feeling）----
# 元の文書のどこにもない気持ちの語（ほっとした、安堵した、うれしかった…）が、推敲後の変わった文に足されたら候補にする。
# 一覧は references/lists/feelings.txt（語の家族ごとに「名前<TAB>正規表現」。3つ目の欄は原文の言い方で、原文にあればその家族の
# 気持ちは原文にあるとみなす）。--fail-on=meaning-risk には数えない。

def _feeling_risks(sides, groups):
    patterns, _ = _load_list("feelings")
    if not patterns or not any(group["new"] for group in groups):
        return []
    # 原文にない家族だけを見る。3つ目の欄（原文の言い方）が原文に当たる家族も、原文にある気持ちとみなす。
    # 速さの直し（結果は同じ）: 原文を家族ごとに調べるのは、推敲後の変わった文に当たった家族だけにする（多くの文書では
    # 気持ちの語のある変わった文がないので、原文を調べずに済む）。変わった文は、気持ちの語の一覧のどれにも当たらなければ、
    # 1つにまとめた正規表現（_any_of）で先に見分けて飛ばす
    found = {}

    def absent(index):
        if index not in found:
            if "original" not in found:
                old_masker = _Masker(sides, 0, skip_kinds=frozenset(("code", "frontmatter", "html_block")))
                found["original"] = "\n".join(
                    old_masker.mask(line, sides.starts[0][number]) for number, line in enumerate(sides.lines[0])
                    if not (number < len(old_masker.rows)
                            and old_masker.rows[number]["kind"] in ("code", "frontmatter", "html_block")))
            original, item = found["original"], patterns[index]
            found[index] = not item[1].search(original) and not (len(item) > 2 and item[2].search(original))
        return found[index]
    masker = _Masker(sides, 1, skip_kinds=frozenset(("code", "frontmatter", "html_block", "table")))
    combined = _any_of(patterns)
    out = []
    order = 0
    for group in groups:
        if not group["new"]:
            continue
        old_texts = set(sentence.text for sentence in group["old"])
        old_for_new = dict((j, i) for i, j in group["pairs"])
        for j, sentence in enumerate(group["new"]):
            if sentence.text in old_texts:
                continue
            body = masker.body(sentence)
            if body is None:
                continue
            if combined is not None and combined.search(body.text) is None:
                continue
            words = []
            for index, item in enumerate(patterns):
                match = item[1].search(body.text)
                if match is not None and match.group(0) not in words and absent(index):
                    words.append(match.group(0))
            if not words:
                continue
            paired = old_for_new.get(j)
            old = group["old"][paired] if paired is not None else None
            out.append((_group_index(group, sentence), order, _risk(
                "feeling", None, old.line if old is not None else None, sentence.line,
                old.text if old is not None else None, sentence.text, {"words": words})))
            order += 1
    return out


# ---- 文体の硬化の検査（JSON の stiffness、レポートの「■ 文体の硬化」）----
# 原文と推敲後で、漢字の割合、平均の文の長さ、名詞化の言い回し、「の」の連続を比べ、推敲で硬くなった所を見直し候補にする。
# 意味が変わる恐れには入れず、candidate_count、状態の行、--fail-on にも入れない。どの条件も推敲で増えた分だけを見る
# （原文がもともと硬いだけなら出さない）。文書の種類が formal（公用文、規程、契約書、仕様書）と incident（障害報告）なら
# 参考（level info）。数値は試作で決め直した値。

STIFFNESS_THRESHOLDS = {
    "doc_kanji_pt": 3.0,        # 文書全体: 漢字の割合の増え（ポイント）。試作の最初の値は +5ポイントかつ平均の長さ +5字
    "doc_kanji_up": 2,          # 文書全体: 漢字の字数の増えの下限（前置きや外枠を消すだけの短い推敲を出さない）
    "sent_kanji_pt": 8.0,       # 1文: 漢字の割合の増え（最初の値は +15ポイントかつ字数が増えた）
    "sent_kanji_up": 2,         # 1文: 漢字の字数の増えの下限
    "sent_hira_down": 2,        # 1文: 平仮名の字数の減りの下限
    "sent_nominal_kanji": 2,    # 1文の名詞化: 漢字の字数の増えの下限
    "nominal_delta": 2,         # 名詞化: 文書全体で原文より増えた数の下限（最初の値のまま）
    "no_nouns": 3,              # 「の」の連続: つながる名詞の数の下限
    "no_kango": 3,              # 「の」の連続: つながる名詞のうち漢語（漢字2字以上）の数の下限
}
# 硬化の検査を参考（level info）としてだけ出す文書の種類。incident は diff の詰めの直しで足した（反証で見つけた例。
# v1.1.2 の人間A/Bの好み「報告書では『障害が起きた朝』より『障害が発生した朝』が合う」と、SKILL.md の incident の行（発生、
# 復旧などの報告の語の規則を当てない）に合わせる）。並びは DOC_TYPES の順
STIFFNESS_INFO_DOC_TYPES = ("incident", "formal", "paper")
_HIRAGANA_CHARS = re.compile("[ぁ-ゖ]")
# 「の」の連続の名詞（漢字・片仮名・英数字の並び。漢字の間の送り仮名を1字ずつ許す。助詞になりうる仮名は送り仮名にしない）。
# 量指定子を入れ子にしない（入れ子にすると長い名詞の並びで後戻りが爆発する）
_NOUN_CHARS = "[" + _K + "ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ]"
_NOUN = (_NOUN_CHARS + "+(?:[" + _OKURI_MID + "](?=[" + _K + "])" + _NOUN_CHARS + "+)*"
         "(?:[" + _OKURI_TAIL + "](?=の))?")
_NO_CHAIN = re.compile("(?<!" + _NOUN_CHARS + ")" + _NOUN + "(?:の" + _NOUN + "){2,}")
_KANGO = re.compile("^[" + _K + "]+(?:[" + _OKURI_MID + "][" + _K + "]+)*[" + _OKURI_TAIL + "]?$")


# 文字と数字（Unicode の分類が L か N の字。Python の \w から「_」を除いたもの）と、長さに数える句読点とかっこ
_LETTER_OR_DIGIT = re.compile(r"[^\W_]")
_LENGTH_PUNCT_PATTERN = re.compile("[" + re.escape("".join(sorted(_LENGTH_PUNCT))) + "]")


def _measure(text):
    """(文の長さ, 漢字の数, 記号と空白を除いた字数)。文の長さは文字・数字と句読点・かっこの字数。"""
    counted = len(_LETTER_OR_DIGIT.findall(text))
    return counted + len(_LENGTH_PUNCT_PATTERN.findall(text)), len(_STIFF_KANJI.findall(text)), counted


def _ratio(kanji, counted):
    return 100.0 * kanji / counted if counted else 0.0


def _nominal_hits(text, patterns):
    """名詞化の言い回しの当たり [(始め, 終わり, 名前)]。重なった当たりは1つにする（先に始まり、長いほうを残す）。
    どの言い回しも当たらない文は、1つにまとめた正規表現（_any_of）で先に見分けて飛ばす（結果は同じ。速さの直し）。"""
    combined = _any_of(patterns)
    if combined is not None and combined.search(text) is None:
        return []
    hits = []
    for name, regex in patterns:
        for match in regex.finditer(text):
            hits.append((match.start(), match.end(), name))
    hits.sort(key=lambda hit: (hit[0], -(hit[1] - hit[0])))
    kept, last_end = [], -1
    for hit in hits:
        if hit[0] >= last_end:
            kept.append(hit)
            last_end = hit[1]
    return kept


# 漢数字で始まる語（一日、一回、三つ）。「の」の連続の漢語に数えない（「工場の最後の一日」は普通の言い方。diff の詰めで、
# 評価用の文の比喩を直した推敲で測って足した）
_NUMERAL_HEAD = re.compile("[〇一二三四五六七八九十百千万]")


def _no_chains(text):
    """「の」の連続（名詞3つ以上で、3つとも漢語）。漢数字で始まる語は漢語に数えない。"""
    out = []
    for match in _NO_CHAIN.finditer(text):
        chain = match.group(0)
        kango = sum(1 for part in chain.split("の")
                    if _KANGO.match(part) and len(_STIFF_KANJI.findall(part)) >= 2 and not _NUMERAL_HEAD.match(part))
        if kango >= STIFFNESS_THRESHOLDS["no_kango"]:
            out.append(chain)
    return out


def _metrics_of(bodies, patterns, memo=None):
    """数える文の並びの値。memo（文 → 値の dict）を渡すと、同じ文の値を1回だけ求める（元と推敲後で変わらない文が多いため。
    速さの直し。結果は同じ）。"""
    length = kanji = counted = 0
    nominal = Counter()
    chains = 0
    for body in bodies:
        text = body.text
        values = memo.get(text) if memo is not None else None
        if values is None:
            values = _measure(text) + ([name for _, _, name in _nominal_hits(text, patterns)], len(_no_chains(text)))
            if memo is not None:
                memo[text] = values
        a, b, c, names, chain_count = values
        length, kanji, counted = length + a, kanji + b, counted + c
        for name in names:
            nominal[name] += 1
        chains += chain_count
    sentences = len(bodies)
    return {"sentences": sentences, "chars": length,
            "avg_sentence_length": round(length / sentences, 2) if sentences else 0.0,
            "kanji_ratio": round(_ratio(kanji, counted), 2), "kanji": kanji,
            "nominalizations": sum(nominal.values()), "nominalization_names": dict(sorted(nominal.items())),
            "no_chains": chains}


def stiffness_metrics(text):
    """1つの文書の値（漢字の割合、平均の文の長さ、名詞化の言い回し、「の」の連続。検査の記録に残す形）。コード、URL、表、見出しは数えない。"""
    patterns, _ = _load_list("nominalization")
    sides = _Sides(text, text)
    return _metrics_of(_all_bodies(sides, 0), patterns)


_EXCERPT_BREAK = "、。，！？!?"


def _changed_excerpt(old, new, width=40):
    """2つの文の変わった所を、読点か句点で区切った節の単位で出す（最初に変わった節から最後に変わった節まで）。"""
    head, tail = _common_affix(old, new)

    def clause(text, left, right):
        while left > 0 and text[left - 1] not in _EXCERPT_BREAK:
            left -= 1
        while right < len(text) and text[right - 1:right] not in tuple(_EXCERPT_BREAK) and text[right] not in _EXCERPT_BREAK:
            right += 1
        part = text[left:right].strip("、，")
        return part if len(part) <= width else part[:width] + "…"
    return clause(old, head, max(head, len(old) - tail)), clause(new, head, max(head, len(new) - tail))


def _stiff_candidate(subkind, old_line, new_line, old, new, detail, level):
    return {"kind": "stiffness", "subkind": subkind, "old_line": old_line, "new_line": new_line,
            "old": old, "new": new, "detail": detail, "level": level}


def stiffness(orig, rw, doc_type=None):
    """文体の硬化の検査（JSON の stiffness と同じ形）。doc_type は文書の種類（incident と formal なら参考）。"""
    full, sides = _build_full_diff(orig, rw, None)
    return _stiffness(sides, full, _sentence_pairs(sides, full), normalize_doc_type(doc_type))


def _stiffness(sides, full, groups, doc_type):
    patterns, source = _load_list("nominalization")
    level = "info" if doc_type in STIFFNESS_INFO_DOC_TYPES else "review"
    limits = STIFFNESS_THRESHOLDS
    maskers = (_Masker(sides, 0), _Masker(sides, 1))
    old_bodies = _all_bodies(sides, 0, maskers[0])
    memo = {}
    old_m = _metrics_of(old_bodies, patterns, memo)
    out = []
    if sides.texts[0] == sides.texts[1] or not full["hunks"]:
        return {"level": level, "candidate_count": 0, "candidates": [], "metrics": {"old": old_m, "new": old_m},
                "list": source, "list_problem": _LIST_PROBLEMS.get("nominalization")}
    new_bodies = _all_bodies(sides, 1, maskers[1])
    new_m = _metrics_of(new_bodies, patterns, memo)

    # 文の組（変わった文だけ）。組にならない文は、置き換えの塊ごとにまとめて1つの組にする（文全体を書き換えた推敲）
    pairs = []
    for group in groups:
        for i, j in group["pairs"]:
            o, n = maskers[0].body(group["old"][i]), maskers[1].body(group["new"][j])
            if o is None or n is None or o.raw == n.raw:
                continue
            pairs.append((o, n))
        if group["hunk"]["tag"] == "replace":
            paired_old = set(i for i, _ in group["pairs"])
            paired_new = set(j for _, j in group["pairs"])
            rest_old = [b for b in (maskers[0].body(s) for k, s in enumerate(group["old"]) if k not in paired_old) if b]
            rest_new = [b for b in (maskers[1].body(s) for k, s in enumerate(group["new"]) if k not in paired_new) if b]
            if rest_old and rest_new:
                pairs.append((_Body("".join(b.text for b in rest_old), "".join(b.raw for b in rest_old),
                                    rest_old[0].line, rest_old[0].start),
                              _Body("".join(b.text for b in rest_new), "".join(b.raw for b in rest_new),
                                    rest_new[0].line, rest_new[0].start)))
    values = {}

    def sentence_values(o, n):
        key = (o.start, n.start, len(o.text), len(n.text))
        if key not in values:
            ol, ok, oc = _measure(o.text)
            nl, nk, nc = _measure(n.text)
            values[key] = (ol, nl, _ratio(ok, oc), _ratio(nk, nc), ok, nk)
        return values[key]

    def hiragana(text):
        return len(_HIRAGANA_CHARS.findall(text))

    # 1文の条件: 漢字の割合 +8ポイント以上、漢字 +2字以上、平仮名 -2字以上
    reported = set()
    for o, n in sorted(pairs, key=lambda pair: pair[1].start):
        ol, nl, orr, nrr, ok, nk = sentence_values(o, n)
        if nrr - orr < limits["sent_kanji_pt"] or nk - ok < limits["sent_kanji_up"]:
            continue
        if hiragana(o.text) - hiragana(n.text) < limits["sent_hira_down"]:
            continue
        reported.add((n.line, n.raw))
        out.append(_stiff_candidate("sentence", o.line, n.line, o.raw, n.raw,
                                    {"old_kanji_ratio": round(orr, 1), "new_kanji_ratio": round(nrr, 1),
                                     "old_length": ol, "new_length": nl}, level))
    # 1文の名詞化: 変わった文に、組の原文の文になかった名詞化の言い回しが出て、漢字が2字以上増えた
    for o, n in sorted(pairs, key=lambda pair: pair[1].start):
        added = Counter(name for _, _, name in _nominal_hits(n.text, patterns))
        added.subtract(Counter(name for _, _, name in _nominal_hits(o.text, patterns)))
        names = sorted(name for name, value in added.items() if value > 0)
        if not names:
            continue
        ol, nl, orr, nrr, ok, nk = sentence_values(o, n)
        if nk - ok < limits["sent_nominal_kanji"] or (n.line, n.raw) in reported:
            continue
        reported.add((n.line, n.raw))
        out.append(_stiff_candidate("sentence_nominal", o.line, n.line, o.raw, n.raw,
                                    {"added_names": names, "old_kanji": ok, "new_kanji": nk}, level))
    # 文書全体: 漢字の割合 +3ポイント以上、かつ漢字 +2字以上。変わった文の組が2つ以上のときだけ出す（diff の詰めの直し。
    # 反証で見つけた例。組が1つなら文書全体の値はその1文の値と同じ向きに動くので、1文の条件より緩い1文の条件に
    # なり、比喩を具体化した直しに出ていた。1文の書き換えは1文の条件と名詞化の条件で見る）
    if (len(pairs) >= 2
            and new_m["kanji_ratio"] - old_m["kanji_ratio"] >= limits["doc_kanji_pt"]
            and new_m["kanji"] - old_m["kanji"] >= limits["doc_kanji_up"]):
        best = max(pairs, key=lambda pair: sentence_values(*pair)[3] - sentence_values(*pair)[2])
        a, b = _changed_excerpt(best[0].text, best[1].text)
        example = {"old_line": best[0].line, "new_line": best[1].line, "old": a, "new": b}
        out.append(_stiff_candidate("document", None, None, None, None,
                                    {"old_kanji_ratio": old_m["kanji_ratio"], "new_kanji_ratio": new_m["kanji_ratio"],
                                     "old_avg_length": old_m["avg_sentence_length"],
                                     "new_avg_length": new_m["avg_sentence_length"], "example": example}, level))
    # 名詞化の言い回し: 文書全体で原文より2つ以上増えた
    if new_m["nominalizations"] - old_m["nominalizations"] >= limits["nominal_delta"]:
        added = Counter(new_m["nominalization_names"])
        added.subtract(old_m["nominalization_names"])
        names = sorted(name for name, value in added.items() if value > 0)
        where = []
        old_raws = set(body.raw for body in old_bodies)
        for body in new_bodies:
            if body.raw not in old_raws and body.line not in where and _nominal_hits(body.text, patterns):
                where.append(body.line)
        out.append(_stiff_candidate("nominalization", None, where[0] if where else None, None, None,
                                    {"old": old_m["nominalizations"], "new": new_m["nominalizations"],
                                     "added_names": names, "new_lines": where}, level))
    # 「の」の連続が、原文になかった所に出た
    old_chains = set()
    old_raw_set = set(body.raw for body in old_bodies)
    for body in old_bodies:
        old_chains.update(_no_chains(body.text))
    paired_old = {}
    for o, n in pairs:
        paired_old.setdefault(n.start, o)
    for group in groups:
        for sentence in group["new"]:
            n = maskers[1].body(sentence)
            if n is None:
                continue
            chains = _no_chains(n.text)
            if not chains:
                continue
            o = paired_old.get(n.start)
            if o is not None:
                if o.raw == n.raw:
                    continue
                before = _no_chains(o.text)
                # 連続の名詞がすべて組の原文の文にあれば出さない（補足カッコを外しただけの推敲。「営業部（東京本社）の今期の売上」→
                # 「東京本社の営業部の今期の売上」。diff の詰めの直し、反証で見つけた例）。名詞は「の」を含まない
                fresh = [chain for chain in chains if chain not in before
                         and not all(part in o.text for part in chain.split("の"))]
                if len(chains) <= len(before) or not fresh:
                    continue
            else:
                if n.raw in old_raw_set:
                    continue
                fresh = [chain for chain in chains if chain not in old_chains]
                if not fresh:
                    continue
            out.append(_stiff_candidate("no_chain", o.line if o is not None else None, n.line,
                                        o.raw if o is not None else None, n.raw, {"chains": fresh}, level))
    return {"level": level, "candidate_count": len(out), "candidates": out, "metrics": {"old": old_m, "new": new_m},
            "list": source, "list_problem": _LIST_PROBLEMS.get("nominalization")}


# ---- 勢いの検査（JSON の tone、レポートの「■ 勢い」）----
# 文書の種類によらず毎回行う。「！」「!」、「？」「?」、絵文字、強める語の数が原文より減ったら、減った行の前後を並べて候補にする。
# 見出しの字数の合計が原文の7割未満になったら候補にする。コード、URL、表の中は数えない。candidate_count、状態の行、
# --fail-on には入れない。技術文書、障害報告、ヘルプ、公用文に当たる種類（pr、article、incident、manual、formal）では参考。
# diff の詰めの直しで次を変えた。
# - 「！」が同じ段落に3つ以上あれば減っても数えない許しを外した（作者の判断、2026-10-14 朝。紹介記事・宣伝文では「！」を
#   3つ以上並べても減らさない。許しは種類によらず外した）。
# - 種類を指定していて promo でないときは、絵文字と見出しの候補を参考にする（反証で見つけた例）。
# - 「？」の減りは、組になった推敲後の文が間接の問い（「〜かとの質問」「〜かどうか」）なら数えない（反証で見つけた例）。
# - 候補の位置の抜き出しを印のまわり（前後20字）にし、2か所目からも行を並べる（反証で見つけた例）。
# - --doc-type promo のときは、番号つき項目の行と太字だけの行も見出しの字数に数える（反証で見つけた例）。
# 同じ強める語の繰り返しを減らした推敲を数えない案（反証で見つけた例）は採らない（強める語を削らない、減らさないという
# 作者の判断と食い違うため）。

TONE_INFO_DOC_TYPES = ("pr", "article", "incident", "manual", "formal", "paper")
# 種類を指定していて promo でないとき、参考（info）にする候補。絵文字を外す（lint の emoji_prohibited）、文の見出しを短い項目名に
# する（SKILL.md 4章）のは yomiyasu の決まりどおりの直しなので。種類なしは見直し候補のまま（紹介記事を種類の判定で取り違えた
# ときに気づくための検査なので）
TONE_TYPED_INFO_SUBKINDS = ("emoji", "heading")
# TONE_TYPED_INFO_SUBKINDS の候補を参考にしない種類（候補ごと）。promo は絵文字も見出しも残す種類。minutes は推敲で見出しを
# 変えない種類（作者の判断、domains/business.md 3章）なので、見出しの候補は見直し候補のまま
# （diff の詰めの直しのあとの反証で見つけた例）
TONE_TYPED_REVIEW_DOC_TYPES = {"emoji": ("promo", "mail"), "heading": ("promo", "minutes", "mail")}
# 参考の理由の文で、参考にした候補ごとに書く決まり（_detector_section）
_TONE_TYPED_RULES = (("emoji", "絵文字を外し", "絵文字を外す"), ("heading", "見出しを短い項目名にし", "見出しを短い項目名にする"))
# 参考の5種類（TONE_INFO_DOC_TYPES）の理由の文で、参考にした候補ごとに書く直し方（_detector_section。絵文字や見出しだけの候補に
# 「「！」や強める語を減らす」と書かない。反証で見つけた例）
_TONE_INFO_RULES = ((("exclamation", "question", "intensifier"), "「！」や強める語を減らし", "「！」や強める語を減らす"),
                    (("emoji",), "絵文字を外し", "絵文字を外す"),
                    (("heading",), "見出しを短い項目名にし", "見出しを短い項目名にする"))
TONE_HEADING_RATIO = 0.7        # 見出しの字数の合計が、原文のこの割合未満になったら候補にする
TONE_PLACES_SHOWN = 5           # 1つの候補で並べる位置の上限（超えた分は「ほか N か所」）
_TONE_EXCERPT_WIDTH = 20        # 位置の抜き出しの、印の前後の字数
# 間接の問い（「予算が足りるかとの質問」「足りるかという声」「進めてよいかどうか」「足りるか否か」「直せるかと聞かれた」）。
# 「ほかと」「確かと」「何かと」は問いではないので除く。推量の「〜かと思います」「〜かと考え」と、「わずかと」「まさかと」の
# ような語の終わりの「か」に「と」が付いた形も問いではないので、「か」のあとの形を決まった言い方に限る（反証で見つけた例）。
# 「かと」と問う語の間には、句読点を除く6字までを許し（「かとお問い合わせ」「かとよく聞かれ」「かとご相談」）、問う語に「相談」
# 「訊」を足す（反証で見つけた例）
_INDIRECT_QUESTION = re.compile(r"(?<![ほ確何])か(?:との|という|といった|どうか|否か"
                                r"|と[^。、！？!?\n]{0,6}?(?:聞|尋|問|質問|相談|訊|たず|き[いか]))")
_TONE_SKIP_KINDS = frozenset(("code", "frontmatter", "html_block", "table", "reference_definition", "thematic_break",
                              "blank", "heading_underline"))
_TONE_KINDS = ("exclamation", "question", "emoji", "intensifier")
_TONE_LABELS = {"exclamation": "「！」", "question": "「？」", "emoji": "絵文字"}
_EXCLAMATION = re.compile(r"[！!]")
_QUESTION_MARK = re.compile(r"[？?]")
# 強める語の数え方から外す語（「絶対値」「絶対パス」は強める語ではない）
_INTENSIFIER_EXCLUDED = re.compile(r"絶対(?:値|パス|参照|座標|位置|時間|温度|音感|零度|的)")
_ATX_MARKERS = re.compile(r"^[ \t]{0,3}#{1,6}(?:[ \t]+|$)|[ \t]+#+[ \t]*$")
_FALLBACK_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u231A\u231B\u23E9-\u23FA]\uFE0F?")
_EMOJI_FINDER = []
# 絵文字かもしれない字（U+2000 以上で、CJK の文字と記号、全角の英数字と記号を除く）。ない行では lint の数え方を呼ばない
_MAYBE_EMOJI = re.compile("[\u2000-\u2fff\ua000-\ufeff\ufff0-\U0010ffff]")


def _emoji_finder():
    """絵文字の数え方。lint と同じ数え方（yomiyasu_lint.py の Unicode 18.0 の一覧）を使う。lint を読めなければ、
    主な絵文字の範囲だけを見る簡単な数え方にする。"""
    if not _EMOJI_FINDER:
        finder = None
        try:
            module = sys.modules.get("yomiyasu_lint")
            if module is None or not hasattr(module, "_emoji_matches"):
                import importlib.util
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yomiyasu_lint.py")
                spec = importlib.util.spec_from_file_location("_yomiyasu_lint_for_diff", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finder = module._emoji_matches
        except Exception:  # lint がない、読めない。止めずに簡単な数え方にする
            finder = _FALLBACK_EMOJI.findall
        _EMOJI_FINDER.append(finder)
    return _EMOJI_FINDER[0]


def _intensifier_pattern(words):
    words = sorted(set(word for word in words if word), key=len, reverse=True)
    return re.compile("|".join(re.escape(word) for word in words)) if words else None


# 紹介記事・宣伝文で見出しとして書かれることの多い行（「1. 昭和から愛される…」のような番号つきの見出し）。番号つき項目の行
# （「1. …」「2) …」。行頭の空白は3つまで）と、段落の行の全体を太字にした行（「**…**」「__…__」）
_ORDERED_ITEM_LINE = re.compile(r"^[ \t]{0,3}\d{1,9}[.)][ \t]+(.+)$")
_BOLD_ONLY_LINE = re.compile(r"^[ \t]{0,3}(?:\*\*|__)(?![ \t])(.+?)(?<![ \t])(?:\*\*|__)[ \t]*$")


def _pseudo_heading(line, kind):
    """番号つき項目の行と太字だけの行の、見出しとして数える文字列（番号、太字の印を除く）。当たらなければ None。"""
    if kind == "list":
        match = _ORDERED_ITEM_LINE.match(line)
        if match:
            inner = _BOLD_ONLY_LINE.match(match.group(1))
            return inner.group(1) if inner else match.group(1)
    elif kind == "paragraph":
        match = _BOLD_ONLY_LINE.match(line)
        if match:
            return match.group(1)
    return None


def _tone_lines(sides, side, intensifiers, pseudo_headings=False):
    """行ごとの数 {行番号: {"exclamation", "question", "emoji", "intensifier", "words", "heading_chars", "text"}}。
    数えない行（コード、表など）は入れない。行の中のインラインのコード、URL、リンク先、画像、HTML のタグは伏せる。
    pseudo_headings が真なら（--doc-type promo）、番号つき項目の行と太字だけの行も見出しの字数に数える（反証で見つけた例。
    種類なしとほかの種類では、コーパス48組の番号つきの一覧を文章にした推敲などで見出しの候補が4組に出たので数えない）。"""
    masker = _Masker(sides, side, skip_kinds=_TONE_SKIP_KINDS)
    finder = None
    out = OrderedDict()
    for index, line in enumerate(sides.lines[side]):
        kind = masker.rows[index]["kind"] if index < len(masker.rows) else "paragraph"
        if kind in _TONE_SKIP_KINDS:
            continue
        text = masker.mask(line, sides.starts[side][index])
        if not text.strip():
            continue
        counts = {"exclamation": len(_EXCLAMATION.findall(text)), "question": len(_QUESTION_MARK.findall(text)),
                  "emoji": 0, "intensifier": 0, "words": Counter(), "heading_chars": 0, "text": line}
        if _MAYBE_EMOJI.search(text):
            if finder is None:
                finder = _emoji_finder()
            counts["emoji"] = len(finder(text))
        if intensifiers is not None:
            plain = _INTENSIFIER_EXCLUDED.sub(lambda match: "＃" * len(match.group(0)), text)
            for match in intensifiers.finditer(plain):
                counts["words"][match.group(0)] += 1
            counts["intensifier"] = sum(counts["words"].values())
        if kind == "heading":
            counts["heading_chars"] = _heading_chars(_ATX_MARKERS.sub("", line))
        elif pseudo_headings:
            pseudo = _pseudo_heading(line, kind)
            if pseudo is not None:
                counts["heading_chars"] = _heading_chars(pseudo)
        out[index + 1] = counts
    return out


def _heading_chars(text):
    """見出しの字数（空白と絵文字を除く）。絵文字を外しただけの見出しを「見出しが短くなった」に数えない（絵文字の減りは絵文字の
    候補で出る。--doc-type minutes の見出しを見直し候補のままにした直しで、短い見出しの絵文字を外しただけの推敲が見出しの
    見直し候補にならないようにした）。"""
    if _MAYBE_EMOJI.search(text):
        for found in _emoji_finder()(text):
            text = text.replace(found, "", 1)
    return len(_SPACES.sub("", text))


def _mark_spans(text, kind, intensifiers):
    """行の中の、数えた印（「！」「？」、絵文字、強める語）の位置 [(始め, 終わり)]。抜き出しの中心を決めるためだけに使う
    （行は伏せる前の形なので、インラインのコードの中の印も入る）。"""
    if kind == "exclamation":
        return [match.span() for match in _EXCLAMATION.finditer(text)]
    if kind == "question":
        return [match.span() for match in _QUESTION_MARK.finditer(text)]
    if kind == "intensifier":
        if intensifiers is None:
            return []
        plain = _INTENSIFIER_EXCLUDED.sub(lambda match: "＃" * len(match.group(0)), text)
        return [match.span() for match in intensifiers.finditer(plain)]
    if kind == "emoji" and _MAYBE_EMOJI.search(text):
        spans, cursor = [], 0
        for found in _emoji_finder()(text):
            position = text.find(found, cursor)
            if position >= 0:
                spans.append((position, position + len(found)))
                cursor = position + len(found)
        return spans
    return []


_SENTENCE_END_MARKS = "。．！？!?"


def _tone_excerpt(old, new, spans, width=_TONE_EXCERPT_WIDTH):
    """減った印のまわりの抜き出し（前後 width 字。切った側に「…」）。印は、変わった所に重なる最初のもの（なければ最初のもの）。
    推敲後の側は、同じ位置（変わった所の中なら、変わった所の長さの割合で対応させた位置）のまわり。前後 width 字の中で、
    印の前の文の終わり（。！？）のあとから始め、印のあとの最初の文の終わりで止める（印が「！」「？」なら印で止める）。
    どちらも空にしない（行の後ろを消しただけの推敲で「→『』」と出していた。反証で見つけた例）。"""
    head, tail = _common_affix(old, new)
    old_end, new_end = len(old) - tail, len(new) - tail
    if spans:
        start, end = next(((left, right) for left, right in spans if left < max(old_end, head + 1) and right > head), spans[0])
    else:
        start = end = head
    if end <= head:
        new_start, new_end_at = start, end
    elif start >= old_end:
        new_start, new_end_at = start + len(new) - len(old), end + len(new) - len(old)
    else:
        new_start = new_end_at = head + (start - head) * (new_end - head) // max(1, old_end - head)

    def cut(text, left, right):
        first, last = max(0, left - width), min(len(text), right + width)
        if right > left and text[right - 1] in _SENTENCE_END_MARKS:
            last = right
        else:
            for index in range(right, last):
                if text[index] in _SENTENCE_END_MARKS:
                    last = index + 1
                    break
        for index in range(left - 1, first - 1, -1):
            if text[index] in _SENTENCE_END_MARKS:
                if text[index + 1:last].strip():
                    first = index + 1
                break
        part = text[first:last].strip()
        if not part:
            return text.strip()[:2 * width]
        return ("…" if first > 0 else "") + part + ("…" if last < len(text) else "")
    return cut(old, start, end), cut(new, new_start, new_end_at)


def tone(orig, rw, doc_type=None):
    """勢いの検査（JSON の tone と同じ形）。doc_type は文書の種類（pr、article、incident、manual、formal なら参考。
    paper も参考。mail と promo は絵文字と見出しも見直し候補、minutes は見出しを見直し候補にする）。"""
    full, sides = _build_full_diff(orig, rw, None)
    return _tone(sides, full, normalize_doc_type(doc_type))


def _tone_level(doc_type, subkind):
    """候補の level。参考の種類（TONE_INFO_DOC_TYPES）はすべて info。種類を指定していて promo でなければ、絵文字と見出しは info
    （minutes の見出しは review のまま。TONE_TYPED_REVIEW_DOC_TYPES）。"""
    if doc_type in TONE_INFO_DOC_TYPES:
        return "info"
    if (doc_type is not None and subkind in TONE_TYPED_INFO_SUBKINDS
            and doc_type not in TONE_TYPED_REVIEW_DOC_TYPES.get(subkind, ())):
        return "info"
    return "review"


def _indirect_question_drop(sides, groups):
    """組になった文で、推敲後の文が間接の問い（_INDIRECT_QUESTION）になったときに減った「？」の数の合計。
    コード、表などの数えない行の文と、伏せる範囲（インラインのコード、URL など）の中の「？」は数えない（_tone_lines と同じ）。"""
    maskers = (_Masker(sides, 0, skip_kinds=_TONE_SKIP_KINDS), _Masker(sides, 1, skip_kinds=_TONE_SKIP_KINDS))
    dropped = 0
    for group in groups:
        for i, j in group["pairs"]:
            old, new = maskers[0].body(group["old"][i]), maskers[1].body(group["new"][j])
            if old is None or new is None:
                continue
            before, after = len(_QUESTION_MARK.findall(old.text)), len(_QUESTION_MARK.findall(new.text))
            if before > after and _INDIRECT_QUESTION.search(new.text):
                dropped += before - after
    return dropped


def _tone(sides, full, doc_type, groups=None):
    words, source = _load_list("intensifiers")
    intensifiers = _intensifier_pattern(words)
    base_level = _tone_level(doc_type, None)
    pseudo = doc_type == "promo"
    old_lines = _tone_lines(sides, 0, intensifiers, pseudo)
    new_lines = old_lines if sides.texts[0] == sides.texts[1] else _tone_lines(sides, 1, intensifiers, pseudo)

    def totals(lines):
        found = dict((kind, sum(counts[kind] for counts in lines.values())) for kind in _TONE_KINDS)
        found["heading_chars"] = sum(counts["heading_chars"] for counts in lines.values())
        return found
    old_total, new_total = totals(old_lines), totals(new_lines)
    out = []
    if sides.texts[0] != sides.texts[1] and full["hunks"]:
        for kind in _TONE_KINDS:
            if new_total[kind] >= old_total[kind]:
                continue
            # 間接の問いにした推敲で減った「？」は数えない（議事録の「予算は足りるのか？」→「予算が足りるかとの質問があった」）。
            # 意味が変わる恐れの「問いの文が問いでなくなった」（sentence_type）は変えない（この直しの範囲の外）
            if kind == "question":
                if groups is None:      # 公開の tone() から呼ばれたときは、要るときだけ文の組を作る
                    groups = _sentence_pairs(sides, full)
                if new_total[kind] >= old_total[kind] - _indirect_question_drop(sides, groups):
                    continue
            detail = {"old": old_total[kind], "new": new_total[kind],
                      "places": _tone_places(full, old_lines, new_lines, kind, intensifiers)}
            if kind == "intensifier":
                before, after = Counter(), Counter()
                for counts in old_lines.values():
                    before.update(counts["words"])
                for counts in new_lines.values():
                    after.update(counts["words"])
                detail["words"] = [word for word in sorted(before, key=lambda w: (-before[w], w)) if after[word] < before[word]]
            first = detail["places"][0] if detail["places"] else {}
            out.append({"kind": "tone", "subkind": kind, "old_line": first.get("old_line"), "new_line": first.get("new_line"),
                        "old": first.get("old"), "new": first.get("new"), "detail": detail,
                        "level": _tone_level(doc_type, kind)})
        old_heading, new_heading = old_total["heading_chars"], new_total["heading_chars"]
        if old_heading and new_heading < old_heading * TONE_HEADING_RATIO:
            places = _tone_places(full, old_lines, new_lines, "heading_chars", intensifiers)
            first = places[0] if places else {}
            out.append({"kind": "tone", "subkind": "heading", "old_line": first.get("old_line"),
                        "new_line": first.get("new_line"), "old": first.get("old"), "new": first.get("new"),
                        "detail": {"old": old_heading, "new": new_heading, "places": places},
                        "level": _tone_level(doc_type, "heading")})
    # 節の level: 見直し候補が1つでもあれば review、参考だけなら info、候補がなければ種類で決まる値
    if any(candidate["level"] == "review" for candidate in out):
        level = "review"
    else:
        level = "info" if out else base_level
    return {"level": level, "candidate_count": len(out), "candidates": out,
            "counts": {"old": old_total, "new": new_total}, "list": source,
            "list_problem": _LIST_PROBLEMS.get("intensifiers")}


def _tone_places(full, old_lines, new_lines, kind, intensifiers=None):
    """数が減った hunk ごとの、減った行の前後（{"old_line", "new_line", "old", "new"}）。kind が heading_chars なら
    見出しの行だけを比べる。長い行（40字を超える）は、減った印のまわりだけを抜き出す（_tone_excerpt）。"""
    places = []
    for hunk in full["hunks"]:
        olds = [(line, old_lines[line]) for line in range(hunk["old_start"], hunk["old_end"] + 1) if line in old_lines]
        news = [(line, new_lines[line]) for line in range(hunk["new_start"], hunk["new_end"] + 1) if line in new_lines]
        if kind == "heading_chars":
            olds = [item for item in olds if item[1]["heading_chars"]]
            news = [item for item in news if item[1]["heading_chars"]] or news
        if sum(counts[kind] for _, counts in olds) <= sum(counts[kind] for _, counts in news):
            continue
        chosen = None
        for offset, (line, counts) in enumerate(olds):
            if not counts[kind]:
                continue
            partner = news[offset] if offset < len(news) else (news[-1] if news else None)
            if partner is None or partner[1][kind] < counts[kind]:
                chosen = (line, counts, partner)
                break
            if chosen is None:
                chosen = (line, counts, partner)
        line, counts, partner = chosen
        old_text = counts["text"].strip()
        if partner is None:
            if kind != "heading_chars" and len(old_text) > 2 * _TONE_EXCERPT_WIDTH:
                old_text = _tone_excerpt(old_text, "", _mark_spans(old_text, kind, intensifiers))[0]
            places.append({"old_line": line, "new_line": None, "old": old_text, "new": None})
            continue
        new_text = partner[1]["text"].strip()
        if kind != "heading_chars" and (len(old_text) > 2 * _TONE_EXCERPT_WIDTH or len(new_text) > 2 * _TONE_EXCERPT_WIDTH):
            old_text, new_text = _tone_excerpt(old_text, new_text, _mark_spans(old_text, kind, intensifiers))
        places.append({"old_line": line, "new_line": partner[0], "old": old_text, "new": new_text})
    return places


# ---- 資料との照合（yomiyasu_check.py がプロセスの中で呼ぶ）----
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
# 「未定」は「未定義」を、「確定」は「確定する」「確定申告」を除く（確度の語ではない）
_CERTAINTY_NOT = {"はず": "(?![れさしすせ])", "未定": "(?!義)", "確定": "(?!する|申告)"}
_CERTAINTY = re.compile("|".join(re.escape(word) + _CERTAINTY_NOT.get(word, "")
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
        """位置を含む文（意味が変わる恐れと同じ分け方）を返す。文に分けない行（コードなど）なら、その行を丸ごと返す。"""
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
    最終稿の「本番環境」と同じとみなす（太字の有無は書式だけの違い。反証で見つけた例）。"""
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


_GROUND_SAME_UNIT = {"s": "秒", "sec": "秒", "secs": "秒", "ms": "ミリ秒", "msec": "ミリ秒",
                    "min": "分", "mins": "分"}
# 照合だけで使う単位。msec を ms より先に読み、英単語の途中の s / min などは単位にしない。
_GROUND_UNIT = re.compile(r"(?:secs|sec|msec|mins|min|ms|s)(?![A-Za-z])|ミリ秒|" + _UNIT.pattern)


def _ground_number_key(key):
    """照合用の比較値。小数部が0だけのときだけ整数にし、非0の末尾や版の番号は削らない。"""
    value, unit = key
    whole, dot, fraction = value.partition(".")
    if dot and fraction and not fraction.strip("0"):
        value = whole
    return value, _GROUND_SAME_UNIT.get(unit, unit)


def _ground_comparison_numbers(numbers):
    """表示用の値を変えずに、範囲・日付・時刻のまとまりと空白の手がかりも含めた比較用の写しを作る。"""
    found = []
    for number in numbers:
        value, unit = _ground_number_key(number.key)
        cluster = tuple(_ground_number_key(key) for key in number.cluster) if number.cluster is not None else None
        notation = number.notation
        if notation is not None:
            group, follow, frame = notation
            group = tuple(_ground_number_key((value, ""))[0] for value in group)
            match = _GROUND_UNIT.match(follow)
            if match is not None:
                follow = _GROUND_SAME_UNIT.get(match.group(0), match.group(0)) + follow[match.end():]
            if frame is not None:
                joins, units, at = frame
                frame = (joins, tuple(_GROUND_SAME_UNIT.get(unit, unit) for unit in units), at)
            notation = (group, follow, frame)
        found.append(_Number(number.start, number.end, value, unit, notation, number.weak, cluster))
    return found


def _ground_items(doc, numbers):
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

    for number in numbers:
        add("number", number.key, number.start, number.end, number.value, number.unit)
    masked = _ground_mask(text, doc.analyses[0])
    for match in _ground_names(masked):
        add("name", _squash(match.group(0)), match.start(), match.end())
    for match in _CERTAINTY.finditer(text):
        add("certainty", match.group(0), match.start(), match.end())
    certainty = set(_CERTAINTY_WORDS)
    starts = [number.start for number in numbers]
    for match in _GROUND_WORD.finditer(masked):
        if match.group(0) in certainty:
            continue
        # 数値として取った範囲（三日、十二月）に重なる語は、語として照らさない（数値で照らす）
        index = bisect_right(starts, match.end() - 1) - 1
        if index >= 0 and numbers[index].end > match.start():
            continue
        add("word", match.group(0), match.start(), match.end())
    return found


def _ground_names(masked):
    """名前（英数字2字以上）。数字のすぐあとの英字（200ms の ms、8GiB の GiB）は単位なので名前にしない。"""
    for match in _NAME.finditer(masked):
        if match.start() and masked[match.start() - 1].isdigit():
            continue
        yield match


class _Source:
    """照らす文（原文か資料）の、比べる形（数値の (数, 単位) の集合と、NFKC にして空白を除いた文）。"""

    def __init__(self, text):
        self.text = text
        analysis = _analyze(text)
        self.found_numbers = _find_numbers(text, analysis, unit_pattern=_GROUND_UNIT)
        comparison = _ground_comparison_numbers(self.found_numbers)
        self.numbers = _KeySet(comparison)
        self.notation = _notation_index(comparison)
        self.squashed = _squash(text)
        # 同じ取り出し方で取った名前と語の集合。項目ごとに資料の全文を探すと「項目の数×資料の字数」の時間になるので、
        # まず集合で引き、ないときだけ部分文字列を探す（結果は部分文字列で探すのと同じ。反証で見つけた例）
        masked = _ground_mask(text, analysis)
        self.names = set(_squash(match.group(0)) for match in _ground_names(masked))
        self.words = set(match.group(0) for match in _GROUND_WORD.finditer(masked))
        self.words.update(match.group(0) for match in _CERTAINTY.finditer(text))
        self.lines = _split_lines(text)
        starts = _line_starts(self.lines)
        self.number_lines = {}
        self.number_rows = {}
        for number in comparison:
            line = bisect_right(starts, number.start)
            self.number_lines.setdefault(number.key, set()).add(line)
            self.number_rows.setdefault(number.value, []).append((number, line))
        self.name_lines = {}
        for match in _ground_names(masked):
            self.name_lines.setdefault(_squash(match.group()), set()).add(bisect_right(starts, match.start()))
        self.bare_lines = {}
        self.certainty_words = list(OrderedDict.fromkeys(m.group() for m in _GROUND_CERTAINTY.finditer(text)))
        for line, body in enumerate(self.lines, 1):
            match = _BARE_SETTING.match(unicodedata.normalize("NFKC", body))
            if match:
                value = _ground_number_key((match.group(1), ""))[0]
                self.bare_lines.setdefault(value, []).append(line)

    def evidence(self, index, line):
        return [index, line, self.lines[line - 1].rstrip("\r\n")[:60]]

    def matching_lines(self, kind, key, final):
        if kind == "name":
            if key in self.name_lines:
                return sorted(self.name_lines[key])
            pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])")
            return [i for i, text in enumerate(self.lines, 1) if pattern.search(_squash(text))]
        key = _ground_number_key(key)
        lines = set(self.number_lines.get(key, ()))
        value, unit = key
        final_set, final_notation = final
        if unit:
            lines.update(line for number, line in self.number_rows.get(value, ())
                         if not number.unit and _notation_match(number, final_set, unit))
        else:
            lines.update(line for number, line in self.number_rows.get(value, ())
                         if number.unit and any(_notation_match(other, self.numbers, number.unit)
                                                for other in final_notation.get(key, ())))
        return sorted(lines)


    def has(self, kind, key, final=None):
        if kind == "number":
            return self.has_number(key, final)
        if kind == "name":
            # 名前は英数字の境目で照らす（Java を JavaScript の中に、SQL を PostgreSQL の中に見つけない）
            if key in self.names:
                return True
            return bool(re.search("(?<![A-Za-z0-9])" + re.escape(key) + "(?![A-Za-z0-9])", self.squashed))
        return key in self.words or key in self.squashed

    def has_number(self, key, final):
        """最終稿の値 key が、この文にあるか。final は最終稿の (_KeySet, _notation_index の形)。
        同じ数の「単位なし」と「単位あり」は、diff の組の文と同じ条件でだけ表記の違いとみなす（16 GB と 16GB、3〜5日 と 3日から5日、
        2026-10-13 と 2026年10月13日、10:30 と 10時30分。「手順2」と「2週間」、「表3」と「3%」はみなさない。
        反証で見つけた例）。"""
        key = _ground_number_key(key)
        if key in self.numbers.keys:
            return True
        final_set, final_notation = final
        value, unit = key
        if unit:
            return any(_notation_match(number, final_set, unit) for number in self.notation.get((value, ""), ()))
        return any(_notation_match(number, self.numbers) for number in final_notation.get(key, ()))



# 照合だけに足す語。既存の diff の確度判定と候補件数は変えない。
_GROUND_CERTAINTY = re.compile(_CERTAINTY.pattern +
    r"|たぶん|多分|おそらく|恐らく|きっと|と思います|と思う|気がする|記憶では|方向で|検討して|まだ決まって|確かめていない"
    + "|" + TYPE_MARKERS["推量"].pattern, re.M)
_BARE_SETTING = re.compile(
    r"^[ \t]*[+-]?[ \t]*[^\W\d]\w*[ \t]*[=:][ \t]*"
    r"([0-9]+(?:\.[0-9]+)?)(?=[ \t]*(?:$|[#;]))")


def _ground_evidence(sources, kind, key, final, indices):
    rows = []
    for index in indices:
        source = sources[index - 1]
        for line in source.matching_lines(kind, key, final):
            rows.append(source.evidence(index, line))
            if len(rows) == 3:
                return rows
    return rows


def _ground_value_certainty(items, doc, found, sources, final):
    if not any(source.certainty_words for source in sources):
        return
    dropped = {item["text"]: item for item in items if item["classification"] == "dropped_certainty"}
    def add(word, value=None):
        if word not in dropped:
            item = {"kind": "certainty", "text": word, "value": None, "unit": None,
                    "final_lines": [], "classification": "dropped_certainty"}
            dropped[word] = item
            items.append(item)
        if value is not None:
            values = dropped[word].setdefault("values", [])
            if value not in values:
                values.append(value)
    final_words = set(m.group() for m in _GROUND_CERTAINTY.finditer(doc.texts[0]))
    for source in sources:
        for word in source.certainty_words:
            if word not in final_words:
                add(word)
    # 値が繰り返される場合も、言い切った文を1つでも含めば見せる。
    occurrences = {}
    for number in _find_numbers(doc.texts[0], doc.analyses[0], unit_pattern=_GROUND_UNIT):
        occurrences.setdefault(number.key, []).append(number.start)
    for (kind, key), entry in found.items():
        if kind != "number":
            continue
        if not any(not _GROUND_CERTAINTY.search(doc.sentence_at(start))
                   for start in occurrences.get(key, [entry["start"]])):
            continue
        for source in sources:
            if source.has(kind, key, final):
                for line in source.matching_lines(kind, key, final):
                    for match in _GROUND_CERTAINTY.finditer(source.lines[line - 1]):
                        add(match.group(), entry["text"])

def ground(final, materials, original=None, labels=None):
    """資料との照合。final は最終稿、materials は資料の文字列の並び、
    original は原文（推敲のとき。なければ新規作成）。照合の JSON（attempt-<n>.materials.json の形）を返す。

    取る項目は数値（diff と同じ取り出し方、(数, 単位) で比べる）、名前（英数字2字以上）、語（漢字2字以上と片仮名2字以上）、
    確度の語。名前と語と確度の語は、NFKC にして空白を除いた文字列の部分文字列かで「ある」とみなす。
    分類は in_original（原文にある）、from_materials（原文になく資料にある）、not_in_sources（どちらにもない）、
    dropped_certainty（資料にある確度の語が最終稿にない）、not_in_final（資料にある数値が最終稿にない。参考で、候補にしない。
    final_lines は []。diff の詰めで足した）。数値は照合の中だけで時間の単位と小数部が0だけの数をそろえる。
    「単位なし」と「単位あり」は、範囲・日付・時刻のまとまりか、空白のあとに単位がある形でだけ表記の違いとみなす。
    名前は英数字の境目で照らす。

    意味が変わる恐れ（kind unsupported）に入れるもの: 新規作成で資料にない数値（subkind number）と、両方のモードで資料にない
    名前（subkind name）。推敲の数値は diff の数値の候補の basis で扱う（check が "material" か "none" を入れる）ので入れない。
    candidate_count は、意味が変わる恐れの数に、照合の節の見直し候補の行（新規作成の「資料にない語」、確度の語、
    推敲の「資料に基づく補足の候補」）を1行ずつ足したもの。「参考」の行は数えない。"""
    mode = "rewrite" if original is not None else "compose"
    materials = list(materials)
    labels = list(labels) if labels is not None else [None] * len(materials)
    if len(labels) != len(materials):
        raise ValueError("資料と出典の数が違います")
    doc = _Doc(final)
    original_source = _Source(original) if original is not None else None
    material_sources = [_Source(text) for text in materials]
    sources = []
    if original is not None:
        sources.append({"role": "source", "index": 1, "chars": len(original)})
    for index, text in enumerate(materials, 1):
        sources.append({"role": "material", "index": index, "chars": len(text), "label": labels[index - 1]})

    items, risks = [], []
    final_found = _find_numbers(doc.texts[0], doc.analyses[0], unit_pattern=_GROUND_UNIT)
    found = _ground_items(doc, final_found)
    comparison = _ground_comparison_numbers(final_found)
    final = (_KeySet(comparison), _notation_index(comparison))
    # 数量を主張しない「一つ」（一つの、一つずつ、もう一つ）だけの値は、資料にない数値の候補にしない（反証で見つけた例）
    strong = set(number.key for number in final_found if not number.weak)
    for (kind, key), entry in sorted(found.items(), key=lambda pair: (_GROUND_KIND_ORDER[pair[0][0]], pair[1]["start"])):
        if original_source is not None and original_source.has(kind, key, final):
            classification = "in_original"
        elif any(source.has(kind, key, final) for source in material_sources):
            classification = "from_materials"
        else:
            classification = "not_in_sources"
        items.append({"kind": kind, "text": entry["text"], "value": entry["value"], "unit": entry["unit"],
                      "final_lines": entry["lines"], "classification": classification})
        item = items[-1]
        if classification == "from_materials":
            item["found_in"] = [i for i, source in enumerate(material_sources, 1) if source.has(kind, key, final)]
            if kind in ("number", "name"):
                item["evidence"] = _ground_evidence(material_sources, kind, key, final, item["found_in"])
        elif classification == "not_in_sources" and kind == "number":
            bare = []
            value = _ground_number_key(key)[0]
            for i, source in enumerate(material_sources, 1):
                bare.extend(source.evidence(i, line) for line in source.bare_lines.get(value, ()))
                if len(bare) >= 3:
                    break
            if bare:
                item["bare_in"] = bare[:3]
        if classification != "not_in_sources":
            continue
        if kind == "number" and mode == "compose" and key in strong:
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
    # 資料にあって最終稿にない数値（参考。候補にしない）。資料で出てくる順に items の最後に入れ、記録の照合の JSON だけから
    # 「参考: 資料にあって最終稿にない数値」の行を作り直せるようにする
    # 「ある」の判定は照合と同じ条件（反証で見つけた例。最終稿の「HTTP/2」の「2」は、資料の「2回」を最終稿にあるとしない）。
    # 数量を主張しない「一つ」は入れない
    final_set, final_notation = final
    rest = OrderedDict()
    for source in material_sources:
        for number in source.found_numbers:
            key = _ground_number_key(number.key)
            if number.key in rest or number.weak or key in final_set.keys:
                continue
            value, unit = key
            if unit:
                present = any(_notation_match(other, source.numbers, unit) for other in final_notation.get((value, ""), ()))
            else:
                present = any(_notation_match(other, final_set) for other in source.notation.get(key, ()))
            if not present:
                rest[number.key] = source.text[number.start:number.end]
    for (value, unit), text in rest.items():
        items.append({"kind": "number", "text": text, "value": value, "unit": unit, "final_lines": [],
                      "classification": "not_in_final"})

    risks = [risk for _, risk in sorted(risks, key=lambda pair: pair[0])]
    lines = 0
    if mode == "compose" and any(item["kind"] == "word" and item["classification"] == "not_in_sources" for item in items):
        lines += 1
    if dropped:
        lines += 1
    if mode == "rewrite" and any(item["classification"] == "from_materials" for item in items):
        lines += 1
    _ground_value_certainty(items, doc, found, material_sources, final)
    return {"format": "yomiyasu-materials", "format_version": MATERIALS_FORMAT_VERSION, "tool_version": __version__,
            "mode": mode, "sources": sources, "items": items, "meaning_risks": risks,
            "candidate_count": len(risks) + lines, "meaning_risk_count": len(risks),
            "not_judged": list(_GROUND_NOT_JUDGED)}


# ---- 確度・かぎかっこ・文体の切り替え ----

_CERTAINTY_VERB = "[るうくすつぬぶむぐたい]"
# 予定・見込みは、文の確かさを言う述語のときだけ数える（「予定表」「見込み客」「会議の予定を調整」「売上の見込みを立てる」の
# ような名詞は数えない。反証で見つけた例）。述語は、あとが「です」「だ」「となる」や文の終わりの形か、動詞の使い方（予定して、
# 見込まれる）。「の」と「で、」が続く形は、前がサ変の名詞か動詞の終わりのとき（リリース予定の機能、修正する予定で、）と、
# 「〜までの予定で、」だけ。
_PREDICATE_END = r"(?=です|だ(?!け)|である|でした|だった|でござ|と(?:な|して|され)|に(?:な|し)|[。）)」』]|$)"
_PREDICATE_STEM = "(?<=[ァ-ヴー一-龥])"
_PREDICATE_BEFORE = "(?<=[るうくすつぬぶむぐたいァ-ヴー一-龥])"
_YOTEI = (r"予定(?=して(?:い|お)|しま|する(?=[。、]|$)|され)"
          r"|予定(?!外|より|通り|どおり)" + _PREDICATE_END
          + r"|" + _PREDICATE_STEM + r"予定(?=の)|" + _PREDICATE_BEFORE + r"予定(?=で(?!は)|、)|(?<=の)予定(?=で、)")
_MIKOMI = (r"見込(?:ま(?:れ|せ)|んで|む(?=[。、]|$)|め(?:る|ま)|み(?=ます))"
           r"|見込み" + _PREDICATE_END
           + r"|" + _PREDICATE_STEM + r"見込み(?=の)|" + _PREDICATE_BEFORE + r"見込み(?=で(?!は)|、)|(?<=の)見込み(?=で、)"
           + r"|見込み(?=(?:が|も|は)(?:高|大き|強|あ|立|薄|低|な))")
# 様態の「そう」と、推量の「よう」「らしい」「みたい」（今の文の種類の印の推量と同じ語をそろえた。反証で見つけた例）
_APPEARANCE = (r"(?<=[きしちにひみりぎじびぴえけせてねへめれげぜべぺさ])そう(?:です|だ|な|に|で(?!す)|でした|だった)"
               r"|(?<=[るうくすつぬぶむぐいた])よう(?:だ|です|でした|だった|である)(?=[。、！!よね]|$)"
               r"|(?<=[るうくすつぬぶむぐた])らし(?:い|かった)(?=[。、！!よね]|です|$)"
               r"|(?<=[るうくすつぬぶむぐいた])みたい(?:だ|です|でした|だった)(?=[。、！!よね]|$)")
_CERTAINTY_TABLE = [
    # (強さ, 名前, 正規表現, core)。core でない語（頻度や傾向の言い方、検討、意見）だけが動いた強めは --fail-on に数えない。
    # 表の順に当て、前の語と重なった位置はあとの語に数えない（「可能性が高い」を「可能性」より先に置く）。
    (2, "可能性が高い", r"可能性(?:が|は|も)?(?:高|大き|十分)", True),
    # 1 可能性
    (1, "かもしれない", r"かも(?:しれ|知れ)(?:ない|ません|ず|なかった|なけれ)", True),
    (1, "可能性", r"可能性(?:が|も|は)?(?:あ|ござ|考え|残|存在|否定でき|捨てきれ|拭え)", True),
    (1, "おそれ", r"(?:おそれ|恐れ|虞)(?=が|も|は|あ)", True),
    (1, "リスク", r"リスク(?:が|も)(?:あ|高|伴|残)", True),
    (1, "懸念", r"懸念(?:が|も)?(?:あ|され|残)", True),
    (1, "得る", r"(?<=[しりきちびみいえけせれべ])(?:得る|得ます|うる)", True),
    (1, "かねない", r"(?<=[しりきちびみいえけせれべ])かね(?:ない|ません|ず)", True),
    (1, "必ずしも", r"必ずしも|とは限(?:らない|らず|りません|らなかった)", True),
    (1, "ことがある", r"(?<![たっだ])こと(?:が|も)(?:ある|あり|あっ)|(?:ケース|とき)(?:が|も)(?:ある|あり|あっ|出)", False),
    (1, "場合がある", r"場合(?:が|も)(?:ある|あり|あっ)", False),
    (1, "検討", r"検討(?:中|して(?:い|お)|を(?:進め|続け|始め))", False),
    # 2 見込み・推量
    (2, "と思われる", r"と(?:思|おも)われ", True),
    (2, "と考えられる", r"と考えられ", True),
    (2, "と見られる", r"と(?:見|み)られ", True),
    (2, "と見ている", r"と(?:見|み)て(?:いる|います|おり)", True),
    (2, "見込み", _MIKOMI, True),
    (2, "予想", r"予(?:想|測)(?:され|して(?:い|お)|します|する(?=[。、]|$)|です|だ(?=[。、]|$)|であ|では)", True),
    (2, "想定", r"想定(?:され|して(?:い|お)|します|する(?=[。、]|$)|です|だ(?=[。、]|$)|であ|では)", True),
    (2, "見通し", r"見通し(?:です|だ|で|が)", True),
    (2, "推測される", r"推(?:測|定|察)(?:され|して(?:い|お)|します|する(?=[。、]|$)|です|だ(?=[。、]|$))", True),
    (2, "公算", r"公算(?:が|は|も)?(?:大き|高|強)", True),
    (2, "でしょう", r"でしょう(?!か)|だろう(?!か)|であろう", True),
    (2, "はず", r"はず(?:だ|です|で|でした|だった|の)", True),
    (2, "おそらく", r"おそらく|恐らく|たぶん|多分", True),
    (2, "示唆", r"示唆(?:する|され|して|し)", True),
    (2, "そう・よう", _APPEARANCE, True),
    (2, "傾向", r"傾向(?:が|に)(?:ある|あり|見られ)", False),
    (2, "期待できる", r"期待(?:でき|され|して(?:い|お)|します|する(?=[。、]|$))", False),
    (2, "と思う", r"と(?:思|考え)(?:います|う|る|ます|ている|ています|ており|ております|ていました)|と(?:思|おも)って(?:い|お)"
                r"|思うのは", False),
    # 3 予定
    (3, "予定", _YOTEI, True),
    (3, "計画", r"(?<=" + _CERTAINTY_VERB + ")計画(?:です|だ|で|である|が(?=あ)|も(?=あ))|計画(?:して(?:い|お)|中)", True),
    (3, "方針", r"(?<=" + _CERTAINTY_VERB + ")方針(?:です|だ|で|である)", True),
    (3, "方向", r"(?<=" + _CERTAINTY_VERB + ")方向(?:です|だ|で|である)", True),
    (3, "つもり", r"つもり(?:です|だ|で)", True),
    # 5 確実・必ず
    (5, "確実", r"(?<!ほぼ)(?<!ほとんど)確実(?:に|だ|です|で|な)", True),
    (5, "必ず", r"必ず(?!しも)", True),
    (5, "間違いなく", r"(?<!ほぼ)間違いなく|間違いありません|間違いない", True),
    (5, "確定", r"確定(?:です|だ|である|済|して(?:いる|います|おり)|しました(?!ら)|した(?!ら))", True),
    (5, "絶対に", r"絶対に", True),
]
_CERT = [(lv, name, re.compile(p), core) for lv, name, p, core in _CERTAINTY_TABLE]
# --fail-on に数えるのは、強さ1と2（可能性、見込み・推量）の core の語が、より強い語か断定に替わったときだけ。
# 予定（強さ3）から断定への言い切り（「見直す予定です」→「見直します」）は、書き手の予定を言い切る正しい書き換えでも
# 起きる（SKILL.md の例）ので、見直し候補にとどめる（反証で見つけた例）。
_COUNTED_FROM = (1, 2)
_CERTAINTY_NEG_AFTER = re.compile(r"^[^、。]{0,4}?(?:は|が|も)?(?:な[いくかし]|ありません|ございません|低|小さ|少な|薄)")
_CERTAINTY_NEG_FORMS = re.compile(r"可能性(?:は|が|も)?(?:低|小さ|少な|な[いく]|ほぼな|ありません)|見込(?:み|め)(?:は|が)?(?:な[いく]|薄|低|ありません)"
                        r"|予定(?:は|が)?(?:な[いく]|ありません)|はず(?:が|は)(?:な|ありません)|(?:おそれ|恐れ)(?:は|が)?(?:な[いく]|ありません)"
                        r"|リスク(?:は|が)?(?:な[いく]|低|小さ|少な|ありません)|懸念(?:は|が)?(?:な[いく]|ありません)"
                        r"|(?:あり|起こり|なり|し)(?:得|え)(?:ない|ません)")

_CERTAINTY_QUESTION = re.compile(r"でしょうか[。？?]?[」』）)]*$")
_CERTAINTY_LEVELS = {1: "可能性", 2: "見込み・推量", 3: "予定", 4: "断定", 5: "確実"}
# 会話の行（行の頭に8字以内の話し手の名前があってもよい）。「」と『』、閉じのあとの句点も見る（反証で見つけた例）
_DIALOGUE = re.compile(r"^[^「」『』、。\s]{0,8}[「『].*[」』][。．]?$")
_QUOTE_CLOSE = {"「": "」", "『": "』"}
# 書き方だけの違いとして外す字。長音の「ー」は語の一部なので外さない（「ビール」と「ビル」。反証で見つけた例）
_QUOTE_DROP = re.compile(r"[\s、。，．,.!！…‥・〜~－-]|\.\.\.")


def _certainty_words(text):
    """表の順に重なりを除く。(強さ, 名前, 位置, 否定つき, core) を位置の順で返す。"""
    return [word[:5] for word in _certainty_word_spans(text)]


def _certainty_word_spans(text):
    """確度の語を、_certainty_words の5つ組に終わりの位置を足して返す。"""
    found, taken = [], []
    for level, name, regex, core in _CERT:
        for match in regex.finditer(text):
            if any(left < match.end() and match.start() < right for left, right in taken):
                continue
            taken.append(match.span())
            negative = name != "必ずしも" and bool(_CERTAINTY_NEG_AFTER.search(text[match.end():match.end() + 10]))
            found.append((level, name, match.start(), negative, core, match.end()))
    return sorted(found, key=lambda word: word[2])


def _certainty_negations(text, words):
    """確度を否定する形（否定のついた表の語と、表にない否定の形の頭の2字）の数。"""
    found = Counter(word[1] for word in words if word[3])
    for match in _CERTAINTY_NEG_FORMS.finditer(text):
        found[match.group(0)[:2]] += 1
    return found


def _cancel_same_level(before, after):
    """同じ強さの語を打ち消し、残った語を返す。同じ名前の語から先に打ち消す（残る語の core を、打ち消した語から借りない。
    「可能性があり、点検することがある」→「可能性があり、点検する予定です」は、ことがある → 予定 として残る。反証で見つけた例）。"""
    rest_old, rest_new, _ = _cancel_pairs(before, after)
    return rest_old, rest_new


def _cancel_pairs(before, after):
    """_cancel_same_level と同じ順で打ち消し、残った語と、打ち消した (元の語, 後の語) の組を返す。"""
    rest_old, rest_new, pairs = list(before), list(after), []
    for same_name in (True, False):
        for word in list(rest_old):
            for other in rest_new:
                if other[0] == word[0] and (not same_name or other[1] == word[1]):
                    rest_old.remove(word)
                    rest_new.remove(other)
                    pairs.append((word, other))
                    break
    return rest_old, rest_new, pairs


# 推量の語のすぐあとの条件の形（おそれがあれば、可能性がある場合）。条件の有無が変わった文は同じ強さにしない（反証で見つけた例）
_HEDGE_CONDITION = re.compile(r"[^、。！？!?\n]{0,8}?(?:れば|たら|なら|場合|とき|時(?:は|に))")
# 節の頭を決める字と、節の中身として比べる字（漢字、片仮名、英数字）
_HEDGE_CLAUSE_STOP = re.compile(r"[、。！？!?\n，,]")
_HEDGE_CONTENT = re.compile(r"[一-龥々〆ヵヶァ-ヴA-Za-z0-9０-９Ａ-Ｚａ-ｚ]")


def _hedge_polarity(text, word, words):
    """語のある節（前後の読点・句点・改行まで）の否定の印の数。確度の語の範囲と、そのすぐあとに続く否定
    （可能性も否定でき｜ません）は数えない。"""
    head = text.rfind("\n", 0, word[2]) + 1
    for stop in "、。！？!?，,":
        head = max(head, text.rfind(stop, 0, word[2]) + 1)
    match = _HEDGE_CLAUSE_STOP.search(text, word[5])
    tail = match.start() if match else len(text)
    return sum(1 for a, b in _negation_marks(text[head:tail])
               if not any(a + head < w[5] and b + head > w[2] or a + head == w[5] for w in words))


def _hedge_conditions(text, words):
    """すぐあとが条件の形になっている確度の語の数。"""
    return sum(1 for w in words if _HEDGE_CONDITION.match(text, w[5]))


def _hedge_clause(text, start):
    """語の前の、同じ節の中身の字（読点・句点・改行から語の頭まで）。"""
    head = text[max(0, start - 200):start]
    stops = [match.end() for match in _HEDGE_CLAUSE_STOP.finditer(head)]
    return set(_HEDGE_CONTENT.findall(head[stops[-1]:] if stops else head))


def _classify_hedge_marks(orig, rewrite, lost, added):
    """推量だけの印の変化を、確度の語の強さで分ける。
    same と strengthen だけを印の候補から外す。問い、否定（述語の否定の数の違い、「とは限らない」を含む）、条件の形の違い、
    表外語を先に除き、印に重なる語をすべて打ち消せたか、残った語がどちら向きに変わったかを見る。
    same にするのは、打ち消しの相手が core の語で、同じ節の中身の字を共有し（別の事柄への慎重さで打ち消さない）、
    相手のない語がどちらの側にも残らないときだけ（反証で見つけた例）。"""
    if {mark["kind"] for mark in list(lost) + list(added)} != {"推量"}:
        return "other_kinds"
    side = 0 if lost else 1
    texts = (orig or "", rewrite or "")
    words = [_certainty_word_spans(text) for text in texts]
    hits = [[(start, start + len(hit)) for start, kind, hit in _mark_positions(text) if kind == "推量"]
            for text in texts]
    for text, ws, marks in zip(texts, words, hits):
        for start, end in _sentence_spans(text) or [(0, len(text))]:
            sentence = text[start:end].strip()
            if sentence and (_is_question(sentence) or _CERTAINTY_QUESTION.search(sentence)):
                if any(start <= w[2] < end for w in ws) or any(start <= a < end for a, _ in marks):
                    return "question"
    if _certainty_negations(texts[0], words[0]) != _certainty_negations(texts[1], words[1]):
        return "negation"
    # 「とは限らない」は起こらない見込みの言い方なので、かもしれない と打ち消さない
    if any(w[1] == "必ずしも" for ws in words for w in ws):
        return "negation"
    if _hedge_conditions(texts[0], words[0]) != _hedge_conditions(texts[1], words[1]):
        return "condition"
    hit_words = []
    for start, end in hits[side]:
        overlapping = [w for w in words[side] if w[2] < end and start < w[5]]
        if not overlapping:
            return "not_in_table"
        if any(w[3] for w in overlapping):
            return "negation"
        # 「らしい」は伝聞とも読めるので、見込み・推測の語と打ち消さない
        if any(w[1] == "そう・よう" and "らし" in texts[side][w[2]:w[5]] for w in overlapping):
            return "not_in_table"
        for word in overlapping:
            if word not in hit_words:
                hit_words.append(word)
    before, after = ([w for w in ws if not w[3]] for ws in words)
    rest_old, rest_new, pairs = _cancel_pairs(before, after)
    rest_old.sort(key=lambda w: (w[0], w[2]))
    rest_new.sort(key=lambda w: (w[0], w[2]))
    rest = rest_old if side == 0 else rest_new
    left = [w for w in rest if w in hit_words]
    if not left:
        # 相手のない語が残った（再開が遅れるかもしれず、停止する見込みです → 遅れる恐れがあり、停止します）
        if len(rest_old) != len(rest_new):
            return "unpaired"
        for pair in pairs:
            hit, other = pair if side == 0 else pair[::-1]
            if hit not in hit_words:
                continue
            # 数えない語（ことがある、検討、傾向、期待できる など）は、推量の語と同じ意味の種類と言えない
            if not other[4]:
                return "not_core"
            # 慎重な言い方と一緒に、その節の述語の肯定と否定が替わった（間に合うと思われます → 間に合わない見込みです）
            if (_hedge_polarity(texts[side], hit, words[side])
                    != _hedge_polarity(texts[1 - side], other, words[1 - side])):
                return "negation"
            clauses = _hedge_clause(texts[side], hit[2]), _hedge_clause(texts[1 - side], other[2])
            if all(clauses) and not clauses[0] & clauses[1]:
                return "unanchored"
        return "same"
    paired = min(len(rest_old), len(rest_new))
    old_base = min([w[0] for w in before] + [4])
    new_base = min([w[0] for w in after] + [4])
    outcomes = set()
    for word in left:
        index = rest.index(word)
        if index < paired:
            other = (rest_new if side == 0 else rest_old)[index]
            up = other[0] > word[0] if side == 0 else word[0] > other[0]
            outcomes.add("strengthen" if up else "weaken")
        elif side == 0:
            outcomes.add("lost" if new_base > word[0] else "consolidated")
        else:
            outcomes.add("added" if old_base > word[0] else "consolidated")
    return "mixed" if len(outcomes) > 1 else outcomes.pop()


def _cancel_with_context(rest, pools):
    """隣の組にならなかった文の語で打ち消す。使った語は pools から取り除き、2つの組で使い回さない（反証で見つけた例）。"""
    kept = []
    for word in rest:
        for pool in pools:
            other = next((w for w in pool if w[0] == word[0]), None)
            if other is not None:
                pool.remove(other)
                break
        else:
            kept.append(word)
    return kept


# 事実や仕様を述べる種類（COUNTED_TYPES）で数える、頻度の言い方（core でない語）の言い切り。
_COUNTED_BY_DOC_TYPE_FROM = ("場合がある", "ことがある")
# 「場合がある」「ことがある」を消しても、書き直した文に残っていれば言い切りにならない頻度の言い方（まれに遅れる、一部の環境で
# 崩れる）。この語のある文では、種類で数える言い切りにしない。
_CERTAINTY_FREQUENCY = re.compile(r"まれに|稀に|ときどき|時々|時折|ときおり|たまに|一部|によっては|場合によって|こともある")
# 断定に強さ5の語（必ず、確実 など）を足した段を、種類で数えない原文の印（決まりを言う文の「必須にする」を「必ず実施する」に
# した書き換えは、決まりの強さを言い換えただけのことが多い）。文の種類の印の「依頼・決まり」（してください、なければならない、
# べき、必要がある など）と同じ表に、必須、ものとする、手順の「〜すること。」を足したもの。
_CERTAINTY_DUTY = re.compile(TYPE_MARKERS["依頼・決まり"].pattern + r"|必須|ものと(?:する|します)|こと(?=[。]|$)", re.M)


def _certainty_change(old, new, old_context=(), new_context=(), split_context=(), doc_type=None, duty=False):
    """強さで打ち消して比べる。old_context と new_context は、隣の組にならなかった文の語のリストの並び（打ち消しだけに使い、
    新しい段にはしない。使った語は取り除く）。確度を否定する形は、両側で同じなら外して残りを比べ、違えば比べない。
    split_context は new_context のうち、元の文から分けた文とみなした文の語のリスト。打ち消しのあとに残った強さ5の語を、
    書き直した文の語に足して比べる（文を分けた先の「必ず」を、元の文と比べる。比べた語はリストから取り除く）。
    doc_type が事実や仕様を述べる種類（COUNTED_TYPES）なら、「場合がある」「ことがある」を消して言い切った段（書き直した文に
    まれに・一部などの頻度の言い方がないとき）と、断定に強さ5の語を足した段（duty が偽のとき。duty は、元の文か隣の組に
    ならなかった元の文に決まりの言い方があるか）も
    数え、その段に "counted_by": "doc_type" を付ける。"""
    if any(_is_question(text) or _CERTAINTY_QUESTION.search(text.rstrip()) for text in (old, new)):
        return None
    before, after = _certainty_words(old), _certainty_words(new)
    if _certainty_negations(old, before) != _certainty_negations(new, after):
        return None
    before = [word for word in before if not word[3]]
    after = [word for word in after if not word[3]]
    rest_old, rest_new = _cancel_same_level(before, after)
    rest_old = _cancel_with_context(rest_old, new_context)
    rest_new = _cancel_with_context(rest_new, old_context)
    split = [(pool, word) for pool in split_context for word in pool if word[0] == 5]
    rest_new.extend(word for _, word in split)
    old_base = min([w[0] for w in before] + [4])
    new_base = min([w[0] for w in after] + [4])
    rest_old.sort(key=lambda w: (w[0], w[2]))
    rest_new.sort(key=lambda w: (w[0], w[2]))
    paired = min(len(rest_old), len(rest_new))
    transitions = list(zip(rest_old[:paired], rest_new[:paired]))
    transitions.extend((w, None) for w in rest_old[paired:] if (w[0] < 4 and new_base > w[0]) or w[0] == 5)
    transitions.extend((None, w) for w in rest_new[paired:] if (w[0] < 4 and w[0] < old_base) or w[0] == 5)
    used = [b for _, b in transitions if b is not None]
    for pool, word in split:
        if any(word is b for b in used) and word in pool:
            pool.remove(word)
    by_doc_type = doc_type in COUNTED_TYPES
    frequent = by_doc_type and bool(_CERTAINTY_FREQUENCY.search(new))
    steps = []
    for a, b in transitions:
        from_level, to_level = (a[0] if a else 4), (b[0] if b else 4)
        if from_level == to_level:
            continue
        step = {"from": a[1] if a else "断定", "to": b[1] if b else "断定",
                "from_level": from_level, "to_level": to_level,
                "counted": a is not None and a[4] and from_level in _COUNTED_FROM and to_level > from_level}
        if by_doc_type and not step["counted"] and (
                (a is not None and a[1] in _COUNTED_BY_DOC_TYPE_FROM and to_level >= 4 and not frequent)
                or (a is None and to_level == 5 and not duty)):
            step["counted"] = True
            step["counted_by"] = "doc_type"
        steps.append(step)
    if not steps:
        return None
    up = any(s["to_level"] > s["from_level"] for s in steps)
    down = any(s["to_level"] < s["from_level"] for s in steps)
    return ("certainty" if any(s["counted"] for s in steps) else "certainty_review",
            "strengthened" if up else "weakened",
            {"old_words": [w[1] for w in before], "new_words": [w[1] for w in after],
             "steps": steps, "mixed": up and down})


def _same_review_sentence(body, risk):
    """hedges と確度で共通の、原文の文の照らし方。"""
    if risk["old_line"] is not None and risk["old_line"] != body.line:
        return False
    text, other = normalize(body.raw).strip(), normalize(risk["old"] or "").strip()
    return text in other or other in text


def _unpaired_neighbors(count, index, paired):
    """組の文 index のすぐ前とすぐあとに続く、組にならなかった文の番号（_with_unpaired_text と同じ範囲）。"""
    first = index
    while first > 0 and first - 1 not in paired:
        first -= 1
    last = index
    while last + 1 < count and last + 1 not in paired:
        last += 1
    return [k for k in range(first, last + 1) if k != index]


def _certainty_risks(sides, groups, risks, masks=None, doc_type=None):
    """確度の候補。組 (i, j) ごとに比べる。組にならなかった隣の書き直した文のうち、2文字の組の半分以上が元の文 i にある文は、
    元の文から分けた文とみなし、その文の強さ5の語も比べる（文を分けても「必ず」の足しが比べられるように）。
    doc_type は _certainty_change に渡す（事実や仕様を述べる種類で数える段を決める）。"""
    masks = masks or (_Masker(sides, 0), _Masker(sides, 1))
    marks = [r for r in risks if (r["kind"], r["subkind"]) == ("sentence_type", "marks")]
    out = []
    for group in groups:
        # 塊ごとに一度だけ伏せる。全文書き換えでも組ごとに全文を走査しない。
        bodies = [[masks[side].body(s) or _Body("", s.text, s.line, s.start) for s in group[key]]
                  for side, key in enumerate(("old", "new"))]
        paired = [set(pair[side] for pair in group["pairs"]) for side in (0, 1)]
        pools = [{}, {}]

        def pool(side, index):
            if index not in pools[side]:
                pools[side][index] = [w for w in _certainty_words(bodies[side][index].text) if not w[3]]
            return pools[side][index]

        for i, j in group["pairs"]:
            old, new = bodies[0][i], bodies[1][j]
            if not old.text or not new.text or old.text == new.text:
                continue
            neighbors = [_unpaired_neighbors(len(bodies[side]), index, paired[side]) for side, index in ((0, i), (1, j))]
            contexts = [[pool(side, k) for k in neighbors[side]] for side in (0, 1)]
            old_grams = _bigrams(old.text)
            split = []
            for k in neighbors[1]:
                grams = _bigrams(bodies[1][k].text)
                if grams and len(grams & old_grams) * 2 >= len(grams):
                    split.append(pool(1, k))
            duty = bool(_CERTAINTY_DUTY.search(old.text)) or any(_CERTAINTY_DUTY.search(bodies[0][k].text) for k in neighbors[0])
            change = _certainty_change(old.text, new.text, *contexts, split_context=split, doc_type=doc_type, duty=duty)
            if change is None:
                continue
            kind, direction, detail = change
            key = "lost" if direction == "strengthened" else "added"
            if any(_same_review_sentence(old, risk)
                   and any(m["kind"] in ("推量", "意見") for m in risk["detail"].get(key, [])) for risk in marks):
                continue
            out.append(_risk(kind, direction, old.line, new.line, old.raw, new.raw, detail))
    return out


# ---- 状態の語の消え・書き手の約束・因果 ----
# 状態・約束・主張の語の表。漢字の範囲も、この検出専用に保つ。

_ADD_K = "一-龥々〆ヵヶ"

_ADD_NEG = r"(?:ない|なく|ません|ず(?![つ])|なかった|ませんでした|おらず)"

_ADD_PERF_NEG = r"(?:て|で)(?:い|お)り?(?:ない|ません|らず|なかった)"

_ADD_CHU = r"(?=です|だ|でし|で、|であ|。|$|のため|とな|につき|の(?:ため|案件|項目|もの|件|状態))"

# 「〜中、」は、同じ節に「は」「が」の主題があるときだけ状態とみなす（「日程は検討中、会場は本社」）。

_ADD_CHU_COMMA = r"(?=、)"

# 原文の状態。先に見つけた語と重なる位置は数えない。

_ADD_STATE = [
    ("unknown", "未確認", r"未確認"),
    ("unknown", "不明", r"(?<!ご)不明(?!瞭|点|な点)"),
    ("unknown", "未判明", r"未(?:判明|解明)"),
    ("unknown", "分からない", r"(?:分か|わか|判)(?:ら(?:ない|ず|なかった|なく)|りません|りかね)(?!(?:点|ところ|こと(?:が|は)?(?:あれ|あった)))"),
    ("unknown", "分かっていない", r"(?:分かっ|わかっ|判明し|把握し|特定し|特定でき|把握でき|確認でき|確認が取れ|確認がとれ|はっきりし|明らかになっ|つかめ|掴め)" + _ADD_PERF_NEG),
    ("unknown", "特定できない", r"(?:特定|把握|確認)(?:でき|が(?:でき|取れ|とれ))(?:ない|ません|ず|なかった)"),
    ("undecided", "未定", r"未(?:定(?!義)|決定|確定|決(?!済))"),
    ("undecided", "決まっていない", r"(?:決まっ|決め|決定し|確定し)" + _ADD_PERF_NEG + r"|決まら(?:ない|ず)|白紙"),
    ("undecided", "目処が立っていない", r"(?:目処|目途|めど|メド|見通し)(?:は|が|も)?(?:まだ)?(?:立っ" + _ADD_PERF_NEG + r"|立た(?:ない|ず)|立ちません|つい" + _ADD_PERF_NEG + r"|つか(?:ない|ず)|つきません)"),
    ("undecided", "判断できない", r"(?:判断|決定|決断)(?:が|は)?(?:でき|つか)(?:ない|ず|ません)"),
    ("investigating", "調査中", r"(?:調査|確認|照会|問い合わせ|問合せ|究明|精査)中" + _ADD_CHU),
    ("investigating", "調査中（読点）", r"(?:調査|確認|照会|問い合わせ|問合せ|究明|精査)中" + _ADD_CHU_COMMA),
    ("investigating", "調べている", r"(?:調べ|調査し|問い合わせ|照会し|精査し)(?:て|で)(?:い|お)(?:る|ます|ります|り(?=、))(?!た)"),
    ("considering", "検討中", r"(?:検討|調整|協議|相談|審議)中" + _ADD_CHU),
    ("considering", "検討中（読点）", r"(?:検討|調整|協議|相談|審議)中" + _ADD_CHU_COMMA),
    ("considering", "検討している", r"(?:検討し|調整し|協議し)(?:て|で)(?:い|お)(?:る|ます|ります|り(?=、))(?!た)"),
    ("considering", "次回話し合う", r"次回(?:に|まで(?:に)?)?(?:改めて)?(?:話し合|検討|決め|協議|相談)"),
    ("pending", "保留", r"保留|持ち越"),
    ("pending", "見送り", r"(?<!お)見送(?:り|る|ります|って|っている)"),
    ("awaiting", "待っている", r"(?:回答|返事|返信|返答|判断|連絡|承認|結果|決定|確定|入荷|許可|審査|結論|入金|納品)(?:を|の)?待(?:ち|って|つ(?=[。、]|$)|っております)"),
    ("awaiting", "待っている", r"待って(?:い|お)(?:る|ます|ります)"),
    ("not_done", "未着手", r"未(?:着手|対応|実施|完了|計測|検証|回答|提出|承認|解決|実装|反映|入金|払い?|納|発送|登録|処理|作成|公開|導入|返信|連絡|受領|到着|修正|適用|整備|返却|清算|精算)"),
    ("not_done", "まだ〜ない", r"まだ[^。、]{0,24}?(?:" + _ADD_NEG + r"|" + _ADD_PERF_NEG + r")"),
    ("not_done", "済んでいない", r"(?:済ん|終わっ|終え|手を(?:つけ|付け)|着手し|完了し)" + _ADD_PERF_NEG),
    ("not_done", "至っていない", r"(?:確認|特定|判明|解決|決定|合意|把握|実施|完了|発表|結論|実現|導入)(?:に|には)(?:まだ)?至(?:っ" + _ADD_PERF_NEG + r"|ら(?:ない|ず)|りません)"),
    ("no_plan", "予定はない", r"予定(?:は|が|も)?(?:ない|なく|ありません|ございません|なし)|予定し" + _ADD_PERF_NEG + r"|計画(?:は|が)(?:ない|ありません)"),
    ("in_progress", "対応中", r"(?:対応|作業|進行|準備|作成|修正|開発|移行|実施|実装|改修|復旧|集計|手配)中" + _ADD_CHU + r"|途中(?=です|だ|でし|。|$)"),
    ("in_progress", "対応中（読点）", r"(?:対応|作業|進行|準備|作成|修正|開発|移行|実施|実装|改修|復旧|集計|手配)中" + _ADD_CHU_COMMA),
]

_ADD_STATE_RX = [(fam, name, re.compile(p)) for fam, name, p in _ADD_STATE]
# 当たる語のない文は、家族ごとの走査を省く（語の表は同じ）。
_ADD_STATE_ANY = re.compile("|".join("(?:" + p + ")" for _, _, p in _ADD_STATE))

# 推敲後に同じ状態が残ったとみなす言い方。

_ADD_KEEP_EXTRA = {
    "unknown": [r"(?:明確|明らか|定か|確か)(?:で|に)?(?:は)?(?:ない|なく|ありません|なっていない|なっておりません)", r"不明確|不透明|未知数|はっきりしない|見えていない|見えておりません",
                r"存じ(?:上げ)?ません"],
    "undecided": [r"(?:決まり|決定し|確定し)(?:次第|ましたら|たら)|決まったら", r"未定"],
    "investigating": [r"(?:確認|調査)を(?:進め|続け)", r"(?:確認|調査)(?:して|を進めて)いるところ", r"現在[^。]{0,12}(?:調べ|確認し|調査し)"],
    "considering": [r"(?:検討|調整|協議)を(?:進め|続け)", r"次回(?:に|まで(?:に)?)?(?:改めて)?(?:話し合|検討|決め|協議|相談)"],
    "pending": [r"判断を待", r"いったん[^。]{0,10}?(?:保留|止め|停止|見合わせ|見送|預か|置い|置き|待)"],
    "awaiting": [r"届(?:いて|き)(?:い|お)?(?:ない|ません|らず)", r"届き次第", r"届きましたら", r"お待ち(?:し|いたし)て(?:い|お)", r"待って(?:い|お)"],
    "not_done": [r"(?:ない|ず|ぬ)まま", r"(?:されて|して|れて)(?:い|お)り?(?:ない|ません|らず)"],
    "no_plan": [],
    "in_progress": [r"進めて(?:い|お)", r"最中", r"(?:て|で)(?:いる|おる)ところ"],
}

# 近い家族への言い換えも残ったとみなす。

_ADD_KEEP_CROSS = {  # ほかの家族の語でも残ったとみなす
    "undecided": ("considering", "pending"),
    "investigating": ("unknown", "not_done", "in_progress"),
    "considering": ("undecided", "pending"),
    "pending": ("undecided", "considering", "awaiting"),
    "awaiting": ("not_done",),
    "not_done": ("in_progress", "awaiting"),
    "in_progress": ("not_done", "investigating"),
    "unknown": (),  # 分からない → 確認を進めています は消えたとする
    "no_plan": (),
}

_ADD_KEEP_EXTRA_RX = dict((k, [re.compile(p) for p in v]) for k, v in _ADD_KEEP_EXTRA.items())

# 条件の中の語は、状態の主張にしない。

_ADD_COND = re.compile(r"[^。、]{0,12}?(?:場合|なら|とき|時(?:は|に)|うちは|(?<=[けれ])ば|たら)")

# 状態そのものを打ち消す言い方（「未確認の項目はありません」「原因不明ではありません」）は、状態の主張にしない。

_ADD_STATE_DENIED = re.compile(r"(?:では|じゃ)(?:ない|なく|ありません|ございません)|(?:の|な)[^。、]{1,10}?(?:は|が|も)(?:ありません|ない(?=[。、]|$)|ございません|なし|ゼロ|0件|０件)")

# 「見送り」は、見送る中身（導入、実施など）が同じ節にあるか、名詞の言い切りのときだけ保留とみなす（人を見送る、を除く）。

_ADD_SEND_OFF_OBJECT = re.compile(r"導入|実施|採用|開催|参加|発売|公開|リリース|購入|変更|対応|提出|出店|契約|発注|申請|更新|移行|延長|追加|掲載|配布|出荷|発表|決定|判断|今回|今年|今期|今月|計画|案|予定|検討|見直し|改定|値上げ")

# 推敲後に済んだ・決まったと言い切っていれば、否定の形だけでは状態が残ったとみなさない。

_ADD_DONE = re.compile(r"済み|済ませ|完了し(?:た|ました)|判明し(?:た|ました)|特定(?:し|でき)(?:た|ました)|決まり?ました|決まった|決定し(?:た|ました)|確定し(?:た|ました)|終わ(?:った|りました)|解決し(?:た|ました)")

# 「〜中」を「〜している」と言い換えた形は、同じ途中の状態とみなす。

_ADD_PROGRESSIVE = r"(?:を|に|の)?(?:進め|続け)?(?:し|させていただい|させて|いたし)?(?:て|で)(?:い|お)(?:る|ます(?!た)|ります|り(?=、)|られ)"

_ADD_TOPIC_STOP = ("現在", "現時点", "時点", "今回", "本日", "当日", "以下", "下記", "件")

_ADD_APOLOGY = re.compile(r"申し訳(?:ありません|ございません|ない)|すみません|かまいません|構いません")

_ADD_ANY_NEG = re.compile(r"(?:て|で)(?:い|お)り?(?:ない|ません|らず|なかった)|でき(?:ない|ず|ません|なかった)|(?:ない|ず)まま|困難|不能|不可能|難し|(?:分か|わか)ら|知らない|まだ|いまだ")

# 依頼・あいさつ・名乗り、自動詞や状態の述語を除く。

_ADD_PERFORMATIVE = re.compile(r"お願い|お詫び|おわび|感謝|お礼|御礼|失礼|恐縮|承知|了解|存じ|拝見|申し上げ|お祈り|祈念|歓迎")

_ADD_REPORT = re.compile(r"(?:ご)?(?:報告|共有|紹介)")

_ADD_REPORT_MAYBE = re.compile(r"(?:ご)?(?:お知らせ|案内|連絡|説明|提案|回答|返信)")

_ADD_PERF_MARK = re.compile(r"以下|下記|次の|とおり|通り|取り急ぎ|まずは|本メール|この(?:メール|場|たび)|ここに|本日は|について|の件で|件につき")

_ADD_FUTURE_MARK = re.compile(r"今後|以後|以降|次回|次の(?:版|回|リリース|会議)|来週|来月|来年|明日|明朝|本日中|今日中|今週中|月内|年内|後日|改めて|あらためて|追って|"
                          r"別途|順次|引き続き|必ず|責任を(?:もって|持って)|までに|次第|こちらで|当方で|弊社で|当社で|私(?:から|が|より|ども)|"
                          r"担当(?:者)?(?:が|から)|チームが|前日に|事前に|早急に|速やかに|至急|すぐに|のちほど|後ほど|あとで|(?:ない|ぬ)よう(?:に)?")

# 「お客様に」は送る相手なので、主語の印にしない。

# 名乗りの文（ご報告いたします）を約束として見るための、あとで行う印。「について」「以下」があっても、
# 追って・改めて・後日のような印があれば約束とみなす。

_ADD_LATER_MARK = re.compile(r"今後|以後|次回|来週|来月|明日|後日|改めて|あらためて|追って|別途|順次|のちほど|後ほど|あとで|次第|までに|本日中|今日中|今週中|月内|年内")

_ADD_LATER_STRONG = re.compile(r"後日|改めて|あらためて|追って|別途|のちほど|後ほど|次第|までに")

_ADD_OTHER_SUBJECT = re.compile(r"(?:先方|お客様|お客さま|貴社|御社|皆様|皆さま|皆さん|取引先|委託先|メーカー|業者)(?:が|から(?!の)|より(?!の))")

# 書き手の行為と読める印。これがない普通の「〜します」は、説明や手順の文かもしれないので数えない（promise_review）。

_ADD_WRITER_MARK = re.compile(r"私|わたくし|弊社|当社|当方|当店|当課|当部|当室|我々|われわれ|こちら|担当|当チーム|当センター")

_ADD_STATIVE = ("あり", "い", "なり", "おり", "でき", "ござい", "分かり", "わかり", "変わり", "始まり", "終わり", "決まり", "届き", "かかり",
            "起き", "起こり", "生じ", "減り", "増え", "消え", "見え", "聞こえ", "思い", "考え", "感じ", "存じ", "困り", "異なり", "違い",
            "続き", "残り", "当たり", "含み", "使え", "言え", "思え", "見られ", "考えられ", "限り", "要り", "いり", "入り", "済み", "済み",
            "並び", "向き", "似", "合い", "気がし", "痛み", "要し", "有し", "存し", "属し", "喜び", "悲しみ", "驚き", "願い", "勝り", "優れ", "及び", "すみ", "過ぎ", "すぎ", "頼り", "知り")

# 原文の未来の行為や決まり。約束の言い換えを一つずつ打ち消す。

_ADD_OLD_FUTURE = re.compile(r"(?:[" + _ADD_K + "ァ-ヴー]{1,6}|[ぁ-ん]{1,3})(?:ます|ません|する|しない|します|いたします|致します|まいります|参ります|"
                         r"(?<=[るうくすつぬぶむぐ])(?=[。、]|ので|が|けど|[よねわなぞさ](?:[。、!！?？]|$)|$)|ない(?=[。、]|ので|が|[よねわ](?:[。、!！]|$)|$))"
                         r"|予定|つもり|方針|ことに(?:なり|なる|し)|たい(?=[。、]|と|です|$)|次第|ましょう")

# 推敲後の約束。再発防止、保証、その他の約束の順に見る。

_ADD_PROMISE = [
    ("prevention", "再発防止", r"(?P<k>再発(?:防止|しない|を防|の防止))"),
    ("prevention", "今後このようなことがないよう", r"(?P<k>(?:今後|二度と)[^。]{0,16}?(?:ない|ぬ)よう)"),
    ("prevention", "同じことが起きないよう", r"(?P<k>同(?:じ|様の)(?:ミス|誤り|こと|事態|問題|不具合)が(?:起き|起こら|発生し|生じ)(?:ない|ぬ)よう)"),
    ("prevention", "徹底", r"(?P<k>徹底)(?:いた|致)?し(?:ます|てまいります|て参ります)|(?P<k2>徹底)(?:する|します|を図)"),
    ("prevention", "気をつける", r"(?P<k>気を(?:つけ|付け|引き締め)|注意(?:を払|し)|心がけ|心掛け|肝に銘じ|努め|取り組んで)(?:ます|てまいります|て参ります|ていきます|る(?=[。]|$))"),
    ("guarantee", "ことはない", r"(?P<k>(?:る|く|う|す|つ|む|ぶ|ぐ|ぬ|い)ことは(?:ありません|ございません|ない(?=[。]|$)|一切))"),
    ("guarantee", "費用はかからない", r"(?P<k>(?:追加|別途)?(?:の)?(?:費用|料金|負担|手数料)(?:は|が|も)?(?:一切)?(?:かかりません|かからない|発生しません|発生いたしません|いただきません|ございません))|(?P<k2>(?:無料|無償)(?:で(?!す)|にて))"),
    ("guarantee", "まま使える", r"(?P<k>(?:まま|問題なく|支障なく|引き続き|これまでどおり|これまで通り|安心して)[^。]{0,16}?(?:いただけ(?:ます|る)|ご利用(?:になれ|でき)(?:ます|る)))"),
    ("guarantee", "変えない", r"(?P<k>(?:変え|上げ|値上げし|変更し|据え置)(?:ない|ません|く)(?=[。]|$))"),
    # 常体は述語の「保証する」「保証される」「保証している」「保証されている」と、「担保する」「担保します」「担保される」だけ
    # （「保証することも」「保証できる」「配信保証」「担保」「保証書」のような名詞は当てない）。常体の「約束する」は
    # 随筆や物語の地の文に多いので足さない。
    ("guarantee", "保証", r"(?P<k>保証|お約束|約束)(?:いた|致)?し(?:ます|ましょう)"
                        r"|(?P<k2>保証|担保)(?:する|される|されます|(?<=担保)します|(?<=保証)(?:して|されて)(?:いる|います))"
                        r"(?=[。、]|$)"),
    ("promise", "させていただく", r"(?P<k>[" + _ADD_K + "ァ-ヴー]{1,6}|[ぁ-ん]{1,3})させていただ(?:きます|く(?=[。、]|ので|$))"),
    ("promise", "いたします", r"(?P<k>(?:お|ご)?[" + _ADD_K + "ァ-ヴー]{1,6}(?:(?![をがはにでともへのやか])[ぁ-ん][" + _ADD_K + "]{0,2})?|(?:お|ご)[ぁ-ん" + _ADD_K + "]{1,6})(?:いた|致)し(?:ます|ましょう)(?!た)"),
    ("promise", "てまいります", r"(?P<k>[" + _ADD_K + "ァ-ヴー]{1,6}[ぁ-ん]{0,3})(?:て|で)(?:まいり|参り|いき)ます(?!た)"),
    ("promise", "お〜します", r"(?P<k>(?:お|ご)[" + _ADD_K + "ァ-ヴー]{1,6}[ぁ-ん]{0,2})(?:し|いたし)ます(?!た)"),
    ("promise", "サ変します", r"(?P<k>[" + _ADD_K + "ァ-ヴー]{2,6})(?:し|いたし)ます(?!た)(?=[。、]|ので|が|$)"),
    ("promise", "動詞ます", r"(?P<k>[" + _ADD_K + "][ぁ-ん]{0,3}?)(?:[しきぎちにびみりいえけせてねべめれげ])ます(?!た)(?=[。、]|ので|が|$)"),
    ("promise", "常体の約束", r"(?P<k>[" + _ADD_K + "ァ-ヴー]{1,6}[ぁ-ん]{0,3}?)(?:する|る|う|く|す|つ|む|ぶ|ぐ)(?=[。]|$)"),
]

_ADD_PROMISE_RX = [(sub, name, re.compile(p)) for sub, name, p in _ADD_PROMISE]

_ADD_REQUEST = re.compile(r"ください|下さい|お願い|いただけ(?:ます|ません)(?:か|でしょうか)|もらえ(?:ます|ません)か|いただきたく|いただければ|てほしい")

_ADD_INTRANSITIVE_SAHEN = ("発生", "存在", "増加", "減少", "低下", "上昇", "変化", "成功", "失敗", "到着", "経過", "一致",
                       "依存", "該当", "動作", "稼働", "機能", "関係", "影響", "相当", "共通", "意味", "比例", "集中",
                       "通過", "所属", "在籍", "改善", "向上", "悪化", "安定", "不足", "満足", "感謝")

# 人が主語にもなるサ変。未来の印か書き手の印があれば約束として見る（「今後は弊社で対応します」）。

_ADD_AGENTIVE_SAHEN = ("完了", "終了", "対応", "参加", "出席", "欠席", "開始", "反映")

_ADD_E_ROW = re.compile(r"(?:られ|れ|せ|え|け|げ|め|ね|べ|へ|ぜ|て)$")

_ADD_INTRANSITIVE_TAIL = re.compile(r"(?:わり|まり|がり|さり|たり|なり|あり|おり|ござい|い|でき|れ|られ)$")

_ADD_PAST_END = re.compile(r"(?:た|ました|でした|だった)[。]?[」』）)]*$")

_ADD_OLD_INTRANSITIVE = re.compile(r"(?:見つか|分か|わか|消え|変わ|増え|減|届|始ま|終わ|決ま|遅れ|止ま|動|起き|起こ|残|続|かか|間に合|替わ|上が|下が|広が|つなが|生じ|現れ|壊れ|外れ|漏れ|集ま|伸び|延び|縮)(?:る|く|う|ります|ります|きます|えます|れます|びます|ません|らない|かない|わない|ない)$")

_ADD_OLD_STATIVE = re.compile(r"(?:あり|い|おり|でき|ござい|分かり|わかり|なり)(?:ます|ません)$")

# 原文にある再発防止と保証の根拠は、表や見出しも含めて探す。

_ADD_PREVENT_ANY = re.compile(r"再発|今後[^。]{0,16}(?:ない|ぬ)よう|二度と|徹底|気を(?:つけ|付け|引き締め)|注意(?:を払|し|いた)|心がけ|心掛け|肝に銘じ|努め|取り組")

# 原文の再発防止の語が、まだない・決まっていない対策を言うときは、誓いの根拠にしない（「再発防止策は未定です」）。

_ADD_PREVENT_UNSETTLED = re.compile(r"[^。]{0,10}?(?:未定|未|検討中|調査中|調整中|ない|ありません|不要|なし|求め|要請)")

# 再発防止の名詞には、書き手がこれから取り組む述語が要る（「再発防止策は実施済みです」「再発防止を求められました」を除く）。

_ADD_PREVENT_ACT = re.compile(r"(?:ます|する(?=[。、]|$)|[るうくすつむぶぐ](?=[。、]|$)|こととし|ことにし|予定|てまいり|ていき)")

# 済んだこと・不要・他人からの求め・打ち消しは誓いにしない。「〜こととした」「〜ことにした」はこれからの行為の決めなので除かない。

_ADD_PREVENT_NOT_ACT = re.compile(r"済|不要|求め|要請|指摘|依頼され|ません|ない(?=[。、]|$)|(?<!こととし)(?<!ことにし)(?:でした|ました|だった|た(?=[。]|$))")

_ADD_GUARANTEE_FAM = {"ことはない": r"ことは(?:ありません|ございません|ない)",
                 "費用はかからない": r"(?:費用|料金|料(?=は|が|を|も)|負担|手数料)(?:は|が|も)?[^。]{0,8}?(?:かから|かかりません|発生し(?:ない|ません)|いただき?ません|不要|なし|ゼロ|[0０〇]円)|無料|無償|[0０〇]円",
                 "まま使える": r"まま|問題なく|支障なく|これまでどおり|これまで通り|安心",
                 "変えない": r"(?:変え|上げ|値上げし|変更し|据え置)(?:ない|ません|く)", "保証": r"保証|約束"}

# 理由・原因と手段・結果のつなぎ。

_ADD_CAUSAL = [
    ("reason", r"(?<=[るたいだう])ため(?:に)?(?=[、]|です|でした|だ|$)|(?<=[のな])ため(?=[、])|(?<!の)ので(?!す|しょう)|(?<=[るたいだ])から(?=[、]|です|だ|こそ|では)|ことから"),
    ("means", r"によって|により|による(?:もの)?|ことで|ことにより|おかげ|せいで|が原因|を受けて|の影響で|影響により|の効果で|効果により|がきっかけ"),
    ("result", r"(?:その|この)?結果(?:、|として)|そのため|このため|これにより|これによって|それにより|したがって|よって(?=、)|"
               r"につなが(?:る|り|った|って|ります|りました)|をもたら|に寄与|に貢献|が功を奏"),
]

_ADD_CAUSAL_RX = [(fam, re.compile(p)) for fam, p in _ADD_CAUSAL]

# 「調べた結果、分かった」は経緯で、因果の足しにしない。

_ADD_INQUIRY_RESULT = re.compile(r"(?:調べ|調査し|確認し|検証し|比較し|試し|測定し|計測し|分析し|検討し|話し合っ|協議し|集計し|聞い|尋ね|試験し|点検し|審査し|見直し)た$")

# 原文の時を言う言い方（とき、時に、際に、直後に）。推敲で同じ中身を原因の語（により、ことで）にしたら因果の足しとみなす。

_ADD_TIME_LINK = re.compile(r"(?:とき|(?<![日同当常定随一臨即瞬何毎])時)(?:に|は|、)|(?<![実交国])際(?:に|は|、)|(?:直後|最中)に")

_ADD_CONTENT = re.compile("[" + _ADD_K + "]{2,}|[ァ-ヴー]{2,}|[A-Za-z][A-Za-z0-9]+")


def _addition_state_words(text):
    found, taken = [], []
    for fam, name, rx in _ADD_STATE_RX:
        for m in rx.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append(m.span())
            if _ADD_COND.match(text, m.end()) or _ADD_STATE_DENIED.match(text, m.end()):
                continue
            clause = text[max(text.rfind("。", 0, m.start()), text.rfind("、", 0, m.start())) + 1:m.start()]
            if name.endswith("（読点）") and not re.search("[はが]", clause):
                continue
            if name == "見送り" and not _ADD_SEND_OFF_OBJECT.search(text[max(0, text.rfind("。", 0, m.start()) + 1):m.start()]) \
                    and not re.match(r"り(?:と(?:な|し|させ|いたし)|にな|です|でした|だ|。|$)", text[m.start() + 2:]):
                continue
            found.append((fam, name, m.start(), m.group(0)))
    return sorted(found, key=lambda w: w[2])


def _addition_topic(text, pos):
    """状態の語の前の、同じ節の内容語（何の状態か）。別の文に移ったとみなすときに照らす。"""
    start = max(text.rfind("。", 0, pos), text.rfind("、", 0, pos)) + 1
    words = [w for w in _ADD_CONTENT.findall(text[start:pos]) if w not in _ADD_TOPIC_STOP]
    if not words:
        words = [w for w in _ADD_CONTENT.findall(text[max(text.rfind("。", 0, pos) + 1, 0):pos]) if w not in _ADD_TOPIC_STOP]
    return words


def _addition_on_topic(topic, text):
    return not topic or any(w in text or any(w[i:i + 2] in text for i in range(len(w) - 1)) for w in topic)


def _addition_stem_neg(word):
    """未X の X と、まだ〜ない の述語の頭（2字）。推敲後に X＋否定 があれば残ったとみなす。"""
    m = re.match("未([" + _ADD_K + "]{1,3})", word)
    if m:
        return m.group(1)
    m = re.search("([" + _ADD_K + "ァ-ヴー]{1,4})[ぁ-ん]{0,4}(?:" + _ADD_NEG + "|" + _ADD_PERF_NEG + ")$", word)
    return m.group(1)[-2:] if m else None


def _addition_promise_clauses(text):
    """推敲後の文の約束の句。[(subkind, 名前, key, 位置, 書き手の印)]。会話の行、問いの文、依頼、名乗り・あいさつの定型は見ない。
    書き手の印は、謙譲の形（いたします、させていただきます、お・ご〜します、てまいります）、未来の印、書き手の主語のどれか。"""
    if not text or re.match(r"^[^「」『』、。\s]{0,8}[「『].*[」』][。．]?$", text):
        return []
    found, taken = [], []
    stripped = text.rstrip()
    question = _is_question(stripped) or bool(re.search(r"か[」』）)]*$", stripped))
    for sub, name, rx in _ADD_PROMISE_RX:
        for m in rx.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            # 見ないと決めた位置も取っておく（あとの広い型が同じ位置の一部を拾わないように）
            taken.append(m.span())
            key = m.groupdict().get("k") or m.groupdict().get("k2") or ""
            clause_start = max(text.rfind("。", 0, m.start()) + 1, 0)
            clause_end = text.find("。", m.end())
            clause = text[clause_start: clause_end if clause_end >= 0 else len(text)]
            window = text[max(0, m.start() - 2):m.end() + 8]
            if question and clause_end < 0:
                continue
            if _ADD_REQUEST.search(window) or "「" in text[:m.start()] and "」" not in text[text.rfind("「", 0, m.start()):m.start()]:
                continue
            future = bool(_ADD_FUTURE_MARK.search(clause))
            strong = (name in ("させていただく", "いたします", "てまいります", "お〜します") or future
                      or bool(_ADD_WRITER_MARK.search(clause)))
            if sub == "prevention":
                tail = text[m.end(): clause_end if clause_end >= 0 else len(text)]
                if _ADD_PREVENT_NOT_ACT.search(tail[:24]) or (key.endswith("防止") and not _ADD_PREVENT_ACT.search(tail)):
                    continue
            if sub == "promise":
                if _ADD_PERFORMATIVE.search(window[:len(window) - 8]):
                    continue
                head = re.sub("^[おご]", "", key)
                if name in ("サ変します", "動詞ます") and any(head.endswith(w) for w in _ADD_INTRANSITIVE_SAHEN):
                    continue
                if name in ("サ変します", "動詞ます") and not strong and any(head.endswith(w) for w in _ADD_AGENTIVE_SAHEN):
                    continue
                if name == "動詞ます":
                    stem = text[m.start():m.end() - 2]
                    if _ADD_INTRANSITIVE_TAIL.search(stem) or any(stem.endswith(w) for w in _ADD_STATIVE):
                        continue
                    if _ADD_E_ROW.search(stem) and not _ADD_FUTURE_MARK.search(clause):
                        continue
                if name == "常体の約束":
                    stem = text[m.start():m.end()]
                    if (not _ADD_FUTURE_MARK.search(clause) or re.search(r"(?:れる|られる|できる|なる|ある|いる|える|める|わる|まる|がる)$", stem)
                            or re.search(r"(?:ます|です|でしょう)$", stem)):
                        continue
                # 名乗りの文は見ない。ただし未来の印（追って、改めて、後日）があれば約束として見る。
                later = bool(_ADD_LATER_MARK.search(clause))
                if _ADD_REPORT.search(key) and (not later or _ADD_PERF_MARK.search(clause) and not _ADD_LATER_STRONG.search(clause)):
                    continue
                if _ADD_REPORT_MAYBE.search(key) and _ADD_PERF_MARK.search(clause) and not future:
                    continue
                if _ADD_OTHER_SUBJECT.search(clause):
                    continue
            found.append((sub, name, key, m.start(), strong or sub != "promise"))
    return found


def _addition_key_head(key):
    """約束の述語の頭。お・ご を外した漢字かカタカナの続き（1字の漢字なら次のかな1字まで）。"""
    key = re.sub("^[おご]", "", key)
    m = re.match("[" + _ADD_K + "ァ-ヴー]+", key)
    if not m:
        return key[:2]
    head = m.group(0)
    if len(head) == 1 and len(key) > 1:
        head = key[:2]
    return head


# 述語の字を照らすときに外す、時や向きの字。

_ADD_PRED_SKIP = set("来週月日年今明後前次回時分秒中内外本当弊社私様方等毎朝夕夜昼午予定針第度場合上下末初")

# 原文の述語と推敲後の約束が別の字でも、同じ行為の言い換えとみなす組（直す → 修正 など）。

_ADD_PRED_SYNONYMS = {
    "直": ("修正", "修理", "訂正", "改修", "是正", "対応"), "出": ("提出", "送付", "発行", "提示", "お送"),
    "送": ("送付", "発送", "送信", "お送"), "作": ("作成", "作製", "制作", "用意", "準備"), "調": ("調査", "確認"),
    "見": ("確認", "拝見", "目を通"), "読": ("拝読", "確認"), "書": ("記載", "記入", "作成"),
    "伝": ("連絡", "報告", "知らせ", "共有"), "知": ("連絡", "報告", "通知", "案内"), "言": ("連絡", "報告", "申し", "伝え"),
    "返": ("返信", "返答", "回答", "返却"), "決": ("決定", "確定"), "変": ("変更",), "止": ("停止", "中止", "終了"),
    "始": ("開始", "着手"), "続": ("継続", "引き続"), "払": ("支払", "入金"), "届": ("お届", "配送", "納品"),
    "渡": ("お渡", "提出", "送付"), "聞": ("確認", "伺", "お聞"), "片": ("整理",), "用": ("準備", "手配"),
    "準": ("用意", "手配"), "手": ("準備", "用意"),
}


def _addition_pred_stem(text, end):
    """述語の字（時の字を外した漢字とカタカナ）。予定・つもりのような印だけなら、その前の動詞の字。"""
    left = text[:end]
    for _ in range(2):
        seg = re.search("[" + _ADD_K + "ァ-ヴー]*[ぁ-ん]*$", left).group(0)
        stem = frozenset(c for c in seg if re.match("[" + _ADD_K + "ァ-ヴー]", c) and c not in _ADD_PRED_SKIP)
        if stem or not seg:
            return stem
        left = left[:len(left) - len(seg)]
    return frozenset()


def _addition_old_futures(text):
    """原文の文の、書き手の未来の行為や決まりを言える述語の字の並び（言い換えの打ち消しに使う。広く取る）。"""
    if _ADD_PAST_END.search(text.rstrip()) and not re.search(r"(?:ます|する|ない|ません)(?:が|ので|、)", text):
        return []
    if _is_question(text) or text.rstrip().endswith("か"):
        return []
    out = []
    for m in _ADD_OLD_FUTURE.finditer(text):
        if re.match(r"(?:予定|つもり|方針)(?:は|が|も)?(?:ない|なく|ありません|ございません|なし)", text[m.start():m.start() + 12]):
            continue
        s = text[max(0, m.start() - 4):m.end()]
        if _ADD_OLD_STATIVE.search(s) and not re.search(r"いたします$", s) or _ADD_OLD_INTRANSITIVE.search(s) or re.search(r"(?:です|でした|だ|である)$", s):
            continue
        out.append(_addition_pred_stem(text, m.end()))
    # 体言止めのサ変（「次回は20日に開催。」）
    stripped = text.rstrip().rstrip("。")
    if re.search("[" + _ADD_K + "]{2}$", stripped):
        out.append(_addition_pred_stem(stripped, len(stripped)))
    return out


def _addition_old_future_count(text):
    return len(_addition_old_futures(text))


def _addition_old_negatives(text):
    return [_addition_pred_stem(text, m.end()) for m in
            re.finditer(r"(?<!あり)(?<!ござい)(?:ない|ません)(?=[。、]|$|ので|が)", text)]


def _addition_old_negative(text):
    return len(_addition_old_negatives(text))


def _addition_same_act(stem, part):
    """原文の述語の字が、推敲後の約束の句（読点から句まで）と同じ行為を言えるか。字のない述語（やります）はどれとも合う。"""
    if not stem:
        return True
    if any(c in part for c in stem):
        return True
    return any(word in part for c in stem for word in _ADD_PRED_SYNONYMS.get(c, ()))


def _addition_find_all(table, text):
    found, taken = [], []
    for fam, rx in table:
        for m in rx.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append(m.span())
            found.append((fam, m.group(0), m.start(), m.end()))
    return sorted(found, key=lambda w: w[2])


def _addition_causal_words(text):
    return [w for w in _addition_find_all(_ADD_CAUSAL_RX, text)
            if not (w[1].startswith("結果") and _ADD_INQUIRY_RESULT.search(text[:w[2]]))]


def _addition_bigrams(text):
    t = re.sub(r"[\s、。，．・「」『』（）()]", "", text)
    return set(t[i:i + 2] for i in range(len(t) - 1))


def _addition_novelty(span, old_doc, old_bigrams=None):
    """span の語のうち、原文 old_doc になく、どの2字も old_doc にない語の割合。
    old_bigrams（old_doc の2字の組の集まり）を渡すと、語ごとに old_doc 全体を探さずに同じ値を求める。_ADD_CONTENT の語は2字以上で、
    語が old_doc にあればその最初の2字も old_doc にあるので、「どの2字も old_doc の2字の組にない」だけで決まる。"""
    words = [w for w in _ADD_CONTENT.findall(span)]
    if not words:
        return 0.0
    if old_bigrams is None:
        new = [w for w in words if w not in old_doc and not any(w[i:i + 2] in old_doc for i in range(len(w) - 1))]
    else:
        new = [w for w in words if not any(w[i:i + 2] in old_bigrams for i in range(len(w) - 1))]
    return len(new) / float(len(words))


def _addition_time_to_cause(old, span):
    cause = set(_ADD_CONTENT.findall(span))
    for m in _ADD_TIME_LINK.finditer(old):
        before = old[max(old.rfind("。", 0, m.start()), old.rfind("、", 0, m.start())) + 1:m.start()]
        if cause & set(_ADD_CONTENT.findall(before)):
            return True
    return False


def _addition_cause_span(text, fam, start, end):
    if fam == "result" and not re.match(r"につなが|をもたら|に寄与|に貢献|が功", text[start:]):
        stop = text.find("。", end)
        return text[end: stop if stop >= 0 else len(text)]
    left = text[:start]
    cut = max(left.rfind("、"), left.rfind("。"), left.rfind("は"))
    return left[cut + 1:]


class _AdditionDocument:
    """文書全体の根拠と語の検索結果。検出中に同じ本文を何度も走査しない。"""

    def __init__(self, sides, masks, risks):
        self.raw = sides.texts[0]
        self.bodies = [_all_bodies(sides, side, masks[side]) for side in (0, 1)]
        self.old_text = "".join(b.text for b in self.bodies[0])
        self.nonpast = "".join(t for t in re.split(r"(?<=[。\n])", self.raw)
                              if not _ADD_PAST_END.search(t.rstrip()))
        self.prevent = any(not _ADD_PREVENT_UNSETTLED.match(self.raw, m.end()) for m in _ADD_PREVENT_ANY.finditer(self.raw))
        self.states, self.kept, self.heads, self.matches = {}, {}, {}, {}
        self._old_bigrams = None
        self.counts = [Counter(w[0] for b in bodies for w in self.state_words(b.text)) for bodies in self.bodies]
        self.by_kind = {}
        for risk in risks:
            self.by_kind.setdefault(risk['kind'], []).append(risk)

    def old_bigrams(self):
        """原文の本文（old_text）の2字の組の集まり（_addition_novelty で、語ごとに原文全体を探さないため。初めて要るときに作る）。"""
        if self._old_bigrams is None:
            text = self.old_text
            self._old_bigrams = {text[k:k + 2] for k in range(len(text) - 1)}
        return self._old_bigrams

    def find(self, name, text):
        key = (name, text)
        if key not in self.matches:
            if name == 'promise':
                found = _addition_promise_clauses(text)
            else:
                found = _addition_causal_words(text)
            self.matches[key] = found
        return self.matches[key]

    def state_words(self, text):
        if text not in self.states:
            self.states[text] = _addition_state_words(text) if _ADD_STATE_ANY.search(text) else []
        return self.states[text]

    def state_kept(self, family, word, text):
        key = (family, word, text)
        if key not in self.kept:
            families = (family,) + _ADD_KEEP_CROSS.get(family, ())
            kept = any(w[0] in families for w in self.state_words(text))
            kept = kept or any(rx.search(text) for rx in _ADD_KEEP_EXTRA_RX.get(family, ()))
            if not kept and word.endswith('中') and family in ('investigating', 'considering', 'in_progress'):
                kept = bool(re.search(re.escape(word[:-1]) + _ADD_PROGRESSIVE, text))
            if family in ('unknown', 'not_done') and not _ADD_DONE.search(text):
                kept = kept or bool(_ADD_ANY_NEG.search(_ADD_APOLOGY.sub('', text)))
            stem = _addition_stem_neg(word)
            if not kept and stem:
                kept = bool(re.search(re.escape(stem) + '[^。、]{0,8}?(?:' + _ADD_NEG + '|' + _ADD_PERF_NEG + ')', text))
            self.kept[key] = kept
        return self.kept[key]

    def same_sentence(self, kind, body):
        return [r for r in self.by_kind.get(kind, ()) if _same_review_sentence(body, r)]

    def has_head(self, head):
        if head not in self.heads:
            self.heads[head] = bool(head and re.search(re.escape(head) + '(?![' + _ADD_K + 'ァ-ヴー])', self.nonpast))
        return self.heads[head]


class _AdditionGroup:
    """既存の組を本文にし、隣の未対応文と打ち消し用の数を共有する。"""

    def __init__(self, group, masks):
        self.bodies = [[masks[side].body(s) or _Body('', s.text, s.line, s.start) for s in group[key]]
                       for side, key in enumerate(('old', 'new'))]
        self.pairs = [dict(group['pairs']), {j: i for i, j in group['pairs']}]
        self.contexts, self.texts = {}, {}
        self.future, self.negative, self.causal = None, None, None
        self.bigram_index = None
        self.covered_cache, self.joined_lines = {}, {}

    def prepare_future(self):
        # 約束の句があるときだけ、原文の述語を取る。
        if self.future is None:
            preds = {text: (_addition_old_futures(text), _addition_old_negatives(text))
                     for text in {b.text for b in self.bodies[0]}}
            self.future, self.negative = [[list(preds[b.text][n]) for b in self.bodies[0]] for n in (0, 1)]
            self.used_preds = [set() for _ in self.bodies[0]]

    def prepare_causal(self):
        if self.causal is None:
            counts = {text: len(_addition_causal_words(text))
                      for text in {b.text for b in self.bodies[0]}}
            self.causal = [counts[b.text] for b in self.bodies[0]]

    def context(self, side, index):
        key = (side, index)
        if key not in self.contexts:
            bodies, paired = self.bodies[side], self.pairs[side]
            if index is None:
                indices = [k for k in range(len(bodies)) if k not in paired]
            else:
                indices = [index] + _unpaired_neighbors(len(bodies), index, paired)
            self.contexts[key] = indices
        return self.contexts[key]

    def text(self, side, index):
        key = (side, index)
        if key not in self.texts:
            self.texts[key] = ''.join(self.bodies[side][k].text for k in self.context(side, index))
        return self.texts[key]

    def risk(self, kind, subkind, i, j, detail):
        old = self.bodies[0][i] if i is not None else None
        new = self.bodies[1][j] if j is not None else None
        return _risk(kind, subkind, old.line if old else None, new.line if new else None,
                     old.raw if old else None, new.raw if new else None, detail)

    def covered(self, text):
        # 2字の並びから原文の文を逆引きする。全組み合わせで本文を読み直さない。
        if text in self.covered_cache:
            return self.covered_cache[text]
        if self.bigram_index is None:
            self.bigram_index, self.bigram_sizes = {}, []
            for k, body in enumerate(self.bodies[0]):
                grams = _addition_bigrams(body.text)
                self.bigram_sizes.append(len(grams))
                for gram in grams:
                    self.bigram_index.setdefault(gram, []).append(k)
        counts = Counter(k for gram in _addition_bigrams(text) for k in self.bigram_index.get(gram, ()))
        covered = sorted(k for k, n in counts.items() if n / float(self.bigram_sizes[k]) >= 0.4)
        self.covered_cache[text] = covered
        self.joined_lines[text] = [self.bodies[0][k].line for k in covered]
        return covered


def _addition_state_risks(doc, group):
    out = []
    for i, body in enumerate(group.bodies[0]):
        j = group.pairs[0].get(i)
        if not body.text or (j is not None and body.text == group.bodies[1][j].text):
            continue
        # 否定の候補があれば、その候補に任せる。
        if any(r['old_line'] == body.line and normalize(r['old'] or '') == normalize(body.raw)
               for r in doc.by_kind.get('negation', ())):
            continue
        # 推量の印が足された文は、文の種類の印の候補に任せる（確度の候補と同じ扱い）。
        if any(_same_review_sentence(body, r) and any(m['kind'] in ('推量', '意見') for m in r['detail'].get('added', []))
               for r in doc.same_sentence('sentence_type', body) if r['subkind'] == 'marks'):
            continue
        lost = []
        for family, name, pos, word in doc.state_words(body.text):
            topic = _addition_topic(body.text, pos)
            near = group.context(1, j)
            if any(doc.state_kept(family, word, group.bodies[1][k].text)
                   and (k == j or _addition_on_topic(topic, group.bodies[1][k].text)) for k in near):
                continue
            if doc.counts[1][family] >= doc.counts[0][family] and any(
                    doc.state_kept(family, word, b.text) and _addition_on_topic(topic, b.text) for b in doc.bodies[1]):
                continue
            lost.append((family, word))
        if lost:
            steps = [step for r in doc.same_sentence('certainty_review', body) for step in r['detail']['steps']]
            out.append(group.risk('state', 'lost', i, j, {
                'words': [w for _, w in lost], 'families': sorted({f for f, _ in lost}), 'certainty_steps': steps}))
    return out


def _addition_promise_risk(doc, group, i, j):
    body = group.bodies[1][j]
    clauses = doc.find('promise', body.text)
    if not clauses:
        return None
    group.prepare_future()
    context = group.context(0, i)
    old_text = group.text(0, i)
    kept = []
    for sub, name, key, pos, strong in clauses:
        if sub == 'prevention':
            if doc.prevent:
                continue
        elif sub == 'guarantee':
            if re.search(_ADD_GUARANTEE_FAM[name], doc.raw):
                continue
        else:
            head = _addition_key_head(key)
            if doc.has_head(head) or (head and i is not None and re.search(
                    re.escape(head) + '(?![' + _ADD_K + 'ァ-ヴー])', old_text)):
                continue
        # 一つの原文の述語は、同じ行為を言える約束の句を一つだけ打ち消す（読みます → 破棄します は打ち消さない）。
        can_cancel = sub == 'promise' or (sub == 'guarantee' and name in ('ことはない', '変えない') and i is not None)
        if can_cancel:
            part_start = max(body.text.rfind('、', 0, pos), body.text.rfind('。', 0, pos)) + 1
            part = body.text[part_start:pos + len(key) + 4]
            # 「〜ことはない」は、否定の数が組の原文の文より増えたとき（複製しません → 複製しないため、漏れることはありません）は
            # 足した言い切りなので、組の原文の文の述語で字を問わずに打ち消さない（起きない → 起きることはない は打ち消す）。
            paired = i
            if (name == 'ことはない' and i is not None
                    and len(_negation_marks(body.text)) > len(_negation_marks(group.bodies[0][i].text))):
                paired = None
            if not _addition_cancel(group, context, sub, part, paired):
                kept.append((sub, name, key, pos, strong))
        else:
            kept.append((sub, name, key, pos, strong))
    if i is not None and doc.same_sentence('certainty', group.bodies[0][i]):
        kept = [c for c in kept if c[0] != 'promise']
    # 読み手への依頼が消えて書き手の行為になった文は、文の種類の印の候補に任せる。
    if i is not None and not _ADD_REQUEST.search(body.text) and any(r['subkind'] == 'marks'
                             and any(m['kind'] == '依頼・決まり' for m in r['detail'].get('lost', ()))
                             and not any(m['kind'] == '依頼・決まり' for m in r['detail'].get('added', ()))
                             for r in doc.same_sentence('sentence_type', group.bodies[0][i])):
        kept = [c for c in kept if c[0] != 'promise']
    out = []
    counted = [c for c in kept if c[4]]
    weak = [c for c in kept if not c[4]]
    if counted:
        subkind = next((sub for sub in ('prevention', 'guarantee') if any(c[0] == sub for c in counted)), 'added')
        out.append(group.risk('promise', subkind, i, j, {
            'phrases': [body.text[pos:pos + max(len(key), 2) + 6] for _, _, key, pos, _ in counted],
            'names': [name for _, name, _, _, _ in counted]}))
    if weak:
        out.append(group.risk('promise_review', 'added', i, j, {
            'phrases': [body.text[pos:pos + max(len(key), 2) + 6] for _, _, key, pos, _ in weak],
            'names': [name for _, name, _, _, _ in weak]}))
    return out


def _addition_cancel(group, context, sub, part, paired):
    """組の原文の文の述語は、言い換えとして字を問わずに打ち消す（確かめます → チェックします）。
    隣の文や組にならなかった文の述語は、同じ行為を言えるときだけ打ち消す。"""
    for k in context:
        preds = [(n, stem) for n, stem in enumerate(group.future[k])]
        if sub == 'guarantee':
            preds += [(len(group.future[k]) + n, stem) for n, stem in enumerate(group.negative[k])]
        for n, stem in preds:
            if n not in group.used_preds[k] and (k == paired or _addition_same_act(stem, part)):
                group.used_preds[k].add(n)
                return True
    return False


def _addition_claim_risks(doc, group, i, j):
    body = group.bodies[1][j]
    out, remaining = [], []
    causes = doc.find('causal', body.text)
    if causes:
        group.prepare_causal()
    for cause in causes:
        for k in group.context(0, i):
            if group.causal[k]:
                group.causal[k] -= 1
                break
        else:
            remaining.append(cause)
    if remaining:
        covered = group.covered(body.text)
        joined = len(covered) >= 2
        words = [word for family, word, start, end in remaining if joined or
                 _addition_novelty(_addition_cause_span(body.text, family, start, end), doc.old_text, doc.old_bigrams()) >= 0.5]
        reason = 'joined' if joined else 'new_content'
        if not words and i is not None:
            # 原文の「〜時に」「〜際に」を、同じ中身のまま原因の語にした（集中時に → 集中したことで）。
            old = group.bodies[0][i].text
            words = [word for family, word, start, end in remaining if family == 'means'
                     and _addition_time_to_cause(old, _addition_cause_span(body.text, family, start, end))]
            reason = 'time_to_cause'
        if words:
            out.append(group.risk('claim', 'causal', i, j, {
                'words': words, 'reason': reason,
                'joined_lines': group.joined_lines[body.text] if joined else []}))
    return out


def _addition_risks(sides, groups, risks, masks):
    """状態の消えと書き足し。文の対応とマスクは既存の検出から受け取る。"""
    if not groups:
        return []
    prepared = [_AdditionGroup(source, masks) for source in groups]
    # 手がかりが一つもない変更では、文書全体の根拠を走査しない。
    # 伏せた本文で調べるので、コードを外して隣り合った語も取りこぼさない。
    state_texts = {body.text for group in prepared for body in group.bodies[0]}
    new_texts = {body.text for group in prepared for body in group.bodies[1]}
    has_state = any(_ADD_STATE_ANY.search(text) for text in state_texts)
    patterns = [rx for _, _, rx in _ADD_PROMISE_RX] + [rx for _, rx in _ADD_CAUSAL_RX]
    if not has_state and not any(rx.search(text) for text in new_texts for rx in patterns):
        return []
    doc = _AdditionDocument(sides, masks, risks)
    out = []
    for group in prepared:
        out.extend(_addition_state_risks(doc, group))
        claims = []
        for j, body in enumerate(group.bodies[1]):
            i = group.pairs[1].get(j)
            if not body.text or (i is not None and body.text == group.bodies[0][i].text):
                continue
            promise = _addition_promise_risk(doc, group, i, j)
            if promise:
                out.extend(promise)
            claims.extend(_addition_claim_risks(doc, group, i, j))
        out.extend(claims)
    return out


def _quote_normalize(text):
    return _QUOTE_DROP.sub("", unicodedata.normalize("NFKC", text).replace("?", "？"))


def _line_quotes(text):
    """1行のかぎかっこ（「」『』）を、かっこの対応を追って取る。入れ子は外側（中身に内側のかっこを含む）と内側の両方。
    文の句点をまたぐ会話（「うん。うん。そう。」）も1つとして取る（反証で見つけた例）。閉じないかっこは見ない。
    (開きの位置, かっこ, 中身) と、いちばん外側のかっこの範囲の並びを返す。"""
    stack, found, tops = [], [], []
    for position, char in enumerate(text):
        if char in _QUOTE_CLOSE:
            stack.append((position, char))
        elif char in "」』":
            depth = len(stack) - 1
            while depth >= 0 and _QUOTE_CLOSE[stack[depth][1]] != char:
                depth -= 1
            if depth < 0:
                continue
            start, opener = stack[depth]
            del stack[depth:]
            found.append((start, opener + char, text[start + 1:position]))
            if not stack:
                tops.append((start, position + 1))
    found.sort()
    return found, tops


def _blank_masked(masker, text, start):
    """伏せる範囲（インラインのコード、URL など）を同じ長さの \\x00 にした文字列（位置を保つ）。"""
    end = start + len(text)
    first = max(0, bisect_right(masker.lefts, start) - 1)
    chars = None
    for left, right in masker.spans[first:]:
        if left >= end:
            break
        if right <= start:
            continue
        if chars is None:
            chars = list(text)
        for k in range(max(left, start), min(right, end)):
            chars[k - start] = "\x00"
    return text if chars is None else "".join(chars)


class _QuoteSide:
    """1つの側のかぎかっこ。quotes は文の位置から [(比べ用の形, かっこ, 中身, 文)]、outside は文の位置から、かぎかっこの
    外の文字を比べ用の形にしたもの、count は文書全体の比べ用の形の数。"""

    def __init__(self, sides, side, masker):
        rows = sides.analyses[side]["lines"]
        self.quotes, self.outside, self.count = {}, {}, Counter()
        by_line = OrderedDict()
        for sentence in _line_sentences(sides, side, 0, len(sides.lines[side])):
            by_line.setdefault(sentence.line, []).append(sentence)
        for line_no, sentences in by_line.items():
            row = rows[line_no - 1] if line_no - 1 < len(rows) else None
            if row is None or row["kind"] in masker.skip_kinds or _is_quote_row(row):
                continue
            line_start = sides.starts[side][line_no - 1]
            text = _blank_masked(masker, sides.lines[side][line_no - 1], line_start)
            found, tops = _line_quotes(text)
            starts = [s.start - line_start for s in sentences]
            for position, bracket, content in found:
                sentence = sentences[max(0, bisect_right(starts, position) - 1)]
                key = _quote_normalize(content)
                self.quotes.setdefault(sentence.start, []).append((key, bracket, content, sentence))
                self.count[key] += 1
            outside = list(text)
            for left, right in tops:
                outside[left:right] = "\x01" * (right - left)
            outside = "".join(outside)
            for sentence, offset in zip(sentences, starts):
                self.outside[sentence.start] = _quote_normalize(outside[offset:offset + len(sentence.text)])


def _quote_risks(sides, groups, masks=None):
    """かぎかっこの中の言葉の書き換え。原文の変わった文のかぎかっこを、推敲後の対応する文とすぐ隣の組にならなかった文
    （組がなければ同じ塊の近い位置の文）だけと照らす。文書全体のどこかに同じ言葉があるだけでは残ったとしない
    （「はい」→「いいえ」、「必要」→「不必要」。反証で見つけた例）。かっこを外しただけ（照らす文のかっこの外に同じ言葉がある）と、
    同じかぎかっこを別の場所に動かしただけ（文書全体の同じ形の数が減っていない）は出さない。"""
    masks = masks or (_Masker(sides, 0), _Masker(sides, 1))
    old_side, new_side = _QuoteSide(sides, 0, masks[0]), _QuoteSide(sides, 1, masks[1])
    out = []
    for group in groups:
        pairs = dict(group["pairs"])
        paired_new = set(pairs.values())
        order = sorted(pairs.items())
        old_count, new_count = len(group["old"]), len(group["new"])
        for i, sentence in enumerate(group["old"]):
            quotes = old_side.quotes.get(sentence.start)
            if not quotes:
                continue
            j = pairs.get(i)
            if j is not None:
                region = [group["new"][j]] + [group["new"][k] for k in _unpaired_neighbors(new_count, j, paired_new)]
            elif new_count:
                # 組にならなかった文は、前後の組の推敲後の文のあいだ（最大6文）と照らす
                earlier = [b for a, b in order if a < i]
                later = [b for a, b in order if a > i]
                low = earlier[-1] if earlier else 0
                high = later[0] if later else new_count - 1
                if high - low > 5:
                    middle = min(new_count - 1, i * new_count // max(1, old_count))
                    low, high = max(low, middle - 2), min(high, middle + 3)
                region = group["new"][low:high + 1]
            else:
                region = []
            region_quotes = [q for s in region for q in new_side.quotes.get(s.start, [])]
            region_keys = set(q[0] for q in region_quotes)
            outside = "\x01".join(new_side.outside.get(s.start, "") for s in region)
            partner_quotes = new_side.quotes.get(group["new"][j].start, []) if j is not None else []
            for index, (key, bracket, content, _) in enumerate(quotes):
                if len(key) < 2 or key in region_keys or key in outside:
                    continue
                if new_side.count[key] >= old_side.count[key]:
                    continue
                best, ratio = None, 0.0
                for candidate in region_quotes:
                    similarity = difflib.SequenceMatcher(None, key, candidate[0], autojunk=False).ratio()
                    if similarity > ratio:
                        best, ratio = candidate, similarity
                if ratio < 0.4 and len(partner_quotes) == len(quotes):
                    # 同じ数のかぎかっこを持つ組の文では、同じ順の言葉を書き換えた先とみなす（「行く」→「行かない」）
                    best, ratio = partner_quotes[index], 1.0
                changed = best is not None and ratio >= 0.4
                if not changed and new_side.count[key]:
                    # 同じ言葉のかぎかっこが推敲後の文書のほかの所に残っていて、この文からは消えただけ（くり返しの名前を
                    # 1か所省いた）なら出さない。言葉を別の言葉に替えた形は上の changed で出る
                    continue
                target = best[3] if changed else (group["new"][j] if j is not None else None)
                out.append(_risk("quote", "changed" if changed else "lost", sentence.line,
                                 target.line if target else None, sentence.text, target.text if target else None,
                                 {"old_quote": content, "new_quote": best[2] if changed else None, "bracket": bracket,
                                  "dialogue": bool(_DIALOGUE.fullmatch(sides.lines[0][sentence.line - 1].strip()))}))
    return out


def _outside_quote(sides, side, body):
    return not _is_quote_row(sides.analyses[side]["lines"][body.line - 1])


def _register_of(text):
    """register() と同じ判定。漢字の「下さい」は仮名の「ください」と同じに読む（register() は9キーの判定なので変えない。
    「実行して下さい」→「実行してください」を常体→敬体と取り違えない。反証で見つけた例）。"""
    return register(text.replace("下さい", "ください"))


def _contained(short, long):
    """short の字のうち long に同じ並びで残る割合。"""
    if not short:
        return 0.0
    blocks = difflib.SequenceMatcher(None, short, long, autojunk=False).get_matching_blocks()
    return sum(block.size for block in blocks) / len(short)


def _neighbor_pairs(order, firsts, i, last):
    """組の並び order（(原文の文, 推敲後の文) を小さい順に並べたもの。firsts はその原文の文の番号の並び）のうち、原文の文が i より前の
    最後の組と、i より後の最初の組の、推敲後の文の番号（前の組がなければ 0、後の組がなければ last）。
    [b for a, b in order if a < i][-1] と [b for a, b in order if a > i][0] と同じ値を、二分探索で求める
    （v2.0.0 は原文の文ごとに組をすべて見ていて、1つの塊に文が数千ある文書で2乗に重くなった）。"""
    before, after = bisect_left(firsts, i), bisect_right(firsts, i)
    return (order[before - 1][1] if before else 0), (order[after][1] if after < len(order) else last)


def _register_changes(sides, groups, politeness):
    threshold = {"min_sentences": 3, "min_ratio": 0.5}
    if any(c["subkind"] == "polite_ratio" for c in politeness.get("candidates", [])):
        return _review_section([], threshold=threshold, skipped_by="politeness")
    masks = (_Masker(sides, 0), _Masker(sides, 1))

    def eligible(side, body):
        return (body is not None and body.text.strip() and _outside_quote(sides, side, body)
                and not _DIALOGUE.fullmatch(sides.lines[side][body.line - 1].strip()))

    counts = []
    for side in (0, 1):
        found = Counter(_register_of(b.text) for b in _all_bodies(sides, side, masks[side]) if eligible(side, b))
        counts.append({"plain": found["常体"], "polite": found["敬体"]})
    changes = {"to_polite": [], "to_plain": []}
    kinds = {("常体", "敬体"): "to_polite", ("敬体", "常体"): "to_plain"}
    for group in groups:
        olds = [masks[0].body(s) for s in group["old"]]
        news = [masks[1].body(s) for s in group["new"]]
        new_registers = [_register_of(b.text) if eligible(1, b) else "" for b in news]
        order = sorted(group["pairs"])
        order_firsts = [i for i, _ in order]
        paired_old = set(order_firsts)
        found = []
        for i, j in order:
            if not eligible(0, olds[i]) or not new_registers[j]:
                continue
            kind = kinds.get((_register_of(olds[i].text), new_registers[j]))
            if kind:
                found.append((i, kind, olds[i], news[j]))
        # 文を合わせた推敲（「設定を開く。保存を押す。」→「設定を開き、保存を押します。」）: 組にならなかった原文の文も、
        # 前後の組の推敲後の文のあいだ（最大6文）に中身の6割以上が残り、その文の文体が切り替わっていれば数える（反証で見つけた例）
        for i, old in enumerate(olds):
            if i in paired_old or not eligible(0, old) or len(old.text) < 4:
                continue
            source = _register_of(old.text)
            if not source:
                continue
            low, high = _neighbor_pairs(order, order_firsts, i, len(news) - 1)
            if high - low > 5:
                middle = min(len(news) - 1, i * len(news) // max(1, len(olds)))
                low, high = max(low, middle - 2), min(high, middle + 3)
            for k in range(max(0, low), min(len(news), high + 1)):
                kind = kinds.get((source, new_registers[k]))
                if kind and _contained(old.text, news[k].text) >= 0.6:
                    found.append((i, kind, old, news[k]))
                    break
        for _, kind, old, new in sorted(found, key=lambda item: item[0]):
            changes[kind].append((old, new))
    out = []
    for kind, source, target in (("to_polite", "plain", "polite"), ("to_plain", "polite", "plain")):
        pairs = changes[kind]
        if len(pairs) < threshold["min_sentences"] or len(pairs) < threshold["min_ratio"] * max(1, counts[0][source]):
            continue
        out.append(_review_candidate(kind, pairs[0][0], pairs[0][1],
                   {"pattern": "unified" if counts[0][target] > counts[0][source] else "switched",
                    "switched": len(pairs), "old_counts": counts[0], "new_counts": counts[1],
                    "lines": [[old.line, new.line] for old, new in pairs[:5]]}))
    return _review_section(out, threshold=threshold, skipped_by=None)


# ---- 事実の穴の候補（check の任意の手がかり。diff の出力には含めない） ----

_GAP_DEGREE = re.compile(
    r"大幅(?:に|な|の)|劇的(?:に|な)|飛躍的(?:に|な)|格段(?:に|の)|著し(?:く|い)|圧倒的(?:に|な)|桁違い|段違い"
    r"|大きく(?=改善|向上|短縮|削減|減|増|変わ|変え|速|下が|上が|低下|上昇|低減|前進|進歩)"
    r"|大きな(?=改善|効果|成果|前進|進歩|変化|向上)")

# 変化の述語。形容詞と和語の動詞は丁寧の形（ました、ます、ています）だけにする（小説や随筆の「短くなった」「首を伸ばした」を
# 拾わない）。漢語の動詞は常体の終止形も拾う。
_GAP_CHANGE = re.compile(
    r"(?:短く|長く|速く|早く|遅く|軽く|重く|多く|少なく|高く|低く|広く|狭く|細かく|厳しく|緩く|ゆるく)"
    r"(?:し(?:ました|ます|ています|ていました)|なり(?:ました|ます)|なって(?:います|いました))"
    r"|(?:増や|減ら|延ば|伸ば|縮め|引き上げ|引き下げ)(?:し(?:ました|ます|ています)|ます|ました)"
    r"|(?:短縮|削減|増加|減少|向上|高速化|軽量化|低減|縮小|拡大|延長|増強|緩和)"
    r"(?:し(?:ました|ます|ています)|され(?:ました|ます|ています)|でき(?:ました|ます)|しました|します"
    r"|した(?=[。]|$)|する(?=[。]|$))")

_GAP_EFFECT = re.compile(
    r"(?:信頼性|安定性|品質|性能|パフォーマンス|使い勝手|利便性|生産性|効率|保守性|可読性|開発体験|体験|満足度|安全性|堅牢性)"
    r"(?:が|を)(?:向上|高ま|高め|改善|上が|上げ|支え|底上げ|強化)"
    r"|(?:混乱|影響|リスク|負担|手間|ダウンタイム|ばらつき)(?:を|が)(?:最小限|最小|低減|軽減|抑え|減ら)"
    r"|(?:改善|最適化|効率化|強化|刷新)(?:しました|します|を行いました|を行います|を実施しました|を図りました|を図ります)"
    r"|シームレス(?:に|な)"
    r"|(?:柔軟な|より良い|最適な)(?:選択肢|運用|対応|体験)")

_GAP_FIGURE = re.compile(
    r"土台(?:づくり|作り)?|(?<!基)礎(?!石)|基盤づくり|第一歩|大きな一歩|一歩前進|連鎖を断ち切|断ち切り"
    r"|道を(?:開|拓|ひら)(?!け)|扉を(?:開|ひら)(?!け)|(?:鍵|カギ)を握|武器(?:に|と)な|強力な武器|景色が(?:変わ|一変)|新たな(?:地平|ステージ|次元)"
    r"|次の(?:ステージ|次元)|底上げ|盤石|追い風|起爆剤|羅針盤|架け橋|屋台骨|息を吹き込|命を吹き込"
    r"|静かに(?:壊れ|失敗|落ち)|黙って(?:無視|捨て|スキップ|破棄|止ま)")

_GAP_NEED = {"degree": "程度の値（何がどれだけ）", "change": "変わる前と後の値", "effect": "何がどう変わるか",
        "figure": "比喩が指す中身（何が起きた、何をした）"}

_GAP_HEDGE = re.compile(r"かもしれ|かも知れ|可能性|予定|未定|未確認|検討中|調査中|見込み|はず|でしょう|だろう|と思|ようです|らしい"
                   r"|おそれ|恐れ|と考えられ|と見られ|れば|なら(?=[、。]|$)|たら(?=[、。]|$)")
# 当たった語のすぐあとの述語が打ち消し（大きく変わりません、一度に大きく変えず）なら出さない
_GAP_NEGATED_TAIL = re.compile(r"^[^、。，！？!?]{0,6}?(?:ない|ません|ず(?![つっ])|なかっ|(?:する|される|した|している)こと(?:は|が)(?:ない|ありません))")
# 意図してぼかした数・時期・相手。この語がある文は出さない（埋めるよう促さない）
_GAP_VAGUE = re.compile(r"一部の|複数|いくつか|数(?:社|時間|分|秒|日|週間|か月|年|倍|割|件|回|人|台|十|百|千|万)|近日|後日|別途|ある取引先|関係者")
# 比べる元がある（「本体より長く」）変化は、値がなくても穴にしない（change だけ）
_GAP_COMPARED = re.compile(r"より")
_GAP_QUESTION = re.compile(r"(?:[？?]|か[。？?])[」』）)]*$")
_GAP_KANJI_NUM = re.compile(r"[〇一二三四五六七八九十百千万]+(?:倍|割|分|秒|時間|日|件|回|人|個|%|％)")
_GAP_SKIP_KINDS = ("code", "frontmatter", "html_block", "table", "heading", "heading_underline", "blank", "thematic_break",
              "reference_definition")
_GAP_ORDER = ("figure", "effect", "degree", "change")
_GAP_NEXT_SENTENCE_RULE = True
_GAP_ASSUMPTION = re.compile(r"もし|仮に|場合|とすれば|としたら|ならば")
_GAP_QUOTE = re.compile(r"「[^」]*」|『[^』]*』")
_GAP_OMISSION = re.compile(r"省きます|省略|伏せ|社外秘|非公開|別途|控え|今後|これからも|引き続き|まいります|ていきます|ていきたい|続けます|に向けて")
BUILTIN_LISTS["fact-gaps"] = tuple((kind, pattern.pattern) for kind, pattern in
                                  (("figure", _GAP_FIGURE), ("effect", _GAP_EFFECT), ("degree", _GAP_DEGREE), ("change", _GAP_CHANGE)))
_LIST_PATTERNS["fact-gaps"] = True


def _gap_has_number(text):
    return bool(extract_numbers(text)) or bool(_GAP_KANJI_NUM.search(text))


def fact_gaps(text, doc_type=None):
    """任意の手がかり。全件数と種類別件数を数え、記録には20件・文80字まで残す。"""
    if doc_type in ("essay", "promo"):
        return {"count": 0, "skipped": doc_type, "by_kind": {}, "items": []}
    doc = _Doc(text)
    rows = doc.analyses[0]["lines"]
    sentences = []
    for index in range(len(doc.lines[0])):
        if index < len(rows) and (rows[index]["kind"] in _GAP_SKIP_KINDS or rows[index].get("quote_depth")):
            continue
        for sentence in _line_sentences(doc, 0, index, index + 1):
            sentences.append(sentence)
    masker = _Masker(doc, 0)
    masker.spans = sorted(masker.spans + [(m.start(), m.end()) for m in _GAP_QUOTE.finditer(text)])
    masker.lefts = [left for left, _ in masker.spans]
    patterns, _ = _load_list("fact-gaps")
    out = []
    for position, sentence in enumerate(sentences):
        body = sentence.text
        if (masker.mask(body, sentence.start) != body or _gap_has_number(body)
                or _GAP_HEDGE.search(body) or _GAP_QUESTION.search(body) or _GAP_VAGUE.search(body)
                or _GAP_OMISSION.search(body) or _GAP_ASSUMPTION.search(body) or _GROUND_CERTAINTY.search(body)):
            continue
        if _GAP_NEXT_SENTENCE_RULE and position + 1 < len(sentences):
            nxt = sentences[position + 1]
            if nxt.line - sentence.line <= 1 and _gap_has_number(nxt.text):
                continue
        found = None
        for kind, pattern in patterns:
            if kind not in _GAP_NEED:
                continue
            for match in pattern.finditer(body):
                if _GAP_NEGATED_TAIL.match(body[match.end():]):
                    continue
                if kind == "change" and _GAP_COMPARED.search(body[:match.start()]):
                    continue
                found = (kind, match.group(0))
                break
            if found:
                break
        if found:
            out.append({"kind": found[0], "line": sentence.line, "sentence": body, "match": found[1],
                        "need": _GAP_NEED[found[0]]})
    counts = dict(Counter(item["kind"] for item in out))
    return {"count": len(out), "skipped": None, "by_kind": counts,
            "items": [dict(item, sentence=item["sentence"][:80]) for item in out[:20]]}


# ---- diff() ----

# ---- 慎重表現・動かしてはいけない値・敬語（mail / paper） ----
# 既存の9キーと推量印の判定は変更しない。慎重表現は独立した節にして、既存の推量印の候補と
# 文単位で重ねない。引用の新しい候補だけは meaning_risks に加える（fail-on の対象）。
NEW_REVIEW_SECTIONS = ("hedges", "immutable", "politeness", "register")
_NEW_SECTION_NAMES = {"hedges": "慎重な言い方", "immutable": "動かしてはいけない値", "politeness": "敬語の度合い", "register": "文体の切り替え"}


def _review_section(candidates, **fields):
    result = {"level": "review", "candidate_count": len(candidates), "candidates": candidates}
    result.update(fields)
    return result


def _review_candidate(subkind, old, new, detail):
    return {"subkind": subkind, "level": "review", "old_line": old.line if old else None,
            "new_line": new.line if new else None, "old": old.raw if old else None,
            "new": new.raw if new else None, "detail": detail}


def _hedges(sides, groups, risks):
    """一覧の語の出現総数が減った文。文の分割先も数え、移動しただけの文は除く。
    同じ文に sentence_type/marks の推量減少か確度の強まりがあれば、独立の候補を出さない。
    同じ強さの言い換えなどで出力から外した推量の印も、重複を避けるために使う。"""
    risks = risks + sides.quiet_marks
    words, _ = _load_list("hedges")
    regex = re.compile("|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))) if words else None
    masks = (_Masker(sides, 0), _Masker(sides, 1))
    marks = [r for r in risks if r["kind"] == "sentence_type" and r["subkind"] == "marks"
             and any(m["kind"] == "推量" for m in r["detail"].get("lost", []))]
    marks += [r for r in risks if r["kind"] == "certainty"
              or (r["kind"], r["subkind"]) == ("certainty_review", "strengthened")]
    out = []
    for group in groups:
        pairs = dict(group["pairs"])
        paired_new = set(pairs.values())
        for i, sentence in enumerate(group["old"]):
            old = masks[0].body(sentence)
            if old is None or regex is None:
                continue
            before = regex.findall(old.text)
            if not before:
                continue
            j = pairs.get(i)
            new = masks[1].body(group["new"][j]) if j is not None else None
            # 分割された後半に慎重表現が残った場合を削除と取り違えない。
            after_text = new.text if new else ""
            if j is not None:
                after_text = _with_unpaired_text(
                    [masks[1].body(s) or _Body("", s.text, s.line, s.start) for s in group["new"]], j, paired_new)
            elif old.raw in sides.texts[1]:
                continue
            after = regex.findall(after_text)
            if len(before) <= len(after):
                continue
            if any(_same_review_sentence(old, r) for r in marks):
                continue
            out.append(_review_candidate("decreased", old, new,
                       {"old_count": len(before), "new_count": len(after),
                        "removed": list((Counter(before) - Counter(after)).elements())}))
    return _review_section(out, **_list_info("hedges"))


# 引用は数値の角括弧か、著者名＋西暦。注記、TODO、リンクのラベルは含めない。
# 英字の著者は、年の前に「,」か「et al.」があるものだけ（(Smith, 2019)、(Smith et al. 2019)）。「(Windows 2000)」
# 「(RFC 2119)」のような製品名・規格名と年の括弧を引用と取らないため（反証で見つけた例）。(Smith 2019) は拾わない。
_CITATION_LATIN = (r"[A-Z][a-z][A-Za-z'’.-]*(?:\s*(?:&|and)\s*[A-Z][A-Za-z'’.-]*)*"
                   r"(?:\s+et\s+al\.[,，]?\s*|[,，]\s*)")
_CITATION_JA = r"[一-鿿々〆ァ-ヴー]+(?:ほか|ら)?[,，]?\s+"
_CITATION = re.compile(
    r"\[[0-9]+(?:\s*[,、–—-]\s*[0-9]+)*\](?!\s*[([])"
    r"|[(（](?:" + _CITATION_JA + "|" + _CITATION_LATIN + r")[12][0-9]{3}[a-z]?[)）]")
# 引用の印は書き方だけの違い（括弧の全角と半角、空白、「、」と「,」、ダッシュの種類）をそろえてから比べる（反証で見つけた例）
_CITATION_KEY = str.maketrans({"（": "(", "）": ")", "，": ",", "、": ",", "–": "-", "—": "-", "−": "-"})


def _citation_key(text):
    return re.sub(r"\s+", "", text.translate(_CITATION_KEY))
# 既存 number が空白つきの mg 等を単位として取らない穴だけを補う。未知の英単語は単位とみなさない。
_SCIENTIFIC_VALUE = re.compile(r"(?<![A-Za-z0-9_.])[0-9]+(?:\.[0-9]+)?[ \t　]*"
                               r"(?:[numcdkMGTμµ]?g|[numcdkμµ]?m(?:ol)?|[numcdkMμµ]?[lL]|[numkMGTμµ]?s|[kMGT]?Hz|[kMGT]?Pa|[kMGT]?W|℃|°C)(?![A-Za-z])")


# 符号は、直前が漢字・片仮名・数字・英字・%・閉じ括弧でないときだけ取る。「10月-12月」「9時-17時」「1万円-2万円」の
# 範囲のハイフンを負の数と取らないため（反証で見つけた例）。そのため「前年比-5%」の符号も見ない（限界）。
_SIGNED_VALUE = re.compile(r"(?<![A-Za-z0-9_.])(?:(?<![一-鿿々〆ァ-ヴー%％)）\]])[+−-])?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


_STATISTIC_VALUE = re.compile(r"(?<![A-Za-z])(?:p|P|α|β|r|t|F|SD|SE)[ \t]*(?:<=|>=|[<>=≤≥])[ \t]*"
                              r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


_EMAIL = re.compile(r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~@-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# 宛名と分かる行頭か「宛先:」の後だけ。名前のあとの助詞（田中さんは）は本文中の言及として対象外。
_ADDRESSEE = re.compile(r"(?m)(?:^[ \t]*(?:宛先[：:][ \t]*)?|(?<=様、)[ \t]*|(?<=さん、)[ \t]*|(?<=様,)[ \t]*|(?<=さん,)[ \t]*)"
                        r"(?P<address>(?P<name>[一-鿿々〆〇○ぁ-ゖァ-ヴーA-Za-zＡ-Ｚａ-ｚ][一-鿿々〆〇○ぁ-ゖァ-ヴーA-Za-zＡ-Ｚａ-ｚ0-9０-９・＆& .　\t]{0,79}?)(?:様|さん))"
                        r"(?=[ \t　]*(?:[、，,：:！!\n]|$))")
# 「さん」「様」が付いても宛名でない語（家族の呼び方など）。名前がこれで終わるものは除く（反証で見つけた例）
_ADDRESSEE_FAMILY = ("婆", "爺", "母", "父", "娘", "息子", "奥", "嫁", "兄", "姉", "坊")
_VALUE_SKIP_KINDS = frozenset(("code", "frontmatter", "html_block", "reference_definition"))


def _value_tokens(sides, side, regex):
    """元の位置を保ってコード・URL等を除く。表・見出しの引用も検査する。"""
    text = sides.texts[side]
    analysis = sides.analyses[side]
    spans = sorted((a, b) for a, b, kind in analysis["protected_spans"] if kind in _BODY_MASK_KINDS)
    lefts = [a for a, _ in spans]
    out = []
    for match in regex.finditer(text):
        a, b = match.span()
        line = sides.line_of(side, a)
        if analysis["lines"][line - 1]["kind"] in _VALUE_SKIP_KINDS:
            continue
        index = max(0, bisect_right(lefts, a) - 1)
        if any(left < b and right > a for left, right in spans[index:index + 2]):
            continue
        if regex is _ADDRESSEE and match.group("name").strip() in ("皆", "みな", "たく", "お客", "お子", "お父", "お母", "お兄", "お姉", "おじい", "おばあ",
                                                                 "お疲れ", "ご苦労", "おかげ", "お陰", "お互い", "逆", "同", "有", "無"):
            continue
        value = (match.group("address") if regex is _ADDRESSEE else match.group()).strip()
        # 「仕様」「模様」等の語末の様は敬称でない（正しい推敲48組の見出しで1件誤検出した）。
        if regex is _ADDRESSEE and value.endswith(("仕様", "模様", "同様", "多様", "異様", "有様", "無様", "一様")):
            continue
        if regex is _ADDRESSEE and match.group("name").strip().endswith(_ADDRESSEE_FAMILY):
            continue
        if regex in (_SCIENTIFIC_VALUE, _STATISTIC_VALUE):
            value = re.sub(r"[ \t　]+", "", value)
        raw = sides.lines[side][line - 1]
        # 比べるのは key（引用は書き方をそろえた形）、出すのは body.text（書いてあるとおり）
        key = _citation_key(value) if regex is _CITATION else value
        out.append((key, _Body(value, raw, line, a)))
    return out


def _value_places(sides, groups):
    """全文差分の塊の行ごとに [組の番号, [(文の始まり, 終わり, 文の番号)]]（元と後）。塊の外の行は変わっていない行。"""
    places = ({}, {})
    for g_index, group in enumerate(groups):
        for side, start_key, end_key, name in ((0, "old_start", "old_end", "old"), (1, "new_start", "new_end", "new")):
            for hunk in group.get("hunks") or [group["hunk"]]:
                for line in range(hunk[start_key], hunk[end_key] + 1):
                    places[side].setdefault(line, [g_index, []])
            for s_index, sentence in enumerate(group[name]):
                entry = places[side].get(sentence.line)
                if entry is not None:
                    entry[1].append((sentence.start, sentence.start + len(sentence.text), s_index))
    return places


def _sentence_at(ranges, position, starts_of):
    """ranges（(始まり, 終わり, 文の番号) の並び）のうち、position を含む最初の範囲の文の番号。なければ None。
    範囲が始まりの順に重ならずに並ぶときは二分探索で引く（1行に文が数千ある文書で、値ごとに行の文をすべて見ると
    文の数の2乗になる）。並びが崩れているときは前から順に見る（どちらも同じ答え）。starts_of は並びごとの始まりの表。"""
    starts = starts_of.get(id(ranges))
    if starts is None:
        ordered = all(ranges[k][1] <= ranges[k + 1][0] for k in range(len(ranges) - 1))
        starts = [a for a, _, _ in ranges] if ordered else False
        starts_of[id(ranges)] = starts
    if starts is False:
        return next((s for a, b, s in ranges if a <= position < b), None)
    k = bisect_right(starts, position) - 1
    if k >= 0 and position < ranges[k][1]:
        return ranges[k][2]
    return None


def _uncancelled_tokens(old, new, places=None, groups=None):
    """同じ値を元と後で打ち消し、残った値（消えた値、足した値）を返す。同じ値の移動は候補にせず、同じ値が2回から1回に
    減ったときは残す。

    places と groups を渡すと、全文差分で変わっていない行の値は除き（両側で同じ）、残りを組の文どうし、同じ塊の中、
    文書全体の順に打ち消す。同じ値が文書に何度もあるとき、位置を見ずに前から打ち消すと、変えていない別の行の値が
    残って候補の行がずれ、既存の数値の候補と重ねない仕組みも効かなかったため（反証で見つけた例）。"""
    tagged = []
    for side, tokens in ((0, old), (1, new)):
        rows = []
        starts_of = {}
        for value, body in tokens:
            if places is None:
                rows.append((value, body, 0, None))
                continue
            entry = places[side].get(body.line)
            if entry is None:
                continue
            rows.append((value, body, entry[0], _sentence_at(entry[1], body.start, starts_of)))
        tagged.append(rows)
    alive = [[True] * len(rows) for rows in tagged]
    pair_maps = [dict(group["pairs"]) for group in groups] if groups is not None else []

    def cancel(old_key, new_key):
        waiting = {}
        for j, row in enumerate(tagged[1]):
            key = new_key(row) if alive[1][j] else None
            if key is not None:
                waiting.setdefault((key, row[0]), []).append(j)
        for i, row in enumerate(tagged[0]):
            key = old_key(row) if alive[0][i] else None
            queue = waiting.get((key, row[0])) if key is not None else None
            if queue:
                j = queue.pop(0)
                alive[0][i] = alive[1][j] = False

    if groups is not None:
        cancel(lambda row: None if row[3] is None or row[3] not in pair_maps[row[2]] else (row[2], pair_maps[row[2]][row[3]]),
               lambda row: None if row[3] is None else (row[2], row[3]))
        cancel(lambda row: row[2], lambda row: row[2])
    cancel(lambda row: 0, lambda row: 0)
    return [[(row[0], row[1]) for k, row in enumerate(rows) if alive[side][k]] for side, rows in enumerate(tagged)]


def _citation_number_covered(old, new, risks):
    """同じ引用の数字だけの変化と、数字を含む印の追加・削除が、同じ行の既存 number で出た場合は重ねない
    （番号や年の変化、[3] の削除は数値の候補として出る）。著者の変化（数字以外の違い）は省かない。
    protected は fail-on 対象でないため、その存在だけで引用の候補を省かない。"""
    a, b = old[0] if old else "", new[0] if new else ""
    if old and new and re.sub(r"[0-9]+", "", a) != re.sub(r"[0-9]+", "", b):
        return False
    if old and new:
        for risk in risks:
            if (risk["kind"] == "number" and risk["subkind"] == "order"
                    and risk.get("old_line") == old[1].line and risk.get("new_line") == new[1].line
                    and risk["detail"].get("old_order") == re.findall(r"[0-9]+", a)
                    and risk["detail"].get("new_order") == re.findall(r"[0-9]+", b)):
                return True
    for side, own, other in (("removed", old, new), ("added", new, old)):
        if own is None:
            continue
        changed = Counter(re.findall(r"[0-9]+", own[0])) - Counter(re.findall(r"[0-9]+", other[0] if other else ""))
        if not changed:
            continue
        line_key = "old_line" if side == "removed" else "new_line"
        reported = Counter()
        for risk in risks:
            if risk["kind"] == "number" and risk.get(line_key) == own[1].line:
                for item in risk["detail"].get(side, []):
                    reported.update(re.findall(r"[0-9]+", item))
        if changed - reported:
            return False
    return bool(Counter(re.findall(r"[0-9]+", a)) != Counter(re.findall(r"[0-9]+", b)))


def _immutable_values(sides, risks, groups=None):
    """引用・宛名・裸のメールアドレスの増減。数字・単位・URLは既存 number/protected に任せる。
    戻り値は (独立の節, meaning_risks に足す引用候補)。既存候補の中身は変えない。
    独立の節の meaning_risk_count は meaning_risks に足した候補の数（run の「値の検査」の行で一緒に数える）。"""
    out, citations = [], []
    places = _value_places(sides, groups) if groups is not None else None
    for kind, regex in (("citation", _CITATION), ("addressee", _ADDRESSEE), ("email", _EMAIL),
                        ("scientific_unit", _SCIENTIFIC_VALUE), ("statistic", _STATISTIC_VALUE), ("number_sign", _SIGNED_VALUE)):
        removed, added = _uncancelled_tokens(_value_tokens(sides, 0, regex), _value_tokens(sides, 1, regex), places, groups)
        if kind == "number_sign":
            # 同じ絶対値の符号だけ変わった穴を補う。数そのものの増減は既存 number に任せる。
            by_value = {}
            for value, body in added:
                by_value.setdefault(value.lstrip("+−-"), []).append((value, body))
            sign_pairs = []
            for own in removed:
                matches = by_value.get(own[0].lstrip("+−-"), [])
                if matches:
                    other = matches.pop(0)
                    if own[0].startswith(("-", "−")) != other[0].startswith(("-", "−")):
                        sign_pairs.append((own, other))
            removed, added = [a for a, _ in sign_pairs], [b for _, b in sign_pairs]
        for index in range(max(len(removed), len(added))):
            old = removed[index] if index < len(removed) else None
            new = added[index] if index < len(added) else None
            if kind == "statistic":
                # 数字の変化は既存 number が扱う。数が同じで比較の印だけ変わった穴に限定する。
                if old is None or new is None or re.findall(r"[0-9.]+", old[0]) != re.findall(r"[0-9.]+", new[0]):
                    continue
                if re.findall(r"<=|>=|[<>=≤≥]", old[0]) == re.findall(r"<=|>=|[<>=≤≥]", new[0]):
                    continue
            if kind == "scientific_unit":
                # 数字・単位の変化を既存 number がすでに報告していれば追加しない。
                covered = True
                for side, own in (("removed", old), ("added", new)):
                    if own is None:
                        continue
                    line_key = "old_line" if side == "removed" else "new_line"
                    if not any(r["kind"] == "number" and r.get(line_key) == own[1].line
                               and own[0] in [re.sub(r"[ \t　]+", "", v) for v in r["detail"].get(side, [])]
                               for r in risks):
                        covered = False
                if covered:
                    continue
            if kind == "citation" and _citation_number_covered(old, new, risks):
                continue
            detail = {"removed": [old[1].text] if old else [], "added": [new[1].text] if new else []}
            item = _review_candidate(kind, old[1] if old else None, new[1] if new else None, detail)
            if kind in ("citation", "scientific_unit", "statistic", "number_sign"):
                subkind = "replaced" if old and new else ("lost" if old else "added")
                citations.append(_risk("citation" if kind == "citation" else "number", subkind, item["old_line"], item["new_line"], item["old"], item["new"], detail))
            else:
                out.append(item)
    return _review_section(out, meaning_risk_count=len(citations)), citations


POLITENESS_THRESHOLD = 0.20
# 活用形も数える。長い「させていただく」を先に取り、いただくと二重に数えない。
_MAIL_HONORIFIC = re.compile(r"(?P<causative>させていただ(?:く|き|け|い|か))|(?P<receive>いただ(?:く|き|け|い|か))"
                        r"|(?P<give>くださ(?:る|り|れ|い|っ|ら))|(?P<say>申し上げ(?:る|ま|た|て))|(?P<know>存じま(?:す|した|せん))")
_MAIL_HONORIFIC_NAMES = {"causative": "させていただく", "receive": "いただく", "give": "くださる", "say": "申し上げる", "know": "存じます"}
_POLITE_END = re.compile(r"(?:です|でした|ます|ました|ません|ませんでした)(?:か|ね|よ|よね)?$")
_PLAIN_END = re.compile(r"(?:だ|だった|である|であった)(?:ね|よ)?$")


def _politeness_metrics(bodies):
    counts = dict((name, 0) for name in _MAIL_HONORIFIC_NAMES.values())
    polite = plain = 0
    for body in bodies:
        for match in _MAIL_HONORIFIC.finditer(body.text):
            counts[_MAIL_HONORIFIC_NAMES[match.lastgroup]] += 1
        end = bare_end(body.text)
        polite += bool(_POLITE_END.search(end))
        plain += bool(_PLAIN_END.search(end))
    return {"sentences": len(bodies), "honorifics": counts, "honorific_count": sum(counts.values()),
            "honorific_rate": sum(counts.values()) / len(bodies) if bodies else 0.0,
            "polite_endings": polite, "plain_endings": plain,
            "polite_ratio": polite / (polite + plain) if polite + plain else None}


def _politeness(sides, doc_type):
    """mail だけ。敬語5家族の出現数/本文の文数、敬体/(敬体+だ・である)の差が0.20以上なら候補。
    分母0の文末は比較しない。体言止め・口語を無理に常体とみなさない。件数と割合を記録し、合否には使わない。"""
    if doc_type != "mail":
        return _review_section([], applicable=False, threshold=POLITENESS_THRESHOLD, metrics=None)
    bodies = [_all_bodies(sides, side) for side in (0, 1)]
    old, new = [_politeness_metrics(rows) for rows in bodies]
    out = []
    for key in ("honorific_rate", "polite_ratio"):
        a, b = old[key], new[key]
        if a is not None and b is not None and abs(a - b) + 1e-12 >= POLITENESS_THRESHOLD:
            samples = [next((body for body in rows if (_MAIL_HONORIFIC.search(body.text) if key == "honorific_rate"
                       else _POLITE_END.search(bare_end(body.text)) or _PLAIN_END.search(bare_end(body.text)))), None)
                       for rows in bodies]
            out.append(_review_candidate(key, samples[0], samples[1],
                                         {"old_ratio": a, "new_ratio": b, "threshold": POLITENESS_THRESHOLD}))
    return _review_section(out, applicable=True, threshold=POLITENESS_THRESHOLD, metrics={"old": old, "new": new})


def _new_review_section(d, key):
    section = d.get(key) or {}
    candidates = section.get("candidates") or []
    notes = []
    if section.get("list_problem"):
        notes.append(_LIST_NOTE.format("慎重な言い方の一覧", "hedges", section["list_problem"]))
    if not candidates and not notes:
        return ""
    label = _NEW_SECTION_NAMES[key]
    lines = ["■ {}（見直し候補 {}件）".format(label, len(candidates))] + notes
    for item in candidates:
        detail = item["detail"]
        where = _where(item["old_line"], item["new_line"])
        if key == "hedges":
            text = "慎重な言い方が減りました{}: {} → {}（{}）。断定に変わっていないか確かめてください。".format(
                where, detail["old_count"], detail["new_count"], "、".join(detail["removed"]))
        elif key == "immutable":
            text = "{}が変わりました{}: {} → {}".format("宛名" if item["subkind"] == "addressee" else "メールアドレス", where,
                       "、".join(detail["removed"]) or "なし", "、".join(detail["added"]) or "なし")
        elif key == "register":
            to_polite = item["subkind"] == "to_polite"
            source, target = ("常体", "敬体") if to_polite else ("敬体", "常体")
            old_counts, new_counts = detail["old_counts"], detail["new_counts"]
            if detail["pattern"] == "unified":
                text = ("原文で揺れていた文末を{}にそろえました（{}{}文 → {}。原文: 常体{}文・敬体{}文）。"
                        "多いほうにそろえたなら残してよいですが、意図した変更か確かめてください。".format(
                            target, source, detail["switched"], target, old_counts["plain"], old_counts["polite"]))
            else:
                text = ("{}の文を{}に変えました（{}文中{}文。原文: 常体{}文・敬体{}文 → 推敲後: 常体{}文・敬体{}文）。"
                        "原文の文体を保つのが基本です。意図した切り替えでなければ、原文の文末に戻してください。".format(
                            source, target, old_counts["plain" if to_polite else "polite"], detail["switched"],
                            old_counts["plain"], old_counts["polite"], new_counts["plain"], new_counts["polite"]))
            text += "読み手に合わせて意図して変えたなら残し、「変えたところ」に書いてください。"
        else:
            text = "{}が変わりました: {:.1%} → {:.1%}。相手への敬語の度合いを確かめてください。".format(
                "1文あたりの敬語の数" if item["subkind"] == "honorific_rate" else "です・ますの割合",
                detail["old_ratio"], detail["new_ratio"])
        lines.append("- " + text)
        for field, label in (("old", "元"), ("new", "後")):
            if item.get(field) is not None:
                lines.append("  {}: {}".format(label, item[field]))
        if key == "register" and len(detail["lines"]) > 1:
            lines.append("  ほか: " + "、".join("元{}行目 → 後{}行目".format(a, b) for a, b in detail["lines"][1:]))
    return "\n".join(lines)


def diff(orig_raw: str, rw_raw: str, stance=None, *, encoding_notes=None, doc_type=None, reader=None, words=None) -> dict:
    """元の文と書き直した文を比べる（JSON の形式2）。

    渡された文字列をそのまま使う（BOM を外したり、改行をそろえたりしない。CLI と check は読むときに decode_source で
    そろえ、違いを encoding_notes で渡す）。stance は STANCES の値（勧め、決まり、説明）か None。
    doc_type（文書の種類）と reader（読者）は context に残す。差分と、意味が変わる恐れの候補の見つけ方は変えない
    （種類と読者を指定しても同じ規則）。事実や仕様を述べる種類（COUNTED_TYPES）だけ、確度の2つ（「場合がある」「ことがある」を
    消した言い切り、断定に「必ず」などを足した書き換え）を --fail-on に数える側に入れる。能力の言い方の消え（ability_lost）は、
    どの種類でも数えない候補（modality_review）。文体の硬化の検査（stiffness）と勢いの検査（tone）は、種類で level を決める
    （paper の硬化と勢いも参考の info。mail の勢いは絵文字・見出しも review）。mail だけ敬語の度合いも検査する。値は中で正規化し、使えない値は ValueError。
    words は語の一覧（markdown_visibility.resolve_words の値）。渡すと context.words（場所、語の数、SHA-256）に残すだけで、
    差分と候補は変えない（diff には allow.txt で外す規則がない）。None なら一覧なし。"""
    context = {"doc_type": normalize_doc_type(doc_type), "reader": normalize_reader(reader)}
    if words is not None:
        context["words"] = words_context(words)
    try:
        rules = _rule_candidates(orig_raw, rw_raw, stance)
        # 許可・能力の言い方と、選ぶ範囲・因果の言い方は、9キーの分析（_rule_candidates の type_changes）が作った範囲を
        # 使い回して比べる
        o, r = normalize(orig_raw), normalize(rw_raw)
        modality = _modality_changes(o, r)
        logic = _logic_changes(o, r)
    finally:
        _LAST_TYPE_RANGES[0] = None
    full, sides = _build_full_diff(orig_raw, rw_raw, encoding_notes)
    # 見出しの数、段、見出しと本文の行の入れ替わりは、全文差分の注記だけでなく「構造」の見直し候補にも出す
    rules["structure"].extend(_heading_structure(sides, full["hunks"]))
    groups = _sentence_pairs(sides, full)
    risks = _meaning_risks(sides, full, rules["type_changes"], groups, doc_type=context["doc_type"], modality=modality,
                           logic=logic)
    if orig_raw == rw_raw and not full["encoding_notes"]:
        status, count = "no_change", 0
    else:
        count = sum(1 for risk in risks if (risk["kind"], risk["subkind"]) != ("sentence_type", "marks"))
        count += _rule_count(rules, bool(full["hunks"]))
        status = "has_candidates" if count else "changed_without_candidates"
    out = {"format": "yomiyasu-diff", "format_version": DIFF_FORMAT_VERSION, "tool_version": __version__,
           "status": status, "changed": status != "no_change", "candidate_count": count,
           "meaning_risk_count": len(risks), "fail_on_meaning_risk_count": fail_on_count(risks),
           "not_judged": ["meaning_equivalence", "reader_comprehension"], "context": context, "meaning_risks": risks}
    out.update(rules)
    out["full_diff"] = full
    # diff の詰め: 文体の硬化の検査と勢いの検査。どちらも見直し候補を出すだけで、
    # candidate_count、状態、--fail-on には入れない（既存の出力の形を変えないよう、最後のキーとして足す）
    out["stiffness"] = _stiffness(sides, full, groups, context["doc_type"])
    out["tone"] = _tone(sides, full, context["doc_type"], groups)
    # diff の詰めの直し: 気持ちの語（meaning_risks の kind feeling）の一覧の出どころ（stiffness.list、tone.list と同じ形。
    # 反証で見つけた例）
    out["feeling"] = _list_info("feelings")
    out["hedges"] = _hedges(sides, groups, risks)
    out["immutable"] = sides.immutable
    out["politeness"] = _politeness(sides, context["doc_type"])
    out["register"] = _register_changes(sides, groups, out["politeness"])
    return out


def _shows_rewritten_only(d):
    """書き直した文だけを見る候補（logic、bold、endings.flags）を数え、出すか。
    変更がない（no_change）か、行の差がない（改行コード、BOM、末尾の改行だけが違う）ときは出さない。"""
    return d.get("status") != "no_change" and bool(d["full_diff"]["hunks"])


def _rule_count(d, rewritten_only):
    """規則の見直し候補の数（レポートの行の数に合わせる）。"""
    e = d.get("endings") or {}
    count = (len(d["markers"]) + bool(d["new_words"]) + bool(d["lost_words"]) + len(d["structure"])
             + len(e.get("changes") or []) + len(d.get("type_changes") or []))
    if rewritten_only:
        count += len(d.get("logic") or []) + len(e.get("flags") or []) + len(d.get("bold") or [])
    return count



# ---- 人が読む出力（v2.0.0）----

_REPORT_FIRST_LINE = "差分の検査を実行しました。"
_REPORT_DISCLAIMER = ("全文差分は変わった箇所を示すだけで、意味が同じだという証明ではありません。"
                      "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。")
# 種類か読者を指定したときに、断りの行のすぐあとに足す1行の後半
_REPORT_CONTEXT_TAIL = "候補の見つけ方は種類と読者によらず同じです。"
# 事実や仕様を述べる種類（COUNTED_TYPES）を指定したときに、その後ろに足す文
_REPORT_COUNTED_TAIL = ("この種類では、「場合がある」「ことがある」を消した言い切りと、断定に「必ず」などを足した書き換えも"
                        " --fail-on に数えます。")


def detector_review_count(d):
    """文体の硬化の検査と勢いの検査の見直し候補（level review）の数。参考（info）は数えない。d にその検査の結果がなければ0。"""
    count = 0
    for key in ("stiffness", "tone"):
        section = d.get(key) if isinstance(d, dict) else None
        if isinstance(section, dict) and isinstance(section.get("candidates"), list):
            count += sum(1 for candidate in section["candidates"]
                         if isinstance(candidate, dict) and candidate.get("level") == "review")
    return count


# 状態の行の末尾に足す文（diff の詰めの直し。反証で見つけた例）。硬化と勢いの候補は candidate_count と状態に入れない
# ので、見直し候補（review）があるときだけ、節があることを添える（「候補はない」と「見直し候補 1件」が並ぶのを防ぐ）。
# レポートの最後の状態の行では、節はその上にあるので「上の節」と書く（反証で見つけた例）
_DETECTOR_STATUS_NOTE = "（文体の硬化と勢いの見直し候補 {}件は下の節）"
_DETECTOR_STATUS_NOTE_ABOVE = "（文体の硬化と勢いの見直し候補 {}件は上の節）"


def _status_line(d, note=_DETECTOR_STATUS_NOTE):
    """状態の行。変更の数は hunk の数。文体の硬化と勢いの見直し候補があれば、末尾にその数を添える（note。レポートの
    最後の行では _DETECTOR_STATUS_NOTE_ABOVE）。"""
    if d["status"] == "no_change":
        return "状態: 変更なし"
    places = len(d["full_diff"]["hunks"])
    if d["status"] == "changed_without_candidates":
        if not places:
            return "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 0か所。改行コード・BOM・末尾の改行だけが違う）"
        line = "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 {}か所）".format(places)
    else:
        line = "状態: 変更あり（{}か所）。見直し候補 {}件、うち意味が変わる恐れ {}件".format(
            places, d["candidate_count"], d["meaning_risk_count"])
    reviews = detector_review_count(d)
    line = line + note.format(reviews) if reviews else line
    extra = sum((d.get(key) or {}).get("candidate_count", 0) for key in NEW_REVIEW_SECTIONS)
    if extra:
        label = "慎重表現・値・敬語"
        if (d.get("register") or {}).get("candidate_count", 0):
            label += "・文体の切り替え"
        line += "（{}の見直し候補 {}件は{}の節）".format(label, extra, "上" if note == _DETECTOR_STATUS_NOTE_ABOVE else "下")
    return line


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
    if kind == "state":
        return ("状態の語が消えた{}: {}。原文は、まだ決まっていない・分かっていない・済んでいないことを伝えています。"
                "決まった・済んだ・約束した形に変えていないか確かめ、変えていれば原文の状態に戻してください。".format(
                    where, "、".join(detail["words"])))
    if kind == "promise":
        label = {"added": "書き手の約束", "guarantee": "保証", "prevention": "再発防止の誓い"}[subkind]
        advice = "依頼にない誓いなら外してください。" if subkind == "prevention" else "原文と依頼にない{}なら外してください。".format(
            "約束" if subkind == "added" else "保証")
        return "原文にない{}{}: {}。{}".format(label, _where(None, new_line),
                "、".join("「{}」".format(p) for p in detail["phrases"]), advice)
    if kind in ("modality", "modality_review"):
        change = "{} → {}".format(_modality_side(detail["from"], detail["lost"]), _modality_side(detail["to"], detail["added"]))
        if subkind == "permission_lost":
            return ("許可の言い方が消えた{}: {}。原文は「〜してよい」と、してもよいことを伝えています。できることの説明や言い切りに"
                    "変えていないか確かめ、変えていれば原文の言い方に戻してください。".format(where, change))
        if subkind == "permission_added":
            return ("原文にない許可の言い方{}: {}。原文は、してもよいとは書いていません。依頼にない許可を足していないか確かめ、"
                    "足していれば原文の言い方に戻してください。".format(where, change))
        note = "" if kind == "modality" else "--fail-on には数えません。"
        return ("能力の言い方が消えた{}: {}。{}原文は「〜できる」と、できることを伝えています。「〜する」「必ず〜する」と"
                "言い切っていないか確かめ、言い切っていれば原文の言い方に戻してください。".format(where, change, note))
    if kind == "choice":
        change = "{}（{}） → {}（{}）".format(detail["from"], "、".join(detail["old_hits"]), detail["to"], "、".join(detail["new_hits"]))
        if subkind == "one_to_all":
            return ("選ぶ範囲が「どれか一つ」から「全部」に変わった{}: {}。原文は、どれか一つでよい・どれか一つに当てはまると"
                    "伝えています。全部が要る・全部に当てはまる意味に変えていないか確かめ、変えていれば原文の言い方に戻してください。"
                    .format(where, change))
        return ("選ぶ範囲が「全部」から「どれか一つ」に変わった{}: {}。原文は、全部が要る・全部に当てはまると伝えています。"
                "どれか一つでよい意味に変えていないか確かめ、変えていれば原文の言い方に戻してください。".format(where, change))
    if kind == "causality":
        return ("関連の言い方が因果の言い方に変わった{}: {}（{}） → {}（{}）。原文は、関連や相関があると述べているだけで、"
                "原因と結果とは書いていません。因果の主張に強めていないか確かめ、強めていれば原文の言い方に戻してください。".format(
                    where, detail["from"], "、".join(detail["old_hits"]), detail["to"], "、".join(detail["new_hits"])))
    if kind == "number_qualifier":
        def side(number, names, markers):
            label = "・".join(_QUALIFIER_LABELS[name] for name in names) or "印なし"
            return "{}（{}）".format(number, label) if not markers else "{}（{}: {}）".format(number, label, "、".join(markers))
        change = "{} → {}".format(side(detail["old_number"], detail["from"], detail["old_markers"]),
                                  side(detail["new_number"], detail["to"], detail["new_markers"]))
        if subkind == "lost":
            advice = ("原文は、数に概数か範囲の印を付けています。印を落として、ちょうどその数と読める書き方に変えていないか"
                      "確かめ、変えていれば原文の印を戻してください。")
        elif subkind == "added":
            advice = ("原文は、数に概数や範囲の印を付けていません。依頼にない印を足して、数の意味を変えていないか確かめ、"
                      "足していれば外してください。")
        else:
            advice = ("原文と印の種類が違います（以上と超、以下と未満は、その数を含むかどうかが違います）。数の範囲を"
                      "変えていないか確かめ、変えていれば原文の印に戻してください。")
        return "数に付いた概数・範囲の印が変わった{}: {}。{}".format(where, change, advice)
    if kind == "promise_review":
        return ("原文にない「〜します」{}: {}。--fail-on には数えません。説明や手順の文なら残し、"
                "書き手の約束として足したのなら外してください。".format(
                    _where(None, new_line), "、".join("「{}」".format(p) for p in detail["phrases"])))
    if kind == "claim":
        quoted = "、".join("「{}」".format(w) for w in detail["words"])
        reason = {"joined": "原文の別々の文を因果でつないでいます。",
                  "time_to_cause": "原文の時を言う言い方（〜時に、〜際に）を、原因の言い方に変えています。"}.get(
                      detail["reason"], "原文にない原因や効き目を足しています。")
        return ("原文にない因果のつながり{}: {}。{}原文が事実を並べていただけなら、"
                "つなぎの語を外して並べてください。".format(where, quoted, reason))
    if kind in ("certainty", "certainty_review"):
        if kind == "certainty":
            label = "確度が強まった"
        elif subkind == "strengthened":
            label = "確度が強まった恐れ（数えない変化）"
        else:
            label = "確度が弱まった"
        steps = []
        for step in detail["steps"]:
            target = "なし（断定）" if step["to"] == "断定" else step["to"]
            steps.append("{} → {}（{} → {}）".format(step["from"], target,
                         _CERTAINTY_LEVELS[step["from_level"]], _CERTAINTY_LEVELS[step["to_level"]]))
        advice = ("原文にない慎重さを足していないか確かめてください。" if subkind == "weakened"
                  else "原文の確かさに戻すか確かめてください。")
        return "{}{}: {}。{}".format(label, where, "、".join(steps), advice)
    if kind == "quote":
        prefix = "会話の" if detail["dialogue"] else ""
        bracket = detail["bracket"]
        old_quote = bracket[0] + detail["old_quote"] + bracket[1]
        if subkind == "lost":
            return "{}かぎかっこの中の言葉が推敲後にない{}: {}".format(prefix, _where(old_line, None), old_quote)
        return "{}かぎかっこの中の言葉が変わった{}: {} → {}{}{}".format(
            prefix, where, old_quote, bracket[0], detail["new_quote"], bracket[1])
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
    if kind == "citation":
        return "引用の印が変わった{}: {} → {}".format(where, "、".join(detail.get("removed", [])) or "なし",
                                              "、".join(detail.get("added", [])) or "なし")
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
    if kind == "contrast_reversal":
        return ("否定対比の主張が逆になった恐れ{}: 原文で否定されていた『{}』が、推敲後は否定のない文に出ています。"
                "主張が逆になっていないか確かめてください。".format(where, detail.get("word", "")))
    if kind == "feeling":
        return "元にない気持ちの語{}: {}".format(where, "、".join(detail.get("words", [])))
    if kind == "unsupported":
        # 資料との照合（check が ground() の結果を同じ節に並べる）。最終稿の側の行だけを書く
        label = "資料にない数値" if subkind == "number" else "資料にない名前"
        return "{}{}: {}".format(label, _where(None, new_line) if new_line is not None else where, detail.get("text", ""))
    return "{}{}".format(kind + ("/" + subkind if subkind else ""), where)


def _modality_side(names, items):
    """許可・能力の候補の行の片側（「許可（てよい）」「能力（られる）」「なし（断定）」）。names は detail の from か to、
    items はその側の印（from は detail の lost、to は added）。"""
    if names == "断定":
        return "なし（断定）"
    members = dict(_MODALITY_NAMES)
    parts = []
    for name in names.split("・"):
        hits = [hit for item in items if item["kind"] in members.get(name, (name,)) for hit in item["hits"]]
        parts.append("{}（{}）".format(name, "、".join(hits)) if hits else name)
    return "、".join(parts)


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


def _line_where(old_line, new_line):
    if old_line is not None and new_line is not None:
        return "{}行目".format(new_line) if old_line == new_line else "元{}行目 → 後{}行目".format(old_line, new_line)
    if new_line is not None:
        return "後{}行目".format(new_line)
    return "元{}行目".format(old_line) if old_line is not None else ""


def _stiffness_line(candidate):
    """文体の硬化の候補の1行（先頭の「- 」と「（参考）」は付けない）。"""
    subkind, detail = candidate["subkind"], candidate.get("detail") or {}
    tail = "硬い言い方に寄っていないか確かめてください。"
    if subkind == "sentence":
        return "{}の文で、漢字の割合が{:.0f}%から{:.0f}%に増えました（{}字→{}字）。{}".format(
            _line_where(candidate["old_line"], candidate["new_line"]), detail["old_kanji_ratio"], detail["new_kanji_ratio"],
            detail["old_length"], detail["new_length"], tail)
    if subkind == "sentence_nominal":
        return "{}の文に、名詞化の言い回し（{}）が出て、漢字が{}字増えました。{}".format(
            _line_where(candidate["old_line"], candidate["new_line"]), "、".join(detail["added_names"]),
            detail["new_kanji"] - detail["old_kanji"], tail)
    if subkind == "document":
        # 平均の文の長さは、表示する値（整数に丸めた値）で増えたかを決める（17.5字 → 18.5字は、どちらも18字と表示するので
        # 「増えました」と書かない。diff の詰めの直し、反証で見つけた例）
        old_avg, new_avg = "{:.0f}".format(detail["old_avg_length"]), "{:.0f}".format(detail["new_avg_length"])
        if int(new_avg) > int(old_avg):
            text = "推敲後、漢字の割合が{:.0f}%から{:.0f}%に、平均の文の長さが{}字から{}字に増えました。".format(
                detail["old_kanji_ratio"], detail["new_kanji_ratio"], old_avg, new_avg)
        elif new_avg == old_avg:
            text = "推敲後、漢字の割合が{:.0f}%から{:.0f}%に増えました（平均の文の長さは{}字のまま）。".format(
                detail["old_kanji_ratio"], detail["new_kanji_ratio"], old_avg)
        else:
            text = "推敲後、漢字の割合が{:.0f}%から{:.0f}%に増えました（平均の文の長さは{}字から{}字）。".format(
                detail["old_kanji_ratio"], detail["new_kanji_ratio"], old_avg, new_avg)
        example = detail.get("example")
        if example:
            return text + "硬い文体に寄っていないか確かめてください（例：{}『{}』→『{}』）。".format(
                _line_where(example["old_line"], example["new_line"]), example["old"], example["new"])
        return text + "硬い文体に寄っていないか確かめてください。"
    if subkind == "nominalization":
        return "名詞化の言い回し（{}）が{}個から{}個に増えました（後{}行目など）。{}".format(
            "、".join(detail["added_names"]), detail["old"], detail["new"],
            "、".join(str(line) for line in detail["new_lines"][:3]) or "?", tail)
    if subkind == "no_chain":
        return "後{}行目に「の」が続く形（『{}』）が出ました。原文にない形です。{}".format(
            candidate["new_line"], detail["chains"][0], tail)
    return subkind


def _tone_place(place):
    """勢いの候補の位置1つ（「3行目『…』→『…』」「元3行目『…』を削除」）。"""
    if place["new"] is None:
        return "{}『{}』を削除".format(_line_where(place["old_line"], None), place["old"])
    return "{}『{}』→『{}』".format(_line_where(place["old_line"], place["new_line"]), place["old"], place["new"])


def _tone_more_places(candidate):
    """勢いの候補の2か所目からの行（TONE_PLACES_SHOWN か所まで。超えた分は「ほか N か所」）。diff の詰めの直しで、
    硬化の節のように行を並べるようにした（反証で見つけた例）。"""
    places = (candidate.get("detail") or {}).get("places") or []
    rows = ["  " + _tone_place(place) for place in places[1:TONE_PLACES_SHOWN]]
    if len(places) > TONE_PLACES_SHOWN:
        rows.append("  ほか{}か所".format(len(places) - TONE_PLACES_SHOWN))
    return rows


def _tone_line(candidate):
    """勢いの検査の候補の1行（先頭の「- 」と「（参考）」は付けない）。位置は1か所目だけ（2か所目からは _tone_more_places）。"""
    subkind, detail = candidate["subkind"], candidate.get("detail") or {}
    places = detail.get("places") or []
    shown = "（" + _tone_place(places[0]) + "）" if places else ""
    tail = "書き手の勢いを落としていないか確かめてください。"
    if subkind == "heading":
        return "見出しの字数の合計が{}字から{}字（原文の{:.0f}%）になりました{}。{}".format(
            detail["old"], detail["new"], 100.0 * detail["new"] / detail["old"], shown, tail)
    if subkind == "intensifier":
        label = "強める語（{}）".format("、".join(detail.get("words") or [])) if detail.get("words") else "強める語"
    else:
        label = _TONE_LABELS.get(subkind, subkind)
    return "原文の{}{}個が、推敲後は{}個になりました{}。{}".format(label, detail["old"], detail["new"], shown, tail)


# 一覧のファイルを読めなかったときに、硬化と勢いの節に出す1行（diff の詰めの直し。反証で見つけた例）。硬化の節には
# 名詞化の言い回しの一覧、勢いの節には強める語の一覧と気持ちの語の一覧（気持ちの語の検査には自分の節がないので、勢いの節に置く）
_LIST_NOTE_LABELS = (("stiffness", "stiffness", "nominalization", "名詞化の言い回しの一覧"),
                     ("tone", "tone", "intensifiers", "強める語の一覧"),
                     ("tone", "feeling", "feelings", "気持ちの語の一覧（意味が変わる恐れの「元にない気持ちの語」に使う）"))
_LIST_NOTE = "- {} references/lists/{}.txt を読めなかったので、内蔵の一覧で検査しました（{}）。ファイルに足し引きした語は効いていません。"


def _list_notes(d, key):
    """節 key（stiffness か tone）に出す、一覧を読めなかったことの行。"""
    notes = []
    for section_key, json_key, name, label in _LIST_NOTE_LABELS:
        if section_key != key:
            continue
        info = d.get(json_key)
        problem = info.get("list_problem") if isinstance(info, dict) else None
        if problem:
            notes.append(_LIST_NOTE.format(label, name, problem))
    return notes


def _detector_section(d, key):
    """「■ 文体の硬化」と「■ 勢い」の節（候補がなければ空の文字列。一覧のファイルを読めなかったときは、候補がなくても
    「■ …（一覧の注意）」の節にその行を出す）。参考（level info）の候補は行の頭に「（参考）」。
    見直し候補と参考が混ざるとき（勢いで、promo 以外の種類を指定して絵文字か見出しの候補が出たとき）は、節の見出しに両方の
    件数を書く。"""
    section = d.get(key) or {}
    candidates = section.get("candidates") or []
    notes = _list_notes(d, key)
    if not candidates:
        if not notes:
            return ""
        # 一覧を読めなかったことは、候補がなくても知らせる（足し引きした語が黙って効かないのを防ぐ。反証で見つけた例）。
        # report() は「（候補なし）」を返さないので、節の見出しは一覧の注意だけを言う（反証で見つけた例）
        return "\n".join(["■ {}（一覧の注意）".format("文体の硬化" if key == "stiffness" else "勢い")] + notes)
    infos = sum(1 for candidate in candidates if candidate.get("level") == "info")
    reviews = len(candidates) - infos
    doc_type = (d.get("context") or {}).get("doc_type")
    if key == "stiffness":
        name, render = "文体の硬化", _stiffness_line
        review = "硬い言い方に寄っていないか確かめる"
        reference = "文書の種類 {} では硬い言い方が普通なので、参考として出しています".format(doc_type)
    else:
        name, render = "勢い", _tone_line
        review = "書き手の勢いを落としていないか確かめる"
        if doc_type in TONE_INFO_DOC_TYPES:
            # 参考にした候補（「！」「？」と強める語、絵文字、見出し）の直し方だけを書く（反証で見つけた例）
            shown = set(candidate.get("subkind") for candidate in candidates if candidate.get("level") == "info")
            rules = [rule for rule in _TONE_INFO_RULES if shown.intersection(rule[0])] or [_TONE_INFO_RULES[0]]
            reference = "文書の種類 {} では{}のが正しい直し方のことが多いので、参考として出しています".format(
                doc_type, "、".join([rule[1] for rule in rules[:-1]] + [rules[-1][2]]))
        else:
            # 参考になった候補（絵文字、見出し）の決まりだけを書く（minutes の見出しのように見直し候補のままの候補の決まりは
            # 書かない。反証で見つけた例）
            shown = set(candidate.get("subkind") for candidate in candidates if candidate.get("level") == "info")
            rules = [rule for rule in _TONE_TYPED_RULES if rule[0] in shown] or list(_TONE_TYPED_RULES)
            reference = "文書の種類 {} では{}のが決まりなので、参考として出しています".format(
                doc_type, "、".join([rule[1] for rule in rules[:-1]] + [rules[-1][2]]))
    if not reviews:
        lines = ["■ {}（参考 {}件。{}）".format(name, infos, reference)]
    elif infos:
        lines = ["■ {}（見直し候補 {}件、参考 {}件。{}）".format(name, reviews, infos, review)]
    else:
        lines = ["■ {}（見直し候補 {}件。{}）".format(name, reviews, review)]
    lines.extend(notes)
    for candidate in candidates:
        lines.append("- " + ("（参考）" if candidate.get("level") == "info" else "") + render(candidate))
        if key == "stiffness":
            if candidate.get("old") is not None:
                lines.append("  元: " + candidate["old"])
            if candidate.get("new") is not None:
                lines.append("  後: " + candidate["new"])
        else:
            lines.extend(_tone_more_places(candidate))
    return "\n".join(lines)


def detector_summary(d, key):
    """完了報告の確認の記録に写す値（「候補なし」「候補{n}件」、参考だけなら「参考{n}件」、見直し候補と参考が混ざれば
    「候補{n}件、参考{m}件」）。key は stiffness、tone、hedges、immutable、politeness、register。d にその検査の結果がなければ None。"""
    section = d.get(key) if isinstance(d, dict) else None
    if not isinstance(section, dict) or section.get("applicable") is False:
        return None
    count = section.get("candidate_count") or 0
    risky = section.get("meaning_risk_count") or 0 if key == "immutable" else 0
    if risky:
        # 値の検査で意味が変わる恐れに入れた候補（引用の印、数値の補い）も数える（反証で見つけた例）
        return "{}意味が変わる恐れ {}件".format("候補{}件、".format(count) if count else "", risky)
    if not count:
        return "候補なし"
    candidates = section.get("candidates")
    if not isinstance(candidates, list):
        return "{}{}件".format("参考" if section.get("level") == "info" else "候補", count)
    infos = sum(1 for candidate in candidates if isinstance(candidate, dict) and candidate.get("level") == "info")
    if infos >= count:
        return "参考{}件".format(count)
    if infos:
        return "候補{}件、参考{}件".format(count - infos, infos)
    return "候補{}件".format(count)


def report_parts(d: dict) -> dict:
    """レポートの節の文字列（{"risks", "rules", "stiffness", "tone", "full_diff"}）。ない節は空の文字列。末尾に改行は付けない。
    stiffness と tone は diff の詰めで足した（文体の硬化の検査と勢いの検査。候補がなければ空）。"""
    return {"risks": _risk_section(d), "rules": _rule_section(d), "stiffness": _detector_section(d, "stiffness"),
            "tone": _detector_section(d, "tone"), "full_diff": _full_diff_section(d),
            **{key: _new_review_section(d, key) for key in NEW_REVIEW_SECTIONS}}


def report(d: dict) -> str:
    """人が読むレポート。1行目、状態の行、断り、意味が変わる恐れ、規則の見直し候補、文体の硬化、勢い、全文差分、
    状態の行の順（文体の硬化と勢いは diff の詰めで足した。候補がなければ出さない）。最後の状態の行の添え書きは「上の節」。
    末尾に改行は付けない。"""
    status = _status_line(d)
    parts = report_parts(d)
    body = [part for part in (parts["risks"], parts["rules"], parts["stiffness"], parts["tone"],
                             parts["hedges"], parts["immutable"], parts["politeness"], parts["register"], parts["full_diff"]) if part]
    head = [_REPORT_FIRST_LINE, status, _REPORT_DISCLAIMER]
    context = d.get("context") or {}
    if context.get("doc_type") is not None or context.get("reader") is not None:
        head.append(context_label(context.get("doc_type"), context.get("reader")) + _REPORT_CONTEXT_TAIL
                    + (_REPORT_COUNTED_TAIL if context.get("doc_type") in COUNTED_TYPES else ""))
    if isinstance(context.get("words"), dict):
        # 語の一覧を使ったときだけ（種類と読者の行のあと）
        head.append(words_label(context["words"]))
    return "\n".join(head) + "\n\n" + "\n\n".join(body) + "\n\n" + _status_line(d, _DETECTOR_STATUS_NOTE_ABOVE)


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ---- CLI ----

_EXIT_CODES = """終了コード:
  0  比べ終わり、--fail-on の条件に当たらなかった（候補の有無によらない）。--endings の正常終了、-h と --version も0
  1  --fail-on=meaning-risk の条件に当たった（数値、否定、主語と目的語の入れ替え、文の種類・引用の印・確度・状態の語・約束・許可の言い方・選ぶ範囲・因果の恐れが1件以上）
  2  使い方か入力の誤り（ファイルを開けない、UTF-8 として読めない、標準入力を読めない、使えない --stance、--fail-on、--doc-type、--reader の値、ファイルの数の誤り、語の一覧を読めない（--words のフォルダがない、UTF-8 でない、1万行を超える）、--words と --no-words を一緒に指定した）
  3  予期しない内部の誤り（標準エラーにトレースバックを出す）か、出力先が閉じられて結果を最後まで書けなかった"""
_USAGE = ("yomiyasu_diff.py [--stance 立場] [--doc-type 種類] [--reader 読者] [--json] [--fail-on meaning-risk]\n"
          "                        [--words フォルダ | --no-words] 元の文 書き直した文\n"
          "       yomiyasu_diff.py --endings ファイル [--stance 立場]\n"
          "       yomiyasu_diff.py --version")
_FAIL_ON_HELP = ("意味が変わる恐れのうち、数値、否定、主語と目的語の入れ替え、文の種類（問いと平叙、文の種類の印）、引用の印の変化、"
                 "確度を強めた書き換え（かもしれない → 見込み、見込み → 予定、と思われる → 断定など）、"
                 "原文の状態の語（未定、未確認、調査中など）が消えた書き換え、原文にない書き手の約束・保証・再発防止の誓いの足しが"
                 "1件でもあれば、終了コード1で終わります。許可の言い方（してよい、してもよい、構わない）が消えたか増えた書き換えも数えます。"
                 "事実や仕様を述べる種類（--doc-type が " + "、".join(COUNTED_TYPES) + "）では、「場合がある」「ことがある」を消して"
                 "言い切った書き換えと、断定に「必ず」「確実に」などを足した書き換えも数えます（ほかの種類と種類なしでは数えません）。"
                 "能力の言い方（できる、可能だ）が消えた書き換えは、どの種類でも数えません。"
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


def _join_doc_types(types):
    """種類の並びを文にする（2つなら「A と B」、3つ以上なら「A、B、C」）。"""
    types = list(types)
    if len(types) == 2:
        return "{} と {}".format(*types)
    return "、".join(types)


def _counted_doc_type_help():
    """--doc-type のヘルプの、意味の検査の数え方が種類で変わる所の文。COUNTED_TYPES から作る（check run のヘルプにも同じ文を書く）。"""
    return ("{}（事実や仕様を述べる種類）では、「場合がある」「ことがある」を消した言い切りと、断定に「必ず」などを足した"
            "書き換えを --fail-on に数えます（意味の検査で種類によって変わるのはこの2つだけです）。").format(
        "、".join(COUNTED_TYPES))


def _detector_level_help():
    """--doc-type のヘルプの、硬化と勢いの検査を参考（info）にする種類の文。STIFFNESS_INFO_DOC_TYPES、TONE_INFO_DOC_TYPES、
    TONE_TYPED_REVIEW_DOC_TYPES から作る（check run のヘルプにも同じ文を書き、tests/test_v200_check_infra.py が一致を見張る。
    反証で見つけた例）。promo の見出しの数え方も書く（反証で見つけた例）。"""
    heading_kept = [doc_type for doc_type in TONE_TYPED_REVIEW_DOC_TYPES["heading"] if doc_type != "promo"]
    return ("文体の硬化の検査は {} のとき、勢いの検査は {} のとき、候補を参考として出します。"
            "promo と mail 以外の種類を指定すると、勢いの検査の絵文字の候補も参考として出し、{} 以外では見出しの候補も参考として出します。"
            "promo では、番号つき項目の行と太字だけの行も勢いの検査の見出しに数えます。").format(
        _join_doc_types(STIFFNESS_INFO_DOC_TYPES), _join_doc_types(TONE_INFO_DOC_TYPES),
        _join_doc_types(["promo"] + heading_kept))


class _ArgumentParser(argparse.ArgumentParser):
    # argparse は、書く先の流れがない（None の）とき、もう一方の流れに書く（使い方が標準出力に、
    # ヘルプが標準エラーに出る）。3.10 までは標準エラーがないと使い方の誤りで AttributeError になる。
    # pythonw や 2>&- のときも、書く先がなければ何も書かずに同じ終了コードで終える。

    def error(self, message):
        stream = sys.stderr
        if stream is None:
            self.exit(2)
        # 使い方の誤りを標準エラーに書く前に、ほかの誤りの文と同じく UTF-8 にする。
        # argparse の英語の行のあとに、日本語の案内を1行足す。
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
        # 省略形（--js など）は受けない。lint、diff、check の3本でそろえる
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
    options.add_argument("--doc-type", metavar="種類",
                         help="文書の種類（値は yomiyasu_lint.py と同じ）。表示と JSON に残します。差分、意味が変わる恐れ、"
                              "規則の見直し候補の見つけ方は、どの種類でも同じです。" + _counted_doc_type_help()
                              + _detector_level_help() + "mail だけ敬語の度合いを検査します。値: "
                              + "、".join("{}（{}）".format(row[0], row[1]) for row in DOC_TYPES) + "。")
    options.add_argument("--reader", metavar="読者",
                         help="想定する読者の知識（値は yomiyasu_lint.py と同じ）。表示と JSON に残すだけで、判定は変わりません。")
    options.add_argument("--words", metavar="フォルダ",
                         help="語の一覧（allow.txt と flag.txt）のフォルダ（値は yomiyasu_lint.py と同じ）。省くと、作業ディレクトリから"
                              "上へたどった git の最上位（.git のあるフォルダ。git の外では作業ディレクトリ）の .yomiyasu-words/ を"
                              "探します。diff では一覧の場所と語の数を表示と JSON に書きます（差分と候補は変わりません）。")
    options.add_argument("--no-words", action="store_true",
                         help="語の一覧を探さず、読みません（--words と一緒には使えません）。")
    options.add_argument("--endings", action="store_true",
                         help="1つのファイルの文末の種類と、立場の混ざりだけを見ます（--json、--fail-on、--words、--no-words は使えません）。")
    options.add_argument("--version", action="store_true", help="版を表示して終わります。")
    parser.set_defaults(fail_on=[])
    return parser


def _version_line():
    return "yomiyasu_diff.py {} (JSON format {})".format(__version__, DIFF_FORMAT_VERSION)


def _use_utf8(stream, **options):
    # 改行は OS によらず "\n" で書く（Windows の既定では "\r\n" になり、記録や CLI の出力が OS で変わる）
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", newline="\n", **options)


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
        # 大文字と小文字、「_」と「-」は区別しない（MEANING_RISK も受ける）。
        pieces = [piece.strip().lower().replace("_", "-") for piece in value.split(",") if piece.strip()]
        if not pieces:
            # 空、空白だけ、カンマだけの値は、目に見えないので「（空）」と書く。
            return False, "--fail-on に使えない値です: （空）。diff で使えるのは meaning-risk です。"
        for piece in pieces:
            if piece != "meaning-risk":
                return False, "--fail-on に使えない値です: {}。diff で使えるのは meaning-risk です。".format(piece)
            hit = True
    return hit, None


def _fail_on_line(total, counted, risks=()):
    """--fail-on=meaning-risk に当たったときの最後の行。数えない種類（変えない箇所）が混ざるときは、全件と数えた件数を書く。"""
    if total == counted:
        return "終了コード1: --fail-on=meaning-risk の条件に当たりました（意味が変わる恐れ {}件）。".format(counted)
    return ("終了コード1: --fail-on=meaning-risk の条件に当たりました"
            "（意味が変わる恐れ {}件のうち、数値・否定・入れ替え・文の種類{} {}件）。".format(
                total, "".join(label for kind, label in (("certainty", "・確度"), ("state", "・状態の語"), ("promise", "・約束"),
                                                         ("modality", "・許可の言い方"), ("choice", "・選ぶ範囲"),
                                                         ("causality", "・因果"))
                               if any(r["kind"] == kind for r in risks)), counted))


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
        if args.doc_type is not None or args.reader is not None:
            # 無視せずに使い方の誤りにする（--json、--fail-on と同じ）
            parser.error("--endings は --doc-type と --reader に対応していません")
        if args.words is not None or args.no_words:
            # 文末だけを見るときは語の一覧を探さない。指定は無視せずに使い方の誤りにする（--doc-type と同じ）
            parser.error("--endings は --words と --no-words に対応していません")
        if len(files) != 1:
            parser.error("--endings のときは、ファイルを1つだけ渡してください（渡されたのは{}つ）".format(len(files)))
    elif len(files) != 2:
        parser.error("元の文と書き直した文の2つのファイルを渡してください（渡されたのは{}つ）".format(len(files)))
    if args.words is not None and args.no_words:
        parser.error("--words と --no-words は一緒に使えません")
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
    try:
        # 種類と読者の値。使えない値と空の文字列は、入力を読む前に2で断る
        doc_type, reader = normalize_doc_type(args.doc_type), normalize_reader(args.reader)
    except ValueError as error:
        _error(str(error))
        return 2
    words = None
    if not args.endings:
        try:
            # 語の一覧。読めない一覧は、入力を読む前に2で断る（--endings では探さない）
            words = resolve_words(current_directory(), args.words, args.no_words)
        except WordsError as error:
            _error(str(error))
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
        result = diff(texts[0], texts[1], stance, encoding_notes=_encoding_notes(infos[0], infos[1]),
                      doc_type=doc_type, reader=reader, words=words)
        counted = result["fail_on_meaning_risk_count"]
        hit = fail_on and counted > 0
        if args.json:
            print(json.dumps(result, ensure_ascii=True, indent=1))
        else:
            print(report(result))
            if hit:
                print()
                print(_fail_on_line(result["meaning_risk_count"], counted, result["meaning_risks"]))
        code = 1 if hit else 0
    # 書き出しの失敗（読む側が先に閉じたなど）を、ここで BrokenPipeError として受けられるようにする。
    if sys.stdout is not None:
        sys.stdout.flush()
    return code


def _closed_output_on_windows(error):
    """Windows で、読む側が閉じたパイプに書いたときの例外か。Windows では BrokenPipeError ではなく、errno が EINVAL の
    OSError になる。ファイル名のある OSError（Windows で名前に使えない字を含むパスなど）と、POSIX では、ほかの誤りとして扱う。"""
    return (os.name == "nt" and type(error) is OSError and error.errno == errno.EINVAL
            and error.filename is None and error.filename2 is None)


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
        if _closed_output_on_windows(error):
            # Windows で出力先が閉じられた。上の BrokenPipeError と同じく扱う
            _silence_stdout()
            _error("yomiyasu_diff.py: 出力先が閉じられたため、結果を最後まで書けませんでした。")
            return 3
        _error("yomiyasu_diff.py: 内部エラー: {}: {}".format(type(error).__name__, error))
        _error(traceback.format_exc().rstrip("\n"))
        return 3


if __name__ == "__main__":
    sys.exit(main())
