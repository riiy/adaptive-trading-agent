# Adaptive Trading Agent — STATE.md

**Last updated:** 2026-11-09  
**Project phase:** M4_SHADOW_RESEARCH_BUILD  
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
project_phase: M4_SHADOW_RESEARCH_BUILD
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

## 7. Completed milestone — M3-H001 preregistered signal kill test (archived)

- Mechanism: delayed information diffusion might cause positive prior 7-day momentum to predict the next 24h gross return.
- Frozen timestamp: 2026-11-09T06:46:19.012Z (same as M2 operator snapshot); 365-day maximum historical scope.
- One fixed BTC/ETH/USDT daily rule, no threshold tuning. Rule and strict kill criteria in `docs/experiments/M3-H001.md`.
- Chronological 60% development, 20% validation, final 20% sealed historical test.
- Weekly block bootstrap, deterministic seed, comparison versus cash, BTC and ETH unconditionally on identical daily observations.
- Historical test is not genuinely blind because M2 aggregate metrics have been observed; prospective evidence required after 2026-11-10 UTC.
- No execution/fill simulation, account allocation, order API, trading tickets or LLM agent in M3-H001.
- PR #6 merged to main; CI completed successfully with **68 pytest tests**.
- **2026-11-09 Ubuntu result:** `predeclared_decision=STOP_NO_SUFFICIENT_EVIDENCE`. H001 is **ARCHIVED_NON_TRADABLE**; lifecycle closed, no parameter rescue and no account simulation.
- Development: 214 observations, candidate mean forward 24h gross return -0.106114%; excess to USDT -0.106114%, BTC +0.051010%, ETH +0.112646%.
- Validation: 71 observations, candidate mean forward 24h gross return +0.329557%; excess to USDT +0.329557%, BTC +0.011455%, ETH **-0.216317%**.
- Validation bootstrap 95% lower bounds for daily mean excess: USDT -0.231528%, BTC -0.249006%, ETH -0.560181%; **all fail the strictly-positive predeclared lower-bound test**.
- Reserved historical-test sample: 72 days, **SEALED**; do not open after failure.
- Diagnostic labels are close-to-close gross forward returns, not executable trade returns. No claim that all possible trend mechanisms are invalidated; **this particular rule failed its frozen evidence gate**.

## 8. Research status

- `current_setup: null`
- `tradable_setups: 0`
- `trading_allowed: false`
- `account_simulation_allowed: false`
- `ticket_generation_allowed: false`
- `M3-H001: ARCHIVED_NON_TRADABLE / FAILED_PREDECLARED_GATE`

No active ATA strategy or approved simulation. **Do not relabel or retune H001** as a new strategy.

An economically distinct mechanism (e.g. volatility-expansion confirmation) may be considered as a *new, separately pre-registered* research candidate only if its marginal information value justifies the time/cost. It is not automatically authorized by H001's failure.

## 9. Current milestone — M4 prospective research feedback loop (in progress)

- **H001 remains permanently archived**; final 72-day historical holdout stays SEALED. M4 does not reuse that rule.
- Objective: measure whether a bounded LLM adds predictive/research value over deterministic baselines using **future-only** shadow decisions.
- First permissible observation date: **2026-11-10 00:00 UTC**. No retrospective forecasts, no account or trade simulation.
- Fixed daily decision timestamp 00:00 UTC; actual recorder runs at 00:15 UTC, and may issue records only between 00:05–00:45 UTC.
- Source data: previous **closed** BTCUSDT/ETHUSDT 1h candles and M2 as-of feature snapshot.
- Storage: independent `/var/lib/ata/shadow.sqlite3` with one write-once forecast per day/source and append-only next-day outcome; market DB opened read-only.
- Baseline: unconditional USDT selection plus 0.5 fixed direction probabilities; LLM is optional and must be explicitly enabled using server-side HTTPS credentials.
- Evaluation: positive 24h return Brier scores, gross close-to-close choice outcomes and contemporaneous BTC/ETH/USDT baselines, abstentions separately counted.
- **No executable entries, transaction cost model, real/Paper orders, parameter tuning or automatic strategy promotion.**
- PR #8 is **merged to main** (2026-11-09). GitHub CI passed 85 pytest tests, Ruff lint/format, Ubuntu install-script syntax, and shadow CLI checks.
- Operator reports `/etc/ata/shadow.env` has been configured. The `ata shadow score` command ran successfully against `/var/lib/ata/shadow.sqlite3`, but reports 0 settled observations for both baseline and LLM. This is expected before the first allowed prospective forecast; it does **not** verify that systemd loaded the LLM environment or that a forecast has run.
- First permissible observation: 2026-11-10 00:00 UTC; scheduled service at 00:15 UTC (08:15 UTC+8). Operational acceptance remains pending: timer activation, first baseline+LLM forecast, then delayed next-day feedback. Reaching 60 days warrants review, not promotion.

The approved engineering experiment starts with one research model. Stop or disable daily LLM usage if it does not demonstrate decision-relevant value after sufficient prospective evidence; preserve a low-cost deterministic pipeline.

## 10. Legacy research tracks — unchanged

- STOCK_RS_PULLBACK_v1 remains ARCHIVED_NON_TRADABLE and INVALIDATED_BY_ENGINE_ERROR.
- ICT Binance v0.1 remains archived after negative validation/test results.
- Existing A-share research constraints and the legacy CNY 500 per-trade risk limit remain scoped to that prior track. They are not silently transferred to ATA.

## 11. Next actions

1. Verify `ata-shadow-observe.timer` and `ata-shadow-settle.timer` are enabled and scheduled; inspect service unit's `EnvironmentFile` reference to `/etc/ata/shadow.env`.
2. On 2026-11-10 00:15 UTC (08:15 UTC+8), verify the first genuine prospective observation records both deterministic baseline and opted-in LLM. Confirm snapshot hash, timestamp, model/prompt version, and sanitized provider result.
3. On/after 2026-11-11 01:05 UTC (09:05 UTC+8), verify 24h feedback settlement, then run `ata shadow score`.
4. Compare LLM calibration and selection quality with the registered static baseline after sufficient prospective observations; disable low-value calls instead of adding agents.
5. Preserve H001's sealed holdout and all three permissions: trading=false, account_simulation=false, ticket_generation=false.

## 12. Stop conditions

- Do not add an execution adapter before the research and risk contracts are tested.
- Do not add more symbols, venues, or LLM agents without evidence that they change a decision.
- Stop or archive a strategy when its preregistered failure criteria are met.
- Do not expand infrastructure work if it does not improve the quality or reproducibility of the trading decision.
