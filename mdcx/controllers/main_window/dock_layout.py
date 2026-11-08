"""左侧 dock 栏(导航按钮 + 状态栏)的布局。纯 Qt, 不依赖任何业务模块。"""

from PyQt6.QtCore import (
    QRect,
    Qt,
)
from PyQt6.QtWidgets import (
    QPushButton,
)

from mdcx.config.manager import manager


class DockLayoutMixin:
    # ============ 左侧导航坞（widget_setting）自适应（议题 #86/#102/#181）============
    # .ui 里侧栏是绝对定位：widget_buttons(0,50,210,390) 内 layoutWidget6(0,0,211,380)
    # 由 QVBoxLayout(spacing 8) 竖排 8 个 40px 导航按钮（8*40+7*8=376），下方
    # label_show_version(0,489,210,201) 是底对齐状态区（正常模式/配置文件名/版本号/
    # 点击检查最新版本），label_local_number(0,680,21,21) 是左下角数字浮标。
    # 设计态整列需 50+390+49+201+40(底距)=730 高；界面缩放很大时（用户 175% 反馈：
    # 可用逻辑分辨率仅 1097x594，窗口高 ~500）贴底公式 min(..., height-201) 会把状态区
    # 顶进导航区 → 状态文字压在「检测网络/使用说明」按钮上（叠字，见 _sync_dock_layout）。
    _DOCK_NAV_BTNS = (
        "pushButton_main",
        "pushButton_log",
        "pushButton_tool",
        "pushButton_emby_manager_nav",
        "pushButton_nfo_library",
        "pushButton_setting",
        "pushButton_net",
        "pushButton_about",
    )
    _DOCK_NAV_BTN_H = 40  # 导航按钮设计高（.ui setMaximumHeight(…, 40)）
    _DOCK_NAV_BTN_H_MIN = 36  # 压缩下限：border-width 9px×2 + 14px 字号仍能显示文字
    _DOCK_NAV_SPACING = 8  # verticalLayout 设计间距
    _DOCK_NAV_SPACING_MIN = 2  # 压缩下限（再小按钮会粘连）
    # widget_buttons 容器高。8 个导航按钮的内容高 8*40 + 7*8 = 376，容器只留这么多：
    # 原设计值 390 多出的 14px 是纯余量（layoutWidget6 的 QVBoxLayout 把富余空间堆在
    # 末尾，**不影响按钮落位**，见 _layout_dock_nav），收掉后二维码白得 14px 预算。
    # 这 14px 正是「状态文字固定预留 5 行 + 二维码恒 180px」能在**默认窗高 700**
    # 同时成立的关键：700 高下 5 行预留(75) + 间距(16) + 链接(22) + 内距(4) + 二维码(180)
    # = 297，加导航底 20+376=396 共 693 ≤ 700，还余 7px；若容器仍高 390（导航底 410）
    # 则需 707 > 700，缺口会把导航整个上移 7px（用户反馈的「整体向上移动」）。
    # 注：曾把按钮/间距收紧到 38/4、容器收到 340，用户反馈后已
    _DOCK_NAV_H = 376
    # 导航区顶边的两个取值，与 _windows_auto_adjust 里的 widget_buttons.move(0, 50/20)
    # 必须一致——那条 move 只在启动/标题栏设置变更时跑一次，_sync_dock_layout 随后会
    # 读 .y() 把它当基线。写成常量而不是读 .y()：_layout_dock_nav 结尾会
    # setGeometry(0, top, …) 把读回来的值又写回去，若基线来自自身就会被逐次抬高。
    _DOCK_NAV_TOP_HIDE = 50  # 隐藏窗口标题栏（window_title == "hide"）
    _DOCK_NAV_TOP_SHOW = 20  # 显示窗口标题栏
    # 导航区可上移到离窗顶多近。用户原话「软件界面容器上方还有10px以上的空间」——
    # 即要求二维码显示不满时把导航整体上移利用这段空间，但**不能顶到 0**（留 10px，
    # 否则第一个按钮贴着窗口边框、圆角与阴影会被切）。
    _DOCK_NAV_TOP_MIN = 10
    _DOCK_STATUS_H = 201  # label_show_version 设计高
    _DOCK_STATUS_H_MIN = 72  # 状态区压缩下限（13px 字号约 4 行，超出裁上方空行）
    _DOCK_STATUS_GAP = 12  # 导航底与状态区顶的最小间距
    # 状态区底（= 状态矩形底 = 窗底）距窗底的预留。原为 40（议题 #102：贴底太靠下），
    # 但 label_show_version 是 AlignBottom 的——文字只占矩形底部约 3~4 行，矩形底与
    # 文字底之间那 40px 全是死区，用户截图里「读取模式·字段优先 / actor.json / MDCx
    # 版本号 / 点击检查最新版本」四行整体悬在窗底上方、下面空一截。改为 0。
    # 这是「二维码保持 180px」能稳定成立的关键——原先默认窗高下预算只有 177。
    # 它只决定「窗底这条基准线在哪」，富余高度落在导航与状态区之间。
    # 在块与这条线之间（用户要的就是这个），0 = 基准线就是窗底、富余最多。
    # 注：置 0 后 _DOCK_STATUS_Y_MIN 在公式里被 min(..., height-_DOCK_STATUS_H) 覆盖
    # （min(max(x, 489), x) ≡ x），该下限对「空间够」分支不再生效，仅矮窗分支仍用。
    _DOCK_STATUS_BOTTOM_PAD = 0  # 状态区底与窗底之间的预留（0 = 基准线就是窗底）
    _DOCK_STATUS_Y_MIN = 489  # 状态区不低于设计 y
    _DOCK_LOCAL_Y_MIN = 680  # label_local_number 不低于设计 y
    _DOCK_LOCAL_H = 21  # label_local_number 设计高
    # 状态文字离屏探针的测量宽度：够大才不会按宽度折行（见 _dock_status_text_probe_h）
    _DOCK_STATUS_TEXT_PROBE_W = 4096
    # 状态文字块高（_dock_status_text_h）的上次测量值，-1 = 从未测量。作「行数是否变了」
    # 的闸门：show_scrape_info 在刮削过程中按**文件**刷新同一行进度文案（可达上千次），
    # 不设闸门就会每个文件重排一次左侧导航（见 _resync_dock_status_layout）。
    _dock_status_text_h_last = -1

    def _dock_status_text_h(self) -> int:
        """状态区（正常模式·字段优先 / 配置文件 / 版本号 / 点击检查）文字块的**估算**高度。

        只作两件事：
          ① 「行数变了没有」的闸门键（`_resync_dock_status_layout`）——`show_scrape_info` 在
             刮削过程中按**文件**刷新同一行进度文案（一次批量可达上千次），不设闸门就会
             每个文件重排一次左侧导航；
          ② 极矮窗口下判断状态区还能不能留 `_DOCK_STATUS_H_MIN`（见 `_sync_dock_layout`）。
        公式是**估算**：真实运行每行都带 emoji、真实行距 17px 而 lineSpacing 只报 15px，
        故它会**低估**（100% 字号 5 行估 75、真实 85）。凡是需要「准」的地方一律用
        `_dock_status_text_probe_h`（真实排版探针）。
        """
        label = self.Ui.label_show_version
        fm = label.fontMetrics()
        text = label.text()
        breaks = text.count("\n") + text.count("<br>")
        # show_scrape_info 的文本以换行开头（f"\n{scrape_info}..."），那一行是空的、
        # 只在块顶部留白而无墨迹。label 是底对齐的，这行空白不移动末行，故要扣掉，
        # 否则间距会整整多出一个行高（实测 15px）。
        stripped = text.lstrip("\n\r")
        breaks -= text[: len(text) - len(stripped)].count("\n")
        return fm.lineSpacing() * breaks + fm.height()

    def _dock_status_text_probe_h(self, text: str) -> int:
        """按 `text` 的**真实排版**量出文字块高度（离屏探针，非估算）。

        为什么不能拿 `lineSpacing × (行数−1) + height` 顶替：真实运行的状态文字每一行
        都以 emoji 开头（🎉/💠/🛠/🐰/🔍），Qt 对这些码位回退到 emoji 字体，而**回退字体的
        行距比 `fontMetrics().lineSpacing()` 报的值大 2px**。实测 100% 字号 Consolas：
        `lineSpacing()=15 / height()=15`，但 `QLabel.sizeHint().height()` 逐行实测
        1行17 / 2行34 / 3行51 / 4行68 / **5行85** / 6行102 / 7行119 —— 即真实行距 17。
        公式估出的 5 行 75 整整少 10px，这就是用户截图里末行被窗底裁掉的直接原因。

        `boundingRect(宽矩形, TextExpandTabs, text)` 会走真实的字体回退与行距，实测对
        5 个 emoji 得 85，与 `sizeHint()` 的真实渲染**逐值相符**；对纯 ASCII/CJK 则给出
        15/行（正确，那些字形没有回退）。宽度必须够大（`_DOCK_STATUS_TEXT_PROBE_W`），否则
        boundingRect 会按给定宽度折行、把行高算多（实测 `"\n"×5` 得 90 ≠ 85）。

        `<br>` 会被 Qt 当软换行渲染（`show_scrape_info` 的文案里有），但对纯文本探针而言
        只是普通字符，故先换成 `\n` 再量。行首那个空行（`show_scrape_info` 的文本以 `\n`
        开头）同样先剥掉——它只在块顶留白、无墨迹，且底/顶对齐都不受它影响。
        """
        probe = text.replace("<br>", "\n").lstrip("\n\r")
        if not probe:
            return 0
        fm = self.Ui.label_show_version.fontMetrics()
        return fm.boundingRect(
            QRect(0, 0, self._DOCK_STATUS_TEXT_PROBE_W, 0),
            Qt.TextFlag.TextExpandTabs,
            probe,
        ).height()

    def _resync_dock_status_layout(self) -> None:
        """状态文字**行数变了**之后重排贴底区，避免新增的行被窗口底部裁掉。

        回归背景（用户截图，读取模式）：首次读取完成后 `show_scrape_info` 往
        `label_show_version` **顶部**追加一行「🎉 刮削完成 7/7」，状态区高度变化后需要
        重新贴底排版，否则新增的行会被窗口底部裁掉。

        用文字块高做闸门：行数没变就不动。`show_scrape_info` 在刮削过程中按文件调用
        （`scraper.py: 已刮削 {count}/{count_all}`），不设闸门会每个文件重排一次
        左侧导航。
        """
        if getattr(self, "Ui", None) is None:
            return
        text_h = self._dock_status_text_h()
        if text_h == self._dock_status_text_h_last:
            return
        self._dock_status_text_h_last = text_h
        self._sync_dock_layout()

    def set_dock_status_text(self, text: str) -> None:
        """`label_show_version` 的唯一入口：写文本 + 行数变了就重排贴底区。

        原先 `init.py` 把 `label_show_version` 信号直接连到 `QLabel.setText`，文本变了
        没人重排，新行会被窗口底部裁掉（见 `_resync_dock_status_layout`）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        ui.label_show_version.setText(text)
        self._resync_dock_status_layout()

    def _dock_nav_buttons(self) -> list[QPushButton]:
        """当前可见的导航按钮（配置可隐藏「演员管理/信息管理」两项）。"""
        ui = self.Ui
        return [b for b in (getattr(ui, name) for name in self._DOCK_NAV_BTNS) if not b.isHidden()]

    def _dock_nav_top_base(self) -> int:
        """导航区顶边的**设计基线**（50 隐藏标题栏 / 20 显示标题栏）。

        与 `_windows_auto_adjust` 里的 `widget_buttons.move(0, 50|20)` 取同一判据
        （`manager.config.window_title == "hide"`），但**不读 `ui.widget_buttons.y()`**：
        `_layout_dock_nav` 结尾会用 `setGeometry(0, top, …)` 把 top 写回去，若基线
        读自身则「上移导航」的结果会变成下次的基线，被逐次抬到窗顶。这里返回常量，
        「上移多少」完全由 `_sync_dock_layout` 的缺口计算决定，两边不互相污染。
        """
        try:
            hidden = manager.config.window_title == "hide"
        except Exception:  # 配置未就绪（启动早期）：按显示标题栏的保守值
            hidden = False
        return self._DOCK_NAV_TOP_HIDE if hidden else self._DOCK_NAV_TOP_SHOW

    def _layout_dock_nav(self, top: int, btn_h: int, spacing: int, container_h: int) -> None:
        """按给定按钮高/间距重排导航按钮（每个按钮 min=max=btn_h，布局无自由度，
        故内容高恒为 count*btn_h + (count-1)*spacing，调用方直接用公式值即可）。

        按钮位置由 layoutWidget6 内的 QVBoxLayout 驱动（军规②：改完尺寸/间距必须
        显式 invalidate+activate）。实测（最小脚本 + 离屏探针）：layoutWidget6 自身
        高度不影响按钮落位——富余空间只堆在末尾（间距不被拉伸），且 SetMinimumSize
        约束会用**缓存的** sizeHint 回写父几何，故此处不再 resize 它，只读不用写。
        """
        ui = self.Ui
        for btn in self._dock_nav_buttons():
            btn.setMinimumHeight(btn_h)
            btn.setMaximumHeight(btn_h)
        ui.verticalLayout.setSpacing(spacing)
        ui.verticalLayout.invalidate()
        ui.verticalLayout.activate()
        ui.widget_buttons.setGeometry(0, top, ui.widget_buttons.width(), container_h)

    def _sync_dock_layout(self) -> None:
        """左侧导航坞 + 贴底状态区随窗口高度同步，窗口过矮时压缩而非重叠。

        议题 #86：状态区原本固定设计 y 坐标，窗口拉高后滞留在上半区——改为贴 widget_setting
        底边下移并预留 40px（#102）；min(..., height-h) 上限保证矮窗口下 label 完整可见。
        议题 #181（用户 175% 界面缩放反馈截图）：上述公式只兜「底边不出窗」，没兜「顶边不撞
        导航」——窗口高 < 730 时状态区顶边（height-201）会进入导航区（50..440），
        「正常模式/actor.json/版本号」与「检测网络/使用说明」按钮叠字。
        这里按「设计基准 + 剩余高度」重算（军规③：固定公式、双向幂等，窗口拉高即复原）：
          ① 空间够（height ≥ 导航底 + 间距 + 状态设计高）：完全保持设计几何；
          ② 不够：导航保持设计高，状态区吃掉剩余高度（最小 72）；
          ③ 仍不够：先压导航间距、再压按钮高（各自有下限），状态区仍不足 72 才隐藏；
             极矮窗口（< 约 460）导航按设计尺寸排布、最下方按钮被窗底裁——此时
             叠字比裁切更糟，不再继续压缩。

        侧栏收款码 / [赞助作者] 区块已于 2026-11-08 整体移除，状态区直接贴在导航下方。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        # 无论走哪条分支都刷新闸门基线：本函数是唯一的「权威重排」入口，走完之后
        # 布局所依据的文字块高就是当前值，下一次文字变化才能被正确识别为「变了」。
        self._dock_status_text_h_last = self._dock_status_text_h()
        height = self.height()
        # 导航顶边基线取常量（50/20）而非 ui.widget_buttons.y()：_layout_dock_nav 结尾会
        # setGeometry(0, top, …) 把 top 写回控件，读自身会让「上移导航」的结果变成下次的
        # 基线、被逐次抬到窗顶。判据与 _windows_auto_adjust 的 move(0, 50|20) 保持一致。
        nav_top = self._dock_nav_top_base()
        nav = self._dock_nav_buttons()
        status = ui.label_show_version
        local = ui.label_local_number
        # ① 空间够：设计几何（议题 #86/#102 原公式，逐值不变）
        status_y = min(
            max(height - self._DOCK_STATUS_H - self._DOCK_STATUS_BOTTOM_PAD, self._DOCK_STATUS_Y_MIN),
            height - self._DOCK_STATUS_H,
        )
        if status_y >= nav_top + self._DOCK_NAV_H + self._DOCK_STATUS_GAP:
            self._layout_dock_nav(nav_top, self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING, self._DOCK_NAV_H)
            status.setGeometry(0, status_y, status.width(), self._DOCK_STATUS_H)
            status.setVisible(True)
            local.setVisible(True)
            local.move(
                0,
                min(
                    max(height - self._DOCK_LOCAL_H - self._DOCK_STATUS_BOTTOM_PAD, self._DOCK_LOCAL_Y_MIN),
                    height - self._DOCK_LOCAL_H,
                ),
            )
            return
        # ② 窗口过矮：导航按设计高/间距排布，状态区吃剩余高度
        avail = height - nav_top
        btn_h, spacing = self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING
        count = len(nav)
        content_h = count * btn_h + max(count - 1, 0) * spacing
        status_h = min(self._DOCK_STATUS_H, max(0, avail - content_h - self._DOCK_STATUS_GAP))
        if status_h < self._DOCK_STATUS_H_MIN and count:
            # ③ 状态区放不下 72：先压间距、再压按钮高，腾出状态区所需高度
            need = max(avail - self._DOCK_STATUS_H_MIN - self._DOCK_STATUS_GAP, 0)
            if count > 1 and count * btn_h + (count - 1) * spacing > need:
                spacing = max(self._DOCK_NAV_SPACING_MIN, min(spacing, (need - count * btn_h) // (count - 1)))
            if count * btn_h + (count - 1) * spacing > need:
                btn_h = max(self._DOCK_NAV_BTN_H_MIN, min(btn_h, (need - (count - 1) * spacing) // count))
            content_h = count * btn_h + (count - 1) * spacing
            status_h = min(self._DOCK_STATUS_H, max(0, avail - content_h - self._DOCK_STATUS_GAP))
        hide_status = status_h < self._DOCK_STATUS_H_MIN
        # 容器高度取 min(内容高, 可用高)：不够时最下方按钮被窗底裁（④，见 docstring）
        self._layout_dock_nav(nav_top, btn_h, spacing, max(min(content_h, avail), 0))
        if hide_status:
            # ④ 极矮窗口：状态区让位，导航独占整列（叠字比裁切更糟）
            status.setVisible(False)
            local.setVisible(False)
            return
        status.setVisible(True)
        local.setVisible(True)
        status_y = nav_top + content_h + self._DOCK_STATUS_GAP
        status.setGeometry(0, status_y, status.width(), status_h)
        # 数字浮标贴状态区左下角，且不得超出窗底
        local.move(0, min(status_y + status_h - self._DOCK_LOCAL_H, height - self._DOCK_LOCAL_H))
