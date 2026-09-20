"""
Paper Broker — Simulated trade execution and portfolio management.

Consolidates ALL paper trading write/mutation logic:
  - Order execution with slippage simulation
  - CNC holding CRUD (buy averaging, sell reducing)
  - MIS position CRUD (open, close with P&L)
  - Paper order persistence
  - Cash balance updates
  - OHLC-based SL/target/LIMIT fill reconciliation
  - Position closure (SL hit, target hit, MIS auto-exit)
  - Pending order cancellation

Used by: ExecutionEngine, OrderReconciler, SLHealthCheck, MISAutoExitEngine.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MIS_BROKERAGE = 20  # Zerodha flat fee per intraday trade
SLIPPAGE_PCT = 0.0005  # 0.05% adverse slippage for MARKET orders


def generate_paper_order_id() -> str:
    """Generate a unique paper order ID."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"PAPER_{ts}_{short_uuid}"


class PaperBroker:
    """
    Simulated broker for paper trading.
    All paper trading DB mutations flow through this class.
    """

    def __init__(self, db, data_client, market_data=None, notifier=None):
        self.db = db
        self.data_client = data_client
        self.market_data = market_data
        self.notifier = notifier

    # ─── ORDER EXECUTION ───

    def execute_order(self, order: dict) -> dict:
        """
        Simulate order execution with realistic conditions.
        Returns {order_id, status, fill_price, message}.
        """
        symbol = order.get("symbol", "")
        exchange = order.get("exchange", "NSE")
        tx_type = order.get("transaction_type", order.get("action", "BUY"))
        order_type = order.get("order_type", "LIMIT")
        limit_price = order.get("price", 0)
        quantity = order.get("quantity", 0)
        product = order.get("product", "CNC")

        ltp = self.get_ltp(symbol, exchange)
        if ltp <= 0:
            return {
                "order_id": generate_paper_order_id(),
                "status": "REJECTED",
                "fill_price": None,
                "message": f"Cannot get LTP for {symbol}",
            }

        fill_price = None

        if order_type == "MARKET":
            if tx_type == "BUY":
                fill_price = round(ltp * (1 + SLIPPAGE_PCT), 2)
            else:
                fill_price = round(ltp * (1 - SLIPPAGE_PCT), 2)

        elif order_type == "LIMIT":
            if tx_type == "BUY" and ltp <= limit_price:
                fill_price = limit_price
            elif tx_type == "SELL" and ltp >= limit_price:
                fill_price = limit_price
            else:
                order_id = generate_paper_order_id()
                self.save_order(order, order_id, "OPEN", None)
                return {
                    "order_id": order_id,
                    "status": "OPEN",
                    "fill_price": None,
                    "message": f"LIMIT order pending. LTP={ltp}, Limit={limit_price}",
                }

        elif order_type == "SL":
            order_id = generate_paper_order_id()
            self.save_order(order, order_id, "TRIGGER PENDING", None)
            return {
                "order_id": order_id,
                "status": "TRIGGER PENDING",
                "fill_price": None,
                "message": "SL order registered for monitoring",
            }

        if fill_price:
            order_id = generate_paper_order_id()
            brokerage = MIS_BROKERAGE if product == "MIS" else 0

            self.apply_fill(
                symbol, exchange, tx_type, quantity, fill_price, product, brokerage,
                stop_loss=order.get("stop_loss", 0),
                target=order.get("target", 0),
            )
            self.save_order(order, order_id, "COMPLETE", fill_price)

            return {
                "order_id": order_id,
                "status": "COMPLETE",
                "fill_price": fill_price,
                "message": f"Paper fill: {tx_type} {quantity}x {symbol} @ {fill_price}",
            }

        return {
            "order_id": generate_paper_order_id(),
            "status": "REJECTED",
            "fill_price": None,
            "message": "Order could not be filled",
        }

    def _sync_trade_fill(self, order_id: str, fill_price: float):
        """Mirror a paper_orders fill onto the trades row with the same order_id.

        Two tables track the same logical event:
          - paper_orders is the broker-side order book; the prompt's
            OPEN/PENDING section reads from here.
          - trades is the user-facing trade journal; the dashboard's
            "Today's Trades" table, the EOD review, and daily summaries
            read from here.
        When OrderReconciler flips a LIMIT/SL row in paper_orders to
        COMPLETE, the matching trades row stays at OPEN unless we mirror
        the change. The dashboard would then show a phantom OPEN row for
        a trade that has actually filled, and EOD aggregation would
        under-count fills. This sync keeps the two tables consistent."""
        if not order_id:
            return
        try:
            self.db.execute(
                "UPDATE trades SET status = 'COMPLETE', fill_price = ?, "
                "fill_timestamp = ? WHERE order_id = ? AND status = 'OPEN'",
                (fill_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_id),
            )
        except Exception as e:
            logger.error(f"Failed to sync trade fill for {order_id}: {e}")

    # ─── PORTFOLIO MUTATIONS ───

    def apply_fill(
        self, symbol: str, exchange: str, tx_type: str,
        quantity: int, fill_price: float, product: str,
        brokerage: float = 0,
        stop_loss: float = 0, target: float = 0,
        order_id: str = "",
    ):
        """
        Apply a fill to the paper portfolio.
        Routes to holdings (CNC) or positions (MIS), updates cash,
        releases any reserved cash.
        """
        if product == "CNC":
            self.update_holdings(symbol, exchange, tx_type, quantity, fill_price)
        else:
            self.update_positions(
                symbol, exchange, tx_type, quantity, fill_price,
                stop_loss=stop_loss, target=target,
            )

        cost = fill_price * quantity
        self.update_cash(tx_type, cost, brokerage)

        if order_id:
            try:
                self.db.execute(
                    "DELETE FROM paper_reserved_cash WHERE order_id = ?",
                    (order_id,),
                )
            except Exception:
                pass

    def update_holdings(
        self, symbol: str, exchange: str, tx_type: str,
        quantity: int, fill_price: float,
    ):
        """CNC holding CRUD. BUY: average-up or insert. SELL: reduce or delete."""
        row = self.db.fetchone(
            "SELECT * FROM paper_holdings WHERE symbol = ?", (symbol,)
        )

        if tx_type == "BUY":
            if row and row["quantity"] > 0:
                old_qty = row["quantity"]
                old_avg = row["avg_price"]
                new_qty = old_qty + quantity
                new_avg = ((old_avg * old_qty) + (fill_price * quantity)) / new_qty
                self.db.execute(
                    "UPDATE paper_holdings SET quantity = ?, avg_price = ? WHERE symbol = ?",
                    (new_qty, round(new_avg, 2), symbol),
                )
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO paper_holdings "
                    "(symbol, exchange, quantity, avg_price) VALUES (?, ?, ?, ?)",
                    (symbol, exchange, quantity, fill_price),
                )
        elif tx_type == "SELL":
            if row:
                old_qty = row["quantity"]
                avg_price = row["avg_price"]
                actual_sold = min(quantity, old_qty)
                new_qty = max(0, old_qty - quantity)
                pnl = round((fill_price - avg_price) * actual_sold, 2)
                if new_qty == 0:
                    self.db.execute(
                        "DELETE FROM paper_holdings WHERE symbol = ?", (symbol,)
                    )
                else:
                    self.db.execute(
                        "UPDATE paper_holdings SET quantity = ? WHERE symbol = ?",
                        (new_qty, symbol),
                    )
                # Record realized P&L so Day/Total P&L on the dashboard sums correctly.
                # Without this, CNC round-trips showed 0 P&L even though cash moved.
                self.record_trade_pnl(symbol, pnl, product="CNC", exchange=exchange)

    def update_positions(
        self, symbol: str, exchange: str, tx_type: str,
        quantity: int, fill_price: float,
        stop_loss: float = 0, target: float = 0,
    ) -> Optional[float]:
        """
        MIS position CRUD. Opens, adjusts, or closes positions.
        Returns realized P&L if position was closed, else None.
        """
        row = self.db.fetchone(
            "SELECT * FROM paper_positions WHERE symbol = ? AND product = 'MIS'",
            (symbol,),
        )

        signed_qty = quantity if tx_type == "BUY" else -quantity

        if row:
            old_qty = row["quantity"]
            new_qty = old_qty + signed_qty
            if new_qty == 0:
                pnl = (fill_price - row["entry_price"]) * old_qty
                self.db.execute(
                    "DELETE FROM paper_positions WHERE symbol = ? AND product = 'MIS'",
                    (symbol,),
                )
                self.record_trade_pnl(symbol, pnl)
                return pnl
            else:
                self.db.execute(
                    "UPDATE paper_positions SET quantity = ? "
                    "WHERE symbol = ? AND product = 'MIS'",
                    (new_qty, symbol),
                )
        else:
            side = "BUY" if tx_type == "BUY" else "SELL"
            self.db.execute(
                "INSERT INTO paper_positions "
                "(symbol, exchange, product, quantity, entry_price, side, "
                "entry_timestamp, stop_loss, target) "
                "VALUES (?, ?, 'MIS', ?, ?, ?, ?, ?, ?)",
                (symbol, exchange, signed_qty, fill_price, side,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 stop_loss or 0, target or 0),
            )
        return None

    def close_position(self, symbol: str, exit_price: float, reason: str = ""):
        """
        Close an MIS position at exit_price. Computes P&L, deletes position,
        updates cash (returns exit proceeds - brokerage).
        """
        try:
            pos = self.db.fetchone(
                "SELECT * FROM paper_positions WHERE symbol = ? AND quantity != 0",
                (symbol,),
            )
            if not pos:
                return

            qty = pos["quantity"]
            entry = pos["entry_price"]

            if qty > 0:  # Long
                pnl = (exit_price - entry) * qty
            else:  # Short
                pnl = (entry - exit_price) * abs(qty)

            self.db.execute(
                "DELETE FROM paper_positions WHERE symbol = ? AND product = 'MIS'",
                (symbol,),
            )

            # Return exit proceeds minus brokerage
            self.db.execute(
                "UPDATE paper_cash SET balance = balance + ? WHERE id = 1",
                (exit_price * abs(qty) - MIS_BROKERAGE,),
            )

            self.record_trade_pnl(symbol, pnl)

            logger.info(
                f"Paper {reason}: {symbol} closed @ INR {exit_price}, "
                f"P&L: INR {pnl:.0f}"
            )

            if self.notifier:
                self.notifier.send_message(
                    f"{reason}: {symbol} @ INR {exit_price:.2f} "
                    f"(P&L: INR {pnl:+,.0f})"
                )

        except Exception as e:
            logger.error(f"Paper close position error for {symbol}: {e}")

    def update_cash(self, tx_type: str, cost: float, brokerage: float = 0):
        """Update paper_cash balance. BUY: debit. SELL: credit."""
        if tx_type == "BUY":
            self.db.execute(
                "UPDATE paper_cash SET balance = balance - ? WHERE id = 1",
                (cost + brokerage,),
            )
        else:
            self.db.execute(
                "UPDATE paper_cash SET balance = balance + ? WHERE id = 1",
                (cost - brokerage,),
            )

    # ─── ORDER PERSISTENCE ───

    def save_order(
        self, order: dict, order_id: str, status: str,
        fill_price: Optional[float] = None,
    ):
        """Save a paper order to the paper_orders table."""
        try:
            self.db.execute(
                """INSERT INTO paper_orders
                   (order_id, symbol, exchange, transaction_type, quantity, price,
                    trigger_price, product, order_type, status, fill_price, tag)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    order.get("symbol", ""),
                    order.get("exchange", "NSE"),
                    order.get("transaction_type", order.get("action", "")),
                    order.get("quantity", 0),
                    order.get("price", 0),
                    order.get("stop_loss") or order.get("trigger_price"),
                    order.get("product", "CNC"),
                    order.get("order_type", "LIMIT"),
                    status,
                    fill_price,
                    order.get("tag", ""),
                ),
            )
        except Exception as e:
            logger.error(f"Failed to save paper order: {e}")

    def cancel_pending_mis_orders(self):
        """Cancel all OPEN MIS paper orders."""
        self.db.execute(
            "UPDATE paper_orders SET status = 'CANCELLED' "
            "WHERE status = 'OPEN' AND product = 'MIS'"
        )

    # ─── OHLC-BASED RECONCILIATION ───

    def reconcile_sl_orders(self):
        """Check TRIGGER PENDING SL orders against OHLC candle range."""
        sl_orders = self.db.fetchall(
            """SELECT * FROM paper_orders
               WHERE status = 'TRIGGER PENDING'
               AND order_type IN ('SL', 'SL-M')"""
        )

        for order in sl_orders:
            order = dict(order)
            symbol = order["symbol"]
            exchange = order.get("exchange", "NSE")
            trigger_price = order.get("trigger_price") or order.get("price", 0)
            if not trigger_price:
                continue

            candle = self.get_candle_or_ltp(symbol, exchange)
            if candle is None:
                continue

            tx_type = order["transaction_type"]
            triggered = False

            if tx_type == "SELL" and candle["low"] <= trigger_price:
                triggered = True
            elif tx_type == "BUY" and candle["high"] >= trigger_price:
                triggered = True

            if triggered:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.db.execute(
                    "UPDATE paper_orders SET status = 'COMPLETE', "
                    "fill_price = ?, fill_timestamp = ? WHERE order_id = ?",
                    (trigger_price, now_str, order["order_id"]),
                )
                self._sync_trade_fill(order["order_id"], trigger_price)

                self.apply_fill(
                    symbol, exchange, tx_type, order["quantity"],
                    trigger_price, order.get("product", "CNC"),
                    brokerage=MIS_BROKERAGE if order.get("product") == "MIS" else 0,
                    order_id=order["order_id"],
                )

                logger.info(
                    f"Paper SL triggered: {tx_type} {symbol} @ INR {trigger_price}"
                )
                if self.notifier:
                    self.notifier.send_message(
                        f"SL triggered: {tx_type} {symbol} @ INR {trigger_price}"
                    )

    def reconcile_limit_orders(self):
        """Check OPEN LIMIT orders against OHLC candle range."""
        limit_orders = self.db.fetchall(
            """SELECT * FROM paper_orders
               WHERE status = 'OPEN'
               AND order_type = 'LIMIT'"""
        )

        for order in limit_orders:
            order = dict(order)
            symbol = order["symbol"]
            exchange = order.get("exchange", "NSE")
            limit_price = order.get("price", 0)
            if not limit_price:
                continue

            candle = self.get_candle_or_ltp(symbol, exchange)
            if candle is None:
                continue

            tx_type = order["transaction_type"]
            filled = False

            if tx_type == "BUY" and candle["low"] <= limit_price:
                filled = True
            elif tx_type == "SELL" and candle["high"] >= limit_price:
                filled = True

            if filled:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.db.execute(
                    "UPDATE paper_orders SET status = 'COMPLETE', "
                    "fill_price = ?, fill_timestamp = ? WHERE order_id = ?",
                    (limit_price, now_str, order["order_id"]),
                )
                self._sync_trade_fill(order["order_id"], limit_price)

                self.apply_fill(
                    symbol, exchange, tx_type, order["quantity"],
                    limit_price, order.get("product", "CNC"),
                    brokerage=MIS_BROKERAGE if order.get("product") == "MIS" else 0,
                    order_id=order["order_id"],
                )

                logger.info(
                    f"Paper LIMIT filled: {tx_type} {symbol} @ INR {limit_price}"
                )
                if self.notifier:
                    self.notifier.send_message(
                        f"LIMIT filled: {tx_type} {symbol} x{order['quantity']} "
                        f"@ INR {limit_price}"
                    )

    def check_holding_sl_orders(self):
        """Check paper_orders SL entries for holdings against OHLC candles."""
        holdings = self.db.fetchall(
            "SELECT * FROM paper_holdings WHERE quantity > 0"
        )
        for h in holdings:
            h = dict(h)
            symbol = h["symbol"]
            exchange = h.get("exchange", "NSE")
            candle = self.get_candle_or_ltp(symbol, exchange)
            if candle is None:
                continue

            sl_orders = self.db.fetchall(
                """SELECT * FROM paper_orders
                   WHERE symbol = ? AND status = 'TRIGGER PENDING'
                   AND order_type IN ('SL', 'SL-M')""",
                (symbol,),
            )

            for sl in sl_orders:
                sl = dict(sl)
                trigger = sl.get("trigger_price") or sl.get("price", 0)
                if not trigger:
                    continue

                tx_type = sl["transaction_type"]
                triggered = False
                if tx_type == "SELL" and candle["low"] <= trigger:
                    triggered = True
                elif tx_type == "BUY" and candle["high"] >= trigger:
                    triggered = True

                if triggered:
                    self.db.execute(
                        "UPDATE paper_orders SET status = 'COMPLETE', "
                        "fill_price = ?, fill_timestamp = ? WHERE order_id = ?",
                        (trigger, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         sl["order_id"]),
                    )
                    self._sync_trade_fill(sl["order_id"], trigger)
                    logger.info(f"Paper SL triggered: {symbol} @ INR {trigger}")
                    if self.notifier:
                        self.notifier.send_message(
                            f"SL triggered for {symbol} @ INR {trigger}"
                        )

    def check_position_sl_targets(self):
        """
        Check MIS positions' SL/target levels against OHLC candles.
        SL has priority over target (conservative).
        """
        positions = self.db.fetchall(
            "SELECT * FROM paper_positions WHERE quantity != 0"
        )
        for p in positions:
            p = dict(p)
            symbol = p["symbol"]
            exchange = p.get("exchange", "NSE")
            candle = self.get_candle_or_ltp(symbol, exchange)
            if candle is None:
                continue

            sl = p.get("stop_loss", 0)
            target = p.get("target", 0)
            qty = p["quantity"]
            is_long = qty > 0

            # Check SL first (priority over target)
            if sl:
                if is_long and candle["low"] <= sl:
                    self.close_position(symbol, sl, "SL triggered")
                    continue
                elif not is_long and candle["high"] >= sl:
                    self.close_position(symbol, sl, "SL triggered (short)")
                    continue

            # Check target
            if target:
                if is_long and candle["high"] >= target:
                    self.close_position(symbol, target, "Target hit")
                elif not is_long and candle["low"] <= target:
                    self.close_position(symbol, target, "Target hit (short)")

    # ─── P&L RECORDING ───

    def record_trade_pnl(
        self, symbol: str, pnl: float,
        product: str = "MIS", exchange: str = "NSE",
    ):
        """Record realized P&L for a closed trade in the trades table."""
        self.db.execute(
            "INSERT INTO trades (timestamp, symbol, exchange, transaction_type, "
            "quantity, price, product, order_type, status, mode, pnl) "
            "VALUES (?, ?, ?, 'CLOSE', 0, 0, ?, 'MARKET', 'COMPLETE', 'PAPER', ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, exchange, product, pnl),
        )

    # ─── SL / TARGET MODIFICATION ───

    def modify_sl_target(
        self, symbol: str, exchange: str = "NSE",
        new_stop_loss: Optional[float] = None,
        new_target: Optional[float] = None,
        reason: str = "",
    ) -> dict:
        """
        Update stop_loss and/or target on an open paper position OR on the
        implied SL/target of a CNC holding (stored as paper_positions row
        with product='CNC' if tracked, otherwise updates the most recent
        matching trade record's stop_loss/target).
        Returns {status, message, old_sl, new_sl, old_target, new_target}.
        """
        result = {
            "status": "NO_CHANGE", "message": "",
            "old_sl": None, "new_sl": None,
            "old_target": None, "new_target": None,
        }

        # Prefer open MIS position row (has sl/target columns)
        pos = self.db.fetchone(
            "SELECT * FROM paper_positions WHERE symbol = ? AND exchange = ? "
            "AND quantity != 0 ORDER BY entry_timestamp DESC LIMIT 1",
            (symbol, exchange),
        )
        updates = []
        params = []
        if pos:
            result["old_sl"] = pos.get("stop_loss") if hasattr(pos, "get") else pos["stop_loss"]
            result["old_target"] = pos.get("target") if hasattr(pos, "get") else pos["target"]
            if new_stop_loss is not None:
                updates.append("stop_loss = ?")
                params.append(new_stop_loss)
                result["new_sl"] = new_stop_loss
            if new_target is not None:
                updates.append("target = ?")
                params.append(new_target)
                result["new_target"] = new_target

            if updates:
                params.extend([symbol, exchange])
                self.db.execute(
                    f"UPDATE paper_positions SET {', '.join(updates)} "
                    f"WHERE symbol = ? AND exchange = ? AND quantity != 0",
                    params,
                )
                result["status"] = "MODIFIED"
                result["message"] = (
                    f"Updated {symbol}: SL {result['old_sl']} -> {result['new_sl']}, "
                    f"TGT {result['old_target']} -> {result['new_target']} ({reason})"
                )
                logger.info(result["message"])
            return result

        # Fall back: update SL/target on the most recent BUY trade record for a CNC holding
        holding = self.db.fetchone(
            "SELECT * FROM paper_holdings WHERE symbol = ? AND exchange = ? "
            "AND quantity > 0",
            (symbol, exchange),
        )
        if not holding:
            result["message"] = f"No open position or holding for {symbol}"
            return result

        latest_trade = self.db.fetchone(
            "SELECT id, stop_loss, target FROM trades WHERE symbol = ? AND exchange = ? "
            "AND transaction_type = 'BUY' AND status = 'COMPLETE' AND mode = 'PAPER' "
            "ORDER BY timestamp DESC LIMIT 1",
            (symbol, exchange),
        )
        if not latest_trade:
            result["message"] = f"No trade record for {symbol} to update"
            return result

        result["old_sl"] = latest_trade["stop_loss"]
        result["old_target"] = latest_trade["target"]
        sets = []
        params = []
        if new_stop_loss is not None:
            sets.append("stop_loss = ?")
            params.append(new_stop_loss)
            result["new_sl"] = new_stop_loss
        if new_target is not None:
            sets.append("target = ?")
            params.append(new_target)
            result["new_target"] = new_target
        if not sets:
            return result

        params.append(latest_trade["id"])
        self.db.execute(
            f"UPDATE trades SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        result["status"] = "MODIFIED"
        result["message"] = (
            f"Updated CNC {symbol}: SL {result['old_sl']} -> {result['new_sl']}, "
            f"TGT {result['old_target']} -> {result['new_target']} ({reason})"
        )
        logger.info(result["message"])
        return result

    # ─── MARKET DATA HELPERS ───

    def get_ltp(self, symbol: str, exchange: str = "NSE") -> float:
        """Get last traded price from data client."""
        try:
            key = f"{exchange}:{symbol}"
            quote = self.data_client.get_ltp([key])
            return quote.get(key, {}).get("last_price", 0)
        except Exception as e:
            logger.error(f"Failed to get LTP for {symbol}: {e}")
            return 0

    def get_candle_or_ltp(
        self, symbol: str, exchange: str = "NSE",
    ) -> Optional[dict]:
        """
        Get latest completed OHLC candle. Falls back to synthetic candle
        from LTP if market_data is unavailable.
        """
        if self.market_data:
            try:
                candle = self.market_data.fetch_recent_candle(symbol, exchange)
                if candle:
                    return candle
            except Exception as e:
                logger.debug(f"Candle fetch failed for {symbol}: {e}")

        # Fallback: synthetic candle from LTP
        ltp = self.get_ltp(symbol, exchange)
        if ltp > 0:
            return {"open": ltp, "high": ltp, "low": ltp, "close": ltp, "volume": 0}
        return None
