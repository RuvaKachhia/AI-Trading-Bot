# AI Trading Bot

An autonomous equity-trading experiment on Indian markets (NSE/BSE), with **Claude
Opus 4.7** making every trading decision and a Next.js dashboard exposing every
trade, prompt, and decision the bot made.

> **Live archive dashboard:** **https://ai-trading-bot-archive.vercel.app**
>
> The experiment ran 2026-04-22 → 2026-05-11 (14 trading sessions) and is now
> concluded. The dashboard is frozen on the final state and serves the full
> archive — `/` is a project showcase, `/dashboard` has every trade and
> snapshot, `/logs` lets you browse every Sonnet, Opus, and Haiku call (system
> prompt, user prompt, response, metadata).

---

## The Experiment

The question we're trying to answer: **how well does Claude Opus 4.7 perform as
an autonomous discretionary trader if we give it good market data, deep stock
research, and a structured decision loop — and stay out of its way?**

**Setup**

| | |
|---|---|
| **Capital** | ₹10,00,000 (paper) |
| **Universe** | NSE/BSE — large + mid caps + select ETFs (~510 instruments) |
| **Started** | 2026-04-22 |
| **Mode** | Paper trading via realistic OHLC fill simulation against live Dhan market data |
| **Decision cadence** | Every 30 min during market hours (12 cycles/day) |
| **Models** | Sonnet 4.6 (market pulse) → Opus 4.7 (deep research + trading decisions) → Haiku 4.5 (news summarization) |
| **Risk gates** | 15+ deterministic guardrails between Claude's decision and order placement |

The bot is mode-blind: Claude never knows it's paper trading. The data format,
prompts, and execution interfaces would be identical in a live-trading run.

---

## Architecture

```
                         ┌──────────────────────────┐
                         │   Dhan HQ (broker API)   │
                         │  market data + LTPs      │
                         └────────────┬─────────────┘
                                      │
   ┌──────────────────────────────────▼──────────────────────────────┐
   │  ai-trading-bot/  (Python 3.11, APScheduler)                    │
   │                                                                 │
   │   06:30  Token refresh   ──► Dhan TOTP login                    │
   │   07:30  Premarket research agent (Opus subprocess)             │
   │   09:00→14:30  ┌───────────────────────────────────────────┐    │
   │   every 30min  │ Market Pulse (Sonnet) → 15-stock watchlist │   │
   │                │ 5 parallel research agents (Opus subproc.) │   │
   │                │ Trading Decision (Opus) → BUY/SELL/MODIFY  │   │
   │                │ Guardrails (15+ rules) → execute or block  │   │
   │                │ Paper Broker → DB mutation + reconciler    │   │
   │                └───────────────────────────────────────────┘    │
   │   09:00→15:30  Risk monitor agent (Opus subproc., every 30 min) │
   │   15:40        EOD review                                       │
   │   16:00        Strategy review agent (rewrites risk overrides)  │
   │                                                                 │
   │   SQLite WAL DB (trades, snapshots, llm_calls, paper_*)         │
   └──────────────────────────────────┬──────────────────────────────┘
                                      │  reads (read-only)
                       ┌─────────────────────────────────┐
                       │  dashboard/  (Next.js 16)       │
                       │  ai-trading-bot-archive         │
                       │     .vercel.app                 │
                       │  Frozen post-experiment archive │
                       └─────────────────────────────────┘
```

Two top-level packages, one git repo:

| Path | What it is |
|---|---|
| [`ai-trading-bot/`](ai-trading-bot/) | The Python trading bot. APScheduler-driven main loop, Anthropic SDK + Claude Code subprocesses, SQLite. See [its README](ai-trading-bot/README.md). |
| [`dashboard/`](dashboard/) | A Next.js 16 dashboard that reads the bot's SQLite DB read-only and renders the experiment in real time. |
| [`ai_trading_bot_spec_v3_with_logging.md`](ai_trading_bot_spec_v3_with_logging.md) | The original 200KB spec the project was built against. |

---

## How It Ran

During the live phase, both components ran as systemd services on a single
Ubuntu 22.04 EC2 instance (ap-south-1):

| Service | Process | Restart policy |
|---|---|---|
| `trading-bot.service` | `python main.py` (APScheduler stays in foreground) | `Restart=always` |
| `trading-dashboard.service` | `npm start` (`next start` on port 3000) | `Restart=always` |

The bot didn't poll — every action was APScheduler-cron-triggered, so the
process was mostly idle between events.

**Post-experiment**, the EC2 is terminated. The dashboard now serves from
Vercel (https://ai-trading-bot-archive.vercel.app) against a frozen snapshot
of the SQLite DB and the per-call AI logs, both committed to the
`experiment-archive` and `vercel-deploy` branches of this repo.

### Tech stack

- **Bot**: Python 3.11, [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python), Claude Code subprocess agents, APScheduler, SQLite + WAL, Dhan HQ SDK (`dhanhq`), pandas-ta-classic, pyotp
- **Dashboard**: Next.js 16.2.3, React 19, TypeScript, better-sqlite3 (read-only), no client framework / no UI library — just inline styled JSX
- **Infra**: AWS EC2 (ap-south-1), systemd, conda env `trading-bot`

---

## Daily Schedule (IST)

| Time | Event | Notes |
|---|---|---|
| 06:30 | Dhan token refresh | TOTP via pyotp; updates SDK header on success |
| 07:30 | Premarket research | Macro brief + overnight news, weekday only |
| 09:00 → 14:30 | Market pulse cycles | Every 30 min; Sonnet → Opus pipeline |
| 09:00 → 15:30 | Risk monitor | Every 30 min; tightens config overrides if concentration grows |
| 09:00 → 15:30 | OHLC reconciler + SL health | Every 5 min |
| 15:00 → 15:12 | MIS auto-exit (4 stages) | Closes any intraday positions |
| 15:40 | EOD review | Daily summary written to DB |
| 16:00 | Strategy review (Opus) | Reads the day, edits `risk_config.yaml` for tomorrow |

---

## Risk Management

Every Claude decision is filtered through a deterministic guardrail layer
**before** it reaches the broker:

- **Position sizing** — max 15% of portfolio per stock (auto-tightening based on concentration)
- **Sector exposure** — max 35% per sector
- **Cluster discipline** — soft 20% cap on correlated themes (e.g. rate-sensitive financials)
- **Cash buffer** — at least 20% cash retained at all times
- **Daily loss limit** — 3% drawdown halts new entries
- **SL range** — every BUY must come with an SL between 0.5% and 5% of entry
- **Min R:R** — 1.5:1 reward-to-risk on every entry
- **ASM/GSM filter** — restricted scrips are auto-blocked
- **Order hygiene** — duplicate working orders on the same symbol are blocked
- **Circuit breaker** — Opus API failures for >15 min trigger SAFE MODE (no new trades until recovery)

All thresholds are read from `config/config.yaml` and can be tightened (never
loosened) at runtime by the daily strategy review agent via
`src/agents/risk_config.yaml`.

---

## Observability

The dashboard is the primary lens, but the underlying data is in the SQLite DB
and on disk:

| Where | What |
|---|---|
| Dashboard `/` | Today's trades, active positions, agent activity, AI cost, daily performance |
| Dashboard `/logs` | Full LLM prompt + response logs by date |
| `ai-trading-bot/logs/app.log` | Application log (rotating) |
| `ai-trading-bot/logs/<date>/ai/` | Per-call LLM prompts, responses, metadata |
| `ai-trading-bot/data/trading_bot.db` | SQLite source of truth — 13 tables |
| `ai-trading-bot/src/agents/outputs/<date>/` | Agent JSON outputs (premarket, watchlist, risk, strategy) |

---

## Status — concluded

The experiment ran **2026-04-22 → 2026-05-11** (14 trading sessions) and is
now concluded. All paper positions were closed at last-known LTPs as part of
the wind-down.

**Final numbers**

| | |
|---|---|
| **Sessions traded** | 14 |
| **Trades** | 160 |
| **Closed positions** | 30 |
| **Win rate** | 36.4% (11W / 19L) |
| **Realized P&L** | −₹26,666 |
| **Final portfolio value** | ₹9,73,335 (started ₹10,00,000) |
| **Cumulative** | **−₹22,846 / −2.28%** |
| **AI spend (lifetime)** | $170.85 |
| **LLM calls** | 784 (Opus + Sonnet + Haiku) |
| **Agent runs** | 955 |
| **Guardrail events** | 2,519 |

See **https://ai-trading-bot-archive.vercel.app** for the full archive:
project showcase on `/`, frozen dashboard on `/dashboard`, and the complete
per-call AI log browser on `/logs`.

---

## Disclaimer

This is a research experiment. The bot trades **paper money only** — no real
positions are taken on Zerodha or any other broker. None of what Claude or the
strategy review agent decides is financial advice. The bot makes mistakes, the
prompts evolve daily, and the risk gates are imperfect. Watch the experiment;
don't copy the trades.
