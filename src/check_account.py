from decimal import Decimal

from .binance_client import create_client


def main() -> int:
    try:
        client = create_client()
        account = client.rest_api.account_information_v3().data()

        wallet_balance = Decimal(account.total_wallet_balance)
        available_balance = Decimal(account.available_balance)
        unrealized_profit = Decimal(account.total_unrealized_profit)
        open_positions = sum(
            Decimal(position.position_amt) != Decimal("0")
            for position in (account.positions or [])
        )
    except Exception:
        print("Binance Futures Demo API account summary failed.")
        return 1

    print(f"Total wallet balance in USDT: {wallet_balance:f}")
    print(f"Available balance in USDT: {available_balance:f}")
    print(f"Total unrealized profit or loss in USDT: {unrealized_profit:f}")
    print(f"Number of currently open positions: {open_positions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
