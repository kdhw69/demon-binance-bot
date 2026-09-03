import unittest
from datetime import datetime, timezone
from decimal import Decimal

from src.exchange_rules import TradingRules
from src.market_data import Candle
from src.risk_manager import AccountRiskState, create_risk_plan
from src.signal_engine import Signal


RULES = TradingRules(
    symbol="BTCUSDT",
    status="TRADING",
    price_tick_size=Decimal("0.10"),
    quantity_step_size=Decimal("0.001"),
    minimum_order_quantity=Decimal("0.001"),
    minimum_notional_value=Decimal("5"),
)
ACCOUNT = AccountRiskState(
    equity=Decimal("10000"),
    open_positions=0,
    combined_open_risk=Decimal("0"),
    total_margin_used=Decimal("0"),
)


def signal(direction, price="100", atr="2"):
    return Signal(
        symbol="BTCUSDT",
        candle_close_time=datetime.now(timezone.utc),
        direction=direction,
        close_price=Decimal(price),
        ema=Decimal("90"),
        donchian_high=Decimal("95"),
        donchian_low=Decimal("85"),
        atr=Decimal(atr),
    )


class RiskManagerTests(unittest.TestCase):
    def test_long_plan_rounds_exits_safely_and_quantity_down(self):
        plan = create_risk_plan(signal("LONG"), ACCOUNT, RULES)
        self.assertEqual(plan.stop_loss, Decimal("97.00"))
        self.assertEqual(plan.take_profit, Decimal("106.00"))
        self.assertEqual(plan.quantity, Decimal("33.333"))
        self.assertLess(plan.risk_amount, Decimal("100"))

    def test_short_plan_rounds_exits_safely(self):
        plan = create_risk_plan(signal("SHORT"), ACCOUNT, RULES)
        self.assertEqual(plan.stop_loss, Decimal("103.00"))
        self.assertEqual(plan.take_profit, Decimal("94.00"))
        self.assertLess(plan.take_profit, plan.entry_price)
        self.assertGreater(plan.stop_loss, plan.entry_price)

    def test_remaining_combined_risk_reduces_allocation(self):
        account = AccountRiskState(
            equity=Decimal("10000"),
            open_positions=1,
            combined_open_risk=Decimal("0.024"),
            total_margin_used=Decimal("0"),
        )
        plan = create_risk_plan(signal("LONG"), account, RULES)
        self.assertLessEqual(plan.risk_amount, Decimal("10"))

    def test_risk_limits_reject(self):
        cases = [
            ("positions", AccountRiskState(Decimal("10000"), 3, Decimal("0"), Decimal("0"))),
            ("risk", AccountRiskState(Decimal("10000"), 0, Decimal("0.025"), Decimal("0"))),
            ("margin", AccountRiskState(Decimal("10000"), 0, Decimal("0"), Decimal("3000"))),
            ("daily", AccountRiskState(Decimal("10000"), 0, Decimal("0"), Decimal("0"), Decimal("0.05"))),
            ("losses", AccountRiskState(Decimal("10000"), 0, Decimal("0"), Decimal("0"), Decimal("0"), 4)),
            ("drawdown", AccountRiskState(Decimal("10000"), 0, Decimal("0"), Decimal("0"), Decimal("0"), 0, Decimal("0.15"))),
        ]
        for name, account in cases:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    create_risk_plan(signal("LONG"), account, RULES)

    def test_minimum_order_rejection(self):
        rules = TradingRules("BTCUSDT", "TRADING", Decimal("0.10"), Decimal("1"), Decimal("100"), Decimal("100000"))
        with self.assertRaisesRegex(ValueError, "minimum"):
            create_risk_plan(signal("LONG"), ACCOUNT, rules)


if __name__ == "__main__":
    unittest.main()
