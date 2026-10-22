"""v2.2.0: 台詞・脚本の推敲で台詞の最後の「。」だけを外した組を、diff が問いの変化に数えないことを確かめる。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402


def question_risks(old, new):
    return [risk for risk in yomiyasu_diff.diff(old, new)["meaning_risks"]
            if risk["kind"] == "sentence_type" and risk.get("subkind") == "question"]


class FinalDialoguePeriodTest(unittest.TestCase):
    def test_removing_only_the_final_period_is_not_a_question_change(self):
        for old, new in (("圭介「棚の鍵は持ったのか。」\n", "圭介「棚の鍵は持ったのか」\n"),
                         ("「今日も来るのか。」\n", "「今日も来るのか」\n"),
                         ("早苗『もう決めたのか。』\n", "早苗『もう決めたのか』\n")):
            with self.subTest(old=old):
                self.assertEqual(question_risks(old, new), [])

    def test_other_changes_are_still_counted(self):
        """問いを言い切りにした組と、括弧の外の「か。」の句点を外した組は、今までどおり問いの変化に数える。"""
        for old, new in (("圭介「棚の鍵は持ったのか。」\n", "圭介「棚の鍵は持った」\n"),
                         ("棚の鍵は持ったのか。\n", "棚の鍵は持ったのか\n"),
                         ("圭介「棚の鍵は持ったのか。」\n", "圭介「棚の鍵を持った。」\n")):
            with self.subTest(old=old, new=new):
                self.assertEqual(len(question_risks(old, new)), 1)


if __name__ == "__main__":
    unittest.main()
