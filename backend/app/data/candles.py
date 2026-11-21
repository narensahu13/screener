from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from zoneinfo import ZoneInfo

from app.models import Candle, Tick

IST = ZoneInfo("Asia/Kolkata")


def floor_to_minute(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    else:
        ts = ts.astimezone(IST)
    return ts.replace(second=0, microsecond=0)


class CandleAggregator:
    """Build 1-minute OHLCV candles from ticks."""

    def __init__(self) -> None:
        self._open: dict[tuple[str, datetime], float] = {}
        self._high: dict[tuple[str, datetime], float] = {}
        self._low: dict[tuple[str, datetime], float] = {}
        self._close: dict[tuple[str, datetime], float] = {}
        self._volume: dict[tuple[str, datetime], float] = {}
        self._last_cum_vol: dict[str, float] = {}
        self._completed: dict[str, list[Candle]] = defaultdict(list)
        self._current_bucket: dict[str, datetime] = {}

    def on_tick(self, tick: Tick) -> Candle | None:
        """Ingest a tick. Returns a completed candle when the minute rolls."""
        bucket = floor_to_minute(tick.ts)
        key = (tick.symbol, bucket)
        prev_bucket = self._current_bucket.get(tick.symbol)

        completed: Candle | None = None
        if prev_bucket is not None and bucket > prev_bucket:
            completed = self._finalize(tick.symbol, prev_bucket)

        if key not in self._open:
            self._open[key] = tick.ltp
            self._high[key] = tick.ltp
            self._low[key] = tick.ltp
            self._close[key] = tick.ltp
            prev_cum = self._last_cum_vol.get(tick.symbol, tick.volume)
            delta = max(0.0, tick.volume - prev_cum) if tick.volume >= prev_cum else tick.volume
            self._volume[key] = delta
        else:
            self._high[key] = max(self._high[key], tick.ltp)
            self._low[key] = min(self._low[key], tick.ltp)
            self._close[key] = tick.ltp
            prev_cum = self._last_cum_vol.get(tick.symbol, tick.volume)
            delta = max(0.0, tick.volume - prev_cum) if tick.volume >= prev_cum else 0.0
            self._volume[key] = self._volume.get(key, 0.0) + delta

        self._last_cum_vol[tick.symbol] = tick.volume
        self._current_bucket[tick.symbol] = bucket
        return completed

    def _finalize(self, symbol: str, bucket: datetime) -> Candle | None:
        key = (symbol, bucket)
        if key not in self._open:
            return None
        candle = Candle(
            symbol=symbol,
            ts=bucket,
            open=self._open.pop(key),
            high=self._high.pop(key),
            low=self._low.pop(key),
            close=self._close.pop(key),
            volume=self._volume.pop(key, 0.0),
        )
        self._completed[symbol].append(candle)
        return candle

    def flush(self, symbol: str | None = None) -> list[Candle]:
        symbols = [symbol] if symbol else list(self._current_bucket.keys())
        out: list[Candle] = []
        for sym in symbols:
            bucket = self._current_bucket.get(sym)
            if bucket is not None:
                c = self._finalize(sym, bucket)
                if c:
                    out.append(c)
                self._current_bucket.pop(sym, None)
        return out

    def get_candles(self, symbol: str) -> list[Candle]:
        return list(self._completed.get(symbol, []))

    def load_candles(self, candles: Iterable[Candle]) -> None:
        for c in candles:
            self._completed[c.symbol].append(c)

    def all_symbols(self) -> list[str]:
        return sorted(self._completed.keys())


def merge_candles(*series: list[Candle]) -> list[Candle]:
    by_ts: dict[datetime, Candle] = {}
    for series_list in series:
        for c in series_list:
            by_ts[c.ts] = c
    return [by_ts[k] for k in sorted(by_ts)]


def same_minute_average_volume(
    candles: list[Candle],
    target_ts: datetime,
    lookback_days: int,
) -> float:
    """Average volume at the same clock minute over prior N sessions."""
    target = floor_to_minute(target_ts)
    hhmm = (target.hour, target.minute)
    volumes: list[float] = []
    seen_dates: set = set()
    for c in reversed(candles):
        cts = floor_to_minute(c.ts)
        if cts >= target:
            continue
        if (cts.hour, cts.minute) != hhmm:
            continue
        d = cts.date()
        if d in seen_dates:
            continue
        seen_dates.add(d)
        volumes.append(c.volume)
        if len(volumes) >= lookback_days:
            break
    if not volumes:
        return 0.0
    return sum(volumes) / len(volumes)


def filter_session(candles: list[Candle], session_date=None) -> list[Candle]:
    if session_date is None:
        return candles
    return [c for c in candles if floor_to_minute(c.ts).date() == session_date]
