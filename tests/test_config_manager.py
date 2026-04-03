"""
Tests for ConfigManager — parse, save, validate, display names.
No Qt, no hardware, no API keys.
"""

import json
import os

import pytest

from app.core.config_manager import ConfigManager


class TestLoad:
    def test_loads_setup_complete_false(self, cfg):
        assert cfg.is_setup_complete() is False

    def test_loads_locations(self, cfg):
        keys = cfg.get_all_location_keys()
        assert sorted(keys) == ["basement_freezer", "fridge", "kitchen_freezer"]

    def test_loads_location_aliases(self, cfg):
        loc = cfg.config.locations["basement_freezer"]
        assert "basement" in loc.aliases

    def test_loads_audio_defaults(self, cfg):
        assert cfg.config.audio.silence_threshold_rms == 500
        assert cfg.config.audio.max_recording_seconds == 8

    def test_loads_ui_defaults(self, cfg):
        assert cfg.config.ui.sleep_timeout_seconds == 300
        assert cfg.config.ui.screen_width == 480

    def test_loads_fuzzy_threshold(self, cfg):
        assert cfg.config.fuzzy_search.similarity_threshold == 70

    def test_missing_file_raises(self, tmp_path):
        bad_path = str(tmp_path / "no_such_file.json")
        with pytest.raises(FileNotFoundError):
            ConfigManager(config_path=bad_path).load()


class TestSave:
    def test_set_setup_complete_persists(self, cfg, tmp_config_path):
        cfg.set_setup_complete(True)
        reloaded = ConfigManager(config_path=tmp_config_path).load()
        assert reloaded.is_setup_complete() is True

    def test_set_wake_word_persists(self, cfg, tmp_config_path):
        cfg.set_wake_word("Jarvis", "jarvis_rpi.ppn")
        reloaded = ConfigManager(config_path=tmp_config_path).load()
        assert reloaded.config.wake_word == "Jarvis"
        assert reloaded.config.wake_word_ppn_filename == "jarvis_rpi.ppn"


class TestValidateApiKeys:
    def test_all_missing_returns_three_names(self, cfg):
        missing = cfg.validate_api_keys()
        assert set(missing) == {"picovoice_access_key", "groq_api_key", "gemini_api_key"}

    def test_all_set_returns_empty_list(self, tmp_config_path, config_dict):
        config_dict["api_keys"]["picovoice_access_key"] = "key1"
        config_dict["api_keys"]["groq_api_key"] = "key2"
        config_dict["api_keys"]["gemini_api_key"] = "key3"
        import pathlib
        pathlib.Path(tmp_config_path).write_text(json.dumps(config_dict))
        cm = ConfigManager(config_path=tmp_config_path).load()
        assert cm.validate_api_keys() == []

    def test_partial_missing_returns_correct_names(self, tmp_config_path, config_dict):
        config_dict["api_keys"]["groq_api_key"] = "filled"
        import pathlib
        pathlib.Path(tmp_config_path).write_text(json.dumps(config_dict))
        cm = ConfigManager(config_path=tmp_config_path).load()
        missing = cm.validate_api_keys()
        assert "groq_api_key" not in missing
        assert "picovoice_access_key" in missing
        assert "gemini_api_key" in missing


class TestLocationDisplayName:
    def test_known_location_returns_display_name(self, cfg):
        assert cfg.get_location_display_name("basement_freezer") == "Basement Freezer"
        assert cfg.get_location_display_name("kitchen_freezer") == "Kitchen Freezer"
        assert cfg.get_location_display_name("fridge") == "Fridge"

    def test_unknown_key_returns_title_cased_fallback(self, cfg):
        result = cfg.get_location_display_name("mystery_location")
        assert result == "Mystery Location"

    def test_empty_key_returns_empty_string(self, cfg):
        result = cfg.get_location_display_name("")
        assert result == ""


class TestMalformedConfig:
    def test_missing_optional_section_uses_defaults(self, tmp_path):
        minimal = {
            "setup_complete": True,
            "locations": {},
        }
        p = tmp_path / "config.json"
        p.write_text(json.dumps(minimal))
        cm = ConfigManager(config_path=str(p)).load()
        assert cm.is_setup_complete() is True
        assert cm.config.audio.silence_threshold_rms == 500  # default
