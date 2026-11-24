"""3.4.0（伏せた番号）: 伏せた番号（090-****-5678、090-■■■■-5678、〒***-0001）の「-」を負の符号に読まない。強調の中の負の数
（**-3%**、*-1,200円*、***-0.5***、**-15%（前年比）**）の符号は今までどおり読む。伏せた数の「消えた数値」の候補は残る。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402

SIGNS = "+−-▲△ "


def sign_and_lost(old, new):
    signs, lost = [], []
    for risk in yomiyasu_diff.diff(old + "\n", new + "\n")["meaning_risks"]:
        detail = risk.get("detail") or {}
        removed, added = detail.get("removed") or [], detail.get("added") or []
        if (risk["kind"] == "number" and removed and added
                and sorted(v.lstrip(SIGNS) for v in removed) == sorted(v.lstrip(SIGNS) for v in added)
                and sorted(removed) != sorted(added)):
            signs.append((removed, added))
        elif risk["kind"] == "number" and risk["subkind"] == "lost":
            lost.append(removed)
    return signs, lost


class MaskedNumberTest(unittest.TestCase):
    def test_masked_numbers_have_no_sign_candidate(self):
        for old, new, lost in (("電話番号は090-1234-5678です。", "電話番号は090-****-5678です。", [["1234"]]),
                               ("電話番号は090-1234-5678です。", "電話番号は090-＊＊＊＊-5678です。", [["1234"]]),
                               ("連絡先は090-1234-5678です。", "連絡先は090-■■■■-5678です。", [["1234"]]),
                               ("お問い合わせ番号は12-3456-7890です。", "お問い合わせ番号は12-□□□□-7890です。", [["3456"]]),
                               ("旧住所は〒150-0001、新住所は〒160-0022です。", "旧住所は〒***-0001、新住所は〒***-0022です。",
                                [["150", "160"]]),
                               ("口座番号は123-4567です。", "口座番号は***-4567です。", [["123"]]),
                               ("カード番号は4111-1111-1111-1234です。", "カード番号は****-****-****-1234です。",
                                [["4111", "1111", "1111"]])):
            with self.subTest(old=old, new=new):
                self.assertEqual(sign_and_lost(old, new), ([], lost))

    def test_signs_inside_emphasis_and_next_to_masks(self):
        for old, new, expected in (("前年比は**-3%**でした。", "前年比は**3%**でした。", [(["-3"], ["3"])]),
                                   ("差額は*-1,200円*です。", "差額は*1,200円*です。", [(["-1"], ["1"])]),
                                   ("評価値は***-0.5***でした。", "評価値は***0.5***でした。", [(["-0.5"], ["0.5"])]),
                                   ("変化率は**-3 %**でした。", "変化率は**3 %**でした。", [(["-3"], ["3"])]),
                                   ("変化は**-3%**と**-5%**でした。", "変化は**3%**と**-5%**でした。", [(["-3"], ["3"])]),
                                   ("補正後の値は、測った値×-1で求めます。", "補正後の値は、測った値×1で求めます。", [(["-1"], ["1"])]),
                                   ("電話 090-1234-5678、差額 -500円", "電話 090-****-5678、差額 500円", [(["-500"], ["500"])])):
            with self.subTest(old=old, new=new):
                self.assertEqual(sign_and_lost(old, new)[0], expected)


class EmphasisClosingRunTest(unittest.TestCase):
    """「*」の並びの閉じは、数と単位のすぐあとでなくても、同じ行のあとの同じ数の並び（すぐあとが数字でも「-」と数字でもないもの）で
    見る。並びのすぐ前が数字かハイフンなら伏せ字。"""

    def test_closing_run_after_other_words(self):
        for old, new, expected in (("今期の利益は**-15%（前年比）**です。", "今期の利益は**15%（前年比）**です。", [(["-15"], ["15"])]),
                                   ("来場者は前年比**-10万人**でした。", "来場者は前年比**10万人**でした。", [(["-10"], ["10"])]),
                                   ("最低気温は**-5度**の予想です。", "最低気温は**5度**の予想です。", [(["-5"], ["5"])]),
                                   ("為替の影響は**-8%前後**です。", "為替の影響は**8%前後**です。", [(["-8"], ["8"])]),
                                   ("明朝は*-2℃前後*まで冷え込みます。", "明朝は*2℃前後*まで冷え込みます。", [(["-2"], ["2"])])):
            with self.subTest(old=old, new=new):
                self.assertEqual(sign_and_lost(old, new)[0], expected)

    def test_counted_candidates_drop_by_the_masked_numbers(self):
        """--fail-on に数える候補は、伏せ字のすぐあとの「-」を符号と読んだ候補の数だけ減る（伏せた番号ごとに1つ。3.3.0 は
        1つの番号で2、同じ文の2つの番号で3、2行の2つの番号で4、カードの番号で2）。伏せた数の「消えた数値」は今までどおり数える。"""
        for old, new, lost, count in (("電話番号は090-1234-5678です。", "電話番号は090-****-5678です。", [["1234"]], 1),
                                      ("電話は090-1234-5678、FAXは03-1111-2222です。", "電話は090-****-5678、FAXは03-****-2222です。",
                                       [["1234", "1111"]], 1),
                                      ("電話は090-1234-5678です。\nFAXは03-1111-2222です。", "電話は090-****-5678です。\nFAXは03-****-2222です。",
                                       [["1234"], ["1111"]], 2),
                                      ("カード番号は1234-5678-9012-3456です。", "カード番号は****-****-****-3456です。",
                                       [["1234", "5678", "9012"]], 1)):
            with self.subTest(old=old, new=new):
                self.assertEqual(sign_and_lost(old, new), ([], lost))
                self.assertEqual(yomiyasu_diff.diff(old + "\n", new + "\n")["fail_on_meaning_risk_count"], count)

    def test_runs_that_stay_masks(self):
        for old, new in (("電話番号は090-12-1234です。", "電話番号は090-**-1234です。"),
                         ("番号は12-34-5678です。", "番号は12**-5678です。"),
                         ("旧住所は〒150-0001、新住所は〒160-0022です。", "旧住所は〒***-0001、新住所は〒***-0022です。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(sign_and_lost(old, new)[0], [])


if __name__ == "__main__":
    unittest.main()
