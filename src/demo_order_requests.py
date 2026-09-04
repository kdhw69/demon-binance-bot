import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NewAlgoOrderAlgoTypeEnum,
    NewAlgoOrderClosePositionEnum,
    NewAlgoOrderPriceProtectEnum,
    NewAlgoOrderSideEnum,
    NewAlgoOrderTypeEnum,
    NewAlgoOrderWorkingTypeEnum,
    NewOrderNewOrderRespTypeEnum,
    NewOrderReduceOnlyEnum,
    NewOrderSideEnum,
    NewOrderTypeEnum,
)

from .config import SYMBOLS
from .execution_engine import ExecutionPreview


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,8}$")


@dataclass(frozen=True)
class DemoOrderRequests:
    entry: Dict[str, Any]
    stop_loss: Dict[str, Any]
    take_profit: Dict[str, Any]


def _client_id(symbol: str, role: str, token: str) -> str:
    if not _TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Order token must contain 1 to 8 safe characters.")

    client_id = f"demon-{symbol.lower()}-{role}-{token}"
    if len(client_id) > 36:
        raise ValueError("Generated client order id is too long.")
    return client_id


def _validate_preview(preview: ExecutionPreview) -> None:
    if preview.symbol not in SYMBOLS:
        raise ValueError("Execution preview symbol is not permitted.")
    if preview.side not in {"BUY", "SELL"}:
        raise ValueError("Execution preview side must be BUY or SELL.")
    if preview.quantity <= 0:
        raise ValueError("Execution preview quantity must be positive.")
    if (
        preview.signal_time.tzinfo is None
        or preview.signal_time.utcoffset() is None
    ):
        raise ValueError(
            "Execution preview signal time must be timezone-aware."
        )

    if preview.side == "BUY":
        valid_prices = (
            preview.stop_loss
            < preview.entry_price
            < preview.take_profit
        )
    else:
        valid_prices = (
            preview.take_profit
            < preview.entry_price
            < preview.stop_loss
        )

    if not valid_prices:
        raise ValueError("Execution preview exit prices are invalid.")


def build_emergency_close_request(
    preview: ExecutionPreview,
    executed_quantity: Decimal,
    token: str,
) -> Dict[str, Any]:
    _validate_preview(preview)
    if not isinstance(executed_quantity, Decimal):
        raise TypeError("Executed quantity must be a Decimal.")
    if executed_quantity <= 0:
        raise ValueError("Executed quantity must be positive.")

    closing_side = (
        NewOrderSideEnum.SELL
        if preview.side == "BUY"
        else NewOrderSideEnum.BUY
    )
    return {
        "symbol": preview.symbol,
        "side": closing_side,
        "type": NewOrderTypeEnum.MARKET,
        "position_side": "BOTH",
        "reduce_only": NewOrderReduceOnlyEnum.TRUE,
        "quantity": float(executed_quantity),
        "new_client_order_id": _client_id(
            preview.symbol,
            "close",
            token,
        ),
        "new_order_resp_type": NewOrderNewOrderRespTypeEnum.RESULT,
    }


def build_demo_order_requests(
    preview: ExecutionPreview,
    token: str,
) -> DemoOrderRequests:
    _validate_preview(preview)

    entry_side = (
        NewOrderSideEnum.BUY
        if preview.side == "BUY"
        else NewOrderSideEnum.SELL
    )
    closing_side = (
        NewAlgoOrderSideEnum.SELL
        if preview.side == "BUY"
        else NewAlgoOrderSideEnum.BUY
    )

    entry = {
        "symbol": preview.symbol,
        "side": entry_side,
        "type": NewOrderTypeEnum.MARKET,
        "position_side": "BOTH",
        "quantity": float(preview.quantity),
        "new_client_order_id": _client_id(
            preview.symbol,
            "entry",
            token,
        ),
        "new_order_resp_type": NewOrderNewOrderRespTypeEnum.RESULT,
    }

    shared_protection = {
        "algo_type": NewAlgoOrderAlgoTypeEnum.CONDITIONAL,
        "symbol": preview.symbol,
        "side": closing_side,
        "position_side": "BOTH",
        "working_type": NewAlgoOrderWorkingTypeEnum.MARK_PRICE,
        "close_position": NewAlgoOrderClosePositionEnum.TRUE,
        "price_protect": NewAlgoOrderPriceProtectEnum.FALSE,
    }

    stop_loss = {
        **shared_protection,
        "type": NewAlgoOrderTypeEnum.STOP_MARKET,
        "trigger_price": float(preview.stop_loss),
        "client_algo_id": _client_id(
            preview.symbol,
            "stop",
            token,
        ),
    }

    take_profit = {
        **shared_protection,
        "type": NewAlgoOrderTypeEnum.TAKE_PROFIT_MARKET,
        "trigger_price": float(preview.take_profit),
        "client_algo_id": _client_id(
            preview.symbol,
            "take",
            token,
        ),
    }

    return DemoOrderRequests(
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )