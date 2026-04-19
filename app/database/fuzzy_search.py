"""
FuzzySearch — finds inventory items matching a spoken query.

Uses rapidfuzz token_set_ratio which handles:
  - Partial queries ("beef" matching "ground beef" with 100% score)
  - Word order differences ("beef ground" vs "ground beef")
  - Subset matching ("chicken" matching "chicken breast" and "chicken thighs")
  - Minor spelling variations

REMOVE logic:
  score >= 90  → remove directly without extra confirmation
  70 – 89      → show confirmation screen with matched item
  < 70         → no match, inform user
"""

from app.database.db_manager import DatabaseManager
from app.database.models import InventoryItem, SearchResult
from app.services.logger import get_logger

log = get_logger(__name__)


def _normalise_phrase(text: str) -> str:
    """Lower-case and collapse whitespace for safe exact-name comparisons."""
    return " ".join(text.strip().lower().split())


class FuzzySearch:
    def __init__(self, db: DatabaseManager, default_threshold: int = 70):
        self._db = db
        self._threshold = default_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        location_filter: str | None = None,
    ) -> list[SearchResult]:
        """
        Search inventory for items matching query.

        Returns SearchResult list sorted by score descending,
        filtered to scores >= threshold.

        **Duplicate-name deduplication (silent drop):**
        When ``location_filter`` is ``None`` this method fetches all items
        across every location and builds a ``name → item`` map that keeps
        only the *first* row encountered for each unique ``item_name``.
        Subsequent rows with the same name (e.g. "chicken" stored in both
        the basement freezer and the fridge) are silently discarded, so the
        result set will contain at most one entry per name and will not
        reflect the full inventory picture for that name.

        If you need all locations for a given item — for example when
        answering a QUERY intent — call ``search_all_locations()`` instead.
        It keys on ``(item_name, location)`` so every location-specific row
        is preserved.  Only use this method directly when you have already
        narrowed to a single location via ``location_filter``, or when you
        explicitly want the first-match-wins deduplication behaviour (e.g.
        in the REMOVE flow, where there is an unambiguous target location).
        """
        from rapidfuzz import fuzz, process

        if location_filter:
            candidates = self._db.list_by_location(location_filter)
        else:
            candidates = self._db.get_all_items()

        if not candidates:
            return []

        # Build name→item map (use first item if duplicate names exist)
        name_map: dict[str, InventoryItem] = {}
        for item in candidates:
            if item.item_name not in name_map:
                name_map[item.item_name] = item

        names = list(name_map.keys())
        query_normalised = query.strip().lower()

        matches = process.extract(
            query_normalised,
            names,
            scorer=fuzz.token_set_ratio,
            limit=10,
            score_cutoff=self._threshold,
        )

        results = []
        for name, score, _ in matches:
            item = name_map[name]
            results.append(SearchResult(item=item, score=float(score)))
            log.debug("Fuzzy match: '%s' → '%s' (%.1f%%)", query, name, score)

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def search_all_locations(
        self,
        query: str,
        location_filter: str | None = None,
    ) -> list[SearchResult]:
        """Search across all locations, deduplicating by item name + location."""
        from rapidfuzz import fuzz, process

        if location_filter:
            all_items = self._db.list_by_location(location_filter)
        else:
            all_items = self._db.get_all_items()
        if not all_items:
            return []

        # Key by (item_name, location) to preserve multi-location entries
        key_map: dict[str, InventoryItem] = {
            f"{item.item_name}|{item.location}": item
            for item in all_items
        }

        # Match only against item names, then recover full items
        name_to_keys: dict[str, list[str]] = {}
        for key, item in key_map.items():
            name_to_keys.setdefault(item.item_name, []).append(key)

        names = list(name_to_keys.keys())
        query_normalised = query.strip().lower()

        matches = process.extract(
            query_normalised,
            names,
            scorer=fuzz.token_set_ratio,
            limit=20,
            score_cutoff=self._threshold,
        )

        results = []
        for name, score, _ in matches:
            for key in name_to_keys[name]:
                item = key_map[key]
                results.append(SearchResult(item=item, score=float(score)))

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # REMOVE decision helper
    # ------------------------------------------------------------------

    def find_for_removal(
        self,
        query: str,
        location_filter: str | None = None,
    ) -> tuple[str, SearchResult | None]:
        """
        Returns (decision, best_match) where decision is one of:
          "direct"  — score >= 90, remove without asking
          "confirm" — score 70-89, show confirmation screen
          "none"    — no match found
        """
        results = self.search(query, location_filter)
        if not results:
            log.info("No fuzzy match for removal query: '%s'", query)
            return "none", None

        best = results[0]
        query_normalised = _normalise_phrase(query)
        item_name_normalised = _normalise_phrase(best.item.item_name)

        if best.score >= 90 and query_normalised == item_name_normalised:
            log.info(
                "Direct removal match: '%s' → '%s' (%.1f%%)",
                query, best.item.item_name, best.score,
            )
            return "direct", best
        else:
            log.info(
                "Removal needs confirmation: '%s' → '%s' (%.1f%%)",
                query, best.item.item_name, best.score,
            )
            return "confirm", best

    # ------------------------------------------------------------------
    # Query response formatting
    # ------------------------------------------------------------------

    def format_query_response(
        self,
        query: str,
        results: list[SearchResult],
        location_display_fn,   # callable(canonical_key) -> display_name
    ) -> str:
        """
        Build a natural-language TTS response string for a QUERY intent.

        location_display_fn: takes a canonical location key, returns display name.
        """
        if not results:
            return f"I don't see any {query} in the freezer."

        if len(results) == 1:
            r = results[0]
            loc = location_display_fn(r.item.location)
            return (
                f"Yes, there is {r.item.quantity} of {r.item.item_name} "
                f"in the {loc}."
            )

        if len(results) <= 3:
            parts = []
            for r in results:
                loc = location_display_fn(r.item.location)
                parts.append(f"{r.item.quantity} of {r.item.item_name} in the {loc}")
            return "I found " + ", and ".join(parts) + "."

        # 4+ results — read top 3 and note there are more
        parts = []
        for r in results[:3]:
            loc = location_display_fn(r.item.location)
            parts.append(f"{r.item.item_name} in the {loc}")
        return (
            f"I found {len(results)} items matching {query}. "
            f"The top results are: " + ", ".join(parts) + ". "
            f"See the screen for the full list."
        )
