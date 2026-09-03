import unittest
from datetime import datetime, timezone
from decimal import Decimal

from src.indicators import (
    calculate_atr_wilder,
    calculate_donchian_channels,
    calculate_ema,
)
from src.market_data import Candle


def candle(high: str, low: str, close: str) -> Candle:
    return Candle(
        close_time=datetime.now(timezone.utc),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


class IndicatorTests(unittest.TestCase):
    def test_ema_uses_sma_seed_and_decimal_smoothing(self):
        values = calculate_ema(
            [candle("2", "0", "1"), candle("3", "1", "2"), candle("4", "2", "3"), candle("5", "3", "4")],
            3,
        )
        self.assertEqual(values[1], None)
        self.assertEqual(values[2], Decimal("2"))
        self.assertEqual(values[3], Decimal("3"))

    def test_donchian_excludes_signal_candle(self):
        values = calculate_donchian_channels(
            [candle("10", "1", "5"), candle("12", "2", "6"), candle("11", "3", "7"), candle("20", "0", "15")],
            3,
        )
        self.assertEqual(values[2], (None, None))
        self.assertEqual(values[3], (Decimal("12"), Decimal("1")))

    def test_atr_uses_wilder_smoothing(self):
        values = calculate_atr_wilder(
            [
                candle("3", "1", "2"),
                candle("4", "2", "3"),
                candle("5", "3", "4"),
                candle("6", "3", "5"),
            ],
            3,
        )
        self.assertEqual(values[2], Decimal("2"))
        self.assertEqual(values[3], Decimal("7") / Decimal("3"))


if __name__ == "__main__":
    unittest.main()
