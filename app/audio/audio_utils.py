"""
Audio utility functions shared across the audio pipeline.
No Qt dependencies — pure Python/PyAudio helpers.
"""

import io
import struct
import wave
from typing import Optional

from app.services.logger import get_logger

log = get_logger(__name__)


def calculate_rms(frame_bytes: bytes) -> float:
    """
    Return the RMS (root mean square) energy of a 16-bit PCM frame.
    Higher values = louder audio. Typical quiet room: 100-300. Speech: 1000+.
    """
    count = len(frame_bytes) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"<{count}h", frame_bytes)
    mean_sq = sum(s * s for s in shorts) / count
    return mean_sq ** 0.5


def pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,   # bytes per sample (2 = 16-bit)
) -> bytes:
    """Wrap raw PCM bytes in a WAV header. Returns complete WAV file bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def list_input_devices() -> list[dict]:
    """
    Return a list of available PyAudio input devices.
    Each entry: {"index": int, "name": str, "default_sample_rate": float}
    Returns empty list if PyAudio is unavailable.
    """
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append({
                    "index": i,
                    "name": info["name"],
                    "default_sample_rate": info["defaultSampleRate"],
                })
        p.terminate()
        return devices
    except Exception as e:
        log.warning("Could not enumerate audio devices: %s", e)
        return []


def check_microphone(device_index: Optional[int] = None) -> bool:
    """
    Return True if a microphone is accessible and can open a stream.
    Used at startup to give an early warning if audio hardware is missing.
    """
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        kwargs = {
            "format": pyaudio.paInt16,
            "channels": 1,
            "rate": 16000,
            "input": True,
            "frames_per_buffer": 512,
        }
        if device_index is not None:
            kwargs["input_device_index"] = device_index
        stream = p.open(**kwargs)
        stream.read(512, exception_on_overflow=False)
        stream.stop_stream()
        stream.close()
        p.terminate()
        log.debug("Microphone check passed.")
        return True
    except Exception as e:
        log.warning("Microphone check failed: %s", e)
        return False
