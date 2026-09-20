# Changelog

All implementation phases and changes tracked chronologically.

---

## Phase 1: Foundation

**Scope**: Project scaffolding, database, configuration, logging

### Files Created
- `main.py` — Entry point with `--once`, `--eod`, `--backup` CLI flags
- `config/config.yaml` — Full configuration (experiment, trading, risk, AI, pricing)
- `config/sector_mapping.yaml` — 11 sectors, 120+ NSE stocks with index keys
- `config/etf_list.yaml` — 11 approved ETFs
- `requirements.txt` — 17 dependencies
- `.gitignore` — Python, IDE, env, data exclusions
- `src/database/db.py` — `Database` class: thread-safe SQLite with WAL mode, row factory
- `src/database/migrations.py` — Schema creation (tables, indexes, views), `run_migrations()`
- `src/database/models.py` — Data model definitions

### Database Tables Created
- `trades` — Trade log with mode column
- `portfolio_snapshots` — Point-in-time portfolio state
- `llm_calls` — Complete LLM call audit (49 columns)
- `llm_daily_costs` — Aggregated daily LLM cost summary
- `guardrail_log` — Guardrail validation results
- `daily_summaries` — EOD performance summaries

### Database Views Created
- `v_llm_cost_analysis` — Per-call cost analysis with model categorization
- `v_session_trace` — Follow a complete decision cycle by session_id

---

## Phase 2: Broker + Data Layer

**Scope**: Kite Connect integration, market data, technical analysis

### Files Created
- `src/broker/kite_auth.py` — `KiteAuthManager`: Authentication with TOTP auto-login
- `src/broker/kite_client.py` — `KiteClientWrapper`: Rate-limited Kite API wrapper
- `src/broker/instruments.py` — `InstrumentManager`: Instrument cache and symbol/token lookup
- `src/data/market_data.py` — `MarketDataFetcher`: OHLC candle fetcher from Kite historical API
- `src/data/indicators.py` — `IndicatorEngine`: 20+ technical indicators (RSI, MACD, Bollinger, ADX, ATR, OBV, MFI, Stochastic, etc.)
- `src/data/levels.py` — `LevelCalculator`: Support/resistance, pivot points, VWAP
- `src/data/patterns.py` — `PatternDetector`: Candlestick pattern detection
- `src/data/universe.py` — `UniverseFilter`: Filters stocks by price, volume, exchange

---

## Phase 3: News + AI Pipeline

**Scope**: News aggregation, Claude integration, prompt building

### Files Created
- `src/news/news_fetcher.py` — `NewsFetcher`: RSS feed scraping (Moneycontrol, ET, LiveMint) + Haiku summarization
- `src/news/macro_data.py` — `MacroDataFetcher`: FII/DII flows, global indices, VIX
- `src/ai/system_prompt.py` — Claude's system prompt with trading rules and output format
- `src/ai/claude_client.py` — `ClaudeClient`: Anthropic SDK wrapper + `ClaudeCircuitBreaker` for safe mode
- `src/ai/prompt_formatter.py` — `PromptFormatter`: Builds Market Pulse and Trading Decision prompts
- `src/ai/response_parser.py` — `ResponseParser`: Parses JSON responses + `PromptSizeManager` for batch splitting
- `src/ai/llm_logger.py` — `LLMInteractionLogger`: Token/cost tracking, file saving, daily cost aggregation

---

## Phase 4: Trading Engine

**Scope**: Guardrails, execution, order management, position tracking

### Files Created
- `src/trading/guardrails.py` — `GuardrailEngine`: 15+ validation rules, `ValidationResult` dataclass
- `src/trading/execution_engine.py` — `ExecutionEngine`: Order placement for paper + live modes
- `src/trading/order_reconciler.py` — `OrderReconciler`: Order status reconciliation
- `src/trading/mis_exit.py` — `MISAutoExitEngine`: 4-stage MIS auto-exit
- `src/trading/sl_health_check.py` — `SLHealthCheck`: Stop-loss monitoring
- `src/trading/portfolio_state.py` — `PortfolioStateManager`: Mode-blind portfolio data
- `src/trading/performance.py` — `PerformanceTracker`: Rolling/cumulative metrics
- `src/trading/trade_logger.py` — CSV audit trail loggers

### Database Tables Created
- `paper_holdings` — Paper CNC holdings
- `paper_positions` — Paper MIS positions
- `paper_orders` — Paper order book
- `paper_cash` — Paper cash balance (single-row table)
- `paper_reserved_cash` — Cash reserved for pending BUY orders
- `position_tracking` — Open position SL/target tracking
- `watchlist_history` — Historical watchlist records

---

## Phase 5: Orchestrator

**Scope**: Central coordination, scheduling, boot sequence

### Files Created
- `src/orchestrator.py` — `Orchestrator`: Boot sequence, `_init_components()`, `_init_broker_components()`, `start_scheduler()`, `run_market_pulse_cycle()`, `_validate_and_execute()`, `run_eod_review()`, `run_daily_backup()`
- `src/data/data_warehouse.py` — `DataWarehouse`: Central in-memory data store
- `src/data/market_pulse.py` — `MarketPulseAggregator`: Market-wide data for Sonnet
- `src/data/deep_dive.py` — `DeepDiveAssembler`: Per-stock data packs for Opus

---

## Phase 6: Dashboard

**Scope**: Streamlit monitoring UI

### Files Created
- `dashboard/app.py` — Full Streamlit dashboard with 6 tabs (Portfolio, Trades, Performance, Guardrails, LLM Costs, Details)

---

## Phase 7: Polish + Testing

**Scope**: Test suite, notifications, scripts

### Files Created
- `tests/conftest.py` — Shared pytest fixtures
- `tests/test_imports.py` — Module import verification (all 30+ modules)
- `tests/test_database.py` — Schema, migration, query tests
- `tests/test_guardrails.py` — Guardrail rule validation tests
- `tests/test_response_parser.py` — Claude response parsing tests
- `tests/test_indicators.py` — Technical indicator computation tests
- `tests/test_llm_logger.py` — LLM cost tracking tests
- `src/notifications/telegram_bot.py` — `TelegramNotifier` + `create_notifier()` factory
- `scripts/setup_db.py` — Standalone database initialization script

---

## Post-Phase: OHLC-Based Paper Trading Enhancement

**Scope**: Replace LTP-based fill simulation with OHLC candle-based simulation + fix 12 bugs

### Bug Fixes

| Bug | File | Fix |
|-----|------|-----|
| `paper_cash SET amount` (column is `balance`) | `execution_engine.py` (2 places) | Changed to `SET balance` |
| `paper_cash SET amount` | `sl_health_check.py` | Changed to `SET balance` |
| `paper_cash SET amount` | `mis_exit.py` | Changed to `SET balance` |
| `_update_paper_positions` missing columns | `execution_engine.py` | Added `side`, `entry_timestamp`, `stop_loss`, `target` to INSERT |
| `_save_paper_order` wrong column names | `execution_engine.py` | Fixed `stop_loss,target,timestamp` → `trigger_price,tag` |
| `_get_paper_cash()` wrong query | `portfolio_state.py` | `SELECT COALESCE(SUM(amount),0)` → `SELECT balance FROM paper_cash WHERE id=1` |
| `order.get("stop_loss")` wrong key | `order_reconciler.py` | Changed to `order.get("trigger_price")` |
| `reconcile_paper_sl_targets()` never called | `orchestrator.py` | Added APScheduler job |
| No LIMIT order reconciliation | `order_reconciler.py` | Added `_reconcile_paper_limit_orders()` |
| `MarketDataFetcher` constructor mismatch | `orchestrator.py` | Removed extra `config=` kwarg |

### Schema Changes
- Added `ALTER TABLE paper_positions ADD COLUMN stop_loss REAL DEFAULT 0`
- Added `ALTER TABLE paper_positions ADD COLUMN target REAL DEFAULT 0`

### New Functionality
- `market_data.py`: Added `fetch_recent_candle()` with 5-min TTL cache per symbol
- `sl_health_check.py`: Complete rewrite — uses candle high/low range instead of LTP. `_get_candle_or_ltp()` helper with LTP fallback. SL priority over target
- `order_reconciler.py`: Complete rewrite — two sub-methods: `_reconcile_paper_sl_orders()` (TRIGGER PENDING) and `_reconcile_paper_limit_orders()` (OPEN LIMIT). `_apply_paper_fill()` for paper state updates
- `orchestrator.py`: Wired `market_data` to `SLHealthCheck` and `OrderReconciler`. Added `paper_sl_target_reconcile` scheduler job (every 5 min, paper mode only)

### Tests Added
- `test_paper_positions_has_sl_target_columns` — Verifies ALTER TABLE migration

**Test count: 52 → 53**

---

## Post-Phase: Paper/Live Data Separation

**Scope**: Add `mode` column to shared tables, fix queries, add dashboard mode selector

### Schema Changes
- `portfolio_snapshots`: Added `mode TEXT NOT NULL DEFAULT 'PAPER'`
- `watchlist_history`: Added `mode TEXT NOT NULL DEFAULT 'PAPER'`
- `daily_summaries`: Rebuilt table with `UNIQUE(date, mode)` (was `UNIQUE(date)`)
- `position_tracking`: Rebuilt table with `UNIQUE(symbol, exchange, status, mode)` (was `UNIQUE(symbol, exchange, status)`)

### Migration Strategy
- Simple column additions: `ALTER TABLE ... ADD COLUMN` in try/except (idempotent)
- Constraint changes: Rename-copy-drop pattern (rename → create new → copy data → drop old)
- Guard clause: Check if `mode` column exists before rebuilding

### Query Fixes

| File | Changes |
|------|---------|
| `db.py` | `count_trades_today()` now accepts optional `mode` param |
| `performance.py` | All 4 queries filter `AND mode = ?`. `save_daily_summary()` and `save_portfolio_snapshot()` include mode in INSERT |
| `portfolio_state.py` | `_get_paper_daily_pnl()` filters `AND mode = 'PAPER'`. `trades_today_count()` passes `mode=self._mode` |

### Dashboard Rewrite
- Added PAPER/LIVE/Both radio selector in sidebar
- Every tab filters by selected view mode
- "Both" mode shows combined data with mode column visible
- LLM Costs tab unchanged (mode-agnostic)
- Tab headers show selected mode (e.g., "Portfolio Overview (PAPER)")

### Tests Added
- `TestModeColumns.test_portfolio_snapshots_has_mode`
- `TestModeColumns.test_daily_summaries_has_mode_and_unique_constraint`
- `TestModeColumns.test_position_tracking_has_mode`
- `TestModeColumns.test_watchlist_history_has_mode`
- `TestModeColumns.test_count_trades_today_by_mode`

**Test count: 53 → 58**

---

## Post-Phase: PaperBroker Extraction

**Scope**: Extract all paper trading mutations from 4 files into a single dedicated `PaperBroker` module

### Problem

Paper trading logic was scattered across 4 trading engine files (~770 lines) with significant code duplication:

| Duplication | Files |
|-------------|-------|
| CNC holding CRUD (insert/update/delete) | `execution_engine.py`, `order_reconciler.py` |
| MIS position CRUD (open/close) | `execution_engine.py`, `order_reconciler.py` |
| `_get_candle_or_ltp()` helper | `order_reconciler.py`, `sl_health_check.py` |
| Position close + cash update | `sl_health_check.py`, `mis_exit.py` |

### Files Created
- `src/trading/paper_broker.py` — `PaperBroker` class (~540 lines): All paper trading DB mutations consolidated. Methods: `execute_order()`, `apply_fill()`, `update_holdings()`, `update_positions()`, `close_position()`, `update_cash()`, `save_order()`, `reconcile_sl_orders()`, `reconcile_limit_orders()`, `check_holding_sl_orders()`, `check_position_sl_targets()`, `cancel_pending_mis_orders()`, `record_trade_pnl()`, `get_ltp()`, `get_candle_or_ltp()`. Also `generate_paper_order_id()` standalone function
- `tests/test_paper_broker.py` — 23 tests across 10 test classes

### Files Refactored

| File | Before | After | Change |
|------|--------|-------|--------|
| `execution_engine.py` | ~468 lines | ~175 lines | Removed 6 paper methods, delegates to PaperBroker |
| `order_reconciler.py` | ~449 lines | ~195 lines | Removed 6 paper methods, delegates to PaperBroker |
| `sl_health_check.py` | ~375 lines | ~200 lines | Removed 3 paper methods, delegates to PaperBroker |
| `mis_exit.py` | ~273 lines | ~200 lines | Simplified 2 paper blocks, delegates to PaperBroker |
| `orchestrator.py` | — | — | Creates PaperBroker, injects into 4 engines |

### Schema Changes
- Added `ALTER TABLE trades ADD COLUMN pnl REAL` for `record_trade_pnl()`

### Bug Fixes
- `mis_exit.py`: Fixed cash update formula — old `ltp * qty + pnl - 20` double-counted for longs. Now uses `exit_price * abs(qty) - brokerage` via PaperBroker.close_position()

### Net Impact
- ~770 lines of duplicated paper logic → ~540 lines in one place
- ~400 lines eliminated across the codebase
- 4 code duplications removed
- 1 cash calculation bug fixed

**Test count: 58 → 81**

---

## Test Summary

| Test File | Tests | Covers |
|-----------|-------|--------|
| `test_imports.py` | 1 | All 30+ module imports |
| `test_database.py` | 15 | Schema, migrations, mode columns, paper cash |
| `test_guardrails.py` | 17 | All guardrail rules |
| `test_response_parser.py` | 12 | Market pulse + trading decision parsing |
| `test_indicators.py` | 8 | Technical indicator computation |
| `test_llm_logger.py` | 5 | LLM call logging and cost tracking |
| `test_paper_broker.py` | 23 | Order execution, holdings, positions, cash, reconciliation, candle fallback |
| **Total** | **81** | |
