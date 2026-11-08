"""solver-first：名单内 / 命中过 CF 挑战的站点直接交给外部 CF 服务，不再先打直连。

用户 2026-11-08 要求：
- 触发过 CF 之后就别再试直连了，直接进 solver；
- 站点名单要能在 UI 里配（`cf_solver_sites`，支持 `*.example.com` 子域通配）；
- 开关可关（`cf_solver_first=False` 时回到「直连 → 挑战 → solver」的老顺序）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mdcx.cf_bypass.trawl_adapter import _session_id_for
from mdcx.web_async import AsyncWebClient


def _ok_response(url: str = "https://missav.ws/x") -> SimpleNamespace:
    return SimpleNamespace(
        status_code=200,
        headers={"x-mdcx-bypass-mode": "html"},
        content=b"<html>ok</html>",
        url=url,
    )


def test_host_matches_patterns_exact_and_wildcard():
    """`*.example.com` 只匹配子域，不含裸域名本身；空 host 不命中任何名单。"""
    assert AsyncWebClient._host_matches_patterns("a.example.com", ("*.example.com",))
    assert not AsyncWebClient._host_matches_patterns("example.com", ("*.example.com",))
    assert AsyncWebClient._host_matches_patterns("example.com", ("example.com",))
    assert not AsyncWebClient._host_matches_patterns("", ("example.com",))


def test_is_solver_first_host_uses_site_list():
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_solver_sites="missav.ws, *.javbus.com",
    )
    assert client._is_solver_first_host("missav.ws")
    assert client._is_solver_first_host("www.javbus.com")
    assert not client._is_solver_first_host("javbus.com")
    assert not client._is_solver_first_host("other.com")


def test_is_solver_first_host_after_challenge_hit():
    """没配名单时，命中过挑战的站点后续也应直接进 solver。"""
    client = AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000")
    assert not client._is_solver_first_host("other.com")
    client._cf_host_challenge_hits["other.com"] = 1
    assert client._is_solver_first_host("other.com")


def test_is_solver_first_host_respects_switch():
    """总开关关闭时，名单与挑战记录都不再生效。"""
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_solver_sites="missav.ws",
        cf_solver_first=False,
    )
    client._cf_host_challenge_hits["other.com"] = 3
    assert not client._is_solver_first_host("missav.ws")
    assert not client._is_solver_first_host("other.com")


@pytest.mark.asyncio
async def test_request_goes_straight_to_solver(monkeypatch):
    """名单内站点：一次直连都不打，直接拿到 solver 响应。"""
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_solver_sites="missav.ws",
    )
    calls = {"curl": 0, "solver": 0}

    async def fake_curl(method, url, **kwargs):
        calls["curl"] += 1
        return _ok_response(url)

    async def fake_solver(**kwargs):
        calls["solver"] += 1
        return _ok_response(kwargs.get("target_url", "")), ""

    monkeypatch.setattr(client, "_curl_request", fake_curl)
    monkeypatch.setattr(client, "_try_bypass_cloudflare", fake_solver)
    monkeypatch.setattr(client, "_store_solver_response_cookies", lambda *a, **k: None)

    response, error = await client.request("GET", "https://missav.ws/SNOS-003/cn", retry_count=1, enable_cf_bypass=True)

    assert error == ""
    assert response is not None
    assert calls == {"curl": 0, "solver": 1}


@pytest.mark.asyncio
async def test_solver_failure_falls_back_to_direct(monkeypatch):
    """solver 失败时仍回退直连，不至于直接判死。"""
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_solver_sites="missav.ws",
    )
    calls = {"curl": 0, "solver": 0}

    async def fake_curl(method, url, **kwargs):
        calls["curl"] += 1
        return _ok_response(url)

    async def fake_solver(**kwargs):
        calls["solver"] += 1
        return None, "solver down"

    monkeypatch.setattr(client, "_curl_request", fake_curl)
    monkeypatch.setattr(client, "_try_bypass_cloudflare", fake_solver)

    response, error = await client.request("GET", "https://missav.ws/x", retry_count=1, enable_cf_bypass=True)

    assert calls == {"curl": 1, "solver": 1}
    assert error == ""
    assert response is not None


def test_session_id_is_mdcx_prefixed_host():
    """TRAWL 请求带 `sessionId=mdcx-{host}`，外部服务据此区分站点。"""
    assert _session_id_for("https://www.minnano-av.com/actress334377.html") == "mdcx-www.minnano-av.com"
    assert _session_id_for("") == ""


def test_solver_reuse_window_switches_back_to_direct():
    """solver 成功后开复用窗口：窗口内 `_is_solver_first_host` 返回 False（先直连带 cookie）。"""
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_solver_sites="missav.ws",
    )
    client._cf_host_challenge_hits["missav.ws"] = 2
    assert client._is_solver_first_host("missav.ws")

    client._mark_solver_reuse("missav.ws")
    assert not client._is_solver_first_host("missav.ws")

    # 窗口过期后又回到 solver-first
    client._cf_solver_reuse_until["missav.ws"] = 0.0
    assert client._is_solver_first_host("missav.ws")


@pytest.mark.asyncio
async def test_second_request_within_window_goes_direct(monkeypatch):
    """同 host 第二次请求（窗口内）走直连，不再调 solver；直连成功即清零挑战计数。"""
    client = AsyncWebClient(
        timeout=1,
        cf_bypass_url="http://127.0.0.1:8000",
        cf_solver_sites="missav.ws",
    )
    calls = {"curl": 0, "solver": 0}

    async def fake_curl(method, url, **kwargs):
        calls["curl"] += 1
        return _ok_response(url)

    async def fake_solver(**kwargs):
        calls["solver"] += 1
        return _ok_response(kwargs.get("target_url", "")), ""

    monkeypatch.setattr(client, "_curl_request", fake_curl)
    monkeypatch.setattr(client, "_try_bypass_cloudflare", fake_solver)
    monkeypatch.setattr(client, "_store_solver_response_cookies", lambda *a, **k: None)

    await client.request("GET", "https://missav.ws/a", retry_count=1, enable_cf_bypass=True)
    assert calls == {"curl": 0, "solver": 1}

    await client.request("GET", "https://missav.ws/b", retry_count=1, enable_cf_bypass=True)
    assert calls == {"curl": 1, "solver": 1}
