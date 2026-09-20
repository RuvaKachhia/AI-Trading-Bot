"""
Telegram notification sender.
Sends trade alerts, daily summaries, error notifications, and guardrail alerts.
"""

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096  # Telegram message limit


class TelegramNotifier:
    """Sends notifications via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.enabled = bool(bot_token and chat_id)

        if not self.enabled:
            logger.warning("Telegram notifier disabled: missing bot_token or chat_id")

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a text message via Telegram."""
        if not self.enabled:
            logger.info(f"[Telegram disabled] {text[:200]}")
            return False

        # Truncate if too long
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[: MAX_MESSAGE_LENGTH - 20] + "\n... [truncated]"

        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            if response.status_code == 200:
                return True
            else:
                logger.error(
                    f"Telegram send failed: {response.status_code} {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def send_trade_alert(self, trade: dict) -> bool:
        """Send a trade execution alert."""
        side = trade.get("transaction_type", "?")
        symbol = trade.get("symbol", "?")
        qty = trade.get("quantity", "?")
        price = trade.get("fill_price") or trade.get("price", "?")
        product = trade.get("product", "?")
        sl = trade.get("stop_loss", "N/A")
        target = trade.get("target", "N/A")
        confidence = trade.get("confidence", "N/A")
        reasoning = trade.get("reasoning", "")[:150]

        msg = (
            f"<b>TRADE EXECUTED</b>\n"
            f"{side} {symbol} x{qty} @ {price}\n"
            f"Product: {product} | SL: {sl} | Target: {target}\n"
            f"Confidence: {confidence}\n"
            f"Reason: {reasoning}"
        )
        return self.send_message(msg)

    def send_guardrail_alert(self, symbol: str, action: str,
                              errors: list) -> bool:
        """Send an alert when guardrails block a trade."""
        msg = (
            f"<b>GUARDRAIL BLOCKED</b>\n"
            f"Action: {action} {symbol}\n"
            f"Errors:\n" + "\n".join(f"- {e}" for e in errors)
        )
        return self.send_message(msg)

    def send_daily_summary(self, summary: dict) -> bool:
        """Send end-of-day P&L summary."""
        msg = (
            f"<b>DAILY SUMMARY - Day {summary.get('day_number', '?')}</b>\n"
            f"P&L: {summary.get('daily_pnl', 0):+.2f} "
            f"({summary.get('daily_pnl_pct', 0):+.2f}%)\n"
            f"Cumulative: {summary.get('cumulative_pnl', 0):+.2f} "
            f"({summary.get('cumulative_pnl_pct', 0):+.2f}%)\n"
            f"Trades: {summary.get('trades_count', 0)} | "
            f"Wins: {summary.get('wins', 0)} | "
            f"Losses: {summary.get('losses', 0)}\n"
            f"Portfolio: {summary.get('portfolio_value', 0):,.0f}\n"
            f"Cash: {summary.get('cash_remaining', 0):,.0f}\n"
            f"LLM Cost: ${summary.get('llm_cost_usd', 0):.4f}"
        )
        return self.send_message(msg)

    def send_error_alert(self, error_type: str, details: str) -> bool:
        """Send a system error alert."""
        msg = f"<b>ERROR: {error_type}</b>\n{details[:500]}"
        return self.send_message(msg)

    def send_loss_limit_alert(self, current_loss: float,
                               limit: float) -> bool:
        """Alert when daily loss limit is hit."""
        msg = (
            f"<b>DAILY LOSS LIMIT HIT</b>\n"
            f"Current loss: {current_loss:,.0f}\n"
            f"Limit: {limit:,.0f}\n"
            f"All new trades STOPPED for today."
        )
        return self.send_message(msg)

    def send_safe_mode_alert(self, reason: str) -> bool:
        """Alert when circuit breaker activates safe mode."""
        msg = (
            f"<b>SAFE MODE ACTIVATED</b>\n"
            f"Reason: {reason}\n"
            f"No new trades. Existing SL/targets remain active on broker."
        )
        return self.send_message(msg)

    def send_mis_exit_alert(self, stage: int, symbol: str,
                             details: str) -> bool:
        """Alert for MIS auto-exit stages."""
        msg = (
            f"<b>MIS EXIT Stage {stage}</b>\n"
            f"Symbol: {symbol}\n"
            f"{details}"
        )
        return self.send_message(msg)


class DummyNotifier:
    """Console-only notifier for testing without Telegram credentials."""

    def send_message(self, text: str, **kwargs) -> bool:
        logger.info(f"[DummyNotifier] {text[:300]}")
        return True

    def send_trade_alert(self, trade: dict = None, **kwargs) -> bool:
        payload = trade if isinstance(trade, dict) else kwargs
        return self.send_message(
            f"Trade: {payload.get('action', payload.get('transaction_type', ''))} "
            f"{payload.get('symbol', '')} x{payload.get('quantity', '')} "
            f"@ {payload.get('price', '')}"
        )

    def send_guardrail_alert(self, *args, **kwargs) -> bool:
        return self.send_message("Guardrail alert")

    def send_daily_summary(self, *args, **kwargs) -> bool:
        return self.send_message("Daily summary")

    def send_error_alert(self, *args, **kwargs) -> bool:
        msg = " ".join(str(a) for a in args)
        return self.send_message(f"Error: {msg[:200]}")

    def send_loss_limit_alert(self, current_loss: float,
                               limit: float) -> bool:
        return self.send_message(f"Loss limit hit: {current_loss}")

    def send_safe_mode_alert(self, reason: str) -> bool:
        return self.send_message(f"Safe mode: {reason}")

    def send_mis_exit_alert(self, *args, **kwargs) -> bool:
        msg = " ".join(str(a) for a in args)
        return self.send_message(f"MIS exit: {msg[:200]}")


def create_notifier(config: dict) -> TelegramNotifier | DummyNotifier:
    """Factory: creates real or dummy notifier based on config."""
    bot_token = config.get("telegram", {}).get("bot_token", "")
    chat_id = config.get("telegram", {}).get("chat_id", "")

    # Resolve env vars
    if bot_token.startswith("${"):
        import os
        env_var = bot_token[2:-1]
        bot_token = os.environ.get(env_var, "")
    if chat_id.startswith("${"):
        import os
        env_var = chat_id[2:-1]
        chat_id = os.environ.get(env_var, "")

    if bot_token and chat_id:
        return TelegramNotifier(bot_token, chat_id)
    else:
        logger.warning("Using DummyNotifier (no Telegram credentials)")
        return DummyNotifier()
