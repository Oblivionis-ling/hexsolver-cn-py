from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import qtawesome as qta
from PySide6.QtCore import QRegularExpression, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .board_view import HexBoardView
from .dialogs import ask_confirmation
from .models import Board, CellVisualType, Coord, MoveAction, SuggestedMove
from .onboarding import GuideTarget, OnboardingOverlay
from .original_bridge import build_default_seed_registry
from .preferences import AppPreferences, StartupWindowMode
from .reason_interaction import InteractiveReasonBrowser, ReasonReference
from .seed_workflow import Difficulty, SeedGeneratorRegistry, SeedRequest
from .settings_dialog import SettingsDialog
from .session import BoardStateError, InteractivePuzzleSession
from .session_store import SESSION_FILE_SUFFIX, SessionStore, SessionStoreError, StoredSession
from .simulation import SimulationSession
from .solver import HexReasoningSolver, PublicConstraintConflict, SolverCancelled
from .theme import COLORS, app_stylesheet
from .widgets import ChamferPanel, HexCounterBadge, StateButton


if TYPE_CHECKING:
    from .detector import HexImageDetector


SCREENSHOT_IMPORT_ENABLED = False
STEP_REASON_BOTTOM_SAFE_MARGIN = 28.0


def build_empty_board() -> Board:
    return Board(
        image_path="",
        image_size=(1100, 900),
        cells={},
        row_clues=[],
        origin=(0.0, 0.0),
        basis_a=(48.0, 0.0),
        basis_b=(24.0, 42.0),
        ring_threshold=18.0,
        logs=["尚未生成种子盘面。"],
        remaining_blue=None,
    )


def show_window_for_startup(window: QMainWindow, mode: StartupWindowMode) -> None:
    if mode is StartupWindowMode.FULLSCREEN:
        window.showFullScreen()
    elif mode is StartupWindowMode.NORMAL:
        window.showNormal()
    else:
        window.showMaximized()


class SeedGenerationThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        registry: SeedGeneratorRegistry,
        request: SeedRequest,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.request = request

    def run(self) -> None:
        try:
            puzzle = self.registry.generate(self.request, require_verified=True)
        except Exception as exc:  # The message is surfaced with a retry path in the UI.
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(puzzle)


class SolveStepThread(QThread):
    succeeded = Signal(object, int)
    failed = Signal(str, int)

    def __init__(
        self,
        board: Board,
        revision: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.board = board
        self.revision = revision

    def run(self) -> None:
        try:
            move = HexReasoningSolver(self.isInterruptionRequested).next_step(self.board)
        except SolverCancelled:
            return
        except Exception as exc:
            self.failed.emit(str(exc), self.revision)
            return
        self.succeeded.emit(move, self.revision)


class SimulationConflictThread(QThread):
    succeeded = Signal(object, int)
    failed = Signal(str, int)

    def __init__(
        self,
        board: Board,
        assumptions: dict[Coord, CellVisualType],
        revision: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.board = board
        self.assumptions = assumptions
        self.revision = revision

    def run(self) -> None:
        try:
            report = HexReasoningSolver(
                self.isInterruptionRequested
            ).find_public_conflict(self.board, self.assumptions)
        except SolverCancelled:
            return
        except Exception as exc:
            self.failed.emit(str(exc), self.revision)
            return
        self.succeeded.emit(report, self.revision)


class BoardStage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.board_view = HexBoardView(self)
        self.counter_badge = HexCounterBadge(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.board_view)

        self.mode_chip = QLabel("快速上手 · 尚未生成地图", self)
        self.mode_text = self.mode_chip.text()
        self.mode_verified = False
        self.mode_simulation = False
        self.mode_chip.setStyleSheet(
            f"background: rgba(255,255,255,220); color: {COLORS['muted']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 7px 11px;"
        )
        self.mode_chip.adjustSize()

        self.toast = QLabel("", self)
        self.toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast.setStyleSheet(
            f"background: {COLORS['charcoal']}; color: {COLORS['white']}; "
            "border-radius: 4px; padding: 9px 15px; font-weight: 600;"
        )
        self.toast.hide()

        self.tool_panel = ChamferPanel(self, fill="#FFFFFF", chamfer=10)
        tools = QHBoxLayout(self.tool_panel)
        tools.setContentsMargins(7, 5, 7, 5)
        tools.setSpacing(1)

        self.import_button = self._tool_button("fa5s.image", "截图识别精度优化中，暂时关闭")
        self.import_button.setEnabled(SCREENSHOT_IMPORT_ENABLED)
        self.import_button.setIcon(qta.icon("fa5s.image", color=COLORS["faint"]))
        self.import_button.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.undo_button = self._tool_button("fa5s.undo-alt", "撤销")
        self.redo_button = self._tool_button("fa5s.redo-alt", "重做")
        self.reset_button = self._tool_button("fa5s.sync-alt", "恢复初始盘面")
        self.zoom_out_button = self._tool_button("fa5s.search-minus", "缩小")
        self.zoom_in_button = self._tool_button("fa5s.search-plus", "放大")
        self.fit_button = self._tool_button("fa5s.expand", "适合窗口")
        self.settings_button = self._tool_button("fa5s.cog", "设置")
        for button in (
            self.import_button,
            self.undo_button,
            self.redo_button,
            self.reset_button,
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_button,
            self.settings_button,
        ):
            tools.addWidget(button)
        self.tool_panel.adjustSize()

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)

    @staticmethod
    def _tool_button(icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("GhostButton")
        button.setIcon(qta.icon(icon_name, color=COLORS["text"]))
        button.setIconSize(QSize(17, 17))
        button.setFixedSize(36, 34)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        return button

    def set_mode(
        self,
        text: str,
        *,
        verified: bool = False,
        simulation: bool = False,
    ) -> None:
        self.mode_text = text
        self.mode_verified = verified
        self.mode_simulation = simulation
        self.mode_chip.setText(text)
        accent = COLORS["orange"] if simulation else COLORS["blue"]
        text_color = (
            COLORS["orange_hover"]
            if simulation
            else COLORS["blue_hover"] if verified else COLORS["muted"]
        )
        self.mode_chip.setStyleSheet(
            f"background: rgba(255,255,255,225); color: {text_color}; "
            f"border: 1px solid {accent if simulation or verified else COLORS['border']}; "
            "border-radius: 4px; padding: 7px 11px; font-weight: 600;"
        )
        self.mode_chip.adjustSize()
        self._position_overlays()

    def show_toast(self, text: str, *, danger: bool = False, duration_ms: int = 3200) -> None:
        self.toast.setText(text)
        color = COLORS["danger"] if danger else COLORS["charcoal"]
        self.toast.setStyleSheet(
            f"background: {color}; color: {COLORS['white']}; "
            "border-radius: 4px; padding: 9px 15px; font-weight: 600;"
        )
        self.toast.adjustSize()
        self.toast.show()
        self.toast.raise_()
        self._position_overlays()
        self._toast_timer.start(duration_ms)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self) -> None:
        margin = 20
        self.counter_badge.move(self.width() - self.counter_badge.width() - margin, 12)
        self.mode_chip.move(24, 22)
        self.tool_panel.adjustSize()
        self.tool_panel.move(
            self.width() - self.tool_panel.width() - margin,
            self.height() - self.tool_panel.height() - margin,
        )
        self.toast.move((self.width() - self.toast.width()) // 2, 22)
        self.counter_badge.raise_()
        self.mode_chip.raise_()
        self.tool_panel.raise_()


class MainWindow(QMainWindow):
    def __init__(
        self,
        seed_generators: SeedGeneratorRegistry | None = None,
        preferences: AppPreferences | None = None,
        session_store: SessionStore | None = None,
        *,
        restore_on_startup: bool = False,
    ) -> None:
        super().__init__()
        self.setWindowTitle("HexInfinite 种子求解器")
        self.setMinimumSize(1120, 760)
        self.resize(1440, 1024)
        self.setWindowIcon(qta.icon("mdi6.hexagon", color=COLORS["orange"]))

        self.solver = HexReasoningSolver()
        self.seed_generators = seed_generators or build_default_seed_registry()
        self.preferences = preferences or AppPreferences()
        self.session_store = session_store or SessionStore()
        self.session = InteractivePuzzleSession(build_empty_board(), self.solver)
        self.simulation_session: Optional[SimulationSession] = None
        self.current_move: Optional[SuggestedMove] = None
        self.current_seed: Optional[SeedRequest] = None
        self.selected_state = CellVisualType.HIDDEN
        self._has_active_board = False
        self._guide_visible = False
        self._detector: Optional["HexImageDetector"] = None
        self._generation_thread: Optional[SeedGenerationThread] = None
        self._solve_thread: Optional[SolveStepThread] = None
        self._simulation_conflict_thread: Optional[SimulationConflictThread] = None
        self._session_revision = 0
        self._simulation_revision = 0
        self._simulation_check_pending = False
        self._simulation_origin_mode: Optional[tuple[str, bool]] = None
        self._solve_busy = False
        self._close_requested = False
        self._autosave_error_reported = False
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._save_autosave_now)

        self.root = QWidget()
        self.root.setObjectName("AppRoot")
        self.setCentralWidget(self.root)
        root_layout = QHBoxLayout(self.root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = self._build_sidebar()
        root_layout.addWidget(self.sidebar)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {COLORS['border']};")
        divider.setFixedWidth(1)
        root_layout.addWidget(divider)

        self.stage = BoardStage()
        root_layout.addWidget(self.stage, 1)

        self.stage.board_view.cell_activated.connect(self._on_cell_activated)
        self.stage.undo_button.clicked.connect(self.undo)
        self.stage.redo_button.clicked.connect(self.redo)
        self.stage.reset_button.clicked.connect(self.reset_board)
        self.stage.zoom_in_button.clicked.connect(self.stage.board_view.zoom_in)
        self.stage.zoom_out_button.clicked.connect(self.stage.board_view.zoom_out)
        self.stage.fit_button.clicked.connect(self.stage.board_view.fit_board)
        self.stage.import_button.clicked.connect(self.import_screenshot)
        self.stage.settings_button.clicked.connect(self.open_settings)
        self.simulation_button.clicked.connect(self.toggle_simulation)
        self.undo_action = QAction("撤销", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.addAction(self.undo_action)
        self.redo_action = QAction("重做", self)
        self.redo_action.setShortcuts(
            (QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Y"))
        )
        self.redo_action.triggered.connect(self.redo)
        self.addAction(self.redo_action)

        self.onboarding_overlay = OnboardingOverlay(
            self.stage,
            (
                GuideTarget(
                    "输入种子、选择难度，然后生成真实盘面。",
                    self.seed_panel,
                    COLORS["orange"],
                ),
                GuideTarget(
                    "按游戏当前进度同步蓝格与排除格。",
                    self.manual_panel,
                    COLORS["blue"],
                ),
                GuideTarget(
                    "卡住时计算下一步，并阅读完整推理理由。",
                    self.next_button,
                    COLORS["blue_hover"],
                ),
                GuideTarget(
                    "在设置中调整启动方式、鼠标操作或重看说明。",
                    self.stage.settings_button,
                    COLORS["orange_hover"],
                ),
            ),
            self.root,
        )
        self.guide_close_button = QPushButton("关闭说明", self.root)
        self.guide_close_button.setObjectName("GuideCloseButton")
        self.guide_close_button.setIcon(qta.icon("fa5s.times", color=COLORS["white"]))
        self.guide_close_button.setAccessibleName("关闭使用说明")
        self.guide_close_button.setAccessibleDescription(
            "关闭当前使用说明；可稍后从设置中重新打开"
        )
        self.guide_close_button.setFixedSize(112, 42)
        self.guide_close_button.setStyleSheet(
            self._primary_button_style(
                COLORS["charcoal"], COLORS["charcoal_hover"], 40, 13
            )
        )
        self.guide_close_button.clicked.connect(self.hide_onboarding)

        self._apply_mouse_control_preference()
        self._load_board(
            self.session.board,
            mode_text="快速上手 · 尚未生成地图",
            active=False,
            close_guide=False,
        )
        self.show_onboarding()
        if restore_on_startup:
            self._restore_autosave_on_startup()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(300)
        sidebar.setStyleSheet(f"background: {COLORS['background']};")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(15, 18, 15, 14)
        layout.setSpacing(9)

        self.seed_panel = self._build_seed_panel()
        layout.addWidget(self.seed_panel)
        self.manual_panel = self._build_manual_panel()
        layout.addWidget(self.manual_panel)
        self.step_panel = self._build_step_panel()
        layout.addWidget(self.step_panel, 1)
        return sidebar

    def _build_seed_panel(self) -> QWidget:
        panel = ChamferPanel(chamfer=16)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        title = QLabel("种子")
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        seed_row = QHBoxLayout()
        seed_row.setSpacing(3)
        self.seed_input = QLineEdit("00000001")
        self.seed_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.seed_input.setMaxLength(10)
        self.seed_input.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self))
        self.seed_input.returnPressed.connect(self.generate_seed_board)
        seed_row.addWidget(self.seed_input, 1)
        self.copy_seed_button = QPushButton()
        self.copy_seed_button.setObjectName("GhostButton")
        self.copy_seed_button.setIcon(qta.icon("fa5s.copy", color=COLORS["blue"]))
        self.copy_seed_button.setIconSize(QSize(17, 17))
        self.copy_seed_button.setToolTip("复制种子号")
        self.copy_seed_button.clicked.connect(self.copy_seed)
        seed_row.addWidget(self.copy_seed_button)
        layout.addLayout(seed_row)

        difficulty_row = QHBoxLayout()
        difficulty_row.setSpacing(2)
        self.difficulty_group = QButtonGroup(self)
        self.difficulty_group.setExclusive(True)
        self.easy_button = QPushButton("简单")
        self.hard_button = QPushButton("困难")
        for button in (self.easy_button, self.hard_button):
            button.setObjectName("DifficultyButton")
            button.setCheckable(True)
            self.difficulty_group.addButton(button)
            difficulty_row.addWidget(button)
        self.easy_button.setChecked(True)
        self.easy_button.toggled.connect(self._refresh_difficulty_styles)
        self.hard_button.toggled.connect(self._refresh_difficulty_styles)
        self._refresh_difficulty_styles()
        layout.addLayout(difficulty_row)

        self.generate_button = QPushButton("生成地图")
        self.generate_button.setObjectName("GenerateButton")
        self.generate_button.setIcon(qta.icon("fa5s.play", color=COLORS["white"]))
        self.generate_button.setIconSize(QSize(14, 14))
        self.generate_button.setStyleSheet(self._primary_button_style(COLORS["orange"], COLORS["orange_hover"], 52, 17))
        self.generate_button.clicked.connect(self.generate_seed_board)
        layout.addWidget(self.generate_button)
        return panel

    def _build_manual_panel(self) -> QWidget:
        panel = ChamferPanel(chamfer=14)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        header = QHBoxLayout()
        left_balance = QWidget()
        left_balance.setFixedSize(28, 28)
        left_balance.setStyleSheet("background-color: transparent;")
        header.addWidget(left_balance)
        header.addStretch(1)
        self.manual_title = QLabel("手动标记")
        self.manual_title.setObjectName("SectionTitle")
        self.manual_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.manual_title)
        header.addStretch(1)
        self.manual_help_button = QPushButton()
        self.manual_help_button.setObjectName("GhostButton")
        self.manual_help_button.setIcon(qta.icon("fa5s.question-circle", color=COLORS["faint"]))
        self.manual_help_button.setToolTip("选择状态后，左键点击右侧棋盘同步游戏进度")
        self.manual_help_button.setFixedSize(28, 28)
        header.addWidget(self.manual_help_button)
        layout.addLayout(header)

        states = QHBoxLayout()
        states.setSpacing(8)
        states.addStretch(1)
        self.state_group = QButtonGroup(self)
        self.state_group.setExclusive(True)
        self.state_buttons: dict[CellVisualType, StateButton] = {}
        for state, label in (
            (CellVisualType.HIDDEN, "未知"),
            (CellVisualType.BLUE, "蓝色"),
            (CellVisualType.BLACK, "排除"),
        ):
            button = StateButton(state, label)
            button.clicked.connect(lambda checked=False, selected=state: self._select_state(selected))
            self.state_group.addButton(button)
            self.state_buttons[state] = button
            states.addWidget(button)
            if state is CellVisualType.HIDDEN:
                button.setChecked(True)
        states.addStretch(1)
        layout.addLayout(states)

        return panel

    def _build_step_panel(self) -> QWidget:
        panel = ChamferPanel(chamfer=13, border=COLORS["blue"])
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)

        heading = QHBoxLayout()
        self.step_title = QLabel("下一步")
        self.step_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {COLORS['text']};")
        heading.addWidget(self.step_title)
        heading.addStretch(1)
        self.step_coord = QLabel("等待计算")
        self.step_coord.setStyleSheet(
            f"font-family: Bahnschrift; font-size: 14px; font-weight: 700; color: {COLORS['blue']};"
        )
        heading.addWidget(self.step_coord)
        layout.addLayout(heading)

        self.step_reason = InteractiveReasonBrowser()
        self.step_reason.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.step_reason.setMinimumHeight(300)
        self.step_reason.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.step_reason.setFrameShape(QFrame.Shape.NoFrame)
        self.step_reason.setViewportMargins(0, 0, 0, 0)
        self.step_reason.document().setDocumentMargin(2)
        self.step_reason.setStyleSheet(
            f"QTextBrowser {{ font-size: 14px; color: {COLORS['text']}; background: {COLORS['panel']}; "
            "border: none; padding: 0 2px 0 0; }}"
        )
        reason_font = QFont("Microsoft YaHei UI")
        reason_font.setPixelSize(14)
        self.step_reason.setFont(reason_font)
        self.step_reason.document().setDefaultFont(reason_font)
        self.step_reason.reference_focus_changed.connect(self._on_reason_reference_focus)
        self.step_reason.pin_state_changed.connect(self._schedule_autosave)
        self.step_reason.verticalScrollBar().valueChanged.connect(
            lambda _value: self._schedule_autosave()
        )
        layout.addWidget(self.step_reason, 1)

        self.step_action_bar = QWidget(panel)
        self.step_action_bar.setObjectName("StepActionBar")
        self.step_action_bar.setFixedHeight(46)
        self.step_action_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.step_action_bar.setStyleSheet(f"QWidget#StepActionBar {{ background: {COLORS['panel']}; }}")
        actions = QHBoxLayout(self.step_action_bar)
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(6)
        self.next_button = QPushButton("计算下一步")
        self.next_button.setObjectName("NextButton")
        self.next_button.setIcon(qta.icon("fa5s.chevron-right", color=COLORS["white"]))
        self.next_button.setStyleSheet(self._primary_button_style(COLORS["blue"], COLORS["blue_hover"], 38, 14))
        self.next_button.setFixedHeight(38)
        self.next_button.clicked.connect(self.solve_next_step)
        actions.addWidget(self.next_button, 1)

        self.apply_button = QPushButton()
        self.apply_button.setObjectName("NextButton")
        self.apply_button.setIcon(qta.icon("fa5s.check", color=COLORS["white"]))
        self.apply_button.setIconSize(QSize(16, 16))
        self.apply_button.setStyleSheet(self._primary_button_style(COLORS["blue"], COLORS["blue_hover"], 38, 14))
        self.apply_button.setAccessibleName("应用当前建议")
        self.apply_button.setAccessibleDescription("把当前建议直接应用到本地盘面")
        self.apply_button.setFixedSize(42, 38)
        self.apply_button.clicked.connect(self.apply_current_move)
        self.apply_button.setEnabled(False)
        actions.addWidget(self.apply_button)

        self.simulation_button = QPushButton()
        self.simulation_button.setObjectName("SimulationButton")
        self.simulation_button.setIcon(
            qta.icon("fa5s.flask", color=COLORS["orange_hover"])
        )
        self.simulation_button.setIconSize(QSize(16, 16))
        self.simulation_button.setAccessibleName("开始模拟推演")
        self.simulation_button.setAccessibleDescription(
            "固定当前真实盘面，在不揭示新信息的隔离分支中尝试填块"
        )
        self.simulation_button.setToolTip("开始模拟推演")
        self.simulation_button.setFixedSize(42, 38)
        self.simulation_button.setStyleSheet(
            f"QPushButton {{ color: {COLORS['orange_hover']}; "
            f"background: {COLORS['orange_soft']}; border: 1px solid {COLORS['orange']}; "
            "font-weight: 700; }} "
            f"QPushButton:hover {{ background: {COLORS['white']}; }} "
            "QPushButton:disabled { color: #B9A98D; background: #F3EEE5; border-color: #DDD2C0; }"
        )
        actions.addWidget(self.simulation_button)
        layout.addWidget(self.step_action_bar)
        return panel

    @staticmethod
    def _primary_button_style(color: str, hover: str, height: int, font_size: int) -> str:
        return f"""
        QPushButton {{
            color: {COLORS['white']};
            background-color: {color};
            border: none;
            border-radius: 4px;
            min-height: {height}px;
            font-size: {font_size}px;
            font-weight: 700;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {hover}; }}
        QPushButton:disabled {{
            color: rgba(255,255,255,145);
            background-color: #A8D9EB;
        }}
        """

    def _refresh_difficulty_styles(self) -> None:
        for button in (self.easy_button, self.hard_button):
            if button.isChecked():
                button.setStyleSheet(
                    f"QPushButton {{ color: {COLORS['white']}; background-color: {COLORS['blue']}; "
                    f"border: 1px solid {COLORS['blue']}; min-height: 34px; font-weight: 700; }}"
                )
            else:
                button.setStyleSheet(
                    f"QPushButton {{ color: {COLORS['text']}; background-color: {COLORS['panel_alt']}; "
                    f"border: 1px solid {COLORS['border']}; min-height: 34px; font-weight: 600; }} "
                    f"QPushButton:hover {{ background-color: {COLORS['white']}; }}"
                )

    def _select_state(self, state: CellVisualType) -> None:
        self.selected_state = state

    def _active_board(self) -> Board:
        if self.simulation_session is not None:
            return self.simulation_session.board
        return self.session.board

    def _apply_mouse_control_preference(self) -> None:
        enabled = self.preferences.original_mouse_controls_enabled
        board_interaction_enabled = self._has_active_board and not self._guide_visible
        simulation = self.simulation_session is not None
        for button in self.state_buttons.values():
            button.setEnabled(board_interaction_enabled and not enabled)
            button.setToolTip(
                "模拟推演：左键排除，右键蓝色；不会揭示新信息"
                if enabled and simulation
                else "原版鼠标操作已开启：左键排除，右键蓝色"
                if enabled
                else f"模拟标记为{button.label}；不会揭示新信息"
                if simulation
                else f"点击棋盘后设为{button.label}"
            )
        if simulation and enabled:
            help_text = "模拟推演：左键排除，右键蓝色；所有标记都不会揭示新信息"
        elif simulation:
            help_text = "模拟推演：选择状态后点击棋盘；所有标记都不会揭示新信息"
        elif enabled:
            help_text = "原版鼠标操作已开启：左键排除，右键蓝色；再次同键点击恢复未知"
        else:
            help_text = "选择状态后，左键点击右侧棋盘同步游戏进度"
        self.manual_help_button.setToolTip(help_text)
        self.manual_help_button.setAccessibleDescription(help_text)
        self.manual_help_button.setEnabled(board_interaction_enabled)

    def _load_board(
        self,
        board: Board,
        *,
        mode_text: str,
        verified: bool = False,
        active: bool = True,
        close_guide: bool = True,
    ) -> None:
        self._has_active_board = active
        self.stage.board_view.set_board(board)
        self.stage.set_mode(mode_text, verified=verified)
        self.current_move = None
        self._update_step_card(None)
        self._update_counts()
        if close_guide:
            self.hide_onboarding()
        else:
            self._refresh_board_interactions()

    def show_onboarding(self) -> None:
        self._guide_visible = True
        self.onboarding_overlay.setGeometry(self.root.rect())
        self.onboarding_overlay.show()
        self.onboarding_overlay.raise_()
        self.guide_close_button.show()
        self._position_guide_close_button()
        self.guide_close_button.raise_()
        self._refresh_board_interactions()

    def hide_onboarding(self) -> None:
        self._guide_visible = False
        self.onboarding_overlay.hide()
        self.guide_close_button.hide()
        self._refresh_board_interactions()

    def _position_guide_close_button(self) -> None:
        margin = 24
        self.guide_close_button.move(
            self.root.width() - self.guide_close_button.width() - margin,
            margin,
        )

    def _refresh_board_interactions(self) -> None:
        enabled = self._has_active_board and not self._guide_visible
        simulation = self.simulation_session is not None
        self.stage.board_view.setEnabled(enabled)
        for button in (
            self.stage.undo_button,
            self.stage.redo_button,
            self.stage.reset_button,
            self.stage.zoom_out_button,
            self.stage.zoom_in_button,
            self.stage.fit_button,
        ):
            button.setEnabled(enabled)
        self.next_button.setEnabled(enabled and not self._solve_busy and not simulation)
        self.apply_button.setEnabled(
            enabled
            and not self._solve_busy
            and not simulation
            and self.current_move is not None
        )
        self.step_action_bar.setVisible(True)
        self.next_button.setVisible(not simulation)
        self.apply_button.setVisible(not simulation)
        generation_idle = self._generation_thread is None
        for widget in (
            self.seed_input,
            self.easy_button,
            self.hard_button,
            self.copy_seed_button,
            self.generate_button,
        ):
            widget.setEnabled(not simulation and generation_idle)
        self.stage.settings_button.setEnabled(not simulation and generation_idle)
        self.simulation_button.setEnabled(
            enabled and not self._solve_busy and generation_idle
        )
        self.stage.counter_badge.setVisible(enabled)
        self._apply_mouse_control_preference()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if hasattr(self, "onboarding_overlay"):
            self.onboarding_overlay.setGeometry(self.root.rect())
            self._position_guide_close_button()

    def toggle_simulation(self) -> None:
        if self.simulation_session is None:
            self.start_simulation()
        else:
            self.end_simulation()

    def start_simulation(self) -> None:
        if (
            not self._has_active_board
            or self._guide_visible
            or self._generation_thread is not None
            or self._solve_thread is not None
        ):
            return
        if not self.session.board.hidden_cells():
            self.stage.show_toast("当前盘面没有可用于模拟推演的未知格")
            return
        self._autosave_timer.stop()
        self._save_autosave_now()
        self.simulation_session = SimulationSession(self.session.board)
        self._simulation_origin_mode = (
            self.stage.mode_text,
            self.stage.mode_verified,
        )
        self._simulation_revision += 1
        self._simulation_check_pending = False
        self.stage.board_view.set_board(self.simulation_session.board)
        self.stage.board_view.set_simulation_state(True)
        self.stage.set_mode(
            "正在模拟推演 · 所有填块都不会揭示新信息",
            simulation=True,
        )
        self._update_simulation_button(True)
        self._set_simulation_status(checking=True)
        self._update_counts()
        self._refresh_board_interactions()
        self._schedule_simulation_conflict_check()
        self.stage.show_toast("已固定当前盘面；模拟标记不会写入真实局面")

    def end_simulation(self, *, show_toast: bool = True) -> None:
        if self.simulation_session is None:
            return
        if (
            self._simulation_conflict_thread is not None
            and self._simulation_conflict_thread.isRunning()
        ):
            self._simulation_conflict_thread.requestInterruption()
        self.simulation_session = None
        self._simulation_revision += 1
        self._simulation_check_pending = False
        mode_text, verified = self._simulation_origin_mode or ("当前局面", True)
        self._simulation_origin_mode = None
        self.stage.board_view.set_board(self.session.board)
        self.stage.board_view.set_simulation_state(False)
        self.stage.set_mode(mode_text, verified=verified)
        self._update_simulation_button(False)
        self.stage.board_view.set_target(self.current_move)
        self._update_step_card(self.current_move)
        self._update_counts()
        self._refresh_board_interactions()
        if show_toast:
            self.stage.show_toast("已丢弃模拟分支并返回推演开始时的真实局面")

    def _update_simulation_button(self, active: bool) -> None:
        self.manual_title.setText("模拟标记" if active else "手动标记")
        self.step_panel.border = QColor(COLORS["orange"] if active else COLORS["blue"])
        self.step_panel.update()
        control_labels = (
            ("撤销模拟修改", "重做模拟修改", "重置本次模拟推演")
            if active
            else ("撤销", "重做", "恢复初始盘面")
        )
        for button, label in zip(
            (
                self.stage.undo_button,
                self.stage.redo_button,
                self.stage.reset_button,
            ),
            control_labels,
        ):
            button.setToolTip(label)
            button.setAccessibleName(label)
        if active:
            self.simulation_button.setText("结束模拟推演")
            self.simulation_button.setIcon(
                qta.icon("fa5s.sign-out-alt", color=COLORS["white"])
            )
            self.simulation_button.setAccessibleName("结束模拟推演")
            self.simulation_button.setAccessibleDescription(
                "丢弃全部模拟标记并返回推演开始时的真实局面"
            )
            self.simulation_button.setToolTip("")
            self.simulation_button.setMinimumWidth(0)
            self.simulation_button.setMaximumWidth(16_777_215)
            self.simulation_button.setFixedHeight(38)
            self.simulation_button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            self.simulation_button.setStyleSheet(
                self._primary_button_style(
                    COLORS["orange"], COLORS["orange_hover"], 34, 13
                )
            )
            return
        self.simulation_button.setText("开始模拟推演")
        self.simulation_button.setIcon(
            qta.icon("fa5s.flask", color=COLORS["orange_hover"])
        )
        self.simulation_button.setAccessibleName("开始模拟推演")
        self.simulation_button.setAccessibleDescription(
            "固定当前真实盘面，在不揭示新信息的隔离分支中尝试填块"
        )
        self.simulation_button.setToolTip("开始模拟推演")
        self.simulation_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.simulation_button.setFixedSize(42, 38)
        self.simulation_button.setStyleSheet(
            f"QPushButton {{ color: {COLORS['orange_hover']}; "
            f"background: {COLORS['orange_soft']}; border: 1px solid {COLORS['orange']}; "
            "font-weight: 700; }} "
            f"QPushButton:hover {{ background: {COLORS['white']}; }} "
            "QPushButton:disabled { color: #B9A98D; background: #F3EEE5; border-color: #DDD2C0; }"
        )

    def _simulation_changed(self) -> None:
        simulation = self.simulation_session
        if simulation is None:
            return
        self._simulation_revision += 1
        self.stage.board_view.set_simulation_state(
            True,
            changed_coords=simulation.changed_coords,
        )
        self._update_counts()
        self._set_simulation_status(checking=True)
        self._schedule_simulation_conflict_check()

    def _schedule_simulation_conflict_check(self) -> None:
        if self.simulation_session is None:
            return
        thread = self._simulation_conflict_thread
        if thread is not None and thread.isRunning():
            self._simulation_check_pending = True
            thread.requestInterruption()
            return
        self._simulation_check_pending = False
        simulation = self.simulation_session
        thread = SimulationConflictThread(
            deepcopy(simulation.initial_board),
            dict(simulation.assumed_states()),
            self._simulation_revision,
            self,
        )
        self._simulation_conflict_thread = thread
        thread.succeeded.connect(self._simulation_conflict_succeeded)
        thread.failed.connect(self._simulation_conflict_failed)
        thread.finished.connect(self._simulation_conflict_finished)
        thread.start()

    def _simulation_conflict_succeeded(self, report: object, revision: int) -> None:
        if self.simulation_session is None or revision != self._simulation_revision:
            return
        if report is not None and not isinstance(report, PublicConstraintConflict):
            self._simulation_conflict_failed("矛盾检查返回了无法识别的结果", revision)
            return
        self._set_simulation_status(report=report)

    def _simulation_conflict_failed(self, message: str, revision: int) -> None:
        if self.simulation_session is None or revision != self._simulation_revision:
            return
        self.stage.board_view.set_simulation_conflict(())
        self.step_title.setText("模拟推演")
        self.step_coord.setText("检查失败")
        self._set_step_reason(
            "矛盾检查没有得到确定结果，当前模拟填块不会被当作正确或错误。\n\n"
            f"原因：{message}"
        )

    def _simulation_conflict_finished(self) -> None:
        thread = self._simulation_conflict_thread
        self._simulation_conflict_thread = None
        if thread is not None:
            thread.deleteLater()
        if self.simulation_session is not None and self._simulation_check_pending:
            self._simulation_check_pending = False
            QTimer.singleShot(0, self._schedule_simulation_conflict_check)
        if self._close_requested:
            QTimer.singleShot(0, self.close)

    def _set_simulation_status(
        self,
        report: Optional[PublicConstraintConflict] = None,
        *,
        checking: bool = False,
    ) -> None:
        if self.simulation_session is None:
            return
        if checking:
            self.stage.board_view.set_simulation_conflict(())
            self.step_title.setText("模拟推演")
            self.step_coord.setText("检查中…")
            self._set_step_reason(
                "下一步推理已关闭。你可以手动尝试排除格或蓝格；"
                "应用只会检查这些假设是否与当前公开线索矛盾。"
            )
            return
        if report is None:
            self.stage.board_view.set_simulation_conflict(())
            self.step_title.setText("模拟推演")
            self.step_coord.setText("暂无矛盾")
            self._set_step_reason(
                "当前模拟填块仍能满足已公开的条件。\n\n"
                "这只表示暂未发现矛盾，不代表这些填块已经被证明正确。"
            )
            return
        self.stage.board_view.set_simulation_conflict(report.assumption_coords)
        if report.base_board_inconsistent:
            self.step_title.setText("起始盘面有矛盾")
            self.step_coord.setText("检查真实局面")
            heading = "进入推演前的公开盘面已经无法满足全部公开条件。"
        else:
            self.step_title.setText("发现模拟矛盾")
            self.step_coord.setText(f"{len(report.assumption_coords)} 个填块")
            coords = "、".join(str(coord) for coord in report.assumption_coords)
            heading = f"以下模拟填块共同导致公开条件无解：{coords}。"
        labels = list(report.constraint_labels)
        shown = labels[:6]
        constraints = "\n".join(f"- {label}" for label in shown)
        if len(labels) > len(shown):
            constraints += f"\n- 另有 {len(labels) - len(shown)} 条相关条件"
        self._set_step_reason(
            f"{heading}\n\n相关公开条件：\n{constraints}\n\n"
            "提示：高亮的是一组足以造成矛盾的假设。这不代表其中每一格都错；"
            "除非公开条件能单独证明，不能断言某一格就是实际错格。"
        )

    def _on_cell_activated(
        self,
        coord: Coord,
        button: Qt.MouseButton = Qt.MouseButton.LeftButton,
    ) -> None:
        if self.preferences.original_mouse_controls_enabled:
            if button == Qt.MouseButton.LeftButton:
                requested_state = CellVisualType.BLACK
            elif button == Qt.MouseButton.RightButton:
                requested_state = CellVisualType.BLUE
            else:
                return
            cell = self._active_board().get_cell(coord)
            if cell is not None and cell.visual_type is requested_state:
                requested_state = CellVisualType.HIDDEN
        else:
            if button != Qt.MouseButton.LeftButton:
                return
            requested_state = self.selected_state
        self.stage.board_view.set_selected(coord)
        try:
            if self.simulation_session is not None:
                change = self.simulation_session.set_cell_state(coord, requested_state)
            else:
                change = self.session.set_cell_state(coord, requested_state)
        except BoardStateError as exc:
            self.stage.show_toast(str(exc), danger=True)
            return
        if change.before is change.after:
            return
        if self.simulation_session is not None:
            self.stage.board_view.sync_state()
            self._simulation_changed()
            return
        self._session_changed()
        self.current_move = None
        self.stage.board_view.set_target(None)
        self.stage.board_view.sync_state()
        self._update_counts()
        self._update_step_card(None)

    def solve_next_step(self) -> None:
        if (
            self.simulation_session is not None
            or self._solve_thread is not None
            or not self._has_active_board
        ):
            return
        revision = self._session_revision
        thread = SolveStepThread(deepcopy(self.session.board), revision, self)
        self._solve_thread = thread
        thread.succeeded.connect(self._solve_succeeded)
        thread.failed.connect(self._solve_failed)
        thread.finished.connect(self._solve_finished)
        self._set_solve_busy(True)
        thread.start()

    def _solve_succeeded(self, move: object, revision: int) -> None:
        if revision != self._session_revision or not self._has_active_board:
            self.stage.show_toast("盘面已变化，已忽略旧的推理结果")
            return
        if move is not None and not isinstance(move, SuggestedMove):
            self.stage.show_toast("求解器返回了无法识别的结果", danger=True)
            return
        self.current_move = move
        self.stage.board_view.set_target(move)
        self._update_step_card(move)
        if move is None:
            self.stage.show_toast("当前公开信息无法推出新的必然步骤")
        else:
            action = "标记蓝色" if move.action is MoveAction.MARK_BLUE else "标记排除"
            self.stage.show_toast(f"已定位：{move.coord} · {action}")
        self._schedule_autosave()

    def _solve_failed(self, message: str, revision: int) -> None:
        if revision != self._session_revision:
            return
        self.stage.show_toast(f"求解失败：{message}", danger=True, duration_ms=5200)

    def _solve_finished(self) -> None:
        thread = self._solve_thread
        self._solve_thread = None
        self._set_solve_busy(False)
        if thread is not None:
            thread.deleteLater()
        if self._close_requested:
            QTimer.singleShot(0, self.close)

    def _set_solve_busy(self, busy: bool) -> None:
        self._solve_busy = busy
        self.next_button.setText("正在推理…" if busy else "计算下一步")
        self.next_button.setIcon(
            qta.icon(
                "fa5s.circle-notch" if busy else "fa5s.chevron-right",
                color=COLORS["white"],
            )
        )
        self._refresh_board_interactions()

    def apply_current_move(self) -> None:
        if self.simulation_session is not None or self.current_move is None:
            return
        move = self.current_move
        try:
            self.session.apply_suggested_move(move)
        except BoardStateError as exc:
            self.stage.show_toast(str(exc), danger=True)
            return
        self._session_changed()
        self.current_move = None
        self.stage.board_view.set_target(None)
        self.stage.board_view.sync_state()
        self._update_counts()
        self._update_step_card(None)

    def undo(self) -> None:
        if self.simulation_session is not None:
            change = self.simulation_session.undo()
            if change is None:
                self.stage.show_toast("没有可以撤销的模拟修改")
                return
            self.stage.board_view.sync_state()
            self._simulation_changed()
            return
        change = self.session.undo()
        if change is None:
            self.stage.show_toast("没有可以撤销的手动修改")
            return
        self._session_changed()
        self.current_move = None
        self.stage.board_view.set_target(None)
        self.stage.board_view.sync_state()
        self._update_counts()
        self._update_step_card(None)

    def redo(self) -> None:
        if self.simulation_session is not None:
            change = self.simulation_session.redo()
            if change is None:
                self.stage.show_toast("没有可以重做的模拟修改")
                return
            self.stage.board_view.sync_state()
            self._simulation_changed()
            return
        change = self.session.redo()
        if change is None:
            self.stage.show_toast("没有可以重做的修改")
            return
        self._session_changed()
        self.current_move = None
        self.stage.board_view.set_target(None)
        self.stage.board_view.sync_state()
        self._update_counts()
        self._update_step_card(None)

    def reset_board(self) -> None:
        if self.simulation_session is not None:
            self.simulation_session.reset()
            self.stage.board_view.set_board(self.simulation_session.board)
            self._simulation_changed()
            self.stage.show_toast("已重置到本次模拟推演的起始局面")
            return
        self.session.reset()
        self._session_changed()
        self.current_move = None
        self.stage.board_view.set_board(self.session.board)
        self._update_counts()
        self._update_step_card(None)
        self.stage.show_toast("已恢复到初始盘面")

    def generate_seed_board(self) -> None:
        if self.simulation_session is not None:
            self.stage.show_toast("请先结束模拟推演，再生成新的地图")
            return
        if self._generation_thread is not None:
            return
        difficulty = Difficulty.EASY if self.easy_button.isChecked() else Difficulty.HARD
        try:
            request = SeedRequest.parse(self.seed_input.text(), difficulty.value)
        except ValueError as exc:
            self.stage.show_toast(str(exc), danger=True)
            self.seed_input.setFocus()
            return

        if not self.seed_generators.fidelity_for(difficulty).is_exact:
            label = "简单" if difficulty is Difficulty.EASY else "困难"
            self.stage.show_toast(
                f"{label}生成器正在做同种子逐格验证，当前不会输出近似地图",
                danger=True,
                duration_ms=4600,
            )
            self.stage.set_mode(f"种子 {self.seed_input.text()} · {label} · 生成器未验证")
            return

        label = "简单" if difficulty is Difficulty.EASY else "困难"
        self._set_generation_busy(True)
        self.stage.set_mode(f"种子 {request.seed:08d} · {label} · 正在离线生成…")
        self.stage.show_toast("正在本地复刻原版地图，无需启动游戏…", duration_ms=1800)
        thread = SeedGenerationThread(self.seed_generators, request, self)
        self._generation_thread = thread
        thread.succeeded.connect(self._generation_succeeded)
        thread.failed.connect(self._generation_failed)
        thread.finished.connect(self._generation_finished)
        thread.start()

    def _generation_succeeded(self, puzzle) -> None:  # type: ignore[no-untyped-def]
        request = puzzle.request
        self.current_seed = request
        self.session = InteractivePuzzleSession(
            puzzle.public_board,
            self.solver,
            private_reveals=puzzle.private_reveals,
        )
        self._session_changed()
        self._load_board(
            self.session.board,
            mode_text=(
                f"种子 {request.seed:08d} · {request.difficulty.label} · "
                f"{'本地缓存' if puzzle.cache_hit else '离线精确生成'}"
            ),
            verified=True,
        )
        if puzzle.cache_hit:
            source = "已从本地缓存加载"
        elif puzzle.cache_saved:
            source = "生成完成并已缓存"
        else:
            source = "生成完成"
        self.stage.show_toast(
            f"{source}：{len(self.session.board.cells)} 个格子，"
            f"{len(self.session.board.row_clues)} 条行线索"
        )
        self._save_autosave_now()

    def _generation_failed(self, message: str) -> None:
        difficulty = Difficulty.EASY if self.easy_button.isChecked() else Difficulty.HARD
        label = "简单" if difficulty is Difficulty.EASY else "困难"
        self.stage.set_mode(f"种子 {self.seed_input.text()} · {label} · 生成失败，可重试")
        self.stage.show_toast(f"生成失败：{message}", danger=True, duration_ms=6000)

    def _generation_finished(self) -> None:
        thread = self._generation_thread
        self._generation_thread = None
        self._set_generation_busy(False)
        if thread is not None:
            thread.deleteLater()

    def _set_generation_busy(self, busy: bool) -> None:
        self.seed_input.setEnabled(not busy)
        self.easy_button.setEnabled(not busy)
        self.hard_button.setEnabled(not busy)
        self.copy_seed_button.setEnabled(not busy)
        self.generate_button.setEnabled(not busy)
        self.stage.settings_button.setEnabled(not busy)
        self.generate_button.setText("离线生成中…" if busy else "生成地图")
        self.generate_button.setIcon(
            qta.icon("fa5s.circle-notch" if busy else "fa5s.play", color=COLORS["white"])
        )

    def import_screenshot(self) -> None:
        if not SCREENSHOT_IMPORT_ENABLED:
            self.stage.show_toast(
                "截图识别功能暂时关闭，请先使用种子生成并手动同步进度。",
                duration_ms=4200,
            )
            return
        from .detector import DetectionError, HexImageDetector

        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 Hexcells Infinite 截图",
            "",
            "图片 (*.png *.jpg *.jpeg *.bmp)",
        )
        if not path:
            return
        self.stage.show_toast("正在识别截图…", duration_ms=1500)
        QApplication.processEvents()
        if self._detector is None:
            package_root = Path(__file__).resolve().parent
            self._detector = HexImageDetector(str(package_root / "assets"))
        try:
            board = self._detector.detect_board(path)
        except (DetectionError, OSError) as exc:
            self.stage.show_toast(f"截图识别失败：{exc}", danger=True, duration_ms=4800)
            return
        self.session = InteractivePuzzleSession(board, self.solver)
        self.current_seed = None
        self._session_changed()
        self._load_board(board, mode_text=f"截图局面 · {Path(path).name}")
        self._save_autosave_now()

    def open_settings(self) -> None:
        if self.simulation_session is not None:
            self.stage.show_toast("请先结束模拟推演，再打开设置")
            return
        dialog = SettingsDialog(
            self.seed_generators.cache,
            self.preferences,
            self,
            session_store=self.session_store,
            has_active_session=self._has_active_board,
        )
        dialog.exec()
        self._apply_mouse_control_preference()
        if dialog.guide_requested:
            self.show_onboarding()
        elif dialog.save_progress_requested:
            self.save_progress_as()
        elif dialog.load_progress_requested:
            self.load_progress_from_file()
        elif dialog.clear_progress_requested:
            self.clear_current_progress()

    def save_progress_as(self) -> None:
        if self.simulation_session is not None:
            self.stage.show_toast("模拟分支不会保存；请先结束推演")
            return
        if not self._has_active_board:
            self.stage.show_toast("当前没有可保存的局面", danger=True)
            return
        default_name = (
            f"hex-{self.current_seed.difficulty.value}-{self.current_seed.seed:08d}{SESSION_FILE_SUFFIX}"
            if self.current_seed is not None
            else f"hex-progress{SESSION_FILE_SUFFIX}"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存当前局面",
            str(self.session_store.directory / default_name),
            f"HexInfinite 局面 (*{SESSION_FILE_SUFFIX});;JSON 文件 (*.json)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += SESSION_FILE_SUFFIX
        try:
            self.session_store.save(
                path,
                self.session,
                self.current_seed,
                self.current_move,
                self.step_reason.verticalScrollBar().value(),
                self._pinned_reason_reference_id(),
            )
        except SessionStoreError as exc:
            self.stage.show_toast(str(exc), danger=True, duration_ms=5200)
            return
        self.stage.show_toast(f"局面已保存：{Path(path).name}")

    def load_progress_from_file(self) -> None:
        if self.simulation_session is not None:
            self.stage.show_toast("请先结束模拟推演，再载入其他局面")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "载入局面",
            str(self.session_store.directory),
            f"HexInfinite 局面 (*{SESSION_FILE_SUFFIX} *.json)",
        )
        if not path:
            return
        try:
            stored = self.session_store.load(path, self.solver)
        except SessionStoreError as exc:
            self.stage.show_toast(str(exc), danger=True, duration_ms=6000)
            return
        self._apply_stored_session(stored, source="手动存档")
        self._save_autosave_now()

    def clear_current_progress(self) -> None:
        if self.simulation_session is not None:
            self.stage.show_toast("请先结束模拟推演，再清除进度")
            return
        confirmed = ask_confirmation(
            self,
            title="清除当前进度",
            message="确定清除当前局面和最近一次自动保存吗？",
            detail="手动另存的 .hexsave 局面文件不会被删除。",
            accept_text="清除进度",
            reject_text="取消",
            destructive=True,
            default_accept=False,
        )
        if not confirmed:
            return
        try:
            self.session_store.clear_autosave()
        except SessionStoreError as exc:
            self.stage.show_toast(str(exc), danger=True)
            return
        self._autosave_timer.stop()
        self.session = InteractivePuzzleSession(build_empty_board(), self.solver)
        self.current_seed = None
        self._session_changed(schedule_autosave=False)
        self._load_board(
            self.session.board,
            mode_text="快速上手 · 尚未生成地图",
            active=False,
            close_guide=False,
        )
        self.show_onboarding()
        self.stage.show_toast("当前进度已清除")

    def _restore_autosave_on_startup(self) -> None:
        if (
            not self.preferences.restore_last_session_enabled
            or not self.session_store.has_autosave()
        ):
            return
        confirmed = ask_confirmation(
            self,
            title="发现未完成的局面",
            message="检测到上一次自动保存的局面，要从这里继续吗？",
            detail=(
                "继续后会恢复盘面、撤销/重做记录和当前推理位置。\n"
                "放弃则删除这份自动保存，并显示使用说明。"
            ),
            accept_text="继续局面",
            reject_text="放弃并查看说明",
            default_accept=True,
        )
        if not confirmed:
            try:
                self.session_store.clear_autosave()
            except SessionStoreError:
                pass
            return
        try:
            stored = self.session_store.load_autosave(self.solver)
        except SessionStoreError as exc:
            try:
                self.session_store.clear_autosave()
            except SessionStoreError:
                pass
            self.stage.show_toast(
                f"自动保存无法恢复，已安全忽略：{exc}",
                danger=True,
                duration_ms=6500,
            )
            return
        self._apply_stored_session(stored, source="自动恢复")
        self.stage.show_toast("已恢复上一次局面")

    def _apply_stored_session(self, stored: StoredSession, *, source: str) -> None:
        self.session = stored.session
        self.current_seed = stored.request
        self.current_move = stored.current_move
        self._session_changed(schedule_autosave=False, clear_move=False)
        if stored.request is not None:
            self.seed_input.setText(f"{stored.request.seed:08d}")
            if stored.request.difficulty is Difficulty.EASY:
                self.easy_button.setChecked(True)
            else:
                self.hard_button.setChecked(True)
            mode = (
                f"种子 {stored.request.seed:08d} · "
                f"{stored.request.difficulty.label} · {source}"
            )
        else:
            mode = f"已载入局面 · {source}"
        self._load_board(self.session.board, mode_text=mode, verified=True)
        self.current_move = stored.current_move
        self.stage.board_view.set_target(self.current_move)
        self._update_step_card(self.current_move)
        self.step_reason.restore_view_state(
            stored.pinned_reference_id,
            stored.reason_scroll_value,
        )

    def _session_changed(
        self,
        *,
        schedule_autosave: bool = True,
        clear_move: bool = True,
    ) -> None:
        self._session_revision += 1
        if self._solve_thread is not None and self._solve_thread.isRunning():
            self._solve_thread.requestInterruption()
        if clear_move:
            self.current_move = None
        if schedule_autosave:
            self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if self._has_active_board and self.simulation_session is None:
            self._autosave_timer.start(250)

    def _save_autosave_now(self) -> None:
        if not self._has_active_board or self.simulation_session is not None:
            return
        try:
            self.session_store.save_autosave(
                self.session,
                self.current_seed,
                self.current_move,
                self.step_reason.verticalScrollBar().value(),
                self._pinned_reason_reference_id(),
            )
            self._autosave_error_reported = False
        except SessionStoreError as exc:
            if not self._autosave_error_reported:
                self.stage.show_toast(str(exc), danger=True, duration_ms=5200)
                self._autosave_error_reported = True

    def _pinned_reason_reference_id(self) -> Optional[str]:
        reference = self.step_reason.pinned_reference
        return reference.reference_id if reference is not None else None

    def copy_seed(self) -> None:
        QApplication.clipboard().setText(self.seed_input.text())
        self.stage.show_toast("种子号已复制")

    def _update_step_card(self, move: Optional[SuggestedMove]) -> None:
        if move is None:
            self.step_title.setText("下一步")
            self.step_coord.setText("等待计算")
            self._set_step_reason("手动同步到卡住的位置后，获取一个必然成立的步骤。")
            self.apply_button.setEnabled(False)
            return
        action = "标记蓝色" if move.action is MoveAction.MARK_BLUE else "标记排除"
        self.step_title.setText(action)
        self.step_coord.setText(str(move.coord))
        self._set_step_reason(move.reason)
        self.apply_button.setEnabled(self._has_active_board and not self._guide_visible)

    def _set_step_reason(self, text: str) -> None:
        self.step_reason.set_reason(text, self._active_board())
        document = self.step_reason.document()
        root_frame = document.rootFrame()
        frame_format = root_frame.frameFormat()
        frame_format.setBottomMargin(STEP_REASON_BOTTOM_SAFE_MARGIN)
        root_frame.setFrameFormat(frame_format)
        self.step_reason.verticalScrollBar().setValue(0)

    def _on_reason_reference_focus(
        self,
        reference: Optional[ReasonReference],
        pinned: bool,
    ) -> None:
        self.stage.board_view.set_reason_reference(reference, pinned=pinned)

    def _update_counts(self) -> None:
        board = self._active_board()
        remaining = board.remaining_blue
        if remaining is None:
            remaining = len(board.hidden_cells())
        self.stage.counter_badge.set_value(
            remaining,
            caption="模拟剩余" if self.simulation_session is not None else "剩余",
        )

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._generation_thread is not None and self._generation_thread.isRunning():
            self.stage.show_toast("离线地图仍在生成，请完成后再关闭窗口。", danger=True)
            event.ignore()
            return
        if self._solve_thread is not None and self._solve_thread.isRunning():
            self._close_requested = True
            self._solve_thread.requestInterruption()
            self.stage.show_toast("正在安全结束本次推理，完成后会自动关闭…")
            event.ignore()
            return
        if (
            self._simulation_conflict_thread is not None
            and self._simulation_conflict_thread.isRunning()
        ):
            self._close_requested = True
            self._simulation_conflict_thread.requestInterruption()
            self.stage.show_toast("正在安全结束模拟矛盾检查，完成后会自动关闭…")
            event.ignore()
            return
        if self.simulation_session is not None:
            self.end_simulation(show_toast=False)
        self._autosave_timer.stop()
        self._save_autosave_now()
        super().closeEvent(event)


def run_app() -> None:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("HexInfinite 种子求解器")
    app.setOrganizationName("HexInfinite Solver")
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    preferences = AppPreferences()
    window = MainWindow(preferences=preferences, restore_on_startup=True)
    show_window_for_startup(window, preferences.startup_window_mode)
    app.exec()
