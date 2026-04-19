"""
Tests for DatabaseManager — CRUD, audit log, WAL mode, schema version.
No Qt, no hardware, no API keys.
"""

import pytest


class TestAddItem:
    def test_returns_inventory_item(self, db):
        item = db.add_item("Chicken Breast", "2 bags", "basement_freezer")
        assert item.id is not None
        assert item.item_name == "chicken breast"   # normalised to lowercase
        assert item.quantity == "2 bags"
        assert item.location == "basement_freezer"

    def test_normalises_name_lowercase_and_stripped(self, db):
        item = db.add_item("  GROUND BEEF  ", "1 package", "kitchen_freezer")
        assert item.item_name == "ground beef"

    def test_persists_to_disk(self, db):
        db.add_item("salmon", "3 fillets", "fridge")
        all_items = db.get_all_items()
        assert any(i.item_name == "salmon" for i in all_items)

    def test_multiple_items_get_unique_ids(self, db):
        a = db.add_item("beef", "1", "basement_freezer")
        b = db.add_item("pork", "1", "basement_freezer")
        assert a.id != b.id

    def test_merges_numeric_quantity_for_same_item_and_location(self, db):
        db.add_item("beef", "1 pack", "basement_freezer")
        item = db.add_item("beef", "2 pack", "basement_freezer")
        assert item.quantity == "3 packs"
        assert len(db.get_all_items()) == 1


class TestRemoveItem:
    def test_removes_existing_item(self, db):
        item = db.add_item("steak", "2", "basement_freezer")
        result = db.remove_item(item.id)
        assert result is True
        assert all(i.id != item.id for i in db.get_all_items())

    def test_returns_false_for_missing_id(self, db):
        result = db.remove_item(99999)
        assert result is False

    def test_does_not_raise_for_missing_id(self, db):
        # Should log a warning, not crash
        db.remove_item(0)

    def test_remove_quantity_decrements_when_possible(self, db):
        item = db.add_item("steak", "3 bags", "basement_freezer")
        status, updated = db.remove_quantity(item.id, "1 bag")
        assert status == "decremented"
        assert updated.quantity == "2 bags"


class TestGetAllItems:
    def test_empty_db_returns_empty_list(self, db):
        assert db.get_all_items() == []

    def test_ordered_by_location_then_name(self, db):
        db.add_item("zucchini", "1", "basement_freezer")
        db.add_item("apple", "1", "basement_freezer")
        db.add_item("mango", "1", "kitchen_freezer")
        items = db.get_all_items()
        assert items[0].item_name == "apple"
        assert items[1].item_name == "zucchini"
        assert items[2].item_name == "mango"


class TestListByLocation:
    def test_filters_by_location(self, db):
        db.add_item("beef", "1", "basement_freezer")
        db.add_item("milk", "1", "fridge")
        items = db.list_by_location("fridge")
        assert len(items) == 1
        assert items[0].item_name == "milk"

    def test_returns_empty_for_empty_location(self, db):
        db.add_item("beef", "1", "basement_freezer")
        assert db.list_by_location("kitchen_freezer") == []


class TestGetItemNames:
    def test_returns_distinct_names(self, db):
        db.add_item("beef", "1", "basement_freezer")
        db.add_item("beef", "2", "kitchen_freezer")   # duplicate name
        db.add_item("chicken", "1", "fridge")
        names = db.get_item_names()
        assert sorted(names) == ["beef", "chicken"]

    def test_filtered_by_location(self, db):
        db.add_item("beef", "1", "basement_freezer")
        db.add_item("chicken", "1", "kitchen_freezer")
        names = db.get_item_names("basement_freezer")
        assert names == ["beef"]


class TestAuditLog:
    def test_log_action_add(self, db):
        db.add_item("tuna", "1 can", "fridge")
        db.log_action("ADD", "tuna", quantity="1 can", location="fridge", transcript="add tuna")
        entries = db.get_audit_log()
        assert len(entries) == 1
        assert entries[0].action == "ADD"
        assert entries[0].item_name == "tuna"
        assert entries[0].transcript == "add tuna"

    def test_get_audit_log_ordered_by_timestamp_desc(self, db):
        db.log_action("ADD", "apple", quantity="1")
        db.log_action("REMOVE", "banana", quantity="2")
        entries = db.get_audit_log()
        assert entries[0].action == "REMOVE"   # most recent first
        assert entries[1].action == "ADD"

    def test_log_action_stores_none_fields(self, db):
        db.log_action("REMOVE", "steak")
        entry = db.get_audit_log()[0]
        assert entry.quantity is None
        assert entry.location is None
        assert entry.transcript is None

    def test_limit_respected(self, db):
        for i in range(10):
            db.log_action("ADD", f"item{i}")
        entries = db.get_audit_log(limit=3)
        assert len(entries) == 3


class TestWALAndSchema:
    def test_wal_journal_mode(self, db):
        row = db._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_schema_version_seeded(self, db):
        row = db._conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
        assert row["v"] == 1

    def test_tables_exist(self, db):
        tables = {
            r[0]
            for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "inventory" in tables
        assert "audit_log" in tables
        assert "schema_version" in tables
