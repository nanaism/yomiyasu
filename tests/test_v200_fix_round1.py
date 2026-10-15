#!/usr/bin/env python3
"""v2.0.0（diff の詰めの直しのあとの反証、1回目の直し）。

1回目の反証（仕様の S2、S3、S5〜S8、S10、誤検出の指摘1、2、4〜7、9〜11、後戻りの Q1、Q2、Q4）の指摘のうち、
判断の要らないものを直した。文はすべて合成の文（反証の担当の再現の入力と同じ文と、それを言い換えた文）。
実在の会社や商品の名前は使わない。

- 勢い（S2）: --doc-type minutes の見出しの候補は見直し候補のまま（議事録の推敲では見出しを変えない。作者の判断
  2026-10-13 15時台の4）。参考の理由の文は、参考になった候補（絵文字、見出し）に合わせて書く。
- check の3行目（S3、Q4）: 「資料にない数値・名前N件」は、出力に示した候補と同じ条件で数える（数量を主張しない「一つ」だけの
  値は数えない）。
- ヘルプと文書（S5、S6、S10）: promo の見出しの数え方、incident の硬化の参考、絵文字と見出しの参考、「候補N件、参考M件」、
  並べる形の逆転、紹介記事の「安い。うまい。早い。」を1文にしていないか。
- diff の表示（S7、S8）: 最後の状態の行は「上の節」。一覧を読めないときの節の見出しに「（候補なし）」を使わない。
- 否定対比の逆転（指摘1、4、5、7）: 比べて下げる語を、A の句に続くときだけ数え、複合動詞などを除く。語で否定した節
  （対象外、非対応など）を否定のある節とみなす。原文の B の側の「Aの〜」では A を除かない。結論を言う「と確認」
  「と考えられます」では並べる形を数える。
- 数値（指摘2、6、Q1、Q2）: 漢数字の「分」「条」の慣用句、「十分間に合う」、「一つも」「一つひとつ」「一つ一つ」を数にしない。
  範囲・日付・時刻のまとまりの表記の違いは、単位とつなぎの字がそろうときだけ。組の文の値が続く文に移ったとみなすのは、
  組の文に同じ単位の値が増えて（減って）いないときだけ。
- 気持ちの語（指摘9、10）: 堅苦しい・見苦しい・重苦しい、心配は要りません・ご心配には及びません、半分に落ち込む・売上の
  落ち込み、失礼を。
- 勢い（指摘11）: 間接の問いは「かとの」「かという」「かどうか」「か否か」「かと聞く」などに限る。
"""

from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import CheckCase, ROOT, SCRIPTS, split_lines  # noqa: E402
from test_v200_check_infra import PLAIN, copy_scripts, run_diff, shipped_lists  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402

REFERENCES = ROOT / "references"
CORPUS = ROOT / "tests" / "corpus"


def result_of(before, after, doc_type=None):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after, doc_type=doc_type)


def levels(section):
    return [(candidate["subkind"], candidate["level"]) for candidate in section["candidates"]]


def reversal_words(before, after, doc_type=None):
    return [risk["detail"]["word"] for risk in result_of(before, after, doc_type)["meaning_risks"]
            if risk["kind"] == "contrast_reversal"]


def feeling_words(before, after, doc_type=None):
    return [word for risk in result_of(before, after, doc_type)["meaning_risks"] if risk["kind"] == "feeling"
            for word in risk["detail"]["words"]]


def number_risks(before, after, doc_type=None):
    return [risk for risk in result_of(before, after, doc_type)["meaning_risks"] if risk["kind"] == "number"]


def tone_subkinds(before, after, doc_type=None):
    return [candidate["subkind"] for candidate in result_of(before, after, doc_type)["tone"]["candidates"]]


def read(path):
    return path.read_text(encoding="utf-8")


def section_text(path, heading):
    """Markdown の見出し heading の節の本文（次の同じ深さか浅い見出しの手前まで）。"""
    text = read(path)
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading + "\n")
    rest = text[start + len(heading) + 1:]
    found = re.search(r"^#{1,%d} " % level, rest, re.M)
    return rest[:found.start()] if found else rest


# ---- S2: 議事録の見出し ----
MINUTES_HEADINGS = ("# 10月定例会の議事録\n\n## 来期の予算配分と人員計画についての議論\n\n山田さんから来期の予算案の説明がありました。\n\n"
                    "## 新しい会議室の予約方法についての確認\n\n佐藤さんが予約の手順を説明しました。",
                    "# 10月定例会の議事録\n\n## 予算\n\n山田さんから来期の予算案の説明がありました。\n\n"
                    "## 会議室\n\n佐藤さんが予約の手順を説明しました。")
MINUTES_EMOJI = ("# 10月定例会の議事録\n\n## 来期の予算配分の方針\n\n山田さんから予算案の説明がありました✅",
                 "# 10月定例会の議事録\n\n## 来期の予算配分の方針\n\n山田さんから予算案の説明がありました。")
SLIDES_HEADING = ("## 検索が遅くなっていた本当の原因は、実はインデックスの不足にあった\n\n商品の数が増えたのに、索引を足していませんでした。",
                  "## 検索が遅かった原因\n\n商品の数が増えたのに、索引を足していませんでした。")
SLIDES_BOTH = ("## 検索が遅くなっていた本当の原因は、実はインデックスの不足にあった🔍\n\n商品の数が増えたのに、索引を足していませんでした。",
               "## 検索が遅かった原因\n\n商品の数が増えたのに、索引を足していませんでした。")


class MinutesHeadingTest(unittest.TestCase):
    def test_minutes_heading_stays_review(self):
        section = result_of(*MINUTES_HEADINGS, doc_type="minutes")["tone"]
        self.assertEqual(levels(section), [("heading", "review")])
        self.assertEqual(section["level"], "review")

    def test_slides_heading_is_info(self):
        self.assertEqual(levels(result_of(*SLIDES_HEADING, doc_type="slides")["tone"]), [("heading", "info")])

    def test_minutes_emoji_is_info(self):
        self.assertEqual(levels(result_of(*MINUTES_EMOJI, doc_type="minutes")["tone"]), [("emoji", "info")])

    def test_reference_sentence_follows_the_info_subkinds(self):
        cases = ((MINUTES_EMOJI, "minutes", "■ 勢い（参考 1件。文書の種類 minutes では絵文字を外すのが決まりなので、参考として出しています）"),
                 (SLIDES_HEADING, "slides",
                  "■ 勢い（参考 1件。文書の種類 slides では見出しを短い項目名にするのが決まりなので、参考として出しています）"),
                 (SLIDES_BOTH, "slides",
                  "■ 勢い（参考 2件。文書の種類 slides では絵文字を外し、見出しを短い項目名にするのが決まりなので、参考として出しています）"))
        for pair, doc_type, head in cases:
            with self.subTest(doc_type=doc_type, head=head):
                lines = yomiyasu_diff.report_parts(result_of(*pair, doc_type=doc_type))["tone"].split("\n")
                self.assertEqual(lines[0], head)

    def test_removing_an_emoji_from_a_short_heading_is_not_a_heading_change(self):
        """短い見出しの絵文字を外しただけの推敲は、絵文字の候補だけ（見出しの字数に絵文字を数えない）。minutes の見出しを
        見直し候補のままにしたので、絵文字を外す決まりどおりの直しを見出しの見直し候補にしない。"""
        before, after = "# 定例会🗓️\n\n予算の説明がありました。", "# 定例会\n\n予算の説明がありました。"
        for doc_type in (None, "minutes", "slides", "promo"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual([subkind for subkind, _ in levels(result_of(before, after, doc_type)["tone"])], ["emoji"])

    def test_minutes_report_does_not_state_the_opposite_rule(self):
        report = yomiyasu_diff.report(result_of(*MINUTES_HEADINGS, doc_type="minutes"))
        self.assertIn("■ 勢い（見直し候補 1件。書き手の勢いを落としていないか確かめる）", report)
        self.assertNotIn("見出しを短い項目名にするのが決まり", report)


class MinutesCheckRunTest(CheckCase):
    def test_check_run_minutes_heading_is_a_candidate(self):
        a, b = self.write("a.md", MINUTES_HEADINGS[0] + "\n"), self.write("b.md", MINUTES_HEADINGS[1] + "\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--doc-type", "minutes", "--no-record")
        self.assertIn("勢いの検査: 候補1件", lines)


# ---- S3、Q4: check の3行目の「資料にない数値・名前N件」 ----
WEAK_SOURCE = "移行の作業は来週に始めます。担当は運用チームです。\n"
WEAK_FINAL = "移行の作業は来週に始めます。もう一つ、担当は運用チームです。\n"
MATERIAL = "- 移行は来週\n- 担当: 運用チーム\n- 手順書: 共有フォルダ\n"
COMPOSED = "移行の作業は来週に始めます。もう一つお知らせがあります。担当は運用チームで、手順書は共有フォルダにあります。\n"
COMPOSED_DAYS = "移行の作業は来週に始めます。もう一つお知らせがあります。担当は運用チームで、作業は3日かかります。\n"
COUNT = re.compile(r"資料にない数値・名前(\d+)件")
RISK = re.compile(r" meaning_risk=(\d+)")


class UnsupportedCountTest(CheckCase):
    def third_line_count(self, lines):
        found = COUNT.search(lines[2])
        self.assertIsNotNone(found, lines[:3])
        return int(found.group(1))

    def test_rewrite_with_material_does_not_count_weak_one(self):
        src, mat, fin = self.write("src.md", WEAK_SOURCE), self.write("mat.md", MATERIAL), self.write("fin.md", WEAK_FINAL)
        process = self.check("run", "--source", src, "--material", mat, "--final", fin, "--no-record", "--fail-on", "meaning-risk")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        self.assertIn("規則に当たる候補はありません", lines[0])
        self.assertEqual(self.third_line_count(lines), 0)

    def test_compose_does_not_count_weak_one(self):
        mat, fin = self.write("mat.md", MATERIAL), self.write("fin.md", COMPOSED)
        process = self.check("run", "--material", mat, "--final", fin, "--no-record", "--fail-on", "meaning-risk")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(self.third_line_count(split_lines(process.stdout)), 0)

    def test_compose_still_counts_days(self):
        mat, fin = self.write("mat.md", MATERIAL), self.write("fin.md", COMPOSED_DAYS)
        process = self.check("run", "--material", mat, "--final", fin, "--no-record", "--fail-on", "meaning-risk")
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        self.assertEqual(self.third_line_count(lines), 1)
        self.assertIn("- 資料にない数値（後1行目）: 3日", lines)

    def test_rewrite_still_counts_new_days(self):
        src, mat = self.write("src.md", WEAK_SOURCE), self.write("mat.md", MATERIAL)
        fin = self.write("fin.md", "移行の作業は来週に始め、3日で終えます。担当は運用チームです。\n")
        process = self.check("run", "--source", src, "--material", mat, "--final", fin, "--no-record")
        self.assertEqual(self.third_line_count(split_lines(process.stdout)), 1)

    def test_corpus_compose_count_matches_the_candidates(self):
        """反証で見つけたコーパスの5組（Q4）: 新規作成の資料照合と diff の数の合計が、状態の行の meaning_risk と同じ。"""
        pairs = (("blacklist_ai/01_tech_arch_sonnet_default.md", "yomiyasu_rewritten/01_tech_arch_sonnet_default_bl.md"),
                 ("human/human_oga_07.md", "human/human_oga_08.md"),
                 ("raw_ai/06_spec_draft_sonnet_formal.md", "raw_ai/07_code_review_sonnet_casual.md"),
                 ("raw_ai/07_code_review_sonnet_formal.md", "raw_ai/08_essay_retrospective_sonnet_casual.md"),
                 ("raw_ai/09_listicle_patterns.md", "raw_ai/10_essay_fragments.md"))
        for material, final in pairs:
            with self.subTest(material=material):
                process = self.check("run", "--material", CORPUS / material, "--final", CORPUS / final, "--no-record")
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                lines = split_lines(process.stdout)
                # 1組目は資料を原文とみなした diff にも確度の見直し候補が出る。
                # 資料にない数値・名前と、diff の意味が変わる恐れをそれぞれ数える。
                diff_count = re.search(r"うち意味が変わる恐れ(\d+)件", lines[2])
                total = self.third_line_count(lines) + (int(diff_count.group(1)) if diff_count else 0)
                self.assertEqual(total, int(RISK.search(lines[1]).group(1)), lines[:3])


# ---- S5: promo の見出しの数え方（ヘルプと文書） ----
PROMO_HEADING_SENTENCE = "promo では、番号つき項目の行と太字だけの行も勢いの検査の見出しに数えます。"


class PromoHeadingHelpTest(unittest.TestCase):
    def test_detector_help_names_the_promo_headings(self):
        self.assertIn(PROMO_HEADING_SENTENCE, yomiyasu_diff._detector_level_help())

    def test_diff_help_limits_what_does_not_change(self):
        text = "".join(subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "-h"], capture_output=True,
                                      env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=30).stdout.decode("utf-8").split())
        self.assertIn("規則の見直し候補", text)
        self.assertNotIn("意味が変わる恐れ、見直し候補、--fail-onは変わりません", text)
        self.assertIn("".join(PROMO_HEADING_SENTENCE.split()), text)

    def test_check_help_has_the_same_sentence(self):
        text = "".join(subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_check.py"), "run", "-h"],
                                      capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                      timeout=30).stdout.decode("utf-8").split())
        self.assertIn("".join(PROMO_HEADING_SENTENCE.split()), text)

    def test_documents_name_the_promo_headings(self):
        self.assertIn("番号つき項目の行", section_text(REFERENCES / "review-points.md", "### ■ 勢い"))
        self.assertIn("番号つき項目の行", section_text(REFERENCES / "audience.md", "## 13. 種類と外す規則の全体の表"))
        self.assertIn("番号つき項目の行", section_text(REFERENCES / "doc-types" / "promo.md", "## 1. 普通な書き方（直さない）"))


# ---- S6: 文書の説明と出力 ----
class ReviewPointsWordingTest(unittest.TestCase):
    def test_stiffness_reference_types(self):
        text = section_text(REFERENCES / "review-points.md", "### ■ 文体の硬化")
        self.assertIn("incident", text)
        self.assertIn("formal", text)

    def test_mixed_summary_value(self):
        self.assertIn("候補N件、参考M件", section_text(REFERENCES / "review-points.md", "## 1. 出力の始めの行"))

    def test_typed_emoji_and_heading(self):
        text = section_text(REFERENCES / "review-points.md", "### ■ 勢い")
        self.assertIn("promo 以外の種類", text)
        self.assertIn("minutes", text)
        self.assertIn("見直し候補 N件、参考 M件", text)

    def test_coordination_reversal(self):
        text = section_text(REFERENCES / "review-points.md", "### ■ 意味が変わる恐れ")
        self.assertIn("AだけでなくB", text)
        self.assertIn("AとB", text)

    def test_audience_incident_row(self):
        rows = [line for line in section_text(REFERENCES / "audience.md", "## 13. 種類と外す規則の全体の表").split("\n")
                if line.startswith("| incident |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("硬化", rows[0])


# ---- S7: 最後の状態の行 ----
EXCLAMATIONS = ("しおかぜラーメンのスープは濃厚です！麺はもちもちです！", "しおかぜラーメンのスープは濃厚です。麺はもちもちです。")


class StatusLinePlaceTest(unittest.TestCase):
    def test_first_status_points_down_and_last_points_up(self):
        lines = yomiyasu_diff.report(result_of(*EXCLAMATIONS)).split("\n")
        self.assertEqual(lines[1], "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 1か所）"
                                   "（文体の硬化と勢いの見直し候補 1件は下の節）")
        self.assertEqual(lines[-1], "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 1か所）"
                                    "（文体の硬化と勢いの見直し候補 1件は上の節）")
        self.assertLess(lines.index("■ 勢い（見直し候補 1件。書き手の勢いを落としていないか確かめる）"), len(lines) - 1)


# ---- S8: 一覧を読めないとき ----
class ListNoteHeadingTest(unittest.TestCase):
    def test_no_candidates_is_not_written(self):
        with tempfile.TemporaryDirectory(prefix="yomiyasu-fix1-lists-") as folder:
            lists = shipped_lists()
            lists["nominalization"] = "が可能\tが可能\n".encode("cp932")
            lists["intensifiers"] = "とても\n".encode("cp932")
            lists["feelings"] = b"\xff\xfe broken\n"
            scripts = copy_scripts(folder, lists)
            process = run_diff(scripts, PLAIN[0], PLAIN[1])
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
            text = process.stdout.decode("utf-8")
            self.assertNotIn("（候補なし）", text)
            lines = text.split("\n")
            self.assertIn("■ 文体の硬化（一覧の注意）", lines)
            self.assertIn("■ 勢い（一覧の注意）", lines)
            self.assertTrue(lines[lines.index("■ 勢い（一覧の注意）") + 1].startswith("- 強める語の一覧 references/lists/"))


# ---- S10: 紹介記事の「安い。うまい。早い。」を1文にした推敲（勢いの検査では拾わない。文書で案内する）----
class PromoFragmentKnownLimitTest(unittest.TestCase):
    def test_tone_does_not_find_the_joined_fragments(self):
        before = "# 港町の日替わり定食\n\n港町の駅前にある食堂の日替わり定食。安い。うまい。早い。"
        after = "# 港町の日替わり定食\n\n港町の駅前にある食堂の日替わり定食は、安く、うまく、早い。"
        self.assertEqual(result_of(before, after, "promo")["tone"]["candidates"], [])

    def test_review_points_guides_the_agent(self):
        text = section_text(REFERENCES / "review-points.md", "### ■ 差分の見直し候補")
        self.assertIn("安い。うまい。早い。", text)
        self.assertIn("doc-types/promo.md", text)


# ---- 指摘1: 比べて下げる語 ----
DEMOTE_REAL_REVERSALS = (
    ("目的は原因の特定ではなく、早期の復旧です。", "目的は原因を突き止めることです。", "原因", "incident"),
    ("今回の対応で重要なのは再起動ではなく、原因の特定です。", "今回の対応で重要なのは、再起動で被害の拡大を食い止めることです。",
     "再起動", "incident"),
    ("最優先は新機能ではなく、既存機能の安定化です。", "新機能のリリースを来週に控え、最優先で準備を進めます。", "新機能", "article"),
    ("重要なのはレビューではなく、テストの自動化です。", "レビューを次回から必須の重要な手順にします。", "レビュー", "pr"),
    ("成功の要因は新しい設計ではなく、地道な改善です。", "新しい設計は後に最も大きな要因となりました。", "設計", "article"),
    ("最優先は新機能ではなく、既存の不具合の修正です。", "最優先は新機能をはやめに出すことです。", "新機能", "pr"),
    ("重要なのは移行ではなく、既存環境の安定です。", "最も重要なのは、移行で障害を避けることです。", "移行", "formal"),
    ("大切なのは批判ではなく、提案です。", "大切なのは批判を受け止めることです。", "批判", "incident"),
    ("重要なのは値下げではなく、品質の向上です。", "重要なのは値下げに歯止めをかけることです。", "値下げ", "article"),
    ("重要なのは移行ではなく、既存環境の安定です。", "移行は障害を避けることを最優先にします。", "移行", None),
)


class DemoteAnchorTest(unittest.TestCase):
    def test_real_reversals_with_demote_like_words_are_found(self):
        for before, after, word, doc_type in DEMOTE_REAL_REVERSALS:
            with self.subTest(after=after):
                self.assertIn(word, reversal_words(before, after, doc_type))

    def test_demoted_forms_still_not_found(self):
        cases = (("優先するのは新機能ではなく、不具合の修正です。", "新機能は次回に回し、不具合の修正を優先します。"),
                 ("大事なのは外観ではなく、操作の速さです。", "外観の調整は見送り、操作の速さを大事にします。"),
                 ("今回はデザインの変更ではなく、表示の速さの改善を優先します。", "今回は表示の速さの改善を優先し、デザインの変更は後にします。"),
                 ("目的は監視ではなく、記録です。", "監視は控え、記録を目的にします。"),
                 ("優先するのは手作業ではなく、自動化です。", "手作業を避け、自動化を優先します。"),
                 ("重視するのは会議ではなく、文書での共有です。", "会議をやめ、文書での共有を重視します。"),
                 ("最優先は移行ではなく、手順書の整備です。", "移行を止め、手順書の整備を最優先にします。"),
                 # 下げる語のすぐ前の時の語（今回は、当面、いったん）
                 ("優先するのは新機能ではなく、不具合の修正です。", "新機能の追加は今回は見送り、不具合の修正を優先します。"),
                 ("優先するのは新機能ではなく、不具合の修正です。", "新機能は当面見送り、不具合の修正を優先します。"),
                 ("優先するのは新機能ではなく、不具合の修正です。", "新機能の追加はいったん保留し、不具合の修正を優先します。"))
        for before, after in cases:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), [])


# ---- 指摘2: 漢数字の「分」「条」と「十分間に合う」 ----
KANJI_IDIOMS = (
    ("参加者の意見は二分した。", "参加者の意見は分かれた。", "minutes"),
    ("成功の見込みは五分五分だ。", "成功の見込みは半々だ。", "minutes"),
    ("窓から一条の光が差し込んだ。", "窓から一筋の光が差し込んだ。", "essay"),
    ("今から出れば、締め切りには十分間に合います。", "今から出ても、締め切りに間に合います。", None),
    ("当たる確率は二分の一だ。", "当たる確率は半分だ。", "essay"),
    ("外れ値は四分位範囲で判定する。", "外れ値はIQRで判定する。", "article"),
    ("成功は九分九厘まちがいない。", "成功はほぼまちがいない。", None),
    ("結果を百分率で示す。", "結果を割合で示す。", "article"),
    ("準備は十二分にできている。", "準備は十分にできている。", None),
    ("意見が二分される。", "意見が分かれる。", None),
)


class KanjiIdiomTest(unittest.TestCase):
    def test_idioms_are_not_numbers(self):
        for before, after, doc_type in KANJI_IDIOMS:
            with self.subTest(before=before):
                result = result_of(before, after, doc_type)
                self.assertEqual([risk for risk in result["meaning_risks"] if risk["kind"] == "number"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_counted_minutes_and_articles_stay(self):
        for before, after, removed, added in (("会議は三十分で終える。", "会議は40分で終える。", ["三十分"], ["40分"]),
                                              ("休憩は十分間とる。", "休憩は20分間とる。", ["十分"], ["20分"]),
                                              ("第三条に定める。", "第4条に定める。", ["第三条"[1:]], ["4条"])):
            with self.subTest(before=before):
                risks = number_risks(before, after)
                self.assertEqual([(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in risks],
                                 [("replaced", removed, added)])


# ---- 指摘4: 語で否定した節 ----
LEXICAL_NEGATION = (
    ("今回の改修の対象はAPIではなく、管理画面です。", "今回の改修は管理画面だけで、APIと認証は対象外です。", "formal"),
    ("対応するのはChromeではなく、社内で配布しているブラウザです。", "対応するのは社内で配布しているブラウザで、ChromeとSafariは非対応です。",
     "formal"),
    ("この規程の対象は役員と嘱託ではなく、従業員である。", "この規程は従業員を対象とし、役員と嘱託は対象外とする。", "formal"),
    ("今回の改修の対象はAPIではなく、管理画面です。", "今回の改修は管理画面だけで、APIは範囲外です。", "formal"),
    ("CSV出力は今回の対象ではなく、優先度も低い。", "CSV出力は今回の対象外で、優先度も低い。", "formal"),
)


class LexicalNegationTest(unittest.TestCase):
    def test_lexically_negated_clause_is_not_a_reversal(self):
        for before, after, doc_type in LEXICAL_NEGATION:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_plain_coordination_is_still_found(self):
        self.assertIn("API", reversal_words("今回の改修の対象はAPIではなく、管理画面です。", "今回の改修の対象はAPIと管理画面です。"))


# ---- 指摘5: 原文の B の側の「Aの〜」 ----
class SameNounOnTheBSideTest(unittest.TestCase):
    def test_a_of_b_does_not_hide_a_reversal(self):
        for before, after, word, doc_type in (("大事なのは道具ではなく、道具の使い方だ。", "大事なのは道具そのものだ。", "道具", "essay"),
                                              ("重要なのはツールではなく、ツールの使い方です。", "重要なのはツールの性能です。", "ツール",
                                               "article")):
            with self.subTest(after=after):
                self.assertIn(word, reversal_words(before, after, doc_type))

    def test_keeping_the_b_side_is_not_a_reversal(self):
        self.assertEqual(reversal_words("大事なのは道具ではなく、道具の使い方だ。", "道具より、道具の使い方が大事だ。", "essay"), [])

    def test_compound_on_the_b_side_is_still_skipped(self):
        """B の側の「既存施設の」の「施設」は複合語の一部なので、今までどおり A として出さない（fp の FR-bad02。逆転は
        「新設」で出る）。"""
        self.assertEqual(reversal_words("本事業の主な目的は、施設の新設ではなく、既存施設の長寿命化である。",
                                        "本事業の主な目的は、施設の新設及び既存施設の長寿命化である。", "formal"), ["新設"])

    def test_same_noun_as_the_main_word_of_b_is_still_skipped(self):
        self.assertEqual(reversal_words("本制度の主な対象は、新たに事業を始める者ではなく、既に事業を営んでいる者である。",
                                        "本制度の主な対象は、既に事業を営んでいる者であり、新たに事業を始める者は対象としない。"), [])


# ---- 指摘6: 「一つも」「一つひとつ」「一つ一つ」 ----
class WeakOneFormsTest(unittest.TestCase):
    def test_forms_that_do_not_count(self):
        for before, after, doc_type in (("エラーは一つも出ませんでした。", "エラーは出ませんでした。", "incident"),
                                        ("設定を一つひとつ確かめてください。", "設定を順に確かめてください。", "manual"),
                                        ("思い出を一つ一つ書き出した。", "思い出を順に書き出した。", "essay"),
                                        ("項目を1つ1つ確かめる。", "項目を順に確かめる。", None)):
            with self.subTest(before=before):
                result = result_of(before, after, doc_type)
                self.assertEqual([risk for risk in result["meaning_risks"] if risk["kind"] == "number"], [])

    def test_receiving_one_still_counts(self):
        self.assertEqual([r["subkind"] for r in number_risks("記念品を一つもらった。", "記念品をもらった。")], ["lost"])

    def test_changed_count_still_replaced(self):
        self.assertEqual([r["subkind"] for r in number_risks("エラーは一つも出ませんでした。", "エラーは二つ出ました。")],
                         ["replaced"])


# ---- 指摘7: 「と確認」「と考えられます」 ----
class ConclusionFormsTest(unittest.TestCase):
    def test_conclusion_with_coordination_is_found(self):
        for before, after, word, doc_type in (
                ("原因はネットワークではなく、設定の誤りでした。", "原因はネットワークと設定の誤りだと確認しました。", "ネットワーク", "incident"),
                ("原因はネットワークではなく、設定の誤りでした。", "原因はネットワークと設定の誤りと考えられます。", "ネットワーク", "incident"),
                ("対応するブラウザはIEではなく、Edgeです。", "対応するブラウザはIEとEdgeであることを確認済みです。", "IE", "formal")):
            with self.subTest(after=after):
                self.assertIn(word, reversal_words(before, after, doc_type))

    def test_checking_both_is_still_not_found(self):
        for after in ("キャッシュとDNSの設定を確かめたところ、DNSの設定の誤りでした。", "キャッシュとDNSを確認しました。",
                      "キャッシュとDNSの両方を調べました。", "まずキャッシュとDNSを疑いましたが、原因はDNSの設定でした。"):
            with self.subTest(after=after):
                self.assertEqual(reversal_words("原因はキャッシュではなく、DNSの設定でした。", after), [])


# ---- 指摘9、10: 気持ちの語 ----
class FeelingWordsTest(unittest.TestCase):
    def test_not_feelings(self):
        for before, after, doc_type in (
                ("形式ばった挨拶は省きます。", "堅苦しい挨拶は省きます。", None),
                ("体裁の整っていない資料は差し戻します。", "見苦しい体裁の資料は差し戻します。", "formal"),
                ("かしこまった店ではありません。気軽に寄ってください！", "堅苦しい店ではありません。気軽に寄ってください！", "promo"),
                ("長い沈黙が続いた。", "重苦しい沈黙が続いた。", "minutes"),
                ("ご安心ください。データは毎晩自動で保存されます。", "データは毎晩自動で保存されるので、心配は要りません。", None),
                ("お送りした請求書の金額は正しいものです。訂正はありません。", "お送りした請求書の金額は正しいので、ご心配には及びません。", None),
                ("障害の間、スループットは半分に下がりました。", "障害の間、スループットは半分に落ち込みました。", "incident"),
                ("前年と比べて売上が減っています。", "前年と比べて売上の落ち込みが目立ちます。", "proposal")):
            with self.subTest(after=after):
                self.assertEqual(feeling_words(before, after, doc_type), [])

    def test_feelings_still_found(self):
        for before, after, word in (("部屋は狭かった。", "部屋は狭く、息苦しかった。", "苦しかっ"),
                                    ("その日は家に帰った。", "その日は落ち込んで家に帰った。", "落ち込"),
                                    ("結果を知らせた。", "結果を知らせたが、心配だった。", "心配"),
                                    ("先日は失礼をいたしました。資料をお送りします。",
                                     "先日は失礼をいたしました。ご協力に感謝しつつ、資料をお送りします。", "感謝")):
            with self.subTest(after=after):
                self.assertIn(word, feeling_words(before, after))

    def test_list_file_and_builtin_list_match(self):
        rows = [line.split("\t") for line in read(REFERENCES / "lists" / "feelings.txt").split("\n")
                if line and not line.startswith("#")]
        self.assertEqual([tuple(row) for row in rows], [tuple(item) for item in yomiyasu_diff.BUILTIN_LISTS["feelings"]])


# ---- 指摘11: 間接の問い ----
class IndirectQuestionNarrowTest(unittest.TestCase):
    def test_guess_and_adverb_are_not_indirect_questions(self):
        for before, after in (("このラーメン、食べてみたくなりませんか？", "このラーメンを食べてみたくなるかと思います。"),
                              ("残りはあとわずか？いいえ、まだ間に合います！", "残りはあとわずかとなりましたが、まだ間に合います！")):
            with self.subTest(after=after):
                self.assertIn("question", tone_subkinds(before, after, "promo"))

    def test_indirect_questions_still_skip(self):
        for before, after in (("予算は足りるのか？", "予算が足りるかとの質問があった。"),
                              ("このまま進めてよいのか？", "このまま進めてよいかどうかを、全員で確かめた。"),
                              ("その機能は要るのか？", "その機能は要るのかという声があった。"),
                              ("来週までに直せるか？", "来週までに直せるかと聞かれた。"),
                              ("来週までに直せるか？", "来週までに直せるかと尋ねられた。")):
            with self.subTest(after=after):
                self.assertNotIn("question", tone_subkinds(before, after))


# ---- Q1: 範囲・日付・時刻のまとまりの単位 ----
CLUSTER_MUST = (
    ("工期は2〜3か月を見込む。", "工期は2週間から3か月を見込む。", ["2"], ["2週間"]),
    ("締め切りは10/30です。", "締め切りは10時30分です。", ["10", "30"], ["10時", "30分"]),
    ("開始は10:30です。", "開始は10月30日です。", ["10", "30"], ["10月", "30日"]),
    ("手順3-5を実行する。", "3日から5日で実行する。", ["3", "5"], ["3日", "5日"]),
    ("待ち時間は10〜20分です。", "待ち時間は10秒から20分です。", ["10"], ["10秒"]),
    ("検証には3-5日かかる。", "検証には3時間から5日かかる。", ["3"], ["3時間"]),
    ("会議は10:30〜11:15です。", "会議は10月30日から11月15日です。", ["10", "30", "11", "15"], ["10月", "30日", "11月", "15日"]),
)
CLUSTER_KEEP = (
    ("作業には3〜5日かかる。", "作業には3日から5日かかる。"),
    ("作業には3-5日かかる。", "作業には3日から5日かかる。"),
    ("作業には3から5日かかる。", "作業には3日から5日かかる。"),
    ("参加者は5〜10を見込む。", "参加者は5人から10人を見込む。"),
    ("参加者は5～10人を見込む。", "参加者は5人から10人を見込む。"),
    ("公開日は2026-10-13です。", "公開日は2026年10月13日です。"),
    ("公開日は2026/10/13です。", "公開日は2026年10月13日です。"),
    ("会議は10:30に始める。", "会議は10時30分に始める。"),
    ("受付は17:30までです。", "受付は17時30分までです。"),
    ("会議は10時30に始める。", "会議は10時30分に始める。"),
    ("見込みは2〜3か月です。", "見込みは2か月から3か月です。"),
    # 時刻と日付の範囲（つなぎの字が混ざるまとまり）
    ("会議は10:30〜11:15です。", "会議は10時30分から11時15分です。"),
    ("受付は10/13〜10/15です。", "受付は10月13日から10月15日です。"),
    # 相手の側で日付と時刻が1つのまとまりになった形（2026年10月13日10時30分）
    ("公開は2026/10/13 10:30です。", "公開は2026年10月13日10時30分です。"),
)


class ClusterUnitTest(unittest.TestCase):
    def test_unit_changes_in_ranges_dates_and_times_are_found(self):
        for before, after, removed, added in CLUSTER_MUST:
            with self.subTest(after=after):
                result = result_of("# 計画\n\n" + before, "# 計画\n\n" + after)
                risks = [risk for risk in result["meaning_risks"] if risk["kind"] == "number"]
                self.assertEqual([(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in risks],
                                 [("replaced", removed, added)])
                self.assertGreater(result["fail_on_meaning_risk_count"], 0)

    def test_notation_differences_still_cancel(self):
        for before, after in CLUSTER_KEEP:
            with self.subTest(after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_ground_uses_the_same_condition(self):
        for final, material, wanted in (("工期は2週間から3か月を見込む。", "工期は2〜3か月を見込む。", ["2週間"]),
                                        ("締め切りは10時30分です。", "締め切りは10/30です。", ["10時", "30分"]),
                                        ("開始は10月30日です。", "開始は10:30です。", ["10月", "30日"])):
            with self.subTest(final=final):
                result = yomiyasu_diff.ground(final + "\n", [material + "\n"])
                got = [risk["detail"]["text"] for risk in result["meaning_risks"] if risk.get("subkind") == "number"]
                self.assertEqual(got, wanted)
        for final, material in (("作業は3日から5日かかる。", "作業は3〜5日かかる。"), ("会議は10時30分に始める。", "会議: 10:30開始"),
                                ("公開日は2026年10月13日です。", "公開日: 2026-10-13")):
            with self.subTest(final=final):
                result = yomiyasu_diff.ground(final + "\n", [material + "\n"])
                self.assertEqual([r for r in result["meaning_risks"] if r.get("subkind") == "number"], [])


# ---- Q2: 組の文の値を変え、続く文に元の値を書いた（消した）推敲 ----
class MovedValueTest(unittest.TestCase):
    def test_changed_value_with_the_old_value_in_an_inserted_sentence(self):
        risks = number_risks("移行は3日で終える。検証は5日かかる。", "移行は5日で終える。予備として3日を見込む。検証は5日かかる。")
        self.assertEqual([(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in risks],
                         [("replaced", ["3日"], ["5日"])])

    def test_changed_value_with_a_deleted_sentence(self):
        risks = number_risks("移行は3日で終える。検証は5日かかる。予備日は3日とる。", "移行は5日で終える。予備日は3日とる。")
        self.assertEqual([(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in risks],
                         [("replaced", ["3日"], ["5日"])])

    def test_moved_sentence_with_shifted_pairs_is_not_a_change(self):
        """文を前へ動かして文の組が1つずれた推敲（正解つきの書き換えの組の1つと同じ文）。
        続く文のほうが組の相手によく似ていれば、今までどおり値を移しただけとみなす（Q2 の直しで「4倍 → 3倍」を出さない）。"""
        queue = "非同期メッセージングキューでサービス間をつなぐと、送信側と受信側の障害が互いに広がりにくくなると言われています。"
        worker = "ワーカーの処理が失敗した場合、指数バックオフにジッタを加えて再実行するのです。"
        moved = "キャンペーン通知を配信したところ、同時アクセスが平常時の4倍に増えたのです。"
        before = queue + worker + moved + "キャンペーン開始で、リクエスト数が通常の約3倍に増えたようです。"
        after = moved + queue + worker + "キャンペーン開始で、リクエスト数が通常の約3倍に増えたと言われています。"
        self.assertEqual(number_risks(before, after), [])

    def test_deleted_sentence_with_shifted_pairs_is_lost(self):
        """文を消し、次の文の言い回しだけを変えた推敲（正解つきの書き換えの組の1つと同じ文）。
        消えた値として出す（「4倍 → 3倍」の入れ替えにしない）。"""
        tail = "から20:47までの35分間、注文APIとユーザー情報APIへのリクエストの約38%に対してゲートウェイが504を返したかもしれない。"
        risks = number_risks("キャンペーン通知の配信で、同時アクセスが平常時の4倍になったという。"
                             "キャンペーン告知メールの配信で、通常の約3倍のリクエストが集中しました。" + tail,
                             "キャンペーン告知メールの配信で、通常の約3倍のリクエストが集中しましただろう。" + tail)
        self.assertEqual([(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in risks], [("lost", ["4倍"], [])])

    def test_split_sentence_still_moves_the_value(self):
        self.assertEqual(number_risks("接続待ちが30秒のタイムアウトに達し、ゲートウェイが504を返した。",
                                      "接続待ちが30秒のタイムアウトに達した。ゲートウェイはそのとき504を返した。"), [])
        self.assertEqual(number_risks("Aの作業は3日かかり、Bの作業は5件残った。", "Aの作業は3日かかった。そのあと、Bの作業は5件残った。"), [])


if __name__ == "__main__":
    unittest.main()
