"""
Guardrail Validation Engine.
Every Claude decision is validated here BEFORE execution.
This is the most safety-critical component.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Agent-managed override file (written by Risk Monitor / Strategy agents)
_RISK_OVERRIDE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agents", "risk_config.yaml",
)


@dataclass
class ValidationResult:
    """Result of guardrail validation for a single order."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    order: dict = field(default_factory=dict)  # potentially modified order


class GuardrailEngine:
    """
    Validates every trading decision against hard-coded rules.
    Claude's output MUST pass all checks before any order is placed.
    """

    def __init__(
        self,
        config: dict,
        portfolio_state,
        instrument_manager=None,
        notifier=None,
    ):
        self.config = config
        self.portfolio = portfolio_state
        self.instruments = instrument_manager
        self.notifier = notifier

        trading = config.get("trading", {})
        risk = config.get("risk", {})

        self._max_position_pct = trading.get("max_position_pct", 0.20)
        self._max_sector_pct = trading.get("max_sector_pct", 0.35)
        self._max_deployed_pct = trading.get("max_deployed_pct", 0.80)
        self._min_cash_buffer_pct = trading.get("min_cash_buffer_pct", 0.20)
        self._min_stock_price = trading.get("min_stock_price", 10)
        self._max_cnc_hold_days = trading.get("max_cnc_hold_days", 15)
        self._unwind_days = trading.get("unwind_phase_days", 5)
        self._no_new_mis_after = trading.get("no_new_mis_after", "14:30")

        self._daily_loss_limit_pct = risk.get("daily_loss_limit_pct", 0.075)
        self._default_sl_pct = risk.get("default_sl_pct", 0.02)
        self._min_sl_pct = risk.get("min_sl_pct", 0.005)
        self._max_sl_pct = risk.get("max_sl_pct", 0.06)
        self._min_confidence = risk.get("min_confidence", 0.50)
        self._duplicate_window = config.get("resilience", {}).get(
            "duplicate_order_window_min", 5
        )

        # Save base values so overrides never exceed them
        self._base_risk = {
            "daily_loss_limit_pct": self._daily_loss_limit_pct,
            "default_sl_pct": self._default_sl_pct,
            "min_sl_pct": self._min_sl_pct,
            "max_sl_pct": self._max_sl_pct,
            "min_confidence": self._min_confidence,
        }
        self._base_trading = {
            "max_position_pct": self._max_position_pct,
            "max_sector_pct": self._max_sector_pct,
            "max_deployed_pct": self._max_deployed_pct,
            "min_cash_buffer_pct": self._min_cash_buffer_pct,
        }
        self._override_mtime: float = 0.0

        # ASM/GSM list (loaded externally)
        self._asm_gsm_list: set[str] = set()

        # Sector map (symbol -> sector name), set externally by orchestrator
        self._sector_map: dict[str, str] = {}

    def set_asm_gsm_list(self, symbols: list[str]) -> None:
        """Update the ASM/GSM restricted list."""
        self._asm_gsm_list = set(symbols)

    def set_sector_map(self, sector_map: dict[str, str]) -> None:
        """Set symbol -> sector mapping, used for concentration check."""
        self._sector_map = sector_map or {}

    def _validate_modify(self, order: dict) -> ValidationResult:
        """
        Validate a MODIFY (SL/target adjustment) decision.
        Rules:
          - Symbol must be currently held (holdings or MIS position)
          - new_stop_loss may only *tighten* (raise for long, lower for short)
          - new_target allowed in either direction but must be on the correct
            side of the entry (target above entry for long, below for short)
        """
        errors: list[str] = []
        warnings: list[str] = []
        symbol = order.get("symbol", "")
        if not symbol:
            return ValidationResult(False, errors=["BLOCKED: MODIFY missing symbol"], order=order)

        # Locate current position context
        holding_qty = self.portfolio.get_holdings_qty(symbol)
        mis_positions = [
            p for p in self.portfolio.get_positions() if p.get("symbol") == symbol
        ]
        if holding_qty <= 0 and not mis_positions:
            errors.append(f"BLOCKED: MODIFY for {symbol} but no open position/holding")
            return ValidationResult(False, errors=errors, order=order)

        # Determine side + current entry/SL
        if mis_positions:
            pos = mis_positions[0]
            side = pos.get("side", "BUY")
            entry = pos.get("entry", 0)
            current_sl = pos.get("stop_loss") or 0
            current_target = pos.get("target") or 0
        else:
            # CNC holding — side is always BUY
            side = "BUY"
            holdings = self.portfolio.get_holdings()
            entry = next((h.get("avg_price", 0) for h in holdings if h.get("symbol") == symbol), 0)
            current_sl = 0  # CNC holdings don't carry an SL column; tracked in trades
            current_target = 0

        new_sl = order.get("new_stop_loss")
        new_target = order.get("new_target")

        if new_sl is None and new_target is None:
            errors.append("BLOCKED: MODIFY must set new_stop_loss and/or new_target")
            return ValidationResult(False, errors=errors, order=order)

        # SL tightening rule
        if new_sl is not None and entry > 0:
            if side == "BUY":
                if current_sl and new_sl < current_sl:
                    errors.append(
                        f"BLOCKED: MODIFY SL for long {symbol} may only raise "
                        f"(current {current_sl}, requested {new_sl})"
                    )
                if new_sl > entry:
                    warnings.append(
                        f"MODIFY sets SL above entry ({new_sl} > {entry}) — locking in profit"
                    )
            else:  # SELL / short
                if current_sl and new_sl > current_sl:
                    errors.append(
                        f"BLOCKED: MODIFY SL for short {symbol} may only lower "
                        f"(current {current_sl}, requested {new_sl})"
                    )

        # Target sanity
        if new_target is not None and entry > 0:
            if side == "BUY" and new_target <= entry:
                errors.append(
                    f"BLOCKED: MODIFY target for long {symbol} must exceed entry "
                    f"({new_target} <= {entry})"
                )
            if side == "SELL" and new_target >= entry:
                errors.append(
                    f"BLOCKED: MODIFY target for short {symbol} must be below entry "
                    f"({new_target} >= {entry})"
                )

        if errors:
            return ValidationResult(False, errors=errors, warnings=warnings, order=order)
        return ValidationResult(True, warnings=warnings, order=order)

    def _apply_agent_overrides(self) -> None:
        """
        Load overrides from src/agents/risk_config.yaml and apply them. Both
        tightening and loosening are accepted, BUT loosening cannot go past
        the base config — base is the floor. This lets the Strategy / Risk
        Monitor agents revert an over-cautious tightening when its original
        trigger has resolved, while preventing them from drifting beyond
        the operator's authored safety floor.
        Re-reads only when the file's mtime changes.
        """
        if not os.path.exists(_RISK_OVERRIDE_PATH):
            return
        try:
            mtime = os.path.getmtime(_RISK_OVERRIDE_PATH)
            if mtime <= self._override_mtime:
                return
            with open(_RISK_OVERRIDE_PATH, "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Could not read risk_config.yaml: {e}")
            return

        overrides = (data.get("overrides") or {})
        risk_over = overrides.get("risk") or {}
        trading_over = overrides.get("trading") or {}

        # Parameters where HIGHER = tighter (e.g., min_confidence, min_cash_buffer_pct)
        tighter_when_higher = {
            "min_confidence", "min_sl_pct", "min_cash_buffer_pct",
        }
        # Parameters where LOWER = tighter (loss limits, max sizes)
        tighter_when_lower = {
            "daily_loss_limit_pct",
            "default_sl_pct", "max_sl_pct",
            "max_position_pct", "max_sector_pct", "max_deployed_pct",
        }

        def try_apply(param: str, new_value, base_value, attr: str) -> bool:
            """
            Apply override if it is between [stricter than base] and base
            (inclusive). For tighter_when_higher params, the override may
            sit anywhere in [base, ∞); for tighter_when_lower params,
            anywhere in (0, base]. Anything beyond base in the loose
            direction is silently clamped at base — base is the floor.
            """
            if not isinstance(new_value, (int, float)):
                return False
            if param in tighter_when_higher:
                # base is the floor (loose end); any value >= base is valid
                if new_value >= base_value:
                    setattr(self, attr, new_value)
                    return True
                # Loosening past base — clamp at base
                setattr(self, attr, base_value)
                return True
            if param in tighter_when_lower:
                # base is the ceiling (loose end); any value <= base is valid
                if new_value <= base_value:
                    setattr(self, attr, new_value)
                    return True
                # Loosening past base — clamp at base
                setattr(self, attr, base_value)
                return True
            return False

        applied = []
        # Reset to base before applying (in case override file shrinks)
        for k, v in self._base_risk.items():
            setattr(self, f"_{k}", v)
        for k, v in self._base_trading.items():
            setattr(self, f"_{k}", v)

        for k, v in risk_over.items():
            base = self._base_risk.get(k)
            if base is not None and try_apply(k, v, base, f"_{k}"):
                applied.append(f"risk.{k}={v}")
        for k, v in trading_over.items():
            base = self._base_trading.get(k)
            if base is not None and try_apply(k, v, base, f"_{k}"):
                applied.append(f"trading.{k}={v}")

        self._override_mtime = mtime
        if applied:
            logger.info(f"Guardrail overrides applied: {', '.join(applied)}")

    def validate_order(self, order: dict) -> ValidationResult:
        """
        Validate a single order dict from Claude's response.
        Returns ValidationResult with is_valid, errors, warnings.
        The order may be modified (e.g., default SL/target applied).
        """
        self._apply_agent_overrides()
        errors = []
        warnings = []
        order = dict(order)  # work on a copy

        # Skip validation for non-actionable decisions
        action = order.get("action", "").upper()
        if action in ("NO_ACTION", "HOLD"):
            return ValidationResult(is_valid=True, order=order)

        # MODIFY has its own validation path (not a new trade)
        if action == "MODIFY":
            return self._validate_modify(order)

        # ─── INSTRUMENT CHECKS ───
        if order.get("exchange") not in ("NSE", "BSE"):
            errors.append(
                f"BLOCKED: Exchange must be NSE or BSE. Got: {order.get('exchange')}"
            )

        if order.get("product") not in ("CNC", "MIS"):
            errors.append(
                f"BLOCKED: Product must be CNC or MIS. Got: {order.get('product')}"
            )

        # ─── SYMBOL VALIDATION ───
        symbol = order.get("symbol", "")
        if self.instruments and not self.instruments.is_valid_symbol(symbol):
            errors.append(f"BLOCKED: Symbol {symbol} not found in instrument list")

        # ─── ASM/GSM CHECK ───
        if symbol in self._asm_gsm_list:
            errors.append(f"BLOCKED: {symbol} is on ASM/GSM restricted list")

        # ─── PRICE CHECK ───
        price = order.get("price", 0)
        if price and price < self._min_stock_price and order.get("order_type") == "LIMIT":
            errors.append(f"BLOCKED: Stock price INR {price} below INR {self._min_stock_price} threshold")

        # ─── SHORT SELLING CHECK (SEBI) ───
        tx_type = order.get("transaction_type", order.get("action", "")).upper()
        if tx_type in ("SELL", "EXIT"):
            if order.get("product") == "CNC":
                holdings_qty = self.portfolio.get_holdings_qty(symbol)
                order_qty = order.get("quantity", 0)
                if holdings_qty < order_qty:
                    errors.append(
                        f"BLOCKED: Cannot short-sell in CNC. "
                        f"Holdings: {holdings_qty}, Order qty: {order_qty}"
                    )

        # ─── POSITION SIZING ───
        portfolio_value = self.portfolio.total_value()
        ltp = order.get("price", 0) or self._get_ltp(symbol, order.get("exchange", "NSE"))
        qty = order.get("quantity", 0)
        position_value = ltp * qty if ltp and qty else 0

        max_position = portfolio_value * self._max_position_pct
        if position_value > max_position:
            errors.append(
                f"BLOCKED: Position value INR {position_value:,.0f} exceeds "
                f"{self._max_position_pct*100:.0f}% of portfolio (INR {max_position:,.0f})"
            )

        # ─── CASH BUFFER CHECK ───
        if tx_type == "BUY" and position_value > 0:
            cash = self.portfolio.get_available_cash()
            remaining_cash = cash - position_value
            min_cash = portfolio_value * self._min_cash_buffer_pct
            if remaining_cash < min_cash:
                errors.append(
                    f"BLOCKED: Order would breach {self._min_cash_buffer_pct*100:.0f}% cash buffer. "
                    f"Cash after: INR {remaining_cash:,.0f}, Min: INR {min_cash:,.0f}"
                )

        # ─── DAILY LOSS LIMIT ───
        daily_pnl = self.portfolio.get_daily_pnl()
        total_daily_loss = daily_pnl.get("realized", 0) + daily_pnl.get("unrealized", 0)
        daily_limit = portfolio_value * self._daily_loss_limit_pct
        if total_daily_loss < -daily_limit:
            errors.append(
                f"BLOCKED: Daily loss limit hit. "
                f"Current loss: INR {abs(total_daily_loss):,.0f}, "
                f"Limit: INR {daily_limit:,.0f}"
            )

        # ─── SECTOR CONCENTRATION ───
        # Max 35% of portfolio in a single sector (including the new position)
        if tx_type == "BUY" and position_value > 0:
            new_sector = self._sector_map.get(symbol, "")
            if new_sector:
                current_sector_value = self._current_sector_exposure(new_sector)
                total_sector_value = current_sector_value + position_value
                max_sector_value = portfolio_value * self._max_sector_pct
                if total_sector_value > max_sector_value:
                    errors.append(
                        f"BLOCKED: Sector '{new_sector}' concentration would exceed "
                        f"{self._max_sector_pct*100:.0f}% "
                        f"(current INR {current_sector_value:,.0f} + new INR {position_value:,.0f} "
                        f"= INR {total_sector_value:,.0f}; max INR {max_sector_value:,.0f})"
                    )

        # ─── TIMING CHECKS ───
        now = datetime.now().time()
        mis_cutoff_parts = self._no_new_mis_after.split(":")
        mis_cutoff = time(int(mis_cutoff_parts[0]), int(mis_cutoff_parts[1]))

        if order.get("product") == "MIS" and tx_type == "BUY" and now > mis_cutoff:
            errors.append("BLOCKED: No new MIS orders after 2:30 PM IST")

        if now < time(9, 15) or now > time(15, 30):
            if not (now >= time(9, 0) and order.get("product") == "CNC"):
                errors.append("BLOCKED: Outside market hours")

        # ─── STOP-LOSS CHECK ───
        if not order.get("stop_loss"):
            if tx_type == "BUY":
                order["stop_loss"] = round(ltp * (1 - self._default_sl_pct), 2) if ltp else None
            elif tx_type in ("SELL", "EXIT"):
                order["stop_loss"] = round(ltp * (1 + self._default_sl_pct), 2) if ltp else None
            warnings.append(
                f"WARNING: No stop-loss specified. Applied default {self._default_sl_pct*100:.0f}% SL."
            )

        # ─── STOP-LOSS RANGE CHECK ───
        sl = order.get("stop_loss", 0)
        if sl and ltp and ltp > 0:
            if tx_type == "BUY":
                sl_pct = (ltp - sl) / ltp
            else:
                sl_pct = (sl - ltp) / ltp

            if sl_pct < self._min_sl_pct:
                warnings.append(
                    f"WARNING: SL too tight ({sl_pct:.1%}). Min {self._min_sl_pct*100:.1f}%."
                )
            if sl_pct > self._max_sl_pct:
                warnings.append(
                    f"WARNING: SL too wide ({sl_pct:.1%}). Max {self._max_sl_pct*100:.0f}%."
                )

        # ─── TARGET CHECK ───
        if not order.get("target"):
            default_target_pct = 0.03
            if tx_type == "BUY":
                order["target"] = round(ltp * (1 + default_target_pct), 2) if ltp else None
            elif tx_type in ("SELL", "EXIT"):
                order["target"] = round(ltp * (1 - default_target_pct), 2) if ltp else None
            warnings.append("WARNING: No target specified. Applied default 3% target.")

        # ─── CONFIDENCE CHECK ───
        confidence = order.get("confidence", 0)
        if confidence < self._min_confidence:
            errors.append(
                f"BLOCKED: Confidence ({confidence}) below {self._min_confidence} threshold"
            )

        # ─── EXPERIMENT PHASE CHECK ───
        exp = self.config.get("experiment", {})
        start_str = exp.get("start_date", "2026-03-01")
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        duration = exp.get("duration_days", 30)
        from datetime import timedelta
        end_date = start_date + timedelta(days=duration)
        today = datetime.now().date()
        # Count remaining trading days
        trading_days_left = 0
        d = today
        while d <= end_date:
            if d.weekday() < 5:
                trading_days_left += 1
            d += timedelta(days=1)

        if trading_days_left <= self._unwind_days:
            if order.get("product") == "CNC" and tx_type == "BUY":
                errors.append(
                    f"BLOCKED: In unwind phase (last {self._unwind_days} trading days). "
                    f"No new CNC positions allowed."
                )

        # ─── CNC HOLD DURATION CHECK ───
        max_hold = order.get("max_hold_days", 0)
        if order.get("product") == "CNC" and max_hold > self._max_cnc_hold_days:
            warnings.append(
                f"WARNING: Max hold days ({max_hold}) exceeds {self._max_cnc_hold_days}-day limit. "
                f"Capping."
            )
            order["max_hold_days"] = self._max_cnc_hold_days

        result = ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            order=order,
        )

        # Log result
        if not result.is_valid:
            logger.warning(
                f"Guardrail BLOCKED {symbol} {tx_type}: {'; '.join(errors)}"
            )
        if warnings:
            logger.info(f"Guardrail warnings for {symbol}: {'; '.join(warnings)}")

        return result

    def validate_all_decisions(self, decisions: list[dict]) -> list[ValidationResult]:
        """Validate a list of decisions from Claude's response."""
        results = []
        for decision in decisions:
            result = self.validate_order(decision)
            results.append(result)
        return results

    def _current_sector_exposure(self, sector: str) -> float:
        """
        Sum the INR value of all currently-held positions (CNC holdings + MIS
        open positions) that belong to `sector`.
        """
        if not sector:
            return 0.0
        total = 0.0
        # CNC holdings — use last_price for current value
        for h in self.portfolio.get_holdings():
            sym = h.get("symbol", "")
            if self._sector_map.get(sym, "") == sector:
                total += (h.get("last_price", 0) or h.get("avg_price", 0)) * h.get("quantity", 0)
        # MIS positions — use ltp for current value
        for p in self.portfolio.get_positions():
            sym = p.get("symbol", "")
            if self._sector_map.get(sym, "") == sector:
                total += (p.get("ltp", 0) or p.get("entry", 0)) * abs(p.get("quantity", 0))
        return total

    def _get_ltp(self, symbol: str, exchange: str = "NSE") -> float:
        """Get LTP for a symbol from portfolio state data."""
        # Try to get from portfolio's cached quotes
        quotes = getattr(self.portfolio, "_last_quotes", {})
        key = f"{exchange}:{symbol}"
        if key in quotes:
            return quotes[key].get("last_price", 0)
        return 0
