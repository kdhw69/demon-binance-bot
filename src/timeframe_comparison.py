import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Sequence

from .backtest_engine import (
    INITIAL_EQUITY,
    BacktestResult,
    HistoricalCandle,
    FundingRate,
    PortfolioBacktest,
    load_candles,
    load_funding_rates,
    write_results,
)
from .config import SYMBOLS


TIMEFRAMES = {"2h": 2, "4h": 4, "6h": 6}
DEVELOPMENT_START = datetime(2022, 1, 1, tzinfo=timezone.utc)
DEVELOPMENT_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
VALIDATION_START = DEVELOPMENT_END
VALIDATION_END = datetime(2026, 9, 4, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ComparisonMetrics:
    timeframe: str
    period: str
    final_equity: Decimal
    total_return: Decimal
    annualized_return: Decimal
    maximum_drawdown: Decimal
    trades: int
    win_rate: Decimal
    gross_profit_factor: Decimal
    net_profit_factor: Decimal
    total_fees: Decimal
    total_slippage: Decimal
    net_funding: Decimal
    average_net_profit: Decimal
    profitable_months: int
    tested_months: int
    symbol_totals: Dict[str, Decimal]
    direction_totals: Dict[str, Decimal]


def aggregate_candles(records: Sequence[HistoricalCandle], hours: int) -> List[HistoricalCandle]:
    if hours not in (4, 6):
        if hours == 2:
            return list(records)
        raise ValueError("Only 2h, 4h, and 6h aggregation is supported.")
    if not records:
        return []
    interval_ms = hours * 60 * 60 * 1000
    groups = defaultdict(list)
    for record in records:
        epoch_ms = int(record.open_time.timestamp() * 1000)
        groups[(epoch_ms // interval_ms) * interval_ms].append(record)
    output = []
    group_keys = sorted(groups)
    expected = hours // 2
    for group_index, key in enumerate(group_keys):
        group = sorted(groups[key], key=lambda item: item.open_time)
        if len(group) != expected:
            if group_index == len(group_keys) - 1:
                continue
            raise ValueError("Incomplete aggregate candle or missing source candle.")
        for current, following in zip(group, group[1:]):
            if following.open_time - current.open_time != timedelta(hours=2):
                raise ValueError("Source candles are not contiguous.")
        output.append(
            HistoricalCandle(
                open_time=group[0].open_time,
                close_time=group[-1].close_time,
                open_price=group[0].open_price,
                high_price=max(item.high_price for item in group),
                low_price=min(item.low_price for item in group),
                close_price=group[-1].close_price,
            )
        )
    return output


def _period_records(records: Sequence[HistoricalCandle], start: datetime, end: datetime) -> List[HistoricalCandle]:
    selected = [record for record in records if record.open_time < end]
    eligible = [record for record in selected if record.open_time >= start]
    if not eligible:
        raise ValueError("No candles in comparison period.")
    first_index = selected.index(eligible[0])
    return selected[max(0, first_index - 250):]


def funding_for_period(records: Sequence[FundingRate], start: datetime, end: datetime) -> List[FundingRate]:
    return [record for record in records if start <= record.funding_time < end]


def _metrics(result: BacktestResult, timeframe: str, period: str) -> ComparisonMetrics:
    trades = result.trades
    wins = [trade for trade in trades if trade.realized_pnl > 0]
    losses = [trade for trade in trades if trade.realized_pnl < 0]
    gross_wins = sum((trade.gross_pnl for trade in wins), Decimal("0"))
    gross_losses = abs(sum((trade.gross_pnl for trade in losses), Decimal("0")))
    net_wins = sum((trade.realized_pnl for trade in wins), Decimal("0"))
    net_losses = abs(sum((trade.realized_pnl for trade in losses), Decimal("0")))
    month_end = {}
    for point in result.equity_curve:
        month_end[datetime.fromisoformat(point["time_utc"]).strftime("%Y-%m")] = Decimal(point["equity"])
    prior = result.initial_equity
    profitable = 0
    for month in sorted(month_end):
        current = month_end[month]
        if current > prior:
            profitable += 1
        prior = current
    symbol_totals = {symbol: sum((trade.realized_pnl for trade in trades if trade.symbol == symbol), Decimal("0")) for symbol in SYMBOLS}
    direction_totals = {direction: sum((trade.realized_pnl for trade in trades if trade.direction == direction), Decimal("0")) for direction in ("LONG", "SHORT")}
    return ComparisonMetrics(
        timeframe=timeframe,
        period=period,
        final_equity=result.final_equity,
        total_return=result.total_return,
        annualized_return=result.annualized_return,
        maximum_drawdown=result.maximum_drawdown,
        trades=len(trades),
        win_rate=Decimal(len(wins)) / Decimal(len(trades)) if trades else Decimal("0"),
        gross_profit_factor=gross_wins / gross_losses if gross_losses else Decimal("0"),
        net_profit_factor=net_wins / net_losses if net_losses else Decimal("0"),
        total_fees=result.total_fees,
        total_slippage=result.total_slippage,
        net_funding=result.net_funding,
        average_net_profit=sum((trade.realized_pnl for trade in trades), Decimal("0")) / Decimal(len(trades)) if trades else Decimal("0"),
        profitable_months=profitable,
        tested_months=len(month_end),
        symbol_totals=symbol_totals,
        direction_totals=direction_totals,
    )


def run_comparison(data_dir: Path = Path("data/historical")) -> List[ComparisonMetrics]:
    source_candles = {symbol: load_candles(data_dir / f"{symbol}_candles.csv") for symbol in SYMBOLS}
    funding = {symbol: load_funding_rates(data_dir / f"{symbol}_funding_rates.csv") for symbol in SYMBOLS}
    results = []
    for timeframe, hours in TIMEFRAMES.items():
        candles = {symbol: aggregate_candles(source_candles[symbol], hours) for symbol in SYMBOLS}
        for period, start, end in (("development", DEVELOPMENT_START, DEVELOPMENT_END), ("validation", VALIDATION_START, VALIDATION_END)):
            windowed = {symbol: _period_records(candles[symbol], start, end) for symbol in SYMBOLS}
            period_funding = {symbol: funding_for_period(funding[symbol], start, end) for symbol in SYMBOLS}
            result = PortfolioBacktest(
                windowed,
                period_funding,
                initial_equity=INITIAL_EQUITY,
                diagnostic_ignore_max_drawdown_halt=True,
                start_time=start,
                end_time=end - timedelta(hours=hours),
            ).run()
            results.append(_metrics(result, timeframe, period))
    return results
