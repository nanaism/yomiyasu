#!/usr/bin/env python3
"""v2.0.0（3回目の直し）: 2回目の反証で判断が要るとして残した点のうち、決めたものを直した試験。

文はすべてこのファイルで作った合成の文（反証で見つけた例と、それを言い換えた文）。実在の会社や商品の名前は使わない。

- 数量を主張しない「一つ」: 「一つのみ」「1つのみ」は数を限る言い方なので、数量を主張しない値にしない。「一つの」「一つずつ」は、
  組の相手の文に数を言う語（まとめて、並列、同時、複数、上限、すべて など）が新しく出れば比べに残す（「一つずつ → まとめて」
  「一つの → 複数の」を見逃さない）。「一つの」「一つずつ」「もう一つ」を数量を主張しない値にするのは漢数字の「一つ」だけで、
  算用数字の「1つ」は数として数える（「1つのリクエストで送る」のように数を言う書き方に使われやすいため。次の直しで、漢数字の
  「一つ」と同じ扱いに改めた。test_v200_fix_round4_diff）。繰り返しの「1つ1つ」と
  強めた否定の「1つも〜ない」は、どちらの書き方でも数量を主張しない（正しい推敲への候補を増やさない）。
- 否定対比の逆転: 見出しの行と「Aは使わず」「Aはせず」の印から取った名詞は、推敲後の A の節そのものに重みの語があるときだけ
  候補にする（文のどこかの「まず」では数えない。見出しと表を見るのは続ける）。否定対比の名詞に、平仮名の入る和語の名詞
  （見た目、使い方、締め切り、言い方）も取る（送り仮名として漢字の間に「た」「い」「め」「わ」を許す。硬化の名詞の数え方は
  変えない）。
- 直前が漢字の漢数字: 頻度の「年」「月」「週」「日」のあと（年二回、月一回、週三日）と、漢数字に続いた助数詞のあと（十月十三日、
  一時間三十分、十時三十分）の漢数字も数として取る。漢数字の助数詞に「時」を足す（「一時」は今までどおり除く。十一時は取る）。
  漢数字を算用数字にしただけの書き換えを候補にせず、漢数字どうしの値の変化を拾う。
- 公開の前の掃除: リポジトリで公開するファイルに、手元の開発のフォルダの名前を書かない。fixture の説明の欄（description、
  generated_by、source_commit、updates）には、手元の記録と道具の名前も書かない。

3回目の直しのあとの反証で見つけた例の直し（このファイルの後半）:

- 「一つの」「一つずつ」の相手の文の語: 形ごとに見る語を分ける（「一つずつ」は まとめて・一括・一度に・並列・並行・同時、
  「一つの」は 複数・いくつ・すべて・上限・無制限）。書き方の違い（全て・全部 → すべて、一括・一度に → まとめて、並行 → 並列）は
  そろえてから比べる。2つの文をまとめた・分けた推敲では、組の文のすぐ前とすぐあとの組にならなかった文の語も合わせて見る。
  （2回目の反証のあとで、語と、つなぐ文の決まりを直した。このファイルの最後の節）
- 期間の語のあとの「一日」「一年」（今日一日、本日一日、去年一年）と、「日一日と」「年一年と」は数にしない。（2回目の反証の
  あとで、数量を主張しない値として取る形に直し、算用数字の「今日1日」は数として取るように戻した。このファイルの最後の節）
- 「十時十分」「一時間十分」の「十分」、直前が漢数字に続いた「人」「名」「回」「件」「個」「枚」の漢数字（一人一回、一人三千円、
  一回三十分）、「午前」と元号（令和、平成、昭和、大正、明治）のあとの漢数字を数として取る。
- 見出しと「は使わず」「はせず」の否定対比: A の節のすぐ前が主題の句（「最優先は、」「大事なのは、」）なら、その句の重みの語も
  A の節の重みとして見る。
- 否定対比の逆転の候補で示す語は、取った語のあとの送り仮名まで示す（「問い合」でなく「問い合わせ」）。比べに使う語は変えない。
  「Aは減らす」は A を下げた形とみなす（「Aを減らすことを最優先にする」は下げた形にしない）。

3回目の直しのあとの2回目の反証で見つけた例の直し（このファイルの最後の節）:

- 期間の語のあとの値: 算用数字の「1日」「1年」（今日1日、本日1日）はいつも数として取る（1回目の直しでは取らなかったので、
  「本日1日は → 本日は1日」のように助詞を足しただけの推敲が片側だけの値になり、「今日1日 → 今日から数日」を見逃した）。
  漢数字の「今日一日」「日一日と」は、数量を主張しない「一つ」と同じ値として取る（相手の側に同じ単位の値がなければ比べから
  外す。「今日一日 → 今日1日」「今日一日 → 今日は」は候補にしない）。1日しかない日（当日、前日、翌日、初日、元日、日曜日など）の
  あとの「一日」も同じ。
- 「十分」: 前に漢数字のない「一時」（一時的に）のあとの「十分」は取らない。「時間」と、漢数字に続いた「人」「名」「回」「件」
  「個」「枚」のあとの「十分」は、時間の量に続く字（の、読点、まで、かかる、とする など）が続くときだけ取る（「一時間十分かかった」
  「一人十分とする」は時間、「七時間十分眠れば」「八時間十分とる」はじゅうぶん）。
- 「一つの」「一つずつ」の相手の文の語: 打ち消した語（並列にせず、複数に分けない）は数えない（「上限」は逆で、打ち消したとき
  だけ数える）。複数といくつ、すべてと語の頭の「各」はそろえて比べ、語の中の「全部」（全部署、全部屋）は数えない。「一つずつ」に
  複数・一斉・一気に・いっぺんに、「一つの」に別々を足した。相手の文で「一つの」の名詞や「一つずつ」の動詞のすぐ前の語を見て、
  数の主張が同じ語（同じ窓口、順に確認）なら変わっていない、変わった語（複数のファイル、まとめて実行）なら変わったとみなす
  （2つの文をまとめた推敲で、元の隣の文の「複数」が「一つの」の名詞に移った形も拾う）。分けた推敲で隣の文をつなぐのは、
  自分の側に「一つの」「一つずつ」があるとき、相手の側に「一つずつ」があるとき、相手の側の「一つの」の名詞が隣の文に出るときだけ。
- 否定対比の逆転: 「は減ら」は A のすぐあと（送り仮名2字まで）だけを A を下げた形とみなし、同じ節のあとに重みの語があれば
  （Aは減らすことを最優先にする）下げた形にしない。「高い品質」のような漢字1字の形容詞と名詞は、名詞（品質）も否定された語として
  見る。示す語は、送り仮名が「も」「が」で始まる語（見積もり、出来上がり）も送り仮名まで示し、助詞の「など」「まで」などは足さない。

3回目の直しのあとの3回目の反証で見つけた例の直し（このファイルの最後の節）:

- 「一つの」「一つずつ」の相手の文の打ち消し: 数を言う語のあとから、その語がかかる述語の終わり（ので、ため、ても、から、動詞に
  続く「て」の前）までを見る。「ではなく」「でなく」「ことなく」は打ち消し。義務や条件の言い方（なければならない、ないといけない、
  ないと間に合わない、ざるを得ない、しかない、ほかない、かもしれない）と、平仮名の動詞（おこなう、おはなし）の「な」は打ち消しに
  しない。「上限」は、上限そのものを打ち消したとき（上限はない、上限なし、上限を設けない、上限をなくす、撤廃する）だけ数える。
- 「一つの」「一つずつ」の相手の文の語: 相手の文が1つの文で、「一つの」の名詞か「一つずつ」の動詞が出るなら、その語のある節
  （助詞で終わる節は次の節も）の語だけを数える（別の述語や別の名詞にかかる語を数えない）。「すべて」と語の頭の「各」は、
  「一つの」の名詞のすぐ前（すべての窓口、各窓口）だけで見る。「〜ごとの」「〜ごとに別の」が名詞のすぐ前にあれば、数の主張が
  変わった形。「いくつ」は「いくつか」「いくつも」「いくつでも」だけ。名詞・動詞のすぐ前の語は、変わった形を先に見る（同じ文の
  別の節の「同じ窓口」「順に」で見逃さない）。
- 否定対比の逆転: 「Aの数・回数・件数・時間・量・頻度・割合は減ら」も A を下げた形。「は減ら」のあとの重みの語で下げた形に
  しないのは、「減らすこと」「減らすのが」のときだけ（読点のない「Aは減らして B を優先する」は下げた形）。送り仮名の
  「い」「た」「め」のあとに2字以上の漢字が続く語（支払い期限、得た知識）は、あとの名詞も否定された語として見る。
- 数値: 「一日十分」「毎日十分」の「十分」と、「一人十分で」のように「で」が続く「十分」を時間として取る（十分です、十分できる、
  十分でしょう は除く）。前に漢数字のない「一時」のあとの「十分」は、時刻に続く字（まで、から、頃 など）が続くときだけ取る。
  時刻を言う語（午前、午後、深夜、夕方、毎朝 など）と1字の 朝・夜・晩・昼 のあとの「時」（朝九時、夜十時、午前一時）を取る。
"""

from pathlib import Path
import json
import re
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import ROOT, SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402


def result_of(before, after, doc_type=None):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after, doc_type=doc_type)


def number_risks(before, after, doc_type=None):
    return [(risk["subkind"], risk["detail"]["removed"], risk["detail"]["added"])
            for risk in result_of(before, after, doc_type)["meaning_risks"] if risk["kind"] == "number"]


def reversal_words(before, after, doc_type=None):
    return [risk["detail"]["word"] for risk in result_of(before, after, doc_type)["meaning_risks"]
            if risk["kind"] == "contrast_reversal"]


def unsupported_numbers(final, materials):
    result = yomiyasu_diff.ground(final + "\n", [material + "\n" for material in materials])
    return [risk["detail"]["text"] for risk in result["meaning_risks"] if risk["subkind"] == "number"]


# ---- 「一つのみ」「1つのみ」は数を限る言い方 ----
class OneOnlyTest(unittest.TestCase):
    LOST = (
        ("添付できるファイルは一つのみです。", "添付できるファイルは複数でもかまいません。", "一つ", "formal"),
        ("登録できる端末は1つのみです。", "登録できる端末に上限はありません。", "1つ", "formal"),
        ("選べるコースは一つのみとする。", "選べるコースは自由とする。", "一つ", None),
    )

    def test_one_only_is_a_quantity(self):
        for before, after, text, doc_type in self.LOST:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after, doc_type), [("lost", [text], [])])
                self.assertGreater(result_of(before, after, doc_type)["fail_on_meaning_risk_count"], 0)

    def test_same_limit_is_not_a_candidate(self):
        """「一つのみ」を「一つだけ」にした言い換えは、値が同じなので出さない。"""
        self.assertEqual(number_risks("選べるのは一つのみです。", "選べるのは一つだけです。"), [])

    def test_one_only_in_new_writing_is_checked(self):
        """新規作成の照合でも、「一つのみ」は資料にない数値の候補にする。"""
        self.assertEqual(unsupported_numbers("添付できるファイルは一つのみです。", ["添付できるファイルの決まり。"]), ["一つ"])


# ---- 「一つの」「一つずつ」と、相手の文の数を言う語 ----
class OnePartnerQuantityTest(unittest.TestCase):
    FOUND = (
        ("ファイルを一つずつ処理します。", "ファイルをまとめて処理します。", [("lost", ["一つ"], [])], "article"),
        ("一つのインスタンスで動かす。", "複数のインスタンスで動かす。", [("lost", ["一つ"], [])], "article"),
        ("ジョブを一つずつ流す。", "ジョブを並列に流す。", [("lost", ["一つ"], [])], None),
        ("リクエストを一つずつ送る。", "リクエストを同時に送る。", [("lost", ["一つ"], [])], None),
        ("一つのファイルだけを直す。", "すべてのファイルを直す。", [("lost", ["一つ"], [])], None),
        ("一つのアカウントで使う。", "アカウントの数に上限はない。", [("lost", ["一つ"], [])], "formal"),
        # 逆向き（数を言う語を消して「一つずつ」「一つの」にした）
        ("ファイルをまとめて処理します。", "ファイルを一つずつ処理します。", [("added", [], ["一つ"])], "article"),
        ("複数のインスタンスで動かす。", "一つのインスタンスで動かす。", [("added", [], ["一つ"])], None),
    )
    NOT_FOUND = (
        # 相手の文に数を言う語がない（足しただけ、消しただけ）
        ("手順を確かめる。", "手順を一つずつ確かめる。"),
        ("単語を覚えていく。", "単語を一つずつ覚えていく。"),
        ("一つの画面で確かめる。", "画面で確かめる。"),
        ("サービスを分けた。", "サービスを分けたので、一つのサービスの障害が他へ広がりにくい。"),
        # 数を言う語が両方の文にもともとある（新しく出た語ではない）
        ("一つずつ順に、すべての項目を見直す。", "すべての項目を順に見直す。"),
        ("項目を一つずつ見直し、複数の担当で分ける。", "項目を見直し、複数の担当で分ける。"),
    )

    def test_quantity_word_in_the_partner_keeps_the_one(self):
        for before, after, expected, doc_type in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after, doc_type), expected)

    def test_one_without_a_quantity_word_is_still_not_a_candidate(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                result = result_of(before, after)
                self.assertEqual([risk for risk in result["meaning_risks"] if risk["kind"] == "number"], [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_other_weak_forms_do_not_use_the_partner(self):
        """「一つも」「一つひとつ」「もう一つ」は、相手の文に数を言う語があっても今までどおり数量を主張しない値。"""
        for before, after in (("エラーは一つも出ませんでした。", "すべての処理でエラーは出ませんでした。"),
                              ("設定を一つひとつ確かめる。", "すべての設定を確かめる。"),
                              ("理由がある。", "複数の理由のほかに、もう一つ理由がある。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])


# ---- 算用数字の「1つ」 ----
# この直しでは算用数字の「1つ」を数として数えたが、「もう1つの利点は → 〜も利点です」「1つずつ → 順に」のような正しい推敲に
# 候補が出たので、次の直しで漢数字の「一つ」と同じ扱いに改めた（test_v200_fix_round4_diff.ArabicOneLikeKanjiTest）。
# 数量の主張が変わった形（1つの → 複数の）は今も数える。
class ArabicOneTest(unittest.TestCase):
    COUNTED = (
        ("設定は1つのファイルにまとめる。", "設定は複数のファイルに分ける。", [("lost", ["1つ"], [])]),
    )
    # 次の直しで、漢数字の「一つの」「もう一つ」「一つずつ」と同じく数量を主張しない値にした形（この直しでの期待は、順に
    # lost 1つ、added 1つ、added 1つ、lost １つ だった）
    LIKE_KANJI = (
        ("1つの画面で確かめる。", "画面で確かめる。"),
        ("理由がある。", "もう1つ理由がある。"),
        ("手順を確かめる。", "手順を1つずつ確かめる。"),
        ("ファイルを１つずつ送る。", "ファイルを送る。"),
    )

    def test_arabic_one_is_counted(self):
        for before, after, expected in self.COUNTED:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)

    def test_arabic_one_like_kanji(self):
        for before, after in self.LIKE_KANJI:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_arabic_idioms_are_not_counted(self):
        """繰り返しの「1つ1つ」と強めた否定の「1つも〜ない」は、算用数字でも数量を主張しない（正しい推敲の「1つ1つ → 順に」を
        元にない数値にしない）。"""
        for before, after in (("項目を1つ1つ確かめる。", "項目を順に確かめる。"),
                              ("警告を1つ1つ消しました。", "警告を順に消しました。"),
                              ("エラーは1つも出ませんでした。", "エラーは出ませんでした。"),
                              ("設定を1つひとつ確かめる。", "設定を順に確かめる。")):
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])
        self.assertEqual(number_risks("候補を1つもしくは2つ選ぶ。", "候補を2つ選ぶ。"), [("lost", ["1つ"], [])])

    def test_kanji_and_arabic_one_are_the_same_value(self):
        """「一つの」を「1つの」にしただけの書き換えは表記の違い（候補なし）。"""
        for before, after in (("一つの画面で確かめる。", "1つの画面で確かめる。"),
                              ("1つの画面で確かめる。", "一つの画面で確かめる。"),
                              ("手順を一つずつ確かめる。", "手順を1つずつ確かめる。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_arabic_one_in_new_writing_is_checked(self):
        """新規作成の照合: 「1つのみ」は資料にない数値の候補にする。「1つの」は、次の直しで漢数字の「一つの」と同じく出さない
        ことにした（この直しでの期待は ["1つ"]）。"""
        self.assertEqual(unsupported_numbers("登録できる端末は1つのみです。", ["端末の登録の決まり。"]), ["1つ"])
        self.assertEqual(unsupported_numbers("新しい画面を1つの画面にまとめました。", ["新しい画面を作る。"]), [])
        self.assertEqual(unsupported_numbers("新しい画面を一つの画面にまとめました。", ["新しい画面を作る。"]), [])

    def test_kanji_forms_are_still_weak(self):
        for before, after in (("エラーは一つも出ませんでした。", "エラーは出ませんでした。"),
                              ("設定を一つひとつ確かめる。", "設定を順に確かめる。"),
                              ("思い出を一つ一つ書き出した。", "思い出を順に書き出した。"),
                              ("理由がある。", "もう一つ理由がある。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])


# ---- 見出しと「Aは使わず」「Aはせず」の否定対比: A の節の重みの語だけを見る ----
class HeadingZuClauseWeightTest(unittest.TestCase):
    NOT_FOUND = (
        # A を後ろに回したまま（重みの語は A の節の外）
        ("## ツールではなく習慣から変える", "## まず習慣、ツールはその次", "slides"),
        ("## 速さではなく読みやすさを優先する", "## 読みやすさを最優先に、速さはその次", "article"),
        ("今日は作業はせず、まず休む。", "今日はまず休み、作業は明日にする。", None),
        ("外部委託はせず、まず社内で作る。", "まず社内で作り、外部委託はその次にする。", None),
    )
    FOUND = (
        ("## 速さではなく読みやすさを優先する", "## 速さを最優先にする", "速さ", "article"),
        ("## ツールではなく習慣から変える", "## まずツールから変える", "ツール", "slides"),
        # 重みの語がなくても、B と並べて肯定する形（AとB）は今までどおり拾う
        ("## ツールではなく習慣から変える", "## ツールと習慣から変える", "ツール", "slides"),
        ("外部委託はせず、社内で作ることを最優先にします。", "外部委託で作ることを最優先にします。", "外部委託", None),
        ("外部委託はせず、社内で作ることを最優先にします。", "外部委託と社内での開発を両立させます。", "外部委託", None),
    )

    def test_weight_outside_the_clause_is_not_a_reversal(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_weight_in_the_clause_is_still_a_reversal(self):
        for before, after, word, doc_type in self.FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [word])

    def test_paragraph_contrast_keeps_the_sentence_rule(self):
        """見出しでも「使わず」「せず」でもない本文の「Aではなく」は、今までどおり文の重みの語で見る（この直しの範囲の外）。
        次の直しで「その次」を A を下げる言い方に足したので、一覧にない「午後に」の文で確かめる（前の文「キャッシュはその次に見る」は
        今は逆転の候補にならない。test_v200_fix_round4_diff.DemoteWordTest）。"""
        self.assertEqual(reversal_words("キャッシュではなく、まずDNSを疑う。", "まずDNSを疑い、キャッシュは午後に見る。"),
                         ["キャッシュ"])

    def test_known_limits(self):
        """残る形: 重みの語が A と同じ節にある書き換え（「まずステージングでキャッシュを試し」）は出る。A の節に重みの語が
        なく「Aも」で A を足した書き換え（「外部委託も使います」）は出ない。"""
        self.assertEqual(reversal_words("本番環境ではキャッシュは使わず、まずステージングで試す。",
                                        "まずステージングでキャッシュを試し、本番環境ではまだ使わない。", "article"),
                         ["キャッシュ"])
        self.assertEqual(reversal_words("外部委託はせず、社内で作ることを最優先にします。",
                                        "社内で作ることを最優先にし、外部委託も使います。"), [])


# ---- 直前が漢字の漢数字（頻度の年・月・週・日のあと、漢数字に続いた助数詞のあと、「時」）----
class KanjiAfterCounterTest(unittest.TestCase):
    NOTATION = (
        ("申請は年二回とする。", "申請は年2回とする。", "formal"),
        ("会議は週二回開きます。", "会議は週2回開きます。", None),
        ("点検は月一回行う。", "点検は月1回行う。", None),
        ("薬は一日三回飲む。", "薬は1日3回飲む。", None),
        ("打ち合わせは十時三十分からです。", "打ち合わせは10時30分からです。", None),
        ("九時五十分に集合する。", "9時50分に集合する。", None),
        ("施行日は十月十三日とする。", "施行日は10月13日とする。", "formal"),
        ("所要時間は一時間三十分です。", "所要時間は1時間30分です。", "manual"),
        ("契約期間は二年三か月とする。", "契約期間は2年3か月とする。", "formal"),
        ("説明会は年二〜三回開く。", "説明会は年2〜3回開く。", None),
        ("受付は十一時までです。", "受付は11時までです。", None),
    )
    REPLACED = (
        ("申請は年二回とする。", "申請は年一回とする。", ["二回"], ["一回"], "formal"),
        ("施行日は十月十三日とする。", "施行日は十月十五日とする。", ["十三日"], ["十五日"], "formal"),
        ("所要時間は一時間三十分です。", "所要時間は一時間四十分です。", ["三十分"], ["四十分"], "manual"),
        ("打ち合わせは十時三十分からです。", "打ち合わせは十一時三十分からです。", ["十時"], ["十一時"], None),
        ("会議は週二回開きます。", "会議は週三回開きます。", ["二回"], ["三回"], None),
    )

    def test_kanji_to_arabic_is_notation(self):
        for before, after, doc_type in self.NOTATION:
            with self.subTest(before=before):
                result = result_of(before, after, doc_type)
                self.assertEqual(number_risks(before, after, doc_type), [])
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)

    def test_kanji_value_change_is_replaced(self):
        for before, after, removed, added, doc_type in self.REPLACED:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after, doc_type), [("replaced", removed, added)])

    def test_words_that_are_not_numbers(self):
        for text in ("四六時中考えている。", "一時的に止める。", "同時に処理する。", "当時の記録を読む。"):
            with self.subTest(text=text):
                self.assertEqual([number["text"] for number in yomiyasu_diff.extract_numbers(text)], [])

    def test_hours_are_numbers(self):
        self.assertEqual([number["text"] for number in yomiyasu_diff.extract_numbers("朝の五時に出て、十二時五十分に着いた。")],
                         ["五時", "十二時", "五十分"])

    def test_new_writing_uses_the_same_rule(self):
        """新規作成の照合: 資料の「年二回」と最終稿の「年2回」は同じ値。"""
        self.assertEqual(unsupported_numbers("申請は年2回とする。", ["申請は年二回とする。"]), [])

    def test_known_limits(self):
        """残る形: 「一時」は「一時的」と分けられないので数にしない（一時三十分 → 1時30分 は 1時 が元にない数値）。
        （「午前二時」は、反証で見つけた例の直しで「午前」のあとの漢数字を取るようにした。KanjiChainMoreTest）"""
        self.assertEqual(number_risks("一時三十分に始める。", "1時30分に始める。"), [("added", [], ["1時"])])


# ---- 平仮名の入る和語の名詞（否定対比の逆転）----
class HiraganaNounContrastTest(unittest.TestCase):
    FOUND = (
        ("見た目ではなく、読み込みの速さを優先した。", "見た目と読み込みの速さを優先した。", "見た目", "article"),
        ("見た目ではなく、読み込みの速さを優先した。", "まず見た目を整えることを優先した。", "見た目", "article"),
        ("大事なのは道具の使い方ではなく、使う目的だ。", "大事なのは使い方だ。", "使い方", "essay"),
        ("締め切りではなく、品質を基準に判断する。", "締め切りを最優先の基準に判断する。", "締め切り", "pr"),
        ("言い方ではなく、中身を変えるのが目的です。", "言い方と中身を変えるのが目的です。", "言い方", "manual"),
        ("見た目ではなく中身で選ぶ。", "見た目だけでなく中身でも選ぶ。", "見た目", "promo"),
    )
    NOT_FOUND = (
        ("見た目ではなく、読み込みの速さを優先した。", "読み込みの速さを優先した。", "article"),
        ("見た目ではなく、読み込みの速さを優先した。", "見た目より読み込みの速さを優先した。", "article"),
        ("見た目ではなく、読み込みの速さを優先した。", "読み込みの速さを最優先にし、見た目は後回しにした。", "article"),
        ("大事なのは道具の使い方ではなく、使う目的だ。", "大事なのは使う目的だ。", "essay"),
        ("締め切りではなく、品質を基準に判断する。", "判断の基準は品質で、締め切りではない。", "pr"),
        ("言い方ではなく、中身を変えるのが目的です。", "言い方は変えず、中身を変えるのが目的です。", "manual"),
        ("来た時ではなく、帰る時に確かめる。", "帰る時に確かめる。", None),
    )

    def test_hiragana_nouns_are_found(self):
        for before, after, word, doc_type in self.FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [word])

    def test_correct_rewrites_are_not_found(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_stiffness_nouns_are_not_widened(self):
        """硬化の検査の名詞化の数え方は変えない（平仮名の入る語を足しても、硬化の候補は出ない）。"""
        result = result_of("見た目を整えるのが目的だ。", "見た目の整備が目的だ。")
        self.assertEqual(result["stiffness"]["candidates"], [])


# ==== 3回目の直しのあとの反証で見つけた例 ====

def fail_on_count(before, after, doc_type=None):
    return result_of(before, after, doc_type)["fail_on_meaning_risk_count"]


def numbers_in(text):
    return [number["text"] for number in yomiyasu_diff.extract_numbers(text)]


# ---- 「一つの」「一つずつ」の相手の文の語: 形ごとの語、書き方の違い、まとめた・分けた文 ----
class OnePartnerFormTest(unittest.TestCase):
    # 正しい推敲（数の主張は変わっていない）
    NOT_FOUND = (
        # 「一つの」と同じ向きの語（一つにまとめる）
        ("手順を一つの表に整理します。", "手順を表にまとめて整理します。"),
        ("設定を一つのファイルに書きます。", "設定をまとめてファイルに書きます。"),
        # 「一つずつ」と同じことを言う「すべて順に」
        ("設定は一つずつ見直します。", "設定はすべて順に見直します。"),
        # 数を言う語の書き方だけを変えた（すべて → 全て など）
        ("項目を一つずつ確認し、すべて記録します。", "項目を順に確認し、全て記録します。"),
        ("一つの画面で、すべての値を確かめます。", "画面で、全ての値を確かめます。"),
        ("手順を一つずつ見直し、全部の結果を残します。", "手順を順に見直し、すべての結果を残します。"),
        # 2つの文を1つにまとめた（数を言う語は元の隣の文にもともとある）
        ("申請書は一つずつ確認します。すべての確認が済んだら連絡します。", "申請書は順に確認し、すべて済んだら連絡します。"),
        ("庭の花を一つずつ数えた。全部で十二輪あった。", "庭の花を数えると、全部で十二輪あった。"),
        ("彼女は窓の灯りを一つずつ消していった。すべての部屋が暗くなった。", "彼女は窓の灯りを順に消し、すべての部屋が暗くなった。"),
        ("入力は一つの画面で受け付ける。上限は五十件とする。", "入力は同じ画面で受け付け、上限は五十件とする。"),
        ("設定の読み込みを一つの関数にまとめました。すべての呼び出し元を直しました。",
         "設定の読み込みを関数にまとめ、呼び出し元をすべて直しました。"),
        ("障害の原因を一つずつ切り分けた。複数の要因が重なっていた。", "障害の原因を順に切り分けると、複数の要因が重なっていた。"),
        # 隣の文も組になっている（まとめても分けてもいない）ときは、その文の語を見ない（塊の文すべてでは見ない）
        ("設定は一つのファイルに書く。ログは毎日見る。", "設定はファイルに書く。ログは複数の担当で見る。"),
        ("手順は一つずつ確かめる。結果は表に書く。", "手順を順に確かめる。結果はまとめて表に書く。"),
    )
    # 数の主張が変わった（文を分けた推敲の、あとの文に数を言う語が出た形を含む）
    FOUND = (
        ("ジョブは一つずつ実行する。", "ジョブを実行する。ただし並列で動かす。", [("lost", ["一つ"], [])]),
        ("設定は一つのファイルに書く。", "設定はファイルに書く。ファイルは複数に分けてよい。", [("lost", ["一つ"], [])]),
        ("申請書は一つずつ受け付けます。", "申請書を受け付けます。まとめて出してもかまいません。", [("lost", ["一つ"], [])]),
        ("鍵は一つずつ貸し出します。", "鍵は一度に何本でも貸し出します。", [("lost", ["一つ"], [])]),
        ("処理は一つずつ行う。", "処理は並行で行う。", [("lost", ["一つ"], [])]),
    )

    def test_correct_rewrites_have_no_number_candidate(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_changed_quantity_is_found(self):
        for before, after, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)


# ---- 期間の語のあとの「一日」「一年」と、「日一日と」「年一年と」 ----
class WholePeriodTest(unittest.TestCase):
    NOT_NUMBER = (
        ("日一日と寒くなります。", "日ごとに寒くなります。"),
        ("日一日と暖かくなる。", "日に日に暖かくなる。"),
        ("日一日と、彼の足音は遠くなった。", "日に日に、彼の足音は遠くなった。"),
        ("年一年と、町の灯りが減っていった。", "年を追うごとに、町の灯りが減っていった。"),
        ("今日一日、資料の整理に充てます。", "今日は、資料の整理に充てます。"),
        ("本日一日、窓口を閉めます。日一日と寒くなりますので、お気をつけください。",
         "本日は、窓口を閉めます。日ごとに寒くなりますので、お気をつけください。"),
        ("去年一年で、利用者が増えました。", "去年は、利用者が増えました。"),
        ("今週一週間は、在宅で働きます。", "今週は、在宅で働きます。"),
        # 算用数字にしただけの書き換え（漢数字の「今日一日」は数量を主張しない値、算用数字の「今日1日」は数。値が同じなので
        # 候補にしない）
        ("今日一日、資料の整理に充てます。", "今日1日、資料の整理に充てます。"),
        ("去年一年で、利用者が増えました。", "去年1年で、利用者が増えました。"),
    )

    def test_whole_period_is_not_a_number(self):
        for before, after in self.NOT_NUMBER:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_other_numbers_after_a_period_word_are_kept(self):
        """「毎年一年分」「今月三日」「今年二年目」「十月一日」は数のまま。"""
        self.assertEqual(numbers_in("毎年一年分を残す。"), ["一年"])
        self.assertEqual(numbers_in("今月三日に出す。"), ["三日"])
        self.assertEqual(numbers_in("今年二年目を迎えた。"), ["二年"])
        self.assertEqual(numbers_in("十月一日に出す。"), ["十月", "一日"])
        self.assertEqual(number_risks("毎年一年分のデータを保存します。", "毎年データを保存します。"), [("lost", ["一年"], [])])
        self.assertEqual(number_risks("点検は年二回です。", "点検は年一回です。"), [("replaced", ["二回"], ["一回"])])
        self.assertEqual(numbers_in("今月1日に出す。"), ["1日"])

    def test_new_writing_uses_the_same_rule(self):
        """新規作成の照合: 資料の「今日一日」は、最終稿の「今日1日」の裏づけになる（値が同じ）。"""
        self.assertEqual(unsupported_numbers("今日1日、資料の整理に充てます。", ["今日一日、資料の整理に充てます。"]), [])


# ---- 「十時十分」の「十分」、「一人一回」、「午前九時」と元号のあとの漢数字 ----
class KanjiChainMoreTest(unittest.TestCase):
    NOTATION = (
        ("次回は十時十分から始める。", "次回は10時10分から始める。"),
        ("ビルドに一時間十分かかった。", "ビルドに1時間10分かかった。"),
        ("二十一時十分に復旧した。", "21時10分に復旧した。"),
        ("受付は午後五時十分までとする。", "受付は午後5時10分までとする。"),
        ("応募は一人一回までとする。", "応募は1人1回までとする。"),
        ("参加費は一人三千円です。", "参加費は1人3000円です。"),
        ("受付は午前九時から午後五時までとする。", "受付は午前9時から午後5時までとする。"),
        ("午前二時に動く。", "午前2時に動く。"),
        ("この規程は、令和七年四月一日から施行する。", "この規程は、令和7年4月1日から施行する。"),
        ("制度は平成三十年に始まった。", "制度は平成30年に始まった。"),
        ("昭和五十年代の写真だ。", "昭和50年代の写真だ。"),
        ("面談は一回三十分です。", "面談は1回30分です。"),
        ("部品は一個百円で売る。", "部品は1個100円で売る。"),
    )
    CHANGED = (
        ("面談は一回三十分です。", "面談は一回四十五分です。", [("replaced", ["三十分"], ["四十五分"])]),
        ("手数料は一件三百円です。", "手数料は一件五百円です。", [("replaced", ["三百円"], ["五百円"])]),
        ("次回は十時十分から始める。", "次回は十時から始める。", [("lost", ["十分"], [])]),
        ("ビルドに一時間十分かかった。", "ビルドに一時間かかった。", [("lost", ["十分"], [])]),
        ("応募は一人一回までとする。", "応募は一人三回までとする。", [("replaced", ["一回"], ["三回"])]),
        ("参加費は一人三千円です。", "参加費は一人五千円です。", [("replaced", ["三千円"], ["五千円"])]),
        ("受付は午前九時から始める。", "受付は午前十時から始める。", [("replaced", ["九時"], ["十時"])]),
        ("この規程は、令和七年四月一日から施行する。", "この規程は、令和八年四月一日から施行する。",
         [("replaced", ["七年"], ["八年"])]),
    )

    def test_kanji_to_arabic_is_notation(self):
        for before, after in self.NOTATION:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_kanji_value_change_is_found(self):
        for before, after, expected in self.CHANGED:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)

    def test_jippun_that_is_not_minutes(self):
        """「十分にある」「一時間で十分」「二時間十分に眠った」の「十分」は数にしない。"""
        self.assertEqual(numbers_in("時間は十分にある。"), [])
        self.assertEqual(numbers_in("一時間で十分だ。"), ["一時間"])
        self.assertEqual(numbers_in("昨夜は二時間十分に眠った。"), ["二時間"])
        self.assertEqual(numbers_in("次回は十時十分から始める。"), ["十時", "十分"])
        self.assertEqual(numbers_in("一人一人に聞く。"), [])

    def test_repeated_counters_stay_quiet(self):
        """「一枚一枚 → 一枚ずつ」「一回一回 → 一回ごと」は、2つ目の値を取っても候補にしない（同じ値が推敲後にある）。"""
        for before, after in (("写真を一枚一枚確かめる。", "写真を一枚ずつ確かめる。"),
                              ("一回一回の練習を大切にする。", "一回ごとの練習を大切にする。")):
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])

    def test_known_limits(self):
        """残る形: 「お一人様一つ」の「一つ」（直前が「様」）と、助数詞の一覧にない「票」は取らない。"""
        self.assertEqual(numbers_in("お一人様一つまで。"), ["一人"])
        self.assertEqual(number_risks("投票は一人一票です。", "投票は一人二票です。"), [])


# ---- 見出しと「は使わず」「はせず」: 主題の句の重みの語 ----
class TopicWeightTest(unittest.TestCase):
    FOUND = (
        ("## 自動化ではなく手作業で確かめる", "## 最優先は、自動化で確かめること", ["自動化"], "article"),
        ("クラウドは使わず、社内のサーバーで動かします。", "一番大事なのは、クラウドで動かすことです。", ["クラウド"], None),
        ("外部サービスは使わず、社内で作る。", "最優先は、外部サービスを使うことだ。", ["外部", "サービス"], None),
        ("## 速さではなく正確さを優先する", "## 目的は、速さを上げること", ["速さ"], "article"),
        ("## コストではなく品質を重視する", "## 大事なのは、コストを下げること", ["コスト"], "article"),
        ("## 新機能ではなく安定性を重視する", "## 重視するのは、新機能の追加", ["新機能"], "article"),
        ("## 速さではなく正確さを優先する", "## 優先するのは、速さ", ["速さ"], "article"),
    )
    NOT_FOUND = (
        ("## 自動化ではなく手作業で確かめる", "## 最優先は、手作業で確かめること", "article"),
        ("外部サービスは使わず、社内で作る。", "最優先は、社内で作ることだ。外部サービスは使わない。", None),
        ("## ツールではなく習慣から変える", "## 大事なのは、習慣。ツールはその次", "slides"),
        ("外部委託はせず、まず社内で作る。", "目的は、社内で作ること。外部委託はその次にする。", None),
        ("## 速さではなく読みやすさを優先する", "## 最優先は、読みやすさ。速さは二の次", "article"),
        ("クラウドは使わず、社内のサーバーで動かす。", "大事なのは、社内のサーバーで動かし、クラウドは使わないことだ。", None),
    )

    def test_weight_in_the_topic_phrase_is_a_reversal(self):
        for before, after, words, doc_type in self.FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), words)

    def test_topic_phrase_with_b_is_not_a_reversal(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_known_limits(self):
        """残る形: A を肯定した節に重みの語がなく、別の節の重みの語（これを最優先に、最優先の課題）が A を指す書き換えは
        拾わない（見出しと使わず・せずでは、A の節と、そのすぐ前の主題の句の重みの語だけを見る）。"""
        self.assertEqual(reversal_words("表計算は使わず、専用の画面で入力します。",
                                        "表計算で入力し、これを最優先の手順にします。"), [])
        self.assertEqual(reversal_words("## 手作業ではなく自動化で回す\n\n本文です。",
                                        "## 手作業で回し、自動化は最優先の課題にする\n\n本文です。", "article"), [])


# ---- 否定対比の逆転で示す語（送り仮名まで示す）と、「Aは減らす」----
class ShownWordTest(unittest.TestCase):
    def test_word_is_shown_with_its_okurigana(self):
        self.assertEqual(reversal_words("問い合わせではなく申し込みを最優先で返してください。",
                                        "問い合わせを最優先で返してください。"), ["問い合わせ"])
        self.assertEqual(reversal_words("打ち合わせではなく、文書で決めることを最優先にする。",
                                        "打ち合わせで決めることを最優先にする。"), ["打ち合わせ"])
        self.assertEqual(reversal_words("話し合いは使わず、文書で決めることを最優先にする。",
                                        "話し合いで決めることを最優先にする。"), ["話し合い"])

    def test_a_is_reduced_is_not_a_reversal(self):
        """「Aは減らす」は A を下げた形（逆転の候補にしない）。「Aを減らすことを最優先」は A が主題なので候補のまま。"""
        for before, after in (("打ち合わせではなく文書で決めることを優先する。", "文書で決めることを優先し、打ち合わせは減らす。"),
                              ("会議ではなく、文書で決めることを最優先にする。", "文書で決めることを最優先にし、会議は減らしていく。"),
                              ("残業ではなく、効率で成果を出すことが目的です。", "効率で成果を出すことが目的で、残業は減らします。")):
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), [])
        self.assertEqual(reversal_words("コストではなく品質を重視する。", "コストを減らすことを最優先にする。"), ["コスト"])
        self.assertEqual(reversal_words("## コストではなく品質を重視する", "## 大事なのは、コストを減らすこと", "article"), ["コスト"])

    def test_other_words_are_shown_as_taken(self):
        for noun in ("見た目", "使い方", "締め切り", "速さ", "外部委託"):
            with self.subTest(noun=noun):
                self.assertEqual(reversal_words("{}ではなく、品質を優先した。".format(noun),
                                                "{}と品質を優先した。".format(noun)), [noun])

    def test_message_shows_the_whole_word(self):
        result = result_of("問い合わせではなく申し込みを最優先で返してください。", "問い合わせを最優先で返してください。")
        text = yomiyasu_diff.report(result)
        self.assertIn("『問い合わせ』", text)
        self.assertNotIn("『問い合』", text)


# ==== 3回目の直しのあとの2回目の反証で見つけた例 ====

# ---- 期間の語のあとの値: 算用数字はいつも数、漢数字の「今日一日」は数量を主張しない値 ----
class WholePeriodWeakTest(unittest.TestCase):
    # 助詞を足した・消しただけか、数を期間の語から離しただけの正しい推敲（値は同じ）
    NOT_FOUND = (
        ("今週1週間は休みます。", "今週は1週間休みます。"),
        ("本日1日は休業します。", "本日は1日休業します。"),
        ("本日は1日休業します。", "本日1日は休業します。"),
        ("去年1年で会員が倍になった。", "去年の1年で会員が倍になった。"),
        ("今日一日は会議です。", "今日は1日会議です。"),
        ("今日は一日会議です。", "今日一日会議です。"),
        ("今日は1日会議です。", "今日1日会議です。"),
        ("今年1年の売上を振り返ります。", "今年の1年間の売上を振り返ります。"),
        ("来週1週間は出張です。", "来週は1週間、出張です。"),
        ("明日は1日中、外出しています。", "明日1日中、外出しています。"),
        ("娘は今年1年生になりました。", "娘はこの春、1年生になりました。"),
        ("娘はこの春、1年生になりました。", "娘は今年1年生になりました。"),
        ("明日1日（金）は休業します。", "明日（1日、金曜）は休業します。"),
        ("本日1日より受付を始めます。", "受付は本日、1日から始めます。"),
        ("今年1年目の社員が三人います。", "入社1年目の社員が今年は三人います。"),
        ("去年1年生だった子が、今年は2年生になった。", "昨年度に1年生だった子が、今年は2年生になった。"),
        ("今年一年生になった。", "今年、一年生になった。"),
        ("今年一年生になった。", "今年から1年生になった。"),
        # 1日しかない日（当日、曜日、元日）のあとの「一日」も、その日の全体を言う
        ("このチケットは当日一日限り有効です。", "このチケットは当日のみ有効です。"),
        ("入場券は、購入した当日一日に限り使える。", "入場券は、購入した当日に限り使える。"),
        ("当日一日、窓口を閉めます。", "当日は、窓口を閉めます。"),
        ("日曜日一日を、読書にあてた。", "日曜日を、読書にあてた。"),
        ("土曜日一日かけて、部屋を片付けた。", "土曜日をまるごと使って、部屋を片付けた。"),
        ("元日一日、彼は家から出なかった。", "元日、彼は家から一歩も出なかった。"),
    )
    # 期間の値を言わなくなった・変えた本当の変化（算用数字）
    CHANGED = (
        ("作業は今日1日で終えます。", "作業は今日から数日で終えます。", [("lost", ["1日"], [])]),
        ("作業は今日1日で終えます。", "作業は今日の午前中で終えます。", [("lost", ["1日"], [])]),
        ("改修は今週1週間で終えます。", "改修は今週から数週間で終えます。", [("lost", ["1週間"], [])]),
        ("去年1年で会員が倍になった。", "去年の半年で会員が倍になった。", [("lost", ["1年"], [])]),
        ("本日1日限りのセールです。", "本日から数日間のセールです。", [("lost", ["1日"], [])]),
        ("明日1日は窓口を閉めます。", "明日から2日間は窓口を閉めます。", [("replaced", ["1日"], ["2日"])]),
        ("当日一日に三回まで入場できます。", "当日一日に五回まで入場できます。", [("replaced", ["三回"], ["五回"])]),
    )

    def test_same_value_is_not_a_candidate(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_changed_period_is_found(self):
        for before, after, expected in self.CHANGED:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)
                self.assertGreater(fail_on_count(before, after), 0)

    def test_new_writing(self):
        """新規作成の照合: 期間の語との間に助詞を足しただけの最終稿は、資料にない数値にしない。資料にない「今日1日」は候補。"""
        self.assertEqual(unsupported_numbers("本日は1日臨時休業します。営業の再開は明日です。",
                                             ["本日1日は臨時休業します。営業の再開は明日です。"]), [])
        self.assertEqual(unsupported_numbers("このチケットは当日一日限り有効です。", ["このチケットは当日のみ有効です。"]), [])
        self.assertEqual(unsupported_numbers("日曜日一日を読書にあてた。", ["日曜日を読書にあてた。"]), [])
        self.assertEqual(unsupported_numbers("作業は今日1日で終えます。", ["作業は今日の午前中で終えます。"]), ["1日"])


# ---- 「十分」: 「一時（いちじ）十分に」「七時間十分眠る」はじゅうぶん、「一人十分」は時間 ----
class JippunAfterCounterTest(unittest.TestCase):
    NOT_NUMBER = (
        ("景気は一時十分に回復したが、また落ち込んだ。", "景気は一時しっかり回復したが、また落ち込んだ。"),
        ("在庫は一時十分な量があったが、今は足りない。", "在庫は一時は足りていたが、今は足りない。"),
        ("症状は一時十分におさまった。", "症状は一時、だいぶおさまった。"),
        ("七時間十分眠れば、疲れは取れる。", "七時間しっかり眠れば、疲れは取れる。"),
        ("睡眠は八時間十分とるようにしている。", "睡眠は八時間しっかりとるようにしている。"),
    )

    def test_jippun_that_means_enough(self):
        for before, after in self.NOT_NUMBER:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)
                self.assertEqual(unsupported_numbers(before, [after]), [])

    def test_minutes_after_a_counter(self):
        """漢数字に続いた「人」「回」などのあとの「十分」（一人十分）は時間。「十一時十分」も今までどおり時間。"""
        self.assertEqual(numbers_in("発表は一人十分とする。"), ["一人", "十分"])
        self.assertEqual(numbers_in("十一時十分に始める。"), ["十一時", "十分"])
        self.assertEqual(number_risks("発表は一人十分とする。", "発表は1人10分とする。"), [])
        self.assertEqual(fail_on_count("発表は一人十分とする。", "発表は1人10分とする。"), 0)
        self.assertEqual(number_risks("発表は一人十分とする。", "発表は一人五分とする。"), [("replaced", ["十分"], ["五分"])])

    def test_known_limits(self):
        """残る形: 「一回十分です」は「十分です（じゅうぶんです）」と分けられないので、数にしない。"""
        self.assertEqual(number_risks("面談は一回十分です。", "面談は1回10分です。"), [("added", [], ["10分"])])
        self.assertEqual(number_risks("面談は一回十分です。", "面談は一回です。"), [])


# ---- 「一つの」「一つずつ」の相手の文の語: 打ち消し、同じ・順に、どの語にかかるか、まとめた文 ----
class OnePartnerScopeTest(unittest.TestCase):
    NOT_FOUND = (
        # 「〜ごとの上限」（上限の値を言い、「一つ」を複数にしていない）
        ("一つの部屋に入れるのは十人までとする。", "部屋ごとの上限は十人とする。"),
        ("一つのアカウントで登録できる端末は三台までとする。", "アカウントごとに登録できる端末の上限は三台とする。"),
        ("一つの注文に入れられる商品は二十個までです。", "注文あたりの商品数の上限は二十個です。"),
        ("一つの会議室を使えるのは八名までです。", "会議室ごとの利用人数の上限は八名です。"),
        ("一つの袋に詰められるのは十個までです！", "袋ごとの上限は十個です！"),
        # 「すべて同じ」
        ("申請書は一つの窓口で受け付けます。", "申請書はすべて同じ窓口で受け付けます。"),
        ("届出は一つの様式で提出する。", "届出はすべて同じ様式で提出する。"),
        ("ログは一つの場所に集めます。", "ログはすべて同じ場所に集めます。"),
        # 打ち消した数を言う語
        ("設定は一つのファイルにまとめます。", "設定は複数のファイルに分けず、まとめて書きます。"),
        ("テストを一つずつ流すようにしました。", "テストは並列にせず、順に流すようにしました。"),
        ("復旧の手順を一つずつ実行した。", "復旧の手順は同時に進めず、順に実行した。"),
        ("質問は一つずつ受け付けます。", "質問はまとめて受け付けず、順に受け付けます。"),
        ("テストは並列で流さないようにしました。", "テストは一つずつ流すようにしました。"),
        ("設定ファイルは複数に分けない。", "設定は一つのファイルにまとめる。"),
        # 数を言う語が別の述語にかかる
        ("議題を一つずつ確認し、結果を一覧で共有する。", "議題を順に確認し、結果はまとめて共有する。"),
        ("ログを一つずつ確認します。あわせて、設定も見直します。", "ログを順に確認し、同時に設定も見直します。"),
        ("古い手紙を一つずつ読みながら、思い出したことを書き留めた。", "古い手紙を順に読み、思い出したことを同時に書き留めた。"),
        ("ログを一つずつ確認しながら、設定も見直した。", "ログを順に確認しながら、並行して設定も見直した。"),
        ("議題は一つずつ扱い、まとめて決めることはしない。", "議題は順に扱い、まとめて決めることはしない。"),
        # 同じ意味の語の言い換え（複数 ↔ いくつも）
        ("一つのプルリクエストに、関係のない変更が複数混ざっていました。",
         "プルリクエストに、関係のない変更がいくつも混ざっていました。"),
        ("一つの関数に、処理がいくつも詰め込まれていた。", "関数に、複数の処理が詰め込まれていた。"),
        # 語の中の「全部」（全部署、全部屋）
        ("通知は一つの窓口から、各部署に送ります。", "通知は同じ窓口から、全部署に送ります。"),
        ("資料は一つの封筒に入れ、各部屋に届けます。", "資料は同じ封筒に入れ、全部屋に届けます。"),
        # 文を分けた推敲（各 → すべて は、ファイルや画面の数の主張ではない）
        ("手順は一つの表にまとめ、各項目に担当者を書きます。", "手順は表にまとめます。すべての項目に担当者を書きます。"),
        ("ログは一つのファイルに出し、各行に時刻を付けます。", "ログはファイルに出します。すべての行に時刻を付けます。"),
        ("設定は一つの画面で変えられ、各項目に説明があります。", "設定は画面で変えられます。すべての項目に説明を付けています。"),
        ("質問は一つの窓口で受け、全員に返します。", "質問は窓口で受けます。答えはすべての人に返します。"),
        ("項目を一つずつ確認し、担当者は二人で同じ時間に作業します。", "項目を順に確認します。担当者は二人で同時に作業します。"),
        ("手順は一つの表にまとめます。各項目に担当者を書きます。", "手順は表にまとめます。表のすべての項目に、担当する人の名前を書き入れます。"),
    )
    FOUND = (
        # 「一つずつ」→ 複数、いくつでも
        ("ファイルは一つずつ選びます。", "ファイルは複数選びます。"),
        ("申請は一つずつ受け付けます。", "申請は複数件を受け付けます。"),
        ("画面は一つずつ開きます。", "画面はいくつでも開けます。"),
        # 「一つずつ」→ 一斉に、一気に、いっぺんに。「一つの」→ 別々の
        ("お知らせのメールは一つずつ送ります。", "お知らせのメールは一斉に送ります。"),
        ("申請書は一つずつ処理します。", "申請書は一気に処理します。"),
        ("彼は窓を一つずつ閉めていった。", "彼は窓をいっぺんに閉めた。"),
        ("設定は一つのファイルに書きます。", "設定は別々のファイルに書きます。"),
        # 打ち消していない数を言う語（前から拾う形）。許す言い方（問題ありません、差し支えない）は打ち消しではない
        ("テストを一つずつ流すようにしました。", "テストを並列で流すようにしました。"),
        ("ジョブは一つずつ流す。", "ジョブはまとめて流しても問題ありません。"),
        ("申請書は一つずつ提出する。", "申請書はまとめて提出しても差し支えない。"),
        ("設定は一つのファイルにまとめます。", "設定は複数のファイルに分けます。"),
        ("ジョブは一つずつ実行する。", "ジョブはまとめて実行する。"),
        ("設定は一つのファイルにまとめる。", "設定は全部の画面ごとに別のファイルに書く。"),
        # 2つの文をまとめた推敲で、数を言う語が「一つの」の名詞か「一つずつ」の動詞に移った
        ("設定は一つのファイルに書く。複数の担当で見直す。", "設定は複数のファイルに分けて書き、担当が見直す。"),
        ("ジョブは一つずつ実行する。結果はまとめて送る。", "ジョブはまとめて実行し、結果を送る。"),
        ("申請は一つの窓口で受ける。すべての申請に番号を付ける。", "申請はすべての窓口で受け、番号を付ける。"),
    )

    def test_correct_rewrites_have_no_number_candidate(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_negated_partner_word_keeps_quiet_with_other_candidates(self):
        """打ち消した「まとめて」は数を言う語に数えない（否定の候補は前から出る）。"""
        self.assertEqual(number_risks("ジョブはまとめて実行しない。", "ジョブは一つずつ実行する。"), [])

    def test_changed_quantity_is_found(self):
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [("lost", ["一つ"], [])])
                self.assertGreater(fail_on_count(before, after), 0)


# ---- 否定対比の逆転: 「Aは減ら」の範囲、形容詞と名詞、示す語 ----
class ReduceAndShownMoreTest(unittest.TestCase):
    FOUND = (
        # 「Aは減らす」のあとの同じ節に重みの語がある（A を減らすことを最優先にした）
        ("コストではなく品質を重視する。", "コストは減らすことを最優先にする。", ["コスト"]),
        ("会議ではなく文書で決めることを優先する。", "会議は減らすことを最優先の目標にする。", ["会議"]),
        ("人数ではなく成果で評価する。", "人数は減らすことが目的だ。", ["人数"]),
        # 「は減らす」が A ではなく、A の節の後ろの別の語に付いている
        ("会議ではなく文書で決めることを優先する。", "会議で決めることを優先して文書は減らす。", ["会議"]),
        ("コストではなく品質を重視する。", "コストを最優先にして品質の確認は減らす。", ["コスト"]),
        ("自動化ではなく手作業で確かめる。", "自動化を最優先にして手間は減らす。", ["自動化"]),
        ("## 手作業ではなく自動化で回す", "## 手作業を最優先にして自動化は減らす", ["手作業"]),
        ("会議ではなく文書で決めることを優先する。", "会議で決めることを優先し、文書は減らす。", ["会議"]),
        # 形容詞と名詞（高い品質）の名詞だけを肯定した
        ("高い品質ではなく、安い値段を優先した。", "品質を最優先にした。", ["品質"]),
        ("長い説明ではなく、短い例を重視する。", "説明を重視する。", ["説明"]),
        ("安い値段ではなく、確かな品質で選ばれています！", "何より値段で選ばれています！", ["値段"]),
        ("彼が求めたのは、長い手紙ではなく短い返事だった。", "彼が何より求めたのは手紙だった。", ["手紙"]),
    )
    NOT_FOUND = (
        ("打ち合わせではなく文書で決めることを優先する。", "文書で決めることを優先し、打ち合わせは減らす。"),
        ("会議ではなく文書で決めることを優先する。", "会議は減らして、文書で決めることを優先する。"),
        ("打ち合わせではなく文書で決めることを優先する。", "文書で決めることを優先し、打ち合わせは減らしていく。"),
    )

    def test_reversal_is_found(self):
        for before, after, words in self.FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), words)

    def test_a_is_reduced_is_not_a_reversal(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), [])

    def test_shown_word(self):
        """送り仮名が「も」「が」で始まる語（見積もり、出来上がり）も送り仮名まで示す。助詞の「など」は足さない。"""
        self.assertEqual(reversal_words("見積もりではなく実測の値を優先します。", "見積もりを優先します。"), ["見積もり"])
        self.assertEqual(reversal_words("出来上がりではなく途中の過程を重視します。", "出来上がりを重視します。"), ["出来上がり"])
        self.assertEqual(reversal_words("会議などではなく、文書で決めることを優先する。", "会議で決めることを最優先にする。"),
                         ["会議"])



# ==== 3回目の直しのあとの3回目の反証で見つけた例 ====

# ---- 「一つの」「一つずつ」の相手の文の打ち消し: 数を言う語がかかる述語までを見る ----
class QuantityNegationScopeTest(unittest.TestCase):
    # 数の主張が変わった（打ち消しは別の述語のもの、打ち消しでない義務や条件の言い方、語で打ち消した「上限」、平仮名の動詞）
    FOUND = (
        # 別の述語の打ち消し（〜ので待ちません、〜て待たせない、〜ても変わらない）
        ("一つの窓口で受け付けます。", "複数の窓口で受け付けるので待ちません。"),
        ("処理は一つずつ行います。", "処理はまとめて行うので時間はかかりません。"),
        ("申請は一つずつ受け付けます。", "申請は一度に受け付けるので順番を待つ必要はない。"),
        ("処理は一つずつ行います。", "処理は並列で行うので遅れない。"),
        ("一つの窓口で受け付けます。", "複数の窓口で受け付けて待たせない。"),
        ("ジョブは一つずつ流す。", "ジョブはまとめて流すので時間がかからない。"),
        ("結果は一つのファイルに書く。", "結果は複数のファイルに書くので迷わない。"),
        ("申請は一つずつ処理する。", "申請は同時に処理するので待たせない。"),
        ("データは一つの表にまとめる。", "データは複数の表に分けて混ざらないようにする。"),
        ("注文は一つずつ受け付ける。", "注文はまとめて受け付けるので漏れがない。"),
        ("テストは一つずつ流す。", "テストは並列で流しても結果は変わらない。"),
        # 打ち消しでない義務や条件の言い方（なければならない、ないといけない、ざるを得ない、しかない、ほかない、ないと〜）
        ("一つの画面で確認します。", "すべての画面で確認しなければならない。"),
        ("一つの画面で確認します。", "すべての画面で確認しないと公開できない。"),
        ("作業は一つずつ進めます。", "作業は同時に進めなければいけない。"),
        ("設定は一つのファイルに書きます。", "設定は複数のファイルに分けなければなりません。"),
        ("設定は一つのファイルに書きます。", "設定は複数のファイルに分けないといけません。"),
        ("設定は一つのファイルに書きます。", "設定は複数のファイルに分けなくてはならない。"),
        ("処理は一つずつ行います。", "処理はまとめて行わざるを得ない。"),
        ("処理は一つずつ行います。", "処理は並列で行わなければならない。"),
        ("一つの窓口で受け付けます。", "すべての窓口で受け付けなくてはいけません。"),
        ("処理は一つずつ行います。", "処理はまとめて行うしかない。"),
        ("一つの窓口で受け付けます。", "複数の窓口で受け付けるしかありません。"),
        ("処理は一つずつ行う。", "処理は並列で行うほかない。"),
        ("部品は一つの箱に入れる。", "部品は別々の箱に入れなければいけない。"),
        ("テストは一つずつ流す。", "テストは並列で流さないと間に合わない。"),
        ("ジョブは一つずつ実行する。", "ジョブは同時に実行することになるかもしれない。"),
        ("部屋は一つの鍵で開ける。", "部屋は複数の鍵がないと開かない。"),
        # 語で打ち消した「上限」（上限をなくす、撤廃する、外す、廃止する、設けない）
        ("予約は一つの枠だけ取れる。", "予約の枠の上限をなくす。"),
        ("申し込みは一つの講座に限る。", "申し込める講座の上限を撤廃する。"),
        ("登録できる端末は一つの機種に限る。", "登録できる端末の上限を外す。"),
        ("予約は一つの枠だけ取れる。", "予約の枠に上限は設けない。"),
        ("申し込みは一つの講座に限る。", "申し込める講座の上限を廃止する。"),
        # 平仮名の動詞（おこなう、おはなしする）の「な」と、あとの別の動詞の打ち消し（読点なし）
        ("テストは一つずつ流すようにしました。", "テストはまとめておこないます。"),
        ("研修は一つの会場で行います。", "研修は複数の会場でおこないます。"),
        ("復旧作業は一つずつ進めた。", "復旧作業は並列でおこないました。"),
        ("ご説明は一つずつ差し上げます。", "ご説明はまとめておはなしします。"),
        ("提案は一つずつ審議する。", "提案は一括で審議をおこない、結論を出す。"),
        ("申請の審査は一つずつ行う。", "申請の審査は一括しておこない、結果を通知する。"),
        ("リクエストは一つずつ処理する。", "リクエストは並列で処理をおこない、結果を返す。"),
        ("注文は一つずつ確かめます。", "注文はまとめて確かめて漏れがないかを見ます。"),
        ("ログは一つずつ送ります。", "ログはまとめて送って取りこぼしがないようにします。"),
        ("画面は一つのタブで開きます。", "画面は複数のタブで開いて比べられないか試します。"),
        ("申請は一つずつ受け付けます。", "申請はまとめて受け付けて不備がないかを確かめます。"),
        # 「順に」を「ではなく」「ことなく」で打ち消し、数を言う語で言い直した
        ("ファイルは一つずつ確認します。", "ファイルは順に確認するのではなく、まとめて確認します。"),
        ("ジョブは一つずつ実行します。", "ジョブは順に実行することなく、並列で実行します。"),
    )
    # 正しい推敲（数を言う語を「ではなく」「でなく」「ことなく」で打ち消した。「〜ごとの上限…を超えない」。打ち消しの節を動かした）
    NOT_FOUND = (
        ("ビルドは一つずつ実行します。", "ビルドは並列ではなく、順番どおりに実行します。"),
        ("マイグレーションを一つずつ適用するようにしました。",
         "マイグレーションは同時にではなく、順番どおりに適用するようにしました。"),
        ("影響のあるサーバーを一つずつ再起動した。", "影響のあるサーバーは一斉にではなく、順番どおりに再起動した。"),
        ("設定値は一つのファイルで管理する。", "設定値は複数のファイルに分けることなく管理する。"),
        ("届出は一つの窓口で受理する。", "届出は窓口を複数設けることなく受理する。"),
        ("ご質問には一つずつお答えします。", "ご質問には、まとめてではなく順番どおりにお答えします。"),
        ("備品の申請は一つずつ処理します。", "備品の申請は一括ではなく、届いた順に処理します。"),
        ("議題は一つずつ検討する。", "議題は並行してではなく、順番どおりに検討する。"),
        ("引き出しの手紙を一つずつ読んだ。", "引き出しの手紙を、まとめてではなく順番どおりに読んだ。"),
        ("彼は窓を一つずつ閉めていった。", "彼は窓を一度にではなく、順番どおりに閉めていった。"),
        ("料理は一つずつ丁寧に仕上げます。", "料理はまとめてではなく、順番どおりに丁寧に仕上げます。"),
        ("テストは一つずつ流します。", "テストは並列でなくて、順番どおりに流します。"),
        ("一つの質問に答えるだけです。", "いくつかの質問ではなく、質問に答えるだけです。"),
        ("一つの部屋に十人まで入れます。", "部屋ごとの上限の十人を超えないようにします。"),
        ("一つの部屋に十人まで入れます。", "部屋ごとに上限は十人で、超えることはできません。"),
        ("一つのアカウントで使えるのは三台までです。", "アカウントごとに上限の三台を超えて使えません。"),
        ("ジョブは一つずつ流し、結果はまとめて送るので待たない。", "ジョブを流し、結果はまとめて送る。待つ必要はない。"),
        ("ファイルは一つずつ開き、変更は同時に保存するしかない。", "ファイルを開き、変更は同時に保存する。"),
    )
    # 元の側の数を言う語が義務の言い方の節にある正しい推敲（文の種類の候補は出るが、数値の候補は出さない）
    NO_NUMBER = (
        ("書類は一つずつ確認し、結果はまとめて送らなければならない。", "書類を確認し、結果はまとめて送る。"),
        ("表は一つの画面に出し、すべての項目を載せなければならない。", "表は画面に出し、すべての項目を載せる。"),
        ("申請は一つの窓口で受け、すべての申請に番号を付けなければいけない。", "申請は窓口で受け、すべての申請に番号を付ける。"),
        ("注文は一つの画面で受け、複数の商品をまとめて買えないといけない。",
         "注文は画面で受け、複数の商品をまとめて買えるようにする。"),
        ("問い合わせは一つの窓口で受け、すべての質問に答えなければならない。", "問い合わせは窓口で受け、すべての質問に答える。"),
    )

    def test_changed_quantity_is_found(self):
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [("lost", ["一つ"], [])])
                self.assertGreater(fail_on_count(before, after), 0)

    def test_correct_rewrites_have_no_number_candidate(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_obligation_on_the_other_side_is_not_a_number_change(self):
        for before, after in self.NO_NUMBER:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_known_limits(self):
        """残る形: 読点のない連用形で続けた別の述語の打ち消し（並列で行い遅延を出さない）は、数を言う語の打ち消しと分けない。"""
        self.assertEqual(number_risks("処理は一つずつ行います。", "処理を並列で行い遅延を出さない。"), [])
        self.assertEqual(number_risks("処理は一つずつ行います。", "処理を並列で行い、遅延を出さない。"), [("lost", ["一つ"], [])])


# ---- 「一つの」「一つずつ」の相手の文の語: 「一つの」の名詞、「一つずつ」の動詞のある節だけを見る ----
class QuantityClauseScopeTest(unittest.TestCase):
    # 正しい推敲（数を言う語は別の述語や別の名詞にかかる。語の頭の「各」は「それぞれ」「〜ごと」の言い換え）
    NOT_FOUND = (
        ("議題を一つずつ確認し、結果を一覧で共有する。", "議題を確認し、結果はまとめて共有する。"),
        ("ログを一つずつ確認します。あわせて、設定も見直します。", "ログを確認し、同時に設定も見直します。"),
        ("古い手紙を一つずつ読みながら、思い出したことを書き留めた。", "古い手紙を読み、思い出したことを同時に書き留めた。"),
        ("ログを一つずつ確認しながら、設定も見直した。", "ログを確認しながら、並行して設定も見直した。"),
        ("ログを一つずつ確認し、気づいた点は一覧にします。", "ログを確認し、気づいた点はまとめて一覧にします。"),
        ("申請を一つずつ審査し、結果は月末に知らせます。", "申請を審査し、結果は月末にまとめて知らせます。"),
        ("申請を一つずつ審査し、結果を通知します。", "申請を審査し、結果を一斉に通知します。"),
        ("一つの窓口で受け付け、結果は担当者に返します。", "窓口で受け付け、結果は複数の担当者に返します。"),
        ("手順は一つの資料にまとめ、どの部署にも配ります。", "手順を資料にまとめ、すべての部署に配ります。"),
        ("手順は一つの資料にまとめ、全員に配ります。", "手順を資料にまとめ、すべての担当者に配ります。"),
        ("一つの画面で入力し、各欄を確かめます。", "画面で入力し、すべての欄を確かめます。"),
        ("問い合わせは一つの窓口で受け、内容は全部記録します。", "問い合わせは窓口で受け、内容はすべて記録します。"),
        ("ログを一つずつ確認します。あわせて、設定も見直します。", "ログをくまなく確認し、同時に設定も見直します。"),
        ("議題を一つずつ確認し、結果を一覧で共有する。", "議題を漏れなく確認し、結果はまとめて共有する。"),
        ("古い手紙を一つずつ読みながら、思い出したことを書き留めた。", "古い手紙を丁寧に読み、思い出したことを同時に書き留めた。"),
        # 年齢の「いくつ」
        ("一つの趣味を、何歳になっても続けたい。", "趣味を、いくつになっても続けたい。"),
        # 語の頭の「各」
        ("一つの表に項目ごとの担当を書きます。", "表に各項目の担当を書きます。"),
        ("手順は一つの資料にまとめ、部署ごとに配ります。", "手順を資料にまとめ、各部署に配ります。"),
        ("ログは一つのファイルに書き、行ごとに時刻を付ける。", "ログはファイルに書き、各行に時刻を付ける。"),
        ("問い合わせは一つの窓口で受け、担当ごとに回す。", "問い合わせは窓口で受け、各担当に回す。"),
        ("設定は一つの画面で変えられ、項目ごとに説明がある。", "設定は画面で変えられ、各項目に説明がある。"),
        ("一つの表に、チームごとの予定をまとめる。", "表に、各チームの予定をまとめる。"),
        ("質問は一つのフォームで受け、部署ごとに答える。", "質問はフォームで受け、各部署が答える。"),
        ("一つの表に、それぞれの担当の予定を書く。", "表に、各担当の予定を書く。"),
        ("設定は一つの画面で、いろいろな項目を変えられる。", "設定は画面で、各種の項目を変えられる。"),
        ("作業は一つの部屋で、めいめいが進める。", "作業は部屋で、各自が進める。"),
        ("申請は一つの窓口で受け付けます。担当の皆様へ。", "各位　申請は窓口で受け付けます。"),
        ("商品は一つの倉庫から、地方ごとに発送する。", "商品は倉庫から、各地に発送する。"),
        ("皆様、資料は一つのフォルダにまとめました。", "関係者各位、資料はフォルダにまとめました。"),
        ("一つの会場に、全国の名産を集めました！", "会場に、全国各地の名産を集めました！"),
        ("手順は一つの表にまとめ、どの手順にも担当を書く。", "手順は表にまとめ、各手順に担当を書く。"),
        ("変更は一つのプルリクエストにまとめ、どのコミットにも説明を付けた。", "変更はプルリクエストにまとめ、各コミットに説明を付けた。"),
        ("議題は一つの資料にまとめ、それぞれの担当が説明する。", "議題は資料にまとめ、各担当が説明する。"),
        ("原因は一つのログにまとめ、時刻ごとに並べた。", "原因はログにまとめ、各時刻の順に並べた。"),
        ("結果は一つの表にまとめ、行ごとに日付を入れる。", "結果は表にまとめ、各行に日付を入れる。"),
        ("申請書の様式は一つの形式にそろえ、どの課でも受け付ける。", "申請書の様式は形式をそろえ、各課で受け付ける。"),
        ("一つの部屋に、家族それぞれの思い出が詰まっている。", "部屋には、家族各人の思い出が詰まっている。"),
        ("問い合わせは一つの窓口で受け、それぞれの担当に回す。", "問い合わせは窓口で受け、各担当に回す。"),
    )
    # 数の主張が変わった（「一つの」の名詞のすぐ前の「各」「〜ごとの」。同じ文の別の節に「同じ」「順に」がある）
    FOUND = (
        ("申請は一つの窓口で受け付けます。", "申請は各窓口で受け付けます。"),
        ("設定は一つのファイルに書く。", "設定は機能ごとのファイルに書く。"),
        ("受付は一つの窓口で行う。", "受付は複数の窓口で行い、返却は同じ窓口で行う。"),
        ("申請は一つずつ確認する。", "申請はまとめて確認し、不備があれば順に確認する。"),
        ("ログは一つのファイルに書く。", "ログは複数のファイルに書き、エラーも同じファイルに書く。"),
        ("テストは一つずつ流す。", "テストは並列で流し、失敗したものは順に流す。"),
        ("設定は一つの画面で変える。", "設定はすべての画面で変えられ、表示も同じ画面で確かめる。"),
    )

    def test_correct_rewrites_have_no_number_candidate(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_changed_quantity_is_found(self):
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [("lost", ["一つ"], [])])
                self.assertGreater(fail_on_count(before, after), 0)

    def test_other_noun_is_not_a_change(self):
        """「一つの」の名詞のすぐ前の「別の」（別のファイル）は、数の主張を変えていない。"""
        self.assertEqual(number_risks("ログは一つのファイルに書きます。", "ログは別のファイルに書きます。"), [])


# ---- 否定対比の逆転: 読点のない「Aは減らして B を優先する」と「Aの数は減らし」----
class ReduceWithoutCommaTest(unittest.TestCase):
    NOT_FOUND = (
        ("打ち合わせではなく文書で決めることを優先する。", "打ち合わせは減らして文書で決めることを優先する。"),
        ("打ち合わせではなく文書で決めることを優先する。", "打ち合わせは減らし文書で決めることを優先する。"),
        ("会議ではなく文書で決めることを優先する。", "会議は減らして文書で決めることを最優先にする。"),
        ("残業ではなく効率を重視する。", "残業は減らして効率を重視する。"),
        ("紙の書類ではなく、電子の申請を優先する。", "紙の書類は減らして電子の申請を最優先にする。"),
        ("打ち合わせではなく、チャットでの相談を重視する。", "打ち合わせは減らしてチャットでの相談を重視する。"),
        ("紙ではなく画面で確認することを重視する。", "紙は減らして画面で確認することを重視する。"),
        ("残業ではなく時間内に終えることを大事にする。", "残業は減らして時間内に終えることを大事にする。"),
        ("電話ではなくメールで連絡する。", "電話は減らしてメールでの連絡を最優先にする。"),
        ("## 手作業ではなく自動化で回す", "## 手作業は減らして自動化を最優先にする"),
        ("会議ではなく文書で決める。", "会議は減らしつつ文書で決めることを最優先にする。"),
        ("会議ではなく文書で決めることを優先する。", "会議の数は減らし、文書で決めることを優先する。"),
        ("会議ではなく文書で決めることを優先する。", "会議の回数は減らして、文書で決めることを優先する。"),
        ("会議ではなく文書で決めることを優先する。", "会議の時間は減らし、文書で決めることを優先する。"),
        ("電話ではなくメールで連絡することを優先する。", "電話の件数は減らし、メールで連絡することを優先する。"),
    )

    def test_a_is_reduced_is_not_a_reversal(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), [])

    def test_reducing_a_as_the_goal_is_still_a_reversal(self):
        """「Aは減らすことを最優先にする」「Aは減らすのが目的だ」は、A を減らすことを主張している（逆転の候補のまま）。"""
        self.assertEqual(reversal_words("コストではなく品質を重視する。", "コストは減らすことを最優先にする。"), ["コスト"])
        self.assertEqual(reversal_words("人数ではなく成果で評価する。", "人数は減らすのが目的だ。"), ["人数"])


# ---- 否定対比の逆転: 送り仮名を挟んで長くなった語（支払い期限、得た知識）の名詞 ----
class OkuriganaNounContrastTest(unittest.TestCase):
    FOUND = (
        ("支払い期限ではなく、請求額の正しさを優先して確認する。", "何より期限を優先して確認する。", ["期限"]),
        ("得た知識ではなく、出会った人を大切にしたい。", "何より知識を大切にしたい。", ["知識"]),
        ("見習い期間ではなく、本採用後の評価を重視します。", "期間を最も重視します。", ["期間"]),
        ("話し合い期間ではなく、決定の速さを優先する。", "話合い期間を最優先にする。", ["期間"]),
        ("立ち会い検査ではなく、書類の確認を優先する。", "何より検査を優先する。", ["検査"]),
        ("支払い方法ではなく、金額を重視する。", "支払方法を最も重視する。", ["方法"]),
    )

    def test_noun_after_okurigana_is_found(self):
        for before, after, words in self.FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), words)

    def test_correct_rewrite_is_not_found(self):
        self.assertEqual(reversal_words("支払い期限ではなく、請求額の正しさを優先する。", "請求額の正しさを最優先にする。"), [])


# ---- 「十分」: 「一日十分」「毎日十分」「一人十分で」、時刻に続く「一時十分まで」----
class JippunMoreTest(unittest.TestCase):
    NOTATION = (
        ("一日十分だけ、日記を書く。", "1日10分だけ、日記を書く。"),
        ("一日十分のストレッチで体が変わります！", "1日10分のストレッチで体が変わります！"),
        ("朝礼は毎日十分で終えます。", "朝礼は毎日10分で終えます。"),
        ("一日十分の練習を続ける。", "1日10分の練習を続ける。"),
        ("発表は一人十分で行う。", "発表は1人10分で行う。"),
        ("面談は一人十分で終える。", "面談は1人10分で終える。"),
        ("問い合わせには一件十分で対応する。", "問い合わせには1件10分で対応する。"),
        ("練習は一回十分で切り上げる。", "練習は1回10分で切り上げる。"),
    )
    CHANGED = (
        ("一日十分だけ、日記を書く。", "一日に少しだけ、日記を書く。", [("lost", ["十分"], [])]),
        ("発表は一人十分で行う。", "発表は一人ずつ行う。", [("lost", ["十分"], [])]),
        ("受付は一時十分までです。", "受付は一時までです。", [("lost", ["十分"], [])]),
        ("会議は午後一時十分に始める。", "会議は午後一時に始める。", [("lost", ["十分"], [])]),
    )

    def test_kanji_to_arabic_is_notation(self):
        for before, after in self.NOTATION:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_changed_minutes_are_found(self):
        for before, after, expected in self.CHANGED:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)
                self.assertGreater(fail_on_count(before, after), 0)

    def test_jippun_that_means_enough(self):
        """「一日に十分な」「毎日十分に」「毎日十分です」「毎日十分できる」の「十分」はじゅうぶん。"""
        self.assertEqual(numbers_in("一日に十分な睡眠をとる。"), ["一日"])
        self.assertEqual(numbers_in("毎日十分に休む。"), [])
        self.assertEqual(numbers_in("睡眠は毎日十分です。"), [])
        self.assertEqual(numbers_in("毎日十分できるようにする。"), [])
        self.assertEqual(numbers_in("一日十分な休みをとる。"), ["一日"])

    def test_known_limits(self):
        """残る形: 前に漢数字も「午前」「午後」もない「一時十分に」は「一時的に十分」と分けられないので、数にしない。"""
        self.assertEqual(number_risks("会議は一時十分に始める。", "会議は一時に始める。"), [])


# ---- 時刻: 「午前一時」「午後一時」、「朝九時」「夜十時」「夕方五時」「毎朝八時」----
class TimeOfDayTest(unittest.TestCase):
    NOTATION = (
        ("障害は午前一時十分に発生した。", "障害は午前1時10分に発生した。"),
        ("次回の会議は午後一時からです。", "次回の会議は午後1時からです。"),
        ("明日の午後一時に伺います。", "明日の午後1時に伺います。"),
        ("深夜一時に作業を始めた。", "深夜1時に作業を始めた。"),
        ("朝九時に集まってください。", "朝9時に集まってください。"),
        ("夜十時には眠るようにしている。", "夜10時には眠るようにしている。"),
        ("夕方五時の鐘が鳴った。", "夕方5時の鐘が鳴った。"),
        ("窓口は毎朝八時三十分に開く。", "窓口は毎朝8時30分に開く。"),
    )
    CHANGED = (
        ("障害は午前一時に発生した。", "障害は深夜に発生した。", [("lost", ["一時"], [])]),
        ("明日の午後一時に伺います。", "明日の午後に伺います。", [("lost", ["一時"], [])]),
        ("次回の会議は午後一時からです。", "次回の会議は午後三時からです。", [("replaced", ["一時"], ["三時"])]),
        ("朝九時に集まってください。", "朝十時に集まってください。", [("replaced", ["九時"], ["十時"])]),
        ("夜十時には眠るようにしている。", "夜十一時には眠るようにしている。", [("replaced", ["十時"], ["十一時"])]),
    )

    def test_kanji_to_arabic_is_notation(self):
        for before, after in self.NOTATION:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(fail_on_count(before, after), 0)

    def test_changed_time_is_found(self):
        for before, after, expected in self.CHANGED:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)
                self.assertGreater(fail_on_count(before, after), 0)

    def test_words_that_are_not_times(self):
        """「朝一番」「一時的」と、「夜一人で」の人数（1字の朝・夜のあとは時刻だけを取る）は、今までどおり数にしない。"""
        self.assertEqual(numbers_in("朝一番に連絡します。"), [])
        self.assertEqual(numbers_in("その夜一時的に停電した。"), [])
        self.assertEqual(numbers_in("夜一人で歩くのは危ない。"), [])
        self.assertEqual(numbers_in("午前一時十分に起きた。"), ["一時", "十分"])

# ---- 公開の前の掃除: 手元の開発のフォルダの名前 ----
# 試験のファイルそのものに当たらないよう、文字列はつないで作る
PRIVATE_NAMES = tuple(head + tail for head, tail in (("v200", "-development"), ("v200", "-handoff"),
                                                     ("step-", "c-"), ("human", "-evals"), ("codex", "-home")))
# 作り直しを待っている fixture（出どころの欄に手元の道具のパスが残っているもの）。g7_unchanged_outputs.json は作り直して
# 出どころの欄と updates から手元の名前を消したので、今は除くものはない
PENDING_FIXTURES = ()
# fixture の説明の欄（description、generated_by、source_commit、updates）には、手元の記録と道具の名前も書かない。
# 出どころは「lint は G7 の前の出力、diff と check は直しのあとの出力」のように書き、記録のファイル名や道具のパスで指さない
FIXTURE_NOTE_FILES = ("tests/fixtures/g7_unchanged_outputs.json",)
FIXTURE_NOTE_KEYS = ("description", "generated_by", "source_commit", "updates")
PRIVATE_NOTE_WORDS = PRIVATE_NAMES + tuple(head + tail for head, tail in (
    ("v200", "-"), ("step", "2"), ("step-", "c"), ("-work", "/"), ("/Us", "ers/"), ("DESIGN", "-"), ("GOA", "LS"),
    ("review1", "-"), ("review2", "-"), ("review-", "spec"), ("review-", "fp"), ("review-", "regress"),
    ("questions", ".md"), ("fixture-", "compare"), ("fix-", "round"), ("finalize", ".md"), ("measure", ".md"),
    ("explain-", "changes"), ("before-", "fix"), ("make_unchanged", "_fixture"), ("remake", "_fixture")))
# git がないときに見るもの
PUBLISHED = ("scripts", "skills", "tests", "references", "README.md", "CHANGELOG.md")


def published_files():
    """リポジトリで追跡しているファイルと、追跡の対象になる新しいファイル（.gitignore と info/exclude で外したものを除く）。
    git がなければ PUBLISHED の下を見る。"""
    try:
        process = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError):
        process = None
    if process is not None and process.returncode == 0 and process.stdout:
        names = sorted(set(name for name in process.stdout.decode("utf-8").split("\0") if name))
        return [name for name in names if (ROOT / name).is_file()]
    out = []
    for top in PUBLISHED:
        path = ROOT / top
        if path.is_file():
            out.append(top)
        elif path.is_dir():
            out.extend(str(found.relative_to(ROOT)).replace("\\", "/") for found in sorted(path.rglob("*"))
                       if found.is_file() and "__pycache__" not in found.parts)
    return out


class PrivatePathTest(unittest.TestCase):
    def test_published_files_have_no_private_folder_names(self):
        found = []
        for name in published_files():
            if name in PENDING_FIXTURES:
                continue
            data = (ROOT / name).read_bytes()
            for private in PRIVATE_NAMES:
                if private.encode("utf-8") in data:
                    found.append("{}: {}".format(name, private))
        self.assertEqual(found, [])

    def test_fixture_notes_have_no_private_record_names(self):
        """作り直した fixture の説明の欄に、手元の記録（反証や測りの記録のファイル名）と道具のパスを書かない。"""
        found = []
        for name in FIXTURE_NOTE_FILES:
            data = json.loads((ROOT / name).read_text(encoding="utf-8"))
            for key in FIXTURE_NOTE_KEYS:
                self.assertIn(key, data, name)
                text = json.dumps(data[key], ensure_ascii=False)
                for word in PRIVATE_NOTE_WORDS:
                    if word in text:
                        found.append("{} {}: {}".format(name, key, word))
        self.assertEqual(found, [])

    def test_the_check_covers_the_published_folders(self):
        names = published_files()
        for top in ("scripts/", "skills/yomiyasu/scripts/", "tests/", "references/"):
            with self.subTest(top=top):
                self.assertTrue(any(name.startswith(top) for name in names))
        self.assertIn("README.md", names)
        self.assertIn("CHANGELOG.md", names)


# ---- 配布物（scripts、skills、references）に、手元の記録の番号、設計の文書の名前と節の番号、作者の名前を書かない ----
# 試験の説明（tests の下）は配布物でないので見ない（反証の指摘の番号が残ってもよい）。
DISTRIBUTED_TOPS = ("scripts/", "skills/", "references/")
# 反証の指摘や記録の番号の形（英大文字1〜2字と数。「-」でつないだ形も。例: R9-9、Z9、F99、C-99、W-XY-ok99）
RECORD_ID = re.compile(r"(?<![A-Za-z0-9_+\\])(?:[A-Z]{1,2}-?\d{1,3}(?:-[A-Z]{0,3}\d+)*[a-z]?|[A-Z]-[A-Z]{2}-[a-z]{2}\d+)"
                       r"(?![A-Za-z0-9_])")
# 番号の形でも配布物で使ってよい語: Unicode の異体字セレクタ、ライセンスの名前、例の文の語（社内の略語の例）、noqa の番号
RECORD_ID_ALLOWED = re.compile(r"\bVS1[56]\b|(?i:license v3)|P1対応|noqa: [A-Z]\d+")
# 手元の設計の文書と記録の名前（文字列はつないで作る）
PRIVATE_DOC_NAMES = tuple(head + tail for head, tail in (
    ("DESIGN", "-"), ("GOA", "LS"), ("USER-", "DECISIONS"), ("START-", "HERE"), ("CHECK", "POINT"), ("STATUS", ".md")))
# 手元の文書の節や章の番号（「設計」「追加文書」「勢いの文書」「beta 文書」のあとの番号）と、種類と読者の設計の呼び方
PRIVATE_SECTION = re.compile(r"(?:設計|追加文書|勢いの文書|beta 文書) ?\d+(?:\.\d+)*|種類と読者の設計")
# 作者の名前に敬称を付けた形（開発の記録の書き方。名前そのものは書かないよう、文字の番号で作る）
OWNER_NOTE = "\u5927\u8cc0" + "\u3055\u3093"


def distributed_texts():
    """配布物のテキストのファイル（相対パス, 中身）。UTF-8 として読めないもの（画像など）は除く。"""
    out = []
    for name in published_files():
        if not name.startswith(DISTRIBUTED_TOPS):
            continue
        try:
            out.append((name, (ROOT / name).read_bytes().decode("utf-8")))
        except UnicodeDecodeError:
            continue
    return out


def record_ids(text):
    masked = RECORD_ID_ALLOWED.sub(lambda match: " " * len(match.group(0)), text)
    return [match.group(0) for match in RECORD_ID.finditer(masked)]


def found_in_lines(text, finder):
    """(行番号, 当たった語) の並び。"""
    out = []
    for number, line in enumerate(text.split("\n"), 1):
        out.extend((number, word) for word in finder(line))
    return out


class DistributedNotesTest(unittest.TestCase):
    """配布物に、反証の指摘の番号の形、手元の設計の文書の名前と節の番号、作者の名前に敬称を付けた形がない。"""

    def check(self, finder):
        found = []
        for name, text in distributed_texts():
            found.extend("{}:{}: {}".format(name, number, word) for number, word in found_in_lines(text, finder))
        self.assertEqual(found, [])

    def test_no_record_ids(self):
        self.check(record_ids)

    def test_no_private_document_names(self):
        self.check(lambda line: [word for word in PRIVATE_DOC_NAMES if word in line])

    def test_no_private_section_numbers(self):
        self.check(lambda line: [match.group(0) for match in PRIVATE_SECTION.finditer(line)])

    def test_no_owner_notes(self):
        self.check(lambda line: [OWNER_NOTE] if OWNER_NOTE in line else [])

    def test_the_patterns(self):
        """見張る形と、見張らない形（ここで作った例）。"""
        for text, expected in (
                ("（R9-9、Z9、F99）", ["R9-9", "Z9", "F99"]), ("（10.9 C-99）", ["C-99"]), ("目標の D-9", ["D-9"]),
                ("G9 で足した", ["G9"]), ("W-XY-ok99 の組", ["W-XY-ok99"]), ("R9-FP9-9", ["R9-FP9-9"]),
                ("U+FF01〜U+FF5E", []), ("VS15 と VS16", []), ("Unicode License V3", []), ("COM1、LPT1", []),
                ("# noqa: E402", []), ("UTF-8、SHA-256、ISO8601、NFKC", []), ("P1対応", []), ("\\U0001f000", [])):
            with self.subTest(text=text):
                self.assertEqual(record_ids(text), expected)
        self.assertEqual([m.group(0) for m in PRIVATE_SECTION.finditer("（設計 9.9.9、追加文書 9.9、勢いの文書9章）")],
                         ["設計 9.9.9", "追加文書 9.9", "勢いの文書9"])
        self.assertEqual(list(PRIVATE_SECTION.finditer("設計の文どおり。仕様や設計が壊れる")), [])

    def test_the_check_covers_the_distributed_folders(self):
        names = [name for name, _ in distributed_texts()]
        for name in ("scripts/yomiyasu_lint.py", "skills/yomiyasu/scripts/yomiyasu_check.py", "skills/yomiyasu/SKILL.md",
                     "references/review-points.md", "references/lists/feelings.txt"):
            with self.subTest(name=name):
                self.assertIn(name, names)
        self.assertFalse(any(name.startswith("tests/") for name in names))


if __name__ == "__main__":
    unittest.main()
