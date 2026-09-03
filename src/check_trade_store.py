import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .trade_store import TradeStore


def main() -> int:
    try:
        with tempfile.TemporaryDirectory() as directory:
            store = TradeStore(Path(directory) / "trading.db")
            trade_id = store.record_planned_trade(
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.001"),
                entry_price=Decimal("50000.12345678"),
                stop_loss_price=Decimal("49000.12345678"),
                take_profit_price=Decimal("52000.12345678"),
                planned_risk=Decimal("1.00000001"),
                margin_used=Decimal("5.00000001"),
            )
            store.mark_open(trade_id, datetime.now(timezone.utc))
            store.mark_closed(
                trade_id,
                Decimal("50100.12345678"),
                Decimal("0.10000001"),
                datetime.now(timezone.utc),
            )
            state = store.read_risk_state()
            active_trades = store.read_active_trades()
            store.close()
            if state.daily_realized_pnl != Decimal("0.10000001") or active_trades:
                raise ValueError("Trade store verification failed.")
    except Exception:
        print("Trade store check failed.")
        return 1

    print("Trade store check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
