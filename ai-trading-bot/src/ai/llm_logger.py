"""
LLM Interaction Audit Logger.
Logs EVERY LLM API call to both SQLite (queryable) and CSV (immutable).
Saves full prompt text and raw API response to individual files.
"""

import csv
import json
import os
import hashlib
import logging
from datetime import datetime
from typing import Optional
from filelock import FileLock

from src.database.models import LLMCallRecord

logger = logging.getLogger(__name__)

# Default pricing (USD per 1M tokens). Overridden by config if provided.
# Source: https://claude.com/pricing
DEFAULT_LLM_PRICING = {
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
    "claude-sonnet-4-6": {
        "input_per_1m": 3.00,
        "output_per_1m": 15.00,
        "cache_read_per_1m": 0.30,
        "cache_create_per_1m": 3.75,
    },
    "claude-sonnet-4-5-20250929": {
        "input_per_1m": 3.00,
        "output_per_1m": 15.00,
        "cache_read_per_1m": 0.30,
        "cache_create_per_1m": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input_per_1m": 1.00,
        "output_per_1m": 5.00,
        "cache_read_per_1m": 0.10,
        "cache_create_per_1m": 1.25,
    },
}


class LLMInteractionLogger:
    """
    Logs every LLM API call to both SQLite (queryable) and CSV (immutable).
    Saves full prompt text and raw API response to individual files.
    """

    CSV_HEADERS = [
        "timestamp", "call_id", "session_id", "parent_call_id", "day_number",
        "model", "call_type", "call_subtype",
        "input_tokens", "output_tokens", "cache_read_tokens", "total_tokens",
        "total_cost_usd", "latency_ms", "status", "error_message",
        "decisions_count", "watchlist_symbols", "actions_summary",
        "system_prompt_file", "user_prompt_file", "response_file",
    ]

    def __init__(self, db, config: dict):
        self.db = db
        self.config = config
        self.log_dir = config.get("logging", {}).get("log_dir", "logs")
        self.llm_dir = os.path.join(self.log_dir, "llm")
        self.day_number = config.get("_day_number", 0)
        self._seq_counter: dict[str, int] = {}
        self._daily_call_counter = 0

        # Keep legacy dirs for backward compat
        for subdir in ["system", "prompts", "responses"]:
            os.makedirs(os.path.join(self.llm_dir, subdir), exist_ok=True)

        # Load pricing
        self.pricing = config.get("llm_pricing", DEFAULT_LLM_PRICING)

    def _get_call_dir(self, call_id: str, call_type: str) -> str:
        """
        Get the date-based directory for a specific call.
        Creates: logs/YYYY-MM-DD/ai/NNN_HHMM_call_type/
        """
        today = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M")
        self._daily_call_counter += 1
        seq = f"{self._daily_call_counter:03d}"
        dir_name = f"{seq}_{time_str}_{call_type.lower()}"
        call_dir = os.path.join(self.log_dir, today, "ai", dir_name)
        os.makedirs(call_dir, exist_ok=True)
        return call_dir

    def set_day_number(self, day_number: int) -> None:
        """Update the current experiment day number."""
        self.day_number = day_number

    def generate_call_id(self, call_type: str) -> str:
        """Generate a unique call ID: YYYYMMDD_HHMMSS_CALLTYPE_SEQ."""
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S")
        key = f"{ts}_{call_type}"
        self._seq_counter[key] = self._seq_counter.get(key, 0) + 1
        seq = f"{self._seq_counter[key]:03d}"
        return f"{ts}_{call_type}_{seq}"

    def save_prompt(self, call_id: str, system_prompt: str,
                    user_prompt: str, call_type: str = "") -> tuple[str, str]:
        """
        Save system prompt (versioned) and user prompt (per-call) to files.
        Writes to both new date-based structure and legacy flat dirs.
        Returns (system_prompt_file, user_prompt_file).
        """
        sys_file = self._save_system_prompt(system_prompt)

        # Legacy flat location
        user_file = os.path.join(self.llm_dir, "prompts", f"{call_id}.txt")
        with open(user_file, "w", encoding="utf-8") as f:
            f.write(user_prompt)

        # New date-based location
        if call_type:
            call_dir = self._get_call_dir(call_id, call_type)
            with open(os.path.join(call_dir, "system_prompt.txt"), "w", encoding="utf-8") as f:
                f.write(system_prompt)
            with open(os.path.join(call_dir, "user_prompt.txt"), "w", encoding="utf-8") as f:
                f.write(user_prompt)
            # Store call_dir for later use by save_response/save_metadata
            self._last_call_dir = call_dir

        return sys_file, user_file

    def _save_system_prompt(self, system_prompt: str) -> str:
        """Save system prompt if new, return path to versioned file."""
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:12]
        sys_file = os.path.join(
            self.llm_dir, "system", f"system_prompt_{prompt_hash}.txt"
        )
        if not os.path.exists(sys_file):
            with open(sys_file, "w", encoding="utf-8") as f:
                f.write(system_prompt)
            logger.info(f"New system prompt version saved: {sys_file}")
        return sys_file

    def save_response(self, call_id: str, raw_response: dict) -> str:
        """Save the complete raw API response as JSON."""
        resp_file = os.path.join(self.llm_dir, "responses", f"{call_id}.json")
        with open(resp_file, "w", encoding="utf-8") as f:
            json.dump(raw_response, f, indent=2, default=str)

        # Also write to new date-based location
        if hasattr(self, '_last_call_dir') and self._last_call_dir:
            try:
                with open(os.path.join(self._last_call_dir, "response_raw.json"), "w", encoding="utf-8") as f:
                    json.dump(raw_response, f, indent=2, default=str)
            except Exception:
                pass

        return resp_file

    def save_parsed_output(self, parsed_data: dict) -> None:
        """Save parsed/structured output to the date-based call directory."""
        if hasattr(self, '_last_call_dir') and self._last_call_dir and parsed_data:
            try:
                with open(os.path.join(self._last_call_dir, "response_parsed.json"), "w", encoding="utf-8") as f:
                    json.dump(parsed_data, f, indent=2, default=str)
            except Exception as e:
                logger.warning(f"Failed to save parsed output: {e}")

    def save_metadata(self, call_id: str, model: str, call_type: str,
                      tokens: dict, cost: dict, latency_ms: int, status: str) -> None:
        """Save per-call metadata to the date-based call directory."""
        if hasattr(self, '_last_call_dir') and self._last_call_dir:
            try:
                metadata = {
                    "call_id": call_id,
                    "model": model,
                    "call_type": call_type,
                    "timestamp": datetime.now().isoformat(),
                    "tokens": tokens,
                    "cost_usd": cost,
                    "latency_ms": latency_ms,
                    "status": status,
                }
                with open(os.path.join(self._last_call_dir, "metadata.json"), "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save metadata: {e}")

    def save_error_response(self, call_id: str, error: Exception,
                             http_status: int = None) -> str:
        """Save error details when an API call fails."""
        resp_file = os.path.join(self.llm_dir, "responses", f"{call_id}.json")
        with open(resp_file, "w", encoding="utf-8") as f:
            json.dump({
                "error": True,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "http_status_code": http_status,
                "timestamp": datetime.now().isoformat(),
            }, f, indent=2)
        return resp_file

    def compute_cost(self, model: str, input_tokens: int, output_tokens: int,
                     cache_read_tokens: int = 0,
                     cache_creation_tokens: int = 0) -> dict:
        """Compute cost in USD for a given token usage."""
        rates = self._get_rates(model)

        input_cost = (input_tokens / 1_000_000) * rates["input_per_1m"]
        output_cost = (output_tokens / 1_000_000) * rates["output_per_1m"]
        cache_read_cost = (cache_read_tokens / 1_000_000) * rates["cache_read_per_1m"]
        cache_create_cost = (cache_creation_tokens / 1_000_000) * rates["cache_create_per_1m"]

        return {
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "cache_read_cost_usd": round(cache_read_cost, 6),
            "cache_creation_cost_usd": round(cache_create_cost, 6),
            "total_cost_usd": round(
                input_cost + output_cost + cache_read_cost + cache_create_cost, 6
            ),
        }

    def _get_rates(self, model: str) -> dict:
        """Get pricing rates for a model, with fuzzy matching."""
        # Exact match
        entry = self.pricing.get(model)
        if isinstance(entry, dict):
            return entry
        # Partial match — only consider dict-valued entries (skip usd_inr_rate etc.)
        for key, rates in self.pricing.items():
            if isinstance(rates, dict) and (key in model or model in key):
                return rates
        # Fallback to any Opus entry, else first available dict entry
        logger.warning(f"Unknown model for pricing: {model}. Using Opus rates.")
        for opus_key in ("claude-opus-4-7", "claude-opus-4-6"):
            entry = self.pricing.get(opus_key)
            if isinstance(entry, dict):
                return entry
        for rates in self.pricing.values():
            if isinstance(rates, dict):
                return rates
        # Last-resort hardcoded rates (USD, Opus 4.7 levels)
        return {
            "input_per_1m": 5.00, "output_per_1m": 25.00,
            "cache_read_per_1m": 0.50, "cache_create_per_1m": 6.25,
        }

    def log_call(
        self,
        call_id: str,
        session_id: str,
        model: str,
        call_type: str,
        response: dict,
        latency_ms: int,
        prompt_file: str,
        response_file: str,
        system_prompt_file: str = None,
        parent_call_id: str = None,
        call_subtype: str = None,
        market_bias: str = None,
        decisions_count: int = 0,
        watchlist_symbols: str = None,
        actions_summary: str = None,
        trade_ids: str = None,
        status: str = "SUCCESS",
        error_message: str = None,
        http_status_code: int = 200,
    ) -> LLMCallRecord:
        """
        Log a complete LLM call to both DB and CSV.
        Returns the LLMCallRecord.
        """
        now = datetime.now()

        # Extract token counts from API response
        usage = response.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read_tokens = usage.get("cache_read_input_tokens", 0)
        cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
        stop_reason = response.get("stop_reason", None)

        # Compute cost
        cost = self.compute_cost(
            model, input_tokens, output_tokens,
            cache_read_tokens, cache_creation_tokens,
        )

        record = LLMCallRecord(
            call_id=call_id,
            session_id=session_id,
            parent_call_id=parent_call_id,
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            date=now.strftime("%Y-%m-%d"),
            day_number=self.day_number,
            response_timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            latency_ms=latency_ms,
            model=model,
            call_type=call_type,
            call_subtype=call_subtype,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            total_tokens=input_tokens + output_tokens,
            **cost,
            system_prompt_file=system_prompt_file,
            user_prompt_file=prompt_file,
            response_file=response_file,
            parsed_output_file=None,
            status=status,
            error_message=error_message,
            http_status_code=http_status_code,
            stop_reason=stop_reason,
            market_bias=market_bias,
            decisions_count=decisions_count,
            watchlist_symbols=watchlist_symbols,
            actions_summary=actions_summary,
            trade_ids=trade_ids,
        )

        self._write_to_db(record)
        self._write_to_csv(record)

        # Write metadata to date-based directory
        self.save_metadata(
            call_id, model, call_type,
            {"input": input_tokens, "output": output_tokens,
             "cache_read": cache_read_tokens, "cache_create": cache_creation_tokens},
            cost, latency_ms, status,
        )

        logger.info(
            f"LLM call logged: {call_id} | {model} | {call_type} | "
            f"{input_tokens}+{output_tokens} tokens | "
            f"${cost['total_cost_usd']:.4f} | {latency_ms}ms"
        )

        return record

    def log_failed_call(
        self,
        call_id: str,
        session_id: str,
        model: str,
        call_type: str,
        error: Exception,
        prompt_file: str,
        response_file: str,
        latency_ms: int = 0,
        http_status_code: int = None,
        **kwargs,
    ) -> LLMCallRecord:
        """Convenience method for logging failed API calls."""
        status = (
            "TIMEOUT" if "timeout" in str(error).lower()
            else "RATE_LIMITED" if http_status_code == 429
            else "ERROR"
        )

        return self.log_call(
            call_id=call_id,
            session_id=session_id,
            model=model,
            call_type=call_type,
            response={"usage": {}, "stop_reason": None},
            latency_ms=latency_ms,
            prompt_file=prompt_file,
            response_file=response_file,
            status=status,
            error_message=str(error),
            http_status_code=http_status_code,
            **kwargs,
        )

    def _write_to_db(self, record: LLMCallRecord) -> None:
        """Insert record into llm_calls table."""
        try:
            self.db.execute(
                """
                INSERT INTO llm_calls (
                    call_id, session_id, parent_call_id,
                    timestamp, date, day_number, response_timestamp, latency_ms,
                    model, call_type, call_subtype,
                    input_tokens, output_tokens, cache_read_tokens,
                    cache_creation_tokens,
                    input_cost_usd, output_cost_usd, cache_read_cost_usd,
                    cache_creation_cost_usd,
                    system_prompt_file, user_prompt_file, response_file,
                    parsed_output_file,
                    status, error_message, http_status_code, stop_reason,
                    market_bias, decisions_count, watchlist_symbols,
                    actions_summary, trade_ids
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    record.call_id, record.session_id, record.parent_call_id,
                    record.timestamp, record.date, record.day_number,
                    record.response_timestamp, record.latency_ms,
                    record.model, record.call_type, record.call_subtype,
                    record.input_tokens, record.output_tokens,
                    record.cache_read_tokens, record.cache_creation_tokens,
                    record.input_cost_usd, record.output_cost_usd,
                    record.cache_read_cost_usd, record.cache_creation_cost_usd,
                    record.system_prompt_file, record.user_prompt_file,
                    record.response_file, record.parsed_output_file,
                    record.status, record.error_message,
                    record.http_status_code, record.stop_reason,
                    record.market_bias, record.decisions_count,
                    record.watchlist_symbols, record.actions_summary,
                    record.trade_ids,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to write LLM call to DB: {e}")

    def _write_to_csv(self, record: LLMCallRecord) -> None:
        """Append record to immutable daily CSV."""
        filepath = os.path.join(
            self.llm_dir, f"llm_calls_{record.date}.csv"
        )
        lock = FileLock(filepath + ".lock")

        try:
            with lock:
                file_exists = os.path.exists(filepath)
                with open(filepath, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow({
                        "timestamp": record.timestamp,
                        "call_id": record.call_id,
                        "session_id": record.session_id,
                        "parent_call_id": record.parent_call_id or "",
                        "day_number": record.day_number,
                        "model": record.model,
                        "call_type": record.call_type,
                        "call_subtype": record.call_subtype or "",
                        "input_tokens": record.input_tokens,
                        "output_tokens": record.output_tokens,
                        "cache_read_tokens": record.cache_read_tokens,
                        "total_tokens": record.total_tokens,
                        "total_cost_usd": record.total_cost_usd,
                        "latency_ms": record.latency_ms,
                        "status": record.status,
                        "error_message": record.error_message or "",
                        "decisions_count": record.decisions_count,
                        "watchlist_symbols": record.watchlist_symbols or "",
                        "actions_summary": record.actions_summary or "",
                        "system_prompt_file": record.system_prompt_file or "",
                        "user_prompt_file": record.user_prompt_file,
                        "response_file": record.response_file,
                    })
        except Exception as e:
            logger.error(f"Failed to write LLM call to CSV: {e}")

    def rebuild_daily_costs(self, date_str: str = None) -> None:
        """
        Rebuild the llm_daily_costs table row for a given date.
        Called at end of day during post-market processing.
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        try:
            self.db.execute(
                """
                INSERT OR REPLACE INTO llm_daily_costs (
                    date, day_number,
                    haiku_calls, haiku_input_tokens, haiku_output_tokens, haiku_cost_usd,
                    sonnet_calls, sonnet_input_tokens, sonnet_output_tokens, sonnet_cost_usd,
                    opus_calls, opus_input_tokens, opus_output_tokens, opus_cost_usd,
                    news_calls, news_cost_usd,
                    pulse_calls, pulse_cost_usd,
                    decision_calls, decision_cost_usd,
                    eod_calls, eod_cost_usd,
                    premarket_calls, premarket_cost_usd,
                    retry_calls, retry_cost_usd,
                    total_calls, total_input_tokens, total_output_tokens,
                    total_tokens, total_cost_usd,
                    total_cache_read_tokens, cache_savings_usd,
                    failed_calls, retry_count
                )
                SELECT
                    date, MAX(day_number),
                    SUM(CASE WHEN model LIKE '%haiku%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%haiku%' THEN input_tokens ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%haiku%' THEN output_tokens ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%haiku%' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%sonnet%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%sonnet%' THEN input_tokens ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%sonnet%' THEN output_tokens ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%sonnet%' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%opus%' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%opus%' THEN input_tokens ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%opus%' THEN output_tokens ELSE 0 END),
                    SUM(CASE WHEN model LIKE '%opus%' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN call_type = 'NEWS_SUMMARY' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN call_type = 'NEWS_SUMMARY' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN call_type = 'MARKET_PULSE' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN call_type = 'MARKET_PULSE' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN call_type = 'TRADING_DECISION' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN call_type = 'TRADING_DECISION' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN call_type = 'EOD_REVIEW' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN call_type = 'EOD_REVIEW' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN call_type = 'PRE_MARKET' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN call_type = 'PRE_MARKET' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    SUM(CASE WHEN call_type = 'RETRY' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN call_type = 'RETRY' THEN
                        (input_cost_usd + output_cost_usd +
                         COALESCE(cache_read_cost_usd, 0) +
                         COALESCE(cache_creation_cost_usd, 0))
                        ELSE 0 END),
                    COUNT(*),
                    SUM(input_tokens),
                    SUM(output_tokens),
                    SUM(input_tokens + output_tokens),
                    SUM(input_cost_usd + output_cost_usd +
                        COALESCE(cache_read_cost_usd, 0) +
                        COALESCE(cache_creation_cost_usd, 0)),
                    SUM(cache_read_tokens),
                    SUM(COALESCE(cache_read_cost_usd, 0)),
                    SUM(CASE WHEN status != 'SUCCESS' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN call_type = 'RETRY' THEN 1 ELSE 0 END)
                FROM llm_calls
                WHERE date = ?
                """,
                (date_str,),
            )
            logger.info(f"Daily costs rebuilt for {date_str}")
        except Exception as e:
            logger.error(f"Failed to rebuild daily costs: {e}")

    def get_daily_cost(self, date_str: str = None) -> dict:
        """Get cost summary for a specific day."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        row = self.db.fetchone(
            "SELECT * FROM llm_daily_costs WHERE date = ?", (date_str,)
        )
        return dict(row) if row else {}

    def get_experiment_total_cost(self) -> float:
        """Get total LLM cost for the entire experiment so far."""
        row = self.db.fetchone(
            """SELECT SUM(
                input_cost_usd + output_cost_usd +
                COALESCE(cache_read_cost_usd, 0) +
                COALESCE(cache_creation_cost_usd, 0)
            ) as total FROM llm_calls"""
        )
        return row["total"] if row and row["total"] else 0.0

    def link_trades(self, call_id: str, trade_ids: list) -> None:
        """Link trade IDs back to the LLM call that generated them."""
        trade_ids_str = ",".join(str(tid) for tid in trade_ids)
        self.db.execute(
            "UPDATE llm_calls SET trade_ids = ? WHERE call_id = ?",
            (trade_ids_str, call_id),
        )
