"""3.0.0: 語の一覧の flag-patterns.txt（1行に「名前<TAB>正規表現」）。

正規表現は、手間が行の長さに比例する書き方だけを受け付ける（上限のない繰り返し、取り込む組、後方参照、印、原子団、所有の
繰り返し、\\z などの 3.11 以降の書き方、FutureWarning を出す字の組を断る。繰り返しの幅と選択肢の数の積と、全パターンの
合計にも上限がある）。使えない行は終了コード2で、ファイル名と行番号を出す。ファイルがないときの出力は前と一字も同じ。
文はすべて合成の文。一覧のフォルダは一時フォルダの中にだけ作る。
"""
from pathlib import Path
import hashlib
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v220_c import CHECK, DIFF, LINT, WORD_KEYS, FolderCase, run, write  # noqa: E402
import markdown_visibility  # noqa: E402
import yomiyasu_check  # noqa: E402
import yomiyasu_lint  # noqa: E402
from portable import paced_limit, timing_clock  # noqa: E402

PATTERN_KEYS = WORD_KEYS + ["flag_patterns_lines", "flag_patterns_sha256"]
BRANCH = "branch\t(?<![一-龥々])枝(?![一-龥々])\n"
TEXT = "修正の枝を main に入れます。\n依存先の決済サービスを呼びます。\n枝豆をゆでます。\n"


def project_terms(result):
    return [f for f in result["findings"] if f["rule"] == "project_term"]


class PatternCase(FolderCase):
    def patterns(self, data, folder=None, **files):
        folder = self.words(folder, **files)
        write(folder / "flag-patterns.txt", data)
        return folder

    def doc(self, text=TEXT):
        return write(self.root / "doc.md", text)


class PatternFindingTest(PatternCase):
    def test_pattern_marks_line(self):
        self.patterns(BRANCH)
        found = project_terms(self.lint_json(str(self.doc())))
        self.assertEqual([f["line"] for f in found], [1])
        self.assertEqual(found[0]["severity"], "info")

    def test_message_names_the_file(self):
        self.patterns(BRANCH, flag="依存先\n")
        found = project_terms(self.lint_json(str(self.doc("修正の枝を依存先に送ります。\n枝だけ。\n依存先だけ。\n"))))
        tail = yomiyasu_lint._V220_MESSAGE_TAIL
        self.assertEqual([f["message"] for f in found],
                         ["語の一覧（flag.txt、flag-patterns.txt）の語（依存先、branch）" + tail,
                          "語の一覧（flag-patterns.txt）の語（branch）" + tail,
                          "語の一覧（flag.txt）の語（依存先）" + tail])

    def test_repeated_letters_marked(self):
        """{m,n} で2回以上続く字（ba{2}c の a）があっても、当たる行を必ず当たる字で外さない。"""
        self.patterns("r\tba{2}c\nb\t枝{2,3}葉\nc\tba{1,3}c\n")
        found = project_terms(self.lint_json(str(self.doc("baacを足します。\n枝枝枝葉です。\nbaaacです。\nbcです。\n"))))
        self.assertEqual([(f["line"], f["message"].split("の語（")[1].split("）")[0]) for f in found],
                         [(1, "r、c"), (2, "b"), (3, "c")])
        for pattern, required in (("ba{2}c", (("ba", "ac"),)), ("枝{2,3}葉", (("枝", "枝葉"),)), ("ba{1}c", (("bac",),))):
            with self.subTest(pattern=pattern):
                self.assertEqual(markdown_visibility.check_pattern(pattern)[1], required)

    def test_same_name_in_flag_and_patterns(self):
        """パターンの名前が flag.txt の語と同じ字でも、message はその行で当たったファイルを並べる。"""
        self.patterns("依存先\t依存先(?=に)\n", flag="依存先\n")
        found = project_terms(self.lint_json(str(self.doc("依存先に送ります。\n依存先を見ます。\n"))))
        tail = yomiyasu_lint._V220_MESSAGE_TAIL
        self.assertEqual([f["message"] for f in found],
                         ["語の一覧（flag.txt、flag-patterns.txt）の語（依存先）" + tail,
                          "語の一覧（flag.txt）の語（依存先）" + tail])

    def test_flag_and_pattern_one_finding(self):
        self.patterns(BRANCH, flag="依存先\n")
        found = project_terms(self.lint_json(str(self.doc("修正の枝を依存先に送り、枝も見ます。\n"))))
        self.assertEqual(len(found), 1)

    def test_allow_by_name_and_by_match(self):
        self.patterns(BRANCH + "bg\t背景(?=実行|ジョブ)\n", allow="branch\n")
        found = project_terms(self.lint_json(str(self.doc("修正の枝を見ます。背景実行です。\n枝だけ。\n"))))
        self.assertEqual([(f["line"], f["message"].split("の語（")[1].split("）")[0]) for f in found], [(1, "bg")])
        # 当たった文字列を allow に書いたときは、その行のそのパターンの当たりがすべて許した文字列のときだけ外す
        self.patterns("key\t鍵穴|(?<!公開)鍵\n", allow="鍵\n")
        found = project_terms(self.lint_json(str(self.doc("新しい鍵です。\n鍵と鍵穴です。\n"))))
        self.assertEqual([f["line"] for f in found], [2])

    def test_hidden_places(self):
        self.patterns(BRANCH)
        text = ("```\n枝 = 1\n```\n\n`枝` はコードです。\n\n> 枝を切ります。\n\n彼は「枝」と言いました。\n\n"
                "<div>枝</div>\n\n---\n\n本文の枝です。\n")
        self.assertEqual([f["line"] for f in project_terms(self.lint_json(str(self.doc(text))))], [15])

    def test_doc_type_does_not_skip(self):
        self.patterns(BRANCH)
        for row in markdown_visibility.DOC_TYPES:
            with self.subTest(doc_type=row[0]):
                found = project_terms(self.lint_json("--doc-type", row[0], str(self.doc())))
                self.assertEqual([f["line"] for f in found], [1])

    def test_score_unaffected(self):
        self.patterns(BRANCH)
        result = self.lint_json(str(self.doc("修正の枝です。\n")))
        self.assertEqual(result["rule_penalty_score"], 100)

    def test_patterns_only_folder(self):
        folder = self.patterns(BRANCH)
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual((words["allow"], words["flag"], words["flag_patterns_lines"]), ((), (), 1))
        result = self.lint_json(str(self.doc()))
        self.assertEqual(list(result["context"]["words"])[:7], PATTERN_KEYS)
        self.assertEqual(result["context"]["words"]["flag_sha256"], None)

    def test_bom_crlf_comments(self):
        data = b"\xef\xbb\xbf# comment\r\n\r\n" + BRANCH.replace("\n", "\r\n").encode("utf-8") + "  # 字下げのコメント\r\n".encode("utf-8")
        folder = self.patterns(data)
        words = markdown_visibility.load_words(str(folder))
        self.assertEqual([item[:2] for item in words["flag_patterns"]], [("branch", "(?<![一-龥々])枝(?![一-龥々])")])
        self.assertEqual(words["flag_patterns_sha256"], hashlib.sha256(data).hexdigest())

    def test_context_keys_only_with_file(self):
        folder = self.words(flag="依存先\n")
        before = self.lint_json(str(self.doc()))
        self.assertEqual([key for key in before["context"]["words"] if key != "allow_removed"], WORD_KEYS)
        human = self.lint(str(self.doc())).stdout
        self.assertIn("（allow 0語、flag 1語）。", human)
        write(folder / "flag-patterns.txt", BRANCH)
        after = self.lint_json(str(self.doc()))
        self.assertEqual([key for key in after["context"]["words"] if key != "allow_removed"], PATTERN_KEYS)
        self.assertEqual(after["context"]["words"]["flag_patterns_lines"], 1)
        self.assertIn("（allow 0語、flag 1語、flag-patterns 1行）。", self.lint(str(self.doc())).stdout)


# (flag-patterns.txt の中身, 誤りの行の番号)
INVALID = (
    ("branch 枝\n", 1),                        # タブがない
    ("\t枝\n", 1),                             # 名前が空
    ("x" * 41 + "\t枝\n", 1),                  # 名前が長い
    ("a\t枝(?<=の+)\n", 1),
    ("a\t枝[\n", 1),                           # re の誤り（[ が閉じていない）
    ("# c\na\t枝.*を\n", 2),
    ("a\t枝+\n", 1),
    ("a\t枝{2,}\n", 1),
    ("a\t枝{,3}\n", 1),
    ("a\t(枝)\n", 1),
    ("a\t(?P<n>枝)\n", 1),
    ("a\t枝\\1\n", 1),
    ("a\t(?i)枝\n", 1),
    ("a\t(?>枝)\n", 1),
    ("a\t枝?+\n", 1),
    ("a\t(?<=の|ので)枝\n", 1),               # 長さの変わる後読み
    ("a\t" + "枝" * 201 + "\n", 1),
    ("a\t枝{0,31}\n", 1),
    ("a\t[^。]{0,30}[^、]{0,30}[^！]{0,30}枝\n", 1),
    ("a\t(?:の|は)?\n", 1),                    # 必ず当たる字がない
    ("a\t枝\\z\n", 1),                         # 3.14 からの書き方
    ("a\t[[a]枝\n", 1),                        # FutureWarning を出す字の組
    ("a\t[a--b]枝\n", 1),
    ("a\t[a&&b]枝\n", 1),
    ("a\t" + "(?:枝|葉)" * 11 + "\n", 1),      # 選択肢の数の積が 2,048
    ("".join("p{}\t枝\n".format(n) for n in range(1001)), 1001),
    ("".join("p{}\t枝{{0,1}}葉\n".format(n) for n in range(513)), 513),     # 試す数の合計が 1,026
    # 最短一致の繰り返しを重ねた組（合計 1,500。10万字の行で2秒ほどかかる）
    ("".join("p{}\t{}\n".format(n, p) for n, p in enumerate(
        ["a??" * 10 + "ab", "a??" * 8 + "ab", "a??" * 7 + "ab", "a??" * 6 + "ab", "a??" * 4 + "ab"] + ["ab"] * 12)), 2),
)


class InvalidPatternTest(PatternCase):
    def test_invalid_lines_exit_2(self):
        doc = self.doc()
        for data, line in INVALID:
            with self.subTest(data=data[:40]):
                folder = self.patterns(data)
                path = str(folder / "flag-patterns.txt")
                for command in ([LINT, str(doc)], [DIFF, str(doc), str(doc)],
                                [CHECK, "run", "--source", str(doc), "--final", str(doc), "--no-record"]):
                    process = run(command, self.root, self.env)
                    self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                    self.assertIn("Error opening file {}: ".format(path), process.stderr)
                    self.assertIn("{}行目".format(line), process.stderr)

    def test_accepted_shapes(self):
        for pattern in (r"(?<=の)枝(?![一-龥々])|(?<![一-龥々])枝(?=[のでにをはが]|ごと)",
                        r"背景(?=で(?:実行|回|走|待)|実行|ジョブ|タスク)",
                        r"(?<!公開)(?<!秘密)(?<!署名)(?<!暗号)(?<!SSH)鍵(?![括盤穴])",
                        r"偽実装を[^。、]{0,6}通[さしすせ]", r"(?:main|ブランチ) ?に入れ", r"枝\Z", r"\b(?:PR|issue) ?の題\b",
                        r"枝{2}", r"枝??葉", "(?:枝|葉)" * 10 + "x"):
            with self.subTest(pattern=pattern):
                compiled, required, cost = markdown_visibility.check_pattern(pattern)
                self.assertEqual(compiled.pattern, pattern)
                self.assertTrue(all(required))
                self.assertLessEqual(cost, markdown_visibility.PATTERN_MAX_COST)

    def test_same_on_39_and_314(self):
        """断る書き方は、どの版の Python でも断る（re の誤りの文は版で変わるので、断ることだけを比べる。
        試験一式は 3.9 と 3.14 の両方で流す）。"""
        for data, _ in INVALID[3:25]:
            pattern = data.rstrip("\n").split("\n")[-1].split("\t", 1)[1]
            with self.subTest(pattern=pattern):
                with self.assertRaises(markdown_visibility._PatternError):
                    markdown_visibility.check_pattern(pattern)


class CheckRecordTest(PatternCase):
    def setUp(self):
        super().setUp()
        self.state = self.root / ".yomiyasu"
        self.a = write(self.root / "a.md", "修正の枝を、今日中に main に入れます。\n")
        self.b = write(self.root / "b.md", "修正の枝を、今日中に main にマージします。\n")

    def check(self, *args):
        return run([CHECK] + list(args), self.root, self.env)

    def test_check_record_and_replay(self):
        folder = self.patterns(BRANCH)
        process = self.check("run", "--source", str(self.a), "--final", str(self.b), "--json")
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        result = json.loads(process.stdout)
        expected = markdown_visibility.words_context(markdown_visibility.load_words(str(folder)))
        self.assertEqual(list(expected), PATTERN_KEYS)
        self.assertEqual(result["context"]["words"], expected)
        self.assertEqual(result["diff"]["context"]["words"], expected)
        record = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["options"]["words"], expected)
        self.assertIn("branch", [mark["word"] for mark in result["kept_marks"]])
        process = self.check("verify", "--final", str(self.b), "--replay")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("replay=ok", process.stdout)
        # 一覧を書き換えたら、作り直したレポートが合わない
        write(folder / "flag-patterns.txt", BRANCH + "main\tmain ?に\n")
        process = self.check("verify", "--final", str(self.b), "--replay")
        self.assertEqual(process.returncode, 1, process.stdout)
        self.assertIn("not_reproducible", process.stdout)

    def test_kept_mark_section_names_patterns(self):
        self.patterns(BRANCH)
        process = self.check("run", "--source", str(self.a), "--final", str(self.b), "--no-record")
        self.assertIn("語の一覧（flag.txt）の語" + yomiyasu_check._KEPT_MARK_PATTERNS_NOTE + "は、", process.stdout)
        self.assertIn("branch", process.stdout)
        self.assertIn("flag-patterns 1行", process.stdout)

    def test_kept_mark_section_without_patterns_unchanged(self):
        self.words(flag="枝\n")
        process = self.check("run", "--source", str(self.a), "--final", str(self.b), "--no-record")
        self.assertIn("語の一覧（flag.txt）の語は、定着した言い方でも残さない。", process.stdout)
        self.assertNotIn(yomiyasu_check._KEPT_MARK_PATTERNS_NOTE, process.stdout)

    def test_record_shape_accepts_five_and_seven_keys(self):
        five = {"path": "/x", "allow_lines": 0, "flag_lines": 1, "allow_sha256": None, "flag_sha256": "0" * 64}
        seven = dict(five, flag_patterns_lines=2, flag_patterns_sha256="1" * 64)
        self.assertTrue(yomiyasu_check._words_shape(five))
        self.assertTrue(yomiyasu_check._words_shape(seven))
        self.assertFalse(yomiyasu_check._words_shape(dict(five, flag_patterns_lines=2)))
        self.assertFalse(yomiyasu_check._words_shape(dict(seven, flag_patterns_sha256=None)))
        patterns_only = dict(seven, flag_sha256=None)
        self.assertTrue(yomiyasu_check._words_shape(patterns_only))


class LongLineTest(unittest.TestCase):
    def test_long_lines_worst_patterns_quick(self):
        """受け付ける上限いっぱいの最悪の形のパターンと、10万字の行で、2.0秒未満。"""
        line = "a" * 99999 + "x\n"
        sets = (["a" + "(?:a|a)" * 10 + "x"],
                ["a(?:a|a)x"] * 512,
                ["a" + "(?:a|a)" * 3 + "x"] * 128,
                ["ax"] * 1000,
                ["a??" * 10 + "ab"],
                ["a??" * 9 + "ab", "a??" * 8 + "ab", "a??" * 7 + "ab", "a??" * 6 + "ab"] + ["ab"] * 64)
        for patterns in sets:
            rows = []
            for number, pattern in enumerate(patterns):
                compiled, required, cost = markdown_visibility.check_pattern(pattern)
                rows.append(("p{}".format(number), pattern, compiled, required))
            self.assertLessEqual(sum(markdown_visibility.check_pattern(p)[2] for p in patterns),
                                 markdown_visibility.PATTERNS_MAX_COST)
            self.assertLessEqual(len(patterns), markdown_visibility.PATTERNS_MAX)
            words = {"path": "/x", "allow": (), "flag": (), "allow_lines": 0, "flag_lines": 0, "allow_sha256": None,
                     "flag_sha256": None, "flag_patterns": tuple(rows), "flag_patterns_lines": len(rows),
                     "flag_patterns_sha256": "0" * 64}
            with self.subTest(count=len(patterns), first=patterns[0][:12]):
                clock = timing_clock()
                started = clock()
                yomiyasu_lint.lint_text(line if patterns[0].endswith("x") else "a" * 99999 + "b\n", words=words)
                elapsed = clock() - started
                limit, detail = paced_limit(2.0, elapsed)
                self.assertLess(elapsed, limit, detail)


if __name__ == "__main__":
    unittest.main()
