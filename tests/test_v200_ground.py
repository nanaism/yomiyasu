#!/usr/bin/env python3
"""v2.0.0: diff の extract_numbers() と ground()（資料との照合）の単体の試験（設計 2.5.2、2.10、3.3、10.3 C1・C2）。

ground() は yomiyasu_check.py がプロセスの中で呼ぶ。check の試験（test_v200_check.py の K21〜K23、例3）は CLI の出力を見るので、
ここでは関数の戻り値（照合の JSON の形）を見る。設計に書いていない細部（戻り値のキー、sources の index の数え方、
数値の値の書き方）は diff の詰めで勧めを決めて、ここではその勧めの形で固定した。
v1.1.2 と、v2.0.0 の diff の前半（2.5.2 と 3.3 はまだ作っていない）では、この試験はすべて失敗する。
文はすべてこのファイルで作った合成の文。
"""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import yomiyasu_diff  # noqa: E402


NUMBER_KEYS = {"text", "value", "unit", "start", "end"}
TOP_KEYS = ["format", "format_version", "tool_version", "mode", "sources", "items", "meaning_risks",
            "candidate_count", "meaning_risk_count", "not_judged"]
ITEM_KEYS = {"kind", "text", "value", "unit", "final_lines", "classification"}
RISK_KEYS = {"kind", "subkind", "old_line", "new_line", "old", "new", "detail", "basis"}
NOT_JUDGED = ["claims", "conditions", "assignees", "meaning_equivalence"]
# diff の詰め: 資料にあって最終稿にない数値を not_in_final として items の最後に入れる
CLASSIFICATIONS = {"in_original", "from_materials", "not_in_sources", "dropped_certainty", "not_in_final"}


class GroundCase(unittest.TestCase):
    def function(self, name):
        function = getattr(yomiyasu_diff, name, None)
        self.assertTrue(callable(function), "v2.0.0 の yomiyasu_diff は %s() を公開する（設計 2.10）" % name)
        return function

    def numbers(self, text):
        found = self.function("extract_numbers")(text)
        self.assertIsInstance(found, list)
        for item in found:
            self.assertEqual(set(item), NUMBER_KEYS, item)
            self.assertEqual(text[item["start"]:item["end"]], item["text"], "text は書かれた形（位置と合う）")
        return found

    def values(self, text):
        return [(item["value"], item["unit"]) for item in self.numbers(text)]

    def ground(self, final, materials, original=None):
        result = self.function("ground")(final, materials, original)
        self.assertEqual(list(result), TOP_KEYS)
        for item in result["items"]:
            self.assertEqual(set(item), ITEM_KEYS, item)
            self.assertIn(item["classification"], CLASSIFICATIONS)
        for risk in result["meaning_risks"]:
            self.assertEqual(set(risk), RISK_KEYS, risk)
        return result

    @staticmethod
    def item(result, kind, text):
        found = [item for item in result["items"] if (item["kind"], item["text"]) == (kind, text)]
        return found[0] if len(found) == 1 else found

    @staticmethod
    def classes(result, kind):
        return {item["text"]: item["classification"] for item in result["items"] if item["kind"] == kind}


class TestExtractNumbers(GroundCase):
    """2.5.2 の数値の取り出し方。値は (数, 単位)。数は3桁区切りを外した算用数字の文字列、単位がなければ空の文字列。"""

    def test_arabic_numbers_with_units(self):
        cases = (
            ("保存期間は3日です。", [("3", "日")]),
            ("割引は10%です。", [("10", "%")]),
            ("公開日は2026年10月12日です。", [("2026", "年"), ("10", "月"), ("12", "日")]),
            ("返事の期限は3週間です。", [("3", "週間")]),
            ("待ち時間は2時間です。", [("2", "時間")]),
            ("容量は3.5GB、応答は100msです。", [("3.5", "GB"), ("100", "ms")]),
            ("上限を3にする。", [("3", "")]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.values(text), expected)

    def test_notation_is_normalized(self):
        """全角と半角、3桁区切りは値をそろえる（表記だけの違いは候補にしない。指示書2.3）。text は書かれた形のまま。"""
        self.assertEqual(self.values("在庫は３日分です。"), [("3", "日")])
        self.assertEqual(self.numbers("在庫は３日分です。")[0]["text"], "３日")
        self.assertEqual(self.values("価格は1,000円です。"), [("1000", "円")])
        self.assertEqual(self.values("価格は１，０００円です。"), [("1000", "円")])
        self.assertEqual(self.values("割引は１０％です。"), [("10", "%")])

    def test_kanji_numbers_need_a_counter(self):
        cases = (
            ("再試行は一回です。", [("1", "回")]),
            ("会議は三日に開く。", [("3", "日")]),
            ("参加者は十二人です。", [("12", "人")]),
            ("申し込みは二十件です。", [("20", "件")]),
            ("費用は百二十円です。", [("120", "円")]),
            ("費用は三千円です。", [("3000", "円")]),
            ("最大三回まで試す。", [("3", "回")]),
            ("後二週間で終わる。", [("2", "週間")]),
            ("第三回の会議です。", [("3", "回")]),
            # diff の詰めで助数詞に「つ」「か所」「種類」「章」「節」「項」「月」を足した（前は []）
            ("三つの案がある。", [("3", "つ")]),
            ("統一回線を使う。", []),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.values(text), expected)

    def test_excluded_words(self):
        """2.5.2 の除く語（一度、一部、一時、十分、一日中、一人ひとり など）は数値にしない。"""
        for text in ("設定を一度確認する。", "一部の画面で使う。", "一時的に止める。", "時間は十分ある。",
                     "一日中動かす。", "一人ひとりに配る。", "一般の利用者に開く。", "万一に備える。"):
            with self.subTest(text=text):
                self.assertEqual(self.values(text), [])

    def test_protected_spans_are_masked(self):
        """コード、インラインのコード、URL、リンク先、先頭の設定、HTML の中の数は取らない。引用と表の中の数は取る。"""
        cases = (
            ("`retry 3` を実行する。", []),
            ("詳しくは https://example.com/v3 を見る。", []),
            ("[手順](https://example.com/3) を読む。", []),
            ("手順です。\n\n```sh\nretry --count 3\n```\n", []),
            ("---\ntitle: 3日\n---\n本文です。\n", []),
            ("> 期限は3日です。\n", [("3", "日")]),
            ("| 保存 | 3日 |\n|---|---|\n| 期間 | 5日 |\n", [("3", "日"), ("5", "日")]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.values(text), expected)

    def test_names_and_lists_are_not_numbers(self):
        """英字に続く数（v2、IPv6、1.2.3 の途中）と、番号つき箇条書きの番号は取らない。
        英字が続く数（3D、5G）は、数として取る（反証レビュー F1。名前とみなして落とすと、30s や 8GiB のような単位つきの値の
        変化を見逃す）。diff の詰めで、続く英字（5字まで）を単位として取るようにした（前は単位なし）。
        3桁区切りでないカンマは数の区切り（単位は最後の数に付く）。月の数え方の表記の違いは単位をそろえる。"""
        cases = (
            ("v2 と IPv6 を使う。", []),
            ("3D と 5G を使う。", [("3", "D"), ("5", "G")]),
            ("版は v1.2 です。", []),
            ("1. 設定を開く。\n2. 値を3回変える。\n", [("3", "回")]),
            ("手順1,2,3日を見る。", [("1", ""), ("2", ""), ("3", "日")]),
            ("期間は3か月、3ヶ月、3カ月、3ヵ月です。", [("3", "か月")] * 4),
            ("版は1.2.3です。", [("1.2.3", "")]),
            # 「一時」は除く語だが、「一時間」は数値（1時間）
            ("一時間待つ。", [("1", "時間")]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.values(text), expected)

    def test_numbers_followed_by_letters(self):
        """反証レビュー F1: 一覧にない英字の単位が続く数も取る（2.5.2）。一覧の単位（ms、GB）は付ける。
        diff の詰めで、続く英字の並び（5字まで）を単位として取るようにした（前は単位なしで、
        30s → 30min のような単位だけの変化を拾えなかった）。コーパスとハーネスで前後の件数を測った。"""
        cases = (
            ("タイムアウトは30sです。", [("30", "s")]),
            ("メモリは8GiBです。", [("8", "GiB")]),
            ("回線は100Mbpsです。", [("100", "Mbps")]),
            ("同時接続は10kまでです。", [("10", "k")]),
            ("応答は100msで、容量は16GBです。", [("100", "ms"), ("16", "GB")]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.values(text), expected)

    def test_numbers_after_commas_and_periods(self):
        """反証レビュー F2・risk 1: 「，」「．」「,」「.」の直後の数も取る（2.5.2 の正規表現に直前の字の条件はない）。
        1.2.3 や v1.2 の途中の数は、直前が「数字と区切り」か英字なので取らない。"""
        cases = (
            ("候補日は3日，5日，7日です。", [("3", "日"), ("5", "日"), ("7", "日")]),
            ("候補日は3日,5日,7日です。", [("3", "日"), ("5", "日"), ("7", "日")]),
            ("参加者は，30人だった．", [("30", "人")]),
            # diff の詰めで算用数字の単位に「つ」を足した（前は ("2", "")）
            ("手順は2つ．3日で終える．", [("2", "つ"), ("3", "日")]),
            ("対象はA,3社だった。", [("3", "社")]),
            ("版は1.2.3です。", [("1.2.3", "")]),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.values(text), expected)

    def test_emphasis_between_number_and_unit(self):
        """反証レビュー F3: 数と単位の間の強調の記号（**）は読み飛ばして単位を付ける。太字を外すだけの直し
        （yomiyasu のよくある直し）で値が変わらないようにする。text は書かれた形のまま。"""
        self.assertEqual(self.values("保存期間は**3**日です。"), [("3", "日")])
        self.assertEqual(self.values("割引は**30**%です。"), [("30", "%")])
        self.assertEqual(self.values("保存期間は3**日**です。"), [("3", "日")])
        self.assertEqual(self.numbers("保存期間は**3**日です。")[0]["text"], "3**日")

    def test_bare_url_followed_by_japanese(self):
        """反証レビュー F4: 空白なしで日本語が続く URL の、URL の外の数は取る（URL として伏せるのは ASCII の字の並びだけ）。"""
        self.assertEqual(self.values("手順はhttps://example.com/guideにあり、保存期間は3日です。"), [("3", "日")])
        self.assertEqual(self.values("手順はhttps://example.com/v3にあり、期限はない。"), [])

    def test_positions_and_order(self):
        text = "Aは3日、Bは5日です。\n参加者は8名です。\n"
        found = self.numbers(text)
        self.assertEqual([item["text"] for item in found], ["3日", "5日", "8名"])
        self.assertEqual([item["start"] for item in found], sorted(item["start"] for item in found))


class TestGroundCompose(GroundCase):
    """3.3 の新規作成（original なし）。"""

    def test_shape_and_versions(self):
        result = self.ground("再試行は最大5回です。\n", ["最大5回まで再試行する。\n"])
        self.assertEqual(result["format"], "yomiyasu-materials")
        self.assertEqual(result["format_version"], yomiyasu_diff.MATERIALS_FORMAT_VERSION)
        self.assertEqual(result["format_version"], 1)
        self.assertEqual(result["tool_version"], yomiyasu_diff.__version__)
        self.assertEqual(result["mode"], "compose")
        self.assertEqual(result["not_judged"], NOT_JUDGED)
        # 10.3 C1: sources[].role は "source" と "material"。新規作成では資料だけ。index は役割ごとに1から
        self.assertEqual(result["sources"], [{"role": "material", "index": 1, "chars": len("最大5回まで再試行する。\n")}])
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(result["meaning_risk_count"], 0)

    def test_k21_number_not_in_materials(self):
        """K21: 資料にない数値は unsupported/number（10.3 C2 の detail）。new_line は最終稿の行、new はその文。"""
        result = self.ground("再試行は最大3回です。\n", ["最大5回まで再試行する。\n"])
        self.assertEqual(self.item(result, "number", "3回")["classification"], "not_in_sources")
        self.assertEqual(self.item(result, "number", "3回")["final_lines"], [1])
        [risk] = result["meaning_risks"]
        self.assertEqual((risk["kind"], risk["subkind"]), ("unsupported", "number"))
        self.assertEqual(risk["detail"], {"text": "3回", "value": "3", "unit": "回"})
        self.assertEqual((risk["old_line"], risk["new_line"], risk["old"], risk["new"]), (None, 1, None, "再試行は最大3回です。"))
        self.assertIsNone(risk["basis"])
        self.assertEqual(result["meaning_risk_count"], 1)
        self.assertGreaterEqual(result["candidate_count"], 1)

    def test_k21_number_found_in_materials(self):
        result = self.ground("再試行は最大5回です。\n", ["最大5回まで再試行する。\n"])
        self.assertEqual(self.item(result, "number", "5回")["classification"], "from_materials")
        self.assertEqual(result["meaning_risks"], [])

    def test_example_3(self):
        """3.5 の例3: 資料にない数値（後4行目の3回）、資料にない語（自動）、資料にあって最終稿にない確度の語（未確認）。
        資料にあって最終稿にない数値（14日、10件）は候補にしない。「一度」は数値にしない。"""
        materials = ["接続の再試行は未確認です。ログは14日残す。\n", "一度に送るのは最大10件です。\n"]
        final = "接続の再試行について書く。\n\n再試行は自動で行う。\n再試行は最大3回です。\n"
        result = self.ground(final, materials)
        self.assertEqual([(risk["kind"], risk["subkind"], risk["new_line"], risk["detail"]["text"]) for risk in result["meaning_risks"]],
                         [("unsupported", "number", 4, "3回")])
        self.assertEqual(self.classes(result, "word"), {"接続": "from_materials", "再試行": "from_materials",
                                                        "自動": "not_in_sources", "最大": "from_materials"})
        self.assertEqual(self.item(result, "certainty", "未確認")["classification"], "dropped_certainty")
        self.assertEqual(self.item(result, "certainty", "未確認")["final_lines"], [])
        self.assertEqual([item["text"] for item in result["items"]
                          if item["kind"] == "number" and item["classification"] != "not_in_final"], ["3回"])
        # diff の詰め: 資料にあって最終稿にない数値は、資料で出てくる順に not_in_final として items の最後に入る
        # （参考。候補には数えない）。check の「参考: 資料にあって最終稿にない数値」の行はこれから作る
        self.assertEqual([(item["text"], item["final_lines"]) for item in result["items"]
                          if item["classification"] == "not_in_final"], [("14日", []), ("10件", [])])
        self.assertEqual(result["items"][-2:], [item for item in result["items"] if item["classification"] == "not_in_final"])
        self.assertEqual(self.item(result, "word", "再試行")["final_lines"], [1, 3, 4])
        self.assertEqual([source["index"] for source in result["sources"]], [1, 2])
        # 見直し候補の数え方（3.5 の照合の節の行。「参考」は数えない）: 意味が変わる恐れ1、資料にない語の行1、確度の語の行1
        self.assertEqual(result["candidate_count"], 3)

    def test_url_scheme_and_markup_are_not_names(self):
        """URL の頭（https://）は名前にせず、残りを1つの名前として照らす。HTML のタグと先頭の設定は名前と語にしない。"""
        result = self.ground("手順は https://example.com/guide にある。<span>注意</span>\n",
                             ["手順は https://example.com/guide にある。\n"])
        self.assertEqual(self.classes(result, "name"), {"example.com/guide": "from_materials"})
        self.assertEqual(result["meaning_risks"], [])

    def test_names(self):
        """名前（英数字2字以上）が資料にないときは unsupported/name（10.3 C2 の detail は {"text": 名前}）。
        資料にあるかは NFKC にして空白を除いた文字列の部分文字列かで見る。"""
        result = self.ground("移行先はPostgreSQLとNode.jsです。\n", ["移行先は Postgre SQL にする。\n"])
        self.assertEqual(self.classes(result, "name"), {"PostgreSQL": "from_materials", "Node.js": "not_in_sources"})
        self.assertEqual([(risk["subkind"], risk["detail"]) for risk in result["meaning_risks"]],
                         [("name", {"text": "Node.js"})])
        result = self.ground("移行先はPostgreSQLです。\n", ["移行先はＰｏｓｔｇｒｅＳＱＬです。\n"])
        self.assertEqual(self.classes(result, "name"), {"PostgreSQL": "from_materials"})
        self.assertEqual(result["meaning_risks"], [])

    def test_numbers_compare_values_not_notation(self):
        result = self.ground("費用は1000円です。\n", ["費用は１，０００円です。\n"])
        self.assertEqual(self.item(result, "number", "1000円")["classification"], "from_materials")
        self.assertEqual(result["meaning_risks"], [])

    def test_notation_in_materials_is_not_a_new_value(self):
        """反証レビュー F3・risk 1: 資料の太字や「，」の書き方が違うだけの値と語は、資料にあるとみなす。"""
        result = self.ground("保存期間は3日です。\n", ["保存期間は**3**日です。\n"])
        self.assertEqual(self.item(result, "number", "3日")["classification"], "from_materials")
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(yomiyasu_diff.fail_on_count(result["meaning_risks"]), 0)
        result = self.ground("本番環境で動かす。\n", ["**本番**環境で動かす。\n"])
        self.assertEqual(self.item(result, "word", "本番環境")["classification"], "from_materials")
        self.assertEqual(result["candidate_count"], 0)
        result = self.ground("保存期間は3日です。\n", ["保存期間は，3日とする．\n"])
        self.assertEqual(self.item(result, "number", "3日")["classification"], "from_materials")
        self.assertEqual(result["meaning_risks"], [])

    def test_certainty_words_in_the_final(self):
        result = self.ground("公開は来月の予定です。\n", ["公開は来月の予定です。\n"])
        self.assertEqual(self.item(result, "certainty", "予定")["classification"], "from_materials")
        result = self.ground("公開は確定です。\n", ["公開は検討中です。\n"])
        self.assertEqual(self.item(result, "certainty", "確定")["classification"], "not_in_sources")
        self.assertEqual(self.item(result, "certainty", "検討中")["classification"], "dropped_certainty")
        self.assertEqual(result["meaning_risks"], [], "確度の語と語は見直し候補の1行だけで、意味が変わる恐れに入れない（0.2の5）")


class TestGroundRewrite(GroundCase):
    """3.3 の推敲（original あり）。数値は diff の候補の basis で扱うので、照合の意味が変わる恐れには入れない。"""

    def test_sources_and_mode(self):
        result = self.ground("保存期間は30日です。\n", ["保存期間は30日に変更した。\n"], "保存期間は3日です。\n")
        self.assertEqual(result["mode"], "rewrite")
        self.assertEqual(result["sources"], [{"role": "source", "index": 1, "chars": len("保存期間は3日です。\n")},
                                             {"role": "material", "index": 1, "chars": len("保存期間は30日に変更した。\n")}])

    def test_k22_number_from_materials_is_not_a_ground_risk(self):
        result = self.ground("保存期間は30日です。\n", ["保存期間は30日に変更した。\n"], "保存期間は3日です。\n")
        self.assertEqual(self.item(result, "number", "30日")["classification"], "from_materials")
        self.assertEqual(result["meaning_risks"], [])

    def test_number_not_in_sources_is_not_a_ground_risk(self):
        """推敲では、どこにもない数値も diff の数値の候補の basis を "none" にするだけで、二重に出さない（3.3 の表）。"""
        result = self.ground("保存期間は7日です。\n", ["保存期間は30日に変更した。\n"], "保存期間は3日です。\n")
        self.assertEqual(self.item(result, "number", "7日")["classification"], "not_in_sources")
        self.assertEqual(result["meaning_risks"], [])

    def test_rewrite_counts_the_supplement_line(self):
        """推敲では、原文になく資料にある項目（資料に基づく補足の候補）があれば、見直し候補を1行と数える。
        資料にない語は diff の「元の文にない語」と重なるので数えない。"""
        result = self.ground("保存期間は30日です。\n", ["保存期間は30日に変更した。\n"], "保存期間は3日です。\n")
        self.assertEqual(result["candidate_count"], 1)
        result = self.ground("保存期間は3日で自動削除です。\n", ["保存期間は3日です。\n"], "保存期間は3日です。\n")
        self.assertEqual(self.item(result, "word", "自動削除")["classification"], "not_in_sources")
        self.assertEqual(result["candidate_count"], 0)

    def test_in_original_comes_first(self):
        result = self.ground("会議は3回開く。PostgreSQLへ移す。\n", ["会議は3回開く。PostgreSQLへ移す。\n"],
                             "会議は3回開く。PostgreSQLへ移す。\n")
        self.assertEqual(self.item(result, "number", "3回")["classification"], "in_original")
        self.assertEqual(self.item(result, "name", "PostgreSQL")["classification"], "in_original")
        self.assertEqual(self.item(result, "word", "会議")["classification"], "in_original")
        self.assertEqual(result["meaning_risks"], [])
        self.assertEqual(result["candidate_count"], 0)

    def test_name_not_in_sources_is_a_risk_in_both_modes(self):
        result = self.ground("移行先はMySQLです。\n", ["移行先は未定です。\n"], "移行先は未定です。\n")
        self.assertEqual([(risk["kind"], risk["subkind"], risk["detail"]) for risk in result["meaning_risks"]],
                         [("unsupported", "name", {"text": "MySQL"})])
        self.assertEqual(self.item(result, "certainty", "未定")["classification"], "dropped_certainty")
        self.assertEqual(result["meaning_risk_count"], 1)


if __name__ == "__main__":
    unittest.main()
