import { NextResponse } from "next/server";
import { queryAll } from "@/lib/db";
import type { LLMCall } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get("limit") || "30");

    const calls = queryAll<LLMCall>(
      `SELECT call_id, timestamp, model, call_type,
              input_tokens, output_tokens,
              (input_cost_usd + output_cost_usd +
               COALESCE(cache_read_cost_usd, 0) +
               COALESCE(cache_creation_cost_usd, 0)) as total_cost_usd,
              latency_ms, status, watchlist_symbols, decisions_count
       FROM llm_calls ORDER BY timestamp DESC LIMIT ?`,
      [limit]
    );

    return NextResponse.json(calls);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
