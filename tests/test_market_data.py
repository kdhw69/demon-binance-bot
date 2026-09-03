import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    KlineCandlestickDataIntervalEnum,
)

from src.market_data import _get_closed_candles


class MarketDataTests(unittest.TestCase):
    def test_requests_confirmed_four_hour_interval(self):
        interval_ms = 4 * 60 * 60 * 1000
        first_open = int(
            (datetime.now(timezone.utc) - timedelta(days=100)).timestamp() * 1000
        )

        raw_candles = []
        for index in range(251):
            open_time = first_open + index * interval_ms
            close_time = open_time + interval_ms - 1
            raw_candles.append(
                [
                    open_time,
                    "100",
                    "101",
                    "99",
                    "100.5",
                    "1",
                    close_time,
                ]
            )

        response = Mock()
        response.data.return_value = raw_candles

        client = Mock()
        client.rest_api.kline_candlestick_data.return_value = response

        candles = _get_closed_candles(client, "BTCUSDT")

        client.rest_api.kline_candlestick_data.assert_called_once_with(
            symbol="BTCUSDT",
            interval=KlineCandlestickDataIntervalEnum.INTERVAL_4h,
            limit=251,
        )
        self.assertEqual(len(candles), 251)


if __name__ == "__main__":
    unittest.main()
    