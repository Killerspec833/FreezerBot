"""
Tests for FuzzySearch — search, find_for_removal decisions, format_query_response.
No Qt, no hardware, no API keys.
"""

import pytest

from app.database.models import InventoryItem, SearchResult


def _item(id, name, qty, loc):
    return InventoryItem(
        id=id, item_name=name, quantity=qty, location=loc,
        created_at="2024-01-01", updated_at="2024-01-01",
    )


class TestSearch:
    def test_exact_match(self, db, fuzzy):
        db.add_item("ground beef", "2 packages", "basement_freezer")
        results = fuzzy.search("ground beef")
        assert len(results) == 1
        assert results[0].item.item_name == "ground beef"

    def test_partial_query_matches(self, db, fuzzy):
        # "beef" should match "ground beef" via token_set_ratio
        db.add_item("ground beef", "2 packages", "basement_freezer")
        results = fuzzy.search("beef")
        assert any(r.item.item_name == "ground beef" for r in results)

    def test_below_threshold_returns_nothing(self, db, fuzzy):
        db.add_item("salmon fillet", "3", "fridge")
        results = fuzzy.search("xyz123")
        assert results == []

    def test_empty_db_returns_empty(self, fuzzy):
        assert fuzzy.search("anything") == []

    def test_results_sorted_by_score_desc(self, db, fuzzy):
        db.add_item("chicken breast", "1", "basement_freezer")
        db.add_item("chicken thighs", "4", "kitchen_freezer")
        results = fuzzy.search("chicken breast")
        assert results[0].score >= results[-1].score

    def test_location_filter_restricts_results(self, db, fuzzy):
        db.add_item("beef", "1", "basement_freezer")
        db.add_item("beef", "1", "kitchen_freezer")
        results = fuzzy.search("beef", location_filter="fridge")
        assert results == []

    def test_location_filter_returns_correct_location(self, db, fuzzy):
        db.add_item("beef", "1", "basement_freezer")
        db.add_item("beef", "1", "kitchen_freezer")
        results = fuzzy.search("beef", location_filter="basement_freezer")
        assert all(r.item.location == "basement_freezer" for r in results)


class TestSearchAllLocations:
    def test_finds_same_item_in_multiple_locations(self, db, fuzzy):
        db.add_item("beef", "1", "basement_freezer")
        db.add_item("beef", "2", "kitchen_freezer")
        results = fuzzy.search_all_locations("beef")
        locations = {r.item.location for r in results}
        assert "basement_freezer" in locations
        assert "kitchen_freezer" in locations

    def test_empty_db_returns_empty(self, fuzzy):
        assert fuzzy.search_all_locations("anything") == []


class TestFindForRemoval:
    def test_direct_decision_for_high_score(self, db, fuzzy):
        # Exact match should score 100 → "direct"
        db.add_item("ground beef", "2 packages", "basement_freezer")
        decision, match = fuzzy.find_for_removal("ground beef")
        assert decision == "direct"
        assert match is not None
        assert match.item.item_name == "ground beef"

    def test_none_decision_when_no_match(self, db, fuzzy):
        db.add_item("salmon", "1", "fridge")
        decision, match = fuzzy.find_for_removal("xyz123abc")
        assert decision == "none"
        assert match is None

    def test_none_decision_on_empty_db(self, fuzzy):
        decision, match = fuzzy.find_for_removal("beef")
        assert decision == "none"
        assert match is None

    def test_confirm_decision_for_mid_score(self, db, fuzzy):
        # Use a threshold of 70 and a query that scores in 70-89 range
        from app.database.fuzzy_search import FuzzySearch
        low_threshold_fuzzy = FuzzySearch(db, default_threshold=70)
        db.add_item("chicken thighs boneless skinless", "4", "basement_freezer")
        decision, match = low_threshold_fuzzy.find_for_removal("chicken thigh")
        # token_set_ratio("chicken thigh", "chicken thighs boneless skinless") should be >= 70
        assert decision in ("direct", "confirm")
        assert match is not None


class TestFormatQueryResponse:
    def _make_result(self, name, qty, loc, score=95.0):
        item = _item(1, name, qty, loc)
        return SearchResult(item=item, score=score)

    def _loc_fn(self, key):
        return {"basement_freezer": "Basement Freezer",
                "kitchen_freezer": "Kitchen Freezer",
                "fridge": "Fridge"}.get(key, key)

    def test_empty_results(self, fuzzy):
        resp = fuzzy.format_query_response("beef", [], self._loc_fn)
        assert "don't see" in resp.lower() or "no" in resp.lower()

    def test_single_result(self, fuzzy):
        results = [self._make_result("ground beef", "2 packages", "basement_freezer")]
        resp = fuzzy.format_query_response("beef", results, self._loc_fn)
        assert "ground beef" in resp
        assert "Basement Freezer" in resp

    def test_two_results(self, fuzzy):
        results = [
            self._make_result("beef", "1", "basement_freezer"),
            self._make_result("beef", "2", "kitchen_freezer"),
        ]
        resp = fuzzy.format_query_response("beef", results, self._loc_fn)
        assert "Basement Freezer" in resp
        assert "Kitchen Freezer" in resp

    def test_four_or_more_results_mentions_count(self, fuzzy):
        results = [
            self._make_result(f"item{i}", "1", "basement_freezer")
            for i in range(5)
        ]
        resp = fuzzy.format_query_response("item", results, self._loc_fn)
        assert "5" in resp
