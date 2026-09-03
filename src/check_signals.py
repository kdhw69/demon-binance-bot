from .signal_engine import get_latest_signals


def main() -> int:
    try:
        signals = get_latest_signals()
    except Exception:
        print("Binance Futures Demo signal check failed.")
        return 1

    for signal in signals.values():
        print(
            f"{signal.symbol}: {signal.direction} | "
            f"candle close UTC: {signal.candle_close_time.isoformat()} | "
            f"close: {signal.close_price:f} | "
            f"EMA 200: {signal.ema:f} | "
            f"Donchian high: {signal.donchian_high:f} | "
            f"Donchian low: {signal.donchian_low:f} | "
            f"ATR 14: {signal.atr:f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
