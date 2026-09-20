# AI Trading Bot

An autonomous equity trading bot for Indian markets (NSE/BSE) powered by Claude AI and Zerodha Kite Connect. The bot uses a two-stage AI pipeline — Sonnet for market scanning and Opus for trading decisions — with deterministic guardrails ensuring every order is validated before execution.

## Key Features

- **Two-Stage AI Pipeline**: Sonnet scans the market and builds a watchlist; Opus analyzes deep-dive data and makes trading decisions
- **Mode-Blind Architecture**: Claude never knows if it's paper or live trading — identical data format in both modes
- **Paper Trading with OHLC Simulation**: Realistic fill simulation using 5-minute candle data instead of LTP snapshots
- **15+ Guardrail Rules**: Hard-coded validation (position sizing, drawdown limits, SL range checks, daily loss caps) before every order
- **4-Stage MIS Auto-Exit**: Independent APScheduler jobs at 3:00, 3:05, 3:10, 3:12 PM for systematic intraday position closure
- **Complete Data Separation**: Paper and live trading data stored separately with mode-filtered queries
- **Real-Time Dashboard**: Streamlit dashboard with PAPER/LIVE/Both toggle for monitoring all metrics
- **Comprehensive Logging**: Every LLM call, guardrail check, trade, and portfolio snapshot is logged to SQLite + CSV

## Architecture Overview

```
main.py → Orchestrator
             ├── Broker Layer (Kite Auth, Client, Instruments)
             ├── Data Layer (Market Data, Indicators, Levels, Patterns, Universe)
             │     ├── Market Pulse Aggregator → Sonnet (watchlist)
             │     └── Deep Dive Assembler → Opus (decisions)
             ├── News Layer (RSS feeds, Macro data)
             ├── AI Layer (Claude Client, Prompt Formatter, Response Parser)
             ├── Trading Layer
             │     ├── Portfolio State Manager (mode-blind)
             │     ├── Guardrail Engine (15+ rules)
             │     ├── Paper Broker (all paper trading mutations)
             │     ├── Execution Engine (delegates paper → PaperBroker)
             │     ├── Order Reconciler (OHLC-based fills)
             │     ├── SL Health Check (candle-based monitoring)
             │     ├── MIS Auto-Exit (4-stage)
             │     └── Performance Tracker
             ├── Database (SQLite WAL, 13 tables, 2 views)
             └── Notifications (Telegram)
```

## Project Structure

```
ai-trading-bot/
├── main.py                      # Entry point (--once, --eod, --backup flags)
├── requirements.txt             # Python dependencies
├── config/
│   ├── config.yaml              # Main configuration
│   ├── sector_mapping.yaml      # 11 sectors, 120+ stocks (metadata only)
│   └── etf_list.yaml            # Approved ETFs for AI consideration
├── src/
│   ├── orchestrator.py          # Central coordinator + APScheduler
│   ├── broker/
│   │   ├── kite_auth.py         # Kite Connect authentication (TOTP support)
│   │   ├── kite_client.py       # Rate-limited Kite API wrapper
│   │   └── instruments.py       # Instrument cache and lookup
│   ├── data/
│   │   ├── market_data.py       # OHLC fetcher with 5-min candle cache
│   │   ├── indicators.py        # 20+ technical indicators via pandas-ta
│   │   ├── levels.py            # Support/resistance, pivots, VWAP
│   │   ├── patterns.py          # Candlestick pattern detection
│   │   ├── universe.py          # Tradeable universe filter
│   │   ├── data_warehouse.py    # Central data store for all symbols
│   │   ├── market_pulse.py      # Market-wide aggregation for Sonnet
│   │   └── deep_dive.py         # Per-stock data packs for Opus
│   ├── news/
│   │   ├── news_fetcher.py      # RSS + web scraping for market headlines
│   │   └── macro_data.py        # FII/DII flows, global indices, VIX
│   ├── ai/
│   │   ├── system_prompt.py     # Claude's system prompt (trading rules)
│   │   ├── claude_client.py     # Anthropic SDK wrapper + circuit breaker
│   │   ├── prompt_formatter.py  # Builds structured prompts for both stages
│   │   ├── response_parser.py   # Parses Claude's JSON responses
│   │   └── llm_logger.py        # Token/cost tracking per call
│   ├── trading/
│   │   ├── portfolio_state.py   # Mode-blind portfolio data provider
│   │   ├── guardrails.py        # 15+ validation rules (safety-critical)
│   │   ├── paper_broker.py      # All paper trading mutations (single source of truth)
│   │   ├── execution_engine.py  # Order placement (delegates paper to PaperBroker)
│   │   ├── order_reconciler.py  # Order status reconciliation (live + paper delegation)
│   │   ├── sl_health_check.py   # SL/target monitoring (live + paper delegation)
│   │   ├── mis_exit.py          # 4-stage MIS auto-exit (3:00-3:12 PM)
│   │   ├── performance.py       # Rolling/cumulative metrics
│   │   └── trade_logger.py      # CSV audit trail
│   ├── database/
│   │   ├── db.py                # Thread-safe SQLite (WAL mode)
│   │   ├── migrations.py        # Schema + idempotent migrations
│   │   └── models.py            # Data models
│   └── notifications/
│       └── telegram_bot.py      # Telegram alerts
├── dashboard/
│   └── app.py                   # Streamlit dashboard (PAPER/LIVE/Both)
├── tests/
│   ├── conftest.py              # Shared fixtures
│   ├── test_imports.py          # Verify all modules import cleanly
│   ├── test_database.py         # Schema, migrations, mode separation
│   ├── test_guardrails.py       # Guardrail rule validation
│   ├── test_response_parser.py  # Claude response parsing
│   ├── test_indicators.py       # Technical indicator computation
│   ├── test_llm_logger.py       # LLM cost tracking
│   └── test_paper_broker.py     # Paper broker execution + portfolio tests
├── scripts/
│   └── setup_db.py              # Standalone DB setup
├── data/                        # Runtime data (SQLite DB)
├── logs/                        # Application logs
└── backups/                     # Daily backups
```

## Setup

### Prerequisites

- Python 3.11+
- Conda (recommended) or pip
- Zerodha Kite Connect API credentials
- Anthropic API key
- Telegram bot (optional, for notifications)

### Installation

```bash
# Create conda environment
conda create -n trading-bot python=3.11
conda activate trading-bot

# Install dependencies
pip install -r requirements.txt
```

### Configuration

1. Copy and edit the config file:
   ```bash
   # Edit config/config.yaml with your settings
   ```

2. Create environment variables (or `config/.env`):
   ```
   KITE_API_KEY=your_api_key
   KITE_API_SECRET=your_api_secret
   KITE_TOTP_SECRET=your_totp_secret    # For auto-login
   ANTHROPIC_API_KEY=your_anthropic_key
   TELEGRAM_BOT_TOKEN=your_bot_token     # Optional
   TELEGRAM_CHAT_ID=your_chat_id         # Optional
   ```

3. Initialize the database:
   ```bash
   python scripts/setup_db.py
   ```

## Usage

### Start the Bot

```bash
# Full auto mode (boot + scheduler)
python main.py

# Single market pulse cycle (for testing)
python main.py --once

# EOD review only
python main.py --eod

# Daily backup only
python main.py --backup
```

### Dashboard

```bash
streamlit run dashboard/app.py
```

The dashboard shows:
- Portfolio overview with value chart
- Trade log with filters
- Performance metrics (win rate, profit factor, P&L)
- Guardrail validation history
- LLM cost tracking by model and call type
- Paper trading state (holdings, positions, orders)

Use the sidebar radio button to switch between **PAPER**, **LIVE**, or **Both** views.

### Run Tests

```bash
python -m pytest tests/ -v
```

## Trading Modes

### Paper Trading (Default)

- Uses real market data from Kite but simulates order execution
- All paper trading mutations flow through `PaperBroker` (single source of truth)
- OHLC-based fill simulation: fetches 5-minute candles and checks if price touched SL/target/limit
- Separate paper tables: `paper_holdings`, `paper_positions`, `paper_orders`, `paper_cash`
- All shared tables (`trades`, `portfolio_snapshots`, `daily_summaries`, `position_tracking`, `watchlist_history`) filter by `mode='PAPER'`

### Live Trading

- Places real orders through Kite Connect
- Same guardrail validation as paper mode
- Claude receives identical data format — it never knows the mode
- All shared tables filter by `mode='LIVE'`

Switch between modes in `config/config.yaml`:
```yaml
trading:
  mode: "PAPER"  # Change to "LIVE" for real trading
```

## Scheduled Jobs (IST)

| Job | Schedule | Description |
|-----|----------|-------------|
| Market Pulse | Every 30 min, Mon-Fri 9:00-14:59 | Sonnet scans market, builds watchlist |
| SL Health Check | Every 5 min, Mon-Fri 9:00-15:59 | OHLC-based SL/target monitoring |
| Order Reconciliation | Every 60 sec | Check pending order status |
| Paper SL/Target Fill | Every 5 min (paper mode only) | OHLC-based fill simulation |
| MIS Exit Stage 1 | 3:00 PM | Graceful LIMIT close |
| MIS Exit Stage 2 | 3:05 PM | Retry unfilled |
| MIS Exit Stage 3 | 3:10 PM | Force MARKET close |
| MIS Exit Stage 4 | 3:12 PM | Emergency verification |
| EOD Review | 3:40 PM | Save summary + Telegram alert |
| Daily Backup | 4:00 PM | DB + config + logs backup |

## Risk Management

- **Max position size**: 20% of portfolio per stock
- **Max deployment**: 80% of capital (20% cash buffer)
- **Daily loss limit**: 3% of portfolio
- **Drawdown reduction**: At 10% drawdown, reduce position sizes
- **Drawdown halt**: At 15% drawdown, stop all new trades
- **SL range**: 0.5% to 5% (orders outside this range are rejected)
- **Minimum risk-reward**: 1.5:1
- **Max trades per day**: 12
- **Max CNC hold**: 15 days (with 5-day unwind phase)

## LLM Cost Tracking

All Claude API calls are tracked with per-token INR costs:
- **Opus 4.6**: Decision-making (INR 1,260/M input, 6,300/M output)
- **Sonnet 4.5**: Market pulse analysis (INR 252/M input, 1,260/M output)
- **Haiku 4.5**: News summarization (INR 67.20/M input, 336/M output)

Prompt caching is enabled to reduce costs on repeated system prompts.

## Database Schema

13 tables + 2 views in SQLite (WAL mode):

| Table | Purpose | Mode Column |
|-------|---------|-------------|
| `trades` | All trade records | Yes |
| `portfolio_snapshots` | Point-in-time portfolio state | Yes |
| `daily_summaries` | EOD performance summary | Yes (UNIQUE with date) |
| `position_tracking` | Open position SL/target tracking | Yes (UNIQUE with symbol/status) |
| `watchlist_history` | Historical watchlists | Yes |
| `llm_calls` | Every LLM API call | No (mode-agnostic) |
| `llm_daily_costs` | Aggregated daily LLM costs | No |
| `guardrail_log` | Validation results | No |
| `paper_holdings` | Paper CNC holdings | Paper-only |
| `paper_positions` | Paper MIS positions | Paper-only |
| `paper_orders` | Paper order book | Paper-only |
| `paper_cash` | Paper cash balance | Paper-only |
| `paper_reserved_cash` | Cash reserved for pending orders | Paper-only |

## Documentation

- [Product Requirements Document](docs/PRD.md)
- [Architecture Guide](docs/ARCHITECTURE.md)
- [Changelog](docs/CHANGELOG.md)
