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

    def test_deleted_sentence_is_not_reported(self):
        self.assert_changes("原因は設定ミスだとされる。対策は来週から始める。", "対策は来週から始める。")


class TestOutputShape(unittest.TestCase):
    def test_existing_keys_are_kept_and_type_changes_is_added(self):
        result = yomiyasu_diff.diff("資料を共有してください。\n", "資料を共有します。\n")
        self.assertEqual(list(result), ["markers", "new_words", "lost_words", "structure", "spans", "logic", "bold",
                                        "endings", "type_changes"])
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
