#!/usr/bin/env python3
"""v1.1.2: 推敲の前後で文を対応させ、文の種類を示す印（伝聞・推量・意見・例え・依頼）の消失と追加を候補にする。"""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


def changes(orig, rewrite):
    return yomiyasu_diff.diff(orig + "\n", rewrite + "\n")["type_changes"]


def kinds(entries, side):
    return [mark["kind"] for entry in entries for mark in entry[side]]


class TestMeaningShifts(unittest.TestCase):
    """SKILL.mdの「文の種類」で防ぎたい4つのずれ。"""

    def test_hearsay_to_assertion(self):
        found = changes("原因は設定ミスだとされる。", "原因は設定ミスだ。")
        self.assertEqual(kinds(found, "lost"), ["伝聞"])
        self.assertEqual(found[0]["lost"][0]["hits"], ["とされる"])
        self.assertEqual(found[0]["orig"], "原因は設定ミスだとされる。")
        self.assertEqual(found[0]["rewrite"], "原因は設定ミスだ。")

    def test_simile_to_assertion(self):
        self.assertIn("例え", kinds(changes("机はまるで戦場のようだ。", "机は戦場だ。"), "lost"))

    def test_opinion_to_fact(self):
        self.assertEqual(kinds(changes("この方式は遅いと思う。", "この方式は遅い。"), "lost"), ["意見"])

    def test_request_to_explanation(self):
        self.assertEqual(kinds(changes("資料を共有してください。", "資料を共有します。"), "lost"), ["依頼・決まり"])

    def test_other_hearsay_and_simile_forms(self):
        for orig, rewrite, kind in (("明日は雨が降るそうだ。", "明日は雨が降る。", "伝聞"),
                                    ("障害は設定ミスが原因とされる。", "障害は設定ミスが原因だ。", "伝聞"),
                                    ("担当者によると、修正は済んでいる。", "修正は済んでいる。", "伝聞"),
                                    ("新しい版では起動が速くなったらしい。", "新しい版では起動が速くなった。", "推量"),
                                    ("彼の机はまるで戦場のようだ。", "彼の机は散らかっている。", "例え")):
            with self.subTest(orig=orig):
                self.assertIn(kind, kinds(changes(orig, rewrite), "lost"))


class TestPerSentenceComparison(unittest.TestCase):
    def test_marks_moved_between_sentences_do_not_cancel(self):
        found = changes("Aは速いらしい。Bは遅い。", "Aは速い。Bは遅いだろう。")
        self.assertEqual([(entry["orig"], kinds([entry], "lost"), kinds([entry], "added")) for entry in found],
                         [("Aは速いらしい。", ["推量"], []), ("Bは遅い。", [], ["推量"])])

    def test_split_sentence_keeps_the_mark(self):
        self.assertEqual(changes("Aは速いらしいが、Bは遅い。", "Aは速いらしい。Bは遅い。"), [])

    def test_unchanged_marks_are_quiet(self):
        for orig, rewrite in (("原因は設定ミスだとされる。", "原因は、設定ミスだとされる。"),
                              ("机はまるで戦場のようだ。", "机は、まるで戦場のようだ。"),
                              ("資料を共有してください。", "資料を、共有フォルダに置いてください。")):
            with self.subTest(orig=orig):
                self.assertEqual(changes(orig, rewrite), [])


class TestSameTypeRewrites(unittest.TestCase):
    """言い方が変わっても種類が同じなら出さない（コーパスで見つけた形）。"""

    def test_same_type_different_forms(self):
        for orig, rewrite in (("木曜までに私へ連絡をください。", "木曜までに私へ連絡してください。"),
                              ("作業前に保存をお願いします。", "作業前に保存してください。"),
                              ("下記のとおりご対応をお願いします。", "下記のとおりご対応ください。"),
                              ("キャッシュ設計を自前で固める必要がある。", "キャッシュ設計を自前で実装しなければならない。"),
                              ("最大の成果であったと考える。", "最大の成果だったと考えている。")):
            with self.subTest(orig=orig):
                self.assertEqual(changes(orig, rewrite), [])

    def test_fact_to_obligation_is_reported(self):
        found = changes("上限値もキャパシティ計画の対象だと改めて認識しました。", "上限値もキャパシティ計画の対象にすべきだと認識しました。")
        self.assertEqual(kinds(found, "added"), ["依頼・決まり"])

    def test_closing_greeting_is_not_a_request(self):
        self.assertEqual(changes("以上です。よろしくお願いします。", "以上です。"), [])


class TestUnrelatedUses(unittest.TestCase):
    """種類と関係のない「そうだ」「ように」「という」では出さない。"""

    def test_unrelated_forms_are_quiet(self):
        for orig, rewrite in (("空を見ると、雨が降りそうだ。", "空を見ると、雨が降る気配がある。"),
                              ("ログを読めるように設定する。", "ログを読める設定にする。"),
                              ("ツールは「よみやす」という名前で公開する。", "ツールは「よみやす」の名で公開する。"),
                              ("この関数はべき乗を計算する。", "この関数は累乗を計算する。"),
                              ("しかるべき手続きを経て公開する。", "必要な手続きを経て公開する。")):
            with self.subTest(orig=orig):
                self.assertEqual(changes(orig, rewrite), [])


class TestReviewedCases(unittest.TestCase):
    """公開前の反証で見つかった誤検知と取りこぼし（v1.1.2）。"""

    def assert_changes(self, orig, rewrite, lost=(), added=()):
        found = changes(orig, rewrite)
        self.assertEqual(sorted(kinds(found, "lost")), sorted(lost), found)
        self.assertEqual(sorted(kinds(found, "added")), sorted(added), found)

    def test_joined_and_split_sentences_keep_their_marks(self):
        for orig, rewrite in (
                ("昨夜の障害の原因は、設定ファイルに残っていた古い接続先の記述だった。担当者によると、修正済みだという。",
                 "昨夜の障害の原因は、設定ファイルに残っていた古い接続先の記述で、担当者によると修正済みだという。"),
                ("新しい検索機能は来月の定例リリースで全ユーザーに公開する予定です。詳細は担当者に確認してください。",
                 "新しい検索機能は来月の定例リリースで全ユーザーに公開する予定なので、詳細は担当者に確認してください。"),
                ("新しい版では起動処理を見直して読み込みの待ち時間を減らしたので、起動は速くなったそうだ。",
                 "新しい版では起動処理を見直して、読み込みの待ち時間を減らした。起動は速くなったそうだ。"),
                ("旧版は遅いと思うが、新しい版ではキャッシュを入れたので応答が大きく改善した。",
                 "旧版は遅いと思う。新しい版ではキャッシュを入れたので、応答が大きく改善した。"),
                ("担当者によると原因は一つ——設定ファイルの記述ミスだ。", "担当者によると、原因は設定ファイルの記述ミスだ。"),
                ("新しい版は**起動が速いらしい**。", "新しい版は起動が速いらしい。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)

    def test_marks_lost_inside_joined_or_similar_sentences(self):
        self.assert_changes("この方式は遅いと思う。ほかの方式も試したい。Bは安定している。",
                            "この方式は遅いので、ほかの方式も試したい。Bは安定していると思う。", lost=["意見"], added=["意見"])
        self.assert_changes("ノード1は応答していないかもしれない。ノード2は応答していない。ログは残っている。",
                            "ノード1は応答していない。ノード2は応答していない。ログは残っているだろう。", lost=["推量"], added=["推量"])
        self.assert_changes("1号機は停止したとされる。2号機は停止した。", "1号機は停止した。2号機も停止した。", lost=["伝聞"])
        self.assert_changes("担当者によると、復旧は明日になる。\n\n詳細は以下のとおり。\n\n担当者によると、復旧は明日になる。",
                            "担当者によると、復旧は明日になる。\n\n詳細は以下のとおり。\n\n復旧は明日になる。", lost=["伝聞"])
        self.assert_changes("まるで戦場のような机——片付けが必要だ。", "散らかった机——片付けが必要だ。", lost=["例え"])
        self.assert_changes("まるで迷路――それが当時のコードベースだった。", "当時のコードベースは迷路だった。", lost=["例え"])

    def test_unrelated_words_are_not_marks(self):
        for orig, rewrite in (("今回の改善は本当に素晴らしい。", "今回の改善は見事だ。"),
                              ("春らしい陽気が続いた。", "暖かい日が続いた。"),
                              ("いかにも彼らしい判断だった。", "彼が選びそうな判断だった。"),
                              ("この作業量なら、金曜には間に合いそうです。", "この作業量なら、金曜には間に合う見込みです。"),
                              ("この進め方で問題ないでしょうか。", "この進め方で問題ありませんか。"),
                              ("レビューでこの不具合は見落とされた。", "レビュー担当者がこの不具合を見落とした。"),
                              ("移行後、応答時間は驚くべき速さで改善した。", "移行後、応答時間は予想を大きく超える速さで改善した。"),
                              ("1日100件と考えると、1か月で約3000件になる。", "1日100件なら、1か月で約3000件になる。"),
                              ("場合によると、再起動が要る。", "再起動が要ることもある。"),
                              ("「どこに置いた？」と聞かれる回数が減った。", "「どこに置いた？」と聞く回数が減った。"),
                              ("二つ目は、判断をADRに残すこと。", "二つ目は、判断をADRに記録すること。"),
                              ("どうしたのかと聞いた。", "どうしたのかと尋ねた。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)

    def test_same_kind_in_other_words(self):
        for orig, rewrite in (("どうやらサーバーが落ちたみたいだ。", "どうやらサーバーが落ちたようだ。"),
                              ("先方の担当者は来週から休暇に入るという。", "先方の担当者は来週から休暇に入るといいます。"),
                              ("設定を反映するには、サーバーを再起動する必要があります。", "設定を反映するには、サーバーの再起動が必要です。"),
                              ("迷惑メールに振り分けられた可能性があります。", "迷惑メールに振り分けられたのかもしれません。"),
                              ("以上、よろしくお願い致します。", "以上です。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)

    def test_more_forms_are_marks(self):
        for orig, rewrite, kind in (("この手法は高速だと言われている。", "この手法は高速だ。", "伝聞"),
                                    ("売上は前年より減ると見られる。", "売上は前年より減る。", "推量"),
                                    ("この方式が最適だと私は考える。", "この方式が最適だ。", "意見"),
                                    ("作業前に必ず保存しなければいけません。", "作業前に保存します。", "依頼・決まり"),
                                    ("資料を金曜までに共有して下さい。", "資料を金曜までに共有します。", "依頼・決まり"),
                                    ("原因は設定ミスらしかった。", "原因は設定ミスだった。", "推量"),
                                    ("来月から料金が上がると聞いています。", "来月から料金が上がります。", "伝聞"),
                                    ("本番では管理者権限で実行してはいけません。", "本番では管理者権限で実行します。", "依頼・決まり")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite, lost=[kind])


class TestReleaseReviewCases(unittest.TestCase):
    """公開前レビュー（v1.1.2）で見つかった、境界の挿入、活用、例えの範囲、移した文。"""

    def assert_changes(self, orig, rewrite, lost=(), added=()):
        found = changes(orig, rewrite)
        self.assertEqual(sorted(kinds(found, "lost")), sorted(lost), found)
        self.assertEqual(sorted(kinds(found, "added")), sorted(added), found)

    def test_marks_added_at_sentence_edges(self):
        self.assert_changes("修正は済んでいる。", "担当者によると、修正は済んでいる。", added=["伝聞"])
        self.assert_changes("昨夜の障害は解消した。修正は済んでいる。", "昨夜の障害は解消した。担当者によると、修正は済んでいる。", added=["伝聞"])
        self.assert_changes("Aは速い", "Aは速いらしい", added=["推量"])
        self.assert_changes("- 本番では管理者権限で実行する\n- 実行前にバックアップを取る",
                            "- 本番では管理者権限で実行するべき\n- 実行前にバックアップを取る", added=["依頼・決まり"])

    def test_new_sentence_between_is_not_a_prefix(self):
        self.assert_changes("障害は解消した。修正は済んでいる。", "障害は解消した。担当者によると原因は設定だ。修正は済んでいる。")

    def test_conjugated_forms_keep_their_kind(self):
        for orig, rewrite in (("移行の前に、運用チームへ申請する必要があり、申請には一週間かかる。", "移行の前に、運用チームへ申請する必要がある。申請には一週間かかる。"),
                              ("この方式では遅いと考え、別の方式を試した。", "この方式では遅いと考える。そこで別の方式を試した。"),
                              ("原因は設定ミスらしい。ただし確証はない。", "原因は設定ミスらしいが、確証はない。"),
                              ("サーバーが落ちたようだ。再起動した。", "サーバーが落ちたようなので、再起動した。"),
                              ("明日は雨が降るそうだ。傘を持っていく。", "明日は雨が降るそうなので、傘を持っていく。"),
                              ("期限までに提出しなければならない。遅れると受理されない。", "期限までに提出しなければならず、遅れると受理されない。"),
                              ("検証にDBの起動が必要になり、単体テストが難しい。", "検証するにはDBを起動する必要があり、単体テストが難しい。"),
                              ("追加の統制が必要となる。", "開発者は認可を別途実装しなければならない。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)

    def test_simile_forms_and_scope(self):
        for orig, rewrite in (("彼の机はまるで戦場のようであった。", "彼の机はまるで戦場のようだった。"),
                              ("まるで夢みたいだった。", "まるで夢のようだった。"),
                              ("まるで戦場のようで、誰も近づかなかった。", "まるで戦場のようだった。誰も近づかなかった。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)
        self.assert_changes("まるで迷路のようなコードで、どうやら誰も全体を把握していないようだ。",
                            "まるで迷路のようなコードで、誰も全体を把握していない。", lost=["推量"])

    def test_moved_sentence_that_lost_its_mark(self):
        self.assert_changes("原因は設定ミスだとされる。対策は来週から始める。再発防止の手順も見直す。",
                            "対策は来週から始める。再発防止の手順も見直す。原因は設定ミスだ。", lost=["伝聞"])

    def test_moved_sentence_unchanged_is_quiet(self):
        self.assert_changes("原因は設定ミスだとされる。対策は来週から始める。再発防止の手順も見直す。",
                            "対策は来週から始める。再発防止の手順も見直す。原因は設定ミスだとされる。")

    def test_marks_swapped_between_short_sentences(self):
        for orig, rewrite, kind in (("費用は安いとされています。品質は高いです。", "費用は安いです。品質は高いとされています。", "伝聞"),
                                    ("新機能は便利だと思います。導入は来月です。", "新機能は便利です。導入は来月だと思います。", "意見"),
                                    ("在庫は少ないかもしれません。出荷は明日です。", "在庫は少ないです。出荷は明日かもしれません。", "推量")):
            with self.subTest(orig=orig):
                found = changes(orig, rewrite)
                self.assertEqual([(entry["orig"], kinds([entry], "lost"), kinds([entry], "added")) for entry in found],
                                 [(orig.split("。")[0] + "。", [kind], []), (orig.split("。")[1] + "。", [], [kind])])

    def test_request_turned_into_description_after_rewording(self):
        self.assert_changes("ログの保存先は管理画面から変更してください。詳細は担当者に確認してください。",
                            "管理画面でログの保存先を変える。詳しくは担当者に聞いてください。", lost=["依頼・決まり"])

    def test_deleted_sentence_is_not_reported(self):
        self.assert_changes("原因は設定ミスだとされる。対策は来週から始める。", "対策は来週から始める。")


class TestPrepublishReviewCases(unittest.TestCase):
    """公開直前の点検（v1.1.2）で見つかった、文を消しただけの書き換え、例えと意見の重なり、印でない用法。"""

    def assert_changes(self, orig, rewrite, lost=(), added=()):
        found = changes(orig, rewrite)
        self.assertEqual(sorted(kinds(found, "lost")), sorted(lost), found)
        self.assertEqual(sorted(kinds(found, "added")), sorted(added), found)

    def test_deleting_a_sentence_does_not_pair_it_with_a_kept_one(self):
        for orig, rewrite in (
                ("新しいキャッシュは応答を速くする。運用の手間も減る。まとめると、新しいキャッシュは導入する価値があるでしょう。",
                 "新しいキャッシュは応答を速くする。運用の手間も減る。"),
                ("この機能は速い。この機能は安定しているかもしれない。", "この機能は速い。"),
                ("Aの設定は管理画面から変更する。Bの設定は管理画面から変更してください。", "Bの設定は管理画面から変更してください。"),
                ("ログの保存先は管理画面から変更できます。ログの保存先は管理画面から変更してください。", "ログの保存先は管理画面から変更してください。"),
                ("サーバーの設定を見直してください。サーバーの設定は来週見直す。", "サーバーの設定は来週見直す。"),
                ("ログの保存期間は30日とされる。ログの保存期間は30日だ。設定は共有フォルダにある。", "ログの保存期間は30日だ。設定は共有フォルダにある。"),
                ("新しい版では起動処理を見直したので、起動が速くなったそうだ。まとめると、新しい版では起動が速くなった。",
                 "新しい版では起動処理を見直したので、起動が速くなったそうだ。"),
                ("新しい版は起動が速いが、古い版は起動が遅いとされる。要するに、古い版は起動が遅い。", "新しい版は起動が速い。古い版は起動が遅いとされる。"),
                ("検索機能は来月公開されるそうだ。\n\n## まとめ\n\n検索機能は来月公開される。", "検索機能は来月公開されるそうだ。"),
                ("この機能は便利だと思います。つまり、この機能は便利です。", "この機能は便利だと思います。"),
                ("ログの保存先は来週変わる。新しいキャッシュは来週変わると思う。新しいキャッシュは速い。", "ログの保存先は来週変わる。新しいキャッシュは速い。"),
                ("ログの保存先は来週変わる。この機能は来週変わるとされる。この機能は来週変わると思う。", "ログの保存先は来週変わる。この機能は来週変わると思う。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)

    def test_simile_keeps_an_opinion_mark_at_the_same_place(self):
        self.assert_changes("まるで昨日のことのように思います。", "まるで昨日のことのようです。", lost=["意見"])
        self.assert_changes("彼はまるで別人のように感じられる。", "彼はまるで別人のようだ。", lost=["意見"])
        self.assert_changes("まるで時間が止まったように感じられた。", "時間が止まったように感じられた。", lost=["例え"])
        self.assert_changes("街はまるで別世界のように思います。", "街は別世界のように思います。", lost=["例え"])

    def test_uses_that_are_not_marks(self):
        for orig, rewrite in (("画像は必要になるまで読み込まない。", "画像は表示する直前に読み込む。"),
                              ("認証が必要になったら、設定を追加する。", "認証を使うときは、設定を追加する。"),
                              ("古い設定は不必要になった。", "古い設定は使わなくなった。"),
                              ("あの人らしいがんばりだった。", "あの人ならではのがんばりだった。"),
                              ("このロボットの動きは人間らしいが、反応は遅い。", "このロボットの動きは人間に近いが、反応は遅い。"),
                              ("どのようなのですか。", "どんなものですか。"),
                              ("1日100件と考え、1か月で約3000件と見積もった。", "1日100件として、1か月で約3000件と見積もった。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)
        self.assert_changes("再起動が必要になる。", "再起動する。", lost=["依頼・決まり"])


class TestRecheckCases(unittest.TestCase):
    """公開直前の再点検（v1.1.2）で見つかった、隣の文の印の取り違え、閉じかっこ、移してつないだ文、組にする順番、印の除外の行き過ぎ。"""

    def assert_changes(self, orig, rewrite, lost=(), added=()):
        found = changes(orig, rewrite)
        self.assertEqual(sorted(kinds(found, "lost")), sorted(lost), found)
        self.assertEqual(sorted(kinds(found, "added")), sorted(added), found)

    def test_deleted_neighbor_does_not_take_the_new_mark(self):
        self.assert_changes("障害の原因は設定ミスだとされる。古い手順は今後使わない。", "障害の原因は設定ミスかもしれない。",
                            lost=["伝聞"], added=["推量"])
        self.assert_changes("障害の原因は設定ミスかもしれない。復旧の手順は来週まとめる。", "障害の原因は設定ミスだとされる。",
                            lost=["推量"], added=["伝聞"])
        self.assert_changes("障害の原因は設定ミスだとされる。古いログは消した。対策は来週から始める。",
                            "障害の原因は設定ミスだという。対策は来週から始める。")
        self.assert_changes("ログの保存先は30日になるかもしれない。新しい版は来週変わる。",
                            "新しい版は来週変わる。ログの保存先は30日になるとされる。", lost=["推量"], added=["伝聞"])

    def test_moved_sentence_next_to_a_closing_bracket(self):
        self.assert_changes("原因は設定ミスだとされる。（詳細は後述する。）", "（詳細は後述する。）原因は設定ミスだ。", lost=["伝聞"])
        self.assert_changes("原因は設定ミスだとされる。担当者は「明日直す。」", "担当者は「明日直す。」原因は設定ミスだ。", lost=["伝聞"])

    def test_moved_and_joined_sentence_that_lost_its_mark(self):
        self.assert_changes("原因は設定ミスだとされる。対策は来週から始める。", "対策は来週から始め、原因は設定ミスだ。", lost=["伝聞"])
        self.assert_changes("出荷は明日らしい。新しい版は起動が速い。", "新しい版は起動が速いが、出荷は明日だ。", lost=["推量"])

    def test_pairing_prefers_the_closest_sentence(self):
        self.assert_changes("新しい版は来月公開する。新しい版は速くなる。新しい版は設定の移行が必要になる。詳しい手順は別の資料にまとめた。",
                            "新しい版は設定を移せば使える。新しい版は来月公開する。詳しい手順は別の資料にまとめた。", lost=["依頼・決まり"])
        self.assert_changes("検索機能は来月公開する。検索画面の表示は変わるかもしれない。検索結果の並び順は変わると思う。",
                            "検索機能は来月公開する。検索結果の並び順は変わるかもしれない。", lost=["意見"], added=["推量"])
        self.assert_changes("新しい版は来月の定例リリースで公開する。料金は据え置くらしい。旧版のサポートは年内で終了する予定です。移行は管理画面から行えると思う。",
                            "料金は据え置くらしい。新しい版は来月の定例リリースで公開する。移行は管理画面から行えるはずだ。旧版のサポートは年内で終了する予定です。",
                            lost=["意見"], added=["推量"])
        self.assert_changes("画面はまるで別のアプリのように動く。操作の手順は前の版から何も変わっていないので、利用者向けの説明会は開かない。画面はまるで迷路のように思う。",
                            "操作の手順は前の版から何も変わっていないので、利用者向けの説明会は開かない。画面はまるで別のアプリのように動く。")

    def test_marks_kept_after_narrowing_the_exclusions(self):
        for orig, rewrite, kind in (("原因は設定ミスらしいが確証はない。", "原因は設定ミスだが確証はない。", "推量"),
                                    ("犯人は学生らしい。", "犯人は学生だ。", "推量"),
                                    ("投稿したのはプロらしい。", "投稿したのはプロだ。", "推量"),
                                    ("最適なのは案2と考える。", "最適なのは案2だ。", "意見"),
                                    ("来場者は500人と考えています。", "来場者は500人です。", "意見"),
                                    ("再起動が必要になったらしい。", "再起動したらしい。", "依頼・決まり"),
                                    ("再起動が必要になったらしい。", "再起動が必要になった。", "推量")):
            with self.subTest(orig=orig, rewrite=rewrite):
                self.assert_changes(orig, rewrite, lost=[kind])

    def test_joined_with_tou_ga(self):
        self.assert_changes("DLQの件数が閾値を超えると、システムはSlackへ通知するという。コンシューマ側で冪等性を確保する。",
                            "DLQの件数が閾値を超えると、システムはSlackへ通知するというが、コンシューマ側で冪等性を確保する。")


class TestFinalCheckCases(unittest.TestCase):
    """公開前の最終確認（v1.1.2）で見つかった、見出しや箇条書きを消した書き換え、短く書き直した文、敬体の似た文、引用のあとの短い部分、折り返した文。"""

    def assert_changes(self, orig, rewrite, lost=(), added=()):
        found = changes(orig, rewrite)
        self.assertEqual(sorted(kinds(found, "lost")), sorted(lost), found)
        self.assertEqual(sorted(kinds(found, "added")), sorted(added), found)

    def test_deleting_a_heading_or_list_item_is_quiet(self):
        for orig, rewrite in (
                ("## 原因\n\nタイムアウトが増えたのは、接続プールの設定が原因だという。\n\n## 対応\n\n上限を40に上げる。",
                 "タイムアウトが増えたのは、接続プールの設定が原因だという。上限を40に上げる。"),
                ("## 背景\n\n- 問い合わせが増えた\n- 回答に時間がかかる\n\n担当者によると、回答に時間がかかるらしい。",
                 "## 背景\n\n- 問い合わせが増えた\n\n担当者によると、回答に時間がかかるらしい。"),
                ("**結論**\n\n移行は年内に終わるという結論だと思う。", "移行は年内に終わるという結論だと思う。"),
                ("- 来週変わる\n- 速い\n\n管理画面の表示は来週変わるかもしれない。", "- 速い\n\n管理画面の表示は来週変わるかもしれない。")):
            with self.subTest(orig=orig):
                self.assert_changes(orig, rewrite)

    def test_shortened_sentence_that_lost_its_mark(self):
        self.assert_changes("重い集計クエリが接続を長く占有し、待機中のリクエストが30秒のタイムアウトに達して504を返したらしい。障害は解消した。",
                            "重い集計クエリで504を返した。障害は解消した。", lost=["推量"])

    def test_similar_polite_sentences(self):
        self.assert_changes("旧版のサポートは年内で終わります。検索画面の設定を見直しました。新版のサポートも年内で終わるでしょう。",
                            "検索画面の設定を見直しました。新版のサポートも年内で終わります。", lost=["推量"])

    def test_short_part_after_a_quote(self):
        self.assert_changes("設定は見直した。テストも増やした。「旧版は年内で止める。」と答えたらしい。",
                            "「旧版は年内で止める。」と答えた。設定は見直した。テストも増やした。", lost=["推量"])

    def test_wrapped_sentence_moved_onto_one_line(self):
        self.assert_changes("障害は解消した。\n自分は何も知らないということを認め、\nこう聞くようにしたと思う。",
                            "自分は何も知らないということを認め、こう聞くようにしたと思う。\n障害は解消した。")


class TestOutputShape(unittest.TestCase):
    def test_existing_keys_are_kept_and_type_changes_is_added(self):
        result = yomiyasu_diff.diff("資料を共有してください。\n", "資料を共有します。\n")
        # v2.0.0 の形式2（DESIGN-interfaces.md 2.8）。v1.1.2 の9キーは名前と間の順を保ち、前後に新しいキーが付く
        # G7（DESIGN-reader-doctype.md 9.4）: not_judged の次に context
        self.assertEqual(list(result), ["format", "format_version", "tool_version", "status", "changed",
                                        "candidate_count", "meaning_risk_count", "fail_on_meaning_risk_count",
                                        "not_judged", "context", "meaning_risks",
                                        "markers", "new_words", "lost_words", "structure", "spans", "logic", "bold",
                                        "endings", "type_changes", "full_diff"])
        self.assertEqual(set(result["type_changes"][0]), {"orig", "rewrite", "lost", "added"})

    def test_report_has_the_new_heading_only_when_needed(self):
        changed = yomiyasu_diff.report(yomiyasu_diff.diff("原因は設定ミスだとされる。\n", "原因は設定ミスだ。\n"))
        self.assertIn("■ 文の種類の印が変わった文", changed)
        self.assertIn("消えた印: 伝聞（とされる）", changed)
        self.assertIn("原因は設定ミスだとされる。", changed)
        quiet = yomiyasu_diff.report(yomiyasu_diff.diff("原因は設定ミスだとされる。\n", "原因は、設定ミスだとされる。\n"))
        self.assertNotIn("文の種類の印", quiet)

    def test_cli_json_includes_type_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / "a.md", Path(folder) / "b.md"
            before.write_text("この方式は遅いと思う。\n", encoding="utf-8")
            after.write_text("この方式は遅い。\n", encoding="utf-8")
            process = subprocess.run([sys.executable, str(ROOT / "scripts" / "yomiyasu_diff.py"), str(before), str(after), "--json"],
                                     capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout)["type_changes"][0]["lost"][0]["kind"], "意見")

    def test_standalone_ending_changes_is_unchanged(self):
        self.assertEqual(yomiyasu_diff.ending_changes("Aは速いらしい。Bは遅い。", "Aは速い。Bは遅いだろう。"),
                         [{"orig": "Bは遅い。", "orig_kind": "常体", "rewrite": "Bは遅いだろう。", "rewrite_kind": "推量・考え"}])


if __name__ == "__main__":
    unittest.main()
