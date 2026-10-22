"""v2.2.0 の担当 A1: calque（直訳語）、metaphor_label（見出しと1行目の比喩ラベル）、katakana_term（意味の薄いカタカナ語）、
thin_evaluation（中身の薄い評価の文）の規則と、2つの語の一覧（references/lists/katakana-terms.txt、thin-evaluation.txt）。

文はすべて自作の類例（v220-development/seed/ の g1-calque と g2-label-hedge の sentences.json、所有者の類例の1〜4、
この試験のために作った文）。利用者の投稿や記事、公開された表の文は入れない。
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import yomiyasu_lint  # noqa: E402

RULES = ("calque", "metaphor_label", "katakana_term", "thin_evaluation")
TAIL = "の候補です。文脈を見て、誰が何をどうするかを書き直すか確かめてください。"
TYPE_NAMES = {1: "型1: 機械やシステムが人の動作をする言い方",
              2: "型2: 実物の名前の代わりに場所のたとえを使う名詞",
              3: "型3: 英語の言い方を一語ずつ写した句"}


def new_findings(text, doc_type=None, keep_words=True):
    """lint_text の結果のうち、A1 の4つの規則の候補（keep_words なら内部の欄 _words も残す）。"""
    if keep_words:
        original = yomiyasu_lint._public_finding
        yomiyasu_lint._public_finding = lambda finding: dict(finding)
        try:
            result = yomiyasu_lint.lint_text(text, doc_type=doc_type)
        finally:
            yomiyasu_lint._public_finding = original
    else:
        result = yomiyasu_lint.lint_text(text, doc_type=doc_type)
    return [finding for finding in result["findings"] if finding["rule"] in RULES]


# 見出しの試験の文書に足す、漢字を含まない段落（metaphor_label は本文が60字以上ある文書だけを見る）
FILLER = "これは、みんなにくばる、ためしのぶんしょうです。よんでから、つぎのところへすすんでください。わからないところは、あとでききます。"


def rules_of(text, doc_type=None):
    return [finding["rule"] for finding in new_findings(text, doc_type)]


# 所有者の類例（指示書の「作業を始める前に」）のうち、この担当の規則に当たる4文。(文, 規則, _words)
OWNER_SEEDS = (
    ("取りこぼした通知は、翌朝の再送ジョブが拾います。", "calque", ("拾う",)),
    ("社外からの接続は、この入口を通ります。", "calque", ("入口",)),
    ("新しい鍵に替えると、古い鍵の失効が効きます。", "calque", ("失効が効く",)),
    ("プロジェクトのマイルストーンを決めます。", "katakana_term", ("マイルストーン",)),
)
# 所有者の類例のうち、ほかの担当の規則の4文（この担当の規則は当たらない）
OWNER_OTHERS = (
    "この結果は、品質の向上につながったと言えるでしょう。",
    "丁寧な、人。",
    "本当に大事なのは、続けられる仕組み。",
    "切るか、続けるか、決める。",
)

# seed/g1-calque の sentences.json。(型の番号, 文)。型の番号が None の文は辞書の訳語の名詞（要求、承認、事実、影響）。
# 直す文のうち「キャッシュの有効期限を短くしたことが、オリジンの負荷に響いています。」は、主語が出来事（短くしたこと）で
# 機械の語でないので型1に当たらない（報告に書いた見落とし）。ここには入れない
CALQUE_FIX = (
    (1, "このミドルウェアは、ログインしていない利用者のリクエストを手前で受け止めます。"),
    (1, "ワーカーは、キューに溜まったジョブを順番に引いていきます。"),
    (1, "Webhook の受信側が、同じイベントを二度食べないようにしています。"),
    (1, "この関数は、空の配列が来たときも黙って通します。"),
    (1, "古いクライアントが、新しいトークンの形式を飲み込めずに落ちています。"),
    (1, "ビルドは、環境変数の値をこのファイルから引いてきます。"),
    (1, "監視のエージェントは、配信サービスへの応答時間を見張っています。"),
    (1, "このワーカーは、起動したときに読んだ鍵をずっと抱えたまま動きます。"),
    (1, "取りこぼした通知は、翌朝の再送ジョブが拾います。"),
    (1, "集計バッチは、前日分の注文ログを毎朝6時に拾いにいきます。"),
    (1, "今のクエリは、削除済みのアカウントまで数に引き込んでいます。"),
    (1, "差分のチェックは、日付の列の書式の違いまでは拾いません。"),
    (1, "このフックは、コミットメッセージの書式の誤りを見張っています。"),
    (1, "検索のインデックスは、記事を公開してから数分で新しい内容を覚えます。"),
    (2, "## 注文データの受け口"),
    (2, "外部からの注文データは、すべてこの受け口に届きます。"),
    (2, "API の入口で、トークンの有効期限を確かめます。"),
    (2, "決済まわりの窓口は、このモジュールに集めています。"),
    (2, "キャッシュの手前に、もう一段の関所を置きます。"),
    (2, "社外からの接続は、この入口を通ります。"),
    (2, "外部向けの口は 443 番だけを開けています。"),
    (2, "障害時のトラフィックの逃がし先として、大阪リージョンを用意しています。"),
    (2, "問い合わせの口は、11月から社内ポータルのフォームに一本化します。"),
    (2, "申請の受け口は、総務部の共有メールアドレスです。"),
    (2, "申請書の受け口"),
    (2, "新しい社内ポータルのトップページが、入社したばかりの人の最初の玄関になります。"),
    (2, "データの合流地点になるのが、この中間テーブルです。"),
    (2, "集計が失敗したときのエラーの寄せ先は、#sales-batch チャンネルです。"),
    (2, "集計結果の着地先は、営業部の共有ドライブです。"),
    (2, "データの出口を CSV と API の二つに絞ります。"),
    (2, "管理画面の裏口として、社内ネットワークからだけ開くURLを用意しています。"),
    (2, "ログインの入口を一つにまとめるため、社内のアプリは来月から共通の認証画面を使います。"),
    (3, "作り直す前は、注文の一覧ページの読み込みが平均で2秒を取っていました。"),
    (3, "この分け方は、チームが二つに分かれた今なら意味をなします。"),
    (3, "リポジトリを分けたこと自体は、利用者にとっての針をほとんど動かしません。"),
    (3, "新しい鍵に替えると、古い鍵の失効が効きます。"),
    (3, "再発を防ぐため、次の三つのステップを取ります。"),
    (3, "この問題には、インフラチームが所有権を持ちます。"),
    (3, "この修正は、問い合わせの数に大きな違いを作りました。"),
    (3, "ご不明な点があれば、情報システム部に手を伸ばしてください。"),
    (3, "新しい申請画面は、本日正午にライブになりました。"),
    (3, "関係者全員が同じページの上にいられるよう、変更点を下の表にまとめました。"),
    (3, "集計のやり方の見直しは、まず水を試すところから始めます。"),
    (3, "新しい集計基盤への移行は、営業部の人にとって透明に行われます。"),
    (3, "新しい割引の条件は、来月の請求から効きます。"),
    (3, "次回の定例は、10月30日の15時に会議室Bで場所を取ります。"),
    (3, "最後に、先週の質問についてループを閉じておきます。"),
    (3, "この判断は、データに駆動されています。"),
    (1, "この体重計は、測った値をスマートフォンのアプリに投げます。"),
    (3, "今期の売上は、前年同期を12%上回る数字を配達しました。"),
)
CALQUE_KEEP = (
    (1, "すべてのテストが通ったら、レビューを依頼してください。"),
    (1, "2回目からはキャッシュが効くので、同じ一覧は50ミリ秒ほどで返ります。"),
    (1, "日付の列にインデックスを張ったので、期間で絞り込む検索にはインデックスが効きます。"),
    (1, "1つのジョブが1件の注文で、ワーカーは在庫を引き当ててから注文を確定します。"),
    (2, "このパッケージの依存先は、`package.json` の `dependencies` に書いてあります。"),
    (2, "決済サービスとメール配信サービスは、どちらもこのシステムの依存先です。"),
    (1, "ワーカーから配信サービスの API サーバーに ping が通ることも確かめています。"),
    (3, "再送の前に、`failed_notifications` テーブルのバックアップを取りました。"),
    (None, "この障害による影響は、確認メールが最大で53分遅れたことです。"),
    (None, "調査で分かった事実だけを書きます。"),
    (2, "問い合わせ先: 情報システム部（10月31日までは内線 1234）"),
    (None, "申請は、部長の承認を得てから経理部に回してください。"),
    (2, "紙の申請書は、これまでどおり本館1階の総務部の窓口に出してください。"),
    (None, "利用者からの要求が多い機能から順に、ポータルを直していきます。"),
    (1, "予算の申請が通ったので、12月から社用車を2台増やします。"),
    (1, "眠くなる薬が効いている間は、社用車を運転しないでください。"),
    (1, "雨の日はブレーキが効きにくくなるため、車間を広めに取ってください。"),
    (2, "本社ビルの正面入口は、工事のため11月末まで閉じています。"),
    (2, "地下鉄の駅の2番入口から地下通路を通ると、ビルの通用口に出られます。"),
    (1, "落とし物を拾った方は、1階の受付に届けてください。"),
    (3, "作業の前に、データベースのバックアップを取ってください。"),
    (3, "異常値の閾値は、過去3か月の統計を取ってから決めます。"),
    (1, "集計のクエリを流します。"),
    (2, "出力したファイルの保存先は、設定画面で変えられます。"),
    (3, "レビューの時間を30分取ってください。"),
    (2, "通知の送信先は、各チームのチャンネルです。"),
    (2, "手順の詳しい内容は、リンク先のページを見てください。"),
    (2, "このライブラリの依存先が古いままなので、先にそちらを更新します。"),
    (2, "外部の地図サービスが止まると、それを依存先にしている店舗検索も動かなくなります。"),
    (2, "申請書の提出先は、市役所2階の市民課の窓口です。"),
    (1, "彼女は駅の改札を通り、北口の階段を下りた。"),
)

KATAKANA_TERM_FIX = (
    "下期は、解約の問い合わせを減らすソリューションを用意します。",
    "顧客とのエンゲージメントを高めることも課題です。",
    "在宅勤務の机のためのライティングソリューションです。",
    "部署間のシナジーを生むことも狙いです。",
    "全社のナレッジを集めるプラットフォームにもしていきます。",
    "今回の切り替えは、紙の申請をなくす計画のマイルストーンです。",
    "新しい決まりには、皆さんのコミットメントが欠かせません。",
    "注文の受け付けを再開する前に、関係者とのアライメントを取ります。",
    "全社員がこのイニシアチブに参加することを期待しています。",
    "新サービスは、顧客に新しいバリューを届けます。",
    "店舗と通販のデータを統合するスキームを検討しています。",
    "集計の結果から、いくつかのインサイトが得られました。",
)
KATAKANA_TERM_KEEP = (
    "ポータルは、すでに全社で使っている「サクラ業務プラットフォーム」の上に作ります。",
    "画面のフレームワークには React を使い、ログインは今の社員アカウントをそのまま使います。",
    "開発は11月から翌年3月までの5か月とし、次のマイルストーンを仮に置きます。",
    "- マイルストーン1（12月19日）: 画面の設計の承認",
    "プロジェクトのマイルストーンを決めます。",
    "CPU とメモリのリソースが足りないときは、夜間の集計ジョブを止めてから始めます。",
    "エンゲージメント率は、いいね、返信、保存の合計を表示回数で割った値です。",
    "ご質問は、ソリューション事業部の窓口までお寄せください。",
    "URL のスキームが https でないリンクには、警告を出します。",
    "アプリは、クラウドのプラットフォームが用意する実行環境（PaaS）に載せます。",
    "マイルストーン M3 の完了の条件は、結合試験で見つかった不具合が0件になることです。",
)
THIN_EVALUATION_FIX = (
    "委託先の回答の品質も高いです。",
    "視認性も高いです。",
    "アームの操作性が優れています。",
    "スイッチの手触りも心地よいです。",
    "本体の質感も上質です。",
    "検索の利便性も高いです。",
    "新しい予約画面は操作の手軽さも抜群です。",
    "新しい部屋の居心地もよいです。",
    "この手順は安定性が高いです。",
    "このマットレスは寝心地がよいです。",
    "キーの打鍵感も心地よいです。",
    "保温性も高いです。",
)
THIN_EVALUATION_KEEP = (
    "先行してお使いいただいた方からは、「夜中に使っても目が疲れにくい」「スイッチの手触りがいい」という声をいただきました。",
    "消費電力は従来品の9ワットから6ワットに下がり、省エネ性能が高くなりました。",
    "台座は重さ1.2キロの鋳鉄製で、アームをいちばん先まで伸ばしても倒れないほど安定性が高いです。",
    "「この布団、寝心地がいいね」と妹は言って、すぐに寝息を立て始めた。",
    "運転音は旧型の42デシベルから35デシベルに下がり、静音性が高まりました。",
    "このペンは、紙に当てたときの引っかかりが少なく、インクが最後まで途切れないので、書き心地がなめらかです。",
    "画面の操作の評価は、5段階で3.1から4.2に上がり、操作性が高いと答えた人は6割になりました。",
    "本施設は、入口の段差をなくし、各階に手すりを設けるなど、利便性の高い造りとしています。",
    "関数を1つ30行以内に分けたので、保守性が高まりました。",
    "レビューには「履き心地がよく、一日歩いても足が痛くならない」という声が並んでいます。",
    "蝶番の耐久性は、10万回の開け閉めの試験で傷みが出なかったことから、十分に高いと判断しました。",
)
# metaphor_label: (見出し, 節の本文)。本文がないのは文書の題
LABEL_FIX = (
    ("## 数え係", "同じ顧客が同じ内容で24時間以内に送った問い合わせは、1件にまとめました。区分は、受け付けた担当者が付けたものをそのまま使い、付け忘れの312件だけを集計の担当が読んで付け直しました。"),
    ("## 灯台", "22時から翌7時までのチャットには、外部の委託先が一次回答を返しています。この時間帯の問い合わせは全体の14%で、一次回答までの時間の中央値は6分でした。翌朝の担当者が委託先の回答を手直しした割合は3%です。委託先の回答の品質も高いです。夜間の対応を続けたことは、解約の申し出の取りこぼしを防いだと言えるでしょう。"),
    ("## 現場の横", "物流部とは週に1回、配送の遅れに関する問い合わせの一覧を共有しています。共有を始めた6月からは、同じ遅れについての二度目の問い合わせが月に40件ほど減りました。"),
    ("## 案内係", "新しいポータルでは、トップページに検索欄を1つ置き、経費、休暇、備品などの手続きの名前で検索すると、書式と締め切りと担当部署が一度に出るようにします。検索の利便性も高いです。"),
    ("## 裏方", "使う人に見えないところでの支えを大切にし、迷わず使えるように整えていきます。"),
    ("## 迷子係", "同じ部屋に予約が重なったときは、先に入れた予約を優先します。どうしても譲ってほしいときは、予約した人に直接ご相談ください。話がまとまらないときは、総務部の担当（内線2210）が間に入ります。"),
    ("## 留守番", "夜間（20時以降）と休日に会議室を使うときは、予約に加えて、前日の17時までに総務部へ利用の届けを出してください。"),
    ("## 黒子", "目立たないところで、皆さんの会議を支えていきます。"),
    ("## 見張り番", "作業のあいだ通知が鳴り続けないように、監視画面で注文データベースの通知を60分止めます。止めた時刻は作業の記録に書きます。"),
    ("## 後片付け係", "一時フォルダの中身を消し、止めていた監視の通知を元に戻します。"),
    ("## 門番", "ログインしていない利用者が管理画面の URL を開くと、ログインの画面に戻します。管理者の権限がない社員には、403 のエラーを返します。"),
    ("## 仕分け係", "取り込んだ売上の明細は、店舗コードと日付で分け、店舗ごとのファイルに書き出します。店舗コードのない明細は別のファイルに残します。"),
    ("## 郵便係", "注文を受けたら、確認のメールを30秒以内に送ります。送れなかったメールは5分ごとに3回まで送り直します。"),
    ("## サーバーのそば", "落ち着いて、一つずつ確かめていきましょう。"),
    ("## 道しるべ", "大切なのは、迷ったときに立ち止まれることです。"),
)
LABEL_KEEP = (
    ("# 2026年度上期 問い合わせの集計報告", ""),
    ("## 件数の推移", "月ごとの件数は、4月の1,102件から9月の1,689件まで増えました。増えた分のおよそ7割は、7月に始めた定期便の解約と配送日の変更に関するものです。7月以降の増加は、定期便の開始が主な原因だったと言えるでしょう。"),
    ("## まとめ", "一次回答までの時間は、前年同期の11分から7分に縮みました。この結果は、品質の向上につながったと言えるでしょう。一方で、定期便に関する問い合わせは下期も増えると言えるでしょう。"),
    ("## 夜ふかし係", "照らす範囲は、机の上の横80センチ、奥行き50センチです。中心から30センチ離れた場所でも、中心の9割の明るさを保ちます。視認性も高いです。"),
    ("## 自在", "アームには関節が3か所あり、片手で角度と高さを変えられます。アームの操作性が優れています。スイッチの手触りも心地よいです。本体の質感も上質です。"),
    ("## 背景", "いまの社内ポータルは2019年に作ったもので、手続きの説明が部署ごとのページに散らばっています。情報システム部への問い合わせの4割は、申請の書式がどこにあるかを尋ねるものでした。今の社内ポータルは、役目を終えつつあると言えるでしょう。"),
    ("## 作り方", "ポータルは、すでに全社で使っている「サクラ業務プラットフォーム」の上に作ります。画面のフレームワークには React を使い、ログインは今の社員アカウントをそのまま使います。"),
    ("## 部署間の連携", "部署間のシナジーを生むことも狙いです。営業部が集めた顧客の声を、開発部が週ごとに読めるページを設けます。全社のナレッジを集めるプラットフォームにもしていきます。"),
    ("## 予約のしかた", "予約画面では、空いている部屋が緑色で表示され、部屋と時間を選ぶ2回の操作で予約が終わります。新しい予約画面は操作の手軽さも抜群です。予約は2週間先まで入れられ、1回に取れるのは3時間までです。"),
    ("## そのほか", "今回の切り替えは、紙の申請をなくす計画のマイルストーンです。総務部は2027年3月までに紙の申請書をすべてなくす計画を進めており、会議室の予約はその1件目にあたります。新しい決まりには、皆さんのコミットメントが欠かせません。旧台帳からの予約の移し替えは総務部で行いますので、移行は大きな混乱なく進むと言えるでしょう。 なお、前回のお知らせにあった「〜と言えるでしょう」という書き方が分かりにくい、とのご意見をいただきました。"),
    ("## 準備", "作業用のサーバーに入り、空き容量が50GB以上あることを確かめます。CPU とメモリのリソースが足りないときは、夜間の集計ジョブを止めてから始めます。"),
    ("## 戻す作業", "1. 注文の受け付けを止めます（メンテナンス画面に切り替えます）。 2. 前日のバックアップを作業用のサーバーに取り出します。 3. 取り出したバックアップから、注文データベースを作り直します。 4. 注文の件数を、前日の締めの件数と比べます。 この手順は安定性が高いです。過去12回の作業で、途中で止まったことは一度もありません。作業の時間は、旧手順の約40分から約12分に縮みました。この手順で戻せば、データの欠けは最小限に抑えられると言えるでしょう。"),
    ("## 水やり係", "朝起きると、まずじょうろを持って外に出る。土の表面が白く乾いていたら、鉢の底から水が流れ出るまで注ぐ。湿っていたら何もしない。それだけのことを、私は半年続けている。"),
    ("## 来客", "六月のある朝、トマトの葉の裏に小さな虫が並んでいた。指でつぶしながら、私は虫よけの薬を買うかどうか一日迷い、結局、牛乳を薄めて吹きかけた。効いたのかどうかは、今もよく分からない。"),
    ("## 収穫", "八月に、初めて赤い実を三つ摘んだ。遊びに来ていた祖母に見せると、「これはもう立派な畑と言えるでしょう」と笑った。鉢が四つあるだけのベランダを、畑と呼んでいいのかは分からない。それでも私は、その日から畑と呼んでいる。 十月に入って、トマトの茎は茶色く固くなった。来年はナスも植えてみたいと思い、空いた鉢の土を新聞紙の上に広げて干している。"),
    ("# ベランダの小さな畑", ""),
    ("# 夜明け係", ""),
    ("## 見張り番", "夜の倉庫の前。守衛の老人がパイプ椅子に座っている。"),
    ("## キャッシュ", "画像は CDN のキャッシュに7日間残ります。"),
    ("## 当番", "今月の掃除の当番は経理部です。"),
    ("## 台所のそば", "幅は18センチで、冷蔵庫と壁のすき間に入ります。"),
    ("## 進め方", "この開発は、社内規程の「大規模な情報システムの導入」に当たると言えるでしょう。そのため、経営会議の承認をお願いします。開発は11月から翌年3月までの5か月とし、次のマイルストーンを仮に置きます。"),
)

# metaphor_label の残す見出しのうち、lint では印がつかないふつうの見出し（よく使う節の名前、本文の話題の語、助詞を含む句、題）
LABEL_ORDINARY = tuple(item for item in LABEL_KEEP
                       if item[0] not in ("## 夜ふかし係", "## 自在", "## 水やり係", "## 来客", "## 収穫", "# 夜明け係",
                                          "## 見張り番", "## 台所のそば"))
# 残す見出しのうち、lint の条件には当たるもの。essay、promo、script の文書（DOC_TYPE_SKIP_RULES で外す。担当 B）と、
# 文書の題（題は推敲で変えず、書き手に確かめる）
LABEL_MATCHES_CONDITION = ("## 夜ふかし係", "## 自在", "## 水やり係", "## 来客", "## 収穫", "# 夜明け係", "## 見張り番",
                           "## 台所のそば")
# katakana_term の残す文のうち、番号を付けた項目の名前とカギ括弧の中（印がつかない）。ほかの残す文は、印はつくが推敲で残す
# フレームワークとリソースは、ソフトウェアの語として定着しているので一覧に入れていない
KATAKANA_KEEP_UNMARKED = (
    "ポータルは、すでに全社で使っている「サクラ業務プラットフォーム」の上に作ります。",
    "画面のフレームワークには React を使い、ログインは今の社員アカウントをそのまま使います。",
    "CPU とメモリのリソースが足りないときは、夜間の集計ジョブを止めてから始めます。",
    "- マイルストーン1（12月19日）: 画面の設計の承認",
    "マイルストーン M3 の完了の条件は、結合試験で見つかった不具合が0件になることです。",
)


class OwnerSeedTest(unittest.TestCase):
    def test_owner_seeds_are_marked(self):
        for text, rule, words in OWNER_SEEDS:
            with self.subTest(text=text):
                found = new_findings(text + "\n")
                self.assertEqual([(f["rule"], f["_words"]) for f in found], [(rule, words)])
                self.assertEqual(found[0]["severity"], "info")
                self.assertEqual(found[0]["snippet"], text)

    def test_owner_seeds_of_other_rules_are_not_marked_here(self):
        for text in OWNER_OTHERS:
            with self.subTest(text=text):
                self.assertEqual(rules_of(text + "\n"), [])

    def test_owner_seeds_in_one_document(self):
        text = "\n".join(text for text, _, _ in OWNER_SEEDS) + "\n"
        self.assertEqual([(f["line"], f["rule"]) for f in new_findings(text)],
                         [(1, "calque"), (2, "calque"), (3, "calque"), (4, "katakana_term")])


class CalqueTest(unittest.TestCase):
    def test_fix_sentences_are_marked_with_the_type(self):
        for number, text in CALQUE_FIX:
            with self.subTest(text=text):
                found = [f for f in new_findings(text + "\n") if f["rule"] == "calque"]
                self.assertEqual(len(found), 1)
                self.assertIn(TYPE_NAMES[number], found[0]["message"])
                self.assertTrue(found[0]["message"].startswith("直訳語（"))
                self.assertTrue(found[0]["message"].endswith("）" + TAIL))
                self.assertTrue(found[0]["_words"])

    def test_keep_sentences_are_not_marked(self):
        for _, text in CALQUE_KEEP:
            with self.subTest(text=text):
                self.assertNotIn("calque", rules_of(text + "\n"))

    def test_established_lists_are_kept(self):
        """組み込みの除外の一覧（定着した言い方）。一覧から消すと、この試験が落ちる。"""
        for word in ("宛先", "送信先", "保存先", "接続先", "連絡先", "取引先", "依存先", "問い合わせ先", "提出先", "出力先",
                     "移行先", "転送先", "参照先", "委託先", "勤務先", "行き先", "届け先", "送り先", "優先"):
            with self.subTest(word=word):
                self.assertIn(word, yomiyasu_lint._CALQUE_ESTABLISHED_SAKI)
                self.assertNotIn("calque", rules_of("データの{}は、この画面で決めます。\n".format(word)))
        for text in ("すべてのテストが通りました。", "2回目からはキャッシュが効きます。", "眠くなる薬が効いてきました。",
                     "雨の日はブレーキが効きにくくなります。", "地下鉄の駅の入口で待ち合わせます。",
                     "人が落とし物を拾って、交番に届けました。", "このパッケージの依存先は、設定のファイルに書いてあります。",
                     "外部の決済サービスは、このシステムの依存先です。", "ビルドが通ったら、レビューを頼みます。",
                     "CI が通らないときは、ログを見ます。", "この関数は、値が負なら例外を投げます。",
                     "ワーカーから API サーバーに ping が通ることを確かめます。", "設定が効かないときは、サーバーを再起動します。",
                     "このシステムは、多くの技術的な負債を抱えています。", "このサービスは、利用者の声を拾って直しています。",
                     "このマイクは、周りの音を拾います。", "このスクリプトは、売上から返品の額を引きます。",
                     "本社ビルの正面入口は、11月末まで閉じています。", "紙の申請書は、総務部の窓口に出してください。",
                     "API の利用申請の窓口は、情報システム部です。", "数年先を見すえて、サーバーの台数を決めます。",
                     "外出先からでも、管理画面に入れます。", "バックアップの戻し先を選びます。"):
            with self.subTest(text=text):
                self.assertNotIn("calque", rules_of(text + "\n"))

    def test_person_subject_and_attributive_verbs_are_not_type1(self):
        for text in ("担当者は、ジョブが拾った通知を確かめます。", "サーバー管理者が、毎朝ログを拾います。",
                     "情報システム部が、申請を見張ります。", "このアプリは、話した内容を文字にします。",
                     "引き続き、サーバーの様子を見ます。", "手順の通りに、処理を進めてください。",
                     "共通する設定は、まとめて書きます。", "在庫が不足しているときは、注文を受け付けません。",
                     "補足すると、このジョブは夜間だけ動きます。", "このスクリプトは、前回の設定を引き継ぎます。",
                     "テストを通すために、境界値の扱いを直しました。", "このフィルターを通して表示します。"):
            with self.subTest(text=text):
                self.assertNotIn("calque", rules_of(text + "\n"))

    def test_each_verb_and_phrase_is_found(self):
        """型1の動詞と型3の句のどれにも当たる類例がある（文書全体の手掛かりの語がどの正規表現も覆っている）。"""
        verbs = {
            "拾う": "このジョブは、失敗した通知を拾います。", "引き込む": "このクエリは、古い行まで引き込みます。",
            "引く": "このワーカーは、キューからジョブを引きます。", "通す": "この関数は、空の値も通します。",
            "通る": "このプロキシは、社内の通信だけが通ります。", "効く": "このフックは、コミットのたびに効きます。",
            "響く": "このキャッシュは、応答の速さに響きます。", "足す": "このスクリプトは、末尾に改行を足します。",
            "抱える": "このワーカーは、古い接続を抱えたまま動きます。", "見張る": "このエージェントは、応答の時間を見張ります。",
            "食う": "このプロセスは、メモリを食います。", "受け止める": "このミドルウェアは、不正なリクエストを受け止めます。",
            "飲み込む": "このクライアントは、新しい形式を飲み込めません。", "覚える": "このキャッシュは、前の結果を覚えます。",
            "忘れる": "このプロセスは、再起動すると状態を忘れます。", "投げる": "この体重計は、測った値をアプリに投げます。",
            "叩く": "このスクリプトは、毎朝 API を叩きます。", "話す": "このクライアントは、サーバーと gRPC で話します。",
            "喋る": "このボットは、利用者と喋ります。", "助ける": "このツールは、表の整理を助けます。",
            "手伝う": "このスクリプトは、移行の作業を手伝います。", "気にする": "この関数は、引数の順序を気にしません。",
            "怒る": "このリンターは、未使用の変数に怒ります。", "文句を言う": "このコンパイラは、型の違いに文句を言います。",
        }
        self.assertEqual(set(verbs), set(name for name, _ in yomiyasu_lint._CALQUE_VERBS))
        for name, text in verbs.items():
            with self.subTest(verb=name):
                found = [f for f in new_findings(text + "\n") if f["rule"] == "calque"]
                self.assertEqual([f["_words"] for f in found], [(name,)])
        phrases = {
            "足すものがない": "この変更には、足すものがありません。", "価値を足す": "この機能は、利用者に価値を足します。",
            "失効が効く": "鍵を替えると、古い鍵の失効が効きます。", "から効く": "新しい料金は、来月の請求から効きます。",
            "時間を取る": "読み込みは、平均で3秒を取っていました。", "意味をなす": "この分け方は、今なら意味をなします。",
            "針を動かす": "この変更は、売上の針をほとんど動かしません。", "ステップを取る": "次の二つのステップを取ります。",
            "所有権を持つ": "この障害には、運用チームが所有権を持ちます。", "違いを作る": "この修正は、大きな違いを作りました。",
            "手を伸ばす": "不明な点は、総務部に手を伸ばしてください。", "ライブになる": "新しい画面は、正午にライブになりました。",
            "同じページにいる": "全員が同じページにいるよう、表にまとめました。", "水を試す": "まず水を試すところから始めます。",
            "透明に": "移行は、利用者にとって透明に行われます。", "場所を取る": "定例は、会議室Aで場所を取ります。",
            "ループを閉じる": "最後に、先週の質問のループを閉じます。", "ループに入れる": "関係者をループに入れておきます。",
            "駆動される": "この判断は、データに駆動されています。", "配達する": "今期は、目標を上回る数字を配達しました。",
            "大きな絵": "まず大きな絵を見てから、細部を決めます。", "インパクトを持つ": "この変更は、大きなインパクトを持ちます。",
            "決定を作る": "来週までに決定を作ります。", "質問を持つ": "質問を持っている人は、後で聞いてください。",
            "真剣に取る": "この指摘を真剣に取ります。", "目を保つ": "応答の時間に目を保ちます。",
            "テーブルに置く": "その案を、もう一度テーブルに載せます。", "次のレベルに": "この改善で、品質を次のレベルに引き上げます。",
        }
        self.assertEqual(set(phrases), set(name for name, _ in yomiyasu_lint._CALQUE_PHRASES))
        for name, text in phrases.items():
            with self.subTest(phrase=name):
                found = [f for f in new_findings(text + "\n") if f["rule"] == "calque"]
                self.assertEqual(len(found), 1)
                self.assertIn(name, found[0]["_words"])
                self.assertIn(TYPE_NAMES[3], found[0]["message"])

    def test_two_types_on_one_line_are_one_finding(self):
        text = "外部からの注文は、この受け口に届き、夜間の集計バッチが拾います。\n"
        found = new_findings(text)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["message"], "直訳語（{}。{}）{}".format(TYPE_NAMES[1], TYPE_NAMES[2], TAIL))
        self.assertEqual(found[0]["_words"], ("拾う", "受け口"))

    def test_metaphor_verb_on_the_line_hides_calque(self):
        """同じ行に metaphor_verb の候補があれば calque を出さない。"""
        text = "データが静かに壊れても、再送ジョブが拾います。\n"
        result = yomiyasu_lint.lint_text(text)
        self.assertIn("metaphor_verb", [f["rule"] for f in result["findings"]])
        self.assertNotIn("calque", [f["rule"] for f in result["findings"]])
        self.assertIn("calque", rules_of("データが届かなくても、再送ジョブが拾います。\n"))

    def test_translated_term_on_the_line_hides_type3(self):
        """同じ行に translated_term の候補があれば型3を出さない（型1と型2は出す）。"""
        text = "この版では、古い鍵の失効が効きます。\n"
        result = yomiyasu_lint.lint_text(text)
        self.assertIn("translated_term", [f["rule"] for f in result["findings"]])
        self.assertNotIn("calque", [f["rule"] for f in result["findings"]])
        found = new_findings("この版では、古い鍵の失効が効き、再送ジョブが拾います。\n")
        self.assertEqual([(f["rule"], f["_words"]) for f in found], [("calque", ("拾う",))])

    def test_dictionary_nouns_are_not_calques(self):
        for _, text in CALQUE_KEEP:
            if _ is None:
                with self.subTest(text=text):
                    self.assertEqual(rules_of(text + "\n"), [])


class MetaphorLabelTest(unittest.TestCase):
    @staticmethod
    def document(heading, body):
        if heading.startswith("## "):
            return "# 社内の資料\n\n{}\n\n{}\n\n{}\n".format(heading, body, FILLER)
        return heading + "\n\n" + body + "\n\n" + FILLER + "\n"

    def test_fix_headings_are_marked(self):
        for heading, body in LABEL_FIX:
            with self.subTest(heading=heading):
                text = self.document(heading, body)
                line = text.split("\n").index(heading) + 1
                found = [f for f in new_findings(text) if f["rule"] == "metaphor_label"]
                self.assertEqual([(f["line"], f["snippet"]) for f in found], [(line, heading)])
                self.assertEqual(found[0]["message"], "見出しか1行目の比喩のラベル" + TAIL)
                self.assertEqual(found[0]["_words"], (heading.lstrip("# "),))

    def test_ordinary_headings_are_not_marked(self):
        for heading, body in LABEL_ORDINARY:
            with self.subTest(heading=heading):
                self.assertNotIn("metaphor_label", rules_of(self.document(heading, body)))

    def test_headings_that_meet_the_condition(self):
        """残す見出しのうち lint の条件に当たるもの（種類で外すか、題として推敲で残す）は、種類なしでは印がつく。"""
        for heading, body in LABEL_KEEP:
            if heading in LABEL_MATCHES_CONDITION:
                with self.subTest(heading=heading):
                    self.assertIn("metaphor_label", rules_of(self.document(heading, body)))

    def test_common_section_names_are_kept(self):
        """組み込みの除外の一覧（よく使う節の名前と題の語）。一覧から消すと、この試験が落ちる。"""
        for word in ("概要", "背景", "目的", "手順", "結果", "まとめ", "はじめに", "注意", "前提", "課題", "対策", "原因", "準備",
                     "作り方", "進め方", "そのほか", "資料", "記録", "議事録"):
            with self.subTest(word=word):
                self.assertIn(word, yomiyasu_lint._LABEL_COMMON)
                self.assertEqual(rules_of("# 記録\n\n## {}\n\n本文は短い説明です。\n\n" + FILLER + "\n".format(word)), [])

    def test_label_in_the_body_is_not_marked(self):
        self.assertIn("metaphor_label", rules_of("# 資料\n\n## 門番\n\nログインしていない人を止めます。\n\n" + FILLER + "\n"))
        self.assertEqual(rules_of("# 資料\n\n## 門番\n\n門番の役目は、ログインしていない人を止めることです。\n\n" + FILLER + "\n"), [])
        # 「〜係」の前の語が本文にあれば、本文の話題とみなす（会計係の節で会計を書く）
        self.assertEqual(rules_of("# 資料\n\n## 会計係\n\n会計の記録は月末に締めます。\n\n" + FILLER + "\n"), [])
        # 本文がほとんどない文書では見ない
        self.assertEqual(rules_of("# 資料\n\n## 門番\n\nログインしていない人を止めます。\n"), [])

    def test_first_line_label(self):
        self.assertEqual([(f["line"], f["rule"]) for f in new_findings("夜勤\n\n夜の作業の手順を書きます。\n\n" + FILLER + "\n")],
                         [(1, "metaphor_label")])
        self.assertEqual(rules_of("---\ntitle: 記録\n---\n\n夜勤\n\n夜の作業の手順を書きます。\n\n" + FILLER + "\n"),
                         ["metaphor_label"])
        # 文として終わる1行目、長い1行目、宛名、表と箇条書きの1行目はラベルではない
        for first in ("夜勤です。", "今月の作業の手順をまとめました", "田中様", "総務部各位", "| 夜勤 | 当番 |", "- 夜勤"):
            with self.subTest(first=first):
                self.assertEqual(rules_of(first + "\n\n手順を書きます。\n\n" + FILLER + "\n"), [])

    def test_phrases_and_normal_compound_headings(self):
        for heading in ("## 変更内容", "## 確認方法", "## 受信処理", "## 冪等性", "## 障害報告書", "## 件数の推移",
                        "## 来月からの変更", "## 速さ", "## 1. 再処理", "## Usage", "## 2026年の予定", "## 丁寧な人",
                        "## 設計 — 実装", "## 確認・修正", "## 見出し", "## 例（合成）", "## 示し方", "## いつ読むか", "## 山"):
            with self.subTest(heading=heading):
                self.assertEqual(rules_of("# 資料\n\n{}\n\n本文は短い説明です。\n\n" + FILLER + "\n".format(heading)), [])

    def test_type2_heading_is_only_metaphor_label(self):
        """見出しのラベルと同じ行に型2の calque が当たるときは、metaphor_label だけを出す。"""
        found = new_findings("# 資料\n\n## 受け口\n\n注文のデータはここに届きます。\n\n" + FILLER + "\n")
        self.assertEqual([(f["line"], f["rule"]) for f in found], [(3, "metaphor_label")])
        found = new_findings("# 資料\n\n## 注文データの受け口\n\n注文のデータはここに届きます。\n\n" + FILLER + "\n")
        self.assertEqual([(f["line"], f["rule"]) for f in found], [(3, "calque")])


class KatakanaTermTest(unittest.TestCase):
    def test_fix_sentences_are_marked(self):
        for text in KATAKANA_TERM_FIX:
            with self.subTest(text=text):
                found = new_findings(text + "\n")
                self.assertEqual([f["rule"] for f in found], ["katakana_term"])
                self.assertEqual(found[0]["message"], "意味の薄くなりやすいカタカナ語" + TAIL)

    def test_keep_sentences(self):
        """残す文の語にも印はつく（直すかは推敲で読み手と分野で決める）。番号を付けた項目とカギ括弧の中だけは印がつかない。"""
        for text in KATAKANA_TERM_KEEP:
            with self.subTest(text=text):
                expected = [] if text in KATAKANA_KEEP_UNMARKED else ["katakana_term"]
                self.assertEqual(rules_of(text + "\n"), expected)

    def test_words_of_a_line(self):
        found = new_findings("全社のナレッジを集めるプラットフォームにし、部署間のシナジーを生みます。\n")
        self.assertEqual([(f["rule"], f["_words"]) for f in found], [("katakana_term", ("ナレッジ", "プラットフォーム", "シナジー"))])
        found = new_findings("在宅勤務の机のためのライティングソリューションです。\n")
        self.assertEqual(found[0]["_words"], ("ソリューション",))


class ThinEvaluationTest(unittest.TestCase):
    def test_fix_sentences_are_marked(self):
        for text in THIN_EVALUATION_FIX:
            with self.subTest(text=text):
                found = new_findings(text + "\n")
                self.assertEqual([f["rule"] for f in found], ["thin_evaluation"])
                self.assertEqual(found[0]["message"], "中身の薄い評価の文" + TAIL)

    def test_keep_sentences_are_not_marked(self):
        for text in THIN_EVALUATION_KEEP:
            with self.subTest(text=text):
                self.assertNotIn("thin_evaluation", rules_of(text + "\n"))

    def test_shapes(self):
        self.assertEqual(new_findings("この椅子は座り心地が快適です。\n")[0]["_words"], ("座り心地",))
        self.assertEqual(new_findings("このソファは座り心地もとても快適です。\n")[0]["_words"], ("座り心地",))
        self.assertEqual(rules_of("このアプリは使い心地がよいです。\n"), ["thin_evaluation"])
        for text in ("この椅子の座り心地は、試してから決めてください。", "座り心地が快適だと答えた人は6割でした。",
                     "クッションを厚くしたので、座り心地が快適です。", "保守性の高いコードを書きます。",
                     "新しいエンジンは、前の型より性能が高くなりました。", "「座り心地が快適です」と書いてありました。"):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text + "\n"), [])


class CommonTest(unittest.TestCase):
    def test_not_in_code_quotes_urls_and_identifiers(self):
        for text in ("```\n再送ジョブが拾います。\n```\n", "> 再送ジョブが拾います。\n", "`再送ジョブが拾います`\n",
                     "「再送ジョブが拾います」と書いた。\n", "『この入口を通ります』と書いた。\n",
                     "“再送ジョブが拾います”と書いた。\n", "<div>再送ジョブが拾います。</div>\n",
                     "---\ntitle: 再送ジョブが拾います\n---\n\n本文です。\n", "詳しくは https://example.com/マイルストーン を見ます。\n",
                     "[資料](https://example.com/マイルストーン)を見ます。\n", "設定は `platform_マイルストーン.json` に書きます。\n"):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text), [])

    def test_headings_tables_and_lists_are_scanned(self):
        self.assertEqual(rules_of("# 資料\n\n## 再送ジョブが拾う通知の一覧と扱い方\n\n本文です。\n"), [])  # 名詞を修飾する形
        self.assertEqual(rules_of("# 資料\n\n## 注文データの受け口\n\n本文です。\n"), ["calque"])
        self.assertEqual(rules_of("| 項目 | 内容 |\n|---|---|\n| 申請書の受け口 | 総務部 |\n"), ["calque"])
        self.assertEqual(rules_of("- 取りこぼした通知は、再送ジョブが拾います。\n"), ["calque"])
        self.assertEqual(rules_of("1. 本体の質感も上質です。\n"), ["thin_evaluation"])

    def test_one_finding_per_rule_per_line(self):
        text = "再送ジョブが拾い、監視のエージェントが見張ります。このワーカーも鍵を抱えます。\n"
        found = new_findings(text)
        self.assertEqual([f["rule"] for f in found], ["calque"])
        self.assertEqual(found[0]["_words"], ("拾う", "見張る", "抱える"))

    def test_info_and_score_and_public_keys(self):
        text = "\n".join(text for text, _, _ in OWNER_SEEDS) + "\n本体の質感も上質です。\n"
        result = yomiyasu_lint.lint_text(text)
        mine = [f for f in result["findings"] if f["rule"] in RULES]
        self.assertEqual(len(mine), 5)
        self.assertTrue(all(f["severity"] == "info" for f in mine))
        self.assertTrue(all(sorted(f) == ["line", "message", "rule", "severity", "snippet"] for f in result["findings"]))
        self.assertNotIn("_words", json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["rule_penalty_score"], yomiyasu_lint._rule_penalty_score(
            [f for f in result["findings"] if f["rule"] not in RULES], result["metrics"]["char_count"], 0))
        for finding in mine:
            self.assertTrue(finding["message"].endswith(TAIL))

    def test_messages_do_not_name_a_replacement(self):
        """message は型と共通の文だけで、置き換え先の語を出さない（候補の語も出さない）。"""
        text = "\n".join(text for text, _, _ in OWNER_SEEDS) + "\n本体の質感も上質です。\n# 資料\n"
        for finding in new_findings(text):
            for word in finding["_words"]:
                self.assertNotIn(word, finding["message"])


class ListFileTest(unittest.TestCase):
    """references/lists/ の2つの一覧と、lint の中の同じ一覧。"""

    def test_files_match_the_builtin_lists(self):
        for name, pattern in (("katakana-terms", False), ("thin-evaluation", True)):
            with self.subTest(name=name):
                data = (ROOT / "references" / "lists" / (name + ".txt")).read_bytes()
                self.assertEqual(data, (ROOT / "skills" / "yomiyasu" / "references" / "lists" / (name + ".txt")).read_bytes())
                parsed = yomiyasu_lint._v220_parse_list(data.decode("utf-8"), pattern=pattern)
                self.assertEqual(parsed, tuple(yomiyasu_lint._V220_BUILTIN_LISTS[name]))
                self.assertTrue(data.decode("utf-8").startswith("# "))

    def test_loaded_from_the_files(self):
        for name in ("katakana-terms", "thin-evaluation"):
            with self.subTest(name=name):
                items, source = yomiyasu_lint._v220_load_list(name)
                self.assertEqual(source, "references/lists/{}.txt".format(name))
                self.assertIsNone(yomiyasu_lint._V220_LIST_PROBLEMS[name])

    def test_parse_list_reads_bom_crlf_and_comments(self):
        text = "﻿# 説明\r\n\r\nマイルストーン\r\n  # 字下げした説明\r\nシナジー\r\n"
        self.assertEqual(yomiyasu_lint._v220_parse_list(text), ("マイルストーン", "シナジー"))
        self.assertEqual(yomiyasu_lint._v220_parse_list("# 説明\r\n質感\t(?:上質)\r\n", pattern=True), (("質感", "(?:上質)"),))
        # 正規表現の誤りは読むときには確かめない（初めて当てるときに確かめる。ListLoadingProcessTest）
        for bad in ("質感\n", "\t上質\n", "質感\t上質\tよい\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(Exception):
                    yomiyasu_lint._v220_parse_list(bad, pattern=True)


_PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import yomiyasu_lint
out = {}
result = yomiyasu_lint.lint_text(sys.argv[2])
out["rules"] = [finding["rule"] for finding in result["findings"]]
for name in ("katakana-terms", "thin-evaluation"):
    items, source = yomiyasu_lint._v220_load_list(name)
    out[name] = {"source": source, "problem": yomiyasu_lint._V220_LIST_PROBLEMS[name], "count": len(items)}
print(json.dumps(out, ensure_ascii=False))
"""


class ListLoadingProcessTest(unittest.TestCase):
    """スクリプトの隣の ../references/lists/ の読み方（diff の _load_list と同じ）。写したスクリプトで子プロセスを動かす。"""

    def probe(self, lists, text="本体の質感も上質です。新しいバリューを届けます。\n"):
        with tempfile.TemporaryDirectory(prefix="yomiyasu-a1-") as folder:
            scripts = Path(folder) / "scripts"
            scripts.mkdir()
            for name in ("yomiyasu_lint.py", "markdown_visibility.py"):
                shutil.copyfile(str(SCRIPTS / name), str(scripts / name))
            if lists is not None:
                base = Path(folder) / "references" / "lists"
                base.mkdir(parents=True)
                for name, data in lists.items():
                    (base / (name + ".txt")).write_bytes(data)
            process = subprocess.run([sys.executable, "-B", "-c", _PROBE, str(scripts), text], capture_output=True,
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace"))
            return json.loads(process.stdout.decode("utf-8"))

    def test_absent_lists_use_the_builtin_lists_silently(self):
        out = self.probe(None)
        for name in ("katakana-terms", "thin-evaluation"):
            self.assertEqual((out[name]["source"], out[name]["problem"]), ("builtin", None))
            self.assertEqual(out[name]["count"], len(yomiyasu_lint._V220_BUILTIN_LISTS[name]))
        self.assertEqual(out["rules"], ["katakana_term", "thin_evaluation"])

    def test_bom_and_crlf_files_are_read(self):
        out = self.probe({"katakana-terms": "﻿# 説明\r\nナレッジ\r\n".encode("utf-8"),
                          "thin-evaluation": "﻿# 説明\r\n質感\t(?:上質)\r\n".encode("utf-8")})
        self.assertEqual((out["katakana-terms"]["source"], out["katakana-terms"]["count"]),
                         ("references/lists/katakana-terms.txt", 1))
        self.assertEqual((out["thin-evaluation"]["source"], out["thin-evaluation"]["count"]),
                         ("references/lists/thin-evaluation.txt", 1))
        self.assertEqual(out["rules"], ["thin_evaluation"])   # バリューは一覧にない

    def test_unreadable_files_fall_back_with_a_reason(self):
        out = self.probe({"katakana-terms": "マイルストーン\n".encode("cp932"),
                          "thin-evaluation": "質感\t(?:\n".encode("utf-8")})
        self.assertEqual((out["katakana-terms"]["source"], out["katakana-terms"]["problem"]), ("builtin", "UTF-8 として読めません"))
        self.assertEqual(out["thin-evaluation"]["source"], "builtin")
        self.assertTrue(out["thin-evaluation"]["problem"].startswith("正規表現の誤り"))
        self.assertEqual(out["rules"], ["katakana_term", "thin_evaluation"])

    def test_empty_lists_turn_the_rules_off(self):
        out = self.probe({"katakana-terms": b"# none\n", "thin-evaluation": b"# none\n"})
        self.assertEqual(out["rules"], [])


if __name__ == "__main__":
    unittest.main()
