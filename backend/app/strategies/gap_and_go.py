"""Example custom strategy — drop-in file pattern.

Gap & Go: if the open gaps ≥ gap_pct% from prior close and the 09:17 bar
closes in the gap direction with rising volume, emit a signal.
"""

from __future__ import annotations

from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

from app.data.candles import floor_to_minute
from app.models import Candle, Side, Signal
from app.strategies.base import Strategy

IST = ZoneInfo("Asia/Kolkata")


class GapAndGo(Strategy):
    name = "gap_and_go"
    default_params: dict[str, Any] = {
        "gap_pct": 0.5,
        "trigger_minute": "09:17",
        "min_volume": 5000,
    }

    def on_candle(self, symbol: str, candles: list[Candle]) -> Signal | None:
        if len(candles) < 10:
            return None

        trigger_hm = self._parse_hm(self.params["trigger_minute"])
        gap_pct = float(self.params["gap_pct"])
        min_vol = float(self.params["min_volume"])

        # Group by session
        by_day: dict = {}
        for c in candles:
            ts = floor_to_minute(c.ts).astimezone(IST)
            by_day.setdefault(ts.date(), []).append(c)

        days = sorted(by_day.keys())
        if len(days) < 2:
            return None

        prev_day, today = days[-2], days[-1]
        prev_close = by_day[prev_day][-1].close
        today_bars = by_day[today]
        open_bar = next(
            (
                c
                for c in today_bars
                if floor_to_minute(c.ts).astimezone(IST).time() == time(9, 15)
            ),
            None,
        )
        trigger = next(
            (
                c
                for c in today_bars
                if floor_to_minute(c.ts).astimezone(IST).time() == trigger_hm
            ),
            None,
        )
        if open_bar is None or trigger is None or prev_close <= 0:
            return None
        if trigger.volume < min_vol:
            return None

        gap = (open_bar.open - prev_close) / prev_close * 100.0
        if gap >= gap_pct and trigger.close >= open_bar.open:
            side = Side.LONG
        elif gap <= -gap_pct and trigger.close <= open_bar.open:
            side = Side.SHORT
        else:
            return None

        return Signal(
            symbol=symbol,
            side=side,
            strategy=self.name,
            trigger_price=trigger.close,
            range_high=open_bar.high,
            range_low=open_bar.low,
            volume_ratio=None,
            time=trigger.ts,
            meta={"gap_pct": round(gap, 3), "prior_close": prev_close},
        )

    @staticmethod
    def _parse_hm(value: str) -> time:
        h, m = value.split(":")
        return time(int(h), int(m))
