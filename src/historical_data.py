import csv
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import requests


PUBLIC_BASE_URL = "https://fapi.binance.com"
INTERVAL_MS = 2 * 60 * 60 * 1000
CANDLE_LIMIT = 1500
FUNDING_LIMIT = 1000
START_TIME_MS = 1640995200000
MAX_RETRIES = 3
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "historical"


@dataclass(frozen=True)
class CandleRecord:
    open_time_ms: int
    close_time_ms: int
    open_time_utc: str
    close_time_utc: str
    open: str
    high: str
    low: str
    close: str
    volume: str


@dataclass(frozen=True)
class FundingRecord:
    funding_time_ms: int
    funding_time_utc: str
    funding_rate: str


@dataclass(frozen=True)
class ValidationResult:
    first_timestamp_utc: str
    last_timestamp_utc: str
    gaps: List[str]


def utc_timestamp(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _decimal_string(value, field: str) -> str:
    if isinstance(value, float):
        raise ValueError(f"Malformed {field} value.")
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Malformed {field} value.")


def _milliseconds(value, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Malformed {field} value.")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Malformed {field} value.")


def parse_candle(raw: Sequence, now_ms: int) -> Optional[CandleRecord]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 7:
        raise ValueError("Malformed candle row.")
    open_time_ms = _milliseconds(raw[0], "candle timestamp")
    close_time_ms = _milliseconds(raw[6], "candle close timestamp")
    for index, field in ((1, "open"), (2, "high"), (3, "low"), (4, "close"), (5, "volume")):
        _decimal_string(raw[index], field)
    if close_time_ms > now_ms:
        return None
    return CandleRecord(
        open_time_ms=open_time_ms,
        close_time_ms=close_time_ms,
        open_time_utc=utc_timestamp(open_time_ms),
        close_time_utc=utc_timestamp(close_time_ms),
        open=_decimal_string(raw[1], "open"),
        high=_decimal_string(raw[2], "high"),
        low=_decimal_string(raw[3], "low"),
        close=_decimal_string(raw[4], "close"),
        volume=_decimal_string(raw[5], "volume"),
    )


def parse_funding(raw: dict) -> FundingRecord:
    if not isinstance(raw, dict):
        raise ValueError("Malformed funding-rate row.")
    funding_time_ms = _milliseconds(raw.get("fundingTime"), "funding timestamp")
    funding_rate = _decimal_string(raw.get("fundingRate"), "funding rate")
    return FundingRecord(
        funding_time_ms=funding_time_ms,
        funding_time_utc=utc_timestamp(funding_time_ms),
        funding_rate=funding_rate,
    )


def validate_candles(candles: Sequence[CandleRecord]) -> ValidationResult:
    if not candles:
        raise ValueError("No candle data was returned.")
    gaps = []
    for current, following in zip(candles, candles[1:]):
        if following.open_time_ms <= current.open_time_ms:
            raise ValueError("Candle timestamps are unordered or duplicated.")
        difference = following.open_time_ms - current.open_time_ms
        if difference != INTERVAL_MS:
            gaps.append(
                f"{utc_timestamp(current.open_time_ms)} to {utc_timestamp(following.open_time_ms)}"
            )
    return ValidationResult(candles[0].open_time_utc, candles[-1].open_time_utc, gaps)


def validate_funding_rates(funding_rates: Sequence[FundingRecord]) -> ValidationResult:
    if not funding_rates:
        raise ValueError("No funding-rate data was returned.")
    for current, following in zip(funding_rates, funding_rates[1:]):
        if following.funding_time_ms <= current.funding_time_ms:
            raise ValueError("Funding-rate timestamps are unordered or duplicated.")
    return ValidationResult(
        funding_rates[0].funding_time_utc,
        funding_rates[-1].funding_time_utc,
        [],
    )


class HistoricalDataDownloader:
    def __init__(
        self,
        session=None,
        output_dir: Optional[Path] = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_retries: int = MAX_RETRIES,
        rate_delay: float = 0.1,
    ):
        self.session = session or requests.Session()
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self.sleep = sleep
        self.now = now
        self.max_retries = max_retries
        self.rate_delay = rate_delay

    def _get_json(self, path: str, params: dict):
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    PUBLIC_BASE_URL + path,
                    params=params,
                    timeout=30,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == self.max_retries:
                        raise RuntimeError("Temporary market-data failure retry limit reached.")
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2**attempt
                    self.sleep(delay)
                    continue
                response.raise_for_status()
                self.sleep(self.rate_delay)
                return response.json()
            except (requests.RequestException, ValueError) as error:
                if isinstance(error, ValueError) and not hasattr(error, "response"):
                    raise RuntimeError("Malformed market-data response.")
                if attempt == self.max_retries:
                    raise RuntimeError("Market-data request retry limit reached.")
                self.sleep(2**attempt)
        raise RuntimeError("Market-data request failed safely.")

    def fetch_candles(self, symbol: str, start_ms: int = START_TIME_MS, end_ms: Optional[int] = None) -> List[CandleRecord]:
        now_ms = int(self.now().astimezone(timezone.utc).timestamp() * 1000)
        latest_closed_open_ms = (now_ms // INTERVAL_MS) * INTERVAL_MS - INTERVAL_MS
        end_ms = latest_closed_open_ms + INTERVAL_MS - 1 if end_ms is None else end_ms
        records = []
        cursor = start_ms
        while cursor <= latest_closed_open_ms and cursor <= end_ms:
            rows = self._get_json(
                "/fapi/v1/klines",
                {"symbol": symbol, "interval": "2h", "startTime": cursor, "endTime": end_ms, "limit": CANDLE_LIMIT},
            )
            if not rows:
                break
            for row in rows:
                candle = parse_candle(row, now_ms)
                if candle and start_ms <= candle.open_time_ms <= latest_closed_open_ms and candle.open_time_ms <= end_ms:
                    records.append(candle)
            last_open = _milliseconds(rows[-1][0], "candle timestamp")
            if len(rows) < CANDLE_LIMIT or last_open >= latest_closed_open_ms:
                break
            cursor = last_open + INTERVAL_MS
        records.sort(key=lambda item: item.open_time_ms)
        validate_candles(records)
        return records

    def fetch_funding_rates(self, symbol: str, start_ms: int = START_TIME_MS, end_ms: Optional[int] = None) -> List[FundingRecord]:
        now_ms = int(self.now().astimezone(timezone.utc).timestamp() * 1000)
        latest_closed_open_ms = (now_ms // INTERVAL_MS) * INTERVAL_MS - INTERVAL_MS
        end_ms = latest_closed_open_ms + INTERVAL_MS - 1 if end_ms is None else end_ms
        records = []
        cursor = start_ms
        while cursor <= end_ms:
            rows = self._get_json(
                "/fapi/v1/fundingRate",
                {"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": FUNDING_LIMIT},
            )
            if not rows:
                break
            for row in rows:
                funding = parse_funding(row)
                if start_ms <= funding.funding_time_ms <= end_ms:
                    records.append(funding)
            last_time = _milliseconds(rows[-1].get("fundingTime"), "funding timestamp")
            if len(rows) < FUNDING_LIMIT or last_time >= end_ms:
                break
            cursor = last_time + 1
        records.sort(key=lambda item: item.funding_time_ms)
        validate_funding_rates(records)
        return records

    def download_symbol(self, symbol: str) -> Dict[str, ValidationResult]:
        candles = self.fetch_candles(symbol)
        funding_rates = self.fetch_funding_rates(symbol)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_candles(symbol, candles)
        self._write_funding_rates(symbol, funding_rates)
        candle_validation = validate_candles(candles)
        funding_validation = validate_funding_rates(funding_rates)
        return {"candles": candle_validation, "funding_rates": funding_validation}

    def _write_candles(self, symbol: str, candles: Sequence[CandleRecord]) -> None:
        path = self.output_dir / f"{symbol}_candles.csv"
        with path.open("w", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["open_time_utc", "close_time_utc", "open", "high", "low", "close", "volume"])
            writer.writerows(
                [record.open_time_utc, record.close_time_utc, record.open, record.high, record.low, record.close, record.volume]
                for record in candles
            )

    def _write_funding_rates(self, symbol: str, funding_rates: Sequence[FundingRecord]) -> None:
        path = self.output_dir / f"{symbol}_funding_rates.csv"
        with path.open("w", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["funding_time_utc", "funding_rate"])
            writer.writerows(
                [record.funding_time_utc, record.funding_rate]
                for record in funding_rates
            )


def download_all(symbols: Sequence[str], output_dir: Optional[Path] = None) -> Dict[str, Dict[str, ValidationResult]]:
    downloader = HistoricalDataDownloader(output_dir=output_dir)
    return {symbol: downloader.download_symbol(symbol) for symbol in symbols}
