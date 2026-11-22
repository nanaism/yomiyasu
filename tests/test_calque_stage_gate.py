"""calque の型4に足した字（段、門）。処理の流れの stage に当てた段と、CI やレビューの gate に当てた門。

段と門は、人の文でも文字どおりに使う（段落、階段、棚の段、囲碁の段、お寺の門、正門）ので、字の形と、同じ文の
処理の流れの語か検査の語の両方がそろったときだけ印をつける。人の文のつもりで書いた文に印がつかないこと、
文脈の語を抜くと印が消えることも確かめる。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402
from portable import paced_limit, timing_clock  # noqa: E402

TYPE4 = "型4: 英語の短い術語に当てた漢字1字の名詞"
WORDS = ("段", "門")


def type4(text, doc_type=None):
    """lint_text の結果のうち calque の型4の候補（内部の欄 _words も残す）。"""
    original = yomiyasu_lint._public_finding
    yomiyasu_lint._public_finding = lambda finding: dict(finding)
    try:
        result = yomiyasu_lint.lint_text(text, doc_type=doc_type)
    finally:
        yomiyasu_lint._public_finding = original
    return [f for f in result["findings"] if f["rule"] == "calque" and TYPE4 in f["message"]]


def new_marks(text, doc_type=None):
    """型4の新しい字（段、門）に当たった候補。"""
    return [f for f in type4(text, doc_type=doc_type) if any(word in WORDS for word in f["_words"])]


# (文, 当たった言い方)
TARGETS = (
    ("段B の学習が終わったら、段C に進みます。", "段"),
    ("段1 のビルドが終わってから、段2 に進みます。", "段"),
    ("パイプラインの第2段で、前処理の結果を確かめます。", "段"),
    ("refine 段の出力を、次のジョブに渡します。", "段"),
    ("各段の前処理は、別のスクリプトで動かします。", "段"),
    ("抽出の段で、LLM が見出しを返します。", "段"),
    ("次の段で、学習済みのモデルを読み込みます。", "段"),
    ("レビューの門を通らないと、PR はマージできません。", "門"),
    ("CI の門で、lint の結果を確かめます。", "門"),
)
# 人の文のつもりで書いた文と、数の後の段（どれにも印がつかない）
KEEPS = (
    "この段落では、学習の手順を説明します。",
    "推論は、3つの段階に分けて進めます。",
    "前処理の手段を、二つ比べます。",
    "値段の比較を、スクリプトで自動にしました。",
    "普段のレビューでは、差分だけを読みます。",
    "格段に速いビルドになりました。",
    "階段の掃除が終わったら、ビルドを始めます。",
    "2 段の LSTM で学習します。",
    "棚の2段目に、ビルドの手順書を置きました。",
    "将棋は段3から、指導対局を受けられます。",
    "ロケットの第2段が切り離されました。",
    "本棚の下の段に、辞書を置いた。",
    "大学の正門の前で、テストの結果を待った。",
    "関門海峡を渡る前に、マージを済ませた。",
    "お寺の門をくぐりました。",
    "学校の門の前で待ち合わせた。",
)


class CalqueStageGateTest(unittest.TestCase):
    def test_targets_are_marked(self):
        for text, word in TARGETS:
            with self.subTest(text=text):
                found = type4(text)
                self.assertEqual(len(found), 1, found)
                self.assertEqual(found[0]["severity"], "info")
                self.assertIn("当たった言い方: " + word, found[0]["message"])
                self.assertIn(word, found[0]["_words"])

    def test_keeps_are_not_marked(self):
        for text in KEEPS:
            with self.subTest(text=text):
                self.assertEqual(new_marks(text), [])

    def test_context_is_required(self):
        """同じ文から処理の流れの語か検査の語だけを抜くと、印が消える。"""
        for marked, plain in (
                ("パイプラインの第2段で、値を変えます。", "ロケットの第2段で、値を変えます。"),
                ("段B の学習が終わりました。", "段B の練習が終わりました。"),
                ("refine 段の出力を、次のジョブに渡します。", "refine 段の出力を、次の人に渡します。"),
                ("レビューの門を通ります。", "お寺の門を通ります。"),
                ("テストの門を通らない変更は、マージしません。", "学校の門を通らない道は、遠回りです。")):
            with self.subTest(marked=marked):
                self.assertEqual(len(new_marks(marked)), 1)
                self.assertEqual(new_marks(plain), [])

    def test_quotes_and_code_not_scanned(self):
        for text in ("「パイプラインの第2段」という言い方は、引用では見ない。", "`レビューの門` はコードの中です。",
                     "> CI の門で、テストを止めます。"):
            with self.subTest(text=text):
                self.assertEqual(new_marks(text), [])

    def test_score_unaffected(self):
        for text, _ in TARGETS:
            with self.subTest(text=text):
                result = yomiyasu_lint.lint_text(text)
                self.assertEqual(result["rule_penalty_score"], 100)
                self.assertEqual(result["counts"]["warn"], 0)

    def test_corpus_has_no_new_marks(self):
        paths = sorted((ROOT / "tests" / "corpus").rglob("*.md"))
        self.assertTrue(paths)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for doc_type in (None,) + tuple(row[0] for row in markdown_visibility.DOC_TYPES):
                with self.subTest(path=path.name, doc_type=doc_type):
                    self.assertEqual(new_marks(text, doc_type=doc_type), [])

    def test_own_documents_have_no_new_marks(self):
        paths = [ROOT / "skills" / "yomiyasu" / "SKILL.md", ROOT / "README.md", ROOT / "README.en.md"]
        paths += sorted((ROOT / "references").rglob("*.md")) + sorted((ROOT / "docs").glob("*.md"))
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual([f["line"] for f in new_marks(path.read_text(encoding="utf-8"))], [])

    def test_long_lines_finish_quickly(self):
        texts = ["段" * 100000 + "\n", "門" * 100000 + "\n", "a" * 100000 + " 段\n", "CI の門と" * 20000 + "\n",
                 "パイプラインの第" + "2" * 100000 + "段\n"]
        for text in texts:
            with self.subTest(head=text[:6]):
                clock = timing_clock()
                started = clock()
                yomiyasu_lint.lint_text(text)
                elapsed = clock() - started
                limit, detail = paced_limit(2.0, elapsed)
                self.assertLess(elapsed, limit, detail)


if __name__ == "__main__":
    unittest.main()
