"""
SQLite database connection manager.
Thread-safe with WAL mode for concurrent reads.
"""

import sqlite3
import threading
import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe SQLite database manager with WAL mode."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._local = threading.local()

        # Ensure parent directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize with WAL mode
        conn = self._get_connection()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local connection."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self.db_path, check_same_thread=False
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query with thread safety."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(query, params)
                conn.commit()
                return cursor
            except Exception as e:
                conn.rollback()
                logger.error(f"DB execute error: {e}\nQuery: {query[:200]}")
                raise

    def executemany(self, query: str, params_list: list) -> sqlite3.Cursor:
        """Execute a query with multiple parameter sets."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.executemany(query, params_list)
                conn.commit()
                return cursor
            except Exception as e:
                conn.rollback()
                logger.error(f"DB executemany error: {e}")
                raise

    def fetchone(self, query: str, params: tuple = ()) -> sqlite3.Row | None:
        """Fetch a single row."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, params)
            return cursor.fetchone()

    def fetchall(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Fetch all rows."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(query, params)
            return cursor.fetchall()

    @contextmanager
    def transaction(self):
        """Context manager for explicit transactions."""
        with self._lock:
            conn = self._get_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def reserve_cash(self, order_id: str, amount: float):
        """Reserve cash for a pending BUY order."""
        self.execute(
            "INSERT INTO paper_reserved_cash (order_id, amount) VALUES (?, ?)",
            (order_id, amount),
        )

    def release_cash_reservation(self, order_id: str):
        """Release reserved cash when order is filled/cancelled/rejected."""
        self.execute(
            "DELETE FROM paper_reserved_cash WHERE order_id = ?",
            (order_id,),
        )

    def get_total_reserved_cash(self) -> float:
        """Get total cash reserved for pending orders."""
        row = self.fetchone(
            "SELECT COALESCE(SUM(amount), 0) as total FROM paper_reserved_cash"
        )
        return row["total"] if row else 0.0

    def count_trades_today(self, mode: str = None) -> int:
        """Count trades placed today, optionally filtered by mode."""
        if mode:
            row = self.fetchone(
                "SELECT COUNT(*) as cnt FROM trades "
                "WHERE DATE(timestamp) = DATE('now') AND mode = ?",
                (mode,),
            )
        else:
            row = self.fetchone(
                "SELECT COUNT(*) as cnt FROM trades WHERE DATE(timestamp) = DATE('now')"
            )
        return row["cnt"] if row else 0

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
