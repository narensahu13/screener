from __future__ import annotations

import struct
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.data.angelone import AngelOneSource, generate_totp, parse_ws_quote
from app.data.source import create_data_source

IST = ZoneInfo("Asia/Kolkata")


def _quote_frame(token: str, ltp_paise: int, volume: int, ts_ms: int) -> bytes:
    buf = bytearray(75)
    buf[0] = 2  # QUOTE
    buf[1] = 1  # NSE_CM
    tok = token.encode("ascii")[:25]
    buf[2 : 2 + len(tok)] = tok
    struct.pack_into("<q", buf, 35, ts_ms)
    struct.pack_into("<q", buf, 43, ltp_paise)
    struct.pack_into("<q", buf, 67, volume)
    return bytes(buf)


def test_parse_ws_quote_ltp_and_volume():
    ts = int(datetime(2024, 6, 3, 9, 17, tzinfo=IST).timestamp() * 1000)
    frame = _quote_frame("2885", 250050, 123456, ts)
    parsed = parse_ws_quote(frame)
    assert parsed["token"] == "2885"
    assert parsed["ltp"] == pytest.approx(2500.50)
    assert parsed["volume"] == 123456.0
    assert parsed["subscription_mode"] == 2


def test_generate_totp_is_six_digits():
    code = generate_totp("JBSWY3DPEHPK3PXP")
    assert code.isdigit()
    assert len(code) == 6


def test_missing_creds_raises():
    settings = Settings(
        data_source="angelone",
        angel_api_key="",
        angel_client_code="",
        angel_password="",
        angel_totp_secret="",
    )
    source = AngelOneSource(settings)
    with pytest.raises(RuntimeError, match="credentials missing"):
        source._require_creds()


def test_create_data_source_angelone():
    settings = Settings(
        data_source="angelone",
        angel_api_key="k",
        angel_client_code="c",
        angel_password="p",
        angel_totp_secret="JBSWY3DPEHPK3PXP",
    )
    src = create_data_source(settings)
    assert isinstance(src, AngelOneSource)


@pytest.mark.asyncio
async def test_angelone_login_and_candles(httpx_mock):
    settings = Settings(
        data_source="angelone",
        angel_api_key="test-key",
        angel_client_code="A123",
        angel_password="1234",
        angel_totp_secret="JBSWY3DPEHPK3PXP",
    )
    source = AngelOneSource(settings)
    source._universe = [
        {
            "symbol": "RELIANCE",
            "angel_token": "2885",
            "instrument_key": "NSE_EQ|INE002A01018",
            "name": "Reliance",
            "isin": "INE002A01018",
            "index": "NIFTY200",
        }
    ]
    source._map_tokens()

    httpx_mock.add_response(
        method="POST",
        url="https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword",
        json={
            "status": True,
            "message": "SUCCESS",
            "data": {
                "jwtToken": "jwt-test",
                "refreshToken": "refresh-test",
                "feedToken": "feed-test",
            },
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData",
        json={
            "status": True,
            "message": "SUCCESS",
            "data": [
                ["2024-06-03T09:15:00+05:30", 100, 101, 99, 100.5, 1000],
                ["2024-06-03T09:16:00+05:30", 100.5, 102, 100, 101, 1100],
            ],
        },
    )

    import httpx

    source._client = httpx.AsyncClient(base_url=settings.angel_rest_base, timeout=10.0)
    await source._login()
    assert source._jwt == "jwt-test"
    assert source._feed_token == "feed-test"

    start = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
    end = datetime(2024, 6, 3, 9, 16, tzinfo=IST)
    candles = await source.get_historical_candles("RELIANCE", start, end)
    await source._client.aclose()

    assert len(candles) == 2
    assert candles[0].close == 100.5
    assert candles[1].volume == 1100
