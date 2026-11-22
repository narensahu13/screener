from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings
from app.data.source import MarketDataSource
from app.models import Candle, FeedStatus, ScanResult, Signal
from app.strategies.base import Strategy
from app.strategies.registry import get_strategy

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


class ScanScheduler:
    """First scan at 09:17:05 IST, then every 1-min candle close until 15:30."""

    def __init__(
        self,
        source: MarketDataSource,
        settings: Settings | None = None,
        strategy_name: str = "opening_range_breakout",
        params: dict[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.settings = settings or get_settings()
        self.strategy_name = strategy_name
        self.params = params or {}
        self.strategy: Strategy = get_strategy(strategy_name, params)
        self._candles: dict[str, list[Candle]] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._listeners: list[Callable[[ScanResult], Awaitable[None] | None]] = []
        self.last_scan: ScanResult | None = None
        self.next_scan_time: datetime | None = None
        self.last_signals: list[Signal] = []

    def set_strategy(self, name: str, params: dict[str, Any] | None = None) -> None:
        self.strategy_name = name
        self.params = params or {}
        self.strategy = get_strategy(name, params)

    def add_listener(self, cb: Callable[[ScanResult], Awaitable[None] | None]) -> None:
        self._listeners.append(cb)

    async def on_candle(self, candle: Candle) -> None:
        self._candles.setdefault(candle.symbol, []).append(candle)

    def load_history(self, history: dict[str, list[Candle]]) -> None:
        for sym, candles in history.items():
            self._candles.setdefault(sym, []).extend(candles)

    def status(self) -> FeedStatus:
        return FeedStatus(
            source=self.settings.data_source,
            connected=self.source.connected,
            last_candle_time=self.source.last_candle_time,
            next_scan_time=self.next_scan_time,
            symbols=len(self.source.symbols),
            message="running" if self._task and not self._task.done() else "idle",
        )

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _parse_hms(self, value: str) -> tuple[int, int, int]:
        parts = [int(x) for x in value.split(":")]
        while len(parts) < 3:
            parts.append(0)
        return parts[0], parts[1], parts[2]

    def _next_scan_after(self, now: datetime) -> datetime:
        sh, sm, ss = self._parse_hms(self.settings.scan_start_time)
        eh, em, es = self._parse_hms(self.settings.scan_end_time)
        start = now.replace(hour=sh, minute=sm, second=ss, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=es, microsecond=0)

        if self.settings.data_source == "mock":
            # In mock mode, follow the accelerated clock if available
            mock_now = getattr(self.source, "now", None)
            if isinstance(mock_now, datetime):
                now = mock_now.astimezone(IST)

        if now.weekday() >= 5:
            days = 7 - now.weekday()
            day = (now + timedelta(days=days)).replace(
                hour=sh, minute=sm, second=ss, microsecond=0
            )
            return day

        if now < start:
            return start
        if now > end:
            nxt = now + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
            return nxt.replace(hour=sh, minute=sm, second=ss, microsecond=0)

        # Align to next minute + 5 seconds after a candle close
        # Candle for minute M closes at M+1:00; we scan at M+1:05
        base = now.replace(second=5, microsecond=0)
        if now.second >= 5:
            base = base + timedelta(minutes=1)
        if base < start:
            return start
        if base > end:
            nxt = now + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
            return nxt.replace(hour=sh, minute=sm, second=ss, microsecond=0)
        return base

    async def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(IST)
            if self.settings.data_source == "mock":
                mock_now = getattr(self.source, "now", None)
                if isinstance(mock_now, datetime):
                    now = mock_now.astimezone(IST)

            target = self._next_scan_after(now)
            self.next_scan_time = target
            delay = (target - now).total_seconds()

            if self.settings.data_source == "mock":
                # Sleep in wall-clock scaled by mock_speed
                speed = max(1.0, self.settings.mock_speed)
                delay = max(0.05, delay / speed)
            else:
                delay = max(0.2, delay)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass

            try:
                result = await self.scan_once()
                await self._publish(result)
            except Exception as exc:  # noqa: BLE001
                logger.exception("scan failed: %s", exc)

    async def scan_once(self) -> ScanResult:
        signals: list[Signal] = []
        for symbol, candles in self._candles.items():
            sig = self.strategy.on_candle(symbol, candles)
            if sig is not None:
                signals.append(sig)
        # Deduplicate by symbol keeping latest
        by_sym: dict[str, Signal] = {}
        for s in signals:
            by_sym[s.symbol] = s
        signals = sorted(by_sym.values(), key=lambda s: s.symbol)
        now = datetime.now(IST)
        if self.settings.data_source == "mock":
            mock_now = getattr(self.source, "now", None)
            if isinstance(mock_now, datetime):
                now = mock_now.astimezone(IST)
        result = ScanResult(
            signals=signals,
            scanned_at=now,
            strategy=self.strategy_name,
            params=dict(self.params),
        )
        self.last_scan = result
        self.last_signals = signals
        return result

    async def _publish(self, result: ScanResult) -> None:
        for cb in self._listeners:
            out = cb(result)
            if asyncio.iscoroutine(out):
                await out
