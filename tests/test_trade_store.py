import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from src.trade_store import TradeStore


class TradeStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = TradeStore(Path(self.directory.name) / "trading.db")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def record_trade(self):
        return self.store.record_planned_trade(
            "BTCUSDT", "BUY", Decimal("0.00100001"), Decimal("50000.12345678"),
            Decimal("49000.12345678"), Decimal("52000.12345678"),
            Decimal("1.00000001"), Decimal("5.00000001"),
        )

    def test_initialization_is_idempotent(self):
        self.store.initialize()
        tables = {
            row[0]
            for row in self.store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertEqual(tables, {"trades", "risk_state", "sqlite_sequence"})

    def test_decimal_values_are_preserved(self):
        trade_id = self.record_trade()
        trade = self.store.read_active_trades()[0]
        self.assertEqual(trade["trade_id"], trade_id)
        self.assertEqual(trade["quantity"], Decimal("0.00100001"))
        self.assertEqual(trade["entry_price"], Decimal("50000.12345678"))
        self.assertEqual(trade["planned_risk"], Decimal("1.00000001"))

    def test_duplicate_active_symbol_is_rejected(self):
        self.record_trade()

        with self.assertRaisesRegex(
            ValueError,
            "active trade already exists",
        ):
            self.record_trade()

    def test_processed_signal_candle_cannot_be_reused(self):
        signal_time = datetime(
            2026, 9, 4, 7, 59, 59, tzinfo=timezone.utc
        )
        trade_id = self.store.record_planned_trade(
            "BTCUSDT",
            "BUY",
            Decimal("0.001"),
            Decimal("50000"),
            Decimal("49000"),
            Decimal("52000"),
            Decimal("1"),
            Decimal("5"),
            signal_time=signal_time,
        )
        self.store.mark_open(trade_id)
        self.store.mark_closed(
            trade_id,
            Decimal("50100"),
            Decimal("1"),
        )

        with self.assertRaisesRegex(
            ValueError,
            "signal candle was already processed",
        ):
            self.store.record_planned_trade(
                "BTCUSDT",
                "BUY",
                Decimal("0.001"),
                Decimal("50000"),
                Decimal("49000"),
                Decimal("52000"),
                Decimal("1"),
                Decimal("5"),
                signal_time=signal_time,
            )

    def test_planned_client_order_ids_are_stored(self):
        trade_id = self.store.record_planned_trade(
            "BTCUSDT",
            "BUY",
            Decimal("0.001"),
            Decimal("50000"),
            Decimal("49000"),
            Decimal("52000"),
            Decimal("1"),
            Decimal("5"),
            "demon-btc-entry-abc",
            "demon-btc-stop-abc",
            "demon-btc-take-abc",
        )

        trade = self.store.read_active_trades()[0]
        self.assertEqual(trade["trade_id"], trade_id)
        self.assertEqual(
            trade["entry_client_order_id"],
            "demon-btc-entry-abc",
        )
        self.assertEqual(
            trade["stop_client_algo_id"],
            "demon-btc-stop-abc",
        )
        self.assertEqual(
            trade["take_profit_client_algo_id"],
            "demon-btc-take-abc",
        )

    def test_partial_planned_client_ids_are_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "All planned client order ids",
        ):
            self.store.record_planned_trade(
                "BTCUSDT",
                "BUY",
                Decimal("0.001"),
                Decimal("50000"),
                Decimal("49000"),
                Decimal("52000"),
                Decimal("1"),
                Decimal("5"),
                "demon-btc-entry-abc",
            )

    def test_trade_lifecycle_and_utc_times(self):
        trade_id = self.record_trade()
        entry_time = datetime(2026, 9, 4, 12, 0, tzinfo=timezone(timedelta(hours=2)))
        exit_time = datetime(2026, 9, 4, 13, 0, tzinfo=timezone(timedelta(hours=2)))
        self.store.mark_open(trade_id, entry_time)
        self.assertEqual(self.store.read_active_trades()[0]["status"], "OPEN")
        self.store.mark_closed(trade_id, Decimal("50100.12"), Decimal("0.10"), exit_time)
        self.assertEqual(self.store.read_active_trades(), [])
        row = self.store._connection.execute(
            "SELECT entry_time, exit_time, status FROM trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
        self.assertEqual(row["status"], "CLOSED")
        self.assertTrue(row["entry_time"].endswith("+00:00"))
        self.assertTrue(row["exit_time"].endswith("+00:00"))

    def test_exchange_order_ids_are_stored(self):
        trade_id = self.record_trade()

        self.store.mark_open_with_exchange_orders(
            trade_id=trade_id,
            entry_order_id=101,
            entry_client_order_id="entry-101",
            stop_algo_id=202,
            stop_client_algo_id="stop-202",
            take_profit_algo_id=303,
            take_profit_client_algo_id="take-303",
        )

        trade = self.store.read_active_trades()[0]
        self.assertEqual(trade["status"], "OPEN")
        self.assertEqual(trade["entry_order_id"], 101)
        self.assertEqual(trade["entry_client_order_id"], "entry-101")
        self.assertEqual(trade["stop_algo_id"], 202)
        self.assertEqual(trade["stop_client_algo_id"], "stop-202")
        self.assertEqual(trade["take_profit_algo_id"], 303)
        self.assertEqual(
            trade["take_profit_client_algo_id"],
            "take-303",
        )

    def test_failed_planned_trade_is_not_active(self):
        trade_id = self.record_trade()

        self.store.mark_failed(trade_id)

        self.assertEqual(self.store.read_active_trades(), [])
        row = self.store._connection.execute(
            "SELECT status FROM trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
        self.assertEqual(row["status"], "FAILED")

    def test_invalid_exchange_order_ids_are_rejected(self):
        trade_id = self.record_trade()

        with self.assertRaisesRegex(ValueError, "positive integers"):
            self.store.mark_open_with_exchange_orders(
                trade_id=trade_id,
                entry_order_id=0,
                entry_client_order_id="entry",
                stop_algo_id=2,
                stop_client_algo_id="stop",
                take_profit_algo_id=3,
                take_profit_client_algo_id="take",
            )

    def test_daily_pnl_and_consecutive_losses(self):
        first = self.record_trade()
        self.store.mark_open(first)
        self.store.mark_closed(first, Decimal("1"), Decimal("-2"))
        second = self.record_trade()
        self.store.mark_open(second)
        self.store.mark_closed(second, Decimal("1"), Decimal("-3"))
        state = self.store.read_risk_state()
        self.assertEqual(state.daily_realized_pnl, Decimal("-5"))
        self.assertEqual(state.consecutive_losses, 2)
        third = self.record_trade()
        self.store.mark_open(third)
        self.store.mark_closed(third, Decimal("1"), Decimal("0"))
        state = self.store.read_risk_state()
        self.assertEqual(state.daily_realized_pnl, Decimal("-5"))
        self.assertEqual(state.consecutive_losses, 0)

    def test_utc_daily_reset(self):
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        self.store._connection.execute(
            "UPDATE risk_state SET trading_date = ?, daily_realized_pnl = '-5' WHERE state_id = 1",
            (yesterday.isoformat(),),
        )
        self.store._connection.commit()
        state = self.store.read_risk_state()
        self.assertEqual(state.trading_date, datetime.now(timezone.utc).date())
        self.assertEqual(state.daily_realized_pnl, Decimal("0"))

    def test_transaction_rollback(self):
        trade_id = self.record_trade()
        self.store.mark_open(trade_id)
        with patch.object(self.store, "_current_risk_state", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                self.store.mark_closed(trade_id, Decimal("1"), Decimal("2"))
        row = self.store._connection.execute(
            "SELECT status, exit_price, realized_pnl FROM trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
        self.assertEqual(row["status"], "OPEN")
        self.assertIsNone(row["exit_price"])
        self.assertIsNone(row["realized_pnl"])

    def test_float_financial_values_are_rejected(self):
        with self.assertRaises(TypeError):
            self.store.record_planned_trade(
                "BTCUSDT", "BUY", 0.1, Decimal("1"), Decimal("1"), Decimal("2"), Decimal("1"), Decimal("1")
            )


if __name__ == "__main__":
    unittest.main()
