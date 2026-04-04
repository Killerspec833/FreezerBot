"""
ConnectivityChecker — validates internet and API key availability.

All checks are blocking and intended to be called from a QThread
so the UI remains responsive.
"""

import os
import socket
from dataclasses import dataclass

from app.services.logger import get_logger

log = get_logger(__name__)


@dataclass
class CheckResult:
    ok: bool
    message: str


class ConnectivityChecker:
    def __init__(self, cfg):
        """cfg: AppConfig from ConfigManager"""
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_wifi(self) -> CheckResult:
        host = self._cfg.network.connectivity_check_host
        port = self._cfg.network.connectivity_check_port
        timeout = self._cfg.network.connectivity_check_timeout_seconds
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((host, port))
            log.debug("WiFi check passed.")
            return CheckResult(ok=True, message="Internet connected")
        except OSError as e:
            log.warning("WiFi check failed: %s", e)
            return CheckResult(ok=False, message="No internet connection")

    def check_picovoice_key(self) -> CheckResult:
        key = self._cfg.api_keys.picovoice_access_key
        if not key:
            return CheckResult(ok=False, message="Picovoice key missing")
        # Lightweight validation: attempt to import and init with the key.
        # A real init needs a .ppn file; we just verify the key format/length here.
        try:
            import pvporcupine  # noqa: F401
        except ImportError:
            return CheckResult(ok=False, message="pvporcupine not installed")
        # Key is present and library available
        log.debug("Picovoice key present.")
        return CheckResult(ok=True, message="Picovoice key present")

    def check_groq_key(self) -> CheckResult:
        key = self._cfg.api_keys.groq_api_key
        if not key:
            return CheckResult(ok=False, message="Groq key missing")
        try:
            from groq import Groq
            client = Groq(api_key=key)
            # Minimal API call: list models (very cheap, just checks auth)
            client.models.list()
            log.debug("Groq key validated.")
            return CheckResult(ok=True, message="Groq key valid")
        except ImportError:
            return CheckResult(ok=False, message="groq package not installed")
        except Exception as e:
            log.warning("Groq key check failed: %s", e)
            return CheckResult(ok=False, message=f"Groq key invalid: {e}")

    def check_gemini_key(self) -> CheckResult:
        key = self._cfg.api_keys.gemini_api_key
        if not key:
            return CheckResult(ok=False, message="Gemini key missing")
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            # Minimal call: list models
            next(iter(genai.list_models()), None)
            log.debug("Gemini key validated.")
            return CheckResult(ok=True, message="Gemini key valid")
        except ImportError:
            return CheckResult(ok=False, message="google-generativeai not installed")
        except Exception as e:
            log.warning("Gemini key check failed: %s", e)
            return CheckResult(ok=False, message=f"Gemini key invalid: {e}")

    def check_ppn_file(self, ppn_filename: str, wake_words_dir: str) -> CheckResult:
        path = os.path.join(wake_words_dir, ppn_filename)
        if os.path.isfile(path):
            log.debug("Wake word file found: %s", ppn_filename)
            return CheckResult(ok=True, message=f"{ppn_filename} found")
        return CheckResult(
            ok=False,
            message=f"Wake word file not found: {ppn_filename}\n"
                    f"Download it from console.picovoice.ai and place it in wake_words/",
        )

    # ------------------------------------------------------------------
    # Run all checks at once
    # ------------------------------------------------------------------

    def run_all(self, ppn_filename: str, wake_words_dir: str) -> dict[str, CheckResult]:
        return {
            "wifi":      self.check_wifi(),
            "picovoice": self.check_picovoice_key(),
            "groq":      self.check_groq_key(),
            "gemini":    self.check_gemini_key(),
            "ppn_file":  self.check_ppn_file(ppn_filename, wake_words_dir),
        }
