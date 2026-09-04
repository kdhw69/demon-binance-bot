from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple

from .config import SYMBOLS
from .risk_guard import GuardDecision, check_live_guard
from .risk_manager import RiskPlan, get_latest_risk_plans


_DIRECTION_TO_SIDE = {
    "LONG": "BUY",
    "SHORT": "SELL",
}


@dataclass(frozen=True)
class ExecutionPreview:
    symbol: str
    side: str
    signal_time: datetime
    quantity: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    planned_risk: Decimal
    margin_used: Decimal


@dataclass(frozen=True)
class DryRunResult:
    allowed: bool
    reasons: Tuple[str, ...]
    previews: Tuple[ExecutionPreview, ...]


def build_execution_previews(
    decision: GuardDecision,
    plans: Dict[str, Optional[RiskPlan]],
) -> DryRunResult:
    if not decision.allowed:
        return DryRunResult(
            allowed=False,
            reasons=decision.reasons,
            previews=(),
        )

    previews = []
    for symbol in SYMBOLS:
        plan = plans.get(symbol)
        if plan is None:
            continue
        if plan.symbol != symbol:
            raise ValueError("Risk-plan symbol does not match its mapping key.")
        if plan.direction not in _DIRECTION_TO_SIDE:
            raise ValueError("Risk-plan direction must be LONG or SHORT.")
        if plan.quantity <= 0:
            raise ValueError("Risk-plan quantity must be positive.")
        previews.append(
            ExecutionPreview(
                symbol=symbol,
                side=_DIRECTION_TO_SIDE[plan.direction],
                signal_time=plan.signal_time,
                quantity=plan.quantity,
                entry_price=plan.entry_price,
                stop_loss=plan.stop_loss,
                take_profit=plan.take_profit,
                planned_risk=plan.risk_amount,
                margin_used=plan.margin_used,
            )
        )

    return DryRunResult(
        allowed=True,
        reasons=(),
        previews=tuple(previews),
    )


def run_dry_run_cycle(database_path=None) -> DryRunResult:
    decision = check_live_guard(database_path)
    if not decision.allowed:
        return DryRunResult(
            allowed=False,
            reasons=decision.reasons,
            previews=(),
        )

    plans = get_latest_risk_plans()
    return build_execution_previews(decision, plans)