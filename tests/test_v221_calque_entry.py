"""v2.2.1: 直訳語（calque）の型2の「入口」「出口」の拾い方を確かめる。

- 技術の文書（_CALQUE_TECH の語のうち、案内や行事の文書にも出る語を除いた語が5種類以上）では、同じ文に技術の語がなくても、
  同じ文の要求や呼び出しを集めたり通したりする形の「入口」「出口」（要求は、どれもこの入口を通ります）に印をつける。
- 技術の文書でも、実物の場所の入口と出口（サーバールーム、駐車場の出口、学校の入口の前、宅配便が届く入口、駅からのアクセス）には
  印をつけない。同じ文に技術の語がある入口と出口（サーバー側の入口、チャットルームの入口）は、2.2.0 のとおり拾う。
- 技術の文書でないとき（画面、通知、フォームのような語だけが並ぶ行事の案内を含む）は、今までどおり同じ文に技術の語があるときだけ拾う。
- 「全〇〇に響く」（全運転手に響きます、全店舗に響く可能性があります）は、技術の文書の、機械やシステムの語がある文だけで拾う。
  音や言葉の名詞が続く形（全社員に響く言葉、全館に響く爆音で）、全館に響き渡る音、すぐ前の主語が音や言葉の文（警報が全フロアに
  響く、社長の言葉は、全社員に響いた）、全身に響く、心に響くは外す。前からある語の一覧の形（全クライアントに響く）は、技術の文書で
  なくても拾う。

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
                         "要求の入口の前では、送り手が登録済みかを確かめます。", "すべての通知は、この入口に届きます。",
                         "要求は、どれもこの入口に通します。", "外からの要求は、ひとつの入口にまとめています。"):
            with self.subTest(sentence=sentence):
                self.assertTrue(calque_on_line(TECH + sentence + "\n", 3))

    def test_physical_places_are_not_marked(self):
        for sentence in ("来場者は、正面の入口を通って会場に入ります。", "サーバールームの入口を通るときは、入館証をかざします。",
                         "データセンターの入口を通るときは、受付で名前を書きます。", "北側の出口を通って、駐車場へ出てください。",
                         "荷物は、倉庫の入口に届きます。", "オフィスの入口の前で待ち合わせます。", "会議室の入口の前に、案内の紙を貼ります。",
                         "1階のロビーの入口で受け付けます。", "工場の出口を通るときは、手袋を外します。",
                         "駐車場の出口を通るときは、精算機で払います。", "学校の入口の前で待ちます。", "宅配便は入口に届きます。",
                         "停電のときは、非常用の出口を通って外に出ます。", "地震のときは、建物の外に出て、入口の前に集まります。",
                         "入口から入ってすぐ右が受付です。", "社屋の入口を通るときは、社員証をかざします。",
                         "データセンターの入口の前に集まります。", "サーバー室の入口で、入館証をかざします。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(TECH + sentence + "\n", 3))

    def test_people_waiting_at_physical_entries_are_not_marked(self):
        for sentence in ("スタッフの呼び出しがあるまで、入口の前でお待ちください。", "要求があれば、マンションの入口に届けます。",
                         "保護者の呼び出しがあったら、幼稚園の入口の前で待ってください。", "組合の要求を受けて、通路の出口を通る人を数えます。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(TECH + sentence + "\n", 3))

    def test_access_to_physical_places_is_not_marked(self):
        for sentence in ("駅からのアクセスは、東口の入口を通るのが便利です。", "ビルへのアクセスは、裏手の入口を通ります。",
                         "夜間のアクセスは、職員用の出口を通ります。", "来訪者のアクセスは、すべてこの入口を通ります。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(TECH + sentence + "\n", 3))

    def test_entries_marked_in_v220_are_kept(self):
        # 同じ文に技術の語がある入口と出口は、前の語が「〜側」「〜場」でも、2.2.0 のとおり拾う
        for sentence in ("クライアント側の出口で、レスポンスを圧縮します。", "サーバー側の入口で、トークンを確かめます。",
                         "API への要求は、サーバー側の入口を通ります。", "要求は、データの置き場の入口を通ります。",
                         "チャットルームの入口で、トークンを確かめます。", "通知センターの入口で、イベントを受けます。",
                         "オンライン店舗の入口で、認証します。", "APIの裏側の入口で、トークンを確かめます。"):
            with self.subTest(sentence=sentence):
                self.assertTrue(calque_on_line(PLAIN + sentence + "\n", 3))

    def test_event_notice_with_general_words_is_not_technical(self):
        text = ("# 秋の社内イベントのご案内\n\n参加の申し込みは社内サイトのフォームから受け付けます。\n\n"
                "受付では、申し込み後に届くメッセージの画面を見せてください。\n\n当日の通知はチャンネルに流します。\n\n"
                "来場者は、この入口を通って2階へ上がってください。\n\n避難のときは、出口を通って駐車場に集まります。\n\n"
                "社長のあいさつは、全社員に響きます。\n")
        self.assertFalse(yomiyasu_lint._v220_doc_tech(text))
        self.assertEqual([f for f in yomiyasu_lint.lint_text(text)["findings"] if f["rule"] == "calque"], [])

    def test_office_procedure_is_not_technical(self):
        text = ("# 経費精算の手順\n\n経費のデータは、会社のシステムに入れてください。ファイルの名前は日付にします。"
                "エラーが出たら、処理を止めて総務に連絡してください。\n\n番号の呼び出しは、待合の入口の前で行います。\n")
        self.assertFalse(yomiyasu_lint._v220_doc_tech(text))
        self.assertFalse(calque_on_line(text, 5))

    def test_non_technical_documents_keep_the_sentence_rule(self):
        self.assertFalse(calque_on_line(PLAIN + "来場者は、この入口を通って会場に入ります。\n", 3))
        self.assertFalse(calque_on_line(PLAIN + "質問は、ひとつの入口に集めています。\n", 3))

    def test_message_names_the_entry(self):
        found = [f for f in yomiyasu_lint.lint_text(TECH + "外部から届く要求は、ひとつの入口に集めています。\n")["findings"]
                 if f["rule"] == "calque"]
        self.assertEqual(len(found), 1)
        self.assertIn("当たった言い方: 入口", found[0]["message"])
        self.assertEqual(found[0]["severity"], "info")


class AllGroupHibikuTest(unittest.TestCase):
    def test_all_group_form_in_technical_documents(self):
        for sentence in ("管理画面が全車両の位置を毎秒読み直すと、全運転手に響きます。", "バッチを日中に回すと、全店舗に響きます。",
                         "この処理の遅れは全社員にまで響きます。"):
            with self.subTest(sentence=sentence):
                self.assertTrue(calque_on_line(TECH + sentence + "\n", 3))

    def test_all_group_form_before_formal_nouns_and_with_other_subjects(self):
        for sentence in ("この処理の遅れは全店舗に響く可能性があります。", "この処理の遅れは全店舗に響く恐れがあります。",
                         "全店舗に響くシステムの変更なので、夜に入れます。", "思いがけない処理の遅れが全店舗に響きます。",
                         "アラームが鳴らないと、復旧の処理の遅れが全店舗に響きます。"):
            with self.subTest(sentence=sentence):
                self.assertTrue(calque_on_line(TECH + sentence + "\n", 3))

    def test_cost_and_non_prefix_forms_keep_v220_behaviour(self):
        # 「全費用に響く」は 2.2.0 の費用の除外のとおり。安全、健全の「全」と、全然、全く、全体として は「全〇〇」にしない
        for prefix in (PLAIN, TECH):
            for sentence in ("円安が全費用に響きます。", "値上げは全料金に響きます。"):
                with self.subTest(sentence=sentence):
                    self.assertFalse(calque_on_line(prefix + sentence + "\n", 3))
        for sentence in ("APIの鍵の扱いは安全性に響きます。", "トークンの管理の甘さは、健全性に響きます。",
                         "新しいAPIの説明会を開いたが、全然お客様に響かなかった。", "ログの話をしても、全く現場に響かなかった。",
                         "データの保全作業は全体として現場に響きます。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(TECH + sentence + "\n", 3))

    def test_all_group_form_needs_a_machine_word_in_the_sentence(self):
        # 機械やシステムの語がない文は、技術の文書でも拾わない（2.2.0 のほかの句と同じ）
        for sentence in ("この遅れは全店舗に響きます。", "社長の言葉は、きっと全社員に響きます。", "警報が鳴り、全フロアに響きます。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(TECH + sentence + "\n", 3))

    def test_literal_and_non_technical_uses_are_not_marked(self):
        for sentence in ("全館に響くチャイムで、休憩の時間を知らせます。", "彼のスピーチは、全員の心に響きました。",
                         "全館に響く放送で、避難の手順を伝えます。", "障害のときは、警報が全フロアに響きます。",
                         "全館に響き渡るアラームが鳴りました。", "全館に響きわたる大きな音。", "衝撃が全身に響きます。",
                         "全社員に響くメッセージを考えます。", "社長の言葉は、全社員に響きました。", "全館に響いた拍手が続きました。",
                         "全館に響く爆音で、サーバーが止まりました。", "障害のときは、全フロアに響く警報で知らせます。",
                         "サーバーのアラームが鳴り、全フロアに響きました。", "監視装置のブザーが大きく全館に響いた。",
                         "サーバーのファンが全フロアに響くほどうるさい。", "全員に響くように、APIの説明を短くしました。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(TECH + sentence + "\n", 3))
        for sentence in ("社長の言葉は、全社員に響きました。", "値上げは全家庭に響きます。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(calque_on_line(PLAIN + sentence + "\n", 3))

    def test_listed_form_is_kept_outside_technical_documents(self):
        self.assertTrue(calque_on_line(PLAIN + "この集計を毎分回すと、全クライアントに響きます。\n", 3))


if __name__ == "__main__":
    unittest.main()
