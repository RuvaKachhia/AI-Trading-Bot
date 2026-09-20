import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";

export const dynamic = "force-dynamic";

const LOG_ROOT =
  process.env.TRADING_LOG_PATH ||
  path.resolve(__dirname, "../../../../../ai-trading-bot/logs");

/**
 * GET /api/ai-logs           -> list all available dates with AI call dirs
 * GET /api/ai-logs?date=YYYY-MM-DD
 *                            -> list the per-call directories for that date
 * GET /api/ai-logs?date=YYYY-MM-DD&call=NNN_HHMM_type
 *                            -> return contents of all files in that call dir
 */
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isSafeName(s: string): boolean {
  return !s.includes("..") && !s.includes("/") && !s.includes("\\") && !s.includes("\0");
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date");
    const call = searchParams.get("call");

    // List dates
    if (!date) {
      if (!fs.existsSync(LOG_ROOT)) return NextResponse.json([]);
      const dates = fs
        .readdirSync(LOG_ROOT)
        .filter((d) => DATE_RE.test(d))
        .filter((d) => fs.existsSync(path.join(LOG_ROOT, d, "ai")))
        .sort()
        .reverse();
      return NextResponse.json(dates);
    }

    if (!DATE_RE.test(date)) {
      return NextResponse.json({ error: "invalid date" }, { status: 400 });
    }
    if (call && !isSafeName(call)) {
      return NextResponse.json({ error: "invalid call" }, { status: 400 });
    }

    const aiDir = path.join(LOG_ROOT, date, "ai");
    if (!fs.existsSync(aiDir)) return NextResponse.json([]);

    // List calls for a date, sorted by HHMM portion of dir name, newest first.
    // Dir names look like "NNN_HHMM_call_type" — the NNN prefix can
    // collide (legacy migration + structured runs both start at 001),
    // so we sort on the time portion which is globally unique within a day.
    if (!call) {
      const calls = fs
        .readdirSync(aiDir)
        .filter((d) => fs.statSync(path.join(aiDir, d)).isDirectory())
        .sort((a, b) => {
          const timeA = a.match(/^\d+_(\d{4})_/)?.[1] ?? "0000";
          const timeB = b.match(/^\d+_(\d{4})_/)?.[1] ?? "0000";
          if (timeA === timeB) return b.localeCompare(a); // stable tiebreak
          return timeB.localeCompare(timeA); // descending (newest first)
        });
      // Attach metadata if present (cheap summary)
      const enriched = calls.map((c) => {
        const metaPath = path.join(aiDir, c, "metadata.json");
        let meta: Record<string, unknown> | null = null;
        if (fs.existsSync(metaPath)) {
          try {
            meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
          } catch {}
        }
        return { dir: c, metadata: meta };
      });
      return NextResponse.json(enriched);
    }

    // Return files in a specific call dir
    const callDir = path.join(aiDir, call);
    if (!fs.existsSync(callDir)) {
      return NextResponse.json({ error: "not found" }, { status: 404 });
    }
    const files = fs.readdirSync(callDir).filter((f) => !f.startsWith("."));
    const result: Record<string, string> = {};
    for (const f of files) {
      const full = path.join(callDir, f);
      if (!fs.statSync(full).isFile()) continue;
      try {
        result[f] = fs.readFileSync(full, "utf-8");
      } catch (e) {
        result[f] = `<read error: ${String(e)}>`;
      }
    }
    return NextResponse.json(result);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
