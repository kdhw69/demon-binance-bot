import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, call

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    TestOrderSideEnum,
    TestOrderTypeEnum,
)

from src.execution_engine import ExecutionPreview
from src.order_service import _submit_execution_test_orders


def make_preview(
    symbol: str = "BTCUSDT",
    side: str = "BUY",
) -> ExecutionPreview:
    return ExecutionPreview(
        symbol=symbol,
        side=side,
        signal_time=datetime(
            2026, 9, 4, 7, 59, 59, tzinfo=timezone.utc
        ),
        quantity=Decimal("0.001"),
        entry_price=Decimal("80000"),
        stop_loss=Decimal("79000"),
        take_profit=Decimal("82000"),
        planned_risk=Decimal("1"),
        margin_used=Decimal("8"),
    )


class OrderServiceTests(unittest.TestCase):
    def test_approved_previews_submit_market_test_orders(self):
        client = Mock()
        response = Mock()
        response.status = 200
        client.rest_api.test_order.return_value = response

        previews = (
            make_preview(),
            make_preview("ETHUSDT", "SELL"),
        )
        result = _submit_execution_test_orders(client, previews)

        self.assertEqual(
            result,
            {
                "BTCUSDT": True,
                "ETHUSDT": True,
            },
        )
        self.assertEqual(
            client.rest_api.test_order.call_args_list,
            [
                call(
                    symbol="BTCUSDT",
                    side=TestOrderSideEnum.BUY,
                    type=TestOrderTypeEnum.MARKET,
                    quantity="0.001",
                ),
                call(
                    symbol="ETHUSDT",
                    side=TestOrderSideEnum.SELL,
                    type=TestOrderTypeEnum.MARKET,
                    quantity="0.001",
                ),
            ],
        )

    def test_duplicate_symbol_fails_before_api_call(self):
        client = Mock()

        with self.assertRaisesRegex(ValueError, "Duplicate"):
            _submit_execution_test_orders(
                client,
                (
                    make_preview(),
                    make_preview(),
                ),
            )

        client.rest_api.test_order.assert_not_called()

    def test_invalid_symbol_fails_before_api_call(self):
        client = Mock()

        with self.assertRaisesRegex(ValueError, "not permitted"):
            _submit_execution_test_orders(
                client,
                (make_preview("XRPUSDT"),),
            )

        client.rest_api.test_order.assert_not_called()

    def test_rejected_test_order_fails_safely(self):
        client = Mock()
        response = Mock()
        response.status = 400
        client.rest_api.test_order.return_value = response

        with self.assertRaisesRegex(ValueError, "not accepted"):
            _submit_execution_test_orders(
                client,
                (make_preview(),),
            )


if __name__ == "__main__":
    unittest.main()