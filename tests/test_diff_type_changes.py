#!/usr/bin/env python3
"""v1.1.2: 推敲の前後で文を対応させ、文の種類を示す印（伝聞・推量・意見・例え・依頼）の消失と追加を候補にする。"""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


def changes(orig, rewrite):
    return yomiyasu_diff.diff(orig + "\n", rewrite + "\n")["type_changes"]


def kinds(entries, side):
    return [mark["kind"] for entry in entries for mark in entry[side]]


class TestMeaningShifts(unittest.TestCase):
    """SKILL.mdの「文の種類」で防ぎたい4つのずれ。"""

    def test_hearsay_to_assertion(self):
        found = changes("原因は設定ミスだとされる。", "原因は設定ミスだ。")
        self.assertEqual(kinds(found, "lost"), ["伝聞"])
        self.assertEqual(found[0]["lost"][0]["hits"], ["とされる"])
        self.assertEqual(found[0]["orig"], "原因は設定ミスだとされる。")
        self.assertEqual(found[0]["rewrite"], "原因は設定ミスだ。")

    def test_simile_to_assertion(self):
        self.assertIn("例え", kinds(changes("机はまるで戦場のようだ。", "机は戦場だ。"), "lost"))

    def test_opinion_to_fact(self):
        self.assertEqual(kinds(changes("この方式は遅いと思う。", "この方式は遅い。"), "lost"), ["意見"])

    def test_request_to_explanation(self):
        self.assertEqual(kinds(changes("資料を共有してください。", "資料を共有します。"), "lost"), ["依頼・決まり"])

    def test_other_hearsay_and_simile_forms(self):
        for orig, rewrite, kind in (("明日は雨が降るそうだ。", "明日は雨が降る。", "伝聞"),
                                    ("障害は設定ミスが原因とされる。", "障害は設定ミスが原因だ。", "伝聞"),
                                    ("担当者によると、修正は済んでいる。", "修正は済んでいる。", "伝聞"),
                                    ("新しい版では起動が速くなったらしい。", "新しい版では起動が速くなった。", "推量"),
                                    ("彼の机はまるで戦場のようだ。", "彼の机は散らかっている。", "例え")):
            with self.subTest(orig=orig):
                self.assertIn(kind, kinds(changes(orig, rewrite), "lost"))


class TestPerSentenceComparison(unittest.TestCase):
    def test_marks_moved_between_sentences_do_not_cancel(self):
        found = changes("Aは速いらしい。Bは遅い。", "Aは速い。Bは遅いだろう。")
        self.assertEqual([(entry["orig"], kinds([entry], "lost"), kinds([entry], "added")) for entry in found],
                         [("Aは速いらしい。", ["推量"], []), ("Bは遅い。", [], ["推量"])])

    def test_split_sentence_keeps_the_mark(self):
        self.assertEqual(changes("Aは速いらしいが、Bは遅い。", "Aは速いらしい。Bは遅い。"), [])

    def test_unchanged_marks_are_quiet(self):
        for orig, rewrite in (("原因は設定ミスだとされる。", "原因は、設定ミスだとされる。"),
                              ("机はまるで戦場のようだ。", "机は、まるで戦場のようだ。"),
                              ("資料を共有してください。", "資料を、共有フォルダに置いてください。")):
            with self.subTest(orig=orig):
                self.assertEqual(changes(orig, rewrite), [])


class TestSameTypeRewrites(unittest.TestCase):
    """言い方が変わっても種類が同じなら出さない（コーパスで見つけた形）。"""

    def test_same_type_different_forms(self):
        for orig, rewrite in (("木曜までに私へ連絡をください。", "木曜までに私へ連絡してください。"),
                              ("作業前に保存をお願いします。", "作業前に保存してください。"),
                              ("下記のとおりご対応をお願いします。", "下記のとおりご対応ください。"),
                              ("キャッシュ設計を自前で固める必要がある。", "キャッシュ設計を自前で実装しなければならない。"),
                              ("最大の成果であったと考える。", "最大の成果だったと考えている。")):
            with self.subTest(orig=orig):
                self.assertEqual(changes(orig, rewrite), [])

    def test_fact_to_obligation_is_reported(self):
        found = changes("上限値もキャパシティ計画の対象だと改めて認識しました。", "上限値もキャパシティ計画の対象にすべきだと認識しました。")
        self.assertEqual(kinds(found, "added"), ["依頼・決まり"])

    def test_closing_greeting_is_not_a_request(self):
        self.assertEqual(changes("以上です。よろしくお願いします。", "以上です。"), [])


class TestUnrelatedUses(unittest.TestCase):
    """種類と関係のない「そうだ」「ように」「という」では出さない。"""

    def test_unrelated_forms_are_quiet(self):
        for orig, rewrite in (("空を見ると、雨が降りそうだ。", "空を見ると、雨が降る気配がある。"),
                              ("ログを読めるように設定する。", "ログを読める設定にする。"),
                              ("ツールは「よみやす」という名前で公開する。", "ツールは「よみやす」の名で公開する。"),
                              ("この関数はべき乗を計算する。", "この関数は累乗を計算する。"),
                              ("しかるべき手続きを経て公開する。", "必要な手続きを経て公開する。")):
            with self.subTest(orig=orig):
                self.assertEqual(changes(orig, rewrite), [])


class TestOutputShape(unittest.TestCase):
    def test_existing_keys_are_kept_and_type_changes_is_added(self):
        result = yomiyasu_diff.diff("資料を共有してください。\n", "資料を共有します。\n")
        self.assertEqual(list(result), ["markers", "new_words", "lost_words", "structure", "spans", "logic", "bold",
                                        "endings", "type_changes"])
        self.assertEqual(set(result["type_changes"][0]), {"orig", "rewrite", "lost", "added"})

    def test_report_has_the_new_heading_only_when_needed(self):
        changed = yomiyasu_diff.report(yomiyasu_diff.diff("原因は設定ミスだとされる。\n", "原因は設定ミスだ。\n"))
        self.assertIn("■ 文の種類の印が変わった文", changed)
        self.assertIn("消えた印: 伝聞（とされる）", changed)
        self.assertIn("原因は設定ミスだとされる。", changed)
        quiet = yomiyasu_diff.report(yomiyasu_diff.diff("原因は設定ミスだとされる。\n", "原因は、設定ミスだとされる。\n"))
        self.assertNotIn("文の種類の印", quiet)

    def test_cli_json_includes_type_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / "a.md", Path(folder) / "b.md"
            before.write_text("この方式は遅いと思う。\n", encoding="utf-8")
            after.write_text("この方式は遅い。\n", encoding="utf-8")
            process = subprocess.run([sys.executable, str(ROOT / "scripts" / "yomiyasu_diff.py"), str(before), str(after), "--json"],
                                     capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout)["type_changes"][0]["lost"][0]["kind"], "意見")

    def test_standalone_ending_changes_is_unchanged(self):
        self.assertEqual(yomiyasu_diff.ending_changes("Aは速いらしい。Bは遅い。", "Aは速い。Bは遅いだろう。"),
                         [{"orig": "Bは遅い。", "orig_kind": "常体", "rewrite": "Bは遅いだろう。", "rewrite_kind": "推量・考え"}])


if __name__ == "__main__":
    unittest.main()
