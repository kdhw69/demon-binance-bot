import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from src.demo_execution_service import DemoExecutionResult
from src.demo_trade_monitor import MonitorReport
from src.execution_engine import DryRunResult, ExecutionPreview
from src.run_demo_bot_cycle import _execution_lock, main


def preview():
    return ExecutionPreview(
        symbol="BTCUSDT",
        side="BUY",
        signal_time=datetime(
            2026, 9, 5, 7, 59, 59, tzinfo=timezone.utc
        ),
        quantity=Decimal("0.001"),
        entry_price=Decimal("80000"),
        stop_loss=Decimal("79000"),
        take_profit=Decimal("82000"),
        planned_risk=Decimal("1"),
        margin_used=Decimal("8"),
    )


class RunDemoBotCycleTests(unittest.TestCase):
    @patch("src.run_demo_bot_cycle.execute_demo_preview")
    @patch("src.run_demo_bot_cycle.monitor_demo_trades")
    @patch("src.run_demo_bot_cycle.run_dry_run_cycle")
    def test_default_mode_is_dry_run(
        self,
        run_dry_run,
        monitor,
        execute,
    ):
        run_dry_run.return_value = DryRunResult(True, (), ())

        result = main([])

        self.assertEqual(result, 0)
        run_dry_run.assert_called_once_with()
        monitor.assert_not_called()
        execute.assert_not_called()

    @patch("src.run_demo_bot_cycle.run_dry_run_cycle")
    def test_execute_flag_without_environment_is_blocked(
        self,
        run_dry_run,
    ):
        with patch.dict(os.environ, {}, clear=True):
            result = main(
                [
                    "--execute-demo",
                    "--confirmation",
                    "DEMO_ONLY",
                ]
            )

        self.assertEqual(result, 2)
        run_dry_run.assert_not_called()

    @patch("src.run_demo_bot_cycle.execute_demo_preview")
    @patch("src.run_demo_bot_cycle.monitor_demo_trades")
    @patch("src.run_demo_bot_cycle.run_dry_run_cycle")
    def test_confirmed_mode_with_no_plan_submits_nothing(
        self,
        run_dry_run,
        monitor,
        execute,
    ):
        monitor.return_value = MonitorReport((), ())
        run_dry_run.return_value = DryRunResult(True, (), ())

        with patch.dict(
            os.environ,
            {"DEMON_DEMO_EXECUTION_ENABLED": "YES"},
        ):
            result = main(
                [
                    "--execute-demo",
                    "--confirmation",
                    "DEMO_ONLY",
                ]
            )

        self.assertEqual(result, 0)
        execute.assert_not_called()

    @patch("src.run_demo_bot_cycle.execute_demo_preview")
    @patch("src.run_demo_bot_cycle.monitor_demo_trades")
    @patch("src.run_demo_bot_cycle.run_dry_run_cycle")
    def test_monitor_issue_blocks_execution(
        self,
        run_dry_run,
        monitor,
        execute,
    ):
        monitor.return_value = MonitorReport(
            (),
            ("Manual reconciliation required.",),
        )

        with patch.dict(
            os.environ,
            {"DEMON_DEMO_EXECUTION_ENABLED": "YES"},
        ):
            result = main(
                [
                    "--execute-demo",
                    "--confirmation",
                    "DEMO_ONLY",
                ]
            )

        self.assertEqual(result, 1)
        run_dry_run.assert_not_called()
        execute.assert_not_called()

    @patch("src.run_demo_bot_cycle.monitor_demo_trades")
    def test_concurrent_execution_is_blocked(
        self,
        monitor,
    ):
        with patch.dict(
            os.environ,
            {"DEMON_DEMO_EXECUTION_ENABLED": "YES"},
        ):
            with _execution_lock():
                result = main(
                    [
                        "--execute-demo",
                        "--confirmation",
                        "DEMO_ONLY",
                    ]
                )

        self.assertEqual(result, 1)
        monitor.assert_not_called()

    @patch("src.run_demo_bot_cycle.secrets.token_hex")
    @patch("src.run_demo_bot_cycle.execute_demo_preview")
    @patch("src.run_demo_bot_cycle.monitor_demo_trades")
    @patch("src.run_demo_bot_cycle.run_dry_run_cycle")
    def test_confirmed_mode_executes_approved_preview(
        self,
        run_dry_run,
        monitor,
        execute,
        token_hex,
    ):
        item = preview()
        monitor.return_value = MonitorReport((), ())
        run_dry_run.return_value = DryRunResult(
            True,
            (),
            (item,),
        )
        token_hex.return_value = "abc12345"
        execute.return_value = DemoExecutionResult(
            trade_id=1,
            symbol="BTCUSDT",
            entry_order_id=101,
            stop_algo_id=201,
            take_profit_algo_id=301,
            executed_quantity=Decimal("0.001"),
        )

        with patch.dict(
            os.environ,
            {"DEMON_DEMO_EXECUTION_ENABLED": "YES"},
        ):
            result = main(
                [
                    "--execute-demo",
                    "--confirmation",
                    "DEMO_ONLY",
                ]
            )

        self.assertEqual(result, 0)
        execute.assert_called_once_with(
            item,
            "abc12345",
            execution_enabled=True,
        )


if __name__ == "__main__":
    unittest.main()
