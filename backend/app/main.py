from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.websocket import broadcast_scan, broadcast_status, ws_router
from app.config import get_settings
from app.data.source import create_data_source
from app.scheduler.scanner import ScanScheduler
from app.strategies.registry import load_custom_strategies

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("screener")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    load_custom_strategies(settings.strategies_dir)

    source = create_data_source(settings)
    scheduler = ScanScheduler(source, settings)

    async def on_scan(result):
        await broadcast_scan(result)
        await broadcast_status(scheduler.status())

    scheduler.add_listener(on_scan)
    source.on_candle(scheduler.on_candle)

    app.state.settings = settings
    app.state.source = source
    app.state.scheduler = scheduler

    await source.connect()
    history = await source.load_history()
    scheduler.load_history(history)
    await source.subscribe()
    await scheduler.start()

    # periodic status push
    async def status_loop():
        while True:
            await broadcast_status(scheduler.status())
            await asyncio.sleep(5)

    status_task = asyncio.create_task(status_loop())
    logger.info(
        "Screener started source=%s symbols=%d",
        settings.data_source,
        len(source.symbols),
    )
    try:
        yield
    finally:
        status_task.cancel()
        await scheduler.stop()
        await source.disconnect()


app = FastAPI(title="NSE Screener", version="1.0.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(ws_router)


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=False)


if __name__ == "__main__":
    run()
