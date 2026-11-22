from __future__ import annotations

import abc
import asyncio
import csv
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, Awaitable

from app.config import Settings, get_settings
from app.models import Candle, Tick


class MarketDataSource(abc.ABC):
    """Pluggable market data interface."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._universe: list[dict[str, str]] = []
        self._on_candle: Callable[[Candle], Awaitable[None] | None] | None = None
        self._on_tick: Callable[[Tick], Awaitable[None] | None] | None = None
        self.connected = False
        self.last_candle_time: datetime | None = None

    def load_universe(self, path: Path | None = None) -> list[dict[str, str]]:
        path = path or self.settings.universe_path
        rows: list[dict[str, str]] = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(
                    {
                        "symbol": row["symbol"].strip(),
                        "instrument_key": row.get("instrument_key", "").strip(),
                        "angel_token": row.get("angel_token", "").strip(),
                        "name": row.get("name", row["symbol"]).strip(),
                        "isin": row.get("isin", "").strip(),
                        "index": row.get("index", "").strip(),
                    }
                )
        self._universe = rows
        return rows

    @property
    def symbols(self) -> list[str]:
        return [r["symbol"] for r in self._universe]

    @property
    def instrument_keys(self) -> list[str]:
        return [r["instrument_key"] for r in self._universe if r.get("instrument_key")]

    def on_candle(self, callback: Callable[[Candle], Awaitable[None] | None]) -> None:
        self._on_candle = callback

    def on_tick(self, callback: Callable[[Tick], Awaitable[None] | None]) -> None:
        self._on_tick = callback

    async def _emit_candle(self, candle: Candle) -> None:
        self.last_candle_time = candle.ts
        if self._on_candle:
            result = self._on_candle(candle)
            if asyncio.iscoroutine(result):
                await result

    async def _emit_tick(self, tick: Tick) -> None:
        if self._on_tick:
            result = self._on_tick(tick)
            if asyncio.iscoroutine(result):
                await result

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...

    @abc.abstractmethod
    async def subscribe(self, symbols: list[str] | None = None) -> None: ...

    @abc.abstractmethod
    async def load_history(self, days: int | None = None) -> dict[str, list[Candle]]: ...

    @abc.abstractmethod
    async def get_intraday_candles(self, symbol: str) -> list[Candle]: ...

    @abc.abstractmethod
    async def get_historical_candles(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[Candle]: ...


def create_data_source(settings: Settings | None = None) -> MarketDataSource:
    settings = settings or get_settings()
    if settings.data_source == "angelone":
        from app.data.angelone import AngelOneSource

        return AngelOneSource(settings)
    if settings.data_source == "upstox":
        from app.data.upstox import UpstoxSource

        return UpstoxSource(settings)
    from app.data.mock import MockSource

    return MockSource(settings)
