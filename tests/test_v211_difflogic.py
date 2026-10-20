#!/usr/bin/env python3
"""v2.1.1: diff の選ぶ範囲（どれか一つ ↔ 全部）と、関連から因果への言い方の変化の試験。

「AまたはBのどちらか」を「AとBの両方」に書き換えて文の真偽が逆になっても、意味が変わる恐れが0件になっていた不具合と、
「関連がある」「相関がある」を「因果関係がある」「原因である」「引き起こす」に強めても、語の差分にしか出なかった不具合を防ぐ。
どちらも --fail-on=meaning-risk に数える。同じ側の中の言い換え（または → か、どちらか → いずれか、両方 → どちらも）、
原文にもともと因果の言い方がある文、「関連」→「関係」の言い換え、関連の言い方のない原文では出さない。
関連を打ち消す原文（関係はありません）、名詞を修飾する関連の語（関係のある部署、相関係数）、原文の広い因果の言い方
（〜による、影響する、〜のため）、選ぶものではない名詞に掛かる「すべての項目」、どれでもよい言い方（どちらでも、AでもBでも）、
問いの「か」（設定が有効か管理者に確認する）でも出さない。
例の文は、このファイルで作った合成の文。
"""

from pathlib import Path
from unittest import mock
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


NEW_KINDS = ("choice", "causality")


def run(before, after, doc_type=None):
    return yomiyasu_diff.diff(before + "\n", after + "\n", doc_type=doc_type)


def kinds(result):
    return [(risk["kind"], risk["subkind"]) for risk in result["meaning_risks"]]


def new_kinds(result):
    return [k for k in kinds(result) if k[0] in NEW_KINDS]


# 検出すべき例: (元, 後, (kind, subkind))
SHOULD_DETECT = [
    # 依頼の組（どれか一つ → 全部）と、その逆
    ("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。", ("choice", "one_to_all")),
    ("AとBの両方を選ぶ必要がある。", "AまたはBのどちらかを選ぶ必要がある。", ("choice", "all_to_one")),
    ("AとBの両方を選ぶ。", "AかBを選ぶ。", ("choice", "all_to_one")),
    ("申請書か委任状のどちらかを提出する。", "申請書と委任状をどちらも提出する。", ("choice", "one_to_all")),
    ("いずれかの条件を満たせば通知する。", "すべての条件を満たせば通知する。", ("choice", "one_to_all")),
    ("すべての条件を満たせば通知する。", "いずれかの条件を満たせば通知する。", ("choice", "all_to_one")),
    ("メールもしくは電話で連絡する。", "メールと電話の双方で連絡する。", ("choice", "one_to_all")),
    ("どちらかの鍵が使えない。", "どちらの鍵も使えない。", ("choice", "one_to_all")),
    ("AとBはともに必須だ。", "AかBが必須だ。", ("choice", "all_to_one")),
    # 依頼の3組（関連・相関 → 因果）
    ("この施策と売上の増加には関連がある。", "この施策と売上の増加には因果関係がある。", ("causality", "relation_to_cause")),
    ("この施策と売上の増加には関連がある。", "この施策が売上の増加の原因である。", ("causality", "relation_to_cause")),
    ("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。", ("causality", "relation_to_cause")),
    ("気温と来店数は関係している。", "気温の変化によって来店数の増減が生じる。", ("causality", "relation_to_cause")),
    ("睡眠時間と集中力は結びついている。", "睡眠不足のせいで集中力が落ちる。", ("causality", "relation_to_cause")),
]

# 検出してはいけない例（種類なしでも formal でも、選ぶ範囲と因果の候補を出さない）
SHOULD_NOT_DETECT = [
    # 同じ側の中の言い換え
    ("AまたはBを選ぶ。", "AかBを選ぶ。"),
    ("どちらかを選ぶ。", "いずれかを選ぶ。"),
    ("AまたはBのどちらかを選ぶ。", "AかBのいずれか一方を選ぶ。"),
    ("両方を選ぶ。", "どちらも選ぶ。"),
    ("いずれの項目も確認する。", "すべての項目を確認する。"),
    ("AとBの両方を選ぶ。", "AもBも選ぶ。"),
    # 両方の言い方を並べた書き換え
    ("AまたはBを選ぶ。", "AかBのどちらか、または両方を選ぶ。"),
    # 問いの「か」、何か、数のあとの「か月」、「どちらかといえば」は、どれか一つの言い方にしない
    ("どの設定が必要か確認する。", "すべての設定を確認する。"),
    ("何か問題があれば連絡する。", "すべての問題を連絡する。"),
    ("3か月ごとに見直す。", "すべての項目を3か月ごとに見直す。"),
    ("どちらかといえば速い。", "どれも速い。"),
    ("どの値が正しいか判断が必要だ。", "すべての値を確かめる必要がある。"),
    # 原文にもともと因果の言い方がある
    ("この施策と売上の増加には関連があり、増加の原因と考えられている。", "この施策が売上の増加の原因と考えられている。"),
    ("設定の誤りと障害には関連があり、障害は設定の誤りが原因だった。", "障害は設定の誤りが原因だった。"),
    ("喫煙と肺がんには因果関係がある。", "喫煙は肺がんの原因になる。"),
    # 「関連」→「関係」の言い換え
    ("この施策と売上の増加には関連がある。", "この施策と売上の増加には関係がある。"),
    ("気温と来店数には相関がある。", "気温と来店数には相関関係がある。"),
    # 原文に関連の言い方がない
    ("この施策の後に売上が増えた。", "この施策が売上の増加の原因である。"),
    ("関連する設定を変更すると、表示が崩れた。", "関連する設定の変更が、表示の崩れの原因だった。"),
    # 因果を弱めた向きは出さない
    ("喫煙が肺がんを引き起こす。", "喫煙と肺がんには相関がある。"),
]


# 出してはいけない例（印の当て方を絞った分）
NOT_DETECT_NARROWED = [
    # 原文が関連を打ち消している（関係はありません、相関は見られなかった）
    ("この障害と更新には関係はありません。", "この障害の原因は更新ではありません。"),
    ("この障害と今回の更新は関係ありません。", "今回の更新は、この障害の原因ではありません。"),
    ("気温と来店数に相関は見られなかった。", "気温は来店数の要因ではなかった。"),
    ("気温と来店数に関連が見られなかった。", "気温は来店数の要因ではなかった。"),
    ("両者に相関は認められない。", "両者に因果関係はない。"),
    ("両者の間に関連は認められませんでした。", "どちらも原因ではありませんでした。"),
    ("この変更と障害に関係があるかを調べる。", "この変更が障害の原因かを調べる。"),
    # 関連の語が名詞を修飾する形や複合語（関係のある部署、関連性の高い記事、相関係数）
    ("関係のある部署に、障害の理由を報告する。", "関係のある部署に、障害の原因を報告する。"),
    ("関係がある部署に、障害の経緯を報告する。", "関係がある部署に、障害の原因を報告する。"),
    ("関連性の高い記事を並べ、閲覧数が伸びた理由を分析する。", "関連性の高い記事を並べ、閲覧数が伸びた要因を分析する。"),
    ("相関係数を計算し、売上が落ちた理由を調べる。", "相関係数を計算し、売上が落ちた要因を調べる。"),
    ("相関分析で、売上が落ちた理由を探る。", "相関分析で、売上が落ちた要因を探る。"),
    ("関連している設定を見直し、理由を調べる。", "関連している設定を見直し、原因を調べる。"),
    ("関係者が集まり、不具合の理由を話し合った。", "関係者が集まり、不具合の原因を話し合った。"),
    ("関連記事を見直し、閲覧数が落ちた理由を調べる。", "関連記事を見直し、閲覧数が落ちた原因を調べる。"),
    # 原文にもともと因果の言い方がある（〜による、〜で起きた、〜のため、影響する、影響がある、〜から生じた、理由）
    ("この遅延は設定ミスによるもので、前回の障害とも関係がある。", "この遅延の原因は設定ミスで、前回の障害とも関係がある。"),
    ("停電で起きた障害は、今回の遅延と関連がある。", "停電が原因の障害は、今回の遅延と関連がある。"),
    ("雨のため来店数が減り、気温とも相関があった。", "雨が原因で来店数が減り、気温とも相関があった。"),
    ("気温は売上に影響し、両者には相関がある。", "気温は売上に影響を与え、両者には相関がある。"),
    ("気温は来店数と関係があり、売上にも影響がある。", "気温は来店数と関係があり、売上にも影響を与える。"),
    ("この遅延は設定ミスから生じたもので、前回の障害とも関係がある。", "この遅延の原因は設定ミスで、前回の障害とも関係がある。"),
    ("遅延の理由は設定ミスで、前回の障害とも関連がある。", "遅延の原因は設定ミスで、前回の障害とも関連がある。"),
    ("雨で来店数が減ったので、天気と売上には関連がある。", "雨が来店数の減少の原因なので、天気と売上には関連がある。"),
    # 文の別の所の「すべて」が、選ぶものではない別の名詞に掛かる（全項目 → すべての項目、漏れなく → すべて）
    ("管理画面またはCLIから、全項目を設定できる。", "管理画面とCLIのどちらからでも、すべての項目を設定できる。"),
    ("管理画面またはCLIから、全項目を設定できる。", "管理画面かCLIから、すべての項目を設定できる。"),
    ("申請はWebまたは郵送で受け付け、書類は漏れなくそろえてください。", "申請はWebや郵送で受け付け、書類はすべてそろえてください。"),
    ("申請はWebまたは郵送で受け付け、書類は漏れなくそろえてください。", "申請はWeb・郵送で受け付けます。書類はすべてそろえてください。"),
    ("AまたはBで申し込めます。", "AやBで、すべての手続きを申し込めます。"),
    ("設定を保存するか、またはキャンセルしてすべての変更を破棄する。", "設定を保存するか、キャンセルしてすべての変更を破棄する。"),
    # どれを選んでもよい言い方（どちらでも、いずれでも、どちらからでも、AでもBでも）は、どれか一つの側に残った言い方
    ("WebまたはCLIで設定できる。", "WebでもCLIでも設定できる。"),
    ("WebまたはCLIで設定できる。", "WebとCLIのどちらでも設定できる。"),
    ("WebまたはCLIで設定できる。", "WebとCLIのいずれでも設定できる。"),
    ("WebまたはCLIで設定できる。", "WebとCLIのどちらからでも設定できる。"),
    # 問いの「か」（〜が有効か管理者に確認する、〜が最新版か担当部署に確かめる）
    ("両方の設定が有効になっているかを、管理者に確認する。", "二つの設定が有効か管理者に確認する。"),
    ("すべての端末で、最新版かどうかを確かめる。", "各端末が最新版か情報システム部に確かめてもらう。"),
    ("すべてのサーバーが正常に動いているかを、担当者に確認する。", "全サーバーが正常か担当者に確認する。"),
    ("すべての項目について、対応できるかを担当者に確認する。", "各項目が対応可能か担当者に確認する。"),
    ("すべての設定が有効かどうかを確認する。", "各設定が有効か現場で判断する。"),
    # 同じ側の中の言い換え
    ("どちらも必須です。", "両方とも必須です。"),
    ("鍵は二つとも必要です。", "鍵は両方とも必要です。"),
    ("AとBの両方に反映する。", "AにもBにも反映する。"),
    ("本番環境と検証環境の両方に反映する。", "本番環境にも検証環境にも反映する。"),
    ("A、B、Cのすべてに当てはまる。", "A、B、Cのどれにも当てはまる。"),
    ("AとBのいずれも必須です。", "A、Bはどちらも必須です。"),
    ("どちらとも言えない。", "どちらか一方とは決められない。"),
    # 選ぶ範囲は、足した文の全部の言い方と組にしない（足した文の「どちらも」「すべて」は、選ぶものを指すとは限らない）
    ("AまたはBを選ぶ。", "AやBを選ぶ。どちらも無料です。"),
    ("申請はWebまたは郵送で受け付けます。", "申請はWebや郵送で受け付けます。書類はすべてを同封してください。"),
    # 元の範囲にどれか一つの言い方があれば、全部の言い方が消えても all_to_one にしない（CかD → CかDのいずれか の言い換え）
    ("AとBの両方を入れ、CかDを選ぶ。", "AやBを入れ、CかDのいずれかを選ぶ。"),
    # one_to_all は数で比べる（両方 → AもBも は同じ数）
    ("AとBの両方を入れ、CかDを選ぶ。", "AもBも入れ、CやDを選ぶ。"),
]

# 検出すべき例（印を足した分と、範囲の比べ方を直した分）
DETECT_ADDED = [
    # 選ぶ句と関係のない「すべての機能」「全ての利用者」「すべてを保存し」が同じ文にあっても出す
    ("AまたはBのいずれかを選ぶと、すべての機能が使える。", "AとBの両方を選ぶと、すべての機能が使える。", ("choice", "one_to_all")),
    ("全ての利用者は、AまたはBのどちらかを選ぶ。", "全ての利用者は、AとBの両方を選ぶ。", ("choice", "one_to_all")),
    ("すべてを保存し、AまたはBを選ぶ。", "すべてを保存し、AとBの両方を選ぶ。", ("choice", "one_to_all")),
    # 全部の言い方（AもBも の項に「の」を含む形、AにもBにも、二つとも、どちらとも）
    ("申請には、本人確認書類または住民票の写しが必要です。", "申請には、本人確認書類も住民票の写しも必要です。", ("choice", "one_to_all")),
    ("本番環境または検証環境に反映する。", "本番環境にも検証環境にも反映する。", ("choice", "one_to_all")),
    ("鍵は二つとも必要です。", "鍵はどちらか一つあればよい。", ("choice", "all_to_one")),
    ("鍵は2つとも必要です。", "鍵はどちらか一つあればよい。", ("choice", "all_to_one")),
    ("AとBのどちらとも必要です。", "AかBのどちらかが必要です。", ("choice", "all_to_one")),
    ("今回も前回の結果も確認した。", "今回か前回の結果を確認した。", ("choice", "all_to_one")),
    # 選ぶ「か」は、確かめる言い方が続いても残す（木曜か金曜に確認する、上長か人事部に確認する）
    ("上長と人事部の両方に確認する。", "上長か人事部に確認する。", ("choice", "all_to_one")),
    ("木曜と金曜の両方に確認する。", "木曜か金曜に確認する。", ("choice", "all_to_one")),
    # 因果の言い方（によって増加した、につながった、のおかげで、の結果、を招く）
    ("この施策と売上の増加には関連がある。", "この施策によって売上が増加した。", ("causality", "relation_to_cause")),
    ("この施策と売上の増加には関連がある。", "この施策が売上の増加につながった。", ("causality", "relation_to_cause")),
    ("この施策と売上の増加には関連がある。", "この施策のおかげで売上が増えた。", ("causality", "relation_to_cause")),
    ("この施策と売上の増加には関連がある。", "この施策の結果、売上が増えた。", ("causality", "relation_to_cause")),
    ("気温と来店数には相関がある。", "気温の上昇が来店数の増加を招く。", ("causality", "relation_to_cause")),
    # 文末の「関連する」「関係する」
    ("喫煙は肺がんと関連する。", "喫煙は肺がんを引き起こす。", ("causality", "relation_to_cause")),
    ("喫煙と肺がんは関係する。", "喫煙は肺がんの原因になる。", ("causality", "relation_to_cause")),
    # 述語を求めるようにした「相関」も、関わりを述べる形なら拾う
    ("気温と来店数には強い相関が見られた。", "気温が来店数の増加を引き起こした。", ("causality", "relation_to_cause")),
    ("関連があるかもしれない。", "原因かもしれない。", ("causality", "relation_to_cause")),
    # 文を分けて、因果の言い方を2文目に足した書き換え
    ("この施策と売上の増加には関連がある。", "この施策と売上の増加には関わりがある。施策が増加の原因だ。",
     ("causality", "relation_to_cause")),
    ("喫煙と肺がんには相関がある。", "喫煙と肺がんには相関がある。喫煙が肺がんを引き起こす。", ("causality", "relation_to_cause")),
]


class DetectTest(unittest.TestCase):
    def test_should_detect(self):
        for before, after, expected in SHOULD_DETECT:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    result = run(before, after, doc_type)
                    self.assertIn(expected, new_kinds(result), kinds(result))
                    self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_should_not_detect(self):
        for before, after in SHOULD_NOT_DETECT:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    self.assertEqual(new_kinds(run(before, after, doc_type)), [])

    def test_should_not_detect_narrowed(self):
        """打ち消しの関連、名詞を修飾する関連の語、原文の因果、別の名詞に掛かる「すべて」、どれでもよい言い方、問いの「か」、
        同じ側の言い換えでは、選ぶ範囲と因果の候補を出さず、--fail-on の数も増やさない。"""
        for before, after in NOT_DETECT_NARROWED:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    self.assertEqual(new_kinds(run(before, after, doc_type)), [])

    def test_should_detect_added(self):
        for before, after, expected in DETECT_ADDED:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, after=after, doc_type=doc_type):
                    result = run(before, after, doc_type)
                    self.assertIn(expected, new_kinds(result), kinds(result))
                    self.assertGreaterEqual(result["fail_on_meaning_risk_count"], 1)

    def test_split_sentence_shows_the_added_sentence(self):
        """2文目に足した因果の言い方で出したときは、後の文に2文目まで含める。範囲の中で出すときは範囲の文だけにする。"""
        risk = [r for r in run("喫煙と肺がんには相関がある。", "喫煙と肺がんには相関がある。喫煙が肺がんを引き起こす。")["meaning_risks"]
                if r["kind"] == "causality"][0]
        self.assertEqual(risk["new"], "喫煙と肺がんには相関がある。喫煙が肺がんを引き起こす。")
        self.assertEqual(risk["detail"]["new_hits"], ["引き起こす"])
        risk = [r for r in run("喫煙と肺がんには相関がある。手順は次のとおり。", "喫煙が肺がんを引き起こす。手順は次のとおり。")["meaning_risks"]
                if r["kind"] == "causality"][0]
        self.assertEqual(risk["new"], "喫煙が肺がんを引き起こす。")
        # 原文の次の文に当たる文は、足した文として含めない
        self.assertEqual(new_kinds(run("喫煙と肺がんには相関がある。理由は分からない。", "喫煙と肺がんには相関がある。理由はまだ分からない。")),
                         [])

    def test_adnominal_all_pairs_with_the_same_noun(self):
        """「すべての条件」は、原文に同じ名詞の「いずれかの条件」があるときだけ全部の言い方にする。「全項目」は「すべての項目」と同じ側。"""
        def hits(before, after):
            return [(r["subkind"], r["detail"]["old_hits"], r["detail"]["new_hits"]) for r in run(before, after)["meaning_risks"]
                    if r["kind"] == "choice"]
        self.assertEqual(hits("いずれかの条件を満たせば通知する。", "すべての条件を満たせば通知する。"),
                         [("one_to_all", ["いずれか"], ["すべて"])])
        self.assertEqual(hits("すべての条件を満たせば通知する。", "いずれかの条件を満たせば通知する。"),
                         [("all_to_one", ["すべて"], ["いずれか"])])
        self.assertEqual(hits("いずれかの項目を選ぶ。", "全項目を選ぶ。"), [("one_to_all", ["いずれか"], ["全項目"])])
        self.assertEqual(hits("いずれかの項目を選び、全項目を保存する。", "すべての項目を選び、全項目を保存する。"), [])
        self.assertEqual(hits("AまたはBを選ぶと、すべての機能が使える。", "AやBを選ぶと、すべての機能が使える。"), [])

    def test_marker_hits(self):
        """印の当て方: 打ち消しや名詞を修飾する関連の語、接続の「つながる」、手順の「〜の結果、」は拾わない。"""
        def hits(text, kind):
            return [hit for _, k, hit in yomiyasu_diff._logic_positions(text) if k == kind]
        for text in ("この二つには関係がありません。", "関係のある部署に送る。", "関係がある部署に送る。", "相関係数を求める。",
                     "相関は見られなかった。", "関連が認められない。", "関係があるか調べる。", "関連記事を読む。",
                     "全員に関係する話だ。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text, "関連"), [])
        for text, expected in (("両者には相関がある。", ["相関"]), ("両者には関連がある。", ["関連がある"]),
                               ("AはBと関連する。", ["関連する"]), ("AとBは関係している。", ["関係している"]),
                               ("関連があるかもしれない。", ["関連がある"])):
            with self.subTest(text=text):
                self.assertEqual(hits(text, "関連"), expected)
        for text in ("サーバーにつながるまで待つ。", "ひとつにつながった瞬間だった。", "調査の結果、関連が分かった。",
                     "その結果、関連が分かった。", "講師を招いた。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text, "因果"), [])
        for text, expected in (("障害につながる。", ["につながる"]), ("混乱を招く。", ["を招く"]), ("施策の結果、増えた。", ["の結果、"]),
                               ("施策のおかげで増えた。", ["おかげで"]), ("施策によって売上が増加した。", ["によって売上が増加し"])):
            with self.subTest(text=text):
                self.assertEqual(hits(text, "因果"), expected)
        for text, expected in (("AまたはBを選ぶと、すべての機能が使える。", []), ("AとBのすべてを選ぶ。", ["すべて"]),
                               ("すべてを保存する。", ["すべて"]), ("書類はすべてそろえる。", []),
                               ("本人確認書類も住民票の写しも要る。", ["本人確認書類も住民票の写しも"]),
                               ("本番環境にも検証環境にも反映する。", ["本番環境にも検証環境にも"]), ("鍵は二つとも要る。", ["二つとも"])):
            with self.subTest(text=text):
                self.assertEqual(hits(text, "全部"), expected)

    def test_choice_ka_hits(self):
        """「AかB」の「か」は語と語の間の選ぶ「か」だけを拾い、問い・回数・期間の「か」は拾わない。"""
        def hits(text):
            return [(kind, hit) for _, kind, hit in yomiyasu_diff._logic_positions(text) if kind == "どれか一つ"]
        for text in ("支払いはカードかコンビニで選ぶ。", "木曜か金曜に確認する。", "管理画面かCLIから再送する。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [("どれか一つ", "か")])
        for text in ("何度か夜中に呼び出された。", "数回か試した。", "3か月ごとに見直す。", "必要か確認する。", "有効か否かを返す。",
                     "何か問題があれば連絡する。", "どちらかといえば速い。", "どの値が正しいか判断が必要だ。",
                     "二つの設定が有効か管理者に確認する。", "各端末が最新版か情報システム部に確かめてもらう。",
                     "全サーバーが正常か担当者に確認する。", "各設定が有効か現場で判断する。", "対応可能か担当者に確認する。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [])
        for text in ("上長か人事部に確認する。", "木曜か金曜に確認する。"):
            with self.subTest(text=text):
                self.assertEqual(hits(text), [("どれか一つ", "か")])

    def test_request_pair_counts_as_meaning_risk(self):
        """依頼の組は、意味が変わる恐れ1件以上で、そのうち選ぶ範囲の1件を --fail-on に数える。"""
        result = run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。")
        self.assertEqual(new_kinds(result), [("choice", "one_to_all")])
        self.assertGreaterEqual(result["meaning_risk_count"], 1)
        self.assertEqual(result["fail_on_meaning_risk_count"], 1)
        self.assertEqual(result["status"], "has_candidates")

    def test_detail(self):
        risk = [r for r in run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。")["meaning_risks"]
                if r["kind"] == "choice"][0]
        self.assertEqual(risk["detail"], {"from": "どれか一つ", "to": "全部", "old_hits": ["または", "どちらか"],
                                          "new_hits": ["両方"]})
        self.assertEqual((risk["old_line"], risk["new_line"]), (1, 1))
        risk = [r for r in run("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。")["meaning_risks"]
                if r["kind"] == "causality"][0]
        self.assertEqual(risk["detail"], {"from": "関連", "to": "因果", "old_hits": ["相関"], "new_hits": ["引き起こす"]})
        self.assertEqual(risk["old"], "喫煙と肺がんには相関がある。")
        self.assertEqual(risk["new"], "喫煙が肺がんを引き起こす。")

    def test_split_sentence_compares_the_corresponding_range(self):
        """文を分けても、元の文に当たる範囲で比べる。別の文の「すべて」は、どれか一つの言い方の消えと組にしない。"""
        result = run("申請書か委任状のどちらかを提出し、窓口で確認を受ける。",
                     "申請書と委任状の両方を提出する。窓口で確認を受ける。")
        self.assertEqual(new_kinds(result), [("choice", "one_to_all")])
        result = run("AまたはBを選ぶ。すべての設定を保存する。", "AやBを選ぶ。すべての設定を保存する。")
        self.assertEqual(new_kinds(result), [])

    def test_human_lines(self):
        report = yomiyasu_diff.report(run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。"))
        self.assertIn("- 選ぶ範囲が「どれか一つ」から「全部」に変わった（1行目）: どれか一つ（または、どちらか） → 全部（両方）。",
                      report)
        report = yomiyasu_diff.report(run("AとBの両方を選ぶ。", "AかBを選ぶ。"))
        self.assertIn("- 選ぶ範囲が「全部」から「どれか一つ」に変わった（1行目）: 全部（両方） → どれか一つ（か）。", report)
        report = yomiyasu_diff.report(run("AまたはBを使える。", "AもBも使える。"))
        self.assertIn("- 選ぶ範囲が「どれか一つ」から「全部」に変わった（1行目）: どれか一つ（または） → 全部（AもBも）。", report)
        report = yomiyasu_diff.report(run("この施策と売上の増加には関連がある。", "この施策が売上の増加の原因である。"))
        self.assertIn("- 関連の言い方が因果の言い方に変わった（1行目）: 関連（関連がある） → 因果（原因）。", report)
        result = run("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。")
        risks = result["meaning_risks"]
        self.assertIn("・選ぶ範囲", yomiyasu_diff._fail_on_line(len(risks) + 1, yomiyasu_diff.fail_on_count(risks), risks))
        result = run("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。")
        risks = result["meaning_risks"]
        self.assertIn("・因果", yomiyasu_diff._fail_on_line(len(risks) + 1, yomiyasu_diff.fail_on_count(risks), risks))


class CliTest(unittest.TestCase):
    def test_cli_exit_codes(self):
        rows = [("AまたはBのどちらかを選ぶ必要がある。", "AとBの両方を選ぶ必要がある。", 1),
                ("この施策と売上の増加には関連がある。", "この施策と売上の増加には因果関係がある。", 1),
                ("この施策と売上の増加には関連がある。", "この施策が売上の増加の原因である。", 1),
                ("喫煙と肺がんには相関がある。", "喫煙が肺がんを引き起こす。", 1),
                ("AまたはBを選ぶ。", "AかBを選ぶ。", 0),
                ("この障害と更新には関係はありません。", "この障害の原因は更新ではありません。", 0),
                ("関係のある部署に、障害の理由を報告する。", "関係のある部署に、障害の原因を報告する。", 0),
                ("気温は売上に影響し、両者には相関がある。", "気温は売上に影響を与え、両者には相関がある。", 0),
                ("管理画面またはCLIから、全項目を設定できる。", "管理画面とCLIのどちらからでも、すべての項目を設定できる。", 0),
                ("すべてのサーバーが正常に動いているかを、担当者に確認する。", "全サーバーが正常か担当者に確認する。", 0),
                ("AまたはBのいずれかを選ぶと、すべての機能が使える。", "AとBの両方を選ぶと、すべての機能が使える。", 1),
                ("本番環境または検証環境に反映する。", "本番環境にも検証環境にも反映する。", 1),
                ("この施策と売上の増加には関連がある。", "この施策によって売上が増加した。", 1),
                ("この施策と売上の増加には関連がある。", "この施策と売上の増加には関係がある。", 0)]
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old.md", Path(folder) / "new.md"
            for before, after, code in rows:
                old.write_text(before + "\n", encoding="utf-8")
                new.write_text(after + "\n", encoding="utf-8")
                for flags in ([], ["--doc-type", "formal"]):
                    with self.subTest(before=before, after=after, flags=flags):
                        process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/yomiyasu_diff.py"), "--fail-on",
                                                  "meaning-risk"] + flags + [str(old), str(new)], capture_output=True, text=True,
                                                 encoding="utf-8")
                        self.assertEqual(process.returncode, code, process.stdout + process.stderr)
                        if code:
                            self.assertIn("終了コード1: --fail-on=meaning-risk の条件に当たりました", process.stdout)


class ContractsTest(unittest.TestCase):
    def test_kinds_and_fail_on(self):
        """新しい kind は数える側に足し、既存の kind の並びはそのまま残す。"""
        self.assertEqual(yomiyasu_diff.FAIL_ON_KINDS[:9], ("number", "negation", "swap", "sentence_type", "citation",
                                                          "certainty", "state", "promise", "modality"))
        self.assertIn("choice", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertIn("causality", yomiyasu_diff.FAIL_ON_KINDS)
        self.assertLess(yomiyasu_diff._RISK_ORDER["modality_review"], yomiyasu_diff._RISK_ORDER["choice"])
        self.assertIn("causality", yomiyasu_diff._RISK_ORDER)

    def test_public_function_matches_diff(self):
        """type_changes を渡した meaning_risks() は、選ぶ範囲と因果の候補を含めて diff() と同じ。None なら足さず、範囲も作らない。"""
        documents = (("AまたはBのどちらかを選ぶ。外部APIは遅れるかもしれない。\n", "AとBの両方を選ぶ。外部APIは遅れる。\n"),
                     ("喫煙と肺がんには相関がある。\n", "喫煙が肺がんを引き起こす。\n"),
                     ("この値は変更してよい。AまたはBを選ぶ。\n", "この値は変更できる。AとBの両方を選ぶ。\n"))
        for before, after in documents:
            for doc_type in (None, "formal"):
                with self.subTest(before=before, doc_type=doc_type):
                    result = yomiyasu_diff.diff(before, after, doc_type=doc_type)
                    self.assertTrue(new_kinds(result))
                    self.assertIsNone(yomiyasu_diff._LAST_TYPE_RANGES[0])
                    found = yomiyasu_diff.meaning_risks(before, after, type_changes=result["type_changes"], doc_type=doc_type)
                    self.assertEqual(found, result["meaning_risks"])
                    self.assertIsNone(yomiyasu_diff._LAST_TYPE_RANGES[0])
        with mock.patch.object(yomiyasu_diff, "_type_ranges", side_effect=AssertionError("範囲を作った")):
            found = yomiyasu_diff.meaning_risks("AまたはBを選ぶ。\n", "AとBの両方を選ぶ。\n")
        self.assertFalse([r for r in found if r["kind"] in NEW_KINDS])

    def test_ranges_are_made_once_in_diff(self):
        """diff() は、文の種類の印の範囲を、許可・能力の比べでも選ぶ範囲・因果の比べでも作り直さない。"""
        documents = (("AまたはBを選ぶ。外部APIは遅れるかもしれない。\n", "AとBの両方を選ぶ。外部APIは遅れる。\n"),
                     ("この値は変更してよい。AまたはBを選ぶ。\n", "この値は変更できる。AとBの両方を選ぶ。\n"),
                     ("AまたはBを選ぶ。\n", "AとBの両方を選ぶ。\n"))
        for before, after in documents:
            with self.subTest(before=before):
                with mock.patch.object(yomiyasu_diff, "_type_ranges", wraps=yomiyasu_diff._type_ranges) as ranges:
                    result = yomiyasu_diff.diff(before, after)
                self.assertEqual(ranges.call_count, 1)
                self.assertIn(("choice", "one_to_all"), kinds(result))
        # 選ぶ範囲と因果の印がどちらの側にもそろわない文章では、範囲を作らない
        with mock.patch.object(yomiyasu_diff, "_type_ranges", wraps=yomiyasu_diff._type_ranges) as ranges:
            yomiyasu_diff.diff("設定を保存する。\n", "設定を保存した。\n")
        self.assertEqual(ranges.call_count, 0)

    def test_help_names_the_new_counted_kinds(self):
        """--fail-on の説明と終了コードの表に、選ぶ範囲と因果を数えることを書く。"""
        helps = {action.dest: action.help for action in yomiyasu_diff._build_parser()._actions}
        self.assertIn("選ぶ範囲が入れ替わった書き換え", helps["fail_on"])
        self.assertIn("因果の言い方（因果、原因、引き起こす など）を足した書き換え", helps["fail_on"])
        self.assertIn("許可の言い方・選ぶ範囲・因果の恐れが1件以上", yomiyasu_diff._EXIT_CODES)

    def test_twin_scripts_are_identical(self):
        self.assertEqual((ROOT / "scripts" / "yomiyasu_diff.py").read_bytes(),
                         (ROOT / "skills" / "yomiyasu" / "scripts" / "yomiyasu_diff.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
