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

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt

from app.core.path_resolver import get_usb_root, get_config_path, get_log_path
from app.core.config_manager import ConfigManager
from app.core.state_machine import StateMachine, AppState
from app.services.logger import setup_logger, get_logger


def _show_startup_error(message: str, detail: str = "") -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    screen = QWidget()
    screen.setWindowTitle("Freezerbot Startup Error")

    layout = QVBoxLayout(screen)

    title = QLabel(message)
    title.setWordWrap(True)
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    if detail:
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(detail_label)

    hint = QLabel(
        "Fix the problem, then restart Freezerbot.\nCheck the USB stick, network, and config files."
    )
    hint.setWordWrap(True)
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(hint)

    close_btn = QPushButton("Exit")
    close_btn.clicked.connect(app.quit)
    layout.addWidget(close_btn)

    screen.resize(760, 420)
    screen.show()
    return app.exec()


def main() -> int:
    # ------------------------------------------------------------------
    # 1. Verify USB stick is accessible
    # ------------------------------------------------------------------
    try:
        usb_root = get_usb_root()
    except RuntimeError as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return _show_startup_error("USB stick not found.", str(e))

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
        return _show_startup_error("Configuration file missing.", str(e))
    except Exception as e:
        log.critical("Failed to load config: %s", e)
        return _show_startup_error(
            "Freezerbot could not load its configuration.",
            str(e),
        )

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

    exit_code = app.exec()
    controller.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
