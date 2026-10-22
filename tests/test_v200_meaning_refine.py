#!/usr/bin/env python3
"""v2.0.0（diff の詰め）: 意味が変わる恐れの判定の詰め（設計 10.7 の勧め）と、
気持ちの創作（kind feeling。10.6 B2、目標の D-1）。

入力は反証レビュー（反証で見つけた例）の例と、このファイルで作った
合成の文。期待は diff の詰めで決めた勧めのとおり。--fail-on=meaning-risk が数える4つの kind（number、negation、swap、
sentence_type）の誤検知を減らし、取りこぼしを拾う。feeling は意味が変わる恐れの節に出すが、--fail-on には数えない。
"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))
from portable import paced_limit, timing_clock  # noqa: E402

COUNTED = ("number", "negation", "swap", "sentence_type")


def result_of(before, after):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after)


def kinds(before, after):
    return [risk["kind"] + ("/" + risk["subkind"] if risk["subkind"] else "")
            for risk in result_of(before, after)["meaning_risks"]]


def counted(before, after):
    return [kind for kind in kinds(before, after) if kind.split("/")[0] in COUNTED and kind != "sentence_type/marks"]


class ShortSentencePairTest(unittest.TestCase):
    """33: 1行対1行の置き換えで両側が1文ずつなら、似かたによらず組にする（6.4 の入力のまま）。"""

    def test_short_question_to_statement(self):
        self.assertIn("sentence_type/question", kinds("動くでしょうか。", "動きます。"))

    def test_short_negation(self):
        self.assertIn("negation", kinds("- 保存する", "- 保存しない"))
        self.assertIn("negation", kinds("する。", "しない。"))

    def test_short_number_is_replaced(self):
        found = kinds("3日", "3週間")
        self.assertEqual(found, ["number/replaced"])

    def test_two_sentence_lines_keep_the_ratio_rule(self):
        """1行に2文あるときは今までどおり似かたで組にする（組にならない文を無理に組にしない）。"""
        found = counted("雨です。動くでしょうか。", "晴れです。動きます。")
        self.assertNotIn("number/replaced", found)


class EndRuleTest(unittest.TestCase):
    """34: 句点の前の規則は、変わった箇所の印でない字が両側で仮名だけのときに限る。"""

    PARAPHRASES = (
        ("結果は変わらない。", "結果は同じだ。"),
        ("値が一致しない。", "値が異なる。"),
        ("この確認は欠かせない。", "この確認は重要だ。"),
        ("変更して構いません。", "変更してよいです。"),
        ("在庫がなくなる。", "在庫が切れる。"),
        ("鍵をなくす。", "鍵を失う。"),
        ("期限を忘れない。", "期限を覚えておく。"),
        ("ファイルは残らない。", "ファイルは消える。"),
        ("二重処理を防ぐ。", "二重に処理しない。"),
    )
    STILL_FOUND = (
        ("設定する。", "設定しない。"),
        ("この変更で直る。", "この変更では直らない。"),
        ("鍵を保存する。", "鍵を保存しない。"),
        ("再起動が必要です。", "再起動は必要ありません。"),
        ("設定を確認した。", "設定を確認していない。"),
    )

    def test_paraphrases_are_not_negation(self):
        for before, after in self.PARAPHRASES:
            with self.subTest(before=before):
                self.assertNotIn("negation", kinds(before, after))

    def test_kana_only_changes_are_still_found(self):
        for before, after in self.STILL_FOUND:
            with self.subTest(before=before):
                self.assertIn("negation", kinds(before, after))


class MidSentenceNegationTest(unittest.TestCase):
    """42: 文の途中の「する → しない」と「せずに ↔ して」。"""

    def test_found(self):
        for before, after in (("設定を使用する場合は再起動する。", "設定を使用しない場合は再起動する。"),
                              ("キャッシュを利用するときは、先に消す。", "キャッシュを利用しないときは、先に消す。"),
                              ("ログを残さずに終了する。", "ログを残して終了する。"),
                              ("ログを残して終了する。", "ログを残さずに終了する。"),
                              ("確認せずに進める。", "確認して進める。")):
            with self.subTest(before=before):
                self.assertIn("negation", kinds(before, after))

    def test_not_found(self):
        for before, after in (("設定を使用する場合は再起動する。", "設定を使用した場合は再起動する。"),
                              ("止まらずに動く。", "止まることなく動く。")):
            with self.subTest(before=before):
                self.assertNotIn("negation", kinds(before, after))


class ParagraphShiftTest(unittest.TestCase):
    """35: 段落を1つ分けても、後ろの段落がずれて組にならない（反証で見つけた例）。"""

    def test_split_without_number_change_has_no_number(self):
        o_p, r_p = [], []
        for i in range(60):
            a = "記録{}の保存期間は{}日です。".format(i, i * 7 % 89 + 2)
            b = "担当者は{}回確認します。".format(i % 8 + 2)
            o_p.append(a + b)
            r_p.append(a.replace("の保存期間は", "は").replace("日です。", "日保存します。") + b.replace("確認します", "確かめます"))
        r_split = r_p[:5] + [r_p[5].split("。")[0] + "。", r_p[5].split("。", 1)[1]] + r_p[6:]
        result = yomiyasu_diff.diff("\n\n".join(o_p) + "\n", "\n\n".join(r_split) + "\n")
        self.assertEqual([risk for risk in result["meaning_risks"] if risk["kind"] == "number"], [])

    def test_negation_after_a_split_is_found(self):
        topics = ["設定ファイル", "ログの保存", "定期の点検", "利用者の一覧", "障害の連絡", "手順書の更新", "鍵の受け渡し",
                  "予算の申請", "鍵の管理の変更", "会議の記録"]
        o_p, r_p = [], []
        for index, topic in enumerate(topics):
            first = "{}を開いて中身を読みます。".format(topic)
            second = "{}は毎朝の一覧を作って共有します。".format(topic) if index != 8 else "{}を担当者に伝えます。".format(topic)
            o_p.append(first + second)
            new_second = second.replace("ます。", "ています。").replace("毎朝", "朝ごとに")
            if index == 8:
                new_second = new_second.replace("伝えています。", "伝えていません。")
            r_p.append(first.replace("ます。", "ています。") + new_second)
        r_split = r_p[:2] + [r_p[2].split("。")[0] + "。", r_p[2].split("。", 1)[1]] + r_p[3:]
        result = yomiyasu_diff.diff("\n\n".join(o_p) + "\n", "\n\n".join(r_split) + "\n")
        negations = [risk for risk in result["meaning_risks"] if risk["kind"] == "negation"]
        self.assertEqual(len(negations), 1, result["meaning_risks"])
        self.assertIn("伝えていません", negations[0]["new"])
        self.assertEqual([risk for risk in result["meaning_risks"] if risk["kind"] == "number"], [])


class LongLineTest(unittest.TestCase):
    """36: 1行が長い文書の全面書き換えでも、6万字で3秒未満（「．」と「. 」の文も文に分ける）。
    37: 2,000字を超える断片でも、前後の同じ字を外してから削除と追加にする（変えていないコードとリンク先を出さない）。"""

    def assert_fast(self, before, after):
        # 3秒の上限は、Windows の遅い機械では基準の処理の遅さの比で延ばす（portable.paced_limit）。時間は CPU 時間で測る
        clock = timing_clock()
        started = clock()
        full = yomiyasu_diff.full_diff(before, after)
        yomiyasu_diff.meaning_risks(before, after, full=full)
        elapsed = clock() - started
        limit, detail = paced_limit(3.0, elapsed)
        self.assertLess(elapsed, limit, detail)

    def test_period_sentences_in_long_lines(self):
        for line_chars, stop in ((1500, "。"), (1900, "。"), (1500, "．"), (800, "．")):
            with self.subTest(line_chars=line_chars, stop=stop):
                sentence = "第{}の処理では入力を確かめてから結果を返します" + stop
                lines_old, lines_new = [], []
                number = 0
                while sum(len(line) for line in lines_old) < 60000:
                    line_old, line_new = "", ""
                    while len(line_old) < line_chars:
                        line_old += sentence.format(number)
                        line_new += sentence.format(number).replace("確かめてから", "確認してから")
                        number += 1
                    lines_old.append(line_old)
                    lines_new.append(line_new)
                self.assert_fast("\n\n".join(lines_old) + "\n", "\n\n".join(lines_new) + "\n")

    def test_english_sentences_in_long_lines(self):
        sentence = "Step {} checks the input before it returns the result. "
        lines_old, lines_new, number = [], [], 0
        while sum(len(line) for line in lines_old) < 60000:
            line_old, line_new = "", ""
            while len(line_old) < 800:
                line_old += sentence.format(number)
                line_new += sentence.format(number).replace("checks", "verifies")
                number += 1
            lines_old.append(line_old)
            lines_new.append(line_new)
        self.assert_fast("\n\n".join(lines_old) + "\n", "\n\n".join(lines_new) + "\n")

    def test_long_fragment_keeps_unchanged_code_and_links(self):
        body = "`make test` を先に実行し、[手順](https://example.com/guide) を読みます，" + "キャッシュとログの中身を確かめます，" * 120
        before = body + "終えます．\n"
        after = body.replace("キャッシュ", "記憶域", 1) + "終えます．\n"
        result = yomiyasu_diff.diff(before, after)
        self.assertEqual([risk for risk in result["meaning_risks"] if risk["kind"] == "protected"], [])


class NumberNotationTest(unittest.TestCase):
    """39、40、41、51: 表記だけの違いは数値の候補にしない。値が変わったものは出す。英字の単位も単位として見る。"""

    NOTATION_ONLY = (
        ("容量は 16 GB です。", "容量は16GBです。"),
        ("成功率は 95 % だった。", "成功率は95%だった。"),
        ("応答は 200 ms 以内に返す。", "応答は200ms以内に返す。"),
        ("作業には3〜5日かかる。", "作業には3日から5日かかる。"),
        ("参加者は5～10人を見込む。", "参加者は5人から10人を見込む。"),
        ("公開日は2026-10-13です。", "公開日は2026年10月13日です。"),
        ("会議は10:30に始める。", "会議は10時30分に始める。"),
        ("方法は二つある。", "方法は2つある。"),
        ("詳しくは第三章で説明する。", "詳しくは第3章で説明する。"),
        ("設定を三か所で変える。", "設定を3か所で変える。"),
        ("ログは三種類ある。", "ログは3種類ある。"),
        ("締め切りは十二月だ。", "締め切りは12月だ。"),
        ("問い合わせは約2千件あった。", "問い合わせは約2,000件あった。"),
        ("一日も早い復旧を目指す。", "できるだけ早い復旧を目指す。"),
        ("(1) 設定を開く。\n(2) 値を入れる。\n(3) 保存する。", "(1) 設定を開く。\n(2) 保存する。"),
        ("（１）設定を開く。\n（２）値を入れる。\n（３）保存する。", "（１）設定を開く。\n（２）保存する。"),
        ("処理は 3 s かかる。", "処理は3sかかる。"),
    )
    VALUE_CHANGED = (
        ("容量は 16 GB です。", "容量は32GBです。"),
        ("作業には3〜5日かかる。", "作業には3日から7日かかる。"),
        ("方法は二つある。", "方法は3つある。"),
        ("問い合わせは約2千件あった。", "問い合わせは約3,000件あった。"),
        ("詳しくは第三章で説明する。", "詳しくは第4章で説明する。"),
        ("待ち時間は30sです。", "待ち時間は30minです。"),
        ("帯域は100Mbpsです。", "帯域は100Gbpsです。"),
        ("保存期間は3日です。", "保存期間は30日です。"),
    )

    def test_notation_only_is_not_number(self):
        for before, after in self.NOTATION_ONLY:
            with self.subTest(before=before):
                self.assertNotIn("number", [kind.split("/")[0] for kind in kinds(before, after)])

    def test_changed_values_are_number(self):
        for before, after in self.VALUE_CHANGED:
            with self.subTest(before=before):
                self.assertIn("number", [kind.split("/")[0] for kind in kinds(before, after)])

    def test_extract_numbers_reads_kanji_thousand_and_spaced_units(self):
        found = yomiyasu_diff.extract_numbers("約2千件、容量は 16 GB、第三章、三か所、二つ、30s。")
        values = [(item["value"], item["unit"]) for item in found]
        self.assertIn(("2000", "件"), values)
        self.assertIn(("16", "GB"), values)
        self.assertIn(("3", "章"), values)
        self.assertIn(("3", "か所"), values)
        self.assertIn(("2", "つ"), values)
        self.assertIn(("30", "s"), values)

    def test_versions_and_ids_are_not_numbers(self):
        """英字の直後から始まる数（v2、IPv6）は今までどおり取らない。数字に続く英字（5字まで）は単位として取る（51）。"""
        found = yomiyasu_diff.extract_numbers("v2 と IPv6 を使う。3Dの図と5Gの回線。")
        values = [(item["value"], item["unit"]) for item in found]
        self.assertEqual(values, [("3", "D"), ("5", "G")])


class PassiveSwapTest(unittest.TestCase):
    """43: 「に」をとる動詞の受け身への書き換えは入れ替えにしない。「を」の入れ替えは今までどおり出す。"""

    def test_passive_with_ni_is_not_swap(self):
        for before, after in (("この変更がユーザーに影響する。", "ユーザーがこの変更に影響される。"),
                              ("AがBに依存する。", "BがAに依存される。")):
            with self.subTest(before=before):
                self.assertNotIn("swap", kinds(before, after))

    def test_active_swap_is_still_found(self):
        for before, after in (("田中が佐藤を呼んだ。", "佐藤が田中を呼んだ。"), ("AがBに送った。", "BがAに送った。")):
            with self.subTest(before=before):
                self.assertIn("swap", kinds(before, after))


class QuestionWordTest(unittest.TestCase):
    """44: 「明らか。」「確か。」などの「か。」は問いにしない。"""

    def test_adjective_ka_is_not_a_question(self):
        for before, after in (("原因は明らか。", "原因は明らかだ。"), ("この数字は確か。", "この数字は確かだ。"),
                              ("残りはわずか。", "残りはわずかだ。"), ("夜は静か。", "夜は静かだ。"),
                              ("- 対象はAとB、そのほか。", "- 対象はAとBなど。"), ("暮らしは豊か。", "暮らしは豊かだ。")):
            with self.subTest(before=before):
                self.assertNotIn("sentence_type/question", kinds(before, after))

    def test_real_question_is_still_found(self):
        self.assertIn("sentence_type/question", kinds("原因は何か。", "原因は設定だ。"))
        self.assertIn("sentence_type/question", kinds("来週公開しますか。", "来週公開します。"))


class FutureWordTest(unittest.TestCase):
    """45: 「未来」「未明」は否定の「未」にしない。「未確認」「未対応」は今までどおり。"""

    def test_mirai_is_not_negation(self):
        self.assertNotIn("negation", kinds("将来の計画を立てる。", "未来の計画を立てる。"))
        self.assertNotIn("negation", kinds("未明に作業する。", "夜明け前に作業する。"))

    def test_mi_negation_is_still_found(self):
        self.assertIn("negation", kinds("この手順は確認済みです。", "この手順は未確認です。"))
        self.assertIn("negation", kinds("確認は完了した。", "確認は未完了だ。"))


class NegationDetailTest(unittest.TestCase):
    """48: 否定の detail は右へ、平仮名を句読点か漢字・片仮名の直前まで（上限6字）広げる。"""

    def test_detail_reaches_the_end_of_the_word(self):
        [risk] = [risk for risk in result_of("設定を変更してください。", "設定を変更しないでください。")["meaning_risks"]
                  if risk["kind"] == "negation"]
        self.assertEqual(risk["detail"], {"old": "変更してください", "new": "変更しないでください"})

    def test_detail_of_the_basic_example_is_unchanged(self):
        [risk] = [risk for risk in result_of("データを保存します。", "データを保存しません。")["meaning_risks"]
                  if risk["kind"] == "negation"]
        self.assertEqual(risk["detail"], {"old": "保存します", "new": "保存しません"})


class GroundTest(unittest.TestCase):
    """38: 資料にあって最終稿にない数値を、照合の items に not_in_final として入れる。
    39、46: 照合の数値の表記の違い、名前・語・確度の語の部分一致。"""

    def test_not_in_final_numbers(self):
        result = yomiyasu_diff.ground("保存期間は3日です。\n", ["保存期間は3日、件数は10件、期限は14日。\n"])
        rest = [item for item in result["items"] if item["classification"] == "not_in_final"]
        self.assertEqual([(item["kind"], item["text"], item["final_lines"]) for item in rest],
                         [("number", "10件", []), ("number", "14日", [])])
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(result["candidate_count"], 0)

    def test_notation_differences_are_in_the_materials(self):
        for final, material in (("メモリは16GBです。\n", "メモリは 16 GB。\n"), ("作業は3日から5日かかる。\n", "作業は3〜5日かかる。\n"),
                                ("公開日は2026年10月13日です。\n", "公開日: 2026-10-13\n"),
                                ("問い合わせは2千件だった。\n", "問い合わせは2,000件だった。\n")):
            with self.subTest(final=final):
                result = yomiyasu_diff.ground(final, [material])
                self.assertEqual([risk for risk in result["meaning_risks"] if risk["subkind"] == "number"], [])

    def test_partial_matches(self):
        cases = (
            ("定義していない変数を読むと止まる。\n", "未定義の変数を読むと止まる。\n", "dropped_certainty", "未定", False),
            ("Enterキーで入力を決める。\n", "Enterキーで入力を確定する。\n", "dropped_certainty", "確定", False),
            ("Javaで書く。\n", "JavaScriptで書く。\n", "not_in_sources", "Java", True),
            ("SQLを使う。\n", "PostgreSQLを使う。\n", "not_in_sources", "SQL", True),
            ("応答は200msで返る。\n", "応答は200ミリ秒で返る。\n", "not_in_sources", "ms", False),
        )
        for final, material, classification, text, expected in cases:
            with self.subTest(final=final):
                result = yomiyasu_diff.ground(final, [material])
                found = [item for item in result["items"]
                         if item["classification"] == classification and item["text"] == text]
                self.assertEqual(bool(found), expected, result["items"])

    def test_words_taken_as_numbers_are_not_words(self):
        result = yomiyasu_diff.ground("作業は三日で終える。\n", ["作業は3日で終える。\n"])
        self.assertEqual([item for item in result["items"] if item["classification"] == "not_in_sources"], [])


class FeelingTest(unittest.TestCase):
    """10.6 B2、目標の D-1: 元の文にない気持ちの語を足した書き換えを kind feeling の候補にする（--fail-on には数えない）。"""

    FOUND = (
        ("設定を変更した。", "設定を変更して、ほっとした。", "ほっと"),
        ("移行を終えた。", "移行を終えて、肩の荷が下りた。", "肩の荷"),
        ("移行を終え、チーム全員が解散した。", "移行を終え、チーム全員が安堵した。", "安堵"),
        ("新しい部署に移った。", "新しい部署に移り、不安でいっぱいだった。", "不安"),
        ("結果を報告した。", "結果を報告でき、本当にうれしかった。", "うれし"),
        ("駅まで歩いた。", "駅まで歩きながら、少し寂しくなった。", "寂し"),
    )
    NOT_FOUND = (
        # 原文にもある気持ちの語を言い直しただけ
        ("移行が終わって、ほっとした。", "移行を終えて、ほっとした。"),
        ("合格の知らせを聞いて、うれしかった。", "合格の知らせに、うれしくなった。"),
        # 気持ちの語でない（不安定、心配りでない語）
        ("接続が切れることがある。", "接続が不安定なことがある。"),
        ("壊れた部品を替えた。", "こわれた部品を替えた。"),
        # 気持ちを足さない普通の推敲
        ("毎朝の散歩が、じわじわと私の心に効いてきている。", "毎朝の散歩のおかげで、気持ちが少しずつ変わってきている。"),
    )

    def test_found(self):
        for before, after, word in self.FOUND:
            with self.subTest(after=after):
                result = result_of(before, after)
                found = [risk for risk in result["meaning_risks"] if risk["kind"] == "feeling"]
                self.assertEqual(len(found), 1, result["meaning_risks"])
                self.assertIn(word, found[0]["detail"]["words"])
                self.assertIsNone(found[0]["subkind"])
                self.assertEqual(found[0]["new_line"], 1)
                self.assertNotIn("feeling", yomiyasu_diff.FAIL_ON_KINDS)
                self.assertEqual(result["fail_on_meaning_risk_count"],
                                 sum(1 for risk in result["meaning_risks"] if risk["kind"] in COUNTED))

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(after=after):
                self.assertNotIn("feeling", kinds(before, after))

    def test_list_files_match_the_builtin_list(self):
        """気持ちの語の一覧は references/lists/feelings.txt（ルートと skills の両方）。内蔵の一覧と同じ（ない環境でも同じに動く）。"""
        for base in (ROOT / "references" / "lists", ROOT / "skills" / "yomiyasu" / "references" / "lists"):
            with self.subTest(base=str(base)):
                text = (base / "feelings.txt").read_text(encoding="utf-8")
                self.assertEqual(yomiyasu_diff.parse_list(text, pattern=True), list(yomiyasu_diff.BUILTIN_LISTS["feelings"]))

    def test_report_line(self):
        report = yomiyasu_diff.report(result_of("設定を変更した。", "設定を変更して、ほっとした。")).split("\n")
        index = report.index("- 元にない気持ちの語（1行目）: ほっと")
        self.assertEqual(report[index + 1:index + 3], ["  元: 設定を変更した。", "  後: 設定を変更して、ほっとした。"])


if __name__ == "__main__":
    unittest.main()
