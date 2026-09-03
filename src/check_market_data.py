from .market_data import get_closed_candles_for_symbols


def main() -> int:
    try:
        candles_by_symbol = get_closed_candles_for_symbols()
    except Exception:
        print("Binance Futures Demo market data retrieval failed.")
        return 1

    for symbol, candles in candles_by_symbol.items():
        latest_candle = candles[-1]
        print(f"{symbol}")
        print(f"Number of closed candles: {len(candles)}")
        print(f"Latest closed candle UTC time: {latest_candle.close_time.isoformat()}")
        print(f"Latest closing price: {latest_candle.close_price:f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
