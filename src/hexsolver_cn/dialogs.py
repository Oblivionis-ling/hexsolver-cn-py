from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import COLORS


class LightConfirmDialog(QDialog):
    """A predictable light confirmation surface independent of the OS theme."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        message: str,
        detail: str = "",
        accept_text: str = "确定",
        reject_text: str = "取消",
        destructive: bool = False,
        default_accept: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LightConfirmDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(520)
        self.setMaximumWidth(640)
        self.setAccessibleName(title)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(12, 12, 12, 12)

        surface = QFrame(self)
        surface.setObjectName("ConfirmSurface")
        shadow = QGraphicsDropShadowEffect(surface)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(35, 38, 40, 72))
        surface.setGraphicsEffect(shadow)
        outer_layout.addWidget(surface)

        layout = QVBoxLayout(surface)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(10)
        brand_icon = QLabel(surface)
        brand_icon.setObjectName("ConfirmBrandIcon")
        brand_icon.setPixmap(qta.icon("mdi6.hexagon", color=COLORS["orange"]).pixmap(22, 22))
        brand_icon.setFixedSize(24, 24)
        brand_icon.setAccessibleName("HexInfinite")
        header.addWidget(brand_icon)

        self.title_label = QLabel(title, surface)
        self.title_label.setObjectName("ConfirmTitle")
        header.addWidget(self.title_label, 1)

        self.close_button = QPushButton(surface)
        self.close_button.setObjectName("ConfirmCloseButton")
        self.close_button.setIcon(qta.icon("fa5s.times", color=COLORS["muted"]))
        self.close_button.setIconSize(QSize(15, 15))
        self.close_button.setFixedSize(36, 36)
        self.close_button.setAccessibleName("关闭")
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        divider = QFrame(surface)
        divider.setObjectName("ConfirmDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_tile = QLabel(surface)
        icon_tile.setObjectName("ConfirmIconTile")
        icon_tile.setPixmap(qta.icon("fa5s.question", color=COLORS["blue_hover"]).pixmap(22, 22))
        icon_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_tile.setFixedSize(48, 48)
        icon_tile.setAccessibleName("确认提示")
        body.addWidget(icon_tile, 0, Qt.AlignmentFlag.AlignTop)

        message_column = QVBoxLayout()
        message_column.setSpacing(8)
        self.message_label = QLabel(message, surface)
        self.message_label.setObjectName("ConfirmMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message_column.addWidget(self.message_label)

        self.detail_label = QLabel(detail, surface)
        self.detail_label.setObjectName("ConfirmDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_label.setVisible(bool(detail))
        message_column.addWidget(self.detail_label)
        body.addLayout(message_column, 1)
        layout.addLayout(body)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        self.reject_button = QPushButton(reject_text, surface)
        self.reject_button.setObjectName("ConfirmSecondaryButton")
        self.reject_button.setMinimumHeight(42)
        self.reject_button.setAccessibleName(reject_text)
        self.reject_button.clicked.connect(self.reject)
        actions.addWidget(self.reject_button)

        self.accept_button = QPushButton(accept_text, surface)
        self.accept_button.setObjectName(
            "ConfirmDangerButton" if destructive else "ConfirmPrimaryButton"
        )
        self.accept_button.setMinimumHeight(42)
        self.accept_button.setAccessibleName(accept_text)
        self.accept_button.clicked.connect(self.accept)
        actions.addWidget(self.accept_button)
        layout.addLayout(actions)

        if default_accept:
            self.accept_button.setDefault(True)
            self.accept_button.setFocus()
        else:
            self.reject_button.setDefault(True)
            self.reject_button.setFocus()

        self.setStyleSheet(
            f"""
            QDialog#LightConfirmDialog {{ background: transparent; }}
            QFrame#ConfirmSurface {{
                background-color: {COLORS['white']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
            QLabel#ConfirmTitle {{
                color: {COLORS['text']}; background: transparent;
                font-size: 18px; font-weight: 700;
            }}
            QLabel#ConfirmMessage {{
                color: {COLORS['text']}; background: transparent;
                font-size: 14px; font-weight: 650;
            }}
            QLabel#ConfirmDetail {{
                color: {COLORS['muted']}; background: transparent;
                font-size: 12px; line-height: 1.6;
            }}
            QLabel#ConfirmIconTile {{
                background-color: {COLORS['blue_soft']};
                border: 1px solid #BDE5F3; border-radius: 24px;
            }}
            QFrame#ConfirmDivider {{
                background-color: {COLORS['border']}; border: none;
            }}
            QPushButton#ConfirmCloseButton {{
                background: transparent; border: none; border-radius: 4px;
                min-width: 36px; min-height: 36px; padding: 0;
            }}
            QPushButton#ConfirmCloseButton:hover {{ background-color: {COLORS['panel_alt']}; }}
            QPushButton#ConfirmSecondaryButton {{
                color: {COLORS['text']}; background-color: {COLORS['white']};
                border: 1px solid {COLORS['border']}; border-radius: 4px;
                padding: 0 18px; font-weight: 650;
            }}
            QPushButton#ConfirmSecondaryButton:hover {{ background-color: {COLORS['panel_alt']}; }}
            QPushButton#ConfirmPrimaryButton {{
                color: {COLORS['white']}; background-color: {COLORS['blue']};
                border: 1px solid {COLORS['blue']}; border-radius: 4px;
                padding: 0 20px; font-weight: 700;
            }}
            QPushButton#ConfirmPrimaryButton:hover {{ background-color: {COLORS['blue_hover']}; }}
            QPushButton#ConfirmDangerButton {{
                color: {COLORS['white']}; background-color: {COLORS['danger']};
                border: 1px solid {COLORS['danger']}; border-radius: 4px;
                padding: 0 20px; font-weight: 700;
            }}
            QPushButton#ConfirmDangerButton:hover {{ background-color: #C94E44; }}
            """
        )


def ask_confirmation(
    parent: QWidget | None,
    *,
    title: str,
    message: str,
    detail: str = "",
    accept_text: str = "确定",
    reject_text: str = "取消",
    destructive: bool = False,
    default_accept: bool = True,
) -> bool:
    dialog = LightConfirmDialog(
        parent,
        title=title,
        message=message,
        detail=detail,
        accept_text=accept_text,
        reject_text=reject_text,
        destructive=destructive,
        default_accept=default_accept,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted
