from __future__ import annotations


COLORS = {
    "background": "#F5F6F5",
    "panel": "#FAFBFA",
    "panel_alt": "#F1F3F2",
    "border": "#E0E3E2",
    "white": "#FFFFFF",
    "text": "#3C3E40",
    "muted": "#7B7F82",
    "faint": "#B8BCBE",
    "orange": "#FFA814",
    "orange_hover": "#F39A00",
    "orange_soft": "#FFF1D4",
    "blue": "#0DA9E5",
    "blue_hover": "#0795CC",
    "blue_soft": "#DDF4FC",
    "charcoal": "#3D3F42",
    "charcoal_hover": "#2F3134",
    "shadow": "#B8BBBC",
    "danger": "#D85D51",
}


def app_stylesheet() -> str:
    c = COLORS
    return f"""
    * {{
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        color: {c['text']};
        outline: none;
    }}
    QMainWindow, QWidget#AppRoot {{
        background-color: {c['background']};
    }}
    QLabel {{
        background-color: transparent;
    }}
    QLabel#SectionTitle {{
        font-size: 14px;
        font-weight: 700;
        color: {c['text']};
    }}
    QLabel#MutedLabel {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QLineEdit {{
        background-color: transparent;
        border: none;
        border-bottom: 1px solid {c['border']};
        padding: 4px 2px 7px 2px;
        font-family: "Bahnschrift", "Segoe UI";
        font-size: 24px;
        font-weight: 650;
        selection-background-color: {c['blue_soft']};
    }}
    QLineEdit:focus {{
        border-bottom: 2px solid {c['blue']};
    }}
    QPushButton {{
        border: 1px solid {c['border']};
        background-color: {c['panel_alt']};
        border-radius: 4px;
        min-height: 34px;
        padding: 0 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {c['white']};
        border-color: #CED2D1;
    }}
    QPushButton:pressed {{
        background-color: #E7E9E8;
    }}
    QPushButton#DifficultyButton {{
        border: 1px solid {c['border']};
        background-color: {c['panel_alt']};
        min-height: 34px;
        padding: 0;
        font-size: 13px;
    }}
    QPushButton#DifficultyButton:checked {{
        color: {c['white']};
        background-color: {c['blue']};
        border-color: {c['blue']};
    }}
    QPushButton#GenerateButton {{
        color: {c['white']};
        background-color: {c['orange']};
        border: none;
        border-radius: 3px;
        min-height: 52px;
        font-size: 17px;
        font-weight: 700;
    }}
    QPushButton#GenerateButton:hover {{
        background-color: {c['orange_hover']};
    }}
    QPushButton#NextButton {{
        color: {c['white']};
        background-color: {c['blue']};
        border-color: {c['blue']};
        min-height: 38px;
        font-size: 14px;
        font-weight: 700;
    }}
    QPushButton#NextButton:hover {{
        background-color: {c['blue_hover']};
    }}
    QPushButton#GhostButton {{
        background-color: transparent;
        border: none;
        padding: 0;
        min-width: 32px;
        min-height: 32px;
    }}
    QPushButton#GhostButton:hover {{
        background-color: {c['panel_alt']};
    }}
    QListWidget {{
        background-color: transparent;
        border: none;
        padding: 2px;
        font-size: 12px;
    }}
    QListWidget::item {{
        min-height: 38px;
        padding: 0 7px;
        border-left: 1px solid {c['border']};
        color: {c['muted']};
    }}
    QListWidget::item:selected {{
        color: {c['blue_hover']};
        background-color: {c['blue_soft']};
        border-left: 3px solid {c['blue']};
        font-weight: 700;
    }}
    QScrollBar:vertical {{
        background-color: transparent;
        width: 7px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: #D3D6D5;
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QToolTip {{
        background-color: {c['charcoal']};
        color: {c['white']};
        border: none;
        padding: 6px 8px;
    }}
    """
