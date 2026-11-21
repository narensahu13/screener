export type Side = 'LONG' | 'SHORT'

export interface Signal {
  symbol: string
  side: Side
  strategy: string
  trigger_price: number
  range_high: number | null
  range_low: number | null
  volume_ratio: number | null
  time: string
  meta?: Record<string, unknown>
}

export interface FeedStatus {
  source: string
  connected: boolean
  last_candle_time: string | null
  next_scan_time: string | null
  symbols: number
  message: string
}

export interface ScanPayload {
  signals: Signal[]
  scanned_at: string
  strategy: string
  params: Record<string, unknown>
}

export interface StrategyInfo {
  name: string
  defaults: Record<string, unknown>
}

export interface TradeResult {
  symbol: string
  side: Side
  entry_time: string
  entry_price: number
  exit_time: string
  exit_price: number
  pnl_pct: number
  reason: string
}

export interface BacktestResult {
  strategy: string
  params: Record<string, unknown>
  start_date: string
  end_date: string
  trades: TradeResult[]
  signals_per_day: Record<string, number>
  hit_rate: number
  total_pnl_pct: number
  equity_curve: { ts: string | null; equity: number }[]
  trade_count: number
}
