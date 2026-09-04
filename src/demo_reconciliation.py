from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .binance_client import create_client
from .trade_store import TradeStore


@dataclass(frozen=True)
class ReconciliationReport:
    safe: bool
    issues: tuple[str, ...]
    position_count: int
    algo_order_count: int


def _response_list(response, operation: str) -> list:
    status = getattr(response, "status", None)
    if not isinstance(status, int) or not 200 <= status < 300:
        raise RuntimeError(f"{operation} was not accepted.")
    data_method = getattr(response, "data", None)
    if not callable(data_method):
        raise RuntimeError(f"{operation} response data is unavailable.")
    data = data_method()
    if not isinstance(data, list):
        raise RuntimeError(f"{operation} response must be a list.")
    return data


def _active_positions(positions: Iterable) -> dict[str, object]:
    active = {}
    for position in positions:
        symbol = getattr(position, "symbol", None)
        amount_text = getattr(position, "position_amt", None)
        if not symbol or amount_text is None:
            raise RuntimeError("Binance position data is incomplete.")
        amount = Decimal(str(amount_text))
        if amount == 0:
            continue
        if symbol in active:
            raise RuntimeError(
                f"Duplicate Binance position for {symbol}."
            )
        active[symbol] = position
    return active


def _algo_orders_by_id(algo_orders: Iterable) -> dict[int, object]:
    indexed = {}
    for order in algo_orders:
        algo_id = getattr(order, "algo_id", None)
        if (
            isinstance(algo_id, bool)
            or not isinstance(algo_id, int)
            or algo_id <= 0
        ):
            raise RuntimeError("Binance algo order id is invalid.")
        if algo_id in indexed:
            raise RuntimeError(
                f"Duplicate Binance algo order id {algo_id}."
            )
        indexed[algo_id] = order
    return indexed


def _check_protection(
    trade: dict,
    order,
    role: str,
    expected_type: str,
    expected_side: str,
    expected_trigger: Decimal,
    issues: list[str],
) -> None:
    if order is None:
        issues.append(
            f"{trade['symbol']}: {role} protection is missing."
        )
        return

    expected_client_id = trade[f"{role}_client_algo_id"]
    if getattr(order, "client_algo_id", None) != expected_client_id:
        issues.append(
            f"{trade['symbol']}: {role} client id differs."
        )
    if getattr(order, "order_type", None) != expected_type:
        issues.append(
            f"{trade['symbol']}: {role} order type differs."
        )
    if getattr(order, "side", None) != expected_side:
        issues.append(
            f"{trade['symbol']}: {role} side differs."
        )
    if getattr(order, "position_side", None) != "BOTH":
        issues.append(
            f"{trade['symbol']}: {role} position side differs."
        )
    if getattr(order, "close_position", None) is not True:
        issues.append(
            f"{trade['symbol']}: {role} is not close-position."
        )

    trigger_text = getattr(order, "trigger_price", None)
    if trigger_text is None:
        issues.append(
            f"{trade['symbol']}: {role} trigger price is missing."
        )
    elif Decimal(str(trigger_text)) != expected_trigger:
        issues.append(
            f"{trade['symbol']}: {role} trigger price differs."
        )


def evaluate_reconciliation(
    local_active_trades: list[dict],
    positions: list,
    algo_orders: list,
) -> ReconciliationReport:
    issues = []
    position_map = _active_positions(positions)
    algo_map = _algo_orders_by_id(algo_orders)

    open_trades = [
        trade
        for trade in local_active_trades
        if trade["status"] == "OPEN"
    ]
    planned_trades = [
        trade
        for trade in local_active_trades
        if trade["status"] == "PLANNED"
    ]

    for trade in planned_trades:
        client_id = trade.get("entry_client_order_id")
        detail = client_id or "missing client id"
        issues.append(
            f"{trade['symbol']}: PLANNED trade requires "
            f"entry reconciliation ({detail})."
        )

    local_open_by_symbol = {}
    referenced_algo_ids = set()
    for trade in open_trades:
        symbol = trade["symbol"]
        if symbol in local_open_by_symbol:
            issues.append(
                f"{symbol}: duplicate local OPEN trades."
            )
            continue
        local_open_by_symbol[symbol] = trade

        position = position_map.get(symbol)
        if position is None:
            issues.append(
                f"{symbol}: local OPEN trade has no Binance position."
            )
        else:
            amount = Decimal(str(position.position_amt))
            expected_side = "BUY" if amount > 0 else "SELL"
            if trade["side"] != expected_side:
                issues.append(
                    f"{symbol}: Binance position direction differs."
                )

        closing_side = "SELL" if trade["side"] == "BUY" else "BUY"

        stop_id = trade.get("stop_algo_id")
        take_id = trade.get("take_profit_algo_id")
        if isinstance(stop_id, int):
            referenced_algo_ids.add(stop_id)
        if isinstance(take_id, int):
            referenced_algo_ids.add(take_id)

        _check_protection(
            trade,
            algo_map.get(stop_id),
            "stop",
            "STOP_MARKET",
            closing_side,
            trade["stop_loss_price"],
            issues,
        )
        _check_protection(
            trade,
            algo_map.get(take_id),
            "take_profit",
            "TAKE_PROFIT_MARKET",
            closing_side,
            trade["take_profit_price"],
            issues,
        )

    for symbol in position_map:
        if symbol not in local_open_by_symbol:
            issues.append(
                f"{symbol}: Binance position has no local OPEN trade."
            )

    for algo_id, order in algo_map.items():
        client_id = getattr(order, "client_algo_id", "") or ""
        if (
            client_id.startswith("demon-")
            and algo_id not in referenced_algo_ids
        ):
            issues.append(
                f"{getattr(order, 'symbol', 'UNKNOWN')}: "
                f"untracked bot protection order {algo_id}."
            )

    return ReconciliationReport(
        safe=not issues,
        issues=tuple(issues),
        position_count=len(position_map),
        algo_order_count=len(algo_map),
    )


def check_demo_reconciliation(
    database_path=None,
    client=None,
) -> ReconciliationReport:
    api_client = create_client() if client is None else client
    positions = _response_list(
        api_client.rest_api.position_information_v3(),
        "Position query",
    )
    algo_orders = _response_list(
        api_client.rest_api.current_all_algo_open_orders(
            algo_type="CONDITIONAL"
        ),
        "Algo-order query",
    )

    store = TradeStore(database_path)
    try:
        active_trades = store.read_active_trades()
    finally:
        store.close()

    return evaluate_reconciliation(
        active_trades,
        positions,
        algo_orders,
    )
