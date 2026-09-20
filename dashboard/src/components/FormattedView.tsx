"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Smart viewer for log files.
 * - *.json files -> pretty-printed JSON.
 * - response_raw.json specifically -> extract content[0].text and render
 *   the nested payload (usually JSON-in-a-markdown-fence).
 * - *.txt files with markdown-like content -> rendered as Markdown.
 * - Anything else -> plain <pre>.
 */
export default function FormattedView({
  filename,
  content,
}: {
  filename: string;
  content: string;
}) {
  // Try to parse JSON first; many files are JSON.
  const parsed = tryJson(content);

  // Special case: response_raw.json has the Anthropic API envelope.
  // The interesting payload is content[0].text.
  if (filename === "response_raw.json" && parsed) {
    const inner = extractAssistantText(parsed);
    if (inner) {
      return <RenderSmart text={inner} fallbackJson={parsed} />;
    }
    return <PrettyJson data={parsed} />;
  }

  // Any other JSON file -> pretty-printed JSON tree.
  if (filename.endsWith(".json") && parsed !== null) {
    return <PrettyJson data={parsed} />;
  }

  // Prompt/markdown files -> markdown render.
  if (filename.endsWith(".txt") || filename.endsWith(".md")) {
    return <MarkdownView text={content} />;
  }

  // Fallback.
  return <Raw text={content} />;
}

function RenderSmart({
  text,
  fallbackJson,
}: {
  text: string;
  fallbackJson?: unknown;
}) {
  // If the assistant text contains a ```json fence, extract and pretty-print.
  const jsonBlock = extractJsonBlock(text);
  if (jsonBlock !== null) {
    return (
      <div>
        <SectionLabel>Extracted JSON (from ```json code block)</SectionLabel>
        <PrettyJson data={jsonBlock} />
        {text && (
          <>
            <SectionLabel>Full assistant text</SectionLabel>
            <MarkdownView text={text} />
          </>
        )}
      </div>
    );
  }

  // Otherwise render as markdown (handles bold/lists/headings nicely).
  // Also keep fallback JSON viewer for completeness.
  return (
    <div>
      <SectionLabel>Assistant text</SectionLabel>
      <MarkdownView text={text} />
      {fallbackJson != null && (
        <>
          <SectionLabel>Full response envelope</SectionLabel>
          <PrettyJson data={fallbackJson} />
        </>
      )}
    </div>
  );
}

function tryJson(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function extractAssistantText(envelope: unknown): string | null {
  if (!envelope || typeof envelope !== "object") return null;
  const e = envelope as Record<string, unknown>;
  const content = e.content;

  // Anthropic API envelope — content is an array of {type, text} blocks
  if (Array.isArray(content)) {
    const texts = content
      .filter(
        (block) =>
          block &&
          typeof block === "object" &&
          (block as Record<string, unknown>).type === "text"
      )
      .map((block) => (block as Record<string, unknown>).text)
      .filter((t) => typeof t === "string");
    if (texts.length > 0) return (texts as string[]).join("\n\n");
  }

  // Our logger sometimes stores content as a raw string directly
  if (typeof content === "string") return content;

  // Some responses put the text under different keys
  if (typeof e.text === "string") return e.text;
  if (typeof e.output === "string") return e.output;

  return null;
}

function extractJsonBlock(text: string): unknown | null {
  if (!text) return null;
  // Find ```json ... ``` fence
  const fenceMatch = text.match(/```json\s*([\s\S]*?)\s*```/i);
  if (fenceMatch) {
    try {
      return JSON.parse(fenceMatch[1].trim());
    } catch {
      // fall through
    }
  }
  // Try any ``` fence
  const anyFence = text.match(/```\s*([\s\S]*?)\s*```/);
  if (anyFence) {
    try {
      return JSON.parse(anyFence[1].trim());
    } catch {
      // fall through
    }
  }
  // Try raw JSON (trimmed)
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return JSON.parse(trimmed);
    } catch {
      // fall through
    }
  }
  return null;
}

function PrettyJson({ data }: { data: unknown }) {
  const pretty = JSON.stringify(data, null, 2);
  return (
    <pre
      style={{
        margin: 0,
        padding: "1rem",
        fontSize: "0.75rem",
        fontFamily: "SF Mono, Cascadia Code, Fira Code, monospace",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        maxHeight: 600,
        overflow: "auto",
        background: "#faf8f2",
      }}
      dangerouslySetInnerHTML={{ __html: syntaxColorJson(pretty) }}
    />
  );
}

function syntaxColorJson(json: string): string {
  // Minimal inline syntax highlighting — no external dep.
  // Escape HTML first.
  const escaped = json
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped.replace(
    /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let color = "#1a1a1a";
      if (/^"/.test(match)) {
        color = /:$/.test(match) ? "#8a6d00" /* key */ : "#16a34a" /* string */;
      } else if (/true|false/.test(match)) {
        color = "#2563eb";
      } else if (/null/.test(match)) {
        color = "#8a8680";
      } else {
        color = "#dc2626"; // number
      }
      return `<span style="color:${color}">${match}</span>`;
    }
  );
}

function MarkdownView({ text }: { text: string }) {
  return (
    <div
      style={{
        padding: "1rem",
        fontSize: "0.85rem",
        fontFamily: "Georgia, serif",
        lineHeight: 1.55,
        maxHeight: 600,
        overflow: "auto",
      }}
      className="md-view"
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code: ({ className, children, ...props }) => {
            const isInline = !className;
            if (isInline) {
              return (
                <code
                  {...props}
                  style={{
                    background: "#f0ece0",
                    padding: "0.08rem 0.3rem",
                    borderRadius: 3,
                    fontFamily:
                      "SF Mono, Cascadia Code, Fira Code, monospace",
                    fontSize: "0.8em",
                  }}
                >
                  {children}
                </code>
              );
            }
            return (
              <pre
                style={{
                  background: "#f0ece0",
                  padding: "0.75rem",
                  borderRadius: 4,
                  overflow: "auto",
                  fontSize: "0.75rem",
                  fontFamily:
                    "SF Mono, Cascadia Code, Fira Code, monospace",
                }}
              >
                <code {...props}>{children}</code>
              </pre>
            );
          },
          h1: ({ children }) => (
            <h1 style={{ fontSize: "1.3rem", marginTop: "1rem" }}>{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 style={{ fontSize: "1.15rem", marginTop: "0.9rem" }}>
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 style={{ fontSize: "1rem", marginTop: "0.8rem" }}>{children}</h3>
          ),
          table: ({ children }) => (
            <table
              style={{
                borderCollapse: "collapse",
                width: "100%",
                margin: "0.5rem 0",
              }}
            >
              {children}
            </table>
          ),
          th: ({ children }) => (
            <th
              style={{
                borderBottom: "1px solid #c9c5bb",
                padding: "0.3rem 0.5rem",
                textAlign: "left",
                background: "#f0ece0",
              }}
            >
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td
              style={{
                borderBottom: "1px solid #e5e2da",
                padding: "0.3rem 0.5rem",
              }}
            >
              {children}
            </td>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function Raw({ text }: { text: string }) {
  return (
    <pre
      style={{
        margin: 0,
        padding: "1rem",
        fontSize: "0.75rem",
        fontFamily: "SF Mono, Cascadia Code, Fira Code, monospace",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        maxHeight: 600,
        overflow: "auto",
      }}
    >
      {text}
    </pre>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: "0.4rem 0.75rem",
        fontSize: "0.7rem",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        color: "#8a8680",
        background: "#f0ece0",
        borderBottom: "1px solid #e5e2da",
        borderTop: "1px solid #e5e2da",
      }}
    >
      {children}
    </div>
  );
}
