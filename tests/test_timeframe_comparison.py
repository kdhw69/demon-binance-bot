import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.backtest_engine import FundingRate, HistoricalCandle, BacktestResult
from src.timeframe_comparison import aggregate_candles, funding_for_period, _metrics


START = datetime(2022, 1, 1, tzinfo=timezone.utc)


def candle(index, open_price, high, low, close, volume=None):
    opened = START + timedelta(hours=2 * index)
    return HistoricalCandle(
        opened,
        opened + timedelta(hours=2) - timedelta(milliseconds=1),
        Decimal(open_price), Decimal(high), Decimal(low), Decimal(close),
    )


class TimeframeComparisonTests(unittest.TestCase):
    def test_four_hour_aggregation(self):
        result = aggregate_candles([
            candle(0, "1", "3", "0.5", "2"), candle(1, "2", "4", "1", "3"),
            candle(2, "3", "5", "2", "4"), candle(3, "4", "6", "3", "5"),
        ], 4)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].open_price, Decimal("1"))
        self.assertEqual(result[0].high_price, Decimal("4"))
        self.assertEqual(result[0].low_price, Decimal("0.5"))
        self.assertEqual(result[0].close_price, Decimal("3"))
        self.assertEqual(result[0].open_time, START)

    def test_six_hour_aggregation_removes_incomplete_final_candle(self):
        result = aggregate_candles([candle(i, "1", "2", "0", "1") for i in range(4)], 6)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].close_price, Decimal("1"))

    def test_funding_alignment(self):
        funding = [
            FundingRate(START - timedelta(seconds=1), Decimal("1"), Decimal("1")),
            FundingRate(START + timedelta(hours=8), Decimal("2"), Decimal("2")),
        ]
        aligned = funding_for_period(funding, START, START + timedelta(hours=12))
        self.assertEqual(len(aligned), 1)
        self.assertEqual(aligned[0].funding_time, START + timedelta(hours=8))

    def test_portfolio_symbol_and_direction_totals_reconcile(self):
        trades = []
        result = BacktestResult(
            Decimal("5000"), Decimal("5000"), Decimal("0"), Decimal("0"), Decimal("0"),
            trades, [{"time_utc": START.isoformat(), "equity": "5000"}], [], [], Decimal("0"), Decimal("0"), Decimal("0"), {}, [],
        )
        metrics = _metrics(result, "2h", "development")
        self.assertEqual(sum(metrics.symbol_totals.values()), Decimal("0"))
        self.assertEqual(sum(metrics.direction_totals.values()), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
