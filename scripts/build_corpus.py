#!/usr/bin/env python3
"""
初期検証用の文章を、実務8ジャンル×3種類の文体で生成するスクリプト。
実行すると既存コーパスのMarkdownを削除・再生成する。現行SKILLの実走検証には使わない。
生の出力24本、単語禁止の指示による出力24本、当時の推敲出力48本を生成する。
"""
import os
import sys
import subprocess
import concurrent.futures

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(BASE_DIR, "tests", "corpus")
RAW_DIR = os.path.join(CORPUS_DIR, "raw_ai")
BL_DIR = os.path.join(CORPUS_DIR, "blacklist_ai")
YOMI_DIR = os.path.join(CORPUS_DIR, "yomiyasu_rewritten")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(BL_DIR, exist_ok=True)
os.makedirs(YOMI_DIR, exist_ok=True)

TOPICS = [
    ("01_tech_arch", "非同期メッセージングキューを用いたマイクロサービスの耐障害性設計について、技術解説記事（400字程度）を書いてください。"),
    ("02_incident_report", "高負荷時にデータベースのコネクションプールが枯渇しAPIが504エラーを返したインシデントの障害報告書（400字程度）を作成してください。"),
    ("03_pr_description", "認証トークンのリフレッシュ処理を同期処理から非同期キューへリファクタリングしたPull Requestの説明文（400字程度）を作成してください。"),
    ("04_slack_announce", "今週末に実施予定のデータベース定期メンテナンスとそれに伴うサービス一時停止について、社内Slack向けのアナウンス文（400字程度）を作成してください。"),
    ("05_comparison", "自社サービスの次期API基盤選定において、REST APIとGraphQLを比較検討した技術選定メモ（400字程度）を作成してください。"),
    ("06_spec_draft", "外部決済プロバイダからのWebhook通知受信機能における、リトライ制御とデッドレターキュー（DLQ）の機能仕様書ドラフト（400字程度）を作成してください。"),
    ("07_code_review", "サービス層にDBアクセスや外部API呼び出しのビジネスロジックが混在しているコードに対する、責務分離を促すコードレビューのフィードバックコメント（400字程度）を作成してください。"),
    ("08_essay_retrospective", "開発チームの拡大に伴い、コードの属人化を防ぎドキュメント文化を定着させるための取り組みについての振り返りエッセイ（400字程度）を書いてください。")
]

VARIANTS = [
    ("sonnet_default", "sonnet", "あなたは一般的なWebエンジニアです。"),
    ("sonnet_formal", "sonnet", "あなたはエンタープライズシステムのシニアアーキテクトです。堅牢で形式的な文体で記述してください。"),
    ("sonnet_casual", "sonnet", "あなたはスタートアップのテックリードです。現場感のある開発者ブログのトーンで記述してください。")
]

RAW_PROMPT_PREFIX = "前置きや挨拶、メタコメント、改善ポイントなどの解説は一切含めず、指示された本文のみを出力してください。\n\n"
BLACKLIST_PROMPT_SUFFIX = "\n\n※注意：「手触り」「解像度」「地味に効く」「〜側に倒す」「静かに壊れる」「時間を溶かす」などのAIらしい表現は絶対に使わないでください。"

YOMIYASU_REWRITE_PROMPT = """以下の文章を「yomiyasu」の原則に従って推敲・書き直してください。
【推敲原則】
1. 統語構造（誰が/何を/どうした）を復元し、非生物主語（キューが、設計が）を行為者（開発者、システム管理者）の主語へ直す。
2. 比喩的動詞（「壊れる」「倒す」「溶かす」「効く」等）を字義通りの具体的な技術的処置や事象に開く。
3. サ変名詞の数珠つなぎ（過剰圧縮）を動詞述語の文へ戻す。
4. 内容の裏付けのない太字装飾を剥がし、不必要な箇条書きを地の文に統合する。
5. 「AではなくB」のような架空の二項対比を削り、肯定的事実を直接書く。
6. 絵文字、文末コロン（：）、不要な補足カッコを完全に排除する。
7. 日本語と英単語・数字の間の半角空白を詰める。

前置きや解説は一切出力せず、書き直した本文のみを出力してください。

【対象文章】
"""


def run_claude_prompt(prompt: str, system_prefix: str, model_alias: str = "sonnet") -> str:
    """Claude CLIで実行"""
    full_prompt = f"{system_prefix}\n\n{prompt}"
    cmd = ["claude", "-p", full_prompt, "--model", model_alias]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=True
        )
        out = res.stdout.strip()
        # メタコメントのクリーンアップ（もしあれば）
        if "---" in out and ("改善ポイント" in out or "文字数" in out):
            out = out.split("---")[0].strip()
        return out
    except Exception as e:
        print(f"Claude error ({model_alias}): {e}", file=sys.stderr)
        return ""


def generate_single_topic(item):
    key, prompt, var_name, model_alias, system_p = item
    raw_file = os.path.join(RAW_DIR, f"{key}_{var_name}.md")
    bl_file = os.path.join(BL_DIR, f"{key}_{var_name}.md")

    if not os.path.exists(raw_file):
        print(f"Generating Raw: {key}_{var_name}...")
        text = run_claude_prompt(RAW_PROMPT_PREFIX + prompt, system_p, model_alias)
        if text:
            with open(raw_file, "w", encoding="utf-8") as f:
                f.write(text)

    if not os.path.exists(bl_file):
        print(f"Generating Blacklist: {key}_{var_name}...")
        text = run_claude_prompt(RAW_PROMPT_PREFIX + prompt + BLACKLIST_PROMPT_SUFFIX, system_p, model_alias)
        if text:
            with open(bl_file, "w", encoding="utf-8") as f:
                f.write(text)

    return key, var_name


def rewrite_single_file(item):
    filename, src_dir, dest_filename = item
    dest_path = os.path.join(YOMI_DIR, dest_filename)
    if os.path.exists(dest_path):
        return dest_filename

    src_path = os.path.join(src_dir, filename)
    with open(src_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return None

    print(f"Rewriting: {dest_filename}...")
    rewritten = run_claude_prompt(YOMIYASU_REWRITE_PROMPT + content, "", "sonnet")
    if rewritten:
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(rewritten)
    return dest_filename


def main():
    # 生成先の既存Markdownを削除する。保存済みコーパスを使う検証では実行しない。
    for d in [RAW_DIR, BL_DIR, YOMI_DIR]:
        for f in os.listdir(d):
            if f.endswith(".md"):
                os.remove(os.path.join(d, f))

    tasks = []
    for key, prompt in TOPICS:
        for var_name, model_alias, system_p in VARIANTS:
            tasks.append((key, prompt, var_name, model_alias, system_p))

    print(f"=== Step 1: Generating Raw AI & Blacklist AI texts ({len(tasks)} topics x 2 = 48 files) ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(generate_single_topic, tasks))

    print(f"Raw AI count: {len(os.listdir(RAW_DIR))}")
    print(f"Blacklist AI count: {len(os.listdir(BL_DIR))}")

    print("\n=== Step 2: Generating Yomiyasu Rewritten texts (48 files) ===")
    rewrite_items = []
    for f in sorted(os.listdir(RAW_DIR)):
        if f.endswith(".md"):
            rewrite_items.append((f, RAW_DIR, f))
    for f in sorted(os.listdir(BL_DIR)):
        if f.endswith(".md"):
            name_parts = f.split(".")
            dest_name = f"{name_parts[0]}_bl.{name_parts[1]}"
            rewrite_items.append((f, BL_DIR, dest_name))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(rewrite_single_file, rewrite_items))

    print("\n=== All Finished ===")
    print(f"Raw AI: {len(os.listdir(RAW_DIR))} files")
    print(f"Blacklist AI: {len(os.listdir(BL_DIR))} files")
    print(f"Yomiyasu Rewritten: {len(os.listdir(YOMI_DIR))} files")


if __name__ == "__main__":
    main()
