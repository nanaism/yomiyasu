"""v2.5.0: 依頼で指定した見出しの形と、まとめの節（5a）。

diff は「見出しの数が変わった」の文に消えた見出しの文字を足し、見出しの形の変化（元の見出しが句点で終わる、読点を含む、
15字を超える）を JSON の heading_shapes と「■ 見出しの形が変わった」の節に出す。どちらも meaning_risk_count、状態、--fail-on に
入れない。check は資料に「見出し」「まとめ」「字数」などの語があるとき、見出しの形の節と、見出しの数の候補がある節を先に出す。
例は tests/corpus/requests の合成のスライドと記事（元、後、依頼の文。.md の数え方に入れないよう .txt で置く）。
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REQUESTS = ROOT / "tests" / "corpus" / "requests"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402

CASES = {
    # (元, 後, 依頼, 見出しの数の文, 形が変わった見出しの (元, 後), v2.4.0 の meaning_risk_count)
    "slides": ("slides_heading_orig.txt", "slides_heading_final.txt", "slides_heading_request.txt",
               "見出しの数が変わった（5 → 4）。節の分け方が元と同じでよいか見る（消えた見出し: まとめ）",
               [("新しい検索は、前より3倍速くなりました。", "検索の速さ"),
                ("古いログは30日で自動的に消えます。", "ログの保存期間"),
                ("次の四半期は、通知の画面を作り直します", "次の四半期の計画")], 2),
    "article": ("article_summary_orig.txt", "article_summary_final.txt", "article_summary_request.txt",
                "見出しの数が変わった（5 → 4）。節の分け方が元と同じでよいか見る（消えた見出し: まとめ）",
                [("検索は、前よりずっと速くなりました。", "検索の速さ"),
                 ("古いログは、30日たつと自動で消えるようにしました。", "ログの保存期間"),
                 ("来月からは、通知の画面を作り直す予定です", "通知の画面")], 1),
}


def read(name):
    return (REQUESTS / name).read_text(encoding="utf-8")


def run(script, *args):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / script)] + list(args), capture_output=True, text=True, encoding="utf-8",
                          cwd=str(REQUESTS))


class HeadingShapeTest(unittest.TestCase):
    def test_removed_heading_and_shapes(self):
        for name, (old, new, _, count_line, shapes, _risks) in CASES.items():
            with self.subTest(case=name):
                result = yomiyasu_diff.diff(read(old), read(new))
                self.assertIn(count_line, result["structure"])
                self.assertEqual([(item["old"], item["new"]) for item in result["heading_shapes"]], shapes)
                report = yomiyasu_diff.report(result)
                self.assertIn("■ 見出しの形が変わった（3件。", report)
                self.assertIn("消えた見出し: まとめ", report)

    def test_meaning_risks_and_exit_codes_are_the_same_as_v240(self):
        for name, (old, new, _, _, _, risks) in CASES.items():
            with self.subTest(case=name):
                result = yomiyasu_diff.diff(read(old), read(new))
                self.assertEqual(result["meaning_risk_count"], risks)
                without = dict(result, heading_shapes=[], comma_increase=None)
                self.assertEqual(yomiyasu_diff._status_line(result), yomiyasu_diff._status_line(without))
                self.assertEqual(run("yomiyasu_diff.py", old, new).returncode, 0)

    def test_no_heading_change_keeps_the_output(self):
        old = "# 手順\n\n## 設定を見直します。\n\n設定を確かめます。\n"
        new = "# 手順\n\n## 設定を見直します。\n\n設定を確認します。\n"
        result = yomiyasu_diff.diff(old, new)
        self.assertEqual(result["heading_shapes"], [])
        self.assertEqual(result["structure"], [])
        self.assertNotIn("■ 見出しの形が変わった", yomiyasu_diff.report(result))

    def test_short_noun_headings_are_not_shapes(self):
        result = yomiyasu_diff.diff("# 手順\n\n## 保存期間\n\n本文です。\n", "# 手順\n\n## 保存の期間\n\n本文です。\n")
        self.assertEqual(result["heading_shapes"], [])

    def test_removed_heading_and_rewritten_heading_are_told_apart(self):
        """消した見出しと書き換えた見出しを、見出しの文字と節の本文の似かたで分ける（文字が似ていない書き換えも組にする）。"""
        old = ("# 新しい勤怠の仕組み\n\n## はじめに\n\nこの文書では、勤怠の仕組みが変わる点を説明します。\n\n"
               "## 打刻の方法が、来月から変わります。\n\n出社したら入口の端末にカードをかざします。\n\n## 申請の締め切り\n\n"
               "月末の三日前までに申請します。\n")
        new = ("# 新しい勤怠の仕組み\n\n## カードでの出勤登録\n\n出社したら入口の端末にカードをかざします。\n\n## 申請の締め切り\n\n"
               "月末の三日前までに申請します。\n")
        result = yomiyasu_diff.diff(old, new)
        self.assertIn("見出しの数が変わった（4 → 3）。節の分け方が元と同じでよいか見る（消えた見出し: はじめに）", result["structure"])
        self.assertEqual([(item["old"], item["new"]) for item in result["heading_shapes"]],
                         [("打刻の方法が、来月から変わります。", "カードでの出勤登録")])

    def test_level_changed_headings_are_paired(self):
        old = ("# 社内検索の改善\n\n## 新しい検索は、前より3倍速くなりました。\n\n- 応答の速さを測りました\n- 古い索引を作り直しました\n\n"
               "## 料金は変わりません\n\n- 契約の見直しはありません\n\n## まとめ\n\n- 検索が速くなりました\n")
        new = ("# 社内検索の改善\n\n### 検索の速さ\n\n- 応答の速さを測った\n- 古い索引を作り直した\n\n## 料金は変わりません\n\n"
               "- 契約の見直しはありません\n")
        result = yomiyasu_diff.diff(old, new)
        self.assertIn("見出しの数が変わった（4 → 3）。節の分け方が元と同じでよいか見る（消えた見出し: まとめ）", result["structure"])
        self.assertEqual([(item["old"], item["new"]) for item in result["heading_shapes"]],
                         [("新しい検索は、前より3倍速くなりました。", "検索の速さ")])

    def test_heading_to_bold_keeps_the_count_line(self):
        """見出しを太字の行にした組は、消えた見出しにしない（2.4.0 と同じ文）。"""
        result = yomiyasu_diff.diff("# 題\n\n## 手順\n\n本文です。\n", "# 題\n\n**手順**\n\n本文です。\n")
        self.assertIn("見出しの数が変わった（2 → 1）。節の分け方が元と同じでよいか見る", result["structure"])
        self.assertFalse([line for line in result["structure"] if "消えた見出し" in line])


class CheckOrderTest(unittest.TestCase):
    def sections(self, *args):
        process = run("yomiyasu_check.py", "run", "--no-record", *args)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return [line for line in process.stdout.split("\n") if line.startswith("■ ")], process.stdout.split("\n")

    def test_request_material_puts_the_heading_sections_first(self):
        for name, (old, new, request, _, _, _) in CASES.items():
            with self.subTest(case=name):
                heads, lines = self.sections("--source", old, "--final", new, "--material", request)
                self.assertEqual(heads[0], "■ 直した箇所（{}".format(heads[0][len("■ 直した箇所（"):]))
                self.assertTrue(heads[1].startswith("■ 見出しの形が変わった"), heads)
                self.assertTrue(heads[2].startswith("■ 差分の見直し候補（diff、"), heads)
                self.assertIn("見出しの形: ", lines[3])

    def test_length_requests_in_other_forms(self):
        old, new = CASES["slides"][0], CASES["slides"][1]
        with tempfile.TemporaryDirectory() as folder:
            for request in ("見出しは30文字程度に収めてください。", "各ページの題は二十字以内にしてください。"):
                with self.subTest(request=request):
                    path = Path(folder) / "request.txt"
                    path.write_bytes((request + "\n").encode("utf-8"))
                    heads, _ = self.sections("--source", old, "--final", new, "--material", str(path))
                    self.assertTrue(heads[1].startswith("■ 見出しの形が変わった"), heads)
            path = Path(folder) / "request.txt"
            path.write_bytes("数字と漢字の書き方は今のままにしてください。\n".encode("utf-8"))
            heads, _ = self.sections("--source", old, "--final", new, "--material", str(path))
            self.assertTrue(heads[1].startswith("■ 意味が変わる恐れ"), heads)

    def test_without_the_request_the_order_is_the_usual_one(self):
        old, new = CASES["slides"][0], CASES["slides"][1]
        heads, _ = self.sections("--source", old, "--final", new)
        names = [head.split("（")[0] for head in heads]
        self.assertLess(names.index("■ 意味が変わる恐れ"), names.index("■ 見出しの形が変わった"))
        self.assertLess(names.index("■ 差分の見直し候補"), names.index("■ 見出しの形が変わった"))


class FirstLineTest(unittest.TestCase):
    """規則に当たる候補がなく、見出しの形か読点の増加の候補だけがあるとき、check の1行目は節があることを書く（2.4.0 の
    原文にない人や担当と同じ形。diff の結果を差し替えて、1行目の文だけを見る）。"""

    def first_line(self, diff_result):
        import yomiyasu_check
        ctx = yomiyasu_check._Context()
        ctx.mode, ctx.required = "rewrite", ["lint", "diff"]
        ctx.entries["lint"] = {"status": "ran"}
        ctx.entries["diff"] = {"status": "ran"}
        ctx.diff_result = dict({"status": "has_candidates", "candidate_count": 0, "added_actors": []}, **diff_result)
        ctx.lint_result = {"candidate_count": 0}

        class Final(object):
            via, sha256, text_sha256 = "file", "a", "a"

            def token(self):
                return "sha256:a"

        class Source(object):
            sha256, text_sha256 = "b", "b"
        ctx.final, ctx.source, ctx.no_record = Final(), Source(), True
        return yomiyasu_check._decide(ctx, recorded=False)[1]

    def test_heading_shapes_only(self):
        line = self.first_line({"heading_shapes": [{"old_line": 1, "new_line": 1, "old": "a", "new": "b"}] * 2,
                                "comma_increase": None})
        self.assertIn("規則に当たる候補はありませんが、形が変わった見出しが2件あります。", line)

    def test_comma_increase_only(self):
        line = self.first_line({"heading_shapes": [], "comma_increase": {"old_count": 0, "new_count": 5,
                                                                      "old_sentences": 2, "new_sentences": 2,
                                                                      "sentences": []}})
        self.assertIn("規則に当たる候補はありませんが、読点が増えた候補が1件あります。", line)

    def test_nothing_new(self):
        line = self.first_line({"heading_shapes": [], "comma_increase": None})
        self.assertIn("規則に当たる候補はありません。", line)


if __name__ == "__main__":
    unittest.main()
