"""
Freezerbot — entry point.

Startup sequence:
  1. Resolve USB stick path
  2. Setup logger
  3. Load config
  4. Launch Qt application
  5. Show setup wizard (first boot) or normal operation
"""

import os
import sys

# Ensure the app/ directory is on the Python path when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from app.core.path_resolver import get_usb_root, get_config_path, get_log_path
from app.core.config_manager import ConfigManager
from app.core.state_machine import StateMachine, AppState
from app.services.logger import setup_logger, get_logger


def main() -> int:
    # ------------------------------------------------------------------
    # 1. Verify USB stick is accessible
    # ------------------------------------------------------------------
    try:
        usb_root = get_usb_root()
    except RuntimeError as e:
        # Qt not yet running — print to stderr and exit
        print(f"[FATAL] {e}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 2. Logger (needs log dir from USB stick)
    # ------------------------------------------------------------------
    setup_logger(get_log_path())
    log = get_logger(__name__)
    log.info("Freezerbot starting. USB root: %s", usb_root)

    # ------------------------------------------------------------------
    # 3. Config
    # ------------------------------------------------------------------
    try:
        cfg_manager = ConfigManager()
        cfg_manager.load()
    except FileNotFoundError as e:
        log.critical("Config not found: %s", e)
        return 1
    except Exception as e:
        log.critical("Failed to load config: %s", e)
        return 1

    # ------------------------------------------------------------------
    # 4. Qt application
    # ------------------------------------------------------------------
    # Hide mouse cursor on touchscreen kiosk
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QApplication(sys.argv)
    app.setOverrideCursor(Qt.CursorShape.BlankCursor)

    # ------------------------------------------------------------------
    # 5. State machine + main window
    # ------------------------------------------------------------------
    initial_state = (
        AppState.SETUP if not cfg_manager.is_setup_complete() else AppState.SLEEP
    )
    state_machine = StateMachine(initial=initial_state)

    # Import here to avoid circular imports before Qt is initialised
    from app.ui.main_window import MainWindow
    from app.core.app_controller import AppController

    window = MainWindow(cfg_manager, state_machine)
    controller = AppController(cfg_manager, state_machine, window)  # noqa: F841

    window.showFullScreen()

    log.info(
        "UI launched. Initial state: %s. Setup complete: %s",
        initial_state.name,
        cfg_manager.is_setup_complete(),
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
