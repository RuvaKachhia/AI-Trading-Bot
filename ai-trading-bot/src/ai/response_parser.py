"""
Response Parser.
Parses and validates Claude's JSON responses into structured action dicts.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ResponseParser:
    """
    Parses Claude's JSON responses into validated action dicts.
    Handles both MARKET_PULSE and TRADING_DECISION response formats.
    """

    def __init__(self, config: dict):
        self.config = config
        self._max_watchlist = config.get("pipeline", {}).get("max_watchlist_size", 15)

    def parse_market_pulse(self, response: dict) -> Optional[dict]:
        """
        Parse a MARKET_PULSE response from Sonnet.
        Returns: {
            market_read: str,
            watchlist: [{symbol, exchange, reason}],
            drop_from_watchlist: [str],
            drop_reasons: str,
        }
        """
        if not response or not isinstance(response, dict):
            logger.warning("Invalid Market Pulse response: not a dict")
            return None

        result = {
            "market_read": response.get("market_read", ""),
            "watchlist": [],
            "drop_from_watchlist": response.get("drop_from_watchlist", []),
            "drop_reasons": response.get("drop_reasons", ""),
        }

        # Parse watchlist
        raw_watchlist = response.get("watchlist", [])
        if not isinstance(raw_watchlist, list):
            logger.warning("Invalid watchlist in Market Pulse response")
            return result

        for item in raw_watchlist[:self._max_watchlist]:
            if isinstance(item, dict):
                symbol = item.get("symbol", "").upper().strip()
                if symbol:
                    result["watchlist"].append({
                        "symbol": symbol,
                        "exchange": item.get("exchange", "NSE").upper(),
                        "reason": item.get("reason", ""),
                    })
            elif isinstance(item, str):
                result["watchlist"].append({
                    "symbol": item.upper().strip(),
                    "exchange": "NSE",
                    "reason": "",
                })

        if not result["watchlist"]:
            logger.warning("Empty watchlist in Market Pulse response")

        return result

    def parse_trading_decision(self, response: dict) -> Optional[dict]:
        """
        Parse a TRADING_DECISION response from Opus.
        Returns: {
            market_assessment: {bias, reasoning, key_levels},
            decisions: [{action, symbol, exchange, product, quantity, ...}],
            position_actions: [{symbol, current_action, new_stop_loss, reasoning}],
            watchlist_notes: str,
            portfolio_notes: str,
        }
        """
        if not response or not isinstance(response, dict):
            logger.warning("Invalid Trading Decision response: not a dict")
            return None

        result = {
            "market_assessment": self._parse_market_assessment(
                response.get("market_assessment", {})
            ),
            "decisions": [],
            "position_actions": [],
            "watchlist_notes": response.get("watchlist_notes", ""),
            "portfolio_notes": response.get("portfolio_notes", ""),
        }

        # Parse decisions
        for dec in response.get("decisions", []):
            parsed = self._parse_decision(dec)
            if parsed:
                result["decisions"].append(parsed)

        # Parse position actions
        for pa in response.get("position_actions", []):
            parsed = self._parse_position_action(pa)
            if parsed:
                result["position_actions"].append(parsed)

        return result

    def _parse_market_assessment(self, raw: dict) -> dict:
        """Parse and validate market assessment."""
        if not isinstance(raw, dict):
            return {"bias": "NEUTRAL", "reasoning": "", "key_levels": {}}

        bias = raw.get("bias", "NEUTRAL").upper()
        if bias not in ("BULLISH", "BEARISH", "NEUTRAL", "CAUTIOUS"):
            bias = "NEUTRAL"

        return {
            "bias": bias,
            "reasoning": raw.get("reasoning", ""),
            "key_levels": raw.get("key_levels", {}),
        }

    def _parse_decision(self, raw: dict) -> Optional[dict]:
        """Parse and validate a single trading decision."""
        if not isinstance(raw, dict):
            return None

        action = raw.get("action", "").upper()
        if action not in ("BUY", "SELL", "HOLD", "EXIT", "NO_ACTION", "MODIFY"):
            logger.warning(f"Invalid action: {action}")
            return None

        symbol = raw.get("symbol", "").upper().strip()
        if not symbol and action not in ("NO_ACTION", "HOLD"):
            logger.warning("Decision missing symbol")
            return None

        # Determine transaction type from action
        if action == "BUY":
            transaction_type = "BUY"
        elif action in ("SELL", "EXIT"):
            transaction_type = "SELL"
        else:
            transaction_type = action  # HOLD / NO_ACTION / MODIFY — no transaction

        product = raw.get("product", "CNC").upper()
        if product not in ("CNC", "MIS"):
            product = "CNC"

        order_type = raw.get("order_type", "LIMIT").upper()
        if order_type not in ("LIMIT", "MARKET", "SL"):
            order_type = "LIMIT"

        # MODIFY accepts new_stop_loss / new_target instead of (or alongside) stop_loss/target
        new_stop_loss = raw.get("new_stop_loss")
        new_target = raw.get("new_target")

        return {
            "action": action,
            "transaction_type": transaction_type,
            "symbol": symbol,
            "exchange": raw.get("exchange", "NSE").upper(),
            "product": product,
            "quantity": int(raw.get("quantity", 0)),
            "order_type": order_type,
            "price": float(raw.get("price", 0)),
            "stop_loss": float(raw.get("stop_loss", 0)) if raw.get("stop_loss") else None,
            "target": float(raw.get("target", 0)) if raw.get("target") else None,
            "new_stop_loss": float(new_stop_loss) if new_stop_loss else None,
            "new_target": float(new_target) if new_target else None,
            "confidence": float(raw.get("confidence", 0)),
            "timeframe": raw.get("timeframe", "SWING").upper(),
            "max_hold_days": int(raw.get("max_hold_days", 0)),
            "reasoning": raw.get("reasoning", ""),
        }

    def _parse_position_action(self, raw: dict) -> Optional[dict]:
        """Parse and validate a position action."""
        if not isinstance(raw, dict):
            return None

        symbol = raw.get("symbol", "").upper().strip()
        if not symbol:
            return None

        action = raw.get("current_action", "HOLD").upper()
        if action not in ("HOLD", "TRAIL_SL", "BOOK_PARTIAL", "EXIT"):
            action = "HOLD"

        return {
            "symbol": symbol,
            "current_action": action,
            "new_stop_loss": raw.get("new_stop_loss"),
            "reasoning": raw.get("reasoning", ""),
        }


class PromptSizeManager:
    """
    Splits watchlist stocks across multiple Opus calls if the deep dive
    prompt would exceed the configured token limit.
    """

    def __init__(self, config: dict):
        self.max_tokens = config.get("resilience", {}).get("max_prompt_tokens", 12000)
        self.overhead_tokens = 2500  # market context + portfolio + positions
        self.per_stock_tokens = 600  # average tokens per stock deep dive

    def split_watchlist(
        self, watchlist: list[str], held_symbols: list[str]
    ) -> list[list[str]]:
        """
        Returns list of batches. Each batch is a list of stock symbols.
        Held symbols are included in EVERY batch.
        """
        available_tokens = self.max_tokens - self.overhead_tokens
        held_tokens = len(held_symbols) * self.per_stock_tokens
        new_stock_budget = available_tokens - held_tokens
        max_new_per_batch = max(1, new_stock_budget // self.per_stock_tokens)

        # Separate held from new picks
        new_picks = [s for s in watchlist if s not in held_symbols]

        batches = []
        for i in range(0, max(1, len(new_picks)), max_new_per_batch):
            batch = held_symbols + new_picks[i:i + max_new_per_batch]
            batches.append(batch)

        if not batches:
            batches = [held_symbols] if held_symbols else [[]]

        return batches

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token for English."""
        return len(text) // 4
