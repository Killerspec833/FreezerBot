"""
TTSEngine — queue-based text-to-speech.

Primary:  gTTS (Google TTS, online) → MP3 → pygame playback
Fallback: pyttsx3 (offline) when network is unavailable or gTTS fails

Call speak(text) from any thread — it is thread-safe.
The engine runs in its own QThread and serialises all speech requests.
"""

import io
import queue
import socket
import tempfile
import os
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from app.services.logger import get_logger

log = get_logger(__name__)

_STOP_SENTINEL = object()   # poison pill to stop the thread


def _is_online(host: str = "8.8.8.8", port: int = 53, timeout: int = 2) -> bool:
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except OSError:
        return False


class TTSEngine(QThread):
    speaking_started  = pyqtSignal()
    speaking_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._pygame_ready = False

    # ------------------------------------------------------------------
    # Public API (thread-safe)
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Queue a text string for speech. Returns immediately."""
        if text:
            self._queue.put(text)

    def stop(self) -> None:
        """Signal the engine to shut down after finishing current speech."""
        self._queue.put(_STOP_SENTINEL)
        self.wait(3000)

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._init_pygame()
        log.info("TTSEngine started.")

        while True:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is _STOP_SENTINEL:
                log.info("TTSEngine stopping.")
                break

            text = str(item)
            self.speaking_started.emit()
            try:
                if _is_online():
                    success = self._speak_gtts(text)
                    if not success:
                        self._speak_pyttsx3(text)
                else:
                    log.info("TTS: offline — using pyttsx3 fallback.")
                    self._speak_pyttsx3(text)
            except Exception as e:
                log.error("TTS error: %s", e)
            finally:
                self.speaking_finished.emit()

    # ------------------------------------------------------------------
    # gTTS (online)
    # ------------------------------------------------------------------

    def _speak_gtts(self, text: str) -> bool:
        """Return True on success."""
        try:
            from gtts import gTTS

            tts = gTTS(text=text, lang="en", slow=False)
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)

            if self._pygame_ready:
                import pygame
                # pygame.mixer.music.load needs a file-like object or path
                # Write to a named temp file for maximum compatibility
                with tempfile.NamedTemporaryFile(
                    suffix=".mp3", delete=False
                ) as tmp:
                    tmp.write(buf.read())
                    tmp_path = tmp.name

                try:
                    pygame.mixer.music.load(tmp_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        self.msleep(50)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            else:
                # Fallback: use mpg123 subprocess
                import subprocess
                with tempfile.NamedTemporaryFile(
                    suffix=".mp3", delete=False
                ) as tmp:
                    tmp.write(buf.read())
                    tmp_path = tmp.name
                try:
                    subprocess.run(
                        ["mpg123", "-q", tmp_path],
                        check=True, timeout=30
                    )
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

            log.debug("TTS (gTTS): '%s'", text[:60])
            return True

        except Exception as e:
            log.warning("gTTS failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # pyttsx3 (offline fallback)
    # ------------------------------------------------------------------

    def _speak_pyttsx3(self, text: str) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 160)   # words per minute
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            log.debug("TTS (pyttsx3): '%s'", text[:60])
        except Exception as e:
            log.error("pyttsx3 failed: %s", e)

    # ------------------------------------------------------------------
    # pygame init
    # ------------------------------------------------------------------

    def _init_pygame(self) -> None:
        try:
            import pygame
            pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            self._pygame_ready = True
            log.debug("pygame.mixer initialised.")
        except Exception as e:
            log.warning("pygame.mixer init failed: %s — will use mpg123.", e)
            self._pygame_ready = False
