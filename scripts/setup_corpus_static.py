#!/usr/bin/env python3
"""
記事の抜粋と、コード内に定義した例文・境界確認用の文章を保存する初期検証用スクリプト。
実行すると保存済みファイルを上書きする。現行SKILLの実走検証には使わない。
"""
import os
import re
from html.parser import HTMLParser

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(BASE_DIR, "tests", "corpus")
HUMAN_DIR = os.path.join(CORPUS_DIR, "human")
EDGE_DIR = os.path.join(CORPUS_DIR, "edge_cases")

os.makedirs(HUMAN_DIR, exist_ok=True)
os.makedirs(EDGE_DIR, exist_ok=True)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts = []
        self.in_script = False
        self.current_tag = None
    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        if tag in ["script", "style", "head", "svg"]:
            self.in_script = True
    def handle_endtag(self, tag):
        if tag in ["script", "style", "head", "svg"]:
            self.in_script = False
    def handle_data(self, data):
        if not self.in_script:
            if self.current_tag in ["h1", "h2", "h3"]:
                self.texts.append(f"\n\n## {data.strip()}\n\n")
            elif self.current_tag == "p":
                self.texts.append(f"{data.strip()}\n\n")
            elif self.current_tag == "li":
                self.texts.append(f"- {data.strip()}\n")
            else:
                self.texts.append(data)


def setup_human_docs():
    # 1. 大賀さんのZenn記事から8本抽出
    source_html = "/Users/aiichiro.oga/.gemini/antigravity/brain/e6973c17-fdf9-4a3d-ab6e-e3775a349e8a/.system_generated/steps/1621/content.md"
    if os.path.exists(source_html):
        with open(source_html, "r", encoding="utf-8") as f:
            html = f.read()
        parser = TextExtractor()
        parser.feed(html)
        full_text = "".join(parser.texts)
        
        # 見出しで分割
        chunks = re.split(r"\n\n##\s+", full_text)
        valid_chunks = []
        for c in chunks:
            clean = c.strip()
            # ヘッダーやフッターのノイズを除外
            if len(clean) > 200 and "Zenn" not in clean[:50] and "登壇" not in clean[:50] and "JavaScript" not in clean:
                valid_chunks.append(clean)
        
        for idx in range(min(8, len(valid_chunks))):
            path = os.path.join(HUMAN_DIR, f"human_oga_{idx+1:02d}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# 大賀愛一郎 実務エッセイ 抜粋 {idx+1}\n\n" + valid_chunks[idx])

    # 2. その他、自然な人間執筆の技術解説・障害メモ・READMEなどから8本
    additional_human_texts = [
        # 09: Pythonパッケージ設計のベストプラクティス
        """# Pythonライブラリのディレクトリ構成方針

ライブラリを開発する際は、srcレイアウトを採用することを推奨します。プロジェクトルート直下にパッケージ名のディレクトリを配置すると、テスト実行時にローカルの未インストールコードを誤ってインポートしてしまい、パッケージング時のファイル不足に気づけない問題が発生します。

srcディレクトリを挟むことで、`pip install -e .` を実行した環境でのみインポート可能となり、本番環境と同じ挙動を保証できます。また、設定ファイルやビルド成果物がパッケージ内に混入する事故も防ぐことができます。""",

        # 10: PostgreSQLのコネクション枯渇対策
        """# コネクションプールの設定見直しについて

先週発生したデータベース接続エラーの原因を調査しました。WebAPIサーバーのオートスケールに伴い、各インスタンスが保持するプールの合計値がPostgreSQLの`max_connections`を超過していたことが判明しました。

対策として、PgBouncerを中継層として導入し、トランザクション単位での接続プーリングに切り替えます。これにより、アプリケーション側のインスタンスが増加しても、DBへの実コネクション数を一定数（最大100本）に抑えられます。""",

        # 11: PR説明文（非同期処理のリトライ改善）
        """# 決済通知Webhookの冪等性担保とリトライ間隔の調整

## 概要
外部決済プロバイダからのWebhook通知において、同一イベントが複数回配信された際に二重決済が発生するリスクがあったため、イベントIDによる重複排除処理を追加しました。

## 変更内容
- RedisにイベントIDをキーとする排他ロック（有効期限10分）を導入しました。
- 処理失敗時の再試行間隔を、即時リトライから指数バックオフ（初期値2秒、最大60秒）に変更しました。
- デッドレターキューの監視アラートをDatadogに追加しました。""",

        # 12: 社内Slack周知（VPNメンテナンス）
        """# 【周知】3月15日（土）深夜 社内VPN機器メンテナンスのお知らせ

インフラチームの大賀です。来週土曜日の深夜に、社内VPNゲートウェイのセキュリティパッチ適用作業を実施します。

作業時間帯: 2026年3月15日（土）01:00 〜 04:00
影響範囲: 上記時間帯のうち、最大15分程度の通信切断が2回発生します。

深夜作業中の方やバッチ処理を実行中の方はご注意ください。作業完了次第、こちらのチャンネルにて再度報告いたします。""",

        # 13: 技術選定メモ（REST vs gRPC）
        """# 内部マイクロサービス間通信のプロトコル選定

社内のバックエンドサービス間における通信プロトコルとして、従来のREST（JSON over HTTP/1.1）からgRPC（Protocol Buffers over HTTP/2）への移行を検討しました。

ペイロードサイズとシリアライズ速度の観点ではgRPCが圧倒的に優れており、高頻度なサービス間連携においてレイテンシを約40%削減できる見込みです。一方で、デバッグの容易さやブラウザ直接連携の要件を考慮し、外部公開APIは従来通りRESTを維持する方針とします。""",

        # 14: コードレビュー指摘
        """# サービス層におけるトランザクション境界の修正依頼

PR拝見しました。注文確定処理（`OrderService.confirm`）の中で、外部決済APIの呼び出しがDBトランザクションの内部に含まれています。

外部APIの応答が遅延した場合、DB接続が長時間保持され、コネクションプールの枯渇を招く恐れがあります。トランザクションはDB更新の直前のみで開始し、外部API呼び出しはトランザクションの外側で行うようにリファクタリングをお願いできますでしょうか。""",

        # 15: オンボーディング資料（開発環境構築）
        """# 新規メンバー向けローカル開発環境のセットアップ手順

リポジトリをクローンした後、まずはプロジェクトルートで以下のコマンドを実行してください。Docker Composeを利用して、ローカルテスト用のPostgreSQLとRedisが自動的に起動します。

```bash
docker compose up -d
cp .env.example .env
npm install
npm run dev
```

起動後にブラウザで `http://localhost:3000` を開き、ログイン画面が表示されることを確認してください。環境変数の設定で不明点があれば、いつでも開発チャンネルで質問してください。""",

        # 16: OSSライブラリの更新方針
        """# 依存ライブラリの定期アップデートと互換性確認

セマンティックバージョニングに従っているライブラリであっても、マイナーアップデートで既存動作に変更が入るケースがあります。そのため、Renovateによる自動PRは週に1回木曜日にまとめて確認し、CIのE2Eテストがすべて成功することを確認してからマージします。

重大な脆弱性（CVEスコア7.0以上）が報告された場合は、定期スケジュールを待たずに即時対応を行います。"""
    ]

    for idx, text in enumerate(additional_human_texts, 9):
        path = os.path.join(HUMAN_DIR, f"human_doc_{idx:02d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.strip())

    print(f"Human docs created: {len(os.listdir(HUMAN_DIR))} files.")


def setup_edge_cases():
    # 48本の正当な日本語・境界値テスト文書
    # 単純な正規表現（握る、倒す、溶かす、割る、壊れる等）が誤爆しやすい文脈
    edge_cases_data = [
        # 1-10: 握る（おにぎり、主導権を握る、手を握る、ハンドルを握る等）
        ("edge_nigiru_01", "お昼休みにコンビニでお握りを買って食べました。鮭のお握りが一番好きです。"),
        ("edge_nigiru_02", "プロジェクトの進行において、クライアント側が主導権を握る構図になっています。"),
        ("edge_nigiru_03", "緊急停止ボタンを操作する際は、レバーを強く握ってください。"),
        ("edge_nigiru_04", "迷子にならないように、子どもの手をしっかり握りながら歩きました。"),
        ("edge_nigiru_05", "長距離運転では、ハンドルを握る位置を定期的に変えて疲労を軽減します。"),
        ("edge_nigiru_06", "寿司職人が一貫ずつ心を込めて寿司を握る様子を見学しました。"),
        ("edge_nigiru_07", "交渉の席では、こちらが主導権を握り続けることが重要になります。"),
        ("edge_nigiru_08", "寒さでかじかんだ手をぎゅっと握りしめました。"),
        ("edge_nigiru_09", "マイクを握って登壇し、自社サービスのアーキテクチャについて発表しました。"),
        ("edge_nigiru_10", "焼きお握りの香ばしい醤油の匂いが部屋中に漂っています。"),

        # 11-20: 倒す（過労で卒倒、風邪で倒れる、将棋の駒を倒す、木を倒す、敵を倒す）
        ("edge_taosu_11", "連日の猛暑と過密スケジュールが重なり、同僚が過労で卒倒してしまいました。"),
        ("edge_taosu_12", "台風の強風によって、庭の植木鉢がいくつか倒れてしまいました。"),
        ("edge_taosu_13", "インフルエンザにかかり、高熱で丸三日ほどベッドに倒れ込んでいました。"),
        ("edge_taosu_14", "将棋の対局で、相手の王将を追い詰めて倒す手順を読み切りました。"),
        ("edge_taosu_15", "林業の現場では、周囲の安全を十分に確認してから大木を倒します。"),
        ("edge_taosu_16", "ドミノ倒しのように次々とタスクが完了していく爽快感があります。"),
        ("edge_taosu_17", "ゲームのボスキャラクターを倒すために、チームで戦略を練りました。"),
        ("edge_taosu_18", "地震の揺れで本棚が倒れないように、突っ張り棒で固定しました。"),
        ("edge_taosu_19", "自転車が風でバタバタと倒れてしまったので、スタンドを補強しました。"),
        ("edge_taosu_20", "ボウリングの練習を行い、狙い通りに最後のピンを倒すことができました。"),

        # 21-28: 溶かす（氷を溶かす、熱で金属を溶かす、砂糖を溶かす）
        ("edge_tokasu_21", "冬の朝に車のフロントガラスが凍結したため、ぬるま湯をかけて氷を溶かしました。"),
        ("edge_tokasu_22", "フライパンを弱火で温め、バターをゆっくりと溶かしていきます。"),
        ("edge_tokasu_23", "理科の実験で、ビーカーの水に食塩を入れてかき混ぜ、完全に溶かしました。"),
        ("edge_tokasu_24", "金属加工工場では、高温の炉で鉄を溶かして鋳型に流し込みます。"),
        ("edge_tokasu_25", "温かい紅茶に角砂糖をひとつ入れ、スプーンで溶かして飲みました。"),
        ("edge_tokasu_26", "チョコレートケーキを作るため、湯煎でクーベルチュールを溶かしました。"),
        ("edge_tokasu_27", "雪が積もった道路に融雪剤を散布し、路面の雪を溶かしてスリップを防ぎます。"),
        ("edge_tokasu_28", "ハンダゴテの熱でハンダを溶かし、基板の配線を丁寧に接続しました。"),

        # 29-36: 割る（卵の殻を割る、腹を割る、木を割る、ガラスが割れる）
        ("edge_waru_29", "ボウルに卵の殻を割って落とし、泡立て器で白身を切るように混ぜます。"),
        ("edge_waru_30", "チーム内の意見の食い違いを解消するため、全員で腹を割って本音で話し合いました。"),
        ("edge_waru_31", "薪割り用の斧を使い、乾燥した丸太を半分に力強く割りました。"),
        ("edge_waru_32", "作業中に手を滑らせて、お気に入りのガラスコップを割ってしまいました。"),
        ("edge_waru_33", "割り勘アプリを利用して、飲み会の会計を参加者の人数で均等に割りました。"),
        ("edge_waru_34", "すいか割りのイベントを行い、目隠しをした参加者を声で誘導しました。"),
        ("edge_waru_35", "硬いクルミの殻を割る専用の器具を使って、実を綺麗に取り出しました。"),
        ("edge_waru_36", "濃いめのウイスキーをソーダで割って、ハイボールを作りました。"),

        # 37-44: 壊れる（胃を壊す、お腹を壊す、時計が壊れる、機械が壊れる）
        ("edge_kowareru_37", "旅行先で冷たい水を飲みすぎてしまい、お腹を壊してしまいました。"),
        ("edge_kowareru_38", "長年愛用していた目覚まし時計の針が動かなくなり、ついに壊れてしまいました。"),
        ("edge_kowareru_39", "暴飲暴食が続いたせいで胃を壊してしまい、数日間はおかゆを食べて過ごしました。"),
        ("edge_kowareru_40", "工場の大型プレス機が壊れてしまい、修理エンジニアを緊急で呼びました。"),
        ("edge_kowareru_41", "スマートフォンの画面が壊れてタッチ操作を受け付けなくなったため、機種変更をしました。"),
        ("edge_kowareru_42", "プリンターの給紙ローラーが壊れたので、部品を取り寄せて自分で交換しました。"),
        ("edge_kowareru_43", "無理なスケジュールで働き続けると、体を壊してしまうので十分な睡眠を取りましょう。"),
        ("edge_kowareru_44", "古くなった自転車のブレーキワイヤーが壊れて外れてしまいました。"),

        # 45-48: 効く・渡す（薬が効く、バトンを渡す、書類を渡す、お茶を渡す）
        ("edge_kiku_45", "頭痛がひどかったので鎮痛薬を飲んだところ、30分ほどで薬が効いて楽になりました。"),
        ("edge_kiku_46", "冷房が効きすぎている部屋では、羽織るものを一枚用意しておくと快適です。"),
        ("edge_watasu_47", "リレー競技において、次の走者へスムーズにバトンを渡す練習を繰り返しました。"),
        ("edge_watasu_48", "受付で来客を確認し、担当者へ入館証と資料を手渡しで渡しました。")
    ]

    for name, content in edge_cases_data:
        path = os.path.join(EDGE_DIR, f"{name}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# 境界値検証: {name}\n\n{content}\n")

    print(f"Edge case docs created: {len(os.listdir(EDGE_DIR))} files.")


if __name__ == "__main__":
    setup_human_docs()
    setup_edge_cases()
