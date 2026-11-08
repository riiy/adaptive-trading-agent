# ATA risk and permission policy

## Default permissions

| Permission | Initial value |
|---|---|
| System mode | RESEARCH_ONLY |
| Live trading | Disabled |
| Account simulation | Disabled |
| Ticket generation | Disabled |
| Market | Binance Spot |
| Symbols | BTCUSDT, ETHUSDT |
| Maximum concurrent positions | 1 |
| Leverage / margin / futures | Prohibited |

The application defaults and checked-in config are fail-closed. Non-order decisions such as HOLD, STAY_CASH, and ABSTAIN do not create execution intents.

## Risk limits and unresolved items

- A 20% peak-to-trough drawdown threshold is retained as a proposed hard guardrail from the project plan. It is not a guarantee against larger realized losses.
- The overall research capital ceiling is CNY 30,000.
- No ATA single-trade risk budget has been approved yet.
- The legacy CNY 500 per-trade limit in the previous research track is not silently copied into ATA.
- A proposed initial live allocation of CNY 1,000–3,000 is not an authorization to trade.

## Required before any paper-account activation

1. Review and approve the paper-account risk policy.
2. Define equity accounting, fee treatment, and drawdown calculation.
3. Define data-health and exchange-disconnection behavior.
4. Pass order-state, reconciliation, restart, and fault-injection tests.
5. Confirm that the paper broker cannot reach authenticated live order endpoints.

## Required before live trading

Live trading remains prohibited until a separate approval records the strategy version, evidence package, account scope, position sizing, loss limits, API permissions, and rollback procedure.

Use read-only API keys for market/account observation where possible. Never enable withdrawals or transfers. Keep secrets outside source control.
