"""試験の道具: Windows でも POSIX と同じ入力のバイト列と、同じ考え方の時間の上限で確かめるための関数。

yomiyasu のスクリプトは読み込まない（試験のファイルが import して使う）。

- run_text: subprocess.run の text モード（encoding、errors、text）の代わり。text モードの標準入力は、Windows では
  「\\n」を「\\r\\n」に、「\\r\\n」を「\\r\\r\\n」にして子に渡すので、文字列の入力を改行を変えずにバイト列にして渡す。
  出力の読み方は text モードと同じ（POSIX で text モードを使ったときと同じ文字列になる）。
- timing_clock、paced_limit: 子プロセスを使わない性能の試験の時計と上限。test_v200_diff_full の性能の試験と同じく、
  秒数の上限を、基準の処理（その CHILD_TIMER の pace）の遅さの比で延ばす（速い機械でも上限は縮めない）。
"""

from pathlib import Path
import re
import subprocess
import sys
import time

DIFF_FULL_TESTS = Path(__file__).resolve().parent / "test_v200_diff_full.py"


def text_output(data, encoding="utf-8", errors="strict"):
    """子の出力のバイト列を、subprocess の text モードと同じく読む（encoding で解き、CRLF と CR を LF にそろえる）。"""
    return data.decode(encoding, errors).replace("\r\n", "\n").replace("\r", "\n")


def run_text(command, input=None, encoding="utf-8", errors="strict", **kwargs):
    """subprocess.run(command, input=input, encoding=encoding, errors=errors, **kwargs) と同じ結果を返す。違いは、文字列の
    input を改行を変えずに encoding のバイト列にして渡すことだけ。標準出力と標準エラーは、捕まえたときは text_output で
    文字列にする。"""
    if isinstance(input, str):
        input = input.encode(encoding, errors)
    process = subprocess.run(command, input=input, **kwargs)
    for name in ("stdout", "stderr"):
        data = getattr(process, name)
        if isinstance(data, bytes):
            setattr(process, name, text_output(data, encoding, errors))
    return process


def timing_clock():
    """性能の試験の時計。CPU 時間で測る（ほかのプロセスに CPU を譲って待った時間を入れない）。Windows の CPU 時間は
    刻みが粗い（約16ミリ秒）ので、壁時計で測る（test_v200_diff_full の CHILD_TIMER と同じ）。"""
    return time.perf_counter if sys.platform == "win32" else time.process_time


_PACE = {}


def _pace():
    """test_v200_diff_full の PACE_SECONDS と pace（yomiyasu を使わない、量の決まった計算）を、そのファイルから読む。"""
    if not _PACE:
        source = DIFF_FULL_TESTS.read_text(encoding="utf-8")
        seconds = float(re.search(r"^PACE_SECONDS = ([0-9.]+)$", source, re.M).group(1))
        start = source.index("# pace は yomiyasu を使わない")
        end = source.index("\ndef sample(", start)
        namespace = {}
        exec(compile("import difflib\nimport re\nfrom bisect import bisect_left\nfrom collections import Counter\n"
                     + source[start:end], "pace", "exec"), namespace)
        _PACE.update(seconds=seconds, run=namespace["pace"])
    return _PACE["seconds"], _PACE["run"]


def pace_scale(rounds=3):
    """この機械の遅さの比。pace を rounds 回動かした最も速い時間を PACE_SECONDS で割った値で、1 より小さければ 1。"""
    seconds, run = _pace()
    clock = timing_clock()
    best = None
    for _ in range(rounds):
        started = clock()
        run()
        elapsed = clock() - started
        best = elapsed if best is None else min(best, elapsed)
    return max(1.0, best / seconds)


def paced_limit(limit, elapsed):
    """(上限, 説明の文) を返す。elapsed が limit 未満なら上限は limit のまま（pace は測らない）。limit 以上なら pace を測り、
    limit をこの機械の遅さの比で延ばした値を上限にする。比は1以上なので、速い機械で上限が縮むことはなく、実装が遅くなった
    ときは、遅い機械でも、その遅さを除いた分だけ上限を超える。"""
    scale = 1.0 if elapsed < limit else pace_scale()
    detail = "%.3f秒。上限 %.3f秒（%s秒 × この機械の遅さ %.2f）" % (elapsed, limit * scale, limit, scale)
    return limit * scale, detail
