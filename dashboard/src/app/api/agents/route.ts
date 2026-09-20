import { NextResponse } from "next/server";
import { queryAll } from "@/lib/db";
import type { AgentRunRow } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get("limit") || "20");

    const runs = queryAll<AgentRunRow>(
      `SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?`,
      [limit]
    );

    return NextResponse.json(runs);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
