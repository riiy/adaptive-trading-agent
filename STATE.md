# Adaptive Trading Agent — STATE.md

**Last updated:** 2026-11-08  
**Project phase:** M0_FOUNDATION  
**System mode:** RESEARCH_ONLY  
**Live trading:** Prohibited

## 1. Objective

Build a reproducible, risk-governed decision system that can determine whether a trading strategy has durable positive expectancy after costs. Engineering exists to support that decision; infrastructure completeness is not an objective by itself.

## 2. Active system scope

- Venue: Binance Spot only.
- Initial symbols: BTCUSDT, ETHUSDT.
- Direction: long-only spot; no leverage, margin, or futures.
- Maximum concurrent positions: 1.
- Research capital ceiling: CNY 30,000.
- Proposed drawdown guardrail: 20%; not a guarantee and not live-authorized.
- ATA single-trade risk budget: not yet approved.
- Initial live allocation proposal: CNY 1,000–3,000; not authorized.
- Runtime: server deployment planned; credentials are not stored in Git.
- LLM: research and explanation only; not in a latency-critical execution path.

## 3. Permission state

```yaml
project_phase: M0_FOUNDATION
system_mode: RESEARCH_ONLY
trading_allowed: false
account_simulation_allowed: false
ticket_generation_allowed: false
active_strategy: null
authorized_strategies: []
```

These permissions must remain false until separate evidence and approval gates are passed. Creating infrastructure does not grant trading permission.

## 4. Current milestone — M0

Build and verify:

1. Immutable typed decision records.
2. Append-only decision journal.
3. Fail-closed risk and permission governor.
4. Automated tests and CI.
5. Read-only market data ingestion only after M0 passes.

M0 acceptance: tests prove research mode rejects order actions, non-order decisions remain recordable, unhealthy data fails closed, and the journal can replay recorded decisions.

## 5. Research status

No ATA strategy is active or authorized.

Potential future hypotheses:
- Trend / momentum continuation.
- Volatility expansion followed by trend confirmation.

These are unvalidated hypotheses, not trading signals. Each requires preregistration, baselines, time-ordered out-of-sample tests, cost stress, robustness analysis, and explicit stop criteria.

## 6. Legacy research tracks — unchanged

- STOCK_RS_PULLBACK_v1 remains ARCHIVED_NON_TRADABLE and INVALIDATED_BY_ENGINE_ERROR.
- ICT Binance v0.1 remains archived after negative validation/test results.
- Existing A-share research constraints and the legacy CNY 500 per-trade risk limit remain scoped to that prior track. They are not silently transferred to ATA.

## 7. Next actions

1. Complete M0 implementation and run tests/CI.
2. Review the server environment without exposing credentials.
3. Add public, read-only Binance Spot market data ingestion.
4. Produce a data-quality and replayability report before strategy research.

## 8. Stop conditions

- Do not add an execution adapter before the research and risk contracts are tested.
- Do not add more symbols, venues, or LLM agents without evidence that they change a decision.
- Stop or archive a strategy when its preregistered failure criteria are met.
- Do not expand infrastructure work if it does not improve the quality or reproducibility of the trading decision.
