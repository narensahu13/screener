"""Refresh data/universe.csv from NSE index lists + Upstox instruments master.

Pulls Nifty 200 and Nifty Midcap 150 constituents from NSE, joins ISINs to
Upstox complete.csv instrument keys (NSE_EQ|<ISIN>), and writes universe.csv.

Usage:
  py -3.12 scripts/refresh_universe.py
  py -3.12 scripts/refresh_universe.py --seed-only   # use bundled seed list
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "universe.csv"

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; screener/1.0)",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}

INDEX_URLS = {
    "NIFTY200": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20200",
    "NIFTYMIDCAP150": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20MIDCAP%20150",
}

UPSTOX_INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"


def fetch_nse_index(client: httpx.Client, index_key: str, url: str) -> list[dict[str, str]]:
    # Warm-up cookie jar
    client.get("https://www.nseindia.com", headers=NSE_HEADERS)
    resp = client.get(url, headers=NSE_HEADERS)
    resp.raise_for_status()
    data = resp.json()
    rows = []
    for item in data.get("data") or []:
        sym = (item.get("symbol") or "").strip()
        if not sym or sym.upper() in {"NIFTY 200", "NIFTY MIDCAP 150"}:
            continue
        meta = item.get("meta") or {}
        isin = (meta.get("isin") or item.get("isin") or "").strip()
        name = (meta.get("companyName") or item.get("meta", {}).get("companyName") or sym).strip()
        rows.append({"symbol": sym, "name": name, "isin": isin, "index": index_key})
    return rows


def fetch_upstox_isin_map(client: httpx.Client) -> dict[str, str]:
    """Map ISIN -> instrument_key for NSE EQ."""
    import gzip

    resp = client.get(UPSTOX_INSTRUMENTS, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()
    raw = resp.content
    if raw[:2] == b"\x1f\x8b":
        text = gzip.decompress(raw).decode("utf-8", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    mapping: dict[str, str] = {}
    for row in reader:
        exch = (row.get("exchange") or row.get("segment") or "").upper()
        itype = (row.get("instrument_type") or row.get("instrumenttype") or "").upper()
        isin = (row.get("isin") or "").strip()
        key = (row.get("instrument_key") or row.get("instrumentKey") or "").strip()
        if not isin or not key:
            continue
        if "NSE" in exch and ("EQ" in itype or "NSE_EQ" in key):
            mapping[isin] = key
    return mapping


def write_universe(rows: list[dict[str, str]]) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Deduplicate by symbol
    by_sym: dict[str, dict[str, str]] = {}
    for r in rows:
        sym = r["symbol"]
        if sym not in by_sym:
            by_sym[sym] = r
        else:
            if r["index"] not in by_sym[sym]["index"]:
                by_sym[sym]["index"] = f"{by_sym[sym]['index']}|{r['index']}"
    ordered = sorted(by_sym.values(), key=lambda x: x["symbol"])
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["symbol", "name", "isin", "instrument_key", "index"]
        )
        writer.writeheader()
        for r in ordered:
            isin = r.get("isin") or ""
            key = r.get("instrument_key") or (f"NSE_EQ|{isin}" if isin else "")
            writer.writerow(
                {
                    "symbol": r["symbol"],
                    "name": r.get("name") or r["symbol"],
                    "isin": isin,
                    "instrument_key": key,
                    "index": r.get("index") or "",
                }
            )
    return OUT


def refresh_live() -> Path:
    rows: list[dict[str, str]] = []
    with httpx.Client(timeout=60.0) as client:
        for key, url in INDEX_URLS.items():
            try:
                part = fetch_nse_index(client, key, url)
                print(f"{key}: {len(part)} symbols")
                rows.extend(part)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: failed fetching {key}: {exc}", file=sys.stderr)
        try:
            isin_map = fetch_upstox_isin_map(client)
            print(f"Upstox NSE EQ instruments: {len(isin_map)}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: Upstox instruments failed: {exc}", file=sys.stderr)
            isin_map = {}

    for r in rows:
        isin = r.get("isin") or ""
        if isin and isin in isin_map:
            r["instrument_key"] = isin_map[isin]
        elif isin:
            r["instrument_key"] = f"NSE_EQ|{isin}"
        else:
            r["instrument_key"] = ""

    path = write_universe(rows)
    print(f"Wrote {path}")
    return path


def refresh_seed() -> Path:
    from generate_universe_seed import main as seed_main

    seed_main()
    return OUT


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NSE universe CSV")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Write bundled seed list instead of live NSE/Upstox fetch",
    )
    args = parser.parse_args()
    if args.seed_only:
        refresh_seed()
    else:
        try:
            refresh_live()
        except Exception as exc:  # noqa: BLE001
            print(f"Live refresh failed ({exc}); falling back to seed", file=sys.stderr)
            refresh_seed()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
