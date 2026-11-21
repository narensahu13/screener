import { useEffect, useRef, useState } from 'react'
import { fetchSignals, fetchStatus, wsUrl } from '../api'
import type { FeedStatus, ScanPayload, Signal } from '../types'

export function useLiveFeed() {
  const [status, setStatus] = useState<FeedStatus | null>(null)
  const [signals, setSignals] = useState<Signal[]>([])
  const [scannedAt, setScannedAt] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const [strategy, setStrategyName] = useState('opening_range_breakout')
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [st, sig] = await Promise.all([fetchStatus(), fetchSignals()])
        if (cancelled) return
        setStatus(st)
        setSignals(sig.signals || [])
        setScannedAt(sig.scanned_at)
        if (sig.strategy) setStrategyName(sig.strategy)
      } catch {
        /* backend may still be starting */
      }
    })()

    const connect = () => {
      const ws = new WebSocket(wsUrl())
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!cancelled) setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as {
            type: string
            data: FeedStatus | ScanPayload
          }
          if (msg.type === 'status') setStatus(msg.data as FeedStatus)
          if (msg.type === 'scan') {
            const scan = msg.data as ScanPayload
            setSignals(scan.signals || [])
            setScannedAt(scan.scanned_at)
            setStrategyName(scan.strategy)
          }
        } catch {
          /* ignore */
        }
      }
    }
    connect()

    return () => {
      cancelled = true
      wsRef.current?.close()
    }
  }, [])

  return { status, signals, scannedAt, connected, strategy, setSignals, setScannedAt }
}
