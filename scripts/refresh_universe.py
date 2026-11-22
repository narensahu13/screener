"""Refresh data/universe.csv from NSE index lists + broker instrument masters.

Joins constituents to:
  - Upstox `instrument_key` (NSE_EQ|<ISIN>)
  - Angel One `angel_token` (SmartAPI symboltoken from OpenAPIScripMaster)

Usage:
  py -3.12 scripts/refresh_universe.py
  py -3.12 scripts/refresh_universe.py --seed-only
  py -3.12 scripts/refresh_universe.py --enrich-angel   # fill angel_token on existing CSV
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
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
ANGEL_SCRIP_MASTER = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# Universe symbol -> Angel OpenAPIScripMaster `name` after corporate renames
ANGEL_NAME_ALIASES = {
    "GMRINFRA": "GMRAIRPORT",
    "HBLPOWER": "HBLENGINE",
    "KALPATPOWR": "KALPATARU",
    "ZOMATO": "ETERNAL",
    "TATAMOTORS": "TMPV",
    "NMDCSTEEL": "NSLNISP",
    "NATURALGAS": "GSPL",  # Gujarat State Petronet often listed as GSPL
}

FIELDNAMES = ["symbol", "name", "isin", "instrument_key", "angel_token", "index"]


def fetch_nse_index(client: httpx.Client, index_key: str, url: str) -> list[dict[str, str]]:
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
        name = (meta.get("companyName") or sym).strip()
        rows.append({"symbol": sym, "name": name, "isin": isin, "index": index_key})
    return rows


def fetch_upstox_isin_map(client: httpx.Client) -> dict[str, str]:
    resp = client.get(UPSTOX_INSTRUMENTS, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()
    raw = resp.content
    text = (
        gzip.decompress(raw).decode("utf-8", errors="replace")
        if raw[:2] == b"\x1f\x8b"
        else raw.decode("utf-8", errors="replace")
    )
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


def fetch_angel_symbol_token_map(client: httpx.Client) -> dict[str, str]:
    """Map NSE cash trading symbol (e.g. RELIANCE) -> Angel symboltoken."""
    resp = client.get(ANGEL_SCRIP_MASTER, follow_redirects=True, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, str):
        data = json.loads(data)
    mapping: dict[str, str] = {}
    for row in data:
        exch = (row.get("exch_seg") or "").upper()
        symbol = (row.get("symbol") or "").strip()
        name = (row.get("name") or "").strip().upper()
        token = str(row.get("token") or "").strip()
        if not token:
            continue
        if exch not in {"NSE", "NSE_CM"} and "NSE" not in exch:
            continue
        # Prefer -EQ cash scrips; fall back to name match
        if symbol.endswith("-EQ") and name:
            mapping[name] = token
        elif name and name not in mapping:
            mapping[name] = token
    return mapping


def write_universe(rows: list[dict[str, str]]) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    by_sym: dict[str, dict[str, str]] = {}
    for r in rows:
        sym = r["symbol"]
        if sym not in by_sym:
            by_sym[sym] = r
        else:
            if r.get("index") and r["index"] not in by_sym[sym].get("index", ""):
                by_sym[sym]["index"] = f"{by_sym[sym].get('index', '')}|{r['index']}".strip("|")
            for k in ("instrument_key", "angel_token", "isin", "name"):
                if r.get(k) and not by_sym[sym].get(k):
                    by_sym[sym][k] = r[k]
    ordered = sorted(by_sym.values(), key=lambda x: x["symbol"])
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
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
                    "angel_token": r.get("angel_token") or "",
                    "index": r.get("index") or "",
                }
            )
    return OUT


def read_existing() -> list[dict[str, str]]:
    if not OUT.exists():
        return []
    with OUT.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def lookup_angel_token(symbol: str, angel_map: dict[str, str]) -> str:
    sym = symbol.upper()
    if sym in angel_map:
        return angel_map[sym]
    alias = ANGEL_NAME_ALIASES.get(sym)
    if alias and alias in angel_map:
        return angel_map[alias]
    return ""


def enrich_angel_tokens() -> Path:
    rows = read_existing()
    if not rows:
        raise SystemExit("universe.csv missing — run seed or live refresh first")
    with httpx.Client(timeout=120.0) as client:
        angel_map = fetch_angel_symbol_token_map(client)
    hit = 0
    for r in rows:
        tok = lookup_angel_token(r["symbol"], angel_map)
        if tok:
            r["angel_token"] = tok
            hit += 1
    write_universe(rows)
    print(f"Filled angel_token for {hit}/{len(rows)} symbols → {OUT}")
    return OUT


def refresh_live() -> Path:
    rows: list[dict[str, str]] = []
    with httpx.Client(timeout=120.0) as client:
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
        try:
            angel_map = fetch_angel_symbol_token_map(client)
            print(f"Angel NSE EQ tokens: {len(angel_map)}")
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: Angel scrip master failed: {exc}", file=sys.stderr)
            angel_map = {}

    for r in rows:
        isin = r.get("isin") or ""
        if isin and isin in isin_map:
            r["instrument_key"] = isin_map[isin]
        elif isin:
            r["instrument_key"] = f"NSE_EQ|{isin}"
        else:
            r["instrument_key"] = ""
        r["angel_token"] = lookup_angel_token(r["symbol"], angel_map)

    path = write_universe(rows)
    print(f"Wrote {path}")
    return path


def refresh_seed() -> Path:
    from generate_universe_seed import main as seed_main

    seed_main()
    # Best-effort Angel token fill after seed
    try:
        enrich_angel_tokens()
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not enrich Angel tokens: {exc}", file=sys.stderr)
    return OUT


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NSE universe CSV")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument(
        "--enrich-angel",
        action="store_true",
        help="Only fill angel_token on the existing universe.csv",
    )
    args = parser.parse_args()
    if args.enrich_angel:
        enrich_angel_tokens()
    elif args.seed_only:
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
