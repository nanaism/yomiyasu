"""v2.3.0: renyo_noun（他動詞を1語だけ名詞にした語を「の」で受ける形。「結果の確かめ」「二つの案の比べ」）と、
語の一覧 references/lists/renyo-nouns.txt。

他動詞の連用形を1語だけ名詞にした語は、目的語を「の」で受ける形では使いにくい。名詞とくっつけた複合語（資金集め）、
複合動詞から来た語（見直し）、「お」を付けた形（お選び）、別の意味で定着した語（住民票の写し）には印をつけない。
文はすべて自作の合成の文（v230-development/k2/sentences.tsv から選んだ文と、この試験のために作った文）。
"""
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_lint  # noqa: E402

TAIL = "の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。"


def renyo(text, doc_type=None, keep_words=False, words=None):
    """lint_text の結果のうち renyo_noun の候補（keep_words なら内部の欄 _words も残す）。"""
    original = yomiyasu_lint._public_finding
    if keep_words:
        yomiyasu_lint._public_finding = lambda finding: dict(finding)
    try:
        if words is None:
            result = yomiyasu_lint.lint_text(text, doc_type=doc_type)
        else:
            result = yomiyasu_lint.lint_text(text, doc_type=doc_type, words=words)
    finally:
        yomiyasu_lint._public_finding = original
    return [finding for finding in result["findings"] if finding["rule"] == "renyo_noun"]


TARGETS = (
    ("出した数字は、表の値との確かめが済んでいません。", "確かめ"),
    ("誤字の直しは、明日の朝までに終えます。", "直し"),
    ("二つの案の比べは、次の会議で行います。", "比べ"),
    ("部屋の広さの測りに、思ったより時間がかかった。", "測り"),
    ("説明の補いを、最後の段落に入れました。", "補い"),
    ("担当の決めが遅れて、作業が止まっています。", "決め"),
    ("候補の選びに迷ったら、先輩に相談してください。", "選び"),
    ("資料の集めが予定どおりに進まない。", "集め"),
    ("用語のそろえが、まだ半分しか終わっていない。", "そろえ"),
    ("古い設定の外しを忘れないでください。", "外し"),
    ("名前の伏せが漏れていた所が、3か所ありました。", "伏せ"),
    ("データの移しに、二日かかりました。", "移し"),
    ("説明の足しを、注に回しました。", "足し"),
    ("新しい手順の試しは、来週から始めます。", "試し"),
    ("誤字の直しだけを、先に済ませます。", "直し"),
    ("結果の確かめや、表の直しを進めます。", "確かめ"),
    ("（結果）の確かめは明日です。", "確かめ"),
    ("Step 2 の確かめが済んだ。", "確かめ"),
    ("**結果**の確かめは明日です。", "確かめ"),
    ("結果の**確かめ**は明日です。", "確かめ"),
    ("結果の確かめから始めます。", "確かめ"),
    ("値の確かめなどを済ませる。", "確かめ"),
    ("その確かめは明日です。", "確かめ"),
    ("表の直しまで終えた。", "直し"),
    ("案の比べより先に、表を作る。", "比べ"),
    ("| 値の確かめ | 済み |", "確かめ"),
)
KEEPS = (
    "資金集めが計画どおりに進まない。",
    "商品選びに時間がかかった。",
    "ズボンの裾の手直しを頼んだ。",
    "色の組み合わせがよい。",
    "部品の組み立てに時間がかかった。",
    "手順の見直しを、来週に行います。",
    "課題の洗い出しから始めました。",
    "原稿の書き直しを、編集者に頼まれた。",
    "表の値との確認が済んでいません。",
    "表の値と照らし合わせて確かめました。",
    "商品のお選びに迷われた際は、お気軽にお尋ねください。",
    "新しい手順のお試しは、来週から始めます。",
    "住民票の写しを、窓口に出してください。",
    "合格の知らせが届いた。",
    "最後の詰めが甘かった。",
    "わずかでも生活の足しになる。",
    "試しに一度動かしてみます。",
    "事態の読みが甘かった。",
    "警察の調べによると、事故の原因は居眠りだった。",
    "法律の定めにより、記録は5年間残します。",
    "顧客の求めに応じて、仕様を変えました。",
    "欠勤の届けを、前日までに出してください。",
    "災害への備えを見直しました。",
    "部屋の片付けが終わりました。",
    "人の動きが、去年より増えた。",
    "株価の上げが続いている。",
    "駅までの送りを、父に頼んだ。",
    "漢字の書きが苦手だ。",
    "部下への示しがつかない。",
    "キッチン用の計りとストップウォッチが置いてある。",
    "力の入れやすい角度に作られている。",
    "値の確かめにくい画面だった。",
    "答えの決めがたい問いだった。",
    "結果の確かめだと思った。",
    "誤字の直し方を、手順書にまとめた。",
    "二つの案の比べ物にならない。",
    "決めの一手が見つからない。",
    "値の確かめにくさが気になる。",
    "答えの決めがたさが残る。",
    "値の確かめやすさを上げる。",
    "部屋の探しものを手伝った。",
    "育ての親に会いに行った。",
    "生みの母より育ての母。",
)


class RenyoNounTest(unittest.TestCase):
    def test_targets_are_marked_with_the_word(self):
        for text, word in TARGETS:
            with self.subTest(text=text):
                found = renyo(text, keep_words=True)
                self.assertEqual(len(found), 1, found)
                self.assertIn(word, found[0]["_words"])
                self.assertEqual(found[0]["severity"], "info")
                self.assertEqual(found[0]["line"], 1)

    def test_keeps_are_not_marked(self):
        for text in KEEPS:
            with self.subTest(text=text):
                self.assertEqual(renyo(text), [])

    def test_one_finding_per_line_lists_the_words(self):
        found = renyo("結果の確かめと、表の直しと、案の比べを済ませます。\n誤字の直しは明日です。", keep_words=True)
        self.assertEqual([finding["line"] for finding in found], [1, 2])
        self.assertEqual(found[0]["_words"], ("確かめ", "直し", "比べ"))
        self.assertEqual(found[0]["message"],
                         "他動詞を1語だけ名詞にした語を「の」で受ける形（当たった言い方: の確かめ、の直し、の比べ）" + TAIL)
        self.assertEqual(found[1]["message"], "他動詞を1語だけ名詞にした語を「の」で受ける形（当たった言い方: の直し）" + TAIL)

    def test_quotes_code_identifiers_and_quote_lines_are_not_scanned(self):
        text = ("「結果の確かめ」のような言い方は、引用では見ない。\n"
                "> 誤字の直しは明日です。\n"
                "`表の直し` はコードの中です。\n"
                "```\n案の比べは、コードの中です。\n```\n"
                "設定は check_の確かめ のような識別子です。\n")
        self.assertEqual(renyo(text), [])

    def test_headings_tables_and_lists_are_scanned(self):
        text = "# 表記のそろえ\n\n- 誤字の直し\n\n| 項目 | 中身 |\n|---|---|\n| 値の確かめ | 済み |\n"
        self.assertEqual([finding["line"] for finding in renyo(text)], [1, 3, 7])

    def test_every_doc_type_marks(self):
        for doc_type in yomiyasu_lint.DOC_TYPE_SKIP_RULES:
            with self.subTest(doc_type=doc_type):
                self.assertEqual(len(renyo("誤字の直しは明日です。", doc_type=doc_type)), 1)

    def test_score_is_not_affected(self):
        result = yomiyasu_lint.lint_text("出した数字は、表の値との確かめが済んでいません。")
        self.assertEqual([finding["rule"] for finding in result["findings"]], ["renyo_noun"])
        self.assertEqual(result["rule_penalty_score"], 100)
        self.assertEqual(result["counts"]["info"], 1)

    def test_allow_removes_word_by_word(self):
        import markdown_visibility
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        (Path(folder.name) / "allow.txt").write_bytes("直し\n".encode("utf-8"))
        words = markdown_visibility.load_words(folder.name)
        found = renyo("結果の確かめと、表の直しを済ませます。\n誤字の直しは明日です。", keep_words=True, words=words)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["_words"], ("確かめ",))
        self.assertEqual(found[0]["message"], "他動詞を1語だけ名詞にした語を「の」で受ける形（当たった言い方: の確かめ）" + TAIL)
        result = yomiyasu_lint.lint_text("誤字の直しは明日です。", words=words)
        self.assertEqual(result["context"]["words"]["allow_removed"]["renyo_noun"], 1)

    def test_list_file_matches_the_builtin_list(self):
        path = ROOT / "references" / "lists" / "renyo-nouns.txt"
        items = yomiyasu_lint._v220_parse_list(path.read_bytes().decode("utf-8-sig"))
        self.assertEqual(items, yomiyasu_lint._V220_BUILTIN_LISTS["renyo-nouns"])
        twin = ROOT / "skills" / "yomiyasu" / "references" / "lists" / "renyo-nouns.txt"
        self.assertEqual(twin.read_bytes(), path.read_bytes())

    def test_builtin_list_is_used_without_the_file(self):
        saved = dict(yomiyasu_lint._V220_LIST_CACHE)
        yomiyasu_lint._V220_LIST_CACHE.pop("renyo-nouns", None)
        real_open = open

        def fake_open(path, *args, **kwargs):
            if str(path).endswith(os.path.join("lists", "renyo-nouns.txt")):
                raise FileNotFoundError(path)
            return real_open(path, *args, **kwargs)
        import builtins
        builtins.open = fake_open
        try:
            items, source = yomiyasu_lint._v220_load_list("renyo-nouns")
        finally:
            builtins.open = real_open
            yomiyasu_lint._V220_LIST_CACHE.clear()
            yomiyasu_lint._V220_LIST_CACHE.update(saved)
        self.assertEqual(source, "builtin")
        self.assertEqual(items, yomiyasu_lint._V220_BUILTIN_LISTS["renyo-nouns"])

    def test_cost_grows_with_the_text(self):
        text = "誤字の直しは明日です。資料の確認は済みました。\n" * 20000
        started = time.perf_counter()
        found = renyo(text)
        self.assertLess(time.perf_counter() - started, 20.0)
        self.assertEqual(len(found), 20000)

    def test_cli_json_lists_the_rule(self):
        import json
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.md"
            path.write_bytes("誤字の直しは明日です。\n".encode("utf-8"))
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_lint.py"), "--json", "--no-words", str(path)],
                                     capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        data = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual([finding["rule"] for finding in data["findings"]], ["renyo_noun"])


if __name__ == "__main__":
    unittest.main()
