import os
import unittest
from unittest.mock import patch

from src.binance_client import create_client


class BinanceClientTests(unittest.TestCase):
    @patch("src.binance_client.DerivativesTradingUsdsFutures")
    @patch("src.binance_client.ConfigurationRestAPI")
    @patch("src.binance_client.load_dotenv")
    def test_demo_url_is_accepted(
        self,
        load_dotenv,
        configuration_class,
        client_class,
    ):
        environment = {
            "BINANCE_API_KEY": "test-key",
            "BINANCE_API_SECRET": "test-secret",
            "BINANCE_BASE_URL": "https://demo-fapi.binance.com",
        }

        with patch.dict(os.environ, environment, clear=True):
            result = create_client()

        configuration_class.assert_called_once_with(
            api_key="test-key",
            api_secret="test-secret",
            base_path="https://demo-fapi.binance.com",
        )
        client_class.assert_called_once_with(
            config_rest_api=configuration_class.return_value,
        )
        self.assertIs(result, client_class.return_value)

    @patch("src.binance_client.DerivativesTradingUsdsFutures")
    @patch("src.binance_client.ConfigurationRestAPI")
    @patch("src.binance_client.load_dotenv")
    def test_non_demo_url_is_rejected(
        self,
        load_dotenv,
        configuration_class,
        client_class,
    ):
        environment = {
            "BINANCE_API_KEY": "test-key",
            "BINANCE_API_SECRET": "test-secret",
            "BINANCE_BASE_URL": "https://fapi.binance.com",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "Demo API"):
                create_client()

        configuration_class.assert_not_called()
        client_class.assert_not_called()

    @patch("src.binance_client.load_dotenv")
    def test_missing_configuration_is_rejected(self, load_dotenv):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "missing"):
                create_client()


if __name__ == "__main__":
    unittest.main()