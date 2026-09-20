"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type {
  SummaryStats,
  Trade,
  AgentRunRow,
  LLMCall,
  DailySummary,
  ActivePosition,
  ActivePositionsResponse,
} from "@/lib/types";

function formatINR(n: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(n);
}

function pnlColor(n: number): string {
  return n > 0 ? "var(--positive)" : n < 0 ? "var(--negative)" : "inherit";
}

function StatusTag({ status }: { status: string }) {
  const cls =
    status === "SUCCESS" || status === "COMPLETE"
      ? "tag tag-success"
      : status === "ERROR" || status === "REJECTED"
        ? "tag tag-error"
        : status === "TIMEOUT"
          ? "tag tag-timeout"
          : "tag tag-running";
  return <span className={cls}>{status}</span>;
}

function SideTag({ side }: { side: string }) {
  return (
    <span className={side === "BUY" ? "tag tag-buy" : "tag tag-sell"}>
      {side}
    </span>
  );
}

export default function Dashboard() {
  const [summary, setSummary] = useState<SummaryStats | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradeHistory, setTradeHistory] = useState<Trade[]>([]);
  const [agents, setAgents] = useState<AgentRunRow[]>([]);
  const [llmCalls, setLlmCalls] = useState<LLMCall[]>([]);
  const [performance, setPerformance] = useState<DailySummary[]>([]);
  const [positions, setPositions] = useState<ActivePosition[]>([]);
  const [positionsSnapshotTs, setPositionsSnapshotTs] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<string>("");
  const [error, setError] = useState<string>("");

  const refresh = async () => {
    try {
      const [sumRes, trRes, agRes, llmRes, perfRes, posRes, histRes] = await Promise.all([
        fetch("/api/summary"),
        fetch("/api/trades"),
        fetch("/api/agents"),
        fetch("/api/llm-calls"),
        fetch("/api/performance"),
        fetch("/api/positions"),
        fetch("/api/trade-history"),
      ]);

      if (sumRes.ok) setSummary(await sumRes.json());
      if (trRes.ok) setTrades(await trRes.json());
      if (agRes.ok) setAgents(await agRes.json());
      if (llmRes.ok) setLlmCalls(await llmRes.json());
      if (perfRes.ok) setPerformance(await perfRes.json());
      if (posRes.ok) {
        const data: ActivePositionsResponse = await posRes.json();
        setPositions(data.rows ?? []);
        setPositionsSnapshotTs(data.snapshot_timestamp ?? null);
      }
      if (histRes.ok) setTradeHistory(await histRes.json());

      setLastRefresh(new Date().toLocaleTimeString());
      setError("");
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, []);

  const isMarketOpen = (() => {
    const now = new Date();
    const h = now.getHours();
    const m = now.getMinutes();
    const day = now.getDay();
    if (day === 0 || day === 6) return false;
    const t = h * 60 + m;
    return t >= 555 && t <= 930; // 9:15 - 15:30
  })();

  return (
    <main style={{ maxWidth: 920, margin: "0 auto", padding: "2rem 1rem" }}>
      {/* Header */}
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.8rem", fontWeight: 700, marginBottom: "0.25rem" }}>
          AI Trading Bot
        </h1>
        <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
          Autonomous Agent System &nbsp;
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: isMarketOpen ? "var(--positive)" : "var(--negative)",
              marginRight: 4,
            }}
          />
          {isMarketOpen ? "MARKET OPEN" : "MARKET CLOSED"} &nbsp;&middot;&nbsp;
          Last refresh: {lastRefresh || "loading..."} &nbsp;&middot;&nbsp;
          <Link href="/logs" style={{ color: "var(--foreground)", textDecoration: "underline" }}>
            Browse AI logs →
          </Link>
        </p>
        {error && (
          <p style={{ color: "var(--negative)", fontSize: "0.8rem" }}>{error}</p>
        )}
      </header>

      {/* Summary Stats */}
      {summary && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "1rem",
            marginBottom: "2rem",
          }}
        >
          <StatCard
            label="Portfolio Value"
            value={formatINR(summary.portfolio_value)}
            sub={
              summary.snapshot_timestamp
                ? `as of ${summary.snapshot_timestamp.split(" ")[1]?.slice(0, 5) ?? ""}`
                : "no snapshot yet"
            }
          />
          <StatCard label="Available Cash" value={formatINR(summary.cash)} />
          <StatCard
            label="Day P&L"
            value={formatINR(summary.day_pnl)}
            color={pnlColor(summary.day_pnl)}
            sub="realized (closed trades today)"
          />
          <StatCard
            label="Total P&L"
            value={formatINR(summary.total_pnl)}
            color={pnlColor(summary.total_pnl)}
            sub={`Realized ${formatINR(summary.total_pnl_realized)} · Unrealized ${formatINR(summary.total_pnl_unrealized)}`}
          />
          <StatCard
            label="Win Rate"
            value={`${(summary.win_rate * 100).toFixed(0)}%`}
            sub={`${summary.trades_today} trades today`}
          />
          <StatCard
            label="AI Cost Today"
            value={`$${summary.ai_cost_today.toFixed(4)}`}
          />
          <StatCard
            label="AI Cost To Date"
            value={`$${summary.ai_cost_total.toFixed(4)}`}
          />
        </div>
      )}

      {/* Today's Trades */}
      <Section title="Today's Trades">
        {trades.length === 0 ? (
          <Empty>No trades today</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Action</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Type</th>
                <th>P&L</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id}>
                  <td className="mono">{t.timestamp.split(" ")[1]?.slice(0, 5)}</td>
                  <td style={{ fontWeight: 600 }}>{t.symbol}</td>
                  <td><SideTag side={t.transaction_type} /></td>
                  <td className="mono">{t.quantity}</td>
                  <td className="mono">{t.fill_price?.toFixed(2) ?? t.price.toFixed(2)}</td>
                  <td>{t.product}</td>
                  <td className="mono" style={{ color: pnlColor(t.pnl ?? 0) }}>
                    {t.pnl != null ? formatINR(t.pnl) : "-"}
                  </td>
                  <td><StatusTag status={t.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Active Positions — live book from the latest mark-to-market snapshot */}
      <Section
        title="Active Positions"
        subtitle={
          positionsSnapshotTs
            ? `as of ${positionsSnapshotTs.replace("T", " ").slice(0, 16)}`
            : undefined
        }
      >
        {positions.length === 0 ? (
          <Empty>No open positions</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Product</th>
                <th>Qty</th>
                <th>Entry</th>
                <th>LTP</th>
                <th>P&L</th>
                <th>P&L %</th>
                <th>SL</th>
                <th>Target</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={`${p.symbol}-${p.product}-${p.side}`}>
                  <td style={{ fontWeight: 600 }}>{p.symbol}</td>
                  <td><SideTag side={p.side} /></td>
                  <td>{p.product}</td>
                  <td className="mono">{p.quantity}</td>
                  <td className="mono">{p.entry_price.toFixed(2)}</td>
                  <td className="mono">
                    {p.last_price ? p.last_price.toFixed(2) : "-"}
                  </td>
                  <td className="mono" style={{ color: pnlColor(p.pnl) }}>
                    {formatINR(p.pnl)}
                  </td>
                  <td className="mono" style={{ color: pnlColor(p.pnl_pct) }}>
                    {p.pnl_pct.toFixed(2)}%
                  </td>
                  <td className="mono">
                    {p.stop_loss ? p.stop_loss.toFixed(2) : "-"}
                  </td>
                  <td className="mono">
                    {p.target ? p.target.toFixed(2) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Trade History — every paper trade across all dates, newest first */}
      <Section
        title="Trade History"
        subtitle={
          tradeHistory.length > 0
            ? `${tradeHistory.length} trades`
            : undefined
        }
        defaultOpen={false}
      >
        {tradeHistory.length === 0 ? (
          <Empty>No trades yet</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Time</th>
                <th>Symbol</th>
                <th>Action</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Type</th>
                <th>P&L</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {tradeHistory.map((t) => {
                const [d, time] = t.timestamp.split(" ");
                return (
                  <tr key={t.id}>
                    <td className="mono">{d}</td>
                    <td className="mono">{time?.slice(0, 5)}</td>
                    <td style={{ fontWeight: 600 }}>{t.symbol}</td>
                    <td><SideTag side={t.transaction_type} /></td>
                    <td className="mono">{t.quantity}</td>
                    <td className="mono">
                      {t.fill_price?.toFixed(2) ?? t.price.toFixed(2)}
                    </td>
                    <td>{t.product}</td>
                    <td className="mono" style={{ color: pnlColor(t.pnl ?? 0) }}>
                      {t.pnl != null ? formatINR(t.pnl) : "-"}
                    </td>
                    <td><StatusTag status={t.status} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Section>

      {/* Agent Activity */}
      <Section title="Agent Activity">
        {agents.length === 0 ? (
          <Empty>No agent runs yet</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Agent</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.id}>
                  <td className="mono">{a.started_at.split(" ")[1]?.slice(0, 5)}</td>
                  <td style={{ fontWeight: 600 }}>{a.agent_name}</td>
                  <td><StatusTag status={a.status} /></td>
                  <td className="mono">{a.duration_seconds?.toFixed(1)}s</td>
                  <td style={{ fontSize: "0.8rem", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {a.error_message || a.output_summary?.slice(0, 100) || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* AI Call Log */}
      <Section title="AI Call Log">
        {llmCalls.length === 0 ? (
          <Empty>No AI calls yet</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Model</th>
                <th>Type</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>Latency</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {llmCalls.map((c) => (
                <tr key={c.call_id}>
                  <td className="mono">{c.timestamp.split(" ")[1]?.slice(0, 5)}</td>
                  <td>{c.model.includes("opus") ? "Opus" : c.model.includes("sonnet") ? "Sonnet" : "Haiku"}</td>
                  <td>{c.call_type}</td>
                  <td className="mono">{(c.input_tokens + c.output_tokens).toLocaleString()}</td>
                  <td className="mono">${c.total_cost_usd.toFixed(4)}</td>
                  <td className="mono">{(c.latency_ms / 1000).toFixed(1)}s</td>
                  <td><StatusTag status={c.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Performance */}
      <Section title="Daily Performance (Last 15 Days)">
        {performance.length === 0 ? (
          <Empty>No performance data yet</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Day</th>
                <th>Trades</th>
                <th>W/L</th>
                <th>Day P&L</th>
                <th>Cumulative</th>
                <th>Portfolio</th>
              </tr>
            </thead>
            <tbody>
              {performance.map((d) => (
                <tr key={d.date}>
                  <td className="mono">{d.date}</td>
                  <td className="mono">{d.day_number}</td>
                  <td className="mono">{d.trades_count}</td>
                  <td className="mono">{d.wins}/{d.losses}</td>
                  <td className="mono" style={{ color: pnlColor(d.total_pnl) }}>
                    {formatINR(d.total_pnl)}
                  </td>
                  <td className="mono" style={{ color: pnlColor(d.cumulative_pnl) }}>
                    {formatINR(d.cumulative_pnl)}
                  </td>
                  <td className="mono">{formatINR(d.portfolio_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Footer */}
      <footer style={{ marginTop: "2rem", textAlign: "center", color: "var(--muted)", fontSize: "0.75rem" }}>
        Refreshes every 15 seconds during market hours
      </footer>
    </main>
  );
}

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div
      style={{
        flex: "1 1 180px",
        background: "var(--card-bg)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "1rem 1.2rem",
      }}
    >
      <div
        style={{
          fontSize: "0.7rem",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: "var(--muted)",
          marginBottom: "0.3rem",
        }}
      >
        {label}
      </div>
      <div className="mono" style={{ fontSize: "1.3rem", fontWeight: 700, color }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "0.2rem" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  subtitle,
  defaultOpen = true,
  children,
}: {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  // Persist open/closed per section across refreshes. The key is derived from
  // the title so adding new sections doesn't disturb existing user state.
  const storageKey = `dash.section.open.${title}`;
  const [open, setOpen] = useState<boolean>(defaultOpen);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored !== null) setOpen(stored === "1");
    } catch {
      // localStorage unavailable (private mode, SSR mismatch) — keep default
    }
    setHydrated(true);
  }, [storageKey]);

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(storageKey, next ? "1" : "0");
      } catch {}
      return next;
    });
  };

  return (
    <section style={{ marginBottom: "2rem" }}>
      <h2
        onClick={toggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        style={{
          fontSize: "1rem",
          fontWeight: 700,
          marginBottom: open ? "0.75rem" : 0,
          paddingBottom: "0.5rem",
          borderBottom: "2px solid var(--foreground)",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "1rem",
          cursor: "pointer",
          userSelect: "none",
        }}
      >
        <span style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
          <span
            aria-hidden="true"
            style={{
              display: "inline-block",
              width: "0.7rem",
              fontSize: "0.7rem",
              color: "var(--muted)",
              transition: "transform 120ms ease",
              transform: open ? "rotate(90deg)" : "rotate(0deg)",
              transformOrigin: "center",
            }}
          >
            ▶
          </span>
          {title}
        </span>
        {subtitle && (
          <span
            style={{
              fontSize: "0.75rem",
              fontWeight: 400,
              color: "var(--muted)",
            }}
          >
            {subtitle}
          </span>
        )}
      </h2>
      {/* Avoid SSR/CSR open-state mismatch: only show body once hydrated has
          read localStorage. defaultOpen still renders on first paint pre-JS. */}
      {(hydrated ? open : defaultOpen) && children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ color: "var(--muted)", fontStyle: "italic", padding: "1rem 0" }}>
      {children}
    </p>
  );
}
