# Product Requirements Document (PRD)

## AI Trading Bot for Indian Equity Markets

**Version**: 1.0
**Status**: Implementation Complete (Paper Trading Ready)
**Target Market**: NSE/BSE Equities (Cash segment)

---

## 1. Product Overview

An autonomous trading bot that uses Claude AI (Anthropic) to make equity trading decisions on Indian markets via Zerodha Kite Connect. The bot operates on a 30-day experiment cycle, starting with INR 1,00,000 in capital, making intraday (MIS) and delivery (CNC) trades based on technical analysis, market data, news sentiment, and macro conditions.

### Core Principle

Claude makes trading decisions, but **deterministic guardrails** validate every order before execution. The AI suggests; the code enforces safety.

---

## 2. Goals and Success Criteria

### Primary Goals
- Demonstrate AI-driven trading on Indian equities with real market data
- Maintain strict risk management through hard-coded guardrails
- Track and analyze every decision, trade, and cost
- Support seamless switching between paper and live trading

### Success Metrics
- Win rate > 50%
- Profit factor > 1.5
- Maximum drawdown < 15%
- Daily LLM cost < INR 500
- Zero guardrail bypass incidents

---

## 3. Functional Requirements

### 3.1 Two-Stage AI Pipeline

**Stage 1 — Market Pulse (Sonnet)**
- Runs every 30 minutes during market hours (9:00-14:59 IST)
- Receives: Market-wide data (indices, sector heatmap, top movers, gap opens, ETF snapshot, news headlines, macro data, portfolio state)
- Returns: Watchlist of 3-15 stocks with reasons, market read, and bias (BULLISH/BEARISH/NEUTRAL)
- Currently held stocks are always included in the watchlist

**Stage 2 — Trading Decision (Opus)**
- Runs after each Market Pulse
- Receives: Deep-dive data packs for watchlisted stocks (15-day OHLC, 20+ indicators, support/resistance levels, candlestick patterns, volume analysis)
- Returns: Per-stock decisions (BUY/SELL/CLOSE/HOLD/NO_ACTION) with price, SL, target, confidence, reasoning
- Batch-splits large watchlists to stay within token limits

### 3.2 Order Validation (Guardrails)

Every AI decision passes through 15+ hard-coded checks:

| Rule | Description |
|------|-------------|
| Max Position Size | No single stock > 20% of portfolio |
| Max Deployment | Total deployed < 80% (20% cash buffer) |
| Daily Loss Limit | Stop trading if daily loss > 3% |
| Drawdown Reduction | Reduce sizes at 10% drawdown |
| Drawdown Halt | Stop all trading at 15% drawdown |
| SL Range | Stop-loss must be 0.5%-5% from entry |
| Min Risk-Reward | Minimum 1.5:1 reward-to-risk ratio |
| Max Daily Trades | No more than 12 trades per day |
| No MIS After 2:30 | No new intraday positions after 14:30 |
| Min Stock Price | Stocks must trade above INR 20 |
| Min Volume | Minimum INR 1Cr daily volume |
| Duplicate Check | No duplicate orders within 5 minutes |
| Exchange Validation | Only NSE/BSE allowed |
| Product Validation | Only CNC/MIS products |
| Confidence Threshold | Minimum 50% confidence required |
| Max CNC Hold | CNC positions auto-close after 15 days |

### 3.3 Paper Trading

- Real market data from Kite, simulated execution
- OHLC-based fill simulation: 5-minute candles checked for SL/target/limit price touches
- Separate database tables for paper state (holdings, positions, orders, cash)
- Reserved cash system for pending BUY orders
- Claude never knows whether mode is PAPER or LIVE

### 3.4 Live Trading

- Real orders through Kite Connect API
- Same guardrail validation as paper mode
- Order reconciliation via Kite order status polling
- Telegram notifications for all trade events

### 3.5 MIS Auto-Exit

Intraday positions must close before market close. Four independent stages:

| Stage | Time | Action |
|-------|------|--------|
| 1 | 15:00 | Graceful LIMIT exit at best bid/ask |
| 2 | 15:05 | Retry unfilled positions |
| 3 | 15:10 | Force MARKET order close |
| 4 | 15:12 | Emergency verification — alert if any remain |

### 3.6 SL Health Check

- Runs every 5 minutes during market hours
- Uses OHLC candle data (not just LTP) for accurate SL/target monitoring
- Checks if candle low breached SL (longs) or candle high breached SL (shorts)
- SL has priority over target when both trigger in same candle (conservative)
- Falls back to LTP if candle data unavailable

### 3.7 Dashboard

Streamlit-based monitoring dashboard with tabs:

| Tab | Content |
|-----|---------|
| Portfolio | Value chart, cash deployed, daily P&L |
| Trades | Full trade log with filters |
| Performance | Win rate, profit factor, cumulative P&L chart |
| Guardrails | Validation history, block rate |
| LLM Costs | Per-model cost breakdown, token usage, cache efficiency |
| Details | Paper state (holdings, positions, orders), position tracking |

**Mode Selector**: PAPER / LIVE / Both radio button in sidebar. Every query filters by selected mode (except LLM costs which are mode-agnostic).

### 3.8 Notifications

Telegram bot sends:
- Trade execution alerts
- Guardrail blocks
- Safe mode entry/exit
- EOD daily summary
- Error alerts

### 3.9 Data Persistence

- **SQLite (WAL mode)**: Thread-safe, 13 tables, 2 views
- **CSV audit trail**: Immutable logs for trades, guardrails, P&L
- **Prompt/response files**: Full LLM conversation logs saved to disk
- **Daily backups**: DB + config + logs archived at 4:00 PM

---

## 4. Non-Functional Requirements

### 4.1 Performance
- Market Pulse cycle < 60 seconds (including API calls)
- Kite API rate limit respected (3 req/sec quotes, 1 req/sec historical)
- Candle cache with 5-minute TTL to avoid redundant API calls

### 4.2 Reliability
- Circuit breaker: If Claude API is unreachable for 15 minutes, enter safe mode (no new trades, existing SL/targets still monitored)
- Idempotent migrations: Safe to run multiple times
- Graceful shutdown on SIGINT/SIGTERM

### 4.3 Security
- API keys stored in environment variables (never in config files)
- No secrets committed to git
- Claude never receives mode information (PAPER/LIVE)

### 4.4 Cost Control
- Prompt caching enabled for system prompts
- Haiku used for low-value tasks (news summarization)
- Sonnet for market scanning, Opus only for final trading decisions
- Daily cost tracking with alerts

---

## 5. Data Sources

| Source | Data | Frequency |
|--------|------|-----------|
| Kite Connect | Quotes, OHLC, positions, orders, margins | Real-time |
| Kite Historical | Daily/intraday candles | On demand (cached) |
| RSS Feeds | Market headlines (Moneycontrol, ET, LiveMint) | Pre-market + every pulse |
| yfinance | Global indices (S&P 500, FTSE, Nikkei) | Pre-market |
| Kite Instruments | Full NSE/BSE instrument list | Daily (cached) |

---

## 6. Configuration

All parameters are in `config/config.yaml`:

| Section | Key Parameters |
|---------|---------------|
| `experiment` | start_date, duration_days, starting_capital |
| `trading` | mode, max_position_pct, MIS timings |
| `risk` | daily_loss_limit, drawdown thresholds, SL range |
| `resilience` | circuit breaker timeout, SL check interval |
| `pipeline` | pulse interval, watchlist size limits |
| `ai` | model selection per task, candle count |
| `llm_pricing` | Per-model token costs in INR |

---

## 7. Out of Scope (v1)

- Options/futures trading
- Multi-account support
- Web-based configuration UI
- Backtesting engine
- Mobile app
- Real-time WebSocket streaming (uses polling)
- Automated Kite login renewal (manual TOTP or env var required)

---

## 8. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Claude makes bad trades | 15+ guardrail rules validate every order |
| API outage (Kite) | SL health check continues with cached data; safe mode for Claude outage |
| Excessive LLM costs | Daily cost tracking, Haiku for cheap tasks, prompt caching |
| Data contamination | Paper/live data fully separated by mode column |
| Runaway losses | 3% daily loss limit, 15% drawdown halt |
| MIS positions not closed | 4-stage auto-exit with emergency verification |
