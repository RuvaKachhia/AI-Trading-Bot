"""Tests for the Guardrail Validation Engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock
from src.trading.guardrails import GuardrailEngine, ValidationResult


@pytest.fixture
def config():
    return {
        "experiment": {
            "start_date": "2026-03-01",
            "duration_days": 30,
            "starting_capital": 100000,
        },
        "trading": {
            "mode": "PAPER",
            "max_position_pct": 0.20,
            "max_deployed_pct": 0.80,
            "min_cash_buffer_pct": 0.20,
            "min_stock_price": 20,
            "max_cnc_hold_days": 15,
            "unwind_phase_days": 5,
            "no_new_mis_after": "14:30",
        },
        "risk": {
            "daily_loss_limit_pct": 0.03,
            "drawdown_reduce_pct": 0.10,
            "drawdown_halt_pct": 0.15,
            "default_sl_pct": 0.02,
            "min_sl_pct": 0.005,
            "max_sl_pct": 0.05,
            "min_confidence": 0.50,
        },
        "resilience": {
            "duplicate_order_window_min": 5,
        },
    }


@pytest.fixture
def mock_portfolio():
    portfolio = MagicMock()
    portfolio.total_value.return_value = 100000
    portfolio.get_available_cash.return_value = 80000
    portfolio.get_daily_pnl.return_value = {"realized": 0, "unrealized": 0}
    portfolio.trades_today_count.return_value = 0
    portfolio.get_holdings_qty.return_value = 0
    return portfolio


@pytest.fixture
def engine(config, mock_portfolio):
    return GuardrailEngine(
        config=config,
        portfolio_state=mock_portfolio,
        instrument_manager=None,
        notifier=None,
    )


class TestValidationResult:
    def test_valid_result(self):
        result = ValidationResult(is_valid=True, order={"symbol": "RELIANCE"})
        assert result.is_valid
        assert result.errors == []
        assert result.warnings == []

    def test_invalid_result(self):
        result = ValidationResult(
            is_valid=False,
            errors=["Price too low"],
            order={"symbol": "RELIANCE"},
        )
        assert not result.is_valid
        assert len(result.errors) == 1


class TestGuardrailEngine:
    def test_no_action_always_passes(self, engine):
        result = engine.validate_order({"action": "NO_ACTION"})
        assert result.is_valid

    def test_hold_always_passes(self, engine):
        result = engine.validate_order({"action": "HOLD"})
        assert result.is_valid

    def test_invalid_exchange_blocked(self, engine):
        order = {
            "action": "BUY",
            "symbol": "RELIANCE",
            "exchange": "NASDAQ",
            "product": "CNC",
            "quantity": 5,
            "price": 2500,
            "confidence": 0.7,
            "transaction_type": "BUY",
        }
        result = engine.validate_order(order)
        assert not result.is_valid
        assert any("Exchange must be NSE or BSE" in e for e in result.errors)

    def test_invalid_product_blocked(self, engine):
        order = {
            "action": "BUY",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "FUTURES",
            "quantity": 5,
            "price": 2500,
            "confidence": 0.7,
            "transaction_type": "BUY",
        }
        result = engine.validate_order(order)
        assert not result.is_valid
        assert any("Product must be CNC or MIS" in e for e in result.errors)

    def test_asm_gsm_blocked(self, engine):
        engine.set_asm_gsm_list(["YESBANK", "RCOM"])
        order = {
            "action": "BUY",
            "symbol": "YESBANK",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 100,
            "price": 25,
            "confidence": 0.7,
            "transaction_type": "BUY",
        }
        result = engine.validate_order(order)
        assert not result.is_valid
        assert any("ASM/GSM" in e for e in result.errors)

    def test_position_sizing_blocked(self, engine):
        # 20% of 100k = 20k. 100 qty * 300 = 30k > 20k
        order = {
            "action": "BUY",
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 100,
            "price": 300,
            "confidence": 0.7,
            "transaction_type": "BUY",
        }
        result = engine.validate_order(order)
        assert not result.is_valid
        assert any("Position value" in e for e in result.errors)

    def test_cash_buffer_check(self, engine, mock_portfolio):
        # Cash = 80k, order cost = 75k, remaining = 5k, min_cash = 20k
        mock_portfolio.get_available_cash.return_value = 80000
        order = {
            "action": "BUY",
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 20,
            "price": 500,  # 20*500 = 10k, within position limit, but check cash
            "confidence": 0.7,
            "transaction_type": "BUY",
        }
        # Position value = 10k, under 20% limit, and cash after = 70k > 20k min
        result = engine.validate_order(order)
        # This should pass (10k position, 70k remaining > 20k min)
        # May have other issues but no cash buffer error
        cash_errors = [e for e in result.errors if "cash buffer" in e.lower()]
        assert len(cash_errors) == 0

    def test_low_confidence_blocked(self, engine):
        order = {
            "action": "BUY",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 5,
            "price": 2500,
            "confidence": 0.3,  # Below 0.50 threshold
            "transaction_type": "BUY",
        }
        result = engine.validate_order(order)
        assert not result.is_valid
        assert any("Confidence" in e for e in result.errors)

    def test_default_sl_applied(self, engine):
        order = {
            "action": "BUY",
            "symbol": "ITC",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 5,
            "price": 1000,
            "confidence": 0.7,
            "transaction_type": "BUY",
        }
        result = engine.validate_order(order)
        # Should have a warning about default SL
        assert any("stop-loss" in w.lower() for w in result.warnings)
        assert result.order.get("stop_loss") is not None

    def test_default_target_applied(self, engine):
        order = {
            "action": "BUY",
            "symbol": "ITC",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 5,
            "price": 1000,
            "confidence": 0.7,
            "transaction_type": "BUY",
        }
        result = engine.validate_order(order)
        assert any("target" in w.lower() for w in result.warnings)
        assert result.order.get("target") is not None

    def test_cnc_short_sell_blocked(self, engine, mock_portfolio):
        mock_portfolio.get_holdings_qty.return_value = 5
        order = {
            "action": "SELL",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 10,  # Trying to sell more than held
            "price": 2500,
            "confidence": 0.8,
            "transaction_type": "SELL",
        }
        result = engine.validate_order(order)
        assert not result.is_valid
        assert any("short-sell" in e.lower() for e in result.errors)

    def test_validate_all_decisions(self, engine):
        decisions = [
            {"action": "NO_ACTION"},
            {"action": "HOLD"},
            {
                "action": "BUY",
                "symbol": "FAKE",
                "exchange": "MARS",
                "product": "CNC",
                "quantity": 1,
                "price": 100,
                "confidence": 0.8,
                "transaction_type": "BUY",
            },
        ]
        results = engine.validate_all_decisions(decisions)
        assert len(results) == 3
        assert results[0].is_valid
        assert results[1].is_valid
        assert not results[2].is_valid  # invalid exchange


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
