import plistlib
import unittest
from pathlib import Path


_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "ops"
    / "com.demon.demo-binance-bot.plist.template"
)


class LaunchdTemplateTests(unittest.TestCase):
    def setUp(self):
        self.raw = _TEMPLATE.read_bytes()
        self.config = plistlib.loads(self.raw)

    def test_runs_three_minutes_after_each_four_hour_close(self):
        schedule = self.config["StartCalendarInterval"]
        self.assertEqual(
            [(item["Hour"], item["Minute"]) for item in schedule],
            [(1, 3), (5, 3), (9, 3), (13, 3), (17, 3), (21, 3)],
        )

    def test_demo_execution_requires_existing_safety_gate(self):
        arguments = self.config["ProgramArguments"]
        environment = self.config["EnvironmentVariables"]
        self.assertIn("--execute-demo", arguments)
        self.assertEqual(arguments[-2:], ["--confirmation", "DEMO_ONLY"])
        self.assertEqual(environment["DEMON_DEMO_EXECUTION_ENABLED"], "YES")

    def test_template_contains_no_credentials_or_production_url(self):
        text = self.raw.decode("utf-8")
        self.assertNotIn("BINANCE_API_KEY", text)
        self.assertNotIn("BINANCE_API_SECRET", text)
        self.assertNotIn("fapi.binance.com", text)
        self.assertIn("__PROJECT_DIR__", text)


if __name__ == "__main__":
    unittest.main()
