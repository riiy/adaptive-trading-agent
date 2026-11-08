# ATA architecture — M0

## Objective

Build a reproducible decision loop with an independent permission boundary. The initial system is research-only and has no exchange order-submission adapter.

## Current implementation

- Domain: immutable decision records and explicit system/action enums.
- Risk: fail-closed authorization for order-like actions.
- Journal: append-only JSONL decision history.
- Config: explicit BTCUSDT / ETHUSDT research universe and disabled permissions.
- CI: automated lint, format, and unit-test checks.

## Planned components, not yet implemented

1. Market observer: public Binance Spot REST/WebSocket ingestion, timestamp normalization, health checks, and immutable snapshots.
2. Feature/state layer: deterministic market features and market-state estimates.
3. Research: registered hypotheses, reproducible backtests, baselines, and out-of-sample evaluation.
4. Paper broker: simulated fills with fee, spread, and slippage assumptions.
5. Feedback: prediction outcomes, realized execution outcomes, and separately labelled counterfactuals.
6. Research agent: constrained experiment proposal and reporting tools.

## Trust boundaries

- LLM output is untrusted input. It cannot modify risk policy or call exchange order endpoints.
- Market data is untrusted until schema, timestamp, freshness, and consistency checks pass.
- Risk authorization is separate from strategy selection.
- No live execution module is present in M0.
- Secrets are injected at runtime and never stored in the repository.

## Design rule

Keep the first deployment as a small Python service. Add queues, distributed services, or additional agents only after a measured bottleneck justifies them.
