from .risk_manager import get_latest_risk_plans


def main() -> int:
    try:
        plans = get_latest_risk_plans()
    except Exception:
        print("Binance Futures Demo risk-plan check failed.")
        return 1

    for symbol, plan in plans.items():
        if plan is None:
            print(f"{symbol}: NO_SIGNAL")
            continue
        print(
            f"{symbol}: {plan.direction} approved | "
            f"quantity: {plan.quantity:f} | entry: {plan.entry_price:f} | "
            f"stop loss: {plan.stop_loss:f} | take profit: {plan.take_profit:f} | "
            f"risk: {plan.risk_amount:f} | margin: {plan.margin_used:f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
