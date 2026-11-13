"""solver 解出的 clearance 必须与 UA/出口成对复用。

依据 FlareSolverr README：
> If you want to use Cloudflare clearance cookie in your scripts, make sure you use the
> FlareSolverr User-Agent too. If they don't match you will see the challenge.

实测 javlibrary（2026-11-13）：solver 在 FlareSolverr 容器出口解出 clearance，直连却走
socks5 代理、UA 也是指纹随机值 → 每次直连都重新挑战，solver 被反复调用。
"""

import sys
from types import SimpleNamespace

import pytest

from mdcx.network_fingerprint import align_user_agent_platform, os_ua_platform_segment
from mdcx.web_async import AsyncWebClient


def _client(**kwargs) -> AsyncWebClient:
    return AsyncWebClient(timeout=1, cf_bypass_url="http://127.0.0.1:8000", **kwargs)


def test_bypass_proxy_falls_back_to_global_proxy_when_site_uses_proxy():
    """没配 Bypass 代理时，solver 必须跟直连同出口，否则 clearance 因 IP 不同立刻失效。"""
    client = _client(proxy="socks5://192.168.50.15:1080")

    assert client._resolve_cf_bypass_proxy(use_proxy=True) == "socks5://192.168.50.15:1080"
    # 站点本次不走代理（direct_sites / 全局关闭）时，solver 也不该自作主张走代理
    assert client._resolve_cf_bypass_proxy(use_proxy=False) == ""


def test_bypass_proxy_explicit_setting_wins():
    """显式配置的「Bypass 代理」优先于全局代理（允许 solver 单独走另一条链路）。"""
    client = _client(proxy="socks5://192.168.50.15:1080", cf_bypass_proxy="http://127.0.0.1:7890")

    assert client._resolve_cf_bypass_proxy(use_proxy=True) == "http://127.0.0.1:7890"


def test_solver_user_agent_platform_follows_running_os():
    """solver 在 Linux 容器里，UA 平台段必须换成本机系统的，不能写死。"""
    linux_ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"

    aligned = align_user_agent_platform(linux_ua)

    assert os_ua_platform_segment() in aligned
    assert "Chrome/152.0.0.0" in aligned, "浏览器版本要沿用 solver 的"
    assert "(KHTML, like Gecko)" in aligned, "只能改第一个括号里的平台段"
    if sys.platform != "linux":
        assert "X11; Linux x86_64" not in aligned


@pytest.mark.parametrize(
    ("fake_platform", "expected"),
    [
        ("win32", "Windows NT 10.0; Win64; x64"),
        ("darwin", "Macintosh; Intel Mac OS X 10_15_7"),
        ("linux", "X11; Linux x86_64"),
    ],
)
def test_align_user_agent_platform_per_os(monkeypatch, fake_platform: str, expected: str):
    """UA 平台段由运行平台决定（Windows/macOS/Linux 各一份，不写死）。"""
    monkeypatch.setattr(sys, "platform", fake_platform)

    aligned = align_user_agent_platform(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    )

    assert aligned.startswith(f"Mozilla/5.0 ({expected})")
    assert "Chrome/152.0.0.0" in aligned


def test_solver_user_agent_stored_alongside_cookies():
    """solver 响应里的 x-cf-bypasser-user-agent 要跟 cookie 一起入 jar，且平台段按本机重写。"""
    client = _client()
    response = SimpleNamespace(
        status_code=200,
        headers={
            "set-cookie": "cf_clearance=abc; Path=/",
            "x-cf-bypasser-user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/152.0.0.0",
        },
        url="https://javlibrary.com/",
    )

    stored = client._store_solver_response_cookies("javlibrary.com", "https://javlibrary.com", None, response)

    assert stored == 1
    locked = client._solver_user_agent_jar["https://javlibrary.com"]
    assert os_ua_platform_segment() in locked
    assert locked.endswith("Chrome/152.0.0.0")


def test_locked_user_agent_drops_stale_ua_hints():
    """锁 UA 时必须一并去掉指纹那套 sec-ch-ua*，否则浏览器画像自相矛盾。"""
    client = _client()
    key = "https://javlibrary.com"
    client._solver_user_agent_jar[key] = "Mozilla/5.0 (X11; Linux x86_64) Chrome/152.0.0.0"

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) Safari/604.1",
        "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136"',
        "Sec-CH-UA-Platform": '"iOS"',
        "sec-ch-ua-mobile": "?1",
        "Accept": "text/html",
    }

    client._apply_solver_identity(headers, key)

    assert headers["User-Agent"] == client._solver_user_agent_jar[key]
    leftovers = [name for name in headers if name.lower().startswith("sec-ch-ua")]
    assert not leftovers, f"UA 提示头未清干净: {leftovers}"
    assert headers["Accept"] == "text/html", "只清 UA 提示头，其它头不动"


def test_apply_solver_identity_noop_without_locked_ua():
    """没解过挑战的池不碰任何头。"""
    client = _client()
    headers = {"User-Agent": "UA-A", "sec-ch-ua": '"Chromium";v="136"'}

    client._apply_solver_identity(headers, "https://other.com")

    assert headers == {"User-Agent": "UA-A", "sec-ch-ua": '"Chromium";v="136"'}


def test_rotate_fingerprint_drops_locked_user_agent():
    """clearance 失效轮换指纹时，锁定的 UA 必须跟 cookie 一起丢弃。"""
    client = _client()
    key = "https://javlibrary.com"
    client._solver_user_agent_jar[key] = "UA-TEST"
    client._solver_cookie_jar[key] = {"cf_clearance": "abc"}
    client._pinned_fingerprint_by_pool_base[key] = ("javlibrary.com", "fp-1")
    client._force_rotate_fingerprint(key, None)

    assert key not in client._solver_user_agent_jar
    assert key not in client._solver_cookie_jar
