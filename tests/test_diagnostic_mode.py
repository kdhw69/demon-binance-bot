import unittest
from datetime import datetime, timezone
from decimal import Decimal

import src.risk_guard as live_risk_guard
from src.backtest_engine import PortfolioBacktest


class DiagnosticModeTests(unittest.TestCase):
    def test_default_backtest_mode_keeps_drawdown_halt(self):
        engine = PortfolioBacktest({}, {})
        engine.equity = Decimal("4000")
        engine._check_limits(datetime.now(timezone.utc))
        self.assertTrue(engine.halted)

    def test_diagnostic_mode_ignores_halt_but_records_crossings(self):
        engine = PortfolioBacktest({}, {}, diagnostic_ignore_max_drawdown_halt=True)
        timestamp = datetime(2022, 1, 1, tzinfo=timezone.utc)
        engine.equity = Decimal("4000")
        engine._check_limits(timestamp)
        self.assertFalse(engine.halted)
        self.assertEqual(len(engine.halts), 1)
        engine.equity = Decimal("5000")
        engine._check_limits(timestamp)
        engine.equity = Decimal("4000")
        engine._check_limits(timestamp)
        self.assertEqual(len(engine.halts), 2)

    def test_diagnostic_option_is_not_available_to_live_guard(self):
        self.assertFalse(hasattr(live_risk_guard, "diagnostic_ignore_max_drawdown_halt"))
        self.assertNotIn("diagnostic_ignore_max_drawdown_halt", dir(live_risk_guard))


if __name__ == "__main__":
    unittest.main()
