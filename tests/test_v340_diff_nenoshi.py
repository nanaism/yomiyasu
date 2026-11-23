"""3.4.0（念押し）: 敬称の「さん」「ちゃん」のあとの「です」を、念押しの「んです」に数えない。非・正・異・通・日・平・尋 の
すぐあとの「常に」（非常に、正常に、異常に、通常に、日常に、平常に、尋常に）も、熟語の終わりなので念押しの「常に」に数えない。
ほかの漢字のあとの副詞の「常に」（24時間常に、作業中常に）は 3.3.0 と同じく数える。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402


def nenoshi(old, new):
    result = yomiyasu_diff.diff(old + "\n", new + "\n")
    return ([(m["orig"], m["rewrite"]) for m in result["markers"] if m["kind"] == "念押し"],
            sum(1 for s in result["spans"] if "念押し" in s["kinds"]))


class SanDesuTest(unittest.TestCase):
    def test_san_desu_is_not_nenoshi(self):
        for old, new in (("担当は田中さんです。", "担当は田中さんになります。"),
                         ("受付は山田です。", "受付は山田さんです。"),
                         ("今回の主役は、参加してくれた皆さんです。", "今回の主役は、参加してくれた皆さん一人ひとりです。"),
                         ("説明はもうたくさんです。", "説明はもう十分です。"),
                         ("お問い合わせの窓口は、総務課の田中さんです。", "お問い合わせの窓口は、総務課の田中さんですので、そちらへご連絡ください。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(nenoshi(old, new), ([], 0))

    def test_real_nenoshi_is_kept(self):
        for old, new in (("この設定を変えると、ログインできなくなるんです。", "この設定を変えると、ログインできなくなります。"),
                         ("佐藤さんですら知らなかったんです。", "佐藤さんでも知りませんでした。"),
                         ("田中さんなんです、この企画を最初に出したのは。", "この企画を最初に出したのは田中さんです。"),
                         ("締め切りは金曜です。", "締め切りは金曜なんです。")):
            with self.subTest(old=old, new=new):
                self.assertTrue(nenoshi(old, new)[0])

    def test_kun_desu_is_unchanged(self):
        """「くんです」は「行くんです」と見分けられないので 3.3.0 のまま念押しに数える。"""
        self.assertEqual(nenoshi("担当は田中くんです。", "担当は田中くんになります。")[0], [(1, 0)])


class ChanTest(unittest.TestCase):
    """「ちゃんです」も念押しに数えない。"""

    def test_chan_desu_is_not_nenoshi(self):
        for old, new in (("妹のゆいちゃんです。", "妹のゆいです。"), ("隣の席はみかちゃんです。", "隣の席は、みかちゃん。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(nenoshi(old, new), ([], 0))

    def test_nenoshi_near_chan_is_kept(self):
        self.assertTrue(nenoshi("ゆいちゃんが作ってくれたんです。", "ゆいちゃんが作ってくれました。")[0])


class JouniTest(unittest.TestCase):
    """熟語の「常に」（非・正・異・通・日・平・尋 のすぐあと）は数えず、副詞の「常に」（文頭、助詞・読点・かな・かっこ・ほかの漢字の
    あと）は今までどおり数える。"""

    def test_compounds_are_not_nenoshi(self):
        for old, new in (("この点は非常に重要です。", "この点はとても重要です。"),
                         ("更新は正常に終わりました。", "更新は問題なく終わりました。"),
                         ("測定で異常に高い値が出ました。", "測定で極端に高い値が出ました。"),
                         ("異常に気づいたら、すぐ連絡してください。", "おかしな点に気づいたら、すぐ連絡してください。"),
                         ("新しい習慣がすっかり日常に溶け込んだ。", "新しい習慣がすっかり暮らしに溶け込んだ。"),
                         ("今年の来場者は通常に比べて多い。", "今年の来場者は例年に比べて多い。"),
                         ("電車の運行は平常に戻りました。", "電車の運行はいつもどおりに戻りました。"),
                         ("逃げずに尋常に勝負しろ。", "逃げずに正々堂々と勝負しろ。"),
                         ("この点はとても大切です。", "この点は非常に大切です。"),
                         ("画面が非常に暗く、非常に見にくい。", "画面が非常に暗く、見にくい。"),
                         ("非常に重要なので、常に確認してください。", "とても重要なので、常に確認してください。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(nenoshi(old, new), ([], 0))

    def test_adverb_jouni_is_kept(self):
        for old, new, expected in (("常に最新の版を使ってください。", "最新の版を使ってください。", (1, 0)),
                                   ("担当者は常に作業の記録を残します。", "担当者は作業の記録を残します。", (1, 0)),
                                   ("作業中は、常にヘルメットを着用してください。", "作業中はヘルメットを着用してください。", (1, 0)),
                                   ("画面を常に最新の状態に保ちます。", "画面を最新の状態に保ちます。", (1, 0)),
                                   ("この店は週末になるとほぼ常に満席です。", "この店は週末になるとほぼ満席です。", (1, 0)),
                                   ("【必須】常に施錠してください。", "【必須】施錠してください。", (1, 0)),
                                   ("鍵は金庫に保管します。", "鍵は常に金庫に保管します。", (0, 1)),
                                   ("- 手袋を着ける\n- 帽子をかぶる", "- 常に手袋を着ける\n- 帽子をかぶる", (0, 1)),
                                   ("非常に重要なので、常に確認してください。", "非常に重要なので、確認してください。", (1, 0))):
            with self.subTest(old=old, new=new):
                self.assertEqual(nenoshi(old, new)[0], [expected])

    def test_adverb_after_other_kanji_is_kept(self):
        """熟語の7字のほかの漢字のすぐあとの副詞の「常に」を消した推敲は、3.3.0 と同じく念押しの 1 → 0 を出す。"""
        for old, new in (("監視カメラで24時間常に見張っています。", "監視カメラで24時間見張っています。"),
                         ("作業中常にヘルメットを着用してください。", "作業中はヘルメットを着用してください。"),
                         ("運転中常にシートベルトを締めてください。", "運転中はシートベルトを締めてください。"),
                         ("期間中常に監視員を置きます。", "期間中は監視員を置きます。"),
                         ("当社は創業以来常に品質を第一に考えてきました。", "当社は創業以来、品質を第一に考えてきました。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(nenoshi(old, new)[0], [(1, 0)])

    def test_particle_or_comma_before_jouni_is_not_a_change(self):
        """漢字のあとの「常に」の前に「は」や読点を足しただけの推敲には、念押しの増減を出さない（3.3.0 と同じ）。"""
        for old, new in (("作業中常にヘルメットを着用してください。", "作業中は常にヘルメットを着用してください。"),
                         ("24時間常に監視しています。", "24時間、常に監視しています。"),
                         ("当社は創業以来常に品質を第一に考えてきました。", "当社は創業以来、常に品質を第一に考えてきました。")):
            with self.subTest(old=old, new=new):
                self.assertEqual(nenoshi(old, new)[0], [])

    def test_jouni_added_before_a_compound_is_counted(self):
        self.assertEqual(nenoshi("システムは正常に動いています。", "システムは常に正常に動いています。")[0], [(0, 1)])

    def test_adverb_after_the_compound_kanji_is_a_known_limit(self):
        """熟語の7字（非・正・異・通・日・平・尋）のすぐあとの副詞の「常に」（毎日常に）は熟語と見分けないので、念押しに数えない（限界）。"""
        self.assertEqual(nenoshi("毎日常に記録を残します。", "毎日記録を残します。"), ([], 0))
        self.assertEqual(nenoshi("毎日記録を残します。", "毎日常に記録を残します。"), ([], 0))


if __name__ == "__main__":
    unittest.main()
