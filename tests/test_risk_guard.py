import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.risk_guard import evaluate_guard
from src.trade_store import TradeStore


class RiskGuardTests(unittest.TestCase):
    def decision(self, **overrides):
        values = {
            "account_equity": Decimal("10000"),
            "day_start_equity": Decimal("10000"),
            "peak_equity": Decimal("10000"),
            "daily_realized_pnl": Decimal("0"),
            "consecutive_losses": 0,
            "halted": False,
            "halt_reason": None,
            "binance_position_symbols": set(),
            "local_active_trades": [],
            "total_used_margin": Decimal("0"),
        }
        values.update(overrides)
        return evaluate_guard(**values)

    def test_all_halt_conditions(self):
        cases = [
            ("daily loss", {"daily_realized_pnl": Decimal("-500")}),
            ("consecutive losses", {"consecutive_losses": 4}),
            ("drawdown", {"account_equity": Decimal("8500")}),
            ("positions", {"binance_position_symbols": {"A", "B", "C"}}),
            ("combined risk", {"local_active_trades": [{"symbol": "A", "planned_risk": Decimal("250") }]}),
            ("margin", {"total_used_margin": Decimal("3000")}),
            ("permanent halt", {"halted": True, "halt_reason": "Manual halt."}),
        ]
        for name, overrides in cases:
            with self.subTest(name=name):
                decision = self.decision(**overrides)
                self.assertFalse(decision.allowed)
                self.assertTrue(decision.reasons)

    def test_position_reconciliation_halts(self):
        decision = self.decision(
            binance_position_symbols={"BTCUSDT"},
            local_active_trades=[],
        )
        self.assertFalse(decision.allowed)
        self.assertIn("Reconciliation required", decision.reasons[0])

    def test_planned_trade_blocks_without_position_mismatch(self):
        decision = self.decision(
            local_active_trades=[
                {
                    "symbol": "BTCUSDT",
                    "status": "PLANNED",
                    "planned_risk": Decimal("1"),
                }
            ],
        )

        self.assertFalse(decision.allowed)
        self.assertIn(
            "Pending planned trade requires reconciliation.",
            decision.reasons,
        )
        self.assertFalse(
            any(
                "Binance positions and local open trades differ"
                in reason
                for reason in decision.reasons
            )
        )

    def test_matching_open_trade_reconciles(self):
        decision = self.decision(
            binance_position_symbols={"BTCUSDT"},
            local_active_trades=[
                {
                    "symbol": "BTCUSDT",
                    "status": "OPEN",
                    "planned_risk": Decimal("1"),
                }
            ],
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reasons, ())

    def test_first_run_initializes_day_start_and_peak(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TradeStore(Path(directory) / "trading.db")
            state = store.sync_equity(Decimal("10000"))
            self.assertEqual(state.day_start_equity, Decimal("10000"))
            self.assertEqual(state.peak_account_equity, Decimal("10000"))
            store.close()

    def test_peak_equity_only_moves_up(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TradeStore(Path(directory) / "trading.db")
            store.sync_equity(Decimal("10000"))
            lower = store.sync_equity(Decimal("9000"))
            higher = store.sync_equity(Decimal("11000"))
            self.assertEqual(lower.peak_account_equity, Decimal("10000"))
            self.assertEqual(higher.peak_account_equity, Decimal("11000"))
            store.close()

    def test_utc_reset_preserves_permanent_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TradeStore(Path(directory) / "trading.db")
            store.sync_equity(Decimal("10000"))
            store._connection.execute(
                """
                UPDATE risk_state
                SET trading_date = ?, daily_realized_pnl = '-500',
                    consecutive_losses = 4, halted = 1, halt_reason = 'Drawdown stop'
                WHERE state_id = 1
                """,
                ((datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat(),),
            )
            store._connection.commit()
            state = store.sync_equity(Decimal("9500"))
            self.assertEqual(state.day_start_equity, Decimal("9500"))
            self.assertEqual(state.daily_realized_pnl, Decimal("0"))
            self.assertEqual(state.peak_account_equity, Decimal("10000"))
            self.assertEqual(state.consecutive_losses, 4)
            self.assertTrue(state.halted)
            self.assertEqual(state.halt_reason, "Drawdown stop")
            store.close()


if __name__ == "__main__":
    unittest.main()
