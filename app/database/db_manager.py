"""
DatabaseManager — all SQLite operations for Freezerbot.

Key design decisions:
  - WAL journal mode: reduces corruption risk on unclean USB unmount
  - All queries use parameterised statements (no string interpolation)
  - schema_version table drives forward-only migrations
  - Connection is opened once at init and closed explicitly on shutdown
"""

import sqlite3
from typing import Optional

from app.database.models import AuditEntry, InventoryItem
from app.services.logger import get_logger

log = get_logger(__name__)

# Schema version this code expects. Bump when adding migrations.
_CURRENT_VERSION = 1

# ---------------------------------------------------------------------------
# SQL statements
# ---------------------------------------------------------------------------

_SQL_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
);
"""

_SQL_CREATE_INVENTORY = """
CREATE TABLE IF NOT EXISTS inventory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name   TEXT    NOT NULL,
    quantity    TEXT    NOT NULL,
    location    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now', 'utc'))
);
"""

_SQL_CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT    NOT NULL,
    item_name   TEXT    NOT NULL,
    quantity    TEXT,
    location    TEXT,
    timestamp   TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
    transcript  TEXT
);
"""

_SQL_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_inventory_location  ON inventory(location);",
    "CREATE INDEX IF NOT EXISTS idx_inventory_item_name ON inventory(item_name);",
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp     ON audit_log(timestamp);",
]

# Ordered list of migration SQL blocks indexed by the version they create.
# Index 0 is unused (version numbers start at 1).
# Add new entries here as the schema evolves; never modify existing ones.
_MIGRATIONS: list[Optional[str]] = [
    None,   # placeholder for index 0
    None,   # version 1 is the initial schema — handled by _create_schema()
]


class DatabaseManager:
    def __init__(self, db_path: str):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection guard
    # ------------------------------------------------------------------

    @property
    def _connection(self) -> sqlite3.Connection:
        """Return the active connection, or raise a clear error if not yet opened."""
        if self._conn is None:
            raise RuntimeError(
                "DatabaseManager: no active connection — call open() before using the database."
            )
        return self._conn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the database and ensure schema is up to date."""
        import os
        os.makedirs(os.path.dirname(self._path), exist_ok=True)

        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # WAL mode — crash-safe for USB sticks
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA synchronous = NORMAL;")

        self._create_schema()
        self._run_migrations()
        log.info("Database opened: %s (schema v%d)", self._path, _CURRENT_VERSION)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            log.debug("Database closed.")

    # ------------------------------------------------------------------
    # CRUD — inventory
    # ------------------------------------------------------------------

    def add_item(
        self,
        item_name: str,
        quantity: str,
        location: str,
    ) -> InventoryItem:
        """Insert a new inventory row. Returns the created item."""
        item_name = item_name.strip().lower()
        quantity  = quantity.strip()
        location  = location.strip()

        cur = self._connection.execute(
            """
            INSERT INTO inventory (item_name, quantity, location)
            VALUES (?, ?, ?)
            """,
            (item_name, quantity, location),
        )
        self._connection.commit()
        row_id = cur.lastrowid
        log.info("ADD: id=%d  item='%s'  qty='%s'  loc='%s'",
                 row_id, item_name, quantity, location)
        return self._fetch_by_id(row_id)

    def remove_item(self, item_id: int) -> bool:
        """Delete an inventory row by primary key. Returns True if a row was deleted."""
        cur = self._connection.execute(
            "DELETE FROM inventory WHERE id = ?", (item_id,)
        )
        self._connection.commit()
        deleted = cur.rowcount > 0
        if deleted:
            log.info("REMOVE: id=%d", item_id)
        else:
            log.warning("REMOVE: id=%d not found.", item_id)
        return deleted

    def get_all_items(self) -> list[InventoryItem]:
        """Return every inventory row ordered by location then item name."""
        rows = self._connection.execute(
            "SELECT * FROM inventory ORDER BY location, item_name"
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_by_location(self, location_key: str) -> list[InventoryItem]:
        """Return all items in a specific location."""
        rows = self._connection.execute(
            "SELECT * FROM inventory WHERE location = ? ORDER BY item_name",
            (location_key,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_item_names(self, location_key: Optional[str] = None) -> list[str]:
        """Return distinct item names (optionally filtered by location)."""
        if location_key:
            rows = self._connection.execute(
                "SELECT DISTINCT item_name FROM inventory WHERE location = ?",
                (location_key,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT DISTINCT item_name FROM inventory"
            ).fetchall()
        return [r["item_name"] for r in rows]

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def log_action(
        self,
        action: str,
        item_name: str,
        quantity: Optional[str] = None,
        location: Optional[str] = None,
        transcript: Optional[str] = None,
    ) -> None:
        """Write an ADD or REMOVE event to the audit log."""
        self._connection.execute(
            """
            INSERT INTO audit_log (action, item_name, quantity, location, transcript)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action.upper(), item_name, quantity, location, transcript),
        )
        self._connection.commit()

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        rows = self._connection.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_audit(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_by_id(self, item_id: int) -> InventoryItem:
        row = self._connection.execute(
            "SELECT * FROM inventory WHERE id = ?", (item_id,)
        ).fetchone()
        if not row:
            raise RuntimeError(f"Item id={item_id} not found after insert.")
        return self._row_to_item(row)

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> InventoryItem:
        return InventoryItem(
            id=row["id"],
            item_name=row["item_name"],
            quantity=row["quantity"],
            location=row["location"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_audit(row: sqlite3.Row) -> AuditEntry:
        return AuditEntry(
            id=row["id"],
            action=row["action"],
            item_name=row["item_name"],
            quantity=row["quantity"],
            location=row["location"],
            timestamp=row["timestamp"],
            transcript=row["transcript"],
        )

    def _create_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        self._connection.execute(_SQL_CREATE_SCHEMA_VERSION)
        self._connection.execute(_SQL_CREATE_INVENTORY)
        self._connection.execute(_SQL_CREATE_AUDIT_LOG)
        for idx_sql in _SQL_CREATE_INDEXES:
            self._connection.execute(idx_sql)
        self._connection.commit()

        # Seed schema_version on first ever open
        version = self._connection.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()["v"]

        if version is None:
            self._connection.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (_CURRENT_VERSION,),
            )
            self._connection.commit()
            log.debug("Schema version seeded at %d.", _CURRENT_VERSION)

    def _run_migrations(self) -> None:
        """Apply any pending migrations in order."""
        current = self._connection.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()["v"] or 0

        for version in range(current + 1, len(_MIGRATIONS)):
            sql = _MIGRATIONS[version]
            if sql:
                log.info("Applying migration to schema version %d.", version)
                self._connection.executescript(sql)
                self._connection.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version,)
                )
                self._connection.commit()
                log.info("Migration to v%d complete.", version)
