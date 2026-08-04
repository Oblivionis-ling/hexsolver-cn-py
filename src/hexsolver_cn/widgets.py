from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QFrame, QSizePolicy, QVBoxLayout, QWidget

from .models import CellVisualType
from .theme import COLORS


def _chamfer_path(rect: QRectF, amount: float) -> QPainterPath:
    amount = min(amount, rect.width() / 3.0, rect.height() / 3.0)
    path = QPainterPath(QPointF(rect.left() + amount, rect.top()))
    path.lineTo(rect.right() - amount, rect.top())
    path.lineTo(rect.right(), rect.top() + amount)
    path.lineTo(rect.right(), rect.bottom() - amount)
    path.lineTo(rect.right() - amount, rect.bottom())
    path.lineTo(rect.left() + amount, rect.bottom())
    path.lineTo(rect.left(), rect.bottom() - amount)
    path.lineTo(rect.left(), rect.top() + amount)
    path.closeSubpath()
    return path


class ChamferPanel(QFrame):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        fill: str = COLORS["panel"],
        border: str = COLORS["border"],
        chamfer: int = 13,
    ) -> None:
        super().__init__(parent)
        self.fill = QColor(fill)
        self.border = QColor(border)
        self.chamfer = chamfer
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(QPen(self.border, 1.2))
        painter.setBrush(self.fill)
        painter.drawPath(_chamfer_path(rect, float(self.chamfer)))
        painter.end()
        super().paintEvent(event)


class StateButton(QAbstractButton):
    STATE_COLORS = {
        CellVisualType.HIDDEN: COLORS["orange"],
        CellVisualType.BLUE: COLORS["blue"],
        CellVisualType.BLACK: COLORS["charcoal"],
    }

    def __init__(self, state: CellVisualType, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.label = label
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(76, 88)
        self.setToolTip(f"点击棋盘后设为{label}")

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2.0, 33.0)
        radius = 25.0
        points = [
            QPointF(
                center.x() + radius * math.cos(math.radians(60 * index)),
                center.y() + radius * math.sin(math.radians(60 * index)),
            )
            for index in range(6)
        ]
        shadow = QPolygonF([QPointF(point.x(), point.y() + 3.0) for point in points])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 35))
        painter.drawPolygon(shadow)

        color = QColor(self.STATE_COLORS[self.state])
        if self.underMouse():
            color = color.lighter(106)
        painter.setPen(QPen(QColor(COLORS["blue"] if self.isChecked() else COLORS["white"]), 3.0))
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF(points))

        if self.state is CellVisualType.BLACK:
            painter.setPen(QPen(QColor(COLORS["white"]), 2.4))
            painter.drawLine(QPointF(center.x() - 6, center.y() - 6), QPointF(center.x() + 6, center.y() + 6))
            painter.drawLine(QPointF(center.x() + 6, center.y() - 6), QPointF(center.x() - 6, center.y() + 6))

        painter.setPen(QColor(COLORS["text"] if self.isChecked() else COLORS["muted"]))
        font = QFont("Microsoft YaHei UI", 10)
        font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
        painter.setFont(font)
        painter.drawText(QRectF(0, 66, self.width(), 20), Qt.AlignmentFlag.AlignCenter, self.label)
        painter.end()


class HexCounterBadge(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0
        self._caption = "剩余"
        self.setFixedSize(112, 128)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_value(self, value: int, caption: str = "剩余") -> None:
        self._value = max(0, int(value))
        self._caption = caption
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2.0, 59.0)
        radius = 52.0
        points = [
            QPointF(
                center.x() + radius * math.cos(math.radians(60 * index + 30)),
                center.y() + radius * math.sin(math.radians(60 * index + 30)),
            )
            for index in range(6)
        ]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 33))
        painter.drawPolygon(QPolygonF([QPointF(p.x(), p.y() + 5) for p in points]))
        painter.setPen(QPen(QColor(COLORS["white"]), 2.5))
        painter.setBrush(QColor(COLORS["blue"]))
        painter.drawPolygon(QPolygonF(points))

        painter.setPen(QColor(COLORS["white"]))
        caption_font = QFont("Microsoft YaHei UI", 10)
        caption_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(caption_font)
        painter.drawText(QRectF(0, 28, self.width(), 20), Qt.AlignmentFlag.AlignCenter, self._caption)
        value_font = QFont("Bahnschrift", 28)
        value_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(value_font)
        painter.drawText(QRectF(0, 46, self.width(), 43), Qt.AlignmentFlag.AlignCenter, str(self._value))
        painter.end()


class CompactPanel(ChamferPanel):
    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 14, 15, 14)
        layout.setSpacing(spacing)
