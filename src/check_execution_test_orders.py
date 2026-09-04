from .execution_engine import run_dry_run_cycle
from .order_service import validate_execution_previews


def main() -> int:
    print("TEST ORDER ONLY: no position will be created.")

    try:
        dry_run = run_dry_run_cycle()

        if not dry_run.allowed:
            print("Execution blocked by risk guard.")
            for reason in dry_run.reasons:
                print(f"- {reason}")
            return 0

        if not dry_run.previews:
            print("No approved trade plans.")
            return 0

        results = validate_execution_previews(dry_run.previews)
    except Exception:
        print("Execution test-order validation failed safely.")
        return 1

    for preview in dry_run.previews:
        print(
            f"{preview.symbol}: {preview.side} test order accepted: "
            f"{results[preview.symbol]}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())