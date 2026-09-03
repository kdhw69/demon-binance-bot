import os
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    TestOrderSideEnum,
    TestOrderTypeEnum,
)

from .binance_client import create_client
from .config import SYMBOLS
from .exchange_rules import TradingRules, get_exchange_rules

_DEMO_BASE_URL = "https://demo-fapi.binance.com"
_ALLOWED_SIDES = {
    "BUY": TestOrderSideEnum.BUY,
    "SELL": TestOrderSideEnum.SELL,
}


def _round_quantity_up(quantity: Decimal, step_size: Decimal) -> Decimal:
    steps = (quantity / step_size).to_integral_value(rounding=ROUND_CEILING)
    return steps * step_size


def _current_price(client, symbol: str) -> Decimal:
    ticker = client.rest_api.symbol_price_ticker(symbol=symbol).data()
    price_data = ticker.actual_instance
    price = getattr(price_data, "price", None)
    if price is None:
        raise ValueError(f"Current market price is missing for {symbol}.")
    current_price = Decimal(str(price))
    if current_price <= 0:
        raise ValueError(f"Current market price is invalid for {symbol}.")
    return current_price


def _test_quantity(price: Decimal, rules: TradingRules) -> Decimal:
    notional_quantity = rules.minimum_notional_value / price
    return _round_quantity_up(
        max(rules.minimum_order_quantity, notional_quantity),
        rules.quantity_step_size,
    )


def submit_test_orders(side: str = "BUY") -> Dict[str, bool]:
    normalized_side = side.upper()
    if normalized_side not in _ALLOWED_SIDES:
        raise ValueError("Order side must be BUY or SELL.")
    load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
    if os.getenv("BINANCE_BASE_URL") != _DEMO_BASE_URL:
        raise ValueError("BINANCE_BASE_URL must target the Binance Futures Demo API.")

    client = create_client()
    rules_by_symbol = get_exchange_rules(client)
    results = {}
    for symbol in SYMBOLS:
        rules = rules_by_symbol[symbol]
        quantity = _test_quantity(_current_price(client, symbol), rules)
        response = client.rest_api.test_order(
            symbol=symbol,
            side=_ALLOWED_SIDES[normalized_side],
            type=TestOrderTypeEnum.MARKET,
            quantity=str(quantity),
        )
        if not 200 <= response.status < 300:
            raise ValueError(f"Test order was not accepted for {symbol}.")
        results[symbol] = True
    return results
