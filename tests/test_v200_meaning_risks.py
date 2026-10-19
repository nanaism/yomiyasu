#!/usr/bin/env python3
"""v2.0.0: diff の「意味が変わる恐れ」（meaning_risks）の試験（設計 2.5、2.7、2.8、6.4）。

指示書10章の種類（数字、日付、固有名詞、否定、条件、例外、確度、実施済みと未確認、元にない書き手の気持ちの追加）を含む。
候補は「確かめる場所」で、意味が変わったという判定ではない。拾えない例も、限界として期待値に固定する。
v1.1.2 の diff() は meaning_risks を返さないので、この試験はすべて失敗する。文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
from unittest import mock
import os
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


RISK_KEYS = {"kind", "subkind", "old_line", "new_line", "old", "new", "detail", "basis"}
SUBKINDS = {
    "number": {"replaced", "added", "lost", "order"},
    "sentence_type": {"marks", "question"},
    "certainty": {"strengthened"},
    "certainty_review": {"strengthened", "weakened"},
    "quote": {"changed", "lost"},
    "state": {"lost"},
    "promise": {"added", "guarantee", "prevention"},
    "claim": {"causal", "evaluation", "general"},
    "protected": {"code", "inline_code", "url", "link", "frontmatter", "html", "quote"},
    "modality": {"permission_lost", "permission_added", "ability_lost"},
    "modality_review": {"ability_lost"},
}
# diff の詰め（10.7、追加文書 1.4）: 否定対比の主張の逆転（contrast_reversal）と気持ちの創作（feeling）を足した。
# どちらも意味が変わる恐れの節に出すが、--fail-on=meaning-risk には数えない
# v2.1.0: 許可・能力の言い方の変化（modality は数える。事実や仕様を述べる種類でない文書の能力の消えは modality_review で数えない）を足した
KINDS = {"number", "negation", "swap", "sentence_type", "protected", "contrast_reversal", "feeling", "certainty", "certainty_review", "quote", "state", "promise", "claim",
         "modality", "modality_review"}

# 2.8 の meaning_risks の要素の例（入力は 2.7 の例A）
EXAMPLE_A_RISK = {"kind": "number", "subkind": "replaced", "old_line": 1, "new_line": 1,
                  "old": "保存期間は3日です。", "new": "保存期間は30日です。",
                  "detail": {"removed": ["3日"], "added": ["30日"]}, "basis": None}


def corpus_pairs():
    pairs = []
    for name in sorted(os.listdir(CORPUS / "yomiyasu_rewritten")):
        if not name.endswith(".md"):
            continue
        source = CORPUS / "blacklist_ai" / (name[:-6] + ".md") if name.endswith("_bl.md") else CORPUS / "raw_ai" / name
        pairs.append((source.read_bytes().decode("utf-8"),
                      (CORPUS / "yomiyasu_rewritten" / name).read_bytes().decode("utf-8"), name))
    return pairs


class RiskCase(unittest.TestCase):
    def result(self, before, after):
        """元と後は1行の文。各ファイルの末尾に改行がある形で比べる（2.7 の例と同じ）。"""
        result = yomiyasu_diff.diff(before + "\n", after + "\n")
        for key in ("meaning_risks", "status", "full_diff"):
            self.assertTrue(key in result, "v2.0.0 の diff() は %s を返す（設計 2.8）。今のキー: %s"
                            % (key, list(result)))
        return result

    def risks(self, before, after):
        return self.result(before, after)["meaning_risks"]

    def need_v2_diff(self):
        """subTest で同じ失敗を何度も出さないよう、先に1回だけ確かめる。"""
        self.result("会議は3時に始まります。", "会議は4時に始まります。")

    @staticmethod
    def kinds(risks):
        return [(risk["kind"], risk.get("subkind")) for risk in risks]

    def report(self, result):
        text = yomiyasu_diff.report(result)
        self.assertNotEqual(text, "（候補なし）")
        return text.split("\n")

    def changed_lines(self, result):
        return [line for hunk in result["full_diff"]["hunks"] for line in hunk["old_lines"] + hunk["new_lines"]]


class TestNumbers(RiskCase):
    """2.5.2 数値（kind number）。"""

    REPLACED = (
        ("保存期間は3日です。", "保存期間は30日です。"),
        ("待ち時間の上限を3にする。", "待ち時間の上限を5にする。"),
        ("在庫は３です。", "在庫は３０です。"),
        ("割引は10%です。", "割引は20%です。"),
        ("公開日は2026年10月12日です。", "公開日は2026年10月21日です。"),
        ("返事の期限は3日です。", "返事の期限は3週間です。"),
        # 反証レビュー F1: 一覧にない英字の単位が続く値（単位なしの数として比べる）
        ("タイムアウトは30sです。", "タイムアウトは60sです。"),
        ("メモリは8GiBです。", "メモリは16GiBです。"),
        # 反証レビュー F2・risk 1: 「，」「．」の直後の値
        ("候補日は3日，5日，7日です。", "候補日は3日，50日，7日です。"),
        ("参加者は，30人だった．", "参加者は，50人だった．"),
        # 反証レビュー F4: 空白なしで日本語が続く URL のあとの値
        ("手順はhttps://example.com/guideにあり、保存期間は3日です。", "手順はhttps://example.com/guideにあり、保存期間は30日です。"),
    )
    NOT_NUMBER = (
        ("価格は1,000円です。", "価格は1000円です。"),
        ("期限は３日です。", "期限は3日です。"),
        ("再試行は一回です。", "再試行は1回です。"),
        # 原文の別の場所にある数を書き足した文。1つ目は組になる文に書き足した形（2.5.2 の added）、
        # 2つ目は文を丸ごと足した形（2.5.2 の最後の項。文書全体の値を集合で比べる読み方。questions-diff.md 18）
        ("保存期間は3日です。\n\n設定を確認します。", "保存期間は3日です。\n\n設定を確認し、3日ごとに見直します。"),
        ("保存期間は3日です。", "保存期間は3日です。見直しは3日ごとに行います。"),
        ("1. 設定を開く。\n2. 値を変える。", "設定を開き、値を変える。"),
        ("設定を一度確認する。", "設定を確認する。"),
        # 反証レビュー F3: 太字を外す・足すだけの直し（数と単位の間の ** は読み飛ばす）
        ("保存期間は**3**日です。", "保存期間は3日です。"),
        ("保存期間は3日です。", "保存期間は**3**日です。"),
        ("割引は**30**%です。", "割引は30%です。"),
    )

    def test_changed_values_are_number(self):
        self.need_v2_diff()
        for before, after in self.REPLACED:
            with self.subTest(before=before, after=after):
                self.assertIn(("number", "replaced"), self.kinds(self.risks(before, after)))

    def test_example_a_element(self):
        self.assertEqual(self.risks("保存期間は3日です。", "保存期間は30日です。"), [EXAMPLE_A_RISK])

    def test_order(self):
        result = self.result("Aは3日、Bは5日です。", "Aは5日、Bは3日です。")
        [risk] = [risk for risk in result["meaning_risks"] if risk["kind"] == "number"]
        self.assertEqual(risk["subkind"], "order")
        self.assertEqual(risk["detail"], {"old_order": ["3日", "5日"], "new_order": ["5日", "3日"]})
        self.assertIn("- 数値の並びが変わった（1行目）: 3日、5日 → 5日、3日", self.report(result))

    def test_value_lost_with_a_removed_sentence(self):
        result = self.result("会議は来週です。参加者は8名です。", "会議は来週です。")
        lost = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("number", "lost")]
        self.assertEqual(len(lost), 1, result["meaning_risks"])
        self.assertIn("8名", lost[0]["detail"]["removed"])
        self.assertIn("- 消えた数値（元1行目）: 8名", self.report(result))

    def test_value_added_that_is_not_in_the_original(self):
        result = self.result("会議は来週です。", "会議は来週です。参加者は8名です。")
        added = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("number", "added")]
        self.assertEqual(len(added), 1, result["meaning_risks"])
        self.assertIn("8名", added[0]["detail"]["added"])
        self.assertIn("- 元にない数値（後1行目）: 8名", self.report(result))

    def assert_paired_number(self, before, after, subkind, side, value, label):
        """組になった文の中で値が消えた、または増えた（2.5.2 の lost と added の本来の定義）。
        レポートの行番号の書き方（「1行目」か「元1行目」か）は組の文では決まっていないので、行の頭と末尾だけを見る。"""
        result = self.result(before, after)
        numbers = [risk for risk in result["meaning_risks"] if risk["kind"] == "number"]
        self.assertEqual(len(numbers), 1, result["meaning_risks"])
        risk = numbers[0]
        self.assertEqual(risk["subkind"], subkind, risk)
        self.assertEqual((risk["old"], risk["new"]), (before, after), "組になった文を old と new に入れる（2.8）")
        self.assertEqual((risk["old_line"], risk["new_line"]), (1, 1))
        self.assertEqual(risk["detail"][side], [value])
        lines = [line for line in self.report(result) if line.startswith("- " + label + "（") and line.endswith("）: " + value)]
        self.assertEqual(len(lines), 1, self.report(result))
        # 10.4 S7: 片側だけの値は、その側の行番号（lost は元、added は後）
        where = "元1行目" if subkind == "lost" else "後1行目"
        self.assertEqual(lines[0], "- {}（{}）: {}".format(label, where, value))

    def test_lost_and_added_use_the_line_of_their_own_side(self):
        """10.4 S7: 行番号が前後で違うとき、消えた数値は元の行番号、元にない数値は後の行番号だけを書く。"""
        result = yomiyasu_diff.diff("# 予定\n\n会議は来週です。参加者は8名です。\n", "# 予定\n会議は来週です。\n")
        lost = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("number", "lost")]
        self.assertEqual(len(lost), 1, result["meaning_risks"])
        self.assertEqual(lost[0]["old_line"], 3)
        self.assertIn("- 消えた数値（元3行目）: 8名", self.report(result))
        result = yomiyasu_diff.diff("# 予定\n会議は来週です。\n", "# 予定\n\n会議は来週です。参加者は8名です。\n")
        added = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("number", "added")]
        self.assertEqual(len(added), 1, result["meaning_risks"])
        self.assertEqual(added[0]["new_line"], 3)
        self.assertIn("- 元にない数値（後3行目）: 8名", self.report(result))

    def test_values_only_in_one_document_are_taken_as_a_set(self):
        """10.4 S4: 文書全体で後にだけある値は集合で取る。同じ新しい値を2回書いても、候補は1つで、値は1回だけ。"""
        result = self.result("会議は来週です。", "会議は来週です。参加者は8名です。定員も8名です。")
        added = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("number", "added")]
        self.assertEqual(len(added), 1, result["meaning_risks"])
        self.assertEqual(added[0]["detail"]["added"], ["8名"])

    def test_value_lost_in_a_paired_sentence(self):
        self.assert_paired_number("設定を3回確認します。", "設定を確認します。", "lost", "removed", "3回", "消えた数値")

    def test_value_added_in_a_paired_sentence(self):
        self.assert_paired_number("設定を確認します。", "設定を3回確認します。", "added", "added", "3回", "元にない数値")

    def test_order_of_values_at_clause_heads(self):
        """反証レビュー risk 3: 節の頭にある数値を入れ替えた文は number/order（2.5.2「多重集合は同じで並びが違う」）。
        数値の直前の2字が同じ「節の頭」でも、数値のあとの語（読点か句点まで）で結び付きを見る。"""
        self.need_v2_diff()
        for before, after in (("10時から設計レビュー、14時からテストを行う。", "14時から設計レビュー、10時からテストを行う。"),
                              ("3日後にAを、5日後にBを出す。", "5日後にAを、3日後にBを出す。"),
                              ("2025年にAを、2026年にBを出す。", "2026年にAを、2025年にBを出す。")):
            with self.subTest(before=before):
                self.assertIn(("number", "order"), self.kinds(self.risks(before, after)))

    def test_order_of_values_in_table_cells(self):
        """反証レビュー E5: 表の行で2つのセルの値を入れ替えると number/order（表の行は何列目かで結び付きを見る）。"""
        before = "| 項目 | 本番 | 検証 |\n|---|---|---|\n| 保存期間 | 30日 | 3日 |\n"
        after = "| 項目 | 本番 | 検証 |\n|---|---|---|\n| 保存期間 | 3日 | 30日 |\n"
        result = yomiyasu_diff.diff(before, after)
        self.assertIn(("number", "order"), self.kinds(result["meaning_risks"]))
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_values_on_unchanged_lines_are_not_number(self):
        """反証レビュー E4: 変わっていない行をコードの囲みに入れただけ（または囲みを外しただけ）では、その行の値を
        「消えた数値」「元にない数値」にしない（2.5 の前書き「対象は全文差分で変わった塊の中だけ」）。コードの変化は protected で出す。"""
        plain = "設定の例を示します。\nretry = 3\n"
        fenced = "設定の例を示します。\n\n```\nretry = 3\n```\n"
        for before, after in ((plain, fenced), (fenced, plain)):
            with self.subTest(before=before):
                result = yomiyasu_diff.diff(before, after)
                self.assertNotIn("number", [kind for kind, _ in self.kinds(result["meaning_risks"])], result["meaning_risks"])
                self.assertIn(("protected", "code"), self.kinds(result["meaning_risks"]))
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_url_followed_by_japanese_is_not_a_url_change(self):
        """反証レビュー F4: URL を変えずに、URL のあとに空白なしで続く本文の値だけを変えたときは、URL の変化を出さない。"""
        result = self.result("手順はhttps://example.com/guideにあり、保存期間は3日です。",
                             "手順はhttps://example.com/guideにあり、保存期間は30日です。")
        self.assertEqual(self.kinds(result["meaning_risks"]), [("number", "replaced")])
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        result = self.result("手順はhttps://example.com/aにある。", "手順はhttps://example.com/bにある。")
        self.assertEqual(self.kinds(result["meaning_risks"]), [("protected", "url")])

    def test_clause_swap_keeps_the_word_number_links(self):
        """節を入れ替えただけで、語と数値の結び付きが同じなら number/order にしない（正解つきの書き換えの組の節の入れ替えで誤検知だった）。"""
        self.need_v2_diff()
        for before, after in (("応答は504を返したが、上限は20接続だった。", "上限は20接続だったが、応答は504を返した。"),
                              ("Aは3日、Bは5日です。", "Bは5日、Aは3日です。")):
            with self.subTest(before=before):
                self.assertNotIn(("number", "order"), self.kinds(self.risks(before, after)))

    def test_notation_only_and_values_found_elsewhere_are_not_number(self):
        self.need_v2_diff()
        for before, after in self.NOT_NUMBER:
            with self.subTest(before=before, after=after):
                result = self.result(before, after)
                self.assertNotIn("number", [kind for kind, _ in self.kinds(result["meaning_risks"])])
                self.assertTrue(result["full_diff"]["hunks"], "数値の候補にしなくても全文差分には出る")


class TestNegation(RiskCase):
    """2.5.3 否定（kind negation）。同じ語の肯定と否定の入れ替わりだけを狭く取る（0.3の4）。"""

    FOUND = (
        ("ログを送信します。", "ログを送信しません。"),
        ("この端末で再生できます。", "この端末で再生できません。"),
        ("明日は会場へ行く。", "明日は会場へ行かない。"),
        ("設定を変更してください。", "設定を変更しないでください。"),
        ("この手順は確認済みです。", "この手順は未確認です。"),
        ("この機能は対応済みです。", "この機能は未対応です。"),
        ("この設定は有効です。", "この設定は無効です。"),
        # 反証レビュー F9・risk 2: 1つの文の中で2つの否定を入れ替えた形（文全体の印の数は同じ）
        ("保存せず、送信する。", "保存し、送信しない。"),
        ("Aは対応しているが、Bは対応していない。", "Aは対応していないが、Bは対応している。"),
        ("Windowsでは使えるが、macOSでは使えない。", "Windowsでは使えないが、macOSでは使える。"),
    )
    NOT_FOUND = (
        ("失敗ではなく、学びだ。", "学びだ。"),
        ("毎日記録しなければならない。", "毎日記録する必要がある。"),
        ("毎日記録しなければなりません。", "毎日記録する必要があります。"),
        ("残りの時間は少ない。", "残りの時間はわずかだ。"),
        ("原因は設定かもしれない。", "原因は設定の可能性がある。"),
        ("在庫が少ない。", "在庫が足りない。"),
        ("まず、設定を開いて値を変える。", "設定を開いて、まず値を変える。"),
        ("列の幅を固定して崩れを防ぐ。", "列の幅を固定してずれないようにする。"),
        # コーパス48組で誤検知だった形。印の数が同じ言い換え、文字の対応で1字だけ同じとされた箇所、
        # 印の手前に読点を足しただけの変更
        ("障害対応の間は調査が止まった。", "障害が起きている間は調査が進まなかった。"),
        ("処理不能なデータが後続を妨げる。", "処理できないデータが後続を止める。"),
        ("認証を同期呼び出しから非同期キューでの実行に変えた。", "認証を同期呼び出しから、非同期キューでの実行に変えた。"),
        ("本流のキューを詰まらせない。", "本流のキューが詰まらないようにします。"),
        ("再投入しても二重反映は起きない。", "再投入しても二重に反映されることはない。"),
        # diff の詰め（反証で見つけた例）: 句点の前の規則が言い換えを否定に出さない
        ("結果は変わらない。", "結果は同じだ。"),
        ("値が一致しない。", "値が異なる。"),
        ("この確認は欠かせない。", "この確認は重要だ。"),
        ("変更して構いません。", "変更してよいです。"),
        ("ファイルは残らない。", "ファイルは消える。"),
        # 「未来」は否定の「未」にしない
        ("将来の計画を立てる。", "未来の計画を立てる。"),
    )

    def test_negation_found(self):
        self.need_v2_diff()
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertIn("negation", [kind for kind, _ in self.kinds(self.risks(before, after))])

    def test_negation_not_found(self):
        self.need_v2_diff()
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertNotIn("negation", [kind for kind, _ in self.kinds(self.risks(before, after))])

    def test_detail_and_report_line_widen_to_word_edges(self):
        """10.2 D7: detail は変わった箇所を語の切れ目まで広げたもの（左へ平仮名4字まで、続く漢字・片仮名の並び全部。
        右へ平仮名3字まで。句読点と空白で止める）。レポートの行も同じ形。"""
        result = self.result("データを保存します。", "データを保存しません。")
        [risk] = [risk for risk in result["meaning_risks"] if risk["kind"] == "negation"]
        self.assertEqual(risk["detail"], {"old": "保存します", "new": "保存しません"})
        self.assertEqual((risk["old"], risk["new"]), ("データを保存します。", "データを保存しません。"))
        self.assertEqual((risk["old_line"], risk["new_line"]), (1, 1))
        self.assertIsNone(risk["subkind"])
        report = self.report(result)
        index = report.index("- 否定の有無が変わった（1行目）: 保存します → 保存しません")
        self.assertEqual(report[index + 1:index + 3], ["  元: データを保存します。", "  後: データを保存しません。"])

    def test_suru_to_shinai_is_found_by_the_end_rule(self):
        """10.2 D1: 句点の前の規則を入れると決めた（コーパス48組で、規則ありの negation 2件が、LIMIT=2 だけの1件の2倍を
        超えない）。「する → しない」は negation として出る。全文差分にも出る。"""
        result = self.result("設定を変更する。", "設定を変更しない。")
        self.assertNotEqual(result["status"], "no_change")
        self.assertIn("設定を変更しない。", self.changed_lines(result))
        [risk] = [risk for risk in result["meaning_risks"] if risk["kind"] == "negation"]
        self.assertEqual(risk["detail"], {"old": "変更する", "new": "変更しない"})
        self.assertIn("- 否定の有無が変わった（1行目）: 変更する → 変更しない", self.report(result))

    def test_end_rule_also_applies_to_items_without_a_period(self):
        """句点のない箇条書きの項目でも、文の終わりの直前5字の中の変化なら数える。"""
        result = yomiyasu_diff.diff("- ログを保存する\n", "- ログを保存しない\n")
        self.assertIn("negation", [kind for kind, _ in self.kinds(result["meaning_risks"])])

    def test_negation_after_an_inserted_block_in_a_full_rewrite(self):
        """反証レビュー E1: 全面書き換えの途中に、空行のない9行の箇条書きを足しても、そのあとの段落が1つの塊にまとまらず、
        段落ごとの hunk になる。後ろの段落の否定（確認します → 確認しません）が出る。数値（節の番号）は変えていないので出ない。

        diff の詰めで入力を1つ変えた。句点の前の規則を「印でない字の違いが平仮名だけ（漢字・
        片仮名は両側で同じ）」に絞ったので、前の入力「値を確認します → 値を確かめません」（語幹ごと書き換えた否定）は、
        2.5.3 の残る限界どおり negation に出なくなった（前は出ていた。前後を測って記録した）。
        この試験の狙いは行の対応なので、15節の後を「値を確認しません」にした。"""
        words = ("開く", "選ぶ", "直す", "保存する", "閉じる", "送る", "待つ", "確かめる", "終える")
        old_paragraphs = ["第{}節では、設定ファイルを開いて値を確認します。".format(i) for i in range(1, 21)]
        new_paragraphs = ["第{}節では、設定ファイルを開き、値を確かめます。".format(i) for i in range(1, 21)]
        old_paragraphs[4] = "手順は、" + "、".join(words) + "、の順です。"
        new_paragraphs[4] = "\n".join("- " + word for word in words)
        new_paragraphs[14] = "第15節では、設定ファイルを開き、値を確認しません。"
        result = yomiyasu_diff.diff("\n\n".join(old_paragraphs) + "\n", "\n\n".join(new_paragraphs) + "\n")
        self.assertEqual(len(result["full_diff"]["hunks"]), 20)
        negations = [risk for risk in result["meaning_risks"] if risk["kind"] == "negation"]
        self.assertEqual([(risk["old"], risk["new"]) for risk in negations],
                         [("第15節では、設定ファイルを開いて値を確認します。", "第15節では、設定ファイルを開き、値を確認しません。")])
        self.assertNotIn("number", [kind for kind, _ in self.kinds(result["meaning_risks"])])

    def test_detail_widens_kanji_words_without_the_particle(self):
        """10.2 D7 の広げ方で、変わった箇所の頭が漢字なら左の助詞は取らず、続く漢字の並びと平仮名3字までを取る。"""
        for before, after, detail in (("この設定は有効です。", "この設定は無効です。", {"old": "有効です", "new": "無効です"}),
                                      ("この手順は確認済みです。", "この手順は未確認です。", {"old": "確認済みです", "new": "未確認です"}),
                                      ("明日は会場へ行く。", "明日は会場へ行かない。", {"old": "行く", "new": "行かない"})):
            with self.subTest(before=before):
                [risk] = [risk for risk in self.risks(before, after) if risk["kind"] == "negation"]
                self.assertEqual(risk["detail"], detail)


class TestSwap(RiskCase):
    """2.5.4 主語と目的語の入れ替え（kind swap）。助詞は が、を、に、は、から、へ、より（「と」は入れない）。"""

    FOUND = (
        ("田中が佐藤を推薦した。", "佐藤が田中を推薦した。"),
        ("AチームがBチームに作業を引き継ぐ。", "BチームがAチームに作業を引き継ぐ。"),
        ("田中さんが佐藤さんを推薦した。", "佐藤さんが田中さんを推薦した。"),
    )
    NOT_FOUND = (
        ("田中が佐藤を承認した。", "佐藤を田中が承認した。"),
        ("田中が佐藤を承認した。", "佐藤が田中に承認された。"),
        ("田中は佐藤と話した。", "佐藤は田中と話した。"),
    )

    def test_swap_found(self):
        self.need_v2_diff()
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertIn("swap", [kind for kind, _ in self.kinds(self.risks(before, after))])

    def test_swap_detail_and_report_line(self):
        result = self.result("田中が佐藤を推薦した。", "佐藤が田中を推薦した。")
        [risk] = [risk for risk in result["meaning_risks"] if risk["kind"] == "swap"]
        self.assertIn({"word": "田中", "old": "が", "new": "を"}, risk["detail"]["pairs"])
        self.assertIn({"word": "佐藤", "old": "を", "new": "が"}, risk["detail"]["pairs"])
        self.assertIn("- 「が」「を」などが入れ替わった（1行目）: 田中 が→を、佐藤 を→が", self.report(result))

    def test_honorific_is_removed_from_the_word(self):
        result = self.result("田中さんが佐藤さんを推薦した。", "佐藤さんが田中さんを推薦した。")
        [risk] = [risk for risk in result["meaning_risks"] if risk["kind"] == "swap"]
        self.assertEqual({pair["word"] for pair in risk["detail"]["pairs"]}, {"田中", "佐藤"})
        result = self.result("田中様が佐藤様を推薦した。", "佐藤様が田中様を推薦した。")
        [risk] = [risk for risk in result["meaning_risks"] if risk["kind"] == "swap"]
        self.assertEqual({pair["word"] for pair in risk["detail"]["pairs"]}, {"田中", "佐藤"})
        # 2字の語の「様」（仕様、同様）は敬称として外さない
        result = self.result("仕様が設計を決める。", "設計が仕様を決める。")
        [risk] = [risk for risk in result["meaning_risks"] if risk["kind"] == "swap"]
        self.assertEqual({pair["word"] for pair in risk["detail"]["pairs"]}, {"仕様", "設計"})

    def test_swap_not_found(self):
        self.need_v2_diff()
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertNotIn("swap", [kind for kind, _ in self.kinds(self.risks(before, after))])


class TestSentenceType(RiskCase):
    """2.5.5 問い（sentence_type/question）と 2.5.6 文の種類の印（sentence_type/marks）。"""

    def test_question_to_statement(self):
        """設計の表から入力を1つ変えた。
        - 「来週公開しますか」は句読点がなく 2.5.5 の問いの定義（？、?、か。、か？）に入らないので、
          「来週公開しますか。」にした（questions-diff.md 5、10.2 D5）。
        - 6.4 の「動くでしょうか。→ 動きます。」は、diff の詰めで、1行対1行の置き換えで両側が1文ずつなら
          似かたによらず組にするようにしたので、6.4 の入力のまま試す（前は主語を足した形に変えていた）。"""
        self.need_v2_diff()
        for before, after in (("動くでしょうか。", "動きます。"), ("この設定で動くでしょうか。", "この設定で動きます。"),
                              ("来週公開しますか。", "来週公開します。")):
            with self.subTest(before=before):
                result = self.result(before, after)
                [risk] = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("sentence_type", "question")]
                self.assertEqual(risk["detail"], {"old_is_question": True, "new_is_question": False})
                self.assertIn("- 問いの文が問いでなくなった（1行目）", self.report(result))

    def test_statement_to_question(self):
        result = self.result("この設定で動きます。", "この設定で動くでしょうか。")
        [risk] = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("sentence_type", "question")]
        self.assertEqual(risk["detail"], {"old_is_question": False, "new_is_question": True})
        self.assertIn("- 問いでない文が問いになった（1行目）", self.report(result))

    def test_conjecture_mark_lost(self):
        result = self.result("原因は設定ミスかもしれない。", "原因は設定ミスだ。")
        marks = [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("sentence_type", "marks")]
        self.assertEqual(len(marks), 1, result["meaning_risks"])
        self.assertIn("推量", [mark["kind"] for mark in marks[0]["detail"]["lost"]])
        [change] = result["type_changes"]
        self.assertEqual(marks[0]["detail"], {"lost": change["lost"], "added": change["added"]})
        report = self.report(result)
        self.assertIn("- 文の種類の印が変わった: 1件（下の「■ 文の種類の印が変わった文」を見る）", report)
        self.assertTrue([line for line in report if line.startswith("■ 文の種類の印が変わった文（")], "既存の節と見出しは残す")


class TestProtected(RiskCase):
    """2.5.7 変えない箇所（kind protected）。コード、リンク先、引用。

    リンク先（protected_spans の link_destination）の subkind は link。2.7 の注の表示の名前の順
    （インラインのコード、URL、リンク先、先頭の設定、HTML、引用）が subkind の順（inline_code、url、link、frontmatter、html、quote）
    と1対1に対応するので、リンク先は link と読んだ（questions-diff.md 6）。"""

    CASES = (
        ("強制するには `--force` を付ける。", "強制するには `--forced` を付ける。", {"inline_code"}),
        ("[手順書](https://example.com/guide-a) を読む。", "[手順書](https://example.com/guide-b) を読む。", {"link"}),
        ("> 締め切りは金曜です。", "> 締め切りは月曜です。", {"quote"}),
    )

    def test_protected_spans(self):
        self.need_v2_diff()
        for before, after, subkinds in self.CASES:
            with self.subTest(before=before):
                found = [subkind for kind, subkind in self.kinds(self.risks(before, after)) if kind == "protected"]
                self.assertTrue(set(found) & subkinds, "protected の %s が出る: %s" % (sorted(subkinds), found))

    # 10.2 D6 の対応（protected_spans の種類 → subkind）。(元, 後, subkind, detail の block, レポートの行)
    EXACT = (
        ("強制するには `--force` を付ける。\n", "強制するには `--forced` を付ける。\n",
         "inline_code", "inline_code", "- インラインのコードが変わった（1行目）"),
        ("[手順書](https://example.com/guide-a) を読む。\n", "[手順書](https://example.com/guide-b) を読む。\n",
         "link", "link_destination", "- リンク先が変わった（1行目）"),
        ("詳しくは https://example.com/a を見る。\n", "詳しくは https://example.com/b を見る。\n",
         "url", "bare_url", "- URLが変わった（1行目）"),
        ("<https://example.com/a> を見る。\n", "<https://example.com/b> を見る。\n",
         "url", "autolink", "- URLが変わった（1行目）"),
        ("手順です。\n\n```sh\nretry --count 3\n```\n", "手順です。\n\n```sh\nretry --count 5\n```\n",
         "code", "code", "- コードが変わった（4行目）"),
        ("手順です。\n\n    retry --count 3\n", "手順です。\n\n    retry --count 5\n",
         "code", "code", "- コードが変わった（3行目）"),
        ("---\ntitle: 手順A\n---\n本文です。\n", "---\ntitle: 手順B\n---\n本文です。\n",
         "frontmatter", "frontmatter", "- 先頭の設定が変わった（2行目）"),
        ("<div>注意を読む</div>\n\n本文です。\n", "<div>注意を守る</div>\n\n本文です。\n",
         "html", "html_block", "- HTMLが変わった（1行目）"),
        ("本文<span class=\"a\">です</span>。\n", "本文<span class=\"b\">です</span>。\n",
         "html", "html_token", "- HTMLが変わった（1行目）"),
        ("> 締め切りは金曜です。\n", "> 締め切りは月曜です。\n", "quote", "quote", "- 引用が変わった（1行目）"),
    )

    def test_each_subkind_detail_and_report_line(self):
        """10.2 D6: inline_code → inline_code、囲みと字下げのコード → code、autolink と bare_url → url、
        link_destination → link、frontmatter → frontmatter、html_block と html_token → html、引用のブロック → quote。
        detail は {"block": 当たった protected_spans の種類（引用は quote）}。レポートの行のあとに元と後の行を出す。"""
        self.need_v2_diff()
        for before, after, subkind, block, line in self.EXACT:
            with self.subTest(before=before):
                result = yomiyasu_diff.diff(before, after)
                protected = [risk for risk in result["meaning_risks"] if risk["kind"] == "protected"]
                self.assertEqual([risk["subkind"] for risk in protected], [subkind], result["meaning_risks"])
                self.assertEqual(protected[0]["detail"], {"block": block})
                self.assertIsNone(protected[0]["basis"])
                report = self.report(result)
                self.assertIn(line, report)
                index = report.index(line)
                self.assertTrue(report[index + 1].startswith("  元: ") and report[index + 2].startswith("  後: "), report)

    def test_whitespace_only_change_in_code_is_protected(self):
        """2.5.7: 空白だけの変更でも出す（コードでは意味がある）。"""
        result = yomiyasu_diff.diff("手順です。\n\n```py\nif x:\n    run()\n```\n", "手順です。\n\n```py\nif x:\n  run()\n```\n")
        self.assertIs(result["full_diff"]["hunks"][0]["whitespace_only"], True)
        self.assertEqual(self.kinds(result["meaning_risks"]), [("protected", "code")])

    def test_inserted_and_deleted_lines_use_the_line_kind(self):
        """2.5.7: 追加と削除の塊は行の種類で決める（コードの行を足す → code、引用の行を消す → quote）。"""
        added = yomiyasu_diff.diff("手順です。\n\n```sh\nstart\n```\n", "手順です。\n\n```sh\nstart\nstop\n```\n")
        self.assertEqual(added["full_diff"]["hunks"][0]["tag"], "insert")
        self.assertEqual(self.kinds(added["meaning_risks"]), [("protected", "code")])
        self.assertIn("- コードが変わった（後5行目）", self.report(added))
        removed = yomiyasu_diff.diff("本文です。\n\n> 引用の一文目。\n> 引用の二文目。\n", "本文です。\n\n> 引用の一文目。\n")
        self.assertEqual(removed["full_diff"]["hunks"][0]["tag"], "delete")
        self.assertEqual(self.kinds(removed["meaning_risks"]), [("protected", "quote")])
        self.assertIn("- 引用が変わった（元4行目）", self.report(removed))

    def test_lazy_continuation_of_a_quote_is_quote(self):
        """反証レビュー F10: 「>」のない行が引用の続き（遅延継続）と読まれるとき、その行の変更も protected/quote にする
        （全文差分の種類も「引用」と出す）。消したときも同じ。"""
        before = "> 締め切りは金曜です。\n担当は田中です。\n"
        result = yomiyasu_diff.diff(before, "> 締め切りは金曜です。\n担当は佐藤です。\n")
        self.assertIn(("protected", "quote"), self.kinds(result["meaning_risks"]))
        self.assertIn("- 引用が変わった（2行目）", self.report(result))
        removed = yomiyasu_diff.diff(before, "> 締め切りは金曜です。\n")
        self.assertIn(("protected", "quote"), self.kinds(removed["meaning_risks"]))

    def test_reference_definitions_and_image_paths_are_links(self):
        """反証レビュー risk 5: リンクの定義の URL と画像のパスの変更は protected/link（10.2 D6「リンク先の URL の変更は link」）。
        どちらも数値の取り出しでは伏せるので、数値には出さない。画像の代わりの文の変更は link にしない。"""
        cases = (
            ("詳しくは[手引き][g]を読む。\n\n[g]: https://example.com/2024/guide\n",
             "詳しくは[手引き][g]を読む。\n\n[g]: https://example.com/2025/guide\n", "reference_definition", 3),
            ("![構成図](img/2024/arch.png)\n", "![構成図](img/2025/arch.png)\n", "image", 1),
            ("![図](img/a.png)\n", "![図](img/b.png)\n", "image", 1),
        )
        for before, after, block, line in cases:
            with self.subTest(before=before):
                result = yomiyasu_diff.diff(before, after)
                self.assertEqual(self.kinds(result["meaning_risks"]), [("protected", "link")])
                self.assertEqual(result["meaning_risks"][0]["detail"], {"block": block})
                self.assertIn("- リンク先が変わった（{}行目）".format(line), self.report(result))
        result = yomiyasu_diff.diff("![構成図](img/arch.png)\n", "![全体の構成図](img/arch.png)\n")
        self.assertNotIn("protected", [kind for kind, _ in self.kinds(result["meaning_risks"])])

    def test_budget_omitted_replace_hunk_still_shows_inline_changes(self):
        """反証レビュー E8: 予算で文字の対応を省いた置き換えの hunk でも、インラインのコードとリンク先の変化は protected に出る。
        変えていない種類（この hunk では引用やコードの囲みはない）は出さない。
        diff の詰めで、塊をそのまま文字で対応させる上限を500字にしたので、予算に届くよう、前の入力
        （1,000字の行を100個）から500字の行を200個に変えた。"""
        base = ("これは記録の文です。" * 50)[:499]
        olds = ["## 節%d\n%s壱" % (n, base) for n in range(200)]
        news = ["## 節%d\n%s弐" % (n, base) for n in range(200)]
        last_old = "`--force` を付けて実行します。[手順](https://example.com/a) を見ます。"
        last_new = "`--forced` を付けて実行します。[手順](https://example.com/b) を見ます。"
        before = "\n".join(olds + ["## 後", last_old]) + "\n"
        after = "\n".join(news + ["## 後", last_new]) + "\n"
        full = yomiyasu_diff.full_diff(before, after)
        self.assertEqual(full["hunks"][-1]["segments_omitted"], "budget")
        risks = yomiyasu_diff.meaning_risks(before, after, full=full)
        last = [risk for risk in risks if risk["kind"] == "protected" and risk["new_line"] == 402]
        self.assertEqual(sorted(risk["subkind"] for risk in last), ["inline_code", "link"])

    def test_text_outside_protected_spans_is_not_protected(self):
        """変えない箇所の外だけを変えたときは protected を出さない（インラインのコードの直後、リンクの文字、ふつうの段落）。"""
        cases = (
            ("強制するには `--force` を付ける。\n", "強制するには `--force` を付けてください。\n"),
            ("[手順書](https://example.com/guide) を読む。\n", "[手引き](https://example.com/guide) を読む。\n"),
            ("手順です。\n\n```sh\nretry\n```\n", "手順を書きます。\n\n```sh\nretry\n```\n"),
        )
        for before, after in cases:
            with self.subTest(before=before):
                kinds = [kind for kind, _ in self.kinds(yomiyasu_diff.diff(before, after)["meaning_risks"])]
                self.assertNotIn("protected", kinds)


class TestMeaningRisksFunction(RiskCase):
    """2.10 の meaning_risks(orig, rw, full=None, type_changes=None)（10.4 S5）。"""

    BEFORE, AFTER = "原因は設定ミスかもしれない。\n", "原因は設定ミスだ。\n"

    def function(self):
        function = getattr(yomiyasu_diff, "meaning_risks", None)
        self.assertTrue(callable(function), "v2.0.0 の yomiyasu_diff は meaning_risks() を公開する（2.10）")
        return function

    def test_type_changes_none_and_empty_mean_no_marks(self):
        """10.4 S5: type_changes が None でも [] でも文の種類の印を含めない。関数の中で9キーの分析を作らない。"""
        meaning_risks = self.function()
        with mock.patch.object(yomiyasu_diff, "_type_changes", side_effect=AssertionError("9キーの分析を作った")):
            for value in (None, []):
                with self.subTest(type_changes=value):
                    risks = meaning_risks(self.BEFORE, self.AFTER, type_changes=value)
                    self.assertNotIn(("sentence_type", "marks"), self.kinds(risks))
            # 印を渡さなければ重複抑制の相手がないので、独立した確度の候補が出る。
            self.assertEqual(self.kinds(meaning_risks(self.BEFORE, self.AFTER)), [("certainty", "strengthened")])

    def test_type_changes_given_become_marks(self):
        """10.4 S5: diff() は自分で求めた type_changes を渡す。渡せば項目ごとに sentence_type/marks になる（2.5.6）。"""
        meaning_risks = self.function()
        changes = yomiyasu_diff.diff(self.BEFORE, self.AFTER)["type_changes"]
        risks = meaning_risks(self.BEFORE, self.AFTER, type_changes=changes)
        self.assertEqual(self.kinds(risks), [("sentence_type", "marks")])
        self.assertEqual(risks[0]["detail"], {"lost": changes[0]["lost"], "added": changes[0]["added"]})
        self.assertEqual((risks[0]["old"], risks[0]["new"]), (changes[0]["orig"], changes[0]["rewrite"]))
        self.assertEqual(risks, yomiyasu_diff.diff(self.BEFORE, self.AFTER)["meaning_risks"])

    def test_full_argument_is_reused(self):
        """full を渡せば全文差分を作り直さず、渡さなければ自分で作る。どちらも同じ結果。"""
        meaning_risks = self.function()
        before, after = "強制するには `--force` を付ける。\n", "強制するには `--forced` を付ける。\n"
        full = yomiyasu_diff.full_diff(before, after)
        with mock.patch.object(yomiyasu_diff, "full_diff", side_effect=AssertionError("全文差分を作り直した")):
            reused = meaning_risks(before, after, full=full)
        self.assertEqual(reused, meaning_risks(before, after))
        self.assertEqual(self.kinds(reused), [("protected", "inline_code")])


class TestFixedLimits(RiskCase):
    """拾えない例と、意味が変わる恐れに入れない変化を、限界として固定する（6.4、8.1の8）。"""

    def test_place_name_is_a_word_change_not_a_meaning_risk(self):
        result = self.result("会議は東京で開く。", "会議は大阪で開く。")
        self.assertEqual(result["meaning_risks"], [])
        self.assertIn("大阪", result["new_words"])
        self.assertIn("東京", result["lost_words"])

    def test_hiragana_names_are_only_in_the_full_diff(self):
        result = self.result("たなかさんが確認した。", "すずきさんが確認した。")
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["status"], "changed_without_candidates")
        self.assertIn("すずきさんが確認した。", self.changed_lines(result))

    def test_removed_condition(self):
        """設計の表から入力を変えた: 「雨なら中止する」は条件の印（なら の直後が読点・句点・行末）に当たらない。
        書いたとおりの入力では meaning_risks が空であることだけを見て、markers の条件は読点つきの形で確かめる（questions-diff.md 3）。"""
        self.assertEqual(self.risks("雨なら中止する。", "中止する。"), [])
        result = self.result("雨なら、中止する。", "中止する。")
        self.assertEqual(result["meaning_risks"], [])
        self.assertIn("条件", [marker["kind"] for marker in result["markers"]])

    def test_removed_exception_is_only_in_the_full_diff(self):
        """設計の表から期待値を弱めた: v1.1.2 の lost_words に「管理者」が出るので、「全文差分にだけ出る」を
        「意味が変わる恐れには出ず、全文差分に出る」と読んだ。candidate_count と status は見ない（questions-diff.md 4）。"""
        result = self.result("管理者を除き、全員が使える。", "全員が使える。")
        self.assertEqual(result["meaning_risks"], [])
        self.assertIn("管理者を除き、全員が使える。", self.changed_lines(result))
        # 10.2 D4: lost_words に「管理者」が出て has_candidates になるのは正しい
        self.assertIn("管理者", result["lost_words"])
        self.assertEqual(result["status"], "has_candidates")

    def test_values_swapped_between_words_in_the_same_order_are_not_found(self):
        """数値の並びは同じで語のほうを入れ替えた形（Aは3日、Bは5日 → Bは3日、Aは5日）は number/order にも swap にも
        ならない（助詞が同じ「は」なので入れ替えに当たらない）。全文差分にだけ出る。限界として固定する。"""
        result = self.result("Aは3日、Bは5日です。", "Bは3日、Aは5日です。")
        self.assertEqual(result["meaning_risks"], [])
        self.assertIn("Bは3日、Aは5日です。", self.changed_lines(result))

    def test_negation_with_a_rephrased_stem_is_only_in_the_full_diff(self):
        """diff の詰めで、句点の前の規則を「印でない字の違いが平仮名だけ」に絞った。そのため、
        語幹ごと書き換えた否定（確認します → 確かめません）は negation に出ない（2.5.3 の残る限界。基準 38d6556 では出ていた。
        反証で見つけた例）。全文差分には出る。限界として固定する。"""
        result = self.result("値を確認します。", "値を確かめません。")
        self.assertNotIn("negation", [kind for kind, _ in self.kinds(result["meaning_risks"])])
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)
        self.assertIn("値を確かめません。", self.changed_lines(result))

    def test_added_feeling_is_in_the_full_diff(self):
        """diff の詰め（10.6 B2、10.7）: 元にない気持ちの語は kind feeling の候補にもする（--fail-on には数えない）。
        全文差分にも今までどおり出る。"""
        result = self.result("設定を変更した。", "設定を変更して、ほっとした。")
        self.assertNotEqual(result["status"], "no_change")
        self.assertEqual(self.kinds(result["meaning_risks"]), [("feeling", None)])
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)
        self.assertTrue([line for line in self.changed_lines(result) if "ほっとし" in line])
        report = self.report(result)
        start = [index for index, line in enumerate(report) if line.startswith("■ 全文差分")]
        self.assertTrue(start, "全文差分の節がある")
        self.assertTrue([line for line in report[start[0]:] if "ほっとし" in line], "全文差分に「ほっとし」が出る")


class TestCorpusWatch(RiskCase):
    """6.4 誤検知の見張り: コーパス48組で、要素の形と kind・subkind の値が 2.8 のとおり。
    10.2 D2: kind・subkind ごとの件数が、実装したときに測った値を超えない。
    コーパスの書き換えは yomiyasu の正しい推敲なので、ここに出るものは確かめれば済む候補で、増えれば誤検知が増えたことになる。"""

    # 2026-10-13 に測った値（句点の前の規則あり）。number/order、swap、sentence_type/question、protected は0件。
    # diff の詰めで測り直した。前の値は
    # negation 2、number/added 4、number/lost 1、number/replaced 1、sentence_type/marks 5（合計13）。今の値は
    # negation 1（「二重処理を防ぐ → 処理しない」の誤検知が 34 の直しで消えた）、number/added 5（「1」が「1つ」になった1件は同じ文、
    # 「一つのサービス」を 40 で数えるようになった1件が増えた）、ほかは同じ（合計13）。contrast_reversal と feeling は0件。
    # diff の詰めの直し（反証で見つけた例）で、数量を主張しない「一つ」（一つの、一つずつ、もう一つ）を
    # 単独では数値の候補にしないようにしたので、number/added を 5 から基準の 4 に戻した（合計12）
    # 評価の足しは5件を見直し候補に出す（--fail-on には数えない）。
    # v2.1.0 で2件増えた。どちらも原文の能力の言い方が推敲で言い切りになった所で、確かめるべき候補とみなす。
    # promise/guarantee 1（01_tech_arch_sonnet_formal の「事態を防げる → 処理を止めることはない」。否定の数が原文より増えた
    # 「〜ことはない」を、組の原文の文の述語で打ち消さなくなった）、modality_review/ability_lost 1（08_essay_retrospective_sonnet_formal の
    # 「担当できるまでになっている → 担当している」。種類なしなので数えない）。
    MEASURED = {"claim/evaluation": 5, "negation": 1, "number/added": 4, "number/lost": 1, "number/replaced": 1, "sentence_type/marks": 5,
                "promise/guarantee": 1, "modality_review/ability_lost": 1}

    def test_corpus_48_pairs_kind_counts_do_not_exceed_the_measured_values(self):
        self.need_v2_diff()
        counts = {}
        for before, after, name in corpus_pairs():
            for risk in yomiyasu_diff.diff(before, after)["meaning_risks"]:
                # 既存の種類の上限は据え置く。新しい見直し候補は専用の試験で確かめる。
                if risk["kind"] in ("certainty_review", "quote"):
                    continue
                key = risk["kind"] + ("/" + risk["subkind"] if risk["subkind"] else "")
                counts[key] = counts.get(key, 0) + 1
        for key in sorted(set(counts) | set(self.MEASURED)):
            with self.subTest(kind=key):
                self.assertLessEqual(counts.get(key, 0), self.MEASURED.get(key, 0), counts)

    def test_corpus_48_pairs_risk_shape(self):
        pairs = corpus_pairs()
        self.assertEqual(len(pairs), 48)
        self.need_v2_diff()
        for before, after, name in pairs:
            with self.subTest(pair=name):
                result = yomiyasu_diff.diff(before, after)
                self.assertEqual(result["meaning_risk_count"], len(result["meaning_risks"]))
                for risk in result["meaning_risks"]:
                    self.assertEqual(set(risk), RISK_KEYS)
                    self.assertIn(risk["kind"], KINDS)
                    if risk["kind"] in SUBKINDS:
                        self.assertIn(risk["subkind"], SUBKINDS[risk["kind"]])
                    for key in ("old_line", "new_line"):
                        self.assertTrue(risk[key] is None or isinstance(risk[key], int), risk)
                    for key in ("old", "new"):
                        self.assertTrue(risk[key] is None or isinstance(risk[key], str), risk)
                    self.assertIsNone(risk["basis"], "diff では basis は常に null（2.8）")


if __name__ == "__main__":
    unittest.main()
