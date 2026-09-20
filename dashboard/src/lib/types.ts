export interface Holding {
  symbol: string;
  exchange: string;
  quantity: number;
  avg_price: number;
}

export interface Position {
  symbol: string;
  exchange: string;
  quantity: number;
  entry_price: number;
  stop_loss: number;
  target: number;
  product: string;
  side: string;
}

export interface ActivePosition {
  symbol: string;
  exchange: string;
  product: string; // "CNC" | "MIS"
  side: string; // "BUY" | "SELL"
  quantity: number;
  entry_price: number;
  last_price: number;
  pnl: number;
  pnl_pct: number;
  days_held: number;
  stop_loss: number;
  target: number;
}

export interface ActivePositionsResponse {
  snapshot_timestamp: string | null;
  rows: ActivePosition[];
}

export interface Trade {
  id: number;
  timestamp: string;
  symbol: string;
  exchange: string;
  transaction_type: string;
  quantity: number;
  price: number;
  product: string;
  order_type: string;
  stop_loss: number | null;
  target: number | null;
  confidence: number | null;
  reasoning: string;
  status: string;
  fill_price: number | null;
  pnl: number | null;
}

export interface AgentRunRow {
  id: number;
  agent_name: string;
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
  duration_seconds: number | null;
  output_summary: string | null;
  status: string;
  error_message: string | null;
}

export interface LLMCall {
  call_id: string;
  timestamp: string;
  model: string;
  call_type: string;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number;
  latency_ms: number;
  status: string;
  watchlist_symbols: string | null;
  decisions_count: number | null;
}

export interface DailySummary {
  date: string;
  day_number: number;
  trades_count: number;
  wins: number;
  losses: number;
  total_pnl: number;
  cumulative_pnl: number;
  portfolio_value: number;
}

export interface SummaryStats {
  portfolio_value: number;
  cash: number;
  snapshot_timestamp: string | null;
  day_pnl: number;
  total_pnl: number;
  total_pnl_realized: number;
  total_pnl_unrealized: number;
  win_rate: number;
  ai_cost_today: number;
  ai_cost_total: number;
  holdings_count: number;
  positions_count: number;
  trades_today: number;
}
