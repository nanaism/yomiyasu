#!/usr/bin/env python3
"""G15 段3: SKILL.md と references の事実の確かめの文が、道具（check）と食い違わないことを確かめる（設計 11.2 の最後の箇条）。

- SKILL.md に節「事実の確かめ」の見出しと references/fact-recovery.md への参照があり、Step 3 の run に --fact-gaps がある。
- references の事実の確かめの文書（ルートと skills/yomiyasu の両方）にある区切りの行が check の受ける形で、
  コードに書いたオプションが check のヘルプにある。区切りの例をそのまま check に渡すと、資料が出典ごとに分かれる。
- references/lists/fact-gaps.txt が両方にあり、内蔵の一覧と同じ中身で読める。
文はすべて合成。
"""

from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "skills" / "yomiyasu"
SKILL_MD = PACKAGE / "SKILL.md"
CHECK = ROOT / "scripts" / "yomiyasu_check.py"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import yomiyasu_check as check  # noqa: E402
import yomiyasu_diff as diff  # noqa: E402
from test_v200_skill_contract import code_segments, check_commands, TOP_LEVEL  # noqa: E402

REFERENCE_BASES = (ROOT / "references", PACKAGE / "references")
FACT_DOCS = ("fact-recovery.md", "fact-recovery-details.md")
# 区切りの行として書いてよい形（check の _MARKERS と _MATERIAL_MARKER と同じ決まり）
MARKER_HEAD = "<<<yomiyasu:"


def fenced_blocks(text):
    """Markdown のフェンスの中身を、(言語, 行のリスト) の並びで返す（行の頭の字下げは外す）。"""
    blocks, fence, lang, rows, indent = [], None, "", [], 0
    for line in text.split("\n"):
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})(\S*)", stripped)
        if fence is None and marker:
            fence, lang, rows = marker.group(1), marker.group(2), []
            indent = len(line) - len(line.lstrip(" "))
            continue
        if fence is not None:
            if stripped.startswith(fence) and stripped.strip(fence[0]) == "":
                blocks.append((lang, rows))
                fence = None
            else:
                rows.append(line[indent:] if line[:indent].strip() == "" else line)
    return blocks


def marker_lines(text):
    """文書のコード（フェンスとインライン）の中で、区切りの頭（<<<yomiyasu:）で始まる行か語。"""
    found = []
    for segment in code_segments(text):
        for piece in segment.split("\n"):
            piece = piece.strip()
            # 「<<<yomiyasu: で始まる行」のように頭だけを名指した語は、区切りの例ではない
            if piece.lower().startswith(MARKER_HEAD) and piece.endswith(">>>"):
                found.append(piece)
    return found


def accepted_marker(line):
    """check が区切りとして受ける行なら役割（source、material、final）を返す。受けなければ None。"""
    bare = line.encode("utf-8")
    if bare in check._MARKERS:
        return check._MARKERS[bare]
    return "material" if check._material_marker(bare) is not None else None


class FactRecoveryCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-g15-skill-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.skill = SKILL_MD.read_text(encoding="utf-8")

    def run_check(self, args, stdin=None):
        env = dict(os.environ, YOMIYASU_STATE_DIR=str(self.root / "state"), COLUMNS="200", NO_COLOR="1",
                   PYTHONDONTWRITEBYTECODE="1")
        for key in ("FORCE_COLOR", "PYTHON_COLORS", "YOMIYASU_SESSION"):
            env.pop(key, None)
        return subprocess.run(
            [sys.executable, "-B", str(CHECK)] + [str(a) for a in args],
            input=stdin.encode("utf-8") if stdin is not None else None,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            capture_output=True, timeout=60, cwd=str(self.root), env=env)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path


class TestSkillMentionsFactCheck(FactRecoveryCase):
    """SKILL.md の文。"""

    def test_has_fact_section_heading_in_template_order(self):
        """出力の雛形に「### 事実の確かめ」があり、「書き手に確かめたい点」のあと、「確認の記録」の前にある。"""
        heading = re.search(r"(?m)^### 事実の確かめ$", self.skill)
        self.assertIsNotNone(heading, "SKILL.md に「### 事実の確かめ」の見出しがない")
        ask = self.skill.find("### 書き手に確かめたい点")
        record = self.skill.find("### 確認の記録")
        self.assertTrue(0 <= ask < heading.start() < record, (ask, heading.start(), record))

    def test_refers_to_fact_recovery_reference(self):
        """references/fact-recovery.md を名指して読む文があり、そのファイルが両方の references にある。"""
        self.assertIn("`references/fact-recovery.md`", self.skill)
        for base in REFERENCE_BASES:
            for name in FACT_DOCS:
                with self.subTest(path=str((base / name).relative_to(ROOT))):
                    self.assertTrue((base / name).is_file())

    def test_run_commands_carry_fact_gaps(self):
        """Step 3 の run のコマンド（ファイルと --stdin）の両方に --fact-gaps がある。"""
        runs = [segment.strip() for segment in code_segments(self.skill)
                if re.search(r"yomiyasu_check\.py run\b", segment)]
        self.assertTrue(any("--stdin" in line for line in runs), runs)
        self.assertTrue(any("--source" in line for line in runs), runs)
        for line in runs:
            with self.subTest(command=line):
                self.assertIn("--fact-gaps", line)

    def test_fact_sentence_sits_after_rephrase_test(self):
        """Step 2 の事実の確かめの文は、言い直しテストのあと、本文を直す項目の前にある（設計の手順3の位置。
        材料を決めるのが書き直しの前になる）。
        2.6.0 で Step 2 の1〜15の手順をなくし、事実の確かめの文は言い直しテストの項目3の末尾に、本文を直す項目は4になった。"""
        step2 = self.skill.find("### Step 2:")
        step3 = self.skill.find("### Step 3:")
        rephrase = self.skill.find("（言い直しテスト）", step2)
        sentence = self.skill.find("自分が書いた原稿では、読み手が動く値と主張を資料と文脈で確かめます。")
        edit_item = self.skill.find("\n4. 本文は1か所ずつ、前後の文を読んで直します。", step2)
        self.assertTrue(0 <= step2 < rephrase < sentence < edit_item < step3,
                        (step2, rephrase, sentence, edit_item, step3))
        self.assertEqual(self.skill.count("`references/fact-recovery.md` を読み"), 1)
        # fact-recovery.md を読むときの並び（見えない中身、抜け、食い違いと出典のない値、値を入れる前、原稿だけの抜け）は
        # v2.5.0 と同じ。言い直しテストのあとの同じ文にある
        reading = self.skill[sentence:self.skill.index("`references/fact-recovery.md` を読み", sentence)]
        for words in ("比喩や誇張で見えない中身", "抜けた主語・数値・条件", "出典のない値", "会話や資料の値を本文に入れる前",
                      "原稿だけを渡されて読み手が動けない値が抜けているとき"):
            with self.subTest(words=words):
                self.assertIn(words, reading)

    def test_question_place_is_report_and_grounds_are_limited(self):
        """設計 5.1 の相殺（確認は報告で行う）と、根拠を限る「だけ」が入っている。
        2.6.0 では、読み取れないことの質問を本文に入れない文が「情報が足りない場合の暫定文」にあり、確かめられなかった
        事実の行き先は雛形の「事実の確かめ」の括弧に書いてある。根拠の文は「〜に書いてあることだけです」になった。"""
        self.assertNotIn("不明な点の確認は「書き手に確かめたい点」で行います", self.skill)
        provisional = self.skill[self.skill.index("### 情報が足りない場合の暫定文"):self.skill.index("### 文書の立場と文末")]
        self.assertIn("読み取れないことの注記、質問、「要確認」のような編集表示は本文に入れず", provisional)
        fact_heading = self.skill.index("### 事実の確かめ\n")
        self.assertIn("確かめられなかった点", self.skill[fact_heading:self.skill.index("### 確認の記録", fact_heading)])
        self.assertIn("コマンドの出力）に書いてあることだけです", self.skill)

    def test_reference_states_its_own_rules(self):
        """fact-recovery.md が、SKILL.md にない決まりを SKILL.md に任せていない（資料での訂正、戻すだけの修正の例外、
        問いの上限、使わない材料）。"""
        for base in REFERENCE_BASES:
            text = (base / "fact-recovery.md").read_text(encoding="utf-8")
            with self.subTest(base=str(base.relative_to(ROOT))):
                self.assertNotIn("SKILL.md の決まりで行う", text)
                self.assertIn("利用者が渡した資料での訂正", text)
                self.assertIn("最優先ルール", text)
                self.assertIn("この場合だけの例外", text)
                self.assertIn("問いは3つまで", text)
                for word in ("この会話で自分が書いたほかのファイル", "CLAUDE.md", "書き手の分からないファイル",
                             "途中で切れた出力"):
                    self.assertIn(word, text)

    def test_old_report_place_for_material_is_gone(self):
        """資料に基づく訂正を「変えたところ」に「（資料に基づく補足）」と書く古い指示が、SKILL.md と references にない。"""
        documents = [SKILL_MD]
        for base in REFERENCE_BASES:
            documents.extend(sorted(base.rglob("*.md")))
        for path in documents:
            with self.subTest(document=str(path.relative_to(ROOT))):
                self.assertNotIn("（資料に基づく補足）", path.read_text(encoding="utf-8"))


class TestReferenceExamplesMatchCheck(FactRecoveryCase):
    """references の区切りの例とコマンドが、check のヘルプの引数と、check の読み方に合う。"""

    def documents(self):
        for base in REFERENCE_BASES:
            for name in FACT_DOCS:
                yield base / name

    def test_marker_lines_are_accepted_by_check(self):
        """事実の確かめの文書のコードにある <<<yomiyasu: の行は、どれも check が区切りとして受ける形。"""
        for path in self.documents():
            text = path.read_text(encoding="utf-8")
            lines = marker_lines(text)
            self.assertTrue(any(line.startswith("<<<yomiyasu:material ") for line in lines),
                            "{} に出典つきの区切りの例がない".format(path.relative_to(ROOT)))
            for line in lines:
                if "…" in line or "materials" in line:   # 書き損じの例として書いたもの（下の試験で確かめる）
                    continue
                with self.subTest(document=str(path.relative_to(ROOT)), line=line):
                    self.assertIsNotNone(accepted_marker(line), "check が受けない区切り: " + line)

    def test_bad_marker_example_is_rejected_by_check(self):
        """書き損じの例（<<<yomiyasu:materials>>>）は、check が終了コード2で止め、記録を書かない。"""
        text = (ROOT / "references" / "fact-recovery-details.md").read_text(encoding="utf-8")
        self.assertIn("`<<<yomiyasu:materials>>>`", text)
        self.write("final.md", "削除は毎日3時です。\n")
        self.write("bad.material.txt", "<<<yomiyasu:materials>>>\n削除は毎日3時に走ります\n")
        result = self.run_check(["run", "--final", "final.md", "--material", "bad.material.txt"])
        self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", "replace"))
        self.assertFalse((self.root / "state").exists())

    def test_options_in_code_are_in_help(self):
        """事実の確かめの文書のコードに書いた check のオプションが、check のヘルプにある。"""
        helps = {}
        for name in ("run", "verify"):
            process = self.run_check([name, "--help"])
            self.assertEqual(process.returncode, 0)
            helps[name] = process.stdout.decode("utf-8")
        commands = 0
        for path in self.documents():
            by_command, loose = check_commands(code_segments(path.read_text(encoding="utf-8")))
            commands += len(by_command) + len(loose)
            for name, options in sorted(by_command.items()):
                self.assertNotEqual(name, TOP_LEVEL)
                for option in sorted(options):
                    with self.subTest(document=str(path.relative_to(ROOT)), command=name, option=option):
                        self.assertIn(option, helps[name])
            for option in sorted(loose):
                with self.subTest(document=str(path.relative_to(ROOT)), option=option, where="loose"):
                    self.assertTrue(any(option in text for text in helps.values()), option)
        # 照らす対象がなければ、この試験は何も確かめていない
        self.assertGreater(commands, 0)

    def test_material_file_example_splits_by_label(self):
        """fact-recovery.md の抜き書きの例をそのまま --material のファイルにすると、出典ごとの資料に分かれ、
        出典の中の数は照らされない。"""
        text = (ROOT / "references" / "fact-recovery.md").read_text(encoding="utf-8")
        examples = [rows for lang, rows in fenced_blocks(text)
                    if rows and rows[0].startswith("<<<yomiyasu:material")]
        self.assertEqual(len(examples), 1, "fact-recovery.md の抜き書きの例が1つでない")
        rows = examples[0]
        labels = [check._material_marker(row.encode("utf-8"))[0] for row in rows if row.startswith(MARKER_HEAD)]
        self.write("drafts/release.md", "再試行の間隔を短くしました。\n削除は毎日2時です。\n")
        self.write("drafts/release.final.md", "再試行の間隔を1秒から0.5秒に短くしました。\n削除は毎日3時です。\n")
        self.write("drafts/release.final.material.txt", "\n".join(rows) + "\n")
        result = self.run_check(["run", "--source", "drafts/release.md", "--final", "drafts/release.final.md",
                                 "--fact-gaps", "--material", "drafts/release.final.material.txt", "--json"])
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        data = json.loads(result.stdout.decode("utf-8"))
        sources = [source for source in data["materials"]["sources"] if source["role"] == "material"]
        self.assertEqual([source.get("label") for source in sources], labels)
        found = [item for item in data["materials"]["items"] if item.get("text") == "3時"]
        self.assertTrue(found and found[0]["classification"] == "from_materials", found)
        # 出典の「2回目」の2は資料の値として照らされない（最終稿に「2回」があっても資料にあるとしない）
        self.write("drafts/other.final.md", "再試行の間隔を短くしました。\n削除は毎日3時で、2回まで再試行します。\n")
        again = self.run_check(["run", "--source", "drafts/release.md", "--final", "drafts/other.final.md",
                                "--material", "drafts/release.final.material.txt", "--json", "--new-run"])
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8", "replace"))
        items = json.loads(again.stdout.decode("utf-8"))["materials"]["items"]
        twice = [item for item in items if item.get("text") == "2回"]
        self.assertTrue(twice and twice[0]["classification"] == "not_in_sources", twice)

    def test_stdin_example_runs(self):
        """fact-recovery-details.md の --stdin の例を、原文と最終稿の置き場所に合成の文を入れて渡すと、
        check が受けて、出典つきの資料が1件になる。"""
        text = (ROOT / "references" / "fact-recovery-details.md").read_text(encoding="utf-8")
        blocks = [rows for lang, rows in fenced_blocks(text) if rows and "run --stdin" in rows[0]]
        self.assertEqual(len(blocks), 1, "fact-recovery-details.md の --stdin の例が1つでない")
        rows = blocks[0]
        command = rows[0]
        self.assertIn("--fact-gaps", command)
        body = rows[1:rows.index("YOMIYASU_EOF")]
        filled = []
        for row in body:
            if row == "（原文）":
                row = "削除は毎日2時です。"
            elif row == "（最終稿）":
                row = "削除は毎日3時です。"
            filled.append(row)
        options = [word for word in command.split() if word.startswith("--")]
        result = self.run_check(["run"] + options + ["--json"], stdin="\n".join(filled) + "\n")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        data = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual([source.get("label") for source in data["materials"]["sources"] if source["role"] == "material"],
                         ["利用者の発言"])
        self.assertIsNotNone(data.get("fact_gaps"))


class TestFactGapsList(unittest.TestCase):
    """references/lists/fact-gaps.txt。"""

    def test_list_is_in_both_places_and_matches_builtin(self):
        """一覧が両方の references にあり、内蔵の一覧と同じ行を同じ順で持つ（置いても候補が変わらない）。"""
        for base in REFERENCE_BASES:
            path = base / "lists" / "fact-gaps.txt"
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertTrue(path.is_file())
                parsed = diff.parse_list(path.read_text(encoding="utf-8"), pattern=True)
                self.assertEqual([tuple(item) for item in parsed],
                                 [tuple(item) for item in diff.BUILTIN_LISTS["fact-gaps"]])

    def test_list_is_read_from_file(self):
        """道具が一覧をファイルから読み、読めなかった理由がない。"""
        diff._LIST_CACHE.pop("fact-gaps", None)
        diff._LIST_PROBLEMS.pop("fact-gaps", None)
        try:
            info = diff._list_info("fact-gaps")
        finally:
            diff._LIST_CACHE.pop("fact-gaps", None)
            diff._LIST_PROBLEMS.pop("fact-gaps", None)
        self.assertEqual(info, {"list": "references/lists/fact-gaps.txt", "list_problem": None})


class TestDocTypeLines(unittest.TestCase):
    """種類ごとの扱いの1行（設計 6.2）が、両方の references の doc-types にある。"""

    def test_doc_types_point_to_details(self):
        for base in REFERENCE_BASES:
            for name in ("essay", "promo", "formal", "paper", "mail"):
                path = base / "doc-types" / (name + ".md")
                with self.subTest(path=str(path.relative_to(ROOT))):
                    text = path.read_text(encoding="utf-8")
                    self.assertIn("会話やファイルから", text)
                    self.assertIn("`references/fact-recovery-details.md` 6章", text)


if __name__ == "__main__":
    unittest.main()
