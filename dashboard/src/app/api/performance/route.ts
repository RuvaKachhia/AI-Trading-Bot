import { NextResponse } from "next/server";
import { queryAll } from "@/lib/db";
import type { DailySummary } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const summaries = queryAll<DailySummary>(
      `SELECT date, day_number, trades_count, wins, losses,
              total_pnl, cumulative_pnl, portfolio_value
       FROM daily_summaries WHERE mode = 'PAPER'
       ORDER BY date DESC LIMIT 15`
    );

    return NextResponse.json(summaries.reverse());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
