"""3.0.0 の仕上げ: SKILL.md と references の食い違いの直し。

- 太字とラベル: ラベルを外すだけにするのは、ラベルの語がすべて説明の文にあるときだけ。ない語は文へ入れて1文にする。
  働きが変わるならラベルとコロンを残す決まり（意味の守り）は保つ。
- 「なく」のあとの読点: 「文長と読点の調整」の決まり（間を作るだけなら外す）に、残す例と直した文の例をそろえる。
  2文の否定対比を1文にまとめるときも読点を足さない。
- 直訳語の型を5つにし（英語の術語に当てた2字以上の名詞）、Step 1 で flag-patterns.txt も読む。
- references が指す SKILL.md の節の名前は、今の SKILL.md の見出しにある。
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "yomiyasu" / "SKILL.md"
REFS = ROOT / "references"
LINT = ROOT / "scripts" / "yomiyasu_lint.py"


def text(path):
    return path.read_text(encoding="utf-8")


def section(body, heading):
    start = body.index(heading)
    rest = body[start + len(heading):]
    match = re.search(r"\n#{2,3} ", rest)
    return heading + (rest[:match.start()] if match else rest)


def ref_files():
    return sorted(path for path in REFS.rglob("*.md"))


class LabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels = section(text(SKILL), "### 太字とラベル")

    def test_label_is_removed_alone_only_when_every_word_is_in_the_sentence(self):
        self.assertIn("ラベルを外すだけにして語を足さないのは、ラベルの語がすべて説明の文にあるときだけです。", self.labels)
        self.assertIn("説明の文にないラベルの語は落とさずに文へ入れ、1文にします", self.labels)
        self.assertNotIn("説明の文がすでにラベルと同じ対象と条件を述べているなら", self.labels)

    def test_meaning_guard_is_kept(self):
        for words in ("2つを1つの条件にまとめず、ラベルとコロンを残して太字だけを外します",
                      "ラベルを文に入れたら、入れる前とラベルの働きが同じかを確かめます",
                      "入れたあとで、条件や否定、「〜し、」で続けた節の掛かる範囲が変わったら、ラベルとコロンの形に戻します",
                      "番号と項目の数と順は保ちます"):
            with self.subTest(words=words):
                self.assertIn(words, self.labels)
        # 意味の守りは、ラベルの語を入れる決まりのあとに置く（入れたあとで確かめる）
        self.assertLess(self.labels.index("説明の文にないラベルの語は落とさずに文へ入れ"), self.labels.index("入れたあとで、"))

    def test_example_has_a_label_word_missing_from_the_sentence_and_keeps_it(self):
        match = re.search(r"`- \*\*(?P<label>[^*]+)\*\*：(?P<body>[^`]+)` → `- (?P<merged>[^`]+)`", self.labels)
        self.assertIsNotNone(match)
        words = re.split(r"[・のと]", match.group("label"))
        self.assertEqual(words, ["鍵", "名札", "返却"])
        missing = [word for word in words if word not in match.group("body")]
        self.assertEqual(missing, ["鍵", "名札"])
        for word in words:
            with self.subTest(word=word):
                self.assertIn(word, match.group("merged"))
        # 例は 1文にまとめた形で、読点を足していない
        self.assertNotIn("、", match.group("merged"))


class NakuCommaTest(unittest.TestCase):
    """「AではなくB」の「なく」のあとに読点を置いた形を、残す例や直した文として見せない。"""

    def test_skill_shows_no_comma_after_naku(self):
        skill = text(SKILL)
        self.assertIn("「AではなくB」の「なく」のあと", section(skill, "### 文長と読点の調整"))
        self.assertNotIn("ではなく、", skill)
        negation = section(skill, "### セルフラベリングと否定対比の整理")
        self.assertIn("「原因はキャッシュではなくDNSの設定でした」", negation)
        self.assertIn("「弱みではなく視点の違いでもある」は一つの文のまま残します", negation)

    def test_merge_does_not_add_a_comma(self):
        merge = section(text(SKILL), "### 2文の否定対比と「もちろん、」")
        self.assertIn("否定を残して1文にまとめ、「なく」のあとに読点を足しません。", merge)

    def test_rephrase_test_examples(self):
        body = text(REFS / "rephrase-test.md")
        self.assertNotIn("ではなく、", section(body, "### 残す例（合成）"))
        fixed = section(body, "### 直す例（合成）")
        rows = [line.split(" | ") for line in fixed.split("\n") if line.startswith("| ") and not line.startswith("| 原文")
                and not line.startswith("|---")]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(row=row[0]):
                self.assertNotIn("ではなく、", row[1])
        self.assertIn("| 必要だったのは新しい道具ではなく使い方をそろえることだった。 |", fixed)
        self.assertIn("「なく」のあとに読点を足さない", fixed)
        # 原文を残す誤った直しの例も、残す原文に読点を置かない
        self.assertNotIn("ではなく、", section(body, "### 直し方を誤った例（合成）"))

    def test_slop_catalog_row(self):
        row = [line for line in text(REFS / "slop-catalog.md").split("\n") if line.startswith("| *it is not X, it is Y* |")]
        self.assertEqual(len(row), 1)
        cells = row[0].split(" | ")
        # 2列目は AI の型（原文）なので読点つきのまま。3列目の残す形と直した形は読点なし
        self.assertIn("「Xではなく、Yです」", cells[1])
        self.assertNotIn("ではなく、", cells[2])
        for words in ("「XではなくYでもある」", "「XではなくYです」", "「XではなくYだ」の1文にまとめ、「なく」のあとに読点を足さない"):
            with self.subTest(words=words):
                self.assertIn(words, cells[2])

    def test_gemini_syntax_principle5_outputs(self):
        principle = section(text(REFS / "gemini-syntax.md"), "### 原則 5:")
        rows = [line.split(" | ") for line in principle.split("\n") if line.startswith("| ") and not line.startswith("| 確認する例")]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(row=row[0]):
                self.assertNotIn("ではなく、", row[1])
                self.assertNotIn("ではなく、", row[2])


class CalqueTypesTest(unittest.TestCase):
    def test_five_types(self):
        calques = section(text(SKILL), "### 直訳語、漢語の詰まり、連用形名詞")
        self.assertIn("英語の短い術語に当てた漢字1字の名詞、英語の術語に当てた2字以上の名詞）", calques)
        self.assertIn("（術語に当てた名詞を定着した呼び名に替えるのは差し替えに入りません）", calques)
        # lint と calques.md の型5と同じ言い方
        self.assertIn("英語の術語に当てた2字以上の名詞", text(LINT))
        self.assertIn("- 型5: 英語の術語に当てた2字以上の名詞", text(REFS / "calques.md"))

    def test_step1_reads_flag_patterns(self):
        step1 = section(text(SKILL), "### Step 1:")
        self.assertIn("`flag-patterns.txt`（見直す語の名前と正規表現。flag.txt と同じ扱い）を読みます", step1)


def skill_pointers(body):
    """本文の SKILL.md「…」の名前（中の「」を含む）を返す。"""
    names = []
    for match in re.finditer(r"SKILL\.md「", body):
        depth, start = 1, match.end()
        for index in range(start, len(body)):
            if body[index] == "「":
                depth += 1
            elif body[index] == "」":
                depth -= 1
                if depth == 0:
                    names.append(body[start:index])
                    break
    return names


class PointerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.headings = [line.lstrip("#").strip() for line in text(SKILL).split("\n") if line.startswith("#")]

    def test_every_named_section_is_a_current_heading(self):
        for path in ref_files():
            for name in skill_pointers(text(path)):
                with self.subTest(file=str(path.relative_to(REFS)), name=name):
                    self.assertTrue(any(name in heading for heading in self.headings))

    def test_no_pointer_to_removed_steps_and_items(self):
        # gemini-syntax.md 原則13 の項目の名前「予告だけの文の解消」は、その文書の中の名前なので SKILL.md を指す形だけを見る
        stale = (r"Step 2 の[59](?![0-9])", r"手順9", r"Step 1 の1(?![0-9])", r"Step 1 の(?:種類の)?表", r"構造点検",
                 r"Step 1 の記録", r"質問は最大3点", r"SKILL\.md「予告だけの文の解消」", r"Step 3 と Step 4",
                 r"「相手との関係…が分かる依頼では…語調を整えます」", r"「文長と読点の調整」の平均の目安")
        for path in ref_files():
            body = text(path)
            for pattern in stale:
                with self.subTest(file=str(path.relative_to(REFS)), pattern=pattern):
                    self.assertIsNone(re.search(pattern, body))

    def test_moved_rules_point_to_their_sections(self):
        expect = (
            ("slop-catalog.md", "SKILL.md「2文の否定対比と「もちろん、」」に従い、「もちろん、」を外す"),
            ("gemini-syntax.md", "SKILL.md「2文の否定対比と「もちろん、」」に従って見直す"),
            ("doc-types/essay.md", "否定を残して1文にまとめる（SKILL.md「2文の否定対比と「もちろん、」」）"),
            ("slop-catalog.md", "SKILL.md「段落と文の論理構造（つながり）」に従い、宣言の数と続く項目の数が合っている場合だけ"),
            ("review-points.md", "renyo_noun（2.3.0。他動詞を1語だけ名詞にした語を「の」で受ける形。message に当たった言い方）: "
                                 "SKILL.md「直訳語、漢語の詰まり、連用形名詞」"),
            ("gemini-syntax.md", "1つだけなら太字を残す（SKILL.md「太字とラベル」）"),
            ("doc-types/manual.md", "（SKILL.md「装飾記号の排除と太字の表示、コピー調の抑制」）"),
            ("doc-types/mail.md", "（SKILL.md 2章 Step 1 の4つ目の項目）"),
            ("persona.md", "SKILL.md 2章 Step 1 の4つ目の項目の、書き手の立場と読み手との関係の細部"),
            ("fact-recovery.md", "「書き手に確かめたい点」の3点（SKILL.md 3章）にも数えない"),
        )
        for name, words in expect:
            with self.subTest(file=name):
                self.assertIn(words, text(REFS / name))
        for name in ("domains/business.md", "domains/essay.md", "domains/tech.md"):
            with self.subTest(file=name):
                self.assertIn("SKILL.md「段落と文の論理構造（つながり）」に従い、", text(REFS / name))


if __name__ == "__main__":
    unittest.main()
