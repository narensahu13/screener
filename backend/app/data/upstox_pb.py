"""Optional protobuf helpers for Upstox Market Data Feed V3.

Upstox publishes a MarketDataFeed V3 .proto. Generate stubs with:

    protoc --python_out=backend/app/data MarketDataFeedV3.proto

Until stubs exist, decode_feed returns an empty list and UpstoxSource
falls back to REST intraday polling for 1-minute candles.
"""

from __future__ import annotations

from typing import Any


def decode_feed(_message: bytes) -> list[dict[str, Any]]:
    return []
