"""G9: instruction residue and the overstatement ending, without legacy changes."""

import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint as lint


def new_findings(text, rule):
    return [f for f in lint.lint_text(text)["findings"]
            if (f["rule"] == "instruction_residue" if rule == 1 else
                f["rule"] == "meta_filler" and "過言" in f["message"])]


class Rule9Tests(unittest.TestCase):
    def test_supplied_examples(self):
        examples = json.loads((ROOT / "tests/fixtures/rule9_examples.json").read_text(encoding="utf-8"))
        self.assertEqual(len(examples), 24)
        for example in examples:
            with self.subTest(id=example["id"]):
                self.assertEqual(set(example), {"id", "text", "lint_expect"})
                hits = new_findings(example["text"], int(example["id"][1]))
                if example["lint_expect"] == "new_rule_finding":
                    self.assertTrue(hits)
                elif example["lint_expect"] == "no_new_rule_finding":
                    self.assertEqual(hits, [])
                else:
                    self.assertEqual(example["lint_expect"], "may_flag")

    def test_overstatement_variants(self):
        for verb in ("言っても", "いっても", "も言っても", "もいっても"):
            for ending in ("ではありません", "ではない", "じゃない", "じゃありません"):
                with self.subTest(verb=verb, ending=ending):
                    hits = new_findings("大きな成果と" + verb + "過言" + ending + "。", 2)
                    self.assertEqual(len(hits), 1)
                    self.assertEqual(hits[0]["severity"], "warn")
                    self.assertIn("事実を淡々と書", hits[0]["message"])

    def test_quotes_and_mentions_are_kept(self):
        for text in (
            "部長は『最高の成果と言っても過言ではない』と語った。",
            "部長は「成果は大きい。最高と言っても過言ではない」と語った。",
            "部長は「成果は大きい。\n最高と言っても過言ではない」と語った。",
            "部長は「成果は大きい。\n\n最高と言っても過言ではない」と語った。",
            "と言っても過言ではないという表現は、大げさに聞こえる。",
            "といっても過言じゃない、という言い回しを避けたい。",
        ):
            with self.subTest(text=text):
                self.assertEqual(new_findings(text, 2), [])

    def test_quoted_phrase_does_not_hide_real_finding_on_same_line(self):
        text = "「革命と言っても過言ではない」は大げさだ。これは傑作と言っても過言じゃない。"
        self.assertEqual(len(new_findings(text, 2)), 1)

    def test_non_ending_and_negation_are_kept(self):
        for text in ("革命と言っても過言ではないとは思わない。",
                     "革命と言っても過言ではないかもしれない、という表現を検討する。"):
            with self.subTest(text=text):
                self.assertEqual(new_findings(text, 2), [])

    def test_instruction_context_and_scope_are_kept(self):
        for text in (
            "この論文では、未回収の質問紙は扱わない。",
            "このマニュアルでは、管理者向けの設定は扱いません。",
            "この記事では、管理者向けの設定は扱いません。管理者ガイドを参照してください。",
            "この記事では、管理者向けの設定は扱いません。\n詳細は管理者ガイドを参照してください。",
            "本稿では、実験対象を成人だけに絞って分析します。",
            "専門用語を使わずに説明してください。",
            "前向きなトーンで話す人が増えました。",
            "「今回は体験に絞って紹介します」と書いてあった。",
            "「今回は、\n体験に絞って紹介します」と書いてあった。",
            "「今回は、\n\n体験に絞って紹介します」と書いてあった。",
        ):
            with self.subTest(text=text):
                self.assertEqual(new_findings(text, 1), [])

    def test_instruction_variations_and_local_scope(self):
        for text in (
            "本記事では専門用語を用いずに解説します。",
            "今回は使用感に限定して紹介します。",
            "細部は省き、要点だけに絞って書く。",
            "本稿では結論を６００字以内でお伝えします。",
            "この記事では保守の話には触れません。",
            "この記事では設定は扱いません。\n\n別の話の参照先は管理者ガイドです。",
            "専門用語を使わずに説明します。手順はマニュアルを参照してください。",
        ):
            with self.subTest(text=text):
                hits = new_findings(text, 1)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["severity"], "info")
                self.assertIn("除外や書き方の指示を述べる文を削", hits[0]["message"])

    def test_markdown_protected_content_and_line_numbers(self):
        for rule, text in ((1, "ここでは専門用語を使わずに説明します。"),
                           (2, "革命と言っても過言ではない。")):
            for protected in ("`" + text + "`", "```\n" + text + "\n```", "> " + text,
                              "---\ntitle: " + text + "\n---", "<!-- " + text + " -->"):
                with self.subTest(rule=rule, protected=protected):
                    self.assertEqual(new_findings(protected, rule), [])
            hits = new_findings("# 題名\n\n" + text, rule)
            self.assertEqual(hits[0]["line"], 3)
            self.assertEqual(set(hits[0]), {"rule", "line", "severity", "message", "snippet"})

    def test_default_exit_and_explicit_fail_on(self):
        for text, severity in (("今回は体験に絞って紹介します。", "info"),
                               ("革命と言っても過言ではない。", "warn")):
            for options, expected in (([], 0), (["--fail-on=error"], 0),
                                      (["--fail-on=warn"], int(severity == "warn"))):
                with self.subTest(text=text, options=options):
                    result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/yomiyasu_lint.py"),
                                             "--json"] + options, input=text, text=True, capture_output=True)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertTrue(json.loads(result.stdout)["findings"])

    def test_existing_findings_and_metrics_with_new_candidates(self):
        for rule, residue, neutral in (
            (1, "今回は体験に絞って紹介します。", "今回は体験の記録を紹介します。"),
            (2, "革命と言っても過言ではない。", "革命の内容を記録として紹介。"),
        ):
            # Same number of visible characters; no legacy pattern in either ending.
            self.assertEqual(len(residue), len(neutral))
            prefix = "結論から言うと、これは重要です。\n\n"
            before = lint.lint_text(prefix + neutral)
            after = lint.lint_text(prefix + residue)
            added = new_findings(prefix + residue, rule)
            self.assertTrue(added)
            self.assertEqual([f for f in after["findings"] if f not in added], before["findings"])
            self.assertEqual(after["metrics"], before["metrics"])

    def test_one_finding_per_pattern_per_line(self):
        for rule, text in ((1, "今回は体験に絞って紹介します。"),
                           (2, "革命と言っても過言ではない。")):
            with self.subTest(rule=rule):
                self.assertEqual(len(new_findings(text * 2, rule)), 1)
                self.assertEqual(len(new_findings(text + "\n" + text, rule)), 2)

    def test_existing_filler_in_quotes_keeps_legacy_behavior(self):
        text = "「結論から言うと、革命と言っても過言ではない」と話した。"
        result = lint.lint_text(text)
        self.assertEqual(new_findings(text, 2), [])
        # The old filler only matches a sentence start, even in this quote.
        self.assertFalse(any(f["rule"] == "meta_filler" for f in result["findings"]))
        text = "「結果が出た。結論から言うと、革命と言っても過言ではない」と話した。"
        result = lint.lint_text(text)
        self.assertEqual(new_findings(text, 2), [])
        fillers = [f for f in result["findings"] if f["rule"] == "meta_filler"]
        self.assertEqual(len(fillers), 1)
        self.assertIn("結論から言うと", fillers[0]["message"])

    def test_overstatement_with_trailing_modality(self):
        for text in ("これは革命と言っても過言ではないでしょう。",
                     "これは革命と言っても過言ではないだろう。",
                     "これは革命と言っても過言ではありませんね。",
                     "これは革命と言っても過言ではないかもしれません。",
                     "これは革命と言っても過言ではないと思います。",
                     "これは革命と言っても過言ではありません（少なくとも私の経験では）。",
                     "これは革命と言い切っても過言ではありません。",
                     "これは革命と言っても言い過ぎではありません。"):
            with self.subTest(text=text):
                self.assertEqual(len(new_findings(text, 2)), 1)
        # Every alternative of the pattern keeps a literal hint, so the literal
        # prefilter never hides a match.
        hints = lint._PATTERN_LITERAL_HINTS[lint._OVERSTATEMENT_PATTERN]
        for text in ("と言っても言いすぎではない。", "といってもいいすぎではない。"):
            with self.subTest(text=text):
                self.assertTrue(any(hint in text for hint in hints))
                self.assertEqual(len(new_findings(text, 2)), 1)

    def test_instruction_paraphrases(self):
        for text in (
            "本記事では、細かい設定方法には触れず、全体の流れだけを説明します。",
            "ここでは、自分の体験に絞ってお話しします。",
            "本記事では、歴史的な経緯については割愛します。",
            "このブログでは、技術的な詳細は省略します。",
            "今回は500文字程度で簡潔にまとめます。",
            "カジュアルな口調で書いていきます。",
            "本稿では、細部には立ち入らず、要点のみを述べます。",
            "今回は専門的な話は抜きにして、体験談だけをお届けします。",
            "この記事では、私自身の失敗談に焦点を当ててご紹介します。",
        ):
            with self.subTest(text=text):
                self.assertEqual(len(new_findings(text, 1)), 1)

    def test_plain_narration_rules_and_references_are_kept(self):
        for text in (
            "彼女は穏やかな口調で振り返る。",
            "議事録は800字以内でまとめる。",
            "今回は、2025年4月の障害に絞って振り返ります。3月の障害は別の報告書にまとめました。",
            "ここでは、ファイルの置き場所は省略します。置き場所は付録Aにあります。",
            "本記事では、導入の手順は扱いません。手順は後述の章で説明します。",
            "このマニュアルでは、管理者向けの設定は扱わず、一般利用者の操作を説明します。",
        ):
            with self.subTest(text=text):
                self.assertEqual(new_findings(text, 1), [])

    def test_sparse_quote_mask_matches_legacy_mask(self):
        import random
        rng = random.Random(9)
        alphabet = "「」『』[]あ。\n x"
        samples = ["", "「", "」", "「a」", "「『a」』", "[「]」", "「\n\n」", "a「b「c」d」e"]
        samples += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40))) for _ in range(3000)]
        for text in samples:
            self.assertEqual(lint._mask_quoted_segments_sparse(text), lint._mask_quoted_segments(text), repr(text))

    def test_package_and_python38_syntax(self):
        source = (ROOT / "scripts/yomiyasu_lint.py").read_bytes()
        self.assertEqual(source, (ROOT / "skills/yomiyasu/scripts/yomiyasu_lint.py").read_bytes())
        ast.parse(source, feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
