"""自动刮削循环（定时触发 → 调度 → 启动）。

从 `main_window.py` 按集群切出，逻辑与文案逐字不变。"""

import time

from PyQt6.QtCore import QTimer

from mdcx.config.enums import Switch
from mdcx.config.manager import manager
from mdcx.core.scraper import start_new_scrape
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.signals import signal_qt


class AutoScrapeMixin:
    # region 自动刮削
    def auto_scrape(self):
        if Switch.TIMED_SCRAPE in manager.config.switch_on and self.Ui.pushButton_start_cap.text() == "开始":
            QTimer.singleShot(100, self._auto_scrape_do_work)

    def _auto_scrape_do_work(self):
        # singleShot(100) 的这 100ms 里用户可能已手工点「开始」或点了「停止」。
        # start_new_scrape() 会无条件清掉停止标志，直接开会让两份刮削并发
        # （重复移动 / NFO 互相覆盖），或把刚发出的停止请求抵消。
        if self.Ui.pushButton_start_cap.text() != "开始" or Flags.stop_requested:
            signal_qt.show_log_text(" ⏭ 已跳过本次循环刮削：有任务在跑或已请求停止。")
            return
        timed_interval = manager.config.timed_interval
        self.atuo_scrape_count += 1
        signal_qt.show_log_text(
            f"\n\n 🍔 已启用「循环刮削」！间隔时间：{timed_interval}！即将开始第 {self.atuo_scrape_count} 次循环刮削！"
        )
        if Flags.scrape_start_time:
            signal_qt.show_log_text(
                " ⏰ 上次刮削时间: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.scrape_start_time))
            )
        start_new_scrape(FileMode.Default)

    def auto_start(self):
        if Switch.AUTO_START in manager.config.switch_on:
            signal_qt.show_log_text("\n\n 🍔 已启用「软件启动后自动刮削」！即将开始自动刮削！")
            self.pushButton_start_scrape_clicked()
