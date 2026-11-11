"""CI が試験を組に分けて流すための決まり（tests/conftest.py と .github/workflows/ci.yml）を確かめる。

conftest.py は pytest を読み込むので、PartsTest では読み込まずにソースを読む（pytest を入れずに unittest で流す環境でも
動かすため）。
- 組の分け方（part_of）: どの試験も、ちょうど1つの組に入る。
- 名前で timing に入れる試験（_TIMED_BY_NAME）: 書いてある名前の試験が、そのファイルのそのクラスにある。
- CI の設定: 分ける組の数と `--part` の指定が合っていて、組を流す段と時間を測る試験の段が、組の一覧と同じ数だけある。
  段を流す条件（if:）を書き損じると、試験を1件も流さないままジョブが成功するので、条件の文も見る。
HookTest は、pytest があるときだけ、conftest.py のフックそのものを pytest に集めさせて確かめる（流さない）。
"""
from pathlib import Path
import ast
import importlib.util
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONFTEST = ROOT / "tests" / "conftest.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def conftest_tree():
    return ast.parse(CONFTEST.read_text(encoding="utf-8"))


def literal(name):
    """conftest.py のモジュールの名前 name に入れてある値（文字列やタプルだけでできたもの）。"""
    for node in conftest_tree().body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("conftest.py に {} がない".format(name))


def function(name):
    """conftest.py の関数 name を、その関数だけ取り出して動かせる形にする（ほかの名前を使わない関数に限る）。"""
    for node in conftest_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            node.returns = None
            for argument in node.args.args:
                argument.annotation = None
            scope = {}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(CONFTEST), "exec"), scope)
            return scope[name]
    raise AssertionError("conftest.py に {} がない".format(name))


def steps(text):
    """ci.yml の step ごとの行（「- name:」か「- uses:」の行から、次の step か次のジョブの前まで。コメントの行は除く）。"""
    found, current = [], None
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if re.match(r"^      - (name|uses): ", line):
            current = [line]
            found.append(current)
        elif current is not None and line.startswith("        "):
            current.append(line)
        else:
            current = None
    return found


class PartsTest(unittest.TestCase):
    def test_every_test_falls_into_exactly_one_part(self):
        part_of = function("part_of")
        for total in range(1, 7):
            for count in (0, 1, total - 1, total, total + 1, 50, 1000):
                parts = [part_of(position, total) for position in range(max(count, 0))]
                self.assertTrue(all(1 <= part <= total for part in parts))
                sizes = [parts.count(part) for part in range(1, total + 1)]
                self.assertEqual(sum(sizes), max(count, 0))
                self.assertLessEqual(max(sizes) - min(sizes), 1, "組の大きさの差は1件まで")

    def test_tests_marked_by_name_exist(self):
        names = literal("_TIMED_BY_NAME")
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            with self.subTest(name=name):
                file_name, class_name, test_name = name.split("::")
                tree = ast.parse((ROOT / "tests" / file_name).read_text(encoding="utf-8"))
                classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
                self.assertEqual(len(classes), 1)
                methods = [node.name for node in classes[0].body if isinstance(node, ast.FunctionDef)]
                self.assertIn(test_name, methods)

    def test_workflow_runs_every_part_and_the_timing_tests(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        lists = re.findall(r'^\s*part: \[(.+)\]\s*$', text, flags=re.MULTILINE)
        self.assertTrue(lists, "ci.yml に part の一覧がない")
        for line in lists:
            with self.subTest(line=line):
                values = [value.strip().strip('"') for value in line.split(",")]
                self.assertEqual(values[-1], "timing")
                numbered = values[:-1]
                total = len(numbered)
                self.assertEqual(numbered, ["{}/{}".format(index, total) for index in range(1, total + 1)])
        # 1つの組が落ちても、ほかの組を最後まで流す
        self.assertEqual(len(re.findall(r"^\s*fail-fast: false\s*$", text, flags=re.MULTILINE)), len(lists))
        # 組に分けて流す段は時間を測らない試験だけ、時間を測る試験の段は1つずつ（-n なし）。
        # どちらの段も、part の一覧1つにつき1つずつあり、段の if が「timing 以外の組」「timing の組」になっている
        part_runs = [step for step in steps(text) if any("--part" in line and "pytest" in line for line in step)]
        self.assertEqual(len(part_runs), len(lists))
        for step in part_runs:
            run = [line for line in step if "pytest" in line]
            self.assertEqual(len(run), 1)
            self.assertIn('-m "not timing"', run[0])
            self.assertIn("--part ${{ matrix.part }}", run[0])
            self.assertEqual([line.strip() for line in step if line.strip().startswith("if:")], ["if: matrix.part != 'timing'"])
        timing_runs = [step for step in steps(text) if any("pytest" in line and "-m timing" in line for line in step)]
        self.assertEqual(len(timing_runs), len(lists))
        for step in timing_runs:
            run = [line for line in step if "pytest" in line]
            self.assertEqual(len(run), 1)
            self.assertNotIn(" -n ", run[0])
            self.assertNotIn("--part", run[0])
            self.assertEqual([line.strip() for line in step if line.strip().startswith("if:")], ["if: matrix.part == 'timing'"])
        # pytest を流す段は、上の2種類だけ
        pytest_steps = [step for step in steps(text) if any("-m pytest" in line for line in step)]
        self.assertEqual(len(pytest_steps), len(part_runs) + len(timing_runs))


def collected(*arguments):
    """pytest が選ぶ試験の名前（集めるだけで、流さない。.pyc とキャッシュは書かない）。"""
    process = subprocess.run([sys.executable, "-B", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
                             + list(arguments), cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    output = process.stdout.decode("utf-8", "replace")
    if process.returncode != 0:
        raise AssertionError(output + process.stderr.decode("utf-8", "replace"))
    return [line for line in output.splitlines() if "::" in line]


@unittest.skipUnless(importlib.util.find_spec("pytest"), "pytest がない")
class HookTest(unittest.TestCase):
    """conftest.py のフックそのものを、pytest に集めさせて確かめる（流さない）。"""

    FILES = ("tests/test_ci_parts.py", "tests/test_v200_check_start.py", "tests/test_v200_hook.py")

    def test_parts_cover_the_selected_tests_exactly_once(self):
        whole = collected("-m", "not timing", *self.FILES)
        self.assertTrue(whole)
        for total in (2, 3):
            parts = [collected("-m", "not timing", "--part", "{}/{}".format(index, total), *self.FILES)
                     for index in range(1, total + 1)]
            self.assertEqual(sorted(name for part in parts for name in part), sorted(whole))
            self.assertLessEqual(max(len(part) for part in parts) - min(len(part) for part in parts), 1)

    def test_tests_marked_by_name_are_timing(self):
        timing = collected("-m", "timing", *self.FILES)
        for name in literal("_TIMED_BY_NAME"):
            self.assertIn("tests/" + name, timing)
        self.assertEqual(set(timing) & set(collected("-m", "not timing", *self.FILES)), set())


if __name__ == "__main__":
    unittest.main()
