import { useEffect, useState } from 'react'
import { fetchStrategies, runScan, setStrategy } from '../api'
import type { StrategyInfo } from '../types'

export function StrategyForm({ onApplied }: { onApplied?: (name: string) => void }) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [name, setName] = useState('opening_range_breakout')
  const [paramsText, setParamsText] = useState('{}')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchStrategies()
      .then((list) => {
        setStrategies(list)
        const first = list.find((s) => s.name === 'opening_range_breakout') || list[0]
        if (first) {
          setName(first.name)
          setParamsText(JSON.stringify(first.defaults, null, 2))
        }
      })
      .catch((e: Error) => setMsg(e.message))
  }, [])

  const onSelect = (n: string) => {
    setName(n)
    const found = strategies.find((s) => s.name === n)
    if (found) setParamsText(JSON.stringify(found.defaults, null, 2))
  }

  const apply = async () => {
    setBusy(true)
    setMsg('')
    try {
      const params = JSON.parse(paramsText) as Record<string, unknown>
      await setStrategy(name, params)
      onApplied?.(name)
      setMsg('Strategy applied')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const scanNow = async () => {
    setBusy(true)
    setMsg('')
    try {
      await runScan()
      setMsg('Scan triggered')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h2>Strategy</h2>
      <label>
        Selector
        <select value={name} onChange={(e) => onSelect(e.target.value)}>
          {strategies.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Params (JSON / YAML-compatible keys)
        <textarea value={paramsText} onChange={(e) => setParamsText(e.target.value)} rows={10} />
      </label>
      <div className="row">
        <button type="button" disabled={busy} onClick={apply}>
          Apply
        </button>
        <button type="button" className="ghost" disabled={busy} onClick={scanNow}>
          Scan now
        </button>
      </div>
      {msg && <p className="hint">{msg}</p>}
    </div>
  )
}
