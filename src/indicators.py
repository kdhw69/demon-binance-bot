from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from .market_data import Candle


def calculate_ema(
    candles: Sequence[Candle], period: int
) -> List[Optional[Decimal]]:
    if period <= 0:
        raise ValueError("Indicator period must be positive.")
    values: List[Optional[Decimal]] = [None] * len(candles)
    if len(candles) < period:
        return values

    seed = sum((candle.close_price for candle in candles[:period]), Decimal("0")) / period
    values[period - 1] = seed
    multiplier = Decimal("2") / Decimal(period + 1)
    for index in range(period, len(candles)):
        previous = values[index - 1]
        values[index] = (candles[index].close_price - previous) * multiplier + previous
    return values


def calculate_donchian_channels(
    candles: Sequence[Candle], period: int
) -> List[Tuple[Optional[Decimal], Optional[Decimal]]]:
    if period <= 0:
        raise ValueError("Indicator period must be positive.")
    channels: List[Tuple[Optional[Decimal], Optional[Decimal]]] = []
    for index in range(len(candles)):
        if index < period:
            channels.append((None, None))
            continue
        previous_candles = candles[index - period:index]
        channels.append(
            (
                max(candle.high_price for candle in previous_candles),
                min(candle.low_price for candle in previous_candles),
            )
        )
    return channels


def calculate_atr_wilder(
    candles: Sequence[Candle], period: int
) -> List[Optional[Decimal]]:
    if period <= 0:
        raise ValueError("Indicator period must be positive.")
    values: List[Optional[Decimal]] = [None] * len(candles)
    if len(candles) < period:
        return values

    true_ranges = []
    for index, candle in enumerate(candles):
        if index == 0:
            true_ranges.append(candle.high_price - candle.low_price)
            continue
        previous_close = candles[index - 1].close_price
        true_ranges.append(
            max(
                candle.high_price - candle.low_price,
                abs(candle.high_price - previous_close),
                abs(candle.low_price - previous_close),
            )
        )

    values[period - 1] = sum(true_ranges[:period], Decimal("0")) / period
    for index in range(period, len(candles)):
        previous = values[index - 1]
        values[index] = ((previous * (period - 1)) + true_ranges[index]) / period
    return values
