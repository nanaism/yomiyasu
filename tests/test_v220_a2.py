"""v2.2.0: 文の形の規則（say_hedge、copy_comma_noun、empty_shikumi、bare_verb_chain）を確かめる。

文はすべて自作の類例（v220-development/seed/g2-label-hedge と g4-copy-shikumi-verbs、所有者の類例の5〜8）と、
この試験のために作った文。
"""
from pathlib import Path
from unittest import mock
import io
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff  # noqa: E402
import yomiyasu_lint  # noqa: E402

SHAPE_RULES = ("say_hedge", "copy_comma_noun", "empty_shikumi", "bare_verb_chain")
COMMON_TAIL = "文脈を見て、誰が何をどうするかを書き直すか確かめてください。"

# 所有者の類例（指示書「作業を始める前に」）の5〜8と、当たる規則
OWNER_SEEDS = (
    ("この結果は、品質の向上につながったと言えるでしょう。", "say_hedge"),
    ("丁寧な、人。", "copy_comma_noun"),
    ("本当に大事なのは、続けられる仕組み。", "empty_shikumi"),
    ("切るか、続けるか、決める。", "bare_verb_chain"),
)
# 所有者の類例の1〜4（ほかの担当の規則）。この4つの規則は当たらない
OWNER_OTHER_SEEDS = (
    "取りこぼした通知は、翌朝の再送ジョブが拾います。",
    "社外からの接続は、この入口を通ります。",
    "新しい鍵に替えると、古い鍵の失効が効きます。",
    "プロジェクトのマイルストーンを決めます。",
)

SAY_HEDGE_FIX = (
    "7月以降の増加は、定期便の開始が主な原因だったと言えるでしょう。",
    "夜間の対応を続けたことは、解約の申し出の取りこぼしを防いだと言えるでしょう。",
    "一方で、定期便に関する問い合わせは下期も増えると言えるでしょう。",
    "今の社内ポータルは、役目を終えつつあると言えるでしょう。",
    "旧台帳からの予約の移し替えは総務部で行いますので、移行は大きな混乱なく進むと言えるでしょう。",
    "この手順で戻せば、データの欠けは最小限に抑えられると言えるでしょう。",
    "画像の遅延読み込みを入れたことで、表示の速さは十分に改善したと言えるでしょう。",
    "今回の停止は、証明書の更新漏れが直接の原因だったと言えるでしょう。",
    "20代の利用者の伸びは、9月の値引きの効果が大きかったと言えるでしょう。",
    "新しい勤怠システムには、多くの方がすでに慣れてきたと言えるでしょう。",
    "型を付けたことで、レビューで見落とす誤りは減ったと言えるでしょう。",
    "移行の作業は、予定どおり今月中に終わるといえるでしょう。",
)
SAY_HEDGE_KEEP = (
    # 引用と会話（カギ括弧の中）
    "「これは一生ものと言えるでしょう」というお便りも届いています。",
    "遊びに来ていた祖母に見せると、「これはもう立派な畑と言えるでしょう」と笑った。",
    "「あの人は、もう家族と言えるでしょう」と母は言った。",
    "刑事「この手口なら、三件とも同じ犯人と言えるでしょう」",
    "開発責任者は「この数字なら成功と言えるでしょう」と話しています。",
    # この言い回しそのものを話題にした文
    "なお、前回のお知らせにあった「〜と言えるでしょう」という書き方が分かりにくい、とのご意見をいただきました。",
    "「〜と言えるでしょう」は、書き手が言い切るのを避けたいときに使われやすい文末です。",
    # ある語や区分に当たるかの判断（直前が体言、「〜に当たる」）
    "法的には、この取り決めは契約と言えるでしょう。",
    "この開発は、社内規程の「大規模な情報システムの導入」に当たると言えるでしょう。",
    "前日の状態に戻す作業は、運用規程の「計画外の変更」に当たると言えるでしょう。",
    "申請者が個人で営む教室も、この要綱の「事業者」に当たると言えるでしょう。",
    "この取引は、金額と納期を書面で決めて部品の製造を頼んでいるので、下請法の対象に当たると言えるでしょう。",
    # 文末ではない、問いの形
    "そう言えるでしょうか、と担当者は首をかしげた。",
    "これで十分と言えるでしょうか。",
)

COPY_FIX = (
    "確かな、手応え。", "速い、表示を。", "長い、一日を。", "いつもの、安心を。", "小さな、贅沢。", "丁寧な、人。",
    "正確な、数字を。", "迷わない、画面。", "届いた、声。", "選ばれた、理由。", "軽い、運用を。", "新しい、毎日を。",
    "## やさしい、温度。", "- 麦の、香りを。",
)
COPY_KEEP = (
    "トップページの見出しの「ちいさな、会議を。」は広報の担当が決めた文句なので、プレビューでも変えずに表示します。",
    "細かな、けれど大事な変更が一つあります。",
    "「冷たい、手。」と、姉は私の指を握って笑った。",
    "去年の春には、店の奥で使っていた古い、角の欠けた机を竹内さんから譲り受けた。",
    "重たい、湿った空気が廊下に残っていた。",
    "安全な、検証済みの設定だけを使います。",
    "新しい、まだ試していない手順なので、作業は2人で行います。",
    "広報紙の題字「みどりの、まち。」は、昭和の終わりから使っています。",
    "大きな、重い荷物は、別の便で送ります。",
    # 感動詞、接続詞、指示語のあとの読点
    "はい、了解。", "また、今度。", "あの、すみません。",
    # 読点の前が節（助詞を含む）、名詞が「の」を含む名詞句、述語で終わる
    "要約の依頼で条件を残した、やや長い出力。",
    "3 書けない、内部の誤り。",
    "迷った、決めた。",
    "> 丁寧な、人。",
)

SHIKUMI_FIX = (
    "問い合わせを減らす仕組みを作る。", "障害に強い仕組みです。", "迷わず使える仕組みになっています。",
    "数字が自然に集まる仕組みです。", "本当に大事なのは、続けられる仕組み。", "申請から承認までが滞らない仕組みになっています。",
    "変更が安全に届く仕組み。", "誰が担当しても同じ品質になる仕組みです。", "手戻りが起きにくい仕組みになっています。",
    "新人がすぐに戦力になる仕組み。", "学びが次に生きる仕組みを作る。", "結局のところ、残るのは続く仕組みです。",
    "記録が自然に残る仕組みを作ります。", "大事なのは、続けるしくみだ。",
)
SHIKUMI_KEEP = (
    # 「仕組み」で終わらない
    "仕組みを見直した結果、月末の残業が半分になりました。",
    "その仕組みについては、次の節で順に説明します。",
    # 引用の中
    "「人を責めず、仕組みを直す」が、この班の決まりです。",
    "班の標語は「続けられる仕組み。」です。",
    # 同じ行に negative_parallelism の候補がある
    "足りないのは人ではなく、仕組みです。",
)

BARE_FIX = (
    "撮る、送る、待つ。", "書く、試す、直す。", "上げる、確かめる、戻す。", "切るか、続けるか、決める。",
    "集める、並べる、確かめる。", "止めるか、待つか、戻すか、選ぶ。", "開く、閉じる、記録する。",
    "足すか、削るか、残すか、判断する。", "調べる、決める、動く。", "待つか、急ぐか、見極める。",
    "消すか、残すか、話し合う。", "読む、まとめる、伝える。", "- 測る、比べる、選ぶ。", "上がる、下がる、止まる。",
)
BARE_KEEP = (
    # 主語や目的語がある、部分が連用形で終わる
    "開発者が書き、CI が組み立て、レビュー担当が確かめる。",
    "箱を開け、中身を数え、伝票と照らし合わせる。",
    "まず原因を調べ、次に対策を決め、来週から動く。",
    "利用者が申請し、管理者が承認し、システムが通知する。",
    "数が合う、送る、待つ。",
    # 台詞の中、命令形
    "「逃げるか、隠れるか、今すぐ選べ。」",
    # 丁寧の形、部分が2つ、30字を超える
    "確認します、送ります、待ちます。",
    "書く、試す。",
    "はじめに設定を読み込み直す、次に記録を確かめる、最後に送る。",
    # 数や形容詞
    "一つ、二つ、三つ。",
    "楽しく、美しく、強く。",
)


def shape_findings(text, doc_type=None):
    result = yomiyasu_lint.lint_text(text, doc_type=doc_type)
    return [finding for finding in result["findings"] if finding["rule"] in SHAPE_RULES]


def rules_of(text, doc_type=None):
    return [finding["rule"] for finding in shape_findings(text, doc_type)]


class OwnerSeedTest(unittest.TestCase):
    def test_owner_seeds_5_to_8(self):
        for text, rule in OWNER_SEEDS:
            with self.subTest(text=text):
                self.assertEqual(rules_of(text + "\n"), [rule])

    def test_owner_seeds_5_to_8_in_one_document(self):
        text = "".join(sentence + "\n" for sentence, _ in OWNER_SEEDS)
        found = shape_findings(text)
        self.assertEqual([(finding["rule"], finding["line"]) for finding in found],
                         [(rule, line) for line, (_, rule) in enumerate(OWNER_SEEDS, 1)])

    def test_owner_seeds_1_to_4_are_not_shape_findings(self):
        for text in OWNER_OTHER_SEEDS:
            with self.subTest(text=text):
                self.assertEqual(rules_of(text + "\n"), [])


class RuleTestBase(unittest.TestCase):
    rule = None
    fix = ()
    keep = ()

    def check(self):
        for text in self.fix:
            with self.subTest(text=text, label="fix"):
                self.assertIn(self.rule, rules_of(text + "\n"))
        for text in self.keep:
            with self.subTest(text=text, label="keep"):
                self.assertNotIn(self.rule, rules_of(text + "\n"))


class SayHedgeTest(RuleTestBase):
    rule, fix, keep = "say_hedge", SAY_HEDGE_FIX, SAY_HEDGE_KEEP

    def test_seed(self):
        self.check()

    def test_owner_seed_alone_and_after_a_sentence(self):
        self.assertEqual(rules_of("前年より問い合わせが減りました。この結果は、品質の向上につながったと言えるでしょう。\n"),
                         ["say_hedge"])

    def test_adjective_stems_are_hedges_but_noun_judgements_are_not(self):
        """形容動詞の語幹（「有効」「効果的」）のあとの「と言えるでしょう」は印をつけ、名詞の判断（「契約」）にはつけない。"""
        for text in ("新しい手順は、問い合わせの多い部署で有効と言えるでしょう。\n",
                     "週ごとの見直しは、小さなチームにとって効果的と言えるでしょう。\n",
                     "鍵を分けて保管するのは、復旧の面でも重要と言えるでしょう。\n"):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text), ["say_hedge"])
        for text in ("この覚え書きは、法の上では契約と言えるでしょう。\n",
                     "今回の遅れは、取り決めの違反に当たると言えるでしょう。\n",
                     "これは一つの効果と言えるでしょう。\n"):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text), [])


class CopyCommaNounTest(RuleTestBase):
    rule, fix, keep = "copy_comma_noun", COPY_FIX, COPY_KEEP

    def test_seed(self):
        self.check()

    def test_promo_counts_from_the_second_hit(self):
        """promo では文書の中で2回目に当たったものから出す。ほかの種類と種類なしでは1回目から出す。"""
        text = "## やさしい、温度。\n\n朝から晩まで温度が変わりません。\n\n長い、一日を。\n\n小さな、贅沢。\n"
        self.assertEqual([finding["line"] for finding in shape_findings(text, "promo")], [5, 7])
        for doc_type in (None, "article", "essay", "slides", "mail"):
            with self.subTest(doc_type=doc_type):
                self.assertEqual([finding["line"] for finding in shape_findings(text, doc_type)], [1, 5, 7])

    def test_promo_used_once_is_not_flagged(self):
        text = "## 麦の、香りを。\n\n朝6時に焼き上がります。\n"
        self.assertEqual(rules_of(text, "promo"), [])
        self.assertEqual(rules_of(text), ["copy_comma_noun"])

    def test_one_finding_per_line(self):
        self.assertEqual(rules_of("いつもの、安心を。小さな、贅沢。\n"), ["copy_comma_noun"])
        self.assertEqual(rules_of("いつもの、安心を。小さな、贅沢。\n", "promo"), ["copy_comma_noun"])


class EmptyShikumiTest(RuleTestBase):
    rule, fix, keep = "empty_shikumi", SHIKUMI_FIX, SHIKUMI_KEEP

    def test_seed(self):
        self.check()

    def test_not_on_a_negative_parallelism_line(self):
        text = "足りないのは人ではなく、仕組みです。\n"
        rules = [finding["rule"] for finding in yomiyasu_lint.lint_text(text)["findings"]]
        self.assertIn("negative_parallelism", rules)
        self.assertNotIn("empty_shikumi", rules)
        # 段落がソフトな改行で続くとき、negative_parallelism は段落の否定の行に出る。同じ段落の「仕組みだ。」にも出さない
        text = "# 観察\n\n努力ではない。\n才能でもない。仕組みだ。\n"
        found = [(finding["rule"], finding["line"]) for finding in yomiyasu_lint.lint_text(text)["findings"]]
        self.assertEqual(found, [("negative_parallelism", 3)])
        # 別の段落の negative_parallelism は外す理由にならない
        text = "足りないのは人ではなく、手順です。\n\n障害に強い仕組みです。\n"
        found = [(finding["rule"], finding["line"]) for finding in yomiyasu_lint.lint_text(text)["findings"]]
        self.assertIn(("negative_parallelism", 1), found)
        self.assertIn(("empty_shikumi", 3), found)

    def test_explained_sentences_are_still_marked(self):
        """前後の文で説明していても印はつく（残すかは推敲で決める）。"""
        text = "マージすると、プレビュー環境は30分後に自動で消えます。消し忘れたまま費用がかさむことのない仕組みです。\n"
        self.assertEqual(rules_of(text), ["empty_shikumi"])


class BareVerbChainTest(RuleTestBase):
    rule, fix, keep = "bare_verb_chain", BARE_FIX, BARE_KEEP

    def test_seed(self):
        self.check()

    def test_inside_a_line_after_another_sentence(self):
        self.assertEqual(rules_of("プレビュー環境の費用は、月に4万円ほどかかっています。切るか、続けるか、決める。\n"),
                         ["bare_verb_chain"])

    def test_markup_inside_the_sentence(self):
        self.assertEqual(rules_of("**撮る**、**送る**、**待つ**。\n"), ["bare_verb_chain"])
        self.assertEqual(rules_of("`撮る`、送る、待つ。\n"), [])


class CommonTest(unittest.TestCase):
    def test_severity_message_and_snippet(self):
        for text, rule in OWNER_SEEDS:
            line = "- " + text
            with self.subTest(rule=rule):
                found = shape_findings("前置きの文です。\n\n" + line + "\n")
                self.assertEqual(len(found), 1)
                finding = found[0]
                self.assertEqual(sorted(finding), ["line", "message", "rule", "severity", "snippet"])
                self.assertEqual((finding["rule"], finding["line"], finding["severity"], finding["snippet"]),
                                 (rule, 3, "info", line))
                self.assertTrue(finding["message"].endswith("の候補です。" + COMMON_TAIL), finding["message"])

    def test_messages_name_no_replacement(self):
        for rule, message in yomiyasu_lint._SHAPE_RULE_MESSAGES.items():
            with self.subTest(rule=rule):
                self.assertTrue(message.endswith("の候補です。" + COMMON_TAIL))
                self.assertNotIn("に替え", message)
                self.assertNotIn("に置き換え", message)

    def test_skipped_places(self):
        """コード、frontmatter、引用の行、表、HTML、カギ括弧の中は見ない。"""
        for text in (
                "```\n丁寧な、人。\n切るか、続けるか、決める。\n```\n",
                "---\ntitle: 障害に強い仕組みです。\n---\n本文です。\n",
                "> 丁寧な、人。\n> 切るか、続けるか、決める。\n> 障害に強い仕組みです。\n",
                "| 列 | 説明 |\n|---|---|\n| 丁寧な、人。 | 切るか、続けるか、決める。 |\n",
                "<div>\n障害に強い仕組みです。\n</div>\n",
                "`丁寧な、人。` と `障害に強い仕組みです。` は例です。\n",
                "「丁寧な、人。」『切るか、続けるか、決める。』と書いた。\n",
                "“丁寧な、人。”と書いた。\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text), [])

    def test_score_and_exit_code_do_not_change(self):
        text = "".join(sentence + "\n\n" for sentence, _ in OWNER_SEEDS)
        result = yomiyasu_lint.lint_text(text)
        self.assertEqual(sorted(finding["rule"] for finding in result["findings"]), sorted(rule for _, rule in OWNER_SEEDS))
        self.assertEqual(result["counts"], {"error": 0, "warn": 0, "info": 4})
        self.assertEqual(result["rule_penalty_score"], 100)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "seed.md"
            path.write_bytes(text.encode("utf-8"))
            for argv in (["--strict", str(path)], ["--fail-on=warn", str(path)], ["--fail-on=error", str(path)]):
                with self.subTest(argv=argv), mock.patch.object(sys, "stdout", io.StringIO()):
                    self.assertEqual(yomiyasu_lint.main(argv), 0)

    def test_document_types_do_not_raise(self):
        text = "".join(sentence + "\n" for sentence, _ in OWNER_SEEDS)
        for doc_type in yomiyasu_lint.DOC_TYPE_SKIP_RULES:
            with self.subTest(doc_type=doc_type):
                yomiyasu_lint.lint_text(text, doc_type=doc_type)

    def test_crlf_input(self):
        text = "".join(sentence + "\r\n" for sentence, _ in OWNER_SEEDS)
        self.assertEqual(sorted(rules_of(text)), sorted(rule for _, rule in OWNER_SEEDS))


class SayHedgeDiffTest(unittest.TestCase):
    def test_removing_to_ieru_is_not_a_meaning_risk(self):
        """「〜につながったと言えるでしょう。」を「〜につながったでしょう。」にした組は、意味が変わる恐れ0件（指示書3章）。"""
        pairs = (
            ("この結果は、品質の向上につながったと言えるでしょう。\n", "この結果は、品質の向上につながったでしょう。\n"),
            ("型を付けたことで、レビューで見落とす誤りは減ったと言えるでしょう。\n",
             "型を付けたことで、レビューで見落とす誤りは減ったでしょう。\n"),
            ("7月以降の増加は、定期便の開始が主な原因だったと言えるでしょう。\n",
             "7月以降の増加は、定期便の開始が主な原因だったでしょう。\n"),
        )
        for original, rewrite in pairs:
            with self.subTest(original=original):
                result = yomiyasu_diff.diff(original, rewrite)
                self.assertEqual(result["meaning_risks"], [])
                self.assertEqual(result["meaning_risk_count"], 0)
                self.assertEqual(yomiyasu_diff.meaning_risks(original, rewrite), [])


if __name__ == "__main__":
    unittest.main()
