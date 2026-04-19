"""
Reads and writes config/config.json on the USB stick.
All other modules access config through this module — never raw JSON reads.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from app.core.path_resolver import get_config_path


# ---------------------------------------------------------------------------
# Dataclasses — typed representation of config.json
# ---------------------------------------------------------------------------

@dataclass
class ApiKeys:
    groq_api_key: str = ""
    gemini_api_key: str = ""


@dataclass
class LocationConfig:
    display_name: str = ""
    aliases: list = field(default_factory=list)


@dataclass
class AudioConfig:
    input_device_index: Optional[int] = None
    silence_threshold_rms: int = 500
    silence_duration_seconds: float = 1.5
    max_recording_seconds: int = 8
    tts_engine: str = "gtts"
    tts_fallback_engine: str = "pyttsx3"


@dataclass
class UiConfig:
    sleep_timeout_seconds: int = 600
    screen_width: int = 1024
    screen_height: int = 600
    orientation: str = "landscape"


@dataclass
class NetworkConfig:
    connectivity_check_host: str = "8.8.8.8"
    connectivity_check_port: int = 53
    connectivity_check_timeout_seconds: int = 2


@dataclass
class LoggingConfig:
    level: str = "INFO"
    max_file_bytes: int = 5242880
    backup_count: int = 3


@dataclass
class FuzzySearchConfig:
    similarity_threshold: int = 70


@dataclass
class AppConfig:
    setup_complete: bool = False
    wake_word: str = ""
    wake_word_model: str = ""
    api_keys: ApiKeys = field(default_factory=ApiKeys)
    locations: dict = field(default_factory=dict)
    audio: AudioConfig = field(default_factory=AudioConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    fuzzy_search: FuzzySearchConfig = field(default_factory=FuzzySearchConfig)


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    def __init__(self, config_path: Optional[str] = None):
        self._path = config_path or get_config_path()
        self._config: AppConfig = AppConfig()
        self._raw: dict = {}

    def load(self) -> "ConfigManager":
        """Load config from disk. Returns self for chaining."""
        if not os.path.isfile(self._path):
            raise FileNotFoundError(
                f"config.json not found at {self._path}. "
                "Ensure the USB stick is mounted and config/config.json exists."
            )
        with open(self._path, "r", encoding="utf-8") as f:
            self._raw = json.load(f)
        self._parse()
        return self

    def save(self) -> None:
        """Write current config back to disk atomically.

        Writes to a sibling temp file first, then os.replace() renames it
        into place. This prevents a corrupt config.json if the Pi loses
        power mid-write.
        """
        dir_name = os.path.dirname(self._path)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._to_dict(), f, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        return self._config

    def is_setup_complete(self) -> bool:
        return self._config.setup_complete

    def set_setup_complete(self, value: bool) -> None:
        self._config.setup_complete = value
        self.save()

    def set_wake_word(self, wake_word: str, model_name: str) -> None:
        self._config.wake_word = wake_word
        self._config.wake_word_model = model_name
        self.save()

    def validate_api_keys(self) -> list[str]:
        """Return list of missing key names. Empty list = all present."""
        missing = []
        keys = self._config.api_keys
        if not keys.groq_api_key:
            missing.append("groq_api_key")
        if not keys.gemini_api_key:
            missing.append("gemini_api_key")
        return missing

    def get_location_display_name(self, canonical_key: str) -> str:
        loc = self._config.locations.get(canonical_key)
        if loc:
            return loc.display_name
        return canonical_key.replace("_", " ").title()

    def get_all_location_keys(self) -> list[str]:
        return list(self._config.locations.keys())

    # ------------------------------------------------------------------
    # Internal parse / serialize
    # ------------------------------------------------------------------

    def _parse(self) -> None:
        r = self._raw
        c = self._config

        c.setup_complete = r.get("setup_complete", False)
        c.wake_word = r.get("wake_word", "")
        c.wake_word_model = r.get("wake_word_model", "")

        keys = r.get("api_keys", {})
        c.api_keys = ApiKeys(
            groq_api_key=keys.get("groq_api_key", ""),
            gemini_api_key=keys.get("gemini_api_key", ""),
        )

        locations_raw = r.get("locations", {})
        c.locations = {}
        for key, val in locations_raw.items():
            c.locations[key] = LocationConfig(
                display_name=val.get("display_name", key),
                aliases=val.get("aliases", []),
            )

        audio = r.get("audio", {})
        c.audio = AudioConfig(
            input_device_index=audio.get("input_device_index"),
            silence_threshold_rms=audio.get("silence_threshold_rms", 500),
            silence_duration_seconds=audio.get("silence_duration_seconds", 1.5),
            max_recording_seconds=audio.get("max_recording_seconds", 8),
            tts_engine=audio.get("tts_engine", "gtts"),
            tts_fallback_engine=audio.get("tts_fallback_engine", "pyttsx3"),
        )

        ui = r.get("ui", {})
        c.ui = UiConfig(
            sleep_timeout_seconds=ui.get("sleep_timeout_seconds", 300),
            screen_width=ui.get("screen_width", 1024),
            screen_height=ui.get("screen_height", 600),
            orientation=ui.get("orientation", "landscape"),
        )

        net = r.get("network", {})
        c.network = NetworkConfig(
            connectivity_check_host=net.get("connectivity_check_host", "8.8.8.8"),
            connectivity_check_port=net.get("connectivity_check_port", 53),
            connectivity_check_timeout_seconds=net.get("connectivity_check_timeout_seconds", 2),
        )

        log = r.get("logging", {})
        c.logging = LoggingConfig(
            level=log.get("level", "INFO"),
            max_file_bytes=log.get("max_file_bytes", 5242880),
            backup_count=log.get("backup_count", 3),
        )

        fuzz = r.get("fuzzy_search", {})
        c.fuzzy_search = FuzzySearchConfig(
            similarity_threshold=fuzz.get("similarity_threshold", 70),
        )

    def _to_dict(self) -> dict:
        c = self._config
        return {
            "setup_complete": c.setup_complete,
            "wake_word": c.wake_word,
            "wake_word_model": c.wake_word_model,
            "api_keys": {
                "groq_api_key": c.api_keys.groq_api_key,
                "gemini_api_key": c.api_keys.gemini_api_key,
            },
            "locations": {
                key: {
                    "display_name": loc.display_name,
                    "aliases": loc.aliases,
                }
                for key, loc in c.locations.items()
            },
            "audio": {
                "input_device_index": c.audio.input_device_index,
                "silence_threshold_rms": c.audio.silence_threshold_rms,
                "silence_duration_seconds": c.audio.silence_duration_seconds,
                "max_recording_seconds": c.audio.max_recording_seconds,
                "tts_engine": c.audio.tts_engine,
                "tts_fallback_engine": c.audio.tts_fallback_engine,
            },
            "ui": {
                "sleep_timeout_seconds": c.ui.sleep_timeout_seconds,
                "screen_width": c.ui.screen_width,
                "screen_height": c.ui.screen_height,
                "orientation": c.ui.orientation,
            },
            "network": {
                "connectivity_check_host": c.network.connectivity_check_host,
                "connectivity_check_port": c.network.connectivity_check_port,
                "connectivity_check_timeout_seconds": c.network.connectivity_check_timeout_seconds,
            },
            "logging": {
                "level": c.logging.level,
                "max_file_bytes": c.logging.max_file_bytes,
                "backup_count": c.logging.backup_count,
            },
            "fuzzy_search": {
                "similarity_threshold": c.fuzzy_search.similarity_threshold,
            },
        }
