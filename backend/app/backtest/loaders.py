from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from app.models import Candle

IST = ZoneInfo("Asia/Kolkata")

REQUIRED = {"symbol", "ts", "open", "high", "low", "close", "volume"}


def _normalize_frame(df: pd.DataFrame, default_symbol: str | None = None) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    aliases = {
        "symbol": ["symbol", "ticker", "tradingsymbol"],
        "ts": ["ts", "timestamp", "datetime", "date", "time"],
        "open": ["open", "o"],
        "high": ["high", "h"],
        "low": ["low", "l"],
        "close": ["close", "c", "ltp"],
        "volume": ["volume", "vol", "v"],
    }
    for target, names in aliases.items():
        for n in names:
            if n in cols:
                rename[cols[n]] = target
                break
    df = df.rename(columns=rename)
    if "symbol" not in df.columns:
        if default_symbol is None:
            raise ValueError("Candle data missing symbol column")
        df["symbol"] = default_symbol
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    df["ts"] = pd.to_datetime(df["ts"], utc=False)
    if df["ts"].dt.tz is None:
        df["ts"] = df["ts"].dt.tz_localize(IST)
    else:
        df["ts"] = df["ts"].dt.tz_convert(IST)
    return df


def frame_to_candles(df: pd.DataFrame) -> dict[str, list[Candle]]:
    out: dict[str, list[Candle]] = {}
    for symbol, group in df.groupby("symbol"):
        candles = [
            Candle(
                symbol=str(symbol),
                ts=row.ts.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in group.itertuples(index=False)
        ]
        candles.sort(key=lambda c: c.ts)
        out[str(symbol)] = candles
    return out


def load_candles_csv(path: Path, symbol: str | None = None) -> dict[str, list[Candle]]:
    df = pd.read_csv(path)
    df = _normalize_frame(df, default_symbol=symbol or path.stem)
    return frame_to_candles(df)


def load_candles_parquet(path: Path, symbol: str | None = None) -> dict[str, list[Candle]]:
    df = pd.read_parquet(path)
    df = _normalize_frame(df, default_symbol=symbol or path.stem)
    return frame_to_candles(df)


def load_candles_path(path: Path) -> dict[str, list[Candle]]:
    path = Path(path)
    if path.is_dir():
        merged: dict[str, list[Candle]] = {}
        for child in sorted(path.glob("**/*")):
            if child.suffix.lower() == ".csv":
                part = load_candles_csv(child)
            elif child.suffix.lower() in {".parquet", ".pq"}:
                part = load_candles_parquet(child)
            else:
                continue
            for sym, candles in part.items():
                merged.setdefault(sym, []).extend(candles)
        for sym in merged:
            merged[sym].sort(key=lambda c: c.ts)
        return merged
    if path.suffix.lower() == ".csv":
        return load_candles_csv(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        return load_candles_parquet(path)
    raise ValueError(f"Unsupported data path: {path}")


def filter_date_range(
    data: dict[str, list[Candle]], start: datetime, end: datetime
) -> dict[str, list[Candle]]:
    out: dict[str, list[Candle]] = {}
    for sym, candles in data.items():
        filtered = [c for c in candles if start <= c.ts <= end]
        if filtered:
            out[sym] = filtered
    return out
