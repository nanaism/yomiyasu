#!/usr/bin/env python3
"""v2.1.1: lint の誤った警告3つを形で除く（slop_vocabulary の「真理」「装置」、metaphor_verb の「〜した瞬間」、
translated_term の出版物の「版」）。拾うべき形は今のまま拾う。

例文は、お願いにある例文と、このファイルで作った合成の文。
"""

from pathlib import Path
from unittest import mock
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_lint  # noqa: E402


MOMENT = "英語直訳「〜した瞬間 (the moment ...)」"


def findings(text, rule):
    return [f for f in yomiyasu_lint.lint_text(text)["findings"] if f["rule"] == rule]


def slop_words(text):
    return [f["message"].split("「", 1)[1].split("」", 1)[0] for f in findings(text, "slop_vocabulary")]


def moment_hits(text):
    return [f for f in findings(text, "metaphor_verb") if f["message"].startswith(MOMENT)]


class SlopTruthDeviceTest(unittest.TestCase):
    """「真理値」「安全装置」のような定着した複合語を、AI頻出語彙「真理」「装置」として警告していた誤りの守り。"""

    def test_issue_example_has_no_truth_or_device(self):
        text = ("# 真理値演算\n\nプログラムでは、条件の判定に真理値(True、False)を使います。\n\n"
                "パイロットランプは、警報が発生したときに点灯する安全装置です。\n")
        self.assertEqual(findings(text, "slop_vocabulary"), [])

    def test_compounds_do_not_fire(self):
        for text in ("真理表を書いて、真理関数を確かめる。\n", "真理条件と真理集合を定義する。\n",
                     "真理子さんに資料を送った。\n",
                     "制御装置と表示装置を交換した。\n", "記憶装置の容量を増やす。\n",
                     "中央処理装置の温度を測る。\n", "レーザー装置の電源を切る。\n", "X線装置で検査する。\n"):
            with self.subTest(text=text):
                self.assertEqual([w for w in slop_words(text) if w in ("真理", "装置")], [])

    def test_metaphor_compounds_still_fire(self):
        """機器の名前を作る語のほかと結んだ比喩の複合語は、今までどおり拾う。"""
        for text in ("SNSは承認欲求の増幅装置だ。\n", "会議は、組織の意思を固める思考装置として働く。\n",
                     "物語は、読者の記憶を呼び起こす演出装置である。\n", "祭りは共同体をつなぐ文化装置だ。\n",
                     "軍は国家の暴力装置である。\n", "国家のイデオロギー装置として機能する。\n",
                     "会議は舞台装置にすぎない。\n"):
            with self.subTest(text=text):
                self.assertEqual(slop_words(text), ["装置"])

    def test_literal_device_compounds_do_not_fire(self):
        for text in ("安全装置を外さないでください。\n", "入力装置と測定装置をつなぐ。\n",
                     "冷却装置と照明装置を点検する。\n", "通信装置と医療装置を区別する。\n",
                     "実験装置と警報装置を並べる。\n", "放射線装置を導入した。\n", "読み取り装置を置く。\n"):
            with self.subTest(text=text):
                self.assertEqual([w for w in slop_words(text) if w == "装置"], [])

    def test_standalone_device_with_operation_does_not_fire(self):
        """単独の「装置」でも、同じ文で後ろに電源や起動など機器の操作が続くときは、文字どおりの機器として除く。"""
        for text in ("この装置は、毎朝9時に自動で起動します。\n", "装置の電源を切ってから、ケーブルを抜く。\n",
                     "点検前に装置の電源を切ること。\n"):
            with self.subTest(text=text):
                self.assertEqual([w for w in slop_words(text) if w == "装置"], [])

    def test_standalone_metaphor_still_fires(self):
        for text, word in (("走ることを通して、私は人生の真理に気づかされた。\n", "真理"),
                           ("失敗こそが人を育てるという真理がある。\n", "真理"),
                           ("# 真理\n", "真理"),
                           ("この町は、記憶を呼び起こす装置として機能している。\n", "装置"),
                           ("祭りは、地域をつなぐ装置だ。\n", "装置"),
                           ("古い洋館が、物語の舞台装置として働く。\n", "装置")):
            with self.subTest(text=text):
                self.assertEqual(slop_words(text), [word])


class MomentTest(unittest.TestCase):
    """時刻を文字どおり表す「〜した瞬間に」を、英語直訳として警告していた誤りの守り。"""

    def test_issue_example_does_not_fire(self):
        self.assertEqual(moment_hits("# 障害対応\n\nボタンを押した瞬間に、画面が真っ白になる。\n"), [])

    def test_literal_timing_does_not_fire(self):
        for text in ("設定を保存した瞬間にキャッシュが消えます。\n",
                     "電源を入れ直した瞬間に、ランプが赤く点滅する。\n",
                     "必要なデータが発生した瞬間に、通知を送る。\n",
                     "値が急に動き出した瞬間を、記録の始まりとする。\n"):
            with self.subTest(text=text):
                self.assertEqual(moment_hits(text), [])

    def test_translationese_shapes_still_fire(self):
        for text in ("検査項目そのものを目的にした瞬間に、品質は崩れる。\n",
                     "実際の運用に落とした瞬間に全滅する。\n",
                     "一度使用した瞬間に、その違いがわかるはずです。\n",
                     "アプリを起動した瞬間、世界が変わった。\n",
                     "グラスを手にした瞬間、ずっしりとした重みが伝わる。\n",
                     "ひと口を口にした瞬間、香りが広がります。\n",
                     "それは、二つの習慣がひとつに結合した瞬間だった。\n",
                     "## 決断した瞬間に、すべてが動き出す\n"):
            with self.subTest(text=text):
                self.assertEqual(len(moment_hits(text)), 1)

    def test_abstract_aphorisms_fire(self):
        """一般論の前置きや、抽象的な主語が続く「〜した瞬間に」は、結果の動詞を問わず拾う。"""
        for text in ("効率を優先した瞬間に、品質は下がる。\n",
                     "指標を目的にした瞬間に、それは指標として機能しなくなる。\n",
                     "完璧を目指した瞬間に、プロジェクトは止まる。\n",
                     "目標を数字にした瞬間に、本来の目的は消える。\n",
                     "学びを言語化した瞬間に、理解は深まる。\n",
                     "売上を目標にした瞬間に、顧客は見えなくなる。\n",
                     "体験した瞬間にわかる。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(moment_hits(text)), 1)

    def test_literal_results_do_not_fire(self):
        """文字どおりの結果（データが失われる、内容がわかる、すべてが再読み込みされる）が続く時刻の表現は拾わない。"""
        for text in ("保存せずに終了した瞬間に、編集内容は失われます。\n",
                     "電源をオフにした瞬間に、未保存のデータは失われる。\n",
                     "キャッシュを削除した瞬間に、すべてが再読み込みされる。\n",
                     "ディスクを取り外した瞬間に、ファイルシステムが崩れることがある。\n",
                     "Enterキーを押した瞬間に、入力した内容がわかる。\n",
                     "いつ止まるかというと、保存ボタンを押した瞬間です。\n",
                     "ログを確認した瞬間に原因がわかった。\n",
                     "接続した瞬間に、認証が失われる不具合がある。\n",
                     "ファイルを削除した瞬間に、データを失うおそれがある。\n",
                     "障害が起きたのは、設定を変更した瞬間だった。\n",
                     "エラーが出たのは、保存ボタンを押した瞬間でした。\n"):
            with self.subTest(text=text):
                self.assertEqual(moment_hits(text), [])

    def test_many_moments_in_one_line_stay_fast(self):
        import time
        start = time.perf_counter()
        yomiyasu_lint.lint_text("した瞬間" * 5000 + "\n")
        self.assertLess(time.perf_counter() - start, 1.0)

    def test_one_finding_per_line(self):
        text = "手にした瞬間、すべてが変わった。目にした瞬間に理解した。\n"
        self.assertEqual(len(moment_hits(text)), 1)


class PublicationVersionTest(unittest.TestCase):
    """出版物の文脈の「次の版では」などを、英語の直訳「版」（version）として警告していた誤りの守り。"""

    def test_issue_example_does_not_fire(self):
        text = ("# 改訂の見出し\n\nこの増刷では、語釈の順序を見直しました。\n\n"
                "この辞書の次の版では、見出し語に英語の発音表記を添えます。\n")
        self.assertEqual(findings(text, "translated_term"), [])

    def test_publication_words_in_the_sentence(self):
        for text in ("この本の次の版では、図を増やします。\n", "書籍の次の版で、誤植を直します。\n",
                     "文庫にしたあと、次の版から解説を付けます。\n", "全集は、次の版で索引を足します。\n",
                     "単行本の前の版では、地図が白黒でした。\n", "図鑑の新しい版では写真を差し替えた。\n",
                     "第3版を出したあと、次の版では章を分けます。\n", "初版の誤りは、次の版で直す。\n",
                     "増刷のときに、次の版で表記をそろえる。\n", "改訂を重ね、今の版では索引が倍になった。\n"):
            with self.subTest(text=text):
                self.assertEqual(findings(text, "translated_term"), [])

    def test_software_version_still_fires(self):
        for text in ("この版では読み込みを速くしました。\n", "新しい版で設定の形式が変わりました。\n",
                     "本ツールの次の版では、設定の形式を変えます。\n", "日本語の資料は、次の版で直します。\n",
                     "基本の機能は、今の版ではまだ使えません。\n", "提供元は「次の版で検討中」と回答しています。\n",
                     "3本のスクリプトは、次の版でまとめます。\n",
                     # 出版物の語が前の文にあっても、別の文の「この版では」は拾う
                     "この辞書は改訂した。その版では読み込みが遅い。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(findings(text, "translated_term")), 1)

    def test_more_publication_words(self):
        for text in ("本書の次の版では、索引を足す。\n", "原書の次の版では、図が増える。\n", "訳書の次の版では、注を足す。\n",
                     "この冊子の次の版では、地図を新しくする。\n", "小冊子の次の版では、地図を足す。\n",
                     "この写真集は、次の版で判型を変える。\n", "この画集の次の版では、色を見直す。\n",
                     "この詩集の次の版では、二編を足す。\n", "この作品集の次の版では、図版を足す。\n",
                     "この論文集の次の版では、注を足す。\n", "この新書の次の版では、章を分ける。\n",
                     "英和辞書の次の版では、例文を足す。\n", "改訂版を出したあと、次の版で直す。\n",
                     "文庫化のあと、次の版で解説を足す。\n", "増刷時に、次の版で表記をそろえる。\n"):
            with self.subTest(text=text):
                self.assertEqual(findings(text, "translated_term"), [])

    def test_software_compounds_still_fire(self):
        """出版物の語がソフトウェアの複合語の一部のときは、出版物の語として数えない。"""
        for text in ("辞書型の扱いは、次の版で変えます。\n", "ユーザー辞書の取り込みは、次の版で対応します。\n",
                     "システム辞書の更新は、次の版で行います。\n", "辞書ファイルの形式は、次の版で変えます。\n",
                     "辞書順の並べ替えは、次の版で直します。\n", "日本語の辞書アプリは、次の版で検索を速くする。\n",
                     "新聞記事のクローラーは、次の版で対応します。\n", "出版社向けの管理画面は、次の版で直します。\n",
                     "初版リリースでは未対応でしたが、次の版で対応します。\n",
                     "新版のアプリでは、次の版で設定を見直します。\n", "本APIの次の版では、認証を変えます。\n",
                     "第2版リリースのあと、次の版で直します。\n", "日本書紀の研究は、次の版でまとめます。\n",
                     # 全角のピリオドも文の区切りとして見る
                     "この辞書を更新した．次の版では索引を足す。\n"):
            with self.subTest(text=text):
                self.assertEqual(len(findings(text, "translated_term")), 1)

    def test_publication_word_after_does_not_hide(self):
        """出版物の語が「版」より後ろにあるときは、除かない。"""
        self.assertEqual(len(findings("次の版では、辞書の読み込みを速くします。\n", "translated_term")), 1)


class ScanPathTest(unittest.TestCase):
    """語の表で文を絞る速い経路と、すべての文に当てる経路で、同じ候補になる。"""

    TEXTS = (
        "プログラムでは真理値を使う。人生の真理に気づいた。安全装置と、つなぐ装置。\n",
        "ボタンを押した瞬間に画面が消える。目的にした瞬間に品質は崩れる。\n",
        "この辞書の次の版では表記を変える。この版では読み込みを速くした。\n",
        "辞書型の扱いは、次の版で変えます。本書の次の版では、索引を足す。\n",
        "効率を優先した瞬間に、品質は下がる。電源をオフにした瞬間に、データは失われる。\n",
        "SNSは承認欲求の増幅装置だ。冷却装置と照明装置を点検する。装置の電源を切る。\n",
    )

    def test_narrowed_and_full_scan_agree(self):
        for text in self.TEXTS:
            with self.subTest(text=text):
                fast = yomiyasu_lint.lint_text(text)
                with mock.patch.object(yomiyasu_lint, "_document_tables", return_value=None):
                    full = yomiyasu_lint.lint_text(text)
                self.assertEqual(fast["findings"], full["findings"])
                self.assertTrue(fast["findings"])

    def test_new_patterns_have_hints(self):
        hints = yomiyasu_lint._PATTERN_LITERAL_HINTS
        self.assertEqual(hints[yomiyasu_lint._TRUTH_PATTERN], ("真理",))
        self.assertEqual(hints[yomiyasu_lint._DEVICE_PATTERN], ("装置",))
        self.assertEqual(hints[yomiyasu_lint._MOMENT_PATTERN], ("した瞬間",))
        self.assertEqual(hints[yomiyasu_lint._VERSION_DEMONSTRATIVE_PATTERN], ("版",))
        self.assertIsNotNone(yomiyasu_lint._document_tables())

    def test_rule_names_and_messages_unchanged(self):
        self.assertIn(MOMENT, [desc for _, desc in yomiyasu_lint.METAPHOR_VERB_PATTERNS])
        self.assertEqual([desc for pattern, desc in yomiyasu_lint.TRANSLATED_TERM_PATTERNS
                          if pattern == yomiyasu_lint._VERSION_DEMONSTRATIVE_PATTERN], ["「版」（version）"])
        self.assertNotIn("真理", yomiyasu_lint.SLOP_WORDS)
        self.assertNotIn("装置", yomiyasu_lint.SLOP_WORDS)
        self.assertEqual([word for word, _ in yomiyasu_lint.SLOP_WORD_PATTERNS][-2:], ["真理", "装置"])

    def test_long_line_stays_fast(self):
        import time
        text = ("この版" + "あ" * 20000 + "。") * 5 + "\n"
        start = time.perf_counter()
        yomiyasu_lint.lint_text(text)
        self.assertLess(time.perf_counter() - start, 5.0)


if __name__ == "__main__":
    unittest.main()
