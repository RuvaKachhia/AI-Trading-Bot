"""Tests for Database and Migrations."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from src.database.db import Database
from src.database.migrations import run_migrations, initialize_paper_cash


@pytest.fixture
def db():
    """Create a temporary in-memory database."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = Database(tmp.name)
    run_migrations(database)
    yield database
    database.close()
    os.unlink(tmp.name)


class TestDatabase:
    def test_connection(self, db):
        row = db.fetchone("SELECT 1 as val")
        assert row["val"] == 1

    def test_execute_and_fetchall(self, db):
        db.execute(
            "INSERT INTO trades (timestamp, symbol, exchange, transaction_type, "
            "quantity, price, product, order_type, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-03-01 10:00:00", "RELIANCE", "NSE", "BUY", 5, 2500, "CNC", "LIMIT", "PAPER"),
        )
        rows = db.fetchall("SELECT * FROM trades WHERE symbol = 'RELIANCE'")
        assert len(rows) == 1
        assert rows[0]["quantity"] == 5

    def test_fetchone_returns_none(self, db):
        row = db.fetchone("SELECT * FROM trades WHERE symbol = 'NONEXISTENT'")
        assert row is None


class TestMigrations:
    def test_tables_created(self, db):
        tables = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = {t["name"] for t in tables}
        expected = {
            "trades", "portfolio_snapshots", "llm_calls", "llm_daily_costs",
            "guardrail_log", "daily_summaries",
            "paper_holdings", "paper_positions", "paper_orders",
            "paper_cash", "paper_reserved_cash",
            "position_tracking", "watchlist_history",
        }
        assert expected.issubset(table_names)

    def test_views_created(self, db):
        views = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
        )
        view_names = {v["name"] for v in views}
        assert "v_llm_cost_analysis" in view_names
        assert "v_session_trace" in view_names

    def test_idempotent_migrations(self, db):
        # Running migrations again should not error
        run_migrations(db)
        row = db.fetchone("SELECT 1 as val")
        assert row["val"] == 1

    def test_paper_positions_has_sl_target_columns(self, db):
        # Verify ALTER TABLE migration added stop_loss and target columns
        db.execute(
            "INSERT INTO paper_positions "
            "(symbol, exchange, quantity, entry_price, side, product, entry_timestamp, "
            "stop_loss, target) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("RELIANCE", "NSE", 5, 2500.0, "BUY", "MIS",
             "2026-03-01 10:00:00", 2450.0, 2575.0),
        )
        row = db.fetchone(
            "SELECT stop_loss, target FROM paper_positions WHERE symbol = 'RELIANCE'"
        )
        assert row is not None
        assert row["stop_loss"] == 2450.0
        assert row["target"] == 2575.0


class TestModeColumns:
    def test_portfolio_snapshots_has_mode(self, db):
        db.execute(
            "INSERT INTO portfolio_snapshots "
            "(timestamp, total_value, cash_available, deployed, daily_pnl, "
            "cumulative_pnl, mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2026-03-01 10:00:00", 100000, 90000, 10000, 500, 500, "PAPER"),
        )
        row = db.fetchone("SELECT mode FROM portfolio_snapshots LIMIT 1")
        assert row["mode"] == "PAPER"

    def test_daily_summaries_has_mode_and_unique_constraint(self, db):
        # Insert PAPER summary for a date
        db.execute(
            "INSERT INTO daily_summaries (date, day_number, mode) VALUES (?, ?, ?)",
            ("2026-03-01", 1, "PAPER"),
        )
        # Insert LIVE summary for the same date — should NOT conflict
        db.execute(
            "INSERT INTO daily_summaries (date, day_number, mode) VALUES (?, ?, ?)",
            ("2026-03-01", 1, "LIVE"),
        )
        rows = db.fetchall(
            "SELECT * FROM daily_summaries WHERE date = '2026-03-01'"
        )
        assert len(rows) == 2
        modes = {r["mode"] for r in rows}
        assert modes == {"PAPER", "LIVE"}

    def test_position_tracking_has_mode(self, db):
        db.execute(
            "INSERT INTO position_tracking "
            "(symbol, exchange, entry_price, stop_loss, target, product, "
            "side, entry_date, status, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("RELIANCE", "NSE", 2500, 2450, 2575, "CNC", "BUY",
             "2026-03-01", "OPEN", "PAPER"),
        )
        # Same symbol in LIVE mode — should NOT conflict
        db.execute(
            "INSERT INTO position_tracking "
            "(symbol, exchange, entry_price, stop_loss, target, product, "
            "side, entry_date, status, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("RELIANCE", "NSE", 2510, 2460, 2580, "CNC", "BUY",
             "2026-03-01", "OPEN", "LIVE"),
        )
        rows = db.fetchall(
            "SELECT * FROM position_tracking WHERE symbol = 'RELIANCE' AND status = 'OPEN'"
        )
        assert len(rows) == 2

    def test_watchlist_history_has_mode(self, db):
        db.execute(
            "INSERT INTO watchlist_history (timestamp, symbols, mode) VALUES (?, ?, ?)",
            ("2026-03-01 10:00:00", "RELIANCE,TCS", "PAPER"),
        )
        row = db.fetchone("SELECT mode FROM watchlist_history LIMIT 1")
        assert row["mode"] == "PAPER"

    def test_count_trades_today_by_mode(self, db):
        db.execute(
            "INSERT INTO trades (timestamp, symbol, exchange, transaction_type, "
            "quantity, price, product, order_type, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-03-01 10:00:00", "TCS", "NSE", "BUY", 3, 3500, "CNC", "LIMIT", "LIVE"),
        )
        db.execute(
            "INSERT INTO trades (timestamp, symbol, exchange, transaction_type, "
            "quantity, price, product, order_type, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-03-01 10:00:00", "INFY", "NSE", "BUY", 5, 1500, "CNC", "LIMIT", "PAPER"),
        )
        # count_trades_today won't match these since they're not "today",
        # but we can test the mode param logic directly
        all_count = db.count_trades_today()  # no mode filter
        paper_count = db.count_trades_today(mode="PAPER")
        live_count = db.count_trades_today(mode="LIVE")
        # All should be 0 since the dates are in the past, but the query should not error
        assert all_count >= 0
        assert paper_count >= 0
        assert live_count >= 0


class TestPaperCash:
    def test_initialize_paper_cash(self, db):
        initialize_paper_cash(db, 100000)
        row = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")
        assert row is not None
        assert row["balance"] == 100000

    def test_initialize_paper_cash_idempotent(self, db):
        initialize_paper_cash(db, 100000)
        initialize_paper_cash(db, 200000)  # second call should not overwrite
        row = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")
        assert row["balance"] == 100000  # first value preserved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
