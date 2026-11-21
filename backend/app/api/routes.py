from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.backtest.engine import Backtester
from app.backtest.loaders import filter_date_range, load_candles_path
from app.models import BacktestRequest, BacktestResult, FeedStatus, ScanResult
from app.strategies.registry import get_strategy, list_strategies

IST = ZoneInfo("Asia/Kolkata")
router = APIRouter()


def _app_state(request: Request):
    return request.app.state


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status", response_model=FeedStatus)
async def status(request: Request) -> FeedStatus:
    scheduler = _app_state(request).scheduler
    return scheduler.status()


@router.get("/strategies")
async def strategies() -> list[dict[str, Any]]:
    return list_strategies()


@router.get("/universe")
async def universe(request: Request) -> list[dict[str, str]]:
    source = _app_state(request).source
    return source._universe


@router.get("/signals")
async def signals(request: Request) -> dict[str, Any]:
    scheduler = _app_state(request).scheduler
    last = scheduler.last_scan
    if last is None:
        return {"signals": [], "scanned_at": None, "strategy": scheduler.strategy_name}
    return last.model_dump(mode="json")


@router.post("/strategy")
async def set_strategy(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    name = body.get("name") or body.get("strategy")
    params = body.get("params") or {}
    if not name:
        raise HTTPException(400, "name is required")
    try:
        get_strategy(name, params)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    scheduler = _app_state(request).scheduler
    scheduler.set_strategy(name, params)
    return {"ok": True, "strategy": name, "params": params}


@router.post("/scan", response_model=ScanResult)
async def scan_now(request: Request) -> ScanResult:
    scheduler = _app_state(request).scheduler
    result = await scheduler.scan_once()
    # also push to websocket listeners
    await scheduler._publish(result)
    return result


@router.post("/backtest", response_model=BacktestResult)
async def backtest(request: Request, body: BacktestRequest) -> BacktestResult:
    settings = _app_state(request).settings
    data_path = Path(body.data_path) if body.data_path else settings.historical_data_dir
    fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "orb_sample.csv"

    if data_path.exists():
        data = load_candles_path(data_path)
    elif fixture.exists():
        data = load_candles_path(fixture)
    else:
        # Fall back to in-memory mock history already loaded
        scheduler = _app_state(request).scheduler
        data = dict(scheduler._candles)

    if body.symbols:
        data = {s: data[s] for s in body.symbols if s in data}

    start = datetime.fromisoformat(body.start_date).replace(tzinfo=IST)
    end = datetime.fromisoformat(body.end_date).replace(hour=23, minute=59, tzinfo=IST)
    data = filter_date_range(data, start, end)

    bt = Backtester(
        strategy=body.strategy,
        params=body.params,
        exit_mode=body.exit_mode,
        hold_minutes=body.hold_minutes,
        target_pct=body.target_pct,
        stop_pct=body.stop_pct,
    )
    return bt.run(data, start=start, end=end)


@router.post("/backtest/export")
async def backtest_export(request: Request, body: BacktestRequest) -> StreamingResponse:
    result = await backtest(request, body)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
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
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=backtest_trades.csv"},
    )
