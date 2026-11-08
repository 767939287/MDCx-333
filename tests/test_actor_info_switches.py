"""演员信息源开关：配置读取与主补全链路的跳过行为。"""

import pytest

from mdcx.config.manager import manager
from mdcx.models.emby import EMbyActressInfo
from mdcx.tools import emby_actor_manager


def test_enabled_actor_info_sources_keeps_order_and_skips_disabled(monkeypatch):
    monkeypatch.setattr(manager.config, "actor_info_sources", ["local", "wiki", "minnano", "database"])
    monkeypatch.setattr(manager.config, "actor_info_disabled", ["wiki", "database"])
    assert emby_actor_manager.enabled_actor_info_sources() == ["local", "minnano"]


def test_enabled_actor_info_sources_defaults_to_all(monkeypatch):
    monkeypatch.setattr(manager.config, "actor_info_sources", ["local", "wiki", "minnano", "database"])
    monkeypatch.setattr(manager.config, "actor_info_disabled", [])
    assert emby_actor_manager.enabled_actor_info_sources() == ["local", "wiki", "minnano", "database"]


@pytest.mark.asyncio
async def test_fill_actor_info_skips_disabled_sources(monkeypatch):
    calls: list[str] = []

    async def fake_wiki(name: str):
        calls.append("wiki")
        return None

    async def fake_minnano(info, wiki_intro: str = ""):
        calls.append("minnano")
        return None, ""

    def fake_db(info):
        calls.append("database")
        return 0, ""

    monkeypatch.setattr(emby_actor_manager, "fetch_wiki_actor", fake_wiki)
    monkeypatch.setattr(emby_actor_manager, "get_minnano_info", fake_minnano)
    monkeypatch.setattr(emby_actor_manager.ActressDB, "update_actor_info_from_db", staticmethod(fake_db))
    monkeypatch.setattr(emby_actor_manager.resources, "get_actor_data", lambda name: {"has_name": False})
    monkeypatch.setattr(manager.config, "use_database", True)
    monkeypatch.setattr(manager.config, "actor_info_sources", ["local", "wiki", "minnano", "database"])
    monkeypatch.setattr(manager.config, "actor_info_disabled", ["wiki", "minnano", "database"])

    info = EMbyActressInfo(name="测试", server_id="", id="")
    sources, _logs = await emby_actor_manager.fill_actor_info_from_sources(info)

    assert calls == []
    assert sources["wiki"] is False
    assert sources["minnano"] is False
    assert sources["db"] == 0


def test_settings_dialog_saves_info_source_switches(monkeypatch, app):
    """设置窗口取消勾选后，保存到 actor_info_disabled（UI 开关落盘）。"""
    from PyQt6.QtCore import Qt

    from mdcx.tools import emby_actor_manager_ui as ui

    seen: dict = {}
    monkeypatch.setattr(ui.manager.config, "actor_info_disabled", [])
    monkeypatch.setattr(ui.manager, "_replace_config", lambda cfg: seen.update(cfg=cfg), raising=False)
    monkeypatch.setattr(ui.manager, "save", lambda: seen.update(saved=True), raising=False)

    dlg = ui.EmbyActorSettingsDialog()
    try:
        target = None
        for index in range(dlg.info_list.count()):
            item = dlg.info_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == "wiki":
                target = item
                break
        assert target is not None
        target.setCheckState(Qt.CheckState.Unchecked)
        dlg._save()

        assert seen["cfg"].actor_info_disabled == ["wiki"]
        assert seen.get("saved") is True
    finally:
        dlg.close()
        app.processEvents()
