#!/usr/bin/env python3
"""v2.0.0: diff の「意味が変わる恐れ」（meaning_risks）の試験（DESIGN-interfaces.md 2.5、2.7、2.8、6.4）。

指示書10章の種類（数字、日付、固有名詞、否定、条件、例外、確度、実施済みと未確認、元にない書き手の気持ちの追加）を含む。
候補は「確かめる場所」で、意味が変わったという判定ではない。拾えない例も、限界として期待値に固定する。
v1.1.2 の diff() は meaning_risks を返さないので、この試験はすべて失敗する。文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
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
    "protected": {"code", "inline_code", "url", "link", "frontmatter", "html", "quote"},
}
KINDS = {"number", "negation", "swap", "sentence_type", "protected"}

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
            self.assertTrue(key in result, "v2.0.0 の diff() は %s を返す（DESIGN-interfaces.md 2.8）。今のキー: %s"
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

    def test_value_lost_in_a_paired_sentence(self):
        self.assert_paired_number("設定を3回確認します。", "設定を確認します。", "lost", "removed", "3回", "消えた数値")

    def test_value_added_in_a_paired_sentence(self):
        self.assert_paired_number("設定を確認します。", "設定を3回確認します。", "added", "added", "3回", "元にない数値")

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

    def test_suru_to_shinai_is_in_the_full_diff(self):
        """する → しない は句点の前の規則を入れたかで期待値が変わる（2.5.3）。ここでは全文差分に出ることだけを見る。
        negation の有無は実装で規則を測ってから決める（questions-diff.md）。"""
        result = self.result("設定を変更する。", "設定を変更しない。")
        self.assertNotEqual(result["status"], "no_change")
        self.assertIn("設定を変更しない。", self.changed_lines(result))


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

    def test_swap_not_found(self):
        self.need_v2_diff()
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertNotIn("swap", [kind for kind, _ in self.kinds(self.risks(before, after))])


class TestSentenceType(RiskCase):
    """2.5.5 問い（sentence_type/question）と 2.5.6 文の種類の印（sentence_type/marks）。"""

    def test_question_to_statement(self):
        """設計の表から入力を変えた: 「来週公開しますか」は句読点がなく 2.5.5 の問いの定義（？、?、か。、か？）に入らないので、
        「来週公開しますか。」にした（questions-diff.md 5）。"""
        self.need_v2_diff()
        for before, after in (("この設定で動くでしょうか。", "この設定で動きます。"), ("来週公開しますか。", "来週公開します。")):
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

    def test_added_feeling_is_in_the_full_diff(self):
        result = self.result("設定を変更した。", "設定を変更して、ほっとした。")
        self.assertNotEqual(result["status"], "no_change")
        self.assertEqual(result["meaning_risks"], [])
        self.assertTrue([line for line in self.changed_lines(result) if "ほっとし" in line])
        report = self.report(result)
        start = [index for index, line in enumerate(report) if line.startswith("■ 全文差分")]
        self.assertTrue(start, "全文差分の節がある")
        self.assertTrue([line for line in report[start[0]:] if "ほっとし" in line], "全文差分に「ほっとし」が出る")


class TestCorpusWatch(RiskCase):
    """6.4 誤検知の見張りの下ごしらえ: コーパス48組で、要素の形と kind・subkind の値が 2.8 のとおり。
    kind ごとの件数の上限は、実装したときに測って CHECKPOINT.md に書いてから足す（questions-diff.md）。"""

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
