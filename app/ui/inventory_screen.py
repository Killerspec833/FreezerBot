"""
InventoryScreen — scrollable inventory table with location tabs.

Layout (480 x 800 portrait):
  - LocationTabBar across the top (All | Basement Freezer | Kitchen Freezer | Fridge)
  - QTableWidget filling the remaining height (Item | Qty | Location)
  - Close button pinned at the bottom
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.theme import (
    COLOR_BACKGROUND,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_WHITE,
    FONT_BODY,
    FONT_SMALL,
    MARGIN,
    PADDING,
    STYLE_NEUTRAL_BUTTON,
    STYLE_TABLE,
)
from app.ui.widgets.location_tab import LocationTabBar


class InventoryScreen(QWidget):
    close_requested = pyqtSignal()

    def __init__(self, location_names: dict[str, str], parent=None):
        """
        location_names: {canonical_key: display_name, ...}
        """
        super().__init__(parent)
        self.setObjectName("InventoryScreen")
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._location_names = location_names
        self._all_rows: list[tuple] = []   # (item_name, quantity, location_key)
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_data(self, rows: list[tuple], select_location: str = "all") -> None:
        """
        rows: list of (item_name, quantity, location_canonical_key)
        select_location: tab to activate after loading
        """
        self._all_rows = rows
        self._tab_bar.select(select_location)
        self._apply_filter(select_location)

    def select_location(self, key: str) -> None:
        self._tab_bar.select(key)
        self._apply_filter(key)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, MARGIN)
        layout.setSpacing(0)

        # Location tab bar
        self._tab_bar = LocationTabBar(
            {k: v for k, v in self._location_names.items()},
            parent=self,
        )
        self._tab_bar.location_selected.connect(self._apply_filter)
        layout.addWidget(self._tab_bar)

        # Row count label
        self._count_label = QLabel("")
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        count_font = QFont()
        count_font.setPointSize(FONT_SMALL)
        self._count_label.setFont(count_font)
        self._count_label.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; padding-right: {MARGIN}px; padding-top: 4px;"
        )
        layout.addWidget(self._count_label)

        # Table
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Item", "Qty", "Location"])
        self._table.setStyleSheet(STYLE_TABLE)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().hide()
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            STYLE_TABLE + "QTableWidget { alternate-background-color: #252525; }"
        )
        # Enable kinetic (touch) scrolling
        self._table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        layout.addWidget(self._table)

        layout.addSpacing(PADDING)

        # Close button
        self._close_btn = QPushButton("Close")
        self._close_btn.setStyleSheet(STYLE_NEUTRAL_BUTTON)
        self._close_btn.setContentsMargins(MARGIN, 0, MARGIN, 0)
        self._close_btn.clicked.connect(self.close_requested)
        layout.addWidget(
            self._close_btn,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        self._close_btn.setFixedWidth(200)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_filter(self, location_key: str) -> None:
        if location_key == "all":
            visible = self._all_rows
        else:
            visible = [r for r in self._all_rows if r[2] == location_key]

        self._table.setRowCount(0)
        for item_name, quantity, loc_key in visible:
            row = self._table.rowCount()
            self._table.insertRow(row)

            name_item = QTableWidgetItem(item_name.title())
            qty_item  = QTableWidgetItem(quantity)
            loc_item  = QTableWidgetItem(
                self._location_names.get(loc_key, loc_key)
            )

            for cell in (name_item, qty_item, loc_item):
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                font = QFont()
                font.setPointSize(FONT_SMALL)
                cell.setFont(font)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, qty_item)
            self._table.setItem(row, 2, loc_item)

        count = len(visible)
        self._count_label.setText(f"{count} item{'s' if count != 1 else ''}")
