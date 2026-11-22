"""calque の型4に足した字（段、門）。処理の流れの stage に当てた段と、CI やレビューの gate に当てた門。

段と門は、人の文でも文字どおりに使う（段落、階段、棚の段、囲碁の段、お寺の門、正門）ので、字の形と、同じ文の
処理の流れの語か検査の語の両方がそろったときだけ印をつける。名前の段（段1、段B）だけは、文脈の語がなくても印をつける。
人の文のつもりで書いた文に印がつかないこと、文脈の語を抜くと印が消えることも確かめる。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import unittest
from unittest import mock

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
    # 名前の段は、処理の流れの語がなくても当てる
    ("段1 の終わりの条件を、測る前に書きます。", "段"),
    ("段B の比べ相手を、先に流し始めました。", "段"),
    ("段10 の手順を、あとで書き直します。", "段"),
    ("前の段の出力を、次のジョブに渡します。", "段"),
    ("最後の段で、ビルドの結果をまとめます。", "段"),
    ("PR門を通った変更だけ、マージします。", "門"),
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
    # 定着した語（前段、後段、次段）と、改まった「この段」「その段」
    "前段で述べた手順の検査を、もう一度行います。",
    "同項後段の規定により、検査を行う。",
    "後段の処理で、ビルドの結果を使います。",
    "次段のジョブに渡します。",
    "その段はレビューのあとでご相談します。",
    "この段の学習では、例文を三つ読みます。",
    # 文脈の語に似た人の文の語（マージン、コミットメント、学習塾）と、1字の英字の門
    "ページのマージンを広げたら、寺の門の写真が切れた。",
    "コミットメントを示すため、彼は寺の門を叩いた。",
    "学習塾の段の上に本を置き、次の段に辞書を並べた。",
    "東京ドームのA門から入り、テストの会場へ向かった。",
    # 段位の語がある文の段は、名前の形でも文脈の語があっても当てない
    "囲碁の段3から、学習を始めました。",
    "将棋は段1から、レビューを受けられます。",
    "柔道の段2を取るまで、毎日ジョブの合間に練習した。",
    "昇段の審査で、段B の課題を出された。",
    # 小文字の英字と、漢字やカタカナのあとの段
    "段a の手順を見ます。",
    "手段1 と手段2 を比べます。",
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
                ("次の段で、学習済みのモデルを読み込みます。", "次の段で、昨日の手紙を読み返します。"),
                ("refine 段の出力を、次のジョブに渡します。", "refine 段の出力を、次の人に渡します。"),
                ("レビューの門を通ります。", "お寺の門を通ります。"),
                ("テストの門を通らない変更は、マージしません。", "学校の門を通らない変更は、取り込みません。")):
            with self.subTest(marked=marked):
                self.assertEqual(len(new_marks(marked)), 1)
                self.assertEqual(new_marks(plain), [])

    def test_rank_words_remove_the_mark(self):
        """名前の段も文脈の語のある段も、同じ文に段位の語を足すと印が消える。"""
        for marked, plain in (("段3 の手順を書きます。", "囲碁の段3 の手順を書きます。"),
                              ("次の段で、学習の結果を読みます。", "将棋の次の段で、学習の結果を読みます。")):
            with self.subTest(marked=marked):
                self.assertEqual(len(new_marks(marked)), 1)
                self.assertEqual(new_marks(plain), [])

    def test_quotes_and_code_not_scanned(self):
        """引用とコードの中の言い方には印がつかない。同じ言い方を外に出すと印がつく。"""
        for masked, plain in (("「パイプラインの第2段」という言い方は、引用では見ない。",
                               "パイプラインの第2段という言い方は、引用では見ない。"),
                              ("`レビューの門` はコードの中です。", "レビューの門 はコードの中です。"),
                              ("> CI の門で、テストを止めます。", "CI の門で、テストを止めます。"),
                              ("`段1` の名前は、コードの中です。", "段1 の名前は、コードの外です。")):
            with self.subTest(masked=masked):
                self.assertEqual(new_marks(masked), [])
                self.assertEqual(len(new_marks(plain)), 1)

    def test_score_unaffected(self):
        for text, _ in TARGETS:
            with self.subTest(text=text):
                # 3.3.0: pause_comma を種類なしでも当てる。pause_comma は点数に入るので、その候補を出さずに比べる
                with mock.patch.object(yomiyasu_lint, "DOC_TYPE_OFF_RULES", {"pause_comma": (None, "promo", "script")}):
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
        # 当たらない英数字の並び（a1a1…）は、並びの途中から検索を始め直すと入力の長さの二乗で遅くなる
        texts = ["段" * 100000 + "\n", "門" * 100000 + "\n", "a" * 100000 + " 段\n", "CI の門と" * 20000 + "\n",
                 "パイプラインの第" + "2" * 100000 + "段\n",
                 "CI 学習 " + "a1" * 50000 + " 段落。\n", "CI 学習 " + "a1" * 50000 + " 門番。\n",
                 "CI 学習 " + "a_" * 50000 + " 段落。\n", "CI 学習 " + "a-" * 50000 + " 門番。\n"]
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
