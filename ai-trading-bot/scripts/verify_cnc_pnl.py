"""
Verify the CNC-sell realized-P&L fix end-to-end.

Scenarios:
  1. Full round-trip at a LOSS     — pnl must be negative and match
  2. Full round-trip at a GAIN     — pnl must be positive and match
  3. Partial sell then full close  — two CLOSE rows, both with correct pnl
  4. MIS round-trip regression     — existing MIS path still records pnl

Run:  conda run -n trading-bot python scripts/verify_cnc_pnl.py
Exits 0 on all-pass, 1 otherwise.
"""
import os
import sys
import tempfile
from unittest.mock import MagicMock

# scripts/ sits one level below repo root; add the root so `from src...` works.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from src.database.db import Database
from src.database.migrations import run_migrations, initialize_paper_cash
from src.trading.paper_broker import PaperBroker, SLIPPAGE_PCT

PASS, FAIL = "PASS", "FAIL"
failures = []


def log(name: str, ok: bool, detail: str = ""):
    status = PASS if ok else FAIL
    print(f"  [{status}] {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def fresh_broker(starting_cash: float = 1_000_000) -> tuple[PaperBroker, Database, MagicMock]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = Database(tmp.name)
    run_migrations(db)
    initialize_paper_cash(db, starting_cash)
    data_client = MagicMock()
    broker = PaperBroker(db=db, data_client=data_client)
    return broker, db, data_client


def set_ltp(data_client: MagicMock, symbol: str, ltp: float, exchange: str = "NSE"):
    data_client.get_ltp.return_value = {f"{exchange}:{symbol}": {"last_price": ltp}}


def market_buy_fill_price(ltp: float) -> float:
    return round(ltp * (1 + SLIPPAGE_PCT), 2)


def market_sell_fill_price(ltp: float) -> float:
    return round(ltp * (1 - SLIPPAGE_PCT), 2)


def sum_pnl(db: Database, symbol: str) -> float:
    row = db.fetchone(
        "SELECT COALESCE(SUM(pnl), 0) as p FROM trades "
        "WHERE symbol = ? AND pnl IS NOT NULL",
        (symbol,),
    )
    return row["p"] if row else 0


def get_close_rows(db: Database, symbol: str) -> list:
    rows = db.fetchall(
        "SELECT product, pnl, transaction_type FROM trades "
        "WHERE symbol = ? AND transaction_type = 'CLOSE' ORDER BY id",
        (symbol,),
    )
    return [dict(r) for r in rows]


def holdings_qty(db: Database, symbol: str) -> int:
    row = db.fetchone(
        "SELECT quantity FROM paper_holdings WHERE symbol = ?", (symbol,)
    )
    return row["quantity"] if row else 0


# ──────────────────────────────────────────────────────────────────────
# Scenario 1: CNC round-trip at a LOSS
# ──────────────────────────────────────────────────────────────────────
def test_cnc_loss():
    print("\nScenario 1: CNC round-trip at a loss")
    broker, db, dc = fresh_broker()
    sym = "AUBANK"

    set_ltp(dc, sym, 700.0)
    buy = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "BUY", "order_type": "MARKET",
        "quantity": 10, "price": 0, "product": "CNC",
    })
    log("buy fills", buy["status"] == "COMPLETE", f"fill={buy['fill_price']}")
    buy_fp = buy["fill_price"]

    set_ltp(dc, sym, 650.0)
    sell = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "SELL", "order_type": "MARKET",
        "quantity": 10, "price": 0, "product": "CNC",
    })
    log("sell fills", sell["status"] == "COMPLETE", f"fill={sell['fill_price']}")
    sell_fp = sell["fill_price"]

    log("holdings cleared", holdings_qty(db, sym) == 0)

    expected_pnl = round((sell_fp - buy_fp) * 10, 2)
    actual_pnl = sum_pnl(db, sym)
    log(
        "realized pnl recorded",
        abs(actual_pnl - expected_pnl) < 0.01,
        f"expected={expected_pnl}, actual={actual_pnl}",
    )
    log("pnl is negative (loss)", actual_pnl < 0)

    closes = get_close_rows(db, sym)
    log("exactly one CLOSE row", len(closes) == 1)
    if closes:
        log("CLOSE row is product=CNC", closes[0]["product"] == "CNC",
            f"got product={closes[0]['product']}")


# ──────────────────────────────────────────────────────────────────────
# Scenario 2: CNC round-trip at a GAIN
# ──────────────────────────────────────────────────────────────────────
def test_cnc_gain():
    print("\nScenario 2: CNC round-trip at a gain")
    broker, db, dc = fresh_broker()
    sym = "HDFC"

    set_ltp(dc, sym, 1500.0)
    buy = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "BUY", "order_type": "MARKET",
        "quantity": 20, "price": 0, "product": "CNC",
    })
    buy_fp = buy["fill_price"]

    set_ltp(dc, sym, 1600.0)
    sell = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "SELL", "order_type": "MARKET",
        "quantity": 20, "price": 0, "product": "CNC",
    })
    sell_fp = sell["fill_price"]

    expected_pnl = round((sell_fp - buy_fp) * 20, 2)
    actual_pnl = sum_pnl(db, sym)
    log("realized pnl recorded",
        abs(actual_pnl - expected_pnl) < 0.01,
        f"expected={expected_pnl}, actual={actual_pnl}")
    log("pnl is positive (gain)", actual_pnl > 0)


# ──────────────────────────────────────────────────────────────────────
# Scenario 3: Partial sell then full close — two CLOSE rows
# ──────────────────────────────────────────────────────────────────────
def test_cnc_partial_then_close():
    print("\nScenario 3: partial sell then full close")
    broker, db, dc = fresh_broker()
    sym = "INFY"

    set_ltp(dc, sym, 1500.0)
    buy = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "BUY", "order_type": "MARKET",
        "quantity": 30, "price": 0, "product": "CNC",
    })
    avg = buy["fill_price"]  # Broker stores this as avg_price

    # Partial sell 10 @ 1480
    set_ltp(dc, sym, 1480.0)
    s1 = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "SELL", "order_type": "MARKET",
        "quantity": 10, "price": 0, "product": "CNC",
    })
    s1_fp = s1["fill_price"]
    log("10 shares remain after partial", holdings_qty(db, sym) == 20,
        f"qty={holdings_qty(db, sym)}")

    # Close remaining 20 @ 1520
    set_ltp(dc, sym, 1520.0)
    s2 = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "SELL", "order_type": "MARKET",
        "quantity": 20, "price": 0, "product": "CNC",
    })
    s2_fp = s2["fill_price"]
    log("holdings cleared", holdings_qty(db, sym) == 0)

    expected_total = round((s1_fp - avg) * 10 + (s2_fp - avg) * 20, 2)
    actual_total = sum_pnl(db, sym)
    log("summed pnl across two closes",
        abs(actual_total - expected_total) < 0.01,
        f"expected={expected_total}, actual={actual_total}")

    closes = get_close_rows(db, sym)
    log("two CLOSE rows exist", len(closes) == 2, f"got {len(closes)}")
    log("both are product=CNC",
        all(c["product"] == "CNC" for c in closes),
        f"products={[c['product'] for c in closes]}")


# ──────────────────────────────────────────────────────────────────────
# Scenario 4: MIS regression — existing MIS path still records pnl
# ──────────────────────────────────────────────────────────────────────
def test_mis_regression():
    print("\nScenario 4: MIS round-trip (regression)")
    broker, db, dc = fresh_broker()
    sym = "TCS"

    set_ltp(dc, sym, 3500.0)
    buy = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "BUY", "order_type": "MARKET",
        "quantity": 5, "price": 0, "product": "MIS",
    })
    log("MIS buy fills", buy["status"] == "COMPLETE")

    set_ltp(dc, sym, 3600.0)
    sell = broker.execute_order({
        "symbol": sym, "exchange": "NSE",
        "transaction_type": "SELL", "order_type": "MARKET",
        "quantity": 5, "price": 0, "product": "MIS",
    })
    log("MIS sell fills", sell["status"] == "COMPLETE")

    actual_pnl = sum_pnl(db, sym)
    log("MIS pnl still recorded (gain)", actual_pnl > 0, f"pnl={actual_pnl}")

    closes = get_close_rows(db, sym)
    log("MIS CLOSE row has product=MIS",
        len(closes) == 1 and closes[0]["product"] == "MIS",
        f"got {closes}")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing CNC realized-P&L fix")
    print("=" * 60)

    test_cnc_loss()
    test_cnc_gain()
    test_cnc_partial_then_close()
    test_mis_regression()

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
        sys.exit(0)
