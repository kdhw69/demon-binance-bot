import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    ChangeMarginTypeMarginTypeEnum,
)

from .binance_client import create_client
from .config import LEVERAGE, MARGIN_MODE, SYMBOLS
from .exchange_rules import get_exchange_rules

_DEMO_BASE_URL = "https://demo-fapi.binance.com"


def _items(value) -> list:
    actual_instance = getattr(value, "actual_instance", None)
    if actual_instance is not None:
        value = actual_instance
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _verify_no_open_activity(client) -> None:
    positions = _items(client.rest_api.position_information_v3().data())
    for position in positions:
        position_amount = getattr(position, "position_amt", None)
        if position_amount is None:
            raise ValueError("Position amount is missing during preflight.")
        if Decimal(str(position_amount)) != Decimal("0"):
            raise ValueError("Open positions exist; configuration stopped safely.")

    open_orders = _items(client.rest_api.current_all_open_orders().data())
    if open_orders:
        raise ValueError("Open orders exist; configuration stopped safely.")


def _verify_position_mode(client) -> bool:
    mode = client.rest_api.get_current_position_mode().data()
    dual_side_position = getattr(mode, "dual_side_position", None)
    if dual_side_position is None:
        raise ValueError("Position mode is missing during verification.")
    return not dual_side_position


def _ensure_one_way_mode(client) -> None:
    if _verify_position_mode(client):
        return
    try:
        client.rest_api.change_position_mode(dual_side_position="false")
    except Exception:
        if not _verify_position_mode(client):
            raise
    if not _verify_position_mode(client):
        raise ValueError("One-way position mode could not be verified.")


def _symbol_configuration(client, symbol: str):
    configurations = _items(client.rest_api.symbol_configuration(symbol=symbol).data())
    configuration = next(
        (item for item in configurations if item.symbol == symbol),
        None,
    )
    if configuration is None:
        raise ValueError(f"Configuration is missing for {symbol}.")
    return configuration


def _verify_symbol_settings(client, symbol: str) -> None:
    configuration = _symbol_configuration(client, symbol)
    if configuration.margin_type != "ISOLATED":
        raise ValueError(f"Isolated margin could not be verified for {symbol}.")
    if configuration.leverage != LEVERAGE:
        raise ValueError(f"10x leverage could not be verified for {symbol}.")


def verify_demo_execution_settings(
    client,
    symbol: str,
) -> None:
    if symbol not in SYMBOLS:
        raise ValueError("Execution symbol is not permitted.")
    if not _verify_position_mode(client):
        raise ValueError(
            "One-way position mode is required for execution."
        )
    _verify_symbol_settings(client, symbol)


def _ensure_symbol_settings(client, symbol: str) -> None:
    configuration = _symbol_configuration(client, symbol)
    if configuration.margin_type is None or configuration.leverage is None:
        raise ValueError(f"Required configuration is missing for {symbol}.")

    if configuration.margin_type != "ISOLATED":
        try:
            client.rest_api.change_margin_type(
                symbol=symbol,
                margin_type=ChangeMarginTypeMarginTypeEnum.ISOLATED,
            )
        except Exception:
            configuration = _symbol_configuration(client, symbol)
            if configuration.margin_type != "ISOLATED":
                raise

    configuration = _symbol_configuration(client, symbol)
    if configuration.leverage != LEVERAGE:
        try:
            client.rest_api.change_initial_leverage(
                symbol=symbol,
                leverage=LEVERAGE,
            )
        except Exception:
            configuration = _symbol_configuration(client, symbol)
            if configuration.leverage != LEVERAGE:
                raise

    _verify_symbol_settings(client, symbol)


def configure_demo_account() -> dict[str, str]:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
    if os.getenv("BINANCE_BASE_URL") != _DEMO_BASE_URL:
        raise ValueError("BINANCE_BASE_URL must target the Binance Futures Demo API.")

    client = create_client()
    _verify_no_open_activity(client)
    rules_by_symbol = get_exchange_rules(client)
    if any(symbol not in rules_by_symbol for symbol in SYMBOLS):
        raise ValueError("Required exchange rules are missing.")

    _ensure_one_way_mode(client)
    for symbol in SYMBOLS:
        _ensure_symbol_settings(client, symbol)

    if not _verify_position_mode(client):
        raise ValueError("Final position mode verification failed.")
    for symbol in SYMBOLS:
        _verify_symbol_settings(client, symbol)

    return {symbol: "verified" for symbol in SYMBOLS}


def main() -> int:
    try:
        configure_demo_account()
    except Exception:
        print("Binance Futures Demo account configuration failed.")
        return 1

    for symbol in SYMBOLS:
        print(f"{symbol}: One-way position mode, Isolated margin mode, 10x leverage verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

