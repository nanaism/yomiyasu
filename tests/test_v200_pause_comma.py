#!/usr/bin/env python3
"""短い主語・主題の読点: 合成例、公開例、出力と適用範囲の検証。"""
import io
import json
import statistics
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint as lint
import yomiyasu_check as check
from test_v200_lint_output import EXAMPLE1_INPUT, EXAMPLE2_INPUT, JSON_KEYS, FINDING_KEYS

TYPES = ("pr", "article", "incident", "proposal", "minutes", "manual", "slides", "essay", "formal", "mail", "paper")

REMOVE = [('回覧板は、木曜の朝に回します。', ['回覧板は']),
 ('新しい温室が、四月から苗を受け入れます。', ['新しい温室が']),
 ('この冊子では、植木の植え替えの手順をまとめます。', ['この冊子では']),
 ('応答は、JSON の形で返します。', ['応答は']),
 ('古いキャッシュが、重複して読み込まれる。', ['古いキャッシュが']),
 ('予備の端末にも、同じ設定を入れました。', ['予備の端末にも']),
 ('受付の窓口には、来月から一人増やします。', ['受付の窓口には']),
 ('来年からは、貸し出しを画面で受け付けます。', ['来年からは']),
 ('残りの3冊については、来週の棚に並べます。', ['残りの3冊については']),
 ('灯台の鍵も、事務所で預かります。', ['灯台の鍵も']),
 ('uv とは、Python のパッケージを管理する道具です。', ['uv とは']),
 ('平日は、9時に開きます。土日は、10時に開きます。', ['平日は', '土日は']),
 ('- 次の棚卸しは、6月の第1週に行います。', ['次の棚卸しは']),
 ('操作画面の『旗』は、まだオンにしません。', ['操作画面の『旗』は']),
 ('当店としては、年内に改装を終えたいと考えています。', ['当店としては']),
 ('今は、紙の帳簿で数えています。', ['今は']),
 ('朝の打ち合わせは、電話で行います。', ['朝の打ち合わせは'])]

KEEP = ['夜のうちに届いた荷物や手紙は、朝の便でまとめて配ります。',
 '最初に手をつけたのは、古い帳簿の整理でした。',
 '今回の改装で棚の高さをそろえたことが、いちばんの成果でした。',
 '窓を開けたまま出かけてよいかは、別に決めます。',
 '会議では、担当者が説明しました。',
 '残りの4脚は、塗料が乾いたら、月末までに運びます。',
 'この画面では、管理者が権限を変えられます。',
 '集合に遅れそうな場合は、電話で知らせてください。',
 'それでも開かないときは、窓口に電話してください。',
 '申請を出したあとは、画面で状況を確かめられます。',
 '設定を戻すには、管理画面の「初期化」を押します。',
 'では、次の手順に進みます。',
 'このたびは、遠いところをお越しいただきありがとうございました。',
 '具体的には、申請の画面を二つに分けます。',
 'それでも、毎回手で直すのは手間です。',
 '東京も、大阪も、朝から雨でした。',
 '平日と祝日は、このノートに書きます。',
 '前半は、受付の流れを、後半は、集計の方法を説明します。',
 '妹は、はじめての町で道に迷った。',
 '在庫はありますが、来週の出荷になります。',
 '多少遅れても、品質を優先します。',
 '誠に恐縮ですが、締め切りを1日延ばしていただけますか。',
 '「この案は、まだ早い」と言われた。',
 '僕は、それでもその町に残ることにした。',
 'それは、思っていたより小さな箱だった。',
 '隣の席の人は、黙って画面を見ていた。',
 '本記事では、設計の解像度を上げる方法を紹介します。',
 '重要なのは、テストを書くことです。',
 '「この棚、もう少し低くできませんか」が、言えなかった。',
 '……が、続けるうちに問題が見えてきた。',
 '準備はいいか、と聞かれた担当者は、黙っていた。']

# 見落としやすい形。名詞化した主語、並べの最後の項目、ひらがなの前の「と」、読点のない2つ目の「も」、
# かっこや半角カナを挟む節、常体の逆接、時の枠の語、時候の挨拶、かっこの中の主語。
# 拾う側は、語の頭の「と」、10字以下の問いの節、お客様、逆接の「が、」とかっこの中の助詞を並べに数えない所、
# 「を」を含む述語の句を並べの項目にしない所。
KEEP_REVIEW = ['本研究では、測定を続けることが欠かせない。',
 '細かい誤りよりも、笑われるのが怖かった。',
 '遅刻の回数、欠席の日数、提出物の数は、学期末にまとめて確かめる。',
 '壊れた椅子や机、汚れた床の広さは、来週の点検で数えます。',
 '大きさと形式は、受け取る側でも確かめます。',
 '誤字の直しも、図の追加もあった。',
 '先月返品になっていた【〇】冊は、担当と相談して戻します。',
 '先月注文したﾌﾟﾘﾝﾀｰは、明日届けます。',
 '急ぐが、間に合わない。',
 '頼むが、先に帰ってくれ。',
 'すまぬが、先に帰る。',
 '雨の降るあいだは、外に出ません。',
 '署名したのちには、控えを渡してください。',
 '薬を飲む直前には、水を用意してください。',
 '皆様には、ますますご健勝のこととお慶び申し上げます。',
 '連絡は、「当番表」の担当者がします。']
REMOVE_REVIEW = [('とりまとめは、明日届けます。', ['とりまとめは']),
 ('いつ始めるかは、来週決めます。', ['いつ始めるかは']),
 ('お客様には、メールでお知らせします。', ['お客様には']),
 ('名簿が、届きましたが、まだ開けていません。', ['名簿が']),
 ('返事は、後で『準備は、まだ』と送ります。', ['返事は']),
 ('新しい手順では、名簿を紙から画面に移し、印刷は必要なときだけにします。', ['新しい手順では'])]

MARKDOWN_KEEP = ['# 応答は、JSON で返す\n',
 '| 項目 | 説明 |\n|---|---|\n| 応答は、 | JSON で返す |\n',
 '> 応答は、JSON の形で返します。\n',
 '```\n応答は、JSON の形で返します。\n```\n',
 '設定は `x は、y` の形で書きます。\n']

# 本記事では（既存規則との重複）と長い並べ（15字超）は検出対象外。
PUBLIC = [('第二に、永続化の仕様変更や外部APIのバージョン更新が、ビジネスロジックの修正に直接波及します。', 26, False),
 ('文書は成果物ではなく、チームの記憶を維持する仕組みであるという認識が共有されたことが、最大の成果であったと考える。', 41, False),
 ('このサービス層では、DBアクセス、外部API呼び出し、ビジネスロジックが1つのメソッドに混在しています。', 8, False),
 ('モバイルとWebで画面ごとにデータ要件が異なる現状では、過剰取得と複数回のリクエストを減らせる。', 26, False),
 ('それでも、質問の行き先が一人に固定される状態は抜け出せたと思っている。', 3, False),
 ('この構造には、責務の分離の観点から三つの問題があります。', 5, False),
 ('現在は、新任メンバーが着任後二週間で単独のリリースを担当できるまでになっている。', 2, False),
 ('外部APIがタイムアウトしたときのリトライも、クライアント側に集約できます。', 21, False),
 ('最初は「全員が設計書を書く」というルールを敷いたが、三週間で誰も更新しなくなった。', 24, False),
 ('アプリケーションのコネクションプール上限は20に設定していましたが、一部のクエリにインデックスがなく、1件あたりの処理時間が長引きました。', 32, False),
 ('第二に、外部APIの仕様変更やDBスキーマの変更が、そのままサービス層の修正につながります。', 24, False),
 ('本記事では、uvの使い方をご紹介します。', 4, False),
 ('本サービス層では、DBアクセスと外部API呼び出しがビジネスロジックと同一のメソッド内に記述されています。', 7, False),
 ('具体的には、永続化をRepositoryに、外部API呼び出しをGatewayまたはClientに切り出してください。', 4, False),
 ('最初に取り組んだのは、文書を書く負担の軽減である。', 9, False),
 ('GraphQLは、クライアントが必要な項目を指定できるため通信量を抑えられる。', 7, False),
 ('決済まわりを書いた一人が休んだ週は、障害対応が丸二日止まった。', 16, False),
 ('ただ、文化が根づいたと感じたのは、レビューで「ここは理由を残してほしい」という指摘が自然に出るようになってからだ。', 15, False),
 ('もう一つ効いたのは、レビューで「これ、新人が読んで分かる？', 8, False),
 ('一度に全部を直すのが重い場合は、まず外部API呼び出しの切り出しから始めてください。', 14, False),
 ('一方、取得項目がエンドポイントごとに固定されるため、画面ごとにデータ要件が異なる場合は、過剰取得や複数回の通信が生じやすい。', 42, False),
 ('ただしモバイルのホーム画面だけは、複数APIを束ねる呼び出しが多く、通信回数が問題になっている。', 15, False),
 ('REST APIは、HTTP標準機能によるキャッシュ制御、認可設計、監視が容易である。', 8, False),
 ('GraphQLは、クライアントが必要なフィールドだけを指定して取得できる。', 7, False),
 ('また、外部APIの仕様変更やスキーマ変更が、業務ロジックの修正を伴う点も保守上の課題です。', 20, False),
 ('この構成では、業務ロジックの検証にDBや外部サービスの起動が必要となり、単体テストが困難です。', 5, False),
 ('このサービス層では、DBアクセス、外部API呼び出し、ビジネスルールの判断が1つのメソッドに混在しています。', 8, False),
 ('バックエンドが4人のチームでは、その保守を背負う余裕がない。', 14, False),
 ('画面要件の変動が大きい社内アプリケーションでは、GraphQLの柔軟性を評価できる。', 22, False),
 ('サービス層には、割引の適用条件や状態遷移といったビジネスルールの判断だけを残す', 6, True),
 ('画面ごとに異なるデータ取得の要望には、BFF層かフィールド指定パラメータで対応する。', 17, False),
 ('三つ目は、新しく入ったメンバーに最初の一週間でREADMEの誤りを直してもらうことだ。', 3, True),
 ('GraphQLは、クライアントが必要な項目だけを指定して取得できるため、モバイルアプリのようにデータ量を絞りたい画面でオーバーフェッチを減らせる。', 7, False),
 ('トランザクションの境界も、サービス層の1か所で管理できます。', 11, True),
 ('ドキュメントの更新を業務として評価対象に含めたことも、継続の支えとなった。', 25, False),
 ('今は動いていても、決済プロバイダを差し替えるときや割引ルールを変えるときに、全部このメソッドを触ることになります。', 7, False),
 ('GraphQLでは、クエリ単位のコスト制限やN+1対策を自前で作り込む必要がある。', 8, True),
 ('ただしパートナー向けAPIでは、HTTPキャッシュ、レート制限、OpenAPIによる仕様共有がそのまま使えるRESTのほうが運用しやすい。', 14, False),
 ('最初にやったのは、大きなドキュメントを書くことではない。', 7, False),
 ('READMEを直す習慣は、新人が遠慮なく質問するきっかけにもなった。', 11, False),
 ('また、外部APIの仕様変更やテーブル構造の変更が、そのままサービス層の修正につながります。', 23, False),
 ('本サービスクラスでは、業務ルールの判定、SQLの発行、外部APIの呼び出しが同一メソッド内に記述されています。', 9, False),
 ('【判断根拠】取引先への提供を伴う公開APIでは、互換性維持と運用統制を優先する。', 22, False),
 ('属人化の解消は、記録を書く行為を個人の善意に任せず、チームの手順として固定することで進んだと総括している。', 6, True),
 ('直接原因は、コネクションプールの最大接続数が想定ピーク負荷に対して不足していたことである。', 4, False),
 ('一つ目は、PRのテンプレートに「なぜこの実装にしたか」の記入欄を加えること。', 3, True)]

BASE_OUTPUT = '表現・書式の検査を実行しました。\n見直し候補: 0件\nこの検査では、意味の保持と読者にとっての分かりやすさは判定していません。\n'

MESSAGE = "短い主語や主題のすぐあとに読点があります（{phrases}）。間を作るだけの読点は、AIの文章らしく見えます。読点のあとに別の主語が来る、条件や場面の枠を示す、並べている、外すと語がつながったり掛かり先が変わったりする、のどれにも当たらなければ、読点だけを外してください（語順と述語は変えません）。小説や随筆で書き手が間として置いた読点は残してかまいません。"


def call(main, args, text=""):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), mock.patch.object(
            sys, "stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8")):
        try:
            code = main(args)
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


def pauses(text, **options):
    return [f for f in lint.lint_text(text, **options)["findings"] if f["rule"] == "pause_comma"]


def corpus():
    return sorted((ROOT / "tests" / "corpus").rglob("*.md"))


class PauseCommaTest(unittest.TestCase):
    def test_t1_remove(self):
        for text, phrases in REMOVE:
            with self.subTest(text=text):
                found = pauses(text, doc_type="article")
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], MESSAGE.format(
                    phrases="".join("「" + p + "、」" for p in phrases)))
                self.assertEqual(found[0]["snippet"], text.strip())

    def test_t1_keep(self):
        for text in KEEP:
            with self.subTest(text=text):
                self.assertEqual(pauses(text, doc_type="article"), [])

    def test_t1_review_examples(self):
        for text in KEEP_REVIEW:
            with self.subTest(text=text):
                self.assertEqual(pauses(text, doc_type="article"), [])
        for text, phrases in REMOVE_REVIEW:
            with self.subTest(text=text):
                found = pauses(text, doc_type="article")
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["message"], MESSAGE.format(
                    phrases="".join("「" + p + "、」" for p in phrases)))

    def test_t15_lines_of_one_paragraph_are_read_together(self):
        # 段落の中の改行をまたぐ文と引用は1つにつないで読み、当たりはその助詞のある行に出す。
        cases = [("この棚には、\n傷みの目立つ板が三枚あります。\n", []),
                 ("「作業を続けます。\n返事は、明日します。」と言われた。\n", []),
                 ("回覧板は、木曜の朝に\n回します。\n", [1]),
                 ("前の文です。\n回覧板は、木曜の朝に回します。\n", [2]),
                 ("この版は、読み\n込みが速い。\n", []),
                 # 短く名詞で終わる見出しのような行とは、つながない。
                 ("■お知らせ\n回覧板は、木曜の朝に回します。\n", [2]),
                 # 句点なしにかなで終わる段落は、文のあとが見えないので拾わない。名詞で終わる題名の行は拾う。
                 ("回覧板は、木曜の朝に回す\n", []),
                 ("新しい温室が、四月から開く理由\n", [1]),
                 # 箇条書きの項目は1つずつ読み、句点がなくても拾う。
                 ("- 回覧板は、木曜に回す\n- 返事は、JSON で返す\n", [1, 2]),
                 ("- 回覧板は、木曜の朝に\n  回します。\n", [1])]
        for text, lines in cases:
            with self.subTest(text=text):
                self.assertEqual([f["line"] for f in pauses(text, doc_type="article")], lines)

    def test_t2_public_positions(self):
        self.assertEqual(len(PUBLIC), 46)
        for text, pos, expected in PUBLIC:
            with self.subTest(text=text, pos=pos):
                self.assertEqual(pos in [hit[0] for hit in lint._pause_comma_hits(text)], expected)

    def test_t4_markdown_and_line_numbers(self):
        sentence = REMOVE[3][0]
        more = ["---\ntitle: " + sentence + "\n---\n",
                "<div>\n" + sentence + "\n</div>\n",
                "[ref]: https://example.com/ '" + sentence + "'\n",
                "[リンク](https://example.com/応答は、)\n",
                "https://example.com/応答は、\n"]
        for text in MARKDOWN_KEEP + more:
            with self.subTest(text=text):
                self.assertEqual(pauses(text, doc_type="article"), [])
        text = "---\ntitle: 点検\n---\n\n" + REMOVE[12][0]
        self.assertEqual([f["line"] for f in pauses(text, doc_type="article")], [5])
        for text in ("- [x] " + sentence, "**応答**は、JSON の形で返します。",
                     "[応答](https://example.com/)は、JSON の形で返します。"):
            self.assertEqual(len(pauses(text, doc_type="article")), 1, text)

    def test_t5_types_and_detection_gate(self):
        self.assertEqual(lint.DOC_TYPE_ONLY_RULES, {"pause_comma": TYPES})
        text = REMOVE[3][0]
        with mock.patch.object(lint, "_pause_comma_hits", side_effect=AssertionError("検出を呼ばない")):
            for options in ({}, {"doc_type": "promo"}, {"reader": "general"}):
                self.assertEqual(pauses(text, **options), [])
        for value in TYPES:
            result = lint.lint_text(text, doc_type=value)
            self.assertEqual(len([f for f in result["findings"] if f["rule"] == "pause_comma"]), 1)
            self.assertNotIn("pause_comma", result["context"]["skipped_by_doc_type"])
        # 表から外すだけで種類なしでも呼ばれる。規則名を固定した分岐にしない。
        with mock.patch.object(lint, "DOC_TYPE_ONLY_RULES", {}):
            self.assertEqual(len(pauses(text)), 1)

    def test_t6_untyped_corpus_and_fixtures(self):
        paths = corpus() + sorted((ROOT / "tests" / "fixtures").rglob("*.md"))
        texts = [p.read_text(encoding="utf-8") for p in paths]
        for name in ("bold_regressions.json", "rule9_examples.json"):
            fixtures = ROOT / "tests" / "fixtures" / name
            texts += [case["text"] for case in json.loads(fixtures.read_text(encoding="utf-8"))]
        fixtures = ROOT / "tests" / "fixtures" / "diff_v112_existing_keys.json"
        for case in json.loads(fixtures.read_text(encoding="utf-8"))["cases"]:
            texts.extend((case["orig"], case["rewrite"]))
        for text in texts:
            self.assertEqual(pauses(text), [])
        self.assertEqual(call(lint.main, ["-"], REMOVE[3][0] + "\n"), (0, BASE_OUTPUT, ""))

    def test_t7_severity_score_and_exit_codes(self):
        for count in (1, 2):
            text = "\n".join([REMOVE[3][0]] * count)
            result = lint.lint_text(text, doc_type="article")
            self.assertEqual([f["severity"] for f in result["findings"]], ["info"] * count)
            self.assertEqual(result["rule_penalty_score"], 100 - 2 * count)
            for flags in ([], ["--strict"], ["--fail-on=warn"], ["--fail-on=error"]):
                self.assertEqual(call(lint.main, ["-", "--doc-type", "article"] + flags, text)[0], 0)
        with tempfile.TemporaryDirectory() as tmp:
            source, final = Path(tmp) / "source.md", Path(tmp) / "final.md"
            source.write_text(REMOVE[3][0].replace("、", ""), encoding="utf-8")
            final.write_text(REMOVE[3][0], encoding="utf-8")
            code, out, err = call(check.main, ["run", "--source", str(source), "--final", str(final),
                                              "--state-dir", str(Path(tmp) / "state"),
                                              "--doc-type", "article", "--fail-on=warn"])
            self.assertEqual((code, err), (0, ""), out)
            self.assertIn("pause_comma", out)
            self.assertIn("下の候補を原文と資料に照らして確かめてください", out.splitlines()[0])

    def test_t8_output_shape(self):
        text = REMOVE[3][0]
        code, out, err = call(lint.main, ["-", "--doc-type", "article", "--json"], text)
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(list(result), JSON_KEYS)
        self.assertEqual(result["format_version"], 2)
        self.assertEqual(set(result["findings"][0]), FINDING_KEYS)
        code, out, err = call(lint.main, ["-", "--doc-type", "article"], text)
        self.assertTrue(any(line.startswith("L1 [INFO] pause_comma: ") for line in out.splitlines()))

    def test_t9_aggregation_and_sentence_boundaries(self):
        text = "".join(REMOVE[i][0] for i in (0, 1, 3, 4))
        found = pauses(text, doc_type="article")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["message"], MESSAGE.format(
            phrases="「回覧板は、」「新しい温室が、」「応答は、」ほか1か所"))
        text = REMOVE[0][0] + REMOVE[1][0] + "\n" + REMOVE[3][0] + REMOVE[4][0]
        self.assertEqual([f["line"] for f in pauses(text, doc_type="article")], [1, 2])
        for end in "。！？!?":
            text = REMOVE[3][0].replace("。", end) * 2
            self.assertEqual(len(lint._pause_comma_hits(text)), 2)
        self.assertEqual(lint._pause_comma_hits("「応答は、JSON。応答は、JSON」は、設定済みです。"), [])

    def test_t10_examples(self):
        for text in (EXAMPLE1_INPUT, EXAMPLE2_INPUT):
            self.assertEqual(pauses(text, doc_type="article"), [])

    def test_t11_other_findings_and_metrics(self):
        for path in corpus():
            text = path.read_text(encoding="utf-8")
            plain = lint.lint_text(text)
            for value in TYPES:
                with self.subTest(path=path, value=value):
                    result = lint.lint_text(text, doc_type=value)
                    partial = lint.DOC_TYPE_SKIP_PATTERNS.get(value, {})
                    expected = [f for f in plain["findings"]
                                if f["rule"] not in lint.DOC_TYPE_SKIP_RULES[value]
                                and not f["message"].startswith(partial.get(f["rule"], ()))]
                    self.assertEqual([f for f in result["findings"] if f["rule"] != "pause_comma"], expected)
                    self.assertEqual(result["metrics"], plain["metrics"])

    def test_t12_long_lines_and_documents(self):
        # 検出を無効にした同じ lint と比べる。絶対時間の小さな揺れは許す。
        for text in ("応答は、" * 5000, (REMOVE[3][0] + "\n") * 2000):
            def elapsed():
                start = time.perf_counter()
                lint.lint_text(text, doc_type="article")
                return time.perf_counter() - start
            with mock.patch.object(lint, "_pause_comma_hits", return_value=[]):
                baseline = statistics.median(elapsed() for _ in range(3))
            actual = statistics.median(elapsed() for _ in range(3))
            self.assertLess(actual, baseline * 5 + 0.2, (baseline, actual))
        # 同じ助詞の並べを数える走査も、句ごとに文全体を見直さない。
        self.assertEqual(lint._pause_comma_hits("応答は、" * 5000), [])

    def test_t13_copies_and_catalog(self):
        package = ROOT / "skills" / "yomiyasu"
        for name in ("scripts/yomiyasu_lint.py", "references/slop-catalog.md", "references/audience.md"):
            self.assertEqual((ROOT / name).read_bytes(), (package / name).read_bytes())
        self.assertIn("## 9. 間を作るだけの読点", (ROOT / "references/slop-catalog.md").read_text(encoding="utf-8"))

    def test_t14_help_is_table_driven(self):
        expected = "種類を指定したときだけ当てる規則: pause_comma（promo を除く11種類。種類を指定しないときは出しません）"
        self.assertIn(expected, call(lint.main, ["--help"])[1])
        with mock.patch.object(lint, "DOC_TYPE_ONLY_RULES", {"pause_comma": TYPES, "sample": ("article",)}):
            help_text = lint._doc_type_table()
            self.assertIn("sample（", help_text)
            self.assertIn("1種類。種類を指定しないときは出しません）", help_text)
        with mock.patch.object(lint, "DOC_TYPE_ONLY_RULES", {}):
            self.assertNotIn("種類を指定したときだけ当てる規則", lint._doc_type_table())


if __name__ == "__main__":
    unittest.main()
