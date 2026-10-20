#!/usr/bin/env python3
"""Optional local hooks. Installation only prints configuration; never edits it."""
import sys
sys.dont_write_bytecode = True
import json
import os

__version__ = "2.1.0"
_EVENTS = ("UserPromptExpansion", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd")
_BUDGETS = {"UserPromptExpansion": 4, "UserPromptSubmit": 4, "PreToolUse": 7,
            "PostToolUse": 7, "Stop": 20, "SessionEnd": 0.8}
_LIMITS = {"max_stop_blocks": 2, "max_runs": 3, "deadline_min": 30}
_MAX_INPUT = 4 * 1024 * 1024
_MAX_TEXT = 2 * 1024 * 1024
_HELP = """使い方: yomiyasu_hook.py --host claude-code|codex [--state-dir DIR]
       yomiyasu_hook.py --print-config claude-code|codex
       yomiyasu_hook.py --version

任意のフックです。利用者が Claude Code か Codex の設定ファイルに貼ったときだけ、ホストが決まった時点で呼びます。
登録した原稿（yomiyasu_check.py start）について、返答の終わりに最終稿が検査記録と合うかを確かめ、合わなければ作業を
続けさせます。登録した原稿に関係する投稿で、本文が検査記録と照合できないときは止めます。読みやすさの合格や、意味が
保たれたかは判定しません。登録していない原稿には何もしません。

引数:
  --host claude-code|codex  フックとして動きます。ホストのイベントの JSON を標準入力から読みます。
  --state-dir DIR           登録を探す状態フォルダ。省くと環境変数 YOMIYASU_STATE_DIR（空白だけの値と ${ を
                            含む値は使いません）、git の最上位（なければ作業ディレクトリ）の .yomiyasu/ の順に探します。
                            Claude Code では、環境変数 CLAUDE_PROJECT_DIR のプロジェクトの .yomiyasu/ も探します。
  --print-config claude-code|codex
                            設定に貼る JSON の例（このスクリプトの絶対パス入り）を出します。設定ファイルには書き込みません。
  --version                 版を表示して終わります。
  -h, --help                このヘルプを表示して終わります。

終了コード:
  0  フックとして呼ばれたとき（--host）は、いつも0です。入力や引数が違っても、登録がなくても、内部の誤りでも、
     ホストの作業を止めないよう何も出さずに終わります（知らない引数も無視します）。作業を続けさせるときと投稿を
     止めるときは、終了コードではなく標準出力の JSON で伝えます。内部の誤りは、check が作った状態フォルダが
     あれば、その hook-errors.log に1行残します。-h、--version、--print-config も0です。
  2  --print-config の値がないか、claude-code でも codex でもない（標準エラーに使える値を出します）。"""
_PRINT_CONFIG_ERROR = "--print-config には claude-code か codex を渡してください。"


def _options(argv):
    # No argparse (or check) on the unregistered fast path. Invalid flags are silent.
    result = {}
    index = 0
    while index < len(argv):
        key = argv[index]
        if key in ("--version", "-h", "--help"):
            result[key] = True
            index += 1
        elif key in ("--host", "--state-dir", "--print-config") and index + 1 < len(argv):
            result[key] = argv[index + 1]
            index += 2
        elif key == "--print-config":
            # A missing value is reported by main (exit 2); --print-config is never in a host's settings.
            result[key] = None
            index += 1
        else:
            return None
    return result


def _project_state(cwd):
    current = cwd
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return os.path.join(current, ".yomiyasu")
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.join(cwd, ".yomiyasu")
        current = parent


def _home_path(value):
    """A leading ~ in --state-dir or YOMIYASU_STATE_DIR becomes the home folder (same rule as check._home_path).

    Only "~" alone and "~/" (also "~\\" on Windows) are expanded, with os.path.expanduser. "~user/x" and "~x" are kept.
    When the home folder cannot be found (the result still starts with ~, or expanduser raised), the value is kept,
    as before (a path relative to cwd). A home folder that is empty, blank or only a root ("/", or "C:\\" on Windows)
    also counts as not found: with HOME set to "", expanduser turns "~/x" into "/x" and "~" into "/", and the state
    folder must not land at the filesystem root (HOME="/" gives the same results, so the two cannot be told apart).
    """
    if isinstance(value, str) and (value == "~" or value[:2] in ("~/", "~" + os.sep)):
        try:
            home = os.path.expanduser("~")
            expanded = os.path.expanduser(value)
        except Exception:
            return value
        if (not home.startswith("~") and os.path.splitdrive(home)[1].strip().strip("/" + os.sep)
                and not expanded.startswith("~")):
            return expanded
    return value


def _state_given(option):
    """The first state folder came from --state-dir or YOMIYASU_STATE_DIR (same test as _states and check)."""
    env = os.environ.get("YOMIYASU_STATE_DIR", "")
    return bool(option) or bool(env.strip() and "${" not in env)


def _states(cwd, host, option):
    candidates = []
    env = os.environ.get("YOMIYASU_STATE_DIR", "")
    for value in (option, env if env.strip() and "${" not in env else None):
        if value:
            candidates.append(os.path.abspath(os.path.join(cwd, _home_path(value))))
    candidates.append(_project_state(cwd))
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if host == "claude-code" and project and "${" not in project:
        candidates.append(_project_state(os.path.abspath(project)))
    result, seen = [], set()
    for path in candidates:
        key = os.path.normcase(os.path.realpath(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _invocation(data, host, event):
    if event == "UserPromptExpansion" and host == "claude-code":
        if data.get("command_name") in ("yomiyasu", "yomiyasu:yomiyasu"):
            args = data.get("command_args")
            return args if isinstance(args, str) else None
    if event == "UserPromptSubmit":
        prompt = data.get("prompt")
        if not isinstance(prompt, str):
            return None
        prompt = prompt.lstrip()
        if host == "claude-code":
            for command in ("/yomiyasu:yomiyasu", "/yomiyasu"):
                if prompt.startswith(command) and len(prompt) > len(command) and prompt[len(command)].isspace():
                    return prompt[len(command):]
        else:
            for word in prompt.split():
                if word in ("$yomiyasu", "$yomiyasu:yomiyasu"):
                    return prompt
    return None


def _config(host):
    import shlex
    path = os.path.realpath(__file__)
    events = ["UserPromptExpansion", "UserPromptSubmit", "PreToolUse", "Stop", "SessionEnd"] if host == "claude-code" else [
        "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"]
    hooks = {}
    for event in events:
        timeout = {"UserPromptExpansion": 5, "UserPromptSubmit": 5, "PreToolUse": 10,
                   "PostToolUse": 10, "Stop": 30, "SessionEnd": 1 if host == "claude-code" else 2}[event]
        handler = {"type": "command", "timeout": timeout}
        if host == "claude-code":
            handler.update(command=sys.executable, args=["-B", path, "--host", host])
        else:
            handler["command"] = shlex.join([sys.executable, "-B", path, "--host", host])
        row = {"hooks": [handler]}
        if event == "UserPromptExpansion":
            row["matcher"] = "^(yomiyasu|yomiyasu:yomiyasu)$"
        elif event == "PreToolUse":
            row["matcher"] = "^(Bash|mcp__.*)$" if host == "claude-code" else "^Bash$|^mcp__.*"
        elif event == "PostToolUse":
            row["matcher"] = "^Bash$"
        hooks[event] = [row]
    return {"hooks": hooks} if host == "claude-code" else {
        "description": "yomiyasu の任意のフック（登録した原稿だけを対象にする）", "hooks": hooks}


def _iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expired(entry):
    return entry["deadline"] < _iso()


def _log(entry, event, result, started, stop_active=None):
    import time
    row = {"at": _iso(), "event": event, "result": result, "ms": int((time.monotonic() - started) * 1000)}
    # The only input flag retained. Never retain any prompt or tool arguments.
    if stop_active is not None:
        row["stop_hook_active"] = bool(stop_active)
    entry["log"].append(row)
    entry["log"] = entry["log"][-50:]


def _error_log(states, event, error):
    import stat
    import time
    import traceback
    for state in states:
        if not os.path.isdir(state):
            continue
        # A folder without .gitignore and state.json was not set up by check (for example a .yomiyasu/
        # made by an agent before run). Writing the log there would show it in git status.
        if not any(os.path.lexists(os.path.join(state, name)) for name in ('.gitignore', 'state.json')):
            return
        try:
            frames = traceback.extract_tb(error.__traceback__)
            location = "yomiyasu_hook.py:0"
            if frames:
                location = "{}:{}".format(os.path.basename(frames[-1].filename), frames[-1].lineno)
            # The event and exception class are from our own code, not from input text.
            event = event if event in _EVENTS else "unknown"
            kind = type(error).__name__
            if not kind.isidentifier():
                kind = "Exception"
            line = "{} {} {} {}\n".format(_iso(), event, kind, location).encode("ascii", "backslashreplace")
            path = os.path.join(state, "hook-errors.log")
            if os.path.islink(path):
                continue
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(path, flags, 0o600)
            with os.fdopen(fd, "r+b") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    continue
                if os.name == "posix":
                    os.chmod(path, 0o600)
                data = stream.read(65537)
                if len(data) + len(line) > 65536:
                    data = data[len(data) // 2:]
                    data = data.partition(b'\n')[2]
                stream.seek(0)
                stream.write(data + line)
                stream.truncate()
        except BaseException:
            pass
        return


def _read_text(path):
    if not os.path.isfile(path):
        raise ValueError("text_file")
    with open(path, "rb") as stream:
        data = stream.read(_MAX_TEXT + 1)
    if len(data) > _MAX_TEXT:
        raise ValueError("text_size")
    data.decode("utf-8-sig")
    return data


def _paths(args, cwd):
    """The manuscript is the first existing text file named in the request (one file only).

    Later names (the final, notes or references) are not registered, so unrelated work is not held.
    """
    import re
    import shlex
    try:
        words = shlex.split(args)
    except ValueError:
        words = args.split()
    candidates = []
    for word in words:
        position = args.find(word)
        candidates.append((position if position >= 0 else len(args), word))
    for match in re.finditer(r'''[^\s"'「」（）()]+\.(?:md|markdown|txt|text|rst|adoc|html?)''', args):
        candidates.append((match.start(), match.group(0)))
    seen = set()
    # sorted is stable: at the same position the shlex word comes first.
    for position, word in sorted(candidates, key=lambda item: item[0]):
        word = word[1:] if word.startswith("@") else word
        if not word:
            continue
        path = os.path.abspath(os.path.join(cwd, word))
        key = _place(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            _read_text(path)
        except (OSError, ValueError):
            continue
        return [path]
    return []


def _place(path):
    return os.path.normcase(os.path.realpath(path))


def _project_root(path):
    current = path
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return path
        current = parent


def _same_project(entry, cwd):
    """An unbound registration is bound only from its own project (cwd equal to or under the project root).

    A state folder shared through --state-dir or YOMIYASU_STATE_DIR must not reach other projects' sessions.
    """
    recorded = entry.get("cwd")
    if not isinstance(recorded, str) or not os.path.isabs(recorded):
        return False
    root = _place(_project_root(recorded))
    here = _place(cwd)
    return here == root or here.startswith(root.rstrip(os.sep) + os.sep)


def _shown(path, cwd):
    try:
        relative = os.path.relpath(path, cwd)
        if relative != os.pardir and not relative.startswith(os.pardir + os.sep):
            return relative
    except ValueError:
        pass
    return path


def _mine(entry, host, session):
    return entry['status'] != 'ended' and entry['host'] == host and entry['session_id'] == session


def _limit_label(entry):
    return {"deadline": "期限{}分".format(entry["limits"]["deadline_min"]),
            "run_limit": "run {}回まで".format(entry["limits"]["max_runs"])}.get(
                entry["status_reason"], "続けさせる回数の上限")


def _notice(entry, cwd):
    return ("yomiyasu: 原稿 {}（実行ID {}）は未確認で終わりました（{}）。最終稿は検査記録と照合できていません。"
            "投稿する前に、yomiyasu_check.py verify で確かめてください。").format(
                _shown(entry['targets']['source']['path'], cwd), entry['run_id'], _limit_label(entry))


def _reason(entry, final, v, cwd):
    import shlex
    source = shlex.quote(_shown(entry['targets']['source']['path'], cwd))
    final = shlex.quote(_shown(final, cwd))
    prefix = "yomiyasu（実行ID {}）: ".format(entry['run_id'])
    tail = "実行できない場合は、完了報告の「実行しなかった検査」に書いてください。"
    if v['status'] == 'no_record':
        message = ("登録した原稿 {} の最終稿 {} に、検査記録がありません。yomiyasu_check.py run --source {} --final {} "
                   "を実行し、そのあと verify を実行してください。").format(source, final, source, final) + tail
    elif v['status'] == 'final_changed':
        message = ("最終稿 {} が、最後に検査した本文と違います（検査のあとに書き換えがありました）。run をもう一度実行し、"
                   "そのあと verify を実行してください。").format(final) + tail
    elif v['status'] == 'incomplete':
        names = [name for name in ('lint', 'diff', 'materials') if any(
            p['code'] in ('missing_check', 'check_target') and p['detail'].startswith(name) for p in v['problems'])]
        message = "検査記録に {} の結果がありません。run をもう一度実行してください。".format('、'.join(names)) + tail
    elif v['status'] == 'tool_changed':
        message = "記録のあとで検査スクリプトが変わりました。run をもう一度実行してください。" + tail
    else:
        # These verify messages are fixed text, never report excerpts or exception messages.
        message = "最終稿 {}: {}".format(final, v['message'])
    return prefix + message + "\n（yomiyasu のフックが続けさせるのは、あと {} 回までです。）".format(
        max(0, entry['limits']['max_stop_blocks'] - entry['counters']['stop_blocks']))


def _stop(check, state, entry, data, host, session, cwd, started, budget):
    import hashlib
    response = {}
    def change(current):
        if not _mine(current, host, session):
            return False
        if current['status'] == 'unverified':
            if current['notified']:
                return False
            response['systemMessage'] = _notice(current, cwd)
            current['notified'] = True
            _log(current, 'Stop', 'unverified:' + current['status_reason'], started, data.get('stop_hook_active', False))
            return
        final = current['targets']['final'] or check.latest_final_path(state, current['run_id'])
        source = current['targets']['source']
        if final is None:
            if not os.path.isfile(source['path']):
                _log(current, 'Stop', 'source_missing', started)
                return
            with open(source['path'], 'rb') as stream:
                unchanged = hashlib.sha256(stream.read()).hexdigest() == source['sha256']
            if unchanged:
                return False
            final = source['path']
        if not os.path.isfile(final):
            _log(current, 'Stop', 'final_missing', started)
            return
        v = check.verify_quick(state, final_path=final, run_id=current['run_id'], since=current['created_at'])
        if v['status'] == 'executed':
            current['status'], current['status_reason'] = 'checked', None
            current['verified'] = {key: v[key] for key in ('attempt', 'final_sha256', 'text_sha256')}
            current['verified']['at'] = _iso()
            _log(current, 'Stop', 'checked', started, data.get('stop_hook_active', False))
            return
        current['status'] = 'active'
        reason = 'deadline' if _expired(current) else (
            'stop_limit' if current['counters']['stop_blocks'] >= current['limits']['max_stop_blocks'] else None)
        if reason:
            current['status'], current['status_reason'] = 'unverified', reason
            if not current['notified']:
                response['systemMessage'] = _notice(current, cwd)
                current['notified'] = True
            _log(current, 'Stop', 'unverified:' + reason, started, data.get('stop_hook_active', False))
        else:
            current['counters']['stop_blocks'] += 1
            response.update(decision='block', reason=_reason(current, final, v, cwd))
            _log(current, 'Stop', 'block:' + v['status'], started, data.get('stop_hook_active', False))
    check.armed_update(state, entry['run_id'], change, budget)
    return response


def _bash_command(value):
    import shlex
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(word, str) for word in value):
        if len(value) >= 3 and value[1] in ('-c', '-lc'):
            return value[2]
        return shlex.join(value)
    return ''


def _shell_segments(command):
    """Split only outside quotes/substitutions; keep heredoc text with its command.

    This is a delimiter scanner, not a shell evaluator. shlex below still parses arguments.
    """
    import re
    result, pending = [], []
    start, index, quote, escaped = 0, 0, None, False
    substitutions = []
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == '\\' and quote != "'":
            escaped = True
            index += 1
            continue
        if quote in ("'", '`'):
            if char == quote:
                quote = None
            index += 1
            continue
        if command.startswith('$(', index):
            substitutions.append([1, quote])
            quote = None
            index += 2
            continue
        if quote == '"':
            if char == '"':
                quote = None
            index += 1
            continue
        if char in ("'", '"', '`'):
            quote = char
            index += 1
            continue
        if substitutions:
            if char == '(':
                substitutions[-1][0] += 1
            elif char == ')':
                substitutions[-1][0] -= 1
                if substitutions[-1][0] == 0:
                    quote = substitutions.pop()[1]
            index += 1
            continue
        if command.startswith('<<', index):
            match = re.match(r'''<<(-?)\s*(["']?)([A-Za-z_][A-Za-z0-9_]*)\2''', command[index:])
            if match:
                pending.append((match.group(3), bool(match.group(1))))
                index += match.end()
                continue
        if char == '\n' and pending:
            end = index + 1
            for delimiter, tabs in pending:
                pattern = r'(?m)^' + (r'\t*' if tabs else '') + re.escape(delimiter) + r'\r?$'
                match = re.search(pattern, command[end:])
                if not match:
                    end = len(command)
                    break
                end += match.end()
                if end < len(command) and command[end] == '\n':
                    end += 1
            result.append(command[start:end])
            start = index = end
            pending = []
            continue
        if char in (';', '|', '\n') or command.startswith('&&', index):
            # A pending heredoc is attached at its newline, including its body.
            if not pending:
                result.append(command[start:index])
                index += 2 if command[index:index + 2] in ('&&', '||') else 1
                start = index
                continue
        index += 1
    if start < len(command):
        result.append(command[start:])
    return result


def _bodies(data, cwd):
    """Yield (bytes or None, path or None, original command). Never execute shell text."""
    import re
    import shlex
    name, tool = data.get('tool_name'), data.get('tool_input')
    if not isinstance(name, str) or not isinstance(tool, dict):
        return []
    bodies = []
    # A lone surrogate (JSON "\ud800") stays as bytes that are not UTF-8, so that field alone cannot match a
    # registered draft (_related skips it) while the other fields are still checked.
    if name.startswith('mcp__'):
        def scan(value, depth):
            for key, item in value.items():
                if key in ('body', 'text', 'content', 'description', 'message', 'notes') and isinstance(item, str):
                    bodies.append((item.encode('utf-8', 'surrogatepass'), None, ''))
                elif isinstance(item, dict) and depth < 2:
                    scan(item, depth + 1)
        scan(tool, 1)
        return bodies
    if name != 'Bash':
        return []
    command = _bash_command(tool.get('command'))
    for context in _shell_segments(command):
        unsafe = any(mark in context for mark in ('$(', '`', '<<'))
        try:
            lexer = shlex.shlex(context, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            lexer.commenters = ''
            words = list(lexer)
        except ValueError:
            words = context.split()
            unsafe = True
        # The first gh word, also by absolute path (/opt/homebrew/bin/gh) or gh.exe.
        names = [os.path.basename(word.replace('\\', '/')) for word in words]
        found = [n for n, word in enumerate(names) if word in ('gh', 'gh.exe')]
        if not found:
            continue
        words = words[found[0] + 1:]
        api = bool(words and words[0] == 'api')
        public = len(words) >= 2 and ((words[0] == 'pr' and words[1] in ('create', 'edit', 'comment', 'review'))
                  or (words[0] == 'issue' and words[1] in ('create', 'edit', 'comment'))
                  or (words[0] == 'release' and words[1] in ('create', 'edit')))
        if not api and not public:
            continue
        if unsafe:
            bodies.append((None, None, context))
            continue
        flags = {'--body': False, '-b': False, '--body-file': True, '-F': True}
        if words[0] == 'release':
            flags = {'--notes': False, '-n': False, '--notes-file': True, '-F': True}
        if api:
            flags = {'-f': False, '--raw-field': False, '-F': True, '--field': True, '--input': True}
        index = 1 if api else 2
        while index < len(words):
            word = words[index]
            flag, equal, value = word.partition('=')
            if flag not in flags:
                index += 1
                continue
            if not equal:
                index += 1
                value = words[index] if index < len(words) else ''
            file_arg = flags[flag]
            if api:
                if flag == '--input':
                    bodies.append((None, None, context))
                    index += 1
                    continue
                key, sep, field = value.partition('=')
                if key not in ('body', 'text', 'notes') or not sep:
                    index += 1
                    continue
                value = field
                file_arg = file_arg and value.startswith('@')
                if file_arg:
                    value = value[1:]
            if file_arg:
                path = os.path.abspath(os.path.join(cwd, value)) if value and value != '-' else None
                try:
                    raw = _read_text(path) if path else None
                except (OSError, ValueError):
                    raw = None
                bodies.append((raw, path, context))
            else:
                bodies.append((value.encode('utf-8', 'surrogatepass'), None, context))
            index += 1
    return bodies


def _related(check, state, entry, body, path, command):
    known, paths = check.run_known_texts(state, entry['run_id'])
    source = entry['targets']['source']
    paths.add(source['path'])
    known.add(source['text_sha256'])
    final = entry['targets']['final'] or check.latest_final_path(state, entry['run_id'])
    if final:
        paths.add(final)
    if path:
        placed = _place(path)
        exports = _place(os.path.join(state, 'exports')) + os.sep
        if placed in {_place(p) for p in paths} or placed.startswith(exports):
            return True
    if body is None:
        for p in paths:
            if any(value and value in command for value in (p, os.path.relpath(p, entry['_cwd']), os.path.basename(p))):
                return True
        return False
    for p in paths:
        try:
            known.add(check.text_sha256_of(_read_text(p)))
        except (OSError, ValueError):
            pass
    try:
        return check.text_sha256_of(body) in known
    except UnicodeError:
        return False


def _pretool(check, state, entry, bodies, host, session, cwd, started, budget):
    response = {}
    def change(current):
        if not _mine(current, host, session):
            return False
        for body, path, command in bodies:
            # Pass cwd only in memory; never persist this helper field.
            related_entry = dict(current, _cwd=cwd)
            if not _related(check, state, related_entry, body, path, command):
                continue
            if body is None:
                status = 'unextractable'
                decision = 'ask' if host == 'claude-code' else 'deny'
                reason = ("yomiyasu（実行ID {}）: 投稿の本文を取り出せないため、登録した原稿 {} の検査記録と照らせません。"
                          "export の写しを --body-file に渡してください。").format(
                              current['run_id'], _shown(current['targets']['source']['path'], cwd))
            else:
                v = check.verify_quick(state, final_bytes=body, run_id=current['run_id'], since=current['created_at'])
                if v['status'] == 'executed':
                    continue
                # Keep successful body matching (including copies and line-ending differences).
                # Only refine a failure's reason when the file is a registered final.
                if path:
                    finals = (current['targets']['final'], check.latest_final_path(state, current['run_id']))
                    if any(final and _place(path) == _place(final) for final in finals):
                        v = check.verify_quick(state, final_path=path, final_bytes=body,
                                               run_id=current['run_id'], since=current['created_at'])
                        if v['status'] == 'executed':
                            continue
                status, decision = v['status'], 'deny'
                final = current['targets']['final'] or check.latest_final_path(state, current['run_id']) or current['targets']['source']['path']
                reason = ("yomiyasu（実行ID {}）: 投稿しようとしている本文は、登録した原稿 {} の検査記録と照合できていません（{}）。"
                          "yomiyasu_check.py run と verify を実行し、yomiyasu_check.py export --final {} で書き出した写しを "
                          "--body-file に渡してください。照合できないときは、投稿せずに未確認として利用者に伝えてください。").format(
                              current['run_id'], _shown(current['targets']['source']['path'], cwd), status, _shown(final, cwd))
            response.update(hookSpecificOutput={'hookEventName': 'PreToolUse', 'permissionDecision': decision,
                                               'permissionDecisionReason': reason})
            _log(current, 'PreToolUse', decision + ':' + status, started)
            return
        return False
    check.armed_update(state, entry['run_id'], change, budget)
    return response


def _process(check, states, invocation, data, host, event, cwd, started, budget, processing, default_place=False):
    import time
    session = data['session_id']
    registrations, combined = [], {}
    def remaining():
        if time.monotonic() >= budget:
            raise TimeoutError('hook_budget')
    if invocation is not None:
        for path in _paths(invocation, cwd):
            remaining()
            existing = [e for state in states for e in check.armed_entries(state)
                        if _mine(e, host, session) and _place(e['targets']['source']['path']) == _place(path)]
            if existing:
                continue
            # First candidate follows --state-dir, environment, project priority. A project .yomiyasu/
            # that already exists gets the same .gitignore and state.json as run (check._ensure_state).
            entry = check.start_run(states[0], path, session=session, host=host,
                                    by='hook:' + host + ':' + event, cwd=cwd, default_place=default_place)
            registrations.append(("yomiyasu の管理: 原稿 {} を登録しました（実行ID {}。上限: 続けさせる2回、run 3回、30分）。"
                                  "この原稿を yomiyasu_check.py run の --source に渡すと、記録がこの登録につながります。"
                                  "返答を終えるときに、最終稿が検査記録と合うかをフックが確かめます。").format(
                                      _shown(path, cwd), entry['run_id']))
    bodies = _bodies(data, cwd) if event == 'PreToolUse' else []
    for state in states:
        remaining()
        entries = check.armed_entries(state)
        # Readers skip invalid records; the hook reports only the exception type.
        folder = os.path.join(state, 'armed')
        if os.path.isdir(folder):
            valid = {e['run_id'] + '.json' for e in entries}
            if any(name.endswith('.json') and name not in valid for name in os.listdir(folder)):
                _error_log([state], event, ValueError('armed_record'))
        for entry in entries:
            remaining()
            if entry['status'] == 'ended':
                continue
            if event != 'SessionEnd' and entry['session_id'] in (None, session) and entry['host'] in (None, host) and (entry['session_id'] is None or entry['host'] is None) and not _expired(entry) and (entry['session_id'] is not None or _same_project(entry, cwd)):
                processing[:] = [(state, entry['run_id'])]
                def bind(current):
                    if current['session_id'] not in (None, session) or current['status'] == 'ended' or current['host'] not in (None, host) or _expired(current) or (current['session_id'] is None and not _same_project(current, cwd)):
                        return False
                    current['session_id'], current['host'], current['bound_at'] = session, host, _iso()
                    _log(current, event, 'bound', started)
                entry = check.armed_update(state, entry['run_id'], bind, budget)
                processing[:] = []
            if not _mine(entry, host, session):
                continue
            processing[:] = [(state, entry['run_id'])]
            if event == 'SessionEnd':
                def finish(current):
                    if not _mine(current, host, session):
                        return False
                    current['status'], current['status_reason'] = 'ended', 'session_end'
                    _log(current, event, 'ended:session_end', started)
                check.armed_update(state, entry['run_id'], finish, budget)
            elif event == 'Stop':
                response = _stop(check, state, entry, data, host, session, cwd, started, budget)
                for key, value in response.items():
                    if key in ('reason', 'systemMessage') and key in combined:
                        combined[key] += '\n' + value
                    else:
                        combined[key] = value
            elif event == 'PreToolUse' and bodies:
                response = _pretool(check, state, entry, bodies, host, session, cwd, started, budget)
                if response:
                    old = combined.get('hookSpecificOutput')
                    new = response['hookSpecificOutput']
                    if old:
                        old['permissionDecisionReason'] += '\n' + new['permissionDecisionReason']
                        if new['permissionDecision'] == 'deny':
                            old['permissionDecision'] = 'deny'
                    else:
                        combined = response
            processing[:] = []
    remaining()
    if registrations:
        return '\n'.join(registrations)
    return json.dumps(combined, ensure_ascii=True) if combined else ''


class _SilentStream(object):
    # check's public hook helpers are quiet; also contain diagnostics from a broken import.
    def write(self, text):
        return len(text)

    def flush(self):
        pass


def main(argv=None):
    states, event = [], 'unknown'
    processing = []
    try:
        options = _options(sys.argv[1:] if argv is None else argv)
        if options is None:
            return 0
        output = ''
        if options.get('--version'):
            output = 'yomiyasu_hook.py ' + __version__
        elif options.get('-h') or options.get('--help'):
            output = _HELP
        elif options.get('--print-config') in ('claude-code', 'codex'):
            output = json.dumps(_config(options['--print-config']), ensure_ascii=True, indent=2)
        elif '--print-config' in options:
            # Only a person runs --print-config (it is never in a host's settings), so a wrong value is a usage error.
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding='utf-8')
            sys.stderr.write(_PRINT_CONFIG_ERROR + '\n')
            return 2
        else:
            host = options.get('--host')
            if host not in ('claude-code', 'codex'):
                return 0
            raw = sys.stdin.buffer.read(_MAX_INPUT + 1)
            if len(raw) > _MAX_INPUT:
                return 0
            try:
                data = json.loads(raw.decode('utf-8'))
            except (ValueError, UnicodeError):
                return 0
            if not isinstance(data, dict) or not isinstance(data.get('session_id'), str) or not data['session_id'].strip():
                return 0
            event = data.get('hook_event_name')
            if event not in _EVENTS or (host == 'claude-code' and event == 'PostToolUse') or (host == 'codex' and event == 'UserPromptExpansion'):
                return 0
            cwd = data.get('cwd')
            if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd):
                return 0
            states = _states(cwd, host, options.get('--state-dir'))
            invocation = _invocation(data, host, event)
            if invocation is None and not any(os.path.isdir(os.path.join(state, 'armed')) for state in states):
                return 0
            # Only json, os and sys have been imported on the unregistered path.
            import time
            import importlib.util
            started = time.monotonic()
            budget = started + _BUDGETS[event]
            import signal
            timer = hasattr(signal, 'setitimer') and hasattr(signal, 'SIGALRM')
            previous = None
            def deadline_reached(number, frame):
                raise TimeoutError('hook_budget')
            try:
                if timer:
                    previous = signal.signal(signal.SIGALRM, deadline_reached)
                    signal.setitimer(signal.ITIMER_REAL, max(0.001, budget - time.monotonic()))
                spec = importlib.util.spec_from_file_location('_yomiyasu_hook_check',
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), 'yomiyasu_check.py'))
                import contextlib
                check = importlib.util.module_from_spec(spec)
                with contextlib.redirect_stdout(_SilentStream()), contextlib.redirect_stderr(_SilentStream()):
                    spec.loader.exec_module(check)
                    output = _process(check, states, invocation, data, host, event, cwd, started, budget, processing,
                                      default_place=not _state_given(options.get('--state-dir')))
            finally:
                if timer and previous is not None:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, previous)
        if output:
            if hasattr(sys.stdout, 'reconfigure'):
                # The registration message is plain text with the draft's name. A name with bytes that are not
                # UTF-8 (a lone surrogate such as '\udcff') is written as an escape instead of failing the hook.
                sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
            sys.stdout.write(output + '\n')
            sys.stdout.flush()
    except BaseException as error:
        if isinstance(error, TimeoutError) and processing and time.monotonic() >= budget:
            # The normal update has unwound and released its lock, and the alarm is off.
            # Best effort only: never wait on another writer beyond this short deadline.
            try:
                state, run_id = processing[0]
                with contextlib.redirect_stdout(_SilentStream()), contextlib.redirect_stderr(_SilentStream()):
                    check.armed_update(state, run_id, lambda entry: _log(entry, event, 'timeout', started),
                                       time.monotonic() + 0.2)
            except BaseException:
                pass
        _error_log(states, event, error)
        # A closed host pipe must not cause another flush error at interpreter exit.
        sys.stdout = _SilentStream()
        sys.stderr = _SilentStream()
    return 0


if __name__ == '__main__':
    sys.exit(main())
