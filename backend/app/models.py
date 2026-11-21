from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Candle(BaseModel):
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ts": self.ts.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class Tick(BaseModel):
    symbol: str
    ts: datetime
    ltp: float
    volume: float = 0.0


class Signal(BaseModel):
    symbol: str
    side: Side
    strategy: str
    trigger_price: float
    range_high: float | None = None
    range_low: float | None = None
    volume_ratio: float | None = None
    time: datetime
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "strategy": self.strategy,
            "trigger_price": self.trigger_price,
            "range_high": self.range_high,
            "range_low": self.range_low,
            "volume_ratio": self.volume_ratio,
            "time": self.time.isoformat(),
            "meta": self.meta,
        }


class FeedStatus(BaseModel):
    source: str
    connected: bool
    last_candle_time: datetime | None = None
    next_scan_time: datetime | None = None
    symbols: int = 0
    message: str = ""


class ScanResult(BaseModel):
    signals: list[Signal]
    scanned_at: datetime
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)


class BacktestRequest(BaseModel):
    strategy: str = "opening_range_breakout"
    params: dict[str, Any] = Field(default_factory=dict)
    start_date: str
    end_date: str
    symbols: list[str] | None = None
    exit_mode: Literal["time", "target_stop"] = "time"
    hold_minutes: int = 60
    target_pct: float = 1.0
    stop_pct: float = 0.5
    data_path: str | None = None


class TradeResult(BaseModel):
    symbol: str
    side: Side
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl_pct: float
    reason: str


class BacktestResult(BaseModel):
    strategy: str
    params: dict[str, Any]
    start_date: str
    end_date: str
    trades: list[TradeResult]
    signals_per_day: dict[str, int]
    hit_rate: float
    total_pnl_pct: float
    equity_curve: list[dict[str, Any]]
    trade_count: int
