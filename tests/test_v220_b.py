"""v2.2.0（担当 B）: 台詞の句点（dialogue_period）、読み物の一人称と数字（narrative_density）、文書の種類 script。

文はすべてこのファイルで作った合成の文。
"""
from pathlib import Path
from unittest import mock
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "skills" / "yomiyasu"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402
from test_v200_doc_type import DocTypeCase  # noqa: E402

SCRIPT_LINES = (
    ("健太", "バス、まだ来ないね"),
    ("沙織", "今日は遅れてるみたい"),
    ("健太", "傘、持ってくればよかった"),
    ("沙織", "私の傘に入りなよ"),
    ("健太", "いいの。ありがとう"),
    ("沙織", "その代わり、今度ご飯おごってね"),
    ("健太", "わかった。何がいい"),
    ("沙織", "ラーメン。駅前の店"),
    ("健太", "あそこ、いつも並んでるよ"),
    ("沙織", "並ぶのも楽しいでしょ"),
)


def script(periods, lines=SCRIPT_LINES, form="{}「{}{}」"):
    """台詞の頭から periods 個の最後に「。」を打った台本。"""
    body = "\n".join(form.format(name, words, "。" if index < periods else "")
                     for index, (name, words) in enumerate(lines))
    return "# 第1話「雨の停留所」\n\nシーン1　夜のバス停。雨が降っている。\n\n" + body + "\n\n（バスのライトが近づく。）\n"


def rules(text, doc_type=None):
    return [finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type=doc_type)["findings"]]


def found(text, rule, doc_type):
    return [finding for finding in yomiyasu_lint.lint_text(text, doc_type=doc_type)["findings"] if finding["rule"] == rule]


# 数字と箇条書きが多く、一人称のない体験記（地の文が1,000字を超える）
AI_ESSAY = ("# 家庭菜園の半年\n\n"
            "会社員が、ベランダの家庭菜園を始めて半年がたった。ここでは、準備から収穫までの流れを振り返る。\n\n"
            "## 準備したもの\n\n- プランター3個（合計2,400円）\n- 培養土25リットル（1,280円）\n- ミニトマトの苗3株\n"
            "- バジルの苗2株\n\n## 半年の流れ\n\n"
            + "".join("{}週目は、水やりを1日{}回にし、収穫は{}個、肥料は{}グラムだった。".format(week, week % 3 + 1, week * 3, week * 5)
                      for week in range(1, 27))
            + "\n\n## 振り返り\n\n"
            "半年の収穫は合計で約1,050個になり、かかった費用は約6,000円だった。次の春は、苗を5株に増やす予定である。\n")
# 一人称で語る、数字のない読み物（地の文が1,000字を超える）
HUMAN_ESSAY = ("# ベランダの朝\n\n"
               + "".join("私は朝になると、まずベランダに出て、{}の葉を一枚ずつ眺める。昨日より少しだけ伸びた気がして、"
                         "私は一人で笑ってしまう。".format(name)
                         for name in ("トマト", "バジル", "シソ", "ネギ", "パセリ", "ミント", "ローズマリー", "レタス",
                                      "ナス", "ピーマン", "オクラ", "キュウリ", "ゴーヤ", "イチゴ", "ルッコラ", "ミツバ",
                                      "セロリ", "パクチー"))
               + "\n")


class DialoguePeriodTest(unittest.TestCase):
    def test_flags_scripts_whose_lines_end_with_a_period(self):
        text = script(10)
        result = yomiyasu_lint.lint_text(text, doc_type="script")
        hits = [finding for finding in result["findings"] if finding["rule"] == "dialogue_period"]
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit["severity"], "info")
        # 最初の台詞の行（見出しの「」とト書きは台詞に数えない）
        self.assertEqual(hit["line"], 5)
        self.assertEqual(hit["snippet"], "健太「バス、まだ来ないね。」")
        self.assertEqual(hit["message"], "台詞の最後の句点（台詞10個のうち10個、100%が「。」で終わる）の候補です。"
                                         "文脈を見て、誰が何をどうするかを書き直すか確かめてください。")
        self.assertEqual(sorted(hit), ["line", "message", "rule", "severity", "snippet"])
        # 点数と warn の件数は変えない
        self.assertEqual(result["rule_penalty_score"],
                         yomiyasu_lint.lint_text(script(0), doc_type="script")["rule_penalty_score"])

    def test_thresholds(self):
        self.assertEqual((yomiyasu_lint.DIALOGUE_MIN, yomiyasu_lint.DIALOGUE_RATIO), (10, 0.5))
        # 10個のうち5個（50%）は出し、4個（40%）と0個は出さない
        self.assertEqual(len(found(script(5), "dialogue_period", "script")), 1)
        self.assertIn("台詞10個のうち5個、50%", found(script(5), "dialogue_period", "script")[0]["message"])
        self.assertEqual(found(script(4), "dialogue_period", "script"), [])
        self.assertEqual(found(script(0), "dialogue_period", "script"), [])
        # 台詞が9個なら、全部が「。」で終わっても出さない
        self.assertEqual(found(script(9, SCRIPT_LINES[:9]), "dialogue_period", "script"), [])

    def test_only_the_last_character_counts(self):
        # 台詞の中の文と文の間の「。」は数えない（「いいの。ありがとう」は句点で終わらない）
        dialogue = yomiyasu_lint._dialogue_lines(markdown_visibility.analyze_markdown(script(0)))
        self.assertEqual(len(dialogue), 10)
        self.assertFalse(any(content.endswith("。") for _, content in dialogue))
        # 「！」「？」で終わる台詞も句点で終わらない
        lines = tuple((name, words + "！") for name, words in SCRIPT_LINES)
        self.assertEqual(found(script(0, lines), "dialogue_period", "script"), [])

    def test_speaker_colon_lines(self):
        for form in ("{}：{}{}", "{}: {}{}", "- {}：{}{}"):
            with self.subTest(form=form):
                self.assertEqual(len(found(script(10, form=form), "dialogue_period", "script")), 1)
                self.assertEqual(found(script(4, form=form), "dialogue_period", "script"), [])
        # 台詞のあとのト書き（（笑う））は外して最後の字を見る。音の指示（SE、M）は台詞に数えない
        text = script(9, form="{}：{}{}") + "健太：じゃあ、行こう。（立ち上がる）\nSE：雨の音。\nM：テーマ曲。\n"
        dialogue = yomiyasu_lint._dialogue_lines(markdown_visibility.analyze_markdown(text))
        self.assertEqual(len(dialogue), 11)
        self.assertEqual(dialogue[-1][1], "じゃあ、行こう。")
        self.assertIn("台詞11個のうち10個", found(text, "dialogue_period", "script")[0]["message"])

    def test_lines_that_are_not_dialogue(self):
        quote = "\n".join("> " + line for line in script(10).split("\n")[4:14])
        code = "```\n" + "\n".join(script(10).split("\n")[4:14]) + "\n```"
        table = "| 名前 | 台詞 |\n|---|---|\n" + "\n".join("| {} | 「{}。」 |".format(n, w) for n, w in SCRIPT_LINES)
        headings = "\n\n".join("## {}「{}。」".format(n, w) for n, w in SCRIPT_LINES)
        inline = "\n".join("`{}「{}。」`".format(n, w) for n, w in SCRIPT_LINES)
        for text in (quote, code, table, headings, inline):
            with self.subTest(text=text[:20]):
                self.assertEqual(found(text + "\n", "dialogue_period", "script"), [])
        # 入れ子の『』は外の「」の中身として1つに数える
        nested = "\n".join("{}「『{}』と書いてあった。」".format(n, w) for n, w in SCRIPT_LINES)
        self.assertIn("台詞10個のうち10個", found(nested + "\n", "dialogue_period", "script")[0]["message"])

    def test_only_script(self):
        text = script(10)
        self.assertNotIn("dialogue_period", rules(text))
        for row in markdown_visibility.DOC_TYPES:
            with self.subTest(doc_type=row[0]):
                self.assertEqual("dialogue_period" in rules(text, row[0]), row[0] == "script")

    def test_detection_runs_only_for_script(self):
        with mock.patch.object(yomiyasu_lint, "_dialogue_lines", side_effect=AssertionError("数えない")):
            for value in (None, "essay", "promo"):
                yomiyasu_lint.lint_text(script(10), doc_type=value)


class NarrativeDensityTest(unittest.TestCase):
    def test_flags_ai_like_essays(self):
        chars, first_person, numbers, bullets, _ = yomiyasu_lint._narrative_counts(
            markdown_visibility.analyze_markdown(AI_ESSAY))
        self.assertGreaterEqual(chars, 1000)
        self.assertEqual((first_person, bullets), (0, 4))
        hits = found(AI_ESSAY, "narrative_density", "essay")
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit["severity"], "info")
        self.assertEqual(hit["line"], 3)
        self.assertEqual(hit["snippet"], AI_ESSAY.split("\n")[2])
        density = (numbers + bullets) * 1000 / chars
        self.assertEqual(hit["message"], "読み物の一人称と数字（地の文{:,}字、一人称は千字あたり0.0、数字と箇条書きは千字あたり{:.1f}）"
                                         "の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。"
                                         "一人称と体験は足さず、数字も消しません。".format(chars, density))

    def test_keeps_first_person_essays(self):
        chars, first_person, numbers, bullets, _ = yomiyasu_lint._narrative_counts(
            markdown_visibility.analyze_markdown(HUMAN_ESSAY))
        self.assertGreaterEqual(chars, 1000)
        self.assertEqual((first_person, numbers, bullets), (36, 0, 0))
        self.assertEqual(found(HUMAN_ESSAY, "narrative_density", "essay"), [])
        # 数字が多くても、一人称が千字あたり1.0以上なら出さない
        text = AI_ESSAY.replace("会社員が、", "私は、").replace("次の春は、", "私は次の春に、")
        self.assertEqual(found(text, "narrative_density", "essay"), [])

    def test_thresholds(self):
        self.assertEqual((yomiyasu_lint.FIRST_PERSON_MAX, yomiyasu_lint.DENSITY_MIN, yomiyasu_lint.NARRATIVE_MIN_CHARS),
                         (1.0, 8, 1000))
        # 地の文が1,000字に満たない文書は数えない
        short = AI_ESSAY[:AI_ESSAY.index("10週目")] + "\n"
        self.assertLess(yomiyasu_lint._narrative_counts(markdown_visibility.analyze_markdown(short))[0], 1000)
        self.assertEqual(found(short, "narrative_density", "essay"), [])
        # 数字と箇条書きが千字あたり8に満たなければ出さない
        plain = HUMAN_ESSAY.replace("私は", "人は")
        self.assertEqual(yomiyasu_lint._narrative_counts(markdown_visibility.analyze_markdown(plain))[1], 0)
        self.assertEqual(found(plain, "narrative_density", "essay"), [])

    def test_counting(self):
        def counts(text):
            return yomiyasu_lint._narrative_counts(markdown_visibility.analyze_markdown(text))[1:4]
        # 複数の形は1回、熟語の「私」と動詞の「わたし」は数えない
        self.assertEqual(counts("私たちは私立の学校に通い、資料を手わたしで受けわたしました。\n")[0], 1)
        self.assertEqual(counts("わたしは、ぼくらと、おれたちと、僕と、俺と、自分と、筆者と、わたくしどもで行った。\n")[0], 8)
        self.assertEqual(counts("お礼の手紙を、おれいに渡しました。枝がおれた。\n")[0], 0)
        # カギ括弧の中、見出し、表、引用、コードの一人称と数字は数えない
        self.assertEqual(counts("「私は3回行った」と彼は言った。\n\n# 私の3日間\n\n| 私 | 3 |\n|---|---|\n\n> 私は3回\n\n"
                                "```\n私 3\n```\n"), (0, 0, 0))
        # 数字は続きを1つ（1,000 と 1.5 は1つ）。全角も数える。英字に続く識別子（v2.1.3、snake_case_2）は数えない
        self.assertEqual(counts("1,000円と1.5倍と３個と2026年10月、v2.1.3 と snake_case_2 と H2。\n")[1], 5)
        self.assertEqual(counts("- 一つ目\n- 二つ目\n1. 三つ目\n\n本文。\n")[2], 3)

    def test_only_essay(self):
        self.assertNotIn("narrative_density", rules(AI_ESSAY))
        for row in markdown_visibility.DOC_TYPES:
            with self.subTest(doc_type=row[0]):
                self.assertEqual("narrative_density" in rules(AI_ESSAY, row[0]), row[0] == "essay")

    def test_detection_runs_only_for_essay(self):
        with mock.patch.object(yomiyasu_lint, "_narrative_counts", side_effect=AssertionError("数えない")):
            for value in (None, "manual", "script"):
                yomiyasu_lint.lint_text(AI_ESSAY, doc_type=value)

    def test_not_scored(self):
        with_rule = yomiyasu_lint.lint_text(AI_ESSAY, doc_type="essay")
        with mock.patch.object(yomiyasu_lint, "_v220_document_findings", lambda analysis, doc_type: []):
            without = yomiyasu_lint.lint_text(AI_ESSAY, doc_type="essay")
        self.assertEqual(with_rule["rule_penalty_score"], without["rule_penalty_score"])
        self.assertEqual(with_rule["counts"]["info"], without["counts"]["info"] + 1)
        self.assertEqual(with_rule["counts"]["warn"], without["counts"]["warn"])


class TableTest(unittest.TestCase):
    def test_script_row(self):
        self.assertEqual(markdown_visibility.DOC_TYPES[-1], ("script", "台詞・脚本", ("essay.md",)))
        self.assertEqual(len(markdown_visibility.DOC_TYPES), 13)
        self.assertEqual(markdown_visibility.normalize_doc_type(" ＳＣＲＩＰＴ "), "script")
        self.assertEqual(markdown_visibility.context_label("script", None), "文書の種類: 台詞・脚本（script）、読者: 指定なし。")

    def test_skip_and_only_tables(self):
        skip = yomiyasu_lint.DOC_TYPE_SKIP_RULES
        self.assertEqual(list(skip)[-1], "script")
        self.assertEqual(skip["script"], ("bare_verb_chain", "fragment_run", "metaphor_label", "sentence_end_repetition"))
        self.assertEqual(skip["essay"], ("bare_verb_chain", "metaphor_label"))
        self.assertEqual(skip["promo"], ("bare_verb_chain", "emoji_prohibited", "fragment_run", "metaphor_label"))
        self.assertEqual(skip["slides"], ("bare_verb_chain", "bold_label_list", "cleft_list_ending", "count_declaration",
                                          "excess_list", "short_summary_heading"))
        only = yomiyasu_lint.DOC_TYPE_ONLY_RULES
        self.assertEqual(only["dialogue_period"], ("script",))
        self.assertEqual(only["narrative_density"], ("essay",))
        self.assertNotIn("script", only["pause_comma"])
        self.assertEqual(len(only["pause_comma"]), 11)

    def test_script_skips_fragment_and_ending_rules(self):
        text = "安い。うまい。早い。\n\n記録を確認します。手順を確認します。結果を確認します。\n"
        self.assertEqual(sorted(set(rules(text))), ["fragment_run", "sentence_end_repetition"])
        result = yomiyasu_lint.lint_text(text, doc_type="script")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["context"]["skipped_by_doc_type"],
                         {"bare_verb_chain": 0, "fragment_run": 1, "metaphor_label": 0, "sentence_end_repetition": 1})

    def test_no_emission_without_a_type(self):
        for text in (script(10), AI_ESSAY):
            result = yomiyasu_lint.lint_text(text)
            self.assertFalse({"dialogue_period", "narrative_density"} & set(f["rule"] for f in result["findings"]))
            self.assertEqual(result["context"]["skipped_by_doc_type"], {})

    def test_script_reference_file(self):
        for base in (ROOT / "references", PACKAGE / "references"):
            lines = (base / "doc-types" / "script.md").read_text(encoding="utf-8").split("\n")
            self.assertEqual(lines[0], "# 台詞・脚本（script）")
            self.assertEqual(lines[2], "あわせて読む: domains/essay.md")
            self.assertEqual(lines[3], "lint で外す規則: bare_verb_chain、fragment_run、metaphor_label、sentence_end_repetition")
            self.assertEqual([line for line in lines if line.startswith("## ")],
                             ["## 1. 普通な書き方（直さない）", "## 2. それでも直すもの", "## 3. 長さと省略", "## 4. 例（合成）"])
        self.assertEqual((ROOT / "references/doc-types/script.md").read_bytes(),
                         (PACKAGE / "references/doc-types/script.md").read_bytes())

    def test_skill_md_and_readme(self):
        skill = (PACKAGE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("文書の種類は下の表の13種類です。", skill)
        self.assertIn("   | script（台詞・脚本） | ", skill)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(readme.count("13種類"), 2)
        self.assertNotIn("12種類", readme)
        self.assertIn("thirteen document types", (ROOT / "README.en.md").read_text(encoding="utf-8"))

    def test_lint_help(self):
        help_text = yomiyasu_lint._build_parser().format_help()
        self.assertIn("  script    bare_verb_chain、fragment_run、metaphor_label、sentence_end_repetition\n", help_text)
        self.assertIn("種類を指定したときだけ当てる規則: pause_comma（promo、script を除く11種類。", help_text)
        self.assertIn("種類を指定したときだけ当てる規則: dialogue_period（script だけ。種類を指定しないときは出しません）", help_text)
        self.assertIn("種類を指定したときだけ当てる規則: narrative_density（essay だけ。種類を指定しないときは出しません）", help_text)


class CommandLineTest(DocTypeCase):
    def test_lint_accepts_script(self):
        path = self.write("script.md", script(10))
        code, out, err = self.lint("--doc-type", "script", path)
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        self.assertEqual(lines[3], "文書の種類: 台詞・脚本（script）、読者: 指定なし。種類に合わせて外した候補 0件（bare_verb_chain 0件、"
                                   "fragment_run 0件、metaphor_label 0件、sentence_end_repetition 0件）。")
        self.assertIn("L5 [INFO] dialogue_period: 台詞の最後の句点（台詞10個のうち10個、100%", out)
        # info なので --strict の判定に入らない
        code, out, err = self.lint("--strict", "--doc-type", "script", path)
        self.assertEqual((code, err), (0, ""))
        code, out, err = self.lint("--json", "--doc-type", "SCRIPT", path)
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["context"]["doc_type"], "script")
        self.assertEqual([f["rule"] for f in result["findings"]].count("dialogue_period"), 1)
        # 種類なしでは出さない
        code, out, err = self.lint(path)
        self.assertNotIn("dialogue_period", out)

    def test_diff_accepts_script(self):
        before = self.write("before.md", script(10))
        after = self.write("after.md", script(0))
        code, out, err = self.diff("--json", "--doc-type", "script", before, after)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["context"], {"doc_type": "script", "reader": None})
        code, out, err = self.diff("--doc-type", "script", before, after)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("文書の種類: 台詞・脚本（script）", out)

    def test_check_run_accepts_script(self):
        before = self.write("before.md", script(10))
        after = self.write("after.md", script(10))
        code, out, err = self.check("run", "--source", before, "--final", after, "--doc-type", "script")
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        path, record = self.record(lines)
        self.assertEqual(record["options"]["doc_type"], "script")
        lint = json.loads((path.parent / "attempt-1.lint.json").read_text(encoding="utf-8"))
        self.assertEqual(lint["context"]["doc_type"], "script")
        self.assertEqual([f["rule"] for f in lint["findings"]].count("dialogue_period"), 1)
        diff = json.loads((path.parent / "attempt-1.diff.json").read_text(encoding="utf-8"))
        self.assertEqual(diff["context"], {"doc_type": "script", "reader": None})
        self.assertIn("doc_type=script", next(line for line in lines if line.startswith("yomiyasu-check: ")))

    def test_bad_value_lists_script(self):
        path = self.write("a.md", "記録を確認した。\n")
        code, out, err = self.lint("--doc-type", "drama", path)
        self.assertEqual(code, 2)
        self.assertIn("paper（論文・研究レポート）、script（台詞・脚本）です。", err)


if __name__ == "__main__":
    unittest.main()
