import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .config import (
    DAILY_LOSS_LIMIT,
    LEVERAGE,
    MAX_COMBINED_OPEN_RISK,
    MAX_DRAWDOWN_STOP,
    MAX_MARGIN_PER_POSITION,
    MAX_SIMULTANEOUS_POSITIONS,
    MAX_TOTAL_MARGIN_USAGE,
    RISK_PER_TRADE,
    STOP_LOSS_ATR_DISTANCE,
    TAKE_PROFIT_ATR_DISTANCE,
    SYMBOLS,
)
from .exchange_rules import TradingRules
from .indicators import calculate_atr_wilder, calculate_donchian_channels, calculate_ema
from .market_data import Candle
from .signal_engine import Signal


INITIAL_EQUITY = Decimal("5000")
TAKER_FEE_RATE = Decimal("0.0005")
SLIPPAGE_RATE = Decimal("0.0002")
INTERVAL = "2h"


@dataclass(frozen=True)
class HistoricalCandle:
    open_time: datetime
    close_time: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class FundingRate:
    funding_time: datetime
    funding_rate: Decimal
    mark_price: Decimal


@dataclass
class BacktestPosition:
    symbol: str
    direction: str
    quantity: Decimal
    entry_time: datetime
    raw_entry_price: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    planned_risk: Decimal
    margin_used: Decimal


@dataclass(frozen=True)
class BacktestTrade:
    trade_id: int
    symbol: str
    direction: str
    quantity: Decimal
    entry_time: datetime
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    exit_time: datetime
    exit_price: Decimal
    exit_reason: str
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    funding_payment: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True)
class BacktestResult:
    initial_equity: Decimal
    final_equity: Decimal
    total_return: Decimal
    annualized_return: Decimal
    maximum_drawdown: Decimal
    trades: List[BacktestTrade]
    equity_curve: List[dict]
    monthly_returns: List[dict]
    risk_halts: List[dict]
    total_fees: Decimal
    total_slippage: Decimal
    net_funding: Decimal
    rejection_counts: Dict[str, int]
    consecutive_loss_cooldowns: List[dict]


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Historical timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except Exception:
        raise ValueError(f"Malformed historical {field} value.")


def load_candles(path: Path) -> List[HistoricalCandle]:
    records = []
    with Path(path).open(newline="") as source:
        for row in csv.DictReader(source):
            required = ("open_time_utc", "close_time_utc", "open", "high", "low", "close")
            if any(row.get(field) in (None, "") for field in required):
                raise ValueError("Required candle data is missing.")
            records.append(
                HistoricalCandle(
                    open_time=_utc(row["open_time_utc"]),
                    close_time=_utc(row["close_time_utc"]),
                    open_price=_decimal(row["open"], "price"),
                    high_price=_decimal(row["high"], "price"),
                    low_price=_decimal(row["low"], "price"),
                    close_price=_decimal(row["close"], "price"),
                )
            )
    if not records:
        raise ValueError("No historical candles found.")
    for current, following in zip(records, records[1:]):
        if following.open_time <= current.open_time:
            raise ValueError("Historical candles are not chronologically ordered.")
    return records


def load_funding_rates(path: Path) -> List[FundingRate]:
    records = []
    with Path(path).open(newline="") as source:
        for row in csv.DictReader(source):
            if not row.get("funding_time_utc") or not row.get("funding_rate"):
                raise ValueError("Required funding data is missing.")
            mark_price = row.get("mark_price")
            if not mark_price:
                raise ValueError("Funding mark price is missing.")
            records.append(
                FundingRate(
                    funding_time=_utc(row["funding_time_utc"]),
                    funding_rate=_decimal(row["funding_rate"], "funding rate"),
                    mark_price=_decimal(mark_price, "funding mark price"),
                )
            )
    if not records:
        raise ValueError("No historical funding rates found.")
    for current, following in zip(records, records[1:]):
        if following.funding_time <= current.funding_time:
            raise ValueError("Historical funding rates are not chronologically ordered.")
    return records


def _as_candles(records: Sequence[HistoricalCandle]) -> List[Candle]:
    return [
        Candle(record.close_time, record.high_price, record.low_price, record.close_price)
        for record in records
    ]


def _floor(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _ceil(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _rules() -> Dict[str, TradingRules]:
    return {
        "BTCUSDT": TradingRules("BTCUSDT", "TRADING", Decimal("0.10"), Decimal("0.0001"), Decimal("0.0001"), Decimal("50")),
        "ETHUSDT": TradingRules("ETHUSDT", "TRADING", Decimal("0.01"), Decimal("0.001"), Decimal("0.001"), Decimal("20")),
        "SOLUSDT": TradingRules("SOLUSDT", "TRADING", Decimal("0.0100"), Decimal("0.01"), Decimal("0.01"), Decimal("5")),
    }


class PortfolioBacktest:
    def __init__(self, candles: Dict[str, Sequence[HistoricalCandle]], funding: Dict[str, Sequence[FundingRate]], initial_equity: Decimal = INITIAL_EQUITY, diagnostic_ignore_max_drawdown_halt: bool = False, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None, risk_model: str = "A"):
        if risk_model not in {"A", "B", "C", "D"}:
            raise ValueError("Unsupported backtest risk model.")
        self.candles = candles
        self.funding = funding
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.peak_equity = initial_equity
        self.day_start_equity = initial_equity
        self.trading_date = None
        self.daily_realized = Decimal("0")
        self.daily_loss_halt_until = None
        self.consecutive_losses = 0
        self.consecutive_loss_cooldown_until = None
        self.halted = False
        self.halt_reason = None
        self.halts = []
        self.consecutive_loss_cooldowns = []
        self.rejection_counts = {
            "daily_loss_limit": 0,
            "consecutive_loss_cooldown": 0,
            "maximum_drawdown": 0,
            "maximum_simultaneous_positions": 0,
            "maximum_combined_open_risk": 0,
            "maximum_total_margin_usage": 0,
            "minimum_order_rules": 0,
        }
        self.positions: Dict[str, BacktestPosition] = {}
        self.trades: List[BacktestTrade] = []
        self.equity_curve = []
        self._trade_id = 0
        self._rules = _rules()
        self._funding_index = {symbol: 0 for symbol in SYMBOLS}
        self._indicator_series = {}
        self.diagnostic_ignore_max_drawdown_halt = diagnostic_ignore_max_drawdown_halt
        self._drawdown_threshold_breached = False
        self.start_time = start_time
        self.end_time = end_time
        self.risk_model = risk_model

    def _halt(self, timestamp: datetime, reason: str) -> None:
        if not self.halted:
            self.halted = True
            self.halt_reason = reason
            self.halts.append({"time_utc": timestamp.isoformat(), "reason": reason})

    def _risk_reset(self, timestamp: datetime) -> None:
        if self.trading_date is None:
            self.trading_date = timestamp.date()
            self.day_start_equity = self.equity
        elif timestamp.date() != self.trading_date:
            self.trading_date = timestamp.date()
            self.day_start_equity = self.equity
            self.daily_realized = Decimal("0")
            self.daily_loss_halt_until = None

    def _check_limits(self, timestamp: datetime) -> None:
        if (
            self.daily_loss_halt_until is None
            and -self.daily_realized >= self.day_start_equity * Decimal(str(DAILY_LOSS_LIMIT))
        ):
            tomorrow = timestamp.date() + timedelta(days=1)
            self.daily_loss_halt_until = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone.utc)
        drawdown_breached = self.equity <= self.peak_equity * (Decimal("1") - Decimal(str(MAX_DRAWDOWN_STOP)))
        if drawdown_breached and not self._drawdown_threshold_breached:
            self.halts.append({"time_utc": timestamp.isoformat(), "reason": "Maximum drawdown threshold crossed."})
            if self.risk_model == "C" or not self.diagnostic_ignore_max_drawdown_halt:
                self._halt(timestamp, "Maximum drawdown stop reached.")
        self._drawdown_threshold_breached = drawdown_breached

    def _reject(self, rule: str) -> None:
        self.rejection_counts[rule] += 1

    def _funding_for(self, position: BacktestPosition, exit_time: datetime) -> Decimal:
        payment = Decimal("0")
        rates = self.funding[position.symbol]
        index = self._funding_index[position.symbol]
        while index < len(rates) and rates[index].funding_time <= exit_time:
            event = rates[index]
            if event.funding_time > position.entry_time:
                notional = position.quantity * event.mark_price
                signed_payment = notional * event.funding_rate
                payment += signed_payment if position.direction == "LONG" else -signed_payment
            index += 1
        self._funding_index[position.symbol] = index
        return payment

    def _close(self, position: BacktestPosition, exit_time: datetime, raw_exit: Decimal, reason: str) -> None:
        if position.direction == "LONG":
            exit_price = raw_exit * (Decimal("1") - SLIPPAGE_RATE)
            gross = (exit_price - position.entry_price) * position.quantity
        else:
            exit_price = raw_exit * (Decimal("1") + SLIPPAGE_RATE)
            gross = (position.entry_price - exit_price) * position.quantity
        entry_notional = position.entry_price * position.quantity
        exit_notional = exit_price * position.quantity
        fees = (entry_notional + exit_notional) * TAKER_FEE_RATE
        entry_slippage = abs(position.raw_entry_price - position.entry_price) * position.quantity
        slippage = entry_slippage + abs(raw_exit - exit_price) * position.quantity
        funding_payment = self._funding_for(position, exit_time)
        realized = gross - fees - slippage - funding_payment
        self.equity += realized
        self.daily_realized += realized
        self.consecutive_losses = self.consecutive_losses + 1 if realized < 0 else 0
        self._trade_id += 1
        self.trades.append(BacktestTrade(self._trade_id, position.symbol, position.direction, position.quantity, position.entry_time, position.entry_price, position.stop_loss, position.take_profit, exit_time, exit_price, reason, gross, fees, slippage, funding_payment, realized))
        del self.positions[position.symbol]
        if realized < 0 and self.consecutive_losses >= 4:
            cooldown_until = exit_time + timedelta(hours=12)
            self.consecutive_loss_cooldown_until = cooldown_until
            self.consecutive_losses = 0
            self.consecutive_loss_cooldowns.append(
                {
                    "started_utc": exit_time.isoformat(),
                    "ends_utc": cooldown_until.isoformat(),
                    "duration_hours": "12",
                }
            )
        self._check_limits(exit_time)

    def _manage(self, symbol: str, record: HistoricalCandle) -> None:
        position = self.positions.get(symbol)
        if position is None:
            return
        stop_hit = record.low_price <= position.stop_loss if position.direction == "LONG" else record.high_price >= position.stop_loss
        target_hit = record.high_price >= position.take_profit if position.direction == "LONG" else record.low_price <= position.take_profit
        if position.direction == "LONG":
            gap = record.open_price <= position.stop_loss
        else:
            gap = record.open_price >= position.stop_loss
        if gap:
            self._close(position, record.open_time, record.open_price, "STOP_LOSS")
        elif stop_hit:
            self._close(position, record.close_time, position.stop_loss, "STOP_LOSS")
        elif target_hit:
            self._close(position, record.close_time, position.take_profit, "TAKE_PROFIT")

    def _entry(self, symbol: str, signal: Signal, record: HistoricalCandle) -> None:
        if self.halted:
            if self.halt_reason and "drawdown" in self.halt_reason.lower():
                self._reject("maximum_drawdown")
            return
        if self.daily_loss_halt_until is not None and record.open_time < self.daily_loss_halt_until:
            self._reject("daily_loss_limit")
            return
        if self.consecutive_loss_cooldown_until is not None and record.open_time < self.consecutive_loss_cooldown_until:
            self._reject("consecutive_loss_cooldown")
            return
        if symbol in self.positions:
            return
        if len(self.positions) >= MAX_SIMULTANEOUS_POSITIONS:
            self._reject("maximum_simultaneous_positions")
            return
        rules = self._rules[symbol]
        raw_entry = record.open_price
        if signal.direction == "LONG":
            entry_price = raw_entry * (Decimal("1") + SLIPPAGE_RATE)
            stop = _floor(entry_price - signal.atr * Decimal(str(STOP_LOSS_ATR_DISTANCE)), rules.price_tick_size)
            target = _ceil(entry_price + signal.atr * Decimal(str(TAKE_PROFIT_ATR_DISTANCE)), rules.price_tick_size)
        else:
            entry_price = raw_entry * (Decimal("1") - SLIPPAGE_RATE)
            stop = _ceil(entry_price + signal.atr * Decimal(str(STOP_LOSS_ATR_DISTANCE)), rules.price_tick_size)
            target = _floor(entry_price - signal.atr * Decimal(str(TAKE_PROFIT_ATR_DISTANCE)), rules.price_tick_size)
        risk_per_unit = abs(entry_price - stop)
        risk_per_trade, combined_risk = self._risk_limits()
        remaining_risk = self.equity * combined_risk - sum((p.planned_risk for p in self.positions.values()), Decimal("0"))
        margin_limit = min(self.equity * Decimal(str(MAX_MARGIN_PER_POSITION)), self.equity * Decimal(str(MAX_TOTAL_MARGIN_USAGE)) - sum((p.margin_used for p in self.positions.values()), Decimal("0")))
        if remaining_risk <= 0 or margin_limit <= 0 or risk_per_unit <= 0:
            self._reject("maximum_combined_open_risk" if remaining_risk <= 0 else "maximum_total_margin_usage")
            return
        quantity = _floor(min(self.equity * risk_per_trade / risk_per_unit, remaining_risk / risk_per_unit, margin_limit * Decimal(str(LEVERAGE)) / entry_price), rules.quantity_step_size)
        if quantity < rules.minimum_order_quantity or quantity * entry_price < rules.minimum_notional_value:
            self._reject("minimum_order_rules")
            return
        margin = quantity * entry_price / Decimal(str(LEVERAGE))
        self.positions[symbol] = BacktestPosition(symbol, signal.direction, quantity, record.open_time, raw_entry, entry_price, stop, target, quantity * risk_per_unit, margin)

    def _risk_limits(self):
        if self.risk_model == "A":
            return Decimal("0.01"), Decimal("0.025")
        if self.risk_model == "B":
            return Decimal("0.005"), Decimal("0.0125")
        if self.risk_model == "D":
            return Decimal("0.0025"), Decimal("0.00625")
        drawdown = Decimal("0") if self.peak_equity <= 0 else (self.peak_equity - self.equity) / self.peak_equity
        if drawdown < Decimal("0.05"):
            return Decimal("0.01"), Decimal("0.025")
        if drawdown < Decimal("0.10"):
            return Decimal("0.005"), Decimal("0.0125")
        return Decimal("0.0025"), Decimal("0.00625")

    def run(self) -> BacktestResult:
        if any(symbol not in self.candles or symbol not in self.funding for symbol in SYMBOLS):
            raise ValueError("Required symbol data is missing.")
        common_times = sorted({record.open_time for records in self.candles.values() for record in records})
        indices = {symbol: {record.open_time: index for index, record in enumerate(records)} for symbol, records in self.candles.items()}
        for symbol in SYMBOLS:
            candle_values = _as_candles(self.candles[symbol])
            self._indicator_series[symbol] = (
                calculate_ema(candle_values, 200),
                calculate_donchian_channels(candle_values, 20),
                calculate_atr_wilder(candle_values, 14),
            )
        for timestamp in common_times:
            if self.start_time is not None and timestamp < self.start_time:
                continue
            if self.end_time is not None and timestamp > self.end_time:
                break
            self._risk_reset(timestamp)
            for symbol in SYMBOLS:
                index = indices[symbol].get(timestamp)
                if index is None:
                    continue
                record = self.candles[symbol][index]
                self._manage(symbol, record)
                if index > 0:
                    previous = self.candles[symbol][index - 1]
                    if previous.close_time < record.open_time:
                        signal = self._signal_at(symbol, index - 1)
                        if signal.direction in {"LONG", "SHORT"}:
                            self._entry(symbol, signal, record)
                self.equity_curve.append({"time_utc": record.close_time.isoformat(), "equity": str(self.equity)})
                if self.equity > self.peak_equity:
                    self.peak_equity = self.equity
                self._check_limits(record.close_time)
        if not self.equity_curve:
            raise ValueError("No candles in the requested backtest window.")
        final_time = _utc(self.equity_curve[-1]["time_utc"])
        for position in list(self.positions.values()):
            record = self.candles[position.symbol][-1]
            self._close(position, final_time, record.close_price, "END_OF_TEST")
        return self._result()

    def _signal_at(self, symbol: str, index: int) -> Signal:
        records = self.candles[symbol]
        ema = self._indicator_series[symbol][0][index]
        high, low = self._indicator_series[symbol][1][index]
        atr = self._indicator_series[symbol][2][index]
        if ema is None or high is None or low is None or atr is None:
            return Signal(symbol, records[index].close_time, "NO_SIGNAL", records[index].close_price, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
        close = records[index].close_price
        direction = "LONG" if close > ema and close > high else "SHORT" if close < ema and close < low else "NO_SIGNAL"
        return Signal(symbol, records[index].close_time, direction, close, ema, high, low, atr)

    def _result(self) -> BacktestResult:
        final = self.equity
        total_return = final / self.initial_equity - Decimal("1")
        if self.equity_curve:
            start = _utc(self.equity_curve[0]["time_utc"])
            end = _utc(self.equity_curve[-1]["time_utc"])
            elapsed = end - start
            elapsed_seconds = elapsed.days * 86400 + elapsed.seconds
            days = max(Decimal(elapsed_seconds) / Decimal("86400"), Decimal("1"))
            annualized = (final / self.initial_equity) ** (Decimal("365") / days) - Decimal("1") if final > 0 else Decimal("-1")
        else:
            annualized = Decimal("0")
        peak = self.initial_equity
        max_drawdown = Decimal("0")
        for point in self.equity_curve:
            equity = Decimal(point["equity"])
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
        monthly = {}
        for point in self.equity_curve:
            month = _utc(point["time_utc"]).strftime("%Y-%m")
            monthly[month] = point["equity"]
        return BacktestResult(self.initial_equity, final, total_return, annualized, max_drawdown, self.trades, self.equity_curve, [{"month": month, "equity": value} for month, value in monthly.items()], self.halts, self._fees(), self._slippage(), self._funding(), self.rejection_counts, self.consecutive_loss_cooldowns)

    def _fees(self): return sum((trade.fees for trade in self.trades), Decimal("0"))
    def _slippage(self): return sum((trade.slippage_cost for trade in self.trades), Decimal("0"))
    def _funding(self): return sum((trade.funding_payment for trade in self.trades), Decimal("0"))


def run_historical_backtest(data_dir: Path = Path("data/historical"), diagnostic_ignore_max_drawdown_halt: bool = False, risk_model: str = "A") -> BacktestResult:
    candles = {symbol: load_candles(data_dir / f"{symbol}_candles.csv") for symbol in SYMBOLS}
    funding = {symbol: load_funding_rates(data_dir / f"{symbol}_funding_rates.csv") for symbol in SYMBOLS}
    return PortfolioBacktest(candles, funding, diagnostic_ignore_max_drawdown_halt=diagnostic_ignore_max_drawdown_halt, risk_model=risk_model).run()


def write_results(result: BacktestResult, output_dir: Path = Path("data/backtests")) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "trades.csv").open("w", newline="") as output:
        fields = list(BacktestTrade.__dataclass_fields__)
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for trade in result.trades:
            writer.writerow({field: str(getattr(trade, field)) for field in fields})
    with (output_dir / "equity_curve.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["time_utc", "equity"])
        writer.writeheader(); writer.writerows(result.equity_curve)
    with (output_dir / "monthly_returns.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["month", "equity"])
        writer.writeheader(); writer.writerows(result.monthly_returns)
    summary = asdict(result)
    summary["trades"] = [asdict(trade) for trade in result.trades]
    for key in ("initial_equity", "final_equity", "total_return", "annualized_return", "maximum_drawdown", "total_fees", "total_slippage", "net_funding"):
        summary[key] = str(summary[key])
    with (output_dir / "summary.json").open("w") as output:
        json.dump(summary, output, indent=2, default=str)
