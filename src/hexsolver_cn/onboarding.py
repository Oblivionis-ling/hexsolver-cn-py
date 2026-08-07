from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QWidget

from .theme import COLORS


@dataclass(frozen=True)
class GuideTarget:
    text: str
    widget: QWidget
    color: str


class OnboardingOverlay(QWidget):
    """Static, code-drawn first-use guide with accessible text callouts."""

    NOTE_WIDTH = 338
    NOTE_HEIGHT = 76

    def __init__(
        self,
        stage: QWidget,
        targets: tuple[GuideTarget, ...],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.stage = stage
        self.targets = targets
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("OnboardingOverlay")

        self.title = QLabel("从这里开始", self)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setAccessibleName("使用说明：从这里开始")
        self.title.setStyleSheet(
            f"color: {COLORS['text']}; background: transparent; "
            'font-family: "Segoe Print", "Microsoft YaHei UI"; '
            "font-size: 27px; font-weight: 700;"
        )
        self.subtitle = QLabel("按顺序完成 01—04；生成真实种子盘面后，本说明会自动收起。", self)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setAccessibleName("使用说明概述")
        self.subtitle.setStyleSheet(
            f"color: {COLORS['muted']}; background: transparent; font-size: 13px;"
        )

        self.notes: list[QLabel] = []
        for index, target in enumerate(targets, start=1):
            label = QLabel(f"{index:02d}  {target.text}", self)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            label.setAccessibleName(f"使用说明第 {index} 步：{target.text}")
            label.setStyleSheet(
                f"color: {COLORS['text']}; background-color: rgba(255,255,255,238); "
                f"border: 2px solid {target.color}; border-radius: 7px; "
                'font-family: "Segoe Print", "Microsoft YaHei UI"; '
                "font-size: 14px; font-weight: 650; padding: 8px 14px;"
            )
            label.setFixedSize(self.NOTE_WIDTH, self.NOTE_HEIGHT)
            self.notes.append(label)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        self._layout_labels()
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._layout_labels()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        stage_rect = self._widget_rect(self.stage)
        painter.fillRect(stage_rect, QColor(255, 255, 255, 218))

        for index, (note, target) in enumerate(zip(self.notes, self.targets)):
            start = self._note_anchor(note.geometry(), self._target_center(target.widget))
            end = self._target_center(target.widget)
            self._draw_sketch_arrow(painter, start, end, QColor(target.color), index)
        painter.end()

    def _layout_labels(self) -> None:
        stage = self._widget_rect(self.stage)
        if stage.width() <= 0 or stage.height() <= 0:
            return
        title_width = min(440, max(300, stage.width() - 64))
        self.title.setGeometry(
            stage.left() + (stage.width() - title_width) // 2,
            stage.top() + 24,
            title_width,
            42,
        )
        subtitle_width = min(610, max(420, stage.width() - 72))
        self.subtitle.setGeometry(
            stage.left() + (stage.width() - subtitle_width) // 2,
            stage.top() + 65,
            subtitle_width,
            28,
        )

        right_x = max(stage.left() + 30, stage.right() - self.NOTE_WIDTH - 34)
        left_x = min(stage.right() - self.NOTE_WIDTH - 30, stage.left() + 38)
        available = max(500, stage.height())
        positions = (
            (left_x, stage.top() + int(available * 0.16)),
            (right_x, stage.top() + int(available * 0.34)),
            (left_x + 14, stage.top() + int(available * 0.55)),
            (right_x - 8, stage.bottom() - self.NOTE_HEIGHT - 56),
        )
        for note, (x, y) in zip(self.notes, positions):
            x = max(stage.left() + 22, min(x, stage.right() - self.NOTE_WIDTH - 22))
            y = max(stage.top() + 102, min(y, stage.bottom() - self.NOTE_HEIGHT - 24))
            note.move(x, y)
            note.raise_()

    def _widget_rect(self, widget: QWidget) -> QRect:
        top_left = self.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        return QRect(top_left, widget.size())

    def _target_center(self, widget: QWidget) -> QPointF:
        center = widget.rect().center()
        mapped = self.mapFromGlobal(widget.mapToGlobal(center))
        return QPointF(mapped)

    @staticmethod
    def _note_anchor(rect: QRect, target: QPointF) -> QPointF:
        center = QPointF(rect.center())
        dx = target.x() - center.x()
        dy = target.y() - center.y()
        if abs(dx) >= abs(dy):
            return QPointF(rect.left() if dx < 0 else rect.right(), center.y())
        return QPointF(center.x(), rect.top() if dy < 0 else rect.bottom())

    @staticmethod
    def _draw_sketch_arrow(
        painter: QPainter,
        start: QPointF,
        end: QPointF,
        color: QColor,
        index: int,
    ) -> None:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        bend = 18.0 if index % 2 == 0 else -18.0
        length = max(1.0, math.hypot(dx, dy))
        normal = QPointF(-dy / length * bend, dx / length * bend)

        def path_with_offset(offset: QPointF) -> QPainterPath:
            path = QPainterPath(start + offset)
            path.cubicTo(
                start + QPointF(dx * 0.34, dy * 0.18) + normal + offset,
                start + QPointF(dx * 0.72, dy * 0.82) + normal * 0.45 + offset,
                end + offset,
            )
            return path

        soft = QColor(color)
        soft.setAlpha(92)
        painter.setPen(
            QPen(soft, 4.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawPath(path_with_offset(QPointF(1.8, 1.2)))
        painter.setPen(
            QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawPath(path_with_offset(QPointF(-0.8, 0.2)))

        angle = math.atan2(dy, dx)
        head_length = 15.0
        for delta in (math.radians(153), math.radians(-153)):
            point = QPointF(
                end.x() + head_length * math.cos(angle + delta),
                end.y() + head_length * math.sin(angle + delta),
            )
            painter.drawLine(end, point)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(end.x() - 6, end.y() - 6, 12, 12))
