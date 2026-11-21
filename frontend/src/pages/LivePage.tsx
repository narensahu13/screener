import { StatusBar } from '../components/StatusBar'
import { SignalTable } from '../components/SignalTable'
import { StrategyForm } from '../components/StrategyForm'
import { useLiveFeed } from '../hooks/useLiveFeed'

export function LivePage() {
  const { status, signals, scannedAt, connected, strategy } = useLiveFeed()

  return (
    <div className="page">
      <header className="hero">
        <p className="brand">NSE Screener</p>
        <h1>Live scan</h1>
        <p className="lede">
          Opening-range and custom strategies on ~250 NSE cash names. Updates push over WebSocket.
        </p>
      </header>
      <StatusBar status={status} wsConnected={connected} strategy={strategy} />
      <div className="layout">
        <StrategyForm />
        <section className="panel grow">
          <div className="panel-head">
            <h2>Signals</h2>
            <span className="hint">{scannedAt ? `Last scan ${new Date(scannedAt).toLocaleString('en-IN')}` : '—'}</span>
          </div>
          <SignalTable signals={signals} />
        </section>
      </div>
    </div>
  )
}
