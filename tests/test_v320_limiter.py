#!/usr/bin/env python3
"""v3.2.0: diff の、範囲を絞る語（だけ、のみ、しか〜ない、に限る）が消えた書き換え（kind limiter）の試験。

範囲を絞る語が推敲で消えると、読み手が受け取る範囲が広がる。変わった塊ごとに限定の語の数を比べ、減った塊の組の文で、
直前の2字ごと推敲後の文書に残っていない語が、後の文の限定の語より多ければ候補にする（--fail-on=meaning-risk に数える）。
範囲を絞らない使い方（するしかない、いただけません、だけでなく、だけど、それだけに、理由の「〜ただけに、」、「だけでは〜ない」）は数えない。
文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


def limiters(result):
    return [risk for risk in result["meaning_risks"] if risk["kind"] == "limiter"]


# 出す組: (元, 後, 消えた語)
FOUND = [
    ("写真撮影だけなら手伝えます。", "写真撮影でしたら手伝えます。", ["だけ"]),
    ("申込みは会員だけが行えます。", "申込みは会員が行えます。", ["だけ"]),
    ("返金は未開封の場合に限ります。", "返金は未開封の場合に対応します。", ["に限り"]),
    # 既知の限界の試験（test_v200_fix_round4_followup）の組。平仮名の数は比べないが、「だけ」の消えは拾う
    ("参加はひとりだけです。", "参加は自由です。", ["だけ"]),
    # g15 の fixture の case 3 と同じ組（v3.1.0 は意味が変わる恐れを出していなかった）
    ("失敗したときだけ再試行します。", "再試行します。", ["だけ"]),
    ("申込みは会員のみ受け付けます。", "申込みを受け付けます。", ["のみ"]),
    ("対象は正社員に限られます。", "対象は正社員です。", ["に限られ"]),
    ("先着30名に限り、資料を差し上げます。", "先着30名の方に、資料を差し上げます。", ["に限り"]),
    # 名詞のあとの「だけに、」は範囲を絞っている（理由の「だけに、」とは分ける）
    ("会員の方だけに、特典をお送りします。", "会員の方に、特典をお送りします。", ["だけ"]),
    # 名詞のあとの「だけで」は範囲を絞っている（足りることを言う動詞のあとの「だけで」とは分ける）
    ("この部屋は会員だけで運営しています。", "この部屋は会員が運営しています。", ["だけ"]),
]

# 出さない組: (元, 後, 理由)
NOT_FOUND = [
    ("今日のうちに保存するしかない。", "今日のうちに保存する。", "「〜するしかない」は限定ではない"),
    ("この端末ではご利用いただけません。", "この端末では使えません。", "「いただけ」の中の「だけ」"),
    ("ご確認いただければ幸いです。", "ご確認ください。", "「いただけ」の中の「だけ」"),
    ("会員だけが申し込めます。詳しくは窓口へお問い合わせください。",
     "申し込めます。対象は会員だけです。詳しくは窓口へお問い合わせください。", "同じ塊の別の文へ「だけ」を移した"),
    ("新しい版はWindowsだけでなくmacOSでも動きます。", "新しい版はWindowsとmacOSで動きます。", "だけでなく"),
    ("まだ試作だけど、動きます。", "まだ試作ですが、動きます。", "だけど"),
    ("準備に時間をかけた。それだけに、中止は残念だ。", "準備に時間をかけた。そのため、中止は残念だ。", "それだけに"),
    # 述語（た・い・な で終わる形）のあとの「だけに、」は理由を述べる言い方で、範囲を絞っていない
    ("雨が降っただけに、客足は少なかった。", "雨が降ったので、客足は少なかった。", "理由の「だけに、」（た）"),
    ("期待が大きかっただけに、落胆も大きかった。", "期待が大きかったので、落胆も大きかった。", "理由の「だけに、」（い）"),
    ("手作業で数えるのは不正確なだけに、集計は機械で行う。", "手作業で数えるのは不正確なので、集計は機械で行う。",
     "理由の「だけに、」（な）"),
    # 動詞と形容詞のあとの、足りることを言う「だけで」は範囲を絞っていない
    ("下流が一つ落ちただけで上流までタイムアウトが連鎖する。", "下流の1件の停止が上流のタイムアウトの連鎖につながる。",
     "足りることを言う「だけで」（た）"),
    ("このボタンを押すだけで設定が完了します。", "このボタンを押すと設定が完了します。", "足りることを言う「だけで」（す）"),
    # 後の文の「限定」は、範囲を絞る言い方が残っている
    ("トランザクションはDB更新の直前のみで開始します。", "トランザクション開始位置のDB更新直前への限定を行います。", "への限定"),
    ("会員だけが申し込めます。", "申し込めるのは会員だけです。", "元と後に同じ数の限定の語がある"),
    ("できるだけ早く返信します。", "なるべく早く返信します。", "できるだけ"),
    ("社員のみならず、家族も参加できます。", "社員も家族も参加できます。", "のみならず"),
    ("社員に限らず、誰でも参加できます。", "誰でも参加できます。", "に限らず"),
    # 「だけでは」「だけで」のあとの同じ節に打ち消しがある形は、それだけでは足りないという意味で、範囲を絞っていない
    ("キューを導入するだけでは耐障害性は確保されず、設計が要る。", "キューを導入しても耐障害性は確保されず、設計が要る。",
     "だけでは〜ず"),
    ("手順書を配るだけでは事故は減りません。", "手順書を配っても事故は減りません。", "だけでは〜ません"),
    ("それだけで品質が上がるわけではありません。", "それで品質が上がるわけではありません。", "だけで〜ありません"),
]


class LimiterFoundTest(unittest.TestCase):
    def test_found(self):
        for before, after, words in FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                found = limiters(result)
                self.assertEqual(len(found), 1, result["meaning_risks"])
                risk = found[0]
                self.assertEqual(risk["subkind"], None)
                self.assertEqual(risk["detail"], {"words": words})
                self.assertEqual((risk["old_line"], risk["new_line"], risk["old"], risk["new"]), (1, 1, before, after))
                self.assertIsNone(risk["basis"])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_shika_with_negation(self):
        """「しか〜ない」は、あとの同じ節に打ち消しがあるときだけ数える。打ち消しの消えは否定の候補にもなる。"""
        result = run("この画面は管理者しか開けません。", "この画面は管理者が開けます。")
        self.assertEqual([risk["detail"] for risk in limiters(result)], [{"words": ["しか"]}])
        self.assertIn("negation", [risk["kind"] for risk in result["meaning_risks"]])

    def test_only_limiter_is_counted(self):
        """限定の語の消えだけの組でも、--fail-on=meaning-risk に数える。"""
        result = run("申込みは会員だけが行えます。", "申込みは会員が行えます。")
        self.assertEqual([risk["kind"] for risk in result["meaning_risks"]], ["limiter"])
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        self.assertEqual(yomiyasu_diff.fail_on_count(result["meaning_risks"]), 1)

    def test_message(self):
        risk = limiters(run("写真撮影だけなら手伝えます。", "写真撮影でしたら手伝えます。"))[0]
        self.assertEqual(yomiyasu_diff._risk_line(risk),
                         "限定の語が消えた（1行目）: 「だけ」。原文は範囲を絞っています。推敲後の文で範囲が広がっていないか"
                         "確かめ、広がっていれば原文の語を戻してください。")

    def test_report_section(self):
        result = run("返金は未開封の場合に限ります。", "返金は未開封の場合に対応します。")
        text = yomiyasu_diff.report(result)
        self.assertIn("■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）", text)
        self.assertIn("- 限定の語が消えた（1行目）: 「に限り」。", text)
        self.assertIn("  元: 返金は未開封の場合に限ります。", text)
        self.assertIn("  後: 返金は未開封の場合に対応します。", text)

    def test_lines_in_a_longer_document(self):
        before = "# 申込み\n\n申込みは会員だけが行えます。\n\n受付は窓口で行います。\n"
        after = "# 申込み\n\n申込みは会員が行えます。\n\n受付は窓口で行います。\n"
        found = limiters(yomiyasu_diff.diff(before, after))
        self.assertEqual([(risk["old_line"], risk["new_line"]) for risk in found], [(3, 3)])

    def test_public_function_matches_diff(self):
        before, after = "失敗したときだけ再試行します。\n", "再試行します。\n"
        changes = yomiyasu_diff.diff(before, after)["type_changes"]
        self.assertEqual(yomiyasu_diff.meaning_risks(before, after, type_changes=changes),
                         yomiyasu_diff.diff(before, after)["meaning_risks"])


class LimiterNotFoundTest(unittest.TestCase):
    def test_not_found(self):
        for before, after, reason in NOT_FOUND:
            with self.subTest(before=before, after=after, reason=reason):
                self.assertEqual(limiters(run(before, after)), [])

    def test_hiragana_numbers_with_shika_are_not_found(self):
        """「ふたつしかない」「ひとつしかない」のような「しかない」の形は数えない（既知の限界の試験と同じ組）。"""
        for before, after in (("席はふたつしかない。", "席は十分ある。"), ("席はひとつしかない。", "席は空いている。")):
            with self.subTest(before=before):
                result = run(before, after)
                self.assertEqual(limiters(result), [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_moved_to_another_line_in_the_same_hunk(self):
        """同じ塊の別の行へ移した書き換えも、塊の限定の語の数が減っていないので出さない。"""
        before = "申込みは会員だけが行えます。\n受付は窓口で行います。\n"
        after = "申込みは窓口で行えます。\n受付は会員だけです。\n"
        self.assertEqual(limiters(yomiyasu_diff.diff(before, after)), [])

    def test_word_kept_elsewhere_in_the_document(self):
        """消えた語が直前の2字ごと推敲後の文書のどこかに残っていれば、その語は消えたことにしない。"""
        before = "申込みは会員だけが行えます。\n\n## 補足\n\n受付は窓口です。\n"
        after = "申込みは会員が行えます。\n\n## 補足\n\n受付は窓口で、会員だけが対象です。\n"
        self.assertEqual(limiters(yomiyasu_diff.diff(before, after)), [])

    def test_existing_number_kind_is_unchanged(self):
        """数値の候補（kind number）の形は変わらない。"""
        result = run("移行は3日で終える。", "移行は30日で終える。")
        self.assertEqual([(risk["kind"], risk["subkind"], risk["detail"]) for risk in result["meaning_risks"]],
                         [("number", "replaced", {"removed": ["3日"], "added": ["30日"]})])


class LimiterKeptTest(unittest.TestCase):
    """21章: 後の文の「ところまで」「までにとどめ」「にとどめ」「に留め」「に絞（っ・り・る）」を、範囲を絞る言い方として後の文の
    限定の語の数に足す（範囲を保った言い換えに出さない）。"""

    NOT_FOUND = (
        ("受付は本人確認だけを窓口で行います。", "受付は本人確認をするところまでを窓口で行います。"),
        ("今回の調査は原因の特定だけにします。", "今回の調査は原因の特定にとどめます。"),
        ("修正は表示の崩れだけにします。", "修正は表示の崩れまでにとどめます。"),
        ("公開は社内だけにします。", "公開は社内に留めます。"),
        ("対象は東京の店舗だけです。", "対象は東京の店舗に絞ります。"),
        ("案内は会員だけに送ります。", "案内は会員に絞って送ります。"),
    )

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(limiters(run(before, after)), [])

    def test_kept_expression_does_not_count_on_the_original_side(self):
        """範囲を絞る言い方は後の文の側だけで数える。元の文の「にとどめ」が消えただけの組は、限定の語の候補にしない。"""
        self.assertEqual(limiters(run("今回の調査は原因の特定にとどめます。", "今回の調査で原因を特定します。")), [])

    def test_without_the_expression_it_is_found(self):
        """同じ組でも、後の文に範囲を絞る言い方がなければ今までどおり出す。"""
        result = run("受付は本人確認だけを窓口で行います。", "受付は本人確認を窓口で行います。")
        self.assertEqual([risk["detail"] for risk in limiters(result)], [{"words": ["だけ"]}])


class LimiterContractTest(unittest.TestCase):
    def test_kind_order_and_fail_on(self):
        """limiter は number_qualifier のあとに足し、--fail-on=meaning-risk に数える。既存の kind の並びはそのまま。"""
        self.assertEqual(yomiyasu_diff.FAIL_ON_KINDS[:12],
                         ("number", "negation", "swap", "sentence_type", "citation", "certainty", "state", "promise",
                          "modality", "choice", "causality", "number_qualifier"))
        self.assertIn("limiter", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["limiter"], 19)

    def test_cli_fail_on_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a.md", Path(folder) / "b.md"
            a.write_bytes("申込みは会員だけが行えます。\n".encode("utf-8"))
            b.write_bytes("申込みは会員が行えます。\n".encode("utf-8"))
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "--fail-on=meaning-risk",
                                      str(a), str(b)], capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                     cwd=folder)
        self.assertEqual(process.returncode, 1, process.stderr.decode("utf-8"))
        self.assertIn("限定の語が消えた（1行目）: 「だけ」", process.stdout.decode("utf-8"))

    def test_fail_on_line_names_the_kind(self):
        """数えない候補が混ざるときの最後の行に、数えた種類として「限定の語」を書く。"""
        result = run("申込みは会員だけが `form` で行えます。", "申込みは会員が `forms` で行えます。")
        risks = result["meaning_risks"]
        self.assertEqual(sorted(risk["kind"] for risk in risks), ["limiter", "protected"])
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        self.assertEqual(yomiyasu_diff._fail_on_line(len(risks), 1, risks),
                         "終了コード1: --fail-on=meaning-risk の条件に当たりました"
                         "（意味が変わる恐れ 2件のうち、数値・否定・入れ替え・文の種類・限定の語 1件）。")

    def test_twin_scripts_are_identical(self):
        self.assertEqual((ROOT / "scripts" / "yomiyasu_diff.py").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_diff.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
