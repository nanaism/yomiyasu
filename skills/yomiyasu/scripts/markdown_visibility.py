"""Shared, dependency-free Markdown visibility for lint candidates.

Offsets are half-open Python string positions. This is a targeted scanner,
not a claim to implement every CommonMark or GFM construct.
"""

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
_BARE_URL = re.compile(r'(?:https?://|www\.)[^\s<>]+')
_REFERENCE_LABEL = re.compile(r'^ {0,3}\[((?:\\.|[^\[\]\\]){1,999})\]:[ \t]*')
_BLANK_TITLE_LINE = re.compile(r'(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)')
_SETEXT = re.compile(r'^ {0,3}(?:=+|-+)[ \t]*$')
_THEMATIC = re.compile(r'^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$')
_INLINE_EVENTS = re.compile(r'[\\`<\[\]hw]')


def unicode_whitespace(ch):
    if not ch: return True
    if len(ch) > 1:
        return all(unicode_whitespace(c) for c in ch)
    return ch in '\t\n\r\f' or unicodedata.category(ch) == 'Zs'


def _escaped(text, position):
    start = position
    while start > 0 and text[start - 1] == '\\':
        start -= 1
    return (position - start) % 2 == 1


def _tag_space_end(text, start):
    """Spaces/tabs and at most one Markdown line ending, not Python isspace."""
    pos = start
    while pos < len(text) and text[pos] in ' \t': pos += 1
    if text.startswith('\r\n', pos): pos += 2
    elif pos < len(text) and text[pos] in '\r\n': pos += 1
    while pos < len(text) and text[pos] in ' \t': pos += 1
    return pos


def _terminator_positions(text):
    return {token: [match.start() for match in re.finditer(re.escape(token), text)]
            for token in ('-->', '?>', ']]>', '>')}


def _tag_end(text, start, terminators=None):
    def closed(token, begin):
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


def _link_end(text, opening):
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


def inline_protected_spans(text):
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
            match = _BARE_URL.match(text, pos)
            if match:
                end = match.end()
                # New www recognition is restricted to published GFM boundaries
                # and a valid ASCII domain. Adjacent-Japanese policy is not widened.
                www = text.startswith('www.', pos)
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


def _columns(text):
    columns = 0
    for ch in text:
        if ch == ' ': columns += 1
        elif ch == '\t': columns += 4 - columns % 4
        else: break
    return columns


def _containers(raw, allow_list=True):
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


def _physical_lines(text):
    rows = []
    start = 0
    for ending in re.finditer(r'\r\n|\r|\n', text):
        rows.append((start, text[start:ending.start()], ending.group(0)))
        start = ending.end()
    rows.append((start, text[start:], ''))
    return rows


def _reference_definition(content):
    """Only a complete one-line definition is hidden; never hide trailing prose."""
    return reference_definition_end([content], 0) == 0


def _table_cells(content):
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
    def __init__(self, lines, row, column=0):
        self.lines = lines
        self.row = row
        self.column = column

    def char(self):
        line = self.lines[self.row]
        if self.column < len(line):
            return line[self.column]
        return '\n' if self.row + 1 < len(self.lines) else None

    def following(self):
        line = self.lines[self.row]
        return line[self.column + 1] if self.column + 1 < len(line) else None

    def advance(self):
        if self.column < len(self.lines[self.row]):
            self.column += 1
        elif self.row + 1 < len(self.lines):
            self.row += 1
            self.column = 0

    def escape(self):
        if self.char() == '\\' and self.following() in _ASCII_PUNCT:
            self.advance()
            self.advance()
            return True
        return False


def _reference_gap(cursor):
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


def _reference_destination(cursor):
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
    while cursor.char() is not None and cursor.char() not in (' ', '\t', '\n'):
        ch = cursor.char()
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


def _reference_title_end(cursor):
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


def reference_definition_end(lines, start, paragraph_context=False):
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
    while cursor.char() is not None and cursor.char() != ']':
        ch = cursor.char()
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


def analyze_markdown(text, skip_frontmatter=True):
    lines = []
    blocks = []
    protected = []
    current = None
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
        info = {'line': index + 1, 'raw': raw, 'start': start, 'ending': ending,
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
            marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', content)
            if marker and not (marker.group(1)[0] == '`' and '`' in marker.group(2)):
                kind = 'code'
                fence = (marker.group(1)[0], len(marker.group(1)), depth)
            elif _columns(content) >= 4 and (current is None or current['kind'] == 'code'):
                kind = 'code'
            elif not stripped:
                kind = 'blank'
            elif re.match(r'^ {0,3}#{1,6}(?:[ \t]+|$)', content):
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
                    if not current['lines']: blocks.remove(current)
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
                    tag = re.match(r'<([A-Za-z]+)', html_start).group(1)
                    html_until = '</' + tag + r'\s*>'
                elif re.match(r'</?([A-Za-z][A-Za-z0-9-]*)(?:[ \t/>]|$)', html_start):
                    tag = re.match(r'</?([A-Za-z][A-Za-z0-9-]*)', html_start).group(1).lower()
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
        if continue_block and kind == 'quote' and current['lines'][0]['quote_depth'] != depth:
            continue_block = False
        if kind == 'list' and current is not None and current['kind'] == 'list' and not _containers(raw)[2]:
            continue_block = True
        if kind == 'paragraph' and current is not None and current['kind'] == 'quote' and depth == 0:
            continue_block = True
            info['kind'] = 'quote'
        if not continue_block:
            current = {'kind': info['kind'], 'lines': []}
            blocks.append(current)
        current['lines'].append(info)
    # Definitions are recognized only at the beginning of a completed leaf
    # paragraph. This both admits multiline labels/destinations/titles and
    # prevents a definition-shaped later row from interrupting existing prose.
    reference_blocks = []
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


def _merged_masks(spans):
    merged = []
    for left, right, _ in sorted(spans):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged, [right for _, right in merged]


def line_visible_text(analysis, line_no, protected_kinds=None):
    """Mask chosen opaque kinds; default masks every protected source interval."""
    key = None if protected_kinds is None else frozenset(protected_kinds)
    cached = analysis.setdefault('_line_visible_cache', {})
    cache_key = (line_no, key)
    if cache_key in cached:
        return cached[cache_key]
    row = analysis['lines'][line_no - 1]
    start = row['start']
    end = start + len(row['raw'])
    if protected_kinds is None:
        masks, ends = analysis['mask_spans'], analysis['mask_ends']
    else:
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


def range_overlaps_protected(analysis, start, end, protected_kinds=None):
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
