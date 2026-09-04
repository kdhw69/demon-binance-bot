import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.demo_trade_monitor import monitor_demo_trades
from src.trade_store import TradeStore


ENTRY_TIME = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
EXIT_TIME_MS = 1788483600000


def response(data=None, status=200):
    return SimpleNamespace(
        status=status,
        data=lambda: data,
    )


def algo(actual_order_id="", actual_qty="0"):
    return SimpleNamespace(
        actual_order_id=actual_order_id,
        actual_qty=actual_qty,
    )


def fill(
    order_id,
    price,
    quantity,
    realized_pnl,
    commission,
    time_ms,
):
    return SimpleNamespace(
        symbol="BTCUSDT",
        order_id=order_id,
        price=price,
        qty=quantity,
        realized_pnl=realized_pnl,
        commission=commission,
        commission_asset="USDT",
        time=time_ms,
    )


def create_open_trade(store):
    trade_id = store.record_planned_trade(
        "BTCUSDT",
        "BUY",
        Decimal("0.001"),
        Decimal("80000"),
        Decimal("79000"),
        Decimal("82000"),
        Decimal("1"),
        Decimal("8"),
        "demon-btc-entry",
        "demon-btc-stop",
        "demon-btc-take",
    )
    store.mark_open_with_exchange_orders(
        trade_id,
        101,
        "demon-btc-entry",
        201,
        "demon-btc-stop",
        301,
        "demon-btc-take",
        ENTRY_TIME,
    )
    return trade_id


class DemoTradeMonitorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.directory.name) / "trading.db"
        )
        self.client = MagicMock()
        self.api = self.client.rest_api

    def tearDown(self):
        self.directory.cleanup()

    def test_triggered_stop_closes_local_trade(self):
        store = TradeStore(self.database_path)
        trade_id = create_open_trade(store)
        store.close()

        self.api.position_information_v3.return_value = response([])
        self.api.query_algo_order.side_effect = [
            response(algo("401", "0.001")),
            response(algo()),
        ]
        self.api.cancel_all_algo_open_orders.return_value = (
            response()
        )
        self.api.account_trade_list.side_effect = [
            response(
                [
                    fill(
                        101,
                        "80000",
                        "0.001",
                        "0",
                        "0.04",
                        1788476400000,
                    )
                ]
            ),
            response(
                [
                    fill(
                        401,
                        "79000",
                        "0.001",
                        "-1",
                        "0.0395",
                        EXIT_TIME_MS,
                    )
                ]
            ),
        ]
        self.api.get_income_history.return_value = response(
            [
                SimpleNamespace(
                    symbol="BTCUSDT",
                    asset="USDT",
                    income="-0.01",
                )
            ]
        )

        report = monitor_demo_trades(
            self.database_path,
            self.client,
        )

        self.assertEqual(report.closed_trade_ids, (trade_id,))
        self.assertEqual(report.issues, ())

        reopened = TradeStore(self.database_path)
        try:
            self.assertEqual(reopened.read_active_trades(), [])
            row = reopened._connection.execute(
                """
                SELECT status, exit_price, realized_pnl
                FROM trades
                WHERE trade_id = ?
                """,
                (trade_id,),
            ).fetchone()
            self.assertEqual(row["status"], "CLOSED")
            self.assertEqual(
                Decimal(row["exit_price"]),
                Decimal("79000"),
            )
            self.assertEqual(
                Decimal(row["realized_pnl"]),
                Decimal("-1.0895"),
            )
        finally:
            reopened.close()

    def test_existing_position_is_left_unchanged(self):
        store = TradeStore(self.database_path)
        create_open_trade(store)
        store.close()

        self.api.position_information_v3.return_value = response(
            [
                SimpleNamespace(
                    symbol="BTCUSDT",
                    position_amt="0.001",
                )
            ]
        )

        report = monitor_demo_trades(
            self.database_path,
            self.client,
        )

        self.assertEqual(report.closed_trade_ids, ())
        self.assertEqual(report.issues, ())
        self.api.query_algo_order.assert_not_called()

    def test_planned_trade_requires_manual_reconciliation(self):
        store = TradeStore(self.database_path)
        store.record_planned_trade(
            "BTCUSDT",
            "BUY",
            Decimal("0.001"),
            Decimal("80000"),
            Decimal("79000"),
            Decimal("82000"),
            Decimal("1"),
            Decimal("8"),
            "demon-btc-entry",
            "demon-btc-stop",
            "demon-btc-take",
        )
        store.close()
        self.api.position_information_v3.return_value = response([])

        report = monitor_demo_trades(
            self.database_path,
            self.client,
        )

        self.assertEqual(report.closed_trade_ids, ())
        self.assertTrue(
            any("manual reconciliation" in item for item in report.issues)
        )
        self.api.query_algo_order.assert_not_called()

    def test_missing_trigger_keeps_trade_open(self):
        store = TradeStore(self.database_path)
        create_open_trade(store)
        store.close()
        self.api.position_information_v3.return_value = response([])
        self.api.query_algo_order.side_effect = [
            response(algo()),
            response(algo()),
        ]

        report = monitor_demo_trades(
            self.database_path,
            self.client,
        )

        self.assertEqual(report.closed_trade_ids, ())
        self.assertTrue(
            any("Exactly one" in item for item in report.issues)
        )
        self.api.cancel_all_algo_open_orders.assert_not_called()

    def test_failed_cancellation_keeps_trade_open(self):
        store = TradeStore(self.database_path)
        create_open_trade(store)
        store.close()
        self.api.position_information_v3.return_value = response([])
        self.api.query_algo_order.side_effect = [
            response(algo("401", "0.001")),
            response(algo()),
        ]
        self.api.cancel_all_algo_open_orders.return_value = response(
            status=500
        )

        report = monitor_demo_trades(
            self.database_path,
            self.client,
        )

        self.assertEqual(report.closed_trade_ids, ())
        self.assertTrue(
            any("cancellation" in item for item in report.issues)
        )
        self.api.account_trade_list.assert_not_called()


if __name__ == "__main__":
    unittest.main()
