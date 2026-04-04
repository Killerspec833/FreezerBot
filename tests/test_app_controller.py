"""
Integration tests for AppController.

Strategy:
  - No Qt event loop is started — QObject/QTimer construction is safe without
    a QApplication when running headless via pytest-qt or plain pytest with
    PyQt6, because we never exec() the loop.
  - All hardware subsystems (WakeWordDetector, Recorder, STTThread,
    IntentParserThread, TTSEngine) are replaced with mocks.
  - The window and its screens are lightweight MagicMocks.
  - A real DatabaseManager backed by a temp SQLite file is used so that
    database-layer integration (ADD, REMOVE, audit log) is exercised end-to-end.
  - The StateMachine is real so state-transition assertions are meaningful.

Tests cover:
  1.  ADD confirmation flow  — confirm path commits item to DB
  2.  ADD denial flow        — deny path does not commit and re-listens
  3.  REMOVE direct path     — score >= 90 removes without confirmation screen
  4.  REMOVE confirm path    — score 70-89 shows confirmation screen
  5.  REMOVE confirm path    — confirmed; item removed, audit log correct
  6.  REMOVE confirm path    — denied; item NOT removed
  7.  Fuzzy "none" decision  — informs user, no DB change
  8.  QUERY intent           — calls search_all_locations, shows inventory screen
  9.  LIST intent            — lists by location, shows inventory screen
  10. UNKNOWN intent         — re-listens (starts new recording)
  11. CONFIRMING state voice CONFIRM — routes to _on_confirmed
  12. CONFIRMING state voice DENY    — routes to _on_denied
  13. Inactivity timer in CONFIRMING state — timer is reset, not forced to SLEEP
  14. Resolved fields on ParsedIntent — location and quantity set from fuzzy match
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from app.core.state_machine import AppState, StateMachine
from app.database.db_manager import DatabaseManager
from app.database.fuzzy_search import FuzzySearch
from app.intent.models import IntentType, ParsedIntent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(intent_type: IntentType, **kwargs) -> ParsedIntent:
    return ParsedIntent(intent_type=intent_type, **kwargs)


def _make_window():
    """Return a MagicMock that satisfies AppController._connect_ui_signals()."""
    win = MagicMock()
    # Signals must be connectable; MagicMock auto-creates .connect attributes.
    win.sleep_screen.touch_detected.connect = MagicMock()
    win.confirmation_screen.confirmed.connect = MagicMock()
    win.confirmation_screen.denied.connect = MagicMock()
    win.inventory_screen.close_requested.connect = MagicMock()
    win.setup_wizard.setup_complete.connect = MagicMock()
    return win


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))
    db.open()
    yield db
    db.close()


@pytest.fixture
def cfg(tmp_path):
    """Minimal ConfigManager backed by a real temp config file."""
    from app.core.config_manager import ConfigManager

    config = {
        "setup_complete": True,
        "wake_word": "computer",
        "wake_word_ppn_filename": "",
        "api_keys": {
            "picovoice_access_key": "",
            "groq_api_key": "",
            "gemini_api_key": "",
        },
        "locations": {
            "basement_freezer": {
                "display_name": "Basement Freezer",
                "aliases": ["basement", "chest freezer"],
            },
            "kitchen_freezer": {
                "display_name": "Kitchen Freezer",
                "aliases": ["kitchen", "tall one"],
            },
            "fridge": {
                "display_name": "Fridge",
                "aliases": ["fridge", "small freezer"],
            },
        },
        "audio": {
            "input_device_index": None,
            "silence_threshold_rms": 500,
            "silence_duration_seconds": 1.5,
            "max_recording_seconds": 8,
            "tts_engine": "gtts",
            "tts_fallback_engine": "pyttsx3",
        },
        "ui": {"sleep_timeout_seconds": 300, "screen_width": 480,
               "screen_height": 800, "orientation": "portrait"},
        "network": {"connectivity_check_host": "8.8.8.8",
                    "connectivity_check_port": 53,
                    "connectivity_check_timeout_seconds": 2},
        "logging": {"level": "INFO", "max_file_bytes": 5242880, "backup_count": 3},
        "fuzzy_search": {"similarity_threshold": 70},
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(config))
    return ConfigManager(config_path=str(p)).load()


@pytest.fixture
def sm():
    return StateMachine(initial=AppState.LISTENING)


@pytest.fixture
def controller(cfg, sm, tmp_db):
    """
    Build an AppController with all hardware replaced by mocks.

    Patches applied (all for the duration of the fixture):
      - DatabaseManager.__init__ / open / close — inject our tmp_db
      - TTSEngine          — silenced
      - WakeWordDetector   — no audio hardware
      - QTimer             — so the inactivity timer doesn't fire unexpectedly
      - get_db_path / get_wake_word_path — not needed (wake word disabled)
    """
    from app.core import app_controller as ac_module

    window = _make_window()

    # We want to inject our already-open tmp_db without re-creating it.
    # Patch DatabaseManager so __init__ returns our fixture instance.
    real_db = tmp_db

    with (
        patch.object(ac_module, "DatabaseManager") as MockDB,
        patch.object(ac_module, "TTSEngine") as MockTTS,
        patch.object(ac_module, "WakeWordDetector"),
        patch.object(ac_module, "get_db_path", return_value="/tmp/fake.db"),
        patch.object(ac_module, "get_wake_word_path", return_value="/tmp/fake.ppn"),
    ):
        # Make DatabaseManager() return our real db instance
        MockDB.return_value = real_db
        # Silence TTS so tests don't need audio
        mock_tts = MagicMock()
        MockTTS.return_value = mock_tts

        from app.core.app_controller import AppController

        ctrl = AppController(cfg_manager=cfg, state_machine=sm, window=window)
        # Replace tts reference so we can inspect .speak() calls
        ctrl._tts = mock_tts
        # Disable the inactivity timer to keep tests predictable
        ctrl._inactivity_timer.stop()

        yield ctrl, window, real_db, mock_tts, sm


# ---------------------------------------------------------------------------
# 1. ADD confirmation flow — confirm commits item
# ---------------------------------------------------------------------------

class TestAddFlow:
    def test_confirm_adds_item_to_db(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.ADD,
                              item_name="ground beef",
                              quantity="2 packages",
                              location="basement_freezer",
                              raw_transcript="add 2 packages of ground beef")

        ctrl.on_intent_parsed(intent)

        assert sm.current == AppState.CONFIRMING
        assert ctrl._pending_intent is intent

        ctrl._on_confirmed()

        items = db.get_all_items()
        assert len(items) == 1
        assert items[0].item_name == "ground beef"
        assert items[0].quantity == "2 packages"
        assert items[0].location == "basement_freezer"

        audit = db.get_audit_log()
        assert len(audit) == 1
        assert audit[0].action == "ADD"

        assert sm.current == AppState.SLEEP
        assert ctrl._pending_intent is None

    def test_confirmation_screen_populated_for_add(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.ADD,
                              item_name="salmon",
                              quantity="3 fillets",
                              location="fridge")
        ctrl.on_intent_parsed(intent)

        win.confirmation_screen.populate.assert_called_once_with(
            intent_type="ADD",
            item_name="salmon",
            quantity="3 fillets",
            location_display="Fridge",
        )

    def test_tts_speaks_add_confirmation_prompt(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.ADD,
                              item_name="peas",
                              quantity="1 bag",
                              location="kitchen_freezer")
        ctrl.on_intent_parsed(intent)

        tts.speak.assert_called_once()
        spoken = tts.speak.call_args[0][0]
        assert "peas" in spoken.lower()
        assert "Kitchen Freezer".lower() in spoken.lower()

    # 2. ADD denial flow
    def test_deny_does_not_add_item(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.ADD,
                              item_name="steak",
                              quantity="1",
                              location="basement_freezer")
        ctrl.on_intent_parsed(intent)
        assert sm.current == AppState.CONFIRMING

        with patch.object(ctrl, "_start_recording"):
            ctrl._on_denied()

        assert db.get_all_items() == []
        assert ctrl._pending_intent is None
        assert sm.current == AppState.LISTENING


# ---------------------------------------------------------------------------
# 3 & 4 & 5 & 6. REMOVE flows
# ---------------------------------------------------------------------------

class TestRemoveFlow:
    def _seed(self, db, name="chicken thighs", qty="2 bags",
              loc="basement_freezer"):
        return db.add_item(name, qty, loc)

    def test_direct_removal_high_score(self, controller):
        """score >= 90: remove without showing confirmation screen."""
        ctrl, win, db, tts, sm = controller
        item = self._seed(db)

        intent = _make_intent(IntentType.REMOVE,
                              item_name="chicken thighs",
                              raw_transcript="remove chicken thighs")

        with patch.object(ctrl._fuzzy, "find_for_removal",
                          return_value=("direct",
                                        MagicMock(item=item, score=95.0))):
            ctrl.on_intent_parsed(intent)

        assert db.get_all_items() == []
        assert sm.current == AppState.SLEEP

        audit = db.get_audit_log()
        assert audit[0].action == "REMOVE"
        assert audit[0].item_name == item.item_name
        assert audit[0].location == item.location
        assert audit[0].quantity == item.quantity

    def test_direct_removal_does_not_show_confirmation_screen(self, controller):
        ctrl, win, db, tts, sm = controller
        item = self._seed(db)

        intent = _make_intent(IntentType.REMOVE, item_name="chicken thighs")

        with patch.object(ctrl._fuzzy, "find_for_removal",
                          return_value=("direct",
                                        MagicMock(item=item, score=95.0))):
            ctrl.on_intent_parsed(intent)

        win.confirmation_screen.populate.assert_not_called()

    def test_confirm_path_shows_confirmation_screen(self, controller):
        """score 70-89: show confirmation screen."""
        ctrl, win, db, tts, sm = controller
        item = self._seed(db)

        intent = _make_intent(IntentType.REMOVE, item_name="chicken")

        with patch.object(ctrl._fuzzy, "find_for_removal",
                          return_value=("confirm",
                                        MagicMock(item=item, score=82.0))):
            ctrl.on_intent_parsed(intent)

        assert sm.current == AppState.CONFIRMING
        win.confirmation_screen.populate.assert_called_once()

    def test_confirm_path_confirmed_removes_item(self, controller):
        ctrl, win, db, tts, sm = controller
        item = self._seed(db)

        intent = _make_intent(IntentType.REMOVE,
                              item_name="chicken",
                              raw_transcript="remove chicken")

        with patch.object(ctrl._fuzzy, "find_for_removal",
                          return_value=("confirm",
                                        MagicMock(item=item, score=82.0))):
            ctrl.on_intent_parsed(intent)

        ctrl._on_confirmed()

        assert db.get_all_items() == []
        audit = db.get_audit_log()
        assert audit[0].action == "REMOVE"
        # Audit uses resolved fields — from the fuzzy match, not the spoken intent
        assert audit[0].location == item.location
        assert audit[0].quantity == item.quantity

    def test_confirm_path_denied_leaves_item_intact(self, controller):
        ctrl, win, db, tts, sm = controller
        item = self._seed(db)

        intent = _make_intent(IntentType.REMOVE, item_name="chicken")

        with patch.object(ctrl._fuzzy, "find_for_removal",
                          return_value=("confirm",
                                        MagicMock(item=item, score=82.0))):
            ctrl.on_intent_parsed(intent)

        with patch.object(ctrl, "_start_recording"):
            ctrl._on_denied()

        # Item should still be in the database
        assert len(db.get_all_items()) == 1
        assert db.get_audit_log() == []

    def test_none_decision_informs_user_and_goes_to_sleep(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.REMOVE, item_name="unicorn")

        with patch.object(ctrl._fuzzy, "find_for_removal",
                          return_value=("none", None)):
            ctrl.on_intent_parsed(intent)

        assert sm.current == AppState.SLEEP
        tts.speak.assert_called_once()
        assert db.get_all_items() == []

    # 14. Resolved fields set correctly on ParsedIntent
    def test_resolved_fields_set_from_fuzzy_match(self, controller):
        ctrl, win, db, tts, sm = controller
        item = self._seed(db, name="pork belly", qty="1 slab",
                          loc="kitchen_freezer")

        intent = _make_intent(IntentType.REMOVE, item_name="pork")

        with patch.object(ctrl._fuzzy, "find_for_removal",
                          return_value=("confirm",
                                        MagicMock(item=item, score=78.0))):
            ctrl.on_intent_parsed(intent)

        assert intent._resolved_item_id == item.id
        assert intent._resolved_item_name == item.item_name
        assert intent._resolved_item_location == item.location
        assert intent._resolved_item_quantity == item.quantity


# ---------------------------------------------------------------------------
# 8. QUERY intent
# ---------------------------------------------------------------------------

class TestQueryIntent:
    def test_query_transitions_to_inventory(self, controller):
        ctrl, win, db, tts, sm = controller
        db.add_item("beef", "2 packs", "basement_freezer")

        intent = _make_intent(IntentType.QUERY, item_name="beef")
        ctrl.on_intent_parsed(intent)

        assert sm.current == AppState.INVENTORY
        win.inventory_screen.load_data.assert_called_once()
        tts.speak.assert_called_once()

    def test_query_uses_search_all_locations(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.QUERY, item_name="salmon")
        with patch.object(ctrl._fuzzy, "search_all_locations",
                          return_value=[]) as mock_search:
            ctrl.on_intent_parsed(intent)
        mock_search.assert_called_once_with("salmon")

    def test_query_no_results_speaks_not_found(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.QUERY, item_name="unicorn steak")
        ctrl.on_intent_parsed(intent)

        spoken = tts.speak.call_args[0][0]
        assert "don't see" in spoken.lower() or "found" in spoken.lower() or "unicorn" in spoken.lower()


# ---------------------------------------------------------------------------
# 9. LIST intent
# ---------------------------------------------------------------------------

class TestListIntent:
    def test_list_with_location_transitions_to_inventory(self, controller):
        ctrl, win, db, tts, sm = controller
        db.add_item("salmon", "2", "fridge")
        db.add_item("steak", "1", "fridge")

        intent = _make_intent(IntentType.LIST, location="fridge")
        ctrl.on_intent_parsed(intent)

        assert sm.current == AppState.INVENTORY
        args, kwargs = win.inventory_screen.load_data.call_args
        rows = args[0]
        assert len(rows) == 2
        assert kwargs.get("select_location") == "fridge"

    def test_list_no_location_uses_all_items(self, controller):
        ctrl, win, db, tts, sm = controller
        db.add_item("apple", "1", "fridge")
        db.add_item("beef", "1", "basement_freezer")

        intent = _make_intent(IntentType.LIST, location=None)
        ctrl.on_intent_parsed(intent)

        args, kwargs = win.inventory_screen.load_data.call_args
        assert len(args[0]) == 2
        assert kwargs.get("select_location") == "all"


# ---------------------------------------------------------------------------
# 10. UNKNOWN intent
# ---------------------------------------------------------------------------

class TestUnknownIntent:
    def test_unknown_starts_new_recording(self, controller):
        ctrl, win, db, tts, sm = controller

        intent = _make_intent(IntentType.UNKNOWN)
        with patch.object(ctrl, "_start_recording") as mock_record:
            ctrl.on_intent_parsed(intent)

        mock_record.assert_called_once()
        assert sm.current == AppState.LISTENING


# ---------------------------------------------------------------------------
# 11 & 12. Voice CONFIRM / DENY while in CONFIRMING state
# ---------------------------------------------------------------------------

class TestVoiceConfirmDeny:
    def test_voice_confirm_while_confirming_calls_on_confirmed(self, controller):
        ctrl, win, db, tts, sm = controller

        # Put controller into CONFIRMING state with a pending ADD
        add_intent = _make_intent(IntentType.ADD,
                                  item_name="tuna",
                                  quantity="1 can",
                                  location="fridge")
        ctrl.on_intent_parsed(add_intent)
        assert sm.current == AppState.CONFIRMING

        # Now send a CONFIRM intent via voice (parsed while CONFIRMING)
        confirm_intent = _make_intent(IntentType.CONFIRM)
        ctrl.on_intent_parsed(confirm_intent)

        # Should have executed the ADD
        items = db.get_all_items()
        assert any(i.item_name == "tuna" for i in items)
        assert sm.current == AppState.SLEEP

    def test_voice_deny_while_confirming_calls_on_denied(self, controller):
        ctrl, win, db, tts, sm = controller

        add_intent = _make_intent(IntentType.ADD,
                                  item_name="tuna",
                                  quantity="1 can",
                                  location="fridge")
        ctrl.on_intent_parsed(add_intent)
        assert sm.current == AppState.CONFIRMING

        deny_intent = _make_intent(IntentType.DENY)
        with patch.object(ctrl, "_start_recording"):
            ctrl.on_intent_parsed(deny_intent)

        # Item must NOT have been added
        assert db.get_all_items() == []
        assert sm.current == AppState.LISTENING


# ---------------------------------------------------------------------------
# 13. Inactivity timer does not force SLEEP while CONFIRMING
# ---------------------------------------------------------------------------

class TestInactivityTimer:
    def test_inactivity_while_confirming_resets_timer_not_sleep(self, controller):
        ctrl, win, db, tts, sm = controller

        # Put into CONFIRMING state
        intent = _make_intent(IntentType.ADD,
                              item_name="tuna",
                              quantity="1",
                              location="fridge")
        ctrl.on_intent_parsed(intent)
        assert sm.current == AppState.CONFIRMING

        with patch.object(ctrl, "reset_inactivity_timer") as mock_reset:
            ctrl._on_inactivity()

        # Must have reset timer
        mock_reset.assert_called_once()
        # Must NOT have transitioned away from CONFIRMING
        assert sm.current == AppState.CONFIRMING

    def test_inactivity_outside_confirming_goes_to_sleep(self, controller):
        ctrl, win, db, tts, sm = controller

        # Force to INVENTORY to exercise the non-CONFIRMING inactivity path
        sm.force(AppState.INVENTORY)
        ctrl._on_inactivity()

        assert sm.current == AppState.SLEEP
