"""v2.2.1: check が、最終稿に残った直訳語（calque）と語の一覧（project_term）の語を「残した印の語」として出すかを確かめる。

- run は、頭の一覧のあとに「残した印の語: 語（種類。L行）」の行を、「■ 意味が変わる恐れ」のあとに「■ 残した印の語」の節を出す。
- verify は、記録と合ったときに同じ語を「残した印の語:」の行で出す（記録の lint の要約 kept_marks を読むだけ）。
- --json の run と verify に kept_marks が付く。印がなければ空の並びで、行と節は出さない。
- 状態と終了コードは変わらない。

文はすべて合成の文。
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts" / "yomiyasu_check.py"

TECH = ("この資料は、社内の API とデータベースの運用をまとめたものです。認証にはトークンを使い、エラーはログに残します。"
        "設定は JSON のファイルに書き、URL は社内の画面から確かめます。\n\n")
SOURCE = TECH + "外部からの要求は、どれもこの入口を通ります。\n\nバッチを日中に回すと、全店舗に響きます。\n"
KEPT = TECH + "外部からの要求は、どれも公開エンドポイントを通ります。\n\nバッチを日中に回すと、全店舗に響きます。\n"
CLEAN = TECH + "外部からのリクエストは、どれも公開エンドポイントを通ります。\n\nバッチを日中に回すと、全店舗のレジの画面が遅くなります。\n"


class KeptMarksTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-kept-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        words = self.root / "words"
        words.mkdir()
        (words / "flag.txt").write_bytes("要求\n".encode("utf-8"))
        self.words = words
        self.source = self.write("source.md", SOURCE)

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def check(self, *args):
        env = dict(os.environ)
        env["YOMIYASU_STATE_DIR"] = str(self.root / ".yomiyasu")
        process = subprocess.run([sys.executable, "-B", str(CHECK)] + [str(arg) for arg in args], capture_output=True,
                                 cwd=str(self.root), env=env)
        return process.returncode, process.stdout.decode("utf-8"), process.stderr.decode("utf-8")

    def run_final(self, text, *extra):
        final = self.write("final.md", text)
        return final, self.check("run", "--source", self.source, "--final", final, "--words", self.words, *extra)

    def test_run_lists_the_kept_words_in_the_head_and_a_section(self):
        _, (code, out, err) = self.run_final(KEPT)
        self.assertEqual((code, err), (0, ""))
        head = [line for line in out.splitlines()[:8] if line.startswith("残した指摘の語: ")]
        self.assertEqual(len(head), 1, out)
        self.assertIn("要求（語の一覧。L3）", head[0])
        self.assertIn("に響く（直訳語。L5）", head[0])
        self.assertIn("■ 残した指摘の語（最終稿の直訳語と語の一覧の指摘。2語）", out)
        section = out.split("■ 残した指摘の語（", 1)[1].split("\n\n", 1)[0]
        self.assertIn("「書き手に確かめたい点」で尋ねる", section)
        self.assertIn("- 要求（語の一覧。L3）", section)

    def test_verify_repeats_the_kept_words_and_replay_matches(self):
        final, (code, _, _) = self.run_final(KEPT)
        self.assertEqual(code, 0)
        code, out, err = self.check("verify", "--final", final)
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(len(lines), 5, lines)
        self.assertTrue(lines[4].startswith("残した指摘の語: 要求（語の一覧。L3）、に響く（直訳語。L5）。"), lines)
        code, out, err = self.check("verify", "--final", final, "--replay")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("replay=ok", out)

    def test_json_has_kept_marks_on_run_and_verify(self):
        final, (code, out, _) = self.run_final(KEPT, "--json")
        self.assertEqual(code, 0)
        expected = [{"rule": "project_term", "word": "要求", "lines": [3]}, {"rule": "calque", "word": "に響く", "lines": [5]}]
        self.assertEqual(json.loads(out)["kept_marks"], expected)
        code, out, _ = self.check("verify", "--final", final, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kept_marks"], expected)

    def test_nothing_is_added_without_kept_marks(self):
        final, (code, out, err) = self.run_final(CLEAN)
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("残した指摘の語", out)
        code, out, _ = self.check("verify", "--final", final)
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 4)
        _, (code, out, _) = self.run_final(CLEAN, "--json", "--no-record")
        self.assertEqual(json.loads(out)["kept_marks"], [])

    def test_many_lines_are_shortened(self):
        text = TECH + "".join("外部からの要求は、どれも公開エンドポイントを通ります。\n\n" for _ in range(8))
        _, (code, out, _) = self.run_final(text, "--no-record")
        self.assertEqual(code, 0)
        self.assertIn("要求（語の一覧。L3、L5、L7、L9、L11、ほか3行）", out)


class KeptMarksHelperTest(unittest.TestCase):
    """_kept_marks を直接呼ぶ（語ごとのまとめ方、語の取り出し方、手間）。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "scripts"))
        import yomiyasu_check
        cls.check = yomiyasu_check

    def finding(self, rule, line, words):
        if rule == "calque":
            message = "直訳語（型2: 実物の名前の代わりに場所のたとえを使う名詞。当たった言い方: {}）の候補です。".format("、".join(words))
        else:
            message = "語の一覧（flag.txt）の語（{}）の候補です。".format("、".join(words))
        return {"rule": rule, "line": line, "severity": "info", "message": message + "文脈を見て、誰が何をどうするかを書き直すか確かめてください。"}

    def test_same_word_with_both_marks_is_listed_once_as_project_term(self):
        marks = self.check._kept_marks([self.finding("calque", 7, ["入口"]), self.finding("project_term", 3, ["要求", "入口"]),
                                        self.finding("calque", 3, ["入口"])])
        # 最初の行が同じ語どうしは、候補に出た順（入口が先）
        self.assertEqual(marks, [{"rule": "project_term", "word": "入口", "lines": [3, 7]},
                                 {"rule": "project_term", "word": "要求", "lines": [3]}])

    def test_words_with_full_width_parentheses_are_read_whole(self):
        marks = self.check._kept_marks([self.finding("project_term", 1, ["決済（旧）"])])
        self.assertEqual(marks, [{"rule": "project_term", "word": "決済（旧）", "lines": [1]}])

    def test_cost_grows_with_the_number_of_findings(self):
        import time
        findings = [self.finding("project_term", line, ["要求"]) for line in range(1, 20001)]
        started = time.perf_counter()
        marks = self.check._kept_marks(findings)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(len(marks[0]["lines"]), 20000)


if __name__ == "__main__":
    unittest.main()
