"""3.4.0（条件の読点）: 「なら」「たら」のすぐあとの読点だけを外した（足した）推敲で、条件の増減を出さない（スライドの見出しの読点の直しで
起きる形）。読点を外した所は、読点のない側でも条件に数え直す。条件を本当に消した・足した推敲は、数え直した数で出す。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402


def condition_markers(old, new):
    return [m for m in yomiyasu_diff.diff(old + "\n", new + "\n")["markers"] if m["kind"] == "条件"]


def conditions(old, new):
    return [(m["orig"], m["rewrite"]) for m in condition_markers(old, new)]


class ConditionCommaTest(unittest.TestCase):
    def test_comma_only_changes(self):
        for old, new in (("## 雨が降ったら、屋内で集まる", "## 雨が降ったら屋内で集まる"),
                         ("# 予定が合わないなら、別の日に変える", "# 予定が合わないなら別の日に変える"),
                         ("時間が合わないなら、録画をご覧ください。", "時間が合わないなら録画をご覧ください。"),
                         ("終わったら、連絡してください。間に合わないなら、早めに教えてください。",
                          "終わったら連絡してください。間に合わないなら早めに教えてください。"),
                         ("準備ができたら、会議室に集まってください。", "準備ができたら会議室へ集まってください。"),
                         ("雨が降ったら屋内で集まります。", "雨が降ったら、屋内で集まります。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(conditions(old, new), [])

    def test_real_condition_changes(self):
        for old, new, expected in (("雨が降ったら、屋内で集まります。", "雨でも屋外で集まります。", [(1, 0)]),
                                   ("## 範囲を絞る", "## 予算が足りないなら、範囲を絞る", [(0, 1)]),
                                   ("終わったら、連絡してください。間に合わないなら、早めに教えてください。",
                                    "終わったら連絡してください。早めに教えてください。", [(2, 1)]),
                                   ("3.1 予約照合と本人確認\n来客者から「予約番号」を伺います。",
                                    "3.1 予約照合と本人確認\n来客者が到着したら、「予約番号」を伺います。", [(0, 1)])):
            with self.subTest(old=old, new=new):
                self.assertEqual(conditions(old, new), expected)


class RecountTest(unittest.TestCase):
    """読点を外したうえで、ほかの所の条件を消した・足した推敲は、読点を外した「なら」「たら」を数え直した数で出す。"""

    def test_recounted_numbers(self):
        for old, new, expected in (("雨なら、中止します。", "雨なら中止します。参加者が少ない場合は延期します。", [(1, 2)]),
                                   ("雨なら、中止します。参加者が5人未満の場合も、中止します。",
                                    "雨なら中止します。参加者が5人未満でも実施します。", [(2, 1)]),
                                   ("## 導入するなら、小さく始める\n\n- 効果が出たら、対象を広げる",
                                    "## 導入するなら小さく始める\n\n- 対象を広げる", [(2, 1)]),
                                   ("## 申し込むなら、今月中に\n\n- 早割は11月末まで",
                                    "## 申し込むなら今月中に\n\n- 席が埋まったら、受付を締め切る", [(1, 2)])):
            with self.subTest(old=old, new=new):
                self.assertEqual(conditions(old, new), expected)

    def test_recounted_hits(self):
        markers = condition_markers("雨なら、中止します。参加者が5人未満の場合も、中止します。",
                                    "雨なら中止します。参加者が5人未満でも実施します。")
        self.assertEqual([(m["orig_hits"], m["rewrite_hits"]) for m in markers], [(["なら", "場合"], ["なら"])])
        markers = condition_markers("雨なら中止します。", "雨なら、中止します。参加者が少ない場合は延期します。")
        self.assertEqual([(m["orig_hits"], m["rewrite_hits"]) for m in markers], [(["なら"], ["なら", "場合"])])


if __name__ == "__main__":
    unittest.main()
