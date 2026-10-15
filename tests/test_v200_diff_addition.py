"""状態の語の消えと書き足しの検出。例の文はすべて合成。

評価の足し（claim/evaluation）と一般化・勧めの足し（claim/general）は、語の表では拾いきれなかったので diff から外した。
その例（R2 の評価、R3、R6、R7、R9〜R11、RN9）は、文を変えずに「出ない」ことを確かめる例にしている。
absent には kind か「kind/subkind」を書く。"""
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import yomiyasu_diff as diff

L = "まだ計測していませんが、決済APIの呼び出しがDBトランザクションの内側にあるため、外部APIが遅延した際にコネクションを長く握る可能性があります。"
EX = [
    ("S1", "ご依頼の部材の納期は未定です。メーカーからの回答を待っています。", "ご依頼の部材は、メーカーからの回答を受けて来週中にお届けします。", {"state/lost", "promise/added"}, ()),
    ("S2", "お届けが遅れた理由は調査中です。", "お届けが遅れたのは配送業者の手違いによるものでした。", {"state/lost", "claim/causal"}, ()),
    ("S3", "先方からはまだ回答がありません。届き次第お伝えします。", "先方から了承の回答をいただきましたので、お伝えします。", {"state/lost"}, ("promise",)),
    ("S4", "今年度は説明会を開く予定はありません。", "今年度の説明会の日程は、決まり次第サイトでお知らせします。", {"state/lost", "promise/added"}, ()),
    ("S5", "外部APIの仕様変更が影響するかは未確認です。", "外部APIの仕様変更による影響はありません。", {"state/lost"}, ()),
    ("S6", "研修の会場は検討中です。", "研修の会場は本社の大会議室です。", {"state/lost"}, ()),
    ("S7", "会計ソフトとの連携は未確認です。", "会計ソフトとの連携はまだ確認が取れておりませんので、こちらは別途確認させていただきます。", {"promise/added"}, ("state",)),
    ("S8", L, L.replace("まだ計測していませんが、", ""), {"state/lost"}, ()),
    ("SN1", "移行の日程は未定です。", "移行の日程は、まだ決まっていません。", set(), ("state", "promise", "claim")),
    ("SN2", "障害の原因は調査中です。", "障害の原因は、現在調べています。", set(), ("state", "promise", "claim")),
    ("SN3", "原因は不明です。調査を続けます。", "原因はまだ特定できていません。引き続き調査します。", set(), ("state", "promise", "claim")),
    ("SN4", "テストは未実施のまま出荷した。", "テストを実施しないまま出荷した。", set(), ("state", "promise", "claim")),
    ("SN5", "`.env` がまだない場合に、ひな形をコピーします。", "`.env` がなければ、ひな形をコピーします。", set(), ("state", "promise", "claim")),
    ("SN6", "作業中は本番サービスを一時停止します。", "作業の間は、本番サービスを止めます。", set(), ("state", "promise", "claim")),
    ("SN7", "ご不明な点があればお知らせください。", "分からない点があれば、お知らせください。", set(), ("state", "promise", "claim")),
    ("SN8", "一方、効果がはっきりしていないこともある。", "一方で、効果が明確でない点も残っています。", set(), ("state",)),
    ("SN9", "テスト環境の構築は未完了です。", "テスト環境の構築は完了しています。", set(), ("state",)),
    ("SN10", "予約がまだ済んでいないため、前日までに担当を決めます。", "予約はまだ済んでいません。そのため、前日までに担当を決めます。", set(), ("state", "promise")),
    ("P1", "駐車場の工事のため、来週は東側の区画が使えません。", "駐車場の工事のため、来週は東側の区画が使えません。代わりの区画はこちらで用意いたします。", {"promise/added"}, ()),
    ("P2", "駐車場の工事のため、来週は東側の区画が使えません。", "駐車場の工事のため、来週は東側の区画が使えません。工事による追加の費用が皆さまにかかることはありません。", {"promise/guarantee"}, ()),
    ("P3", "4月から会員の料金が変わります。", "4月から会員の料金が変わります。4月末までは、これまでの料金のままご利用いただけます。", {"promise/guarantee"}, ()),
    ("P4", "見積もりは来週出す。", "見積もりは来週提出する。金額は前回から変えない。", {"promise/guarantee"}, ()),
    ("P5", "新しい勤怠システムは5月から使います。使い方の説明会は4月に2回開きます。", "新しい勤怠システムは5月から使います。使い方の説明会は4月に2回開きます。参加できなかった方には、個別に説明いたします。", {"promise/added"}, ()),
    ("P6", "来週の打ち合わせの資料、目を通しておいてもらえますか。", "来週の打ち合わせの資料をお送りしますので、お目通しいただけますでしょうか。", {"promise/added"}, ()),
    ("P7", "請求書の金額を間違えてお送りしました。申し訳ありません。", "請求書の金額を誤ってお送りしました。申し訳ございません。今後このようなことがないよう、確認を徹底いたします。", {"promise/prevention"}, ()),
    ("P8", "納品が1日遅れました。", "納品が1日遅れてしまい、申し訳ございません。二度とこのようなことがないよう努めます。", {"promise/prevention"}, ()),
    ("P9", "部品の入荷は来週の見込みです。", "部品の入荷は来週の見込みです。準備が整い次第、改めてご連絡いたします。", {"promise/added"}, ()),
    ("PN1", "来週、見積もりを送ります。", "来週、お見積もりをお送りいたします。", set(), ("state", "promise", "claim")),
    ("PN2", "結果が出たら連絡します。", "結果が出ましたら、ご連絡いたします。", set(), ("state", "promise", "claim")),
    ("PN3a", "資料を確認してください。", "資料をご確認いただけますでしょうか。", set(), ("promise",)),
    ("PN3b", "返事をください。", "ご返信をお願いいたします。", set(), ("promise",)),
    ("PN4", "よろしくお願いします。", "よろしくお願いいたします。", set(), ("state", "promise", "claim")),
    ("PN5", "電話での予約も続けます。", "電話でのご予約も引き続き受け付けます。", set(), ("state", "promise", "claim")),
    ("PN6", "今後は確認を徹底します。申し訳ありません。", "申し訳ございません。今後は確認を徹底いたします。", set(), ("state", "promise", "claim")),
    ("PN7", "設定ファイルを読み込み、ジョブを登録する。", "設定ファイルを読み込む。そのあとジョブを登録する。", set(), ("state", "promise", "claim")),
    ("PN8", "この関数は値を検証し、エラーなら例外を投げる。", "この関数は値を検証します。エラーなら例外を投げます。", set(), ("state", "promise", "claim")),
    ("PN9", "担当の佐藤が明日電話します。", "明日、担当の佐藤からお電話いたします。", set(), ("state", "promise", "claim")),
    ("PN10", "比較した結果です。", "比較した結果を共有します。", set(), ("promise",)),
    ("PN11", "遅延は起きない。", "遅延が起きることはない。", set(), ("promise",)),
    ("PN12", "利用料は0円です。", "利用料は無料です。", set(), ("promise",)),
    ("PN13", "「明日、迎えに行きます」と彼は言った。", "「明日、迎えに行くよ」と彼は言った。", set(), ("promise",)),
    ("PN14", "来週お届けできる見込みです。", "来週お届けします。", set(), ("promise",)),
    ("R1", "フォームの項目を12から7に減らした。問い合わせは月50件から31件になった。", "フォームの項目を12から7に削減した結果、問い合わせ件数が月50件から31件に減少した。", {"claim/causal"}, ("state", "promise")),
    ("R2", "フォームの項目を12から7に減らした。満足度は3.9から4.3になった。", "フォームの項目を12から7に減らした。入力の手間が減ったことが、満足度の3.9から4.3への向上につながったと考えられる。", {"claim/causal"}, ("claim/evaluation", "claim/general")),
    ("R3", "フォームの項目を12から7に減らした。", "フォームの項目を12から7に減らした。他の窓口でも同様の見直しを進めるべきです。", set(), ("claim/evaluation", "claim/general")),
    ("R4", "雪のため、配送が半日遅れました。", "雪のため配送が半日遅れました。到着が遅れたのは、事前の手配が足りなかったためです。", {"claim/causal"}, ()),
    ("R5", "駅前の店は3月で閉めます。近くに2号店があります。", "近くに2号店があるため、駅前の店は3月で閉めます。", {"claim/causal"}, ()),
    ("R6", "テストのカバー率は61%から74%になった。", "テストのカバー率は61%から74%に上がり、品質が向上した。", set(), ("claim/evaluation", "claim/general")),
    ("R7", "先日の講習会には12人が参加しました。", "先日の講習会には12人が参加しました。今後も定期的に開くことをおすすめします。", set(), ("claim/evaluation", "claim/general")),
    ("RN1", "雪のため、配送が遅れました。", "雪の影響で、配送が遅れました。", set(), ("state", "promise", "claim")),
    ("RN2", "フォームの項目を減らしたので、問い合わせが減った。", "フォームの項目を減らしたため、問い合わせが減った。", set(), ("state", "promise", "claim")),
    ("RN3", "ライブラリを2.3に上げた。テストの時間は8分から5分になった。", "ライブラリを2.3に上げ、テストの時間は8分から5分になった。", set(), ("state", "promise", "claim")),
    ("RN4", "A窓口で用紙の欄を半分にした。記入のし直しは月30件から8件になった。", "A窓口で用紙の欄を半分にしたところ、記入のし直しは月30件から8件になった。", set(), ("state", "promise", "claim")),
    ("RN5", "会議の数は月40回から28回になった。", "会議の数は月40回から28回に減った。", set(), ("state", "promise", "claim")),
    ("RN6a", "この方法は効果があった。", "この方法には効果がありました。", set(), ("state", "promise", "claim")),
    ("RN6b", "レビューが効いた。", "レビューの効果があった。", set(), ("claim",)),
    ("RN7", "他の部署でも使うべきだという声がある。", "ほかの部署でも使うべきだという声があります。", set(), ("state", "promise", "claim")),
    ("RN8", "イベントIDを保存しており、二重処理されません。", "イベントIDを保存しているため、二重処理されません。", set(), ("claim",)),
    ("RN9", "長距離では、握る位置を変えて疲れを減らします。", "長距離では、疲れを減らすために、握る位置を変えるとよいでしょう。", set(), ("claim/evaluation", "claim/general")),
    # 反証のあとで足した例（同じ途中の状態の言い換え、敬語の「おりません」、状態の打ち消し、別の対象の状態）
    ("S9", "処理は保留です。", "処理はいったん完了しました。", {"state/lost"}, ()),
    ("S10", "修正は作業中です。", "修正は終わったところです。", {"state/lost"}, ()),
    ("S11", "原因は未確認です。", "原因は特定済みですが、解決は困難です。", {"state/lost"}, ()),
    ("S12", "納期は未定です。", "納期は来月です。会場は未定です。", {"state/lost"}, ()),
    ("S13", "納期は見通しが立ちません。", "納期は来月です。", {"state/lost"}, ()),
    ("S14", "日程は検討中、会場は本社です。", "日程は10日、会場は本社です。", {"state/lost"}, ()),
    ("S15", "合意には至っていません。", "合意しました。", {"state/lost"}, ()),
    ("SN11", "内容は確認中です。", "内容を確認しています。", set(), ("state",)),
    ("SN12", "工場と相談中です。", "現在、工場と相談しております。", set(), ("state",)),
    ("SN13", "承認待ちです。", "承認をお待ちしております。", set(), ("state",)),
    ("SN14", "原因は不明です。", "原因は分かっておりません。", set(), ("state",)),
    ("SN15", "日程は未定です。", "日程は決まっておりません。", set(), ("state",)),
    ("SN16", "未確認の項目はありません。", "すべての項目を確認済みです。", set(), ("state",)),
    ("SN17", "彼を駅まで見送ります。", "彼を駅まで送ります。", set(), ("state",)),
    ("SN18", "原因は調査中です。", "原因は設定の誤りと考えられます。", set(), ("state",)),
    ("P10", "資料は机にあります。", "資料は机にあります。資料を破棄いたします。", {"promise/added"}, ()),
    ("P11", "資料は机の上です。", "資料は机の上です。お客様に資料をお送りします。", {"promise/added"}, ()),
    ("P12", "資料は机の上です。", "資料は机の上です。今後は弊社で対応します。", {"promise/added"}, ()),
    ("P13", "費用についての説明です。", "費用についての説明です。追加費用はかかりません。", {"promise/guarantee"}, ()),
    ("P14", "再発防止策は未定です。", "再発防止策は未定です。今後は確認を徹底します。", {"promise/prevention"}, ()),
    ("P15", "日程は未定です。", "日程は、決まりましたらご連絡いたします。", {"promise/added"}, ("state",)),
    ("PN15", "見積もり、金曜に出すね。", "お見積もりは金曜に提出いたします。", set(), ("promise", "promise_review")),
    ("PN16", "そこ直しとくね。", "該当箇所を修正いたします。", set(), ("promise", "promise_review")),
    ("PN17", "同じ事故を防ぐ対策は実施済みです。", "再発防止策は実施済みです。", set(), ("promise",)),
    ("PN18", "この靴は疲れにくい。", "この靴は疲労を軽減します。", {"promise_review/added"}, ("promise",)),
    ("PN19", "作業が早く終われば、停止時間は短くなります。", "作業が早く完了した場合は、停止時間を短縮します。", {"promise_review/added"}, ("promise",)),
    ("PN20", "不明な点があればご連絡ください。", "不明な点があれば、こちらからご説明いたします。", set(), ("promise",)),
    ("R8", "大雨のときに停電した。", "大雨により停電した。", {"claim/causal"}, ()),
    ("R9", "業務の効率化を検討しています。", "業務の効率化を検討しています。品質も向上しました。", set(), ("claim/evaluation", "claim/general")),
    ("R10", "鍵を箱に入れた。", "大切な鍵を箱に入れた。", set(), ("claim/evaluation", "claim/general")),
    ("R11", "その方法を使った。", "その方法を使った。その方法は勧められる。", set(), ("claim/evaluation", "claim/general")),
    ("RN10", "効き目があった。", "効果があった。", set(), ("claim",)),
    ("RN11", "その案は嫌われた。", "その案は好まれなかった。", set(), ("claim",)),
    ("RN12", "これは特筆に値する。", "これは特筆すべきです。", set(), ("claim",)),
    ("RN13", "回線と機器の両方を調べて分かった。", "回線と機器の両方を調べた結果、分かった。", set(), ("claim",)),
    ("RN14", "注文日時に今日のボタンを足した。", "注文日時に今日のボタンを足したことで、すぐ探せる。", set(), ("claim",)),
]

EXAMPLES = {name: (old, new) for name, old, new, _, _ in EX}
NEW_KINDS = ('state', 'promise', 'claim', 'promise_review')
BASELINE = json.loads((ROOT / 'tests/fixtures/diff_addition_baseline.json').read_text(encoding='utf-8'))


def additions(result):
    return [r for r in result['meaning_risks'] if r['kind'] in NEW_KINDS]


class DesignExamples(unittest.TestCase):
    def check_example(self, row):
        name, old, new, want, absent = row
        result = diff.diff(old, new)
        added = additions(result)
        got = {r['kind'] + '/' + r['subkind'] for r in added}
        self.assertTrue(want <= got, (want, got))
        self.assertFalse(any(r['kind'] in absent or r['kind'] + '/' + r['subkind'] in absent for r in added), added)
        self.assertTrue(all(r['basis'] is None for r in added))
        # 既存の候補の内容と順番は保持し、統合した確度の見直しだけを除く。
        expected = BASELINE['risks'][name]
        states = [diff._Body('', r['old'], r['old_line'], 0) for r in added if r['kind'] == 'state']
        expected = [r for r in expected if r['kind'] != 'certainty_review'
                    or not any(diff._same_review_sentence(b, r) for b in states)]
        self.assertEqual(result['meaning_risks'], expected + added)
        self.assertEqual(added, sorted(added, key=lambda r: (
            r['old_line'] if r['old_line'] is not None else r['new_line'] or 0,
            r['new_line'] if r['new_line'] is not None else 0)))
        self.assertEqual(result['fail_on_meaning_risk_count'], diff.fail_on_count(expected)
                         + sum(r['kind'] in ('state', 'promise') for r in added))


def example_test(row):
    def test(self):
        self.check_example(row)
    return test


for row in EX:
    setattr(DesignExamples, 'test_' + row[0], example_test(row))


class Contracts(unittest.TestCase):
    def test_nine_keys_and_top_level(self):
        for name in ('S1', 'P1', 'R1'):
            result = diff.diff(*EXAMPLES[name])
            self.assertEqual({k: result[k] for k in BASELINE['nine'][name]}, BASELINE['nine'][name])
            self.assertEqual(list(result), BASELINE['keys'])
            self.assertEqual(result['format_version'], 2)

    def test_unchanged_reports(self):
        for name, expected in BASELINE['reports'].items():
            self.assertEqual(diff.report(diff.diff(*EXAMPLES[name])), expected)

    def test_state_detail_and_certainty_merge(self):
        result = diff.diff(*EXAMPLES['S6'])
        state = next(r for r in additions(result) if r['kind'] == 'state')
        self.assertEqual(state['detail']['words'], ['検討中'])
        self.assertEqual(state['detail']['families'], ['considering'])
        expected = [step for r in BASELINE['risks']['S6'] if r['kind'] == 'certainty_review'
                    for step in r['detail']['steps']]
        self.assertEqual(state['detail']['certainty_steps'], expected)
        self.assertFalse(any(r['kind'] == 'certainty_review' for r in result['meaning_risks']))

    def test_unpaired_lines_and_detail(self):
        added = additions(diff.diff(*EXAMPLES['P1']))[0]
        self.assertIsNone(added['old_line'])
        self.assertIsNone(added['old'])
        self.assertEqual(added['new_line'], 1)
        self.assertEqual(set(added['detail']), {'phrases', 'names'})
        old = EXAMPLES['S6'][0]
        state = next(r for r in additions(diff.diff(old, '')) if r['kind'] == 'state')
        self.assertIsNone(state['new_line'])
        self.assertIsNone(state['new'])
        self.assertIn('（元1行目）', diff._risk_line(state))

    def test_causal_reason_and_joined_lines(self):
        for name, reason in (('R1', 'joined'), ('S2', 'new_content'), ('R4', 'new_content')):
            item = next(r for r in additions(diff.diff(*EXAMPLES[name])) if r['subkind'] == 'causal')
            self.assertEqual(item['detail']['reason'], reason)
            self.assertEqual(bool(item['detail']['joined_lines']), reason == 'joined')
        old, new = EXAMPLES['R1']
        item = next(r for r in additions(diff.diff(old.replace('。', '。\n'), new)) if r['subkind'] == 'causal')
        self.assertEqual(item['detail']['joined_lines'], [1, 2])

    def test_no_negation_or_certainty_duplicate(self):
        for name, existing in (('SN9', 'negation'), ('PN14', 'certainty')):
            found = diff.diff(*EXAMPLES[name])['meaning_risks']
            self.assertTrue(any(r['kind'] == existing for r in found))
            self.assertFalse(any(r['kind'] in ('state', 'promise') for r in found))

    def test_general_should_is_not_counted_twice(self):
        # 一般化・勧めの足しは出さない。「べき」は既存の文の種類の印の候補だけが拾う。
        old = EXAMPLES['R3'][0]
        new = 'フォームの項目を12から7に減らすべきです。'
        found = diff.diff(old, new)['meaning_risks']
        self.assertTrue(any(r['kind'] == 'sentence_type' for r in found))
        self.assertFalse(any(r['kind'] == 'claim' and r['subkind'] == 'general' for r in found))
        self.assertFalse(any(r['subkind'] == 'general' for r in additions(diff.diff(*EXAMPLES['RN9']))))

    def test_feeling_word_not_repeated_as_evaluation(self):
        # 評価の足しは出さない。既存の気持ち候補があってもなくても、評価の候補は0件。
        old, new = EXAMPLES['R6']
        full, sides = diff._build_full_diff(old, new, None)
        groups = diff._sentence_pairs(sides, full)
        feeling = diff._risk('feeling', 'added', 1, 1, old, new, {'words': ['向上']})
        masks = (diff._Masker(sides, 0), diff._Masker(sides, 1))
        for risks in ([feeling], []):
            found = diff._addition_risks(sides, groups, risks, masks)
            self.assertFalse(any(r['subkind'] == 'evaluation' for r in found))

    def test_masked_text_is_not_detected(self):
        for name in ('S6', 'P1', 'R6'):
            for template in ('```\n{}\n```\n', '# {}\n', '`{}`\n', '| 内容 |\n| --- |\n| {} |\n'):
                old, new = [template.format(t) for t in EXAMPLES[name]]
                self.assertEqual(additions(diff.diff(old, new)), [])

    def test_time_and_table_evidence(self):
        pairs = [
            ('この作業の途中で、ジョブを登録する。', 'この作業の間に、ジョブを登録する。'),
            ('| 対策 |\n| --- |\n| 期限監視を導入し、確認する。 |\n', '期限監視の仕組みを導入します。'),
            ('ご不明な点がございましたらお知らせください。', '分からない点があれば、お知らせください。'),
        ]
        for old, new in pairs:
            self.assertEqual(additions(diff.diff(old, new)), [])

    def test_promise_review_is_not_counted(self):
        # 書き手の印のない「〜します」は、説明や手順の文かもしれないので数えない（kind も別にする）。
        result = diff.diff(*EXAMPLES['PN18'])
        item = next(r for r in additions(result) if r['kind'] == 'promise_review')
        self.assertEqual(set(item['detail']), {'phrases', 'names'})
        self.assertNotIn('promise_review', diff.FAIL_ON_KINDS)
        self.assertEqual(result['fail_on_meaning_risk_count'], diff.fail_on_count(BASELINE['risks']['PN18']))

    def test_state_kept_on_another_topic_is_lost(self):
        # 別の項目の状態の語や、済んだと言い切った文の否定では、状態が残ったとみなさない。
        for name in ('S11', 'S12'):
            self.assertTrue(any(r['kind'] == 'state' for r in additions(diff.diff(*EXAMPLES[name]))), name)
        kept = diff.diff('予約がまだ済んでいないため、前日までに担当を決めます。',
                         '予約はまだ済んでいません。そのため、前日までに担当を決めます。')
        self.assertFalse(any(r['kind'] == 'state' for r in additions(kept)))

    def test_added_dialogue_is_not_a_promise(self):
        old = EXAMPLES['PN13'][0]
        self.assertFalse(any(r['kind'] == 'promise' for r in additions(diff.diff(old, old + '\n「明日、迎えに行きます」'))))

    def test_human_lines_and_fail_on_summary(self):
        labels = {'S6': '状態の語が消えた', 'P1': '原文にない書き手の約束',
                  'P2': '原文にない保証', 'P7': '原文にない再発防止の誓い',
                  'R1': '原文にない因果のつながり',
                  'PN18': '原文にない「〜します」（後1行目）: 「軽減します。」。--fail-on には数えません。',
                  'R8': '原文の時を言う言い方（〜時に、〜際に）を、原因の言い方に変えています。'}
        for name, label in labels.items():
            self.assertIn(label, diff.report(diff.diff(*EXAMPLES[name])))
        # 評価と一般化・勧めの足しは出さない。
        for name in ('R2', 'R3', 'R6', 'R7', 'R9', 'R10', 'R11', 'RN9'):
            text = diff.report(diff.diff(*EXAMPLES[name]))
            self.assertNotIn('原文にない評価の語', text)
            self.assertNotIn('原文にない一般化・勧め', text)
        found = diff.diff(*EXAMPLES['S1'])['meaning_risks']
        line = diff._fail_on_line(len(found) + 1, diff.fail_on_count(found), found)
        self.assertIn('・状態の語・約束', line)
        self.assertIn('原文の状態の語', diff._FAIL_ON_HELP)
        self.assertIn('原文にない因果のつながりの足しと', diff._FAIL_ON_HELP)
        self.assertNotIn('一般化', diff._FAIL_ON_HELP)
        self.assertNotIn('評価', diff._FAIL_ON_HELP)
        self.assertIn('「〜します」の足し（説明や手順の文かもしれないもの）も数えません', diff._FAIL_ON_HELP)

    def test_shared_sentence_groups_and_maskers(self):
        with mock.patch.object(diff, '_sentence_pairs', wraps=diff._sentence_pairs) as pairs, \
                mock.patch.object(diff, '_addition_risks', wraps=diff._addition_risks) as addition, \
                mock.patch.object(diff, '_certainty_risks', wraps=diff._certainty_risks) as certainty:
            diff.diff(*EXAMPLES['S1'])
        self.assertEqual(pairs.call_count, 1)
        self.assertIs(addition.call_args[0][1], certainty.call_args[0][1])
        self.assertIs(addition.call_args[0][3], certainty.call_args[0][3])

    def test_distributed_files_match(self):
        for path in ('scripts/yomiyasu_diff.py', 'scripts/yomiyasu_check.py', 'references/review-points.md'):
            self.assertEqual((ROOT / path).read_bytes(), (ROOT / 'skills/yomiyasu' / path).read_bytes())

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / 'old.md', Path(folder) / 'new.md'
            for name, failed in (('S1', 1), ('P1', 1), ('P7', 1), ('R1', 0), ('R3', 0), ('R6', 0),
                                 ('S13', 1), ('SN11', 0), ('SN14', 0), ('PN16', 0), ('PN18', 0), ('PN19', 0)):
                a, b = EXAMPLES[name]
                old.write_text(a, encoding='utf-8'); new.write_text(b, encoding='utf-8')
                for flags, code in (([], 0), (['--fail-on=meaning-risk'], failed)):
                    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/yomiyasu_diff.py'),
                                             str(old), str(new)] + flags, capture_output=True, text=True)
                    self.assertEqual(result.returncode, code, result.stdout + result.stderr)

    def test_addition_time_for_full_rewrite(self):
        # 合成の例だけで6万字を超える書き換えを作り、既存の文の組は測定の外で一度だけ作る。
        old, new = EXAMPLES['S2']
        old, new = (old + '\n') * 3600, (new + '\n') * 3600
        self.assertGreaterEqual(min(len(old), len(new)), 60000)
        full, sides = diff._build_full_diff(old, new, None)
        groups = diff._sentence_pairs(sides, full)
        masks = (diff._Masker(sides, 0), diff._Masker(sides, 1))
        durations = []
        for _ in range(3):
            start = time.perf_counter()
            diff._addition_risks(sides, groups, [], masks)
            durations.append(time.perf_counter() - start)
        self.assertLess(statistics.median(durations), 0.3, durations)


sys.path.insert(0, str(ROOT / 'tests'))
from test_v200_check import CheckCase


class CheckAddition(CheckCase):
    def test_run_counts_state_and_promise(self):
        old = self.write('old.md', EXAMPLES['S1'][0])
        new = self.write('new.md', EXAMPLES['S1'][1])
        result = self.check_json('run', '--source', old, '--final', new, '--fail-on', 'meaning-risk', code=1)
        self.assertTrue(result['fail_on_hit'])
        self.assertGreaterEqual(result['fail_on_meaning_risk_count'], 2)
        result = self.check('run', '--source', old, '--final', new)
        self.assertIn('状態の語が消えた', result.stdout)
        self.assertIn('原文にない書き手の約束', result.stdout)

    def test_no_addition_keeps_run_lines(self):
        for name in ('SN1', 'PN1', 'RN1'):
            _, _, lines = self.run_pair(*EXAMPLES[name], names=(name + '-old.md', name + '-new.md'))
            expected = BASELINE['check_lines'][name]
            stable = [line for line in lines if not line.startswith(('検査を実行しました', 'yomiyasu-check:', '記録:'))]
            self.assertEqual(stable, expected)
            self.assertFalse(any('状態の語が消えた' in line or '原文にない書き手の約束' in line for line in lines))


if __name__ == '__main__':
    unittest.main()
