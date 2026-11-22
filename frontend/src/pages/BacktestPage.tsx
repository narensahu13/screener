import { useEffect, useState } from 'react'
import { fetchStrategies, runBacktest } from '../api'
import { EquityCurve } from '../components/EquityCurve'
import type { BacktestResult, StrategyInfo } from '../types'

export function BacktestPage() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [strategy, setStrategy] = useState('opening_range_breakout')
  const [paramsText, setParamsText] = useState('{"volume_lookback_days": 1, "volume_mult": 0.5}')
  const [start, setStart] = useState('2024-06-03')
  const [end, setEnd] = useState('2024-06-05')
  const [exitMode, setExitMode] = useState<'time' | 'target_stop'>('time')
  const [holdMinutes, setHoldMinutes] = useState(60)
  const [targetPct, setTargetPct] = useState(1)
  const [stopPct, setStopPct] = useState(0.5)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchStrategies()
      .then(setStrategies)
      .catch((e: Error) => setError(e.message))
  }, [])

  const onRun = async () => {
    setBusy(true)
    setError('')
    try {
      const params = JSON.parse(paramsText) as Record<string, unknown>
      const res = await runBacktest({
        strategy,
        params,
        start_date: start,
        end_date: end,
        exit_mode: exitMode,
        hold_minutes: holdMinutes,
        target_pct: targetPct,
        stop_pct: stopPct,
      })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <header className="hero compact">
        <p className="brand">NSE Screener</p>
        <h1>Backtest</h1>
        <p className="lede">Same Strategy class over historical 1-min candles. Fixture data ships for demo.</p>
      </header>

      <div className="layout">
        <div className="panel">
          <h2>Parameters</h2>
          <label>
            Strategy
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Start
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            End
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <label>
            Exit mode
            <select
              value={exitMode}
              onChange={(e) => setExitMode(e.target.value as 'time' | 'target_stop')}
            >
              <option value="time">Time</option>
              <option value="target_stop">Target / stop</option>
            </select>
          </label>
          {exitMode === 'time' ? (
            <label>
              Hold minutes
              <input
                type="number"
                value={holdMinutes}
                onChange={(e) => setHoldMinutes(Number(e.target.value))}
              />
            </label>
          ) : (
            <>
              <label>
                Target %
                <input
                  type="number"
                  step="0.1"
                  value={targetPct}
                  onChange={(e) => setTargetPct(Number(e.target.value))}
                />
              </label>
              <label>
                Stop %
                <input
                  type="number"
                  step="0.1"
                  value={stopPct}
                  onChange={(e) => setStopPct(Number(e.target.value))}
                />
              </label>
            </>
          )}
          <label>
            Strategy params
            <textarea rows={8} value={paramsText} onChange={(e) => setParamsText(e.target.value)} />
          </label>
          <button type="button" disabled={busy} onClick={onRun}>
            {busy ? 'Running…' : 'Run backtest'}
          </button>
          {error && <p className="error">{error}</p>}
        </div>

        <section className="panel grow">
          <h2>Results</h2>
          {!result && <div className="empty">Run a backtest to see trades and equity.</div>}
          {result && (
            <>
              <div className="stats">
                <div>
                  <span className="label">Trades</span>
                  <strong>{result.trade_count}</strong>
                </div>
                <div>
                  <span className="label">Hit rate</span>
                  <strong>{(result.hit_rate * 100).toFixed(1)}%</strong>
                </div>
                <div>
                  <span className="label">Total PnL</span>
                  <strong>{result.total_pnl_pct.toFixed(2)}%</strong>
                </div>
              </div>
              <EquityCurve points={result.equity_curve} />
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th>Entry</th>
                      <th>Exit</th>
                      <th>PnL %</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={`${t.symbol}-${t.entry_time}-${i}`}>
                        <td className="mono">{t.symbol}</td>
                        <td>
                          <span className={`side ${t.side.toLowerCase()}`}>{t.side}</span>
                        </td>
                        <td>{t.entry_price.toFixed(2)}</td>
                        <td>{t.exit_price.toFixed(2)}</td>
                        <td className={t.pnl_pct >= 0 ? 'up' : 'down'}>{t.pnl_pct.toFixed(2)}</td>
                        <td>{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
