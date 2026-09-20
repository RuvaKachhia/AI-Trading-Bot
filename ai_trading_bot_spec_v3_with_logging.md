# AI Trading Bot — Complete Specification Document
# Claude Opus 4.6 Autonomous Equity Trading Experiment

> **Purpose**: This document is the single source of truth for building an autonomous
> AI-powered equity trading system on Indian markets (NSE/BSE) using Claude Opus 4.6
> and Zerodha Kite Connect. Feed this document to Claude Code for implementation.

---

## TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Prerequisites & Accounts](#3-prerequisites--accounts)
4. [Tech Stack](#4-tech-stack)
5. [Tradeable Universe](#5-tradeable-universe)
6. [SEBI Rules & Hard Guardrails](#6-sebi-rules--hard-guardrails)
7. [Risk Management Rules](#7-risk-management-rules)
8. [Stock Discovery Pipeline](#8-stock-discovery-pipeline)
9. [Data Sources & Fetching](#9-data-sources--fetching)
10. [Complete System Prompt](#10-complete-system-prompt)
11. [Complete User Prompt Template](#11-complete-user-prompt-template)
12. [API Cost Optimization — Tiered Model Approach](#12-api-cost-optimization--tiered-model-approach)
13. [Daily Schedule & Workflow](#13-daily-schedule--workflow)
14. [Paper Trading Mode](#14-paper-trading-mode)
15. [Guardrail Validation Engine](#15-guardrail-validation-engine)
15B. [MIS Auto-Exit Engine](#15b-mis-auto-exit-engine)
15C. [Claude API Circuit Breaker](#15c-claude-api-circuit-breaker-safe-mode)
15D. [Order Reconciliation Loop](#15d-order-reconciliation-loop)
15E. [Corporate Actions Filter](#15e-corporate-actions-filter)
15F. [SL & Target Health Check](#15f-sl--target-health-check)
15G. [Prompt Size Management](#15g-prompt-size-management)
16. [Logging & Observability](#16-logging--observability)
17. [Phased Rollout Plan](#17-phased-rollout-plan)
18. [Estimated Costs](#18-estimated-costs)
19. [Project Directory Structure](#19-project-directory-structure)
20. [Key Risks & Mitigations](#20-key-risks--mitigations)

---

## 1. PROJECT OVERVIEW

### Goal
Test how well Claude Opus 4.6 performs as an autonomous equity trader on Indian
markets, making all trading decisions based on market data, technical analysis,
news, and macro context.

### Experiment Parameters
- **Capital**: ₹1,00,000 INR in a Zerodha account
- **Duration**: Till 31st March 2026
- **Markets**: NSE and BSE equity segment ONLY
- **Instruments**: NSE and BSE stocks + NSE-listed ETFs
- **NOT allowed**: F&O (futures/options), commodities, currency trading
- **Timeframes**: Intraday (MIS) and Swing trades (CNC, max hold till 31st March 2026)
- **NOT allowed**: Positional/long-term trades (thesis requiring > 3-4 weeks)
- **Success metric**: Not profit/loss alone — how well Claude reasons, adapts, and
  manages risk. All decisions and reasoning are logged for analysis.

### Core Design Principle
**Claude suggests → Hard-coded rules validate → Execution engine acts.**
The AI never bypasses the guardrail layer. Every Claude output is validated by
deterministic code before any order touches the broker API.

---



## 2. ARCHITECTURE

```
┌──────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                             │
│                   (Python main loop)                          │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐    │
│  │ Market Data  │  │ News &      │  │ Portfolio State    │    │
│  │ Module       │  │ Sentiment   │  │ Manager            │    │
│  │              │  │ Module      │  │                    │    │
│  │ - Kite API   │  │ - RSS feeds │  │ - Holdings         │    │
│  │ - Historical │  │ - Haiku     │  │ - Positions         │    │
│  │ - WebSocket  │  │   summaries │  │ - P&L tracking      │    │
│  │ - Bulk data  │  │ - BSE/NSE   │  │ - Trade log (DB)    │    │
│  └──────┬──────┘  └──────┬──────┘  └─────────┬───────────┘    │
│         │                │                    │                │
│         ▼                ▼                    ▼                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │            MARKET PULSE BUILDER                         │   │
│  │  Compact market dashboard: sectors, movers, volume,     │   │
│  │  macro, news headlines — NO individual stock analysis   │   │
│  └───────────────────────┬────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │        CLAUDE (Sonnet) — MARKET PULSE CALL              │   │
│  │  - Receives: compact market overview (~3K tokens)       │   │
│  │  - Returns: watchlist of 8-15 stocks + reasoning        │   │
│  │  - Claude decides WHAT to look at                       │   │
│  └───────────────────────┬────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │            DEEP DIVE DATA PACK BUILDER                  │   │
│  │  Fetches full data ONLY for Claude-requested stocks:    │   │
│  │  candles, indicators, news, levels, patterns            │   │
│  └───────────────────────┬────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │        CLAUDE (Opus) — TRADING DECISION CALL            │   │
│  │  - Receives: system prompt + deep dive data             │   │
│  │  - Returns: JSON with trading decisions + reasoning     │   │
│  │  - Claude decides WHETHER and HOW to trade              │   │
│  └───────────────────────┬────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │            GUARDRAIL VALIDATION ENGINE                   │   │
│  │  - Validates every decision against hard-coded rules    │   │
│  │  - SEBI compliance, position limits, risk checks        │   │
│  │  - Rejects invalid orders with logged reasons           │   │
│  └───────────────────────┬────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │            TRADE EXECUTION ENGINE                       │   │
│  │  - PAPER mode: logs to local DB, simulates fills        │   │
│  │  - LIVE mode: executes via kite.place_order()           │   │
│  │  - Sends Telegram notifications                         │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐   │
│  │            NOTIFICATION & LOGGING                       │   │
│  │  - Telegram bot for real-time alerts                    │   │
│  │  - SQLite/PostgreSQL for complete trade log             │   │
│  │  - Every Claude prompt + response stored                │   │
│  │  - Dashboard (Streamlit) for monitoring                 │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow Summary
```
Kite Connect API ──→ Raw OHLCV, quotes, portfolio, instruments
                          │
                          ▼
Data Infrastructure ──→ Bulk indicator computation, sector aggregation
(pandas-ta, ta-lib)       │
                          ▼
News sources ──────→ RSS feeds → Haiku summarization
(MoneyControl, ET, BSE)   │
                          ▼
Macro data ────────→ FII/DII, global cues, VIX
(scraping, free APIs)     │
                          ▼
Market Pulse Builder ─→ Compact dashboard (~3,000 tokens)
                          │
                          ▼
Claude (Sonnet) ───→ Watchlist request: "I want deep data on these stocks"
                          │
                          ▼
Deep Dive Builder ─→ Full data pack for Claude-selected stocks only
                          │
                          ▼
Claude (Opus) ─────→ JSON trading decisions
                          │
                          ▼
Guardrail Engine ──→ Validate → Execute or Reject
                          │
                          ▼
Kite Connect API ──→ Place order (LIVE) or Log (PAPER)
```

## 3. PREREQUISITES & ACCOUNTS

### 3.1 Zerodha Kite Connect
- **Cost**: ₹500/month
- **Sign up**: https://developers.kite.trade
- **What you get**: `api_key` and `api_secret`
- **Important**: Access tokens expire daily. You need to re-authenticate each
  morning. This requires a manual login step or a TOTP-based auto-login workaround.
- **Rate limits**: 10 requests/second for orders, 1 request/second for historical
  data. Design polling accordingly.

### 3.2 Anthropic API
- **Sign up**: https://console.anthropic.com
- **Note**: The Claude chat subscription (Pro/Max) does NOT include API access.
  They are separate products. You need to set up Console access and pay for API
  usage separately.
- **Models you'll use**:
  - `claude-opus-4-6` — for trading decisions (most expensive, most capable)
  - `claude-sonnet-4-6` — for analysis tasks (balanced cost/quality)
  - `claude-haiku-4-5-20251001` — for news summarization (cheapest, fastest)

### 3.3 Server / VPS
- Needs to be running during market hours: 9:00 AM – 4:00 PM IST
- Options: AWS Lightsail, DigitalOcean droplet, Google Cloud VM, or a Raspberry Pi
  at home
- Low latency is NOT critical (this is not HFT)
- Recommended: Ubuntu 22.04+, 2GB RAM, 1 vCPU minimum

### 3.4 Zerodha Trading Account
- Fund it with ₹1,00,000
- Ensure equity segment is activated (it is by default)

### 3.5 Telegram Bot (for notifications)
- Create a bot via @BotFather on Telegram
- Get the bot token and your chat_id
- Used for: trade alerts, daily P&L summaries, error notifications, guardrail
  trigger alerts

---

## 4. TECH STACK

| Component | Technology |
|---|---|
| **Language** | Python 3.11+ |
| **Broker SDK** | `kiteconnect` (official Zerodha Python package) |
| **AI SDK** | `anthropic` (official Anthropic Python package) |
| **Technical Analysis** | `pandas-ta` and/or `ta-lib` |
| **Data Processing** | `pandas`, `numpy` |
| **News Fetching** | `feedparser` (RSS), `requests` + `beautifulsoup4` (scraping) |
| **Database** | SQLite (simple) or PostgreSQL (if scaling) |
| **Scheduling** | `APScheduler` or simple `time.sleep` loop with time checks |
| **Notifications** | `python-telegram-bot` or raw Telegram Bot API via `requests` |
| **Dashboard** | Streamlit (optional, for monitoring) |
| **Config Management** | `pyyaml` for config files |
| **Logging** | Python `logging` module → file + console |
| **Environment** | `python-dotenv` for secrets management |

### Python Dependencies (requirements.txt)
```
kiteconnect>=5.0.0
anthropic>=0.40.0
pandas>=2.0.0
numpy>=1.24.0
pandas-ta>=0.3.14
TA-Lib>=0.4.28
feedparser>=6.0.0
requests>=2.31.0
beautifulsoup4>=4.12.0
APScheduler>=3.10.0
python-telegram-bot>=20.0
pyyaml>=6.0
python-dotenv>=1.0.0
filelock>=3.12.0
streamlit>=1.30.0
```

---

## 5. TRADEABLE UNIVERSE

### 5.1 Stocks
- **Primary universe**: Stocks listed on NSE/BSE with the Market Capitalization of ₹1000 crore or more
- **Segment**: Equity (EQ) ONLY
- **Excluded**: F&O segment, commodity segment, currency segment
- **Filtered out**:
  - Stocks priced below ₹20
  - Stocks with average daily volume below ₹1 crore (20-day average)
  - Stocks on SEBI's ASM (Additional Surveillance Measure) list
  - Stocks on SEBI's GSM (Graded Surveillance Measure) list
  - Stocks under trade-to-trade (T2T) segment

### 5.2 ETFs (Allowed and Encouraged)
ETFs provide broad market/sector exposure without single-stock risk. Claude can
use these for thematic plays or defensive positioning.

| ETF Symbol | Tracks | Use Case |
|---|---|---|
| NIFTYBEES | Nifty 50 | Broad market bet |
| BANKBEES | Bank Nifty | Banking sector play |
| GOLDBEES | Gold price | Hedge / defensive |
| ITBEES | Nifty IT | IT sector exposure |
| PSUBNKBEES | PSU Bank index | PSU banking theme |
| JUNIORBEES | Nifty Next 50 | Midcap exposure |
| LIQUIDBEES | Liquid fund | Parking cash (defensive) |
| CPSEETF | CPSE index | PSU theme |
| SILVERBEES | Silver price | Commodity hedge |
| PHARMABEES | Nifty Pharma | Pharma sector |
| MOM50 | Nifty Momentum 50 | Momentum strategy |

All ETFs trade on NSE equity segment with CNC/MIS, so no special rules needed.

### 5.3 NOT Allowed
- Futures & Options (F&O) — ANY instrument in F&O segment
- Commodities (MCX segment)
- Currency derivatives (CDS segment)
- Stocks with market capitalization below ₹1000 crore (unless exceptional catalyst — rare)
- Penny stocks (below ₹20)
- Illiquid stocks (volume < ₹1 Cr daily)

---

## 6. SEBI RULES & HARD GUARDRAILS

These rules are enforced in CODE, not by prompting. Claude's output is validated
against these before any order is placed. Violations are logged and the order is
rejected.

### 6.1 Instrument Restrictions
```
RULE: instrument_type must be "EQ" (equity)
RULE: exchange must be "NSE" or "BSE"
RULE: product must be "CNC" or "MIS" only
RULE: NEVER allow product types: NRML, BO, CO
RULE: NEVER allow F&O, commodity, or currency instruments
```

### 6.2 Short Selling Rules (SEBI Regulation)
```
RULE: CNC (delivery) SELL orders:
  - Can ONLY sell stocks you already hold
  - sell_quantity <= current_holdings_quantity
  - If holdings = 0, CNC SELL is BLOCKED
  - Rationale: SEBI prohibits naked short selling in delivery

RULE: MIS (intraday) SELL orders:
  - CAN short sell (sell without holding)
  - Position MUST be squared off by the bot before 3:10 PM IST same day
  - Bot runs a 3-stage exit process (3:00→3:05→3:10 PM) to close all MIS
  - NEVER rely on Zerodha's auto-square-off at 3:20 PM — it charges ₹50+GST
    per position
```

### 6.3 Timing Rules
```
RULE: Market hours are 9:15 AM – 3:30 PM IST
RULE: No MIS orders after 2:30 PM IST (not enough time for thesis to play out)
RULE: Begin MIS square-off process at 3:00 PM IST
RULE: All MIS positions MUST be closed by 3:10 PM IST (HARD DEADLINE)
RULE: The bot MUST square off all MIS positions itself. NEVER rely on Zerodha's
      auto-square-off (triggers at 3:20 PM) because it charges ₹50 + GST per
      position. This is wasted money. The bot must handle this autonomously.
RULE: If any MIS position is still open at 3:12 PM, place MARKET order to close
      immediately (emergency fallback — accept slippage to avoid ₹59 penalty).
RULE: CNC orders can be placed anytime during market hours
RULE: Pre-market orders (9:00-9:15 AM) allowed for CNC but NOT for MIS
```

### 6.4 Stock Quality Rules
```
RULE: Stock price must be >= ₹20
RULE: 20-day average daily volume must be >= ₹1,00,00,000 (₹1 Crore)
RULE: Stock must NOT be on ASM list (fetch daily from NSE)
RULE: Stock must NOT be on GSM list (fetch daily from NSE)
RULE: Stock must be in NSE/BSE equity segment OR be an approved ETF
```

### 6.5 Experiment Timeframe Rules
```
RULE: Experiment duration = 30 calendar days (approx 22 trading days)
RULE: Max CNC holding period = Till 31st March 2026
RULE: Every CNC trade MUST have: price target, stop-loss, AND time-based exit
RULE: No new CNC positions in the last 5 trading days (unwind phase)
RULE: Last 5 days = intraday only + unwinding existing CNC holdings
RULE: All positions must be closed by experiment end date
```

---

## 7. RISK MANAGEMENT RULES

These are also enforced in code, not by prompting.

### 7.1 Position Sizing
```
RULE: No single position > 20% of total portfolio value
RULE: Total deployed capital must not exceed 80% of portfolio value
RULE: Minimum 20% cash buffer must always be maintained
RULE: Position size calculation:
      max_position_value = portfolio_total_value * 0.20
      max_quantity = floor(max_position_value / current_price)
```

### 7.2 Stop-Loss & Target (Broker-Side Enforcement)
```
RULE: Every trade MUST have BOTH a stop-loss AND a target price
RULE: If Claude doesn't specify a stop-loss, apply default:
      - BUY orders: SL = entry_price * 0.98 (2% below)
      - SELL orders (MIS short): SL = entry_price * 1.02 (2% above)
RULE: If Claude doesn't specify a target, apply default:
      - BUY orders: Target = entry_price * 1.03 (3% above, i.e. 1.5:1 R:R)
      - SELL orders (MIS short): Target = entry_price * 0.97 (3% below)
RULE: Stop-loss AND target orders MUST be placed on the broker side (Kite)
      immediately after the entry order is filled — not just tracked locally
RULE: SL orders placed as SL or SL-M order type on Kite
RULE: Target orders placed as LIMIT exit orders on Kite
RULE: Claude can suggest wider/tighter SL, but minimum is 0.5% and max is 5%
RULE: SL and target can be updated later (e.g., trailing SL) via order
      modification on Kite, but must ALWAYS exist on the broker side
RULE: A background "SL Health Check" runs every 5 minutes during market hours
      and verifies that for every open position, a corresponding SL order and
      target order exist on Kite. If missing (e.g., due to order rejection or
      cancellation), the bot re-places the SL/target immediately and sends a
      Telegram alert.
```

### 7.3 Daily Loss Limits
```
RULE: If (realized_loss + unrealized_loss) for the day > daily_loss_limit:
      - STOP all new trades for the day
      - Square off all MIS positions
      - Send Telegram alert: "DAILY LOSS LIMIT HIT"
      - Claude receives NO_ACTION instruction for rest of day
RULE: daily_loss_limit = total_capital * 0.05 (5%)
      e.g., ₹1,00,000 capital → ₹5,000 daily loss limit
```

### 7.4 Trade Frequency
```
RULE: Max trades per day = 25 (configurable)
RULE: This counts order placements, not modifications/cancellations
RULE: Rationale: controls brokerage costs and prevents hyperactive behavior
```



## 8. STOCK DISCOVERY PIPELINE

Claude drives the entire stock selection process. The Python layer is a data
servant — it collects, organizes, and delivers data. It never filters, ranks,
or applies trading logic. All investment intelligence comes from Claude.

### Design Principle
> **Claude decides WHAT to look at, THEN decides WHETHER to trade.**
> Python provides the raw data infrastructure. No screeners, no signal
> detection, no directional opinions in code.

### Layer 1: Universe Filter (Pure Python, Daily at 8:30 AM)
The only filtering that happens in code — and it's purely mechanical
(regulatory/liquidity constraints, not trading logic).

```
Input:  Nifty 500 stock list + ETF list
Filter: Remove ASM/GSM stocks, T2T stocks, stocks < ₹20, volume < ₹1 Cr
Output: ~350-450 tradeable stocks (the "eligible universe")
Cost:   Zero (local computation)
```

### Layer 2: Data Infrastructure (Pure Python, Continuous)
Collect and pre-compute raw data for the ENTIRE eligible universe. No
filtering, no ranking — just make data available so Claude can request
deep dives on any stock instantly.

**What gets collected (bulk, in background):**

- Live quotes for all ~400 eligible stocks (via WebSocket or periodic polling)
- Daily OHLCV candles (cached once at market open, updated end of day)
- Intraday 15-min candles (updated every 15 min)
- Technical indicators computed in bulk: RSI, MACD, SMA(20/50/200), ADX, ATR,
  Bollinger Bands, VWAP, Supertrend — stored per stock, ready for instant retrieval
- Sector-level aggregations: sector index performance, sector breadth, avg sector RSI
- News headlines fetched via RSS for all stocks (raw, not yet summarized)
- Corporate actions calendar (ex-dates, splits, bonuses flagged)

**What gets pre-aggregated for the Market Pulse:**

- Top 10 gainers (by % change) from the eligible universe
- Top 10 losers (by % change) from the eligible universe
- Top 10 volume surges (today's volume vs 20-day average)
- Stocks at/near 52-week highs (within 2%)
- Stocks at/near 52-week lows (within 2%)
- Sector heatmap: each sector index's % change, ranked
- Gap-up and gap-down stocks (> 2% gap at open)

```
Output: Complete data warehouse for all ~400 stocks, queryable instantly
Cost:   Zero (local computation using pandas-ta)
Note:   These aggregations are presented as RAW FACTS — no "buy/sell" 
        signals, no "bullish/bearish" labels. Just: "TATAMOTORS is up 3.2% 
        on 2.1x average volume." Claude interprets what this means.
```

### Layer 3: Market Pulse (Claude Sonnet, Every 30 min)
Send Claude a compact, high-level dashboard of the entire market. Claude
reads this like a trader scanning Bloomberg, and tells us which stocks
it wants full data on and WHY.

**Market Pulse prompt contains (~2,500-3,500 tokens):**

- Index levels and changes (Nifty, Bank Nifty, sectoral indices)
- Market breadth (advance/decline ratio)
- Sector heatmap (all sectors ranked by performance)
- Top 10 gainers with % change and volume ratio
- Top 10 losers with % change and volume ratio
- Top 10 volume surges (stocks with unusual activity)
- 52-week high/low stocks
- Gap stocks (> 2% gap at open)
- FII/DII flows
- Key macro data (VIX, USD/INR, crude, global indices)
- Top news headlines (5-10 most impactful, Haiku-summarized)
- ETF snapshot (all approved ETFs with price change)
- Current portfolio state (brief: holdings, cash, P&L)
- Existing positions summary (symbols + P&L %, for context)

**Claude Sonnet responds with a watchlist request:**

```json
{
  "market_read": "Brief 2-3 sentence market assessment",
  "watchlist": [
    {
      "symbol": "TATAMOTORS",
      "exchange": "NSE",
      "reason": "Auto sector outperforming, TATAMOTORS leading with 2x volume. Want to check if breakout is sustained on daily chart."
    },
    {
      "symbol": "HDFCBANK",
      "exchange": "NSE",
      "reason": "Banking sector weak but HDFCBANK holding near support. Potential relative strength play if broader market stabilizes."
    },
    {
      "symbol": "GOLDBEES",
      "exchange": "NSE",
      "reason": "VIX rising + FII selling. Want to evaluate defensive ETF positioning."
    }
  ],
  "drop_from_watchlist": ["INFY", "SBIN"],
  "drop_reasons": "INFY thesis played out (target hit). SBIN sector momentum fading."
}
```

**Critical: Claude's watchlist reasoning is logged.** This is core experiment
data — it shows how Claude scans markets and identifies opportunities.

```
Output: 8-15 stock symbols Claude wants to analyze in depth
Cost:   ~₹2-5 per call (Sonnet is much cheaper than Opus)
```

### Layer 4: Deep Dive Data Pack (Pure Python, On Demand)
Python fetches the full data package ONLY for the stocks Claude requested
in Layer 3. This is identical to the old per-stock data format — candles,
indicators, news, levels — but assembled on demand for Claude's selections.

**For each Claude-requested stock:**
- Full daily candles (last 15 sessions) with OHLCV
- Intraday 15-min candles (today)
- Complete technical indicator suite (RSI, MACD, SMA, EMA, VWAP, BBands, ADX, ATR, Supertrend)
- Support/resistance levels and pivot points
- Candlestick patterns (last 5 sessions)
- News & catalysts (Haiku-summarized, 1-2 sentences per headline)
- Sector context (sector index, peer performance)

```
Output: Full structured data pack for 8-15 Claude-selected stocks
Cost:   Haiku calls for news summarization (~₹2-5)
Note:   Data is already pre-computed in Layer 2 — this step just assembles
        and formats it for the Opus prompt. Near-instant.
```

### Layer 5: Trading Decision (Claude Opus)
Send the complete structured prompt (see Sections 10 & 11) with:
- Market context
- Portfolio state
- 8-15 Claude-selected stocks with full candle data + indicators + news
- Existing position updates
- Performance history

Claude analyzes and returns JSON trading decisions.

```
Output: Specific BUY/SELL/HOLD/EXIT decisions with reasoning
Cost:   Main cost center (~₹30-60 per call, 8-10 calls/day)
```

### Why This Architecture Matters for the Experiment

In the old design, Python screeners decided what was "interesting" (RSI
crossovers, golden crosses, volume breakouts). Claude just picked from a
pre-filtered menu. That made it impossible to isolate Claude's alpha.

In this design:
1. **Claude sees the whole market** via the Market Pulse — nothing is hidden
2. **Claude decides what to investigate** — its watchlist choices reveal its
   market scanning ability
3. **Claude decides whether to trade** — its analysis of the deep dive data
   reveals its trading intelligence
4. **Every step is logged** — watchlist reasoning, deep dive analysis, trade
   decisions. The experiment can evaluate Claude at each stage independently.

The Python layer is intentionally "dumb" — it collects raw data and delivers
it on demand. All trading intelligence comes from Claude.

---

## 9. DATA SOURCES & FETCHING

### 9.1 Complete Data Source Reference Table

| Data Field | Source | API / Method | Fetch Frequency | Notes |
|---|---|---|---|---|
| **Index prices** (Nifty 50, Bank Nifty, Nifty IT, etc.) | Kite Connect | `kite.quote("NSE:NIFTY 50", ...)` or WebSocket | Real-time / every tick | Use WebSocket for live streaming, quote API for on-demand |
| **Stock live price** (LTP, OHLC, volume) | Kite Connect | `kite.quote("NSE:SYMBOL")` | Real-time | Returns last traded price, day OHLC, volume |
| **Historical daily candles** | Kite Connect | `kite.historical_data(token, from, to, "day")` | Once at start of day, cached | Returns OHLCV arrays |
| **Intraday candles** (15-min) | Kite Connect | `kite.historical_data(token, from, to, "15minute")` | Every 15 minutes | Also supports "5minute", "minute" intervals |
| **Portfolio holdings** (CNC) | Kite Connect | `kite.holdings()` | Every prompt cycle | Returns all delivery holdings with avg price, quantity |
| **Open positions** (MIS + CNC day) | Kite Connect | `kite.positions()` | Every prompt cycle | Returns `day` and `net` positions |
| **Available margin / cash** | Kite Connect | `kite.margins()` | Every prompt cycle | `margins["equity"]["available"]["cash"]` |
| **Order history** | Kite Connect | `kite.orders()` | As needed | All orders placed today |
| **Instrument list** (all tradeable) | Kite Connect | `kite.instruments("NSE")` | Once daily (pre-market) | Returns full instrument dump with tokens |
| **RSI, MACD, SMA, EMA, ADX, ATR** | Computed locally | `pandas-ta` library | Every prompt cycle | Computed from Kite historical data |
| **Bollinger Bands** | Computed locally | `pandas-ta` → `df.ta.bbands()` | Every prompt cycle | |
| **VWAP** | Computed locally | Python: `cumsum(price*vol) / cumsum(vol)` | Every prompt cycle | Computed from intraday candle data |
| **Candlestick patterns** | Computed locally | `ta-lib` CDL functions or `pandas-ta` | Every prompt cycle | Doji, Engulfing, Hammer, etc. |
| **Support / Resistance** | Computed locally | Python swing high/low detection | Daily + intraday refresh | Based on recent pivot points |
| **Pivot Points** | Computed locally | `(prev_high + prev_low + prev_close) / 3` | Daily | Classic pivot formula |
| **FII / DII flows** | Web scraping | MoneyControl or NSDL website | Twice daily (AM + PM) | `https://www.moneycontrol.com/stocks/marketinfo/fii_dii_activity/` |
| **USD/INR** | Kite Connect | `kite.quote("NSE:USDINR")` | Real-time | Macro context, not for trading |
| **Crude Oil** | Kite Connect or API | `kite.quote("MCX:CRUDEOIL")` or free API | Periodically | Macro context only |
| **US market data** (S&P 500, Dow, Nasdaq) | External API | Yahoo Finance (`yfinance`) or Alpha Vantage | Pre-market (once) | Previous close data |
| **SGX Nifty** (pre-market) | Web scraping | MoneyControl or Investing.com | Pre-market (once) | Indicates how Nifty might open |
| **India VIX** | Kite Connect | `kite.quote("NSE:INDIA VIX")` | Real-time | Volatility index — low VIX = calm, high = fear |
| **Stock news & catalysts** | RSS feeds | `feedparser` library parsing MoneyControl, ET, LiveMint RSS | Every 30-60 min | Raw headlines, then summarized by Haiku |
| **Corporate announcements** | BSE website | BSE API or scraping | Morning + as needed | Board meetings, dividends, results dates |
| **Bulk/Block deals** | NSE/BSE website | Scraping or CSV download | Daily (post-market) | Large institutional trades |
| **Insider trading disclosures** | NSE website | SAST data scraping | Daily | Promoter buy/sell signals |
| **ASM/GSM stock list** | NSE website | Download CSV from NSE circulars | Daily (pre-market) | For filtering out restricted stocks |
| **Sector index performance** | Kite Connect | `kite.quote()` for NIFTY IT, NIFTY BANK, etc. | Real-time | Sector rotation context |
| **Peer stock prices** | Kite Connect | `kite.quote()` for peer symbols | Every prompt cycle | Relative performance |
| **Trade history & P&L** | Local database | SQLite/PostgreSQL queries | Every prompt cycle | Your own trade log |
| **Performance metrics** (win rate, etc.) | Local database | Python computation from trade log | Daily / every prompt | Rolling 5-day stats |
| **Risk parameters** | Config file | `config.yaml` | Static | Loss limits, max trades, position sizes |
| **Experiment day counter** | Computed | `(today - start_date).days` | Every prompt | Day X of 30 |

### 9.2 Kite Connect API Quick Reference

```python
from kiteconnect import KiteConnect, KiteTicker

kite = KiteConnect(api_key="your_api_key")

# --- Authentication (daily) ---
# Step 1: Generate login URL
login_url = kite.login_url()  # redirect user here
# Step 2: After login, you get a request_token
data = kite.generate_session("request_token", api_secret="your_secret")
kite.set_access_token(data["access_token"])

# --- Quotes ---
quotes = kite.quote(["NSE:RELIANCE", "NSE:INFY", "NSE:NIFTY 50"])
# Returns: { "NSE:RELIANCE": { "last_price": 2460, "ohlc": {...}, "volume": ... } }

# --- Historical Data ---
from datetime import datetime, timedelta
instrument_token = 738561  # RELIANCE token from instruments list
data = kite.historical_data(
    instrument_token,
    from_date=datetime.now() - timedelta(days=30),
    to_date=datetime.now(),
    interval="day"  # options: minute, 5minute, 15minute, 30minute, 60minute, day
)
# Returns: [{"date": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]

# --- Portfolio ---
holdings = kite.holdings()          # CNC delivery holdings
positions = kite.positions()        # day + net positions
margins = kite.margins()            # available cash, used margin

# --- Place Order ---
order_id = kite.place_order(
    variety=kite.VARIETY_REGULAR,
    exchange=kite.EXCHANGE_NSE,
    tradingsymbol="RELIANCE",
    transaction_type=kite.TRANSACTION_TYPE_BUY,
    quantity=4,
    product=kite.PRODUCT_CNC,       # CNC for delivery, MIS for intraday
    order_type=kite.ORDER_TYPE_LIMIT,
    price=2450,
    validity=kite.VALIDITY_DAY
)

# --- Place Stop-Loss Order ---
sl_order_id = kite.place_order(
    variety=kite.VARIETY_REGULAR,
    exchange=kite.EXCHANGE_NSE,
    tradingsymbol="RELIANCE",
    transaction_type=kite.TRANSACTION_TYPE_SELL,
    quantity=4,
    product=kite.PRODUCT_CNC,
    order_type=kite.ORDER_TYPE_SL,
    price=2390,           # limit price (order executes at this or better)
    trigger_price=2396,   # trigger price (order activates when LTP hits this)
    validity=kite.VALIDITY_DAY
)

# --- Instruments List ---
instruments = kite.instruments("NSE")  # full NSE instrument dump
# Filter for equity: [i for i in instruments if i["instrument_type"] == "EQ"]

# --- WebSocket for Live Data ---
kws = KiteTicker("api_key", "access_token")

def on_ticks(ws, ticks):
    for tick in ticks:
        process_tick(tick)  # your handler

kws.on_ticks = on_ticks
kws.subscribe([738561, 408065])  # instrument tokens
kws.set_mode(kws.MODE_FULL, [738561, 408065])
kws.connect(threaded=True)
```

### 9.3 News Fetching Examples

```python
import feedparser

# MoneyControl RSS
feed = feedparser.parse("https://www.moneycontrol.com/rss/marketreports.xml")
for entry in feed.entries[:10]:
    print(entry.title, entry.link)

# Google News RSS for specific stock
feed = feedparser.parse("https://news.google.com/rss/search?q=RELIANCE+stock+NSE&hl=en-IN")
for entry in feed.entries[:5]:
    print(entry.title)

# Then summarize with Haiku:
# client.messages.create(model="claude-haiku-4-5-20251001", ...)
```

### 9.4 FII/DII Scraping

```python
import requests
from bs4 import BeautifulSoup

# MoneyControl FII/DII page
url = "https://www.moneycontrol.com/stocks/marketinfo/fii_dii_activity/"
response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
soup = BeautifulSoup(response.text, "html.parser")
# Parse the table to extract FII/DII buy/sell values
```



## 10. COMPLETE SYSTEM PROMPT

This is sent as the `system` parameter in every Anthropic API call. It defines
Claude's role, constraints, and output format. It is STATIC — you write it once
and only update it if the rules change.

There are TWO call types that use this system prompt:
1. **MARKET_PULSE** (Sonnet) — Claude scans the market and builds a watchlist
2. **TRADING_DECISION** (Opus) — Claude analyzes deep data and makes trade decisions

The system prompt covers both. The call type is indicated in the user prompt.

```
You are an autonomous equity trading assistant operating on the Indian stock
markets (NSE/BSE) via the Zerodha Kite Connect API. You have two roles
depending on the call type:

1. MARKET_PULSE calls: You receive a compact market overview and decide which
   stocks deserve deeper analysis. You are the one scanning the market and
   choosing where to focus — like a human trader looking at their Bloomberg
   terminal each morning.

2. TRADING_DECISION calls: You receive full data for stocks you previously
   selected, and make specific trading decisions with exact prices, quantities,
   stop-losses, and targets.

═══════════════════════════════════════════
HARD CONSTRAINTS (NEVER VIOLATE THESE)
═══════════════════════════════════════════

1. EQUITY ONLY — You may only trade in the equity (EQ) segment on NSE and BSE.
   You must NEVER suggest trades in F&O (futures, options), commodities, or
   currency segments. ETFs listed on NSE equity segment ARE allowed.

2. PRODUCT TYPES — You may only use:
   - CNC (Cash & Carry / Delivery): For holding stocks overnight or longer.
   - MIS (Margin Intraday Square-off): For intraday trades only.
   You must NEVER use NRML, BO, or CO product types.

3. SHORT SELLING RULES (SEBI):
   - CNC (delivery): You can ONLY SELL stocks you already hold. You CANNOT
     short sell in delivery. If holdings quantity is 0, you cannot place a
     CNC SELL order.
   - MIS (intraday): You CAN short sell (SELL without holding), but the
     position MUST be squared off before 3:20 PM IST the same day.

4. POSITION SIZING:
   - No single position may exceed 20% of total portfolio value.
   - Total deployed capital must not exceed 80% of portfolio value.
   - Minimum cash buffer of 20% must always be maintained.

5. RISK MANAGEMENT:
   - Every trade MUST include a stop_loss price AND a target price.
   - Default stop-loss: 2% below entry for BUY, 2% above entry for short SELL.
   - Stop-loss and target orders are placed on the broker side at entry time.
     They can be updated later (e.g., trailing SL), but must always exist.
   - If daily realized + unrealized loss exceeds the daily_loss_limit
     provided in the data, output NO_ACTION for all decisions.
   - Maximum trades per day: as specified in the data.

6. STOCK RESTRICTIONS:
   - Do NOT trade stocks priced below ₹20.
   - Do NOT trade stocks with average daily volume below ₹1 crore.
   - Do NOT trade stocks in the ASM/GSM list (provided in data if applicable).
   - Stick to Nifty 500 universe + approved ETFs unless there is an
     exceptional catalyst.

7. TIMING:
   - Do NOT place new MIS orders after 2:30 PM IST.
   - Recommend squaring off MIS positions by 3:00 PM IST.
   - All MIS positions MUST be closed by 3:10 PM IST (HARD DEADLINE).
   - NEVER leave MIS positions for Zerodha's auto-square-off (3:20 PM) as it
     charges ₹50 + GST per position. The bot handles all MIS exits itself.
   - CNC orders can be placed anytime during market hours (9:15 AM – 3:30 PM).

8. EXPERIMENT TIMEFRAME:
   - This experiment runs for approximately 1 month (30 calendar days / ~22
     trading days).
   - Maximum CNC holding period: 15 trading days.
   - Every CNC trade must include: (a) price target, (b) stop-loss, and
     (c) a time-based exit plan (e.g., "exit if target not hit in 7 days").
   - Do NOT enter trades where the thesis requires more than 3-4 weeks to
     play out.
   - In the final 5 trading days: NO new CNC positions. Focus on unwinding
     existing holdings and intraday trades only.
   - All positions must be closed by experiment end date.

═══════════════════════════════════════════
TRADEABLE INSTRUMENTS
═══════════════════════════════════════════

- Nifty 500 stocks on NSE/BSE (equity segment only)
- NSE-listed ETFs: NIFTYBEES, BANKBEES, GOLDBEES, ITBEES, PSUBNKBEES,
  JUNIORBEES, LIQUIDBEES, CPSEETF, SILVERBEES, PHARMABEES, MOM50
- NO F&O, NO commodities, NO currency derivatives

═══════════════════════════════════════════
TRADING PHILOSOPHY
═══════════════════════════════════════════

- You are a disciplined, systematic trader. NOT a gambler.
- Doing nothing is a valid and often correct decision. If the setup is not
  clear, output NO_ACTION. Capital preservation is your #1 priority.
- You prefer high-probability setups with favorable risk-reward (min 1:1.5).
- You combine technical analysis (price action, indicators) with fundamental
  catalysts (news, earnings, sector trends) for decision-making.
- You think in terms of risk-reward, not just direction. Always define your
  exit before your entry.
- You are aware of sector rotation, market breadth, and macro context.
- You adapt: in trending markets you ride momentum; in choppy/sideways
  markets you reduce position sizes or stay in cash.
- For intraday (MIS): focus on momentum, volume spikes, and VWAP.
- For swing trades (CNC): focus on daily chart patterns, fundamental
  catalysts, support/resistance levels, and setups with 3-15 day holding period.
- Consider ETFs when you want sector/market exposure without single-stock risk,
  or when you want to be defensive (GOLDBEES, LIQUIDBEES).
- Learn from past performance: if a strategy has been losing, adjust. If a
  sector is consistently profitable, consider increasing allocation.

═══════════════════════════════════════════
MARKET PULSE — WATCHLIST SELECTION
═══════════════════════════════════════════

When the call_type is MARKET_PULSE, you will receive a compact market
dashboard showing the entire market landscape: sector performance, top movers,
volume surges, 52-week extremes, news headlines, macro data, and your current
portfolio.

Your job is to scan this data like a professional trader and select 8-15
stocks (from the eligible universe) that you want FULL data on for deeper
analysis. Think of it this way: you're looking at a Bloomberg terminal and
deciding where to zoom in.

Your selections can be driven by ANY logic you see fit:
- A stock with unusual volume that might signal institutional activity
- A sector theme playing out (e.g., all banking stocks rallying)
- A stock in the news with a catalyst (earnings, policy change)
- A stock near a key level (52-week high/low) that might break out
- A defensive ETF play because market conditions look risky
- A stock you held previously and want to re-enter
- A contrarian play: a stock that's down when its sector is up
- Anything else — you are the decision maker

You MUST also include any stocks you currently hold in your watchlist (so
you get updated data for position management).

Respond with JSON in this format:

{
  "market_read": "2-3 sentence assessment of overall market conditions",
  "watchlist": [
    {
      "symbol": "SYMBOL",
      "exchange": "NSE",
      "reason": "Why you want to analyze this stock. Be specific."
    }
  ],
  "drop_from_watchlist": ["SYMBOL1", "SYMBOL2"],
  "drop_reasons": "Why these stocks no longer interest you."
}

═══════════════════════════════════════════
TRADING DECISION — OUTPUT FORMAT
═══════════════════════════════════════════

When the call_type is TRADING_DECISION, you will receive full data for the
stocks you selected in your last Market Pulse call. Analyze each and make
trading decisions.

You MUST respond with valid JSON only. No markdown, no explanation outside
the JSON structure. No code blocks. Just raw JSON. Use this exact schema:

{
  "market_assessment": {
    "bias": "BULLISH | BEARISH | NEUTRAL | CAUTIOUS",
    "reasoning": "2-3 sentences on overall market read",
    "key_levels": {
      "nifty_support": <number>,
      "nifty_resistance": <number>
    }
  },
  "decisions": [
    {
      "action": "BUY | SELL | HOLD | EXIT | NO_ACTION",
      "symbol": "SYMBOL",
      "exchange": "NSE",
      "product": "CNC | MIS",
      "quantity": <integer>,
      "order_type": "LIMIT | MARKET | SL",
      "price": <number>,
      "stop_loss": <number>,
      "target": <number>,
      "confidence": <float between 0.0 and 1.0>,
      "timeframe": "INTRADAY | SWING",
      "max_hold_days": <integer, only for CNC>,
      "time_exit_plan": "What to do if target/SL not hit by max_hold_days",
      "reasoning": "Detailed reasoning: what setup you see, why now, what
                    could go wrong, risk-reward ratio, and your exit plan."
    }
  ],
  "position_actions": [
    {
      "symbol": "SYMBOL",
      "current_action": "HOLD | TRAIL_SL | BOOK_PARTIAL | EXIT",
      "new_stop_loss": <number or null>,
      "reasoning": "Why this action for this existing position"
    }
  ],
  "watchlist_notes": "Any stocks from this batch you want to keep watching
                      but aren't ready to trade yet, and what trigger would
                      make them actionable.",
  "portfolio_notes": "Any overall portfolio observations, risk commentary, or
                      strategy adjustments."
}

IMPORTANT:
- If there are no trades to make, return an empty decisions array and explain
  why in market_assessment.reasoning.
- Always include position_actions for EVERY existing position (even if HOLD).
- Confidence below 0.5 = do not trade. Only suggest trades with confidence >= 0.5.
- Be specific with prices — use actual price levels, not vague suggestions.
```


---

## 11. USER PROMPT TEMPLATES

There are now TWO user prompt templates corresponding to the two-stage
decision pipeline:

### 11A. MARKET PULSE PROMPT (sent to Sonnet, every 30 min)

This is the compact market dashboard. Claude scans this and tells us which
stocks to fetch deep data for.

```
call_type: MARKET_PULSE

══════════════════════════════════════════════════════════
EXPERIMENT STATUS
══════════════════════════════════════════════════════════
Day {day_number} of 30 | Trading days remaining: {trading_days_left}
Phase: {NORMAL | UNWIND_PHASE}
Rule reminder: {if unwind phase: "No new CNC positions. Unwind existing holdings."}

══════════════════════════════════════════════════════════
MARKET OVERVIEW
══════════════════════════════════════════════════════════
Timestamp: {YYYY-MM-DD HH:MM:SS} IST
Market Status: {OPEN | PRE_MARKET | CLOSED}

--- INDICES ---
NIFTY 50:       {price} ({change_pct}%)  | Day range: {low} – {high}
BANK NIFTY:     {price} ({change_pct}%)  | Day range: {low} – {high}
NIFTY IT:       {price} ({change_pct}%)
NIFTY PHARMA:   {price} ({change_pct}%)
NIFTY AUTO:     {price} ({change_pct}%)
NIFTY METAL:    {price} ({change_pct}%)
NIFTY REALTY:   {price} ({change_pct}%)
NIFTY ENERGY:   {price} ({change_pct}%)
NIFTY PSU BANK: {price} ({change_pct}%)
INDIA VIX:      {value} ({change_pct}%)

[SOURCE: Kite Connect → kite.quote("NSE:NIFTY 50", "NSE:NIFTY BANK", ...)]

--- MARKET BREADTH ---
Advances: {count} | Declines: {count} | Unchanged: {count}
Advance-Decline Ratio: {ratio}

--- SECTOR HEATMAP (ranked by % change) ---
  1. {sector_name}: {change_pct}%
  2. {sector_name}: {change_pct}%
  ... (all sectors)

[SOURCE: Sector index quotes from Kite Connect, sorted by performance]

--- TOP 10 GAINERS ---
┌──────────────┬──────────┬──────────┬───────────────┬────────────┐
│ Symbol       │  CMP     │ Change % │ Vol vs 20d Avg│ Sector     │
├──────────────┼──────────┼──────────┼───────────────┼────────────┤
│ {symbol}     │ ₹{cmp}   │ +{pct}%  │ {ratio}x      │ {sector}   │
│ ...          │          │          │               │            │
└──────────────┴──────────┴──────────┴───────────────┴────────────┘

[SOURCE: Computed from live Kite quotes for entire eligible universe]

--- TOP 10 LOSERS ---
┌──────────────┬──────────┬──────────┬───────────────┬────────────┐
│ Symbol       │  CMP     │ Change % │ Vol vs 20d Avg│ Sector     │
├──────────────┼──────────┼──────────┼───────────────┼────────────┤
│ {symbol}     │ ₹{cmp}   │ -{pct}%  │ {ratio}x      │ {sector}   │
│ ...          │          │          │               │            │
└──────────────┴──────────┴──────────┴───────────────┴────────────┘

--- TOP 10 VOLUME SURGES ---
┌──────────────┬──────────┬──────────┬───────────────┬────────────┐
│ Symbol       │  CMP     │ Change % │ Vol vs 20d Avg│ Sector     │
├──────────────┼──────────┼──────────┼───────────────┼────────────┤
│ {symbol}     │ ₹{cmp}   │ {pct}%   │ {ratio}x      │ {sector}   │
│ ...          │          │          │               │            │
└──────────────┴──────────┴──────────┴───────────────┴────────────┘

[SOURCE: Volume ratio computed from Kite historical 20-day avg vs today]

--- 52-WEEK EXTREMES ---
Near 52-week highs (within 2%): {SYMBOL1} (₹{cmp}, {pct}% from high), {SYMBOL2}, ...
Near 52-week lows (within 2%):  {SYMBOL1} (₹{cmp}, {pct}% from low), {SYMBOL2}, ...

--- GAP STOCKS (> 2% gap at open) ---
Gap up:   {SYMBOL1} (+{pct}%), {SYMBOL2} (+{pct}%), ...
Gap down: {SYMBOL1} (-{pct}%), {SYMBOL2} (-{pct}%), ...

[SOURCE: Computed from today's open vs previous close]

--- MACRO CONTEXT ---
FII today: {sign}{amount} Cr ({net_buy/net_sell})
DII today: {sign}{amount} Cr ({net_buy/net_sell})
USD/INR: {rate} ({change_pct}%)
Brent Crude: ${price} ({change_pct}%)
Gold (MCX): ₹{price}/10g ({change_pct}%)

--- GLOBAL CUES ---
US S&P 500 (prev close): {price} ({change_pct}%)
Dow Jones: {price} ({change_pct}%)
Nasdaq: {price} ({change_pct}%)
SGX Nifty (pre-market): {price} ({change_pct}%)

--- TOP NEWS HEADLINES ---
- [{timestamp}] {headline summary — 1 sentence}
- [{timestamp}] {headline summary — 1 sentence}
- ... (5-10 most impactful headlines)

[SOURCE: RSS feeds summarized by Haiku. Only the most market-relevant headlines.]

--- ETF SNAPSHOT ---
┌─────────────┬────────┬──────────┬────────┐
│ ETF         │  CMP   │ Change % │ Vol    │
├─────────────┼────────┼──────────┼────────┤
│ NIFTYBEES   │ {cmp}  │ {pct}%   │ {vol}  │
│ BANKBEES    │ {cmp}  │ {pct}%   │ {vol}  │
│ GOLDBEES    │ {cmp}  │ {pct}%   │ {vol}  │
│ ITBEES      │ {cmp}  │ {pct}%   │ {vol}  │
│ PSUBNKBEES  │ {cmp}  │ {pct}%   │ {vol}  │
└─────────────┴────────┴──────────┴────────┘

══════════════════════════════════════════════════════════
YOUR PORTFOLIO (brief)
══════════════════════════════════════════════════════════
Capital: ₹{total_capital} | Cash: ₹{cash} ({cash_pct}%) | Deployed: ₹{deployed} ({deployed_pct}%)
Today's P&L: {sign}₹{amount} ({pct}%) | Cumulative: {sign}₹{amount} ({pct}%)
Trades today: {count} of {max_trades} max

Current holdings: {SYMBOL1} ({pnl_pct}%), {SYMBOL2} ({pnl_pct}%), ... or NONE
Open MIS: {SYMBOL1} ({side}, {pnl_pct}%), ... or NONE

══════════════════════════════════════════════════════════
PREVIOUS WATCHLIST (from your last Market Pulse call)
══════════════════════════════════════════════════════════
{SYMBOL1}, {SYMBOL2}, {SYMBOL3}, ... or "First call of the day — no previous watchlist"

══════════════════════════════════════════════════════════
CORPORATE ACTIONS TODAY
══════════════════════════════════════════════════════════
{SYMBOL}: {action_type} (ex-date today — price movement is adjustment, not organic)
... or "None affecting eligible universe today"

══════════════════════════════════════════════════════════
CURRENT TIME: {HH:MM} IST | MARKET {CLOSES IN X HOURS / IS CLOSED}
EXPERIMENT DAY: {N} of 30 | TRADING DAYS LEFT: {M}
══════════════════════════════════════════════════════════

Scan the market data above. Select 8-15 stocks (or ETFs) you want full data
on for trading analysis. You MUST include all stocks you currently hold in
your selections. Respond with JSON in the MARKET_PULSE format.
```

### 11B. TRADING DECISION PROMPT (sent to Opus, every 30 min after Pulse)

This prompt contains FULL data for the stocks Claude selected in the Market
Pulse call. Format is the same as the original spec's candidate stock section.

```
call_type: TRADING_DECISION

══════════════════════════════════════════════════════════
EXPERIMENT STATUS
══════════════════════════════════════════════════════════
Day {day_number} of 30 | Trading days remaining: {trading_days_left}
Phase: {NORMAL | UNWIND_PHASE}
Rule reminder: {if unwind phase: "No new CNC positions. Unwind existing holdings."}

[SOURCE: Computed → (current_date - experiment_start_date).days]

══════════════════════════════════════════════════════════
MARKET OVERVIEW
══════════════════════════════════════════════════════════
Timestamp: {YYYY-MM-DD HH:MM:SS} IST
Market Status: {OPEN | PRE_MARKET | CLOSED}

--- INDICES ---
NIFTY 50:       {price} ({change_pct}%)  | Day range: {low} – {high}
BANK NIFTY:     {price} ({change_pct}%)  | Day range: {low} – {high}
NIFTY IT:       {price} ({change_pct}%)
NIFTY PHARMA:   {price} ({change_pct}%)
NIFTY AUTO:     {price} ({change_pct}%)
NIFTY METAL:    {price} ({change_pct}%)
NIFTY REALTY:   {price} ({change_pct}%)
NIFTY ENERGY:   {price} ({change_pct}%)
NIFTY PSU BANK: {price} ({change_pct}%)
INDIA VIX:      {value} ({change_pct}%)

--- MARKET BREADTH ---
Advances: {count} | Declines: {count} | Unchanged: {count}
Advance-Decline Ratio: {ratio}

--- MACRO CONTEXT ---
FII today: {sign}{amount} Cr ({net_buy/net_sell})
DII today: {sign}{amount} Cr ({net_buy/net_sell})
USD/INR: {rate} ({change_pct}%)
Brent Crude: ${price} ({change_pct}%)
Gold (MCX): ₹{price}/10g ({change_pct}%)
India 10Y Bond Yield: {yield}%

--- GLOBAL CUES ---
US S&P 500 (prev close): {price} ({change_pct}%)
Dow Jones: {price} ({change_pct}%)
Nasdaq: {price} ({change_pct}%)
SGX Nifty (pre-market): {price} ({change_pct}%)

--- KEY EVENTS TODAY ---
{list of relevant events: RBI meeting, US Fed minutes, earnings releases, etc.}

══════════════════════════════════════════════════════════
PORTFOLIO STATE
══════════════════════════════════════════════════════════

Capital: ₹{total_capital}
Cash available: ₹{cash}
Deployed: ₹{deployed} ({deployed_pct}%)
Max deployable (80% rule): ₹{max_deploy}
Remaining deployable: ₹{remaining_deploy}

--- TODAY'S P&L ---
Realized P&L:    {sign}₹{amount}
Unrealized P&L:  {sign}₹{amount}
Total P&L:       {sign}₹{amount} ({pct}%)
Daily loss limit: ₹{limit} | Remaining: ₹{remaining}
Trades today: {count} of {max_trades} max

--- CUMULATIVE P&L (experiment to date) ---
Total realized P&L: {sign}₹{amount} ({pct}% of starting capital)
Current portfolio value: ₹{value}
Starting capital: ₹{starting}
Overall return: {pct}%

--- CNC HOLDINGS (delivery / swing trades) ---
┌──────────┬─────┬──────────┬────────┬────────┬─────────┬──────┬────────────┐
│ Symbol   │ Qty │ Avg Cost │  CMP   │  P&L   │  P&L %  │ Days │ Current SL │
├──────────┼─────┼──────────┼────────┼────────┼─────────┼──────┼────────────┤
│ {symbol} │ {q} │ {avg}    │ {cmp}  │ {pnl}  │ {pct}%  │ {d}  │ {sl}       │
└──────────┴─────┴──────────┴────────┴────────┴─────────┴──────┴────────────┘

--- MIS POSITIONS (intraday) ---
┌──────────┬──────┬─────┬────────┬────────┬───────┬────────┬────────┐
│ Symbol   │ Side │ Qty │ Entry  │  CMP   │  P&L  │   SL   │ Target │
├──────────┼──────┼─────┼────────┼────────┼───────┼────────┼────────┤
│ {symbol} │ {s}  │ {q} │ {ent}  │ {cmp}  │ {pnl} │ {sl}   │ {tgt}  │
└──────────┴──────┴─────┴────────┴────────┴───────┴────────┴────────┘

══════════════════════════════════════════════════════════
YOUR WATCHLIST SELECTIONS (from Market Pulse)
══════════════════════════════════════════════════════════
You requested deep data on these stocks. Your reasoning at selection time:
{SYMBOL1}: "{reason from Market Pulse response}"
{SYMBOL2}: "{reason from Market Pulse response}"
... (for each selected stock)

══════════════════════════════════════════════════════════
DEEP DIVE: STOCK DATA
══════════════════════════════════════════════════════════

--- STOCK {N}: {SYMBOL} ({EXCHANGE}) ---

Your selection reason: "{reason from Market Pulse}"

Price Data:
  CMP: ₹{cmp} | Day change: {sign}{pct}% ({sign}₹{abs_change})
  Today OHLC: {open} / {high} / {low} / {close}
  52-week range: ₹{low_52w} – ₹{high_52w}
  Avg daily volume (20d): ₹{vol_avg} Cr | Today: ₹{vol_today} Cr ({vol_ratio}x)

Daily Candles (last 15 sessions, newest first):
  Date       | Open   | High   | Low    | Close  | Vol(₹Cr)
  {date_1}   | {o}    | {h}    | {l}    | {c}    | {v}
  ... (15 rows total)

Intraday 15-min Candles (today):
  Time  | Open   | High   | Low    | Close  | Vol(Lakhs)
  09:15 | {o}    | {h}    | {l}    | {c}    | {v}
  ... (all candles up to current time)

Technical Indicators:
  RSI(14):            {value}
  MACD(12,26,9):      Signal={bullish_crossover/bearish_crossover/neutral}
  MACD Histogram:     {value} ({expanding/contracting})
  SMA 20:             ₹{value} (price {above/below})
  SMA 50:             ₹{value} (price {above/below})
  SMA 200:            ₹{value} (price {above/below})
  EMA 9:              ₹{value} (price {above/below})
  VWAP (today):       ₹{value} (price {above/below})
  Bollinger Bands:    Upper=₹{u} | Mid=₹{m} | Lower=₹{l}
  ADX(14):            {value}
  ATR(14):            ₹{value}
  Volume SMA(20):     ₹{value} Cr (today is {ratio}x)
  Supertrend(10,3):   {BUY/SELL signal} at ₹{level}

Key Levels (auto-computed):
  Resistance 1: ₹{r1}
  Resistance 2: ₹{r2}
  Support 1:    ₹{s1}
  Support 2:    ₹{s2}
  Pivot Point:  ₹{pp}

Candlestick Patterns Detected (last 5 sessions):
  - {date}: {pattern_name}
  - {date}: {pattern_name}

News & Catalysts:
  - [{date}] "{headline summary — 1-2 sentences}"
  - [{date}] "{headline summary}"

Sector Context:
  Sector: {sector_name}
  Sector index: {index_name} {change_pct}% today
  Peer performance: {PEER1} {pct}%, {PEER2} {pct}%, {PEER3} {pct}%

--- (REPEAT FOR EACH STOCK IN WATCHLIST, typically 8-15 stocks) ---

══════════════════════════════════════════════════════════
ETF SNAPSHOT
══════════════════════════════════════════════════════════
┌─────────────┬────────┬──────────┬────────┐
│ ETF         │  CMP   │ Change % │ Vol    │
├─────────────┼────────┼──────────┼────────┤
│ NIFTYBEES   │ {cmp}  │ {pct}%   │ {vol}  │
│ BANKBEES    │ {cmp}  │ {pct}%   │ {vol}  │
│ GOLDBEES    │ {cmp}  │ {pct}%   │ {vol}  │
│ ITBEES      │ {cmp}  │ {pct}%   │ {vol}  │
│ PSUBNKBEES  │ {cmp}  │ {pct}%   │ {vol}  │
└─────────────┴────────┴──────────┴────────┘

══════════════════════════════════════════════════════════
EXISTING POSITION UPDATES
══════════════════════════════════════════════════════════

Review each existing position and recommend: HOLD, TRAIL_SL, BOOK_PARTIAL, or EXIT.

{SYMBOL} (CNC, held {N} days, max hold: {M} days):
  Entry: ₹{entry} | CMP: ₹{cmp} | P&L: {pct}%
  Current SL: ₹{sl} | Original target: ₹{target}
  RSI: {val} | Trend: {above/below key MAs}
  Recent news: {any new developments}
  Time remaining: {M - N} days before time-based exit

... (repeat for each existing position)

══════════════════════════════════════════════════════════
PERFORMANCE CONTEXT (rolling 5-day summary)
══════════════════════════════════════════════════════════

Total trades: {N} | Wins: {W} | Losses: {L} | Breakeven: {B}
Win rate: {pct}%
Average win: ₹{avg_win} | Average loss: ₹{avg_loss}
Profit factor: {total_wins / total_losses}x
Largest win: ₹{amount} ({symbol}, {strategy})
Largest loss: ₹{amount} ({symbol}, {strategy})
Best performing strategy: {description}
Worst performing strategy: {description}
Best performing sector: {sector}
Net P&L (5 days): {sign}₹{amount} ({pct}%)
Cumulative P&L (experiment): {sign}₹{amount} ({pct}%)

══════════════════════════════════════════════════════════
CURRENT TIME: {HH:MM} IST | MARKET {CLOSES IN X HOURS / IS CLOSED}
EXPERIMENT DAY: {N} of 30 | TRADING DAYS LEFT: {M}
══════════════════════════════════════════════════════════

Analyze all data above and provide your trading decisions in the required
JSON format. Remember: quality over quantity. NO_ACTION is always valid.
Capital preservation is priority #1.
```


---

## 12. API COST OPTIMIZATION — TIERED MODEL APPROACH

Do NOT use Opus for everything. Use a tiered approach to minimize costs.

### Model Usage Strategy

| Task | Model | Why | Approx Cost/Call |
|---|---|---|---|
| News headline summarization | Haiku 4.5 | Cheap, fast, good enough for summarization | ~₹0.20 |
| Market Pulse (watchlist selection) | Sonnet 4.5 | Balanced — can scan market data and select watchlist | ~₹3-8 |
| Pre-market strategy brief | Opus 4.6 | Needs deep reasoning for day planning | ~₹15-25 |
| Trading decisions (main loop) | Opus 4.6 | Critical — needs best judgment | ~₹30-60 |
| End-of-day review | Opus 4.6 | Consistent reasoning quality; avoids info leak from mixing models | ~₹15-25 |

### Estimated Daily API Costs

| Model | Calls/Day | Tokens/Call (in+out) | Daily Cost |
|---|---|---|---|
| Haiku 4.5 (news) | ~20 | ~2K each | ₹5-10 |
| Sonnet 4.5 (Market Pulse) | ~10-12 | ~4K each | ₹30-95 |
| Opus 4.6 (decisions + EOD) | ~9-11 | ~8K each | ₹275-550 |
| **Total** | | | **₹310-655/day** |
| **Monthly estimate** | | | **₹6,800-14,400** |

### Token Usage Breakdown

**Per Market Pulse call (Sonnet):**

| Section | Input Tokens (approx.) |
|---|---|
| System prompt | ~1,200 |
| Market overview + sector heatmap | ~400 |
| Top movers + volume surges | ~500 |
| 52-week extremes + gaps | ~200 |
| Macro + global cues + news | ~400 |
| ETF snapshot | ~100 |
| Portfolio brief + previous watchlist | ~200 |
| **Total input** | **~3,000** |
| **Expected output** (watchlist JSON) | **~500-800** |

**Per Trading Decision call (Opus):**

| Section | Input Tokens (approx.) |
|---|---|
| System prompt | ~1,200 |
| Market overview + macro | ~300 |
| Portfolio state | ~250 |
| Per stock (candles + indicators + news) × 10 | ~5,000 |
| Watchlist context (selection reasons) | ~200 |
| ETF snapshot | ~150 |
| Existing position updates | ~300 |
| Performance context | ~150 |
| **Total input** | **~7,550** |
| **Expected output** (JSON response) | **~800-1,500** |

### Cost Reduction Tips
- Use prompt caching (Anthropic supports this) — the system prompt is identical
  every call, so it can be cached
- Reduce Market Pulse frequency from 30 min to 45-60 min
- Use Sonnet instead of Opus for midday trading decisions (configurable)
- Send 10 daily candles instead of 15
- Run Market Pulse only when market conditions change significantly (detect
  via VIX spike or index movement threshold)


---

## 13. DAILY SCHEDULE & WORKFLOW

All times in IST. The orchestrator runs these steps automatically.

### Pre-Market Phase (8:30 AM – 9:15 AM)

| Time | Action | Details |
|---|---|---|
| 8:30 AM | **System startup** | Re-authenticate Kite (daily token refresh). Load config. |
| 8:30 AM | **Universe filter** | Download NSE instruments, filter ASM/GSM, build tradeable universe (~400 stocks). |
| 8:32 AM | **Corporate actions check** | Fetch corporate actions calendar (BSE API). Flag ex-date stocks. (Section 15E) |
| 8:33 AM | **Data infrastructure boot** | Begin bulk data collection for entire universe: fetch daily candles, compute all indicators, cache in memory. |
| 8:35 AM | **Fetch pre-market data** | Global cues (US close, SGX Nifty), FII/DII (previous day), overnight news. |
| 8:40 AM | **News scan** | Fetch RSS feeds for top news. Summarize with Haiku. Identify market-moving headlines. |
| 8:45 AM | **Pre-market Market Pulse (SONNET)** | Send pre-market dashboard to Sonnet. Claude scans overnight developments, global cues, and pre-market data. Returns initial watchlist of 10-15 stocks to monitor. |
| 8:50 AM | **Deep dive data prep** | Fetch full data for Claude's watchlist selections (indicators already computed in bulk). |
| 9:00 AM | **Pre-market strategy call (OPUS)** | Send deep dive data to Opus. Claude sets day's bias, outlines strategy, and may place pre-market CNC orders. |
| 9:00-9:15 AM | **WebSocket setup** | Subscribe to live ticks for watchlist stocks + indices + ETFs. |

### Market Hours Phase (9:15 AM – 3:30 PM)

| Time | Action | Details |
|---|---|---|
| 9:15 AM | **Market opens** | WebSocket starts receiving live ticks. Data infrastructure begins updating intraday candles. |
| 9:20 AM | **Opening data refresh** | Update all indicators with opening 5 minutes of data. Recompute top movers, volume surges, gaps. |
| 9:22 AM | **First Market Pulse (SONNET)** | Send updated market dashboard. Claude reviews opening action and may adjust watchlist. |
| 9:25 AM | **Deep dive data prep** | Assemble full data for Claude's (possibly updated) watchlist. |
| 9:27 AM | **First trading call (OPUS)** | Send full prompt with opening data. First actionable trading decisions. |
| Every 30 min | **Market Pulse cycle** | **Step 1:** Refresh bulk data (quotes, indicators, movers). **Step 2:** Send Market Pulse to Sonnet — Claude reviews market and updates watchlist. **Step 3:** Assemble deep dive data for watchlist. **Step 4:** Send to Opus for trading decisions. |
| Ongoing | **Data infrastructure** | Continuous: update quotes via WebSocket, recompute intraday indicators every 15 min, aggregate sector performance, detect new volume surges and movers. |
| Ongoing | **SL & Target health check** | Every 5 min: verify broker-side SL and target orders exist for all open positions. Re-place if missing. (Section 15F) |
| Ongoing | **Order reconciliation** | Track all placed orders. Verify fills via kite.order_history(). Update local DB. Handle REJECTED/CANCELLED. Reserve cash for PENDING orders. (Section 15D) |
| 2:30 PM | **Last MIS entry cutoff** | No new intraday (MIS) positions after this time. |
| 2:30 PM | **Afternoon review (OPUS)** | Final decision call. Focus on: close MIS positions? Any last swing entries? |
| 3:00 PM | **MIS square-off begins** | Bot places exit orders for ALL open MIS positions. |
| 3:05 PM | **MIS fill check** | Check if all MIS exit orders are filled. Re-place unfilled orders at revised prices. |
| 3:10 PM | **MIS HARD DEADLINE** | All MIS must be closed by now. If any remain open, place MARKET orders immediately. |
| 3:12 PM | **Emergency MIS check** | Final verification. If anything is still open, send Telegram alert + force MARKET close. |

### Post-Market Phase (3:30 PM – 4:00 PM)

| Time | Action | Details |
|---|---|---|
| 3:30 PM | **Market closes** | Final prices locked. |
| 3:35 PM | **EOD data collection** | Fetch final positions, holdings, day P&L, order history. |
| 3:40 PM | **EOD review (OPUS)** | Claude Opus reviews the day: what worked, what didn't, lessons learned. Includes review of watchlist selection quality — were the right stocks chosen? Stored in log. |
| 3:45 PM | **Performance update** | Update local DB with all trade results. Compute daily/cumulative metrics. |
| 3:47 PM | **LLM cost summary** | Rebuild `llm_daily_costs` table for today. Append to `costs_daily.csv`. Compare AI cost vs trading P&L. |
| 3:50 PM | **Daily summary notification** | Send Telegram message: P&L, trades executed, cumulative performance, watchlist hit rate, today's LLM cost. |
| 4:00 PM | **Daily backup** | Back up logs/, database, and config. (Section 16.6) |
| 4:05 PM | **System sleep** | Shut down WebSocket, archive logs, go idle until next morning. |

### Weekly Review (Weekend)

- Aggregate weekly performance metrics
- Analyze watchlist selection quality: did Claude pick the right stocks to focus on?
- Identify best/worst performing strategies
- Optional: adjust system prompt if Claude is consistently making certain errors
- Review guardrail trigger logs

---

## 14. PAPER TRADING MODE

Zerodha does NOT offer paper trading. Instead, build paper trading directly into
the bot with a mode flag.

### CRITICAL RULE: Claude Must NEVER Know the Trading Mode

Claude must always believe it is trading with real money. The system prompt and
user prompt must be IDENTICAL in both PAPER and LIVE modes. This is non-negotiable.

**Why?** If Claude knows it's paper trading, it may:
- Take riskier bets ("it's not real money anyway")
- Be less disciplined with stop-losses
- Over-trade to "test theories"
- Not treat capital preservation seriously

**How to enforce this:**
- The `mode` flag (`PAPER` / `LIVE`) exists ONLY in the execution engine config
- The `mode` value must NEVER appear in any Claude prompt — not in the system
  prompt, not in the user prompt, not in portfolio state, not anywhere
- The prompt builder has ZERO knowledge of the mode — it builds the same prompt
  regardless
- The mode flag is checked ONLY at the final execution step: order goes to Kite
  (LIVE) or local DB (PAPER)
- Even the portfolio state fed to Claude should look identical — paper trading
  engine must simulate realistic holdings, positions, P&L, and cash balances
- Brokerage deductions (₹20/intraday) should be simulated in paper mode so the
  P&L Claude sees is realistic
- Slippage simulation should be applied in paper mode (e.g., 0.05% adverse fill)
  so Claude doesn't see unrealistically clean execution

**Architecture for mode blindness:**
```
Prompt Builder ──→ Claude ──→ Guardrails ──→ Execution Engine
       │                                          │
       │ (identical prompt                        │ (ONLY place where
       │  regardless of mode)                     │  mode is checked)
       │                                          │
       │                                    ┌─────┴─────┐
       │                                    │           │
       │                                  PAPER       LIVE
       │                                    │           │
       │                                Local DB    Kite API
       │                                    │           │
       └────────────────────────────────────┴───────────┘
                                    │
                        Portfolio State Manager
                    (provides same interface to prompt
                     builder regardless of mode)
```

**The Portfolio State Manager** is the key abstraction. It exposes methods like:
- `get_holdings()` → returns holdings (from Kite in LIVE, from local DB in PAPER)
- `get_positions()` → returns positions (from Kite in LIVE, from local DB in PAPER)
- `get_margins()` → returns cash available (from Kite in LIVE, from local DB in PAPER)
- `get_daily_pnl()` → returns P&L (from Kite in LIVE, from local DB in PAPER)

The prompt builder calls these methods without knowing or caring about the mode.
Claude sees identical data structures in both modes.

### Implementation

```python
# config.yaml
trading:
  mode: "PAPER"  # Options: "PAPER" or "LIVE"
  # This value is NEVER exposed to Claude. Only the execution engine reads it.

# In execution engine:
class ExecutionEngine:
    def __init__(self, kite, config, db):
        self.kite = kite
        self.mode = config["trading"]["mode"]
        self.db = db

    def execute_order(self, order):
        if self.mode == "PAPER":
            return self._paper_execute(order)
        elif self.mode == "LIVE":
            return self._live_execute(order)

    def _paper_execute(self, order):
        """Simulate order execution with realistic conditions."""
        # Get current live price from Kite (we still use real market data)
        quote = self.kite.quote(f"{order['exchange']}:{order['symbol']}")
        ltp = quote[f"{order['exchange']}:{order['symbol']}"]["last_price"]

        # Simulate fill with realistic slippage
        if order["order_type"] == "MARKET":
            # Apply 0.05% adverse slippage for MARKET orders
            if order["transaction_type"] == "BUY":
                fill_price = round(ltp * 1.0005, 2)  # slightly worse for buyer
            else:
                fill_price = round(ltp * 0.9995, 2)  # slightly worse for seller
        elif order["order_type"] == "LIMIT":
            # LIMIT BUY fills if LTP <= limit price
            if order["transaction_type"] == "BUY" and ltp <= order["price"]:
                fill_price = order["price"]
            # LIMIT SELL fills if LTP >= limit price
            elif order["transaction_type"] == "SELL" and ltp >= order["price"]:
                fill_price = order["price"]
            else:
                fill_price = None  # Order pending
        elif order["order_type"] == "SL":
            # SL order: triggers when LTP hits trigger_price, fills at limit
            fill_price = None  # SL orders are tracked separately

        if fill_price:
            paper_order_id = generate_paper_order_id()

            # Simulate brokerage deduction
            brokerage = 0
            if order["product"] == "MIS":
                brokerage = 20  # ₹20 per intraday trade (Zerodha flat fee)

            # Log to database as if it were a real fill
            self.db.log_paper_trade({
                "order_id": paper_order_id,
                "symbol": order["symbol"],
                "exchange": order["exchange"],
                "transaction_type": order["transaction_type"],
                "quantity": order["quantity"],
                "price": fill_price,
                "product": order["product"],
                "status": "COMPLETE",
                "brokerage": brokerage,
                "timestamp": datetime.now(),
            })

            # Update paper portfolio state
            self.db.update_paper_portfolio(order, fill_price, brokerage)

            return {"order_id": paper_order_id, "status": "COMPLETE"}
        else:
            return {"order_id": generate_paper_order_id(), "status": "OPEN"}

    def _live_execute(self, order):
        """Execute real order via Kite Connect."""
        return self.kite.place_order(
            variety=self.kite.VARIETY_REGULAR,
            exchange=order["exchange"],
            tradingsymbol=order["symbol"],
            transaction_type=order["transaction_type"],
            quantity=order["quantity"],
            product=order["product"],
            order_type=order["order_type"],
            price=order.get("price"),
            trigger_price=order.get("trigger_price"),
            validity=self.kite.VALIDITY_DAY
        )
```

### Mode-Blind Portfolio State Manager

This is the critical abstraction that keeps Claude unaware of the trading mode.

```python
class PortfolioStateManager:
    """
    Provides a unified interface to portfolio data regardless of mode.
    The prompt builder ONLY interacts with this class — never with Kite
    or the paper DB directly.
    
    CRITICAL: This class NEVER exposes the mode to callers.
    """

    def __init__(self, kite, db, config):
        self.kite = kite
        self.db = db
        self.mode = config["trading"]["mode"]  # internal only

    def get_holdings(self) -> list:
        """Returns CNC holdings. Identical format in both modes."""
        if self.mode == "LIVE":
            return self.kite.holdings()
        else:
            return self.db.get_paper_holdings()

    def get_positions(self) -> dict:
        """Returns open positions. Identical format in both modes."""
        if self.mode == "LIVE":
            return self.kite.positions()
        else:
            return self.db.get_paper_positions()

    def get_available_cash(self) -> float:
        """Returns available cash for trading."""
        if self.mode == "LIVE":
            margins = self.kite.margins()
            return margins["equity"]["available"]["cash"]
        else:
            return self.db.get_paper_cash()

    def get_daily_pnl(self) -> dict:
        """Returns today's P&L breakdown."""
        if self.mode == "LIVE":
            positions = self.kite.positions()
            realized = sum(p["realised"] for p in positions["day"])
            unrealized = sum(p["unrealised"] for p in positions["day"])
            return {"realized": realized, "unrealized": unrealized}
        else:
            return self.db.get_paper_daily_pnl()

    def total_value(self) -> float:
        """Returns total portfolio value (cash + holdings value)."""
        if self.mode == "LIVE":
            cash = self.get_available_cash()
            holdings_value = sum(
                h["last_price"] * h["quantity"]
                for h in self.kite.holdings()
            )
            return cash + holdings_value
        else:
            return self.db.get_paper_total_value()

    def trades_today_count(self) -> int:
        """Returns number of trades placed today."""
        # Always from local DB — both modes log trades there
        return self.db.count_trades_today()
```

### Paper Portfolio Simulation Details

The paper trading DB must track:
- **Paper holdings**: symbol, quantity, avg_price (updated on each BUY/SELL)
- **Paper positions**: open MIS trades with entry price, quantity, side
- **Paper cash**: starts at `starting_capital`, decremented on BUY, incremented on SELL
- **Paper brokerage**: ₹20 deducted per MIS trade (entry + exit = ₹40 round trip)
- **Paper slippage**: 0.05% adverse fill on MARKET orders
- **Paper STT/charges**: optionally simulate (STT, transaction charges, GST) for
  maximum realism — or skip for simplicity

The paper portfolio must produce data in the **exact same format** as
`kite.holdings()`, `kite.positions()`, and `kite.margins()` so the prompt
builder cannot distinguish between modes.

### Paper Trading Benefits
- Entire pipeline runs identically: data fetching, Claude analysis, guardrails, order logic
- Claude has ZERO awareness of the mode — it always trades as if real money is at stake
- Still needs Kite Connect subscription (₹2,000/month) for real market data
- No real capital at risk during testing phase
- Realistic simulation: slippage, brokerage deductions, same portfolio data format
- When ready to go live: change `mode: "PAPER"` to `mode: "LIVE"` — one config change
- All logs (CSV trade logs, guardrail logs, Claude decision logs) are generated
  identically in both modes — the `mode` column in CSVs is for YOUR reference only,
  never fed back to Claude

### Paper Trading Portfolio Tracking
The paper trading engine maintains its own portfolio state in the local DB,
accessed through the PortfolioStateManager (see above). Key points:
- Track paper holdings (quantity, avg price) in local DB
- Compute paper P&L from simulated fills (with slippage applied)
- Deduct simulated brokerage (₹20/intraday trade, 0 for delivery)
- The PortfolioStateManager feeds this data to the prompt builder in the EXACT
  same format as Kite API responses — Claude cannot tell the difference
- SL order monitoring must be simulated: a background task checks if LTP has
  hit any paper SL trigger prices, and if so, simulates the fill

---

## 15. GUARDRAIL VALIDATION ENGINE

Every decision from Claude is validated by this engine BEFORE execution.
This is the most safety-critical component.

### Implementation

```python
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, time

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str]
    warnings: List[str]

class GuardrailEngine:
    def __init__(self, config, portfolio, kite):
        self.config = config
        self.portfolio = portfolio
        self.kite = kite

    def validate_order(self, order: dict) -> ValidationResult:
        errors = []
        warnings = []

        # --- INSTRUMENT CHECKS ---
        if order.get("instrument_type", "EQ") != "EQ":
            errors.append(f"BLOCKED: Only equity (EQ) allowed. Got: {order.get('instrument_type')}")

        if order.get("exchange") not in ["NSE", "BSE"]:
            errors.append(f"BLOCKED: Exchange must be NSE or BSE. Got: {order.get('exchange')}")

        if order.get("product") not in ["CNC", "MIS"]:
            errors.append(f"BLOCKED: Product must be CNC or MIS. Got: {order.get('product')}")

        # --- VALIDATE SYMBOL EXISTS ---
        valid_symbols = self.get_valid_symbols()
        if order["symbol"] not in valid_symbols:
            errors.append(f"BLOCKED: Symbol {order['symbol']} not found in instrument list")

        # --- ASM/GSM CHECK ---
        if order["symbol"] in self.config["asm_gsm_list"]:
            errors.append(f"BLOCKED: {order['symbol']} is on ASM/GSM list")

        # --- PRICE CHECK ---
        if order.get("price", 0) < 20 and order["order_type"] == "LIMIT":
            errors.append(f"BLOCKED: Stock price below ₹20 threshold")

        # --- SHORT SELLING CHECK ---
        if order["product"] == "CNC" and order["transaction_type"] == "SELL":
            current_holdings = self.portfolio.get_holdings_qty(order["symbol"])
            if current_holdings < order["quantity"]:
                errors.append(
                    f"BLOCKED: Cannot short-sell in CNC. "
                    f"Holdings: {current_holdings}, Order qty: {order['quantity']}"
                )

        # --- POSITION SIZING ---
        quote = self.kite.quote(f"{order['exchange']}:{order['symbol']}")
        ltp = quote[f"{order['exchange']}:{order['symbol']}"]["last_price"]
        position_value = ltp * order["quantity"]
        portfolio_value = self.portfolio.total_value()

        if position_value > portfolio_value * 0.20:
            errors.append(
                f"BLOCKED: Position value ₹{position_value:,.0f} exceeds "
                f"20% of portfolio (₹{portfolio_value * 0.20:,.0f})"
            )

        # --- CASH BUFFER CHECK ---
        cash = self.portfolio.available_cash()
        if order["transaction_type"] == "BUY":
            remaining_cash = cash - position_value
            min_cash = portfolio_value * 0.20
            if remaining_cash < min_cash:
                errors.append(
                    f"BLOCKED: Order would breach 20% cash buffer. "
                    f"Cash after: ₹{remaining_cash:,.0f}, Min: ₹{min_cash:,.0f}"
                )

        # --- DAILY LOSS LIMIT ---
        daily_loss = self.portfolio.daily_pnl()
        if daily_loss < -self.config["daily_loss_limit"]:
            errors.append(
                f"BLOCKED: Daily loss limit hit. "
                f"Current loss: ₹{abs(daily_loss):,.0f}, Limit: ₹{self.config['daily_loss_limit']:,.0f}"
            )

        # --- TRADE COUNT LIMIT ---
        trades_today = self.portfolio.trades_today_count()
        if trades_today >= self.config["max_trades_per_day"]:
            errors.append(
                f"BLOCKED: Max trades per day ({self.config['max_trades_per_day']}) reached"
            )

        # --- TIMING CHECKS ---
        now = datetime.now().time()
        if order["product"] == "MIS" and now > time(14, 30):
            errors.append("BLOCKED: No new MIS orders after 2:30 PM IST")

        if now < time(9, 15) or now > time(15, 30):
            errors.append("BLOCKED: Market is closed")

        # --- STOP-LOSS CHECK ---
        if "stop_loss" not in order or order["stop_loss"] is None:
            warnings.append(
                f"WARNING: No stop-loss specified. Applying default 2% SL."
            )
            # Auto-apply default SL
            if order["transaction_type"] == "BUY":
                order["stop_loss"] = round(order["price"] * 0.98, 2)
            else:
                order["stop_loss"] = round(order["price"] * 1.02, 2)

        # --- STOP-LOSS RANGE CHECK ---
        if order.get("stop_loss"):
            if order["transaction_type"] == "BUY":
                sl_pct = (order["price"] - order["stop_loss"]) / order["price"]
            else:
                sl_pct = (order["stop_loss"] - order["price"]) / order["price"]
            if sl_pct < 0.005:
                warnings.append(f"WARNING: SL too tight ({sl_pct:.1%}). Min 0.5%.")
            if sl_pct > 0.05:
                warnings.append(f"WARNING: SL too wide ({sl_pct:.1%}). Max 5%.")

        # --- EXPERIMENT PHASE CHECK ---
        trading_days_left = self.config["trading_days_remaining"]
        if trading_days_left <= 5 and order["product"] == "CNC" and order["transaction_type"] == "BUY":
            errors.append(
                f"BLOCKED: In unwind phase (last 5 trading days). "
                f"No new CNC positions allowed."
            )

        # --- CNC HOLD DURATION CHECK ---
        if order["product"] == "CNC" and order.get("max_hold_days", 0) > 15:
            warnings.append(
                f"WARNING: Max hold days ({order['max_hold_days']}) exceeds 15-day limit. "
                f"Capping at 15."
            )
            order["max_hold_days"] = 15

        # --- CONFIDENCE CHECK ---
        if order.get("confidence", 0) < 0.5:
            errors.append(
                f"BLOCKED: Confidence ({order['confidence']}) below 0.5 threshold"
            )
            # NOTE: LLM self-reported confidence scores are often uncalibrated.
            # During paper trading, track whether confidence scores actually
            # correlate with trade outcomes. If they don't, consider removing
            # this threshold or replacing it with objective criteria (e.g.,
            # R:R ratio + technical setup quality computed by code).

        # --- TARGET CHECK ---
        if "target" not in order or order["target"] is None:
            warnings.append(
                f"WARNING: No target specified. Applying default 3% target."
            )
            if order["transaction_type"] == "BUY":
                order["target"] = round(order["price"] * 1.03, 2)
            else:
                order["target"] = round(order["price"] * 0.97, 2)

        # --- CIRCUIT LIMIT CHECK ---
        if order["symbol"] in self.get_circuit_limit_stocks():
            circuit_info = self.get_circuit_limit_stocks()[order["symbol"]]
            if circuit_info["at_upper"] and order["transaction_type"] == "BUY":
                errors.append(
                    f"BLOCKED: {order['symbol']} is at upper circuit limit "
                    f"(₹{circuit_info['upper_limit']}). Buy orders unlikely to fill."
                )
            if circuit_info["at_lower"] and order["transaction_type"] == "SELL":
                errors.append(
                    f"BLOCKED: {order['symbol']} is at lower circuit limit "
                    f"(₹{circuit_info['lower_limit']}). Sell orders unlikely to fill."
                )

        # --- DUPLICATE ORDER CHECK ---
        recent_orders = self.portfolio.get_recent_orders(
            symbol=order["symbol"],
            side=order["transaction_type"],
            window_minutes=self.config.get("duplicate_order_window_min", 5)
        )
        if recent_orders:
            errors.append(
                f"BLOCKED: Duplicate order detected. {order['transaction_type']} "
                f"{order['symbol']} already placed {len(recent_orders)} time(s) "
                f"in the last {self.config.get('duplicate_order_window_min', 5)} min. "
                f"Use Kite order tag for idempotency."
            )

        # --- DRAWDOWN CHECK ---
        total_return_pct = self.portfolio.total_return_pct()
        if total_return_pct < -0.15:
            errors.append("BLOCKED: 15% drawdown breached. Trading halted.")
        elif total_return_pct < -0.10:
            if order["product"] == "CNC":
                errors.append("BLOCKED: 10% drawdown. CNC not allowed, intraday only.")
            order["quantity"] = order["quantity"] // 2  # halve position size
            warnings.append("WARNING: 10% drawdown. Position size halved.")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
```

## 15B. MIS AUTO-EXIT ENGINE

This is a critical module that ensures the bot ALWAYS closes MIS positions itself,
avoiding Zerodha's ₹50+GST auto-square-off penalty.

### Why This Matters
Zerodha auto-squares-off all MIS positions at 3:20 PM IST and charges ₹50 + 18%
GST = ₹59 per position. If Claude makes 5 intraday trades/day and they all hit
auto-square-off, that's ₹295/day wasted = ~₹6,500/month. This module eliminates
that cost entirely.

### 3-Stage Exit Process

**IMPORTANT**: Each stage runs as a separate APScheduler job, NOT as a blocking
`time.sleep()` chain. This ensures that if any stage crashes, subsequent stages
still execute independently.

```python
class MISAutoExitEngine:
    """
    Ensures all MIS positions are closed before Zerodha's auto-square-off.
    Each stage is scheduled as an independent cron job via APScheduler.
    
    Stage 1 (3:00 PM): Place LIMIT exit orders at LTP with small tolerance
    Stage 2 (3:05 PM): Cancel unfilled exits, re-place at revised LTP
    Stage 3 (3:10 PM): HARD DEADLINE — force MARKET orders for anything remaining
    Emergency (3:12 PM): Final check — if still open, MARKET + Telegram alert
    
    DESIGN: Each stage is an independent scheduled job. If Stage 1 crashes,
    Stage 2 still runs. If Stage 2 crashes, Stage 3 still runs. This is
    critical — a blocking time.sleep() chain would fail silently if any
    stage threw an exception, potentially leaving MIS positions open and
    triggering Zerodha's ₹50+GST auto-square-off penalty.
    """

    def __init__(self, kite, portfolio, config, notifier):
        self.kite = kite
        self.portfolio = portfolio
        self.config = config
        self.notifier = notifier

    def stage_1_graceful_exit(self):
        """3:00 PM — Place LIMIT exit orders with small slippage tolerance."""
        try:
            open_mis = self.portfolio.get_open_mis_positions()
            if not open_mis:
                return

            for pos in open_mis:
                quote = self.kite.quote(f"{pos['exchange']}:{pos['symbol']}")
                ltp = quote[f"{pos['exchange']}:{pos['symbol']}"]["last_price"]

                exit_side = "SELL" if pos["side"] == "BUY" else "BUY"

                if exit_side == "SELL":
                    limit_price = round(ltp * 0.999, 1)
                else:
                    limit_price = round(ltp * 1.001, 1)

                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=pos["exchange"],
                    tradingsymbol=pos["symbol"],
                    transaction_type=exit_side,
                    quantity=abs(pos["quantity"]),
                    product=self.kite.PRODUCT_MIS,
                    order_type=self.kite.ORDER_TYPE_LIMIT,
                    price=limit_price,
                    validity=self.kite.VALIDITY_DAY
                )
                self.notifier.send(
                    f"MIS EXIT Stage 1: {exit_side} {pos['symbol']} "
                    f"x{abs(pos['quantity'])} @ ₹{limit_price} (LIMIT)"
                )
        except Exception as e:
            self.notifier.send(f"🚨 MIS EXIT Stage 1 FAILED: {e}")

    def stage_2_retry_unfilled(self):
        """3:05 PM — Cancel unfilled LIMIT orders and re-place at current LTP."""
        try:
            open_mis = self.portfolio.get_open_mis_positions()
            if not open_mis:
                return

            # Cancel pending exit orders
            pending_orders = [o for o in self.kite.orders()
                             if o["status"] == "OPEN" and o["product"] == "MIS"]
            for order in pending_orders:
                self.kite.cancel_order(
                    variety=self.kite.VARIETY_REGULAR,
                    order_id=order["order_id"]
                )

            # Re-place at current LTP
            for pos in open_mis:
                quote = self.kite.quote(f"{pos['exchange']}:{pos['symbol']}")
                ltp = quote[f"{pos['exchange']}:{pos['symbol']}"]["last_price"]
                exit_side = "SELL" if pos["side"] == "BUY" else "BUY"

                self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=pos["exchange"],
                    tradingsymbol=pos["symbol"],
                    transaction_type=exit_side,
                    quantity=abs(pos["quantity"]),
                    product=self.kite.PRODUCT_MIS,
                    order_type=self.kite.ORDER_TYPE_LIMIT,
                    price=ltp,
                    validity=self.kite.VALIDITY_DAY
                )
                self.notifier.send(
                    f"⚠️ MIS EXIT Stage 2 (retry): {exit_side} {pos['symbol']} @ ₹{ltp}"
                )
        except Exception as e:
            self.notifier.send(f"🚨 MIS EXIT Stage 2 FAILED: {e}")

    def stage_3_force_market_close(self):
        """3:10 PM — HARD DEADLINE. Use MARKET orders. Accept any slippage."""
        try:
            open_mis = self.portfolio.get_open_mis_positions()
            if not open_mis:
                return

            # Cancel ALL pending MIS orders
            for order in self.kite.orders():
                if order["status"] == "OPEN" and order["product"] == "MIS":
                    self.kite.cancel_order(
                        variety=self.kite.VARIETY_REGULAR,
                        order_id=order["order_id"]
                    )

            # Force close with MARKET orders
            for pos in open_mis:
                exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
                self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=pos["exchange"],
                    tradingsymbol=pos["symbol"],
                    transaction_type=exit_side,
                    quantity=abs(pos["quantity"]),
                    product=self.kite.PRODUCT_MIS,
                    order_type=self.kite.ORDER_TYPE_MARKET,
                    validity=self.kite.VALIDITY_DAY
                )
                self.notifier.send(
                    f"🚨 MIS EXIT Stage 3 (FORCED MARKET): {exit_side} {pos['symbol']} "
                    f"x{abs(pos['quantity'])} — MARKET ORDER"
                )
        except Exception as e:
            self.notifier.send(f"🔴 MIS EXIT Stage 3 FAILED: {e}")

    def stage_4_emergency_check(self):
        """3:12 PM — If ANYTHING is still open, something went very wrong."""
        try:
            open_mis = self.portfolio.get_open_mis_positions()
            if not open_mis:
                return

            symbols = [p["symbol"] for p in open_mis]
            self.notifier.send(
                f"🔴 EMERGENCY: MIS positions STILL OPEN at 3:12 PM: {symbols}. "
                f"Zerodha auto-square-off will trigger at 3:20 PM and charge "
                f"₹50+GST per position. Manual intervention may be needed!"
            )
            # Final attempt — MARKET orders again
            for pos in open_mis:
                exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
                try:
                    self.kite.place_order(
                        variety=self.kite.VARIETY_REGULAR,
                        exchange=pos["exchange"],
                        tradingsymbol=pos["symbol"],
                        transaction_type=exit_side,
                        quantity=abs(pos["quantity"]),
                        product=self.kite.PRODUCT_MIS,
                        order_type=self.kite.ORDER_TYPE_MARKET,
                        validity=self.kite.VALIDITY_DAY
                    )
                except Exception as e:
                    self.notifier.send(
                        f"🔴 CRITICAL: Failed to close {pos['symbol']}: {e}"
                    )
        except Exception as e:
            self.notifier.send(f"🔴 EMERGENCY CHECK FAILED: {e}")
```

### Integration with Scheduler
```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

# Each MIS exit stage is an INDEPENDENT job — if one stage crashes,
# subsequent stages still execute. This is critical for safety.
scheduler.add_job(
    mis_exit_engine.stage_1_graceful_exit,
    trigger='cron', day_of_week='mon-fri', hour=15, minute=0,
    timezone='Asia/Kolkata', id='mis_exit_stage_1'
)
scheduler.add_job(
    mis_exit_engine.stage_2_retry_unfilled,
    trigger='cron', day_of_week='mon-fri', hour=15, minute=5,
    timezone='Asia/Kolkata', id='mis_exit_stage_2'
)
scheduler.add_job(
    mis_exit_engine.stage_3_force_market_close,
    trigger='cron', day_of_week='mon-fri', hour=15, minute=10,
    timezone='Asia/Kolkata', id='mis_exit_stage_3'
)
scheduler.add_job(
    mis_exit_engine.stage_4_emergency_check,
    trigger='cron', day_of_week='mon-fri', hour=15, minute=12,
    timezone='Asia/Kolkata', id='mis_exit_stage_4'
)
```

### Paper Trading Mode
In PAPER mode, the MIS exit engine logs simulated exits at current LTP instead
of placing real orders. The 3-stage timing still runs to validate the logic.

---

## 15C. CLAUDE API CIRCUIT BREAKER (Safe Mode)

If the Anthropic API is down or degraded during market hours, the bot must not
blindly retry forever while the market moves. A circuit breaker prevents this.

### Rules
```
RULE: If no successful Claude API call in the last 15 minutes (configurable),
      the bot enters SAFE MODE.
RULE: In SAFE MODE:
      - No new trades are placed
      - Existing broker-side SL and target orders remain active (they protect
        positions regardless of bot state)
      - The SL Health Check continues running (Section 15F)
      - MIS exit engine continues running on schedule (it doesn't depend on Claude)
      - Telegram alert sent: "Claude API unreachable. Safe mode activated."
RULE: The bot retries Claude API every 5 minutes with exponential backoff
RULE: If fallback is enabled, the bot can fall back to Sonnet for trading
      decisions (configurable: claude_fallback_model in config)
RULE: When Claude API recovers, the bot exits safe mode and sends a Telegram
      notification. It requests a fresh trading decision on the next cycle.
```

### Implementation
```python
class ClaudeCircuitBreaker:
    """
    Tracks Claude API health and triggers safe mode if unreachable.
    """

    def __init__(self, config, notifier):
        self.timeout_minutes = config.get("claude_safe_mode_timeout_min", 15)
        self.last_successful_call = datetime.now()
        self.in_safe_mode = False
        self.notifier = notifier

    def record_success(self):
        """Called after every successful Claude API response."""
        self.last_successful_call = datetime.now()
        if self.in_safe_mode:
            self.in_safe_mode = False
            self.notifier.send("✅ Claude API recovered. Exiting safe mode.")

    def record_failure(self, error):
        """Called after every failed Claude API call."""
        elapsed = (datetime.now() - self.last_successful_call).total_seconds() / 60
        if elapsed >= self.timeout_minutes and not self.in_safe_mode:
            self.in_safe_mode = True
            self.notifier.send(
                f"🔴 Claude API unreachable for {elapsed:.0f} min. "
                f"SAFE MODE activated. No new trades. Existing SL/targets on "
                f"broker side remain active."
            )

    def is_safe_mode(self) -> bool:
        """Check before making any new trade decisions."""
        elapsed = (datetime.now() - self.last_successful_call).total_seconds() / 60
        if elapsed >= self.timeout_minutes:
            self.in_safe_mode = True
        return self.in_safe_mode
```

---

## 15D. ORDER RECONCILIATION LOOP

After placing any order on Kite, the bot must verify it was filled, at what
price, and handle edge cases (partial fills, rejections, cancellations).

### Why This is Critical
- If an order is placed but not yet filled, the cash is still "available" in
  Kite margins. The next Claude decision may deploy that cash again, leading
  to over-deployment when both orders fill.
- If an order is rejected (insufficient margin, price out of circuit range),
  the bot must update its state and inform Claude on the next cycle.
- If a network hiccup causes `place_order` to succeed on Kite's side but the
  response doesn't reach the bot, the bot may retry and place a duplicate.

### Rules
```
RULE: After placing any order, poll kite.order_history(order_id) within 30
      seconds to check status
RULE: Statuses to handle:
      - COMPLETE: Update local DB with actual fill_price, fill_quantity
      - OPEN: Order is pending. Track it. Reserve the cash in local state
        to prevent over-deployment.
      - CANCELLED: Log reason. Release reserved cash.
      - REJECTED: Log reason (e.g., insufficient margin, circuit limit).
        Release reserved cash. Send Telegram alert.
RULE: For every PENDING/OPEN order, run a background check every 60 seconds
      until it reaches a terminal state (COMPLETE, CANCELLED, REJECTED)
RULE: The portfolio state manager must account for PENDING orders when
      calculating available cash — subtract pending BUY order values from
      available cash even if not yet filled.
RULE: Use Kite's `tag` parameter on orders for idempotency. Generate a
      unique tag per Claude decision (e.g., session_id + symbol + timestamp).
      Before placing, check if an order with the same tag already exists.
```

### Implementation
```python
class OrderReconciler:
    """
    Monitors all placed orders and updates local state with actual outcomes.
    """

    def __init__(self, kite, db, notifier):
        self.kite = kite
        self.db = db
        self.notifier = notifier
        self.pending_orders = {}  # order_id → order_details

    def track_order(self, order_id, order_details):
        """Register a newly placed order for tracking."""
        self.pending_orders[order_id] = order_details
        # Reserve cash for pending BUY orders
        if order_details["transaction_type"] == "BUY":
            estimated_value = order_details["price"] * order_details["quantity"]
            self.db.reserve_cash(order_id, estimated_value)

    def reconcile(self):
        """Check all pending orders. Called every 60 seconds."""
        resolved = []
        for order_id, details in self.pending_orders.items():
            try:
                history = self.kite.order_history(order_id)
                latest = history[-1]  # most recent status update

                if latest["status"] == "COMPLETE":
                    self.db.update_trade_fill(
                        order_id=order_id,
                        fill_price=latest["average_price"],
                        fill_quantity=latest["filled_quantity"],
                        status="COMPLETE"
                    )
                    self.db.release_cash_reservation(order_id)
                    # Place broker-side SL and target orders for the filled trade
                    self._place_sl_and_target(details, latest["average_price"])
                    resolved.append(order_id)

                elif latest["status"] in ["CANCELLED", "REJECTED"]:
                    self.db.update_trade_fill(
                        order_id=order_id,
                        fill_price=None,
                        fill_quantity=0,
                        status=latest["status"]
                    )
                    self.db.release_cash_reservation(order_id)
                    self.notifier.send(
                        f"⚠️ Order {latest['status']}: {details['symbol']} "
                        f"{details['transaction_type']} — {latest.get('status_message', 'No reason')}"
                    )
                    resolved.append(order_id)

                # OPEN/PENDING — keep tracking

            except Exception as e:
                self.notifier.send(f"Order reconciliation error for {order_id}: {e}")

        for order_id in resolved:
            del self.pending_orders[order_id]

    def _place_sl_and_target(self, order_details, fill_price):
        """Place broker-side SL and target orders immediately after fill."""
        symbol = order_details["symbol"]
        exchange = order_details["exchange"]
        qty = order_details["quantity"]
        product = order_details["product"]

        if order_details["transaction_type"] == "BUY":
            # Place SL-M SELL order
            sl_price = order_details.get("stop_loss", round(fill_price * 0.98, 2))
            self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange, tradingsymbol=symbol,
                transaction_type="SELL", quantity=qty, product=product,
                order_type=self.kite.ORDER_TYPE_SL_M,
                trigger_price=sl_price, validity=self.kite.VALIDITY_DAY
            )
            # Place target LIMIT SELL order
            target_price = order_details.get("target", round(fill_price * 1.03, 2))
            self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange, tradingsymbol=symbol,
                transaction_type="SELL", quantity=qty, product=product,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=target_price, validity=self.kite.VALIDITY_DAY
            )
        else:
            # Short sell — place SL-M BUY and target LIMIT BUY
            sl_price = order_details.get("stop_loss", round(fill_price * 1.02, 2))
            self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange, tradingsymbol=symbol,
                transaction_type="BUY", quantity=qty, product=product,
                order_type=self.kite.ORDER_TYPE_SL_M,
                trigger_price=sl_price, validity=self.kite.VALIDITY_DAY
            )
            target_price = order_details.get("target", round(fill_price * 0.97, 2))
            self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange, tradingsymbol=symbol,
                transaction_type="BUY", quantity=qty, product=product,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=target_price, validity=self.kite.VALIDITY_DAY
            )
```

---

## 15E. CORPORATE ACTIONS FILTER

Stocks undergoing corporate actions (splits, bonuses, dividends, rights issues)
can cause misleading price movements that confuse both the screeners and Claude.

### Problem
On an ex-date, a stock might "drop" 10% because of a dividend — your screener
would flag this as a breakdown, and Claude might short it. Similarly, a stock
split can look like a crash.

### Rules
```
RULE: Every morning during pre-market, fetch the corporate actions calendar
      for the next 3 trading days from BSE API / NSE website
RULE: On ex-dates: EXCLUDE the stock from all screeners for the day
      (the price movement is not organic — it's a corporate action adjustment)
RULE: On record dates / book closure dates: flag the stock with a warning
      in the prompt if it's a candidate (Claude should know about it)
RULE: For stock splits and bonuses: adjust historical candle data before
      feeding to indicators (or exclude for 2 days post-adjustment)
RULE: Store corporate actions in local DB for reference
```

### Data Sources
```python
# BSE Corporate Actions API
# https://api.bseindia.com/BseIndiaAPI/api/CorporateAction/w?
#   scripcode=&index=&segment=Equity&fromdate=01/03/2026&todate=31/03/2026

# NSE Corporate Actions
# https://www.nseindia.com/companies-listing/corporate-filings-actions
# (requires scraping with proper headers)
```

---

## 15F. SL & TARGET HEALTH CHECK

A background process that continuously verifies broker-side protection orders
exist for every open position.

### Why This is Critical
If the bot crashes and restarts, or if a SL order gets rejected by the broker,
the position is unprotected. This health check ensures protection is always in place.

### Rules
```
RULE: Runs every 5 minutes during market hours (configurable)
RULE: For every open position (CNC holdings + MIS positions):
      - Query kite.orders() to find corresponding SL and target orders
      - If SL order is missing → re-place immediately + Telegram alert
      - If target order is missing → re-place immediately + Telegram alert
      - If SL order was triggered (COMPLETE) → log the exit, update DB
      - If target order was triggered (COMPLETE) → log the exit, update DB,
        also cancel the corresponding SL order (and vice versa)
RULE: When either SL or target fills, cancel the OTHER order for that position
      to avoid double execution
```

### Implementation
```python
class SLHealthCheck:
    """
    Periodically verifies that every open position has broker-side SL and
    target orders. Re-places missing orders immediately.
    """

    def __init__(self, kite, db, notifier):
        self.kite = kite
        self.db = db
        self.notifier = notifier

    def check(self):
        """Run every 5 minutes during market hours."""
        open_positions = self.db.get_all_open_positions()
        active_orders = {
            o["tradingsymbol"]: o
            for o in self.kite.orders()
            if o["status"] in ["OPEN", "TRIGGER PENDING"]
        }

        for pos in open_positions:
            symbol = pos["symbol"]
            has_sl = any(
                o["tradingsymbol"] == symbol
                and o["order_type"] in ["SL", "SL-M"]
                and o["status"] in ["OPEN", "TRIGGER PENDING"]
                for o in self.kite.orders()
            )
            has_target = any(
                o["tradingsymbol"] == symbol
                and o["order_type"] == "LIMIT"
                and o["transaction_type"] != pos["transaction_type"]
                and o["status"] == "OPEN"
                for o in self.kite.orders()
            )

            if not has_sl:
                self.notifier.send(
                    f"⚠️ SL MISSING for {symbol}! Re-placing SL order."
                )
                self._replace_sl(pos)

            if not has_target:
                self.notifier.send(
                    f"⚠️ TARGET MISSING for {symbol}! Re-placing target order."
                )
                self._replace_target(pos)

    def _replace_sl(self, pos):
        """Re-place a missing SL order."""
        sl_price = self.db.get_sl_for_position(pos["symbol"])
        exit_side = "SELL" if pos["transaction_type"] == "BUY" else "BUY"
        self.kite.place_order(
            variety=self.kite.VARIETY_REGULAR,
            exchange=pos["exchange"],
            tradingsymbol=pos["symbol"],
            transaction_type=exit_side,
            quantity=abs(pos["quantity"]),
            product=pos["product"],
            order_type=self.kite.ORDER_TYPE_SL_M,
            trigger_price=sl_price,
            validity=self.kite.VALIDITY_DAY
        )

    def _replace_target(self, pos):
        """Re-place a missing target order."""
        target_price = self.db.get_target_for_position(pos["symbol"])
        exit_side = "SELL" if pos["transaction_type"] == "BUY" else "BUY"
        self.kite.place_order(
            variety=self.kite.VARIETY_REGULAR,
            exchange=pos["exchange"],
            tradingsymbol=pos["symbol"],
            transaction_type=exit_side,
            quantity=abs(pos["quantity"]),
            product=pos["product"],
            order_type=self.kite.ORDER_TYPE_LIMIT,
            price=target_price,
            validity=self.kite.VALIDITY_DAY
        )
```


## 15G. PROMPT SIZE MANAGEMENT

The two-stage pipeline naturally manages prompt size better than the old
single-prompt approach, but overflow is still possible if Claude requests
many stocks in its watchlist.

### Rules
```
RULE: The Market Pulse prompt is compact by design (~3,000 tokens). It should
      never exceed 5,000 tokens. If it does, trim the movers/losers tables
      from 10 to 5 entries each.
RULE: For the Trading Decision prompt, estimate token count before sending
      (rough estimate: 1 token ≈ 4 characters for English text)
RULE: If estimated tokens > max_prompt_tokens (default: 12,000):
      - Split Claude's watchlist into batches that fit within the limit
      - Send each batch as a separate Opus call with the SAME market
        context, portfolio state, and existing positions
      - Only the "DEEP DIVE: STOCK DATA" section differs per batch
      - Merge decisions from all batches before passing to guardrail engine
RULE: Market context + portfolio state + existing positions ≈ 2,500 tokens
      (fixed overhead per call)
RULE: Each stock deep dive ≈ 500-700 tokens
RULE: With 12,000 token limit: ~13-15 stocks per call
RULE: If Claude requests > 15 stocks in watchlist, split into 2 Opus calls
RULE: Always include existing position updates in EVERY batch
RULE: Claude's watchlist is soft-capped at 15 stocks. If Sonnet returns
      more than 15, take the first 15 (Sonnet is instructed to prioritize).
      Current holdings are always included regardless of cap.
```

### Implementation
```python
class PromptSizeManager:
    """
    Splits watchlist stocks across multiple Opus calls if the deep dive
    prompt would exceed the configured token limit.
    """

    def __init__(self, config):
        self.max_tokens = config.get("max_prompt_tokens", 12000)
        self.overhead_tokens = 2500  # market context + portfolio + positions
        self.per_stock_tokens = 600  # average tokens per stock deep dive

    def split_watchlist(self, watchlist: list, held_symbols: list) -> list:
        """
        Returns a list of batches. Each batch is a list of stock symbols.
        Held symbols are included in EVERY batch.
        """
        available_tokens = self.max_tokens - self.overhead_tokens
        held_tokens = len(held_symbols) * self.per_stock_tokens
        new_stock_budget = available_tokens - held_tokens
        max_new_per_batch = max(1, new_stock_budget // self.per_stock_tokens)

        # Separate held stocks from new watchlist picks
        new_picks = [s for s in watchlist if s not in held_symbols]

        batches = []
        for i in range(0, len(new_picks), max_new_per_batch):
            batch = held_symbols + new_picks[i:i + max_new_per_batch]
            batches.append(batch)

        if not batches:
            batches = [held_symbols]

        return batches
```

---

## 16. LOGGING & OBSERVABILITY

### 16.1 What to Log

The system maintains TWO logging layers:
- **CSV files (immutable audit trail)**: Append-only, set to read-only after
  each trading day. These are the ground truth. Never edited, never deleted.
- **SQLite database (queryable state)**: Used by the bot for lookups, aggregation,
  and feeding data back into prompts. Mutable — can be rebuilt from CSV if corrupted.

**Every single one of these must be logged with timestamps:**

1. **Trades** → CSV (`logs/trades/`) + DB (`trades` table)
2. **LLM prompts** → Text files (`logs/llm/prompts/`) + reference in DB (`llm_calls` table)
3. **LLM responses** → JSON files (`logs/llm/responses/`) + reference in DB (`llm_calls` table)
4. **LLM call metadata** → CSV (`logs/llm/llm_calls_*.csv`) + DB (`llm_calls` table) — model, tokens, cost, latency, status, file paths, decision metadata
5. **LLM daily costs** → CSV (`logs/llm/costs_daily.csv`) + DB (`llm_daily_costs` table) — per-model and per-call-type breakdown
6. **Guardrail results** → CSV (`logs/guardrails/`) + DB — every validation pass/fail
7. **Daily P&L** → CSV (`logs/pnl/pnl_daily.csv`) + DB (`daily_summaries` table)
8. **Portfolio snapshots** → DB (`portfolio_snapshots` table) — periodic state dumps
9. **Market Pulse watchlists** → DB (`llm_calls.watchlist_symbols`) + response files — what Claude chose to look at and why
10. **News fetched** → DB — raw headlines and Haiku summaries
11. **Errors** → `logs/app.log` — API failures, connection drops, exceptions
12. **Telegram notifications** → `logs/app.log` — what was sent and when

### 16.2 Database Schema (SQLite)

**Note:** The database is the mutable, queryable layer used by the bot for
lookups, aggregation, and feeding data into prompts. It is NOT the audit trail.
The immutable CSV logs (Section 16.3) are the ground truth. If the DB is ever
corrupted, it can be rebuilt from the CSVs.

```sql
-- Trade log
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    transaction_type TEXT NOT NULL,  -- BUY or SELL
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    product TEXT NOT NULL,           -- CNC or MIS
    order_type TEXT NOT NULL,        -- LIMIT, MARKET, SL
    stop_loss REAL,
    target REAL,
    confidence REAL,
    timeframe TEXT,                  -- INTRADAY or SWING
    max_hold_days INTEGER,
    reasoning TEXT,                  -- Claude's reasoning
    order_id TEXT,                   -- Kite order ID (or paper ID)
    status TEXT,                     -- PLACED, FILLED, REJECTED, CANCELLED
    fill_price REAL,
    fill_timestamp DATETIME,
    mode TEXT NOT NULL,              -- PAPER or LIVE (NEVER exposed to Claude)
    claude_session_id TEXT           -- links to prompt/response files
);

-- Portfolio snapshots
CREATE TABLE portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    total_value REAL NOT NULL,
    cash_available REAL NOT NULL,
    deployed REAL NOT NULL,
    daily_pnl REAL NOT NULL,
    cumulative_pnl REAL NOT NULL,
    holdings_json TEXT,              -- JSON dump of all holdings
    positions_json TEXT              -- JSON dump of all positions
);

-- ═══════════════════════════════════════════════════════════
-- LLM INTERACTION AUDIT TABLE (the core tracking table)
-- Every single LLM call — Haiku, Sonnet, Opus — goes here.
-- This is the single source of truth for all AI interactions.
-- ═══════════════════════════════════════════════════════════
CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- ─── IDENTITY ───
    call_id TEXT NOT NULL UNIQUE,     -- Unique ID: "20260301_093015_PULSE_001"
                                      -- Format: YYYYMMDD_HHMMSS_CALLTYPE_SEQ
    session_id TEXT NOT NULL,          -- Groups related calls in one cycle
                                      -- e.g., a Pulse + its follow-up Decision share a session
    parent_call_id TEXT,               -- If this call was triggered by another call
                                      -- e.g., Deep Dive Opus call → parent = Market Pulse call
                                      -- NULL for top-level calls (news, pulse)

    -- ─── TIMING ───
    timestamp DATETIME NOT NULL,       -- When the API call was initiated
    date DATE NOT NULL,                -- Trading date (for easy daily grouping)
    day_number INTEGER NOT NULL,       -- Experiment day 1-30
    response_timestamp DATETIME,       -- When the response was received
    latency_ms INTEGER,                -- API round-trip time in milliseconds

    -- ─── MODEL & CALL TYPE ───
    model TEXT NOT NULL,               -- Exact model string:
                                      --   "claude-opus-4-6"
                                      --   "claude-sonnet-4-5-20250929"
                                      --   "claude-haiku-4-5-20251001"
    call_type TEXT NOT NULL,           -- What triggered this call:
                                      --   "NEWS_SUMMARY"      — Haiku summarizing headlines
                                      --   "MARKET_PULSE"      — Sonnet scanning market
                                      --   "PRE_MARKET"        — Opus pre-market strategy
                                      --   "TRADING_DECISION"  — Opus main trading call
                                      --   "EOD_REVIEW"        — Opus end-of-day review
                                      --   "RETRY"             — Retry of a failed call
    call_subtype TEXT,                 -- Optional further classification:
                                      --   For NEWS_SUMMARY: stock symbol being summarized
                                      --   For TRADING_DECISION: "batch_1_of_2", "batch_2_of_2"
                                      --   For RETRY: original call_type being retried

    -- ─── TOKEN ACCOUNTING ───
    input_tokens INTEGER NOT NULL,     -- Tokens sent (from API response usage.input_tokens)
    output_tokens INTEGER NOT NULL,    -- Tokens received (from API response usage.output_tokens)
    cache_read_tokens INTEGER DEFAULT 0,  -- Tokens read from cache (prompt caching)
    cache_creation_tokens INTEGER DEFAULT 0,  -- Tokens written to cache
    total_tokens INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,

    -- ─── COST CALCULATION (in INR) ───
    -- Costs are computed at logging time using the rates in config.yaml
    -- Stored as INR for direct comparison with trading P&L
    input_cost_inr REAL NOT NULL,      -- Cost of input tokens in ₹
    output_cost_inr REAL NOT NULL,     -- Cost of output tokens in ₹
    cache_read_cost_inr REAL DEFAULT 0, -- Cost of cache read tokens
    cache_creation_cost_inr REAL DEFAULT 0, -- Cost of cache creation tokens
    total_cost_inr REAL GENERATED ALWAYS AS
        (input_cost_inr + output_cost_inr + cache_read_cost_inr + cache_creation_cost_inr) STORED,

    -- ─── FILE REFERENCES ───
    -- Every prompt and response is saved as a separate file for full reproducibility
    system_prompt_file TEXT,            -- Path to system prompt file (NULL if same as previous)
    user_prompt_file TEXT NOT NULL,     -- Path to full user prompt text file
    response_file TEXT NOT NULL,        -- Path to full raw response JSON file
    parsed_output_file TEXT,            -- Path to parsed/structured output (if different from raw)

    -- ─── RESPONSE METADATA ───
    status TEXT NOT NULL DEFAULT 'SUCCESS',  -- SUCCESS, ERROR, TIMEOUT, RATE_LIMITED, INVALID_JSON
    error_message TEXT,                 -- Error details if status != SUCCESS
    http_status_code INTEGER,           -- HTTP status from API (200, 429, 500, etc.)
    stop_reason TEXT,                   -- API stop_reason: "end_turn", "max_tokens", etc.

    -- ─── DECISION METADATA (for TRADING_DECISION and MARKET_PULSE calls) ───
    -- Quick-access fields so you can query decisions without parsing files
    market_bias TEXT,                   -- BULLISH/BEARISH/NEUTRAL/CAUTIOUS (from response)
    decisions_count INTEGER DEFAULT 0,  -- Number of trade decisions in response
    watchlist_symbols TEXT,             -- Comma-separated: "RELIANCE,INFY,HDFCBANK"
    actions_summary TEXT,               -- Compact: "BUY:RELIANCE,SBIN | EXIT:TATAMOTORS"

    -- ─── LINKAGE ───
    -- Connect LLM calls to the trades they generated
    trade_ids TEXT,                     -- Comma-separated trade IDs from trades table
                                       -- Set after guardrail validation + execution

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_llm_calls_date ON llm_calls(date);
CREATE INDEX idx_llm_calls_model ON llm_calls(model);
CREATE INDEX idx_llm_calls_call_type ON llm_calls(call_type);
CREATE INDEX idx_llm_calls_session ON llm_calls(session_id);
CREATE INDEX idx_llm_calls_parent ON llm_calls(parent_call_id);
CREATE INDEX idx_llm_calls_status ON llm_calls(status);

-- ═══════════════════════════════════════════════════════════
-- LLM DAILY COST SUMMARY (materialized view, rebuilt daily)
-- Quick lookup: "How much did I spend on AI today?"
-- ═══════════════════════════════════════════════════════════
CREATE TABLE llm_daily_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    day_number INTEGER NOT NULL,

    -- Per-model breakdown
    haiku_calls INTEGER DEFAULT 0,
    haiku_input_tokens INTEGER DEFAULT 0,
    haiku_output_tokens INTEGER DEFAULT 0,
    haiku_cost_inr REAL DEFAULT 0,

    sonnet_calls INTEGER DEFAULT 0,
    sonnet_input_tokens INTEGER DEFAULT 0,
    sonnet_output_tokens INTEGER DEFAULT 0,
    sonnet_cost_inr REAL DEFAULT 0,

    opus_calls INTEGER DEFAULT 0,
    opus_input_tokens INTEGER DEFAULT 0,
    opus_output_tokens INTEGER DEFAULT 0,
    opus_cost_inr REAL DEFAULT 0,

    -- Per call-type breakdown
    news_calls INTEGER DEFAULT 0,
    news_cost_inr REAL DEFAULT 0,
    pulse_calls INTEGER DEFAULT 0,
    pulse_cost_inr REAL DEFAULT 0,
    decision_calls INTEGER DEFAULT 0,
    decision_cost_inr REAL DEFAULT 0,
    eod_calls INTEGER DEFAULT 0,
    eod_cost_inr REAL DEFAULT 0,
    premarket_calls INTEGER DEFAULT 0,
    premarket_cost_inr REAL DEFAULT 0,
    retry_calls INTEGER DEFAULT 0,
    retry_cost_inr REAL DEFAULT 0,

    -- Totals
    total_calls INTEGER DEFAULT 0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    total_cost_inr REAL DEFAULT 0,

    -- Cache efficiency
    total_cache_read_tokens INTEGER DEFAULT 0,
    cache_savings_inr REAL DEFAULT 0,   -- How much cache saved vs full-price

    -- Error tracking
    failed_calls INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,

    -- Context: trading performance vs AI cost
    trading_pnl_inr REAL,               -- Day's trading P&L for comparison
    cost_to_pnl_ratio REAL,             -- total_cost_inr / abs(trading_pnl_inr)

    -- Cumulative (experiment to date)
    cumulative_cost_inr REAL DEFAULT 0,
    cumulative_tokens INTEGER DEFAULT 0,

    UNIQUE(date)
);

-- ═══════════════════════════════════════════════════════════
-- CONVENIENCE VIEW: Quick cost-per-call analysis
-- ═══════════════════════════════════════════════════════════
CREATE VIEW v_llm_cost_analysis AS
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
    total_tokens,
    total_cost_inr,
    latency_ms,
    status,
    decisions_count,
    watchlist_symbols,
    actions_summary,
    user_prompt_file,
    response_file,
    -- Readable model name
    CASE
        WHEN model LIKE '%opus%' THEN 'Opus'
        WHEN model LIKE '%sonnet%' THEN 'Sonnet'
        WHEN model LIKE '%haiku%' THEN 'Haiku'
        ELSE model
    END AS model_short,
    -- Cost per 1K tokens (for spotting anomalies)
    CASE WHEN total_tokens > 0
        THEN ROUND(total_cost_inr / (total_tokens / 1000.0), 4)
        ELSE 0
    END AS cost_per_1k_tokens
FROM llm_calls
ORDER BY timestamp DESC;

-- ═══════════════════════════════════════════════════════════
-- CONVENIENCE VIEW: Session trace (follow one decision cycle)
-- ═══════════════════════════════════════════════════════════
CREATE VIEW v_session_trace AS
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
    total_cost_inr,
    status,
    watchlist_symbols,
    actions_summary,
    decisions_count,
    user_prompt_file,
    response_file
FROM llm_calls
ORDER BY session_id, timestamp;

-- Guardrail log
CREATE TABLE guardrail_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    trade_id INTEGER,               -- references trades.id
    llm_call_id TEXT,               -- references llm_calls.call_id (which LLM call produced this trade)
    is_valid BOOLEAN NOT NULL,
    errors_json TEXT,
    warnings_json TEXT
);

-- Daily summaries
CREATE TABLE daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE,
    day_number INTEGER NOT NULL,     -- experiment day 1-30
    trades_count INTEGER,
    wins INTEGER,
    losses INTEGER,
    total_pnl REAL,
    cumulative_pnl REAL,
    portfolio_value REAL,
    market_bias TEXT,                -- Claude's assessment
    notes TEXT,                      -- EOD review notes
    llm_cost_inr REAL,              -- Total AI cost for the day
    llm_calls_count INTEGER         -- Total LLM calls for the day
);
```

### 16.3 Read-Only Trade Logs (Immutable Audit Trail)

In addition to the SQLite database (which is mutable and used by the bot for
queries), maintain a **separate, append-only, human-readable log file** for every
trade. These files are your permanent audit trail — never edited, never deleted.

**Why separate from the DB?**
- DB rows can be accidentally updated/deleted by buggy code
- Log files are append-only — once written, they're permanent
- Easy to share, review, or import into Excel/Google Sheets
- Serves as the ground truth if DB ever gets corrupted

#### Trade Log File: `logs/trades/trades_YYYY-MM-DD.csv`

A new CSV file is created for each trading day. Append-only — never overwrite.

**IMPORTANT:** The `mode` column in the CSV is for YOUR analysis only. This value
is NEVER included in any data sent to Claude. The prompt builder does not have
access to the mode — only the execution engine and this logger do.

```csv
timestamp,day_number,mode,order_id,symbol,exchange,side,product,order_type,quantity,signal_price,fill_price,stop_loss,target,confidence,timeframe,max_hold_days,reasoning,status,guardrail_result,guardrail_errors
2026-03-01 09:32:15,1,LIVE,240301000001,RELIANCE,NSE,BUY,CNC,LIMIT,4,2450.00,2448.50,2396.00,2550.00,0.72,SWING,10,"Golden cross + volume breakout + Q3 results catalyst",FILLED,PASSED,""
2026-03-01 09:32:15,1,LIVE,240301000002,RELIANCE,NSE,SELL,CNC,SL,4,2396.00,,2396.00,,,,,Stop-loss order for RELIANCE BUY,PLACED,PASSED,""
2026-03-01 10:05:42,1,LIVE,240301000003,SBIN,NSE,BUY,MIS,LIMIT,10,780.00,780.50,765.00,795.00,0.65,INTRADAY,0,"PSU bank momentum + 2.3x volume",FILLED,PASSED,""
2026-03-01 10:05:42,1,LIVE,,TATAMOTORS,NSE,BUY,MIS,LIMIT,15,620.00,,612.00,635.00,0.45,INTRADAY,0,"Sector rotation play",REJECTED,FAILED,"Confidence 0.45 below 0.5 threshold"
2026-03-01 15:02:30,1,LIVE,240301000004,SBIN,NSE,SELL,MIS,LIMIT,10,792.00,791.50,,,,,MIS auto-exit Stage 1,FILLED,N/A,""
```

#### Implementation

```python
import csv
import os
from datetime import datetime
from filelock import FileLock  # pip install filelock

class TradeLogger:
    """
    Append-only, read-only trade logger.
    Creates one CSV per trading day. Never modifies existing entries.
    """

    HEADERS = [
        "timestamp", "day_number", "mode", "order_id", "symbol", "exchange",
        "side", "product", "order_type", "quantity", "signal_price",
        "fill_price", "stop_loss", "target", "confidence", "timeframe",
        "max_hold_days", "reasoning", "status", "guardrail_result",
        "guardrail_errors"
    ]

    def __init__(self, log_dir="logs/trades"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def _get_filepath(self):
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"trades_{today}.csv")

    def log_trade(self, trade: dict):
        """Append a single trade record. NEVER modifies existing rows."""
        filepath = self._get_filepath()
        lock = FileLock(filepath + ".lock")

        with lock:
            file_exists = os.path.exists(filepath)
            with open(filepath, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.HEADERS)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "day_number": trade.get("day_number", ""),
                    "mode": trade.get("mode", ""),
                    "order_id": trade.get("order_id", ""),
                    "symbol": trade.get("symbol", ""),
                    "exchange": trade.get("exchange", ""),
                    "side": trade.get("transaction_type", ""),
                    "product": trade.get("product", ""),
                    "order_type": trade.get("order_type", ""),
                    "quantity": trade.get("quantity", ""),
                    "signal_price": trade.get("price", ""),
                    "fill_price": trade.get("fill_price", ""),
                    "stop_loss": trade.get("stop_loss", ""),
                    "target": trade.get("target", ""),
                    "confidence": trade.get("confidence", ""),
                    "timeframe": trade.get("timeframe", ""),
                    "max_hold_days": trade.get("max_hold_days", ""),
                    "reasoning": trade.get("reasoning", "").replace("\n", " "),
                    "status": trade.get("status", ""),
                    "guardrail_result": trade.get("guardrail_result", ""),
                    "guardrail_errors": trade.get("guardrail_errors", ""),
                })

    # No update or delete methods exist — this class is append-only by design
```

#### Additional Log Files

**1. Daily P&L Log: `logs/pnl/pnl_daily.csv`** (append one row per trading day)
```csv
date,day_number,starting_value,ending_value,daily_pnl,daily_pnl_pct,cumulative_pnl,cumulative_pnl_pct,trades_count,wins,losses,cash_remaining,deployed_pct
2026-03-01,1,100000,100320,320,0.32%,320,0.32%,3,2,1,62400,37.6%
2026-03-02,2,100320,99850,-470,-0.47%,-150,-0.15%,5,2,3,58200,41.8%
```

**2. Guardrail Log: `logs/guardrails/guardrails_YYYY-MM-DD.csv`** (every validation)
```csv
timestamp,symbol,action,product,result,errors,warnings
2026-03-01 09:32:15,RELIANCE,BUY,CNC,PASSED,"",""
2026-03-01 10:05:42,TATAMOTORS,BUY,MIS,FAILED,"Confidence 0.45 below 0.5 threshold",""
2026-03-01 10:35:00,ADANIENT,BUY,CNC,FAILED,"Position exceeds 20% of portfolio",""
```

**3. LLM Interaction Log: `logs/llm/llm_calls_YYYY-MM-DD.csv`** (every LLM call)

This is the immutable CSV mirror of the `llm_calls` DB table. One row per API
call — Haiku, Sonnet, or Opus. This file is the ground truth for cost auditing.

```csv
timestamp,call_id,session_id,parent_call_id,day_number,model,call_type,call_subtype,input_tokens,output_tokens,cache_read_tokens,total_tokens,total_cost_inr,latency_ms,status,error_message,decisions_count,watchlist_symbols,actions_summary,system_prompt_file,user_prompt_file,response_file
2026-03-01 08:40:15,20260301_084015_NEWS_001,sess_084000,,,claude-haiku-4-5-20251001,NEWS_SUMMARY,RELIANCE,320,85,0,405,0.08,240,SUCCESS,,0,,,logs/llm/system/haiku_news_v1.txt,logs/llm/prompts/20260301_084015_NEWS_001.txt,logs/llm/responses/20260301_084015_NEWS_001.json
2026-03-01 09:22:00,20260301_092200_PULSE_001,sess_092200,,1,claude-sonnet-4-5-20250929,MARKET_PULSE,,2800,620,1200,3420,4.85,1850,SUCCESS,,0,"TATAMOTORS,HDFCBANK,RELIANCE,GOLDBEES,SBIN,INFY,BHARTIARTL,ICICIBANK",,logs/llm/system/system_prompt_v1.txt,logs/llm/prompts/20260301_092200_PULSE_001.txt,logs/llm/responses/20260301_092200_PULSE_001.json
2026-03-01 09:27:00,20260301_092700_DECISION_001,sess_092200,20260301_092200_PULSE_001,1,claude-opus-4-6,TRADING_DECISION,,7200,1100,1200,8300,42.50,4200,SUCCESS,,2,"TATAMOTORS,HDFCBANK,RELIANCE,GOLDBEES,SBIN,INFY,BHARTIARTL,ICICIBANK","BUY:RELIANCE,BUY:SBIN",logs/llm/system/system_prompt_v1.txt,logs/llm/prompts/20260301_092700_DECISION_001.txt,logs/llm/responses/20260301_092700_DECISION_001.json
```

**4. LLM Daily Cost Summary: `logs/llm/costs_daily.csv`** (one row per day)
```csv
date,day_number,haiku_calls,haiku_tokens,haiku_cost_inr,sonnet_calls,sonnet_tokens,sonnet_cost_inr,opus_calls,opus_tokens,opus_cost_inr,total_calls,total_tokens,total_cost_inr,failed_calls,cache_savings_inr,trading_pnl_inr,cumulative_cost_inr
2026-03-01,1,18,7200,4.20,12,41000,58.50,10,83000,425.00,40,131200,487.70,0,32.50,320.00,487.70
2026-03-02,2,15,6000,3.50,10,35000,49.00,9,74700,382.00,34,115700,434.50,1,28.00,-470.00,922.20
```

### 16.3A LLM File Storage Structure

Every LLM input and output is stored as a separate file. Files are organized
by date and type for easy browsing and replay.

```
logs/llm/
├── system/                              # System prompts (versioned, reused across calls)
│   ├── system_prompt_v1.txt             # The full system prompt text
│   ├── system_prompt_v2.txt             # If you update it mid-experiment
│   └── haiku_news_v1.txt                # Haiku news summarization system prompt
│
├── prompts/                             # Every user prompt sent to any model
│   ├── 20260301_084015_NEWS_001.txt     # Haiku: raw news text for summarization
│   ├── 20260301_084018_NEWS_002.txt     # Haiku: another stock's news
│   ├── 20260301_092200_PULSE_001.txt    # Sonnet: Market Pulse dashboard
│   ├── 20260301_092700_DECISION_001.txt # Opus: Trading Decision with deep dives
│   ├── 20260301_100200_PULSE_002.txt    # Sonnet: Next cycle's Market Pulse
│   ├── 20260301_100700_DECISION_002.txt # Opus: Next cycle's Trading Decision
│   └── ...
│
├── responses/                           # Every raw response from any model
│   ├── 20260301_084015_NEWS_001.json    # Haiku response (news summary)
│   ├── 20260301_092200_PULSE_001.json   # Sonnet response (watchlist JSON)
│   ├── 20260301_092700_DECISION_001.json # Opus response (trading decisions JSON)
│   └── ...
│
├── llm_calls_2026-03-01.csv             # Immutable daily CSV (all calls)
├── llm_calls_2026-03-02.csv
├── costs_daily.csv                      # Running daily cost summary
└── README.txt                           # Explains the file naming convention
```

**File naming convention:** `YYYYMMDD_HHMMSS_CALLTYPE_SEQ.{txt|json}`
- `YYYYMMDD_HHMMSS` — timestamp when the call was initiated
- `CALLTYPE` — `NEWS`, `PULSE`, `DECISION`, `PREMARKET`, `EOD`, `RETRY`
- `SEQ` — sequence number to handle multiple calls in the same second: `001`, `002`
- `.txt` for prompts (plain text), `.json` for responses (raw API response JSON)

**What gets stored in each file:**

| File | Contents |
|---|---|
| System prompt `.txt` | The full `system` parameter text. Versioned — only saved when it changes. All calls reference which version they used. |
| User prompt `.txt` | The complete `user` message text exactly as sent to the API. For Market Pulse: the full dashboard. For Trading Decision: the full deep dive data. For News: the raw headlines. |
| Response `.json` | The complete raw API response JSON, including `content`, `usage`, `model`, `stop_reason`. Not just the text — the entire response object. |

**Why store the full raw API response (not just the text)?**
The API response includes `usage.input_tokens` and `usage.output_tokens` which
are the authoritative token counts. It also includes `stop_reason` (did Claude
finish or hit `max_tokens`?), `model` (confirms which model actually served the
request), and the full `content` array (which may include tool use blocks in
future). Storing the raw response means you never lose information.

### 16.3B LLM Interaction Logger Implementation

```python
import csv
import json
import os
import time
from datetime import datetime
from filelock import FileLock
from dataclasses import dataclass, asdict
from typing import Optional


# ═══════════════════════════════════════════
# PRICING TABLE (INR per 1M tokens)
# Update these if Anthropic changes prices.
# ═══════════════════════════════════════════
# Prices as of March 2026 (check https://docs.anthropic.com/en/docs/about-claude/pricing)
# Converted to INR at the USD/INR rate in config.yaml

LLM_PRICING = {
    "claude-opus-4-6": {
        "input_per_1m": 1260.00,      # $15/MTok × ₹84
        "output_per_1m": 6300.00,     # $75/MTok × ₹84
        "cache_read_per_1m": 126.00,  # $1.50/MTok × ₹84
        "cache_create_per_1m": 1575.00,  # $18.75/MTok × ₹84
    },
    "claude-sonnet-4-5-20250929": {
        "input_per_1m": 252.00,       # $3/MTok × ₹84
        "output_per_1m": 1260.00,     # $15/MTok × ₹84
        "cache_read_per_1m": 25.20,   # $0.30/MTok × ₹84
        "cache_create_per_1m": 315.00,  # $3.75/MTok × ₹84
    },
    "claude-haiku-4-5-20251001": {
        "input_per_1m": 67.20,        # $0.80/MTok × ₹84
        "output_per_1m": 336.00,      # $4/MTok × ₹84
        "cache_read_per_1m": 6.72,    # $0.08/MTok × ₹84
        "cache_create_per_1m": 84.00, # $1/MTok × ₹84
    },
}


@dataclass
class LLMCallRecord:
    """Complete record of a single LLM API call."""

    # Identity
    call_id: str
    session_id: str
    parent_call_id: Optional[str]

    # Timing
    timestamp: str          # ISO format
    date: str               # YYYY-MM-DD
    day_number: int
    response_timestamp: str
    latency_ms: int

    # Model & type
    model: str
    call_type: str          # NEWS_SUMMARY, MARKET_PULSE, TRADING_DECISION, etc.
    call_subtype: Optional[str]

    # Tokens
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_tokens: int

    # Cost (INR)
    input_cost_inr: float
    output_cost_inr: float
    cache_read_cost_inr: float
    cache_creation_cost_inr: float
    total_cost_inr: float

    # File paths
    system_prompt_file: Optional[str]
    user_prompt_file: str
    response_file: str
    parsed_output_file: Optional[str]

    # Response metadata
    status: str             # SUCCESS, ERROR, TIMEOUT, RATE_LIMITED, INVALID_JSON
    error_message: Optional[str]
    http_status_code: Optional[int]
    stop_reason: Optional[str]

    # Decision metadata
    market_bias: Optional[str]
    decisions_count: int
    watchlist_symbols: Optional[str]
    actions_summary: Optional[str]
    trade_ids: Optional[str]


class LLMInteractionLogger:
    """
    Logs EVERY LLM API call to both SQLite (queryable) and CSV (immutable).
    Saves full prompt text and raw API response to individual files.

    Usage:
        logger = LLMInteractionLogger(db, config)

        # Before the API call:
        call_id = logger.generate_call_id("MARKET_PULSE")
        prompt_file = logger.save_prompt(call_id, system_prompt, user_prompt)

        # Make the API call:
        start_time = time.time()
        response = anthropic_client.messages.create(...)
        latency_ms = int((time.time() - start_time) * 1000)

        # After the API call:
        response_file = logger.save_response(call_id, response)
        record = logger.log_call(
            call_id=call_id,
            session_id=session_id,
            parent_call_id=pulse_call_id,  # or None
            model="claude-opus-4-6",
            call_type="TRADING_DECISION",
            response=response,
            latency_ms=latency_ms,
            prompt_file=prompt_file,
            response_file=response_file,
            system_prompt_file="logs/llm/system/system_prompt_v1.txt",
            # Optional decision metadata:
            market_bias="BULLISH",
            decisions_count=2,
            watchlist_symbols="RELIANCE,SBIN",
            actions_summary="BUY:RELIANCE,BUY:SBIN",
        )
    """

    CSV_HEADERS = [
        "timestamp", "call_id", "session_id", "parent_call_id", "day_number",
        "model", "call_type", "call_subtype",
        "input_tokens", "output_tokens", "cache_read_tokens", "total_tokens",
        "total_cost_inr", "latency_ms", "status", "error_message",
        "decisions_count", "watchlist_symbols", "actions_summary",
        "system_prompt_file", "user_prompt_file", "response_file",
    ]

    def __init__(self, db, config):
        self.db = db
        self.config = config
        self.log_dir = config.get("log_dir", "logs")
        self.llm_dir = os.path.join(self.log_dir, "llm")
        self.day_number = config.get("day_number", 0)
        self._seq_counter = {}  # For generating unique call_ids

        # Create directories
        for subdir in ["system", "prompts", "responses"]:
            os.makedirs(os.path.join(self.llm_dir, subdir), exist_ok=True)

        # Load pricing (can be overridden in config)
        self.pricing = config.get("llm_pricing", LLM_PRICING)

    def generate_call_id(self, call_type: str) -> str:
        """Generate a unique call ID: YYYYMMDD_HHMMSS_CALLTYPE_SEQ."""
        now = datetime.now()
        ts = now.strftime("%Y%m%d_%H%M%S")
        key = f"{ts}_{call_type}"
        self._seq_counter[key] = self._seq_counter.get(key, 0) + 1
        seq = f"{self._seq_counter[key]:03d}"
        return f"{ts}_{call_type}_{seq}"

    def save_prompt(self, call_id: str, system_prompt: str,
                    user_prompt: str) -> tuple:
        """
        Save system prompt (versioned) and user prompt (per-call) to files.
        Returns (system_prompt_file, user_prompt_file).
        """
        # System prompt: save with version hash, reuse if unchanged
        sys_file = self._save_system_prompt(system_prompt)

        # User prompt: always save per-call
        user_file = os.path.join(self.llm_dir, "prompts", f"{call_id}.txt")
        with open(user_file, "w") as f:
            f.write(user_prompt)

        return sys_file, user_file

    def _save_system_prompt(self, system_prompt: str) -> str:
        """Save system prompt if it's new, return path to the versioned file."""
        import hashlib
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:12]
        sys_file = os.path.join(self.llm_dir, "system",
                                f"system_prompt_{prompt_hash}.txt")
        if not os.path.exists(sys_file):
            with open(sys_file, "w") as f:
                f.write(system_prompt)
        return sys_file

    def save_response(self, call_id: str, raw_response: dict) -> str:
        """Save the complete raw API response as JSON."""
        resp_file = os.path.join(self.llm_dir, "responses", f"{call_id}.json")
        with open(resp_file, "w") as f:
            json.dump(raw_response, f, indent=2, default=str)
        return resp_file

    def save_error_response(self, call_id: str, error: Exception,
                            http_status: int = None) -> str:
        """Save error details when an API call fails."""
        resp_file = os.path.join(self.llm_dir, "responses", f"{call_id}.json")
        with open(resp_file, "w") as f:
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
        """Compute cost in INR for a given token usage."""
        rates = self.pricing.get(model, {})
        if not rates:
            raise ValueError(f"Unknown model for pricing: {model}")

        input_cost = (input_tokens / 1_000_000) * rates["input_per_1m"]
        output_cost = (output_tokens / 1_000_000) * rates["output_per_1m"]
        cache_read_cost = (cache_read_tokens / 1_000_000) * rates["cache_read_per_1m"]
        cache_create_cost = (cache_creation_tokens / 1_000_000) * rates["cache_create_per_1m"]

        return {
            "input_cost_inr": round(input_cost, 4),
            "output_cost_inr": round(output_cost, 4),
            "cache_read_cost_inr": round(cache_read_cost, 4),
            "cache_creation_cost_inr": round(cache_create_cost, 4),
            "total_cost_inr": round(
                input_cost + output_cost + cache_read_cost + cache_create_cost, 4
            ),
        }

    def log_call(self, call_id: str, session_id: str, model: str,
                 call_type: str, response: dict, latency_ms: int,
                 prompt_file: str, response_file: str,
                 system_prompt_file: str = None,
                 parent_call_id: str = None,
                 call_subtype: str = None,
                 # Decision metadata (optional)
                 market_bias: str = None, decisions_count: int = 0,
                 watchlist_symbols: str = None,
                 actions_summary: str = None,
                 trade_ids: str = None,
                 # Error info
                 status: str = "SUCCESS",
                 error_message: str = None,
                 http_status_code: int = 200,
                 ) -> LLMCallRecord:
        """
        Log a complete LLM call to both DB and CSV.
        `response` is the raw API response dict.
        Returns the LLMCallRecord for downstream use.
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
            cache_read_tokens, cache_creation_tokens
        )

        # Build record
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

        # Write to DB
        self._write_to_db(record)

        # Write to immutable CSV
        self._write_to_csv(record)

        return record

    def log_failed_call(self, call_id: str, session_id: str, model: str,
                        call_type: str, error: Exception,
                        prompt_file: str, response_file: str,
                        latency_ms: int = 0,
                        http_status_code: int = None,
                        **kwargs) -> LLMCallRecord:
        """Convenience method for logging failed API calls."""
        # For failed calls, token counts may be 0
        status = "TIMEOUT" if "timeout" in str(error).lower() else \
                 "RATE_LIMITED" if http_status_code == 429 else "ERROR"

        return self.log_call(
            call_id=call_id,
            session_id=session_id,
            model=model,
            call_type=call_type,
            response={"usage": {}, "stop_reason": None},  # empty response
            latency_ms=latency_ms,
            prompt_file=prompt_file,
            response_file=response_file,
            status=status,
            error_message=str(error),
            http_status_code=http_status_code,
            **kwargs,
        )

    def _write_to_db(self, record: LLMCallRecord):
        """Insert record into llm_calls table."""
        self.db.execute("""
            INSERT INTO llm_calls (
                call_id, session_id, parent_call_id,
                timestamp, date, day_number, response_timestamp, latency_ms,
                model, call_type, call_subtype,
                input_tokens, output_tokens, cache_read_tokens,
                cache_creation_tokens,
                input_cost_inr, output_cost_inr, cache_read_cost_inr,
                cache_creation_cost_inr,
                system_prompt_file, user_prompt_file, response_file,
                parsed_output_file,
                status, error_message, http_status_code, stop_reason,
                market_bias, decisions_count, watchlist_symbols,
                actions_summary, trade_ids
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            record.call_id, record.session_id, record.parent_call_id,
            record.timestamp, record.date, record.day_number,
            record.response_timestamp, record.latency_ms,
            record.model, record.call_type, record.call_subtype,
            record.input_tokens, record.output_tokens,
            record.cache_read_tokens, record.cache_creation_tokens,
            record.input_cost_inr, record.output_cost_inr,
            record.cache_read_cost_inr, record.cache_creation_cost_inr,
            record.system_prompt_file, record.user_prompt_file,
            record.response_file, record.parsed_output_file,
            record.status, record.error_message, record.http_status_code,
            record.stop_reason,
            record.market_bias, record.decisions_count,
            record.watchlist_symbols, record.actions_summary,
            record.trade_ids,
        ))

    def _write_to_csv(self, record: LLMCallRecord):
        """Append record to immutable daily CSV."""
        filepath = os.path.join(
            self.llm_dir, f"llm_calls_{record.date}.csv"
        )
        lock = FileLock(filepath + ".lock")

        with lock:
            file_exists = os.path.exists(filepath)
            with open(filepath, "a", newline="") as f:
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
                    "total_cost_inr": record.total_cost_inr,
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

    def rebuild_daily_costs(self, date_str: str = None):
        """
        Rebuild the llm_daily_costs table row for a given date.
        Called at end of day during post-market processing.
        Also appends to the immutable costs_daily.csv.
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        self.db.execute("""
            INSERT OR REPLACE INTO llm_daily_costs (
                date, day_number,
                haiku_calls, haiku_input_tokens, haiku_output_tokens, haiku_cost_inr,
                sonnet_calls, sonnet_input_tokens, sonnet_output_tokens, sonnet_cost_inr,
                opus_calls, opus_input_tokens, opus_output_tokens, opus_cost_inr,
                news_calls, news_cost_inr,
                pulse_calls, pulse_cost_inr,
                decision_calls, decision_cost_inr,
                eod_calls, eod_cost_inr,
                premarket_calls, premarket_cost_inr,
                retry_calls, retry_cost_inr,
                total_calls, total_input_tokens, total_output_tokens,
                total_tokens, total_cost_inr,
                total_cache_read_tokens, cache_savings_inr,
                failed_calls, retry_count
            )
            SELECT
                date, MAX(day_number),
                -- Per model
                SUM(CASE WHEN model LIKE '%haiku%' THEN 1 ELSE 0 END),
                SUM(CASE WHEN model LIKE '%haiku%' THEN input_tokens ELSE 0 END),
                SUM(CASE WHEN model LIKE '%haiku%' THEN output_tokens ELSE 0 END),
                SUM(CASE WHEN model LIKE '%haiku%' THEN total_cost_inr ELSE 0 END),
                SUM(CASE WHEN model LIKE '%sonnet%' THEN 1 ELSE 0 END),
                SUM(CASE WHEN model LIKE '%sonnet%' THEN input_tokens ELSE 0 END),
                SUM(CASE WHEN model LIKE '%sonnet%' THEN output_tokens ELSE 0 END),
                SUM(CASE WHEN model LIKE '%sonnet%' THEN total_cost_inr ELSE 0 END),
                SUM(CASE WHEN model LIKE '%opus%' THEN 1 ELSE 0 END),
                SUM(CASE WHEN model LIKE '%opus%' THEN input_tokens ELSE 0 END),
                SUM(CASE WHEN model LIKE '%opus%' THEN output_tokens ELSE 0 END),
                SUM(CASE WHEN model LIKE '%opus%' THEN total_cost_inr ELSE 0 END),
                -- Per call type
                SUM(CASE WHEN call_type = 'NEWS_SUMMARY' THEN 1 ELSE 0 END),
                SUM(CASE WHEN call_type = 'NEWS_SUMMARY' THEN total_cost_inr ELSE 0 END),
                SUM(CASE WHEN call_type = 'MARKET_PULSE' THEN 1 ELSE 0 END),
                SUM(CASE WHEN call_type = 'MARKET_PULSE' THEN total_cost_inr ELSE 0 END),
                SUM(CASE WHEN call_type = 'TRADING_DECISION' THEN 1 ELSE 0 END),
                SUM(CASE WHEN call_type = 'TRADING_DECISION' THEN total_cost_inr ELSE 0 END),
                SUM(CASE WHEN call_type = 'EOD_REVIEW' THEN 1 ELSE 0 END),
                SUM(CASE WHEN call_type = 'EOD_REVIEW' THEN total_cost_inr ELSE 0 END),
                SUM(CASE WHEN call_type = 'PRE_MARKET' THEN 1 ELSE 0 END),
                SUM(CASE WHEN call_type = 'PRE_MARKET' THEN total_cost_inr ELSE 0 END),
                SUM(CASE WHEN call_type = 'RETRY' THEN 1 ELSE 0 END),
                SUM(CASE WHEN call_type = 'RETRY' THEN total_cost_inr ELSE 0 END),
                -- Totals
                COUNT(*),
                SUM(input_tokens),
                SUM(output_tokens),
                SUM(input_tokens + output_tokens),
                SUM(total_cost_inr),
                -- Cache
                SUM(cache_read_tokens),
                SUM(cache_read_cost_inr),  -- approximate savings
                -- Errors
                SUM(CASE WHEN status != 'SUCCESS' THEN 1 ELSE 0 END),
                SUM(CASE WHEN call_type = 'RETRY' THEN 1 ELSE 0 END)
            FROM llm_calls
            WHERE date = ?
        """, (date_str,))

    def get_daily_cost(self, date_str: str = None) -> dict:
        """Get cost summary for a specific day. Useful for Telegram reports."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
        row = self.db.fetchone(
            "SELECT * FROM llm_daily_costs WHERE date = ?", (date_str,)
        )
        return dict(row) if row else {}

    def get_experiment_total_cost(self) -> float:
        """Get total LLM cost for the entire experiment so far."""
        row = self.db.fetchone(
            "SELECT SUM(total_cost_inr) as total FROM llm_calls"
        )
        return row["total"] if row and row["total"] else 0.0

    def link_trades(self, call_id: str, trade_ids: list):
        """
        After guardrail validation + execution, link trade IDs back to the
        LLM call that generated them. This closes the audit loop.
        """
        trade_ids_str = ",".join(str(tid) for tid in trade_ids)
        self.db.execute(
            "UPDATE llm_calls SET trade_ids = ? WHERE call_id = ?",
            (trade_ids_str, call_id)
        )
```

### 16.3C Sample Queries for Audit & Cost Analysis

These queries run on the `llm_calls` table and views. Use them in the
Streamlit dashboard or for post-experiment analysis.

```sql
-- ═══════════════════════════════════════════
-- COST ANALYSIS
-- ═══════════════════════════════════════════

-- Total cost by model (experiment to date)
SELECT
    CASE
        WHEN model LIKE '%opus%' THEN 'Opus'
        WHEN model LIKE '%sonnet%' THEN 'Sonnet'
        WHEN model LIKE '%haiku%' THEN 'Haiku'
    END AS model_name,
    COUNT(*) AS total_calls,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    ROUND(SUM(total_cost_inr), 2) AS total_cost_inr,
    ROUND(AVG(total_cost_inr), 2) AS avg_cost_per_call
FROM llm_calls
WHERE status = 'SUCCESS'
GROUP BY model_name
ORDER BY total_cost_inr DESC;

-- Cost by call type (where is the money going?)
SELECT
    call_type,
    COUNT(*) AS calls,
    ROUND(SUM(total_cost_inr), 2) AS total_cost,
    ROUND(AVG(total_cost_inr), 2) AS avg_cost,
    ROUND(AVG(latency_ms), 0) AS avg_latency_ms
FROM llm_calls
WHERE status = 'SUCCESS'
GROUP BY call_type
ORDER BY total_cost DESC;

-- Daily cost trend
SELECT date, day_number, total_calls, total_cost_inr, trading_pnl_inr,
       ROUND(cumulative_cost_inr, 2) AS cumulative_cost
FROM llm_daily_costs
ORDER BY date;

-- Cache savings analysis
SELECT
    date,
    SUM(cache_read_tokens) AS cached_tokens,
    SUM(input_tokens) AS total_input,
    ROUND(100.0 * SUM(cache_read_tokens) / NULLIF(SUM(input_tokens), 0), 1)
        AS cache_hit_pct,
    ROUND(SUM(cache_read_cost_inr), 2) AS cache_savings_inr
FROM llm_calls
GROUP BY date
ORDER BY date;

-- ═══════════════════════════════════════════
-- DECISION TRACING ("What happened at 10:30 AM?")
-- ═══════════════════════════════════════════

-- Follow a complete decision cycle (session trace)
SELECT call_type, model, timestamp, latency_ms,
       input_tokens, output_tokens, total_cost_inr,
       watchlist_symbols, actions_summary, decisions_count,
       user_prompt_file, response_file
FROM v_session_trace
WHERE session_id = 'sess_103000'
ORDER BY timestamp;

-- Find all LLM calls that led to actual trades
SELECT lc.call_id, lc.call_type, lc.timestamp, lc.model,
       lc.actions_summary, lc.total_cost_inr,
       lc.user_prompt_file, lc.response_file,
       lc.trade_ids
FROM llm_calls lc
WHERE lc.trade_ids IS NOT NULL AND lc.trade_ids != ''
ORDER BY lc.timestamp DESC;

-- View the prompt and response files for a specific call
SELECT call_id, user_prompt_file, response_file, system_prompt_file
FROM llm_calls
WHERE call_id = '20260301_092700_DECISION_001';

-- ═══════════════════════════════════════════
-- ERROR ANALYSIS
-- ═══════════════════════════════════════════

-- All failed calls
SELECT timestamp, call_id, model, call_type, status, error_message,
       http_status_code, latency_ms
FROM llm_calls
WHERE status != 'SUCCESS'
ORDER BY timestamp DESC;

-- Error rate by model
SELECT model,
       COUNT(*) AS total_calls,
       SUM(CASE WHEN status != 'SUCCESS' THEN 1 ELSE 0 END) AS failures,
       ROUND(100.0 * SUM(CASE WHEN status != 'SUCCESS' THEN 1 ELSE 0 END)
             / COUNT(*), 1) AS failure_pct
FROM llm_calls
GROUP BY model;

-- ═══════════════════════════════════════════
-- WATCHLIST QUALITY ANALYSIS
-- ═══════════════════════════════════════════

-- What stocks did Claude pick most often in Market Pulse?
-- (Requires post-processing of watchlist_symbols field)

-- Which Market Pulse calls led to trades?
SELECT
    p.call_id AS pulse_call_id,
    p.timestamp AS pulse_time,
    p.watchlist_symbols,
    d.call_id AS decision_call_id,
    d.actions_summary,
    d.decisions_count,
    d.trade_ids
FROM llm_calls p
JOIN llm_calls d ON d.parent_call_id = p.call_id
WHERE p.call_type = 'MARKET_PULSE'
  AND d.call_type = 'TRADING_DECISION'
  AND d.decisions_count > 0
ORDER BY p.timestamp DESC;
```

#### File Permissions (Read-Only After Write)

After each trading day is complete, the post-market process should set log files
to read-only:

```python
import os
import stat

def lock_daily_logs(date_str):
    """Make the day's log files read-only after market close."""
    files = [
        f"logs/trades/trades_{date_str}.csv",
        f"logs/guardrails/guardrails_{date_str}.csv",
        f"logs/llm/llm_calls_{date_str}.csv",
    ]
    # Also lock all prompt and response files for that date
    for subdir in ["prompts", "responses"]:
        dirpath = f"logs/llm/{subdir}/"
        if os.path.exists(dirpath):
            for fname in os.listdir(dirpath):
                if fname.startswith(date_str.replace("-", "")):
                    files.append(os.path.join(dirpath, fname))

    for filepath in files:
        if os.path.exists(filepath):
            # Remove write permission for owner, group, others
            os.chmod(filepath, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
```

#### Log Directory Structure
```
logs/
├── trades/                          # Immutable trade records
│   ├── trades_2026-03-01.csv
│   └── ...
├── pnl/                             # Daily P&L summary
│   └── pnl_daily.csv
├── guardrails/                      # Every guardrail check
│   ├── guardrails_2026-03-01.csv
│   └── ...
├── llm/                             # ═══ LLM AUDIT TRAIL (all AI interactions) ═══
│   ├── system/                      # System prompts (versioned, deduplicated)
│   │   ├── system_prompt_a1b2c3.txt # Hash-named; reused across calls
│   │   ├── system_prompt_d4e5f6.txt # New version if you update mid-experiment
│   │   └── haiku_news_7g8h9i.txt    # Haiku news summarization prompt
│   │
│   ├── prompts/                     # Every user prompt (one file per API call)
│   │   ├── 20260301_084015_NEWS_001.txt
│   │   ├── 20260301_092200_PULSE_001.txt
│   │   ├── 20260301_092700_DECISION_001.txt
│   │   └── ...
│   │
│   ├── responses/                   # Every raw API response (one file per call)
│   │   ├── 20260301_084015_NEWS_001.json
│   │   ├── 20260301_092200_PULSE_001.json
│   │   ├── 20260301_092700_DECISION_001.json
│   │   └── ...
│   │
│   ├── llm_calls_2026-03-01.csv     # Immutable daily CSV of all LLM calls
│   ├── llm_calls_2026-03-02.csv
│   └── costs_daily.csv              # Running daily cost summary
│
└── app.log                          # Application runtime log
```

### 16.4 Telegram Notifications

Send alerts for:
- Trade executed (BUY/SELL with price, quantity, reasoning summary)
- Stop-loss triggered
- Daily loss limit hit
- Guardrail blocked a trade (with reason)
- Daily P&L summary (post-market) — includes today's LLM cost and cumulative cost
- LLM cost alert: if daily LLM cost exceeds configurable threshold (e.g., ₹800)
- LLM error alert: if API call fails or returns INVALID_JSON
- System errors (API failure, connection drop)
- Drawdown warnings (10%, 15%)
- Experiment milestones (Day 10, Day 20, Final Day)

### 16.5 Dashboard (Streamlit — Optional)

Build a simple Streamlit app for real-time monitoring:
- Current portfolio state (holdings, cash, deployed %)
- Today's trades (with Claude's reasoning)
- Running P&L (daily + cumulative chart)
- Win rate and performance metrics
- Guardrail trigger history
- Claude's current market assessment
- **LLM Cost Dashboard:**
  - Today's cost breakdown by model (Haiku / Sonnet / Opus)
  - Today's cost breakdown by call type (News / Pulse / Decision / EOD)
  - Daily cost trend chart (experiment to date)
  - Cumulative cost vs cumulative trading P&L chart
  - Token usage heatmap (which hours consume most tokens)
  - Cache hit rate and savings
  - Failed call count and error log
  - Per-call drill-down: click any row to see the full prompt and response files

### 16.6 Backup & Disaster Recovery

The SQLite DB and CSV logs are all on a single VPS. If the disk fails, you
lose everything — including the "ground truth" audit trail.

**Daily Automated Backup:**
```
RULE: Every day after post-market processing (4:00 PM), automatically back up:
      - logs/ directory (entire tree — CSVs, JSONL, prompts, responses)
      - data/trading_bot.db (SQLite database)
      - config/config.yaml (in case you made changes during the day)
RULE: Backup to at least ONE off-site location:
      - Option A: S3 bucket (cheapest, ~₹50/month for this volume)
      - Option B: Google Drive (free, use rclone for automation)
      - Option C: Daily tarball emailed to yourself (simple but limited)
RULE: Keep last 7 daily backups locally in backups/ directory
RULE: Keep last 30 daily backups in off-site storage
RULE: Test restore from backup at least once before going live
```

**Implementation:**
```python
import subprocess
import shutil
from datetime import datetime

def daily_backup(config):
    """Run after post-market processing at 4:00 PM."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    backup_dir = f"backups/{date_str}"
    os.makedirs(backup_dir, exist_ok=True)

    # Copy critical files
    shutil.copytree("logs/", f"{backup_dir}/logs/", dirs_exist_ok=True)
    shutil.copy2("data/trading_bot.db", f"{backup_dir}/trading_bot.db")
    shutil.copy2("config/config.yaml", f"{backup_dir}/config.yaml")

    # Create tarball
    tarball = f"backups/backup_{date_str}.tar.gz"
    subprocess.run(["tar", "-czf", tarball, backup_dir], check=True)

    # Push to off-site (example: rclone to Google Drive)
    # subprocess.run(["rclone", "copy", tarball, "gdrive:trading-bot-backups/"])

    # Clean up old local backups (keep last 7)
    cleanup_old_backups("backups/", keep=7)

    return tarball
```

### 16.7 Human Veto Mode (Phase 4)

During Phase 4 (Semi-Auto), the bot sends a Telegram notification BEFORE
executing each trade, giving you a 60-second window to cancel.

```python
class VetoMode:
    """
    Sends trade details via Telegram and waits for a VETO response.
    If no VETO received within the timeout, the trade executes.
    """

    def __init__(self, telegram_bot, config):
        self.bot = telegram_bot
        self.timeout_seconds = config.get("veto_timeout_seconds", 60)
        self.enabled = config.get("veto_mode_enabled", False)

    async def request_approval(self, order: dict) -> bool:
        """
        Send trade details and wait for veto.
        Returns True if trade should proceed, False if vetoed.
        """
        if not self.enabled:
            return True  # veto mode disabled, auto-approve

        message = (
            f"🔔 TRADE PENDING APPROVAL\n"
            f"{order['transaction_type']} {order['symbol']} "
            f"x{order['quantity']} @ ₹{order['price']}\n"
            f"Product: {order['product']} | SL: ₹{order.get('stop_loss')}\n"
            f"Target: ₹{order.get('target')}\n"
            f"Confidence: {order.get('confidence')}\n"
            f"Reason: {order.get('reasoning', '')[:100]}\n\n"
            f"Reply VETO within {self.timeout_seconds}s to cancel.\n"
            f"No reply = auto-execute."
        )
        self.bot.send_message(message)

        # Wait for response
        veto_received = await self.bot.wait_for_reply(
            timeout=self.timeout_seconds,
            expected="VETO"
        )

        if veto_received:
            self.bot.send_message(f"❌ VETOED: {order['symbol']} trade cancelled.")
            return False
        else:
            self.bot.send_message(f"✅ No veto. Executing {order['symbol']} trade.")
            return True
```

---

## 17. PHASED ROLLOUT PLAN

| Phase | Duration | Capital | What Happens |
|---|---|---|---|
| **Phase 1: Build** | 1-2 weeks | ₹0 | Build entire system. Unit test each module. No market data needed yet. |
| **Phase 2: Paper Trading** | 1-2 weeks | ₹0 (simulated ₹50K-1L) | Full system runs on live market data. Orders go to local DB. Validate pipeline end-to-end. Fix bugs. |
| **Phase 3: Micro-Live** | 3-5 days | ₹10,000-20,000 | Deploy small capital. Max 2-3 trades/day. Manual approval via Telegram (Claude suggests, you confirm). |
| **Phase 4: Semi-Auto (Veto Mode)** | 1-2 weeks | ₹50,000 | Autonomous trading with tight guardrails. Bot sends a Telegram notification BEFORE each trade with a 60-second veto window — reply "VETO" to cancel. If no reply in 60s, trade executes. This gives you a safety net during the transition without slowing things down significantly. Monitor daily. |
| **Phase 5: Full Experiment** | 1 month | ₹50,000-1,00,000 | Full autonomous run. The actual experiment. |

### Phase Transitions
- Phase 1 → 2: All modules pass unit tests, config is complete
- Phase 2 → 3: 5+ paper trading days with no crashes, reasonable decisions from Claude
- Phase 3 → 4: All micro-live trades executed correctly, no guardrail bugs
- Phase 4 → 5: Comfortable with system behavior, no unexpected issues



## 18. ESTIMATED COSTS

### Monthly Operating Costs

| Item | Cost (Monthly) | Notes |
|---|---|---|
| Kite Connect API | ₹2,000 | Fixed subscription |
| Anthropic API (tiered) | ₹6,800-14,400 | Opus for decisions + EOD, Sonnet for Market Pulse, Haiku for news |
| Cloud VM (VPS) | ₹500-1,500 | AWS Lightsail / DigitalOcean |
| Zerodha Brokerage | ₹200-500 | ₹20/intraday trade, ₹0 for delivery. Bot self-exits MIS positions to avoid ₹50+GST auto-square-off penalty. |
| Off-site Backup (S3/GDrive) | ₹0-100 | Google Drive free via rclone, or S3 ~₹50/month |
| Telegram Bot | ₹0 | Free |
| **Total Overhead** | **₹9,500-18,500/month** |

### Break-Even Analysis
With ₹1,00,000 capital and ₹14,000/month overhead:
- Need 14% monthly return just to cover costs
- This is aggressive — the experiment should be treated as a learning cost
- The value is in understanding Claude's decision-making, not in profits
- The Market Pulse layer adds ~₹30-95/day but gives Claude full autonomy,
  which is the entire point of the experiment

### Cost Optimization Levers
1. Use Sonnet instead of Opus for midday trading calls (saves 60-70% on those calls)
2. Reduce Market Pulse frequency from 30 min to 45-60 min (fewer Sonnet calls)
3. Cap watchlist at 8-10 stocks instead of 15 (reduces Opus tokens)
4. Use prompt caching for the system prompt (saves on repeated input tokens)
5. Run on a home machine instead of cloud VM (saves ₹500-1,500)
6. Skip Market Pulse if market hasn't moved significantly (VIX stable, indices
   within 0.2% of last check)


---

## 19. PROJECT DIRECTORY STRUCTURE

```
ai-trading-bot/
├── config/
│   ├── config.yaml              # All configurable parameters
│   ├── etf_list.yaml            # Approved ETF symbols and metadata
│   ├── sector_mapping.yaml      # Stock → sector → peers mapping
│   └── .env                     # API keys (NEVER commit to git)
│
├── src/
│   ├── __init__.py
│   ├── main.py                  # Orchestrator / main loop
│   │
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── kite_client.py       # Kite Connect wrapper (auth, quotes, orders)
│   │   ├── kite_auth.py         # Daily authentication handler
│   │   └── instruments.py       # Instrument list management
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── market_data.py       # Historical + live data fetching from Kite
│   │   ├── indicators.py        # Technical indicator computation (pandas-ta)
│   │   ├── data_warehouse.py    # Bulk data storage for entire universe (Layer 2)
│   │   ├── market_pulse.py      # Aggregates movers, losers, volume surges, sectors
│   │   ├── deep_dive.py         # Assembles full data pack for Claude-selected stocks
│   │   ├── levels.py            # Support/resistance/pivot computation
│   │   ├── patterns.py          # Candlestick pattern detection
│   │   └── universe.py          # Universe filtering (Layer 1)
│   │
│   ├── news/
│   │   ├── __init__.py
│   │   ├── rss_fetcher.py       # RSS feed fetching (MoneyControl, ET, etc.)
│   │   ├── bse_announcements.py # BSE corporate announcement fetcher
│   │   ├── corporate_actions.py # Corporate action calendar (ex-dates, splits, bonuses)
│   │   ├── macro_data.py        # FII/DII, global cues, VIX
│   │   └── summarizer.py        # Claude Haiku news summarization
│   │
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── pulse_prompt_builder.py   # Builds the Market Pulse prompt (Sonnet)
│   │   ├── decision_prompt_builder.py # Builds the Trading Decision prompt (Opus)
│   │   ├── claude_client.py     # Anthropic API wrapper (handles all 3 models)
│   │   ├── response_parser.py   # Parses Claude's JSON responses (both types)
│   │   ├── watchlist_manager.py # Tracks Claude's watchlist across cycles
│   │   ├── llm_logger.py        # LLM interaction audit logger (Section 16.3B)
│   │   └── system_prompt.py     # Stores the system prompt text
│   │
│   ├── trading/
│   │   ├── __init__.py
│   │   ├── guardrails.py        # Guardrail validation engine
│   │   ├── execution.py         # Order execution (paper + live modes)
│   │   ├── mis_exit_engine.py   # 3-stage MIS auto-exit (avoids ₹50+GST penalty)
│   │   ├── portfolio.py         # Mode-blind portfolio state manager
│   │   ├── risk_manager.py      # Daily loss limits, drawdown, position sizing
│   │   ├── position_tracker.py  # Track SL, targets, hold durations
│   │   ├── trade_logger.py      # Append-only CSV trade logger (immutable audit trail)
│   │   ├── order_reconciler.py  # Order fill verification + SL/target placement
│   │   ├── sl_health_check.py   # Periodic broker-side SL/target verification
│   │   ├── circuit_breaker.py   # Claude API circuit breaker (safe mode)
│   │   ├── corporate_actions.py # Corporate action calendar filter
│   │   ├── veto_mode.py         # Human veto via Telegram (Phase 4)
│   │   └── prompt_size_mgr.py   # Prompt splitting when watchlist exceeds token limit
│   │
│   ├── notifications/
│   │   ├── __init__.py
│   │   └── telegram_bot.py      # Telegram notification sender
│   │
│   └── database/
│       ├── __init__.py
│       ├── db.py                # SQLite connection + queries
│       ├── models.py            # Table definitions / ORM models
│       └── migrations.py        # Schema creation scripts
│
├── logs/
│   ├── trades/                  # Immutable CSV trade records (one per day)
│   ├── pnl/                     # Daily P&L summary (append-only)
│   ├── guardrails/              # Every guardrail validation (one per day)
│   ├── llm/                     # ═══ LLM AUDIT TRAIL ═══
│   │   ├── system/              # Versioned system prompts (hash-named)
│   │   ├── prompts/             # Every user prompt sent to any model
│   │   │   ├── 20260301_084015_NEWS_001.txt
│   │   │   ├── 20260301_092200_PULSE_001.txt
│   │   │   ├── 20260301_092700_DECISION_001.txt
│   │   │   └── ...
│   │   ├── responses/           # Every raw API response JSON
│   │   │   ├── 20260301_084015_NEWS_001.json
│   │   │   ├── 20260301_092200_PULSE_001.json
│   │   │   ├── 20260301_092700_DECISION_001.json
│   │   │   └── ...
│   │   ├── llm_calls_2026-03-01.csv   # Immutable daily call log
│   │   └── costs_daily.csv            # Running daily cost summary
│   └── app.log                  # Application runtime log
│
├── data/
│   ├── trading_bot.db           # SQLite database
│   ├── instruments_cache.csv    # Cached instrument list
│   ├── asm_gsm_list.csv         # ASM/GSM restricted stocks
│   └── corporate_actions.csv    # Cached corporate actions calendar
│
├── backups/
│
├── dashboard/
│   └── app.py                   # Streamlit dashboard
│
├── tests/
│   ├── test_guardrails.py
│   ├── test_market_pulse.py     # Test Market Pulse prompt builder + response parser
│   ├── test_deep_dive.py        # Test deep dive data assembly
│   ├── test_watchlist_manager.py
│   ├── test_llm_logger.py       # Test LLM audit logging, cost calculation, file storage
│   ├── test_prompt_builder.py
│   ├── test_execution.py
│   └── test_indicators.py
│
├── scripts/
│   ├── setup_db.py              # Initialize database
│   ├── backfill_data.py         # Download historical data
│   └── generate_report.py       # Generate experiment report
│
├── requirements.txt
├── README.md
└── .gitignore
```


---

## 20. KEY RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|---|---|---|
| **Kite token expiry** | Bot can't trade | Auto-detect auth failure, send Telegram alert, implement TOTP-based auto-login if possible |
| **Claude hallucinating stock symbols** | Invalid order placed | Always validate symbol against instrument list in guardrails |
| **Claude suggesting F&O or commodities** | SEBI violation | Hard-coded guardrail blocks non-equity instruments |
| **Market Pulse returns invalid watchlist** | No stocks to analyze | Validate Sonnet response. If invalid, retry once. If still invalid, fall back to previous cycle's watchlist. |
| **Claude requests stocks outside universe** | Data not available | Validate watchlist against eligible universe. Drop invalid symbols, log them, continue with valid ones. |
| **Sonnet and Opus disagree** | Watchlist doesn't match trading intent | This is expected and fine. Sonnet selects based on surface signals; Opus analyzes deeply and may pass on all of them. Logged for experiment analysis. |
| **Watchlist stagnation** | Claude keeps picking same stocks | Log watchlist diversity metrics. If < 30% turnover across 5 cycles, flag in Telegram. Consider adding "at least 2 new stocks per cycle" soft guidance. |
| **API rate limits (Kite)** | Data fetching fails | Implement rate limiting with backoff, cache aggressively. Bulk data collection is rate-limit aware. |
| **API rate limits (Anthropic)** | Trading decisions delayed | Implement retry with exponential backoff, fall back to Sonnet |
| **Claude API down during market hours** | No trading decisions | Circuit breaker activates safe mode after 15 min. Existing broker-side SL/target orders protect positions. No new trades until API recovers. See Section 15C. |
| **Network failure during open positions** | Uncontrolled losses | 3-stage MIS exit as independent APScheduler jobs. Broker-side SL/target orders protect CNC positions. Health check every 5 min. |
| **Claude outputs invalid JSON** | Parse error, no trades | Implement JSON parsing with error handling, retry once, log failure |
| **Slippage** | Execution at worse price | Prefer LIMIT orders over MARKET. Account for ATR-based slippage in paper trading simulation |
| **Over-trading** | High brokerage, poor returns | Max 12 trades/day cap enforced in guardrails |
| **Drawdown spiral** | Significant capital loss | Hard stop at 15% drawdown, reduced trading at 10% |
| **System crash** | Missed trades or stuck positions | Health check script restarts on failure. Broker-side SL/target orders protect positions. |
| **Stale data** | Decisions based on old prices | Timestamp every data point. Reject decisions if data is > 5 min old for intraday. |
| **News data poisoning** | Claude misreads fake/wrong news | Use trusted sources only (MoneyControl, ET, BSE). Cross-reference multiple sources. |
| **Weekend/holiday gaps** | Positions gap up/down at open | Don't hold positions over long weekends. Be cautious on Fridays. |
| **Circuit limits (upper/lower)** | Orders won't fill | Guardrail checks if stock is at/near circuit limit before placing orders. |
| **Corporate actions** | Misleading price movements | Corporate actions filter (Section 15E) flags ex-date stocks. Market Pulse includes corporate actions section so Claude is aware. |
| **Duplicate orders** | Double position, excess risk | Duplicate order detection in guardrails with 5-min window. Kite order tags. |
| **Uncalibrated confidence scores** | Bad trades pass, good trades blocked | Track confidence vs outcomes during paper trading. If uncorrelated, adjust or remove threshold. |
| **Prompt size explosion** | Token costs blow up, context truncation | Two-stage pipeline naturally limits prompt size. Prompt size manager splits watchlist if > 15 stocks. (Section 15G) |
| **Data loss (disk failure)** | Lose audit trail and trade history | Daily automated backups (Section 16.6). CSV logs are ground truth. |
| **SL/target order missing on broker** | Unprotected position | SL Health Check (Section 15F) runs every 5 min, verifies and re-places missing orders. |
| **Bulk data computation too slow** | Stale indicators in prompt | Profile indicator computation. Pre-compute and cache. Use vectorized pandas-ta operations. Target < 30 seconds for full universe refresh. |


---

## APPENDIX A: CONFIG FILE TEMPLATE (config.yaml)

```yaml
# AI Trading Bot Configuration

experiment:
  start_date: "2026-03-01"          # Experiment start date
  duration_days: 30                  # Calendar days
  starting_capital: 100000           # INR

trading:
  mode: "PAPER"                      # PAPER or LIVE
  exchanges: ["NSE", "BSE"]
  products: ["CNC", "MIS"]
  max_trades_per_day: 12
  max_position_pct: 0.20             # 20% of portfolio per position
  max_deployed_pct: 0.80             # 80% max deployment
  min_cash_buffer_pct: 0.20          # 20% min cash
  max_cnc_hold_days: 15              # Max swing trade duration
  unwind_phase_days: 5               # Last N days = unwind only
  min_stock_price: 20                # ₹20 minimum
  min_daily_volume_cr: 1.0           # ₹1 Cr minimum daily volume
  no_new_mis_after: "14:30"          # No new intraday after 2:30 PM
  mis_squareoff_start: "15:00"       # Begin MIS square-off at 3:00 PM
  mis_squareoff_hard_deadline: "15:10"  # All MIS MUST be closed by 3:10 PM
  mis_emergency_market_close: "15:12"   # Force MARKET close if anything still open
  # NEVER rely on Zerodha auto-square-off (3:20 PM) — it charges ₹50+GST per position

risk:
  daily_loss_limit_pct: 0.03         # 3% of capital
  drawdown_reduce_pct: 0.10          # 10% → intraday only, half size
  drawdown_halt_pct: 0.15            # 15% → halt all trading
  default_sl_pct: 0.02               # 2% stop-loss
  min_sl_pct: 0.005                  # 0.5% minimum SL
  max_sl_pct: 0.05                   # 5% maximum SL
  min_confidence: 0.50               # Don't trade below this confidence
  min_risk_reward: 1.5               # Minimum risk-reward ratio

resilience:
  claude_safe_mode_timeout_min: 15   # If no successful Claude call in 15 min, enter safe mode
  sl_health_check_interval_min: 5    # Verify broker-side SL orders every 5 min
  duplicate_order_window_min: 5      # Block duplicate orders within 5 min
  max_prompt_tokens: 12000           # If prompt exceeds this, split watchlist across calls
  daily_backup_enabled: true
  backup_destination: "backups/"

corporate_actions:
  check_enabled: true
  exclude_on_exdate: true

# === CLAUDE-DRIVEN PIPELINE SETTINGS ===
pipeline:
  market_pulse_model: "claude-sonnet-4-5-20250929"    # Model for Market Pulse (watchlist selection)
  market_pulse_interval_minutes: 30                    # How often to run Market Pulse
  max_watchlist_size: 15                                # Max stocks Claude can request per pulse
  min_watchlist_size: 3                                 # Min stocks (held positions always included)
  always_include_held: true                             # Always include held positions in watchlist
  watchlist_fallback: "previous"                        # If Pulse fails: "previous" or "top_movers"
  pulse_skip_if_stable: false                           # Skip Pulse if market hasn't moved much
  pulse_skip_threshold_pct: 0.2                         # Index must move > 0.2% to trigger re-scan

  # Data infrastructure
  bulk_indicator_refresh_minutes: 15                    # Recompute indicators for full universe
  top_movers_count: 10                                  # How many gainers/losers/volume surges to show
  gap_threshold_pct: 2.0                                # Min gap % to flag at open
  high_low_proximity_pct: 2.0                           # % within 52-week high/low to flag

ai:
  decision_model: "claude-opus-4-6"
  analysis_model: "claude-sonnet-4-5-20250929"
  news_model: "claude-haiku-4-5-20251001"
  decision_interval_minutes: 30      # How often to call Opus (matches pulse interval)
  daily_candles_count: 15            # How many daily candles to send per stock
  enable_prompt_caching: true

# ═══ LLM COST TRACKING (INR per 1M tokens) ═══
# Update these if Anthropic changes pricing or USD/INR rate changes.
# Current rates based on: Anthropic pricing × ₹84/USD
llm_pricing:
  usd_inr_rate: 84.0                  # Update periodically
  claude-opus-4-6:
    input_per_1m: 1260.00             # $15/MTok
    output_per_1m: 6300.00            # $75/MTok
    cache_read_per_1m: 126.00         # $1.50/MTok
    cache_create_per_1m: 1575.00      # $18.75/MTok
  claude-sonnet-4-5-20250929:
    input_per_1m: 252.00              # $3/MTok
    output_per_1m: 1260.00            # $15/MTok
    cache_read_per_1m: 25.20          # $0.30/MTok
    cache_create_per_1m: 315.00       # $3.75/MTok
  claude-haiku-4-5-20251001:
    input_per_1m: 67.20               # $0.80/MTok
    output_per_1m: 336.00             # $4/MTok
    cache_read_per_1m: 6.72           # $0.08/MTok
    cache_create_per_1m: 84.00        # $1/MTok

kite:
  api_key: "${KITE_API_KEY}"
  api_secret: "${KITE_API_SECRET}"

anthropic:
  api_key: "${ANTHROPIC_API_KEY}"

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"

database:
  path: "data/trading_bot.db"

veto:
  enabled: false
  timeout_seconds: 60

backup:
  enabled: true
  local_dir: "backups/"
  keep_local_days: 7
  offsite_enabled: false
  offsite_remote: "gdrive:trading-bot-backups/"

logging:
  level: "INFO"
  log_dir: "logs/"
  save_prompts: true
  save_responses: true

etfs:
  approved:
    - NIFTYBEES
    - BANKBEES
    - GOLDBEES
    - ITBEES
    - PSUBNKBEES
    - JUNIORBEES
    - LIQUIDBEES
    - CPSEETF
    - SILVERBEES
    - PHARMABEES
    - MOM50
```

---

## APPENDIX B: .env FILE TEMPLATE

```bash
# NEVER commit this file to git

# Zerodha Kite Connect
KITE_API_KEY=your_kite_api_key
KITE_API_SECRET=your_kite_api_secret

# Anthropic
ANTHROPIC_API_KEY=your_anthropic_api_key

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

---

## APPENDIX C: .gitignore

```
# Secrets
.env
config/.env

# Database
data/*.db

# Logs
logs/

# Cache
__pycache__/
*.pyc
data/instruments_cache.csv

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
```


---

**END OF SPECIFICATION**

This document contains everything needed to implement the AI trading bot.
Feed this to Claude Code and build module by module, starting with:
1. Database setup (schema creation)
2. Kite Connect client (auth + data fetching)
3. Universe filter (Layer 1)
4. Data infrastructure / warehouse (Layer 2 — bulk data collection + indicators)
5. Market Pulse aggregator (movers, losers, volume surges, sector heatmap)
6. Market Pulse prompt builder (Sonnet prompt)
7. Watchlist manager (tracks Claude's selections across cycles)
8. Deep dive data assembler (fetches full data for Claude-selected stocks)
9. Trading Decision prompt builder (Opus prompt)
10. Response parser (handles both Market Pulse and Trading Decision JSON)
11. Corporate actions filter
12. Guardrail engine (incl. circuit limit checks, duplicate order detection)
13. Execution engine (paper mode first)
14. Order reconciliation loop
15. SL & Target health check
16. MIS auto-exit engine (3-stage exit as independent APScheduler jobs)
17. Claude API circuit breaker (safe mode)
18. Main orchestrator loop (two-stage pipeline: Pulse → Decision)
19. Telegram notifications
20. Human veto mode (for Phase 4)
21. Daily backup automation
22. Dashboard (optional)

Test each module independently before integrating.
