import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.backtest_engine import BacktestPosition, HistoricalCandle, PortfolioBacktest
from src.risk_guard import evaluate_guard
from src.signal_engine import Signal
from src.trade_store import TradeStore


CURRENT_UTC_DATE = datetime.now(timezone.utc).date()
MIDNIGHT = datetime.combine(
    CURRENT_UTC_DATE,
    datetime.min.time(),
    tzinfo=timezone.utc,
)
START = MIDNIGHT - timedelta(minutes=1)


def base_guard(**changes):
    values = dict(
        account_equity=Decimal("10000"), day_start_equity=Decimal("10000"),
        peak_equity=Decimal("10000"), daily_realized_pnl=Decimal("-500"),
        consecutive_losses=0, consecutive_loss_cooldown_until=None,
        daily_loss_halt_until=MIDNIGHT, halted=False, halt_reason=None,
        binance_position_symbols=set(), local_active_trades=[],
        total_used_margin=Decimal("0"),
    )
    values.update(changes)
    return evaluate_guard(**values)


class DailyLossHaltTests(unittest.TestCase):
    def test_blocked_immediately_before_midnight(self):
        self.assertFalse(base_guard(now=MIDNIGHT - timedelta(microseconds=1)).allowed)

    def test_allowed_at_midnight(self):
        self.assertTrue(base_guard(now=MIDNIGHT).allowed)

    def test_store_reset_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trading.db"
            store = TradeStore(path)
            store.begin_daily_loss_halt(MIDNIGHT)
            store._connection.execute(
                "UPDATE risk_state SET trading_date = ?, daily_realized_pnl = '-500' WHERE state_id = 1",
                ((MIDNIGHT - timedelta(days=1)).date().isoformat(),),
            )
            store._connection.commit()
            store.close()
            reopened = TradeStore(path)
            state = reopened.read_risk_state()
            self.assertEqual(state.daily_realized_pnl, Decimal("0"))
            self.assertIsNone(state.daily_loss_halt_until)
            reopened.close()

    def test_daily_reset_does_not_clear_drawdown_halt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TradeStore(Path(directory) / "trading.db")
            store.update_risk_state(halted=True, halt_reason="Maximum drawdown stop reached.")
            store._connection.execute(
                "UPDATE risk_state SET trading_date = ?, daily_realized_pnl = '-500', daily_loss_halt_until = ? WHERE state_id = 1",
                ((MIDNIGHT - timedelta(days=1)).date().isoformat(), MIDNIGHT.isoformat()),
            )
            store._connection.commit()
            state = store.read_risk_state()
            self.assertTrue(state.halted)
            self.assertEqual(state.halt_reason, "Maximum drawdown stop reached.")
            self.assertEqual(state.daily_realized_pnl, Decimal("0"))
            store.close()

    def test_daily_and_consecutive_cooldowns_overlap_independently(self):
        decision = base_guard(
            now=START,
            consecutive_loss_cooldown_until=START + timedelta(hours=1),
        )
        self.assertFalse(decision.allowed)
        decision = base_guard(
            now=MIDNIGHT,
            daily_realized_pnl=Decimal("0"),
            consecutive_loss_cooldown_until=MIDNIGHT + timedelta(hours=1),
        )
        self.assertFalse(decision.allowed)
        self.assertIn("cooldown", decision.reasons[0].lower())

    def test_existing_position_managed_during_daily_halt(self):
        candles = {symbol: [
            HistoricalCandle(START, START + timedelta(hours=2), Decimal("100"), Decimal("101"), Decimal("98"), Decimal("99"))
        ] for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
        engine = PortfolioBacktest(candles, {symbol: [] for symbol in candles})
        engine.daily_loss_halt_until = MIDNIGHT
        engine.positions["BTCUSDT"] = BacktestPosition("BTCUSDT", "LONG", Decimal("1"), START, Decimal("100"), Decimal("100"), Decimal("99"), Decimal("110"), Decimal("1"), Decimal("10"))
        engine._manage("BTCUSDT", candles["BTCUSDT"][0])
        self.assertEqual(engine.trades[0].exit_reason, "STOP_LOSS")


if __name__ == "__main__":
    unittest.main()
