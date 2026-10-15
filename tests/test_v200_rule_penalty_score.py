#!/usr/bin/env python3
"""H40 の式、地の文字数、出力互換性を独立の有理数計算と実際の文書で確かめる。"""
from fractions import Fraction
from pathlib import Path
from unittest import mock
import json
import sys
import unittest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
import yomiyasu_lint as _lint

_DASH_RULES = ("dash_decoration", "dash_insertion", "dash_list_ending")
_WARN = "重要なのは、毎日確認することです。"
_INFO = "本記事では、設計を紹介します。"
_ERROR = "これは**「重要」**です。"


def _finding(severity="warn", rule="meta_filler"):
    return {"rule": rule, "severity": severity}


def _reference(findings, chars, dash_hits=0):
    """実装の整数式とは別に、分数で密度を求めて四捨五入する。"""
    if not findings:
        return 100
    weights = {"error": 3, "warn": 2, "info": 1}
    documents = {"excess_bold": 2, "excess_list": 2, "bold_label_list": 1}
    line = sum(weights[f["severity"]] for f in findings
               if f["rule"] not in documents and f["rule"] != "negative_parallelism_density")
    shown = sum(f["rule"] in _DASH_RULES for f in findings)
    line += 2 * max(0, dash_hits - shown)
    density = Fraction(1000 * line, max(chars, 1000))
    density += sum(documents.get(f["rule"], 0) for f in findings)
    rounded = Fraction(4000, 1) / (40 + density) + Fraction(1, 2)
    return max(1, min(99, rounded.numerator // rounded.denominator))


def _prose_chars(text):
    """公開 metrics を変えずに、参照用の字数を可視行から数える。"""
    analysis = _lint.analyze_markdown(text)
    total = 0
    for row in analysis["lines"]:
        if row["kind"] in ("code", "frontmatter", "html_block", "reference_definition",
                           "table", "heading", "heading_underline", "thematic_break"):
            continue
        if row["quote_depth"] or not row["raw"].strip():
            continue
        visible = _lint.line_visible_text(analysis, row["line"], _lint._METRIC_OPAQUE_KINDS)
        if _lint._image_only_row(analysis, row, visible):
            continue
        total += len("".join(visible.split()))
    return total


def _padding(chars):
    return "\n\n".join("山" * min(80, chars - i) for i in range(0, chars, 80))


def _corpus():
    return sorted((_ROOT / "tests" / "corpus").glob("*/*.md"))


class RulePenaltyScoreTest(unittest.TestCase):
    def _assert_reference(self, text, doc_type=None):
        hits = []
        original = _lint._dash_finding

        def counting(*args):
            finding = original(*args)
            if finding and finding["rule"] not in _lint.DOC_TYPE_SKIP_RULES.get(doc_type, ()):
                hits.append(finding)
            return finding

        with mock.patch.object(_lint, "_dash_finding", counting):
            result = _lint.lint_text(text, doc_type=doc_type)
        chars = _prose_chars(text)
        self.assertEqual(result["rule_penalty_score"], _reference(result["findings"], chars, len(hits)))
        self.assertEqual(_lint._metrics_and_list_gate(_lint.analyze_markdown(text))[2], chars)
        return result

    def test_01_repeated_corpus_above_floor(self):
        paths = _corpus()
        self.assertEqual(len(paths), 163)
        for path in paths:
            text = path.read_text(encoding="utf-8-sig").rstrip("\n")
            for mode in (None, "article"):
                scores = []
                for repeat in (1, 2, 4, 8, 16):
                    joined = "\n\n".join([text] * repeat) + "\n"
                    result = _lint.lint_text(joined, doc_type=mode)
                    # 地の文が1,000字に満たない回は1,000字として割るので、件数だけで決まり比べない。
                    if _prose_chars(joined) >= 1000:
                        scores.append(result["rule_penalty_score"])
                if len(scores) >= 2:
                    self.assertLessEqual(max(scores) - min(scores), 2, (path.name, mode, scores))

    def test_02_long_groups(self):
        groups = {}
        for path in _corpus():
            groups.setdefault(path.parent.name, []).append(path.read_text(encoding="utf-8-sig").rstrip("\n"))
        for group, texts in groups.items():
            short = "\n\n".join(texts)
            repeats = max(1, round(60000 / max(1, _prose_chars(short))))
            long = "\n\n".join([short] * repeats)
            for mode in (None, "article"):
                a = self._assert_reference(short, mode)["rule_penalty_score"]
                b = self._assert_reference(long, mode)["rule_penalty_score"]
                self.assertGreater(b, 0, group)
                self.assertLessEqual(abs(a - b), 1, (group, mode))
                if mode is None and group in ("human_doc", "edge_cases"):
                    self.assertEqual((a, b), (100, 100))

    def test_03_monotonicity(self):
        additions = [_finding(severity) for severity in ("error", "warn", "info")]
        additions += [_finding("warn", "excess_list"), _finding("warn", "excess_bold"),
                      _finding("info", "bold_label_list"), _finding("info", "negative_parallelism_density")]
        for chars in (1, 50, 999, 1000, 1001, 60000, 200000):
            for errors in range(4):
                for warns in range(4):
                    for infos in range(4):
                        findings = ([_finding("error")] * errors + [_finding()] * warns
                                    + [_finding("info")] * infos)
                        before = _reference(findings, chars)
                        self.assertEqual(_lint._rule_penalty_score(findings, chars, 0), before)
                        for addition in additions:
                            after = _reference(findings + [addition], chars)
                            self.assertLessEqual(after, before)
                            self.assertEqual(_lint._rule_penalty_score(findings + [addition], chars, 0), after)
            text = _padding(chars)
            before = self._assert_reference(text)["rule_penalty_score"]
            for count in range(1, 4):
                result = self._assert_reference(text + "\n\n" + "\n\n".join([_WARN] * count))
                self.assertLessEqual(result["rule_penalty_score"], before)
                before = result["rule_penalty_score"]
        dash = "項目——補足です。\n\n"
        self.assertLessEqual(self._assert_reference(dash * 5)["rule_penalty_score"],
                             self._assert_reference(dash * 4)["rule_penalty_score"])

    def test_04_severity_order(self):
        for chars in (0, 20, 999, 1000, 1001, 2000, 60000, 200000):
            scores = []
            for severity in ("error", "warn", "info"):
                findings = [_finding(severity)]
                score = _lint._rule_penalty_score(findings, chars, 0)
                self.assertEqual(score, _reference(findings, chars))
                scores.append(score)
            # 逆にはならない。長い文書では整数に丸めるので同点になる（6万字では3つとも99）。
            self.assertEqual(scores, sorted(scores))
            if chars <= 1000:
                self.assertEqual(scores, [93, 95, 98])
        for text, score in ((_ERROR, 93), (_WARN, 95), (_INFO, 98)):
            self.assertEqual(self._assert_reference(text)["rule_penalty_score"], score)

    def test_05_empty_and_range(self):
        for text in ("", "```\n" + _WARN + "\n```", _padding(60000)):
            self.assertEqual(self._assert_reference(text)["rule_penalty_score"], 100)
        self.assertEqual(self._assert_reference(_padding(60000) + "\n\n" + _INFO)["rule_penalty_score"], 99)
        zero = "# これは**「重要」**です。\n"
        self.assertEqual(_prose_chars(zero), 0)
        result = self._assert_reference(zero)
        self.assertIn("bold_not_rendered", [f["rule"] for f in result["findings"]])
        self.assertGreaterEqual(result["rule_penalty_score"], 1)
        for count in (1, 10, 100, 10000):
            findings = [_finding("error")] * count
            score = _lint._rule_penalty_score(findings, 0, 0)
            self.assertEqual(score, _reference(findings, 0))
            self.assertTrue(1 <= score <= 99)
        self.assertEqual(score, 1)

    def test_06_short_floor(self):
        for chars, expected in ((20, 95), (100, 95), (999, 95), (1000, 95), (2000, 98)):
            text = _WARN + "\n\n" + _padding(chars - len(_WARN))
            self.assertEqual(_prose_chars(text), chars)
            result = self._assert_reference(text)
            self.assertEqual(result["counts"], {"error": 0, "warn": 1, "info": 0})
            self.assertEqual(result["rule_penalty_score"], expected)

    def test_07_non_prose_does_not_dilute(self):
        # 下限を超え、字数を誤って足せば点数が動く例で除外を確認する。
        text = "\n\n".join([_WARN] * 10) + "\n\n" + _padding(1500 - 10 * len(_WARN))
        baseline = self._assert_reference(text)
        additions = ["```\n" + "コード" * 500 + "\n```",
                     "| 項目 | 値 |\n|---|---|\n" + "| 資料 | 記録 |\n" * 100,
                     "# " + "見出し" * 500, "見出し" * 500 + "\n===", "---",
                     "> " + "引用文" * 500, "https://example.com/" + "a" * 1500,
                     "    " + "コード" * 500, "<div>\n" + "本文" * 750 + "\n</div>",
                     "![画像](https://example.com/image.png)", "[ref]: https://example.com/" + "a" * 1500]
        for addition in additions:
            result = self._assert_reference(text + "\n\n" + addition)
            self.assertEqual(result["findings"], baseline["findings"], addition[:30])
            self.assertEqual(result["rule_penalty_score"], baseline["rule_penalty_score"])
        frontmatter = "---\ntitle: " + "資料" * 750 + "\n---\n\n"
        self.assertEqual(self._assert_reference(frontmatter + text)["rule_penalty_score"], baseline["rule_penalty_score"])
        inline = "記録 [資料](https://example.com/abc) `code` <span>本文</span> ![絵](a.png)"
        self.assertEqual(_prose_chars(inline), 8)
        self._assert_reference(inline)
        details = "<details>\n<summary>資料</summary>\n\n- 記録\n\n</details>"
        self.assertEqual(self._assert_reference(details)["metrics"]["char_count"], _prose_chars(details))

    def test_08_document_rules_and_summary(self):
        for chars in (1000, 60000):
            # 印と空白を除く本文を合わせ、地の文を指定字数にする。
            text = "\n".join("- " + "山" * 99 for _ in range(chars // 100))
            self.assertEqual(_prose_chars(text), chars)
            result = self._assert_reference(text)
            self.assertEqual([f["rule"] for f in result["findings"]], ["excess_list"])
            self.assertEqual(result["rule_penalty_score"], 95)
        result = self._assert_reference("AではなくBです。\n\nCではなくDです。\n\nEではなくFです。")
        findings = result["findings"]
        without = [f for f in findings if f["rule"] != "negative_parallelism_density"]
        self.assertEqual(len(findings) - len(without), 1)
        for chars in (27, 60000):
            self.assertEqual(_lint._rule_penalty_score(findings, chars, 0), _reference(without, chars))
        for rule, severity, score in (("excess_bold", "warn", 95), ("bold_label_list", "info", 98)):
            self.assertEqual(_lint._rule_penalty_score([_finding(severity, rule)], 60000, 0), score)

    def test_09_dash_display_limit(self):
        text = "".join("項目{}——補足です。\n\n".format(i) for i in range(5))
        result = self._assert_reference(text)
        self.assertEqual(len(result["findings"]), 3)
        self.assertTrue(all(f["rule"] in _DASH_RULES for f in result["findings"]))
        # 地の文50字、warn 5か所の重み10。表示した3件だけの87にはならない。
        self.assertEqual(result["rule_penalty_score"], 80)
        skip = dict(_lint.DOC_TYPE_SKIP_RULES, article=("dash_decoration",))
        with mock.patch.object(_lint, "DOC_TYPE_SKIP_RULES", skip):
            result = self._assert_reference(text + _INFO, "article")
            self.assertEqual([f["rule"] for f in result["findings"]], ["meta_intro"])
            self.assertEqual(result["rule_penalty_score"], 98)
        # 上限は外したあとに当てる。外す規則のダッシュが先に3行あっても、あとの外さない規則のダッシュは候補に出て数える。
        inserted = "".join("前置き{}——補足——です。\n\n".format(i) for i in range(4))
        with mock.patch.object(_lint, "DOC_TYPE_SKIP_RULES", skip):
            result = self._assert_reference(text + inserted, "article")
        self.assertEqual([f["rule"] for f in result["findings"]], ["dash_insertion"] * 3)
        self.assertEqual(result["context"]["skipped_by_doc_type"]["dash_decoration"], 5)
        # 地の文の字数は下限の内側、外さないダッシュ4行の重み8で83。
        self.assertEqual(result["rule_penalty_score"], 83)
        # 1行に何か所あっても、当たるのは1行に1件。
        one_line = self._assert_reference("記録——確認、手順——更新、資料——整理、担当——連絡のとおりです。")
        self.assertEqual(len(one_line["findings"]), 1)
        self.assertEqual(one_line["rule_penalty_score"], 95)

    def test_10_half_up(self):
        # 地の文1,000字、warn 12件の重み24。4000/64 = 62.5 を63へ丸める。
        findings = [_finding()] * 12
        self.assertEqual(Fraction(4000, 40 + 24), Fraction(125, 2))
        self.assertEqual(_reference(findings, 1000), 63)
        self.assertEqual(_lint._rule_penalty_score(findings, 1000, 0), 63)
        text = "\n\n".join([_WARN] * 12) + "\n\n" + _padding(1000 - 12 * len(_WARN))
        self.assertEqual(self._assert_reference(text)["rule_penalty_score"], 63)

    def test_11_doc_type(self):
        text = "回覧板は、木曜の朝に回します。"
        plain = self._assert_reference(text)
        promo = self._assert_reference(text, "promo")
        self.assertEqual(plain["findings"], promo["findings"])
        self.assertEqual(plain["rule_penalty_score"], promo["rule_penalty_score"])
        article = self._assert_reference(text, "article")
        self.assertEqual([f["rule"] for f in article["findings"]], ["pause_comma"])
        self.assertLess(article["rule_penalty_score"], plain["rule_penalty_score"])
        emoji = _WARN + "\n\n新作です😀"
        self.assertEqual(self._assert_reference(emoji, "promo")["rule_penalty_score"], 95)
        self.assertEqual(self._assert_reference(emoji)["rule_penalty_score"], 91)

    def test_12_outputs_and_exit_codes(self):
        # fixture の plain / strict / fail_error / stdin は式の変更前の値を保持している。
        from test_v200_doc_type import unchanged_lint
        fixture = json.loads((_ROOT / "tests" / "fixtures" / "g7_unchanged_outputs.json").read_text(encoding="utf-8"))
        self.assertEqual(unchanged_lint(), fixture["lint"])
        # 点数を除いた JSON のキー、順序、値は従来の短文の結果と同じ。
        result = _lint.lint_text("記録を確認した。")
        result.pop("rule_penalty_score")
        expected = {"format": "yomiyasu-lint", "format_version": 2, "tool_version": _lint.__version__,
                    "candidate_count": 0, "counts": {"error": 0, "warn": 0, "info": 0},
                    "no_rule_findings": True, "not_judged": ["meaning_preservation", "reader_comprehension"],
                    "context": {"doc_type": None, "reader": None, "skipped_by_doc_type": {}},
                    "metrics": {"char_count": 8, "total_lines": 1, "list_lines": 0, "list_ratio": 0.0,
                                "bold_count": 0, "bold_per_1000": 0.0}, "findings": []}
        self.assertEqual(json.dumps(result), json.dumps(expected))

    def test_13_script_copies(self):
        for path in (_ROOT / "skills" / "yomiyasu" / "scripts").glob("*.py"):
            self.assertEqual(path.read_bytes(), (_ROOT / "scripts" / path.name).read_bytes())

    def test_14_help(self):
        parser = _lint._build_parser()
        action = next(a for a in parser._actions if "--json" in a.option_strings)
        self.assertEqual(action.help, "結果をJSON（形式2）で出します。日本語は \\uXXXX の形で出します。"
                         "rule_penalty_score は、候補の多さを地の文の長さで割った目安です（下の式）。合否には使わないでください。")
        expected = """rule_penalty_score（--json の目安）:
  候補が0件なら100。候補があれば 100 × 40 ÷ (40 + x) を四捨五入し、1〜99に収めます。
  x は、行ごとの候補の重み（error 3、warn 2、info 1）を地の文1,000字あたりに直した数です。
  地の文はコード、表、引用、見出し、URL を除いた字数で、1,000字に満たなければ1,000字として割ります。
  excess_bold と excess_list は1件で2、bold_label_list は1を x に足し、
  negative_parallelism_density は数えません。ダッシュの規則に当たった行は、候補に出さない4行目からも数えます。
  --doc-type で候補が変わると、点数も変わります。CI では --fail-on か counts を使ってください。"""
        help_text = parser.format_help()
        self.assertIn(expected, help_text)
        self.assertLess(help_text.index(expected), help_text.index("終了コード:"))


if __name__ == "__main__":
    unittest.main()
