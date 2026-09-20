"""
Performance Tracker.
Computes rolling and cumulative performance metrics for Claude's prompts.
All queries filter by trading mode (PAPER/LIVE) to keep metrics separate.
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """
    Computes trading performance metrics from the trades DB.
    Used to populate the PERFORMANCE CONTEXT section in prompts.
    """

    def __init__(self, db, config: dict):
        self.db = db
        self.config = config
        self._starting_capital = config.get("experiment", {}).get("starting_capital", 100000)
        self._mode = config.get("trading", {}).get("mode", "PAPER")

    def get_rolling_performance(self, days: int = 5) -> dict:
        """
        Get rolling N-day performance summary for prompt context.
        Returns dict matching the PERFORMANCE CONTEXT format in the spec.
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        try:
            rows = self.db.fetchall(
                """SELECT * FROM trades
                   WHERE DATE(timestamp) >= ?
                   AND status = 'COMPLETE'
                   AND transaction_type IN ('BUY', 'SELL', 'CLOSE')
                   AND mode = ?
                   ORDER BY timestamp""",
                (cutoff, self._mode),
            )
        except Exception as e:
            logger.error(f"Failed to query trades for performance: {e}")
            return {}

        if not rows:
            return {}

        # Compute metrics
        wins = 0
        losses = 0
        breakeven = 0
        total_win_amount = 0
        total_loss_amount = 0
        largest_win = 0
        largest_loss = 0

        for row in rows:
            # sqlite3.Row supports __getitem__ but not .get(), so use keys() guard
            pnl = row["pnl"] if "pnl" in row.keys() else 0
            if pnl is None:
                pnl = 0

            if pnl > 0:
                wins += 1
                total_win_amount += pnl
                if pnl > largest_win:
                    largest_win = pnl
            elif pnl < 0:
                losses += 1
                total_loss_amount += abs(pnl)
                if abs(pnl) > largest_loss:
                    largest_loss = abs(pnl)
            else:
                breakeven += 1

        total_trades = wins + losses + breakeven
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        avg_win = (total_win_amount / wins) if wins > 0 else 0
        avg_loss = (total_loss_amount / losses) if losses > 0 else 0
        profit_factor = (
            total_win_amount / total_loss_amount
            if total_loss_amount > 0
            else float("inf") if total_win_amount > 0
            else 0
        )
        net_pnl = total_win_amount - total_loss_amount

        # Cumulative P&L (for this mode only)
        cumulative_row = self.db.fetchone(
            """SELECT COALESCE(SUM(pnl), 0) as total_pnl FROM trades
               WHERE status = 'COMPLETE' AND mode = ?""",
            (self._mode,),
        )
        cumulative_pnl = cumulative_row["total_pnl"] if cumulative_row else 0

        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 0),
            "avg_loss": round(avg_loss, 0),
            "profit_factor": round(profit_factor, 2),
            "largest_win": round(largest_win, 0),
            "largest_loss": round(largest_loss, 0),
            "net_pnl_5d": round(net_pnl, 0),
            "cumulative_pnl": round(cumulative_pnl, 0),
            "period_days": days,
        }

    def get_daily_summary(self, target_date: str = None) -> dict:
        """
        Get summary for a specific trading day.
        Used for EOD review and daily summary notifications.
        """
        if target_date is None:
            target_date = date.today().isoformat()

        try:
            rows = self.db.fetchall(
                """SELECT * FROM trades
                   WHERE DATE(timestamp) = ? AND status = 'COMPLETE' AND mode = ?""",
                (target_date, self._mode),
            )
        except Exception:
            rows = []

        trades_count = len(rows)
        # sqlite3.Row has __getitem__ but no .get() — coerce to dict first.
        rows = [dict(r) for r in rows]
        wins = sum(1 for r in rows if (r.get("pnl") or 0) > 0)
        losses = sum(1 for r in rows if (r.get("pnl") or 0) < 0)
        total_pnl = sum(r.get("pnl", 0) or 0 for r in rows)

        # Cumulative (for this mode only)
        cum_row = self.db.fetchone(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades "
            "WHERE status = 'COMPLETE' AND mode = ?",
            (self._mode,),
        )
        cumulative_pnl = cum_row["total"] if cum_row else 0

        return {
            "date": target_date,
            "trades_count": trades_count,
            "wins": wins,
            "losses": losses,
            "total_pnl": round(total_pnl, 0),
            "cumulative_pnl": round(cumulative_pnl, 0),
        }

    def save_daily_summary(self, portfolio_value: float, market_bias: str = "", notes: str = ""):
        """Save the daily summary to the database."""
        today = date.today().isoformat()
        summary = self.get_daily_summary(today)

        # Get LLM costs
        cost_row = self.db.fetchone(
            "SELECT total_cost_usd, total_calls FROM llm_daily_costs WHERE date = ?",
            (today,),
        )
        llm_cost = cost_row["total_cost_usd"] if cost_row else 0
        llm_calls = cost_row["total_calls"] if cost_row else 0

        # Compute experiment day number
        start_str = self.config.get("experiment", {}).get("start_date", "2026-03-01")
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        day_number = (date.today() - start_date).days + 1

        try:
            self.db.execute(
                """INSERT OR REPLACE INTO daily_summaries
                   (date, day_number, trades_count, wins, losses,
                    total_pnl, cumulative_pnl, portfolio_value,
                    market_bias, notes, llm_cost_usd, llm_calls_count, mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    today, day_number,
                    summary["trades_count"], summary["wins"], summary["losses"],
                    summary["total_pnl"], summary["cumulative_pnl"],
                    portfolio_value, market_bias, notes,
                    llm_cost, llm_calls,
                    self._mode,
                ),
            )
            logger.info(f"Daily summary saved for {today} ({self._mode})")
        except Exception as e:
            logger.error(f"Failed to save daily summary: {e}")

    def save_portfolio_snapshot(self, portfolio_state: dict):
        """Save a point-in-time portfolio snapshot."""
        try:
            total = portfolio_state.get("total_value", 0)
            cash = portfolio_state.get("cash", 0)
            deployed = total - cash
            pnl = portfolio_state.get("daily_pnl", {})
            daily_pnl = pnl.get("realized", 0) + pnl.get("unrealized", 0)
            cumulative = total - self._starting_capital

            self.db.execute(
                """INSERT INTO portfolio_snapshots
                   (timestamp, total_value, cash_available, deployed,
                    daily_pnl, cumulative_pnl, holdings_json, positions_json, mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    total, cash, deployed, daily_pnl, cumulative,
                    json.dumps(portfolio_state.get("holdings", [])),
                    json.dumps(portfolio_state.get("mis_positions", [])),
                    self._mode,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to save portfolio snapshot: {e}")
