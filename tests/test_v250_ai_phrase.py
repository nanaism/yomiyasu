"""v2.5.0: AI の文章によく出る言い回しの規則 ai_phrase（4章）。

info で、点数（rule_penalty_score）と --strict、--fail-on に入らない。allow.txt の語（当たった言い方）で外せる。
なんよは script と essay で、て形の体言止めは slides、minutes、promo、script で外す。文はすべて自作の合成の文。
"""
from pathlib import Path
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_lint  # noqa: E402
from markdown_visibility import resolve_words  # noqa: E402


def ai(text, **options):
    result = yomiyasu_lint.lint_text(text if text.endswith("\n") else text + "\n", **options)
    return [f for f in result["findings"] if f["rule"] == "ai_phrase"]


TARGETS = (
    # 指示書の再現の表の類例（lint で扱う9語句のうち ai_phrase の7つ）
    ("今回の結果は、市場が回復に向かうという見立てです。", "見立てです"),
    ("この設計は、運用時にリスクが潜む構造です。", "潜む"),
    ("放置すると、深刻な事態が招く危機に直面します。", "が招く"),
    ("スマホは、今や私たちの生活に欠かせない存在です。", "欠かせない存在"),
    ("過去の記憶の改ざんという挙動を排除する。", "という挙動を排除"),
    ("設定を見直して、速度を改善。", "て形の体言止め"),
    ("これは設定の問題なんよ。", "なんよ"),
    # ほかの形
    ("日常に潜む危険を知っておきましょう。", "潜む"),
    ("この手順には、更新のたびに問題が潜んでいます。", "潜む"),
    ("油断が招く失敗です。", "が招く"),
    ("クラウドは欠かせない存在となっています。", "欠かせない存在"),
    ("これは設定の問題なんよね。", "なんよ"),
    ("データを集めて、分析を実施。", "て形の体言止め"),
    ("今回の数字は、売上が持ち直すとの見立てだ。", "見立てです"),
    ("二重に送信するという挙動を防止します。", "という挙動を排除"),
    ("Facebookに潜む各種のリスクをまとめた。", "潜む"),
    ("社会が招く結果を考えます。", "が招く"),
)
KEEPS = (
    # 指示書の「指摘しない形」の列
    "医師の見立てでは、軽い風邪です。", "彼の見立てどおり、雨になった。", "それは見立て違いだった。",
    "専門家は、市場が回復に向かうという見立てです。", "田中さんは、来月には回復するとの見立てだ。",
    "私は、これで十分だという見立てです。", "日銀は、景気が緩やかに回復しているとの見立てだ。",
    "山に潜む動物を調べます。", "物陰に潜む。", "犯人が潜む家を見つけた。", "草むらに虫が潜んでいる。",
    "この契約が誤解を招いた。", "客を招く準備をします。", "講師を招く予定です。", "ミスを招いた原因を探します。",
    "社長が招く客を出迎えます。",
    "この手順は欠かせません。", "今や誰もがスマホを持っています。",
    "この挙動を確かめます。", "外れた値を渡すと、エラーという挙動になります。",
    "「これは設定の問題なんよ。」と彼は言った。",
    "速度を改善。", "設定を見直して、改善。", "そして、計画を発表。", "品質について、議論を開始。",
    "すべて、手順を確認。",
    # 判断した人や組織が「の」や「たち」「ら」で付く文、役職の語（点検で見つけた形）
    "田中さんの見立てです。", "これは医師の見立てです。", "私の見立てです。", "政府の見立てだ。",
    "私たちは、回復に向かうという見立てです。", "医師たちは、軽い症状で済むという見立てです。",
    "社長は、来期は増収になるという見立てです。", "主治医は、全治2か月との見立てだ。",
    "犯行は計画的だったというのが検察の見立てだ。",
    # 潜むものが動物や虫で、危険の語がそれを修飾するだけの文
    "物陰に潜む危険な動物に気をつけてください。", "茂みに潜む危険な蛇に注意します。", "草むらに潜む虫の危険を調べます。",
    "山に潜む動物の危険を知っておきたい。", "草むらに潜むマダニの危険性に注意してください。",
    # 人や組織が招く文
    "上司が招く食事会に出ます。", "父が招く客を迎えます。", "当店が招く講師は三人です。", "県が招く講師による研修会を開きます。",
    "毎年、母が招く客は近所の人ばかりだ。",
    # 動詞でない「て」「で」
    "結果に応じて、方針を検討。", "年間を通じて、販売を継続。", "会場にて、新製品を発表。", "雨のせいで、試合を中止。",
)


class AiPhraseTest(unittest.TestCase):
    def test_targets_get_one_finding(self):
        for text, word in TARGETS:
            with self.subTest(text=text):
                found = ai(text)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["severity"], "info")
                self.assertIn("当たった言い方: " + word, found[0]["message"])

    def test_keeps_have_no_new_findings(self):
        for text in KEEPS:
            with self.subTest(text=text):
                self.assertEqual(ai(text), [])
                result = yomiyasu_lint.lint_text(text + "\n")
                self.assertNotIn("calque", [f["rule"] for f in result["findings"]])

    def test_message_names_no_replacement(self):
        found = ai("この設計は、運用時にリスクが潜む構造です。")
        self.assertEqual(found[0]["message"], "AIの文章によく出る言い回し（当たった言い方: 潜む）" + yomiyasu_lint._V220_MESSAGE_TAIL)

    def test_one_finding_per_line(self):
        found = ai("この設計は、運用時にリスクが潜む構造です。放置すると、深刻な事態が招く危機に直面します。")
        self.assertEqual(len(found), 1)
        self.assertIn("潜む、が招く", found[0]["message"])

    def test_document_types_drop_two_forms(self):
        text = "これは設定の問題なんよ。\n\n設定を見直して、速度を改善。\n"
        cases = {None: [1, 3], "article": [1, 3], "essay": [3], "script": [], "slides": [1], "minutes": [1],
                 "promo": [1], "manual": [1, 3]}
        for doc_type, lines in cases.items():
            with self.subTest(doc_type=doc_type):
                self.assertEqual([f["line"] for f in ai(text, doc_type=doc_type)], lines)

    def test_headings_lists_and_tables_do_not_get_the_te_form(self):
        text = "# 設定を見直して、速度を改善。\n\n- 設定を見直して、速度を改善。\n\n| 設定を見直して、速度を改善。 |\n|---|\n| a |\n"
        self.assertEqual(ai(text), [])

    def test_not_in_score_strict_or_fail_on(self):
        text = "この設計は、運用時にリスクが潜む構造です。\n"
        result = yomiyasu_lint.lint_text(text)
        self.assertEqual([f["rule"] for f in result["findings"]], ["ai_phrase"])
        self.assertEqual(result["rule_penalty_score"], 100)
        self.assertIn("ai_phrase", yomiyasu_lint._V250_RULES)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.md"
            path.write_bytes((text).encode("utf-8"))
            for args in (["--strict"], ["--fail-on", "warn"], ["--fail-on", "error"]):
                with self.subTest(args=args):
                    out, err = io.StringIO(), io.StringIO()
                    with redirect_stdout(out), redirect_stderr(err):
                        try:
                            code = yomiyasu_lint.main(args + ["--no-words", str(path)])
                        except SystemExit as stop:
                            code = stop.code
                    self.assertEqual(code, 0, out.getvalue() + err.getvalue())

    def test_allow_words_remove_the_finding(self):
        text = "この設計は、運用時にリスクが潜む構造です。放置すると、深刻な事態が招く危機に直面します。\n"
        with tempfile.TemporaryDirectory() as folder:
            words_dir = Path(folder) / ".yomiyasu-words"
            words_dir.mkdir()
            (words_dir / "allow.txt").write_bytes(("潜む\n").encode("utf-8"))
            words = resolve_words(folder, str(words_dir))
            result = yomiyasu_lint.lint_text(text, words=words)
            found = [f for f in result["findings"] if f["rule"] == "ai_phrase"]
            self.assertEqual(len(found), 1)
            self.assertIn("当たった言い方: が招く）", found[0]["message"])
            (words_dir / "allow.txt").write_bytes(("潜む\nが招く\n").encode("utf-8"))
            words = resolve_words(folder, str(words_dir))
            result = yomiyasu_lint.lint_text(text, words=words)
            self.assertEqual([f for f in result["findings"] if f["rule"] == "ai_phrase"], [])
            self.assertEqual(result["context"]["words"]["allow_removed"]["ai_phrase"], 1)

    def test_corpus_human_has_no_findings(self):
        for path in sorted((ROOT / "tests" / "corpus" / "human").glob("*.md")):
            for doc_type in (None, "article", "essay"):
                with self.subTest(path=path.name, doc_type=doc_type):
                    self.assertEqual(ai(path.read_text(encoding="utf-8"), doc_type=doc_type), [])


if __name__ == "__main__":
    unittest.main()
