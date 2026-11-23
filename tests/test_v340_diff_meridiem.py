"""3.4.0（午前・午後）: 午前・午後の時刻を24時制にそろえて比べ（打ち消すときだけ）、午前と午後の入れ替えを number の meridiem で出す。
午後0時（正午）も12時にそろえる。午前12時と午後12時は読み方が分かれるので、3.3.0 のまま 12時 と同じ数に読む。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402


def number_risks(old, new):
    return [risk for risk in yomiyasu_diff.diff(old + "\n", new + "\n")["meaning_risks"] if risk["kind"] == "number"]


def meridiem(old, new):
    return [risk for risk in number_risks(old, new) if risk["subkind"] == "meridiem"]


class TwentyFourHourTest(unittest.TestCase):
    def test_same_time_in_24_hour_form_is_not_a_number_change(self):
        for old, new in (("会議は午後3時に始めます。", "会議は15時に始めます。"),
                         ("納品は当日の午後4時までにお願いします。", "納品は当日の16:00までにお願いします。"),
                         ("受付は午後3時から5時までです。", "受付は15時から17時までです。"),
                         ("電話での問い合わせは、午後1〜5時に受け付けています。", "電話での問い合わせは、13〜17時に受け付けています。"),
                         ("上映は午後1時、4時、7時の3回です。", "上映は13時、16時、19時の3回です。"),
                         ("面談の枠は午後2時と4時の2つです。", "面談の枠は14時と16時の2つです。"),
                         ("打ち合わせは午後3時半からです。", "打ち合わせは15:30からです。"),
                         ("会議は午後3時半に始めます。", "会議は15時30分に始めます。"),
                         ("セミナーは午後1時半に開場し、午後2時に開演します。", "セミナーは13時半に開場し、14時に開演します。"),
                         ("夜間の工事は午後10時から翌午前5時まで行います。", "夜間の工事は22時から翌5時まで行います。"),
                         ("本番環境へのデプロイは、利用者の少ない21時に行います。", "本番環境へのデプロイは、利用者の少ない午後9時に行います。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(number_risks(old, new), [])

    def test_real_changes_are_still_number_risks(self):
        for old, new in (("説明会は午後3時に始まり、1時間ほどで終わります。", "説明会は16時に始まり、1時間ほどで終わります。"),
                         ("健康診断の受付は午後1時から4時までです。", "健康診断の受付は13時から4時までです。"),
                         ("交流会は午後3時半に始まります。", "交流会は15時に始まります。"),
                         ("交流会は午後3時半に始まります。", "交流会は16時30分に始まります。"),
                         ("上映は午後1時、4時、7時の3回です。", "上映は13時、16時、18時の3回です。")):
            with self.subTest(old=old, new=new):
                self.assertTrue(number_risks(old, new))

    def test_half_without_meridiem_is_unchanged(self):
        """午前・午後のない「3時半 → 3時30分」は 3.3.0 のまま（元にない数値 30分）。"""
        risks = number_risks("会議は3時半に始めます。", "会議は3時30分に始めます。")
        self.assertEqual([r["detail"]["added"] for r in risks], [["30分"]])


class SameHourAndHalfInRangeTest(unittest.TestCase):
    """範囲の後ろの時刻が前と同じ時の数でも「午後」を引き継ぎ、範囲の後ろの「半」も30分と読む。"""

    def test_same_hour_and_half_after_the_range(self):
        for old, new in (("二次会は午後11時から11時30分までです。", "二次会は23時から23時30分までです。"),
                         ("休憩は午後3時から3時15分までです。", "休憩は15時から15時15分までです。"),
                         ("受付は午後1時から1時半までです。", "受付は13時から13時30分までです。"),
                         ("説明は午後2時から3時半までです。", "説明は14時から15時30分までです。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(number_risks(old, new), [])

    def test_end_moved_to_the_night_is_reported(self):
        for old, new in (("休憩は午後3時から3時15分までです。", "休憩は15時から3時15分までです。"),
                         ("受付は午後1時から1時半までです。", "受付は13時から1時30分までです。"),
                         ("受付は午後1時から1時半までです。", "受付は13時から14時30分までです。")):
            with self.subTest(old=old, new=new):
                self.assertTrue(number_risks(old, new))


class SwapTest(unittest.TestCase):
    def test_swap_is_reported_and_counted(self):
        for old, new, removed, added in (
                ("定例の進捗会議は、毎週水曜の午後3時から行います。", "定例の進捗会議は、毎週水曜の午前3時から行います。", ["午後3時"], ["午前3時"]),
                ("定期メンテナンスは午前1:00に始まります。", "定期メンテナンスは午後1:00に始まります。", ["午前1:00"], ["午後1:00"]),
                ("交流会は午後3時半に始まります。", "交流会は午前3時半に始まります。", ["午後3時半"], ["午前3時半"])):
            with self.subTest(old=old, new=new):
                result = yomiyasu_diff.diff(old + "\n", new + "\n")
                found = [r for r in result["meaning_risks"] if r["subkind"] == "meridiem"]
                self.assertEqual([(r["detail"]["removed"], r["detail"]["added"]) for r in found], [(removed, added)])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_reorder_and_dropping_meridiem_are_not_swaps(self):
        for old, new in (("相談会の受付は、午前10時と午後3時の2回です。", "相談会の受付は、午後3時と午前10時の2回です。"),
                         ("朝の部は午前9時、夜の部は午後7時です。", "夜の部は午後7時、朝の部は午前9時です。"),
                         ("初日は午前9時に開場し、午後9時に閉場します。", "初日は午後9時に閉場し、午前9時に開場します。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(meridiem(old, new), [])


class MergedSplitReorderedTest(unittest.TestCase):
    """文をまとめた・分けた・動かした推敲でも24時制にそろえ、入れ替えを出す（文書全体の比べへの広げ）。"""

    def test_merged_split_reordered_rewrites(self):
        for old, new in (("受付は午後1時に始めます。説明会は午後2時からです。", "受付は13時に始め、説明会は14時から行います。"),
                         ("受付は午後1時に始まり、説明会は午後2時から本館で行います。", "受付は13時に始まります。説明会は14時から本館で行います。"),
                         ("ご来場の際は、受付で名刺を1枚お渡しください。当日の受付は午後1時から始まり、開演は午後2時を予定しております。",
                          "当日は13時から受付を始め、14時に開演する予定です。ご来場の際は、受付で名刺を1枚お渡しください。"),
                         ("開場は午後5時半、開演は午後6時です。", "開場は17時30分です。開演は18時です。"),
                         ("開場は午後6時、開演は午後6時30分です。\n\n会場は本社の3階ホールです。",
                          "会場は本社の3階ホールです。\n\n開場は18時、開演は18時30分です。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(number_risks(old, new), [])

    def test_swaps_and_real_changes_after_merge_or_move(self):
        self.assertTrue(meridiem("受付は午後1時に始めます。説明会は午後2時からです。",
                                 "受付は午後1時に始め、説明会は午前2時から行います。"))
        self.assertTrue(meridiem("開場は午後6時、開演は午後6時30分です。\n\n会場は本社の3階ホールです。",
                                 "会場は本社の3階ホールです。\n\n開場は午前6時、開演は18時30分です。"))
        self.assertTrue(number_risks("受付は午後1時に始めます。説明会は午後2時からです。",
                                     "受付は13時に始め、説明会は15時から行います。"))
        # 消した文の値は、変えていない段落の同じ時刻で打ち消さない
        self.assertTrue(number_risks("説明会は午後2時からです。\n\n懇親会は14時からです。", "懇親会は14時からです。"))

    def test_unrelated_sentences_are_not_swaps(self):
        self.assertEqual(meridiem("早朝の作業は午前3時に始めます。\n\n全員で片付けます。",
                                  "全員で片付けます。\n\n片付けの後の打ち上げは午後3時からです。"), [])


class NoonTest(unittest.TestCase):
    """午後0時は正午なので12時にそろえる（午後の0〜11時）。午前12時と午後12時は 3.3.0 のまま。"""

    def test_noon_in_24_hour_form_is_not_a_number_change(self):
        for old, new in (("昼の部は午後0時に始まります。", "昼の部は12時に始まります。"),
                         ("昼休みは午後0時から1時までです。", "昼休みは12時から13時までです。"),
                         ("昼休みは午後0時30分までです。", "昼休みは12時30分までです。"),
                         ("式は午後12時からです。", "式は12時からです。"),
                         ("式は午前12時からです。", "式は12時からです。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(number_risks(old, new), [])

    def test_noon_changes_are_reported(self):
        self.assertTrue(number_risks("昼休みは午後0時からです。", "昼休みは13時からです。"))
        result = yomiyasu_diff.diff("受付は午前0時に締め切ります。\n", "受付は午後0時に締め切ります。\n")
        found = [r for r in result["meaning_risks"] if r["subkind"] == "meridiem"]
        self.assertEqual([(r["detail"]["removed"], r["detail"]["added"]) for r in found], [(["午前0時"], ["午後0時"])])
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_dropping_meridiem_from_noon_is_a_known_limit(self):
        """打ち消すときだけ24時制にそろえるので、午後0時 → 0時（意味が変わる）は 3.3.0 と同じく出ない（限界）。"""
        self.assertEqual(number_risks("昼休みは午後0時からです。", "昼休みは0時からです。"), [])


if __name__ == "__main__":
    unittest.main()
