"""
Recorder — captures one utterance from the microphone.

Started by AppController after wake word detection.
Uses VAD (RMS energy threshold) to detect end-of-speech.
Emits recording_complete(wav_bytes) when done, or recording_failed(reason).

Pre-roll buffer:
  The last PRE_ROLL_SECONDS of audio before recording starts is prepended
  to the capture, so fast speakers whose first word overlaps the wake word
  response don't lose the beginning of their command.
"""

import collections
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from app.audio.audio_utils import calculate_rms, pcm_to_wav
from app.core.config_manager import AudioConfig
from app.services.logger import get_logger

log = get_logger(__name__)

PRE_ROLL_SECONDS = 0.3      # seconds of audio to keep before speech onset


class Recorder(QThread):
    recording_complete = pyqtSignal(bytes)   # WAV bytes
    recording_failed   = pyqtSignal(str)     # error reason

    def __init__(
        self,
        audio_cfg: AudioConfig,
        device_index: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._cfg          = audio_cfg
        self._device_index = device_index
        self._sample_rate  = 16000
        self._frame_size   = 512
        self._sample_width = 2   # 16-bit = 2 bytes

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            wav_bytes = self._record()
            if wav_bytes:
                self.recording_complete.emit(wav_bytes)
            else:
                self.recording_failed.emit("No audio captured.")
        except Exception as e:
            log.error("Recorder error: %s", e)
            self.recording_failed.emit(str(e))

    def _record(self) -> Optional[bytes]:
        import pyaudio

        pa = pyaudio.PyAudio()

        # Resolve which device to use.  If the configured index has no input
        # channels (e.g. the USB mic index shifted after reboot), scan for a
        # USB input device, then fall back to the system default.
        def _find_input_device():
            if self._device_index is not None:
                # Explicit index configured — verify it has input channels.
                candidate = pa.get_device_info_by_index(self._device_index)
                if candidate["maxInputChannels"] >= 1:
                    return candidate, self._device_index
                log.warning(
                    "Configured device_index=%d (%s) has no input channels — falling back to default.",
                    self._device_index, candidate["name"],
                )
            # No index configured (or bad index) — use system default.
            # Don't scan for hw: devices directly: if PulseAudio is running it
            # owns the hw: device and direct access will fail with -9985.
            info_d = pa.get_default_input_device_info()
            log.info("Using default input device: %s", info_d["name"])
            return info_d, None

        info, resolved_index = _find_input_device()
        self._sample_rate = int(info["defaultSampleRate"])

        open_kwargs = {
            "format":           pyaudio.paInt16,
            "channels":         1,
            "rate":             self._sample_rate,
            "input":            True,
            "frames_per_buffer": self._frame_size,
        }
        if resolved_index is not None:
            open_kwargs["input_device_index"] = resolved_index

        stream = pa.open(**open_kwargs)
        log.info("Recorder started. device=%s rate=%d silence_rms=%d",
                 info["name"], self._sample_rate, self._cfg.silence_threshold_rms)

        threshold     = self._cfg.silence_threshold_rms
        silence_limit = self._cfg.silence_duration_seconds
        max_seconds   = self._cfg.max_recording_seconds

        # Pre-roll: circular buffer holding the last PRE_ROLL_SECONDS of frames
        pre_roll_frames = int(
            PRE_ROLL_SECONDS * self._sample_rate / self._frame_size
        )
        pre_roll: collections.deque = collections.deque(maxlen=pre_roll_frames)

        frames: list[bytes] = []
        silence_frames  = 0
        total_frames    = 0
        max_frames      = int(max_seconds * self._sample_rate / self._frame_size)
        silence_frames_limit = int(
            silence_limit * self._sample_rate / self._frame_size
        )

        try:
            while total_frames < max_frames:
                if self.isInterruptionRequested():
                    break

                frame = stream.read(self._frame_size, exception_on_overflow=False)
                rms = calculate_rms(frame)

                if not frames:
                    # Still in pre-roll / waiting for speech onset
                    pre_roll.append(frame)
                    if rms > threshold:
                        # Speech started — flush pre-roll into frames
                        frames.extend(pre_roll)
                        pre_roll.clear()
                        silence_frames = 0
                        log.debug("Speech onset detected (RMS=%.0f)", rms)
                else:
                    frames.append(frame)
                    if rms < threshold:
                        silence_frames += 1
                        if silence_frames >= silence_frames_limit:
                            log.debug(
                                "Silence detected after %.1fs — stopping.",
                                silence_frames * self._frame_size / self._sample_rate,
                            )
                            break
                    else:
                        silence_frames = 0

                total_frames += 1

        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

        if not frames:
            log.warning("Recorder: no speech detected within timeout.")
            return None

        pcm_data = b"".join(frames)
        wav_bytes = pcm_to_wav(pcm_data, self._sample_rate)
        duration = len(pcm_data) / (self._sample_rate * self._sample_width)
        log.info("Recording complete: %.2f seconds, %d bytes WAV.", duration, len(wav_bytes))
        return wav_bytes
