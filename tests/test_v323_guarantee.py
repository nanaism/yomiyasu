#!/usr/bin/env python3
"""v3.2.3: diff の「原文にない保証」と「原文にない再発防止の誓い」の同じ言い方の比べ（3.2.2）で、以外 のすぐあとに も・でも・にも が
付いた形（法人会員以外も）を、範囲を広げる言い方として 以外は・を除き と別の種類（以外も）にする直しの試験。

3.2.2 は、範囲や条件を決める語の種類を句の前の語に残して比べるようにしたが、以外 と を除き を同じ種類にし、以外 のすぐあとの
も・でも・にも を外す助詞として先に外してから種類を読んだので、法人会員を除き（範囲を狭める）と 法人会員以外も（範囲を広げる）を
同じ言い方にしていた。そのため、範囲を広げるか狭める推敲（法人会員を除き、→ 法人会員以外も、とその逆）に、3.2.0 と 3.2.1 が出して
いた候補を出さなくなっていた（v3.2.2 の公開のあとの確かめで見つかった形）。3.2.3 からは、以外 のすぐあとに も・でも・にも が付いた
形を 以外も という種類にする。以外も・以外でも・以外にも どうしは同じ種類なので、この言い換えには出さない。以外は と 以外も の
入れ替え（範囲が逆になる）には、3.2.0 と同じく出す（3.2.1 と 3.2.2 は出さなかった）。以外 と助詞のあいだに太字やかぎかっこが挟まる形（**法人会員以外**も）と、も で終わる長い助詞
（においても、に関しても）と まで も、範囲を広げる言い方として同じ種類にする（3.2.3 の1回目のレビューの指摘）。文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402


C = "引き続きご利用いただけます。"
F = "追加の費用は発生いたしません。"
V = "再発しないよう、監視を強化してまいります。"


def run(before, after):
    return yomiyasu_diff.diff(before + "\n", after + "\n")


def promise_kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"] if risk["kind"] == "promise"]


# 出す組（範囲を広げるか狭める。3.2.0 と 3.2.1 は出し、3.2.2 は出さなかった）: (元, 後, subkind)
RESTORED = [
    ("法人会員を除き、" + C, "法人会員以外も、" + C, "guarantee"),
    ("法人会員以外も、" + C, "法人会員を除き、" + C, "guarantee"),
    ("法人会員を除き、" + C, "法人会員以外でも、" + C, "guarantee"),
    ("法人会員を除き、" + C, "法人会員以外にも、" + C, "guarantee"),
    ("法人会員を除いて、" + F, "法人会員以外も、" + F, "guarantee"),
    ("法人会員をのぞき、" + C, "法人会員以外も、" + C, "guarantee"),
    ("本体を除き担保されます。", "本体以外も担保されます。", "guarantee"),
    ("本番環境を除き、" + V, "本番環境以外も、" + V, "prevention"),
    ("法人会員を除き、" + C, "法人会員以外に関しても、" + C, "guarantee"),
    ("本番環境を除き、" + V, "本番環境以外においても、" + V, "prevention"),
    ("法人会員を除き、" + C, "**法人会員以外**も、" + C, "guarantee"),
    ("法人会員を除き、" + C, "法人会員以外まで、" + C, "guarantee"),
]

# 出す組（以外は・以外 と 以外も の入れ替え。範囲が逆になる。3.2.0 も出し、3.2.1 と 3.2.2 は出さなかった）: (元, 後)
NEWLY = [
    ("法人会員以外は、" + C, "法人会員以外も、" + C),
    ("スマートフォン以外は" + C, "スマートフォン以外でも、" + C),
    ("法人会員以外、" + C, "法人会員以外にも、" + C),
    ("法人会員以外については、" + C, "法人会員以外についても、" + C),
]

# 出さない組（同じ種類の言い換え、飾りの付け外し、句の前の語の前だけを直した推敲。3.2.1 と 3.2.2 も出さない。を除き → 以外は は 3.2.2 から）: (元, 後)
KEPT = [
    ("法人会員以外も、" + C, "法人会員以外でも、" + C),
    ("法人会員以外も、" + C, "法人会員以外にも、" + C),
    ("法人会員を除き、" + C, "法人会員以外は、" + C),
    ("なお、法人会員以外も、" + C, "法人会員以外も、" + C),
    ("法人会員以外も、" + C, "法人会員以外も " + C),
    ("本番環境以外においても、" + V, "本番環境以外でも、" + V),
    ("法人会員以外に関しても、" + F, "法人会員以外も、" + F),
    ("**法人会員以外**も、" + C, "法人会員以外も、" + C),
    ("「法人会員以外」も、" + C, "法人会員以外も、" + C),
    ("法人会員以外まで、" + C, "法人会員以外も、" + C),
]

# 出す組（3.2.1 と 3.2.2 も出す。以外も と に限らず は別の種類、以外の方も は句の前の語が 方 になる）: (元, 後)
CHANGED_AS_322 = [
    ("法人会員以外も、" + C, "法人会員に限らず、" + C),
    ("法人会員を除き、" + C, "法人会員以外の方も、" + C),
]


class ScopeTest(unittest.TestCase):
    def test_restored_is_reported(self):
        for before, after, subkind in RESTORED:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertIn(("promise", subkind), promise_kinds(result), result["meaning_risks"])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_newly_reported(self):
        for before, after in NEWLY:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertIn(("promise", "guarantee"), promise_kinds(result), result["meaning_risks"])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_kept_is_not_reported(self):
        for before, after in KEPT:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(promise_kinds(result), [], result["meaning_risks"])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_changed_as_322_is_reported(self):
        for before, after in CHANGED_AS_322:
            with self.subTest(before=before, after=after):
                self.assertIn(("promise", "guarantee"), promise_kinds(run(before, after)))


class WordingTest(unittest.TestCase):
    def wording(self, text):
        return [yomiyasu_diff._addition_promise_wording(text, pos, key, name)
                for sub, name, key, pos, _ in yomiyasu_diff._addition_promise_clauses(text) if sub in ("guarantee", "prevention")]

    def test_inclusive_kind(self):
        """以外 のあとに範囲を広げる助詞が付いた形は 以外も の種類。以外は・以外・を除き は 以外 の種類のまま。"""
        self.assertEqual(self.wording("法人会員以外も、" + C), [("法人会員以外も", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員以外でも、" + C), [("法人会員以外も", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員以外にも、" + F), [("法人会員以外も", "追加の費用は発生いたしません")])
        self.assertEqual(self.wording("法人会員以外は、" + C), [("法人会員以外", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員以外、" + C), [("法人会員以外", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員を除き、" + C), [("法人会員以外", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員以外の方も、" + C), [("方", "引き続きご利用いただけます")])
        # 記号が挟まる形、も で終わる長い助詞、まで も 以外も の種類。は で終わる長い助詞は 以外 のまま
        self.assertEqual(self.wording("**法人会員以外**も、" + C), [("法人会員以外も", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("「法人会員以外」も、" + C), [("法人会員以外も", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員以外においても、" + C), [("法人会員以外も", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員以外につきましても、" + F), [("法人会員以外も", "追加の費用は発生いたしません")])
        self.assertEqual(self.wording("法人会員以外まで、" + C), [("法人会員以外も", "引き続きご利用いただけます")])
        self.assertEqual(self.wording("法人会員以外については、" + C), [("法人会員以外", "引き続きご利用いただけます")])


if __name__ == "__main__":
    unittest.main()
