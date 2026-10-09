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
from bisect import bisect_right
from itertools import chain, compress
from operator import is_
from typing import List, Dict, Any, Tuple
try:
    if __package__:
        from .markdown_visibility import analyze_markdown, line_visible_text, range_overlaps_protected, inline_protected_spans, unicode_whitespace
    else:
        from markdown_visibility import analyze_markdown, line_visible_text, range_overlaps_protected, inline_protected_spans, unicode_whitespace
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
    line_visible_text = _visibility_module.line_visible_text
    range_overlaps_protected = _visibility_module.range_overlaps_protected
    inline_protected_spans = _visibility_module.inline_protected_spans
    unicode_whitespace = _visibility_module.unicode_whitespace


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

# 文脈を確かめる語の一覧。含まれていることだけでは誤りとしない。
SLOP_WORDS = [
    # 質感を装う疑似具体語
    "手触り", "肌感", "肌感覚", "体温", "温度感", "熱量", "血の通った", "泥臭い", "泥臭さ",
    # 認知・評価を装う語
    "解像度", "腹落ち", "メンタルモデル", "本質的", "地に足のついた", "等身大",
    # 抽象比喩名詞
    "営み", "装置", "土台", "羅針盤", "起爆剤", "触媒",
    # 日常の体験を大げさに表す場合がある語
    "真理", "虚飾", "境地", "美学", "深淵", "冷徹", "禁欲的", "優美", "極致", "宿命",
    # 指す役割を確かめる語
    "正本",
]

# 部分一致では別の語を巻き込むため、形で確かめる語（語, パターン）
SLOP_WORD_PATTERNS = [
    # ナビゲート、デリゲートなど -gate で終わる外来語は、直前のカタカナで除く（レビューゲートなどは拾う）。
    ("ゲート", r"(?:(?<![ァ-ヴー])|(?<=レビュー)|(?<=リリース)|(?<=チェック)|(?<=デプロイ)|(?<=マージ)|(?<=テスト))"
               r"(?<!搭乗)(?<!改札)ゲート(?!ウ[ェエ]イ|ボール|キーパー)"),
    # 数学の閉包（推移閉包、閉包演算など）や、会計・行政の台帳は定義どおりの用語として残す。
    ("閉包", r"(?<!推移)(?<!反射)(?<!対称)(?<!凸)(?<!代数)(?<!代数的)閉包(?!演算)"),
    ("台帳", r"(?<!資産)(?<!住民基本)(?<!会計)(?<!会計の)(?<!行政の)(?<!課税)(?<!土地)(?<!家屋)(?<!備品)(?<!登記)台帳"),
    ("〜のOS", r"(思考|意思決定|仕事|人生|組織|チーム|学習|経営)の?OS(?![A-Za-z])"),
    ("本質を突く", r"本質を突"),
]

# 英語の技術用語を辞書的な漢語にした直訳。「日本語版」「回帰テスト」など定着した用語は形で除外する。
TRANSLATED_TERM_PATTERNS = [
    (r"(この|その|あの|新しい|古い|最新の|前の|次の|今の|現在の|以前の)版(では|で|に|から|を|が|へ|の)", "「版」（version）"),
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
    r"(?:^|(?<=[。！？!?]))\s*" + _LIST_ITEM + "(?:、[ \t　]*" + _LIST_ITEM + "){2,}[ \t　]*[" + DASH_CHARS + "]+(?:[。．.]|$)")
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
# 小説などで点数が大きく下がらないよう、ダッシュの指摘は1文書あたりこの件数までにする。
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
    while end and (sentence[end - 1].isspace() or sentence[end - 1] in _QUESTION_CLOSERS):
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
# 文ごとに当てる（^ と $ は文の頭と終わり）。
FILLER_PATTERNS = [
    (r"^(まず|ここで)?(重要|大切|大事)なのは、?", "前置フィラー「重要なのは」"),
    (r"^結論から(言|い)(う|い|え)|^結論から申し上げ", "前置フィラー「結論から言うと」"),
    (r"^正直に言うと、?", "前置フィラー「正直に言うと」"),
    (r"^本音を言うと、?", "前置フィラー「本音を言うと」"),
    (r"^避けたいのは、?", "前置フィラー「避けたいのは」"),
    (r"^ポイントは、", "前置フィラー「ポイントは、」"),
    (r"見落とされがち|面白いのはここ|まさにそこがポイント", "自己ラベル「見落とされがち」など"),
    (r"いかがでした(でしょうか|か)?[？?。]?$", "定型クロージング「いかがでしたでしょうか」"),
    (r"ぜひ(参考|試し|活用)(に)?して(みて)?ください[！!。]?", "定型クロージング「ぜひ〜してみてください」"),
    (r"参考に(なれ|な)ば幸い|お役に立て(れ)?ば幸い|ぜひご(活用|参考に)ください|まずは小さく(始め|はじめ)(?:ましょう|てみましょう|てください|てみてください|てみませんか|て(?:みて)?はいかが(?:ですか|でしょうか)|る(?:ことが(?:大切|大事|重要)|のがおすすめ)です)[。！？!?]?$", "定型クロージング「参考になれば幸いです」など"),
    (r"〜に他なりません", "過剰な自己ラベリング「〜に他なりません」"),
    (r"^ご質問ありがとうございます", "チャット応答の名残「ご質問ありがとうございます」"),
    (r"見ていきましょう[。！!]?$|深掘りしていきます", "定型導入「それでは見ていきましょう」など"),
    (r"^(必要なら|ご希望があれば|よろしければ)、?(次に|続けて|この後(?!の))[^。！？!?]*(?:ます|ましょう)(?:か|よ|ね|よね)?(?:（[^。！？!?（）]*）)?[。！？!?]?$", "チャット応答の名残「必要なら次に〜します」"),
]

# 規則の説明に添える、残してよい場合（指針の例外に合わせる）
FILLER_NOTES = {
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
    r"(地味に|よく|じわじわ)効[かきくけいた]": ("効",),
    r"(データ|仕様|設計|環境|ビルド|システム|秩序)が(静かに)?壊れ": ("壊れ",),
    r"静かに(壊れ|落ち|失敗|沈黙)": ("静かに",),
    r"黙って(無視|捨て|スキップ|破棄)": ("黙って",),
    r"側に倒[すしせ]": ("側に倒",),
    r"時間[をに]溶か[したす]": ("溶か",),
    r"(1つずつ|一つずつ)潰[していく]": ("つずつ潰",),
    r"(実装|詳細|コード|設計|内部|仕組み|領域|本質)(に|まで|へ)踏み込[んむみま]": ("踏み込",),
    r"動かしながら引き返[すし]": ("動かしながら引き返",),
    r"代わりに添え[るた]": ("代わりに添え",),
    r"(議論|意見|結論|方向性|価格|話題|検討)が[^。！？!?]*?収斂": ("収斂",),
    r"した瞬間に?": ("した瞬間",),
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
    r"ぜひ(参考|試し|活用)(に)?して(みて)?ください[！!。]?": ("ぜひ",),
    r"参考に(なれ|な)ば幸い|お役に立て(れ)?ば幸い|ぜひご(活用|参考に)ください|まずは小さく(始め|はじめ)(?:ましょう|てみましょう|てください|てみてください|てみませんか|て(?:みて)?はいかが(?:ですか|でしょうか)|る(?:ことが(?:大切|大事|重要)|のがおすすめ)です)[。！？!?]?$": ("ば幸い", "ぜひご", "まずは小さく"),
    r"〜に他なりません": ("〜に他なりません",),
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
    r"(この|その|あの|新しい|古い|最新の|前の|次の|今の|現在の|以前の)版(では|で|に|から|を|が|へ|の)": ("版",),
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
    + r"(?![^。！？!?]{0,40}" + _NEGATION_NEGATIVE_END + r"[。！!])"
    + r"[^。！？!?]{1,40}" + _NEGATION_CONCLUSION_END + r"[。！!]")
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


def _sentence_end_findings(sentences, source_sentences=None, paragraph_groups=None):
    """Keep visible ending decisions and original finding snippets separate."""
    findings = []
    end_types = []

    for line_no, s in sentences:
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
        end_types.append((line_no, s, end_type))

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


def _metrics_from_analysis(analysis):
    """Use the same protected data boundary as lexical and sentence checks."""
    plain_rows = []
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
    total_lines = len(plain_rows)
    list_lines = 0
    for row, _ in plain_rows:
        if _LIST_MARKER_LINE.match(row["raw"]):
            if not _LIST_LINK_LINE.search(row["raw"]):
                list_lines += 1
    plain_content = "\n".join(visible for _, visible in plain_rows)
    bold_count = len(re.findall(r"\*\*[^*]+\*\*", plain_content))
    char_count = len("".join(plain_content.split()))
    bold_per_1000 = bold_count / char_count * 1000 if char_count > 0 else 0
    list_ratio = list_lines / total_lines if total_lines > 0 else 0
    return {"char_count": char_count, "total_lines": total_lines, "list_lines": list_lines,
            "list_ratio": round(list_ratio, 3), "bold_count": bold_count,
            "bold_per_1000": round(bold_per_1000, 2)}


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


def lint_text(text: str) -> Dict[str, Any]:
    """文章全体を総合検査する"""
    findings = []
    analysis = analyze_markdown(text)
    extra_negation_lines = _extra_negation_line_numbers(analysis)
    metrics = _metrics_from_analysis(analysis)
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
    dash_count = 0
    dash_possible = (_dash_finding is not _DASH_FINDING_DEFAULT or _DASH_RUN is not _DASH_RUN_DEFAULT
                     or any(char in text for char in "—―─━"))
    previous_sentence = ""
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

        if metrics["list_ratio"] > 0.25:
            findings.append({
                "rule": "excess_list",
                "line": 1,
                "severity": "warn",
                "message": f"箇条書きの比率（{round(metrics['list_ratio']*100, 1)}%）が設定した目安を超えています（推奨: 15%以下）。項目の役割を確かめ、不要なものだけ整理してください。",
                "snippet": f"リスト行: {metrics['list_lines']} / 全非空行: {metrics['total_lines']}"
            })

    # 2. 文末重複検査
    findings.extend(_sentence_end_findings(sentences, source_sentences, paragraph_groups))

    # 2.5 太字が表示されるか（GitHub などの Markdown で ** がそのまま出ることがある箇所）
    for p in _bold_problems_with_analysis(text, analysis):
        findings.append({
            "rule": "bold_not_rendered",
            "line": p["line"],
            "severity": "error",
            "message": f"太字の印（**）について、太字として表示されない可能性のある書き方が見つかりました。GitHub などで太字にならず ** がそのまま表示されることがあります。直し方: {p['how']}。",
            "snippet": f"{p['found']} → {p['suggest']}" if p["suggest"] else p["found"]
        })

    # 3. 語彙・構文パターン検査
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
            if dash and dash_count < DASH_FINDING_LIMIT:
                findings.append(dash)
                dash_count += 1
        if row["kind"] == "heading":
            if re.search(r"とは[：:]", scan_text):
                findings.append({
                    "rule": "heading_colon",
                    "line": line_no,
                    "severity": "warn",
                    "message": "見出しが「Xとは：Y」の形になっています。コロンの後の語句を落とさずに、「Xの仕組みと使い方」のような名詞句にしてください。",
                    "snippet": stripped
                })
            if _SUMMARY_HEADING.match(stripped) and metrics["char_count"] < 2000:
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
        if re.search(r"[：:]$", stripped):
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

        # スロップ語彙
        if narrowed is None:
            slop_hits = [word for word in SLOP_WORDS if word in plain_text]
            slop_hits += [word for word, pattern in SLOP_WORD_PATTERNS if re.search(pattern, plain_text)]
        else:
            slop_hits = [word for word in slop_words if word in plain_text]
            slop_hits += [word for word, pattern, required in slop_patterns
                          if _may_match_literals(required, plain_text) and re.search(pattern, plain_text)]
        for word in slop_hits:
            findings.append({
                "rule": "slop_vocabulary",
                "line": line_no,
                "severity": "warn",
                "message": f"AI頻出語彙「{word}」が含まれています。文脈上必要のない比喩や大げさな装飾であれば、ふだん使う自然な表現に置き換えてください。ただし、文字どおりの意味や必要な文脈を担っている場合は残してかまいません。",
                "snippet": line.strip()
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
                        "snippet": line.strip()
                    })
                    break
                continue

            m = pattern.search(plain_text)
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

        # 英語直訳の語
        if narrowed is None:
            translated_hits = (desc for pattern, desc in TRANSLATED_TERM_PATTERNS if re.search(pattern, plain_text))
        else:
            translated_hits = (desc for pattern, desc, required in translated_patterns
                               if _may_match_literals(required, plain_text) and re.search(pattern, plain_text))
        for desc in dict.fromkeys(translated_hits):
            findings.append({
                "rule": "translated_term",
                "line": line_no,
                "severity": "warn",
                "message": f"英語の直訳{desc}が検出されました。ソフトウェアの文脈であれば、開発現場で定着した言い方（「バージョン」「リグレッション」「デグレ」など）や具体的な説明を検討してください。ただし、出版物や製品の種類を表す「版」、回帰テストや回帰分析など定着した用語は残してかまいません。",
                "snippet": line.strip()
            })

        # フィラーパターン（文ごとに見て、同じ型は1行1件）
        for pattern, desc, required in filler_patterns:
            if _may_match_literals(required, plain_text) and any(pattern.search(sentence) for sentence in line_sentences):
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

        for index, sentence in enumerate(line_sentences):
            if ("もちろん、" not in plain_text and "勿論、" not in plain_text):
                break
            if not _SHORT_MOCHIRON.match(sentence) or _MOCHIRON_ANSWER.match(sentence):
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

        # ネガティブパラレリズム
        if "ではなく" in plain_text and plain_text.count("ではなく") == len(_NEGATION_ALSO.findall(plain_text)):
            negation_message = None
        elif _has_negative_parallelism(plain_text) and "ではなく" in plain_text:
            negation_message = "「AではなくB」構文が検出されました。否定を外しても主張が変わらない場合は肯定文を検討してください。ただし、誤解の訂正や見方の切り替えなど意味・比重を担っている否定なら、無理に肯定化せずそのまま残してください。"
        elif (line_no in extra_negation_lines
              or ("でもない。" in plain_text and _NEGATION_EXTRA.search(plain_text))
              or ("じゃない、" in plain_text
                  and any(_NEGATION_JANAI.match(sentence) for sentence in line_sentences))):
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
        if sys.stdin is None:
            print("Error reading stdin: standard input is not available", file=sys.stderr)
            sys.exit(2)
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        try:
            content = sys.stdin.read()
        except (UnicodeDecodeError, OSError) as e:
            print(f"Error reading stdin: {e}", file=sys.stderr)
            sys.exit(2)

    result = lint_text(content)

    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
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
