"""
Intent models — pure dataclasses, no API or database logic.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class IntentType(Enum):
    ADD     = auto()   # Add item to inventory
    REMOVE  = auto()   # Remove / consume item
    QUERY   = auto()   # "Is there any beef?"
    LIST    = auto()   # "What's in the basement freezer?"
    CONFIRM = auto()   # "Yes" / "That's right"
    DENY    = auto()   # "No" / "Wrong" / "Cancel"
    UNKNOWN = auto()   # Unintelligible or off-topic


@dataclass
class ParsedIntent:
    intent_type:    IntentType
    item_name:      Optional[str]   = None  # normalised, lowercase
    quantity:       Optional[str]   = None  # free-text e.g. "2 packages"
    location:       Optional[str]   = None  # canonical key after resolution
    confidence:     float           = 0.0
    raw_transcript: Optional[str]   = None  # original Whisper text
    notes:          Optional[str]   = None  # Gemini internal notes (never shown)

    # Set by AppController during REMOVE flow after fuzzy matching.
    # These are proper optional fields (not dynamic attributes) so that
    # static analysis, type checkers, and dataclasses.asdict() all see them.
    _resolved_item_id:       Optional[int] = field(default=None, repr=False)
    _resolved_item_name:     Optional[str] = field(default=None, repr=False)
    _resolved_item_location: Optional[str] = field(default=None, repr=False)
    _resolved_item_quantity: Optional[str] = field(default=None, repr=False)
