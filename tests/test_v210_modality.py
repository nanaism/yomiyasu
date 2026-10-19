#!/usr/bin/env python3
"""v2.1.0: diff の許可・能力・保証の言い方の検査と、文書の種類で数える確度の強まりの試験。

お願いの表の行（種類なしと formal）、文を分けたときの再現、正しい直し3種（出さない）、今までも止めていた行（敬体の保証、
許可から義務）が止まったままであることを確かめる。検出すべき例と検出してはいけない例は、このファイルで作った合成の文。
表の行のうち3行（この値は管理者…、設定を変えても…、この処理は再実行…）も、確かめるために作った文。
"""

from pathlib import Path
from unittest import mock
import importlib.util
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


PERMISSION_LOST = [("modality", "permission_lost")]
# (名前, 元の文, 書き直した文, 種類なしで出る候補, formal で出る候補, 種類なしの --fail-on の数, formal の数)
TABLE = [
    ("許可→能力1", "同じ Pull Request に含めてよい。", "同じ Pull Request に含められる。", PERMISSION_LOST, PERMISSION_LOST, 1, 1),
    ("許可→能力2", "安全で元に戻せる小さな判断は、仮定を明示して進めてよい。",
     "安全で元に戻せる小さな判断は、仮定を明示して進められる。", PERMISSION_LOST, PERMISSION_LOST, 1, 1),
    ("許可→能力3", "この値は管理者だけが変更してよい。", "この値は管理者だけが変更できる。", PERMISSION_LOST, PERMISSION_LOST, 1, 1),
    ("許可→説明", "`accepted` は、この成果物を公開または完了判断に進めてよいことを表す。",
     "`accepted` は、この成果物を公開または完了判断に進めることを表す。", PERMISSION_LOST, PERMISSION_LOST, 1, 1),
    ("許可→言い切り", "この値は管理者が変更してもよい。", "この値は管理者が変更する。", PERMISSION_LOST, PERMISSION_LOST, 1, 1),
    ("能力→言い切り", "ほかの完了条件を満たしていればTaskを完了できます。", "ほかの完了条件を満たしていればTaskを完了します。",
     [("modality_review", "ability_lost")], [("modality", "ability_lost")], 0, 1),
    ("可能性→言い切り", "同じ文字列でも記録の種類が違う場合がある。", "同じ文字列でも記録の種類が違う。",
     [("certainty_review", "strengthened")], [("certainty", "strengthened")], 0, 1),
    ("説明→必ず", "どのArtifactを対象にしているかを照合する。", "どのArtifactを対象にしているかを必ず照合する。",
     [("certainty_review", "strengthened")], [("certainty", "strengthened")], 0, 1),
    ("説明→保証（敬体）", "実行してよいものだけを実行へ渡します。", "実行してよいものだけが実行されることを保証します。",
     [("promise", "guarantee")], [("promise", "guarantee")], 1, 1),
    ("説明→保証（常体）1", "両方を通過した値だけを実行へ渡す。", "両方を通過した値だけを実行へ渡すことで、安全な実行を保証する。",
     [("promise", "guarantee")], [("promise", "guarantee")], 1, 1),
    ("説明→保証（常体）2", "設定を変えても結果は変わらない。", "設定を変えても結果が変わらないことを保証する。",
     [("promise", "guarantee")], [("promise", "guarantee")], 1, 1),
    ("説明→保証（否定の言い切り）", "秘密情報を含む可能性のある設定ファイル全文は複製しません。",
     "設定ファイル全文は複製しないため、秘密情報が漏れることはありません。", [("promise", "guarantee")], [("promise", "guarantee")], 1, 1),
    ("許可→義務", "この処理は再実行してよい。", "この処理は再実行しなければならない。",
     [("sentence_type", "marks")], [("sentence_type", "marks")], 1, 1),
    ("文を分けた再現", "レビューは任意です。監督Codexはレビュー証拠なしに成果物を判断し、ほかの完了条件を満たしていればTaskを完了できます。",
     "レビューは任意です。監督Codexはレビュー証拠がなくても成果物を判断できます。ほかの完了条件を満たしていれば、Taskを必ず完了します。",
     [("certainty_review", "strengthened")], [("certainty", "strengthened")], 0, 1),
    ("分けない", "レビューは任意です。監督Codexはレビュー証拠なしに成果物を判断し、ほかの完了条件を満たしていればTaskを完了できます。",
     "レビューは任意です。監督Codexはレビュー証拠なしに成果物を判断し、ほかの完了条件を満たしていればTaskを必ず完了します。",
     [("certainty_review", "strengthened"), ("modality_review", "ability_lost")],
     [("certainty", "strengthened"), ("modality", "ability_lost")], 0, 2),
    # 正しい直し（意味の恐れに出さない）
    ("外枠を外す", "この値は管理者が変更することができる。", "この値は管理者が変更できる。", [], [], 0, 0),
    ("同じ許可の言い換え", "この値は管理者が変更してもよい。", "この値は管理者が変更してよい。", [], [], 0, 0),
    ("同じ許可が残る", "この値は、管理者が必要に応じて変更してよい。", "必要に応じて、管理者がこの値を変更してよい。", [], [], 0, 0),
]

# 検出すべき例（合成の文）: (元, 後, 種類なしの (kind, subkind) の並び, modality の (from, to))
SHOULD_DETECT = [
    ("この欄は空のままでも差し支えない。", "この欄は空のままにできる。", [("modality", "permission_lost")], ("許可", "能力")),
    ("結果は翌日に確認しても構いません。", "結果は翌日に確認します。", [("modality", "permission_lost")], ("許可", "断定")),
    ("古い設定は削除する。", "古い設定は削除してもよい。", [("modality", "permission_added")], ("断定", "許可")),
    ("管理者は設定を変更できる。", "管理者は設定を変更してよい。", [("modality", "permission_added")], ("能力", "許可")),
    ("この欄は空欄でもよい。", "この欄は入力を必須とする。", [("modality", "permission_lost")], ("許可", "義務")),
    ("失敗したら再試行してよい。", "失敗したら必ず再試行する。",
     [("certainty_review", "strengthened"), ("modality", "permission_lost")], ("許可", "保証")),
    ("管理者だけに書き込みを許可する。", "管理者だけが書き込む。", [("modality", "permission_lost")], ("許可", "断定")),
    # 1文を2文に分けても、同じ範囲で比べる
    ("設定を読み込み、値を検証できる。", "設定を読み込む。値を検証する。", [("modality_review", "ability_lost")], ("能力", "断定")),
    # 常体の受身の保証
    ("結果の順序は入力の順と同じになる。", "結果の順序は入力の順と同じになることが保証される。", [("promise", "guarantee")], None),
]

# 検出してはいけない例（合成の文）。種類なしでも formal でも、許可・能力・約束・確度の数える候補を出さない。
SHOULD_NOT_DETECT = [
    # もとの否定の言い切りを「ことはない」に言い換えただけ
    ("再投入しても二重反映は起きない。", "再投入しても二重に反映されることはない。"),
    # 「ケースが出ます」を「ことがあります」に言い換えただけ
    ("片方だけ成功するケースが出ます。", "片方だけ成功することがあります。"),
    # 名詞の句を動詞に開いたときの「できる」「られる」（能力が増えただけは出さない）
    ("リストア確認を行います。", "リストアできることを確認します。"),
    ("旧系統は切り替え用に残しておく。", "旧系統は切り替えられるように残しておく。"),
    # 受身の「られ」
    ("通知が消える。", "通知が送られない。"),
    # 名詞の「保証」、「保証することも」、「保証できる」は保証の足しにしない
    ("冪等性の確認は難しい。", "冪等性を保証することも難しい。"),
    ("配信の確実さを高める。", "配信保証を高める。"),
    ("整合性を確かめられる。", "整合性を保証できる。"),
    # 能力の弱い印が強い印の消えを吸う、同じ許可の言い換え
    ("この関数は設定を使うことができる。", "この関数は設定を使える。"),
    ("この値は変更してもよい。", "この値は変更して構わない。"),
    # 許可から外す形（勧めの「とよい」「ばよい」、「と言ってもよい」、名詞のあとの「でよい」、「とても」「にとって」「極めて」）
    ("設定を見直すとよい。", "設定を見直す。"),
    ("再起動すればよい。", "再起動する。"),
    ("これは事実上の標準と言ってもよい。", "これは事実上の標準だ。"),
    ("設定はこれでよい。", "設定はこれで正しい。"),
    ("この案はとてもよい。", "この案は優れている。"),
    ("ユーザーにとってよい設計にする。", "ユーザーに合う設計にする。"),
    ("極めてよい結果が出た。", "よい結果が出た。"),
    # 能力から外す形と、過去・打ち消しの形の言い換え
    ("できるだけ早く返す。", "早く返す。"),
    ("一部の利用者がサービスを利用できない状態が続いた。", "一部の利用者がサービスを利用できなかった。"),
    ("準備ができた。", "準備が整った。"),
    # 決まりを言う文の「必須にする」を「必ず実施する」にした（formal でも数えない）
    ("負荷試験を必須にする。", "負荷試験を必ず実施する。"),
    # 弱める向きは数えない
    ("同じ値でも結果が違う。", "同じ値でも結果が違う場合がある。"),
]

COUNTED_KINDS = ("modality", "promise", "certainty")


def kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"]]


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


class RequestTableTest(unittest.TestCase):
    """お願いの表の行と文を分けたときの再現を、1文どうし（または2〜3文どうし）で比べる。"""

    def test_table_without_doc_type_and_formal(self):
        for name, before, after, plain, formal, plain_count, formal_count in TABLE:
            for doc_type, expected, count in ((None, plain, plain_count), ("formal", formal, formal_count)):
                with self.subTest(row=name, doc_type=doc_type):
                    result = run(before, after, doc_type)
                    self.assertEqual(kinds(result), expected)
                    self.assertEqual(result["fail_on_meaning_risk_count"], count)

    def test_permission_detail(self):
        result = run("同じ Pull Request に含めてよい。", "同じ Pull Request に含められる。")
        self.assertEqual(result["meaning_risks"][0]["detail"], {
            "lost": [{"kind": "許可", "hits": ["てよい"]}], "added": [{"kind": "能力（弱い印）", "hits": ["られる"]}],
            "from": "許可", "to": "能力"})
        self.assertEqual((result["meaning_risks"][0]["old_line"], result["meaning_risks"][0]["new_line"]), (1, 1))
        result = run("この値は管理者が変更してもよい。", "この値は管理者が変更する。")
        self.assertEqual(result["meaning_risks"][0]["detail"]["to"], "断定")

    def test_counted_steps_name_the_doc_type(self):
        """formal で数えた確度の段にだけ counted_by を付ける。種類なしでは付けない。"""
        for before, after in (("同じ文字列でも記録の種類が違う場合がある。", "同じ文字列でも記録の種類が違う。"),
                              ("どのArtifactを対象にしているかを照合する。", "どのArtifactを対象にしているかを必ず照合する。")):
            with self.subTest(before=before):
                step = run(before, after, "formal")["meaning_risks"][0]["detail"]["steps"][0]
                self.assertEqual((step["counted"], step["counted_by"]), (True, "doc_type"))
                step = run(before, after)["meaning_risks"][0]["detail"]["steps"][0]
                self.assertFalse(step["counted"])
                self.assertNotIn("counted_by", step)
        # もとから数える段（見込み → 断定）には付けない
        step = run("明日届く見込みです。", "明日届きます。", "formal")["meaning_risks"][0]["detail"]["steps"][0]
        self.assertTrue(step["counted"])
        self.assertNotIn("counted_by", step)

    def test_counted_doc_types(self):
        """事実や仕様を述べる種類だけが数え方を変える。essay、promo、mail、minutes、slides は種類なしと同じ。"""
        self.assertEqual(yomiyasu_diff.COUNTED_TYPES, ("pr", "article", "incident", "proposal", "manual", "formal", "paper"))
        before, after = "同じ文字列でも記録の種類が違う場合がある。", "同じ文字列でも記録の種類が違う。"
        for doc_type in yomiyasu_diff.COUNTED_TYPES:
            self.assertEqual(run(before, after, doc_type)["fail_on_meaning_risk_count"], 1, doc_type)
        for doc_type in ("essay", "promo", "mail", "minutes", "slides"):
            self.assertEqual(run(before, after, doc_type)["fail_on_meaning_risk_count"], 0, doc_type)

    def test_split_sentence_compares_the_split_part(self):
        """分けた先の文の「必ず」を、元の文と比べる。元の文と字面の重ならない足した文の「必ず」は比べない。"""
        name, before, after = TABLE[13][:3]
        steps = run(before, after)["meaning_risks"][0]["detail"]["steps"]
        self.assertEqual([(s["from"], s["to"]) for s in steps], [("断定", "必ず")])
        result = run("設定を保存し、終了する。", "設定を保存して終了する。ログは必ず残す。", "formal")
        self.assertFalse([k for k in kinds(result) if k[0].startswith("certainty")], kinds(result))

    def test_cli_exit_codes(self):
        rows = [row for row in TABLE if row[0] in ("許可→能力3", "能力→言い切り", "可能性→言い切り", "文を分けた再現", "外枠を外す")]
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old.md", Path(folder) / "new.md"
            for name, before, after, _, _, plain_count, formal_count in rows:
                old.write_text(before + "\n", encoding="utf-8")
                new.write_text(after + "\n", encoding="utf-8")
                for flags, count in (([], plain_count), (["--doc-type", "formal"], formal_count)):
                    with self.subTest(row=name, flags=flags):
                        process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/yomiyasu_diff.py"), "--fail-on",
                                                  "meaning-risk"] + flags + [str(old), str(new)], capture_output=True, text=True,
                                                 encoding="utf-8")
                        self.assertEqual(process.returncode, 1 if count else 0, process.stdout + process.stderr)


class ExamplesTest(unittest.TestCase):
    def test_should_detect(self):
        for before, after, expected, names in SHOULD_DETECT:
            with self.subTest(before=before):
                result = run(before, after)
                self.assertEqual(kinds(result), expected)
                modality = [r for r in result["meaning_risks"] if r["kind"].startswith("modality")]
                if names:
                    self.assertEqual((modality[0]["detail"]["from"], modality[0]["detail"]["to"]), names)

    def test_should_not_detect(self):
        for before, after in SHOULD_NOT_DETECT:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, doc_type=doc_type):
                    result = run(before, after, doc_type)
                    found = [k for k in kinds(result) if k[0] in COUNTED_KINDS or k[0] == "modality_review"]
                    self.assertEqual(found, [])

    def test_permission_to_prohibition_stays_a_sentence_type_mark(self):
        """依頼・決まりの印が動いた範囲は、文の種類の印の候補に任せる（許可・能力の候補を重ねない）。"""
        result = run("ログを削除してよい。", "ログを削除してはいけない。")
        self.assertIn(("sentence_type", "marks"), kinds(result))
        self.assertFalse([k for k in kinds(result) if k[0].startswith("modality")])

    def test_ability_lost_is_counted_only_for_fact_documents(self):
        before, after = "設定を読み込み、値を検証できる。", "設定を読み込む。値を検証する。"
        self.assertEqual(run(before, after, "essay")["fail_on_meaning_risk_count"], 0)
        self.assertEqual(run(before, after, "manual")["fail_on_meaning_risk_count"], 1)

    def test_human_lines(self):
        labels = (("同じ Pull Request に含めてよい。", "同じ Pull Request に含められる。", None,
                   "- 許可の言い方が消えた（1行目）: 許可（てよい） → 能力（られる）。"),
                  ("古い設定は削除する。", "古い設定は削除してもよい。", None,
                   "- 原文にない許可の言い方（1行目）: なし（断定） → 許可（てもよい）。"),
                  ("ほかの完了条件を満たしていればTaskを完了できます。", "ほかの完了条件を満たしていればTaskを完了します。", None,
                   "- 能力の言い方が消えた（1行目）: 能力（できます） → なし（断定）。--fail-on には数えません"),
                  ("ほかの完了条件を満たしていればTaskを完了できます。", "ほかの完了条件を満たしていればTaskを完了します。", "formal",
                   "- 能力の言い方が消えた（1行目）: 能力（できます） → なし（断定）。原文は「〜できる」"))
        for before, after, doc_type, label in labels:
            with self.subTest(label=label):
                self.assertIn(label, yomiyasu_diff.report(run(before, after, doc_type)))
        result = run("この値は管理者が変更してもよい。", "この値は管理者の値を3にする。")
        self.assertIn("・許可と能力", yomiyasu_diff._fail_on_line(len(result["meaning_risks"]) + 1,
                                                          yomiyasu_diff.fail_on_count(result["meaning_risks"]),
                                                          result["meaning_risks"]))


class ContractsTest(unittest.TestCase):
    def test_kinds_and_fail_on(self):
        self.assertIn("modality", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertNotIn("modality_review", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertLess(yomiyasu_diff._RISK_ORDER["promise_review"], yomiyasu_diff._RISK_ORDER["modality"])
        self.assertIn("modality_review", yomiyasu_diff._RISK_ORDER)

    def test_public_function_takes_doc_type(self):
        """meaning_risks() は doc_type を受け、確度の数え方を diff() とそろえる。許可・能力の候補は diff() だけが足す。"""
        before, after = "同じ文字列でも記録の種類が違う場合がある。\n", "同じ文字列でも記録の種類が違う。\n"
        found = yomiyasu_diff.meaning_risks(before, after, type_changes=[], doc_type="formal")
        self.assertEqual([(r["kind"], r["subkind"]) for r in found], [("certainty", "strengthened")])
        found = yomiyasu_diff.meaning_risks(before, after, type_changes=[])
        self.assertEqual([(r["kind"], r["subkind"]) for r in found], [("certainty_review", "strengthened")])
        with self.assertRaises(ValueError):
            yomiyasu_diff.meaning_risks(before, after, doc_type="unknown")
        with mock.patch.object(yomiyasu_diff, "_type_ranges", side_effect=AssertionError("範囲を作った")):
            found = yomiyasu_diff.meaning_risks("変更してよい。\n", "変更できる。\n", type_changes=[])
        self.assertFalse([r for r in found if r["kind"].startswith("modality")])

    def test_ranges_are_made_once_in_diff(self):
        """diff() は、文の種類の印の範囲を許可・能力の比べで作り直さない。"""
        before = "この値は変更してよい。外部APIは遅れるかもしれない。\n"
        after = "この値は変更できる。外部APIは遅れる。\n"
        with mock.patch.object(yomiyasu_diff, "_type_ranges", wraps=yomiyasu_diff._type_ranges) as ranges:
            result = yomiyasu_diff.diff(before, after)
        self.assertEqual(ranges.call_count, 1)
        self.assertIn(("modality", "permission_lost"), kinds(result))
        self.assertIn(("sentence_type", "marks"), kinds(result))
        # 文の種類の印がない文章では、許可・能力の比べのときだけ範囲を作る
        with mock.patch.object(yomiyasu_diff, "_type_ranges", wraps=yomiyasu_diff._type_ranges) as ranges:
            result = yomiyasu_diff.diff("この値は変更してよい。\n", "この値は変更できる。\n")
        self.assertEqual(ranges.call_count, 1)
        # 直前の範囲が別の文章のものなら使わずに作る（同じ結果）
        o, r = yomiyasu_diff.normalize(before), yomiyasu_diff.normalize(after)
        expected = yomiyasu_diff._modality_changes(o, r)
        yomiyasu_diff.diff("別の文です。\n", "別の文でした。\n")
        self.assertEqual(yomiyasu_diff._modality_changes(o, r), expected)

    def test_counted_doc_type_help_is_the_same_in_check(self):
        sentence = yomiyasu_diff._counted_doc_type_help()
        for doc_type in yomiyasu_diff.COUNTED_TYPES:
            self.assertIn(doc_type, sentence)
        spec = importlib.util.spec_from_file_location("yomiyasu_check_for_modality", ROOT / "scripts" / "yomiyasu_check.py")
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        parser, run_parser, verify = check._build_parser()
        helps = {action.dest: action.help for action in run_parser._actions}
        self.assertIn(sentence, helps["doc_type"])
        diff_helps = {action.dest: action.help for action in yomiyasu_diff._build_parser()._actions}
        self.assertIn(sentence, diff_helps["doc_type"])
        self.assertIn("許可の言い方", diff_helps["fail_on"])
        self.assertIn("許可の言い方", helps["fail_on"])

    def test_modality_on_a_long_document_is_fast(self):
        """許可・能力の比べ（印を探す所と範囲ごとの比べ）は、6万字の全面書き換えでも1秒未満。範囲は diff() で作ったものを使う。"""
        rows = ["第{}項の値は管理者が変更してよい。利用者は結果を確認できる。".format(n) for n in range(1900)]
        rewritten = ["第{}項の値は管理者が変更できる。利用者は結果を確認する。".format(n) for n in range(1900)]
        before, after = "\n".join(rows) + "\n", "\n".join(rewritten) + "\n"
        self.assertGreaterEqual(len(before), 60000)
        o, r = yomiyasu_diff.normalize(before), yomiyasu_diff.normalize(after)
        opcodes = yomiyasu_diff._ExactSequenceMatcher(None, o, r, autojunk=False).get_opcodes()
        yomiyasu_diff._type_changes(o, r, opcodes)
        durations = []
        for _ in range(3):
            start = time.perf_counter()
            found = yomiyasu_diff._modality_changes(o, r)
            durations.append(time.perf_counter() - start)
        self.assertEqual(len(found), 3800)
        self.assertLess(min(durations), 1.0, durations)


if __name__ == "__main__":
    unittest.main()
