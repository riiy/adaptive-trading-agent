# Adaptive Trading Agent — STATE.md

**Last updated:** 2026-11-09  
**Project phase:** M3_SIGNAL_HYPOTHESIS  
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
project_phase: M3_SIGNAL_HYPOTHESIS
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

## 5. Completed milestone — M1 market data

Implementation is present on `main`. PR #1, PR #2 and PR #4 are merged. On 2026-11-09 the operator supplied a real Ubuntu 24.04 `ata market verify` report and systemd/journal evidence:
- M1 data gate: **PASS**; database_issues=[].
- BTCUSDT and ETHUSDT each have 35,041 15m, 8,760 1h and 2,189 4h candles (91,980 total).
- History 364.667–365.0 days, zero missing bars, zero lag bars, all six series PASS.
- `ata-market-sync.timer` active; recent `ata-market-sync.service` completed successfully.
- Recent overlapping ETH 1h/4h fetches showed `rows_inserted=0` and `rows_unchanged=4`.
- This establishes **M1_ACCEPTED** for the core data and operating contract. Long-term timer reliability is not yet proven; monitor operationally without blocking M2.

- Unauthenticated Binance REST client using `data-api.binance.vision`.
- Server-time-based filtering of unfinished candles.
- Strict OHLCV, timestamp, interval, and ordering validation.
- Bounded retry behavior: 429 honors Retry-After; 418 stops immediately.
- Paginated synchronization with a three-bar overlap.
- SQLite WAL storage with exact decimal text, transactional writes, immutable candle keys, conflict detection, and SHA-256 batch provenance.
- CLI commands for market sync and data-quality audit.
- Ubuntu 24.04 systemd service/timer and installation script.
- M1 GitHub Actions CI passed: Ruff lint, Ruff format, and 41 pytest tests.
- PR #2 and PR #4 are merged.
- The server-side data gate, history coverage, freshness, gap checks, latest sync, and timer activity have been verified by operator-supplied output.

M1 acceptance requires:
1. Ruff and all automated tests pass.
2. A live public-REST smoke test on the Ubuntu server completes for both symbols and all three intervals.
3. Repeated sync is idempotent.
4. Audit output is reviewed; any historical gaps are explained or backfilled from source, never synthetically filled.
5. systemd timer and journald operation are verified.

## 6. Completed milestone — M2 descriptive features and passive benchmarks

M2 scope:
- Completed, aligned 1h BTCUSDT and ETHUSDT candles only.
- 24h and 7d close-to-close momentum, 7d realized annualized volatility, and last24h/preceding144h relative volume.
- Passive USDT cash, BTC buy-and-hold and ETH buy-and-hold with explicitly labeled hypothetical fee/slippage assumptions.
- Research snapshot strictly as-of: closed bars only, no future leakage, no orders, no model fitting.
- PR #5 merged to main, M2 GitHub CI passed all 59 tests.
- 2026-11-09 actual Ubuntu read-only snapshot: status DESCRIPTIVE_ONLY, same completed hour for BTC and ETH, 180-day USDT buy-and-hold 0%, BTC -8.357134%, ETH -7.627509% with **illustrative** 10bps fees and 5bps slippage per side.
- 24h momentum BTC -1.791035%, ETH -4.760456%; 7d momentum BTC -4.983123%, ETH -7.125438%; 7d historic annualized volatility BTC 41.143348%, ETH 60.260047%.
- M2 status: **M2_ACCEPTED**, descriptive baselines only, no evidence of alpha.

## 7. Current milestone — M3-H001 preregistered signal kill test

- Mechanism: delayed information diffusion might cause positive prior 7-day momentum to predict the next 24h gross return.
- Frozen timestamp: 2026-11-09T06:46:19.012Z (same as M2 operator snapshot); 365-day maximum historical scope.
- One fixed BTC/ETH/USDT daily rule, no threshold tuning. Rule and strict kill criteria in `docs/experiments/M3-H001.md`.
- Chronological 60% development, 20% validation, final 20% sealed historical test.
- Weekly block bootstrap, deterministic seed, comparison versus cash, BTC and ETH unconditionally on identical daily observations.
- Historical test is not genuinely blind because M2 aggregate metrics have been observed; prospective evidence required after 2026-11-10 UTC.
- No execution/fill simulation, account allocation, order API, trading tickets or LLM agent in M3-H001.
- PR #6 covers the M3-H001 diagnostic. GitHub CI passed: Ruff lint/format, CLI, Ubuntu installer checks, and **68 pytest tests**. The real Ubuntu historical diagnostic has not yet been run. If preregistered evidence fails, archive H001 without adjusting parameters.

## 8. Research status

No ATA strategy is active or authorized.

Potential future hypotheses:
- Trend / momentum continuation.
- Volatility expansion followed by trend confirmation.

These are unvalidated hypotheses, not trading signals. Each requires preregistration, baselines, time-ordered out-of-sample tests, cost stress, robustness analysis, and explicit stop criteria.

## 9. Legacy research tracks — unchanged

- STOCK_RS_PULLBACK_v1 remains ARCHIVED_NON_TRADABLE and INVALIDATED_BY_ENGINE_ERROR.
- ICT Binance v0.1 remains archived after negative validation/test results.
- Existing A-share research constraints and the legacy CNY 500 per-trade risk limit remain scoped to that prior track. They are not silently transferred to ATA.

## 10. Next actions

1. Review M3-H001 PR and CI test result.
2. After merging, update the Ubuntu app and run `ata research m3-h001 --db /var/lib/ata/market.sqlite3` once, recording the development and validation report.
3. Apply the preregistered kill criteria. If `STOP_NO_SUFFICIENT_EVIDENCE`, archive M3-H001. Do not retune it.
4. If `REVIEW_BEFORE_HISTORICAL_TEST`, separately evaluate holdout-release approval and genuine prospective signal evaluation, then model real execution costs before paper permissions.
5. Preserve `trading_allowed=false`, `account_simulation_allowed=false`, `ticket_generation_allowed=false`.

## 11. Stop conditions

- Do not add an execution adapter before the research and risk contracts are tested.
- Do not add more symbols, venues, or LLM agents without evidence that they change a decision.
- Stop or archive a strategy when its preregistered failure criteria are met.
- Do not expand infrastructure work if it does not improve the quality or reproducibility of the trading decision.
