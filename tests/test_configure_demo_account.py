import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.configure_demo_account import (
    verify_demo_execution_settings,
)


def response(data):
    return SimpleNamespace(data=lambda: data)


def configured_client(
    *,
    one_way=True,
    margin_type="ISOLATED",
    leverage=10,
):
    client = MagicMock()
    client.rest_api.get_current_position_mode.return_value = response(
        SimpleNamespace(
            dual_side_position=not one_way,
        )
    )
    client.rest_api.symbol_configuration.return_value = response(
        [
            SimpleNamespace(
                symbol="BTCUSDT",
                margin_type=margin_type,
                leverage=leverage,
            )
        ]
    )
    return client


class DemoAccountVerificationTests(unittest.TestCase):
    def test_valid_execution_settings_pass(self):
        client = configured_client()

        verify_demo_execution_settings(client, "BTCUSDT")

        client.rest_api.change_position_mode.assert_not_called()
        client.rest_api.change_margin_type.assert_not_called()
        client.rest_api.change_initial_leverage.assert_not_called()

    def test_hedge_mode_is_rejected(self):
        client = configured_client(one_way=False)

        with self.assertRaisesRegex(ValueError, "One-way"):
            verify_demo_execution_settings(
                client,
                "BTCUSDT",
            )

    def test_cross_margin_is_rejected(self):
        client = configured_client(margin_type="CROSSED")

        with self.assertRaisesRegex(ValueError, "Isolated"):
            verify_demo_execution_settings(
                client,
                "BTCUSDT",
            )

    def test_wrong_leverage_is_rejected(self):
        client = configured_client(leverage=5)

        with self.assertRaisesRegex(ValueError, "10x"):
            verify_demo_execution_settings(
                client,
                "BTCUSDT",
            )

    def test_unapproved_symbol_is_rejected(self):
        client = configured_client()

        with self.assertRaisesRegex(ValueError, "not permitted"):
            verify_demo_execution_settings(
                client,
                "XRPUSDT",
            )


if __name__ == "__main__":
    unittest.main()
