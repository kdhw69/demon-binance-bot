from decimal import Decimal

from .timeframe_comparison import run_comparison


def _pct(value: Decimal) -> str:
    return f"{value * Decimal('100'):.4f}%"


def main() -> int:
    try:
        metrics = run_comparison()
    except Exception:
        print("Timeframe comparison failed safely.")
        return 1

    print(
        "| Timeframe | Period | Final Equity | Return | Annualized | Max DD | Trades | "
        "Win Rate | Gross PF | Net PF | Fees | Slippage | Funding | Avg Net/Trade | Profitable Months |"
    )
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in metrics:
        print(
            f"| {item.timeframe} | {item.period} | {item.final_equity:f} | {_pct(item.total_return)} | "
            f"{_pct(item.annualized_return)} | {_pct(item.maximum_drawdown)} | {item.trades} | "
            f"{_pct(item.win_rate)} | {item.gross_profit_factor:.4f} | {item.net_profit_factor:.4f} | "
            f"{item.total_fees:f} | {item.total_slippage:f} | {item.net_funding:f} | "
            f"{item.average_net_profit:f} | {item.profitable_months} / {item.tested_months} |"
        )
    winner = max((item for item in metrics if item.period == "development"), key=lambda item: item.final_equity)
    print(f"Development-period winner: {winner.timeframe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
