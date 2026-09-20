import { NextResponse } from "next/server";
import { queryAll, queryOne } from "@/lib/db";
import type { ActivePosition } from "@/lib/types";

export const dynamic = "force-dynamic";

// The mark-to-market snapshot is the dashboard's source of truth for live P&L:
// the bot writes it every market-pulse cycle with per-symbol LTP + P&L already
// computed, so we don't need to re-query Dhan from the read-only dashboard DB.
type SnapshotRow = {
  timestamp: string;
  holdings_json: string | null;
  positions_json: string | null;
};

type HoldingJson = {
  symbol: string;
  exchange: string;
  quantity: number;
  avg_price: number;
  last_price: number;
  pnl: number;
  pnl_pct: number;
  days_held: number;
  stop_loss: number;
  target: number;
};

type PositionJson = HoldingJson & {
  side: string;
  entry: number;
  ltp: number;
};

function safeParse<T>(raw: string | null): T[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

export async function GET() {
  try {
    const snap = queryOne<SnapshotRow>(
      `SELECT timestamp, holdings_json, positions_json
       FROM portfolio_snapshots
       WHERE mode = 'PAPER'
       ORDER BY timestamp DESC LIMIT 1`
    );

    const holdings = safeParse<HoldingJson>(snap?.holdings_json ?? null);
    const mis = safeParse<PositionJson>(snap?.positions_json ?? null);

    // CNC SL/target live on the latest COMPLETE BUY trade row per symbol —
    // paper_broker.modify_sl_target writes there on MODIFY. The snapshot
    // JSON records 0 for CNC SL/target (paper_holdings has no such column),
    // so we overlay the live values from trades. Using a per-symbol latest
    // pick rather than a GROUP BY so we don't depend on ORDER BY semantics
    // across aggregated rows.
    const cncSlTgt = new Map<string, { stop_loss: number; target: number }>();
    if (holdings.length > 0) {
      const trades = queryAll<{
        symbol: string;
        exchange: string;
        stop_loss: number | null;
        target: number | null;
      }>(
        `SELECT symbol, exchange, stop_loss, target
         FROM trades
         WHERE transaction_type = 'BUY' AND status = 'COMPLETE'
           AND mode = 'PAPER'
         ORDER BY timestamp DESC`
      );
      for (const t of trades) {
        const k = `${t.symbol}|${t.exchange}`;
        if (!cncSlTgt.has(k)) {
          cncSlTgt.set(k, {
            stop_loss: t.stop_loss ?? 0,
            target: t.target ?? 0,
          });
        }
      }
    }

    const rows: ActivePosition[] = [
      ...holdings
        .filter((h) => h.quantity > 0)
        .map((h) => {
          const live = cncSlTgt.get(`${h.symbol}|${h.exchange}`);
          return {
            symbol: h.symbol,
            exchange: h.exchange,
            product: "CNC",
            side: "BUY",
            quantity: h.quantity,
            entry_price: h.avg_price,
            last_price: h.last_price,
            pnl: h.pnl,
            pnl_pct: h.pnl_pct,
            days_held: h.days_held,
            stop_loss: live?.stop_loss ?? h.stop_loss ?? 0,
            target: live?.target ?? h.target ?? 0,
          };
        }),
      ...mis
        .filter((p) => p.quantity !== 0)
        .map((p) => ({
          symbol: p.symbol,
          exchange: p.exchange,
          product: "MIS",
          side: p.side,
          quantity: Math.abs(p.quantity),
          entry_price: p.entry,
          last_price: p.ltp,
          pnl: p.pnl,
          pnl_pct: p.pnl_pct,
          days_held: p.days_held ?? 0,
          stop_loss: p.stop_loss ?? 0,
          target: p.target ?? 0,
        })),
    ];

    return NextResponse.json({
      snapshot_timestamp: snap?.timestamp ?? null,
      rows,
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
