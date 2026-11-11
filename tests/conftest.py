"""pytest の設定: 時間を測って上限と比べる試験に timing の印を付け、試験を組に分けて流せるようにする。

CI は試験を並列に動かす（pytest-xdist）。同時に動くほかの試験の負荷で、時間を測る試験が上限を超えないよう、CI では
`-m "not timing"` を並列に動かし、`-m timing` は別のジョブで1つずつ動かす。

印を付けるのは、試験の本体が時計を使う試験と、時計を使う補助の関数（試験のクラスとその親クラスのメソッド、試験の
ファイルの関数）を呼ぶ試験。時計は、性能の試験の時計と上限（tests/portable.py の timing_clock と paced_limit、
test_v200_diff_full の CHILD_TIMER）と、time.perf_counter、time.process_time、time.monotonic。補助の関数が別の補助の
関数を呼ぶときもたどる。ソースからは見分けられない試験は、名前で印を付ける（_TIMED_BY_NAME）。

`--part I/N` を付けると、選ばれた試験（-m や -k で絞ったあと）を集めた順に N 組へ1件ずつ配り、I 番目の組だけを流す。
CI はこれで、時間を測らない試験を別々のジョブに分ける。手元でふつうに流すときは付けない。

組は集めた順の位置で決めるので、同じ環境の N 個のジョブ（別々の機械）が、同じ試験を同じ順で集めることに頼っている。
pytest はファイルを名前の順に集め、unittest はメソッドを名前の順に並べるので、機械によって変わらない。試験は
unittest.TestCase のメソッドとして書き、環境によって定義が増えたり減ったりする書き方（条件つきの class や def）はしない
（飛ばすときは skip を使う。skip は集める数を変えない）。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator

import pytest

_CLOCKS = ("timing_clock", "paced_limit", "CHILD_TIMER", "perf_counter", "process_time", "monotonic(")


# 試験の側では時計を読まないが、スクリプトの中の時間の予算に頼る試験（フックの SessionEnd の 0.8秒、子プロセスを並べたときの
# ロックの待ち）。負荷がかかると予算を過ぎて落ちうるが、ソースに時計の名前がないので、名前で印を付ける。
# 書き方は「ファイル::クラス::試験」。tests/test_ci_parts.py が、ここの名前の試験があることと、timing に入ることを確かめる。
_TIMED_BY_NAME = (
    "test_v200_check_start.py::StartTests::test_h3_parallel_starts_keep_one_active_registration",
    "test_v200_check_start.py::StartTests::test_h5_parallel_runs_reserve_attempt_before_checks",
    "test_v200_hook.py::HookTests::test_h12_session_end_and_ended_exclusion",
    "test_v200_hook.py::HookTests::test_h13_no_body_in_any_event_or_errors",
    "test_v200_hook.py::HookTests::test_h15_parallel_stop_pretool_and_stale_lock",
    "test_v200_hook.py::HookTests::test_state_candidates_and_partial_session_binding",
)

_SOURCES: dict[int, tuple[object, str]] = {}


def _source(target: object) -> str:
    """target のソース。補助の関数は試験のクラスごとに何度も読むので、関数ごとに結果を覚える。"""
    target = getattr(target, "__func__", target)
    known = _SOURCES.get(id(target))
    if known is not None and known[0] is target:
        return known[1]
    try:
        text = inspect.getsource(target)
    except (OSError, TypeError):
        text = ""
    _SOURCES[id(target)] = (target, text)
    return text


def part_of(position: int, total: int) -> int:
    """集めた順で position 番目（0 から）の試験が入る組の番号（1 から total）。1件ずつ順に配る。"""
    return position % total + 1


def _part(value: str) -> tuple[int, int]:
    index, _, total = value.partition("/")
    if not (index.isdigit() and total.isdigit() and 1 <= int(index) <= int(total)):
        raise pytest.UsageError("--part は 2/3 のように「組の番号/組の数」で書きます: " + repr(value))
    return int(index), int(total)


def _helpers(item: pytest.Item) -> Iterator[tuple[str, Callable[..., object]]]:
    """試験から呼べる補助の関数と、試験の本体に書くときの形（self.名前( か 名前(）。"""
    test_class = getattr(item, "cls", None)
    for owner in test_class.__mro__ if test_class is not None else ():
        if owner.__module__.startswith("unittest"):
            continue
        for name, value in vars(owner).items():
            if inspect.isfunction(value) and not name.startswith("test"):
                yield "self." + name + "(", value
    module = getattr(item, "module", None)
    for name, value in vars(module).items() if module is not None else ():
        if inspect.isfunction(value) and value.__module__ == module.__name__:
            yield name + "(", value


def _timed_calls(item: pytest.Item) -> tuple[str, ...]:
    """時計そのものと、時計を（ほかの補助の関数を通してでも）使う補助の関数の、書かれ方の一覧。"""
    timed = list(_CLOCKS)
    pending = [(call, _source(function)) for call, function in _helpers(item)]
    found = True
    while found:
        found = False
        for call, source in list(pending):
            if any(name in source for name in timed):
                timed.append(call)
                pending.remove((call, source))
                found = True
    return tuple(timed)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--part", default="", metavar="I/N",
                     help="選ばれた試験を N 組に分け、I 番目の組だけを流す（CI が試験を別々のジョブに分けるのに使う）")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "timing: 時間を測って上限と比べる試験（CI では並列に動かさない）")
    if config.getoption("--part"):
        _part(config.getoption("--part"))


# yield の前はほかのプラグインより先に、あとは全部が済んでから動く（-m の絞り込みは pytest の側のフックなので、間に入る）。
# 古い形の hookwrapper=True を使うのは、新しい形（wrapper=True）を知らない古い pluggy でも動かすため。
@pytest.hookimpl(hookwrapper=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> Iterator[None]:
    # 印は、-m で絞る前に付ける
    cache: dict[tuple[object, object], tuple[str, ...]] = {}
    for item in items:
        key = (getattr(item, "module", None), getattr(item, "cls", None))
        if key not in cache:
            cache[key] = _timed_calls(item)
        named = item.nodeid.rsplit("/", 1)[-1] in _TIMED_BY_NAME
        if named or any(name in _source(getattr(item, "obj", None)) for name in cache[key]):
            item.add_marker(pytest.mark.timing)
    yield
    # 組は、-m や -k で絞ったあとの試験を分ける
    if config.getoption("--part"):
        index, total = _part(config.getoption("--part"))
        kept = [item for position, item in enumerate(items) if part_of(position, total) == index]
        dropped = [item for position, item in enumerate(items) if part_of(position, total) != index]
        if dropped:
            config.hook.pytest_deselected(items=dropped)
            items[:] = kept
