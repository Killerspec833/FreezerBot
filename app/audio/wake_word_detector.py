"""
WakeWordDetector — always-on Porcupine wake word detection.

Runs in a dedicated QThread. Emits wake_word_detected when the chosen
keyword is recognised.

Pause/resume protocol:
  AppController calls pause() before starting the recorder so both threads
  don't fight over the microphone. After recording finishes it calls resume().
"""

import struct
import threading
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from app.services.logger import get_logger

log = get_logger(__name__)


class WakeWordDetector(QThread):
    wake_word_detected = pyqtSignal()

    def __init__(
        self,
        ppn_path: str,
        access_key: str,
        device_index: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._ppn_path    = ppn_path
        self._access_key  = access_key
        self._device_index = device_index

        # Pause/resume synchronisation
        self._paused      = False
        self._pause_lock  = threading.Lock()
        self._resume_event = threading.Event()
        self._resume_event.set()   # not paused initially

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pause(self) -> None:
        """Pause detection so the recorder can use the microphone."""
        with self._pause_lock:
            self._paused = True
            self._resume_event.clear()
        log.debug("WakeWordDetector paused.")

    def resume(self) -> None:
        """Resume detection after recording is complete."""
        with self._pause_lock:
            self._paused = False
            self._resume_event.set()
        log.debug("WakeWordDetector resumed.")

    def stop(self) -> None:
        """Request the thread to stop and wait for it."""
        self.requestInterruption()
        self._resume_event.set()   # unblock if waiting in pause
        self.wait(3000)

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._run_detection_loop()
        except Exception as e:
            log.error("WakeWordDetector fatal error: %s", e)

    def _run_detection_loop(self) -> None:
        import pvporcupine
        import pyaudio

        porcupine = pvporcupine.create(
            access_key=self._access_key,
            keyword_paths=[self._ppn_path],
        )
        pa = pyaudio.PyAudio()

        open_kwargs = {
            "rate":             porcupine.sample_rate,
            "channels":         1,
            "format":           pyaudio.paInt16,
            "input":            True,
            "frames_per_buffer": porcupine.frame_length,
        }
        if self._device_index is not None:
            open_kwargs["input_device_index"] = self._device_index

        stream = pa.open(**open_kwargs)
        log.info(
            "WakeWordDetector running. sample_rate=%d frame_length=%d",
            porcupine.sample_rate, porcupine.frame_length,
        )

        try:
            while not self.isInterruptionRequested():
                # Block here while paused (mic yielded to recorder)
                if self._paused:
                    stream.stop_stream()
                    self._resume_event.wait()       # sleep until resume()
                    if self.isInterruptionRequested():
                        break
                    # Only restart the stream if we are genuinely resumed.
                    # A second pause() could arrive between wait() returning
                    # and this point, so recheck the flag.
                    if not self._paused:
                        stream.start_stream()
                    continue   # re-evaluate pause state at the top of the loop

                pcm_bytes = stream.read(
                    porcupine.frame_length, exception_on_overflow=False
                )
                pcm = struct.unpack_from(
                    f"h" * porcupine.frame_length, pcm_bytes
                )
                keyword_index = porcupine.process(pcm)

                if keyword_index >= 0:
                    log.info("Wake word detected!")
                    self.wake_word_detected.emit()   # queued → main thread

        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            porcupine.delete()
            log.info("WakeWordDetector stopped.")
