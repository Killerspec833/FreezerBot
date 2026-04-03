"""
Tests for LocationResolver — canonical key, alias, fuzzy, unresolvable.
No Qt, no hardware, no API keys.
"""

import pytest

from app.intent.location_resolver import LocationResolver


@pytest.fixture
def resolver(cfg):
    return LocationResolver(cfg)


class TestResolve:
    def test_canonical_key_resolves_to_itself(self, resolver):
        assert resolver.resolve("basement_freezer") == "basement_freezer"
        assert resolver.resolve("kitchen_freezer") == "kitchen_freezer"
        assert resolver.resolve("fridge") == "fridge"

    def test_canonical_key_case_insensitive(self, resolver):
        assert resolver.resolve("Basement_Freezer") == "basement_freezer"
        assert resolver.resolve("FRIDGE") == "fridge"

    def test_exact_alias_match(self, resolver):
        assert resolver.resolve("basement") == "basement_freezer"
        assert resolver.resolve("kitchen") == "kitchen_freezer"
        assert resolver.resolve("tall one") == "kitchen_freezer"
        assert resolver.resolve("chest freezer") == "basement_freezer"
        assert resolver.resolve("small freezer") == "fridge"

    def test_alias_case_insensitive(self, resolver):
        assert resolver.resolve("BASEMENT") == "basement_freezer"
        assert resolver.resolve("Kitchen") == "kitchen_freezer"

    def test_alias_with_surrounding_whitespace(self, resolver):
        assert resolver.resolve("  basement  ") == "basement_freezer"

    def test_fuzzy_alias_match(self, resolver):
        # "basment" (typo) should fuzzy-match "basement" → basement_freezer
        result = resolver.resolve("basment freezer")
        assert result == "basement_freezer"

    def test_none_input_returns_none(self, resolver):
        assert resolver.resolve(None) is None

    def test_empty_string_returns_none(self, resolver):
        assert resolver.resolve("") is None

    def test_unresolvable_returns_none(self, resolver):
        assert resolver.resolve("the moon") is None
        assert resolver.resolve("xyz123") is None


class TestAllDisplayNames:
    def test_returns_all_three_locations(self, resolver):
        names = resolver.all_display_names()
        assert set(names.keys()) == {"basement_freezer", "kitchen_freezer", "fridge"}

    def test_display_names_match_config(self, resolver):
        names = resolver.all_display_names()
        assert names["basement_freezer"] == "Basement Freezer"
        assert names["fridge"] == "Fridge"
