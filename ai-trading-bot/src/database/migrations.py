"""
Database schema creation and migrations.
Idempotent — safe to run multiple times.
"""

import logging

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- ═══════════════════════════════════════════════════════════
-- TRADE LOG
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    product TEXT NOT NULL,
    order_type TEXT NOT NULL,
    stop_loss REAL,
    target REAL,
    confidence REAL,
    timeframe TEXT,
    max_hold_days INTEGER,
    reasoning TEXT,
    order_id TEXT,
    status TEXT,
    fill_price REAL,
    fill_timestamp DATETIME,
    mode TEXT NOT NULL,
    claude_session_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(DATE(timestamp));

-- ═══════════════════════════════════════════════════════════
-- PORTFOLIO SNAPSHOTS
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    total_value REAL NOT NULL,
    cash_available REAL NOT NULL,
    deployed REAL NOT NULL,
    daily_pnl REAL NOT NULL,
    cumulative_pnl REAL NOT NULL,
    holdings_json TEXT,
    positions_json TEXT,
    mode TEXT NOT NULL DEFAULT 'PAPER'
);

-- ═══════════════════════════════════════════════════════════
-- LLM INTERACTION AUDIT TABLE
-- Every single LLM call goes here.
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity
    call_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    parent_call_id TEXT,

    -- Timing
    timestamp DATETIME NOT NULL,
    date DATE NOT NULL,
    day_number INTEGER NOT NULL,
    response_timestamp DATETIME,
    latency_ms INTEGER,

    -- Model & call type
    model TEXT NOT NULL,
    call_type TEXT NOT NULL,
    call_subtype TEXT,

    -- Token accounting
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,

    -- Cost calculation (USD)
    input_cost_usd REAL NOT NULL DEFAULT 0,
    output_cost_usd REAL NOT NULL DEFAULT 0,
    cache_read_cost_usd REAL DEFAULT 0,
    cache_creation_cost_usd REAL DEFAULT 0,

    -- File references
    system_prompt_file TEXT,
    user_prompt_file TEXT NOT NULL,
    response_file TEXT NOT NULL,
    parsed_output_file TEXT,

    -- Response metadata
    status TEXT NOT NULL DEFAULT 'SUCCESS',
    error_message TEXT,
    http_status_code INTEGER,
    stop_reason TEXT,

    -- Decision metadata
    market_bias TEXT,
    decisions_count INTEGER DEFAULT 0,
    watchlist_symbols TEXT,
    actions_summary TEXT,
    trade_ids TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_date ON llm_calls(date);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_call_type ON llm_calls(call_type);
CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_parent ON llm_calls(parent_call_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_status ON llm_calls(status);

-- ═══════════════════════════════════════════════════════════
-- LLM DAILY COST SUMMARY
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS llm_daily_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    day_number INTEGER NOT NULL,

    -- Per-model breakdown
    haiku_calls INTEGER DEFAULT 0,
    haiku_input_tokens INTEGER DEFAULT 0,
    haiku_output_tokens INTEGER DEFAULT 0,
    haiku_cost_usd REAL DEFAULT 0,

    sonnet_calls INTEGER DEFAULT 0,
    sonnet_input_tokens INTEGER DEFAULT 0,
    sonnet_output_tokens INTEGER DEFAULT 0,
    sonnet_cost_usd REAL DEFAULT 0,

    opus_calls INTEGER DEFAULT 0,
    opus_input_tokens INTEGER DEFAULT 0,
    opus_output_tokens INTEGER DEFAULT 0,
    opus_cost_usd REAL DEFAULT 0,

    -- Per call-type breakdown
    news_calls INTEGER DEFAULT 0,
    news_cost_usd REAL DEFAULT 0,
    pulse_calls INTEGER DEFAULT 0,
    pulse_cost_usd REAL DEFAULT 0,
    decision_calls INTEGER DEFAULT 0,
    decision_cost_usd REAL DEFAULT 0,
    eod_calls INTEGER DEFAULT 0,
    eod_cost_usd REAL DEFAULT 0,
    premarket_calls INTEGER DEFAULT 0,
    premarket_cost_usd REAL DEFAULT 0,
    retry_calls INTEGER DEFAULT 0,
    retry_cost_usd REAL DEFAULT 0,

    -- Totals
    total_calls INTEGER DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0,

    -- Cache efficiency
    total_cache_read_tokens INTEGER DEFAULT 0,
    cache_savings_usd REAL DEFAULT 0,

    -- Error tracking
    failed_calls INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,

    -- Context: trading P&L vs AI cost
    trading_pnl_inr REAL,
    cost_to_pnl_ratio REAL,

    -- Cumulative
    cumulative_cost_usd REAL DEFAULT 0,
    cumulative_tokens INTEGER DEFAULT 0,

    UNIQUE(date)
);

-- ═══════════════════════════════════════════════════════════
-- GUARDRAIL LOG
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS guardrail_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    trade_id INTEGER,
    llm_call_id TEXT,
    is_valid BOOLEAN NOT NULL,
    errors_json TEXT,
    warnings_json TEXT
);

-- ═══════════════════════════════════════════════════════════
-- DAILY SUMMARIES
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    day_number INTEGER NOT NULL,
    trades_count INTEGER,
    wins INTEGER,
    losses INTEGER,
    total_pnl REAL,
    cumulative_pnl REAL,
    portfolio_value REAL,
    market_bias TEXT,
    notes TEXT,
    llm_cost_usd REAL,
    llm_calls_count INTEGER,
    mode TEXT NOT NULL DEFAULT 'PAPER',
    UNIQUE(date, mode)
);

-- ═══════════════════════════════════════════════════════════
-- PAPER TRADING TABLES
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS paper_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    avg_price REAL NOT NULL DEFAULT 0,
    product TEXT NOT NULL DEFAULT 'CNC',
    UNIQUE(symbol, exchange)
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    side TEXT NOT NULL,
    product TEXT NOT NULL,
    entry_timestamp DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL,
    trigger_price REAL,
    product TEXT NOT NULL,
    order_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    fill_price REAL,
    fill_timestamp DATETIME,
    tag TEXT,
    placed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_cash (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    balance REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_reserved_cash (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    amount REAL NOT NULL
);

-- ═══════════════════════════════════════════════════════════
-- POSITION TRACKING (SL, target, hold days)
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS position_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target REAL NOT NULL,
    product TEXT NOT NULL,
    side TEXT NOT NULL,
    max_hold_days INTEGER,
    entry_date DATE NOT NULL,
    sl_order_id TEXT,
    target_order_id TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    mode TEXT NOT NULL DEFAULT 'PAPER',
    UNIQUE(symbol, exchange, status, mode)
);

-- ═══════════════════════════════════════════════════════════
-- WATCHLIST HISTORY
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS watchlist_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    session_id TEXT,
    symbols TEXT NOT NULL,
    reasons_json TEXT,
    mode TEXT NOT NULL DEFAULT 'PAPER'
);

-- ═══════════════════════════════════════════════════════════
-- AGENT RUNS
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    exit_code INTEGER,
    duration_seconds REAL,
    output_summary TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    error_message TEXT
);

-- ═══════════════════════════════════════════════════════════
-- CONVENIENCE VIEWS
-- ═══════════════════════════════════════════════════════════

-- View: Quick cost-per-call analysis
CREATE VIEW IF NOT EXISTS v_llm_cost_analysis AS
SELECT
    call_id,
    date,
    day_number,
    model,
    call_type,
    call_subtype,
    input_tokens,
    output_tokens,
    cache_read_tokens,
    (input_tokens + output_tokens) AS total_tokens,
    (input_cost_usd + output_cost_usd + COALESCE(cache_read_cost_usd, 0)
     + COALESCE(cache_creation_cost_usd, 0)) AS total_cost_usd,
    latency_ms,
    status,
    decisions_count,
    watchlist_symbols,
    actions_summary,
    user_prompt_file,
    response_file,
    CASE
        WHEN model LIKE '%opus%' THEN 'Opus'
        WHEN model LIKE '%sonnet%' THEN 'Sonnet'
        WHEN model LIKE '%haiku%' THEN 'Haiku'
        ELSE model
    END AS model_short,
    CASE WHEN (input_tokens + output_tokens) > 0
        THEN ROUND(
            (input_cost_usd + output_cost_usd + COALESCE(cache_read_cost_usd, 0)
             + COALESCE(cache_creation_cost_usd, 0))
            / ((input_tokens + output_tokens) / 1000.0), 4)
        ELSE 0
    END AS cost_per_1k_tokens
FROM llm_calls
ORDER BY timestamp DESC;

-- View: Session trace (follow one decision cycle)
CREATE VIEW IF NOT EXISTS v_session_trace AS
SELECT
    session_id,
    call_id,
    parent_call_id,
    call_type,
    model,
    timestamp,
    latency_ms,
    input_tokens,
    output_tokens,
    (input_cost_usd + output_cost_usd + COALESCE(cache_read_cost_usd, 0)
     + COALESCE(cache_creation_cost_usd, 0)) AS total_cost_usd,
    status,
    watchlist_symbols,
    actions_summary,
    decisions_count,
    user_prompt_file,
    response_file
FROM llm_calls
ORDER BY session_id, timestamp;
"""


def run_migrations(db) -> None:
    """Run all schema migrations. Idempotent."""
    logger.info("Running database migrations...")

    # Split and execute each statement separately
    statements = [s.strip() for s in SCHEMA_SQL.split(";") if s.strip()]
    for statement in statements:
        # Skip empty or comment-only statements
        lines = [l for l in statement.split("\n") if l.strip() and not l.strip().startswith("--")]
        if not lines:
            continue
        try:
            db.execute(statement)
        except Exception as e:
            logger.error(f"Migration error: {e}\nStatement: {statement[:200]}")
            raise

    # Incremental migrations: add columns that may not exist yet
    _run_alter_migrations(db)

    logger.info("Database migrations complete.")


def _run_alter_migrations(db) -> None:
    """Add columns to existing tables. Each ALTER is idempotent (ignore if exists)."""
    # Simple column additions (safe to re-run — errors ignored if column exists)
    alter_statements = [
        "ALTER TABLE paper_positions ADD COLUMN stop_loss REAL DEFAULT 0",
        "ALTER TABLE paper_positions ADD COLUMN target REAL DEFAULT 0",
        "ALTER TABLE portfolio_snapshots ADD COLUMN mode TEXT NOT NULL DEFAULT 'PAPER'",
        "ALTER TABLE watchlist_history ADD COLUMN mode TEXT NOT NULL DEFAULT 'PAPER'",
        "ALTER TABLE trades ADD COLUMN pnl REAL",
    ]
    for stmt in alter_statements:
        try:
            db.execute(stmt)
        except Exception:
            pass  # Column already exists

    # Rebuild tables that need UNIQUE constraint changes
    _rebuild_daily_summaries(db)
    _rebuild_position_tracking(db)


def _rebuild_daily_summaries(db) -> None:
    """Rebuild daily_summaries with UNIQUE(date, mode) instead of UNIQUE(date)."""
    # Check if mode column already exists
    try:
        db.fetchone("SELECT mode FROM daily_summaries LIMIT 1")
        return  # Already migrated
    except Exception:
        pass  # Column doesn't exist — proceed with rebuild

    try:
        db.execute("ALTER TABLE daily_summaries RENAME TO _daily_summaries_old")
        db.execute("""
            CREATE TABLE daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                day_number INTEGER NOT NULL,
                trades_count INTEGER,
                wins INTEGER,
                losses INTEGER,
                total_pnl REAL,
                cumulative_pnl REAL,
                portfolio_value REAL,
                market_bias TEXT,
                notes TEXT,
                llm_cost_usd REAL,
                llm_calls_count INTEGER,
                mode TEXT NOT NULL DEFAULT 'PAPER',
                UNIQUE(date, mode)
            )
        """)
        db.execute("""
            INSERT INTO daily_summaries
                (date, day_number, trades_count, wins, losses, total_pnl,
                 cumulative_pnl, portfolio_value, market_bias, notes,
                 llm_cost_usd, llm_calls_count, mode)
            SELECT date, day_number, trades_count, wins, losses, total_pnl,
                   cumulative_pnl, portfolio_value, market_bias, notes,
                   llm_cost_usd, llm_calls_count, 'PAPER'
            FROM _daily_summaries_old
        """)
        db.execute("DROP TABLE _daily_summaries_old")
        logger.info("Rebuilt daily_summaries with UNIQUE(date, mode)")
    except Exception as e:
        logger.warning(f"daily_summaries rebuild skipped: {e}")


def _rebuild_position_tracking(db) -> None:
    """Rebuild position_tracking with UNIQUE(symbol, exchange, status, mode)."""
    try:
        db.fetchone("SELECT mode FROM position_tracking LIMIT 1")
        return  # Already migrated
    except Exception:
        pass

    try:
        db.execute("ALTER TABLE position_tracking RENAME TO _position_tracking_old")
        db.execute("""
            CREATE TABLE position_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                target REAL NOT NULL,
                product TEXT NOT NULL,
                side TEXT NOT NULL,
                max_hold_days INTEGER,
                entry_date DATE NOT NULL,
                sl_order_id TEXT,
                target_order_id TEXT,
                status TEXT NOT NULL DEFAULT 'OPEN',
                mode TEXT NOT NULL DEFAULT 'PAPER',
                UNIQUE(symbol, exchange, status, mode)
            )
        """)
        db.execute("""
            INSERT INTO position_tracking
                (symbol, exchange, entry_price, stop_loss, target, product,
                 side, max_hold_days, entry_date, sl_order_id, target_order_id,
                 status, mode)
            SELECT symbol, exchange, entry_price, stop_loss, target, product,
                   side, max_hold_days, entry_date, sl_order_id, target_order_id,
                   status, 'PAPER'
            FROM _position_tracking_old
        """)
        db.execute("DROP TABLE _position_tracking_old")
        logger.info("Rebuilt position_tracking with UNIQUE(symbol, exchange, status, mode)")
    except Exception as e:
        logger.warning(f"position_tracking rebuild skipped: {e}")


def initialize_paper_cash(db, starting_capital: float) -> None:
    """Initialize paper cash balance if not already set."""
    row = db.fetchone("SELECT balance FROM paper_cash WHERE id = 1")
    if row is None:
        db.execute(
            "INSERT INTO paper_cash (id, balance) VALUES (1, ?)",
            (starting_capital,),
        )
        logger.info(f"Paper cash initialized: {starting_capital}")
    else:
        logger.info(f"Paper cash already exists: {row['balance']}")
