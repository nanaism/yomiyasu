#!/usr/bin/env python3
"""v2.0.0（diff の詰めの直し）: 文体の硬化の検査（stiffness）、勢いの検査（tone）、lint の種類 promo。

仕様の反証レビュー（反証で見つけた例の一部）と、誤検出の反証
レビュー（反証で見つけた例）、大賀さんの判断（2026-10-14 朝。紹介記事・宣伝文では「！」を
同じ段落に3つ以上並べても減らさず、評価の語を短く重ねる型「安い。うまい。早い。」も残す）の直し。文はすべて合成の文
（レビューの組の文と、それを言い換えた文、この段で足した文）。
実在の会社や商品の名前は使わない。

- 勢い: 「！」が3つ以上あれば減っても数えない許しを、種類によらず外した。紹介記事で3つの「！」を1つにした推敲も候補になる
  （種類なしと promo は見直し候補、技術文書などの参考の種類では参考のまま）。
- lint: --doc-type promo のとき fragment_run（評価の語だけの短い文の並び）を外す。種類なしとほかの種類は今までどおり。
- 勢い: 紹介記事で同じ強める語の繰り返しを減らした推敲（「とても」3個 → 1個）は、promo でも見直し候補のまま（fp の P6 は
  採らない。強める語を削らない、減らさないという大賀さんの判断と食い違うため）。
- 硬化: 障害報告（incident）も参考（info）の種類にする（v1.1.2 の好み「報告書では『障害が発生した朝』が合う」）。
- 硬化: 文書全体の候補は、変わった文の組が2つ以上のときだけ出す（fp の P3）。
- 硬化: 「の」の連続は、新しい連続の名詞が組になった原文の文にすべてあれば出さない（補足カッコを外しただけの推敲。fp の P7）。
- 硬化: 平均の文の長さは、表示する値（整数に丸めた値）で増えたかを決める（「18字から18字に増えました」を出さない。spec の F12）。
- 勢い: 種類を指定していて promo でないときは、絵文字と見出しの候補を参考（info）にする（fp の P4）。種類なしは見直し候補のまま。
  1つの検査に見直し候補と参考が混ざるときは、節の見出しを「見直し候補 N件、参考 M件」、完了報告の値を「候補N件、参考M件」にする。
- 勢い: 「？」の減りは、組になった推敲後の文が間接の問い（「〜かとの」「〜かという」「〜かどうか」など）なら数えない
  （fp の F9）。意味が変わる恐れの「問いの文が問いでなくなった」（sentence_type）は変えない。
- 勢い: 候補の行の抜き出しを、「！」や強める語、絵文字の位置のまわり（前後20字）にし、2か所目からも行を並べる（5か所まで。
  超えたら「ほか N か所」）。空の抜き出し（『』）は出さない（spec の F11）。
- コーパス48組（yomiyasu の正しい推敲）で、硬化と勢いの候補は0件（spec の F14 の一部）。
"""

from pathlib import Path
import os
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import markdown_visibility  # noqa: E402
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402
from test_v200_check import CheckCase  # noqa: E402

TAIL = "書き手の勢いを落としていないか確かめてください。"
DOC_TYPES = tuple(row[0] for row in markdown_visibility.DOC_TYPES)


def result_of(before, after, doc_type=None):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after, doc_type=doc_type)


def tone_of(before, after, doc_type=None):
    return result_of(before, after, doc_type)["tone"]


def stiffness_of(before, after, doc_type=None):
    return result_of(before, after, doc_type)["stiffness"]


def levels(section):
    return [(candidate["subkind"], candidate["level"]) for candidate in section["candidates"]]


def section_lines(result, key):
    return yomiyasu_diff.report_parts(result)[key].split("\n")


# ---- 大賀さんの判断 1: 「！」の3つ以上の許しを外す ----
THREE_ONE_LINE = ("安い！うまい！早い！", "安くてうまくて早い！")
THREE_LINES = ("安い！\nうまい！\n早い！", "安くて\nうまくて\n早い！")
# 紹介記事の組の many の3組と同じ形（同じ段落の3つの「！」を減らした推敲）
PROMO_MANY = (
    ("新作が出ました！ どれもおいしい！ 今すぐ来てください！", "新作が出ました！ どれもおいしいので、ぜひ来てください。"),
    ("安い！ うまい！ 早い！ 三拍子そろったお店です。", "安くて、うまくて、早い！ 三拍子そろったお店です。"),
    ("最強です！ 最高です！ 間違いなしです！", "最強です！ 間違いなしの一品です。"),
)


class ExclamationRunTest(unittest.TestCase):
    """同じ段落に「！」が3つ以上並んでも、減らせば候補になる（勢いの文書 2.2 の許しを、大賀さんの判断で外した）。"""

    def test_one_line_is_a_review_candidate_without_type_and_for_promo(self):
        for doc_type in (None, "promo"):
            with self.subTest(doc_type=doc_type):
                section = tone_of(*THREE_ONE_LINE, doc_type=doc_type)
                self.assertEqual(levels(section), [("exclamation", "review")])
                detail = section["candidates"][0]["detail"]
                self.assertEqual((detail["old"], detail["new"]), (3, 1))

    def test_line_breaks_inside_a_paragraph_are_the_same(self):
        for doc_type in (None, "promo"):
            with self.subTest(doc_type=doc_type):
                section = tone_of(*THREE_LINES, doc_type=doc_type)
                self.assertEqual(levels(section), [("exclamation", "review")])
                detail = section["candidates"][0]["detail"]
                self.assertEqual((detail["old"], detail["new"]), (3, 1))

    def test_reference_doc_types_stay_info(self):
        for doc_type in ("pr", "article", "incident", "manual", "formal"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(levels(tone_of(*THREE_ONE_LINE, doc_type=doc_type)), [("exclamation", "info")])

    def test_promo_cases_with_many_exclamations(self):
        for before, after in PROMO_MANY:
            with self.subTest(before=before):
                found = levels(tone_of(before, after, doc_type="promo"))
                self.assertIn(("exclamation", "review"), found)

    def test_keeping_every_exclamation_has_no_candidate(self):
        before = "スープは濃厚！麺はもちもち！しおかぜラーメン、本当におすすめです！"
        self.assertEqual(tone_of(before, before, doc_type="promo")["candidates"], [])


# ---- 大賀さんの判断 2: lint の promo で fragment_run を外す ----
FRAGMENTS = "港町の駅前にある食堂の日替わり定食。安い。うまい。早い。\n"


class LintPromoFragmentTest(unittest.TestCase):
    def rules(self, text, doc_type=None):
        return [finding["rule"] for finding in yomiyasu_lint.lint_text(text, doc_type=doc_type)["findings"]]

    def test_promo_skips_fragment_run(self):
        result = yomiyasu_lint.lint_text(FRAGMENTS, doc_type="promo")
        self.assertNotIn("fragment_run", [finding["rule"] for finding in result["findings"]])
        self.assertEqual(result["context"]["skipped_by_doc_type"], {"emoji_prohibited": 0, "fragment_run": 1})
        report = yomiyasu_lint.render_report(result)
        self.assertIn("種類に合わせて外した候補 1件（emoji_prohibited 0件、fragment_run 1件）。", report)

    def test_no_type_and_other_types_keep_fragment_run(self):
        self.assertIn("fragment_run", self.rules(FRAGMENTS))
        for doc_type in DOC_TYPES:
            if doc_type == "promo":
                continue
            with self.subTest(doc_type=doc_type):
                self.assertIn("fragment_run", self.rules(FRAGMENTS, doc_type))

    def test_table_row(self):
        self.assertEqual(tuple(yomiyasu_lint.DOC_TYPE_SKIP_RULES["promo"]), ("emoji_prohibited", "fragment_run"))


# ---- 大賀さんの判断 3: 強める語の繰り返しを減らした推敲は promo でも候補のまま（fp の P6 を採らない）----
REPEATED_INTENSIFIERS = (
    # 反証で見つけた例
    ("とても安くて、とてもおいしくて、とても量が多い！ 学生に大人気の定食屋です。",
     "安くておいしく、量もとても多い！ 学生に大人気の定食屋です。", ["とても"]),
    ("本当に本当においしいので、ぜひ食べてみてください！", "本当においしいので、ぜひ食べてみてください！", ["本当に"]),
    ("どのケーキも、本当においしい！ 本当に、本当におすすめです！", "どのケーキも本当においしい！ 心からおすすめです！", ["本当に"]),
)


class RepeatedIntensifierTest(unittest.TestCase):
    def test_reducing_repeated_intensifiers_stays_a_review_candidate(self):
        for before, after, words in REPEATED_INTENSIFIERS:
            with self.subTest(before=before):
                section = tone_of(before, after, doc_type="promo")
                [candidate] = [c for c in section["candidates"] if c["subkind"] == "intensifier"]
                self.assertEqual(candidate["level"], "review")
                self.assertEqual(candidate["detail"]["words"], words)


# ---- spec の F3: 障害報告の硬化は参考 ----
INCIDENT_PAIRS = (
    ("障害が起きた朝、サーバーが止まりました。原因を調べて、昼に直しました。",
     "障害が発生した朝、サーバーが停止しました。原因を調査し、昼に復旧しました。"),
    ("10時ごろにつながらなくなり、11時に元に戻りました。", "10時ごろに接続障害が発生し、11時に復旧しました。"),
)


class IncidentStiffnessTest(unittest.TestCase):
    def test_incident_is_a_reference_doc_type(self):
        self.assertEqual(tuple(yomiyasu_diff.STIFFNESS_INFO_DOC_TYPES), ("incident", "formal"))

    def test_incident_candidates_are_info(self):
        for before, after in INCIDENT_PAIRS:
            with self.subTest(before=before):
                result = result_of(before, after, doc_type="incident")
                section = result["stiffness"]
                self.assertTrue(section["candidates"])
                self.assertEqual(section["level"], "info")
                self.assertEqual({c["level"] for c in section["candidates"]}, {"info"})
                lines = section_lines(result, "stiffness")
                self.assertTrue(lines[0].startswith("■ 文体の硬化（参考 "), lines[0])
                self.assertIn("文書の種類 incident では硬い言い方が普通なので、参考として出しています", lines[0])

    def test_without_type_they_are_review(self):
        for before, after in INCIDENT_PAIRS:
            with self.subTest(before=before):
                section = stiffness_of(before, after)
                self.assertTrue(section["candidates"])
                self.assertEqual({c["level"] for c in section["candidates"]}, {"review"})


# ---- fp の P3: 文書全体の候補は、変わった文の組が2つ以上のときだけ ----
ONE_PAIR_REWRITES = (
    # 意味の取れない比喩の主語を、持つ手に直した（1文だけの直し。合成の文）
    ("担いだ桶の、縄が真っ先に重さに負けていく。", "担いだ桶の、縄を持つ両手の指が真っ先に重さに負けていく。", "essay"),
    # 比喩で隠した中身を具体的に書いた（1文だけの直し。合成の文）
    ("表示の速さは、台数を増やさずに順番を整えて生み出したものです。",
     "画面の表示の速さは、サーバーの台数と性能を増やさずに、処理の順番と読み込む単位を整えて出したものです。", None),
    # IC-ok14（2段落のうち1文だけを直した）
    ("ジョブが悲鳴を上げていた。\n\n夜間のバッチ処理が、予定の三倍の時間をかけても終わらなかった。",
     "夜間のバッチ処理が遅れていた。\n\n夜間のバッチ処理が、予定の三倍の時間をかけても終わらなかった。", "incident"),
)
# 2文を少しずつ硬くした推敲（どちらの文も1文の条件には当たらない。文書全体の条件で拾う）
TWO_PAIRS_STIFF = ("設定を見直したので、待ち時間が減りました。来週も同じやり方で進めます。",
                   "設定を見直したので、待ち時間が減少しました。来週も同様のやり方で進めます。")


class DocumentStiffnessTest(unittest.TestCase):
    def test_one_changed_pair_has_no_document_candidate(self):
        for before, after, doc_type in ONE_PAIR_REWRITES:
            for typed in (None, doc_type):
                with self.subTest(before=before, doc_type=typed):
                    found = [c["subkind"] for c in stiffness_of(before, after, doc_type=typed)["candidates"]]
                    self.assertNotIn("document", found)
                    self.assertEqual(found, [])

    def test_two_changed_pairs_still_give_a_document_candidate(self):
        section = stiffness_of(*TWO_PAIRS_STIFF)
        self.assertEqual([c["subkind"] for c in section["candidates"]], ["document"])


# ---- fp の P7: 補足カッコを外しただけの「の」の連続 ----
class ChainNounsTest(unittest.TestCase):
    def test_nouns_all_in_the_paired_original_sentence(self):
        cases = (
            ("営業部（東京本社）の今期の売上は、前年より伸びました。", "東京本社の営業部の今期の売上は、前年より伸びました。", "article"),
            ("新宿区（東京都）の住民を対象にした調査です。", "東京都の新宿区の住民を対象にした調査です。", None),
        )
        for before, after, doc_type in cases:
            for typed in (None, doc_type):
                with self.subTest(before=before, doc_type=typed):
                    found = [c["subkind"] for c in stiffness_of(before, after, doc_type=typed)["candidates"]]
                    self.assertNotIn("no_chain", found)

    def test_a_new_noun_in_the_chain_is_still_found(self):
        section = stiffness_of("今期の売上は、前年より伸びました。", "営業部の今期の売上は、前年より伸びました。")
        [chain] = [c for c in section["candidates"] if c["subkind"] == "no_chain"]
        self.assertEqual(chain["detail"]["chains"], ["営業部の今期の売上"])

    def test_addendum_example_is_still_found(self):
        section = stiffness_of("申請の手順を減らせないか、総務部で検討します。", "申請手続き簡素化の検討の実施。")
        self.assertIn("no_chain", [c["subkind"] for c in section["candidates"]])


# ---- spec の F12: 平均の文の長さの表示 ----
def document_candidate(old_ratio, new_ratio, old_avg, new_avg):
    return {"kind": "stiffness", "subkind": "document", "old_line": None, "new_line": None, "old": None, "new": None,
            "level": "review", "detail": {"old_kanji_ratio": old_ratio, "new_kanji_ratio": new_ratio,
                                          "old_avg_length": old_avg, "new_avg_length": new_avg, "example": None}}


class AverageLengthDisplayTest(unittest.TestCase):
    SAME_SHOWN = re.compile(r"平均の文の長さが(\d+)字から\1字に増えました")

    def test_rounded_values_decide_the_wording(self):
        line = yomiyasu_diff._stiffness_line(document_candidate(32.0, 42.0, 17.6, 18.4))
        self.assertIsNone(self.SAME_SHOWN.search(line), line)
        self.assertTrue(line.startswith("推敲後、漢字の割合が32%から42%に増えました（平均の文の長さは18字のまま）。"), line)

    def test_shown_increase(self):
        line = yomiyasu_diff._stiffness_line(document_candidate(32.0, 42.0, 17.4, 18.6))
        self.assertTrue(line.startswith("推敲後、漢字の割合が32%から42%に、平均の文の長さが17字から19字に増えました。"), line)

    def test_shown_decrease(self):
        line = yomiyasu_diff._stiffness_line(document_candidate(32.0, 42.0, 20.0, 15.0))
        self.assertTrue(line.startswith("推敲後、漢字の割合が32%から42%に増えました（平均の文の長さは20字から15字）。"), line)

    def test_spec_example_does_not_show_the_same_value_as_an_increase(self):
        result = result_of(*INCIDENT_PAIRS[0])
        report = yomiyasu_diff.report(result)
        self.assertIsNone(self.SAME_SHOWN.search(report), report)


# ---- fp の P4: 種類を指定して promo でないとき、絵文字と見出しは参考 ----
EMOJI_SLIDE = ("## 来期の方針🎯\n\n問い合わせの多い画面から直します✅", "## 来期の方針\n\n問い合わせの多い画面から直します。")
LONG_HEADING = ("## 検索が遅くなっていた本当の原因は、実はインデックスの不足にあった\n\n商品の数が増えたのに、索引を足していませんでした。",
                "## 検索が遅かった原因\n\n商品の数が増えたのに、索引を足していませんでした。")
EMOJI_AND_EXCLAMATION = ("## 来期の方針🎯\n\n問い合わせの多い画面から直します！", "## 来期の方針\n\n問い合わせの多い画面から直します。")
ESSAY_EMOJI = ("公園のベンチに座ると🌸、桜がもう散り始めていた。", "公園のベンチに座ると、桜がもう散り始めていた。")
TYPED_NOT_PROMO = tuple(value for value in DOC_TYPES if value != "promo")


class TypedEmojiHeadingTest(unittest.TestCase):
    def test_typed_emoji_and_heading_are_info(self):
        for before, after, subkind in ((EMOJI_SLIDE[0], EMOJI_SLIDE[1], "emoji"), (LONG_HEADING[0], LONG_HEADING[1], "heading"),
                                       (ESSAY_EMOJI[0], ESSAY_EMOJI[1], "emoji")):
            for doc_type in TYPED_NOT_PROMO:
                if subkind == "heading" and doc_type == "minutes":
                    # 議事録の推敲では見出しを変えないので、見出しの候補は見直し候補のまま（反証で見つけた例。
                    # tests/test_v200_fix_round1.py の MinutesHeadingTest）
                    continue
                with self.subTest(subkind=subkind, doc_type=doc_type):
                    section = tone_of(before, after, doc_type=doc_type)
                    self.assertEqual(levels(section), [(subkind, "info")])
                    self.assertEqual(section["level"], "info")

    def test_no_type_and_promo_stay_review(self):
        for before, after in (EMOJI_SLIDE, LONG_HEADING, ESSAY_EMOJI):
            for doc_type in (None, "promo"):
                with self.subTest(before=before, doc_type=doc_type):
                    section = tone_of(before, after, doc_type=doc_type)
                    self.assertTrue(section["candidates"])
                    self.assertEqual({c["level"] for c in section["candidates"]}, {"review"})
                    self.assertEqual(section["level"], "review")

    def test_report_for_typed_info_only(self):
        result = result_of(*EMOJI_SLIDE, doc_type="slides")
        lines = section_lines(result, "tone")
        # 参考の理由の文は、参考になった候補（ここでは絵文字だけ）の決まりだけを書く（反証で見つけた例）
        self.assertEqual(lines[0], "■ 勢い（参考 1件。文書の種類 slides では絵文字を外すのが決まりなので、参考として出しています）")
        self.assertTrue(lines[1].startswith("- （参考）原文の絵文字2個が、推敲後は0個になりました"), lines[1])
        self.assertEqual(yomiyasu_diff.detector_summary(result, "tone"), "参考1件")

    def test_mixed_review_and_info(self):
        result = result_of(*EMOJI_AND_EXCLAMATION, doc_type="slides")
        section = result["tone"]
        self.assertEqual(levels(section), [("exclamation", "review"), ("emoji", "info")])
        self.assertEqual(section["level"], "review")
        lines = section_lines(result, "tone")
        self.assertEqual(lines[0], "■ 勢い（見直し候補 1件、参考 1件。書き手の勢いを落としていないか確かめる）")
        self.assertTrue(lines[1].startswith("- 原文の「！」1個が"), lines[1])
        self.assertTrue([line for line in lines if line.startswith("- （参考）原文の絵文字1個が")], lines)
        self.assertEqual(yomiyasu_diff.detector_summary(result, "tone"), "候補1件、参考1件")

    def test_tone_info_types_keep_the_old_summary(self):
        self.assertEqual(yomiyasu_diff.detector_summary(result_of(*EMOJI_SLIDE, doc_type="incident"), "tone"), "参考1件")
        self.assertEqual(yomiyasu_diff.detector_summary(result_of(*EMOJI_SLIDE), "tone"), "候補1件")

    def test_reference_doc_types_keep_their_wording(self):
        result = result_of(*EMOJI_AND_EXCLAMATION, doc_type="incident")
        self.assertEqual(levels(result["tone"]), [("exclamation", "info"), ("emoji", "info")])
        lines = section_lines(result, "tone")
        # 2回目の反証の直し（反証で見つけた例）: 理由の文は参考にした候補（「！」と絵文字）に合わせる
        self.assertEqual(lines[0], "■ 勢い（参考 2件。文書の種類 incident では「！」や強める語を減らし、絵文字を外すのが正しい直し方の"
                                   "ことが多いので、参考として出しています）")
        self.assertEqual(yomiyasu_diff.detector_summary(result, "tone"), "参考2件")


class CheckRunLinesTest(CheckCase):
    """check run の「勢いの検査:」の行も、diff の detector_summary と同じ値（完了報告の確認の記録に写す値）。"""

    def detector_lines(self, lines):
        self.assertTrue(lines[4].startswith("記録: "), lines[:6])
        return lines[5:7]

    def test_typed_info_only_and_mixed(self):
        a, b, lines = self.run_pair(EMOJI_SLIDE[0] + "\n", EMOJI_SLIDE[1] + "\n", "--doc-type", "slides")
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 候補なし", "勢いの検査: 参考1件"])
        a, b, lines = self.run_pair(EMOJI_AND_EXCLAMATION[0] + "\n", EMOJI_AND_EXCLAMATION[1] + "\n", "--doc-type", "slides",
                                    names=("c.md", "d.md"))
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 候補なし", "勢いの検査: 候補1件、参考1件"])
        self.assertIn("■ 勢い（見直し候補 1件、参考 1件。書き手の勢いを落としていないか確かめる）", lines)
        path, record = self.record_from(lines)
        summary = self.check_entry(record, "diff")["summary"]
        self.assertEqual((summary["tone_candidate_count"], summary["tone_level"]), (2, "review"))
        # 1つ目の run と最終稿が同じなので、原文を付けて verify する
        verify = self.check("verify", "--source", a, "--final", b)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_incident_stiffness_is_reference(self):
        a, b, lines = self.run_pair(INCIDENT_PAIRS[0][0] + "\n", INCIDENT_PAIRS[0][1] + "\n", "--doc-type", "incident")
        self.assertEqual(self.detector_lines(lines), ["硬化の検査: 参考1件", "勢いの検査: 候補なし"])


# ---- fp の F9: 間接の問い ----
class IndirectQuestionTest(unittest.TestCase):
    def test_indirect_question_is_not_a_tone_candidate(self):
        cases = (
            ("佐藤さん: 予算は足りるのか？\n田中さん: 今の見積もりでは足りる。",
             "佐藤さんから、予算が足りるかとの質問があった。田中さんは、今の見積もりでは足りると答えた。", "minutes"),
            ("このまま進めてよいのか？", "このまま進めてよいかどうかを、全員で確かめた。", None),
            ("その機能は要るのか？", "その機能は要るのかという声があった。", None),
            ("来週までに直せるか？", "来週までに直せるかと聞かれた。", None),
        )
        for before, after, doc_type in cases:
            for typed in (None, doc_type):
                with self.subTest(before=before, doc_type=typed):
                    result = result_of(before, after, doc_type=typed)
                    self.assertNotIn("question", [c["subkind"] for c in result["tone"]["candidates"]])

    def test_sentence_type_risk_is_unchanged(self):
        """問いの文が問いでなくなった恐れ（sentence_type/question）はこの直しの範囲の外で、今までどおり出る。"""
        result = result_of("佐藤さん: 予算は足りるのか？\n田中さん: 今の見積もりでは足りる。",
                           "佐藤さんから、予算が足りるかとの質問があった。田中さんは、今の見積もりでは足りると答えた。", "minutes")
        self.assertIn(("sentence_type", "question"), [(r["kind"], r["subkind"]) for r in result["meaning_risks"]])

    def test_plain_statement_is_still_a_candidate(self):
        for before, after in (("予算は足りるのか？", "予算は足りる。"), ("なぜ遅いのでしょうか？", "遅い理由を調べました。"),
                              ("ほかと比べてどうですか？", "ほかと比べた結果を示します。")):
            with self.subTest(before=before):
                self.assertEqual(levels(tone_of(before, after)), [("question", "review")])


# ---- spec の F2: 番号つき項目の行と太字だけの行の見出し（promo のときだけ数える）----
PROMO_TITLE = "# 港町のスーパーで探す最強のお土産！安くて美味いご当地ラーメン4選"
PROMO_H1 = "1. 昭和から愛される港町のソウルフード「しおかぜラーメン」（なぎさ製麺）"
PROMO_H1_SHORT = "1. しおかぜラーメン（なぎさ製麺）"
PROMO_H2 = "2. 焦がしニンニク油が香る本格派「灯台とんこつラーメン」（なぎさ製麺）"
PROMO_H2_SHORT = "2. 灯台とんこつラーメン（なぎさ製麺）"


def promo_article(first, second, wrap=lambda text: text):
    return "\n".join([PROMO_TITLE, "", "港町のスーパーには、手頃でおいしいご当地ラーメンがずらりと並んでいます。", "",
                      wrap(first), "", "甘めのとんこつスープで、子どもにも人気です。", "",
                      wrap(second), "", "焦がしニンニク油のパンチを自宅で味わうなら、この一袋がおすすめです。", "",
                      "## まとめ", "", "自宅用にも配り用にも大活躍するおすすめ銘柄です。ぜひ探してみてください！", ""])


def bold(text):
    return "**" + text + "**"


# 勢いの文書1章の表の2組目と3組目を、文書のとおりの形（番号つき項目の行、太字だけの行）で書いたもの
PSEUDO_HEADING_PAIRS = (
    ("numbered", promo_article(PROMO_H1, PROMO_H2), promo_article(PROMO_H1_SHORT, PROMO_H2_SHORT)),
    ("bold_numbered", promo_article(PROMO_H1, PROMO_H2, bold), promo_article(PROMO_H1_SHORT, PROMO_H2_SHORT, bold)),
    ("bold", promo_article(PROMO_H1[3:], PROMO_H2[3:], bold), promo_article(PROMO_H1_SHORT[3:], PROMO_H2_SHORT[3:], bold)),
)
# 番号つきの手順を短くした正しい推敲（マニュアル）
STEPS = ("## 設定の手順\n\n"
         "1. まず最初に、画面の右上にある歯車の形をしたアイコンを押して、設定の画面を開いてください。\n"
         "2. 次に、表示された一覧の中から「通知」という名前の項目を探して、その項目を選んでください。\n"
         "3. 最後に、画面のいちばん下にある「保存」と書かれたボタンを押せば、設定は完了となります。\n",
         "## 設定の手順\n\n"
         "1. 右上の歯車のアイコンを押し、設定の画面を開きます。\n"
         "2. 一覧から「通知」を選びます。\n"
         "3. いちばん下の「保存」を押します。\n")
# 太字だけの行のラベルを本文にまとめた正しい推敲（障害報告）
BOLD_LABELS = ("# 障害報告書\n\n**原因**\n\n設定の誤りでした。\n\n**対応**\n\n設定を戻しました。\n\n**再発防止**\n\n手順書を直します。\n",
               "# 障害報告書\n\n原因は設定の誤りでした。設定を戻して復旧し、再発を防ぐために手順書を直します。\n")


class PseudoHeadingTest(unittest.TestCase):
    """紹介記事・宣伝文（--doc-type promo）では、番号つき項目の行（「1. …」）と太字だけの行（「**…**」）も見出しに数える。
    種類なしとほかの種類では数えない（コーパス48組の、番号つきの一覧を文章にした推敲と太字のラベルを外した推敲で、
    見出しの候補が4組に出たため）。"""

    def test_promo_counts_numbered_and_bold_lines(self):
        for name, before, after in PSEUDO_HEADING_PAIRS:
            with self.subTest(form=name):
                section = tone_of(before, after, doc_type="promo")
                self.assertEqual(levels(section), [("heading", "review")])
                self.assertLess(section["candidates"][0]["detail"]["new"], section["candidates"][0]["detail"]["old"] * 0.7)

    def test_not_counted_without_promo(self):
        """拾えない形（限界）: 種類なしとほかの種類では、番号つき項目と太字だけの行を縮めても見出しの候補にしない。"""
        for name, before, after in PSEUDO_HEADING_PAIRS:
            for doc_type in (None,) + TYPED_NOT_PROMO:
                with self.subTest(form=name, doc_type=doc_type):
                    self.assertNotIn("heading", [c["subkind"] for c in tone_of(before, after, doc_type=doc_type)["candidates"]])

    def test_correct_rewrites_of_lists_and_labels(self):
        for before, after, doc_type in ((STEPS[0], STEPS[1], "manual"), (BOLD_LABELS[0], BOLD_LABELS[1], "incident")):
            for typed in (None, doc_type):
                with self.subTest(before=before[:12], doc_type=typed):
                    self.assertNotIn("heading", [c["subkind"] for c in tone_of(before, after, doc_type=typed)["candidates"]])

    def test_promo_keeping_the_lines_has_no_candidate(self):
        before = promo_article(PROMO_H1, PROMO_H2)
        after = before.replace("子どもにも人気", "子どもにも大人気")
        self.assertEqual(tone_of(before, after, doc_type="promo")["candidates"], [])
        made_heading = before.replace(PROMO_H1, "## " + PROMO_H1).replace(PROMO_H2, "## " + PROMO_H2)
        self.assertEqual(tone_of(before, made_heading, doc_type="promo")["candidates"], [])


# ---- spec の F11: 候補の行の抜き出し ----
LONG_LINE = ("もちろん、これは仕事がなくなることを意味しません。日々の開発に地味に効いてきます。ぜひ参考にしてみてください！",
             "導入によって作業そのものがなくなるわけではありません。日々の開発の手間が少しずつ減り、提供の速さにつながります。")
TAIL_CUT = ("このツールは、毎日の作業を楽にしてくれる便利なツールです。いかがでしたか？参考になれば幸いです。ぜひご活用ください。",
            "このツールは、毎日の作業を楽にしてくれる便利なツールです。")


class ExcerptTest(unittest.TestCase):
    PLACE = re.compile(r"『([^』]*)』")

    def test_excerpt_is_around_the_mark(self):
        section = tone_of(*LONG_LINE)
        for candidate in section["candidates"]:
            with self.subTest(subkind=candidate["subkind"]):
                old, new = candidate["old"], candidate["new"]
                self.assertLessEqual(len(old), 45, old)
                self.assertLessEqual(len(new), 45, new)
                self.assertTrue(new.strip("…"), new)
        [mark] = [c for c in section["candidates"] if c["subkind"] == "exclamation"]
        self.assertIn("！", mark["old"])
        [word] = [c for c in section["candidates"] if c["subkind"] == "intensifier"]
        self.assertIn("ぜひ", word["old"])

    def test_excerpt_keeps_the_sentence_of_the_mark(self):
        """抜き出しは、印の前の文の終わり（。！？）のあとから始め、印のあとの最初の文の終わりで止める（前後20字の中で）。"""
        section = tone_of(*LONG_LINE)
        found = dict((c["subkind"], c["old"]) for c in section["candidates"])
        self.assertEqual(found, {"exclamation": "…ぜひ参考にしてみてください！", "intensifier": "…ぜひ参考にしてみてください！"})
        question = [c for c in tone_of(*TAIL_CUT)["candidates"] if c["subkind"] == "question"][0]
        self.assertEqual(question["old"], "…いかがでしたか？…")

    def test_no_empty_excerpt(self):
        result = result_of(*TAIL_CUT)
        report = yomiyasu_diff.report(result)
        self.assertNotIn("『』", report)
        for candidate in result["tone"]["candidates"]:
            with self.subTest(subkind=candidate["subkind"]):
                self.assertTrue(candidate["new"])
                self.assertTrue(candidate["new"].endswith("便利なツールです。"), candidate["new"])
                self.assertLessEqual(len(candidate["old"]), 45, candidate["old"])

    def test_every_place_is_listed(self):
        before = "\n\n".join(["一つ目です！", "二つ目です！", "三つ目です！"])
        after = "\n\n".join(["一つ目です。", "二つ目です。", "三つ目です。"])
        lines = section_lines(result_of(before, after), "tone")
        self.assertEqual(lines[1], "- 原文の「！」3個が、推敲後は0個になりました（1行目『一つ目です！』→『一つ目です。』）。" + TAIL)
        self.assertEqual(lines[2:], ["  3行目『二つ目です！』→『二つ目です。』", "  5行目『三つ目です！』→『三つ目です。』"])

    def test_places_over_the_limit(self):
        before = "\n\n".join("{}番目です！".format(n) for n in range(1, 8))
        after = "\n\n".join("{}番目です。".format(n) for n in range(1, 8))
        lines = section_lines(result_of(before, after), "tone")
        self.assertEqual(lines[1], "- 原文の「！」7個が、推敲後は0個になりました（1行目『1番目です！』→『1番目です。』）。" + TAIL)
        self.assertEqual(lines[2:], ["  3行目『2番目です！』→『2番目です。』", "  5行目『3番目です！』→『3番目です。』",
                                     "  7行目『4番目です！』→『4番目です。』", "  9行目『5番目です！』→『5番目です。』",
                                     "  ほか2か所"])

    def test_deleted_line_place(self):
        before = "残す行です。\n\n消す行です！\n\nもう一つ消します！"
        after = "残す行です。"
        lines = section_lines(result_of(before, after), "tone")
        self.assertEqual(lines[1], "- 原文の「！」2個が、推敲後は0個になりました（元3行目『消す行です！』を削除）。" + TAIL)


# ---- spec の F14 の一部: コーパス48組で硬化と勢いの候補は0件 ----
def corpus_pairs():
    pairs = []
    for name in sorted(os.listdir(str(CORPUS / "yomiyasu_rewritten"))):
        if not name.endswith(".md"):
            continue
        source = CORPUS / "blacklist_ai" / (name[:-6] + ".md") if name.endswith("_bl.md") else CORPUS / "raw_ai" / name
        pairs.append((source.read_bytes().decode("utf-8"),
                      (CORPUS / "yomiyasu_rewritten" / name).read_bytes().decode("utf-8"), name))
    return pairs


class CorpusDetectorWatchTest(unittest.TestCase):
    """コーパス48組は yomiyasu の正しい推敲なので、硬化と勢いの候補は0件（目標 3.6 の1と2の根拠の値）。増えたら誤検出が
    増えたことになる。"""

    def test_corpus_48_pairs_have_no_stiffness_or_tone_candidate(self):
        pairs = corpus_pairs()
        self.assertEqual(len(pairs), 48)
        found = {}
        for before, after, name in pairs:
            result = yomiyasu_diff.diff(before, after)
            for key in ("stiffness", "tone"):
                for candidate in result[key]["candidates"]:
                    found.setdefault(key, []).append((name, candidate["subkind"]))
        self.assertEqual(found, {})


if __name__ == "__main__":
    unittest.main()
