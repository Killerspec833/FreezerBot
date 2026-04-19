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
import time

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

        # Guard against burst wake word detections (flag set before recorder
        # thread is running, cleared when recording/TTS is fully done).
        self._recording_active = False

        # Consecutive short-transcript (TTS echo) counter — reset on real speech.
        self._echo_count = 0

        # Timestamp of the last TTS-finished event. Wake-word detections within
        # 2 s of TTS finishing are ignored — the paused stream accumulates a
        # buffer of TTS audio that scores above the wake-word threshold when
        # resumed, causing a spurious detection.
        self._tts_finished_at: float = 0.0

        # --- TTS engine (always running) ---
        self._tts = TTSEngine(parent=self)
        self._tts.speaking_finished.connect(self._on_tts_finished)
        self._tts.start()

        self._connect_ui_signals()

        # Wire state changes so inventory refreshes whenever we return to SLEEP
        self._sm.state_changed.connect(self._on_state_changed_ctrl)

        # Start audio pipeline only if setup is complete
        if cfg_manager.is_setup_complete():
            self._start_audio()

        # Populate the inventory screen on startup
        self._refresh_inventory()

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
        # Do not fire while audio pipeline is active — re-arm and try later.
        if self._recording_active:
            log.debug("Inactivity timeout while recording/processing — resetting timer.")
            self.reset_inactivity_timer()
            return
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
        # Pause the wake word detector so it drains the mic buffer when it
        # resumes.  Without this, TTS echoes from the last command accumulate
        # while the app was active and immediately trigger a false wake-word
        # the moment the screensaver becomes visible.  We also start a fresh
        # 2-second grace period so any detection that slips through before the
        # drain completes is ignored.
        if self._wake_detector:
            self._tts_finished_at = time.monotonic()
            self._wake_detector.pause()
            QTimer.singleShot(300, self._resume_detector)

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
        if self._recording_active:
            return
        # Post-TTS grace period: ignore wake-word detections for 2 s after TTS
        # finishes. The paused stream accumulates buffered audio (TTS echo) that
        # can score above the detection threshold the moment the stream resumes.
        elapsed = time.monotonic() - self._tts_finished_at
        if elapsed < 2.0:
            log.debug("Wake word ignored — %.1fs post-TTS grace period.", elapsed)
            return
        self._recording_active = True
        # Block the detector from emitting further wake_word_detected signals
        # while we process this one. Unblocked in _on_tts_finished.
        if self._wake_detector:
            self._wake_detector.blockSignals(True)
        self.reset_inactivity_timer()
        if self._sm.current in (AppState.SLEEP, AppState.INVENTORY):
            if self._sm.transition(AppState.LISTENING):
                self._start_recording()
            else:
                self._recording_active = False
                if self._wake_detector:
                    self._wake_detector.blockSignals(False)
        else:
            self._recording_active = False
            if self._wake_detector:
                self._wake_detector.blockSignals(False)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        """Pause wake word detector, open recorder."""
        # Guard: only record in states where audio input is expected.
        # This prevents stale QTimer.singleShot re-listen calls from opening
        # a recorder after the app has already transitioned to SLEEP.
        if self._sm.current not in (AppState.LISTENING, AppState.CONFIRMING):
            log.debug(
                "_start_recording() called in state %s — ignoring stale timer.",
                self._sm.current.name,
            )
            self._recording_active = False
            return

        if self._wake_detector:
            self._wake_detector.pause()

        # Show snowflake on whichever screen is active
        if self._sm.current == AppState.CONFIRMING:
            self._win.confirmation_screen.set_voice_hint("Say  YES  or  NO  now")
            self._win.confirmation_screen.show_snowflake("Listening…")
        # LISTENING state: snowflake is already shown by main_window state change

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
        # If two recorders spawned from a burst detection, only process the last
        # one created (self._recorder). Drop results from stale recorders.
        if self.sender() is not self._recorder:
            log.debug("Ignoring stale recording_complete from previous recorder.")
            return
        # Keep detector paused until TTS finishes — resumed in _on_tts_finished.
        self._win.confirmation_screen.hide_snowflake()
        self._win.inventory_screen.set_mic_status("Transcribing…")
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
        self._win.confirmation_screen.hide_snowflake()
        self._tts.speak("I didn't catch that. Please try again.")
        self._sm.transition(AppState.INVENTORY)
        # _recording_active stays True until TTS finishes (_on_tts_finished)

    def _on_tts_finished(self) -> None:
        """Called when TTS finishes speaking.

        Resumes the wake word detector (prevents speaker echo triggering it).
        If the app is in CONFIRMING state, automatically starts a new recording
        cycle so the user can say yes/no without re-saying the wake word.
        """
        self._tts_finished_at = time.monotonic()
        self._recording_active = False
        self.reset_inactivity_timer()
        if self._sm.current == AppState.CONFIRMING:
            # speaking_finished fires when pygame's internal buffer empties, but
            # PulseAudio still has ~300-500 ms of audio queued for playback.
            # We wait 3 s total so speaker output + room reverb clear before the
            # mic opens.  Show a countdown so the user knows to wait.
            self._recording_active = True
            self._win.confirmation_screen.set_voice_hint("Mic opens in 3s — wait…")
            QTimer.singleShot(1000, lambda: self._win.confirmation_screen.set_voice_hint("Mic opens in 2s…"))
            QTimer.singleShot(2000, lambda: self._win.confirmation_screen.set_voice_hint("Mic opens in 1s…"))
            QTimer.singleShot(3000, self._start_recording)
        else:
            # All other states (SLEEP, LISTENING, INVENTORY, etc.): resume the
            # detector so the next real "Hey Jarvis" is caught.
            # The 2-second grace period in on_wake_word_detected handles any
            # stale detections from buffered TTS audio.
            QTimer.singleShot(500, self._resume_detector)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resume_detector(self) -> None:
        """Unblock and resume the wake word detector (called via QTimer)."""
        if self._wake_detector:
            self._wake_detector.blockSignals(False)
            self._wake_detector.resume()

    def _refresh_inventory(self) -> None:
        """Reload all items from DB and repopulate the inventory screen."""
        items = self._db.get_all_items()
        rows = [(i.item_name, i.quantity, i.location) for i in items]
        self._win.inventory_screen.load_data(rows, select_location="all")

    def _on_state_changed_ctrl(self, state: AppState) -> None:
        """Refresh inventory when waking to LISTENING (returns from screensaver).
        INVENTORY transitions are NOT refreshed here — LIST/QUERY handlers set their
        own filtered view via load_data(), and ADD/REMOVE call _refresh_inventory()
        explicitly after the DB write so the updated full list is shown."""
        if state == AppState.LISTENING:
            self._refresh_inventory()

    # ------------------------------------------------------------------
    # Speech-to-text
    # ------------------------------------------------------------------

    def on_transcript_ready(self, transcript: str) -> None:
        log.info("Transcript: '%s'", transcript)

        # Guard against TTS echo: very short transcripts (< 3 words) are almost
        # certainly speaker bleed, not a real command.
        # Exception: CONFIRMING state legitimately receives 1-word answers ("yes"/"no").
        if len(transcript.split()) < 3 and self._sm.current != AppState.CONFIRMING:
            self._echo_count += 1
            log.warning(
                "Transcript too short (%d word(s)) — likely TTS echo #%d; re-listening.",
                len(transcript.split()),
                self._echo_count,
            )
            if self._echo_count >= 2:
                # Two consecutive echoes: give up and sleep so the detector can
                # catch a real wake word from the user.
                log.warning("Too many echo transcripts — returning to SLEEP.")
                self._echo_count = 0
                self._recording_active = False
                self._sm.force(AppState.INVENTORY)
                QTimer.singleShot(1500, self._resume_detector)
            elif self._sm.current in (AppState.LISTENING, AppState.CONFIRMING):
                # Wait longer than the first delay to let any remaining echo clear.
                QTimer.singleShot(1200, self._start_recording)
            return

        # Real command — reset echo counter.
        self._echo_count = 0

        self._win.inventory_screen.set_mic_status("Thinking…")
        self._intent_thread = IntentParserThread(transcript, self._cfg, parent=self)
        self._intent_thread.intent_parsed.connect(self.on_intent_parsed)
        self._intent_thread.error.connect(
            lambda e: log.error("Intent parser error: %s", e)
        )
        self._intent_thread.start()

    def _on_stt_failed(self, reason: str) -> None:
        log.warning("STT failed: %s", reason)
        self._tts.speak("Sorry, I couldn't understand that. Please try again.")
        self._sm.transition(AppState.INVENTORY)

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

        # --- Voice DENY ("done") while viewing inventory ---
        if self._sm.current == AppState.INVENTORY and intent_type == IntentType.DENY:
            self._sm.force(AppState.SLEEP)
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
                self._sm.transition(AppState.INVENTORY)
                return

            parsed_intent._resolved_item_id       = match.item.id
            parsed_intent._resolved_item_name     = match.item.item_name
            parsed_intent._resolved_item_location = match.item.location
            parsed_intent._resolved_item_quantity = match.item.quantity
            loc_display = self._cfg.get_location_display_name(match.item.location)

            if decision == "direct":
                # Score >= 90: high-confidence match — execute without confirmation
                self._execute_intent(parsed_intent)
                self._refresh_inventory()
                self._sm.transition(AppState.INVENTORY)
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
            log.warning("Unknown intent — returning to INVENTORY.")
            self._sm.force(AppState.INVENTORY)
            self._tts.speak("Sorry, I didn't understand.")

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def _on_confirmed(self) -> None:
        self.reset_inactivity_timer()
        intent = self._pending_intent
        if intent is not None:
            self._execute_intent(intent)
        self._pending_intent = None
        self._refresh_inventory()
        self._sm.transition(AppState.INVENTORY)

    def _on_denied(self) -> None:
        log.info("User denied — returning to INVENTORY.")
        self.reset_inactivity_timer()
        self._pending_intent = None
        self._sm.force(AppState.INVENTORY)
        self._tts.speak("Cancelled.")

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
