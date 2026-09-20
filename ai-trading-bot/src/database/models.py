"""
Dataclass models representing database rows.
Python-side representations of DB tables.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Trade:
    """A single trade record."""
    id: Optional[int] = None
    timestamp: str = ""
    symbol: str = ""
    exchange: str = ""
    transaction_type: str = ""  # BUY or SELL
    quantity: int = 0
    price: float = 0.0
    product: str = ""  # CNC or MIS
    order_type: str = ""  # LIMIT, MARKET, SL
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    confidence: Optional[float] = None
    timeframe: str = ""  # INTRADAY or SWING
    max_hold_days: Optional[int] = None
    reasoning: str = ""
    order_id: str = ""
    status: str = ""  # PLACED, FILLED, REJECTED, CANCELLED
    fill_price: Optional[float] = None
    fill_timestamp: Optional[str] = None
    mode: str = ""  # PAPER or LIVE (NEVER exposed to Claude)
    claude_session_id: str = ""


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state."""
    id: Optional[int] = None
    timestamp: str = ""
    total_value: float = 0.0
    cash_available: float = 0.0
    deployed: float = 0.0
    daily_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    holdings_json: str = ""
    positions_json: str = ""


@dataclass
class GuardrailResult:
    """Result of a guardrail validation check."""
    id: Optional[int] = None
    timestamp: str = ""
    trade_id: Optional[int] = None
    llm_call_id: str = ""
    is_valid: bool = True
    errors_json: str = "[]"
    warnings_json: str = "[]"


@dataclass
class DailySummary:
    """End-of-day summary."""
    id: Optional[int] = None
    date: str = ""
    day_number: int = 0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    cumulative_pnl: float = 0.0
    portfolio_value: float = 0.0
    market_bias: str = ""
    notes: str = ""
    llm_cost_usd: float = 0.0
    llm_calls_count: int = 0


@dataclass
class LLMCallRecord:
    """Complete record of a single LLM API call."""
    # Identity
    call_id: str = ""
    session_id: str = ""
    parent_call_id: Optional[str] = None

    # Timing
    timestamp: str = ""
    date: str = ""
    day_number: int = 0
    response_timestamp: str = ""
    latency_ms: int = 0

    # Model & type
    model: str = ""
    call_type: str = ""
    call_subtype: Optional[str] = None

    # Tokens
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_tokens: int = 0

    # Cost (USD)
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    cache_read_cost_usd: float = 0.0
    cache_creation_cost_usd: float = 0.0
    total_cost_usd: float = 0.0

    # File paths
    system_prompt_file: Optional[str] = None
    user_prompt_file: str = ""
    response_file: str = ""
    parsed_output_file: Optional[str] = None

    # Response metadata
    status: str = "SUCCESS"
    error_message: Optional[str] = None
    http_status_code: Optional[int] = None
    stop_reason: Optional[str] = None

    # Decision metadata
    market_bias: Optional[str] = None
    decisions_count: int = 0
    watchlist_symbols: Optional[str] = None
    actions_summary: Optional[str] = None
    trade_ids: Optional[str] = None


@dataclass
class PaperHolding:
    """Paper trading holding."""
    symbol: str = ""
    exchange: str = ""
    quantity: int = 0
    avg_price: float = 0.0
    product: str = "CNC"


@dataclass
class PaperPosition:
    """Paper trading open position."""
    symbol: str = ""
    exchange: str = ""
    quantity: int = 0
    entry_price: float = 0.0
    side: str = ""  # BUY or SELL
    product: str = ""
    entry_timestamp: str = ""
