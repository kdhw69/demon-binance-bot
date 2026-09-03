from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable

from .binance_client import create_client
from .config import SYMBOLS


@dataclass(frozen=True)
class TradingRules:
    symbol: str
    status: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    minimum_order_quantity: Decimal
    minimum_notional_value: Decimal


def _filter_by_type(filters: Iterable, filter_type: str):
    return next(
        (item for item in filters if item.filter_type == filter_type),
        None,
    )


def _decimal_filter_value(filter_item, attribute: str, symbol: str, filter_type: str) -> Decimal:
    value = getattr(filter_item, attribute, None)
    if value is None:
        raise ValueError(f"Required {filter_type} field is missing for {symbol}.")
    return Decimal(str(value))


def _extract_rules(symbol_info) -> TradingRules:
    symbol = symbol_info.symbol
    if not symbol:
        raise ValueError("Exchange information contains a symbol without a name.")
    if not symbol_info.status:
        raise ValueError(f"Required status is missing for {symbol}.")
    if not symbol_info.filters:
        raise ValueError(f"Required filters are missing for {symbol}.")

    price_filter = _filter_by_type(symbol_info.filters, "PRICE_FILTER")
    lot_size_filter = _filter_by_type(symbol_info.filters, "LOT_SIZE")
    notional_filter = next(
        (
            item
            for item in symbol_info.filters
            if item.filter_type in {"MIN_NOTIONAL", "NOTIONAL"}
        ),
        None,
    )

    if price_filter is None:
        raise ValueError(f"Required PRICE_FILTER is missing for {symbol}.")
    if lot_size_filter is None:
        raise ValueError(f"Required LOT_SIZE is missing for {symbol}.")
    if notional_filter is None:
        raise ValueError(f"Required minimum notional filter is missing for {symbol}.")

    return TradingRules(
        symbol=symbol,
        status=symbol_info.status,
        price_tick_size=_decimal_filter_value(
            price_filter, "tick_size", symbol, "PRICE_FILTER"
        ),
        quantity_step_size=_decimal_filter_value(
            lot_size_filter, "step_size", symbol, "LOT_SIZE"
        ),
        minimum_order_quantity=_decimal_filter_value(
            lot_size_filter, "min_qty", symbol, "LOT_SIZE"
        ),
        minimum_notional_value=_decimal_filter_value(
            notional_filter, "notional", symbol, "minimum notional filter"
        ),
    )


def get_exchange_rules(client=None) -> Dict[str, TradingRules]:
    if client is None:
        client = create_client()
    exchange_info = client.rest_api.exchange_information().data()
    symbols_by_name = {symbol.symbol: symbol for symbol in (exchange_info.symbols or [])}

    rules = {}
    for symbol in SYMBOLS:
        symbol_info = symbols_by_name.get(symbol)
        if symbol_info is None:
            raise ValueError(f"Required symbol {symbol} is missing from exchange information.")
        rules[symbol] = _extract_rules(symbol_info)
    return rules
