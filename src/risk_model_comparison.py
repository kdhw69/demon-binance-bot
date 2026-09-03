from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from .backtest_engine import INITIAL_EQUITY, PortfolioBacktest, load_candles, load_funding_rates
from .config import SYMBOLS
from .timeframe_comparison import DEVELOPMENT_END, DEVELOPMENT_START, _metrics, _period_records, aggregate_candles, funding_for_period

VALIDATION_END = datetime(2026, 9, 4, tzinfo=timezone.utc)
VALIDATION_START = DEVELOPMENT_END
RISK_MODELS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class RiskModelResult:
    model: str
    period: str
    result: object
    metrics: object
    qualified: bool = False


def _run_model(candles, funding, model: str, period: str, start: datetime, end: datetime, ignore_drawdown_halt: bool) -> RiskModelResult:
    windowed = {symbol: _period_records(candles[symbol], start, end) for symbol in SYMBOLS}
    period_funding = {symbol: funding_for_period(funding[symbol], start, end) for symbol in SYMBOLS}
    result = PortfolioBacktest(
        windowed,
        period_funding,
        initial_equity=INITIAL_EQUITY,
        diagnostic_ignore_max_drawdown_halt=ignore_drawdown_halt,
        start_time=start,
        end_time=end - timedelta(hours=4),
        risk_model=model,
    ).run()
    metrics = _metrics(result, "4h", period)
    qualified = (
        metrics.maximum_drawdown < Decimal("0.15")
        and metrics.net_profit_factor >= Decimal("1.20")
        and metrics.annualized_return > Decimal("0")
    )
    return RiskModelResult(model, period, result, metrics, qualified)


def run_risk_model_comparison(data_dir: Path = Path("data/historical")) -> tuple[List[RiskModelResult], RiskModelResult | None]:
    source = {symbol: load_candles(data_dir / f"{symbol}_candles.csv") for symbol in SYMBOLS}
    funding = {symbol: load_funding_rates(data_dir / f"{symbol}_funding_rates.csv") for symbol in SYMBOLS}
    candles = {symbol: aggregate_candles(source[symbol], 4) for symbol in SYMBOLS}
    development = [
        _run_model(candles, funding, model, "development", DEVELOPMENT_START, DEVELOPMENT_END, True)
        for model in RISK_MODELS
    ]
    qualified = [item for item in development if item.qualified]
    ranked = sorted(
        qualified,
        key=lambda item: item.metrics.annualized_return,
        reverse=True,
    )
    validations = []
    selected = None
    for candidate in ranked:
        validation = _run_model(
            candles,
            funding,
            candidate.model,
            "validation",
            VALIDATION_START,
            VALIDATION_END,
            False,
        )
        validations.append(validation)
        if validation.qualified and not validation.result.risk_halts:
            selected = validation
            break
    return development + validations, selected
