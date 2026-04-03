"""
SleepScreen — completely black. Any touch wakes the system.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QWidget


class SleepScreen(QWidget):
    touch_detected = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SleepScreen")
        self.setStyleSheet("background-color: #000000;")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.touch_detected.emit()
        super().mousePressEvent(event)
