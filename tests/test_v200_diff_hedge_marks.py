"""推量の印の同じ強さへの言い換えと、確度への引き継ぎの契約。
例文と比較値は固定し、試験中に旧版を読み込まない。
"""
from pathlib import Path
from unittest import mock
import json
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yomiyasu_diff as diff

EXAMPLES = {'S1': ('プールサイズの暫定引き上げは、別の負荷問題を誘発するかもしれません。\n', 'プールサイズの暫定的な拡張は、別の負荷問題を誘発するおそれがあります。\n'),
 'S2': ('キャッシュの再構築が完了するまでの間、数十分程度は影響が続くと思われます。\n', 'キャッシュの再構築が完了するまでの数十分程度は、影響が続く見込みです。\n'),
 'S3': ('コードと乖離した文書が増えれば、かえって誤解を招く可能性がある。\n', 'コードと乖離した文書が増えれば、かえって誤解を招くリスクがある。\n'),
 'S4': ('外部APIの応答が遅延した場合、コネクションプールの枯渇を招く恐れがあります。\n', '外部APIの応答が遅延した場合、コネクションプールの枯渇を招く可能性があります。\n'),
 'S5': ('この記録は古いイベントを再送しうる期間中は保持する。\n', 'この記録は、古いイベントが再送される可能性がある間は保持する。\n'),
 'S6': ('そのため、停止は90分前後に収まる見込みですが、2時間の枠を超えるかもしれません。\n', 'そのため、停止時間は90分程度を見込んでいますが、2時間の枠を超える可能性もあります。\n'),
 'S7': ('また、再開直後は一部の画面でレスポンスが低下すると考えられます。\n', 'また、再開直後は一部の画面でレスポンスが低下することが予想されます。\n'),
 'S8': ('早めに境界を引いておいた方が後が楽になる見込みです。\n', '早期に境界を明確にしておくことで、後々の対応がスムーズになると考えられます。\n'),
 'S9': ('この変更は別の負荷問題を誘発するかもしれない。\n', 'この変更は別の負荷問題を誘発するおそれがある。\n'),
 'U1': ('うまく機能すれば、レビューの負担も下がるかもしれない。\n', 'うまく機能すれば、レビュー負荷の軽減が期待できます。\n'),
 'U2': ('原因は設定の誤りかもしれません。\n', '原因は設定の誤りと見込んでいます。\n'),
 'U3': ('影響が続くかもしれませんが、来週検証する見込みです。\n', '影響が続く恐れがありますが、来週検証する予定です。\n'),
 'U4': ('たとえば「購買計画」。何かを買う計画なんだろうな、という見当はつきます。\nでも会議では、その言葉が単体で問われることはありません。\n',
        'たとえば「購買計画」。購買に関する計画であるとの推測は可能です。\nしかし会議においては、当該用語単独での意味の確認が行われることはありません。\n'),
 'K1': ('原因は設定ミスかもしれない。\n', '原因は設定ミスだ。\n'),
 'K2': ('アラート閾値は、運用データを見ながら調整することになると思われます。\n', 'アラート閾値は、運用データを見ながら調整することになります。\n'),
 'K3': ('明日は晴れる。\n', '明日は晴れるでしょう。\n'),
 'K4': ('影響が続くと思われます。\n', '影響が続く恐れがあります。\n'),
 'K5': ('影響が続く見込みです。\n', '影響が続くかもしれません。\n'),
 'K6': ('なお、順序保証が必要な処理では、パーティション設計がボトルネックになる可能性があると考えられます。\n',
        'なお、順序保証が求められる処理においては、パーティション設計がボトルネックとなる可能性が考えられます。\n'),
 'K7': ('ワーカー数は現状の見積もりで足りると考えられますが、実測はしていません。\n', 'ワーカー数は現状の見積もりで足りると考えていますが、実測はしていません。\n'),
 'K8': ('問題ないのではないですか？\n', '問題ないのではないでしょうか？\n'),
 'K9': ('原因は設定のようだ。\n', '原因は設定の恐れがある。\n'),
 'K10': ('明日は雨が降るかもしれない。\n', '明日は雨が降る可能性は低い。\n'),
 'K11': ('負荷が上がるとプール枯渇につながるかもしれません。\n', '負荷が増大すると、コネクションプールの枯渇につながるリスクが考えられます。\n'),
 'S10': ('プールサイズの暫定引き上げは、別の負荷問題を誘発するかもしれません。\n\n原因は設定ミスかもしれない。\n',
         'プールサイズの暫定的な拡張は、別の負荷問題を誘発するおそれがあります。\n\n原因は設定ミスだ。\n'),
 'mixed': ('遅れるかもしれず、止まるかもしれない。\n', '遅れる見込みで、止まる。\n')}

NINE_BASELINE = {'S1': {'markers': [],
        'new_words': ['拡張', '暫定的'],
        'lost_words': ['暫定引'],
        'structure': [],
        'spans': [{'added': '的な拡張',
                   'was': '引き上げ',
                   'kinds': [],
                   'new_words': ['拡張'],
                   'where': 'プールサイズの暫定［的な拡張］は、別の負荷問題を誘発するおそれがあ'},
                  {'added': 'おそ',
                   'was': 'かもし',
                   'kinds': ['推量'],
                   'new_words': [],
                   'where': '定的な拡張は、別の負荷問題を誘発する［おそ］れがあります。'},
                  {'added': 'があり',
                   'was': '',
                   'kinds': ['推量'],
                   'new_words': [],
                   'where': '拡張は、別の負荷問題を誘発するおそれ［があり］ます。'}],
        'logic': [],
        'bold': [],
        'endings': {'stance': None,
                    'changes': [{'orig': 'プールサイズの暫定引き上げは、別の負荷問題を誘発するかもしれません。',
                                 'orig_kind': '推量・考え',
                                 'rewrite': 'プールサイズの暫定的な拡張は、別の負荷問題を誘発するおそれがあります。',
                                 'rewrite_kind': '説明（〜ます）'}],
                    'flags': [],
                    'orig_flags': []},
        'type_changes': [{'orig': 'プールサイズの暫定引き上げは、別の負荷問題を誘発するかもしれません。',
                          'rewrite': 'プールサイズの暫定的な拡張は、別の負荷問題を誘発するおそれがあります。',
                          'lost': [{'kind': '推量', 'hits': ['かもしれません']}],
                          'added': []}]},
 'U1': {'markers': [{'kind': '可能', 'orig': 0, 'rewrite': 1, 'orig_hits': [], 'rewrite_hits': ['できます']},
                    {'kind': '推量', 'orig': 1, 'rewrite': 0, 'orig_hits': ['かもしれ'], 'rewrite_hits': []}],
        'new_words': ['期待', '負荷', '軽減'],
        'lost_words': ['負担'],
        'structure': [],
        'spans': [{'added': '負荷',
                   'was': '',
                   'kinds': [],
                   'new_words': ['負荷'],
                   'where': 'うまく機能すれば、レビュー［負荷］の軽減が期待できます。'},
                  {'added': '軽減',
                   'was': '負担も下',
                   'kinds': [],
                   'new_words': ['軽減'],
                   'where': 'うまく機能すれば、レビュー負荷の［軽減］が期待できます。'},
                  {'added': '期待できます',
                   'was': 'るかもしれない',
                   'kinds': ['可能'],
                   'new_words': ['期待'],
                   'where': 'まく機能すれば、レビュー負荷の軽減が［期待できます］。'}],
        'logic': [],
        'bold': [],
        'endings': {'stance': None,
                    'changes': [{'orig': 'うまく機能すれば、レビューの負担も下がるかもしれない。',
                                 'orig_kind': '推量・考え',
                                 'rewrite': 'うまく機能すれば、レビュー負荷の軽減が期待できます。',
                                 'rewrite_kind': '説明（〜ます）'}],
                    'flags': [],
                    'orig_flags': []},
        'type_changes': [{'orig': 'うまく機能すれば、レビューの負担も下がるかもしれない。',
                          'rewrite': 'うまく機能すれば、レビュー負荷の軽減が期待できます。',
                          'lost': [{'kind': '推量', 'hits': ['かもしれない']}],
                          'added': []}]},
 'K1': {'markers': [{'kind': '推量', 'orig': 1, 'rewrite': 0, 'orig_hits': ['かもしれ'], 'rewrite_hits': []}],
        'new_words': [],
        'lost_words': [],
        'structure': [],
        'spans': [],
        'logic': [],
        'bold': [],
        'endings': {'stance': None,
                    'changes': [{'orig': '原因は設定ミスかもしれない。',
                                 'orig_kind': '推量・考え',
                                 'rewrite': '原因は設定ミスだ。',
                                 'rewrite_kind': '常体'}],
                    'flags': [],
                    'orig_flags': []},
        'type_changes': [{'orig': '原因は設定ミスかもしれない。',
                          'rewrite': '原因は設定ミスだ。',
                          'lost': [{'kind': '推量', 'hits': ['かもしれない']}],
                          'added': []}]}}

RISKS_BASELINE = {'U4': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': '何かを買う計画なんだろうな、という見当はつきます。',
         'new': '購買に関する計画であるとの推測は可能です。',
         'detail': {'lost': [{'kind': '推量', 'hits': ['だろう']}], 'added': []},
         'basis': None}],
 'K1': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': '原因は設定ミスかもしれない。',
         'new': '原因は設定ミスだ。',
         'detail': {'lost': [{'kind': '推量', 'hits': ['かもしれない']}], 'added': []},
         'basis': None}],
 'K2': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': 'アラート閾値は、運用データを見ながら調整することになると思われます。',
         'new': 'アラート閾値は、運用データを見ながら調整することになります。',
         'detail': {'lost': [{'kind': '推量', 'hits': ['と思われます']}], 'added': []},
         'basis': None}],
 'K3': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': '明日は晴れる。',
         'new': '明日は晴れるでしょう。',
         'detail': {'lost': [], 'added': [{'kind': '推量', 'hits': ['でしょう']}]},
         'basis': None}],
 'K4': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': '影響が続くと思われます。',
         'new': '影響が続く恐れがあります。',
         'detail': {'lost': [{'kind': '推量', 'hits': ['と思われます']}], 'added': []},
         'basis': None},
        {'kind': 'certainty_review',
         'subkind': 'weakened',
         'old_line': 1,
         'new_line': 1,
         'old': '影響が続くと思われます。',
         'new': '影響が続く恐れがあります。',
         'detail': {'old_words': ['と思われる'],
                    'new_words': ['おそれ'],
                    'steps': [{'from': 'と思われる',
                               'to': 'おそれ',
                               'from_level': 2,
                               'to_level': 1,
                               'counted': False}],
                    'mixed': False},
         'basis': None}],
 'K5': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': '影響が続く見込みです。',
         'new': '影響が続くかもしれません。',
         'detail': {'lost': [], 'added': [{'kind': '推量', 'hits': ['かもしれません']}]},
         'basis': None}],
 'K6': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': 'なお、順序保証が必要な処理では、パーティション設計がボトルネックになる可能性があると考えられます。',
         'new': 'なお、順序保証が求められる処理においては、パーティション設計がボトルネックとなる可能性が考えられます。',
         'detail': {'lost': [{'kind': '推量', 'hits': ['可能性がある', 'と考えられます']}], 'added': []},
         'basis': None}],
 'K7': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': 'ワーカー数は現状の見積もりで足りると考えられますが、実測はしていません。',
         'new': 'ワーカー数は現状の見積もりで足りると考えていますが、実測はしていません。',
         'detail': {'lost': [{'kind': '推量', 'hits': ['と考えられます']}],
                    'added': [{'kind': '意見', 'hits': ['と考えています']}]},
         'basis': None}],
 'K8': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': '問題ないのではないですか？',
         'new': '問題ないのではないでしょうか？',
         'detail': {'lost': [], 'added': [{'kind': '推量', 'hits': ['ではないでしょうか']}]},
         'basis': None}],
 'K9': [{'kind': 'sentence_type',
         'subkind': 'marks',
         'old_line': 1,
         'new_line': 1,
         'old': '原因は設定のようだ。',
         'new': '原因は設定の恐れがある。',
         'detail': {'lost': [{'kind': '推量', 'hits': ['ようだ']}], 'added': []},
         'basis': None},
        {'kind': 'certainty_review',
         'subkind': 'weakened',
         'old_line': 1,
         'new_line': 1,
         'old': '原因は設定のようだ。',
         'new': '原因は設定の恐れがある。',
         'detail': {'old_words': [],
                    'new_words': ['おそれ'],
                    'steps': [{'from': '断定', 'to': 'おそれ', 'from_level': 4, 'to_level': 1, 'counted': False}],
                    'mixed': False},
         'basis': None}],
 'K10': [{'kind': 'sentence_type',
          'subkind': 'marks',
          'old_line': 1,
          'new_line': 1,
          'old': '明日は雨が降るかもしれない。',
          'new': '明日は雨が降る可能性は低い。',
          'detail': {'lost': [{'kind': '推量', 'hits': ['かもしれない']}], 'added': []},
          'basis': None}],
 'K11': [{'kind': 'sentence_type',
          'subkind': 'marks',
          'old_line': 1,
          'new_line': 1,
          'old': '負荷が上がるとプール枯渇につながるかもしれません。',
          'new': '負荷が増大すると、コネクションプールの枯渇につながるリスクが考えられます。',
          'detail': {'lost': [{'kind': '推量', 'hits': ['かもしれません']}], 'added': []},
          'basis': None}]}

CANDIDATE_BASELINE = {'S1': 4,
 'S2': 4,
 'S3': 3,
 'S4': 2,
 'S5': 4,
 'S6': 7,
 'S7': 5,
 'S8': 6,
 'S9': 3,
 'U1': 6,
 'U2': 4,
 'U3': 4,
 'U4': 6,
 'K1': 3,
 'K2': 3,
 'K3': 3,
 'K4': 4,
 'K5': 4,
 'K6': 3,
 'K7': 2,
 'K8': 2,
 'K9': 2,
 'K10': 4,
 'K11': 5,
 'S10': 7,
 'mixed': 4}

TOP_KEYS = ['format',
 'format_version',
 'tool_version',
 'status',
 'changed',
 'candidate_count',
 'meaning_risk_count',
 'fail_on_meaning_risk_count',
 'not_judged',
 'context',
 'meaning_risks',
 'markers',
 'new_words',
 'lost_words',
 'structure',
 'spans',
 'logic',
 'bold',
 'endings',
 'type_changes',
 'full_diff',
 'stiffness',
 'tone',
 'feeling',
 'hedges',
 'immutable',
 'politeness',
 'register']

RULES_BASELINE = '■ 規則の見直し候補（4件）\n■ 元の文にない語: 拡張、暫定的\n■ 消えた語: 暫定引\n■ 文末の種類が変わった文（立場に合う向きか見る）\n- 推量・考え → 説明（〜ます）: プールサイズの暫定的な拡張は、別の負荷問題を誘発するおそれがあります。\n■ 文の種類の印が変わった文（伝聞・推量・意見・例え・依頼が、元の文と同じか見る）\n- 元: プールサイズの暫定引き上げは、別の負荷問題を誘発するかもしれません。\n  後: プールサイズの暫定的な拡張は、別の負荷問題を誘発するおそれがあります。\n  消えた印: 推量（かもしれません）'

RESTORED_BASELINE = {'format': 'yomiyasu-diff',
 'format_version': 2,
 'tool_version': '2.0.2',
 'status': 'has_candidates',
 'changed': True,
 'candidate_count': 6,
 'meaning_risk_count': 1,
 'fail_on_meaning_risk_count': 1,
 'not_judged': ['meaning_equivalence', 'reader_comprehension'],
 'context': {'doc_type': None, 'reader': None},
 'meaning_risks': [{'kind': 'sentence_type',
                    'subkind': 'marks',
                    'old_line': 1,
                    'new_line': 1,
                    'old': '何かを買う計画なんだろうな、という見当はつきます。',
                    'new': '購買に関する計画であるとの推測は可能です。',
                    'detail': {'lost': [{'kind': '推量', 'hits': ['だろう']}], 'added': []},
                    'basis': None}],
 'markers': [{'kind': '推量', 'orig': 1, 'rewrite': 0, 'orig_hits': ['だろう'], 'rewrite_hits': []},
             {'kind': 'つなぎ', 'orig': 0, 'rewrite': 1, 'orig_hits': [], 'rewrite_hits': ['しかし']}],
 'new_words': ['可能', '当該用語単独', '意味', '推測', '確認'],
 'lost_words': ['単体', '見当', '言葉'],
 'structure': [],
 'spans': [{'added': 'の推測',
            'was': 'いう見当',
            'kinds': [],
            'new_words': ['推測'],
            'where': '購買計画」。購買に関する計画であると［の推測］は可能です。\nしかし会議においては、'},
           {'added': '可能で',
            'was': 'つきま',
            'kinds': [],
            'new_words': ['可能'],
            'where': '」。購買に関する計画であるとの推測は［可能で］す。\nしかし会議においては、当該用語'},
           {'added': 'しかし',
            'was': 'でも',
            'kinds': ['つなぎ'],
            'new_words': [],
            'where': 'する計画であるとの推測は可能です。\n［しかし］会議においては、当該用語単独での意味'},
           {'added': '当該用語単独で',
            'was': 'そ',
            'kinds': [],
            'new_words': ['当該用語単独'],
            'where': 'は可能です。\nしかし会議においては、［当該用語単独で］の意味の確認が行われることはありませ'},
           {'added': '意味の確認',
            'was': '言葉',
            'kinds': [],
            'new_words': ['意味', '確認'],
            'where': 'かし会議においては、当該用語単独での［意味の確認］が行われることはありません。'}],
 'logic': [{'kind': '文頭のつなぎ', 'sentence': 'しかし会議においては、当該用語単独での意味の確認が行われることはありません。'}],
 'bold': [],
 'endings': {'stance': None, 'changes': [], 'flags': [], 'orig_flags': []},
 'type_changes': [{'orig': '何かを買う計画なんだろうな、という見当はつきます。',
                   'rewrite': '購買に関する計画であるとの推測は可能です。',
                   'lost': [{'kind': '推量', 'hits': ['だろう']}],
                   'added': []}],
 'full_diff': {'encoding_notes': [],
               'final_newline': {'old': True, 'new': True},
               'limits_applied': [],
               'hunks': [{'index': 1,
                          'tag': 'replace',
                          'old_start': 1,
                          'old_end': 2,
                          'new_start': 1,
                          'new_end': 2,
                          'old_blocks': ['paragraph'],
                          'new_blocks': ['paragraph'],
                          'whitespace_only': False,
                          'notes': [],
                          'moved_to': None,
                          'moved_from': None,
                          'old_lines': ['たとえば「購買計画」。何かを買う計画なんだろうな、という見当はつきます。',
                                        'でも会議では、その言葉が単体で問われることはありません。'],
                          'new_lines': ['たとえば「購買計画」。購買に関する計画であるとの推測は可能です。',
                                        'しかし会議においては、当該用語単独での意味の確認が行われることはありません。'],
                          'segments': [['=', 'たとえば「購買計画」。'],
                                       ['-', '何かを'],
                                       ['+', '購'],
                                       ['=', '買'],
                                       ['-', 'う'],
                                       ['+', 'に関する'],
                                       ['=', '計画'],
                                       ['-', 'なんだろうな、'],
                                       ['+', 'である'],
                                       ['=', 'と'],
                                       ['-', 'いう見当'],
                                       ['+', 'の推測'],
                                       ['=', 'は'],
                                       ['-', 'つきま'],
                                       ['+', '可能で'],
                                       ['=', 'す。\n'],
                                       ['-', 'でも'],
                                       ['+', 'しかし'],
                                       ['=', '会議'],
                                       ['-', 'で'],
                                       ['+', 'において'],
                                       ['=', 'は、'],
                                       ['-', 'そ'],
                                       ['+', '当該用語単独で'],
                                       ['=', 'の'],
                                       ['-', '言葉'],
                                       ['+', '意味の確認'],
                                       ['=', 'が'],
                                       ['-', '単体で問'],
                                       ['+', '行'],
                                       ['=', 'われることはありません。']],
                          'segments_omitted': None}]},
 'stiffness': {'level': 'review',
               'candidate_count': 2,
               'candidates': [{'kind': 'stiffness',
                               'subkind': 'sentence',
                               'old_line': 1,
                               'new_line': 1,
                               'old': '何かを買う計画なんだろうな、という見当はつきます。',
                               'new': '購買に関する計画であるとの推測は可能です。',
                               'detail': {'old_kanji_ratio': 26.1,
                                          'new_kanji_ratio': 45.0,
                                          'old_length': 25,
                                          'new_length': 21},
                               'level': 'review'},
                              {'kind': 'stiffness',
                               'subkind': 'document',
                               'old_line': None,
                               'new_line': None,
                               'old': None,
                               'new': None,
                               'detail': {'old_kanji_ratio': 29.82,
                                          'new_kanji_ratio': 40.62,
                                          'old_avg_length': 21.33,
                                          'new_avg_length': 23.33,
                                          'example': {'old_line': 1,
                                                      'new_line': 1,
                                                      'old': '何かを買う計画なんだろうな、という見当はつきます',
                                                      'new': '購買に関する計画であるとの推測は可能です'}},
                               'level': 'review'}],
               'metrics': {'old': {'sentences': 3,
                                   'chars': 64,
                                   'avg_sentence_length': 21.33,
                                   'kanji_ratio': 29.82,
                                   'kanji': 17,
                                   'nominalizations': 0,
                                   'nominalization_names': {},
                                   'no_chains': 0},
                           'new': {'sentences': 3,
                                   'chars': 70,
                                   'avg_sentence_length': 23.33,
                                   'kanji_ratio': 40.62,
                                   'kanji': 26,
                                   'nominalizations': 1,
                                   'nominalization_names': {'に関して': 1},
                                   'no_chains': 0}},
               'list': 'references/lists/nominalization.txt',
               'list_problem': None},
 'tone': {'level': 'review',
          'candidate_count': 0,
          'candidates': [],
          'counts': {'old': {'exclamation': 0,
                             'question': 0,
                             'emoji': 0,
                             'intensifier': 0,
                             'heading_chars': 0},
                     'new': {'exclamation': 0,
                             'question': 0,
                             'emoji': 0,
                             'intensifier': 0,
                             'heading_chars': 0}},
          'list': 'references/lists/intensifiers.txt',
          'list_problem': None},
 'feeling': {'list': 'references/lists/feelings.txt', 'list_problem': None},
 'hedges': {'level': 'review',
            'candidate_count': 0,
            'candidates': [],
            'list': 'references/lists/hedges.txt',
            'list_problem': None},
 'immutable': {'level': 'review', 'candidate_count': 0, 'candidates': [], 'meaning_risk_count': 0},
 'politeness': {'level': 'review',
                'candidate_count': 0,
                'candidates': [],
                'applicable': False,
                'threshold': 0.2,
                'metrics': None},
 'register': {'level': 'review',
              'candidate_count': 0,
              'candidates': [],
              'threshold': {'min_sentences': 3, 'min_ratio': 0.5},
              'skipped_by': None}}

def risks(result, kind, subkind=None):
    return [r for r in result['meaning_risks']
            if r['kind'] == kind and (subkind is None or r['subkind'] == subkind)]


class HedgeMarks(unittest.TestCase):
    def check_example(self, tag):
        result = diff.diff(*EXAMPLES[tag])
        self.assertEqual(list(result), TOP_KEYS)
        marks = risks(result, 'sentence_type', 'marks')
        if tag.startswith('S') and tag != 'S10':
            self.assertEqual(marks, [])
            self.assertEqual(result['fail_on_meaning_risk_count'], 0)
            self.assertEqual(len(result['type_changes']), 1)
            self.assertEqual(result['candidate_count'], CANDIDATE_BASELINE[tag])
            self.assertEqual(result['hedges']['candidate_count'], 0)
            self.assertEqual([(r['kind'], r['subkind']) for r in result['meaning_risks']],
                             [('claim', 'causal')] if tag == 'S8' else [])
        elif tag == 'S10':
            self.assertEqual(len(marks), 1)
            self.assertEqual(marks[0]['old'], EXAMPLES['K1'][0].strip())
            self.assertEqual(marks[0]['old_line'], 3)
            self.assertEqual(result['fail_on_meaning_risk_count'], 1)
            self.assertEqual(len(result['type_changes']), 2)
            self.assertEqual(result['candidate_count'], CANDIDATE_BASELINE[tag])
        elif tag in ('U1', 'U2', 'U3'):
            self.assertEqual(marks, [])
            found = risks(result, 'certainty', 'strengthened')
            self.assertEqual(len(found), 1)
            self.assertEqual(result['fail_on_meaning_risk_count'], 1)
            self.assertEqual(result['candidate_count'], CANDIDATE_BASELINE[tag] + 1)
            self.assertEqual(result['hedges']['candidate_count'], 0)
            expected = {'U1': ('かもしれない', '期待できる'), 'U2': ('かもしれない', '見込み'),
                        'U3': ('見込み', '予定')}[tag]
            self.assertEqual([(s['from'], s['to']) for s in found[0]['detail']['steps']], [expected])
            self.assertTrue(found[0]['detail']['steps'][0]['counted'])
        else:
            self.assertEqual(result['meaning_risks'], RISKS_BASELINE[tag])
            self.assertEqual(result['candidate_count'], CANDIDATE_BASELINE[tag])
            self.assertEqual(len(marks), 1)
            self.assertEqual(result['fail_on_meaning_risk_count'], 1)
        if tag == 'S1':
            report = diff.report(result)
            self.assertIn('■ 文の種類の印が変わった文', report)
            self.assertNotIn('- 文の種類の印が変わった:', report)
            self.assertNotIn('■ 意味が変わる恐れ', report)
            self.assertEqual(diff.report_parts(result)['rules'], RULES_BASELINE)
            self.assertEqual(diff.meaning_risks(*EXAMPLES[tag], type_changes=result['type_changes']),
                             result['meaning_risks'])
        if tag == 'U4':
            self.assertEqual(result, RESTORED_BASELINE)
            self.assertEqual(risks(result, 'certainty'), [])
            self.assertEqual(risks(result, 'certainty_review'), [])

    def test_P1_nine_keys(self):
        for tag, expected in NINE_BASELINE.items():
            with self.subTest(tag=tag):
                result = diff.diff(*EXAMPLES[tag])
                self.assertEqual({k: result[k] for k in expected}, expected)

    def test_P2_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = Path(tmp) / 'old.md', Path(tmp) / 'new.md'
            for tag in ('S1', 'U1', 'K1'):
                old.write_text(EXAMPLES[tag][0], encoding='utf-8')
                new.write_text(EXAMPLES[tag][1], encoding='utf-8')
                for fail_on in (False, True):
                    with self.subTest(tag=tag, fail_on=fail_on):
                        cmd = [sys.executable, '-B', str(ROOT / 'scripts/yomiyasu_diff.py'), '--json']
                        if fail_on:
                            cmd.append('--fail-on=meaning-risk')
                        process = subprocess.run(cmd + [str(old), str(new)], capture_output=True, text=True)
                        self.assertEqual(process.returncode, int(fail_on and tag != 'S1'), process.stderr)
                        self.assertEqual(json.loads(process.stdout), diff.diff(*EXAMPLES[tag]))

    def test_P3_help(self):
        process = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/yomiyasu_diff.py'), '--help'],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('推量の印が同じ強さの慎重な言い方に替わっただけの文', process.stdout)
        self.assertIn('かもしれません → 恐れがあります、と思われます → 見込みです', ' '.join(process.stdout.split()))
        self.assertIn('かもしれない → 見込み', process.stdout)

    def test_P4_classification(self):
        expected = {'S1': 'same', 'S4': 'same', 'S6': 'same', 'U1': 'strengthen', 'U3': 'same',
                    'U4': 'strengthen', 'K1': 'lost', 'K3': 'added', 'K4': 'weaken', 'K5': 'weaken',
                    'K6': 'consolidated', 'K7': 'other_kinds', 'K8': 'question', 'K9': 'not_in_table',
                    'K10': 'negation', 'K11': 'lost', 'mixed': 'mixed'}
        for tag, classification in expected.items():
            with self.subTest(tag=tag):
                result = diff.diff(*EXAMPLES[tag])
                change, = result['type_changes']
                self.assertEqual(diff._classify_hedge_marks(change['orig'], change['rewrite'],
                                                          change['lost'], change['added']), classification)

    def test_P5_full_diff_speed(self):
        # 6万字をすべて替える。反復文字の負荷に、推量の印の例を添える。
        old = 'a' * 60000 + '\n\n' + EXAMPLES['S1'][0]
        new = 'b' * 60000 + '\n\n' + EXAMPLES['S1'][1]
        durations = []
        for _ in range(3):
            start = time.perf_counter()
            result = diff.diff(old, new)
            durations.append(time.perf_counter() - start)
        self.assertLess(sorted(durations)[1], 3.0, durations)
        self.assertEqual(result['fail_on_meaning_risk_count'], 0)

    def test_public_function_without_type_changes(self):
        old, new = EXAMPLES['K1']
        for changes in (None, []):
            with self.subTest(changes=changes):
                found = diff.meaning_risks(old, new, type_changes=changes)
                self.assertFalse(any(r['subkind'] == 'marks' for r in found))
                self.assertEqual([(r['kind'], r['subkind']) for r in found], [('certainty', 'strengthened')])

    def test_quiet_marks_for_other_detectors(self):
        # 外した印も hedges と状態・約束の重複判定に届く。
        for tag in ('S4', 'S9', 'U1'):
            with self.subTest(tag=tag):
                with mock.patch.object(diff, '_addition_risks', wraps=diff._addition_risks) as additions:
                    with mock.patch.object(diff, '_hedges', wraps=diff._hedges) as hedges:
                        result = diff.diff(*EXAMPLES[tag])
                passed = additions.call_args[0][2]
                self.assertEqual(len([r for r in passed if r['subkind'] == 'marks']), 1)
                quiet = hedges.call_args[0][0].quiet_marks
                self.assertEqual(len(quiet), 1)
                self.assertNotIn(quiet[0], result['meaning_risks'])
                self.assertEqual(result['hedges']['candidate_count'], 0)

    def test_certainty_word_spans_preserve_tuple_shape(self):
        for old, new in EXAMPLES.values():
            for text in (old, new):
                words = diff._certainty_words(text)
                spans = diff._certainty_word_spans(text)
                self.assertEqual(words, [w[:5] for w in spans])
                self.assertTrue(all(w[2] < w[5] <= len(text) for w in spans))


# 同じ強さの語で打ち消せても、意味が変わる形は今のまま印の候補を出す（反証で見つけた例）。
KEPT = {
    # 述語の肯定と否定が替わった
    'N1': ('移行は間に合うと思われます。', '移行は間に合わない見込みです。', 'negation'),
    'N2': ('障害は再発しないと思われます。', '障害が再発する見込みです。', 'negation'),
    'N3': ('売上は伸びるかもしれません。', '売上が伸びないリスクがあります。', 'negation'),
    'N4': ('障害が起きるかもしれません。', '障害が起きるおそれがあるとは言えません。', 'negation'),
    # 「とは限らない」
    'N5': ('この施策で売上が伸びるかもしれない。', 'この施策で売上が伸びるとは限らない。', 'negation'),
    # 条件の形に替わった
    'C1': ('再開が遅れるかもしれませんが、点検します。', '再開が遅れるおそれがあれば、点検します。', 'condition'),
    # 別の節・別の文の慎重さで打ち消した
    'A1': ('原因は設定ミスかもしれない。', '原因は設定ミスで、再発の恐れもある。', 'unanchored'),
    'A2': ('原因は設定ミスかもしれない。', '原因は設定ミスだ。再発の恐れもある。', 'unanchored'),
    # 相手のない語が残った（見込み → 断定）
    'A3': ('再開が遅れるかもしれず、停止する見込みです。', '再開が遅れる恐れがあり、停止します。', 'unpaired'),
    'A4': ('復旧は明日と思われます。', '復旧は明日の見込みですが、遅れる恐れもあります。', 'unpaired'),
    # 数えない語が相手
    'R1': ('来月から料金を変えるかもしれません。', '来月からの料金の変更を検討しています。', 'not_core'),
    'R2': ('このAPIはタイムアウトするかもしれない。', 'このAPIはタイムアウトすることがある。', 'not_core'),
    'R3': ('ユーザーは離脱すると考えられる。', 'ユーザーは離脱する傾向がある。', 'not_core'),
    'R4': ('コストが下がると思われます。', 'コストの削減が期待できます。', 'not_core'),
    # 伝聞とも読める「らしい」
    'H1': ('部長は来月退職するらしい。', '部長は来月退職する見込みだ。', 'not_in_table'),
}


class HedgeMarksKept(unittest.TestCase):
    def test_kept(self):
        for tag, (old, new, classification) in KEPT.items():
            with self.subTest(tag=tag):
                result = diff.diff(old + '\n', new + '\n')
                change, = result['type_changes']
                self.assertEqual(diff._classify_hedge_marks(change['orig'], change['rewrite'],
                                                          change['lost'], change['added']), classification)
                marks = risks(result, 'sentence_type', 'marks')
                self.assertEqual(len(marks), 1)
                self.assertEqual(marks[0]['detail'], {'lost': change['lost'], 'added': change['added']})
                self.assertGreaterEqual(result['fail_on_meaning_risk_count'], 1)
                self.assertEqual(risks(result, 'certainty', 'strengthened'), [])

    def test_restore_uses_line(self):
        # 同じ原文の文が別の行にあっても、その行の確度の候補では、1行目の印を戻す決めを止めない。
        old = EXAMPLES['U4'][0] + '\nこれは何かを買う計画なんだろうな、という見当はつきます。\n'
        new = EXAMPLES['U4'][1] + '\nこれは何かを買う計画なのは確実です。\n'
        result = diff.diff(old, new)
        found = [(r['kind'], r['subkind'], r['old_line']) for r in result['meaning_risks']]
        self.assertEqual(found, [('sentence_type', 'marks', 1), ('certainty', 'strengthened', 4)])
        self.assertEqual(result['fail_on_meaning_risk_count'], 2)

    def test_cancel_same_level_unchanged(self):
        for old, new in EXAMPLES.values():
            before, after = diff._certainty_words(old), diff._certainty_words(new)
            rest_old, rest_new, pairs = diff._cancel_pairs(before, after)
            self.assertEqual(diff._cancel_same_level(before, after), (rest_old, rest_new))
            self.assertEqual(len(pairs) + len(rest_old), len(before))
            self.assertEqual(len(pairs) + len(rest_new), len(after))

def make_example_test(tag):
    def test(self):
        self.check_example(tag)
    return test


for _tag in EXAMPLES:
    if _tag != 'mixed':
        setattr(HedgeMarks, 'test_' + _tag, make_example_test(_tag))


if __name__ == '__main__':
    unittest.main()
