# NSE Screener v1

Live Indian (NSE) stock screener: FastAPI backend + React/Vite UI, Opening Range Breakout strategy, mock or Upstox market data, and a shared-class backtester.

## Features

- Universe: Nifty 200 + Nifty Midcap 150 (~300 unique cash symbols) in `data/universe.csv` with Upstox `NSE_EQ|<ISIN>` keys
- Pluggable `MarketDataSource`: `MockSource` (no credentials) and `UpstoxSource` (REST + WebSocket V3)
- Strategies: `opening_range_breakout`, example `gap_and_go`; drop a custom `Strategy` subclass into `backend/app/strategies/`
- Scheduler: first scan at `09:17:05` IST, then every 1-min close until `15:30`; pushes results over WebSocket
- Backtester: CLI + `/api/backtest` with time or target/stop exits and CSV export
- Dark-theme UI: live signal table, strategy params, status bar, backtest + equity curve

## Quick start (mock mode)

```bash
# Python 3.11+
py -3.12 -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -r backend/requirements.txt

copy .env.example .env            # DATA_SOURCE=mock by default
$env:PYTHONPATH="backend"
uvicorn app.main:app --reload --app-dir backend --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — mock feed accelerates a synthetic session so ORB scans fire without Upstox credentials.

### Docker

```bash
docker compose up --build
```

- API: http://localhost:8000
- UI:  http://localhost:8080

## Upstox live mode

1. Open an Upstox account and create an API app ([developer docs](https://upstox.com/developer/api-documentation/)).
2. Generate an **Analytics Token** (read-only, ~1 year, no daily login / static IP for market data).
3. Set in `.env`:

```env
DATA_SOURCE=upstox
UPSTOX_API_KEY=...
UPSTOX_API_SECRET=...
UPSTOX_ACCESS_TOKEN=...
```

4. Restart the backend. It loads prior-day 1-min history via REST, subscribes to the V3 feed, and polls intraday candles so 9:17 bars are complete even if protobuf stubs are not generated yet.

Optional: place generated Market Data Feed V3 protobuf stubs so `app/data/upstox_pb.py` can decode binary frames. Until then, REST intraday polling fills 1-min OHLCV.

## Refresh universe

```bash
# Bundled seed (~Nifty 200 + Midcap 150)
py -3.12 scripts/refresh_universe.py --seed-only

# Live: NSE index APIs + Upstox instruments master
py -3.12 scripts/refresh_universe.py
```

## Strategies

ORB defaults (`backend/app/strategies/orb.py`):

- Range = 09:15 + 09:16 high/low
- LONG if 09:17 closes above range high with volume > N-day same-minute average × `volume_mult`
- SHORT if closes below range low with the same volume filter

Params are editable in the UI (JSON) or via `POST /api/strategy`.

Custom strategy: copy `gap_and_go.py`, subclass `Strategy`, set `name` / `default_params`, implement `on_candle`. Files in `backend/app/strategies/` auto-register on startup.

## Backtest

CLI (from repo root with `PYTHONPATH=backend`):

```bash
py -3.12 -m app.backtest.cli ^
  --strategy opening_range_breakout ^
  --params "{\"volume_lookback_days\":1,\"volume_mult\":0.5}" ^
  --data backend/tests/fixtures/orb_sample.csv ^
  --start 2024-06-03 --end 2024-06-05 ^
  --export data/historical/trades.csv
```

API: `POST /api/backtest` with `{ strategy, params, start_date, end_date, exit_mode, ... }`.

### Seeding historical 1-min data (Hugging Face)

Fastest bootstrap for multi-year history:

1. Browse [`xxparthparekhxx/indian-stock-market-minute-data`](https://huggingface.co/datasets/xxparthparekhxx/indian-stock-market-minute-data) (Parquet, ~2022→present, sourced from Upstox; author notes survivorship bias).
2. Download symbols you care about into `data/historical/` (CSV or Parquet with columns `symbol,ts,open,high,low,close,volume`).
3. Point the backtester / API `data_path` at that folder.

Keep the store current with nightly Upstox V3 historical pulls (`UpstoxSource.get_historical_candles`). Broker history is typically **unadjusted** for splits/bonuses.

## Tests

```bash
$env:PYTHONPATH="backend"
py -3.12 -m pytest backend/tests -q

cd frontend
npm run build
```

## Config

See `.env.example`. Never commit `.env` or tokens. `secret.txt` is gitignored.

## Project layout

```
backend/app/          FastAPI app, data sources, strategies, scheduler, backtest
frontend/             React + Vite + TypeScript UI
data/universe.csv     NSE cash universe + Upstox instrument keys
scripts/              universe refresh + seed generator
```

## What works in mock vs live Upstox

| Area | Mock | Live Upstox |
|------|------|-------------|
| Live scan UI + WS | Exercised | Wired; needs real token |
| ORB / gap_and_go | Covered by unit tests + mock feed | Same code path |
| Backtester + fixture | Tested | Uses same Strategy; needs historical files or REST |
| Tick→1m aggregation | Unit tested | Same aggregator; WS protobuf decode is stubbed — REST poller supplies candles |
| Universe refresh live NSE/Upstox | Seed path tested | Network fetch best-effort; falls back to seed |
