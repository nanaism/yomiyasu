"""v2.2.0: 新しい規則の土台（点数に入れないこと、候補の内部の欄を出さないこと、ヘルプ）を確かめる。

文はすべて合成の文。
"""
from pathlib import Path
from unittest import mock
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402

RULES = ("calque", "metaphor_label", "say_hedge", "thin_evaluation", "katakana_term", "dialogue_period",
         "narrative_density", "copy_comma_noun", "bare_verb_chain", "project_term")


def fake_finding(rule="calque"):
    return {"rule": rule, "line": 1, "severity": "info", "message": "合成の候補です。", "snippet": "記録を確認した。",
            "_words": ("確認",)}


class BaseTest(unittest.TestCase):
    def test_rule_names(self):
        self.assertEqual(yomiyasu_lint._V220_RULES, RULES)

    def test_new_rules_do_not_change_the_score(self):
        """新しい規則の候補だけなら点数は100のまま。ほかの候補があるときも、新しい規則の候補を除いた点数と同じ。"""
        text = "記録を確認した。\n"
        plain = yomiyasu_lint.lint_text(text)
        for rule in RULES:
            # 種類を限って当てる規則（dialogue_period と narrative_density）は、その種類を指定して見る
            doc_type = yomiyasu_lint.DOC_TYPE_ONLY_RULES.get(rule, (None,))[0]
            with self.subTest(rule=rule), \
                    mock.patch.object(yomiyasu_lint, "_v220_word_findings", lambda analysis, r=rule: [fake_finding(r)]):
                result = yomiyasu_lint.lint_text(text, doc_type=doc_type)
            self.assertEqual(result["rule_penalty_score"], plain["rule_penalty_score"])
            self.assertEqual(result["rule_penalty_score"], 100)
            self.assertEqual(result["counts"], {"error": 0, "warn": 0, "info": 1})
            self.assertEqual(result["candidate_count"], 1)
        text = "ここで重要なのは、記録を残すことです。\n"
        plain = yomiyasu_lint.lint_text(text)
        self.assertTrue(plain["findings"])
        with mock.patch.object(yomiyasu_lint, "_v220_word_findings", lambda analysis: [fake_finding()]):
            result = yomiyasu_lint.lint_text(text)
        self.assertEqual(result["rule_penalty_score"], plain["rule_penalty_score"])
        self.assertEqual(result["candidate_count"], plain["candidate_count"] + 1)

    def test_internal_keys_are_not_output(self):
        with mock.patch.object(yomiyasu_lint, "_v220_word_findings", lambda analysis: [fake_finding()]):
            result = yomiyasu_lint.lint_text("記録を確認した。\n")
        finding = result["findings"][0]
        self.assertEqual(sorted(finding), ["line", "message", "rule", "severity", "snippet"])
        self.assertNotIn("_words", json.dumps(result, ensure_ascii=False))

    def test_no_words_context_without_a_list(self):
        result = yomiyasu_lint.lint_text("記録を確認した。\n")
        self.assertEqual(list(result["context"]), ["doc_type", "reader", "skipped_by_doc_type"])

    def test_help_names_every_new_rule(self):
        help_text = yomiyasu_lint._build_parser().format_help()
        section = help_text[help_text.index("rule_penalty_score（--json の目安）"):help_text.index("終了コード:")]
        for rule in RULES:
            self.assertIn(rule, section)


if __name__ == "__main__":
    unittest.main()
