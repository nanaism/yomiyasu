"""3.4.0（午前・午後）: 午前・午後の時刻を24時制にそろえて比べ（打ち消すときだけ）、午前と午後の入れ替えを number の meridiem で出す。
午後0時（正午）も12時にそろえる。午前12時と午後12時は読み方が分かれるので、3.3.0 のまま 12時 と同じ数に読む。
項目どうしの時刻の入れ替え（会議は午後3時、懇親会は午後6時 → 会議は18時、懇親会は15時）と、項目の名前の順を入れ替えて値の並びを
保った入れ替え（→ 懇親会は15時、会議は18時）は打ち消さない（ItemSwapTest）。

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


class ItemSwapTest(unittest.TestCase):
    """24時制にそろえた値が同じで並びだけが違い、値と語の結び付き（数の前の2字とあとの語）も変わった推敲は、項目どうしの時刻の
    入れ替えなので打ち消さない（3.3.0 と同じ数値の候補を出し、--fail-on に数える）。値の並びが同じでも、結び付きの手がかりの集まりが
    同じで結び付きだけが変わった推敲（項目の名前の順を入れ替えた）は打ち消さない。結び付きが同じ並べ替えは打ち消す。"""

    def test_swapped_times_between_items_are_reported(self):
        for old, new, removed, added in (("会議は午後3時、懇親会は午後6時です。", "会議は18時、懇親会は15時です。",
                                          ["3時", "6時"], ["18時", "15時"]),
                                         ("受付は午後1時、閉場は午後5時です。", "受付は17時、閉場は13時です。",
                                          ["1時", "5時"], ["17時", "13時"]),
                                         ("説明会は午後2時、交流会は午後4時に始めます。", "説明会は16時、交流会は14時に始めます。",
                                          ["2時", "4時"], ["16時", "14時"]),
                                         ("会議は午後3時から、懇親会は18時からです。", "会議は18時から、懇親会は15時からです。",
                                          ["3時"], ["15時"])):
            with self.subTest(old=old, new=new):
                result = yomiyasu_diff.diff(old + "\n", new + "\n")
                found = [(r["subkind"], r["detail"]["removed"], r["detail"]["added"])
                         for r in result["meaning_risks"] if r["kind"] == "number"]
                self.assertEqual(found, [("replaced", removed, added)])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_swapped_times_with_the_item_names_reordered_are_reported(self):
        """項目の名前の順を入れ替えて値の並びを保った入れ替え（2つの項目と、3つの項目を回した形）も、3.3.0 と同じ数値の候補を出す。"""
        for old, new, removed, added in (("会議は午後3時、懇親会は午後6時です。", "懇親会は15時、会議は18時です。",
                                          ["3時", "6時"], ["15時", "18時"]),
                                         ("受付は午後1時、開会は午後2時、閉会は午後5時です。", "開会は13時、閉会は14時、受付は17時です。",
                                          ["1時", "2時", "5時"], ["13時", "14時", "17時"])):
            with self.subTest(old=old, new=new):
                result = yomiyasu_diff.diff(old + "\n", new + "\n")
                found = [(r["subkind"], r["detail"]["removed"], r["detail"]["added"])
                         for r in result["meaning_risks"] if r["kind"] == "number"]
                self.assertEqual(found, [("replaced", removed, added)])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_swapped_times_in_separate_sentences_are_unchanged(self):
        """文が別なら組ごとに比べるので、3.3.0 と同じく文ごとに出る（数の前の2字とあとの語が同じ入れ替えも）。"""
        for old, new in (("受付は午後1時です。閉場は午後5時です。", "受付は17時です。閉場は13時です。"),
                         ("東京会場は午後3時開始です。大阪会場は午後5時開始です。", "東京会場は17時開始です。大阪会場は15時開始です。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(yomiyasu_diff.diff(old + "\n", new + "\n")["fail_on_meaning_risk_count"], 2)

    def test_reordered_items_with_the_same_times_are_quiet(self):
        for old, new in (("集合は午前8時、解散は午後8時です。", "解散は20時、集合は8時です。"),
                         ("会議は午後3時、懇親会は午後6時です。", "懇親会は18時、会議は15時です。"),
                         ("開場は午後5時、開演は午後6時です。", "開演は18時、開場は17時です。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(number_risks(old, new), [])

    def test_swaps_the_bindings_do_not_tell_are_known_limits(self):
        """同じ文の2つの項目で数の前の2字（午前・午後は数えない）とあとの語が同じ入れ替え（東京会場は〜開始、大阪会場は〜開始。
        開場は、閉場は）と、2つの範囲の初めの時刻でこの2字と語が同じ範囲の入れ替えは打ち消す（限界。午後のない同じ入れ替えも
        3.3.0 から出ない）。"""
        for old, new in (("東京会場は午後3時開始、大阪会場は午後5時開始です。", "東京会場は17時開始、大阪会場は15時開始です。"),
                         ("東京会場は15時開始、大阪会場は17時開始です。", "東京会場は17時開始、大阪会場は15時開始です。"),
                         ("開場は午後5時、閉場は午後9時です。", "開場は21時、閉場は17時です。"),
                         ("1部は午後1時から3時、2部は午後4時から6時です。", "1部は16時から18時、2部は13時から15時です。"),
                         ("説明会は午後1時から3時まで、懇談会は午後4時から6時までです。", "説明会は16時から18時まで、懇談会は13時から15時までです。"),
                         ("1部は13時から15時、2部は16時から18時です。", "1部は16時から18時、2部は13時から15時です。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(number_risks(old, new), [])

    def test_range_swaps_with_different_characters_keep_the_old_candidate(self):
        """2つの範囲の初めの時刻で数の前の2字が違う範囲の入れ替えは、3.3.0 と同じ数値の候補を出す（「から」でも「〜」でも）。"""
        for old, new in (("受付は午後1時から3時、懇親会は午後4時から6時です。", "受付は16時から18時、懇親会は13時から15時です。"),
                         ("受付は午後1時〜3時、懇親会は午後4時〜6時です。", "受付は16時〜18時、懇親会は13時〜15時です。")):
            with self.subTest(old=old, new=new):
                result = yomiyasu_diff.diff(old + "\n", new + "\n")
                found = [(r["subkind"], r["detail"]["removed"], r["detail"]["added"])
                         for r in result["meaning_risks"] if r["kind"] == "number"]
                self.assertEqual(found, [("replaced", ["1時", "3時", "4時", "6時"], ["16時", "18時", "13時", "15時"])])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_merged_split_or_reworded_swaps_are_known_limits(self):
        """文をまとめたり分けたりして書いた入れ替えと、言い換えて値の並びを保った入れ替えは打ち消す（限界。3.3.0 は数値の候補を
        出していた。午後のない同じ形のまとめと分けは 3.3.0 からも出ない）。"""
        for old, new in (("会議は午後3時です。懇親会は午後6時です。", "会議は18時、懇親会は15時です。"),
                         ("会議は午後3時、懇親会は午後6時です。", "会議は18時です。懇親会は15時です。"),
                         ("開場は午後5時、開演は午後6時です。", "開演は17時開始で、開場は18時開始です。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(number_risks(old, new), [])

    def test_reorder_with_a_word_after_the_time_keeps_the_old_candidate(self):
        """結び付きを保った並べ替えでも、時刻のあとに語を足すと結び付きが変わったと読み、3.3.0 と同じ誤った数値の候補が出る（限界）。"""
        result = yomiyasu_diff.diff("開場は午後5時、開演は午後6時です。\n", "開演は18時開始で、開場は17時開始です。\n")
        found = [(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in result["meaning_risks"] if r["kind"] == "number"]
        self.assertEqual(found, [("replaced", ["5時", "6時"], ["18時", "17時"])])
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_swap_next_to_a_converted_time_keeps_the_old_candidate(self):
        """同じ文で午前と午後を入れ替えた時刻があると、24時制にそろえた時刻の候補（3時 → 15時）も 3.3.0 と同じく残る（限界）。"""
        result = yomiyasu_diff.diff("会議は午後3時から、懇親会は午後6時からです。\n", "会議は15時から、懇親会は午前6時からです。\n")
        found = [(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in result["meaning_risks"] if r["kind"] == "number"]
        self.assertEqual(found, [("replaced", ["3時"], ["15時"]), ("meridiem", ["午後6時"], ["午前6時"])])
        self.assertEqual(result["fail_on_meaning_risk_count"], 2)


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
