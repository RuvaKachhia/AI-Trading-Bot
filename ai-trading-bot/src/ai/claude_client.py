"""
Claude API Client.
Wraps the Anthropic SDK with prompt caching, circuit breaker, and logging.
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

import anthropic

from src.ai.system_prompt import build_system_prompt
from src.ai.llm_logger import LLMInteractionLogger

logger = logging.getLogger(__name__)


class ClaudeCircuitBreaker:
    """
    Tracks Claude API health and triggers safe mode if unreachable.
    """

    # A streak that has seen no new failure for longer than this is treated as
    # stale and reset on the next failure — so yesterday's EOD failure does not
    # combine with tomorrow's premarket failure into a spurious multi-hour streak.
    _STALE_STREAK_MINUTES = 60

    def __init__(self, config: dict, notifier=None):
        self.timeout_minutes = config.get("resilience", {}).get(
            "claude_safe_mode_timeout_min", 15
        )
        self.last_successful_call = datetime.now()
        self.first_failure_at = None
        self.in_safe_mode = False
        self.notifier = notifier

    def record_success(self):
        """Called after every successful Claude API response. Clears any
        in-progress failure streak so safe mode only cares about *sustained*
        outages, not old isolated blips."""
        self.last_successful_call = datetime.now()
        self.first_failure_at = None
        if self.in_safe_mode:
            self.in_safe_mode = False
            if self.notifier:
                self.notifier.send_message(
                    "Claude API recovered. Exiting safe mode."
                )

    def record_failure(self, error):
        """Safe mode trips only when failures have been sustained for
        timeout_minutes, measured from the *first failure of the current streak*.
        Idle time (overnight, cycle gaps) never contributes to the streak."""
        now = datetime.now()
        if (
            self.first_failure_at is not None
            and (now - self.first_failure_at).total_seconds() / 60
            > self._STALE_STREAK_MINUTES
        ):
            self.first_failure_at = None
        if self.first_failure_at is None:
            self.first_failure_at = now
        streak_duration = (now - self.first_failure_at).total_seconds() / 60
        if streak_duration >= self.timeout_minutes and not self.in_safe_mode:
            self.in_safe_mode = True
            if self.notifier:
                self.notifier.send_safe_mode_alert(
                    f"Claude API failing for {streak_duration:.0f} min. "
                    f"SAFE MODE activated. No new trades."
                )

    def is_safe_mode(self) -> bool:
        """Check before making any new trade decisions. The flag is only set by
        sustained failures via record_failure, and cleared by record_success —
        idle time does not trip safe mode."""
        return self.in_safe_mode


class ClaudeClient:
    """
    Unified client for all Claude API calls.
    Handles Haiku (news), Sonnet (pulse), and Opus (decisions).
    """

    def __init__(
        self,
        config: dict,
        llm_logger: LLMInteractionLogger,
        notifier=None,
        session_id: str = None,
    ):
        self.config = config
        self.llm_logger = llm_logger
        self.notifier = notifier
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        # Models
        ai_config = config.get("ai", {})
        self.decision_model = ai_config.get("decision_model", "claude-opus-4-7")
        self.analysis_model = ai_config.get("analysis_model", "claude-sonnet-4-6")
        self.news_model = ai_config.get("news_model", "claude-haiku-4-5-20251001")
        self.enable_caching = ai_config.get("enable_prompt_caching", True)

        # Initialize Anthropic client
        api_key = config.get("anthropic", {}).get("api_key", "")
        if api_key.startswith("${"):
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        self.client = anthropic.Anthropic(api_key=api_key)

        # Render system prompt once with current config; stable string => cache hits.
        self._system_prompt = build_system_prompt(config)

        # Circuit breaker
        self.circuit_breaker = ClaudeCircuitBreaker(config, notifier)

    def call_market_pulse(
        self, user_prompt: str, parent_call_id: str = None
    ) -> Optional[dict]:
        """
        Send Market Pulse prompt to Sonnet. Returns parsed watchlist response.
        """
        return self._call(
            model=self.analysis_model,
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            call_type="MARKET_PULSE",
            parent_call_id=parent_call_id,
            max_tokens=4000,
        )

    def call_trading_decision(
        self, user_prompt: str, parent_call_id: str = None
    ) -> Optional[dict]:
        """
        Send Trading Decision prompt to Opus. Returns parsed decision response.
        """
        return self._call(
            model=self.decision_model,
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            call_type="TRADING_DECISION",
            parent_call_id=parent_call_id,
            max_tokens=16000,
        )

    def call_eod_review(
        self, user_prompt: str, parent_call_id: str = None
    ) -> Optional[dict]:
        """Send end-of-day review prompt to Opus."""
        return self._call(
            model=self.decision_model,
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            call_type="EOD_REVIEW",
            parent_call_id=parent_call_id,
            max_tokens=6000,
        )

    def call_haiku(
        self, prompt: str, call_type: str = "NEWS_SUMMARY"
    ) -> Optional[dict]:
        """
        Send a lightweight prompt to Haiku for news summarization etc.
        """
        return self._call(
            model=self.news_model,
            system_prompt="You are a concise financial news assistant. Respond only with valid JSON.",
            user_prompt=prompt,
            call_type=call_type,
            max_tokens=1000,
        )

    def _call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        call_type: str,
        parent_call_id: str = None,
        max_tokens: int = 4000,
    ) -> Optional[dict]:
        """
        Core API call with logging, caching, and circuit breaker.
        Returns parsed JSON response or None on failure.
        """
        call_id = self.llm_logger.generate_call_id(call_type)

        # Save prompts to files (call_type enables date-based dir layout)
        sys_file, user_file = self.llm_logger.save_prompt(
            call_id, system_prompt, user_prompt, call_type=call_type
        )

        start_time = time.time()

        try:
            # Build messages
            system_content = self._build_system_content(system_prompt)

            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_content,
                messages=[{"role": "user", "content": user_prompt}],
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Extract text content
            text_content = ""
            for block in response.content:
                if block.type == "text":
                    text_content += block.text

            # Build response dict for logging
            response_dict = {
                "id": response.id,
                "model": response.model,
                "stop_reason": response.stop_reason,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cache_read_input_tokens": getattr(
                        response.usage, "cache_read_input_tokens", 0
                    ),
                    "cache_creation_input_tokens": getattr(
                        response.usage, "cache_creation_input_tokens", 0
                    ),
                },
                "content": text_content,
            }

            # Save response to file
            resp_file = self.llm_logger.save_response(call_id, response_dict)

            # Parse JSON from Claude's response
            parsed = self._parse_json_response(text_content)

            # Extract metadata for logging
            watchlist_symbols = None
            decisions_count = 0
            market_bias = None
            actions_summary = None

            if parsed:
                if call_type == "MARKET_PULSE":
                    wl = parsed.get("watchlist", [])
                    watchlist_symbols = ",".join(
                        w.get("symbol", "") for w in wl
                    )
                elif call_type == "TRADING_DECISION":
                    decisions = parsed.get("decisions", [])
                    decisions_count = len(decisions)
                    market_bias = parsed.get("market_assessment", {}).get("bias")
                    actions = [
                        f"{d.get('action', '')} {d.get('symbol', '')}"
                        for d in decisions
                    ]
                    actions_summary = "; ".join(actions) if actions else None

            # Log the call
            self.llm_logger.log_call(
                call_id=call_id,
                session_id=self.session_id,
                model=model,
                call_type=call_type,
                response=response_dict,
                latency_ms=latency_ms,
                prompt_file=user_file,
                response_file=resp_file,
                system_prompt_file=sys_file,
                parent_call_id=parent_call_id,
                market_bias=market_bias,
                decisions_count=decisions_count,
                watchlist_symbols=watchlist_symbols,
                actions_summary=actions_summary,
            )

            self.circuit_breaker.record_success()
            return parsed

        except anthropic.RateLimitError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            resp_file = self.llm_logger.save_error_response(call_id, e, 429)
            self.llm_logger.log_failed_call(
                call_id=call_id,
                session_id=self.session_id,
                model=model,
                call_type=call_type,
                error=e,
                prompt_file=user_file,
                response_file=resp_file,
                latency_ms=latency_ms,
                http_status_code=429,
            )
            self.circuit_breaker.record_failure(e)
            logger.error(f"Rate limited on {call_type}: {e}")
            return None

        except anthropic.APIError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            status_code = getattr(e, "status_code", None)
            resp_file = self.llm_logger.save_error_response(call_id, e, status_code)
            self.llm_logger.log_failed_call(
                call_id=call_id,
                session_id=self.session_id,
                model=model,
                call_type=call_type,
                error=e,
                prompt_file=user_file,
                response_file=resp_file,
                latency_ms=latency_ms,
                http_status_code=status_code,
            )
            self.circuit_breaker.record_failure(e)
            logger.error(f"API error on {call_type}: {e}")
            return None

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            resp_file = self.llm_logger.save_error_response(call_id, e)
            self.llm_logger.log_failed_call(
                call_id=call_id,
                session_id=self.session_id,
                model=model,
                call_type=call_type,
                error=e,
                prompt_file=user_file,
                response_file=resp_file,
                latency_ms=latency_ms,
            )
            self.circuit_breaker.record_failure(e)
            logger.error(f"Unexpected error on {call_type}: {e}")
            return None

    def _build_system_content(self, system_prompt: str):
        """
        Build system content with prompt caching if enabled.
        The system prompt is static and cacheable across calls.
        """
        if self.enable_caching:
            return [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        return system_prompt

    def _parse_json_response(self, text: str) -> Optional[dict]:
        """
        Parse JSON from Claude's response text.
        Handles cases where JSON may be wrapped in code blocks.
        """
        if not text:
            return None

        # Try direct parse
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from code block
        if "```json" in text:
            try:
                start = text.index("```json") + 7
                end = text.index("```", start)
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

        if "```" in text:
            try:
                start = text.index("```") + 3
                end = text.index("```", start)
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # Try finding JSON object/array boundaries
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            first = text.find(start_char)
            last = text.rfind(end_char)
            if first != -1 and last != -1 and last > first:
                try:
                    return json.loads(text[first:last + 1])
                except json.JSONDecodeError:
                    pass

        logger.warning(f"Failed to parse JSON from Claude response: {text[:200]}")
        return None
