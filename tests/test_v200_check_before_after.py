#!/usr/bin/env python3
"""check の前後表示（T1〜T20）。文は合成し、既存の検査と記録の不変も確かめる。"""
import ast
import json
from pathlib import Path
import sys
from unittest import mock
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v200_doc_type import DocTypeCase, yomiyasu_check as check
from test_v200_check import RECORD_KEYS, CHECK_KEYS

ROOT = Path(__file__).resolve().parent.parent
OLD = "保存期間は3日です。\n"
NEW = "保存期間は30日です。\n"
WARN = "ログを確認します。設定を変更します。結果を保存します。\n"
MEMO = "- 定例: 木曜 10:00〜\n- 議題: 予算、人員、来期の採用、備品の購入、席替え\n- 欠席: 山田（出張）\n"
COMPOSED = "来週の定例は木曜の10時からです。\n"
NOTE = "lint の規則に当たった数で、点数ではありません。増えても減っても読みやすさの良し悪しは示しません"
COMPOSE_NOTE = "新規作成なので原文の件数はありません。lint の規則に当たった数で、点数ではありません"


class BeforeAfterTest(DocTypeCase):
    def pair(self, old=OLD, new=NEW):
        return self.write("old.md", old), self.write("new.md", new)

    def run_pair(self, old=OLD, new=NEW, extra=()):
        a, b = self.pair(old, new)
        return self.check("run", "--source", a, "--final", b, *extra)

    def data_pair(self, old=OLD, new=NEW, extra=()):
        code, out, err = self.run_pair(old, new, ("--json",) + extra)
        self.assertEqual(err, "")
        return code, json.loads(out)

    def excerpt(self, old, new):
        ctx = check._Context()
        ctx.required = ["lint", "diff"]
        diff = check._diff_module()
        ctx.diff_result = diff.diff(old, new)
        blocks, summary = check._changed_places(ctx, diff, False)
        return blocks[0], summary

    def replace_result(self, name, value):
        wait = check._Children.wait
        def altered(children):
            results = wait(children)
            results[name] = value
            return results
        return mock.patch.object(check._Children, "wait", altered)

    def test_t01_counts_and_position(self):
        a, b = self.pair(WARN, NEW)
        code, out, err = self.check("run", "--source", a, "--final", b)
        self.assertEqual((code, err), (0, ""))
        _, lint, _ = self.lint("--json", a)
        n = json.loads(lint)["candidate_count"]
        lines = out.splitlines()
        index = self.record_index(lines)
        self.assertEqual(lines[index + 1:index + 5], ["硬化の検査: 候補なし", "勢いの検査: 候補なし",
                                                     "慎重表現の検査: 候補なし", "値の検査: 候補なし"])
        self.assertIn("lint（最終稿）候補0件", lines[2])
        self.assertEqual(lines[index + 5], "見直し候補: 原文 {}件 → 最終稿 0件（{}）".format(n, NOTE))

    def test_t02_headings_and_order(self):
        _, out, _ = self.run_pair(OLD + "\n確認済みです。\n", NEW + "\n確認中です。\n")
        lines = out.splitlines()
        index = self.record_index(lines)
        self.assertEqual(lines[index + 6:index + 8], ["", "■ 直した箇所（2か所。元と後）"])
        short = out.split("■ 直した箇所", 1)[1].split("\n\n", 1)[0]
        full = out.split("■ 全文差分（", 1)[1]
        self.assertEqual([s for s in short.splitlines() if s.startswith("@ ")],
                         [s for s in full.splitlines() if s.startswith("@ ")])
        self.assertIn("■ 全文差分（変更 2か所。省略していません）", out)

    def test_t03_existing_output_is_unchanged(self):
        normal = self.run_pair(extra=("--no-record",))
        with mock.patch.object(check, "_candidate_lines", return_value=[]):
            with mock.patch.object(check, "_changed_places", return_value=([], None)):
                without = self.run_pair(extra=("--no-record",))
        lines = normal[1].splitlines(keepends=True)
        index = next(i for i, line in enumerate(lines) if line.startswith("見直し候補:"))
        del lines[index]
        start = next(i for i, line in enumerate(lines) if line.startswith("■ 直した箇所"))
        end = next(i for i in range(start, len(lines)) if lines[i] == "\n")
        del lines[start:end + 1]
        self.assertEqual((normal[0], "".join(lines), normal[2]), without)

    def test_t04_status_footer_and_exit_codes(self):
        for final, extra, expected in ((NEW, (), 0), (WARN, ("--fail-on", "warn"), 1)):
            with self.subTest(expected=expected):
                code, out, _ = self.run_pair(new=final, extra=("--no-record",) + extra)
                lines = out.splitlines()
                self.assertEqual(code, expected)
                self.assertEqual(lines[-2:], lines[:2])
                self.assertEqual(sum(s.startswith("yomiyasu-check: ") for s in lines), 2)
        with self.replace_result("lint", ("timeout", None, None, "", 0, "時間切れ")):
            self.assertEqual(self.run_pair(extra=("--no-record",))[0], 3)

    def test_t05_source_arguments_and_same_deadline(self):
        start = check._Children.start
        calls = []
        def capture(children, name, command):
            calls.append((id(children), children.deadline, name, command))
            return start(children, name, command)
        with mock.patch.object(check._Children, "start", capture):
            _, data = self.data_pair(WARN, NEW, ("--doc-type", "minutes", "--reader", "expert"))
        _, out, _ = self.lint("--json", "--doc-type", "minutes", "--reader", "expert", self.root / "old.md")
        self.assertEqual(data["candidate_counts"]["source"], json.loads(out)["candidate_count"])
        self.assertEqual(len({(row[0], row[1]) for row in calls}), 1)
        commands = {row[2]: row[3] for row in calls}
        self.assertEqual(commands["lint"][:-1], commands["source_lint"][:-1])
        self.assertEqual(commands["source_lint"][:2], [sys.executable, "-B"])
        self.assertNotEqual(commands["source_lint"][-1], str(self.root / "old.md"))

    def test_t06_windows(self):
        self.assertEqual(check._window_text("あ" * 60, 20), ("…" + "あ" * 40, True))
        self.assertEqual(check._window_text("あ" * 60, 0), ("あ" * 60, False))
        self.assertEqual(check._window_text("あ" * 61, 0), ("あ" * 60 + "…", True))
        for prefix, expected in (("共通です。", 5), ("あ" * 42 + "、" + "い" * 8, 43), ("あ" * 50, 20),
                                 ("段落〔改行〕", 6), ("共通!?！？", 6)):
            with self.subTest(prefix=prefix):
                old, new = prefix + "旧" * 80, prefix + "新" * 80
                start = check._change_window_start(old, new)
                self.assertEqual(start, expected)
                for value in (old, new):
                    self.assertEqual(check._window_text(value, start), ("…" + value[start:start + 60] + "…", True))
        self.assertEqual(check._window_text("あ" * 58 + "〔改行〕" + "い" * 20, 0)[0], "あ" * 58 + "〔改行〕…")
        self.assertEqual(check._window_text("あ" * 18 + "〔改行〕" + "い" * 80, 20)[0], "…〔改行〕" + "い" * 58 + "…")
        self.assertEqual(check._window_text("あ" * 58 + "〔空行〕" + "い" * 20, 0)[0], "あ" * 58 + "〔空行〕…")
        self.assertEqual(check._window_text("あ" * 70, 20), ("…" + "あ" * 50, True))
        # 末尾の印を丸ごと含めて省略がなくなれば、60字超でも clipped は偽。
        old, new = "旧" * 57 + "〔空行〕", "新" * 57 + "〔空行〕"
        text, summary = self.excerpt(old, new)
        self.assertEqual(text.splitlines()[2:4], ["  元: " + old, "  後: " + new])
        self.assertFalse(summary["clipped"])
        self.assertNotIn("長い所は、", text)

    def test_t06_replace_one_short_side(self):
        prefix = "共通の説明です。"
        short, long = prefix + "旧" * (60 - len(prefix)), prefix + "新" * 70
        self.assertEqual(len(short), 60)
        for old, new in ((short, long), (long, short)):
            with self.subTest(old_length=len(old)):
                text, summary = self.excerpt(old, new)
                expected = ["  {}: …{}{}".format(label, value[len(prefix):len(prefix) + 60],
                                                "…" if len(value) > len(prefix) + 60 else "")
                            for label, value in (("元", old), ("後", new))]
                self.assertEqual(text.splitlines()[2:4], expected)
                self.assertEqual(summary, {"count": 1, "shown": 1, "omitted": 0, "clipped": True})
                self.assertIn("長い所は、", text)
                _, data = self.data_pair(old, new, ("--no-record",))
                self.assertEqual(data["changed_places"], summary)

    def test_t06_replace_both_short(self):
        prefix = "共通の説明です。"
        old, new = prefix + "旧" * (60 - len(prefix)), prefix + "新" * 20
        self.assertGreater(check._change_window_start(old, new), 0)
        text, summary = self.excerpt(old, new)
        self.assertEqual(text.splitlines()[2:4], ["  元: " + old, "  後: " + new])
        self.assertNotIn("…", text)
        self.assertNotIn("長い所は、", text)
        self.assertEqual(summary, {"count": 1, "shown": 1, "omitted": 0, "clipped": False})
        _, data = self.data_pair(old, new, ("--no-record",))
        self.assertEqual(data["changed_places"], summary)

    def test_t06_replace_start_inside_marker(self):
        # w が印の途中に来た場合も、両側の開始位置を一緒に広げる。
        for marker in ("〔改行〕", "〔空行〕"):
            for offset in (1, 2, 3):
                with self.subTest(marker=marker, offset=offset):
                    prefix = "あ" * 18 + marker + "い" * (26 + offset)
                    old, new = prefix + "旧", prefix + "新" * 80
                    with mock.patch.object(check, "_change_window_start", return_value=18 + offset):
                        text, summary = self.excerpt(old, new)
                    end = 18 + offset + 60
                    self.assertEqual(text.splitlines()[2:4], [
                        "  元: …" + old[18:], "  後: …" + new[18:end] + "…"])
                    self.assertTrue(summary["clipped"])
        # 片側だけに印があるときも、もう片側を同じ開始位置へ戻す。
        old, new = "あ" * 18 + "〔改行〕" + "旧" * 30, "あ" * 18 + "印の文字" + "新" * 80
        with mock.patch.object(check, "_change_window_start", return_value=20):
            text, summary = self.excerpt(old, new)
        self.assertEqual(text.splitlines()[2:4], ["  元: …" + old[18:], "  後: …" + new[18:80] + "…"])
        self.assertTrue(summary["clipped"])

    def test_t06_one_side_is_prefix_of_other(self):
        # 段落の最後に文を足した・消したとき、短い側が「…」だけにならず、最後の文から見える。
        head = "従来は、アクセストークンの期限切れを検知するたびに認可サーバーへリフレッシュ要求を送っていました。"
        last, added = "次のように責務を分けることを提案します。", "失敗したら3回まで再試行します。"
        for old, new in ((head + last, head + last + added), (head + last + added, head + last)):
            with self.subTest(old_length=len(old)):
                self.assertGreater(len(old + new), 120)
                text, summary = self.excerpt(old + "\n", new + "\n")
                self.assertEqual(text.splitlines()[2:4], ["  元: …" + old[len(head):], "  後: …" + new[len(head):]])
                self.assertTrue(summary["clipped"])
                self.assertIn("- 長い所は、変わり始めの少し前からおよそ60字だけを出しています（「…」は省いた所）。", text)
        # 短い側が読点で終わるときも空にしない
        old, new = "あ" * 70 + "、", "あ" * 70 + "、追加しました。"
        text, _ = self.excerpt(old + "\n", new + "\n")
        for row in text.splitlines()[2:4]:
            self.assertNotEqual(row.split(": ", 1)[1], "…")

    def test_t06_same_joined_text(self):
        # 本文の「〔改行〕」の字と本当の改行は、つなぐと同じ形になる。元と後を並べず、全文差分へ案内する。
        for old, new in (("説明は〔改行〕次の行です。\n", "説明は\n次の行です。\n"),
                         ("説明は〔改行〕" + "あ" * 70 + "\n", "説明は\n" + "あ" * 70 + "\n")):
            with self.subTest(length=len(old)):
                text, summary = self.excerpt(old, new)
                rows = text.splitlines()
                self.assertEqual(rows[2], "  （この形では元と後が同じに見えます。空行や「〔改行〕」の字の違いは、下の「■ 全文差分」で見られます）")
                self.assertFalse(any(row.startswith(("  元:", "  後:")) for row in rows))
                self.assertFalse(summary["clipped"])

    def test_t06_uneven_lines_note(self):
        text, _ = self.excerpt("**原因**\n設定の誤りでした。\n", "## 原因\n")
        self.assertIn("- 元と後で行の数が違う所は、別の段落どうしが並んでいることがあります。省いていない", text)
        for old, new in ((OLD, NEW), ("前の行\n元の行\n", "後の行\n次の行\n")):
            text, _ = self.excerpt(old, new)
            self.assertNotIn("行の数が違う", text)

    def test_t07_multiline_insert_delete(self):
        self.assertEqual(check._joined_lines([" 先頭\t", "", " \t", "次"]), " 先頭\t〔改行〕次")
        self.assertEqual(check._joined_lines(["", " \t"]), "〔空行〕")
        for old, new, present, absent in (("共通\n", "共通\n\n追加\n", "  後: 追加", "  元:"),
                                          ("共通\n\n削除\n", "共通\n", "  元: 削除", "  後:"),
                                          ("共通\n", "共通\n\n" + "追" * 61 + "\n", "  後: " + "追" * 60 + "…", "  元:"),
                                          ("共通\n\n" + "削" * 61 + "\n", "共通\n", "  元: " + "削" * 60 + "…", "  後:")):
            text, summary = self.excerpt(old, new)
            self.assertIn(present, text)
            self.assertNotIn(absent, text)
            self.assertEqual(summary["clipped"], present.endswith("…"))
        text, _ = self.excerpt("前の行\n元の行\n", "後の行\n次の行\n")
        self.assertIn("元: 前の行〔改行〕元の行", text)
        self.assertIn("後: 後の行〔改行〕次の行", text)
        text, _ = self.excerpt("", "追加\n")
        self.assertIn("  元: 〔空行〕", text)

    def test_t08_whitespace_only(self):
        text, summary = self.excerpt("保存 期間\n", "保存　期間\n")
        self.assertIn("  （空白だけの変更。下の「■ 全文差分」の「差:」で見られます）", text)
        self.assertNotIn("  元:", text)
        self.assertNotIn("  後:", text)
        self.assertFalse(summary["clipped"])

    def test_t09_ten_places(self):
        old = "\n\n".join("区間{}は旧です。".format(i) for i in range(13))
        new = old.replace("旧", "新")
        text, summary = self.excerpt(old, new)
        self.assertEqual(summary, {"count": 13, "shown": 10, "omitted": 3, "clipped": False})
        self.assertEqual(sum(s.startswith("@ ") for s in text.splitlines()), 10)
        self.assertIn("初めの10か所だけを出しました（ほか3か所）。", text)
        self.assertIn("区間9は新", text)
        self.assertNotIn("区間10は新", text)

    def test_t10_guide_record_name(self):
        for attempt in (1, 2):
            _, out, _ = self.run_pair()
            _, record = self.record(out.splitlines())
            entry = next(e for e in record["checks"] if e["name"] == "diff")
            filename = Path(entry["text"]).name
            self.assertEqual(filename, "attempt-{}.diff.txt".format(attempt))
            short = out.split("■ 直した箇所", 1)[1].split("\n\n", 1)[0]
            self.assertIn("記録と同じフォルダの {} にあります。".format(filename), short)
            self.assertNotIn("長い所は", short)
        _, out, _ = self.run_pair(extra=("--no-record",))
        self.assertIn('- 省いていない元と後は下の「■ 全文差分」にあります。', out)
        self.assertNotIn(".diff.txt", out)

    def test_t11_no_changes_and_encoding(self):
        _, out, _ = self.run_pair(OLD, OLD, ("--no-record",))
        self.assertIn("■ 直した箇所（0か所。元と後）\n- 原文から変わった箇所はありません。", out)
        self.assertIn("■ 全文差分: 変わった箇所はありません。", out)
        for new in (OLD.replace("\n", "\r\n"), "\ufeff" + OLD, OLD.rstrip("\n")):
            with self.subTest(new=new):
                _, out, _ = self.run_pair(OLD, new, ("--no-record",))
                self.assertIn("■ 直した箇所（0か所。元と後）\n- 行の中身は変わっていません。", out)
                self.assertIn("■ 全文差分（変更 0か所。省略していません）", out)

    def test_t12_compose_and_treated(self):
        for material, final, treated in ((MEMO, COMPOSED, False), (OLD, NEW, True)):
            a, b = self.pair(material, final)
            with mock.patch.object(check._Children, "start", autospec=True, side_effect=check._Children.start) as start:
                code, out, err = self.check("run", "--material", a, "--final", b, "--no-record")
            self.assertEqual((code, err), (0, ""))
            if treated:
                self.assertIn("見直し候補: 資料1（原文とみなした資料） 0件 → 最終稿 0件", out)
                self.assertIn("■ 直した箇所", out)
            else:
                lines = out.splitlines()
                self.assertEqual(lines[self.record_index(lines) + 1], "見直し候補: 最終稿 0件（{}）".format(COMPOSE_NOTE))
                self.assertNotIn("■ 直した箇所", out)
            self.assertEqual(any(c.args[1] == "source_lint" for c in start.call_args_list), treated)
            _, data, _ = self.check("run", "--material", a, "--final", b, "--no-record", "--json")
            counts = json.loads(data)["candidate_counts"]
            self.assertEqual(counts["source_index"], 1 if treated else None)
            if not treated:
                self.assertTrue(all(v is None for k, v in counts.items() if k.startswith("source")))
                self.assertIsNone(json.loads(data)["changed_places"])

    def test_t13_stdin(self):
        for role, old, new in (("original", OLD, NEW), ("material", MEMO, COMPOSED)):
            a, b = self.pair(old, new)
            _, file_out, _ = self.check("run", "--source" if role == "original" else "--material", a, "--final", b, "--no-record")
            data = ("<<<yomiyasu:{}>>>\n{}<<<yomiyasu:final>>>\n{}".format(role, old, new)).encode("utf-8")
            code, out, err = self.check("run", "--stdin", "--no-record", stdin=data)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(out.splitlines()[2:-2], file_out.splitlines()[2:-2])

    def test_t14_optional_source_failure(self):
        for status, stdout, label in (("timeout", None, "時間切れ"), ("error", None, "内部エラー"),
                                      ("ran", b"not json", "内部エラー"), ("ran", b'{}', "内部エラー")):
            with self.subTest(status=status, stdout=stdout):
                with self.replace_result("source_lint", (status, 0 if status == "ran" else None, stdout, "子のエラー", 0, "失敗")):
                    code, out, err = self.run_pair()
                    _, data = self.data_pair()
                self.assertEqual((code, err), (0, ""))
                self.assertIn("yomiyasu-check: executed ", out)
                self.assertIn("見直し候補: 原文 数えられず（{}） → 最終稿 0件".format(label), out)
                self.assertEqual(data["candidate_counts"]["source_status"], "timeout" if status == "timeout" else "error")
                self.assertIsNone(data["candidate_counts"]["source"])
                self.assertIsNone(data["candidate_counts"]["source_counts"])

    def test_t15_partial_and_changed_final(self):
        for name in ("lint", "diff"):
            with self.replace_result(name, ("timeout", None, None, "", 0, "時間切れ")):
                code, out, err = self.run_pair(extra=("--no-record",))
                json_code, json_out, _ = self.run_pair(extra=("--no-record", "--json"))
            self.assertEqual((code, json_code), (3, 3))
            self.assertTrue(err)
            self.assertEqual("見直し候補:" in out, name != "lint")
            self.assertEqual("■ 直した箇所" in out, name != "diff")
            data = json.loads(json_out)
            if name == "lint":
                self.assertIsNone(data["candidate_counts"]["final"])
            else:
                self.assertIsNone(data["changed_places"])
        original = check._run_checks
        def change(ctx, *args):
            value = original(ctx, *args)
            Path(ctx.final.path).write_bytes("途中で変更しました。\n".encode("utf-8"))
            return value
        with mock.patch.object(check, "_run_checks", change):
            code, out, _ = self.run_pair(extra=("--no-record",))
            _, json_out, _ = self.run_pair(extra=("--no-record", "--json"))
        self.assertEqual(code, 3)
        self.assertNotIn("見直し候補:", out)
        self.assertNotIn("■ 直した箇所", out)
        data = json.loads(json_out)
        self.assertIsNone(data["changed_places"])
        self.assertIsNone(data["candidate_counts"]["source_status"])

    def test_t16_source_warn_not_fail_on(self):
        code, data = self.data_pair(WARN, NEW, ("--fail-on", "warn"))
        self.assertEqual(code, 0)
        self.assertGreater(data["candidate_counts"]["source_counts"]["warn"], 0)
        self.assertEqual(data["candidate_counts"]["final"], 0)
        self.assertFalse(data["fail_on_hit"])

    def test_t17_record_unchanged_and_replay(self):
        _, out, _ = self.run_pair()
        path, record = self.record(out.splitlines())
        self.assertEqual(tuple(record), RECORD_KEYS)
        self.assertEqual(record["required_checks"], ["lint", "diff"])
        self.assertEqual([e["name"] for e in record["checks"]], ["lint", "diff"])
        for entry in record["checks"]:
            self.assertEqual(tuple(entry), CHECK_KEYS)
        self.assertEqual({p.name for p in path.parent.iterdir()}, {"attempt-1.json", "attempt-1.lint.json", "attempt-1.lint.txt",
                                                                       "attempt-1.diff.json", "attempt-1.diff.txt"})
        code, out, err = self.check("verify", "--final", self.root / "new.md", "--replay")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("executed via=verify", out)

    def test_t18_json_order_and_values(self):
        _, data = self.data_pair()
        expected = ["format", "format_version", "tool_version", "command", "status", "status_line", "message", "next",
                    "run_id", "attempt", "fix_count", "mode", "context", "record_path", "fail_on_hit", "meaning_risk_count",
                    "fail_on_meaning_risk_count", "stiffness_check", "tone_check", "hedges_check", "immutable_check",
                    "politeness_check", "lint", "diff", "materials", "candidate_counts", "changed_places", "fact_gaps",
                    "kept_marks"]
        self.assertEqual(list(data), expected)
        self.assertEqual(data["format_version"], 1)
        self.assertEqual(data["candidate_counts"], {"basis": "lint", "source": 0, "final": 0, "source_kind": "original",
                                                   "source_index": 0, "source_status": "ran", "source_counts": {"error": 0, "warn": 0, "info": 0}})
        self.assertEqual(data["candidate_counts"]["final"], data["lint"]["candidate_count"])
        self.assertEqual(data["changed_places"], {"count": len(data["diff"]["full_diff"]["hunks"]), "shown": 1, "omitted": 0, "clipped": False})

    def test_t19_verify_summary_and_no_import(self):
        self.run_pair()
        with mock.patch.object(check, "_load_tool", side_effect=AssertionError("検査の読み込み")):
            code, out, err = self.check("verify", "--final", self.root / "new.md")
            _, json_out, _ = self.check("verify", "--final", self.root / "new.md", "--json")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(out.splitlines()), 4)
        self.assertEqual(out.splitlines()[3], "記録の中身: 見直し候補 最終稿 0件、直した箇所 1か所（原文の件数と元と後は run の出力にあります）")
        data = json.loads(json_out)
        self.assertEqual(list(data)[-3:], ["final_candidate_count", "changed_place_count", "kept_marks"])
        self.assertEqual((data["final_candidate_count"], data["changed_place_count"]), (0, 1))
        material, final = self.write("memo.md", MEMO), self.write("composed.md", COMPOSED)
        self.check("run", "--material", material, "--final", final)
        _, out, _ = self.check("verify", "--final", final)
        self.assertEqual(out.splitlines()[3], "記録の中身: 見直し候補 最終稿 0件（新規作成）")
        _, json_out, _ = self.check("verify", "--final", final, "--json")
        self.assertIsNone(json.loads(json_out)["changed_place_count"])
        missing = self.write("missing.md", "別の本文です。\n")
        _, out, _ = self.check("verify", "--final", missing)
        self.assertEqual(len(out.splitlines()), 3)
        _, json_out, _ = self.check("verify", "--final", missing, "--json")
        data = json.loads(json_out)
        self.assertIsNone(data["final_candidate_count"])
        self.assertIsNone(data["changed_place_count"])
        for value in (None, True, "1", 1.5):
            record = {"checks": [{"name": "lint", "summary": {"candidate_count": value}}]}
            self.assertIsNone(check._record_summary_count(record, "lint", "candidate_count"))
        self.assertEqual(check._verified_contents_line(None, None, ["lint", "diff"]),
                         "記録の中身: 見直し候補 最終稿 不明、直した箇所 不明（原文の件数と元と後は run の出力にあります）")

    def test_t20_copies_and_python38_syntax(self):
        script = (ROOT / "scripts" / "yomiyasu_check.py").read_bytes()
        self.assertEqual(script, (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_check.py").read_bytes())
        ast.parse(script.decode("utf-8"), feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
