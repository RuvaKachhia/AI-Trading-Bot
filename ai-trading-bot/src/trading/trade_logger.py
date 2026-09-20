"""
Append-only, immutable trade logger.
Creates one CSV per trading day. Never modifies existing entries.
This is the ground truth audit trail — DB can be rebuilt from these.
"""

import csv
import os
import logging
from datetime import datetime
from filelock import FileLock

logger = logging.getLogger(__name__)


class TradeLogger:
    """
    Append-only trade CSV logger.
    No update or delete methods exist — this class is append-only by design.
    """

    HEADERS = [
        "timestamp",
        "day_number",
        "mode",
        "order_id",
        "symbol",
        "exchange",
        "side",
        "product",
        "order_type",
        "quantity",
        "signal_price",
        "fill_price",
        "stop_loss",
        "target",
        "confidence",
        "timeframe",
        "max_hold_days",
        "reasoning",
        "status",
        "guardrail_result",
        "guardrail_errors",
    ]

    def __init__(self, log_dir: str = "logs/trades"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def _get_filepath(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"trades_{today}.csv")

    def log_trade(self, trade: dict) -> None:
        """Append a single trade record. NEVER modifies existing rows."""
        filepath = self._get_filepath()
        lock = FileLock(filepath + ".lock")

        with lock:
            file_exists = os.path.exists(filepath)
            with open(filepath, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.HEADERS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "day_number": trade.get("day_number", ""),
                        "mode": trade.get("mode", ""),
                        "order_id": trade.get("order_id", ""),
                        "symbol": trade.get("symbol", ""),
                        "exchange": trade.get("exchange", ""),
                        "side": trade.get("transaction_type", ""),
                        "product": trade.get("product", ""),
                        "order_type": trade.get("order_type", ""),
                        "quantity": trade.get("quantity", ""),
                        "signal_price": trade.get("price", ""),
                        "fill_price": trade.get("fill_price", ""),
                        "stop_loss": trade.get("stop_loss", ""),
                        "target": trade.get("target", ""),
                        "confidence": trade.get("confidence", ""),
                        "timeframe": trade.get("timeframe", ""),
                        "max_hold_days": trade.get("max_hold_days", ""),
                        "reasoning": trade.get("reasoning", "").replace("\n", " "),
                        "status": trade.get("status", ""),
                        "guardrail_result": trade.get("guardrail_result", ""),
                        "guardrail_errors": trade.get("guardrail_errors", ""),
                    }
                )

        logger.info(
            f"Trade logged: {trade.get('transaction_type', '')} "
            f"{trade.get('symbol', '')} x{trade.get('quantity', '')} "
            f"@ {trade.get('price', '')} [{trade.get('status', '')}]"
        )


class GuardrailLogger:
    """Append-only guardrail validation CSV logger."""

    HEADERS = [
        "timestamp",
        "symbol",
        "action",
        "product",
        "result",
        "errors",
        "warnings",
    ]

    def __init__(self, log_dir: str = "logs/guardrails"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def _get_filepath(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"guardrails_{today}.csv")

    def log_validation(self, symbol: str, action: str, product: str,
                       is_valid: bool, errors: list, warnings: list) -> None:
        """Log a guardrail validation result."""
        filepath = self._get_filepath()
        lock = FileLock(filepath + ".lock")

        with lock:
            file_exists = os.path.exists(filepath)
            with open(filepath, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.HEADERS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "symbol": symbol,
                        "action": action,
                        "product": product,
                        "result": "PASSED" if is_valid else "FAILED",
                        "errors": "; ".join(errors),
                        "warnings": "; ".join(warnings),
                    }
                )


class PnLLogger:
    """Append-only daily P&L CSV logger."""

    HEADERS = [
        "date",
        "day_number",
        "starting_value",
        "ending_value",
        "daily_pnl",
        "daily_pnl_pct",
        "cumulative_pnl",
        "cumulative_pnl_pct",
        "trades_count",
        "wins",
        "losses",
        "cash_remaining",
        "deployed_pct",
    ]

    def __init__(self, log_dir: str = "logs/pnl"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def log_daily(self, data: dict) -> None:
        """Append a daily P&L row."""
        filepath = os.path.join(self.log_dir, "pnl_daily.csv")
        lock = FileLock(filepath + ".lock")

        with lock:
            file_exists = os.path.exists(filepath)
            with open(filepath, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.HEADERS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(data)
