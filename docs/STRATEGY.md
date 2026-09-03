# Confirmed Strategy

## Market and Execution

| Parameter | Value |
|---|---|
| Symbols | BTCUSDT, ETHUSDT, SOLUSDT |
| Timeframe | 2h |
| Margin mode | Isolated |
| Leverage | 10x |
| Maximum simultaneous positions | 3 |

## Risk Management

| Parameter | Value |
|---|---|
| Risk per trade | 1% of account equity |
| Maximum combined open risk | 2.5% |
| Maximum margin per position | 10% |
| Maximum total margin usage | 30% |
| Daily loss limit | 5% |
| Consecutive loss limit | 4 |
| Maximum drawdown stop | 15% |

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
