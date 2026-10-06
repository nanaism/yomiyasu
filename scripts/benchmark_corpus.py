#!/usr/bin/env python3
"""
保存済みコーパスに対し、単純な正規表現とyomiyasu_lint.pyの検出件数・スコアを集計する。
検出件数の比は精度や誤検出率ではない。実行するとbenchmark_results.jsonを上書きする。
"""
import os
import sys
import re
import json
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(BASE_DIR, "tests", "corpus")
RESULTS_PATH = os.path.join(CORPUS_DIR, "benchmark_results.json")

# yomiyasu_lint から関数をインポート
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
from yomiyasu_lint import lint_text


# 単純なキーワードマッチ（Lookaroundなしのナイーブ版正規表現）
NAIVE_PATTERNS = [
    ("壊れる", r"壊(?:れる|れ|れず)"),
    ("倒す", r"倒(?:す|し|さ)"),
    ("溶かす", r"溶(?:かす|かし|かさ)"),
    ("握る", r"握(?:る|り|っ|ら)"),
    ("割る", r"割(?:る|り|っ|ら)"),
    ("効く", r"効(?:く|き|い)"),
    ("渡す", r"渡(?:す|し|さ)"),
    ("潜る", r"潜(?:る|り|っ|ら)"),
    ("寄せる", r"寄(?:せる|せ|せな)"),
    ("逃がす", r"逃(?:がす|がし|がさ)"),
    ("潰す", r"潰(?:す|し|さ)"),
    ("走る", r"走(?:る|り|っ|ら)"),
]


def run_naive_lint(text: str):
    """Lookaroundなしの単純正規表現での検出件数をカウント"""
    total_matches = 0
    match_details = []
    lines = text.split("\n")
    for idx, line in enumerate(lines, 1):
        for name, pat in NAIVE_PATTERNS:
            found = re.findall(pat, line)
            if found:
                total_matches += len(found)
                match_details.append((idx, name, line.strip()))
    return total_matches, match_details


def benchmark_corpus():
    groups = {
        "human": os.path.join(CORPUS_DIR, "human"),
        "edge_cases": os.path.join(CORPUS_DIR, "edge_cases"),
        "raw_ai": os.path.join(CORPUS_DIR, "raw_ai"),
        "blacklist_ai": os.path.join(CORPUS_DIR, "blacklist_ai"),
        "yomiyasu_rewritten": os.path.join(CORPUS_DIR, "yomiyasu_rewritten"),
    }

    results = {}
    summary = {}

    total_files = 0
    for gname, gpath in groups.items():
        if not os.path.exists(gpath):
            continue
        files = [f for f in sorted(os.listdir(gpath)) if f.endswith(".md")]
        total_files += len(files)
        results[gname] = []

        g_naive_matches = 0
        g_lookaround_findings = 0
        g_scores = []
        g_metaphor_verbs = 0
        g_symbols = 0
        g_formatting = 0

        for f in files:
            fpath = os.path.join(gpath, f)
            with open(fpath, "r", encoding="utf-8") as fp:
                content = fp.read()

            naive_count, _ = run_naive_lint(content)
            res = lint_text(content)

            g_naive_matches += naive_count
            g_lookaround_findings += len(res["findings"])
            g_scores.append(res["score"])

            for finding in res["findings"]:
                rule = finding.get("rule", "")
                if "metaphor_verb" in rule:
                    g_metaphor_verbs += 1
                elif rule in {"trailing_colon", "redundant_bracket", "emoji_prohibited"}:
                    g_symbols += 1
                elif rule in {"excess_bold", "excess_list", "negative_parallelism"}:
                    g_formatting += 1

            results[gname].append({
                "file": f,
                "naive_matches": naive_count,
                "lookaround_findings": len(res["findings"]),
                "score": res["score"],
                "char_count": res.get("metrics", {}).get("char_count", len(content))
            })

        avg_score = round(sum(g_scores) / len(g_scores), 1) if g_scores else 0
        summary[gname] = {
            "file_count": len(files),
            "avg_score": avg_score,
            "total_naive_matches": g_naive_matches,
            "total_lookaround_findings": g_lookaround_findings,
            "metaphor_verbs": g_metaphor_verbs,
            "symbols": g_symbols,
            "formatting": g_formatting
        }

    out_data = {
        "total_files": total_files,
        "summary": summary,
        "details": results
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as fp:
        json.dump(out_data, fp, ensure_ascii=False, indent=2)

    print("\n" + "="*70)
    print(f"コーパスの検出件数とスコア (対象ファイル数: {total_files}本)")
    print("="*70)
    print(f"{'グループ':<20} | {'本数':<5} | {'平均点':<6} | {'単純一致件数':<10} | {'リンター指摘件数':<14} | {'件数減少率':<10}")
    print("-" * 75)

    for gname, s in summary.items():
        naive = s["total_naive_matches"]
        look = s["total_lookaround_findings"]
        reduction = f"{(1 - look/naive)*100:.1f}%" if naive > 0 else "N/A"
        print(f"{gname:<20} | {s['file_count']:<5} | {s['avg_score']:<6} | {naive:<10} | {look:<14} | {reduction:<10}")

    print("\n" + "="*70)
    print(f"詳細結果を保存しました: {RESULTS_PATH}")
    return out_data


if __name__ == "__main__":
    benchmark_corpus()
