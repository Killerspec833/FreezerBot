"""
SetupWizard — placeholder for Phase 3.

Emits setup_complete(dict) when the user finishes first-boot configuration.
The dict contains all values to be merged into config.json.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.core.theme import COLOR_BACKGROUND, COLOR_TEXT_SECONDARY, FONT_BODY, MARGIN


class SetupWizard(QWidget):
    """
    Full implementation coming in Phase 3.
    Currently shows a placeholder screen so the app can launch without crashing.
    """

    setup_complete = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SetupWizard")
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._build_placeholder()

    def _build_placeholder(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.addStretch()

        label = QLabel("Setup Wizard\n\n(Phase 3 — Coming Soon)")
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        font = QFont()
        font.setPointSize(FONT_BODY)
        label.setFont(font)
        label.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        layout.addWidget(label)

        layout.addStretch()
