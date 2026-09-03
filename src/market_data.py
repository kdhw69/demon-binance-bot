from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    KlineCandlestickDataIntervalEnum,
)

from .binance_client import create_client
from .config import SYMBOLS, TIMEFRAME

_CANDLE_LIMIT = 251
_CANDLE_CLOSE_TIME_INDEX = 6
_CANDLE_CLOSE_PRICE_INDEX = 4


@dataclass(frozen=True)
class Candle:
    close_time: datetime
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


def _get_closed_candles(client, symbol: str) -> List[Candle]:
    response = client.rest_api.kline_candlestick_data(
        symbol=symbol,
        interval=KlineCandlestickDataIntervalEnum.INTERVAL_4h,
        limit=_CANDLE_LIMIT,
    ).data()

    now = datetime.now(timezone.utc)
    candles = [
        Candle(
            close_time=datetime.fromtimestamp(
                int(raw_candle[_CANDLE_CLOSE_TIME_INDEX]) / 1000,
                tz=timezone.utc,
            ),
            high_price=Decimal(str(raw_candle[2])),
            low_price=Decimal(str(raw_candle[3])),
            close_price=Decimal(str(raw_candle[_CANDLE_CLOSE_PRICE_INDEX])),
        )
        for raw_candle in response
        if datetime.fromtimestamp(
            int(raw_candle[_CANDLE_CLOSE_TIME_INDEX]) / 1000,
            tz=timezone.utc,
        ) <= now
    ]

    if len(candles) < 250:
        raise ValueError("Insufficient closed market data returned.")
    if any(
        current.close_time >= following.close_time
        for current, following in zip(candles, candles[1:])
    ):
        raise ValueError("Market data is not ordered from oldest to newest.")

    return candles


def get_closed_candles_for_symbols() -> dict[str, List[Candle]]:
    if TIMEFRAME != "4h":
        raise ValueError("Configured timeframe is not supported.")
    client = create_client()
    return {
        symbol: _get_closed_candles(client, symbol)
        for symbol in SYMBOLS
    }
