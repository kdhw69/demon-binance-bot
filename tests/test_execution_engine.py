import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from src.execution_engine import (
    build_execution_previews,
    run_dry_run_cycle,
)
from src.risk_guard import GuardDecision
from src.risk_manager import RiskPlan


def make_plan(
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
) -> RiskPlan:
    return RiskPlan(
        symbol=symbol,
        direction=direction,
        signal_time=datetime(
            2026, 9, 4, 7, 59, 59, tzinfo=timezone.utc
        ),
        quantity=Decimal("0.001"),
        entry_price=Decimal("80000"),
        stop_loss=Decimal("79000"),
        take_profit=Decimal("82000"),
        risk_amount=Decimal("1"),
        margin_used=Decimal("8"),
        reason="Approved within confirmed risk limits.",
    )


class ExecutionEngineTests(unittest.TestCase):
    def test_approved_long_plan_becomes_buy_preview(self):
        result = build_execution_previews(
            GuardDecision(True, ()),
            {
                "BTCUSDT": make_plan(),
                "ETHUSDT": None,
                "SOLUSDT": None,
            },
        )

        self.assertTrue(result.allowed)
        self.assertEqual(len(result.previews), 1)
        self.assertEqual(result.previews[0].symbol, "BTCUSDT")
        self.assertEqual(result.previews[0].side, "BUY")
        self.assertEqual(result.previews[0].planned_risk, Decimal("1"))

    def test_short_plan_becomes_sell_preview(self):
        result = build_execution_previews(
            GuardDecision(True, ()),
            {
                "BTCUSDT": make_plan(direction="SHORT"),
                "ETHUSDT": None,
                "SOLUSDT": None,
            },
        )

        self.assertEqual(result.previews[0].side, "SELL")

    def test_blocked_guard_returns_no_previews(self):
        result = build_execution_previews(
            GuardDecision(False, ("Trading is halted.",)),
            {"BTCUSDT": make_plan()},
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reasons, ("Trading is halted.",))
        self.assertEqual(result.previews, ())

    def test_mismatched_symbol_fails_safely(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_execution_previews(
                GuardDecision(True, ()),
                {"BTCUSDT": make_plan(symbol="ETHUSDT")},
            )

    @patch("src.execution_engine.get_latest_risk_plans")
    @patch("src.execution_engine.check_live_guard")
    def test_blocked_cycle_does_not_request_plans(
        self,
        check_guard,
        get_plans,
    ):
        check_guard.return_value = GuardDecision(
            False,
            ("Risk guard blocked execution.",),
        )

        result = run_dry_run_cycle()

        self.assertFalse(result.allowed)
        get_plans.assert_not_called()


if __name__ == "__main__":
    unittest.main()