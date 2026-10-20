#!/usr/bin/env python3
"""v2.1.1: diff の「構造」の見直し候補に、見出しの変化を出す試験。

太字の行を見出しにした組と、見出しの段を変えた組は、v2.1.0 では全文差分に注記が付くだけで、structure は空、
candidate_count は0だった。見出しの数の増減、太字の行や本文の行を見出しにしたこと、見出しを本文の行にしたこと、
見出しの段の変化を structure に出し、意味が変わる恐れと --fail-on=meaning-risk の終了コードは変えないことを確かめる。
文はどれもこのファイルで作った合成の文。
"""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


BOLD_SRC = "# 手順\n\n**前提条件**\n\n設定を確認します。\n\n**作業内容**\n\n値を更新します。\n"
BOLD_DST = "# 手順\n\n#### 前提条件\n\n設定を確認します。\n\n#### 作業内容\n\n値を更新します。\n"
LEVEL_SRC = "# 手順\n\n### 前提\n\n設定を確認します。\n"
LEVEL_DST = "# 手順\n\n#### 前提\n\n設定を確認します。\n"
HEADING_PREFIXES = ("見出しの数が変わった", "太字の行を見出しにした", "本文の行を見出しにした", "見出しを本文の行にした",
                    "見出しの段を変えた")


def heading_entries(result):
    return [s for s in result["structure"] if s.startswith(HEADING_PREFIXES)]


def run_cli(src, dst, *args):
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "a.md", Path(tmp) / "b.md"
        a.write_text(src, encoding="utf-8")
        b.write_text(dst, encoding="utf-8")
        return subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "yomiyasu_diff.py"), str(a), str(b)] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8")


class BoldToHeadingTest(unittest.TestCase):
    def test_bold_lines_to_headings_are_structure_candidates(self):
        """太字の行2つを #### の見出しにした組が、変更はあるのに候補0件になっていた不具合を防ぐ。"""
        result = yomiyasu_diff.diff(BOLD_SRC, BOLD_DST)
        self.assertEqual(result["structure"], [
            "見出しの数が変わった（1 → 3）。節の分け方が元と同じでよいか見る",
            "太字の行を見出しにした（元3行目「**前提条件**」→ 後3行目「#### 前提条件」、"
            "元7行目「**作業内容**」→ 後7行目「#### 作業内容」）",
        ])
        self.assertEqual(result["status"], "has_candidates")
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["meaning_risk_count"], 0)
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_report_lists_the_heading_candidates(self):
        out = yomiyasu_diff.report(yomiyasu_diff.diff(BOLD_SRC, BOLD_DST))
        self.assertIn("見直し候補 2件、うち意味が変わる恐れ 0件", out)
        self.assertIn("■ 太字の行を見出しにした（元3行目「**前提条件**」→ 後3行目「#### 前提条件」", out)
        self.assertNotIn("専用の規則に当たる見直し候補はない", out)

    def test_bold_label_with_colon_and_shifted_lines(self):
        """太字の行と見出しが全文差分の別の hunk に入っても（行の対応がずれても）、組にして挙げる。"""
        src = ("**原因**\n設定の値が古いままだったことが原因である。\n\n**対応**\n設定の値を直した。\n\n"
               "**今後の対策：**\n設定を見直す。\n")
        dst = ("## 原因\n\n古い設定の値を使い続けていた。\n\n## 対応\n\n担当者が設定の値を直した。\n\n"
               "## 今後の対策\n\n担当者が設定を見直す。\n")
        entries = heading_entries(yomiyasu_diff.diff(src, dst))
        self.assertEqual(entries[0], "見出しの数が変わった（0 → 3）。節の分け方が元と同じでよいか見る")
        self.assertEqual(len(entries), 2)
        for old, new in (("**原因**", "## 原因"), ("**対応**", "## 対応"), ("**今後の対策：**", "## 今後の対策")):
            self.assertIn("「{}」→".format(old), entries[1])
            self.assertIn("「{}」".format(new), entries[1])

    def test_many_lines_are_shortened(self):
        labels = ["項目{}".format(n) for n in range(1, 6)]
        src = "".join("**{}**\n\n説明です。\n\n".format(label) for label in labels)
        dst = "".join("## {}\n\n説明です。\n\n".format(label) for label in labels)
        entries = heading_entries(yomiyasu_diff.diff(src, dst))
        self.assertTrue(entries[1].startswith("太字の行を見出しにした（元1行目「**項目1**」→ 後1行目「## 項目1」"))
        self.assertTrue(entries[1].endswith("、ほか2か所）"))

    def test_plain_body_line_to_heading(self):
        src = "障害の報告\n\n設定を確認しました。\n"
        dst = "# 障害の報告\n\n設定を確認しました。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [
            "見出しの数が変わった（0 → 1）。節の分け方が元と同じでよいか見る",
            "本文の行を見出しにした（元1行目「障害の報告」→ 後1行目「# 障害の報告」）",
        ])

    def test_line_with_two_bold_parts_is_not_called_bold_line(self):
        """「**a** と **b**」のように太字が2つある行は、行の全体の太字として挙げない。"""
        src = "**入力** と **出力**\n\n値を渡します。\n"
        dst = "## 入力 と 出力\n\n値を渡します。\n"
        entries = heading_entries(yomiyasu_diff.diff(src, dst))
        self.assertEqual(entries[0], "見出しの数が変わった（0 → 1）。節の分け方が元と同じでよいか見る")
        self.assertFalse(any(s.startswith("太字の行を見出しにした") for s in entries))


class HeadingLevelTest(unittest.TestCase):
    def test_level_change_is_a_structure_candidate(self):
        """### を #### にした組が、全文差分の「見出しの段 3 → 4」だけで候補0件になっていた不具合を防ぐ。"""
        result = yomiyasu_diff.diff(LEVEL_SRC, LEVEL_DST)
        self.assertEqual(result["structure"], ["見出しの段を変えた（元3行目 段3「### 前提」→ 後3行目 段4「#### 前提」）"])
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["meaning_risk_count"], 0)

    def test_level_and_text_changed_together(self):
        src = "# 手順\n\n## 前提の条件\n\n設定を確認します。\n"
        dst = "# 手順\n\n### 前提条件\n\n設定を確認します。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)),
                         ["見出しの段を変えた（元3行目 段2「## 前提の条件」→ 後3行目 段3「### 前提条件」）"])

    def test_setext_to_atx(self):
        src = "手順\n====\n\n設定を確認します。\n"
        same = "# 手順\n\n設定を確認します。\n"
        lower = "## 手順\n\n設定を確認します。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, same)), [])
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, lower)),
                         ["見出しの段を変えた（元1行目 段1「手順」→ 後1行目 段2「## 手順」）"])


class HeadingToBodyTest(unittest.TestCase):
    def test_heading_to_bold_line(self):
        src = "# 手順\n\n## 前提条件\n\n設定を確認します。\n"
        dst = "# 手順\n\n**前提条件**\n\n設定を確認します。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [
            "見出しの数が変わった（2 → 1）。節の分け方が元と同じでよいか見る",
            "見出しを本文の行にした（元3行目「## 前提条件」→ 後3行目「**前提条件**」）",
        ])


class NoHeadingChangeTest(unittest.TestCase):
    def test_rewrite_that_keeps_headings(self):
        src = "# 手順\n\n## 前提条件\n\n設定を確認することが重要です。\n\n**注意**\n\n値を更新します。\n"
        dst = "# 手順\n\n## 前提条件\n\n設定を確認します。\n\n**注意**\n\n値を更新しました。\n"
        result = yomiyasu_diff.diff(src, dst)
        self.assertEqual(heading_entries(result), [])

    def test_heading_text_rewritten_at_same_level(self):
        src = "# 手順\n\n## 前提条件について\n\n設定を確認します。\n"
        dst = "# 手順\n\n## 前提条件\n\n設定を確認します。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [])

    def test_hash_lines_in_code_are_not_headings(self):
        src = "# 手順\n\n```sh\n# 設定を読む\nmake\n```\n"
        dst = "# 手順\n\n```sh\n## 設定を読む\nmake\n```\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [])

    def test_dash_after_list_item_is_not_a_heading_underline(self):
        """箇条書きの項目のあとの、字下げのない「- 」は次の項目で、見出しの下線として数えない（見出しの数を誤って変えない）。"""
        src = "# 確認\n\n- 在庫はいくつか\n- \n- 届くのはいつか\n- \n"
        dst = "# 確認\n\n- 在庫の数\n- 届く日\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [])

    def test_no_change(self):
        result = yomiyasu_diff.diff(BOLD_SRC, BOLD_SRC)
        self.assertEqual(result["structure"], [])
        self.assertEqual(result["status"], "no_change")


class HeadingPairingTest(unittest.TestCase):
    """見出しの組の作り方。見出しどうしの組を先に作り、同じ位置で段と文字を一緒に変えた見出しも段の変化として出す。"""

    def test_bold_line_with_same_text_does_not_hide_level_change(self):
        """同じ文字の太字の行を見出しの前に足し、見出しの段も変えた組で、見出しと太字の行を組にしない。"""
        src = "# 手順\n\n## 準備\n\n道具をそろえる。\n\n## 注意\n\n電源を切る。\n"
        dst = "# 手順\n\n## 準備\n\n道具をそろえる。\n\n**注意**\n\n手袋を付ける。\n\n### 注意\n\n電源を切る。\n"
        result = yomiyasu_diff.diff(src, dst)
        self.assertEqual(heading_entries(result),
                         ["見出しの段を変えた（元7行目 段2「## 注意」→ 後11行目 段3「### 注意」）"])
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_same_text_headings_pair_inside_their_own_hunk(self):
        """同じ文字の見出しが並ぶ文書でも、同じ hunk の中の見出しどうしを先に組にする。"""
        src = "## 注意\n\n本文です。\n\n## 注意\n\n本文です。\n"
        dst = "**注意**\n\n本文です。\n\n### 注意\n\n本文です。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [
            "見出しの数が変わった（2 → 1）。節の分け方が元と同じでよいか見る",
            "見出しを本文の行にした（元1行目「## 注意」→ 後1行目「**注意**」）",
            "見出しの段を変えた（元5行目 段2「## 注意」→ 後5行目 段3「### 注意」）",
        ])

    def test_level_and_unrelated_text_changed_at_same_position(self):
        """同じ位置の見出しの段と文字を一緒に変えた組は、文字が似ていなくても段の変化として出す。"""
        src = "# 手順\n\n## 前提\n\n本文です。\n"
        dst = "# 手順\n\n### 準備するもの\n\n本文です。\n"
        result = yomiyasu_diff.diff(src, dst)
        self.assertEqual(heading_entries(result),
                         ["見出しの段を変えた（元3行目 段2「## 前提」→ 後3行目 段3「### 準備するもの」）"])
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)
        src = "# 手順\n\n## 前提\n\n本文です。\n\n## 作業\n\n値を更新します。\n"
        dst = "# 手順\n\n### 必要なもの\n\n本文です。\n\n## 作業\n\n値を更新します。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)),
                         ["見出しの段を変えた（元3行目 段2「## 前提」→ 後3行目 段3「### 必要なもの」）"])

    def test_unrelated_text_at_same_level_is_not_a_level_change(self):
        src = "# 手順\n\n## 前提\n\n本文です。\n"
        dst = "# 手順\n\n## 準備するもの\n\n本文です。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [])

    def test_headings_of_other_sections_in_one_hunk_are_not_paired(self):
        """行の対応がずれて、別の節の見出し（文書の中で何番目かが違う見出し）が同じ hunk に入っても、段の変化にしない。"""
        src = ("# 手順\n\n### 一. 準備\n道具をそろえる。\n\n### 二. 作業\n値を更新する。\n\n## まとめ\n\n"
               "以上で作業は終わりです。\n\n次回もこの手順で進めます。\n")
        dst = ("# 手順\n\n### 一. 道具の準備\n\n道具をそろえます。\n\n### 二. 値の更新\n\n値を更新します。\n\n"
               "## 今後の進め方\n\n次回もこの手順で進めます。\n")
        result = yomiyasu_diff.diff(src, dst)
        hunks = [(h["old_lines"], h["new_lines"]) for h in result["full_diff"]["hunks"]]
        self.assertIn((["## まとめ"], ["### 二. 値の更新"]), hunks)
        self.assertEqual(heading_entries(result), [])

    def test_section_rewritten_with_its_body_is_not_paired_by_position(self):
        """見出しと節の本文をまとめて別の中身に書き換えた組は、文字の似ていない見出しを位置だけで組にしない。"""
        src = "# 週報\n\n今週は設定を見直しました。\n"
        dst = "## お知らせ\n\n来週の作業はお休みです。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [])

    def test_removed_setext_underline(self):
        """setext の下線の行だけを消して太字の行に戻した組で、どの行かを挙げる。"""
        src = "# 手順\n\n**前提**\n----\n\n本文です。\n"
        dst = "# 手順\n\n**前提**\n\n本文です。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, dst)), [
            "見出しの数が変わった（2 → 1）。節の分け方が元と同じでよいか見る",
            "見出しを本文の行にした（元3行目「**前提**」と4行目「----」→ 後3行目「**前提**」）",
        ])
        self.assertEqual(heading_entries(yomiyasu_diff.diff(dst, src)), [
            "見出しの数が変わった（1 → 2）。節の分け方が元と同じでよいか見る",
            "太字の行を見出しにした（元3行目「**前提**」→ 後3行目「**前提**」と4行目「----」）",
        ])

    def test_setext_underline_changed_level(self):
        src = "# 手順\n\n前提\n----\n\n本文です。\n"
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, src.replace("----", "===="))),
                         ["見出しの段を変えた（元3行目 段2「前提」→ 後3行目 段1「前提」）"])
        self.assertEqual(heading_entries(yomiyasu_diff.diff(src, src.replace("----", "------"))), [])

    def test_fail_on_exit_code_for_new_pairs(self):
        cases = (("# 手順\n\n## 前提\n\n本文です。\n", "# 手順\n\n### 準備するもの\n\n本文です。\n"),
                 ("# 手順\n\n**前提**\n----\n\n本文です。\n", "# 手順\n\n**前提**\n\n本文です。\n"))
        for src, dst in cases:
            proc = run_cli(src, dst, "--fail-on=meaning-risk", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertGreaterEqual(len(heading_entries(data)), 1)
            self.assertEqual(data["fail_on_meaning_risk_count"], 0)


class FailOnTest(unittest.TestCase):
    def test_fail_on_meaning_risk_exit_code_is_unchanged(self):
        """見出しの候補は意味が変わる恐れに数えないので、--fail-on=meaning-risk の終了コードは0のまま。"""
        for src, dst in ((BOLD_SRC, BOLD_DST), (LEVEL_SRC, LEVEL_DST)):
            proc = run_cli(src, dst, "--fail-on=meaning-risk")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            proc = run_cli(src, dst, "--fail-on=meaning-risk", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertGreaterEqual(len(heading_entries(data)), 1)
            self.assertEqual(data["fail_on_meaning_risk_count"], 0)

    def test_fail_on_still_counts_meaning_risks(self):
        """見出しと数値を一緒に変えた組は、今までどおり数値の恐れで終了コード1になる。"""
        src = "**前提条件**\n\n設定を3回確認します。\n"
        dst = "## 前提条件\n\n設定を5回確認します。\n"
        proc = run_cli(src, dst, "--fail-on=meaning-risk")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
