"""3.0.0: metaphor_verb の「前提が崩れる」を、崩れています、崩れました、崩れやすい などのどの形にも、「前提も崩れ」にも当てる。

この規則だけ、指摘の文を「中身が前後の文にあればその中身で書き、なければ本文を残して尋ねる」手順の文にして、
references/slop-catalog.md 10章を指す（ほかの metaphor_verb の文は変えない）。warn のままで、点数と判定は前と同じ扱い。
文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402

PREMISE_MESSAGE = ("抽象比喩「前提が崩れる」が検出されました。前提の中身が前後の文にあれば、その中身で書いてください。"
                   "なければ本文を残し、何が成り立たなくなったかを尋ねてください（references/slop-catalog.md 10章）。"
                   "文字どおりの地盤や土台のことなら、直さずに残してください。")
OTHER_TAIL = ("が検出されました。不自然な比喩動詞であれば、ふだん使う動詞や客観的な表現に書き直してください。ただし、"
              "文字どおりの動作や状態変化を表している場合は無理に言い換える必要はありません。")


def metaphor(text):
    return [f for f in yomiyasu_lint.lint_text(text)["findings"] if f["rule"] == "metaphor_verb"]


class PremiseTest(unittest.TestCase):
    def test_widened_forms_warn(self):
        for text in ("新しい料金表では、この前提が崩れています。", "前提が崩れますので、見積もりを出し直します。",
                     "この前提は崩れやすいので、前提が崩れやすい所から見ます。", "先月の数字で、前提が崩れました。",
                     "前提が崩れていて、表の数字が合いません。", "この前提も崩れていて、出し直しが要ります。",
                     "古い基盤が崩れつつあります。", "前提が崩れずに残ったのは、二つだけです。"):
            with self.subTest(text=text):
                found = metaphor(text)
                self.assertEqual(len(found), 1, found)
                self.assertEqual(found[0]["severity"], "warn")
                self.assertEqual(found[0]["message"], PREMISE_MESSAGE)

    def test_existing_forms_still_warn(self):
        for text in ("このままでは前提が崩れる。", "その時点で前提が崩れた。"):
            with self.subTest(text=text):
                found = metaphor(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], PREMISE_MESSAGE)
                self.assertEqual(found[0]["snippet"], text)

    def test_literal_breaks_not_marked(self):
        for text in ("午後から天気が崩れます。", "積み木が崩れました。", "体調が崩れて、休みました。",
                     "前提の理解がずれていると、全体の設計が崩れやすくなります。",
                     "前提は、郊外店については当てはまりません。"):
            with self.subTest(text=text):
                self.assertEqual(metaphor(text), [])

    def test_other_messages_unchanged(self):
        """ほかの metaphor_verb の文は前と一字も同じ。"""
        for text, desc in (("このままでは、夜間の処理が静かに壊れる。", "英語直訳「静かに壊れる (silently fail)」"),
                           ("判断に迷ったら、安全側に倒します。", "判断を方向で表現する「〜側に倒す」"),
                           ("設定を変えると、データが壊れる。", "比喩動詞「壊れる」")):
            with self.subTest(text=text):
                found = [f for f in metaphor(text) if f["message"].startswith(desc)]
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], desc + OTHER_TAIL)
        self.assertEqual(list(yomiyasu_lint._METAPHOR_VERB_MESSAGE_TAILS), [r"(前提|基盤)(?:が|も)崩れ[るた]?"])

    def test_score_and_strict_same_as_other_warns(self):
        result = yomiyasu_lint.lint_text("新しい料金表では、この前提が崩れています。")
        self.assertEqual(result["counts"]["warn"], 1)
        self.assertLess(result["rule_penalty_score"], 100)

    def test_allow_removes_by_phrase(self):
        found = [f for f in self.lint_kept("この前提が崩れています。") if f["rule"] == "metaphor_verb"]
        self.assertEqual(found[0]["_words"][0], "前提が崩れる")
        words = {"path": "/x", "allow": ("前提が崩れる",), "flag": (), "allow_lines": 1, "flag_lines": 0,
                 "allow_sha256": None, "flag_sha256": None}
        for text in ("この前提が崩れています。", "この前提も崩れています。"):
            with self.subTest(text=text):
                result = yomiyasu_lint.lint_text(text, words=words)
                self.assertEqual([f for f in result["findings"] if f["rule"] == "metaphor_verb"], [])
                self.assertEqual(result["context"]["words"]["allow_removed"]["metaphor_verb"], 1)

    def lint_kept(self, text):
        original = yomiyasu_lint._public_finding
        yomiyasu_lint._public_finding = lambda finding: dict(finding)
        try:
            return yomiyasu_lint.lint_text(text)["findings"]
        finally:
            yomiyasu_lint._public_finding = original

    def test_corpus_human_unchanged(self):
        for path in sorted((ROOT / "tests" / "corpus" / "human").glob("*.md")):
            with self.subTest(path=path.name):
                self.assertEqual([f for f in metaphor(path.read_text(encoding="utf-8"))
                                  if "前提が崩れる" in f["message"]], [])


if __name__ == "__main__":
    unittest.main()
