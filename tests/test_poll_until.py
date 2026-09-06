"""util.poll_until 的行为锁定：golden.py 十处轮询循环共用的骨架。

probe 契约：None=继续等；非 None（含 False）=终值透传；异常上抛；超时返回 None。
"""

from __future__ import annotations

import pytest

from corenova.util import poll_until


class FakeClock:
    """可控时钟：sleep(n) 直接推进时间，不真实等待。"""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


class TestPollUntil:
    def test_terminal_value_returned_immediately(self, clock):
        assert poll_until(lambda: "done", timeout_s=60, interval_s=5,
                          clock=clock.time, sleep=clock.sleep) == "done"
        assert clock.slept == []  # 终值立即返回，不多睡一次

    def test_false_is_terminal_not_pending(self, clock):
        # False 是合法终值：destroy_canary 用它表示 DELETE_FAILED（终态但非成功）
        assert poll_until(lambda: False, timeout_s=60, interval_s=5,
                          clock=clock.time, sleep=clock.sleep) is False
        assert clock.slept == []

    def test_none_keeps_polling_until_value(self, clock):
        seq = iter([None, None, "ready"])
        assert poll_until(lambda: next(seq), timeout_s=300, interval_s=10,
                          clock=clock.time, sleep=clock.sleep) == "ready"
        assert clock.slept == [10, 10]

    def test_timeout_returns_none(self, clock):
        assert poll_until(lambda: None, timeout_s=100, interval_s=30,
                          clock=clock.time, sleep=clock.sleep) is None
        # 100s 窗口 / 30s 间隔 → t=0,30,60,90 共 4 次 probe
        assert clock.slept == [30, 30, 30, 30]

    def test_exception_propagates(self, clock):
        def probe():
            raise RuntimeError("terminal failure")
        with pytest.raises(RuntimeError, match="terminal failure"):
            poll_until(probe, timeout_s=60, interval_s=5, clock=clock.time, sleep=clock.sleep)
        assert clock.slept == []  # 异常不重试

    def test_zero_timeout_never_probes(self, clock):
        calls = []

        def probe():
            calls.append(1)
            return "x"

        assert poll_until(probe, timeout_s=0, interval_s=5,
                          clock=clock.time, sleep=clock.sleep) is None
        assert calls == []
