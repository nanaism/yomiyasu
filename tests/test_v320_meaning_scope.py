#!/usr/bin/env python3
"""v3.2.0: diff の「意味が変わる恐れ」の照らし合わせを直した所と広げた所の試験（章ごとにクラスを分ける）。

指示書の各章の「当てる形と当てない形」の表の組を、そのまま試験にする。文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


def kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"]]


class ZeroMinuteTimeTest(unittest.TestCase):
    """10章: 分が0の時刻を「時」だけで書いた形（18:00 → 18時）を、表記の違いとして打ち消す。"""

    CANCELLED = (
        ("会議は18:00に始めます。", "会議は18時に始めます。"),
        ("切り替えは0:00に行います。", "切り替えは0時に行います。"),
        ("受付は9:00〜17:00です。", "受付は9時〜17時です。"),
        ("説明会は14:00〜15:30に行います。", "説明会は14時〜15時30分に行います。"),
        ("受付は9:00〜9:30です。", "受付は9時〜9時30分です。"),
        # 逆向き
        ("18時に始めます。", "18:00に始めます。"),
        ("受付は9時〜17時です。", "受付は9:00〜17:00です。"),
    )
    # 今までどおり出す: (元, 後, 消えた値, 足した値)
    KEPT = (
        ("受付は9:30からです。", "受付は9時からです。", ["9", "30"], ["9時"]),
        ("開始は13:00です。", "開始は15時です。", ["13", "00"], ["15時"]),
        ("終了は18:00です。", "終了は19時です。", ["18", "00"], ["19時"]),
        ("受付は8:45からです。", "受付は8時からです。", ["8", "45"], ["8時"]),
    )

    def test_cancelled(self):
        for before, after in self.CANCELLED:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_kept(self):
        for before, after, removed, added in self.KEPT:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual([(risk["kind"], risk["subkind"], risk["detail"]) for risk in result["meaning_risks"]],
                                 [("number", "replaced", {"removed": removed, "added": added})])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_existing_cancellations_are_unchanged(self):
        """v3.1.0 で打ち消していた形（10:30 → 10時30分、18:00 → 18時00分、日付）は、今までどおり候補にしない。"""
        for before, after in (("会議は10:30に始めます。", "会議は10時30分に始めます。"),
                              ("会議は18:00に始めます。", "会議は18時00分に始めます。"),
                              ("公開は2026-10-13です。", "公開は2026年10月13日です。"),
                              ("作業は3〜5日かかります。", "作業は3日から5日かかります。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(run(before, after)["meaning_risks"], [])

    def test_only_the_matching_hour_is_cancelled(self):
        """同じ文の2つの時刻のうち、時の値が同じものだけを打ち消し、変わったほうは今までどおり出す。"""
        result = run("会議は18:00と20:00に開きます。", "会議は18時と21時に開きます。")
        self.assertEqual(kinds(result), [("number", "replaced")])
        self.assertEqual(result["meaning_risks"][0]["detail"]["added"], ["21時"])
        self.assertEqual(kinds(run("会議は18:00と20:00に開きます。", "会議は18時と20時に開きます。")), [])

    def test_seconds_are_not_cancelled(self):
        """時:分:秒 の形は打ち消さない（分と秒の組を時と分の組と取り違えないため）。"""
        self.assertEqual(kinds(run("時刻は18:00:00です。", "時刻は18時です。")), [("number", "replaced")])

    def test_cancelled_values_are_not_shown_again(self):
        """打ち消した値は、文書全体で比べるときにも出さない（足した文の中の値は今までどおり比べる）。"""
        before = "会議は18:00に始めます。\n\n場所は本社です。\n"
        after = "会議は18時に始めます。\n\n場所は本社です。\n"
        self.assertEqual(yomiyasu_diff.diff(before, after)["meaning_risks"], [])


if __name__ == "__main__":
    unittest.main()
