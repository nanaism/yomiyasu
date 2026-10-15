#!/usr/bin/env python3
"""v2.0.0（5回目の直しの反証のあと、diff）: 5回目の直しで前の版から拾えなくなった形と、正しい推敲への新しい誤検出の直しと、
残す限界の試験。

文はすべてこのファイルで作った合成の文（反証で見つけた例と、それを言い換えた文）。実在の会社や商品の名前は使わない。

直したこと:

- 否定対比の逆転: 重みの語だけの句のあとで、原文で肯定した側（AではなくBの B）の語が A より後ろに出ても、B のすぐあとが
  「を・は・も」と B を退ける動詞（中止、減らす、省く、捨てる、廃止、控える、見送る、禁止、やめる、止める、なくす、削る）なら、
  B を肯定したとはみなさない（## まず、手作業で回して自動化を中止する は手作業の逆転。5回目の直しの前と同じ）。B のすぐあとが
  「の〜を減らす」（自動化の漏れを減らす）なら、今までどおり B を肯定した形として見る。
- 「一つずつ」の動詞・「一つの」の名詞を言い換えた1文: 複数・いくつ・別々 を数えるのは、元の文の主題（文頭の「〜は」「〜が」）と
  同じ主語の節か、主語のない節だけにした（申請は一つずつ審査し、何人かの担当者が確かめます → 申請は逐一見て、複数の担当者が
  確かめます は、担当者の数の言い換えで、申請の数の主張は変わっていない）。主語が違っても、その節に主題の語が出れば数える
  （申請は一つずつ審査します → 担当者は複数の申請を見ます）。助詞で終わる節（申請は、）は次の節と1つにして見る。
- 数値の並び: 数の直前の2字を取るときに、数のすぐ前の共通の修飾語（約、計、合計、最大、最小、最短、最長、およそ）を飛ばす
  （移行は約2週間、検証で約3日かかる → 検証は約3日、移行で約2週間かかる は語順だけの推敲）。

限界として固定する形（直さない。今の出力のまま）:

- B を廃止する・見送る・控える・禁止する・頼らない、B より A を優先する、B を後回しにする、と言う逆転は拾わない（前の版から同じ）。
- 言い換えた1文で、主題と同じ語を主語にした節（似た質問が複数届いたら）、主語のない節（版ごとに別々の名前を付けます）、送り仮名の
  途中で切れる主語（問い合わせが）にある 複数・別々 は、正しい推敲でも消えた数値になる。
- 原文にない担当者や動作主を主語や通知先に足した推敲は、意味が変わる恐れに出ない（全文差分と新しく出た語には出る）。
- できる → している、評価の語（容易）や表題の（下書き）を消した推敲、範囲を言い換えた推敲、する側と受ける側を替えた推敲、
  「にくい」を否定にした推敲は、意味が変わる恐れに出ない。
- 文を分け、否定を別の言い方で次の文に移した推敲は、正しい推敲でも否定の候補になる。
- 数を言わない語を数字で言い直した推敲（一意 → 1つ、集約 → 1件にまとめ、倍々 → 2倍ずつ、単体 → 1件ずつ）と、助数詞を替えた
  推敲（2〜3本 → 2〜3回）と、1枚挟む → 作って置く は、正しい推敲でも数値の候補になる。
- 同じ助詞と「約」の数の入れ替え（設計に約3日、試験に約5時間 → 設計に約5時間、試験に約3日）は拾わない（前の版から同じ）。
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v200_check import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402


def result_of(before, after, doc_type=None):
    if not before.endswith("\n"):
        before += "\n"
    if not after.endswith("\n"):
        after += "\n"
    return yomiyasu_diff.diff(before, after, doc_type=doc_type)


def number_risks(before, after):
    """数値の候補を (subkind, 元の側, 後の側) で返す。並び（order）は元と後の並びを入れる。"""
    out = []
    for risk in result_of(before, after)["meaning_risks"]:
        if risk["kind"] != "number":
            continue
        detail = risk["detail"]
        if risk["subkind"] == "order":
            out.append(("order", detail["old_order"], detail["new_order"]))
        else:
            out.append((risk["subkind"], detail["removed"], detail["added"]))
    return out


def reversal_words(before, after):
    return [risk["detail"]["word"] for risk in result_of(before, after)["meaning_risks"]
            if risk["kind"] == "contrast_reversal"]


def risk_kinds(before, after):
    return [risk["kind"] + ("/" + risk["subkind"] if risk.get("subkind") else "")
            for risk in result_of(before, after)["meaning_risks"]]


H = "## 手作業ではなく自動化で回す"
M = "## 会議ではなく文書で決める"


# ---- 否定対比の逆転: 重みの語だけの句のあとで、B を退ける動詞を使った逆転 ----
class WeightOnlyRejectedSideTest(unittest.TestCase):
    FOUND = (
        (H, "## まず、手作業で回して自動化を中止する", ["手作業"]),
        (H, "## まず、手作業を基本にして自動化を減らす", ["手作業"]),
        (H, "## まず、手作業で回して自動化を捨てる", ["手作業"]),
        (H, "## まず、手作業で回して自動化を削る", ["手作業"]),
        (M, "## まず、会議で決めて文書は省く", ["会議"]),
        (M, "## まず、会議を増やして文書を減らす", ["会議"]),
        ("会議はせず、文書で決めます。", "まず、会議で決めて文書を減らします。", ["会議"]),
        # 5回目の直しの前から拾っていた形（変わらない）
        (H, "## まず、手作業に戻して自動化をやめる", ["手作業"]),
        (M, "## まず、会議で決めて文書を取りやめる", ["会議"]),
        (M, "## まず、会議で決めて文書も減らす", ["会議"]),
    )
    NOT_FOUND = (
        # B のすぐあとが「の〜を減らす」（B を退けていない）と、B を肯定した正しい推敲
        (H, "## まず、手作業の手順を見直して自動化の漏れを減らす"),
        (M, "## まず、会議の議題を文書にして文書の手戻りを減らす"),
        (H, "## まず、手作業を自動化して手戻りを減らす"),
        (H, "## まず、手作業の手順を自動化する"),
        (M, "## まず、会議の議題を文書で決める"),
    )

    def test_rejected_side_is_a_reversal(self):
        for before, after, expected in self.FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), expected)

    def test_affirmed_side_is_still_not_a_reversal(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), [])


# ---- 「一つずつ」「一つの」を言い換えた1文: 主語の違う節の 複数・別々 ----
class QuantityOtherSubjectTest(unittest.TestCase):
    NOT_FOUND = (
        ("申請は一つずつ審査し、何人かの担当者が確かめます。", "申請は逐一見て、複数の担当者が確かめます。"),
        ("原稿は一つずつ点検し、誤字が何か所かあれば戻します。", "原稿は逐一目を通し、誤字が複数あれば戻します。"),
        ("荷物は一つずつ検品し、傷がいくらかあれば返品します。", "荷物はそれぞれ目で見て、傷が複数あれば返品します。"),
        ("設定は一つのファイルに書き、ログは日ごとに分けて残します。", "設定はひとまとめにし、ログは日ごとに別々に残します。"),
        ("鍵は一つの金庫に入れ、合鍵は各自で分けて持ちます。", "鍵はまとめて保管し、合鍵は各自が別々に持ちます。"),
        # 逆の向き（後の文に「一つずつ」「一つの」を足した）と、算用数字の「1つずつ」
        ("申請は逐一見て、複数の担当者が確かめます。", "申請は一つずつ審査し、何人かの担当者が確かめます。"),
        ("設定はひとまとめにし、ログは日ごとに別々に残します。", "設定は一つのファイルに書き、ログは日ごとに分けて残します。"),
        ("申請は1つずつ審査し、何人かの担当者が確かめます。", "申請は逐一見て、複数の担当者が確かめます。"),
        ("申請は一つずつ審査し、担当者が何人かで確かめます。", "申請は逐一見て、担当者が複数で確かめます。"),
        # 送り仮名で終わる主語
        ("原稿は一つずつ点検し、誤字が何か所かあれば戻します。", "原稿は逐一目を通し、誤りが複数あれば戻します。"),
        ("図面は一つずつ確認し、寸法の揺れがいくらかあれば直します。", "図面は逐一確かめ、寸法の揺れが複数あれば直します。"),
    )
    FOUND = (
        # 主語が違っても、その節に主題の語が出る
        ("申請は一つずつ審査します。", "担当者は複数の申請を見ます。"),
        ("質問は一つずつ受け付けます。", "窓口は複数の質問に答えます。"),
        ("部品は一つの箱に入れます。", "作業者が部品を別々に包みます。"),
        # 助詞で終わる節（申請は、）は次の節と1つにして見る
        ("申請は一つずつ審査します。", "申請は、担当者が複数を見ます。"),
        ("設定は一つのファイルに書きます。", "設定は、運用チームが別々に管理します。"),
        # 主題と同じ主語の節
        ("設定は一つのファイルに書き、ログは日ごとに分けて残します。", "設定は別々の場所に置き、ログは日ごとに残します。"),
        ("申請は一つずつ審査します。", "申請は複数まとめて見ます。"),
        ("設定は一つのファイルに書きます。", "設定は別々の場所に置きます。"),
    )

    def test_other_subject_is_not_a_change(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_same_topic_is_still_a_change(self):
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertIn(("lost", ["一つ"], []), number_risks(before, after))


# ---- 数値の並び: 数のすぐ前の共通の修飾語 ----
class NumberOrderCommonModifierTest(unittest.TestCase):
    NOT_FOUND = (
        ("移行は約2週間、検証で約3日かかる。", "検証は約3日、移行で約2週間かかる。"),
        ("設計は約3日、試験に約5時間かける。", "試験は約5時間、設計に約3日かける。"),
        ("開発に計3人、運用は計2台を使う。", "運用に計2台、開発は計3人を使う。"),
        ("移行は合計2週間、検証で合計3日かかる。", "検証は合計3日、移行で合計2週間かかる。"),
        ("移行はおよそ2週間、検証でおよそ3日かかる。", "検証はおよそ3日、移行でおよそ2週間かかる。"),
        ("設計には最大3日、試験は最大5時間を見込む。", "試験には最大5時間、設計は最大3日を見込む。"),
    )
    FOUND = (
        ("まず設計に最大3日、次に試験に最大5時間を充てる。", "設計に最大5時間、試験に最大3日を充てる。",
         ["3日", "5時間"], ["5時間", "3日"]),
        ("開発に計3人、運用に計2台を使う。", "開発に計2台、運用に計3人を使う。", ["3人", "2台"], ["2台", "3人"]),
    )

    def test_reordered_words_are_not_an_order_change(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])

    def test_swapped_values_are_an_order_change(self):
        for before, after, old_order, new_order in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertIn(("order", old_order, new_order), number_risks(before, after))


# ---- 限界（直さない。今の出力のまま） ----
class KnownLimitsRound5ReviewTest(unittest.TestCase):
    def test_reversals_with_other_verbs(self):
        """B を廃止する・見送る・控える・禁止する・頼らない、B より A を優先する、B を後回しにする、と言う逆転は拾わない。"""
        cases = (
            (H, "## まず、手作業で回して自動化を廃止する"),
            (H, "## まず、手作業で回して自動化は見送る"),
            (H, "## まず、手作業で回して自動化に頼らない"),
            (H, "## まず、手作業で回して自動化をなくす"),
            ("## 口頭ではなくチャットで伝える", "## 第一に、口頭で伝えてチャットを禁止する"),
            ("## 口頭ではなくチャットで伝える", "## まず、口頭で伝えてチャットは控える"),
            (M, "## まず、会議を文書より優先する"),
            (M, "## まず、会議で決めて文書を後回しにする"),
            (M, "## まず、会議で決めて文書を廃止する"),
            ("会議はせず、文書で決めます。", "まず、会議で決めて文書を廃止します。"),
        )
        for before, after in cases:
            with self.subTest(after=after):
                self.assertEqual(reversal_words(before, after), [])

    def test_quantity_word_in_a_clause_left_counted(self):
        """主題と同じ語を主語にした節、主語のない節、送り仮名の途中で切れる主語の節の 複数・別々 は、正しい推敲でも数える。"""
        cases = (
            ("質問は一つずつ回答し、似た質問が何件か届いたら一覧にします。",
             "質問には逐一答え、似た質問が複数届いたら一覧にします。"),
            ("資料は一つのフォルダに入れ、版ごとに分けて名前を付けます。", "資料はひとまとめに置き、版ごとに別々の名前を付けます。"),
            ("質問は一つずつ回答し、問い合わせが何件か重なれば一覧にします。",
             "質問には逐一答え、問い合わせが複数重なれば一覧にします。"),
        )
        for before, after in cases:
            with self.subTest(before=before):
                self.assertEqual(number_risks(before, after), [("lost", ["一つ"], [])])

    def test_added_actor_is_not_a_meaning_risk(self):
        """原文にない担当者や動作主を主語や通知先に足した推敲は、担当者だけでは意味が変わる恐れに出ない。因果の足しは見直し候補に出る。"""
        cases = (
            ("倉庫の棚に札を足し、在庫は台帳から数える。", "物流チームは倉庫の棚に札を足し、在庫を台帳から数える。", "チーム"),
            ("回線の帯域を一時的に広げ、再接続して戻した。", "夜間の担当者が回線の帯域を一時的に広げ、再接続して戻した。", "担当者"),
            ("残りの容量が一割を切ったら知らせる。", "残りの容量が一割を切ったら、保守担当者に知らせる。", "保守担当者"),
            ("監視の設定が未整備で、発見が遅れた。", "保守チームが監視を設定していなかったため、発見が遅れた。", "チーム"),
        )
        for before, after, word in cases:
            with self.subTest(after=after):
                result = result_of(before, after)
                expected = [("claim", "causal")] if "ため" in after else []
                self.assertEqual([(r["kind"], r["subkind"]) for r in result["meaning_risks"]], expected)
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)
                if expected:
                    self.assertEqual(result["meaning_risks"][0]["detail"]["reason"], "new_content")
                self.assertIn(word, result["new_words"])

    def test_modality_evaluation_scope_and_role(self):
        """できる → している、評価の語や（下書き）を消した推敲、範囲の言い換え、する側と受ける側の交代、「にくい」を否定にした
        推敲は、意味が変わる恐れに出ない。「にくい」でなく肯定を否定にした推敲は否定の候補になる。"""
        cases = (
            ("見習いは一人で検品を担当できるまでになっている。", "見習いは一人で検品を担当している。"),
            ("既定の設定で記録、通知、集計が容易である。", "既定の設定で記録し、通知し、集計できる。"),
            ("# 帳票の出力の手順（下書き）\n\n本文。", "# 帳票の出力の手順\n\n本文。"),
            ("上限と制限を窓口の層で一律にかけられる。", "上限と制限を窓口の層で全部の口に同じ設定でかけられる。"),
            ("最初に私が自分の帳票でやり、皆に見せた。", "最初に私が自分の帳票でこの依頼を受け、皆に見せた。"),
            ("記録を残さないので、障害時の原因を追いにくくなっています。", "記録を残さないので、障害が起きたときに原因を追えません。"),
        )
        for before, after in cases:
            with self.subTest(after=after):
                self.assertEqual(risk_kinds(before, after), [])
        self.assertEqual(risk_kinds("記録を残さないので、障害時の原因を追えます。",
                                    "記録を残さないので、障害が起きたときに原因を追えません。"), ["negation"])

    def test_negation_moved_to_the_next_sentence(self):
        """文を分け、否定を別の言い方で次の文に移した推敲は、正しい推敲でも否定の候補になる（同じ語で書けば出ない）。"""
        before = "同じ処理で予備の表に書き込み、別の処理が配る形に変えてから、抜けた通知の調査は発生していません。"
        head = "今は、同じ処理で予備の表に書き込み、別の処理が配っています。"
        self.assertEqual(risk_kinds(before, head + "この形に変えてから、抜けた通知を調べる事態は起きていません。"),
                         ["negation"])
        self.assertEqual(risk_kinds(before, head + "この形に変えてから、抜けた通知の調査は発生していません。"), [])
        self.assertEqual(risk_kinds(before, head), ["negation"])

    def test_numbers_from_words_and_counters(self):
        """数を言わない語を数字で言い直した推敲と、助数詞を替えた推敲と、1枚挟む → 作って置く は、数値の候補になる。"""
        cases = (
            ("番号を保存して重複を弾けば、鍵は一意に保たれる。", "番号を保存して重複を弾けば、鍵は1つに定まる。",
             ("added", [], ["1つ"])),
            ("同じ人の重複した注文は鍵で集約し、二重の発送を防ぐ。", "同じ人の重複した注文は鍵で1件にまとめ、二重に発送しないようにする。",
             ("added", [], ["1件"])),
            ("待ち時間は初めの10秒から倍々に伸ばす。", "初めは10秒後に試し、以降は待ち時間を2倍ずつ延ばす。", ("added", [], ["2倍"])),
            ("障害のあとは画面から単体または一括で送り直せる。", "障害のあとは画面から1件ずつでも一括でも送り直せる。",
             ("added", [], ["1件"])),
            ("一覧で2〜3本の要求を順に送っている。", "一覧が窓口を2〜3回順に呼んでいる。", ("replaced", ["3本"], ["3回"])),
            ("今の窓口は残し、前に変換の層を1枚挟む。", "今の窓口は残し、変換の層を作って前に置く。", ("lost", ["1枚"], [])),
        )
        for before, after, expected in cases:
            with self.subTest(after=after):
                self.assertEqual(number_risks(before, after), [expected])
                self.assertEqual(result_of(before, after)["fail_on_meaning_risk_count"], 1)

    def test_swap_with_the_same_particle_and_about(self):
        """同じ助詞と「約」の数の入れ替えは拾わない（前の版から同じ）。"""
        self.assertEqual(number_risks("設計に約3日、試験に約5時間かける。", "設計に約5時間、試験に約3日かける。"), [])


if __name__ == "__main__":
    unittest.main()
