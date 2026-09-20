# Architecture Guide

## System Design

The bot follows a layered architecture where each layer has clear responsibilities and dependencies flow downward.

```
┌──────────────────────────────────────────────────────────────┐
│                        main.py                                │
│                     (Entry Point)                             │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                     Orchestrator                              │
│              src/orchestrator.py                              │
│  Boot sequence, APScheduler, market pulse cycle, EOD review  │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬────────────────┘
   │      │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼      ▼
Broker  Data   News    AI   Trading  DB    Notify
Layer   Layer  Layer  Layer  Layer  Layer   Layer
```

---

## Layer Details

### 1. Broker Layer (`src/broker/`)

| Module | Class | Responsibility |
|--------|-------|----------------|
| `kite_auth.py` | `KiteAuthManager` | Kite Connect authentication with TOTP auto-login support |
| `kite_client.py` | `KiteClientWrapper` | Rate-limited wrapper around kiteconnect SDK. Adds retry logic and error notifications |
| `instruments.py` | `InstrumentManager` | Downloads and caches NSE/BSE instrument list. Provides symbol-to-token lookup |

### 2. Data Layer (`src/data/`)

| Module | Class | Responsibility |
|--------|-------|----------------|
| `market_data.py` | `MarketDataFetcher` | Fetches OHLC candles (daily + intraday) from Kite. Includes `fetch_recent_candle()` with 5-min TTL cache |
| `indicators.py` | `IndicatorEngine` | Computes 20+ technical indicators via pandas-ta (RSI, MACD, Bollinger, ADX, ATR, OBV, MFI, Stochastic, etc.) |
| `levels.py` | `LevelCalculator` | Support/resistance levels, pivot points, VWAP |
| `patterns.py` | `PatternDetector` | Candlestick pattern detection (doji, hammer, engulfing, etc.) |
| `universe.py` | `UniverseFilter` | Filters tradeable stocks by price, volume, and exchange criteria |
| `data_warehouse.py` | `DataWarehouse` | Central in-memory store. Boots with universe, caches OHLC/indicator/level data for all symbols |
| `market_pulse.py` | `MarketPulseAggregator` | Builds market-wide summary: top movers, gap opens, sector heatmap, ETF snapshot. Input for Sonnet |
| `deep_dive.py` | `DeepDiveAssembler` | Builds per-stock data packs: 15-day OHLC, indicators, levels, patterns, volume analysis. Input for Opus |

**Data Flow:**
```
Kite API → MarketDataFetcher → DataWarehouse
                                    ├── MarketPulseAggregator → Sonnet prompt
                                    └── DeepDiveAssembler → Opus prompt
```

### 3. News Layer (`src/news/`)

| Module | Class | Responsibility |
|--------|-------|----------------|
| `news_fetcher.py` | `NewsFetcher` | Fetches market headlines from RSS feeds (Moneycontrol, Economic Times, LiveMint). Uses Haiku for summarization |
| `macro_data.py` | `MacroDataFetcher` | FII/DII flow data, global index quotes (via yfinance), VIX level |

### 4. AI Layer (`src/ai/`)

| Module | Class | Responsibility |
|--------|-------|----------------|
| `system_prompt.py` | `SYSTEM_PROMPT` | Claude's system prompt: trading rules, position sizing guidelines, risk parameters, output format |
| `claude_client.py` | `ClaudeClient` | Anthropic SDK wrapper. Manages prompt caching, tracks tokens, handles retries. Contains `ClaudeCircuitBreaker` for safe mode |
| `prompt_formatter.py` | `PromptFormatter` | Builds structured user prompts for both stages. Handles Market Pulse format and Trading Decision format |
| `response_parser.py` | `ResponseParser` | Parses Claude's JSON responses. Extracts watchlist (Stage 1) or trading decisions (Stage 2). `PromptSizeManager` splits large watchlists into batches |
| `llm_logger.py` | `LLMInteractionLogger` | Logs every LLM call to `llm_calls` table with full token/cost breakdown. Saves prompt/response files to disk. Rebuilds `llm_daily_costs` aggregation |

**AI Pipeline Flow:**
```
MarketPulseAggregator → PromptFormatter.format_market_pulse()
    → ClaudeClient.call_market_pulse() [Sonnet]
    → ResponseParser.parse_market_pulse()
    → Watchlist (3-15 stocks)

DeepDiveAssembler → PromptFormatter.format_trading_decision()
    → ClaudeClient.call_trading_decision() [Opus]
    → ResponseParser.parse_trading_decision()
    → Decisions [{action, symbol, price, sl, target, confidence}]
```

### 5. Trading Layer (`src/trading/`)

| Module | Class | Responsibility |
|--------|-------|----------------|
| `portfolio_state.py` | `PortfolioStateManager` | **Mode-blind abstraction**. Provides identical data format to prompt builder regardless of PAPER/LIVE. Claude never sees the mode |
| `guardrails.py` | `GuardrailEngine` | Validates every order against 15+ rules. Returns `ValidationResult` with `is_valid`, `errors`, `warnings`, and potentially modified `order` |
| `paper_broker.py` | `PaperBroker` | **Single source of truth** for all paper trading DB mutations. Handles order execution, holding/position CRUD, cash updates, OHLC-based reconciliation, position closure. Used by ExecutionEngine, OrderReconciler, SLHealthCheck, MISAutoExitEngine |
| `execution_engine.py` | `ExecutionEngine` | Places orders via Kite (live) or delegates to PaperBroker (paper). Logs all trades to DB and CSV |
| `order_reconciler.py` | `OrderReconciler` | Live: polls Kite order status. Paper: delegates to PaperBroker for OHLC-based SL/LIMIT fill simulation |
| `sl_health_check.py` | `SLHealthCheck` | Live: verifies broker-side SL/target orders exist. Paper: delegates to PaperBroker for candle-based SL/target monitoring |
| `mis_exit.py` | `MISAutoExitEngine` | 4-stage MIS position closure at 3:00/3:05/3:10/3:12 PM. Each stage is an independent APScheduler job. Paper mode delegates to PaperBroker |
| `performance.py` | `PerformanceTracker` | Computes rolling 5-day and cumulative metrics. All queries filter by mode. Saves daily summaries and portfolio snapshots |
| `trade_logger.py` | `TradeLogger`, `GuardrailLogger`, `PnLLogger` | CSV audit trail writers for trades, guardrail checks, and P&L |

**Order Lifecycle:**
```
Claude Decision
    → GuardrailEngine.validate_order()
    → [if valid] ExecutionEngine.execute_order()
        → [LIVE] Kite API → order_id
        → [PAPER] PaperBroker.execute_order() → paper_orders, paper_holdings/positions, paper_cash
    → OrderReconciler.track_order()
    → [later] OrderReconciler.reconcile() (live)
              or PaperBroker.reconcile_sl_orders() + reconcile_limit_orders() (paper)
```

**PaperBroker Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                      PaperBroker                            │
│            (Single source of truth for paper DB)            │
├─────────────────────────────────────────────────────────────┤
│ execute_order()           Order simulation (MARKET/LIMIT/SL)│
│ apply_fill()              Routes to holdings or positions   │
│ update_holdings()         CNC holding CRUD (avg up/sell)    │
│ update_positions()        MIS position CRUD (open/close)    │
│ close_position()          MIS close + P&L + cash update     │
│ update_cash()             Paper cash balance (debit/credit) │
│ reconcile_sl_orders()     OHLC-based SL fill simulation     │
│ reconcile_limit_orders()  OHLC-based LIMIT fill simulation  │
│ check_holding_sl_orders() Holding SL monitoring via candle  │
│ check_position_sl_targets() Position SL/target monitoring   │
│ cancel_pending_mis_orders() MIS order cleanup               │
│ get_candle_or_ltp()       OHLC candle with LTP fallback     │
├─────────────────────────────────────────────────────────────┤
│ Used by: ExecutionEngine, OrderReconciler,                  │
│          SLHealthCheck, MISAutoExitEngine                   │
└─────────────────────────────────────────────────────────────┘
```

### 6. Database Layer (`src/database/`)

| Module | Class | Responsibility |
|--------|-------|----------------|
| `db.py` | `Database` | Thread-safe SQLite connection manager. WAL mode for concurrent reads. Provides `execute()`, `fetchone()`, `fetchall()`, `transaction()`. Cash reservation helpers |
| `migrations.py` | `run_migrations()` | Creates 13 tables + 2 views. Idempotent ALTER TABLE for column additions. Rename-copy-drop for UNIQUE constraint changes |
| `models.py` | — | Data model definitions |

### 7. Notifications (`src/notifications/`)

| Module | Class | Responsibility |
|--------|-------|----------------|
| `telegram_bot.py` | `TelegramNotifier` | Sends messages via Telegram Bot API. Methods: `send_message()`, `send_daily_summary()`, `send_safe_mode_alert()` |

---

## Database Schema

### Entity-Relationship Overview

```
trades ──────────────────── guardrail_log (trade_id FK)
   │
   └── mode column ─────── daily_summaries.mode
                            portfolio_snapshots.mode
                            position_tracking.mode
                            watchlist_history.mode

llm_calls ──────────────── llm_daily_costs (aggregated)
   │
   └── parent_call_id ──── self-referencing (market_pulse → trading_decision)

paper_holdings ─┐
paper_positions ├── Paper-only state
paper_orders    │
paper_cash ─────┤
paper_reserved_cash ┘
```

### Mode Separation Strategy

| Table Type | Strategy |
|------------|----------|
| Paper-only (`paper_*`) | Dedicated tables, no mode column needed |
| Shared (`trades`, `portfolio_snapshots`, etc.) | `mode TEXT NOT NULL DEFAULT 'PAPER'` column, all queries filter by mode |
| Mode-agnostic (`llm_calls`, `llm_daily_costs`, `guardrail_log`) | No mode column — same AI costs regardless of trading mode |

### Migration Strategy

- **New columns**: `ALTER TABLE ... ADD COLUMN` wrapped in try/except (idempotent)
- **Constraint changes**: Rename-copy-drop pattern:
  1. `ALTER TABLE x RENAME TO _x_old`
  2. `CREATE TABLE x (... new constraints ...)`
  3. `INSERT INTO x SELECT ... FROM _x_old`
  4. `DROP TABLE _x_old`
- **Guard clause**: Check if migration already applied before running

---

## Scheduling Architecture

The Orchestrator uses APScheduler with `BackgroundScheduler` (timezone: Asia/Kolkata).

```
┌─────────────────────────────────────────────────────────┐
│                    APScheduler                          │
├─────────────────────────────────────────────────────────┤
│ market_pulse_cycle    CronTrigger  Mon-Fri */30 9-14    │
│ sl_health_check       CronTrigger  Mon-Fri */5  9-15    │
│ order_reconcile       Interval     60 sec               │
│ paper_sl_target_fill  CronTrigger  Mon-Fri */5  9-15    │  ← Paper only
│ mis_exit_stage_1      CronTrigger  Mon-Fri 15:00        │
│ mis_exit_stage_2      CronTrigger  Mon-Fri 15:05        │
│ mis_exit_stage_3      CronTrigger  Mon-Fri 15:10        │
│ mis_exit_stage_4      CronTrigger  Mon-Fri 15:12        │
│ eod_review            CronTrigger  Mon-Fri 15:40        │
│ daily_backup          CronTrigger  Mon-Fri 16:00        │
└─────────────────────────────────────────────────────────┘
```

---

## OHLC-Based Paper Trading

Instead of checking only the last traded price (LTP), the bot uses 5-minute OHLC candles for realistic fill simulation:

```
Candle: {open: 2500, high: 2520, low: 2480, close: 2510}

For a LONG position with SL=2485, Target=2525:
  - SL check: candle.low (2480) <= SL (2485) → SL HIT
  - Target check: candle.high (2520) < Target (2525) → NOT hit

For a LIMIT BUY at 2490:
  - Fill check: candle.low (2480) <= 2490 → FILLED at 2490
```

**Key design decisions:**
- SL has priority over target when both trigger in the same candle (conservative)
- Second-to-last completed candle is used (the last candle may still be forming)
- 5-minute cache per symbol prevents hitting Kite's 1 req/sec historical data rate limit
- Falls back to synthetic LTP candle (open=high=low=close=LTP) if candle fetch fails

---

## Mode-Blind Architecture

The `PortfolioStateManager` is the only class that knows about PAPER vs LIVE mode. All other components receive normalized data:

```
                    ┌─────────────────────────┐
                    │  PortfolioStateManager   │
                    │                         │
                    │  _mode (internal only)  │
                    │                         │
  PAPER ────────────│ _get_paper_holdings()   │──── get_holdings() ────→ PromptFormatter
                    │ _get_paper_positions()  │──── get_positions() ──→ (same format
  LIVE  ────────────│ _get_live_holdings()    │──── get_available_cash() regardless
                    │ _get_live_positions()   │                         of mode)
                    └─────────────────────────┘
```

Claude receives identical portfolio data in both modes. It cannot determine whether it is paper or live trading.

---

## Error Handling and Resilience

### Circuit Breaker
- `ClaudeCircuitBreaker` tracks time since last successful API call
- After 15 minutes of failures → enters safe mode
- Safe mode: no new trading decisions, but SL health checks continue
- Auto-recovers on next successful call

### Graceful Degradation
- If Kite is not authenticated → runs in offline mode (no trades, data only)
- If news fetch fails → continues without news data
- If macro data fails → continues with empty macro context
- If candle fetch fails → falls back to LTP for SL monitoring

### Data Safety
- WAL mode for concurrent SQLite reads
- Thread-local connections with locks
- Reserved cash prevents over-committing capital on pending orders
- Daily backups at 4:00 PM (DB + config + logs)
