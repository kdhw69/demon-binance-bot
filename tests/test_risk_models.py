import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.backtest_engine import HistoricalCandle, PortfolioBacktest


class RiskModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = PortfolioBacktest({}, {})

    def test_fixed_models(self):
        self.assertEqual(self.engine._risk_limits(), (Decimal("0.01"), Decimal("0.025")))
        self.engine.risk_model = "B"
        self.assertEqual(self.engine._risk_limits(), (Decimal("0.005"), Decimal("0.0125")))

    def test_model_d_uses_fixed_low_risk_limits(self):
        engine = PortfolioBacktest({}, {}, risk_model="D")
        self.assertEqual(
            engine._risk_limits(),
            (Decimal("0.0025"), Decimal("0.00625")),
        )

    def test_adaptive_threshold_transitions_and_recovery(self):
        self.engine.risk_model = "C"
        self.engine.peak_equity = Decimal("10000")
        for equity, expected in ((Decimal("10000"), ("0.01", "0.025")), (Decimal("9500"), ("0.005", "0.0125")), (Decimal("9000"), ("0.0025", "0.00625")), (Decimal("9600"), ("0.01", "0.025")), (Decimal("10000"), ("0.01", "0.025"))):
            self.engine.equity = equity
            self.assertEqual(self.engine._risk_limits(), tuple(Decimal(value) for value in expected))

    def test_adaptive_model_halts_at_fifteen_percent(self):
        self.engine.risk_model = "C"
        self.engine.diagnostic_ignore_max_drawdown_halt = True
        self.engine.peak_equity = Decimal("10000")
        self.engine.equity = Decimal("8500")
        self.engine._check_limits(datetime(2022, 1, 1, tzinfo=timezone.utc))
        self.assertTrue(self.engine.halted)

    def test_combined_risk_scaling_is_model_specific(self):
        self.engine.risk_model = "A"
        self.assertEqual(self.engine._risk_limits()[1], Decimal("0.025"))
        self.engine.risk_model = "B"
        self.assertEqual(self.engine._risk_limits()[1], Decimal("0.0125"))
        self.engine.risk_model = "C"
        self.engine.equity = Decimal("9000")
        self.engine.peak_equity = Decimal("10000")
        self.assertEqual(self.engine._risk_limits()[1], Decimal("0.00625"))


if __name__ == "__main__":
    unittest.main()
