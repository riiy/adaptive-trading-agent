# ATA research protocol

## Required sequence

Economic mechanism → data → benchmark → sample → robustness → costs → risk → executability.

## Experiment registration

Before running an experiment, record:

- Hypothesis and proposed economic mechanism.
- Market, symbols, timeframe, and observation period.
- Data source and snapshot/version identifiers.
- Baselines and benchmark definitions.
- Train, validation, and untouched test periods.
- Parameters and the complete search range.
- Fee, spread, slippage, and market-impact assumptions.
- Primary metrics and stopping criteria.

## Evidence requirements

Report at least:

- Net return after modeled trading costs.
- Maximum drawdown and time under water.
- Median trade and return distribution.
- Tail losses and contribution of the largest winners.
- Turnover, exposure, and time in cash.
- Performance by time period and market regime.
- Parameter sensitivity and cost stress.
- Walk-forward or other strictly time-ordered out-of-sample results.

Use block-based or otherwise dependence-aware resampling where appropriate. Do not treat serially dependent trades as automatically independent observations.

## Anti-overfitting rules

- Do not repeatedly tune a failed candidate against the same test set.
- Keep a final untouched test period.
- Record every attempted variant, including failures.
- Do not promote a strategy based on a small number of exceptional trades.
- A sample-count target is not a substitute for adequate independent evidence.

## Current status

No strategy is active or authorized. Trend continuation and volatility-expansion confirmation are unvalidated research hypotheses only; they must be registered and given explicit stop criteria before testing.
