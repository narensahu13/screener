from __future__ import annotations

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Any, Type

from app.strategies.base import Strategy
from app.strategies.gap_and_go import GapAndGo
from app.strategies.orb import OpeningRangeBreakout

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[Strategy]] = {
    OpeningRangeBreakout.name: OpeningRangeBreakout,
    GapAndGo.name: GapAndGo,
}


def register(cls: Type[Strategy]) -> Type[Strategy]:
    _REGISTRY[cls.name] = cls
    return cls


def get_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy: {name}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name](params)


def list_strategies() -> list[dict[str, Any]]:
    out = []
    for name, cls in sorted(_REGISTRY.items()):
        out.append({"name": name, "defaults": dict(cls.default_params)})
    return out


def load_custom_strategies(directory: Path | None = None) -> int:
    """Import extra Strategy subclasses from *.py files in a folder.

    Drop a file like `my_strategy.py` with a Strategy subclass into
    backend/app/strategies/ (or STRATEGIES_DIR) and it will be registered.
    Bundled modules are skipped.
    """
    directory = directory or Path(__file__).resolve().parent
    bundled = {"base.py", "registry.py", "orb.py", "gap_and_go.py", "__init__.py"}
    loaded = 0
    for path in sorted(directory.glob("*.py")):
        if path.name in bundled:
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"custom_{path.stem}", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Strategy) and obj is not Strategy and obj.name not in _REGISTRY:
                    register(obj)
                    loaded += 1
                    logger.info("Loaded custom strategy %s from %s", obj.name, path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed loading %s: %s", path, exc)
    return loaded
