"""主窗口专属样式。

通用主题令牌与通用 QSS 构件（_qss_resources / LIGHT_TOKENS / DARK_TOKENS / _tokens /
get_theme_tokens / apply_application_palette / build_tree_widget_style / build_menu_style /
build_scrollbar_style）在中立层 mdcx/ui_theme.py，这里导入并重新导出，既有导入路径不变。

换皮 A1（2026-11-13）：浅色 / 深色两套几乎镜像的 QSS 合并为**一份模板**
`build_app_stylesheet(self, dark)`，按 token 渲染后一次性打给 centralwidget。

合并前是 6 个容器（widget_setting / page_main / page_tool / page_about / page_setting /
centralwidget）各 setStyleSheet 一次，同一批控件被 polish 3~4 遍；合并后子容器不再
单独下发样式。原来"各页各设一份"的规则用 `#page_tool ...` / `#page_setting ...` 这类
祖先选择器限定回原容器，避免 `*` / `QGroupBox` 等无前缀规则外溢到主界面。

有意统一的外观差异（换皮前两套 QSS 不一致的地方）：
- 输入框圆角：浅色 10px / 暗色 20px / 工具页 15px → 统一 `radius_lg`(10px)
- 输入框字号：浅色 14px / 暗色 13px → 统一 `font_md`(14px)
- 按钮 hover/pressed：原选择器缺 `QPushButton` 前缀（`:hover#foo`）导致部分按钮无反馈
  → 全部补全类型前缀
- `padding: 2px, 2px`（逗号非法，Qt 丢弃声明）→ 改 `padding: 2px`
- 补齐 disabled 态（输入框 / 勾选框 / 中性按钮 / 滑块）
"""

from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize

from mdcx.config.resources import resources
from mdcx.ui_theme import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    _qss_resources,
    _tokens,
    apply_application_palette,
    build_menu_style,
    build_scrollbar_style,
    build_tree_widget_style,
    get_theme_tokens,
)

__all__ = [
    "DARK_TOKENS",
    "LIGHT_TOKENS",
    "_apply_log_document_style",
    "_nfo_lib_top_button_qss",
    "_qss_resources",
    "_tokens",
    "apply_application_palette",
    "apply_nfo_lib_top_button_style",
    "build_app_stylesheet",
    "build_menu_style",
    "build_scrollbar_style",
    "build_tree_widget_style",
    "get_theme_tokens",
    "resources",
    "set_dark_style",
    "set_style",
]

if TYPE_CHECKING:
    from .main_window import MyMAinWindow


# 左侧导航按钮
_NAV_BUTTONS = (
    "pushButton_main",
    "pushButton_log",
    "pushButton_tool",
    "pushButton_setting",
    "pushButton_net",
    "pushButton_about",
    "pushButton_emby_manager_nav",
    "pushButton_nfo_library",
)

# 主界面标题类标签（原浅色 QSS 里 label_poster1 被重复列了一次，这里去重）
_MAIN_TITLE_LABELS = (
    "label_number1",
    "label_actor1",
    "label_title1",
    "label_poster1",
    "label_number",
    "label_actor",
    "label_title",
)

# 右上角图标按钮（无底色，hover 才出现灰底）
_ICON_BUTTONS = (
    "pushButton_right_menu",
    "pushButton_play",
    "pushButton_open_folder",
    "pushButton_open_nfo",
    "pushButton_show_hide_logs",
    "pushButton_save_failed_list",
    "pushButton_tree_clear",
    "pushButton_clear_logs",
)

# 灰底胶囊按钮（选目录 / 各种工具入口）
_NEUTRAL_BUTTONS = (
    "pushButton_save_new_config",
    "pushButton_save_new_config_tool",
    "pushButton_init_config",
    "pushButton_init_config_tool",
    "pushButton_success_list_close",
    "pushButton_success_list_save",
    "pushButton_success_list_clear",
    "pushButton_show_tips_close",
    "pushButton_nfo_close",
    "pushButton_nfo_save",
    "pushButton_show_pic_actor",
    "pushButton_add_actor_pic",
    "pushButton_add_actor_info",
    "pushButton_add_actor_pic_kodi",
    "pushButton_del_actor_folder",
    "pushButton_move_mp4",
    "pushButton_select_file",
    "pushButton_actor_db_pick_nfo_dir",
    "pushButton_actor_db_sync_aliases",
    "pushButton_select_local_library",
    "pushButton_select_netdisk_path",
    "pushButton_select_localdisk_path",
    "pushButton_creat_symlink",
    "pushButton_find_missing_number",
    "pushButton_select_thumb",
    "pushButton_start_single_file",
    "pushButton_select_file_clear_info",
    "pushButton_add_sub_for_all_video",
    "pushButton_view_failed_list",
    "pushButton_select_media_folder",
    "pushButton_select_media_folder_setting_page",
    "pushButton_select_data_dir",
    "pushButton_select_softlink_folder",
    "pushButton_select_sucess_folder",
    "pushButton_select_failed_folder",
    "pushButton_view_success_file",
    "pushButton_select_subtitle_folder",
    "pushButton_select_actor_photo_folder",
    "pushButton_select_gfriends_local",
    "pushButton_select_actor_info_db",
    "pushButton_select_config_folder",
    "pushButton_add_all_extrafanart_copy",
    "pushButton_del_all_extrafanart_copy",
    "pushButton_add_all_extras",
    "pushButton_del_all_extras",
    "pushButton_add_all_theme_videos",
    "pushButton_del_all_theme_videos",
    "pushButton_check_and_clean_files",
    "pushButton_search_by_number",
    "pushButton_search_by_url",
    "pushButton_cover_backfill_start",
)

# 蓝底胶囊按钮（保存 / 信息管理页操作）
_PRIMARY_BUTTONS = (
    "pushButton_save_config",
    "pushButton_save_config_tool",
    "pushButton_nfo_lib_save",
    "pushButton_nfo_lib_batch_save",
    "pushButton_nfo_lib_crop",
)

# 蓝底强调按钮（开始 / 检测网络 / 失败列表）
_START_BUTTONS = (
    "pushButton_start_cap",
    "pushButton_start_cap2",
    "pushButton_check_net",
    "pushButton_scraper_failed_list",
)

# 设置页各 tab 的内容容器（原浅/暗两份 QSS 各列一遍）
_SETTING_PAGES = (
    "tab1",
    "tab2",
    "tab3",
    "tab4",
    "tab5",
    "tab",
    "tab_2",
    "tab_3",
    "tab_4",
    "tab_5",
    "tab_6",
    "tab_7",
    "scrollAreaWidgetContents_guaxiaomulu",
    "scrollAreaWidgetContents_guaxiaomoshi",
    "scrollAreaWidgetContents_guaxiaowangzhan",
    "scrollAreaWidgetContents_xiazai",
    "scrollAreaWidgetContents_mingming",
    "scrollAreaWidgetContents_fanyi",
    "scrollAreaWidgetContents_zimu",
    "scrollAreaWidgetContents_shuiyin",
    "scrollAreaWidgetContents_nfo",
    "scrollAreaWidgetContents_yanyuan",
    "scrollAreaWidgetContents_wangluo",
    "scrollAreaWidgetContents_gaoji",
)

_FONT_FAMILY = "Consolas, 'PingFang SC', 'Microsoft YaHei UI', 'Noto Color Emoji', 'Segoe UI Emoji'"


def _sel(base: str, names: tuple[str, ...]) -> str:
    """把一组 objectName 拼成 `base#name1, base#name2, ...` 选择器。

    每个选择器都必须带完整前缀：`#a, :hover#b` 这种写法在 Qt 里只有首项生效。
    """
    return ", ".join(f"{base}#{name}" for name in names)


def _apply_log_document_style(self: MyMAinWindow, dark: bool) -> None:
    t = _tokens(dark)
    document_style = f"""
        a {{
            color: {t["link"]};
            text-decoration: none;
            font-weight: 500;
        }}
        a:hover {{
            color: {t["link_hover"]};
            text-decoration: underline;
        }}
    """
    for text_browser in (
        self.Ui.textBrowser_log_main,
        self.Ui.textBrowser_log_main_2,
        self.Ui.textBrowser_log_main_3,
        self.Ui.textBrowser_net_main,
        self.Ui.textBrowser_show_success_list,
        self.Ui.textBrowser_show_tips,
    ):
        text_browser.document().setDefaultStyleSheet(document_style)


def _nfo_lib_top_button_qss(dark: bool) -> str:
    """信息管理顶栏「选择目录」「刷新」按钮样式。

    外观与「软件设置 → 高级 → 选择目录」（pushButton_select_config_folder）保持一致，
    单独下发是为了在套用样式前后按控件原始尺寸钉死宽高，避免顶栏整体位移。
    """
    t = _tokens(dark)
    # 注意：每个选择器都要带上完整前缀，`#a,#b:hover` 会让 hover 状态作用在整组上
    return f"""
        QPushButton#pushButton_nfo_lib_select_dir,
        QPushButton#pushButton_nfo_lib_refresh{{
            font-size:{t["font_md"]};
            background-color: {t["button_neutral"]};
            border-color:{t["button_neutral_border"]};
            border-width:8px;
            border-radius:{t["radius_pill"]};
            padding: {t["space_xs"]};
        }}
        QPushButton:hover#pushButton_nfo_lib_select_dir,
        QPushButton:hover#pushButton_nfo_lib_refresh{{
            color: #FFFFFF;
            background-color: {t["accent"]};
            font-weight:bold;
        }}
        QPushButton:pressed#pushButton_nfo_lib_select_dir,
        QPushButton:pressed#pushButton_nfo_lib_refresh{{
            background-color:{t["accent_pressed"]};
            border-color:{t["button_neutral_border"]};
            border-width:14px;
            font-weight:bold;
        }}
        """


def apply_nfo_lib_top_button_style(self: MyMAinWindow, dark: bool) -> None:
    """套用信息管理顶栏按钮样式，并把宽高钉死在套用前的尺寸上。

    QSS 里的 padding/边框会改变控件的 sizeHint，直接套用会让顶部栏重新排版；
    这里先量出原始尺寸再固定，保证「选择目录」「刷新」按钮的宽高与加样式前完全一致。
    """
    sheet = _nfo_lib_top_button_qss(dark)
    for name in ("pushButton_nfo_lib_select_dir", "pushButton_nfo_lib_refresh"):
        button = getattr(self.Ui, name, None)
        if button is None:
            continue
        button.ensurePolished()
        hint = button.sizeHint()
        minimum = button.minimumSize()
        natural = QSize(max(hint.width(), minimum.width()), max(hint.height(), minimum.height()))
        button.setStyleSheet(sheet)
        button.setFixedSize(natural)


def build_app_stylesheet(self: MyMAinWindow, dark: bool) -> str:
    """渲染主窗口的**唯一**一份 QSS（浅色 / 深色由 token 决定）。"""
    t = _tokens(dark)
    arrow = "chevron_down_dark.svg" if dark else "chevron_down_light.svg"

    nav = _sel("#widget_setting QPushButton", _NAV_BUTTONS)
    main_titles = _sel("#page_main QLabel", _MAIN_TITLE_LABELS)
    setting_pages = _sel("#page_setting QWidget", _SETTING_PAGES)

    icon = _sel("QPushButton", _ICON_BUTTONS)
    icon_hover = _sel("QPushButton:hover", _ICON_BUTTONS)
    icon_pressed = _sel("QPushButton:pressed", _ICON_BUTTONS)

    neutral = _sel("QPushButton", _NEUTRAL_BUTTONS)
    neutral_hover = _sel("QPushButton:hover", _NEUTRAL_BUTTONS)
    neutral_pressed = _sel("QPushButton:pressed", _NEUTRAL_BUTTONS)
    neutral_disabled = _sel("QPushButton:disabled", _NEUTRAL_BUTTONS)

    primary = _sel("QPushButton", _PRIMARY_BUTTONS)
    primary_hover = _sel("QPushButton:hover", _PRIMARY_BUTTONS)
    primary_pressed = _sel("QPushButton:pressed", _PRIMARY_BUTTONS)

    start = _sel("QPushButton", _START_BUTTONS)
    start_hover = _sel("QPushButton:hover", _START_BUTTONS)
    start_pressed = _sel("QPushButton:pressed", _START_BUTTONS)

    return _qss_resources(f"""
        * {{
            font-family: {_FONT_FAMILY};
            font-size: {t["font_sm"]};
            color: {t["text"]};
        }}

        QWidget#centralwidget {{
            background: {t["window"]};
            border: {self.window_border}px solid {t["panel_border"]};
            border-radius: {self.window_radius}px;
        }}

        /* ---- 左侧导航栏 ---- */
        QWidget#widget_setting {{
            background: {t["sidebar"]};
            border-top-left-radius: {self.window_radius}px;
            border-bottom-left-radius: {self.window_radius}px;
        }}
        {nav} {{
            font-size: {t["font_md"]};
            color: {t["sidebar_text"]};
            border-width: 9px;
            border-color: gray;
            border-radius: {t["radius_lg"]};
            text-align: left;
            qproperty-iconSize: 20px 20px;
            padding-left: 20px;
        }}
        #widget_setting QLabel#label_show_version {{
            font-size: {t["font_sm"]};
            color: {t["sidebar_text_muted"]};
            border: 0px solid rgba(255, 255, 255, 80);
        }}

        /* ---- 主界面 ---- */
        {main_titles} {{
            font-size: {t["font_lg"]};
            font-weight: bold;
            background-color: {t["group_box_flat"]};
            border: 0px solid {t["panel_border"]};
        }}
        #page_main QLabel#label_file_path {{
            font-size: {t["font_lg"]};
            color: {t["text"]};
            background-color: {t["group_box_flat"]};
            font-weight: bold;
            border: 0px solid {t["panel_border"]};
        }}
        #page_main QLabel#label_poster_size {{
            color: {t["text_soft"]};
        }}
        #page_main QLabel#label_poster, #page_main QLabel#label_thumb {{
            border: 1px solid {t["poster_border"]};
        }}
        #page_main QGroupBox {{
            background-color: {t["group_box_flat"]};
        }}

        /* ---- 工具页 ---- */
        #page_tool * {{
            font-size: {t["font_sm"]};
        }}
        #page_tool QScrollArea {{
            background-color: {t["group_box_flat"]};
            border-color: {t["group_box_flat"]};
        }}
        #page_tool QWidget#scrollAreaWidgetContents_gongju {{
            background-color: {t["group_box_flat"]};
            border-color: {t["window"]};
        }}
        #page_tool QLabel {{
            font-size: {t["font_sm"]};
            border: 0px solid {t["panel_border"]};
        }}
        #page_tool QGroupBox {{
            background-color: {t["group_box"]};
            border-radius: {t["radius_lg"]};
        }}

        /* ---- 使用帮助页 ---- */
        #page_about * {{
            font-size: {t["font_sm"]};
        }}
        #page_about QTextBrowser {{
            font-family: {_FONT_FAMILY};
            font-size: {t["font_sm"]};
            border: 0px solid {t["splitter_line"]};
            background-color: {t["group_box_flat"]};
            padding: {t["space_xs"]};
        }}

        /* ---- 设置页 ---- */
        #page_setting * {{
            font-size: {t["font_sm"]};
        }}
        #page_setting QScrollArea {{
            background-color: {t["group_box_flat"]};
            border-color: {t["group_box_flat"]};
        }}
        /* tab 栏所在区域由 QTabWidget 自身背景绘制：不设会透出 centralwidget 的
           window 色（暗色 #121A24），比页面底色 #18222D 更黑，顶部出现一条断层。 */
        #page_setting QTabWidget {{
            background: {t["page_bg"]};
            border: 0px solid {t["page_bg"]};
        }}
        /* Tab 子控件选择器（QTabBar::tab / QTabWidget::tab-bar / ::pane）带祖先 ID
           前缀时 Qt 匹配不到，会退回系统 palette（暗色下表现为 #121A24 一条更黑的
           横带）。主窗口只有设置页有 QTabWidget，故写成无前缀全局规则。
           tests/test_ui_structure.py 不校验这几条，改前缀前先手测顶部 tab 栏底色。 */
        QTabWidget::tab-bar {{
            alignment: center;
        }}
        QTabWidget::pane {{
            border: 0px solid {t["group_box_flat"]};
            background: {t["page_bg"]};
        }}
        QTabBar::tab {{
            color: {t["text"]};
            border: 1px solid {t["tab_border"]};
            min-height: 3ex;
            min-width: 6ex;
            padding: {t["space_xs"]};
            background-color: {t["tab_bg"]};
            border-radius: {t["radius_sm"]};
        }}
        QTabBar::tab:selected {{
            color: #FFFFFF;
            font-weight: bold;
            border-bottom: 2px solid {t["tab_selected"]};
            background-color: {t["tab_selected"]};
            border-radius: {t["radius_sm"]};
        }}
        QTabBar::tab:hover:!selected {{
            border: 1px solid {t["accent"]};
        }}
        {setting_pages} {{
            background-color: {t["page_bg"]};
            border-color: {t["group_box_flat"]};
        }}
        #page_setting QLabel {{
            font-size: {t["font_sm"]};
            border: 0px solid {t["panel_border"]};
        }}
        #page_setting QLabel#label_config,
        #page_tool QLabel#label_config_tool {{
            font-size: {t["font_sm"]};
            /* 两页页脚同款：底色跟页面一致（工具页原本就无底色），只用一条上边框
               与滚动内容分开。写作 `#page_setting ... #label_config_tool` 是错的，
               那个标签实际在 page_tool 里，会被前缀挡掉。 */
            background: {t["config_footer_bg"]};
            border-top: 1px solid {t["border"]};
        }}
        #page_setting QPushButton {{
            color: {t["text"]};
        }}
        #page_setting QGroupBox {{
            background-color: {t["group_box"]};
            border-radius: {t["radius_lg"]};
        }}
        #page_setting QRadioButton, #page_setting QCheckBox {{
            font-size: {t["font_sm"]};
        }}
        #page_setting QPlainTextEdit {{
            font-size: {t["font_sm"]};
        }}

        /* ---- 结果树 / 日志面板 ---- */
        QTreeWidget {{
            background-color: {t["group_box_flat"]};
            font-size: {t["font_xs"]};
            border: 0px solid rgb(120, 120, 120);
        }}
        QTextBrowser#textBrowser_log_main, QTextBrowser#textBrowser_net_main {{
            font-size: {t["font_sm"]};
            border: 0px solid {t["splitter_line"]};
            background-color: {t["group_box_flat"]};
            padding: {t["space_xs"]};
        }}
        QTextBrowser#textBrowser_log_main_2 {{
            font-size: {t["font_sm"]};
            border-radius: 0px;
            border-top: 1px solid {t["splitter_line"]};
            background-color: {t["log_bg_alt"]};
            padding: {t["space_xs"]};
        }}
        QTextBrowser#textBrowser_log_main_3 {{
            font-size: {t["font_sm"]};
            border-radius: 0px;
            border-right: 1px solid {t["border"]};
            background-color: {t["log_bg_detail"]};
            padding: {t["space_xs"]};
        }}
        QTextBrowser#textBrowser_show_success_list, QTextBrowser#textBrowser_show_tips {{
            font-size: {t["font_sm"]};
            border: 1px solid {t["splitter_line"]};
            background-color: {t["log_bg_tail"]};
            padding: {t["space_xs"]};
        }}
        QWidget#widget_show_success, QWidget#widget_show_tips, QWidget#widget_nfo {{
            background-color: {t["panel"]};
            border: 1px solid {t["panel_border"]};
            border-radius: {t["radius_lg"]};
        }}
        QWidget#scrollAreaWidgetContents_nfo_editor {{
            background-color: {t["editor_bg"]};
            border: 0px solid {t["panel_border"]};
        }}

        /* ---- 输入控件 ---- */
        QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox {{
            font-size: {t["font_md"]};
            background: {t["input_bg"]};
            border-radius: {t["radius_lg"]};
            border: 1px solid {t["input_border"]};
            padding: 4px 8px;
            selection-background-color: {t["accent"]};
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
            border: 1px solid {t["accent"]};
            background: {t["input_focus_bg"]};
        }}
        QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {{
            color: {t["text_disabled"]};
            border: 1px solid {t["border"]};
        }}
        QTextEdit#textEdit_nfo_outline, QTextEdit#textEdit_nfo_originalplot, QTextEdit#textEdit_nfo_tag {{
            font-size: {t["font_md"]};
            background: {t["input_bg"]};
            border: 1px solid {t["input_border"]};
            padding: 4px 8px;
        }}

        /* ---- 下拉框 ---- */
        QComboBox {{
            combobox-popup: 0;
            font-size: {t["font_sm"]};
            color: {t["text"]};
            background: {t["input_bg"]};
            border: 1px solid {t["input_border"]};
            border-radius: {t["radius_md"]};
            padding: 3px 30px 3px 8px;
            selection-background-color: {t["accent"]};
        }}
        /* 「分屏缩放」下拉框：外框宽度被「隐藏演员管理」的 sizeHint 钉死（真机 102px），
           加宽这条路已被用户否掉，只能从控件内部腾地方。通用 QComboBox 的
           `padding-right: 30px` 在 QSS 样式下与 26px 箭头**重复占位**（Qt 已从内容区
           扣过箭头宽），102px 的框里文本区只剩 35px，而「跟随系统」要 52px，于是被
           截成「跟随系」。把冗余右内边距清零后文本区 35→65px，外框宽度、箭头位置
           都不动（见 tests/test_advanced_scale_combo_width.py）。 */
        QComboBox#comboBox_ui_scale {{
            padding: 3px 0px 3px 8px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 26px;
            border-left: 1px solid {t["input_border"]};
            border-top-right-radius: {t["radius_md"]};
            border-bottom-right-radius: {t["radius_md"]};
            background: {t["dropdown_bg"]};
        }}
        QComboBox::drop-down:hover {{
            background: {t["dropdown_hover"]};
        }}
        QComboBox::down-arrow {{
            image: url(resources/Img/{arrow});
            width: 14px;
            height: 14px;
        }}
        QComboBox:focus {{
            border: 1px solid {t["accent"]};
        }}
        QComboBox:disabled {{
            color: {t["text_disabled"]};
            border: 1px solid {t["border"]};
        }}
        QComboBox QAbstractItemView {{
            background: {t["panel"]};
            border: 1px solid {t["input_border"]};
            selection-background-color: {t["accent"]};
            selection-color: #FFFFFF;
            outline: 0;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 24px;
            padding: 4px 8px;
            color: {t["text"]};
        }}
        QComboBox QAbstractItemView::item:selected {{
            color: #FFFFFF;
            background: {t["accent"]};
        }}

        /* ---- 勾选框 / 单选框 ---- */
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {t["indicator_border"]};
            background: {t["input_bg"]};
        }}
        QCheckBox::indicator {{
            border-radius: {t["radius_sm"]};
        }}
        QRadioButton::indicator {{
            border-radius: 7px;
        }}
        QCheckBox::indicator:checked {{
            background: {t["accent"]};
            border: 1px solid {t["accent"]};
            image: url(resources/Img/check_indicator.svg);
        }}
        QRadioButton::indicator:checked {{
            background: {t["accent"]};
            border: 1px solid {t["accent"]};
            image: url(resources/Img/radio_indicator.svg);
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
            border: 1px solid {t["accent"]};
        }}
        QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
            border: 1px solid {t["border"]};
            background: {t["surface_muted"]};
        }}

        /* ---- 提示气泡 ---- */
        QToolTip {{
            border: 1px solid {t["input_border"]};
            border-radius: {t["radius_md"]};
            background: {t["tooltip_bg"]};
            color: {t["tooltip_text"]};
            padding: 6px 10px;
        }}

        /* ---- 图标按钮 ---- */
        {icon} {{
            background-color: transparent;
            border-radius: {t["radius_lg"]};
            border: 0px solid {t["panel_border"]};
        }}
        {icon_hover} {{
            background-color: {t["icon_button_hover"]};
        }}
        {icon_pressed} {{
            background-color: {t["icon_button_pressed"]};
        }}

        /* ---- 灰底胶囊按钮 ---- */
        {neutral} {{
            /* 必须显式给前景色：不写会继承到偏淡的默认色，浅色下压不住 #DCDCDC 底 */
            color: {t["text"]};
            font-size: {t["font_md"]};
            background-color: {t["button_neutral"]};
            border-color: {t["button_neutral_border"]};
            border-width: 8px;
            border-radius: {t["radius_pill"]};
            padding: {t["space_xs"]};
        }}
        {neutral_hover} {{
            color: #FFFFFF;
            background-color: {t["accent"]};
            font-weight: bold;
        }}
        {neutral_pressed} {{
            color: #FFFFFF;
            background-color: {t["accent_pressed"]};
            border-color: {t["button_neutral_border"]};
            border-width: 14px;
            font-weight: bold;
        }}
        {neutral_disabled} {{
            color: {t["text_disabled"]};
            background-color: {t["surface_muted"]};
            border-color: {t["border"]};
        }}

        /* ---- 蓝底保存按钮 ---- */
        {primary} {{
            color: #FFFFFF;
            font-size: {t["font_md"]};
            background-color: {t["accent"]};
            border-radius: {t["radius_pill"]};
            padding: {t["space_xs"]};
        }}
        {primary_hover} {{
            color: #FFFFFF;
            background-color: {t["accent_hover"]};
            font-weight: bold;
        }}
        {primary_pressed} {{
            color: #FFFFFF;
            background-color: {t["accent_pressed"]};
            border-color: {t["button_neutral_border"]};
            border-width: 14px;
            font-weight: bold;
        }}

        /* ---- 蓝底强调按钮 ---- */
        {start} {{
            color: #FFFFFF;
            font-size: {t["font_md"]};
            background-color: {t["accent"]};
            border-radius: {t["radius_pill"]};
            padding: {t["space_xs"]};
            font-weight: bold;
        }}
        {start_hover} {{
            color: #FFFFFF;
            background-color: {t["accent_hover"]};
            font-weight: bold;
        }}
        {start_pressed} {{
            color: #FFFFFF;
            background-color: {t["accent_pressed"]};
            border-color: {t["button_neutral_border"]};
            border-width: 12px;
            font-weight: bold;
        }}

        /* ---- 说明 / 字段提示按钮 ---- */
        QPushButton#pushButton_field_tips_nfo, QPushButton#pushButton_scrape_note {{
            color: {t["text"]};
            background: {t["note_bg"]};
            border: 1px solid {t["outline_border"]};
            border-radius: {t["radius_md"]};
            padding: 3px 10px;
        }}
        QPushButton:hover#pushButton_field_tips_nfo {{
            color: #FFFFFF;
            background: {t["accent"]};
            border: 1px solid {t["accent"]};
        }}
        QPushButton:pressed#pushButton_field_tips_nfo {{
            color: #FFFFFF;
            background: {t["accent_pressed"]};
            border: 1px solid {t["accent_pressed"]};
        }}
        QPushButton:hover#pushButton_scrape_note {{
            color: {t["text"]};
            background: {t["note_hover_bg"]};
            border: 1px solid {t["note_hover_border"]};
        }}
        QPushButton:pressed#pushButton_scrape_note {{
            color: {t["text"]};
            background: {t["note_pressed_bg"]};
            border: 1px solid {t["note_hover_border"]};
        }}

        /* ---- 滑块 ---- */
        QSlider::groove:horizontal {{
            height: 6px;
            border-radius: 3px;
            background: {t["slider_groove"]};
        }}
        QSlider::sub-page:horizontal {{
            border-radius: 3px;
            background: {t["accent"]};
        }}
        QSlider::add-page:horizontal {{
            border-radius: 3px;
            background: {t["slider_groove"]};
        }}
        QSlider::handle:horizontal {{
            width: 16px;
            height: 16px;
            margin: -5px 0;
            border-radius: 8px;
            border: 2px solid {t["accent"]};
            background: {t["slider_handle"]};
        }}
        QSlider::handle:horizontal:hover {{
            border: 2px solid {t["accent_pressed"]};
            background: {t["input_focus_bg"]};
        }}
        QSlider::handle:horizontal:disabled {{
            border: 2px solid {t["border"]};
            background: {t["surface_muted"]};
        }}

        {build_scrollbar_style(dark)}

        QProgressBar::chunk {{
            background-color: {t["progress_chunk"]};
            width: 3px; /*区块宽度*/
            margin: 0px;
        }}

        {build_tree_widget_style(dark)}
        """)  # noqa: E501


def set_style(self: MyMAinWindow) -> None:
    if self.dark_mode:
        self.set_dark_style()
        return

    apply_application_palette(False)
    _apply_log_document_style(self, False)
    self.Ui.centralwidget.setStyleSheet(build_app_stylesheet(self, False))
    apply_nfo_lib_top_button_style(self, False)


def set_dark_style(self: MyMAinWindow) -> None:
    apply_application_palette(True)
    _apply_log_document_style(self, True)
    self.Ui.centralwidget.setStyleSheet(build_app_stylesheet(self, True))
    apply_nfo_lib_top_button_style(self, True)
