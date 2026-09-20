import { NextResponse } from "next/server";
import { queryAll } from "@/lib/db";
import type { Trade } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date") || new Date().toISOString().split("T")[0];

    const trades = queryAll<Trade>(
      `SELECT id, timestamp, symbol, exchange, transaction_type, quantity, price,
              product, order_type, stop_loss, target, confidence, reasoning,
              status, fill_price, pnl
       FROM trades WHERE DATE(timestamp) = ? AND mode = 'PAPER'
       ORDER BY timestamp DESC`,
      [date]
    );

    return NextResponse.json(trades);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
