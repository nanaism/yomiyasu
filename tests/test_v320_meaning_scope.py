#!/usr/bin/env python3
"""v3.2.0: diff の「意味が変わる恐れ」の照らし合わせを直した所と広げた所の試験（章ごとにクラスを分ける）。

指示書の各章の「当てる形と当てない形」の表の組を、そのまま試験にする。文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


def kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"]]


def of_kind(result, kind):
    return [risk for risk in result["meaning_risks"] if risk["kind"] == kind]


def diff_exit_code(before, after):
    """diff --fail-on meaning-risk の終了コード（元と後は1行の文）。"""
    with tempfile.TemporaryDirectory() as folder:
        old, new = Path(folder) / "old.md", Path(folder) / "new.md"
        old.write_bytes((before + "\n").encode("utf-8"))
        new.write_bytes((after + "\n").encode("utf-8"))
        process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "yomiyasu_diff.py"), "--fail-on", "meaning-risk",
                                  str(old), str(new)], capture_output=True, text=True, encoding="utf-8", cwd=folder)
    return process.returncode


class ZeroMinuteTimeTest(unittest.TestCase):
    """10章: 分が0の時刻を「時」だけで書いた形（18:00 → 18時）を、表記の違いとして打ち消す。"""

    CANCELLED = (
        ("会議は18:00に始めます。", "会議は18時に始めます。"),
        ("切り替えは0:00に行います。", "切り替えは0時に行います。"),
        ("受付は9:00〜17:00です。", "受付は9時〜17時です。"),
        ("説明会は14:00〜15:30に行います。", "説明会は14時〜15時30分に行います。"),
        ("受付は9:00〜9:30です。", "受付は9時〜9時30分です。"),
        # 逆向き
        ("18時に始めます。", "18:00に始めます。"),
        ("受付は9時〜17時です。", "受付は9:00〜17:00です。"),
    )
    # 今までどおり出す: (元, 後, 消えた値, 足した値)
    KEPT = (
        ("受付は9:30からです。", "受付は9時からです。", ["9", "30"], ["9時"]),
        ("開始は13:00です。", "開始は15時です。", ["13", "00"], ["15時"]),
        ("終了は18:00です。", "終了は19時です。", ["18", "00"], ["19時"]),
        ("受付は8:45からです。", "受付は8時からです。", ["8", "45"], ["8時"]),
    )

    def test_cancelled(self):
        for before, after in self.CANCELLED:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_kept(self):
        for before, after, removed, added in self.KEPT:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual([(risk["kind"], risk["subkind"], risk["detail"]) for risk in result["meaning_risks"]],
                                 [("number", "replaced", {"removed": removed, "added": added})])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_existing_cancellations_are_unchanged(self):
        """v3.1.0 で打ち消していた形（10:30 → 10時30分、18:00 → 18時00分、日付）は、今までどおり候補にしない。"""
        for before, after in (("会議は10:30に始めます。", "会議は10時30分に始めます。"),
                              ("会議は18:00に始めます。", "会議は18時00分に始めます。"),
                              ("公開は2026-10-13です。", "公開は2026年10月13日です。"),
                              ("作業は3〜5日かかります。", "作業は3日から5日かかります。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(run(before, after)["meaning_risks"], [])

    def test_only_the_matching_hour_is_cancelled(self):
        """同じ文の2つの時刻のうち、時の値が同じものだけを打ち消し、変わったほうは今までどおり出す。"""
        result = run("会議は18:00と20:00に開きます。", "会議は18時と21時に開きます。")
        self.assertEqual(kinds(result), [("number", "replaced")])
        self.assertEqual(result["meaning_risks"][0]["detail"]["added"], ["21時"])
        self.assertEqual(kinds(run("会議は18:00と20:00に開きます。", "会議は18時と20時に開きます。")), [])

    def test_seconds_are_not_cancelled(self):
        """時:分:秒 の形は打ち消さない（分と秒の組を時と分の組と取り違えないため）。"""
        self.assertEqual(kinds(run("時刻は18:00:00です。", "時刻は18時です。")), [("number", "replaced")])

    def test_cancelled_values_are_not_shown_again(self):
        """打ち消した値は、文書全体で比べるときにも出さない（足した文の中の値は今までどおり比べる）。"""
        before = "会議は18:00に始めます。\n\n場所は本社です。\n"
        after = "会議は18時に始めます。\n\n場所は本社です。\n"
        self.assertEqual(yomiyasu_diff.diff(before, after)["meaning_risks"], [])


class RequestRestatedTest(unittest.TestCase):
    """11章: 「ご提出いただけますと幸いです」「お願いしたい」を依頼の印にし、問いの形の依頼をそのまま依頼の文に言い直した組を、
    問いの変化と依頼の印の足しにしない。逆向き（設計例 PN3a と P6）と、依頼が消えた組は今までどおり出す。"""

    NOT_FOUND = (
        ("書類は金曜までにご提出いただけますと幸いです。", "書類は金曜までに提出してください。"),
        ("ご確認いただけますと助かります。", "確認をお願いします。"),
        ("資料をお送りいただけますでしょうか。", "資料を送ってください。"),
        ("ご連絡いただけますか。", "ご連絡ください。"),
        ("お願いしたいことは3点あります。", "次の3点をお願いします。"),
    )
    # 今までどおり出す: (元, 後, 候補の kind と subkind)
    KEPT = (
        ("資料を確認してください。", "資料をご確認いただけますでしょうか。",
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("目を通しておいてもらえますか。", "お目通しいただけますでしょうか。", [("sentence_type", "marks")]),
        ("ご確認いただけますか。", "確認は不要です。", [("sentence_type", "question")]),
    )

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_kept(self):
        for before, after, expected in self.KEPT:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(kinds(result), expected)
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_new_request_marks(self):
        """依頼・決まりの印に足した2つの形。「よろしくお願いしたい」は今までどおり印にしない。"""
        for text in ("書類をご提出いただけますと幸いです。", "ご確認いただければ助かります。", "ご返信頂けますと幸いです。",
                     "教えていただけたらありがたいです。", "お願いしたいことがあります。"):
            with self.subTest(text=text):
                self.assertIn("依頼・決まり", yomiyasu_diff.type_marks(text))
        for text in ("今後ともよろしくお願いしたいと存じます。", "ご提出いただけますか。"):
            with self.subTest(text=text):
                self.assertNotIn("依頼・決まり", yomiyasu_diff.type_marks(text))

    def test_rule_candidates_still_show_the_change(self):
        """意味が変わる恐れには出さないが、規則の見直し候補の「文の種類を表す語が変わった文」には今までどおり出る。"""
        result = run("資料をお送りいただけますでしょうか。", "資料を送ってください。")
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual([[item["kind"] for item in change["added"]] for change in result["type_changes"]],
                         [["依頼・決まり"]])


class IntensifierWordsTest(unittest.TestCase):
    """12章: 強める語の一覧に、程度や意気込みを強める語を7語足す（勢いの検査。意味が変わる恐れと --fail-on には入らない）。"""

    WORDS = ("大幅", "抜本的", "全力", "飛躍的", "劇的", "心より", "格段")
    # 勢いの候補を出す: (元, 後, 減った語)
    FOUND = (
        ("処理速度が劇的に向上しました。", "処理速度が向上しました。", ["劇的"]),
        ("作業時間を大幅に減らしました。", "作業時間を減らしました。", ["大幅"]),
        ("手順を抜本的に見直し、作業時間を大幅に減らしました。", "手順を見直し、作業時間を減らしました。", ["大幅", "抜本的"]),
        ("新しい窓口の準備に全力で取り組みます。", "新しい窓口の準備に取り組みます。", ["全力"]),
        ("登録の件数が飛躍的に伸びました。", "登録の件数が伸びました。", ["飛躍的"]),
        ("ご参加いただいた皆さまに心よりお礼申し上げます。", "ご参加いただいた皆さまにお礼申し上げます。", ["心より"]),
        ("検索の精度が格段に上がりました。", "検索の精度が上がりました。", ["格段"]),
    )

    def tone_words(self, result):
        return [candidate["detail"]["words"] for candidate in result["tone"]["candidates"]
                if candidate["subkind"] == "intensifier"]

    def test_found(self):
        for before, after, words in self.FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(self.tone_words(result), [words])
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_same_count_is_not_found(self):
        """強める語を同じ数のまま別の語に替えた書き換えは出さない。"""
        result = run("処理速度が劇的に向上しました。", "処理速度が飛躍的に向上しました。")
        self.assertEqual(self.tone_words(result), [])

    def test_words_are_in_the_files_and_the_builtin_list(self):
        """2つの一覧のファイルの最後と内蔵の一覧の最後に、同じ7語が同じ順で入っている。"""
        self.assertEqual(yomiyasu_diff.BUILTIN_LISTS["intensifiers"][-7:], self.WORDS)
        for base in (ROOT / "references" / "lists", ROOT / "skills" / "yomiyasu" / "references" / "lists"):
            with self.subTest(base=str(base.relative_to(ROOT))):
                parsed = yomiyasu_diff.parse_list((base / "intensifiers.txt").read_text(encoding="utf-8"))
                self.assertEqual(tuple(parsed[-7:]), self.WORDS)
        self.assertEqual((ROOT / "references" / "lists" / "intensifiers.txt").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "references" / "lists" / "intensifiers.txt").read_bytes())


class NegatedProhibitionTest(unittest.TestCase):
    """13章: 打ち消した「禁止」（禁止されていません、禁止しません）を許可として読む。「禁止です → かまいません」は今までどおり出す。"""

    NOT_FOUND = (
        ("持ち込みは禁止されていません。", "持ち込んでもかまいません。"),
        ("持ち込みを禁止しません。", "持ち込んでも構いません。"),
        ("飲み物の持ち込みは禁止されていません。", "飲み物は持ち込んでもかまいません。"),
        ("持ち込みは禁止しておりません。", "持ち込んでもかまいません。"),
        ("持ち込みは禁止ではありません。", "持ち込んでもかまいません。"),
    )
    # 今までどおり出す: (元, 後, subkind, from, to)
    KEPT = (
        ("撮影は禁止です。", "撮影してもかまいません。", "permission_added", "禁止", "許可"),
        ("立ち入りは禁止されています。", "立ち入ってもかまいません。", "permission_added", "禁止", "許可"),
        ("持ち込んでもかまいません。", "持ち込みは禁止されています。", "permission_lost", "許可", "禁止"),
    )

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_kept(self):
        for before, after, subkind, source, target in self.KEPT:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual([(risk["kind"], risk["subkind"], risk["detail"]["from"], risk["detail"]["to"])
                                  for risk in result["meaning_risks"]], [("modality", subkind, source, target)])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_negated_prohibition_is_permission(self):
        """打ち消した「禁止」は許可の印になり、禁止の印にならない。打ち消していない「禁止」は今までどおり禁止の印。"""
        def kinds_of(text):
            return [kind for _, kind, _ in yomiyasu_diff._modality_positions(text)]
        for text in ("持ち込みは禁止されていません。", "持ち込みを禁止しません。", "持ち込みは禁止しておりません。",
                     "持ち込みは禁止されていない。", "持ち込みは禁止ではありません。"):
            with self.subTest(text=text):
                self.assertEqual(kinds_of(text), ["許可"])
        for text in ("撮影は禁止です。", "立ち入りは禁止されています。", "持ち込みを禁止します。"):
            with self.subTest(text=text):
                self.assertEqual(kinds_of(text), ["禁止"])


class ObligationTest(unittest.TestCase):
    """14章: 義務の強さの変化（kind obligation）。「必須ではない（任意）」「不要」「必要がある（決まり）」「お願い」の入れ替わりを、
    --fail-on に数えない見直しの候補にする。既存の文の種類の候補などは、重なっても消さない。"""

    # (元, 後, subkind, 元の語, 後の語)
    FOUND = (
        ("回答は必須ではありません。", "回答は不要です。", "optional_to_unneeded", "必須ではありません", "不要"),
        ("事前予約は任意です。", "事前予約は不要です。", "optional_to_unneeded", "任意", "不要"),
        ("参加は必須です。", "参加は任意です。", "duty_to_optional", "必須", "任意"),
        ("申請を行う必要があります。", "申請をお願いします。", "duty_to_request", "必要があります", "お願いします"),
        ("身分証の提示が義務付けられています。", "身分証をご提示ください。", "duty_to_request", "義務", "ご提示ください"),
        # 類例: 逆の向き、丁寧な形の不要、任意を言い直した「してもしなくてもよい」
        ("事前の登録は不要です。", "事前の登録は任意です。", "unneeded_to_optional", "不要", "任意"),
        ("アンケートへの回答は任意です。", "アンケートへの回答は必須です。", "optional_to_duty", "任意", "必須"),
        ("名札の着用は必須ではありません。", "名札は着用しなくてかまいません。", "optional_to_unneeded", "必須ではありません",
         "なくてかまいません"),
        ("書類は提出しなければなりません。", "書類は提出しなくても構いません。", "duty_to_optional", "なければなりません",
         "なくても構いません"),
        ("登録は必須です。", "登録はしてもしなくてもよいです。", "duty_to_optional", "必須", "てもしなくてもよい"),
    )
    NOT_FOUND = (
        ("参加は任意です。", "参加は自由です。"),
        ("全員が出席する必要があります。", "全員の出席が必要です。"),
        ("申請してください。", "申請をお願いします。"),
        ("不要です。", "しなくてかまいません。"),
        # 類例: 任意を「してもしなくてもよい」と言い直した組（中の「しなくてもかまいません」を不要に数えない）
        ("回答は任意です。", "回答はしてもしなくてもかまいません。"),
    )

    def test_found(self):
        for before, after, subkind, source, target in self.FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual([(risk["subkind"], risk["detail"]) for risk in of_kind(result, "obligation")],
                                 [(subkind, {"from": source, "to": target})])
                # 数えない候補なので、--fail-on の数は義務の強さの候補を除いた数と同じ
                self.assertEqual(result["fail_on_meaning_risk_count"],
                                 yomiyasu_diff.fail_on_count([risk for risk in result["meaning_risks"]
                                                              if risk["kind"] != "obligation"]))

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(of_kind(run(before, after), "obligation"), [])

    def test_existing_candidates_are_kept(self):
        """文の種類の候補（依頼の印が増えた）は、義務の強さの候補と重なっても消さず、既存の候補の後ろに並べる。"""
        result = run("身分証の提示が義務付けられています。", "身分証をご提示ください。")
        self.assertEqual(kinds(result), [("sentence_type", "marks"), ("obligation", "duty_to_request")])
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_message(self):
        report = yomiyasu_diff.report(run("回答は必須ではありません。", "回答は不要です。"))
        self.assertIn("- 「必須ではない（任意）」が「不要」に変わった（1行目）: 必須ではありません → 不要。--fail-on には数えません。"
                      "原文の強さ（してもしなくてもよい、しなくてよい、しなければならない）が変わっていないか確かめてください。", report)
        report = yomiyasu_diff.report(run("申請を行う必要があります。", "申請をお願いします。"))
        self.assertIn("- 決まり（必須、しなければならない）が「お願い」に変わった（1行目）: 必要があります → お願いします。", report)

    def test_not_counted(self):
        self.assertNotIn("obligation", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["obligation"], 21)
        self.assertEqual(diff_exit_code("回答は必須ではありません。", "回答は不要です。"), 0)


class CorpusFalsePositiveTest(unittest.TestCase):
    """21章: 推敲の実例（tests/corpus の48組）で見つけた誤った指摘を3つ直す。「事例がある」を「ことがある」と同じ強さに数える、
    「お願いしたい」を依頼の印にする（11章と同じ直し）、後の文の「ところまで」などを範囲を絞る言い方に数える（limiter）。"""

    CORPUS = ROOT / "tests" / "corpus"

    def pair(self, name):
        source = ("blacklist_ai", name[:-6] + ".md") if name.endswith("_bl.md") else ("raw_ai", name)
        before = (self.CORPUS / source[0] / source[1]).read_bytes().decode("utf-8")
        after = (self.CORPUS / "yomiyasu_rewritten" / name).read_bytes().decode("utf-8")
        return yomiyasu_diff.diff(before, after)

    def test_case_word_counts_like_koto_ga_aru(self):
        """「〜事例がある」は「ことがある」と同じ強さ。「事例がありました → ことがありました」は確度の弱まりにしない。"""
        for before, after in (("同時に要求が届くと、更新に失敗する事例がありました。", "同時に要求が届くと、更新に失敗することがありました。"),
                              ("古い端末では表示が崩れる事例があります。", "古い端末では表示が崩れることがあります。")):
            with self.subTest(before=before):
                self.assertEqual(run(before, after)["meaning_risks"], [])

    def test_corpus_pairs(self):
        """3つの組で、直した誤った指摘が出ない（ほかの候補はそのまま）。"""
        result = self.pair("03_pr_description_sonnet_default_bl.md")
        self.assertNotIn(("certainty_review", "weakened"), kinds(result))
        result = self.pair("04_slack_announce_sonnet_default.md")
        self.assertFalse([risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) == ("sentence_type", "marks")
                          and "お願いしたい" in (risk["old"] or "")])
        result = self.pair("06_spec_draft_sonnet_casual_bl.md")
        self.assertNotIn("limiter", [risk["kind"] for risk in result["meaning_risks"]])
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)


if __name__ == "__main__":
    unittest.main()
