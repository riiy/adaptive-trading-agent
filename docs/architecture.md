# ATA architecture — M4

## Objective

Build a reproducible decision loop with an independent permission boundary. The initial system is research-only and has no exchange order-submission adapter.

## Current implementation

- Domain: immutable decision records and explicit system/action enums.
- Risk: fail-closed authorization for order-like actions.
- Journal: append-only JSONL decision history.
- Config: explicit BTCUSDT / ETHUSDT research universe and disabled permissions.
- Market data: unauthenticated Binance REST client, completed-kline validation, bounded retry handling, and paginated synchronization.
- Storage: SQLite WAL, exact decimal text columns, immutable candle primary keys, batch hashes, and ingestion provenance.
- Operations: Ubuntu 24.04 systemd service/timer and least-privilege data directory.
- M2 research: read-only aligned 1h feature snapshot and USDT/BTC/ETH passive benchmarks.
- M3 mechanism screen: archived after failing its preregistered gate, with historical holdout sealed.
- M4 shadow research: strictly future-dated daily frozen observations, optional bounded LLM
  structured forecasts, write-once separate SQLite journal, append-only delayed 24h
  feedback, and same-day static benchmarks. No action/order API.
- CI: automated lint, format, and unit-test checks.

## Planned components, not yet implemented

1. Streaming observer: public Binance Spot WebSocket ingestion, reconnect handling, and REST reconciliation.
2. State classification: any future regime labels or probabilistic estimates need independent evidence.
3. Research: registered hypotheses, reproducible backtests and out-of-sample evaluation.
4. Paper broker: simulated fills with fee, spread, and slippage assumptions.
5. Feedback: prediction outcomes, realized execution outcomes, and separately labelled counterfactuals.
6. Research agent: constrained experiment proposal and reporting tools.

## Trust boundaries

- LLM output is untrusted input. It cannot modify risk policy or call exchange order endpoints.
- Market data is untrusted until schema, timestamp, freshness, and consistency checks pass.
- Risk authorization is separate from strategy selection.
- The market-data client uses only public REST endpoints; there is no account or order API client.
- Secrets are injected at runtime and never stored in the repository.

## Design rule

Keep the first deployment as a small Python service. Add queues, distributed services, or additional agents only after a measured bottleneck justifies them.
