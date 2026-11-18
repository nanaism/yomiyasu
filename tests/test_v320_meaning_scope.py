#!/usr/bin/env python3
"""v3.2.0: diff の「意味が変わる恐れ」の照らし合わせを直した所と広げた所の試験（章ごとにクラスを分ける）。

指示書の各章の「当てる形と当てない形」の表の組を、そのまま試験にする。文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


def kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"]]


def of_kind(result, kind):
    return [risk for risk in result["meaning_risks"] if risk["kind"] == kind]


def rewrite_pairs():
    """推敲の48組（元、後、名前）。tests/test_v200_meaning_risks.py の corpus_pairs() と同じ作り方。"""
    pairs = []
    for name in sorted(os.listdir(CORPUS / "yomiyasu_rewritten")):
        if not name.endswith(".md"):
            continue
        source = CORPUS / "blacklist_ai" / (name[:-6] + ".md") if name.endswith("_bl.md") else CORPUS / "raw_ai" / name
        pairs.append((source.read_bytes().decode("utf-8"),
                      (CORPUS / "yomiyasu_rewritten" / name).read_bytes().decode("utf-8"), name))
    return pairs


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

    def test_swapped_times_are_not_cancelled(self):
        """時の並びが相手の側と同じ順でない書き換え（時刻の入れ替え）は打ち消さず、今までどおり数値の候補にする。"""
        for before, after in (("会議は18:00、懇親会は19:00からです。", "会議は19時、懇親会は18時からです。"),
                              ("受付は9:00〜17:00です。", "受付は17時〜9時です。")):
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(kinds(result), [("number", "replaced")])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

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
        # 元の文も頼む内容を打ち消した依頼なら、言い直し
        ("資料を送らないでいただけますか。", "資料を送らないでください。"),
        # 「ご遠慮なく」（気軽にどうぞ）、名詞の「控え」、「禁止事項」は、頼む内容を打ち消した依頼ではない
        ("ご不明な点があれば、お知らせいただけますか。", "ご不明な点があれば、ご遠慮なくお知らせください。"),
        ("申込書を印刷していただけますか。", "申込書を印刷し、控えを保管してください。"),
        ("利用規約をお読みいただけますか。", "利用規約の禁止事項をお読みください。"),
    )
    # 今までどおり出す: (元, 後, 候補の kind と subkind)
    KEPT = (
        ("資料を確認してください。", "資料をご確認いただけますでしょうか。",
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("目を通しておいてもらえますか。", "お目通しいただけますでしょうか。", [("sentence_type", "marks")]),
        ("ご確認いただけますか。", "確認は不要です。", [("sentence_type", "question")]),
        # 問いの形の依頼を、頼む内容を打ち消した依頼に変えた組は、言い直しとして外さない
        ("資料をお送りいただけますか。", "資料を送らないでください。", [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("会議にご参加いただけますか。", "会議へのご参加はご遠慮ください。",
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("撮影していただけますか。", "撮影は控えてください。", [("sentence_type", "question")]),
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

    def test_casual_request_counts_like_the_polite_one(self):
        """くだけた「〜てもらえると助かります」「〜いただけると助かります」も依頼の印にする。敬語に直しただけの推敲（見てもらえると
        助かります → ご確認いただけますと幸いです）を、依頼の印の足しにしない。依頼が消えた書き換えは今までどおり出す。"""
        for text in ("見てもらえると助かります。", "お返事をいただけると助かります。", "読んでもらえればありがたいです。"):
            with self.subTest(text=text):
                self.assertIn("依頼・決まり", yomiyasu_diff.type_marks(text))
        for before, after in (("住所が合っているか、見てもらえると助かります。", "住所が合っているか、ご確認いただけますと幸いです。"),
                              ("お返事をいただけると助かります。", "お返事をいただけますと幸いです。"),
                              ("14日までに送ってもらえると助かります。", "14日までにお送りいただけますと助かります。")):
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)
        result = run("手伝ってもらえると助かります。", "手伝ってもらえました。")
        self.assertIn(("sentence_type", "marks"), kinds(result))
        self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_onegai_kept_in_another_form(self):
        """「お願いしたい」を印の形でない「お願い」（お願いし、お願いです）で言い直した組は、依頼・決まりの印が消えたことにしない。
        「お願い」が残らない組と、済んだことの報告（お願いしました）にした組は今までどおり出す。3.1.0 からの「お願いします」の
        消えは変えない。"""
        for before, after in (("まずお願いしたいのは資料の作成ではなく、内容の確認です。",
                               "まず内容の確認をお願いし、資料の作成については後日で構いません。"),
                              ("先方にお願いしたい点を整理します。", "先方へのお願いを整理します。")):
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertNotIn(("sentence_type", "marks"), kinds(result))
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)
        for before, after in (("お願いしたいことは3点あります。", "次の3点です。"),
                              ("お願いしたいことは3点あります。", "次の3点をお願いしました。"),
                              ("先方に資料の確認をお願いしたいです。", "先方に資料の確認をお願いしておきました。"),
                              ("先方にお願いしたい点を整理します。", "先方からお願いされた点を整理します。"),
                              ("確認をお願いします。", "確認をお願いし、結果を共有しました。")):
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertIn(("sentence_type", "marks"), kinds(result))
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_more_request_forms(self):
        """「いただけましたら幸い」「お願いできれば幸い」も依頼の印にする。お礼の決まり文句「そう言っていただけると助かります」は
        依頼の印にしない。「お願いしたく」「いただきたく」は印にしない（「〜いただきたく、ご連絡いたしました」のような知らせの文で、
        片方の文だけが印になる組が増えるため。限界）。"""
        for before, after in (("ご確認いただけましたら幸いです。", "ご確認ください。"),
                              ("ご確認をお願いできれば幸いです。", "ご確認をお願いします。"),
                              ("そう言っていただけると助かります。", "お気遣いありがとうございます。"),
                              ("そうおっしゃっていただけると助かります。", "お気遣いありがとうございます。"),
                              ("何かあればおっしゃっていただけると助かります。", "何かあればご連絡ください。"),
                              ("ご確認いただけましたら幸いです。", "ご確認のほど、よろしくお願いいたします。"),
                              ("ご返信いただけましたら幸いです。", "ご返信をお待ちしております。"),
                              ("先方にお願いできれば、作業は早く終わります。", "先方に頼めれば、作業は早く終わります。"),
                              ("ご確認をお願いできればと存じます。", "ご確認をお願いします。"),
                              ("そう言っていただけるとありがたいです。", "そう言っていただき、ありがとうございます。")):
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)
        self.assertNotIn("依頼・決まり", yomiyasu_diff.type_marks("そう言っていただけると助かります。"))

    def test_closing_greeting_without_content_is_not_a_kept_request(self):
        """頼む中身のない結びの挨拶（今後ともよろしくお願いいたします）に言い直した組は、依頼が消えたことのまま出す。"""
        result = run("資料をご確認ください。", "今後ともよろしくお願いいたします。")
        self.assertIn(("sentence_type", "marks"), kinds(result))

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

    def test_words_inside_other_words_are_not_counted(self):
        """漢字が前に付いた語の中の「心より」「劇的」（中心より、重心より、都心より、演劇的、悲劇的）は、強める語に数えない。
        「衷心より」は数える。"""
        for before, after in (("ボタンは画面の中心より右に置きます。", "ボタンは画面の中央から右に置きます。"),
                              ("荷物は重心より前に積みます。", "荷物は重心の前方に積みます。"),
                              ("演劇的な照明を使います。", "舞台のような照明を使います。"),
                              ("悲劇的な結末です。", "悲しい結末です。"),
                              ("都心より郊外が安い。", "郊外が安い。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(self.tone_words(run(before, after)), [])

    def test_chushin_yori_is_counted(self):
        self.assertEqual(self.tone_words(run("衷心よりお礼申し上げます。", "お礼申し上げます。")), [["心より"]])

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
        ("持ち込みは禁止されてはいません。", "持ち込んでもかまいません。"),
        ("持ち込みは禁止されておらず、自由です。", "持ち込んでもかまいません。"),
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
        # 「してもしなくてもよい」は任意に数え、中の「しなくてもよい」を不要に数えない
        ("提出は不要です。", "提出はしてもしなくてもよいです。", "unneeded_to_optional", "不要", "てもしなくてもよい"),
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


class ChoiceJoinedTest(unittest.TestCase):
    """15章: 「AまたはB」「AかB」（どれか一つ）を「AとB」（全部）にした書き換え（既存の kind choice、subkind one_to_all。
    --fail-on に数える）。後の文にどれか一つか全部を表す言い方があれば出さず、既存の choice と合わせて1件だけにする。"""

    # (元, 後, 元の語, 後の語)
    FOUND = (
        ("お問い合わせは電話かメールで受け付けます。", "お問い合わせは電話とメールで受け付けます。", "か", "と"),
        ("申請は紙の申請書もしくはWebフォームで行います。", "申請は紙の申請書とWebフォームで行います。", "もしくは", "と"),
        ("AプランかBプランのいずれかを選べます。", "AプランとBプランを選べます。", "か", "と"),
        ("お支払いはクレジットカード、または銀行振込です。", "お支払いはクレジットカードと銀行振込です。", "または", "と"),
        # 類例: あるいは → および
        ("連絡先には電話番号あるいはメールアドレスを書きます。", "連絡先には電話番号およびメールアドレスを書きます。", "あるいは",
         "および"),
        # 接続の「一方、」は、どれか一つを選ぶ言い方ではない
        ("お問い合わせは電話かメールで受け付けますが、窓口では受け付けません。",
         "お問い合わせは電話とメールで受け付ける一方、窓口では受け付けません。", "か", "と"),
    )
    NOT_FOUND = (
        ("申請はWebまたは郵送で受け付け、書類は漏れなくそろえてください。", "申請はWeb・郵送で受け付けます。書類はすべてそろえてください。"),
        ("WebまたはCLIで設定できる。", "WebとCLIのいずれでも設定できる。"),
        ("WebまたはCLIで設定できる。", "WebとCLIのどちらでも設定できる。"),
        ("AまたはBを選んでください。", "AかBを選んでください。"),
        ("電話かメールでご連絡ください。", "電話やメールなどでご連絡ください。"),
        ("何かあれば連絡してください。", "何かあったら連絡してください。"),
        # 類例: つないだ名詞の中から選ぶ言い方
        ("AかBを選んでください。", "AとBから選んでください。"),
        ("AプランかBプランを選んでください。", "AプランとBプランの一方を選んでください。"),
        ("AプランかBプランを選んでください。", "AプランとBプランの片方を選んでください。"),
        # 問いの「か」（設定が有効か確認する）は、どれか一つを選ぶ言い方ではない
        ("設定が有効か管理者に確認します。", "設定が有効と管理者に確認しました。"),
    )

    def test_found(self):
        for before, after, source, target in self.FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual([(risk["subkind"], risk["detail"]) for risk in of_kind(result, "choice")],
                                 [("one_to_all", {"from": "どれか一つ", "to": "全部", "old_hits": [source], "new_hits": [target]})])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(of_kind(run(before, after), "choice"), [])

    def test_one_candidate_with_the_existing_rule(self):
        """後の文に全部の言い方（両方、双方）がある組は、既存の choice の候補1件だけ。"""
        for before, after, target in (("AまたはBを選ぶ。", "AとBの両方を選ぶ。", "両方"),
                                      ("メールもしくは電話で連絡する。", "メールと電話の双方で連絡する。", "双方")):
            with self.subTest(before=before):
                found = of_kind(run(before, after), "choice")
                self.assertEqual([risk["detail"]["new_hits"] for risk in found], [[target]])

    def test_message_and_exit_code(self):
        report = yomiyasu_diff.report(run("お問い合わせは電話かメールで受け付けます。", "お問い合わせは電話とメールで受け付けます。"))
        self.assertIn("- 選ぶ範囲が「どれか一つ」から「全部」に変わった（1行目）: どれか一つ（か） → 全部（と）。", report)
        self.assertEqual(diff_exit_code("お問い合わせは電話かメールで受け付けます。", "お問い合わせは電話とメールで受け付けます。"), 1)
        self.assertEqual(diff_exit_code("AまたはBを選んでください。", "AかBを選んでください。"), 0)

    def test_public_function_without_type_changes(self):
        """meaning_risks() に type_changes を渡さないときは、既存の選ぶ範囲の候補と同じく、「と」でつないだ書き換えの候補も
        足さない。渡したときは diff() と同じ。"""
        before, after = "お問い合わせは電話かメールで受け付けます。\n", "お問い合わせは電話とメールで受け付けます。\n"
        self.assertEqual(yomiyasu_diff.meaning_risks(before, after), [])
        result = yomiyasu_diff.diff(before, after)
        self.assertEqual(yomiyasu_diff.meaning_risks(before, after, type_changes=result["type_changes"]), result["meaning_risks"])
        self.assertEqual(kinds(result), [("choice", "one_to_all")])


class QuantifierTest(unittest.TestCase):
    """16章: 範囲の語が消えた書き換え（kind quantifier。--fail-on に数えない見直しの候補）。全部（すべて、全て、全部、全件）、
    全員、一切、例外なく（例外なく、もれなく、漏れなく）の集まりごとに数え、同じ集まりの言い換えは消えたことにしない。"""

    # (元, 後, 消えた語)
    FOUND = (
        ("新しい規程は全員に適用されます。", "新しい規程が適用されます。", ["全員"]),
        ("参加者は例外なく名札を着用してください。", "参加者は名札を着用してください。", ["例外なく"]),
        ("すべての端末を更新します。", "一部の端末を更新します。", ["すべて"]),
        # 類例
        ("申込書はもれなく提出してください。", "申込書を提出してください。", ["もれなく"]),
        ("手順を全面的に見直します。", "手順を見直します。", ["全面"]),
    )
    NOT_FOUND = (
        ("全部のファイルを保存してください。", "すべてのファイルを保存してください。"),
        ("すべての項目を確認します。", "項目はすべて確認します。"),
        ("全員に配布します。", "皆さん全員に配布します。"),
        ("閲覧、更新、バッチ処理のすべてがご利用いただけません。", "閲覧も更新もバッチ処理もできません。"),
        # 類例: 別の集まりの語で言い直した組（文を分けた組も）、別の文へ移した組、「一切れ」
        ("書類は漏れなくそろえてください。", "書類はすべてそろえてください。"),
        ("申請はWebまたは郵送で受け付け、書類は漏れなくそろえてください。", "申請はWeb・郵送で受け付けます。書類はすべてそろえてください。"),
        ("資料は全員に配ります。説明会を開きます。", "資料を配ります。説明会は全員が対象です。"),
        ("ケーキを一切れ食べました。", "ケーキを食べました。"),
        # 「全面」は全部の集まりの語（全部直す → 全面修正）
        ("一度に全部直すと差分が大きくなります。", "一括での全面修正は差分の肥大化につながります。"),
    )

    def test_found(self):
        for before, after, words in self.FOUND:
            with self.subTest(before=before, after=after):
                found = of_kind(run(before, after), "quantifier")
                self.assertEqual([(risk["subkind"], risk["detail"]) for risk in found], [(None, {"words": words})])

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(of_kind(run(before, after), "quantifier"), [])

    def test_existing_negation_is_kept(self):
        """「例外なく」の消えは、今までどおり否定の数の変化にも出る（範囲の語の候補は既存の候補の後ろ）。"""
        result = run("参加者は例外なく名札を着用してください。", "参加者は名札を着用してください。")
        self.assertEqual(kinds(result), [("negation", None), ("quantifier", None)])
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_message_and_not_counted(self):
        report = yomiyasu_diff.report(run("新しい規程は全員に適用されます。", "新しい規程が適用されます。"))
        self.assertIn("- 範囲の語が消えた（1行目）: 「全員」。--fail-on には数えません。原文は全部に当てはまると書いています。"
                      "推敲後の文で範囲があいまいになっていないか確かめてください。", report)
        self.assertNotIn("quantifier", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["quantifier"], 22)
        self.assertEqual(diff_exit_code("新しい規程は全員に適用されます。", "新しい規程が適用されます。"), 0)


class DeadlineTest(unittest.TestCase):
    """17章: 期限の語（までに、以内、より前に、期限、必着）が消えた書き換え（kind deadline。--fail-on に数えない見直しの候補）。"""

    # (元, 後, 消えた語)
    FOUND = (
        ("経費精算は月末までに提出してください。", "経費精算は月末に提出してください。", ["までに"]),
        ("返金は申請から3営業日以内に行います。", "返金は申請から3営業日で行います。", ["以内"]),
        ("申込書は15日必着でお送りください。", "申込書は15日にお送りください。", ["必着"]),
        ("解約は30日前までに通知してください。", "解約は30日前に通知してください。", ["までに"]),
        # 類例
        ("返金は3営業日以内に行います。", "返金は3営業日ほどで行います。", ["以内"]),
    )
    NOT_FOUND = (
        ("金曜までに提出してください。", "提出の期限は金曜です。"),
        ("10日までに申し込んでください。", "申し込みの期限は10日です。"),
        ("一人で運用できるまでになった。", "一人で運用できるようになった。"),
        ("3日以内にご返信ください。", "3日以内に返信してください。"),
        # 類例: 期限でない「までに」「以内」、同じ意味の言い換え、文書全体で数が減らない組
        ("参考までに、手順を書きます。", "手順を書きます。"),
        ("これまでに3回の障害がありました。", "3回の障害がありました。"),
        ("画像は5MB以内にしてください。", "画像は5MBにしてください。"),
        ("会議より前に資料を送ってください。", "会議の前に資料を送ってください。"),
        ("提出期限は10日です。", "提出の期日は10日です。"),
        ("月末までに提出してください。窓口は平日に開きます。", "月末に提出してください。窓口は17時までに閉まります。"),
        # 物や権利の期限（有効期限、賞味期限）は、動作の期限ではない
        ("排他ロック（有効期限10分）を導入しました。", "排他ロック（10分で切れる）を入れました。"),
        ("賞味期限は製造から30日です。", "製造から30日はおいしく食べられます。"),
    )

    def test_found(self):
        for before, after, words in self.FOUND:
            with self.subTest(before=before, after=after):
                found = of_kind(run(before, after), "deadline")
                self.assertEqual([(risk["subkind"], risk["detail"]) for risk in found], [(None, {"words": words})])

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(of_kind(run(before, after), "deadline"), [])

    def test_request_candidate_is_kept(self):
        """「期限は金曜です」の組には、今までどおり文の種類の候補（依頼が消えた）が出る。"""
        result = run("金曜までに提出してください。", "提出の期限は金曜です。")
        self.assertEqual(kinds(result), [("sentence_type", "marks")])

    def test_deadline_kept_elsewhere_in_the_document(self):
        """見出しの「返却（14日以内）」を「返却」にしても、本文に同じ「14日以内」が残っていれば出さない。"""
        before = "## 返却（14日以内）\n\n借りた本は14日以内に返してください。\n"
        after = "## 返却\n\n借りた本は14日以内に返してください。\n"
        self.assertEqual(of_kind(yomiyasu_diff.diff(before, after), "deadline"), [])

    def test_message_and_not_counted(self):
        report = yomiyasu_diff.report(run("経費精算は月末までに提出してください。", "経費精算は月末に提出してください。"))
        self.assertIn("- 期限の語が消えた（1行目）: 「までに」。--fail-on には数えません。原文の期限（その日までに、その日数以内に）が、"
                      "その日ちょうどの意味に変わっていないか確かめてください。", report)
        self.assertNotIn("deadline", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["deadline"], 23)
        self.assertEqual(diff_exit_code("経費精算は月末までに提出してください。", "経費精算は月末に提出してください。"), 0)


class ConditionTest(unittest.TestCase):
    """18章: 条件の句が消えた書き換え（kind condition。--fail-on に数えない見直しの候補）。3.1.0 までは意味が変わる恐れに
    しないと決めていた（test_v200_meaning_risks の test_removed_condition）が、3.2.0 で仕様を変えた。"""

    # (元, 後, 消えた句)
    FOUND = (
        ("管理者権限がある場合は、設定を変更できます。", "設定を変更できます。", "管理者権限がある場合は"),
        ("会員登録をした方は、送料が無料になります。", "送料が無料になります。", "会員登録をした方は"),
        ("体調が優れないときは、無理せず休んでください。", "無理せず休んでください。", "体調が優れないときは"),
        ("海外から接続する際には、VPNを経由してください。", "VPNを経由してください。", "海外から接続する際には"),
        ("在庫がある限り、即日発送します。", "即日発送します。", "在庫がある限り、"),
        ("雨なら、中止する。", "中止する。", "雨なら、"),
    )
    NOT_FOUND = (
        ("雨の場合は中止します。", "雨が降ったら中止します。"),
        ("障害が起きた場合は、担当者に連絡します。", "担当者に連絡するのは、障害が起きたときです。"),
        ("ログを確認する際は、管理画面を開きます。", "ログを確認するときは、管理画面を開きます。"),
        ("上限回数を超えた場合は退避します。", "回数が上限に達したら退避します。"),
        # 類例: 句を言い換えて条件を残した組、語のない句、読点のない「なら」
        ("会議室の鍵が開かないときは、受付に連絡してください。", "解錠できないときは、受付にご連絡ください。"),
        ("その場合は、担当者に連絡します。", "担当者に連絡します。"),
        ("雨なら中止する。", "中止する。"),
    )

    def test_found(self):
        for before, after, clause in self.FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual([(risk["subkind"], risk["detail"]) for risk in of_kind(result, "condition")],
                                 [(None, {"clause": clause})])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(of_kind(run(before, after), "condition"), [])

    def test_known_limit(self):
        """限界: 「雨天」と「雨」を同じ語とみなさないので、「雨天の場合、→ 雨が降ったら」には出る。"""
        self.assertEqual([risk["detail"] for risk in of_kind(run("雨天の場合、中止します。", "雨が降ったら中止します。"), "condition")],
                         [{"clause": "雨天の場合、"}])

    def test_message_and_not_counted(self):
        report = yomiyasu_diff.report(run("管理者権限がある場合は、設定を変更できます。", "設定を変更できます。"))
        self.assertIn("- 条件の句が消えた（1行目）: 「管理者権限がある場合は」。--fail-on には数えません。原文は、この条件のときだけの話"
                      "として書いています。条件を外して、いつでも当てはまる文にしていないか確かめてください。", report)
        self.assertNotIn("condition", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["condition"], 24)
        self.assertEqual(diff_exit_code("管理者権限がある場合は、設定を変更できます。", "設定を変更できます。"), 0)


class DroppedSentenceTest(unittest.TestCase):
    """19章: 段落から文が丸ごと消えた書き換え（kind dropped_sentence。--fail-on に数えない見直しの候補）。言い換えて組に
    ならなかった文と分けるため、条件を絞る。"""

    # (元, 後, 消えた内容の語)
    FOUND = (
        ("メンテナンスは22時から翌2時までです。作業中はログインできません。終了後にお知らせします。",
         "メンテナンスは22時から翌2時までです。終了後にお知らせします。", ["作業中", "ログイン"]),
        ("4月から料金を改定します。既存の契約は更新日まで旧料金のままです。詳しくは窓口へお問い合わせください。",
         "4月から料金を改定します。詳しくは窓口へお問い合わせください。", ["既存", "契約", "更新日"]),
        ("商品は到着から8日以内であれば返品できます。返品の送料はお客様のご負担となります。返品の際は、購入時の伝票を同封してください。",
         "商品は到着から8日以内であれば返品できます。返品の際は、購入時の伝票を同封してください。", ["送料", "客様", "負担"]),
    )
    NOT_FOUND = (
        # 1文を2文に分けた書き換え、2文を1文にまとめた書き換え
        ("会議は10時に始まり、資料は前日までに共有します。", "会議は10時に始まります。資料は前日までに共有します。"),
        ("会議は10時に始まります。資料は前日までに共有します。", "会議は10時に始まり、資料は前日までに共有します。"),
        # 3文を3文のまま言い換えた段落
        ("障害の原因はメモリ不足だった。再起動で復旧した。今後は監視を強める。",
         "原因はメモリが足りなかったことだった。再起動して復旧した。今後は監視を強化する。"),
        # 予告の文（類例: 文書そのものを指して始まる予告の文も）
        ("比較結果は以下のとおり。処理Aは処理Bより速い。", "処理Aは処理Bより速い。"),
        ("この記事では、旅行の計画を立てる手順を紹介します。まず行き先と日程を決めます。", "まず行き先と日程を決めます。"),
        # 類例: 句点で終わらない文、先頭15字にコロンがある文、「■」で始まる文
        ("料金は4月に改定します。既存の契約は更新日まで旧料金のまま", "料金は4月に改定します。"),
        ("料金は4月に改定します。注意：既存の契約は更新日まで旧料金です。", "料金は4月に改定します。"),
        ("料金は4月に改定します。■既存の契約は更新日まで旧料金です。", "料金は4月に改定します。"),
    )

    def test_found(self):
        for before, after, words in self.FOUND:
            with self.subTest(before=before):
                found = of_kind(run(before, after), "dropped_sentence")
                self.assertEqual([(risk["subkind"], risk["old_line"], risk["new_line"], risk["new"], risk["detail"])
                                  for risk in found], [(None, 1, None, None, {"words": words})])
                self.assertEqual(run(before, after)["fail_on_meaning_risk_count"], 0)

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before):
                self.assertEqual(of_kind(run(before, after), "dropped_sentence"), [])

    def test_heading_line_is_not_found(self):
        before = "# 料金の改定\n\n## 既存の契約は更新日まで旧料金です。\n\n4月から料金を改定します。\n"
        after = "# 料金の改定\n\n4月から料金を改定します。\n"
        self.assertEqual(of_kind(yomiyasu_diff.diff(before, after), "dropped_sentence"), [])

    def test_other_candidate_on_the_same_line(self):
        """設計例 S1: 状態の候補が同じ元の行にあるので、消えた文の候補は出さない（同じ変化を2回数えない）。"""
        result = run("ご依頼の部材の納期は未定です。メーカーからの回答を待っています。",
                     "ご依頼の部材は、メーカーからの回答を受けて来週中にお届けします。")
        self.assertEqual(of_kind(result, "dropped_sentence"), [])
        self.assertIn("state", [kind for kind, _ in kinds(result)])

    def test_slides_without_periods(self):
        """見出しと句点のない行（スライドの要約の行）を外した組（test_v250_heading の slides）には出さない。"""
        requests = CORPUS / "requests"
        result = yomiyasu_diff.diff((requests / "slides_heading_orig.txt").read_text(encoding="utf-8"),
                                    (requests / "slides_heading_final.txt").read_text(encoding="utf-8"))
        self.assertEqual(of_kind(result, "dropped_sentence"), [])

    def test_three_or_more_in_a_document_are_not_found(self):
        """1つの文書で3件以上になったときは、書き直しが大きいので、どれも出さない。"""
        before = ("会議は10時に始まります。会場の空調は午後に点検します。駐車場の区画は東側を使います。"
                  "受付の名簿は総務課が用意します。\n")
        after = "会議は10時に始まります。\n"
        self.assertEqual(of_kind(yomiyasu_diff.diff(before, after), "dropped_sentence"), [])
        two = "会議は10時に始まります。会場の空調は午後に点検します。駐車場の区画は東側を使います。\n"
        self.assertEqual(len(of_kind(yomiyasu_diff.diff(two, after), "dropped_sentence")), 2)

    def test_corpus_48_pairs_have_none(self):
        """推敲の48組では、消えた文の候補は0件。"""
        for before, after, name in rewrite_pairs():
            with self.subTest(pair=name):
                self.assertEqual(of_kind(yomiyasu_diff.diff(before, after), "dropped_sentence"), [])

    def test_message_and_not_counted(self):
        before, after, _ = self.FOUND[0]
        report = yomiyasu_diff.report(run(before, after))
        self.assertIn("- 消えた文（元1行目）: 内容の語（作業中、ログイン）が推敲後のどこにもありません。--fail-on には数えません。"
                      "読み手に要らない文として外したのでなければ、文を戻してください。\n  元: 作業中はログインできません。\n\n", report)
        self.assertNotIn("dropped_sentence", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["dropped_sentence"], 20)
        self.assertEqual(diff_exit_code(before, after), 0)


class BoundaryTest(unittest.TestCase):
    """20章: 境目の言い方の変化（kind boundary。--fail-on に数える）。「超える」「未満」はその値を含まず、「以上」「以下」
    「達する」は含む。"""

    # (元, 後, subkind, 元の語, 後の語)
    FOUND = (
        ("応答が2秒を超えたら警告します。", "応答が2秒以上なら警告します。", "strict_to_inclusive", "超え", "以上"),
        ("18歳未満は保護者の同意が必要です。", "18歳以下は保護者の同意が必要です。", "strict_to_inclusive", "未満", "以下"),
        ("タイムアウトに達して504になりました。", "タイムアウトを超えたものから504を返しました。", "inclusive_to_strict", "達し",
         "超え"),
        # 類例
        ("上限回数を超えた場合は退避します。", "回数が上限に達したら退避します。", "strict_to_inclusive", "超え", "達し"),
        ("対象は18歳以上の方です。", "対象は18歳を超える方です。", "inclusive_to_strict", "以上", "超え"),
        # 禁止の形の「超えてはいけない」は含む側。含まない側への言い直しは出す
        ("ファイルの大きさは10MBを超えてはいけません。", "ファイルの大きさは10MB未満にしてください。", "inclusive_to_strict",
         "超えてはいけ", "未満"),
        # 想定との比べ（接続数と想定）は数の境目
        ("同時接続数が想定を超えたらスケールアウトします。", "同時接続数が想定以上になったらスケールアウトします。",
         "strict_to_inclusive", "超え", "以上"),
        # 肯定の「超えることはあります」は含まない側
        ("処理件数が100件を超えることはあります。", "処理件数が100件以上になることがあります。", "strict_to_inclusive", "超え",
         "以上"),
    )
    NOT_FOUND = (
        ("10個以上あれば発送します。", "10個以上あるときに発送します。"),
        ("30度を超えたら休憩します。", "30度を上回ったら休憩します。"),
        # 類例: 打ち消した「超えない」（その値を含む）、文の頭や助詞のあとの「以上」「以下」、「配達し」
        ("メモリの使用量が8GBを超えないように設定します。", "メモリの使用量を8GB以下に抑えます。"),
        ("上限を超えたらエラーにします。", "上限を超えたら、以下のエラーを返します。"),
        ("以上の理由で、Aを選びました。", "この理由で、Aを選びました。"),
        ("在庫が10個を下回ったら発注します。", "在庫が少なくなったら発注し、翌日に配達します。"),
        # 禁止と不可能の形（超えてはいけない、超えてはならない、超えられない、下回ってはいけない）は、その値を含む側
        ("ファイルの大きさは10MBを超えてはいけません。", "ファイルの大きさは10MB以下にしてください。"),
        ("人数は10人を超えてはならない。", "人数は10人以下でなければならない。"),
        ("1回の送信は100件を超えられません。", "1回に送信できるのは100件以下です。"),
        ("気温が下限を下回ってはいけません。", "気温は下限以上に保ってください。"),
        # 数の境目でない「期待」「想像」「予想」「予測」との比べ
        ("期待を超える成果が出ました。", "期待以上の成果が出ました。"),
        ("想像を超える反響がありました。", "想像以上の反響がありました。"),
        ("反響は予想を超えるものでした。", "反響は予想以上のものでした。"),
        ("売上は予想を上回りました。", "売上は予想以上でした。"),
        # 同じ動詞の形を変えただけの組（境目は同じ）
        ("1回の送信は100件を超えられません。", "1回の送信が100件を超えるとエラーになります。"),
        ("上限を超えることはできません。", "上限を超えると処理を止めます。"),
        ("8GBを超えないようにします。", "8GBを超えたら止めます。"),
        ("処理件数が100件を超えることはありません。", "処理件数は100件以下です。"),
    )

    def test_found(self):
        for before, after, subkind, source, target in self.FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual([(risk["subkind"], risk["detail"]) for risk in of_kind(result, "boundary")],
                                 [(subkind, {"from": source, "to": target})])
                self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_not_found(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(of_kind(result, "boundary"), [])
        # 表の「出さない」の組は、--fail-on の数も0のまま
        for before, after in self.NOT_FOUND[:2]:
            with self.subTest(before=before, after=after):
                self.assertEqual(run(before, after)["fail_on_meaning_risk_count"], 0)

    def test_counted_and_exit_codes(self):
        self.assertIn("boundary", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["boundary"], 25)
        self.assertEqual(diff_exit_code("応答が2秒を超えたら警告します。", "応答が2秒以上なら警告します。"), 1)
        self.assertEqual(diff_exit_code("タイムアウトに達して504になりました。", "タイムアウトを超えたものから504を返しました。"), 1)
        self.assertEqual(diff_exit_code("10個以上あれば発送します。", "10個以上あるときに発送します。"), 0)
        self.assertEqual(diff_exit_code("30度を超えたら休憩します。", "30度を上回ったら休憩します。"), 0)

    def test_message_and_fail_on_line(self):
        result = run("応答が2秒を超えたら警告します。", "応答が2秒以上なら警告します。")
        report = yomiyasu_diff.report(result)
        self.assertIn("- 境目の言い方が変わった（1行目）: 超え → 以上。「超える」「未満」はその値を含まず、「以上」「以下」「達する」は"
                      "その値を含みます。境目の値ちょうどの扱いが変わっていないか確かめてください。", report)
        self.assertNotIn("数えません", yomiyasu_diff._risk_line(result["meaning_risks"][0]))
        risks = result["meaning_risks"]
        self.assertIn("・境目の言い方", yomiyasu_diff._fail_on_line(len(risks) + 1, yomiyasu_diff.fail_on_count(risks), risks))

    def test_corpus_48_pairs(self):
        """推敲の48組では3件（02 の2組と 03 の1組）。どれも境目が変わった組。"""
        found = []
        for before, after, name in rewrite_pairs():
            result = yomiyasu_diff.diff(before, after)
            found.extend((name, risk["subkind"], risk["detail"]["from"], risk["detail"]["to"])
                         for risk in of_kind(result, "boundary"))
            if name == "02_incident_report_sonnet_casual_bl.md":
                # ほかの候補は数えない候補だけなので、境目の言い方の候補で --fail-on の数が0から1になる
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        self.assertEqual(found, [("02_incident_report_sonnet_casual.md", "inclusive_to_strict", "達し", "超え"),
                                 ("02_incident_report_sonnet_casual_bl.md", "strict_to_inclusive", "超え", "以上"),
                                 ("03_pr_description_sonnet_formal.md", "strict_to_inclusive", "超え", "達し")])


class ScopeCommonTest(unittest.TestCase):
    """9章: 3.2.0 で足した kind の共通の決まり（並びの番号、--fail-on に数える kind、候補の並べ方、JSON の形、公開の関数）。"""

    PAIRS = (
        ("回答は必須ではありません。", "回答は不要です。"),
        ("お問い合わせは電話かメールで受け付けます。", "お問い合わせは電話とメールで受け付けます。"),
        ("新しい規程は全員に適用されます。", "新しい規程が適用されます。"),
        ("経費精算は月末までに提出してください。", "経費精算は月末に提出してください。"),
        ("管理者権限がある場合は、設定を変更できます。", "設定を変更できます。"),
        ("メンテナンスは22時から翌2時までです。作業中はログインできません。終了後にお知らせします。",
         "メンテナンスは22時から翌2時までです。終了後にお知らせします。"),
        ("応答が2秒を超えたら警告します。", "応答が2秒以上なら警告します。"),
    )

    def test_risk_order_and_fail_on_kinds(self):
        order = yomiyasu_diff._RISK_ORDER
        self.assertEqual([order[kind] for kind in ("limiter", "dropped_sentence", "obligation", "quantifier", "deadline",
                                                   "condition", "boundary")], [19, 20, 21, 22, 23, 24, 25])
        self.assertEqual(yomiyasu_diff.FAIL_ON_KINDS[-2:], ("limiter", "boundary"))
        for kind in ("dropped_sentence", "obligation", "quantifier", "deadline", "condition"):
            with self.subTest(kind=kind):
                self.assertNotIn(kind, yomiyasu_diff.FAIL_ON_KINDS)

    def test_shape_and_messages(self):
        """ほかの kind と同じ8つのキーで出し、数えない5つの message には「--fail-on には数えません。」を入れる。"""
        keys = {"kind", "subkind", "old_line", "new_line", "old", "new", "detail", "basis"}
        seen = set()
        for before, after in self.PAIRS:
            with self.subTest(before=before):
                result = run(before, after)
                self.assertTrue(result["meaning_risks"])
                for risk in result["meaning_risks"]:
                    self.assertEqual(set(risk), keys)
                    self.assertIsNone(risk["basis"])
                    seen.add(risk["kind"])
                    line = yomiyasu_diff._risk_line(risk)
                    counted = risk["kind"] in yomiyasu_diff.FAIL_ON_KINDS
                    self.assertEqual("--fail-on には数えません。" in line, not counted, line)
        self.assertTrue({"obligation", "choice", "quantifier", "deadline", "condition", "dropped_sentence", "boundary"} <= seen)

    def test_new_candidates_follow_the_existing_ones(self):
        """同じ行では、既存の候補（数に付いた範囲の語）の後ろに並べる。"""
        result = run("18歳未満は保護者の同意が必要です。", "18歳以下は保護者の同意が必要です。")
        self.assertEqual(kinds(result), [("number_qualifier", "changed"), ("boundary", "strict_to_inclusive")])
        self.assertEqual(result["fail_on_meaning_risk_count"], 2)

    def test_lines_in_a_longer_document(self):
        """候補は行の順に並び、行番号は元と後の文書の行。"""
        before = "## 申請\n\n申請を行う必要があります。\n\n## 受付\n\n電話かメールで受け付けます。\n"
        after = "## 申請\n\n申請をお願いします。\n\n## 受付\n\n電話とメールで受け付けます。\n"
        result = yomiyasu_diff.diff(before, after)
        self.assertEqual([(risk["kind"], risk["old_line"], risk["new_line"]) for risk in result["meaning_risks"]],
                         [("obligation", 3, 3), ("choice", 7, 7)])

    def test_public_function_matches_diff(self):
        """type_changes を渡した meaning_risks() は diff() と同じ。"""
        for before, after in self.PAIRS:
            with self.subTest(before=before):
                result = run(before, after)
                found = yomiyasu_diff.meaning_risks(before + "\n", after + "\n", type_changes=result["type_changes"])
                self.assertEqual(found, result["meaning_risks"])

    def test_twin_scripts_are_identical(self):
        self.assertEqual((ROOT / "scripts" / "yomiyasu_diff.py").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_diff.py").read_bytes())


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


class RoundTwoFixesTest(unittest.TestCase):
    """直したあとの確かめで見つけた形（3.2.0）。禁止の依頼の言い方、頼む内容が逆になった依頼の結び、依頼を表す語の副詞と
    「嬉しい」「幸甚」、書き手の望みの言い方、依頼の結びの言い方、境目の語の打ち消し、選ぶ範囲の「一方」、遠慮を打ち消した
    言い方、済んだことの報告、「一同心より」。"""

    # (元, 後, --fail-on の数, 出る候補の kind と subkind)
    CASES = (
        # 禁止の依頼（お控えください、差し控えて、も控えて、なるべく控えて）への言い換えは、問いの依頼の言い直しにしない
        ("資料をお送りいただけますか。", "資料の送付はお控えください。", 2, [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("ご利用いただけますか。", "ご利用は差し控えてください。", 2, [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("ご利用いただけますか。", "ご利用をお控えいただけますと幸いです。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("会議で撮影していただけますか。", "会議での撮影はお控えください。", 1, [("sentence_type", "question")]),
        ("撮影していただけますか。", "撮影も控えてください。", 1, [("sentence_type", "question")]),
        ("撮影していただけますか。", "撮影はなるべく控えてください。", 1, [("sentence_type", "question")]),
        ("資料をお送りいただけますか。", "資料をお送りください。", 0, []),
        # 前からの依頼の語（〜てください、ご遠慮ください）が消えた組は、依頼の結びに言い直しても、3.1.0 と同じく依頼の語が消えた
        # 候補を出す
        ("会場には直接来ないでください。", "会場へのご来場をお待ちしております。", 1, [("sentence_type", "marks")]),
        ("当日の電話でのお問い合わせはご遠慮ください。", "当日のお電話でのお問い合わせをお待ちしております。", 1,
         [("sentence_type", "marks")]),
        ("資料を社外に共有してください。", "資料を社外に共有しないよう、ご協力のほどよろしくお願いいたします。", 1,
         [("sentence_type", "marks")]),
        ("会場内での飲食はご遠慮ください。", "会場内での飲食については、ご協力のほどよろしくお願いいたします。", 1,
         [("sentence_type", "marks")]),
        ("会場内での飲食はご遠慮ください。", "会場内での飲食はご遠慮いただきますよう、ご協力のほどよろしくお願いいたします。", 1,
         [("sentence_type", "marks")]),
        # 3.2.0 で依頼を表す語にした言い方の依頼を結びに言い直した組は、依頼が残ったとみる（3.1.0 と同じく出さない）
        ("ご確認いただけましたら幸いです。", "ご確認のほど、よろしくお願いいたします。", 0, []),
        # 依頼の結びの言い方（何卒、どうぞ、お待ち申し上げております）
        ("ご確認いただけましたら幸いです。", "ご確認のほど何卒よろしくお願い申し上げます。", 0, []),
        ("ご確認いただけましたら幸いです。", "ご確認のほど、何卒よろしくお願いいたします。", 0, []),
        ("ご検討いただけますと幸いです。", "ご検討をどうぞよろしくお願いいたします。", 0, []),
        ("ご来場いただけましたら幸いです。", "ご来場をお待ち申し上げております。", 0, []),
        # 「お願いできれば嬉しい」「大変助かります」「幸甚です」も依頼を表す語。いただけ・もらえ の側も同じ
        ("レビューをお願いできれば嬉しいです。", "レビューをお願いします。", 0, []),
        ("ご確認をお願いできれば大変助かります。", "ご確認ください。", 0, []),
        ("ご確認をお願いできれば幸甚です。", "ご確認をお願いします。", 0, []),
        ("ご確認をお願いできれば大変助かります。", "確認は済んでいます。", 1, [("sentence_type", "marks")]),
        ("先方にお願いできれば、作業は早く終わります。", "先方に頼めば、作業は早く終わります。", 0, []),
        ("ご確認いただけますと大変助かります。", "ご確認ください。", 0, []),
        ("ご確認いただけると、大変助かります。", "ご確認ください。", 0, []),
        ("ご確認いただけますと幸甚です。", "ご確認ください。", 0, []),
        # 書き手の望み（楽しんでもらえると、気に入っていただけると）は依頼を表す語にしない
        ("皆さんに楽しんでもらえるとうれしいです。", "皆さんが楽しんでくれたらうれしいです。", 0, []),
        ("気に入っていただけると嬉しいです。", "気に入ってもらえたら何よりです。", 0, []),
        ("見てもらえると嬉しいです。", "見てください。", 0, []),
        # 「ご遠慮なさらず」「遠慮せず」「遠慮しないで」は禁止の依頼でない
        ("ご不明な点があれば、お知らせいただけますか。", "ご不明な点があれば、ご遠慮なさらずお知らせください。", 0, []),
        ("ご不明な点があれば、お知らせいただけますか。", "ご不明な点があれば、遠慮せずにお知らせください。", 0, []),
        ("ご不明な点があれば、お知らせいただけますか。", "ご不明な点があれば、遠慮しないでください。", 0, []),
        # 済んだことの報告（お願いしておりました、お願いしてきました）は「お願いしたい」が残ったとみない
        ("先方に資料の確認をお願いしたいです。", "先方に資料の確認をお願いしておりました。", 1, [("sentence_type", "marks")]),
        ("先方に資料の確認をお願いしたいです。", "先方に資料の確認をお願いしてきました。", 1, [("sentence_type", "marks")]),
        # 選ぶ範囲: 接続の「その一方」と「一方的」は除かず、「片方を選ぶ」「一方を選ぶ」は除く
        ("お問い合わせは電話かメールで受け付けますが、窓口では受け付けません。",
         "お問い合わせは電話とメールで受け付けますが、その一方で窓口では受け付けません。", 1, [("choice", "one_to_all")]),
        ("申請は電話かメールで受け付けますが、本人の一方的な取り消しはできません。",
         "申請は電話とメールで受け付けますが、本人の一方的な取り消しはできません。", 1, [("choice", "one_to_all")]),
        ("申請は電話かメールで受け付けます。", "申請は電話とメールで受け付け、片方を選びます。", 0, []),
        ("申請は電話かメールで受け付けます。", "申請は電話とメール、一方を選んで受け付けます。", 0, []),
    )

    def test_cases(self):
        for before, after, count, expected in self.CASES:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(kinds(result), expected)
                self.assertEqual(result["fail_on_meaning_risk_count"], count)

    # 境目の語の打ち消し（その値を含む側）: (元, 後)。どれも境目は同じなので boundary を出さない
    BOUNDARY_SAME = (
        ("処理件数が100件を超えることはあり得ません。", "処理件数は100件以下です。"),
        ("処理件数が100件を超えることはあり得ない。", "処理件数は100件以下だ。"),
        ("処理件数が100件を超えることはなさそうです。", "処理件数は100件以下になりそうです。"),
        ("上限を超えることはできかねます。", "上限以下でお申し込みください。"),
        ("使用量が上限を超えることのないよう、注意してください。", "使用量が上限以下になるよう、注意してください。"),
        ("使用量が上限を超えることがないよう、注意してください。", "使用量が上限以下になるよう、注意してください。"),
        ("使用量が上限を超えることもありません。", "使用量は上限以下です。"),
        ("料金が1万円を超えることはございません。", "料金は1万円以下です。"),
        ("料金が1万円を超えることは決してありません。", "料金は1万円以下です。"),
        ("料金が1万円を超えることはまずないでしょう。", "料金は1万円以下でしょう。"),
        ("料金が1万円を超えることは許されません。", "料金は1万円以下にしてください。"),
        ("上限を超えることなく運用します。", "上限以下で運用します。"),
    )
    # 肯定の形（含まない側のまま）: 境目が変わるので出す
    BOUNDARY_CHANGED = (
        ("処理件数が100件を超えることがあります。", "処理件数は100件以上になることがあります。"),
        ("処理件数が100件を超えることもある。", "処理件数は100件以上になることもある。"),
        ("処理件数が100件を超えることはあり得る。", "処理件数は100件以上になり得る。"),
    )

    def test_boundary_negations(self):
        for before, after in self.BOUNDARY_SAME:
            with self.subTest(before=before):
                self.assertEqual(of_kind(run(before, after), "boundary"), [])
        for before, after in self.BOUNDARY_CHANGED:
            with self.subTest(before=before):
                self.assertEqual([risk["subkind"] for risk in of_kind(run(before, after), "boundary")], ["strict_to_inclusive"])

    def test_kokoro_yori_after_a_word_boundary(self):
        """「一同心より」「本日心より」「真心より」「衷心より」は強める語に数え、「安心より」「中心より」は数えない。"""
        for before, after, counted in (("スタッフ一同心よりお待ちしております。", "スタッフ一同お待ちしております。", True),
                                       ("社員一同心より感謝申し上げます。", "社員一同感謝申し上げます。", True),
                                       ("本日心よりお詫び申し上げます。", "本日お詫び申し上げます。", True),
                                       ("真心よりお祝い申し上げます。", "お祝い申し上げます。", True),
                                       ("衷心よりお詫び申し上げます。", "お詫び申し上げます。", True),
                                       ("安心より不安が勝ちます。", "不安が勝ちます。", False),
                                       ("中心より外側を塗ります。", "外側を塗ります。", False)):
            with self.subTest(before=before):
                self.assertEqual(run(before, after)["tone"]["counts"]["old"]["intensifier"], 1 if counted else 0)


class RoundThreeFixesTest(unittest.TestCase):
    """2回目の直しを確かめ直して見つけた形（3.2.0）。依頼の結びの決まりは、3.2.0 で依頼を表す語にした言い方が消えた組だけに使い
    （条件の「問題ないようでしたら」、目的の「漏れのないよう、」、予定の「本番を控えております」があっても使う）、前からの依頼の
    語が消えた組は 3.1.0 と同じく出す。問いの依頼の言い直しは「〜を控え、〜ください」も禁止に読む。書き手の望みの敬語の形
    （お楽しみいただける）、感想と昔の話（嬉しいものです、嬉しかった）も依頼を表す語にしない。"""

    # (元, 後, --fail-on の数, 出る候補の kind と subkind（並びは問わない）)
    CASES = (
        # 3.2.0 で依頼を表す語にした言い方を結びに言い直した組は、条件・目的の「〜ないよう」があっても依頼が消えたことにしない
        ("内容に問題ないようでしたら、ご承認いただけますと幸いです。", "内容に問題がなければ、ご承認のほどよろしくお願いいたします。", 0, []),
        ("差し支えなければ、ご確認いただけますと幸いです。", "差し支えないようでしたら、ご確認のほどよろしくお願いいたします。", 0, []),
        ("漏れのないよう、ご確認いただけますと幸いです。", "漏れなく、ご確認のほどよろしくお願いいたします。", 0, []),
        ("お忘れのないよう、ご提出いただけますと幸いです。", "忘れずにご提出のほど、よろしくお願いいたします。", 0, []),
        ("お間違えのないよう、ご注意いただけますと幸いです。", "お間違えにご注意のほどよろしくお願いいたします。", 0, []),
        # 前からの依頼の語（お越しください、ご注意ください、てください、ないでください）が消えた組は、3.1.0 と同じく出す
        ("遅れないよう、早めにお越しください。", "早めのお越しをお待ちしております。", 1, [("sentence_type", "marks")]),
        ("お忘れにならないよう、ご注意ください。", "お忘れのないよう、ご注意のほどよろしくお願いいたします。", 1, [("sentence_type", "marks")]),
        ("資料を社外に共有してください。", "資料を社外に共有することのないよう、ご協力のほどよろしくお願いいたします。", 1,
         [("sentence_type", "marks")]),
        ("資料は社外に持ち出さないでください。", "資料の社外への持ち出しについては、ご配慮のほどよろしくお願いいたします。", 1,
         [("sentence_type", "marks")]),
        # 既知の限界: 3.2.0 で依頼を表す語にした言い方の依頼を、禁止の結びに言い直した組は出さない（3.1.0 と同じ）
        ("当日はご来場いただけますと幸いです。", "当日はご来場をご遠慮のほど、よろしくお願いいたします。", 0, []),
        ("当日は会場にお越しいただけますと幸いです。", "当日は会場へのご来場をお控えのほど、よろしくお願いいたします。", 0, []),
        ("会場での撮影はお控えいただけますと幸いです。", "会場での撮影はご遠慮のほど、よろしくお願いいたします。", 0, []),
        # 予定の「控えております」、書き手の「控えます」、「やめて、」、打ち消した「禁止されていません」は禁止でない
        ("来週に本番リリースを控えておりますので、最終版の資料をご確認いただけますと幸いです。",
         "来週が本番リリースのため、最終版の資料のご確認をよろしくお願いいたします。", 0, []),
        ("詳細は控えますが、ご確認いただけますと幸いです。", "詳細は省きますが、ご確認のほどよろしくお願いいたします。", 0, []),
        ("紙の申請はやめて、オンラインでご申請いただけますと幸いです。", "紙ではなく、オンラインでのご申請をよろしくお願いいたします。", 0, []),
        # 打ち消した「禁止されていません」を「できます」にした組は、依頼の結びに言い直しても、依頼のない文と同じく許可の言い方が
        # 消えた候補を出す（許可の候補を文の種類の候補に任せない）
        ("持ち込みは禁止されていませんので、ご持参いただけますと幸いです。", "持ち込みはできますので、ご持参のほどよろしくお願いいたします。",
         1, [("modality", "permission_lost")]),
        # 問いの依頼の言い直し: 「〜が控えている」「〜を控えた今」は禁止に読まず、「〜を控え、〜ください」は禁止に読む
        ("来週は監査があるので、資料をご準備いただけますか。", "来週に監査が控えているので、資料を準備してください。", 0, []),
        ("本番前に資料を確認していただけますか。", "本番を控えた今、資料を確認してください。", 0, []),
        ("当日は車でお越しいただけますか。", "当日は車でのお越しを控え、電車をご利用ください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("会場で撮影していただけますか。", "会場での撮影は控え、メモを取ってください。", 1, [("sentence_type", "question")]),
        ("ご不明な点があれば、ご連絡いただけますか。", "ご不明な点があれば、どうぞご遠慮なさらないでください。", 0, []),
        # 書き手の望みは敬語の形も依頼を表す語にしない。「条件を満足していただけますと」は依頼
        ("新しい機能にご満足いただけると嬉しいです。", "新しい機能に満足してもらえると嬉しいです。", 0, []),
        ("皆様にお喜びいただけましたら幸いです。", "皆様に喜んでいただけたら幸いです。", 0, []),
        ("気に入っていただけると嬉しいです。", "お気に召していただけると嬉しいです。", 0, []),
        ("楽しんでいただけると幸いです。", "お楽しみいただければ幸いです。", 0, []),
        ("提出物は以下の条件を満足していただけますと幸いです。", "提出物が以下の条件を満たすかを確認します。", 1,
         [("sentence_type", "marks")]),
        # 感想と昔の話
        ("人に褒めてもらえると、とても嬉しいものです。", "人に褒められると、とても嬉しいものです。", 0, []),
        ("子どもの頃、褒めてもらえると、とても嬉しかった。", "子どもの頃は、褒められるのがとても嬉しかった。", 0, []),
        # 「お願いしてみたく」は済んだことの報告でない
        ("まずお願いしたいのは、資料の確認です。", "まず資料の確認をお願いしてみたく、ご連絡しました。", 0, []),
        # 「その片方」は選ぶ範囲を残した言い方
        ("申請は電話かメールで受け付けます。", "申請は電話とメールの2つの方法があり、その片方で受け付けます。", 1, [("number", "added")]),
    )

    def test_cases(self):
        for before, after, count, expected in self.CASES:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(sorted(kinds(result), key=str), sorted(expected, key=str))
                self.assertEqual(result["fail_on_meaning_risk_count"], count)

    def test_wish_in_honorific_form(self):
        """「お楽しみいただけましたら幸いです → 楽しんでいただけたら嬉しいです」に文の種類の候補を出さない。"""
        result = run("本日のイベントをお楽しみいただけましたら幸いです。", "本日のイベントを楽しんでいただけたら嬉しいです。")
        self.assertNotIn("sentence_type", [risk["kind"] for risk in result["meaning_risks"]])
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    # 境目の語: 境目の語のすぐあとに打ち消しがある文（未満にならない、以上にならない）の組は比べない。二重の打ち消しは打ち消しでない
    BOUNDARY_SAME = (
        # 既知の限界: 境目が変わった組も出さない
        ("費用が10万円を超えないよう、調整してください。", "費用が10万円以上にならないよう、調整してください。"),
        ("費用が10万円を超えることのないよう、調整してください。", "費用が10万円以上にならないよう、調整してください。"),
        ("在庫が10個を下回ることのないよう、補充してください。", "在庫が10個未満にならないよう、補充してください。"),
        ("在庫が10個を下回らないよう、補充してください。", "在庫が10個未満にならないよう、補充してください。"),
    )
    BOUNDARY_CHANGED = (
        ("処理件数が100件を超えることがないわけではありません。", "処理件数は100件以上になることもあります。", "strict_to_inclusive"),
    )

    def test_boundary_negated_words(self):
        for before, after in self.BOUNDARY_SAME:
            with self.subTest(before=before):
                self.assertEqual(of_kind(run(before, after), "boundary"), [])
        for before, after, subkind in self.BOUNDARY_CHANGED:
            with self.subTest(before=before):
                self.assertEqual([risk["subkind"] for risk in of_kind(run(before, after), "boundary")], [subkind])


class RoundFourFixesTest(unittest.TestCase):
    """3回目の直しを確かめ直して見つけた形（3.2.0）。依頼の結びは 3.2.0 で依頼を表す語にした言い方が消えた組だけに使うので、
    一覧にない禁止の言い方（ご理解とご協力のほど何卒）でも、前からの依頼の語が消えた組は出し、「ご留意いただけますと幸いです」の
    結びへの言い直しは出さない。境目の語のすぐあとに打ち消しがある文（以上にしなければなりません、以上でないと、以上に増えない）
    の組は比べない。"""

    # (元, 後, --fail-on の数, 出る候補の kind と subkind（並びは問わない）)
    CASES = (
        ("会場内では撮影しないよう、ご理解とご協力をお願いいたします。",
         "会場内での撮影について、ご理解とご協力のほど何卒よろしくお願いいたします。", 1, [("sentence_type", "marks")]),
        ("敷地内に駐車してください。", "敷地内には駐車なさらないよう、ご理解ご協力のほど、どうぞよろしくお願いいたします。", 1,
         [("sentence_type", "marks")]),
        ("撮影はご遠慮賜りますようお願い申し上げます。", "撮影については、ご理解のほど何卒よろしくお願い申し上げます。", 1,
         [("sentence_type", "marks")]),
        ("以下の点にご留意いただけますと幸いです。", "以下の点のご確認をよろしくお願いいたします。", 0, []),
        ("体調にお気をつけいただけますと幸いです。", "ご自愛のほどよろしくお願いいたします。", 0, []),
        ("ファイルの削除にご注意ください。", "ファイルを削除し忘れないよう、ご注意のほどよろしくお願いいたします。", 1,
         [("sentence_type", "marks")]),
        ("ご確認ください。", "ご確認のほど、よろしくお願いいたします。", 1, [("sentence_type", "marks")]),
        # 問いの依頼の言い直し: 「差し控えますよう」「〜ないようご注意ください」「〜ないようお願いします」は禁止に読み、単独の
        # 「ご留意ください」は禁止に読まない
        ("会場で撮影していただけますか。", "会場での撮影は差し控えますようお願いいたします。", 1, [("sentence_type", "question")]),
        ("資料を共有していただけますか。", "資料を共有しないようご注意ください。", 1, [("sentence_type", "question")]),
        ("期日までに提出していただけますか。", "期日に遅れないようお願いします。", 1, [("sentence_type", "question")]),
        ("期限を確認していただけますか。", "期限にご留意ください。", 0, []),
        # 「お願いできれば」は、ほかの人に頼む話と昔の話を依頼の印にしない
        ("先方にお願いできれば、とても助かります。", "先方に頼めれば、とても助かります。", 0, []),
        ("先方にお願いできればと考えていたが、断られた。", "先方に頼もうと考えていたが、断られた。", 0, []),
        ("ご確認をお願いできればと存じます。", "ご確認ください。", 0, []),
    )

    def test_cases(self):
        for before, after, count, expected in self.CASES:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(sorted(kinds(result), key=str), sorted(expected, key=str))
                self.assertEqual(result["fail_on_meaning_risk_count"], count)

    BOUNDARY_NOT_COMPARED = (
        ("パスワードは8文字以上にしなければなりません。", "パスワードは8文字以上にする必要があります。"),
        ("ファイルは10MB以下にしなければなりません。", "ファイルは10MB以下にしてください。"),
        ("パスワードは8文字以上にしないと登録できません。", "パスワードは8文字以上でないと登録できません。"),
        ("使用量が100GB以上にならないよう、監視してください。", "使用量が100GB以上に増えないよう、監視してください。"),
        ("在庫が10個を下回ることもありません。", "在庫が10個未満になることもありません。"),
    )

    def test_boundary_with_negation_after_the_word(self):
        for before, after in self.BOUNDARY_NOT_COMPARED:
            with self.subTest(before=before):
                result = run(before, after)
                self.assertEqual(of_kind(result, "boundary"), [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)


class RoundFiveFixesTest(unittest.TestCase):
    """4回目の直しを確かめ直して見つけた形（3.2.0）。3.2.0 で依頼を表す語にした言い方の依頼と、依頼を続けている文（お願い、
    お待ち、〜いただきますよう、〜のほど・の程）のあいだの言い直しは、どちらの向きでも候補にしない（3.1.0 と同じ）。問いの依頼の
    言い直しは、禁止の語の有り無しが両方の文でそろうときだけ外し、「控えたうえで」「ご遠慮なさって」「お控えの上」も禁止に読む。
    境目の語は、あとの平仮名の続きに打ち消しがある文だけを比べず、漢字の語のあとの述語の打ち消しのある文は比べる。"""

    # (元, 後, --fail-on の数, 出る候補の kind と subkind（並びは問わない）)
    CASES = (
        ("資料をご確認いただけますと幸いです。", "資料のご確認よろしくお願いいたします。", 0, []),
        ("ご参加いただけますと幸いです。", "皆様のご参加を心よりお待ちしております。", 0, []),
        ("ご連絡いただけますと幸いです。", "ご連絡お待ちしております。", 0, []),
        ("資料をご確認いただけますと幸いです。", "資料をご確認いただきますよう、よろしくお願いいたします。", 0, []),
        ("ご検討いただけますと幸いです。", "ご検討賜りますよう、よろしくお願い申し上げます。", 0, []),
        ("ご確認いただけますと幸いです。", "ご確認の程よろしくお願いいたします。", 0, []),
        # 逆向き（依頼を続けている文を、新しく依頼を表す語にした言い方の依頼にした組）も出さない
        ("ご確認のほど、よろしくお願いいたします。", "ご確認いただけますと幸いです。", 0, []),
        ("ご返信をお待ちしております。", "ご返信いただけますと幸いです。", 0, []),
        # 依頼でない文を新しい言い方の依頼にした組は、依頼を表す語が足された候補として出す
        ("資料を添付します。", "資料をご確認いただけますと幸いです。", 1, [("sentence_type", "marks")]),
        # 問いの依頼を禁止の依頼に変えた組と、禁止の問いの依頼をふつうの依頼に変えた組は、言い直しとして外さない
        ("車でお越しいただけますか。", "車でのお越しは控えたうえで、電車をご利用ください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("車でお越しいただけますか。", "車でのお越しはご遠慮なさって、電車をご利用ください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("当日はお車でお越しいただけますか。", "当日はお車でのご来場はお控えの上、公共交通機関をご利用ください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("資料を送らないでいただけますか。", "資料を送ってください。", 2, [("sentence_type", "question"), ("sentence_type", "marks")]),
        # 両方の文が同じ「控え」の依頼の組は言い直し（書き留める意味の「控えて」どうし）
        ("受付番号をお控えいただけますか。", "受付番号を控えてください。", 0, []),
    )

    def test_cases(self):
        for before, after, count, expected in self.CASES:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(sorted(kinds(result), key=str), sorted(expected, key=str))
                self.assertEqual(result["fail_on_meaning_risk_count"], count)

    # 境目の語のあとが漢字の語の述語の打ち消しなら比べる: (元, 後, subkind)
    BOUNDARY_COMPARED = (
        ("10件を超えると表示されません。", "10件以上になると表示されません。", "strict_to_inclusive"),
        ("100MBを超えるとアップロードできません。", "100MB以上ではアップロードできません。", "strict_to_inclusive"),
        ("20歳未満では購入できません。", "20歳以下では購入できません。", "strict_to_inclusive"),
    )

    def test_boundary_with_predicate_negation(self):
        for before, after, subkind in self.BOUNDARY_COMPARED:
            with self.subTest(before=before):
                self.assertEqual([risk["subkind"] for risk in of_kind(run(before, after), "boundary")], [subkind])


class RoundSixFixesTest(unittest.TestCase):
    """5回目の直しを確かめ直して見つけた形（3.2.0）。新しい言い方の依頼だけで依頼・決まりの語の有り無しが変わった範囲では、
    許可の候補を文の種類の候補に任せない（3.1.0 と同じく許可の変化を出す）。予定の意味の「〜を控えた皆さん」は禁止に読まない。
    境目の語の「未満に減らない」「以上に集まらない」は比べない。依頼を続けている文の手がかりは、済んだことの報告と名詞を外す。"""

    # (元, 後, --fail-on の数, 出る候補の kind と subkind（並びは問わない）)
    CASES = (
        ("メールでも構いませんので、ご連絡いただけますと幸いです。", "ご連絡お待ちしております。", 1, [("modality", "permission_lost")]),
        ("ご確認いただけますと幸いです。", "ご確認は後日でも構いませんので、ご連絡お待ちしております。", 1,
         [("modality", "permission_added"), ("claim", "causal")]),
        # 予定の意味の「控えた」が両方の文にある組で、依頼を禁止に変えた書き換えは出す
        ("発表を控えた皆さん、スライドを事前に共有していただけますか。", "発表を控えた皆さん、スライドの事前の共有はご遠慮ください。",
         1, [("sentence_type", "question")]),
        ("発表を控えた皆さん、スライドを事前に共有していただけますか。", "スライドを事前に共有してください。", 0, []),
        # 済んだことの報告と名詞は、依頼を続けている文の手がかりにしない
        ("先日お願いいたしました資料を添付します。", "先日お願いいたしました資料をご確認いただけますと幸いです。", 1,
         [("sentence_type", "marks")]),
        ("どの程度の工数がかかるか、お知らせいただけますと幸いです。", "どの程度の工数がかかるかを調べます。", 1,
         [("sentence_type", "marks")]),
    )

    def test_cases(self):
        for before, after, count, expected in self.CASES:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(sorted(kinds(result), key=str), sorted(expected, key=str))
                self.assertEqual(result["fail_on_meaning_risk_count"], count)

    BOUNDARY_NOT_COMPARED = (
        ("在庫が10個を下回らないよう、発注してください。", "在庫が10個未満に減らないよう、発注してください。"),
        ("室温が10度を下回らないよう、暖房を入れてください。", "室温が10度未満に低下しないよう、暖房を入れてください。"),
        ("応募が定員に満たない講座は、開講しません。", "応募が定員以上に集まらない講座は、開講しません。"),
    )

    def test_boundary_with_kanji_verb_negation(self):
        for before, after in self.BOUNDARY_NOT_COMPARED:
            with self.subTest(after=after):
                self.assertEqual(of_kind(run(before, after), "boundary"), [])


class RoundSevenFixesTest(unittest.TestCase):
    """6回目の直しを確かめ直して見つけた形（3.2.0）。問いの依頼の言い直しで、予定の意味の「控えた」（控えた今、控えた皆さん）の
    ほかは禁止に読む（控えた状態で、控えたい方）。依頼を続けている文の手がかりに「いただければと存じます」「賜りたく」を足し、
    「お待ちしていただければ」は済んだことの報告に数えない。"""

    # (元, 後, --fail-on の数, 出る候補の kind と subkind（並びは問わない）)
    CASES = (
        ("健康診断の当日は、朝食をとってからお越しいただけますか。", "健康診断の当日は、朝食を控えた状態でお越しください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("健康診断の当日は、朝食を控えた状態でお越しいただけますか。", "健康診断の当日は、朝食をとってからお越しください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("当日は、朝食を控えてお越しいただけますでしょうか。", "当日は、朝食を控えた状態でお越しください。", 0, []),
        ("撮影したい方は、事前にお申し出いただけますか。", "撮影を控えたい方は、事前にお申し出ください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("本番前に資料を確認していただけますか。", "本番を控えた今、資料を確認してください。", 0, []),
        # 両方の文に同じ字の並びである禁止の語（受験を控えた）は、頼む内容の変化に数えない
        ("受験を控えたお子さまの保護者の方は、説明会にご参加いただけますか。",
         "受験を控えたお子さまの保護者の方は、説明会へのご参加はご遠慮ください。", 2,
         [("sentence_type", "question"), ("sentence_type", "marks")]),
        ("ご確認いただけますと幸いです。", "ご確認いただければと存じます。", 0, []),
        ("先日お願いいたしました件につきまして、ご確認いただけますと幸いです。",
         "先日お願いいたしました件につきまして、ご確認いただければと存じます。", 0, []),
        ("このほど新しい窓口を設けましたので、ご利用いただけますと幸いです。",
         "このほど新しい窓口を設けましたので、ご利用を賜りたく存じます。", 0, []),
        ("受付で番号札をお取りいただけますと幸いです。", "受付で番号札をお取りのうえ、お待ちしていただければと存じます。", 0, []),
    )

    def test_cases(self):
        for before, after, count, expected in self.CASES:
            with self.subTest(before=before, after=after):
                result = run(before, after)
                self.assertEqual(sorted(kinds(result), key=str), sorted(expected, key=str))
                self.assertEqual(result["fail_on_meaning_risk_count"], count)


if __name__ == "__main__":
    unittest.main()
