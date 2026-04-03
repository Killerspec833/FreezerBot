"""
SpeechToText — sends WAV bytes to Groq Whisper API and returns a transcript.

Runs as a one-shot QThread per utterance.
Emits transcript_ready(str) on success, transcript_failed(str) on error.
"""

import io

from PyQt6.QtCore import QThread, pyqtSignal

from app.services.logger import get_logger

log = get_logger(__name__)

_WHISPER_MODEL = "whisper-large-v3"


class STTThread(QThread):
    transcript_ready  = pyqtSignal(str)
    transcript_failed = pyqtSignal(str)

    def __init__(self, wav_bytes: bytes, groq_api_key: str, parent=None):
        super().__init__(parent)
        self._wav_bytes   = wav_bytes
        self._groq_key    = groq_api_key

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            transcript = self._transcribe()
            if transcript:
                log.info("Transcript: '%s'", transcript)
                self.transcript_ready.emit(transcript)
            else:
                self.transcript_failed.emit("Empty transcript returned.")
        except Exception as e:
            log.error("STT error: %s", e)
            self.transcript_failed.emit(str(e))

    # ------------------------------------------------------------------
    # Groq Whisper call
    # ------------------------------------------------------------------

    def _transcribe(self) -> str:
        from groq import Groq

        client = Groq(api_key=self._groq_key)

        # Groq SDK expects a file-like tuple: (filename, file_obj, mime_type)
        audio_file = ("audio.wav", io.BytesIO(self._wav_bytes), "audio/wav")

        response = client.audio.transcriptions.create(
            model=_WHISPER_MODEL,
            file=audio_file,
            language="en",
            response_format="text",
        )

        # response is a plain string when response_format="text"
        transcript = str(response).strip()
        log.debug("Groq Whisper raw response: '%s'", transcript[:120])
        return transcript
