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

    def test_publication_word_after_does_not_hide(self):
        """出版物の語が「版」より後ろにあるときは、除かない。"""
        self.assertEqual(len(findings("次の版では、辞書の読み込みを速くします。\n", "translated_term")), 1)


class ScanPathTest(unittest.TestCase):
    """語の表で文を絞る速い経路と、すべての文に当てる経路で、同じ候補になる。"""

    TEXTS = (
        "プログラムでは真理値を使う。人生の真理に気づいた。安全装置と、つなぐ装置。\n",
        "ボタンを押した瞬間に画面が消える。目的にした瞬間に品質は崩れる。\n",
        "この辞書の次の版では表記を変える。この版では読み込みを速くした。\n",
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
