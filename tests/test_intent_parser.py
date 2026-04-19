"""
Tests for IntentParser — JSON parsing, markdown stripping, intent mapping.

No network API calls are made: we test _parse_json() directly and mock
_call_groq() to return canned strings for end-to-end parse() tests.
"""

import json
from unittest.mock import patch

import pytest

from app.intent.intent_parser import IntentParser
from app.intent.models import IntentType


@pytest.fixture
def parser(cfg):
    return IntentParser(cfg)


class TestParseJson:
    """Unit tests for IntentParser._parse_json — no network required."""

    def _make_json(self, intent, item=None, qty=None, loc=None, conf=0.9):
        return json.dumps({
            "intent": intent,
            "item_name": item,
            "quantity": qty,
            "location": loc,
            "confidence": conf,
            "notes": None,
        })

    def test_add_intent(self, parser):
        raw = self._make_json("ADD", item="ground beef", qty="2 packages",
                              loc="basement_freezer")
        result = parser._parse_json(raw, "add ground beef")
        assert result is not None
        assert result.intent_type == IntentType.ADD
        assert result.item_name == "ground beef"
        assert result.quantity == "2 packages"
        assert result.location == "basement_freezer"
        assert result.confidence == pytest.approx(0.9)

    def test_remove_intent(self, parser):
        raw = self._make_json("REMOVE", item="chicken thighs", conf=0.95)
        result = parser._parse_json(raw, "remove chicken thighs")
        assert result.intent_type == IntentType.REMOVE
        assert result.item_name == "chicken thighs"
        assert result.quantity is None

    def test_query_intent(self, parser):
        raw = self._make_json("QUERY", item="beef", conf=0.9)
        result = parser._parse_json(raw, "is there any beef")
        assert result.intent_type == IntentType.QUERY
        assert result.item_name == "beef"

    def test_list_intent(self, parser):
        raw = self._make_json("LIST", loc="kitchen_freezer", conf=0.93)
        result = parser._parse_json(raw, "what's in the kitchen")
        assert result.intent_type == IntentType.LIST
        assert result.location == "kitchen_freezer"

    def test_confirm_intent(self, parser):
        raw = self._make_json("CONFIRM", conf=0.9)
        result = parser._parse_json(raw, "yes")
        assert result.intent_type == IntentType.CONFIRM

    def test_deny_intent(self, parser):
        raw = self._make_json("DENY", conf=0.92)
        result = parser._parse_json(raw, "no")
        assert result.intent_type == IntentType.DENY

    def test_unknown_intent(self, parser):
        raw = self._make_json("UNKNOWN", conf=0.1)
        result = parser._parse_json(raw, "blah blah")
        assert result.intent_type == IntentType.UNKNOWN

    def test_unrecognised_intent_value_falls_back_to_unknown(self, parser):
        raw = json.dumps({"intent": "DANCE", "item_name": None,
                          "quantity": None, "location": None, "confidence": 0.5})
        result = parser._parse_json(raw, "dance")
        assert result.intent_type == IntentType.UNKNOWN

    def test_strips_markdown_code_fence(self, parser):
        inner = self._make_json("ADD", item="steak", qty="1")
        raw = f"```json\n{inner}\n```"
        result = parser._parse_json(raw, "add steak")
        assert result is not None
        assert result.intent_type == IntentType.ADD

    def test_strips_plain_code_fence(self, parser):
        inner = self._make_json("LIST", loc="fridge")
        raw = f"```\n{inner}\n```"
        result = parser._parse_json(raw, "list fridge")
        assert result is not None
        assert result.intent_type == IntentType.LIST

    def test_invalid_json_returns_none(self, parser):
        result = parser._parse_json("not json at all", "transcript")
        assert result is None

    def test_null_item_name_becomes_none(self, parser):
        raw = self._make_json("REMOVE", item=None)
        result = parser._parse_json(raw, "remove")
        assert result.item_name is None

    def test_raw_transcript_preserved(self, parser):
        raw = self._make_json("ADD", item="peas", qty="1")
        result = parser._parse_json(raw, "add peas to the fridge")
        assert result.raw_transcript == "add peas to the fridge"


class TestParseMocked:
    """End-to-end parse() with _call_groq mocked — tests location resolution."""

    def _good_response(self, intent, item=None, qty=None, loc=None):
        return json.dumps({
            "intent": intent,
            "item_name": item,
            "quantity": qty,
            "location": loc,
            "confidence": 0.95,
            "notes": None,
        })

    def test_parse_add_with_known_location(self, parser):
        resp = self._good_response("ADD", item="salmon", qty="2",
                                   loc="basement_freezer")
        with patch.object(parser, "_call_groq", return_value=resp):
            intent = parser.parse("add 2 salmon to the basement")
        assert intent.intent_type == IntentType.ADD
        assert intent.location == "basement_freezer"

    def test_parse_groq_failure_returns_unknown(self, parser):
        with patch.object(parser, "_call_groq", return_value=None):
            intent = parser.parse("completely unintelligible $$#@")
        assert intent.intent_type == IntentType.UNKNOWN

    def test_parse_bad_json_retries_once(self, parser):
        # First call returns garbage, retry also returns garbage → UNKNOWN
        with patch.object(parser, "_call_groq", return_value="{{bad json"):
            intent = parser.parse("something")
        assert intent.intent_type == IntentType.UNKNOWN

    def test_parse_retry_succeeds(self, parser):
        # First call fails JSON, second call succeeds
        good = self._good_response("QUERY", item="beef")
        calls = ["{{bad", good]
        with patch.object(parser, "_call_groq", side_effect=calls):
            intent = parser.parse("is there beef")
        assert intent.intent_type == IntentType.QUERY
