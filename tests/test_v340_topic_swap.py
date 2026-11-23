#!/usr/bin/env python3
"""v3.4.0: diff の、話題ごとの入れ替わり（kind topic の subkind person と negation）の試験。

「初日の受付は田中さん、二日目は鈴木さんです」を「初日の受付は鈴木さん、二日目は田中さんです」にすると、担当が入れ替わる。
「旧版は使えません。新版は使えます。」を「旧版は使えます。新版は使えません。」にすると、使えない版が入れ替わる。文の組が
「旧版は使えません ↔ 旧版は使えます」でなく「旧版は使えません ↔ 新版は使えません」とずれたり、1つの文を2つに分けたりすると、
組になった文の中を比べる今までの否定と「が」「を」の入れ替えの検査では拾えなかった。3.4.0 からは、同じ変更の塊（hunk）の文を
話題（「〜は」「〜では」など）に分け、元と後のどちらにも1度だけ出る話題の語の中身を比べる。
人の入れ替わりは kind topic の subkind person、否定の移動は subkind negation として出し、見直しの候補として
--fail-on=meaning-risk には数えない（3.2.0 の義務の強さなどと同じ）。
組は tests/fixtures/topic_swap_cases.json（3.4.0 の作業で書いた組。文は、本物の下書きの段落を言い換えた real- の組のほかは合成の文）。
数の線の組は、出すべき組（report）15と出さない組（no_report）16。0でなければならない組（required_zero）は、確かめ役が別に
書いた出さない組（A01〜A20 のうちの19組と、id が heldout- の21組）、その1つ（中身が句読点だけの話題「今週は、」が次の節の
中身を受ける形）の下の話題の語を変えた A21、本物の下書きの段落の言い換え（real-K1〜K3）。ほかは数えない組で、拾えない形
（docs/limitations.md に書いた形）は今の動きのまま見張る。
"""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yomiyasu_diff  # noqa: E402
from portable import paced_limit, timing_clock  # noqa: E402

CASES = {case["id"]: case for case in json.loads((ROOT / "tests" / "fixtures" / "topic_swap_cases.json")
                                                  .read_text(encoding="utf-8"))["cases"]}
# この版の kind と subkind
PERSON = ("topic", "person")
NEGATION = ("topic", "negation")
COUNTED = False


def run(case):
    return yomiyasu_diff.diff(case["a"], case["b"])


def topic_risks(result):
    return [risk for risk in result["meaning_risks"] if (risk["kind"], risk["subkind"]) in (PERSON, NEGATION)]


def group(name):
    return [case for case in CASES.values() if case["group"] == name]


class TopicSwapSetTest(unittest.TestCase):
    def test_report_cases(self):
        """出すべき組15は、人の入れ替わりか否定の移動の候補をちょうど1件出す。"""
        for case in group("report"):
            with self.subTest(case=case["id"]):
                result = run(case)
                found = topic_risks(result)
                self.assertEqual(len(found), 1, found)
                expected = PERSON if case["category"].startswith("人の入れ替わり") else NEGATION
                self.assertEqual((found[0]["kind"], found[0]["subkind"]), expected)
                self.assertGreaterEqual(len(found[0]["detail"]["topics"]), 2)
                self.assertIsNone(found[0]["basis"])
                self.assertEqual(yomiyasu_diff.fail_on_count(found), 1 if COUNTED else 0)

    def test_no_report_cases(self):
        """出さない組16と、0でなければならない組44（確かめ役の組、下の話題の語を変えた A01 の形、本物の下書きの言い換え）と、
        数えない出さない組は、候補を出さない。"""
        for name in ("no_report", "required_zero", "no_report_extra"):
            for case in group(name):
                with self.subTest(group=name, case=case["id"]):
                    self.assertEqual(topic_risks(run(case)), [])
        self.assertEqual(len(group("no_report")), 16)
        self.assertEqual(len(group("required_zero")), 44)

    def test_taken_over_topics(self):
        """中身が句読点だけの話題（今週は、）は次の節の中身を受ける。元と後で受けた先の話題の語が違えば比べない（節の順を
        入れ替えただけの A01・A19・A21）。受けた先が同じなら比べる（週ごとに入れ替えた W01・W02）。片方だけが受けた中身は、受けた先の
        話題の語がもう片方の中身にあるときだけ比べる（先の節の「では」「は」を「で」「が」にして節の順を入れ替えただけの heldout-N03
        と heldout-N04 は比べず、P11 と、受けた先の語に空白のある V01 は比べる）。親の話題で始まる文の話題は、元と後の親の語が違えば
        比べない（段落の順を入れ替えただけの heldout-N21）。受けた中身の話題は、受けた先の話題も比べるときは人の比べに入れない
        （親の話題の下で2人が入れ替わった heldout-R12 を拾う）。"""
        for name in ("A01", "A19", "A21", "heldout-N03", "heldout-N04", "heldout-N21"):
            with self.subTest(case=name):
                self.assertEqual(topic_risks(run(CASES[name])), [])
                self.assertEqual(topic_risks(yomiyasu_diff.diff(CASES[name]["b"], CASES[name]["a"])), [])
        for name in ("P11", "V01"):
            with self.subTest(case=name):
                found = topic_risks(run(CASES[name]))
                self.assertEqual([(risk["kind"], risk["subkind"]) for risk in found], [NEGATION])
                self.assertEqual([item["topic"] for item in found[0]["detail"]["topics"]], ["v1のAPI", "v2のAPI"])
        found = topic_risks(run(CASES["heldout-R12"]))
        self.assertEqual([(risk["kind"], risk["subkind"]) for risk in found], [PERSON])
        self.assertEqual(found[0]["detail"], {"topics": [{"topic": "月曜", "old": ["青木さん"], "new": ["松井さん"]},
                                                         {"topic": "木曜", "old": ["松井さん"], "new": ["青木さん"]}]})
        old = yomiyasu_diff._topic_segments(["前半は、司会は小野さん、記録は田村さんです。"])
        new = yomiyasu_diff._topic_segments(["後半は、記録は小野さん、司会は田村さんです。"])
        self.assertEqual(yomiyasu_diff._topic_parents(old), {"司会": "前半", "記録": "前半"})
        self.assertEqual(yomiyasu_diff._topic_parents(new), {"記録": "後半", "司会": "後半"})
        self.assertEqual(yomiyasu_diff._topic_changes(["前半は、司会は小野さん、記録は田村さんです。"],
                                                      ["後半は、記録は小野さん、司会は田村さんです。"]), [])
        found = topic_risks(run(CASES["W01"]))
        self.assertEqual([(risk["kind"], risk["subkind"]) for risk in found], [PERSON])
        self.assertEqual(found[0]["detail"], {"topics": [{"topic": "今週", "old": ["田中さん"], "new": ["鈴木さん"]},
                                                         {"topic": "来週", "old": ["鈴木さん"], "new": ["田中さん"]}]})
        found = topic_risks(run(CASES["W02"]))
        self.assertEqual([(risk["kind"], risk["subkind"]) for risk in found], [NEGATION])
        self.assertEqual([item["topic"] for item in found[0]["detail"]["topics"]], ["今週", "来週"])
        segments = yomiyasu_diff._topic_segments(["今週は、本番環境では有効にせず、検証環境では有効にします。"])
        self.assertEqual(segments, [("今週", 0, "本番環境では有効にせず", True, "本番環境"),
                                    ("本番環境", 0, "有効にせず", False, "本番環境"),
                                    ("検証環境", 0, "有効にします", False, "検証環境")])

    def test_former_limits(self):
        """「しか〜ない」と「だけ」を逆の向きに言い換えただけの A03 は出さない。中身と一緒に値が動いた F13 は出す。"""
        self.assertEqual(topic_risks(run(CASES["A03"])), [])
        found = topic_risks(run(CASES["F13"]))
        self.assertEqual([(risk["kind"], risk["subkind"]) for risk in found], [NEGATION])
        self.assertEqual(found[0]["detail"]["topics"],
                         [{"topic": "会員登録", "old": "無料です", "new": "月額500円の有料ですが"},
                          {"topic": "プレミアム機能の利用", "old": "月額500円の有料です", "new": "無料です"}])

    def test_report_extras(self):
        """数えない出すべき組。拾える形（1つの塊で最初の1組だけを出す。L02、V09）と、拾えない形（docs/limitations.md に書いた形）を、
        今の動きのまま見張る。今の否定や数値の候補が拾う組（expect が existing か、covered_by のある組）は下の試験で見る。"""
        missed = {"F11", "F14", "W03", "X01", "X02", "X04", "X07", "X09", "X10", "heldout-E01", "V02", "V03", "V04", "V05", "V08",
                  "V10", "V11", "V12", "V13", "V14", "recheck-X20", "recheck-PH11"}
        for case in group("report_extra"):
            if case["expect"] == "existing" or case.get("covered_by"):
                continue
            with self.subTest(case=case["id"]):
                found = topic_risks(run(case))
                self.assertEqual(len(found), 0 if case["id"] in missed else 1, found)
                if found and case.get("subkind"):
                    self.assertEqual(found[0]["subkind"], case["subkind"])

    def test_hiragana_and_latin_names_are_not_people(self):
        """人に数えるのは漢字か片仮名の1〜6字の名前に敬称を付けた語だけなので、平仮名の名前（V13）と英字の名前（V14）の入れ替わりには
        話題の候補が出ない（限界）。行頭の句の宛名の候補は出る。"""
        for name, removed, added in (("V13", "初日の受付はさくらさん", "初日の受付はもみじさん"),
                                     ("V14", "初日の発表はJohnさん", "初日の発表はMaryさん")):
            with self.subTest(case=name):
                result = run(CASES[name])
                self.assertEqual(topic_risks(result), [])
                self.assertEqual([c["detail"] for c in result["immutable"]["candidates"] if c["subkind"] == "addressee"],
                                 [{"removed": [removed], "added": [added]}])

    def test_existing_candidates_are_not_doubled(self):
        """今の否定と数値の候補が出る組（X05、X06、X11 と、covered_by のある heldout-R04、posthoc-H06）には、話題の候補を重ねない。"""
        for case in group("report_extra"):
            if case["expect"] != "existing" and not case.get("covered_by"):
                continue
            with self.subTest(case=case["id"]):
                result = run(case)
                self.assertEqual(topic_risks(result), [])
                kinds = (case["covered_by"],) if case.get("covered_by") else ("number", "negation")
                self.assertTrue([risk for risk in result["meaning_risks"] if risk["kind"] in kinds])

    def test_partly_covered_moves_and_joined_lines(self):
        """今の否定の候補が入れ替わった文の一部にだけ出た組（recheck-R07）には、話題の候補も出す（全部の文が覆われたときだけ
        重ねない）。別の行の文を「元」「後」でつなぐとき、前の文が句点などで終わらなければ全角の空白を挟む（recheck-R12）。"""
        for name in ("recheck-R07", "recheck-R12"):
            for old, new in ((CASES[name]["a"], CASES[name]["b"]), (CASES[name]["b"], CASES[name]["a"])):
                with self.subTest(case=name, old=old):
                    found = topic_risks(yomiyasu_diff.diff(old, new))
                    self.assertEqual([(risk["kind"], risk["subkind"]) for risk in found], [NEGATION])
        result = run(CASES["recheck-R07"])
        self.assertTrue([risk for risk in result["meaning_risks"] if risk["kind"] == "negation"])
        found = topic_risks(run(CASES["recheck-R12"]))
        self.assertEqual((found[0]["old"], found[0]["new"]),
                         ("Aプランは初期費用なし" + chr(0x3000) + "Bプランは初期費用あり",
                          "Aプランは初期費用あり" + chr(0x3000) + "Bプランは初期費用なし"))
        self.assertEqual(yomiyasu_diff._topic_join([]), "")

    def test_candidates_come_last(self):
        """話題の候補は、ほかの候補の決め方に使わず、意味が変わる恐れの最後に足す。"""
        for case in group("report") + group("report_extra"):
            with self.subTest(case=case["id"]):
                risks = run(case)["meaning_risks"]
                kinds = [(risk["kind"], risk["subkind"]) in (PERSON, NEGATION) for risk in risks]
                self.assertEqual(kinds, sorted(kinds))

    def test_messages(self):
        """否定の移動の行は、語の途中で切らずに話題の中身を出す。"""
        lines = {name: [yomiyasu_diff._risk_line(risk) for risk in topic_risks(run(CASES[name]))] for name in ("P01", "P02", "P09")}
        self.assertEqual(lines["P01"], ['話題ごとの人の組み合わせが変わった（4行目）: 初日の受付 田中さん→鈴木さん、二日目 鈴木さん→田中さん。--fail-on には数えません。原文の話題と人の組を入れ替えていないか確かめてください。'])
        self.assertEqual(lines["P02"], ['否定が別の話題へ移った（1行目）: 旧版「使えません」→「使えます」、新版「使えます」→「使えません」。--fail-on には数えません。否定を別の話題に移していないか確かめてください。'])
        self.assertEqual(lines["P09"], ['否定が別の話題へ移った（3行目）: Windows版「初期設定で有効になっており」→「初期設定で無効になっています」、Mac版「無効になっています」→「有効です」。--fail-on には数えません。否定を別の話題に移していないか確かめてください。'])
        for case in group("report"):
            with self.subTest(case=case["id"]):
                line, = [yomiyasu_diff._risk_line(risk) for risk in topic_risks(run(case))]
                self.assertEqual("--fail-on には数えません。" in line, not COUNTED, line)

    def test_risk_order_and_fail_on_kinds(self):
        """kind topic は見直しの候補で、FAIL_ON_KINDS に入れず、_RISK_ORDER では既存の kind の後ろに置く。"""
        self.assertNotIn("topic", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(yomiyasu_diff._RISK_ORDER["topic"], 26)
        self.assertEqual(max(yomiyasu_diff._RISK_ORDER.values()), 26)
        result = run(CASES["P02"])
        self.assertEqual(result["meaning_risk_count"], 1)
        self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_negation_flip_default_unchanged(self):
        """_negation_flip の marks を渡さないときは、今までと同じ数え方（_negation_marks）。"""
        for old, new in (("設定する。", "設定しない。"), ("旧版は使えません。", "新版は使えません。"),
                         ("学年を問わず、参加できます。", "学年に関係なく参加できます。")):
            with self.subTest(old=old):
                self.assertEqual(yomiyasu_diff._negation_flip(old, new),
                                 yomiyasu_diff._negation_flip(old, new, yomiyasu_diff._negation_marks))

    def test_twin_scripts_are_identical(self):
        self.assertEqual((ROOT / "scripts" / "yomiyasu_diff.py").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_diff.py").read_bytes())


def shapes(count):
    """話題の候補の決め方が2乗になりうる形（3.4.0 の確かめで見つけた形と、作り直しで足した形）。元と後の文の並び。oneside は片方
    だけが受けた中身の話題（受けた先の語をもう片方の中身で探す）、parents は親の話題の違う文の組。"""
    names = ["{}{}{}さん".format(chr(0x30A2 + i % 40), chr(0x30A2 + i // 40 % 40), chr(0x30A2 + i // 1600 % 40)) for i in range(count + 1)]
    return {
        "flips": (["項目{}は使え{}。".format(i, "ません" if i % 2 else "ます") for i in range(count)],
                  ["項目{}は使え{}。".format(i, "ます" if i % 2 else "ません") for i in range(count)]),
        "blanks": (["、".join("区分{}は".format(i) for i in range(count)) + "使えません。"],
                   ["、".join("区分{}は".format(i) for i in range(count)) + "使えます。"]),
        "chain": (["第{}週は{}。".format(i, names[i]) for i in range(count)],
                  ["第{}週は{}。".format(i, names[i + 1]) for i in range(count)]),
        "crowd": (["、".join("区分{}は".format(i) for i in range(count)) + "、" + "と".join(names[:count]) + "が担当します。",
                   "受付は田中さん、案内は鈴木さんです。"],
                  ["、".join("区分{}は".format(i) for i in range(count)) + "、" + "と".join(names[:count]) + "が担当します。",
                   "受付は鈴木さん、案内は田中さんです。"]),
        "exchange": (["、".join("区分{}は".format(i) for i in range(count)) + "、" + "旧版の画面と古い帳票と" * 50 + "を使えません。",
                      "備考は使えます。"],
                     ["、".join("区分{}は".format(i) for i in range(count)) + "、" + "新しい画面とまとめた一覧と" * 50 + "を使えます。",
                      "備考は使えません。"]),
        "oneside": (["上期{}は、本社では在宅勤務を認めず、支社では認めます。".format(i) for i in range(count)],
                    ["上期{}は支社で在宅勤務を認め、本社では認めません。".format(i) for i in range(count)]),
        "parents": (["区分{0}は、司会{0}は小野さん、記録{0}は田村さんです。".format(i) for i in range(count)],
                    ["区画{0}は、記録{0}は小野さん、司会{0}は田村さんです。".format(i) for i in range(count)]),
    }


class TopicSwapWorkTest(unittest.TestCase):
    def test_work_is_linear(self):
        """中身の切り出し、人の語を探す字数、受けた先の語を探すためにそろえる字数は、話題の数を2倍にしても3倍未満（2乗なら4倍）。"""
        from unittest.mock import patch
        work = {}
        for count in (250, 500, 1000):
            with patch.object(yomiyasu_diff, "_topic_trim", wraps=yomiyasu_diff._topic_trim) as trim, \
                    patch.object(yomiyasu_diff, "_topic_persons", wraps=yomiyasu_diff._topic_persons) as persons, \
                    patch.object(yomiyasu_diff, "_topic_normal", wraps=yomiyasu_diff._topic_normal) as normal:
                for name, (old, new) in shapes(count).items():
                    yomiyasu_diff._topic_changes(old, new)
            work[count] = (sum(len(call.args[0]) for call in trim.call_args_list),
                           sum(len(call.args[0]) for call in persons.call_args_list),
                           sum(len(call.args[0]) for call in normal.call_args_list))
        for count in (500, 1000):
            for part in range(3):
                with self.subTest(count=count, part=part):
                    self.assertLess(work[count][part], 3 * work[count // 2][part])


class TopicSwapTimingTest(unittest.TestCase):
    def test_large_shapes_finish_quickly(self):
        """話題が4,000ある形でも、話題の比べ（_topic_changes）は1形0.5秒以内（3.4.0 の最初の試作は blanks 6秒、chain 30秒）。"""
        clock = timing_clock()
        for name, (old, new) in shapes(4000).items():
            with self.subTest(shape=name):
                started = clock()
                yomiyasu_diff._topic_changes(old, new)
                limit, detail = paced_limit(0.5, clock() - started)
                self.assertLess(clock() - started, limit, detail)


class TopicSwapCliTest(unittest.TestCase):
    def cli(self, case, *args):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "a.md").write_bytes(case["a"].encode("utf-8"))
            Path(folder, "b.md").write_bytes(case["b"].encode("utf-8"))
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "--fail-on=meaning-risk",
                                      *args, "a.md", "b.md"], capture_output=True,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"), cwd=folder)
        return process.returncode, process.stdout.decode("utf-8"), process.stderr.decode("utf-8")

    def test_exit_code_and_text(self):
        code, out, err = self.cli(CASES["P02"])
        self.assertEqual(code, 0, err)
        self.assertIn("- " + '否定が別の話題へ移った（1行目）: 旧版「使えません」→「使えます」、新版「使えます」→「使えません」。--fail-on には数えません。否定を別の話題に移していないか確かめてください。' + "\n", out)
        code, out, err = self.cli(CASES["N02"])
        self.assertEqual(code, 0, err)

    def test_json_format_is_unchanged(self):
        """JSON の版と、上の段と意味が変わる恐れのキーは、話題の候補が出ても出なくても同じ。"""
        code, out, err = self.cli(CASES["P01"], "--json")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        code, out, err = self.cli(CASES["N01"], "--json")
        self.assertEqual(code, 0, err)
        quiet = json.loads(out)
        self.assertEqual((found["format"], found["format_version"]), ("yomiyasu-diff", 2))
        self.assertEqual(list(found), list(quiet))
        risk = found["meaning_risks"][-1]
        self.assertEqual(list(risk), ["kind", "subkind", "old_line", "new_line", "old", "new", "detail", "basis"])
        self.assertEqual((risk["kind"], risk["subkind"]), PERSON)
        self.assertEqual(risk["detail"], {"topics": [{"topic": "初日の受付", "old": ["田中さん"], "new": ["鈴木さん"]},
                                                     {"topic": "二日目", "old": ["鈴木さん"], "new": ["田中さん"]}]})


if __name__ == "__main__":
    unittest.main()
