"""v2.4.0: calque の型4（英語の短い術語に当てた漢字1字の名詞。今回の版、lint の印、一覧の頭）。

版は連体の修飾を受けて名詞として使う形、印は検査や推敲の語がある文の1字の印、頭は行や一覧や PR の「頭」に印をつける。
出版物の版、記号の印、体や慣用の頭には印をつけない。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_lint  # noqa: E402

TYPE4 = "型4: 英語の短い術語に当てた漢字1字の名詞"


def type4(text, words=None, keep_words=False):
    """lint_text の結果のうち、calque の型4の候補（keep_words なら内部の欄 _words も残す）。"""
    original = yomiyasu_lint._public_finding
    if keep_words:
        yomiyasu_lint._public_finding = lambda finding: dict(finding)
    try:
        if words is None:
            result = yomiyasu_lint.lint_text(text)
        else:
            result = yomiyasu_lint.lint_text(text, words=words)
    finally:
        yomiyasu_lint._public_finding = original
    return [f for f in result["findings"] if f["rule"] == "calque" and TYPE4 in f["message"]]


TARGETS = (
    ("今回の版では、設定の読み込みを速くしました。", "版"),
    ("直した版を、明日の朝に配ります。", "版"),
    ("同じ版のスクリプトを同じフォルダに置いてください。", "版"),
    ("版ごとに、変更点を一覧にまとめています。", "版"),
    ("版の文字列は、package.json から読みます。", "版"),
    ("次の版（3.1）で、古い設定を外します。", "版"),
    ("手元の版と公開中の版で、出力が違います。", "版"),
    ("管理職向けの短い版も作れます。", "版"),
    ("Python の版によって、結果が変わります。", "版"),
    ("lint は、この文に印をつけます。", "印"),
    ("推量の印が消えた文を数えます。", "印"),
    ("検証に通らなかった行には印をつけて、ログに残します。", "印"),
    ("新しい印は3件で、どれも calque でした。", "印"),
    ("最終稿に残った印は、一つずつ見直します。", "印"),
    ("穴のある記録には印をつけて、元に戻してから入れ直しています。", "印"),
    ("diff の印が消えた文を見直します。", "印"),
    ("一覧の頭には、最新の5件を固定で出します。", "頭"),
    ("出力の頭の2行だけを見ます。", "頭"),
    ("PR の頭から ZIP を作って確かめます。", "頭"),
    ("段落の頭に、結論を置いてください。", "頭"),
    ("ログの頭に、日付を付けます。", "頭"),
    ("今回の版で回帰が出た。", "版"),
)
KEEPS = (
    "この本の新しい版では、第3章を書き直した。",
    "日本語吹き替え版を、来月から配信します。",
    "iPhone 版とアンドロイド版で、画面が違います。",
    "版画の版を彫るのに、三日かかった。",
    "新聞の最終版に、訂正を載せました。",
    "第2版を刷るときに、誤植を直します。",
    "改訂版は、来年の春に出ます。",
    "同じ版の写真集を、二冊持っている。",
    "地図に赤ペンで印をつけた。",
    "該当する項目に印をつけてください。",
    "用紙を印の線まで入れます。",
    "感謝の印として、花を贈りました。",
    "箱のふたに、部署名と印をつけてください。",
    "右上の×印をクリックすると閉じます。",
    "カレンダーの予定日に、印をつけておきました。",
    "受賞作は★印で示しています。",
    "これは成功の印だと思う。",
    "表の3行目に印をつけてください。",
    "テストで間違えた所に印をつけた。",
    "試験に出る所に、先生が印をつけてくれた。",
    "朝から頭が痛い。",
    "頭の中で手順を並べた。",
    "曲の頭から、もう一度弾いてください。",
    "列の頭に並んでいた人が、最初に入場した。",
    "頭のいい人ほど、説明が短い。",
    "先頭の行に、見出しを置きます。",
    "失敗した試験には印が残ります。",
    "Mac 版と Windows 版の違いを書きます。",
    "PC 版の名前を変えます。",
    "Android 版を分けて配る。",
    "書類の右下に印を押してから、出力した控えを渡す。",
    "モンキーの頭を描いた。",
    "ロボットの頭の行動を記録する。",
)
# 15語の表: 語ごとに、英語の術語に当てた使い方の文と、文字どおりの使い方の文を1つずつ。型4の印がつくのは版、印、頭の
# 直訳の文だけ（ほかの語は、推敲の手順で扱う。v2.3.0 の推敲で直るか、何を指すかを尋ねる）。
TABLE = (
    ("版", "直した版を、明日の朝に配ります。", "改訂版は、来年の春に出ます。", True),
    ("段", "3つ目の段で、値を検証します。", "本棚の下の段に、辞書を置いた。", False),
    ("窓", "直近5分の窓で、件数を数えます。", "窓を開けて、空気を入れ替えた。", False),
    ("帯", "許容の帯を外れた値は、警告にします。", "浴衣の帯を結んでもらった。", False),
    ("系", "試験の系で動かしてから、本番に出します。", "太陽系の惑星を順に並べた。", False),
    ("口", "外部の口からの要求は、すべて認証を通します。", "口の中を少しやけどした。", False),
    ("印", "lint は、この文に印をつけます。", "地図に赤ペンで印をつけた。", True),
    ("床", "応答時間の床を200msに決めました。", "床に落ちたねじを拾った。", False),
    ("穴", "ログに穴がある時間帯は、計算から外します。", "壁にねじの穴を開けた。", False),
    ("頭", "一覧の頭には、最新の5件を固定で出します。", "朝から頭が痛い。", True),
    ("枠", "画面の上の枠に、通知を出します。", "写真の周りに白い枠を付けた。", False),
    ("箱", "構成図の箱は、それぞれ1つのサービスです。", "段ボール箱に書類を入れた。", False),
    ("旗", "旗を立てているあいだは、新しい設定を読みません。", "入口に会社の旗を立てた。", False),
    ("門", "認証の門を通らない要求は、拒否します。", "学校の門の前で待ち合わせた。", False),
    ("組", "入力と期待する出力の組を、試験に使います。", "試写会に5組10名様を招待します。", False),
)


class Kanji1CalqueTest(unittest.TestCase):
    def test_targets_are_marked_with_the_kanji(self):
        hit = 0
        for text, word in TARGETS:
            with self.subTest(text=text):
                found = type4(text, keep_words=True)
                self.assertEqual(len(found), 1, found)
                self.assertIn(word, found[0]["_words"])
                self.assertEqual(found[0]["severity"], "info")
                self.assertIn("当たった言い方: " + word, found[0]["message"])
                hit += 1
        self.assertEqual(hit, len(TARGETS))

    def test_keeps_are_not_marked(self):
        for text in KEEPS:
            with self.subTest(text=text):
                self.assertEqual(type4(text), [])

    def test_fifteen_word_table(self):
        for word, calque, literal, marked in TABLE:
            with self.subTest(word=word):
                self.assertEqual(type4(literal), [])
                self.assertEqual(bool(type4(calque)), marked)

    def test_translated_term_line_does_not_get_type4_version(self):
        result = yomiyasu_lint.lint_text("新しい版では、ログの出力先を変えました。")
        rules = [f["rule"] for f in result["findings"]]
        self.assertIn("translated_term", rules)
        self.assertEqual(type4("新しい版では、ログの出力先を変えました。"), [])

    def test_one_finding_per_line_lists_the_words(self):
        found = type4("PR の頭と一覧の頭に、lint の印が残っています。\n今回の版では直しました。", keep_words=True)
        self.assertEqual([f["line"] for f in found], [1, 2])
        self.assertEqual(found[0]["_words"], ("印", "頭"))
        self.assertEqual(found[1]["_words"], ("版",))

    def test_quotes_and_identifiers_are_not_scanned(self):
        self.assertEqual(type4("「lint の印」という見出しは、引用では見ない。"), [])
        self.assertEqual(type4("`一覧の頭` はコードの中です。"), [])

    def test_headings_tables_and_lists_are_scanned(self):
        text = "# lint の印の見方\n\n- 一覧の頭の行\n\n| 項目 | 中身 |\n|---|---|\n| 今回の版 | 3.1 |\n"
        self.assertEqual([f["line"] for f in type4(text)], [1, 3, 7])

    def test_score_is_not_affected(self):
        result = yomiyasu_lint.lint_text("一覧の頭には、最新の5件を固定で出します。")
        self.assertEqual(result["rule_penalty_score"], 100)

    def test_allow_removes_the_kanji(self):
        import markdown_visibility
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        (Path(folder.name) / "allow.txt").write_bytes("印\n".encode("utf-8"))
        words = markdown_visibility.load_words(folder.name)
        self.assertEqual(type4("lint は、この文に印をつけます。", words=words), [])
        self.assertEqual(len(type4("一覧の頭には、最新の5件を固定で出します。", words=words)), 1)

    def test_corpus_has_no_type4(self):
        for path in sorted((ROOT / "tests" / "corpus").rglob("*.md")):
            with self.subTest(path=path.name):
                self.assertEqual(type4(path.read_text(encoding="utf-8")), [])

    def test_own_documents_have_no_type4(self):
        paths = [ROOT / "skills" / "yomiyasu" / "SKILL.md", ROOT / "README.md"]
        paths += sorted((ROOT / "references").rglob("*.md")) + sorted((ROOT / "docs").glob("*.md"))
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual([f["line"] for f in type4(path.read_text(encoding="utf-8"))], [])


if __name__ == "__main__":
    unittest.main()
