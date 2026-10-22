"""v2.1.2: 全角の小数点（３．５）を含む文を書き換えた組で、diff の数の概数・範囲の印の検査が止まらないことを確かめる。

全角の「．」は文の区切りにも読まれるので、「値は３．５％だった。」は「値は３．」と「５％だった。」に分かれる。一方、数は
「３．５％」とひとまとまりで読むので、数の終わりが文の範囲を越える。2.1.1 では、ここで AttributeError になって終了コード3で
止まっていた。今は、数を含む文の終わり（次の句点か改行）までを範囲にして、数のあとの印も半角の小数点と同じように読む。
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIFF = ROOT / "scripts" / "yomiyasu_diff.py"
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402


def kinds(old, new):
    result = yomiyasu_diff.diff(old, new)
    return [(risk["kind"], risk.get("subkind")) for risk in result["meaning_risks"]]


class FullwidthDecimalTest(unittest.TestCase):
    def test_issue_pairs_do_not_crash(self):
        """報告の3組。どれも例外にならず、半角の小数点と同じ結果になる。"""
        for old, new, half_old, half_new in (
                ("値は３．５％だった。\n", "値は４．５％だった。\n", "値は3.5％だった。\n", "値は4.5％だった。\n"),
                ("値は３．５％だった。成長した。\n", "値は３．５％だった。大きく成長した。\n",
                 "値は3.5％だった。成長した。\n", "値は3.5％だった。大きく成長した。\n")):
            with self.subTest(old=old):
                self.assertEqual(kinds(old, new), kinds(half_old, half_new))

    def test_cli_exit_code(self):
        with tempfile.TemporaryDirectory(prefix="yomiyasu-v212-") as folder:
            a, b = os.path.join(folder, "a.md"), os.path.join(folder, "b.md")
            Path(a).write_bytes("値は３．５％だった。\n".encode("utf-8"))
            Path(b).write_bytes("値は４．５％だった。\n".encode("utf-8"))
            plain = subprocess.run([sys.executable, "-B", str(DIFF), a, b], capture_output=True, timeout=60)
            self.assertEqual(plain.returncode, 0, plain.stderr.decode("utf-8"))
            self.assertEqual(plain.stderr, b"")
            failing = subprocess.run([sys.executable, "-B", str(DIFF), a, b, "--fail-on=meaning-risk"],
                                     capture_output=True, timeout=60)
            self.assertEqual(failing.returncode, 1)  # 数値が変わった（3.5 → 4.5）
            self.assertIn("数値が変わった", failing.stdout.decode("utf-8"))

    def test_markers_around_fullwidth_decimals_are_read(self):
        """数のあとの印（程度）と前の印（約）の増減を、半角の小数点と同じように拾い、同じ種類の言い換えでは出さない。"""
        for old, new, expected in (
                ("値は３．５％程度だった。\n", "値は３．５％だった。\n", [("number_qualifier", "lost")]),
                ("値は約３．５％だった。\n", "値は３．５％だった。\n", [("number_qualifier", "lost")]),
                ("値は３．５％だった。\n", "値は３．５％以上だった。\n", [("number_qualifier", "added")]),
                ("値は３．５％程度だった。\n", "値は３．５％ほどだった。\n", []),
                ("値は３．５％程度だった。\n", "値は3.5％程度だった。\n", []),
                ("値は３．５％だった。\n", "値は３．５％だった。次の文です。\n", [])):
            with self.subTest(old=old, new=new):
                found = [kind for kind in kinds(old, new) if kind[0] == "number_qualifier"]
                self.assertEqual(found, expected)
                half = [kind for kind in kinds(old.replace("３．５", "3.5"), new.replace("３．５", "3.5"))
                        if kind[0] == "number_qualifier"]
                self.assertEqual(found, half)

    def test_number_at_the_end_without_sentence_end(self):
        """句点も改行もない終わりの数でも止まらない。"""
        self.assertEqual([k for k in kinds("値は３．５", "値は約３．５") if k[0] == "number_qualifier"],
                         [("number_qualifier", "added")])


if __name__ == "__main__":
    unittest.main()
