#!/usr/bin/env python3
"""v2.0.0: lint で、HTML の <details> の中の箇条書きを箇条書きの比率（list_ratio と excess_list）に数えない。

PR の説明文などで、本文の段落のあとに、根拠を <details> に畳んで「主張の要約: 識別子」の箇条書きを並べる書き方がある。
v1.1.2 はこの箇条書きも数えるので、本文に箇条書きがなくても excess_list が出ていた。

決めたこと（このファイルの試験で固定する）:

- <details> の中の箇条書きの行は list_lines と list_ratio に数えず、metrics の details_list_lines に別に数える。
  total_lines（非空行）と、char_count、bold_count、bold_per_1000 は今までどおり（<details> の中も数える）。
  list_ratio は「<details> の外の箇条書きの行 ÷（全体の非空行 − <details> の中の箇条書きの行）」。中に箇条書きを多く畳んでも、
  外の箇条書きの比率は薄まらない。この比率は v1.1.2 の比率より大きくならず、excess_list が新しく出ることはない。
  details_list_lines は、組になった <details> と </details> が1つでもある文書にだけ足す（ない文書の JSON は今までと同じ）。
- <details> の外の箇条書きは今までどおり数える。
- 開き（<details>）と閉じ（</details>）は、HTML のブロックの行（行頭から HTML を書いた行）でだけ見る。段落の中に書いた
  <details>、インラインのコード、コードの囲みとインデントしたコードの中、HTML のコメントの中、引用の中の <details> は
  見ない（今までどおり数える）。
- 閉じていない <details> と、開きのない </details> は、ほかの HTML のブロックと同じに扱う（中を数える）。
- 入れ子は内側から組にする。組になった範囲のどれかの中にある行を「中」とする。
- <details open> と大文字の <DETAILS> も同じに扱う。<details-panel> のような別の名前のタグは見ない。

文はすべてこのファイルで作った合成の文。実在の会社や商品の名前は使わない。
"""

from pathlib import Path
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
CORPUS = ROOT / "tests" / "corpus"
CHECK = SCRIPTS_DIR / "yomiyasu_check.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import yomiyasu_lint  # noqa: E402

OLD_METRIC_KEYS = ["char_count", "total_lines", "list_lines", "list_ratio", "bold_count", "bold_per_1000"]
NEW_METRIC_KEYS = OLD_METRIC_KEYS + ["details_list_lines"]

BODY = (
    "## 変更の概要\n"
    "\n"
    "設定の読み込みを1か所にまとめ、起動時に値を検証するようにしました。検証に失敗したときは、足りない項目の名前を"
    "標準エラーに出して止まります。これまでは読み込みが3か所に分かれていて、同じ項目を別々の既定値で読んでいました。\n"
    "\n"
    "既存の設定ファイルはそのまま読めます。新しい項目は省略でき、省略したときは今までと同じ既定値を使います。"
    "手元の設定を書き換える必要はありません。\n"
)
CLAIMS = (
    "- 設定を1か所で読む: config-loader\n"
    "- 起動時に値を検証する: validate-on-start\n"
    "- 足りない項目を名前で示す: missing-key-message\n"
    "- 既定値は今までと同じ: default-values\n"
    "- 古い設定ファイルも読める: legacy-format\n"
    "- 書き換えは要らない: no-migration\n"
)
# 本文の段落と、根拠を畳んだ <details> の中の「主張の要約: 識別子」の箇条書き（PR の説明文の形）
PR_DOC = (BODY + "\n<details>\n<summary>根拠（主張ごとの変更と試験）</summary>\n\n" + CLAIMS + "\n</details>\n")
# 同じ箇条書きを本文に置いたもの（<details> の行だけを除いた）
PR_DOC_OPEN = BODY + "\n" + CLAIMS


def lint(text, **options):
    return yomiyasu_lint.lint_text(text, **options)


def rules(result):
    return [finding["rule"] for finding in result["findings"]]


def as_div(text):
    """<details> を <div> にした文書（同じ行が HTML のブロックになり、中の行は今までどおり数える）。"""
    return text.replace("<details>", "<div>").replace("</details>", "</div>")


def call_lint(argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "stdout", out))
        stack.enter_context(mock.patch.object(sys, "stderr", err))
        if stdin is not None:
            stack.enter_context(mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")))
        try:
            code = yomiyasu_lint.main(argv)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class PrShapeTest(unittest.TestCase):
    """本文の段落と、<details> に畳んだ根拠の箇条書き。"""

    def test_lists_inside_details_do_not_raise_excess_list(self):
        result = lint(PR_DOC)
        self.assertNotIn("excess_list", rules(result))
        self.assertEqual(result["metrics"]["list_lines"], 0)
        self.assertEqual(result["metrics"]["details_list_lines"], 6)
        self.assertEqual(result["metrics"]["list_ratio"], 0.0)

    def test_denominator_and_other_metrics_are_unchanged(self):
        """分母の非空行、字数、太字は <details> の中も数える（<div> にした文書と同じ値）。"""
        result, plain = lint(PR_DOC)["metrics"], lint(as_div(PR_DOC))["metrics"]
        for key in ("char_count", "total_lines", "bold_count", "bold_per_1000"):
            self.assertEqual(result[key], plain[key], key)
        self.assertEqual(result["total_lines"], 9)

    def test_the_same_lists_in_the_body_still_raise_excess_list(self):
        result = lint(PR_DOC_OPEN)
        self.assertIn("excess_list", rules(result))
        self.assertEqual(result["metrics"]["list_lines"], 6)
        self.assertNotIn("details_list_lines", result["metrics"])

    def test_json_adds_the_key_after_the_old_keys(self):
        code, out, err = call_lint(["--json"], stdin=PR_DOC.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))
        metrics = json.loads(out)["metrics"]
        self.assertEqual(list(metrics), NEW_METRIC_KEYS)
        self.assertEqual(metrics["details_list_lines"], 6)

    def test_report_and_exit_codes(self):
        code, out, err = call_lint(["--strict"], stdin=PR_DOC.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("見直し候補: 0件", out)
        code, out, _ = call_lint(["--strict"], stdin=PR_DOC_OPEN.encode("utf-8"))
        self.assertEqual(code, 1)
        self.assertIn("excess_list", out)

    def test_doc_types_have_nothing_to_skip(self):
        """種類で excess_list を外す pr でも、外す候補がもとからない（外した件数は0）。"""
        for doc_type in ("pr", "promo", "article"):
            with self.subTest(doc_type=doc_type):
                result = lint(PR_DOC, doc_type=doc_type)
                self.assertNotIn("excess_list", rules(result))
                self.assertEqual(result["context"]["skipped_by_doc_type"].get("excess_list", 0), 0)
        self.assertEqual(lint(PR_DOC_OPEN, doc_type="pr")["context"]["skipped_by_doc_type"], {"excess_list": 1})

    def test_analyze_markdown_metrics_matches_lint(self):
        self.assertEqual(yomiyasu_lint.analyze_markdown_metrics(PR_DOC), lint(PR_DOC)["metrics"])


class OutsideListsTest(unittest.TestCase):
    """<details> の外の箇条書きは今までどおり数える。"""

    # 外の地の文が300字を超える文書にしてある（<details> の中の箇条書きは、地の文の量の門にも数えないため。外が短い文書は
    # ShortOutsideGateTest で見る）
    DOC = (BODY + "\n変更のあとは、起動のたびに設定を一度だけ読み、各部品は読み込んだ値を受け取って使います。部品ごとに設定を"
           "読み直すことはありません。値を変えたときは、起動し直すと新しい値が使われます。\n"
           "\n- 読み込みを1か所にした\n- 起動時に検証する\n- 既定値は同じ\n- 古い設定も読める\n"
           "\n<details>\n<summary>根拠</summary>\n\n" + CLAIMS + "\n</details>\n")

    def test_outside_lists_still_raise_excess_list(self):
        result = lint(self.DOC)
        self.assertIn("excess_list", rules(result))
        self.assertEqual(result["metrics"]["list_lines"], 4)
        self.assertEqual(result["metrics"]["details_list_lines"], 6)
        self.assertEqual(result["metrics"]["total_lines"], 14)
        self.assertEqual(result["metrics"]["list_ratio"], round(4 / 8, 3))

    def test_snippet_says_details_lines_are_not_counted(self):
        finding = [item for item in lint(self.DOC)["findings"] if item["rule"] == "excess_list"][0]
        self.assertEqual(finding["snippet"], "リスト行: 4 / 全非空行: 8（<details> の中の箇条書き6行は数えていません）")
        self.assertIn("箇条書きの比率（50.0%）", finding["message"])

    def test_snippet_is_unchanged_without_lists_inside(self):
        doc = (BODY + "\n- 一つ目\n- 二つ目\n- 三つ目\n\n<details>\n<summary>根拠</summary>\n\n"
               "起動時の検証で足りない項目の名前を出すことを確かめる試験と、古い設定ファイルをそのまま読めることを"
               "確かめる試験を足しました。どちらも手元の環境と自動の試験の両方で通ることを確かめています。"
               "試験の名前は変更の一覧に書きました。\n\n</details>\n")
        result = lint(doc)
        self.assertEqual(result["metrics"]["details_list_lines"], 0)
        finding = [item for item in result["findings"] if item["rule"] == "excess_list"][0]
        self.assertEqual(finding["snippet"], "リスト行: 3 / 全非空行: 7")

    def test_counts_add_up_to_the_old_counts(self):
        """外の箇条書きと中の箇条書きを足すと、<div> にした文書（今までの数え方）の箇条書きの行の数になる。"""
        for doc in (PR_DOC, self.DOC, NestedTest.DOC):
            with self.subTest(doc=doc[-40:]):
                result, plain = lint(doc)["metrics"], lint(as_div(doc))["metrics"]
                self.assertEqual(result["list_lines"] + result["details_list_lines"], plain["list_lines"])
                self.assertLessEqual(result["list_ratio"], plain["list_ratio"])


class NestedTest(unittest.TestCase):
    DOC = (
        "本文の段落です。設定の読み込みを1か所にまとめました。\n"
        "\n"
        "<details>\n<summary>外側</summary>\n\n"
        "- 外側の一つ目\n"
        "\n"
        "<details>\n<summary>内側</summary>\n\n"
        "- 内側の一つ目\n- 内側の二つ目\n"
        "\n</details>\n\n"
        "- 内側を閉じたあとの外側の項目\n"
        "\n</details>\n\n"
        "- 外側を閉じたあとの本文の項目\n"
    )

    def test_lines_in_any_pair_are_inside(self):
        metrics = lint(self.DOC)["metrics"]
        self.assertEqual(metrics["details_list_lines"], 4)
        self.assertEqual(metrics["list_lines"], 1)

    def test_unclosed_inner_details(self):
        """閉じは内側の開きと組になる。組にならなかった外側の開きは見ない（外側だけの範囲は今までどおり数える）。"""
        doc = ("本文です。\n\n<details>\n<summary>外側</summary>\n\n- 外側の項目\n\n"
               "<details>\n<summary>内側</summary>\n\n- 内側の項目\n\n</details>\n\n- あとの項目\n")
        metrics = lint(doc)["metrics"]
        self.assertEqual(metrics["details_list_lines"], 1)
        self.assertEqual(metrics["list_lines"], 2)


class NotADetailsRegionTest(unittest.TestCase):
    """組にならない <details> と、HTML のブロックの行でない <details> は見ない。出力は <div> にした文書と同じ。"""

    def assert_counted_as_before(self, doc):
        result, plain = lint(doc), lint(as_div(doc))
        self.assertNotIn("details_list_lines", result["metrics"])
        self.assertEqual(result["metrics"], plain["metrics"])
        self.assertEqual(rules(result), rules(plain))
        self.assertIn("excess_list", rules(result))

    def test_unclosed_details(self):
        self.assert_counted_as_before(BODY + "\n<details>\n<summary>根拠</summary>\n\n" + CLAIMS)

    def test_close_without_open(self):
        self.assert_counted_as_before(BODY + "\n" + CLAIMS + "\n</details>\n")

    def test_open_in_a_fenced_code_block(self):
        doc = (BODY + "\n```html\n<details>\n<summary>根拠</summary>\n```\n\n" + CLAIMS + "\n</details>\n")
        self.assert_counted_as_before(doc)
        self.assertNotIn("details_list_lines", lint(doc)["metrics"])

    def test_whole_example_in_a_fenced_code_block(self):
        doc = BODY + "\n```html\n<details>\n<summary>根拠</summary>\n\n- 例の項目\n\n</details>\n```\n\n" + CLAIMS
        result = lint(doc)
        self.assertNotIn("details_list_lines", result["metrics"])
        self.assertEqual(result["metrics"]["list_lines"], 6)

    def test_open_in_an_indented_code_block(self):
        doc = BODY + "\n    <details>\n    <summary>根拠</summary>\n\n" + CLAIMS + "\n</details>\n"
        result = lint(doc)
        self.assertNotIn("details_list_lines", result["metrics"])
        self.assertIn("excess_list", rules(result))

    def test_inline_code_in_a_paragraph(self):
        doc = BODY + "\n根拠は `<details>` に畳みます。\n\n" + CLAIMS + "\n</details>\n"
        self.assert_counted_as_before(doc)

    def test_inline_tag_in_a_paragraph(self):
        """段落の途中に書いた <details>（タグの名前を地の文で書いたもの）は開きにしない。"""
        doc = BODY + "\n根拠は <details> に畳みました。\n\n" + CLAIMS + "\n</details>\n"
        self.assert_counted_as_before(doc)

    def test_html_comment(self):
        doc = BODY + "\n<!-- <details> -->\n\n" + CLAIMS + "\n<!-- </details> -->\n"
        self.assert_counted_as_before(doc)

    def test_multiline_html_comment(self):
        doc = BODY + "\n<!--\n<details>\n-->\n\n" + CLAIMS + "\n<!--\n</details>\n-->\n"
        self.assert_counted_as_before(doc)

    def test_raw_text_element(self):
        doc = BODY + "\n<script>\nconst tag = '<details>';\n</script>\n\n" + CLAIMS + "\n</details>\n"
        self.assert_counted_as_before(doc)

    def test_details_in_a_quote(self):
        """引用の中の <details> は見ない（引用の行は、もとから比率に数えない）。"""
        doc = BODY + "\n> <details>\n> <summary>根拠</summary>\n\n" + CLAIMS + "\n</details>\n"
        self.assert_counted_as_before(doc)

    def test_other_tag_names(self):
        doc = BODY + "\n<details-panel>\n<summary>根拠</summary>\n\n" + CLAIMS + "\n</details-panel>\n"
        result = lint(doc)
        self.assertNotIn("details_list_lines", result["metrics"])
        self.assertIn("excess_list", rules(result))


class DetailsFormsTest(unittest.TestCase):
    def test_open_attribute_and_upper_case(self):
        for open_tag, close_tag in (("<details open>", "</details>"), ("<DETAILS>", "</DETAILS>"),
                                    ('<details class="evidence">', "</details >")):
            with self.subTest(open_tag=open_tag):
                doc = BODY + "\n" + open_tag + "\n<summary>根拠</summary>\n\n" + CLAIMS + "\n" + close_tag + "\n"
                result = lint(doc)
                self.assertNotIn("excess_list", rules(result))
                self.assertEqual(result["metrics"]["details_list_lines"], 6)

    def test_summary_on_the_same_line(self):
        doc = BODY + "\n<details><summary>根拠</summary>\n\n" + CLAIMS + "\n</details>\n"
        self.assertEqual(lint(doc)["metrics"]["details_list_lines"], 6)

    def test_close_after_a_list_without_a_blank_line(self):
        doc = BODY + "\n<details>\n<summary>根拠</summary>\n\n" + CLAIMS + "</details>\n"
        result = lint(doc)
        self.assertEqual(result["metrics"]["details_list_lines"], 6)
        self.assertNotIn("excess_list", rules(result))

    def test_lists_inside_the_html_block_are_not_counted_anywhere(self):
        """<summary> のすぐあとに空行がないと、箇条書きの形の行も HTML のブロックになり、今までも数えていない。"""
        doc = BODY + "\n<details>\n<summary>根拠</summary>\n" + CLAIMS + "</details>\n"
        result, plain = lint(doc)["metrics"], lint(as_div(doc))["metrics"]
        self.assertEqual(result["details_list_lines"], 0)
        self.assertEqual(result["list_lines"], plain["list_lines"])
        self.assertEqual(result["total_lines"], plain["total_lines"])

    def test_details_on_one_line(self):
        doc = BODY + "\n<details><summary>根拠</summary>試験を足しました。</details>\n\n" + CLAIMS
        result = lint(doc)
        self.assertEqual(result["metrics"]["details_list_lines"], 0)
        self.assertEqual(result["metrics"]["list_lines"], 6)
        self.assertIn("excess_list", rules(result))

    def test_details_inside_a_list_item(self):
        doc = (BODY + "\n- 変更の要約\n\n  <details>\n  <summary>根拠</summary>\n\n"
               "  - 設定を1か所で読む: config-loader\n  - 起動時に値を検証する: validate-on-start\n"
               "  - 既定値は今までと同じ: default-values\n\n  </details>\n")
        metrics = lint(doc)["metrics"]
        self.assertEqual(metrics["details_list_lines"], 3)
        self.assertEqual(metrics["list_lines"], 1)

    def test_other_rules_still_look_inside(self):
        """箇条書きの比率のほかの規則は、今までどおり <details> の中も見る。"""
        doc = BODY + "\n<details>\n<summary>根拠</summary>\n\n- この変更は設計の解像度を上げます。\n\n</details>\n"
        self.assertIn("slop_vocabulary", rules(lint(doc)))


class NoDetailsUnchangedTest(unittest.TestCase):
    """<details> のない文書の metrics は今までと同じキー（tests/corpus の出力は test_v200_doc_type の fixture で照らす）。"""

    def test_corpus_has_no_details_and_keeps_the_old_keys(self):
        files = sorted(CORPUS.rglob("*.md"))
        self.assertEqual(len(files), 163)
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("<details", text.lower(), path.name)
            self.assertEqual(list(lint(text)["metrics"]), OLD_METRIC_KEYS, path.name)

    def test_plain_documents_keep_the_old_keys(self):
        for doc in (PR_DOC_OPEN, "", "本文です。\n", "<div>\n\n- 項目\n\n</div>\n"):
            with self.subTest(doc=doc[:20]):
                self.assertEqual(list(lint(doc)["metrics"]), OLD_METRIC_KEYS)


class CheckPassesLintTest(unittest.TestCase):
    """check の lint の節も同じ（check は lint を子プロセスで動かす）。"""

    def test_check_run_has_no_excess_list_for_details_lists(self):
        with tempfile.TemporaryDirectory() as folder:
            source, final = Path(folder) / "source.md", Path(folder) / "final.md"
            source.write_bytes("## 変更の概要\n\n設定の読み込みを3か所から1か所にまとめます。\n".encode("utf-8"))
            final.write_bytes(PR_DOC.encode("utf-8"))
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            env.pop("YOMIYASU_STATE_DIR", None)
            process = subprocess.run(
                [sys.executable, "-B", str(CHECK), "run", "--source", str(source), "--final", str(final),
                 "--state-dir", str(Path(folder) / "state")],
                cwd=folder, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            out = process.stdout.decode("utf-8")
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
            self.assertIn("lint（最終稿）候補0件", out)
            self.assertNotIn("excess_list", out)


if __name__ == "__main__":
    unittest.main()


SHORT_PR = (
    "## 変更の概要\n\n設定の読み込みを1か所にまとめました。\n\n## 変更点\n\n- 起動時に値を検証する\n- 足りない項目の名前を出す\n\n"
    "<details>\n<summary>根拠（試験の対応）</summary>\n\n"
    + "".join("- 試験{0}: 設定の読み込みで、項目{0}の既定値が今までと同じことを確かめる\n".format(n) for n in range(1, 9))
    + "\n</details>\n"
)


class ShortOutsideGateTest(unittest.TestCase):
    """箇条書きの比率の判定は、地の文の量の門（300字）でも <details> の中の箇条書きを数えない。

    外の地の文が短く、根拠の箇条書きを <details> に畳んだ PR の説明文で、畳んだ箇条書きの字数で門を通って excess_list が
    出ないこと（反証で見つけた例）。<details> のない文書の門は今までどおり（字数は char_count と同じ）。"""

    def test_short_body_with_folded_lists_has_no_excess_list(self):
        result = lint(SHORT_PR)
        self.assertNotIn("excess_list", rules(result))
        self.assertEqual(result["metrics"]["details_list_lines"], 8)
        self.assertEqual(list(result["metrics"]), NEW_METRIC_KEYS)

    def test_strict_exit_code_is_zero(self):
        code, out, err = call_lint(["--strict"], stdin=SHORT_PR.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("excess_list", out)

    def test_long_body_with_outside_lists_still_raises(self):
        doc = BODY + "\n" + CLAIMS + "\n<details>\n<summary>根拠</summary>\n\n" + CLAIMS + "\n</details>\n"
        self.assertIn("excess_list", rules(lint(doc)))

    def test_without_details_the_gate_is_unchanged(self):
        open_doc = SHORT_PR.replace("<details>\n<summary>根拠（試験の対応）</summary>\n\n", "").replace("\n</details>\n", "\n")
        self.assertIn("excess_list", rules(lint(open_doc)))
