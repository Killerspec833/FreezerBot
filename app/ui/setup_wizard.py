"""
SetupWizard — first-boot configuration flow.

Steps:
  0  Welcome
  1  Wake word selection (touch list, 4 options)
  2  Storage locations review (read-only)
  3  System check (auto: WiFi, wake word engine, API keys)
  4  Complete

Emits setup_complete(dict) with:
  { "wake_word": str, "wake_word_model": str }
"""

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config_manager import ConfigManager
from app.core.theme import (
    COLOR_BACKGROUND,
    COLOR_BORDER,
    COLOR_CONFIRM_GREEN,
    COLOR_SURFACE,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_WHITE,
    FONT_BODY,
    FONT_SMALL,
    FONT_TITLE,
    MARGIN,
    PADDING,
    STYLE_CONFIRM_BUTTON,
    STYLE_NEUTRAL_BUTTON,
)
from app.services.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Wake word definitions
# Each entry: (display_name, ppn_filename)
# ---------------------------------------------------------------------------
WAKE_WORDS: list[tuple[str, str]] = [
    ("Hey Jarvis",  "hey_jarvis"),
    ("Alexa",       "alexa"),
    ("Hey Mycroft", "hey_mycroft"),
    ("Hey Rhasspy", "hey_rhasspy"),
]


# ---------------------------------------------------------------------------
# Background thread for system checks
# ---------------------------------------------------------------------------

class _CheckThread(QThread):
    results_ready = pyqtSignal(dict)

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg

    def run(self) -> None:
        from app.services.connectivity_checker import ConnectivityChecker
        checker = ConnectivityChecker(self._cfg)
        results = checker.run_all()
        self.results_ready.emit(results)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_title(text: str) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(FONT_TITLE)
    font.setBold(True)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
    lbl.setWordWrap(True)
    return lbl


def _make_body(text: str, secondary: bool = False) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(FONT_BODY)
    lbl.setFont(font)
    color = COLOR_TEXT_SECONDARY if secondary else COLOR_TEXT_WHITE
    lbl.setStyleSheet(f"color: {color};")
    lbl.setWordWrap(True)
    return lbl


def _make_small(text: str) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(FONT_SMALL)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
    lbl.setWordWrap(True)
    return lbl


def _nav_buttons(
    back_cb=None,
    next_cb=None,
    next_label: str = "Next",
    next_enabled: bool = True,
) -> tuple[QHBoxLayout, QPushButton | None, QPushButton]:
    row = QHBoxLayout()
    row.setSpacing(PADDING)

    back_btn = None
    if back_cb:
        back_btn = QPushButton("Back")
        back_btn.setStyleSheet(STYLE_NEUTRAL_BUTTON)
        back_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        back_btn.clicked.connect(back_cb)
        row.addWidget(back_btn)

    next_btn = QPushButton(next_label)
    next_btn.setStyleSheet(STYLE_CONFIRM_BUTTON)
    next_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    next_btn.setEnabled(next_enabled)
    if next_cb:
        next_btn.clicked.connect(next_cb)
    row.addWidget(next_btn)

    return row, back_btn, next_btn


# ---------------------------------------------------------------------------
# Step 0 — Welcome
# ---------------------------------------------------------------------------

class _WelcomeStep(QWidget):
    next_requested = pyqtSignal()

    _SWIPE_THRESHOLD = 40  # px — minimum movement to count as a swipe

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN * 2, MARGIN, MARGIN)
        layout.setSpacing(PADDING)

        layout.addStretch(2)

        # Icon placeholder (large coloured circle)
        icon = QLabel("❄")
        icon.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        icon_font = QFont()
        icon_font.setPointSize(72)
        icon.setFont(icon_font)
        icon.setStyleSheet("color: #1565C0;")
        layout.addWidget(icon)

        layout.addSpacing(PADDING)

        title = _make_title("Welcome to\nFreezerbot")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        layout.addSpacing(PADDING)

        sub = _make_body(
            "Your voice-controlled\nfreezer inventory system.",
            secondary=True,
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(sub)

        layout.addSpacing(PADDING)

        swipe_hint = QLabel("swipe to continue")
        swipe_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        swipe_font = QFont()
        swipe_font.setPointSize(FONT_SMALL)
        swipe_hint.setFont(swipe_font)
        swipe_hint.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(swipe_hint)

        layout.addStretch(3)

    def mousePressEvent(self, event) -> None:
        self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._press_pos is not None:
            delta = event.position().toPoint() - self._press_pos
            if (abs(delta.x()) >= self._SWIPE_THRESHOLD or
                    abs(delta.y()) >= self._SWIPE_THRESHOLD):
                self.next_requested.emit()
        self._press_pos = None
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# Step 1 — Wake word selection
# ---------------------------------------------------------------------------

class _WakeWordStep(QWidget):
    next_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._selected: tuple[str, str] | None = None  # (display, ppn)
        self._next_btn: QPushButton | None = None
        self._build()

    @property
    def selected(self) -> tuple[str, str] | None:
        return self._selected

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.setSpacing(PADDING)

        layout.addWidget(_make_title("Choose Your\nWake Word"))
        layout.addWidget(_make_small("Tap the name you want to use to activate Freezerbot."))

        # List widget
        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_TEXT_WHITE};
                font-size: {FONT_BODY}pt;
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            QListWidget::item {{
                padding: 14px {MARGIN}px;
                border-bottom: 1px solid {COLOR_BORDER};
            }}
            QListWidget::item:selected {{
                background-color: #1565C0;
                color: {COLOR_TEXT_WHITE};
            }}
        """)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)

        for display, ppn in WAKE_WORDS:
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, ppn)
            font = QFont()
            font.setPointSize(FONT_BODY)
            item.setFont(font)
            self._list.addItem(item)

        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        nav, _, self._next_btn = _nav_buttons(
            back_cb=self.back_requested.emit,
            next_cb=self.next_requested.emit,
            next_enabled=False,
        )
        layout.addLayout(nav)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._selected = (item.text(), item.data(Qt.ItemDataRole.UserRole))
        if self._next_btn:
            self._next_btn.setEnabled(True)
        log.debug("Wake word selected: %s", self._selected[0])


# ---------------------------------------------------------------------------
# Step 2 — Storage locations review
# ---------------------------------------------------------------------------

class _LocationsStep(QWidget):
    next_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, cfg_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._cfg = cfg_manager
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.setSpacing(PADDING)

        layout.addWidget(_make_title("Storage\nLocations"))
        layout.addWidget(_make_small(
            "These are the freezer locations Freezerbot knows about."
        ))

        # Scrollable area for location cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        cards_widget = QWidget()
        cards_widget.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        cards_layout = QVBoxLayout(cards_widget)
        cards_layout.setSpacing(PADDING)
        cards_layout.setContentsMargins(0, 0, 0, 0)

        for key, loc in self._cfg.config.locations.items():
            card = self._make_location_card(loc.display_name, loc.aliases)
            cards_layout.addWidget(card)

        cards_layout.addStretch()
        scroll.setWidget(cards_widget)
        layout.addWidget(scroll)

        nav, _, _ = _nav_buttons(
            back_cb=self.back_requested.emit,
            next_cb=self.next_requested.emit,
        )
        layout.addLayout(nav)

    @staticmethod
    def _make_location_card(display_name: str, aliases: list[str]) -> QWidget:
        card = QWidget()
        card.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_SURFACE};
                border-radius: 8px;
                border: 1px solid {COLOR_BORDER};
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        cl.setSpacing(4)

        name_lbl = QLabel(display_name)
        name_font = QFont()
        name_font.setPointSize(FONT_BODY)
        name_font.setBold(True)
        name_lbl.setFont(name_font)
        name_lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE}; border: none;")
        cl.addWidget(name_lbl)

        say_text = "Say:  " + "  ·  ".join(f'"{a}"' for a in aliases)
        say_lbl = QLabel(say_text)
        say_font = QFont()
        say_font.setPointSize(FONT_SMALL)
        say_lbl.setFont(say_font)
        say_lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; border: none;")
        say_lbl.setWordWrap(True)
        cl.addWidget(say_lbl)

        return card


# ---------------------------------------------------------------------------
# Step 3 — System check
# ---------------------------------------------------------------------------

_CHECK_LABELS = {
    "wifi":       "Internet connection",
    "wake_word":  "Wake word engine",
    "groq":       "Groq API key",
    "gemini":     "Gemini API key",
}


class _SystemCheckStep(QWidget):
    next_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, cfg_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._cfg = cfg_manager
        self._model_name: str = ""
        self._thread: _CheckThread | None = None
        self._next_btn: QPushButton | None = None
        self._retry_btn: QPushButton | None = None
        self._row_labels: dict[str, QLabel] = {}
        self._build()

    def set_model_name(self, model_name: str) -> None:
        self._model_name = model_name

    def on_show(self) -> None:
        self._run_checks()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.setSpacing(PADDING)

        layout.addWidget(_make_title("System Check"))
        layout.addWidget(_make_small("Verifying your setup…"))

        # Status rows
        rows_widget = QWidget()
        rows_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {COLOR_SURFACE};
                border-radius: 8px;
                border: 1px solid {COLOR_BORDER};
            }}
        """)
        rows_layout = QVBoxLayout(rows_widget)
        rows_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        rows_layout.setSpacing(8)

        for key, label in _CHECK_LABELS.items():
            row = QHBoxLayout()
            name_lbl = QLabel(label)
            name_font = QFont()
            name_font.setPointSize(FONT_SMALL)
            name_lbl.setFont(name_font)
            name_lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE}; border: none;")

            status_lbl = QLabel("…")
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            status_font = QFont()
            status_font.setPointSize(FONT_SMALL)
            status_lbl.setFont(status_font)
            status_lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; border: none;")
            status_lbl.setMinimumWidth(180)
            status_lbl.setWordWrap(True)

            row.addWidget(name_lbl)
            row.addWidget(status_lbl)
            rows_layout.addLayout(row)
            self._row_labels[key] = status_lbl

        layout.addWidget(rows_widget)
        layout.addStretch()

        # Retry button
        self._retry_btn = QPushButton("Retry")
        self._retry_btn.setStyleSheet(STYLE_NEUTRAL_BUTTON)
        self._retry_btn.setVisible(False)
        self._retry_btn.clicked.connect(self._run_checks)
        layout.addWidget(self._retry_btn)

        nav, _, self._next_btn = _nav_buttons(
            back_cb=self.back_requested.emit,
            next_cb=self.next_requested.emit,
            next_enabled=False,
        )
        layout.addLayout(nav)

    def _run_checks(self) -> None:
        if self._next_btn:
            self._next_btn.setEnabled(False)
        if self._retry_btn:
            self._retry_btn.setVisible(False)

        for lbl in self._row_labels.values():
            lbl.setText("checking…")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; border: none;")

        self._thread = _CheckThread(self._cfg.config)
        self._thread.results_ready.connect(self._on_results)
        self._thread.start()

    def _on_results(self, results: dict) -> None:
        all_ok = True
        for key, result in results.items():
            lbl = self._row_labels.get(key)
            if not lbl:
                continue
            if result.ok:
                lbl.setText("✓  " + result.message)
                lbl.setStyleSheet(f"color: {COLOR_CONFIRM_GREEN}; border: none;")
            else:
                lbl.setText("✗  " + result.message)
                lbl.setStyleSheet(f"color: #EF5350; border: none;")
                all_ok = False

        if self._next_btn:
            self._next_btn.setEnabled(all_ok)
        if self._retry_btn:
            self._retry_btn.setVisible(not all_ok)

        if all_ok:
            log.info("All system checks passed.")
        else:
            log.warning("One or more system checks failed.")


# ---------------------------------------------------------------------------
# Step 4 — Complete
# ---------------------------------------------------------------------------

class _CompleteStep(QWidget):
    finish_requested = pyqtSignal()
    back_requested   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._build()

    def set_wake_word(self, name: str) -> None:
        self._wake_word_lbl.setText(f"Wake word:  {name}")

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN * 2, MARGIN, MARGIN)
        layout.setSpacing(PADDING)

        layout.addStretch(2)

        check = QLabel("✓")
        check.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        check_font = QFont()
        check_font.setPointSize(72)
        check.setFont(check_font)
        check.setStyleSheet(f"color: {COLOR_CONFIRM_GREEN};")
        layout.addWidget(check)

        layout.addSpacing(PADDING)

        title = _make_title("You're all set!")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        layout.addSpacing(PADDING)

        self._wake_word_lbl = _make_body("", secondary=True)
        self._wake_word_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._wake_word_lbl)

        layout.addStretch(3)

        nav, _, start_btn = _nav_buttons(
            back_cb=self.back_requested.emit,
            next_cb=self.finish_requested.emit,
            next_label="Start Freezerbot",
        )
        layout.addLayout(nav)


# ---------------------------------------------------------------------------
# SetupWizard — orchestrates the steps
# ---------------------------------------------------------------------------

class SetupWizard(QWidget):
    setup_complete = pyqtSignal(dict)

    # Step indices
    _STEP_WELCOME   = 0
    _STEP_WAKEWORD  = 1
    _STEP_LOCATIONS = 2
    _STEP_SYSCHECK  = 3
    _STEP_COMPLETE  = 4

    def __init__(self, cfg_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.setObjectName("SetupWizard")
        self.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        self._cfg = cfg_manager
        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Step indicator bar
        self._step_bar = _StepBar(total=5)
        layout.addWidget(self._step_bar)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Instantiate steps
        self._welcome   = _WelcomeStep()
        self._wakeword  = _WakeWordStep()
        self._locations = _LocationsStep(self._cfg)
        self._syscheck  = _SystemCheckStep(self._cfg)
        self._complete  = _CompleteStep()

        for step in (
            self._welcome,
            self._wakeword,
            self._locations,
            self._syscheck,
            self._complete,
        ):
            self._stack.addWidget(step)

        # Wire navigation signals
        self._welcome.next_requested.connect(
            lambda: self._go_to(self._STEP_WAKEWORD)
        )
        self._wakeword.next_requested.connect(self._on_wakeword_next)
        self._wakeword.back_requested.connect(
            lambda: self._go_to(self._STEP_WELCOME)
        )
        self._locations.next_requested.connect(
            lambda: self._go_to(self._STEP_SYSCHECK)
        )
        self._locations.back_requested.connect(
            lambda: self._go_to(self._STEP_WAKEWORD)
        )
        self._syscheck.next_requested.connect(
            lambda: self._go_to(self._STEP_COMPLETE)
        )
        self._syscheck.back_requested.connect(
            lambda: self._go_to(self._STEP_LOCATIONS)
        )
        self._complete.finish_requested.connect(self._on_finish)
        self._complete.back_requested.connect(
            lambda: self._go_to(self._STEP_SYSCHECK)
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to(self, step_index: int) -> None:
        current = self._stack.currentWidget()
        if hasattr(current, "on_hide"):
            current.on_hide()

        self._stack.setCurrentIndex(step_index)
        self._step_bar.set_step(step_index)

        incoming = self._stack.currentWidget()
        if hasattr(incoming, "on_show"):
            incoming.on_show()

        log.debug("Setup wizard: step %d", step_index)

    def _on_wakeword_next(self) -> None:
        selected = self._wakeword.selected
        if not selected:
            return
        display, model_name = selected
        self._syscheck.set_model_name(model_name)
        self._complete.set_wake_word(display)
        self._go_to(self._STEP_LOCATIONS)

    def _on_finish(self) -> None:
        selected = self._wakeword.selected
        if not selected:
            log.error("Finish called with no wake word selected.")
            return
        display, model_name = selected
        result = {
            "wake_word": display,
            "wake_word_model": model_name,
        }
        log.info("Setup wizard complete. Wake word: %s", display)
        self.setup_complete.emit(result)


# ---------------------------------------------------------------------------
# Step indicator bar
# ---------------------------------------------------------------------------

class _StepBar(QWidget):
    """Row of dots showing current step position."""

    def __init__(self, total: int, parent=None):
        super().__init__(parent)
        self._total = total
        self._labels: list[QLabel] = []
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(MARGIN, 4, MARGIN, 4)
        layout.setSpacing(8)
        layout.addStretch()
        for _ in range(total):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {COLOR_BORDER}; font-size: 10pt;")
            layout.addWidget(dot)
            self._labels.append(dot)
        layout.addStretch()
        self.set_step(0)

    def set_step(self, index: int) -> None:
        for i, lbl in enumerate(self._labels):
            lbl.setStyleSheet(
                f"color: {COLOR_TEXT_WHITE}; font-size: 10pt;"
                if i == index
                else f"color: {COLOR_BORDER}; font-size: 10pt;"
            )
