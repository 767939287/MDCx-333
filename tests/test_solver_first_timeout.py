"""solver 首次调用不按 45s 提前放弃（用户 2026-11-13 要求）。

三类「第一次」放宽到 10 分钟硬上限，之后仍用 `_cf_bypass_timeout`(45s)：
1. 程序生命周期内第一次调 solver；
2. 该站点第一次命中挑战；
3. 适配层第一次启动（`SERVER_FIRST_START_TIMEOUT`，见 trawl_adapter 测试）。
"""

from __future__ import annotations

from mdcx.cf_bypass.trawl_adapter import (
    SERVER_FIRST_START_TIMEOUT,
    SERVER_START_TIMEOUT,
    TrawlAdapterServer,
)
from mdcx.web_async import AsyncWebClient


def _client() -> AsyncWebClient:
    return AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")


def test_first_solver_call_ever_is_not_capped_at_45s():
    """程序生命周期内第一次调 solver 等到底（不是 45s）。"""
    client = _client()

    assert client._solver_call_timeout("javdb.com") == client._cf_bypass_first_timeout
    assert client._cf_bypass_first_timeout > client._cf_bypass_timeout


def test_first_challenge_per_host_is_not_capped_at_45s():
    """非首次调用，但该站点第一次命中挑战（计数为 1）同样不按 45s 卡。"""
    client = _client()
    client._cf_solver_first_call_done = True
    # request() 里是先 +1 再调 bypass，所以首次命中时读到的就是 1
    client._cf_host_challenge_hits["javdb.com"] = 1

    assert client._solver_call_timeout("javdb.com") == client._cf_bypass_first_timeout


def test_repeat_solver_calls_keep_45s():
    """同一站点第二次及以后命中挑战，回到正常 45s，不会每轮都等满 10 分钟。"""
    client = _client()
    client._cf_solver_first_call_done = True
    client._cf_host_challenge_hits["javdb.com"] = 2

    assert client._solver_call_timeout("javdb.com") == client._cf_bypass_timeout == 45.0


def test_other_host_still_uses_first_timeout_after_first_call():
    """程序第一次已经用掉，但对另一个从没被拦过的站点仍按其首次放宽。"""
    client = _client()
    client._cf_solver_first_call_done = True
    client._cf_host_challenge_hits["javdb.com"] = 5

    assert client._solver_call_timeout("other.com") == client._cf_bypass_first_timeout


def test_trawl_adapter_first_start_uses_long_timeout():
    """适配层首次启动放宽到 SERVER_FIRST_START_TIMEOUT，第二次回到 60s。"""
    server = TrawlAdapterServer(trawl_url="http://127.0.0.1:8191")

    assert server._start_wait_timeout() == SERVER_FIRST_START_TIMEOUT
    assert SERVER_FIRST_START_TIMEOUT > SERVER_START_TIMEOUT

    server._start_attempted = True
    assert server._start_wait_timeout() == SERVER_START_TIMEOUT
