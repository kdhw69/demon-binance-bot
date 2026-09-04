from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from .binance_client import create_client
from .demo_order_requests import (
    build_demo_order_requests,
    build_emergency_close_request,
)
from .demo_reconciliation import (
    ReconciliationReport,
    check_demo_reconciliation,
)
from .execution_engine import ExecutionPreview
from .risk_guard import GuardDecision, check_live_guard
from .trade_store import TradeStore


@dataclass(frozen=True)
class DemoExecutionResult:
    trade_id: int
    symbol: str
    entry_order_id: int
    stop_algo_id: int
    take_profit_algo_id: int
    executed_quantity: Decimal


class AmbiguousEntryStateError(RuntimeError):
    pass


class EmergencyCleanupError(RuntimeError):
    pass


def _require_success(response, operation: str) -> None:
    status = getattr(response, "status", None)
    if not isinstance(status, int) or not 200 <= status < 300:
        raise RuntimeError(f"{operation} was not accepted.")


def _response_data(response, operation: str):
    _require_success(response, operation)
    data_method = getattr(response, "data", None)
    if not callable(data_method):
        raise RuntimeError(f"{operation} response data is unavailable.")
    data = data_method()
    if data is None:
        raise RuntimeError(f"{operation} response data is unavailable.")
    return data


def _positive_integer(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{field} is missing or invalid.")
    return value


def _required_text(value, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{field} is missing or invalid.")
    return value


def _filled_entry_data(response):
    try:
        data = _response_data(response, "Entry order")
        status = _required_text(
            getattr(data, "status", None),
            "Entry order status",
        )
        quantity_text = getattr(data, "executed_qty", None)
        if quantity_text is None:
            raise RuntimeError(
                "Executed entry quantity is unavailable."
            )
        quantity = Decimal(str(quantity_text))
    except Exception as error:
        raise AmbiguousEntryStateError(
            "Entry order response could not be reconciled."
        ) from error

    if status != "FILLED" or quantity <= 0:
        raise AmbiguousEntryStateError(
            "Entry order is not confirmed as fully filled."
        )
    return data, quantity


def _entry_identifiers(data) -> tuple[int, str]:
    order_id = _positive_integer(
        getattr(data, "order_id", None),
        "Entry order id",
    )
    client_order_id = _required_text(
        getattr(data, "client_order_id", None),
        "Entry client order id",
    )
    return order_id, client_order_id


def _algo_details(response, role: str) -> tuple[int, str]:
    data = _response_data(response, f"{role} order")
    algo_id = _positive_integer(
        getattr(data, "algo_id", None),
        f"{role} algo id",
    )
    client_algo_id = _required_text(
        getattr(data, "client_algo_id", None),
        f"{role} client algo id",
    )
    return algo_id, client_algo_id


def _recover_entry_response(client, request: dict):
    try:
        return client.rest_api.query_order(
            symbol=request["symbol"],
            orig_client_order_id=request["new_client_order_id"],
        )
    except Exception as error:
        raise AmbiguousEntryStateError(
            "Entry submission result could not be reconciled."
        ) from error


def _cancel_symbol_protection(client, symbol: str) -> None:
    response = client.rest_api.cancel_all_algo_open_orders(
        symbol=symbol,
    )
    _require_success(response, "Protection-order cancellation")


def _emergency_close(
    client,
    preview: ExecutionPreview,
    executed_quantity: Decimal,
    token: str,
) -> None:
    request = build_emergency_close_request(
        preview,
        executed_quantity,
        token,
    )
    response = client.rest_api.new_order(**request)
    _filled_entry_data(response)


def execute_demo_preview(
    preview: ExecutionPreview,
    token: str,
    database_path=None,
    *,
    execution_enabled: bool = False,
    client=None,
    reconciliation_checker: Callable[
        [Optional[object], Optional[object]],
        ReconciliationReport,
    ] = check_demo_reconciliation,
    guard_checker: Callable[[Optional[object]], GuardDecision] = (
        check_live_guard
    ),
) -> DemoExecutionResult:
    if execution_enabled is not True:
        raise PermissionError(
            "Demo order execution requires explicit confirmation."
        )

    requests = build_demo_order_requests(preview, token)
    reconciliation = reconciliation_checker(
        database_path,
        client,
    )
    if not reconciliation.safe:
        raise RuntimeError(
            "Reconciliation blocked demo execution: "
            + "; ".join(reconciliation.issues)
        )

    decision = guard_checker(database_path)
    if not decision.allowed:
        raise RuntimeError(
            "Risk guard blocked demo execution: "
            + "; ".join(decision.reasons)
        )

    api_client = create_client() if client is None else client
    store = TradeStore(database_path)
    trade_id = store.record_planned_trade(
        preview.symbol,
        preview.side,
        preview.quantity,
        preview.entry_price,
        preview.stop_loss,
        preview.take_profit,
        preview.planned_risk,
        preview.margin_used,
        requests.entry["new_client_order_id"],
        requests.stop_loss["client_algo_id"],
        requests.take_profit["client_algo_id"],
    )

    executed_quantity = None
    try:
        try:
            entry_response = api_client.rest_api.new_order(
                **requests.entry
            )
        except Exception:
            entry_response = _recover_entry_response(
                api_client,
                requests.entry,
            )

        entry_data, executed_quantity = _filled_entry_data(
            entry_response
        )
        (
            entry_order_id,
            entry_client_order_id,
        ) = _entry_identifiers(entry_data)

        stop_response = api_client.rest_api.new_algo_order(
            **requests.stop_loss
        )
        stop_algo_id, stop_client_algo_id = _algo_details(
            stop_response,
            "Stop-loss",
        )

        take_response = api_client.rest_api.new_algo_order(
            **requests.take_profit
        )
        take_profit_algo_id, take_profit_client_algo_id = (
            _algo_details(take_response, "Take-profit")
        )

        store.mark_open_with_exchange_orders(
            trade_id,
            entry_order_id,
            entry_client_order_id,
            stop_algo_id,
            stop_client_algo_id,
            take_profit_algo_id,
            take_profit_client_algo_id,
        )
        return DemoExecutionResult(
            trade_id=trade_id,
            symbol=preview.symbol,
            entry_order_id=entry_order_id,
            stop_algo_id=stop_algo_id,
            take_profit_algo_id=take_profit_algo_id,
            executed_quantity=executed_quantity,
        )
    except AmbiguousEntryStateError:
        raise
    except Exception as original_error:
        if executed_quantity is None:
            store.mark_failed(trade_id)
            raise

        cleanup_errors = []
        try:
            _cancel_symbol_protection(
                api_client,
                preview.symbol,
            )
        except Exception as error:
            cleanup_errors.append(error)

        try:
            _emergency_close(
                api_client,
                preview,
                executed_quantity,
                token,
            )
        except Exception as error:
            cleanup_errors.append(error)

        if cleanup_errors:
            raise EmergencyCleanupError(
                "Automatic cleanup was incomplete; "
                "manual reconciliation is required."
            ) from original_error

        store.mark_failed(trade_id)
        raise RuntimeError(
            "Protection setup failed; the demo position was closed."
        ) from original_error
    finally:
        store.close()
