#!/usr/bin/env python3
"""v2.0.0（diff の詰めの直し）: check と diff の表示、一覧のハッシュ、一覧の読み込み、ヘルプ、--stdin の区切りの書き損じ。

- 反証 spec の F1: 文体の硬化と勢いの見直し候補（level review）だけのとき、diff の状態の行と check の1行目が「候補はない」
  だけを言わないようにする。JSON の candidate_count と status は変えず、人が読む文だけに添える。参考（info）だけなら添えない。
- spec の F5、regress の R9: 記録の tools に references/lists/ の一覧のファイル（あれば）の SHA-256 を足し、verify で比べて
  変わっていれば tool_changed にする。1行目は、一覧が変わったことが分かる文にする（--replay でも同じ）。一覧のファイルがあるのに
  読めず、内蔵の一覧で動いたときは、硬化と勢いの節に1行出す（ファイルがないときは出さない）。気持ちの語の一覧の出どころも
  JSON の feeling.list に出す。
- regress の R8: BOM つきの UTF-8 と CRLF で保存した一覧も、ファイルから読む（コメント行を語にしない）。
- spec の F6、F7: --fail-on と check run の --doc-type のヘルプ。
- G15 の道具の観点: --stdin で「<<<yomiyasu:」で始まるが決まった区切りと
  一字一句同じでない行は、終了コード2で止める（資料が原文に黙ってつながるのを防ぐ）。
文はすべて合成の文。
"""

from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import (  # noqa: E402
    CHECK, CheckCase, FINALIZE_STATE_DIR, RUN_HEAD_NOTE, RUN_REWRITE_FIRST, RUN_REWRITE_FIRST_NO_CANDIDATES, ROOT, SCRIPTS,
    SKILL_MD, TOOL_NAMES, VERIFY_LINE1, sha256_file, split_lines)

sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402

# diff が読む4つの一覧と、2.2.0 で lint が読む2つの一覧（check の記録の tools にはどれも入る）
DIFF_LIST_NAMES = ("nominalization", "intensifiers", "feelings", "hedges")
LINT_LIST_NAMES = ("katakana-terms", "thin-evaluation", "renyo-nouns")
LIST_NAMES = DIFF_LIST_NAMES + LINT_LIST_NAMES
LIST_KEYS = tuple("references/lists/{}.txt".format(name) for name in LIST_NAMES)
LISTS = ROOT / "references" / "lists"

TONE = ("最強のお土産です！\n", "最強のお土産です。\n")
STIFF_AND_TONE = ("ログを見れば、時間を溶かさずに原因がわかります！\n", "ログの参照により、迅速な原因究明が可能です。\n")
NUMBER_AND_TONE = ("保存期間は3日です！\n", "保存期間は30日です。\n")
PLAIN = ("保存期間は3日です。\n", "保存期間は30日です。\n")
QUIET = ("設定を確認します。\n", "設定を 確認します。\n")

DETECTOR_NOTE = "（文体の硬化と勢いの見直し候補 {}件は下の節）"
# レポートの最後の状態の行は、節がその上にあるので「上の節」（反証で見つけた例）
DETECTOR_NOTE_LAST = "（文体の硬化と勢いの見直し候補 {}件は上の節）"
RUN_FIRST_DETECTORS = ("検査を実行しました（1回目）。規則に当たる候補はありませんが、文体の硬化と勢いの見直し候補が{}件あります。"
                       "その節を原文と照らし、全文差分で意図しない変更がないかを確かめ、直すなら1回まで、直さないなら")
LIST_CHANGED_LINE = ("記録のあとで、検査に使う語の一覧（{}）が変わりました。yomiyasu_check.py run をもう一度実行してください。")
SCRIPT_AND_LIST_CHANGED_LINE = ("記録のあとで、検査スクリプトと、検査に使う語の一覧（{}）が変わりました。"
                                "yomiyasu_check.py run をもう一度実行してください。")
LIST_LABELS = {"nominalization": "名詞化の言い回しの一覧", "intensifiers": "強める語の一覧",
               "feelings": "気持ちの語の一覧（意味が変わる恐れの「元にない気持ちの語」に使う）"}
LIST_PROBLEM_LINE = "- {} references/lists/{}.txt を読めなかったので、内蔵の一覧で検査しました（{}）。ファイルに足し引きした語は効いていません。"
FAIL_ON_NOT_COUNTED = "否定対比の主張の逆転と、元にない気持ちの語も数えません。"


def diff_of(before, after, **options):
    return yomiyasu_diff.diff(before, after, **options)


def report_lines(result):
    return yomiyasu_diff.report(result).split("\n")


def load_check_module():
    spec = importlib.util.spec_from_file_location("check_module_infra", str(CHECK))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def action_help(parser, dest):
    for action in parser._actions:
        if action.dest == dest:
            return action.help
    raise AssertionError("{} の引数がない".format(dest))


def copy_scripts(folder, lists=None):
    """scripts の4本を folder/scripts に写す。lists が dict なら folder/references/lists/<名前>.txt にバイト列を書く
    （None の値は書かない）。lists が None なら references のフォルダを作らない（ZIP やスクリプトだけの置き方）。"""
    target = Path(folder) / "scripts"
    target.mkdir(parents=True)
    for name in TOOL_NAMES:
        shutil.copyfile(str(SCRIPTS / name), str(target / name))
    if lists is not None:
        base = Path(folder) / "references" / "lists"
        base.mkdir(parents=True)
        for name, data in lists.items():
            if data is not None:
                (base / (name + ".txt")).write_bytes(data)
    return target


def shipped_lists(transform=None):
    """リポジトリの3つの一覧のバイト列（transform で変えられる）。"""
    out = {}
    for name in LIST_NAMES:
        data = (LISTS / (name + ".txt")).read_bytes()
        out[name] = transform(data) if transform is not None else data
    return out


def run_diff(scripts, before, after, *extra):
    folder = Path(scripts).parent
    a, b = folder / "pair-a.md", folder / "pair-b.md"
    a.write_bytes(before.encode("utf-8"))
    b.write_bytes(after.encode("utf-8"))
    return subprocess.run([sys.executable, "-B", str(Path(scripts) / "yomiyasu_diff.py")] + list(extra) + [str(a), str(b)],
                          capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=60)


# ---- spec の F1: 状態の行と1行目 ----

class DiffStatusLineTest(unittest.TestCase):
    def test_tone_only_status_line_names_the_section(self):
        result = diff_of(*TONE)
        self.assertEqual((result["status"], result["candidate_count"]), ("changed_without_candidates", 0))
        lines = report_lines(result)
        expected = "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 1か所）"
        self.assertEqual(lines[1], expected + DETECTOR_NOTE.format(1))
        self.assertEqual(lines[-1], expected + DETECTOR_NOTE_LAST.format(1))

    def test_stiffness_and_tone_are_counted_together(self):
        result = diff_of(*STIFF_AND_TONE)
        reviews = [c for key in ("stiffness", "tone") for c in result[key]["candidates"] if c["level"] == "review"]
        self.assertEqual(len(reviews), 2)
        self.assertEqual(result["candidate_count"], 4)
        self.assertEqual([(r["kind"], r["subkind"]) for r in result["meaning_risks"]], [("claim", "causal")])
        self.assertEqual(report_lines(result)[1],
                         "状態: 変更あり（1か所）。見直し候補 4件、うち意味が変わる恐れ 1件" + DETECTOR_NOTE.format(2))

    def test_status_with_rule_candidates_also_gets_the_note(self):
        result = diff_of(*NUMBER_AND_TONE)
        self.assertEqual(report_lines(result)[1],
                         "状態: 変更あり（1か所）。見直し候補 1件、うち意味が変わる恐れ 1件" + DETECTOR_NOTE.format(1))

    def test_reference_only_and_no_candidates_are_unchanged(self):
        result = diff_of(*TONE, doc_type="incident")
        self.assertEqual([c["level"] for c in result["tone"]["candidates"]], ["info"])
        self.assertEqual(report_lines(result)[1], "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 1か所）")
        self.assertEqual(report_lines(diff_of(*PLAIN))[1], "状態: 変更あり（1か所）。見直し候補 1件、うち意味が変わる恐れ 1件")
        self.assertEqual(report_lines(diff_of(*QUIET))[1], "状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 1か所）")
        self.assertEqual(report_lines(diff_of("同じです。\n", "同じです。\n"))[1], "状態: 変更なし")


class CheckFirstLineTest(CheckCase):
    def test_tone_only_first_line_points_to_the_section(self):
        a, b, lines = self.run_pair(*TONE)
        self.assertEqual(lines[0], RUN_FIRST_DETECTORS.format(1) + self.finalize_file())
        self.assertIn("規則に当たる候補はありません", lines[0])
        self.assertIn("■ 勢い（見直し候補 1件。書き手の勢いを落としていないか確かめる）", lines)

    def test_json_counts_and_next_are_unchanged(self):
        a = self.write("a.md", TONE[0])
        b = self.write("b.md", TONE[1])
        result = self.check_json("run", "--source", a, "--final", b)
        self.assertEqual((result["status"], result["next"]), ("executed", "review"))
        self.assertEqual((result["diff"]["status"], result["diff"]["candidate_count"]), ("changed_without_candidates", 0))
        self.assertEqual(result["message"], RUN_FIRST_DETECTORS.format(1) + self.finalize_file())

    def test_reference_only_keeps_the_first_line(self):
        a, b, lines = self.run_pair(*TONE, "--doc-type", "incident")
        self.assertEqual(lines[0], RUN_REWRITE_FIRST_NO_CANDIDATES + self.finalize_file())

    def test_rule_candidates_keep_the_first_line(self):
        a, b, lines = self.run_pair(*NUMBER_AND_TONE)
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + self.finalize_file())


# ---- spec の F5、regress の R9: 一覧のハッシュと verify ----

class ListHashTest(CheckCase):
    def skill_with_lists(self, names=LIST_NAMES):
        scripts = self.skill_copy()
        lists = scripts.parent / "references" / "lists"
        lists.mkdir(parents=True)
        for name in names:
            shutil.copyfile(str(LISTS / (name + ".txt")), str(lists / (name + ".txt")))
        return scripts, lists

    def run_skill(self, script, pair=TONE):
        a = self.write("a.md", pair[0])
        b = self.write("b.md", pair[1])
        process, lines = self.check_ok("run", "--source", a, "--final", b, script=script)
        return a, b, lines

    def test_record_tools_have_the_list_hashes(self):
        scripts, lists = self.skill_with_lists()
        a, b, lines = self.run_skill(scripts / "yomiyasu_check.py")
        path, record = self.record_from(lines)
        self.assertEqual(set(record["tools"]), set(TOOL_NAMES) | set(LIST_KEYS))
        for name, key in zip(LIST_NAMES, LIST_KEYS):
            self.assertEqual(record["tools"][key], {"version": None, "sha256": sha256_file(lists / (name + ".txt"))})
        for name in TOOL_NAMES:
            self.assertEqual(record["tools"][name]["sha256"], sha256_file(scripts / name))

    def test_no_list_keys_without_the_files(self):
        scripts = self.skill_copy()
        a, b, lines = self.run_skill(scripts / "yomiyasu_check.py")
        path, record = self.record_from(lines)
        self.assertEqual(set(record["tools"]), set(TOOL_NAMES))
        self.assert_verify(self.check("verify", "--final", b, "--replay", script=scripts / "yomiyasu_check.py"),
                           "executed", code=0)

    def test_unchanged_lists_verify_and_replay(self):
        scripts, lists = self.skill_with_lists()
        script = scripts / "yomiyasu_check.py"
        a, b, lines = self.run_skill(script)
        self.assert_verify(self.check("verify", "--final", b, script=script), "executed", code=0)
        self.assert_verify(self.check("verify", "--final", b, "--replay", script=script), "executed", code=0)

    def test_changed_list_is_tool_changed(self):
        """R9 の再現: 一覧の行を引いたあとの verify と verify --replay は tool_changed で、1行目が一覧の名前を言う。"""
        scripts, lists = self.skill_with_lists()
        script = scripts / "yomiyasu_check.py"
        a, b, lines = self.run_skill(script, pair=("この店のラーメンは本当においしいです。\n", "この店のラーメンはおいしいです。\n"))
        path = lists / "intensifiers.txt"
        path.write_bytes(path.read_text(encoding="utf-8").replace("本当に\n", "").encode("utf-8"))
        expected = LIST_CHANGED_LINE.format("references/lists/intensifiers.txt")
        for extra in ([], ["--replay"]):
            with self.subTest(extra=extra):
                verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, *extra, script=script),
                                                     "tool_changed")
                self.assertEqual(verify_lines[0], expected)
        result = json.loads(self.check("verify", "--final", b, "--json", script=script).stdout)
        self.assertEqual(result["status"], "tool_changed")
        self.assertIn({"code": "tool_changed", "detail": "references/lists/intensifiers.txt"}, result["problems"])
        self.assertEqual(result["message"], expected)

    def test_added_and_removed_list_files_are_tool_changed(self):
        scripts, lists = self.skill_with_lists(names=("nominalization", "intensifiers"))
        script = scripts / "yomiyasu_check.py"
        a, b, lines = self.run_skill(script)
        path, record = self.record_from(lines)
        self.assertNotIn("references/lists/feelings.txt", record["tools"])
        shutil.copyfile(str(LISTS / "feelings.txt"), str(lists / "feelings.txt"))
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, script=script), "tool_changed")
        self.assertEqual(verify_lines[0], LIST_CHANGED_LINE.format("references/lists/feelings.txt"))
        os.remove(str(lists / "feelings.txt"))
        self.assert_verify(self.check("verify", "--final", b, script=script), "executed", code=0)
        os.remove(str(lists / "nominalization.txt"))
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, script=script), "tool_changed")
        self.assertEqual(verify_lines[0], LIST_CHANGED_LINE.format("references/lists/nominalization.txt"))

    def test_script_and_list_changed(self):
        scripts, lists = self.skill_with_lists()
        script = scripts / "yomiyasu_check.py"
        a, b, lines = self.run_skill(script)
        with open(str(lists / "feelings.txt"), "ab") as handle:
            handle.write("# 足した行\n".encode("utf-8"))
        with open(str(lists / "intensifiers.txt"), "ab") as handle:
            handle.write("# 足した行\n".encode("utf-8"))
        with open(str(scripts / "yomiyasu_lint.py"), "ab") as handle:
            handle.write(b"# changed after the record by test_v200_check_infra\n")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, script=script), "tool_changed")
        self.assertEqual(verify_lines[0], SCRIPT_AND_LIST_CHANGED_LINE.format(
            "references/lists/intensifiers.txt、references/lists/feelings.txt"))

    def test_only_script_changed_keeps_the_line(self):
        scripts, lists = self.skill_with_lists()
        script = scripts / "yomiyasu_check.py"
        a, b, lines = self.run_skill(script)
        with open(str(scripts / "yomiyasu_diff.py"), "ab") as handle:
            handle.write(b"# changed after the record by test_v200_check_infra\n")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b, script=script), "tool_changed")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["tool_changed"])

    def test_broken_list_entry_in_the_record_is_invalid(self):
        """記録の tools の一覧の項目の形が違えば invalid_record（digest を作り直しても）。"""
        scripts, lists = self.skill_with_lists()
        script = scripts / "yomiyasu_check.py"
        a, b, lines = self.run_skill(script)
        path, record = self.record_from(lines)
        record["tools"]["references/lists/feelings.txt"] = "abc"
        module = load_check_module()
        record["record_digest"] = module._record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", b, script=script), "invalid_record")

    def test_check_list_names_match_diff(self):
        module = load_check_module()
        self.assertEqual(tuple(module._LIST_NAMES), LIST_NAMES)
        # fact-gaps は任意の手がかり。verify の通常判定ではなく replay で比べる。
        self.assertEqual(set(DIFF_LIST_NAMES) | {"fact-gaps"}, set(yomiyasu_diff.BUILTIN_LISTS))
        # 2.2.0: lint の katakana_term と thin_evaluation の一覧
        self.assertEqual(set(LINT_LIST_NAMES), set(yomiyasu_lint._V220_BUILTIN_LISTS))


# ---- spec の F5 の後半: 読めない一覧の知らせと、気持ちの語の一覧の出どころ ----

class ListProblemTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-lists-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def json_of(self, scripts, pair=PLAIN, *extra):
        process = run_diff(scripts, pair[0], pair[1], "--json", *extra)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        return json.loads(process.stdout.decode("utf-8"))

    def text_of(self, scripts, pair=PLAIN, *extra):
        process = run_diff(scripts, pair[0], pair[1], *extra)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        return process.stdout.decode("utf-8").split("\n")

    def test_repository_lists_are_reported_as_files(self):
        result = diff_of(*PLAIN)
        self.assertEqual(result["feeling"], {"list": "references/lists/feelings.txt", "list_problem": None})
        self.assertEqual((result["stiffness"]["list"], result["stiffness"]["list_problem"]),
                         ("references/lists/nominalization.txt", None))
        self.assertEqual((result["tone"]["list"], result["tone"]["list_problem"]), ("references/lists/intensifiers.txt", None))
        self.assertEqual(list(result)[-11:], ["full_diff", "stiffness", "tone", "feeling", "hedges", "immutable", "politeness",
                                              "register", "added_actors", "heading_shapes", "comma_increase"])

    def test_missing_lists_are_silent(self):
        scripts = copy_scripts(self.folder)
        result = self.json_of(scripts)
        self.assertEqual(result["feeling"], {"list": "builtin", "list_problem": None})
        self.assertEqual((result["stiffness"]["list"], result["stiffness"]["list_problem"]), ("builtin", None))
        self.assertEqual((result["tone"]["list"], result["tone"]["list_problem"]), ("builtin", None))
        lines = self.text_of(scripts)
        self.assertFalse([line for line in lines if line.startswith(("■ 文体の硬化", "■ 勢い"))], lines)
        self.assertFalse([line for line in lines if "読めなかった" in line], lines)

    def test_unreadable_lists_are_reported_in_the_sections(self):
        lists = shipped_lists()
        lists["nominalization"] = "が可能\tが可能\n".encode("cp932")
        lists["intensifiers"] = "とても\n".encode("cp932")
        lists["feelings"] = "壊れた\t(?:\n".encode("utf-8")
        scripts = copy_scripts(self.folder, lists)
        result = self.json_of(scripts)
        self.assertEqual((result["stiffness"]["list"], result["stiffness"]["list_problem"]), ("builtin", "UTF-8 として読めません"))
        self.assertEqual((result["tone"]["list"], result["tone"]["list_problem"]), ("builtin", "UTF-8 として読めません"))
        self.assertEqual(result["feeling"]["list"], "builtin")
        self.assertTrue(result["feeling"]["list_problem"].startswith("正規表現の誤り"), result["feeling"])
        lines = self.text_of(scripts)
        stiff = lines.index("■ 文体の硬化（一覧の注意）")
        self.assertEqual(lines[stiff + 1], LIST_PROBLEM_LINE.format(LIST_LABELS["nominalization"], "nominalization",
                                                                     "UTF-8 として読めません"))
        tone = lines.index("■ 勢い（一覧の注意）")
        self.assertEqual(lines[tone + 1], LIST_PROBLEM_LINE.format(LIST_LABELS["intensifiers"], "intensifiers",
                                                                    "UTF-8 として読めません"))
        self.assertEqual(lines[tone + 2], LIST_PROBLEM_LINE.format(LIST_LABELS["feelings"], "feelings",
                                                                    result["feeling"]["list_problem"]))
        # 節は全文差分の前（意味が変わる恐れ、規則の見直し候補のあと）
        self.assertLess(tone, lines.index("■ 全文差分（変更 1か所。省略していません）"))

    def test_note_comes_before_the_candidates(self):
        lists = shipped_lists()
        lists["intensifiers"] = "最強\n".encode("cp932")
        scripts = copy_scripts(self.folder, lists)
        lines = self.text_of(scripts, TONE)
        tone = lines.index("■ 勢い（見直し候補 1件。書き手の勢いを落としていないか確かめる）")
        self.assertEqual(lines[tone + 1], LIST_PROBLEM_LINE.format(LIST_LABELS["intensifiers"], "intensifiers",
                                                                    "UTF-8 として読めません"))
        self.assertTrue(lines[tone + 2].startswith("- 原文の「！」"), lines[tone:tone + 3])

    def test_unreadable_folder_entry(self):
        lists = shipped_lists()
        lists["nominalization"] = None
        scripts = copy_scripts(self.folder, lists)
        (self.folder / "references" / "lists" / "nominalization.txt").mkdir()
        result = self.json_of(scripts)
        self.assertEqual(result["stiffness"]["list"], "builtin")
        self.assertTrue(result["stiffness"]["list_problem"].startswith("ファイルを開けません"), result["stiffness"])

    def test_check_run_shows_the_note(self):
        lists = shipped_lists()
        lists["nominalization"] = "が可能\tが可能\n".encode("cp932")
        scripts = copy_scripts(self.folder, lists)
        a, b = self.folder / "a.md", self.folder / "b.md"
        a.write_bytes(PLAIN[0].encode("utf-8"))
        b.write_bytes(PLAIN[1].encode("utf-8"))
        env = dict(os.environ, PYTHONIOENCODING="utf-8", YOMIYASU_STATE_DIR=str(self.folder / ".yomiyasu"))
        process = subprocess.run([sys.executable, "-B", str(scripts / "yomiyasu_check.py"), "run", "--source", str(a),
                                  "--final", str(b)], capture_output=True, env=env, cwd=str(self.folder), timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
        lines = process.stdout.decode("utf-8").split("\n")
        stiff = lines.index("■ 文体の硬化（一覧の注意）")
        self.assertEqual(lines[stiff + 1], LIST_PROBLEM_LINE.format(LIST_LABELS["nominalization"], "nominalization",
                                                                     "UTF-8 として読めません"))
        # 記録の行のあとの2行（完了報告に写す値。候補がなければ6行目と7行目、候補の一覧と案内の2行があれば8行目と9行目）は候補の数のまま
        index = 6 if lines[4] == RUN_HEAD_NOTE else 4
        self.assertTrue(lines[index].startswith("記録: "), lines[:index + 1])
        self.assertEqual(lines[index + 1:index + 3], ["硬化の検査: 候補なし", "勢いの検査: 候補なし"])


# ---- regress の R8: BOM つきの UTF-8 ----

_LOAD_LISTS = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import yomiyasu_diff
out = {}
for name in ("nominalization", "intensifiers", "feelings", "hedges"):
    items, source = yomiyasu_diff._load_list(name)
    out[name] = {"source": source,
                 "items": [item if isinstance(item, str) else [item[0]] + [regex.pattern for regex in item[1:]]
                           for item in items]}
print(json.dumps(out))
"""


class BomListTest(unittest.TestCase):
    def test_bom_and_crlf_lists_are_read_from_the_files(self):
        with tempfile.TemporaryDirectory(prefix="yomiyasu-bom-") as folder:
            lists = shipped_lists(lambda data: b"\xef\xbb\xbf" + data.replace(b"\n", b"\r\n"))
            scripts = copy_scripts(folder, lists)
            process = subprocess.run([sys.executable, "-B", "-c", _LOAD_LISTS, str(scripts)], capture_output=True,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
            loaded = json.loads(process.stdout.decode("utf-8"))
            for name in DIFF_LIST_NAMES:
                with self.subTest(name=name):
                    self.assertEqual(loaded[name]["source"], "references/lists/{}.txt".format(name))
                    builtin = [item if isinstance(item, str) else list(item) for item in yomiyasu_diff.BUILTIN_LISTS[name]]
                    self.assertEqual(loaded[name]["items"], builtin)
            result = json.loads(run_diff(scripts, PLAIN[0], PLAIN[1], "--json").stdout.decode("utf-8"))
            self.assertEqual((result["stiffness"]["list"], result["stiffness"]["list_problem"]),
                             ("references/lists/nominalization.txt", None))
            self.assertEqual((result["tone"]["list"], result["tone"]["list_problem"]),
                             ("references/lists/intensifiers.txt", None))
            self.assertEqual(result["feeling"], {"list": "references/lists/feelings.txt", "list_problem": None})

    def test_parse_list_drops_a_leading_bom(self):
        self.assertEqual(yomiyasu_diff.parse_list("﻿# 説明\r\nとても\r\n"), ["とても"])
        self.assertEqual(yomiyasu_diff.parse_list("﻿とても\n"), ["とても"])


# ---- spec の F6、F7: ヘルプ ----

class HelpTest(unittest.TestCase):
    def test_fail_on_help_names_the_kinds_it_does_not_count(self):
        diff_help = action_help(yomiyasu_diff._build_parser(), "fail_on")
        self.assertIn(FAIL_ON_NOT_COUNTED, diff_help)
        parser, run, verify = load_check_module()._build_parser()
        self.assertIn(FAIL_ON_NOT_COUNTED, action_help(run, "fail_on"))

    def test_doc_type_help_names_the_reference_types(self):
        sentence = yomiyasu_diff._detector_level_help()
        for doc_type in yomiyasu_diff.STIFFNESS_INFO_DOC_TYPES + yomiyasu_diff.TONE_INFO_DOC_TYPES:
            self.assertIn(doc_type, sentence)
        self.assertIn(sentence, action_help(yomiyasu_diff._build_parser(), "doc_type"))
        parser, run, verify = load_check_module()._build_parser()
        self.assertIn(sentence, action_help(run, "doc_type"))

    def test_help_runs(self):
        for script, args in ((CHECK, ["run", "-h"]), (SCRIPTS / "yomiyasu_diff.py", ["-h"])):
            process = subprocess.run([sys.executable, "-B", str(script)] + args, capture_output=True,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=30)
            self.assertEqual(process.returncode, 0)
            # argparse は長い日本語の文を字の途中で折り返すので、空白と改行を除いて探す
            self.assertIn("否定対比の主張の逆転", "".join(process.stdout.decode("utf-8").split()))


# ---- regress の R10（速さ）: 出力を変えない最適化の見張り ----

class AnyOfTest(unittest.TestCase):
    """一覧の正規表現を1つにつないだ先の見分け（_any_of）は、どれかが当たる文でだけ当たる。つなぐと意味が変わりうる一覧
    （捕まえる組、文書全体の印）では作らず、1つずつ調べる（足し引きした一覧でも結果を変えない）。"""

    def corpus_sentences(self):
        sentences = []
        for folder in ("raw_ai", "yomiyasu_rewritten", "human", "edge_cases"):
            for path in sorted((ROOT / "tests" / "corpus" / folder).glob("*.md")):
                for line in path.read_text(encoding="utf-8").split("\n"):
                    sentences.extend(piece for piece in line.split("。") if piece.strip())
        return sentences + ["ほっとした。", "不安定な接続", "心配はありません", "条件を満足する場合", "売上が落ち込んだ",
                            "が可能です", "することが可能", "を担保する"]

    def test_combined_pattern_matches_exactly_when_one_pattern_matches(self):
        sentences = self.corpus_sentences()
        self.assertGreater(len(sentences), 1000)
        for name in ("feelings", "nominalization"):
            items, _ = yomiyasu_diff._load_list(name)
            combined = yomiyasu_diff._any_of(items)
            self.assertIsNotNone(combined, name)
            for text in sentences:
                self.assertEqual(combined.search(text) is not None, any(item[1].search(text) for item in items),
                                 (name, text))

    def test_lists_that_cannot_be_joined_are_checked_one_by_one(self):
        import re
        self.assertIsNone(yomiyasu_diff._any_of([("a", re.compile("(ほっ)と\\1?"))]))
        self.assertIsNone(yomiyasu_diff._any_of([("a", re.compile("(?i)abc")), ("b", re.compile("x"))]))
        self.assertIsNone(yomiyasu_diff._any_of([]))
        joined = yomiyasu_diff._any_of([("a", re.compile("嬉し|うれし")), ("b", re.compile("(?i:abc)"))])
        self.assertTrue(joined.search("ABC") and joined.search("うれしい") and not joined.search("かなしい"))

    def test_feeling_list_with_groups_still_works(self):
        with tempfile.TemporaryDirectory(prefix="yomiyasu-anyof-") as folder:
            lists = shipped_lists()
            lists["feelings"] = "ほっと\t(ほっ)と(?=し)\n安堵\t(?i)安堵\n".encode("utf-8")
            scripts = copy_scripts(folder, lists)
            result = json.loads(run_diff(scripts, "設定を変更した。\n", "設定を変更して、ほっとした。\n", "--json")
                                .stdout.decode("utf-8"))
            self.assertEqual(result["feeling"], {"list": "references/lists/feelings.txt", "list_problem": None})
            self.assertEqual([(risk["kind"], risk["detail"]) for risk in result["meaning_risks"] if risk["kind"] == "feeling"],
                             [("feeling", {"words": ["ほっと"]})])


# ---- G15 の道具の観点の P2: --stdin の区切りの書き損じ ----

class StdinMarkerTest(CheckCase):
    BAD = (
        ("原文に出典を足した区切り", "<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:original 利用者の発言>>>\n"
         "保存期間は30日に変える。\n<<<yomiyasu:final>>>\n保存期間は30日です。\n", 3, "<<<yomiyasu:original 利用者の発言>>>"),
        ("複数形", "<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:materials>>>\n保存期間は30日に変える。\n"
         "<<<yomiyasu:final>>>\n保存期間は30日です。\n", 3, "<<<yomiyasu:materials>>>"),
        ("綴りの誤りの最初の行", "<<<yomiyasu:orignal>>>\n保存期間は3日です。\n<<<yomiyasu:final>>>\n保存期間は30日です。\n",
         1, "<<<yomiyasu:orignal>>>"),
        ("空白なしで出典", "<<<yomiyasu:material出典>>>\n保存期間は30日に変える。\n<<<yomiyasu:final>>>\n保存期間は30日です。\n",
         1, "<<<yomiyasu:material出典>>>"),
        ("行末の空白", "<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:final>>> \n保存期間は30日です。\n",
         3, "<<<yomiyasu:final>>> "),
        ("字下げ", "<<<yomiyasu:original>>>\n保存期間は3日です。\n  <<<yomiyasu:material>>>\n保存期間は30日に変える。\n"
         "<<<yomiyasu:final>>>\n保存期間は30日です。\n", 3, "  <<<yomiyasu:material>>>"),
        ("大文字", "<<<yomiyasu:original>>>\r\n保存期間は3日です。\r\n<<<YOMIYASU:MATERIAL>>>\r\n保存期間は30日に変える。\r\n"
         "<<<yomiyasu:final>>>\r\n保存期間は30日です。\r\n", 3, "<<<YOMIYASU:MATERIAL>>>"),
    )

    def test_misspelled_markers_are_usage_errors(self):
        for name, body, line, shown in self.BAD:
            with self.subTest(case=name):
                process = self.check("run", "--stdin", stdin=body)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn("{}行目の「{}」が、決まった区切りの行と一字一句同じではありません".format(line, shown),
                              process.stderr)
                self.assertIn("<<<yomiyasu:final>>>", process.stderr)
                self.assertIn("ファイルに保存して", process.stderr)
                self.assertFalse(self.state.exists())

    def test_long_marker_lines_are_shortened(self):
        body = ("<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:material " + "あ" * 201 + ">>>\nメモ\n"
                "<<<yomiyasu:final>>>\n保存期間は30日です。\n")
        process = self.check("run", "--stdin", stdin=body)
        self.assertEqual(process.returncode, 2)
        self.assertIn("3行目の「<<<yomiyasu:material " + "あ" * 39 + "…」", process.stderr)

    def test_correct_markers_still_work(self):
        body = ("\n<<<yomiyasu:original>>>\r\n保存期間は3日です。本文に <<<yomiyasu:final>>> と書いた行。\r\n"
                "<<<yomiyasu:material>>>\r\n保存期間は30日に変える。\r\n<<<yomiyasu:final>>>\r\n保存期間は30日です。\r\n")
        process = self.check("run", "--stdin", "--json", stdin=body)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual((result["mode"], result["status"]), ("rewrite", "executed"))
        record = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(record["inputs"]["materials"]), 1)
        self.assertEqual(record["inputs"]["source"]["bytes"], len("保存期間は3日です。本文に <<<yomiyasu:final>>> と書いた行。\r\n"
                                                                 .encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
