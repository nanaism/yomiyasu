"""v2.3.0: diff の _pair_gone_sentences が、消えた文の2文字の組の集合ごとに1回だけ数えて使い回すようにした直しの試験。

同じ段落をくり返す文書では同じ文が何度も消えるので、前は消えた文ごとに、同じ組を持つ書き直した文をすべて数えていた。
この試験は、直す前の書き方（v2.2.2 の _pair_gone_sentences を写した _pair_gone_reference）と、diff() の結果が一字も違わないことを
確かめる。文はすべて合成の文。
"""
from collections import Counter
from pathlib import Path
import json
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402
from yomiyasu_diff import _bigrams, _overlapping  # noqa: E402,F401


def _pair_gone_reference(o, r, opcodes, groups, moved, gone, r_spans):
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


SENTENCES = ("原因はキャッシュだと思います。", "明日の作業は中止になるらしい。", "この設定は見直すべきだ。", "まるで迷路のようだ。", "設定の値を確認しました。", "画面の表示を修正します。", "結果は表にまとめました。", "テストは毎晩動かしています。",
             "担当者は田中さんです。", "期限は10月20日です。", "必ず保存してください。", "この手順は使いません。",
             "費用は3万円でした。", "原因はまだ分かっていません。", "古い記録を消しました。", "承認は部長が行います。")
EDITS = (lambda s: s.replace("しました", "した"), lambda s: s.replace("です", "でした"), lambda s: s + "ただし例外があります。",
         lambda s: "", lambda s: s.replace("10月20日", "10月21日"), lambda s: s.replace("使いません", "使います"),
         lambda s: s.replace("。", "、念のため。"), lambda s: s.replace("と思います", "と考えられます"),
         lambda s: s.replace("らしい", "そうだ"), lambda s: s.replace("べきだ", "たほうがよい"))


def pair(rng):
    para = [rng.choice(SENTENCES) for _ in range(rng.randint(2, 6))]
    a, b = [], []
    for _ in range(rng.randint(1, 30)):
        pa = list(para) if rng.random() < 0.8 else [rng.choice(SENTENCES) for _ in range(rng.randint(1, 5))]
        pb = [rng.choice(EDITS)(s) if rng.random() < 0.4 else s for s in pa]
        if rng.random() < 0.3:
            pb = pb[1:] + pb[:1]
        a.append("".join(pa))
        b.append("".join(x for x in pb if x))
    sep = rng.choice(("\n\n", "\n"))
    return sep.join(a) + "\n", sep.join(b) + "\n"


def run(original, revised, doc_type, function):
    saved = yomiyasu_diff._pair_gone_sentences
    yomiyasu_diff._pair_gone_sentences = function
    try:
        return json.dumps(yomiyasu_diff.diff(original, revised, doc_type=doc_type), ensure_ascii=False, sort_keys=True)
    finally:
        yomiyasu_diff._pair_gone_sentences = saved


class PairGoneReuseTest(unittest.TestCase):
    def test_same_result_as_before_on_repeated_paragraphs(self):
        rng = random.Random(20261024)
        for number in range(60):
            original, revised = pair(rng)
            for doc_type in (None, "article"):
                with self.subTest(number=number, doc_type=doc_type):
                    self.assertEqual(run(original, revised, doc_type, yomiyasu_diff._pair_gone_sentences),
                                     run(original, revised, doc_type, _pair_gone_reference))

    def test_each_distinct_gone_sentence_is_counted_once(self):
        """同じ文が何度も消える文書で、書き直した文を数える Counter を、中身の違う消えた文の数だけ作る（前は消えた文の数だけ作っていた）。"""
        # 文の種類の印（「と思います」）があるときだけ組を探すので、意見の文を入れ、文の順を入れ替えて書き直す
        para = "原因はキャッシュだと思います。取りこぼした通知は、翌朝の再送ジョブが拾います。設定の値は毎晩確認しています。"
        rewrite = "送信に失敗した通知は、翌朝の再送ジョブがもう一度送ります。原因はキャッシュだと考えられます。設定の値は、毎晩チェックしています。"
        original = "\n\n".join([para] * 120) + "\n"
        revised = "\n\n".join([rewrite] * 120) + "\n"
        seen = {}
        real_counter = yomiyasu_diff.Counter
        real_function = yomiyasu_diff._pair_gone_sentences

        class Counting(real_counter):
            def __init__(self, *args, **kwargs):
                seen["counters"] = seen.get("counters", 0) + 1
                super().__init__(*args, **kwargs)

        def wrapped(o, r, opcodes, groups, moved, gone, r_spans):
            seen["gone"] = seen.get("gone", 0) + len(gone)
            seen["distinct"] = seen.get("distinct", 0) + len({frozenset(_bigrams(text)) for text, _, _ in gone})
            yomiyasu_diff.Counter = Counting
            try:
                return real_function(o, r, opcodes, groups, moved, gone, r_spans)
            finally:
                yomiyasu_diff.Counter = real_counter
        yomiyasu_diff._pair_gone_sentences = wrapped
        try:
            yomiyasu_diff.diff(original, revised)
        finally:
            yomiyasu_diff._pair_gone_sentences = real_function
        self.assertGreaterEqual(seen.get("gone", 0), 120)
        self.assertLessEqual(seen["distinct"], 4)
        self.assertEqual(seen.get("counters", 0), seen["distinct"])

if __name__ == "__main__":
    unittest.main()
