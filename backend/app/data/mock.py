from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.data.candles import CandleAggregator, floor_to_minute
from app.data.source import MarketDataSource
from app.models import Candle, Tick

IST = ZoneInfo("Asia/Kolkata")


class MockSource(MarketDataSource):
    """Synthetic ticks + recorded 1-min candles with an accelerated clock."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._aggregator = CandleAggregator()
        self._history: dict[str, list[Candle]] = {}
        self._clock: datetime | None = None
        self._base_prices: dict[str, float] = {}
        self._rng = random.Random(42)

    @property
    def now(self) -> datetime:
        return self._clock or datetime.now(IST)

    async def connect(self) -> None:
        self.load_universe()
        limit = int(self.settings.mock_symbol_limit or 0)
        if limit > 0:
            self._universe = self._universe[:limit]
        for i, sym in enumerate(self.symbols):
            self._base_prices[sym] = 100.0 + (i % 50) * 17.5 + self._rng.random() * 5
        self.connected = True
        self._stop.clear()

    async def disconnect(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.connected = False

    async def subscribe(self, symbols: list[str] | None = None) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_feed(symbols or self.symbols))

    async def load_history(self, days: int | None = None) -> dict[str, list[Candle]]:
        days = days or self.settings.history_lookback_days
        today = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        history: dict[str, list[Candle]] = {}
        for sym in self.symbols:
            candles: list[Candle] = []
            price = self._base_prices.get(sym, 200.0)
            for d in range(days, 0, -1):
                day = today - timedelta(days=d)
                if day.weekday() >= 5:
                    continue
                session = self._session_candles(sym, day, price)
                candles.extend(session)
                if session:
                    price = session[-1].close
            history[sym] = candles
            self._aggregator.load_candles(candles)
        self._history = history
        return history

    def _session_candles(self, symbol: str, day: datetime, start_price: float) -> list[Candle]:
        candles: list[Candle] = []
        price = start_price
        # 9:15 to 15:29 inclusive → 375 minutes
        start = day.replace(hour=9, minute=15, second=0, microsecond=0, tzinfo=IST)
        for i in range(375):
            ts = start + timedelta(minutes=i)
            drift = math.sin(i / 18.0 + hash(symbol) % 7) * 0.15
            shock = self._rng.gauss(0, 0.25)
            open_p = price
            close_p = max(1.0, price * (1 + (drift + shock) / 100))
            high_p = max(open_p, close_p) * (1 + abs(self._rng.gauss(0, 0.05)) / 100)
            low_p = min(open_p, close_p) * (1 - abs(self._rng.gauss(0, 0.05)) / 100)
            vol = abs(self._rng.gauss(8000, 2500)) * (1.8 if i < 5 else 1.0)
            candles.append(
                Candle(
                    symbol=symbol,
                    ts=ts,
                    open=round(open_p, 2),
                    high=round(high_p, 2),
                    low=round(low_p, 2),
                    close=round(close_p, 2),
                    volume=round(vol, 0),
                )
            )
            price = close_p
        return candles

    async def get_intraday_candles(self, symbol: str) -> list[Candle]:
        today = self.now.date()
        return [c for c in self._aggregator.get_candles(symbol) if c.ts.date() == today]

    async def get_historical_candles(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[Candle]:
        return [
            c
            for c in self._history.get(symbol, self._aggregator.get_candles(symbol))
            if start <= c.ts <= end
        ]

    async def _run_feed(self, symbols: list[str]) -> None:
        """Accelerate through a trading session starting at 09:15."""
        speed = max(1.0, self.settings.mock_speed)
        # Align mock clock to 09:15 today (or next weekday)
        base = datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)
        if base.weekday() >= 5:
            base += timedelta(days=(7 - base.weekday()))
        self._clock = base
        prices = dict(self._base_prices)
        cum_vol = {s: 0.0 for s in symbols}
        minute_ticks = 12  # ticks per simulated minute

        while not self._stop.is_set():
            now = self._clock
            assert now is not None
            if (now.hour, now.minute) >= (15, 30):
                # Loop next day
                nxt = (now + timedelta(days=1)).replace(
                    hour=9, minute=15, second=0, microsecond=0
                )
                while nxt.weekday() >= 5:
                    nxt += timedelta(days=1)
                self._clock = nxt
                await asyncio.sleep(0.5)
                continue

            bucket = floor_to_minute(now)
            for t_i in range(minute_ticks):
                if self._stop.is_set():
                    return
                tick_ts = bucket + timedelta(seconds=t_i * (60 // minute_ticks))
                self._clock = tick_ts
                for sym in symbols:
                    shock = self._rng.gauss(0, 0.08)
                    prices[sym] = max(1.0, prices[sym] * (1 + shock / 100))
                    # Boost early volume so ORB can fire
                    boost = 2.5 if bucket.minute in (15, 16, 17) and bucket.hour == 9 else 1.0
                    delta = abs(self._rng.gauss(900, 300)) * boost
                    cum_vol[sym] += delta
                    tick = Tick(symbol=sym, ts=tick_ts, ltp=round(prices[sym], 2), volume=cum_vol[sym])
                    await self._emit_tick(tick)
                    completed = self._aggregator.on_tick(tick)
                    if completed:
                        await self._emit_candle(completed)
                await asyncio.sleep(1.0 / speed / minute_ticks)

            # advance to next minute boundary
            self._clock = bucket + timedelta(minutes=1)
