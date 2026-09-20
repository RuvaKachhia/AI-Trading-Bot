import { NextResponse } from "next/server";
import { queryAll } from "@/lib/db";
import type { Trade } from "@/lib/types";

export const dynamic = "force-dynamic";

// Full trade history across every date — most recent first. Capped at 500 rows
// to keep the dashboard responsive once the journal grows; bump if needed.
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = Math.min(Number(searchParams.get("limit")) || 500, 2000);

    const trades = queryAll<Trade>(
      `SELECT id, timestamp, symbol, exchange, transaction_type, quantity, price,
              product, order_type, stop_loss, target, confidence, reasoning,
              status, fill_price, pnl
       FROM trades WHERE mode = 'PAPER'
       ORDER BY timestamp DESC LIMIT ?`,
      [limit]
    );

    return NextResponse.json(trades);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
