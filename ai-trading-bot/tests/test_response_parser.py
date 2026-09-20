"""Tests for the Response Parser and PromptSizeManager."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from src.ai.response_parser import ResponseParser, PromptSizeManager


@pytest.fixture
def config():
    return {
        "pipeline": {"max_watchlist_size": 15},
        "resilience": {"max_prompt_tokens": 12000},
    }


@pytest.fixture
def parser(config):
    return ResponseParser(config)


@pytest.fixture
def size_mgr(config):
    return PromptSizeManager(config)


class TestResponseParserMarketPulse:
    def test_valid_market_pulse(self, parser):
        response = {
            "market_read": "Markets are cautiously bullish today.",
            "watchlist": [
                {"symbol": "RELIANCE", "exchange": "NSE", "reason": "Breakout above 2500"},
                {"symbol": "INFY", "exchange": "NSE", "reason": "Strong results"},
            ],
            "drop_from_watchlist": ["TATAMOTORS"],
            "drop_reasons": "Weak momentum",
        }
        result = parser.parse_market_pulse(response)
        assert result is not None
        assert result["market_read"] == "Markets are cautiously bullish today."
        assert len(result["watchlist"]) == 2
        assert result["watchlist"][0]["symbol"] == "RELIANCE"
        assert result["drop_from_watchlist"] == ["TATAMOTORS"]

    def test_string_watchlist(self, parser):
        response = {
            "market_read": "Bullish",
            "watchlist": ["RELIANCE", "infy", "  TCS  "],
        }
        result = parser.parse_market_pulse(response)
        assert len(result["watchlist"]) == 3
        assert result["watchlist"][1]["symbol"] == "INFY"  # uppercased
        assert result["watchlist"][2]["symbol"] == "TCS"  # stripped

    def test_none_response(self, parser):
        assert parser.parse_market_pulse(None) is None

    def test_non_dict_response(self, parser):
        assert parser.parse_market_pulse("not a dict") is None

    def test_empty_watchlist(self, parser):
        result = parser.parse_market_pulse({"market_read": "Flat", "watchlist": []})
        assert result is not None
        assert len(result["watchlist"]) == 0

    def test_watchlist_truncated_to_max(self, parser):
        response = {
            "market_read": "Test",
            "watchlist": [{"symbol": f"SYM{i}", "reason": ""} for i in range(20)],
        }
        result = parser.parse_market_pulse(response)
        assert len(result["watchlist"]) == 15  # max_watchlist_size


class TestResponseParserTradingDecision:
    def test_valid_trading_decision(self, parser):
        response = {
            "market_assessment": {
                "bias": "BULLISH",
                "reasoning": "Strong breadth",
                "key_levels": {"NIFTY": {"support": 22000, "resistance": 22500}},
            },
            "decisions": [
                {
                    "action": "BUY",
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "product": "CNC",
                    "quantity": 5,
                    "order_type": "LIMIT",
                    "price": 2500,
                    "stop_loss": 2450,
                    "target": 2600,
                    "confidence": 0.75,
                    "timeframe": "SWING",
                    "max_hold_days": 7,
                    "reasoning": "Strong breakout",
                },
            ],
            "position_actions": [
                {
                    "symbol": "INFY",
                    "current_action": "TRAIL_SL",
                    "new_stop_loss": 1550,
                    "reasoning": "Strong momentum",
                },
            ],
        }
        result = parser.parse_trading_decision(response)
        assert result is not None
        assert result["market_assessment"]["bias"] == "BULLISH"
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["symbol"] == "RELIANCE"
        assert result["decisions"][0]["confidence"] == 0.75
        assert len(result["position_actions"]) == 1
        assert result["position_actions"][0]["current_action"] == "TRAIL_SL"

    def test_invalid_action_skipped(self, parser):
        response = {
            "decisions": [
                {"action": "YOLO", "symbol": "TEST"},
                {"action": "BUY", "symbol": "RELIANCE", "confidence": 0.8, "price": 100},
            ],
        }
        result = parser.parse_trading_decision(response)
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["symbol"] == "RELIANCE"

    def test_invalid_bias_defaults_neutral(self, parser):
        response = {
            "market_assessment": {"bias": "MOON"},
            "decisions": [],
        }
        result = parser.parse_trading_decision(response)
        assert result["market_assessment"]["bias"] == "NEUTRAL"

    def test_transaction_type_mapping(self, parser):
        response = {
            "decisions": [
                {"action": "BUY", "symbol": "A", "confidence": 0.8, "price": 100},
                {"action": "SELL", "symbol": "B", "confidence": 0.8, "price": 100},
                {"action": "EXIT", "symbol": "C", "confidence": 0.8, "price": 100},
            ],
        }
        result = parser.parse_trading_decision(response)
        assert result["decisions"][0]["transaction_type"] == "BUY"
        assert result["decisions"][1]["transaction_type"] == "SELL"
        assert result["decisions"][2]["transaction_type"] == "SELL"

    def test_default_product_cnc(self, parser):
        response = {"decisions": [{"action": "BUY", "symbol": "X", "price": 100, "confidence": 0.8}]}
        result = parser.parse_trading_decision(response)
        assert result["decisions"][0]["product"] == "CNC"

    def test_none_response(self, parser):
        assert parser.parse_trading_decision(None) is None


class TestPromptSizeManager:
    def test_single_batch_small_watchlist(self, size_mgr):
        batches = size_mgr.split_watchlist(
            ["A", "B", "C", "D"], held_symbols=[]
        )
        assert len(batches) == 1
        assert set(batches[0]) == {"A", "B", "C", "D"}

    def test_held_in_every_batch(self, size_mgr):
        # Force multiple batches by having many symbols
        watchlist = [f"SYM{i}" for i in range(30)]
        held = ["HELD1", "HELD2"]
        batches = size_mgr.split_watchlist(watchlist, held)
        for batch in batches:
            assert "HELD1" in batch
            assert "HELD2" in batch

    def test_empty_watchlist(self, size_mgr):
        batches = size_mgr.split_watchlist([], [])
        assert len(batches) == 1

    def test_estimate_tokens(self, size_mgr):
        text = "Hello world"  # 11 chars -> ~2-3 tokens
        estimate = size_mgr.estimate_tokens(text)
        assert estimate == 2  # 11 // 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
