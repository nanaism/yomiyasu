"""lint と diff の組み込みの正規表現が、この Python ですべて組めることを確かめる。

読み込みのときに組む正規表現は、初めて使うときに組む（_lazy_compile）。試験の文で使わない正規表現は、書き誤りや、
この Python のバージョンで使えない書き方があっても、ほかの試験では見つからない。ここで、読み込んだあとにある
_LazyPattern をすべて組む。

3.0.1 で足した確かめ:
- 組むときに Python が警告を出す書き方（文字の集合の中の「[[」など）がない。読み込みのときに組んでいた 3.0.0 までは、
  警告がどの実行でも標準エラーに出たので気づけた。初めて使うときに組む形では、その正規表現を使う文書でしか出ない。
- 関数の外で re.compile を呼んでいない（読み込みのときに組む形に戻っていない）。
- _lazy_compile が返すもの（_LazyPattern）を re の関数に渡していない。re.Pattern ではないので、渡すと TypeError になる。
"""
from pathlib import Path
import ast
import gc
import re
import sys
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402

SOURCES = (ROOT / "scripts" / "yomiyasu_lint.py", ROOT / "scripts" / "yomiyasu_diff.py")


def _is_re_attribute(node, names=None):
    """node が re.名前 の形か。names を渡すと、その名前のときだけ。"""
    return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "re"
            and (names is None or node.attr in names))


def eager_compiles(tree):
    """関数の外（読み込みのときに動く所）にある re.compile の呼び出しの行。
    関数の既定値とデコレータは定義のときに動くので、関数の外として数える。"""
    found = []
    pending = [(tree, False)]
    while pending:
        node, inside = pending.pop()
        if isinstance(node, ast.Call) and not inside and _is_re_attribute(node.func, ("compile",)):
            found.append(node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = node.args
            outside = list(arguments.defaults) + [item for item in arguments.kw_defaults if item is not None]
            if not isinstance(node, ast.Lambda):
                outside += list(node.decorator_list)
            body = [node.body] if isinstance(node, ast.Lambda) else list(node.body)
            pending.extend((item, inside) for item in outside)
            pending.extend((item, True) for item in body)
            continue
        pending.extend((child, inside) for child in ast.iter_child_nodes(node))
    return sorted(found)


def lazy_names(tree):
    """モジュールの名前のうち、_lazy_compile の結果か、それを入れた入れ物（辞書、タプル、内包表記など）を持つもの。
    その名前をそのまま別の名前に入れた別名も含める。"""
    names = set()
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            holds = any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "_lazy_compile"
                        for item in ast.walk(value))
            alias = isinstance(value, ast.Name) and value.id in names
            if not (holds or alias):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
    return names


def lazy_misuses(tree):
    """_LazyPattern を re.Pattern として扱っている所の (行, 説明)。
    re の関数の引数に、lazy_names の名前（か、その入れ物の要素）をそのまま渡す形と、isinstance(…, re.Pattern)。"""
    names = lazy_names(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_re_attribute(node.func):
            for argument in node.args:
                base = argument.value if isinstance(argument, ast.Subscript) else argument
                if isinstance(base, ast.Name) and base.id in names:
                    found.append((node.lineno, "re.{}({}…)".format(node.func.attr, base.id)))
        elif isinstance(node.func, ast.Name) and node.func.id == "isinstance" and len(node.args) == 2:
            kinds = node.args[1].elts if isinstance(node.args[1], ast.Tuple) else [node.args[1]]
            if any(_is_re_attribute(kind, ("Pattern",)) for kind in kinds):
                found.append((node.lineno, "isinstance(…, re.Pattern)"))
    return sorted(found)


class LazyPatternTest(unittest.TestCase):
    def test_every_builtin_pattern_compiles(self):
        for module in (yomiyasu_lint, yomiyasu_diff):
            with self.subTest(module=module.__name__):
                patterns = [value for value in gc.get_objects() if type(value) is module._LazyPattern]
                self.assertTrue(patterns)
                broken = []
                for pattern in patterns:
                    try:
                        pattern.groups
                    except re.error as error:
                        broken.append((pattern.pattern[:80], str(error)))
                self.assertEqual(broken, [])

    def test_no_builtin_pattern_warns(self):
        """組むときに警告を出す正規表現がない。同じプロセスで先に使われた正規表現は組んだものが残っているので、
        re のキャッシュを空にしてから、文字列と flags で組み直して確かめる。"""
        for module in (yomiyasu_lint, yomiyasu_diff):
            with self.subTest(module=module.__name__):
                patterns = [value for value in gc.get_objects() if type(value) is module._LazyPattern]
                self.assertTrue(patterns)
                warned = []
                re.purge()
                with warnings.catch_warnings():
                    warnings.simplefilter("error")
                    for pattern in patterns:
                        try:
                            re.compile(pattern.pattern, pattern._flags)
                        except (Warning, re.error) as problem:
                            warned.append((pattern.pattern[:80], "{}: {}".format(type(problem).__name__, problem)))
                self.assertEqual(warned, [])


class LazyGuardTest(unittest.TestCase):
    """lint と diff のソースを読み、初めて使うときに組む形が保たれていることを確かめる。"""

    def test_no_compile_while_loading(self):
        for path in SOURCES:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertEqual(eager_compiles(tree), [],
                                 "関数の外の re.compile は _lazy_compile にする（読み込みのたびに組まないため）")

    def test_wrappers_are_not_used_as_compiled_patterns(self):
        for path in SOURCES:
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                self.assertTrue(lazy_names(tree))
                self.assertEqual(lazy_misuses(tree), [],
                                 "_lazy_compile の結果は re.Pattern ではない。.search などを呼ぶか、.pattern で文字列を渡す")

    def test_the_guards_find_what_they_look_for(self):
        """見張りそのものの確かめ。戻した形と誤った使い方を書いた短いソースで、見つかることを見る。"""
        eager = ast.parse(
            "import re\n"
            "A = re.compile('a')\n"
            "B = [re.compile(item) for item in ('b', 'c')]\n"
            "def f(x=re.compile('d')):\n"
            "    return re.compile('e')\n"
            "C = lambda: re.compile('f')\n"
        )
        self.assertEqual(eager_compiles(eager), [2, 3, 4])
        misuse = ast.parse(
            "import re\n"
            "A = _lazy_compile('a')\n"
            "TABLE = {'k': _lazy_compile('b')}\n"
            "ALIAS = A\n"
            "PLAIN = 'c'\n"
            "def f(text, name):\n"
            "    re.sub(A, '', text)\n"
            "    re.search(TABLE[name], text)\n"
            "    re.split(ALIAS, text)\n"
            "    isinstance(text, (str, re.Pattern))\n"
            "    re.search(PLAIN, text)\n"
            "    re.compile(A.pattern)\n"
            "    return A.search(text)\n"
        )
        self.assertEqual(lazy_names(misuse), {"A", "TABLE", "ALIAS"})
        self.assertEqual([line for line, _ in lazy_misuses(misuse)], [7, 8, 9, 10])


if __name__ == "__main__":
    unittest.main()
