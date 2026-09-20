"""
Prompt Formatter.
Builds the Market Pulse and Trading Decision prompts from data.
Mode-blind: has ZERO knowledge of PAPER vs LIVE.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class PromptFormatter:
    """
    Formats structured data into the prompt templates for Claude.
    This class NEVER sees or references the trading mode.
    """

    def __init__(self, config: dict):
        self.config = config
        exp = config.get("experiment", {})
        self._start_date = datetime.strptime(
            exp.get("start_date", "2026-03-01"), "%Y-%m-%d"
        ).date()
        self._duration_days = exp.get("duration_days", 30)
        trading = config.get("trading", {})
        self._unwind_days = trading.get("unwind_phase_days", 5)

    # ─── HELPERS ───

    def _experiment_status(self) -> dict:
        """Compute experiment day number, trading days left, phase."""
        today = date.today()
        day_number = (today - self._start_date).days + 1
        day_number = max(1, min(day_number, self._duration_days))

        end_date = self._start_date + timedelta(days=self._duration_days)
        days_left = (end_date - today).days
        # Approximate trading days (weekdays)
        trading_days_left = 0
        d = today
        while d <= end_date:
            if d.weekday() < 5:
                trading_days_left += 1
            d += timedelta(days=1)

        phase = "UNWIND_PHASE" if trading_days_left <= self._unwind_days else "NORMAL"
        rule_reminder = ""
        if phase == "UNWIND_PHASE":
            rule_reminder = "No new CNC positions. Unwind existing holdings."

        return {
            "day_number": day_number,
            "trading_days_left": trading_days_left,
            "phase": phase,
            "rule_reminder": rule_reminder,
        }

    def _market_status(self) -> str:
        """Determine current market status."""
        now = datetime.now()
        h, m = now.hour, now.minute
        t = h * 60 + m
        if t < 9 * 60 + 15:
            return "PRE_MARKET"
        elif t <= 15 * 60 + 30:
            return "OPEN"
        else:
            return "CLOSED"

    def _time_until_close(self) -> str:
        """Human-readable time until market close."""
        now = datetime.now()
        close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now >= close:
            return "IS CLOSED"
        diff = close - now
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        return f"CLOSES IN {hours}h {minutes}m"

    def _format_table_row(self, data: dict, columns: list) -> str:
        """Format a dict into a table row string."""
        parts = []
        for col in columns:
            val = data.get(col, "")
            if isinstance(val, float):
                val = f"{val:.2f}"
            parts.append(str(val).ljust(14))
        return "| " + " | ".join(parts) + " |"

    # ─── MARKET PULSE PROMPT ───

    def format_market_pulse(
        self,
        indices: dict,
        pulse_data: dict,
        sector_heatmap: list,
        macro: dict,
        news_headlines: list,
        etf_snapshot: list,
        portfolio_state: dict,
        previous_watchlist: list = None,
        corporate_actions: list = None,
        premarket_research: dict = None,
    ) -> str:
        """
        Build the complete Market Pulse user prompt for Sonnet.
        """
        exp = self._experiment_status()
        now = datetime.now()

        sections = []

        # Call type header
        sections.append("call_type: MARKET_PULSE")

        # Experiment status
        sections.append(self._section_experiment_status(exp))

        # Pre-market research (web-searched overnight news + FII/DII + macro themes)
        if premarket_research:
            sections.append(self._section_premarket_research(premarket_research))

        # Market overview
        sections.append(self._section_market_overview(indices, now))

        # Market breadth
        breadth = pulse_data.get("market_breadth", {})
        sections.append(self._section_breadth(breadth))

        # Sector heatmap
        sections.append(self._section_sector_heatmap(sector_heatmap))

        # Top gainers
        sections.append(self._section_movers(
            "TOP GAINERS", pulse_data.get("top_gainers", [])
        ))

        # Top losers
        sections.append(self._section_movers(
            "TOP LOSERS", pulse_data.get("top_losers", [])
        ))

        # Volume surges
        sections.append(self._section_movers(
            "TOP VOLUME SURGES", pulse_data.get("volume_surges", [])
        ))

        # Sector leaders (top 3 per sector)
        sections.append(self._section_sector_leaders(
            pulse_data.get("top_per_sector", {})
        ))

        # 52-week extremes
        sections.append(self._section_52w_extremes(
            pulse_data.get("near_52w_highs", []),
            pulse_data.get("near_52w_lows", []),
        ))

        # Gap stocks
        sections.append(self._section_gap_stocks(
            pulse_data.get("gap_stocks", {})
        ))

        # Macro context
        sections.append(self._section_macro(macro))

        # Global cues
        sections.append(self._section_global_cues(macro.get("global_cues", {})))

        # News headlines
        sections.append(self._section_news(news_headlines))

        # ETF snapshot
        sections.append(self._section_etf_snapshot(etf_snapshot))

        # Portfolio (brief)
        sections.append(self._section_portfolio_brief(portfolio_state))

        # Previous watchlist
        sections.append(self._section_previous_watchlist(previous_watchlist))

        # Corporate actions
        if corporate_actions:
            sections.append(self._section_corporate_actions(corporate_actions))

        # Footer
        sections.append(self._section_footer(exp, now))

        pipeline = self.config.get("pipeline", {})
        min_w = pipeline.get("min_watchlist_size", 3)
        max_w = pipeline.get("max_watchlist_size", 25)
        sections.append(
            f"Scan the market data above. Select {min_w}-{max_w} stocks (or ETFs) you want "
            "full data on for trading analysis. You MUST include all stocks you currently "
            "hold in your selections. Respond with JSON in the MARKET_PULSE format."
        )

        return "\n\n".join(sections)

    # ─── TRADING DECISION PROMPT ───

    def format_trading_decision(
        self,
        indices: dict,
        macro: dict,
        portfolio_state: dict,
        watchlist_reasons: dict,
        deep_dive_packs: list,
        etf_snapshot: list,
        existing_positions: list,
        performance_context: dict,
        supplementary_research: list = None,
        open_orders: list = None,
    ) -> str:
        """
        Build the complete Trading Decision user prompt for Opus.
        """
        exp = self._experiment_status()
        now = datetime.now()

        sections = []

        sections.append("call_type: TRADING_DECISION")

        # Priority framing: review held positions FIRST
        sections.append(
            "PRIORITY: First walk through the EXISTING POSITIONS section and "
            "issue a HOLD / MODIFY / EXIT decision for each. Only then consider "
            "new BUY/SELL entries. Use MODIFY (with new_stop_loss / new_target) "
            "to trail SLs or adjust targets instead of EXIT+re-entry."
        )

        # Experiment status
        sections.append(self._section_experiment_status(exp))

        # Market overview (compact)
        sections.append(self._section_market_overview(indices, now))

        # Breadth (from portfolio_state if available)
        breadth = portfolio_state.get("market_breadth", {})
        if breadth:
            sections.append(self._section_breadth(breadth))

        # Macro
        sections.append(self._section_macro(macro))
        sections.append(self._section_global_cues(macro.get("global_cues", {})))

        # Portfolio state (full)
        sections.append(self._section_portfolio_full(portfolio_state))

        # Watchlist selections with reasons
        sections.append(self._section_watchlist_reasons(watchlist_reasons))

        # Deep dive stock data
        sections.append(self._section_deep_dive(deep_dive_packs, watchlist_reasons))

        # Supplementary research from watchlist research agents
        if supplementary_research:
            sections.append(self._section_supplementary_research(supplementary_research))

        # ETF snapshot
        sections.append(self._section_etf_snapshot(etf_snapshot))

        # Working orders (OPEN LIMITs, TRIGGER PENDING SLs) — shown before
        # existing positions so ORDER HYGIENE checks see them naturally.
        sections.append(self._section_open_orders(open_orders or []))

        # Existing position updates
        sections.append(self._section_existing_positions(existing_positions))

        # Performance context
        sections.append(self._section_performance(performance_context))

        # Footer
        sections.append(self._section_footer(exp, now))

        sections.append(
            "Analyze all data above and provide your trading decisions in the required "
            "JSON format. Remember: quality over quantity. NO_ACTION is always valid. "
            "Capital preservation is priority #1."
        )

        return "\n\n".join(sections)

    # ─── SECTION BUILDERS ───

    def _section_experiment_status(self, exp: dict) -> str:
        lines = [
            "=" * 54,
            "EXPERIMENT STATUS",
            "=" * 54,
            f"Day {exp['day_number']} of {self._duration_days} | "
            f"Trading days remaining: {exp['trading_days_left']}",
            f"Phase: {exp['phase']}",
        ]
        if exp["rule_reminder"]:
            lines.append(f"Rule reminder: {exp['rule_reminder']}")
        return "\n".join(lines)

    def _section_market_overview(self, indices: dict, now: datetime) -> str:
        lines = [
            "=" * 54,
            "MARKET OVERVIEW",
            "=" * 54,
            f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')} IST",
            f"Market Status: {self._market_status()}",
            "",
            "--- INDICES ---",
        ]

        index_list = [
            ("NIFTY 50", "NSE:NIFTY 50"),
            ("BANK NIFTY", "NSE:NIFTY BANK"),
            ("NIFTY IT", "NSE:NIFTY IT"),
            ("NIFTY PHARMA", "NSE:NIFTY PHARMA"),
            ("NIFTY AUTO", "NSE:NIFTY AUTO"),
            ("NIFTY METAL", "NSE:NIFTY METAL"),
            ("NIFTY REALTY", "NSE:NIFTY REALTY"),
            ("NIFTY ENERGY", "NSE:NIFTY ENERGY"),
            ("NIFTY PSU BANK", "NSE:NIFTY PSU BANK"),
            ("INDIA VIX", "NSE:INDIA VIX"),
        ]

        for display_name, key in index_list:
            data = indices.get(key, indices.get(display_name, {}))
            ltp = data.get("last_price", data.get("ltp", 0))
            change = data.get("change_pct", 0)
            sign = "+" if change >= 0 else ""
            line = f"{display_name:<16} {ltp:>10.2f} ({sign}{change:.2f}%)"
            ohlc = data.get("ohlc", {})
            if ohlc.get("low") and ohlc.get("high"):
                line += f"  | Day range: {ohlc['low']:.2f} - {ohlc['high']:.2f}"
            lines.append(line)

        return "\n".join(lines)

    def _section_breadth(self, breadth: dict) -> str:
        lines = [
            "--- MARKET BREADTH ---",
            f"Advances: {breadth.get('advances', 0)} | "
            f"Declines: {breadth.get('declines', 0)} | "
            f"Unchanged: {breadth.get('unchanged', 0)}",
            f"Advance-Decline Ratio: {breadth.get('ad_ratio', 0):.2f}",
        ]
        return "\n".join(lines)

    def _section_sector_heatmap(self, heatmap: list) -> str:
        lines = ["--- SECTOR HEATMAP (ranked by % change) ---"]
        for i, sector in enumerate(heatmap, 1):
            sign = "+" if sector.get("change_pct", 0) >= 0 else ""
            lines.append(
                f"  {i}. {sector.get('sector', 'Unknown')}: "
                f"{sign}{sector.get('change_pct', 0):.2f}%"
            )
        return "\n".join(lines)

    def _section_supplementary_research(self, research: list) -> str:
        """Render per-stock agent research into a compact prompt section."""
        lines = ["--- SUPPLEMENTARY RESEARCH (per-stock agent findings) ---"]
        if not research:
            lines.append("  (no agent research available)")
            return "\n".join(lines)

        for item in research:
            symbol = item.get("symbol", "?")
            lines.append(f"\n[{symbol}]")
            if item.get("research_sentiment"):
                mod = item.get("confidence_modifier", 0) or 0
                lines.append(
                    f"  Sentiment: {item['research_sentiment']} "
                    f"(confidence modifier: {mod:+.2f})"
                )
            if item.get("recent_news"):
                lines.append(f"  News: {item['recent_news']}")
            if item.get("sector_context"):
                lines.append(f"  Sector: {item['sector_context']}")
            if item.get("peer_comparison"):
                lines.append(f"  Peers: {item['peer_comparison']}")
            red = item.get("red_flags") or []
            if red:
                lines.append(f"  Red flags: {', '.join(red)}")
            cat = item.get("catalysts") or []
            if cat:
                lines.append(f"  Catalysts: {', '.join(cat)}")

        return "\n".join(lines)

    def _section_premarket_research(self, brief: dict) -> str:
        """Render the pre-market research agent output into a prompt section."""
        lines = ["--- PRE-MARKET RESEARCH (web-searched overnight) ---"]
        if not brief:
            return "\n".join(lines)

        summary = brief.get("brief_summary") or ""
        if summary:
            lines.append(f"Outlook: {summary}")

        cues = brief.get("global_cues") or {}
        if cues:
            parts = []
            if cues.get("us_markets"): parts.append(f"US: {cues['us_markets']}")
            if cues.get("european_markets"): parts.append(f"EU: {cues['european_markets']}")
            if cues.get("asian_markets"): parts.append(f"Asia: {cues['asian_markets']}")
            if cues.get("sentiment"): parts.append(f"Sentiment: {cues['sentiment']}")
            if parts:
                lines.append("Global cues:")
                for p in parts:
                    lines.append(f"  - {p}")

        fii = brief.get("fii_dii_summary")
        if fii:
            lines.append(f"FII/DII: {fii}")

        earnings = brief.get("earnings_calendar") or []
        if earnings:
            lines.append("Earnings calendar:")
            for e in earnings[:10]:
                lines.append(f"  - {e}")

        events = brief.get("macro_events") or []
        if events:
            lines.append("Macro events:")
            for e in events[:8]:
                lines.append(f"  - {e}")

        themes = brief.get("sector_themes") or []
        if themes:
            lines.append("Sector themes:")
            for t in themes[:8]:
                lines.append(f"  - {t}")

        risks = brief.get("risk_flags") or []
        if risks:
            lines.append("Risk flags:")
            for r in risks[:8]:
                lines.append(f"  - {r}")

        return "\n".join(lines)

    def _section_movers(self, title: str, stocks: list) -> str:
        lines = [f"--- {title} ---"]
        if not stocks:
            lines.append("  (No data available)")
            return "\n".join(lines)

        header = f"{'Symbol':<14} {'CMP':>10} {'Change %':>10} {'Vol Ratio':>10} {'Sector':<12}"
        lines.append(header)
        lines.append("-" * len(header))
        for s in stocks:
            sign = "+" if s.get("change_pct", 0) >= 0 else ""
            lines.append(
                f"{s.get('symbol', ''):<14} "
                f"{s.get('ltp', 0):>10.2f} "
                f"{sign}{s.get('change_pct', 0):>9.2f}% "
                f"{s.get('volume_ratio', 0):>9.1f}x "
                f"{s.get('sector', ''):<12}"
            )
        return "\n".join(lines)

    def _section_sector_leaders(self, by_sector: dict) -> str:
        """Top N gainers per sector — surfaces sector rotation plays."""
        lines = ["--- SECTOR LEADERS (top movers within each sector) ---"]
        if not by_sector:
            lines.append("  (No data available)")
            return "\n".join(lines)

        # Sort sectors by their strongest stock's change_pct (leaders first)
        sorted_sectors = sorted(
            by_sector.items(),
            key=lambda kv: kv[1][0].get("change_pct", 0) if kv[1] else 0,
            reverse=True,
        )
        for sector, stocks in sorted_sectors:
            if not stocks:
                continue
            parts = []
            for s in stocks:
                sign = "+" if s.get("change_pct", 0) >= 0 else ""
                parts.append(
                    f"{s.get('symbol', '')} ({sign}{s.get('change_pct', 0):.2f}%)"
                )
            lines.append(f"  {sector}: {', '.join(parts)}")
        return "\n".join(lines)

    def _section_52w_extremes(self, highs: list, lows: list) -> str:
        lines = ["--- 52-WEEK EXTREMES ---"]

        if highs:
            items = ", ".join(
                f"{s['symbol']} ({s['pct_from_high']:.1f}% from high)"
                for s in highs[:8]
            )
            lines.append(f"Near 52-week highs (within 2%): {items}")
        else:
            lines.append("Near 52-week highs: None")

        if lows:
            items = ", ".join(
                f"{s['symbol']} ({s['pct_from_low']:.1f}% from low)"
                for s in lows[:8]
            )
            lines.append(f"Near 52-week lows (within 2%): {items}")
        else:
            lines.append("Near 52-week lows: None")

        return "\n".join(lines)

    def _section_gap_stocks(self, gaps: dict) -> str:
        lines = ["--- GAP STOCKS (> 2% gap at open) ---"]
        gap_up = gaps.get("gap_up", [])
        gap_down = gaps.get("gap_down", [])

        if gap_up:
            items = ", ".join(f"{s['symbol']} (+{s['gap_pct']:.1f}%)" for s in gap_up[:8])
            lines.append(f"Gap up: {items}")
        else:
            lines.append("Gap up: None")

        if gap_down:
            items = ", ".join(f"{s['symbol']} ({s['gap_pct']:.1f}%)" for s in gap_down[:8])
            lines.append(f"Gap down: {items}")
        else:
            lines.append("Gap down: None")

        return "\n".join(lines)

    def _section_macro(self, macro: dict) -> str:
        lines = ["--- MACRO CONTEXT ---"]

        fii_dii = macro.get("fii_dii", {})
        fii_net = fii_dii.get("fii_net", 0)
        dii_net = fii_dii.get("dii_net", 0)
        fii_sign = "+" if fii_net >= 0 else ""
        dii_sign = "+" if dii_net >= 0 else ""
        fii_label = "net_buy" if fii_net >= 0 else "net_sell"
        dii_label = "net_buy" if dii_net >= 0 else "net_sell"
        lines.append(f"FII today: {fii_sign}{fii_net:.0f} Cr ({fii_label})")
        lines.append(f"DII today: {dii_sign}{dii_net:.0f} Cr ({dii_label})")

        usd = macro.get("usd_inr", {})
        lines.append(f"USD/INR: {usd.get('rate', 0):.2f} ({usd.get('change_pct', 0):+.2f}%)")

        crude = macro.get("crude", {})
        lines.append(f"Crude Oil: {crude.get('price', 0):.2f} ({crude.get('change_pct', 0):+.2f}%)")

        gold = macro.get("gold", {})
        lines.append(f"Gold: {gold.get('price', 0):.0f} ({gold.get('change_pct', 0):+.2f}%)")

        vix = macro.get("vix", {})
        lines.append(f"India VIX: {vix.get('value', 0):.2f} ({vix.get('change_pct', 0):+.2f}%)")

        return "\n".join(lines)

    def _section_global_cues(self, global_cues: dict) -> str:
        lines = ["--- GLOBAL CUES ---"]
        for key, label in [("sp500", "US S&P 500"), ("dow", "Dow Jones"), ("nasdaq", "Nasdaq")]:
            data = global_cues.get(key, {})
            lines.append(
                f"{label}: {data.get('price', 0):.2f} ({data.get('change_pct', 0):+.2f}%)"
            )
        sgx = global_cues.get("sgx_nifty", {})
        lines.append(f"SGX Nifty: {sgx.get('price', 0):.2f} ({sgx.get('change_pct', 0):+.2f}%)")
        return "\n".join(lines)

    def _section_news(self, headlines: list) -> str:
        """
        Render the India-relevant news stream. Each item shows the source,
        timestamp, title, and RSS summary (when present). No pre-interpretation —
        Sonnet/Opus form their own view.
        """
        lines = [f"--- INDIA-RELEVANT NEWS ({len(headlines)} items) ---"]
        if not headlines:
            lines.append("  (No headlines available)")
            return "\n".join(lines)

        for h in headlines:
            src = h.get("source", "")
            ts = h.get("published", "")
            title = h.get("title", "")
            summary = h.get("summary", "")
            lines.append(f"- [{ts} · {src}] {title}")
            if summary:
                lines.append(f"    {summary}")
        return "\n".join(lines)

    def _section_etf_snapshot(self, etfs: list) -> str:
        lines = [
            "--- ETF SNAPSHOT ---",
            f"{'ETF':<14} {'CMP':>10} {'Change %':>10} {'Volume':>12}",
            "-" * 50,
        ]
        for etf in etfs:
            sign = "+" if etf.get("change_pct", 0) >= 0 else ""
            lines.append(
                f"{etf.get('symbol', ''):<14} "
                f"{etf.get('ltp', 0):>10.2f} "
                f"{sign}{etf.get('change_pct', 0):>9.2f}% "
                f"{etf.get('volume', 0):>12}"
            )
        return "\n".join(lines)

    def _section_portfolio_brief(self, state: dict) -> str:
        lines = [
            "=" * 54,
            "YOUR PORTFOLIO (brief)",
            "=" * 54,
        ]
        total = state.get("total_value", 0)
        cash = state.get("cash", 0)
        deployed = total - cash
        cash_pct = (cash / total * 100) if total > 0 else 100
        deployed_pct = (deployed / total * 100) if total > 0 else 0

        lines.append(
            f"Capital: INR {total:,.0f} | Cash: INR {cash:,.0f} ({cash_pct:.0f}%) | "
            f"Deployed: INR {deployed:,.0f} ({deployed_pct:.0f}%)"
        )

        pnl = state.get("daily_pnl", {})
        total_pnl = pnl.get("realized", 0) + pnl.get("unrealized", 0)
        pnl_pct = (total_pnl / total * 100) if total > 0 else 0
        lines.append(
            f"Today's P&L: INR {total_pnl:+,.0f} ({pnl_pct:+.2f}%) | "
            f"Trades today: {state.get('trades_today', 0)}"
        )

        # Holdings
        holdings = state.get("holdings", [])
        if holdings:
            items = ", ".join(
                f"{h.get('symbol', '')} ({h.get('pnl_pct', 0):+.1f}%)"
                for h in holdings[:5]
            )
            lines.append(f"Current holdings: {items}")
        else:
            lines.append("Current holdings: NONE")

        # MIS positions
        positions = state.get("mis_positions", [])
        if positions:
            items = ", ".join(
                f"{p.get('symbol', '')} ({p.get('side', '')}, {p.get('pnl_pct', 0):+.1f}%)"
                for p in positions[:5]
            )
            lines.append(f"Open MIS: {items}")
        else:
            lines.append("Open MIS: NONE")

        return "\n".join(lines)

    def _section_portfolio_full(self, state: dict) -> str:
        lines = [
            "=" * 54,
            "PORTFOLIO STATE",
            "=" * 54,
        ]
        total = state.get("total_value", 0)
        cash = state.get("cash", 0)
        deployed = total - cash
        deployed_pct = (deployed / total * 100) if total > 0 else 0
        max_deploy = total * 0.80
        remaining = max_deploy - deployed

        lines.append(f"Capital: INR {total:,.0f}")
        lines.append(f"Cash available: INR {cash:,.0f}")
        lines.append(f"Deployed: INR {deployed:,.0f} ({deployed_pct:.0f}%)")
        lines.append(f"Max deployable (80% rule): INR {max_deploy:,.0f}")
        lines.append(f"Remaining deployable: INR {max(0, remaining):,.0f}")
        lines.append("")

        # Today's P&L
        pnl = state.get("daily_pnl", {})
        realized = pnl.get("realized", 0)
        unrealized = pnl.get("unrealized", 0)
        total_pnl = realized + unrealized
        pnl_pct = (total_pnl / total * 100) if total > 0 else 0

        risk = self.config.get("risk", {})
        daily_limit = total * risk.get("daily_loss_limit_pct", 0.03)
        limit_remaining = daily_limit - abs(min(0, total_pnl))

        lines.append("--- TODAY'S P&L ---")
        lines.append(f"Realized P&L:    INR {realized:+,.0f}")
        lines.append(f"Unrealized P&L:  INR {unrealized:+,.0f}")
        lines.append(f"Total P&L:       INR {total_pnl:+,.0f} ({pnl_pct:+.2f}%)")
        lines.append(f"Daily loss limit: INR {daily_limit:,.0f} | Remaining: INR {limit_remaining:,.0f}")
        lines.append(f"Trades today: {state.get('trades_today', 0)}")
        lines.append("")

        # Cumulative P&L
        starting = self.config.get("experiment", {}).get("starting_capital", 100000)
        cumulative = total - starting
        cum_pct = (cumulative / starting * 100) if starting > 0 else 0
        lines.append("--- CUMULATIVE P&L (experiment to date) ---")
        lines.append(f"Total realized P&L: INR {cumulative:+,.0f} ({cum_pct:+.2f}% of starting capital)")
        lines.append(f"Current portfolio value: INR {total:,.0f}")
        lines.append(f"Starting capital: INR {starting:,.0f}")
        lines.append(f"Overall return: {cum_pct:+.2f}%")
        lines.append("")

        # CNC holdings table
        holdings = state.get("holdings", [])
        lines.append("--- CNC HOLDINGS (delivery / swing trades) ---")
        if holdings:
            lines.append(
                f"{'Symbol':<10} {'Qty':>5} {'Avg Cost':>10} {'CMP':>8} "
                f"{'P&L':>8} {'P&L %':>7} {'Days':>5} {'SL':>8}"
            )
            for h in holdings:
                lines.append(
                    f"{h.get('symbol', ''):<10} "
                    f"{h.get('quantity', 0):>5} "
                    f"{h.get('avg_price', 0):>10.2f} "
                    f"{h.get('ltp', 0):>8.2f} "
                    f"{h.get('pnl', 0):>8.0f} "
                    f"{h.get('pnl_pct', 0):>6.1f}% "
                    f"{h.get('days_held', 0):>5} "
                    f"{h.get('stop_loss', 0):>8.2f}"
                )
        else:
            lines.append("  NONE")
        lines.append("")

        # MIS positions table
        positions = state.get("mis_positions", [])
        lines.append("--- MIS POSITIONS (intraday) ---")
        if positions:
            lines.append(
                f"{'Symbol':<10} {'Side':<5} {'Qty':>5} {'Entry':>8} "
                f"{'CMP':>8} {'P&L':>8} {'SL':>8} {'Target':>8}"
            )
            for p in positions:
                lines.append(
                    f"{p.get('symbol', ''):<10} "
                    f"{p.get('side', ''):<5} "
                    f"{p.get('quantity', 0):>5} "
                    f"{p.get('entry', 0):>8.2f} "
                    f"{p.get('ltp', 0):>8.2f} "
                    f"{p.get('pnl', 0):>8.0f} "
                    f"{p.get('stop_loss', 0):>8.2f} "
                    f"{p.get('target', 0):>8.2f}"
                )
        else:
            lines.append("  NONE")

        return "\n".join(lines)

    def _section_previous_watchlist(self, watchlist: list) -> str:
        lines = [
            "=" * 54,
            "PREVIOUS WATCHLIST (from your last Market Pulse call)",
            "=" * 54,
        ]
        if watchlist:
            lines.append(", ".join(watchlist))
        else:
            lines.append("First call of the day — no previous watchlist")
        return "\n".join(lines)

    def _section_corporate_actions(self, actions: list) -> str:
        lines = [
            "=" * 54,
            "CORPORATE ACTIONS TODAY",
            "=" * 54,
        ]
        if actions:
            for a in actions:
                lines.append(
                    f"{a.get('symbol', '')}: {a.get('action_type', '')} "
                    f"(ex-date today — price movement is adjustment, not organic)"
                )
        else:
            lines.append("None affecting eligible universe today")
        return "\n".join(lines)

    def _section_watchlist_reasons(self, reasons: dict) -> str:
        lines = [
            "=" * 54,
            "YOUR WATCHLIST SELECTIONS (from Market Pulse)",
            "=" * 54,
            "You requested deep data on these stocks. Your reasoning at selection time:",
        ]
        for symbol, reason in reasons.items():
            lines.append(f'{symbol}: "{reason}"')
        return "\n".join(lines)

    def _section_deep_dive(self, packs: list, reasons: dict) -> str:
        lines = [
            "=" * 54,
            "DEEP DIVE: STOCK DATA",
            "=" * 54,
        ]

        for i, pack in enumerate(packs, 1):
            symbol = pack.get("symbol", "")
            exchange = pack.get("exchange", "NSE")
            reason = reasons.get(symbol, "")

            lines.append(f"\n--- STOCK {i}: {symbol} ({exchange}) ---")
            if reason:
                lines.append(f'Your selection reason: "{reason}"')
            lines.append("")

            # Price data
            pd_data = pack.get("price_data", {})
            change = pd_data.get("change_pct", 0)
            sign = "+" if change >= 0 else ""
            lines.append("Price Data:")
            lines.append(f"  CMP: INR {pd_data.get('ltp', 0):.2f} | Day change: {sign}{change:.2f}% ({sign}INR {pd_data.get('abs_change', 0):.2f})")
            lines.append(f"  Today OHLC: {pd_data.get('day_open', 0):.2f} / {pd_data.get('day_high', 0):.2f} / {pd_data.get('day_low', 0):.2f} / {pd_data.get('ltp', 0):.2f}")
            lines.append(f"  52-week range: INR {pd_data.get('low_52w', 0):.2f} - INR {pd_data.get('high_52w', 0):.2f}")
            lines.append(f"  Avg daily volume (20d): INR {pd_data.get('avg_volume_20d_cr', 0):.2f} Cr | Today: INR {pd_data.get('volume_today_cr', 0):.2f} Cr ({pd_data.get('volume_ratio', 0):.1f}x)")
            lines.append("")

            # Daily candles
            candles = pack.get("daily_candles", [])
            if candles:
                lines.append(f"Daily Candles (last {len(candles)} sessions, newest first):")
                lines.append(f"  {'Date':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} {'Vol(Cr)':>8}")
                for c in candles:
                    lines.append(
                        f"  {c.get('date', ''):<12} "
                        f"{c.get('open', 0):>8.2f} {c.get('high', 0):>8.2f} "
                        f"{c.get('low', 0):>8.2f} {c.get('close', 0):>8.2f} "
                        f"{c.get('volume_cr', 0):>8.2f}"
                    )
                lines.append("")

            # Intraday candles
            intra = pack.get("intraday_candles", [])
            if intra:
                lines.append("Intraday 15-min Candles (today):")
                lines.append(f"  {'Time':<6} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} {'Vol(L)':>8}")
                for c in intra:
                    lines.append(
                        f"  {c.get('time', ''):<6} "
                        f"{c.get('open', 0):>8.2f} {c.get('high', 0):>8.2f} "
                        f"{c.get('low', 0):>8.2f} {c.get('close', 0):>8.2f} "
                        f"{c.get('volume_lakhs', 0):>8.2f}"
                    )
                lines.append("")

            # Technical indicators
            ind = pack.get("indicators", {})
            if ind:
                lines.append("Technical Indicators:")
                lines.append(f"  RSI(14):            {ind.get('rsi', 0):.1f}")

                macd = ind.get("macd_crossover", "neutral")
                lines.append(f"  MACD(12,26,9):      Signal={macd}")
                lines.append(f"  MACD Histogram:     {ind.get('macd_histogram', 0):.4f}")

                for ma_name in ["sma_20", "sma_50", "sma_200"]:
                    val = ind.get(ma_name, 0)
                    rel = ind.get("price_vs_sma", {}).get(ma_name, "")
                    label = ma_name.upper().replace("_", " ")
                    lines.append(f"  {label}:          INR {val:.2f} (price {rel})")

                lines.append(f"  EMA 9:              INR {ind.get('ema_9', 0):.2f}")

                vwap = pack.get("vwap")
                if vwap:
                    lines.append(f"  VWAP (today):       INR {vwap:.2f}")

                lines.append(f"  Bollinger Bands:    Upper=INR {ind.get('bb_upper', 0):.2f} | Mid=INR {ind.get('bb_mid', 0):.2f} | Lower=INR {ind.get('bb_lower', 0):.2f}")
                lines.append(f"  ADX(14):            {ind.get('adx', 0):.1f}")
                lines.append(f"  ATR(14):            INR {ind.get('atr', 0):.2f}")
                lines.append(f"  Supertrend(10,3):   {ind.get('supertrend_signal', 'N/A')} at INR {ind.get('supertrend', 0):.2f}")
                lines.append("")

            # Key levels
            levels = pack.get("levels", {})
            if levels:
                lines.append("Key Levels:")
                lines.append(f"  Pivot Point:  INR {levels.get('pivot', 0):.2f}")
                lines.append(f"  Resistance 1: INR {levels.get('r1', 0):.2f}")
                lines.append(f"  Resistance 2: INR {levels.get('r2', 0):.2f}")
                lines.append(f"  Support 1:    INR {levels.get('s1', 0):.2f}")
                lines.append(f"  Support 2:    INR {levels.get('s2', 0):.2f}")
                if levels.get("swing_resistance"):
                    lines.append(f"  Swing resistance: {', '.join(f'INR {l:.2f}' for l in levels['swing_resistance'][:3])}")
                if levels.get("swing_support"):
                    lines.append(f"  Swing support: {', '.join(f'INR {l:.2f}' for l in levels['swing_support'][:3])}")
                lines.append("")

            # Patterns
            patterns = pack.get("patterns", [])
            if patterns:
                lines.append("Candlestick Patterns Detected (last 5 sessions):")
                for date_str, pattern_name in patterns:
                    lines.append(f"  - {date_str}: {pattern_name}")
                lines.append("")

            # Sector context
            sector = pack.get("sector", "")
            if sector:
                lines.append(f"Sector Context: {sector}")
                lines.append("")

        return "\n".join(lines)

    def _section_open_orders(self, orders: list) -> str:
        lines = [
            "=" * 54,
            "OPEN / PENDING ORDERS",
            "=" * 54,
            "Working orders that have NOT yet filled. Before emitting a new "
            "BUY/SELL, check this list — do NOT stack a second same-direction "
            "order on a symbol that already appears here (see ORDER HYGIENE).",
        ]

        if not orders:
            lines.append("  None.")
            return "\n".join(lines)

        for o in orders:
            sym = o.get("symbol", "")
            side = o.get("transaction_type", "")
            qty = o.get("quantity", 0)
            prod = o.get("product", "")
            otype = o.get("order_type", "")
            status = o.get("status", "")
            age = o.get("age_minutes")
            age_str = f"{age}m ago" if age is not None else o.get("placed_at", "?")
            # LIMIT orders quote price; SL/TRIGGER PENDING quote trigger_price.
            price_val = o.get("price", 0) or o.get("trigger_price", 0)
            price_label = "trigger" if status == "TRIGGER PENDING" else "limit"
            lines.append(
                f"  {side:<4} {qty:>4}x {sym:<12} {prod} {otype} "
                f"@ {price_label} INR {price_val:.2f}  [{status}, placed {age_str}]"
            )
        return "\n".join(lines)

    def _section_existing_positions(self, positions: list) -> str:
        lines = [
            "=" * 54,
            "EXISTING POSITION UPDATES",
            "=" * 54,
            "Review each existing position and recommend: HOLD, TRAIL_SL, BOOK_PARTIAL, or EXIT.",
        ]

        if not positions:
            lines.append("  No existing positions.")
            return "\n".join(lines)

        for p in positions:
            lines.append(f"\n{p.get('symbol', '')} ({p.get('product', '')}, held {p.get('days_held', 0)} days):")
            lines.append(f"  Entry: INR {p.get('entry', 0):.2f} | CMP: INR {p.get('ltp', 0):.2f} | P&L: {p.get('pnl_pct', 0):+.1f}%")
            lines.append(f"  Current SL: INR {p.get('stop_loss', 0):.2f} | Original target: INR {p.get('target', 0):.2f}")

        return "\n".join(lines)

    def _section_performance(self, perf: dict) -> str:
        lines = [
            "=" * 54,
            "PERFORMANCE CONTEXT (rolling 5-day summary)",
            "=" * 54,
        ]

        if not perf:
            lines.append("  No performance data yet (first day of trading)")
            return "\n".join(lines)

        total = perf.get("total_trades", 0)
        wins = perf.get("wins", 0)
        losses = perf.get("losses", 0)
        win_rate = (wins / total * 100) if total > 0 else 0

        lines.append(f"Total trades: {total} | Wins: {wins} | Losses: {losses}")
        lines.append(f"Win rate: {win_rate:.0f}%")
        lines.append(f"Average win: INR {perf.get('avg_win', 0):,.0f} | Average loss: INR {perf.get('avg_loss', 0):,.0f}")
        lines.append(f"Profit factor: {perf.get('profit_factor', 0):.1f}x")
        lines.append(f"Net P&L (5 days): INR {perf.get('net_pnl_5d', 0):+,.0f}")
        lines.append(f"Cumulative P&L (experiment): INR {perf.get('cumulative_pnl', 0):+,.0f}")

        return "\n".join(lines)

    def _section_footer(self, exp: dict, now: datetime) -> str:
        return (
            "=" * 54 + "\n"
            f"CURRENT TIME: {now.strftime('%H:%M')} IST | MARKET {self._time_until_close()}\n"
            f"EXPERIMENT DAY: {exp['day_number']} of {self._duration_days} | "
            f"TRADING DAYS LEFT: {exp['trading_days_left']}\n"
            + "=" * 54
        )
