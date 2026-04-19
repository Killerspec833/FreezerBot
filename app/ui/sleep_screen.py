"""
SleepScreen — falling-snow screensaver.

Shown after the inactivity timeout.  Any touch or the wake word dismisses it.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QWidget

from app.core.theme import SCREEN_H, SCREEN_W
from app.ui.widgets.falling_snow_widget import FallingSnowWidget


class SleepScreen(QWidget):
    touch_detected = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SleepScreen")
        self.setStyleSheet("background-color: #000000;")

        self._snow = FallingSnowWidget(self)
        self._snow.setGeometry(0, 0, SCREEN_W, SCREEN_H)

    # ------------------------------------------------------------------
    # Lifecycle hooks (called by MainWindow._on_state_changed)
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        self._snow.start()

    def on_hide(self) -> None:
        self._snow.stop()

    # ------------------------------------------------------------------
    # Touch / resize
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._snow.setGeometry(0, 0, self.width(), self.height())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.touch_detected.emit()
        super().mousePressEvent(event)
