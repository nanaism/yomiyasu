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
    # 撥音便とイ音便の過去（んだ、いだ）
    "今回選んだのは、PostgreSQL、Redis、S3。",
    "最初に取り組んだのは、型の整理、テストの追加、ログの見直し。",
    "急いだのは、移行、権限、性能試験。",
    # コード、リンクの字、半角空白を含む項目
    "このPRで変えたのは、`parse()`、`load()`、`save()`の3つ。",
    "このPRで変えたのは、`parse()`、`load()`、`save()` の3つ。",
    "変わったのは、[確かさ](https://example.com)、引用、語調。",
    "変わったのは、API の応答、ログの形式、設定ファイル。",
    # 動詞から作った名詞で終わる項目（読点だけで並べる形）
    "書き換えで変わったのは、言い回し、語調、段落の流れ。",
    "新しい設計で分けたのは、読み込み、変換、書き出し。",
    "あるのは、楽しみ、悲しみ、苦しみ。",
    # 「・」「，」で区切る形
    "書き換えで変わったのは、確かさ・引用・語調。",
    "書き換えで変わったのは、確かさ，引用，語調。",
    "目指したのは、速さ・軽さと静けさ。",
    # 「と」でつないでも、最後の項目に「の」がなければ並べとみる
    "変わったのは、確かさと引用の2つ。",
    "選んだのは、父の時計と母の指輪、兄の笑顔。",
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
    # 限定の「のみ」「だけ」「ばかり」で終える文
    "記事の公開設定を変えられるのは、管理者と編集者のみ。",
    "書き込めるのは、管理者、編集者、オーナーのみ。",
    "根拠にするのは、原文、依頼、提供された資料だけ。",
    "変わったのは、確かさ、引用、語調ばかり。",
    # 動詞から作った名詞や「・」でも、読点だけの2項目は当てない。述語まで書いた文も当てない
    "目指したのは、言い回し、流れ。",
    "今回選んだのは、速さ、軽さ、静けさです。",
    "変わったのは、`timeout`、`retry`、`backoff` の既定値です。",
    "目指したのは、速さ・軽さ。",
    # 読点がなく「と・や」で1回つなぎ、最後の項目に「の」がある1つの名詞句
    "印象に残ったのは、父と母の笑顔。",
    "比べたのは、AとBの速度。",
    "変わったのは、人と人の距離。",
    "問題になったのは、東京と大阪の差。",
)
SAMPLE = HITS[0] + "\n"
# 改行で折り返した文の1行目（述語は次の行にある）
WRAPPED = (
    "今回の改修で見直したのは、画面、帳票、通知\nの三つの仕組みです。\n",
    "- 今回の改修で見直したのは、画面と帳票\n  の二つです。\n",
    "変わったのは、確かさ、引用、語調\nそれ以外は同じ。\n",
)
# 句点がなくてもブロックの最後の文なら当てる（行の番号）
BLOCK_ENDS = (
    ("- [ ] 確認するのは、鍵、台帳、印鑑\n", 1),
    ("1. 手順で使うのは、鍵、台帳、印鑑\n2. 次に使うのは、ペン\n", 1),
    ("目指したのは、速さや軽さ、静けさ\n\n次の段落です。\n", 1),
    ("前置きの文です。\n目指したのは、速さや軽さ、静けさ\n", 2),
)
# 推敲の試験の原稿と同じ形。前提を前の段落に書いた文書と、書いていない文書
PREMISE_DRAFT = ("# 新しい推敲の手順を試した\n\n"
                 "先週から、チームの記事の推敲に新しい手順を使い始めた。5本の記事を通して前後を比べると、"
                 "変わった所と変わらなかった所がはっきり分かれた。\n\n"
                 "{}段落の順と見出しは、どの記事でも変わらなかった。\n\n"
                 "来週からは、手順の結果を編集の担当にも見てもらう。\n")
NO_PREMISE_DRAFT = ("# 新しい推敲の手順を試した\n\n"
                    "先週から、チームの記事の推敲に新しい手順を使い始めた。最初の1週間で5本の記事を通した。\n\n"
                    "書き換えの中で変動したのは、確かさ、引用、語調。\n\n"
                    "来週からは、手順の結果を編集の担当にも見てもらう。\n")
# 直前の文が問いか、「のは」の前の動詞の漢字を含む（前提がある）
WITH_PREMISE = (
    "何が変わったのか。変わったのは、確かさ、引用、語調。\n",
    "何が変わったか？ 変わったのは、確かさ、引用、語調。\n",
    "変わった点は3つある。変わったのは、確かさ、引用、語調。\n",
    "書き換えでは、いくつかの点が変わった。変わったのは、確かさ、引用、語調。\n",
    "「変わった点」は3つ。変わったのは、確かさ、引用、語調。\n",
    "何をリリースしたのか。リリースしたのは、認証、課金、通知。\n",
    "## 何が変わったのか\n\n変わったのは、確かさ、引用、語調。\n",
    "## 変わった所\n\n書き換えで変わったのは、確かさ、引用、語調。\n",
    "何を目指したのか\n\n目指したのは、速さ、軽さ、静けさ。\n",
    # 改行で折り返した前の文はつないで見る
    "前後を比べると、変わった所が\nはっきり分かれた。変わったのは、確かさ、引用、語調。\n",
    "前後を比べると、変わった所が\nはっきり分かれた。\n\n変わったのは、確かさ、引用、語調。\n",
    "- 変わった所をまとめる。\n- 変わったのは、確かさ、引用、語調。\n",
)
# 当たる文書（行の番号）。前の文はあるが、問いでも同じ動詞の漢字を含む文でもないものと、脚注を付けた項目
DOCUMENT_HITS = (
    ("前の段落の文です。書き換えの中で変動したのは、確かさ、引用、語調。\n", 1),
    ("動きはなかった。今回の調査で分かったのは、費用、期間、人手。\n", 1),
    ("# 新しい推敲の手順を試した\n\n書き換えの中で変動したのは、確かさ、引用、語調。\n", 3),
    # 「のは」の前に漢字がなければ、漢字では見ない
    ("## 結果\n\nリリースしたのは、認証、課金、通知。\n", 3),
    # 表を挟むと、その前の文は見ない
    ("変わったのは何か、という問いは置いておく。\n\n| a |\n|---|\n| b |\n\n変わったのは、確かさ、引用、語調。\n", 7),
    # 脚注は伏せた字として項目に数える
    ("変わったのは、確かさ、引用、語調[^1]。\n\n[^1]: 注\n", 1),
)


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

    def test_wrapped_first_lines_are_not_reported(self):
        for text in WRAPPED:
            with self.subTest(text=text):
                self.assertNotIn(RULE, rules(text))

    def test_sentences_without_a_full_stop_at_the_end_of_a_block(self):
        for text, line in BLOCK_ENDS:
            with self.subTest(text=text):
                self.assertEqual([f["line"] for f in findings(text) if f["rule"] == RULE], [line])

    def test_premise_in_the_previous_paragraph_keeps_the_sentence(self):
        for sentence in ("書き換えの中で変動したのは、確かさ、引用、語調。", "書き換えで変わったのは、確かさ、引用、語調。",
                         "書き換えの中で変わったのは、確かさ、引用、語調。"):
            with self.subTest(sentence=sentence):
                self.assertNotIn(RULE, rules(PREMISE_DRAFT.format(sentence)))
        self.assertEqual([(f["rule"], f["line"]) for f in findings(NO_PREMISE_DRAFT)], [(RULE, 5)])

    def test_previous_question_or_same_verb_keeps_the_sentence(self):
        for text in WITH_PREMISE:
            with self.subTest(text=text):
                self.assertNotIn(RULE, rules(text))

    def test_documents_that_are_reported(self):
        for text, line in DOCUMENT_HITS:
            with self.subTest(text=text):
                self.assertEqual([f["line"] for f in findings(text) if f["rule"] == RULE], [line])

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
                 "変わったのは、" * 5000 + "山、川、海です。\n", "変わったのは、" + "さとさや" * 10000 + "です\n",
                 "変わったのは、" + "山・" * 20000 + "です。\n", "変わったのは、" + "山 " * 20000 + "です。\n",
                 "変わったのは、" + "`a`、" * 10000 + "です。\n", "変わったのは、" + "見直し、" * 20000 + "です。\n")
        for text in texts:
            started = time.perf_counter()
            self.assertNotIn(RULE, rules(text))
            self.assertLess(time.perf_counter() - started, 10.0)

    def test_many_lines_finish_quickly(self):
        # 前の文を探すのは、句点などが2つ見つかるまで。同じ段落に5,000行あっても行の数に比例する時間で終わる
        texts = ("選んだのは、山、川、海。\n" * 5000, "あいう\n" * 5000 + "選んだのは、山、川、海。\n",
                 ("あいう\n" * 50 + "選んだのは、山、川、海。\n") * 100, "- 選んだのは、山、川、海\n" * 5000)
        for text in texts:
            started = time.perf_counter()
            # 2つ目からは、前の文に同じ動詞の漢字（選）があるので出さない
            self.assertEqual(rules(text).count(RULE), 1)
            self.assertLess(time.perf_counter() - started, 10.0)


if __name__ == "__main__":
    unittest.main()
