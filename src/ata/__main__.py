"""Minimal safety-status command."""

from ata.domain import Action
from ata.risk import RiskContext, RiskGovernor, RiskPolicy


def main() -> None:
    governor = RiskGovernor(RiskPolicy())
    result = governor.authorize(
        action=Action.BUY_BTC,
        symbol="BTCUSDT",
        context=RiskContext(data_healthy=True),
    )
    print("Adaptive Trading Agent")
    print("mode=RESEARCH_ONLY")
    print("trading_allowed=false")
    print("account_simulation_allowed=false")
    print("ticket_generation_allowed=false")
    print(f"sample_buy_authorized={str(result.allowed).lower()}")
    print(f"sample_buy_reason={result.code.value}")


if __name__ == "__main__":
    main()
