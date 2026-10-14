#!/usr/bin/env python3
"""v2.0.0（5回目の直し、diff と lint）: 前の版から拾えなくなった形と、正しい推敲への誤検出の直しと、残す限界の試験。

文はすべてこのファイルで作った合成の文（反証で見つけた例と、それを言い換えた文）。実在の会社や商品の名前は使わない。

直したこと:

- lint の <details>: 箇条書きの比率（list_ratio と excess_list）を「<details> の外の箇条書きの行 ÷（全体の非空行 − <details> の
  中の箇条書きの行）」にした。中に箇条書きを多く畳んでも、外の箇条書きの比率は薄まらない。この比率は、<details> の中も数えて
  いた前の比率（中と外の箇条書きの行 ÷ 全体の非空行）より大きくならないので、excess_list が新しく出ることはない。
  metrics の total_lines は今までどおり全体の非空行。候補の注記は「リスト行: 外の数 / 全非空行: 分母（<details> の中の箇条書き
  N行は数えていません）」の形にした。
- diff の「一つずつ」「一つの」: 相手が1つの文で、「一つずつ」の動詞・「一つの」の名詞がその文に出ない（言い換えた）ときは、
  動詞・名詞が取れないときと同じく、複数・いくつ・別々 を文のどこに出ても数の主張の変化として数える（質問は一つずつ受け付けます
  → 質問は複数でも構いません、設定は一つのファイルに書きます → 設定は別々の場所に置きます）。ただし、その文に数の主張が同じ語
  （一つずつ: 順に、順番に、個別に、一件ずつ。一つの: 同じ、同一、単一。打ち消したものと、すぐ前が漢字の「手順に」は除く）が
  あるときは、この3つの語を数えない。「一つずつ」の「複数の〜」「いくつかの〜」は、〜が元の文にない名詞なら数えない（ファイルを
  順に見て、複数の誤りを探す）。前から数えていた語（一つずつ: まとめて など。一つの: 複数、上限、無制限）は、数の主張が同じ語が
  あっても今までどおり数える。
- diff の数値の並び: 単位ごとの並びが同じで、同じ語句に付く値も変わらないときでも、数量を言う値（数量を主張しない「一つ」
  などを除く）の並びが変わり、値の多重集合と、数の直前の2字の多重集合が元と後で同じで、値と直前の2字の組が入れ替わったときは、
  並びの候補にする（まず設計に3日、次に試験に5時間 → 設計に5時間、試験に3日）。直前が文頭か読点の数は組に入れない
  （会議は3回、2時間ずつ → 会議は2時間ずつ、3回 は語順だけの推敲）。
- diff の否定対比の逆転: 重みの語だけの句（まず、第一に、何よりも など）から A の節に重みを取ったときは、原文で肯定した側
  （AではなくBの B）の語が同じ節の A より後ろに否定なしで出て、すぐあとが「も」でなければ、A を下げた推敲とみなして候補に
  しない（## まず、手作業の手順を自動化する）。B の語のすぐあとが「を置き換える」などの置き換えの形（B を置き換えた側にした）
  なら、B を肯定したとはみなさない（まず、外部のツールで社内のツールを置き換える は外部の逆転）。

限界として固定する形（直さない。今の出力のまま）:

- 文を分けて、別の文に「複数」「いくつでも」を置いた推敲（ファイルは一つずつ送ってください → ファイルを送ってください。
  複数あってもかまいません）は、名詞を言い換えなくても拾わない。
- 見出しと「使わず・せず」の重みの語だけの句のあとで、原文の B の語を使わずに A を変える・取り除く・調べる言い方（まず、
  手作業を洗い出す／何よりも、手作業をスクリプトにする／まず、手作業の時間を測る）は、正しい推敲でも逆転の候補に出る。
- 重みの語だけの句のあとで A と B の語を両方使った逆転（## まず、会議で決めて文書で知らせる）は拾わない。
- 直前が読点の数を入れ替えた推敲（設計に3日、5時間を試験に充てる → 設計に5時間、3日を試験に充てる）は、並びの候補にしない。
- 「一つずつ」の言い換えの1文で、数の主張が同じ語があっても、前から数えていた語（まとめて）が別の述語に付けば、前の版と同じく
  消えた数値になる（ファイルは一つずつ確認する → ファイルを順に見て、結果はまとめて送る）。

試験のファイルに作者の名前（敬称つき）を書かない（開発の記録の書き方は「作者」にする）ことも、ここで見張る。
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import SCRIPTS  # noqa: E402
from test_v200_details_lists import BODY, PR_DOC, as_div, call_lint, lint, rules  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402

TESTS = Path(__file__).resolve().parent


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


# ---- lint の <details>: 比率の分母から中の箇条書きの行を引く ----
OUTSIDE = (
    "\n## 変更点\n\n"
    "- 設定の読み込みを1か所にまとめ、同じ項目を同じ既定値で読むようにした\n"
    "- 起動時に値を検証し、失敗したら足りない項目の名前を出して止まる\n"
    "- 新しい項目は省略でき、省略したときは今までと同じ既定値を使う\n"
    "- 古い形式の設定ファイルも、書き換えずにそのまま読める\n"
    "- 検証の結果は標準エラーに出し、標準出力には何も足さない\n"
    "- 読み込みの順番は今までと同じで、あとに読んだ値が勝つ\n"
)
INSIDE = "".join("- 根拠の項目{}: test_case_{:02d}\n".format(number, number) for number in range(1, 41))
# 外の箇条書きだけで目安を超える文書と、同じ文書のあとに、中に箇条書きを40行畳んだ <details> を足した文書
HEAVY = BODY + OUTSIDE
HEAVY_WITH_DETAILS = HEAVY + "\n<details>\n<summary>根拠（試験の対応）</summary>\n\n" + INSIDE + "\n</details>\n"
# 外に1項目、中に12項目（PR の説明文の形。前の直しで excess_list が消えた形）
ONE_OUTSIDE = (BODY + "\n- 書き換えは要らない\n\n<details>\n<summary>根拠</summary>\n\n"
               + "".join("- 主張{}: claim-{:02d}\n".format(number, number) for number in range(1, 13)) + "\n</details>\n")
# 3つの <details> に4項目ずつ
THREE_SECTIONS = BODY + "".join(
    "\n<details>\n<summary>根拠{}</summary>\n\n".format(section)
    + "".join("- 項目{}-{}: case-{}{}\n".format(section, number, section, number) for number in range(1, 5))
    + "\n</details>\n" for section in range(1, 4))


def old_ratio(metrics):
    """<details> の中も数えていた前の比率（中と外の箇条書きの行 ÷ 全体の非空行）。"""
    total = metrics["total_lines"]
    return (metrics["list_lines"] + metrics.get("details_list_lines", 0)) / total if total else 0


class DetailsRatioTest(unittest.TestCase):
    def test_lists_folded_inside_do_not_hide_outside_lists(self):
        """中に箇条書きを多く畳んでも、外の箇条書きだけで目安を超える文書の excess_list は消えない。"""
        plain, folded = lint(HEAVY), lint(HEAVY_WITH_DETAILS)
        self.assertIn("excess_list", rules(plain))
        self.assertIn("excess_list", rules(folded))
        metrics = folded["metrics"]
        self.assertEqual((metrics["list_lines"], metrics["details_list_lines"], metrics["total_lines"]), (6, 40, 50))
        self.assertEqual(metrics["list_ratio"], round(6 / 10, 3))

    def test_ratio_formula(self):
        for doc in (HEAVY_WITH_DETAILS, ONE_OUTSIDE, THREE_SECTIONS, PR_DOC, HEAVY):
            with self.subTest(doc=doc[-30:]):
                metrics = lint(doc)["metrics"]
                base = metrics["total_lines"] - metrics.get("details_list_lines", 0)
                self.assertEqual(metrics["list_ratio"], round(metrics["list_lines"] / base, 3) if base else 0)

    def test_ratio_is_never_above_the_old_ratio(self):
        """前の比率より大きくならないので、excess_list が新しく出る文書はない（出るなら <div> にした文書でも出る）。"""
        for doc in (HEAVY_WITH_DETAILS, ONE_OUTSIDE, THREE_SECTIONS, PR_DOC, HEAVY):
            with self.subTest(doc=doc[-30:]):
                result = lint(doc)
                self.assertLessEqual(result["metrics"]["list_ratio"], round(old_ratio(result["metrics"]), 3))
                if "excess_list" in rules(result):
                    self.assertIn("excess_list", rules(lint(as_div(doc))))

    def test_pr_shaped_documents_stay_quiet(self):
        """前の直しで excess_list が消えた PR の説明文の形は、消えたまま。"""
        for doc in (PR_DOC, ONE_OUTSIDE, THREE_SECTIONS):
            with self.subTest(doc=doc[-30:]):
                self.assertNotIn("excess_list", rules(lint(doc)))
                self.assertIn("excess_list", rules(lint(as_div(doc))))

    def test_snippet_shows_the_denominator(self):
        finding = [item for item in lint(HEAVY_WITH_DETAILS)["findings"] if item["rule"] == "excess_list"][0]
        self.assertEqual(finding["snippet"], "リスト行: 6 / 全非空行: 10（<details> の中の箇条書き40行は数えていません）")
        self.assertIn("箇条書きの比率（60.0%）", finding["message"])

    def test_total_lines_is_still_every_non_empty_line(self):
        self.assertEqual(lint(HEAVY_WITH_DETAILS)["metrics"]["total_lines"],
                         lint(as_div(HEAVY_WITH_DETAILS))["metrics"]["total_lines"])

    def test_strict_exit_code(self):
        code, out, err = call_lint(["--strict"], stdin=HEAVY_WITH_DETAILS.encode("utf-8"))
        self.assertEqual((code, err), (1, ""))
        self.assertIn("excess_list", out)
        code, _, err = call_lint(["--strict"], stdin=ONE_OUTSIDE.encode("utf-8"))
        self.assertEqual((code, err), (0, ""))


# ---- 「一つずつ」の動詞・「一つの」の名詞を言い換えた1つの文 ----
class QuantityHeadRewordedTest(unittest.TestCase):
    FOUND = (
        ("質問は一つずつ受け付けます。", "質問は複数でも構いません。"),
        ("ファイルは一つずつ送ってください。", "ファイルは複数を添付できます。"),
        ("画像は一つずつ選んでください。", "画像は複数を指定できます。"),
        ("注文は一つずつ処理します。", "注文は複数件をさばけます。"),
        ("記事は一つずつ公開します。", "記事は複数を予約できます。"),
        ("申請は一つずつ審査します。", "申請はいくつでも出せます。"),
        ("ファイルは一つずつ送ってください。", "複数のファイルを添付できます。"),
        ("設定は一つのファイルに書きます。", "設定は別々の場所に置きます。"),
        ("部品は一つの箱に入れます。", "部品は別々に包みます。"),
        ("部品は一つの箱に入れます。", "部品は別々の袋に包みます。"),
        ("ログと設定は一つのファイルに書く。", "ログと設定は別々に書く。"),
        # 「手順に」「語順に」の「順に」は数の主張が同じ語にしない
        ("ファイルは一つずつ送ってください。", "手順に沿って複数のファイルを添付できます。"),
        ("申請は一つずつ審査します。", "申請は手順に従い、複数でも受け付けます。"),
        # 数の主張が同じ語は打ち消せば数えない
        ("部品は一つの箱に入れます。", "部品は同じではない箱に別々に包みます。"),
    )
    # 前から数えていた語（「一つの」の 複数・上限、「一つずつ」の まとめて）は、数の主張が同じ語があっても今までどおり数える
    KEPT = (
        ("設定は一つのファイルに書きます。", "設定は同じ形式で複数の場所に置きます。"),
        ("設定は一つのファイルに書きます。", "設定は同じ名前のまま、上限なしで置けます。"),
        ("ファイルは一つずつ確認する。", "ファイルは順に開き、まとめて見られます。"),
    )
    NOT_FOUND = (
        # 数の主張が同じ語がある
        ("ファイルを一つずつ確認する。", "ファイルを順に見て、複数の誤りを探す。"),
        ("申請は一つずつ審査します。", "申請は順番に見て、複数の担当で確かめます。"),
        ("画像は一つずつ選んでください。", "画像は順に指定し、複数の候補から決めてください。"),
        ("ファイルを一つずつ開いて、何か所も直す。", "ファイルを順に見ながら、複数の箇所を直す。"),
        ("設定は一つのファイルに書きます。", "設定は同じ場所にまとめ、ログは別々に残します。"),
        # 「複数の〜」「いくつかの〜」の〜が元の文にない名詞
        ("ファイルは一つずつ確認する。", "ファイルを見て、複数の誤りを探す。"),
        ("申請は一つずつ審査します。", "申請を見て、いくつかの点を確かめます。"),
        # 数を言う語がない
        ("質問は一つずつ受け付けます。", "質問は順番に伺います。"),
        ("部品は一つの箱に入れます。", "部品は同じ箱にしまいます。"),
        ("記事は一つずつ公開します。", "記事は個別に出します。"),
        ("部品は一つの箱に入れます。", "部品は同一の箱にしまい、説明書は別々に付けます。"),
        ("申請は一つずつ審査します。", "申請は届いた順番に見て、複数の担当で確かめます。"),
    )

    def test_changed_quantity_claim_is_found(self):
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertIn(("lost", ["一つ"], []), number_risks(before, after))
                self.assertGreaterEqual(result_of(before, after)["fail_on_meaning_risk_count"], 1)

    def test_words_counted_before_are_still_counted(self):
        for before, after in self.KEPT:
            with self.subTest(before=before, after=after):
                self.assertIn(("lost", ["一つ"], []), number_risks(before, after))

    def test_same_claim_is_not_a_change(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])


# ---- 数値の並び: 値と数の直前の2字の組の入れ替え ----
class NumberOrderLeadSwapTest(unittest.TestCase):
    FOUND = (
        ("まず設計に3日、次に試験に5時間かける。", "設計に5時間、試験に3日かける。", ["3日", "5時間"], ["5時間", "3日"]),
        ("設計に3日、試験に5時間かける。", "まず設計に5時間、次に試験に3日かける。", ["3日", "5時間"], ["5時間", "3日"]),
        ("応答は200ms以内、復旧は5分以内にする。", "目標として応答は5分以内、復旧は200ms以内にする。",
         ["200ms", "5分"], ["5分", "200ms"]),
        ("東京に3台、大阪に5人を置く。", "拠点として東京に5人、大阪に3台を置く。", ["3台", "5人"], ["5人", "3台"]),
        ("初回は30日、更新は1年ごとに見直す。", "契約の初回は1年、更新は30日ごとに見直す。", ["30日", "1年"], ["1年", "30日"]),
        ("午前は2時間、午後は30分の休憩を取る。", "休憩は午前は30分、午後は2時間取る。", ["2時間", "30分"], ["30分", "2時間"]),
        ("メールは24時間以内、電話は3日以内に返す。", "返事はメールは3日以内、電話は24時間以内にする。",
         ["24時間", "3日"], ["3日", "24時間"]),
    )
    NOT_FOUND = (
        ("会議は3回、2時間ずつ行う。", "会議は2時間ずつ、3回行う。"),
        ("まず設計に3日、次に試験に5時間かける。", "試験に5時間、設計に3日かける。"),
        ("設計に3日、試験に5時間かける。", "まず試験に5時間、次に設計に3日かける。"),
        ("ひとりで2時間歩いた。", "2時間、ひとりで歩いた。"),
        ("3日で5人が参加した。", "5人が3日で参加した。"),
        ("研修は3日間、毎日6時間行う。", "研修は毎日6時間、3日間行う。"),
        ("1日3回、食後に30分歩く。", "食後に30分、1日3回歩く。"),
        ("東の倉庫に30箱、西の倉庫に2台を運ぶ。", "西の倉庫に2台、東の倉庫に30箱を運ぶ。"),
        ("2週間で、3つの機能を作る。", "3つの機能を、2週間で作る。"),
        ("3人で2時間かけて片付けた。", "2時間かけて3人で片付けた。"),
        ("10GBの容量を3台で分ける。", "3台で10GBの容量を分ける。"),
        ("一人で3つの箱を運んだ。", "3つの箱を一人で運んだ。"),
    )

    def test_swapped_values_are_an_order_change(self):
        for before, after, old_order, new_order in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertIn(("order", old_order, new_order), number_risks(before, after))
                self.assertEqual(result_of(before, after)["fail_on_meaning_risk_count"], 1)

    def test_reordered_words_are_not_an_order_change(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])


# ---- 否定対比の逆転: 重みの語だけの句のあとに、原文で肯定した側の語を出した推敲 ----
class WeightOnlyAffirmedSideTest(unittest.TestCase):
    NOT_FOUND = (
        ("## 手作業ではなく自動化で回す", "## まず、手作業の手順を自動化する", None),
        ("## 手作業ではなく自動化で回す", "## まず、手作業を洗い出して自動化する", None),
        ("## 手作業ではなく自動化で回す", "## まず、手作業を自動化する", None),
        ("## 手作業ではなく自動化で回す", "## まず、手作業を自動化する", "slides"),
        ("## 手作業ではなく自動化で回す", "## まず、手作業を自動化に変える", None),
        ("## 会議ではなく文書で決める", "## まず、会議の議題を文書にする", None),
        ("## 会議ではなく文書で決める", "## 何よりも、会議で決めていたことを文書で決める", None),
        ("## 口頭ではなくチャットで伝える", "## まず、口頭で伝えていた連絡をチャットに移す", None),
        ("## 口頭ではなくチャットで伝える", "## まず、口頭の連絡をチャットに寄せる", None),
        ("## キャッシュは使わず、DBを直接読む", "## まず、キャッシュを外してDBを直接読む", None),
        ("## 紙の帳票ではなく画面で入力する", "## 第一に、紙の帳票を見直して画面で入力する", None),
        ("手作業はせず、スクリプトで回す。", "まず、手作業をスクリプトにする。", None),
        ("手作業はせず、スクリプトで回す。", "まず、手作業の確認をスクリプトにする。", None),
    )
    FOUND = (
        # B の語を置き換えた側にした
        ("外部のツールは使わず、社内のツールで回す。", "まず、外部のツールで社内のツールを置き換える。", None, ["外部"]),
        ("## 手作業ではなく自動化で回す", "## まず、手作業で自動化を置き換える", None, ["手作業"]),
        # B の語のすぐあとが「も」
        ("## 手作業ではなく自動化で回す", "## まず、手作業で回して自動化も試す", None, ["手作業"]),
        # B の語がない、または別の節
        ("## 手作業ではなく自動化で回す", "## まず、手作業で回す", None, ["手作業"]),
        ("外部の認証は使わず、自前の認証を作る。", "まず、外部の認証を使い、自前の認証は後で作る。", None, ["外部"]),
        ("## 手作業ではなく自動化で回す", "## まずは、手作業で回して様子を見る", None, ["手作業"]),
        ("外部の認証は使わず、自前の認証を作る。", "何よりも、外部の認証を使う。", None, ["外部"]),
        # 重みの語が A の節そのものや主題の句にある形は、今までどおり
        ("## 会議ではなく文書で決める", "## 大事なのは、会議で決めて文書で知らせること", "slides", ["会議"]),
    )

    def test_affirmed_side_after_a_is_not_a_reversal(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(before=before, after=after, doc_type=doc_type):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_reversals_are_still_found(self):
        for before, after, doc_type, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), expected)


# ---- 限界（直さない。今の出力のまま） ----
class KnownLimitsRound5Test(unittest.TestCase):
    def test_quantity_word_in_a_separate_sentence(self):
        """文を分けて、別の文に「複数」「いくつでも」を置いた推敲は、名詞を言い換えなくても拾わない。"""
        cases = (
            ("ファイルは一つずつ送ってください。", "ファイルを送ってください。複数あってもかまいません。"),
            ("申請は一つずつ審査します。", "申請を審査します。複数の申請があってもかまいません。"),
            ("質問は一つずつ受け付けます。", "質問を受け付けます。いくつでも構いません。"),
            ("端末は一つずつ登録してください。", "端末を登録してください。複数台でも登録できます。"),
            ("注文は一つずつ発送します。", "注文を発送します。複数の注文は同じ箱に入れます。"),
        )
        for before, after in cases:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [])

    def test_weight_only_forms_without_the_b_side(self):
        """重みの語だけの句のあとで、原文の B の語を使わずに A を変える・取り除く・調べる言い方は、正しい推敲でも候補に出る。"""
        h = "## 手作業ではなく自動化で回す"
        z = "外部の認証は使わず、自前の認証を作る。"
        cases = (
            (h, "## まず、手作業を洗い出す", ["手作業"]),
            (h, "## 何よりも、手作業をスクリプトにする", ["手作業"]),
            (h, "## まず、手作業をスクリプトに変える", ["手作業"]),
            (h, "## まず、手作業の削減から始める", ["手作業"]),
            (h, "## まず、手作業の時間を測る", ["手作業"]),
            (z, "まず、外部の認証への依存を減らす。", ["外部"]),
            (z, "まず、外部の認証との連携を外し、自前の認証を作る。", ["外部"]),
            ("手作業はせず、スクリプトで回す。", "まず、手作業を自動化する。", ["手作業"]),
        )
        for before, after, expected in cases:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), expected)

    def test_other_predicate_with_a_word_counted_before(self):
        """数の主張が同じ語（順に）があっても、前から数えていた語（まとめて）が別の述語に付く1文は、前の版と同じく消えた数値に
        なる（言い換えた1文で足した語の見分けは、前から数えていた語には当てない）。"""
        self.assertEqual(number_risks("ファイルは一つずつ確認する。", "ファイルを順に見て、結果はまとめて送る。"),
                         [("lost", ["一つ"], [])])

    def test_reversal_with_both_a_and_b(self):
        """重みの語だけの句のあとで A と B の語を両方使った逆転は拾わない。"""
        self.assertEqual(reversal_words("## 会議ではなく文書で決める", "## まず、会議で決めて文書で知らせる"), [])

    def test_swap_with_a_number_after_a_comma(self):
        """直前が読点の数を入れ替えた推敲は、並びの候補にしない（前の版から同じ）。"""
        self.assertEqual(number_risks("設計に3日、5時間を試験に充てる。", "設計に5時間、3日を試験に充てる。"), [])


# ---- 試験のファイルに作者の名前を書かない ----
# 作者の名前に敬称を付けた形（名前そのものは書かないよう、文字の番号で作る。test_v200_fix_round3 の見張りと同じ）
OWNER_NOTE = "\u5927\u8cc0" + "\u3055\u3093"


class TestFilesHaveNoOwnerNotesTest(unittest.TestCase):
    def test_no_owner_notes_in_test_files(self):
        found = []
        for path in sorted(TESTS.glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if OWNER_NOTE in line:
                    found.append("{}:{}".format(path.name, number))
        self.assertEqual(found, [])

    def test_the_pattern(self):
        self.assertIsNotNone(re.search(OWNER_NOTE, "x" + OWNER_NOTE + "の判断"))
        self.assertIsNone(re.search(OWNER_NOTE, "作者の判断"))


if __name__ == "__main__":
    unittest.main()
