"""
WakeWordDetector — always-on openWakeWord wake word detection.

Runs in a dedicated QThread. Emits wake_word_detected when the chosen
keyword is recognised.

Pause/resume protocol:
  AppController calls pause() before starting the recorder so both threads
  don't fight over the microphone. After recording finishes it calls resume().
"""

import threading
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from app.services.logger import get_logger

log = get_logger(__name__)


class WakeWordDetector(QThread):
    wake_word_detected = pyqtSignal()

    def __init__(
        self,
        model_name: str,
        threshold: float = 0.5,
        device_index: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._model_name   = model_name
        self._threshold    = threshold
        self._device_index = device_index

        # Pause/resume synchronisation
        self._paused       = False
        self._pause_lock   = threading.Lock()
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
        import numpy as np
        import pyaudio
        from openwakeword.model import Model

        oww = Model(wakeword_model_paths=[])  # load all bundled pre-trained models
        pa = pyaudio.PyAudio()

        SAMPLE_RATE  = 16000
        FRAME_LENGTH = 1280   # 80 ms chunks — what openWakeWord expects

        open_kwargs = {
            "rate":              SAMPLE_RATE,
            "channels":          1,
            "format":            pyaudio.paInt16,
            "input":             True,
            "frames_per_buffer": FRAME_LENGTH,
        }
        if self._device_index is not None:
            open_kwargs["input_device_index"] = self._device_index

        stream = pa.open(**open_kwargs)
        log.info(
            "WakeWordDetector running. model=%s threshold=%.2f",
            self._model_name, self._threshold,
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

                pcm_bytes = stream.read(FRAME_LENGTH, exception_on_overflow=False)
                pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
                predictions = oww.predict(pcm)

                if predictions.get(self._model_name, 0) >= self._threshold:
                    log.info("Wake word detected!")
                    self.wake_word_detected.emit()   # queued → main thread

        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            log.info("WakeWordDetector stopped.")
