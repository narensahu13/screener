export function EquityCurve({
  points,
}: {
  points: { ts: string | null; equity: number }[]
}) {
  if (!points.length) return <div className="empty">No equity data</div>
  const vals = points.map((p) => p.equity)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  const w = 640
  const h = 180
  const pad = 12
  const coords = points.map((p, i) => {
    const x = pad + (i / Math.max(points.length - 1, 1)) * (w - pad * 2)
    const y = h - pad - ((p.equity - min) / span) * (h - pad * 2)
    return `${x},${y}`
  })
  const polyline = coords.join(' ')
  return (
    <svg className="equity" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Equity curve">
      <polyline fill="none" stroke="var(--accent)" strokeWidth="2" points={polyline} />
      <text x={pad} y={16} fill="var(--muted)" fontSize="11">
        {max.toFixed(2)}%
      </text>
      <text x={pad} y={h - 4} fill="var(--muted)" fontSize="11">
        {min.toFixed(2)}%
      </text>
    </svg>
  )
}
