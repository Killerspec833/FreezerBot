#!/usr/bin/env python3
"""
Preview the falling-snow screensaver in isolation.

Run from the project root:
    python3 scripts/preview_sleep_screen.py

Click the window or press Escape to exit.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from app.ui.sleep_screen import SleepScreen


class _PreviewScreen(SleepScreen):
    """Thin wrapper that adds Escape-to-quit for the preview."""

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()
        super().keyPressEvent(event)


def main() -> None:
    app = QApplication(sys.argv)

    w = _PreviewScreen()
    w.setWindowTitle("Freezerbot — Sleep Screen Preview  (click or Esc to quit)")
    w.resize(1024, 600)
    w.show()
    w.on_show()

    # Click anywhere to close
    w.touch_detected.connect(QApplication.quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
