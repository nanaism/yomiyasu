#!/usr/bin/env python3
"""v2.0.2: diff の太字の検査も、1つの段落に崩れた太字が多いときに崩れの数の2乗の仕事をしない。

yomiyasu_diff.py は、書き直した文の太字の検査（bold_problems）に lint と同じ処理の写しを持っている。v2.0.2 で lint に入れた
速さの直し（直し方の案を、元の解析の結果から決められるときは段落全体を解析し直さない）を、diff の写しにも入れた。
tests/test_lint_performance_regressions.py の太字の試験と同じ形で、diff の写しを見る。時間ではなく、解析した字数、
印の前後を調べた回数、元の解析から案を決めるための表を作った回数を数える。文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_diff  # noqa: E402


class TestDiffBoldRepairPerformance(unittest.TestCase):
    def test_many_broken_bold_in_one_paragraph_do_linear_repair_work(self):
        # 1つの段落に直せる崩れが多いとき、案を確かめるたびに段落全体を解析し直すと、崩れの数の2乗の仕事になる
        # （v2.0.1 の diff では、lint と同じく1段落に1,000組で数秒、3,000組で数十秒かかった）。
        unit = "これは **「重要」**です。"
        work = {}
        for count in (40, 80, 160):
            text = unit * count
            with patch.object(yomiyasu_diff, "analyze_markdown", wraps=yomiyasu_diff.analyze_markdown) as analyzed, \
                    patch.object(yomiyasu_diff, "_roles", wraps=yomiyasu_diff._roles) as roles:
                findings = yomiyasu_diff.bold_problems(text)
            self.assertEqual(len(findings), 2 * count - 1)
            self.assertEqual([item["how"] for item in findings[:3]],
                             ["かっこの内側だけを太字にする", "手で直す", "かっこの内側だけを太字にする"])
            self.assertEqual(findings[-1]["found"], "これは **「重要」**です。")
            self.assertEqual(findings[-1]["suggest"], "これは 「**重要**」です。")
            work[count] = (sum(len(call.args[0]) for call in analyzed.call_args_list), roles.call_count)
            # 段落全体を解析し直すのは、決まった回数まで（元の文書と、表を作る前に解析し直す2回と、表の1回）。
            self.assertLessEqual(work[count][0], 6 * len(text))
        for count in (80, 160):
            with self.subTest(count=count):
                # 組の数を2倍にしたとき、仕事が3倍未満で済む（2乗なら4倍になる）。
                self.assertLess(work[count][0], 3 * work[count // 2][0])
                self.assertLess(work[count][1], 3 * work[count // 2][1])

    def test_bold_repairs_from_the_original_parse_match_full_reparse(self):
        # 元の解析から決めた案が、案ごとに段落全体を解析し直したときと同じになる。崩れを3組以上並べて、
        # 表を使う道を通す。diff の全体の結果（JSON に出す辞書と通常の出力）と、--endings の出力も比べる。
        units = (
            "これは **「重要」**です。",
            "**「重要」**です。\n",
            "> **「重要」**です。\n",
            "- 項目\n  **「重要」**です。\n",
            "これは **「`code`」**です。",
            "これは [リンク](https://example.com) **「重要」**です。",
            "これは https://example.com **「重要」**です。",
            "これは **「重要」**です。ここは **太字** です。",
            "これは **(重要)**です。",
            "これは **[重要]**(x)です。",
            "これは!**[重要]**です。",
            "これは **重要!**[a](b)です。",
            "これは **重要。**です",
            "これは \\**「重要」**です。",
            "これは **「重要」**\\です。",
            "これは**「重要」**です。 **ok**、",
            "、**「重要」**です。*x*",
            "# **「重要」**です。\n",
            "**「重要」**www.example.com です。",
            "これは **「www.example.com」** です。",
            "a**b」**c **「d**e。",
        )
        original = "これは元の文です。保存期間は3日です。\n"
        texts = [unit * 4 for unit in units] + ["".join(units), "\n".join(units)]
        for text in texts:
            with self.subTest(text=text):
                expected = yomiyasu_diff.diff(original, text)
                expected_report = yomiyasu_diff.report(expected)
                expected_endings = yomiyasu_diff._endings_report(text, None)
                with patch.object(yomiyasu_diff, "_bold_repair_index", return_value=None):
                    result = yomiyasu_diff.diff(original, text)
                    self.assertEqual(result, expected)
                    self.assertEqual(yomiyasu_diff.report(result), expected_report)
                    self.assertEqual(yomiyasu_diff._endings_report(text, None), expected_endings)

    def test_repair_table_is_built_only_when_enough_pairs_remain(self):
        # 表を作る手間は段落全体を解析し直す1回分とほぼ同じなので、案を確かめる組が残り3組未満のときに作ると、
        # 作る手間のほうが省ける手間より大きい。直せる崩れが3つの段落では表を作らず、4つ以上なら段落ごとに1回作る。
        unit = "これは **「重要」**です。"
        for count, built in ((3, 0), (4, 1), (40, 1)):
            with self.subTest(count=count):
                text = "\n\n".join([unit * count] * 3) + "\n"
                with patch.object(yomiyasu_diff, "_BoldRepairIndex", wraps=yomiyasu_diff._BoldRepairIndex) as index:
                    findings = yomiyasu_diff.bold_problems(text)
                self.assertEqual(index.call_count, 3 * built)
                self.assertEqual(len(findings), 3 * (2 * count - 1))
                with patch.object(yomiyasu_diff, "_bold_repair_index", return_value=None):
                    self.assertEqual(yomiyasu_diff.bold_problems(text), findings)

    def test_forced_repair_table_declines_where_a_full_reparse_differs(self):
        # 最初の案から表で決めさせても、案ごとに段落全体を解析し直したときと同じ答えになる。表を使う前の確かめを
        # 1つ外すと答えが食い違う文を3つ選んだ。1つめは GFM の規則で閉じる相手を探した下限より後ろに (1, False) の
        # 開ける印が残る形、2つめはブロックに「<」がある形（動かした「]」で CDATA の終わりの「]]>」ができる）、
        # 3つめは「(」を動かすと「]」と隣り合ってリンクの「](」ができる形。
        cases = (
            (" *a *b **「。x」**→ y*z w** ", True),
            ("前 <![CDATA[ a**[x]**]> **[y]**c **[z]**c", False),
            ("x **x!** [b]**(x)**a", True),
        )
        original_scan = yomiyasu_diff._bold_scan_context
        original_decide = yomiyasu_diff._BoldRepairIndex.decide
        verdicts = []

        def scan(block_text, runs):
            result = original_scan(block_text, runs)
            result[3]["slow_tries"] = 2
            yomiyasu_diff._bold_repair_index(block_text, result[3])  # 残りの組の数によらず、表を先に作る
            return result

        def decide(index, i, j, shape, middle):
            verdict = original_decide(index, i, j, shape, middle)
            verdicts.append(verdict)
            return verdict

        for text, decided in cases:
            with self.subTest(text=text):
                with patch.object(yomiyasu_diff, "_bold_repair_index", return_value=None):
                    expected = yomiyasu_diff.bold_problems(text)
                del verdicts[:]
                with patch.object(yomiyasu_diff, "_bold_scan_context", side_effect=scan), \
                        patch.object(yomiyasu_diff._BoldRepairIndex, "decide", decide):
                    self.assertEqual(yomiyasu_diff.bold_problems(text), expected)
                # 表から決めた案があるか（「<」のあるブロックでは表を作らないので、1つもない）
                self.assertEqual(any(verdict is not None for verdict in verdicts), decided)


if __name__ == "__main__":
    unittest.main()
