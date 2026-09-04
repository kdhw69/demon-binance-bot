import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.demo_execution_service import (
    AmbiguousEntryStateError,
    execute_demo_preview,
)
from src.demo_reconciliation import ReconciliationReport
from src.execution_engine import ExecutionPreview
from src.risk_guard import GuardDecision
from src.trade_store import TradeStore


def make_preview() -> ExecutionPreview:
    return ExecutionPreview(
        symbol="BTCUSDT",
        side="BUY",
        quantity=Decimal("0.001"),
        entry_price=Decimal("80000"),
        stop_loss=Decimal("79000"),
        take_profit=Decimal("82000"),
        planned_risk=Decimal("1"),
        margin_used=Decimal("8"),
    )


def api_response(**fields):
    model = SimpleNamespace(**fields)
    return SimpleNamespace(
        status=200,
        data=lambda: model,
    )


def entry_response(
    order_id=101,
    client_order_id="demon-entry",
    quantity="0.001",
    status="FILLED",
):
    return api_response(
        order_id=order_id,
        client_order_id=client_order_id,
        executed_qty=quantity,
        status=status,
    )


def algo_response(algo_id, client_algo_id):
    return api_response(
        algo_id=algo_id,
        client_algo_id=client_algo_id,
    )


def allowed_guard(_database_path):
    return GuardDecision(True, ())


def allowed_reconciliation(_database_path, _client):
    return ReconciliationReport(True, (), 0, 0)


class DemoExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.directory.name) / "trading.db"
        )
        self.client = MagicMock()
        self.api = self.client.rest_api

    def tearDown(self):
        self.directory.cleanup()

    def test_explicit_confirmation_is_required(self):
        with self.assertRaisesRegex(
            PermissionError,
            "explicit confirmation",
        ):
            execute_demo_preview(
                make_preview(),
                "abc123",
                self.database_path,
                client=self.client,
                reconciliation_checker=allowed_reconciliation,
                guard_checker=allowed_guard,
            )

        self.api.new_order.assert_not_called()

    def test_reconciliation_failure_blocks_orders(self):
        def blocked_reconciliation(_database_path, _client):
            return ReconciliationReport(
                False,
                ("Protection order is missing.",),
                1,
                0,
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "Reconciliation blocked",
        ):
            execute_demo_preview(
                make_preview(),
                "abc123",
                self.database_path,
                execution_enabled=True,
                client=self.client,
                reconciliation_checker=blocked_reconciliation,
                guard_checker=allowed_guard,
            )

        self.api.new_order.assert_not_called()
        self.api.new_algo_order.assert_not_called()

    def test_success_records_all_exchange_order_ids(self):
        self.api.new_order.return_value = entry_response()
        self.api.new_algo_order.side_effect = [
            algo_response(201, "demon-stop"),
            algo_response(301, "demon-take"),
        ]

        result = execute_demo_preview(
            make_preview(),
            "abc123",
            self.database_path,
            execution_enabled=True,
            client=self.client,
            reconciliation_checker=allowed_reconciliation,
            guard_checker=allowed_guard,
        )

        self.assertEqual(result.entry_order_id, 101)
        self.assertEqual(result.stop_algo_id, 201)
        self.assertEqual(result.take_profit_algo_id, 301)

        store = TradeStore(self.database_path)
        try:
            trade = store.read_active_trades()[0]
            self.assertEqual(trade["status"], "OPEN")
            self.assertEqual(trade["entry_order_id"], 101)
            self.assertEqual(trade["stop_algo_id"], 201)
            self.assertEqual(
                trade["take_profit_algo_id"],
                301,
            )
        finally:
            store.close()

    def test_protection_failure_cancels_and_emergency_closes(self):
        self.api.new_order.side_effect = [
            entry_response(),
            entry_response(
                order_id=102,
                client_order_id="demon-close",
            ),
        ]
        self.api.new_algo_order.side_effect = [
            algo_response(201, "demon-stop"),
            RuntimeError("take-profit failed"),
        ]
        self.api.cancel_all_algo_open_orders.return_value = (
            api_response()
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "demo position was closed",
        ):
            execute_demo_preview(
                make_preview(),
                "abc123",
                self.database_path,
                execution_enabled=True,
                client=self.client,
                reconciliation_checker=allowed_reconciliation,
                guard_checker=allowed_guard,
            )

        self.api.cancel_all_algo_open_orders.assert_called_once_with(
            symbol="BTCUSDT"
        )
        self.assertEqual(self.api.new_order.call_count, 2)

        store = TradeStore(self.database_path)
        try:
            self.assertEqual(store.read_active_trades(), [])
        finally:
            store.close()

    def test_filled_entry_with_missing_id_is_emergency_closed(self):
        self.api.new_order.side_effect = [
            entry_response(order_id=None),
            entry_response(
                order_id=102,
                client_order_id="demon-close",
            ),
        ]
        self.api.cancel_all_algo_open_orders.return_value = (
            api_response()
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "demo position was closed",
        ):
            execute_demo_preview(
                make_preview(),
                "abc123",
                self.database_path,
                execution_enabled=True,
                client=self.client,
                reconciliation_checker=allowed_reconciliation,
                guard_checker=allowed_guard,
            )

        self.assertEqual(self.api.new_order.call_count, 2)
        self.api.cancel_all_algo_open_orders.assert_called_once_with(
            symbol="BTCUSDT"
        )

        store = TradeStore(self.database_path)
        try:
            self.assertEqual(store.read_active_trades(), [])
        finally:
            store.close()

    def test_ambiguous_entry_remains_planned(self):
        self.api.new_order.side_effect = RuntimeError(
            "connection lost"
        )
        self.api.query_order.side_effect = RuntimeError(
            "query failed"
        )

        with self.assertRaises(AmbiguousEntryStateError):
            execute_demo_preview(
                make_preview(),
                "abc123",
                self.database_path,
                execution_enabled=True,
                client=self.client,
                reconciliation_checker=allowed_reconciliation,
                guard_checker=allowed_guard,
            )

        self.api.new_algo_order.assert_not_called()
        self.api.cancel_all_algo_open_orders.assert_not_called()

        store = TradeStore(self.database_path)
        try:
            trade = store.read_active_trades()[0]
            self.assertEqual(trade["status"], "PLANNED")
            self.assertEqual(
                trade["entry_client_order_id"],
                "demon-btcusdt-entry-abc123",
            )
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
