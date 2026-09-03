from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Sequence, Set

from .binance_client import create_client
from .config import (
    DAILY_LOSS_LIMIT,
    MAX_COMBINED_OPEN_RISK,
    MAX_DRAWDOWN_STOP,
    MAX_SIMULTANEOUS_POSITIONS,
    MAX_TOTAL_MARGIN_USAGE,
)
from .trade_store import TradeStore


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reasons: tuple[str, ...]


def _limit(value) -> Decimal:
    return Decimal(str(value))


def _position_symbols(positions: Iterable) -> Set[str]:
    symbols = set()
    for position in positions:
        amount = getattr(position, "position_amt", None)
        symbol = getattr(position, "symbol", None)
        if amount is None or not symbol:
            raise ValueError("Required position state is unavailable.")
        if Decimal(str(amount)) != Decimal("0"):
            symbols.add(symbol)
    return symbols


def evaluate_guard(
    account_equity: Decimal,
    day_start_equity: Optional[Decimal],
    peak_equity: Optional[Decimal],
    daily_realized_pnl: Decimal,
    consecutive_losses: int,
    halted: bool,
    halt_reason: Optional[str],
    binance_position_symbols: Set[str],
    local_active_trades: Sequence[dict],
    total_used_margin: Decimal,
) -> GuardDecision:
    reasons = []
    if account_equity <= 0:
        return GuardDecision(False, ("Current account equity is unavailable.",))
    if day_start_equity is None or peak_equity is None:
        return GuardDecision(False, ("Risk equity state is unavailable.",))

    local_symbols = {trade["symbol"] for trade in local_active_trades}
    if binance_position_symbols != local_symbols:
        reasons.append("Reconciliation required: Binance positions and local active trades differ.")

    if halted:
        reasons.append(halt_reason or "Trading is permanently halted.")
    if -daily_realized_pnl >= day_start_equity * _limit(DAILY_LOSS_LIMIT):
        reasons.append("Daily realized loss limit reached.")
    if consecutive_losses >= 4:
        reasons.append("Consecutive loss limit reached.")
    if account_equity <= peak_equity * (Decimal("1") - _limit(MAX_DRAWDOWN_STOP)):
        reasons.append("Maximum drawdown stop reached.")
    if len(binance_position_symbols) >= MAX_SIMULTANEOUS_POSITIONS:
        reasons.append("Maximum simultaneous positions reached.")

    planned_risk = sum(
        (Decimal(str(trade["planned_risk"])) for trade in local_active_trades),
        Decimal("0"),
    )
    if planned_risk >= account_equity * _limit(MAX_COMBINED_OPEN_RISK):
        reasons.append("Maximum combined planned open risk reached.")
    if total_used_margin >= account_equity * _limit(MAX_TOTAL_MARGIN_USAGE):
        reasons.append("Maximum total margin usage reached.")

    return GuardDecision(not reasons, tuple(reasons))


def _account_snapshot(client):
    account = client.rest_api.account_information_v3().data()
    equity_text = account.total_margin_balance or account.total_wallet_balance
    margin_text = account.total_initial_margin
    if equity_text is None or margin_text is None or account.positions is None:
        raise ValueError("Required account risk state is unavailable.")
    equity = Decimal(str(equity_text))
    positions = account.positions
    return equity, Decimal(str(margin_text)), _position_symbols(positions)


def check_live_guard(database_path=None) -> GuardDecision:
    client = create_client()
    store = TradeStore(database_path)
    try:
        equity, account_margin, position_symbols = _account_snapshot(client)
        state = store.sync_equity(equity)
        active_trades = store.read_active_trades()
        planned_margin = sum(
            (
                Decimal(str(trade["margin_used"] if trade["status"] == "PLANNED" else "0"))
                for trade in active_trades
            ),
            Decimal("0"),
        )
        decision = evaluate_guard(
            account_equity=equity,
            day_start_equity=state.day_start_equity,
            peak_equity=state.peak_account_equity,
            daily_realized_pnl=state.daily_realized_pnl,
            consecutive_losses=state.consecutive_losses,
            halted=state.halted,
            halt_reason=state.halt_reason,
            binance_position_symbols=position_symbols,
            local_active_trades=active_trades,
            total_used_margin=account_margin + planned_margin,
        )
        if not decision.allowed and not state.halted:
            reason = "; ".join(decision.reasons)
            store.update_risk_state(halted=True, halt_reason=reason)
        return decision
    finally:
        store.close()
