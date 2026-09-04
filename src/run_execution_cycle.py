from .execution_engine import run_dry_run_cycle


def main() -> int:
    print("DRY RUN: no orders will be submitted.")

    try:
        result = run_dry_run_cycle()
    except Exception:
        print("Dry-run execution cycle failed safely.")
        return 1

    if not result.allowed:
        print("Execution blocked by risk guard.")
        for reason in result.reasons:
            print(f"- {reason}")
        return 0

    if not result.previews:
        print("No approved trade plans.")
        return 0

    for preview in result.previews:
        print(
            f"{preview.symbol}: {preview.side} preview | "
            f"quantity: {preview.quantity:f} | "
            f"entry reference: {preview.entry_price:f} | "
            f"stop loss: {preview.stop_loss:f} | "
            f"take profit: {preview.take_profit:f} | "
            f"planned risk: {preview.planned_risk:f} | "
            f"margin: {preview.margin_used:f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())