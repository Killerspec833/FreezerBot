"""
Data models for the inventory database.
Pure dataclasses — no database logic here.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class InventoryItem:
    id: int
    item_name: str
    quantity: str
    location: str           # canonical key e.g. "basement_freezer"
    created_at: str         # ISO-8601 UTC string
    updated_at: str         # ISO-8601 UTC string


@dataclass
class AuditEntry:
    id: int
    action: str             # "ADD" or "REMOVE"
    item_name: str
    quantity: Optional[str]
    location: Optional[str]
    timestamp: str          # ISO-8601 UTC string
    transcript: Optional[str]


@dataclass
class SearchResult:
    item: InventoryItem
    score: float            # 0.0 – 100.0 similarity score
