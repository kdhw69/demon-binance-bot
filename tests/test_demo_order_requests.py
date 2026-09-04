import unittest
from datetime import datetime, timezone
from decimal import Decimal

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NewAlgoOrderClosePositionEnum,
    NewAlgoOrderSideEnum,
    NewAlgoOrderTypeEnum,
    NewOrderReduceOnlyEnum,
    NewOrderSideEnum,
    NewOrderTypeEnum,
)

from src.demo_order_requests import (
    build_demo_order_requests,
    build_emergency_close_request,
)
from src.execution_engine import ExecutionPreview


def make_preview(side: str = "BUY") -> ExecutionPreview:
    if side == "BUY":
        stop_loss = Decimal("79000")
        take_profit = Decimal("82000")
    else:
        stop_loss = Decimal("82000")
        take_profit = Decimal("79000")

    return ExecutionPreview(
        symbol="BTCUSDT",
        side=side,
        signal_time=datetime(
            2026, 9, 4, 7, 59, 59, tzinfo=timezone.utc
        ),
        quantity=Decimal("0.001"),
        entry_price=Decimal("80000"),
        stop_loss=stop_loss,
        take_profit=take_profit,
        planned_risk=Decimal("1"),
        margin_used=Decimal("8"),
    )


class DemoOrderRequestTests(unittest.TestCase):
    def test_buy_request_builds_sell_protection(self):
        requests = build_demo_order_requests(
            make_preview("BUY"),
            "abc123",
        )

        self.assertEqual(requests.entry["side"], NewOrderSideEnum.BUY)
        self.assertEqual(requests.entry["type"], NewOrderTypeEnum.MARKET)
        self.assertEqual(
            requests.stop_loss["side"],
            NewAlgoOrderSideEnum.SELL,
        )
        self.assertEqual(
            requests.take_profit["side"],
            NewAlgoOrderSideEnum.SELL,
        )

    def test_sell_request_builds_buy_protection(self):
        requests = build_demo_order_requests(
            make_preview("SELL"),
            "abc123",
        )

        self.assertEqual(requests.entry["side"], NewOrderSideEnum.SELL)
        self.assertEqual(
            requests.stop_loss["side"],
            NewAlgoOrderSideEnum.BUY,
        )
        self.assertEqual(
            requests.take_profit["side"],
            NewAlgoOrderSideEnum.BUY,
        )

    def test_protection_is_close_all_without_quantity(self):
        requests = build_demo_order_requests(
            make_preview(),
            "abc123",
        )

        for protection in (
            requests.stop_loss,
            requests.take_profit,
        ):
            self.assertEqual(
                protection["close_position"],
                NewAlgoOrderClosePositionEnum.TRUE,
            )
            self.assertNotIn("quantity", protection)
            self.assertNotIn("reduce_only", protection)

        self.assertEqual(
            requests.stop_loss["type"],
            NewAlgoOrderTypeEnum.STOP_MARKET,
        )
        self.assertEqual(
            requests.take_profit["type"],
            NewAlgoOrderTypeEnum.TAKE_PROFIT_MARKET,
        )

    def test_emergency_close_is_reduce_only_and_opposite(self):
        request = build_emergency_close_request(
            make_preview("BUY"),
            Decimal("0.001"),
            "abc123",
        )

        self.assertEqual(request["side"], NewOrderSideEnum.SELL)
        self.assertEqual(request["type"], NewOrderTypeEnum.MARKET)
        self.assertEqual(
            request["reduce_only"],
            NewOrderReduceOnlyEnum.TRUE,
        )
        self.assertEqual(request["position_side"], "BOTH")
        self.assertEqual(request["quantity"], 0.001)

    def test_emergency_close_rejects_invalid_quantity(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            build_emergency_close_request(
                make_preview(),
                Decimal("0"),
                "abc123",
            )

        with self.assertRaisesRegex(TypeError, "Decimal"):
            build_emergency_close_request(
                make_preview(),
                0.001,
                "abc123",
            )

    def test_invalid_exit_prices_are_rejected(self):
        preview = ExecutionPreview(
            symbol="BTCUSDT",
            side="BUY",
            signal_time=datetime(
                2026, 9, 4, 7, 59, 59, tzinfo=timezone.utc
            ),
            quantity=Decimal("0.001"),
            entry_price=Decimal("80000"),
            stop_loss=Decimal("81000"),
            take_profit=Decimal("82000"),
            planned_risk=Decimal("1"),
            margin_used=Decimal("8"),
        )

        with self.assertRaisesRegex(ValueError, "exit prices"):
            build_demo_order_requests(preview, "abc123")

    def test_unsafe_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "safe characters"):
            build_demo_order_requests(
                make_preview(),
                "invalid token",
            )


if __name__ == "__main__":
    unittest.main()