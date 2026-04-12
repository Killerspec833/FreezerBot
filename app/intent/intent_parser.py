"""
IntentParser — converts a Whisper transcript into a ParsedIntent.

Flow:
  1. Build prompt (system + user message)
  2. POST to Groq API (llama-3.3-70b-versatile, temp=0.1)
  3. Parse JSON response → ParsedIntent
  4. Resolve location alias via LocationResolver
  5. On parse failure: retry once, then return UNKNOWN

Runs in IntentParserThread (QThread) so the UI stays responsive.
"""

import json
import re
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.config_manager import ConfigManager
from app.intent.location_resolver import LocationResolver
from app.intent.models import IntentType, ParsedIntent
from app.services.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a freezer inventory assistant. Your job is to parse voice commands
about food inventory and return structured JSON. The system has exactly three
storage locations: "basement_freezer", "kitchen_freezer", and "fridge".

The user may refer to locations using informal names. Known aliases:
- basement_freezer: "basement", "chest freezer", "basement freezer"
- kitchen_freezer: "kitchen freezer", "kitchen", "tall one", "tall freezer"
- fridge: "fridge", "fridge freezer", "small freezer"

Always normalize item names: lowercase, singular where unambiguous, trimmed.

Return ONLY a JSON object. No explanation, no markdown, no code fences.

JSON schema:
{
  "intent": one of ["ADD", "REMOVE", "QUERY", "LIST", "CONFIRM", "DENY", "UNKNOWN"],
  "item_name": string or null,
  "quantity": string or null,
  "location": one of ["basement_freezer", "kitchen_freezer", "fridge", null],
  "confidence": float between 0.0 and 1.0,
  "notes": string or null
}

Rules:
- For ADD: item_name and quantity are required. location defaults to null if not mentioned.
- For REMOVE: item_name is required. quantity and location are optional hints.
- For QUERY: item_name is required. location is optional filter.
- For LIST: location is required. item_name is null.
- For CONFIRM: all fields except intent are null. Examples: "yes", "correct", "that's right", "yep", "sure".
- For DENY: all fields except intent are null. Examples: "no", "wrong", "cancel", "nope", "start over", "done", "finished", "close", "go back", "exit", "I'm done".
- UNKNOWN: use when the command is unintelligible or clearly not inventory-related.
- If quantity is not stated for ADD, set quantity to "1".
- The "notes" field is for your internal observations only. It is never shown to the user.
- confidence reflects how certain you are of the intent and data extraction.

Examples:

Input: "Add ground beef 2 packages basement freezer"
Output: {"intent":"ADD","item_name":"ground beef","quantity":"2 packages","location":"basement_freezer","confidence":0.97,"notes":null}

Input: "Remove chicken thighs"
Output: {"intent":"REMOVE","item_name":"chicken thighs","quantity":null,"location":null,"confidence":0.95,"notes":null}

Input: "Is there any beef?"
Output: {"intent":"QUERY","item_name":"beef","quantity":null,"location":null,"confidence":0.95,"notes":null}

Input: "What's in the tall one?"
Output: {"intent":"LIST","item_name":null,"quantity":null,"location":"kitchen_freezer","confidence":0.93,"notes":"User said tall one, resolved to kitchen_freezer"}

Input: "Yeah that's right"
Output: {"intent":"CONFIRM","item_name":null,"quantity":null,"location":null,"confidence":0.90,"notes":null}

Input: "No that's wrong"
Output: {"intent":"DENY","item_name":null,"quantity":null,"location":null,"confidence":0.92,"notes":null}

Input: "Done"
Output: {"intent":"DENY","item_name":null,"quantity":null,"location":null,"confidence":0.97,"notes":null}

Input: "I'm finished"
Output: {"intent":"DENY","item_name":null,"quantity":null,"location":null,"confidence":0.95,"notes":null}
"""


# ---------------------------------------------------------------------------
# Parser (sync, used by the thread)
# ---------------------------------------------------------------------------

class IntentParser:
    def __init__(self, cfg_manager: ConfigManager):
        self._cfg = cfg_manager
        self._resolver = LocationResolver(cfg_manager)

    def parse(self, transcript: str) -> ParsedIntent:
        """Parse transcript → ParsedIntent. Retries once on JSON failure."""
        raw_json = self._call_groq(transcript)

        if raw_json is None:
            log.warning("Groq call failed — returning UNKNOWN.")
            return ParsedIntent(
                intent_type=IntentType.UNKNOWN,
                raw_transcript=transcript,
            )

        intent = self._parse_json(raw_json, transcript)
        if intent is None:
            # Retry once with a stricter prompt
            log.info("JSON parse failed — retrying Groq call.")
            raw_json2 = self._call_groq(transcript, retry=True)
            if raw_json2:
                intent = self._parse_json(raw_json2, transcript)

        if intent is None:
            log.warning("Could not parse Groq response — returning UNKNOWN.")
            return ParsedIntent(
                intent_type=IntentType.UNKNOWN,
                raw_transcript=transcript,
            )

        # Resolve location alias if needed
        if intent.location is not None:
            resolved = self._resolver.resolve(intent.location)
            intent.location = resolved

        log.info(
            "Intent: %s  item='%s'  qty='%s'  loc='%s'  conf=%.2f",
            intent.intent_type.name,
            intent.item_name,
            intent.quantity,
            intent.location,
            intent.confidence,
        )
        return intent

    # ------------------------------------------------------------------
    # Groq API call
    # ------------------------------------------------------------------

    def _call_groq(self, transcript: str, retry: bool = False) -> Optional[str]:
        try:
            from groq import Groq

            client = Groq(api_key=self._cfg.config.api_keys.groq_api_key)

            user_msg = f'Voice command transcript: "{transcript}"'
            if retry:
                user_msg += (
                    "\n\nIMPORTANT: Return ONLY valid JSON. "
                    "No markdown, no explanation, no code fences."
                )

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=256,
            )
            raw = response.choices[0].message.content.strip()
            log.debug("Groq raw response: %s", raw)
            return raw

        except Exception as e:
            log.error("Groq intent API error: %s", e)
            return None

    # ------------------------------------------------------------------
    # JSON → ParsedIntent
    # ------------------------------------------------------------------

    def _parse_json(
        self, raw: str, transcript: str
    ) -> Optional[ParsedIntent]:
        # Strip markdown code fences if the model ignored the instruction
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.warning("JSON decode error: %s — raw: %s", e, cleaned[:200])
            return None

        intent_str = str(data.get("intent", "UNKNOWN")).upper()
        try:
            intent_type = IntentType[intent_str]
        except KeyError:
            log.warning("Unknown intent value from model: '%s'", intent_str)
            intent_type = IntentType.UNKNOWN

        return ParsedIntent(
            intent_type=intent_type,
            item_name=data.get("item_name") or None,
            quantity=data.get("quantity") or None,
            location=data.get("location") or None,
            confidence=float(data.get("confidence", 0.0)),
            raw_transcript=transcript,
            notes=data.get("notes") or None,
        )


# ---------------------------------------------------------------------------
# QThread wrapper
# ---------------------------------------------------------------------------

class IntentParserThread(QThread):
    intent_parsed = pyqtSignal(object)   # emits ParsedIntent
    error         = pyqtSignal(str)

    def __init__(self, transcript: str, cfg_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self._transcript = transcript
        self._cfg = cfg_manager

    def run(self) -> None:
        try:
            parser = IntentParser(self._cfg)
            intent = parser.parse(self._transcript)
            self.intent_parsed.emit(intent)
        except Exception as e:
            log.error("IntentParserThread unhandled error: %s", e)
            self.error.emit(str(e))
            self.intent_parsed.emit(
                ParsedIntent(
                    intent_type=IntentType.UNKNOWN,
                    raw_transcript=self._transcript,
                )
            )
