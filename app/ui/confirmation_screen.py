"""
ConfirmationScreen — displayed after speech is parsed for ADD or REMOVE.

Shows the interpreted item/qty/location and asks user to confirm or deny.
Confirmation can be via touch (buttons) or voice (handled by AppController).

Layout (1024 x 600 landscape):
  - Header: "I heard:" / "Removing:"
  - Key-value table: Item / Quantity / Location
  - Hint label: "Say 'yes' to confirm or 'no' to cancel"
  - Two full-width buttons: [Confirm]  [Deny]
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.theme import (
    COLOR_BACKGROUND,
    COLOR_BORDER,
    COLOR_SURFACE,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_WHITE,
    FONT_BODY,
    FONT_SMALL,
    FONT_TITLE,
    MARGIN,
    PADDING,
    STYLE_CONFIRM_BUTTON,
    STYLE_DENY_BUTTON,
    STYLE_TABLE,
)
from app.ui.widgets.snowflake_widget import SnowflakeWidget


class ConfirmationScreen(QWidget):
    confirmed = pyqtSignal()
    denied    = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConfirmationScreen")
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._build_ui()

        # Snowflake overlay — shown in bottom-left when mic is recording
        self._snowflake = SnowflakeWidget(self)
        self._snowflake.move(8, 544)   # updated by resizeEvent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_snowflake(self, status: str = "Listening…") -> None:
        self._snowflake.set_status(status)
        self._snowflake.start()

    def hide_snowflake(self) -> None:
        self._snowflake.stop()

    def set_voice_hint(self, text: str) -> None:
        """Update the voice hint label (e.g. countdown or 'Listening now')."""
        self._voice_hint.setText(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        margin = 8
        self._snowflake.move(margin, self.height() - self._snowflake.height() - margin)

    def populate(
        self,
        intent_type: str,      # "ADD" or "REMOVE"
        item_name: str,
        quantity: str,
        location_display: str,
    ) -> None:
        """Fill the table with parsed intent data."""
        verb = "Adding" if intent_type == "ADD" else "Removing"
        self._header.setText(f"{verb}:")

        # Reset voice hint to default; AppController will update it when mic opens
        self._voice_hint.setText("Say  'yes'  to confirm  or  'no'  to cancel")

        rows = [
            ("Item",     item_name),
            ("Quantity", quantity or "—"),
            ("Location", location_display or "—"),
        ]
        self._table.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            key_item = QTableWidgetItem(key)
            key_item.setForeground(QColor(COLOR_TEXT_SECONDARY))
            key_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

            val_item = QTableWidgetItem(value)
            val_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

            self._table.setItem(row, 0, key_item)
            self._table.setItem(row, 1, val_item)

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        outer.setSpacing(PADDING)

        # Header label
        self._header = QLabel("I heard:")
        header_font = QFont()
        header_font.setPointSize(FONT_TITLE)
        header_font.setBold(True)
        self._header.setFont(header_font)
        self._header.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        self._header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(self._header)

        # Key-value table
        self._table = QTableWidget(3, 2)
        self._table.setStyleSheet(STYLE_TABLE)
        self._table.horizontalHeader().hide()
        self._table.verticalHeader().hide()
        self._table.setShowGrid(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setFixedHeight(160)
        self._table.setStyleSheet(
            STYLE_TABLE + f"""
            QTableWidget {{
                background-color: {COLOR_SURFACE};
                border-radius: 8px;
                border: 1px solid {COLOR_BORDER};
            }}
        """
        )
        outer.addWidget(self._table)

        outer.addStretch(1)

        # Voice hint label (text updated dynamically by AppController)
        self._voice_hint = QLabel("Say  'yes'  to confirm  or  'no'  to cancel")
        self._voice_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hint_font = QFont()
        hint_font.setPointSize(FONT_SMALL)
        hint_font.setItalic(True)
        self._voice_hint.setFont(hint_font)
        self._voice_hint.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        outer.addWidget(self._voice_hint)

        outer.addSpacing(PADDING)

        # Confirm / Deny buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(PADDING)

        self._confirm_btn = QPushButton("Confirm")
        self._confirm_btn.setStyleSheet(STYLE_CONFIRM_BUTTON)
        self._confirm_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._confirm_btn.clicked.connect(self.confirmed)

        self._deny_btn = QPushButton("Deny")
        self._deny_btn.setStyleSheet(STYLE_DENY_BUTTON)
        self._deny_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._deny_btn.clicked.connect(self.denied)

        btn_row.addWidget(self._confirm_btn)
        btn_row.addWidget(self._deny_btn)
        outer.addLayout(btn_row)
