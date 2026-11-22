import type { Signal } from '../types'

function fmtTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' })
  } catch {
    return ts
  }
}

export function SignalTable({ signals }: { signals: Signal[] }) {
  if (!signals.length) {
    return <div className="empty">No signals yet — waiting for the next scan.</div>
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Side</th>
            <th>Trigger</th>
            <th>Range H</th>
            <th>Range L</th>
            <th>Vol ratio</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={`${s.symbol}-${s.time}`}>
              <td className="mono">{s.symbol}</td>
              <td>
                <span className={`side ${s.side.toLowerCase()}`}>{s.side}</span>
              </td>
              <td>{s.trigger_price.toFixed(2)}</td>
              <td>{s.range_high?.toFixed(2) ?? '—'}</td>
              <td>{s.range_low?.toFixed(2) ?? '—'}</td>
              <td>{s.volume_ratio?.toFixed(2) ?? '—'}</td>
              <td>{fmtTime(s.time)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
