"""
补全emby信息及头像
"""

import asyncio
import os
import re
import shutil
import time
import traceback
from typing import Literal

import aiofiles
import aiofiles.os
from lxml import etree

from ..base.web import download_file_with_filepath
from ..config.enums import EmbyAction
from ..config.extend import get_movie_path_setting
from ..config.manager import manager
from ..config.resources import resources
from ..models.emby import EMbyActressInfo
from ..signals import signal
from ..utils import get_used_time
from ..utils.file import copy_file_async
from ..utils.task_stop import stop_requested
from .emby_actor_image import (
    _get_actor_detail,
    _get_emby_actor_list,
    _get_gfriends_actor_data,
    update_emby_actor_photo,
)
from .emby_actor_manager import fill_actor_info_from_sources
from .emby_shared import _build_jellyfin_headers, _generate_server_url
from .minnano_crawler import load_cache


class ActorTaskStopped(Exception): ...


# 内置补全的并发数由配置 actor_info_concurrency 提供（1~50，1 = 单线程）。
# Emby/Jellyfin 侧没有速率压力，但每个演员会串行请求维基/Minnano/JavDB/本地库；
# 9922 个演员一次性全部开跑会同时压满网络栈，且每个演员只在整条链路跑完后
# 才输出一行，表现为「日志长时间空白」。默认 10 并发让结果稳定地逐条冒出来。
ACTOR_INFO_CONCURRENCY_DEFAULT = 10
ACTOR_INFO_CONCURRENCY_MAX = 50
# 每完成多少个演员输出一次进度（逐人结果已经单独输出，这里只防「看起来卡死」）。
ACTOR_INFO_PROGRESS_STEP = 50


def _actor_info_concurrency() -> int:
    """读取配置里的演员信息补全并发数，夹到 1~50；配置异常时回退默认值。"""
    try:
        value = int(getattr(manager.config, "actor_info_concurrency", ACTOR_INFO_CONCURRENCY_DEFAULT))
    except TypeError, ValueError:
        return ACTOR_INFO_CONCURRENCY_DEFAULT
    return max(1, min(value, ACTOR_INFO_CONCURRENCY_MAX))


def _is_stop_requested() -> bool:
    return stop_requested()


def _raise_if_stop_requested() -> None:
    if _is_stop_requested():
        raise ActorTaskStopped("手动停止演员补全")


async def creat_kodi_actors(add: bool, *, manage_button_state: bool = True) -> None:
    if manage_button_state:
        signal.change_buttons_status.emit()
    try:
        _raise_if_stop_requested()
        signal.show_log_text(f"📂 待刮削目录: {get_movie_path_setting().movie_path}")
        gfriends_actor_data: dict[str, str] | Literal[False] | None | bool
        if add:
            signal.show_log_text("💡 将为等待刮削目录中的每个视频创建.actors文件夹，并补全演员图片到.actors文件夹中\n")
            signal.show_log_text("👩🏻 开始补全 Kodi/Plex/Jvedio 演员头像...")
            gfriends_actor_data = await _get_gfriends_actor_data()
        else:
            signal.show_log_text("💡 将清除该目录下的所有 .actors 文件夹...\n")
            gfriends_actor_data = True

        _raise_if_stop_requested()
        if gfriends_actor_data:
            await _deal_kodi_actors(gfriends_actor_data, add)
    except ActorTaskStopped:
        signal.show_log_text("⛔️ 演员头像补全已手动停止！")
    finally:
        if manage_button_state:
            signal.reset_buttons_status.emit()
        signal.show_log_text("================================================================================")


async def update_emby_actor_info() -> None:
    signal.change_buttons_status.emit()
    # 加载缓存
    load_cache()
    start_time = time.time()
    tasks: list[asyncio.Task[tuple[int, str]]] = []
    try:
        _raise_if_stop_requested()
        emby_on = manager.config.emby_on
        server_name = "Emby" if "emby" == manager.config.server_type else "Jellyfin"
        signal.show_log_text(f"👩🏻 开始补全 {server_name} 演员信息...")

        actor_list = await _get_emby_actor_list()
        _raise_if_stop_requested()

        # 开局先把「处理谁、多少人、什么范围」说清楚：内置补全逐个演员输出结果，
        # 某个人整条链路跑完之前日志是空白的，9922 人时很容易被误认为卡死。
        concurrency = _actor_info_concurrency()
        scope = "仅缺少信息的演员" if EmbyAction.ACTOR_INFO_MISS in emby_on else "所有演员"
        signal.show_log_text(
            f"📋 待处理演员 {len(actor_list)} 个（{scope}），并发 {concurrency}，每个演员处理完会立即输出一行结果..."
        )

        sem = asyncio.Semaphore(concurrency)

        async def _run_one(actor: dict) -> tuple[int, str]:
            async with sem:
                return await _process_actor_async(actor, emby_on)

        for actor in actor_list:
            _raise_if_stop_requested()
            actor_name = actor.get("Name")
            if not isinstance(actor_name, str):
                continue
            task = asyncio.create_task(_run_one(actor))
            tasks.append(task)

        db = 0
        wiki = 0
        local = 0
        updated = 0
        completed = 0
        for done_task in asyncio.as_completed(tasks):
            _raise_if_stop_requested()
            flag, msg = await done_task
            _raise_if_stop_requested()
            updated += flag != 0
            wiki += flag & 1
            db += (flag >> 1) & 3
            local += (flag >> 3) & 1
            completed += 1
            signal.show_log_text(msg)
            if completed % ACTOR_INFO_PROGRESS_STEP == 0:
                signal.show_log_text(f"⏳ 处理进度: {completed}/{len(tasks)}")

        signal.show_log_text(
            f"\n🎉🎉🎉 补全完成！！！ 用时 {get_used_time(start_time)} 秒 共更新: {updated} Minnano: {sum(1 for t in tasks if t.done() and (t.result()[0] & 4))} Wiki: {wiki} DB: {db} Local: {local}"
        )

        if EmbyAction.ACTOR_INFO_PHOTO in emby_on:
            signal.show_log_text("5 秒后开始补全演员头像头像...")
            for _ in range(5):
                _raise_if_stop_requested()
                await asyncio.sleep(1)
            signal.show_log_text("\n")
            signal.change_buttons_status.emit()
            await update_emby_actor_photo()
            signal.reset_buttons_status.emit()
    except ActorTaskStopped:
        signal.show_log_text("⛔️ 演员信息补全已手动停止！")
    except asyncio.CancelledError:
        # 主界面「停止」走 executor.cancel_async() 直接取消本协程，不会抛
        # ActorTaskStopped（后者只在协程内部轮询到停止标记时才触发）。
        # 不在这里补一行日志的话，用户看到的日志会停在「连接成功」后突然结束，
        # 像是任务凭空消失、也没回写服务器。
        signal.show_log_text("⛔️ 演员信息补全已手动停止！")
        raise
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        signal.reset_buttons_status.emit()


async def _process_actor_async(actor: dict, emby_on: list[EmbyAction]) -> tuple[int, str]:
    """异步处理单个演员信息"""
    actor_name = actor.get("Name", "Unknown Actor")
    try:
        _raise_if_stop_requested()
        server_id = actor.get("ServerId", "")
        actor_id = actor.get("Id", "")
        # 已有资料时跳过
        actor_homepage, _, _, _, _, update_url = _generate_server_url(actor)
        res, error = await _get_actor_detail(actor)
        _raise_if_stop_requested()
        if res is None:
            return 0, f"🔴 {actor_name}: Emby/Jellyfin 获取演员信息错误！\n    错误信息: {error}"

        overview = res.get("Overview", "")
        if overview and "无维基百科信息" not in overview and EmbyAction.ACTOR_INFO_MISS in emby_on:
            return 0, f"✅ {actor_name}: Emby/Jellyfin 已有演员信息！跳过！"

        actor_info = EMbyActressInfo(name=actor_name, server_id=server_id, id=actor_id)
        _raise_if_stop_requested()

        # 共用数据源链路：本地→wiki→javdb→minnano→db
        sources, logs = await fill_actor_info_from_sources(
            actor_info,
            existing_overview=overview,
            skip_db_if_marker=EmbyAction.ACTOR_INFO_MISS in emby_on,
        )
        _raise_if_stop_requested()

        wiki_found = int(sources["wiki"])
        javdb_found = int(sources.get("javdb", 0))
        db_exist = sources["db"]
        minnano_found = int(sources["minnano"])
        local_applied = sources["local_applied"]

        # summary
        summary = "\n    " + "\n".join(logs) if logs else ""
        if minnano_found or db_exist or wiki_found or javdb_found or local_applied:
            # 议题 #56(图2): Emby/Jellyfin 都需要鉴权头, 否则 POST /Items/{id} 故 server 401
            headers = _build_jellyfin_headers()
            async with manager.acquire_computed() as computed:
                post_res, error = await computed.async_client.post_text(
                    update_url, json_data=actor_info.dump(), headers=headers, use_proxy=False
                )
            _raise_if_stop_requested()
            if post_res is not None:
                return (
                    (8 if local_applied else 0)
                    + (wiki_found << 0)
                    + (db_exist << 1)
                    + (minnano_found << 2)
                    + (javdb_found << 4),
                    f"✅ {actor_name} 更新成功.{summary}\n主页: {actor_homepage}",
                )
            return 0, f"🔴 {actor_name} 更新失败: {error}{summary}"
        return 0, f"🔴 {actor_name}: 未检索到演员信息！跳过！"

    except ActorTaskStopped:
        raise
    except Exception:
        return 0, f"🔴 {actor_name} 未知异常:\n    {traceback.format_exc()}"


async def show_emby_actor_list(mode: int) -> None:
    signal.change_buttons_status.emit()
    start_time = time.time()
    try:
        _raise_if_stop_requested()
        mode += 1
        if mode == 1:
            signal.show_log_text("🚀 开始查询所有演员列表...")
        elif mode == 2:
            signal.show_log_text("🚀 开始查询 有头像，有信息 的演员列表...")
        elif mode == 3:
            signal.show_log_text("🚀 开始查询 没头像，有信息 的演员列表...")
        elif mode == 4:
            signal.show_log_text("🚀 开始查询 有头像，没信息 的演员列表...")
        elif mode == 5:
            signal.show_log_text("🚀 开始查询 没信息，没头像 的演员列表...")
        elif mode == 6:
            signal.show_log_text("🚀 开始查询 有信息 的演员列表...")
        elif mode == 7:
            signal.show_log_text("🚀 开始查询 没信息 的演员列表...")
        elif mode == 8:
            signal.show_log_text("🚀 开始查询 有头像 的演员列表...")
        elif mode == 9:
            signal.show_log_text("🚀 开始查询 没头像 的演员列表...")

        actor_list = await _get_emby_actor_list()
        _raise_if_stop_requested()
        if not actor_list:
            return

        count = 1
        succ_pic = 0
        fail_pic = 0
        succ_info = 0
        fail_info = 0
        succ = 0
        fail_noinfo = 0
        fail_nopic = 0
        fail = 0
        total = len(actor_list)
        actor_list_temp = ""
        logs = ""
        for actor_js in actor_list:
            _raise_if_stop_requested()
            actor_name = actor_js["Name"]
            actor_imagetages = actor_js.get("ImageTags")
            actor_homepage, _, _, _, _, _ = _generate_server_url(actor_js)
            # http://192.168.5.191:8096/web/index.html#!/item?id=2146&serverId=57cdfb2560294a359d7778e7587cdc98

            if actor_imagetages:
                succ_pic += 1
                actor_list_temp = f"\n✅ {count}/{total} 已有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
            else:
                fail_pic += 1
                actor_list_temp = f"\n🔴 {count}/{total} 没有头像！ 👩🏻 {actor_name} \n{actor_homepage}"

            if mode > 7:
                if mode == 8 and actor_imagetages:
                    actor_list_temp = f"\n✅ {succ_pic}/{total} 已有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                    logs += actor_list_temp + "\n"
                elif mode == 9 and not actor_imagetages:
                    actor_list_temp = f"\n🔴 {fail_pic}/{total} 没有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                    logs += actor_list_temp + "\n"
                if count % 100 == 0 or (succ_pic + fail_pic) == total:
                    signal.show_log_text(logs)
                    logs = ""
                count += 1
            else:
                # http://192.168.5.191:8096/emby/Persons/梦乃爱华?api_key=your_api_key
                res, error = await _get_actor_detail(actor_js)
                _raise_if_stop_requested()
                if res is None:
                    signal.show_log_text(
                        f"\n🔴 {count}/{total} Emby/Jellyfin 获取演员信息错误！👩🏻 {actor_name} \n    错误信息: {error}"
                    )
                    continue
                overview = res.get("Overview")

                if overview:
                    succ_info += 1
                else:
                    fail_info += 1

                if mode == 1:
                    if actor_imagetages and overview:
                        signal.show_log_text(
                            f"\n✅ {count}/{total} 已有信息！已有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                        )
                        succ += 1
                    elif actor_imagetages:
                        signal.show_log_text(
                            f"\n🔴 {count}/{total} 没有信息！已有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                        )
                        fail_noinfo += 1
                    elif overview:
                        signal.show_log_text(
                            f"\n🔴 {count}/{total} 已有信息！没有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                        )
                        fail_nopic += 1
                    else:
                        signal.show_log_text(
                            f"\n🔴 {count}/{total} 没有信息！没有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                        )
                        fail += 1
                    count += 1
                elif mode == 2 and actor_imagetages and overview:
                    signal.show_log_text(
                        f"\n✅ {count}/{total} 已有信息！已有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                    )
                    count += 1
                    succ += 1
                elif mode == 3 and not actor_imagetages and overview:
                    signal.show_log_text(
                        f"\n🔴 {count}/{total} 已有信息！没有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                    )
                    count += 1
                    fail_nopic += 1
                elif mode == 4 and actor_imagetages and not overview:
                    signal.show_log_text(
                        f"\n🔴 {count}/{total} 没有信息！已有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                    )
                    count += 1
                    fail_noinfo += 1
                elif mode == 5 and not actor_imagetages and not overview:
                    signal.show_log_text(
                        f"\n🔴 {count}/{total} 没有信息！没有头像！ 👩🏻 {actor_name} \n{actor_homepage}"
                    )
                    count += 1
                    fail += 1
                elif mode == 6 and overview:
                    signal.show_log_text(f"\n✅ {count}/{total} 已有信息！ 👩🏻 {actor_name} \n{actor_homepage}")
                    count += 1
                elif mode == 7 and not overview:
                    signal.show_log_text(f"\n🔴 {count}/{total} 没有信息！ 👩🏻 {actor_name} \n{actor_homepage}")
                    count += 1

        signal.show_log_text(f"\n\n🎉🎉🎉 查询完成！ 用时: {get_used_time(start_time)}秒")
        if mode == 1:
            signal.show_log_text(
                f"👩🏻 演员数量: {total} ✅ 有头像有信息: {succ} 🔴 有头像没信息: {fail_noinfo} 🔴 没头像有信息: {fail_nopic} 🔴 没头像没信息: {fail}\n"
            )
        elif mode == 2:
            other = total - succ
            signal.show_log_text(f"👩🏻 演员数量: {total} ✅ 有头像有信息: {succ} 🔴 其他: {other}\n")
        elif mode == 3:
            signal.show_log_text(f"👩🏻 演员数量: {total} 🔴 有信息没头像: {fail_nopic}\n")
        elif mode == 4:
            signal.show_log_text(f"👩🏻 演员数量: {total} 🔴 有头像没信息: {fail_noinfo}\n")
        elif mode == 5:
            signal.show_log_text(f"👩🏻 演员数量: {total} 🔴 没信息没头像: {fail}\n")
        elif mode == 6 or mode == 7:
            signal.show_log_text(f"👩🏻 演员数量: {total} ✅ 已有信息: {succ_info} 🔴 没有信息: {fail_info}\n")
        else:
            signal.show_log_text(f"👩🏻 演员数量: {total} ✅ 已有头像: {succ_pic} 🔴 没有头像: {fail_pic}\n")
        signal.show_log_text("================================================================================")
    except ActorTaskStopped:
        signal.show_log_text("⛔️ 演员列表查询已手动停止！")
    finally:
        signal.reset_buttons_status.emit()


async def _deal_kodi_actors(gfriends_actor_data, add):
    vedio_path = get_movie_path_setting().movie_path
    if vedio_path == "" or not await aiofiles.os.path.isdir(vedio_path):
        signal.show_log_text("🔴 待刮削目录不存在！任务已停止！")
        return False
    actor_folder = resources.u("actor")
    emby_on = manager.config.emby_on
    all_files = await asyncio.to_thread(os.walk, vedio_path)
    all_actor = set()
    success = set()
    failed = set()
    download_failed = set()
    no_pic = set()
    actor_clear = set()
    for root, dirs, files in all_files:
        _raise_if_stop_requested()
        if not add:
            for each_dir in dirs:
                _raise_if_stop_requested()
                if each_dir == ".actors":
                    kodi_actor_folder = os.path.join(root, each_dir)
                    await asyncio.to_thread(shutil.rmtree, kodi_actor_folder, ignore_errors=True)
                    signal.show_log_text(f"✅ 头像文件夹已清理！{kodi_actor_folder}")
                    actor_clear.add(kodi_actor_folder)
            continue
        for file in files:
            _raise_if_stop_requested()
            if file.lower().endswith(".nfo"):
                nfo_path = os.path.join(root, file)
                vedio_actor_folder = os.path.join(root, ".actors")
                try:
                    async with aiofiles.open(nfo_path, encoding="utf-8") as f:
                        content = await f.read()
                    parser = etree.HTMLParser(encoding="utf-8")
                    xml_nfo = etree.HTML(content.encode("utf-8"), parser)
                    actor_list = xml_nfo.xpath("//actor/name/text()")
                    for each in actor_list:
                        _raise_if_stop_requested()
                        all_actor.add(each)
                        actor_name_list = resources.get_actor_data(each)["keyword"]
                        for actor_name in actor_name_list:
                            _raise_if_stop_requested()
                            if actor_name:
                                net_pic_path = gfriends_actor_data.get(f"{actor_name}.jpg")
                                if net_pic_path:
                                    vedio_actor_path = os.path.join(vedio_actor_folder, each + ".jpg")
                                    if await aiofiles.os.path.isfile(vedio_actor_path):
                                        if "actor_replace" not in emby_on:
                                            success.add(each)
                                            continue
                                    if "https://" in net_pic_path:
                                        net_file_name = net_pic_path.split("/")[-1]
                                        net_file_name = re.findall(r"^[^?]+", net_file_name)[0]
                                        local_file_path = actor_folder / net_file_name
                                        if not await aiofiles.os.path.isfile(local_file_path):
                                            if not await download_file_with_filepath(
                                                net_pic_path, local_file_path, actor_folder
                                            ):
                                                signal.show_log_text(f"🔴 {actor_name} 头像下载失败！{net_pic_path}")
                                                failed.add(each)
                                                download_failed.add(each)
                                                continue
                                    else:
                                        local_file_path = net_pic_path
                                    if not await aiofiles.os.path.isdir(vedio_actor_folder):
                                        await aiofiles.os.mkdir(vedio_actor_folder)
                                    await copy_file_async(local_file_path, vedio_actor_path)
                                    signal.show_log_text(f"✅ {actor_name} 头像已创建！ {vedio_actor_path}")
                                    success.add(each)
                                    break
                        else:
                            signal.show_log_text(f"🔴 {each} 没有头像资源！")
                            failed.add(each)
                            no_pic.add(each)
                except Exception:
                    signal.show_traceback_log(traceback.format_exc())
    if add:
        signal.show_log_text(
            f"\n🎉 操作已完成! 共有演员: {len(all_actor)}, 已有头像: {len(success)}, 没有头像: {len(failed)}, 下载失败: {len(download_failed)}, 没有资源: {len(no_pic)}"
        )
    else:
        signal.show_log_text(f"\n🎉 操作已完成! 共清理了 {len(actor_clear)} 个 .actors 文件夹!")
    return None
