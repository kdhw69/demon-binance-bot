from .binance_client import create_client


def main() -> int:
    try:
        client = create_client()
        client.rest_api.account_information_v3().data()
    except Exception:
        print("Binance Futures Demo API connection failed.")
        return 1

    print("Binance Futures Demo API connection successful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
