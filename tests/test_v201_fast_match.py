#!/usr/bin/env python3
"""v2.0.1: diff の速さの直しが、出力を一字も変えないことを見張る。

1. _ExactSequenceMatcher と difflib.SequenceMatcher(None, a, b, autojunk=False) を突き合わせる（種を決めた乱数の組）。
   求め方を選ぶ定数を小さくした組でも回し、小さな文字列でもすべての求め方を通す。
   hash を粗くして（違う部分文字列がよく同じ値になるようにして）も同じ答えになる（hash は手がかりにだけ使う）。
2. 文字列でない並び、捨てる要素（isjunk、autojunk の popular）、文字列の外にはみ出す範囲、int でない位置は、difflib にそのまま任せる。
3. 同じ形の段落の全面書き換え（v2.0.0 では3万字で2分あまりかかった形）と、1字のくり返しの長い文字列が、すぐに終わり、
   difflib と同じ対応になる。
4. 2乗で重かった所（_widen_to_sentences、_pair_gone_sentences、_ending_changes_from_units、_Masker.mask、_rule_candidates、
   _register_changes、_addition_novelty）を、v2.0.0 の書き方（このファイルに写した OLD_ の関数）と突き合わせる。
5. 同じ段落を何百回もくり返す文書で、種で探す段が、次の段落で一致が見つかったところで止まり（残りの段落の種を伸ばさない）、
   difflib と同じ対応になる。
文はすべてこのファイルで作った合成の文。コーパスの組は tests/corpus を読むだけで、書き換えない。
"""

from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict
from pathlib import Path
from unittest import mock
import copy
import difflib
import hashlib
import random
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402


Matcher = yomiyasu_diff._ExactSequenceMatcher

# 求め方を選ぶ定数の組。最初は既定の値（patch.multiple には名前が1つ以上要るので、既定の値をそのまま入れる）。
# ほかは、小さな文字列でも、長さちょうどの表（b の範囲だけの表と b 全体の表）、種（見つかる、見つからない、候補が多すぎる）、
# DP、接尾辞オートマトン、長さの二分探索を通るようにした値。どの値でも答えは同じはず（定数は求め方を選ぶだけ）。
SETTINGS = (
    {"_MATCH_SMALL_AREA": yomiyasu_diff._MATCH_SMALL_AREA},
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 3, "_MATCH_SEED_SHORT": 2, "_MATCH_SEED_LONG": 3, "_MATCH_SAMPLE_MIN": 3,
     "_MATCH_WHOLE_INDEX_MIN": 30},
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 1000, "_MATCH_SEED_SHORT": 3, "_MATCH_SEED_LONG": 5, "_MATCH_SAMPLE_MIN": 4,
     "_MATCH_WHOLE_INDEX_MIN": 0, "_MATCH_PROBE_CACHE": 1},
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 0, "_MATCH_SEED_SHORT": 1, "_MATCH_SEED_LONG": 1, "_MATCH_SAMPLE_MIN": 1,
     "_MATCH_SAM_FACTOR": 0},
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 2, "_MATCH_SEED_SHORT": 4, "_MATCH_SEED_LONG": 6, "_MATCH_SAMPLE_MIN": 5,
     "_MATCH_SAMPLE_BUDGET_DIV": 1, "_MATCH_SAM_FACTOR": 0, "_MATCH_WHOLE_INDEX_MIN": 0},
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 0, "_MATCH_SAMPLE_MIN": 10 ** 9, "_MATCH_SAM_FACTOR": 0,
     "_MATCH_AUTOMATON_MAX": 0},
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 2, "_MATCH_SEED_SHORT": 4, "_MATCH_SEED_LONG": 6, "_MATCH_SAMPLE_MIN": 5,
     "_MATCH_SAMPLE_BUDGET_DIV": 10 ** 9, "_MATCH_SAM_FACTOR": 10 ** 9},
    # 長さの二分探索で、1字ずつずらす hash を使う（3字以上）。2字以下は切り出す hash（同じ二分探索の中で両方を通る）
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 0, "_MATCH_SAMPLE_MIN": 10 ** 9, "_MATCH_SAM_FACTOR": 0,
     "_MATCH_AUTOMATON_MAX": 0, "_MATCH_ROLLING_MIN": 3},
    # b 全体の表がまだない長さで、範囲だけの表で探す（a の側の表と b の側の表）。表は最近使った順に2つまで残す
    {"_MATCH_SMALL_AREA": 0, "_MATCH_PROBE_MAX": 1000, "_MATCH_SAMPLE_MIN": 10 ** 9, "_MATCH_WHOLE_INDEX_MIN": 0,
     "_MATCH_LOCAL_DIV": 1},
)
WORDS = ["設定", "ファイル", "を", "開", "いて", "値", "確認", "します", "。", "、", "\n", "第", "1", "2", "節", "担当者", "は", "結果"]


def _edit(rng, text):
    """text を少し直した写し（足す、消す、置き換える）。"""
    chars = list(text)
    for _ in range(rng.randint(0, 6)):
        position = rng.randint(0, len(chars))
        choice = rng.random()
        if choice < 0.4:
            chars[position:position] = list(rng.choice(["x", "を", "します。", text[:rng.randint(0, 10)]]))
        elif choice < 0.8:
            del chars[position:position + rng.randint(1, 5)]
        else:
            chars[position:position + 2] = list("ん")
    return "".join(chars)


def _pairs(rng, count):
    """突き合わせる組 (a, b)。空、同じもの、字の種類の少ない文字列、語のつなぎ、少し直した写し、くり返し、同じ形の段落、
    含む・含まれる。"""
    out = [("", ""), ("", "abc"), ("abc", ""), ("あいう", "あいう"), ("a" * 50, "a" * 70)]
    for n in range(count):
        kind = n % 8
        if kind == 0:
            alphabet = rng.choice(["a", "ab", "abc", "abcd"])
            a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        elif kind == 1:
            a = "".join(rng.choice(WORDS) for _ in range(rng.randint(0, 60)))
            b = "".join(rng.choice(WORDS) for _ in range(rng.randint(0, 60)))
        elif kind == 2:
            a = "".join(rng.choice("あいうえお") for _ in range(rng.randint(0, 200)))
            b = _edit(rng, a)
        elif kind == 3:
            unit = "".join(rng.choice("abc") for _ in range(rng.randint(1, 6)))
            a = unit * rng.randint(0, 40) + rng.choice(["", "x", unit[:2]])
            b = (unit if rng.random() < 0.5 else unit[::-1]) * rng.randint(0, 40)
        elif kind == 4:
            paragraphs = rng.randint(1, 12)
            a = "\n\n".join("第{}節では値を確認します。担当者は{}回目の結果を残します。".format(i, i % 3) for i in range(paragraphs))
            b = _edit(rng, a.replace("確認します", rng.choice(["確かめます", "確認します", "見ます"])))
        elif kind == 5:
            a = "".join(rng.choice("ab") for _ in range(rng.randint(0, 300)))
            start = rng.randint(0, len(a))
            b = a[start:start + rng.randint(0, 300)]
            if rng.random() < 0.5:
                a, b = b, a
        elif kind == 6:
            a = "".join(rng.choice(WORDS) for _ in range(rng.randint(0, 40)))
            b = a
        else:
            a = "".join(rng.choice("漢字かなカナ。\n") for _ in range(rng.randint(0, 120)))
            b = _edit(rng, a)[::-1] if rng.random() < 0.3 else _edit(rng, a)
        out.append((a, b))
    return out


def _full_rewrite(n):
    """同じ形の段落 n 個の全面書き換え（どの段落も同じ言い回しを書き換える）。"""
    old = ["第{}節では、設定ファイルを開いて値を確認します。担当者は{}回目の結果を残し、翌週に共有します。".format(i, i % 9 + 1)
           for i in range(n)]
    new = ["第{}節では、設定ファイルを開き、値を確かめます。担当者は{}回目の結果を記録して、翌週に共有します。".format(i, i % 9 + 1)
           for i in range(n)]
    return "\n\n".join(old) + "\n", "\n\n".join(new) + "\n"


REPEATED_OLD = ("設定ファイルは起動のたびに読み込まれ、各サービスの接続先と待ち時間と再試行の回数は、この値で決まります。"
                "値が変わったときは、担当者が手順書に沿って確認し、結果を共有の記録に残してから、翌週の定例で報告します。"
                "接続先が応答しないときは、三回まで待ってから次の接続先に切り替え、切り替えたことを監視の画面に表示します。")
REPEATED_NEW = ("設定ファイルは起動のたびに読み込まれ、各サービスの接続先と待ち時間と再試行の回数は、この値で決まります。"
                "値が変わったら、担当者が手順書に沿って確かめ、結果を共有の記録に残してから、翌週の定例で報告します。"
                "接続先が応答しないときは、三回まで待ってから次の接続先に切り替え、切り替えたことを監視の画面に表示します。")


def _repeated_rewrite(n, last=REPEATED_NEW):
    """同じ段落 n 個の書き換え（どの段落も同じ文を同じように書き換える。最後の段落だけ last にできる）。
    書き換えの前後で同じ部分（段落の終わりの文から次の段落の初めの文まで）は100字を超えるので、
    一致の長さの上限が _MATCH_PROBE_MAX より長い範囲を、種で探す段で解く。"""
    return "\n\n".join([REPEATED_OLD] * n) + "\n", "\n\n".join([REPEATED_NEW] * (n - 1) + [last]) + "\n"


class MatcherEquivalenceTests(unittest.TestCase):
    """_ExactSequenceMatcher は difflib.SequenceMatcher(None, a, b, autojunk=False) と同じ答えを返す。"""

    def check_pair(self, a, b, rng):
        expected = difflib.SequenceMatcher(None, a, b, autojunk=False)
        got = Matcher(None, a, b, autojunk=False)
        blocks = got.get_matching_blocks()
        if blocks != expected.get_matching_blocks() or got.get_opcodes() != expected.get_opcodes():
            self.fail("食い違い: {!r} {!r}".format(a, b))
        self.assertTrue(all(type(block) is difflib.Match for block in blocks))
        for _ in range(2):
            alo = rng.randint(0, len(a))
            ahi = rng.randint(alo, len(a))
            blo = rng.randint(0, len(b))
            bhi = rng.randint(blo, len(b))
            match = got.find_longest_match(alo, ahi, blo, bhi)
            if match != expected.find_longest_match(alo, ahi, blo, bhi) or type(match) is not difflib.Match:
                self.fail("find_longest_match の食い違い: {!r} {!r} {}".format(a, b, (alo, ahi, blo, bhi)))

    def test_random_pairs_under_every_setting(self):
        rng = random.Random(20261017)
        for setting in SETTINGS:
            with self.subTest(setting=setting), mock.patch.multiple(yomiyasu_diff, **setting):
                for a, b in _pairs(rng, 400):
                    self.check_pair(a, b, rng)

    def test_every_search_path_is_used(self):
        """上の突き合わせが、すべての求め方を実際に通っている（通らない求め方は、突き合わせで見張れない）。"""
        calls = Counter()

        def counting(name, original):
            def wrapper(*args):
                result = original(*args)
                calls[name, "none" if result is None else "false" if result is False else "found"] += 1
                if name == "_probe_local":       # どちらの側の表で探したか（短いほうの側の表を作る）
                    _, alo, ahi, blo, bhi, _ = args
                    calls[name, "b_side" if bhi - blo <= ahi - alo else "a_side"] += 1
                if name == "_first_of_length":   # 切り出す hash か、1字ずつずらす hash か
                    calls[name, "rolling" if args[5] >= yomiyasu_diff._MATCH_ROLLING_MIN else "sliced"] += 1
                if name == "_seeded" and args[5] >= args[6]:   # 長さが上限と同じ段（一致が見つかった最初の格子の位置で止める）
                    calls[name, "early_" + ("none" if result is None else "false" if result is False else "found")] += 1
                return result
            return wrapper
        patches = [mock.patch.object(Matcher, name, counting(name, getattr(Matcher, name)))
                   for name in ("_dp", "_probe", "_probe_local", "_seeded", "_bisect_length", "_first_of_length")]
        patches.append(mock.patch.object(yomiyasu_diff, "_automaton_longest",
                                         counting("automaton", yomiyasu_diff._automaton_longest)))
        patches.append(mock.patch.object(yomiyasu_diff, "_gram_index", counting("gram_index", yomiyasu_diff._gram_index)))
        rng = random.Random(7)
        for patch in patches:
            patch.start()
        try:
            for setting in SETTINGS:
                with mock.patch.multiple(yomiyasu_diff, **setting):
                    for a, b in _pairs(rng, 120):
                        Matcher(None, a, b, autojunk=False).get_opcodes()
        finally:
            for patch in patches:
                patch.stop()
        for key in (("_dp", "found"), ("_probe", "found"), ("_probe", "none"), ("_probe_local", "found"), ("_probe_local", "none"),
                    ("_probe_local", "a_side"), ("_probe_local", "b_side"), ("_seeded", "found"), ("_seeded", "false"),
                    ("_seeded", "none"), ("_seeded", "early_found"), ("_seeded", "early_false"), ("_seeded", "early_none"),
                    ("automaton", "found"), ("_bisect_length", "found"), ("_first_of_length", "found"),
                    ("_first_of_length", "none"), ("_first_of_length", "sliced"), ("_first_of_length", "rolling"),
                    ("gram_index", "found")):
            with self.subTest(path=key):
                self.assertGreater(calls[key], 0)

    def test_reused_matcher_follows_new_sequences(self):
        """set_seq1、set_seq2、set_seqs で並びを替えても、前の並びの表を使わずに difflib と同じ答えになる。"""
        rng = random.Random(11)
        texts = [a for pair in _pairs(rng, 60) for a in pair] + ["第1節では値を確認します。" * 30]
        for setting in SETTINGS[:3]:
            with self.subTest(setting=setting), mock.patch.multiple(yomiyasu_diff, **setting):
                expected = difflib.SequenceMatcher(None, "", "", autojunk=False)
                got = Matcher(None, "", "", autojunk=False)
                for step in range(150):
                    choice = step % 3
                    if choice == 0:
                        a = rng.choice(texts)
                        expected.set_seq1(a)
                        got.set_seq1(a)
                    elif choice == 1:
                        b = rng.choice(texts)
                        expected.set_seq2(b)
                        got.set_seq2(b)
                    else:
                        a, b = rng.choice(texts), rng.choice(texts)
                        expected.set_seqs(a, b)
                        got.set_seqs(a, b)
                    self.assertEqual(got.get_opcodes(), expected.get_opcodes())
                    self.assertEqual(got.ratio(), expected.ratio())

    def test_coarse_hash_gives_the_same_answers(self):
        """hash を粗くして、違う部分文字列がよく同じ値になるようにしても同じ答えになる（hash は表を引く手がかりにだけ使い、
        引いた位置は必ず字で確かめる。確かめで範囲の外の位置を拾うと、ここで食い違う）。"""
        rng = random.Random(29)
        pairs = _pairs(rng, 80)
        for name, coarse, modulus in (("constant", lambda text: 0, 2), ("two_bits", lambda text: hash(text) & 3, 5)):
            for setting in SETTINGS:
                with self.subTest(hash=name, setting=setting), mock.patch.multiple(yomiyasu_diff, **setting), \
                        mock.patch.object(yomiyasu_diff, "hash", coarse, create=True), \
                        mock.patch.object(yomiyasu_diff, "_ROLLING_MOD", modulus):
                    for a, b in pairs:
                        self.check_pair(a, b, rng)

    def test_rolling_hashes_equal_the_polynomial_of_each_part(self):
        rng = random.Random(31)
        mod, base = yomiyasu_diff._ROLLING_MOD, yomiyasu_diff._ROLLING_BASE
        for _ in range(200):
            codes = [rng.choice((0x3042, 0x3044, 0x61, 0x10FFFF, 0)) for _ in range(rng.randint(0, 30))]
            size = rng.randint(0, 32)
            expected = []
            if size > 0:
                for start in range(len(codes) - size + 1):
                    value = 0
                    for code in codes[start:start + size]:
                        value = (value * base + code) % mod
                    expected.append(value)
            self.assertEqual(list(yomiyasu_diff._rolling_hashes(codes, size)), expected)

    def test_full_rewrite_of_150_paragraphs_equals_difflib(self):
        """7千字の全面書き換え（正規化した文書全体）で、difflib と同じ対応になる（difflib で1秒あまり）。"""
        a, b = _full_rewrite(150)
        o, r = yomiyasu_diff.normalize(a), yomiyasu_diff.normalize(b)
        self.assertEqual(Matcher(None, o, r, autojunk=False).get_opcodes(),
                         difflib.SequenceMatcher(None, o, r, autojunk=False).get_opcodes())

    def test_repeated_paragraphs_under_every_setting(self):
        """同じ段落のくり返しの書き換えで、difflib と同じ答えになる。右の範囲の答えはすぐ次の段落にあり、種で探す段は一致の見つかった
        最初の格子の位置で止まる。最後の段落だけ違う組（書き換えない、途中で切れる、空）も入れ、くり返しの終わりの形も見る。"""
        rng = random.Random(41)
        for setting in SETTINGS:
            for n in (1, 2, 3, 7, 12):
                for last in (REPEATED_NEW, REPEATED_OLD, REPEATED_NEW[:40], ""):
                    with self.subTest(setting=setting, n=n, last=last[:10]), mock.patch.multiple(yomiyasu_diff, **setting):
                        self.check_pair(*_repeated_rewrite(n, last), rng)


class FallbackTests(unittest.TestCase):
    """速い求め方を使えないときは、difflib にそのまま任せる（速い求め方の関数を呼ばない）。"""

    def assert_falls_back(self, isjunk, a, b, autojunk=False):
        expected = difflib.SequenceMatcher(isjunk, a, b, autojunk=autojunk)
        with mock.patch.object(Matcher, "_longest", side_effect=AssertionError("速い求め方を使った")):
            got = Matcher(isjunk, a, b, autojunk=autojunk)
            self.assertEqual(got.get_opcodes(), expected.get_opcodes())
            self.assertEqual(got.find_longest_match(0, len(a), 0, len(b)), expected.find_longest_match(0, len(a), 0, len(b)))
            self.assertEqual(got.ratio(), expected.ratio())

    def test_lists_of_lines_use_difflib(self):
        old = ["見出し\n", "\n", "本文です。\n", "\n", "```\n", "code\n", "```\n"] * 5
        new = ["見出し\n", "\n", "本文を直しました。\n", "\n", "```\n", "code\n", "```\n"] * 4 + ["足した行\n"]
        self.assert_falls_back(None, old, new)

    def test_junk_uses_difflib(self):
        self.assert_falls_back(lambda ch: ch == " ", "設定 を 開いて 値を 確認 します", "設定 を 開き 値を 確かめ ます")

    def test_popular_elements_use_difflib(self):
        """autojunk=True で、b が200字以上あり、1%を超えて出る字（popular）があるとき。"""
        a = "ab" * 150
        b = "a" * 250 + "b" * 10
        self.assertTrue(difflib.SequenceMatcher(None, a, b).bpopular)
        self.assert_falls_back(None, a, b, autojunk=True)

    def test_autojunk_without_popular_elements_matches_difflib(self):
        """autojunk=True でも popular がなければ、捨てる要素がないので速い求め方を使い、difflib と同じ答えになる。"""
        a, b = "設定ファイルを開いて値を確認します。" * 3, "設定ファイルを開き、値を確かめます。" * 3
        expected = difflib.SequenceMatcher(None, a, b)
        self.assertFalse(expected.bpopular)
        self.assertEqual(Matcher(None, a, b).get_opcodes(), expected.get_opcodes())

    def test_str_subclass_uses_difflib(self):
        class Text(str):
            pass
        self.assert_falls_back(None, Text("設定を確認します。"), Text("設定を確かめます。"))

    def test_ranges_outside_the_strings_behave_like_difflib(self):
        a, b = "設定を確認します。", "設定を確かめます。"
        got, expected = Matcher(None, a, b, autojunk=False), difflib.SequenceMatcher(None, a, b, autojunk=False)
        for args in ((-3, 4, 0, 5), (2, 1, 0, len(b)), (0, len(a), 3, 2)):
            with self.subTest(args=args):
                self.assertEqual(got.find_longest_match(*args), expected.find_longest_match(*args))
        for matcher in (got, expected):
            with self.assertRaises(IndexError):
                matcher.find_longest_match(0, len(a) + 1, 0, len(b))

    @staticmethod
    def outcome(matcher, args):
        """find_longest_match の結果（値と型）か、上がった例外（型と文）。"""
        try:
            match = matcher.find_longest_match(*args)
        except Exception as error:  # noqa: BLE001  例外も difflib と同じであることを見る
            return "raised", type(error), str(error)
        return repr(match), type(match), tuple(type(x) for x in match)

    def test_out_of_range_calls_on_long_strings_behave_like_difflib(self):
        """DP で解かない大きさの文字列でも、文字列の外にはみ出す範囲（終わりが長さを超える、始まりが負、範囲が逆）で、
        difflib と同じ値か同じ例外になる（範囲の確かめを外すと、例外の代わりに値を返す呼び方がある）。"""
        a, b = "bababaaab", "ab" * 19 + "a"
        for matcher in (Matcher(None, a, b, autojunk=False), difflib.SequenceMatcher(None, a, b, autojunk=False)):
            with self.assertRaises(IndexError):
                matcher.find_longest_match(1, 10, 9, 1)
        rng = random.Random(37)
        for a, b in [pair for pair in _pairs(rng, 40) if len(pair[0]) * len(pair[1]) > 2048] + [(a, b)]:
            got, expected = Matcher(None, a, b, autojunk=False), difflib.SequenceMatcher(None, a, b, autojunk=False)
            for _ in range(20):
                args = tuple(rng.randint(-3, n + 3) for n in (len(a), len(a), len(b), len(b)))
                self.assertEqual(self.outcome(got, args), self.outcome(expected, args), (a, b, args))

    def test_positions_that_are_not_int_behave_like_difflib(self):
        """True や False を位置に渡しても、difflib と同じ値と型になる（difflib は見つけた一致の位置を int で返す）。"""
        a, b = "x" + "abc" * 100, "abc" * 100 + "y"
        got, expected = Matcher(None, a, b, autojunk=False), difflib.SequenceMatcher(None, a, b, autojunk=False)
        for args in ((True, len(a), 0, len(b)), (1, len(a), False, len(b)), (True, len(a), True, len(b)),
                     (0, len(a), True, True), (False, None, False, None), (1.0, len(a), 0, len(b))):
            with self.subTest(args=args):
                self.assertEqual(self.outcome(got, args), self.outcome(expected, args))


class LargeRewriteTests(unittest.TestCase):
    """同じ形の段落の全面書き換え（v2.0.0 では、3万字で diff に2分あまり、6万字で15分あまりかかった）。"""

    # 590段落の書き換えを正規化した文書全体の opcodes の数と sha256（difflib で求めた値。difflib では2分あまりかかる）
    OPCODES_590 = (4721, "8090fa8f846fb310e1b16f2676beee40fc7cc8d42bb668207f5d8ed8b0f83cb2")

    def test_whole_document_opcodes_equal_difflib(self):
        a, b = _full_rewrite(590)
        o, r = yomiyasu_diff.normalize(a), yomiyasu_diff.normalize(b)
        opcodes = Matcher(None, o, r, autojunk=False).get_opcodes()
        self.assertEqual((len(opcodes), hashlib.sha256(repr(opcodes).encode("utf-8")).hexdigest()), self.OPCODES_590)

    def test_long_runs_of_one_character_finish_quickly(self):
        """1字のくり返し10万字（接尾辞オートマトンを作らない長さ。種の候補が多すぎて、長さの二分探索になる）。
        前の書き方では、二分探索の1段で長さ5万字の部分を10万か所切り出して、30秒あまりかかった。"""
        half = 50000
        a, b = "あ" * (2 * half), "あ" * half + "い" + "あ" * half
        started = time.perf_counter()
        opcodes = Matcher(None, a, b, autojunk=False).get_opcodes()
        self.assertLess(time.perf_counter() - started, 10.0)
        # difflib の答え: いちばん長い一致は5万字で、a と b でいちばん前の (0, 0)。残りの右の範囲も5万字で一致する
        self.assertEqual(opcodes, [("equal", 0, half, 0, half), ("insert", half, half, half, half + 1),
                                   ("equal", half, 2 * half, half + 1, 2 * half + 1)])
        small = 300
        a, b = "あ" * (2 * small), "あ" * small + "い" + "あ" * small
        self.assertEqual(difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes(),
                         [("equal", 0, small, 0, small), ("insert", small, small, small, small + 1),
                          ("equal", small, 2 * small, small + 1, 2 * small + 1)])

    # 同じ段落200個の書き換えを正規化した文書全体の opcodes の数と sha256（difflib で求めた値。difflib では1分あまりかかる）
    OPCODES_REPEATED_200 = (801, "0cc535752cfb3efdc9cad18ec5466c2c74a1fa91e3735a96df9e45e0948adbed")

    def test_repeated_paragraphs_stop_at_the_next_copy(self):
        """同じ段落200個の書き換え。右の範囲の答えはすぐ次の段落にあるので、種で探す段は残りの段落の種を伸ばさない。
        前の書き方は、範囲の中のすべての格子の位置の種を、残りの段落の数だけ伸ばした（伸ばした種は18万あまり。今は4万に届かない）。"""
        a, b = _repeated_rewrite(200)
        o, r = yomiyasu_diff.normalize(a), yomiyasu_diff.normalize(b)
        extended = []
        original = yomiyasu_diff._common_suffix_len

        def counting(*args):
            extended.append(1)
            return original(*args)
        with mock.patch.object(yomiyasu_diff, "_common_suffix_len", counting):
            opcodes = Matcher(None, o, r, autojunk=False).get_opcodes()
        self.assertEqual((len(opcodes), hashlib.sha256(repr(opcodes).encode("utf-8")).hexdigest()), self.OPCODES_REPEATED_200)
        self.assertLess(len(extended), 60000)

    def test_diff_of_30k_chars_finishes_quickly(self):
        a, b = _full_rewrite(590)
        self.assertGreater(len(b), 30000)
        started = time.perf_counter()
        result = yomiyasu_diff.diff(a, b)
        self.assertLess(time.perf_counter() - started, 30.0)
        self.assertTrue(result["changed"])
        self.assertEqual(len(result["full_diff"]["hunks"]), 590)


# ---- v2.0.0 の書き方（突き合わせの基準。scripts/yomiyasu_diff.py の v2.0.0 から写した）----

def OLD_widen_to_sentences(groups, moved, r_spans):
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


def OLD_pair_gone_sentences(o, r, opcodes, groups, moved, gone, r_spans):
    _bigrams = yomiyasu_diff._bigrams

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


def OLD_ending_changes_from_units(ou, ru):
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


def OLD_mask(self, text, start):
    end = start + len(text)
    first = max(0, bisect_right(self.lefts, start) - 1)
    pieces, cursor = [], start
    for left, right in self.spans[first:]:
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


def OLD_rule_candidates(orig_raw, rw_raw, stance=None):
    d = yomiyasu_diff
    o, r = d.normalize(orig_raw), d.normalize(rw_raw)
    out = {"markers": [], "new_words": [], "lost_words": [], "structure": [], "spans": [], "logic": d.logic_points(rw_raw),
           "bold": d.bold_problems(rw_raw)}
    rw_units, flags = d.stance_flags(rw_raw, stance)
    orig_units, orig_flags = d.stance_flags(orig_raw, stance)
    out["endings"] = {"stance": stance, "changes": d._ending_changes_from_units(orig_units, rw_units),
                      "flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in flags],
                      "orig_flags": [{"note": n, "sentences": [x["sentence"] for x in rows]} for n, rows in orig_flags]}
    opcodes = d._ExactSequenceMatcher(None, o, r, autojunk=False).get_opcodes() if o != r else []
    out["type_changes"] = d._type_changes(o, r, opcodes)
    for name, pat in d._MARKER_REGEXES:
        a, b = len(pat.findall(o)), len(pat.findall(r))
        if a != b:
            hits_r = [m.group(0) for m in pat.finditer(r)]
            hits_o = [m.group(0) for m in pat.finditer(o)]
            out["markers"].append({"kind": name, "orig": a, "rewrite": b,
                                   "orig_hits": hits_o, "rewrite_hits": hits_r})
    o_words = set(d.CONTENT.findall(o))
    r_words = set(d.CONTENT.findall(r))
    out["new_words"] = sorted(w for w in r_words if w not in o)
    out["lost_words"] = sorted(w for w in o_words if w not in r)
    if d.has_list(orig_raw) and not d.has_list(rw_raw):
        out["structure"].append("箇条書きを地の文にした。各項目の文末（指示・説明・評価）が元と同じか見る")
    po, pr = len(d.paragraphs(orig_raw)), len(d.paragraphs(rw_raw))
    if pr < po:
        out["structure"].append(f"段落をまとめた（{po} → {pr}）。まとめた段落の話題が1つか見る")
    if len(d.sentences(r)) != len(d.sentences(o)):
        out["structure"].append(f"文の数が変わった（{len(d.sentences(o))} → {len(d.sentences(r))}）")
    if o != r:
        for tag, i1, i2, j1, j2 in opcodes:
            if tag in ("insert", "replace"):
                seg = r[j1:j2]
                around = r[max(0, j1 - 3):j2 + 3]
                kinds = [n for n, p in d._MARKER_REGEXES if p.search(around)]
                words = [w for w in d.CONTENT.findall(seg) if w not in o]
                if kinds or words:
                    out["spans"].append({"added": seg, "was": o[i1:i2], "kinds": kinds, "new_words": words,
                                         "where": d.context(r, j1, j2)})
    return out


OLD_COVERAGE = Counter()     # 下の写しで、組にならなかった原文の文の前後の組を探した回数（突き合わせがその道を通ったか見るため）


def OLD_register_changes(sides, groups, politeness):
    d = yomiyasu_diff
    threshold = {"min_sentences": 3, "min_ratio": 0.5}
    if any(c["subkind"] == "polite_ratio" for c in politeness.get("candidates", [])):
        return d._review_section([], threshold=threshold, skipped_by="politeness")
    masks = (d._Masker(sides, 0), d._Masker(sides, 1))

    def eligible(side, body):
        return (body is not None and body.text.strip() and d._outside_quote(sides, side, body)
                and not d._DIALOGUE.fullmatch(sides.lines[side][body.line - 1].strip()))

    counts = []
    for side in (0, 1):
        found = Counter(d._register_of(b.text) for b in d._all_bodies(sides, side, masks[side]) if eligible(side, b))
        counts.append({"plain": found["常体"], "polite": found["敬体"]})
    changes = {"to_polite": [], "to_plain": []}
    kinds = {("常体", "敬体"): "to_polite", ("敬体", "常体"): "to_plain"}
    for group in groups:
        olds = [masks[0].body(s) for s in group["old"]]
        news = [masks[1].body(s) for s in group["new"]]
        new_registers = [d._register_of(b.text) if eligible(1, b) else "" for b in news]
        order = sorted(group["pairs"])
        paired_old = set(i for i, _ in order)
        found = []
        for i, j in order:
            if not eligible(0, olds[i]) or not new_registers[j]:
                continue
            kind = kinds.get((d._register_of(olds[i].text), new_registers[j]))
            if kind:
                found.append((i, kind, olds[i], news[j]))
        for i, old in enumerate(olds):
            if i in paired_old or not eligible(0, old) or len(old.text) < 4:
                continue
            source = d._register_of(old.text)
            if not source:
                continue
            earlier = [b for a, b in order if a < i]
            later = [b for a, b in order if a > i]
            OLD_COVERAGE["earlier", bool(earlier)] += 1
            OLD_COVERAGE["later", bool(later)] += 1
            low = earlier[-1] if earlier else 0
            high = later[0] if later else len(news) - 1
            if high - low > 5:
                middle = min(len(news) - 1, i * len(news) // max(1, len(olds)))
                low, high = max(low, middle - 2), min(high, middle + 3)
            for k in range(max(0, low), min(len(news), high + 1)):
                kind = kinds.get((source, new_registers[k]))
                if kind and d._contained(old.text, news[k].text) >= 0.6:
                    found.append((i, kind, old, news[k]))
                    break
        for _, kind, old, new in sorted(found, key=lambda item: item[0]):
            changes[kind].append((old, new))
    out = []
    for kind, source, target in (("to_polite", "plain", "polite"), ("to_plain", "polite", "plain")):
        pairs = changes[kind]
        if len(pairs) < threshold["min_sentences"] or len(pairs) < threshold["min_ratio"] * max(1, counts[0][source]):
            continue
        out.append(d._review_candidate(kind, pairs[0][0], pairs[0][1],
                   {"pattern": "unified" if counts[0][target] > counts[0][source] else "switched",
                    "switched": len(pairs), "old_counts": counts[0], "new_counts": counts[1],
                    "lines": [[old.line, new.line] for old, new in pairs[:5]]}))
    return d._review_section(out, threshold=threshold, skipped_by=None)


def OLD_addition_novelty(span, old_doc):
    words = [w for w in yomiyasu_diff._ADD_CONTENT.findall(span)]
    if not words:
        return 0.0
    new = [w for w in words if w not in old_doc and not any(w[i:i + 2] in old_doc for i in range(len(w) - 1))]
    return len(new) / float(len(words))


# 文の種類の印（伝聞、推量、意見、例え、依頼・決まり）、伏せる範囲（コード、URL）を含む合成の文
POOL = ["設定ファイルを開いて値を確認します。", "結果は翌週に共有してください。", "原因はログにあるでしょう。",
        "この手順は必要だと思います。", "担当者によると、障害は昨夜に起きたそうです。", "まるで別の画面のようだ。",
        "`config.yaml` の値を見ます。", "詳しくは https://example.com/docs を読んでください。", "値は3日で消えます。",
        "必ず保存しなければなりません。", "表示が遅いかもしれません。", "次の版で直す予定です。", "本当に助かりました！",
        "なぜ止まったのか？", "- 手順を1つずつ確かめます。", "## 準備"]
ENDINGS = (("します。", "してください。"), ("でしょう。", "です。"), ("と思います。", "です。"), ("そうです。", "ます。"),
           ("ください。", "ます。"), ("ようだ。", "だ。"), ("！", "。"), ("？", "。"))


# 原因の語（ため、によって、ので）を足した推敲（_addition_novelty を、原文にない語があるときとないときの両方で通す）
CAUSAL_PAIRS = (("表示が遅いです。設定を見直しました。\n", "表示が遅いです。キャッシュ設定を見直したため、表示が速くなりました。\n"),
                ("ログを確認しました。原因は不明です。\n", "ログを確認しました。メモリ不足によって、処理が止まりました。\n"),
                ("処理が止まりました。\n", "サーバーが過負荷だったので、処理が止まりました。\n"),
                ("設定を見直しました。表示が速くなりました。\n", "設定を見直したため、表示が速くなりました。\n"))


def _document(rng, sentences):
    """文を段落（1〜3文）に分けてつなぐ。"""
    out, line = [], []
    for sentence in sentences:
        line.append(sentence)
        if sentence.startswith(("- ", "## ")) or len(line) >= rng.randint(1, 3):
            out.append("".join(line))
            line = []
    if line:
        out.append("".join(line))
    return "\n\n".join(out) + "\n"


def _generated_pairs(rng, count):
    """消す、動かす、文末や印を変える、足す、つなぐ推敲をした組。"""
    pairs = []
    for _ in range(count):
        old = [rng.choice(POOL) for _ in range(rng.randint(4, 16))]
        new = list(old)
        for _ in range(rng.randint(1, 6)):
            if not new:
                break
            k = rng.randrange(len(new))
            choice = rng.random()
            if choice < 0.2:
                del new[k]
            elif choice < 0.4:
                new.insert(rng.randrange(len(new) + 1), new.pop(k))
            elif choice < 0.7:
                before, after = rng.choice(ENDINGS)
                new[k] = new[k].replace(before, after)
            elif choice < 0.85:
                new.insert(k, rng.choice(POOL).replace("。", "ね。"))
            elif k + 1 < len(new):
                new[k:k + 2] = [new[k].rstrip("。") + "、" + new[k + 1]]
        pairs.append((_document(rng, old), _document(rng, new)))
    return pairs


class SecondaryEquivalenceTests(unittest.TestCase):
    """2乗で重かった所の新しい書き方が、v2.0.0 の書き方と同じ結果になり、渡した範囲を同じに書き換える。"""

    def test_real_calls_match_v200(self):
        """diff() の中の実際の呼び出しで、新旧を同じ入力の写しにかけて比べる（コーパスの組と、合成の推敲の組）。"""
        calls = Counter()
        new_widen = yomiyasu_diff._widen_to_sentences
        new_pair = yomiyasu_diff._pair_gone_sentences
        new_endings = yomiyasu_diff._ending_changes_from_units
        new_mask = yomiyasu_diff._Masker.mask
        new_rule = yomiyasu_diff._rule_candidates
        new_register = yomiyasu_diff._register_changes
        new_novelty = yomiyasu_diff._addition_novelty

        def widen(groups, moved, r_spans):
            expected = copy.deepcopy((groups, moved))
            OLD_widen_to_sentences(expected[0], expected[1], r_spans)
            new_widen(groups, moved, r_spans)
            self.assertEqual((groups, moved), expected)
            calls["widen"] += 1

        def pair(o, r, opcodes, groups, moved, gone, r_spans):
            expected_groups, expected_moved = copy.deepcopy((groups, moved))
            expected = OLD_pair_gone_sentences(o, r, opcodes, expected_groups, expected_moved, list(gone), list(r_spans))
            got = new_pair(o, r, opcodes, groups, moved, gone, r_spans)
            self.assertEqual((got, groups, moved), (expected, expected_groups, expected_moved))
            calls["pair"] += 1
            return got

        def endings(ou, ru):
            expected = OLD_ending_changes_from_units(ou, ru)
            got = new_endings(ou, ru)
            self.assertEqual(got, expected)
            calls["endings", bool(got)] += 1
            return got

        def mask(masker, text, start):
            got = new_mask(masker, text, start)
            self.assertEqual(got, OLD_mask(masker, text, start))
            calls["mask", got != text] += 1
            return got

        def rule(orig_raw, rw_raw, stance=None):
            got = new_rule(orig_raw, rw_raw, stance)
            self.assertEqual(got, OLD_rule_candidates(orig_raw, rw_raw, stance))
            calls["rule", bool(got["new_words"]), any(span["new_words"] for span in got["spans"])] += 1
            return got

        def register(sides, groups, politeness):
            got = new_register(sides, groups, politeness)
            self.assertEqual(got, OLD_register_changes(sides, groups, politeness))
            calls["register"] += 1
            return got

        def novelty(span, old_doc, old_bigrams=None):
            got = new_novelty(span, old_doc, old_bigrams)
            self.assertEqual(got, OLD_addition_novelty(span, old_doc))
            calls["novelty", old_bigrams is not None, got > 0] += 1
            return got

        rng = random.Random(5)
        OLD_COVERAGE.clear()
        pairs = _generated_pairs(rng, 60) + list(CAUSAL_PAIRS)
        for raw in sorted((CORPUS / "raw_ai").glob("*.md"))[:8]:
            rewritten = CORPUS / "yomiyasu_rewritten" / raw.name
            if rewritten.is_file():
                pairs.append((raw.read_text(encoding="utf-8"), rewritten.read_text(encoding="utf-8")))
        with mock.patch.object(yomiyasu_diff, "_widen_to_sentences", widen), \
                mock.patch.object(yomiyasu_diff, "_pair_gone_sentences", pair), \
                mock.patch.object(yomiyasu_diff, "_ending_changes_from_units", endings), \
                mock.patch.object(yomiyasu_diff._Masker, "mask", mask), \
                mock.patch.object(yomiyasu_diff, "_rule_candidates", rule), \
                mock.patch.object(yomiyasu_diff, "_register_changes", register), \
                mock.patch.object(yomiyasu_diff, "_addition_novelty", novelty):
            for index, (a, b) in enumerate(pairs):
                yomiyasu_diff.diff(a, b, doc_type=(None, "mail", "article")[index % 3])
        for key in ("widen", "pair", ("endings", True), ("endings", False), ("mask", True), ("mask", False),
                    ("rule", True, True), ("rule", False, False), "register", ("novelty", True, True),
                    ("novelty", True, False)):
            with self.subTest(call=key):
                self.assertGreater(calls[key], 0)
        for key in (("earlier", True), ("earlier", False), ("later", True), ("later", False)):
            with self.subTest(register=key):
                self.assertGreater(OLD_COVERAGE[key], 0)

    def test_widen_matches_v200_on_random_spans(self):
        """形の崩れた範囲（始まり > 終わり、幅0、同じ範囲の重なり）も含めて、新旧が同じ端にする。"""
        rng = random.Random(9)
        for _ in range(400):
            cuts = sorted(rng.sample(range(1, 200), rng.randint(1, 12)))
            r_spans = [(x, y) for x, y in zip([0] + cuts, cuts + [200]) if rng.random() < 0.8]

            def span():
                a = rng.randint(0, 200)
                b = a + rng.randint(-3 if rng.random() < 0.1 else 0, 30)
                return a, b
            groups = [[["文"], [(0, 1)], *span()] for _ in range(rng.randint(0, 10))]
            if groups and rng.random() < 0.3:
                groups.append([["同じ"], [(0, 1)], groups[0][2], groups[0][3]])
            moved = [(["文"], [(0, 1)], *span()) for _ in range(rng.randint(0, 4))]
            expected = copy.deepcopy(groups)
            OLD_widen_to_sentences(expected, moved, r_spans)
            yomiyasu_diff._widen_to_sentences(groups, moved, r_spans)
            self.assertEqual(groups, expected)

    def test_pair_gone_matches_v200_on_random_documents(self):
        """字の種類の少ない文で、共通の2文字の組の数が組にする下限の前後になる形を多く作り、新旧が同じ組と同じ書き換えをする。"""
        rng = random.Random(23)
        letters = "あいうえおかき"

        def text(count):
            return "".join("".join(rng.choice(letters) for _ in range(rng.randint(2, 9))) + "。" for _ in range(count))
        for _ in range(300):
            o, r = text(rng.randint(1, 8)), text(rng.randint(1, 8))
            r_spans = yomiyasu_diff._sentence_spans(r)
            o_spans = yomiyasu_diff._sentence_spans(o)
            gone = [(o[s:e].strip(), s, e) for s, e in o_spans if rng.random() < 0.6]
            groups = []
            for s, e in o_spans:
                if rng.random() < 0.4:
                    a = rng.randint(0, len(r) - 1)
                    groups.append([[o[s:e].strip()], [(s, e)], a, min(len(r), a + rng.randint(1, 12))])
            groups.sort(key=lambda g: g[2])
            moved = [([o[s:e].strip()], [(s, e)], a, b) for (s, e), (a, b) in zip(o_spans, r_spans) if rng.random() < 0.2]
            expected_groups, expected_moved = copy.deepcopy((groups, moved))
            expected = OLD_pair_gone_sentences(o, r, [], expected_groups, expected_moved, gone, r_spans)
            got = yomiyasu_diff._pair_gone_sentences(o, r, [], groups, moved, gone, r_spans)
            self.assertEqual((got, groups, moved), (expected, expected_groups, expected_moved))

    def test_overlapping_matches_the_full_scan(self):
        rng = random.Random(13)
        for _ in range(300):
            items = []
            for _ in range(rng.randint(0, 15)):
                a = rng.randint(0, 100)
                items.append([None, None, a, a + rng.randint(-2, 40)])
            spans = [(x, x + rng.randint(0, 30)) for x in sorted(rng.randint(0, 100) for _ in range(rng.randint(0, 10)))]
            expected = [[x for x in items if x[2] < b and a < x[3]] for a, b in spans]
            got = yomiyasu_diff._overlapping(items, spans)
            self.assertEqual(got, expected)
            self.assertTrue(all(g is e for gs, es in zip(got, expected) for g, e in zip(gs, es)))

    def test_ending_changes_match_v200_on_random_units(self):
        """空の文、同じ文のくり返し、共通の字のない文も含めて、新旧が同じ組を返す。
        ratio をすべての組で _ExactSequenceMatcher で求めるとき（_ENDING_EXACT_AREA が0）も同じ。"""
        rng = random.Random(17)
        pieces = ["設定", "を", "確認", "します", "してください", "でしょう", "。", "値", "", "x", "結果", "です"]
        kinds = ["動作（〜します）", "依頼", "推量・考え", "断定（〜です）"]
        for area in (yomiyasu_diff._ENDING_EXACT_AREA, 0):
            with self.subTest(area=area), mock.patch.object(yomiyasu_diff, "_ENDING_EXACT_AREA", area):
                for _ in range(300):
                    def units(count):
                        return [{"sentence": "".join(rng.choice(pieces) for _ in range(rng.randint(0, 5))),
                                 "kind": rng.choice(kinds), "where": rng.choice(["地の文", "箇条書き"])} for _ in range(count)]
                    ou, ru = units(rng.randint(0, 12)), units(rng.randint(0, 12))
                    self.assertEqual(yomiyasu_diff._ending_changes_from_units(ou, ru), OLD_ending_changes_from_units(ou, ru))

    def test_ending_changes_of_long_sentences_match_v200(self):
        """字の種類の少ない長い文（「。」のない数百字の1文）の組は _ExactSequenceMatcher で比べ、新旧が同じ組を返す。"""
        rng = random.Random(41)
        kinds = ["動作（〜します）", "推量・考え"]
        used = Counter()
        original_ratio = Matcher.ratio

        def counting_ratio(matcher):
            used["exact"] += 1
            return original_ratio(matcher)
        with mock.patch.object(Matcher, "ratio", counting_ratio):
            for _ in range(6):
                def sentence():
                    text = "".join(rng.choice("ああい") for _ in range(rng.randint(300, 900)))
                    return text + rng.choice(["します", "でしょう"])
                ou = [{"sentence": sentence(), "kind": rng.choice(kinds), "where": "地の文"} for _ in range(3)]
                ru = [{"sentence": _edit(rng, y["sentence"]), "kind": rng.choice(kinds), "where": "地の文"} for y in ou]
                got = yomiyasu_diff._ending_changes_from_units(ou, ru)
                self.assertEqual(got, OLD_ending_changes_from_units(ou, ru))
        self.assertGreater(used["exact"], 0)

    def test_one_long_sentence_finishes_quickly(self):
        """「。」のない2万字の1文の書き換え（difflib の ratio では20秒あまりかかった）。"""
        half = 10000
        old = "あ" * (2 * half) + "\n"
        new = "あ" * (half - 1) + "い" + "あ" * half + "\n"
        started = time.perf_counter()
        result = yomiyasu_diff.diff(old, new)
        self.assertLess(time.perf_counter() - started, 10.0)
        self.assertTrue(result["changed"])

    def test_neighbor_pairs_match_the_full_scan(self):
        """_register_changes の、組にならなかった原文の文の前後の組（v2.0.0 は組をすべて見て求めていた）。"""
        rng = random.Random(43)
        for _ in range(500):
            order = sorted({(rng.randint(0, 12), rng.randint(0, 12)) for _ in range(rng.randint(0, 10))})
            firsts = [a for a, _ in order]
            last = rng.randint(0, 20)
            for i in range(-1, 15):
                earlier = [b for a, b in order if a < i]
                later = [b for a, b in order if a > i]
                expected = (earlier[-1] if earlier else 0, later[0] if later else last)
                self.assertEqual(yomiyasu_diff._neighbor_pairs(order, firsts, i, last), expected, (order, i))

    def test_addition_novelty_with_bigrams_matches_v200(self):
        """原文の2字の組の集まりを渡したときも、v2.0.0 の書き方と同じ割合になる（語が原文にある、2字だけある、どちらもない）。"""
        rng = random.Random(47)
        letters = "設定値確認原因不明メモリ不足キャッシュサーバー過負荷abcXYZ12"
        for _ in range(400):
            old_doc = "".join(rng.choice(letters + "。、") for _ in range(rng.randint(0, 60)))
            span = "".join(rng.choice(letters + "がをに。") for _ in range(rng.randint(0, 30)))
            grams = {old_doc[k:k + 2] for k in range(len(old_doc) - 1)}
            expected = OLD_addition_novelty(span, old_doc)
            self.assertEqual(yomiyasu_diff._addition_novelty(span, old_doc), expected)
            self.assertEqual(yomiyasu_diff._addition_novelty(span, old_doc, grams), expected)

    def test_mask_matches_v200_on_random_spans(self):
        rng = random.Random(19)
        for _ in range(300):
            masker = object.__new__(yomiyasu_diff._Masker)
            spans = []
            for _ in range(rng.randint(0, 12)):
                left = rng.randint(0, 80)
                spans.append((left, left + rng.randint(0, 10)))
            masker.spans = sorted(spans)
            masker.lefts = [left for left, _ in masker.spans]
            start = rng.randint(0, 80)
            text = "".join(rng.choice("あいう`x") for _ in range(rng.randint(0, 30)))
            self.assertEqual(yomiyasu_diff._Masker.mask(masker, text, start), OLD_mask(masker, text, start))


if __name__ == "__main__":
    unittest.main()
