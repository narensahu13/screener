from __future__ import annotations

import abc
from typing import Any

from app.models import Candle, Signal


class Strategy(abc.ABC):
    """Base strategy: inspect candles for a symbol and optionally emit a Signal."""

    name: str = "base"
    default_params: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = {**self.default_params, **(params or {})}

    @abc.abstractmethod
    def on_candle(self, symbol: str, candles: list[Candle]) -> Signal | None:
        """Evaluate latest state. Return a Signal or None."""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "params": self.params,
            "defaults": self.default_params,
        }
