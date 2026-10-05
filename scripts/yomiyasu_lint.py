#!/usr/bin/env python3
"""
yomiyasu_lint.py - 日本語の表現とMarkdownの書式を、設定されたルールで点検する。

指摘は見直し候補であり、意味の保持や読みやすさを判定するものではない。
Python標準ライブラリだけで動作する。
"""

import sys
import re
import argparse
import json
import unicodedata
from typing import List, Dict, Any, Tuple


# 絵文字正規表現パターン（CJK統合漢字拡張などのサロゲートペア漢字を除外した厳密な絵文字範囲）
EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F]"  # Emoticons
    r"|[\U0001F300-\U0001F5FF]"  # Misc Symbols and Pictographs
    r"|[\U0001F680-\U0001F6FF]"  # Transport and Map
    r"|[\U0001F700-\U0001F77F]"  # Alchemical Symbols
    r"|[\U0001F780-\U0001F7FF]"  # Geometric Shapes Extended
    r"|[\U0001F800-\U0001F8FF]"  # Supplemental Arrows-C
    r"|[\U0001F900-\U0001F9FF]"  # Supplemental Symbols and Pictographs
    r"|[\U0001FA00-\U0001FA6F]"  # Chess Symbols
    r"|[\U0001FA70-\U0001FAFF]"  # Symbols and Pictographs Extended-A
    r"|[\u2600-\u27BF]"          # Misc Symbols, Dingbats
    r"|[\u2300-\u23FF]"          # Misc Technical
    r"|[\u2B50-\u2B55]"
)

# 文脈を確かめる語の一覧。含まれていることだけでは誤りとしない。
SLOP_WORDS = [
    # 質感を装う疑似具体語
    "手触り", "肌感", "肌感覚", "体温", "温度感", "熱量", "血の通った", "泥臭い", "泥臭さ",
    # 認知・評価を装う語
    "解像度", "腹落ち", "メンタルモデル", "本質的", "地に足のついた", "等身大",
    # 抽象比喩名詞
    "営み", "装置", "意思決定OS", "土台", "羅針盤", "起爆剤", "触媒",
    # 日常の体験を大げさに表す場合がある語
    "真理", "虚飾", "境地", "美学", "深淵", "冷徹", "禁欲的", "優美", "極致", "宿命",
    # 指す役割を確かめる語
    "正本",
]

# 比喩動詞・AI偏愛動詞パターン
METAPHOR_VERB_PATTERNS = [
    (r"(地味に|よく|じわじわ)効[かきくけいた]", "比喩動詞「効く」の過剰使用"),
    (r"(データ|仕様|設計|環境|ビルド|システム|秩序)が(静かに)?壊れ", "比喩動詞「壊れる」"),
    (r"静かに(壊れ|落ち|失敗|沈黙)", "英語直訳「静かに壊れる (silently fail)」"),
    (r"黙って(無視|捨て|スキップ|破棄)", "英語直訳「黙って無視される」"),
    (r"側に倒[すしせ]", "判断を方向で表現する「〜側に倒す」"),
    (r"時間[をに]溶か[したす]", "比喩動詞「時間を溶かす」"),
    (r"(1つずつ|一つずつ)潰[していく]", "比喩動詞「潰す」"),
    (r"(実装|詳細|コード|設計|内部|仕組み|領域|本質)(に|まで|へ)踏み込[んむみま]", "比喩動詞「踏み込む」"),
    (r"動かしながら引き返[すし]", "比喩動詞「引き返す」"),
    (r"代わりに添え[るた]", "比喩動詞「添える」"),
    (r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂", "比喩動詞「収斂する」"),
    (r"した瞬間に?", "英語直訳「〜した瞬間 (the moment ...)」"),
    (r"(前提|基盤)が崩れ[るた]", "抽象比喩「前提が崩れる」"),
    (r"文化が醸成", "非生物主語「文化が醸成される」"),
    (r"プロセスが定着", "非生物主語「プロセスが定着する」"),
    (r"事例が残した", "非生物主語「事例が残した」"),
]

# メタフィラー・定型句
FILLER_PATTERNS = [
    (r"^(まず|ここで)?重要なのは、?", "前置フィラー「重要なのは」"),
    (r"^結論から言うと、?", "前置フィラー「結論から言うと」"),
    (r"^正直に言うと、?", "前置フィラー「正直に言うと」"),
    (r"^避けたいのは、?", "前置フィラー「避けたいのは」"),
    (r"いかがでした(でしょうか|か)?[？?。]?$", "定型クロージング「いかがでしたでしょうか」"),
    (r"ぜひ(参考|試し|活用)(に)?して(みて)?ください[！!。]?", "定型クロージング「ぜひ〜してみてください」"),
    (r"〜に他なりません", "過剰な自己ラベリング「〜に他なりません」"),
]

# ネガティブパラレリズム（AではなくB）
NEGATIVE_PARALLELISM_PATTERN = re.compile(r"([^。、]+)ではなく、?([^。、]+)")


def get_frontmatter_line_count(lines: List[str]) -> int:
    """YAMLフロントマター（先頭の --- から 次の --- まで）の行数を返す"""
    if not lines or lines[0].strip() != "---":
        return 0
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return idx + 1
    return 0


def extract_plain_sentences(text: str) -> List[Tuple[int, str]]:
    """コードブロックや引用、箇条書きを除去し、地の文の段落文（行番号つき）を抽出する"""
    lines = text.split("\n")
    sentences = []
    in_code_block = False
    fm_lines = get_frontmatter_line_count(lines)

    for idx, line in enumerate(lines, 1):
        if idx <= fm_lines:
            continue
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        # 空行、見出し、表行、画像記法、HTMLタグ、引用行、箇条書き行、インデントされたリスト継続行は地の文から除外
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("|")
            or stripped.startswith("![")
            or stripped.startswith("[![")
            or stripped.startswith("<")
            or stripped.startswith(">")
            or re.match(r"^[-*+]\s|^\d+\.\s", stripped)
            or line.startswith("  ")
            or line.startswith("\t")
        ):
            continue

        # 文の区切り（。！？または行末）
        raw_sents = re.split(r"(?<=[。！？])", stripped)
        for s in raw_sents:
            s_clean = s.strip()
            if s_clean and len(s_clean) > 3:
                sentences.append((idx, s_clean))

    return sentences


def check_sentence_end_repetitions(sentences: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
    """3文以上連続する同一語尾の検知"""
    findings = []
    end_types = []

    for line_no, s in sentences:
        clean = re.sub(r"[。！？\s]+$", "", s)
        end_type = "その他"
        if clean.endswith("です"):
            end_type = "です"
        elif clean.endswith("ます"):
            end_type = "ます"
        elif clean.endswith("でした"):
            end_type = "でした"
        elif clean.endswith("ました"):
            end_type = "ました"
        elif clean.endswith("である"):
            end_type = "である"
        elif clean.endswith("だ"):
            end_type = "だ"
        elif clean.endswith("だろう"):
            end_type = "だろう"
        end_types.append((line_no, s, end_type))

    # 3連続チェック
    count = 1
    for i in range(1, len(end_types)):
        prev_line, prev_s, prev_type = end_types[i - 1]
        curr_line, curr_s, curr_type = end_types[i]

        if curr_type != "その他" and curr_type == prev_type:
            count += 1
            if count == 3:
                findings.append({
                    "rule": "sentence_end_repetition",
                    "line": curr_line,
                    "severity": "warn",
                    "message": f"同一文末「{curr_type}」が3回以上連続しています。読みにくくなっていないか確認し、自然な説明や文体は保ってください。",
                    "snippet": curr_s
                })
        else:
            count = 1

    return findings


def analyze_markdown_metrics(text: str) -> Dict[str, Any]:
    """太字頻度、箇条書き比率などの構造メトリクスを算出（引用文やコードブロックは除外）"""
    lines = text.split("\n")
    plain_lines = []
    in_code = False
    fm_lines = get_frontmatter_line_count(lines)
    for idx, l in enumerate(lines, 1):
        if idx <= fm_lines:
            continue
        stripped = l.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(">") or stripped.startswith("|") or stripped.startswith("![") or stripped.startswith("[![") or stripped.startswith("<"):
            continue
        plain_lines.append(l)

    total_lines = len([l for l in plain_lines if l.strip()])
    list_lines = 0
    for l in plain_lines:
        if re.match(r"^\s*([-*+]|\d+\.)\s+", l):
            # 外部参照リンク（- [タイトル](http...)）は並列データのため思考リストから除外
            if not re.search(r"[-*+]\s+\[.*?\]\(https?://", l):
                list_lines += 1

    plain_content = "\n".join(plain_lines)
    bold_matches = re.findall(r"\*\*[^*]+\*\*", plain_content)
    bold_count = len(bold_matches)
    char_count = len(re.sub(r"\s+", "", plain_content))

    bold_per_1000 = (bold_count / char_count * 1000) if char_count > 0 else 0
    list_ratio = (list_lines / total_lines) if total_lines > 0 else 0

    return {
        "char_count": char_count,
        "total_lines": total_lines,
        "list_lines": list_lines,
        "list_ratio": round(list_ratio, 3),
        "bold_count": bold_count,
        "bold_per_1000": round(bold_per_1000, 2),
    }


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


def lint_text(text: str) -> Dict[str, Any]:
    """文章全体を総合検査する"""
    findings = []
    metrics = analyze_markdown_metrics(text)
    sentences = extract_plain_sentences(text)

    # 1. メトリクス異常の検査（地の文が十分ある場合に適用）
    if metrics["char_count"] > 300:
        if metrics["bold_per_1000"] > 3.0:
            findings.append({
                "rule": "excess_bold",
                "line": 1,
                "severity": "warn",
                "message": f"太字の頻度（1,000字あたり {metrics['bold_per_1000']}個）が設定した目安を超えています（推奨: 2.0以下）。強調の役割を確かめ、不要なものだけ整理してください。",
                "snippet": f"太字数: {metrics['bold_count']}回 / {metrics['char_count']}文字"
            })

        if metrics["list_ratio"] > 0.25:
            findings.append({
                "rule": "excess_list",
                "line": 1,
                "severity": "warn",
                "message": f"箇条書きの比率（{round(metrics['list_ratio']*100, 1)}%）が設定した目安を超えています（推奨: 15%以下）。項目の役割を確かめ、不要なものだけ整理してください。",
                "snippet": f"リスト行: {metrics['list_lines']} / 全非空行: {metrics['total_lines']}"
            })

    # 2. 文末重複検査
    findings.extend(check_sentence_end_repetitions(sentences))

    # 2.5 太字が表示されるか（GitHub などの Markdown で ** がそのまま出るところ）
    for p in bold_problems(text):
        findings.append({
            "rule": "bold_not_rendered",
            "line": p["line"],
            "severity": "error",
            "message": f"太字の印（**）が記号に接していて、GitHub などでは太字にならず ** がそのまま表示されます。直し方: {p['how']}。",
            "snippet": f"{p['found']} → {p['suggest']}" if p["suggest"] else p["found"]
        })

    # 3. 語彙・構文パターン検査
    lines = text.split("\n")
    in_code = False
    fm_lines = get_frontmatter_line_count(lines)
    for line_no, line in enumerate(lines, 1):
        if line_no <= fm_lines:
            continue
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue

        # 絵文字検知（見出し・本文問わず禁止）
        emoji_matches = EMOJI_PATTERN.findall(line)
        if emoji_matches:
            findings.append({
                "rule": "emoji_prohibited",
                "line": line_no,
                "severity": "warn",
                "message": f"絵文字（{' '.join(emoji_matches[:3])}）が検出されました。AI特有の装飾を排し、平文で記述してください。",
                "snippet": line.strip()
            })

        # 見出し行の余計な言い換え補足カッコ検知
        if stripped.startswith("#"):
            if re.search(r"（(素の出力|いわゆる|概要|詳細|感謝と設計への反映)）", stripped):
                findings.append({
                    "rule": "redundant_bracket",
                    "line": line_no,
                    "severity": "warn",
                    "message": "見出しに情報量の増えない補足カッコが含まれています。平文で簡潔に記述してください。",
                    "snippet": line.strip()
                })
            continue

        # 引用ブロック（>）やテーブル行（|）、画像、HTMLタグはアンチパターン例示等の可能性が高いため語彙スキャンをスキップ
        if stripped.startswith(">") or stripped.startswith("|") or stripped.startswith("![") or stripped.startswith("[![") or stripped.startswith("<"):
            continue

        # インラインコード（`...`）を除去したテキストを作成
        scan_text = re.sub(r"`[^`]+`", "", stripped)
        # 太字や強調などの装飾記号（**、*、__）を除去した正規化テキストで語彙・比喩を検査
        plain_text = re.sub(r"\*\*|\*|__", "", scan_text)

        # 和欧文間の不自然な半角空白検知（例: 「も yomiyasu で」「この README は」）
        if re.search(r"([ぁ-んァ-ヶ一-龥])\s+([a-zA-Z0-9_-]{2,})\s+([ぁ-ん])", scan_text):
            # リンク構文 [text](url) の一部でないことを確認
            if not re.search(r"\[.*?\]\(.*?\)", scan_text):
                findings.append({
                    "rule": "unnatural_halfwidth_space",
                    "line": line_no,
                    "severity": "warn",
                    "message": "英単語の前後に不要な半角空白が空けられています。日本語の助詞と自然に接続させてください。",
                    "snippet": line.strip()
                })

        # 文末コロン（全角「：」または半角「:」）検知
        if re.search(r"[：:]$", scan_text) and not scan_text.startswith("http"):
            findings.append({
                "rule": "trailing_colon",
                "line": line_no,
                "severity": "warn",
                "message": "文末にコロン（：）があります。ラベルと値の対応などに必要か確認し、不要な前置きなら整理してください。",
                "snippet": line.strip()
            })

        # スロップ語彙
        for word in SLOP_WORDS:
            if word in plain_text:
                findings.append({
                    "rule": "slop_vocabulary",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"AI頻出語彙「{word}」が含まれています。文脈上必要のない比喩や大げさな装飾であれば、ふだん使う自然な表現に置き換えてください。ただし、文字どおりの意味や必要な文脈を担っている場合は残してかまいません。",
                    "snippet": line.strip()
                })

        # 比喩動詞パターン
        kowareru_span = None
        for pattern, desc in METAPHOR_VERB_PATTERNS:
            if desc == "英語直訳「静かに壊れる (silently fail)」" and kowareru_span:
                # 「壊れる」と「静かに壊れる」が同一動詞に二重反応することを防止
                for m in re.finditer(pattern, plain_text):
                    span = (m.start(), m.end())
                    if kowareru_span[0] <= span[0] and span[1] <= kowareru_span[1]:
                        continue
                    findings.append({
                        "rule": "metaphor_verb",
                        "line": line_no,
                        "severity": "warn",
                        "message": f"{desc}が検出されました。不自然な比喩動詞であれば、ふだん使う動詞や客観的な表現に書き直してください。ただし、文字どおりの動作や状態変化を表している場合は無理に言い換える必要はありません。",
                        "snippet": line.strip()
                    })
                    break
                continue

            m = re.search(pattern, plain_text)
            if m:
                if desc == "比喩動詞「壊れる」":
                    kowareru_span = (m.start(), m.end())
                findings.append({
                    "rule": "metaphor_verb",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。不自然な比喩動詞であれば、ふだん使う動詞や客観的な表現に書き直してください。ただし、文字どおりの動作や状態変化を表している場合は無理に言い換える必要はありません。",
                    "snippet": line.strip()
                })

        # フィラーパターン
        for pattern, desc in FILLER_PATTERNS:
            if re.search(pattern, plain_text):
                findings.append({
                    "rule": "meta_filler",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。単なる前置きや不要な飾りであれば削り、本題から書いてください。ただし、「何が大事か」という評価や主張そのものを担っている場合は、述語に移すなどして意味を残してください。",
                    "snippet": line.strip()
                })

        # ネガティブパラレリズム
        if NEGATIVE_PARALLELISM_PATTERN.search(plain_text):
            if "ではなく、" in plain_text or "ではなく" in plain_text:
                findings.append({
                    "rule": "negative_parallelism",
                    "line": line_no,
                    "severity": "info",
                    "message": "「AではなくB」構文が検出されました。否定を外しても主張が変わらない場合は肯定文を検討してください。ただし、誤解の訂正や見方の切り替えなど意味・比重を担っている否定なら、無理に肯定化せずそのまま残してください。",
                    "snippet": line.strip()
                })

    # スコア計算（100点満点からの減点方式: warn=5点, info=2点）
    penalty = sum(5 if f["severity"] in ("warn", "error") else 2 for f in findings)
    score = max(0, 100 - penalty)

    return {
        "score": score,
        "is_clean": len(findings) == 0,
        "metrics": metrics,
        "findings": findings
    }


def main():
    parser = argparse.ArgumentParser(description="日本語の表現とMarkdownの書式を、設定されたルールで点検します。指摘は見直し候補です。")
    parser.add_argument("file", nargs="?", help="検査対象のMarkdownファイルパス（指定なしの場合は標準入力）")
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    parser.add_argument("--strict", action="store_true", help="警告が1件でもあれば非ゼロ（終了コード1）で終了")

    args = parser.parse_args()

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error opening file {args.file}: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        content = sys.stdin.read()

    result = lint_text(content)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print(f"AIっぽさ 検査レポート (スコア: {result['score']}/100)")
        print("=" * 60)
        m = result["metrics"]
        print(f"・文字数: {m['char_count']} | 行数: {m['total_lines']}")
        print(f"・太字頻度: 1,000字あたり {m['bold_per_1000']} 個 (推奨: 2.0以下 / 警告: 3.0超)")
        print(f"・箇条書き比率: {round(m['list_ratio']*100, 1)}% (推奨: 15%以下 / 警告: 25%超)")
        print("-" * 60)

        if result["is_clean"]:
            print("[PASS] 設定された検査ルールによる指摘はありません。")
        else:
            print(f"[NOTICE] {len(result['findings'])} 件の見直し候補が見つかりました。\n")
            for f in result["findings"]:
                sev = f"[{f['severity'].upper()}]"
                print(f"L{f['line']} {sev} {f['message']}")
                print(f"  > {f['snippet']}\n")

    if args.strict:
        warn_count = sum(1 for f in result["findings"] if f["severity"] in ("warn", "error"))
        if warn_count > 0:
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
