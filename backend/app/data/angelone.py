"""Angel One SmartAPI market data adapter.

Auth (daily, until midnight IST): loginByPassword with client code + PIN + TOTP.
Live ticks: SmartWebSocket V2 (`wss://smartapisocket.angelone.in/smart-stream`).
History: POST historical/v1/getCandleData (ONE_MINUTE, max 30 days/request).

Docs: https://smartapi.angelone.in/docs
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
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

LOGIN_PATH = "/rest/auth/angelbroking/user/v1/loginByPassword"
CANDLE_PATH = "/rest/secure/angelbroking/historical/v1/getCandleData"
LOGOUT_PATH = "/rest/secure/angelbroking/user/v1/logout"

# SmartWebSocket V2 binary layout (little-endian); prices in paise (÷100).
NSE_CM = 1
LTP_MODE = 1
QUOTE_MODE = 2


def generate_totp(secret: str) -> str:
    import pyotp

    return pyotp.TOTP(secret.replace(" ", "").strip()).now()


def parse_ws_quote(binary_data: bytes) -> dict[str, Any]:
    """Parse SmartWebSocket V2 LTP/QUOTE binary frame into a dict."""
    if len(binary_data) < 51:
        raise ValueError("frame too short")
    mode = binary_data[0]
    exchange_type = binary_data[1]
    token = _parse_token(binary_data[2:27])
    exchange_ts_ms = struct.unpack_from("<q", binary_data, 35)[0]
    ltp_raw = struct.unpack_from("<q", binary_data, 43)[0]
    out: dict[str, Any] = {
        "subscription_mode": mode,
        "exchange_type": exchange_type,
        "token": token,
        "exchange_timestamp": exchange_ts_ms,
        "ltp": ltp_raw / 100.0,
        "volume": 0.0,
    }
    if mode in (QUOTE_MODE, 3) and len(binary_data) >= 75:
        out["volume"] = float(struct.unpack_from("<q", binary_data, 67)[0])
    return out


def _parse_token(packet: bytes) -> str:
    chars: list[str] = []
    for b in packet:
        if b == 0:
            break
        chars.append(chr(b))
    return "".join(chars)


class AngelOneSource(MarketDataSource):
    """SmartAPI REST + WebSocket V2 feed for NSE cash symbols."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)
        self._client: httpx.AsyncClient | None = None
        self._ws_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._aggregator = CandleAggregator()
        self._history: dict[str, list[Candle]] = {}
        self._token_to_symbol: dict[str, str] = {}
        self._symbol_to_token: dict[str, str] = {}
        self._jwt: str = ""
        self._feed_token: str = ""
        self._refresh_token: str = ""

    def _require_creds(self) -> None:
        missing = [
            name
            for name, val in (
                ("ANGEL_API_KEY", self.settings.angel_api_key),
                ("ANGEL_CLIENT_CODE", self.settings.angel_client_code),
                ("ANGEL_PASSWORD", self.settings.angel_password),
                ("ANGEL_TOTP_SECRET", self.settings.angel_totp_secret),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Angel One credentials missing: " + ", ".join(missing)
            )

    def _base_headers(self, *, authed: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": self.settings.angel_mac_address or "00:00:00:00:00:01",
            "X-PrivateKey": self.settings.angel_api_key,
        }
        if authed and self._jwt:
            token = self._jwt if self._jwt.startswith("Bearer ") else f"Bearer {self._jwt}"
            headers["Authorization"] = token
        return headers

    async def connect(self) -> None:
        self._require_creds()
        self.load_universe()
        self._map_tokens()
        self._client = httpx.AsyncClient(
            base_url=self.settings.angel_rest_base.rstrip("/"),
            timeout=30.0,
        )
        await self._login()
        self.connected = True
        self._stop.clear()

    def _map_tokens(self) -> None:
        self._token_to_symbol.clear()
        self._symbol_to_token.clear()
        for row in self._universe:
            token = (row.get("angel_token") or "").strip()
            sym = row["symbol"]
            if token:
                self._token_to_symbol[token] = sym
                self._symbol_to_token[sym] = token

    async def _login(self) -> None:
        assert self._client
        totp = generate_totp(self.settings.angel_totp_secret)
        payload = {
            "clientcode": self.settings.angel_client_code,
            "password": self.settings.angel_password,
            "totp": totp,
        }
        resp = await self._client.post(
            LOGIN_PATH, headers=self._base_headers(authed=False), json=payload
        )
        resp.raise_for_status()
        body = resp.json()
        if not body.get("status"):
            raise RuntimeError(f"Angel One login failed: {body.get('message')}")
        data = body.get("data") or {}
        self._jwt = data.get("jwtToken") or ""
        self._feed_token = data.get("feedToken") or ""
        self._refresh_token = data.get("refreshToken") or ""
        if not self._jwt or not self._feed_token:
            raise RuntimeError("Angel One login missing jwtToken/feedToken")
        logger.info("Angel One login ok for client %s", self.settings.angel_client_code)

    async def disconnect(self) -> None:
        self._stop.set()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self._client and self._jwt:
            try:
                await self._client.post(
                    LOGOUT_PATH,
                    headers=self._base_headers(authed=True),
                    json={"clientcode": self.settings.angel_client_code},
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Angel logout: %s", exc)
        if self._client:
            await self._client.aclose()
            self._client = None
        self.connected = False

    async def subscribe(self, symbols: list[str] | None = None) -> None:
        if self._ws_task and not self._ws_task.done():
            return
        self._ws_task = asyncio.create_task(self._run_websocket(symbols))

    def _tokens_for(self, symbols: list[str] | None) -> list[str]:
        wanted = set(symbols or self.symbols)
        tokens = []
        for sym in wanted:
            tok = self._symbol_to_token.get(sym)
            if tok:
                tokens.append(tok)
            else:
                logger.warning("No angel_token for %s — skip subscribe", sym)
        return tokens

    async def load_history(self, days: int | None = None) -> dict[str, list[Candle]]:
        days = days or self.settings.history_lookback_days
        end = datetime.now(IST)
        start = end - timedelta(days=days + 2)
        history: dict[str, list[Candle]] = {}
        for sym in self.symbols:
            if sym not in self._symbol_to_token:
                history[sym] = []
                continue
            try:
                candles = await self.get_historical_candles(sym, start, end)
                history[sym] = candles
                self._aggregator.load_candles(candles)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Angel history %s: %s", sym, exc)
                history[sym] = []
            await asyncio.sleep(0.55)  # ~2 req/s candle limit
        self._history = history
        return history

    async def get_intraday_candles(self, symbol: str) -> list[Candle]:
        now = datetime.now(IST)
        start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        return await self.get_historical_candles(symbol, start, now)

    async def get_historical_candles(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[Candle]:
        token = self._symbol_to_token.get(symbol)
        if not token:
            raise KeyError(f"No angel_token for {symbol}")
        assert self._client
        candles: list[Candle] = []
        cursor = start.astimezone(IST)
        end = end.astimezone(IST)
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=30), end)
            payload = {
                "exchange": "NSE",
                "symboltoken": token,
                "interval": "ONE_MINUTE",
                "fromdate": cursor.strftime("%Y-%m-%d %H:%M"),
                "todate": chunk_end.strftime("%Y-%m-%d %H:%M"),
            }
            resp = await self._client.post(
                CANDLE_PATH, headers=self._base_headers(authed=True), json=payload
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("status"):
                raise RuntimeError(body.get("message") or "candle error")
            rows = body.get("data") or []
            candles.extend(self._parse_candle_rows(symbol, rows))
            cursor = chunk_end + timedelta(minutes=1)
            await asyncio.sleep(0.55)
        candles.sort(key=lambda c: c.ts)
        return candles

    def _parse_candle_rows(self, symbol: str, rows: list[Any]) -> list[Candle]:
        out: list[Candle] = []
        for row in rows:
            # [timestamp, open, high, low, close, volume]
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            ts_raw = row[0]
            if isinstance(ts_raw, str):
                cleaned = ts_raw.replace("Z", "+00:00")
                try:
                    ts = datetime.fromisoformat(cleaned)
                except ValueError:
                    ts = datetime.strptime(ts_raw[:16], "%Y-%m-%d %H:%M").replace(
                        tzinfo=IST
                    )
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=IST)
                else:
                    ts = ts.astimezone(IST)
            else:
                ts = datetime.fromtimestamp(float(ts_raw) / 1000.0, tz=IST)
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
        return out

    async def _run_websocket(self, symbols: list[str] | None) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets package required for AngelOneSource") from exc

        tokens = self._tokens_for(symbols)
        if not tokens:
            logger.error("Angel WS: no tokens to subscribe")
            return

        # Chunk to stay under connection limits (docs: up to 1000 tokens/session).
        chunks = [tokens[i : i + 900] for i in range(0, len(tokens), 900)]
        url = self.settings.angel_ws_url
        headers = {
            "Authorization": self._jwt if self._jwt.startswith("Bearer ") else self._jwt,
            "x-api-key": self.settings.angel_api_key,
            "x-client-code": self.settings.angel_client_code,
            "x-feed-token": self._feed_token,
        }

        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    url, additional_headers=headers, max_size=10_000_000, ping_interval=10
                ) as ws:
                    for idx, chunk in enumerate(chunks):
                        sub = {
                            "correlationID": f"screener{idx:02d}",
                            "action": 1,
                            "params": {
                                "mode": QUOTE_MODE,
                                "tokenList": [{"exchangeType": NSE_CM, "tokens": chunk}],
                            },
                        }
                        await ws.send(json.dumps(sub))
                    logger.info("Angel WS subscribed to %d tokens", len(tokens))
                    poll = asyncio.create_task(self._poll_intraday(list(symbols or self.symbols)))
                    try:
                        async for message in ws:
                            if self._stop.is_set():
                                break
                            if isinstance(message, str):
                                if message == "pong":
                                    continue
                                continue
                            await self._handle_binary(message)
                    finally:
                        poll.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("Angel WS error: %s — reconnect in 5s", exc)
                await asyncio.sleep(5)

    async def _handle_binary(self, message: bytes) -> None:
        try:
            parsed = parse_ws_quote(message)
        except Exception:  # noqa: BLE001
            return
        token = parsed.get("token") or ""
        sym = self._token_to_symbol.get(token)
        if not sym:
            return
        ts_ms = parsed.get("exchange_timestamp") or 0
        if ts_ms:
            ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=IST)
        else:
            ts = datetime.now(IST)
        tick = Tick(
            symbol=sym,
            ts=ts,
            ltp=float(parsed["ltp"]),
            volume=float(parsed.get("volume") or 0),
        )
        await self._emit_tick(tick)
        completed = self._aggregator.on_tick(tick)
        if completed:
            await self._emit_candle(completed)

    async def _poll_intraday(self, symbols: list[str]) -> None:
        while not self._stop.is_set():
            for sym in symbols:
                if self._stop.is_set():
                    return
                if sym not in self._symbol_to_token:
                    continue
                try:
                    candles = await self.get_intraday_candles(sym)
                    existing = {c.ts for c in self._aggregator.get_candles(sym)}
                    for c in candles:
                        if c.ts not in existing:
                            self._aggregator.load_candles([c])
                            await self._emit_candle(c)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Angel intraday poll %s: %s", sym, exc)
                await asyncio.sleep(0.55)
            await asyncio.sleep(55)
