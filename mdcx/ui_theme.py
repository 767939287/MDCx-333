"""全局主题令牌与通用 QSS 构件（浅色 / 深色）。

这些部件与具体窗口无关：主窗口、裁剪窗口、赞赏窗口、演员管理对话框、站点优先级
对话框……都要用同一套配色与滚动条 / 菜单 / 树控件样式。放在 mdcx 根下作为中立层，
避免 views / tools 反向依赖 controllers 里的主窗口样式模块。

主窗口专属的部分（set_style / set_dark_style / 信息管理顶栏按钮样式）仍留在
mdcx/controllers/main_window/style.py，它从本模块导入并重新导出这些通用部件，
既有导入路径保持不变。

注意：_qss_resources 通过 mdcx.config.resources 的 resources 单例取绝对路径，
而该单例被大量测试用 style_mod.resources.qtr = ... 打补丁；两个模块持有的是同一个
Resources 实例，所以补丁依然生效。
"""

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from mdcx.config.resources import resources


def _qss_resources(style: str) -> str:
    """将 QSS 中的相对资源路径替换为 Qt 可识别的绝对路径。"""
    return (
        style.replace("url(resources/Img/check_indicator.svg)", f"url({resources.qtr('Img/check_indicator.svg')})")
        .replace("url(resources/Img/radio_indicator.svg)", f"url({resources.qtr('Img/radio_indicator.svg')})")
        .replace("url(resources/Img/chevron_down_light.svg)", f"url({resources.qtr('Img/chevron_down_light.svg')})")
        .replace("url(resources/Img/chevron_down_dark.svg)", f"url({resources.qtr('Img/chevron_down_dark.svg')})")
    )


# 结构档位：圆角 4 档 / 字号 4 档 / 间距 3 档。QSS 里一律引用这些键，
# 不再各处手写 px 值（换皮前 style.py 里散着 14 种圆角、6 种字号）。
RADIUS_SCALE = {
    "radius_sm": "4px",
    "radius_md": "8px",
    "radius_lg": "10px",
    "radius_pill": "20px",
}

FONT_SCALE = {
    "font_xs": "12px",
    "font_sm": "13px",
    "font_md": "14px",
    "font_lg": "16px",
}

SPACE_SCALE = {
    "space_xs": "2px",
    "space_sm": "4px",
    "space_md": "8px",
}

LIGHT_TOKENS = {
    "window": "#FFFFFF",
    "surface": "#F8FAFC",
    "surface_muted": "#F5F7FF",
    "text": "#111827",
    "text_muted": "#4B5563",
    "text_disabled": "#9AA3AF",
    "placeholder": "#6B7280",
    "border": "#D8DEE9",
    "accent": "#4C6EFF",
    "accent_hover": "#6684FF",
    "accent_pressed": "#3F5FE6",
    "link": "#0B63CE",
    "link_hover": "#084A9C",
    "selection_bg": "rgba(76, 110, 255, 42)",
    "selection_bg_inactive": "rgba(76, 110, 255, 34)",
    "selection_text": "#111827",
    "tree_hover": "rgba(76, 110, 255, 18)",
    "tree_border": "rgba(76, 110, 255, 170)",
    # --- 换皮 A1 新增语义色：浅色取值 = 换皮前的实际硬编码值，保证像素级不变 ---
    "sidebar": "#EEF3FF",
    "sidebar_text": "#000000",
    "panel": "rgba(246, 246, 246, 255)",
    "panel_border": "rgba(20, 20, 20, 50)",
    "editor_bg": "rgba(240, 245, 240, 240)",
    "group_box": "rgba(245, 245, 246, 220)",
    "group_box_flat": "rgba(246, 246, 246, 0)",
    "button_neutral": "rgba(220, 220, 220, 255)",
    "button_neutral_border": "#000000",
    "icon_button_hover": "rgba(181, 181, 181, 120)",
    "icon_button_pressed": "rgba(150, 150, 150, 120)",
    "tooltip_bg": "#FFFFFF",
    "tooltip_text": "#111827",
    "tab_bg": "#FFFFFF",
    "tab_selected": "#2080F7",
    "tab_border": "#E8E8E8",
    "indicator_border": "#B8C0CC",
    "input_bg": "#FFFFFF",
    "input_border": "#D8DEE9",
    "input_focus_bg": "#FFFFFF",
    "dropdown_bg": "#F8FAFC",
    "dropdown_hover": "#EEF2FF",
    "slider_groove": "#D7DDE8",
    "slider_handle": "#FFFFFF",
    "progress_chunk": "#5777FF",
    "splitter_line": "#BEBEBE",
    "log_bg_alt": "rgba(238, 245, 245, 60)",
    "log_bg_detail": "rgba(239, 255, 252, 240)",
    "log_bg_tail": "rgba(240, 245, 240, 240)",
    "outline_border": "#CBD5E1",
    "note_bg": "#FFFFFF",
    "note_hover_bg": "#F1F5F9",
    "note_hover_border": "#94A3B8",
    "note_pressed_bg": "#E2E8F0",
    "sidebar_text_muted": "#141414",
    "poster_border": "rgba(60, 60, 60, 100)",
    "text_soft": "rgba(0, 0, 0, 200)",
    "page_bg": "#FFFFFF",
    "config_footer_bg": "#FFFFFF",
}

DARK_TOKENS = {
    # 与 page_bg 同色：window 是 centralwidget / tab 栏空白区的底色，比页面更深一档
    # 会在顶部形成一条 #121A24 的断层（用户 2026-11-13 反馈"暗色颜色不统一"）。
    "window": "#18222D",
    "surface": "#18222D",
    "surface_muted": "#1D2834",
    "text": "#E5E7EB",
    "text_muted": "#B6C2D0",
    "text_disabled": "#6B7280",
    "placeholder": "#94A3B8",
    "border": "#2F3A46",
    "accent": "#6684FF",
    "accent_hover": "#8EA3FF",
    "accent_pressed": "#4C6EE0",
    "link": "#9DB7FF",
    "link_hover": "#C3D2FF",
    "selection_bg": "rgba(102, 132, 255, 80)",
    "selection_bg_inactive": "rgba(102, 132, 255, 58)",
    "selection_text": "#FFFFFF",
    "tree_hover": "rgba(102, 132, 255, 34)",
    "tree_border": "rgba(142, 163, 255, 190)",
    # --- 换皮 A1 新增语义色：暗色取值 = 换皮前的实际硬编码值 ---
    "sidebar": "#1F272F",
    "sidebar_text": "#FFFFFF",
    "panel": "#1F272F",
    "panel_border": "rgba(240, 240, 240, 150)",
    "editor_bg": "#18222D",
    "group_box": "rgba(180, 180, 180, 20)",
    "group_box_flat": "rgba(246, 246, 246, 0)",
    "button_neutral": "rgba(220, 220, 220, 50)",
    "button_neutral_border": "#000000",
    "icon_button_hover": "rgba(181, 181, 181, 120)",
    "icon_button_pressed": "rgba(150, 150, 150, 120)",
    "tooltip_bg": "#F9FAFB",
    "tooltip_text": "#111827",
    "tab_bg": "#242D37",
    "tab_selected": "#2080F7",
    "tab_border": "#1F272F",
    "indicator_border": "#5B6673",
    "input_bg": "#18222D",
    "input_border": "#2F3A46",
    "input_focus_bg": "#1D2834",
    "dropdown_bg": "#1D2834",
    "dropdown_hover": "#243244",
    "slider_groove": "#2F3A46",
    "slider_handle": "#F8FAFC",
    "progress_chunk": "#5777FF",
    "splitter_line": "#BEBEBE",
    "log_bg_alt": "#18222D",
    "log_bg_detail": "#1F272F",
    "log_bg_tail": "#18222D",
    "outline_border": "#3B4654",
    "note_bg": "#1D2834",
    "note_hover_bg": "#253140",
    "note_hover_border": "#566374",
    "note_pressed_bg": "#2B3A4C",
    "sidebar_text_muted": "#D2D2D2",
    "poster_border": "rgba(255, 255, 255, 200)",
    "text_soft": "rgba(255, 255, 255, 200)",
    "page_bg": "#18222D",
    "config_footer_bg": "#18222D",
}


def _tokens(dark: bool) -> dict[str, str]:
    """返回当前主题的完整 token 表（配色 + 圆角/字号/间距档位）。"""
    return {
        **(DARK_TOKENS if dark else LIGHT_TOKENS),
        **RADIUS_SCALE,
        **FONT_SCALE,
        **SPACE_SCALE,
    }


def get_theme_tokens(dark: bool) -> dict[str, str]:
    return _tokens(dark)


def apply_application_palette(dark: bool) -> None:
    app = QApplication.instance()
    if app is None:
        return

    t = _tokens(dark)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(t["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(t["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(t["surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(t["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor(t["link"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["placeholder"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(t["surface"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(t["surface_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor(t["text_disabled"]))
    try:
        palette.setColor(QPalette.ColorRole.Accent, QColor(t["accent"]))
    except AttributeError:
        pass
    app.setPalette(palette)  # type: ignore[attr-defined]


def build_tree_widget_style(dark: bool) -> str:
    t = _tokens(dark)
    return f"""
        QTreeWidget {{
            outline: 0;
            border: 0;
            color: {t["text"]};
            background: transparent;
            alternate-background-color: transparent;
            selection-background-color: transparent;
            selection-color: {t["selection_text"]};
        }}
        QTreeWidget::item {{
            color: {t["text"]};
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 2px 4px;
        }}
        QTreeWidget::item:hover {{
            color: {t["text"]};
            background: {t["tree_hover"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::item:selected,
        QTreeWidget::item:selected:active {{
            color: {t["selection_text"]};
            background: {t["selection_bg"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::item:selected:!active {{
            color: {t["selection_text"]};
            background: {t["selection_bg_inactive"]};
            border: 1px solid {t["tree_border"]};
        }}
        QTreeWidget::branch {{
            background: transparent;
            border: 0;
            image: none;
        }}
        QTreeWidget::branch:selected {{
            background: transparent;
            image: none;
        }}
    """


def build_menu_style(dark: bool) -> str:
    t = _tokens(dark)
    return f"""
        QMenu {{
            color: {t["text"]};
            background: {t["surface"]};
            border: 1px solid {t["border"]};
            padding: 4px;
        }}
        QMenu::item {{
            color: {t["text"]};
            padding: 5px 28px 5px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            color: #FFFFFF;
            background: {t["accent"]};
        }}
        QMenu::item:disabled {{
            color: {t["text_disabled"]};
        }}
        QMenu::separator {{
            height: 1px;
            background: {t["border"]};
            margin: 4px 8px;
        }}
    """


def build_scrollbar_style(dark: bool) -> str:
    handle = "#4B5563" if dark else "#CBD5E1"
    handle_hover = "#64748B" if dark else "#94A3B8"
    # 轨道透明：议题 #153 定的 16px 宽 + 实心直角手柄保留，但不再给轨道上底色。
    # 上底色会在设置页/信息管理页右侧画出一条贯穿整页的竖带，正好压在「保存」
    # 按钮右侧，看起来像按钮被切掉一截（用户 2026-11-13 反馈）。
    track = "transparent"
    # 议题 #153: 加宽(10->16px)、改直角实心、给轨道淡底色, 更接近浏览器滚动条;
    # 深/浅主题颜色由 build_scrollbar_style(dark) 统一切换。
    return f"""
        QScrollBar:vertical{{
            width: 16px;
            margin: 0;
            background: {track};
        }}
        QScrollBar::handle:vertical{{
            min-height: 44px;
            border-radius: 3px;
            background: {handle};
        }}
        QScrollBar::handle:vertical:hover{{
            background: {handle_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{{
            height: 0;
            background: transparent;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{{
            background: transparent;
        }}
        QScrollBar:horizontal{{
            height: 16px;
            margin: 0;
            background: {track};
        }}
        QScrollBar::handle:horizontal{{
            min-width: 44px;
            border-radius: 3px;
            background: {handle};
        }}
        QScrollBar::handle:horizontal:hover{{
            background: {handle_hover};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal{{
            width: 0;
            background: transparent;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal{{
            background: transparent;
        }}
    """
