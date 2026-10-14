#!/usr/bin/env python3
"""v2.0.0（4回目の直し、diff）: 数値と否定対比の逆転の判定で、正しい推敲への誤検出を減らした直しと、残す限界の試験。

文はすべてこのファイルで作った合成の文（反証で見つけた例と、それを言い換えた文）。実在の会社や商品の名前は使わない。

- 算用数字の「1つ」: 漢数字の「一つ」と同じ扱いにする。「もう1つ」「1つ1つ」「1つも〜ない」は数量を主張しない値。
  「1つの」「1つずつ」は、相手の文で数の主張が変わったとき（まとめて、複数の など）だけ比べに残す。「1つのみ」は数を限る
  言い方なので数える。前は算用数字の「1つ」を数として数えていたが、「もう1つの利点は → 〜も利点です」「1つずつ → 順に」の
  ような正しい推敲に --fail-on の候補が出たので改めた。「理由がある → もう1つ理由がある」と、新規作成の「1つの画面に
  まとめました」は候補に出なくなる（限界）。
- 平仮名の数（ひとつ〜ここのつ、ひとり、ふたり）: 値1〜9、単位「つ」「人」の、数量を主張しない値として取る。相手の側に同じ
  単位の値があれば比べ、なければ比べから外す。「1つ → ひとつ」「一人 → ひとり」は候補にせず、「ひとつ → ふたつ」
  「3人 → ひとり」は候補にする。「ひとつの」「ひとつずつ」は漢数字の「一つの」「一つずつ」と同じ扱い。「ひとつまみ」
  「ひとつき」「ひとりでに」「やっつける」「むっつり」と「一人ひとり」の「ひとり」は数にしない。「とお」は「通る」「遠い」
  などと分けられないので取らない（限界）。
- 「一つずつ」の相手の文の語: 一斉、一気に、いっぺんに、同時、並列、並行、一括、一度に を「まとめて」とそろえてから比べる
  （同じ組の語どうしの言い換えを、新しく出た語にしない）。「一つずつ」の 複数・いくつでも・いくつも と、「一つの」の 別々 は、
  動詞や名詞のすぐ前に出るときだけ数える（「一つずつ開き、何か所も直す → 開く。複数の箇所を直す」は数の主張を変えない）。
- 否定対比の逆転: A を下げる言い方に、その次、二番手、二番目、脇に置く、脇役、添え物、おまけ、どうでも、そのあとに回す を
  足した（「品質が最優先で、締め切りはその次です」を逆転にしない）。
- 見出しと「Aは使わず」「Aはせず」の否定対比: A の節の前の節が重みの語だけの句（まず、まずは、第一に、何より、何よりも、
  最優先で、最優先として、一番に）なら、A の節の重みとして見る（「## まず、手作業で回す」を拾う）。
- 主題の句（最優先は、大事なのは、）のあとに A を減らす言い方を置いた正しい推敲（最優先は、手作業を減らして自動化で回すこと）は、
  逆転の候補に出る（限界）。原文で肯定した側の語が同じ文に出れば候補にしない形は、B も出る本当の逆転を見逃すので入れていない。
- 限界として固定する形（直さない）: 回数を言わなくした「月一回 → 毎月」と、「一人十分の量 → 一人あたり十分な量」は消えた数値に
  なる。見出しと「使わず・せず」で重みの語が A と別の節にある逆転、文を分け名詞を言い換えて数を変えた推敲、2つの文をまとめた
  推敲で組にならなかった文の「一つずつ」は拾わない。重みの語だけの句のあとに A を減らす言い方を置いた推敲（## まず、手作業を
  減らす）は、正しくても逆転の候補に出る。
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


def number_risks(before, after, doc_type=None):
    return [(risk["subkind"], risk["detail"]["removed"], risk["detail"]["added"])
            for risk in result_of(before, after, doc_type)["meaning_risks"] if risk["kind"] == "number"]


def reversal_words(before, after, doc_type=None):
    return [risk["detail"]["word"] for risk in result_of(before, after, doc_type)["meaning_risks"]
            if risk["kind"] == "contrast_reversal"]


def unsupported_numbers(final, materials):
    result = yomiyasu_diff.ground(final + "\n", [material + "\n" for material in materials])
    return [risk["detail"]["text"] for risk in result["meaning_risks"] if risk["subkind"] == "number"]


def values(text):
    return [(number["value"], number["unit"]) for number in yomiyasu_diff.extract_numbers(text)]


# ---- 算用数字の「1つ」は、漢数字の「一つ」と同じ扱い ----
class ArabicOneLikeKanjiTest(unittest.TestCase):
    NOT_FOUND = (
        ("もう1つの利点は、設定が1か所で済むことです。", "設定が1か所で済むのも利点です。", "article"),
        ("1つの目安として、応答は200ミリ秒以内を狙います。", "目安として、応答は200ミリ秒以内を狙います。", "article"),
        ("ファイルを1つずつ開いて確認します。", "ファイルを順に開いて確認します。", "article"),
        ("もう1つ、READMEの誤字も直しました。", "あわせて、READMEの誤字も直しました。", "pr"),
        ("注意点がもう1つあります。退室の前に窓を閉めてください。", "また、退室の前に窓を閉めてください。", None),
        ("1つの選択肢として、キャッシュを置く案もある。", "選択肢として、キャッシュを置く案もある。", None),
        ("職人が1つずつ手作りしています！", "職人が手作りしています！", "promo"),
        ("エラーを1つずつ潰していきました。もう1つ、注意点があります。",
         "エラーを順に潰していきました。さらに、注意点があります。", None),
        ("1つのメソッドに混在しています。", "同一のメソッド内に記述されています。", None),
        ("手順を確かめる。", "手順を1つずつ確かめる。", None),
        ("1つの画面で確かめる。", "画面で確かめる。", None),
        ("ファイルを１つずつ送る。", "ファイルを送る。", None),
        ("テストを1つずつ見直し、不要なものを消しました。", "テストを順に見直し、不要なものを消しました。", "pr"),
    )
    FOUND = (
        ("登録できる端末は1つのみです。", "登録できる端末は複数でもかまいません。", [("lost", ["1つ"], [])]),
        ("処理を1つずつ行う。", "処理を並列で行う。", [("lost", ["1つ"], [])]),
        ("設定は1つの画面で変える。", "設定は複数の画面で変える。", [("lost", ["1つ"], [])]),
        ("設定は1つのファイルにまとめる。", "設定は複数のファイルに分ける。", [("lost", ["1つ"], [])]),
        ("ファイルを1つずつ送る。", "ファイルをまとめて送る。", [("lost", ["1つ"], [])]),
        ("2つのサービスに分ける。", "1つのサービスにまとめる。", [("replaced", ["2つ"], ["1つ"])]),
        ("1つの方法がある。", "3つの方法がある。", [("replaced", ["1つ"], ["3つ"])]),
        ("候補を1つもしくは2つ選ぶ。", "候補を2つ選ぶ。", [("lost", ["1つ"], [])]),
        ("方法は1つだ。", "方法は3つだ。", [("replaced", ["1つ"], ["3つ"])]),
    )

    def test_arabic_one_without_a_quantity_claim_is_not_a_candidate(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after, doc_type), [])
                self.assertEqual(result_of(before, after, doc_type)["fail_on_meaning_risk_count"], 0)

    def test_changed_quantity_is_still_a_candidate(self):
        for before, after, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)

    def test_new_writing(self):
        """新規作成の照合: 「1つのみ」は資料にない数値の候補。「もう1つ」「1つずつ」は出さない。"""
        self.assertEqual(unsupported_numbers("添付できるファイルは1つのみです。", ["添付できるファイルの決まり。"]), ["1つ"])
        self.assertEqual(unsupported_numbers("手順を1つずつ確かめます。もう1つ、注意があります。", ["手順の一覧。"]), [])


# ---- 平仮名の数 ----
class HiraganaNumberTest(unittest.TestCase):
    NOT_FOUND = (
        ("角砂糖を1つ入れる。", "角砂糖をひとつ入れる。", None),
        ("一人で受付を担当します。", "ひとりで受付を担当します。", None),
        ("少年一人が駆け寄ってきた。", "少年がひとり駆け寄ってきた。", "essay"),
        ("青年二人が店に入ってきた。", "青年がふたり店に入ってきた。", "essay"),
        ("毎日一人で散歩をする。", "毎日ひとりで散歩をする。", "essay"),
        ("去年一人暮らしを始めた。", "去年、ひとり暮らしを始めた。", "essay"),
        ("当日一人で受付を担当します。", "当日はひとりで受付を担当します。", None),
        ("見張りは一人で十分だ。", "見張りはひとりで足りる。", None),
        ("二つの案がある。", "ふたつの案がある。", None),
        ("三つの案がある。", "みっつの案がある。", None),
        ("箱が四つある。", "箱がよっつある。", None),
        ("玉を五つ並べる。", "玉をいつつ並べる。", None),
        ("石を六つ拾った。", "石をむっつ拾った。", "essay"),
        ("星が七つ見える。", "星がななつ見える。", "essay"),
        ("皿を八つ出す。", "皿をやっつ出す。", None),
        ("鐘が九つ鳴った。", "鐘がここのつ鳴った。", "essay"),
        ("角砂糖をひとつ入れる。", "角砂糖を一つ入れる。", None),
        ("ふたりで話した。", "二人で話した。", "essay"),
        # 平仮名の数を消しただけ・数量を主張しない形
        ("ひとりで作業した。", "作業した。", None),
        ("エラーはひとつも出ませんでした。", "エラーは出ませんでした。", None),
        ("もうひとつ、注意点があります。", "さらに、注意点があります。", None),
        ("設定をひとつひとつ確かめる。", "設定を順に確かめる。", None),
        ("ひとつの画面で確かめる。", "画面で確かめる。", None),
        ("手順をひとつずつ確かめる。", "手順を順に確かめる。", None),
    )
    FOUND = (
        ("角砂糖をひとつ入れる。", "角砂糖をふたつ入れる。", [("replaced", ["ひとつ"], ["ふたつ"])]),
        ("ひとりで担当する。", "ふたりで担当する。", [("replaced", ["ひとり"], ["ふたり"])]),
        ("受付は3人で担当します。", "受付はひとりで担当します。", [("replaced", ["3人"], ["ひとり"])]),
        ("ひとりで担当する。", "二人で担当する。", [("replaced", ["ひとり"], ["二人"])]),
        ("ふたつの案がある。", "一つの案がある。", [("replaced", ["ふたつ"], ["一つ"])]),
        ("みっつの案がある。", "5つの案がある。", [("replaced", ["みっつ"], ["5つ"])]),
        # 「ひとつずつ」「ひとつの」は「一つずつ」「一つの」と同じ
        ("ファイルをひとつずつ処理します。", "ファイルをまとめて処理します。", [("lost", ["ひとつ"], [])]),
        ("ひとつのインスタンスで動かす。", "複数のインスタンスで動かす。", [("lost", ["ひとつ"], [])]),
    )

    def test_same_value_in_hiragana_is_not_a_candidate(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after, doc_type), [])
                self.assertEqual(result_of(before, after, doc_type)["fail_on_meaning_risk_count"], 0)

    def test_changed_value_in_hiragana_is_a_candidate(self):
        for before, after, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), expected)

    def test_values(self):
        cases = (
            ("角砂糖をひとつ入れる。", [("1", "つ")]),
            ("ふたりで話した。", [("2", "人")]),
            ("みっつ、よっつ、いつつ、むっつ、ななつ、やっつ、ここのつ。",
             [("3", "つ"), ("4", "つ"), ("5", "つ"), ("6", "つ"), ("7", "つ"), ("8", "つ"), ("9", "つ")]),
            ("ひとつひとつ確かめる。", [("1", "つ"), ("1", "つ")]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(values(text), expected)

    def test_words_that_are_not_numbers(self):
        for text in ("塩をひとつまみ入れる。", "ひとつかみの砂。", "ひとつきかけて作った。", "ドアがひとりでに開いた。",
                     "敵をやっつけた。", "彼はむっつりしていた。", "一人ひとりに配る。", "いつつくるのか。", "ひとつながりの道。"):
            with self.subTest(text=text):
                self.assertEqual(values(text), [])

    def test_new_writing(self):
        """新規作成の照合: 平仮名の数は数量を主張しない値なので、資料にない数値の候補にしない。資料の「1つ」と最終稿の「ひとつ」は
        同じ値。"""
        self.assertEqual(unsupported_numbers("角砂糖をひとつ入れる。", ["紅茶の淹れ方。"]), [])
        result = yomiyasu_diff.ground("角砂糖をひとつ入れる。\n", ["角砂糖を1つ入れる。\n"])
        self.assertEqual([item["classification"] for item in result["items"] if item["kind"] == "number"],
                         ["from_materials"])


# ---- 「一つずつ」の相手の文の語をそろえ、複数・別々はすぐ前だけで見る ----
class QuantityWordAlignTest(unittest.TestCase):
    NOT_FOUND = (
        # 同じ組の語の言い換え（まとめて、一度に、同時に、一括 → 一斉に、一気に、並列）
        ("ファイルを一つずつ確認し、結果はまとめて送る。", "ファイルを確認する。結果は一斉に送る。"),
        ("メールは一つずつ開いて読み、返信は一度に送る。", "メールは開いて読む。返信は一気に送る。"),
        ("ページを一つずつ見直し、直しは同時に反映する。", "ページを見直す。直しは一斉に反映する。"),
        ("テストを一つずつ流し、結果は一括で送る。", "テストを流す。結果は並列で送る。"),
        # 複数・別々が「一つずつ」の動詞や「一つの」の名詞にかからない
        ("ファイルを一つずつ開き、何か所も直す。", "ファイルを開く。複数の箇所を直す。"),
        ("書類を一つずつ確認し、何人かで見直す。", "書類を確認する。複数人で見直す。"),
        ("一つの部屋で、二つの班が交代で作業する。", "部屋で、二つの班が別々の時間に作業する。"),
        ("一つの部屋で、二つの班が交代で作業する。", "部屋を決める。二つの班が別々の時間に作業する。"),
    )
    FOUND = (
        ("ファイルを一つずつ処理します。", "ファイルをまとめて処理します。"),
        ("ファイルを一つずつ送る。", "ファイルを一斉に送る。"),
        ("ファイルを一つずつ送る。", "ファイルを一気に送る。"),
        ("ファイルを一つずつ送る。", "ファイルをいっぺんに送る。"),
        ("ジョブを一つずつ流す。", "ジョブを並列に流す。"),
        ("ジョブを一つずつ流す。", "ジョブを並行して流す。"),
        ("リクエストを一つずつ送る。", "リクエストを同時に送る。"),
        ("データを一つずつ取り込む。", "データを一括で取り込む。"),
        ("データを一つずつ取り込む。", "データを一度に取り込む。"),
        ("候補を一つずつ選ぶ。", "候補を複数選ぶ。"),
        ("申請を一つずつ受け付けます。", "申請を複数件受け付けます。"),
        ("申請を一つずつ受け付けます。", "申請を複数受け付けます。"),
        ("タブを一つずつ開ける。", "タブをいくつでも開ける。"),
        ("設定は一つのファイルに書く。", "設定は別々のファイルに書く。"),
        ("項目を一つずつ確認する。結果は記録する。", "項目をまとめて確認し、結果を記録する。"),
        ("一つのインスタンスで動かす。", "複数のインスタンスで動かす。"),
        ("申請を一つずつ受け付けます。", "申請を複数の窓口で受け付けます。"),
        # 元の文の別の節にも同じ組の語（同時に）がある。語をそろえても、「一つずつ」の動詞の前の「まとめて」（目的語を挟む）で拾う
        ("ファイルを一つずつ確認し、同時に記録する。", "まとめてファイルを確認し、記録する。"),
    )

    def test_aligned_or_unrelated_words_are_not_a_change(self):
        for before, after in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [])
                self.assertEqual(result_of(before, after)["fail_on_meaning_risk_count"], 0)

    def test_changed_quantity_is_still_found(self):
        for before, after in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(number_risks(before, after), [("lost", ["一つ"], [])])


# ---- 否定対比の逆転: A を下げる言い方 ----
class DemoteWordTest(unittest.TestCase):
    NOT_FOUND = (
        ("見た目ではなく中身で選ぶ。", "一番大事なのは中身で、見た目は脇役だ。", "essay"),
        ("使い方ではなく考え方を重視した。", "考え方を一番に重視し、使い方は脇に置いた。", "article"),
        ("締め切りではなく品質を優先します。", "品質が最優先で、締め切りはその次です。", None),
        ("見た目ではなく中身を大事にする。", "大事にするのは中身で、見た目は添え物だ。", "essay"),
        ("問い合わせではなく申し込みを優先してください。", "申し込みを最優先にし、問い合わせは二番手としてください。", None),
        ("問い合わせではなく申し込みを優先して返信してください。",
         "申し込みへの返信を最優先にし、問い合わせはその次にしてください。", None),
        ("使い方ではなく目的を先に説明することを重視する。", "目的を先に説明することを重視し、使い方の説明はそのあとに回す。", None),
        ("彼が気にしたのは、見た目ではなく中身だった。", "彼が一番気にしたのは中身で、見た目はどうでもよかった。", "essay"),
        ("外見ではなく中身で選ぶ。", "一番大事なのは中身で、外見は脇役だ。", "essay"),
        ("手順ではなく考え方を重視した。", "考え方を一番に重視し、手順は脇に置いた。", None),
        ("納期ではなく品質を優先します。", "品質が最優先で、納期はその次です。", None),
        ("支払い期限ではなく、請求額の正しさを最優先で確かめる。", "請求額の正しさを最優先で確かめ、支払期限はその次にする。", None),
        ("速さではなく正しさを優先する。", "正しさを最優先にし、速さは二番目にする。", None),
        ("景品ではなく味で選んでほしい。", "何より味で選んでほしく、景品はおまけだ。", "promo"),
        ("## ツールではなく習慣から変える", "## まず、ツールは脇に置く", "slides"),
    )
    FOUND = (
        ("見た目ではなく中身で選ぶ。", "見た目で選ぶことが一番大事だ。", ["見た目"]),
        ("締め切りではなく品質を優先します。", "締め切りを最優先にします。", ["締め切り"]),
        ("締め切りではなく品質を優先します。", "締め切りを最優先にし、品質はその次です。", ["締め切り"]),
        ("ツールではなく習慣を最優先にする。", "ツールを最優先にし、習慣は二番目に見る。", ["ツール"]),
        ("コストではなく品質を重視する。", "コストを重視し、その次に品質を見る。", ["コスト"]),
        ("外見ではなく中身で選ぶ。", "外見で選ぶのが一番で、中身はおまけだ。", ["外見"]),
        # 読点のない「Aを重視してその次に B」の「その次」は A を下げていない
        ("コストではなく品質を重視する。", "コストを重視してその次に品質を見る。", ["コスト"]),
    )

    def test_demoted_a_is_not_a_reversal(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_reversal_is_still_found(self):
        for before, after, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after), expected)


# ---- 見出しと「使わず」「せず」: 重みの語だけの前の節 ----
class WeightOnlyClauseTest(unittest.TestCase):
    FOUND = (
        ("## 手作業ではなく自動化で回す", "## まず、手作業で回す", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## 第一に、手作業で回す", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## 何より、手作業で回すこと", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## 最優先として、手作業で回す", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## 最優先で、手作業で回す", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## 一番に、手作業で回す", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## まずは、手作業で回す", "slides", ["手作業"]),
        ("外部の認証は使わず、自前の認証を作る。", "何よりも、外部の認証を使う。", None, ["外部"]),
        ("外部の認証は使わず、自前の認証を作る。", "第一に、外部の認証を使う。", None, ["外部"]),
        ("グローバル変数は使わず、引数で渡す。", "まず、グローバル変数で渡す。", None, ["グローバル", "変数"]),
        ("手動の切り替えはせず、自動で切り替える。", "最優先として、手動の切り替えを行う。", None, ["手動"]),
    )
    NOT_FOUND = (
        ("## ツールではなく習慣から変える", "## まず習慣、ツールはその次", "slides"),
        ("## 手作業ではなく自動化で回す", "## まず、自動化で回し、手作業はその次", "slides"),
        ("外部の認証は使わず、自前の認証を作る。", "まず、自前の認証を作り、外部の認証は使わない。", None),
        ("## 手作業ではなく自動化で回す", "## まず、手作業はやめる", "slides"),
        ("今日は作業はせず、まず休む。", "今日はまず休み、作業は明日にする。", None),
        ("外部委託はせず、まず社内で作る。", "まず社内で作り、外部委託はその次にする。", None),
    )

    def test_weight_only_clause_before_a(self):
        for before, after, doc_type, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), expected)

    def test_a_kept_behind_is_not_a_reversal(self):
        for before, after, doc_type in self.NOT_FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])


# ---- 主題の句の重みの語: 逆転を拾うことと、A を減らす言い方の正しい推敲（限界）----
class TopicPhraseTest(unittest.TestCase):
    """「最優先は、」「大事なのは、」のあとで A を肯定した逆転は拾う。原文で肯定した側（AではなくB の B）の語が同じ文に出れば
    候補にしない形を試したが、B も出る本当の逆転（「最優先は、手作業で回し、自動化も進めること」「大事なのは、会議で決めて
    文書で知らせること」）を見逃すので入れていない。そのため、主題の句のあとに A を減らす言い方を置いた正しい推敲は、
    逆転の候補に出る（限界）。逆転は --fail-on に数えない。"""
    FOUND = (
        ("## 自動化ではなく手作業で確かめる", "## 最優先は、自動化で確かめること", "slides", ["自動化"]),
        ("クラウドは使わず、社内のサーバーで動かします。", "一番大事なのは、クラウドで動かすことです。", None, ["クラウド"]),
        ("外部サービスは使わず、社内で作る。", "最優先は、外部サービスを使うことだ。", None, ["外部", "サービス"]),
        ("## 速さではなく正確さを優先する", "## 目的は、速さを上げること", "slides", ["速さ"]),
        ("## コストではなく品質を重視する", "## 大事なのは、コストを下げること", "slides", ["コスト"]),
        ("## 新機能ではなく安定性を重視する", "## 重視するのは、新機能の追加", "slides", ["新機能"]),
        ("## 速さではなく正確さを優先する", "## 優先するのは、速さ", "slides", ["速さ"]),
        # 原文で肯定した側の語も出るが、A を最優先にした逆転
        ("## 手作業ではなく自動化で回す", "## 最優先は、手作業で回し、自動化も進めること", "slides", ["手作業"]),
        ("## 手作業ではなく自動化で回す", "## 最優先は、手作業で回して自動化も進めること", "slides", ["手作業"]),
        ("クラウドは使わず、社内のサーバーで動かします。", "一番大事なのは、クラウドで動かし、社内のサーバーも残すことです。",
         None, ["クラウド"]),
        ("## 会議ではなく文書で決める", "## 大事なのは、会議で決めて文書で知らせること", "slides", ["会議"]),
    )
    LIMITS = (
        ("## 手作業ではなく自動化で回す", "## 最優先は、手作業を減らして自動化で回すこと", "slides", ["手作業"]),
        ("表計算は使わず、専用の画面で入力します。", "最優先は、表計算を減らして専用の画面で入力することです。", None, ["表計算"]),
        ("## 会議ではなく文書で決める", "## 一番大事なのは、会議を最小限にして文書で決めること", "slides", ["会議"]),
        ("## 手作業ではなく自動化で回す", "## 最優先は、手作業から自動化へ移すこと", "slides", ["手作業"]),
        ("残業はせず、時間内に終えることを優先します。", "優先するのは、残業を減らして時間内に終えることです。", None, ["残業"]),
        ("## 会議ではなく文書で決める", "## 大事なのは、会議の数を減らして文書で決めること", "slides", ["会議"]),
    )

    def test_reversal_after_topic_phrase(self):
        for before, after, doc_type, expected in self.FOUND:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), expected)

    def test_known_limit_reduce_after_topic_phrase(self):
        for before, after, doc_type, expected in self.LIMITS:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), expected)
                self.assertEqual(result_of(before, after, doc_type)["fail_on_meaning_risk_count"], 0)


# ---- 限界として固定する形（直さない）----
class KnownLimitsRound4Test(unittest.TestCase):
    def test_number_limits(self):
        # 回数を言わなくした書き換えと、「一人十分の量」の「十分」は消えた数値になる
        self.assertEqual(number_risks("点検は月一回行う。", "点検は毎月行う。"), [("lost", ["一回"], [])])
        self.assertEqual(number_risks("一人十分の量を用意する。", "一人あたり十分な量を用意する。"), [("lost", ["十分"], [])])
        # 数量を主張しない「もう1つ」を足した書き換えと、「1つの」を消しただけの書き換えは、候補にならない（漢数字と同じ）
        self.assertEqual(number_risks("理由がある。", "もう1つ理由がある。"), [])
        self.assertEqual(number_risks("設定は1つのファイルに書く。", "設定はファイルに書く。"), [])
        self.assertEqual(unsupported_numbers("新しい画面を1つの画面にまとめました。", ["新しい画面を作る。"]), [])
        # 文を分け、名詞を言い換えて数を変えた推敲は拾わない
        self.assertEqual(number_risks("ログは一つのファイルに出す。", "ログを出す。出力先は複数に分ける。"), [])
        self.assertEqual(number_risks("申請は一つの窓口で受ける。", "申請を受ける。受付は複数の場所で行う。"), [])
        # 2つの文をまとめた推敲で、組にならなかった文の「一つずつ」は拾わない
        self.assertEqual(number_risks("処理は一つずつ行う。同時に二つの画面を開かない。",
                                      "処理は同時に行い、二つの画面を開かない。"), [])
        # 「とお」は数にしない
        self.assertEqual(values("とおの指で数える。"), [])

    def test_reversal_limits(self):
        """見出しと「使わず・せず」で、重みの語が A と別の節にある逆転と、A を足しただけの書き換えは拾わない。"""
        cases = (
            ("## 速さではなく正しさを優先する", "## 速さ、それが最優先", "slides"),
            ("## 手作業ではなく自動化で回す", "## 手作業で回す、まずはそこから", "slides"),
            ("## キャッシュではなく索引で速くする", "## 目的は速くすること、手段はキャッシュ", "slides"),
            ("社外のツールは使わず、社内の仕組みだけで回すのが目的です。", "社外のツールを使い、社内の仕組みでも回すのが目的です。",
             None),
            ("外部の認証は使わず、自前の認証を最優先で作る。", "自前の認証を最優先で作り、外部の認証も使う。", None),
            ("グローバル変数は使わず、引数で渡すことを優先しました。", "引数で渡すことを優先しつつ、グローバル変数も使いました。",
             None),
        )
        for before, after, doc_type in cases:
            with self.subTest(before=before, after=after):
                self.assertEqual(reversal_words(before, after, doc_type), [])

    def test_reduce_after_weight_only_clause(self):
        """重みの語だけの句のあとに A を減らす言い方を置いた推敲は、正しくても逆転の候補に出る（「Aを減らすことを最優先に
        する」を逆転として拾う決まりと同じ形）。逆転は --fail-on に数えない。"""
        before, after = "## 手作業ではなく自動化で回す", "## まず、手作業を減らす"
        self.assertEqual(reversal_words(before, after, "slides"), ["手作業"])
        self.assertEqual(result_of(before, after, "slides")["fail_on_meaning_risk_count"], 0)


if __name__ == "__main__":
    unittest.main()
