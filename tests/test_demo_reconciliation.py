import unittest
from decimal import Decimal
from types import SimpleNamespace

from src.demo_reconciliation import evaluate_reconciliation


def position(symbol="BTCUSDT", amount="0.001"):
    return SimpleNamespace(
        symbol=symbol,
        position_amt=amount,
    )


def protection(
    algo_id,
    client_id,
    order_type,
    trigger_price,
    side="SELL",
    symbol="BTCUSDT",
):
    return SimpleNamespace(
        algo_id=algo_id,
        client_algo_id=client_id,
        algo_type="CONDITIONAL",
        order_type=order_type,
        symbol=symbol,
        side=side,
        position_side="BOTH",
        close_position=True,
        trigger_price=trigger_price,
    )


def open_trade():
    return {
        "trade_id": 1,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "status": "OPEN",
        "planned_risk": Decimal("1"),
        "stop_loss_price": Decimal("79000"),
        "take_profit_price": Decimal("82000"),
        "stop_algo_id": 201,
        "stop_client_algo_id": "demon-btc-stop",
        "take_profit_algo_id": 301,
        "take_profit_client_algo_id": "demon-btc-take",
    }


def matching_protections():
    return [
        protection(
            201,
            "demon-btc-stop",
            "STOP_MARKET",
            "79000",
        ),
        protection(
            301,
            "demon-btc-take",
            "TAKE_PROFIT_MARKET",
            "82000",
        ),
    ]


class DemoReconciliationTests(unittest.TestCase):
    def test_empty_state_is_safe(self):
        report = evaluate_reconciliation([], [], [])

        self.assertTrue(report.safe)
        self.assertEqual(report.issues, ())
        self.assertEqual(report.position_count, 0)
        self.assertEqual(report.algo_order_count, 0)

    def test_matching_open_trade_is_safe(self):
        report = evaluate_reconciliation(
            [open_trade()],
            [position()],
            matching_protections(),
        )

        self.assertTrue(report.safe)
        self.assertEqual(report.issues, ())

    def test_planned_trade_requires_reconciliation(self):
        report = evaluate_reconciliation(
            [
                {
                    "trade_id": 1,
                    "symbol": "BTCUSDT",
                    "status": "PLANNED",
                    "entry_client_order_id": (
                        "demon-btc-entry-abc"
                    ),
                }
            ],
            [],
            [],
        )

        self.assertFalse(report.safe)
        self.assertIn(
            "PLANNED trade requires entry reconciliation",
            report.issues[0],
        )

    def test_missing_protection_is_reported(self):
        report = evaluate_reconciliation(
            [open_trade()],
            [position()],
            [],
        )

        self.assertFalse(report.safe)
        self.assertTrue(
            any(
                "stop protection is missing" in issue
                for issue in report.issues
            )
        )
        self.assertTrue(
            any(
                "take_profit protection is missing" in issue
                for issue in report.issues
            )
        )

    def test_untracked_position_and_bot_order_are_reported(self):
        order = protection(
            999,
            "demon-btc-stop-old",
            "STOP_MARKET",
            "79000",
        )
        report = evaluate_reconciliation(
            [],
            [position()],
            [order],
        )

        self.assertFalse(report.safe)
        self.assertTrue(
            any(
                "no local OPEN trade" in issue
                for issue in report.issues
            )
        )
        self.assertTrue(
            any(
                "untracked bot protection order" in issue
                for issue in report.issues
            )
        )


if __name__ == "__main__":
    unittest.main()
