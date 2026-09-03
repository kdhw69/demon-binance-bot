import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.backtest_engine import BacktestPosition, HistoricalCandle, PortfolioBacktest
from src.risk_guard import evaluate_guard
from src.signal_engine import Signal
from src.trade_store import TradeStore


START = datetime(2022, 1, 1, tzinfo=timezone.utc)


def candle(open_price="100", high="101", low="99", close="100"):
    return HistoricalCandle(START, START + timedelta(hours=2), Decimal(open_price), Decimal(high), Decimal(low), Decimal(close))


def signal():
    return Signal("BTCUSDT", START, "LONG", Decimal("100"), Decimal("90"), Decimal("95"), Decimal("85"), Decimal("2"))


class ConsecutiveLossCooldownTests(unittest.TestCase):
    def test_cooldown_starts_and_resets_count(self):
        engine = PortfolioBacktest({symbol: [candle()] for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}, {symbol: [] for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")})
        engine.consecutive_losses = 3
        position = BacktestPosition("BTCUSDT", "LONG", Decimal("1"), START, Decimal("100"), Decimal("100"), Decimal("90"), Decimal("110"), Decimal("10"), Decimal("10"))
        engine.positions["BTCUSDT"] = position
        engine._close(position, START, Decimal("90"), "STOP_LOSS")
        self.assertEqual(engine.consecutive_losses, 0)
        self.assertEqual(engine.consecutive_loss_cooldown_until, START + timedelta(hours=12))

    def test_live_cooldown_blocks_before_expiry_and_allows_at_expiry(self):
        until = START + timedelta(hours=12)
        common = dict(account_equity=Decimal("10000"), day_start_equity=Decimal("10000"), peak_equity=Decimal("10000"), daily_realized_pnl=Decimal("0"), consecutive_losses=0, halted=False, halt_reason=None, binance_position_symbols=set(), local_active_trades=[], total_used_margin=Decimal("0"), consecutive_loss_cooldown_until=until)
        blocked = evaluate_guard(now=until - timedelta(seconds=1), **common)
        allowed = evaluate_guard(now=until, **common)
        self.assertFalse(blocked.allowed)
        self.assertTrue(allowed.allowed)

    def test_cooldown_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trading.db"
            store = TradeStore(path)
            until = START + timedelta(hours=12)
            store.begin_consecutive_loss_cooldown(until)
            store.close()
            reopened = TradeStore(path)
            state = reopened.read_risk_state()
            self.assertEqual(state.consecutive_loss_cooldown_until, until)
            self.assertEqual(state.consecutive_losses, 0)
            reopened.close()

    def test_existing_position_is_managed_during_cooldown(self):
        engine = PortfolioBacktest({symbol: [candle()] for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}, {symbol: [] for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")})
        engine.consecutive_loss_cooldown_until = START + timedelta(hours=12)
        position = BacktestPosition("BTCUSDT", "LONG", Decimal("1"), START, Decimal("100"), Decimal("100"), Decimal("99"), Decimal("110"), Decimal("1"), Decimal("10"))
        engine.positions["BTCUSDT"] = position
        engine._manage("BTCUSDT", candle(open_price="100", high="101", low="98"))
        self.assertEqual(engine.trades[0].exit_reason, "STOP_LOSS")

    def test_permanent_halt_does_not_expire(self):
        decision = evaluate_guard(account_equity=Decimal("10000"), day_start_equity=Decimal("10000"), peak_equity=Decimal("10000"), daily_realized_pnl=Decimal("-500"), consecutive_losses=0, consecutive_loss_cooldown_until=None, halted=True, halt_reason="Manual review required.", binance_position_symbols=set(), local_active_trades=[], total_used_margin=Decimal("0"), now=START + timedelta(days=30))
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
