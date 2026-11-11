"""lint と diff の組み込みの正規表現が、この Python ですべて組めることを確かめる。

読み込みのときに組む正規表現は、初めて使うときに組む（_lazy_compile）。試験の文で使わない正規表現は、書き誤りや、
この Python のバージョンで使えない書き方があっても、ほかの試験では見つからない。ここで、読み込んだあとにある
_LazyPattern をすべて組む。
"""
from pathlib import Path
import gc
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
