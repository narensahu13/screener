from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Allow `python -m app.backtest.cli` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.backtest.engine import Backtester
from app.backtest.loaders import filter_date_range, load_candles_path
from app.strategies.registry import list_strategies, load_custom_strategies

IST = ZoneInfo("Asia/Kolkata")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NSE screener backtester")
    p.add_argument("--strategy", default="opening_range_breakout")
    p.add_argument("--params", default="{}", help="JSON strategy params")
    p.add_argument("--data", required=True, help="CSV/Parquet file or directory")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--exit-mode", choices=["time", "target_stop"], default="time")
    p.add_argument("--hold-minutes", type=int, default=60)
    p.add_argument("--target-pct", type=float, default=1.0)
    p.add_argument("--stop-pct", type=float, default=0.5)
    p.add_argument("--export", default="", help="CSV path for trades")
    p.add_argument("--list-strategies", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_custom_strategies()
    if args.list_strategies:
        print(json.dumps(list_strategies(), indent=2))
        return 0

    params = json.loads(args.params)
    start = datetime.fromisoformat(args.start).replace(tzinfo=IST)
    end = datetime.fromisoformat(args.end).replace(hour=23, minute=59, tzinfo=IST)
    data = load_candles_path(Path(args.data))
    data = filter_date_range(data, start, end)

    bt = Backtester(
        strategy=args.strategy,
        params=params,
        exit_mode=args.exit_mode,
        hold_minutes=args.hold_minutes,
        target_pct=args.target_pct,
        stop_pct=args.stop_pct,
    )
    result = bt.run(data, start=start, end=end)
    summary = {
        "strategy": result.strategy,
        "trade_count": result.trade_count,
        "hit_rate": result.hit_rate,
        "total_pnl_pct": result.total_pnl_pct,
        "signals_per_day": result.signals_per_day,
    }
    print(json.dumps(summary, indent=2))
    if args.export:
        path = Backtester.export_csv(result, Path(args.export))
        print(f"exported {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
