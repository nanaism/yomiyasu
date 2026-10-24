"""確度・引用・文体の切り替えの設計例と、既存出力の契約。
例文は合成の文と公開の題材。比較用の値は固定し、試験中に旧版を読み込まない。
"""
from pathlib import Path
from unittest import mock
import json
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff as diff
sys.path.insert(0, str(ROOT / "tests"))
from portable import paced_limit, timing_clock  # noqa: E402

EXAMPLES = {'C1': ('来週の負荷試験で効果を検証する見込みです。\n', '来週の負荷試験で効果を検証する予定です。\n'),
 'C2': ('ジッターで緩和できると思われますが、負荷試験は来週実施する見込みです。\n', 'ジッターで緩和できると考えられますが、負荷試験は来週実施する予定です。\n'),
 'C3': ('アラート閾値は、運用データを見ながら調整することになると思われます。\n', 'アラート閾値は、運用データを見ながら調整することになります。\n'),
 'C4': ('結果は関連を示唆する。\n', '結果は関連を示す。\n'),
 'C5': ('メンテ明けは、キャッシュが温まるまで数分間レスポンスが遅くなると考えられます。\n', 'メンテナンス終了後は、キャッシュが温まるまで数分間、レスポンスが遅くなる可能性があります。\n'),
 'C6': ('次の四半期には、変更したコードと関連文書の更新漏れをCIで検知する仕組みを試す見込みだ。\n', '次の四半期には、変更したコードと関連する文書の更新漏れをCIで検出する仕組みの導入を検討している。\n'),
 'C7': ('ログの量は月ごとに増える。\n', 'ログの量は月ごとに増える傾向がある。\n'),
 'C8': ('Webhook通知を欠落なく処理する。\n', 'Webhook通知を確実に受け取る。\n'),
 'C9': ('一方、効果がはっきりしていないこともある。\n', '一方で、効果が不明確な点もある。\n'),
 'C10': ('保持期間は14日とする想定であり、監査要件次第では延長が必要になるかもしれません。\n', '保持期間は14日を予定していますが、監査の要件によっては延長が必要になる可能性があります。\n'),
 'N1': ('ただ、上限を上げるだけではDB側の接続数上限に先に到達するかもしれません。\n', 'ただし、上限を上げるだけではDB側の接続数上限に先に到達する可能性があります。\n'),
 'N2': ('プールサイズの暫定引き上げは、別の負荷問題を誘発するかもしれません。\n', 'プールサイズの暫定的な拡張は、別の負荷問題を誘発するおそれがあります。\n'),
 'N3': ('キャッシュの再構築が完了するまでの間、数十分程度は影響が続くと思われます。\n', 'キャッシュの再構築が完了するまでの数十分程度は、影響が続く見込みです。\n'),
 'N4': ('順序が逆転するイベントが発生する可能性があると考えられます。\n', '順序が逆転するイベントが発生する可能性があります。\n'),
 'N5': ('再発するかは五分五分と見ている。\n', '再発する見込みは半々と見ている。\n'),
 'N6': ('九分九厘、うまくいくと思っていた。\n', 'ほぼ確実に、うまくいくと思っていた。\n'),
 'N7': ('これから何を作る予定か？\n', 'これから何を作るか？\n'),
 'N8': ('本番での再試行の予定はありません。\n', '本番では再試行しません。\n'),
 'N9': ('業務データの更新とイベントの保存を同じDBトランザクションで確定し、別の処理がキューへ送る。\n', '業務データの更新とイベントの保存を同じDBトランザクションで確定する。\n'),
 'N10': ('配送は重複し得るため、検索側でバージョン比較を行う。\n', 'イベントは重複して届くことがあるため、検索側でバージョンを比較する。\n'),
 'N11': ('直接原因は、最大接続数が想定ピーク負荷に対して不足していたことである。\n', '直接の原因は、想定したピーク負荷に対して最大接続数が少なすぎたことである。\n'),
 'N12': ('原因は設定の誤りと考えられ、今週中に修正する予定です。\n', '原因は設定の誤りと考えられます。今週中に修正する予定です。\n'),
 'N13': ('原因は設定の誤りと考えられます。今週中に修正する予定です。\n', '原因は設定の誤りと考えられ、今週中に修正する予定です。\n'),
 'N14': ('品質ではなく、速度を優先する。\n', '速度を最優先にする。品質はおまけと考える。\n'),
 'N15': ('切り替え作業の日程が確定しましたので共有します。\n', '切り替え作業の日程が確定したので共有します。\n'),
 'N17': ('手順は `見込み` を `予定` にする。\n\n```\n見込み\n```\n', '手順は `予定` を `予定` にする。\n\n```\n予定\n```\n'),
 'Q1': ('まず着手したのは、PRテンプレートに「なぜこの変更をするのか」を必須項目として加えることだ。\n', 'まず取り組んだのは、PRテンプレートに「なぜこの変更を行うのか」を必須項目として加えることだ。\n'),
 'Q2': ('「明日の会議、延期できます？」\n', '「明日の会議を延期できますか？」\n'),
 'Q3': ('「行くの？」と母が聞いた。\n', '「行くの」と母が言った。\n'),
 'Q4a': ('「もっと短く！」と言われた。\n', '「もっと短く」と言われた。\n'),
 'Q4b': ('僕「...」\n', '僕「……」\n'),
 'Q5': ('プール上限は「とりあえず動く値」のまま放置しがちです。\n', 'プール上限は、とりあえず動く値のまま放置しがちです。\n'),
 'Q6': ('プール上限は「とりあえず動く値」のまま放置しがちです。\n', 'プール上限は暫定的な値のまま放置しがちです。\n'),
 'Q7': ('> 彼は「すぐ戻る」と言った。\n', '> 彼は「すぐに戻ります」と言った。\n'),
 'Q8': ('まず「型を書く」と決めた。\n\n次に進む。\n', '次に進む。\n\nまず「型を書く」と決めた。\n'),
 'Q9': ('設定は `「a」` のままにする。\n', '設定は `「b」` のままにする。\n'),
 'R1': ('今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n', '今日は晴れです。\n明日は雨が降ります。\n傘を持っていきます。\n帰りは遅くなります。\n'),
 'R2': ('今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなります。\n夕食は外で食べます。\n駅で待ちます。\n電話します。\n連絡します。\n',
        '今日は晴れです。\n明日は雨が降ります。\n傘を持っていきます。\n帰りは遅くなります。\n夕食は外で食べます。\n駅で待ちます。\n電話します。\n連絡します。\n'),
 'R3': ('今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n夕食は外で食べる。\n',
        '今日は晴れです。\n明日は雨が降ります。\n傘を持っていく。\n帰りは遅くなる。\n夕食は外で食べる。\n'),
 'R4': ('今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n夕食は外で食べる。\n駅で待つ。\n',
        '今日は晴れです。\n明日は雨が降ります。\n傘を持っていきます。\n帰りは遅くなる。\n夕食は外で食べる。\n駅で待つ。\n'),
 'R6': ('「それは無理だ」\n「明日やる」\n「先に帰る」\n', '「それは無理です」\n「明日やります」\n「先に帰ります」\n'),
 'R7': ('今日は晴れです。\n明日は雨が降ります。\n傘を持っていきます。\n帰りは遅くなります。\n', '今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n'),
 'N16': ('来週の負荷試験で効果を検証する見込みです。\n', '来週の負荷試験で効果を検証する見込みです。\n'),
 'R5': ('今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n', '今日は晴れです。\n明日は雨が降ります。\n傘を持っていきます。\n帰りは遅くなります。\n'),
 'R8': ('今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n', '今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n'),
 'R9': ('今日は晴れだ。\n明日は雨が降る。\n傘を持っていく。\n帰りは遅くなる。\n', '今日は晴れです。\n明日は雨が降ります。\n傘を持っていきます。\n帰りは遅くなります。\n')}

NINE_BASELINE = {'C1': {'markers': [],
        'new_words': ['予定'],
        'lost_words': ['見込'],
        'structure': [],
        'spans': [{'added': '予定',
                   'was': '見込み',
                   'kinds': [],
                   'new_words': ['予定'],
                   'where': '来週の負荷試験で効果を検証する［予定］です。'}],
        'logic': [],
        'bold': [],
        'endings': {'stance': None, 'changes': [], 'flags': [], 'orig_flags': []},
        'type_changes': []},
 'Q1': {'markers': [],
        'new_words': [],
        'lost_words': ['着手'],
        'structure': [],
        'spans': [{'added': '取り組んだ',
                   'was': '着手した',
                   'kinds': ['つなぎ'],
                   'new_words': [],
                   'where': 'まず［取り組んだ］のは、PRテンプレートに「なぜこの変'}],
        'logic': [],
        'bold': [],
        'endings': {'stance': None, 'changes': [], 'flags': [], 'orig_flags': []},
        'type_changes': []},
 'R1': {'markers': [],
        'new_words': [],
        'lost_words': [],
        'structure': [],
        'spans': [],
        'logic': [],
        'bold': [],
        'endings': {'stance': None,
                    'changes': [{'orig': '今日は晴れだ。',
                                 'orig_kind': '常体',
                                 'rewrite': '今日は晴れです。',
                                 'rewrite_kind': '断定（〜です）'},
                                {'orig': '明日は雨が降る。',
                                 'orig_kind': '常体',
                                 'rewrite': '明日は雨が降ります。',
                                 'rewrite_kind': '動作（〜します）'},
                                {'orig': '傘を持っていく。',
                                 'orig_kind': '常体',
                                 'rewrite': '傘を持っていきます。',
                                 'rewrite_kind': '動作（〜します）'},
                                {'orig': '帰りは遅くなる。',
                                 'orig_kind': '常体',
                                 'rewrite': '帰りは遅くなります。',
                                 'rewrite_kind': '説明（〜ます）'}],
                    'flags': [],
                    'orig_flags': []},
        'type_changes': []}}

REPORT_BASELINE = {'N15': ['状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 1か所）',
         '■ 全文差分（変更 1か所。省略していません）',
         '状態: 変更はあるが、専用の規則に当たる見直し候補はない（変更 1か所）'],
 'N16': ['状態: 変更なし', '■ 全文差分: 変わった箇所はありません。', '状態: 変更なし'],
 'N17': ['状態: 変更あり（2か所）。見直し候補 3件、うち意味が変わる恐れ 2件',
         '■ 意味が変わる恐れ（2件。原文と資料に照らして確かめる）',
         '■ 規則の見直し候補（1件）',
         '■ 消えた語: 見込',
         '■ 全文差分（変更 2か所。省略していません）',
         '状態: 変更あり（2か所）。見直し候補 3件、うち意味が変わる恐れ 2件']}


def risks(result, *kinds):
    return [r for r in result['meaning_risks'] if r['kind'] in kinds]


class DesignExamples(unittest.TestCase):
    def check_example(self, tag):
        options = {'doc_type': 'mail'} if tag == 'R5' else {'reader': 'general'} if tag == 'R9' else {}
        result = diff.diff(*EXAMPLES[tag], **options)
        certainty = risks(result, 'certainty', 'certainty_review')
        quotes = risks(result, 'quote')
        section = result['register']
        if tag.startswith('C'):
            expected = {
                'C1': ('certainty', 'strengthened', '見込み', '予定'),
                'C2': ('certainty', 'strengthened', '見込み', '予定'),
                'C4': ('certainty', 'strengthened', '示唆', '断定'),
                'C5': ('certainty_review', 'weakened', 'と考えられる', '可能性'),
                'C6': ('certainty_review', 'weakened', '見込み', '検討'),
                'C7': ('certainty_review', 'weakened', '断定', '傾向'),
                'C8': ('certainty_review', 'strengthened', '断定', '確実'),
                'C9': ('certainty_review', 'strengthened', 'ことがある', '断定'),
                'C10': ('certainty', 'strengthened', '想定', '予定'),
            }
            if tag == 'C3':
                self.assertEqual(certainty, [])
                marks = risks(result, 'sentence_type')
                self.assertEqual(len(marks), 1)
                self.assertEqual(marks[0]['subkind'], 'marks')
            else:
                kind, subkind, before, after = expected[tag]
                self.assertEqual(len(certainty), 1)
                item = certainty[0]
                self.assertEqual((item['kind'], item['subkind']), (kind, subkind))
                self.assertEqual(len(item['detail']['steps']), 1)
                step = item['detail']['steps'][0]
                self.assertEqual((step['from'], step['to']), (before, after))
                self.assertEqual(step['counted'], kind == 'certainty')
                self.assertFalse(item['detail']['mixed'])
                self.assertEqual(item['basis'], None)
                self.assertEqual((item['old_line'], item['new_line']), (1, 1))
                self.assertEqual(result['fail_on_meaning_risk_count'], int(kind == 'certainty'))
            self.assertEqual(result['hedges']['candidate_count'], 0)
        elif tag.startswith('N'):
            self.assertEqual(certainty, [])
            if tag in ('N2', 'N3'):
                # 同じ強さへの言い換えは、意味が変わる恐れには数えない。
                self.assertEqual(risks(result, 'sentence_type'), [])
                self.assertEqual(result['fail_on_meaning_risk_count'], 0)
        elif tag.startswith('Q'):
            expected = {'Q1': 'changed', 'Q2': 'changed', 'Q3': 'changed', 'Q6': 'lost'}
            self.assertEqual([r['subkind'] for r in quotes], [expected[tag]] if tag in expected else [])
            self.assertEqual(diff.fail_on_count(quotes), 0)
            if quotes:
                detail = quotes[0]['detail']
                self.assertEqual(detail['dialogue'], tag == 'Q2')
                self.assertEqual(detail['bracket'], '「」')
                self.assertTrue(detail['old_quote'])
                self.assertEqual(detail['new_quote'] is None, tag == 'Q6')
                self.assertIn('かぎかっこの中の言葉', diff.report(result))
            if tag == 'Q7':
                self.assertTrue([r for r in risks(result, 'protected') if r['subkind'] == 'quote'])
        else:
            expected = tag in ('R1', 'R2', 'R4', 'R7', 'R9')
            self.assertEqual(section['candidate_count'], int(expected))
            self.assertEqual(section['threshold'], {'min_sentences': 3, 'min_ratio': 0.5})
            self.assertEqual(section['skipped_by'], 'politeness' if tag == 'R5' else None)
            self.assertEqual(list(result)[-2:], ['register', 'added_actors'])
            if expected:
                item = section['candidates'][0]
                self.assertEqual(item['subkind'], 'to_plain' if tag == 'R7' else 'to_polite')
                self.assertEqual(item['detail']['pattern'], 'unified' if tag == 'R2' else 'switched')
                self.assertEqual(item['detail']['switched'], 3 if tag in ('R2', 'R4') else 4)
                self.assertEqual(item['level'], 'review')
                self.assertLessEqual(len(item['detail']['lines']), 5)
                self.assertIn('読み手に合わせて意図して変えたなら残し、「変えたところ」に書いてください。', diff.report(result))
            if tag == 'R6':
                self.assertEqual(len(quotes), 3)
            if tag == 'R9':
                self.assertEqual(section, diff.diff(*EXAMPLES['R1'])['register'])


# 各設計例を独立した試験として表示する。
def example_test(tag):
    def test(self):
        self.check_example(tag)
    if tag == 'C10':
        test.__doc__ = '仕様書の想定は予定に近い用法もあるが、強さ2→3として数える。文の別の節の同じ強さは打ち消す。'
    elif tag == 'Q6':
        test.__doc__ = '強調と引用は形だけでは分けられないため候補に残すが、--fail-on には数えない。'
    return test


for _tag in EXAMPLES:
    setattr(DesignExamples, 'test_' + _tag, example_test(_tag))


class Contracts(unittest.TestCase):
    def test_quote_details_and_nested_brackets(self):
        item = risks(diff.diff(*EXAMPLES['Q1']), 'quote')[0]
        self.assertEqual(item['detail']['old_quote'], 'なぜこの変更をするのか')
        self.assertEqual(item['detail']['new_quote'], 'なぜこの変更を行うのか')
        old, new = [s.replace('「', '『「').replace('」', '」』') for s in EXAMPLES['Q1']]
        self.assertEqual({r['detail']['bracket'] for r in risks(diff.diff(old, new), 'quote')}, {'「」', '『』'})

    def test_register_excludes_quote_blocks_and_has_document_counts(self):
        old, new = EXAMPLES['R1']
        quoted = ['\n'.join('> ' + line for line in text.splitlines()) for text in (old, new)]
        self.assertEqual(diff.diff(*quoted)['register']['candidate_count'], 0)
        detail = diff.diff(old, new)['register']['candidates'][0]['detail']
        self.assertEqual(detail['old_counts'], {'plain': 4, 'polite': 0})
        self.assertEqual(detail['new_counts'], {'plain': 0, 'polite': 4})
        self.assertEqual(detail['lines'], [[1, 1], [2, 2], [3, 3], [4, 4]])

    def test_review_strengthening_suppresses_custom_hedge(self):
        with mock.patch.dict(diff._LIST_CACHE, {'hedges': (['こともある'], 'builtin')}):
            result = diff.diff(*EXAMPLES['C9'])
        self.assertEqual(result['hedges']['candidate_count'], 0)
        self.assertEqual(risks(result, 'certainty_review')[0]['subkind'], 'strengthened')

    def test_nine_keys_and_register_counts(self):
        for tag, expected in NINE_BASELINE.items():
            with self.subTest(tag=tag):
                result = diff.diff(*EXAMPLES[tag])
                self.assertEqual({key: result[key] for key in expected}, expected)
                self.assertEqual(list(result)[-2:], ['register', 'added_actors'])
                if tag == 'R1':
                    self.assertEqual(result['fail_on_meaning_risk_count'], 0)
                    with mock.patch.object(diff, '_register_changes', return_value=diff._review_section([])):
                        without = diff.diff(*EXAMPLES[tag])
                    self.assertEqual(result['candidate_count'], without['candidate_count'])
                    self.assertEqual(result['status'], without['status'])

    def test_existing_risks_keep_order_and_contents(self):
        for tag in EXAMPLES:
            with self.subTest(tag=tag):
                result = diff.diff(*EXAMPLES[tag])
                with mock.patch.object(diff, '_certainty_risks', return_value=[]), mock.patch.object(diff, '_quote_risks', return_value=[]):
                    before = diff.diff(*EXAMPLES[tag])['meaning_risks']
                self.assertEqual(result['meaning_risks'][:len(before)], before)
                added = result['meaning_risks'][len(before):]
                self.assertTrue(all(r['kind'] in ('certainty', 'certainty_review', 'quote') for r in added))

    def test_fixed_report_lines_without_new_candidates(self):
        for tag, expected in REPORT_BASELINE.items():
            with self.subTest(tag=tag):
                result = diff.diff(*EXAMPLES[tag])
                lines = diff.report(result).splitlines()
                self.assertEqual([line for line in lines if line.startswith(('状態:', '■ '))], expected)
                self.assertEqual(lines[0], '差分の検査を実行しました。')

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / 'old.md', Path(folder) / 'new.md'
            for tag in ('C1', 'C5', 'C8', 'Q1', 'R1'):
                old.write_bytes(EXAMPLES[tag][0].encode('utf-8'))
                new.write_bytes(EXAMPLES[tag][1].encode('utf-8'))
                for flag in ([], ['--fail-on=meaning-risk']):
                    with self.subTest(tag=tag, flag=flag):
                        run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/yomiyasu_diff.py'),
                                              *flag, str(old), str(new)], capture_output=True, text=True, encoding='utf-8')
                        self.assertEqual(run.returncode, int(tag == 'C1' and bool(flag)), run.stderr)

    def test_fail_on_line_only_mentions_certainty_when_counted(self):
        counted = risks(diff.diff(*EXAMPLES['C1']), 'certainty')
        self.assertIn('文の種類・確度 1件', diff._fail_on_line(2, 1, counted))
        self.assertNotIn('・確度', diff._fail_on_line(2, 1))

    def test_review_examples_do_not_fail(self):
        # 強調の言い換え、多い文体への統一、確定の活用だけの変更。
        for tag in ('Q6', 'R2', 'N15'):
            self.assertEqual(diff.diff(*EXAMPLES[tag])['fail_on_meaning_risk_count'], 0)

    def test_mirrors(self):
        for relative in ('scripts/yomiyasu_diff.py', 'scripts/yomiyasu_check.py', 'references/review-points.md'):
            self.assertEqual((ROOT / relative).read_bytes(), (ROOT / 'skills/yomiyasu' / relative).read_bytes())

    def test_new_detectors_full_rewrite_speed(self):
        # 6万字の全面書き換えで、確度・かぎかっこ・文体の検査を動かす。壁時計の決まった秒数だけで見ると、実装が同じでも遅い機械で
        # 落ちるので、test_v200_diff_full の性能の試験と同じく2つを見る。1つ目は、4分の1の大きさからの時間の伸び（8倍未満。
        # 大きさの2乗で伸びる処理なら約16倍）。2つ目は、0.3秒の上限を、基準の処理（test_v200_diff_full の pace）の遅さの比で
        # 延ばした値。時間は CPU 時間で測る（Windows は刻みが粗いので壁時計）。
        clock = time.perf_counter if sys.platform == "win32" else time.process_time
        source = (ROOT / "tests" / "test_v200_diff_full.py").read_text(encoding="utf-8")
        pace_seconds = float(re.search(r"^PACE_SECONDS = ([0-9.]+)$", source, re.M).group(1))
        start = source.index("# pace は yomiyasu を使わない")
        end = source.index("\ndef sample(", start)
        namespace = {}
        exec(compile("import difflib\nimport re\nfrom bisect import bisect_left\nfrom collections import Counter\n"
                     + source[start:end], "pace", "exec"), namespace)

        def best_time(work):
            times = []
            for _ in range(3):
                started = clock()
                work()
                times.append(clock() - started)
            return min(times)

        def detectors(size):
            old, new = EXAMPLES['C2']
            repeats = size // min(len(old), len(new)) + 1
            full, sides = diff._build_full_diff(old * repeats, new * repeats, None)
            groups = diff._sentence_pairs(sides, full)

            def work():
                diff._certainty_risks(sides, groups, [])
                diff._quote_risks(sides, groups)
                diff._register_changes(sides, groups, {})
            return best_time(work)

        quarter, whole = detectors(15000), detectors(60000)
        scale = max(1.0, best_time(namespace["pace"]) / pace_seconds)
        detail = "%.3f秒（4分の1の大きさで %.4f秒）。上限 %.3f秒（0.3秒 × この機械の遅さ %.2f）" % (whole, quarter, 0.3 * scale, scale)
        self.assertLess(whole, 0.3 * scale, detail)
        self.assertLess(whole, 8 * quarter, "文書を4倍にすると時間が8倍以上に伸びる（大きさの2乗で伸びる処理の疑い）\n" + detail)


class ReviewFixes(unittest.TestCase):
    """反証で見つけた形（合成の文）。"""

    def certainty(self, old, new):
        return risks(diff.diff(old + '\n', new + '\n'), 'certainty', 'certainty_review')

    def test_noun_yotei_and_mikomi_are_not_certainty(self):
        for old, new in (('会議の予定を調整します。', '会議の日程を調整します。'), ('予定表を確認します。', '日程表を確認します。'),
                         ('予定日を過ぎても連絡がない。', '期日を過ぎても連絡がない。'), ('リリース予定日は10日です。', 'リリース日は10日です。'),
                         ('見込み客に連絡します。', '潜在顧客に連絡します。'), ('売上の見込みを立てます。', '売上の予測を立てます。')):
            with self.subTest(old=old):
                self.assertEqual(self.certainty(old, new), [])
        # 述語の「予定」「見込み」は今までどおり見る
        self.assertEqual(self.certainty('29日にレビューの予定です。', '29日にレビューします。')[0]['subkind'], 'strengthened')
        self.assertEqual(self.certainty('回復の見込みです。', '回復します。')[0]['kind'], 'certainty')

    def test_hedges_outside_the_old_table_keep_the_level(self):
        for new in ('費用が減りそうです。', '費用が減ると予測しています。', '費用が減ると推定しています。', '費用が減ると期待しています。',
                    '費用が減る公算が大きいです。', '費用が減ると考えております。', '費用が減りかねません。'):
            with self.subTest(new=new):
                found = self.certainty('費用が減る見込みです。', new)
                self.assertFalse([r for r in found if r['kind'] == 'certainty'], found)
        self.assertEqual(self.certainty('来週に復旧する予定です。', '来週に復旧する計画があります。'), [])
        self.assertEqual(self.certainty('停止する可能性が高い。', '停止する見込みです。'), [])

    def test_plan_to_assertion_is_review_only(self):
        result = diff.diff('設計を見直す予定です。\n', '設計を見直します。\n')
        self.assertEqual([(r['kind'], r['subkind']) for r in risks(result, 'certainty', 'certainty_review')],
                         [('certainty_review', 'strengthened')])
        self.assertEqual(result['fail_on_meaning_risk_count'], 0)
        self.assertIn('確度が強まった恐れ（数えない変化）', diff.report(result))

    def test_inflections(self):
        self.assertEqual(self.certainty('復旧するとは限らない。', '復旧するとは限りません。'), [])
        self.assertEqual(self.certainty('変更が入るケースがあります。', '変更が入ることがあります。'), [])
        self.assertEqual(self.certainty('褒められることもありました。', '褒められることもあった。'), [])

    def test_cancelled_core_word_is_not_borrowed(self):
        found = self.certainty('再発の可能性があり、点検することがある。', '再発の可能性があり、点検する予定です。')
        self.assertEqual([(r['kind'], r['subkind']) for r in found], [('certainty_review', 'strengthened')])

    def test_negated_clause_does_not_hide_other_clause(self):
        kind, direction, detail = diff._certainty_change('再発する可能性があるが、導入する予定はない。', '再発するが、導入する予定はない。')
        self.assertEqual((kind, direction), ('certainty', 'strengthened'))
        self.assertIsNone(diff._certainty_change('可能性は低い。', '可能性が高い。'))

    def test_neighbor_words_are_used_once(self):
        found = self.certainty('サーバーは停止する見込みです。回線も切れる見込みです。',
                               'サーバーは停止します。明日は晴れる見込みです。回線も切れます。')
        self.assertEqual([r['kind'] for r in found], ['certainty'])

    def quotes(self, old, new):
        return risks(diff.diff(old + '\n', new + '\n'), 'quote')

    def test_quotes_with_inner_periods_and_local_matching(self):
        for old, new in (('「うん。うん。そう。」と彼はうなずいた。', '「うん、そうだね」と彼はうなずいた。'),
                         ('「そうだ。行こう」と彼は言った。', '「そうだね、行こう」と彼は言った。'),
                         ('彼は「必要」と答えた。', '彼は「不必要」と答えた。'),
                         ('甲は「賛成」と答えた。乙も「賛成」と答えた。', '甲は「反対」と答えた。乙も「賛成」と答えた。'),
                         ('彼は「はい」と答えた。\n\n妻も「はい」と言った。', '彼は「いいえ」と答えた。\n\n妻もはいと言った。'),
                         ('「承認」ボタンを押す。', '「承認する」ボタンを押す。'),
                         ('「行く」と言った。', '「行かない」と言った。'),
                         ('「ビール」を買う。', '「ビル」を買う。'),
                         ('「外の「内側」を守れ」と言った。', '「外の「内側」を壊せ」と言った。')):
            with self.subTest(old=old):
                found = self.quotes(old, new)
                self.assertEqual([r['subkind'] for r in found], ['changed'])
                self.assertEqual(diff.fail_on_count(found), 0)

    def test_dialogue_lines_in_double_brackets_are_not_register(self):
        for old, new in (('『今日は晴れだ』\n『明日は雨が降る』\n『傘を持っていく』', '『今日は晴れです』\n『明日は雨が降ります』\n『傘を持っていきます』'),
                         ('「今日は晴れだ」。\n「明日は雨が降る」。\n「傘を持っていく」。', '「今日は晴れです」。\n「明日は雨が降ります」。\n「傘を持っていきます」。')):
            with self.subTest(old=old):
                self.assertEqual(diff.diff(old + '\n', new + '\n')['register']['candidate_count'], 0)

    def test_register_reads_kanji_kudasai_as_polite(self):
        result = diff.diff('確認して下さい。保存して下さい。終了して下さい。\n', '確認してください。保存してください。終了してください。\n')
        self.assertEqual(result['register']['candidate_count'], 0)

    def test_register_counts_merged_sentences(self):
        result = diff.diff('設定を開く。保存を押す。画面を閉じる。\n', '設定を開き、保存を押して画面を閉じます。\n')
        item = result['register']['candidates'][0]
        self.assertEqual((item['subkind'], item['detail']['switched']), ('to_polite', 3))
        # 文を消しただけ（中身が残らない）なら数えない
        result = diff.diff('設定を開く。保存を押す。画面を閉じる。\n', '設定を開きます。\n')
        self.assertEqual(result['register']['candidate_count'], 0)

    def test_quote_speed_with_many_unpaired_dialogue_lines(self):
        old = ''.join('「今日は{}番目の話をしようか」と太郎は言った。\n'.format(i) for i in range(400))
        new = ''.join('「まったく別の{}話だね」と花子が笑って返事をした。\n'.format(i * 7) for i in range(400))
        full, sides = diff._build_full_diff(old, new, None)
        groups = diff._sentence_pairs(sides, full)
        clock = timing_clock()
        durations = []
        for _ in range(3):
            start = clock()
            diff._quote_risks(sides, groups)
            durations.append(clock() - start)
        limit, detail = paced_limit(0.3, sorted(durations)[1])
        self.assertLess(sorted(durations)[1], limit, "{} {}".format(detail, durations))


sys.path.insert(0, str(ROOT / 'tests'))
from test_v200_check import CheckCase


class CheckRegister(CheckCase):
    def test_check_counts_certainty(self):
        old = self.write('old.md', EXAMPLES['C1'][0])
        new = self.write('new.md', EXAMPLES['C1'][1])
        result = self.check_json('run', '--source', old, '--final', new, '--fail-on', 'meaning-risk', code=1)
        self.assertEqual(result['fail_on_meaning_risk_count'], 1)
        self.assertTrue(result['fail_on_hit'])

    def test_run_line_and_record(self):
        old, new, lines = self.run_pair(*EXAMPLES['R1'])
        self.assertIn('文体の検査: 候補1件', lines)
        self.assertIn('■ 文体の切り替え（見直し候補 1件）', lines)
        path, record = self.record_from(lines)
        summary = self.check_entry(record, 'diff')['summary']
        self.assertEqual(summary['register_candidate_count'], 1)
        self.assertEqual(summary['register_review_count'], 1)
        self.assertEqual(summary['register_level'], 'review')
        self.assertEqual(self.check('verify', '--final', new).returncode, 0)

    def test_json_and_no_candidate_line(self):
        old = self.write('old.md', EXAMPLES['R1'][0])
        new = self.write('new.md', EXAMPLES['R1'][1])
        result = self.check_json('run', '--source', old, '--final', new)
        self.assertNotIn('register_check', result)
        self.assertEqual(result['diff']['register']['candidate_count'], 1)
        _, _, lines = self.run_pair(*EXAMPLES['N15'], names=('a.md', 'b.md'))
        self.assertFalse(any(line.startswith('文体の検査:') for line in lines))


if __name__ == '__main__':
    unittest.main()
