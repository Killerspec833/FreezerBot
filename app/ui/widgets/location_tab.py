"""
LocationTabBar — horizontal tab strip for filtering inventory by location.

Emits location_selected(str) with the canonical location key,
or "all" when the All tab is selected.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.core.theme import (
    COLOR_BORDER,
    COLOR_TAB_ACTIVE,
    COLOR_TAB_INACTIVE,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_WHITE,
    FONT_SMALL,
    TAB_HEIGHT,
)

_TAB_STYLE_ACTIVE = f"""
    QPushButton {{
        background-color: {COLOR_TAB_ACTIVE};
        color: {COLOR_TEXT_WHITE};
        font-size: {FONT_SMALL}pt;
        font-weight: bold;
        border: none;
        border-bottom: 3px solid {COLOR_TEXT_WHITE};
        padding: 4px 8px;
        min-height: {TAB_HEIGHT}px;
    }}
"""

_TAB_STYLE_INACTIVE = f"""
    QPushButton {{
        background-color: {COLOR_TAB_INACTIVE};
        color: {COLOR_TEXT_SECONDARY};
        font-size: {FONT_SMALL}pt;
        border: none;
        border-bottom: 3px solid {COLOR_BORDER};
        padding: 4px 8px;
        min-height: {TAB_HEIGHT}px;
    }}
    QPushButton:pressed {{
        background-color: #3A3A3A;
    }}
"""


class LocationTabBar(QWidget):
    location_selected = pyqtSignal(str)   # canonical key or "all"

    def __init__(self, location_names: dict[str, str], parent=None):
        """
        location_names: {canonical_key: display_name, ...}
        """
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        self._current: str = "all"
        self._build(location_names)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(self, key: str) -> None:
        """Programmatically activate a tab without emitting the signal."""
        self._set_active(key, emit=False)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self, location_names: dict[str, str]) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = {"all": "All", **location_names}
        for key, display in tabs.items():
            btn = QPushButton(display)
            font = QFont()
            font.setPointSize(FONT_SMALL)
            btn.setFont(font)
            btn.setStyleSheet(
                _TAB_STYLE_ACTIVE if key == "all" else _TAB_STYLE_INACTIVE
            )
            btn.clicked.connect(lambda checked, k=key: self._set_active(k))
            layout.addWidget(btn)
            self._buttons[key] = btn

    def _set_active(self, key: str, emit: bool = True) -> None:
        if key == self._current:
            return
        for k, btn in self._buttons.items():
            btn.setStyleSheet(
                _TAB_STYLE_ACTIVE if k == key else _TAB_STYLE_INACTIVE
            )
        self._current = key
        if emit:
            self.location_selected.emit(key)
