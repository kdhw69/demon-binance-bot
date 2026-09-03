from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Sequence

from .config import ATR_PERIOD, DONCHIAN_CHANNEL_PERIOD, EMA_PERIOD, SYMBOLS
from .indicators import (
    calculate_atr_wilder,
    calculate_donchian_channels,
    calculate_ema,
)
from .market_data import Candle, get_closed_candles_for_symbols


@dataclass(frozen=True)
class Signal:
    symbol: str
    candle_close_time: object
    direction: str
    close_price: Decimal
    ema: Decimal
    donchian_high: Decimal
    donchian_low: Decimal
    atr: Decimal


def evaluate_signal(symbol: str, candles: Sequence[Candle]) -> Signal:
    minimum_candles = max(EMA_PERIOD, ATR_PERIOD, DONCHIAN_CHANNEL_PERIOD + 1)
    if len(candles) < minimum_candles:
        raise ValueError("Insufficient closed candles for signal evaluation.")

    ema_values = calculate_ema(candles, EMA_PERIOD)
    donchian_values = calculate_donchian_channels(candles, DONCHIAN_CHANNEL_PERIOD)
    atr_values = calculate_atr_wilder(candles, ATR_PERIOD)
    index = len(candles) - 1
    ema = ema_values[index]
    donchian_high, donchian_low = donchian_values[index]
    atr = atr_values[index]
    if ema is None or donchian_high is None or donchian_low is None or atr is None:
        raise ValueError("Signal indicators are unavailable.")

    close_price = candles[index].close_price
    if close_price > ema and close_price > donchian_high:
        direction = "LONG"
    elif close_price < ema and close_price < donchian_low:
        direction = "SHORT"
    else:
        direction = "NO_SIGNAL"

    return Signal(
        symbol=symbol,
        candle_close_time=candles[index].close_time,
        direction=direction,
        close_price=close_price,
        ema=ema,
        donchian_high=donchian_high,
        donchian_low=donchian_low,
        atr=atr,
    )


def get_latest_signals() -> Dict[str, Signal]:
    candles_by_symbol = get_closed_candles_for_symbols()
    return {
        symbol: evaluate_signal(symbol, candles_by_symbol[symbol])
        for symbol in SYMBOLS
    }
