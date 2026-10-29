"""v2.4.0: diff の「原文にない人や担当を足した文」（JSON の added_actors）。

- 推敲で、原文と資料にない人・担当・部署を、主語か、知らせる・頼む相手として足した文を出す。
- 意味が変わる恐れの kind ではない。meaning_risk_count、candidate_count、状態、状態の行、--fail-on の終了コード、check の
  記録の meaning_risk= は変わらない（JSON に足すのは最後のキー added_actors だけ）。
- yomiyasu 自身が勧めるカタカナの役割語の和語への言い換え（ステークホルダー → 関係者など）、原文にある人の別の書き方、
  原文に書き手の一人称があるときの一人称、資料にある人は出さない。
- check run は同じ節を出し、資料を diff に渡す（verify --replay も同じ資料で作り直す）。

文はすべて自作の合成の文。
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DIFF = SCRIPTS / "yomiyasu_diff.py"
CHECK = SCRIPTS / "yomiyasu_check.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))
import yomiyasu_diff  # noqa: E402
from portable import paced_limit, timing_clock  # noqa: E402

HEADING = "■ 原文にない人や担当を足した文（{}件。原文、資料、依頼のどれにもない人や担当なら、原文の書き方に戻す）"

# 出るべき組: (原文, 推敲後, [(語, 役割, 区分)])
FLAGS = (
    ("容量が一割を切ったら知らせる。", "容量が一割を切ったら、保守担当者に知らせる。", [("保守担当者", "recipient", "A")]),
    ("エラー率が5%を超えたらアラートを出す。", "エラー率が5%を超えたら、情シスに連絡する。", [("情シス", "recipient", "A")]),
    ("申請書は月末までに提出する。", "申請者は月末までに申請書を総務部へ提出する。",
     [("申請者", "subject", "B"), ("総務部", "recipient", "A")]),
    ("設定を変更したら再起動する。", "管理者は設定を変更したら再起動する。", [("管理者", "subject", "B")]),
    ("不具合が見つかったら報告してください。", "不具合が見つかったら上長に報告してください。", [("上長", "recipient", "A")]),
    ("請求書の再発行を受け付けました。", "経理課が請求書の再発行を受け付けました。", [("経理課", "subject", "B")]),
    ("原因を調査中です。", "開発チームが原因を調査中です。", [("開発チーム", "subject", "B")]),
    ("会議の議事録を共有します。", "議事録は田中さんから共有します。", [("田中さん", "subject", "B")]),
    ("バックアップは毎晩取得する。", "当番の人がバックアップを毎晩取得する。", [("当番の人", "subject", "B")]),
    ("更新があれば通知される。", "更新があれば利用者に通知する。", [("利用者", "recipient", "A")]),
    ("承認後に公開する。", "責任者が承認したら公開する。", [("責任者", "subject", "B")]),
    ("障害が起きたら連絡する。", "障害が起きたら経理の担当者に連絡する。", [("経理の担当者", "recipient", "A")]),
    ("ログを確認する。", "SREがログを確認する。", [("SRE", "subject", "B")]),
    ("同じ通知が二度届く前提で作る。", "開発者は同じ通知が二度届く前提で作る。", [("開発者", "subject", "C")]),
    ("その認識が共有された。", "その認識を全員が共有した。", [("全員", "subject", "C")]),
    # 原文に書き手の一人称がないのに、一人称を主語に足した（persona.md 5章の3）
    ("手順を見直しました。", "私たちは手順を見直しました。", [("私たち", "subject", "W")]),
    # 「お」の付いた呼び名は「お」も語に含めて出す（「客さん」「嬢さん」と欠けた語にしない）
    ("注文が届いたら連絡する。", "注文が届いたら、お客さんに連絡する。", [("お客さん", "recipient", "A")]),
    ("駅で待ち合わせた。", "駅でお嬢さんが待っていた。", [("お嬢さん", "subject", "B")]),
    # 動作主の「より」（すぐあとが読点か、知らせる・伝える語）は主語に数える
    ("あとで連絡します。", "あとで総務部より連絡します。", [("総務部", "subject", "B")]),
    ("お知らせです。", "事務局より、お知らせです。", [("事務局", "subject", "B")]),
    ("日程を決めました。", "日程は事務局よりご案内します。", [("事務局", "subject", "B")]),
)

# 出ないべき組: (原文, 推敲後)
KEEPS = (
    # yomiyasu 自身が勧めるカタカナの役割語の和語への言い換え
    ("ステークホルダーに共有する。", "関係者に共有する。"),
    ("ステークホルダーに連絡する。", "関係部署に連絡する。"),
    ("アドミンに依頼する。", "管理者に依頼する。"),
    ("レビュアーが確認する。", "レビュー担当者が確認する。"),
    ("レビュワーが確認する。", "レビュー担当者が確認する。"),
    ("オーナーが決める。", "責任者が決める。"),
    ("オーナーが決める。", "持ち主が決める。"),
    ("サポートに連絡する。", "サポート窓口に連絡する。"),
    ("オンコールに連絡する。", "当番に連絡する。"),
    ("オンコールに連絡する。", "当番の担当者に連絡する。"),
    ("ユーザーが設定する。", "利用者が設定する。"),
    # 原文にある人の別の書き方
    ("運用担当が確認する。結果を残す。", "運用担当者が確認し、結果を残す。"),
    ("受付の担当者が入館証を渡す。", "受付担当者が入館証を渡す。"),
    ("PMに相談してください。", "プロジェクトマネージャーに相談してください。"),
    ("情報システム部が管理する。", "情シスが管理する。"),
    ("総務に提出する。", "総務部に提出する。"),
    ("営業部門が担当する。", "営業部が担当する。"),
    ("上司に報告する。", "上長に報告する。"),
    ("お客さまに案内する。", "お客様に案内する。"),
    ("経理部の担当者が処理する。", "経理担当者が処理する。"),
    ("開発側で直す。", "開発チームが直す。"),
    ("システムの管理者が設定する。", "システム管理者が設定する。"),
    ("詳しくは営業部の佐藤までご連絡ください。", "詳しくは佐藤さんまでご連絡ください。"),
    ("田中さんが調べています。分かったら連絡します。", "田中さんが調べています。分かったら田中さんから連絡します。"),
    # 書き手の自称の言い換えと、原文にある一人称の補い
    ("こちらでは確認できていません。", "弊社では確認できておりません。"),
    ("弊社で対応します。", "当社で対応します。"),
    ("私が設定を戻しました。再起動して確かめました。", "私が設定を戻しました。私が再起動して確かめました。"),
    # 人でない語
    ("システムが自動で通知する。", "システムが自動で知らせる。"),
    ("監視ツールがアラートを送る。", "監視ツールがアラートを送信する。"),
    ("この一部の設定は内部で使う。", "この設定の一部は内部で使う。"),
    ("仕様を変えた。", "仕様は変えた。"),
    ("同じように知らせる。", "同様に知らせる。"),
    ("第1部で説明する。", "第1部では説明する。"),
    ("回転数を上げる。", "RPMは上げる。"),
    ("値の小数の部分を丸める。", "小数部は丸める。"),
    # 人や担当を、主語でも知らせる相手でもない形で書いた（の、を、と）
    ("承認を得てから公開する。", "管理者の承認を得てから公開する。"),
    # 人でない「〜さま」（逆さま）
    ("画像が上下反対に表示されていないか確かめる。", "画像が逆さまに表示されていないか確認する。"),
    ("画像が上下反対に表示されていないか確かめる。", "画像が逆様に表示されていないか確認する。"),
    # 地域の「〜部」と、データの区切りの「〜部」
    ("都会では人口が増えている。", "都市部では人口が増えている。"),
    ("海の近くでは風が強い。", "沿岸部では風が強い。"),
    ("山の中では雪が多い。", "山間部では雪が多い。"),
    ("パケットの後半には値が入る。", "パケットのデータ部には値が入る。"),
    ("後ろには中身が入る。", "ペイロード部には中身が入る。"),
    ("最上位の1ビットは正負を表す。", "符号部は正負を表す。"),
    ("末尾の値は検証に使う。", "署名部は検証に使う。"),
    # 比べる「より」は主語の助詞に数えない
    ("新しい方式は速い。", "新しい方式は前のチームより速い。"),
    ("新しい方式は速い。", "新しい方式は前のチームよりも速い。"),
    ("確認する。", "担当者より先に確認する。"),
    # 同じ人を指す別の書き方（読者と読み手、開発者とエンジニア、スタッフと社員）
    ("この書き方だと読み手が迷う。", "この書き方だと読者は迷う。"),
    ("この書き方だと読者が迷う。", "この書き方だと読み手は迷う。"),
    ("エンジニアが設定を確認する。", "開発者が設定を確認する。"),
    ("開発メンバーが設定を確認する。", "エンジニアが設定を確認する。"),
    ("社員が窓口で対応する。", "スタッフが窓口で対応する。"),
    ("職員が窓口で対応する。", "スタッフが窓口で対応する。"),
    # お客様、お客さん、顧客は同じ人を指す
    ("顧客に案内する。", "お客様に案内する。"),
    ("注文が届いたら顧客に連絡する。", "注文が届いたら、お客さんに連絡する。"),
    ("注文が届いたらお客様に連絡する。", "注文が届いたら、お客さんに連絡する。"),
    # 人名とみなさない「お子さん」「お母さん」（表の語を「お」の付いた形で照らす）
    ("連絡帳に書いてください。", "お子さんは連絡帳に書いてください。"),
    ("夕方に知らせた。", "夕方にお母さんに知らせた。"),
    # 役割の語を含む「お〜様」は、役割の語のまま原文と照らす
    ("取引先に送る。", "お取引先様に送る。"),
)


def added(old, new, materials=None):
    return yomiyasu_diff.diff(old + "\n", new + "\n", materials=materials)["added_actors"]


def words(items):
    return [(actor["word"], actor["frame"], actor["tier"]) for item in items for actor in item["actors"]]


class AddedActorTest(unittest.TestCase):
    def test_flags(self):
        for old, new, expected in FLAGS:
            with self.subTest(new=new):
                self.assertEqual(words(added(old, new)), expected)

    def test_keeps(self):
        for old, new in KEEPS:
            with self.subTest(new=new):
                self.assertEqual(added(old, new), [])

    def test_item_shape(self):
        [item] = added("担当者に連絡する。", "運用担当者に連絡する。")
        self.assertEqual(list(item), ["old_line", "new_line", "old", "new", "actors"])
        self.assertEqual((item["old_line"], item["new_line"], item["old"], item["new"]),
                         (1, 1, "担当者に連絡する。", "運用担当者に連絡する。"))
        # 原文の「担当者」に語を足して狭めた
        self.assertEqual(item["actors"], [{"word": "運用担当者", "frame": "recipient", "tier": "A", "narrowed_from": "担当者"}])

    def test_materials(self):
        old, new = "容量が一割を切ったら知らせる。", "容量が一割を切ったら、保守担当者に知らせる。"
        self.assertEqual(len(added(old, new)), 1)
        self.assertEqual(added(old, new, materials=["保守担当者が容量を見ています。"]), [])
        self.assertEqual(len(added(old, new, materials=["別の資料です。"])), 1)

    def test_self_reference_in_source(self):
        # 原文のどこかに書き手の自称があれば、一人称を主語に足しても出さない（原文にある一人称の補い）
        self.assertEqual(added("こちらで調べます。手順を見直しました。", "こちらで調べます。私たちは手順を見直しました。"), [])
        # 読み手を呼ぶ語は、書き手の自称があっても出す
        self.assertEqual(words(added("私が調べます。設定を確かめてください。", "私が調べます。皆さんは設定を確かめてください。")),
                         [("皆さん", "subject", "W")])

    def test_code_and_url_are_not_read(self):
        self.assertEqual(added("文字列を探す。", "`管理者が` という文字列を探す。"), [])
        self.assertEqual(added("手順:\n\n```\necho\n```", "手順:\n\n```\n管理者が echo する\n```"), [])

    def test_unpaired_sentence_takes_the_nearest_source_sentence(self):
        old = "障害の経緯をまとめる。設定を戻して復旧した。今後は監視を足す。"
        new = "障害の経緯をまとめる。設定を戻して復旧した。今後は運用チームが監視を足し、閾値も見直す。結果は翌週に共有する。"
        items = added(old, new)
        self.assertEqual(words(items), [("運用チーム", "subject", "B")])
        self.assertEqual(items[0]["old"], "今後は監視を足す。")

    def test_same_sentence_is_read_once(self):
        # 同じ段落を何度もくり返す文書でも、文ごとに1件（くり返した数だけ出る）
        old = "\n\n".join(["設定を変更したら再起動する。"] * 3) + "\n"
        new = "\n\n".join(["管理者は設定を変更したら再起動する。"] * 3) + "\n"
        items = yomiyasu_diff.diff(old, new)["added_actors"]
        self.assertEqual([item["new_line"] for item in items], [1, 3, 5])


class NotAMeaningRiskTest(unittest.TestCase):
    """added_actors は数えない。ほかのキーと人が読む出力の節（この節を除く）は、検査を外したときと1字も違わない。"""

    OLD = "# 手順\n\n設定を変更したら再起動する。\n\n不具合が見つかったら報告してください。\n"
    NEW = "# 手順\n\n管理者は設定を変更したら再起動する。\n\n不具合が見つかったら上長に報告してください。\n"

    def without_actors(self):
        original = yomiyasu_diff._added_actors
        yomiyasu_diff._added_actors = lambda sides, groups, materials=(): []
        try:
            return yomiyasu_diff.diff(self.OLD, self.NEW)
        finally:
            yomiyasu_diff._added_actors = original

    def test_other_keys_do_not_change(self):
        result = yomiyasu_diff.diff(self.OLD, self.NEW)
        self.assertEqual(len(result["added_actors"]), 2)
        # 2.5.0 で、見出しの形の変化（heading_shapes）と、読点が増えた候補（comma_increase）を後ろに足した
        self.assertEqual(list(result)[-3:], ["added_actors", "heading_shapes", "comma_increase"])
        plain = self.without_actors()
        self.assertEqual(dict(result, added_actors=[]), plain)
        self.assertFalse([risk for risk in result["meaning_risks"] if "actor" in risk["kind"]])

    def test_report_only_adds_the_section(self):
        result = yomiyasu_diff.diff(self.OLD, self.NEW)
        report = yomiyasu_diff.report(result)
        section = yomiyasu_diff.report_parts(result)["added_actors"]
        self.assertEqual(section.split("\n"), [
            HEADING.format(2),
            "- 主語に「管理者」を足しました（3行目）",
            "  元: 設定を変更したら再起動する。",
            "  後: 管理者は設定を変更したら再起動する。",
            "- 知らせる・頼む相手に「上長」を足しました（5行目）",
            "  元: 不具合が見つかったら報告してください。",
            "  後: 不具合が見つかったら上長に報告してください。"])
        self.assertEqual(report.replace(section + "\n\n", ""), yomiyasu_diff.report(self.without_actors()))
        # 規則の見直し候補のあと、文体の硬化の前
        self.assertLess(report.index("■ 規則の見直し候補"), report.index(HEADING.format(2)))
        self.assertLess(report.index(HEADING.format(2)), report.index("■ 全文差分"))
        # 状態の行は変わらない
        self.assertEqual(report.split("\n")[1], yomiyasu_diff.report(self.without_actors()).split("\n")[1])

    def test_no_section_without_candidates(self):
        result = yomiyasu_diff.diff("設定を変更する。\n", "設定を変える。\n")
        self.assertEqual(result["added_actors"], [])
        self.assertEqual(yomiyasu_diff.report_parts(result)["added_actors"], "")
        self.assertNotIn("原文にない人や担当", yomiyasu_diff.report(result))


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="yomiyasu-actor-")
        self.addCleanup(folder.cleanup)
        self.root = Path(os.path.realpath(folder.name))
        self.source = self.write("source.md", "容量が一割を切ったら知らせる。\n\n設定を変更したら再起動する。\n")
        self.final = self.write("final.md", "容量が一割を切ったら、保守担当者に知らせる。\n\n管理者は設定を変更したら再起動する。\n")
        self.material = self.write("material.md", "保守担当者が毎朝、容量を見ています。\n")

    def write(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def run_tool(self, tool, *args):
        env = dict(os.environ)
        env["YOMIYASU_STATE_DIR"] = str(self.root / ".yomiyasu")
        process = subprocess.run([sys.executable, "-B", str(tool)] + [str(arg) for arg in args], capture_output=True,
                                 cwd=str(self.root), env=env)
        return process.returncode, process.stdout.decode("utf-8"), process.stderr.decode("utf-8")

    def test_diff_json_and_material(self):
        code, out, err = self.run_tool(DIFF, "--json", "--no-words", self.source, self.final)
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(words(result["added_actors"]), [("保守担当者", "recipient", "A"), ("管理者", "subject", "B")])
        code, out, err = self.run_tool(DIFF, "--json", "--no-words", "--material", self.material, self.source, self.final)
        self.assertEqual((code, err), (0, ""))
        with_material = json.loads(out)
        self.assertEqual(words(with_material["added_actors"]), [("管理者", "subject", "B")])
        # 資料は added_actors のほかを変えない
        self.assertEqual(dict(with_material, added_actors=[]), dict(result, added_actors=[]))

    def test_fail_on_is_not_hit(self):
        code, out, err = self.run_tool(DIFF, "--fail-on", "meaning-risk", "--no-words", self.source, self.final)
        self.assertEqual((code, err), (0, ""))
        self.assertIn(HEADING.format(2), out)
        self.assertIn("状態: 変更あり（2か所）。見直し候補 2件、うち意味が変わる恐れ 0件", out)
        self.assertNotIn("終了コード1", out)

    def test_endings_does_not_take_material(self):
        code, _, err = self.run_tool(DIFF, "--endings", "--material", self.material, self.final)
        self.assertEqual(code, 2)
        self.assertIn("--endings は --material に対応していません", err)

    def test_check_run_shows_the_section_and_passes_materials(self):
        code, out, err = self.run_tool(CHECK, "run", "--no-words", "--no-record", "--source", self.source, "--final", self.final)
        self.assertEqual((code, err), (0, ""))
        lines = out.split("\n")
        self.assertIn("meaning_risk=0", lines[1])
        self.assertIn("原文にない人や担当: 後1行目 保守担当者、後3行目 管理者", lines[3])
        self.assertIn(HEADING.format(2), out)
        self.assertLess(out.index("■ 差分の見直し候補（diff、"), out.index(HEADING.format(2)))
        self.assertLess(out.index(HEADING.format(2)), out.index("■ 全文差分（"))
        # 資料にある人は出さない。記録した run は、verify --replay でも同じ資料で diff を作り直す
        code, out, err = self.run_tool(CHECK, "run", "--no-words", "--source", self.source, "--material", self.material,
                                       "--final", self.final)
        self.assertEqual((code, err), (0, ""))
        self.assertIn(HEADING.format(1), out)
        self.assertNotIn("「保守担当者」", out)
        code, out, err = self.run_tool(CHECK, "verify", "--final", self.final, "--replay")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("replay=ok", out.split("\n")[1])

    def test_check_first_line_names_the_section_when_nothing_else_is_found(self):
        # 規則に当たる候補がなく、人や担当の足しだけがあるとき（diff の結果を差し替えて、1行目の文だけを見る）
        sys.path.insert(0, str(SCRIPTS))
        import yomiyasu_check
        ctx = yomiyasu_check._Context()
        ctx.mode, ctx.required = "rewrite", ["lint", "diff"]
        ctx.entries["lint"] = {"status": "ran"}
        ctx.entries["diff"] = {"status": "ran"}
        ctx.diff_result = {"status": "has_candidates", "candidate_count": 0, "added_actors": [{"actors": []}]}
        ctx.lint_result = {"candidate_count": 0}

        class Final(object):
            via, sha256, text_sha256 = "file", "a", "a"

            def token(self):
                return "sha256:a"

        class Source(object):
            sha256, text_sha256 = "b", "b"
        ctx.final, ctx.source, ctx.no_record = Final(), Source(), True
        status, line, following, token = yomiyasu_check._decide(ctx, recorded=False)
        self.assertEqual((status, following), ("unrecorded", "report_unrecorded"))
        self.assertIn("meaning_risk=0", token)
        self.assertIn("規則に当たる候補はありませんが、原文にない人や担当を足した文が1件あります。その節を原文と資料と依頼に照らし、",
                      line)


class SpeedTest(unittest.TestCase):
    def test_many_changed_paragraphs(self):
        old = "\n\n".join("項目{}の設定を変更したら再起動し、結果を知らせる。".format(i) for i in range(1500)) + "\n"
        new = "\n\n".join("管理者は項目{}の設定を変更したら再起動し、結果を運用担当者に知らせる。".format(i)
                          for i in range(1500)) + "\n"
        full, sides = yomiyasu_diff._build_full_diff(old, new, None)
        groups = yomiyasu_diff._sentence_pairs(sides, full)
        clock = timing_clock()
        started = clock()
        items = yomiyasu_diff._added_actors(sides, groups)
        elapsed = clock() - started
        self.assertEqual(len(items), 1500)
        limit, detail = paced_limit(1.0, elapsed)
        self.assertLess(elapsed, limit, detail)

    def test_rewritten_block_without_pairs(self):
        # 1つの塊を全面に書き換え、文がどれも組にならないとき。元の文は、位置から見込んだ近くの文だけと比べる
        # （塊の元の文すべてと比べると、文の数の2乗で伸びる）
        old = "\n".join("項目{}の値を確かめる。".format(i) for i in range(2000)) + "\n"
        new = "\n".join("管理者は手順{}で別の処理を走らせてから結果を残す。".format(i) for i in range(2000)) + "\n"
        full, sides = yomiyasu_diff._build_full_diff(old, new, None)
        groups = yomiyasu_diff._sentence_pairs(sides, full)
        clock = timing_clock()
        started = clock()
        items = yomiyasu_diff._added_actors(sides, groups)
        elapsed = clock() - started
        self.assertEqual(len(items), 2000)
        limit, detail = paced_limit(1.0, elapsed)
        self.assertLess(elapsed, limit, detail)

    def test_many_distinct_names(self):
        # 文ごとに別の人名を足した長い文書。語ごとに原文の全体を探し直すと、語の数と原文の長さの積で伸びる
        # （6,000文で、探し直す形は2秒ほどかかった）
        kanji = "田中山川林森石井上下木村本松竹梅野原小大高橋佐藤伊加鈴吉岡島"

        def name(i):
            return kanji[i % 30] + kanji[(i // 30) % 30] + kanji[(i // 900) % 30]
        old = "\n\n".join("項目{}の設定を確かめて、結果を残す。".format(i) for i in range(6000)) + "\n"
        new = "\n\n".join("{}さんは項目{}の設定を確かめて、結果を残す。".format(name(i), i) for i in range(6000)) + "\n"
        full, sides = yomiyasu_diff._build_full_diff(old, new, None)
        groups = yomiyasu_diff._sentence_pairs(sides, full)
        clock = timing_clock()
        started = clock()
        items = yomiyasu_diff._added_actors(sides, groups)
        elapsed = clock() - started
        self.assertEqual(len(items), 6000)
        self.assertEqual(items[1]["actors"][0]["word"], name(1) + "さん")
        limit, detail = paced_limit(1.0, elapsed)
        self.assertLess(elapsed, limit, detail)

    def test_long_source_lookup_matches_plain_search(self):
        # 長い原文で使う位置の表の探し方は、文字列をそのまま探したときと同じ答えになる
        text = "".join("営業{}部の担当者が見積もりを出す。".format(i) for i in range(3000))
        source = yomiyasu_diff._ActorSource([text])
        self.assertGreaterEqual(len(source.text), yomiyasu_diff._ACTOR_INDEX_MIN)
        for piece in ("営業12部", "営業2999部の担当者", "担当者が", "見積もり", "営業3000部", "部の担当者", "の担当", "担", "",
                      "出す。営業", "総務部"):
            with self.subTest(piece=piece):
                self.assertEqual(source.contains(piece), piece in source.text)
                self.assertEqual(source.contains(piece), piece in source.text)


if __name__ == "__main__":
    unittest.main()
