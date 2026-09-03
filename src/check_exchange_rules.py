from .exchange_rules import get_exchange_rules


def main() -> int:
    try:
        rules_by_symbol = get_exchange_rules()
    except Exception:
        print("Binance Futures Demo exchange rules retrieval failed.")
        return 1

    for rules in rules_by_symbol.values():
        print(f"{rules.symbol}")
        print(f"Status: {rules.status}")
        print(f"Price tick size: {rules.price_tick_size:f}")
        print(f"Quantity step size: {rules.quantity_step_size:f}")
        print(f"Minimum order quantity: {rules.minimum_order_quantity:f}")
        print(f"Minimum notional value: {rules.minimum_notional_value:f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
