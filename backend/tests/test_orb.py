from __future__ import annotations

from pathlib import Path

from app.backtest.loaders import load_candles_csv
from app.models import Side
from app.strategies.orb import OpeningRangeBreakout

FIXTURE = Path(__file__).parent / "fixtures" / "orb_sample.csv"


def test_orb_long_on_breakout():
    data = load_candles_csv(FIXTURE)
    strat = OpeningRangeBreakout({"volume_lookback_days": 1, "volume_mult": 1.0})
    candles = data["RELIANCE"]
    subset = [c for c in candles if c.ts.date().isoformat() <= "2024-06-04"]
    signal = strat.on_candle("RELIANCE", subset)
    assert signal is not None
    assert signal.side == Side.LONG
    assert signal.trigger_price == 2822.0
    assert signal.range_high == 2816.0
    assert signal.volume_ratio is not None
    assert signal.volume_ratio > 1.0


def test_orb_short_on_breakdown():
    data = load_candles_csv(FIXTURE)
    strat = OpeningRangeBreakout({"volume_lookback_days": 1, "volume_mult": 1.0})
    candles = data["RELIANCE"]
    signal = strat.on_candle("RELIANCE", candles)
    assert signal is not None
    assert signal.side == Side.SHORT
    assert signal.trigger_price == 2812.0


def test_orb_no_signal_without_volume():
    data = load_candles_csv(FIXTURE)
    strat = OpeningRangeBreakout({"volume_lookback_days": 1, "volume_mult": 100.0})
    candles = data["INFY"]
    signal = strat.on_candle("INFY", candles)
    assert signal is None
