"""
InventoryScreen — scrollable inventory table with location tabs.

Layout (1024 x 600 landscape):
  - LocationTabBar across the top (All | Basement Freezer | Kitchen Freezer | Fridge)
  - QTableWidget filling the remaining height (Item | Qty | Location)
  - Bottom bar: idle text  OR  [snowflake] + command list side-by-side in layout
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
    STYLE_TABLE,
)
from app.ui.widgets.location_tab import LocationTabBar
from app.ui.widgets.snowflake_widget import SnowflakeWidget


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

    def show_snowflake(self, status: str = "Listening…") -> None:
        """Show the animated snowflake indicator (mic is active)."""
        self._snowflake.set_status(status)
        self._snowflake.start()
        self._idle_footer.hide()
        self._active_bar.show()

    def hide_snowflake(self) -> None:
        """Hide the snowflake indicator."""
        self._snowflake.stop()
        self._active_bar.hide()
        self._idle_footer.show()

    def set_mic_status(self, text: str) -> None:
        """Update the status text next to the snowflake (shown only when active)."""
        self._snowflake.set_status(text)

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

        # ---- Idle footer (shown when mic is off) ----
        self._idle_footer = QLabel("Tap or speak to get started")
        self._idle_footer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        idle_font = QFont()
        idle_font.setPointSize(FONT_SMALL)
        self._idle_footer.setFont(idle_font)
        self._idle_footer.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; padding-bottom: 8px;"
        )
        layout.addWidget(self._idle_footer)

        # ---- Active bar (shown when mic is on): [snowflake] [command list] ----
        # Embedding the snowflake directly in the layout row avoids any
        # floating-overlay z-order issues on bare X11 (no compositor).
        self._active_bar = QWidget()
        self._active_bar.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        bar_layout = QHBoxLayout(self._active_bar)
        bar_layout.setContentsMargins(8, 0, 8, 8)
        bar_layout.setSpacing(8)

        self._snowflake = SnowflakeWidget(self._active_bar)
        bar_layout.addWidget(
            self._snowflake,
            0,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        )

        self._cmd_panel = QLabel(
            "Add [item] to [location]  \u2022  Remove [item]  \u2022  "
            "What\u2019s in [location]?  \u2022  List [location]  \u2022  Done / Finished"
        )
        cmd_font = QFont()
        cmd_font.setPointSize(FONT_SMALL)
        self._cmd_panel.setFont(cmd_font)
        self._cmd_panel.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        self._cmd_panel.setWordWrap(True)
        self._cmd_panel.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        bar_layout.addWidget(self._cmd_panel, 1)

        self._active_bar.hide()
        layout.addWidget(self._active_bar)

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
