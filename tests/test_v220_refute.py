"""v2.2.0: 反証で見つけた新しい規則の誤った印と遅さの直しを確かめる。

- metaphor_label: ふつうの一語の見出し（変更、再現、後片付け）、動詞＋「こと」の見出し、版を書いた見出しには印をつけない。
- calque の型2: 技術の語のない文の定着した「〜先」（回し先、働き先）には印をつけない。型1: 件数や道具の名前をはさむ
  「テストが通る」と、「〜ないでください」の依頼には印をつけない。
- dialogue_period: 漫画のネームのコマや場所の柱の行（コマ1：…）は台詞に数えない。
- copy_comma_noun: 形容詞で終わる文（暑い、暑い。）には印をつけない。
- 長い英数字や数字の並びのある行で、lint が遅くならない。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import paced_limit, timing_clock  # noqa: E402

BODY = ("この節では、来週の作業の段取りを順に書きます。担当者は前の日の夕方までに表の値を確かめ、"
        "違いがあれば赤で印をつけて差し戻します。差し戻した表は翌日の昼までに直してもらいます。\n")


def rules_of(text, doc_type=None):
    return [finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type=doc_type)["findings"]
            if finding["rule"] in yomiyasu_lint._V220_RULES]


class MetaphorLabelTest(unittest.TestCase):
    def test_ordinary_headings_are_not_marked(self):
        for heading in ("## 変更", "## 再現", "## 後片付け", "## 守ること", "## いつも守ること", "# v1.1.2 チェックポイント",
                        "## 3. 移行"):
            with self.subTest(heading=heading):
                self.assertNotIn("metaphor_label", rules_of(heading + "\n\n" + BODY))

    def test_metaphor_labels_are_still_marked(self):
        for heading in ("## 机のそば", "## 灯台", "## 確かめ係"):
            with self.subTest(heading=heading):
                self.assertIn("metaphor_label", rules_of(heading + "\n\n" + BODY))


class CalqueTest(unittest.TestCase):
    def test_established_saki_outside_technical_sentences(self):
        for text in ("申請書は課長の確認のあと、経理の回し先に送ります。\n", "父の働き先が決まりました。\n",
                     "旅行の立ち寄り先を三つ選びました。\n", "お金の借り先が見つかりません。\n",
                     "チケットの割り振り先は、毎朝リーダーが決めます。\n"):
            with self.subTest(text=text):
                self.assertNotIn("calque", rules_of(text))

    def test_saki_in_technical_sentences_is_still_marked(self):
        for text in ("障害時のトラフィックの逃がし先として、大阪リージョンを用意しています。\n",
                     "集計が失敗したときのエラーの寄せ先は、運用チームのチャンネルです。\n"):
            with self.subTest(text=text):
                self.assertIn("calque", rules_of(text))

    def test_tests_pass_with_counts_and_tools(self):
        for text in ("テストは218件とも通りました。\n", "テスト273件が通ることを確かめた。\n",
                     "テスト一式は pytest で通します。\n", "外部ライブラリは足さないでください。\n"):
            with self.subTest(text=text):
                self.assertNotIn("calque", rules_of(text))
        for text in ("このリンターは、推敲で見落としやすい表現を拾うための補助です。\n",
                     "この検査は、表記ゆれをすべて拾います。\n", "設定のフックは、サブエージェントの呼び出しにも効く。\n"):
            with self.subTest(text=text):
                self.assertNotIn("calque", rules_of(text))
        self.assertIn("calque", rules_of("取りこぼした通知は、翌朝の再送ジョブが拾います。\n"))


class DialoguePeriodTest(unittest.TestCase):
    def test_panel_and_scene_lines_are_not_dialogue(self):
        lines = ["# ネーム（合成）", "", "場所：夕方の駅前。", "時間：午後五時。"]
        for number in range(1, 11):
            lines.append("コマ{}：ハルが改札を出てくる。".format(number))
            lines.append("ハル「今日もここで待ってたんだ」")
        text = "\n".join(lines) + "\n"
        self.assertNotIn("dialogue_period", rules_of(text, doc_type="script"))
        ended = text.replace("待ってたんだ」", "待ってたんだ。」")
        self.assertIn("dialogue_period", rules_of(ended, doc_type="script"))


class CopyCommaNounTest(unittest.TestCase):
    def test_adjective_endings_are_not_marked(self):
        for text in ("暑い、暑い。\n", "疲れた、眠い。\n", "早い、安い、うまい。\n"):
            with self.subTest(text=text):
                self.assertNotIn("copy_comma_noun", rules_of(text))
        self.assertIn("copy_comma_noun", rules_of("新しい、出会い。\n"))


class LongRunTest(unittest.TestCase):
    def test_long_ascii_and_digit_runs_finish_quickly(self):
        """2.1.3 ではすぐ終わる行（入口の語と、署名や鍵を貼った長い英数字の並び）で、新しい規則が遅くならない。"""
        texts = ("社外からの接続は、この入口を通ります。署名は " + "A" * 100000 + " です。\n",
                 "a" * 100000 + " x_y の値を見ます。\n",
                 "新しい鍵に替えると、古い鍵の失効が効きます。" + "１" * 20000 + "\n")
        for doc_type in (None, "essay"):
            for text in texts:
                with self.subTest(doc_type=doc_type, size=len(text)):
                    # 上限の秒数は、Windows の遅い機械では基準の処理の遅さの比で延ばす（portable.paced_limit）。時間は CPU 時間で測る
                    clock = timing_clock()
                    started = clock()
                    yomiyasu_lint.lint_text(text, doc_type=doc_type)
                    elapsed = clock() - started
                    limit, detail = paced_limit(2.0, elapsed)
                    self.assertLess(elapsed, limit, detail)


if __name__ == "__main__":
    unittest.main()
