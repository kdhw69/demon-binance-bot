import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from src.historical_data import (
    HistoricalDataDownloader,
    CandleRecord,
    INTERVAL_MS,
    parse_candle,
    validate_candles,
)


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self.payload


def raw_candle(open_time, close_time=None):
    close_time = open_time + INTERVAL_MS - 1 if close_time is None else close_time
    return [open_time, "1.00000001", "2.00000002", "0.50000005", "1.500000015", "10.00000009", close_time]


class HistoricalDataTests(unittest.TestCase):
    def test_kline_pagination(self):
        first_page = [raw_candle(index * INTERVAL_MS) for index in range(1500)]
        second_page = [raw_candle(1500 * INTERVAL_MS)]
        session = Mock()
        session.get.side_effect = [FakeResponse(first_page), FakeResponse(second_page)]
        downloader = HistoricalDataDownloader(
            session=session,
            now=lambda: datetime.fromtimestamp((1501 * INTERVAL_MS) / 1000, timezone.utc),
            sleep=lambda _: None,
        )
        candles = downloader.fetch_candles("BTCUSDT", start_ms=0, end_ms=1500 * INTERVAL_MS)
        self.assertEqual(len(candles), 1501)
        self.assertEqual(session.get.call_count, 2)

    def test_retry_limit(self):
        session = Mock()
        session.get.return_value = FakeResponse([], status_code=503)
        sleeps = []
        downloader = HistoricalDataDownloader(session=session, sleep=sleeps.append, max_retries=2)
        with self.assertRaisesRegex(RuntimeError, "retry limit"):
            downloader._get_json("/fapi/v1/klines", {})
        self.assertEqual(sleeps, [1, 2])
        self.assertEqual(session.get.call_count, 3)

    def test_duplicate_detection(self):
        candles = [
            parse_candle(raw_candle(0), INTERVAL_MS * 3),
            parse_candle(raw_candle(0), INTERVAL_MS * 3),
        ]
        with self.assertRaisesRegex(ValueError, "duplicated"):
            validate_candles(candles)

    def test_gap_detection(self):
        candles = [
            parse_candle(raw_candle(0), INTERVAL_MS * 4),
            parse_candle(raw_candle(2 * INTERVAL_MS), INTERVAL_MS * 4),
        ]
        result = validate_candles(candles)
        self.assertEqual(len(result.gaps), 1)

    def test_incomplete_candle_is_removed(self):
        complete = parse_candle(raw_candle(0), INTERVAL_MS)
        incomplete = parse_candle(raw_candle(INTERVAL_MS), INTERVAL_MS)
        self.assertIsNotNone(complete)
        self.assertIsNone(incomplete)

    def test_malformed_candle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Malformed"):
            parse_candle([0, "bad"], INTERVAL_MS)


if __name__ == "__main__":
    unittest.main()
