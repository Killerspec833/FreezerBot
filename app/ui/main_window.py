"""
MainWindow — top-level QMainWindow.

Owns a QStackedWidget containing all screens.
Switches the active screen in response to state_machine.state_changed.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from app.core.config_manager import ConfigManager
from app.core.state_machine import AppState, StateMachine
from app.core.theme import SCREEN_H, SCREEN_W, STYLE_MAIN_WINDOW
from app.ui.confirmation_screen import ConfirmationScreen
from app.ui.inventory_screen import InventoryScreen
from app.ui.listening_screen import ListeningScreen
from app.ui.setup_wizard import SetupWizard
from app.ui.sleep_screen import SleepScreen


# Fixed indices in the QStackedWidget
_IDX_SLEEP        = 0
_IDX_LISTENING    = 1
_IDX_CONFIRMING   = 2
_IDX_INVENTORY    = 3
_IDX_SETUP        = 4


class MainWindow(QMainWindow):
    def __init__(
        self,
        cfg_manager: ConfigManager,
        state_machine: StateMachine,
        parent=None,
    ):
        super().__init__(parent)
        self._cfg = cfg_manager
        self._sm  = state_machine

        self.setWindowTitle("Freezerbot")
        self.setFixedSize(SCREEN_W, SCREEN_H)
        self.setStyleSheet(STYLE_MAIN_WINDOW)

        # Remove window frame for kiosk mode
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )

        self._build_stack()

        # React to state changes
        self._sm.state_changed.connect(self._on_state_changed)

        # Show the correct initial screen
        self._on_state_changed(self._sm.current)

    # ------------------------------------------------------------------
    # Screen accessors (used by AppController to populate data)
    # ------------------------------------------------------------------

    @property
    def sleep_screen(self) -> SleepScreen:
        return self._sleep

    @property
    def listening_screen(self) -> ListeningScreen:
        return self._listening

    @property
    def confirmation_screen(self) -> ConfirmationScreen:
        return self._confirmation

    @property
    def inventory_screen(self) -> InventoryScreen:
        return self._inventory

    @property
    def setup_wizard(self) -> SetupWizard:
        return self._setup

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_stack(self) -> None:
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        location_names = {
            k: v.display_name
            for k, v in self._cfg.config.locations.items()
        }

        self._sleep        = SleepScreen(self)
        self._listening    = ListeningScreen(self)
        self._confirmation = ConfirmationScreen(self)
        self._inventory    = InventoryScreen(location_names, self)
        self._setup        = SetupWizard(self._cfg, self)

        # Order must match _IDX_* constants
        for screen in (
            self._sleep,
            self._listening,
            self._confirmation,
            self._inventory,
            self._setup,
        ):
            self._stack.addWidget(screen)

    # ------------------------------------------------------------------
    # State → screen mapping
    # ------------------------------------------------------------------

    def _on_state_changed(self, state: AppState) -> None:
        mapping = {
            AppState.SLEEP:      _IDX_SLEEP,
            AppState.LISTENING:  _IDX_LISTENING,
            AppState.CONFIRMING: _IDX_CONFIRMING,
            AppState.INVENTORY:  _IDX_INVENTORY,
            AppState.SETUP:      _IDX_SETUP,
        }
        idx = mapping.get(state, _IDX_SLEEP)

        # Notify outgoing screen
        current_widget = self._stack.currentWidget()
        if hasattr(current_widget, "on_hide"):
            current_widget.on_hide()

        self._stack.setCurrentIndex(idx)

        # Notify incoming screen
        incoming = self._stack.currentWidget()
        if hasattr(incoming, "on_show"):
            incoming.on_show()
