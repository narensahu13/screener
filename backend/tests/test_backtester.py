from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.backtest.engine import Backtester
from app.backtest.loaders import load_candles_csv

IST = ZoneInfo("Asia/Kolkata")
FIXTURE = Path(__file__).parent / "fixtures" / "orb_sample.csv"


def test_backtester_produces_trades_and_equity():
    data = load_candles_csv(FIXTURE)
    bt = Backtester(
        strategy="opening_range_breakout",
        params={"volume_lookback_days": 1, "volume_mult": 0.5},
        exit_mode="time",
        hold_minutes=60,
    )
    start = datetime(2024, 6, 3, tzinfo=IST)
    end = datetime(2024, 6, 5, 23, 59, tzinfo=IST)
    result = bt.run(data, start=start, end=end)
    assert result.trade_count >= 1
    assert 0.0 <= result.hit_rate <= 1.0
    assert len(result.equity_curve) >= 2
    assert result.signals_per_day


def test_backtester_target_stop_exit():
    data = load_candles_csv(FIXTURE)
    bt = Backtester(
        strategy="opening_range_breakout",
        params={"volume_lookback_days": 1, "volume_mult": 0.5},
        exit_mode="target_stop",
        target_pct=0.2,
        stop_pct=0.2,
    )
    result = bt.run(data)
    assert result.trade_count >= 1
    assert all(t.reason in {"target", "stop", "eod", "time"} for t in result.trades)
