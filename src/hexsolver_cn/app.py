from __future__ import annotations

import os
import sys
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import qtawesome as qta
from PySide6.QtCore import QPointF, QRegularExpression, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .board_view import HexBoardView
from .demo_board import build_demo_board
from .detector import DetectionError, HexImageDetector
from .models import Board, CellVisualType, Coord, MoveAction, SuggestedMove
from .original_bridge import build_default_seed_registry
from .seed_workflow import Difficulty, SeedGeneratorRegistry, SeedRequest
from .session import BoardStateError, InteractivePuzzleSession, StateChange
from .solver import HexReasoningSolver, SolverError
from .theme import COLORS, app_stylesheet
from .widgets import ChamferPanel, HexCounterBadge, StateButton


SCREENSHOT_IMPORT_ENABLED = False


@dataclass(frozen=True)
class HistoryEntry:
    action: str
    coord: Optional[Coord]
    state_change: bool = False
    initial: bool = False


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


class BoardStage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.board_view = HexBoardView(self)
        self.counter_badge = HexCounterBadge(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.board_view)

        self.mode_chip = QLabel("界面演示盘 · 非种子生成结果", self)
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
        self.reset_button = self._tool_button("fa5s.sync-alt", "恢复初始盘面")
        self.zoom_out_button = self._tool_button("fa5s.search-minus", "缩小")
        self.zoom_in_button = self._tool_button("fa5s.search-plus", "放大")
        self.fit_button = self._tool_button("fa5s.expand", "适合窗口")
        for button in (
            self.import_button,
            self.undo_button,
            self.reset_button,
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_button,
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
        return button

    def set_mode(self, text: str, *, verified: bool = False) -> None:
        self.mode_chip.setText(text)
        self.mode_chip.setStyleSheet(
            f"background: rgba(255,255,255,225); color: {COLORS['blue_hover'] if verified else COLORS['muted']}; "
            f"border: 1px solid {COLORS['blue'] if verified else COLORS['border']}; "
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
    def __init__(self, seed_generators: SeedGeneratorRegistry | None = None) -> None:
        super().__init__()
        self.setWindowTitle("HexInfinite 种子求解器")
        self.setMinimumSize(1120, 760)
        self.resize(1440, 1024)
        self.setWindowIcon(qta.icon("mdi6.hexagon", color=COLORS["orange"]))

        self.solver = HexReasoningSolver()
        self.seed_generators = seed_generators or build_default_seed_registry()
        self.session = InteractivePuzzleSession(build_demo_board(), self.solver)
        self.current_move: Optional[SuggestedMove] = None
        self.current_seed: Optional[SeedRequest] = None
        self.selected_state = CellVisualType.HIDDEN
        self.history: list[HistoryEntry] = []
        self._detector: Optional[HexImageDetector] = None
        self._generation_thread: Optional[SeedGenerationThread] = None

        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
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
        self.stage.reset_button.clicked.connect(self.reset_board)
        self.stage.zoom_in_button.clicked.connect(self.stage.board_view.zoom_in)
        self.stage.zoom_out_button.clicked.connect(self.stage.board_view.zoom_out)
        self.stage.fit_button.clicked.connect(self.stage.board_view.fit_board)
        self.stage.import_button.clicked.connect(self.import_screenshot)

        self._load_board(self.session.board, mode_text="界面演示盘 · 非种子生成结果")
        self._populate_initial_history()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(300)
        sidebar.setStyleSheet(f"background: {COLORS['background']};")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(15, 18, 15, 14)
        layout.setSpacing(9)

        layout.addWidget(self._build_seed_panel())
        layout.addWidget(self._build_stats_panel())
        layout.addWidget(self._build_manual_panel())
        layout.addWidget(self._build_history_panel(), 1)
        layout.addWidget(self._build_step_panel())
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

    def _build_stats_panel(self) -> QWidget:
        panel = ChamferPanel(chamfer=14)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(16, 10, 16, 11)
        layout.setSpacing(0)

        remaining_box = QVBoxLayout()
        remaining_box.setSpacing(0)
        remaining_label = QLabel("剩余")
        remaining_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        remaining_label.setObjectName("MutedLabel")
        self.remaining_value = QLabel("0")
        self.remaining_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remaining_value.setStyleSheet(
            f"font-family: Bahnschrift; font-size: 29px; font-weight: 650; color: {COLORS['blue']};"
        )
        remaining_box.addWidget(remaining_label)
        remaining_box.addWidget(self.remaining_value)
        layout.addLayout(remaining_box, 1)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {COLORS['border']};")
        layout.addWidget(divider)

        error_box = QVBoxLayout()
        error_box.setSpacing(0)
        error_label = QLabel("冲突")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setObjectName("MutedLabel")
        self.error_value = QLabel("0")
        self.error_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_value.setStyleSheet(
            f"font-family: Bahnschrift; font-size: 29px; font-weight: 650; color: {COLORS['text']};"
        )
        error_box.addWidget(error_label)
        error_box.addWidget(self.error_value)
        layout.addLayout(error_box, 1)
        return panel

    def _build_manual_panel(self) -> QWidget:
        panel = ChamferPanel(chamfer=14)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(13, 13, 13, 10)
        layout.setSpacing(5)

        header = QHBoxLayout()
        left_balance = QWidget()
        left_balance.setFixedSize(28, 28)
        left_balance.setStyleSheet("background-color: transparent;")
        header.addWidget(left_balance)
        header.addStretch(1)
        title = QLabel("手动标记")
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(title)
        header.addStretch(1)
        help_button = QPushButton()
        help_button.setObjectName("GhostButton")
        help_button.setIcon(qta.icon("fa5s.question-circle", color=COLORS["faint"]))
        help_button.setToolTip("选择状态后，点击右侧棋盘同步游戏进度")
        help_button.setFixedSize(28, 28)
        header.addWidget(help_button)
        layout.addLayout(header)

        states = QHBoxLayout()
        states.setSpacing(5)
        self.state_group = QButtonGroup(self)
        self.state_group.setExclusive(True)
        for state, label in (
            (CellVisualType.HIDDEN, "未知"),
            (CellVisualType.BLUE, "蓝色"),
            (CellVisualType.BLACK, "排除"),
        ):
            button = StateButton(state, label)
            button.clicked.connect(lambda checked=False, selected=state: self._select_state(selected))
            self.state_group.addButton(button)
            states.addWidget(button)
            if state is CellVisualType.HIDDEN:
                button.setChecked(True)
        layout.addLayout(states)
        return panel

    def _build_history_panel(self) -> QWidget:
        panel = ChamferPanel(chamfer=14)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(13, 12, 13, 12)
        layout.setSpacing(6)

        title = QLabel("步骤历史")
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.history_list = QListWidget()
        self.history_list.setIconSize(QSize(30, 34))
        self.history_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_list.itemClicked.connect(self._history_item_clicked)
        self.history_list.currentRowChanged.connect(self._refresh_history_icons)
        layout.addWidget(self.history_list, 1)
        return panel

    def _build_step_panel(self) -> QWidget:
        panel = ChamferPanel(chamfer=13, border=COLORS["blue"])
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

        self.step_reason = QTextEdit()
        self.step_reason.setReadOnly(True)
        self.step_reason.setPlainText("手动同步到卡住的位置后，获取一个必然成立的步骤。")
        self.step_reason.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.step_reason.setMinimumHeight(156)
        self.step_reason.setMaximumHeight(228)
        self.step_reason.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.step_reason.document().setDocumentMargin(1)
        self.step_reason.setStyleSheet(
            f"QTextEdit {{ font-size: 12px; color: {COLORS['muted']}; background: transparent; "
            "border: none; padding: 0; }}"
        )
        layout.addWidget(self.step_reason)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.next_button = QPushButton("计算下一步")
        self.next_button.setObjectName("NextButton")
        self.next_button.setIcon(qta.icon("fa5s.chevron-right", color=COLORS["white"]))
        self.next_button.setStyleSheet(self._primary_button_style(COLORS["blue"], COLORS["blue_hover"], 38, 14))
        self.next_button.clicked.connect(self.solve_next_step)
        actions.addWidget(self.next_button, 1)

        self.apply_button = QPushButton()
        self.apply_button.setObjectName("NextButton")
        self.apply_button.setIcon(qta.icon("fa5s.check", color=COLORS["white"]))
        self.apply_button.setIconSize(QSize(16, 16))
        self.apply_button.setStyleSheet(self._primary_button_style(COLORS["blue"], COLORS["blue_hover"], 38, 14))
        self.apply_button.setToolTip("把建议应用到本地盘面")
        self.apply_button.setFixedWidth(42)
        self.apply_button.clicked.connect(self.apply_current_move)
        self.apply_button.setEnabled(False)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
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

    def _load_board(self, board: Board, *, mode_text: str, verified: bool = False) -> None:
        self.stage.board_view.set_board(board)
        self.stage.set_mode(mode_text, verified=verified)
        self.current_move = None
        self._update_step_card(None)
        self._update_counts()

    def _populate_initial_history(self) -> None:
        self.history.clear()
        self.history_list.clear()
        known = sorted(
            (cell.coord for cell in self.session.board.known_blue_cells() if not cell.clue_text),
            key=lambda coord: (coord[1], coord[0]),
        )
        for coord in known[-5:]:
            self._append_history(HistoryEntry("初始蓝色", coord, initial=True), select=False)
        if self.history_list.count():
            self.history_list.setCurrentRow(self.history_list.count() - 1)

    def _append_history(self, entry: HistoryEntry, *, select: bool = True) -> None:
        self.history.append(entry)
        coord_text = "" if entry.coord is None else f" {entry.coord}"
        item = QListWidgetItem(f"{entry.action}{coord_text}")
        item.setData(Qt.ItemDataRole.UserRole, entry)
        self.history_list.addItem(item)
        if select:
            self.history_list.setCurrentItem(item)
            self.history_list.scrollToItem(item)
        self._refresh_history_icons(self.history_list.currentRow())

    def _refresh_history_icons(self, current_row: int) -> None:
        for row in range(self.history_list.count()):
            self.history_list.item(row).setIcon(self._step_badge_icon(row + 1, row == current_row))

    @staticmethod
    def _step_badge_icon(number: int, active: bool) -> QIcon:
        pixmap = QPixmap(60, 68)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(30.0, 33.0)
        radius = 24.0
        points = QPolygonF(
            [
                QPointF(
                    center.x() + radius * math.cos(math.radians(60 * index + 30)),
                    center.y() + radius * math.sin(math.radians(60 * index + 30)),
                )
                for index in range(6)
            ]
        )
        fill = QColor(COLORS["blue"] if active else COLORS["panel_alt"])
        stroke = QColor(COLORS["blue"] if active else COLORS["muted"])
        painter.setPen(QPen(stroke, 2.2))
        painter.setBrush(fill)
        painter.drawPolygon(points)
        painter.setPen(QColor(COLORS["white"] if active else COLORS["muted"]))
        font = QFont("Bahnschrift", 10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, str(number))
        painter.end()
        return QIcon(pixmap)

    def _history_item_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, HistoryEntry) and entry.coord is not None:
            self.stage.board_view.set_selected(entry.coord)

    def _on_cell_activated(self, coord: Coord) -> None:
        self.stage.board_view.set_selected(coord)
        try:
            change = self.session.set_cell_state(coord, self.selected_state)
        except BoardStateError as exc:
            self.stage.show_toast(str(exc), danger=True)
            return
        if change.before is change.after:
            return
        self.current_move = None
        self.stage.board_view.set_target(None)
        self.stage.board_view.sync_state()
        action = {
            CellVisualType.HIDDEN: "恢复未知",
            CellVisualType.BLUE: "标记蓝色",
            CellVisualType.BLACK: "标记排除",
        }[change.after]
        self._append_history(HistoryEntry(action, coord, state_change=True))
        self._update_counts()
        self._update_step_card(None)

    def solve_next_step(self) -> None:
        try:
            move = self.session.next_step()
        except SolverError as exc:
            self.stage.show_toast(f"求解失败：{exc}", danger=True)
            return
        self.current_move = move
        self.stage.board_view.set_target(move)
        self._update_step_card(move)
        if move is None:
            self.stage.show_toast("当前公开信息无法推出新的必然步骤")
        else:
            action = "标记蓝色" if move.action is MoveAction.MARK_BLUE else "标记排除"
            self.stage.show_toast(f"已定位：{move.coord} · {action}")

    def apply_current_move(self) -> None:
        if self.current_move is None:
            return
        move = self.current_move
        try:
            self.session.apply_suggested_move(move)
        except BoardStateError as exc:
            self.stage.show_toast(str(exc), danger=True)
            return
        action = "求解器：蓝色" if move.action is MoveAction.MARK_BLUE else "求解器：排除"
        self._append_history(HistoryEntry(action, move.coord, state_change=True))
        self.current_move = None
        self.stage.board_view.set_target(None)
        self.stage.board_view.sync_state()
        self._update_counts()
        self._update_step_card(None)

    def undo(self) -> None:
        change = self.session.undo()
        if change is None:
            self.stage.show_toast("没有可以撤销的手动修改")
            return
        self.current_move = None
        self.stage.board_view.set_target(None)
        self.stage.board_view.sync_state()
        for index in range(len(self.history) - 1, -1, -1):
            if self.history[index].state_change:
                del self.history[index]
                self.history_list.takeItem(index)
                break
        self._update_counts()
        self._update_step_card(None)

    def reset_board(self) -> None:
        self.session.reset()
        self.current_move = None
        self.stage.board_view.set_board(self.session.board)
        self._populate_initial_history()
        self._update_counts()
        self._update_step_card(None)
        self.stage.show_toast("已恢复到初始盘面")

    def generate_seed_board(self) -> None:
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
        self.history.clear()
        self.history_list.clear()
        self._load_board(
            self.session.board,
            mode_text=f"种子 {request.seed:08d} · {request.difficulty.label} · 离线精确生成",
            verified=True,
        )
        self._populate_initial_history()
        self.stage.show_toast(
            f"生成完成：{len(self.session.board.cells)} 个格子，{len(self.session.board.row_clues)} 条行线索"
        )

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
        self.history.clear()
        self.history_list.clear()
        self._load_board(board, mode_text=f"截图局面 · {Path(path).name}")
        self._populate_initial_history()

    def copy_seed(self) -> None:
        QApplication.clipboard().setText(self.seed_input.text())
        self.stage.show_toast("种子号已复制")

    def _update_step_card(self, move: Optional[SuggestedMove]) -> None:
        if move is None:
            self.step_title.setText("下一步")
            self.step_coord.setText("等待计算")
            self.step_reason.setPlainText("手动同步到卡住的位置后，获取一个必然成立的步骤。")
            self.apply_button.setEnabled(False)
            return
        action = "标记蓝色" if move.action is MoveAction.MARK_BLUE else "标记排除"
        self.step_title.setText(action)
        self.step_coord.setText(str(move.coord))
        self.step_reason.setPlainText(move.reason)
        self.step_reason.verticalScrollBar().setValue(0)
        self.apply_button.setEnabled(True)

    def _update_counts(self) -> None:
        board = self.session.board
        remaining = board.remaining_blue
        if remaining is None:
            remaining = len(board.hidden_cells())
        self.remaining_value.setText(str(remaining))
        self.stage.counter_badge.set_value(remaining)
        self.error_value.setText("0")

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._generation_thread is not None and self._generation_thread.isRunning():
            self.stage.show_toast("离线地图仍在生成，请完成后再关闭窗口。", danger=True)
            event.ignore()
            return
        super().closeEvent(event)


def run_app() -> None:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("HexInfinite 种子求解器")
    app.setOrganizationName("HexInfinite Solver")
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    window = MainWindow()
    window.show()
    app.exec()
