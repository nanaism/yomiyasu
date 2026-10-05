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
  6. 書き直した文の中で、太字にならない書き方（GitHub などで ** がそのまま表示されるところ）と、直し方の案
言い換えかどうか、つながりが合っているか、文末が立場に合っているかの最終判断は、この結果を見たモデル（または人）がする。
"""
import re
import sys
import json
import difflib
import unicodedata

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
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"[（(][^（）()]*[）)]$", "", t).strip()
    return re.sub(r"[」』）)]+$", "", t)


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


def ending_changes(o: str, r: str):
    """書き直しで文末の種類が変わった文。似ている元の文と組にして比べる"""
    ou, ru = ending_units(o), ending_units(r)
    changes = []
    for x in ru:
        best, score = None, 0.0
        for y in ou:
            sc = difflib.SequenceMatcher(None, y["sentence"], x["sentence"], autojunk=False).ratio()
            if sc > score:
                best, score = y, sc
        if best and score >= 0.45 and best["kind"] != x["kind"]:
            changes.append({"orig": best["sentence"], "orig_kind": best["kind"] + ("・箇条書き" if best["where"] == "箇条書き" else ""),
                            "rewrite": x["sentence"], "rewrite_kind": x["kind"]})
    return changes


# ---- 太字が表示されるか（GitHub などの Markdown）----
# GitHub の Markdown では、** のすぐ内側が記号（「」（）` など）で、すぐ外側が文字だと、** を太字の印として読まず、
# ** がそのまま表示される。新しい CommonMark（記号に Unicode の S も入る）でも、GitHub の GFM（P だけ）でも
# 太字になる形だけを「表示される」とみなす。直し方の案は、かっこの内側だけを太字にする → 句読点を太字の外に出す
# → 文字に接する側に半角スペースを入れる、の順に試す。
BOLD_ASCII_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
BOLD_BRACKETS = {"「": "」", "『": "』", "（": "）", "(": ")", "【": "】", "〔": "〕", "［": "］", "[": "]",
                 "〈": "〉", "《": "》", "“": "”", "‘": "’", "＜": "＞"}


def _bold_ws(ch: str) -> bool:
    return ch == "" or ch.isspace()


def _bold_punct_gfm(ch: str) -> bool:
    return ch != "" and (ch in BOLD_ASCII_PUNCT or unicodedata.category(ch).startswith("P"))


def _bold_punct_new(ch: str) -> bool:
    return ch != "" and unicodedata.category(ch)[0] in "PS"


def _bold_can_open(prev: str, nxt: str) -> bool:
    return all(not _bold_ws(nxt) and (not p(nxt) or _bold_ws(prev) or p(prev)) for p in (_bold_punct_gfm, _bold_punct_new))


def _bold_can_close(prev: str, nxt: str) -> bool:
    return all(not _bold_ws(prev) and (not p(prev) or _bold_ws(nxt) or p(nxt)) for p in (_bold_punct_gfm, _bold_punct_new))


def _bold_code_spans(text: str):
    """インラインコード（同じ数のバッククォートで閉じたもの）の範囲"""
    runs = [(m.start(), m.end()) for m in re.finditer(r"`+", text)]
    spans, k = [], 0
    while k < len(runs):
        s, e = runs[k]
        for m in range(k + 1, len(runs)):
            if runs[m][1] - runs[m][0] == e - s:
                spans.append((s, runs[m][1]))
                k = m
                break
        k += 1
    return spans


def _bold_pairs(text: str):
    """後方互換用: テキスト内の太字ペアを返す"""
    return _bold_pairs_in_block(text)


def _bold_pairs_in_block(block_text: str):
    code = _bold_code_spans(block_text)
    pos = []
    for m in re.finditer(r"(?<!\*)\*\*(?!\*)", block_text):
        p = m.start()
        if any(a <= p < b for a, b in code):
            continue
        bs_match = re.search(r"\\*$", block_text[:p])
        bs_count = len(bs_match.group(0)) if bs_match else 0
        if bs_count % 2 == 1:
            continue
        pos.append(p)

    pairs = []
    used = set()

    # 第1段: 強調開閉の基本条件（前後の空白判定）によるスタック照合
    stack = []
    for p in pos:
        prev = block_text[p - 1] if p > 0 else ""
        nxt = block_text[p + 2] if p + 2 < len(block_text) else ""

        can_open = not _bold_ws(nxt)
        can_close = not _bold_ws(prev)

        if can_close and stack:
            opener = stack.pop()
            if opener + 2 < p:
                pairs.append((opener, p))
                used.add(opener)
                used.add(p)
        elif can_open:
            stack.append(p)

    # 第2段: 内側空白によって開閉条件から外れた太字候補のペアリング
    unpaired = [p for p in pos if p not in used]
    idx = 0
    while idx < len(unpaired) - 1:
        p1 = unpaired[idx]
        p2 = unpaired[idx + 1]
        if any(p1 < a < p2 or p1 < b < p2 for a, b in pairs):
            idx += 1
            continue
        inner = block_text[p1 + 2:p2]
        if inner.strip() != "":
            if _bold_ws(inner[0]) or _bold_ws(inner[-1]):
                pairs.append((p1, p2))
                used.add(p1)
                used.add(p2)
                idx += 2
                continue
        idx += 1

    pairs.sort(key=lambda x: x[0])
    return pairs


def _bold_pair_ok(text: str, i: int, j: int) -> bool:
    ch = lambda p: text[p] if 0 <= p < len(text) else ""
    return _bold_can_open(ch(i - 1), ch(i + 2)) and _bold_can_close(ch(j - 1), ch(j + 2))


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
    inner = text[i + 2:j]
    tries = []
    if len(inner) >= 3 and inner[0] in BOLD_BRACKETS and _bold_close_of(inner) == len(inner) - 1:
        tries.append((inner[0] + "**" + inner[1:-1] + "**" + inner[-1], "かっこの内側だけを太字にする"))
    if len(inner) >= 2 and inner[-1] in "。、．，！？!?":
        tries.append(("**" + inner[:-1] + "**" + inner[-1], "句読点を太字の外に出す"))
    ch = lambda p: text[p] if 0 <= p < len(text) else ""
    body = inner
    if _bold_ws(ch(i + 2)) or _bold_ws(ch(j - 1)):
        body = inner.strip()
    left = "" if _bold_can_open(ch(i - 1), body[:1]) else " "
    right = "" if _bold_can_close(body[-1:], ch(j + 2)) else " "
    tries.append((left + "**" + body + "**" + right, "太字の内側の空白を取る" if body != inner and not (left or right)
                  else "文字に接する側に半角スペースを入れる"))
    for middle, how in tries:
        cand = text[:i] + middle + text[j + 2:]
        pairs = _bold_pairs_in_block(cand)
        if k < len(pairs) and _bold_pair_ok(cand, *pairs[k]):
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
    """太字にならない ** の場所と、直し方の案。
    コードブロック・インラインコード・HTML の行・先頭の設定部分は見ない。
    段落・リスト・引用などのブロック単位で複数行太字を正しく扱う。
    """
    out = []
    lines = text.split("\n")
    start = 0
    if skip_frontmatter and lines and lines[0].rstrip("\r") == "---":
        for n in range(1, len(lines)):
            if lines[n].rstrip("\r") == "---":
                start = n + 1
                break

    blocks = []
    curr_lines = []
    fence = None
    curr_depth = 0
    in_table = False

    def flush():
        nonlocal curr_lines, curr_depth, in_table
        if curr_lines:
            blocks.append(curr_lines)
            curr_lines = []
        curr_depth = 0
        in_table = False

    for no in range(start, len(lines)):
        raw_line = lines[no]
        line = raw_line.rstrip("\r")
        line_no = no + 1

        is_list, depth, content = _line_containers(line)

        # フェンスコードブロックの開始・終了
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", content)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not m.group(2).strip():
                fence = None
            continue
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            flush()
            fence = (m.group(1)[0], len(m.group(1)))
            continue

        if not content.strip():
            flush()
            continue

        if content.lstrip().startswith("<"):
            flush()
            continue

        if re.match(r"^\s{0,3}(?:(\*)\s*(?:\1\s*){2,}|(-)\s*(?:\2\s*){2,}|(_)\s*(?:\3\s*){2,})\s*$", content):
            flush()
            continue

        # GFM 表の区切り行（-- | -- など、外周パイプなしを含む）
        m_tbl_sep = re.match(r"^\s{0,3}\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$", content)
        if m_tbl_sep:
            if curr_lines:
                hdr = curr_lines.pop()
                flush()
                blocks.append([hdr])
            else:
                flush()
            in_table = True
            continue

        # Setext 見出し下線（=== または ---）
        if curr_lines and re.match(r"^\s{0,3}(=+|-+)\s*$", content):
            flush()
            continue

        # ATX 見出し
        if re.match(r"^\s{0,3}#{1,6}(\s+|$)", content):
            flush()
            blocks.append([(line_no, line)])
            continue

        # 表の行（外周パイプあり、または表の継続行）
        if content.startswith("|") or (in_table and "|" in content):
            flush()
            blocks.append([(line_no, line)])
            in_table = True
            continue
        else:
            in_table = False

        # リスト項目の開始
        if is_list or re.match(r"^\s{0,3}(?:[*+-]|\d+[.)])\s+", content):
            flush()
            curr_depth = depth
            curr_lines.append((line_no, line))
            continue

        # 引用深度の変更（lazy continuation: 直前の深さ>0 かつ 現在の深さ0 の場合は許容）
        if curr_lines:
            if depth != curr_depth:
                if not (curr_depth > 0 and depth == 0):
                    flush()
                    curr_depth = depth

        if not curr_lines:
            curr_depth = depth

        curr_lines.append((line_no, line))

    flush()

    for block in blocks:
        block_text = "\n".join(l for _, l in block)
        offsets = [0]
        for _, l in block[:-1]:
            offsets.append(offsets[-1] + len(l) + 1)

        def get_line_no(char_idx: int) -> int:
            import bisect
            l_idx = bisect.bisect_right(offsets, char_idx) - 1
            return block[l_idx][0]

        pairs = _bold_pairs_in_block(block_text)
        for k, (i, j) in enumerate(pairs):
            if _bold_pair_ok(block_text, i, j):
                continue
            middle, how = _bold_fix(block_text, i, j, k)
            pre, post = block_text[max(0, i - 4):i], block_text[j + 2:j + 6]
            found = pre + _bold_short(block_text[i:j + 2]) + post
            suggest = pre + _bold_short(middle) + post if middle is not None else ""
            line_no = get_line_no(i)
            out.append({"line": line_no, "found": found, "suggest": suggest, "how": how})

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
    _, flags = stance_flags(rw_raw, stance)
    _, orig_flags = stance_flags(orig_raw, stance)
    out["endings"] = {"stance": stance, "changes": ending_changes(orig_raw, rw_raw),
                      "flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in flags],
                      "orig_flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in orig_flags]}

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
    sm = difflib.SequenceMatcher(None, o, r, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            seg = r[j1:j2]
            kinds = [n for n, p in MARKERS.items() if re.search(p, r[max(0, j1 - 3):j2 + 3])]
            words = [w for w in CONTENT.findall(seg) if w not in o]
            if kinds or words:
                out["spans"].append({"added": seg, "was": o[i1:i2], "kinds": kinds, "new_words": words,
                                     "where": context(r, j1, j2)})
    return out


def bold_head(where: str = "") -> str:
    return f"■ 太字にならない書き方（{where}GitHub などで ** がそのまま表示される。表示可否と案の範囲を確認して直す）"


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


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stance = None
    for a in sys.argv[1:]:
        if a.startswith("--stance="):
            stance = STANCES.get(a.split("=", 1)[1])
    if "--endings" in sys.argv and args:
        # 1つのファイルの文末だけを見る（マークダウンのコードブロックや表の区切りは飛ばす）
        t = open(args[0], encoding="utf-8").read()
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
    o = open(args[0], encoding="utf-8").read()
    r = open(args[1], encoding="utf-8").read()
    d = diff(o, r, stance)
    print(json.dumps(d, ensure_ascii=False, indent=1) if "--json" in sys.argv else report(d))
