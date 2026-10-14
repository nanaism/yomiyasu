#!/usr/bin/env python3
"""v2.0.0（diff の詰めの直しのあとの反証、2回目の直し）。

2回目の反証（仕様の T1〜T7、誤検出の指摘1〜8（下では R2-1〜R2-8）、後戻りの V1〜V4）の指摘のうち、
判断の要らないものを直した。文はすべて合成の文（反証の担当の再現の入力と同じ文と、それを言い換えた文）。
実在の会社や商品の名前は使わない。

- 文書（T1、T2、T6、T7）: rephrase-test.md 3章の4の検出の説明と拾えない語、SKILL.md「案内用の見出し」の議事録の見出し、
  promo の箇条書きの太字の行、種類を直したときの --new-run。
- 勢い（T3、R2-8）: 参考の5種類の理由の文を、参考にした候補に合わせる。--doc-type のヘルプの「残すだけで」をやめる。
  間接の問いの「かとお問い合わせ」「かとよく聞かれ」「かとご相談」。
- 記録（T4）: diff の summary に、見直し候補（level が review）の数を足す。
- 数値（T5、R2-5、R2-6、V1、V2、V3）: 漢数字の範囲の前の数、時間の「二分」「十二分」「五分」、「一つもしくは」「一つもって」、
  日付の月と日・時刻の時と分の入れ替え、範囲を1つの値に縮めた書き換え。
- 否定対比の逆転（R2-1〜R2-4）: A を下げたままの言い換え、B の句の語で否定する語、両方を確かめた形、B の句の言い換え。
- 気持ちの語（R2-7）: 人の名前や呼び名のあとの「落ち込む」。
- 速さ（V4）: 続く文に移った値の似かたの比べ。
"""

from collections import Counter, namedtuple
from pathlib import Path
import difflib
import importlib.util
import os
import re
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import CheckCase, ROOT, SCRIPTS, split_lines  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402

REFERENCES = ROOT / "references"


def result_of(before, after, doc_type=None):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after, doc_type=doc_type)


def reversal_words(before, after, doc_type=None):
    return [risk["detail"]["word"] for risk in result_of(before, after, doc_type)["meaning_risks"]
            if risk["kind"] == "contrast_reversal"]


def feeling_words(before, after, doc_type=None):
    return [word for risk in result_of(before, after, doc_type)["meaning_risks"] if risk["kind"] == "feeling"
            for word in risk["detail"]["words"]]


def number_risks(before, after, doc_type=None):
    return [(risk["subkind"], risk["detail"]["removed"], risk["detail"]["added"])
            for risk in result_of(before, after, doc_type)["meaning_risks"] if risk["kind"] == "number"]


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


def help_text(*args):
    process = subprocess.run([sys.executable, "-B"] + [str(arg) for arg in args], capture_output=True,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=30)
    # argparse は長い日本語の文を字の途中で折り返すので、空白と改行を除いて探す
    return "".join(process.stdout.decode("utf-8").split())


# ---- T1: rephrase-test.md 3章の4（検出の説明と、拾えない平仮名の入る語）----
class RephraseTestWordingTest(unittest.TestCase):
    """3回目の直しで、否定対比の名詞に平仮名の入る語（見た目、使い方、締め切り）も取るようにした。文書もそれに合わせ、
    拾えない語は平仮名で始まる語（お知らせ）とする（反証で見つけた例: 文書が古い動きのままだった）。"""

    def test_detection_is_described_like_review_points(self):
        text = section_text(REFERENCES / "rephrase-test.md", "## 3. 否定対比（AではなくB）")
        item = [line for line in text.split("\n") if line.startswith("4. ")][0]
        for word in ("並べて肯定", "AとB", "Aに加えてB", "AだけでなくB", "平仮名で始まる語", "お知らせ"):
            with self.subTest(word=word):
                self.assertIn(word, item)
        self.assertNotIn("否定していた語が「目的」「重視」「まず」などの語と同じ文に出たときに見直し候補を出す", item)
        self.assertNotIn("平仮名の入る語は拾えない", item)

    def test_wrong_fix_example_says_diff_finds_it(self):
        text = section_text(REFERENCES / "rephrase-test.md", "### 直し方を誤った例（合成）")
        row = [line for line in text.split("\n") if line.startswith("| 見た目ではなく")][0]
        self.assertIn("diff", row)
        self.assertIn("否定対比の主張が逆になった恐れ", row)
        self.assertNotIn("候補に出ない", row)

    def test_wrong_fix_example_matches_the_diff(self):
        """文書の例を今の diff に通すと、文書のとおり逆転の候補が出る。"""
        self.assertEqual(reversal_words("見た目ではなく、読み込みの速さを優先した。", "見た目と読み込みの速さを優先した。"),
                         ["見た目"])


class HiraganaNounKnownLimitTest(unittest.TestCase):
    """平仮名の入る和語の名詞。3回目の直しで、否定対比の名詞に送り仮名として漢字の間の「た」「い」「め」「わ」を許し、見た目、
    使い方、締め切り、問い合わせ（比べには「問い合」を使い、候補には送り仮名までの「問い合わせ」を示す）を取るようにした
    （test_v200_fix_round3.HiraganaNounContrastTest、ShownWordTest）。平仮名で始まる語（お知らせ）は今も取らない（拾えない形）。"""

    def test_hiragana_nouns_are_taken(self):
        for noun, word in (("見た目", "見た目"), ("使い方", "使い方"), ("締め切り", "締め切り"), ("問い合わせ", "問い合わせ")):
            with self.subTest(noun=noun):
                self.assertEqual(reversal_words("{}ではなく、読み込みの速さを優先した。".format(noun),
                                                "{}と読み込みの速さを優先した。".format(noun)), [word])

    def test_words_starting_with_hiragana_are_not_taken(self):
        self.assertEqual(reversal_words("お知らせではなく、読み込みの速さを優先した。", "お知らせと読み込みの速さを優先した。"), [])

    def test_kanji_and_katakana_nouns_are_taken(self):
        for noun in ("デザイン", "外観"):
            with self.subTest(noun=noun):
                self.assertEqual(reversal_words("{}ではなく、読み込みの速さを優先した。".format(noun),
                                                "{}と読み込みの速さを優先した。".format(noun)), [noun])


# ---- T2: 議事録の見出し（SKILL.md「案内用の見出し」。beta の gemini-syntax.md 原則15 は SKILL.md のこの節に移った）----
class MinutesHeadingPrincipleTest(unittest.TestCase):
    def test_guide_headings_keep_minutes_headings(self):
        text = section_text(ROOT / "skills" / "yomiyasu" / "SKILL.md", "### 案内用の見出し")
        lines = [line for line in text.split("\n") if "議事録を推敲する" in line]
        self.assertEqual(len(lines), 1, text)
        self.assertIn("見出し", lines[0])
        self.assertIn("domains/business.md", lines[0])


# ---- T3: 参考の5種類の理由の文と、--doc-type のヘルプ ----
PR_EMOJI = ("## 概要\n\nログの出力先を変えました🎉\n\n## 確認したこと\n\n手元で動かしました。",
            "## 概要\n\nログの出力先を変えました。\n\n## 確認したこと\n\n手元で動かしました。")
INCIDENT_HEADING = ("# 障害報告：決済が止まった件についての詳しい経過と今後の対応\n\n決済が止まりました。",
                    "# 障害報告：決済の停止\n\n決済が止まりました。")
MIXED = ("# 新しい手順🚀\n\nこの手順で作業がとても楽になります！", "# 新しい手順\n\nこの手順で作業が楽になります。")
INCIDENT_EXCLAMATION = ("復旧しました！", "復旧しました。")


def tone_head(pair, doc_type):
    return yomiyasu_diff.report_parts(result_of(*pair, doc_type=doc_type))["tone"].split("\n")[0]


class InfoTypeReasonTest(unittest.TestCase):
    def test_reason_follows_the_candidates(self):
        cases = ((PR_EMOJI, "pr", "■ 勢い（参考 1件。文書の種類 pr では絵文字を外すのが正しい直し方のことが多いので、参考として出しています）"),
                 (PR_EMOJI, "formal",
                  "■ 勢い（参考 1件。文書の種類 formal では絵文字を外すのが正しい直し方のことが多いので、参考として出しています）"),
                 (INCIDENT_HEADING, "incident",
                  "■ 勢い（参考 1件。文書の種類 incident では見出しを短い項目名にするのが正しい直し方のことが多いので、"
                  "参考として出しています）"),
                 (MIXED, "pr",
                  "■ 勢い（参考 3件。文書の種類 pr では「！」や強める語を減らし、絵文字を外すのが正しい直し方のことが多いので、"
                  "参考として出しています）"))
        for pair, doc_type, head in cases:
            with self.subTest(doc_type=doc_type, head=head):
                self.assertEqual(tone_head(pair, doc_type), head)

    def test_exclamation_only_keeps_the_sentence(self):
        self.assertEqual(tone_head(INCIDENT_EXCLAMATION, "incident"),
                         "■ 勢い（参考 1件。文書の種類 incident では「！」や強める語を減らすのが正しい直し方のことが多いので、"
                         "参考として出しています）")


class DocTypeHelpOpeningTest(unittest.TestCase):
    def test_diff_help_does_not_say_only_kept(self):
        text = help_text(SCRIPTS / "yomiyasu_diff.py", "-h")
        self.assertNotIn("表示とJSONに残すだけで、差分", text)
        self.assertIn("表示とJSONに残し、差分、意味が変わる恐れ、規則の見直し候補、--fail-onは変わりません", text)


# ---- T4: 記録の diff の summary の見直し候補の数 ----
SLIDES_MIXED = ("# 新しい手順🚀\n\nこの手順で作業がとても楽になります！\n", "# 新しい手順\n\nこの手順で作業が楽になります。\n")


def load_check_module():
    spec = importlib.util.spec_from_file_location("check_module_fix2", str(SCRIPTS / "yomiyasu_check.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordReviewCountTest(CheckCase):
    def test_summary_has_review_counts(self):
        a, b, lines = self.run_pair(*SLIDES_MIXED, "--doc-type", "slides")
        self.assertIn("勢いの検査: 候補2件、参考1件", lines)
        path, record = self.record_from(lines)
        summary = self.check_entry(record, "diff")["summary"]
        self.assertEqual((summary["tone_candidate_count"], summary["tone_review_count"], summary["tone_level"]), (3, 2, "review"))
        self.assertEqual((summary["stiffness_candidate_count"], summary["stiffness_review_count"]), (0, 0))
        verify = self.check("verify", "--final", b, "--replay")
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_info_only_has_zero_review_count(self):
        a, b, lines = self.run_pair(*PR_EMOJI_FILES, "--doc-type", "pr")
        path, record = self.record_from(lines)
        summary = self.check_entry(record, "diff")["summary"]
        self.assertEqual((summary["tone_candidate_count"], summary["tone_review_count"], summary["tone_level"]), (1, 0, "info"))

    def test_changed_review_count_is_invalid(self):
        a, b, lines = self.run_pair(*SLIDES_MIXED, "--doc-type", "slides")
        path, record = self.record_from(lines)
        self.check_entry(record, "diff")["summary"]["tone_review_count"] = 3
        module = load_check_module()
        record["record_digest"] = module._record_digest(record)
        self.save_record(path, record)
        verify = self.check("verify", "--final", b)
        self.assertNotEqual(verify.returncode, 0, verify.stdout)
        self.assertIn("invalid_record", verify.stdout)


PR_EMOJI_FILES = (PR_EMOJI[0] + "\n", PR_EMOJI[1] + "\n")


# ---- T5: 漢数字の範囲を算用数字にした書き換え ----
KANJI_RANGE_KEEP = (
    ("作業は三〜五日かかります。", "作業は3〜5日かかります。"),
    ("説明は二〜三回行う。", "説明は2〜3回行う。"),
    ("参加は十〜二十人です。", "参加は10〜20人です。"),
    ("作業は三、四日かかる。", "作業は3、4日かかる。"),
    ("作業は三から五日かかる。", "作業は3から5日かかる。"),
    ("作業は三・四日かかる。", "作業は3・4日かかる。"),
    ("作業は3〜5日かかります。", "作業は三〜五日かかります。"),
    ("作業は三〜五日かかります。", "作業は3日から5日かかります。"),
)


class KanjiRangeTest(unittest.TestCase):
    def test_notation_only_is_not_a_candidate(self):
        for before, after in KANJI_RANGE_KEEP:
            with self.subTest(before=before, after=after):
                result = result_of(before, after)
                self.assertEqual([r for r in result["meaning_risks"] if r["kind"] == "number"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_changed_ranges_are_still_found(self):
        for before, after, wanted in (("作業は三〜五日かかります。", "作業は3〜7日かかります。", [("replaced", ["五日"], ["7日"])]),
                                      ("作業は三〜五日かかります。", "作業は三〜七日かかります。", [("replaced", ["五日"], ["七日"])]),
                                      ("作業は三〜五日かかります。", "作業は5日かかります。", [("lost", ["三"], [])]),
                                      ("説明は二〜三回行う。", "説明は1〜3回行う。", [("replaced", ["二"], ["1"])])):
            with self.subTest(after=after):
                self.assertEqual(number_risks(before, after), wanted)

    def test_kanji_in_words_is_not_taken(self):
        """直前が漢字（統一、唯一）の漢数字は、範囲の前の数としても取らない（2.5.2 の直前の字の決まり）。"""
        values = [(item["value"], item["unit"]) for item in yomiyasu_diff.extract_numbers("統一、二日目に集まる。唯一から三年。")]
        self.assertEqual(values, [("2", "日"), ("3", "年")])
        values = [(item["value"], item["unit"]) for item in yomiyasu_diff.extract_numbers("作業は三〜五日、説明は二、三回。")]
        self.assertEqual(values, [("3", ""), ("5", "日"), ("2", ""), ("3", "回")])


# ---- T6: promo の箇条書きの太字の行（数えない形を文書に書く）----
BULLET_BOLD = ("港町で食べたいラーメンを集めました。\n\n- **昭和から愛される港町の醤油ラーメン**\n"
               "- **濃厚スープがクセになる灯台とんこつラーメン**\n\n脂が多めです。",
               "港町で食べたいラーメンを集めました。\n\n- **醤油ラーメン**\n- **とんこつラーメン**\n\n脂が多めです。")


class PromoBulletBoldTest(unittest.TestCase):
    def test_bullet_bold_lines_are_not_counted(self):
        self.assertEqual(result_of(*BULLET_BOLD, doc_type="promo")["tone"]["candidates"], [])

    def test_documents_say_bullet_bold_lines_are_not_counted(self):
        for path, heading in ((REFERENCES / "doc-types" / "promo.md", "## 1. 普通な書き方（直さない）"),
                              (REFERENCES / "review-points.md", "### ■ 勢い")):
            with self.subTest(path=path.name):
                self.assertIn("箇条書きの太字の行", section_text(path, heading))


# ---- T7: 種類を直したときの run のやり直し ----
class AudienceNewRunTest(unittest.TestCase):
    def test_section_12_names_new_run(self):
        lines = [line for line in section_text(REFERENCES / "audience.md", "## 12. 示し方").split("\n")
                 if "利用者が種類か読者を直したら" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("--new-run", lines[0])


# ---- R2-1: A を下げたままの言い換え ----
NEW_FEATURE = "優先するのは新機能ではなく、不具合の修正です。"
DEMOTED_KEEP = (
    (NEW_FEATURE, "新機能は今回のリリースでは見送り、不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能は来週まで保留し、不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能に関しては見送り、不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能の追加は次回からにし、今回は不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能は次の版まで見送り、不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能は年内は見送り、不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能への着手は見送り、不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能について今回は見送り、不具合の修正を優先します。", "article"),
    (NEW_FEATURE, "新機能をいま入れるのは避け、不具合の修正を優先します。", "article"),
    ("本規程の主な対象は契約社員ではなく、正社員である。", "本規程は正社員を主な対象とし、契約社員への適用は見送る。", "formal"),
    ("優先するのは原因の調査ではなく、復旧です。", "復旧を優先し、原因に関する調査は後日行います。", "incident"),
    ("重要なのはキャッシュではなく、計測です。", "キャッシュを本番で使うのは避け、まず計測を重要視します。", "article"),
)


class DemoteKeepTest(unittest.TestCase):
    def test_demoted_paraphrases_are_not_reversals(self):
        for before, after, doc_type in DEMOTED_KEEP:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_real_reversals_are_still_found(self):
        for after in ("新機能を最優先にし、不具合の修正は見送ります。", "最優先は新機能で、不具合の修正は後日とします。"):
            with self.subTest(after=after):
                self.assertEqual(reversal_words(NEW_FEATURE, after, "article"), ["新機能"])

    def test_known_limits(self):
        """除けない形（記録の限界。直したら、この試験を変える）: 「Aに手を付けるのは見送り」の「手を」は別の目的語に見える。
        「新機能は、今回は見送り」は読点で節が切れる（1回目の直しの前から）。"""
        self.assertEqual(reversal_words("最優先はリファクタリングではなく、不具合の修正です。",
                                        "不具合の修正を最優先にし、リファクタリングに手を付けるのは見送ります。", "pr"),
                         ["リファクタリング"])
        self.assertEqual(reversal_words(NEW_FEATURE, "新機能は、今回は見送り、不具合の修正を優先します。", "article"), ["新機能"])


# ---- R2-2: B の句の語で否定する語 ----
LEXICAL_IN_B = (
    ("このリリースの目的は性能改善ではなく、古いAPIの廃止です。", "このリリースの目的は性能改善と古いAPIの廃止です。", "性能改善", "article"),
    ("今回の改正の主眼は罰則の強化ではなく、手続きの廃止である。", "今回の改正の主眼は罰則の強化と手続きの廃止である。", "強化", "formal"),
    ("この設定の目的は自動更新ではなく、古い証明書の無効化です。", "この設定の目的は自動更新と古い証明書の無効化です。", "自動更新", "formal"),
    ("対策の中心は再起動ではなく、問題の機能の無効化です。", "対策の中心は再起動と問題の機能の無効化です。", "再起動", "incident"),
    ("一番お願いしたいのは値下げではなく、送料の据え置きです。", "一番お願いしたいのは値下げと送料の据え置きです。", "値下げ", None),
    ("本補助の主な対象は国内ではなく、海外の事業である。", "本補助の主な対象は国内外の事業である。", "国内", "formal"),
    ("主な対象は社内ではなく、社外の取引先です。", "主な対象は社内外の取引先です。", "社内", None),
)


class LexicalNegationInBTest(unittest.TestCase):
    def test_negating_word_of_the_coordinated_noun_does_not_hide_a_reversal(self):
        for before, after, word, doc_type in LEXICAL_IN_B:
            with self.subTest(after=after):
                self.assertIn(word, reversal_words(before, after, doc_type))

    def test_negated_coordination_is_still_not_a_reversal(self):
        for before, after in (("今回の改修の対象はAPIではなく、管理画面です。", "今回の改修は管理画面だけで、APIと認証は対象外です。"),
                              ("今回の改修の対象はAPIではなく、管理画面です。", "APIとCLIは今回の改修の範囲外です。"),
                              ("この規程の対象は役員と嘱託ではなく、従業員である。", "この規程は従業員を対象とし、役員と嘱託は対象外とする。")):
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, "formal"), [])


# ---- R2-3: 並べた2つを確かめた形 ----
CACHE = "原因はキャッシュではなく、DNSの設定でした。"


class CheckedBothTest(unittest.TestCase):
    def test_checking_both_is_not_a_reversal(self):
        for after in ("キャッシュとDNSの設定を順に確認し、原因はDNSの設定だと分かりました。",
                      "キャッシュとDNSの設定を再確認したところ、原因はDNSの設定でした。",
                      "キャッシュとDNSの設定が正しいか確認し、DNSの設定に誤りを見つけました。",
                      "キャッシュとDNSの設定も確認し、原因はDNSの設定だと分かりました。",
                      "キャッシュとDNSの設定は確認済みで、原因はDNSの設定でした。",
                      "キャッシュとDNSの設定を一つずつ確かめ、原因はDNSの設定だと分かりました。"):
            with self.subTest(after=after):
                self.assertEqual(reversal_words(CACHE, after, "incident"), [])

    def test_conclusions_are_still_found(self):
        for after in ("原因はネットワークと設定の誤りだと確認しました。", "原因はネットワークと設定の誤りだと再確認しました。",
                      "原因はネットワークと設定の誤りであることを確認しました。"):
            with self.subTest(after=after):
                self.assertEqual(reversal_words("原因はネットワークではなく、設定の誤りでした。", after, "incident"),
                                 ["ネットワーク"])


# ---- R2-4: B の句の言い換え ----
class BSidePhraseParaphraseTest(unittest.TestCase):
    def test_paraphrased_b_side_is_not_a_reversal(self):
        for before, after, doc_type in (("大事なのは道具ではなく、道具の使い方だ。", "大事なのは、道具をどう使うかだ。", "essay"),
                                        ("重要なのはデータの量ではなく、データの質です。", "重要なのは、質の高いデータを集めることです。",
                                         "article"),
                                        ("大切なのは紅茶ではなく、紅茶の淹れ方です。", "大切なのは、紅茶を丁寧に淹れることです。", "promo")):
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_a_itself_is_still_found(self):
        for before, after, word in (("大事なのは道具ではなく、道具の使い方だ。", "大事なのは道具そのものだ。", "道具"),
                                    ("重要なのはツールではなく、ツールの使い方です。", "重要なのはツールの性能です。", "ツール")):
            with self.subTest(after=after):
                self.assertIn(word, reversal_words(before, after))

    def test_known_limit_without_a_clue_word(self):
        """手がかりの語が残らない言い換え（実行時間 → どれだけ速く回せるか）は除けない（記録の限界）。"""
        self.assertEqual(reversal_words("重要なのはテストではなく、テストの実行時間です。", "重要なのは、テストをどれだけ速く回せるかです。",
                                        "pr"), ["テスト"])


# ---- R2-5: 時間の「二分」「十二分」「五分」 ----
TIME_MINUTES = (
    ("残り時間が二分しかないため、議題4は次回に回した。", "残り時間が2分しかないため、議題4は次回に回した。", "minutes"),
    ("タイマーが二分すぎたら火を止めます。", "タイマーが2分すぎたら火を止めます。", None),
    ("二分さえあれば終わります。", "2分さえあれば終わります。", None),
    ("発表の時間を十二分に縮めた。", "発表の時間を12分に縮めた。", "minutes"),
    ("駅から五分位です。", "駅から5分くらいです。", None),
)


class TimeMinutesTest(unittest.TestCase):
    def test_minutes_in_arabic_numerals_are_notation(self):
        for before, after, doc_type in TIME_MINUTES:
            with self.subTest(before=before):
                result = result_of(before, after, doc_type)
                self.assertEqual([r for r in result["meaning_risks"] if r["kind"] == "number"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_changed_minutes_show_the_old_value(self):
        self.assertEqual(number_risks("残り時間は二分しかありません。", "残り時間は5分しかありません。"),
                         [("replaced", ["二分"], ["5分"])])

    def test_idioms_alone_are_not_numbers(self):
        for before, after in (("参加者の意見は二分した。", "参加者の意見は分かれた。"), ("準備は十二分にできている。", "準備は十分にできている。"),
                              ("成功の見込みは五分五分だ。", "成功の見込みは半々だ。")):
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])


# ---- R2-6、V3: 「一つもしくは」「一つもって」 ----
class WeakOneMoTest(unittest.TestCase):
    def test_or_and_holding_still_count(self):
        for before, after, removed, doc_type in (("選べるプランは1つもしくは2つです。", "選べるプランは2つです。", ["1つ"], "formal"),
                                                 ("提出する書類は一つもしくは二つとする。", "提出する書類は二つとする。", ["一つ"], "formal"),
                                                 ("傘を一つもって出かけた。", "傘をもって出かけた。", ["一つ"], None),
                                                 ("対象を1つもしくは複数のファイルから選ぶ。", "対象を複数のファイルから選ぶ。", ["1つ"], None),
                                                 ("候補を1つもしくは2つ選ぶ。", "候補を2つ選ぶ。", ["1つ"], None)):
            with self.subTest(before=before):
                result = result_of(before, after, doc_type)
                self.assertEqual([(r["subkind"], r["detail"]["removed"]) for r in result["meaning_risks"] if r["kind"] == "number"],
                                 [("lost", removed)])
                self.assertGreater(result["fail_on_meaning_risk_count"], 0)

    def test_emphatic_negation_does_not_count(self):
        for before, after in (("エラーは一つも出ませんでした。", "エラーは出ませんでした。"), ("空には雲が一つもなかった。", "空には雲がなかった。"),
                              ("該当する記録は一つも見つかりませんでした。", "該当する記録は見つかりませんでした。"),
                              ("エラーは一つもなし。", "エラーはなし。")):
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])


# ---- R2-7: 人の名前や呼び名のあとの「落ち込む」 ----
class FeelingAfterNamesTest(unittest.TestCase):
    def test_names_before_ochikomu_are_feelings(self):
        for before, after in (("井上は何も言わずに部屋へ戻った。", "井上は落ち込んで、何も言わずに部屋へ戻った。"),
                              ("村上は返事をしなかった。", "村上は落ち込んで、返事をしなかった。"),
                              ("マークは窓の外を見ていた。", "マークは落ち込んだまま、窓の外を見ていた。"),
                              ("ルーカスは黙って皿を洗った。", "ルーカスは落ち込んで、黙って皿を洗った。"),
                              ("母上はその晩、口をきかなかった。", "母上は落ち込んで、その晩は口をきかなかった。"),
                              ("ゲストは帰り支度を始めた。", "ゲストは落ち込んだ様子で帰り支度を始めた。"),
                              ("チームメイトが黙っていた。", "チームメイトが落ち込んで黙っていた。")):
            with self.subTest(after=after):
                self.assertIn("落ち込", feeling_words(before, after, "essay"))

    def test_amount_drops_are_still_not_feelings(self):
        for before, after, doc_type in (("障害の間、スループットは半分に下がりました。", "障害の間、スループットは半分に落ち込みました。", "incident"),
                                        ("前年と比べて売上が減っています。", "前年と比べて売上の落ち込みが目立ちます。", "proposal"),
                                        ("アクセス数は半分に減った。", "アクセス数は半分に落ち込んだ。", "article"),
                                        ("問い合わせ件数が減った。", "問い合わせ件数の落ち込みが続いた。", "minutes"),
                                        ("夜間はトラフィックが減る。", "夜間はトラフィックが落ち込む。", "article"),
                                        ("更新のあと処理のパフォーマンスが下がった。", "更新のあと処理のパフォーマンスが落ち込んだ。", "incident"),
                                        ("今月はコストが下がった。", "今月はコストが落ち込んだ。", "proposal")):
            with self.subTest(after=after):
                self.assertEqual(feeling_words(before, after, doc_type), [])

    def test_list_file_and_builtin_list_match(self):
        rows = [line.split("\t") for line in read(REFERENCES / "lists" / "feelings.txt").split("\n")
                if line and not line.startswith("#")]
        self.assertEqual([tuple(row) for row in rows], [tuple(item) for item in yomiyasu_diff.BUILTIN_LISTS["feelings"]])


# ---- R2-8: 間接の問い ----
class IndirectQuestionWiderTest(unittest.TestCase):
    def test_honorific_and_adverb_forms_are_indirect_questions(self):
        for before, after, doc_type in (("「在宅勤務の日も交通費は出ますか？」とお問い合わせをいただきました。",
                                         "在宅勤務の日も交通費が出るかとお問い合わせをいただきました。", None),
                                        ("「予約なしでも入れますか？」とよく聞かれます。答えは、はい！です。",
                                         "予約なしでも入れるかとよく聞かれます。答えは、はい！です。", "promo"),
                                        ("「打ち合わせは来週でも大丈夫ですか？」とご相談をいただきました。",
                                         "打ち合わせが来週でも大丈夫かとご相談をいただきました。", None)):
            with self.subTest(after=after):
                self.assertNotIn("question", tone_subkinds(before, after, doc_type))

    def test_guess_and_adverb_are_still_not_indirect_questions(self):
        for before, after in (("このラーメン、食べてみたくなりませんか？", "このラーメンを食べてみたくなるかと思います。"),
                              ("残りはあとわずか？いいえ、まだ間に合います！", "残りはあとわずかとなりましたが、まだ間に合います！")):
            with self.subTest(after=after):
                self.assertIn("question", tone_subkinds(before, after, "promo"))


# ---- V1: 日付の月と日、時刻の時と分の入れ替え ----
SWAPPED = (
    ("提出の締め切りは3/4です。", "提出の締め切りは4月3日です。", ["3", "4"], ["4月", "3日"]),
    ("会議は10:30〜11:15です。", "会議は10時15分から11時30分です。", ["10", "30", "11", "15"], ["10時", "15分", "11時", "30分"]),
    ("公開日は2026/03/04です。", "公開日は2026年4月3日です。", ["2026", "03", "04"], ["2026年", "4月", "3日"]),
    ("開始は9:45です。", "開始は45時9分です。", ["9", "45"], ["45時", "9分"]),
)


class SwappedClusterTest(unittest.TestCase):
    def test_swapped_month_and_day_or_hour_and_minute_are_found(self):
        for before, after, removed, added in SWAPPED:
            with self.subTest(after=after):
                result = result_of("# 予定\n\n" + before, "# 予定\n\n" + after)
                self.assertEqual([(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in result["meaning_risks"]
                                  if r["kind"] == "number"], [("replaced", removed, added)])
                self.assertGreater(result["fail_on_meaning_risk_count"], 0)

    def test_same_order_still_cancels(self):
        for before, after in (("提出の締め切りは3/4です。", "提出の締め切りは3月4日です。"), ("締め切りは10/10です。", "締め切りは10月10日です。"),
                              ("会議は10:30〜11:15です。", "会議は10時30分から11時15分です。"),
                              ("公開は2026/10/13 10:30です。", "公開は2026年10月13日10時30分です。"),
                              ("受付は10/13〜10/15です。", "受付は10月13日から10月15日です。")):
            with self.subTest(after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_ground_uses_the_same_condition(self):
        for final, material, wanted in (("提出の締め切りは4月3日です。", "提出の締め切りは3/4です。", ["4月", "3日"]),
                                        ("会議は10時15分から11時30分です。", "会議は10:30〜11:15です。", ["10時", "15分", "11時", "30分"]),
                                        ("提出の締め切りは3月4日です。", "提出の締め切りは3/4です。", [])):
            with self.subTest(final=final):
                result = yomiyasu_diff.ground(final + "\n", [material + "\n"])
                self.assertEqual([r["detail"]["text"] for r in result["meaning_risks"] if r.get("subkind") == "number"], wanted)


# ---- V2: 範囲を1つの値に縮めた書き換え（消えた端と同じ値が文書の別の所にある）----
class NarrowedRangeTest(unittest.TestCase):
    def test_narrowed_range_with_the_value_elsewhere_is_found(self):
        for before, after, wanted in (("# 計画\n\n移行は3〜5日で終える。\n\n予備日は3日とる。", "# 計画\n\n移行は5日で終える。\n\n予備日は3日とる。",
                                       [("lost", ["3"], [])]),
                                      ("# 計画\n\n移行は3〜5日で終える。\n\n検証に5日かける。", "# 計画\n\n移行は3日で終える。\n\n検証に5日かける。",
                                       [("lost", ["5日"], [])]),
                                      ("# 計画\n\n担当は2〜3人です。\n\n確認は2人で行う。", "# 計画\n\n担当は3人です。\n\n確認は2人で行う。",
                                       [("lost", ["2"], [])])):
            with self.subTest(after=after):
                result = result_of(before, after)
                self.assertEqual([(r["subkind"], r["detail"]["removed"], r["detail"]["added"]) for r in result["meaning_risks"]
                                  if r["kind"] == "number"], wanted)
                self.assertGreater(result["fail_on_meaning_risk_count"], 0)

    def test_widened_range_with_the_value_elsewhere_is_found(self):
        """逆向き（1つの値を範囲に広げた書き換え）も、足した端と同じ値が文書の別の所にあるだけでは「元にある」としない
        （V2 と同じ穴。基準 38d6556 は出していた）。"""
        for before, after, wanted in (("# 計画\n\n移行は5日で終える。\n\n予備日は3日とる。", "# 計画\n\n移行は3〜5日で終える。\n\n予備日は3日とる。",
                                       [("added", [], ["3"])]),
                                      ("# 計画\n\n移行は3日で終える。\n\n検証に5日かける。", "# 計画\n\n移行は3〜5日で終える。\n\n検証に5日かける。",
                                       [("added", [], ["5日"])])):
            with self.subTest(after=after):
                self.assertEqual(number_risks(before, after), wanted)

    def test_values_in_merged_or_split_sentences_are_not_found(self):
        """文をまとめた・分けた推敲では、組の相手の文のすぐ前とすぐあとの組にならなかった文（まとめる前、分けたあとの文）の値も
        「ある」とみなす（コーパスの blacklist_ai/02_incident_report_sonnet_casual → _bl の1行目と2行目をまとめた推敲と同じ形）。"""
        for before, after, wanted in (
                ("# 障害報告書\n\n**発生日時**：2026年9月24日 20:12〜20:47（35分間）\n"
                 "**影響**：注文APIとユーザー情報APIのリクエストの約38%が504を返した。",
                 "# 障害報告書\n\n2026年9月24日20:12から20:47までの35分間、注文APIとユーザー情報APIへのリクエストの約38%に対して"
                 "ゲートウェイが504を返した。", []),
                ("2026年9月24日20:12から20:47までの35分間、注文APIへのリクエストの約38%に対してゲートウェイが504を返した。",
                 "発生日時は2026年9月24日 20:12〜20:47（35分間）。\n\n注文APIのリクエストの約38%が504を返した。", []),
                # 続く文の「3日」は元にない値として今までどおり出る（消えた 3 は出さない）
                ("# 計画\n\n移行は3〜5日で終える。", "# 計画\n\n移行は5日で終える。ただし3日で終わることもある。",
                 [("added", [], ["3日"])])):
            with self.subTest(after=after):
                self.assertEqual(number_risks(before, after), wanted)

    def test_moved_sentence_with_a_range_is_not_lost(self):
        """範囲を含む文を丸ごと別の所へ動かした推敲（正解つきの書き換えの組の1つと同じ文）。
        組の相手の文に範囲の値が1つも残らないときは、今までどおり文書全体で「ある」を見る（範囲を縮めた形と分ける）。"""
        listing = "一覧画面がAPIを3〜4回直列に呼んでおり、画面ごとに必要な項目も違うためだという。"
        token = "認証トークンのリフレッシュ処理を、リクエスト内の同期呼び出しから非同期キューのワーカーへ移しましたとされる。"
        rest = ("DBだけ更新されて通知が送られない不整合は、\nこれで起きなくなるという。ただし当初は文書の量が増えただけで、\n"
                "内容が古くなったまま残る問題が新たに出たかもしれない。")
        self.assertEqual(number_risks(listing + "\n\n" + token + rest, token + "\n\n" + listing + rest), [])

    def test_notation_with_the_value_elsewhere_still_cancels(self):
        for before, after in (("作業は3〜5日かかる。\n\n予備日は3日とる。", "作業は3日から5日かかる。\n\n予備日は3日とる。"),
                              ("作業は3〜5日かかる。\n\n検証に5日かける。", "作業は3日以上5日以内かかる。\n\n検証に5日かける。"),
                              ("作業は3〜5日かかる。", "作業は3日から5日かかる。")):
            with self.subTest(after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_known_limit_value_in_the_same_sentence(self):
        """消えた端の値を、同じ文の別の値として書いた書き換えは拾えない（記録の限界。直したら、この試験を変える）。"""
        self.assertEqual(number_risks("# 計画\n\n作業は3〜5日で終える。", "# 計画\n\n作業は5日で終え、予備に3日をとる。"), [])


# ---- V4: 続く文に移った値の似かたの比べ（6万字で3秒未満。設計 2.11 の約束1）----
def moved_document(paragraphs, length):
    """反証で見つけた例の文書（反証の測りと同じ作り）。"""
    olds, news = [], []
    for i in range(paragraphs):
        body = "".join("第{}項の設定を開き、値を確かめてから記録に残し、担当者へ知らせる手順を守る".format(i * 100 + k)
                       for k in range(length // 40))[:length]
        tail = ("別の作業として、ログの保管と通知の宛先の見直しを進め、利用者の問い合わせに答える体制を整える" * (length // 45 + 1))[:length]
        olds.append("移行は3日で終え、" + body + "。")
        news.append("移行は5日で終え、" + body + "。" + "予備として3日を見込み、" + tail + "。")
    return "\n\n".join(olds) + "\n", "\n\n".join(news) + "\n"


class MovedValueSpeedTest(unittest.TestCase):
    def test_long_following_sentences_stay_within_the_promise(self):
        before, after = moved_document(17, 1850)
        self.assertGreater(len(after), 60000)
        started = time.perf_counter()
        full = yomiyasu_diff.full_diff(before, after)
        risks = yomiyasu_diff.meaning_risks(before, after, full=full)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 3.0)
        self.assertEqual(Counter(r["subkind"] for r in risks if r["kind"] == "number"), Counter({"replaced": 17}))

    def test_ratio_is_not_computed_when_its_upper_bound_is_low(self):
        """続く文の ratio は、上限（quick_ratio）が組の文どうしの似かたを超えるときだけ求める（結果は変わらない）。"""
        source, partner = "移行は3日で終え、手順を守る。", "移行は5日で終え、手順を守る。"
        following = "予備として3日を見込み、別の作業を進める。"
        sentence = namedtuple("Sentence", "text")(following)
        calls = []
        original = yomiyasu_diff._text_ratio

        def counted(a, b):
            calls.append((a, b))
            return original(a, b)
        yomiyasu_diff._text_ratio = counted
        try:
            moved = yomiyasu_diff._moved_keys([(sentence, [yomiyasu_diff._Number(5, 7, "3", "日")])], Counter({("5", "日"): 1}),
                                              source, partner)
        finally:
            yomiyasu_diff._text_ratio = original
        self.assertEqual(moved, Counter())
        self.assertEqual(calls, [(source, partner)])
        self.assertLessEqual(difflib.SequenceMatcher(None, source, following, autojunk=False).quick_ratio(), original(source, partner))

if __name__ == "__main__":
    unittest.main()
