# Demon Binance Bot

Private single-user Binance USD-M Futures Demo trading bot.

This project is locked to the Binance Futures Demo API. It does not support Binance production trading.

## Confirmed Strategy

- Symbols: BTCUSDT, ETHUSDT, SOLUSDT
- Timeframe: 4h
- Position mode: One-way
- Margin mode: Isolated
- Leverage: 10x
- Risk per trade: 0.25% of account equity
- Maximum combined open risk: 0.625%
- Maximum total margin usage: 30%
- Daily realized loss limit: 5%
- Consecutive-loss cooldown: 12 hours after 4 losses
- Permanent maximum-drawdown stop: 15%

See `docs/STRATEGY.md` for the complete confirmed rules.

## Safety Controls

- Binance Futures Demo URL is enforced in the client.
- Dry-run is the default execution mode.
- Demo orders require a CLI flag, confirmation phrase, and environment opt-in.
- Account mode, isolated margin, and leverage are verified before entry.
- Local trades, Binance positions, and protection orders are reconciled.
- Entry orders require confirmed `FILLED` status.
- Protection failure triggers cancellation and a reduce-only emergency close.
- Ambiguous entry state blocks further execution.
- Duplicate active-symbol and repeated signal-candle execution are blocked.
- A process lock prevents overlapping execution cycles.
- Closed trades include realized PnL, commissions, and funding adjustments.

These controls reduce operational risk but cannot guarantee profitability or eliminate exchange, network, software, liquidity, or market risk.

## Installation

Python 3.12 is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a local `.env` file:

```text
BINANCE_API_KEY=your_demo_api_key
BINANCE_API_SECRET=your_demo_api_secret
BINANCE_BASE_URL=https://demo-fapi.binance.com
```

Never commit `.env` or API credentials.

## Tests

```bash
python -m unittest discover -s tests -q
```

## Safe Dry Run

```bash
python -m src.run_demo_bot_cycle
```

The default command never submits orders.

## Demo Account Configuration

This command may change the Demo account to the confirmed One-way, Isolated, 10x configuration. It stops safely if open positions or orders exist.

```bash
python -m src.configure_demo_account
```

## Demo Order Execution

Demo order execution is reserved for the designated Mac mini only. Do not run the execution command from multiple computers.

The guarded execution command requires all three controls:

```bash
DEMON_DEMO_EXECUTION_ENABLED=YES python -m src.run_demo_bot_cycle --execute-demo --confirmation DEMO_ONLY
```

Do not save the execution opt-in permanently in `.env`. Set it only for the single command or the designated Mac mini service.

## Local State

Runtime state is stored locally under `data/`, including `trading.db`. The directory is ignored by Git.

After Demo execution begins, the Mac mini database is the authoritative state. Do not copy an older database from another computer and do not run the bot from the MacBook.

## Development Workflow

Before changing computers:

```bash
python -m unittest discover -s tests -q
git status -sb
git push
```

On the other development computer:

```bash
git status -sb
git pull --ff-only
python -m unittest discover -s tests -q
```

Resolve or stash local changes before pulling. Never use destructive Git commands to discard unverified work.
