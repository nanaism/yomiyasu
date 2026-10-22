#!/usr/bin/env python3
"""v2.0.0-beta: check の固めの試験（設計 10.8 の C-44、C-45、C-46、C-47、C-41 と、
check の段の問いへの勧めのうち実装が要るもの）。

- C-44 の似かたのしきい値は、tests/corpus の推敲の48組（原文 → 推敲）と、正しい新規作成の組（下の COMPOSITIONS。
  評価の題材とは別に作った合成の文）で測って決めた。
- 実装の前に書き、v2.0.0 の check の段（45a5885）で落ちることを確かめてから実装した。文はすべて合成。
- 動かし方と一時フォルダの扱いは test_v200_check.py の CheckCase と同じ。
"""

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portable import paced_limit, timing_clock  # noqa: E402
from test_v200_check import (  # noqa: E402
    CHECK, CheckCase, ROOT, SCRIPTS, SKILL_MD, TOOL_NAMES, FINALIZE_FILE, FINALIZE_STDIN, RUN_COMPOSE_FIRST, RUN_REWRITE_FIRST,
    RUN_REWRITE_FIRST_NO_CANDIDATES, RUN_SAME_FINAL, RUN_AFTER_FIX, RUN_OVER_LIMIT, VERIFY_LINE1,
    inject_cli_code, record_digest, sha256_file, split_lines, text_sha256, tree_digest,
)

CORPUS = ROOT / "tests" / "corpus"

# C-44: 1行目に添える文（10.8）
C44_NOTE = "資料の1つが最終稿とよく似ているので、原文とみなして diff も実行しました。書き直す前の文章なら --source に渡してください。"
# C-45: 資料と最終稿が同じ中身のときの誤りの文（10.8）
C45_ERROR = ("資料と最終稿が同じ中身です。資料には、利用者から受け取った資料を渡してください。"
             "書き直す前の文章なら --source に渡してください。")
# C-47: 空の最終稿（10.8。勧め47の続きの文を足した）
C47_ERROR = "最終稿が空です。書き終えた最終稿を渡してください。"
# 42 の (1): partial の1行目の最後に足す文（5.3）
PARTIAL_TAIL = "verify は実行せず、完了報告にこの出力の2行目を写してください。"
# 42 の (3) と 5 の案: 途中で最終稿が変わったときの1行目と3行目
FINAL_CHANGED_DURING_RUN = "最終稿が検査の途中で変わりました。変え終えてから yomiyasu_check.py run をもう一度実行してください。"
SUMMARY_NONE_CHANGED = "実行した検査: なし（途中で最終稿が変わったため）"
# 42 の (2): verify が、時間切れか内部エラーで終わった検査の記録を見つけたとき
VERIFY_PARTIAL_LINE = ("記録の {}で終わっています。run をもう一度実行しても同じなら、完了報告に run の出力の2行目を写し、"
                       "「実行しなかった検査」に「{}」と書いてください。")
# 48: verify と run の注記
NEWER_ATTEMPT_NOTE = "この実行には、あとで検査した別の本文があります。直しが失われていないか確かめてください。"
RECORDED_SOURCE_NOTE = "渡した本文は、記録では原文か資料として使われています。--final には最終稿を渡してください。"
SOURCE_WAS_FINAL_NOTE = ("原文が、前に最終稿として検査した本文と同じです。続けて直す依頼でなければ、原文を上書きしたか、"
                         "原文と最終稿を逆に渡していないか確かめてください。")
# 55: --state-dir で記録したときの {仕上げ} と、verify の no_record の3行目
FINALIZE_STATE_DIR = "提出の直前に、本文を変えずに verify --state-dir {} を1回実行してください。"
NO_RECORD_LINE3 = "記録: なし（探した状態フォルダ: {}）"
# 56: 本文だけを返す指定もあるので、verify の executed は「完了報告を付けるときは」。run --stdin の {仕上げ} は、
# ファイルと同じく返す直前の verify を案内する（CheckCase.finalize_stdin。本文だけを返す依頼で verify が抜けたため）
VERIFY_EXECUTED_TAIL = "合格の判定ではありません。完了報告を付けるときは、この出力の2行目を写してください。"
# 57、58: 原文から本文が変わっていないとき
RUN_NO_CHANGE_NEW = ("検査を実行しました。原文から変更はありません。書き直したのに変更なしと出たときは、"
                     "原文を上書きしていないか確かめてください。")
RUN_NO_CHANGE_TEXT_SAME = ("検査を実行しました。原文から変更はありません（改行コード、BOM、末尾の改行だけが違います）。"
                           "書き直したのに変更なしと出たときは、原文を上書きしていないか確かめてください。")
VERIFY_TEXT_SAME_NOTE = "本文は記録と同じで、改行コード、BOM、末尾の改行だけが違います。run をもう一度実行しても修正には数えません。"
SAME_FILE_TAIL = ("元の版を取り出せないときは、最終稿を写して --source に渡さず、完了報告の「実行しなかった検査」に"
                  "「diff（原文を上書きしたため）」と書いてください。")
# 59: 記録を書かないときの4行目と {仕上げ}
UNRECORDED_DISCLAIMER = "この結果は検査を実行したことを示すだけで、意味が保たれたことや読みやすさの合格を示すものではありません。"
FINALIZE_NO_RECORD_NEW = ("完了報告の「実行しなかった検査」に「最終稿の照合（記録を残さない指定のため）」と書いてください"
                          "（記録を残さない指定なので verify はできません）。")
# 43 の1: 原文は同じで資料の集まりが違う記録が複数あるときの ambiguous の1行目（--source では絞れない）
AMBIGUOUS_MATERIALS = ("同じ最終稿に、資料の集まりが違う記録が複数あります。どの検査の記録を使うかを決められないので、"
                       "--run-id を付けて verify を実行してください。")
# 51: 実行IDの誤り
RUN_ID_ERROR_TAIL = "末尾の「.」と、Windows で使えない名前（CON、NUL、COM1 など）は使えません。"

# C-44 のしきい値（測って決めた値）
THRESHOLD = 0.53

# 正しい新規作成の組（資料 → 最終稿）。評価の題材とは別の内容で作った合成の文。
# minutes_close は、メモの言い回しを多く残した議事録で、しきい値にいちばん近い。
COMPOSITIONS = {
    "release": (
        [
            "# kasumi-sync 3.2 の変更点（メモ）\n\n"
            "- 同期の間隔の既定を 15 分から 5 分にした\n"
            "- 競合したファイルは上書きせず、名前に「（競合）」を付けて両方残す\n"
            "- 1 ファイルの上限を 2GB から 4GB に上げた\n"
            "- 古い設定ファイル（v1 形式）は読めなくなった。移行コマンドは kasumi migrate\n"
            "- Windows の長いパス（260 字を超える）は未確認\n",
            "# 問い合わせのまとめ（9月）\n\n"
            "- 競合で片方のファイルが消えたという問い合わせが 12 件\n"
            "- 同期が遅いという声が多い。ほとんどは間隔の既定が長いことによる\n",
        ],
        "## kasumi-sync 3.2 を公開しました\n\n"
        "kasumi-sync 3.2 では、9月に多く寄せられた問い合わせに合わせて、同期の動きを見直しました。\n\n"
        "### 同期の間隔を短くしました\n\n"
        "「同期が遅い」という声の多くは、既定の間隔が長いことが原因でした。そこで、同期の間隔の既定を 15 分から 5 分に"
        "変えました。設定で変えている場合は、その値がそのまま使われます。\n\n"
        "### 競合したファイルを両方残します\n\n"
        "これまでは、同じファイルを2か所で編集すると、片方が上書きされて消えることがありました（9月の問い合わせは 12 件）。"
        "3.2 からは上書きせず、片方の名前に「（競合）」を付けて、両方のファイルを残します。どちらを使うかは、中身を見比べて"
        "選んでください。\n\n"
        "### そのほかの変更\n\n"
        "1 ファイルの大きさの上限を 2GB から 4GB に上げました。\n\n"
        "古い形式（v1）の設定ファイルは、3.2 では読めません。更新の前に `kasumi migrate` を実行して、新しい形式に移して"
        "ください。\n\n"
        "なお、Windows で 260 字を超える長いパスを扱えるかは、まだ確かめていません。\n",
    ),
    "minutes": (
        [
            "11/6 開発会議メモ\n"
            "出席: 篠原、大森、片桐 / 欠席: 津田\n\n"
            "・ログイン画面の改修 → 片桐。デザイン案は 11/13 に出す\n"
            "・篠原: 二段階認証を必須にするかは営業と相談してから\n"
            "・検索が遅い件。大森が原因を調べた。索引がなかった。追加は来週\n"
            "・年末の休み中の当番は未定\n"
            "次回 11/13\n",
        ],
        "# 開発会議 議事録（11月6日）\n\n"
        "- 出席者: 篠原、大森、片桐\n"
        "- 欠席者: 津田\n\n"
        "## 決まったこと\n\n"
        "1. ログイン画面の改修は片桐さんが担当します。11月13日の会議でデザイン案を示します。\n"
        "2. 検索が遅い問題は、大森さんの調査で、索引がないことが原因と分かりました。来週、索引を追加します。\n\n"
        "## 持ち越したこと\n\n"
        "- 二段階認証を必須にするかどうか。篠原さんが営業部と相談してから決めます。\n"
        "- 年末の休み中の当番。まだ決まっていません。\n\n"
        "## 次回\n\n"
        "11月13日\n",
    ),
    "guide": (
        [
            "仕様メモ: 共有リンク\n"
            "- 期限は 1 日、7 日、30 日から選ぶ。既定は 7 日\n"
            "- パスワードは任意。8 文字以上\n"
            "- 期限が切れたリンクは 404 ではなく案内のページを出す\n"
            "- 管理者は全員の共有リンクを一覧で止められる\n",
            "よくある質問の下書き\n"
            "Q 期限を延ばせる? → 作り直す必要がある\n"
            "Q 誰が開いたか分かる? → 分からない（記録していない）\n",
        ],
        "## 共有リンクを作る\n\n"
        "ファイルの右上にある「共有」を押すと、共有リンクを作れます。作るときに、リンクを開ける期間を 1 日、7 日、30 日の"
        "中から選びます。何も選ばなければ 7 日です。\n\n"
        "リンクにはパスワードを付けることもできます。付ける場合は 8 文字以上にしてください。\n\n"
        "### 期限が切れたとき\n\n"
        "期限が切れたリンクを開くと、エラーではなく、期限が切れたことを知らせるページが表示されます。期限をあとから延ばす"
        "ことはできないので、続けて共有したいときはリンクを作り直してください。\n\n"
        "### 知っておいてほしいこと\n\n"
        "- だれがリンクを開いたかは記録していないため、確かめられません。\n"
        "- 管理者は、組織の全員が作った共有リンクを一覧で確認し、まとめて止められます。\n",
    ),
    "interview": (
        [
            "ヒアリングメモ（物流センター 現場リーダー）\n"
            "・ピッキングの紙のリストをやめたい。1日に3回は書き損じが出る\n"
            "・端末は手袋のまま押せるものがいい\n"
            "・朝8時から9時が一番混む。この時間に止まると困る\n"
            "・新人は最初の1週間、ベテランと組ませている\n",
        ],
        "# 物流センターでの聞き取りの報告\n\n"
        "現場のリーダーに、ピッキング作業の困りごとを聞きました。\n\n"
        "いま使っている紙のリストは、1日に3回ほど書き損じが出ており、やめたいという要望がありました。代わりの端末は、"
        "作業中に手袋を外さずに操作できるものが求められています。\n\n"
        "作業が最も混み合うのは朝8時から9時で、この時間帯に端末やシステムが止まると作業全体に響くとのことです。入れ替えの"
        "作業や更新は、この時間を避ける必要があります。\n\n"
        "なお、新人は最初の1週間、ベテランと組んで作業しています。新しい端末を入れる場合も、この組み合わせの中で使い方を"
        "覚えてもらう形が取りやすそうです。\n",
    ),
    "minutes_close": (
        [
            "4/22 定例メモ\n"
            "出席: 矢野、森田、北川\n\n"
            "■ 請求書の送付\n"
            "・森田: 先月から PDF の添付が届かない取引先が2社ある\n"
            "・送付先のアドレスを確認する → 森田（4/26まで）\n\n"
            "■ 新しい経費精算の仕組み\n"
            "・矢野: 5月から試したい。最初は営業部だけ\n"
            "・説明会の日程は未定\n\n"
            "次回: 4/29\n",
        ],
        "# 定例会議 議事録（4月22日）\n\n"
        "出席: 矢野、森田、北川\n\n"
        "## 請求書の送付\n\n"
        "森田さんから、先月から PDF の添付が届かない取引先が2社あると報告がありました。\n\n"
        "- 対応: 森田さんが、送付先のアドレスを確認する（4月26日まで）。\n\n"
        "## 新しい経費精算の仕組み\n\n"
        "矢野さんから、5月から試したいという提案がありました。最初は営業部だけで試します。\n\n"
        "- 未定: 説明会の日程は決まっていない。\n\n"
        "## 次回\n\n"
        "4月29日\n",
    ),
}


def corpus_pairs():
    """tests/corpus の推敲の48組（raw_ai か blacklist_ai の原文 → yomiyasu_rewritten の推敲）。tools/difftime.py と同じ組み方。"""
    pairs = []
    for path in sorted((CORPUS / "yomiyasu_rewritten").glob("*.md")):
        name = path.name
        source = CORPUS / ("blacklist_ai" if name.endswith("_bl.md") else "raw_ai") / (
            name[:-len("_bl.md")] + ".md" if name.endswith("_bl.md") else name)
        pairs.append((name, source.read_bytes(), path.read_bytes()))
    return pairs


def load_check():
    """check をこのプロセスに別の名前で読み込む（似かたの関数を直に呼ぶため。.pyc は作らない）。"""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("_yomiyasu_check_for_harden_test", str(CHECK))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


# メモの言い回しをほぼそのまま残し、敬称と句点を足して並べ直しただけの議事録（しきい値を測った組と同じ型）。
# 推敲の組と見分けられないので、原文とみなして diff も実行する（diff は止めずに足すだけ。しきい値を
# 超える新規作成）
MEMO_KEPT = (
    "9/30 運用会議メモ\n"
    "出席: 小松、千葉、仁科\n\n"
    "■ バックアップの失敗\n"
    "・千葉: 先週の土曜に夜間のバックアップが2回失敗した。容量不足\n"
    "・古い世代を消す設定を見直す → 千葉（10/3まで）\n\n"
    "■ 監視の通知\n"
    "・小松: 夜中の通知が多すぎる。半分は再起動で直る\n"
    "・通知の条件を変えるかは次回決める\n",
    "# 9/30 運用会議 議事録\n\n"
    "出席: 小松、千葉、仁科\n\n"
    "## バックアップの失敗\n\n"
    "- 千葉さん: 先週の土曜に夜間のバックアップが2回失敗した。容量不足。\n"
    "- 古い世代を消す設定を見直す（千葉さん、10/3まで）。\n\n"
    "## 監視の通知\n\n"
    "- 小松さん: 夜中の通知が多すぎる。半分は再起動で直る。\n"
    "- 通知の条件を変えるかは次回決める。\n",
)


class TestC44Similarity(unittest.TestCase):
    """C-44 の似かたの測り方としきい値。"""

    @classmethod
    def setUpClass(cls):
        cls.check = load_check()

    def similarity(self, material, final):
        decode = self.check.decode_source
        return self.check._similarity(decode(material)[0], decode(final)[0])

    def test_threshold_is_the_measured_value(self):
        self.assertEqual(self.check._SIMILAR_TO_SOURCE, THRESHOLD)

    def test_every_corpus_rewrite_reaches_the_threshold(self):
        pairs = corpus_pairs()
        self.assertEqual(len(pairs), 48)
        values = []
        for name, source, final in pairs:
            value = self.similarity(source, final)
            values.append(value)
            with self.subTest(pair=name):
                self.assertGreaterEqual(value, THRESHOLD)
        # 測った最小は 0.577（05_comparison_sonnet_formal_bl.md）。しきい値との間を 0.04 より狭めない
        self.assertGreaterEqual(min(values) - THRESHOLD, 0.04, min(values))

    def test_correct_compositions_stay_below_the_threshold(self):
        values = {}
        for name, (materials, final) in COMPOSITIONS.items():
            value = max(self.similarity(material.encode("utf-8"), final.encode("utf-8")) for material in materials)
            values[name] = value
            with self.subTest(case=name):
                self.assertLess(value, THRESHOLD)
        # いちばん近い minutes_close（0.495）も、しきい値との間を 0.03 より狭めない
        self.assertGreaterEqual(THRESHOLD - max(values.values()), 0.03, values)

    def test_both_directions_must_be_similar(self):
        """大きな資料（コーパスの原文を全部つないだもの）に短い最終稿のほとんどの2字組が含まれても、資料の側から見て
        重なりが少なければ、原文とみなさない（片側だけの割合で決めない）。"""
        big = b"\n".join(source for _, source, _ in corpus_pairs())
        for name, (materials, final) in COMPOSITIONS.items():
            with self.subTest(case=name):
                self.assertLess(self.similarity(big, final.encode("utf-8")), 0.1)
        _, source, final = corpus_pairs()[0]
        self.assertLess(self.similarity(big, final), 0.1)

    def test_spacing_and_width_do_not_change_the_value(self):
        """空白と改行、全角と半角（NFKC）の違いでは値が変わらない。"""
        material = "保存期間は30日です。\n手動で作ったものは消しません。\n"
        final = "保存期間は ３０日 です。 手動で作ったものは 消しません。"
        self.assertAlmostEqual(self.similarity(material.encode("utf-8"), final.encode("utf-8")), 1.0)

    def test_long_documents_are_fast(self):
        """6万字ほどの文書でも速い（文字数に比例する。lint と diff より十分に短い）。"""
        pairs = corpus_pairs()
        source = b"\n".join(source for _, source, _ in pairs) * 3
        final = b"\n".join(final for _, _, final in pairs) * 3
        self.assertGreater(len(source.decode("utf-8")), 60000)
        # 上限の秒数は、Windows の遅い機械では基準の処理の遅さの比で延ばす（portable.paced_limit）。時間は CPU 時間で測る
        clock = timing_clock()
        started = clock()
        self.similarity(source, final)
        elapsed = clock() - started
        limit, detail = paced_limit(0.5, elapsed)
        self.assertLess(elapsed, limit, detail)

    def test_composition_that_keeps_the_memo_wording_is_treated(self):
        """メモの言い回しをほぼそのまま残した新規作成は、推敲と見分けられないので、原文とみなす（しきい値を超える）。"""
        material, final = MEMO_KEPT
        self.assertGreaterEqual(self.similarity(material.encode("utf-8"), final.encode("utf-8")), THRESHOLD)


class TestC44Run(CheckCase):
    """C-44: 新規作成で資料の1つが最終稿とよく似ていれば、その資料を原文とみなして diff も実行する。"""

    SOURCE = "保存期間は3日です。手動で作ったバックアップは消しません。\n"
    FINAL = "保存期間は30日です。手動で作ったバックアップは消しません。\n"

    def compose_with_source_as_material(self, *extra):
        a = self.write("a.md", self.SOURCE)
        b = self.write("b.md", self.FINAL)
        process, lines = self.check_ok("run", "--material", a, "--final", b, *extra)
        return a, b, lines

    def test_source_given_as_material_runs_the_diff(self):
        a, b, lines = self.compose_with_source_as_material()
        self.assertEqual(lines[0], RUN_COMPOSE_FIRST + self.finalize_file() + C44_NOTE)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields["mode"], fields["checks"]), ("executed", "compose", "lint,diff,materials"))
        self.assertEqual(lines[2], "実行した検査: lint（最終稿）候補0件、diff（資料1→最終稿）変更あり 候補1件"
                                   "（うち意味が変わる恐れ1件）、資料との照合（資料1件→最終稿）資料にない数値・名前1件")
        self.assertIn("- 数値が変わった（1行目）: 3日 → 30日", lines)
        self.assertIn("■ 全文差分（変更 1か所。省略していません）", lines)
        path, record = self.record_from(lines)
        self.assertEqual((record["mode"], record["required_checks"]), ("compose", ["lint", "diff", "materials"]))
        self.assertIsNone(record["inputs"]["source"])
        material = record["inputs"]["materials"][0]
        self.assertIs(material["treated_as_source"], True)
        self.assertGreaterEqual(material["similarity"], THRESHOLD)
        diff = self.check_entry(record, "diff")
        self.assertEqual((diff["status"], diff["target"]),
                         ("ran", {"source": sha256_file(a), "final": sha256_file(b)}))
        self.assertEqual([entry["name"] for entry in record["checks"]], ["lint", "diff", "materials"])
        self.assertEqual(record["record_digest"], record_digest(record))
        result = self.check_json("run", "--material", a, "--final", b, "--new-run")
        self.assertEqual(result["diff"]["format"], "yomiyasu-diff")
        self.assertEqual([risk["basis"] for risk in result["diff"]["meaning_risks"] if risk["kind"] == "number"],
                         ["none"])

    def test_verify_requires_and_accepts_the_diff(self):
        a, b, lines = self.compose_with_source_as_material()
        status, fields = self.status(lines[1])
        verify_lines, verify_fields = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertEqual(verify_lines[0], VERIFY_LINE1["executed"].replace(
            "合格の判定ではありません。完了報告にこの出力の2行目を写してください。", VERIFY_EXECUTED_TAIL).format(
            checks="lint、diff、資料との照合"))
        self.assertEqual((verify_fields["mode"], verify_fields["checks"]), ("compose", "lint,diff,materials"))
        # フックや採点器が原文を知っていて --source を付けても、原文とみなした資料と同じなら executed
        self.assert_verify(self.check("verify", "--final", b, "--source", a), "executed", code=0)
        _, verify_fields = self.assert_verify(self.check("verify", "--final", b, "--replay"), "executed", code=0)
        self.assertEqual(verify_fields["replay"], "ok")

    def test_record_without_the_diff_is_not_executed(self):
        """記録から diff と印を消して digest を作り直しても、verify は写しから似かたを求め直すので完了と扱わない。"""
        a, b, lines = self.compose_with_source_as_material()
        path, record = self.record_from(lines)
        original = json.loads(path.read_text(encoding="utf-8"))
        record["checks"] = [entry for entry in record["checks"] if entry["name"] != "diff"]
        record["required_checks"] = ["lint", "materials"]
        # 印は treated_as_source と treated_by（決め方。反証レビュー bypass 2 で足した）の2つ。両方を消す
        record["inputs"]["materials"][0]["treated_as_source"] = False
        record["inputs"]["materials"][0]["treated_by"] = None
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "invalid_record")
        result = self.check_json("verify", "--final", b, code=1)
        codes = [problem["code"] for problem in result["problems"]]
        self.assertIn("treated_as_source", codes)
        self.assertIn("missing_check", codes)
        # 印を残したまま diff だけを消した記録は incomplete
        record = original
        record["checks"] = [entry for entry in record["checks"] if entry["name"] != "diff"]
        record["required_checks"] = ["lint", "materials"]
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "incomplete")
        self.assertTrue(verify_lines[0].startswith("記録に diff の結果がありません。"), verify_lines[0])

    def test_far_material_is_a_normal_composition(self):
        materials, final = COMPOSITIONS["minutes_close"]
        m = self.write("memo.txt", materials[0])
        f = self.write("minutes.md", final)
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        self.assertEqual(lines[0], RUN_COMPOSE_FIRST + self.finalize_file())
        self.assertEqual(self.status(lines[1])[1]["checks"], "lint,materials")
        path, record = self.record_from(lines)
        self.assertEqual(record["required_checks"], ["lint", "materials"])
        self.assertIs(record["inputs"]["materials"][0]["treated_as_source"], False)
        self.assertLess(record["inputs"]["materials"][0]["similarity"], THRESHOLD)
        self.assert_verify(self.check("verify", "--final", f), "executed", code=0)

    def test_most_similar_material_is_chosen(self):
        far = self.write("far.md", COMPOSITIONS["interview"][0][0])
        a = self.write("a.md", self.SOURCE)
        b = self.write("b.md", self.FINAL)
        process, lines = self.check_ok("run", "--material", far, "--material", a, "--final", b)
        path, record = self.record_from(lines)
        self.assertEqual([item["treated_as_source"] for item in record["inputs"]["materials"]], [False, True])
        self.assertEqual(self.check_entry(record, "diff")["target"]["source"], sha256_file(a))
        self.assertIn("diff（資料2→最終稿）", lines[2])

    def test_stdin_material_like_the_final(self):
        body = "<<<yomiyasu:material>>>\n" + self.SOURCE + "<<<yomiyasu:final>>>\n" + self.FINAL
        process, lines = self.check_ok("run", "--stdin", stdin=body)
        self.assertTrue(lines[0].endswith(C44_NOTE), lines[0])
        self.assertEqual(self.status(lines[1])[1]["checks"], "lint,diff,materials")
        self.assert_verify(self.check("verify", "--final", "-", "--replay", stdin=self.FINAL), "executed", code=0)

    def test_note_comes_after_the_fail_on_head(self):
        a = self.write("a.md", self.SOURCE)
        b = self.write("b.md", self.FINAL)
        process = self.check("run", "--material", a, "--final", b, "--fail-on", "meaning-risk")
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        line = split_lines(process.stdout)[0]
        self.assertTrue(line.startswith("--fail-on=meaning-risk の条件に当たりました（終了コード1）。検査を実行しました"), line)
        self.assertTrue(line.endswith(C44_NOTE), line)

    def test_rewrite_mode_is_not_changed(self):
        """推敲（--source あり）では、資料が最終稿に似ていても印を付けない（C-44 は新規作成だけ）。"""
        a = self.write("a.md", self.SOURCE)
        m = self.write("m.md", "保存期間は30日です。手動で作ったバックアップは消しません。運用部\n")
        b = self.write("b.md", self.FINAL)
        process, lines = self.check_ok("run", "--source", a, "--material", m, "--final", b)
        self.assertNotIn(C44_NOTE, lines[0])
        path, record = self.record_from(lines)
        self.assertEqual(record["required_checks"], ["lint", "diff", "materials"])
        self.assertIs(record["inputs"]["materials"][0]["treated_as_source"], False)


class TestC45MaterialSameAsFinal(CheckCase):
    """C-45: 資料と最終稿が同じファイルか同じ中身なら、推敲でも新規作成でも2（何も書かない）。"""

    def test_same_file_or_same_text_is_a_usage_error(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        copy = self.write("copy.md", "保存期間は30日です。\r\n\r\n")  # 改行コードと末尾の改行だけが違う同じ本文
        cases = (
            ["--material", b, "--final", b],
            ["--material", copy, "--final", b],
            ["--source", a, "--material", b, "--final", b],
            ["--source", a, "--material", copy, "--final", b],
        )
        for args in cases:
            with self.subTest(args=[Path(str(x)).name for x in args]):
                process = self.check("run", *args)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn(C45_ERROR, process.stderr)
                self.assertFalse(self.state.exists())

    def test_same_text_on_stdin_is_a_usage_error(self):
        body = "<<<yomiyasu:material>>>\n保存期間は30日です。\n<<<yomiyasu:final>>>\n保存期間は30日です。\n"
        process = self.check("run", "--stdin", stdin=body)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn(C45_ERROR, process.stderr)
        self.assertFalse(self.state.exists())


class TestC46CopiedOverAnotherRecord(CheckCase):
    """C-46: 検査ずみの最終稿を、別の原文の記録があるパスへ写したときは ambiguous。"""

    def test_copy_onto_a_path_with_another_source(self):
        a1 = self.write("a1.md", "保存期間は3日です。\n")
        b1 = self.write("b1.md", "保存期間は30日です。\n")
        a2 = self.write("a2.md", "会議は3時に始まります。\n")
        b2 = self.write("b2.md", "会議は、3時に始まります。\n")
        first = self.status(self.check_ok("run", "--source", a1, "--final", b1)[1][1])[1]["run"]
        second = self.status(self.check_ok("run", "--source", a2, "--final", b2)[1][1])[1]["run"]
        b2.write_bytes(b1.read_bytes())  # b1 の検査ずみの最終稿を、a2 の記録がある b2 に写す
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b2), "ambiguous")
        self.assertEqual(verify_lines[0], C46_PLACE_LINE)
        self.assertIn(first, verify_lines[2])
        self.assertIn(second, verify_lines[2])
        _, fields = self.assert_verify(self.check("verify", "--final", b2, "--source", a1), "executed", code=0)
        self.assertEqual(fields["run"], first)
        self.assert_verify(self.check("verify", "--final", b2, "--run-id", first), "executed", code=0)

    def test_copy_to_the_source_place_is_still_executed(self):
        """同じ原文の記録しかないパス（推敲の原文の場所など）へ写したときは今までどおり executed。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        run_id = self.status(self.check_ok("run", "--source", a, "--final", b)[1][1])[1]["run"]
        place = self.write("place.md", "保存期間は30日です。\n")
        _, fields = self.assert_verify(self.check("verify", "--final", place), "executed", code=0)
        self.assertEqual(fields["run"], run_id)


class TestC47EmptyFinal(CheckCase):
    """C-47: 空の最終稿。run は2、verify は no_record。"""

    def test_run_refuses_an_empty_or_blank_final(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        for number, body in enumerate(("", "\n\n", " 　\t\n", "﻿\r\n")):
            with self.subTest(body=body):
                b = self.write("b{}.md".format(number), body)
                process = self.check("run", "--source", a, "--final", b)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn(C47_ERROR, process.stderr)
        process = self.check("run", "--stdin", stdin="<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:final>>>\n\n")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn(C47_ERROR, process.stderr)
        self.assertFalse(self.state.exists())

    def test_verify_does_not_accept_an_empty_body(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b)
        empty = self.write("empty.md", "")
        for args, stdin in ((["--final", "-"], ""), (["--final", "-"], "\n \n"), (["--final", empty], None)):
            with self.subTest(args=[str(x) for x in args], stdin=stdin):
                lines, fields = self.assert_verify(self.check("verify", *args, stdin=stdin), "no_record")
                self.assertTrue(lines[0].startswith("最終稿が空です。"), lines[0])
                result = self.check_json("verify", *args, stdin=stdin, code=1)
                self.assertIn("empty_final", [problem["code"] for problem in result["problems"]])


class TestC41AndRunChain(CheckCase):
    """C-41（partial の回を前回との比べから外す）と、勧め43（回のつなぎ方と修正の回数）。"""

    def test_partial_then_same_final_is_a_first_run(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", b, "--timeout", "0.001")
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        run_id = self.status(split_lines(process.stdout)[1])[1]["run"]
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        status, fields = self.status(lines[1])
        self.assertEqual((fields["run"], fields["attempt"]), (run_id, "2"))
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + self.finalize_file())
        path, record = self.record_from(lines)
        self.assertEqual((record["fix_count"], record["result"]["next"]), (0, "review"))
        # previous は直前の回を指したまま（3.7。比べから外すだけ）
        self.assertEqual(record["previous"]["attempt"], 1)

    def test_revert_counts_as_a_second_fix(self):
        """A → B → A は、前回と違う最終稿だった回が2つなので fix_count は2（勧め43の2）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b)
        b.write_bytes("保存期間は300日です。\n".encode("utf-8"))
        self.check_ok("run", "--source", a, "--final", b)
        b.write_bytes("保存期間は30日です。\n".encode("utf-8"))
        result = self.check_json("run", "--source", a, "--final", b)
        self.assertEqual((result["attempt"], result["fix_count"], result["next"]), (3, 2, "finalize_over_limit"))
        self.assertEqual(result["message"], RUN_OVER_LIMIT.format(n=2) + self.finalize_file())

    def test_line_ending_change_is_not_a_fix(self):
        """改行コードか末尾の改行だけが違う最終稿で run し直しても、修正に数えない（本文のハッシュで比べる。勧め57）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b)
        b.write_bytes("保存期間は30日です。\r\n\r\n".encode("utf-8"))
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        self.assertEqual(lines[0], RUN_SAME_FINAL + self.finalize_file())
        path, record = self.record_from(lines)
        self.assertEqual((record["attempt"], record["fix_count"]), (2, 0))
        self.assert_verify(self.check("verify", "--final", b), "executed", code=0)

    def test_materials_are_part_of_the_chain_in_a_rewrite(self):
        """推敲でも、資料の集まりが違えば前の実行につながない（勧め43の1）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        m = self.write("m.md", "保存期間は30日に変更した。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        first = self.status(self.check_ok("run", "--source", a, "--material", m, "--final", b)[1][1])[1]["run"]
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        status, fields = self.status(lines[1])
        self.assertNotEqual(fields["run"], first)
        self.assertEqual(fields["attempt"], "1")
        # 同じ最終稿に、資料の集まりが違う記録が2つあるので、どちらの検査を使うかは決められない
        self.assert_verify(self.check("verify", "--final", b), "ambiguous")
        self.assert_verify(self.check("verify", "--final", b, "--run-id", first), "executed", code=0)

    def test_ambiguous_by_materials_asks_for_the_run_id(self):
        """原文は同じで資料の集まりだけが違うときは、--source では絞れないので --run-id を案内する。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        m = self.write("m.md", "保存期間は30日に変更した。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        first = self.status(self.check_ok("run", "--source", a, "--material", m, "--final", b)[1][1])[1]["run"]
        second = self.status(self.check_ok("run", "--source", a, "--final", b)[1][1])[1]["run"]
        for extra in ([], ["--source", a]):
            with self.subTest(extra=[str(x) for x in extra]):
                lines, _ = self.assert_verify(self.check("verify", "--final", b, *extra), "ambiguous")
                self.assertEqual(lines[0], AMBIGUOUS_MATERIALS)
                self.assertEqual(lines[2], "記録: 複数あります（実行ID {}、{}）".format(second, first))


class TestPartialLines(CheckCase):
    """勧め42: partial の1行目、verify の incomplete、途中で最終稿が変わったとき。"""

    def test_partial_line_says_not_to_verify(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", b, "--timeout", "0.001")
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        self.assertTrue(lines[0].startswith("検査の一部を実行できませんでした（"), lines[0])
        self.assertTrue(lines[0].endswith("と書いてください。" + PARTIAL_TAIL), lines[0])
        failed = self.status(lines[1])[1]["failed"]
        names = [item.split("(")[0] for item in failed.split(",")]
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "incomplete")
        self.assertEqual(verify_lines[0], VERIFY_PARTIAL_LINE.format(
            "、".join(names) + " は時間切れ", "、".join(name + "（時間切れ）" for name in names)))

    def test_final_changed_during_the_run_asks_to_run_again(self):
        worker = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('_check_under_test', sys.argv[1])\n"
            "check = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(check)\n"
            "original = check._run_checks\n"
            "def wrapped(*args, **kwargs):\n"
            "    result = original(*args, **kwargs)\n"
            "    with open(sys.argv[2], 'ab') as handle:\n"
            "        handle.write('追記した文です。\\n'.encode('utf-8'))\n"
            "    return result\n"
            "check._run_checks = wrapped\n"
            "sys.exit(check.main(sys.argv[3:]))\n"
        )
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process = subprocess.run([sys.executable, "-B", "-c", worker, str(CHECK), str(b),
                                  "run", "--source", str(a), "--final", str(b)],
                                 cwd=str(self.root), env=self.env(), capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        lines = split_lines(process.stdout)
        status, fields = self.status(lines[1])
        self.assertEqual((status, fields["failed"]), ("partial", "final(changed)"))
        self.assertNotIn("meaning_risk", fields)
        self.assertEqual(lines[0], FINAL_CHANGED_DURING_RUN)
        self.assertEqual(lines[2], SUMMARY_NONE_CHANGED)
        path, record = self.record_from(lines)
        self.assertEqual((record["result"]["status"], record["result"]["next"]), ("partial", "rerun"))


class TestVerifyNotes(CheckCase):
    """勧め48（直しが失われた、原文を --final に渡した、原文が前の最終稿と同じ）と勧め49（件数の食い違い）。"""

    def test_newer_attempt_with_another_text_is_noted(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        first = b.read_bytes()
        self.check_ok("run", "--source", a, "--final", b)
        b.write_bytes("データの保存期間は30日です。\n".encode("utf-8"))
        self.check_ok("run", "--source", a, "--final", b)
        b.write_bytes(first)  # 直しが失われ、1回目の本文に戻った
        verify_lines, fields = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertEqual(fields["attempt"], "1")
        self.assertTrue(verify_lines[0].endswith(NEWER_ATTEMPT_NOTE), verify_lines[0])
        result = self.check_json("verify", "--final", b)
        self.assertIn("newer_attempt_differs", [problem["code"] for problem in result["problems"]])

    def test_latest_attempt_has_no_note(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b)
        self.check_ok("run", "--source", a, "--final", b)  # 同じ本文でもう一度
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "executed", code=0)
        self.assertNotIn(NEWER_ATTEMPT_NOTE, verify_lines[0])

    def test_source_given_to_final_is_noted(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", a), "no_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["no_record"] + RECORDED_SOURCE_NOTE)
        result = self.check_json("verify", "--final", a, code=1)
        self.assertIn("is_recorded_source", [problem["code"] for problem in result["problems"]])

    def test_source_that_was_a_final_is_noted_in_run(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        c = self.write("c.md", "データの保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b)
        process, lines = self.check_ok("run", "--source", b, "--final", c)
        self.assertTrue(lines[0].startswith(SOURCE_WAS_FINAL_NOTE + "検査を実行しました（1回目）。"), lines[0])
        self.assertEqual(self.status(lines[1])[0], "executed")

    def test_counts_that_do_not_match_the_reports_are_invalid(self):
        """記録の件数（result と summary）を、ハッシュを確かめたレポートの件数と照らす（--replay なしでも）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        path, record = self.record_from(lines)
        record["result"]["meaning_risk_count"] = 0
        record["result"]["fail_on_meaning_risk_count"] = 0
        self.check_entry(record, "diff")["summary"]["meaning_risk_count"] = 0
        self.check_entry(record, "diff")["summary"]["fail_on_meaning_risk_count"] = 0
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "invalid_record")
        result = self.check_json("verify", "--final", b, code=1)
        self.assertIn("summary_mismatch", [problem["code"] for problem in result["problems"]])
        self.assertIsNone(result["meaning_risk_count"])


class TestRecordChecks(CheckCase):
    """勧め49 の照合の件数、C-44 の印の形、勧め42の2 の理由が混ざった partial の記録。"""

    def test_materials_counts_that_do_not_match_are_invalid(self):
        materials, final = COMPOSITIONS["minutes"]
        m = self.write("memo.txt", materials[0])
        f = self.write("minutes.md", final)
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        path, record = self.record_from(lines)
        entry = self.check_entry(record, "materials")
        self.assertGreater(entry["summary"]["not_in_sources"], 0)
        entry["summary"]["not_in_sources"] = 0
        record["materials_summary"]["not_in_sources"] = 0
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", f), "invalid_record")
        result = self.check_json("verify", "--final", f, code=1)
        problems = dict((problem["code"], problem["detail"]) for problem in result["problems"])
        self.assertIn("materials.not_in_sources", problems["summary_mismatch"])

    def test_marks_must_have_the_designed_shape(self):
        """印（treated_as_source）は新規作成の資料1つだけ。推敲の資料に付いた記録や、2つに付いた記録は形の誤り。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        m = self.write("m.md", "保存期間は30日に変更した。運用部\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--material", m, "--final", b)
        path, record = self.record_from(lines)
        record["inputs"]["materials"][0]["treated_as_source"] = True
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", b), "invalid_record")
        result = self.check_json("verify", "--final", b, code=1)
        self.assertEqual([problem["code"] for problem in result["problems"]], ["record_shape"])
        materials, final = COMPOSITIONS["release"]
        m1 = self.write("notes.md", materials[0])
        m2 = self.write("faq.md", materials[1])
        f = self.write("release.md", final)
        process, lines = self.check_ok("run", "--material", m1, "--material", m2, "--final", f)
        path, record = self.record_from(lines)
        for item in record["inputs"]["materials"]:
            item["treated_as_source"] = True
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", f), "invalid_record")

    def test_partial_record_with_two_reasons(self):
        """記録の検査が、内部エラーと時間切れで終わっていたときの1行目（理由ごとにまとめる）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        path, record = self.record_from(lines)
        for name, status in (("lint", "error"), ("diff", "timeout")):
            entry = self.check_entry(record, name)
            entry.update({"status": status, "exit_code": None, "report": None, "report_sha256": None, "text": None,
                          "text_sha256": None, "summary": None, "error": "試験で作った止まり方"})
        record["result"]["status"] = "partial"
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "incomplete")
        self.assertEqual(verify_lines[0], VERIFY_PARTIAL_LINE.format("lint は内部エラー、diff は時間切れ",
                                                                     "lint（内部エラー）、diff（時間切れ）"))


class TestPathsAndRunIds(CheckCase):
    """勧め50（macOS で綴りの違う同じファイル）と勧め51・20（実行IDの名前）。"""

    def case_insensitive(self):
        probe = self.write("Probe.md", "x\n")
        return (self.root / "probe.md").exists() and os.path.samefile(str(probe), str(self.root / "PROBE.md"))

    @unittest.skipUnless(sys.platform == "darwin", "macOS の F_GETPATH の試験")
    def test_other_spelling_of_the_same_file_links_to_the_run(self):
        if not self.case_insensitive():
            self.skipTest("大文字と小文字を区別するファイルシステム")
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("Draft.md", "保存期間は30日です。\n")
        run_id = self.status(self.check_ok("run", "--source", a, "--final", self.root / "Draft.md")[1][1])[1]["run"]
        b.write_bytes("データの保存期間は30日です。\n".encode("utf-8"))
        process, lines = self.check_ok("run", "--source", a, "--final", self.root / "draft.md")
        status, fields = self.status(lines[1])
        self.assertEqual((fields["run"], fields["attempt"]), (run_id, "2"))
        self.assertEqual(lines[0], RUN_AFTER_FIX + self.finalize_file())
        # NFC と NFD の綴り（「データ」の濁点。濁点のない語では NFC と NFD が同じになり、試験にならない）
        nfc = unicodedata.normalize("NFC", "データ.md")
        nfd = unicodedata.normalize("NFD", "データ.md")
        self.assertNotEqual(nfc, nfd)
        target = self.write(nfc, "保存期間は30日です。\n")
        run_id = self.status(self.check_ok("run", "--source", a, "--final", target)[1][1])[1]["run"]
        target.write_bytes("記録の保存期間は30日です。\n".encode("utf-8"))
        process, lines = self.check_ok("run", "--source", a, "--final", self.root / nfd)
        self.assertEqual(self.status(lines[1])[1]["run"], run_id)

    def test_run_ids_that_windows_cannot_use_are_rejected(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        for run_id in ("abc.", "CON", "nul", "Com1", "lpt9.log", "aux.txt", "PRN"):
            with self.subTest(run_id=run_id):
                for command in (["run", "--source", a, "--final", b], ["verify", "--final", b]):
                    process = self.check(*(command + ["--run-id", run_id]))
                    self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                    self.assertIn("--run-id に使えない値です: {}。".format(run_id), process.stderr)
                    self.assertIn(RUN_ID_ERROR_TAIL, process.stderr)
                self.assertFalse(self.state.exists())
        for run_id in ("console", "com10", "a.b", "nul-1"):
            with self.subTest(run_id=run_id):
                self.check_ok("run", "--source", a, "--final", b, "--run-id", run_id)

    def test_run_id_that_differs_only_in_case_is_rejected(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b, "--run-id", "CI-Run")
        before = tree_digest(self.state)
        for command in (["run", "--source", a, "--final", b], ["verify", "--final", b]):
            with self.subTest(command=command[0]):
                process = self.check(*(command + ["--run-id", "ci-run"]))
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertIn("--run-id ci-run は、すでにある実行ID CI-Run と大文字と小文字だけが違います。", process.stderr)
        self.assertEqual(tree_digest(self.state), before)


class TestOutputWording(CheckCase):
    """勧め54〜59 の出力の文。"""

    def test_status_line_is_last_in_the_merged_output_of_a_partial_run(self):
        """勧め54: 終了コード3のとき、標準エラーを先に書くので、2>&1 でまとめた出力の最後は状態の行になる。
        パイプでも端末でも同じ順にする（端末では標準出力が行ごとに書き出されるので、pty で確かめる）。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        command = [sys.executable, "-B", str(CHECK), "run", "--source", str(a), "--final", str(b), "--timeout", "0.001"]
        process = subprocess.run(command, cwd=str(self.root), env=self.env(), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 3, process.stdout)
        merged = split_lines(process.stdout)
        self.assertTrue(merged[-1].startswith("yomiyasu-check: partial via=run "), merged[-3:])
        if os.name != "posix":
            return
        import pty
        master, slave = pty.openpty()
        try:
            child = subprocess.Popen(command + ["--new-run"], cwd=str(self.root), env=self.env(),
                                     stdin=subprocess.DEVNULL, stdout=slave, stderr=slave)
        finally:
            os.close(slave)
        chunks = []
        try:
            while True:
                try:
                    data = os.read(master, 65536)
                except OSError:  # 子が端末を閉じたあと（Linux は EIO）
                    break
                if not data:
                    break
                chunks.append(data)
        finally:
            os.close(master)
        self.assertEqual(child.wait(timeout=30), 3)
        merged = split_lines(b"".join(chunks).decode("utf-8").replace("\r\n", "\n"))
        self.assertTrue(merged[-1].startswith("yomiyasu-check: partial via=run "), merged[-3:])

    def test_state_dir_option_is_in_the_finalize_text(self):
        """勧め55: --state-dir で記録したら、verify にも同じ --state-dir を付けるよう案内する。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        other = self.root / "other state"
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--state-dir", other)
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_STATE_DIR.format('"{}"'.format(other)))
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", a, "--state-dir", other), "no_record")
        self.assertEqual(verify_lines[2], NO_RECORD_LINE3.format(other))

    def test_no_record_line_3_names_the_searched_folder(self):
        b = self.write("b.md", "保存期間は30日です。\n")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "no_record")
        self.assertEqual(verify_lines[2], NO_RECORD_LINE3.format(self.state))

    def test_report_copy_wording_allows_body_only_replies(self):
        """勧め56: 本文だけを返す指定では確認の記録を付けないので、verify は「完了報告を付けるときは」。
        run --stdin は、返す直前に最終稿だけを verify --final - に渡すよう案内する。"""
        body = "<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:final>>>\n保存期間は30日です。\n"
        process, lines = self.check_ok("run", "--stdin", stdin=body)
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + self.finalize_stdin())
        self.assertNotIn("この出力の2行目を写して", lines[0])
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", "-", stdin="保存期間は30日です。\n"),
                                             "executed", code=0)
        self.assertTrue(verify_lines[0].endswith(VERIFY_EXECUTED_TAIL), verify_lines[0])

    def test_same_text_as_the_source_is_no_change(self):
        """勧め57: 原文と本文が同じで、改行コード、BOM、末尾の改行だけが違うときは「変更はありません」。"""
        a = self.write("a.md", "保存期間は30日です。\n")
        b = self.write("b.md", "﻿保存期間は30日です。\r\n\r\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        self.assertEqual(lines[0], RUN_NO_CHANGE_TEXT_SAME + self.finalize_file())
        self.assertTrue(lines[2].startswith("実行した検査: lint（最終稿）候補0件、diff（原文→最終稿）変更なし"), lines[2])
        same = self.write("same.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", same)
        self.assertEqual(lines[0], RUN_NO_CHANGE_NEW + self.finalize_file())

    def test_verify_notes_a_trailing_newline_difference(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        self.check_ok("run", "--source", a, "--final", b)
        b.write_bytes("保存期間は30日です。".encode("utf-8"))  # 末尾の改行だけを落とす
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "final_changed")
        self.assertTrue(verify_lines[0].endswith(VERIFY_TEXT_SAME_NOTE), verify_lines[0])
        result = self.check_json("verify", "--final", b, code=1)
        self.assertIn("only_line_endings_differ", [problem["code"] for problem in result["problems"]])

    def test_same_file_error_explains_what_to_report(self):
        """勧め58: 原文を上書きして元の版を取り出せないときの書き方。"""
        a = self.write("a.md", "保存期間は30日です。\n")
        process = self.check("run", "--source", a, "--final", a)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn(SAME_FILE_TAIL, process.stderr)

    def test_no_record_option_wording(self):
        """勧め59: 記録を書かないときの4行目は「この結果は」、reason は no_record_option、{仕上げ} の並べ替え。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        process, lines = self.check_ok("run", "--source", a, "--final", b, "--no-record")
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_NO_RECORD_NEW)
        # 断りの行は記録の行のすぐ上（候補がなければ4行目。候補があると、候補の一覧と案内の2行のぶん下がる）
        self.assertEqual(lines[self.record_index(lines) - 1], UNRECORDED_DISCLAIMER)
        self.assertEqual(self.status(lines[1])[1]["reason"], "no_record_option")


# ---- check の固めの反証レビューの直し ----
# 直す前の作業ツリー（check の SHA-256 の先頭 829dbe1372d4b1bc）で落ちることを確かめてから直した。

# spec 4: C-46（このパスの最新の記録と原文が違う）の ambiguous の1行目。3.9 の文は「同じ最終稿に…複数」で、事実と合わない
C46_PLACE_LINE = ("この最終稿の記録と、このパスで最後に検査した記録とで、原文が違います。どちらの記録を使うかを決められないので、"
                  "--run-id か --source を付けて verify を実行してください。")
# bypass 2: 同じ実行の前の回で原文とみなした資料を、後の回も原文とみなしたときの注記
C44_INHERITED_NOTE = ("前の回で原文とみなした資料を、この回も原文とみなして diff も実行しました。"
                      "書き直す前の文章なら --source に渡してください。")
# compat 5: diff が最後まで動かなかった partial では「diff も実行しました」と書かない（partial の文の前に置く）
C44_PENDING_NOTE = ("資料の1つが最終稿とよく似ているので、原文とみなして diff も必要な検査に入れました。"
                    "書き直す前の文章なら --source に渡してください。")

# bypass 2: 1回目は資料とよく似ていて（約0.94）、2回目に段落を足すと似かたがしきい値を下回る（約0.44）最終稿。
# どちらも「手動で作ったバックアップは消しません」を「消します」に変えた（diff だけが見つける否定の変化）
INHERIT_MATERIAL = ("# バックアップの決まり\n\n"
                    "データは毎日の夜に自動でバックアップします。古いバックアップは30日後に消します。"
                    "手動で作ったバックアップは消しません。復元は管理者だけが行えます。\n")
INHERIT_FIRST = INHERIT_MATERIAL.replace("手動で作ったバックアップは消しません。", "手動で作ったバックアップも消します。")
INHERIT_SECOND = INHERIT_FIRST + (
    "\n## 問い合わせ\n\n"
    "復元を頼みたいときは、情報システム部の窓口に、日付とファイルの場所を書いて送ってください。"
    "急ぎのときは電話でも受け付けます。受け付けたら、その日のうちに担当者から返事をします。\n")


def copy_scripts(root, name):
    """4本と SKILL.md を root/name/scripts に写す（test_v200_check.py の TestReviewFixes.copy_scripts と同じ）。"""
    scripts = root / name / "scripts"
    scripts.mkdir(parents=True)
    for tool in TOOL_NAMES:
        shutil.copyfile(str(SCRIPTS / tool), str(scripts / tool))
    shutil.copyfile(str(SKILL_MD), str(scripts.parent / "SKILL.md"))
    return scripts


class TestReviewC46(CheckCase):
    """spec 1 と 4: C-46 は原文（推敲の原文と、新規作成で原文とみなした資料。新規作成では資料の集まり）だけを比べ、
    同じ文書を続けて直して原文の場所に写す流れ（3.9、5.1 の手順6）を ambiguous にしない。"""

    def test_continued_edit_copied_back_to_the_place_is_executed(self):
        orig = self.write("orig.md", "保存期間は3日である。\n")
        doc = self.write("doc.md", "保存期間は3日です。\n")
        self.check_ok("run", "--source", orig, "--final", doc)
        doc2 = self.write("doc2.md", "データの保存期間は3日です。\n")
        second = self.status(self.check_ok("run", "--source", doc, "--final", doc2)[1][1])[1]["run"]
        doc.write_bytes(doc2.read_bytes())  # 続けて直す依頼の最終稿を、原文の場所に写す
        _, fields = self.assert_verify(self.check("verify", "--final", doc), "executed", code=0)
        self.assertEqual(fields["run"], second)
        # もう1回続けて直して写しても同じ（原文をたどって、このパスの記録の最終稿に行き着く）
        doc3 = self.write("doc3.md", "データの保存期間は、3日です。\n")
        third = self.status(self.check_ok("run", "--source", doc, "--final", doc3)[1][1])[1]["run"]
        doc.write_bytes(doc3.read_bytes())
        _, fields = self.assert_verify(self.check("verify", "--final", doc), "executed", code=0)
        self.assertEqual(fields["run"], third)

    def test_composed_document_edited_and_copied_back_is_executed(self):
        memo = self.write("memo.md", COMPOSITIONS["interview"][0][0])
        doc = self.write("doc.md", COMPOSITIONS["interview"][1])
        self.check_ok("run", "--material", memo, "--final", doc)
        doc2 = self.write("doc2.md", COMPOSITIONS["interview"][1].replace("現場のリーダーに、", "物流センターの現場のリーダーに、"))
        second = self.status(self.check_ok("run", "--source", doc, "--final", doc2)[1][1])[1]["run"]
        doc.write_bytes(doc2.read_bytes())
        _, fields = self.assert_verify(self.check("verify", "--final", doc), "executed", code=0)
        self.assertEqual(fields["run"], second)

    def test_same_source_with_other_materials_is_not_ambiguous(self):
        """10.8 C-46 は「原文が同じなら今のまま」。資料の集まりだけが違う記録のあるパスへ写しても executed。"""
        a = self.write("a.md", "保存期間は3日です。\n")
        m = self.write("m.md", "保存期間は30日に変更した。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        c = self.write("c.md", "保存期間は30日とします。\n")
        first = self.status(self.check_ok("run", "--source", a, "--material", m, "--final", b)[1][1])[1]["run"]
        self.check_ok("run", "--source", a, "--final", c)
        c.write_bytes(b.read_bytes())
        _, fields = self.assert_verify(self.check("verify", "--final", c), "executed", code=0)
        self.assertEqual(fields["run"], first)

    def test_place_ambiguity_has_its_own_first_line(self):
        a1 = self.write("a1.md", "保存期間は3日です。\n")
        b1 = self.write("b1.md", "保存期間は30日です。\n")
        a2 = self.write("a2.md", "会議は3時に始まります。\n")
        b2 = self.write("b2.md", "会議は、3時に始まります。\n")
        first = self.status(self.check_ok("run", "--source", a1, "--final", b1)[1][1])[1]["run"]
        second = self.status(self.check_ok("run", "--source", a2, "--final", b2)[1][1])[1]["run"]
        b2.write_bytes(b1.read_bytes())
        lines, _ = self.assert_verify(self.check("verify", "--final", b2), "ambiguous")
        self.assertEqual(lines[0], C46_PLACE_LINE)
        self.assertEqual(lines[2], "記録: 複数あります（実行ID {}、{}）".format(second, first))
        result = self.check_json("verify", "--final", b2, code=1)
        self.assertEqual([problem["code"] for problem in result["problems"]], ["ambiguous"])


class TestReviewC44Counts(CheckCase):
    """spec 2: 原文とみなした資料の照合は推敲と同じ扱いにする（3.3 の「二重に出さない」）。同じ数値の変化を diff と照合で
    2回数えない。"""

    def test_treated_material_counts_a_change_once(self):
        a = self.write("a.md", TestC44Run.SOURCE)
        b = self.write("b.md", TestC44Run.FINAL)
        process, lines = self.check_ok("run", "--material", a, "--final", b)
        self.assertEqual(self.status(lines[1])[1]["meaning_risk"], "1")
        self.assertIn("■ 意味が変わる恐れ（1件。原文と資料に照らして確かめる）", lines)
        self.assertIn("- 数値が変わった（1行目）: 3日 → 30日", lines)
        self.assertNotIn("- 資料にない数値（後1行目）: 30日", lines)
        self.assertFalse([line for line in lines if line.startswith("- 参考: 資料にあって最終稿にない数値")], lines)
        path, record = self.record_from(lines)
        self.assertEqual((record["result"]["meaning_risk_count"], record["result"]["fail_on_meaning_risk_count"]), (1, 1))
        entry = self.check_entry(record, "materials")
        self.assertEqual(entry["target"], {"source": sha256_file(a), "materials": [sha256_file(a)],
                                           "final": sha256_file(b)})
        materials = json.loads((self.state / entry["report"]).read_text(encoding="utf-8"))
        self.assertEqual(materials["meaning_risks"], [])
        # 同じ入力を推敲として渡したときと同じ件数
        rewrite = self.check_ok("run", "--source", a, "--material", a, "--final", b, "--new-run")[1]
        self.assertEqual(self.status(rewrite[1])[1]["meaning_risk"], "1")
        self.assert_verify(self.check("verify", "--final", b, "--run-id", self.status(lines[1])[1]["run"]),
                           "executed", code=0)
        _, fields = self.assert_verify(self.check("verify", "--final", b, "--run-id", self.status(lines[1])[1]["run"],
                                                  "--replay"), "executed", code=0)
        self.assertEqual(fields["replay"], "ok")


class TestReviewFinalizeStateDir(CheckCase):
    """spec 3: 勧め55は「--state-dir か YOMIYASU_STATE_DIR で状態フォルダを決めたとき」。環境変数で決めたときも、verify に
    同じ --state-dir を付けるよう案内する（呼び出しごとに環境変数が引き継がれないシェルのため）。"""

    def test_state_dir_from_the_environment_is_in_the_finalize_text(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        other = self.root / "env state"
        process, lines = self.check_ok("run", "--source", a, "--final", b, env=self.env(YOMIYASU_STATE_DIR=str(other)))
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_STATE_DIR.format('"{}"'.format(other)))
        plain = self.env()
        plain.pop("YOMIYASU_STATE_DIR")
        self.assert_verify(self.check("verify", "--final", b, "--state-dir", other, env=plain), "executed", code=0)

    def test_default_state_folder_keeps_the_short_text(self):
        """--state-dir も環境変数もないとき（git の最上位の .yomiyasu/）は今までどおり。"""
        top = self.root / "top"
        top.mkdir()
        (top / ".git").mkdir()
        a = self.write("top/a.md", "保存期間は3日です。\n")
        b = self.write("top/b.md", "保存期間は30日です。\n")
        plain = self.env()
        plain.pop("YOMIYASU_STATE_DIR")
        process, lines = self.check_ok("run", "--source", a, "--final", b, env=plain, cwd=top)
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_FILE)

    def test_stdin_finalize_names_verify_with_the_same_state_folder(self):
        """--stdin でも、返す直前に最終稿だけを verify --final - に渡すよう案内し、その案内どおりの verify が記録と合う。
        状態フォルダを決めたときは同じ --state-dir を、決めないとき（git の最上位の .yomiyasu/）は付けない。"""
        body = "<<<yomiyasu:original>>>\n保存期間は3日です。\n<<<yomiyasu:final>>>\n保存期間は30日です。\n"
        final = "保存期間は30日です。\n"
        other = self.root / "env state"
        process, lines = self.check_ok("run", "--stdin", stdin=body, env=self.env(YOMIYASU_STATE_DIR=str(other)))
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_STDIN.replace(
            "verify --final -", 'verify --state-dir "{}" --final -'.format(other)))
        plain = self.env()
        plain.pop("YOMIYASU_STATE_DIR")
        self.assert_verify(self.check("verify", "--state-dir", other, "--final", "-", stdin=final, env=plain),
                           "executed", code=0)
        top = self.root / "top"
        top.mkdir()
        (top / ".git").mkdir()
        process, lines = self.check_ok("run", "--stdin", stdin=body, env=plain, cwd=top)
        self.assertEqual(lines[0], RUN_REWRITE_FIRST + FINALIZE_STDIN)
        self.assert_verify(self.check("verify", "--final", "-", stdin=final, env=plain, cwd=top), "executed", code=0)
        # 区切りの行ごと渡すと、記録と合わない（最終稿だけを渡す理由）
        self.assert_verify(self.check("verify", "--final", "-", stdin=body, env=plain, cwd=top), "no_record")


class TestReviewRecordedSource(CheckCase):
    """spec 5: 記録を書けなかった run が置いた写しで、最終稿を「原文か資料」と案内しない（勧め48の2）。"""

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "chmod で書けなくできない環境（root と Windows）")
    def test_final_of_an_unrecorded_run_is_not_called_a_source(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        c = self.write("c.md", "保存期間は31日です。\n")
        self.check_ok("run", "--source", a, "--final", c)
        runs = self.state / "runs"
        os.chmod(str(runs), 0o500)
        self.addCleanup(os.chmod, str(runs), 0o700)
        process, lines = self.check_ok("run", "--source", a, "--final", b)
        self.assertEqual(self.status(lines[1])[1]["reason"], "not_writable")
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", b), "no_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["no_record"])
        result = self.check_json("verify", "--final", b, code=1)
        self.assertNotIn("is_recorded_source", [problem["code"] for problem in result["problems"]])
        # 記録に残った原文は今までどおり案内する
        verify_lines, _ = self.assert_verify(self.check("verify", "--final", a), "no_record")
        self.assertEqual(verify_lines[0], VERIFY_LINE1["no_record"] + RECORDED_SOURCE_NOTE)


class TestReviewChildContext(CheckCase):
    """spec 7（G7-8）: 子の JSON の context が、渡した種類と読者と違うか、lint の外した件数が0以上の整数で
    ないときは、その検査を error にして partial（終了コード3）にする。"""

    CASES = (
        ("lint", (), ("result = _yomiyasu_test_real(*args, **kwargs)", "result['context']['doc_type'] = 'essay'")),
        ("diff", (), ("result = _yomiyasu_test_real(*args, **kwargs)", "result['context']['reader'] = 'general'")),
        ("lint", ("--doc-type", "pr"),
         ("result = _yomiyasu_test_real(*args, **kwargs)", "result['context']['skipped_by_doc_type'] = {'excess_list': '3'}")),
        ("lint", ("--doc-type", "pr"),
         ("result = _yomiyasu_test_real(*args, **kwargs)", "result['context']['skipped_by_doc_type'] = {'excess_list': -1}")),
    )

    def test_child_context_that_does_not_match_is_an_error(self):
        a = self.write("a.md", "保存期間は3日です。\n")
        b = self.write("b.md", "保存期間は30日です。\n")
        for number, (name, extra, body) in enumerate(self.CASES):
            with self.subTest(case=number):
                scripts = copy_scripts(self.root, "skill-context-{}".format(number))
                function = "lint_text" if name == "lint" else "diff"
                inject_cli_code(scripts / "yomiyasu_{}.py".format(name), (
                    "_yomiyasu_test_real = {}".format(function),
                    "def {}(*args, **kwargs):".format(function)) + tuple("    " + line for line in body) + (
                    "    return result",))
                process = self.check("run", "--source", a, "--final", b, "--new-run", *extra,
                                     script=scripts / "yomiyasu_check.py")
                self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
                self.assertNotIn("Traceback", process.stderr)
                lines = split_lines(process.stdout)
                status, fields = self.status(lines[1])
                self.assertEqual((status, fields.get("failed")), ("partial", name + "(error)"))
                path, record = self.record_from(lines)
                entry = self.check_entry(record, name)
                self.assertEqual(entry["status"], "error")
                self.assertIn("context", entry["error"])


class TestReviewInheritedSource(CheckCase):
    """bypass 2: 同じ実行で、前の回が原文とみなした資料は、後の回で似かたがしきい値を下回っても原文とみなす（直しを重ねて
    diff が外れないように）。記録には前の回から引き継いだことを残し、verify は同じ実行の前の回の記録で確かめる。"""

    def test_later_attempt_keeps_the_material_as_the_source(self):
        check = load_check()
        self.assertGreaterEqual(check._similarity(INHERIT_MATERIAL, INHERIT_FIRST), THRESHOLD)
        self.assertLess(check._similarity(INHERIT_MATERIAL, INHERIT_SECOND), THRESHOLD)
        m = self.write("memo.md", INHERIT_MATERIAL)
        f = self.write("final.md", INHERIT_FIRST)
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        run_id = self.status(lines[1])[1]["run"]
        path, record = self.record_from(lines)
        self.assertEqual(record["inputs"]["materials"][0]["treated_by"], "similarity")
        f.write_bytes(INHERIT_SECOND.encode("utf-8"))
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        status, fields = self.status(lines[1])
        self.assertEqual((fields["run"], fields["attempt"], fields["checks"]), (run_id, "2", "lint,diff,materials"))
        self.assertGreaterEqual(int(fields["meaning_risk"]), 1)
        self.assertEqual(lines[0], RUN_AFTER_FIX + self.finalize_file() + C44_INHERITED_NOTE)
        self.assertIn("diff（資料1→最終稿）", lines[2])
        path, record = self.record_from(lines)
        material = record["inputs"]["materials"][0]
        self.assertEqual((material["treated_as_source"], material["treated_by"]), (True, "previous_attempt"))
        self.assertLess(material["similarity"], THRESHOLD)
        _, fields = self.assert_verify(self.check("verify", "--final", f), "executed", code=0)
        self.assertEqual(fields["checks"], "lint,diff,materials")
        _, fields = self.assert_verify(self.check("verify", "--final", f, "--replay"), "executed", code=0)
        self.assertEqual(fields["replay"], "ok")
        # 印と diff を消して digest を作り直した記録は、前の回の記録と食い違うので完了と扱わない
        record["checks"] = [entry for entry in record["checks"] if entry["name"] != "diff"]
        record["required_checks"] = ["lint", "materials"]
        material.update({"treated_as_source": False, "treated_by": None})
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        self.assert_verify(self.check("verify", "--final", f), "invalid_record")
        result = self.check_json("verify", "--final", f, code=1)
        self.assertIn("treated_as_source", [problem["code"] for problem in result["problems"]])

    def test_treated_by_must_match_how_the_mark_was_made(self):
        """決め方（treated_by）は、印と同じく写しから求め直して照らす。印のない資料に決め方があれば形の誤り。"""
        m = self.write("memo.md", INHERIT_MATERIAL)
        f = self.write("final.md", INHERIT_FIRST)
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        path, record = self.record_from(lines)
        original = json.loads(path.read_text(encoding="utf-8"))
        record["inputs"]["materials"][0]["treated_by"] = "previous_attempt"
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        result = self.check_json("verify", "--final", f, code=1)
        self.assertEqual(result["status"], "invalid_record")
        self.assertIn("treated_as_source", [problem["code"] for problem in result["problems"]])
        record = original
        record["inputs"]["materials"][0].update({"treated_as_source": False, "treated_by": "similarity"})
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        result = self.check_json("verify", "--final", f, code=1)
        self.assertEqual([problem["code"] for problem in result["problems"]], ["record_shape"])
        self.assertIn("treated_by", result["problems"][0]["detail"])

    def test_new_run_does_not_inherit(self):
        m = self.write("memo.md", INHERIT_MATERIAL)
        f = self.write("final.md", INHERIT_FIRST)
        self.check_ok("run", "--material", m, "--final", f)
        f.write_bytes(INHERIT_SECOND.encode("utf-8"))
        process, lines = self.check_ok("run", "--material", m, "--final", f, "--new-run")
        self.assertEqual(self.status(lines[1])[1]["checks"], "lint,materials")
        self.assertNotIn(C44_INHERITED_NOTE, lines[0])


class TestReviewSimilarityInputs(CheckCase):
    """bypass 4（C-45 を空白と NFKC をそろえて比べる）と 7（書式の文字を除いて似かたを測る）。"""

    def test_material_that_differs_only_in_spacing_is_a_usage_error(self):
        b = self.write("b.md", "保存期間は30日です。手動で作ったバックアップは消しません。\n")
        cases = {
            "space.md": "保存期間は30日です。 \n手動で作ったバックアップは消しません。\n",
            "wide.md": "保存期間は３０日です。手動で作った　バックアップは消しません。",
            "zero_width.md": "保存期間は30日です。​手動で作ったバックアップは消しません。\n",
        }
        for name, text in cases.items():
            with self.subTest(material=name):
                m = self.write(name, text)
                process = self.check("run", "--material", m, "--final", b)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn(C45_ERROR, process.stderr)
        self.assertFalse(self.state.exists())

    def test_format_characters_do_not_hide_the_source(self):
        check = load_check()
        source = TestC44Run.SOURCE * 3
        final = TestC44Run.FINAL * 3
        plain = check._similarity(source, final)
        for mark in ("​", "­", "⁠", "﻿"):
            with self.subTest(mark=hex(ord(mark))):
                self.assertAlmostEqual(check._similarity(mark.join(source), final), plain)
        m = self.write("a.md", "​".join(TestC44Run.SOURCE))
        f = self.write("b.md", TestC44Run.FINAL)
        process, lines = self.check_ok("run", "--material", m, "--final", f)
        self.assertEqual(self.status(lines[1])[1]["checks"], "lint,diff,materials")


class TestReviewDiskSpelling(CheckCase):
    """compat 3: macOS で最終稿を消して別の綴り（NFC と NFD、大文字と小文字）で作り直しても、前の回につながる。"""

    def case_insensitive(self):
        probe = self.write("Probe.md", "x\n")
        return (self.root / "probe.md").exists() and os.path.samefile(str(probe), str(self.root / "PROBE.md"))

    def recreate_flow(self, created, typed):
        src = self.write("src.md", "設定の値を記録の表と照らします。担当者は結果を残し、会議で共有します。\n")
        (self.root / created).write_bytes("設定の値を記録の表と照らし合わせます。担当者は結果を残します。\n".encode("utf-8"))
        run_id = self.status(self.check_ok("run", "--source", src, "--final", self.root / typed)[1][1])[1]["run"]
        os.remove(str(self.root / typed))
        (self.root / typed).write_bytes("設定の値を記録の表と照らし合わせます。担当者は結果を翌週に残します。\n".encode("utf-8"))
        self.assert_verify(self.check("verify", "--final", self.root / typed), "final_changed")
        process, lines = self.check_ok("run", "--source", src, "--final", self.root / typed)
        status, fields = self.status(lines[1])
        self.assertEqual((fields["run"], fields["attempt"]), (run_id, "2"))

    @unittest.skipUnless(sys.platform == "darwin", "macOS の F_GETPATH の試験")
    def test_recreated_file_in_the_other_normalization_links(self):
        nfc = unicodedata.normalize("NFC", "データの手順.md")
        self.recreate_flow(unicodedata.normalize("NFD", nfc), nfc)

    @unittest.skipUnless(sys.platform == "darwin", "macOS の F_GETPATH の試験")
    def test_recreated_file_in_the_other_case_links(self):
        if not self.case_insensitive():
            self.skipTest("大文字と小文字を区別するファイルシステム")
        self.recreate_flow("Final.md", "final.md")


class TestReviewRecheckGuard(CheckCase):
    """compat 4: verify は、記録を作ったときと Unicode の版か check が違えば、原文とみなす資料を求め直さない
    （書き換えていない記録を invalid_record にしない。check が変わったときは tool_changed）。"""

    def treated_run(self, script=None):
        a = self.write("a.md", TestC44Run.SOURCE)
        b = self.write("b.md", TestC44Run.FINAL)
        args = ["run", "--material", a, "--final", b]
        process, lines = self.check_ok(*args, script=script) if script else self.check_ok(*args)
        return b, lines

    def test_record_keeps_the_unicode_version(self):
        b, lines = self.treated_run()
        path, record = self.record_from(lines)
        self.assertEqual(record["python"]["unicode_version"], unicodedata.unidata_version)
        result = self.check_json("verify", "--final", b)
        self.assertNotIn("treated_not_rechecked", [problem["code"] for problem in result["problems"]])

    def test_other_unicode_version_is_not_rechecked(self):
        b, lines = self.treated_run()
        path, record = self.record_from(lines)
        record["python"]["unicode_version"] = "0.0.0"
        record["record_digest"] = record_digest(record)
        self.save_record(path, record)
        result = self.check_json("verify", "--final", b)
        self.assertEqual(result["status"], "executed")
        self.assertIn("treated_not_rechecked", [problem["code"] for problem in result["problems"]])

    def test_changed_check_is_tool_changed(self):
        scripts = copy_scripts(self.root, "skill-threshold")
        b, lines = self.treated_run(script=scripts / "yomiyasu_check.py")
        check = scripts / "yomiyasu_check.py"
        source = check.read_text(encoding="utf-8")
        self.assertIn("_SIMILAR_TO_SOURCE = 0.53\n", source)
        check.write_bytes(source.replace("_SIMILAR_TO_SOURCE = 0.53\n", "_SIMILAR_TO_SOURCE = 0.999\n").encode("utf-8"))
        process = self.check("verify", "--final", b, "--json", script=check)
        self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["status"], "tool_changed")
        self.assertNotIn("treated_as_source", [problem["code"] for problem in result["problems"]])


class TestReviewPartialNote(CheckCase):
    """compat 5: diff が最後まで動かなかった partial の1行目に「diff も実行しました」と書かない。注記は partial の文の前。"""

    def test_partial_run_says_the_diff_was_required(self):
        a = self.write("a.md", TestC44Run.SOURCE)
        b = self.write("b.md", TestC44Run.FINAL)
        process = self.check("run", "--material", a, "--final", b, "--timeout", "0.001")
        self.assertEqual(process.returncode, 3, process.stdout + process.stderr)
        line = split_lines(process.stdout)[0]
        self.assertTrue(line.startswith(C44_PENDING_NOTE + "検査の一部を実行できませんでした（"), line)
        self.assertTrue(line.endswith(PARTIAL_TAIL), line)
        self.assertNotIn(C44_NOTE, line)


if __name__ == "__main__":
    unittest.main()
