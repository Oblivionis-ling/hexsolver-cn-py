from __future__ import annotations

from PySide6.QtCore import QSettings


ORIGINAL_MOUSE_CONTROLS_KEY = "controls/original_mouse_buttons"


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
