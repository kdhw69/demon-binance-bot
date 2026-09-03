import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.backtest_engine import (
    BacktestPosition,
    FundingRate,
    HistoricalCandle,
    PortfolioBacktest,
    SLIPPAGE_RATE,
    TAKER_FEE_RATE,
    _rules,
)
from src.signal_engine import Signal


START = datetime(2022, 1, 1, tzinfo=timezone.utc)


def candle(index, open_price="100", high="101", low="99", close="100"):
    opened = START + timedelta(hours=2 * index)
    return HistoricalCandle(opened, opened + timedelta(hours=2), Decimal(open_price), Decimal(high), Decimal(low), Decimal(close))


def signal(direction, atr="2"):
    return Signal("BTCUSDT", START, direction, Decimal("100"), Decimal("90"), Decimal("95"), Decimal("85"), Decimal(atr))


class BacktestEngineTests(unittest.TestCase):
    def engine(self, equity="5000"):
        candles = {symbol: [candle(i) for i in range(4)] for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
        funding = {symbol: [] for symbol in candles}
        return PortfolioBacktest(candles, funding, Decimal(equity))

    def test_no_lookahead_entry_uses_next_open(self):
        engine = self.engine()
        engine._entry("BTCUSDT", signal("LONG"), candle(1, open_price="110"))
        position = engine.positions["BTCUSDT"]
        self.assertEqual(position.raw_entry_price, Decimal("110"))
        self.assertEqual(position.entry_time, candle(1).open_time)

    def test_long_and_short_stop_target_prices(self):
        engine = self.engine()
        engine._entry("BTCUSDT", signal("LONG"), candle(1))
        long_position = engine.positions["BTCUSDT"]
        self.assertLess(long_position.stop_loss, long_position.entry_price)
        del engine.positions["BTCUSDT"]
        engine._entry("BTCUSDT", signal("SHORT"), candle(1))
        short_position = engine.positions["BTCUSDT"]
        self.assertGreater(short_position.stop_loss, short_position.entry_price)
        self.assertLess(short_position.take_profit, short_position.entry_price)

    def test_stop_wins_when_both_levels_touch(self):
        engine = self.engine()
        engine.positions["BTCUSDT"] = BacktestPosition("BTCUSDT", "LONG", Decimal("1"), candle(0).open_time, Decimal("100"), Decimal("100"), Decimal("99"), Decimal("101"), Decimal("1"), Decimal("10"))
        engine._manage("BTCUSDT", candle(1, open_price="100", high="102", low="98"))
        self.assertEqual(engine.trades[0].exit_reason, "STOP_LOSS")

    def test_gap_through_stop_uses_open(self):
        engine = self.engine()
        engine.positions["BTCUSDT"] = BacktestPosition("BTCUSDT", "LONG", Decimal("1"), candle(0).open_time, Decimal("100"), Decimal("100"), Decimal("99"), Decimal("101"), Decimal("1"), Decimal("10"))
        engine._manage("BTCUSDT", candle(1, open_price="95", high="96", low="94"))
        expected = Decimal("95") * (Decimal("1") - SLIPPAGE_RATE)
        self.assertEqual(engine.trades[0].exit_price, expected)

    def test_fees_slippage_and_funding_are_separate(self):
        engine = self.engine()
        engine.funding["BTCUSDT"] = [FundingRate(candle(0).open_time + timedelta(hours=1), Decimal("0.001"), Decimal("100"))]
        engine.positions["BTCUSDT"] = BacktestPosition("BTCUSDT", "LONG", Decimal("1"), candle(0).open_time, Decimal("100"), Decimal("100"), Decimal("90"), Decimal("110"), Decimal("10"), Decimal("10"))
        engine._close(engine.positions["BTCUSDT"], candle(1).close_time, Decimal("105"), "TAKE_PROFIT")
        trade = engine.trades[0]
        self.assertGreater(trade.fees, Decimal("0"))
        self.assertGreater(trade.slippage_cost, Decimal("0"))
        self.assertEqual(trade.funding_payment, Decimal("0.1"))
        self.assertEqual(trade.fees, (Decimal("100") + trade.exit_price) * TAKER_FEE_RATE)

    def test_position_and_margin_limits(self):
        engine = self.engine()
        engine.positions = {symbol: BacktestPosition(symbol, "LONG", Decimal("1"), START, Decimal("100"), Decimal("100"), Decimal("90"), Decimal("110"), Decimal("1"), Decimal("100")) for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
        engine._entry("BTCUSDT", signal("LONG"), candle(1))
        self.assertEqual(len(engine.positions), 3)

    def test_daily_consecutive_and_drawdown_halts(self):
        engine = self.engine()
        engine._check_limits(START)
        engine.daily_realized = Decimal("-250")
        engine._check_limits(START)
        self.assertFalse(engine.halted)
        self.assertEqual(engine.daily_loss_halt_until, START + timedelta(days=1))
        engine = self.engine()
        engine.consecutive_losses = 4
        engine._check_limits(START)
        self.assertFalse(engine.halted)
        engine = self.engine()
        engine.equity = Decimal("4250")
        engine._check_limits(START)
        self.assertTrue(engine.halted)

    def test_final_forced_close(self):
        engine = self.engine()
        engine.positions["BTCUSDT"] = BacktestPosition("BTCUSDT", "LONG", Decimal("1"), START, Decimal("100"), Decimal("100"), Decimal("90"), Decimal("110"), Decimal("10"), Decimal("10"))
        result = engine.run()
        self.assertEqual(result.trades[-1].exit_reason, "END_OF_TEST")


if __name__ == "__main__":
    unittest.main()
