from .candles import CandleAggregator
from .source import MarketDataSource, create_data_source

__all__ = ["CandleAggregator", "MarketDataSource", "create_data_source"]


def _lazy_angelone():
    from .angelone import AngelOneSource, generate_totp, parse_ws_quote

    return AngelOneSource, generate_totp, parse_ws_quote
