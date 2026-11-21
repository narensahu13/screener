import type { BacktestResult, FeedStatus, ScanPayload, StrategyInfo } from './types'

const API = import.meta.env.VITE_API_BASE ?? ''

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json() as Promise<T>
}

export function fetchStatus() {
  return json<FeedStatus>('/api/status')
}

export function fetchStrategies() {
  return json<StrategyInfo[]>('/api/strategies')
}

export function fetchSignals() {
  return json<ScanPayload>('/api/signals')
}

export function setStrategy(name: string, params: Record<string, unknown>) {
  return json<{ ok: boolean }>('/api/strategy', {
    method: 'POST',
    body: JSON.stringify({ name, params }),
  })
}

export function runScan() {
  return json<ScanPayload>('/api/scan', { method: 'POST' })
}

export function runBacktest(body: Record<string, unknown>) {
  return json<BacktestResult>('/api/backtest', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function wsUrl(): string {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL as string
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = import.meta.env.DEV ? '127.0.0.1:8000' : window.location.host
  return `${proto}://${host}/ws`
}
