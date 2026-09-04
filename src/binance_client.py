import os
from pathlib import Path

from dotenv import load_dotenv
from binance_common.configuration import ConfigurationRestAPI
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures


_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_DEMO_BASE_URL = "https://demo-fapi.binance.com"


def create_client() -> DerivativesTradingUsdsFutures:
    load_dotenv(dotenv_path=_ENV_PATH)

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    base_url = os.getenv("BINANCE_BASE_URL")

    if not api_key or not api_secret or not base_url:
        raise ValueError("Required Binance environment configuration is missing.")
    if base_url != _DEMO_BASE_URL:
        raise ValueError(
            "BINANCE_BASE_URL must target the Binance Futures Demo API."
        )

    configuration = ConfigurationRestAPI(
        api_key=api_key,
        api_secret=api_secret,
        base_path=base_url,
    )
    return DerivativesTradingUsdsFutures(config_rest_api=configuration)
