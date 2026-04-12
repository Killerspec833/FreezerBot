"""
AppController — central orchestrator.

Owns and connects all subsystems:
  - StateMachine (state transitions)
  - DatabaseManager + FuzzySearch
  - WakeWordDetector (always-on thread)
  - Recorder (one-shot per utterance)
  - STTThread (Groq Whisper, one-shot per utterance)
  - IntentParserThread (Gemini, one-shot per utterance)
  - TTSEngine (queue-based speech output)
  - Inactivity timer (5-min sleep)
"""

import os

from PyQt6.QtCore import QObject, QTimer

from app.audio.recorder import Recorder
from app.audio.speech_to_text import STTThread
from app.audio.tts_engine import TTSEngine
from app.audio.wake_word_detector import WakeWordDetector
from app.core.config_manager import ConfigManager
from app.core.path_resolver import get_db_path
from app.core.state_machine import AppState, StateMachine
from app.database.db_manager import DatabaseManager
from app.database.fuzzy_search import FuzzySearch
from app.intent.intent_parser import IntentParserThread
from app.intent.models import IntentType
from app.services.logger import get_logger

log = get_logger(__name__)


class AppController(QObject):
    def __init__(
        self,
        cfg_manager: ConfigManager,
        state_machine: StateMachine,
        window,
        parent=None,
    ):
        super().__init__(parent)
        self._cfg = cfg_manager
        self._sm  = state_machine
        self._win = window

        # --- Database ---
        self._db = DatabaseManager(get_db_path())
        self._db.open()
        self._fuzzy = FuzzySearch(
            self._db,
            default_threshold=cfg_manager.config.fuzzy_search.similarity_threshold,
        )

        # --- Inactivity timer ---
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self._on_inactivity)
        self._inactivity_timer.start(cfg_manager.config.ui.sleep_timeout_seconds * 1000)

        # --- Pending confirmation state ---
        self._pending_intent = None

        # --- Thread references (prevent GC) ---
        self._wake_detector: WakeWordDetector | None = None
        self._recorder:      Recorder | None = None
        self._stt_thread:    STTThread | None = None
        self._intent_thread: IntentParserThread | None = None

        # --- TTS engine (always running) ---
        self._tts = TTSEngine(parent=self)
        self._tts.start()

        self._connect_ui_signals()

        # Start audio pipeline only if setup is complete
        if cfg_manager.is_setup_complete():
            self._start_audio()

        log.info("AppController initialised. State: %s", self._sm.current.name)

    # ------------------------------------------------------------------
    # Audio pipeline startup
    # ------------------------------------------------------------------

    def _start_audio(self) -> None:
        """Initialise and start the wake word detector."""
        cfg = self._cfg.config
        if not cfg.wake_word_model:
            log.warning("No wake word model configured — audio disabled.")
            return

        self._wake_detector = WakeWordDetector(
            model_name=cfg.wake_word_model,
            device_index=cfg.audio.input_device_index,
            parent=self,
        )
        self._wake_detector.wake_word_detected.connect(self.on_wake_word_detected)
        self._wake_detector.start()
        log.info("Wake word detector started: %s", cfg.wake_word)

    # ------------------------------------------------------------------
    # UI signal wiring
    # ------------------------------------------------------------------

    def _connect_ui_signals(self) -> None:
        win = self._win
        win.sleep_screen.touch_detected.connect(self._on_touch_wake)
        win.confirmation_screen.confirmed.connect(self._on_confirmed)
        win.confirmation_screen.denied.connect(self._on_denied)
        win.inventory_screen.close_requested.connect(self._on_inventory_close)
        win.setup_wizard.setup_complete.connect(self._on_setup_complete)

    # ------------------------------------------------------------------
    # Inactivity timer
    # ------------------------------------------------------------------

    def reset_inactivity_timer(self) -> None:
        self._inactivity_timer.start(
            self._cfg.config.ui.sleep_timeout_seconds * 1000
        )

    def _on_inactivity(self) -> None:
        # Do not interrupt an active confirmation — the user may be mid-tap.
        if self._sm.current == AppState.CONFIRMING:
            log.debug("Inactivity timeout while CONFIRMING — resetting timer.")
            self.reset_inactivity_timer()
            return
        # Keep screen alive during setup wizard.
        if self._sm.current == AppState.SETUP:
            log.debug("Inactivity timeout during SETUP — resetting timer.")
            self.reset_inactivity_timer()
            return
        log.info("Inactivity timeout — going to sleep.")
        self._sm.force(AppState.SLEEP)

    # ------------------------------------------------------------------
    # Touch wake
    # ------------------------------------------------------------------

    def _on_touch_wake(self) -> None:
        self.reset_inactivity_timer()
        if self._sm.current == AppState.SLEEP:
            if self._sm.transition(AppState.LISTENING):
                self._start_recording()

    # ------------------------------------------------------------------
    # Wake word detected
    # ------------------------------------------------------------------

    def on_wake_word_detected(self) -> None:
        self.reset_inactivity_timer()
        if self._sm.current in (AppState.SLEEP, AppState.INVENTORY):
            if self._sm.transition(AppState.LISTENING):
                self._start_recording()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        """Pause wake word detector, open recorder."""
        if self._wake_detector:
            self._wake_detector.pause()

        cfg = self._cfg.config
        self._recorder = Recorder(
            audio_cfg=cfg.audio,
            device_index=cfg.audio.input_device_index,
            parent=self,
        )
        self._recorder.recording_complete.connect(self._on_recording_complete)
        self._recorder.recording_failed.connect(self._on_recording_failed)
        self._recorder.start()
        log.debug("Recorder started.")

    def _on_recording_complete(self, wav_bytes: bytes) -> None:
        if self._wake_detector:
            self._wake_detector.resume()

        self._win.listening_screen.set_status("Transcribing…")
        self._stt_thread = STTThread(
            wav_bytes=wav_bytes,
            groq_api_key=self._cfg.config.api_keys.groq_api_key,
            parent=self,
        )
        self._stt_thread.transcript_ready.connect(self.on_transcript_ready)
        self._stt_thread.transcript_failed.connect(self._on_stt_failed)
        self._stt_thread.start()

    def _on_recording_failed(self, reason: str) -> None:
        log.warning("Recording failed: %s", reason)
        if self._wake_detector:
            self._wake_detector.resume()
        self._tts.speak("I didn't catch that. Please try again.")
        self._sm.transition(AppState.SLEEP)

    # ------------------------------------------------------------------
    # Speech-to-text
    # ------------------------------------------------------------------

    def on_transcript_ready(self, transcript: str) -> None:
        log.info("Transcript: '%s'", transcript)
        self._win.listening_screen.set_status("Thinking…")
        self._intent_thread = IntentParserThread(transcript, self._cfg, parent=self)
        self._intent_thread.intent_parsed.connect(self.on_intent_parsed)
        self._intent_thread.error.connect(
            lambda e: log.error("Intent parser error: %s", e)
        )
        self._intent_thread.start()

    def _on_stt_failed(self, reason: str) -> None:
        log.warning("STT failed: %s", reason)
        self._tts.speak("Sorry, I couldn't understand that. Please try again.")
        self._sm.transition(AppState.SLEEP)

    # ------------------------------------------------------------------
    # Intent parsed
    # ------------------------------------------------------------------

    def on_intent_parsed(self, parsed_intent) -> None:
        self.reset_inactivity_timer()
        intent_type = parsed_intent.intent_type

        # --- Voice CONFIRM/DENY while in CONFIRMING state ---
        if self._sm.current == AppState.CONFIRMING:
            if intent_type == IntentType.CONFIRM:
                self._on_confirmed()
                return
            elif intent_type == IntentType.DENY:
                self._on_denied()
                return

        if intent_type == IntentType.ADD:
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
            self._tts.speak(
                f"Adding {parsed_intent.quantity or '1'} "
                f"{parsed_intent.item_name} to the {loc_display}. "
                f"Is that correct?"
            )
            self._sm.transition(AppState.CONFIRMING)

        elif intent_type == IntentType.REMOVE:
            decision, match = self._fuzzy.find_for_removal(
                parsed_intent.item_name or "",
                location_filter=parsed_intent.location or None,
            )
            if decision == "none":
                self._tts.speak(
                    f"I couldn't find {parsed_intent.item_name} in the freezer. "
                    f"Nothing was removed."
                )
                self._sm.transition(AppState.SLEEP)
                return

            parsed_intent._resolved_item_id       = match.item.id
            parsed_intent._resolved_item_name     = match.item.item_name
            parsed_intent._resolved_item_location = match.item.location
            parsed_intent._resolved_item_quantity = match.item.quantity
            loc_display = self._cfg.get_location_display_name(match.item.location)

            if decision == "direct":
                # Score >= 90: high-confidence match — execute without confirmation
                self._execute_intent(parsed_intent)
                self._sm.transition(AppState.SLEEP)
                return

            # "confirm" — score 70-89: show confirmation screen
            self._pending_intent = parsed_intent
            self._win.confirmation_screen.populate(
                intent_type="REMOVE",
                item_name=match.item.item_name,
                quantity=match.item.quantity,
                location_display=loc_display,
            )
            self._tts.speak(
                f"Remove {match.item.quantity} of {match.item.item_name} "
                f"from the {loc_display}. Is that correct?"
            )
            self._sm.transition(AppState.CONFIRMING)

        elif intent_type == IntentType.QUERY:
            results = self._fuzzy.search_all_locations(
                parsed_intent.item_name or ""
            )
            response = self._fuzzy.format_query_response(
                query=parsed_intent.item_name or "",
                results=results,
                location_display_fn=self._cfg.get_location_display_name,
            )
            self._tts.speak(response)
            rows = [
                (r.item.item_name, r.item.quantity, r.item.location)
                for r in results
            ]
            self._win.inventory_screen.load_data(rows, select_location="all")
            self._sm.transition(AppState.INVENTORY)

        elif intent_type == IntentType.LIST:
            loc_key = parsed_intent.location or "all"
            if loc_key == "all":
                items = self._db.get_all_items()
                loc_display = "all locations"
            else:
                items = self._db.list_by_location(loc_key)
                loc_display = self._cfg.get_location_display_name(loc_key)

            count = len(items)
            self._tts.speak(
                f"Here is what's in the {loc_display}. "
                f"{count} item{'s' if count != 1 else ''}."
            )
            rows = [(i.item_name, i.quantity, i.location) for i in items]
            self._win.inventory_screen.load_data(rows, select_location=loc_key)
            self._sm.transition(AppState.INVENTORY)

        elif intent_type == IntentType.UNKNOWN:
            log.warning("Unknown intent — re-listening.")
            self._tts.speak("Sorry, I didn't understand. Please try again.")
            self._sm.transition(AppState.LISTENING)
            self._start_recording()

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def _on_confirmed(self) -> None:
        self.reset_inactivity_timer()
        intent = self._pending_intent
        if intent is not None:
            self._execute_intent(intent)
        self._pending_intent = None
        self._sm.transition(AppState.SLEEP)

    def _on_denied(self) -> None:
        log.info("User denied — re-listening.")
        self.reset_inactivity_timer()
        self._pending_intent = None
        self._tts.speak("Let's try again. Listening.")
        self._sm.transition(AppState.LISTENING)
        self._start_recording()

    def _execute_intent(self, intent) -> None:
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
                transcript=intent.raw_transcript,
            )
            loc_display = self._cfg.get_location_display_name(item.location)
            self._tts.speak(f"Added. {item.item_name} is now in the {loc_display}.")
            log.info("DB ADD: id=%d '%s'", item.id, item.item_name)

        elif intent_type == "REMOVE":
            item_id   = intent._resolved_item_id
            item_name = intent._resolved_item_name or "item"
            item_loc  = intent._resolved_item_location or intent.location
            item_qty  = intent._resolved_item_quantity or intent.quantity
            if item_id is not None:
                self._db.remove_item(item_id)
                self._db.log_action(
                    action="REMOVE",
                    item_name=item_name,
                    quantity=item_qty,
                    location=item_loc,
                    transcript=intent.raw_transcript,
                )
                self._tts.speak(f"Removed. {item_name} has been taken out.")
                log.info("DB REMOVE: id=%d '%s'", item_id, item_name)

    # ------------------------------------------------------------------
    # Inventory screen
    # ------------------------------------------------------------------

    def _on_inventory_close(self) -> None:
        self.reset_inactivity_timer()
        self._sm.force(AppState.SLEEP)

    # ------------------------------------------------------------------
    # Setup wizard
    # ------------------------------------------------------------------

    def _on_setup_complete(self, config_data: dict) -> None:
        log.info("Setup wizard complete. Saving config.")
        self._cfg.set_wake_word(
            wake_word=config_data.get("wake_word", ""),
            model_name=config_data.get("wake_word_model", ""),
        )
        self._cfg.set_setup_complete(True)
        log.info("Config saved. Wake word: %s", config_data.get("wake_word"))
        self._sm.force(AppState.SLEEP)
        # Start audio now that setup is done
        self._start_audio()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Clean shutdown of all threads. Call before QApplication.quit()."""
        log.info("AppController shutting down.")
        if self._wake_detector:
            self._wake_detector.stop()
        if self._tts:
            self._tts.stop()
        if self._recorder and self._recorder.isRunning():
            self._recorder.requestInterruption()
            self._recorder.wait(2000)
        self._db.close()
