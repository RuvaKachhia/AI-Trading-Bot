"""Tests for the LLM Interaction Logger."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from src.database.db import Database
from src.database.migrations import run_migrations
from src.ai.llm_logger import LLMInteractionLogger


@pytest.fixture
def db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = Database(tmp.name)
    run_migrations(database)
    yield database
    database.close()
    os.unlink(tmp.name)


@pytest.fixture
def config():
    return {
        "experiment": {
            "start_date": "2026-03-01",
        },
        "llm_pricing": {
            "claude-sonnet-4-5-20250929": {
                "input_per_1m": 3.00,
                "output_per_1m": 15.00,
                "cache_read_per_1m": 0.30,
                "cache_create_per_1m": 3.75,
            },
            "claude-opus-4-7": {
                "input_per_1m": 5.00,
                "output_per_1m": 25.00,
                "cache_read_per_1m": 0.50,
                "cache_create_per_1m": 6.25,
            },
            "claude-opus-4-6": {
                "input_per_1m": 15.00,
                "output_per_1m": 75.00,
                "cache_read_per_1m": 1.50,
                "cache_create_per_1m": 18.75,
            },
            "claude-haiku-4-5-20251001": {
                "input_per_1m": 1.00,
                "output_per_1m": 5.00,
                "cache_read_per_1m": 0.10,
                "cache_create_per_1m": 1.25,
            },
        },
        "logging": {
            "log_dir": tempfile.mkdtemp(),
            "save_prompts": True,
            "save_responses": True,
        },
    }


@pytest.fixture
def llm_logger(db, config):
    return LLMInteractionLogger(db, config)


class TestLLMLogger:
    def test_compute_cost_sonnet(self, llm_logger):
        cost = llm_logger.compute_cost(
            model="claude-sonnet-4-5-20250929",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_creation_tokens=0,
        )
        assert "input_cost_usd" in cost
        assert "output_cost_usd" in cost
        assert cost["input_cost_usd"] > 0
        assert cost["output_cost_usd"] > 0
        assert cost["total_cost_usd"] > 0

    def test_compute_cost_unknown_model_uses_opus_fallback(self, llm_logger):
        cost = llm_logger.compute_cost(
            model="unknown-model",
            input_tokens=100,
            output_tokens=50,
        )
        # Unknown model falls back to Opus rates (most expensive = safe default)
        assert cost["total_cost_usd"] > 0

    def test_log_call(self, llm_logger, config):
        import tempfile, os
        # Save prompt and response files first
        prompt_file = os.path.join(config["logging"]["log_dir"], "test_prompt.txt")
        resp_file = os.path.join(config["logging"]["log_dir"], "test_resp.json")
        with open(prompt_file, "w") as f:
            f.write("Test prompt")
        with open(resp_file, "w") as f:
            f.write("{}")

        call_id = llm_logger.generate_call_id("MARKET_PULSE")
        record = llm_logger.log_call(
            call_id=call_id,
            session_id="test_session",
            model="claude-sonnet-4-5-20250929",
            call_type="MARKET_PULSE",
            response={"usage": {"input_tokens": 100, "output_tokens": 50}},
            latency_ms=500,
            prompt_file=prompt_file,
            response_file=resp_file,
        )
        assert record is not None
        assert record.call_id == call_id

    def test_get_daily_cost(self, llm_logger, db):
        # Insert a cost record manually
        from datetime import date
        today = date.today().isoformat()
        db.execute(
            "INSERT INTO llm_daily_costs (date, day_number, total_cost_usd, total_calls) "
            "VALUES (?, ?, ?, ?)",
            (today, 1, 15.50, 5),
        )
        cost = llm_logger.get_daily_cost()
        assert cost.get("total_cost_usd") == 15.50
        assert cost.get("total_calls") == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
