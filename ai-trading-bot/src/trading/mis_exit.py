"""
MIS Auto-Exit Engine.
Ensures all MIS positions are closed before market close.
4-stage independent exit process via APScheduler.

CRITICAL: Each stage is an INDEPENDENT scheduled job. If one crashes,
the next still runs.
"""

import logging

logger = logging.getLogger(__name__)


class MISAutoExitEngine:
    """
    4-stage MIS exit process:
    Stage 1 (3:00 PM): LIMIT exit orders with small tolerance
    Stage 2 (3:05 PM): Cancel unfilled, re-place at revised LTP
    Stage 3 (3:10 PM): HARD DEADLINE — force MARKET orders
    Stage 4 (3:12 PM): Emergency check — final MARKET + alert
    """

    def __init__(self, portfolio_state, config: dict,
                 notifier=None, db=None, paper_broker=None, data_client=None):
        self.portfolio = portfolio_state
        self.config = config
        self.notifier = notifier
        self.db = db
        self.paper_broker = paper_broker
        self.data_client = data_client

    def stage_1_graceful_exit(self):
        """3:00 PM — Place LIMIT exit orders with small slippage tolerance."""
        try:
            open_mis = self._get_open_mis()
            if not open_mis:
                logger.info("MIS Exit Stage 1: No open MIS positions")
                return

            logger.info(f"MIS Exit Stage 1: Closing {len(open_mis)} positions (LIMIT)")

            for pos in open_mis:
                try:
                    ltp = self._get_ltp(pos["symbol"], pos.get("exchange", "NSE"))
                    if ltp <= 0:
                        continue

                    exit_side = "SELL" if pos["side"] == "BUY" else "BUY"

                    if exit_side == "SELL":
                        limit_price = round(ltp * 0.999, 1)
                    else:
                        limit_price = round(ltp * 1.001, 1)

                    self._place_exit_order(
                        pos, exit_side, limit_price, "LIMIT", "Stage 1"
                    )
                except Exception as e:
                    logger.error(f"Stage 1 error for {pos.get('symbol')}: {e}")

        except Exception as e:
            msg = f"MIS EXIT Stage 1 FAILED: {e}"
            logger.error(msg)
            if self.notifier:
                self.notifier.send_mis_exit_alert(msg)

    def stage_2_retry_unfilled(self):
        """3:05 PM — Cancel unfilled LIMIT orders and re-place at current LTP."""
        try:
            open_mis = self._get_open_mis()
            if not open_mis:
                logger.info("MIS Exit Stage 2: All MIS positions closed")
                return

            logger.info(f"MIS Exit Stage 2: {len(open_mis)} positions still open, retrying")

            self.paper_broker.cancel_pending_mis_orders()

            for pos in open_mis:
                try:
                    ltp = self._get_ltp(pos["symbol"], pos.get("exchange", "NSE"))
                    if ltp <= 0:
                        continue

                    exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
                    self._place_exit_order(pos, exit_side, ltp, "LIMIT", "Stage 2")
                except Exception as e:
                    logger.error(f"Stage 2 error for {pos.get('symbol')}: {e}")

        except Exception as e:
            msg = f"MIS EXIT Stage 2 FAILED: {e}"
            logger.error(msg)
            if self.notifier:
                self.notifier.send_mis_exit_alert(msg)

    def stage_3_force_market_close(self):
        """3:10 PM — HARD DEADLINE. Use MARKET orders. Accept any slippage."""
        try:
            open_mis = self._get_open_mis()
            if not open_mis:
                logger.info("MIS Exit Stage 3: All MIS positions closed")
                return

            logger.warning(
                f"MIS Exit Stage 3 (FORCED): {len(open_mis)} positions, using MARKET orders"
            )

            self.paper_broker.cancel_pending_mis_orders()

            for pos in open_mis:
                try:
                    exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
                    self._place_exit_order(pos, exit_side, 0, "MARKET", "Stage 3 FORCED")
                except Exception as e:
                    logger.error(f"Stage 3 error for {pos.get('symbol')}: {e}")

        except Exception as e:
            msg = f"MIS EXIT Stage 3 FAILED: {e}"
            logger.error(msg)
            if self.notifier:
                self.notifier.send_mis_exit_alert(msg)

    def stage_4_emergency_check(self):
        """3:12 PM — If ANYTHING is still open, something went very wrong."""
        try:
            open_mis = self._get_open_mis()
            if not open_mis:
                logger.info("MIS Exit Stage 4: All clear, no open MIS positions")
                return

            symbols = [p.get("symbol", "") for p in open_mis]
            msg = (
                f"EMERGENCY: MIS positions STILL OPEN at 3:12 PM: {symbols}. "
                f"Attempting final MARKET close."
            )
            logger.critical(msg)

            if self.notifier:
                self.notifier.send_mis_exit_alert(msg)

            for pos in open_mis:
                try:
                    exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
                    self._place_exit_order(pos, exit_side, 0, "MARKET", "Stage 4 EMERGENCY")
                except Exception as e:
                    err_msg = f"CRITICAL: Failed to close {pos.get('symbol')}: {e}"
                    logger.critical(err_msg)
                    if self.notifier:
                        self.notifier.send_error_alert(err_msg)

        except Exception as e:
            msg = f"EMERGENCY CHECK FAILED: {e}"
            logger.critical(msg)
            if self.notifier:
                self.notifier.send_error_alert(msg)

    # ─── HELPERS ───

    def _get_open_mis(self) -> list[dict]:
        """Get all open MIS positions."""
        positions = self.portfolio.get_positions()
        return [p for p in positions if p.get("quantity", 0) != 0]

    def _get_ltp(self, symbol: str, exchange: str = "NSE") -> float:
        """Get current LTP via data client."""
        try:
            key = f"{exchange}:{symbol}"
            quote = self.data_client.get_ltp([key])
            return quote.get(key, {}).get("last_price", 0)
        except Exception:
            return 0

    def _place_exit_order(
        self, pos: dict, exit_side: str, price: float,
        order_type: str, stage_label: str
    ):
        """Place a paper exit order."""
        symbol = pos.get("symbol", "")
        exchange = pos.get("exchange", "NSE")
        qty = abs(pos.get("quantity", 0))

        ltp = self._get_ltp(symbol, exchange) if price == 0 else price
        if ltp > 0:
            self.paper_broker.close_position(
                symbol, ltp, f"MIS {stage_label}"
            )
        logger.info(
            f"MIS {stage_label}: Paper {exit_side} {symbol} x{qty} @ INR {ltp}"
        )

        if self.notifier:
            self.notifier.send_mis_exit_alert(
                f"MIS {stage_label}: {exit_side} {symbol} x{qty} "
                f"@ {'MARKET' if order_type == 'MARKET' else f'INR {price:.2f}'}"
            )
