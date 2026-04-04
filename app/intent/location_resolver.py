"""
LocationResolver — maps raw location strings to canonical keys.

Resolution order:
  1. Already a canonical key ("basement_freezer") → return as-is
  2. Case-insensitive exact match against any alias → return canonical key
  3. Fuzzy match (rapidfuzz token_sort_ratio >= 80) against all aliases
  4. None → caller will ask user to clarify

This is a fallback layer. Gemini's system prompt instructs it to resolve
aliases directly, so layer 3-4 should rarely be needed in practice.
"""

from typing import Optional

from app.core.config_manager import ConfigManager
from app.services.logger import get_logger

log = get_logger(__name__)

_FUZZY_THRESHOLD = 80


class LocationResolver:
    def __init__(self, cfg_manager: ConfigManager):
        self._cfg = cfg_manager
        # Build flat alias → canonical_key lookup at init time
        self._alias_map: dict[str, str] = {}
        for key, loc in cfg_manager.config.locations.items():
            # Canonical key maps to itself
            self._alias_map[key.lower()] = key
            for alias in loc.aliases:
                self._alias_map[alias.lower().strip()] = key

        self._all_aliases = list(self._alias_map.keys())
        self._canonical_keys = list(cfg_manager.config.locations.keys())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, raw: Optional[str]) -> Optional[str]:
        """
        Return a canonical location key for raw, or None if unresolvable.
        raw may be None (e.g. not mentioned in transcript) → returns None.
        """
        if raw is None:
            return None

        raw_clean = raw.strip().lower()

        if not raw_clean:
            return None

        # Layer 1 — already a canonical key
        if raw_clean in [k.lower() for k in self._canonical_keys]:
            # Return the correctly-cased key
            for key in self._canonical_keys:
                if key.lower() == raw_clean:
                    log.debug("Location resolved (canonical): '%s' → '%s'", raw, key)
                    return key

        # Layer 2 — exact alias match
        if raw_clean in self._alias_map:
            resolved = self._alias_map[raw_clean]
            log.debug("Location resolved (alias): '%s' → '%s'", raw, resolved)
            return resolved

        # Layer 3 — fuzzy match
        try:
            from rapidfuzz import fuzz, process
            match = process.extractOne(
                raw_clean,
                self._all_aliases,
                scorer=fuzz.token_set_ratio,
                score_cutoff=_FUZZY_THRESHOLD,
            )
            if match:
                alias, score, _ = match
                resolved = self._alias_map[alias]
                log.info(
                    "Location resolved (fuzzy %.0f%%): '%s' → '%s'",
                    score, raw, resolved,
                )
                return resolved
        except ImportError:
            log.warning("rapidfuzz not available for location fuzzy matching.")

        # Layer 4 — unresolvable
        log.warning("Location unresolvable: '%s'", raw)
        return None

    def all_display_names(self) -> dict[str, str]:
        """Return {canonical_key: display_name} for all known locations."""
        return {
            key: loc.display_name
            for key, loc in self._cfg.config.locations.items()
        }
