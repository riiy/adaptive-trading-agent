# Adaptive Trading Agent — STATE.md

**Last updated:** 2026-11-09  
**Project phase:** M1_VERIFY_PENDING  
**System mode:** RESEARCH_ONLY  
**Live trading:** Prohibited

## 1. Objective

Build a reproducible, risk-governed decision system that can determine whether a trading strategy has durable positive expectancy after costs. Engineering exists to support that decision; infrastructure completeness is not an objective by itself.

## 2. Active system scope

- Venue: Binance Spot only.
- Initial symbols: BTCUSDT, ETHUSDT.
- Direction: long-only spot; no leverage, margin, or futures.
- Initial research intervals: 15m, 1h, 4h.
- 1m is deferred until a concrete strategy or execution-model requirement justifies its additional data volume.
- Maximum concurrent positions: 1.
- Research capital ceiling: CNY 30,000.
- Proposed drawdown guardrail: 20%; not a guarantee and not live-authorized.
- ATA single-trade risk budget: not yet approved.
- Initial live allocation proposal: CNY 1,000–3,000; not authorized.
- Deployment target: Ubuntu 24.04 LTS, Python 3.12, systemd, SQLite.
- LLM: research and explanation only; not in a latency-critical execution path.
- Binance market data: public read-only endpoints; no API key required for M1.

## 3. Permission state

```yaml
project_phase: M1_VERIFY_PENDING
system_mode: RESEARCH_ONLY
trading_allowed: false
account_simulation_allowed: false
ticket_generation_allowed: false
active_strategy: null
authorized_strategies: []
```

These permissions must remain false until separate evidence and approval gates are passed. Creating infrastructure or collecting data does not grant trading permission.

## 4. Completed milestone — M0 foundation

- Immutable typed decision records.
- Append-only JSONL decision journal.
- Fail-closed risk and permission governor.
- Automated CI.
- 19 pytest tests passed on the M0 PR head, including research-mode rejection, invalid inputs, unhealthy data, drawdown, position limits, exit-path handling, and journal replay.
- PR #1 has been merged. M0 implementation is present on main.

## 5. Current milestone — M1 market data

Implementation is present on `main`. PR #1 and PR #2 are merged. The operator confirms Ubuntu 24.04 deployment and successful live Binance data downloads. This user-reported fact does not yet establish database quality, idempotence on the server, or continuous timer health.

- Unauthenticated Binance REST client using `data-api.binance.vision`.
- Server-time-based filtering of unfinished candles.
- Strict OHLCV, timestamp, interval, and ordering validation.
- Bounded retry behavior: 429 honors Retry-After; 418 stops immediately.
- Paginated synchronization with a three-bar overlap.
- SQLite WAL storage with exact decimal text, transactional writes, immutable candle keys, conflict detection, and SHA-256 batch provenance.
- CLI commands for market sync and data-quality audit.
- Ubuntu 24.04 systemd service/timer and installation script.
- M1 GitHub Actions CI passed: Ruff lint, Ruff format, and 41 pytest tests.
- PR #2 is merged; Binance data downloads have succeeded on the Ubuntu server (operator report).
- A new read-only six-stream readiness gate is being reviewed in PR #3.
- Database audit output, history coverage, staleness, idempotence, and systemd timer health have not been independently verified.

M1 acceptance requires:
1. Ruff and all automated tests pass.
2. A live public-REST smoke test on the Ubuntu server completes for both symbols and all three intervals.
3. Repeated sync is idempotent.
4. Audit output is reviewed; any historical gaps are explained or backfilled from source, never synthetically filled.
5. systemd timer and journald operation are verified.

## 6. Research status

No ATA strategy is active or authorized.

Potential future hypotheses:
- Trend / momentum continuation.
- Volatility expansion followed by trend confirmation.

These are unvalidated hypotheses, not trading signals. Each requires preregistration, baselines, time-ordered out-of-sample tests, cost stress, robustness analysis, and explicit stop criteria.

## 7. Legacy research tracks — unchanged

- STOCK_RS_PULLBACK_v1 remains ARCHIVED_NON_TRADABLE and INVALIDATED_BY_ENGINE_ERROR.
- ICT Binance v0.1 remains archived after negative validation/test results.
- Existing A-share research constraints and the legacy CNY 500 per-trade risk limit remain scoped to that prior track. They are not silently transferred to ATA.

## 8. Next actions

1. Review and merge the M1 readiness-gate PR.
2. On Ubuntu, run `ata market verify --db /var/lib/ata/market.sqlite3 --min-history-days 350 --max-lag-bars 2`.
3. Confirm the five-minute systemd timer, recurring journal runs and any sync failures.
4. If the gate passes, explicitly record M1 acceptance and begin the smallest sufficient M2 feature research task.
5. If the gate fails, repair only the reported data issue before proceeding.

## 9. Stop conditions

- Do not add an execution adapter before the research and risk contracts are tested.
- Do not add more symbols, venues, or LLM agents without evidence that they change a decision.
- Stop or archive a strategy when its preregistered failure criteria are met.
- Do not expand infrastructure work if it does not improve the quality or reproducibility of the trading decision.
