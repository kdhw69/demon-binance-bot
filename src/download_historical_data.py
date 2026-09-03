from .config import SYMBOLS
from .historical_data import (
    HistoricalDataDownloader,
    validate_candles,
    validate_funding_rates,
)


def main() -> int:
    try:
        downloader = HistoricalDataDownloader()
        for symbol in SYMBOLS:
            candles = downloader.fetch_candles(symbol)
            funding_rates = downloader.fetch_funding_rates(symbol)
            downloader.output_dir.mkdir(parents=True, exist_ok=True)
            downloader._write_candles(symbol, candles)
            downloader._write_funding_rates(symbol, funding_rates)
            candle_result = validate_candles(candles)
            funding_result = validate_funding_rates(funding_rates)
            gaps = candle_result.gaps or ["none"]
            print(
                f"{symbol} candles: records: {len(candles)}; "
                f"first UTC: {candle_result.first_timestamp_utc}; "
                f"last UTC: {candle_result.last_timestamp_utc}; "
                f"gaps: {', '.join(gaps)}"
            )
            print(
                f"{symbol} funding rates: records: {len(funding_rates)}; "
                f"first UTC: {funding_result.first_timestamp_utc}; "
                f"last UTC: {funding_result.last_timestamp_utc}; gaps: none"
            )
    except Exception:
        print("Historical market-data download failed safely.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
