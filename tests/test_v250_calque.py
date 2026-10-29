"""v2.5.0: calque の型1の定着した言い方の副詞（2章）、比喩の「効く」の見落とし（3章）、型3に足した句（3章、4章）。

2章: テストが通る、キャッシュが効く などの定着した言い方の助詞と動詞の間に入れてよい副詞を、主語の語ごとの一覧から
共通の一覧（_CALQUE_ESTABLISHED_ADVERBS）にした。副詞は2つまで、助詞と副詞のあとの読点も許す。機械が主語の型1は残す。
3章: 3つ目の形（効いてくる）の同じ文と前の3行の判定で、キャッシュや最適化のようなソフトウェアの語を使わない。
何が大事かを言う「ここで効いてくるのが」を型3の句にした。文字どおりの使い方と慣用句には出さない。
4章: 型3に「〜レベルの」と「テーブルの上にある」を足した。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_lint  # noqa: E402

TYPE1 = "型1: 機械やシステムが人の動作をする言い方"
TYPE3 = "型3: 英語の言い方を一語ずつ写した句"


def findings(text, **options):
    return yomiyasu_lint.lint_text(text if text.endswith("\n") else text + "\n", **options)["findings"]


def rules(text, **options):
    return [f["rule"] for f in findings(text, **options)]


def calque(text):
    return [f for f in findings(text) if f["rule"] == "calque"]


class EstablishedAdverbTest(unittest.TestCase):
    """2章: 定着した言い方に副詞が挟まった文に型1を出さない。"""

    NO_CALQUE = (
        # 指示書の再現の表の7文
        "CIがすべて通っている。", "テストがまだ通らない。", "キャッシュがちゃんと効いていません。", "CIが通っている。",
        "テストが通らない。", "テストがすべて通った。", "キャッシュが効いていません。",
        # 指示書の受け入れ条件の4文
        "CIはもう全部通りました。", "ビルドがなかなか通らない。", "設定がちゃんと効いているか確かめます。",
        "フラグがまだ効いていない。",
        # 読点（助詞のあとと副詞のあと）、副詞2つ、件数や道具の名前をはさむ既存の形
        "テストが、まだ通らない。", "テストがまだ、通らない。", "CIがもうすべて通りました。",
        "ビルドが一度で通りました。", "キャッシュがきちんと効いています。", "テストは218件とも通りました。",
        "テスト一式は pytest で通す。", "コンパイルが問題なく通った。", "インデックスがしっかり効いている。",
    )
    KEEP_TYPE1 = (
        ("取りこぼした通知は、翌朝の再送ジョブが拾います。", "拾う"),
        # 指示書の「この経路は、まだ社外の通信も通します。」は v2.4.0 でも出ない（主語の語の一覧に経路と通信がない）。
        # 機械が主語の同じ形の文で、型1が残ることを見る
        ("このプロキシは、まだ社外の通信も通します。", "通す"),
        ("このプロキシは、社外の通信をきちんと通します。", "通す"),
        ("このジョブは、失敗した通知を毎朝しっかり拾います。", "拾う"),
    )

    def test_established_forms_with_adverbs_have_no_calque(self):
        for text in self.NO_CALQUE:
            with self.subTest(text=text):
                self.assertEqual(calque(text), [])

    def test_machine_subject_type1_is_kept(self):
        for text, word in self.KEEP_TYPE1:
            with self.subTest(text=text):
                found = calque(text)
                self.assertEqual(len(found), 1)
                self.assertIn(TYPE1, found[0]["message"])
                self.assertIn(word, found[0]["message"])

    def test_route_sentence_is_the_same_as_v240(self):
        self.assertEqual(calque("この経路は、まだ社外の通信も通します。"), [])

    def test_adverbs_are_exact_words(self):
        """副詞の一覧は語の完全一致（任意の字の並びにしない）。一覧にない語が挟まれば、今までどおり型1の候補になる。"""
        self.assertIn("ちゃんと", yomiyasu_lint._CALQUE_ESTABLISHED_ADVERBS)
        self.assertNotIn("[", yomiyasu_lint._CALQUE_ESTABLISHED_ADVERB.replace("[^", ""))
        self.assertEqual(len(calque("キャッシュが夜中に効いていません。")), 1)
        self.assertEqual(len(calque("テストがまだまだまだ通らない。")), 1)


class KikuTest(unittest.TestCase):
    """3章: 比喩の「効く」の見落とし。"""

    ONE = (
        # 指示書の再現の表で「なし」だった4文（薬の後の行の例を除く）
        "キャッシュを入れました。\nここで効いてくるのが、型の考え方です。",
        "最適化の話をしました。\n\nここで効いてくるのが、型の考え方です。",
        "ここで効いてくるのが、キャッシュの設計です。",
        "そこで効くのが、型の考え方です。",
    )
    KEPT = (
        # 指示書の表で metaphor_verb か calque が出ていた文はそのまま出る
        "ここで効いてくるのが、型の考え方です。",
        "型の定義を見ていきます。\nここで効いてくるのが、型の考え方です。",
        "地味に効いてくる。",
        "この変更が効いて、速くなりました。",
    )
    NONE = (
        "薬が効く。\nブレーキが効かない。\n冷房がよく効いた部屋です。\nわさびが効いている。\n気が利く人です。",
        "融通が効く。", "飲んで30分ほどで効いてきます。", "キャッシュが効いてくると速くなります。",
        "ここで薬が効いてくるのが分かります。", "薬はここで効いてくるのが分かります。",
        "薬を飲むと、ここで効いてくるのが分かります。", "冷房をつけて10分ほどたつと、そこで効いてくるのが分かります。",
        "そこで効くのが、わさびです。", "そこで効くのが、この薬です。",
        "インデックスを作ると、検索が多いときに効きます。", "設定の変更は来月から効きます。",
        "ダイエットにいちばん効くのは、毎日の運動です。",
    )

    def kiku(self, text):
        return [f for f in findings(text) if f["rule"] in ("metaphor_verb", "calque")]

    def test_missed_sentences_get_one_finding(self):
        for text in self.ONE:
            with self.subTest(text=text):
                self.assertEqual(len(self.kiku(text)), 1)

    def test_findings_in_the_table_are_kept(self):
        for text in self.KEPT:
            with self.subTest(text=text):
                self.assertGreaterEqual(len(self.kiku(text)), 1)

    def test_literal_uses_and_idioms_have_none(self):
        for text in self.NONE:
            with self.subTest(text=text):
                self.assertEqual(self.kiku(text), [])

    def test_after_a_medicine_line_the_phrase_is_calque(self):
        """「薬が効く。」の次の行の「ここで効いてくるのが」は、metaphor_verb は前の行の薬で外れ、型3の句が1件出る（固定）。"""
        found = self.kiku("薬が効く。\nここで効いてくるのが、型の考え方です。")
        self.assertEqual([(f["rule"], f["line"]) for f in found], [("calque", 2)])
        self.assertIn(TYPE3, found[0]["message"])
        self.assertIn("ここで効くのが", found[0]["message"])

    def test_calque_is_not_stacked_on_metaphor_verb(self):
        found = self.kiku("ここで効いてくるのが、型の考え方です。")
        self.assertEqual([f["rule"] for f in found], ["metaphor_verb"])

    def test_chapter2_sentences_get_no_new_findings(self):
        for text in EstablishedAdverbTest.NO_CALQUE:
            with self.subTest(text=text):
                self.assertEqual(self.kiku(text), [])

    def test_software_words_stay_in_the_subject_check(self):
        for word in ("キャッシュ", "インデックス", "最適化", "JIT", "設定の変更"):
            with self.subTest(word=word):
                self.assertIn(word, yomiyasu_lint._KIKU_LITERAL)
                self.assertNotIn(word, yomiyasu_lint._KIKU_LITERAL_NEAR)


class NewPhraseTest(unittest.TestCase):
    """3章と4章: 型3に足した句（_CALQUE_PHRASES_V250）。"""

    EXAMPLES = {
        "ここで効くのが": "そこで効くのが、名前の付け方です。",
        "レベルの": "リポジトリレベルのコンテキストファイルを用意します。",
        "テーブルにある": "その案はいま、テーブルの上にあります。",
    }
    MORE = (
        ("プロジェクトレベルの設定は、ここに置きます。", "レベルの"),
        ("組織レベルの方針を決めます。", "レベルの"),
        ("この選択肢は、まだテーブルに載っています。", "テーブルにある"),
        ("三つの提案がテーブルにあります。", "テーブルにある"),
        ("最後に効いてくるのは、テストの書き方です。", None),
    )
    KEEP = (
        "OSレベルの設定を変えます。", "カーネルレベルの処理です。", "アプリケーションレベルのログを見ます。",
        "組織レベルの高い会社です。", "レベル3の資格を取りました。", "レベルの低い議論です。",
        "テーブルの上にある鍵を取ってください。", "皿がテーブルに載っています。", "答案はテーブルの上にあります。",
        # 表の「テーブル」と、テーブルの上にある物を言う連体の形（点検で見つけた形）
        "抽出の条件は users テーブルにあります。", "条件は、下のテーブルにあるとおりです。",
        "選択肢は、マスタのテーブルに載っている値から選びます。", "その案は、テーブルの上にある資料にまとめました。",
    )

    def test_each_new_phrase_is_found(self):
        """どの句にも当たる類例がある（文書全体の手掛かりの語が、足した句の正規表現も覆っている）。"""
        self.assertEqual(set(self.EXAMPLES), set(name for name, _ in yomiyasu_lint._CALQUE_PHRASES_V250))
        for name, text in self.EXAMPLES.items():
            with self.subTest(phrase=name):
                found = calque(text)
                self.assertEqual(len(found), 1)
                self.assertIn(TYPE3, found[0]["message"])
                self.assertIn(name, found[0]["message"])

    def test_more_examples(self):
        for text, name in self.MORE:
            with self.subTest(text=text):
                found = [f for f in findings(text) if f["rule"] in ("calque", "metaphor_verb")]
                self.assertEqual(len(found), 1)
                if name:
                    self.assertIn(name, found[0]["message"])

    def test_layers_and_objects_are_kept(self):
        for text in self.KEEP:
            with self.subTest(text=text):
                self.assertEqual(calque(text), [])

    def test_existing_table_phrase_is_not_doubled(self):
        found = calque("その案を、もう一度テーブルに載せます。")
        self.assertEqual(len(found), 1)
        self.assertIn("テーブルに置く", found[0]["message"])

    def test_v220_phrase_table_is_unchanged(self):
        """2.5.0 の句は別のタプルに置き、2.2.0 の句の表（test_v220_a1 が全部を見る）には足さない。"""
        names = set(name for name, _ in yomiyasu_lint._CALQUE_PHRASES)
        self.assertTrue(names.isdisjoint(name for name, _ in yomiyasu_lint._CALQUE_PHRASES_V250))


class ChapterOneTest(unittest.TestCase):
    """1章: 型1に「語る」、型2に人の役目の名詞を足す条件（tests/corpus の human で0件、raw_ai で1件以上）を満たさないので、
    lint は変えない。指示書の表の文の結果と、定着した言い方の文に新しい指摘が出ないことを見る。"""

    TABLE = (
        ("この関数は、呼び出し元の事情を知っています。", []),
        ("コードが語るのは、設計者の意図です。", []),
        ("このクラスは、DB との対話を一手に引き受けます。", []),
        ("ミドルウェアがリクエストの門番を務めます。", []),
        ("ルーターが、交通整理の役を果たします。", []),
        ("UserService が認証の責任を引き受けます。", []),
        ("このフックは、変更を見張っています。", ["calque"]),
        ("パーサーは入力を食べて、木を吐き出します。", ["calque"]),
    )
    PLAIN = ("このツールはログを集めます。", "UserService が認証を担当します。", "関数は値を返します。",
             "サービス A はサービス B に依存しています。")

    def test_table_sentences(self):
        for text, expected in self.TABLE:
            with self.subTest(text=text):
                self.assertEqual([r for r in rules(text) if r in ("calque", "ai_phrase")], expected)

    def test_plain_descriptions_have_no_findings(self):
        for text in self.PLAIN:
            with self.subTest(text=text):
                self.assertEqual(rules(text), [])

    def test_kataru_is_not_a_type1_verb(self):
        self.assertNotIn("語る", [name for name, _ in yomiyasu_lint._CALQUE_VERBS])


if __name__ == "__main__":
    unittest.main()
