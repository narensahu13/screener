from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.data.candles import CandleAggregator, floor_to_minute, same_minute_average_volume
from app.models import Candle, Tick

IST = ZoneInfo("Asia/Kolkata")


def test_floor_to_minute():
    ts = datetime(2024, 6, 3, 9, 17, 45, tzinfo=IST)
    assert floor_to_minute(ts) == datetime(2024, 6, 3, 9, 17, 0, tzinfo=IST)


def test_aggregator_builds_ohlcv_across_minute_roll():
    agg = CandleAggregator()
    base = datetime(2024, 6, 3, 9, 15, 0, tzinfo=IST)
    ticks = [
        Tick(symbol="RELIANCE", ts=base + timedelta(seconds=5), ltp=100.0, volume=100),
        Tick(symbol="RELIANCE", ts=base + timedelta(seconds=20), ltp=102.0, volume=150),
        Tick(symbol="RELIANCE", ts=base + timedelta(seconds=40), ltp=101.0, volume=200),
        Tick(symbol="RELIANCE", ts=base + timedelta(minutes=1, seconds=1), ltp=103.0, volume=260),
    ]
    completed = None
    for t in ticks:
        result = agg.on_tick(t)
        if result:
            completed = result

    assert completed is not None
    assert completed.open == 100.0
    assert completed.high == 102.0
    assert completed.low == 100.0
    assert completed.close == 101.0
    assert completed.volume == 100.0


def test_same_minute_average_volume():
    candles = []
    for day in (1, 2, 3, 4, 5):
        ts = datetime(2024, 6, day, 9, 17, tzinfo=IST)
        candles.append(
            Candle(
                symbol="X",
                ts=ts,
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1000 * day,
            )
        )
    target = datetime(2024, 6, 6, 9, 17, tzinfo=IST)
    avg = same_minute_average_volume(candles, target, lookback_days=3)
    assert avg == 4000.0
