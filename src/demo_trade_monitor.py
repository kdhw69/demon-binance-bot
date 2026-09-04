from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    GetIncomeHistoryIncomeTypeEnum,
)

from .binance_client import create_client
from .trade_store import TradeStore


@dataclass(frozen=True)
class MonitorReport:
    closed_trade_ids: tuple[int, ...]
    issues: tuple[str, ...]


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


def _response_list(response, operation: str) -> list:
    data = _response_data(response, operation)
    if not isinstance(data, list):
        raise RuntimeError(f"{operation} response must be a list.")
    return data


def _active_position_symbols(positions: Iterable) -> set[str]:
    symbols = set()
    for position in positions:
        symbol = getattr(position, "symbol", None)
        amount_text = getattr(position, "position_amt", None)
        if not symbol or amount_text is None:
            raise RuntimeError("Position data is incomplete.")
        if Decimal(str(amount_text)) != 0:
            symbols.add(symbol)
    return symbols


def _triggered_order_id(algo) -> int | None:
    actual_order_id = getattr(algo, "actual_order_id", None)
    actual_quantity = getattr(algo, "actual_qty", None)
    if actual_order_id in (None, ""):
        return None
    if actual_quantity in (None, ""):
        return None
    if Decimal(str(actual_quantity)) <= 0:
        return None
    order_id = int(actual_order_id)
    if order_id <= 0:
        raise RuntimeError("Triggered order id is invalid.")
    return order_id


def _trade_fills(api, symbol: str, order_id: int) -> list:
    return _response_list(
        api.account_trade_list(
            symbol=symbol,
            order_id=order_id,
        ),
        f"Trade-fill query for order {order_id}",
    )


def _validate_fill(fill, symbol: str, order_id: int) -> None:
    if getattr(fill, "symbol", None) != symbol:
        raise RuntimeError("Trade-fill symbol differs.")
    if getattr(fill, "order_id", None) != order_id:
        raise RuntimeError("Trade-fill order id differs.")
    required = (
        "price",
        "qty",
        "realized_pnl",
        "commission",
        "commission_asset",
        "time",
    )
    if any(getattr(fill, field, None) is None for field in required):
        raise RuntimeError("Trade-fill data is incomplete.")
    if fill.commission_asset != "USDT":
        raise RuntimeError(
            "Non-USDT commission requires manual reconciliation."
        )


def _settlement(
    symbol: str,
    entry_order_id: int,
    exit_order_id: int,
    entry_fills: list,
    exit_fills: list,
    funding_rows: list,
) -> tuple[Decimal, Decimal, datetime]:
    if not entry_fills or not exit_fills:
        raise RuntimeError("Required trade fills are missing.")

    for fill in entry_fills:
        _validate_fill(fill, symbol, entry_order_id)
    for fill in exit_fills:
        _validate_fill(fill, symbol, exit_order_id)

    exit_quantity = sum(
        (Decimal(str(fill.qty)) for fill in exit_fills),
        Decimal("0"),
    )
    if exit_quantity <= 0:
        raise RuntimeError("Exit fill quantity is invalid.")

    exit_notional = sum(
        (
            Decimal(str(fill.price)) * Decimal(str(fill.qty))
            for fill in exit_fills
        ),
        Decimal("0"),
    )
    exit_price = exit_notional / exit_quantity

    realized_pnl = sum(
        (
            Decimal(str(fill.realized_pnl))
            for fill in entry_fills + exit_fills
        ),
        Decimal("0"),
    )
    commissions = sum(
        (
            Decimal(str(fill.commission))
            for fill in entry_fills + exit_fills
        ),
        Decimal("0"),
    )

    funding = Decimal("0")
    for row in funding_rows:
        if getattr(row, "symbol", None) != symbol:
            raise RuntimeError("Funding symbol differs.")
        if getattr(row, "asset", None) != "USDT":
            raise RuntimeError(
                "Non-USDT funding requires manual reconciliation."
            )
        income = getattr(row, "income", None)
        if income is None:
            raise RuntimeError("Funding income is missing.")
        funding += Decimal(str(income))

    exit_time_ms = max(int(fill.time) for fill in exit_fills)
    exit_time = datetime.fromtimestamp(
        exit_time_ms / 1000,
        tz=timezone.utc,
    )
    net_pnl = realized_pnl - commissions + funding
    return exit_price, net_pnl, exit_time


def monitor_demo_trades(
    database_path=None,
    client=None,
) -> MonitorReport:
    api_client = create_client() if client is None else client
    api = api_client.rest_api
    positions = _response_list(
        api.position_information_v3(),
        "Position query",
    )
    active_position_symbols = _active_position_symbols(positions)

    store = TradeStore(database_path)
    closed_trade_ids = []
    issues = []
    try:
        active_trades = store.read_active_trades()
        for trade in active_trades:
            if trade["status"] == "PLANNED":
                issues.append(
                    f"{trade['symbol']}: PLANNED trade requires "
                    "manual reconciliation."
                )
                continue
            if trade["symbol"] in active_position_symbols:
                continue

            try:
                stop = _response_data(
                    api.query_algo_order(
                        algo_id=trade["stop_algo_id"]
                    ),
                    "Stop-loss algo query",
                )
                take_profit = _response_data(
                    api.query_algo_order(
                        algo_id=trade["take_profit_algo_id"]
                    ),
                    "Take-profit algo query",
                )
                triggered_ids = [
                    order_id
                    for order_id in (
                        _triggered_order_id(stop),
                        _triggered_order_id(take_profit),
                    )
                    if order_id is not None
                ]

                if len(triggered_ids) != 1:
                    raise RuntimeError(
                        "Exactly one triggered protection order "
                        "could not be identified."
                    )

                cancel_response = (
                    api.cancel_all_algo_open_orders(
                        symbol=trade["symbol"]
                    )
                )
                _require_success(
                    cancel_response,
                    "Remaining protection-order cancellation",
                )

                exit_order_id = triggered_ids[0]
                entry_fills = _trade_fills(
                    api,
                    trade["symbol"],
                    trade["entry_order_id"],
                )
                exit_fills = _trade_fills(
                    api,
                    trade["symbol"],
                    exit_order_id,
                )
                exit_time_ms = max(
                    int(fill.time)
                    for fill in exit_fills
                )
                entry_time_ms = int(
                    trade["entry_time"].timestamp() * 1000
                )
                funding_rows = _response_list(
                    api.get_income_history(
                        symbol=trade["symbol"],
                        income_type=(
                            GetIncomeHistoryIncomeTypeEnum.FUNDING_FEE
                        ),
                        start_time=entry_time_ms,
                        end_time=exit_time_ms,
                        limit=1000,
                    ),
                    "Funding query",
                )
                exit_price, net_pnl, exit_time = _settlement(
                    trade["symbol"],
                    trade["entry_order_id"],
                    exit_order_id,
                    entry_fills,
                    exit_fills,
                    funding_rows,
                )
                store.mark_closed(
                    trade["trade_id"],
                    exit_price,
                    net_pnl,
                    exit_time,
                )
                closed_trade_ids.append(trade["trade_id"])
            except Exception as error:
                issues.append(
                    f"{trade['symbol']}: {error}"
                )
    finally:
        store.close()

    return MonitorReport(
        closed_trade_ids=tuple(closed_trade_ids),
        issues=tuple(issues),
    )
