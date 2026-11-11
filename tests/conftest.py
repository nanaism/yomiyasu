"""pytest の設定: 時間を測って上限と比べる試験に timing の印を付ける。

CI は試験を並列に動かす（pytest-xdist）。同時に動くほかの試験の負荷で、時間を測る試験が上限を超えないよう、CI では
`-m "not timing"` を並列に動かしたあと、`-m timing` を1つずつ動かす。印は、試験の本体が性能の試験の時計と上限
（tests/portable.py の timing_clock と paced_limit）か、time.perf_counter、time.process_time を使う試験に付ける。
"""

from __future__ import annotations

import inspect

import pytest

_CLOCKS = ("timing_clock", "paced_limit", "perf_counter", "process_time")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "timing: 時間を測って上限と比べる試験（CI では並列に動かさない）")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        try:
            source = inspect.getsource(item.obj)
        except (AttributeError, OSError, TypeError):
            continue
        if any(name in source for name in _CLOCKS):
            item.add_marker(pytest.mark.timing)
