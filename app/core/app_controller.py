"""
AppController — central orchestrator.

Phase 2 skeleton: handles touch-based state transitions and the
5-minute inactivity timer. Audio and intent subsystems are wired in
later phases.
"""

from PyQt6.QtCore import QObject, QTimer

from app.core.config_manager import ConfigManager
from app.core.path_resolver import get_db_path
from app.core.state_machine import AppState, StateMachine
from app.database.db_manager import DatabaseManager
from app.database.fuzzy_search import FuzzySearch
from app.services.logger import get_logger

log = get_logger(__name__)


class AppController(QObject):
    def __init__(
        self,
        cfg_manager: ConfigManager,
        state_machine: StateMachine,
        window,           # MainWindow — typed as Any to avoid circular import
        parent=None,
    ):
        super().__init__(parent)
        self._cfg = cfg_manager
        self._sm  = state_machine
        self._win = window

        # Database
        self._db = DatabaseManager(get_db_path())
        self._db.open()
        self._fuzzy = FuzzySearch(
            self._db,
            default_threshold=cfg_manager.config.fuzzy_search.similarity_threshold,
        )

        # Inactivity timer — fires after sleep_timeout_seconds of no interaction
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self._on_inactivity)
        timeout_ms = self._cfg.config.ui.sleep_timeout_seconds * 1000
        self._inactivity_timer.start(timeout_ms)

        # Holds the most recent parsed intent while waiting for confirmation
        self._pending_intent = None

        self._connect_signals()
        log.info("AppController initialised. State: %s", self._sm.current.name)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        win = self._win

        # Sleep screen — touch wakes the system
        win.sleep_screen.touch_detected.connect(self._on_touch_wake)

        # Confirmation screen — touch confirm/deny
        win.confirmation_screen.confirmed.connect(self._on_confirmed)
        win.confirmation_screen.denied.connect(self._on_denied)

        # Inventory screen — close button
        win.inventory_screen.close_requested.connect(self._on_inventory_close)

        # Setup wizard — completion
        win.setup_wizard.setup_complete.connect(self._on_setup_complete)

    # ------------------------------------------------------------------
    # Inactivity timer
    # ------------------------------------------------------------------

    def reset_inactivity_timer(self) -> None:
        """Call on any user interaction to reset the sleep countdown."""
        timeout_ms = self._cfg.config.ui.sleep_timeout_seconds * 1000
        self._inactivity_timer.start(timeout_ms)

    def _on_inactivity(self) -> None:
        log.info("Inactivity timeout — going to sleep.")
        self._sm.force(AppState.SLEEP)

    # ------------------------------------------------------------------
    # Touch wake
    # ------------------------------------------------------------------

    def _on_touch_wake(self) -> None:
        log.debug("Touch wake detected.")
        self.reset_inactivity_timer()
        if self._sm.current == AppState.SLEEP:
            ok = self._sm.transition(AppState.LISTENING)
            if not ok:
                self._sm.force(AppState.LISTENING)

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def _on_confirmed(self) -> None:
        log.info("User confirmed action.")
        self.reset_inactivity_timer()
        intent = self._pending_intent
        if intent is not None:
            self._execute_intent(intent)
        self._pending_intent = None
        self._sm.transition(AppState.SLEEP)

    def _on_denied(self) -> None:
        log.info("User denied — re-listening.")
        self.reset_inactivity_timer()
        self._sm.transition(AppState.LISTENING)

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def _on_inventory_close(self) -> None:
        log.debug("Inventory screen closed.")
        self.reset_inactivity_timer()
        self._sm.force(AppState.SLEEP)

    # ------------------------------------------------------------------
    # Setup wizard
    # ------------------------------------------------------------------

    def _on_setup_complete(self, config_data: dict) -> None:
        log.info("Setup wizard complete. Saving config.")
        self._cfg.set_wake_word(
            wake_word=config_data.get("wake_word", ""),
            ppn_filename=config_data.get("wake_word_ppn_filename", ""),
        )
        self._cfg.set_setup_complete(True)
        log.info("Config saved. Wake word: %s", config_data.get("wake_word"))
        self._sm.force(AppState.SLEEP)

    # ------------------------------------------------------------------
    # Public hooks for audio pipeline (Phase 6)
    # ------------------------------------------------------------------

    def on_wake_word_detected(self) -> None:
        """Called by WakeWordDetector thread (via Qt queued signal)."""
        self.reset_inactivity_timer()
        if self._sm.current in (AppState.SLEEP, AppState.INVENTORY):
            self._sm.transition(AppState.LISTENING)

    def on_intent_parsed(self, parsed_intent) -> None:
        """Called by IntentParserThread after Gemini returns a result."""
        self.reset_inactivity_timer()
        intent_type = parsed_intent.intent_type.name

        if intent_type == "ADD":
            self._pending_intent = parsed_intent
            loc_display = self._cfg.get_location_display_name(
                parsed_intent.location or ""
            )
            self._win.confirmation_screen.populate(
                intent_type="ADD",
                item_name=parsed_intent.item_name or "",
                quantity=parsed_intent.quantity or "",
                location_display=loc_display,
            )
            self._sm.transition(AppState.CONFIRMING)

        elif intent_type == "REMOVE":
            decision, match = self._fuzzy.find_for_removal(
                parsed_intent.item_name or "",
                location_filter=parsed_intent.location or None,
            )
            if decision == "none":
                log.info("No match for removal: '%s'", parsed_intent.item_name)
                # TTS handled in Phase 6; return to LISTENING
                self._sm.transition(AppState.LISTENING)
                return
            # Store the resolved DB item id on the intent for _execute_intent
            parsed_intent._resolved_item_id = match.item.id
            parsed_intent._resolved_item_name = match.item.item_name
            self._pending_intent = parsed_intent
            loc_display = self._cfg.get_location_display_name(match.item.location)
            self._win.confirmation_screen.populate(
                intent_type="REMOVE",
                item_name=match.item.item_name,
                quantity=match.item.quantity,
                location_display=loc_display,
            )
            self._sm.transition(AppState.CONFIRMING)

        elif intent_type == "QUERY":
            results = self._fuzzy.search_all_locations(
                parsed_intent.item_name or ""
            )
            rows = [
                (r.item.item_name, r.item.quantity, r.item.location)
                for r in results
            ]
            self._win.inventory_screen.load_data(rows, select_location="all")
            self._sm.transition(AppState.INVENTORY)

        elif intent_type == "LIST":
            loc_key = parsed_intent.location or "all"
            if loc_key == "all":
                rows = [
                    (i.item_name, i.quantity, i.location)
                    for i in self._db.get_all_items()
                ]
            else:
                rows = [
                    (i.item_name, i.quantity, i.location)
                    for i in self._db.list_by_location(loc_key)
                ]
            self._win.inventory_screen.load_data(rows, select_location=loc_key)
            self._sm.transition(AppState.INVENTORY)

        elif intent_type == "UNKNOWN":
            log.warning("Unknown intent — staying in LISTENING.")
            # TTS "Sorry, I didn't understand" handled in Phase 6

    def _execute_intent(self, intent) -> None:
        """Write a confirmed ADD or REMOVE to the database."""
        intent_type = intent.intent_type.name

        if intent_type == "ADD":
            item = self._db.add_item(
                item_name=intent.item_name or "",
                quantity=intent.quantity or "1",
                location=intent.location or "",
            )
            self._db.log_action(
                action="ADD",
                item_name=item.item_name,
                quantity=item.quantity,
                location=item.location,
                transcript=getattr(intent, "raw_transcript", None),
            )
            log.info("DB ADD confirmed: id=%d '%s'", item.id, item.item_name)

        elif intent_type == "REMOVE":
            item_id = getattr(intent, "_resolved_item_id", None)
            if item_id is not None:
                self._db.remove_item(item_id)
                self._db.log_action(
                    action="REMOVE",
                    item_name=getattr(intent, "_resolved_item_name", ""),
                    quantity=intent.quantity,
                    location=intent.location,
                    transcript=getattr(intent, "raw_transcript", None),
                )
                log.info("DB REMOVE confirmed: id=%d", item_id)

    def on_confirm_voice(self) -> None:
        """Called when voice CONFIRM intent is detected while in CONFIRMING."""
        if self._sm.current == AppState.CONFIRMING:
            self._on_confirmed()

    def on_deny_voice(self) -> None:
        """Called when voice DENY intent is detected while in CONFIRMING."""
        if self._sm.current == AppState.CONFIRMING:
            self._on_denied()
