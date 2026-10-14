#!/usr/bin/env python3
"""v2.0.0（4回目の直しの続き、diff）: 4回目の直しのあとの反証で見つけた、正しい推敲への新しい誤検出と後戻りの直しと、
残す限界の試験。

文はすべてこのファイルで作った合成の文（反証で見つけた例と、それを言い換えた文）。実在の会社や商品の名前は使わない。

直したこと:

- 否定対比の逆転: 重みの語だけの句（まず、第一に、何よりも など）や主題の句（最優先は、大事なのは）のあとで、
  「Aを〜に置き換える・切り替える・移す・移行する・乗り換える」「Aを〜で置き換える」と A を別のものに替えた推敲は、A を下げた形とみなし、
  逆転の候補にしない。見るのは A のすぐあとの「を」から（「Aの〜を」と、「グローバル変数」の「変数」のように A に続く
  語の字は挟んでよい）。「Bを A に置き換える」（A に替えた）は今までどおり逆転の候補。
- 否定対比の逆転: 下げる語（その次、二番手、二番目、脇に置く、脇役、添え物、おまけ、どうでも、そのあとに回す）のすぐ前の
  は・も・が・を と A のあいだに、別の名詞へ続く切れ目（で、て、にし、し のすぐあとに漢字・片仮名・英字）があれば、
  下げたのは A でない（「品質を最優先にして速度はその次にする」は品質の逆転）。
- 数値の並び: 同じ単位の数どうしの前後が入れ替わったときだけ候補にする（「ひとりで2時間歩いた → 2時間、ひとりで歩いた」は
  候補にしない。「部屋にふたり、廊下に3人いた → 部屋に3人、廊下にふたりいた」は候補）。
- 「一つずつ」「一つの」: 「一つずつ」の動詞のすぐ前の「複数でも」と、「一つの」の名詞のすぐあとの「を・は・が・も別々」は
  数の主張が変わった形。「ずつ」「の」のあとに動詞・名詞が取れないとき（どうぞ、です、にして）は、複数・いくつ・別々 を相手の
  文のどこに出ても数える。相手が1つの文なら、動詞・名詞のある節の「複数」（一つずつ）と「別々に」（一つの）も数える。
- 平仮名の数: 「に」「で」のすぐあとの「いつつ」（あとが読点、漢字、「も」。いる + つつ）と「ひとり言」は数にしない。

このあとの直しで、数値の並び（同じ語句に付く値の入れ替えも候補にする）、置き換えの形（Aは・Aも、足した動詞、A を前に出す先と
A を使う句の除外）、下げる語の前の別の名詞の決まりを広げた（test_v200_fix_round4_second.py）。このファイルの試験は、広げたあとも
書き換えずに通る。さらにそのあとの直し（test_v200_fix_round5.py）で、重みの語だけの句のあとに原文で肯定した側の語を出した推敲
（まず、手作業を自動化する）と、「一つの」の名詞を言い換えた1つの文（ログと設定は別々に書く）の扱いが変わったので、下の限界から
その2つの形を外した（このファイルの限界の試験もそれに合わせた）。

限界として固定する形（直さない。今の出力のまま）:

- 重みの語だけの句のあとに、置き換え先を言わずに A を変える言い方（第一に、会議の数を絞る／まず、手作業を減らす／まず、
  手作業の自動化から）を置いた正しい推敲は、逆転の候補に出る（--fail-on には数えない）。
- 同じ単位の数の前後を入れ替えただけの推敲（ひとりで3人分を食べた → 3人分をひとりで食べた）は、並びの候補に出る。
- 下げる語は A のすぐあと（Aはその次）のときだけ見る。読点を挟んだ形（Aは、その次に見る）は正しい推敲でも逆転の候補に出る。
  別の名詞のあとの「は後に回す」（品質を最優先にして速度は後に回す）の逆転は拾わない。
- 「一つの」の名詞を相手の文の別の語から離した推敲（鍵は別々の場所にある金庫にしまう）は拾わない。
- 平仮名の数（ひとつ〜ここのつ、ひとり、ふたり）は、相手の文に同じ単位の値がないと比べない。足しただけ・消しただけの推敲と、
  「ふたつしか」「ひとりだけ」「ふたりまで」「ふたつずつ」を言い換えた推敲は拾わない。新規作成の照合でも、平仮名の数は資料の
  値と違っても候補にしない。「に」「で」のすぐあとの「いつつ」は数として取らない（箱にいつつ入れる）。
- 「1つの」「一つの」を消した推敲は、数を限る意味（1つの端末だけ、1つの部屋に2人まで）でも拾わない。
- 「優先順位を下げる」は下げる形にしていない（逆転の候補に出る）。序数の「1つ目 → 最初の」は消えた数値、「一つずつ →
  一枚ずつ」は元にない数値になる。
- lint の lint_text() にライブラリとして先頭の BOM がついた文字列を渡すと、1行目の <details> を見ない（CLI は BOM を外して
  読むので同じ値になる）。
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402


def result_of(before, after, doc_type=None):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after, doc_type=doc_type)


def number_risks(before, after, doc_type=None):
    """数値の候補を (subkind, 元の側, 後の側) で返す。並び（order）は元と後の並びを入れる。"""
    out = []
    for risk in result_of(before, after, doc_type)["meaning_risks"]:
        if risk["kind"] != "number":
            continue
        detail = risk["detail"]
        if risk["subkind"] == "order":
            out.append(("order", detail["old_order"], detail["new_order"]))
        else:
            out.append((risk["subkind"], detail["removed"], detail["added"]))
    return out


def reversal_words(before, after, doc_type=None):
    return [risk["detail"]["word"] for risk in result_of(before, after, doc_type)["meaning_risks"]
            if risk["kind"] == "contrast_reversal"]


def values(text):
    return [(number["value"], number["unit"]) for number in yomiyasu_diff.extract_numbers(text)]


def unsupported_numbers(final, materials):
    result = yomiyasu_diff.ground(final + "\n", [material + "\n" for material in materials])
    return [risk["detail"]["text"] for risk in result["meaning_risks"] if risk["subkind"] == "number"]


# ---- 否定対比の逆転: A を別のものに置き換える・切り替える・移す推敲 ----
class ReplaceADemotesTest(unittest.TestCase):
    NOT_FOUND = (
        # 重みの語だけの句のあと
        ("## 手作業ではなく自動化で回す", "## 何よりも、手作業を自動化に切り替える", "slides"),
        ("外部の認証は使わず、自前の認証を作る。", "まず、外部の認証を自前の認証に置き換える。", None),
        ("## 会議ではなく文書で決める", "## まず、会議を文書に置き換える", "slides"),
        ("## 紙の帳票ではなく画面で入力する", "## まず、紙の帳票を画面の入力に移す", "slides"),
        ("## 紙の帳票ではなく画面で入力する", "## 最優先で、紙の帳票を画面の入力に移す", "slides"),
        ("## 手作業ではなく自動化で回す", "## まずは、手作業を仕組みに置き換える", "slides"),
        ("## 手作業ではなく自動化で回す", "## まず、手作業を自動化へ移行する", "slides"),
        ("外部のツールは使わず、社内のツールで回す。", "まず、外部のツールを社内のツールに乗り換える。", None),
        ("## 表計算ではなく専用の画面で管理する", "## 第一に、表計算の管理を専用の画面へ移す", "slides"),
        ("## 手作業ではなく自動化で回す", "## まず、手作業を自動化で置き換える", "slides"),
        ("## 手作業ではなく自動化で回す", "## まず、手作業をスクリプトで置き換える", "slides"),
        # A に続く語の字（グローバル変数）を挟む
        ("グローバル変数は使わず、引数で渡す。", "何よりも、グローバル変数を引数に置き換える。", None),
        ("グローバル変数は使わず、引数で渡す。", "まず、グローバル変数の参照を引数に置き換える。", None),
        # 主題の句と、文の重みの語
        ("## 手作業ではなく自動化で回す", "## 最優先は、手作業を自動化に置き換えること", "slides"),
        ("## 会議ではなく文書で決める", "## 大事なのは、会議を文書に置き換えること", "slides"),
        ("紙の帳票ではなく画面で入力することを最優先にする。", "紙の帳票を画面の入力に切り替えることを最優先にする。", None),
    )
    FOUND = (
        ("外部の認証は使わず、自前の認証を作る。", "まず、自前の認証を外部の認証に置き換える。", None, ["外部"]),
        ("## 会議ではなく文書で決める", "## まず、文書を会議に置き換える", "slides", ["会議"]),
        ("外部のツールは使わず、社内のツールで回す。", "まず、社内のツールを外部のツールに乗り換える。", None, ["外部"]),
        ("グローバル変数は使わず、引数で渡す。", "まず、引数をグローバル変数に置き換える。", None, ["グローバル", "変数"]),
        ("## 表計算ではなく専用の画面で管理する", "## 第一に、専用の画面の管理を表計算へ移す", "slides", ["表計算"]),
        ("## 手作業ではなく自動化で回す", "## まず、自動化を手作業に切り替える", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## まず、自動化を手作業で置き換える", "slides", ["手作業"]),
        ("外部のツールは使わず、社内のツールで回す。", "まず、外部のツールで社内のツールを置き換える。", None, ["外部"]),
        ("## 手作業ではなく自動化で回す", "## まず、手作業で回す", "slides", ["手作業"]),
        ("外部の認証は使わず、自前の認証を作る。", "まず、外部の認証を使う。", None, ["外部"]),
    )
    LIMITS = (
        # 置き換え先を言わずに A を変える言い方は、正しい推敲でも逆転の候補に出る（限界）。原文の B の語（自動化）を出した
        # 「## まず、手作業を自動化する」は、あとの直しで逆転にしなくなった（test_v200_fix_round5.py）
        ("## 会議ではなく文書で決める", "## 第一に、会議の数を絞る", "slides", ["会議"]),
        ("## 手作業ではなく自動化で回す", "## まず、手作業を減らす", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## まず、手作業の自動化から", "slides", ["手作業"]),
    )

    def test_replacing_a_is_not_a_reversal(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_replacing_with_a_is_still_a_reversal(self):
        for before, after, doc_type, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), expected)

    def test_known_limit_changing_a_without_a_target(self):
        for before, after, doc_type, expected in self.LIMITS:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), expected)
                self.assertEqual(result_of(before, after, doc_type)["fail_on_meaning_risk_count"], 0)


# ---- 否定対比の逆転: 下げる語が A と別の名詞に付く ----
class DemoteWordOnOtherNounTest(unittest.TestCase):
    FOUND = (
        ("品質ではなく速度を重視する。", "品質を最優先にして速度はその次にする。", ["品質"]),
        ("品質ではなく速度を重視する。", "品質を最優先にして速度を二番目に置く。", ["品質"]),
        ("品質ではなく速度を重視する。", "何より品質を重視して速度は脇に置く。", ["品質"]),
        ("コストではなく品質を優先する。", "コストを最優先にして品質は二番手に回す。", ["コスト"]),
        ("## 速度ではなく品質", "## 最優先は速度で品質はその次", ["速度"]),
        ("見た目ではなく中身で選ぶ。", "大事なのは見た目で中身はどうでもいい。", ["見た目"]),
        ("価格ではなく品質で選ぶ。", "価格を最も重視し品質を脇役にする。", ["価格"]),
    )
    NOT_FOUND = (
        ("品質ではなく速度を重視する。", "最優先は速度で、品質はその次だ。"),
        ("品質ではなく速度を重視する。", "速度を最優先にし、品質は二番目に見る。"),
        ("見た目ではなく中身で選ぶ。", "中身を最も重視し、見た目はおまけと考える。"),
        ("コストではなく品質を優先する。", "品質を一番に考え、コストはその次とする。"),
        ("コストではなく品質を優先する。", "品質が最優先で、コストの話はその次だ。"),
        ("コストではなく品質を優先する。", "品質が最優先で、コストについてはその次に考える。"),
        ("コストではなく品質を優先する。", "品質が最優先で、コスト面はその次に回す。"),
        ("コストではなく品質を優先する。", "品質が最優先で、コストの検討はそのあとに回す。"),
        ("見た目ではなく使いやすさを重視する。", "使いやすさが一番で、見た目は二番目以降だ。"),
        ("見た目ではなく使いやすさを重視する。", "使いやすさを最優先にし、見た目に凝るのはその次にする。"),
        ("見た目ではなく使いやすさを重視する。", "使いやすさを最優先にし、見た目の工夫は脇に置く。"),
        ("キャッシュではなく、DNSの設定を疑う。", "まずDNSの設定を疑い、キャッシュはその次に見る。"),
    )

    def test_demote_word_on_other_noun_is_still_a_reversal(self):
        for before, after, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after), expected)

    def test_demoted_a_is_not_a_reversal(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after), [])

    def test_known_limits(self):
        # 読点を挟んだ「Aは、その次に」は、正しい推敲でも逆転の候補に出る
        self.assertEqual(reversal_words("キャッシュではなく、DNSの設定を疑う。", "まずDNSの設定を疑い、キャッシュは、その次に見る。"),
                         ["キャッシュ"])
        # 別の名詞のあとの「は後に回す」の逆転は拾わない
        self.assertEqual(reversal_words("品質ではなく速度を重視する。", "品質を最優先にして速度は後に回す。"), [])
        # 「優先順位を下げる」は下げる形にしていない
        self.assertEqual(reversal_words("見た目ではなく使いやすさを重視する。",
                                        "使いやすさを最も大事にし、見た目は優先順位を下げる。"), ["見た目"])


# ---- 数値の並び: 同じ単位の数どうしで比べる ----
class NumberOrderByUnitTest(unittest.TestCase):
    NOT_FOUND = (
        # 違う単位の数の前後が入れ替わっただけ（平仮名の数）
        ("ひとりで2時間歩いた。", "2時間、ひとりで歩いた。", "essay"),
        ("ふたりで3年暮らした家だ。", "3年をふたりで暮らした家だ。", "essay"),
        ("彼女はひとりで10年店を続けた。", "10年、彼女はひとりで店を続けた。", "essay"),
        ("ひとつの鍋で3品を作る。", "3品を、ひとつの鍋で作る。", None),
        ("ふたりの子と3匹の猫がいる。", "3匹の猫と、ふたりの子がいる。", "essay"),
        ("ファイルをひとつずつ3回確認する。", "3回、ファイルをひとつずつ確認する。", None),
        ("ひとつずつ、2回に分けて確かめた。", "2回に分けて、ひとつずつ確かめた。", None),
        ("ひとりで5キロ泳いだ。", "5キロをひとりで泳いだ。", "essay"),
        ("ひとつも3日では終わらなかった。", "3日では、ひとつも終わらなかった。", "essay"),
        ("ひとりで3つの箱を運んだ。", "3つの箱をひとりで運んだ。", "essay"),
        ("ふたりで2時間かけて片付けた。", "2時間かけて、ふたりで片付けた。", "essay"),
        ("ひとつの部屋に3人が集まった。", "3人がひとつの部屋に集まった。", "essay"),
        ("毎朝ひとりで5キロ走る。", "毎朝5キロをひとりで走る。", "essay"),
        ("ひとり3枚まで買える。", "3枚まで、ひとりで買える。", None),
        # 漢数字・算用数字の同じ形
        ("一つの部屋に3人が集まった。", "3人が一つの部屋に集まった。", "essay"),
        ("1つの部屋に3人が集まった。", "3人が1つの部屋に集まった。", None),
        ("ファイルを一つずつ3回確認する。", "3回、ファイルを一つずつ確認する。", None),
        ("ファイルを1つずつ3回確認する。", "3回、ファイルを1つずつ確認する。", None),
        ("一人で3つの箱を運んだ。", "3つの箱を一人で運んだ。", "essay"),
        ("二人で2時間かけて片付けた。", "2時間かけて、二人で片付けた。", "essay"),
    )
    FOUND = (
        ("部屋にふたり、廊下に3人いた。", "部屋に3人、廊下にふたりいた。", "essay", ["ふたり", "3人"], ["3人", "ふたり"]),
        ("部屋にひとり、廊下にふたりいた。", "部屋にふたり、廊下にひとりいた。", "essay", ["ひとり", "ふたり"], ["ふたり", "ひとり"]),
        ("部屋に一人、廊下に二人いた。", "部屋に二人、廊下に一人いた。", "essay", ["一人", "二人"], ["二人", "一人"]),
        ("設計は3日、試験は5日かかる。", "設計は5日、試験は3日かかる。", None, ["3日", "5日"], ["5日", "3日"]),
        ("10時から設計レビュー、14時からテストを行う。", "14時から設計レビュー、10時からテストを行う。", None,
         ["10時", "14時"], ["14時", "10時"]),
    )

    def test_different_units_swapped_is_not_an_order_change(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after, doc_type), [])
                self.assertEqual(result_of(before, after, doc_type)["fail_on_meaning_risk_count"], 0)

    def test_same_unit_swapped_is_an_order_change(self):
        for before, after, doc_type, old_order, new_order in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after, doc_type), [("order", old_order, new_order)])

    def test_known_limit_same_unit_word_order(self):
        """同じ単位の数（ひとり と 3人分）の前後を入れ替えただけの推敲は、正しくても並びの候補に出る。"""
        self.assertEqual(number_risks("ひとりで3人分を食べた。", "3人分をひとりで食べた。", "essay"),
                         [("order", ["ひとり", "3人"], ["3人", "ひとり"])])
        self.assertEqual(number_risks("ひとりで2人分の仕事をした。", "2人分の仕事を、ひとりでこなした。", "essay"),
                         [("order", ["ひとり", "2人"], ["2人", "ひとり"])])


# ---- 「一つずつ」「一つの」: 動詞・名詞のすぐ前でない数の主張の変化 ----
class QuantityClaimFollowupTest(unittest.TestCase):
    FOUND = (
        # 「一つずつ」の動詞のすぐ前の「複数でも」
        ("候補は一つずつ選ぶ。", "候補は複数でも選べる。"),
        ("ファイルは一つずつ送る。", "ファイルは複数でも送れる。"),
        # 「一つの」の名詞のすぐあとの「を・は・が・も別々」
        ("一つの窓口で受け付ける。", "窓口を別々にして受け付ける。"),
        ("申請と問い合わせは一つの窓口で受け付ける。", "申請と問い合わせは窓口を別々にする。"),
        ("ログと設定は一つのファイルに書く。", "ログと設定はファイルを別々にする。"),
        ("2つの班が一つの部屋を使う。", "2つの班が部屋を別々に使う。"),
        # 「ずつ」「の」のあとに動詞・名詞がない（どうぞ、です、にして）
        ("添付は一つずつにしてください。", "添付は複数でもかまいません。"),
        ("質問は一つずつどうぞ。", "質問はいくつでもどうぞ。"),
        ("申し込みは一人一つずつです。", "申し込みは一人で複数できます。"),
        ("質問は一つずつお願いします。", "質問は複数あってもかまいません。"),
        ("画像は一つずつしか選べません。", "画像はいくつでも選べます。"),
        ("画像は一つずつしか選べません。", "画像は複数選べます。"),
        # 相手が1つの文で、動詞・名詞のある節の「複数」「別々に」
        ("候補は一つずつ選ぶ。", "選べる候補は複数ある。"),
        ("ファイルを一つずつ送る。", "送れるファイルは複数です。"),
        ("申請は一つずつ審査する。", "審査する申請は、複数になってもよい。"),
        ("端末は一つずつ登録する。", "登録は、端末が複数でもよい。"),
        ("設定は一つの場所に置く。", "設定は場所を分けて別々に置く。"),
        ("二人は一つの部屋を使う。", "二人は部屋を別々に使う。"),
    )
    NOT_FOUND = (
        # 「複数」「別々」が「一つずつ」「一つの」の主張にかからない
        ("一つの部屋で、二つの班が交代で作業する。", "部屋で、二つの班が別々の時間に作業する。"),
        ("ファイルを一つずつ開き、何か所も直す。", "ファイルを開く。複数の箇所を直す。"),
        ("ファイルを一つずつ開いて、何か所も直す。", "ファイルを順に開いて、複数の箇所を直す。"),
        ("1つのファイルに、複数の設定を書く。", "ファイルに、複数の設定を書く。"),
        ("一つの画面で、複数の項目を設定する。", "画面で、複数の項目を設定する。"),
        ("1つの選択肢として、複数のキャッシュを置く案もある。", "選択肢として、複数のキャッシュを置く案もある。"),
    )

    def test_changed_quantity_claim_is_found(self):
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertIn(("lost", ["一つ"], []), number_risks(before, after))

    def test_unrelated_quantity_words_are_not_a_change(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(result_of(before, after)["fail_on_meaning_risk_count"], 0)

    def test_known_limits(self):
        """「一つの」の名詞を相手の文の別の語から離した推敲は拾わない。名詞を言い換えた1つの文（ログと設定は別々に書く）は、
        あとの直しで拾うようになった（test_v200_fix_round5.py）。"""
        self.assertEqual(number_risks("鍵は一つの金庫にしまう。", "鍵は別々の場所にある金庫にしまう。"), [])
        self.assertEqual(number_risks("ログと設定は一つのファイルに書く。", "ログと設定は別々に書く。"),
                         [("lost", ["一つ"], [])])


# ---- 平仮名の数: 数でない「いつつ」「ひとり言」 ----
class KanaNotNumberFollowupTest(unittest.TestCase):
    def test_not_numbers(self):
        for text in ("家にいつつ、仕事をした。", "元気でいつつ働く。", "そばにいつつ見守る。", "家にいつつも、仕事は進めた。",
                     "彼はひとり言をこぼした。"):
            with self.subTest(text=text):
                self.assertEqual(values(text), [])

    def test_still_numbers(self):
        cases = (
            ("玉をいつつ並べる。", [("5", "つ")]),
            ("全部でいつつある。", [("5", "つ")]),
            ("いつつの箱がある。", [("5", "つ")]),
            ("ひとり旅に出た。", [("1", "人")]),
            ("ひとりで行く。", [("1", "人")]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(values(text), expected)

    def test_shown_values(self):
        """候補で示す値に、数でない語を混ぜない。"""
        self.assertEqual(number_risks("家にいつつ、案を二つ考えた。", "家で、案を三つ考えた。", "essay"),
                         [("replaced", ["二つ"], ["三つ"])])
        self.assertEqual(number_risks("彼はひとり言をこぼし、二人の客を見送った。", "彼は独り言をこぼし、三人の客を見送った。", "essay"),
                         [("replaced", ["二人"], ["三人"])])

    def test_known_limit_itsutsu_after_ni(self):
        """「に」「で」のすぐあとの「いつつ」は数として取らない（箱にいつつ入れる）。数の書き換えも拾わない。"""
        self.assertEqual(values("箱にいつつ入れる。"), [])
        self.assertEqual(number_risks("箱にいつつ入れる。", "箱にむっつ入れる。"), [])
        self.assertEqual(number_risks("玉をいつつ並べる。", "玉をむっつ並べる。"), [("replaced", ["いつつ"], ["むっつ"])])


# ---- 限界として固定する形（直さない）----
class KnownLimitsFollowupTest(unittest.TestCase):
    def test_hiragana_numbers_added_or_removed(self):
        """平仮名の数は、相手の文に同じ単位の値がないと比べない（足しただけ・消しただけ、しか・だけ・まで・ずつの言い換え）。
        漢数字なら候補になる。"""
        for before, after in (
                ("会議室はふたつあります。", "会議室があります。"),
                ("この作業を担当する。", "この作業はふたりで担当する。"),
                ("窓口はみっつ用意した。", "窓口を用意した。"),
                ("席はふたつしかない。", "席は十分ある。"),
                ("参加はひとりだけです。", "参加は自由です。"),
                ("ふたつの案がある。", "案がある。"),
                ("席はひとつしかない。", "席は空いている。"),
                ("菓子をふたつずつ配る。", "菓子をまとめて配る。"),
                ("参加はふたりまでです。", "参加は自由です。"),
                ("窓口はみっつある。", "窓口がある。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(result_of(before, after)["fail_on_meaning_risk_count"], 0)
        self.assertEqual(number_risks("会議室は二つあります。", "会議室があります。"), [("lost", ["二つ"], [])])
        self.assertEqual(number_risks("参加は二人までです。", "参加は自由です。"), [("lost", ["二人"], [])])

    def test_hiragana_numbers_in_new_writing(self):
        """新規作成の照合では、平仮名の数は資料の値と違っても資料にない数値にしない（漢数字ならする）。"""
        self.assertEqual(unsupported_numbers("受付はふたりで担当します。", ["受付は三人で担当する。"]), [])
        self.assertEqual(unsupported_numbers("窓口をみっつ用意します。", ["窓口を五つ用意する。"]), [])
        self.assertEqual(unsupported_numbers("受付は二人で担当します。", ["受付は三人で担当する。"]), ["二人"])
        result = yomiyasu_diff.ground("受付はふたりで担当します。\n", ["受付は三人で担当する。\n"])
        self.assertEqual([(item["text"], item["classification"]) for item in result["items"] if item["kind"] == "number"],
                         [("ふたり", "not_in_sources"), ("三人", "not_in_final")])

    def test_limiting_one_removed(self):
        """「1つの」「一つの」を消した推敲は、数を限る意味でも拾わない。"""
        for before, after in (
                ("同時に使える端末は1つの端末だけです。", "同時に使える端末に制限はありません。"),
                ("1つの部屋に2人まで泊まれる。", "部屋に2人まで泊まれる。"),
                ("一つの部屋に2人まで泊まれる。", "部屋に2人まで泊まれる。"),
                ("API キーは1つのプロジェクトに1つずつ発行する。", "API キーはプロジェクトに発行する。"),
                ("1つの箱に3個入れる。", "箱に3個ずつ入れる。")):
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_ordinal_and_counter(self):
        """序数の「1つ目 → 最初の」は消えた数値、「一つずつ → 一枚ずつ」は元にない数値になる（正しい推敲にも出る）。"""
        self.assertEqual(number_risks("1つ目の理由は費用だ。", "最初の理由は費用だ。"), [("lost", ["1つ"], [])])
        self.assertEqual(number_risks("書類を一つずつ確認する。", "書類を一枚ずつ確認する。"), [("added", [], ["一枚"])])

    def test_lint_text_with_bom(self):
        """lint_text() に先頭の BOM がついた文字列を渡すと、1行目の <details> を見ない（CLI は BOM を外して読む）。"""
        text = ("<details>\n<summary>根拠</summary>\n\n"
                + "".join("- 確かめた点{}: 手順のとおりに動いた\n".format(index) for index in range(1, 7))
                + "\n</details>\n\n確かめたい点があれば、この説明に書き込んでください。計測に使ったデータは、前の週の記録から"
                  "個人の情報を外して作りました。同じ手順で、ほかの画面も速くできるかを次に調べます。\n")
        plain = yomiyasu_lint.lint_text(text)["metrics"]
        self.assertEqual((plain["list_lines"], plain["details_list_lines"]), (0, 6))
        with_bom = yomiyasu_lint.lint_text("﻿" + text)["metrics"]
        self.assertEqual(with_bom["list_lines"], 6)
        self.assertNotIn("details_list_lines", with_bom)


if __name__ == "__main__":
    unittest.main()
