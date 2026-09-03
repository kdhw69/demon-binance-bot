import sys

from .config import SYMBOLS
from .order_service import submit_test_orders


def main() -> int:
    side = sys.argv[1] if len(sys.argv) > 1 else "BUY"
    try:
        results = submit_test_orders(side)
    except Exception:
        print("Binance Futures Demo test-order validation failed.")
        return 1

    for symbol in SYMBOLS:
        print(f"{symbol}: test order accepted: {results[symbol]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
