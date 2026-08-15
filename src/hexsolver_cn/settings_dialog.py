from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .preferences import AppPreferences, StartupWindowMode
from .seed_cache import SeedCacheStats, SeedResultCache
from .session_store import SessionStore
from .theme import COLORS
from .dialogs import ask_confirmation
from .widgets import ChamferPanel


def format_storage_size(byte_count: int) -> str:
    value = float(max(0, byte_count))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return "0 B"


class StartupModeComboBox(QComboBox):
    """Branded combo box with an explicit, theme-independent chevron."""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = COLORS["blue"] if self.hasFocus() else COLORS["muted"]
        pen = QPen(QColor(color), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center_x = float(self.width() - 20)
        center_y = float(self.height()) / 2.0
        painter.drawLine(
            QPointF(center_x - 4.0, center_y - 2.0),
            QPointF(center_x, center_y + 2.0),
        )
        painter.drawLine(
            QPointF(center_x, center_y + 2.0),
            QPointF(center_x + 4.0, center_y - 2.0),
        )


class StartupModeItemDelegate(QStyledItemDelegate):
    """Keep popup rows legible and selected states consistent on Windows."""

    def paint(self, painter, option, index) -> None:
        styled = QStyleOptionViewItem(option)
        active = bool(
            styled.state
            & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)
        )
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        styled.palette.setColor(
            QPalette.ColorRole.Highlight,
            QColor(COLORS["blue_soft"]),
        )
        styled.palette.setColor(
            QPalette.ColorRole.HighlightedText,
            QColor(COLORS["reason_text"]),
        )
        styled.palette.setColor(
            QPalette.ColorRole.Text,
            QColor(COLORS["reason_text"] if active else COLORS["text"]),
        )
        super().paint(painter, styled, index)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(38, hint.height()))


class SettingsDialog(QDialog):
    """Scrollable settings surface designed to accept more sections later."""

    def __init__(
        self,
        cache: SeedResultCache | None,
        preferences: AppPreferences | None = None,
        parent: QWidget | None = None,
        *,
        session_store: SessionStore | None = None,
        has_active_session: bool = False,
    ) -> None:
        super().__init__(parent)
        self.cache = cache
        self.preferences = preferences or AppPreferences()
        self.session_store = session_store
        self.has_active_session = has_active_session
        self.guide_requested = False
        self.save_progress_requested = False
        self.load_progress_requested = False
        self.clear_progress_requested = False
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("设置 · HexInfinite 种子求解器")
        self.setWindowIcon(qta.icon("fa5s.cog", color=COLORS["orange"]))
        self.setModal(True)
        self.resize(720, 600)
        self.setMinimumSize(620, 420)
        self.setStyleSheet(
            f"""
            QDialog#SettingsDialog {{ background: {COLORS['background']}; }}
            QLabel#SettingsTitle {{
                color: {COLORS['text']}; font-size: 23px; font-weight: 700;
            }}
            QLabel#SettingsSectionTitle {{
                color: {COLORS['text']}; font-size: 16px; font-weight: 700;
            }}
            QLabel#SettingsDescription {{
                color: {COLORS['muted']}; font-size: 12px;
            }}
            QLabel#SettingsValue {{
                color: {COLORS['text']}; font-size: 13px; font-weight: 600;
            }}
            QPushButton#DangerButton {{
                color: {COLORS['danger']}; background: transparent;
                border: 1px solid {COLORS['danger']}; border-radius: 4px;
                min-height: 40px; padding: 0 18px; font-weight: 700;
            }}
            QPushButton#DangerButton:hover {{
                color: {COLORS['white']}; background: {COLORS['danger']};
            }}
            QPushButton#DangerButton:disabled {{
                color: {COLORS['faint']}; background: transparent;
                border-color: {COLORS['border']};
            }}
            QPushButton#DialogCloseButton {{
                color: {COLORS['white']}; background: {COLORS['blue']};
                border: none; border-radius: 4px; min-height: 40px;
                min-width: 96px; font-weight: 700;
            }}
            QPushButton#DialogCloseButton:hover {{ background: {COLORS['blue_hover']}; }}
            QPushButton#SettingsToggleButton {{
                color: {COLORS['blue_hover']}; background-color: {COLORS['white']};
                border: 1px solid {COLORS['blue']}; border-radius: 4px;
                min-height: 40px; padding: 0 16px; font-weight: 700;
            }}
            QPushButton#SettingsToggleButton:hover {{ background-color: {COLORS['blue_soft']}; }}
            QPushButton#SettingsToggleButton:checked,
            QPushButton#SettingsToggleButton:checked:hover,
            QPushButton#SettingsToggleButton:checked:pressed {{
                color: {COLORS['white']}; background-color: {COLORS['blue']};
                border-color: {COLORS['blue']};
            }}
            QPushButton#GuideButton {{
                color: {COLORS['blue_hover']}; background-color: {COLORS['white']};
                border: 1px solid {COLORS['blue']}; border-radius: 4px;
                min-height: 40px; padding: 0 16px; font-weight: 700;
            }}
            QPushButton#GuideButton:hover {{ background-color: {COLORS['blue_soft']}; }}
            QPushButton#GuideButton:disabled {{
                color: {COLORS['faint']}; background-color: {COLORS['panel_alt']};
                border-color: {COLORS['border']};
            }}
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(26, 22, 26, 20)
        root_layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(
            qta.icon("mdi6.hexagon-multiple", color=COLORS["orange"]).pixmap(30, 30)
        )
        header.addWidget(icon)
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("设置")
        title.setObjectName("SettingsTitle")
        title_column.addWidget(title)
        subtitle = QLabel(f"HexInfinite 种子求解器 · {__version__}")
        subtitle.setObjectName("SettingsDescription")
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch(1)
        root_layout.addLayout(header)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"color: {COLORS['border']};")
        root_layout.addWidget(divider)

        scroll = QScrollArea()
        scroll.setObjectName("SettingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea#SettingsScrollArea { background: transparent; border: none; }"
        )
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self.sections_layout = QVBoxLayout(content)
        self.sections_layout.setContentsMargins(0, 0, 6, 0)
        self.sections_layout.setSpacing(14)
        self.sections_layout.addWidget(self._build_startup_section())
        self.sections_layout.addWidget(self._build_progress_section())
        self.sections_layout.addWidget(self._build_guide_section())
        self.sections_layout.addWidget(self._build_mouse_controls_section())
        self.sections_layout.addWidget(self._build_cache_section())
        self.sections_layout.addStretch(1)
        scroll.setWidget(content)
        root_layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("SettingsDescription")
        self.feedback_label.setAccessibleName("设置操作结果")
        footer.addWidget(self.feedback_label, 1)
        close_button = QPushButton("完成")
        close_button.setObjectName("DialogCloseButton")
        close_button.setAccessibleName("关闭设置")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root_layout.addLayout(footer)

        self.refresh_cache_stats()

    def _build_startup_section(self) -> QWidget:
        panel = ChamferPanel(fill=COLORS["panel"], border=COLORS["border"], chamfer=13)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(qta.icon("fa5s.desktop", color=COLORS["blue"]).pixmap(22, 22))
        heading.addWidget(icon)
        title = QLabel("启动窗口")
        title.setObjectName("SettingsSectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        layout.addLayout(heading)

        description = QLabel(
            "选择应用下次启动时的窗口状态。有窗口最大化保留标题栏和系统任务栏；"
            "无边框全屏占满整个屏幕；普通窗口使用 1440 × 1024 的默认尺寸。"
        )
        description.setObjectName("SettingsDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.startup_mode_combo = StartupModeComboBox(panel)
        self.startup_mode_combo.setObjectName("StartupModeCombo")
        self.startup_mode_combo.setAccessibleName("应用启动窗口模式")
        self.startup_mode_combo.setAccessibleDescription("设置下次启动时使用的窗口状态")
        self.startup_mode_combo.setMaxVisibleItems(len(StartupWindowMode))
        self.startup_mode_combo.setStyleSheet(
            f"""
            QComboBox#StartupModeCombo {{
                color: {COLORS['text']}; background-color: {COLORS['white']};
                border: 1px solid {COLORS['border']}; border-radius: 4px;
                min-height: 42px; padding: 0 46px 0 14px; font-weight: 650;
            }}
            QComboBox#StartupModeCombo:hover {{ border-color: #CED2D1; }}
            QComboBox#StartupModeCombo:focus {{
                border: 2px solid {COLORS['blue']};
                padding-left: 13px;
            }}
            QComboBox#StartupModeCombo::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 40px; background-color: {COLORS['panel_alt']};
                border: none; border-left: 1px solid {COLORS['border']};
                border-top-right-radius: 4px; border-bottom-right-radius: 4px;
            }}
            """
        )
        # Stylesheets disable auto-fill during polish. Polish first so the white
        # surface below is retained on every Windows theme and Qt style.
        self.startup_mode_combo.ensurePolished()
        self.startup_mode_combo.setAutoFillBackground(True)
        combo_palette = self.startup_mode_combo.palette()
        for role in (
            QPalette.ColorRole.Window,
            QPalette.ColorRole.Base,
            QPalette.ColorRole.Button,
        ):
            combo_palette.setColor(role, QColor(COLORS["white"]))
        combo_palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
        combo_palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
        self.startup_mode_combo.setPalette(combo_palette)
        popup = self.startup_mode_combo.view()
        popup.setObjectName("StartupModePopup")
        popup.setAutoFillBackground(True)
        popup.viewport().setAutoFillBackground(True)
        popup.setMouseTracking(True)
        popup.setItemDelegate(StartupModeItemDelegate(popup))
        popup.setStyleSheet(
            f"""
            QAbstractItemView#StartupModePopup {{
                color: {COLORS['text']}; background-color: {COLORS['white']};
                border: 1px solid {COLORS['border']};
                outline: none; padding: 4px;
                selection-color: {COLORS['reason_text']};
                selection-background-color: {COLORS['blue_soft']};
            }}
            QAbstractItemView#StartupModePopup::item {{
                color: {COLORS['text']}; background-color: {COLORS['white']};
                border: none; min-height: 38px; padding: 0 12px;
            }}
            QAbstractItemView#StartupModePopup::item:hover,
            QAbstractItemView#StartupModePopup::item:selected {{
                color: {COLORS['reason_text']};
                background-color: {COLORS['blue_soft']};
            }}
            """
        )
        popup_palette = popup.palette()
        popup_palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["white"]))
        popup_palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
        popup_palette.setColor(
            QPalette.ColorRole.Highlight,
            QColor(COLORS["blue_soft"]),
        )
        popup_palette.setColor(
            QPalette.ColorRole.HighlightedText,
            QColor(COLORS["reason_text"]),
        )
        popup.setPalette(popup_palette)
        for mode in StartupWindowMode:
            self.startup_mode_combo.addItem(mode.label, mode.value)
        selected_index = self.startup_mode_combo.findData(
            self.preferences.startup_window_mode.value
        )
        self.startup_mode_combo.setCurrentIndex(max(0, selected_index))
        self.startup_mode_combo.currentIndexChanged.connect(self._set_startup_mode)
        layout.addWidget(self.startup_mode_combo)
        return panel

    def _set_startup_mode(self, index: int = -1) -> None:
        value = self.startup_mode_combo.currentData()
        try:
            mode = StartupWindowMode(str(value))
        except ValueError:
            mode = StartupWindowMode.MAXIMIZED
        self.preferences.set_startup_window_mode(mode)
        self.feedback_label.setText("启动窗口设置已保存，将在下次启动时生效。")
        self.feedback_label.setStyleSheet(f"color: {COLORS['blue_hover']};")

    def _build_guide_section(self) -> QWidget:
        panel = ChamferPanel(fill=COLORS["panel"], border=COLORS["border"], chamfer=13)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(qta.icon("fa5s.route", color=COLORS["orange"]).pixmap(22, 22))
        heading.addWidget(icon)
        title = QLabel("使用说明")
        title.setObjectName("SettingsSectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        layout.addLayout(heading)

        description = QLabel(
            "重新显示启动时的手绘引导，查看种子生成、手动同步、下一步推理和设置入口。"
            "引导可以随时关闭，成功生成地图后也会自动收起。"
        )
        description.setObjectName("SettingsDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.show_guide_button = QPushButton("重新查看使用说明")
        self.show_guide_button.setObjectName("GuideButton")
        self.show_guide_button.setIcon(
            qta.icon("fa5s.map-signs", color=COLORS["blue_hover"])
        )
        self.show_guide_button.setAccessibleName("重新查看使用说明")
        self.show_guide_button.clicked.connect(self._request_guide)
        action_row.addWidget(self.show_guide_button)
        layout.addLayout(action_row)
        return panel

    def _build_progress_section(self) -> QWidget:
        panel = ChamferPanel(fill=COLORS["panel"], border=COLORS["border"], chamfer=13)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(qta.icon("fa5s.save", color=COLORS["orange"]).pixmap(22, 22))
        heading.addWidget(icon)
        title = QLabel("局面与进度")
        title.setObjectName("SettingsSectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self.restore_session_state_label = QLabel()
        heading.addWidget(self.restore_session_state_label)
        layout.addLayout(heading)

        description = QLabel(
            "程序会持续保存最近一次真实局面。可以选择启动时是否询问恢复，也可以把当前局面另存为独立文件。"
        )
        description.setObjectName("SettingsDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.restore_session_toggle = QPushButton()
        self.restore_session_toggle.setObjectName("SettingsToggleButton")
        self.restore_session_toggle.setCheckable(True)
        self.restore_session_toggle.setAccessibleName("启动时恢复上次局面")
        self.restore_session_toggle.setChecked(
            self.preferences.restore_last_session_enabled
        )
        self.restore_session_toggle.toggled.connect(self._set_restore_session_enabled)
        restore_row = QHBoxLayout()
        restore_row.addStretch(1)
        restore_row.addWidget(self.restore_session_toggle)
        layout.addLayout(restore_row)
        self._refresh_restore_session_state()

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.save_progress_button = QPushButton("保存当前局面")
        self.save_progress_button.setObjectName("GuideButton")
        self.save_progress_button.setAccessibleName("把当前局面保存到文件")
        self.save_progress_button.setEnabled(self.has_active_session)
        self.save_progress_button.clicked.connect(self._request_save_progress)
        actions.addWidget(self.save_progress_button)

        self.load_progress_button = QPushButton("载入局面")
        self.load_progress_button.setObjectName("GuideButton")
        self.load_progress_button.setAccessibleName("从文件载入局面")
        self.load_progress_button.clicked.connect(self._request_load_progress)
        actions.addWidget(self.load_progress_button)

        self.clear_progress_button = QPushButton("清除当前进度")
        self.clear_progress_button.setObjectName("DangerButton")
        self.clear_progress_button.setAccessibleName("清除当前局面和自动保存")
        self.clear_progress_button.setEnabled(
            self.has_active_session
            or (self.session_store is not None and self.session_store.has_autosave())
        )
        self.clear_progress_button.clicked.connect(self._request_clear_progress)
        actions.addWidget(self.clear_progress_button)
        layout.addLayout(actions)
        return panel

    def _set_restore_session_enabled(self, enabled: bool) -> None:
        self.preferences.set_restore_last_session_enabled(enabled)
        self._refresh_restore_session_state()
        self.feedback_label.setText("自动恢复设置已保存。")
        self.feedback_label.setStyleSheet(f"color: {COLORS['blue_hover']};")

    def _refresh_restore_session_state(self) -> None:
        enabled = self.restore_session_toggle.isChecked()
        self.restore_session_toggle.setText(
            "启动时询问恢复已开启" if enabled else "启动时不询问恢复"
        )
        toggle_foreground = COLORS["white"] if enabled else COLORS["blue_hover"]
        toggle_background = COLORS["blue"] if enabled else COLORS["white"]
        toggle_hover = COLORS["blue_hover"] if enabled else COLORS["blue_soft"]
        self.restore_session_toggle.setStyleSheet(
            f"QPushButton {{ color: {toggle_foreground}; "
            f"background-color: {toggle_background}; border: 1px solid {COLORS['blue']}; "
            "border-radius: 4px; min-height: 40px; padding: 0 16px; font-weight: 700; }} "
            f"QPushButton:hover {{ background-color: {toggle_hover}; }}"
        )
        self.restore_session_state_label.setText("已开启" if enabled else "已关闭")
        foreground = COLORS["blue_hover"] if enabled else COLORS["muted"]
        background = COLORS["blue_soft"] if enabled else COLORS["panel_alt"]
        self.restore_session_state_label.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: 4px; "
            "padding: 4px 8px; font-size: 11px; font-weight: 700;"
        )

    def _request_save_progress(self) -> None:
        self.save_progress_requested = True
        self.accept()

    def _request_load_progress(self) -> None:
        self.load_progress_requested = True
        self.accept()

    def _request_clear_progress(self) -> None:
        self.clear_progress_requested = True
        self.accept()

    def _request_guide(self) -> None:
        self.guide_requested = True
        self.accept()

    def _build_mouse_controls_section(self) -> QWidget:
        panel = ChamferPanel(fill=COLORS["panel"], border=COLORS["border"], chamfer=13)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(qta.icon("fa5s.mouse-pointer", color=COLORS["orange"]).pixmap(22, 22))
        heading.addWidget(icon)
        title = QLabel("棋盘鼠标操作")
        title.setObjectName("SettingsSectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self.mouse_controls_state_label = QLabel()
        heading.addWidget(self.mouse_controls_state_label)
        layout.addLayout(heading)

        description = QLabel(
            "开启后沿用原版游戏的快速操作：左键排除，右键标记蓝色；"
            "对同一状态再次按相同按键会恢复为未知。关闭后继续使用左侧手动标记工具。"
        )
        description.setObjectName("SettingsDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.original_mouse_controls_toggle = QPushButton()
        self.original_mouse_controls_toggle.setObjectName("SettingsToggleButton")
        self.original_mouse_controls_toggle.setCheckable(True)
        self.original_mouse_controls_toggle.setAccessibleName("启用原版左右键棋盘操作")
        self.original_mouse_controls_toggle.setToolTip("左键排除，右键标记蓝色")
        self.original_mouse_controls_toggle.setChecked(
            self.preferences.original_mouse_controls_enabled
        )
        self.original_mouse_controls_toggle.toggled.connect(
            self._set_original_mouse_controls_enabled
        )
        action_row.addWidget(self.original_mouse_controls_toggle)
        layout.addLayout(action_row)
        self._refresh_mouse_controls_state()
        return panel

    def _set_original_mouse_controls_enabled(self, enabled: bool) -> None:
        self.preferences.set_original_mouse_controls_enabled(enabled)
        self._refresh_mouse_controls_state()
        self.feedback_label.setText("鼠标操作设置已保存。")
        self.feedback_label.setStyleSheet(f"color: {COLORS['blue_hover']};")

    def _refresh_mouse_controls_state(self) -> None:
        enabled = self.original_mouse_controls_toggle.isChecked()
        self.original_mouse_controls_toggle.setText(
            "原版左右键操作已开启" if enabled else "开启原版左右键操作"
        )
        toggle_foreground = COLORS["white"] if enabled else COLORS["blue_hover"]
        toggle_background = COLORS["blue"] if enabled else COLORS["white"]
        toggle_hover = COLORS["blue_hover"] if enabled else COLORS["blue_soft"]
        self.original_mouse_controls_toggle.setStyleSheet(
            f"QPushButton {{ color: {toggle_foreground}; "
            f"background-color: {toggle_background}; border: 1px solid {COLORS['blue']}; "
            "border-radius: 4px; min-height: 40px; padding: 0 16px; font-weight: 700; }} "
            f"QPushButton:hover {{ background-color: {toggle_hover}; }}"
        )
        self.mouse_controls_state_label.setText("已开启" if enabled else "已关闭")
        foreground = COLORS["blue_hover"] if enabled else COLORS["muted"]
        background = COLORS["blue_soft"] if enabled else COLORS["panel_alt"]
        self.mouse_controls_state_label.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: 4px; "
            "padding: 4px 8px; font-size: 11px; font-weight: 700;"
        )

    def _build_cache_section(self) -> QWidget:
        panel = ChamferPanel(fill=COLORS["panel"], border=COLORS["border"], chamfer=13)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(13)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(qta.icon("fa5s.database", color=COLORS["blue"]).pixmap(22, 22))
        heading.addWidget(icon)
        title = QLabel("种子结果缓存")
        title.setObjectName("SettingsSectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        self.cache_state_label = QLabel("自动启用")
        self.cache_state_label.setStyleSheet(
            f"color: {COLORS['blue_hover']}; background: {COLORS['blue_soft']}; "
            "border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: 700;"
        )
        heading.addWidget(self.cache_state_label)
        layout.addLayout(heading)

        description = QLabel(
            "首次生成仍使用精确原版后端；再次加载相同游戏版本、难度和种子时，"
            "会直接读取本地结果，尤其可以明显缩短困难地图的等待时间。"
        )
        description.setObjectName("SettingsDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        stats = QGridLayout()
        stats.setHorizontalSpacing(18)
        stats.setVerticalSpacing(9)
        for row, text in enumerate(("缓存条目", "占用空间", "存储位置")):
            label = QLabel(text)
            label.setObjectName("SettingsDescription")
            label.setAlignment(Qt.AlignmentFlag.AlignTop)
            stats.addWidget(label, row, 0)
        self.cache_count_value = QLabel("0")
        self.cache_count_value.setObjectName("SettingsValue")
        self.cache_size_value = QLabel("0 B")
        self.cache_size_value.setObjectName("SettingsValue")
        self.cache_path_value = QLabel("")
        self.cache_path_value.setObjectName("SettingsValue")
        self.cache_path_value.setWordWrap(True)
        self.cache_path_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cache_path_value.setAccessibleName("种子缓存存储位置")
        stats.addWidget(self.cache_count_value, 0, 1)
        stats.addWidget(self.cache_size_value, 1, 1)
        stats.addWidget(self.cache_path_value, 2, 1)
        stats.setColumnStretch(1, 1)
        layout.addLayout(stats)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.clear_cache_button = QPushButton("删除缓存")
        self.clear_cache_button.setObjectName("DangerButton")
        self.clear_cache_button.setIcon(qta.icon("fa5s.trash-alt", color=COLORS["danger"]))
        self.clear_cache_button.setAccessibleName("删除全部种子结果缓存")
        self.clear_cache_button.setToolTip("删除由本程序保存的全部种子生成结果")
        self.clear_cache_button.clicked.connect(self.confirm_clear_cache)
        action_row.addWidget(self.clear_cache_button)
        layout.addLayout(action_row)
        return panel

    def refresh_cache_stats(self) -> SeedCacheStats | None:
        if self.cache is None:
            self.cache_state_label.setText("未启用")
            self.cache_state_label.setStyleSheet(
                f"color: {COLORS['muted']}; background: {COLORS['panel_alt']}; "
                "border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: 700;"
            )
            self.cache_count_value.setText("—")
            self.cache_size_value.setText("—")
            self.cache_path_value.setText("当前运行模式未配置持久缓存")
            self.clear_cache_button.setEnabled(False)
            return None
        stats = self.cache.stats()
        self.cache_count_value.setText(f"{stats.entry_count} 项")
        self.cache_size_value.setText(format_storage_size(stats.total_bytes))
        self.cache_path_value.setText(str(stats.directory))
        self.cache_path_value.setToolTip(str(stats.directory))
        self.clear_cache_button.setEnabled(stats.entry_count > 0)
        return stats

    def confirm_clear_cache(self) -> None:
        if self.cache is None:
            return
        before = self.cache.stats()
        if before.entry_count == 0:
            self.feedback_label.setText("当前没有可删除的缓存。")
            self.refresh_cache_stats()
            return
        confirmed = ask_confirmation(
            self,
            title="删除种子结果缓存",
            message=f"确定删除 {before.entry_count} 项种子结果缓存吗？",
            detail="之后再次打开这些种子时，需要重新生成地图。",
            accept_text="删除缓存",
            reject_text="取消",
            destructive=True,
            default_accept=False,
        )
        if not confirmed:
            return
        self.cache.clear()
        after = self.refresh_cache_stats()
        if after is not None and after.entry_count == 0:
            self.feedback_label.setText("缓存已删除。")
            self.feedback_label.setStyleSheet(f"color: {COLORS['blue_hover']};")
        else:
            self.feedback_label.setText("部分缓存无法删除，请关闭占用文件的程序后重试。")
            self.feedback_label.setStyleSheet(f"color: {COLORS['danger']};")
