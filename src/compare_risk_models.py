from decimal import Decimal

from .risk_model_comparison import run_risk_model_comparison


def pct(value):
    return f"{value * Decimal('100'):.4f}%"


def main() -> int:
    try:
        results, selected = run_risk_model_comparison()
    except Exception:
        print("Risk-model comparison failed safely.")
        return 1

    print("| Model | Period | Final Equity | Return | Annualized | Max DD | Net PF | Trades | Win Rate | Total Costs | Halt |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for item in results:
        metrics = item.metrics
        halt = item.result.risk_halts[-1]["time_utc"] if item.result.risk_halts else "none"
        costs = metrics.total_fees + metrics.total_slippage + abs(metrics.net_funding)
        print(f"| {item.model} | {item.period} | {metrics.final_equity:f} | {pct(metrics.total_return)} | {pct(metrics.annualized_return)} | {pct(metrics.maximum_drawdown)} | {metrics.net_profit_factor:.4f} | {metrics.trades} | {pct(metrics.win_rate)} | {costs:f} | {halt} |")
    print(f"Selected model: {selected.model if selected else 'NO_MODEL_QUALIFIED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
