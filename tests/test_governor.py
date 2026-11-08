from decimal import Decimal

import pytest

from ata.domain import Action, SystemMode
from ata.risk import AuthorizationCode, RiskContext, RiskGovernor, RiskPolicy


def healthy_context(
    *,
    drawdown: Decimal = Decimal("0"),
    positions: tuple[str, ...] = (),
) -> RiskContext:
    return RiskContext(
        data_healthy=True,
        current_drawdown_fraction=drawdown,
        open_positions=positions,
    )


def test_default_research_policy_rejects_buy_even_with_healthy_data() -> None:
    result = RiskGovernor().authorize(
        Action.BUY_BTC,
        "BTCUSDT",
        healthy_context(),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.MODE_NOT_EXECUTABLE


def test_non_order_action_is_allowed_without_execution_permission() -> None:
    result = RiskGovernor().authorize(Action.STAY_CASH, None, RiskContext())

    assert result.allowed is True
    assert result.code is AuthorizationCode.NON_ORDER_ACTION


def test_unhealthy_data_fails_closed() -> None:
    policy = RiskPolicy(
        mode=SystemMode.PAPER,
        account_simulation_allowed=True,
    )
    result = RiskGovernor(policy).authorize(
        Action.BUY_BTC,
        "BTCUSDT",
        RiskContext(data_healthy=False),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.DATA_UNHEALTHY


def test_drawdown_guardrail_blocks_new_order() -> None:
    policy = RiskPolicy(
        mode=SystemMode.PAPER,
        account_simulation_allowed=True,
    )
    result = RiskGovernor(policy).authorize(
        Action.BUY_ETH,
        "ETHUSDT",
        healthy_context(drawdown=Decimal("0.20")),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.DRAWDOWN_LIMIT


def test_paper_authorization_requires_explicit_permission() -> None:
    policy = RiskPolicy(mode=SystemMode.PAPER)
    result = RiskGovernor(policy).authorize(
        Action.BUY_BTC,
        "BTCUSDT",
        healthy_context(),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.ACCOUNT_SIMULATION_DISABLED


def test_paper_mode_stays_blocked_until_broker_is_implemented() -> None:
    policy = RiskPolicy(
        mode=SystemMode.PAPER,
        account_simulation_allowed=True,
    )
    result = RiskGovernor(policy).authorize(
        Action.BUY_BTC,
        "BTCUSDT",
        healthy_context(),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.PAPER_EXECUTION_NOT_IMPLEMENTED


def test_live_mode_stays_blocked_until_adapter_is_implemented() -> None:
    policy = RiskPolicy(
        mode=SystemMode.LIVE_GUARDED,
        trading_allowed=True,
        ticket_generation_allowed=True,
    )
    result = RiskGovernor(policy).authorize(
        Action.BUY_BTC,
        "BTCUSDT",
        healthy_context(),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.LIVE_EXECUTION_NOT_IMPLEMENTED


def test_unknown_action_fails_closed() -> None:
    result = RiskGovernor().authorize(
        "BUY_BTC",  # type: ignore[arg-type]
        "BTCUSDT",
        healthy_context(),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.INVALID_ACTION


def test_position_limit_blocks_second_concurrent_position() -> None:
    policy = RiskPolicy(
        mode=SystemMode.PAPER,
        account_simulation_allowed=True,
        max_concurrent_positions=1,
    )
    result = RiskGovernor(policy).authorize(
        Action.BUY_ETH,
        "ETHUSDT",
        healthy_context(positions=("BTCUSDT",)),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.POSITION_LIMIT


def test_exit_requires_an_existing_position() -> None:
    policy = RiskPolicy(
        mode=SystemMode.PAPER,
        account_simulation_allowed=True,
    )
    result = RiskGovernor(policy).authorize(
        Action.EXIT,
        "BTCUSDT",
        healthy_context(),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.NO_POSITION_TO_EXIT


def test_research_mode_cannot_be_configured_with_execution_permissions() -> None:
    with pytest.raises(ValueError, match="research and shadow"):
        RiskPolicy(trading_allowed=True)


def test_unsupported_symbol_is_rejected() -> None:
    policy = RiskPolicy(
        mode=SystemMode.PAPER,
        account_simulation_allowed=True,
    )
    result = RiskGovernor(policy).authorize(
        Action.BUY_BTC,
        "BTCUSDT-PERP",
        healthy_context(),
    )

    assert result.allowed is False
    assert result.code is AuthorizationCode.ACTION_SYMBOL_MISMATCH
