"""
ListeningScreen — shown while the system is recording audio.

Layout (480 x 800 portrait):
  - AnimatedCircle centred vertically in the upper 60% of the screen
  - "Listening..." label below the circle
  - Optional status line at the bottom (e.g. "Processing...")
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.core.theme import (
    COLOR_BACKGROUND,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_WHITE,
    FONT_BODY,
    FONT_SMALL,
    MARGIN,
)
from app.ui.widgets.animated_circle import AnimatedCircle


class ListeningScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ListeningScreen")
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        """Update the small status label at the bottom (e.g. 'Processing...')."""
        self._status_label.setText(text)

    def on_show(self) -> None:
        """Call when this screen becomes active."""
        self._circle.start_animation()
        self._main_label.setText("Listening...")
        self._status_label.setText("")

    def on_hide(self) -> None:
        """Call when this screen is replaced by another."""
        self._circle.stop_animation()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, 0, MARGIN, MARGIN)
        layout.setSpacing(0)

        # Top spacer — pushes circle into upper-centre region
        layout.addStretch(2)

        # Animated circle — centred horizontally
        self._circle = AnimatedCircle(self)
        layout.addWidget(self._circle, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(24)

        # "Listening..." label
        self._main_label = QLabel("Listening...")
        self._main_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        font = QFont()
        font.setPointSize(FONT_BODY)
        font.setBold(True)
        self._main_label.setFont(font)
        self._main_label.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        layout.addWidget(self._main_label)

        # Bottom spacer
        layout.addStretch(3)

        # Status line at the very bottom
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        status_font = QFont()
        status_font.setPointSize(FONT_SMALL)
        self._status_label.setFont(status_font)
        self._status_label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        layout.addWidget(self._status_label)
