# Adaptive Trading Agent (ATA)

**Status: RESEARCH_ONLY. No live trading is enabled.**

ATA is a research-first system for observing Binance Spot markets, recording reproducible decisions, evaluating candidate strategies, and enforcing independent risk and permission controls.

The initial research universe is limited to:

- `BTCUSDT`
- `ETHUSDT`

The system must be able to abstain or stay in cash. No strategy is presumed profitable.

## Non-negotiable safety constraints

- `trading_allowed: false`
- `account_simulation_allowed: false`
- `ticket_generation_allowed: false`
- No leverage, futures, margin, withdrawals, or transfer permissions.
- No exchange credentials or LLM API keys in source control.
- Research code must not have a path to submit live orders.
- A backtest or Testnet pass does not grant live-trading permission.

The public repository must contain placeholders only. Store secrets in the deployment environment or a secrets manager.

## Development baseline

- Python 3.12+
- `src/` layout
- pytest for tests
- ruff for linting and formatting
- Small, auditable modules before introducing distributed infrastructure

## Current milestone

**M3-H001 archived; research paused pending a distinct hypothesis**

M0, M1 and M2 are merged into main. The M2 research snapshot ran successfully on Ubuntu on 2026-11-09, giving an aligned 180-day passive USDT/BTC/ETH benchmark. M3-H001's frozen seven-day momentum rule **failed** its predeclared evidence gate on 2026-11-09 and was archived. Its 72-day historical test remains sealed; no strategy or simulation is authorized.

Initial collection scope:
- Symbols: BTCUSDT and ETHUSDT.
- Intervals: 15m, 1h, and 4h.
- 1m is deferred until a concrete research or execution-model need exists.
- Public market-data endpoints only; no API key is needed.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

## Market data quick start

After installing the package, fetch the last 365 days of completed candles:

```bash
ata market sync --symbols BTCUSDT ETHUSDT --intervals 15m 1h 4h --lookback-days 365 --db data/ata.sqlite3
ata market audit --symbol BTCUSDT --interval 1h --db data/ata.sqlite3
ata market verify --db data/ata.sqlite3 --min-history-days 350 --max-lag-bars 2
```

The collector uses Binance's unauthenticated market-data-only REST host, excludes unfinished candles, preserves decimal precision, and fails on conflicting historical candles. See [Ubuntu 24.04 deployment](deploy/ubuntu24/README.md).

## M2 research snapshot (read-only)

After the M2 PR merges, analyze the aligned last 180 days using **closed 1h bars only**:

```bash
ata research snapshot --db data/ata.sqlite3 --days 180 --fee-bps 10 --slippage-bps 5
```

This outputs descriptive 24h/7d momentum, 7d realized volatility, relative volume,
and fee/slippage-adjusted passive BTC/ETH buy-and-hold vs USDT cash. It is **not**
a trading strategy and cannot generate orders. See [M2 research contract](docs/m2-research.md).

## M3 first experiment — fixed signal kill test

For reproducibility, the archived M3-H001 diagnostic remains available:

```bash
ata research m3-h001 --db data/ata.sqlite3
```

The diagnostic's cutoff, rule, data split and bootstrap seed remain frozen. It returned `STOP_NO_SUFFICIENT_EVIDENCE`; rerunning it cannot reopen the archived strategy. The historical test set is sealed. It does not simulate a trading account.

## Project documents

- [Current state](STATE.md)
- [Architecture](docs/architecture.md)
- [Market data contract](docs/market-data.md)
- [M1 server acceptance](docs/m1-acceptance.md)
- [M2 research and benchmark contract](docs/m2-research.md)
- [M3-H001 pre-registered momentum diagnostic](docs/experiments/M3-H001.md)
- [Ubuntu 24.04 deployment](deploy/ubuntu24/README.md)
- [Risk policy](docs/risk-policy.md)
- [Research protocol](docs/research-protocol.md)

## Operating principle

The first objective is not to make an AI trade. It is to make a system that can reliably explain what it observed, what it decided, why an action was rejected or allowed, and how that decision can later be evaluated without hindsight leakage.
