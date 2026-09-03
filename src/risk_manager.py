from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Dict, Optional

from .config import (
    ATR_PERIOD,
    LEVERAGE,
    MAX_COMBINED_OPEN_RISK,
    MAX_DRAWDOWN_STOP,
    MAX_MARGIN_PER_POSITION,
    MAX_SIMULTANEOUS_POSITIONS,
    MAX_TOTAL_MARGIN_USAGE,
    RISK_PER_TRADE,
    STOP_LOSS_ATR_DISTANCE,
    TAKE_PROFIT_ATR_DISTANCE,
)
from .exchange_rules import TradingRules, get_exchange_rules
from .signal_engine import Signal, get_latest_signals
from .binance_client import create_client


@dataclass(frozen=True)
class AccountRiskState:
    equity: Decimal
    open_positions: int
    combined_open_risk: Decimal
    total_margin_used: Decimal
    daily_loss: Decimal = Decimal("0")
    consecutive_losses: int = 0
    drawdown: Decimal = Decimal("0")


@dataclass(frozen=True)
class RiskPlan:
    symbol: str
    direction: str
    quantity: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_amount: Decimal
    margin_used: Decimal
    reason: str


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _round_exit_prices(signal: Signal, rules: TradingRules):
    stop_distance = signal.atr * Decimal(str(STOP_LOSS_ATR_DISTANCE))
    take_profit_distance = signal.atr * Decimal(str(TAKE_PROFIT_ATR_DISTANCE))
    if signal.direction == "LONG":
        stop_loss = _floor_to_step(signal.close_price - stop_distance, rules.price_tick_size)
        take_profit = _ceil_to_step(signal.close_price + take_profit_distance, rules.price_tick_size)
    elif signal.direction == "SHORT":
        stop_loss = _ceil_to_step(signal.close_price + stop_distance, rules.price_tick_size)
        take_profit = _floor_to_step(signal.close_price - take_profit_distance, rules.price_tick_size)
    else:
        raise ValueError("Risk plans require a LONG or SHORT signal.")
    if signal.direction == "LONG" and not (stop_loss < signal.close_price < take_profit):
        raise ValueError("Rounded LONG exit prices are invalid.")
    if signal.direction == "SHORT" and not (take_profit < signal.close_price < stop_loss):
        raise ValueError("Rounded SHORT exit prices are invalid.")
    return stop_loss, take_profit


def create_risk_plan(
    signal: Signal,
    account: AccountRiskState,
    rules: TradingRules,
) -> RiskPlan:
    if signal.direction not in {"LONG", "SHORT"}:
        raise ValueError("No trade signal is available.")
    if signal.symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
        raise ValueError("Symbol is not permitted.")
    if account.equity <= 0:
        raise ValueError("Account equity must be positive.")
    if account.open_positions >= MAX_SIMULTANEOUS_POSITIONS:
        raise ValueError("Maximum simultaneous positions reached.")
    if account.daily_loss >= Decimal("0.05"):
        raise ValueError("Daily loss limit reached.")
    if account.consecutive_losses >= 4:
        raise ValueError("Consecutive loss limit reached.")
    if account.drawdown >= MAX_DRAWDOWN_STOP:
        raise ValueError("Maximum drawdown stop reached.")
    combined_risk_limit = Decimal(str(MAX_COMBINED_OPEN_RISK))
    risk_per_trade = Decimal(str(RISK_PER_TRADE))
    remaining_risk = combined_risk_limit - account.combined_open_risk
    if remaining_risk <= 0:
        raise ValueError("Maximum combined open risk reached.")

    risk_allocation = min(risk_per_trade, remaining_risk)
    stop_loss, take_profit = _round_exit_prices(signal, rules)
    risk_per_unit = abs(signal.close_price - stop_loss)
    if risk_per_unit <= 0:
        raise ValueError("Stop-loss distance must be positive.")

    risk_quantity = account.equity * risk_allocation / risk_per_unit
    per_position_margin = account.equity * Decimal(str(MAX_MARGIN_PER_POSITION))
    remaining_margin = (
        account.equity * Decimal(str(MAX_TOTAL_MARGIN_USAGE))
        - account.total_margin_used
    )
    margin_limit = min(per_position_margin, remaining_margin)
    if margin_limit <= 0:
        raise ValueError("Margin limit reached.")
    margin_quantity = margin_limit * Decimal(str(LEVERAGE)) / signal.close_price
    quantity = _floor_to_step(min(risk_quantity, margin_quantity), rules.quantity_step_size)
    if quantity < rules.minimum_order_quantity:
        raise ValueError("Rounded quantity is below the minimum order quantity.")
    if quantity * signal.close_price < rules.minimum_notional_value:
        raise ValueError("Rounded quantity is below the minimum notional value.")

    margin_used = quantity * signal.close_price / Decimal(str(LEVERAGE))
    risk_amount = quantity * risk_per_unit
    return RiskPlan(
        symbol=signal.symbol,
        direction=signal.direction,
        quantity=quantity,
        entry_price=signal.close_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_amount=risk_amount,
        margin_used=margin_used,
        reason="Approved within confirmed risk limits.",
    )


def _account_risk_state(client) -> AccountRiskState:
    account = client.rest_api.account_information_v3().data()
    equity = Decimal(str(account.total_margin_balance or account.total_wallet_balance))
    positions = account.positions or []
    open_positions = sum(
        Decimal(str(position.position_amt)) != Decimal("0")
        for position in positions
    )
    combined_open_risk = sum(
        (abs(Decimal(str(position.initial_margin or "0"))) for position in positions),
        Decimal("0"),
    )
    if equity <= 0:
        raise ValueError("Account equity must be positive.")
    combined_open_risk /= equity
    total_margin_used = Decimal(str(account.total_initial_margin or "0"))
    return AccountRiskState(
        equity=equity,
        open_positions=open_positions,
        combined_open_risk=combined_open_risk,
        total_margin_used=total_margin_used,
    )


def _reserve_plan(account: AccountRiskState, plan: RiskPlan) -> AccountRiskState:
    return AccountRiskState(
        equity=account.equity,
        open_positions=account.open_positions + 1,
        combined_open_risk=(
            account.combined_open_risk
            + plan.risk_amount / account.equity
        ),
        total_margin_used=account.total_margin_used + plan.margin_used,
        daily_loss=account.daily_loss,
        consecutive_losses=account.consecutive_losses,
        drawdown=account.drawdown,
    )


def get_latest_risk_plans() -> Dict[str, Optional[RiskPlan]]:
    client = create_client()
    account = _account_risk_state(client)
    rules_by_symbol = get_exchange_rules(client)
    signals = get_latest_signals()
    plans = {}
    for symbol, signal in signals.items():
        if signal.direction == "NO_SIGNAL":
            plans[symbol] = None
        else:
            plan = create_risk_plan(signal, account, rules_by_symbol[symbol])
            plans[symbol] = plan
            account = _reserve_plan(account, plan)
    return plans
