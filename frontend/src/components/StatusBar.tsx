import type { FeedStatus } from '../types'

function fmt(ts: string | null | undefined) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' })
  } catch {
    return ts
  }
}

export function StatusBar({
  status,
  wsConnected,
  strategy,
}: {
  status: FeedStatus | null
  wsConnected: boolean
  strategy: string
}) {
  return (
    <div className="status-bar">
      <div>
        <span className="label">Feed</span>
        <span className={`pill ${status?.connected ? 'ok' : 'bad'}`}>
          {status?.source ?? '—'} {status?.connected ? 'live' : 'down'}
        </span>
      </div>
      <div>
        <span className="label">UI WS</span>
        <span className={`pill ${wsConnected ? 'ok' : 'bad'}`}>{wsConnected ? 'connected' : 'offline'}</span>
      </div>
      <div>
        <span className="label">Symbols</span>
        <span>{status?.symbols ?? 0}</span>
      </div>
      <div>
        <span className="label">Last candle</span>
        <span>{fmt(status?.last_candle_time)}</span>
      </div>
      <div>
        <span className="label">Next scan</span>
        <span>{fmt(status?.next_scan_time)}</span>
      </div>
      <div>
        <span className="label">Strategy</span>
        <span className="mono">{strategy}</span>
      </div>
    </div>
  )
}
