from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextBrowser

from .models import Board, CellVisualType, Coord, LineFamily
from .theme import COLORS


_COORD_PATTERN = re.compile(r"\((-?\d+)\s*,\s*(-?\d+)\)")
_COORD_ARRAY_PATTERN = re.compile(
    r"\[(?:\s*\(-?\d+\s*,\s*-?\d+\)\s*(?:、\s*)?)+\]"
)


class ReasonReferenceKind(str, Enum):
    CELLS = "cells"
    ROW = "row"


@dataclass(frozen=True)
class RowReferenceKey:
    line_id: str
    family: LineFamily
    length: int


@dataclass(frozen=True)
class ReasonReference:
    reference_id: str
    kind: ReasonReferenceKind
    start: int
    end: int
    label: str
    coords: tuple[Coord, ...]
    row_key: Optional[RowReferenceKey] = None


def parse_reason_references(text: str, board: Board) -> tuple[ReasonReference, ...]:
    """Find board-backed references while preserving their exact source spans."""

    occupied: list[tuple[int, int]] = []
    pending: list[
        tuple[int, int, ReasonReferenceKind, tuple[Coord, ...], Optional[RowReferenceKey]]
    ] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < used_end and end > used_start for used_start, used_end in occupied)

    def board_coords(matches: list[tuple[str, str]]) -> tuple[Coord, ...]:
        result: list[Coord] = []
        seen: set[Coord] = set()
        for q_text, r_text in matches:
            coord = (int(q_text), int(r_text))
            cell = board.get_cell(coord)
            if (
                coord in seen
                or cell is None
                or cell.visual_type is CellVisualType.OUTSIDE
            ):
                continue
            seen.add(coord)
            result.append(coord)
        return tuple(result)

    # Arrays are intentionally claimed first so one long set behaves as one link,
    # rather than becoming a dense run of competing single-coordinate links.
    for match in _COORD_ARRAY_PATTERN.finditer(text):
        coords = board_coords(_COORD_PATTERN.findall(match.group(0)))
        if not coords:
            continue
        start, end = match.span()
        occupied.append((start, end))
        pending.append((start, end, ReasonReferenceKind.CELLS, coords, None))

    # Use the model's own display name as the parsing contract. This avoids fuzzy
    # direction matching and keeps mirrored left/right labels tied to the exact row.
    row_names = sorted(
        ((row.display_name(), row) for row in board.row_clues),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for display_name, row in row_names:
        search_from = 0
        while True:
            start = text.find(display_name, search_from)
            if start < 0:
                break
            end = start + len(display_name)
            search_from = end
            if overlaps(start, end):
                continue
            coords = tuple(
                coord
                for coord in row.coords
                if (cell := board.get_cell(coord)) is not None
                and cell.visual_type is not CellVisualType.OUTSIDE
            )
            if not coords:
                continue
            row_key = RowReferenceKey(row.line_id, row.family, len(row.coords))
            occupied.append((start, end))
            pending.append((start, end, ReasonReferenceKind.ROW, coords, row_key))

    for match in _COORD_PATTERN.finditer(text):
        start, end = match.span()
        if overlaps(start, end):
            continue
        coords = board_coords([match.groups()])
        if not coords:
            continue
        occupied.append((start, end))
        pending.append((start, end, ReasonReferenceKind.CELLS, coords, None))

    references: list[ReasonReference] = []
    for index, (start, end, kind, coords, row_key) in enumerate(
        sorted(pending, key=lambda item: (item[0], item[1]))
    ):
        references.append(
            ReasonReference(
                reference_id=f"reason-ref-{index}",
                kind=kind,
                start=start,
                end=end,
                label=text[start:end],
                coords=coords,
                row_key=row_key,
            )
        )
    return tuple(references)


class InteractiveReasonBrowser(QTextBrowser):
    """Read-only reason text whose board references can be previewed or pinned."""

    reference_focus_changed = Signal(object, bool)
    pin_state_changed = Signal()

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.setAccessibleName("推理原因")
        self.setAccessibleDescription(
            "悬停坐标或行线索可在棋盘预览；点击可固定高亮，再次点击取消。"
        )
        self._references: tuple[ReasonReference, ...] = ()
        self._references_by_href: dict[str, ReasonReference] = {}
        self._hovered: Optional[ReasonReference] = None
        self._pinned: Optional[ReasonReference] = None
        self._pressed: Optional[ReasonReference] = None

    @property
    def references(self) -> tuple[ReasonReference, ...]:
        return self._references

    @property
    def hovered_reference(self) -> Optional[ReasonReference]:
        return self._hovered

    @property
    def pinned_reference(self) -> Optional[ReasonReference]:
        return self._pinned

    @property
    def active_reference(self) -> Optional[ReasonReference]:
        return self._hovered or self._pinned

    def set_reason(self, text: str, board: Board) -> None:
        self._hovered = None
        self._pinned = None
        self._pressed = None
        self._references = parse_reason_references(text, board)
        self._references_by_href = {
            self._href(reference): reference for reference in self._references
        }
        self.setPlainText(text)
        self._refresh_reference_formats()
        self.reference_focus_changed.emit(None, False)

    def clear_reference_state(self) -> None:
        if self._hovered is None and self._pinned is None:
            self.reference_focus_changed.emit(None, False)
            return
        self._hovered = None
        self._pinned = None
        self._pressed = None
        self._refresh_reference_formats()
        self.reference_focus_changed.emit(None, False)

    def restore_view_state(
        self,
        pinned_reference_id: Optional[str],
        scroll_value: int,
    ) -> None:
        self._pinned = next(
            (
                reference
                for reference in self._references
                if reference.reference_id == pinned_reference_id
            ),
            None,
        )
        self._hovered = None
        self._pressed = None
        self._refresh_reference_formats()
        self._emit_active_reference()
        scroll_bar = self.verticalScrollBar()
        scroll_bar.setValue(max(scroll_bar.minimum(), min(scroll_value, scroll_bar.maximum())))

    def reference_cursor_rect(self, reference: ReasonReference):  # type: ignore[no-untyped-def]
        cursor = QTextCursor(self.document())
        cursor.setPosition(reference.start)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        return self.cursorRect(cursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        reference = self._reference_at(event.position().toPoint())
        if reference is not self._hovered:
            self._hovered = reference
            self._refresh_reference_formats()
            self._emit_active_reference()
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor
            if reference is not None
            else Qt.CursorShape.IBeamCursor
        )
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self._reference_at(event.position().toPoint())
            if self._pressed is not None:
                event.accept()
                return
        self._pressed = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pressed is not None:
            pressed = self._pressed
            self._pressed = None
            if self._reference_at(event.position().toPoint()) == pressed:
                self._toggle_reference(pressed)
            event.accept()
            return
        self._pressed = None
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._clear_hover()
        super().leaveEvent(event)

    def viewportEvent(self, event: QEvent) -> bool:
        # References already communicate their state through text and board
        # highlighting. Suppress Qt's hover help path completely so no native
        # tooltip can obscure the reasoning text.
        if event.type() == QEvent.Type.ToolTip:
            return True
        if event.type() == QEvent.Type.Leave:
            self._clear_hover()
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        if dx or dy:
            self._clear_hover()
        super().scrollContentsBy(dx, dy)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            href = self.textCursor().charFormat().anchorHref()
            reference = self._references_by_href.get(href)
            if reference is not None:
                self._toggle_reference(reference)
                event.accept()
                return
        super().keyPressEvent(event)

    def _toggle_reference(self, reference: ReasonReference) -> None:
        self._pinned = None if self._pinned == reference else reference
        self._refresh_reference_formats()
        self._emit_active_reference()
        self.pin_state_changed.emit()

    def _clear_hover(self) -> None:
        if self._hovered is not None:
            self._hovered = None
            self._refresh_reference_formats()
            self._emit_active_reference()
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    def _emit_active_reference(self) -> None:
        active = self.active_reference
        self.reference_focus_changed.emit(active, active is not None and active == self._pinned)

    def _reference_at(self, point: QPoint) -> Optional[ReasonReference]:
        return self._references_by_href.get(self.anchorAt(point))

    def _refresh_reference_formats(self) -> None:
        for reference in self._references:
            text_format = QTextCharFormat()
            text_format.setAnchor(True)
            text_format.setAnchorHref(self._href(reference))
            text_format.setToolTip("")
            text_format.setFontUnderline(False)
            text_format.setForeground(QColor(COLORS["reason_text"]))
            text_format.setBackground(QColor(0, 0, 0, 0))
            text_format.setFontWeight(QFont.Weight.Normal)
            if reference == self._hovered:
                text_format.setBackground(QColor(COLORS["reason_soft"]))
            if reference == self._pinned:
                text_format.setForeground(QColor(COLORS["reason_pinned"]))
                text_format.setBackground(QColor(COLORS["reason_soft"]))
                text_format.setFontWeight(QFont.Weight.Bold)
            cursor = QTextCursor(self.document())
            cursor.setPosition(reference.start)
            cursor.setPosition(reference.end, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(text_format)

    @staticmethod
    def _href(reference: ReasonReference) -> str:
        return f"reason://{reference.reference_id}"
