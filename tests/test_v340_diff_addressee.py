"""3.4.0（宛名）: 主題・目的語の句（初日の受付は田中さん、司会を山田さん）の形だけを、同じ名前のまま変えた推敲を宛名の候補に
しない。名前が変わった、担当を入れ替えた、敬称が変わったときは 3.3.0 のまま候補にする。

宛名の候補の順番を数える正規表現は、3.3.0 の _HONORIFIC（主語と目的語の入れ替えの検査で、名前のあとの さん・くん・ちゃん を
外す）と別の名前にする（同じ名前で付け直すと、入れ替えの検査が くん・ちゃん の名前を見落とす。SwapNamesTest）。

句の名前の前に語を足した・動かした形（受付は初日に田中さん、司会は引き続き佐藤さん）は、句の後ろの名前で比べる。名前の前の
2字以上の語が反対の側の同じ順番の名前の前にないとき（総務の田中さん → 経理の田中さん、初日に田中さん → 二日目に田中さん）は
候補にする（PrefixWordTest）。句の頭の話題の語を別の語に替えた推敲（東京会場の受付は田中さん → 大阪会場の受付は田中さん）も
候補にする（ReplacedTopicWordTest。漢字・片仮名・英字の語のすぐ前の平仮名の語（こども向け）も比べる）。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402


def addressees(old, new):
    result = yomiyasu_diff.diff(old + "\n", new + "\n")
    return [c["detail"] for c in result["immutable"]["candidates"] if c["subkind"] == "addressee"]


class TopicPhraseTest(unittest.TestCase):
    def test_same_names_in_reshaped_phrases(self):
        for old, new in (("初日の受付は田中さん、二日目は鈴木さんです。", "初日の受付は田中さんが、二日目は鈴木さんが担当します。"),
                         ("司会は山田さん、記録は佐藤さんにお願いしました。", "司会を山田さん、記録を佐藤さんにお願いしました。"),
                         ("最初の発表は鈴木さん、次が田中さんの予定です。", "発表は鈴木さん、田中さんの順です。"),
                         ("担当窓口は営業二課の藤田様、緊急時は課長の岡田様にご連絡ください。",
                          "担当窓口は営業二課の藤田様です。緊急時は課長の岡田様にご連絡ください。"),
                         ("- 議事録は山口さん、タイムキーパーは石川さん\n- 次回は12月5日",
                          "- 議事録：山口さん、タイムキーパー：石川さん\n- 次回は12月5日"),
                         ("受付は田中さん、案内は鈴木さんです。", "受付は田中さんです。案内は鈴木さんです。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(addressees(old, new), [])

    def test_changed_or_swapped_names_are_kept(self):
        for old, new in (("次は田中さん、発表をお願いします。", "次は佐藤さん、発表をお願いします。"),
                         ("初日の受付は田中さん、二日目は鈴木さんです。", "初日の受付は佐藤さん、二日目は鈴木さんです。"),
                         ("初日の受付は田中さん、二日目は鈴木さんです。", "初日の受付は鈴木さん、二日目は田中さんです。"),
                         ("受付は田中さん、案内は鈴木さんです。", "受付は鈴木さんです。案内は田中さんです。"),
                         ("司会は山田さん、記録は佐藤さんです。", "司会は山田様、記録は佐藤さんです。"),
                         ("では田中さん、続きをお願いします。", "では佐藤さん、続きをお願いします。"),
                         ("山田はるか様、先日はありがとうございました。", "山田様、先日はありがとうございました。"),
                         ("自由が丘店 店長 田中様、お世話になっております。", "自由が丘店 店長 田中さん、お世話になっております。")):
            with self.subTest(old=old, new=new):
                self.assertTrue(addressees(old, new))


class GaMoTest(unittest.TestCase):
    """「が」「も」の句も同じに扱う。"""

    def test_ga_mo_phrases(self):
        self.assertEqual(addressees("初日が田中さん、二日目が鈴木さんの担当です。", "初日は田中さん、二日目は鈴木さんが担当します。"), [])
        self.assertEqual(addressees("二日目も田中さん、三日目は鈴木さんにお願いします。",
                                    "二日目も田中さんに、三日目は鈴木さんにお願いします。"), [])
        self.assertTrue(addressees("初日が田中さん、二日目が鈴木さんです。", "初日が佐藤さん、二日目が鈴木さんです。"))
        self.assertTrue(addressees("自由が丘店 店長 田中様、お世話になっております。", "自由が丘店 店長 山田様、お世話になっております。"))


class PrefixWordTest(unittest.TestCase):
    """句の名前の前の語（初日に、今週から、引き続き）を足した・動かした推敲は、同じ人と順なら候補にしない。"""

    def test_same_names_with_moved_or_added_words(self):
        for old, new in (("初日の受付が田中さん、二日目が鈴木さんです。", "受付は初日に田中さん、二日目に鈴木さんが担当します。"),
                         ("担当は今週から田中さん、来週から鈴木さんです。", "今週からの担当は田中さん、来週からは鈴木さんです。"),
                         ("司会は佐藤さん、書記は伊藤さん。", "司会は引き続き佐藤さん、書記は伊藤さん。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(addressees(old, new), [])

    def test_changed_words_or_people_are_kept(self):
        for old, new in (("受付は総務の田中さん、会計は佐藤さんです。", "受付は経理の田中さん、会計は佐藤さんです。"),
                         ("受付は初日に田中さん、二日目に鈴木さんです。", "受付は初日に中田さん、二日目に鈴木さんです。"),
                         ("受付は初日に田中さん、二日目に鈴木さんです。", "受付は二日目に田中さん、初日に鈴木さんです。"),
                         ("初日の受付は田中さん、二日目は鈴木さんです。", "受付は初日に田中様、二日目に鈴木様です。")):
            with self.subTest(old=old, new=new):
                self.assertTrue(addressees(old, new))


class ReplacedTopicWordTest(unittest.TestCase):
    """句の頭の話題の語を別の語に替えた推敲（名前は同じ）は、句の形だけを変えた推敲とみなさず、3.3.0 と同じく宛名の候補にする。
    語を外しただけ・足しただけなら候補にしない。名前の順を保って話題の語だけを入れ替えた推敲には、宛名の候補と話題の候補の両方が出る。"""

    def test_replaced_topic_words_are_kept(self):
        for old, new, removed, added in (
                ("東京会場の受付は田中さん、案内は鈴木さんです。", "大阪会場の受付は田中さん、案内は鈴木さんです。",
                 "東京会場の受付は田中さん", "大阪会場の受付は田中さん"),
                ("司会は田中さん、記録は鈴木さんです。受付の場所は1階です。", "受付は田中さん、記録は鈴木さんです。受付の場所は1階です。",
                 "司会は田中さん", "受付は田中さん"),
                ("司会は田中さん、記録は鈴木さんです。\n\n会場の受付は佐藤さんが担当します。",
                 "受付は田中さん、記録は鈴木さんです。\n\n会場の受付は佐藤さんが担当します。", "司会は田中さん", "受付は田中さん"),
                ("経理部長は田中様、\n総務部長は佐藤様です。", "経理課長は田中様、\n総務部長は佐藤様です。", "経理部長は田中様", "経理課長は田中様"),
                ("営業部の窓口は田中様、\n経理部の窓口は佐藤様です。", "人事部の窓口は田中様、\n経理部の窓口は佐藤様です。",
                 "営業部の窓口は田中様", "人事部の窓口は田中様")):
            with self.subTest(old=old, new=new):
                self.assertEqual(addressees(old, new), [{"removed": [removed], "added": [added]}])

    def test_replaced_hiragana_topic_words_are_kept(self):
        """漢字・片仮名・英字の語のすぐ前の平仮名の話題の語を替えた推敲も、3.3.0 と同じく宛名の候補にする。"""
        for old, new, removed, added in (
                ("こども向けの受付は田中さん、案内は鈴木さんです。", "おとな向けの受付は田中さん、案内は鈴木さんです。",
                 "こども向けの受付は田中さん", "おとな向けの受付は田中さん"),
                ("ひるの部の受付は田中さん、よるの部の受付は鈴木さんです。", "あさの部の受付は田中さん、よるの部の受付は鈴木さんです。",
                 "ひるの部の受付は田中さん", "あさの部の受付は田中さん")):
            with self.subTest(old=old, new=new):
                self.assertEqual(addressees(old, new), [{"removed": [removed], "added": [added]}])

    def test_swapped_hiragana_topic_words_show_both_candidates(self):
        result = yomiyasu_diff.diff("こども向けの受付は田中さん、おとな向けの受付は鈴木さんです。\n",
                                    "おとな向けの受付は田中さん、こども向けの受付は鈴木さんです。\n")
        self.assertEqual([(c["subkind"], c["detail"]) for c in result["immutable"]["candidates"]],
                         [("addressee", {"removed": ["こども向けの受付は田中さん"], "added": ["おとな向けの受付は田中さん"]})])
        self.assertEqual([(r["kind"], r["subkind"]) for r in result["meaning_risks"]], [("topic", "person")])

    def test_synonym_topic_words_are_a_known_limit(self):
        """話題の語を同じ意味の語に言い換えた推敲も、語を替えた推敲として 3.3.0 と同じく宛名の候補にする（意味が同じかは見ない。限界）。"""
        for old, new, removed, added in (
                ("一日目の受付は山口さん、二日目の受付は松本さんです。", "初日の受付は山口さん、二日目の受付は松本さんです。",
                 "一日目の受付は山口さん", "初日の受付は山口さん"),
                ("受付係は山口さん、案内係は松本さんです。", "受付担当は山口さん、案内係は松本さんです。", "受付係は山口さん", "受付担当は山口さん")):
            with self.subTest(old=old, new=new):
                self.assertEqual(addressees(old, new), [{"removed": [removed], "added": [added]}])
        result = yomiyasu_diff.diff("受付係は山口さん、案内係は松本さんです。\n", "受付担当は山口さん、案内係は松本さんです。\n")
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_dropped_or_added_words_stay_quiet(self):
        for old, new in (("最初の発表は鈴木さん、次が田中さんの予定です。", "発表は鈴木さん、田中さんの順です。"),
                         ("東京の受付は田中さん、案内は鈴木さんです。", "東京会場の受付は田中さん、案内は鈴木さんです。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(addressees(old, new), [])

    def test_added_or_dropped_words_that_change_the_place_are_a_known_limit(self):
        """語を足したり外したりして指す所が変わった推敲（本社 → 本社別館、第一会議室 → 会議室）も、語を外しただけ・足しただけの推敲と
        みなして宛名の候補にしない（限界。3.3.0 は候補にしていた）。"""
        for old, new in (("本社の受付は田中さん、案内は鈴木さんです。", "本社別館の受付は田中さん、案内は鈴木さんです。"),
                         ("第一会議室の予約は田中さん、第二会議室の予約は鈴木さんです。", "会議室の予約は田中さん、第二会議室の予約は鈴木さんです。")):
            with self.subTest(old=old, new=new):
                result = yomiyasu_diff.diff(old + "\n", new + "\n")
                self.assertEqual(result["immutable"]["candidates"], [])
                self.assertEqual(result["meaning_risks"], [])

    def test_swapped_topic_words_show_both_candidates(self):
        for old, new in (("東京会場の受付は前田様、大阪会場の受付は藤田様です。", "大阪会場の受付は前田様、東京会場の受付は藤田様です。"),
                         ("初日の受付は前田様、二日目の受付は藤田様です。", "二日目の受付は前田様、初日の受付は藤田様です。")):
            with self.subTest(old=old, new=new):
                result = yomiyasu_diff.diff(old + "\n", new + "\n")
                self.assertEqual([c["subkind"] for c in result["immutable"]["candidates"]], ["addressee"])
                self.assertEqual([(r["kind"], r["subkind"]) for r in result["meaning_risks"]], [("topic", "person")])


class SwapNamesTest(unittest.TestCase):
    """宛名の直しのあとも、くん・ちゃん・さん の名前の入れ替え（swap）は 3.3.0 と同じく出す。"""

    def test_swaps_with_kun_chan_san_are_kept(self):
        for old, new in (("高橋くんが伊藤くんに鍵を返した。", "伊藤くんが高橋くんに鍵を返した。"),
                         ("小林ちゃんが加藤ちゃんに手紙を送った。", "加藤ちゃんが小林ちゃんに手紙を送った。"),
                         ("吉田くんが山本さんに資料を渡した。", "山本さんが吉田くんに資料を渡した。")):
            with self.subTest(old=old, new=new):
                risks = yomiyasu_diff.diff(old + "\n", new + "\n")["meaning_risks"]
                self.assertTrue(any(risk["kind"] == "swap" for risk in risks))
        self.assertIsNot(yomiyasu_diff._HONORIFIC, yomiyasu_diff._HONORIFIC_AFTER_NAME)
        self.assertIsNotNone(yomiyasu_diff._HONORIFIC.match("くん"))


if __name__ == "__main__":
    unittest.main()
