import { NextResponse } from "next/server";
import { queryOne, queryAll } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const today = new Date().toISOString().split("T")[0];

    // Latest mark-to-market snapshot (written every market-pulse cycle + EOD).
    // Prefer this over summing avg_price * qty, which is cost basis and hides P&L.
    const snap = queryOne<{
      total_value: number;
      cash_available: number;
      cumulative_pnl: number;
      timestamp: string;
    }>(
      `SELECT total_value, cash_available, cumulative_pnl, timestamp
       FROM portfolio_snapshots
       WHERE mode = 'PAPER'
       ORDER BY timestamp DESC LIMIT 1`
    );

    // Fallback path if no snapshot exists yet (fresh DB / bot hasn't run a cycle).
    const cashRow = queryOne<{ balance: number }>(
      "SELECT balance FROM paper_cash WHERE id = 1"
    );
    const cashFallback = cashRow?.balance ?? 0;
    const holdings = queryAll<{ quantity: number; avg_price: number }>(
      "SELECT quantity, avg_price FROM paper_holdings WHERE quantity > 0"
    );
    const holdingsCostBasis = holdings.reduce(
      (sum, h) => sum + h.quantity * h.avg_price,
      0
    );

    const portfolioValue = snap ? snap.total_value : cashFallback + holdingsCostBasis;
    const cash = snap ? snap.cash_available : cashFallback;

    // Positions count
    const positions = queryAll(
      "SELECT * FROM paper_positions WHERE quantity != 0"
    );

    // Today's trades
    const tradesRow = queryOne<{ cnt: number; wins: number; losses: number; pnl: number }>(
      `SELECT COUNT(*) as cnt,
              SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
              SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
              COALESCE(SUM(pnl), 0) as pnl
       FROM trades WHERE DATE(timestamp) = ? AND mode = 'PAPER' AND status = 'COMPLETE'`,
      [today]
    );

    // AI cost today
    const costRow = queryOne<{ total: number }>(
      `SELECT COALESCE(SUM(
        input_cost_usd + output_cost_usd +
        COALESCE(cache_read_cost_usd, 0) + COALESCE(cache_creation_cost_usd, 0)
      ), 0) as total FROM llm_calls WHERE date = ?`,
      [today]
    );

    // AI cost to date (all-time across every llm_calls row, all models)
    const costAllRow = queryOne<{ total: number }>(
      `SELECT COALESCE(SUM(
        input_cost_usd + output_cost_usd +
        COALESCE(cache_read_cost_usd, 0) + COALESCE(cache_creation_cost_usd, 0)
      ), 0) as total FROM llm_calls`
    );

    // All-time realized P&L (sum of every closed paper trade with a recorded P&L).
    const realizedRow = queryOne<{ total: number }>(
      `SELECT COALESCE(SUM(pnl), 0) as total FROM trades
       WHERE mode = 'PAPER' AND status = 'COMPLETE' AND pnl IS NOT NULL`
    );
    const totalRealized = realizedRow?.total ?? 0;
    // cumulative_pnl (from snapshot) = total_value - starting_capital
    //                               = all-time realized + current mark-to-market unrealized
    // So unrealized = cumulative - realized.
    const totalPnl = snap?.cumulative_pnl ?? 0;
    const totalUnrealized = snap ? totalPnl - totalRealized : 0;

    const wins = tradesRow?.wins ?? 0;
    const losses = tradesRow?.losses ?? 0;
    const totalTrades = wins + losses;

    return NextResponse.json({
      portfolio_value: portfolioValue,
      cash,
      snapshot_timestamp: snap?.timestamp ?? null,
      day_pnl: tradesRow?.pnl ?? 0,
      total_pnl: totalPnl,
      total_pnl_realized: totalRealized,
      total_pnl_unrealized: totalUnrealized,
      win_rate: totalTrades > 0 ? wins / totalTrades : 0,
      ai_cost_today: costRow?.total ?? 0,
      ai_cost_total: costAllRow?.total ?? 0,
      holdings_count: holdings.length,
      positions_count: positions.length,
      trades_today: tradesRow?.cnt ?? 0,
    });
  } catch (e) {
    return NextResponse.json(
      { error: String(e) },
      { status: 500 }
    );
  }
}
