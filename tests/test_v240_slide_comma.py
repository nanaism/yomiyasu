"""v2.4.0: slide_comma（スライドの見出しと1行の箇条の、間を作るだけの読点。slides だけ。info で、点数に入れない）。

拾うのは、文頭のつなぎの語、決まった「〜ば」、文頭の5字以上の時や場面の句、文頭の短い主題や主語、目的語の「を」のあとの読点。
逆接、条件、理由、名詞の並び、短い時の句（その夜、）の読点は拾わない。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402


def slide(text, doc_type="slides"):
    result = yomiyasu_lint.lint_text(text, doc_type=doc_type)
    return [f for f in result["findings"] if f["rule"] == "slide_comma"]


TARGETS = (
    ("## だから、引き継ぎの資料を先に作った", "だから、"),
    ("- それでも、測れない所は残る", "それでも、"),
    ("- そこで、手順を3つに分けた", "そこで、"),
    ("- 結局、元の設定に戻した", "結局、"),
    ("- 実は、半分は手作業だった", "実は、"),
    ("## 振り返れば、最初の設計が甘かった", "振り返れば、"),
    ("- 言われてみれば、そのとおりだった", "言われてみれば、"),
    ("- 数字で言えば、問い合わせは半分に減った", "数字で言えば、"),
    ("- その日のうちに、手順書を書き直した", "その日のうちに、"),
    ("- 会議が終わるまでに、結論を一つに絞る", "会議が終わるまでに、"),
    ("## 新しい手順では、確認を1回にまとめる", "新しい手順では、"),
    ("- 大事なのは、止めずに続けること", "大事なのは、"),
    ("- テストを書かない理由は、習慣がないこと", "テストを書かない理由は、"),
    ("- 既存のコードには、触った所だけ足す", "既存のコードには、"),
    ("- 小さなチームが、毎週リリースしている", "小さなチームが、"),
    ("- 古い仕組みを、少しずつ置き換えた", "古い仕組みを、"),
    ("- 詳しい人を、最初の相談相手にした", "詳しい人を、"),
    ("1. まず、今の手順を書き出す", "まず、"),
    ("- 返信は24時間以内。急ぎの件では、電話も使う", "急ぎの件では、"),
    ("- 決めた手順と変えた理由を、先に共有する", "決めた手順と変えた理由を、"),
    ("- 新人も、初日から本番の手順を見る", "新人も、"),
    # 行頭の印（入れ子の箇条、「・」「①」、【】、ラベル、番号つきの見出し）を外してから文頭を決める
    ("- 親\n    - だから、引き継ぎの資料を先に作った", "だから、"),
    ("・だから、急ぐ", "だから、"),
    ("① まず、今の手順を書き出す", "まず、"),
    ("- 【結論】だから、急ぐ", "だから、"),
    ("- **結論**：だから、急ぐ", "だから、"),
    ("## Step 1: まず、測る", "まず、"),
    ("- 遅れた！だから、急ぐ", "だから、"),
    # 当たった言い方は元の行から切り出す（コードはそのまま、リンクは文字だけ）
    ("- `npm test` を、毎回走らせる", "`npm test` を、"),
    ("- [資料](https://example.com/a)を、先に配る", "資料を、"),
)
KEEPS = (
    "- テストは通るのに、本番で落ちた",
    "- 急ぎなら、電話で連絡する",
    "- 時間がかかったが、手戻りは減った",
    "- 手順を変えたので、問い合わせが減った",
    "- 3回試しても、同じ結果だった",
    "- 間に合わないなら、範囲を絞る",
    "- 予算、人数、期限を先に決める",
    "- 東京、大阪、福岡で試した",
    "- その夜、直す前と後を比べた",
    "- 翌朝、全員に知らせた",
    "- 「速さより、正しさ」を合言葉にした",
    "- データを集め、傾向を見て、仮説を立てる",
    "- 手を動かして、覚える",
    "- 小さく始めるために、対象を1つに絞った",
    "## 今期の数字と来期の打ち手",
    "- 返信は24時間以内",
    "- 会議では、担当者が説明した",
    "- 今回は、私が進める",
    "## 移行では、チームが2つに分かれる",
    "- 書き換えの中で変わったのは、画面、帳票、通知",
    "- 問い合わせが多い日は、2人で受ける体制にした場合の費用と、1人で受けたときの待ち時間を比べて、どちらにするかを来月の会議で決める予定です。",
    # 「も」で終わる逆接、目的と条件の「には」「は」、条件の「〜ば」
    "- 手間はかかるけれども、効果は大きい",
    "- 小さいながらも、効果がある",
    "- 迷いつつも、前に進めた",
    "- 失敗しようとも、続ける",
    "- 急がなくては、間に合わない",
    "- 早く出すためには、手順を減らす",
    "- 早く出すには、手順を減らす",
    "- 引き受けた以上は、期限を守る",
    "- 上司に言えば、すぐ直してくれる",
    "- 使ってみれば、良さが分かる",
    # 主題のあとに別の主語（ひらがなで終わる人の語、英字、「は」の主語）
    "- 今回は、私たちが進める",
    "- 会議では、田中さんが説明した",
    "- 今回は、Claude が下書きを書いた",
    "- 会議では、部長は反対した",
    "- 移行では、チームが多くの作業を抱えた",
    # 述語のあとの括弧に続く逆接、同じ助詞の並び、伏せた語のあとの「でも」「なので」、6字に満たない時の句
    "- 処理は速くなった（約2倍）が、メモリは増えた",
    "- 予算を、人数を、期限を先に決める",
    "- 営業が、開発が、それぞれ説明した",
    "- macOS でも、同じ手順で動く",
    "- `main` でも、同じ手順で動く",
    "- 「急ぎ」なので、電話で連絡する",
    "- 月末までに、結論を出す",
    # 「〜ときは」「〜場合は」の条件と、長い節の主語
    "- 雨のときは、屋内で集まる",
    "- 間に合わない場合は、早めに知らせる",
    "- 最初は見るだけだった新人が、今は手順を教えている",
)


class SlideCommaTest(unittest.TestCase):
    def test_targets_are_found(self):
        # 短い主語や主題のあとの読点は、pause_comma が出ている行では slide_comma を重ねない（どちらかが出ればよい）
        for line, hit in TARGETS:
            with self.subTest(line=line):
                result = yomiyasu_lint.lint_text(line + "\n", doc_type="slides")
                found = [f for f in result["findings"] if f["rule"] == "slide_comma"]
                pause = [f for f in result["findings"] if f["rule"] == "pause_comma"]
                if found:
                    self.assertEqual(len(found), 1, found)
                    self.assertIn("「" + hit + "」", found[0]["message"])
                    self.assertEqual(found[0]["severity"], "info")
                else:
                    self.assertTrue(pause, line)

    def test_keeps_are_not_found(self):
        for line in KEEPS:
            with self.subTest(line=line):
                self.assertEqual(slide(line + "\n"), [])

    def test_only_for_slides(self):
        text = "## だから、引き継ぎの資料を先に作った\n- その日のうちに、手順書を書き直した\n"
        self.assertEqual(len(slide(text)), 2)
        for doc_type in (None, "article", "manual", "pr", "mail"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(slide(text, doc_type=doc_type), [])

    def test_one_finding_per_line_lists_the_hits(self):
        found = slide("- 結局、古い仕組みを、少しずつ置き換えた\n")
        self.assertEqual(len(found), 1)
        self.assertIn("「結局、」", found[0]["message"])
        self.assertIn("「古い仕組みを、」", found[0]["message"])

    def test_hit_is_shown_from_the_last_punctuation(self):
        # 当たった言い方は、句読点のあとから読点までを語の途中で切らずに出す（20字より長いときだけ、頭に「…」を付けて終わりの20字）
        found = slide("- 夜間に起きた集計の失敗は、翌朝の朝会で共有する\n")
        self.assertIn("「夜間に起きた集計の失敗は、」", found[0]["message"])
        found = slide("- 今年の春に始めた新しいプロジェクトの資料を、全員に配る\n")
        self.assertIn("「…の春に始めた新しいプロジェクトの資料を、」", found[0]["message"])

    def test_only_single_line_items(self):
        # 続きの行がある箇条と、複数行の段落の行は見ない。「・」で始まる行は、続いていても1行ずつの項目として見る
        self.assertEqual(slide("- 会議では、\\\n  担当者が説明した\n"), [])
        self.assertEqual(slide("- 会議では、  \n  担当者が説明した\n"), [])
        self.assertEqual(slide("段落の1行目はここまでで終わり\nだから、段落の2行目\n"), [])
        self.assertEqual(len(slide("・だから、急ぐ\n・そこで、手順を3つに分けた\n")), 2)

    def test_score_is_not_affected(self):
        text = "## だから、引き継ぎの資料を先に作った\n"
        self.assertEqual(yomiyasu_lint.lint_text(text, doc_type="slides")["rule_penalty_score"], 100)

    def test_quotes_and_code_are_not_scanned(self):
        self.assertEqual(slide("- 「だから、急ぐ」と書いた\n"), [])
        self.assertEqual(slide("```\n- だから、急ぐ\n```\n"), [])

    def test_does_not_repeat_pause_comma(self):
        text = "- v1.0.0 は、意味を壊していた\n"
        result = yomiyasu_lint.lint_text(text, doc_type="slides")
        rules = [f["rule"] for f in result["findings"]]
        self.assertIn("pause_comma", rules)
        self.assertNotIn("slide_comma", rules)


if __name__ == "__main__":
    unittest.main()
