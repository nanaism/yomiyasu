"""v2.5.0: SKILL.md、references、README の文の決まり（1章、4章、5a、5b、5c、6章、8a）と、6章のコーパスの例文の期待。

6章の例文（tests/corpus/edge_cases/edge_hitei_49〜51、edge_kango_52〜54）は、コーパスのほかの例文と同じく、期待をこの試験に書く。
資料がある例は、資料の文だけで書き直した文を期待にし、check の資料との照合で資料にない数値と名前がないことを確かめる。
資料がない例は、本文を残して書き手に尋ねる（期待の本文は原文と同じ）。
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "yomiyasu" / "SKILL.md"
REFS = ROOT / "references"
EDGE = ROOT / "tests" / "corpus" / "edge_cases"
CHECK = ROOT / "scripts" / "yomiyasu_check.py"
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402


def text(path):
    return path.read_text(encoding="utf-8")


def section(body, heading):
    start = body.index(heading)
    rest = body[start + len(heading):]
    match = re.search(r"\n#{2,3} ", rest)
    return heading + (rest[:match.start()] if match else rest)


class SkillTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = text(SKILL)

    def test_command_section_comes_before_step3(self):
        body = self.skill
        self.assertLess(body.index("### 実行するコマンド"), body.index("### Step 3:"))
        commands = section(body, "### 実行するコマンド")
        for word in ("`python3`、`python`、`py -3` の順に試して", "command not found", "Python was not found",
                     "`yomiyasu-check: not_run reason=no_python`", "${CLAUDE_SKILL_DIR}", "`cd`、`&&`"):
            with self.subTest(word=word):
                self.assertIn(word, commands)

    def test_every_script_call_uses_the_skill_dir_and_refers_to_the_section(self):
        self.assertNotIn("<スキル配置ディレクトリ>", self.skill)
        calls = [line for line in self.skill.split("\n") if re.search(r"scripts/yomiyasu_(?:lint|check)\.py", line)
                 and not line.startswith("allowed-tools:")]
        self.assertTrue(calls)
        for line in calls:
            with self.subTest(line=line[:60]):
                self.assertIn("${CLAUDE_SKILL_DIR}/scripts/", line)
        for heading in ("### Step 2:", "### Step 3:", "### Step 5:"):
            with self.subTest(heading=heading):
                self.assertIn("「実行するコマンド」の節", section(self.skill, heading))
        self.assertNotIn("`python3` がなければ `python` か `py -3` で実行します。", self.skill)

    def test_stdin_only_when_files_cannot_be_written(self):
        step3 = section(self.skill, "### Step 3:")
        self.assertIn("ファイルを書けないとき（ファイルに保存しないよう頼まれたときを含みます）だけ `run --stdin` を使い", step3)
        self.assertIn("ファイルを書けないとき（ファイルに保存しないよう頼まれたときを含みます）だけ、次のように原文と最終稿を"
                      "標準入力から渡します", step3)
        for code in re.findall(r"```bash\n(.*?)```", self.skill, re.S):
            # 置き換える値の <…>、標準入力の区切りの <<<…>>>、heredoc の <<'…' を除いてから、cd、&&、出力のリダイレクトを探す
            plain = re.sub(r"<<<[a-z:]+>>>|<<'[A-Z_]+'|<[^<>\n]*>", "", code)
            with self.subTest(code=code[:40]):
                self.assertNotRegex(plain, r"(?m)^\s*cd\s|&&|2>&1|\s>{1,2}\s*\S")

    def test_chapter1_paragraph(self):
        part = section(self.skill, "### 擬人化の解消")
        for word in ("何を受け取り、何を返し、何を呼ぶか", "知っている", "語る", "門番", "交通整理", "責任を引き受ける",
                     "責務を持つ、依存する、呼び出す、委譲する、返す、受け取る", "オブジェクト指向", "書き手に確かめたい点"):
            with self.subTest(word=word):
                self.assertIn(word, part)

    def test_chapter6_paragraphs_keep_the_rephrase_test(self):
        negation = section(self.skill, "### セルフラベリングと否定対比の整理")
        self.assertIn("「〜を意味するわけではありません」で終わり", negation)
        self.assertIn("言い直しテスト（`references/rephrase-test.md`）の6点は変えません", negation)
        nouns = section(self.skill, "### 内容に合わない大げさな名詞の整理")
        self.assertIn("「分離」「保証」「管理」「対応」「担保」", nouns)
        self.assertIn("言い直しテストの6点は変えません", nouns)
        self.assertIn("語を同じ意味の別の漢語に替えるだけでは済ませません", nouns)

    def test_chapter8a_paragraph_and_step5(self):
        commas = section(self.skill, "### 文長と読点の調整")
        self.assertIn("推敲で文をつないだり言い換えたりして新しく読点を置くときは", commas)
        self.assertIn("外すのは読点だけで、語順と述語は変えません", commas)
        self.assertIn("6字以内の短い目的語の「を、」も候補に出ます", commas)
        self.assertNotIn("（「を、」は候補に出ません）", self.skill)
        self.assertIn("原文と最終稿で地の文の読点の数を比べ", section(self.skill, "### Step 5:"))

    def test_chapter5a_sentence_and_references(self):
        sentence = "依頼で見出しの形（長さ、言い切り、番号、記号）や、まとめの節・ページを指定されているときは、その形と節を保ち、直しません。"
        self.assertIn(sentence.rstrip("。"), section(self.skill, "### 案内用の見出し"))
        self.assertIn("依頼でまとめの節やページを指定されているときは残します。「案内用の見出し」", self.skill)
        slides = text(REFS / "doc-types" / "slides.md")
        self.assertIn("まとめのページを指定されているときは直さず", slides)
        self.assertIn("依頼で見出しの形を指定されていれば直さない", slides)

    def test_chapter4_pointer(self):
        self.assertIn("`references/slop-catalog.md` 10章", section(self.skill, "### Step 2:"))

    def test_skill_md_stays_under_500_lines(self):
        self.assertLess(len(self.skill.split("\n")), 500)


class ReferenceTextTest(unittest.TestCase):
    def test_slop_catalog_chapter10_lists_the_phrases_without_replacements(self):
        catalog = text(REFS / "slop-catalog.md")
        self.assertTrue(catalog.rstrip().split("\n## ")[-1].startswith("10. 2026年に見つかった言い回し"))
        chapter = section(catalog, "## 10. 2026年に見つかった言い回し")
        self.assertIn("| 言い回し | 用例 | 何が足りない文か | 確かめる問い |", chapter)
        for word in ("見立てです", "潜む", "が招く", "欠かせない存在", "という挙動を排除する", "なんよ", "漢語の名詞。",
                     "レベルの", "テーブルの上にある", "ここで効いてくるのが"):
            with self.subTest(word=word):
                self.assertIn(word, chapter)
        self.assertNotIn("言い換えの候補", chapter)
        self.assertNotIn("→", chapter)

    def test_slop_catalog_rows_for_chapters1_and_8(self):
        catalog = text(REFS / "slop-catalog.md")
        self.assertIn("| 技術文のコードに人の知識や役目を持たせる |", section(catalog, "## 8. 成り立たない比喩と、残してよい比喩"))
        nine = section(catalog, "## 9. 間を作るだけの読点")
        self.assertIn("「まず、この画面は、注文を、順番に、表示します」", nine)
        self.assertNotIn("（「を、」は候補に出ない）", nine)

    def test_audience_and_tech(self):
        audience = text(REFS / "audience.md")
        self.assertIn("「初心者向けに」「やさしく」と頼まれたときは", audience)
        self.assertIn("子ども向けの語尾（〜だよ、〜しようね、〜かな？）", audience)
        tech = text(REFS / "domains" / "tech.md")
        self.assertIn("1文に測定値（単位つきの数値）が4つ以上あり", tech)
        self.assertIn("数値は1つも消さず、丸めず", tech)
        self.assertIn("SKILL.md「擬人化の解消」", tech)
        self.assertIn("`references/calques.md` の型1", tech)

    def test_copies_are_the_same(self):
        for name in ("slop-catalog.md", "audience.md", "review-points.md", "domains/tech.md", "doc-types/slides.md"):
            with self.subTest(name=name):
                self.assertEqual(text(REFS / name), text(ROOT / "skills" / "yomiyasu" / "references" / name))


class ReadmeTextTest(unittest.TestCase):
    def test_windows_notes(self):
        self.assertIn("Windows では `py -3 scripts/yomiyasu_lint.py article.md` のように `py -3` で実行してください。",
                      text(ROOT / "README.md"))
        self.assertIn("On Windows, run them with `py -3` instead of `python3`", text(ROOT / "README.en.md"))
        self.assertIn("Windows では `py -3 scripts/yomiyasu_lint.py article.md` のように", text(ROOT / "docs" / "tools.md"))

    def test_permission_paragraph(self):
        readme = text(ROOT / "README.md")
        part = section(readme, "### 承認する人がいない実行で使うとき")
        self.assertIn("`--allowedTools`", part)
        self.assertIn("`permissions.allow`", part)
        self.assertIn("Bash(python3 /path/to/yomiyasu/scripts/yomiyasu_check.py *)", part)


# 6章の例文の期待（ファイル名: (本文, 資料か None, 期待の本文, 資料がないときに尋ねること)）
CHAPTER6 = {
    "edge_hitei_49": ("保留は申請を却下したという意味ではありません。",
                      "保留は、担当者が書類の不足を確かめているあいだの状態で、書類がそろえば審査に戻る。",
                      "保留は、担当者が書類の不足を確かめているあいだの状態です。書類がそろえば審査に戻ります。"
                      "申請を却下したという意味ではありません。", None),
    "edge_hitei_50": ("下書きは公開を取りやめた記事ではありません。",
                      "下書きは、まだ公開の操作をしていない記事で、公開の日時を入れると予約になる。",
                      "下書きはまだ公開の操作をしていない記事です。公開の日時を入れると予約になります。"
                      "公開を取りやめた記事ではありません。", None),
    "edge_hitei_51": ("同期済みはすべての端末で同じ内容になったことを意味するわけではありません。", None,
                      "同期済みはすべての端末で同じ内容になったことを意味するわけではありません。",
                      "同期済みが何の状態を指すか"),
    "edge_kango_52": ("受付と審査を分離します。", "受付は窓口でその日のうちに済ませ、審査は翌日に別の担当者が行う。",
                      "受付は窓口でその日のうちに済ませ、審査は翌日に別の担当者が行います。", None),
    "edge_kango_53": ("障害時の対応は運用チームが管理します。",
                      "障害が起きたら、運用チームが当番表で担当者を決め、30分以内に一次連絡を入れる。",
                      "障害が起きたら、運用チームが当番表で担当者を決め、30分以内に一次連絡を入れます。", None),
    "edge_kango_54": ("通知の到達は保証しません。", None, "通知の到達は保証しません。",
                      "「到達は保証しません」が、何を保証しないという意味か"),
}


class ChapterSixCorpusTest(unittest.TestCase):
    def test_files_hold_the_sentences_and_lint_clean(self):
        for name, (body, *_rest) in CHAPTER6.items():
            with self.subTest(name=name):
                content = text(EDGE / (name + ".md"))
                self.assertEqual(content, "# 境界値検証: {}\n\n{}\n".format(name, body))
                self.assertEqual(yomiyasu_lint.lint_text(content)["candidate_count"], 0)

    def test_rewrites_use_only_the_material(self):
        for name, (body, material, expected, question) in CHAPTER6.items():
            with self.subTest(name=name):
                if material is None:
                    self.assertEqual(expected, body)
                    self.assertTrue(question)
                    continue
                self.assertIsNone(question)
                with tempfile.TemporaryDirectory() as folder:
                    folder = Path(folder)
                    (folder / "src.md").write_bytes((body + "\n").encode("utf-8"))
                    (folder / "final.md").write_bytes((expected + "\n").encode("utf-8"))
                    (folder / "material.txt").write_bytes((material + "\n").encode("utf-8"))
                    process = subprocess.run([sys.executable, "-B", str(CHECK), "run", "--no-record", "--source", "src.md",
                                              "--final", "final.md", "--material", "material.txt"],
                                             capture_output=True, text=True, encoding="utf-8", cwd=str(folder))
                    self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                    self.assertIn("資料にない数値・名前0件", process.stdout.split("\n")[2])


if __name__ == "__main__":
    unittest.main()
