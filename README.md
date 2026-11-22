# NSE Screener v1

Live Indian (NSE) stock screener: FastAPI backend + React/Vite UI, Opening Range Breakout strategy, pluggable market data (Angel One / Upstox / mock), and a shared-class backtester.

## Features

- Universe: Nifty 200 + Nifty Midcap 150 in `data/universe.csv` with **both** Upstox `instrument_key` (`NSE_EQ|<ISIN>`) and Angel One `angel_token` (SmartAPI symboltoken)
- Pluggable `MarketDataSource`:
  - **`AngelOneSource`** — recommended live path (SmartAPI login + WebSocket V2 + 1-min candles)
  - **`UpstoxSource`** — optional adapter (Analytics Token + REST/WS V3)
  - **`MockSource`** — synthetic accelerated session (no credentials)
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

Open http://localhost:5173 — mock feed accelerates a synthetic session so ORB scans fire without broker credentials.

### Docker

```bash
docker compose up --build
```

- API: http://localhost:8000
- UI:  http://localhost:8080

## Angel One live mode (recommended)

Angel One SmartAPI is the primary free live feed. **A registered static IP is required to create any SmartAPI app** (including market-data-only) — confirmed by Angel moderators. Host the backend on **Oracle Cloud Always Free** (Hyderabad/Mumbai) so the VM’s public IP can be registered.

### 1. Create a SmartAPI app

1. Open an Angel One demat/trading account.
2. Enable TOTP on the account (authenticator app) and save the **TOTP secret** (QR / “secret key” text).
3. Go to [smartapi.angelone.in](https://smartapi.angelone.in/) → **Create an app**.
4. Enter your Oracle VM **primary static public IP** (required field).
5. Copy the **API key**.

### 2. Configure `.env`

```env
DATA_SOURCE=angelone
ANGEL_API_KEY=...
ANGEL_CLIENT_CODE=...          # Angel client / user id
ANGEL_PASSWORD=...             # 4-digit trading PIN (not login password)
ANGEL_TOTP_SECRET=...          # Base32 secret from authenticator setup
```

### 3. Daily login / TOTP

SmartAPI sessions last until ~**midnight IST**. The backend logs in on startup with a fresh TOTP from `ANGEL_TOTP_SECRET` (via `pyotp`). Restart the process each trading morning (or add a cron that restarts before 09:15).

### 4. Oracle Always Free note

- Use an A1 Ampere VM in Hyderabad (or Mumbai if capacity allows) with a reserved public IP.
- Register that IP on the SmartAPI app form.
- Keep the VM reproducible (idle Always Free VMs can be reclaimed after prolonged low utilisation).

### 5. Run

```bash
$env:PYTHONPATH="backend"
uvicorn app.main:app --app-dir backend --port 8000
```

The adapter: logs in → loads prior-day 1-min history → subscribes to WebSocket V2 QUOTE mode for universe tokens → polls intraday candles so completed 1-min bars are available for the 09:17 scan.

**ToS:** Angel One does not allow redistributing the live feed to other users. Keep this screener private / personal.

## Upstox live mode (optional)

1. Create an Upstox API app and generate an **Analytics Token** (~1 year, no daily login; market data without static IP).
2. Set:

```env
DATA_SOURCE=upstox
UPSTOX_API_KEY=...
UPSTOX_API_SECRET=...
UPSTOX_ACCESS_TOKEN=...
```

## Refresh universe

```bash
# Bundled seed + best-effort Angel token fill
py -3.12 scripts/refresh_universe.py --seed-only

# Only fill / refresh angel_token from OpenAPIScripMaster
py -3.12 scripts/refresh_universe.py --enrich-angel

# Live: NSE index APIs + Upstox instruments + Angel scrip master
py -3.12 scripts/refresh_universe.py
```

CSV columns: `symbol,name,isin,instrument_key,angel_token,index`.

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

Keep current with Angel One `getCandleData` (ONE_MINUTE, 30 days/request) or Upstox V3 historical. Broker history is typically **unadjusted** for splits/bonuses.

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
data/universe.csv     NSE cash universe + Upstox + Angel keys
scripts/              universe refresh + seed generator
```

## Mock vs live

| Area | Mock | Angel One | Upstox |
|------|------|-----------|--------|
| Live scan UI + WS | Exercised | Wired; needs creds + static IP | Wired; needs Analytics Token |
| ORB / gap_and_go | Unit tests + mock feed | Same strategy path | Same |
| Backtester + fixture | Tested | Same Strategy; REST history | Same |
| Tick→1m aggregation | Unit tested | WS QUOTE + REST poller | Aggregator + REST poller (protobuf stubbed) |
| Daily auth | None | TOTP login each morning | Analytics Token (~1y) |
