"""
Portfolio State Manager.
Provides portfolio data from paper trading tables.
Claude NEVER knows this is paper trading.
"""

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


class PortfolioStateManager:
    """
    Unified interface to portfolio data for paper trading.
    The prompt builder ONLY interacts with this class.
    """

    def __init__(self, data_client, db, config: dict):
        self.data_client = data_client
        self.db = db
        self._starting_capital = config.get("experiment", {}).get("starting_capital", 100000)

    # ─── CORE ACCESSORS ───

    def get_holdings(self) -> list[dict]:
        """
        Returns CNC holdings.
        Format: [{symbol, quantity, avg_price, last_price, pnl, pnl_pct, days_held, ...}]
        """
        try:
            rows = self.db.fetchall(
                "SELECT * FROM paper_holdings WHERE quantity > 0"
            )
            exchanges = [
                (row["exchange"] if "exchange" in row.keys() else "NSE")
                for row in rows
            ]
            ltps = self._get_ltps_bulk(
                [f"{ex}:{row['symbol']}" for row, ex in zip(rows, exchanges)]
            )
            # CNC holdings store SL/target on the latest COMPLETE BUY trade row
            # in the trades table (see paper_broker.modify_sl_target's CNC
            # fallback). Without this lookup the prompt formatter shows
            # SL=0 / target=0 to Opus and he re-modifies every cycle from
            # scratch, unaware of the state he already set.
            sl_target_by_symbol = self._latest_cnc_sl_targets(
                [(row["symbol"], ex) for row, ex in zip(rows, exchanges)]
            )
            holdings = []
            for row, exchange in zip(rows, exchanges):
                symbol = row["symbol"]
                qty = row["quantity"]
                avg = row["avg_price"]
                ltp = ltps.get(f"{exchange}:{symbol}", 0)
                pnl = (ltp - avg) * qty if ltp else 0
                pnl_pct = ((ltp - avg) / avg * 100) if avg > 0 and ltp else 0
                sl, tgt = sl_target_by_symbol.get((symbol, exchange), (0, 0))
                holdings.append({
                    "symbol": symbol,
                    "exchange": exchange,
                    "quantity": qty,
                    "avg_price": avg,
                    "last_price": ltp,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "days_held": 0,
                    "stop_loss": sl or 0,
                    "target": tgt or 0,
                })
            return holdings
        except Exception as e:
            logger.error(f"Failed to get paper holdings: {e}")
            return []

    def get_positions(self) -> list[dict]:
        """
        Returns open MIS positions.
        Format: [{symbol, side, quantity, entry, ltp, pnl, pnl_pct, stop_loss, target, ...}]
        """
        try:
            rows = self.db.fetchall(
                "SELECT * FROM paper_positions WHERE quantity != 0 AND product = 'MIS'"
            )
            ltps = self._get_ltps_bulk([f"NSE:{row['symbol']}" for row in rows])
            positions = []
            for row in rows:
                symbol = row["symbol"]
                qty = row["quantity"]
                entry = row["entry_price"]
                ltp = ltps.get(f"NSE:{symbol}", 0)
                side = "BUY" if qty > 0 else "SELL"
                pnl = (ltp - entry) * abs(qty) if ltp else 0
                if side == "SELL":
                    pnl = -pnl
                pnl_pct = (pnl / (entry * abs(qty)) * 100) if entry > 0 else 0
                positions.append({
                    "symbol": symbol,
                    "exchange": "NSE",
                    "side": side,
                    "quantity": abs(qty),
                    "entry": entry,
                    "ltp": ltp,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "stop_loss": (row["stop_loss"] if "stop_loss" in row.keys() else 0) or 0,
                    "target": (row["target"] if "target" in row.keys() else 0) or 0,
                })
            return positions
        except Exception as e:
            logger.error(f"Failed to get paper positions: {e}")
            return []

    def get_available_cash(self) -> float:
        """Returns available cash for trading."""
        try:
            row = self.db.fetchone(
                "SELECT balance FROM paper_cash WHERE id = 1"
            )
            cash = row["balance"] if row else self._starting_capital
            reserved = self.db.get_total_reserved_cash()
            return max(0, cash - reserved)
        except Exception as e:
            logger.error(f"Failed to get paper cash: {e}")
            return self._starting_capital

    def get_daily_pnl(self) -> dict:
        """Returns today's P&L breakdown: {realized, unrealized}."""
        try:
            today = date.today().isoformat()
            row = self.db.fetchone(
                """SELECT COALESCE(SUM(pnl), 0) as realized
                   FROM trades WHERE DATE(timestamp) = ? AND status = 'COMPLETE'
                   AND mode = 'PAPER'""",
                (today,),
            )
            realized = row["realized"] if row else 0

            unrealized = 0
            for h in self.get_holdings():
                unrealized += h.get("pnl", 0)
            for p in self.get_positions():
                unrealized += p.get("pnl", 0)

            return {"realized": round(realized, 2), "unrealized": round(unrealized, 2)}
        except Exception as e:
            logger.error(f"Failed to get paper P&L: {e}")
            return {"realized": 0, "unrealized": 0}

    def total_value(self) -> float:
        """Returns total portfolio value (cash + holdings value)."""
        cash = self.get_available_cash()
        holdings_value = sum(
            h.get("last_price", 0) * h.get("quantity", 0)
            for h in self.get_holdings()
        )
        return cash + holdings_value

    def trades_today_count(self) -> int:
        """Returns number of trades placed today."""
        return self.db.count_trades_today(mode="PAPER")

    def get_holdings_qty(self, symbol: str) -> int:
        """Get holdings quantity for a specific symbol. Direct DB lookup; does
        not fetch LTPs. Callers that only need quantity (e.g. guardrails'
        short-sell / MODIFY existence checks) should use this instead of
        get_holdings() to avoid an unnecessary Dhan round-trip."""
        try:
            row = self.db.fetchone(
                "SELECT quantity FROM paper_holdings "
                "WHERE symbol = ? AND quantity > 0 LIMIT 1",
                (symbol,),
            )
            return row["quantity"] if row else 0
        except Exception as e:
            logger.error(f"Failed to get holdings qty for {symbol}: {e}")
            return 0

    # ─── FULL STATE FOR PROMPTS ───

    def get_portfolio_state(self) -> dict:
        """
        Build the complete portfolio state dict for prompt formatting.
        This is the main interface used by PromptFormatter.
        """
        holdings = self.get_holdings()
        positions = self.get_positions()
        cash = self.get_available_cash()
        daily_pnl = self.get_daily_pnl()
        total = self.total_value()

        return {
            "total_value": total,
            "cash": cash,
            "daily_pnl": daily_pnl,
            "holdings": holdings,
            "mis_positions": positions,
            "trades_today": self.trades_today_count(),
            "starting_capital": self._starting_capital,
        }

    def get_existing_positions_for_prompt(self) -> list[dict]:
        """
        Build position details for the EXISTING POSITION UPDATES section.
        Merges holdings + MIS positions into a single list.
        """
        result = []

        for h in self.get_holdings():
            result.append({
                "symbol": h.get("symbol", ""),
                "product": "CNC",
                "side": "BUY",
                "quantity": h.get("quantity", 0),
                "entry": h.get("avg_price", 0),
                "ltp": h.get("last_price", 0),
                "pnl": h.get("pnl", 0),
                "pnl_pct": h.get("pnl_pct", 0),
                "days_held": h.get("days_held", 0),
                "stop_loss": h.get("stop_loss", 0),
                "target": h.get("target", 0),
            })

        for p in self.get_positions():
            result.append({
                "symbol": p.get("symbol", ""),
                "product": "MIS",
                "side": p.get("side", "BUY"),
                "quantity": p.get("quantity", 0),
                "entry": p.get("entry", 0),
                "ltp": p.get("ltp", 0),
                "pnl": p.get("pnl", 0),
                "pnl_pct": p.get("pnl_pct", 0),
                "days_held": 0,
                "stop_loss": p.get("stop_loss", 0),
                "target": p.get("target", 0),
            })

        return result

    def get_working_orders(self) -> list[dict]:
        """
        Return still-active paper orders — LIMITs not yet filled (status='OPEN')
        and SL orders waiting to trigger (status='TRIGGER PENDING'). Used by the
        TRADING_DECISION prompt so Claude doesn't stack duplicate BUYs on a
        symbol that already has a working order.
        """
        try:
            rows = self.db.fetchall(
                "SELECT order_id, symbol, exchange, transaction_type, quantity, "
                "price, trigger_price, product, order_type, status, placed_at "
                "FROM paper_orders WHERE status IN ('OPEN', 'TRIGGER PENDING') "
                "ORDER BY placed_at DESC"
            )
            out = []
            now = datetime.now()
            for row in rows:
                row = dict(row)
                placed_at_str = row.get("placed_at", "")
                age_min = None
                if placed_at_str:
                    try:
                        placed_dt = datetime.strptime(placed_at_str, "%Y-%m-%d %H:%M:%S")
                        age_min = int((now - placed_dt).total_seconds() / 60)
                    except Exception:
                        pass
                out.append({
                    "order_id": row.get("order_id", ""),
                    "symbol": row.get("symbol", ""),
                    "exchange": row.get("exchange", "NSE"),
                    "transaction_type": row.get("transaction_type", ""),
                    "quantity": row.get("quantity", 0),
                    "price": row.get("price", 0) or 0,
                    "trigger_price": row.get("trigger_price", 0) or 0,
                    "product": row.get("product", ""),
                    "order_type": row.get("order_type", ""),
                    "status": row.get("status", ""),
                    "placed_at": placed_at_str,
                    "age_minutes": age_min,
                })
            return out
        except Exception as e:
            logger.error(f"Failed to get working orders: {e}")
            return []

    def get_held_symbols(self) -> list[str]:
        """Get list of symbols currently held (CNC + MIS)."""
        symbols = set()
        for h in self.get_holdings():
            if h.get("quantity", 0) > 0:
                symbols.add(h.get("symbol", ""))
        for p in self.get_positions():
            if p.get("quantity", 0) != 0:
                symbols.add(p.get("symbol", ""))
        return list(symbols)

    def total_return_pct(self) -> float:
        """Compute total return percentage since experiment start."""
        total = self.total_value()
        if self._starting_capital > 0:
            return (total - self._starting_capital) / self._starting_capital
        return 0.0

    # ─── HELPERS ───

    def _latest_cnc_sl_targets(
        self, symbol_exchanges: list[tuple[str, str]]
    ) -> dict[tuple[str, str], tuple[float, float]]:
        """Read each CNC holding's current SL/target from the latest COMPLETE
        BUY trade row (the source of truth — paper_broker.modify_sl_target
        writes the values here on every MODIFY). Returns {(symbol, exchange):
        (stop_loss, target)}."""
        if not symbol_exchanges:
            return {}
        try:
            # One subquery per symbol would be N round-trips; instead select
            # every BUY trade row for the set of symbols and pick the latest
            # per (symbol, exchange) in Python. CNC books are small (10-ish
            # rows), so this stays cheap.
            symbols = sorted({s for s, _ in symbol_exchanges})
            placeholders = ",".join("?" * len(symbols))
            rows = self.db.fetchall(
                f"SELECT symbol, exchange, stop_loss, target, timestamp "
                f"FROM trades "
                f"WHERE transaction_type = 'BUY' AND status = 'COMPLETE' "
                f"  AND mode = 'PAPER' AND symbol IN ({placeholders}) "
                f"ORDER BY timestamp DESC",
                symbols,
            )
            out: dict[tuple[str, str], tuple[float, float]] = {}
            for r in rows:
                key = (r["symbol"], r["exchange"])
                if key in out:
                    continue  # already took the newest (rows are DESC)
                out[key] = (r["stop_loss"] or 0, r["target"] or 0)
            return out
        except Exception as e:
            logger.error(f"Failed to read CNC SL/targets: {e}")
            return {}

    def _get_ltps_bulk(self, keys: list[str]) -> dict[str, float]:
        """Fetch LTPs for many instruments in a single Dhan call.

        keys: list of "EXCHANGE:SYMBOL" strings, e.g. ["NSE:RELIANCE", "BSE:TCS"].
        Returns: {"EXCHANGE:SYMBOL": last_price, ...}, 0 for misses.

        Dhan's market-feed endpoint is one HTTP call per invocation regardless
        of payload size, and our rate limiter charges one slot per call — so
        this replaces N per-symbol calls (N×2s at the 1-req/2s limit) with a
        single ~2s request, which is why MODIFY validation used to take 32s
        with 8 holdings and now takes ~2s.
        """
        if not self.data_client or not keys:
            return {}
        try:
            quote = self.data_client.get_ltp(keys)
        except Exception as e:
            logger.error(f"Bulk LTP fetch failed for {len(keys)} keys: {e}")
            return {}
        return {k: quote.get(k, {}).get("last_price", 0) for k in keys}
