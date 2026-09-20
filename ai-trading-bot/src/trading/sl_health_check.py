"""
SL & Target Health Check.
Paper mode: delegates OHLC-based monitoring to PaperBroker.
Also applies a deterministic trailing stop-loss (paper-only, for now).
"""

import logging

logger = logging.getLogger(__name__)


class SLHealthCheck:
    """
    Runs every 5 minutes during market hours.
    Two jobs:
      1. Delegate SL/target fill checks to PaperBroker (candle-based).
      2. Auto-trail stop-loss for winning positions, so gains are protected
         even if Claude doesn't act between cycles.

    Trailing rules (long positions):
      - LTP >= entry * (1 + breakeven_at_pct)  -> raise SL to at least entry
      - LTP >= entry * (1 + trail_start_pct)   -> raise SL to LTP * (1 - trail_gap_pct)
      - Never lowers an existing SL.
    Mirrored for short MIS positions.
    """

    def __init__(self, db, notifier=None, config: dict = None,
                 market_data=None, paper_broker=None):
        self.db = db
        self.notifier = notifier
        self.config = config or {}
        self.market_data = market_data
        self.paper_broker = paper_broker

        trailing = (config or {}).get("trailing_sl", {})
        self._enabled = trailing.get("enabled", True)
        self._breakeven_at_pct = trailing.get("breakeven_at_pct", 0.02)  # 2%
        self._trail_start_pct = trailing.get("trail_start_pct", 0.04)    # 4%
        self._trail_gap_pct = trailing.get("trail_gap_pct", 0.02)        # 2%

    def check(self):
        """Run the health check. Called every 5 minutes."""
        self.paper_broker.check_holding_sl_orders()
        self.paper_broker.check_position_sl_targets()
        if self._enabled:
            try:
                self._trail_mis_positions()
                self._trail_cnc_holdings()
            except Exception as e:
                logger.error(f"Trailing SL failed: {e}", exc_info=True)

    def _trail_mis_positions(self):
        """Tighten SL on winning MIS positions."""
        rows = self.db.fetchall(
            "SELECT symbol, exchange, side, entry_price, quantity, stop_loss, target "
            "FROM paper_positions WHERE quantity != 0 AND product = 'MIS'"
        )
        for row in rows:
            symbol = row["symbol"]
            exchange = row.get("exchange", "NSE") if hasattr(row, "get") else row["exchange"]
            entry = row["entry_price"]
            current_sl = row["stop_loss"] or 0
            side = row["side"]
            if entry <= 0:
                continue

            ltp = self.paper_broker.get_ltp(symbol, exchange)
            if ltp <= 0:
                continue

            new_sl = self._compute_trailing_sl(side, entry, ltp, current_sl)
            if new_sl is not None and new_sl != current_sl:
                self.paper_broker.modify_sl_target(
                    symbol=symbol, exchange=exchange,
                    new_stop_loss=new_sl,
                    reason=f"auto-trail ltp={ltp:.2f}",
                )

    def _trail_cnc_holdings(self):
        """
        Tighten SL on winning CNC holdings. SL is stored on the most recent
        BUY trade record (holdings table has no SL column).
        """
        rows = self.db.fetchall(
            "SELECT symbol, exchange, quantity, avg_price "
            "FROM paper_holdings WHERE quantity > 0"
        )
        for row in rows:
            symbol = row["symbol"]
            exchange = row.get("exchange", "NSE") if hasattr(row, "get") else row["exchange"]
            entry = row["avg_price"]
            if entry <= 0:
                continue

            ltp = self.paper_broker.get_ltp(symbol, exchange)
            if ltp <= 0:
                continue

            trade = self.db.fetchone(
                "SELECT id, stop_loss FROM trades WHERE symbol = ? AND exchange = ? "
                "AND transaction_type = 'BUY' AND status = 'COMPLETE' AND mode = 'PAPER' "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol, exchange),
            )
            if not trade:
                continue
            current_sl = trade["stop_loss"] or 0

            new_sl = self._compute_trailing_sl("BUY", entry, ltp, current_sl)
            if new_sl is not None and new_sl != current_sl:
                self.paper_broker.modify_sl_target(
                    symbol=symbol, exchange=exchange,
                    new_stop_loss=new_sl,
                    reason=f"auto-trail ltp={ltp:.2f}",
                )

    def _compute_trailing_sl(
        self, side: str, entry: float, ltp: float, current_sl: float
    ) -> float | None:
        """
        Return the new SL value if it should be raised (long) or lowered (short).
        Never returns a value that would loosen the existing SL.
        """
        if entry <= 0 or ltp <= 0:
            return None

        if side == "BUY":
            gain_pct = (ltp - entry) / entry
            candidate = None
            if gain_pct >= self._trail_start_pct:
                candidate = round(ltp * (1 - self._trail_gap_pct), 2)
            elif gain_pct >= self._breakeven_at_pct:
                candidate = round(entry, 2)
            if candidate is None:
                return None
            # Only raise, never lower
            return candidate if candidate > current_sl else None

        # Short (MIS SELL)
        gain_pct = (entry - ltp) / entry
        candidate = None
        if gain_pct >= self._trail_start_pct:
            candidate = round(ltp * (1 + self._trail_gap_pct), 2)
        elif gain_pct >= self._breakeven_at_pct:
            candidate = round(entry, 2)
        if candidate is None:
            return None
        # For shorts, "tighter" = lower SL. Only lower, never raise.
        # current_sl == 0 means no SL set — always accept candidate.
        if current_sl == 0:
            return candidate
        return candidate if candidate < current_sl else None
