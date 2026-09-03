from .risk_guard import check_live_guard


def main() -> int:
    try:
        decision = check_live_guard()
    except Exception:
        print("HALTED: Risk guard data unavailable.")
        return 1

    if decision.allowed:
        print("ALLOWED")
        return 0

    for reason in decision.reasons:
        print(f"HALTED: {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
