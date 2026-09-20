"""Tests for PaperBroker."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from unittest.mock import MagicMock, patch
from src.database.db import Database
from src.database.migrations import run_migrations, initialize_paper_cash
from src.trading.paper_broker import PaperBroker, generate_paper_order_id


@pytest.fixture
def db():
    """Create a temporary database with migrations."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = Database(tmp.name)
    run_migrations(database)
    initialize_paper_cash(database, 100000)
    yield database
    database.close()
    os.unlink(tmp.name)


@pytest.fixture
def mock_data_client():
    """Create a mock data client."""
    client = MagicMock()
    client.get_ltp.return_value = {"NSE:RELIANCE": {"last_price": 2500.0}}
    return client


@pytest.fixture
def broker(db, mock_data_client):
    """Create a PaperBroker instance."""
    return PaperBroker(db=db, data_client=mock_data_client)


class TestGeneratePaperOrderId:
    def test_format(self):
        oid = generate_paper_order_id()
        assert oid.startswith("PAPER_")
        assert len(oid) > 20

    def test_unique(self):
        ids = {generate_paper_order_id() for _ in range(100)}
        assert len(ids) == 100


class TestExecuteOrder:
    def test_market_buy_fills_immediately(self, broker):
        result = broker.execute_order({
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "order_type": "MARKET",
            "quantity": 5,
            "price": 0,
            "product": "CNC",
        })
        assert result["status"] == "COMPLETE"
        assert result["fill_price"] is not None
        assert result["order_id"].startswith("PAPER_")

    def test_limit_buy_pending(self, broker):
        # LTP is 2500, limit at 2400 should not fill
        result = broker.execute_order({
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "quantity": 5,
            "price": 2400,
            "product": "CNC",
        })
        assert result["status"] == "OPEN"

    def test_limit_buy_fills_at_ltp(self, broker):
        # LTP is 2500, limit at 2600 should fill
        result = broker.execute_order({
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "quantity": 5,
            "price": 2600,
            "product": "CNC",
        })
        assert result["status"] == "COMPLETE"
        assert result["fill_price"] == 2600

    def test_sl_order_registered(self, broker):
        result = broker.execute_order({
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "transaction_type": "SELL",
            "order_type": "SL",
            "quantity": 5,
            "price": 2400,
            "product": "CNC",
            "stop_loss": 2400,
        })
        assert result["status"] == "TRIGGER PENDING"

    def test_rejected_when_no_ltp(self, broker):
        broker.data_client.get_ltp.return_value = {"NSE:TCS": {"last_price": 0}}
        result = broker.execute_order({
            "symbol": "TCS",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "order_type": "MARKET",
            "quantity": 5,
            "product": "CNC",
        })
        assert result["status"] == "REJECTED"


class TestUpdateHoldings:
    def test_buy_new_holding(self, broker, db):
        broker.update_holdings("RELIANCE", "NSE", "BUY", 10, 2500.0)
        row = db.fetchone("SELECT * FROM paper_holdings WHERE symbol = 'RELIANCE'")
        assert row["quantity"] == 10
        assert row["avg_price"] == 2500.0

    def test_buy_average_up(self, broker, db):
        broker.update_holdings("RELIANCE", "NSE", "BUY", 10, 2500.0)
        broker.update_holdings("RELIANCE", "NSE", "BUY", 10, 2600.0)
        row = db.fetchone("SELECT * FROM paper_holdings WHERE symbol = 'RELIANCE'")
        assert row["quantity"] == 20
        assert row["avg_price"] == 2550.0

    def test_sell_partial(self, broker, db):
        broker.update_holdings("RELIANCE", "NSE", "BUY", 10, 2500.0)
        broker.update_holdings("RELIANCE", "NSE", "SELL", 5, 2600.0)
        row = db.fetchone("SELECT * FROM paper_holdings WHERE symbol = 'RELIANCE'")
        assert row["quantity"] == 5

    def test_sell_full_deletes(self, broker, db):
        broker.update_holdings("RELIANCE", "NSE", "BUY", 10, 2500.0)
        broker.update_holdings("RELIANCE", "NSE", "SELL", 10, 2600.0)
        row = db.fetchone("SELECT * FROM paper_holdings WHERE symbol = 'RELIANCE'")
        assert row is None


class TestUpdatePositions:
    def test_open_long_position(self, broker, db):
        broker.update_positions("RELIANCE", "NSE", "BUY", 5, 2500.0, 2450.0, 2575.0)
        row = db.fetchone(
            "SELECT * FROM paper_positions WHERE symbol = 'RELIANCE'"
        )
        assert row["quantity"] == 5
        assert row["side"] == "BUY"
        assert row["stop_loss"] == 2450.0
        assert row["target"] == 2575.0

    def test_close_position_returns_pnl(self, broker, db):
        broker.update_positions("RELIANCE", "NSE", "BUY", 5, 2500.0)
        pnl = broker.update_positions("RELIANCE", "NSE", "SELL", 5, 2600.0)
        assert pnl == 500.0  # (2600 - 2500) * 5

        # Position should be deleted
        row = db.fetchone(
            "SELECT * FROM paper_positions WHERE symbol = 'RELIANCE'"
        )
        assert row is None

    def test_open_short_position(self, broker, db):
        broker.update_positions("RELIANCE", "NSE", "SELL", 5, 2500.0)
        row = db.fetchone(
            "SELECT * FROM paper_positions WHERE symbol = 'RELIANCE'"
        )
        assert row["quantity"] == -5
        assert row["side"] == "SELL"


class TestClosePosition:
    def test_close_long_position(self, broker, db):
        db.execute(
            "INSERT INTO paper_positions "
            "(symbol, exchange, product, quantity, entry_price, side, entry_timestamp) "
            "VALUES (?, ?, 'MIS', ?, ?, ?, ?)",
            ("RELIANCE", "NSE", 5, 2500.0, "BUY", "2026-03-01 10:00:00"),
        )
        initial_cash = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")["balance"]

        broker.close_position("RELIANCE", 2600.0, "Target hit")

        # Position should be deleted
        row = db.fetchone(
            "SELECT * FROM paper_positions WHERE symbol = 'RELIANCE'"
        )
        assert row is None

        # Cash should increase by exit proceeds minus brokerage
        final_cash = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")["balance"]
        expected = initial_cash + (2600.0 * 5 - 20)
        assert final_cash == expected

    def test_close_short_position(self, broker, db):
        db.execute(
            "INSERT INTO paper_positions "
            "(symbol, exchange, product, quantity, entry_price, side, entry_timestamp) "
            "VALUES (?, ?, 'MIS', ?, ?, ?, ?)",
            ("RELIANCE", "NSE", -5, 2500.0, "SELL", "2026-03-01 10:00:00"),
        )

        broker.close_position("RELIANCE", 2400.0, "Target hit (short)")

        row = db.fetchone(
            "SELECT * FROM paper_positions WHERE symbol = 'RELIANCE'"
        )
        assert row is None


class TestUpdateCash:
    def test_buy_debits(self, broker, db):
        initial = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")["balance"]
        broker.update_cash("BUY", 10000, 20)
        final = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")["balance"]
        assert final == initial - 10020

    def test_sell_credits(self, broker, db):
        initial = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")["balance"]
        broker.update_cash("SELL", 10000, 20)
        final = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")["balance"]
        assert final == initial + 9980


class TestCancelPendingMISOrders:
    def test_cancels_open_mis_orders(self, broker, db):
        db.execute(
            "INSERT INTO paper_orders "
            "(order_id, symbol, exchange, transaction_type, quantity, product, "
            "order_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ORD1", "RELIANCE", "NSE", "BUY", 5, "MIS", "LIMIT", "OPEN"),
        )
        db.execute(
            "INSERT INTO paper_orders "
            "(order_id, symbol, exchange, transaction_type, quantity, product, "
            "order_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ORD2", "TCS", "NSE", "BUY", 3, "CNC", "LIMIT", "OPEN"),
        )

        broker.cancel_pending_mis_orders()

        mis_order = db.fetchone("SELECT status FROM paper_orders WHERE order_id = 'ORD1'")
        cnc_order = db.fetchone("SELECT status FROM paper_orders WHERE order_id = 'ORD2'")
        assert mis_order["status"] == "CANCELLED"
        assert cnc_order["status"] == "OPEN"  # CNC not cancelled


class TestGetCandleOrLtp:
    def test_returns_synthetic_candle_from_ltp(self, broker):
        candle = broker.get_candle_or_ltp("RELIANCE", "NSE")
        assert candle is not None
        assert candle["high"] == 2500.0
        assert candle["low"] == 2500.0

    def test_returns_none_when_no_ltp(self, broker):
        broker.data_client.get_ltp.return_value = {}
        candle = broker.get_candle_or_ltp("UNKNOWN", "NSE")
        assert candle is None

    def test_prefers_candle_over_ltp(self, broker):
        mock_md = MagicMock()
        mock_md.fetch_recent_candle.return_value = {
            "open": 2490, "high": 2520, "low": 2480, "close": 2510, "volume": 1000
        }
        broker.market_data = mock_md

        candle = broker.get_candle_or_ltp("RELIANCE", "NSE")
        assert candle["high"] == 2520
        assert candle["low"] == 2480


class TestRecordTradePnl:
    def test_records_to_trades_table(self, broker, db):
        broker.record_trade_pnl("RELIANCE", 500.0)
        row = db.fetchone(
            "SELECT * FROM trades WHERE symbol = 'RELIANCE' AND transaction_type = 'CLOSE'"
        )
        assert row is not None
        assert row["pnl"] == 500.0
        assert row["mode"] == "PAPER"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
