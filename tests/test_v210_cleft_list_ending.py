#!/usr/bin/env python3
"""v2.1.0: 前置きなしの強調構文（「〜したのは、A、B、C。」）を lint の cleft_list_ending（info）で候補にする。

当たる文と当たらない文は、お願いの例文と、このファイルで作った合成の文。コーパスは読むだけ。
"""

from pathlib import Path
from unittest import mock
import contextlib
import io
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_lint  # noqa: E402


RULE = "cleft_list_ending"
# 当たる文（1行1文）
HITS = (
    "書き換えの中で変動したのは、確かさ、引用、語調。",
    # 「新しいエディタで目指したのは、速さ、軽さ、静けさ──。」からダッシュを外した文
    "新しいエディタで目指したのは、速さ、軽さ、静けさ。",
    "今回の調査で分かったのは、費用、期間、人手。",
    "書き換えの中で変動したのは、確かさ、引用、語調など。",
    "書き換えの中で変動したのは、確かさ、引用、語調の3つ。",
    "書き換えの中で変動したのは、確かさ、引用、語調の3点。",
    "目指したのは、速さと軽さ。",
    "目指したのは、速さや軽さ、静けさ",
    "変わったのは、確かさ、引用、語調！",
    "ただ、変わったのは、確かさ、引用、そして語調。",
)
# 当たらない文。述語まで書いた文、直した形、読点だけの2項目、名詞でない項目、問い
MISSES = (
    "理由は、AとBです。",
    "書き換えでは、確かさ、引用、語調が変わった。",
    "新しいエディタでは、速さと軽さ、静けさを目指しました。",
    "最初に手をつけたのは、古い帳簿の整理でした。",
    "再試行するのは、5xx の場合に限る。",
    "変わったのは、確かさ、引用、語調です。",
    "目指したのは、速さ、軽さ、静けさだ。",
    "停止するのは、本番サービス、管理画面、社内ダッシュボードです。",
    "変わったのは、確かさが上がり、引用が減り、語調が変わったこと。",
    "目指したのは、速さ、軽さ。",
    "変わったのは、走る、跳ぶ、泳ぐ。",
    "変わったのは、確かさ、引用、語調？",
)
SAMPLE = HITS[0] + "\n"


def findings(text, **options):
    return yomiyasu_lint.lint_text(text, **options)["findings"]


def rules(text, **options):
    return [finding["rule"] for finding in findings(text, **options)]


def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "stdout", out))
        stack.enter_context(mock.patch.object(sys, "stderr", err))
        try:
            code = yomiyasu_lint.main([str(item) for item in argv])
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class CleftListEndingTest(unittest.TestCase):
    def test_hits(self):
        for sentence in HITS:
            with self.subTest(sentence=sentence):
                found = findings(sentence + "\n")
                self.assertEqual([finding["rule"] for finding in found], [RULE])
                self.assertEqual((found[0]["severity"], found[0]["line"], found[0]["snippet"]), ("info", 1, sentence))

    def test_misses(self):
        for sentence in MISSES:
            with self.subTest(sentence=sentence):
                self.assertNotIn(RULE, rules(sentence + "\n"))

    def test_meta_filler_heads_are_reported_once(self):
        for sentence in ("重要なのは、速さ、軽さ、静けさ。", "避けたいのは、遅さ、重さ、騒がしさ。"):
            with self.subTest(sentence=sentence):
                self.assertEqual(rules(sentence + "\n"), ["meta_filler"])

    def test_dash_ending_is_left_to_the_dash_rules(self):
        found = rules("新しいエディタで目指したのは、速さ、軽さ、静けさ──。\n")
        self.assertNotIn(RULE, found)
        self.assertIn("dash_decoration", found)

    def test_places(self):
        kept = {
            "list": "- 新しいエディタで目指したのは、速さ、軽さ、静けさ\n",
            "bold": "**今回の調査で分かったのは**、費用、期間、人手。\n",
            "after a sentence": "前の段落の文です。" + SAMPLE,
        }
        for name, text in kept.items():
            with self.subTest(name=name):
                self.assertEqual(rules(text), [RULE])
        skipped = {
            "quotation": "彼は「" + HITS[0] + "」と言った。\n",
            "block quote": "> " + SAMPLE,
            "heading": "## 書き換えの中で変動したのは、確かさ、引用、語調\n",
            "table": "| 項目 | 説明 |\n|---|---|\n| 変化 | " + HITS[0] + " |\n",
            "code": "```\n" + SAMPLE + "```\n",
        }
        for name, text in skipped.items():
            with self.subTest(name=name):
                self.assertNotIn(RULE, rules(text))

    def test_one_finding_per_line(self):
        self.assertEqual(rules(HITS[0] + HITS[2] + "\n"), [RULE])

    def test_slides_skips_the_rule_and_other_types_keep_it(self):
        self.assertIn(RULE, yomiyasu_lint.DOC_TYPE_SKIP_RULES["slides"])
        result = yomiyasu_lint.lint_text(SAMPLE, doc_type="slides")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["context"]["skipped_by_doc_type"][RULE], 1)
        for value in yomiyasu_lint.DOC_TYPE_SKIP_RULES:
            if value != "slides":
                with self.subTest(doc_type=value):
                    self.assertNotIn(RULE, yomiyasu_lint.DOC_TYPE_SKIP_RULES[value])
                    self.assertEqual(rules(SAMPLE, doc_type=value), [RULE])

    def test_info_does_not_change_the_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cleft.md"
            path.write_text(SAMPLE, encoding="utf-8")
            for options in ([], ["--strict"], ["--fail-on=warn"], ["--fail-on=error"]):
                with self.subTest(options=options):
                    code, out, err = call(options + [path])
                    self.assertEqual((code, err), (0, ""))
                    self.assertIn("見直し候補: 1件", out)

    def test_penalty_weight_is_info(self):
        # 地の文1,000字未満で info 1件: 100 × 40 ÷ (40 + 1) を丸めて98
        self.assertEqual(yomiyasu_lint.lint_text(SAMPLE)["rule_penalty_score"], 98)

    def test_message_says_what_to_do_and_when_to_keep(self):
        message = findings(SAMPLE)[0]["message"]
        for part in ("「〜のは、」のあとに名詞を並べ", "「のは」の前の動詞を述語に戻し", "「〜では、A、B、Cが変わった。」",
                     "前提が直前に書いてある場合", "見出し、結び、スライドの箇条", "残してかまいません"):
            self.assertIn(part, message)

    def test_corpus_has_no_hits(self):
        for group in ("human", "yomiyasu_rewritten", "raw_ai", "blacklist_ai", "edge_cases"):
            for path in sorted((CORPUS / group).glob("*.md")):
                with self.subTest(path=path.relative_to(CORPUS).as_posix()):
                    self.assertNotIn(RULE, rules(path.read_text(encoding="utf-8")))

    def test_long_lines_finish_quickly(self):
        texts = ("変わったのは、" + "山、" * 20000 + "です。\n", "変わったのは、" + "山と" * 20000 + "です。\n",
                 "変わったのは、" * 5000 + "山、川、海です。\n", "変わったのは、" + "さとさや" * 10000 + "です\n")
        for text in texts:
            started = time.perf_counter()
            self.assertNotIn(RULE, rules(text))
            self.assertLess(time.perf_counter() - started, 10.0)


if __name__ == "__main__":
    unittest.main()
