from __future__ import annotations

import math
import os
from typing import Dict, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QStyle,
)

from .models import Board, CellVisualType, Coord, LineFamily, SuggestedMove
from .reason_interaction import ReasonReference, RowReferenceKey
from .theme import COLORS


class HexBoardView(QGraphicsView):
    cell_activated = Signal(object, object)

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        # Keep the fitted board and its outer line clues clear of the mode chip,
        # remaining counter, and bottom-right tool rail drawn by BoardStage.
        self.setViewportMargins(16, 64, 132, 18)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        self.board: Optional[Board] = None
        self._radius = 28.0
        self._cell_items: Dict[Coord, QGraphicsPolygonItem] = {}
        self._cell_text_items: Dict[Coord, QGraphicsSimpleTextItem] = {}
        self._row_clue_items: list[QGraphicsSimpleTextItem] = []
        self._row_clue_items_by_key: dict[RowReferenceKey, QGraphicsSimpleTextItem] = {}
        self._reason_halo_items: Dict[Coord, QGraphicsPolygonItem] = {}
        self._reason_overlay_items: Dict[Coord, QGraphicsPolygonItem] = {}
        self._reason_reference: Optional[ReasonReference] = None
        self._reason_pinned = False
        self._reason_animation_elapsed_ms = 0
        self._reason_animation_timer = QTimer(self)
        self._reason_animation_timer.setInterval(40)
        self._reason_animation_timer.timeout.connect(self._advance_reason_animation)
        self._reason_animation_enabled = (
            os.environ.get("HEXSOLVER_REDUCED_MOTION", "").strip().lower()
            not in {"1", "true", "yes"}
            and bool(self.style().styleHint(QStyle.StyleHint.SH_Widget_Animate, None, self))
        )
        self._target: Optional[Coord] = None
        self._selected: Optional[Coord] = None
        self._pan_origin: Optional[QPoint] = None
        self._auto_fit = True

    def set_board(self, board: Board) -> None:
        self.set_reason_reference(None)
        self.board = board
        self._target = None
        self._selected = None
        self._auto_fit = True
        self._rebuild_scene()
        QTimer.singleShot(0, self.fit_board)

    def _rebuild_scene(self) -> None:
        self._scene.clear()
        self._cell_items.clear()
        self._cell_text_items.clear()
        self._row_clue_items.clear()
        self._row_clue_items_by_key.clear()
        self._reason_halo_items.clear()
        self._reason_overlay_items.clear()
        if self.board is None:
            return

        self._radius = self._estimate_radius()
        for cell in self.board.visible_cells():
            if cell.visual_type is CellVisualType.OUTSIDE:
                continue
            cx, cy = cell.center
            shadow = self._polygon(cx, cy + 4.2, self._radius)
            shadow_item = self._scene.addPolygon(
                shadow,
                QPen(Qt.PenStyle.NoPen),
                QColor(0, 0, 0, 30),
            )
            shadow_item.setZValue(0)

            item = QGraphicsPolygonItem(self._polygon(cx, cy, self._radius))
            item.setPen(QPen(QColor(COLORS["white"]), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            item.setBrush(QColor(self._cell_color(cell.visual_type)))
            item.setData(0, cell.coord)
            item.setZValue(1)
            self._scene.addItem(item)
            self._cell_items[cell.coord] = item

            text = QGraphicsSimpleTextItem(cell.clue_text, item)
            font = QFont("Bahnschrift", max(10, int(self._radius * 0.50)))
            font.setWeight(QFont.Weight.DemiBold)
            text.setFont(font)
            text.setBrush(QColor(COLORS["white"]))
            text.setData(0, cell.coord)
            self._cell_text_items[cell.coord] = text
            self._position_cell_text(cell.coord)

            reason_halo = QGraphicsPolygonItem(
                self._polygon(cx, cy, self._radius + 7.0)
            )
            reason_halo.setPen(QPen(Qt.PenStyle.NoPen))
            reason_halo.setBrush(Qt.BrushStyle.NoBrush)
            reason_halo.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            reason_halo.setVisible(False)
            reason_halo.setZValue(5.5)
            self._scene.addItem(reason_halo)
            self._reason_halo_items[cell.coord] = reason_halo

            reason_overlay = QGraphicsPolygonItem(
                self._polygon(cx, cy, self._radius + 4.6)
            )
            reason_overlay.setPen(QPen(Qt.PenStyle.NoPen))
            reason_overlay.setBrush(Qt.BrushStyle.NoBrush)
            reason_overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            reason_overlay.setVisible(False)
            reason_overlay.setZValue(6)
            self._scene.addItem(reason_overlay)
            self._reason_overlay_items[cell.coord] = reason_overlay

        self._draw_row_clues()
        self._ensure_row_clues_visible()
        bounds = self._scene.itemsBoundingRect().adjusted(-68, -62, 68, 62)
        self._scene.setSceneRect(bounds)
        self.sync_state()

    def _draw_row_clues(self) -> None:
        if self.board is None:
            return
        rotation = {
            LineFamily.HORIZONTAL: 0.0,
            LineFamily.DOWN_RIGHT: 58.0,
            LineFamily.DOWN_LEFT: -58.0,
        }
        for row in self.board.row_clues:
            if not row.clue_text:
                continue
            text = QGraphicsSimpleTextItem(row.clue_text)
            font = QFont("Bahnschrift", 14)
            font.setWeight(QFont.Weight.DemiBold)
            text.setFont(font)
            text.setBrush(QColor(COLORS["text"]))
            if not any(self.board.get_cell(coord) for coord in row.coords):
                continue
            anchor = row.anchor
            bounds = text.boundingRect()
            text.setTransformOriginPoint(bounds.center())
            text.setRotation(rotation[row.family])
            text.setPos(anchor[0] - bounds.width() / 2.0, anchor[1] - bounds.height() / 2.0)
            text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            text.setZValue(8)
            self._scene.addItem(text)
            self._row_clue_items.append(text)
            self._row_clue_items_by_key[
                RowReferenceKey(row.line_id, row.family, len(row.coords))
            ] = text

    def _ensure_row_clues_visible(self) -> None:
        for item in self._row_clue_items:
            item.setVisible(True)
            item.setOpacity(1.0)
            item.setZValue(8)

    @property
    def row_clue_items(self) -> tuple[QGraphicsSimpleTextItem, ...]:
        return tuple(self._row_clue_items)

    @property
    def reason_highlighted_coords(self) -> tuple[Coord, ...]:
        return tuple(
            coord for coord, item in self._reason_overlay_items.items() if item.isVisible()
        )

    @property
    def reason_highlight_is_pinned(self) -> bool:
        return self._reason_reference is not None and self._reason_pinned

    @property
    def reason_animation_active(self) -> bool:
        return self._reason_animation_timer.isActive()

    @property
    def reason_highlighted_row(self) -> Optional[RowReferenceKey]:
        if self._reason_reference is None:
            return None
        return self._reason_reference.row_key

    def set_reason_reference(
        self,
        reference: Optional[ReasonReference],
        *,
        pinned: bool = False,
    ) -> None:
        self._reason_animation_timer.stop()
        self._reason_reference = reference
        self._reason_pinned = bool(reference is not None and pinned)
        self._reason_animation_elapsed_ms = 0

        for item in self._reason_halo_items.values():
            item.setVisible(False)
            item.setOpacity(1.0)
            item.setPen(QPen(Qt.PenStyle.NoPen))
        for item in self._reason_overlay_items.values():
            item.setVisible(False)
            item.setOpacity(1.0)
            item.setPen(QPen(Qt.PenStyle.NoPen))
        self._restore_row_clue_styles()

        if reference is None:
            self.viewport().update()
            return

        accent_pen = QPen(
            QColor(COLORS["reason_pinned"] if self._reason_pinned else COLORS["reason"]),
            3.0 if self._reason_pinned else 2.4,
            Qt.PenStyle.SolidLine if self._reason_pinned else Qt.PenStyle.CustomDashLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        if not self._reason_pinned:
            accent_pen.setDashPattern([1.8, 1.55])

        halo_pen = QPen(
            QColor(
                COLORS[
                    "reason_pinned_glow" if self._reason_pinned else "reason_glow"
                ]
            ),
            7.2 if self._reason_pinned else 6.4,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        preview_halo_opacity = 0.10 if self._reason_animation_enabled else 0.30
        for coord in reference.coords:
            halo_item = self._reason_halo_items.get(coord)
            item = self._reason_overlay_items.get(coord)
            if halo_item is None or item is None:
                continue
            halo_item.setPen(halo_pen)
            halo_item.setOpacity(0.38 if self._reason_pinned else preview_halo_opacity)
            halo_item.setVisible(True)
            item.setPen(accent_pen)
            item.setOpacity(1.0 if self._reason_pinned else 0.94)
            item.setVisible(True)

        if reference.row_key is not None:
            row_item = self._row_clue_items_by_key.get(reference.row_key)
            if row_item is not None:
                row_item.setBrush(
                    QColor(
                        COLORS["reason_pinned"]
                        if self._reason_pinned
                        else COLORS["reason"]
                    )
                )
                font = row_item.font()
                font.setWeight(
                    QFont.Weight.Bold if self._reason_pinned else QFont.Weight.DemiBold
                )
                row_item.setFont(font)
                row_item.setZValue(9)

        if not self._reason_pinned and self._reason_animation_enabled:
            self._reason_animation_timer.start()
        self.viewport().update()

    def _restore_row_clue_styles(self) -> None:
        for item in self._row_clue_items:
            item.setBrush(QColor(COLORS["text"]))
            font = item.font()
            font.setWeight(QFont.Weight.DemiBold)
            item.setFont(font)
            item.setOpacity(1.0)
            item.setZValue(8)

    def _advance_reason_animation(self) -> None:
        if self._reason_reference is None or self._reason_pinned:
            self._reason_animation_timer.stop()
            return
        self._reason_animation_elapsed_ms += self._reason_animation_timer.interval()
        progress = min(1.0, self._reason_animation_elapsed_ms / 240.0)
        eased = 1.0 - (1.0 - progress) ** 3
        opacity = 0.10 + (0.30 - 0.10) * eased
        for coord in self._reason_reference.coords:
            item = self._reason_halo_items.get(coord)
            if item is not None and item.isVisible():
                item.setOpacity(opacity)
        if progress >= 1.0:
            self._reason_animation_timer.stop()
        self.viewport().update()

    def sync_state(self) -> None:
        if self.board is None:
            return
        for coord, item in self._cell_items.items():
            cell = self.board.get_cell(coord)
            if cell is None:
                continue
            item.setBrush(QColor(self._cell_color(cell.visual_type)))
            text_item = self._cell_text_items.get(coord)
            if text_item is not None and text_item.text() != cell.clue_text:
                text_item.setText(cell.clue_text)
                self._position_cell_text(coord)
            if coord == self._target:
                item.setPen(QPen(QColor(COLORS["blue"]), 5.0))
                item.setZValue(4)
            elif coord == self._selected:
                item.setPen(QPen(QColor(COLORS["orange"]), 4.0))
                item.setZValue(3)
            else:
                item.setPen(QPen(QColor(COLORS["white"]), 3.2))
                item.setZValue(1)
        self._ensure_row_clues_visible()
        self.viewport().update()

    def _position_cell_text(self, coord: Coord) -> None:
        if self.board is None:
            return
        cell = self.board.get_cell(coord)
        text = self._cell_text_items.get(coord)
        if cell is None or text is None:
            return
        cx, cy = cell.center
        bounds = text.boundingRect()
        text.setPos(cx - bounds.width() / 2.0, cy - bounds.height() / 2.0 - 1.0)

    def set_target(self, move: Optional[SuggestedMove]) -> None:
        self._target = move.coord if move is not None else None
        self.sync_state()
        if move is not None and move.coord in self._cell_items:
            self.centerOn(self._cell_items[move.coord])

    def set_selected(self, coord: Optional[Coord]) -> None:
        self._selected = coord
        self.sync_state()

    def fit_board(self) -> None:
        if self._scene.items():
            self.resetTransform()
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self._auto_fit = True

    def zoom_in(self) -> None:
        self._auto_fit = False
        self.scale(1.14, 1.14)

    def zoom_out(self) -> None:
        self._auto_fit = False
        self.scale(1.0 / 1.14, 1.0 / 1.14)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self._auto_fit:
            QTimer.singleShot(0, self.fit_board)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._auto_fit = False
        factor = 1.12 if event.angleDelta().y() > 0 else 1.0 / 1.12
        current = self.transform().m11()
        if (factor > 1 and current < 3.2) or (factor < 1 and current > 0.22):
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            item: Optional[QGraphicsItem] = self.itemAt(event.position().toPoint())
            coord = None
            while item is not None and coord is None:
                coord = item.data(0)
                item = item.parentItem()
            if isinstance(coord, tuple) and len(coord) == 2:
                self.cell_activated.emit(coord, event.button())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._pan_origin is not None:
            current = event.position().toPoint()
            delta = current - self._pan_origin
            self._pan_origin = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._auto_fit = False
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_origin is not None:
            self._pan_origin = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(COLORS["background"]))
        painter.save()
        painter.setPen(QPen(QColor("#E9EBEA"), 1.1))
        radius = 68.0
        step_x = 230.0
        step_y = 198.0
        start_x = math.floor(rect.left() / step_x) * step_x
        start_y = math.floor(rect.top() / step_y) * step_y
        y = start_y
        row = 0
        while y <= rect.bottom() + step_y:
            x = start_x + (step_x / 2.0 if row % 2 else 0.0)
            while x <= rect.right() + step_x:
                painter.drawPolygon(self._polygon(x, y, radius))
                x += step_x
            y += step_y
            row += 1
        painter.restore()

    def _estimate_radius(self) -> float:
        if self.board is None:
            return 28.0
        spacing = min(
            value
            for value in (
                math.hypot(*self.board.basis_a),
                math.hypot(*self.board.basis_b),
            )
            if value > 0.1
        )
        return max(14.0, spacing * 0.55)

    @staticmethod
    def _polygon(cx: float, cy: float, radius: float) -> QPolygonF:
        return QPolygonF(
            [
                QPointF(
                    cx + radius * math.cos(math.radians(60 * index)),
                    cy + radius * math.sin(math.radians(60 * index)),
                )
                for index in range(6)
            ]
        )

    @staticmethod
    def _cell_color(state: CellVisualType) -> str:
        return {
            CellVisualType.HIDDEN: COLORS["orange"],
            CellVisualType.BLUE: COLORS["blue"],
            CellVisualType.BLACK: COLORS["charcoal"],
            CellVisualType.GREY: "#C9CCCB",
            CellVisualType.OUTSIDE: COLORS["background"],
        }[state]
