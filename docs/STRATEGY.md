# Confirmed Strategy

## Market and Execution

| Parameter | Value |
|---|---|
| Symbols | BTCUSDT, ETHUSDT, SOLUSDT |
| Timeframe | 4h |
| Margin mode | Isolated |
| Leverage | 10x |
| Maximum simultaneous positions | 3 |

## Risk Management

| Parameter | Value |
|---|---|
| Risk per trade | 0.25% of account equity |
| Maximum combined open risk | 0.625% |
| Maximum margin per position | 10% |
| Maximum total margin usage | 30% |
| Daily loss limit | 5% |
| Consecutive loss limit | 4 |
| Maximum drawdown stop | 15% |

After 4 consecutive losing trades, new entries are blocked for exactly 12 hours.
The consecutive-loss count resets when the cooldown begins, existing positions
continue to be managed, and entries resume automatically at cooldown expiry.

## Indicators and Exits

Signals are evaluated only after a candle has fully closed. The Donchian breakout
levels use the 20 candles immediately before the signal candle, excluding the
signal candle itself. ATR uses Wilder smoothing.

| Parameter | Value |
|---|---|
| EMA period | 200 |
| Donchian Channel period | 20 |
| ATR period | 14 |
| Stop loss distance | 1.5 ATR |
| Take profit distance | 3 ATR |
