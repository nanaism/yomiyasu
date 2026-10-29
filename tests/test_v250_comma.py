"""v2.5.0: 読点の多すぎる文（8章）。

8b: diff の「読点が増えた」の候補（JSON の comma_increase）。最終稿の地の文の読点が原文より3個以上多く、1文あたりの読点が
0.3個以上増えたときだけ出す。meaning_risk_count、candidate_count、状態、--fail-on には入れない。
8c: lint の pause_comma（--doc-type を指定したときだけ）から、外すと掛かり先が変わる形（店長は、慌てて逃げた客を追いかけた）を
外し、6字以内の短い目的語の「を、」を足した（並べ、長い目的語、節の目的語、カギ括弧の目的語、引用、essay は外す）。
文は指示書の再現の表の12文と、自作の合成の文。
"""
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402

# 指示書の再現の表の12文と、article のときの pause_comma の当たった言い方（なければ空）。種類なしではどれも候補なし
TABLE = (
    ("まず、この機能は、ユーザーが、設定を、変更したときに、動きます。", ["ユーザーが", "設定を"]),
    ("このとき、システムは、受け取ったデータを、順番に、処理します。", ["システムは"]),
    ("また、ログは、一定期間、保存され、その後、自動的に、削除されます。", ["ログは"]),
    ("なお、この設定は、管理者だけが、変更できます。", ["管理者だけが"]),
    ("さらに、今回は、新しい、検索機能も、追加しました。", ["今回は", "検索機能も"]),
    ("つまり、私たちは、毎日、少しずつ、前に、進んでいます。", []),
    ("会議では、担当者が説明しました。", []),
    ("店長は、慌てて逃げた客を追いかけた。", []),
    ("東京、大阪、名古屋の3か所で開きます。", []),
    ("夜のうちに届いた荷物や手紙は、翌朝に仕分けます。", []),
    ("雨が降った場合は、延期します。", []),
    ("必要なファイルを集め、形式をそろえ、圧縮してから送ります。", []),
)


def pause(text, doc_type="article"):
    return [f for f in yomiyasu_lint.lint_text(text + "\n", doc_type=doc_type)["findings"] if f["rule"] == "pause_comma"]


def phrases(finding):
    return re.findall(r"「([^「」]+)、」", re.search(r"（(.*?)）", finding["message"]).group(1))


class PauseCommaTableTest(unittest.TestCase):
    def test_twelve_sentences(self):
        for text, expected in TABLE:
            with self.subTest(text=text):
                found = pause(text)
                self.assertEqual([phrases(f) for f in found], [expected] if expected else [])
                self.assertEqual(yomiyasu_lint.lint_text(text + "\n")["findings"], [])

    def test_object_message_only_when_there_is_an_object(self):
        """「を、」があるときだけ message の初めが「短い主語や主題、目的語」になる。ないときは 2.4.0 と同じ文。"""
        with_object = pause(TABLE[0][0])[0]["message"]
        without = pause(TABLE[1][0])[0]["message"]
        self.assertTrue(with_object.startswith("短い主語や主題、目的語のすぐあとに読点があります（"), with_object)
        self.assertTrue(without.startswith("短い主語や主題のすぐあとに読点があります（"), without)
        self.assertEqual(with_object.split("）", 1)[1], without.split("）", 1)[1])


class TenchoTest(unittest.TestCase):
    """外すと掛かり先が変わる形だけを狭く外す。"""

    def test_attachment_commas_are_kept(self):
        for text in ("店長は、慌てて逃げた客を追いかけた。", "店長は、急いで作った資料を配った。",
                     "担当者は、まとめて受け取った申請を確かめた。"):
            with self.subTest(text=text):
                self.assertEqual(pause(text), [])

    def test_other_topic_commas_still_hit(self):
        # 動詞の「〜て」でない「て」「で」（助詞の「で」、「である」「ではなく」「すでに」「ので」）と「〜ている」は数えない
        for text in ("店長は、急いで準備した。", "店長は、客を追いかけた。", "店長は、慌てて客を追いかけた。",
                     "今回は、試作機である端末を紹介します。", "この画面は、すでにある設定を表示します。",
                     "今回は、今までに集めた記録を整理します。", "山田さんは、引退ではなく移籍を選んだ。",
                     "この画面は、使っている端末を表示します。", "この記事は、東京で開いた会議を紹介します。",
                     "この機能は、古いので使わない設定を消します。", "今回は、手元で動く例を紹介します。",
                     "このツールは、誰でも使える機能を備えます。"):
            with self.subTest(text=text):
                self.assertEqual(len([f for f in pause(text) if f["rule"] == "pause_comma"]), 1)

    def test_particles_and_adverbs_ending_in_te_are_not_verb_te(self):
        """「て」「で」で終わる助詞と副詞（ai_phrase と同じ _TE_NOT_VERB の語）は動詞の「〜て」に数えず、2.4.0 と同じく候補に出す。"""
        for text in ("このページは、決して壊れない設定を説明します。", "このページは、けっして壊れない設定を説明します。",
                     "このページは、大して難しくない手順を説明します。", "店長は、例として挙げた手順を見る。",
                     "担当者は、来月に向けて作った計画を説明します。", "担当者は、改めて確認した内容を報告します。",
                     "担当者は、会場にて配った資料を集めます。", "店長は、雨のせいで遅れた客を案内した。"):
            with self.subTest(text=text):
                self.assertEqual(len([f for f in pause(text) if f["rule"] == "pause_comma"]), 1)
        found = yomiyasu_lint.lint_text("- このページは、決して壊れない設定を説明する\n", doc_type="slides")["findings"]
        self.assertEqual([f["rule"] for f in found if f["rule"] in ("pause_comma", "slide_comma")], ["pause_comma"])

    def test_slides_do_not_get_slide_comma_instead(self):
        found = yomiyasu_lint.lint_text("- 店長は、慌てて逃げた客を追いかけた\n", doc_type="slides")["findings"]
        self.assertEqual([f["rule"] for f in found if f["rule"] in ("pause_comma", "slide_comma")], [])
        found = yomiyasu_lint.lint_text("# 今回は、すでにある設定を見直す\n", doc_type="slides")["findings"]
        self.assertEqual([f["rule"] for f in found], ["slide_comma"])

    def test_slides_keep_other_object_commas(self):
        """pause_comma が拾った短い目的語の「を、」だけを slide_comma で重ねず、同じ行のほかの目的語の読点は出す。"""
        found = yomiyasu_lint.lint_text("- 受け取ったデータを、順番に処理し、設定を、保存する\n", doc_type="slides")["findings"]
        by_rule = {f["rule"]: f["message"] for f in found}
        self.assertIn("「設定を、」", by_rule["pause_comma"])
        self.assertIn("「受け取ったデータを、」", by_rule["slide_comma"])
        self.assertNotIn("「設定を、」", by_rule["slide_comma"])

    def test_slides_keep_topic_commas_when_pause_comma_has_only_objects(self):
        """pause_comma が「を、」だけを拾った1行の箇条でも、主題と主語の読点は slide_comma に出る（2.4.0 と同じく、どちらかに出る）。"""
        for line, topic in (("- これは、設定を、毎朝早い時間に一度だけ確かめるための手順", "「これは、」"),
                            ("- 私たちは、資料を、来週の定例会議までに全員分そろえます", "「私たちは、」")):
            with self.subTest(line=line):
                found = yomiyasu_lint.lint_text(line + "\n", doc_type="slides")["findings"]
                by_rule = {f["rule"]: f["message"] for f in found}
                self.assertNotIn(topic, by_rule["pause_comma"])
                self.assertIn(topic, by_rule["slide_comma"])
        found = yomiyasu_lint.lint_text("- 今日は、担当者が、設定を、確かめます\n", doc_type="slides")["findings"]
        self.assertEqual([f["rule"] for f in found], ["pause_comma"])


class ShortObjectTest(unittest.TestCase):
    HITS = ("設定を、変更したときに確かめます。", "ガイドの言葉を、直接お知らせしましょう。", "その画面を、毎朝開きます。",
            "ログを、毎晩消します。")
    KEEPS = (
        "予算を、人数を、期限を先に決めます。",          # Aを、Bを、の並べ
        "AとBを、比べます。",                          # AとBを、
        "パン、牛乳を、買います。",                     # A、Bを、
        "メール、カレンダー、連絡先、メモを、同期する。",  # A、B、Cを、
        "「設定」を、変更します。",                     # カギ括弧の目的語
        "これを、変更します。", "何を、どう伝えるか。",   # 指示語と疑問の語
        "設定を、管理者が変更します。",                 # 読点のあとに別の主語
        "前半は、受付の流れを、後半は、集計の方法を説明します。",
        "読んだ本を、棚に戻します。",                   # 節の目的語
        "長い長い説明文の目的語を、ここで切ります。",     # 7字以上の目的語
        "この画像を、画像処理ソフトを使って切り取ります。",  # 読点のあとの句にもう1つの「を」
        "彼は「設定を、変更した」と言った。",            # 引用の中
        "鍵を、なくした人に届けた。",                   # 読点のあとの節の動詞に目的語が掛かって読める
        "息子を、迎えに来た妻に預けた。",
        "資料を、急いで作った担当者に渡した。",
    )

    def test_short_objects_hit(self):
        for text in self.HITS:
            with self.subTest(text=text):
                found = pause(text)
                self.assertEqual(len(found), 1)
                self.assertTrue(any(p.endswith("を") for p in phrases(found[0])), found[0]["message"])

    def test_lists_long_clausal_quoted_and_actor_cases_are_kept(self):
        for text in self.KEEPS:
            with self.subTest(text=text):
                self.assertEqual(pause(text), [])

    def test_essay_and_no_type_do_not_get_objects(self):
        self.assertEqual(pause("設定を、変更したときに確かめます。", doc_type="essay"), [])
        self.assertEqual(pause("設定を、変更したときに確かめます。", doc_type=None), [])

    def test_hits_function_keeps_its_signature(self):
        """_pause_comma_hits は今までどおり「は」「が」「も」だけを返す（「を、」は別の関数）。"""
        self.assertEqual(yomiyasu_lint._pause_comma_hits("設定を、変更したときに確かめます。"), [])
        self.assertEqual([hit[1] for hit in yomiyasu_lint._pause_comma_object_hits("設定を、変更したときに確かめます。")],
                         ["を"])

    def test_corpus_human_does_not_get_more(self):
        for path in sorted((ROOT / "tests" / "corpus" / "human").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for doc_type in ("article", "slides", "manual"):
                with self.subTest(path=path.name, doc_type=doc_type):
                    found = [f for f in yomiyasu_lint.lint_text(text, doc_type=doc_type)["findings"]
                             if f["rule"] == "pause_comma"]
                    self.assertFalse([f for f in found if f["message"].startswith("短い主語や主題、目的語")])


ORIGINAL = ("この機能は、ユーザーが設定を変更したときに動きます。システムは受け取ったデータを順番に処理します。"
            "ログは一定期間保存され、その後自動的に削除されます。\n\nなお、この設定は管理者だけが変更できます。"
            "今回は新しい検索機能も追加しました。\n")
REWRITES = {
    # 読点を8個足しただけ（候補が出る）
    "plus8": ("この機能は、ユーザーが、設定を、変更したときに、動きます。システムは、受け取ったデータを、順番に処理します。"
              "ログは、一定期間、保存され、その後、自動的に削除されます。\n\nなお、この設定は管理者だけが変更できます。"
              "今回は新しい検索機能も追加しました。\n"),
    # 読点を変えない推敲、減らした推敲、2個だけ足した推敲（候補が出ない）
    "same": ("この機能は、ユーザーが設定を変えたときに動きます。システムは受け取ったデータを順番に処理します。"
             "ログは一定期間保存され、その後自動的に削除されます。\n\nなお、この設定は管理者だけが変更できます。"
             "今回は新しい検索機能も追加しました。\n"),
    "fewer": ("この機能はユーザーが設定を変更したときに動きます。システムは受け取ったデータを順番に処理します。"
              "ログは一定期間保存され、その後自動的に削除されます。\n\nこの設定は管理者だけが変更できます。"
              "今回は新しい検索機能も追加しました。\n"),
    "plus2": ("この機能は、ユーザーが、設定を変更したときに動きます。システムは、受け取ったデータを順番に処理します。"
              "ログは一定期間保存され、その後自動的に削除されます。\n\nなお、この設定は管理者だけが変更できます。"
              "今回は新しい検索機能も追加しました。\n"),
}


class CommaIncreaseTest(unittest.TestCase):
    def test_only_the_plus8_rewrite_gets_the_candidate(self):
        for name, final in REWRITES.items():
            with self.subTest(name=name):
                result = yomiyasu_diff.diff(ORIGINAL, final)
                self.assertEqual(result["meaning_risk_count"], 0)
                self.assertEqual(result["fail_on_meaning_risk_count"], 0)
                if name == "plus8":
                    item = result["comma_increase"]
                    self.assertEqual((item["old_count"], item["new_count"]), (3, 11))
                    self.assertEqual((item["old_sentences"], item["new_sentences"]), (5, 5))
                    self.assertEqual([(s["old_count"], s["new_count"]) for s in item["sentences"]], [(1, 4), (0, 2), (1, 4)])
                    self.assertIn("■ 読点が増えた（3個 → 11個。1文あたり 0.60個 → 2.20個。", yomiyasu_diff.report(result))
                else:
                    self.assertIsNone(result["comma_increase"])
                    self.assertNotIn("■ 読点が増えた", yomiyasu_diff.report(result))

    def test_not_counted_in_candidates_status_or_exit_code(self):
        result = yomiyasu_diff.diff(ORIGINAL, REWRITES["plus8"])
        without = dict(result, comma_increase=None)
        self.assertEqual(result["candidate_count"], without["candidate_count"])
        self.assertEqual(yomiyasu_diff._status_line(result), yomiyasu_diff._status_line(without))
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "a.md", Path(folder) / "b.md"
            old.write_bytes((ORIGINAL).encode("utf-8"))
            new.write_bytes((REWRITES["plus8"]).encode("utf-8"))
            process = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_diff.py"), "--fail-on", "meaning-risk",
                                      str(old), str(new)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertIn("■ 読点が増えた", process.stdout)
            check = subprocess.run([sys.executable, "-B", str(SCRIPTS / "yomiyasu_check.py"), "run", "--no-record",
                                    "--source", str(old), "--final", str(new)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertIn("読点の増加: 3 → 11個", check.stdout.split("\n")[3])
            self.assertIn("■ 読点が増えた", check.stdout)

    def test_exact_boundary_counts(self):
        """1文あたり0.3個ちょうどの増え方も出す（分数で比べる）。"""
        base = ["朝は、駅まで歩きます。", "昼は、近くの店で食べます。", "午後は、会議があります。", "夕方は、資料を読みます。",
                "夜は家で本を読みます。", "週末は公園に行きます。", "雨の日は家にいます。", "冬は早く寝ます。",
                "夏は川で泳ぎます。", "秋は山に登ります。"]
        old = "".join(base) + "\n"
        new = "".join(base[:4] + ["夜は、家で本を読みます。", "週末は、公園に行きます。", "雨の日は、家にいます。"] + base[7:]) + "\n"
        item = yomiyasu_diff.diff(old, new)["comma_increase"]
        self.assertEqual((item["old_count"], item["new_count"], item["old_sentences"], item["new_sentences"]), (4, 7, 10, 10))

    def test_quotes_with_periods_are_not_counted(self):
        old = "試合のあと、監督は記者の質問に答えた。「選手はよく走った。後半は足が止まった。次の試合までに立て直したい」と話した。\n"
        new = "試合のあと、監督は記者の質問に答えた。「選手は、よく走った。後半は、足が、止まった。次の試合までに、立て直したい」と話した。\n"
        self.assertIsNone(yomiyasu_diff.diff(old, new)["comma_increase"])
        self.assertIsNone(yomiyasu_diff.diff("設定を変えます。\n", "設定を変えます。`a、b、c、d` を見ます。\n")["comma_increase"])

    def test_joined_sentences_compare_with_both_originals(self):
        """2文をつないだ文は、つないだ元の2文の読点と比べる（つなぎの読点1個だけの増え方は文に挙げない）。"""
        old = "検索は、前より速くなった。索引は、夜に作り直す。ログは、30日で消える。通知は、まとめて届く。画面は、来月に直す。設定は、管理者が変える。\n"
        new = "検索は、前より速くなり、索引は、夜に作り直す。ログは、30日で消え、通知は、まとめて届く。画面は、来月に直し、設定は、管理者が変える。\n"
        item = yomiyasu_diff.diff(old, new)["comma_increase"]
        self.assertEqual((item["old_count"], item["new_count"]), (6, 9))
        self.assertEqual(item["sentences"], [])

    def test_same_text_has_no_candidate(self):
        self.assertIsNone(yomiyasu_diff.diff(ORIGINAL, ORIGINAL)["comma_increase"])

    def test_code_tables_quotes_and_urls_are_not_counted(self):
        old = "設定を変えます。\n"
        extra = ("設定を変えます。\n\n```\na、b、c、d、e\n```\n\n| a、b、c、d |\n|---|\n| e、f、g、h |\n\n"
                 "> 引用、引用、引用、引用\n\n彼は「あ、い、う、え」と言った。\n")
        self.assertIsNone(yomiyasu_diff.diff(old, extra)["comma_increase"])

    def test_json_key_is_last(self):
        self.assertEqual(list(yomiyasu_diff.diff(ORIGINAL, REWRITES["plus8"]))[-2:], ["heading_shapes", "comma_increase"])


if __name__ == "__main__":
    unittest.main()
