#!/usr/bin/env python3
"""v2.0.0（diff の詰めの直し）: 数値の判定の後戻りを直す（v200-development/step-c-detectors/review-regress.md の R1〜R4、
review-fp.md の F10）。

- R1: 組の文のあとに続く、組にならない文の数値は、組の文の数値と「表記の違い」として打ち消さない。続く文に同じ値
  （数と単位が同じ）があれば、文を分けた・合わせた推敲として数えない。それ以外は文書全体の比べに回す。
- R3: 数値の候補は、値の書かれている文と行を示す。
- R2: 単位なしの数と単位つきの数を「表記の違い」とみなすのは、単位なしの側が範囲（〜、から、-）、日付（-、/）、時刻（:）
  の部品のときと、数と単位の間に空白があるとき（3 日 → 3日）だけ。範囲・日付・時刻は、まとまりの中の単位なしの数が
  すべて相手の側にあるときだけ（12:25 と 25分 は打ち消さない）。
- R2b: 資料との照合（ground）と「参考: 資料にあって最終稿にない数値」も、R2 と同じ条件で「ある」とみなす。
- R4: 数量を主張しない「一つ」（直後が「の」「ずつ」、直前が「もう」）は、元にない数値・消えた数値として単独では出さない。
  同じ単位の数と入れ替わったとき（二つ → 一つ、一つの → 三つの）は number/replaced。
- F10: 漢数字の助数詞と算用数字の単位に「条」「号」「階」を足す。漢数字の助数詞に「分」を足し、「十分」を数にしないのは
  直前が漢数字でないときだけにする（三十分 → 30分 は候補なし）。万を含む数の換算は限界のまま。
文はすべてこのファイルで作った合成の文（R1〜R3 の入力は review-regress.md の再現の入力と同じ文）。
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402


def result_of(before, after):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after)


def numbers(result):
    return [risk for risk in result["meaning_risks"] if risk["kind"] == "number"]


def shape(result):
    """数値の候補を (subkind, 元の行, 後の行, 消えた値, 増えた値) にする。"""
    return [(risk["subkind"], risk["old_line"], risk["new_line"], risk["detail"].get("removed", []),
             risk["detail"].get("added", [])) for risk in numbers(result)]


def report_lines(result):
    return yomiyasu_diff.report(result).split("\n")


class CrossSentenceTest(unittest.TestCase):
    """R1: 組の文に続く文の数値を、組の文の数値と打ち消し合わせない（基準 38d6556 と同じ候補が出る）。"""

    def test_version_number_and_new_days_in_the_following_sentence(self):
        """入力1（review-regress.md R1）: 続く文の「3」（単位なし）と「3日」を打ち消さない。"""
        result = result_of("# 報告\n\n障害は昨夜のうちに解消しました。対応した版は3です。",
                           "# 報告\n\n障害は昨夜のうちに解消した。再発に備えて、監視の間隔を3日ごとに見直す。")
        self.assertEqual(sorted(shape(result)), [("added", None, 3, [], ["3日"]), ("lost", 3, None, ["3"], [])])
        self.assertEqual(result["fail_on_meaning_risk_count"], 2)
        lines = report_lines(result)
        self.assertIn("- 元にない数値（後3行目）: 3日", lines)
        self.assertIn("- 消えた数値（元3行目）: 3", lines)

    def test_lost_days_and_appendix_number_in_the_following_sentence(self):
        """入力2（review-regress.md R1）: 「保存期間は3日」が消えたことを出す。"""
        result = result_of("障害は昨夜のうちに解消しました。ログの保存期間は3日です。",
                           "障害は昨夜のうちに解消した。詳しい経緯は付録3にまとめた。")
        self.assertEqual(sorted(shape(result)), [("added", None, 1, [], ["3"]), ("lost", 1, None, ["3日"], [])])
        lines = report_lines(result)
        self.assertIn("- 消えた数値（元1行目）: 3日", lines)
        self.assertIn("- 元にない数値（後1行目）: 3", lines)

    def test_heading_number_does_not_hide_weeks_in_a_later_sentence(self):
        """コーパスの human_oga_02 → 03 の「2週間」と同じ形（組になった見出しの「抜粋 2」と、続く文の「2週間」）。"""
        result = result_of("## 抜粋 2\n資料は来週そろいます。", "## 抜粋 3\n先方の納期は、2週間は見ておきたい。")
        self.assertEqual(shape(result), [("replaced", 1, 1, ["2"], ["3"]), ("added", None, 2, [], ["2週間"])])
        self.assertIn("- 元にない数値（後2行目）: 2週間", report_lines(result))

    def test_minutes_of_a_time_are_not_cancelled_by_a_duration(self):
        """コーパスの 02_incident_report の「12:25 の 25」と同じ形: 時刻の「25」を、別の文の「25分」と打ち消さない。"""
        result = result_of("会議を10時に始めました。12:25に原因を特定しました。",
                           "会議を10時に始めた。原因の特定には25分かかった。")
        lost = [risk for risk in numbers(result) if risk["subkind"] == "lost"]
        self.assertEqual([risk["detail"]["removed"] for risk in lost], [["12", "25"]])
        self.assertEqual(lost[0]["old"], "12:25に原因を特定しました。")
        added = [risk for risk in numbers(result) if risk["subkind"] == "added"]
        self.assertEqual([risk["detail"]["added"] for risk in added], [["25分"]])

    def test_time_parts_need_their_counterparts_together(self):
        """時刻の「12:25」の「12」が別の所（20:12）にあっても、「12」と「25」が1つのまとまり（12時25分など）にそろって
        いなければ、「25」を「25分」と表記の違いにしない（コーパスの 02_incident_report と同じ形）。"""
        result = result_of("会議を10時に始めました。12:25に原因を特定しました。",
                           "会議を10時に始めた。20:12に通知が来た。原因の特定には25分かかった。")
        lost = [risk["detail"]["removed"] for risk in numbers(result) if risk["subkind"] == "lost"]
        self.assertEqual(lost, [["25"]])
        result = result_of("会議は10:30に始める。", "会議は10時に始め、30分休む。")
        self.assertEqual(shape(result), [("replaced", 1, 1, ["10", "30"], ["10時", "30分"])])

    def test_split_sentence_keeps_values_that_moved_to_the_next_sentence(self):
        """文を2つに分けた推敲で、続く文に移った値（数と単位が同じ）は数値の候補にしない（questions.md 35 の組み方のための処理）。"""
        before = "接続待ちが30秒のタイムアウトに達し、ゲートウェイが504を返した。"
        after = "接続待ちが30秒のタイムアウトに達した。ゲートウェイはそのとき504を返した。"
        self.assertEqual(numbers(result_of(before, after)), [])
        before = "Aの作業は3日かかり、Bの作業は5件残った。"
        after = "Aの作業は3日かかった。そのあと、Bの作業は5件残った。"
        self.assertEqual(numbers(result_of(before, after)), [])

    def test_split_sentence_with_a_changed_value(self):
        """文を分けて、続く文の値を変えたときは、その値を出す（値の書かれた文を示す）。"""
        result = result_of("接続待ちが30秒のタイムアウトに達し、ゲートウェイが504を返した。",
                           "接続待ちが30秒のタイムアウトに達した。ゲートウェイはそのとき503を返した。")
        found = shape(result)
        self.assertTrue(found, result["meaning_risks"])
        for risk in numbers(result):
            for value in risk["detail"].get("removed", []):
                self.assertIn(value, risk["old"] or "")
            for value in risk["detail"].get("added", []):
                self.assertIn(value, risk["new"] or "")


class PlaceTest(unittest.TestCase):
    """R3: 数値の候補は、値の書かれている文と行を示す。"""

    def test_values_point_to_their_own_lines(self):
        """review-regress.md R3 の入力（見出しの組のあとに続く文の値を、見出しの行に付けない）。"""
        result = result_of("【概要】\nその日の夜、決済の画面が開かなくなった。\n影響は全体の35%に及んだ。",
                           "概要\n夜になって、利用者が決済を終えられない状態が続いた。\nこのとき失敗した要求は、全体のおよそ38%だった。")
        self.assertTrue(numbers(result))
        for risk in numbers(result):
            with self.subTest(risk=risk):
                for value in risk["detail"].get("removed", []):
                    self.assertIn(value, risk["old"] or "")
                for value in risk["detail"].get("added", []):
                    self.assertIn(value, risk["new"] or "")
                self.assertNotEqual(risk["old_line"], 1)
                self.assertNotEqual(risk["new_line"], 1)

    def test_corpus_number_risks_show_the_sentence_with_the_value(self):
        """コーパス（推敲の48組と、同じフォルダの続く文書を並べた組）で、数値の候補が示す文に、挙げた値が書かれている
        （step-c-detectors/review-work/regress/misattr.py と同じ数え方。直す前は139件中22件で書かれていなかった）。"""
        pairs = []
        for name in sorted(os.listdir(str(CORPUS / "yomiyasu_rewritten"))):
            source = ("blacklist_ai/" + name[:-6] + ".md") if name.endswith("_bl.md") else ("raw_ai/" + name)
            pairs.append((source, "yomiyasu_rewritten/" + name))
        for folder in ("edge_cases", "human", "raw_ai"):
            names = sorted(os.listdir(str(CORPUS / folder)))
            pairs.extend((folder + "/" + a, folder + "/" + b) for a, b in zip(names, names[1:]))
        missing = []
        for a, b in pairs:
            before = (CORPUS / a).read_bytes().decode("utf-8")
            after = (CORPUS / b).read_bytes().decode("utf-8")
            for risk in numbers(yomiyasu_diff.diff(before, after)):
                if risk["subkind"] not in ("added", "lost", "replaced"):
                    continue
                miss = ([value for value in risk["detail"].get("removed", []) if value not in (risk["old"] or "")]
                        + [value for value in risk["detail"].get("added", []) if value not in (risk["new"] or "")])
                if miss:
                    missing.append((a, b, risk["subkind"], miss))
        self.assertEqual(missing, [])


class SameSentenceUnitTest(unittest.TestCase):
    """R2: 同じ文の中で単位を付けた・外した・別の種類の数に変えた書き換えは number/replaced。表記の違いは候補にしない。"""

    REPLACED = (
        ("設定は手順3で変える。", "設定は3日で変える。", ["3"], ["3日"]),
        ("リトライは3回までにする。", "リトライは3までにする。", ["3回"], ["3"]),
        ("上限は5です。", "上限は5GBです。", ["5"], ["5GB"]),
        # 時刻の「10:30」の「30」と、時間の長さの「30分」（まとまりの「10」が相手の側にない）
        ("会議は10:30に始める。", "会議は30分後に始める。", ["10", "30"], ["30分"]),
    )
    NOTATION_ONLY = (
        ("容量は 16 GB です。", "容量は16GBです。"),
        ("処理は 3 s かかる。", "処理は3sかかる。"),
        ("作業は3 日かかる。", "作業は3日かかる。"),
        ("作業には3〜5日かかる。", "作業には3日から5日かかる。"),
        ("作業には3から5日かかる。", "作業には3日から5日かかる。"),
        ("作業には3-5日かかる。", "作業には3日から5日かかる。"),
        ("参加者は5～10人を見込む。", "参加者は5人から10人を見込む。"),
        ("参加者は5〜10を見込む。", "参加者は5人から10人を見込む。"),
        ("公開日は2026-10-13です。", "公開日は2026年10月13日です。"),
        ("公開日は2026/10/13です。", "公開日は2026年10月13日です。"),
        ("会議は10:30に始める。", "会議は10時30分に始める。"),
        ("受付は17:30までです。", "受付は17時30分までです。"),
        ("作業には3〜5日かかる。", "作業には3日以上5日以内かかる。"),
    )

    def test_unit_added_or_removed_is_replaced(self):
        for before, after, removed, added in self.REPLACED:
            with self.subTest(before=before):
                result = result_of(before, after)
                self.assertEqual(shape(result), [("replaced", 1, 1, removed, added)])
                self.assertEqual(result["fail_on_meaning_risk_count"], 1)

    def test_range_date_time_and_space_are_notation(self):
        for before, after in self.NOTATION_ONLY:
            with self.subTest(before=before):
                self.assertEqual(numbers(result_of(before, after)), [])

    def test_range_shortened_to_one_value(self):
        """範囲を1つの値にした書き換え（3〜5日 → 3日）は、消えた「5日」だけを出す（「3」は「3日」の表記の違い）。"""
        self.assertEqual(shape(result_of("作業は3〜5日かかる。", "作業は3日かかる。")), [("lost", 1, 1, ["5日"], [])])

    def test_cli_fail_on(self):
        with tempfile.TemporaryDirectory(prefix="yomiyasu-numbers-") as folder:
            for index, (before, after, _, _) in enumerate(self.REPLACED[:3]):
                with self.subTest(before=before):
                    a = Path(folder) / "a{}.md".format(index)
                    b = Path(folder) / "b{}.md".format(index)
                    a.write_bytes((before + "\n").encode("utf-8"))
                    b.write_bytes((after + "\n").encode("utf-8"))
                    process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "--fail-on", "meaning-risk",
                                              str(a), str(b)], capture_output=True, encoding="utf-8", timeout=60)
                    self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                    self.assertIn("- 数値が変わった（1行目）: ", process.stdout)


class GroundNumberTest(unittest.TestCase):
    """R2b: 資料との照合で、資料の単位なしの数が単位つきの数を「資料にある」としてしまう形を塞ぐ。"""

    def classification(self, result, text):
        found = [item["classification"] for item in result["items"]
                 if item["kind"] == "number" and item["text"] == text and item["classification"] != "not_in_final"]
        self.assertEqual(len(found), 1, result["items"])
        return found[0]

    def test_step_number_does_not_support_weeks(self):
        result = yomiyasu_diff.ground("移行は2週間後に始め、設定ファイルの値を確かめる。\n",
                                      ["移行の手順2では、設定ファイルを開いて値を確かめる。\n"])
        self.assertEqual(self.classification(result, "2週間"), "not_in_sources")
        self.assertIn({"text": "2週間", "value": "2", "unit": "週間"},
                      [risk["detail"] for risk in result["meaning_risks"] if risk["subkind"] == "number"])

    def test_plan_and_table_numbers_do_not_support_days_and_percent(self):
        result = yomiyasu_diff.ground("作業は1日で終わり、成功率は3%だった。\n", ["第1案を採る。結果は表3にまとめた。\n"])
        self.assertEqual(self.classification(result, "1日"), "not_in_sources")
        self.assertEqual(self.classification(result, "3%"), "not_in_sources")

    def test_unitless_final_number_is_not_supported_by_a_unit_number(self):
        """最終稿の単位なしの数も同じ条件（範囲・日付・時刻の部品か、空白のあとに単位）で見る。"""
        result = yomiyasu_diff.ground("設定は手順2で開く。\n", ["移行には2週間かかる。\n"])
        self.assertEqual(self.classification(result, "2"), "not_in_sources")

    def test_notation_differences_are_still_in_the_materials(self):
        for final, material in (("メモリは16GBです。\n", "メモリは 16 GB。\n"),
                                ("処理は3日かかる。\n", "処理は3 日かかる。\n"),
                                ("作業は3日から5日かかる。\n", "作業は3〜5日かかる。\n"),
                                ("作業は3〜5日かかる。\n", "作業は3日から5日かかる。\n"),
                                ("公開日は2026年10月13日です。\n", "公開日: 2026-10-13\n"),
                                ("公開日は2026-10-13です。\n", "公開日は2026年10月13日。\n"),
                                ("会議は10時30分に始める。\n", "会議: 10:30開始\n")):
            with self.subTest(final=final):
                result = yomiyasu_diff.ground(final, [material])
                self.assertEqual([risk for risk in result["meaning_risks"] if risk["subkind"] == "number"], [])
                self.assertEqual([item for item in result["items"] if item["classification"] == "not_in_final"], [])

    def test_time_does_not_support_a_duration(self):
        result = yomiyasu_diff.ground("原因の特定には25分かかった。\n", ["12:25に原因を特定した。\n"])
        self.assertEqual(self.classification(result, "25分"), "not_in_sources")
        # 最終稿の別の所に「12」（20:12）があっても、「12」と「25」が1つのまとまりにそろっていなければ資料にあるとしない
        result = yomiyasu_diff.ground("20:12に通知が来た。原因の特定には25分かかった。\n", ["12:25に原因を特定した。\n"])
        self.assertEqual(self.classification(result, "25分"), "not_in_sources")
        result = yomiyasu_diff.ground("作業は20:30に終えた。\n", ["上限は20接続で、待ちは30秒だった。\n"])
        self.assertEqual(self.classification(result, "30"), "not_in_sources")

    def test_not_in_final_uses_the_same_rule(self):
        """「参考: 資料にあって最終稿にない数値」: 最終稿の「HTTP/2」の「2」は、資料の「2回」を「最終稿にある」としない。"""
        result = yomiyasu_diff.ground("HTTP/2で通信する。\n", ["再試行は2回までにする。\n"])
        rest = [item["text"] for item in result["items"] if item["classification"] == "not_in_final"]
        self.assertEqual(rest, ["2回"])

    def test_check_run_with_material_fails_on_meaning_risk(self):
        """review-regress.md R2b の入力: check run --material で「資料にない数値: 2週間」が出て、終了コード1。"""
        with tempfile.TemporaryDirectory(prefix="yomiyasu-numbers-") as folder:
            root = Path(os.path.realpath(folder))
            material = root / "mat.md"
            final = root / "final.md"
            material.write_bytes("移行の手順2では、設定ファイルを開いて値を確かめる。\n".encode("utf-8"))
            final.write_bytes("移行は2週間後に始め、設定ファイルの値を確かめる。\n".encode("utf-8"))
            env = dict(os.environ)
            for name in ("YOMIYASU_STATE_DIR", "YOMIYASU_SESSION", "CODEX_THREAD_ID"):
                env.pop(name, None)
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_check.py"), "run", "--fail-on", "meaning-risk",
                                      "--material", str(material), "--final", str(final), "--state-dir", str(root / "state")],
                                     cwd=str(root), env=env, capture_output=True, encoding="utf-8", timeout=60)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertIn("- 資料にない数値（後1行目）: 2週間", process.stdout.split("\n"))
            self.assertIn("meaning_risk=1", process.stdout.split("\n")[1])


class OneThingTest(unittest.TestCase):
    """R4: 数量を主張しない「一つ」（一つの、一つずつ、もう一つ）は、単独では数値の候補にしない。数が変わればまだ出す。"""

    NOT_NUMBER = (
        ("サービスを分けた。", "サービスを分けたので、一つのサービスの障害が他へ広がりにくい。"),
        ("手順を確かめる。", "手順を一つずつ確かめる。"),
        ("理由がある。", "もう一つ理由がある。"),
        ("一つの画面で確かめる。", "画面で確かめる。"),
        ("1つの画面で確かめる。", "画面で確かめる。"),
        ("理由がある。", "ひとつの理由がある。"),
        ("画面を開く。", "画面を開く。\n\nもう一つの画面も開く。"),
    )
    REPLACED = (
        ("二つのサービスに分ける。", "一つのサービスにまとめる。", ["二つ"], ["一つ"]),
        ("一つの方法がある。", "三つの方法がある。", ["一つ"], ["三つ"]),
        ("方法は一つだ。", "方法は三つだ。", ["一つ"], ["三つ"]),
    )

    def test_one_without_a_quantity_claim_is_not_number(self):
        for before, after in self.NOT_NUMBER:
            with self.subTest(before=before, after=after):
                result = result_of(before, after)
                self.assertEqual(numbers(result), [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_changed_count_is_still_replaced(self):
        for before, after, removed, added in self.REPLACED:
            with self.subTest(before=before):
                self.assertEqual(shape(result_of(before, after)), [("replaced", 1, 1, removed, added)])

    def test_one_with_other_values_is_not_replaced(self):
        """「一つの」が消えて別の単位の値が増えたときは、増えた値だけを出す（一つ → 30秒 の入れ替えにしない）。"""
        result = result_of("一つの理由は遅延だ。", "理由は30秒の遅延だ。")
        self.assertEqual(shape(result), [("added", 1, 1, [], ["30秒"])])

    def test_one_without_a_quantity_claim_is_not_unsupported(self):
        """新規作成の照合でも、数量を主張しない「一つ」だけでは「資料にない数値」にしない。数量の「三つ」は出す。"""
        result = yomiyasu_diff.ground("サービスを分けたので、一つのサービスの障害が他へ広がりにくい。\n", ["サービスを分ける。\n"])
        self.assertEqual([risk for risk in result["meaning_risks"] if risk["subkind"] == "number"], [])
        result = yomiyasu_diff.ground("サービスを三つに分ける。\n", ["サービスを分ける。\n"])
        self.assertEqual([risk["detail"]["text"] for risk in result["meaning_risks"] if risk["subkind"] == "number"], ["三つ"])

    def test_corpus_pair_with_one_service(self):
        """コーパスの blacklist_ai/01_tech_arch_sonnet_default → yomiyasu_rewritten/…_bl（正しい推敲）は、基準 38d6556 と同じく
        --fail-on=meaning-risk に数える候補が0件。"""
        before = (CORPUS / "blacklist_ai" / "01_tech_arch_sonnet_default.md").read_bytes().decode("utf-8")
        after = (CORPUS / "yomiyasu_rewritten" / "01_tech_arch_sonnet_default_bl.md").read_bytes().decode("utf-8")
        self.assertEqual(yomiyasu_diff.diff(before, after)["fail_on_meaning_risk_count"], 0)


class KanjiCounterTest(unittest.TestCase):
    """F10: 条、号、階、分の漢数字。万を含む数の換算は限界のまま。"""

    NOTATION_ONLY = (
        ("第三条に定める手続を経た場合に限り、許可する。", "第3条に定める手続を経た場合に限り、許可する。"),
        ("第二号の書式で届け出る。", "第2号の書式で届け出る。"),
        ("会場は三階の会議室です。", "会場は3階の会議室です。"),
        ("作業は三十分で終わる。", "作業は30分で終わる。"),
        ("休憩は十分間です。", "休憩は10分間です。"),
        ("作業は二十五分かかる。", "作業は25分かかる。"),
    )
    VALUE_CHANGED = (
        ("第三条に定める。", "第4条に定める。"),
        ("会場は三階です。", "会場は4階です。"),
        ("作業は三十分で終わる。", "作業は40分で終わる。"),
    )

    def test_kanji_and_arabic_counters_are_notation(self):
        for before, after in self.NOTATION_ONLY:
            with self.subTest(before=before):
                self.assertEqual(numbers(result_of(before, after)), [])

    def test_changed_values_are_number(self):
        for before, after in self.VALUE_CHANGED:
            with self.subTest(before=before):
                self.assertEqual([risk["subkind"] for risk in numbers(result_of(before, after))], ["replaced"])

    def test_enough_is_not_a_number(self):
        for text in ("十分に確かめた。", "十分な時間がある。", "数十分かかる。"):
            with self.subTest(text=text):
                self.assertEqual(yomiyasu_diff.extract_numbers(text), [])
        values = [(item["value"], item["unit"]) for item in yomiyasu_diff.extract_numbers("三十分と十分間、第三条、第二号、三階。")]
        self.assertEqual(values, [("30", "分"), ("10", "分"), ("3", "条"), ("2", "号"), ("3", "階")])
        values = [(item["value"], item["unit"]) for item in yomiyasu_diff.extract_numbers("第3条、第2号、3階。")]
        self.assertEqual(values, [("3", "条"), ("2", "号"), ("3", "階")])

    def test_words_that_are_not_counters(self):
        """「階層」「条件」の「階」「条」は助数詞にしない（3階層 → 3層 を数値の候補にしない）。"""
        values = [(item["value"], item["unit"]) for item in yomiyasu_diff.extract_numbers("3階層と三階層、3条件と三条件。")]
        self.assertEqual(values, [("3", ""), ("3", "")])
        self.assertEqual(numbers(result_of("システムは3階層で動く。", "システムは3層で動く。")), [])

    def test_ten_thousand_is_still_a_limit(self):
        """万を含む数の換算（一万円 → 1万円）は、2.5.2 の残る限界のまま（「1」が元にない数値になる）。"""
        self.assertEqual(shape(result_of("費用は一万円です。", "費用は1万円です。")), [("added", 1, 1, [], ["1"])])


if __name__ == "__main__":
    unittest.main()
