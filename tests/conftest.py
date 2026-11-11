"""pytest の設定: 時間を測って上限と比べる試験に timing の印を付ける。

CI は試験を並列に動かす（pytest-xdist）。同時に動くほかの試験の負荷で、時間を測る試験が上限を超えないよう、CI では
`-m "not timing"` を並列に動かしたあと、`-m timing` を1つずつ動かす。

印を付けるのは、試験の本体が時計を使う試験と、時計を使う補助の関数（試験のクラスとその親クラスのメソッド、試験の
ファイルの関数）を呼ぶ試験。時計は、性能の試験の時計と上限（tests/portable.py の timing_clock と paced_limit、
test_v200_diff_full の CHILD_TIMER）と、time.perf_counter、time.process_time、time.monotonic。補助の関数が別の補助の
関数を呼ぶときもたどる。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator

import pytest

_CLOCKS = ("timing_clock", "paced_limit", "CHILD_TIMER", "perf_counter", "process_time", "monotonic(")


def _source(target: object) -> str:
    try:
        return inspect.getsource(target)
    except (OSError, TypeError):
        return ""


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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "timing: 時間を測って上限と比べる試験（CI では並列に動かさない）")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    cache: dict[tuple[object, object], tuple[str, ...]] = {}
    for item in items:
        key = (getattr(item, "module", None), getattr(item, "cls", None))
        if key not in cache:
            cache[key] = _timed_calls(item)
        if any(name in _source(getattr(item, "obj", None)) for name in cache[key]):
            item.add_marker(pytest.mark.timing)
