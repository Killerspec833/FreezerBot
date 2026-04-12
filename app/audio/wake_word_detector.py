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

        OWW_RATE     = 16000   # rate openWakeWord requires
        FRAME_LENGTH = 1280    # 80 ms at 16000 Hz

        # Resolve which device to use for input.
        # If a specific index is configured, verify it actually has input channels.
        # If not (e.g. it's an output device or the index shifted after reboot),
        # fall back to scanning for the first device whose name contains "usb"
        # (case-insensitive), then the system default.
        def _find_input_device() -> tuple[dict, Optional[int]]:
            if self._device_index is not None:
                candidate = pa.get_device_info_by_index(self._device_index)
                if candidate["maxInputChannels"] >= 1:
                    return candidate, self._device_index
                log.warning(
                    "Configured device_index=%d (%s) has no input channels — scanning for USB mic.",
                    self._device_index, candidate["name"],
                )
            # Scan for a USB input device
            for i in range(pa.get_device_count()):
                info_i = pa.get_device_info_by_index(i)
                if info_i["maxInputChannels"] >= 1 and "usb" in info_i["name"].lower():
                    log.info("Auto-selected USB input device: index=%d name=%s", i, info_i["name"])
                    return info_i, i
            # Last resort: system default input
            info_d = pa.get_default_input_device_info()
            log.info("Using default input device: %s", info_d["name"])
            return info_d, None

        info, resolved_index = _find_input_device()
        native_rate = int(info["defaultSampleRate"])

        # How many native frames to read per 1280-sample OWW chunk.
        native_frames = int(FRAME_LENGTH * native_rate / OWW_RATE)

        open_kwargs = {
            "rate":              native_rate,
            "channels":          1,
            "format":            pyaudio.paInt16,
            "input":             True,
            "frames_per_buffer": native_frames,
        }
        if resolved_index is not None:
            open_kwargs["input_device_index"] = resolved_index

        stream = pa.open(**open_kwargs)
        log.info(
            "WakeWordDetector running. model=%s threshold=%.2f native_rate=%d device=%s",
            self._model_name, self._threshold, native_rate, info["name"],
        )

        try:
            while not self.isInterruptionRequested():
                # Block here while paused (mic yielded to recorder)
                if self._paused:
                    stream.stop_stream()
                    stream.close()                  # fully release ALSA device
                    self._resume_event.wait()       # sleep until resume()
                    if self.isInterruptionRequested():
                        break
                    if not self._paused:
                        stream = pa.open(**open_kwargs)  # reacquire device
                    continue

                pcm_bytes = stream.read(native_frames, exception_on_overflow=False)
                pcm_native = np.frombuffer(pcm_bytes, dtype=np.int16)

                # Downsample to 16000 Hz if needed
                if native_rate != OWW_RATE:
                    pcm = np.interp(
                        np.linspace(0, len(pcm_native) - 1, FRAME_LENGTH),
                        np.arange(len(pcm_native)),
                        pcm_native,
                    ).astype(np.int16)
                else:
                    pcm = pcm_native

                predictions = oww.predict(pcm)

                if predictions.get(self._model_name, 0) >= self._threshold:
                    log.info("Wake word detected!")
                    self.wake_word_detected.emit()

        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            log.info("WakeWordDetector stopped.")
