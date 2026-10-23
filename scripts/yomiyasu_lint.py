#!/usr/bin/env python3
"""
yomiyasu_lint.py - 日本語の表現とMarkdownの書式を、設定されたルールで点検する。

指摘は見直し候補であり、意味の保持や読みやすさを判定するものではない。
Python標準ライブラリだけで動作する。
mail は絵文字と meta_filler の返信・結びの5型を外す。宛名・挨拶・署名・クッション言葉を削る専用規則はない。
paper は慎重表現をぼかしとして削る規則がないので、外す規則はない。
"""
__version__ = "2.2.1"

import os
import errno
import functools
import sys
import re
import argparse
import json
import traceback
import unicodedata
from bisect import bisect_right
from itertools import chain, compress
from operator import is_
from typing import List, Dict, Any, Tuple
_VISIBILITY_NAMES = ("analyze_markdown", "line_visible_text", "range_overlaps_protected",
                     "inline_protected_spans", "unicode_whitespace", "decode_source",
                     "DOC_TYPES", "READER_LEVELS", "normalize_doc_type", "normalize_reader", "context_label",
                     "WordsError", "resolve_words", "current_directory", "words_context", "words_label")
try:
    try:
        if __package__:
            from .markdown_visibility import analyze_markdown, line_visible_text, range_overlaps_protected, inline_protected_spans, unicode_whitespace, decode_source
            from .markdown_visibility import DOC_TYPES, READER_LEVELS, normalize_doc_type, normalize_reader, context_label
            from .markdown_visibility import WordsError, resolve_words, current_directory, words_context, words_label
        else:
            from markdown_visibility import analyze_markdown, line_visible_text, range_overlaps_protected, inline_protected_spans, unicode_whitespace, decode_source
            from markdown_visibility import DOC_TYPES, READER_LEVELS, normalize_doc_type, normalize_reader, context_label
            from markdown_visibility import WordsError, resolve_words, current_directory, words_context, words_label
    except SyntaxError as error:
        # 隣の markdown_visibility.py が壊れている。ほかの読めないときと同じく ImportError にする（スクリプトでは終了コード3）。
        raise ImportError(
            "{} を読めません（SyntaxError: {}）。yomiyasu_lint.py と同じ版の markdown_visibility.py を置いてください。".format(
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
            # （OSError と SyntaxError のままだと外の except で受けられず、トレースバックと終了コード1になる。diff と同じ）。
            raise ImportError(
                "{} を読めません（{}: {}）。yomiyasu_lint.py と同じ版の markdown_visibility.py を同じフォルダに置いてください。".format(
                    _visibility_spec.origin, type(_load_error).__name__, _load_error),
                name=expected) from _load_error
        _missing = [name for name in _VISIBILITY_NAMES if not hasattr(_visibility_module, name)]
        if _missing:
            raise ImportError(
                "{} に {} がありません。yomiyasu_lint.py と同じ版の markdown_visibility.py を置いてください。".format(
                    _visibility_spec.origin, "、".join(_missing)),
                name=expected)
        analyze_markdown = _visibility_module.analyze_markdown
        line_visible_text = _visibility_module.line_visible_text
        range_overlaps_protected = _visibility_module.range_overlaps_protected
        inline_protected_spans = _visibility_module.inline_protected_spans
        unicode_whitespace = _visibility_module.unicode_whitespace
        decode_source = _visibility_module.decode_source
        DOC_TYPES = _visibility_module.DOC_TYPES
        READER_LEVELS = _visibility_module.READER_LEVELS
        normalize_doc_type = _visibility_module.normalize_doc_type
        normalize_reader = _visibility_module.normalize_reader
        context_label = _visibility_module.context_label
        WordsError = _visibility_module.WordsError
        resolve_words = _visibility_module.resolve_words
        current_directory = _visibility_module.current_directory
        words_context = _visibility_module.words_context
        words_label = _visibility_module.words_label
except ImportError as _import_error:
    # スクリプトとして動かしたときは、main() が内部エラー（終了コード3）として出す。
    # 終了コード1は --strict と --fail-on の条件に当たったときだけに使う。
    # モジュールとして読むときは、そのまま ImportError を出す。
    if __name__ != "__main__":
        raise
    _IMPORT_ERROR = _import_error
else:
    _IMPORT_ERROR = None


# --json の出力の形の版。キーを足すだけなら上げない。キーの意味や型を変えたときに上げる。
# v1.1.2 までの形（score、is_clean、metrics、findings）を1とみなす。
# 公開前の形式2の中の変更（2.0.0 の rule_penalty_score の式）では上げない。
LINT_FORMAT_VERSION = 2

# 文書の種類ごとに外す規則（種類ごとに決めた組。formal と promo はあとから足した）。
# その種類で普通な書き方を候補にしてしまう規則のうち、根拠のある組だけ。規則ID の順に並べる。検出はそのまま行い、
# 件数と点数を数える前に候補から除く（種類を限って当てる規則を除けば、種類なしの候補からこの規則を除いたものと同じ）。
# 公開の名前として読むだけにし、書き換えて使う使い方は約束しない。
DOC_TYPE_SKIP_RULES = {
    "pr": ("excess_list",),
    "article": (),
    "incident": ("excess_list",),
    "proposal": (),
    "minutes": ("bold_label_list", "excess_list", "sentence_end_repetition"),
    "manual": ("excess_list",),
    # スライドの箇条で強調として選ぶ「〜のは、A、B、C。」（cleft_list_ending）も普通の書き方として外す
    # 2.2.0: 主語も目的語もない動詞を並べる型（bare_verb_chain）もスライドの箇条では普通の書き方として外す
    "slides": ("bare_verb_chain", "bold_label_list", "cleft_list_ending", "count_declaration", "excess_list",
               "short_summary_heading"),
    # 2.2.0: 読み物、宣伝文、台詞では、見出しの短い比喩（metaphor_label）と動詞を並べる型（bare_verb_chain）を外す
    "essay": ("bare_verb_chain", "metaphor_label"),
    "formal": (),
    # 紹介記事・宣伝文では書き手の絵文字を残す（diff の勢いの検査は絵文字が減ると候補にするので、lint の
    # 絵文字の候補と食い違わせない。diff の詰めで測って決めた）。
    # 評価の語を短く重ねる型（「安い。うまい。早い。」。fragment_run）も勢いとして残す（作者の判断）
    "promo": ("bare_verb_chain", "emoji_prohibited", "fragment_run", "metaphor_label"),
    "mail": ("emoji_prohibited",),
    "paper": (),
    # 2.2.0: 台詞では、短い文の重ね（fragment_run）と同じ語尾の続き（sentence_end_repetition）が普通に出る
    "script": ("bare_verb_chain", "fragment_run", "metaphor_label", "sentence_end_repetition"),
}
# meta_filler 全体を外すと誇張や無関係な前置きまで残すため、既存の型の説明で5型だけを選ぶ。
# これらは mail では相手への返信・結びとして普通の形。宛名、挨拶、署名、クッション言葉の専用規則は元からない。
DOC_TYPE_SKIP_PATTERNS = {"mail": {"meta_filler": (
    "チャット応答の名残「ご質問ありがとうございます」",
    "チャット応答の名残「必要なら次に〜します」",
    "定型クロージング「いかがでしたでしょうか」",
    "定型クロージング「ぜひ〜してみてください」",
    "定型クロージング「参考になれば幸いです」など",
)}}
# paper: 慎重表現そのものを削る規則はない。誇張の「過言ではない」や文末反復まで一括で外さない。
# 種類を限って当てる規則（規則ID から、当てる種類のタプルへ）。種類を指定しないときと、ほかの種類では除く。
DOC_TYPE_ONLY_RULES = {
    "pause_comma": ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal", "mail", "paper"),
    # 2.2.0: 台詞の句点は script だけ、読み物の一人称と数字は essay だけ
    "dialogue_period": ("script",),
    "narrative_density": ("essay",),
}


# Emoji facts are pinned to Unicode 18.0, not broad Unicode block membership.
# Derived from Unicode, Inc. data (copyright 1991-2026); Unicode License V3
# copyright/permission notice must accompany the installed skill and ZIP.
# Sources: Unicode 18.0 emoji-data.txt, emoji-variation-sequences.txt,
# emoji-sequences.txt. No Unicode data file/network/package is read at runtime.
_EMOJI_DATA_VERSION = "18.0"
_EMOJI_REGISTERED_TEXT_BASES = (
    (0x231A, 0x231B),
    (0x2328, 0x2328),
    (0x23CF, 0x23CF),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x25FD, 0x25FE),
    (0x2600, 0x2604),
    (0x260E, 0x260E),
    (0x2611, 0x2611),
    (0x2614, 0x2615),
    (0x2618, 0x2618),
    (0x261D, 0x261D),
    (0x2620, 0x2620),
    (0x2622, 0x2623),
    (0x2626, 0x2626),
    (0x262A, 0x262A),
    (0x262E, 0x262F),
    (0x2638, 0x263A),
    (0x2640, 0x2640),
    (0x2642, 0x2642),
    (0x2648, 0x2653),
    (0x265F, 0x2660),
    (0x2663, 0x2663),
    (0x2665, 0x2666),
    (0x2668, 0x2668),
    (0x267B, 0x267B),
    (0x267E, 0x267F),
    (0x2692, 0x2697),
    (0x2699, 0x2699),
    (0x269B, 0x269C),
    (0x26A0, 0x26A1),
    (0x26A7, 0x26A7),
    (0x26AA, 0x26AB),
    (0x26B0, 0x26B1),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26C8, 0x26C8),
    (0x26CE, 0x26CF),
    (0x26D1, 0x26D1),
    (0x26D3, 0x26D4),
    (0x26E9, 0x26EA),
    (0x26F0, 0x26F5),
    (0x26F7, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2702, 0x2702),
    (0x2705, 0x2705),
    (0x2708, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2728, 0x2728),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2763, 0x2764),
    (0x2795, 0x2797),
    (0x27A1, 0x27A1),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x1F004, 0x1F004),
    (0x1F21A, 0x1F21A),
    (0x1F22F, 0x1F22F),
    (0x1F30D, 0x1F30F),
    (0x1F315, 0x1F315),
    (0x1F31C, 0x1F31C),
    (0x1F321, 0x1F321),
    (0x1F324, 0x1F32C),
    (0x1F336, 0x1F336),
    (0x1F378, 0x1F378),
    (0x1F37D, 0x1F37D),
    (0x1F393, 0x1F393),
    (0x1F396, 0x1F397),
    (0x1F399, 0x1F39B),
    (0x1F39E, 0x1F39F),
    (0x1F3A7, 0x1F3A7),
    (0x1F3AC, 0x1F3AE),
    (0x1F3C2, 0x1F3C2),
    (0x1F3C4, 0x1F3C4),
    (0x1F3C6, 0x1F3C6),
    (0x1F3CA, 0x1F3CE),
    (0x1F3D4, 0x1F3E0),
    (0x1F3ED, 0x1F3ED),
    (0x1F3F3, 0x1F3F3),
    (0x1F3F5, 0x1F3F5),
    (0x1F3F7, 0x1F3F7),
    (0x1F408, 0x1F408),
    (0x1F415, 0x1F415),
    (0x1F41F, 0x1F41F),
    (0x1F426, 0x1F426),
    (0x1F43F, 0x1F43F),
    (0x1F441, 0x1F442),
    (0x1F446, 0x1F449),
    (0x1F44D, 0x1F44E),
    (0x1F453, 0x1F453),
    (0x1F46A, 0x1F46A),
    (0x1F47D, 0x1F47D),
    (0x1F4A3, 0x1F4A3),
    (0x1F4B0, 0x1F4B0),
    (0x1F4B3, 0x1F4B3),
    (0x1F4BB, 0x1F4BB),
    (0x1F4BF, 0x1F4BF),
    (0x1F4CB, 0x1F4CB),
    (0x1F4DA, 0x1F4DA),
    (0x1F4DF, 0x1F4DF),
    (0x1F4E4, 0x1F4E6),
    (0x1F4EA, 0x1F4ED),
    (0x1F4F7, 0x1F4F7),
    (0x1F4F9, 0x1F4FB),
    (0x1F4FD, 0x1F4FD),
    (0x1F508, 0x1F508),
    (0x1F50D, 0x1F50D),
    (0x1F512, 0x1F513),
    (0x1F549, 0x1F54A),
    (0x1F550, 0x1F567),
    (0x1F56F, 0x1F570),
    (0x1F573, 0x1F579),
    (0x1F587, 0x1F587),
    (0x1F58A, 0x1F58D),
    (0x1F590, 0x1F590),
    (0x1F5A5, 0x1F5A5),
    (0x1F5A8, 0x1F5A8),
    (0x1F5B1, 0x1F5B2),
    (0x1F5BC, 0x1F5BC),
    (0x1F5C2, 0x1F5C4),
    (0x1F5D1, 0x1F5D3),
    (0x1F5DC, 0x1F5DE),
    (0x1F5E1, 0x1F5E1),
    (0x1F5E3, 0x1F5E3),
    (0x1F5E8, 0x1F5E8),
    (0x1F5EF, 0x1F5EF),
    (0x1F5F3, 0x1F5F3),
    (0x1F5FA, 0x1F5FA),
    (0x1F610, 0x1F610),
    (0x1F687, 0x1F687),
    (0x1F68D, 0x1F68D),
    (0x1F691, 0x1F691),
    (0x1F694, 0x1F694),
    (0x1F698, 0x1F698),
    (0x1F6AD, 0x1F6AD),
    (0x1F6B2, 0x1F6B2),
    (0x1F6B9, 0x1F6BA),
    (0x1F6BC, 0x1F6BC),
    (0x1F6CB, 0x1F6CB),
    (0x1F6CD, 0x1F6CF),
    (0x1F6E0, 0x1F6E5),
    (0x1F6E9, 0x1F6E9),
    (0x1F6F0, 0x1F6F0),
    (0x1F6F3, 0x1F6F3),
)

_EMOJI_OTHER_BASES = (
    (0x1F0CF, 0x1F0CF),
    (0x1F18E, 0x1F18E),
    (0x1F191, 0x1F19A),
    (0x1F201, 0x1F201),
    (0x1F232, 0x1F236),
    (0x1F238, 0x1F23A),
    (0x1F250, 0x1F251),
    (0x1F300, 0x1F30C),
    (0x1F310, 0x1F314),
    (0x1F316, 0x1F31B),
    (0x1F31D, 0x1F320),
    (0x1F32D, 0x1F335),
    (0x1F337, 0x1F377),
    (0x1F379, 0x1F37C),
    (0x1F37E, 0x1F392),
    (0x1F3A0, 0x1F3A6),
    (0x1F3A8, 0x1F3AB),
    (0x1F3AF, 0x1F3C1),
    (0x1F3C3, 0x1F3C3),
    (0x1F3C5, 0x1F3C5),
    (0x1F3C7, 0x1F3C9),
    (0x1F3CF, 0x1F3D3),
    (0x1F3E1, 0x1F3EC),
    (0x1F3EE, 0x1F3F0),
    (0x1F3F4, 0x1F3F4),
    (0x1F3F8, 0x1F407),
    (0x1F409, 0x1F414),
    (0x1F416, 0x1F41E),
    (0x1F420, 0x1F425),
    (0x1F427, 0x1F43E),
    (0x1F440, 0x1F440),
    (0x1F443, 0x1F445),
    (0x1F44A, 0x1F44C),
    (0x1F44F, 0x1F452),
    (0x1F454, 0x1F469),
    (0x1F46B, 0x1F47C),
    (0x1F47E, 0x1F4A2),
    (0x1F4A4, 0x1F4AF),
    (0x1F4B1, 0x1F4B2),
    (0x1F4B4, 0x1F4BA),
    (0x1F4BC, 0x1F4BE),
    (0x1F4C0, 0x1F4CA),
    (0x1F4CC, 0x1F4D9),
    (0x1F4DB, 0x1F4DE),
    (0x1F4E0, 0x1F4E3),
    (0x1F4E7, 0x1F4E9),
    (0x1F4EE, 0x1F4F6),
    (0x1F4F8, 0x1F4F8),
    (0x1F4FC, 0x1F4FC),
    (0x1F4FF, 0x1F507),
    (0x1F509, 0x1F50C),
    (0x1F50E, 0x1F511),
    (0x1F514, 0x1F53D),
    (0x1F54B, 0x1F54E),
    (0x1F57A, 0x1F57A),
    (0x1F595, 0x1F596),
    (0x1F5A4, 0x1F5A4),
    (0x1F5FB, 0x1F60F),
    (0x1F611, 0x1F64F),
    (0x1F680, 0x1F686),
    (0x1F688, 0x1F68C),
    (0x1F68E, 0x1F690),
    (0x1F692, 0x1F693),
    (0x1F695, 0x1F697),
    (0x1F699, 0x1F6AC),
    (0x1F6AE, 0x1F6B1),
    (0x1F6B3, 0x1F6B8),
    (0x1F6BB, 0x1F6BB),
    (0x1F6BD, 0x1F6C5),
    (0x1F6CC, 0x1F6CC),
    (0x1F6D0, 0x1F6D2),
    (0x1F6D5, 0x1F6D9),
    (0x1F6DC, 0x1F6DF),
    (0x1F6EB, 0x1F6EC),
    (0x1F6F4, 0x1F6FC),
    (0x1F7E0, 0x1F7EB),
    (0x1F7F0, 0x1F7F0),
    (0x1F90C, 0x1F93A),
    (0x1F93C, 0x1F945),
    (0x1F947, 0x1F9FF),
    (0x1FA70, 0x1FA7C),
    (0x1FA80, 0x1FAC6),
    (0x1FAC8, 0x1FAC8),
    (0x1FACC, 0x1FADD),
    (0x1FADF, 0x1FAEB),
    (0x1FAEF, 0x1FAFA),
)

_EMOJI_EXPLICIT_VARIATION_BASES = (
    (0xA9, 0xA9),
    (0xAE, 0xAE),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),
    (0x2139, 0x2139),
    (0x2194, 0x2199),
    (0x21A9, 0x21AA),
    (0x231A, 0x231B),
    (0x2328, 0x2328),
    (0x23CF, 0x23CF),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x2604),
    (0x260E, 0x260E),
    (0x2611, 0x2611),
    (0x2614, 0x2615),
    (0x2618, 0x2618),
    (0x261D, 0x261D),
    (0x2620, 0x2620),
    (0x2622, 0x2623),
    (0x2626, 0x2626),
    (0x262A, 0x262A),
    (0x262E, 0x262F),
    (0x2638, 0x263A),
    (0x2640, 0x2640),
    (0x2642, 0x2642),
    (0x2648, 0x2653),
    (0x265F, 0x2660),
    (0x2663, 0x2663),
    (0x2665, 0x2666),
    (0x2668, 0x2668),
    (0x267B, 0x267B),
    (0x267E, 0x267F),
    (0x2692, 0x2697),
    (0x2699, 0x2699),
    (0x269B, 0x269C),
    (0x26A0, 0x26A1),
    (0x26A7, 0x26A7),
    (0x26AA, 0x26AB),
    (0x26B0, 0x26B1),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26C8, 0x26C8),
    (0x26CE, 0x26CF),
    (0x26D1, 0x26D1),
    (0x26D3, 0x26D4),
    (0x26E9, 0x26EA),
    (0x26F0, 0x26F5),
    (0x26F7, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2702, 0x2702),
    (0x2705, 0x2705),
    (0x2708, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2728, 0x2728),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2763, 0x2764),
    (0x2795, 0x2797),
    (0x27A1, 0x27A1),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0x1F004, 0x1F004),
    (0x1F170, 0x1F171),
    (0x1F17E, 0x1F17F),
    (0x1F202, 0x1F202),
    (0x1F21A, 0x1F21A),
    (0x1F22F, 0x1F22F),
    (0x1F237, 0x1F237),
    (0x1F30D, 0x1F30F),
    (0x1F315, 0x1F315),
    (0x1F31C, 0x1F31C),
    (0x1F321, 0x1F321),
    (0x1F324, 0x1F32C),
    (0x1F336, 0x1F336),
    (0x1F378, 0x1F378),
    (0x1F37D, 0x1F37D),
    (0x1F393, 0x1F393),
    (0x1F396, 0x1F397),
    (0x1F399, 0x1F39B),
    (0x1F39E, 0x1F39F),
    (0x1F3A7, 0x1F3A7),
    (0x1F3AC, 0x1F3AE),
    (0x1F3C2, 0x1F3C2),
    (0x1F3C4, 0x1F3C4),
    (0x1F3C6, 0x1F3C6),
    (0x1F3CA, 0x1F3CE),
    (0x1F3D4, 0x1F3E0),
    (0x1F3ED, 0x1F3ED),
    (0x1F3F3, 0x1F3F3),
    (0x1F3F5, 0x1F3F5),
    (0x1F3F7, 0x1F3F7),
    (0x1F408, 0x1F408),
    (0x1F415, 0x1F415),
    (0x1F41F, 0x1F41F),
    (0x1F426, 0x1F426),
    (0x1F43F, 0x1F43F),
    (0x1F441, 0x1F442),
    (0x1F446, 0x1F449),
    (0x1F44D, 0x1F44E),
    (0x1F453, 0x1F453),
    (0x1F46A, 0x1F46A),
    (0x1F47D, 0x1F47D),
    (0x1F4A3, 0x1F4A3),
    (0x1F4B0, 0x1F4B0),
    (0x1F4B3, 0x1F4B3),
    (0x1F4BB, 0x1F4BB),
    (0x1F4BF, 0x1F4BF),
    (0x1F4CB, 0x1F4CB),
    (0x1F4DA, 0x1F4DA),
    (0x1F4DF, 0x1F4DF),
    (0x1F4E4, 0x1F4E6),
    (0x1F4EA, 0x1F4ED),
    (0x1F4F7, 0x1F4F7),
    (0x1F4F9, 0x1F4FB),
    (0x1F4FD, 0x1F4FD),
    (0x1F508, 0x1F508),
    (0x1F50D, 0x1F50D),
    (0x1F512, 0x1F513),
    (0x1F549, 0x1F54A),
    (0x1F550, 0x1F567),
    (0x1F56F, 0x1F570),
    (0x1F573, 0x1F579),
    (0x1F587, 0x1F587),
    (0x1F58A, 0x1F58D),
    (0x1F590, 0x1F590),
    (0x1F5A5, 0x1F5A5),
    (0x1F5A8, 0x1F5A8),
    (0x1F5B1, 0x1F5B2),
    (0x1F5BC, 0x1F5BC),
    (0x1F5C2, 0x1F5C4),
    (0x1F5D1, 0x1F5D3),
    (0x1F5DC, 0x1F5DE),
    (0x1F5E1, 0x1F5E1),
    (0x1F5E3, 0x1F5E3),
    (0x1F5E8, 0x1F5E8),
    (0x1F5EF, 0x1F5EF),
    (0x1F5F3, 0x1F5F3),
    (0x1F5FA, 0x1F5FA),
    (0x1F610, 0x1F610),
    (0x1F687, 0x1F687),
    (0x1F68D, 0x1F68D),
    (0x1F691, 0x1F691),
    (0x1F694, 0x1F694),
    (0x1F698, 0x1F698),
    (0x1F6AD, 0x1F6AD),
    (0x1F6B2, 0x1F6B2),
    (0x1F6B9, 0x1F6BA),
    (0x1F6BC, 0x1F6BC),
    (0x1F6CB, 0x1F6CB),
    (0x1F6CD, 0x1F6CF),
    (0x1F6E0, 0x1F6E5),
    (0x1F6E9, 0x1F6E9),
    (0x1F6F0, 0x1F6F0),
    (0x1F6F3, 0x1F6F3),
)

_EMOJI_FLAG_REGION_CODES = (
    "AC AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD "
    "BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC "
    "CD CF CG CH CI CK CL CM CN CO CP CQ CR CU CV CW CX CY CZ DE "
    "DG DJ DK DM DO DZ EA EC EE EG EH ER ES ET EU FI FJ FK FM FO "
    "FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY "
    "HK HM HN HR HT HU IC ID IE IL IM IN IO IQ IR IS IT JE JM JO "
    "JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT "
    "LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT "
    "MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA "
    "PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA "
    "SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ "
    "TA TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM "
    "UN US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW "
).split()

def _emoji_character_class(ranges):
    """Build a compact stdlib regex class from pinned scalar intervals."""
    def escaped(cp):
        return "\\u%04x" % cp if cp <= 0xFFFF else "\\U%08x" % cp
    return "[" + "".join(escaped(lo) if lo == hi else escaped(lo) + "-" + escaped(hi)
                         for lo, hi in ranges) + "]"


def _emoji_flag_pattern():
    """Recognize only flag pairs in the pinned registered-region data."""
    seconds = {}
    for code in _EMOJI_FLAG_REGION_CODES:
        seconds.setdefault(code[0], set()).add(code[1])
    groups = []
    for first in sorted(seconds):
        first_cp = 0x1F1E6 + ord(first) - ord("A")
        second_cps = [0x1F1E6 + ord(ch) - ord("A") for ch in sorted(seconds[first])]
        groups.append(_emoji_character_class(((first_cp, first_cp),)) +
                      _emoji_character_class(tuple((cp, cp) for cp in second_cps)))
    return "(?:" + "|".join(groups) + ")"


# Preserve the public compiled Pattern interface and noncapturing findall.
# Legacy Emoji=Yes/default-emoji bases remain style candidates. Registered
# VS15 is text; qualified keycaps/flags and explicit VS16 are emoji candidates.
EMOJI_PATTERN = re.compile(
    "(?:" + _emoji_flag_pattern() +
    r"|[0-9#*]\ufe0f\u20e3" +
    "|" + _emoji_character_class(_EMOJI_EXPLICIT_VARIATION_BASES) + r"\ufe0f" +
    "|" + _emoji_character_class(_EMOJI_REGISTERED_TEXT_BASES) + r"(?!\ufe0e)" +
    "|" + _emoji_character_class(_EMOJI_OTHER_BASES) + ")"
)

# Every default branch begins with one of these scalar classes. Enumerating
# only those starts avoids retrying the flag/variation alternation at each
# Japanese character, while the original Pattern remains the public object.
_EMOJI_DEFAULT_PATTERN = EMOJI_PATTERN
# A small conservative superset is faster than hundreds of duplicate scalar
# intervals. All pinned default-branch starts are inside these intervals;
# extra symbols remain candidates only and the original Pattern rejects them.
_EMOJI_START_PATTERN = re.compile(
    r"[0-9#*](?=\ufe0f\u20e3)|[\u00a9-\u2fff\u3030\u303d\u3297\u3299\U0001f000-\U0001faff]"
)


def _emoji_matches(text):
    """Preserve findall order/non-overlap, and custom public-pattern behavior."""
    if EMOJI_PATTERN is not _EMOJI_DEFAULT_PATTERN:
        return EMOJI_PATTERN.findall(text)
    matches = []
    previous_end = 0
    for start in _EMOJI_START_PATTERN.finditer(text):
        position = start.start()
        if position < previous_end:
            continue
        matched = EMOJI_PATTERN.match(text, position)
        if matched is not None:
            matches.append(matched.group(0))
            previous_end = matched.end()
    return matches


# 文末に固定した規則は、文の終わりの後ろに続く飾りを読み飛ばして判定する。
# 飾りは、空白（全角も）と、emoji_prohibited が絵文字として拾う字（EMOJI_PATTERN の元の表から作る。異体字セレクタ、
# ZWJ、肌の色、タグ、旗、キーキャップを含む）と、☆♪✓のような記号。絵文字そのものは emoji_prohibited で別に拾う。
# 句点、感嘆符、疑問符は飾りではないので、除かずに位置だけを詰める
# （「見ていきましょう🚀！」は「見ていきましょう！」として読み、「見ていきましょう？🚀」は「見ていきましょう？」として読む）。
# 閉じかっこ（）)】〕〉》］）、矢印（←↑→↓）、波線（〜～）を飾りに数えるのは、文の型を見る規則だけ（_END_CLOSERS）。
# 閉じかっこは、対の開きかっこが文の頭か、句点か述語（です、ます、た など）の直後にあるとき
# （「（見ていきましょう）」「〜まとめました（後半で見ていきましょう）」）だけ除く。目次の副題（「実践編（〜）」）は除かない。
# 閉じかぎと引用符（」』”’"'）は、同じ段落のその行までに対の開きがない行でだけ除く（_end_quote_closers）。
# リンクの文字列の終わりになる ASCII の ] は、どの規則でも飾りに数えない。
def _merged_ranges(ranges):
    merged = []
    for low, high in sorted(ranges):
        if merged and low <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    return tuple(merged)


# 文末の後ろに置かれる記号（絵文字の表にない ☆♪✓ などを含む）と、絵文字の並びをつなぐ字
_END_SYMBOL_RANGES = ((0x2600, 0x27BF), (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55),
                      (0x231A, 0x231B), (0x23E9, 0x23FA), (0x2934, 0x2935), (0x3297, 0x3297), (0x3299, 0x3299),
                      (0x1F000, 0x1FAFF))
_END_JOINER_RANGES = ((0xFE0E, 0xFE0F), (0x200D, 0x200D), (0xE0020, 0xE007F))
# 絵文字の判定（EMOJI_PATTERN）の元の表と、旗の地域指示子を足す。手で写さず同じ表から作るので、範囲がずれない
_END_VISIBLE_RANGES = _merged_ranges(_END_SYMBOL_RANGES + _EMOJI_EXPLICIT_VARIATION_BASES
                                     + _EMOJI_REGISTERED_TEXT_BASES + _EMOJI_OTHER_BASES + ((0x1F1E6, 0x1F1FF),))
_END_VISIBLE_CHARS = _emoji_character_class(_END_VISIBLE_RANGES)[1:-1]
_END_JOINER_CHARS = _emoji_character_class(_END_JOINER_RANGES)[1:-1]
_END_DECORATION_CHARS = _END_VISIBLE_CHARS + _END_JOINER_CHARS
_END_DECORATION_CHAR = re.compile("[" + _END_DECORATION_CHARS + "]")
_END_KEYCAP = r"[0-9#*]\ufe0f?\u20e3"
# 正規表現の中で、文末の前に置ける飾りの並び（空でもよい）
_END_DECORATION_RUN = r"(?:" + _END_KEYCAP + r"|[\s" + _END_DECORATION_CHARS + r"])*"
_END_BRACKETS = {"）": "（", ")": "(", "】": "【", "〕": "〔", "〉": "〈", "》": "《", "］": "［"}
_END_CLOSERS = "".join(_END_BRACKETS) + "←↑→↓〜～"
_END_QUOTES = {"」": "「", "』": "『", "”": "“", "’": "‘", '"': '"', "'": "'"}
_END_MARKS = "。．！？!?"
_END_BRACKET_AFTER_PREDICATE = re.compile(r"(?:です|ます|でした|ました|ません|ない|だ|た|る)$")


def _bracket_opens_sentence(text, position, closer):
    """text[position] の閉じかっこと対の開きかっこが、文の頭か、句点か述語の直後にあるか。

    見るのは閉じかっこの前の256字まで。そこで分からなければ除かない（長い行でも手間を抑える）。"""
    opener = _END_BRACKETS[closer]
    floor = max(0, position - 256)
    depth = 0
    index = position
    while index > floor:
        index -= 1
        char = text[index]
        if char == closer:
            depth += 1
        elif char == opener:
            if depth:
                depth -= 1
                continue
            before = index
            while before > floor and (text[before - 1].isspace() or _END_DECORATION_CHAR.match(text[before - 1])):
                before -= 1
            if not before:
                return True
            return before > floor and (text[before - 1] in _END_MARKS
                                       or bool(_END_BRACKET_AFTER_PREDICATE.search(text, max(0, before - 3), before)))
    return False


def _strip_end_decoration(text, closers=""):
    """文の終わりの後ろの飾りを除いた文を返す。飾りがなければ text をそのまま返す。

    句点、感嘆符、疑問符は残し、飾りとの並びの順も保つ。closers の字（閉じかっこ、矢印、波線と、
    呼び出し側が確かめた閉じ引用符）も飾りとして除く。閉じかっこは、対の開きかっこが文の頭か、句点か述語の直後に
    あるときだけ除く。"""
    position = len(text)
    marks = []
    removed = False
    while position:
        char = text[position - 1]
        if char in _END_MARKS:
            marks.append(char)
            position -= 1
        elif char == "\u20e3":
            removed = True
            position -= 1
            if position and text[position - 1] == "\ufe0f":
                position -= 1
            if position and text[position - 1] in "0123456789#*":
                position -= 1
        elif char.isspace() or _END_DECORATION_CHAR.match(char):
            removed = True
            position -= 1
        elif char in closers and (char not in _END_BRACKETS or _bracket_opens_sentence(text, position - 1, char)):
            removed = True
            position -= 1
        else:
            break
    if not removed:
        return text
    return text[:position] + "".join(reversed(marks))


# 文の途中で、句点の代わりに置いた絵文字の並び（「いかがでしたか😊 次回も…」）。並びは見える飾りの字で始まる。
_END_BREAK_RUN = re.compile(r"(?:" + _END_KEYCAP + r"|[" + _END_VISIBLE_CHARS + r"])"
                            r"(?:" + _END_KEYCAP + r"|[\s" + _END_DECORATION_CHARS + r"])*")
# 並びのあとが助詞なら、文が続いている（「いかがでしたか🚀という結び」「🍎を買う」）。
# 並びのあとが字（かな、漢字、英数字）でなく、かっこや記号のときも分けない（「〜です♪（笑）」）
_END_BREAK_CONTINUES = re.compile(
    r"(?:と|って|の|を|が|は|に|へ|や|か|から|まで|より|など|だけ|で(?![はも])|も(?!ちろん|し|っと|う)|ー)")
# 並びの前が助詞や読点なら、絵文字が語の代わりになっている（「設定は⚙ボタンから」）
_END_BREAK_HEAD_CHARS = "はがをのにでとへやも、，,：:"
_END_BREAK_PAIRS = (("「", "」"), ("『", "』"), ("（", "）"), ("(", ")"), ("【", "】"), ("“", "”"),
                    ("［", "］"), ("[", "]"))


def _decoration_breaks(sentence):
    """句点の代わりに絵文字の並びを置いて次の文を続けた所で分けた文の並びを返す。分けられなければ None。

    分けた文は後ろに絵文字の並びを残す（呼び出し側が _strip_end_decoration で除く）。
    かっこや引用の中と、助詞や記号が続く所では分けない。"""
    if not _END_DECORATION_CHAR.search(sentence):
        return None
    pieces = []
    start = scanned = 0
    # 分けた所からのかっこの開きの数（開き − 閉じ）と、空白でない字があるか。長い行でも1回なめるだけにする
    balance = dict.fromkeys(_END_BREAK_PAIRS, 0)
    has_text = False
    length = len(sentence)
    for run in _END_BREAK_RUN.finditer(sentence):
        segment = sentence[scanned:run.start()]
        scanned = run.start()
        if segment:
            has_text = has_text or not segment.isspace()
            for pair in _END_BREAK_PAIRS:
                balance[pair] += segment.count(pair[0]) - segment.count(pair[1])
        end = run.end()
        word = end
        while word < length and sentence[word] in "*_":
            word += 1
        if word >= length or not sentence[word].isalnum() or _END_BREAK_CONTINUES.match(sentence, word):
            continue
        last = run.start()
        while last > start and sentence[last - 1].isspace():
            last -= 1
        if (not has_text or last == start or sentence[last - 1] in _END_BREAK_HEAD_CHARS
                or any(value > 0 for value in balance.values())):
            continue
        pieces.append(sentence[start:end])
        start = scanned = end
        balance = dict.fromkeys(_END_BREAK_PAIRS, 0)
        has_text = False
    if not pieces:
        return None
    pieces.append(sentence[start:])
    return pieces


def _with_undecorated(sentences, closers=_END_CLOSERS):
    """文の並びに、文末の飾りを除いた文と、句点の代わりの絵文字で分けた文を足す（飾りのない文はそのまま）。"""
    result = list(sentences)
    for sentence in sentences:
        core = _strip_end_decoration(sentence, closers)
        if core is not sentence:
            result.append(core)
        for piece in _decoration_breaks(sentence) or ():
            result.append(_strip_end_decoration(piece, closers))
    return result


def _end_quote_closers(analysis):
    """行ごとに、文末の飾りとして除いてよい閉じ引用符を返す。

    同じ段落（箇条書きは項目ごと）のその行までに対の開き（「『“‘）がない閉じかぎと閉じ引用符だけを除く。
    "' は、その行までに1つしかなく、それがその行にあるときだけ除く。対になった引用（語への言及や会話）は除かない。"""
    allowed = {}
    for block in analysis["blocks"]:
        if block["kind"] not in ("paragraph", "list"):
            continue
        counts = dict.fromkeys(_END_QUOTES.values(), 0)
        for row in block["lines"]:
            visible = _prose_visible_text(analysis, row["line"])
            for opener in counts:
                counts[opener] += visible.count(opener)
            chars = "".join(closer for closer, opener in _END_QUOTES.items()
                            if closer in visible and counts[opener] == (1 if closer == opener else 0))
            if chars:
                allowed[row["line"]] = chars
    return allowed


def _end_closers_for(analysis, line_no):
    """文の型を見る規則が、その行の文末で飾りとして除く字（閉じかっこ、矢印、波線と、対のない閉じ引用符）。"""
    allowed = analysis.get("_end_quote_closers")
    if allowed is None:
        allowed = analysis["_end_quote_closers"] = _end_quote_closers(analysis)
    return _END_CLOSERS + allowed.get(line_no, "")

# 文脈を確かめる語の一覧。含まれていることだけでは誤りとしない。
SLOP_WORDS = [
    # 質感を装う疑似具体語
    "手触り", "肌感", "肌感覚", "体温", "温度感", "熱量", "血の通った", "泥臭い", "泥臭さ",
    # 認知・評価を装う語
    "解像度", "腹落ち", "メンタルモデル", "本質的", "地に足のついた", "等身大",
    # 抽象比喩名詞
    "営み", "土台", "羅針盤", "起爆剤", "触媒",
    # 日常の体験を大げさに表す場合がある語
    "虚飾", "境地", "美学", "深淵", "冷徹", "禁欲的", "優美", "極致", "宿命",
    # 指す役割を確かめる語
    "正本",
]

# 部分一致では別の語を巻き込むため、形で確かめる語（語, パターン）
_TRUTH_PATTERN = r"真理(?!値|表|関数|条件|集合|子|恵|奈|亜|絵|江|さん|ちゃん|様)"
# 機器の名前を作る前の語。ここにない漢字の語との複合語（増幅装置、思考装置、演出装置、文化装置、舞台装置など）は拾う。
_DEVICE_LITERAL_PREFIXES = (
    "安全", "制御", "記憶", "表示", "入力", "出力", "測定", "計測", "冷却", "加熱", "照明", "通信", "医療", "実験",
    "警報", "処理", "演算", "記録", "検出", "検知", "検査", "分析", "試験", "製造", "発電", "変電", "駆動", "制動",
    "操舵", "推進", "噴射", "点火", "排気", "換気", "空調", "暖房", "冷房", "冷凍", "浄化", "濾過", "給水", "排水",
    "消火", "防火", "防犯", "監視", "撮影", "投影", "映写", "音響", "録音", "受信", "送信", "中継", "露光", "洗浄",
    "乾燥", "粉砕", "搬送", "昇降", "分離", "蒸留", "電源", "補助", "予備", "非常", "救命", "維持", "透析", "照射",
    "診断", "治療", "計算", "周辺", "端末", "遮断", "保護", "防護", "防止", "固定", "連結", "緩衝", "減速", "変速",
    "蓄電", "充電", "給電", "印刷", "複写", "読取", "走査", "識別", "認証", "暗号", "圧縮", "自動", "遠隔", "計量",
    "包装", "溶接", "切断", "加工", "研磨", "塗装", "成形", "射出", "送風", "集塵", "加湿", "除湿", "殺菌", "滅菌",
    "培養", "撹拌", "混合", "選別", "航法", "着陸", "発射", "照準", "起爆", "時限", "発光", "警告", "信号", "制震",
    "免震", "防振", "保安", "調整", "調節", "変換", "変圧", "整流", "発振", "映像", "画像", "光学", "電子", "油圧",
    "空圧", "真空", "排煙", "消音", "防音", "供給", "回収", "循環", "浄水", "揚水", "貯蔵", "運搬", "牽引", "計装",
    "電波", "音波", "取り", "読取り",
)
# 前が漢字か平仮名か文の頭で、上の語でないときだけ拾う。カタカナと英数字の語のあと（レーザー装置、X線装置）は機器の名前として除く。
# 機器の操作や状態の語が同じ文で後ろに続く単独の「装置」（「この装置は、毎朝自動で起動します」）も除く。
_DEVICE_PATTERN = (r"(?:(?<![ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ線])|(?<=イデオロギー))"
                   + "".join("(?<!" + "|".join(group) + ")" for group in (
                       sorted(w for w in _DEVICE_LITERAL_PREFIXES if len(w) == 2),
                       sorted(w for w in _DEVICE_LITERAL_PREFIXES if len(w) == 3)))
                   + r"装置(?![^。！？!?]{0,20}?(?:電源|起動|停止|配線|ケーブル|スイッチ|ボタン|ランプ|点検|修理|故障|稼働"
                     r"|作動|設置|取扱|取り扱|保守|校正|電池|電圧|電流))")
SLOP_WORD_PATTERNS = [
    # ナビゲート、デリゲートなど -gate で終わる外来語は、直前のカタカナで除く（レビューゲートなどは拾う）。
    ("ゲート", r"(?:(?<![ァ-ヴー])|(?<=レビュー)|(?<=リリース)|(?<=チェック)|(?<=デプロイ)|(?<=マージ)|(?<=テスト))"
               r"(?<!搭乗)(?<!改札)ゲート(?!ウ[ェエ]イ|ボール|キーパー)"),
    # 数学の閉包（推移閉包、閉包演算など）や、会計・行政の台帳は定義どおりの用語として残す。
    ("閉包", r"(?<!推移)(?<!反射)(?<!対称)(?<!凸)(?<!代数)(?<!代数的)閉包(?!演算)"),
    ("台帳", r"(?<!資産)(?<!住民基本)(?<!会計)(?<!会計の)(?<!行政の)(?<!課税)(?<!土地)(?<!家屋)(?<!備品)(?<!登記)台帳"),
    ("〜のOS", r"(思考|意思決定|仕事|人生|組織|チーム|学習|経営)の?OS(?![A-Za-z])"),
    ("本質を突く", r"本質を突"),
    # 真理値、真理表など論理学の用語と、真理子などの名前は除く（「人生の真理」「〜という真理」は拾う）。
    ("真理", _TRUTH_PATTERN),
    # 安全装置、制御装置、表示装置のように、機器の名前を作る語と結んだ「装置」は除く。
    # 比喩の複合語（増幅装置、思考装置、舞台装置など）と、「〜という装置」「〜の装置」のような単独の使い方は拾う。
    ("装置", _DEVICE_PATTERN),
]

# 英語の技術用語を辞書的な漢語にした直訳。「日本語版」「回帰テスト」など定着した用語は形で除外する。
# 出版物の語。同じ文でこれより後ろにある「次の版では」などは、出版物の版として残す。
# 語として単独で使うときだけ数える。前にカタカナや英数字が付く語（ユーザー辞書、システム辞書）と、
# 後ろに漢字やカタカナ、英数字が続く複合語（辞書型、辞書順、辞書アプリ、辞書ファイル、新聞記事、出版社、初版リリース）は、
# ソフトウェアの語のことが多いので数えない（後ろが「版・化・時・後・前」のとき、改訂版、文庫化、増刷時などは数える）。
# 「本」「本書」「原書」「新書」は、前に漢字や数字がないときだけ数える（日本、基本、本番、本ツール、3本、日本書紀は数えない）。
_PUBLICATION_AFTER = r"(?!(?![版化時後前])[一-龥々ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ])"
_PUBLICATION_WORDS = (r"(?:(?<![ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ])"
                      r"(?:辞書|辞典|事典|図鑑|書籍|文庫|全集|単行本|雑誌|教科書|絵本|新聞|増刷|重版|改訂|改版|初版"
                      r"|刊行|出版|版元|訳書|冊子|写真集|画集|詩集|歌集|句集|作品集|論文集|選集|叢書|出版物|刊行物"
                      r"|第[0-9０-９一二三四五六七八九十百]+版)"
                      r"|(?<![一-龥々ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ])(?:本書|原書|新書))" + _PUBLICATION_AFTER
                      + r"|(?<![一-龥々0-9０-９])本(?![一-龥々ァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ])")
# 文の頭（行頭か、。．！？!? の直後）から出版物の語を通らずに「この版では」などまで届くときだけ拾う（ソフトウェアの「この版では」は拾う）。
_VERSION_DEMONSTRATIVE_PATTERN = (r"(?:^|(?<=[。．！？!?]))(?:(?!" + _PUBLICATION_WORDS + r")[^。．！？!?])*?"
                                  r"(この|その|あの|新しい|古い|最新の|前の|次の|今の|現在の|以前の)版(では|で|に|から|を|が|へ|の)")
TRANSLATED_TERM_PATTERNS = [
    (_VERSION_DEMONSTRATIVE_PATTERN, "「版」（version）"),
    # 「日本語版を更新」「第2版を更新」のように、語の一部としての「版」は除く。
    (r"(?<![一-龥ァ-ヴーA-Za-z0-9])版を(上げ|下げ|更新|戻)", "「版」（version）"),
    (r"(?<!原点)(?<!への)(?<!先祖)(?<!平均)回帰(が|を)(出|発生|起こ|起き|生じ|防)", "「回帰」（regression）"),
]

# ダッシュ類。em dash（—）、horizontal bar（―）、罫線（─ ━）。en dash（–）、長音（ー）、波ダッシュ（〜）は含めない。
DASH_CHARS = "—―─━"
_DASH_RUN = re.compile("[" + DASH_CHARS + "]+")
# 木構造やASCII図に使う罫線。これを含む行は図とみなし、ダッシュの検査をしない。
_DIAGRAM_CHARS = re.compile(r"[│┃├┣└┗┌┏┐┓┘┛┬┳┴┻┼╋╭╮╰╯]")
# 短い語を読点で3つ以上並べ、ダッシュで閉じて文を終える形（「速さ、軽さ、静けさ──。」）。文ごとに見る。
_LIST_ITEM = r"[^、。！？!?\s" + DASH_CHARS + "]{1,12}"
_DASH_LIST_ENDING = re.compile(
    r"(?:^|(?<=[。！？!?]))\s*" + _LIST_ITEM + "(?:、[ \t　]*" + _LIST_ITEM + "){2,}[ \t　]*[" + DASH_CHARS + "]+" + _END_DECORATION_RUN + "(?:[。．.]|$)")
# 出典ラベル、著者と書名、英語の著者名と書誌情報を手掛かりにする。短い行というだけでは除外しない。
_ATTRIBUTION_LABEL = re.compile(r"^(?:出典|引用元|著者|Source|Author)\s*[:：]", re.IGNORECASE)
_ATTRIBUTION_BOOK = re.compile(r"^[一-龥々ァ-ヴーA-Za-z .・'’-]+『[^』]+』(?:[ \t　]*(?:（[^）]*）|\([^)]*\)))*[。.]?$")
_ATTRIBUTION_ENGLISH = re.compile(r"^[A-Z][A-Za-z.'’−-]*(?:[ \t]+[A-Z][A-Za-z.'’−-]*)+,[ \t]+\S")
# 「人間」「作業時間」「目線」などの普通名詞は、区間を表す接尾辞と取り違えない。
_NON_ROUTE_ENDINGS = ("人間", "時間", "期間", "空間", "世間", "仲間", "手間", "目線", "視線", "動線", "光線", "伏線", "生命線", "方便", "利便", "不便")


def _is_dash_attribution(text):
    text = text.strip()
    if not text or text[0] not in DASH_CHARS:
        return False
    credit = text.lstrip(DASH_CHARS + " \t　")
    return bool(_ATTRIBUTION_LABEL.match(credit) or _ATTRIBUTION_BOOK.match(credit)
                or _ATTRIBUTION_ENGLISH.match(credit))


def _mask_quoted_segments(text):
    """Mask balanced quotes, including nesting, in one pass plus a prefix sum."""
    closing = {"「": "」", "『": "』", "[": "]"}
    stacks = {closer: [] for closer in closing.values()}
    changes = [0] * (len(text) + 1)
    for index, char in enumerate(text):
        if char in closing:
            stacks[closing[char]].append(index)
        elif char in stacks and stacks[char]:
            start = stacks[char].pop()
            changes[start] += 1
            changes[index + 1] -= 1
    depth = 0
    result = []
    for index, char in enumerate(text):
        depth += changes[index]
        result.append(" " if depth else char)
    return "".join(result)


_QUOTE_MARKS = re.compile(r"[「」『』\[\]]")


def _mask_quoted_segments_sparse(text):
    """Same output as _mask_quoted_segments, but visits only the bracket marks.

    Used for whole documents, where the per-character loop is the main cost.
    """
    closing = {"「": "」", "『": "』", "[": "]"}
    stacks = {closer: [] for closer in closing.values()}
    changes = {}
    for match in _QUOTE_MARKS.finditer(text):
        index = match.start()
        char = text[index]
        if char in closing:
            stacks[closing[char]].append(index)
        elif stacks[char]:
            start = stacks[char].pop()
            changes[start] = changes.get(start, 0) + 1
            changes[index + 1] = changes.get(index + 1, 0) - 1
    if not changes:
        return text
    pieces = []
    depth = 0
    cursor = 0
    for point in sorted(changes):
        if not changes[point]:
            continue
        pieces.append(" " * (point - cursor) if depth else text[cursor:point])
        cursor = point
        depth += changes[point]
    pieces.append(" " * (len(text) - cursor) if depth else text[cursor:])
    return "".join(pieces)


def _mask_route_dashes(text):
    """Scan the adjacent noun runs once per dash, avoiding regex backtracking."""
    def noun_char(char):
        return "一" <= char <= "龥" or "ァ" <= char <= "ヴ" or char in "ー々"

    result = list(text)
    for match in _DASH_RUN.finditer(text):
        left, right = match.start(), match.end()
        if right - left != 1 or left == 0 or right == len(text):
            continue
        if not noun_char(text[left - 1]) or not noun_char(text[right]):
            continue
        end = right
        while end < len(text) and noun_char(text[end]):
            end += 1
        destination = text[right:end]
        for index, char in enumerate(destination):
            if char not in "間線便":
                continue
            end = index + 1
            suffix_length = 2 if destination.endswith("区間", 0, end) else 1
            if end > suffix_length and not destination.endswith(_NON_ROUTE_ENDINGS, 0, end):
                result[left] = " "
                break
    return "".join(result)


# ダッシュで補足や言い換えを挟む形（「今日——正確には昨日——連絡しました。」）
_DASH_INSERTION = re.compile("[" + DASH_CHARS + "]{1,2}[^" + DASH_CHARS + "。\n]{1,40}[" + DASH_CHARS + "]{1,2}")
# 小説などで、同じ文書に同じ指摘を出しすぎないよう、ダッシュの指摘は1文書あたりこの件数までにする。
# 上限は種類で外した候補を除いたあとに当て、点数には上限の前の数（当たった行の数）を使う。
DASH_FINDING_LIMIT = 3

# 「」『』の中は会話文や記号への言及、リンクの文字列は引用した題名として扱う。
_QUOTED_SEGMENT = re.compile(r"「[^「」]*」|『[^『』]*』|\[[^\[\]]*\]")
# リンクの直後に著者などを添える区切り（「[記事](URL) — 著者氏」）。表示上のテキストではURLが空白になる。
_LINK_ATTRIBUTION = re.compile(r"\][ \t]*[" + DASH_CHARS + "]+")


_QUESTION_CLOSERS = "」』）)\"'*_"
_QUESTION_SUFFIXES = ("ですか", "ますか", "ませんか", "でしょうか", "だろうか", "のか", "ないか",
                      "うか", "くか", "ぐか", "すか", "つか", "ぬか", "ぶか", "むか", "るか", "たか", "いいか", "よいか")
_WH_QUESTION = re.compile(
    r"なぜ|どうして(?!も)|どのよう(?:に|な)|いつ(?!でも|も|か(?!ら))|どこ(?!でも|も|か(?!ら))|"
    r"誰(?!でも|も|か(?!ら))|何(?!でも|も|か(?!ら))|どれ(?!でも|も|か(?!ら))|どの(?![^。！？!?、]{1,12}でも)"
)


def _question_content_end(sentence):
    end = len(sentence)
    while end and (sentence[end - 1].isspace() or sentence[end - 1] in _QUESTION_CLOSERS
                   or _END_DECORATION_CHAR.match(sentence[end - 1])):
        end -= 1
    return end


def _last_context_sentence(text):
    end = _question_content_end(text)
    if not end:
        return ""
    start = max(text.rfind(mark, 0, end - 1) for mark in "。！？!?") + 1
    return text[start:end]


def _ends_with_question(sentence):
    """Recognize an adjacent yes/no question, not an arbitrary word ending in か."""
    end = _question_content_end(sentence)
    if not end:
        return False
    explicit = sentence[end - 1] in "？?"
    if not explicit and sentence[end - 1] == "。":
        end -= 1
    if not explicit and (sentence.endswith("いくつか", 0, end)
                         or not sentence.endswith(_QUESTION_SUFFIXES, 0, end)):
        return False
    return _WH_QUESTION.search(sentence, 0, end) is None


def _dash_finding(text, line_no, snippet):
    """Flag decorative dashes once per line; diagrams, dividers and attributions are not prose."""
    if not _DASH_RUN.search(text):
        return None
    if _is_dash_attribution(text):
        text = text.lstrip().lstrip(DASH_CHARS)
    text = _mask_route_dashes(_mask_quoted_segments(_LINK_ATTRIBUTION.sub("]", text))).strip()
    rest = text.strip(DASH_CHARS + " 　")
    if not _DASH_RUN.search(text) or _DIAGRAM_CHARS.search(text) or not rest:
        return None
    # 「――◆――」のように記号だけを挟んだ区切り線や、出典表記の行は散文ではない。
    if all(unicodedata.category(ch)[0] in "PSZ" or ch in DASH_CHARS for ch in rest):
        return None
    if _DASH_LIST_ENDING.search(text):
        rule = "dash_list_ending"
        message = ("名詞を読点で並べて末尾を「──」などのダッシュで閉じる書き方が検出されました。余韻を装う装飾に見えやすいため、"
                   "何についての列挙かを述語で言い切ってください。文脈から述語が分からない場合は、推測で補わず書き手に確かめてください。")
    elif _DASH_INSERTION.search(text):
        rule = "dash_insertion"
        message = ("補足や言い換えをダッシュで挟む書き方が検出されました。読点や助詞、括弧でつなぐか、文を分けてください。"
                   "ただし、小説や随筆で書き手が文体として使っている場合や、引用は残してかまいません。")
    else:
        rule = "dash_decoration"
        message = ("ダッシュ記号（—、―、──など）が検出されました。補足や余韻のための装飾であれば、読点や助詞、括弧でつなぐか、"
                   "文を分けてください。ただし、小説や随筆で書き手が文体として使っている場合や、引用は残してかまいません。")
    return {"rule": rule, "line": line_no, "severity": "warn", "message": message, "snippet": snippet}


_DASH_FINDING_DEFAULT = _dash_finding
_DASH_RUN_DEFAULT = _DASH_RUN

# 「〜した瞬間」は、時刻を文字どおり表す「ボタンを押した瞬間に、画面が真っ白になる」
# 「保存せずに終了した瞬間に、編集内容は失われます」では拾わない。直訳の形として、次を拾う。
# - 「手にした瞬間」など五感の語
# - 「〜を目的にした瞬間」「〜を優先した瞬間」「〜を目指した瞬間」のような一般論の前置き
# - 「〜した瞬間だった」で文を結ぶ形（「〜のは、〜した瞬間でした」のように時刻を答える文は除く）
# - 同じ句のうち（40字まで）に、品質、価値、意味、目的、それ などの抽象的な主語が続く形
# - すぐあとに「わかる」「実感」「確信」「崩れる」が続く形と、「全滅」「世界が変わる」「すべてが動き出す」のような大げさな結果
_MOMENT_ABSTRACT = (r"(?:品質|価値|信頼|指標|意味|目的|本質|理解|学び|成長|可能性|魅力|違い|良さ|大切さ|重要性"
                    r"|情熱|やる気|モチベーション|創造性|(?<!お)それ)(?:は|が|も)")
_MOMENT_PATTERN = (r"(?:手|目|口|耳)にした瞬間"
                   r"|(?:目的|目標|ゴール|指標|手段)にした瞬間|(?:優先|目指|追求|追い求め)した瞬間"
                   r"|(?:^|(?<=[。．！？!?]))(?:(?!のは)[^。．！？!?])*?した瞬間(?:だった|でした)(?=" + _END_DECORATION_RUN + r"(?:[。．！？!?」』）)]|$))"
                   r"|した瞬間(?:に|から)?(?:は|も)?[、，,]?"
                   r"(?:(?:わか|分か)(?:る|り|った|ら)|悟|実感|確信|理解(?:する|した|でき)|崩れ|崩壊)"
                   r"|した瞬間(?:に|から)?(?:は|も)?[、，,]?[^、，,。！？!?]{0,40}?"
                   r"(?:" + _MOMENT_ABSTRACT + r"|全滅|台無し|無意味|色あせ|色褪せ|虜|魅了|心を奪"
                   r"|(?:世界|景色|人生|価値観|見え方)が(?:一変|変わ)"
                   r"|(?:すべて|全て|何もかも)が?(?:変わ|動き出|始ま|一変|つなが|繋が|報われ|輝))")

# 比喩の「効く」（何がどう良くなるのかを書かない「効く」）。
# 表の正規表現は動詞の「効く」（効か・効き・効く・効け・効い）を見つけるだけで、拾うかどうかは _kiku_metaphor_in_line が
# 文ごとに決める（語の表で文を絞る速い経路でも、すべての文に当てる経路でも、同じ関数を通す）。拾うのは次の3つの形。
# - v2.1.0 から拾っている「地味に」「よく」「じわじわ」の直後の「効く」（「よく効かない」も今までどおり拾う）
# - 見直し、工夫、改善、施策 などの手順や取り組みを主語にした「効く」「効いた」。主語の語と助詞のあとに読点を1つまで挟んでよい。
#   「見直したのが」「工夫したことが」のような名詞にした主語、「改善から効く」、「見直しの効き目が出る」も拾う
#   （主語の分からない「効き目が出る」は拾わない）。
# - 効き目がだんだん表れることを言う「効いてくる」「効いてきます」「効いてきた」「効いてくれる」「効き始める」と、
#   「後から」「後で」「後になって」「徐々に」などの副詞のあとの「効く」
# 次のときは拾わない。
# - 「効く」の主語や対象に当たる位置（語のすぐあとの「が」「は」「の」「に」「、」などから10字まで）に、薬、冷房、ブレーキ、
#   わさびや辛さ、圧縮や最適化のような、文字どおり効き目が出るものの語があるとき（どの形でも）
# - 「融通が効く」「気が効く」のような「利く」の慣用句（どの形でも。「効く」と「利く」の表記の違いはこの規則では扱わない）
# - 2つ目と3つ目の形の打ち消し（「効かない」「効いていない」「効いてこない」）
# - 3つ目の形だけに当たる文で、同じ文、同じ行の前の文、前の3行のどこかに文字どおりの語（服用、飲んで、サプリ、コーヒー など）が
#   あるときと、同じ文に「30分ほど」「1時間後」のような分や時間の長さがあるとき（薬や冷房の効き方の説明）
# 文字どおりの語は、すぐあとに漢字やカタカナが続く所では語とみなさない（「塩谷さん」「酒井さん」「居酒屋」「毒舌」
# 「製剤チーム」「治療方針」「キャッシュ戦略」「インデックス投資」）。
_KIKU_END = "。．！？!?"
_KIKU_PATTERN = r"効[かきくけいた]"
_KIKU_LITERAL = (
    # 薬と体
    r"薬|剤|(?<=[0-9０-９数一二三四五六])錠|抗生物質|ワクチン|注射|点滴|麻酔|湿布|漢方|治療|鍼|ツボ|マッサージ|サプリメント|サプリ"
    r"|服用|服薬|内服|接種|症状|頭痛|腰痛|肩こり|肩凝り|花粉症|風邪|二日酔い|鼻炎|乾燥肌|肌荒れ|便秘|むくみ|筋肉痛|痛み"
    r"|日焼け止め|保湿|肥料|カフェイン|コーヒー|アルコール|酒|(?<!気の)毒"
    # 冷房や暖房、風呂
    r"|冷房|暖房|エアコン|クーラー|ヒーター|空調|除湿|床暖房|床暖|ストーブ|冷蔵|冷凍|扇風機|冷え|入浴|湯船|風呂|温泉"
    # 車、ソフトウェアの仕組み、設定の反映
    r"|ブレーキ|制動|サスペンション|グリップ|(?<![A-Za-z])(?:ABS|JIT)|キャッシュ|インデックス|圧縮|最適化|プリフェッチ|チューニング"
    r"|設定の変更|設定変更"
    # 調味料と味
    r"|わさび|ワサビ|山葵|塩加減|塩気|塩味|塩分|塩|胡椒|こしょう|コショウ|スパイス|辛子|カラシ|出汁|香辛料|調味料|酢"
    r"|生姜|ショウガ|山椒|唐辛子|七味|柚子|ハーブ|ミント|にんにく|ニンニク|レモン|炭酸"
    r"|隠し味|酸味|辛味|辛み|辛さ|甘さ|甘み|甘味|酸っぱさ|苦味|苦み|旨味|うま味|風味|香り(?!づけ|付け)|味付け|味つけ"
    r"|(?<![一-龥々])味")
# 主語の位置でなくても、近くにあれば文字どおりとみなす語（薬の飲み方の言い方）
_KIKU_CONTEXT = (r"飲んで|飲んだ|飲む|飲め|飲み(?:始め|はじめ|続け)|飲ませ|飲み物|飲み方|食後|食前|就寝前|用法|用量"
                 r"|効き目は個人差|個人差")
_KIKU_ABSTRACT = (r"(?:見直し|工夫|改善|施策|対策|習慣|仕組み|しくみ|積み重ね|経験|努力|ルール|変更"
                  r"|取り組み|取組み|修正|調整|改修|方針|戦略|準備|練習|勉強|投資|配慮)")
_KIKU_STOP = "、，," + _KIKU_END
_KIKU_RE = {
    "literal_subject": re.compile(r"(?:" + _KIKU_LITERAL + r")(?:(?:が|は|も|こそ|の|に|って|として)[、，,]?|[、，,])"
                                  r"[^" + _KIKU_STOP + r"を]{0,10}$"),
    "idiom": re.compile(r"(?:融通|小回り|応用|機転|睨み|にらみ|潰し|つぶし|保存|無理|ごまかし|誤魔化し|押し|抑え|見通し|見晴らし"
                        r"|保険|割引|学割|(?<![一-龥々])(?:気|目|鼻|口|顔|腕|足))[がのはもを](?:よく|地味に|じわじわ)?$"),
    "v210": re.compile(r"(?:地味に|よく|じわじわ)$"),
    "negation": re.compile(r"か|きませ|けな|けませ|いて(?:い)?な|いていませ|いてませ|いてこ|いてきませ|いてくれ(?:な|ませ)"
                           r"|き(?:始め|はじめ)(?:な|ませ)|き出さ"),
    "abstract_subject": re.compile(_KIKU_ABSTRACT + r"(?:し?(?:た|ておいた|ていた)(?:の|こと))?(?:が|は|も|こそ|から)[、，,]?"
                                   r"[^" + _KIKU_STOP + r"]{0,12}$"),
    "verb": re.compile(r"く|き(?!目)|け|い[てた]"),
    "effect_owner": re.compile(_KIKU_ABSTRACT + r"の$"),
    "effect": re.compile(r"き目(?:が|は|も)(?:出|表れ|現れ|あらわれ)"),
    "gradual": re.compile(r"いて(?:く[るれ]|き[たてまそ])|き(?:始め|はじめ|出[しすせ])"),
    "adverb": re.compile(r"(?:後から|あとから|後々|あとあと|徐々に|次第に|じわりと|じんわりと?|じわじわと|ジワジワと?|じわっと"
                         r"|後で|あとで|後になって|あとになって)$"),
    "context": re.compile(r"(?:" + _KIKU_LITERAL + r"|" + _KIKU_CONTEXT + r")(?![一-龥々ァ-ヴーA-Za-z])"),
    "timing": re.compile(r"(?:[0-9０-９]+|数|半)\s*(?:分|時間)(?:間)?"
                         r"(?=ほど|くらい|ぐらい|程度|後|以内|経|たつ|たっ|で|もすると|もしないうち)"),
    "sentence": re.compile(r"[^" + _KIKU_END + r"]+[" + _KIKU_END + r"]*|[" + _KIKU_END + r"]+"),
}
_KIKU_CANDIDATE = re.compile(_KIKU_PATTERN)
_KIKU_WINDOW_LINES = 3


def _kiku_metaphor_in_line(text, before_lines=()):
    """行の中に比喩の「効く」として拾う文があれば True。before_lines は同じ文書の前の行（新しい行が後ろ）。"""
    patterns = _KIKU_RE
    earlier = []
    window = None
    for sentence_match in patterns["sentence"].finditer(text):
        sentence = sentence_match.group()
        loose = None
        for match in _KIKU_CANDIDATE.finditer(sentence):
            start = match.start()
            prefix = sentence[max(0, start - 48):start]
            suffix = sentence[start + 1:start + 13]
            if patterns["idiom"].search(prefix) or patterns["literal_subject"].search(prefix):
                continue
            if patterns["v210"].search(prefix):
                return True
            if patterns["negation"].match(suffix):
                continue
            if patterns["verb"].match(suffix) and patterns["abstract_subject"].search(prefix):
                return True
            if patterns["effect"].match(suffix) and patterns["effect_owner"].search(prefix):
                return True
            if not (patterns["gradual"].match(suffix)
                    or (patterns["verb"].match(suffix) and patterns["adverb"].search(prefix))):
                continue
            if loose is None:
                loose = bool(patterns["context"].search(sentence) or patterns["timing"].search(sentence))
            if loose:
                continue
            if window is None:
                nearby = list(before_lines)[-_KIKU_WINDOW_LINES:] + earlier
                window = bool(patterns["context"].search("\n".join(nearby)))
            if window:
                continue
            return True
        earlier.append(sentence)
    return False


# 比喩動詞・AI偏愛動詞パターン
METAPHOR_VERB_PATTERNS = [
    (_KIKU_PATTERN, "比喩動詞「効く」の過剰使用"),
    (r"(データ|仕様|設計|環境|ビルド|システム|秩序)が(静かに)?壊れ", "比喩動詞「壊れる」"),
    (r"静かに(壊れ|落ち|失敗|沈黙)", "英語直訳「静かに壊れる (silently fail)」"),
    (r"黙って(無視|捨て|スキップ|破棄)", "英語直訳「黙って無視される」"),
    (r"側に倒[すしせ]", "判断を方向で表現する「〜側に倒す」"),
    (r"時間[をに]溶か[さしすせそ]", "比喩動詞「時間を溶かす」"),
    (r"(1つずつ|一つずつ)潰[していく]", "比喩動詞「潰す」"),
    (r"(実装|詳細|コード|設計|内部|仕組み|領域|本質)(に|まで|へ)踏み込[んむみま]", "比喩動詞「踏み込む」"),
    (r"動かしながら引き返[すし]", "比喩動詞「引き返す」"),
    (r"代わりに添え[るた]", "比喩動詞「添える」"),
    (r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂", "比喩動詞「収斂する」"),
    (_MOMENT_PATTERN, "英語直訳「〜した瞬間 (the moment ...)」"),
    (r"(前提|基盤)が崩れ[るた]", "抽象比喩「前提が崩れる」"),
    (r"文化が醸成", "非生物主語「文化が醸成される」"),
    (r"プロセスが定着", "非生物主語「プロセスが定着する」"),
    (r"事例が残した", "非生物主語「事例が残した」"),
]

# メタフィラー・定型句
# 文ごとに当てる（^ と $ は文の頭と終わり）。
# 文末の推量・確信・念押し（でしょう、かもしれません、と思います、ね）や、文末の短い補足カッコが付いても拾う。
# 「〜ではないとは思わない」や、読点で文が続く形（「〜ではないかもしれない、という表現」）は文末でないので拾わない。
_OVERSTATEMENT_PATTERN = (r"とも?(?:言|い)(?:い切|いき)?っても(?:過言|言い過ぎ|言いすぎ|いいすぎ)"
                          r"(?:では(?:ありません|ない)|じゃ(?:ありません|ない))(?:です)?"
                          r"(?:でしょう|だろう|かもしれ(?:ません|ない)|と(?:思|おも)(?:います|う)|ね|よ)?"
                          r"(?:[（(][^）)]*[）)])?[。！？!?]?$")
_OVERSTATEMENT_DESC = "文末の付け足し「〜と言っても過言ではありません」"
FILLER_PATTERNS = [
    (r"^(まず|ここで)?(重要|大切|大事)なのは、?", "前置フィラー「重要なのは」"),
    (r"^結論から(言|い)(う|い|え)|^結論から申し上げ", "前置フィラー「結論から言うと」"),
    (r"^正直に言うと、?", "前置フィラー「正直に言うと」"),
    (r"^本音を言うと、?", "前置フィラー「本音を言うと」"),
    (r"^避けたいのは、?", "前置フィラー「避けたいのは」"),
    (r"^ポイントは、", "前置フィラー「ポイントは、」"),
    (r"見落とされがち|面白いのはここ|まさにそこがポイント", "自己ラベル「見落とされがち」など"),
    (r"いかがでした(でしょうか|か)?[？?。]?$", "定型クロージング「いかがでしたでしょうか」"),
    (r"ぜひ(?:参考にして|試して|活用して)(?:みて)?ください[！!。]?", "定型クロージング「ぜひ〜してみてください」"),
    (r"参考に(なれ|な)ば幸い|お役に立て(れ)?ば幸い|ぜひご(活用|参考に)ください|まずは小さく(始め|はじめ)(?:ましょう|てみましょう|てください|てみてください|てみませんか|て(?:みて)?はいかが(?:ですか|でしょうか)|る(?:ことが(?:大切|大事|重要)|のがおすすめ)です)[。！？!?]?$", "定型クロージング「参考になれば幸いです」など"),
    (r"に(?:他|ほか)なりません", "過剰な自己ラベリング「〜に他なりません」"),
    (r"^ご質問ありがとうございます", "チャット応答の名残「ご質問ありがとうございます」"),
    (r"見ていきましょう[。！!]?$|深掘りしていきます", "定型導入「それでは見ていきましょう」など"),
    (r"^(必要なら|ご希望があれば|よろしければ)、?(次に|続けて|この後(?!の))[^。！？!?]*(?:ます|ましょう)(?:か|よ|ね|よね)?(?:（[^。！？!?（）]*）)?[。！？!?]?$", "チャット応答の名残「必要なら次に〜します」"),
    (_OVERSTATEMENT_PATTERN, _OVERSTATEMENT_DESC),
]

# 規則の説明に添える、残してよい場合（指針の例外に合わせる）
FILLER_NOTES = {
    _OVERSTATEMENT_DESC: "事実を淡々と書いてください。数値などの裏付けがあって誇張でない事実を強調する場合や、引用・会話・表現そのものへの言及は残してかまいません。",
    "チャット応答の名残「ご質問ありがとうございます」": "チャットやメールの返信そのものなら残してかまいません。",
    "チャット応答の名残「必要なら次に〜します」": "書き手が読み手に実際に申し出ている案内なら残してかまいません。",
    "定型クロージング「参考になれば幸いです」など": "メールや手紙の結びの挨拶や、書き手が実際に勧めている内容なら残してかまいません。",
    "定型クロージング「いかがでしたでしょうか」": "メールや手紙の結びの挨拶なら残してかまいません。",
    "定型クロージング「ぜひ〜してみてください」": "書き手が実際に勧めている内容なら残してかまいません。",
}

# 見直しのきっかけにとどめる文単位の型（info）。（パターン, 規則, 説明）
INFO_SENTENCE_PATTERNS = [
    (r"^(まとめると|総じて)、", "summary_restatement",
     "言い直しの締め（「まとめると」「総じて」）が検出されました。本文で言い終えた内容を繰り返すだけなら削ってください。新しい情報、条件、結論の絞り込みを担う場合や、長い文書や発表で要約の役割を担う場合は残してください。削るときも、その箇所にしかない数値・条件・例外は落とさないでください。"),
    (r"^本記事では", "meta_intro",
     "「本記事では」で始まる案内が検出されました。続く本文と同じ内容を予告しているだけなら削り、長い文書の目次的な案内なら残してください。"),
    (r"(ポイント|理由|観点|コツ|方法)は(3|三|３)つ(です|あります)|以下の(3|三|３)つの(観点|ポイント)", "count_declaration",
     "数の宣言（「ポイントは3つです」など）が検出されました。宣言した数と続く項目の数が合っていれば、宣言の文を中身とまとめるか削ってください。項目を数に合わせて足したり削ったりしないでください。"),
]

# Necessary literals for these exact patterns, not replacement rules. A changed
# or custom pattern has no hint and keeps the complete regular-expression scan.
_PATTERN_LITERAL_HINTS = {
    _OVERSTATEMENT_PATTERN: ("過言", "言い過ぎ", "言いすぎ", "いいすぎ"),
    _KIKU_PATTERN: ("効",),
    r"(データ|仕様|設計|環境|ビルド|システム|秩序)が(静かに)?壊れ": ("壊れ",),
    r"静かに(壊れ|落ち|失敗|沈黙)": ("静かに",),
    r"黙って(無視|捨て|スキップ|破棄)": ("黙って",),
    r"側に倒[すしせ]": ("側に倒",),
    r"時間[をに]溶か[さしすせそ]": ("溶か",),
    r"(1つずつ|一つずつ)潰[していく]": ("つずつ潰",),
    r"(実装|詳細|コード|設計|内部|仕組み|領域|本質)(に|まで|へ)踏み込[んむみま]": ("踏み込",),
    r"動かしながら引き返[すし]": ("動かしながら引き返",),
    r"代わりに添え[るた]": ("代わりに添え",),
    r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂": ("収斂",),
    _MOMENT_PATTERN: ("した瞬間",),
    r"(前提|基盤)が崩れ[るた]": ("が崩れ",),
    r"文化が醸成": ("文化が醸成",),
    r"プロセスが定着": ("プロセスが定着",),
    r"事例が残した": ("事例が残した",),
    r"^(まず|ここで)?(重要|大切|大事)なのは、?": ("なのは",),
    r"^結論から(言|い)(う|い|え)|^結論から申し上げ": ("結論から",),
    r"^正直に言うと、?": ("正直に言うと",),
    r"^本音を言うと、?": ("本音を言うと",),
    r"^避けたいのは、?": ("避けたいのは",),
    r"^ポイントは、": ("ポイントは、",),
    r"見落とされがち|面白いのはここ|まさにそこがポイント": ("見落とされがち", "面白いのはここ", "まさにそこがポイント"),
    r"いかがでした(でしょうか|か)?[？?。]?$": ("いかがでした",),
    r"ぜひ(?:参考にして|試して|活用して)(?:みて)?ください[！!。]?": ("ぜひ",),
    r"参考に(なれ|な)ば幸い|お役に立て(れ)?ば幸い|ぜひご(活用|参考に)ください|まずは小さく(始め|はじめ)(?:ましょう|てみましょう|てください|てみてください|てみませんか|て(?:みて)?はいかが(?:ですか|でしょうか)|る(?:ことが(?:大切|大事|重要)|のがおすすめ)です)[。！？!?]?$": ("ば幸い", "ぜひご", "まずは小さく"),
    r"に(?:他|ほか)なりません": ("他なりません", "ほかなりません"),
    r"^ご質問ありがとうございます": ("ご質問ありがとうございます",),
    r"見ていきましょう[。！!]?$|深掘りしていきます": ("見ていきましょう", "深掘りしていきます"),
    r"^(必要なら|ご希望があれば|よろしければ)、?(次に|続けて|この後(?!の))[^。！？!?]*(?:ます|ましょう)(?:か|よ|ね|よね)?(?:（[^。！？!?（）]*）)?[。！？!?]?$": ("必要なら", "ご希望があれば", "よろしければ"),
    r"^(まとめると|総じて)、": ("まとめると", "総じて"),
    r"^本記事では": ("本記事では",),
    r"(ポイント|理由|観点|コツ|方法)は(3|三|３)つ(です|あります)|以下の(3|三|３)つの(観点|ポイント)": ("3つ", "三つ", "３つ"),
    r"(?:(?<![ァ-ヴー])|(?<=レビュー)|(?<=リリース)|(?<=チェック)|(?<=デプロイ)|(?<=マージ)|(?<=テスト))(?<!搭乗)(?<!改札)ゲート(?!ウ[ェエ]イ|ボール|キーパー)": ("ゲート",),
    r"(?<!推移)(?<!反射)(?<!対称)(?<!凸)(?<!代数)(?<!代数的)閉包(?!演算)": ("閉包",),
    r"(?<!資産)(?<!住民基本)(?<!会計)(?<!会計の)(?<!行政の)(?<!課税)(?<!土地)(?<!家屋)(?<!備品)(?<!登記)台帳": ("台帳",),
    r"(思考|意思決定|仕事|人生|組織|チーム|学習|経営)の?OS(?![A-Za-z])": ("OS",),
    r"本質を突": ("本質を突",),
    _TRUTH_PATTERN: ("真理",),
    _DEVICE_PATTERN: ("装置",),
    _VERSION_DEMONSTRATIVE_PATTERN: ("版",),
    r"(?<![一-龥ァ-ヴーA-Za-z0-9])版を(上げ|下げ|更新|戻)": ("版を",),
    r"(?<!原点)(?<!への)(?<!先祖)(?<!平均)回帰(が|を)(出|発生|起こ|起き|生じ|防)": ("回帰",),
}
_ALWAYS_SCAN = object()
_DOCUMENT_TABLES_CACHE = []


def _literal_can_cover(literal, other):
    return other != literal and any(
        other[index:].startswith(literal)
        or (index and literal.startswith(other[index:]))
        for index in range(len(other))
    )


def _document_tables():
    tables = (SLOP_WORDS, SLOP_WORD_PATTERNS, METAPHOR_VERB_PATTERNS,
              TRANSLATED_TERM_PATTERNS, FILLER_PATTERNS, INFO_SENTENCE_PATTERNS)
    if any(type(table) not in (list, tuple) for table in tables):
        return None
    if _DOCUMENT_TABLES_CACHE:
        saved, result, lengths, flat = _DOCUMENT_TABLES_CACHE
        # Cached entries are immutable plain strings/tuples. Identity checks
        # cannot invoke a malformed replacement's equality/hash hooks.
        if tuple(map(len, tables)) == lengths and all(map(is_, chain.from_iterable(tables), flat)):
            return result
    words, *families = tables
    if not all(type(word) is str for word in words):
        return None
    if not all(type(row) is tuple and len(row) == width
               and all(type(item) is str for item in row)
               for table, width in zip(families, (2, 2, 2, 2, 3)) for row in table):
        return None
    saved = tuple(tuple(table) for table in tables)
    words, slop, metaphor, translated, filler, info = saved
    literals = []
    alternatives = []

    def keyed(rows, sources):
        keys = []
        out = []
        for row, source in zip(rows, sources):
            required = _PATTERN_LITERAL_HINTS.get(source)
            out.append((*row, required))
            if required is None:
                keys.append(_ALWAYS_SCAN)
            elif len(required) == 1:
                keys.append(required[0])
            else:
                keys.append(required)
                alternatives.append(required)
            literals.extend(required or ())
        return out, keys

    indexed = (
        keyed(slop, [pattern for _, pattern in slop]),
        keyed([(re.compile(pattern), desc) for pattern, desc in metaphor], [pattern for pattern, _ in metaphor]),
        keyed(translated, [pattern for pattern, _ in translated]),
        keyed([(re.compile(pattern), desc) for pattern, desc in filler], [pattern for pattern, _ in filler]),
        keyed([(re.compile(pattern), rule, message) for pattern, rule, message in info], [pattern for pattern, _, _ in info]),
    )
    word_keys = [word if word and len(word) <= 64
                 and not any(char in "*_" or char.isspace() for char in word)
                 else _ALWAYS_SCAN for word in words]
    literals.extend(word for word in word_keys if word is not _ALWAYS_SCAN)
    literals = list(dict.fromkeys(literals))
    if len(literals) > 128:
        return None
    ordered = sorted(literals, key=len, reverse=True)
    finder = re.compile("|".join(map(re.escape, ordered))) if ordered else None
    covered = [(literal, covers) for literal in literals
               for covers in [frozenset(other for other in literals if _literal_can_cover(literal, other))]
               if covers]
    result = finder, covered, alternatives, (list(words), word_keys), indexed, literals
    _DOCUMENT_TABLES_CACHE[:] = [saved, result, tuple(map(len, saved)), tuple(chain.from_iterable(saved))]
    return result


def _narrowed_document_rows(text):
    tables = _document_tables()
    if tables is None:
        return None
    finder, covered, alternatives, (words, word_keys), families, literals = tables
    gate = text.replace("*", "").replace("_", "")
    if finder is None:
        found = frozenset()
    elif len(gate) <= 2048:
        found = frozenset(finder.findall(gate))
    else:
        # Bound repeated-hit work on dense long documents. Direct membership
        # completes exactly the same set when the short scan budget is spent.
        found = set()
        for index, match in enumerate(finder.finditer(gate)):
            if index == 8:
                found = {literal for literal in literals if literal in gate}
                break
            found.add(match.group())
        found = frozenset(found)
    present = set(found)
    for literal, covers in covered:
        if not found.isdisjoint(covers) and literal in gate:
            present.add(literal)
    present.add(_ALWAYS_SCAN)
    for required in alternatives:
        if not present.isdisjoint(required):
            present.add(required)
    contains = present.__contains__
    return ([list(compress(words, map(contains, word_keys)))]
            + [list(compress(rows, map(contains, keys))) for rows, keys in families])


def _may_match_literals(literals, text):
    if literals is None:
        return True
    for literal in literals:
        if literal in text:
            return True
    return False

# 評価の語だけの短い文を3つ以上並べる型（「効く。重い。安い。」）
_FRAGMENT_RUN = re.compile(r"(?:^|(?<=[。！？]))(?:[^。！？、\s「」『』]{1,4}[。！]){3,}")
# 否定を重ねてから言い切る型（「車でも、家でもない。有頂天だ。」「これは努力じゃない、仕組みです。」）
# 二度否定してから言い切る文が続く形だけを見る（「何でもない」「とんでもない」、接続詞の「それでも、」は除く）。
_NOT_IDIOM = r"(?<!何)(?<!なん)(?<!まんざら)(?<!とん)"
_NEGATION_CONCLUSION_END = r"(?:[うくぐすつぬぶむるいだた]|だけ)(?:よね|よ|ね)?"
_NEGATION_NEGATIVE_END = (
    r"(?:[な無]い|[な無]かった|ません(?:でした)?)"
    r"(?:(?:の|ん)(?:だ|です|だった|でした|である|であった)|です|でした|でしょう|だろう|であろう)?(?:よね|よ|ね)?"
)
_NEGATION_EXTRA = re.compile(
    r"(?:[^。、]{1,15}(?:では|じゃ)ない。[^。]{0,15}|[^。、]{1,15}(?<!それ)(?<!今)(?<!いつ)(?<!誰)(?<!何)でも、[^。、]{1,15})"
    + _NOT_IDIOM + r"でもない。"
    + r"(?![^。！？!?]{0,40}" + _NEGATION_NEGATIVE_END + _END_DECORATION_RUN + r"[。！!])"
    + r"[^。！？!?]{1,40}" + _NEGATION_CONCLUSION_END + _END_DECORATION_RUN + r"[。！!]")
# 「これは努力じゃない、仕組みです。」（文ごとに見る）
_NEGATION_JANAI = re.compile(
    r"^(?:(?:でも|しかし|つまり|ただ|ただし|けれども?|けど|だが|それでも|だから)、)?"
    r"(?![い良]いじゃない、|すごいじゃない、|凄いじゃない、)"
    r"[^。、]{1,15}じゃない、[^。]{1,30}(?:です|だ)(?:よ|ね|よね)?[。！!]?$"
)
# 文頭の「もちろん、」のあとに数語だけが続いて終わる短い文（「もちろん、失敗もする。」）
_SHORT_MOCHIRON = re.compile(r"^(もちろん|勿論)、[^。！？!?、「」『』]{1,10}[。！!]$")
# 問いや依頼への答えの定型（「もちろん、大丈夫です。」）は先回りの認めではない
_MOCHIRON_ANSWER = re.compile(r"^(もちろん|勿論)、(大丈夫|構いません|かまいません|いいですよ|いいよ|できます|可能です|です|だ)")
# 文頭の「〜(連体形)のは、」のあとに名詞を並べ、述語を書かずに終える文（「今回の改修で増えたのは、画面、帳票、通知。」）。
# 項目は格助詞（を・が・は・に・で・へ・から・まで・より）を含まず、名詞らしい字で終わる。読点（、，・）だけで並べるなら
# 3つ以上、「と・や・および」を交えるなら2つ以上。「〜など。」「〜の3つ。」「〜の3点。」で終わる形も当てる。
# 述語まで書いた文（です、だ、でした、に限る）、ダッシュで終わる文、限定の「〜のみ。」「〜だけ。」「〜ばかり。」は、
# 最後の項目が名詞の字で終わらないので当たらない。
_CLEFT_LIST_HEAD = r"^(?P<head>[^。！？!?]{0,60}?(?:[るたいうくすつぬむぶぐ]|な|[んい]だ))のは、"
_CLEFT_LIST_NOUN_END = r"(?:[一-龥々〆ヵヶァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ%％さ]|(?<!の)み)"
# 読点だけで区切る項目（項目の中の「と・や」はそのまま項目の字として読む）。動詞から作った名詞（言い回し、流れ、
# 見直し、書き出し）で終わる項目も認める。
_CLEFT_LIST_COMMA_ITEM = (r"(?:(?!から|より)[^、，,・。！？!?「」『』（）()\[\]\sをがはにでへ]){0,14}"
                          r"(?:" + _CLEFT_LIST_NOUN_END + r"|もの|こと|[しきれえげぎちせ]|(?<!ばか)り)")
# 「と・や・および」でも区切る項目（区切りの語を項目に含めず、区切り方を1つに決める）
_CLEFT_LIST_MIXED_ITEM = (r"(?:(?!から|より|および)[^、，,・。！？!?「」『』（）()\[\]\sをがはにでへとや]){0,14}"
                          r"(?:" + _CLEFT_LIST_NOUN_END + r"|もの)")
_CLEFT_LIST_TAIL = r"(?:など|の[0-9０-９一二三四五六七八九十]+[つ点])?[。！!]?$"
_CLEFT_LIST_COMMA = re.compile(_CLEFT_LIST_HEAD + _CLEFT_LIST_COMMA_ITEM
                               + r"(?:[、，・]" + _CLEFT_LIST_COMMA_ITEM + r"){2,}" + _CLEFT_LIST_TAIL)
_CLEFT_LIST_MIXED = re.compile(_CLEFT_LIST_HEAD + r"(?P<items>" + _CLEFT_LIST_MIXED_ITEM
                               + r"(?:(?:[、，・]|と|や|および)" + _CLEFT_LIST_MIXED_ITEM + r")+)" + _CLEFT_LIST_TAIL)
_CLEFT_LIST_JOINER = re.compile(r"[とや]|および")
_CLEFT_LIST_COMMA_MARK = re.compile(r"[、，・]")
# コード、リンク、脚注は空白に伏せてあるので、2字以上の空白の並びを名詞の仮の字に置き換え、ほかの空白は除いてから照合する
_CLEFT_LIST_MASKED_RUN = re.compile(r"\s{2,}")
_CLEFT_LIST_SPACE = re.compile(r"\s")
# 「のは」の前の動詞の語幹の漢字の並び（「変動したのは」なら「変動」）
_CLEFT_LIST_STEM = re.compile(r"[一-龥々〆ヵヶ]+(?=[ぁ-ん]*$)")
# 直前の文を探すときの文の終わりの字
_CLEFT_LIST_STOPS = "。！？!?"


def _cleft_list_head(sentence):
    """「〜のは、A、B、C。」の形なら「のは」の前までを返す。当たらなければ None。"""
    if "のは、" not in sentence:
        return None
    sentence = _CLEFT_LIST_SPACE.sub("", _CLEFT_LIST_MASKED_RUN.sub("Ｘ", sentence))
    comma = _CLEFT_LIST_COMMA.match(sentence)
    if comma:
        return comma.group("head")
    mixed = _CLEFT_LIST_MIXED.match(sentence)
    if not mixed:
        return None
    items = mixed.group("items")
    joiners = len(_CLEFT_LIST_JOINER.findall(items))
    # 読点だけの2項目（「目指したのは、速さ、軽さ。」）は当てない
    if not joiners:
        return None
    # 読点がなく「と・や」で1回つなぎ、最後の項目に「の」がある形（「父と母の笑顔」）は、1つの名詞句として当てない
    if (joiners == 1 and not _CLEFT_LIST_COMMA_MARK.search(items)
            and "の" in items[_CLEFT_LIST_JOINER.search(items).end():]):
        return None
    return mixed.group("head")


def _cleft_list_premise(head, previous):
    """直前の文が問いか、「のは」の前の動詞の語幹の漢字を含めば、前提を書いてあるとみる。"""
    end = _question_content_end(previous)
    if end and (previous[end - 1] in "？?" or previous.endswith(("か。", "か"), 0, end)):
        return True
    stem = _CLEFT_LIST_STEM.search(head)
    return bool(stem) and any(char in previous for char in stem.group())


def _cleft_list_join(analysis, rows, position, text):
    """rows[:position] の行を後ろから text の前につなぐ（改行で折り返した文を1つの文として読む）。
    最後の文が分かるだけ（句点などが2つになるまで）つなぐ。"""
    marks = sum(map(text.count, _CLEFT_LIST_STOPS))
    while position and marks < 2:
        position -= 1
        piece = _prose_visible_text(analysis, rows[position]["line"]).replace("__", "").replace("*", "").strip()
        marks += sum(map(piece.count, _CLEFT_LIST_STOPS))
        text = piece + text
    return text


def _cleft_list_previous(analysis, line_no, before):
    """「〜のは、」の文の直前の文。同じ段落の前の文、なければ前の段落の最後の文、なければ直前の見出し。

    before はその行で「〜のは、」の文より前にある字。表、コード、引用などを挟んだときは前の文はないとみる。"""
    blocks = analysis["blocks"]
    places = analysis.get("_cleft_list_places")
    if places is None:
        places = analysis["_cleft_list_places"] = {
            row["line"]: (number, position) for number, block in enumerate(blocks)
            if block["kind"] in ("paragraph", "list") for position, row in enumerate(block["lines"])}
    number, position = places[line_no]
    text = _cleft_list_join(analysis, blocks[number]["lines"], position, before)
    end = max(map(text.rfind, _CLEFT_LIST_STOPS))
    if end >= 0:
        return _last_context_sentence(text[:end + 1])
    if not number or blocks[number - 1]["kind"] not in ("paragraph", "list", "heading"):
        return ""
    rows = blocks[number - 1]["lines"]
    return _last_context_sentence(_cleft_list_join(analysis, rows, len(rows), ""))


def _has_cleft_list_ending(analysis, line_no, contexts, line_sentences, filler_patterns):
    """行の文のどれかが、前提を書かずに「〜のは、A、B、C。」で終えていれば True。

    contexts は _rule9_context の行の文（引用を伏せた文と、同じブロックの次の文）。引用を伏せた文と伏せていない文の
    数が同じ行では、前の文を伏せていない文で見る（「」の中の語も前提に数える）。"""
    for index, (sentence, following) in enumerate(contexts):
        # 句点で終わらない文は、改行で折り返した文の途中でありうるので、ブロックの最後の文のときだけ当てる
        if following and not sentence.endswith(("。", "！", "!")):
            continue
        head = _cleft_list_head(sentence)
        # 文末の後ろの飾り（「画面、帳票、通知 🚀」）を除いて読む
        core = _strip_end_decoration(sentence, _end_closers_for(analysis, line_no))
        if head is None and core is not sentence:
            head = _cleft_list_head(core)
        # 頭が meta_filler の型の文（「重要なのは、」）は、そちらだけを出す
        if head is None or any(_may_match_literals(required, sentence) and (pattern.search(sentence) or pattern.search(core))
                               for pattern, _, required in filler_patterns):
            continue
        before = line_sentences if len(line_sentences) == len(contexts) else [item[0] for item in contexts]
        if not _cleft_list_premise(head, _cleft_list_previous(analysis, line_no, "".join(before[:index]))):
            return True
    return False


# 否定のあとに「でもある」と続ける文（「AではなくBでもある」）は、元の言い方のまま残す
_NEGATION_ALSO = re.compile(r"ではなく、?[^。]{1,40}?(?<!どこに)(?<!誰に)(?<!だれに)(?<!何)(?<!なん)(?<!いつ)でも(ある|あります|あった|ありました)")
# 「- **特徴**: 説明」のように、太字の見出し語とコロンで始まる箇条書き
# 「- **特徴：** 説明」（コロンが太字の内側）や番号付きリストも同じ型として数える。
_BOLD_LABEL_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\*\*[^*]+?(?:\*\*\s*[:：]|[:：]\s*\*\*)")
_SUMMARY_HEADING = re.compile(r"^#{1,6}\s*(まとめ|おわりに)\s*$")

# ネガティブパラレリズム（AではなくB）
NEGATIVE_PARALLELISM_PATTERN = re.compile(r"([^。、]+)ではなく、?([^。、]+)")
_NEGATIVE_PARALLELISM_DEFAULT = NEGATIVE_PARALLELISM_PATTERN


def _has_negative_parallelism(text: str) -> bool:
    """Exact existence test for the default pattern; preserve custom searches."""
    pattern = NEGATIVE_PARALLELISM_PATTERN
    default = _NEGATIVE_PARALLELISM_DEFAULT
    if (type(pattern) is not type(default) or pattern.pattern != default.pattern
            or pattern.flags != default.flags):
        return "ではなく" in text and bool(pattern.search(text))

    # Each successful regex match has a literal with at least one valid char
    # on each side. The right side may consume one optional Japanese comma.
    literal = "ではなく"
    offset = 0
    while True:
        position = text.find(literal, offset)
        if position == -1:
            return False
        end = position + len(literal)
        if position > 0 and text[position - 1] not in "。、" and end < len(text):
            if text[end] not in "。、":
                return True
            if text[end] == "、" and end + 1 < len(text) and text[end + 1] not in "。、":
                return True
        # This fixed literal has no proper self-overlap.
        offset = position + len(literal)


def get_frontmatter_line_count(lines: List[str]) -> int:
    """YAMLフロントマター（先頭の --- から 次の --- まで）の行数を返す"""
    if not lines or lines[0].strip() != "---":
        return 0
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return idx + 1
    return 0


_SENTENCE_END_POSITION = re.compile(r"(?<=[。！？])")
_LIST_MARKER_LINE = re.compile(r"^\s*([-*+]|\d+\.)\s+")
_LIST_LINK_LINE = re.compile(r"[-*+]\s+\[.*?\]\(https?://")
_LINE_SENTENCE_BREAK = re.compile(r"(?<=[。！？!?])")


def _plain_sentence_records(analysis):
    """Visible prose plus original source slices from the same scan boundary."""
    records = []
    for block_id, block in enumerate(analysis["blocks"]):
        if block["kind"] != "paragraph":
            continue
        section = 0
        for row in block["lines"]:
            visible = _prose_visible_text(analysis, row["line"])
            # Image-only rows are visual breaks in the existing style policy,
            # including a link whose entire label is one image. A multiline
            # code atom is not such a break; retain its paragraph group.
            if ((_image_only_row is not _IMAGE_ONLY_ROW_DEFAULT
                 or not visible.strip() or row["raw"].lstrip().startswith("[!["))
                    and _image_only_row(analysis, row, visible)):
                section += 1
                continue
            if not visible.strip():
                continue
            start = 0
            ends = [match.start() for match in _SENTENCE_END_POSITION.finditer(visible)]
            if not ends or ends[-1] != len(visible):
                ends.append(len(visible))
            for end in ends:
                clean = visible[start:end].strip()
                if clean and len(clean) > 3:
                    records.append((row["line"], clean, row["raw"][start:end].strip(), (block_id, section)))
                start = end
    return records


def extract_plain_sentences(text: str) -> List[Tuple[int, str]]:
    """コードブロックや引用、箇条書きを除き、元の行番号つきで地の文を抽出する。"""
    records = _plain_sentence_records(analyze_markdown(text))
    return [(line, visible) for line, visible, _, _ in records]


def check_sentence_end_repetitions(sentences: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
    """3文以上連続する同一語尾の検知。抽出時に除いた行をまたいでは数えない。"""
    return _sentence_end_findings(sentences)


def _sentence_end_type(s):
    """sentence_end_repetition が数える語尾の種類。数えない文は「その他」。"""
    # Scan ordinary short suffixes directly. Bound Python-level work for
    # long removable suffixes; the guarded regex starts only at run edges.
    end = len(s)
    floor = max(0, end - 64)
    while end > floor and (s[end - 1] in "。！？" or s[end - 1].isspace()):
        end -= 1
    if end == floor and end and (s[end - 1] in "。！？" or s[end - 1].isspace()):
        clean = re.sub(r"(?<![。！？\s])[。！？\s]+$", "", s)
    else:
        clean = s[:end]
    # 文末の後ろの絵文字や空白（「〜です 🚀」）は除いて語尾を見る。閉じかっこと閉じかぎは除かない（会話や補足の終わり）。
    core = _strip_end_decoration(clean)
    if core is not clean:
        end = len(core)
        while end and (core[end - 1] in "。！？" or core[end - 1].isspace()):
            end -= 1
        clean = core[:end]
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
    elif clean.endswith("でしょう"):
        end_type = "でしょう"
    elif clean.endswith("ですね"):
        end_type = "ですね"
    return end_type


def _split_decoration_breaks(sentences, source_sentences, paragraph_groups):
    """句点の代わりに絵文字を置いて続けた文（「これはAです🚀これはBです🚀」）を、句点で分けたときと同じように分ける。

    分けるのは、前後とも4字以上あるときだけ（句点で分けた文と同じく、3字以下の文は数えない）。
    語尾が数えない種類の文も分ける。分けないと、次の文の語尾を引き継いで続きを誤って数えるため。"""
    if not any(_END_DECORATION_CHAR.search(sentence) for _, sentence in sentences):
        return sentences, source_sentences, paragraph_groups
    split_sentences, split_sources, split_groups = [], [], []
    for (line_no, sentence), (_, source), group in zip(sentences, source_sentences, paragraph_groups):
        pieces = _decoration_breaks(sentence)
        cuts = []
        if pieces:
            # 分けた所の後ろは空白で始まらない（空白は前の絵文字の並びに含める）ので、残りの字数は引き算で分かる
            text_end = len(sentence.rstrip())
            position = 0
            start = 0
            for piece in pieces[:-1]:
                position += len(piece)
                # 4字以上あるかは前の文の終わりの方だけで分かる（分けない所が続く長い行でも手間を抑える）
                if len(sentence[max(start, position - 8):position].strip()) > 3 and text_end - position > 3:
                    cuts.append(position)
                    start = position
        if not cuts:
            split_sentences.append((line_no, sentence))
            split_sources.append((line_no, source))
            split_groups.append(group)
            continue
        same_width = len(source) == len(sentence)
        for start, end in zip([0] + cuts, cuts + [len(sentence)]):
            split_sentences.append((line_no, sentence[start:end].strip()))
            split_sources.append((line_no, source[start:end].strip() if same_width else source))
            split_groups.append(group)
    return split_sentences, split_sources, split_groups


def _sentence_end_findings(sentences, source_sentences=None, paragraph_groups=None):
    """Keep visible ending decisions and original finding snippets separate."""
    findings = []
    end_types = [(line_no, s, _sentence_end_type(s)) for line_no, s in sentences]

    # 3連続チェック
    count = 1
    for i in range(1, len(end_types)):
        prev_line, prev_s, prev_type = end_types[i - 1]
        curr_line, curr_s, curr_type = end_types[i]

        # 同じ行や隣接行は同じ段落として数え、空行や除外したブロックを挟めば数え直す。
        same_paragraph = (paragraph_groups[i] == paragraph_groups[i - 1]
                          if paragraph_groups is not None else curr_line <= prev_line + 1)
        if same_paragraph and curr_type != "その他" and curr_type == prev_type:
            count += 1
            if count == 3:
                findings.append({
                    "rule": "sentence_end_repetition",
                    "line": curr_line,
                    "severity": "warn",
                    "message": f"同一文末「{curr_type}」が3回以上連続しています。読みにくくなっていないか確認し、自然な説明や文体は保ってください。",
                    "snippet": source_sentences[i][1] if source_sentences is not None else curr_s
                })
        else:
            count = 1

    return findings


_METRIC_OPAQUE_KINDS = frozenset((
    "code", "frontmatter", "html_block", "reference_definition", "inline_code",
    "html_token", "autolink", "link_destination", "image", "bare_url"
))
_PROSE_SCAN_KINDS = _METRIC_OPAQUE_KINDS | frozenset(("container_prefix",))


def _prose_visible_text(analysis, line_no):
    """Reuse the same immutable raw-source view for sentences and lexical scan."""
    cache = analysis.setdefault("_prose_line_cache", {})
    if line_no not in cache:
        cache[line_no] = line_visible_text(analysis, line_no, _PROSE_SCAN_KINDS)
    return cache[line_no]


def _image_only_row(analysis, row, visible):
    """A real image with no visible prose; never skip prose after an image."""
    if not visible.strip():
        return range_overlaps_protected(analysis, row["start"], row["start"] + len(row["raw"]),
                                        frozenset(("image",)))
    raw = row["raw"]
    if not raw.strip().startswith("[!["):
        return False
    # Validate the complete outer link by the protected source atoms, not by
    # treating every literal [] near an image as disposable markup. Cache the
    # start indexes once; many badge rows must not rescan every protected atom.
    if "_image_link_start_indexes" not in analysis:
        images, destinations = {}, {}
        for left, right, kind in analysis["protected_spans"]:
            if kind == "image":
                images[left] = right
            elif kind == "link_destination":
                destinations[left] = right
        analysis["_image_link_start_indexes"] = (images, destinations)
    images, destinations = analysis["_image_link_start_indexes"]
    start = row["start"] + len(raw) - len(raw.lstrip())
    end = row["start"] + len(raw.rstrip())
    image_end = images.get(start + 1)
    return (image_end is not None
            and analysis["text"][image_end:image_end + 2] == "]("
            and destinations.get(image_end + 1) == end)


_IMAGE_ONLY_ROW_DEFAULT = _image_only_row

# HTML のブロックの行で、<details> の開きと閉じを探すときの印。コメントと、中身をタグとして読まない要素
# （script、style、textarea）の中は飛ばす。
_DETAILS_HINT = re.compile(r"<details", re.I)
_DETAILS_TOKEN = re.compile(r"<!--|<(/?)(details|script|style|textarea)(?=[\s/>]|$)", re.I)


def _details_inner_lines(analysis):
    """組になった <details> と </details> の間にある行の番号の集合。組が1つもなければ None。

    開きと閉じは、HTML のブロックの行（引用の外）でだけ見る。段落の中、インラインのコード、コードの囲みとインデントした
    コード、HTML のコメントの中の <details> は見ない。閉じは、まだ閉じていないいちばん新しい開きと組にする（入れ子）。
    組にならない開きと閉じは見ない（その範囲は今までどおり数える）。"""
    if not _DETAILS_HINT.search(analysis["text"]):
        return None
    opened, pairs = [], []
    in_comment, raw_close = False, None
    for row in analysis["lines"]:
        if row["kind"] != "html_block" or row["quote_depth"]:
            # HTML のブロックが終わったら、コメントと script などの中にいる状態も終わる
            in_comment, raw_close = False, None
            continue
        text, position = row["raw"], 0
        while position < len(text):
            if in_comment:
                end = text.find("-->", position)
                if end < 0:
                    break
                in_comment, position = False, end + 3
                continue
            if raw_close is not None:
                found = raw_close.search(text, position)
                if found is None:
                    break
                raw_close, position = None, found.end()
                continue
            token = _DETAILS_TOKEN.search(text, position)
            if token is None:
                break
            position = token.end()
            if token.group(0) == "<!--":
                in_comment = True
            elif token.group(2).lower() != "details":
                if not token.group(1):
                    raw_close = re.compile(r"</" + token.group(2) + r"(?=[\s>]|$)", re.I)
            elif not token.group(1):
                opened.append(row["line"])
            elif opened:
                pairs.append((opened.pop(), row["line"]))
    if not pairs:
        return None
    inside = set()
    for first, last in pairs:
        inside.update(range(first + 1, last))
    return inside


def _metrics_from_analysis(analysis):
    """Use the same protected data boundary as lexical and sentence checks."""
    return _metrics_and_list_gate(analysis)[0]


def _metrics_and_list_gate(analysis):
    """metrics、箇条書きの判定用字数（<details> 内の箇条書きを除く）、点数用の地の文字数を返す。"""
    plain_rows = []
    prose_chars = 0
    for row in analysis["lines"]:
        stripped = row["raw"].strip()
        if row["kind"] in ("code", "frontmatter", "html_block", "reference_definition"):
            continue
        # Preserve legacy structural counting, including empty bullet markers.
        # Do not redefine the denominator merely because a container is masked
        # for lexical inspection. Actual opaque code/URI data stays excluded.
        if row["quote_depth"] or row["kind"] == "table":
            continue
        visible = line_visible_text(analysis, row["line"], _METRIC_OPAQUE_KINDS)
        if ((_image_only_row is not _IMAGE_ONLY_ROW_DEFAULT
             or not visible.strip() or row["raw"].lstrip().startswith("[!["))
                and _image_only_row(analysis, row, visible)):
            continue
        if stripped:
            plain_rows.append((row, visible))
            if row["kind"] not in ("heading", "heading_underline", "thematic_break"):
                prose_chars += len("".join(visible.split()))
    total_lines = len(plain_rows)
    # <details> の中の箇条書きは、箇条書きの比率に数えず、details_list_lines に別に数える（畳んだ根拠の一覧などで
    # excess_list を出さないため）。total_lines と、字数と太字は今までどおり中も数える。比率の分母は、全体の非空行から
    # 中の箇条書きの行を引いた数（中に箇条書きを多く畳んでも、外の箇条書きの比率が薄まらない。反証で見つけた例）。
    # 外の箇条書きの行 L、中の箇条書きの行 M、全体の非空行 T で L/(T-M) <= (L+M)/T なので、中も数えていた前の比率より
    # 大きくならず、excess_list が新しく出ることはない
    details_inside = _details_inner_lines(analysis)
    list_lines = 0
    details_list_lines = 0
    details_list_chars = 0
    for row, visible in plain_rows:
        if _LIST_MARKER_LINE.match(row["raw"]):
            if not _LIST_LINK_LINE.search(row["raw"]):
                if details_inside and row["line"] in details_inside:
                    details_list_lines += 1
                    details_list_chars += len("".join(visible.split()))
                else:
                    list_lines += 1
    plain_content = "\n".join(visible for _, visible in plain_rows)
    bold_count = len(re.findall(r"\*\*[^*]+\*\*", plain_content))
    char_count = len("".join(plain_content.split()))
    bold_per_1000 = bold_count / char_count * 1000 if char_count > 0 else 0
    ratio_base = total_lines - details_list_lines
    list_ratio = list_lines / ratio_base if ratio_base > 0 else 0
    metrics = {"char_count": char_count, "total_lines": total_lines, "list_lines": list_lines,
               "list_ratio": round(list_ratio, 3), "bold_count": bold_count,
               "bold_per_1000": round(bold_per_1000, 2)}
    if details_inside is not None:
        # 組になった <details> がある文書にだけ足す（ない文書の metrics は今までと同じキー）
        metrics["details_list_lines"] = details_list_lines
    # 箇条書きの比率の判定の門（地の文が300字を超える）も、比率と同じく <details> の中の箇条書きを数えない。外が短く、根拠の
    # 箇条書きを畳んだ文書で、畳んだ字数で門を通って excess_list が出ないため（反証で見つけた例）。<details> がなければ char_count と同じ
    return metrics, char_count - details_list_chars, prose_chars


def analyze_markdown_metrics(text: str) -> Dict[str, Any]:
    """太字頻度、箇条書き比率などの構造メトリクスを算出（引用文やコードブロックは除外）"""
    return _metrics_from_analysis(analyze_markdown(text))


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


def _extra_negation_line_numbers(analysis):
    """Find the construction across soft line breaks, never across blocks."""
    hit_lines = set()

    def scan(parts):
        if not parts:
            return
        joined = "".join(visible for _, visible in parts)
        if "でもない。" not in joined:
            return
        offsets = []
        total = 0
        for _, visible in parts:
            offsets.append(total)
            total += len(visible)
        for match in _NEGATION_EXTRA.finditer(joined):
            index = bisect_right(offsets, match.start()) - 1
            hit_lines.add(parts[index][0])

    for block in analysis["blocks"]:
        if block["kind"] != "paragraph":
            continue
        parts = []
        for row in block["lines"]:
            visible = _prose_visible_text(analysis, row["line"])
            if (row["quote_depth"]
                    or ((_image_only_row is not _IMAGE_ONLY_ROW_DEFAULT
                         or not visible.strip() or row["raw"].lstrip().startswith("[!["))
                        and _image_only_row(analysis, row, visible))):
                scan(parts)
                parts = []
                continue
            visible = visible.replace("__", "").replace("*", "").strip()
            if visible:
                parts.append((row["line"], visible))
        scan(parts)
    return hit_lines


# AIへの指示残りは作者の意図を断定できないため info にとどめる。
# 書く行為の予告と、書き方・除外の条件が同居する型だけを見る。
_WRITING_ACTION = re.compile(
    r"(?:書(?:きます|く|いてみます|いていきます)|(?:説明|紹介|解説)し(?:ます|ていきます)|"
    r"まとめ(?:ます|る|ていきます)|お伝えし(?:ます|ていきます)|述べ(?:ます|る)|"
    r"振り返(?:ります|る|っていきます)|お話し?し(?:ます|ていきます)|お届けします|話していきます)[。！？!?]?$"
)
# 書き方の条件は、敬体の予告か、記事の範囲を示す書き出しの文だけで見る（小説の地の文や規程の文を除く）。
_RESIDUE_OPENER = r"^(?:この記事|本記事|本稿|このブログ|ここ|以下|今回)(?:では|は)"
_RESIDUE_OPENER_RE = re.compile(_RESIDUE_OPENER)
_WRITING_STYLE = re.compile(
    r"(?:トーン|文体|口調)で|(?:専門用語|箇条書き)を\s*(?:できるだけ|なるべく)?"
    r"(?:使わず|用いず|避け)|(?:AI|ＡＩ)(?:っぽさ|らしさ)(?:が出ないよう|を(?:抑え|なく|避け))|"
    r"飾らない言葉で|語り口で|トーンを意識|(?<![0-9０-９])[0-9０-９]+文?字(?:程度|以内|前後)?で"
)
_WRITING_LIMIT = re.compile(r"に(?:絞って|限定して|焦点を(?:当てて|絞って))|触れず|扱わず|立ち入らず|[はを]抜きにして")
_SCOPE_EXCLUSION = re.compile(
    _RESIDUE_OPENER + r"[^。！？!?]*"
    r"(?:扱いません|扱わない|触れません|触れない|省きます|省く|割愛します|省略します)[。！？!?]?$"
)
_READER_SCOPE = re.compile(r"^(?:この|本)?(?:マニュアル|手順書|ガイド|論文|研究)(?:では|は)")
_SCOPE_REFERENCE = re.compile(
    r"参照|ご覧|別途|付録|後述|後ほど|別の?[^。！？!?]{0,8}(?:記事|ページ|章|節|報告書?|資料|文書|ガイド)|"
    r"(?:後|次|前)の(?:章|節)|第[0-9０-９一二三四五六七八九十]+章"
)


def _rule9_context(analysis):
    """New rules alone use unquoted prose and the immediately following sentence.

    Mask balanced quotes before splitting sentences, including paragraph breaks.
    Retain each original line's width so the existing line numbers stay usable.
    References cannot exempt a scope declaration across a paragraph boundary.
    """
    rows = analysis["lines"]
    parts = [(_prose_visible_text(analysis, row["line"]).replace("__", "").replace("*", "")
              if row["kind"] in ("paragraph", "list") and not row["quote_depth"] else "")
             for row in rows]
    masked = _mask_quoted_segments_sparse("\n".join(parts))
    # _mask_quoted_segments also masks newlines inside quotations. Slice by
    # the original widths instead of splitting its output on newlines.
    offset = 0
    visible_lines = {}
    for row, part in zip(rows, parts):
        visible_lines[row["line"]] = masked[offset:offset + len(part)].strip()
        offset += len(part) + 1
    contexts = {}
    for block in analysis["blocks"]:
        if block["kind"] not in ("paragraph", "list"):
            continue
        records = []
        for row in block["lines"]:
            contexts[row["line"]] = []
            for sentence in _LINE_SENTENCE_BREAK.split(visible_lines[row["line"]]):
                if sentence.strip():
                    records.append((row["line"], sentence.strip()))
        for index, (line, sentence) in enumerate(records):
            following = records[index + 1][1] if index + 1 < len(records) else ""
            contexts[line].append((sentence, following))
    return contexts


def _has_instruction_residue(sentence, following):
    writing = _WRITING_ACTION.search(sentence)
    if (writing and ("ます" in writing.group() or _RESIDUE_OPENER_RE.search(sentence))
            and _WRITING_STYLE.search(sentence)):
        return True
    if not (_SCOPE_EXCLUSION.search(sentence) or (writing and _WRITING_LIMIT.search(sentence))):
        return False
    # A reader-facing scope and its adjacent reference are useful information.
    return not (_READER_SCOPE.search(sentence)
                or _SCOPE_REFERENCE.search(sentence) or _SCOPE_REFERENCE.search(following))


def _has_instruction_residue_core(sentence, following, closers=_END_CLOSERS):
    """文末の後ろの飾り（「〜書いていきます 🚀」）を除いた文で、もう一度確かめる。飾りがなければ確かめない。

    句点の代わりに絵文字を置いて続けた文（「〜扱いません🙏 詳しくは〜」）は、分けた文ごとに次の文と合わせて確かめる。"""
    core = _strip_end_decoration(sentence, closers)
    if core is not sentence and _has_instruction_residue(core, following):
        return True
    pieces = _decoration_breaks(sentence)
    if not pieces:
        return False
    return any(_has_instruction_residue(_strip_end_decoration(piece, closers),
                                        pieces[index + 1] if index + 1 < len(pieces) else following)
               for index, piece in enumerate(pieces))


# 短い主語・主題の読点。判定は a〜t の順で、当てはまる除外条件があれば残す。
_PAUSE_KANJI = r"一-龥々〆ヵヶ"
_PAUSE_WORD = re.compile(r"[" + _PAUSE_KANJI + r"ぁ-んァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ]")
_PAUSE_OPEN = "「『（(“【［["
_PAUSE_CLOSE = "」』）)”】］]"
_PAUSE_BOUNDARY = "、，,。！？!?：:"
_PAUSE_LEAD_SYMBOLS = " \t　・※•●○◆◇■□▶▷→＊*-"
_PAUSE_CHECKBOX = re.compile(r"^\[[ xX]\]\s*")

# 助詞のかたまり（長いものから）。
_PAUSE_COMPOUND = sorted(set([
    "においては", "にとっては", "については", "に対しては", "によっては", "としては", "としても",
    "についても", "においても", "にとっても", "に対しても",
    "からは", "までは", "よりは", "へは", "とは", "では", "には", "にも", "でも", "とも", "からも",
    "までも", "へも", "ても",
]), key=len, reverse=True)
# 拾わない助詞のかたまり（接続・逆接・譲歩）
_PAUSE_SKIP_CHUNKS = {"でも", "ても", "とも", "としても", "によっては"}

# 文頭の接続・前置き・手紙の定型。句全体がこれに当たれば拾わない。
_PAUSE_CONNECTIVE = {
    "それでは", "これでは", "では", "しかも", "けれども", "それでも", "それにしても", "とはいえ",
    "ただ", "もっとも", "それとも", "そもそも", "つきましては", "少なくとも", "そのためには",
    "今でも", "なかでも", "中でも", "それには", "まずは", "最後には", "さらには", "ひいては", "ついては",
    "このたびは", "この度は", "平素は", "日頃は", "日ごろは", "先日は", "昨日は", "本日は", "今回も",
}
_PAUSE_CONNECTIVE_END = re.compile(r"的には$|的にも$")
# ほかの規則（meta_intro、meta_filler）がすでに拾う文頭の句。1つの読点に2つの候補を出さない。
_PAUSE_COVERED = re.compile(r"^(?:本記事では|ポイントは|(?:まず|ここで)?(?:重要|大切|大事)なのは|避けたいのは)$")

# 「が」の前が述語の終わり（逆接・前置きの「が、」）
_PAUSE_GA_CONJ_END = re.compile(
    r"(?:です|ます|でした|ました|ません|ませんでした|だ|だった|である|であった|た|る|い|ない|なかった|"
    r"う|く|ぐ|す|つ|ぬ|ぶ|む|よう|たい|らしい|ん|ある|いる|した|する|れる|せる|ている|ていた|ておく|けれど)$")
_PAUSE_GA_NOUN_HIRA = re.compile(r"(?:さん|さま|様|くん|ちゃん|こと|もの|とき|ところ|ほう|ため|の|さ|たち|ら|など|だけ|まで|ばかり|"
                          r"くらい|ぐらい|ほど|こそ|もと|うち|あと|まえ|わけ|はず|よう|みんな|それ|これ|あれ|どれ|ここ|そこ|どこ|誰|僕|私)$")
_PAUSE_NOUNISH_END = re.compile(r"[" + _PAUSE_KANJI + r"ァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ」』）)\]>%％]$")

_PAUSE_VERB_ATTR = (r"(?:[るたうくすつぬむぶぐ]|ない|ている|ていた|された|される|できる|した|する|った|んだ|いた|えた|れた|せた|"
             r"きた|だった|ような)")
_PAUSE_CLAUSE_IN = re.compile(r"(?<=[" + _PAUSE_KANJI + r"ぁ-んァ-ヴー])" + _PAUSE_VERB_ATTR +
                       r"(?=[" + _PAUSE_KANJI + r"ァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ【「『（(［\[]|の|こと|もの|とき|ところ|ほう)")
_PAUSE_OKURI_NOUN = re.compile(r"(?:問い合わせ|打ち合わせ|取り消し|申し込み|引き渡し|割り当て|振り込み|書き込み|読み込み|受け付け|"
                        r"立ち上げ|切り替え|切り出し|入れ替え|洗い出し|聞き取り|見積もり|取り込み|呼び出し|払い戻し|"
                        r"組み合わせ|貸し出し|締め|売り場|手当て|付け直し|使い方|考え方|進め方|書き方|作り)")
# 分裂文（〜のは、〜のが、〜ことが、）。
_PAUSE_CLEFT = re.compile(_PAUSE_VERB_ATTR + r"(?:の|こと)$|(?:かった|しい|たい|ない|な|だった)の$")
# 条件・場面・時の枠
_PAUSE_FRAME = re.compile(_PAUSE_VERB_ATTR + r"(?:場合|とき|時|際|ころ|あと|後|うち|ため|上|うえ|前|間|限り|範囲|以上|"
                   r"あいだ|のち|直前|直後|最中|途中|以降|以前|前後)(?:に|で)?$|"
                   r"(?:場合|とき|際)(?:に|で)?$|" + _PAUSE_VERB_ATTR + r"$")
_PAUSE_FRAME_CHUNKS = {"は", "も", "には", "では", "からは", "までは"}
# 人と指示語だけの主題（随筆の語りの間）
_PAUSE_PERSON = re.compile(r"(?:僕|ぼく|私|わたし|わたくし|俺|おれ|あたし|自分|彼女|彼|我々|われわれ|あなた|君|きみ)(?:たち|ら|達)?$|(?:の人|人たち|人々)$")
_PAUSE_DEMONSTRATIVE = re.compile(r"^(?:それ|これ|あれ|そこ|ここ|あそこ|こちら|そちら|どれ|どこ)$")
_PAUSE_FIXED_SUBJ = re.compile(r"(?:必要|こと|可能性|恐れ|おそれ|余地)$")
_PAUSE_NOMINAL_END = re.compile(r"(?:こと|もの)$|" + _PAUSE_VERB_ATTR + r"の$")
# 手紙の時候の挨拶「皆様には、ますます〜」（お客様は除く）
_PAUSE_LETTER_ADDRESS = re.compile(r"(?<!客)(?:様|さま|各位)$")
_PAUSE_LETTER_GREETING = re.compile(r"(?:ますます|益々|いよいよ|一層)")
# 並べの項目の前の句（名詞で終わる）。今回、現在のような副詞の名詞は1つだけでは並べにしない
_PAUSE_ADVERBIAL_NOUN = re.compile(r"(?:結果|ため|上|うえ|際|場合|とき|ところ|一方|今回|現在|今後|以前|当日|通常|実際|最初|最後|当初|従来)$")
_PAUSE_ITEM_START = re.compile(r"^\s*(?:[-*+•]|\d+[.)．])\s")
_PAUSE_LABEL_LINE = re.compile(r"^[^、，,]{0,12}$(?<![ぁ-ん。！？!?」』）)])")

_PAUSE_MAX_LEN = 15
_PAUSE_LIST_ITEM_MAX = 18
_PAUSE_SHORT_CLAUSE = 10


def _pause_comma_chunk(t, i):
    for comp in _PAUSE_COMPOUND:
        st = i + 1 - len(comp)
        if st >= 0 and t[st:i + 1] == comp:
            prev = t[st - 1] if st > 0 else ""
            if comp.startswith("と") and prev in "こひもあ":
                continue
            if comp in ("では", "でも") and prev in "ん":
                continue
            if comp.startswith("に") and prev in "な":
                continue
            return comp, st
    return t[i], i

def _pause_comma_next_subject(after):
    parts = re.split(r"(、|。)", after)
    text = ""
    for k in range(0, len(parts), 2):
        seg = parts[k]
        text += seg
        # 並べの1項目は目的語の「を」を含まない（「〜方法に変え、」は項目にしない）。
        is_list_item = (len(seg) <= _PAUSE_LIST_ITEM_MAX and not re.search(r"[ぁ-ん]{2,}$", seg) and not re.search(r"[をにでへとがはも]$", seg)
                        and "を" not in seg and k + 1 < len(parts) and parts[k + 1] == "、")
        if not is_list_item:
            break
        text += "、"
    for m in re.finditer(r"(が|は)", text[:60]):
        before = text[:m.start()]
        if not before or before[-1] in "、":
            continue
        if m.group(1) == "が":
            if _PAUSE_GA_CONJ_END.search(before) and not _PAUSE_GA_NOUN_HIRA.search(before):
                continue
            if _PAUSE_FIXED_SUBJ.search(before) and re.match(r"(?:あ|な|でき|大き|高)", text[m.end():]):
                continue
        # 「〜ことが」「〜するのが」は名詞化した主語なので、助詞の「と」「の」と分ける。
        nominal = _PAUSE_NOMINAL_END.search(before)
        if m.group(1) == "は" and not nominal:
            if re.search(r"(?:で|に|と|て|から|まで|へ|より|だけ|ので)$", before):
                continue
        if before[-1] in "をにへとのやか" and not nominal:
            continue
        return True
    return False

def _pause_comma_quote_blocks(phrase):
    """句の中のかっこの中身を返す。"""
    out, depth, cur = [], 0, []
    for ch in phrase:
        if ch in _PAUSE_OPEN:
            depth += 1
            if depth == 1:
                cur = []
                continue
        if ch in _PAUSE_CLOSE and depth > 0:
            depth -= 1
            if depth == 0:
                out.append("".join(cur))
                continue
        if depth > 0:
            cur.append(ch)
    return out

def _pause_comma_context(text):
    """深さ、句の頭、文の範囲、文頭判定の累積表を行につき1回作る。"""
    depths, phrase_starts, sentence_ids, spans = [], [0], [], []
    nonlead = [0]
    depth, boundary, sentence_start = 0, 0, 0
    for i, ch in enumerate(text):
        if ch in _PAUSE_OPEN:
            depth += 1
        depths.append(depth)
        sentence_ids.append(len(spans))
        if depth == 0:
            if ch in _PAUSE_BOUNDARY:
                boundary = i + 1
            if ch in "。！？!?":
                spans.append((sentence_start, i))
                sentence_start = i + 1
        phrase_starts.append(boundary)
        nonlead.append(nonlead[-1] + (ch not in _PAUSE_LEAD_SYMBOLS + _PAUSE_OPEN))
        if ch in _PAUSE_CLOSE and depth > 0:
            depth -= 1
    spans.append((sentence_start, len(text)))
    return depths, phrase_starts, sentence_ids, spans, nonlead


_PAUSE_PARTICLE_COMMA = re.compile(r"(?=(は|が|も)、)")
# 「Aも、Bも〜」のあとの「も」（「最も」「もの」は除く）
_PAUSE_LATER_MO = re.compile(r"(?<!最)[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9）」』]も(?!の)")
_PAUSE_LIST_AND = re.compile(r"[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9さみ](?:と|や)[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9]")


def _pause_comma_phrase_end(t, k, depth):
    """位置 k から、深さ0の次の句の区切りの位置を返す。"""
    n = len(t)
    while k < n and not (depth[k] == 0 and t[k] in _PAUSE_BOUNDARY):
        k += 1
    return k


def _pause_comma_prev_segment(t, j, starts):
    """句の頭 j の直前が読点のとき、その前の句を返す（なければ None）。"""
    if j < 2 or t[j - 1] not in "、，,":
        return None, 0
    k = starts[j - 2]
    return t[k:j - 1].lstrip(_PAUSE_LEAD_SYMBOLS), k


def _pause_comma_list_before(t, j, starts):
    """句が名詞の並べの最後の項目か（「A、B、Cは、」「AやB、Cは、」）。"""
    prev, k = _pause_comma_prev_segment(t, j, starts)
    if not prev or not _PAUSE_NOUNISH_END.search(prev) or _PAUSE_ADVERBIAL_NOUN.search(prev):
        return False
    if _PAUSE_LIST_AND.search(prev):
        return True
    prev2, _ = _pause_comma_prev_segment(t, k, starts)
    return bool(prev2 and _PAUSE_NOUNISH_END.search(prev2) and not _PAUSE_ADVERBIAL_NOUN.search(prev2))


def _pause_comma_hits(plain_text):
    """見える1行から (助詞の位置, かたまり, 句) を出現順に返す。"""
    t = plain_text
    if not any(p in t for p in ("は、", "が、", "も、")):
        return []
    depth, starts, sentence_ids, spans, nonlead = _pause_comma_context(t)
    positions = [m.start() for m in _PAUSE_PARTICLE_COMMA.finditer(t)]
    # r の同じかたまりの出現数。複合助詞の接尾辞も数える。
    # 句ごとの sent.count や文の切り出しを避ける。
    counts = [{} for _ in spans]
    for i in positions:
        # 引用の中と、述語のあとの「が、」（逆接）は並べに数えない。
        if depth[i] > 0:
            continue
        if t[i] == "が":
            pre = t[max(0, i - 8):i]
            if _PAUSE_GA_CONJ_END.search(pre) and not (_PAUSE_GA_NOUN_HIRA.search(pre) or _PAUSE_NOUNISH_END.search(pre)):
                continue
        counts_in_sentence = counts[sentence_ids[i]]
        for chunk in _PAUSE_COMPOUND + ["は", "が", "も"]:
            if t.startswith(chunk, max(0, i + 1 - len(chunk)), i + 1):
                counts_in_sentence[chunk] = counts_in_sentence.get(chunk, 0) + 1
    hits = []
    unquoted = None
    for i in positions:
        # a: 引用の中。b: 長い助詞のかたまりから照合。c: 接続・譲歩。
        if depth[i] > 0:
            continue
        chunk, cstart = _pause_comma_chunk(t, i)
        if chunk in _PAUSE_SKIP_CHUNKS:
            continue
        # d: 句の頭の箇条書き記号とチェックボックスを除く。
        j = starts[cstart]
        phrase = _PAUSE_CHECKBOX.sub("", t[j:cstart].lstrip(_PAUSE_LEAD_SYMBOLS)).lstrip(_PAUSE_LEAD_SYMBOLS)
        if not phrase or not _PAUSE_WORD.search(phrase):
            continue
        # e: 引用から続く句。f: 逆接の「が」。g: て形。
        if phrase[0] in _PAUSE_CLOSE or (phrase[0] == "と" and j >= 1 and t[j - 1] in "、，,"):
            continue
        if (chunk == "が" and _PAUSE_GA_CONJ_END.search(phrase)
                and not (_PAUSE_GA_NOUN_HIRA.search(phrase) or _PAUSE_NOUNISH_END.search(phrase))):
            continue
        if chunk in ("は", "も") and re.search(r"(?:て|で)$", phrase):
            continue
        if chunk == "も" and re.search(r"(?:けれど|しか|それで|それに|ど)$", phrase):
            continue
        # h: 接続・定型。i: 既存規則が拾う文頭。
        sstart, send = spans[sentence_ids[i]]
        at_start = nonlead[j] == nonlead[sstart]
        whole = phrase + chunk
        if whole in _PAUSE_CONNECTIVE or _PAUSE_CONNECTIVE_END.search(whole):
            continue
        if at_start and _PAUSE_COVERED.match(whole):
            continue
        if chunk == "には" and _PAUSE_LETTER_ADDRESS.search(phrase) and _PAUSE_LETTER_GREETING.match(t, i + 2):
            continue
        # j: 引用を含む主語。k: 空白を除いて15字を超える句。
        if re.search(r"[」』”）)]と", phrase):
            continue
        if any(re.search(r"[、。！？!?]", inner) or len(inner) > 12
               for inner in _pause_comma_quote_blocks(phrase)):
            continue
        plen = len(re.sub(r"\s", "", phrase))
        if plen > _PAUSE_MAX_LEN:
            continue
        # l: 分裂文。m: 条件・場面。n: 問いの節。
        if chunk in ("は", "が") and _PAUSE_CLEFT.search(phrase):
            continue
        if chunk in _PAUSE_FRAME_CHUNKS and _PAUSE_FRAME.search(phrase):
            continue
        if phrase.endswith("か") and plen > _PAUSE_SHORT_CLAUSE:
            continue
        # o: 句の中の主語。p: 送り仮名の名詞を伏せて節を調べる。
        if len(phrase) > 1 and re.search(r"[^、]が(?!、)|[^でにとて]は(?!、)", phrase[:-1]):
            continue
        masked = _PAUSE_OKURI_NOUN.sub(lambda m: "名" * len(m.group(0)), phrase)
        if plen > _PAUSE_SHORT_CLAUSE and _PAUSE_CLAUSE_IN.search(masked):
            continue
        # q: あとの主語。先頭60字と、その直後の定型を判定できれば足りる。
        # 18字の並べの終わりを見分ける余裕も含め84字に限り、長い接尾辞をコピーしない。
        # かっこの中（引用や題名）の助詞と読点は、あとの主語や並べに数えない。
        if unquoted is None:
            unquoted = "".join("〇" if d else ch for ch, d in zip(t, depth))
        after = unquoted[i + 2:min(send + 1, i + 2 + 84)]
        if _pause_comma_next_subject(after):
            continue
        # r: 同じ文の並べ、句の中の並べ、直前の「と、」「や、」。
        if counts[sentence_ids[i]].get(chunk, 0) > 1:
            continue
        if re.search(r"[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9さみ](と|や)[" + _PAUSE_KANJI + r"ァ-ヴーA-Za-z0-9]", phrase):
            continue
        if j >= 2 and t[j - 2] in "とや" and t[j - 1] == "、":
            continue
        if _pause_comma_list_before(t, j, starts):
            continue
        if chunk.endswith("も") and _PAUSE_LATER_MO.search(t[i + 2:_pause_comma_phrase_end(t, i + 2, depth)]):
            continue
        # s: 人と指示語。t: 外すと同じ字がつながる所。
        if _PAUSE_PERSON.search(phrase) or _PAUSE_DEMONSTRATIVE.match(phrase):
            continue
        if i + 2 < len(t) and t[i + 2] == t[i]:
            continue
        hits.append((i, chunk, phrase))
    return hits


def _pause_comma_line_hits(analysis):
    """段落と箇条書きの1項目ごとに、見える行をつないで当てる（行をまたぐ文と引用を1つに読む）。
    行番号から、その行の見える文字での (助詞の位置, かたまり, 句) の並びへの表を返す。"""
    out = {}

    def flush(unit, kind):
        if not unit:
            return
        joined = "".join(plain for _, plain in unit)
        offsets, pos = [], 0
        for line_no, plain in unit:
            offsets.append(pos)
            out[line_no] = []
            pos += len(plain)
        # 段落が句点なしにかなや読点で終わるときは、文の途中で切れていてあとが見えないので、その文では拾わない
        # （名詞で終わる題名のような行は拾う）。
        tail = len(joined)
        if kind == "paragraph" and re.search(r"[ぁ-ん、，,]$", joined.rstrip()):
            tail = max(joined.rfind(ch) for ch in "。！？!?")
        for i, chunk, phrase in _pause_comma_hits(joined):
            if i > tail:
                continue
            k = bisect_right(offsets, i) - 1
            out[unit[k][0]].append((i - offsets[k], chunk, phrase))
        del unit[:]

    for block in analysis["blocks"]:
        kind = block["kind"]
        if kind not in ("paragraph", "list"):
            continue
        unit = []
        for row in block["lines"]:
            if row["quote_depth"] or row["kind"] not in ("paragraph", "list"):
                flush(unit, kind)
                continue
            plain = _prose_visible_text(analysis, row["line"]).strip().replace("__", "").replace("*", "")
            if not plain:
                flush(unit, kind)
                continue
            # 新しい項目と、短く名詞で終わる見出しのような行（「■影響」）のあとでは、つながない。
            if unit and (_PAUSE_ITEM_START.match(row["raw"]) or _PAUSE_LABEL_LINE.match(unit[-1][1])):
                flush(unit, kind)
            unit.append((row["line"], plain))
        flush(unit, kind)
    return out


_PENALTY_WEIGHTS = {"error": 3, "warn": 2, "info": 1}
_PENALTY_FLOOR = 1000
_PENALTY_HALF = 40
_DOCUMENT_RULE_WEIGHTS = {"excess_bold": 2, "excess_list": 2, "bold_label_list": 1}
_SUMMARY_RULES = ("negative_parallelism_density",)
# 2.2.0 で足した規則。どれも info で、点数を計算する前に除く（この規則の候補だけなら100のまま）。
# 点数に入れるかは tests/corpus で測って決める
_V220_RULES = ("calque", "metaphor_label", "say_hedge", "thin_evaluation", "katakana_term", "dialogue_period",
               "narrative_density", "copy_comma_noun", "bare_verb_chain", "project_term")
_DASH_RULES = ("dash_decoration", "dash_insertion", "dash_list_ending")


def _rule_penalty_score(findings, prose_chars, dash_hits):
    """行の候補の密度と文書単位の候補から、整数だけで目安を計算する。"""
    if not findings:
        return 100
    line_weight = 0
    document_weight = 0
    dash_found = 0
    for finding in findings:
        rule = finding["rule"]
        if rule in _DASH_RULES:
            dash_found += 1
        if rule in _DOCUMENT_RULE_WEIGHTS:
            document_weight += _DOCUMENT_RULE_WEIGHTS[rule]
        elif rule not in _SUMMARY_RULES:
            line_weight += _PENALTY_WEIGHTS[finding["severity"]]
    line_weight += max(0, dash_hits - dash_found) * _PENALTY_WEIGHTS["warn"]
    m = max(prose_chars, _PENALTY_FLOOR)
    num = 100 * _PENALTY_HALF * m
    den = (_PENALTY_HALF + document_weight) * m + 1000 * line_weight
    return max(1, min(99, (2 * num + den) // (2 * den)))


# 2.2.0 の語の規則（calque、metaphor_label、katakana_term、thin_evaluation）。どれも info で、置き換え先の語は出さない。
# 行ごとに、地の文の見える文字（_prose_visible_text と同じ伏せ方）から、カギ括弧と引用符の中と、英数字の識別子（snake_case、
# camelCase、ドットや / を含む語）を伏せて見る。コード、引用（> の行）、frontmatter、HTML は見ない。見出し、表、箇条書きは見る。
# 1行に同じ規則の候補は1件まで。当たった語は候補の内部の欄 _words に入れる（語の一覧の allow.txt で外すため。出力には出ない）。
# 速さのため、文書全体に一度だけ、どれかの規則の手掛かりの語（_V220_TRIGGER_LITERALS と2つの一覧の語）を当て、
# 当たった行と、見出しと1行目のうちラベルになりうる行だけを細かく見る。
class _V220Lazy:
    """初めて使うときに組む正規表現（2.2.0 の規則の正規表現は、当たる手掛かりがある文書でだけ要るので、読み込みのときには
    組まない。lint を CLI で1文書ずつ動かすときの起動の時間を延ばさないため）。組んだあとは re.Pattern の関数をそのまま持つ。"""

    def __init__(self, pattern, flags=0):
        self.pattern = pattern
        self._flags = flags

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        compiled = re.compile(self.pattern, self._flags)
        for method in ("search", "match", "fullmatch", "finditer", "findall", "sub", "split"):
            setattr(self, method, getattr(compiled, method))
        return getattr(compiled, name)


_V220_MESSAGE_TAIL = "の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。"
_CALQUE_TYPE_NAMES = {1: "型1: 機械やシステムが人の動作をする言い方",
                      2: "型2: 実物の名前の代わりに場所のたとえを使う名詞",
                      3: "型3: 英語の言い方を一語ずつ写した句"}
# 伏せる所: 引用符の中（カギ括弧は _mask_quoted_segments で伏せる）と、英数字の識別子
_V220_QUOTES = _V220Lazy(r"“[^”\n]*”|\"[^\"\n]*\"|‘[^’\n]*’")
_V220_IDENTIFIER = _V220Lazy(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[_./\\][A-Za-z0-9]+)+[_./]?|(?<![a-z])[a-z]+[A-Z][A-Za-z0-9]*|[_./\\][A-Za-z0-9_]+")
_V220_SENTENCE = _V220Lazy(r"[^。．！？!?|｜]+[。．！？!?]*")

# 型1: 機械やシステムが主語の文（主語の語に「は」「が」「も」「こそ」が付く）で、人や物の動作の動詞を使う形。
# 主語の語のあとに漢字やカタカナが続いて人や組織の語で終わるとき（サーバー管理者、情報システム部）は主語にしない。
_CALQUE_SUBJECTS = tuple((
    "ジョブ 処理 バッチ サーバー サーバ システム API 関数 スクリプト キュー ワーカー "
    "プロセス モジュール 設定 鍵 ミドルウェア クライアント ビルド エージェント フック クエリ "
    "チェック インデックス キャッシュ ライブラリ プログラム アプリ サービス ツール コマンド "
    "パイプライン ルーター ロードバランサー ゲートウェイ プロキシ データベース DB Webhook ボット "
    "クローラー スケジューラー コンテナ ノード クラスター センサー 端末 デバイス 機器 装置 "
    "受信側 送信側 監視 ファイアウォール フィルター パーサー コンパイラ リンター エンジン ブラウザ "
    "プラグイン 拡張機能 バックエンド フロントエンド テスト 体重計 計測器 cron CI "
).split())
_CALQUE_PERSON_END = r"(?:者|員|人|さん|様|さま|氏|チーム|部|課|室|班|係|担当|会社|社|陣|部門|部署)"
_CALQUE_SUBJECT_WORD = _V220Lazy(r"(?<![A-Za-z])(?:" + "|".join(sorted(map(re.escape, _CALQUE_SUBJECTS), key=len, reverse=True))
                                  + r")")
_CALQUE_SUBJECT_EXT = 6           # 主語の語のあとに続いてよい漢字、カタカナ、英数字の数（再送ジョブ管理画面が）
_CALQUE_SUBJECT_PARTICLES = ("こそ", "は", "が", "も")
_CALQUE_PERSON_SUBJECT = _V220Lazy(
    r"(?:" + _CALQUE_PERSON_END[3:-1] + r"|私|僕|わたし|ぼく|我々|皆さん|みなさん|お客様|彼|彼女|あなた)(?:は|が|も|こそ)")
_CALQUE_PERSON_EXT = _V220Lazy(_CALQUE_PERSON_END + r"$")
# (辞書の形, 正規表現)。活用の形まで書き、名詞の使い方（引き続き、通りに、足し算、食い違い）は外す。
# 動詞の漢字の前が漢字のとき（不足して、共通する、電話します、補足すると）は、_calque_type1 が外す（_CALQUE_COMPOUND_OK の動詞を除く）
_CALQUE_VERBS = (
    ("拾う", r"拾(?:う|い|わ|っ[てた]|え|お)"),
    ("引き込む", r"引き込(?:む|み|ん|ま|め)"),
    ("引く", r"(?<!差し)引(?:く|い[てた]|か(?:な|ず|れ)|き(?=[ぁ-ん])|け(?=[ぁ-ん]))"),
    ("通す", r"(?<!を)通(?:す|し(?=[ぁ-ん])|さ(?:な|ず|せ))"),
    ("通る", r"通(?:る|り(?=[ぁ-ん])(?![にのだでがはをもと])|ら(?:な|ず)|っ[てた]|れ(?=[ぁ-ん]))"),
    ("効く", r"効(?:く|き(?=[ぁ-ん])|か(?:な|ず)|い[てた]|け(?=[ぁ-ん]))"),
    ("響く", r"響(?:く|き(?=[ぁ-ん])|か(?:な|ず)|い[てた]|け(?=[ぁ-ん]))"),
    ("足す", r"足(?:す|し(?=[ぁ-ん])|さ(?:な|ず|れ)|せ(?=[ぁ-ん]))"),
    ("抱える", r"抱え(?:る|て|た|ま|な|ず|込)"),
    ("見張る", r"見張(?:る|り|っ[てた]|ら|れ)"),
    ("食う", r"食(?:う|い(?=[ぁ-ん])|わ(?:な|ず|れ)|っ[てた])|食べ(?:る|て|た|ま|な|ず|られ)"),
    ("受け止める", r"受け止め"),
    ("飲み込む", r"[飲呑]み込(?:む|み|ん|め|ま)"),
    ("覚える", r"覚え(?:る|て|た|ま|な|ず|させ|られ)"),
    ("忘れる", r"忘れ(?:る|て|た|ま|な|ず|られ)"),
    ("投げる", r"投げ(?:る|て|た|ま|な|ず|込|つけ|られ)"),
    ("叩く", r"叩(?:く|き(?=[ぁ-ん])|か(?:な|ず|れ)|い[てた])"),
    ("話す", r"話(?:す|し(?=[ぁ-ん])|さ(?:な|ず)|せ(?=[ぁ-ん]))"),
    ("喋る", r"喋(?:る|り|ら|っ[てた]|れ)"),
    ("助ける", r"助け(?:る|て|た|ま|な|ず|られ)"),
    ("手伝う", r"手伝(?:う|い|わ|っ[てた]|え)"),
    ("気にする", r"気に(?:す|し|せ|さ)"),
    ("怒る", r"怒(?:る|り(?=ま)|ら|っ[てた])"),
    ("文句を言う", r"文句を(?:言|い)"),
)
# 前が漢字でもよい動詞（引き込む、抱える、見張る など、漢字の熟語の一部にならない語幹）
_CALQUE_COMPOUND_OK = ("引き込む", "抱える", "見張る", "受け止める", "飲み込む", "覚える", "忘れる", "投げる", "喋る", "助ける",
                       "手伝う", "文句を言う")
# 動詞ごとの (語幹の字, 辞書の形, 正規表現)。文に語幹の字があるときだけ、その動詞の正規表現を組んで当てる
_CALQUE_VERB_EACH = tuple((re.sub(r"^(?:\(\?<![^)]*\))*(?:\[[^\]]*\])?", "", pattern)[0], name, _V220Lazy(pattern))
                          for name, pattern in _CALQUE_VERBS)
# 型1の定着した言い方（試験で守る）。動詞がこの当たりの中にあれば出さない。
# 動詞が名詞を修飾する形（拾った通知、話した内容）は、主語が機械と決まらないので出さない
_CALQUE_ESTABLISHED_TYPE1 = (
    r"テスト(?:が|は|も)(?:すべて|全部|全て|無事に?)?通",
    # 件数や一式、道具の名前をはさむ形（テストは218件とも通りました、テスト一式は pytest で通す）
    r"テスト(?:一式)?[0-9０-９]*件?(?:が|は|も)(?:[0-9０-９]+件(?:とも|すべて)?|すべて|全部|全て|無事に?|\s?[A-Za-z][\w.-]{0,15}\s?で)?\s?通",
    r"(?:ビルド|CI|コンパイル|審査|申請|予算|企画|法案|稟議|認証|筋|話|声|意見|理屈|名前|電気|電流)\s?(?:が|は|も)(?:無事に?)?通",
    r"(?i:ping)\s*(?:が|は|も)\s*通", r"疎通",
    r"(?:キャッシュ|インデックス|薬|ブレーキ|冷房|暖房|エアコン|設定|オプション|フラグ|権限|フック|上限)\s?(?:が|は|も)(?:よく|まだ|うまく)?効",
    # 設定やフックが何に及ぶかを言う「〜にも効く」（フックは、サブエージェントの呼び出しにも効く）
    r"(?:設定|オプション|フラグ|権限|フック|上限|ルール|規則)\s?(?:が|は|も)、?[^。]{0,30}?に(?:も)?効",
    r"(?:声|音|ノイズ|電波|信号|振動)を拾",
    # 検出の意味の「拾う」（表現を拾う、エラーを拾う）
    r"(?:誤り|誤字|脱字|表現|候補|エラー|警告|違反|表記ゆれ|変更|差分)を[^。、]{0,6}拾",
    r"から[^。、]{0,15}(?:額|数|値|分|量|費|料|金|点|[0-9０-９]+)を引(?:く|き|い|か)",
    r"(?:線|辞書|くじ|クジ|風邪|かぜ|手|目|注意|関心|興味|気|幕|身|糸|尾|図|グラフ|罫線|下線|傍線|カーテン|ブラインド)を引",
    r"落とし物を拾", r"(?:例外|エラー|exception|Exception)を投げ",
    r"(?:課題|問題|負債|リスク|不安|悩み|弱点|欠陥|バグ|不具合|矛盾)を(?:多く|いくつも|たくさん)?抱え",
)
_CALQUE_ESTABLISHED_TYPE1_RE = _V220Lazy("|".join(_CALQUE_ESTABLISHED_TYPE1))
_CALQUE_KANA_RUN = _V220Lazy(r"[ぁ-ん]*")
# 主語から動詞までの字数の上限と、間にあれば主語と動詞を結ばない記号（括弧、矢印。例を並べた文）
_CALQUE_SUBJECT_REACH = 30
_CALQUE_SUBJECT_BREAK = _V220Lazy(r"[（()）「」『』→←]")
_CALQUE_REQUEST = ("てください", "て下さい", "てくださ", "いでくださ", "いで下さ", "なさい", "ましょう", "てほしい", "て欲しい",
                   "ていただ", "てもらえ")
_CALQUE_ATTRIBUTIVE_END = ("た", "る", "う", "く", "す", "つ", "む", "ぶ", "ぐ", "だ", "ない", "いる")

# 型2: 場所のたとえの名詞。受け口と「〜向けの口」はいつも拾う。「〜先」は _CALQUE_SAKI の形で、定着した語
# （_CALQUE_ESTABLISHED_SAKI）を除いて拾う。入口、窓口などの実物にもある名前は、同じ文に機械やシステムの語（_CALQUE_TECH）が
# あるときだけ拾い、実物の場所（駅の入口）と組織の窓口（総務部の窓口）は外す
# 後ろに漢字やカタカナが続く語（入口付近、窓口業務、口座）は _calque_type2 が外す。動詞のあとの「口」（トークンを出す口）は、
# 実物の口（水を出す口、切符を受け取る口）と分けるため、機械やシステムの語がある文だけで拾う
_CALQUE_PLACE_ALWAYS = _V220Lazy(r"受け口|(?:向け|用)の口|(?:出す|受ける|受け取る|返す|渡す|発行する)口(?=[はがをにでもへと、。]|$)")
_CALQUE_PLACE_CONTEXT = _V220Lazy(r"(?:入り?口|出口|窓口|玄関口?|関所|関門|裏口|勝手口|抜け道|裏道|通り道|合流地点|合流点"
                                   r"|防波堤|砦)|の口(?=[はがをにでもへと、。]|$)")
# 実物の場所の入口（駅の入口、正面入口、2番入口）と、組織の窓口（総務部の窓口）
_CALQUE_PLACE_REAL = _V220Lazy(
    r"(?:駅|正面|[東西南北]|番|建物|ビル|店|会場|公園|館|門|地下|トンネル|洞窟|港|校舎|病院|施設|部屋|通用|非常|改札|階段"
    r"|空港|ホーム|ホール|劇場|球場|庭|家|屋敷|森|山|川|村|町|街|道|高速|本館|別館|棟|フロア|階"
    # 2.2.1: 技術の文書の中の実物の場所（サーバールーム、データセンター、北側の出口）
    r"|ルーム|室|センター|オフィス|倉庫|工場|店舗|売り場|ロビー|受付|玄関|フロント|側)の?$")
_CALQUE_PLACE_ORG = _V220Lazy(
    r"(?:部|課|室|係|局|センター|デスク|担当|相談|問い合わせ|問合せ|受付|事務所|事務局|総合|専用|役所|役場|銀行|郵便局"
    r"|市役所|区役所|窓口|申請|手続き|手続)の?$")
_CALQUE_MOUTH_REAL = _V220Lazy(
    r"(?:人|彼|彼女|私|僕|子|犬|猫|魚|鳥|瓶|びん|袋|ボトル|缶|容器|鍋|壺|樽|筒|穴|管|ホース|川|洞窟|トンネル|火山|傷|蛇)の口$")
_CALQUE_MOUTH_IDIOM = _V220Lazy(r"口(?:に合|が(?:堅|固|軽|悪|うま|上手|重|滑|すべ|裂)|を(?:出|挟|はさ|開|ひら|閉|とざ|揃|そろ"
                                 r"|つぐ|きく|利|割))")
_CALQUE_TECH = _V220Lazy(
    r"(?<![A-Za-z])(?:" + "|".join(sorted(map(re.escape, _CALQUE_SUBJECTS), key=len, reverse=True))
    + r"|データ|URL|リクエスト|レスポンス|接続|通信|トラフィック|ログイン|認証|ポータル|ページ|画面|サイト|フォーム"
    r"|アドレス|ポート|エンドポイント|ネットワーク|テーブル|ファイル|ログ|エラー|通知|CSV|JSON|HTTP|送信|受信|集計|決済"
    r"|リポジトリ|コード|メソッド|クラス|インターフェース|SDK|トークン|パケット|イベント|メッセージ|ドライブ|チャンネル)")
# 入口と出口は、同じ文に技術の語がなくても、技術の文書（_CALQUE_TECH の語が5種類以上）で、要求や接続を集めたり通したり
# する形（この入口を通ります、ひとつの入口に集めています）なら拾う。実物の場所（_CALQUE_PLACE_REAL）は今までどおり外す
_CALQUE_DOC_TECH_MIN = 5
_CALQUE_ENTRY_FLOW = _V220Lazy(r"(?:の前|を通|に集め|へ集め|に届|へ届|で受け|を経由|から入)")
# 窓口は、コードの部品の語が同じ文にあり、組織の名前（総務部、情報システム課、サポートセンター）がないときだけ
# （決済の窓口をこのモジュールに集める）
_CALQUE_ORG_WORDS = ("センター", "デスク", "担当", "事務局")
_CALQUE_ORG_SUFFIXES = "部課室係局班"
_CALQUE_CODE = _V220Lazy(r"(?<![A-Za-z])(?:モジュール|関数|クラス|API|エンドポイント|サーバー|サーバ|コード|ライブラリ|メソッド"
                          r"|インターフェース|SDK|ミドルウェア|プロキシ|ゲートウェイ)")
# 「〜先」: 漢字1字と動詞の連用形の送り仮名（し、せ、げ など）のあとの「先」（逃がし先、寄せ先）と、場所のたとえの漢語の「先」
# （_CALQUE_SAKI_KANJI。着地先）。漢字2字の「〜先」の多くは定着した語（保存先、接続先、修飾先）なので、一覧の語だけを拾う。
# 後ろに漢字やカタカナが続く語（先日、先方）と、助詞や「て」のあとの「先」（何を先に、置いて先に、項より先）は除く
_CALQUE_SAKI_KANJI = ("着地", "着弾", "漂着", "逃走", "終着", "着陸", "落下")
_CALQUE_SAKI_TAIL = "しせげけめりちきぎびみいえねべれじ"
# 定着した「〜先」（試験で守る）。当たった語がこのどれかで終われば出さない
_CALQUE_ESTABLISHED_SAKI = tuple((
    "宛先 宛て先 送信先 受信先 保存先 接続先 連絡先 取引先 依存先 問い合わせ先 問合せ先 "
    "回し先 割り振り先 振り分け先 立ち寄り先 働き先 通い先 務め先 引き合い先 取り寄せ先 借り先 貸し先 "
    "問合わせ先 提出先 申請先 申込先 申し込み先 照会先 相談先 通報先 報告先 連携先 格納先 "
    "出力先 入力先 書き込み先 読み込み先 書き出し先 取り込み先 移動先 移行先 遷移先 参照先 "
    "呼び出し先 配信先 通知先 公開先 共有先 掲載先 展開先 導入先 設置先 登録先 記録先 保管先 "
    "退避先 返却先 回収先 引き取り先 引き継ぎ先 譲渡先 売却先 取得先 利用先 適用先 反映先 "
    "割り当て先 割当先 代入先 転送先 送付先 返送先 請求先 支払先 支払い先 振込先 振り込み先 "
    "入金先 送金先 投資先 融資先 寄付先 預け先 預入先 勤務先 勤め先 所属先 配属先 委託先 "
    "外注先 発注先 受注先 仕入先 仕入れ先 購入先 調達先 供給先 納品先 納入先 出荷先 配送先 "
    "配達先 届け先 送り先 販売先 輸出先 輸入先 取材先 派遣先 出向先 転勤先 赴任先 就職先 "
    "転職先 進学先 留学先 旅行先 出張先 訪問先 避難先 移住先 越し先 滞在先 宿泊先 行き先 "
    "得意先 嫁ぎ先 落ち着き先 引受先 受け入れ先 受入先 実習先 研修先 見学先 紹介先 取次先 "
    "接種先 通院先 入院先 搬送先 転院先 飛び先 戻り先 移し先 写し先 優先 通信先 同期先 "
    "複製先 複写先 配置先 配備先 配布先 発行先 発送先 発信先 着信先 返信先 回答先 問合先 "
    "移転先 移設先 転居先 引越先 誘導先 案内先 相手先 顧客先 契約先 提携先 協力先 加盟先 "
    "参加先 出資先 移籍先 異動先 転属先 採用先 応募先 投稿先 寄稿先 掲示先 提供先 供与先 "
    "貸与先 買収先 寄贈先 支援先 返金先 引落先 引き落とし先 外出先 観光先 持参先 届出先 "
    "表示先 書込先 読込先 待避先 復元先 復旧先 切替先 置換先 変換先 変更先 更新先 追加先 "
    "代替先 委任先 依頼先 請負先 受託先 移管先 電話先 通話先 玄関先 納め先 戻し先 預かり先 "
    "付け先 込み先 出し先 入れ先 渡し先 継ぎ先 替え先 換え先 向け先 扱い先 一足先 "
    "掛かり先 係り先 掛り先 修飾先 "
    "少し先 一つ先 二つ先 三つ先 ひとつ先 以上先 以下先 "
).split())
# 時や距離の「先」（数年先、一歩先、数時間先）
_CALQUE_SAKI_TIME = _V220Lazy(r"[年月日週間時分秒歩手里キロメートル]先$|[たうくるだつむぬぶぐす]先$")

# 型3: 英語の言い方を一語ずつ写した句（試験で守る）。(名前, 正規表現)
_CALQUE_PHRASES = (
    ("足すものがない", r"足すもの(?:が|は|も)(?:ない|ありません|なかった|ありませんでした|何もない)"),
    ("価値を足す", r"価値を足"),
    ("失効が効く", r"失効が効"),
    ("から効く", r"(?:日|月|年|週|請求|分|回|以降|翌[日月週年]|来[月週年]|明日|今日|本日|次回)から効(?:く|き(?=[ぁ-ん])|い[てた])"),
    ("時間を取る", r"(?<![0-9０-９])[0-9０-９]+(?:[.．][0-9０-９]+)?\s*(?:ミリ秒|秒|分|時間)を取(?:る|り|っ|ら)"),
    ("意味をなす", r"意味を(?:なす|成す|なし|成し)(?!てい?な|ませ|えな|得な)"),
    ("針を動かす", r"針を(?:ほとんど|大きく|少し|まったく|全く|あまり)?動か"),
    ("ステップを取る", r"ステップを取"),
    ("所有権を持つ", r"(?:問題|課題|タスク|機能|サービス|障害|不具合|チケット|作業|プロジェクト|コード|モジュール)(?:に(?:は|ついては)|の)、?"
                    r"[^。]{0,12}所有権を持"),
    ("違いを作る", r"違いを作"),
    ("手を伸ばす", r"(?:部|課|室|チーム|担当者?|窓口|サポート|事務局|私たち|弊社|当社|我々)(?:まで|に|へ)(?:お?気軽に)?手を伸ば"),
    ("ライブになる", r"ライブに(?:な|し)"),
    ("同じページにいる", r"同じページ(?:の上)?に(?:い|立|そろ|揃)"),
    ("水を試す", r"水を試"),
    ("透明に", r"(?:にとって|に対して|から見て|からは)透明に|透明に(?:行われ|動作|処理|移行|切り替|動|扱)"),
    ("場所を取る", r"で場所を取(?:る|り|っ)"),
    ("ループを閉じる", r"ループを閉じ"),
    ("ループに入れる", r"ループに(?:入れ|入っ|加え)"),
    ("駆動される", r"(?:データ|数字|数値|指標|顧客|ユーザー|利用者|テスト|仕様)に駆動され"),
    ("配達する", r"(?:数字|数値|結果|成果|価値|売上|利益|成長|体験)を配達"),
    ("大きな絵", r"大きな絵(?:を|が|で|の中)(?![^。]*(?:描|画家|美術|展示|額|飾))"),
    ("インパクトを持つ", r"インパクトを持"),
    ("決定を作る", r"決定を作"),
    ("質問を持つ", r"質問を持(?:っ|ち|つ)"),
    ("真剣に取る", r"真剣に取(?:る|り|っ|ら)"),
    ("目を保つ", r"目を保"),
    ("テーブルに置く", r"(?:案|提案|選択肢|アイデア|条件|議題)を[^。]{0,6}テーブルに(?:置|載せ|乗せ|出)"),
    ("次のレベルに", r"次のレベルに(?:引き上げ|持っていく|押し上げ|連れて)"),
    # 2.2.0 の直訳語の対応表から足した形（machine-to-machine、matter、affect、pull、go through、turn）
    ("機械どうし", r"機械(?:どうし|同士)(?:の|で|が|は|を|に)"),
    ("ときに効く", r"(?:とき|際|場合|うえ|上)に(?:いちばん|特に|大きく|強く)?効(?:く|き(?=[ぁ-ん])|い[てた])"),
    ("に響く", r"(?:クライアント|サーバー?|性能|応答|処理|ユーザー|利用者|ダッシュボード|システム|速度|画面|負荷|料金|費用"
              r"|コスト|請求)(?:の[^。、]{0,6})?に(?:まで|も)?響(?:く|き|い|か)"),
    # 間引く、差し引く、引き渡す、引き上げる、引きずる などの複合の動詞は外す
    ("データを引く", r"(?:データ|ログ|レコード|設定|履歴)を(?:[^。、]{0,6})?(?<![間割])(?<!差し)引"
                    r"(?:く|き(?![出継続受取渡伸上下ず合寄止戻抜締起換替])|い|か|け)"),
    # 「通」の前が漢字の語（予定通り、手順通り、一通り、大通り）と「通りに」などは外す
    ("書き込みが通る", r"(?:書き込み|読み込み|書き換え|削除|更新|操作|アクセス)(?:も|が|は)(?:[^。、]{0,4}[ぁ-ん])?通"
                     r"(?:る|り(?=[ぁ-ん])(?![にのだでがはをもと])|っ|ら|れ)"),
    # 数字の並びの途中から試さないよう、前に数字がないことを見る（長い数字の並びで遅くならない）
    ("ターン", r"(?:毎|(?<![0-9０-９一二三])[0-9０-９一二三]+|各|次の|前の|同じ)ターン(?![ァ-ヴー])"),
)
_CALQUE_PHRASE = _V220Lazy("|".join("(?:{})".format(pattern) for _, pattern in _CALQUE_PHRASES))
_CALQUE_PHRASE_EACH = tuple((name, _V220Lazy(pattern)) for name, pattern in _CALQUE_PHRASES)
# 「〜から効く」は、薬や冷房の効き方（_KIKU_RE の文字どおりの語が同じ文にある）なら出さない
_CALQUE_PHRASE_KIKU = "から効く"
# 対応表から足した句と、型1の同じ動詞（型1が当てた文では句を重ねない）
_CALQUE_PHRASE_VERB = {"ときに効く": "効く", "に響く": "響く", "データを引く": "引く", "書き込みが通る": "通る"}
_CALQUE_TURN_CONTEXT = _V220Lazy(r"指示|会話|依頼|プロンプト|モデル|エージェント|LLM|Claude|Codex|ツール|呼び出|読み込"
                                 r"|応答|返答|トークン|コンテキスト|セッション")
# ゲームの手番の「ターン」（毎ターン山札から引く、敵の AI は毎ターン行動を選ぶ）
_CALQUE_TURN_GAME = _V220Lazy(r"ゲーム|カード|山札|手札|プレイヤー|将棋|囲碁|チェス|手番|モンスター|敵|攻撃|対戦|駒|盤")
# 「ときに効く」は、構成や運用を決める話（what matters）か、機械やシステムの語がある文だけ（疲れたときに効くストレッチは外す）
_CALQUE_KIKU_DECIDE = _V220Lazy(r"構成|設計|選ぶ|選び|決め|判断|見積|運用|導入|移行|方針|検討")
# 「に響く」の文字どおりの音と心（心に響く、音が部屋に響く）
_CALQUE_HIBIKU_LITERAL = _V220Lazy(r"(?:心|胸|耳|琴線)に(?:まで|も)?響|(?:音|声|鐘|足音|歌)(?:が|は|も)")
# 「に響く」の料金や費用は、機械やシステムの語がある文だけ（円安が費用に響く は外す）
_CALQUE_HIBIKU_COST = ("料金", "費用", "コスト", "請求")
# 「機械どうし」は、通信ややり取りの話のときだけ（工場の機械同士の間隔は外す）
_CALQUE_MACHINE_TALK = _V220Lazy(r"通信|やり取り|やりとり|接続|データ|API|連携|認証|リクエスト|メッセージ|プロトコル|経路")

# metaphor_label: 見出しか文書の1行目が、記号を除いて8字以下で、「〜の横」「〜のそば」「〜係」「〜番」で終わるか一語だけで、
# そのラベルが本文のほかの行に出てこないとき。よく使う節の名前（試験で守る）と、関係、一番などは外す
_LABEL_MAX = 8
_LABEL_COMMON = frozenset((
    "概要 背景 目的 手順 結果 まとめ はじめに おわりに 注意 注意点 前提 課題 対策 原因 "
    "準備 作り方 進め方 使い方 やり方 読み方 書き方 考え方 そのほか その他 参考 参考文献 "
    "付録 補足 備考 要約 結論 考察 方法 経緯 現状 影響 今後 次回 予定 日程 費用 "
    "体制 対象 範囲 方針 構成 仕様 設計 実装 導入 設定 環境 要件 機能 特徴 制限 "
    "制約 問題 解決策 謝辞 用語 定義 例 実例 例文 質問 回答 連絡先 問い合わせ "
    "お問い合わせ 変更点 変更履歴 更新履歴 履歴 一覧 目次 序文 序章 終章 本文 内容 詳細 "
    "評価 検証 試験 運用 保守 監視 障害 対応 復旧 再発防止 再発防止策 振り返り 所感 "
    "感想 学び 教訓 議題 決定事項 宿題 出席者 参加者 日時 場所 持ち物 料金 価格 "
    "申し込み 申込 締め切り 期限 期間 注意事項 留意事項 概略 全体像 仕組み 流れ 効果 "
    "成果 実績 比較 分析 調査 測定 計画 提案 依頼 報告 お知らせ ご案内 案内 概況 "
    "結び おわり 終わり あとがき まえがき 序論 本論 緒言 背景と目的 利点 欠点 長所 短所 "
    "前提条件 動作環境 必要なもの インストール セットアップ トラブルシューティング ライセンス 関連 "
    "関連資料 関連項目 参照 出典 注 脚注 当番 本番 順番 定番 一番 番号 係 "
    "変更 再現 再現手順 決まり 道具 限界 命名 スクリプト チェックポイント 修正 不具合 動作 期待する動作 "
    "実際の動作 回避策 移行 後片付け 片付け 後始末 引き継ぎ 切り戻し "
    # 文書の題によく使う語
    "資料 記録 メモ ノート 日報 週報 月報 議事録 手順書 仕様書 提案書 企画書 説明書 "
    "マニュアル ガイド 告知 通知 連絡 規約 規程 日記 雑記 覚え書き 備忘録 下書き 草稿 "
    "原稿 索引 用語集 年表 略歴 経歴 自己紹介 紹介 プロフィール 挨拶 あいさつ お願い "
    "お詫び おわび ご報告 ご連絡 ご依頼 ご提案 募集 求人 告示 公告 通達 時系列 経過 "
    "タイムライン あらすじ 登場人物 配役 見出し 本文 題名 題 タイトル 件名 "
).split())
_LABEL_NUMBERING = _V220Lazy(r"^(?:[0-9０-９]+[.)．）]|[（(][0-9０-９]+[)）]|[①-⑳]|第[0-9０-９一二三四五六七八九十]+[章節部回条])")
_LABEL_MARKS = "「『“\"（("
# 漢字と仮名でない字（伏せる前の行から、ラベルになりうる字だけを残すのに使う。漢字の範囲の正規表現はこの1つだけにする）
_LABEL_ASCII = _V220Lazy(r"[A-Za-z0-9０-９Ａ-Ｚａ-ｚ]")
_LABEL_NOT_JAPANESE = _V220Lazy(r"[^ぁ-んァ-ヴー一-龥々〆ヵヶ]+")
_LABEL_ENDINGS = ("の横", "のそば", "係", "番")
# 「関係」「番号」などと、宛名や人の呼び方（田中様、各位、御中）で終わる語はラベルにしない
_LABEL_NOT_ENDINGS = ("関係", "連係", "一番", "二番", "順番", "番号", "様", "さま", "殿", "各位", "御中", "さん", "くん", "ちゃん",
                      "先生", "氏")
# ラベルを見るのは、本文（その行のほかの文字）がこの字数以上ある文書だけ（本文がほとんどない文書では、語が本文に出てこないことが
# 比喩の手掛かりにならない）
_LABEL_MIN_BODY = 60
# 語と語を区切る記号（設計 — 実装、確認・修正、手順：準備）。見出しの中にあれば一語のラベルではない
_LABEL_SEPARATED = _V220Lazy(r"[^\s—―─━・/／:：、，,|｜~〜\-–]\s*[\s—―─━・/／:：、，,|｜~〜\-–]+\s*[^\s—―─━・/／:：、，,|｜~〜\-–]")
# 一語の近似: 漢字やカタカナのあとに助詞か「な」（の、と、や、を、に、が、は、で、へ、も、な）が続かず、
# 動詞や形容詞が名詞を修飾する形（使った技術、新しい道具）も、「から」「まで」などの句も、動詞で終わる形（いつ読むか）もないこと。
# 正規表現にすると漢字の範囲の字の組を組むのに時間がかかる（CLI の起動が遅くなる）ので、字ごとに調べる
_LABEL_AFTER_NOUN = "のとやをにがはでへもな"
_LABEL_ATTRIBUTIVE = "たるいうくすつむぶぐだ"
_LABEL_ANYWHERE = "のをがへ"
_LABEL_BETWEEN = "とやにでは"
_LABEL_VERB_END = "うくすつぬむぶぐる"
# 名前の語で終わるふつうの見出し（変更内容、確認方法、受信処理、冪等性、障害報告書）。「〜方」は仮名のあと（作り方、示し方）だけ
_LABEL_ABSTRACT_ENDINGS = (
    "性", "化", "さ", "み", "率", "量", "数", "値", "額", "費", "報", "処理", "方法", "方式", "内容", "制御", "報告", "報告書", "書",
    "事項", "事象", "一覧", "手順", "管理", "機能", "対応", "検証", "確認", "結果", "状況", "計画", "分析", "調査", "設計", "仕様",
    "要件", "概要", "方針", "表", "図", "例", "編", "章", "版", "案", "論", "法", "点", "策", "順", "式", "型", "層", "群", "集", "録",
    "記", "票", "欄", "項目", "条件", "基準", "形式", "構成", "構造", "一覧表", "履歴", "環境", "作業", "操作", "画面", "設定", "対象",
    "範囲", "期間", "日程", "体制", "役割", "担当", "権限", "規則", "ルール", "ポリシー", "ガイド",
)


def _v220_kanji(char):
    return "一" <= char <= "龥" or char in "々〆ヵヶ"


def _v220_katakana(char):
    return "ァ" <= char <= "ヴ" or char == "ー"


def _v220_hiragana(char):
    return "ぁ" <= char <= "ん"


def _v220_word_char(char):
    """漢字かカタカナ（長音を除く）。"""
    return _v220_kanji(char) or "ァ" <= char <= "ヴ"


def _v220_alnum(char):
    return (char.isascii() and char.isalnum()) or "０" <= char <= "９" or "Ａ" <= char <= "Ｚ" or "ａ" <= char <= "ｚ"


def _label_is_phrase(label):
    """ラベルが一語でなく句か（助詞、名詞を修飾する形、から・まで・より、動詞で終わる形）。"""
    if any(char in _LABEL_ANYWHERE for char in label) or "から" in label or "まで" in label or "より" in label:
        return True
    if label.endswith("か"):
        return True
    length = len(label)
    for index in range(1, length):
        char = label[index]
        before = label[index - 1]
        if char in _LABEL_AFTER_NOUN and (_v220_kanji(before) or _v220_katakana(before)):
            return True
        if char in _LABEL_BETWEEN and index + 1 < length and _v220_word_char(label[index + 1]):
            return True
        if _v220_hiragana(char) and not _v220_hiragana(before) and (_v220_kanji(before) or _v220_katakana(before)):
            end = index
            while end < length and _v220_hiragana(label[end]):
                end += 1
            if end < length and _v220_word_char(label[end]) and label[end - 1] in _LABEL_ATTRIBUTIVE:
                return True
    if label[-1] in _LABEL_VERB_END:
        index = length - 2
        while index >= 0 and _v220_hiragana(label[index]):
            index -= 1
        if index >= 0 and _v220_kanji(label[index]):
            return True
    # 動詞の終止形＋「こと」（守ること、いつも守ること）も句
    if length > 2 and label.endswith("こと") and label[-3] in _LABEL_VERB_END:
        return True
    return False


def _label_kanji_runs(text):
    """漢字の続き（2字以上）とカタカナの続き（2字以上）。"""
    runs = []
    current = ""
    kind = None
    for char in text + " ":
        now = "k" if _v220_kanji(char) else "t" if _v220_katakana(char) else None
        if now == kind and now is not None:
            current += char
            continue
        if kind is not None and len(current) >= 2:
            runs.append((kind, current))
        current, kind = (char, now) if now is not None else ("", None)
    return runs


# katakana_term と thin_evaluation の一覧（references/lists/ の隣の一覧を読む。ないとき、読めないときは内蔵の一覧）
_V220_BUILTIN_LISTS = {
    "katakana-terms": tuple((
        "マイルストーン シナジー ソリューション エンゲージメント プラットフォーム コミットメント アライメント ナレッジ イニシアチブ バリュー スキーム インサイト エコシステム ケイパビリティ "
        "レバレッジ オポチュニティ ステークホルダー コンセンサス ロードマップ ベストプラクティス イノベーション トランスフォーメーション エクスペリエンス カスタマージャーニー タッチポイント "
        "モメンタム コアコンピタンス プレゼンス ウェルビーイング パーパス "
    ).split()),
    "thin-evaluation": (
        ("座り心地", "(?:快適|よい|良い|いい|抜群)"),
        ("使い心地", "(?:よい|良い|いい|快適|抜群)"),
        ("書き心地", "(?:なめらか|滑らか|よい|良い|いい|抜群)"),
        ("寝心地", "(?:よい|良い|いい|快適|抜群)"),
        ("履き心地", "(?:よい|良い|いい|快適|抜群)"),
        ("着心地", "(?:よい|良い|いい|快適|抜群)"),
        ("乗り心地", "(?:快適|よい|良い|いい|抜群)"),
        ("居心地", "(?:よい|良い|いい|快適|抜群)"),
        ("肌触り", "(?:心地よい|心地良い|よい|良い|いい|なめらか|滑らか|抜群)"),
        ("手触り", "(?:心地よい|心地良い|よい|良い|いい|なめらか|滑らか|抜群)"),
        ("質感", "(?:上質|よい|良い|いい|高い|抜群)"),
        ("使い勝手", "(?:よい|良い|いい|抜群)"),
        ("手軽さ", "(?:抜群|魅力)"),
        ("打鍵感", "(?:心地よい|心地良い|よい|良い|いい|快適|抜群)"),
        ("装着感", "(?:快適|よい|良い|いい|抜群)"),
        ("仕上がり", "(?:美しい|きれい|綺麗|上質|抜群)"),
        ("味わい", "(?:深い|豊か|格別)"),
        ("香り", "(?:豊か|よい|良い|いい|格別)"),
        ("操作性", "(?:高い|優れてい(?:ます|る)|よい|良い|抜群)"),
        ("視認性", "(?:高い|優れてい(?:ます|る)|よい|良い|抜群)"),
        ("利便性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("快適性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("安定性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("耐久性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("携帯性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("静音性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("保温性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("信頼性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("拡張性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("保守性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("可読性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("機能性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("デザイン性", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("品質", "(?:高い|優れてい(?:ます|る)|抜群)"),
        ("性能", "(?:高い|優れてい(?:ます|る)|抜群)"),
    ),
}
_V220_LIST_CACHE = {}
# 一覧のファイルがあるのに読めなかった理由（なければ None）。lint の出力には出さない（diff の _LIST_PROBLEMS と同じ扱い）
_V220_LIST_PROBLEMS = {}
_V220_LIST_ABSENT = (FileNotFoundError, NotADirectoryError)


def _v220_parse_list(text, pattern=False):
    """一覧のファイルの中身を読む（yomiyasu_diff.parse_list と同じ書き方）。空行と「#」で始まる行は読み飛ばす。
    正規表現の誤りはここでは確かめない（組むのに時間がかかるので、初めて使うときに _v220_thin_match が確かめる）。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    out = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if pattern:
            name, _, regex = line.partition("\t")
            if not name.strip() or not regex.strip() or "\t" in regex.strip():
                shown = line if len(line) <= 40 else line[:40] + "…"
                raise ValueError("「名詞<TAB>述語の正規表現」の形でない行があります: " + shown)
            out.append((name.strip(), regex.strip()))
        else:
            out.append(line.strip())
    return tuple(out)


def _v220_load_list(name):
    """一覧を読む（yomiyasu_diff._load_list と同じ読み方）。(項目のタプル, 出どころ) を返す。出どころは
    "references/lists/<名前>.txt" か "builtin"。スクリプトの隣の ../references/lists/<名前>.txt を utf-8-sig で読む。
    ないときは何も言わずに内蔵の一覧で動き、読めないとき（UTF-8 でない、書き方の誤り、開けない）は、理由を
    _V220_LIST_PROBLEMS に残して内蔵の一覧で動く。thin-evaluation の正規表現の誤りは、初めて使うときに見つけて同じようにする。"""
    if name in _V220_LIST_CACHE:
        return _V220_LIST_CACHE[name]
    pattern = name == "thin-evaluation"
    items, problem = None, None
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "references", "lists", name + ".txt")
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except _V220_LIST_ABSENT:
        data = None
    except OSError as error:
        data, problem = None, "ファイルを開けません（{}）".format(getattr(error, "strerror", None) or error)
    if data is not None:
        try:
            items = _v220_parse_list(data.decode("utf-8-sig"), pattern=pattern)
        except UnicodeDecodeError:
            problem = "UTF-8 として読めません"
        except ValueError as error:
            problem = str(error)
    if items is None:
        result = (tuple(_V220_BUILTIN_LISTS[name]), "builtin")
    else:
        result = (items, "references/lists/{}.txt".format(name))
    _V220_LIST_CACHE[name] = result
    _V220_LIST_PROBLEMS[name] = problem
    return result


# 文書全体に一度だけ当てる手掛かりの語（型1の動詞の頭、型2の名詞、型3の句の頭）。katakana_term と thin_evaluation の一覧の語も足す。
# どの規則の正規表現も、当たるときはこのどれかを含む（試験で守る）
_V220_TRIGGER_LITERALS = tuple((
    # 型1の動詞
    "拾う 拾い 拾わ 拾っ 拾え 拾お 引く 引い 引か 引き 引け 通す 通し 通さ 通る 通り "
    "通ら 通っ 通れ 効く 効き 効か 効い 効け 響く 響き 響か 響い 響け 足す 足し 足さ "
    "足せ 抱え 見張 食う 食い 食わ 食っ 食べ 受け止め 飲み込 呑み込 覚え 忘れ 投げ 叩く "
    "叩き 叩か 叩い 話す 話し 話さ 話せ 喋 助け 手伝 気にす 気にし 気にせ 気にさ 怒る "
    "怒り 怒ら 怒っ 文句を "
    # 型2の名詞（「口」で受け口、入口、出口、窓口、裏口、〜向けの口を拾う）
    "口 玄関 関所 関門 抜け道 裏道 通り道 合流 防波堤 砦 先 "
    # 型3の句（足すものがない、価値を足す、失効が効く、〜から効く は型1の動詞の頭で拾う）
    "秒を取 分を取 時間を取 場所を取 ステップを取 意味を 針を 所有権を持 違いを作 手を伸ば ライブに "
    "同じページ 水を試 透明に ループを ループに 駆動され 配達 大きな絵 インパクトを持 決定を作 "
    "質問を持 真剣に取 目を保 テーブルに置 テーブルに載 テーブルに乗 テーブルに出 次のレベルに 機械 ターン "
).split())
_V220_TYPE1_END = _V220_TRIGGER_LITERALS.index("口")
_V220_TYPE2_END = _V220_TRIGGER_LITERALS.index("秒を取")


def _v220_literal_re(literals):
    """文字列のどれかに当たる正規表現。先頭の字ごとにまとめる（re は分かれ道を1つずつ試すので、同じ字で始まる語を
    1つの分かれ道にまとめると、その字の位置で試す数が減る）。長い語を先に試す。"""
    groups = {}
    for literal in sorted(set(literals), key=len, reverse=True):
        if literal:
            groups.setdefault(literal[0], []).append(literal[1:])
    parts = []
    for head, tails in groups.items():
        if "" in tails:
            tails = [tail for tail in tails if tail] + [""]
        if len(tails) == 1:
            parts.append(re.escape(head) + re.escape(tails[0]))
        else:
            parts.append(re.escape(head) + "(?:" + "|".join(map(re.escape, tails)) + ")")
    return _V220Lazy("|".join(parts))


# 文ごとに、型の手掛かりの語があるかを先に見る（ない文は型の正規表現を当てない）
_CALQUE_VERB_STEMS = frozenset(stem for stem, _, _ in _CALQUE_VERB_EACH)     # どれも1字
_CALQUE_PLACE_HEAD = _v220_literal_re(_V220_TRIGGER_LITERALS[_V220_TYPE1_END:_V220_TYPE2_END])
_CALQUE_PHRASE_HEAD = _v220_literal_re(_V220_TRIGGER_LITERALS[_V220_TYPE2_END:] + ("効", "足す", "足し", "響", "引", "通"))

# thin_evaluation: 文が「（20字以下の読点のない前置き）名詞（が|は|も）（程度の副詞）述語（です|だ など）。」の形
_THIN_PREFIX_MAX = 20
_THIN_ADVERB = r"(?:とても|非常に|大変|たいへん|すごく|かなり|十分に?|抜群に|格段に|より|さらに|一段と)?"
_THIN_TAIL = r"(?:です|でした|だ|だった|である|でございます|ですね|ですよ)?"
_V220_COMPILED = {}


def _v220_patterns():
    """一覧から組んだ正規表現（katakana_term、thin_evaluation、文書全体の手掛かり）。一覧ごとに1回だけ組む。"""
    katakana, katakana_source = _v220_load_list("katakana-terms")
    thin, thin_source = _v220_load_list("thin-evaluation")
    key = (katakana_source, id(katakana), thin_source, id(thin))
    if _V220_COMPILED.get("key") == key:
        return _V220_COMPILED["value"]
    katakana_re = None
    if katakana:
        # 番号や記号を付けた項目の名前（マイルストーン1、マイルストーン B）は、何を指すかが決まっているので外す
        katakana_re = _V220Lazy("(?:" + "|".join(map(re.escape, sorted(set(katakana), key=len, reverse=True)))
                                 + r")(?![ 　]?[0-9０-９A-Za-zＡ-Ｚａ-ｚ])")
    thin_re = None
    nouns = ()
    if thin:
        nouns = tuple(sorted(set(noun for noun, _ in thin), key=len, reverse=True))
        body = "|".join("(?:{}(?:が|は|も){}(?:{}))".format(re.escape(noun), _THIN_ADVERB, predicate)
                        for noun, predicate in thin)
        thin_re = _V220Lazy(r"^(?P<prefix>[^、，,]{0," + str(_THIN_PREFIX_MAX) + r"}?)(?P<body>" + body + r")" + _THIN_TAIL
                             + r"[。．！!]*$")
    # 手掛かりの語は、先読みや後読み、捕まえる組のない文字列だけをつなぐ（re が先頭の字の候補で位置を飛ばせて速い）。
    # 先頭の平仮名は外し、漢字で始まる語とカタカナで始まる語を別の正規表現にする（1つにまとめると、よく出る字の位置で
    # すべての語を試すので遅い）
    literals = set(re.sub(r"^[ぁ-ん]+", "", literal) for literal in _V220_TRIGGER_LITERALS + tuple(katakana) + nouns)
    literals.discard("")
    trigger = tuple(_v220_literal_re(group) for group in (
        [literal for literal in literals if not ("ァ" <= literal[0] <= "ヴ" or literal[0] == "ー")],
        [literal for literal in literals if "ァ" <= literal[0] <= "ヴ" or literal[0] == "ー"]) if group)
    value = (katakana_re, thin_re, nouns, trigger)
    _V220_COMPILED["thin_nouns"] = _v220_literal_re(nouns) if nouns else None
    _V220_COMPILED["key"] = key
    _V220_COMPILED["value"] = value
    return value


def _v220_thin_match(sentence):
    """thin_evaluation の正規表現を文に当てる。一覧のファイルの正規表現に誤りがあれば、理由を残して内蔵の一覧で当てる。"""
    thin_re = _v220_patterns()[1]
    try:
        return thin_re.match(sentence)
    except re.error as error:
        _V220_LIST_CACHE["thin-evaluation"] = (tuple(_V220_BUILTIN_LISTS["thin-evaluation"]), "builtin")
        _V220_LIST_PROBLEMS["thin-evaluation"] = "正規表現の誤り（{}）".format(error)
        return _v220_patterns()[1].match(sentence)


def _v220_scan_text(analysis, line_no):
    """新しい語の規則が見る行の文字。見える文字から、カギ括弧と引用符の中、英数字の識別子を空白にする。"""
    visible = _prose_visible_text(analysis, line_no).replace("__", "").replace("*", "")
    if "「" in visible or "『" in visible or "[" in visible:
        visible = _mask_quoted_segments_sparse(visible)
    if "“" in visible or '"' in visible or "‘" in visible:
        visible = _V220_QUOTES.sub(lambda m: " " * len(m.group()), visible)
    return _V220_IDENTIFIER.sub(lambda m: " " * len(m.group()), visible)


def _v220_noun_start(text, position):
    """position の字が漢字かカタカナか英字か。"""
    if position >= len(text):
        return False
    char = text[position]
    return _v220_kanji(char) or _v220_katakana(char) or (char.isascii() and char.isalpha())


def _v220_has_verb_stem(text):
    """型1の動詞の語幹の字があるか。"""
    return not _CALQUE_VERB_STEMS.isdisjoint(text)


def _calque_subject_end(sentence, limit):
    """limit より前で最後の、機械やシステムの語が主語の「は」「が」「も」「こそ」の終わりの位置（なければ -1）。
    主語の語のあとに漢字やカタカナが続いて、人や組織の語で終わるとき（サーバー管理者は）は主語にしない。"""
    last = -1
    for subject in _CALQUE_SUBJECT_WORD.finditer(sentence, 0, limit):
        end = subject.end()
        for extra in range(_CALQUE_SUBJECT_EXT + 1):
            position = end + extra
            if position >= limit:
                break
            particle = next((item for item in _CALQUE_SUBJECT_PARTICLES if sentence.startswith(item, position)), None)
            if particle is not None:
                if position + len(particle) <= limit and not _CALQUE_PERSON_EXT.search(sentence[end:position]):
                    last = position + len(particle)
                break
            char = sentence[position]
            if not (_v220_kanji(char) or _v220_katakana(char) or (char.isascii() and char.isalnum())):
                break
    return last


def _calque_type1(sentence, words):
    """型1に当たれば True（当たった動詞の辞書の形を words に足す）。"""
    if not _v220_has_verb_stem(sentence) or not _CALQUE_SUBJECT_WORD.search(sentence):
        return False
    found = False
    established = None
    matches = sorted((match.start(), index, match) for index, (stem, _, pattern) in enumerate(_CALQUE_VERB_EACH)
                     if stem in sentence for match in pattern.finditer(sentence))
    covered = -1
    for start, index, match in matches:
        if start < covered:
            continue    # 同じ所に当たった別の動詞（引き込む と 引く）は、表の前のほうだけを数える
        if start and _v220_kanji(sentence[start - 1]) and _CALQUE_VERB_EACH[index][1] not in _CALQUE_COMPOUND_OK \
                and not match.group().startswith("食べ"):
            continue    # 漢字の熟語の一部（不足し、共通す、電話し、有効、朝食）
        covered = match.end()
        subject_end = _calque_subject_end(sentence, start)
        if subject_end < 0 or start - subject_end > _CALQUE_SUBJECT_REACH \
                or _CALQUE_SUBJECT_BREAK.search(sentence, subject_end, start):
            continue
        if any(person.end() > subject_end for person in _CALQUE_PERSON_SUBJECT.finditer(sentence, subject_end, start)):
            continue
        if established is None:
            established = [m.span() for m in _CALQUE_ESTABLISHED_TYPE1_RE.finditer(sentence)]
        if any(left <= start < right for left, right in established):
            continue
        kana = _CALQUE_KANA_RUN.match(sentence, match.end()).group()
        if (match.group() + kana).endswith(_CALQUE_ATTRIBUTIVE_END) \
                and _v220_noun_start(sentence, match.end() + len(kana)):
            continue    # 名詞を修飾する形（拾った通知、話した内容）
        if kana.startswith(_CALQUE_REQUEST):
            continue    # 読み手に頼む形（1行を足してください）。動作をするのは読み手
        words.append(_CALQUE_VERB_EACH[index][1])
        found = True
    return found


def _v220_noun_or_alnum(text, position):
    return 0 <= position < len(text) and (_v220_kanji(text[position]) or _v220_katakana(text[position])
                                          or _v220_alnum(text[position]))


def _calque_saki_spans(sentence):
    """「〜先」の当たり（_CALQUE_SAKI_KANJI の語か、漢字1字と連用形の送り仮名のあとの「先」）の (始め, 終わり)。"""
    spans = []
    position = sentence.find("先")
    while position >= 0:
        end = position + 1
        if position and not (end < len(sentence) and (_v220_kanji(sentence[end]) or _v220_katakana(sentence[end]))):
            start = None
            for word in _CALQUE_SAKI_KANJI:
                if sentence.startswith(word, position - len(word)) and position >= len(word):
                    start = position - len(word)
                    break
            if start is None and sentence[position - 1] in _CALQUE_SAKI_TAIL:
                if position >= 2 and _v220_kanji(sentence[position - 2]):
                    start = position - 2
                elif (position >= 3 and _v220_hiragana(sentence[position - 2]) and _v220_kanji(sentence[position - 3])
                      and sentence[position - 2:position] != "より"):
                    start = position - 3
            if start is not None and not _v220_noun_or_alnum(sentence, start - 1):
                spans.append((start, end))
        position = sentence.find("先", end)
    return spans


def _calque_has_org(sentence):
    """文に組織の名前（総務部、情報システム課、サポートセンター）があるか。"""
    if any(word in sentence for word in _CALQUE_ORG_WORDS):
        return True
    for index, char in enumerate(sentence):
        if (char in _CALQUE_ORG_SUFFIXES and index and (_v220_kanji(sentence[index - 1]) or _v220_katakana(sentence[index - 1]))
                and not (index + 1 < len(sentence) and _v220_kanji(sentence[index + 1]))):
            return True
    return False


def _v220_doc_tech(text):
    """技術の文書か（_CALQUE_TECH の語が _CALQUE_DOC_TECH_MIN 種類以上）。"""
    return len(set(_CALQUE_TECH.findall(text))) >= _CALQUE_DOC_TECH_MIN


def _calque_type2(sentence, words, doc_tech=False):
    """型2に当たれば True（当たった名詞を words に足す）。doc_tech は技術の文書か（入口と出口の拾い方に使う）。"""
    if not _CALQUE_PLACE_HEAD.search(sentence):
        return False
    found = False
    tech = None
    for match in _CALQUE_PLACE_ALWAYS.finditer(sentence):
        if match.group() != "受け口" and _v220_noun_start(sentence, match.end()):
            continue
        if not match.group().endswith(("受け口", "の口")):
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech:
                continue
        words.append("受け口" if match.group() == "受け口" else "口")
        found = True
    for start, end in _calque_saki_spans(sentence):
        word = sentence[start:end]
        before = sentence[max(0, start - 8):end]
        if _CALQUE_SAKI_TIME.search(word) or any(before.endswith(item) for item in _CALQUE_ESTABLISHED_SAKI):
            continue
        # 一覧の着地先などのほかは、技術の語のある文の「〜先」だけを見る（旅行の立ち寄り先、父の働き先は見ない）
        if not any(word.endswith(kanji + "先") for kanji in _CALQUE_SAKI_KANJI):
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech:
                continue
        words.append(word)
        found = True
    end_is_noun = _v220_noun_start
    for match in _CALQUE_PLACE_CONTEXT.finditer(sentence):
        word = match.group()
        if word != "の口" and end_is_noun(sentence, match.end()):
            continue
        before = sentence[max(0, match.start() - 10):match.start()]
        if word == "の口":
            if _CALQUE_MOUTH_REAL.search(sentence[max(0, match.start() - 6):match.end()]) \
                    or _CALQUE_MOUTH_IDIOM.match(sentence, match.start() + 1):
                continue
            if before.endswith(("向け", "用")):
                continue    # _CALQUE_PLACE_ALWAYS で数えた
            word = "口"
        elif _CALQUE_PLACE_REAL.search(before):
            continue
        if word == "窓口":
            if (_CALQUE_PLACE_ORG.search(before) or not _CALQUE_CODE.search(sentence)
                    or _calque_has_org(sentence)):
                continue
        else:
            if tech is None:
                tech = bool(_CALQUE_TECH.search(sentence))
            if not tech and not (doc_tech and word in ("入口", "入り口", "出口")
                                 and _CALQUE_ENTRY_FLOW.match(sentence, match.end())):
                continue
        words.append(word)
        found = True
    return found


def _calque_type3(sentence, words):
    """型3に当たれば True（当たった句の名前を words に足す）。"""
    if not _CALQUE_PHRASE_HEAD.search(sentence):
        return False
    found = False
    type1_here = None
    for match in _CALQUE_PHRASE.finditer(sentence):
        name = next((name for name, each in _CALQUE_PHRASE_EACH if each.match(sentence, match.start())), match.group())
        if name in (_CALQUE_PHRASE_KIKU, "ときに効く") and _KIKU_RE["context"].search(sentence):
            continue
        if name == "ときに効く" and (_CALQUE_ESTABLISHED_TYPE1_RE.search(sentence)
                                    or not (_CALQUE_KIKU_DECIDE.search(sentence) or _CALQUE_TECH.search(sentence))):
            continue
        if name == "に響く" and (_CALQUE_HIBIKU_LITERAL.search(sentence)
                               or (match.group().startswith(_CALQUE_HIBIKU_COST) and not _CALQUE_TECH.search(sentence))):
            continue
        if name == "機械どうし" and not _CALQUE_MACHINE_TALK.search(sentence):
            continue
        if name == "書き込みが通る" and match.group().startswith("アクセス") and not _CALQUE_TECH.search(sentence):
            continue
        # 型1が同じ文で同じ動詞を当てたときは、対応表から足した形を重ねない（このキャッシュは、応答の速さに響きます）。
        # 同じ行のほかの文の型1とは比べない
        verb = _CALQUE_PHRASE_VERB.get(name)
        if verb:
            if type1_here is None:
                type1_here = []
                _calque_type1(sentence, type1_here)
            if verb in type1_here:
                continue
        # 「ターン」は、ゲームの手番でなく、指示や会話、モデルの呼び出しの話のときだけ
        if name == "ターン" and (not _CALQUE_TURN_CONTEXT.search(sentence) or _CALQUE_TURN_GAME.search(sentence)):
            continue
        words.append(name)
        found = True
    return found


def _label_text(analysis, row, scan):
    """見出しか1行目のラベル（記号と番号を除いた文字。英数字は残す）。"""
    text = scan.strip()
    if row["kind"] == "heading":
        text = text.strip("#").strip()
    text = _LABEL_NUMBERING.sub("", text).strip()
    return "".join(char for char in text if _v220_kanji(char) or _v220_katakana(char) or _v220_hiragana(char)
                   or _v220_alnum(char))


def _label_shape(label):
    """ラベルの形の条件（8字以下で、よく使う節の名前でなく、「〜の横」「〜のそば」「〜係」「〜番」で終わるか一語）。"""
    if not label or len(label) < 2 or len(label) > _LABEL_MAX or label in _LABEL_COMMON:
        return False
    if any(_v220_alnum(char) for char in label) or label.endswith(_LABEL_NOT_ENDINGS):
        return False
    run = longest = 0
    for char in label:
        run = run + 1 if _v220_hiragana(char) else 0
        longest = max(longest, run)
    if longest >= 4 or not any(_v220_word_char(char) for char in label):
        return False
    if label.endswith(_LABEL_ENDINGS):
        return True
    if label.endswith(_LABEL_ABSTRACT_ENDINGS) or (label.endswith("方") and len(label) > 1 and _v220_hiragana(label[-2])):
        return False
    return not _label_is_phrase(label)


def _label_may_fit(row):
    """見出しか1行目が、伏せる前の文字でラベルになりうるか（長い見出しと、ふつうの見出しを先に飛ばす）。
    伏せる所（識別子、コード）は英数字か記号なので、漢字と仮名だけを残した文字で見る。"""
    raw = row["raw"]
    quick = _LABEL_NOT_JAPANESE.sub("", raw)
    if not 2 <= len(quick) <= _LABEL_MAX or any(mark in raw for mark in _LABEL_MARKS):
        return False    # 台詞や引用、作品の名前、括弧の補足を含む行は、一語のラベルではない
    return _label_shape(quick)


def _metaphor_label(analysis, row, scan):
    """metaphor_label のラベルを返す（当たらなければ None）。"""
    if row["kind"] not in ("heading", "paragraph"):
        return None     # 1行目が表や箇条書きのときは見ない
    if row["kind"] != "heading" and scan.rstrip().endswith(("。", "．", "！", "？", "!", "?")):
        return None     # 文として終わる1行目はラベルとみなさない
    if any(mark in row["raw"] for mark in _LABEL_MARKS):
        return None
    content = _LABEL_NUMBERING.sub("", scan.strip().strip("#").strip()).strip()
    if _LABEL_SEPARATED.search(content):
        return None
    # 番号のほかに英数字を含む見出し（v1.1.2 チェックポイント）は、版や名前を書いた見出しで、一語の比喩ではない
    if _LABEL_ASCII.search(_LABEL_NUMBERING.sub("", row["raw"].strip().strip("#").strip())):
        return None
    if len("".join(analysis["text"].split())) - len("".join(row["raw"].split())) < _LABEL_MIN_BODY:
        return None
    label = _label_text(analysis, row, scan)
    if not _label_shape(label):
        return None
    text = analysis["text"]
    raw = row["raw"]
    pieces = [label]
    stem = label
    for ending in _LABEL_ENDINGS:
        if stem.endswith(ending):
            stem = stem[:-len(ending)]
            break
    # ラベルの漢字の続きの2字（とカタカナの続き）。どれかが本文のほかの行に出れば、本文の話題の語とみなして出さない
    for kind, run in _label_kanji_runs(stem):
        if kind == "t":
            pieces.append(run)
        else:
            pieces.extend(run[index:index + 2] for index in range(len(run) - 1))
    if any(text.count(piece) > raw.count(piece) for piece in dict.fromkeys(pieces)):
        return None
    if not label.endswith(_LABEL_ENDINGS):
        # 一語のラベルの漢字が、どれも本文のほかの所に出る（文体の節に「文」と「体」が出る）なら、本文の話題の語とみなす
        kanji = [char for char in label if _v220_kanji(char)]
        if len(kanji) >= 2 and all(text.count(char) > raw.count(char) for char in kanji):
            return None
    return label


def _v220_word_findings(analysis):
    """calque、metaphor_label、katakana_term、thin_evaluation の候補。

    既存の規則の候補は analysis["_findings"] から読む（同じ行に metaphor_verb があれば calque を出さない。
    translated_term があれば型3を出さない）。"""
    rows = analysis["lines"]
    if not rows:
        return []
    katakana_re, thin_re, thin_nouns, trigger = _v220_patterns()
    thin_noun_re = _V220_COMPILED.get("thin_nouns")
    text = analysis["text"]
    starts = None
    candidate_lines = set()
    for pattern in trigger:
        for match in pattern.finditer(text):
            if starts is None:
                starts = [row["start"] for row in rows]
            candidate_lines.add(bisect_right(starts, match.start()))
    # ラベルを見る行: 見出しの行と、文書の1行目（frontmatter と空行を除く）。伏せる前の文字でも長すぎる行は先に外す
    label_lines = set()
    for block in analysis["blocks"]:
        if block["kind"] == "heading":
            label_lines.update(row["line"] for row in block["lines"] if _label_may_fit(row))
    for row in rows:
        if row["kind"] in ("frontmatter", "blank"):
            continue
        if _label_may_fit(row):
            label_lines.add(row["line"])
        break
    if not candidate_lines and not label_lines:
        return []
    blocked_all = set()
    blocked_type3 = set()
    for finding in analysis.get("_findings", ()):
        if finding["rule"] == "metaphor_verb":
            blocked_all.add(finding["line"])
        elif finding["rule"] == "translated_term":
            blocked_type3.add(finding["line"])
    out = []
    doc_tech = None
    for line_no in sorted(candidate_lines | label_lines):
        row = rows[line_no - 1]
        if row["kind"] not in ("paragraph", "list", "heading", "table") or row["quote_depth"]:
            continue
        scan = _v220_scan_text(analysis, line_no)
        if not scan.strip():
            continue
        snippet = row["raw"].strip()
        label = _metaphor_label(analysis, row, scan) if line_no in label_lines else None
        if label is not None:
            out.append({"rule": "metaphor_label", "line": line_no, "severity": "info",
                        "message": "見出しか1行目の比喩のラベル" + _V220_MESSAGE_TAIL, "snippet": snippet,
                        "_words": (label,)})
        if line_no not in candidate_lines:
            continue
        # 伏せたあとの行に、規則ごとの手掛かりの語があるかを先に見る
        finders = []
        if line_no not in blocked_all:
            if _v220_has_verb_stem(scan) and _CALQUE_SUBJECT_WORD.search(scan):
                finders.append((1, _calque_type1))
            if label is None and _CALQUE_PLACE_HEAD.search(scan):
                if doc_tech is None:
                    doc_tech = _v220_doc_tech(text)
                # 見出しのラベルと同じ行の型2は metaphor_label だけを出す
                finders.append((2, functools.partial(_calque_type2, doc_tech=doc_tech)))
            if line_no not in blocked_type3 and _CALQUE_PHRASE_HEAD.search(scan):
                finders.append((3, _calque_type3))
        thin_possible = thin_re is not None and thin_noun_re.search(scan) is not None
        sentences = ()
        if finders or thin_possible:
            sentences = [part for part in (piece.strip() for piece in _V220_SENTENCE.findall(scan)) if part]
        types = []
        calque_words = []
        word_types = []
        for number, finder in finders:
            before = len(calque_words)
            if any([finder(sentence, calque_words) for sentence in sentences]):
                types.append(number)
                word_types.extend((word, number) for word in calque_words[before:])
        if types:
            out.append({"rule": "calque", "line": line_no, "severity": "info",
                        "message": _calque_message(types, word_types), "snippet": snippet,
                        "_words": tuple(dict.fromkeys(calque_words)), "_word_types": tuple(word_types)})
        if katakana_re is not None:
            katakana_words = katakana_re.findall(scan)
            if katakana_words:
                out.append({"rule": "katakana_term", "line": line_no, "severity": "info",
                            "message": "意味の薄くなりやすいカタカナ語" + _V220_MESSAGE_TAIL, "snippet": snippet,
                            "_words": tuple(dict.fromkeys(katakana_words))})
        if thin_possible:
            thin_words = []
            for sentence in sentences:
                match = _v220_thin_match(sentence)
                if match:
                    body = match.group("body")
                    thin_words.append(next((noun for noun in thin_nouns if body.startswith(noun)), body))
            if thin_words:
                out.append({"rule": "thin_evaluation", "line": line_no, "severity": "info",
                            "message": "中身の薄い評価の文" + _V220_MESSAGE_TAIL, "snippet": snippet,
                            "_words": tuple(dict.fromkeys(thin_words))})
    return out


def _calque_message(types, word_types):
    """calque の message。1行に1件なので、当たった言い方を並べる（同じ行の2つ目を読み落とさないため。置き換え先の語は出さない）。"""
    hit = tuple(dict.fromkeys(word for word, _ in word_types))
    shown = "。当たった言い方: " + "、".join(hit) if hit else ""
    return "直訳語（{}{}）{}".format("。".join(_CALQUE_TYPE_NAMES[number] for number in types), shown, _V220_MESSAGE_TAIL)


# 2.2.0 の文の形の規則（say_hedge、copy_comma_noun、bare_verb_chain）。
# 既存の表（_PATTERN_LITERAL_HINTS）とは別に、行ごとに見える文字（_prose_visible_text）を見る。
# カギ括弧、二重カギ括弧、[ ]、引用符の中は伏せる。引用の行、表、コード、frontmatter、HTML は見ない。
_SHAPE_RULE_MESSAGES = {
    "say_hedge": "文末の「と言えるでしょう」の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。推量の「でしょう」は残します。ある区分に当たるかを判断する文（印のないもの）は直しません。",
    "copy_comma_noun": "修飾語と短い名詞の間に読点を打って名詞で終える、キャッチコピーの型の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。",
    "bare_verb_chain": "主語も目的語もない動詞を読点で並べて止める文の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。",
}
# 文書の元の文字で、3つの規則のどれかに当たりうる所（速さのための絞り込み）。当たった行だけを見える文字で調べる。
# 見える文字では「*」「_」が消えるので、読点と句点の前の「*」「_」は許す
_SHAPE_GATE_WORDS = ("えるでしょう",)
_SHAPE_COMMA_GATE = re.compile(
    r"[ないたのうくぐすつぬぶむるか][*_]*、(?:[^、。\n]{1,14}。|[^。\n]{0,30}、[^、。\n]{0,30}[うくぐすつぬぶむる][*_]*。)")
_SHAPE_HEADING_MARK = re.compile(r"^\s*#{1,6}(?:\s+|$)|\s+#+\s*$")
_SHAPE_QUOTE_MARKS = ("「", "『", "[", "“", '"')
_SHAPE_CURLY_QUOTED = re.compile(r"“[^“”]*”|\"[^\"]*\"")
_SHAPE_SENTENCE = re.compile(r"[^。！？!?]+(?:[。！？!?]+|$)")
# 文末の「と言えるでしょう」。問いの「でしょうか」は含めない
_SAY_HEDGE = re.compile(r"(.{0,4})と(?:言|い)えるでしょう[。！!]?$")
# 直前が体言（漢字かカタカナで終わる）なら、ある語に当たるかの判断（「契約と言えるでしょう」）として出さない
_SAY_HEDGE_NOUN_END = re.compile(r"[一-龯々〆ヵヶァ-ヴーｦ-ﾟA-Za-z0-9０-９Ａ-Ｚａ-ｚ]")
# ただし、形容動詞の語幹（「有効」「効果的」など）のあとは評価のぼかしとして出す（「有効と言えるでしょう」）
_SAY_HEDGE_NA_ADJECTIVE = re.compile(r"(?:的|重要|有効|必要|適切|十分|妥当|有用|大切|確実|可能|重大|有益|顕著|明確|"
                                     r"不可欠|理想|最適|容易|困難|安全|安心)$")
# 「〜に当たると言えるでしょう」も、ある区分に当たるかの判断として出さない
_SAY_HEDGE_JUDGE = re.compile(r"(?:に|へ)(?:当た|あた)る(?:と(?:言|い)えるでしょう)|に該当する(?:と(?:言|い)えるでしょう)")
# 「な、」「い、」「た、」「の、」のあとに6字以下の名詞（か名詞＋を）で「。」。名詞は漢字、仮名、英数字だけ
_COPY_COMMA_NOUN = re.compile(r"(?:^|、)([^、]+?[ないたの])、([一-龯々〆ヵヶぁ-ゖァ-ヴーA-Za-z0-9０-９Ａ-Ｚａ-ｚ]{1,7})。$")
# 読点の前の部分に助詞の「を」「は」「が」「で」があれば、修飾語ではなく節とみて出さない（「条件を残した、やや長い出力。」）
_COPY_MODIFIER_PARTICLE = re.compile(r"を|[はがで](?![ぁ-ゖ])")
# 読点の前が感動詞、接続詞、指示語なら出さない（「はい、了解。」「また、今度。」）
_COPY_NOT_MODIFIER = frozenset(("はい", "いいえ", "いい", "また", "まあ", "あの", "その", "この", "どの", "あのね",
                                "ええ", "いや", "おい", "なお", "ただ", "しかし", "ちなみ", "つまり", "さて", "では"))
# 名詞のほうが述語や助詞で終わるなら名詞ではない（「迷った、決めた。」「ある、です。」）。「の」を含む名詞句（「内部の誤り」）も外す
_COPY_I_NOUNS = frozenset(("思い", "想い", "願い", "違い", "匂い", "出会い", "味わい", "祝い", "誓い", "迷い", "笑い", "住まい",
                           "佇まい", "問い", "扱い", "装い", "幸い"))
_COPY_NOUN_NOT = re.compile(r"(?:[るたすだてでねよわかぞぜさうくぐつぬぶむずじ]|ない|ません|しい|たい)$|[はがにでの]")
# 終止形（う段の仮名）か「終止形＋か」で終わる部分
_BARE_VERB_PART = re.compile(r"[一-龯々ぁ-ゖァ-ヴー]*[うくぐすつぬぶむる]か?$")
_BARE_VERB_LAST = re.compile(r"[一-龯々ぁ-ゖァ-ヴー]*[うくぐすつぬぶむる]$")
_BARE_VERB_POLITE = re.compile(r"(?:ます|です|ません)か?$")
# 動詞ではないのに、う段の仮名で終わる部分（「一つ、二つ、三つ。」の数、「楽しく」の形容詞）
_BARE_VERB_NOT_VERB = re.compile(r"(?:^[一二三四五六七八九十百千0-9０-９いくひとふたみよ]+つ|しく)か?$")
# 助詞の「は」「が」「に」: 後ろが平仮名でない（漢字やカタカナの語が続く）ものを助詞とみる。「を」はいつも助詞
_BARE_VERB_PARTICLE = re.compile(r"を|[はがに](?![ぁ-ゖ])")


def _shape_visible_text(analysis, row):
    """形の規則で見る行の文字。見ない行は空の文字列。引用の中身は空白で伏せる。"""
    if row["kind"] not in ("paragraph", "list", "heading") or row["quote_depth"]:
        return ""
    text = _prose_visible_text(analysis, row["line"])
    text = text.replace("__", "").replace("*", "")
    if row["kind"] == "heading":
        text = _SHAPE_HEADING_MARK.sub("", text)
    if any(mark in text for mark in _SHAPE_QUOTE_MARKS):
        text = _mask_quoted_segments(text)
        if "“" in text or '"' in text:
            text = _SHAPE_CURLY_QUOTED.sub(lambda match: " " * len(match.group()), text)
    return text


def _say_hedge_sentence(sentence):
    match = _SAY_HEDGE.search(sentence)
    if not match:
        return False
    head = match.group(1)
    if _SAY_HEDGE_JUDGE.search(sentence):
        return False
    if head and _SAY_HEDGE_NOUN_END.match(head[-1]) and not _SAY_HEDGE_NA_ADJECTIVE.search(head):
        return False
    return True


def _copy_comma_noun_sentence(sentence):
    if len(sentence) > 20 or not sentence.endswith("。"):
        return False
    match = _COPY_COMMA_NOUN.search(sentence)
    if not match:
        return False
    modifier, noun = match.group(1).strip(), match.group(2)
    if noun.endswith("を"):
        noun = noun[:-1]
    if (not noun or len(noun) > 6 or len(modifier) < 2 or modifier in _COPY_NOT_MODIFIER
            or _COPY_MODIFIER_PARTICLE.search(modifier)):
        return False
    # 「暑い、暑い。」「疲れた、眠い。」のように形容詞で終わる文は、名詞で止める型ではない（「い」で終わる名詞は残す）
    if noun.endswith("い") and noun not in _COPY_I_NOUNS:
        return False
    return not _COPY_NOUN_NOT.search(noun)


def _bare_verb_chain_sentence(sentence):
    if len(sentence) > 30 or not sentence.endswith("。"):
        return False
    parts = [part.strip() for part in sentence[:-1].split("、")]
    if len(parts) < 3 or _BARE_VERB_PARTICLE.search(sentence):
        return False
    for part in parts[:-1]:
        if (not _BARE_VERB_PART.fullmatch(part) or _BARE_VERB_POLITE.search(part)
                or _BARE_VERB_NOT_VERB.search(part)):
            return False
    last = parts[-1]
    return (bool(_BARE_VERB_LAST.fullmatch(last)) and not _BARE_VERB_POLITE.search(last)
            and not _BARE_VERB_NOT_VERB.search(last))


def _v220_shape_findings(analysis, findings, doc_type):
    """say_hedge、copy_comma_noun、bare_verb_chain の候補。findings は既存の規則の候補（読むだけ。いまは使わない）。

    1行に同じ規則の候補は1件まで。copy_comma_noun は promo では文書の中で2回目に当たったものから出す。
    中身のない「仕組み」（empty_shikumi）は、推敲の前後の比べで直せた文がなく、仕組みを説明している文を書き換えたので
    2.2.0 には入れなかった。"""
    result = []
    source = analysis["text"]
    positions = [match.start() for match in _SHAPE_COMMA_GATE.finditer(source)]
    for word in _SHAPE_GATE_WORDS:
        position = source.find(word)
        while position >= 0:
            positions.append(position)
            position = source.find(word, position + 1)
    if not positions:
        return result
    rows = analysis["lines"]
    starts = [row["start"] for row in rows]
    indexes = sorted({bisect_right(starts, position) - 1 for position in positions})
    copy_hits = 0
    for index in indexes:
        row = rows[index]
        text = _shape_visible_text(analysis, row)
        if not text:
            continue
        line_no = row["line"]
        found = set()
        for match in _SHAPE_SENTENCE.finditer(text):
            sentence = match.group().strip()
            if not sentence:
                continue
            if "say_hedge" not in found and "える" in sentence and _say_hedge_sentence(sentence):
                found.add("say_hedge")
            if "、" in sentence:
                if _copy_comma_noun_sentence(sentence):
                    copy_hits += 1
                    if doc_type != "promo" or copy_hits >= 2:
                        found.add("copy_comma_noun")
                if "bare_verb_chain" not in found and _bare_verb_chain_sentence(sentence):
                    found.add("bare_verb_chain")
        for rule in ("say_hedge", "copy_comma_noun", "bare_verb_chain"):
            if rule in found:
                result.append({"rule": rule, "line": line_no, "severity": "info",
                               "message": _SHAPE_RULE_MESSAGES[rule], "snippet": row["raw"].strip()})
    return result


# dialogue_period（script だけ）: 台詞が DIALOGUE_MIN 個以上あり、最後の字が「。」の台詞の割合が DIALOGUE_RATIO 以上なら
# 文書に1件。narrative_density（essay だけ）: 地の文が NARRATIVE_MIN_CHARS 字以上で、一人称が千字あたり
# FIRST_PERSON_MAX 未満、数字と箇条書きの項目の合計が千字あたり DENSITY_MIN 以上なら文書に1件。
# 値は tests/corpus（human、raw_ai）と自作の類例で測って決めた（2.2.0。根拠の数は CHANGELOG）
DIALOGUE_MIN = 10
DIALOGUE_RATIO = 0.5
FIRST_PERSON_MAX = 1.0
DENSITY_MIN = 8
NARRATIVE_MIN_CHARS = 1000
# 台詞と地の文を探さない行（見出し、コード、表、引用は数えない）
_DOCUMENT_SKIP_KINDS = frozenset(("code", "frontmatter", "html_block", "reference_definition", "heading",
                                  "heading_underline", "thematic_break", "table"))
_QUOTE_PAIRS = {"「": "」", "『": "』"}
_QUOTE_CLOSERS = frozenset(_QUOTE_PAIRS.values())
# 「名前：台詞」の行。名前は空白、句読点、括弧を含まない12字以下（全角と半角のコロン）
_SPEAKER_LINE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)?([^\s：:「」『』（）()、。！？!?，,．.]{1,12})[ \t　]*[：:][ \t　]*(.+)$")
# 音と音楽の指示（SE、M、BGM）は台詞ではない。数字だけの名前（10:00）も外す
# コマ、ページ、場所や時間の柱、ト書きの見出しは話し手ではない（ナレーションは話し手として数える）
_NOT_SPEAKER = re.compile(r"^(?:SE|ＳＥ|M|Ｍ|BGM|ＢＧＭ|[0-9０-９]+|(?:[0-9０-９]+)?(?:コマ|ページ|P|Ｐ)目?[0-9０-９]*|場所|時間|時|"
                          r"人物|登場人物|柱|ト書き?|注|メモ|備考)$", re.I)
# 台詞の前後のト書き（「ハル：屁理屈（笑う）」の（笑う））
_EDGE_STAGE_NOTE = re.compile(r"^[（(][^（）()]*[）)]\s*|\s*[（(][^（）()]*[）)]$")
# 一人称（たち、ら、ども などの複数の形も同じ語として1回に数える）。仮名の語は、前が仮名でなく、動詞の続き
# （手わたします、おれた、など）でないときだけ。「私」は公私、私立、私鉄のような熟語を外す
_FIRST_PERSON = re.compile(
    r"(?<![公無])私(?![立鉄的物有服用語設費学道塾刑権財欲情事信案邸宅募企営益生淑書])"
    r"|(?<![ぁ-ゖ手受引見])(?:わたくし|わたし(?!て|た(?!ち)|ます|まし|ませ)|ぼく(?![じしさめ])|おれ(?!い|る|た(?!ち)|て|ま|ば|ず|ろ|そ))"
    r"|僕|俺|自分|筆者")
# 数字の続き（全角を含む。1,000 や 1.5 は1つ）。英字のすぐあとの数字（版の番号や見出しの記号）は識別子として数えない
_NARRATIVE_NUMBER = re.compile(r"(?<![A-Za-z_0-9０-９.,．，])[0-9０-９]+(?:[.,．，][0-9０-９]+)*(?![_0-9０-９])")
_ASCII_IDENTIFIER = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*(?:[./][A-Za-z0-9_]+)+|(?<![A-Za-z])[A-Za-z]+_[A-Za-z0-9_]+")


def _top_quote_contents(text):
    """1行の中の、いちばん外の「」と『』の中身。閉じていない括弧は数えない。"""
    contents = []
    stack = []
    for index, char in enumerate(text):
        if char in _QUOTE_PAIRS:
            stack.append((char, index))
        elif char in _QUOTE_CLOSERS and stack and _QUOTE_PAIRS[stack[-1][0]] == char:
            _, start = stack.pop()
            if not stack:
                contents.append(text[start + 1:index])
    return contents


def _dialogue_lines(analysis):
    """台詞の (行番号, 中身) の並び。「」と『』の中身、「名前「…」」の行、「名前：…」の行の中身を数える。
    見出し、コード、表、引用（> の行）は数えない。「」が1つもない行だけ「名前：…」の形を見る。"""
    dialogue = []
    for row in analysis["lines"]:
        if row["kind"] in _DOCUMENT_SKIP_KINDS or row["quote_depth"] or row["kind"] == "quote":
            continue
        visible = _prose_visible_text(analysis, row["line"]).replace("__", "").replace("*", "")
        if not visible.strip():
            continue
        quoted = _top_quote_contents(visible) if ("「" in visible or "『" in visible) else []
        if not quoted:
            speaker = _SPEAKER_LINE.match(visible)
            if speaker is None or _NOT_SPEAKER.match(speaker.group(1)):
                continue
            quoted = [_EDGE_STAGE_NOTE.sub("", speaker.group(2).strip())]
        for content in quoted:
            content = content.strip(" \t　")
            if content:
                dialogue.append((row["line"], content))
    return dialogue


def _narrative_counts(analysis):
    """地の文の (字数, 一人称の数, 数字の数, 箇条書きの項目の数, 最初の行の番号)。
    見出し、コード、表、引用（> の行）、画像だけの行は数えない。字数は空白を除いた見える文字。一人称と数字は、
    カギ括弧の中と英数字の識別子を伏せてから数える。"""
    chars = first_person = numbers = bullets = 0
    first_line = None
    for row in analysis["lines"]:
        if row["kind"] in _DOCUMENT_SKIP_KINDS or row["quote_depth"] or row["kind"] == "quote":
            continue
        visible = _prose_visible_text(analysis, row["line"])
        if not visible.strip():
            continue
        # 画像だけの行（[![…](…)](…) のバッジ）は数えない（_metrics_and_list_gate と同じ判定の門）
        if ((_image_only_row is not _IMAGE_ONLY_ROW_DEFAULT or row["raw"].lstrip().startswith("[!["))
                and _image_only_row(analysis, row, visible)):
            continue
        plain = visible.replace("__", "").replace("*", "")
        length = len("".join(plain.split()))
        if not length:
            continue
        if first_line is None:
            first_line = row["line"]
        chars += length
        if row["kind"] == "list" and _LIST_MARKER_LINE.match(row["raw"]):
            bullets += 1
        masked = _mask_quoted_segments_sparse(plain) if ("「" in plain or "『" in plain) else plain
        if "_" in masked or "." in masked or "/" in masked:
            masked = _ASCII_IDENTIFIER.sub(" ", masked)
        first_person += len(_FIRST_PERSON.findall(masked))
        numbers += len(_NARRATIVE_NUMBER.findall(masked))
    return chars, first_person, numbers, bullets, first_line


def _per_thousand(count, chars):
    return count * 1000 / chars if chars else 0.0


def _v220_document_findings(analysis, doc_type):
    """dialogue_period と narrative_density の候補（文書に1件）。種類を限って当てる規則なので、その種類のときだけ数える。"""
    findings = []
    if doc_type == "script":
        dialogue = _dialogue_lines(analysis)
        ended = sum(1 for _, content in dialogue if content.endswith(("。", "｡")))
        if len(dialogue) >= DIALOGUE_MIN and ended >= DIALOGUE_RATIO * len(dialogue):
            line_no = dialogue[0][0]
            findings.append({
                "rule": "dialogue_period",
                "line": line_no,
                "severity": "info",
                "message": "台詞の最後の句点（台詞{}個のうち{}個、{}%が「。」で終わる）の候補です。文脈を見て、誰が何をどうするかを"
                           "書き直すか確かめてください。".format(len(dialogue), ended, round(ended * 100 / len(dialogue))),
                "snippet": analysis["lines"][line_no - 1]["raw"].strip()
            })
    elif doc_type == "essay":
        chars, first_person, numbers, bullets, first_line = _narrative_counts(analysis)
        person_rate = _per_thousand(first_person, chars)
        density = _per_thousand(numbers + bullets, chars)
        if chars >= NARRATIVE_MIN_CHARS and person_rate < FIRST_PERSON_MAX and density >= DENSITY_MIN:
            findings.append({
                "rule": "narrative_density",
                "line": first_line,
                "severity": "info",
                "message": "読み物の一人称と数字（地の文{:,}字、一人称は千字あたり{:.1f}、数字と箇条書きは千字あたり{:.1f}）の候補です。"
                           "文脈を見て、誰が何をどうするかを書き直すか確かめてください。一人称と体験は足さず、数字も消しません。"
                           .format(chars, person_rate, density),
                "snippet": analysis["lines"][first_line - 1]["raw"].strip()
            })
    return findings


# 語の一覧の allow.txt の語で外す規則（規則ID の順。context.words.allow_removed の並び）
_ALLOW_RULES = ("calque", "katakana_term", "metaphor_label", "metaphor_verb", "project_term", "slop_vocabulary",
                "translated_term")
_LABEL_WORD = re.compile(r"「([^」]+)」")
# 語の一覧の flag.txt の語の message。その行に出た flag の語を「語の一覧（flag.txt）の語（依存先、承認）」のように並べる
_PROJECT_TERM_MESSAGE = "語の一覧（flag.txt）の語（{}）" + _V220_MESSAGE_TAIL
# 英数字で始まるか終わる語は、識別子（snake_case、camelCase、ドットや / を含む語）の一部では数えない
_WORD_ASCII = re.compile(r"[A-Za-z0-9_]")
_WORD_BEFORE = r"(?<![A-Za-z0-9_./\\-])"
_WORD_AFTER = r"(?![A-Za-z0-9_])(?![./\\-][A-Za-z0-9_])"


def _hit_words(label, match):
    """候補の内部の欄 _words の値。message に出る規則の表の語（label。「」があればその中身）、そこから「〜」と英語の
    注記を除いた語、当たった文字列（前後の空白を除く）を、重ねずにこの順で並べる。"""
    words = []
    quoted = _LABEL_WORD.search(label)
    shown = quoted.group(1) if quoted else label
    name = re.sub(r"[ 　]*[（(][^）)]*[）)]$", "", shown).strip("〜~ 　")
    for word in (shown, name, match.group(0).strip() if match is not None else ""):
        if word and word not in words:
            words.append(word)
    return tuple(words)


def _flag_pattern(flag):
    """flag.txt の語を1つの正規表現にする（長い語を先に。英数字の端には識別子の境目を付ける）。語がなければ None。"""
    words = sorted(set(flag), key=lambda word: (-len(word), word))
    if not words:
        return None
    parts = []
    for word in words:
        part = re.escape(word)
        if _WORD_ASCII.match(word[0]):
            part = _WORD_BEFORE + part
        if _WORD_ASCII.match(word[-1]):
            part += _WORD_AFTER
        parts.append(part)
    return re.compile("|".join(parts))


def _project_term_findings(analysis, words):
    """語の一覧の flag.txt の語の候補（project_term）。見える文字（コード、URL、リンク先、HTML、frontmatter を伏せた行）に
    flag の語が出る行に1件。引用（> の行）とカギ括弧・二重カギ括弧の中は数えない。_words にその行の flag の語。"""
    if not words or not words.get("flag"):
        return []
    pattern = _flag_pattern(words["flag"])
    found = []
    for row in analysis["lines"]:
        if row["kind"] in ("code", "frontmatter", "html_block", "reference_definition", "quote") or row["quote_depth"]:
            continue
        visible = _prose_visible_text(analysis, row["line"])
        if not visible.strip():
            continue
        hits = tuple(dict.fromkeys(match.group(0) for match in pattern.finditer(_mask_quoted_segments(visible))))
        if hits:
            found.append({"rule": "project_term", "line": row["line"], "severity": "info",
                          "message": _PROJECT_TERM_MESSAGE.format("、".join(hits)), "snippet": row["raw"].strip(),
                          "_words": hits})
    return found


def _apply_words(findings, words):
    """語の一覧の allow.txt の語で候補を外す。(残った候補, context に入れる words の値か None) を返す。

    外すのは _ALLOW_RULES の規則の候補で、候補の _words のどれかが allow の語と同じもの。残った候補の順は変えない。
    1行に1件で語を並べる規則（_ALLOW_PARTIAL_RULES）は、許した語だけを除き、許していない語が残れば候補を残して
    message を作り直す（外した件数には数えない）。
    words が None（一覧を使わない）なら、候補をそのまま返し、context の値は None。"""
    if words is None:
        return findings, None
    allow = frozenset(words.get("allow") or ())
    removed = dict((rule, 0) for rule in _ALLOW_RULES)
    kept = findings
    if allow:
        kept = []
        for finding in findings:
            hit = finding.get("_words") or ()
            if finding["rule"] in removed and any(word in allow for word in hit):
                rest = tuple(word for word in hit if word not in allow)
                if finding["rule"] in _ALLOW_PARTIAL_RULES and rest:
                    kept.append(_finding_with_words(finding, rest))
                else:
                    removed[finding["rule"]] += 1
            else:
                kept.append(finding)
    context = words_context(words)
    context["allow_removed"] = removed
    return kept, context


# 1行に1件で、行の語を _words に並べる規則。allow.txt の語は語ごとに外す
_ALLOW_PARTIAL_RULES = ("calque", "katakana_term", "project_term")


def _finding_with_words(finding, rest):
    """許していない語（rest）だけを残した候補の写し。calque と project_term は message も作り直す。"""
    out = dict(finding, _words=rest)
    if finding["rule"] == "calque":
        word_types = tuple((word, number) for word, number in finding.get("_word_types") or () if word in rest)
        out["_word_types"] = word_types
        out["message"] = _calque_message(list(dict.fromkeys(number for _, number in word_types)), word_types)
    elif finding["rule"] == "project_term":
        out["message"] = _PROJECT_TERM_MESSAGE.format("、".join(rest))
    return out


def _public_finding(finding):
    """候補の内部の欄（_ で始まるキー。_words など）を除いた写し。"""
    return {key: value for key, value in finding.items() if not key.startswith("_")}


def lint_text(text: str, *, doc_type=None, reader=None, words=None) -> Dict[str, Any]:
    """文章全体を総合検査する。

    doc_type（文書の種類）を渡すと、DOC_TYPE_SKIP_RULES のその種類の規則の候補を除き、除いた件数を context に入れる。
    reader（読者）は context に入れるだけで、候補は変えない。値は中で正規化し、使えない値は ValueError。
    words は語の一覧（allow.txt と flag.txt）。None なら一覧なしとして動く。"""
    doc_type, reader = normalize_doc_type(doc_type), normalize_reader(reader)
    findings = []
    analysis = analyze_markdown(text)
    rule9_context = _rule9_context(analysis)
    extra_negation_lines = _extra_negation_line_numbers(analysis)
    metrics, list_gate_chars, prose_chars = _metrics_and_list_gate(analysis)
    sentence_records = _plain_sentence_records(analysis)
    sentences = [(line, visible) for line, visible, _, _ in sentence_records]
    source_sentences = [(line, source) for line, _, source, _ in sentence_records]
    paragraph_groups = [block_id for _, _, _, block_id in sentence_records]
    narrowed = _narrowed_document_rows(text)
    if narrowed is None:
        # Keep original eager compilation and lazy per-line lexical access for
        # unusual configuration values, compiled custom patterns or generators.
        metaphor_patterns = [(re.compile(pattern), desc, None) for pattern, desc in METAPHOR_VERB_PATTERNS]
        filler_patterns = [(re.compile(pattern), desc, None) for pattern, desc in FILLER_PATTERNS]
        info_sentence_patterns = [(re.compile(pattern), rule, message, None)
                                  for pattern, rule, message in INFO_SENTENCE_PATTERNS]
    else:
        slop_words, slop_patterns, metaphor_patterns, translated_patterns, filler_patterns, info_sentence_patterns = narrowed
    dash_possible = (_dash_finding is not _DASH_FINDING_DEFAULT or _DASH_RUN is not _DASH_RUN_DEFAULT
                     or any(char in text for char in "—―─━"))
    previous_sentence = ""
    kiku_lines = []
    kiku_before = []
    negation_lines = []
    bold_label_lines = []

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

    if list_gate_chars > 300:
        if metrics["list_ratio"] > 0.25:
            # 分母は比率と同じ（<details> の中の箇条書きの行を引いた数）。引いたときは注記で行の数を示す
            snippet = (f"リスト行: {metrics['list_lines']} / "
                       f"全非空行: {metrics['total_lines'] - metrics.get('details_list_lines', 0)}")
            if metrics.get("details_list_lines"):
                snippet += f"（<details> の中の箇条書き{metrics['details_list_lines']}行は数えていません）"
            findings.append({
                "rule": "excess_list",
                "line": 1,
                "severity": "warn",
                "message": f"箇条書きの比率（{round(metrics['list_ratio']*100, 1)}%）が設定した目安を超えています（推奨: 15%以下）。項目の役割を確かめ、不要なものだけ整理してください。",
                "snippet": snippet
            })

    # 2. 文末重複検査
    # 句点の代わりに絵文字を置いて続けた文は、句点で分けたときと同じように分けて数える
    findings.extend(_sentence_end_findings(*_split_decoration_breaks(sentences, source_sentences, paragraph_groups)))

    # 2.5 太字が表示されるか（GitHub などの Markdown で ** がそのまま出ることがある箇所）
    for p in _bold_problems_with_analysis(text, analysis):
        findings.append({
            "rule": "bold_not_rendered",
            "line": p["line"],
            "severity": "error",
            "message": f"太字の印（**）について、太字として表示されない可能性のある書き方が見つかりました。GitHub などで太字にならず ** がそのまま表示されることがあります。直し方: {p['how']}。",
            "snippet": f"{p['found']} → {p['suggest']}" if p["suggest"] else p["found"]
        })

    def _vocabulary_findings(plain_text, line_no, snippet):
        """AI頻出語彙と比喩動詞。見出しの行にも当てる（文の頭と終わりを前提にした型は当てない）。"""
        # スロップ語彙
        # 語の一覧の allow.txt で外すため、候補の内部の欄 _words に当たった語（型の語は、型の名前と当たった文字列）を入れる
        if narrowed is None:
            slop_hits = [(word, (word,)) for word in SLOP_WORDS if word in plain_text]
            slop_hits += [(word, _hit_words(word, match)) for word, match in
                          ((word, re.search(pattern, plain_text)) for word, pattern in SLOP_WORD_PATTERNS) if match]
        else:
            slop_hits = [(word, (word,)) for word in slop_words if word in plain_text]
            slop_hits += [(word, _hit_words(word, match)) for word, match in
                          ((word, re.search(pattern, plain_text) if _may_match_literals(required, plain_text) else None)
                           for word, pattern, required in slop_patterns) if match]
        for word, hit in slop_hits:
            findings.append({
                "rule": "slop_vocabulary",
                "line": line_no,
                "severity": "warn",
                "message": f"AI頻出語彙「{word}」が含まれています。文脈上必要のない比喩や大げさな装飾であれば、ふだん使う自然な表現に置き換えてください。ただし、文字どおりの意味や必要な文脈を担っている場合は残してかまいません。",
                "snippet": snippet,
                "_words": hit
            })

        # 比喩動詞パターン
        kowareru_span = None
        for pattern, desc, required in metaphor_patterns:
            if not _may_match_literals(required, plain_text):
                continue
            if (pattern.pattern == r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂"
                    and "収斂" not in plain_text):
                continue
            if desc == "英語直訳「静かに壊れる (silently fail)」" and kowareru_span:
                # 「壊れる」と「静かに壊れる」が同一動詞に二重反応することを防止
                for m in pattern.finditer(plain_text):
                    span = (m.start(), m.end())
                    if kowareru_span[0] <= span[0] and span[1] <= kowareru_span[1]:
                        continue
                    findings.append({
                        "rule": "metaphor_verb",
                        "line": line_no,
                        "severity": "warn",
                        "message": f"{desc}が検出されました。不自然な比喩動詞であれば、ふだん使う動詞や客観的な表現に書き直してください。ただし、文字どおりの動作や状態変化を表している場合は無理に言い換える必要はありません。",
                        "snippet": snippet,
                        "_words": _hit_words(desc, m)
                    })
                    break
                continue

            m = pattern.search(plain_text)
            if m and pattern.pattern == _KIKU_PATTERN and not _kiku_metaphor_in_line(plain_text, kiku_before):
                # 比喩の「効く」は、文字どおりの「効く」や慣用句を除いて、文ごとに決める
                m = None
            if m:
                if desc == "比喩動詞「壊れる」":
                    kowareru_span = (m.start(), m.end())
                findings.append({
                    "rule": "metaphor_verb",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。不自然な比喩動詞であれば、ふだん使う動詞や客観的な表現に書き直してください。ただし、文字どおりの動作や状態変化を表している場合は無理に言い換える必要はありません。",
                    "snippet": snippet,
                    "_words": _hit_words(desc, m)
                })

    # 3. 語彙・構文パターン検査
    pause_lines = None
    for row in analysis["lines"]:
        line_no, line = row["line"], row["raw"]
        if row["kind"] in ("code", "frontmatter", "html_block", "reference_definition"):
            previous_sentence = ""
            continue
        stripped = line.strip()
        scan_text = _prose_visible_text(analysis, line_no).strip()
        if (row["kind"] in ("table", "thematic_break", "quote") or row["quote_depth"]
                or ((_image_only_row is not _IMAGE_ONLY_ROW_DEFAULT
                     or not scan_text or row["raw"].lstrip().startswith("[!["))
                    and _image_only_row(analysis, row, scan_text))):
            previous_sentence = ""
        if not scan_text:
            continue
        # 空行で区切ったQ&Aは保ち、別の内容があればその最後の文へ更新する。
        sentence_before_line = previous_sentence
        plain_text = scan_text.replace("__", "").replace("*", "")
        previous_sentence = plain_text
        # 比喩の「効く」で、前の行の文字どおりの語（薬、エアコン など）を見るための窓
        kiku_before = kiku_lines[-_KIKU_WINDOW_LINES:]
        kiku_lines = kiku_before + [plain_text]

        # Glyphs inside code, URI data and HTML tokens are not prose decoration.
        emoji_matches = _emoji_matches(scan_text)
        if emoji_matches:
            findings.append({
                "rule": "emoji_prohibited",
                "line": line_no,
                "severity": "warn",
                "message": f"絵文字（{' '.join(emoji_matches[:3])}）が検出されました。AI特有の不要な装飾であれば整理してください。ただし、意味や必要な用途を担っている表現は保ってください。",
                "snippet": stripped
            })

        # Keep the existing lexical exemption for all quoted content, including
        # lists/headings inside a quote. Visible emoji keeps its earlier policy.
        if row["quote_depth"] or row["kind"] == "quote":
            previous_sentence = ""
            continue
        # A dash in a table cell often means "not applicable", so tables are skipped.
        if row["kind"] != "table" and dash_possible:
            dash = _dash_finding(plain_text, line_no, stripped)
            if dash:
                # 1文書の件数の上限は、種類で外した候補を除いたあとに当てる
                findings.append(dash)
        if row["kind"] == "heading":
            if re.search(r"とは[：:]", scan_text):
                findings.append({
                    "rule": "heading_colon",
                    "line": line_no,
                    "severity": "warn",
                    "message": "見出しが「Xとは：Y」の形になっています。コロンの後の語句を落とさずに、「Xの仕組みと使い方」のような名詞句にしてください。",
                    "snippet": stripped
                })
            if ((_SUMMARY_HEADING.match(stripped) or _SUMMARY_HEADING.match(_strip_end_decoration(stripped)))
                    and metrics["char_count"] < 2000):
                findings.append({
                    "rule": "short_summary_heading",
                    "line": line_no,
                    "severity": "info",
                    "message": "短い文書に「まとめ」「おわりに」の見出しがあります。本文の繰り返しになっていないか確かめてください。新しい情報や結論の絞り込み、数値を担う場合は残してください。",
                    "snippet": stripped
                })
            if re.search(r"（(素の出力|いわゆる|概要|詳細|感謝と設計への反映)）", scan_text):
                findings.append({
                    "rule": "redundant_bracket",
                    "line": line_no,
                    "severity": "warn",
                    "message": "見出しに補足カッコが含まれています。役割を確認し、同じ情報の繰り返しや不要な補足であれば整理してください。",
                    "snippet": stripped
                })
            _vocabulary_findings(plain_text, line_no, stripped)
            continue
        if row["kind"] == "table":
            previous_sentence = ""
            continue
        if _BOLD_LABEL_ITEM.match(line):
            bold_label_lines.append(line_no)
        line_sentences = [clean for part in _LINE_SENTENCE_BREAK.split(plain_text) if (clean := part.strip())]

        # A real final prose colon must not be manufactured by removing a value.
        # Keep the tested legacy URI-prefix exemption, separately from GFM's
        # punctuation trimming. Only real code spans are removed for this test.
        if re.search(r"[：:]$", stripped) and not re.fullmatch(r":{3,}", stripped):
            uri_prefix_text = line_visible_text(analysis, line_no, frozenset(("inline_code",))).strip()
            last = len(line.rstrip()) - 1
            if (not uri_prefix_text.startswith("http")
                    and not range_overlaps_protected(analysis, row["start"] + last, row["start"] + last + 1, _METRIC_OPAQUE_KINDS)):
                findings.append({
                    "rule": "trailing_colon",
                    "line": line_no,
                    "severity": "warn",
                    "message": "文末にコロン（：）があります。ラベルと値の対応などに必要か確認し、不要な前置きなら整理してください。",
                    "snippet": stripped
                })

        _vocabulary_findings(plain_text, line_no, line.strip())

        # 英語直訳の語
        # 同じ desc の型が2つ当たっても1件。当たった文字列は _words にまとめて残す（語の一覧の allow.txt で外すため）
        if narrowed is None:
            translated_hits = ((desc, re.search(pattern, plain_text)) for pattern, desc in TRANSLATED_TERM_PATTERNS)
        else:
            translated_hits = ((desc, re.search(pattern, plain_text) if _may_match_literals(required, plain_text) else None)
                               for pattern, desc, required in translated_patterns)
        translated_words = {}
        for desc, match in translated_hits:
            if match:
                translated_words[desc] = translated_words.get(desc, ()) + _hit_words(desc, match)
        for desc, hit in translated_words.items():
            findings.append({
                "rule": "translated_term",
                "line": line_no,
                "severity": "warn",
                "message": f"英語の直訳{desc}が検出されました。ソフトウェアの文脈であれば、開発現場で定着した言い方（「バージョン」「リグレッション」「デグレ」など）や具体的な説明を検討してください。ただし、出版物や製品の種類を表す「版」、回帰テストや回帰分析など定着した用語は残してかまいません。",
                "snippet": line.strip(),
                "_words": tuple(dict.fromkeys(hit))
            })

        # フィラーパターン（文ごとに見て、同じ型は1行1件）
        # 文末に固定した型（$）は、文末の後ろの飾りを除いた文にも当てる
        line_cores = None
        context_cores = None
        for pattern, desc, required in filler_patterns:
            if not _may_match_literals(required, plain_text):
                continue
            # Do not change quote handling for any of the pre-existing fillers.
            if pattern.pattern == _OVERSTATEMENT_PATTERN:
                if context_cores is None:
                    context_cores = _with_undecorated(tuple(sentence for sentence, _ in rule9_context.get(line_no, ())),
                                                      _end_closers_for(analysis, line_no))
                filler_sentences = context_cores
            elif "$" in pattern.pattern:
                if line_cores is None:
                    line_cores = _with_undecorated(line_sentences, _end_closers_for(analysis, line_no))
                filler_sentences = line_cores
            else:
                filler_sentences = line_sentences
            if any(pattern.search(sentence) for sentence in filler_sentences):
                findings.append({
                    "rule": "meta_filler",
                    "line": line_no,
                    "severity": "warn",
                    "message": f"{desc}が検出されました。単なる前置きや不要な飾りであれば削り、本題から書いてください。ただし、「何が大事か」という評価や主張そのものを担っている場合は、述語に移すなどして意味を残してください。" + FILLER_NOTES.get(desc, ""),
                    "snippet": line.strip()
                })

        # 見直しのきっかけにとどめる文の型
        for pattern, rule, message, required in info_sentence_patterns:
            if _may_match_literals(required, plain_text) and any(pattern.search(sentence) for sentence in line_sentences):
                findings.append({"rule": rule, "line": line_no, "severity": "info", "message": message, "snippet": stripped})

        if any(_has_instruction_residue(sentence, following)
               or _has_instruction_residue_core(sentence, following, _end_closers_for(analysis, line_no))
               for sentence, following in rule9_context.get(line_no, ())):
            findings.append({
                "rule": "instruction_residue",
                "line": line_no,
                "severity": "info",
                "message": "AIへの指示が本文に残る形（書き方や除外の予告）が検出されました。除外や書き方の指示を述べる文を削ってください。ただし、読者のための範囲・対象読者・前提・参照先・用語の定義を示す文は残してください。",
                "snippet": stripped
            })

        for index, sentence in enumerate(line_sentences):
            if ("もちろん、" not in plain_text and "勿論、" not in plain_text):
                break
            if (not (_SHORT_MOCHIRON.match(sentence)
                     or _SHORT_MOCHIRON.match(_strip_end_decoration(sentence, _end_closers_for(analysis, line_no))))
                    or _MOCHIRON_ANSWER.match(sentence)):
                continue
            if _ends_with_question(line_sentences[index - 1] if index else _last_context_sentence(sentence_before_line)):
                continue
            findings.append({
                "rule": "short_mochiron",
                "line": line_no,
                "severity": "info",
                "message": "文頭の「もちろん、」のあとに数語だけが続く短い文が検出されました。読み手が思いそうなことを先回りして認めているだけなら「もちろん、」を外してください。その含みを「当然、」などの別の語で補ったり、元にない理由や因果を足したりはしないでください。問いや依頼への答え、条件や前提の確認なら残してかまいません。",
                "snippet": stripped
            })
            break
        # 引用は中身を伏せた「」に置き換え、短い文の数に入れない（「1位は「田中」。」を断片にしない）。
        if (plain_text.count("。") + plain_text.count("！") >= 3
                and _FRAGMENT_RUN.search(_QUOTED_SEGMENT.sub("「」", plain_text))):
            findings.append({
                "rule": "fragment_run",
                "line": line_no,
                "severity": "info",
                "message": "評価の語だけの短い文が3つ以上続いています（「効く。重い。安い。」など）。何がどうなのかが前後から分かる場合は、対象と評価を述語までつないでください。分からない場合は主語や理由を作らず、原文を残して書き手に確かめてください。小説の語りや詩など、書き手が意図した表現は残してかまいません。",
                "snippet": stripped
            })
        # 「〜のは、A、B、C。」（引用の中は伏せた文で見る）。直前の文が問いか同じ動詞の漢字を含むときは、前提があるとみて出さない。
        if "のは、" in plain_text and _has_cleft_list_ending(
                analysis, line_no, rule9_context.get(line_no, ()), line_sentences, filler_patterns):
            findings.append({
                "rule": "cleft_list_ending",
                "line": line_no,
                "severity": "info",
                "message": "「〜のは、」のあとに名詞を並べ、述語を書かずに終える文（「〜で変わったのは、A、B、C。」）が検出されました。何かが変わった、何かを目指したといった前提を前の文や見出しで書いていなければ、「のは」の前の動詞を述語に戻し、「〜では、A、B、Cが変わった。」のように述語まで書いてください。前提が直前に書いてある場合や、見出し、結び、スライドの箇条で書き手が強調として選んだ形なら残してかまいません。",
                "snippet": stripped
            })

        # ネガティブパラレリズム
        if "ではなく" in plain_text and plain_text.count("ではなく") == len(_NEGATION_ALSO.findall(plain_text)):
            negation_message = None
        elif _has_negative_parallelism(plain_text) and "ではなく" in plain_text:
            negation_message = "「AではなくB」構文が検出されました。否定を外しても主張が変わらない場合は肯定文を検討してください。ただし、誤解の訂正や見方の切り替えなど意味・比重を担っている否定なら、無理に肯定化せずそのまま残してください。"
        elif (line_no in extra_negation_lines
              or ("でもない。" in plain_text and _NEGATION_EXTRA.search(plain_text))
              or ("じゃない、" in plain_text
                  and any(_NEGATION_JANAI.match(sentence)
                          for sentence in _with_undecorated(line_sentences, _end_closers_for(analysis, line_no))))):
            negation_message = "否定を重ねてから言い切る構文（「AでもBでもない。Cだ。」「Aじゃない、Bです。」）が検出されました。否定している内容を誰も主張していないなら、言い切る文だけにしてください。読み手の思い込みを正す否定なら、一つの文にまとめて残してください。直前で挙げた二つ（問いなど）を両方とも打ち消すだけなら、「どちらでもない。」（敬体なら「どちらでもありません。」）と短く受けてもかまいません。打ち消すほかに、問いにない強めの語や限定、なぜ違うかの説明を含む否定は短くしないでください。"
        else:
            negation_message = None
        if negation_message:
            negation_lines.append(line_no)
            findings.append({
                "rule": "negative_parallelism",
                "line": line_no,
                "severity": "info",
                "message": negation_message,
                "snippet": line.strip()
            })

        # 表にない規則は当て、表にある規則は指定した種類が含まれるときだけ検出する。
        if "pause_comma" not in DOC_TYPE_ONLY_RULES or doc_type in DOC_TYPE_ONLY_RULES["pause_comma"]:
            if pause_lines is None:
                pause_lines = _pause_comma_line_hits(analysis)
            pause_hits = pause_lines[line_no] if line_no in pause_lines else _pause_comma_hits(plain_text)
            if pause_hits:
                phrases = "".join("「{}{}、」".format(phrase, chunk) for _, chunk, phrase in pause_hits[:3])
                if len(pause_hits) > 3:
                    phrases += "ほか{}か所".format(len(pause_hits) - 3)
                findings.append({
                    "rule": "pause_comma",
                    "line": line_no,
                    "severity": "info",
                    "message": f"短い主語や主題のすぐあとに読点があります（{phrases}）。間を作るだけの読点は、AIの文章らしく見えます。読点のあとに別の主語が来る、条件や場面の枠を示す、並べている、外すと語がつながったり掛かり先が変わったりする、のどれにも当たらなければ、読点だけを外してください（語順と述語は変えません）。小説や随筆で書き手が間として置いた読点は残してかまいません。",
                    "snippet": line.strip()
                })

    # 文書全体の型
    if len(negation_lines) >= 3:
        findings.append({
            "rule": "negative_parallelism_density",
            "line": negation_lines[2],
            "severity": "info",
            "message": f"否定の対比（「AではなくB」など）が文書内に{len(negation_lines)}か所あります。1か所ずつの役割を確かめ、言い切れば足りる箇所だけを肯定文にしてください。",
            "snippet": f"行: {', '.join(str(n) for n in negation_lines[:5])}"
        })
    if len(bold_label_lines) >= 3:
        findings.append({
            "rule": "bold_label_list",
            "line": bold_label_lines[0],
            "severity": "info",
            "message": f"太字の見出し語とコロンで始まる箇条書きが{len(bold_label_lines)}行あります。値が日時や場所、担当、数値などの短い事実なら残してください。見出し語が抽象的で、値が一文の説明なら、地の文にするか、太字とコロンを外してください。並列関係が明確で読みやすい箇条書きは箇条書きのまま残し、項目の区別と数・順序は変えないでください。",
            "snippet": f"行: {', '.join(str(n) for n in bold_label_lines[:5])}"
        })

    # 2.2.0 の規則（どれも info で、点数に入れない）。既存の規則の候補は analysis["_findings"] で渡す（重なりを見るため。読むだけ）
    analysis["_findings"] = findings
    findings.extend(_v220_word_findings(analysis))
    findings.extend(_v220_shape_findings(analysis, findings, doc_type))
    findings.extend(_v220_document_findings(analysis, doc_type))
    findings.extend(_project_term_findings(analysis, words))

    # 文書の種類で外す規則。検出が終わったあと、件数と点数を数える前に、前から順に
    # 除いて規則ごとに数える。残った候補の順は変えない。種類を指定しないときは、種類を限って当てる規則だけを除く
    skipped = dict((rule, 0) for rule in DOC_TYPE_SKIP_RULES[doc_type]) if doc_type is not None else {}
    partial = DOC_TYPE_SKIP_PATTERNS.get(doc_type, {})
    skipped.update((rule, 0) for rule in partial)
    if skipped or DOC_TYPE_ONLY_RULES:
        kept = []
        for finding in findings:
            rule = finding["rule"]
            if (rule in DOC_TYPE_SKIP_RULES.get(doc_type, ())
                    or finding["message"].startswith(partial.get(rule, ()))):
                skipped[rule] += 1
            elif rule not in DOC_TYPE_ONLY_RULES or doc_type in DOC_TYPE_ONLY_RULES[rule]:
                kept.append(finding)
        findings = kept
    # 語の一覧の allow.txt の語で外す候補。件数と点数を数える前に除く
    findings, words_context = _apply_words(findings, words)
    # ダッシュの候補は、外したあとに残ったものの初めから DASH_FINDING_LIMIT 件だけを出し、点数には全部を数える
    dash_hits = 0
    shown = []
    for finding in findings:
        if finding["rule"] in _DASH_RULES:
            dash_hits += 1
            if dash_hits > DASH_FINDING_LIMIT:
                continue
        shown.append(finding)
    findings = shown

    # 候補の重みを地の文1,000字あたりに直した x から、100 × 40 ÷ (40 + x) を丸める目安。品質の点数ではない。
    # 2.2.0 の規則の候補は点数を計算する前に除く
    rule_penalty_score = _rule_penalty_score([finding for finding in findings if finding["rule"] not in _V220_RULES],
                                             prose_chars, dash_hits)
    counts = {"error": 0, "warn": 0, "info": 0}
    for finding in findings:
        if finding["severity"] in counts:
            counts[finding["severity"]] += 1
    context = {"doc_type": doc_type, "reader": reader, "skipped_by_doc_type": skipped}
    if words_context is not None:
        context["words"] = words_context

    return {
        "format": "yomiyasu-lint",
        "format_version": LINT_FORMAT_VERSION,
        "tool_version": __version__,
        "candidate_count": len(findings),
        "counts": counts,
        "no_rule_findings": len(findings) == 0,
        "rule_penalty_score": rule_penalty_score,
        "not_judged": ["meaning_preservation", "reader_comprehension"],
        "context": context,
        "metrics": metrics,
        "findings": [_public_finding(finding) for finding in findings]
    }


# ---- 人が読む出力 ----

_REPORT_HEADER = (
    "表現・書式の検査を実行しました。",
    "見直し候補: {count}件",
    "この検査では、意味の保持と読者にとっての分かりやすさは判定していません。",
)


def render_findings(result: Dict[str, Any]) -> str:
    """内訳の行と候補の並びだけを返す（候補が0件なら空の文字列）。末尾に改行は付けない。

    候補は行番号の順に並べる（同じ行の中は findings の順のまま）。findings の順そのものは変えない。
    """
    findings = result["findings"]
    if not findings:
        return ""
    counts = result["counts"]
    blocks = ["内訳: error {}件、warn {}件、info {}件".format(counts["error"], counts["warn"], counts["info"])]
    for finding in sorted(findings, key=lambda item: item["line"]):
        lines = ["L{} [{}] {}: {}".format(finding["line"], finding["severity"].upper(), finding["rule"], finding["message"])]
        for snippet_line in str(finding["snippet"]).split("\n"):
            snippet_line = snippet_line.rstrip()
            if snippet_line:
                lines.append("  > " + snippet_line)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _context_line(result):
    """種類か読者を指定したときの4行目。指定しないときは None。"""
    context = result.get("context") or {}
    doc_type, reader = context.get("doc_type"), context.get("reader")
    if doc_type is None and reader is None:
        return None
    line = context_label(doc_type, reader)
    if doc_type is not None:
        skipped = context.get("skipped_by_doc_type") or {}
        if skipped:
            line += "種類に合わせて外した候補 {}件（{}）。".format(
                sum(skipped.values()), "、".join("{} {}件".format(rule, count) for rule, count in skipped.items()))
        else:
            line += "この種類で外す規則はありません。"
    if reader is not None:
        line += "読者では候補を変えていません。"
    return line


def _words_line(result):
    """語の一覧を使ったときの行（種類か読者の4行目のあと。なければ4行目）。使わないときは None。"""
    words = (result.get("context") or {}).get("words")
    if not isinstance(words, dict):
        return None
    return words_label(words) + "allow で外した候補 {}件。".format(sum((words.get("allow_removed") or {}).values()))


def render_report(result: Dict[str, Any]) -> str:
    """通常の出力の全体（1〜3行目、種類か読者を指定したときの4行目、語の一覧を使ったときの行、候補があれば内訳と
    候補の並び）を返す。末尾に改行は付けない。"""
    header = "\n".join(_REPORT_HEADER).format(count=result["candidate_count"])
    for line in (_context_line(result), _words_line(result)):
        if line is not None:
            header += "\n" + line
    body = render_findings(result)
    return header + "\n\n" + body if body else header


# ---- CLI ----

# --strict と --fail-on の条件。値は (終了コード1の行に書く文, 当たったかを決める重さ)。
_FAIL_CONDITIONS = {
    "strict": ("--strict の条件（warn か error の候補が1件以上）", ("warn", "error")),
    "warn": ("--fail-on=warn の条件（warn か error の候補が1件以上）", ("warn", "error")),
    "error": ("--fail-on=error の条件（error の候補が1件以上）", ("error",)),
}
_MEANING_RISK_MESSAGE = (
    "--fail-on=meaning-risk は lint では使えません。lint は1つの文章だけを見るので、意味の変化は判定できません。"
    "原文と比べる yomiyasu_diff.py か yomiyasu_check.py に付けてください。"
)
_EXIT_CODES = """終了コード:
  0  検査を最後まで実行し、--strict と --fail-on の条件に当たらなかった（候補の有無によらない）。-h と --version も0
  1  --strict か --fail-on の条件に当たった
  2  使い方か入力の誤り（ファイルを開けない、UTF-8 として読めない、標準入力を読めない、使えない --fail-on、--doc-type、--reader の値、語の一覧を読めない（--words のフォルダがない、UTF-8 でない、1万行を超える）、--words と --no-words を一緒に指定した）
  3  予期しない内部の誤り（標準エラーにトレースバックを出す）か、出力先が閉じられて結果を最後まで書けなかった"""


def _doc_type_table():
    """ヘルプの終了コードの表の前に置く、種類ごとの規則の一覧（SKIP と ONLY の表から作る）。"""
    lines = ["文書の種類ごとに外す規則（--doc-type）:"]
    for value, rules in DOC_TYPE_SKIP_RULES.items():
        lines.append("  {:<10}{}".format(value, "、".join(rules) if rules else "なし"))
    lines.append("mail は meta_filler の返信・結びの5型だけも外します（ご質問ありがとうございます、必要なら次に〜します、いかがでしたでしょうか、ぜひ〜してみてください、参考になれば幸いです等）。宛名・挨拶・署名を削る専用規則はありません。paper は慎重表現を削る規則がないため除外なし。")
    for rule, allowed in DOC_TYPE_ONLY_RULES.items():
        excluded = [row[0] for row in DOC_TYPES if row[0] not in allowed]
        # 当てる種類が外す種類より少ない規則（2.2.0 の dialogue_period など）は、当てる種類を並べる
        if len(allowed) < len(excluded):
            scope = "{} だけ".format("、".join(allowed))
        else:
            scope = "{} を除く{}種類".format("、".join(excluded), len(allowed)) if excluded else "全{}種類".format(len(allowed))
        lines.append("種類を指定したときだけ当てる規則: {}（{}。種類を指定しないときは出しません）".format(rule, scope))
    lines.append("外した候補は、見直し候補の件数と --strict、--fail-on の判定に入れません。")
    return "\n".join(lines)


def _choices(rows):
    return "、".join("{}（{}）".format(row[0], row[1]) for row in rows)


class _ConditionAction(argparse.Action):
    """--strict と --fail-on を、指定した順に1つの並びに集める。"""

    def __call__(self, parser, namespace, values, option_string=None):
        conditions = list(getattr(namespace, "conditions", None) or [])
        conditions.append(("strict", option_string) if self.nargs == 0 else ("fail-on", values))
        setattr(namespace, "conditions", conditions)


class _ArgumentParser(argparse.ArgumentParser):
    # argparse は、書く先の流れがない（None の）とき、もう一方の流れに書く（使い方が標準出力に、
    # ヘルプが標準エラーに出る）。3.10 までは標準エラーがないと使い方の誤りで AttributeError になる。
    # pythonw や 2>&- のときも、書く先がなければ何も書かずに同じ終了コードで終える。

    def error(self, message):
        stream = sys.stderr
        if stream is None:
            self.exit(2)
        # 使い方の誤りを標準エラーに書く前に、ほかの誤りの文と同じく UTF-8 にする。
        # argparse の英語の行のあとに、日本語の案内を1行足す（ほかの誤りの文と同じ形）。
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


_PENALTY_HELP = """rule_penalty_score（--json の目安）:
  候補が0件なら100。候補があれば 100 × 40 ÷ (40 + x) を四捨五入し、1〜99に収めます。
  x は、行ごとの候補の重み（error 3、warn 2、info 1）を地の文1,000字あたりに直した数です。
  地の文はコード、表、引用、見出し、前置きの設定（frontmatter）、HTML、URL と空白を除いた字数で、
  1,000字に満たなければ1,000字として割ります。
  excess_bold と excess_list は1件で2、bold_label_list は1を x に足し、
  negative_parallelism_density は数えません。ダッシュの規則に当たった行は、候補に出さない4行目からも数えます。
  2.2.0 で足した次の規則の候補も数えず、その候補だけのときは100です: calque、metaphor_label、
  say_hedge、thin_evaluation、katakana_term、dialogue_period、narrative_density、copy_comma_noun、
  bare_verb_chain、project_term。
  --doc-type で候補が変わると、点数も変わります。CI では --fail-on か counts を使ってください。
"""


_WORDS_HELP = ("語の一覧（allow.txt と flag.txt）のフォルダ。省くと、作業ディレクトリから上へたどった git の最上位"
               "（.git のあるフォルダ。git の外では作業ディレクトリ）の .yomiyasu-words/ を探します（下の「語の一覧」）。")
_WORDS_EPILOG = """語の一覧（--words、--no-words）:
  allow.txt の語は、次の規則の候補から外し、外した件数を出します: calque、katakana_term、metaphor_label、
  metaphor_verb、project_term、slop_vocabulary、translated_term。flag.txt の語には project_term（info）の
  印をつけます。どちらも1行に1語（UTF-8。# で始まる行と空の行は読み飛ばします）。
"""
_NO_WORDS_HELP = "語の一覧を探さず、読みません（--words と一緒には使えません）。"


def _build_parser():
    parser = _ArgumentParser(
        prog="yomiyasu_lint.py",
        description=("日本語の表現とMarkdownの書式を、決まった規則で点検します。結果は見直し候補です。"
                     "候補の数や点数は、文章の品質、意味の保持、読者にとっての分かりやすさの合否ではありません。"),
        epilog=_doc_type_table() + "\n\n" + _PENALTY_HELP + "\n" + _WORDS_EPILOG + "\n" + _EXIT_CODES,
        formatter_class=_HelpFormatter,
        add_help=False,
        # 省略形（--js など）は受けない。lint、diff、check の3本でそろえる
        allow_abbrev=False,
    )
    arguments = parser.add_argument_group("引数")
    arguments.add_argument("file", nargs="?",
                           help="検査するファイル（UTF-8）。省略するか - を渡すと標準入力を読みます。")
    options = parser.add_argument_group("オプション")
    options.add_argument("-h", "--help", action="help", help="このヘルプを表示して終わります。")
    options.add_argument("--json", action="store_true",
                         help="結果をJSON（形式2）で出します。日本語は \\uXXXX の形で出します。"
                              "rule_penalty_score は、候補の多さを地の文の長さで割った目安です（下の式）。合否には使わないでください。")
    options.add_argument("--strict", action=_ConditionAction, nargs=0, dest="conditions",
                         help="warn か error の候補が1件でもあれば、終了コード1で終わります。"
                              "info の候補と点数は使いません（--fail-on=warn と同じです）。")
    options.add_argument("--fail-on", action=_ConditionAction, dest="conditions", metavar="{warn,error}",
                         help="指定した中身の候補があれば、終了コード1で終わります。"
                              "warn: warn か error の候補。error: error の候補（太字が表示されない書き方）。"
                              "何度でも、カンマ区切りでも指定できます。点数は条件に使えません。"
                              "meaning-risk は2つの文章を比べないと判定できないので、"
                              "yomiyasu_diff.py か yomiyasu_check.py に付けてください。")
    options.add_argument("--doc-type", metavar="種類",
                         help="文書の種類。指定すると、その種類で普通な書き方を候補にする規則（下の一覧）の候補を外し、"
                              "外した件数を出します。外した候補の中身は、指定せずに実行すると見られます。"
                              "省くと、すべての規則を当てます（今までどおり）。値: " + _choices(DOC_TYPES) + "。")
    options.add_argument("--reader", metavar="読者",
                         help="想定する読者の知識。表示と JSON に残すだけで、候補は変えません。値: " + _choices(READER_LEVELS) + "。")
    options.add_argument("--words", metavar="フォルダ", help=_WORDS_HELP)
    options.add_argument("--no-words", action="store_true", help=_NO_WORDS_HELP)
    options.add_argument("--version", action="store_true", help="版を表示して終わります。")
    parser.set_defaults(conditions=[])
    return parser


def _version_line():
    return "yomiyasu_lint.py {} (JSON format {})".format(__version__, LINT_FORMAT_VERSION)


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


def _conditions(raw):
    """--strict と --fail-on の並びを、条件の名前の並びにする。使えない値があれば誤りの文を返す。

    meaning-risk は、ほかの値と混ぜても、ほかの誤りより先に断る。
    """
    names = []
    unknown = []
    for kind, value in raw:
        if kind == "strict":
            names.append("strict")
            continue
        # 大文字と小文字、「_」と「-」は区別しない（WARN、meaning_risk も受ける）。
        pieces = [piece.strip().lower().replace("_", "-") for piece in value.split(",") if piece.strip()]
        if not pieces:
            # 空、空白だけ、カンマだけの値は、目に見えないので「（空）」と書く。
            unknown.append("（空）")
        for piece in pieces:
            if piece in ("warn", "error"):
                names.append(piece)
            elif piece == "meaning-risk":
                return None, _MEANING_RISK_MESSAGE
            else:
                unknown.append(piece)
    if unknown:
        return None, "--fail-on に使えない値です: {}。lint で使えるのは warn と error です。".format(unknown[0])
    return names, None


def _read_input(path):
    """ファイルか標準入力を読み、(文字列, None) か (None, 誤りの文) を返す。"""
    if path is not None and path != "-":
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except (OSError, ValueError) as error:
            reason = getattr(error, "strerror", None) or error
            return None, "Error opening file {}: ファイルを開けません（{}）".format(path, reason)
        try:
            return decode_source(data)[0], None
        except UnicodeDecodeError:
            return None, "Error opening file {}: UTF-8 として読めません".format(path)
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
    try:
        return decode_source(data)[0], None
    except UnicodeDecodeError:
        return None, "Error reading stdin: UTF-8 として読めません"


def _run(argv):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(_version_line())
        return 0
    conditions, problem = _conditions(args.conditions)
    if problem:
        _error(problem)
        return 2
    try:
        # 種類と読者の値。使えない値と空の文字列は、入力を読む前に2で断る
        doc_type, reader = normalize_doc_type(args.doc_type), normalize_reader(args.reader)
    except ValueError as error:
        _error(str(error))
        return 2
    if args.words is not None and args.no_words:
        parser.error("--words と --no-words は一緒に使えません")
    try:
        # 語の一覧。読めない一覧は、入力を読む前に2で断る
        words = resolve_words(current_directory(), args.words, args.no_words)
    except WordsError as error:
        _error(str(error))
        return 2
    content, problem = _read_input(args.file)
    if problem:
        _error(problem)
        return 2

    result = lint_text(content, doc_type=doc_type, reader=reader, words=words)

    hit = []
    for name in conditions:
        text, severities = _FAIL_CONDITIONS[name]
        if text not in hit and any(result["counts"][severity] for severity in severities):
            hit.append(text)

    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        print(render_report(result))
        if hit:
            print()
            print("終了コード1: {}に当たりました（error {}件、warn {}件）。".format(
                "、".join(hit), result["counts"]["error"], result["counts"]["warn"]))
    # 書き出しの失敗（読む側が先に閉じたなど）を、ここで BrokenPipeError として受けられるようにする。
    if sys.stdout is not None:
        sys.stdout.flush()
    return 1 if hit else 0


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
    """CLI。終了コードを返す（0: 条件に当たらない、1: 条件に当たった、2: 使い方か入力の誤り、3: 内部の誤り）。"""
    try:
        if _IMPORT_ERROR is not None:
            raise _IMPORT_ERROR
        _use_utf8(sys.stdout)
        return _run(argv)
    except BrokenPipeError:
        # 出力先（パイプの読む側）が先に閉じた。lint の不具合ではないので、トレースバックは出さない。
        # 結果を最後まで書けなかったので、終了コードは3にする。
        _silence_stdout()
        _error("yomiyasu_lint.py: 出力先が閉じられたため、結果を最後まで書けませんでした。")
        return 3
    except Exception as error:
        if _closed_output_on_windows(error):
            # Windows で出力先が閉じられた。上の BrokenPipeError と同じく扱う
            _silence_stdout()
            _error("yomiyasu_lint.py: 出力先が閉じられたため、結果を最後まで書けませんでした。")
            return 3
        _error("yomiyasu_lint.py: 内部エラー: {}: {}".format(type(error).__name__, error))
        _error(traceback.format_exc().rstrip("\n"))
        return 3


if __name__ == "__main__":
    sys.exit(main())
