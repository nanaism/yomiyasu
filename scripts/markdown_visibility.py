# -*- coding: utf-8 -*-
"""Shared, dependency-free Markdown visibility for lint candidates.

Offsets are half-open Python string positions. This is a targeted scanner,
not a claim to implement every CommonMark or GFM construct.
"""

from __future__ import annotations
__version__ = "3.0.0"

import os
from pathlib import Path
from collections.abc import Callable, Collection, Iterable, Sequence
from typing import TypedDict
import re
import unicodedata
from bisect import bisect_left, bisect_right

_ASCII_PUNCT = set('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~')
_HTML_BLOCK_TAGS = set(('address article aside base basefont blockquote body caption center col colgroup '
                        'dd details dialog dir div dl dt fieldset figcaption figure footer form frame '
                        'frameset h1 h2 h3 h4 h5 h6 head header hr html iframe legend li link main '
                        'menu menuitem nav noframes ol optgroup option p param section source summary '
                        'table tbody td tfoot th thead title tr track ul').split())
_TAG_NAME = re.compile(r'</?[A-Za-z][A-Za-z0-9-]*')
_ATTRIBUTE_NAME = re.compile(r'[A-Za-z_:][A-Za-z0-9_.:-]*')
_AUTOLINK = re.compile(r'<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\x00-\x20]*|'
                       r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9]'
                       r'(?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
                       r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*>)')
_CONTAINER_MARKER = re.compile(r'(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$)')
_CONTAINER_MARKER_DEFAULT = _CONTAINER_MARKER
_BARE_URL = re.compile(r'(?:https?://|www\.)[^\s<>]+')
_REFERENCE_LABEL = re.compile(r'^ {0,3}\[((?:\\.|[^\[\]\\]){1,999})\]:[ \t]*')
_BLANK_TITLE_LINE = re.compile(r'(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)')
_SETEXT = re.compile(r'^ {0,3}(?:=+|-+)[ \t]*$')
_THEMATIC = re.compile(r'^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$')
_INLINE_EVENTS = re.compile(r'[\\`<\[\]hw]')
_FENCE_OPEN = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_ATX_HEADING = re.compile(r'^ {0,3}#{1,6}(?:[ \t]+|$)')


class MarkdownLine(TypedDict):
    line: int
    raw: str
    start: int
    ending: str
    content_start: int
    content: str
    quote_depth: int
    list_item: bool
    kind: str


class MarkdownBlock(TypedDict):
    kind: str
    lines: list[MarkdownLine]


def _path_matches(probe: Callable[[], bool]) -> bool:
    """Boolean path probes treat an unreadable name as no match, as os.path did."""
    try:
        return probe()
    except OSError:
        return False


def absolute_path(path: str) -> str:
    """Normalize lexical components and Windows drive-relative paths without following links."""
    # Path.absolute() leaves other-drive paths relative before Python 3.12;
    # Path.resolve() would change the symlink semantics.
    return os.path.abspath(path)  # noqa: PTH100 -- native drive-relative resolution is required


def unicode_whitespace(ch: str) -> bool:
    if not ch: return True
    if len(ch) > 1:
        return all(unicode_whitespace(c) for c in ch)
    return ch in '\t\n\r\f' or unicodedata.category(ch) == 'Zs'


def _escaped(text: str, position: int) -> bool:
    start = position
    while start > 0 and text[start - 1] == '\\':
        start -= 1
    return (position - start) % 2 == 1


def _tag_space_end(text: str, start: int) -> int:
    """Spaces/tabs and at most one Markdown line ending, not Python isspace."""
    pos = start
    while pos < len(text) and text[pos] in ' \t': pos += 1
    if text.startswith('\r\n', pos): pos += 2
    elif pos < len(text) and text[pos] in '\r\n': pos += 1
    while pos < len(text) and text[pos] in ' \t': pos += 1
    return pos


def _terminator_positions(text: str) -> dict[str, list[int]]:
    return {token: [match.start() for match in re.finditer(re.escape(token), text)]
            for token in ('-->', '?>', ']]>', '>')}


def _tag_end(text: str, start: int, terminators: dict[str, list[int]] | None = None) -> int | None:
    def closed(token: str, begin: int) -> int | None:
        if terminators is None:
            end = text.find(token, begin)
        else:
            positions = terminators[token]
            index = bisect_left(positions, begin)
            end = positions[index] if index < len(positions) else -1
        return None if end < 0 else end + len(token)
    if text.startswith('<!--', start):
        if text.startswith('<!-->', start): return start + 5
        if text.startswith('<!--->', start): return start + 6
        return closed('-->', start + 4)
    if text.startswith('<?', start):
        return closed('?>', start + 2)
    if text.startswith('<![CDATA[', start):
        return closed(']]>', start + 9)
    if (text.startswith('<!', start) and start + 2 < len(text)
            and text[start + 2] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'):
        return closed('>', start + 3)
    opening = _TAG_NAME.match(text, start)
    if opening is None:
        return None
    pos = opening.end()
    closing = text.startswith('</', start)
    while pos < len(text):
        space_end = _tag_space_end(text, pos)
        if space_end < len(text) and text[space_end] == '>': return space_end + 1
        if not closing and text.startswith('/>', space_end): return space_end + 2
        if closing or space_end == pos: return None
        attribute = _ATTRIBUTE_NAME.match(text, space_end)
        if attribute is None: return None
        pos = attribute.end()
        assignment = _tag_space_end(text, pos)
        if assignment >= len(text) or text[assignment] != '=':
            continue  # The same whitespace can separate the next attribute.
        pos = _tag_space_end(text, assignment + 1)
        if pos >= len(text): return None
        if text[pos] in '\"\'':
            end = text.find(text[pos], pos + 1)
            if end < 0: return None
            pos = end + 1
        else:
            begin = pos
            while pos < len(text) and text[pos] not in ' \t\r\n\"\'=<>`': pos += 1
            if pos == begin: return None
    return None


def _link_end(text: str, opening: int) -> int | None:
    """Return a validated inline destination/title end, or no opaque range."""
    pos = opening + 1
    while pos < len(text) and text[pos] in ' \t\n\r': pos += 1
    if pos >= len(text): return None
    if text[pos] == '<':
        pos += 1
        while pos < len(text):
            if text[pos] == '\\' and pos + 1 < len(text): pos += 2; continue
            if text[pos] == '>': pos += 1; break
            if text[pos] in '<\n\r': return None
            pos += 1
        else: return None
    else:
        depth = 0
        while pos < len(text):
            ch = text[pos]
            if ch == '\\' and pos + 1 < len(text): pos += 2; continue
            if ch == '(':
                depth += 1
                if depth > 32: return None
            elif ch == ')':
                if depth == 0: return pos + 1
                depth -= 1
            elif ch in ' \t\n\r':
                if depth: return None
                break
            elif ord(ch) < 32 or ch in '<>': return None
            pos += 1
        if depth: return None
    spaces_start = pos
    while pos < len(text) and text[pos] in ' \t\n\r': pos += 1
    if pos < len(text) and text[pos] == ')': return pos + 1
    if pos == spaces_start or pos >= len(text) or text[pos] not in '\"\'(':
        return None
    closer = ')' if text[pos] == '(' else text[pos]
    pos += 1
    while pos < len(text):
        if text[pos] == '\\' and pos + 1 < len(text): pos += 2; continue
        if text[pos] == closer: pos += 1; break
        if _BLANK_TITLE_LINE.match(text, pos): return None
        if closer == ')' and text[pos] == '(': return None
        pos += 1
    else: return None
    while pos < len(text) and text[pos] in ' \t\n\r': pos += 1
    return pos + 1 if pos < len(text) and text[pos] == ')' else None


def inline_protected_spans(text: str) -> list[tuple[int, int, str]]:
    """Code, escaped punctuation and opaque inline tokens, preserving labels."""
    runs = [(m.start(), m.end()) for m in re.finditer(r'`+', text)]
    by_width = {}
    for start, end in runs:
        by_width.setdefault(end - start, []).append((start, end))
    starts_by_width = {width: [pair[0] for pair in pairs] for width, pairs in by_width.items()}
    spans = []
    brackets = []
    terminators = _terminator_positions(text) if '<' in text else None
    pos = 0
    while pos < len(text):
        # Other code points cannot start any token recognized below. Seeking
        # only event characters preserves the same raw positions and state.
        event = _INLINE_EVENTS.search(text, pos)
        if event is None:
            break
        pos = event.start()
        ch = text[pos]
        if ch == '\\' and pos + 1 < len(text) and text[pos + 1] in _ASCII_PUNCT:
            spans.append((pos, pos + 2, 'escape'))
            pos += 2
            continue
        if ch == '`':
            end = pos + 1
            while end < len(text) and text[end] == '`': end += 1
            width = end - pos
            positions = starts_by_width.get(width, ())
            index = bisect_left(positions, end)
            closing = by_width[width][index][1] if index < len(positions) else None
            if closing is not None:
                spans.append((pos, closing, 'inline_code'))
                pos = closing
                continue
            pos = end
            continue
        if ch == '<':
            auto = _AUTOLINK.match(text, pos)
            if auto:
                end = auto.end()
                spans.append((pos, end, 'autolink'))
                pos = end
                continue
            end = _tag_end(text, pos, terminators)
            if end is not None:
                spans.append((pos, end, 'html_token'))
                pos = end
                continue
        if ch == '[':
            brackets.append(pos)
        elif ch == ']' and brackets:
            opening = brackets.pop()
            if pos + 1 < len(text) and text[pos + 1] == '(':
                end = _link_end(text, pos + 1)
                if end is not None:
                    if opening > 0 and text[opening - 1] == '!' and not _escaped(text, opening - 1):
                        spans.append((opening - 1, end, 'image'))
                    else:
                        spans.append((pos + 1, end, 'link_destination'))
                    pos = end
                    continue
        # GFM bare URLs are data for prose inspection, not emphasis instructions.
        if text.startswith(('http://', 'https://', 'www.'), pos):
            www = text.startswith('www.', pos)
            # Reject an impossible www start before scanning its entire suffix.
            if www and pos and not (unicode_whitespace(text[pos - 1]) or text[pos - 1] in '*_~('):
                pos += 1
                continue
            match = _BARE_URL.match(text, pos)
            if match:
                end = match.end()
                # New www recognition is restricted to published GFM boundaries
                # and a valid ASCII domain. Adjacent-Japanese policy is not widened.
                domain = re.split(r'[/?:#]', match.group(0), maxsplit=1)[0]
                segments = domain.split('.')
                valid_www = (len(segments) >= 2
                             and all(re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in segments)
                             and all('_' not in part for part in segments[-2:])
                             and (pos == 0 or unicode_whitespace(text[pos - 1])
                                  or text[pos - 1] in '*_~('))
                if not www or valid_www:
                    # Terminal Markdown delimiters/punctuation are not URL data.
                    while end > pos and text[end - 1] in '?!.,:*_~': end -= 1
                    excess = text[pos:end].count(')') - text[pos:end].count('(')
                    while excess > 0 and end > pos and text[end - 1] == ')':
                        end -= 1
                        excess -= 1
                    spans.append((pos, end, 'bare_url'))
                    pos = end
                    continue
        pos += 1
    return sorted(spans)


def _columns(text: str) -> int:
    columns = 0
    for ch in text:
        if ch == ' ': columns += 1
        elif ch == '\t': columns += 4 - columns % 4
        else: break
    return columns


def _containers(raw: str, allow_list: bool = True) -> tuple[int, int, bool]:
    # Default containers can start only with an ASCII space, a quote marker,
    # a list marker, or a Unicode digit. isdigit() is a conservative superset
    # of regex \d; unusual custom marker patterns keep the original path.
    if (type(raw) is str and raw and raw[0] not in ' >'
            and (not allow_list or (_CONTAINER_MARKER is _CONTAINER_MARKER_DEFAULT
                                   and raw[0] not in '-+*' and not raw[0].isdigit()))):
        return 0, 0, False
    pos = 0
    quotes = 0
    list_item = False
    while pos < len(raw):
        candidate = pos
        while candidate < len(raw) and candidate - pos < 3 and raw[candidate] == ' ':
            candidate += 1
        if candidate < len(raw) and raw[candidate] == '>':
            quotes += 1
            pos = candidate + 1
            if pos < len(raw) and raw[pos] in ' \t': pos += 1
            continue
        marker = _CONTAINER_MARKER.match(raw, candidate) if allow_list else None
        if marker:
            list_item = True
            pos = marker.end()
            continue
        break
    return pos, quotes, list_item


def _physical_lines(text: str) -> list[tuple[int, str, str]]:
    rows = []
    start = 0
    for ending in re.finditer(r'\r\n|\r|\n', text):
        rows.append((start, text[start:ending.start()], ending.group(0)))
        start = ending.end()
    rows.append((start, text[start:], ''))
    return rows


def _reference_definition(content: str) -> bool:
    """Only a complete one-line definition is hidden; never hide trailing prose."""
    return reference_definition_end([content], 0) == 0


def _table_cells(content: str) -> list[str]:
    """GFM cell boundaries; an escaped pipe is data even inside code spans."""
    stripped = content.strip(' \t')
    starts = [0]
    ends = []
    for index, ch in enumerate(stripped):
        if ch == '|' and not _escaped(stripped, index):
            ends.append(index)
            starts.append(index + 1)
    ends.append(len(stripped))
    cells = [stripped[left:right] for left, right in zip(starts, ends)]
    if stripped.startswith('|'): cells.pop(0)
    if stripped.endswith('|') and not _escaped(stripped, len(stripped) - 1): cells.pop()
    return cells


class _RowCursor:
    def __init__(self, lines: list[str], row: int, column: int = 0) -> None:
        self.lines = lines
        self.row = row
        self.column = column

    def char(self) -> str | None:
        line = self.lines[self.row]
        if self.column < len(line):
            return line[self.column]
        return '\n' if self.row + 1 < len(self.lines) else None

    def following(self) -> str | None:
        line = self.lines[self.row]
        return line[self.column + 1] if self.column + 1 < len(line) else None

    def advance(self) -> None:
        if self.column < len(self.lines[self.row]):
            self.column += 1
        elif self.row + 1 < len(self.lines):
            self.row += 1
            self.column = 0

    def escape(self) -> bool:
        if self.char() == '\\' and self.following() in _ASCII_PUNCT:
            self.advance()
            self.advance()
            return True
        return False


def _reference_gap(cursor: _RowCursor) -> bool:
    """Consume spaces/tabs and at most one row break; return whether present."""
    seen = False
    while cursor.char() in (' ', '\t'):
        cursor.advance()
        seen = True
    if cursor.char() == '\n':
        cursor.advance()
        seen = True
        while cursor.char() in (' ', '\t'):
            cursor.advance()
    return seen


def _reference_destination(cursor: _RowCursor) -> bool:
    if cursor.char() == '<':
        cursor.advance()
        while cursor.char() is not None:
            if cursor.escape():
                continue
            if cursor.char() == '>':
                cursor.advance()
                return True
            if cursor.char() in ('<', '\n'):
                return False
            cursor.advance()
        return False
    count = 0
    depth = 0
    while (ch := cursor.char()) is not None and ch not in (' ', '\t', '\n'):
        if cursor.escape():
            count += 2
            continue
        if ord(ch) < 32 or ord(ch) == 127 or ch in '<>':
            return False
        if ch == '(':
            depth += 1
            if depth > 32:
                return False  # Explicit, bounded nesting policy; at least 3.
        elif ch == ')':
            if depth == 0:
                return False
            depth -= 1
        cursor.advance()
        count += 1
    return count > 0 and depth == 0


def _reference_title_end(cursor: _RowCursor) -> int | None:
    opener = cursor.char()
    closer = ')' if opener == '(' else opener
    cursor.advance()
    while cursor.char() is not None:
        if cursor.escape():
            continue
        ch = cursor.char()
        if ch == closer:
            cursor.advance()
            while cursor.char() in (' ', '\t'):
                cursor.advance()
            return cursor.row if cursor.char() in (None, '\n') else None
        if opener == '(' and ch == '(':
            return None
        if ch == '\n' and not cursor.lines[cursor.row + 1].strip(' \t'):
            return None
        cursor.advance()
    return None


def reference_definition_end(lines: list[str], start: int, paragraph_context: bool = False) -> int | None:
    """Return the last definition row (inclusive), or no opaque boundary.

    Rows contain no line terminator and preserve row identity. The caller has
    already decided container ownership and whether an ordinary paragraph is
    open. A failed next-row title leaves a valid destination-only row intact;
    same-row extra text invalidates the whole definition.
    """
    if paragraph_context or not 0 <= start < len(lines):
        return None
    cursor = _RowCursor(lines, start)
    spaces = 0
    while cursor.char() == ' ' and spaces < 3:
        cursor.advance()
        spaces += 1
    if cursor.char() != '[':
        return None
    cursor.advance()
    label_length = 0
    meaningful = False
    while (ch := cursor.char()) is not None and ch != ']':
        if cursor.escape():
            label_length += 2
            meaningful = True
        else:
            if ch == '[':
                return None
            if ch == '\n' and not cursor.lines[cursor.row + 1].strip(' \t'):
                return None
            meaningful |= ch not in ' \t\n'
            label_length += 1
            cursor.advance()
        if label_length > 999:
            return None
    if cursor.char() != ']' or not meaningful:
        return None
    cursor.advance()
    if cursor.char() != ':':
        return None
    cursor.advance()
    _reference_gap(cursor)
    if cursor.char() in (None, '\n') or not _reference_destination(cursor):
        return None
    destination_row = cursor.row
    separated = _reference_gap(cursor)
    if cursor.char() in (None, '\n'):
        return destination_row
    if not separated or cursor.char() not in ('"', "'", '('):
        return destination_row if cursor.row > destination_row else None
    title_on_later_row = cursor.row > destination_row
    title_row = _reference_title_end(cursor)
    return destination_row if title_row is None and title_on_later_row else title_row


def analyze_markdown(text: str, skip_frontmatter: bool = True) -> dict:
    lines: list[MarkdownLine] = []
    blocks: list[MarkdownBlock] = []
    protected = []
    current: MarkdownBlock | None = None
    fence = None
    html_until = None
    active_list_indent = 0
    raw_rows = _physical_lines(text)
    fm_end = 0
    if skip_frontmatter and raw_rows and raw_rows[0][1].strip() == '---':
        for index in range(1, len(raw_rows)):
            if raw_rows[index][1].strip() == '---':
                fm_end = index + 1
                break
    for index, (start, raw, ending) in enumerate(raw_rows):
        prefix, depth, list_item = _containers(raw)
        quote_prefix, quote_depth, _ = _containers(raw, allow_list=False)
        quote_content = raw[quote_prefix:]
        # Setext and thematic rules precede list-marker recognition.
        if (_THEMATIC.match(quote_content)
                or (current is not None and current['kind'] in ('paragraph', 'quote', 'list')
                    and _SETEXT.match(quote_content))):
            prefix, depth, list_item = quote_prefix, quote_depth, False
        if list_item:
            active_list_indent = prefix
        elif active_list_indent and depth and prefix >= active_list_indent:
            list_item = True
        elif active_list_indent and raw.strip():
            indent = len(raw) - len(raw.lstrip(' \t'))
            if depth == 0 and indent >= active_list_indent:
                prefix = active_list_indent
                list_item = True
            elif depth == 0:
                active_list_indent = 0
        content = raw[prefix:]
        stripped = content.strip(' \t')
        info: MarkdownLine = {'line': index + 1, 'raw': raw, 'start': start, 'ending': ending,
                'content_start': start + prefix, 'content': content,
                'quote_depth': depth, 'list_item': list_item, 'kind': 'paragraph'}
        if prefix:
            protected.append((start, start + prefix, 'container_prefix'))
        if index < fm_end:
            kind = 'frontmatter'
        elif fence is not None and depth < fence[2]:
            fence = None
            kind = None
        else:
            kind = None
        if kind is None and fence is not None:
            kind = 'code'
            closing = re.match(r'^ {0,3}(' + re.escape(fence[0]) + r'{'+str(fence[1])+r',})[ \t]*$', content)
            if closing: fence = None
        if kind is None and html_until is not None:
            kind = 'html_block'
            if html_until == 'blank':
                if not stripped: html_until = None
            elif re.search(html_until, content, re.I): html_until = None
        if kind is None:
            marker = _FENCE_OPEN.match(content)
            if marker and not (marker.group(1)[0] == '`' and '`' in marker.group(2)):
                kind = 'code'
                fence = (marker.group(1)[0], len(marker.group(1)), depth)
            elif _columns(content) >= 4 and (current is None or current['kind'] == 'code'):
                kind = 'code'
            elif not stripped:
                kind = 'blank'
            elif _ATX_HEADING.match(content):
                kind = 'heading'
            elif _SETEXT.match(content) and current is not None and current['kind'] in ('paragraph', 'quote', 'list'):
                current['kind'] = 'heading'
                for earlier in current['lines']: earlier['kind'] = 'heading'
                kind = 'heading_underline'
            elif _THEMATIC.match(content):
                kind = 'thematic_break'
            elif (current is not None and current['kind'] in ('paragraph', 'quote', 'list')
                  and current['lines'] and '|' in content
                  and len(_table_cells(content)) == len(_table_cells(current['lines'][-1]['content']))
                  and all(re.fullmatch(r'[ \t]*:?-+:?[ \t]*', cell) for cell in _table_cells(content))):
                if current['lines']:
                    header = current['lines'].pop()
                    header['kind'] = 'table'
                    if not current['lines']:
                        # current is the active (last appended) block.
                        blocks.pop()
                    blocks.append({'kind': 'table', 'lines': [header]})
                    current = None
                kind = 'table'
            elif current is not None and current['kind'] == 'table' and '|' in content:
                kind = 'table'
            else:
                html_start = content.lstrip(' \t')
                if html_start.startswith('<!--'): html_until = '-->'
                elif html_start.startswith('<?'): html_until = r'\?>'
                elif html_start.startswith('<![CDATA['): html_until = r'\]\]>'
                elif re.match(r'<![A-Z]', html_start): html_until = '>'
                elif re.match(r'<(?:script|pre|style|textarea)(?:[ \t>]|$)', html_start, re.I):
                    opening = re.match(r'<([A-Za-z]+)', html_start)
                    assert opening is not None
                    tag = opening.group(1)
                    html_until = '</' + tag + r'\s*>'
                elif re.match(r'</?([A-Za-z][A-Za-z0-9-]*)(?:[ \t/>]|$)', html_start):
                    opening = re.match(r'</?([A-Za-z][A-Za-z0-9-]*)', html_start)
                    assert opening is not None
                    tag = opening.group(1).lower()
                    if tag in _HTML_BLOCK_TAGS: html_until = 'blank'
                    elif (current is None or current['kind'] not in ('paragraph', 'list', 'quote')):
                        end = _tag_end(html_start, 0)
                        if end is not None and not html_start[end:].strip(' \t'):
                            html_until = 'blank'
                if html_until is not None:
                    kind = 'html_block'
                    if html_until != 'blank' and re.search(html_until, content, re.I): html_until = None
                else:
                    kind = 'list' if list_item else 'quote' if depth else 'paragraph'
        info['kind'] = kind
        lines.append(info)
        if kind in ('blank', 'thematic_break', 'heading_underline'):
            current = None
            continue
        if kind in ('code', 'frontmatter', 'html_block', 'reference_definition'):
            protected.append((start, start + len(raw) + len(ending), kind))
        continue_block = (current is not None and current['kind'] == kind
                          and kind not in ('heading', 'table', 'list'))
        if continue_block and kind == 'quote' and current is not None and current['lines'][0]['quote_depth'] != depth:
            continue_block = False
        if kind == 'list' and current is not None and current['kind'] == 'list' and not _containers(raw)[2]:
            continue_block = True
        if kind == 'paragraph' and current is not None and current['kind'] == 'quote' and depth == 0:
            continue_block = True
            info['kind'] = 'quote'
        if not continue_block:
            current = {'kind': info['kind'], 'lines': []}
            blocks.append(current)
        assert current is not None
        current['lines'].append(info)
    # Definitions are recognized only at the beginning of a completed leaf
    # paragraph. This both admits multiline labels/destinations/titles and
    # prevents a definition-shaped later row from interrupting existing prose.
    reference_blocks: list[MarkdownBlock] = []
    for block in blocks:
        rows = block['lines']
        offset = 0
        if block['kind'] in ('paragraph', 'list', 'quote', 'heading'):
            contents = [row['content'] for row in rows]
            while offset < len(rows):
                end = reference_definition_end(contents, offset)
                if end is None:
                    break
                reference_rows = rows[offset:end + 1]
                for row in reference_rows:
                    row['kind'] = 'reference_definition'
                    protected.append((row['start'], row['start'] + len(row['raw']) + len(row['ending']),
                                      'reference_definition'))
                reference_blocks.append({'kind': 'reference_definition', 'lines': reference_rows})
                offset = end + 1
        if offset < len(rows):
            reference_blocks.append({'kind': block['kind'], 'lines': rows[offset:]})
    blocks = reference_blocks
    # Inline parsing cannot cross a leaf-block boundary.
    for block in blocks:
        if block['kind'] in ('code', 'frontmatter', 'html_block', 'reference_definition'):
            continue
        first, last = block['lines'][0], block['lines'][-1]
        begin = first['start']
        finish = last['start'] + len(last['raw'])
        segment = list(text[begin:finish])
        for row in block['lines']:
            for position in range(row['start'], row['content_start']):
                segment[position - begin] = ' '
        for left, right, kind in inline_protected_spans(''.join(segment)):
            protected.append((begin + left, begin + right, kind))
    ordered = sorted(protected)
    merged = []
    for left, right, _ in ordered:
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else: merged.append((left, right))
    return {'text': text, 'lines': lines, 'blocks': blocks,
            'protected_spans': ordered, 'mask_spans': merged,
            'mask_ends': [right for _, right in merged]}


def _merged_masks(spans: Iterable[tuple[int, int, str]]) -> tuple[list[tuple[int, int]], list[int]]:
    merged = []
    for left, right, _ in sorted(spans):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged, [right for _, right in merged]


def line_visible_text(analysis: dict, line_no: int, protected_kinds: Collection[str] | None = None) -> str:
    """Mask chosen opaque kinds; default masks every protected source interval."""
    key = None if protected_kinds is None else frozenset(protected_kinds)
    cached = analysis.setdefault('_line_visible_cache', {})
    cache_key = (line_no, key)
    if cache_key in cached:
        return cached[cache_key]
    row = analysis['lines'][line_no - 1]
    start = row['start']
    end = start + len(row['raw'])
    if not analysis['protected_spans']:
        cached[cache_key] = row['raw']
        return row['raw']
    if protected_kinds is None:
        masks, ends = analysis['mask_spans'], analysis['mask_ends']
    else:
        assert key is not None
        cache = analysis.setdefault('_kind_mask_cache', {})
        if key not in cache:
            cache[key] = _merged_masks(span for span in analysis['protected_spans'] if span[2] in key)
        masks, ends = cache[key]
    begin = bisect_right(ends, start)
    if begin >= len(masks) or masks[begin][0] >= end:
        cached[cache_key] = row['raw']
        return row['raw']
    visible = list(row['raw'])
    for index in range(begin, len(masks)):
        left, right = masks[index]
        if left >= end: break
        for position in range(max(left, start), min(right, end)):
            if visible[position - start] not in '\r\n': visible[position - start] = ' '
    result = ''.join(visible)
    cached[cache_key] = result
    return result


def range_overlaps_protected(analysis: dict, start: int, end: int, protected_kinds: Collection[str] | None = None) -> bool:
    """Whether a nonempty raw-source range intersects any protected atom."""
    if end <= start: return False
    if protected_kinds is None:
        masks, ends = analysis['mask_spans'], analysis['mask_ends']
    else:
        key = frozenset(protected_kinds)
        cache = analysis.setdefault('_kind_mask_cache', {})
        if key not in cache:
            cache[key] = _merged_masks(span for span in analysis['protected_spans'] if span[2] in key)
        masks, ends = cache[key]
    index = bisect_right(ends, start)
    return index < len(masks) and masks[index][0] < end


def decode_source(data: str | bytes | bytearray) -> tuple[str, dict]:
    """入力のバイト列を、検査に使う文字列にする。lint、diff、check で同じ読み方にするための関数。

    UTF-8 として厳密に解き（読めなければ UnicodeDecodeError）、先頭の BOM を1つ外し、
    CRLF と CR を LF にそろえる。戻り値は (文字列, 情報) の組。情報は
    {"bom": BOM があったか, "eol": 元の改行コード}。eol は "lf"、"crlf"、"cr"、
    2種類以上が混ざるときは "mixed"、改行がなければ "none"。

    標準入力が StringIO のようにバイト列を読めないときは、read() した文字列を渡してよい。
    そのときは解く処理を飛ばし、BOM と改行の処理だけをする。
    """
    if isinstance(data, str):
        text = data
    else:
        text = bytes(data).decode("utf-8")
    bom = text.startswith("\ufeff")
    if bom:
        text = text[1:]
    if "\r" in text:
        crlf = text.count("\r\n")
        cr = text.count("\r") - crlf
        lf = text.count("\n") - crlf
        kinds = [name for name, count in (("lf", lf), ("crlf", crlf), ("cr", cr)) if count]
        eol = kinds[0] if len(kinds) == 1 else "mixed"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    else:
        eol = "lf" if "\n" in text else "none"
    return text, {"bom": bom, "eol": eol}


# ---- 文書の種類と読者 ----
# lint、diff、check の3本が同じ値と名前を使うので、ここに1つだけ置く（ほかは import する）。
# 公開の名前として読むだけにし、書き換えて使う使い方は約束しない。

# (値, 名前, あわせて読む domains のファイル)。順は種類の表のとおり（formal と promo、2.2.0 の script は、あとから足した）
DOC_TYPES = (
    ("pr", "PR説明", ("business.md",)),
    ("article", "技術記事", ("tech.md",)),
    ("incident", "障害報告", ("business.md",)),
    ("proposal", "提案書", ("business.md",)),
    ("minutes", "議事録", ("business.md",)),
    ("manual", "マニュアル", ("tech.md", "business.md")),
    ("slides", "スライド", ("tech.md", "business.md")),
    ("essay", "エッセイ・小説", ("essay.md",)),
    ("formal", "公用文、規程、契約書、仕様書", ("business.md", "tech.md")),
    ("promo", "紹介記事・宣伝文", ("essay.md", "business.md")),
    ("mail", "メール・チャット", ("business.md",)),
    ("paper", "論文・研究レポート", ("tech.md",)),
    ("script", "台詞・脚本", ("essay.md",)),
)
# (値, 名前)
READER_LEVELS = (
    ("expert", "同じ分野の専門家"),
    ("informed", "分野は違うが技術に詳しい人"),
    ("general", "専門知識のない人"),
)


def _normalize_choice(option: str, value: object, rows: Sequence[tuple]) -> str | None:
    """NFKC にし、前後の空白を外し、英字を小文字にして、使える値なら返す。None はそのまま返す。
    使えない値（空の文字列を含む）は、標準エラーにそのまま書ける1行の文の ValueError にする。"""
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).strip().lower()
    for row in rows:
        if row[0] == normalized:
            return normalized
    # 空や空白だけの値は、目に見えないので「（空）」と書く（--stance、--fail-on と同じ）
    shown = value if str(value).strip() else "（空）"
    # 値の一覧の閉じ括弧と「です」の間に空白を入れない（設計の文どおり。反証で見つけた例）
    raise ValueError("{} に使えない値です: {}。使えるのは {}です。".format(
        option, shown, "、".join("{}（{}）".format(row[0], row[1]) for row in rows)))


def normalize_doc_type(value: object) -> str | None:
    """--doc-type の値を正規化する（SLIDES、前後の空白、全角も slides）。None はそのまま。使えない値は ValueError。"""
    return _normalize_choice("--doc-type", value, DOC_TYPES)


def normalize_reader(value: object) -> str | None:
    """--reader の値を正規化する。None はそのまま。使えない値は ValueError。"""
    return _normalize_choice("--reader", value, READER_LEVELS)


def context_label(doc_type: object, reader: object) -> str:
    """lint と diff の人が読む出力で、種類と読者を書く行の初めの部分（「文書の種類: スライド（slides）、読者: 指定なし。」）。"""
    doc_type, reader = normalize_doc_type(doc_type), normalize_reader(reader)
    kinds, readers = dict(row[:2] for row in DOC_TYPES), dict(READER_LEVELS)
    return "文書の種類: {}、読者: {}。".format(
        "{}（{}）".format(kinds[doc_type], doc_type) if doc_type else "指定なし",
        "{}（{}）".format(readers[reader], reader) if reader else "指定なし")


# ---- 語の一覧（.yomiyasu-words/ の allow.txt と flag.txt）----
# lint、diff、check、フックの4本が同じ探し方と読み方を使うので、ここに1つだけ置く。
# .git まで上へたどり、linked worktree に一覧がなければ元の checkout を探す。.yomiyasu/ の中は探さない。

WORDS_FOLDER = ".yomiyasu-words"
# (キーの先頭に付ける語, ファイルの名前)。context.words のキーと出力の行の順もこの順
WORDS_FILES = (("allow", "allow.txt"), ("flag", "flag.txt"))
WORDS_MAX_LINES = 10000
# 3.0.0: 語の正規表現の一覧（1行に「名前<TAB>正規表現」）。WORDS_FILES とは別に読み、ファイルがあるときだけ context.words に
# flag_patterns_lines と flag_patterns_sha256 を足す（ないときの出力は前と一字も同じ）
PATTERNS_FILE = "flag-patterns.txt"
PATTERNS_MAX = 500              # パターンの数
PATTERN_NAME_MAX = 40           # 名前の字数
PATTERN_MAX_LENGTH = 200        # 正規表現の字数
PATTERN_MAX_REPEAT = 30         # {m,n} の n
PATTERN_MAX_COST = 512          # 1つのパターンが1か所で試す数（繰り返しの幅と選択肢の数の積）
PATTERNS_MAX_COST = 512         # 全パターンの試す数の合計（時間はこの合計にほぼ比例する。10万字の行で、最短一致の繰り返しを重ねた最悪の組が手元の macOS で約0.7秒、CI の Linux でも2秒より十分短く終わる数。1,024 では CI で2秒を超えた）
# ないファイル（とフォルダ）は一覧なし。ほかの読めない理由は終了コード2
_WORDS_ABSENT = (FileNotFoundError, NotADirectoryError)


class WordsError(Exception):
    """語の一覧を読めない（ないフォルダの --words、UTF-8 でない、1万行を超える、開けない）。終了コード2にする。
    str() は標準エラーにそのまま書ける1行の文（入力の誤りの「Error opening file …」と同じ形）。"""


def _words_home(value: str) -> str:
    """--words の値の頭の ~ を、ホームフォルダに置き換える（check と hook の _home_path と同じ決まり）。"""
    if isinstance(value, str) and (value == "~" or value[:2] in ("~/", "~" + os.sep)):
        try:
            configured = (os.environ.get("USERPROFILE", os.environ.get("HOMEDRIVE", "") + os.environ.get("HOMEPATH", ""))
                          if os.name == "nt" else os.environ.get("HOME"))
            if configured is not None and not os.path.splitdrive(configured)[1].strip().strip("/" + os.sep):
                return value
            home = str(Path("~").expanduser())
            expanded = str(Path(value).expanduser())
        except Exception:  # pwd を読めない環境など
            return value
        if (not home.startswith("~") and os.path.splitdrive(home)[1].strip().strip("/" + os.sep)
                and not expanded.startswith("~")):
            return expanded
    return value


def _worktree_words_folder(git_file: Path) -> Path | None:
    """linked worktree の管理ファイルを読み、元の checkout の語の一覧を探す。読めなければ None。"""
    try:
        marker = git_file.read_text(encoding="utf-8").strip()
        if not marker.startswith("gitdir:"):
            return None
        target = marker.removeprefix("gitdir:").strip()
        if not target:
            return None
        git_dir = git_file.parent / target
        common = (git_dir / "commondir").read_text(encoding="utf-8").strip()
        if not common:
            return None
        common_dir = Path(absolute_path(str(git_dir / common)))
        folder = common_dir.parent / WORDS_FOLDER
        return folder if _path_matches(folder.is_dir) else None
    except (OSError, UnicodeError, ValueError):
        return None


def find_words_folder(cwd: str | None, option: str | None = None) -> str | None:
    """語の一覧のフォルダの絶対パスか None（フォルダがない）。

    1 option（--words）があれば、そのフォルダ（相対パスは cwd から。ないかフォルダでなければ WordsError）。
    2 cwd から上へたどり、.git（フォルダでもファイルでもよい）がある最初のフォルダの .yomiyasu-words/。
    .git がファイルで一覧のフォルダがなければ、gitdir と commondir から元の checkout の一覧を探す。
    3 git の外では cwd の .yomiyasu-words/。2と3は、フォルダがなければ None。cwd が None（作業ディレクトリを
    読めない）ときは、2と3を探さずに None、相対パスの option は WordsError。"""
    if option is not None:
        value = _words_home(option)
        if not str(value).strip():
            raise WordsError("--words に空の値は使えません")
        if not Path(value).is_absolute():
            if cwd is None:
                raise WordsError("Error opening folder {}: 作業ディレクトリを読めないため、相対パスを決められません".format(option))
            value = str(Path(cwd) / value)
        folder = absolute_path(value)
        if not _path_matches(Path(folder).is_dir):
            reason = "フォルダではありません" if _path_matches(Path(folder).exists) else "フォルダがありません"
            raise WordsError("Error opening folder {}: --words の{}".format(option, reason))
        return folder
    if cwd is None:
        return None
    origin = Path(absolute_path(cwd))
    current = origin
    while True:
        git_path = current / ".git"
        if _path_matches(git_path.exists):
            folder = current / WORDS_FOLDER
            break
        parent = current.parent
        if parent == current:
            folder = origin / WORDS_FOLDER
            break
        current = parent
    if _path_matches(folder.is_dir):
        return str(folder)
    fallback = _worktree_words_folder(git_path) if _path_matches(git_path.is_file) else None
    return str(fallback) if fallback is not None else None


def _words_lines(path: str, data: bytes) -> list[str]:
    """空行とコメントを除いた行を返す。前後の空白と TAB は残す。
    UTF-8 でないときと1万行を超えるときは WordsError（行番号つき）。"""
    return [row for row in _words_text_rows(path, data) if row.strip() and not row.lstrip().startswith("#")]


def _words_text_rows(path: str, data: bytes) -> list[str]:
    """1つのファイルのバイト列を行の並びにする（BOM を外し、改行をそろえる）。UTF-8 でないときと1万行を超えるときは
    WordsError（行番号つき）。"""
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        before = data[:error.start]
        line = before.count(b"\n") + before.count(b"\r") - before.count(b"\r\n") + 1
        raise WordsError("Error opening file {}: UTF-8 として読めません（{}行目）".format(path, line))
    text = decode_source(data)[0]
    rows = text.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    if len(rows) > WORDS_MAX_LINES:
        raise WordsError("Error opening file {}: 行が多すぎます（{}行目。{:,}行までです）".format(
            path, WORDS_MAX_LINES + 1, WORDS_MAX_LINES))
    return rows


class _PatternError(ValueError):
    """flag-patterns.txt の1行の正規表現を使えない理由。"""


_PATTERN_META = frozenset(".^$*+?{}[]\\|()")
# \ のあとに書ける英字（字の種類と、幅のない位置）。\z（3.14 から）、\x、\u、\N、後方参照などは使えない
_PATTERN_ESCAPE_CLASS = frozenset("dDwWsS")
_PATTERN_ESCAPE_ZERO = frozenset("bBAZ")
_PATTERN_ESCAPE_CHAR = {"t": "\t", "n": "\n"}


def _pattern_escape(pattern: str, index: int, in_class: bool) -> tuple[int, str, str | None]:
    """index の \\ のあと。(次の位置, 種類（"lit"、"cls"、"zero"）, 字か None)。"""
    if index + 1 >= len(pattern):
        raise _PatternError("行の終わりに \\ だけがあります")
    char = pattern[index + 1]
    if char in _PATTERN_ESCAPE_CLASS:
        return index + 2, "cls", None
    if char in _PATTERN_ESCAPE_CHAR:
        return index + 2, "lit", _PATTERN_ESCAPE_CHAR[char]
    if char in _PATTERN_ESCAPE_ZERO and not in_class:
        return index + 2, "zero", None
    if char.isascii() and char.isalnum():
        raise _PatternError("\\{} は使えません（使えるのは \\d \\D \\w \\W \\s \\S \\b \\B \\A \\Z \\t \\n と、記号の前の \\）"
                            .format(char))
    return index + 2, "lit", char


def _pattern_class(pattern: str, index: int) -> int:
    """index の [ から ] までの字の組。次の位置。入れ子の [ と、--、&&、~~、|| は断る（Python が FutureWarning を出す）。"""
    position = index + 1
    if position < len(pattern) and pattern[position] == "^":
        position += 1
    first = True
    previous = None
    while True:
        if position >= len(pattern):
            raise _PatternError("[ が閉じていません")
        char = pattern[position]
        if char == "]" and not first:
            return position + 1
        if char == "\\":
            position = _pattern_escape(pattern, position, True)[0]
            previous = None
        else:
            if char == "[":
                raise _PatternError("[ ] の中の [ は \\[ と書いてください")
            if char in "-&~|" and previous == char:
                raise _PatternError("[ ] の中の {0}{0} は使えません（\\{0} と書いてください）".format(char))
            previous = char
            position += 1
        first = False


def _pattern_sequence(pattern: str, index: int, depth: int) -> tuple[int, list[list[str]], int]:
    """選択肢の並びを読む。(次の位置, 選択肢ごとの必ず当たる字の並びのリスト, 試す数)。試す数は、選択肢の試す数の和。"""
    branches = []
    runs = []
    run = ""
    cost = 1
    total = 0
    while index < len(pattern) and pattern[index] != ")":
        char = pattern[index]
        if char == "|":
            if run:
                runs.append(run)
            branches.append(runs)
            total += cost
            runs, run, cost = [], "", 1
            index += 1
            continue
        inner_runs = None
        if char == "(":
            if pattern.startswith("(?:", index):
                kind, start = "group", index + 3
            elif pattern.startswith("(?=", index) or pattern.startswith("(?!", index):
                kind, start = "look", index + 3
            elif pattern.startswith("(?<=", index) or pattern.startswith("(?<!", index):
                kind, start = "look", index + 4
            elif pattern.startswith("(?", index):
                raise _PatternError("(? の組は (?: (?= (?! (?<= (?<! だけです（印、名前、原子団、注釈、条件は使えません）")
            else:
                raise _PatternError("取り込む組 ( ) は使えません。(?: ) と書いてください")
            end, inner, inner_cost = _pattern_sequence(pattern, start, depth + 1)
            if end >= len(pattern):
                raise _PatternError("( が閉じていません")
            end += 1
            single = False
            if kind == "group" and len(inner) == 1:
                inner_runs = inner[0]
            atom_kind = kind
        elif char == "[":
            end, atom_kind, literal, inner_cost, single = _pattern_class(pattern, index), "cls", None, 1, True
        elif char == "\\":
            end, atom_kind, literal = _pattern_escape(pattern, index, False)
            inner_cost, single = 1, atom_kind != "zero"
        elif char == ".":
            end, atom_kind, literal, inner_cost, single = index + 1, "cls", None, 1, True
        elif char in "^$":
            end, atom_kind, literal, inner_cost, single = index + 1, "zero", None, 1, False
        elif char in _PATTERN_META:
            raise _PatternError("{0} は、字として使うなら \\{0} と書いてください（繰り返しなら、前に字か組が要ります）".format(char))
        else:
            end, atom_kind, literal, inner_cost, single = index + 1, "lit", char, 1, True
        # 繰り返し
        quantifier = pattern[end] if end < len(pattern) else ""
        width, optional, repeated = 1, False, False
        if quantifier in ("*", "+"):
            raise _PatternError("上限のない繰り返し（* と +）は使えません。{0,30} のように上限を書いてください")
        if quantifier == "{":
            close = pattern.find("}", end)
            body = pattern[end + 1:close] if close >= 0 else ""
            pieces = body.split(",")
            if close < 0 or len(pieces) > 2 or not all(piece.isdigit() and piece.isascii() for piece in pieces):
                raise _PatternError("{ の書き方は {m} か {m,n} です（上限のない {m,} と、{,n} は使えません）")
            low, high = int(pieces[0]), int(pieces[-1])
            if high > PATTERN_MAX_REPEAT or low > high:
                raise _PatternError("繰り返しの上限は {} までです".format(PATTERN_MAX_REPEAT))
            if not single:
                raise _PatternError("{m,n} を付けられるのは1字の要素だけです（組に付けられるのは ? だけです）")
            width, optional, repeated, end = high - low + 1, low == 0, high > 1, close + 1
        elif quantifier == "?":
            if atom_kind in ("zero", "look"):
                raise _PatternError("幅のない位置（^ $ \\b や先読み・後読み）には ? を付けられません")
            width, optional, end = 2, True, end + 1
        if quantifier in ("{", "?") and end < len(pattern):
            if pattern[end] == "+":
                raise _PatternError("所有の繰り返し（?+ など）は Python 3.9 で使えません")
            if pattern[end] == "?":
                end += 1        # 最短一致
            if end < len(pattern) and pattern[end] in "*+?{":
                raise _PatternError("繰り返しが重なっています")
        # 必ず当たる字（? と {0,n} の外で、先読み・後読みの外の字）
        if atom_kind == "lit" and not optional:
            assert literal is not None      # "lit" の要素はいつも字を持つ
            run += literal
            if repeated:
                # x{m,n} の x は2回以上続くことがあるので、x の前と後で字の並びを分ける（ba{2}c は ba と ac）
                runs.append(run)
                run = literal
        else:
            if run:
                runs.append(run)
                run = ""
            if inner_runs is not None and not optional:
                runs.extend(inner_runs)
        cost *= width * inner_cost
        if cost > PATTERN_MAX_COST:
            raise _PatternError("試す組み合わせが多すぎます（繰り返しの幅と選択肢の数の積は {:,} までです）".format(PATTERN_MAX_COST))
        index = end
    if run:
        runs.append(run)
    branches.append(runs)
    total += cost
    if total > PATTERN_MAX_COST:
        raise _PatternError("試す組み合わせが多すぎます（繰り返しの幅と選択肢の数の積は {:,} までです）".format(PATTERN_MAX_COST))
    return index, branches, total


def check_pattern(pattern: str) -> tuple[re.Pattern[str], tuple[tuple[str, ...], ...], int]:
    """flag-patterns.txt の正規表現を確かめる。(組んだ正規表現, 一番上の選択肢ごとの必ず当たる字の並び, 試す数)。
    使えない書き方は _PatternError（理由の文）。Python の版で意味の変わる書き方と、手間が行の長さに比例しない書き方を断る。"""
    import warnings
    if not pattern:
        raise _PatternError("正規表現が空です")
    if len(pattern) > PATTERN_MAX_LENGTH:
        raise _PatternError("正規表現は {} 字までです".format(PATTERN_MAX_LENGTH))
    end, branches, cost = _pattern_sequence(pattern, 0, 0)
    if end != len(pattern):
        raise _PatternError(") が多すぎます")
    required = []
    for runs in branches:
        runs = tuple(run for run in runs if run.strip())
        if not runs:
            raise _PatternError("どの選択肢にも、? や繰り返し、先読み・後読みの外に、必ず当たる字を1字以上書いてください")
        required.append(runs)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compiled = re.compile(pattern)
        except re.error as error:
            raise _PatternError("正規表現の誤り（{}）".format(error))
    if caught:
        raise _PatternError("Python が警告を出す書き方です（{}）".format(caught[0].message))
    if compiled.groups:
        raise _PatternError("取り込む組 ( ) は使えません。(?: ) と書いてください")
    return compiled, tuple(required), cost


def _patterns_lines(path: str, data: bytes) -> list[tuple[str, str, re.Pattern[str], tuple[tuple[str, ...], ...]]]:
    """flag-patterns.txt のバイト列を [(名前, 正規表現の文字列, 組んだ正規表現, 必ず当たる字の並び)] にする。
    使えない行は WordsError（ファイル名と行番号つき）。"""
    rows = _words_text_rows(path, data)
    patterns = []
    total = 0
    for number, row in enumerate(rows, 1):
        if not row.strip() or row.lstrip().startswith("#"):
            continue
        if "\t" not in row:
            raise WordsError("Error opening file {}: {}行目に、名前と正規表現を分けるタブがありません".format(path, number))
        name, pattern = row.split("\t", 1)
        # 正規表現の前後は半角の空白とタブだけを除く（全角の空白は正規表現の字として残す。空白で終わる形は [ ] と書く）
        name, pattern = name.strip(), pattern.strip(" \t")
        if not name:
            raise WordsError("Error opening file {}: {}行目の名前が空です".format(path, number))
        if len(name) > PATTERN_NAME_MAX:
            raise WordsError("Error opening file {}: {}行目の名前は {} 字までです".format(path, number, PATTERN_NAME_MAX))
        if len(patterns) >= PATTERNS_MAX:
            raise WordsError("Error opening file {}: パターンが多すぎます（{}行目。{:,}個までです）".format(
                path, number, PATTERNS_MAX))
        try:
            compiled, required, cost = check_pattern(pattern)
        except _PatternError as error:
            raise WordsError("Error opening file {}: {}行目の正規表現を使えません（{}）".format(path, number, error))
        total += cost
        if total > PATTERNS_MAX_COST:
            raise WordsError("Error opening file {}: {}行目までで、試す組み合わせの合計が多すぎます（{:,} までです）".format(
                path, number, PATTERNS_MAX_COST))
        patterns.append((name, pattern, compiled, required))
    return patterns


def load_words(folder: str) -> dict | None:
    """フォルダの allow.txt と flag.txt を読む。どちらもないときは None（一覧なし）。

    戻り値は {"path": フォルダ, "allow": 語のタプル, "flag": 語のタプル, "allow_lines": 語の数, "flag_lines": 語の数,
    "allow_sha256": 中身の SHA-256 か None, "flag_sha256": …, "flag_replacements": {使わない語: 使う語}}。
    flag は TAB の左だけ。ないほうのファイルは、語なし、数0、SHA-256 は None。
    3.0.0: flag-patterns.txt があれば、"flag_patterns"（(名前, 正規表現の文字列, 組んだ正規表現, 必ず当たる字の並び) の
    タプル）、"flag_patterns_lines"（パターンの数）、"flag_patterns_sha256" も足す（ないときは、この3つのキーを足さない）。
    flag-patterns.txt だけがあっても一覧ありとみなす。読めないファイルと使えないパターンは WordsError。"""
    import hashlib
    result = {"path": folder}
    found = False
    for key, name in WORDS_FILES + (("flag_patterns", PATTERNS_FILE),):
        path = str(Path(folder) / name)
        try:
            with Path(path).open("rb") as handle:
                data = handle.read()
        except _WORDS_ABSENT:
            if key == "flag_patterns":
                continue
            words, digest = [], None
        except (OSError, ValueError) as error:
            reason = getattr(error, "strerror", None) or error
            raise WordsError("Error opening file {}: ファイルを開けません（{}）".format(path, reason))
        else:
            found = True
            reader = _patterns_lines if key == "flag_patterns" else _words_lines
            words, digest = reader(path, data), hashlib.sha256(data).hexdigest()
        result[key] = tuple(words)
        result[key + "_lines"] = len(words)
        result[key + "_sha256"] = digest
    result["allow"] = tuple(row.strip() for row in result["allow"])
    flag_parts = (row.partition("\t") for row in result["flag"])
    flag_entries = [(word.strip(), replacement.strip()) for word, _, replacement in flag_parts if word.strip()]
    result["flag"] = tuple(word for word, _ in flag_entries)
    result["flag_replacements"] = {word: replacement for word, replacement in flag_entries if replacement}
    for key, _ in WORDS_FILES:
        result[key + "_lines"] = len(result[key])
    return result if found else None


def resolve_words(cwd: str | None, option: str | None = None, disabled: bool = False) -> dict | None:
    """--words と --no-words から語の一覧を決める。一覧を使うときは load_words の値、使わないときは None。
    disabled（--no-words）なら探さない。cwd は作業ディレクトリ（読めなければ None）。読めない一覧は WordsError。"""
    if disabled:
        return None
    folder = find_words_folder(cwd, option)
    return load_words(folder) if folder is not None else None


def current_directory() -> str | None:
    """作業ディレクトリか、読めない（消えた）ときは None。"""
    try:
        return str(Path.cwd())
    except OSError:
        return None


# ---- コマンドラインで渡されたファイルを読む範囲（3.0.0）----
# lint、diff、check の3本は、コマンドラインで名前を渡されたファイルのうち、作業フォルダの中で、作業フォルダからの道筋に
# 点で始まる部分（.env、.git/、sub/.secret/ など）がないものだけを読む。編集中の文書に紛れ込んだ指示で、事前に許された
# コマンドが鍵や認証のファイルを読んで中身を出さないようにするため。標準入力（-）はいつでも読める。道具が自分で探すフォルダ
# （状態フォルダ .yomiyasu/、語の一覧 .yomiyasu-words/、references/lists/）と --words のフォルダは、ここでは見ない。

INPUT_PATH_OUTSIDE = "作業フォルダの外にあるファイルは読みません"
INPUT_PATH_HIDDEN = "名前が点で始まるファイルと、名前が点で始まるフォルダの中のファイルは読みません"
INPUT_PATH_NO_CWD = "作業フォルダを読めないため、読んでよいファイルか決められません"


def input_path_problem(path: str) -> str | None:
    """コマンドラインで渡されたファイルのパスを読んでよいか。読んでよければ None、読まないなら理由の文
    （INPUT_PATH_OUTSIDE、INPUT_PATH_HIDDEN、INPUT_PATH_NO_CWD のどれか）を返す。ファイルは開かない。

    - は標準入力なので読んでよい。ほかは、シンボリックリンクをたどった本当の場所（os.path.realpath）で比べる。
    作業フォルダの外（Windows でドライブが違うときも）か、作業フォルダからの道筋に点で始まる部分があれば読まない。
    パスに NUL を含むときは None を返し、開くときの誤りに任せる（どこも開けない）。ほかの理由で場所を決められないときは
    外とみなす。"""
    if path == "-":
        return None
    try:
        base = os.path.normcase(os.path.realpath(os.getcwd()))  # noqa: PTH109 -- same os module as the os.path calls (tests swap it for ntpath)
    except OSError:
        return INPUT_PATH_NO_CWD
    if "\0" in path:
        return None
    try:
        target = os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError, TypeError):
        return INPUT_PATH_OUTSIDE
    parts = _parts_inside(base, target)
    if parts is None:
        return INPUT_PATH_OUTSIDE
    if any(part.startswith(".") for part in parts):
        return INPUT_PATH_HIDDEN
    return None


def _parts_inside(base: str, target: str) -> list[str] | None:
    """target が作業フォルダ base の中なら、base からの道筋の部分のリスト（base そのものなら空）、外なら None。

    まず文字列で比べる。合わないときは、target から上のフォルダをたどり、base と同じフォルダ（os.path.samestat）が
    あるかを見る。macOS で大文字と小文字だけが違うパスや、日本語の名前の NFC と NFD だけが違うパスは、realpath と
    normcase では同じ文字列にならないが、同じフォルダなので中とみなす（3.0.0）。"""
    try:
        if os.path.commonpath([base, target]) == base:
            relative = os.path.relpath(target, base)
            return [] if relative == os.curdir else relative.split(os.sep)  # noqa: PTH206 -- split relpath by the os.path flavor
    except ValueError:
        # Windows でドライブが違う（C: と D:）など。下で同じフォルダかを見る
        pass
    try:
        base_stat = os.stat(base)  # noqa: PTH116 -- paired with os.path.samestat on the same os module
    except (OSError, ValueError):
        return None
    if not getattr(base_stat, "st_ino", 0):
        # ファイルの番号を持たないファイルシステムでは、同じフォルダかを決められない
        return None
    parts = []
    current = target
    while True:
        try:
            if os.path.samestat(os.stat(current), base_stat):  # noqa: PTH116 -- paired with os.path.samestat
                parts.reverse()
                return parts
        except (OSError, ValueError):
            pass
        parent, name = os.path.split(current)
        if not name or parent == current:
            return None
        parts.append(name)
        current = parent


def words_context(words: dict) -> dict:
    """JSON の context.words と check の記録の options.words に入れる5つのキー（この順）。flag-patterns.txt があるときだけ、
    そのあとに flag_patterns_lines と flag_patterns_sha256 を足して7つにする。"""
    context = {"path": words["path"], "allow_lines": words["allow_lines"], "flag_lines": words["flag_lines"],
               "allow_sha256": words["allow_sha256"], "flag_sha256": words["flag_sha256"]}
    if words.get("flag_patterns_sha256") is not None:
        context["flag_patterns_lines"] = words["flag_patterns_lines"]
        context["flag_patterns_sha256"] = words["flag_patterns_sha256"]
    return context


def words_label(context: dict) -> str:
    """人が読む出力の「語の一覧: <パス>（allow N語、flag N語）。」。flag-patterns.txt があれば「、flag-patterns N行」を足す。
    context は words_context の値（読むだけ）。"""
    patterns = ("、flag-patterns {}行".format(context["flag_patterns_lines"])
                if context.get("flag_patterns_sha256") is not None else "")
    return "語の一覧: {}（allow {}語、flag {}語{}）。".format(context["path"], context["allow_lines"], context["flag_lines"],
                                                           patterns)
