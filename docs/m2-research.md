# M2 — Minimal research observation and benchmark contract

## Purpose

M1 is accepted for engineering readiness: 6 Binance Spot streams, about 365 days
of history, no reported missing bars, server timer active, and a successful
idempotent incremental sync observed on 2026-11-09.

M2 must turn historical data into **reproducible observations**, without
silently promoting those observations to strategies or trading permissions.

## Scope and exclusions

- Input: completed **1-hour BTCUSDT and ETHUSDT** candles already stored by M1.
- Compare passive holding benchmarks for **USDT**, **BTC**, **ETH** over the same
  aligned historical 180-day window by default.
- Do not use LLM, statistical optimization, live accounts or order submission.
- No 1m data, tick data, chain data, news, model fitting, or new infrastructure.

## Causal as-of convention

At timestamp `T`, a bar may be observed only when:

`close_time_ms < T`.

The analysis aligns both assets to the same latest completed one-hour candle.
Missing or unordered data causes a failure, not forward fill or interpolation.
An explicit `--asof` creates a historical replay; without it the system
requires freshness within two 1-hour bars.

Future candles inserted later must not alter a historical snapshot.

## Features — descriptive only

For each symbol:

1. **24-hour close-to-close return**, percentage.
2. **7-day close-to-close return**, percentage.
3. **7-day realized annualized volatility**: sample standard deviation of 168
   hourly log returns times `sqrt(24*365)`, expressed as a percentage.
4. **Volume relative to the previous period**: mean base volume in the latest
   24 closed hourly bars divided by mean volume in the preceding 144 bars.

No threshold is fitted and none of these metrics authorizes a trade.

## Passive benchmarks

For the same 180-day window:

- **USDT cash**: fixed 0% USDT nominal return, excluding yield and stablecoin risk.
- **BTC buy-and-hold**: first observed closing price to last observed closing
  price, with hypothetical entry and exit costs.
- **ETH buy-and-hold**: same treatment and aligned timestamps.

The modeled net return is

`(last_close / first_close) * (1 - c)^2 - 1`, with
`c = (fee_bps_per_side + slippage_bps_per_side) / 10000`.

Defaults (fee 10 bps + slippage 5 bps per side) are **illustrative**, not a
claim about account-specific Binance fees or executable close-price fills.
The baseline is an opportunity-cost reference, not an investable signal.

## Run on Ubuntu

After the M2 PR merges and application update:

```bash
sudo -u ata /opt/ata/venv/bin/ata research snapshot \
  --db /var/lib/ata/market.sqlite3 \
  --days 180 --fee-bps 10 --slippage-bps 5
```

For a stable replay independent of today's date, provide
`--asof 2026-11-01T00:00:00Z` (or another valid UTC historical timestamp).

## Acceptance

- All lint and unit tests pass.
- Reports have a common as-of timestamp and synchronized BTC/ETH boundaries.
- No future candles affect a historical replay.
- Missing history or gaps fail closed.
- Larger fee/slippage assumptions monotonically reduce passive net returns.
- The command does not mutate the SQLite database or grant trading permission.
- A real-server snapshot executes successfully using M1's current database.

## Stop rule

Completing M2 does **not** demonstrate alpha. Do not add indicators to improve
a pretty report. In M3 choose at most two economic hypotheses and test them
against these fixed benchmarks under a pre-registered time-ordered protocol.
