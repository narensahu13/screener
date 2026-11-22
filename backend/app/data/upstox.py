from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.data.candles import CandleAggregator, floor_to_minute
from app.data.source import MarketDataSource
from app.models import Candle, Tick

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class UpstoxSource(MarketDataSource):
    """Upstox REST + WebSocket V3 market data.

    Auth via env: UPSTOX_API_KEY, UPSTOX_API_SECRET, UPSTOX_ACCESS_TOKEN
    (Analytics Token recommended — 1-year, no daily login).

    WebSocket V3 uses protobuf binary frames. Decoding uses a lightweight
    JSON-fallback parser when protobuf stubs are unavailable; live LTPC
    fields are extracted best-effort from decoded feed payloads.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)
        self._client: httpx.AsyncClient | None = None
        self._ws_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._aggregator = CandleAggregator()
        self._history: dict[str, list[Candle]] = {}
        self._key_to_symbol: dict[str, str] = {}

    def _headers(self) -> dict[str, str]:
        token = self.settings.upstox_access_token
        if not token:
            raise RuntimeError("UPSTOX_ACCESS_TOKEN is not set")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Api-Version": "2.0",
        }

    async def connect(self) -> None:
        self.load_universe()
        for row in self._universe:
            if row.get("instrument_key"):
                self._key_to_symbol[row["instrument_key"]] = row["symbol"]
        self._client = httpx.AsyncClient(
            base_url=self.settings.upstox_rest_base,
            headers=self._headers(),
            timeout=30.0,
        )
        self.connected = True
        self._stop.clear()

    async def disconnect(self) -> None:
        self._stop.set()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        self.connected = False

    async def subscribe(self, symbols: list[str] | None = None) -> None:
        if self._ws_task and not self._ws_task.done():
            return
        self._ws_task = asyncio.create_task(self._run_websocket(symbols))

    async def load_history(self, days: int | None = None) -> dict[str, list[Candle]]:
        days = days or self.settings.history_lookback_days
        end = datetime.now(IST)
        start = end - timedelta(days=days + 3)
        history: dict[str, list[Candle]] = {}
        for sym in self.symbols:
            try:
                candles = await self.get_historical_candles(sym, start, end)
                history[sym] = candles
                self._aggregator.load_candles(candles)
            except Exception as exc:  # noqa: BLE001
                logger.warning("history load failed for %s: %s", sym, exc)
                history[sym] = []
            await asyncio.sleep(0.05)  # respect rate limits
        self._history = history
        return history

    def _instrument_key(self, symbol: str) -> str:
        for row in self._universe:
            if row["symbol"] == symbol:
                return row["instrument_key"]
        raise KeyError(f"Unknown symbol: {symbol}")

    async def get_intraday_candles(self, symbol: str) -> list[Candle]:
        assert self._client
        key = self._instrument_key(symbol)
        # V3 intraday 1-minute candles
        url = f"/v3/historical-candle/intraday/{key}/minutes/1"
        resp = await self._client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        return self._parse_candle_payload(symbol, payload)

    async def get_historical_candles(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[Candle]:
        assert self._client
        key = self._instrument_key(symbol)
        # Upstox allows ~1 month per request — chunk if needed
        candles: list[Candle] = []
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=28), end)
            to_date = chunk_end.strftime("%Y-%m-%d")
            from_date = cursor.strftime("%Y-%m-%d")
            url = f"/v3/historical-candle/{key}/minutes/1/{to_date}/{from_date}"
            resp = await self._client.get(url)
            resp.raise_for_status()
            candles.extend(self._parse_candle_payload(symbol, resp.json()))
            cursor = chunk_end + timedelta(days=1)
            await asyncio.sleep(0.05)
        return candles

    def _parse_candle_payload(self, symbol: str, payload: dict[str, Any]) -> list[Candle]:
        """Parse Upstox candle arrays: [ts, open, high, low, close, volume, oi]."""
        data = payload.get("data") or {}
        rows = data.get("candles") or []
        out: list[Candle] = []
        for row in rows:
            if len(row) < 6:
                continue
            ts_raw = row[0]
            if isinstance(ts_raw, str):
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone(IST)
            else:
                ts = datetime.fromtimestamp(ts_raw / 1000, tz=IST)
            out.append(
                Candle(
                    symbol=symbol,
                    ts=floor_to_minute(ts),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        out.sort(key=lambda c: c.ts)
        return out

    async def _run_websocket(self, symbols: list[str] | None) -> None:
        """Subscribe to Upstox Market Data Feed V3.

        Uses websockets library. Binary protobuf frames are decoded via a
        best-effort path; if protobuf decode fails, the connection stays up
        and REST intraday polling can still backfill candles each minute.
        """
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets package required for UpstoxSource") from exc

        keys = []
        wanted = set(symbols or self.symbols)
        for row in self._universe:
            if row["symbol"] in wanted and row.get("instrument_key"):
                keys.append(row["instrument_key"])

        url = self.settings.upstox_ws_url
        headers = {"Authorization": f"Bearer {self.settings.upstox_access_token}"}

        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    url, additional_headers=headers, max_size=10_000_000
                ) as ws:
                    sub = {
                        "guid": "screener-v1",
                        "method": "sub",
                        "data": {
                            "mode": "ltpc",
                            "instrumentKeys": keys,
                        },
                    }
                    await ws.send(json.dumps(sub).encode("utf-8"))
                    logger.info("Upstox WS subscribed to %d keys", len(keys))
                    # Parallel REST poller to ensure 1-min candles complete
                    poll = asyncio.create_task(self._poll_intraday(list(wanted)))
                    try:
                        async for message in ws:
                            if self._stop.is_set():
                                break
                            await self._handle_ws_message(message)
                    finally:
                        poll.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Upstox WS error: %s — reconnecting in 5s", exc)
                await asyncio.sleep(5)

    async def _handle_ws_message(self, message: bytes | str) -> None:
        # Prefer protobuf decode if available; otherwise ignore binary and rely on REST.
        if isinstance(message, str):
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                return
            await self._ingest_ltpc_dict(data)
            return

        try:
            from app.data import upstox_pb as pb  # optional generated stubs

            feed = pb.decode_feed(message)
            for item in feed:
                await self._ingest_ltpc_dict(item)
        except Exception:  # noqa: BLE001
            # Binary frame without stubs — REST poller handles candles.
            return

    async def _ingest_ltpc_dict(self, data: dict[str, Any]) -> None:
        key = data.get("instrument_key") or data.get("instrumentKey")
        ltp = data.get("ltp") or data.get("last_price")
        if key is None or ltp is None:
            feeds = data.get("feeds") or {}
            for k, v in feeds.items():
                ltpc = (v or {}).get("ltpc") or v or {}
                price = ltpc.get("ltp")
                if price is None:
                    continue
                sym = self._key_to_symbol.get(k)
                if not sym:
                    continue
                ts = datetime.now(IST)
                vol = float(ltpc.get("cp") or ltpc.get("v") or 0)
                tick = Tick(symbol=sym, ts=ts, ltp=float(price), volume=vol)
                await self._emit_tick(tick)
                completed = self._aggregator.on_tick(tick)
                if completed:
                    await self._emit_candle(completed)
            return

        sym = self._key_to_symbol.get(key)
        if not sym:
            return
        tick = Tick(
            symbol=sym,
            ts=datetime.now(IST),
            ltp=float(ltp),
            volume=float(data.get("volume") or data.get("v") or 0),
        )
        await self._emit_tick(tick)
        completed = self._aggregator.on_tick(tick)
        if completed:
            await self._emit_candle(completed)

    async def _poll_intraday(self, symbols: list[str]) -> None:
        """Every ~55s pull completed intraday bars so scans have fresh candles."""
        while not self._stop.is_set():
            for sym in symbols:
                if self._stop.is_set():
                    return
                try:
                    candles = await self.get_intraday_candles(sym)
                    existing = {c.ts for c in self._aggregator.get_candles(sym)}
                    for c in candles:
                        if c.ts not in existing:
                            self._aggregator.load_candles([c])
                            await self._emit_candle(c)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("intraday poll %s: %s", sym, exc)
                await asyncio.sleep(0.05)
            await asyncio.sleep(55)
