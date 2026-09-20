"""
Trade Execution Engine.
Routes validated orders to PaperBroker for simulated fills.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Executes validated orders via PaperBroker.
    """

    def __init__(self, db, config: dict, notifier=None,
                 trade_logger=None, paper_broker=None):
        self.db = db
        self.notifier = notifier
        self.trade_logger = trade_logger
        self.paper_broker = paper_broker

    def execute_order(self, order: dict, session_id: str = "") -> dict:
        """
        Execute a single validated order.
        Returns {order_id, status, fill_price, message}.
        """
        action = order.get("action", "").upper()

        # MODIFY: adjust SL/target on an existing position — not a new trade
        if action == "MODIFY":
            modify_result = self.paper_broker.modify_sl_target(
                symbol=order.get("symbol", ""),
                exchange=order.get("exchange", "NSE"),
                new_stop_loss=order.get("new_stop_loss"),
                new_target=order.get("new_target"),
                reason=order.get("reasoning", "")[:100],
            )
            return {
                "order_id": f"MODIFY_{order.get('symbol', '')}",
                "status": modify_result.get("status", "NO_CHANGE"),
                "fill_price": None,
                "message": modify_result.get("message", ""),
            }

        result = self.paper_broker.execute_order(order)

        # Log trade to DB
        self._log_trade_to_db(order, result, session_id)

        # Log to immutable CSV
        if self.trade_logger:
            self.trade_logger.log_trade({
                **order,
                "order_id": result.get("order_id", ""),
                "fill_price": result.get("fill_price", ""),
                "status": result.get("status", ""),
                "mode": "PAPER",
                "guardrail_result": "PASSED",
                "guardrail_errors": "",
            })

        # Send notification
        if self.notifier and result.get("status") == "COMPLETE":
            self.notifier.send_trade_alert(
                symbol=order.get("symbol", ""),
                action=order.get("transaction_type", order.get("action", "")),
                quantity=order.get("quantity", 0),
                price=result.get("fill_price", order.get("price", 0)),
                order_type=order.get("product", ""),
                reasoning=order.get("reasoning", "")[:100],
            )

        return result

    def _log_trade_to_db(self, order: dict, result: dict, session_id: str):
        """Log trade to the main trades table."""
        try:
            self.db.execute(
                """INSERT INTO trades
                   (timestamp, symbol, exchange, transaction_type, quantity, price,
                    product, order_type, stop_loss, target, confidence, timeframe,
                    max_hold_days, reasoning, order_id, status, fill_price,
                    mode, claude_session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    order.get("symbol", ""),
                    order.get("exchange", "NSE"),
                    order.get("transaction_type", order.get("action", "")),
                    order.get("quantity", 0),
                    order.get("price", 0),
                    order.get("product", "CNC"),
                    order.get("order_type", "LIMIT"),
                    order.get("stop_loss"),
                    order.get("target"),
                    order.get("confidence"),
                    order.get("timeframe"),
                    order.get("max_hold_days"),
                    order.get("reasoning", "")[:500],
                    result.get("order_id", ""),
                    result.get("status", ""),
                    result.get("fill_price"),
                    "PAPER",
                    session_id,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to log trade to DB: {e}")


class GuardrailLogger:
    """Logs guardrail validation results to both DB and CSV."""

    def __init__(self, db, csv_logger=None):
        self.db = db
        self.csv_logger = csv_logger

    def log_validation(
        self, order: dict, validation_result, llm_call_id: str = None
    ):
        """Log a guardrail validation result."""
        import json

        try:
            self.db.execute(
                """INSERT INTO guardrail_log
                   (timestamp, llm_call_id, is_valid, errors_json, warnings_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    llm_call_id,
                    validation_result.is_valid,
                    json.dumps(validation_result.errors),
                    json.dumps(validation_result.warnings),
                ),
            )
        except Exception as e:
            logger.error(f"Failed to log guardrail result: {e}")

        if self.csv_logger:
            self.csv_logger.log_validation(
                symbol=order.get("symbol", ""),
                action=order.get("action", ""),
                product=order.get("product", ""),
                is_valid=validation_result.is_valid,
                errors=validation_result.errors,
                warnings=validation_result.warnings,
            )
