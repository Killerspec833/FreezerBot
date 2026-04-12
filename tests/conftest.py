"""
Shared pytest fixtures.

All fixtures are hardware-free: no audio, no Qt, no openWakeWord, no API keys.
FREEZERBOT_ROOT is not needed because ConfigManager and DatabaseManager
both accept explicit paths.
"""

import json
import os
import tempfile

import pytest

from app.core.config_manager import ConfigManager
from app.database.db_manager import DatabaseManager
from app.database.fuzzy_search import FuzzySearch


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "setup_complete": False,
    "wake_word": "",
    "wake_word_model": "",
    "api_keys": {
        "groq_api_key": "",
        "gemini_api_key": "",
    },
    "locations": {
        "basement_freezer": {
            "display_name": "Basement Freezer",
            "aliases": ["basement", "chest freezer", "basement freezer"],
        },
        "kitchen_freezer": {
            "display_name": "Kitchen Freezer",
            "aliases": ["kitchen freezer", "kitchen", "tall one", "tall freezer"],
        },
        "fridge": {
            "display_name": "Fridge",
            "aliases": ["fridge", "fridge freezer", "small freezer"],
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
    "ui": {
        "sleep_timeout_seconds": 300,
        "screen_width": 1024,
        "screen_height": 600,
        "orientation": "landscape",
    },
    "network": {
        "connectivity_check_host": "8.8.8.8",
        "connectivity_check_port": 53,
        "connectivity_check_timeout_seconds": 2,
    },
    "logging": {
        "level": "INFO",
        "max_file_bytes": 5242880,
        "backup_count": 3,
    },
    "fuzzy_search": {
        "similarity_threshold": 70,
    },
}


@pytest.fixture
def config_dict():
    """Return a fresh copy of the base config dict."""
    import copy
    return copy.deepcopy(_BASE_CONFIG)


@pytest.fixture
def tmp_config_path(tmp_path, config_dict):
    """Write a config.json to a temp file and return its path."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps(config_dict))
    return str(p)


@pytest.fixture
def cfg(tmp_config_path):
    """A loaded ConfigManager backed by a temp config file."""
    return ConfigManager(config_path=tmp_config_path).load()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test_inventory.db")


@pytest.fixture
def db(tmp_db_path):
    """An open DatabaseManager. Closed after each test."""
    manager = DatabaseManager(tmp_db_path)
    manager.open()
    yield manager
    manager.close()


@pytest.fixture
def fuzzy(db, cfg):
    """FuzzySearch using the test db and config."""
    return FuzzySearch(db, default_threshold=cfg.config.fuzzy_search.similarity_threshold)
