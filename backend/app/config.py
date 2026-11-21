from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_source: Literal["mock", "upstox"] = "mock"
    universe_path: Path = ROOT / "data" / "universe.csv"
    historical_data_dir: Path = ROOT / "data" / "historical"
    strategies_dir: Path = ROOT / "backend" / "app" / "strategies"

    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_access_token: str = ""
    upstox_ws_url: str = "wss://api.upstox.com/v3/feed/market-data-feed"
    upstox_rest_base: str = "https://api.upstox.com"

    scan_start_time: str = "09:17:05"
    scan_end_time: str = "15:30:00"
    timezone: str = "Asia/Kolkata"
    mock_speed: float = 60.0  # simulated seconds per real second
    mock_symbol_limit: int = 40  # keep mock startup fast; 0 = all
    history_lookback_days: int = 5

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
