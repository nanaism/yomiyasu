#!/usr/bin/env python3
"""v2.1.1: diff の、数に付いた概数と範囲の印の増減（kind number_qualifier）の試験。

「約120人」を「120人」に直しても、意味が変わる恐れが0件で、全文差分にしか出なかった不具合を防ぐ。同じ数（値と単位が同じ）の
前後の概数の印（約、およそ、ほど、程度、前後、くらい、ごろ など）、下限の印（以上、以降、超、を超える）、上限の印（以下、
以内、以前、未満、を下回る）が、組の文で消えたり増えたりしたら出し、--fail-on=meaning-risk に数える。同じ家族の中の言い換え
（約 → ほど、以下 → 以内）、表記だけの違い（一万円 → 1万円、1,000 → 1000、全角の数字 → 半角）、数に付かない語（約束、程度の差、
前後関係、文末の「以上です」、「以下のとおり」「以上の3点」）では出さない。以上と超、以下と未満の入れ替え（その数を含むか）と、
下限と上限の入れ替えは出す。動詞の言い方（を超える）と以上の入れ替えは出さない。
例の文は、このファイルで作った合成の文。
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


KIND = "number_qualifier"


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


def found(result):
    return [(risk["subkind"], risk["detail"]["from"], risk["detail"]["to"]) for risk in result["meaning_risks"]
            if risk["kind"] == KIND]


# 出すべき例: (元, 後, (subkind, from, to))
SHOULD_DETECT = [
    # 依頼の組と、その逆
    ("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人です。", ("lost", ["approx"], [])),
    ("影響を受けた利用者は120人です。", "影響を受けた利用者は約120人です。", ("added", [], ["approx"])),
    # 数の前の概数の印
    ("およそ120人が参加した。", "120人が参加した。", ("lost", ["approx"], [])),
    ("参加者は概ね50人だった。", "参加者は50人だった。", ("lost", ["approx"], [])),
    ("達成率はほぼ90%です。", "達成率は90%です。", ("lost", ["approx"], [])),
    ("合計約120人です。", "合計120人です。", ("lost", ["approx"], [])),
    # 数のあとの概数の印（単位、万、「間」、片仮名の単位のあと）
    ("作業は3日ほどかかる。", "作業は3日かかる。", ("lost", ["approx"], [])),
    ("費用は5万円程度です。", "費用は5万円です。", ("lost", ["approx"], [])),
    ("会議は10時ごろに始まる。", "会議は10時に始まる。", ("lost", ["approx"], [])),
    ("会議は10時に始まる。", "会議は10時頃に始まる。", ("added", [], ["approx"])),
    ("移行は2週間前後で終わる。", "移行は2週間で終わる。", ("lost", ["approx"], [])),
    ("1時間弱で終わる。", "1時間で終わる。", ("lost", ["approx"], [])),
    ("100人近くが集まった。", "100人が集まった。", ("lost", ["approx"], [])),
    ("1時間足らずで終わった。", "1時間で終わった。", ("lost", ["approx"], [])),
    ("3年あまり続いた。", "3年続いた。", ("lost", ["approx"], [])),
    ("3日間ほど休む。", "3日間休む。", ("lost", ["approx"], [])),
    ("登録は30件くらいです。", "登録は30件です。", ("lost", ["approx"], [])),
    # 範囲は1つにまとめて1件
    ("作業は3〜5日程度かかる。", "作業は3〜5日かかる。", ("lost", ["approx"], [])),
    # 下限と上限
    ("参加者は100人以上です。", "参加者は100人です。", ("lost", ["lower_in"], [])),
    ("120万人以上が利用する。", "120万人が利用する。", ("lost", ["lower_in"], [])),
    ("5メートル以上離れる。", "5メートル離れる。", ("lost", ["lower_in"], [])),
    ("2020年以降に導入した。", "2020年に導入した。", ("lost", ["lower_in"], [])),
    ("申請は3日以内に処理する。", "申請は3日で処理する。", ("lost", ["upper_in"], [])),
    ("ファイルは10MB未満にする。", "ファイルは10MBにする。", ("lost", ["upper_ex"], [])),
    ("応募は100件を超えた。", "応募は100件だった。", ("lost", ["lower_verb"], [])),
    ("参加者は100人です。", "参加者は100人超です。", ("added", [], ["lower_ex"])),
    # 含むかの入れ替え、下限と上限の入れ替え、概数から範囲へ
    ("参加者は100人以上です。", "参加者は100人超です。", ("changed", ["lower_in"], ["lower_ex"])),
    ("参加者は100人以下です。", "参加者は100人未満です。", ("changed", ["upper_in"], ["upper_ex"])),
    ("参加者は100人以上です。", "参加者は100人以下です。", ("changed", ["lower_in"], ["upper_in"])),
    ("参加者は約100人です。", "参加者は100人以上です。", ("changed", ["approx"], ["lower_in"])),
    # 同じ文の、ほかの数の印は残っている
    ("約3人と約5人が来た。", "3人と約5人が来た。", ("lost", ["approx"], [])),
]

# 出してはいけない例: (元, 後)
SHOULD_NOT_DETECT = [
    # 印も数も変わらない
    ("影響を受けた利用者は約120人です。", "影響を受けた利用者は約120人でした。"),
    ("参加者は100人以上です。", "参加者は、100人以上です。"),
    # 表記だけの違い
    ("費用は一万円です。", "費用は1万円です。"),
    ("費用は約一万円です。", "費用は約1万円です。"),
    ("費用は1,000円です。", "費用は1000円です。"),
    ("費用は約１２０円です。", "費用は約120円です。"),
    ("会議は十時ごろに始まる。", "会議は10時ごろに始まる。"),
    # 同じ家族の中の言い換え
    ("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人ほどです。"),
    ("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人前後です。"),
    ("影響を受けた利用者はおよそ120人です。", "影響を受けた利用者は120人程度です。"),
    ("会議は10時ごろに始まる。", "会議は10時頃に始まる。"),
    ("参加者は100人以下です。", "参加者は100人以内です。"),
    ("作業は約3〜5日かかる。", "作業は3〜5日程度かかる。"),
    ("作業は3日から5日ほどかかる。", "作業は3〜5日ほどかかる。"),
    ("3人と約3人。", "約3人と3人。"),
    # 相手の側の、同じ数の隣の印に近い語と、文の見積もりの語・範囲の語
    ("参加者は100人以上です。", "参加者は少なくとも100人です。"),
    ("参加者は最大100人です。", "参加者は100人以下です。"),
    ("参加者は100人以内です。", "参加者は100人までです。"),
    ("最大10件まで送れる。", "10件まで送れる。"),
    ("2020年以降に導入した。", "2020年から導入した。"),
    ("2020年以降に導入した。", "2020年より導入した。"),
    ("約120人が参加した。", "120人が参加したと見られる。"),
    ("推定120人が参加した。", "120人が参加したと推定される。"),
    ("ゲートウェイのタイムアウトは30秒で、接続待ちがこれを超えたため504を返しました。",
     "接続待ちがゲートウェイのタイムアウトの30秒を超えたため、504を返しました。"),
    # 動詞の言い方と以上の入れ替え（含むかは比べない）
    ("参加者は100人を超える。", "参加者は100人以上だ。"),
    ("処理が2秒を超え、待ちが積み上がった。", "処理が2秒以上かかり、待ちが積み上がった。"),
    ("10MBを超えない範囲で送る。", "10MB以下で送る。"),
    # 数に付かない語
    ("約束の3日後に会う。", "3日後に会う。"),
    ("契約3件を結んだ。", "3件を結んだ。"),
    ("予約3件を確認した。", "3件を確認した。"),
    ("程度の差はあるが3人が来た。", "3人が来た。"),
    ("前後関係を3点確認した。", "3点を確認した。"),
    ("10分前後して到着した。", "10分して到着した。"),
    ("確認事項は次の3点です。以上です。", "確認事項は次の3点です。"),
    ("以下のとおり3点を確認する。", "3点を確認する。"),
    ("以上の3点を確認する。", "3点を確認する。"),
    ("3時間超過した。", "3時間かかった。"),
    ("効果は3倍強化された。", "効果は3倍になった。"),
    ("震度5弱の揺れを観測した。", "震度5弱を観測した。"),
    ("上限は100件です。", "上限は100件以下です。"),
]


class DetectTest(unittest.TestCase):
    def test_should_detect(self):
        for before, after, expected in SHOULD_DETECT:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    self.assertEqual(found(run(before, after, doc_type)), [expected])

    def test_should_not_detect(self):
        for before, after in SHOULD_NOT_DETECT:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    self.assertEqual(found(run(before, after, doc_type)), [])

    def test_changed_value_is_left_to_the_number_kind(self):
        """値が変わった数（約120人 → 130人）は数値の候補が扱い、印の候補を重ねない。"""
        result = run("影響を受けた利用者は約120人です。", "影響を受けた利用者は130人です。")
        self.assertEqual(found(result), [])
        self.assertIn(("number", "replaced"), [(r["kind"], r["subkind"]) for r in result["meaning_risks"]])

    def test_detail_and_line(self):
        result = run("前置きの文です。\n\n影響を受けた利用者は約120人です。", "前置きの文です。\n\n影響を受けた利用者は120人です。")
        risks = [r for r in result["meaning_risks"] if r["kind"] == KIND]
        self.assertEqual(len(risks), 1)
        risk = risks[0]
        self.assertEqual((risk["old_line"], risk["new_line"]), (3, 3))
        self.assertEqual(risk["old"], "影響を受けた利用者は約120人です。")
        self.assertEqual(risk["new"], "影響を受けた利用者は120人です。")
        self.assertEqual(risk["detail"], {"old_number": "120人", "new_number": "120人", "from": ["approx"], "to": [],
                                          "old_markers": ["約"], "new_markers": []})
        self.assertIsNone(risk["basis"])
        self.assertEqual(result["status"], "has_candidates")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_human_lines(self):
        rows = [("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人です。",
                 "数に付いた概数・範囲の印が変わった（1行目）: 120人（概数: 約） → 120人（印なし）。原文は、数に概数か範囲の印を"),
                ("影響を受けた利用者は120人です。", "影響を受けた利用者は約120人です。",
                 "120人（印なし） → 120人（概数: 約）。原文は、数に概数や範囲の印を付けていません。"),
                ("参加者は100人以上です。", "参加者は100人超です。",
                 "100人（下限（その数を含む）: 以上） → 100人（下限（その数を含まない）: 超）。原文と印の種類が違います")]
        for before, after, text in rows:
            with self.subTest(before=before, after=after):
                self.assertIn(text, yomiyasu_diff.report(run(before, after)))

    def test_public_function_includes_the_kind(self):
        """meaning_risks() も、type_changes の有無によらず、数値の候補と同じく印の候補を含める。"""
        before, after = "影響を受けた利用者は約120人です。\n", "影響を受けた利用者は120人です。\n"
        result = yomiyasu_diff.diff(before, after)
        self.assertEqual(yomiyasu_diff.meaning_risks(before, after, type_changes=result["type_changes"]),
                         result["meaning_risks"])
        self.assertEqual([r["kind"] for r in yomiyasu_diff.meaning_risks(before, after)], [KIND])


class CliTest(unittest.TestCase):
    def test_diff_exit_codes(self):
        rows = [("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人です。", 1),
                ("影響を受けた利用者は120人です。", "影響を受けた利用者は約120人です。", 1),
                ("参加者は100人以上です。", "参加者は100人です。", 1),
                ("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人ほどです。", 0),
                ("費用は1,000円です。", "費用は1000円です。", 0),
                ("約束の3日後に会う。", "3日後に会う。", 0)]
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old.md", Path(folder) / "new.md"
            for before, after, code in rows:
                old.write_text(before + "\n", encoding="utf-8")
                new.write_text(after + "\n", encoding="utf-8")
                for flags in ([], ["--doc-type", "formal"]):
                    with self.subTest(before=before, after=after, flags=flags):
                        process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/yomiyasu_diff.py"), "--fail-on",
                                                  "meaning-risk"] + flags + [str(old), str(new)], capture_output=True, text=True,
                                                 encoding="utf-8")
                        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                        if code:
                            self.assertIn("終了コード1: --fail-on=meaning-risk の条件に当たりました（意味が変わる恐れ 1件）。",
                                          process.stdout)

    def test_check_run_exit_codes(self):
        rows = [("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人です。", 1),
                ("影響を受けた利用者は120人です。", "影響を受けた利用者は約120人です。", 1),
                ("影響を受けた利用者は約120人です。", "影響を受けた利用者は120人ほどです。", 0)]
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old.md", Path(folder) / "new.md"
            for before, after, code in rows:
                old.write_text(before + "\n", encoding="utf-8")
                new.write_text(after + "\n", encoding="utf-8")
                with self.subTest(before=before, after=after):
                    process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/yomiyasu_check.py"), "run", "--source",
                                              str(old), "--final", str(new), "--fail-on", "meaning-risk", "--no-record"],
                                             capture_output=True, text=True, encoding="utf-8", cwd=folder)
                    self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                    if code:
                        self.assertIn("meaning_risk=1", process.stdout)


class ContractsTest(unittest.TestCase):
    def test_kinds_and_fail_on(self):
        """新しい kind は数える側の最後に足し、既存の kind の並びはそのまま残す。"""
        self.assertEqual(yomiyasu_diff.FAIL_ON_KINDS[:11], ("number", "negation", "swap", "sentence_type", "citation",
                                                           "certainty", "state", "promise", "modality", "choice",
                                                           "causality"))
        self.assertEqual(yomiyasu_diff.FAIL_ON_KINDS[-1], KIND)
        self.assertLess(yomiyasu_diff._RISK_ORDER["causality"], yomiyasu_diff._RISK_ORDER[KIND])

    def test_existing_number_kind_is_unchanged(self):
        """数値の候補（kind number）の形は変えない（印の候補は別の kind）。"""
        result = run("移行は3日で終える。", "移行は30日で終える。")
        risks = [(r["kind"], r["subkind"], r["detail"]) for r in result["meaning_risks"]]
        self.assertEqual(risks, [("number", "replaced", {"removed": ["3日"], "added": ["30日"]})])

    def test_help_names_the_markers(self):
        helps = {action.dest: action.help for action in yomiyasu_diff._build_parser()._actions}
        self.assertIn("約120人 → 120人、100人以上 → 100人", helps["fail_on"])

    def test_twin_scripts_are_identical(self):
        self.assertEqual((ROOT / "scripts" / "yomiyasu_diff.py").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_diff.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
