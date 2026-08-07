from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QSettings


ORIGINAL_MOUSE_CONTROLS_KEY = "controls/original_mouse_buttons"
STARTUP_WINDOW_MODE_KEY = "ui/startup_window_mode"


class StartupWindowMode(str, Enum):
    MAXIMIZED = "maximized"
    FULLSCREEN = "fullscreen"
    NORMAL = "normal"

    @property
    def label(self) -> str:
        return {
            StartupWindowMode.MAXIMIZED: "有窗口最大化（默认）",
            StartupWindowMode.FULLSCREEN: "无边框全屏",
            StartupWindowMode.NORMAL: "普通窗口",
        }[self]


class AppPreferences:
    """Small typed wrapper around persistent user-facing application options."""

    def __init__(
        self,
        settings: QSettings | None = None,
        *,
        persistent: bool = True,
    ) -> None:
        self._settings = settings if settings is not None else (QSettings() if persistent else None)
        self._memory_values: dict[str, object] = {}

    @property
    def original_mouse_controls_enabled(self) -> bool:
        value = self._value(ORIGINAL_MOUSE_CONTROLS_KEY, False)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def set_original_mouse_controls_enabled(self, enabled: bool) -> None:
        self._set_value(ORIGINAL_MOUSE_CONTROLS_KEY, bool(enabled))

    @property
    def startup_window_mode(self) -> StartupWindowMode:
        value = str(
            self._value(STARTUP_WINDOW_MODE_KEY, StartupWindowMode.MAXIMIZED.value)
        ).strip()
        try:
            return StartupWindowMode(value)
        except ValueError:
            return StartupWindowMode.MAXIMIZED

    def set_startup_window_mode(self, mode: StartupWindowMode) -> None:
        self._set_value(STARTUP_WINDOW_MODE_KEY, mode.value)

    def _value(self, key: str, default: object) -> object:
        if self._settings is None:
            return self._memory_values.get(key, default)
        return self._settings.value(key, default)

    def _set_value(self, key: str, value: object) -> None:
        if self._settings is None:
            self._memory_values[key] = value
            return
        self._settings.setValue(key, value)
        self._settings.sync()
