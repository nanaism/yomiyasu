"""v2.2.1: 直訳語（calque）の型2の「入口」「出口」の拾い方を確かめる。

- 技術の文書（_CALQUE_TECH の語が5種類以上）では、同じ文に技術の語がなくても、要求や接続を集めたり通したりする形の
  「入口」「出口」（この入口を通ります、ひとつの入口に集めています）に印をつける。
- 技術の文書でも、実物の場所の入口と出口（サーバールーム、データセンター、北側の出口、倉庫）には印をつけない。
- 技術の文書でないときは、今までどおり同じ文に技術の語があるときだけ拾う。

文はすべて合成の文。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_lint  # noqa: E402

TECH = ("この資料は、社内の API とデータベースの運用をまとめたものです。認証にはトークンを使い、エラーはログに残します。"
        "設定は JSON のファイルに書き、URL は社内の画面から確かめます。\n\n")
PLAIN = "来週の展示会の案内です。受付は朝9時からです。\n\n"


def calque_on_line(text, line):
    return any(f["rule"] == "calque" and f["line"] == line for f in yomiyasu_lint.lint_text(text)["findings"])


class EntryInTechnicalDocumentTest(unittest.TestCase):
    def test_flow_forms_are_marked_without_a_technical_word_in_the_sentence(self):
        for sentence in ("外部から届く要求は、ひとつの入口に集めています。", "チャットからの要求は、どれもこの入口を通ります。",
                         "入口の前では、送り手が登録済みかを確かめます。", "すべての通知は、この入口に届きます。"):
            with self.subTest(sentence=sentence):
                self.assertTrue(calque_on_line(TECH + sentence + "\n", 3))

    def test_physical_places_are_not_marked(self):
        for sentence in ("来場者は、正面の入口を通って会場に入ります。", "サーバールームの入口を通るときは、入館証をかざします。",
                         "データセンターの入口を通るときは、受付で名前を書きます。", "北側の出口を通って、駐車場へ出てください。",
                         "荷物は、倉庫の入口に届きます。", "オフィスの入口の前で待ち合わせます。", "会議室の入口の前に、案内の紙を貼ります。",
                         "1階のロビーの入口で受け付けます。", "工場の出口を通るときは、手袋を外します。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(TECH + sentence + "\n", 3))

    def test_non_technical_documents_keep_the_sentence_rule(self):
        self.assertFalse(calque_on_line(PLAIN + "来場者は、この入口を通って会場に入ります。\n", 3))
        self.assertFalse(calque_on_line(PLAIN + "質問は、ひとつの入口に集めています。\n", 3))

    def test_message_names_the_entry(self):
        found = [f for f in yomiyasu_lint.lint_text(TECH + "外部から届く要求は、ひとつの入口に集めています。\n")["findings"]
                 if f["rule"] == "calque"]
        self.assertEqual(len(found), 1)
        self.assertIn("当たった言い方: 入口", found[0]["message"])
        self.assertEqual(found[0]["severity"], "info")


if __name__ == "__main__":
    unittest.main()
