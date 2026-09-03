from collections import defaultdict
from decimal import Decimal
import sys

from .backtest_engine import run_historical_backtest, write_results


def _percent(value: Decimal) -> str:
    return f"{value * Decimal('100'):.4f}%"


def _grouped(trades, attribute):
    grouped = defaultdict(list)
    for trade in trades:
        grouped[getattr(trade, attribute)].append(trade)
    return grouped


def _print_group(label, trades):
    if not trades:
        print(f"{label}: trades=0")
        return
    wins = [trade for trade in trades if trade.realized_pnl > 0]
    losses = [trade for trade in trades if trade.realized_pnl < 0]
    gross_profit = sum((trade.realized_pnl for trade in wins), Decimal("0"))
    gross_loss = abs(sum((trade.realized_pnl for trade in losses), Decimal("0")))
    profit_factor = "infinite" if not gross_loss else f"{gross_profit / gross_loss:.4f}"
    print(
        f"{label}: trades={len(trades)}, win rate={_percent(Decimal(len(wins)) / Decimal(len(trades)))}, "
        f"profit factor={profit_factor}"
    )


def main() -> int:
    try:
        diagnostic = "--diagnostic-ignore-max-drawdown-halt" in sys.argv[1:]
        result = run_historical_backtest(diagnostic_ignore_max_drawdown_halt=diagnostic)
        write_results(result)
    except Exception:
        print("Historical backtest failed safely.")
        return 1

    start = result.equity_curve[0]["time_utc"] if result.equity_curve else "unavailable"
    end = result.equity_curve[-1]["time_utc"] if result.equity_curve else "unavailable"
    wins = [trade for trade in result.trades if trade.realized_pnl > 0]
    losses = [trade for trade in result.trades if trade.realized_pnl < 0]
    gross_profit = sum((trade.realized_pnl for trade in wins), Decimal("0"))
    gross_loss = abs(sum((trade.realized_pnl for trade in losses), Decimal("0")))
    count = Decimal(len(result.trades) or 1)
    expectancy = sum((trade.realized_pnl for trade in result.trades), Decimal("0")) / count
    average_profit = gross_profit / Decimal(len(wins)) if wins else Decimal("0")
    average_loss = -gross_loss / Decimal(len(losses)) if losses else Decimal("0")
    print(f"Test start: {start}")
    print(f"Test end: {end}")
    print(f"Initial equity: {result.initial_equity:f} USDT")
    print(f"Final equity: {result.final_equity:f} USDT")
    print(f"Total return: {_percent(result.total_return)}")
    print(f"Annualized return: {_percent(result.annualized_return)}")
    print(f"Maximum drawdown: {_percent(result.maximum_drawdown)}")
    print(f"Number of trades: {len(result.trades)}")
    print(f"Win rate: {_percent(Decimal(len(wins)) / count)}")
    print(f"Profit factor: {'infinite' if not gross_loss else f'{gross_profit / gross_loss:.4f}'}")
    print(f"Average profit: {average_profit:f} USDT")
    print(f"Average loss: {average_loss:f} USDT")
    print(f"Expectancy per trade: {expectancy:f} USDT")
    print(f"Total fees: {result.total_fees:f} USDT")
    print(f"Total estimated slippage cost: {result.total_slippage:f} USDT")
    print(f"Net funding cost or credit: {-result.net_funding:f} USDT")
    _print_group("LONG", [trade for trade in result.trades if trade.direction == "LONG"])
    _print_group("SHORT", [trade for trade in result.trades if trade.direction == "SHORT"])
    for symbol, trades in _grouped(result.trades, "symbol").items():
        _print_group(symbol, trades)
    print(f"Consecutive-loss cooldowns: {len(result.consecutive_loss_cooldowns)}")
    for cooldown in result.consecutive_loss_cooldowns:
        print(
            f"Consecutive-loss cooldown: {cooldown['started_utc']} to "
            f"{cooldown['ends_utc']} ({cooldown['duration_hours']} hours)"
        )
    print("Risk-rule rejection counts:")
    for rule, count in result.rejection_counts.items():
        print(f"{rule}: {count}")
    print(f"Risk-halt events: {len(result.risk_halts)}")
    for event in result.risk_halts:
        print(f"Risk halt: {event['time_utc']} - {event['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
