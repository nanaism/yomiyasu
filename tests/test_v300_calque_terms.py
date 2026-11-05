"""3.0.0: calque の型4に足した字（枝、題、罫）と、型5（英語の術語に当てた2字以上の名詞。背景実行、基準線、時間窓、根因、
台本、見張り など）。

型4の字と型5の語は、人の文でも文字どおりに使う（木の枝、作文の題、便箋の罫、写真の背景、舞台の台本、見張りに立つ）ので、
語ごとに技術の文書でしか使わない形か文脈の語に限る。人の文のつもりで書いた文に印がつかないこと、文脈の語を抜くと印が
消えることも確かめる。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import markdown_visibility  # noqa: E402
import yomiyasu_lint  # noqa: E402
from portable import paced_limit, timing_clock  # noqa: E402

TYPE4 = "型4: 英語の短い術語に当てた漢字1字の名詞"
TYPE5 = "型5: 英語の術語に当てた2字以上の名詞"


def calque(text, words=None, doc_type=None):
    """lint_text の結果のうち calque の候補（内部の欄 _words も残す）。"""
    original = yomiyasu_lint._public_finding
    yomiyasu_lint._public_finding = lambda finding: dict(finding)
    try:
        result = yomiyasu_lint.lint_text(text, words=words, doc_type=doc_type)
    finally:
        yomiyasu_lint._public_finding = original
    return [f for f in result["findings"] if f["rule"] == "calque"]


def new_marks(text, doc_type=None):
    """型4の新しい字（枝、題、罫）か型5に当たった calque の候補。"""
    return [f for f in calque(text, doc_type=doc_type)
            if TYPE5 in f["message"] or any(word in ("枝", "題", "罫") for word in f["_words"])]


# (文, 型, 当たった言い方)
TARGETS = (
    ("作業が終わったら、修正の枝を main にマージしてください。", 4, "枝"),
    ("PR の題には、変更した画面の名前を書いてください。", 4, "題"),
    ("コミットの題は、50字以内にしてください。", 4, "題"),
    ("見出しの下の罫を、CSS で細くしました。", 4, "罫"),
    ("テストは背景実行にして、終わったらログを確かめます。", 5, "背景実行"),
    ("ビルドを背景で走らせて、そのあいだに設定を見直します。", 5, "背景"),
    ("背景ジョブの数を、夜だけ減らします。", 5, "背景ジョブ"),
    ("背景タスクが終わるまで、画面を閉じないでください。", 5, "背景タスク"),
    ("前回の計測を基準線にして、処理時間の増減を比べます。", 5, "基準線"),
    ("前回のベンチマークを基準線にします。", 5, "基準線"),
    ("直近10分の時間窓で、エラーの件数を数えます。", 5, "時間窓"),
    ("表の下罫が二重に見えるので、CSS の border を一本にします。", 5, "下罫"),
    ("偽緑のテストがないか、失敗するはずの入力でも確かめます。", 5, "偽緑"),
    ("障害の根因は、設定ファイルを読む順番でした。", 5, "根因"),
    ("設定の生成器を直したので、出力の YAML も作り直します。", 5, "生成器"),
    ("入力の検査器を直して、空の文字列を受け付けないようにします。", 5, "検査器"),
    ("飛行中のリクエストが終わるまで、サーバーを止めません。", 5, "飛行中"),
    ("CI の見張りが、失敗したジョブを Slack に知らせます。", 5, "見張り"),
    ("見張りのプロセスは、5分ごとに起きます。", 5, "見張り"),
    ("移行の台本を実行する前に、手元の環境で一度流します。", 5, "台本"),
    ("台本を実行すると、古い表が消えます。", 5, "台本"),
)
# 人の文のつもりで書いた文（どれにも印がつかない）
KEEPS = (
    "庭の桜の枝が伸びたので、週末に切ります。",
    "月の周りに、光の環が見えました。",
    "自転車の鎖が外れたので、手で戻しました。",
    "先生が出した題で、短い作文を書きました。",
    "便箋の罫に沿って、ていねいに書きました。",
    "図面の基準線から、柱の位置を測ります。",
    "舞台の台本を読み合わせてから、立ち稽古に入ります。",
    "夜のあいだ、交代で見張りに立ちました。",
    "新しい店の品ぞろえには、目を見張りました。",
    "飛行中の機内では、ベルトを締めてお待ちください。",
    "事件の背景で何が起きたかを、記者が調べています。",
    "写真の背景で、子どもたちが遊んでいます。",
    "この写真の枝のデータを、フォルダにまとめました。",
    "国語のテストの題は、春の思い出でした。",
    "探査機が送ったデータで、土星の環の写真を作りました。",
    "ベンゼン環のデータを、表にまとめました。",
    "自転車の鎖が外れたので、近くのサービス店に持っていきました。",
    "タンパク質の鎖をコードする遺伝子を調べました。",
    "便箋の罫に沿って書いたメッセージを、封筒に入れました。",
    "罫の入ったルーズリーフを、ファイルに綴じて渡します。",
    "警備会社の見張りが、防犯カメラの画面を確かめます。",
    "見張りの交代は、無線で通知します。",
    "舞台の台本どおりに、効果音を流します。",
    "撮影は台本に沿って、カメラを回します。",
    "台本は、実行委員会へ渡します。",
    "台本を実行委員会へ渡します。",
    "完成した台本を実行委員に配りました。",
    "自己PRの題は、学生時代に力を入れたことにしました。",
    "エントリーシートの自己PRの題を、先輩に見てもらいました。",
    "商品PRの題を、店長と相談して決めます。",
    "観光PRの題は、地元の高校生が考えました。",
    "利益のマージンを確保するため、枝の剪定を自分たちで行います。",
    "週末のブランチは、桜の枝を飾ったテーブルで食べました。",
    "表の罫を0.1mmに細くしました。",
    "組版では、表の罫を細くして、数字を読みやすくします。",
    "セルの罫を太くして、合計の行を目立たせます。",
    "表の下罫が二重に見えるので、定規で引き直します。",
    "左罫と右罫のある便箋に、手紙を書きました。",
    "陸上競技の計測では、基準線から跳んだ距離を測ります。",
    "写真の背景で動く人影が気になります。",
    "映画の背景で走る列車が好きです。",
    "背景で回る観覧車がきれいでした。",
    "グラフの基準線を、データに合わせて引き直しました。",
    "発症から4.5時間という時間窓があります。",
    "信号に時間窓をかけて、データを切り出します。",
    "手荷物の検査器を通るときは、上着を脱ぎます。",
    "リモートで庭師さんにお願いしたら、伸びた枝を切ってくれました。",
    "写真をコミットしたいので、桜の枝の写真を撮りました。",
    "オゾン生成器を部屋に置きました。",
    "酸素生成器が動いています。",
    "枝豆をゆでて、枝分かれした道を歩きました。",
    "大きな問題が残っています。",
    "環境構築の手順です。",
    "下罫線を引いた表を、印刷して配ります。",
    "背景処理の画像を、ファイルに保存します。",
)


class CalqueTermsTest(unittest.TestCase):
    def test_targets_are_marked(self):
        for text, number, word in TARGETS:
            with self.subTest(text=text):
                found = calque(text)
                self.assertEqual(len(found), 1, found)
                self.assertEqual(found[0]["severity"], "info")
                self.assertIn(TYPE4 if number == 4 else TYPE5, found[0]["message"])
                self.assertIn("当たった言い方: " + word, found[0]["message"])
                self.assertIn(word, found[0]["_words"])

    def test_keeps_are_not_marked(self):
        for text in KEEPS:
            with self.subTest(text=text):
                self.assertEqual(calque(text), [])

    def test_context_is_required(self):
        """同じ文から文脈の語だけを抜くと、印が消える。"""
        for marked, plain in (
                ("修正の枝を main にマージしてください。", "修正の枝を庭に運んでください。"),
                ("修正の枝を、マージの前に見直します。", "修正の枝を、植える前に見直します。"),
                ("見出しの下の罫を、CSS で細くしました。", "見出しの下の罫を、鉛筆で細くしました。"),
                ("前回のベンチマークを基準線にします。", "前回の計測を基準線にします。"),
                ("下罫を CSS で消します。", "下罫を定規で引きます。"),
                ("直近10分の時間窓を使います。", "この10分の時間窓を使います。"),
                ("CI の見張りが知らせます。", "門の見張りが知らせます。"),
                ("移行の台本を読みます。", "舞台の台本を読みます。"),
                ("入力の検査器を直します。", "空港の検査器を直します。"),
                ("PR の題を直します。", "作文の題を直します。")):
            with self.subTest(marked=marked):
                self.assertEqual(len(calque(marked)), 1)
                self.assertEqual(calque(plain), [])

    def test_dropped_words_are_not_marked(self):
        """環と鎖は根拠が弱く、人の文に当たるので、技術の文でも印をつけない。"""
        for text in ("リトライの環が止まらず、ジョブが同じ API を呼び続けました。",
                     "依存の鎖をたどると、古いライブラリが3つ見つかりました。"):
            with self.subTest(text=text):
                self.assertEqual(calque(text), [])

    def test_types_listed_on_one_line(self):
        found = calque("今回の版と、背景実行の設定を見直します。")
        self.assertEqual(len(found), 1)
        self.assertIn(TYPE4 + "。" + TYPE5 + "。当たった言い方: 版、背景実行）", found[0]["message"])
        self.assertEqual(found[0]["_words"], ("版", "背景実行"))

    def test_words_are_the_matched_text(self):
        """型5の当たった言い方は、本文の字のまま（表の名前ではない）。"""
        self.assertEqual(calque("背景タスクを止めます。")[0]["_words"], ("背景タスク",))
        self.assertEqual(calque("左罫を CSS で消します。")[0]["_words"], ("左罫",))
        self.assertEqual(calque("ビルドを背景で走らせます。")[0]["_words"], ("背景",))

    def test_kanji1_table_unchanged(self):
        """2.4.0 の型4の試験の文は、前と同じ結果と message。"""
        import test_v240_kanji1 as v240
        for text, word in v240.TARGETS:
            with self.subTest(text=text):
                found = [f for f in calque(text) if TYPE4 in f["message"]]
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], "直訳語（{}。当たった言い方: {}）{}".format(
                    TYPE4, word, yomiyasu_lint._V220_MESSAGE_TAIL))
        for text in v240.KEEPS:
            with self.subTest(text=text):
                self.assertEqual([f for f in calque(text) if TYPE4 in f["message"]], [])
        for word, marked_text, literal, marked in v240.TABLE:
            with self.subTest(word=word):
                self.assertEqual(calque(literal), [])
                self.assertEqual(bool([f for f in calque(marked_text) if TYPE4 in f["message"]]), marked)

    def test_metaphor_verb_line_blocks_new_types(self):
        for text in ("修正の枝を main にマージすると、前提が崩れる。", "移行の台本を実行すると、前提が崩れる。"):
            with self.subTest(text=text):
                result = yomiyasu_lint.lint_text(text)
                self.assertIn("metaphor_verb", [f["rule"] for f in result["findings"]])
                self.assertEqual(calque(text), [])

    def test_quotes_code_identifiers_not_scanned(self):
        for text in ("「背景実行」という語は、引用では見ない。", "`背景実行` はコードの中です。",
                     "“CI の見張り” は引用符の中です。", "> テストは背景実行にします。"):
            with self.subTest(text=text):
                self.assertEqual(calque(text), [])

    def test_headings_tables_lists_scanned(self):
        text = "# 背景実行の設定\n\n- 根因の一覧\n\n| 項目 | 中身 |\n|---|---|\n| PR の題 | 短く書く |\n"
        self.assertEqual([f["line"] for f in calque(text)], [1, 3, 7])

    def test_score_unaffected(self):
        for text, _, _ in TARGETS:
            with self.subTest(text=text):
                result = yomiyasu_lint.lint_text(text)
                self.assertEqual(result["rule_penalty_score"], 100)
                self.assertEqual(result["counts"]["warn"], 0)

    def test_allow_removes_each_word(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        (Path(folder.name) / "allow.txt").write_bytes("枝\n背景タスク\n".encode("utf-8"))
        words = markdown_visibility.load_words(folder.name)
        found = calque("修正の枝を main にマージして、背景実行にします。", words=words)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["_words"], ("背景実行",))
        self.assertIn("当たった言い方: 背景実行）", found[0]["message"])
        self.assertNotIn(TYPE4, found[0]["message"])
        self.assertEqual(calque("背景タスクを止めます。", words=words), [])
        self.assertEqual(len(calque("背景ジョブを止めます。", words=words)), 1)

    def test_doc_type_does_not_skip(self):
        for row in markdown_visibility.DOC_TYPES:
            with self.subTest(doc_type=row[0]):
                self.assertEqual(len(calque("障害の根因は、設定ファイルを読む順番でした。", doc_type=row[0])), 1)

    def test_corpus_human_has_no_new_marks(self):
        paths = sorted((ROOT / "tests" / "corpus" / "human").glob("*.md"))
        self.assertTrue(paths)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for doc_type in (None,) + tuple(row[0] for row in markdown_visibility.DOC_TYPES):
                with self.subTest(path=path.name, doc_type=doc_type):
                    self.assertEqual(new_marks(text, doc_type=doc_type), [])

    def test_corpus_has_no_new_marks(self):
        for path in sorted((ROOT / "tests" / "corpus").rglob("*.md")):
            with self.subTest(path=path.name):
                self.assertEqual(new_marks(path.read_text(encoding="utf-8")), [])

    def test_own_documents_have_no_new_marks(self):
        paths = [ROOT / "skills" / "yomiyasu" / "SKILL.md", ROOT / "README.md", ROOT / "README.en.md"]
        paths += sorted((ROOT / "references").rglob("*.md")) + sorted((ROOT / "docs").glob("*.md"))
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual([f["line"] for f in new_marks(path.read_text(encoding="utf-8"))], [])

    def test_long_lines_finish_quickly(self):
        texts = ["枝" * 100000 + "\n", "背景" * 50000 + "\n", "見張り" * 33000 + "\n", "問題" * 50000 + "\n",
                 "PR の題と" * 20000 + "\n", "CI の" * 25000 + "見張り\n"]
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
