#!/usr/bin/env python3
"""v2.0.0（G12）: diff の勢いの検査（tone）と、文書の種類 promo（紹介記事・宣伝文）。

期待値は勢いの文書（yomiyasu-v2.0.0-addendum-tone-preservation_20261013-2135.md）の1章、3章、5章から取った。
文はすべて合成の文（勢いの文書の表の文と、このファイルで作った文）。

- 勢いの検査は文書の種類によらず毎回行う。「！」「？」絵文字、強める語の数が原文より減ったとき、見出しの字数の合計が
  原文の7割未満になったときに候補を出す。コード、URL、表の中は数えない。
- 結果は diff の JSON の tone（最後のキー）と、レポートの「■ 勢い」の節に出す。candidate_count、状態の行、
  --fail-on=meaning-risk には入れない。
- 文書の種類が pr、article、incident、manual、formal（技術文書、障害報告、ヘルプ、公用文に当たる種類）なら参考（level info）。
- 強める語の一覧は references/lists/intensifiers.txt（ルートと skills の両方）。なければ内蔵の一覧で動く。
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PACKAGE = ROOT / "skills" / "yomiyasu"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402

TONE_KEYS = {"kind", "subkind", "old_line", "new_line", "old", "new", "detail", "level"}
TAIL = "書き手の勢いを落としていないか確かめてください。"
INFO_TYPES = ("pr", "article", "incident", "manual", "formal")
REVIEW_TYPES = ("proposal", "minutes", "slides", "essay", "promo")


def tone(before, after, **options):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    result = yomiyasu_diff.diff(before, after, **options)
    return result, result["tone"]


def subkinds(section):
    return [candidate["subkind"] for candidate in section["candidates"]]


# ---- 勢いの文書 1章の表（5組とも、直してはいけない推敲）----
# 2行目と3行目は、元の記事の見出し（番号つきの小見出し）として Markdown の見出しにした。店名と商品名は、references/doc-types/promo.md
# 4章の例と同じ架空の名前（港町、しおかぜラーメン、灯台とんこつラーメン、なぎさ製麺）にした（実在の会社や商品の名前を使わない）
TITLE = "港町のスーパーで探す最強のお土産！安くて美味いご当地ラーメン4選"
TITLE_FLAT = "港町のスーパーで探す最強のお土産、安くて美味いご当地ラーメン4選"
HEADING_1 = "## 1. 昭和から愛される港町のソウルフード「しおかぜラーメン」（なぎさ製麺）"
HEADING_1_SHORT = "## 1. しおかぜラーメン（なぎさ製麺）"
HEADING_2 = "## 2. 焦がしニンニク油が香る本格派「灯台とんこつラーメン」（なぎさ製麺）"
HEADING_2_SHORT = "## 2. 灯台とんこつラーメン（なぎさ製麺）"
PUNCH = "「黒マー油（焦がしニンニク油）」のパンチを自宅で味わうなら"
PUNCH_FLAT = "「黒マー油（焦がしニンニク油）」の力強い風味を自宅で味わうなら"
ACTIVE = "自宅用にも配り用にも大活躍するおすすめ銘柄"
ACTIVE_FLAT = "自宅用にも配る用にも重宝するおすすめの銘柄"

ARTICLE = "\n".join([
    "# " + TITLE, "",
    "港町のスーパーには、手頃でおいしいご当地ラーメンがずらりと並んでいます。", "",
    HEADING_1, "",
    "甘めのとんこつスープで、子どもにも人気です。", "",
    HEADING_2, "",
    PUNCH + "、この一袋がおすすめです。", "",
    "## まとめ", "",
    ACTIVE + "です。ぜひ探してみてください！", "",
])
CHAPTER1_PAIRS = (
    ("title", ARTICLE.replace(TITLE, TITLE_FLAT), "exclamation"),
    ("heading_1", ARTICLE.replace(HEADING_1, HEADING_1_SHORT).replace(HEADING_2, HEADING_2_SHORT), "heading"),
    ("punch", ARTICLE.replace(PUNCH, PUNCH_FLAT), "intensifier"),
    ("active", ARTICLE.replace(ACTIVE, ACTIVE_FLAT), "intensifier"),
)


class ChapterOneTest(unittest.TestCase):
    """勢いの文書1章の5組（直してはいけない推敲）は、どれも勢いの検査の候補になる。そのまま残せば何も出ない。"""

    def test_unchanged_article_has_no_candidate(self):
        result, section = tone(ARTICLE, ARTICLE, doc_type="promo")
        self.assertEqual(section["candidates"], [])
        self.assertEqual(section["candidate_count"], 0)

    def test_flattened_rewrites_are_found(self):
        for label, after, subkind in CHAPTER1_PAIRS:
            with self.subTest(pair=label):
                result, section = tone(ARTICLE, after, doc_type="promo")
                self.assertIn(subkind, subkinds(section))
                self.assertEqual(section["level"], "review")
                for candidate in section["candidates"]:
                    self.assertEqual(set(candidate), TONE_KEYS)
                    self.assertEqual(candidate["kind"], "tone")

    def test_heading_detail(self):
        result, section = tone(ARTICLE, CHAPTER1_PAIRS[1][1], doc_type="promo")
        [heading] = [c for c in section["candidates"] if c["subkind"] == "heading"]
        self.assertLess(heading["detail"]["new"], heading["detail"]["old"] * 0.7)
        self.assertTrue(heading["detail"]["places"])


# ---- 勢いの文書 5章の表 ----

class ChapterFiveTest(unittest.TestCase):
    def test_keep_exclamation(self):
        """残す（紹介記事）: 「！」が残る推敲では候補なし。"""
        result, section = tone(TITLE, TITLE, doc_type="promo")
        self.assertEqual(section["candidates"], [])

    def test_keep_heading(self):
        """残す（紹介記事）: 見出しを残した推敲では候補なし。見出しの言い回しを削ると候補が出る。"""
        before = HEADING_1 + "\n\n甘めのとんこつスープです。\n"
        self.assertEqual(tone(before, before, doc_type="promo")[1]["candidates"], [])
        shortened = tone(before, before.replace(HEADING_1, HEADING_1_SHORT), doc_type="promo")[1]
        self.assertEqual(subkinds(shortened), ["heading"])

    def test_keep_punch(self):
        """残す（紹介記事）: 「パンチ」を残せば候補なし。落ち着いた言い方にすると強める語の候補が出る。"""
        before = "「黒マー油」のパンチを自宅で味わうなら"
        self.assertEqual(tone(before, before, doc_type="promo")[1]["candidates"], [])
        after = "「黒マー油」の力強い風味を自宅で味わうなら"
        self.assertEqual(subkinds(tone(before, after, doc_type="promo")[1]), ["intensifier"])

    def test_known_limit_repeated_praise_not_in_list(self):
        """限界（紹介記事）: 強める語の一覧にない褒め言葉（絶品）の繰り返しを減らした推敲は、勢いの検査の候補にならない。
        紹介記事では同じ褒め言葉の繰り返しを減らさずに残すのが決まり（references/doc-types/promo.md）なので、減らしていないかは
        推敲の見直しで読み比べる（references/review-points.md）。"""
        before = "この麺は絶品です。スープも絶品で、具も絶品です。"
        after = "この麺は絶品です。スープも具も、よくできています。"
        self.assertEqual(tone(before, after, doc_type="promo")[1]["candidates"], [])

    def test_detect_without_doc_type(self):
        """検出（指定なし）: 原文「最強のお土産！」、推敲後「最強のお土産、」で候補が出る（見直し候補）。"""
        result, section = tone("最強のお土産！", "最強のお土産、")
        [candidate] = section["candidates"]
        self.assertEqual((candidate["subkind"], candidate["level"]), ("exclamation", "review"))
        self.assertEqual((candidate["detail"]["old"], candidate["detail"]["new"]), (1, 0))
        report = yomiyasu_diff.report(result)
        line = [row for row in report.split("\n") if row.startswith("- 原文の「！」1個が、推敲後は0個になりました（1行目")]
        self.assertEqual(len(line), 1, report)
        self.assertTrue(line[0].endswith("）。" + TAIL), line[0])
        self.assertIn("■ 勢い（見直し候補 1件", report)

    def test_incident_gives_info_only(self):
        """出さない（障害報告）: 原文「至急対応が必要です！」、推敲後「至急対応が必要です。」は参考だけ。"""
        result, section = tone("至急対応が必要です！", "至急対応が必要です。", doc_type="incident")
        self.assertEqual(section["level"], "info")
        self.assertEqual([c["level"] for c in section["candidates"]], ["info"])
        report = yomiyasu_diff.report(result)
        self.assertIn("■ 勢い（参考 1件", report)
        self.assertNotIn("■ 勢い（見直し候補", report)


class LevelTest(unittest.TestCase):
    def test_info_doc_types(self):
        for value in INFO_TYPES:
            with self.subTest(doc_type=value):
                self.assertEqual(tone("最強のお土産！", "最強のお土産、", doc_type=value)[1]["level"], "info")

    def test_review_doc_types_and_none(self):
        for value in REVIEW_TYPES + (None,):
            with self.subTest(doc_type=value):
                self.assertEqual(tone("最強のお土産！", "最強のお土産、", doc_type=value)[1]["level"], "review")


class CountTest(unittest.TestCase):
    """3.1 の5つの数え方。"""

    def test_each_kind_of_decrease(self):
        cases = (
            ("今日は晴れ！散歩に行こう！", "今日は晴れ。散歩に行こう。", "exclamation", (2, 0)),
            ("今日は晴れ!", "今日は晴れ。", "exclamation", (1, 0)),
            ("どうして遅いのでしょう？", "遅い理由を調べました。", "question", (1, 0)),
            ("新作のケーキです\U0001F370", "新作のケーキです。", "emoji", (1, 0)),
            ("本当においしいので、ぜひ食べてください。", "おいしいので、食べてください。", "intensifier", (2, 0)),
        )
        for before, after, subkind, numbers in cases:
            with self.subTest(before=before):
                section = tone(before, after)[1]
                [candidate] = [c for c in section["candidates"] if c["subkind"] == subkind]
                self.assertEqual((candidate["detail"]["old"], candidate["detail"]["new"]), numbers)

    def test_counts_are_recorded(self):
        section = tone("最強のお土産！", "最強のお土産、")[1]
        for side in ("old", "new"):
            self.assertEqual(set(section["counts"][side]),
                             {"exclamation", "question", "emoji", "intensifier", "heading_chars"})
        self.assertEqual(section["counts"]["old"]["exclamation"], 1)
        self.assertEqual(section["counts"]["old"]["intensifier"], 1)

    def test_increase_or_same_is_not_a_candidate(self):
        self.assertEqual(tone("おいしいです。", "本当においしいです！")[1]["candidates"], [])

    def test_code_urls_and_tables_are_not_counted(self):
        before = ("説明です。\n\n```\necho \"hello!\"\n```\n\n`a != b` を確かめる。<https://example.com/?q=1>\n\n"
                  "| 列 | 値 |\n|---|---|\n| 最強！ | 1 |\n\n![図！](img.png)\n")
        after = ("説明です。\n\n```\necho \"hello\"\n```\n\n`a == b` を確かめる。<https://example.com/>\n\n"
                 "| 列 | 値 |\n|---|---|\n| 最強 | 1 |\n\n![図](img.png)\n")
        self.assertEqual(tone(before, after)[1]["candidates"], [])

    def test_heading_sum_threshold_is_seventy_percent(self):
        before = "# 春の新作ケーキを10種類まとめて紹介\n\n本文です。\n"
        keep = "# 春の新作ケーキを10種類紹介\n\n本文です。\n"       # 17字 → 14字（8割を超える）
        short = "# 春の新作ケーキ\n\n本文です。\n"                     # 17字 → 6字
        self.assertEqual(tone(before, keep)[1]["candidates"], [])
        self.assertEqual(subkinds(tone(before, short)[1]), ["heading"])

    def test_no_change(self):
        result, section = tone(ARTICLE, ARTICLE)
        self.assertEqual(section["candidates"], [])
        self.assertEqual(result["status"], "no_change")


class NotCountedTest(unittest.TestCase):
    def test_tone_is_not_a_candidate_count_or_fail_on(self):
        """勢いの検査は見直し候補を出すだけ。candidate_count、状態の行、--fail-on には入れない（3.3）。"""
        result, section = tone("最強のお土産！", "最強のお土産、")
        self.assertTrue(section["candidates"])
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(result["candidate_count"], yomiyasu_diff._rule_count(result, True))
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)
        self.assertEqual(result["status"], "changed_without_candidates")

    def test_cli_fail_on_exit_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a.md", Path(folder) / "b.md"
            a.write_bytes("最強のお土産！\n".encode("utf-8"))
            b.write_bytes("最強のお土産、\n".encode("utf-8"))
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "--fail-on=meaning-risk",
                                      str(a), str(b)], capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(process.returncode, 0)
        out = process.stdout.decode("utf-8")
        self.assertIn("■ 勢い（見直し候補 1件", out)


class ListFileTest(unittest.TestCase):
    def test_intensifier_list_files_match_the_builtin_list(self):
        for base in (ROOT / "references" / "lists", PACKAGE / "references" / "lists"):
            with self.subTest(base=str(base)):
                path = base / "intensifiers.txt"
                self.assertTrue(path.is_file())
                parsed = yomiyasu_diff.parse_list(path.read_text(encoding="utf-8"))
                self.assertEqual(parsed, list(yomiyasu_diff.BUILTIN_LISTS["intensifiers"]))

    def test_initial_words_are_in_the_list(self):
        """3.1 の4の初めの一覧。"""
        for word in ("本当に", "とても", "すごく", "ぜひ", "絶対", "最強", "抜群", "イチオシ", "大活躍"):
            self.assertIn(word, yomiyasu_diff.BUILTIN_LISTS["intensifiers"])

    def test_list_used(self):
        self.assertEqual(tone("最強！", "最強。")[1]["list"], "references/lists/intensifiers.txt")


class PromoDocTypeTest(unittest.TestCase):
    """D-5: 文書の種類 promo（紹介記事・宣伝文）。lint は promo のとき emoji_prohibited を外す（diff の詰めで測って決めた）。
    fragment_run も外す（作者の判断、2026-10-14 朝。試験は test_v200_tone_stiffness_refine.LintPromoFragmentTest）。"""

    def test_promo_is_a_doc_type(self):
        import markdown_visibility
        self.assertEqual(markdown_visibility.normalize_doc_type(" PROMO "), "promo")
        self.assertIn(("promo", "紹介記事・宣伝文"), [row[:2] for row in markdown_visibility.DOC_TYPES])

    def test_lint_skips_emoji_for_promo(self):
        text = "# 春のおすすめケーキ\n\n新作のケーキが並びました\U0001F370\n"
        plain = yomiyasu_lint.lint_text(text)
        self.assertIn("emoji_prohibited", [f["rule"] for f in plain["findings"]])
        promo = yomiyasu_lint.lint_text(text, doc_type="promo")
        self.assertNotIn("emoji_prohibited", [f["rule"] for f in promo["findings"]])
        # 作者の判断（2026-10-14 朝）で fragment_run も外す（評価の語を短く重ねる型を勢いとして残す）
        # 2.2.0 で metaphor_label と bare_verb_chain も外す
        self.assertEqual(promo["context"]["skipped_by_doc_type"],
                         {"bare_verb_chain": 0, "emoji_prohibited": 1, "fragment_run": 0, "metaphor_label": 0})
        self.assertEqual(yomiyasu_lint.DOC_TYPE_SKIP_RULES["promo"],
                         ("bare_verb_chain", "emoji_prohibited", "fragment_run", "metaphor_label"))

    def test_other_doc_types_keep_emoji(self):
        text = "新作のケーキが並びました\U0001F370\n"
        for value in ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal"):
            with self.subTest(doc_type=value):
                found = yomiyasu_lint.lint_text(text, doc_type=value)
                self.assertIn("emoji_prohibited", [f["rule"] for f in found["findings"]])

    def test_diff_and_check_accept_promo(self):
        result = yomiyasu_diff.diff("a\n", "b\n", doc_type="promo")
        self.assertEqual(result["context"]["doc_type"], "promo")


if __name__ == "__main__":
    unittest.main()
