"""演员信息补全并发数：配置为 1 时逐个处理，配置为 N 时最多 N 个同时处理。"""

import asyncio

import pytest

from mdcx.config.manager import manager
from mdcx.models.flags import Flags
from mdcx.signals import signal
from mdcx.tools import emby_actor_info


@pytest.fixture(autouse=True)
def reset_stop_flags():
    Flags.stop_requested = False
    signal.stop = False
    yield
    Flags.stop_requested = False
    signal.stop = False


class _SilentSignal:
    """只吞掉按钮状态与日志信号，避免测试依赖 Qt 主窗口。"""

    def emit(self, *_args):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(("configured", "expected_peak"), [(1, 1), (3, 3)])
async def test_update_emby_actor_info_respects_configured_concurrency(
    monkeypatch: pytest.MonkeyPatch, configured: int, expected_peak: int
):
    active = 0
    peak = 0

    async def fake_get_actor_list():
        return [{"Name": f"演员{i}", "Id": str(i)} for i in range(8)]

    async def fake_process_actor(actor: dict, emby_on):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
        finally:
            active -= 1
        return 1, f"done {actor['Name']}"

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "emby_on", [])
    monkeypatch.setattr(manager.config, "actor_info_concurrency", configured)
    monkeypatch.setattr(emby_actor_info, "_get_emby_actor_list", fake_get_actor_list)
    monkeypatch.setattr(emby_actor_info, "_process_actor_async", fake_process_actor)
    monkeypatch.setattr(emby_actor_info.signal, "change_buttons_status", _SilentSignal())
    monkeypatch.setattr(emby_actor_info.signal, "reset_buttons_status", _SilentSignal())
    monkeypatch.setattr(emby_actor_info.signal, "show_log_text", lambda _text: None)

    await emby_actor_info.update_emby_actor_info()

    assert peak == expected_peak


@pytest.mark.asyncio
async def test_actor_info_concurrency_is_clamped(monkeypatch: pytest.MonkeyPatch):
    """非法/越界配置不得让信号量崩掉：0 与负数按 1，超大值按上限 50。"""
    monkeypatch.setattr(manager.config, "actor_info_concurrency", 0)
    assert emby_actor_info._actor_info_concurrency() == 1
    monkeypatch.setattr(manager.config, "actor_info_concurrency", -5)
    assert emby_actor_info._actor_info_concurrency() == 1
    monkeypatch.setattr(manager.config, "actor_info_concurrency", 999)
    assert emby_actor_info._actor_info_concurrency() == 50
