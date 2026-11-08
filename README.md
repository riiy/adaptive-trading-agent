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

**M0 — Verified decision and risk boundary**

1. Define typed decision records.
2. Implement a fail-closed risk/permission governor.
3. Record and replay decision events.
4. Add tests proving that research mode rejects all order intents.
5. Establish CI before connecting exchange data or an LLM.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
ruff check .
```

## Project documents

- [Current state](STATE.md)
- [Architecture](docs/architecture.md)
- [Risk policy](docs/risk-policy.md)
- [Research protocol](docs/research-protocol.md)

## Operating principle

The first objective is not to make an AI trade. It is to make a system that can reliably explain what it observed, what it decided, why an action was rejected or allowed, and how that decision can later be evaluated without hindsight leakage.
