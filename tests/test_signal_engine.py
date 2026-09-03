import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.market_data import Candle
from src.signal_engine import evaluate_signal


def candles_with_latest(close: str, high: str, low: str):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            close_time=start + timedelta(hours=2 * index),
            high_price=Decimal("11"),
            low_price=Decimal("9"),
            close_price=Decimal("10"),
        )
        for index in range(200)
    ]
    candles.append(
        Candle(
            close_time=start + timedelta(hours=400),
            high_price=Decimal(high),
            low_price=Decimal(low),
            close_price=Decimal(close),
        )
    )
    return candles


class SignalTests(unittest.TestCase):
    def test_long_signal_requires_close_above_ema_and_previous_high(self):
        signal = evaluate_signal("BTCUSDT", candles_with_latest("12", "13", "11"))
        self.assertEqual(signal.direction, "LONG")

    def test_short_signal_requires_close_below_ema_and_previous_low(self):
        signal = evaluate_signal("ETHUSDT", candles_with_latest("8", "9", "7"))
        self.assertEqual(signal.direction, "SHORT")

    def test_no_signal_when_breakout_condition_is_not_met(self):
        signal = evaluate_signal("SOLUSDT", candles_with_latest("10", "11", "9"))
        self.assertEqual(signal.direction, "NO_SIGNAL")


if __name__ == "__main__":
    unittest.main()
