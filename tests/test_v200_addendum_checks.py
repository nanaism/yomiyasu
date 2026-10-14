#!/usr/bin/env python3
"""v2.0.0（G10、G11）: diff の否定対比の主張の逆転（kind contrast_reversal）と、文体の硬化の検査（stiffness）。

期待値は追加文書（yomiyasu-v2.0.0-addendum-rephrase-stiffness_20261013-1900.md）の 1.4、1.5、2.2〜2.5 と、
試作で決め直した数値から取った。文はすべて合成の文
（追加文書の表の文と、試作の段で作った合成の組）。

- contrast_reversal は meaning_risks に入る（意味が変わる恐れの節に出す）が、--fail-on=meaning-risk には数えない。
- 硬化の検査は diff の JSON の stiffness（最後のキー）と、レポートの「■ 文体の硬化」の節に出す。見直し候補の件数
  （candidate_count）と状態の行には入れない（既存の出力の形を変えない）。文書の種類が formal なら参考（level info）。
- 名詞化の言い回しの一覧は references/lists/nominalization.txt（ルートと skills の両方）。diff はスクリプトの隣の
  ../references/lists/ を読み、なければ内蔵の一覧で動く。
"""

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PACKAGE = ROOT / "skills" / "yomiyasu"
sys.path.insert(0, str(SCRIPTS))

import yomiyasu_diff  # noqa: E402

RISK_KEYS = {"kind", "subkind", "old_line", "new_line", "old", "new", "detail", "basis"}
STIFF_KEYS = {"kind", "subkind", "old_line", "new_line", "old", "new", "detail", "level"}


def diff(before, after, **options):
    """1行の文は、各ファイルの末尾に改行がある形で比べる。"""
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after, **options)


def reversals(result):
    return [risk for risk in result["meaning_risks"] if risk["kind"] == "contrast_reversal"]


# ---- 追加文書 1.5 の表 ----

KEEP_UNCHANGED = (
    "原因はキャッシュではなく、DNSの設定でした。",
    "怒っているのではなく、心配しているだけです。",
    "仮説では書き込みが遅いと考えていたが、実際は読み込みが遅かった。",
)
# 残す例の言い回しだけを変えた形（試作）
KEEP_REWORDED = (
    ("原因はキャッシュではなく、DNSの設定でした。", "キャッシュではなく、DNSの設定が原因でした。"),
    ("怒っているのではなく、心配しているだけです。", "怒ってはいません。心配しているだけです。"),
    ("仮説では書き込みが遅いと考えていたが、実際は読み込みが遅かった。", "書き込みが遅いと考えていたが、測ると読み込みのほうが遅かった。"),
)
FIX = ("渡すのは判断ではなく、項目です。", "渡すのは項目です。")
DETECT = ("共通化ではなく、障害時の切り分けを速くするために導入しました。", "共通化と障害時の切り分けの迅速化を目的に導入しました。")
DETECT_MESSAGE = "原文で否定されていた『共通化』が、推敲後は否定のない文に出ています。主張が逆になっていないか確かめてください。"

# 試作の合成の組から取った。残す・正しく直す例を、逆転の例より多くする
REVERSED = (
    ("今回の改修は速度改善ではなく、保守のしやすさを狙ったものです。", "今回の改修は、速度改善と保守のしやすさを狙いとしたものです。", "速度改善"),
    ("重要なのはテストの数ではなく、落ちたときに原因がわかることです。", "重要なのは、テストの数と、落ちたときに原因がわかることです。", "テスト"),
    ("移行の目的は新機能ではなく、古いライブラリの脆弱性をなくすことです。", "移行の目的は、新機能の追加と古いライブラリの脆弱性の解消です。", "新機能"),
    ("会議を減らした狙いは時間の節約ではなく、決める人をはっきりさせることでした。", "会議を減らした狙いは、時間の節約と、決める人の明確化でした。", "時間"),
    ("このPRは性能の改善ではなく、読みやすさのための整理です。", "このPRの目的は、性能の改善と読みやすさのための整理です。", "性能"),
    ("共通化ではない。障害時の切り分けを速くするために導入した。", "共通化と、障害時の切り分けを速くすることが目的だ。", "共通化"),
    ("優先するのは機能の追加ではなく、既存の不具合の修正です。", "最優先は機能の追加で、あわせて既存の不具合も修正します。", "機能"),
    ("大事なのはコストの削減ではなく、作業の安全です。", "コストの削減と作業の安全が大事です。", "コスト"),
)
CORRECT = (
    ("原因はキャッシュではなく、DNSの設定でした。", "最初はキャッシュを疑いましたが、原因はDNSの設定でした。"),
    ("原因はキャッシュではなく、DNSの設定でした。", "まずキャッシュを疑いましたが、原因はDNSの設定でした。"),
    ("共通化ではなく、障害時の切り分けを速くするために導入しました。", "導入の目的は共通化ではなく、障害時の切り分けを速くすることです。"),
    ("共通化ではなく、障害時の切り分けを速くするために導入しました。", "共通化は目的にしていません。障害時の切り分けを速くするために導入しました。"),
    ("共通化ではなく、障害時の切り分けを速くするために導入しました。", "障害時の切り分けを速くすることが目的です。"),
    ("共通化ではなく、障害時の切り分けを速くするために導入しました。", "共通化よりも、障害時の切り分けの速さを重視しました。"),
    ("共通化ではなく、障害時の切り分けを速くするために導入しました。", "共通化は二の次で、目的は障害時の切り分けを速くすることです。"),
    ("共通化ではなく、障害時の切り分けを速くするために導入しました。", "共通化もできますが、目的は障害時の切り分けを速くすることです。"),
    ("重要なのはテストの数ではなく、落ちたときに原因がわかることです。", "テストの数より、落ちたときに原因がわかることのほうが重要です。"),
    ("目指すのはコスト削減ではなく、障害時の復旧時間を短くすることです。", "目指すのは、障害時の復旧時間を短くすることです。コスト削減は狙っていません。"),
    ("優先するのは機能の追加ではなく、既存の不具合の修正です。", "機能の追加より先に、既存の不具合を直すことを優先します。"),
    ("遅いのはデータベースではなく、外部APIの呼び出しでした。", "まずデータベースが遅いと考えましたが、計測すると外部APIの呼び出しが遅れていました。"),
    ("散歩は運動じゃない、考えごとの時間です。", "散歩は運動というより、考えごとの時間です。"),
    ("書き込みではなく、読み込みが遅かった。", "書き込みが遅いと思っていたが、遅かったのは読み込みだった。"),
    # 試作の Check の段で足した形（打ち消しの「ず」、理由・条件の節）
    ("今回の目的は高速化ではなく、障害の切り分けを速くすることです。", "今回は高速化を狙わず障害の切り分けを速くすることを目的にしました。"),
    ("今回の目的は高速化ではなく、障害の切り分けを速くすることです。", "今回は高速化を狙わずに、障害の切り分けを速くすることを目的にしました。"),
    ("まだ本番環境ではないので、まず検証環境で試します。", "本番環境に出す前に、まず検証環境で試します。"),
    ("まだ正式版ではないため、まず社内の数人で試します。", "正式版を出す前に、まず社内の数人で試します。"),
    ("優先するのは見た目の統一ではなく、読み込みの速さです。", "見た目の統一は求めずに、読み込みの速さを優先します。"),
    ("本制度は、罰則ではなく、自主的な改善を促すことを目的とする。", "本制度は、罰則ではなく、自主的な改善を促すことを目的とする。"),
)


class ContrastReversalTest(unittest.TestCase):
    """追加文書 1.4、1.5: 原文の否定対比の名詞が、推敲後に否定のない文で重みの語と一緒に出たら候補にする。"""

    def test_keep_examples_unchanged_have_no_candidate(self):
        for text in KEEP_UNCHANGED:
            with self.subTest(text=text):
                result = diff(text, text)
                self.assertEqual(reversals(result), [])
                self.assertEqual(result["status"], "no_change")

    def test_keep_examples_reworded_have_no_candidate(self):
        for before, after in KEEP_REWORDED:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversals(diff(before, after)), [])

    def test_fix_example_has_no_candidate(self):
        self.assertEqual(reversals(diff(*FIX)), [])

    def test_detect_example(self):
        result = diff(*DETECT)
        [risk] = reversals(result)
        self.assertEqual(set(risk), RISK_KEYS)
        self.assertIsNone(risk["subkind"])
        self.assertIsNone(risk["basis"])
        self.assertEqual((risk["old_line"], risk["new_line"]), (1, 1))
        self.assertEqual((risk["old"], risk["new"]), DETECT)
        self.assertEqual(risk["detail"]["word"], "共通化")
        report = yomiyasu_diff.report(result).split("\n")
        index = report.index("- 否定対比の主張が逆になった恐れ（1行目）: " + DETECT_MESSAGE)
        self.assertEqual(report[index + 1:index + 3], ["  元: " + DETECT[0], "  後: " + DETECT[1]])

    def test_keep_examples_outnumber_detect_examples(self):
        """追加文書 1.5: 残す例の数は、直す例と同じかそれ以上。"""
        keep = len(KEEP_UNCHANGED) + len(KEEP_REWORDED) + len(CORRECT) + 1
        self.assertGreaterEqual(keep, len(REVERSED) + 1)

    def test_reversed_pairs_are_found(self):
        for before, after, word in REVERSED:
            with self.subTest(before=before):
                found = reversals(diff(before, after))
                self.assertTrue(found, "逆転の候補が出る")
                self.assertIn(word, [risk["detail"]["word"] for risk in found])

    def test_correct_pairs_are_not_found(self):
        for before, after in CORRECT:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversals(diff(before, after)), [])

    def test_not_counted_for_fail_on(self):
        """否定対比の逆転は意味が変わる恐れの節に出て meaning_risk_count に入るが、--fail-on=meaning-risk には数えない。"""
        result = diff(*DETECT)
        kinds = [risk["kind"] for risk in result["meaning_risks"]]
        self.assertIn("contrast_reversal", kinds)
        self.assertEqual(result["meaning_risk_count"], len(result["meaning_risks"]))
        counted = [kind for kind in kinds if kind in yomiyasu_diff.FAIL_ON_KINDS]
        self.assertEqual(result["fail_on_meaning_risk_count"], len(counted))
        self.assertNotIn("contrast_reversal", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertEqual(result["status"], "has_candidates")

    def test_cli_fail_on_ignores_reversal(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a.md", Path(folder) / "b.md"
            a.write_text(DETECT[0] + "\n", encoding="utf-8")
            b.write_text(DETECT[1] + "\n", encoding="utf-8")
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "--fail-on=meaning-risk",
                                      str(a), str(b)], capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        result = yomiyasu_diff.diff(DETECT[0] + "\n", DETECT[1] + "\n")
        expected = 1 if result["fail_on_meaning_risk_count"] else 0
        self.assertEqual(process.returncode, expected, process.stdout.decode("utf-8") + process.stderr.decode("utf-8"))


# ---- 追加文書 2.5 の表 ----

STIFF_DETECT_1 = ("ログを見れば、時間を溶かさずに原因がわかります。", "ログの参照により、迅速な原因究明が可能です。")
STIFF_DETECT_2 = ("申請の手順を減らせないか、総務部で検討します。", "申請手続き簡素化の検討の実施。")
STIFF_NONE_1 = ("申請の手順を減らせないか、総務部で検討します。", "申請の手順を減らせないか、総務部が検討します。")
STIFF_NONE_2 = ("本規程は、令和8年4月1日から施行する。", "本規程は、令和8年4月1日から施行する。")

# 試作の Check の段の、短い文書で前置きや外枠を消すだけの正しい推敲（出ないのが正しい）
STIFF_OK = (
    ("新しい勤怠システムでは、スマートフォンからでも打刻をすることができるようになります。外出先からでも簡単に打刻を"
     "することができますので、ぜひ活用してみてください。",
     "新しい勤怠システムでは、スマートフォンからも打刻できます。外出先からも打刻できるので、使ってみてください。"),
    ("このバグのせいで、丸一日を溶かしてしまいました。原因は設定ファイルの書き間違いでした。",
     "このバグの調査で、丸一日かかってしまいました。原因は設定ファイルの書き間違いでした。"),
    ("今回はキャッシュの設定で応答時間を半分にした話を紹介しました。いかがでしたでしょうか。ぜひ皆さんも試してみてくださいね。",
     "今回はキャッシュの設定で応答時間を半分にした話を紹介しました。"),
    ("このAPIは、リクエストを受け取ったら、まず認証を行うようになっています。認証に失敗した場合は、401を返すようになっています。",
     "このAPIは、リクエストを受け取ると、まず認証します。認証に失敗したら、401を返します。"),
    ("ここで重要なのは、キャッシュの有効期限をきちんと決めておくということです。", "キャッシュの有効期限をきちんと決めておくことが重要です。"),
    ("そんなこんなで、気がつけばもう三年も走り続けているのである。", "気がつけば、もう三年も走り続けている。"),
)
# 硬くした推敲（出るのが正しい）
STIFF_HIT = (
    ("設定を見直せば、待ち時間を減らせます。", "設定の見直しにより、待ち時間の削減が可能です。"),
    ("申請の手間を減らせないか、総務部で考えています。決まったら、またお知らせします。",
     "申請手続きの簡素化に関して、総務部において検討を実施しています。決定後、改めて周知を行います。"),
    ("コーヒーを飲むと、やっと目が覚めた気がした。窓の外では、雨が上がりかけていた。",
     "コーヒーの摂取により、ようやく覚醒した感覚を得た。窓外では、降雨が終息しつつあった。"),
    ("休むときは、前の日までに上司に伝えてください。", "休暇取得時は、前日までに上長への報告を行ってください。"),
    ("テストが落ちていたので直しました。", "テスト失敗事象の修正を実施しました。"),
)


class StiffnessTest(unittest.TestCase):
    """追加文書 2.2〜2.5: 推敲で漢字の割合、名詞化の言い回し、「の」の連続が増えたら候補にする（見直し候補だけ）。"""

    def stiffness(self, before, after, **options):
        result = diff(before, after, **options)
        self.assertIn("stiffness", result)
        return result, result["stiffness"]

    def test_detect_examples(self):
        for before, after in (STIFF_DETECT_1, STIFF_DETECT_2):
            with self.subTest(before=before):
                result, stiff = self.stiffness(before, after)
                self.assertGreaterEqual(stiff["candidate_count"], 1)
                self.assertEqual(stiff["candidate_count"], len(stiff["candidates"]))
                self.assertEqual(stiff["level"], "review")
                for candidate in stiff["candidates"]:
                    self.assertEqual(set(candidate), STIFF_KEYS)
                    self.assertEqual(candidate["kind"], "stiffness")
                    self.assertEqual(candidate["level"], "review")

    def test_detect_example_1_is_a_sentence_candidate(self):
        """2.5 の例1は、文全体の書き換えで1文の候補になる（試作の決め直した数値。最初の数値では出ない）。"""
        result, stiff = self.stiffness(*STIFF_DETECT_1)
        self.assertEqual([c["subkind"] for c in stiff["candidates"]], ["sentence"])
        report = yomiyasu_diff.report(result)
        self.assertIn("■ 文体の硬化（見直し候補 1件", report)
        self.assertIn("1行目の文で、漢字の割合が27%から50%に増えました（24字→22字）。硬い言い方に寄っていないか確かめてください。",
                      report)

    def test_detect_example_2_is_a_no_chain_candidate(self):
        result, stiff = self.stiffness(*STIFF_DETECT_2)
        self.assertIn("no_chain", [c["subkind"] for c in stiff["candidates"]])
        [chain] = [c for c in stiff["candidates"] if c["subkind"] == "no_chain"]
        self.assertEqual(chain["detail"]["chains"], ["申請手続き簡素化の検討の実施"])

    def test_no_candidate_examples(self):
        for before, after in (STIFF_NONE_1, STIFF_NONE_2):
            with self.subTest(before=before):
                result, stiff = self.stiffness(before, after)
                self.assertEqual(stiff["candidates"], [])
                self.assertEqual(stiff["candidate_count"], 0)
                self.assertNotIn("■ 文体の硬化", yomiyasu_diff.report(result))

    def test_short_correct_rewrites_have_no_candidate(self):
        for before, after in STIFF_OK:
            with self.subTest(before=before):
                self.assertEqual(self.stiffness(before, after)[1]["candidates"], [])

    def test_stiff_rewrites_are_found(self):
        for before, after in STIFF_HIT:
            with self.subTest(before=before):
                self.assertTrue(self.stiffness(before, after)[1]["candidates"])

    def test_formal_makes_candidates_info(self):
        """D-4: 文書の種類が formal なら、同じ条件の候補を参考（level info）としてだけ出す。"""
        for before, after in (STIFF_DETECT_1, STIFF_DETECT_2):
            with self.subTest(before=before):
                result, stiff = self.stiffness(before, after, doc_type="formal")
                self.assertEqual(stiff["level"], "info")
                self.assertTrue(stiff["candidates"])
                self.assertEqual({c["level"] for c in stiff["candidates"]}, {"info"})
                report = yomiyasu_diff.report(result)
                self.assertIn("■ 文体の硬化（参考 ", report)

    def test_other_doc_types_keep_review(self):
        # incident は diff の詰めの直し（反証で見つけた例）で参考の種類に移した
        # （試験は test_v200_tone_stiffness_refine.IncidentStiffnessTest）
        for value in ("pr", "article", "proposal", "minutes", "manual", "slides", "essay", "promo"):
            with self.subTest(doc_type=value):
                self.assertEqual(self.stiffness(*STIFF_DETECT_1, doc_type=value)[1]["level"], "review")

    def test_not_counted_in_candidates_status_or_fail_on(self):
        """硬化の検査は見直し候補を出すだけ。candidate_count、状態の行、--fail-on、meaning_risks には入れない（2.4）。"""
        before, after = STIFF_NONE_1[0], STIFF_DETECT_1[1]
        result = diff(*STIFF_DETECT_1)
        base = diff(STIFF_DETECT_1[0], STIFF_DETECT_1[1])
        self.assertEqual(result["candidate_count"], base["candidate_count"])
        self.assertNotIn("stiffness", [risk["kind"] for risk in result["meaning_risks"]])
        self.assertEqual(result["fail_on_meaning_risk_count"],
                         sum(1 for risk in result["meaning_risks"] if risk["kind"] in yomiyasu_diff.FAIL_ON_KINDS))
        del before, after, base

    def test_metrics_are_recorded(self):
        result, stiff = self.stiffness(*STIFF_DETECT_1)
        for side in ("old", "new"):
            metrics = stiff["metrics"][side]
            for key in ("sentences", "chars", "avg_sentence_length", "kanji_ratio", "kanji", "nominalizations",
                        "nominalization_names", "no_chains"):
                self.assertIn(key, metrics)
        self.assertEqual(stiff["metrics"]["new"]["nominalizations"], 1)
        self.assertEqual(stiff["metrics"]["old"]["nominalizations"], 0)

    def test_only_increases_are_reported(self):
        """原文がもともと硬いだけなら出さない（2.4）。硬い原文を和らげた推敲でも出さない。"""
        result, stiff = self.stiffness(STIFF_HIT[0][1], STIFF_HIT[0][0])
        self.assertEqual(stiff["candidates"], [])

    def test_code_url_tables_and_headings_are_not_counted(self):
        before = "# 設定の手順\n\n設定を見直せば、待ち時間を減らせます。\n\n```\n申請手続き簡素化の検討の実施\n```\n"
        after = "# 設定見直し手順の概要の説明\n\n設定を見直せば、待ち時間を減らせます。\n\n```\n申請手続き簡素化の検討の実施を行う\n```\n"
        self.assertEqual(self.stiffness(before, after)[1]["candidates"], [])


class ListFileTest(unittest.TestCase):
    """名詞化の言い回しの一覧（追加文書 2.2 の3）。references/lists/ に置き、足し引きできる。なければ内蔵の一覧で動く。"""

    def test_list_files_exist_in_both_places_and_match_the_builtin_list(self):
        for base in (ROOT / "references" / "lists", PACKAGE / "references" / "lists"):
            with self.subTest(base=str(base)):
                path = base / "nominalization.txt"
                self.assertTrue(path.is_file())
                parsed = yomiyasu_diff.parse_list(path.read_text(encoding="utf-8"), pattern=True)
                self.assertEqual(parsed, list(yomiyasu_diff.BUILTIN_LISTS["nominalization"]))

    def test_diff_reports_which_list_it_used(self):
        result = diff(*STIFF_DETECT_1)
        self.assertEqual(result["stiffness"]["list"], "references/lists/nominalization.txt")

    def test_diff_works_without_the_references_folder(self):
        """配布 ZIP に一覧がない場合: scripts だけを一時フォルダに写して動かすと、内蔵の一覧で同じ候補を出す。"""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scripts"
            target.mkdir()
            for name in ("yomiyasu_diff.py", "markdown_visibility.py", "yomiyasu_lint.py"):
                shutil.copy(str(SCRIPTS / name), str(target / name))
            a, b = Path(folder) / "a.md", Path(folder) / "b.md"
            a.write_text(STIFF_DETECT_1[0] + "\n", encoding="utf-8")
            b.write_text(STIFF_DETECT_1[1] + "\n", encoding="utf-8")
            process = subprocess.run([sys.executable, "-B", str(target / "yomiyasu_diff.py"), "--json", str(a), str(b)],
                                     capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
            outside = json.loads(process.stdout.decode("utf-8"))
        inside = diff(*STIFF_DETECT_1)
        self.assertEqual(outside["stiffness"]["list"], "builtin")
        self.assertEqual(outside["stiffness"]["candidates"], inside["stiffness"]["candidates"])

    def test_broken_list_file_falls_back_to_the_builtin_list(self):
        """一覧のファイルが壊れていても（正規表現の誤り）、止まらずに内蔵の一覧で動く。"""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scripts"
            lists = Path(folder) / "references" / "lists"
            target.mkdir()
            lists.mkdir(parents=True)
            for name in ("yomiyasu_diff.py", "markdown_visibility.py", "yomiyasu_lint.py"):
                shutil.copy(str(SCRIPTS / name), str(target / name))
            (lists / "nominalization.txt").write_text("壊れた\t(?:\n", encoding="utf-8")
            a, b = Path(folder) / "a.md", Path(folder) / "b.md"
            a.write_text(STIFF_DETECT_1[0] + "\n", encoding="utf-8")
            b.write_text(STIFF_DETECT_1[1] + "\n", encoding="utf-8")
            process = subprocess.run([sys.executable, "-B", str(target / "yomiyasu_diff.py"), "--json", str(a), str(b)],
                                     capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
            self.assertEqual(json.loads(process.stdout.decode("utf-8"))["stiffness"]["list"], "builtin")


class JsonAndReportTest(unittest.TestCase):
    def test_new_keys_are_added_after_full_diff(self):
        """新しい出力は追加の項目。既存のキーの順は変えず、full_diff のあとに stiffness と tone を足す。
        diff の詰めの直し（反証で見つけた例）で、気持ちの語の一覧の出どころ（feeling）を最後に足した。"""
        keys = list(diff(*DETECT))
        self.assertEqual(keys[-7:], ["full_diff", "stiffness", "tone", "feeling", "hedges", "immutable", "politeness"])

    def test_report_sections_only_when_there_are_candidates(self):
        report = yomiyasu_diff.report(diff("保存期間は3日です。", "保存期間は30日です。"))
        self.assertNotIn("■ 文体の硬化", report)
        self.assertNotIn("■ 勢い", report)

    def test_report_parts_has_the_new_sections(self):
        parts = yomiyasu_diff.report_parts(diff(*STIFF_DETECT_1))
        self.assertTrue(parts["stiffness"].startswith("■ 文体の硬化（"))
        self.assertEqual(parts["tone"], "")
        for key in ("risks", "rules", "full_diff"):
            self.assertIn(key, parts)


class PerformanceTest(unittest.TestCase):
    """2.11 の約束（6万字の全面書き換えで3秒未満）を、2つの検査を足しても守る（追加文書 3章の処理時間）。"""

    def test_sixty_thousand_characters(self):
        paragraph_old = ("ログを見れば、時間を溶かさずに原因がわかります。共通化ではなく、障害時の切り分けを速くするために導入しました。"
                         "設定を見直せば、待ち時間を減らせます。今回の目的は本当に大事です！")
        paragraph_new = ("ログの参照により、迅速な原因究明が可能です。共通化と障害時の切り分けの迅速化を目的に導入しました。"
                         "設定の見直しにより、待ち時間の削減が可能です。今回の目的は大事です。")
        count = 60000 // len(paragraph_old) + 1
        before = "\n\n".join("{}。{}".format(index, paragraph_old) for index in range(count)) + "\n"
        after = "\n\n".join("{}。{}".format(index, paragraph_new) for index in range(count)) + "\n"
        self.assertGreater(len(before), 60000)
        sides = yomiyasu_diff._Sides(before, after)
        started = time.perf_counter()
        full = yomiyasu_diff.full_diff(before, after)
        yomiyasu_diff.meaning_risks(before, after, full=full)
        yomiyasu_diff.stiffness(before, after)
        yomiyasu_diff.tone(before, after)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 3.0)
        del sides


if __name__ == "__main__":
    unittest.main()
