from __future__ import annotations

from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

from app.data.candles import floor_to_minute, same_minute_average_volume
from app.models import Candle, Side, Signal
from app.strategies.base import Strategy

IST = ZoneInfo("Asia/Kolkata")


class OpeningRangeBreakout(Strategy):
    """Opening Range Breakout on 9:15 + 9:16 range.

    LONG  if 9:17 closes above range high with volume > N-day same-minute avg * mult
    SHORT if 9:17 closes below range low with the same volume filter
    """

    name = "opening_range_breakout"
    default_params: dict[str, Any] = {
        "range_start": "09:15",
        "range_end": "09:16",
        "trigger_minute": "09:17",
        "volume_lookback_days": 5,
        "volume_mult": 1.0,
        "allow_long": True,
        "allow_short": True,
    }

    def on_candle(self, symbol: str, candles: list[Candle]) -> Signal | None:
        if not candles:
            return None

        range_start = self._parse_hm(self.params["range_start"])
        range_end = self._parse_hm(self.params["range_end"])
        trigger_hm = self._parse_hm(self.params["trigger_minute"])
        lookback = int(self.params["volume_lookback_days"])
        vol_mult = float(self.params["volume_mult"])

        by_day: dict = {}
        for c in candles:
            ts = floor_to_minute(c.ts).astimezone(IST)
            by_day.setdefault(ts.date(), []).append(c)

        # Prefer evaluating the most recent session that has a trigger candle
        for day in sorted(by_day.keys(), reverse=True):
            day_candles = by_day[day]
            range_bars = [
                c
                for c in day_candles
                if range_start <= floor_to_minute(c.ts).astimezone(IST).time() <= range_end
            ]
            trigger = next(
                (
                    c
                    for c in day_candles
                    if floor_to_minute(c.ts).astimezone(IST).time() == trigger_hm
                ),
                None,
            )
            if len(range_bars) < 2 or trigger is None:
                continue

            range_high = max(c.high for c in range_bars)
            range_low = min(c.low for c in range_bars)
            avg_vol = same_minute_average_volume(candles, trigger.ts, lookback)
            vol_ok = avg_vol <= 0 or trigger.volume > avg_vol * vol_mult
            vol_ratio = (trigger.volume / avg_vol) if avg_vol > 0 else None

            side: Side | None = None
            if self.params.get("allow_long", True) and trigger.close > range_high and vol_ok:
                side = Side.LONG
            elif self.params.get("allow_short", True) and trigger.close < range_low and vol_ok:
                side = Side.SHORT

            if side is None:
                return None

            return Signal(
                symbol=symbol,
                side=side,
                strategy=self.name,
                trigger_price=trigger.close,
                range_high=range_high,
                range_low=range_low,
                volume_ratio=round(vol_ratio, 3) if vol_ratio is not None else None,
                time=trigger.ts,
                meta={
                    "trigger_volume": trigger.volume,
                    "avg_volume": avg_vol,
                    "volume_mult": vol_mult,
                },
            )
        return None

    @staticmethod
    def _parse_hm(value: str) -> time:
        h, m = value.split(":")
        return time(int(h), int(m))
