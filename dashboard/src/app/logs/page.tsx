"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import FormattedView from "@/components/FormattedView";

type CallEntry = {
  dir: string;
  metadata: {
    call_id?: string;
    model?: string;
    call_type?: string;
    timestamp?: string;
    tokens?: { input?: number; output?: number; cache_read?: number };
    cost_usd?: { total_cost_usd?: number };
    latency_ms?: number;
    status?: string;
  } | null;
};

type Tab = "ai" | "agents";

export default function LogsBrowser() {
  const [tab, setTab] = useState<Tab>("ai");
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<string>("");

  // AI calls
  const [calls, setCalls] = useState<CallEntry[]>([]);
  const [selectedCall, setSelectedCall] = useState<string>("");
  const [callFiles, setCallFiles] = useState<Record<string, string>>({});
  const [activeFile, setActiveFile] = useState<string>("");

  // Agent outputs
  const [agentFiles, setAgentFiles] = useState<string[]>([]);
  const [selectedAgentFile, setSelectedAgentFile] = useState<string>("");
  const [agentFileContent, setAgentFileContent] = useState<string>("");

  // View mode: "formatted" (pretty-rendered) or "raw" (plain text)
  const [viewMode, setViewMode] = useState<"formatted" | "raw">("formatted");

  // Load dates whenever tab changes
  useEffect(() => {
    const url = tab === "ai" ? "/api/ai-logs" : "/api/agent-outputs";
    fetch(url)
      .then((r) => r.json())
      .then((d: string[]) => {
        setDates(d);
        if (d.length > 0) setDate(d[0]);
      });
    // Reset selections
    setSelectedCall("");
    setCallFiles({});
    setActiveFile("");
    setSelectedAgentFile("");
    setAgentFileContent("");
  }, [tab]);

  // Load calls/files for selected date
  useEffect(() => {
    if (!date) return;
    if (tab === "ai") {
      fetch(`/api/ai-logs?date=${date}`)
        .then((r) => r.json())
        .then((d: CallEntry[]) => setCalls(d));
    } else {
      fetch(`/api/agent-outputs?date=${date}`)
        .then((r) => r.json())
        .then((d: string[]) => setAgentFiles(d));
    }
  }, [date, tab]);

  // Load files for a specific AI call
  useEffect(() => {
    if (tab !== "ai" || !date || !selectedCall) return;
    fetch(`/api/ai-logs?date=${date}&call=${encodeURIComponent(selectedCall)}`)
      .then((r) => r.json())
      .then((d: Record<string, string>) => {
        setCallFiles(d);
        // Auto-select metadata first, else first file
        const keys = Object.keys(d);
        if (keys.includes("metadata.json")) setActiveFile("metadata.json");
        else if (keys.length) setActiveFile(keys[0]);
      });
  }, [selectedCall, date, tab]);

  // Load agent file contents
  useEffect(() => {
    if (tab !== "agents" || !date || !selectedAgentFile) return;
    fetch(
      `/api/agent-outputs?date=${date}&file=${encodeURIComponent(
        selectedAgentFile
      )}`
    )
      .then(async (r) => {
        const ct = r.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          const j = await r.json();
          setAgentFileContent(JSON.stringify(j, null, 2));
        } else {
          setAgentFileContent(await r.text());
        }
      });
  }, [selectedAgentFile, date, tab]);

  const formatMeta = (m: CallEntry["metadata"]) => {
    if (!m) return "";
    const model = m.model || "?";
    const type = m.call_type || "?";
    const toks = m.tokens
      ? `${m.tokens.input ?? 0}+${m.tokens.output ?? 0}`
      : "";
    const cost = m.cost_usd?.total_cost_usd?.toFixed(4) ?? "-";
    const lat = m.latency_ms ? `${(m.latency_ms / 1000).toFixed(1)}s` : "";
    return `${model.replace("claude-", "")} · ${type} · ${toks} tok · $${cost} · ${lat}`;
  };

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "2rem 1rem" }}>
      <header style={{ marginBottom: "1.5rem" }}>
        <Link href="/" style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
          ← Back to dashboard
        </Link>
        <h1 style={{ fontSize: "1.8rem", fontWeight: 700, marginTop: "0.5rem" }}>
          Logs Browser
        </h1>
        <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
          Browse AI call prompts/responses and agent output files
        </p>
      </header>

      {/* Tab switcher */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <TabBtn active={tab === "ai"} onClick={() => setTab("ai")}>
          AI Calls
        </TabBtn>
        <TabBtn active={tab === "agents"} onClick={() => setTab("agents")}>
          Agent Outputs
        </TabBtn>
      </div>

      {/* Date selector */}
      <div style={{ marginBottom: "1rem" }}>
        <label style={{ fontSize: "0.85rem", color: "var(--muted)", marginRight: "0.5rem" }}>
          Date:
        </label>
        <select
          value={date}
          onChange={(e) => setDate(e.target.value)}
          style={{ padding: "0.3rem 0.5rem", fontSize: "0.9rem" }}
        >
          {dates.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>

      {tab === "ai" ? (
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "1rem" }}>
          {/* Call list */}
          <div style={{ border: "1px solid var(--border)", borderRadius: 6 }}>
            <div style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border)", fontWeight: 600, fontSize: "0.85rem" }}>
              AI Calls ({calls.length})
            </div>
            <div style={{ maxHeight: 600, overflow: "auto" }}>
              {calls.map((c) => (
                <div
                  key={c.dir}
                  onClick={() => setSelectedCall(c.dir)}
                  style={{
                    padding: "0.5rem 0.75rem",
                    borderBottom: "1px solid var(--border)",
                    cursor: "pointer",
                    background: selectedCall === c.dir ? "#f0ece0" : "transparent",
                    fontSize: "0.8rem",
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{c.dir}</div>
                  <div style={{ color: "var(--muted)", fontSize: "0.7rem" }}>
                    {formatMeta(c.metadata)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* File viewer */}
          <div style={{ border: "1px solid var(--border)", borderRadius: 6, minHeight: 600 }}>
            {selectedCall ? (
              <>
                <div
                  style={{
                    display: "flex",
                    borderBottom: "1px solid var(--border)",
                    justifyContent: "space-between",
                  }}
                >
                  <div style={{ display: "flex", flexWrap: "wrap" }}>
                    {Object.keys(callFiles).map((f) => (
                      <button
                        key={f}
                        onClick={() => setActiveFile(f)}
                        style={{
                          padding: "0.5rem 0.85rem",
                          background: activeFile === f ? "#f0ece0" : "transparent",
                          border: "none",
                          borderRight: "1px solid var(--border)",
                          cursor: "pointer",
                          fontSize: "0.8rem",
                          fontFamily: "inherit",
                        }}
                      >
                        {f}
                      </button>
                    ))}
                  </div>
                  <ViewToggle value={viewMode} onChange={setViewMode} />
                </div>
                {viewMode === "formatted" ? (
                  <FormattedView
                    filename={activeFile}
                    content={callFiles[activeFile] || ""}
                  />
                ) : (
                  <pre
                    style={{
                      padding: "1rem",
                      fontSize: "0.75rem",
                      fontFamily: "SF Mono, Cascadia Code, Fira Code, monospace",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      maxHeight: 560,
                      overflow: "auto",
                      margin: 0,
                    }}
                  >
                    {callFiles[activeFile] || ""}
                  </pre>
                )}
              </>
            ) : (
              <div style={{ padding: "2rem", color: "var(--muted)" }}>
                Select a call on the left to inspect its prompt, response, and metadata files.
              </div>
            )}
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: "1rem" }}>
          {/* Agent file list */}
          <div style={{ border: "1px solid var(--border)", borderRadius: 6 }}>
            <div style={{ padding: "0.5rem 0.75rem", borderBottom: "1px solid var(--border)", fontWeight: 600, fontSize: "0.85rem" }}>
              Agent Outputs ({agentFiles.length})
            </div>
            <div style={{ maxHeight: 600, overflow: "auto" }}>
              {agentFiles.map((f) => (
                <div
                  key={f}
                  onClick={() => setSelectedAgentFile(f)}
                  style={{
                    padding: "0.5rem 0.75rem",
                    borderBottom: "1px solid var(--border)",
                    cursor: "pointer",
                    background: selectedAgentFile === f ? "#f0ece0" : "transparent",
                    fontSize: "0.8rem",
                  }}
                >
                  {f}
                </div>
              ))}
            </div>
          </div>

          {/* File viewer */}
          <div style={{ border: "1px solid var(--border)", borderRadius: 6, minHeight: 600 }}>
            {selectedAgentFile ? (
              <>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "flex-end",
                    borderBottom: "1px solid var(--border)",
                    padding: "0.25rem 0.5rem",
                  }}
                >
                  <ViewToggle value={viewMode} onChange={setViewMode} />
                </div>
                {viewMode === "formatted" ? (
                  <FormattedView
                    filename={selectedAgentFile}
                    content={agentFileContent}
                  />
                ) : (
                  <pre
                    style={{
                      padding: "1rem",
                      fontSize: "0.75rem",
                      fontFamily: "SF Mono, Cascadia Code, Fira Code, monospace",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      maxHeight: 560,
                      overflow: "auto",
                      margin: 0,
                    }}
                  >
                    {agentFileContent}
                  </pre>
                )}
              </>
            ) : (
              <div style={{ padding: "2rem", color: "var(--muted)" }}>
                Select an output file on the left to view its contents.
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "0.5rem 1rem",
        fontSize: "0.85rem",
        fontFamily: "inherit",
        background: active ? "var(--foreground)" : "transparent",
        color: active ? "var(--background)" : "var(--foreground)",
        border: "1px solid var(--border)",
        borderRadius: 4,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function ViewToggle({
  value,
  onChange,
}: {
  value: "formatted" | "raw";
  onChange: (v: "formatted" | "raw") => void;
}) {
  const btn = (label: string, v: "formatted" | "raw") => (
    <button
      onClick={() => onChange(v)}
      style={{
        padding: "0.3rem 0.7rem",
        fontSize: "0.7rem",
        fontFamily: "inherit",
        background: value === v ? "var(--foreground)" : "transparent",
        color: value === v ? "var(--background)" : "var(--foreground)",
        border: "1px solid var(--border)",
        cursor: "pointer",
        textTransform: "uppercase",
        letterSpacing: "0.03em",
      }}
    >
      {label}
    </button>
  );
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.3rem", padding: "0.3rem" }}>
      {btn("Formatted", "formatted")}
      {btn("Raw", "raw")}
    </div>
  );
}
