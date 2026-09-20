"""
AI Trading Bot — Streamlit Dashboard.

Run: streamlit run dashboard/app.py
"""

import json
import os
import sys
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml

# ─── CONFIG ───

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "trading_bot.db"
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@st.cache_resource
def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def get_db_connection(db_path: str = None):
    path = db_path or str(DEFAULT_DB_PATH)
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query_df(conn, sql, params=()) -> pd.DataFrame:
    if conn is None:
        return pd.DataFrame()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame()


def mode_filter_sql(column: str, view_mode: str) -> str:
    """Return a SQL WHERE/AND clause fragment for mode filtering."""
    if view_mode == "Both":
        return ""
    return f" AND {column} = '{view_mode}'"


def mode_filter_params(view_mode: str) -> tuple:
    """Return params tuple for parameterized mode filter."""
    if view_mode == "Both":
        return ()
    return (view_mode,)


# ─── PAGE CONFIG ───

st.set_page_config(
    page_title="AI Trading Bot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── SIDEBAR ───

config = load_config()
starting_capital = config.get("experiment", {}).get("starting_capital", 100000)
active_mode = config.get("trading", {}).get("mode", "PAPER")
start_date_str = config.get("experiment", {}).get("start_date", "2026-03-01")

st.sidebar.title("AI Trading Bot")
st.sidebar.caption(f"Active Mode: **{active_mode}** | Capital: INR {starting_capital:,.0f}")

# Mode selector for dashboard view
view_mode = st.sidebar.radio(
    "View Mode",
    ["PAPER", "LIVE", "Both"],
    index=0 if active_mode == "PAPER" else 1,
    help="Filter all dashboard data by trading mode",
)

# Experiment day number
try:
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    day_number = (date.today() - start_dt).days + 1
    duration = config.get("experiment", {}).get("duration_days", 30)
    st.sidebar.progress(
        min(day_number / duration, 1.0),
        text=f"Day {day_number} / {duration}",
    )
except Exception:
    day_number = 0

# DB connection
conn = get_db_connection()
if conn is None:
    st.error("Database not found. Run the bot at least once to create it.")
    st.stop()

# Auto-refresh
refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=False)
if refresh:
    st.rerun()

# ─── TABS ───

tab_overview, tab_trades, tab_performance, tab_llm, tab_guardrails, tab_details = st.tabs(
    ["Portfolio", "Trades", "Performance", "LLM Costs", "Guardrails", "Details"]
)


# ═══════════════════════════════════════════════
# TAB 1: PORTFOLIO OVERVIEW
# ═══════════════════════════════════════════════

with tab_overview:
    st.header(f"Portfolio Overview ({view_mode})")

    # Latest snapshot — filtered by mode
    if view_mode == "Both":
        snapshot = query_df(
            conn,
            "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1",
        )
    else:
        snapshot = query_df(
            conn,
            "SELECT * FROM portfolio_snapshots WHERE mode = ? ORDER BY timestamp DESC LIMIT 1",
            (view_mode,),
        )

    if not snapshot.empty:
        s = snapshot.iloc[0]
        total = s["total_value"]
        cash = s["cash_available"]
        deployed = s["deployed"]
        daily_pnl = s["daily_pnl"]
        cum_pnl = s["cumulative_pnl"]
        deployed_pct = (deployed / total * 100) if total > 0 else 0

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Value", f"INR {total:,.0f}", f"{cum_pnl:+,.0f}")
        col2.metric("Cash", f"INR {cash:,.0f}")
        col3.metric("Deployed", f"INR {deployed:,.0f}", f"{deployed_pct:.0f}%")
        col4.metric("Day P&L", f"INR {daily_pnl:+,.0f}")
        col5.metric("Cumulative P&L", f"INR {cum_pnl:+,.0f}")

        # Holdings
        holdings_json = s.get("holdings_json", "[]")
        try:
            holdings = json.loads(holdings_json) if holdings_json else []
        except Exception:
            holdings = []

        if holdings:
            st.subheader("Current Holdings (CNC)")
            df_h = pd.DataFrame(holdings)
            if not df_h.empty:
                display_cols = [c for c in ["symbol", "quantity", "avg_price", "ltp", "pnl", "pnl_pct"] if c in df_h.columns]
                st.dataframe(df_h[display_cols] if display_cols else df_h, use_container_width=True)

        # Positions
        positions_json = s.get("positions_json", "[]")
        try:
            positions = json.loads(positions_json) if positions_json else []
        except Exception:
            positions = []

        if positions:
            st.subheader("MIS Positions")
            df_p = pd.DataFrame(positions)
            if not df_p.empty:
                display_cols = [c for c in ["symbol", "quantity", "entry_price", "ltp", "pnl", "side"] if c in df_p.columns]
                st.dataframe(df_p[display_cols] if display_cols else df_p, use_container_width=True)
    else:
        st.info("No portfolio snapshots yet. Run the bot to generate data.")

    # Portfolio value over time
    if view_mode == "Both":
        snapshots_df = query_df(
            conn,
            "SELECT timestamp, total_value, cash_available, deployed, daily_pnl, "
            "cumulative_pnl, mode FROM portfolio_snapshots ORDER BY timestamp",
        )
    else:
        snapshots_df = query_df(
            conn,
            "SELECT timestamp, total_value, cash_available, deployed, daily_pnl, "
            "cumulative_pnl, mode FROM portfolio_snapshots WHERE mode = ? ORDER BY timestamp",
            (view_mode,),
        )
    if not snapshots_df.empty and len(snapshots_df) > 1:
        st.subheader("Portfolio Value Over Time")
        snapshots_df["timestamp"] = pd.to_datetime(snapshots_df["timestamp"])
        st.line_chart(
            snapshots_df.set_index("timestamp")[["total_value"]],
            use_container_width=True,
        )


# ═══════════════════════════════════════════════
# TAB 2: TRADES
# ═══════════════════════════════════════════════

with tab_trades:
    st.header(f"Trade Log ({view_mode})")

    # Date filter
    col_a, col_b = st.columns(2)
    with col_a:
        trade_date_from = st.date_input(
            "From",
            value=date.today() - timedelta(days=7),
            key="trade_from",
        )
    with col_b:
        trade_date_to = st.date_input("To", value=date.today(), key="trade_to")

    if view_mode == "Both":
        trades_df = query_df(
            conn,
            """SELECT timestamp, symbol, exchange, transaction_type, quantity,
                      price, fill_price, product, order_type, stop_loss, target,
                      confidence, reasoning, status, mode
               FROM trades
               WHERE DATE(timestamp) BETWEEN ? AND ?
               ORDER BY timestamp DESC""",
            (trade_date_from.isoformat(), trade_date_to.isoformat()),
        )
    else:
        trades_df = query_df(
            conn,
            """SELECT timestamp, symbol, exchange, transaction_type, quantity,
                      price, fill_price, product, order_type, stop_loss, target,
                      confidence, reasoning, status, mode
               FROM trades
               WHERE DATE(timestamp) BETWEEN ? AND ? AND mode = ?
               ORDER BY timestamp DESC""",
            (trade_date_from.isoformat(), trade_date_to.isoformat(), view_mode),
        )

    if not trades_df.empty:
        # Summary row
        total_trades = len(trades_df)
        buys = len(trades_df[trades_df["transaction_type"] == "BUY"])
        sells = len(trades_df[trades_df["transaction_type"].isin(["SELL", "CLOSE"])])
        st.caption(f"Total: {total_trades} trades | Buys: {buys} | Sells/Closes: {sells}")

        st.dataframe(trades_df, use_container_width=True, height=400)

        # Claude's reasoning for selected trade
        st.subheader("Trade Reasoning")
        reasons = trades_df[trades_df["reasoning"].notna() & (trades_df["reasoning"] != "")]
        if not reasons.empty:
            selected_idx = st.selectbox(
                "Select trade",
                reasons.index,
                format_func=lambda i: f"{reasons.loc[i, 'timestamp']} — {reasons.loc[i, 'transaction_type']} {reasons.loc[i, 'symbol']}",
            )
            st.text_area(
                "Reasoning",
                value=reasons.loc[selected_idx, "reasoning"],
                height=150,
                disabled=True,
            )
    else:
        st.info("No trades in selected date range.")


# ═══════════════════════════════════════════════
# TAB 3: PERFORMANCE
# ═══════════════════════════════════════════════

with tab_performance:
    st.header(f"Performance Metrics ({view_mode})")

    # Daily summaries — filtered by mode
    if view_mode == "Both":
        daily_df = query_df(
            conn,
            """SELECT date, day_number, trades_count, wins, losses,
                      total_pnl, cumulative_pnl, portfolio_value,
                      market_bias, llm_cost_inr, mode
               FROM daily_summaries ORDER BY date""",
        )
    else:
        daily_df = query_df(
            conn,
            """SELECT date, day_number, trades_count, wins, losses,
                      total_pnl, cumulative_pnl, portfolio_value,
                      market_bias, llm_cost_inr, mode
               FROM daily_summaries WHERE mode = ? ORDER BY date""",
            (view_mode,),
        )

    if not daily_df.empty:
        latest = daily_df.iloc[-1]

        # Key metrics
        total_days = len(daily_df)
        total_trades = daily_df["trades_count"].sum()
        total_wins = daily_df["wins"].sum()
        total_losses = daily_df["losses"].sum()
        win_rate = (total_wins / (total_wins + total_losses) * 100) if (total_wins + total_losses) > 0 else 0
        cum_pnl = latest["cumulative_pnl"]
        total_llm_cost = daily_df["llm_cost_inr"].sum()

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Trading Days", total_days)
        col2.metric("Total Trades", int(total_trades))
        col3.metric("Win Rate", f"{win_rate:.1f}%")
        col4.metric("Cumulative P&L", f"INR {cum_pnl:+,.0f}")
        col5.metric("Total LLM Cost", f"INR {total_llm_cost:,.2f}")

        # P&L chart
        st.subheader("Cumulative P&L")
        daily_df["date"] = pd.to_datetime(daily_df["date"])
        st.line_chart(
            daily_df.set_index("date")[["cumulative_pnl"]],
            use_container_width=True,
        )

        # Daily P&L bar chart
        st.subheader("Daily P&L")
        chart_df = daily_df.set_index("date")[["total_pnl"]]
        st.bar_chart(chart_df, use_container_width=True)

        # Profit factor
        winning_days = daily_df[daily_df["total_pnl"] > 0]["total_pnl"].sum()
        losing_days = abs(daily_df[daily_df["total_pnl"] < 0]["total_pnl"].sum())
        pf = winning_days / losing_days if losing_days > 0 else float("inf")

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Profit Factor", f"{pf:.2f}")
        col_b.metric("Best Day", f"INR {daily_df['total_pnl'].max():+,.0f}")
        col_c.metric("Worst Day", f"INR {daily_df['total_pnl'].min():+,.0f}")

        # Daily details table
        st.subheader("Daily Summary Table")
        display_cols = ["date", "day_number", "trades_count", "wins", "losses",
                        "total_pnl", "cumulative_pnl", "portfolio_value", "llm_cost_inr"]
        if view_mode == "Both":
            display_cols.append("mode")
        st.dataframe(daily_df[display_cols], use_container_width=True)
    else:
        st.info("No daily summaries yet. Run the bot to generate performance data.")


# ═══════════════════════════════════════════════
# TAB 4: LLM COSTS (mode-agnostic)
# ═══════════════════════════════════════════════

with tab_llm:
    st.header("LLM Cost Dashboard")

    # Today's costs
    today_str = date.today().isoformat()
    today_cost = query_df(
        conn,
        "SELECT * FROM llm_daily_costs WHERE date = ?",
        (today_str,),
    )

    if not today_cost.empty:
        tc = today_cost.iloc[0]

        st.subheader(f"Today ({today_str})")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Cost", f"INR {tc['total_cost_inr']:.2f}")
        col2.metric("Total Calls", int(tc["total_calls"]))
        col3.metric("Total Tokens", f"{int(tc['total_tokens']):,}")
        col4.metric("Cache Savings", f"INR {tc.get('cache_savings_inr', 0):.2f}")

        # Cost by model
        st.subheader("Cost by Model")
        model_data = {
            "Model": ["Haiku", "Sonnet", "Opus"],
            "Calls": [tc["haiku_calls"], tc["sonnet_calls"], tc["opus_calls"]],
            "Input Tokens": [tc["haiku_input_tokens"], tc["sonnet_input_tokens"], tc["opus_input_tokens"]],
            "Output Tokens": [tc["haiku_output_tokens"], tc["sonnet_output_tokens"], tc["opus_output_tokens"]],
            "Cost (INR)": [tc["haiku_cost_inr"], tc["sonnet_cost_inr"], tc["opus_cost_inr"]],
        }
        st.dataframe(pd.DataFrame(model_data), use_container_width=True)

        # Cost by call type
        st.subheader("Cost by Call Type")
        type_data = {
            "Call Type": ["News", "Pulse", "Decision", "EOD", "Pre-market", "Retry"],
            "Calls": [
                tc["news_calls"], tc["pulse_calls"], tc["decision_calls"],
                tc["eod_calls"], tc["premarket_calls"], tc["retry_calls"],
            ],
            "Cost (INR)": [
                tc["news_cost_inr"], tc["pulse_cost_inr"], tc["decision_cost_inr"],
                tc["eod_cost_inr"], tc["premarket_cost_inr"], tc["retry_cost_inr"],
            ],
        }
        st.dataframe(pd.DataFrame(type_data), use_container_width=True)
    else:
        st.info("No LLM cost data for today.")

    # Daily cost trend
    cost_trend = query_df(
        conn,
        "SELECT date, total_cost_inr, total_calls, total_tokens, "
        "cumulative_cost_inr, haiku_cost_inr, sonnet_cost_inr, opus_cost_inr, "
        "cache_savings_inr, failed_calls, trading_pnl_inr "
        "FROM llm_daily_costs ORDER BY date",
    )

    if not cost_trend.empty and len(cost_trend) > 1:
        cost_trend["date"] = pd.to_datetime(cost_trend["date"])

        st.subheader("Daily Cost Trend")
        st.line_chart(
            cost_trend.set_index("date")[["total_cost_inr"]],
            use_container_width=True,
        )

        # Cumulative cost vs trading P&L
        if cost_trend["trading_pnl_inr"].notna().any():
            st.subheader("Cumulative Cost vs Trading P&L")
            cum_cost = cost_trend["total_cost_inr"].cumsum()
            cum_pnl = cost_trend["trading_pnl_inr"].fillna(0).cumsum()
            compare_df = pd.DataFrame({
                "Cumulative LLM Cost": cum_cost.values,
                "Cumulative Trading P&L": cum_pnl.values,
            }, index=cost_trend["date"])
            st.line_chart(compare_df, use_container_width=True)

        # Cost breakdown by model over time
        st.subheader("Cost Breakdown by Model (Daily)")
        model_trend = cost_trend.set_index("date")[
            ["haiku_cost_inr", "sonnet_cost_inr", "opus_cost_inr"]
        ].rename(columns={
            "haiku_cost_inr": "Haiku",
            "sonnet_cost_inr": "Sonnet",
            "opus_cost_inr": "Opus",
        })
        st.bar_chart(model_trend, use_container_width=True)

    # Token usage by hour (heatmap-like)
    hourly = query_df(
        conn,
        """SELECT strftime('%H', timestamp) as hour,
                  SUM(input_tokens + output_tokens) as tokens,
                  COUNT(*) as calls
           FROM llm_calls
           WHERE date = ?
           GROUP BY hour ORDER BY hour""",
        (today_str,),
    )
    if not hourly.empty:
        st.subheader("Token Usage by Hour (Today)")
        hourly = hourly.set_index("hour")
        st.bar_chart(hourly[["tokens"]], use_container_width=True)

    # Recent LLM calls table
    st.subheader("Recent LLM Calls")
    recent_calls = query_df(
        conn,
        """SELECT timestamp, model, call_type, call_subtype,
                  input_tokens, output_tokens, cache_read_tokens,
                  (input_cost_inr + output_cost_inr + COALESCE(cache_read_cost_inr, 0)
                   + COALESCE(cache_creation_cost_inr, 0)) as total_cost_inr,
                  latency_ms, status, watchlist_symbols, decisions_count,
                  user_prompt_file, response_file
           FROM llm_calls ORDER BY timestamp DESC LIMIT 50""",
    )

    if not recent_calls.empty:
        st.dataframe(recent_calls, use_container_width=True, height=300)

        # Per-call drill-down
        st.subheader("Call Detail Drill-Down")
        call_idx = st.selectbox(
            "Select call to inspect",
            recent_calls.index,
            format_func=lambda i: (
                f"{recent_calls.loc[i, 'timestamp']} | "
                f"{recent_calls.loc[i, 'call_type']} | "
                f"{recent_calls.loc[i, 'model']}"
            ),
            key="llm_drill",
        )
        selected_call = recent_calls.loc[call_idx]

        col_prompt, col_response = st.columns(2)
        with col_prompt:
            st.caption("User Prompt")
            prompt_file = selected_call.get("user_prompt_file", "")
            if prompt_file and os.path.exists(prompt_file):
                with open(prompt_file, "r", encoding="utf-8") as f:
                    st.text_area("Prompt", f.read(), height=300, disabled=True, key="prompt_view")
            else:
                st.caption(f"File: {prompt_file or 'N/A'}")

        with col_response:
            st.caption("Response")
            resp_file = selected_call.get("response_file", "")
            if resp_file and os.path.exists(resp_file):
                with open(resp_file, "r", encoding="utf-8") as f:
                    st.text_area("Response", f.read(), height=300, disabled=True, key="resp_view")
            else:
                st.caption(f"File: {resp_file or 'N/A'}")

    # Error log
    failed = query_df(
        conn,
        """SELECT timestamp, model, call_type, status, error_message, http_status_code
           FROM llm_calls WHERE status != 'SUCCESS'
           ORDER BY timestamp DESC LIMIT 20""",
    )
    if not failed.empty:
        st.subheader("Failed / Error Calls")
        st.dataframe(failed, use_container_width=True)


# ═══════════════════════════════════════════════
# TAB 5: GUARDRAILS
# ═══════════════════════════════════════════════

with tab_guardrails:
    st.header(f"Guardrail Activity ({view_mode})")

    if view_mode == "Both":
        gr_df = query_df(
            conn,
            """SELECT g.timestamp, g.is_valid, g.errors_json, g.warnings_json,
                      t.symbol, t.transaction_type, t.quantity, t.price, t.confidence, t.mode
               FROM guardrail_log g
               LEFT JOIN trades t ON g.trade_id = t.id
               ORDER BY g.timestamp DESC LIMIT 100""",
        )
    else:
        gr_df = query_df(
            conn,
            """SELECT g.timestamp, g.is_valid, g.errors_json, g.warnings_json,
                      t.symbol, t.transaction_type, t.quantity, t.price, t.confidence, t.mode
               FROM guardrail_log g
               LEFT JOIN trades t ON g.trade_id = t.id
               WHERE t.mode = ? OR t.mode IS NULL
               ORDER BY g.timestamp DESC LIMIT 100""",
            (view_mode,),
        )

    if not gr_df.empty:
        # Summary
        total_checks = len(gr_df)
        passed = gr_df["is_valid"].sum()
        blocked = total_checks - passed
        block_rate = (blocked / total_checks * 100) if total_checks > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Checks", total_checks)
        col2.metric("Passed", int(passed))
        col3.metric("Blocked", int(blocked), f"{block_rate:.0f}%")

        # Blocked trades
        blocked_df = gr_df[gr_df["is_valid"] == 0]
        if not blocked_df.empty:
            st.subheader("Blocked Trades")
            for _, row in blocked_df.iterrows():
                errors = row.get("errors_json", "[]")
                try:
                    errors_list = json.loads(errors) if errors else []
                except Exception:
                    errors_list = [str(errors)]

                symbol = row.get("symbol", "?")
                tx = row.get("transaction_type", "?")
                ts = row.get("timestamp", "")
                with st.expander(f"{ts} — {tx} {symbol} (BLOCKED)"):
                    for err in errors_list:
                        st.error(err)

        # All checks table
        st.subheader("Full Guardrail Log")
        display_df = gr_df.copy()
        display_df["is_valid"] = display_df["is_valid"].map({1: "PASS", 0: "BLOCKED"})
        st.dataframe(display_df, use_container_width=True, height=300)
    else:
        st.info("No guardrail checks recorded yet.")


# ═══════════════════════════════════════════════
# TAB 6: DETAILS / DIAGNOSTICS
# ═══════════════════════════════════════════════

with tab_details:
    st.header("System Details")

    # Config summary
    st.subheader("Configuration")
    col1, col2 = st.columns(2)
    with col1:
        st.json({
            "mode": active_mode,
            "starting_capital": starting_capital,
            "start_date": start_date_str,
            "duration_days": config.get("experiment", {}).get("duration_days", 30),
            "max_position_pct": config.get("trading", {}).get("max_position_pct", 0.20),
            "daily_loss_limit_pct": config.get("risk", {}).get("daily_loss_limit_pct", 0.03),
        })
    with col2:
        st.json({
            "decision_model": config.get("ai", {}).get("decision_model", ""),
            "analysis_model": config.get("ai", {}).get("analysis_model", ""),
            "news_model": config.get("ai", {}).get("news_model", ""),
            "pulse_interval_min": config.get("pipeline", {}).get("market_pulse_interval_minutes", 30),
            "sl_check_interval_min": config.get("resilience", {}).get("sl_health_check_interval_min", 5),
        })

    # Watchlist history
    st.subheader("Recent Watchlists")
    wl_df = query_df(
        conn,
        "SELECT timestamp, session_id, symbols, reasons_json "
        "FROM watchlist_history ORDER BY timestamp DESC LIMIT 20",
    )
    if not wl_df.empty:
        st.dataframe(wl_df, use_container_width=True)

    # Paper trading state (show when view mode includes PAPER)
    if view_mode in ("PAPER", "Both"):
        st.subheader("Paper Trading State")

        paper_cash = query_df(conn, "SELECT balance FROM paper_cash WHERE id = 1")
        if not paper_cash.empty:
            st.metric("Paper Cash", f"INR {paper_cash.iloc[0]['balance']:,.2f}")

        paper_h = query_df(conn, "SELECT * FROM paper_holdings WHERE quantity > 0")
        if not paper_h.empty:
            st.caption("Paper Holdings")
            st.dataframe(paper_h, use_container_width=True)

        paper_p = query_df(conn, "SELECT * FROM paper_positions WHERE quantity != 0")
        if not paper_p.empty:
            st.caption("Paper MIS Positions")
            st.dataframe(paper_p, use_container_width=True)

        paper_o = query_df(
            conn,
            "SELECT * FROM paper_orders WHERE status IN ('OPEN', 'TRIGGER PENDING') "
            "ORDER BY placed_at DESC",
        )
        if not paper_o.empty:
            st.caption("Pending Paper Orders")
            st.dataframe(paper_o, use_container_width=True)

    # Position tracking — filtered by mode
    st.subheader("Open Position Tracking")
    if view_mode == "Both":
        pos_track = query_df(
            conn,
            "SELECT * FROM position_tracking WHERE status = 'OPEN'",
        )
    else:
        pos_track = query_df(
            conn,
            "SELECT * FROM position_tracking WHERE status = 'OPEN' AND mode = ?",
            (view_mode,),
        )
    if not pos_track.empty:
        st.dataframe(pos_track, use_container_width=True)
    else:
        st.caption("No open tracked positions.")

    # DB stats
    st.subheader("Database Stats")
    tables = [
        "trades", "portfolio_snapshots", "llm_calls", "llm_daily_costs",
        "guardrail_log", "daily_summaries", "paper_holdings", "paper_positions",
        "paper_orders", "position_tracking", "watchlist_history",
    ]
    stats = {}
    for t in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {t}").fetchone()
            stats[t] = row[0] if row else 0
        except Exception:
            stats[t] = "N/A"

    st.json(stats)

# Close connection
conn.close()
