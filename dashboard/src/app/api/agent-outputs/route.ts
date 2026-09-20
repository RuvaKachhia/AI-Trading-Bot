import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";

export const dynamic = "force-dynamic";

const OUTPUTS_ROOT =
  process.env.TRADING_AGENT_OUTPUTS_PATH ||
  path.resolve(
    __dirname,
    "../../../../../ai-trading-bot/src/agents/outputs"
  );

/**
 * GET /api/agent-outputs           -> list dates
 * GET /api/agent-outputs?date=...  -> list files under that date
 * GET /api/agent-outputs?date=...&file=...
 *                                  -> return the file contents
 */
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isSafeName(s: string): boolean {
  return !s.includes("..") && !s.includes("/") && !s.includes("\\") && !s.includes("\0");
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date");
    const file = searchParams.get("file");

    if (!fs.existsSync(OUTPUTS_ROOT)) return NextResponse.json([]);

    if (!date) {
      const dates = fs
        .readdirSync(OUTPUTS_ROOT)
        .filter((d) => DATE_RE.test(d))
        .filter((d) => fs.statSync(path.join(OUTPUTS_ROOT, d)).isDirectory())
        .sort()
        .reverse();
      return NextResponse.json(dates);
    }

    if (!DATE_RE.test(date)) {
      return NextResponse.json({ error: "invalid date" }, { status: 400 });
    }
    if (file && !isSafeName(file)) {
      return NextResponse.json({ error: "invalid file" }, { status: 400 });
    }

    const dir = path.join(OUTPUTS_ROOT, date);
    if (!fs.existsSync(dir)) return NextResponse.json([]);

    if (!file) {
      // Sort by modification time, newest first.
      const files = fs
        .readdirSync(dir)
        .filter((f) => f.endsWith(".json"))
        .map((f) => ({
          name: f,
          mtime: fs.statSync(path.join(dir, f)).mtimeMs,
        }))
        .sort((a, b) => b.mtime - a.mtime)
        .map((x) => x.name);
      return NextResponse.json(files);
    }

    const full = path.join(dir, file);
    if (!fs.existsSync(full)) {
      return NextResponse.json({ error: "not found" }, { status: 404 });
    }
    const text = fs.readFileSync(full, "utf-8");
    try {
      return NextResponse.json(JSON.parse(text));
    } catch {
      return new NextResponse(text, {
        headers: { "content-type": "text/plain" },
      });
    }
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
