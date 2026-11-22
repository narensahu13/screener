from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.models import BacktestResult, Candle, Side, Signal, TradeResult
from app.strategies.base import Strategy
from app.strategies.registry import get_strategy

IST = ZoneInfo("Asia/Kolkata")


class Backtester:
    """Run a Strategy over historical 1-min candles with simple exits."""

    def __init__(
        self,
        strategy: Strategy | str,
        params: dict[str, Any] | None = None,
        exit_mode: Literal["time", "target_stop"] = "time",
        hold_minutes: int = 60,
        target_pct: float = 1.0,
        stop_pct: float = 0.5,
    ) -> None:
        if isinstance(strategy, str):
            self.strategy = get_strategy(strategy, params)
        else:
            self.strategy = strategy
            if params:
                self.strategy.params.update(params)
        self.exit_mode = exit_mode
        self.hold_minutes = hold_minutes
        self.target_pct = target_pct
        self.stop_pct = stop_pct

    def run(
        self,
        data: dict[str, list[Candle]],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> BacktestResult:
        trades: list[TradeResult] = []
        signals_per_day: dict[str, int] = defaultdict(int)
        equity = 0.0
        equity_curve: list[dict[str, Any]] = [{"ts": None, "equity": 0.0}]

        for symbol, candles in data.items():
            if start or end:
                candles = [
                    c
                    for c in candles
                    if (start is None or c.ts >= start) and (end is None or c.ts <= end)
                ]
            if not candles:
                continue

            # Evaluate once per session day using candles available up to that day
            by_day: dict = defaultdict(list)
            for c in candles:
                by_day[c.ts.astimezone(IST).date()].append(c)

            cumulative: list[Candle] = []
            for day in sorted(by_day.keys()):
                cumulative.extend(by_day[day])
                signal = self.strategy.on_candle(symbol, cumulative)
                if signal is None:
                    continue
                if signal.time.astimezone(IST).date() != day:
                    continue
                signals_per_day[str(day)] += 1
                trade = self._simulate_trade(signal, by_day[day])
                if trade:
                    trades.append(trade)
                    equity += trade.pnl_pct
                    equity_curve.append(
                        {"ts": trade.exit_time.isoformat(), "equity": round(equity, 4)}
                    )

        wins = sum(1 for t in trades if t.pnl_pct > 0)
        hit_rate = (wins / len(trades)) if trades else 0.0
        start_s = start.date().isoformat() if start else ""
        end_s = end.date().isoformat() if end else ""
        if not start_s and trades:
            start_s = min(t.entry_time for t in trades).date().isoformat()
        if not end_s and trades:
            end_s = max(t.exit_time for t in trades).date().isoformat()

        return BacktestResult(
            strategy=self.strategy.name,
            params=dict(self.strategy.params),
            start_date=start_s,
            end_date=end_s,
            trades=trades,
            signals_per_day=dict(signals_per_day),
            hit_rate=round(hit_rate, 4),
            total_pnl_pct=round(equity, 4),
            equity_curve=equity_curve,
            trade_count=len(trades),
        )

    def _simulate_trade(self, signal: Signal, day_candles: list[Candle]) -> TradeResult | None:
        entry = signal.trigger_price
        entry_time = signal.time
        after = [c for c in day_candles if c.ts > entry_time]
        if not after:
            return None

        side = signal.side
        exit_price = after[-1].close
        exit_time = after[-1].ts
        reason = "eod"

        if self.exit_mode == "time":
            deadline = entry_time + timedelta(minutes=self.hold_minutes)
            for c in after:
                if c.ts >= deadline:
                    exit_price = c.close
                    exit_time = c.ts
                    reason = "time"
                    break
            else:
                exit_price = after[-1].close
                exit_time = after[-1].ts
                reason = "eod"
        else:
            target = entry * (1 + self.target_pct / 100) if side == Side.LONG else entry * (
                1 - self.target_pct / 100
            )
            stop = entry * (1 - self.stop_pct / 100) if side == Side.LONG else entry * (
                1 + self.stop_pct / 100
            )
            for c in after:
                if side == Side.LONG:
                    if c.low <= stop:
                        exit_price, exit_time, reason = stop, c.ts, "stop"
                        break
                    if c.high >= target:
                        exit_price, exit_time, reason = target, c.ts, "target"
                        break
                else:
                    if c.high >= stop:
                        exit_price, exit_time, reason = stop, c.ts, "stop"
                        break
                    if c.low <= target:
                        exit_price, exit_time, reason = target, c.ts, "target"
                        break

        if side == Side.LONG:
            pnl = (exit_price - entry) / entry * 100
        else:
            pnl = (entry - exit_price) / entry * 100

        return TradeResult(
            symbol=signal.symbol,
            side=side,
            entry_time=entry_time,
            entry_price=entry,
            exit_time=exit_time,
            exit_price=exit_price,
            pnl_pct=round(pnl, 4),
            reason=reason,
        )

    @staticmethod
    def export_csv(result: BacktestResult, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "symbol",
                    "side",
                    "entry_time",
                    "entry_price",
                    "exit_time",
                    "exit_price",
                    "pnl_pct",
                    "reason",
                ],
            )
            writer.writeheader()
            for t in result.trades:
                writer.writerow(
                    {
                        "symbol": t.symbol,
                        "side": t.side.value,
                        "entry_time": t.entry_time.isoformat(),
                        "entry_price": t.entry_price,
                        "exit_time": t.exit_time.isoformat(),
                        "exit_price": t.exit_price,
                        "pnl_pct": t.pnl_pct,
                        "reason": t.reason,
                    }
                )
        return path
