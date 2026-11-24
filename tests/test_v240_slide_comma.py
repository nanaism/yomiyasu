"""v2.4.0: slide_comma（スライドの見出しと1行の箇条の、間を作るだけの読点。slides だけ。info で、点数に入れない）。

拾うのは、文頭のつなぎの語、決まった「〜ば」、文頭の5字以上の時や場面の句、文頭の短い主題や主語、目的語の「を」のあとの読点。
逆接、条件、理由、名詞の並び、短い時の句（その夜、）の読点は拾わない。文はすべて自作の合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402
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
        # 3.3.0: 「夜間に起きた集計の失敗は、」（節を含む11字の主題）は pause_comma に出るようになったので、
        # 節を含む15字の主題（pause_comma が外す長さ）の文に替えた
        found = slide("- 夜間のバッチで起きた集計の失敗は、翌朝の朝会で共有する\n")
        self.assertIn("「夜間のバッチで起きた集計の失敗は、」", found[0]["message"])
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


# 3.4.0: 「#」で始まる見出し（文書の題を除く）は、読点を形を問わず全部候補に出す。文はすべて自作の合成の文
HEADING_MESSAGE = "カギ括弧や引用符の中と数字の区切りを除き、見出しには読点を残しません"
HEADING_TARGETS = (
    ("## 移行では、チームが2つに分かれる", ("移行では、",)),            # 主題のあとに別の主語（2.4.0 からは残す側だった）
    ("## 道が混んだら、開始を遅らせる", ("道が混んだら、",)),          # 条件
    ("## 予約は増えたが、来店は減った", ("予約は増えたが、",)),          # 逆接
    ("## 部品が届かないので、出荷を1日遅らせる", ("部品が届かないので、",)),  # 理由
    ("## 受付、展示、撤収", ("受付、", "展示、")),                      # 名詞の並び
    ("## その夜、全員で数字を見直した", ("その夜、",)),                  # 短い時の句
    ("## 2. 目的：事故を減らすために、手順を1枚に", ("事故を減らすために、",)),  # 番号とラベルのあと
    ("## 今期の受注は、2,400件", ("今期の受注は、",)),                  # 数字の区切りは数えない
    ("## 背景，課題，対策", ("背景，", "課題，")),                       # 全角の「，」も読点
    ("## 【至急、全員】サーバーの停止", ("【至急、",)),                  # 【】の中も見る
    ("## 2、3日で届く新しい配送", ("2、",)),                            # 数の並び（数字の区切りではない）
    ("## 来年の春から本社と全国の支店で一斉に使い始める新しい経費精算の仕組みの導入は、"
     "混乱を避けるために三つの段階に分けて進める", ("…い始める新しい経費精算の仕組みの導入は、",)),  # 60字を超える見出しも見る
)
HEADING_KEEPS = (
    "## 「止める、知らせる、残す」を守る",
    "## 合言葉は「小さく作って、早く見せる」",
    "## 社内報『現場から、明日へ』",
    "## “遅い、高い”という声への答え",
    "## \"遅い、高い\" への答え",
    "## 月3,200件の問い合わせ",
    "## 会員数１２，０００人の内訳",
    "## “Done, not perfect” を合言葉に",
    "## `sort -t, -k2` で並べ替える",
    "## 準備・当日・片付け",
    "## ‘はい、いいえ’で答える",
    "## 速さ, 正しさ",                                              # 半角の「,」は読点に数えない
)


class SlideHeadingCommaTest(unittest.TestCase):
    def test_heading_commas_are_all_found(self):
        for line, hits in HEADING_TARGETS:
            with self.subTest(line=line):
                found = slide(line + "\n\n- 本文\n")
                self.assertEqual([f["line"] for f in found], [1])
                self.assertIn(HEADING_MESSAGE, found[0]["message"])
                for hit in hits:
                    self.assertIn("「" + hit + "」", found[0]["message"])

    def test_quotes_digits_and_code_are_kept(self):
        for line in HEADING_KEEPS:
            with self.subTest(line=line):
                self.assertEqual(slide(line + "\n\n- 本文\n"), [])

    def test_hit_starts_after_a_hidden_comma(self):
        # 当たった言い方が引用やコードの中の読点を含むときは、そのあとから切り出して頭に「…」を付ける
        found = slide("## 「軽い、丈夫」より、直しやすさで選ぶ\n")
        self.assertIn("「…より、」", found[0]["message"])
        self.assertNotIn("軽い、丈夫", found[0]["message"])
        self.assertIn("「…の違い、」", slide("## `a、b` の違い、使い分け\n")[0]["message"])
        self.assertIn("「「早く」、」", slide("## 「早く」、「正しく」の2つを守る\n")[0]["message"])

    def test_document_title_keeps_the_v240_shapes(self):
        # 最初の見出しが「# 」で、「# 」がそれ1つだけなら文書の題として、2.4.0 からの型だけを見る（この題は型に当たらない）
        self.assertEqual(slide("# 2027年度の方針、3つの柱\n\n## 今期の振り返り\n\n- 本文\n"), [])
        found = slide("# 今回は、すでにある設定を見直す\n")
        self.assertEqual([f["line"] for f in found], [1])
        self.assertNotIn(HEADING_MESSAGE, found[0]["message"])

    def test_headings_in_quotes_are_not_counted_for_the_title(self):
        # 引用（> の行）の中の見出しは数えないので、そのあとの「# 」がただ1つの見出しなら文書の題（2.4.0 からの型だけを見る）
        self.assertEqual(slide("> # 前回の方針、3つの柱\n\n# 今期の方針、3つの柱\n\n## 背景\n\n- 本文\n"), [])
        self.assertEqual([f["line"] for f in slide("# 前回の方針、3つの柱\n\n# 今期の方針、3つの柱\n\n## 背景\n\n- 本文\n")], [1, 3])

    def test_without_a_title_every_hash_heading_is_a_slide_heading(self):
        # Marp のように「# 」の見出しが2つ以上あれば、どれも各ページの見出し（題と、部の見出し1つでも同じ）
        found = slide("# 新しい検索は、前より速い\n\n- 本文\n\n---\n\n# 料金は今のまま\n\n- 本文\n")
        self.assertEqual([f["line"] for f in found], [1])
        self.assertIn(HEADING_MESSAGE, found[0]["message"])
        found = slide("# 発表会、全体の流れ\n\n## 開場\n\n- 本文\n\n# 第2部、質疑\n\n- 本文\n")
        self.assertEqual([f["line"] for f in found], [1, 7])
        # 「# 」がただ1つでも、最初の見出しでなければ題でない（最初が「## 」や下線の見出しのとき）
        self.assertEqual([f["line"] for f in slide("## はじめに\n\n- 本文\n\n# 本編、3つの話\n")], [5])
        self.assertEqual([f["line"] for f in slide("展示会の記録\n===\n\n# 初日、来場の多い時間\n")], [4])

    def test_limits_setext_and_link_text(self):
        # 限界: 下線の見出しは 2.4.0 からの型で見る。リンクの文字と [ ] の中の読点は見ない
        self.assertEqual(slide("道が混んだら、開始を遅らせる\n---\n\n- 本文\n"), [])
        found = slide("見本市の準備は、早めに\n===\n\n- 本文\n")
        self.assertEqual([f["line"] for f in found], [1])
        self.assertNotIn(HEADING_MESSAGE, found[0]["message"])
        self.assertEqual(slide("## [議事録、11月分](https://example.com/minutes)の要点\n"), [])
        self.assertEqual(slide("## [速報、続報] 停電の状況\n"), [])

    def test_list_lines_keep_the_v240_shapes(self):
        # 1行の箇条は 2.4.0 からの型のまま。箇条のすぐ下の --- で見出しの行になった箇条も、# で始まらないので同じ
        self.assertEqual(slide("## 連絡の決まり\n\n- 急ぎなら、電話で連絡する\n- 翌朝、全員に知らせた\n---\n"), [])
        self.assertEqual([f["line"] for f in slide("## 連絡の決まり\n\n- だから、資料は先に配る\n")], [3])

    def test_heading_rule_is_only_for_slides(self):
        for doc_type in (None, "article", "minutes", "pr"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual(slide("## 道が混んだら、開始を遅らせる\n", doc_type=doc_type), [])


# 3.4.0: 見出しの読点の説明（docs/tools.md と README.en.md）が、今の lint と diff の動きと合う。文はすべて自作の合成の文
def condition_changes(old, new):
    return [(m["orig"], m["rewrite"]) for m in yomiyasu_diff.diff(old + "\n", new + "\n")["markers"] if m["kind"] == "条件"]


class SlideHeadingDocsTest(unittest.TestCase):
    def test_tools_md_on_the_condition_count(self):
        # diff の条件の読点の直し（3.4.0）が入ったので、見出しの「なら、」「たら、」の読点だけを外しても条件の増減は出ない
        tools = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
        self.assertIn("見出しの「なら、」「たら、」の読点だけを外した推敲では、diff は条件の増減を出しません。"
                      "読点と一緒にすぐ前かすぐあとの語も変えたときは出ることがあります。", tools)
        self.assertNotIn("「条件: 1 → 0」が出ます", tools)
        for old, new in (("## 霧が出たら、ロープウェイを運休する", "## 霧が出たらロープウェイを運休する"),
                         ("## 雨なら、屋内で集まる", "## 雨なら屋内で集まる")):
            with self.subTest(old=old):
                self.assertEqual(condition_changes(old, new), [])
        # 読点と一緒に、すぐあとの語（会の）か、すぐ前の語（雨 → 雨天）も変えた推敲では出る
        self.assertEqual(condition_changes("## 質問があるなら、会の最後に", "## 質問があるなら最後に"), [(1, 0)])
        self.assertEqual(condition_changes("## 雨なら、中止", "## 雨天なら中止"), [(1, 0)])

    def test_tools_md_limits_on_quote_marks_and_hits(self):
        tools = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
        self.assertIn("〝〟と全角の＂＂は引用符に数えないので、その中の読点も候補に出ます（〝はい、いいえ〟で答える）。", tools)
        self.assertIn("「〝はい、」", slide("## 〝はい、いいえ〟で答える\n")[0]["message"])
        self.assertIn("「＂はい、」", slide("## ＂はい、いいえ＂で答える\n")[0]["message"])
        # 当たった言い方の限り（見出しの行は候補に出る）
        self.assertIn("同じ言い方の読点が2つあっても1つだけ並べます", tools)
        self.assertEqual([f["line"] for f in slide("## 確認、確認、また確認\n")], [1])
        self.assertEqual(slide("## 確認、確認、また確認\n")[0]["message"].count("「確認、」"), 1)
        self.assertIn("「…、」", slide("## 「速く、正しく」、そして安く\n")[0]["message"])
        self.assertIn("「０００件、」", slide("## １２，０００件、達成\n")[0]["message"])

    def test_readme_en_on_headings_and_bullets(self):
        readme = (ROOT / "README.en.md").read_text(encoding="utf-8")
        self.assertIn("in one-line bullets the skill removes those commas and keeps commas for contrast, conditions, reasons and lists. "
                      "Since 3.4.0, in `#` headings other than the document title, `slide_comma` marks every Japanese comma (、 and ，) "
                      "except those inside quotation marks, code, link text and URLs and those used as digit separators. "
                      "Unless the request specifies the heading format, the instructions tell the skill to remove them",
                      readme)
        self.assertNotIn("the skill removes those commas and keeps commas for contrast, conditions, reasons and lists.", readme.replace(
            "in one-line bullets the skill removes those commas", ""))
        # 書いてある動き: 題でない「#」の見出しは条件の読点も候補、1行の箇条の条件の読点は残す、引用の中と数字の区切りとコードとリンクの文字は見ない
        found = slide("# 題\n\n## 道が混んだら、開始を遅らせる\n\n- 急ぎなら、電話で連絡する\n\n## 「止める、知らせる」と月3,200件\n\n"
                      "## `a、b` を使う\n\n## [速く、正しく](https://example.com/a、b) を読む\n")
        self.assertEqual([f["line"] for f in found], [3])
        self.assertIn(HEADING_MESSAGE, found[0]["message"])


if __name__ == "__main__":
    unittest.main()
