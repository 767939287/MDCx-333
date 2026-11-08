"""议题 #125/#137：MediaWiki（Wikidata/Wikipedia）请求限速与合规 User-Agent 回归测试。

维基媒体按客户端类型限速（未识别 10 req/min、仅合规 User-Agent 200 req/min）。
#125 曾对 wiki 域名单独限速 1 req/s 并改用可识别 UA；#137 放宽为「双桶」；
现在进一步改为 2 req/s + 180 req/min，且所有 Wikimedia 子域共用一个桶——
语言子域各建一个 180/min 桶会让总速率叠到官方限额以上。
"""

import asyncio

import pytest

from mdcx.config.manager import manager
from mdcx.consts import GITHUB_REPO
from mdcx.models.emby import EMbyActressInfo
from mdcx.tools import wiki
from mdcx.web_async import (
    _MEDIAWIKI_HOSTS,
    _MEDIAWIKI_RATE_PER_MIN,
    _MEDIAWIKI_RATE_PER_SEC,
    AsyncWebLimiters,
    _CompositeLimiter,
)


def test_mediawiki_hosts_use_dual_bucket_limiter():
    """wiki 域名须使用「2 req/s + 180 req/min」双桶限速；其它域名保持通用 8 req/s。"""
    limiters = AsyncWebLimiters()
    for host in _MEDIAWIKI_HOSTS:
        limiter = limiters.get(host)
        assert isinstance(limiter, _CompositeLimiter), f"{host} 未使用 wiki 双桶限速"
        buckets = {(lim.max_rate, lim.time_period) for lim in limiter.limiters}
        assert buckets == {
            (_MEDIAWIKI_RATE_PER_SEC, 1),
            (_MEDIAWIKI_RATE_PER_MIN, 60),
        }, f"{host} 双桶参数不符: {buckets}"
    # 非 wiki 域名仍是单个 8 req/s 限速器
    assert limiters.get("example.com").max_rate == 8


def test_all_wikimedia_subdomains_share_one_bucket():
    """任意语言子域 / commons / upload 都命中同一组桶，不能各自叠加额度。"""
    limiters = AsyncWebLimiters()
    shared = limiters.get("ja.wikipedia.org")
    assert isinstance(shared, _CompositeLimiter)
    for host in (
        "zh.wikipedia.org",
        "en.wikipedia.org",
        "zh.m.wikipedia.org",
        "upload.wikimedia.org",
        "commons.wikimedia.org",
    ):
        assert limiters.get(host) is shared, f"{host} 未复用同一个 Wikimedia 限速桶"


@pytest.mark.asyncio
async def test_composite_limiter_gates_by_tightest_bucket():
    """组合限速器的通过量取各桶的最小值（先到瓶颈的桶决定）。"""
    from aiolimiter import AsyncLimiter

    # 2/s + 1/min：受 1/min 桶限制，只应有 1 个请求立即通过
    comp = _CompositeLimiter(AsyncLimiter(2, 1000), AsyncLimiter(1, 1000))
    passed = 0
    for _ in range(2):
        try:
            async with asyncio.timeout(0.3):
                async with comp:
                    passed += 1
        except TimeoutError:
            break
    assert passed == 1, f"应受最紧桶限制只通过 1 个，实际 {passed}"

    # 2/s + 2/min：两个桶容量都为 2，应有 2 个请求立即通过
    comp2 = _CompositeLimiter(AsyncLimiter(2, 1000), AsyncLimiter(2, 1000))
    passed2 = 0
    for _ in range(3):
        try:
            async with asyncio.timeout(0.3):
                async with comp2:
                    passed2 += 1
        except TimeoutError:
            break
    assert passed2 == 2, f"两个桶容量 2 时应通过 2 个，实际 {passed2}"


def test_wiki_headers_use_identifiable_user_agent():
    """wiki 请求头须携带可识别 UA，避免被划入「未识别」档。

    #183 已把仓库从 cdlongbow/mdcx-diy 换成 z291173301/MDCx，UA 随之更新；
    此处断言 GITHUB_REPO 常量（单一来源），以后再换仓库也不会失效。
    """
    headers = wiki._wiki_headers()
    ua = headers["User-Agent"]
    assert "Mozilla" not in ua
    assert GITHUB_REPO in ua


@pytest.mark.asyncio
async def test_search_wiki_sends_identifiable_user_agent(monkeypatch):
    """search_wiki 实际发出的请求须带合规 UA（而非随机浏览器指纹）。"""
    captured: dict = {}

    async def fake_get_json(url, *, headers=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        return {"search": []}, ""

    monkeypatch.setattr(manager.computed.async_client, "get_json", fake_get_json)

    info = EMbyActressInfo(name="测试演员", server_id="server", id="actor")
    res, _msg = await wiki.search_wiki(info)

    assert res is None
    assert "wikidata.org" in captured["url"]
    ua = captured["headers"]["User-Agent"]
    assert "Mozilla" not in ua
    assert GITHUB_REPO in ua


@pytest.mark.asyncio
async def test_fetch_wiki_actor_sends_identifiable_user_agent(monkeypatch):
    """移植后的 fetch_wiki_actor 每次 Wikidata 请求也必须带合规 UA。"""
    from mdcx.tools import wiki_actor

    captured: list[dict] = []

    async def fake_get_json(url, *, headers=None, **kwargs):
        captured.append(headers or {})
        return {"search": []}, ""

    monkeypatch.setattr(manager.computed.async_client, "get_json", fake_get_json)
    monkeypatch.setattr(wiki_actor.resources, "get_actor_data", lambda name: {"has_name": False})

    assert await wiki_actor.fetch_wiki_actor("测试演员") is None
    assert captured
    for headers in captured:
        ua = headers["User-Agent"]
        assert "Mozilla" not in ua
        assert GITHUB_REPO in ua
