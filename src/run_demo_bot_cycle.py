import argparse
import fcntl
import os
import secrets
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Sequence

from .demo_execution_service import execute_demo_preview
from .demo_trade_monitor import monitor_demo_trades
from .execution_engine import run_dry_run_cycle


_EXECUTION_ENV = "DEMON_DEMO_EXECUTION_ENABLED"
_EXECUTION_VALUE = "YES"
_CONFIRMATION = "DEMO_ONLY"
_LOCK_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "demo_bot_cycle.lock"
)


@contextmanager
def _execution_lock():
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = _LOCK_PATH.open("a+")
    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        handle.close()
        raise

    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one guarded Binance Futures Demo bot cycle."
        )
    )
    parser.add_argument(
        "--execute-demo",
        action="store_true",
        help="Allow Binance Futures Demo order submission.",
    )
    parser.add_argument(
        "--confirmation",
        default="",
        help="Required confirmation phrase for demo orders.",
    )
    return parser


def _print_dry_run(result) -> None:
    print("DRY RUN: no orders will be submitted.")
    if not result.allowed:
        for reason in result.reasons:
            print(f"BLOCKED: {reason}")
        return
    if not result.previews:
        print("No approved trade plans.")
        return
    for preview in result.previews:
        print(
            f"{preview.symbol}: {preview.side} preview | "
            f"quantity: {preview.quantity:f} | "
            f"signal UTC: {preview.signal_time.isoformat()} | "
            f"entry: {preview.entry_price:f} | "
            f"stop: {preview.stop_loss:f} | "
            f"take profit: {preview.take_profit:f}"
        )


def _execution_gate_is_open(args) -> bool:
    return (
        args.execute_demo
        and args.confirmation == _CONFIRMATION
        and os.getenv(_EXECUTION_ENV) == _EXECUTION_VALUE
    )


def _run_cycle(args) -> int:
    if args.execute_demo:
        monitor_report = monitor_demo_trades()
        if monitor_report.issues:
            print("Demo execution blocked by trade monitoring.")
            for issue in monitor_report.issues:
                print(f"BLOCKED: {issue}")
            return 1
        for trade_id in monitor_report.closed_trade_ids:
            print(f"Settled local trade: {trade_id}")

    dry_run = run_dry_run_cycle()
    if not args.execute_demo:
        _print_dry_run(dry_run)
        return 0 if dry_run.allowed else 1

    if not dry_run.allowed:
        print("Demo execution blocked by risk guard.")
        for reason in dry_run.reasons:
            print(f"BLOCKED: {reason}")
        return 1
    if not dry_run.previews:
        print("No approved trade plans.")
        return 0

    for preview in dry_run.previews:
        token = secrets.token_hex(4)
        try:
            result = execute_demo_preview(
                preview,
                token,
                execution_enabled=True,
            )
        except Exception:
            print(
                f"{preview.symbol}: demo execution failed safely."
            )
            return 1
        print(
            f"{result.symbol}: demo position protected | "
            f"trade id: {result.trade_id} | "
            f"entry order: {result.entry_order_id} | "
            f"stop algo: {result.stop_algo_id} | "
            f"take-profit algo: {result.take_profit_algo_id}"
        )

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)

    if args.execute_demo and not _execution_gate_is_open(args):
        print(
            "Demo execution blocked: explicit CLI confirmation "
            "and environment opt-in are both required."
        )
        return 2

    if not args.execute_demo:
        return _run_cycle(args)

    try:
        with _execution_lock():
            return _run_cycle(args)
    except BlockingIOError:
        print(
            "Demo execution blocked: another cycle is running."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
