"""Fail-closed authorization checks. This module does not submit orders."""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from ata.domain import Action, ORDER_ACTIONS, SystemMode


class AuthorizationCode(StrEnum):
    NON_ORDER_ACTION = "NON_ORDER_ACTION"
    UNSUPPORTED_SYMBOL = "UNSUPPORTED_SYMBOL"
    ACTION_SYMBOL_MISMATCH = "ACTION_SYMBOL_MISMATCH"
    DATA_UNHEALTHY = "DATA_UNHEALTHY"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    POSITION_LIMIT = "POSITION_LIMIT"
    NO_POSITION_TO_EXIT = "NO_POSITION_TO_EXIT"
    MODE_NOT_EXECUTABLE = "MODE_NOT_EXECUTABLE"
    ACCOUNT_SIMULATION_DISABLED = "ACCOUNT_SIMULATION_DISABLED"
    TRADING_DISABLED = "TRADING_DISABLED"
    TICKET_GENERATION_DISABLED = "TICKET_GENERATION_DISABLED"
    INVALID_ACTION = "INVALID_ACTION"
    PAPER_EXECUTION_NOT_IMPLEMENTED = "PAPER_EXECUTION_NOT_IMPLEMENTED"
    LIVE_EXECUTION_NOT_IMPLEMENTED = "LIVE_EXECUTION_NOT_IMPLEMENTED"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    mode: SystemMode = SystemMode.RESEARCH_ONLY
    trading_allowed: bool = False
    account_simulation_allowed: bool = False
    ticket_generation_allowed: bool = False
    allowed_symbols: frozenset[str] = field(
        default_factory=lambda: frozenset({"BTCUSDT", "ETHUSDT"})
    )
    max_concurrent_positions: int = 1
    max_drawdown_fraction: Decimal = Decimal("0.20")

    def __post_init__(self) -> None:
        if self.max_concurrent_positions < 1:
            raise ValueError("max_concurrent_positions must be at least 1")
        if not Decimal("0") < self.max_drawdown_fraction <= Decimal("1"):
            raise ValueError("max_drawdown_fraction must be in the interval (0, 1]")
        if self.mode in {SystemMode.RESEARCH_ONLY, SystemMode.SHADOW} and any(
            (
                self.trading_allowed,
                self.account_simulation_allowed,
                self.ticket_generation_allowed,
            )
        ):
            raise ValueError("research and shadow modes cannot grant execution permissions")
        if self.mode is SystemMode.PAPER and self.trading_allowed:
            raise ValueError("paper mode cannot grant live trading permission")


@dataclass(frozen=True, slots=True)
class RiskContext:
    data_healthy: bool = False
    current_drawdown_fraction: Decimal = Decimal("0")
    open_positions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.current_drawdown_fraction <= Decimal("1"):
            raise ValueError("current_drawdown_fraction must be in the interval [0, 1]")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    code: AuthorizationCode
    reason: str


class RiskGovernor:
    """Evaluate action permissions without performing execution side effects."""

    _BUY_SYMBOLS = {
        Action.BUY_BTC: "BTCUSDT",
        Action.BUY_ETH: "ETHUSDT",
    }

    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def authorize(
        self,
        action: Action,
        symbol: str | None,
        context: RiskContext | None = None,
    ) -> RiskDecision:
        context = context or RiskContext()

        if not isinstance(action, Action):
            return self._deny(
                AuthorizationCode.INVALID_ACTION,
                "Action must be a recognized Action enum value.",
            )

        if action not in ORDER_ACTIONS:
            return RiskDecision(
                allowed=True,
                code=AuthorizationCode.NON_ORDER_ACTION,
                reason="Non-order decisions do not create execution intents.",
            )

        expected_symbol = self._BUY_SYMBOLS.get(action)
        if expected_symbol is not None and symbol != expected_symbol:
            return self._deny(
                AuthorizationCode.ACTION_SYMBOL_MISMATCH,
                f"{action.value} requires {expected_symbol}.",
            )
        if symbol is None or symbol not in self.policy.allowed_symbols:
            return self._deny(
                AuthorizationCode.UNSUPPORTED_SYMBOL,
                "The symbol is missing or outside the configured research universe.",
            )
        if not context.data_healthy:
            return self._deny(
                AuthorizationCode.DATA_UNHEALTHY,
                "Market data is not explicitly marked healthy.",
            )
        if context.current_drawdown_fraction >= self.policy.max_drawdown_fraction:
            return self._deny(
                AuthorizationCode.DRAWDOWN_LIMIT,
                "The configured drawdown guardrail has been reached.",
            )

        if action is Action.EXIT:
            if symbol not in context.open_positions:
                return self._deny(
                    AuthorizationCode.NO_POSITION_TO_EXIT,
                    "There is no recorded open position for this symbol.",
                )
        elif len(context.open_positions) >= self.policy.max_concurrent_positions:
            return self._deny(
                AuthorizationCode.POSITION_LIMIT,
                "The maximum number of concurrent positions has been reached.",
            )

        if self.policy.mode in {SystemMode.RESEARCH_ONLY, SystemMode.SHADOW}:
            return self._deny(
                AuthorizationCode.MODE_NOT_EXECUTABLE,
                "Research and shadow modes cannot authorize order execution.",
            )

        if self.policy.mode is SystemMode.PAPER:
            if not self.policy.account_simulation_allowed:
                return self._deny(
                    AuthorizationCode.ACCOUNT_SIMULATION_DISABLED,
                    "Paper account simulation has not been explicitly enabled.",
                )
            return self._deny(
                AuthorizationCode.PAPER_EXECUTION_NOT_IMPLEMENTED,
                "Paper broker is not implemented; order-like actions remain blocked.",
            )

        if not self.policy.trading_allowed:
            return self._deny(
                AuthorizationCode.TRADING_DISABLED,
                "Live trading permission is disabled.",
            )
        if not self.policy.ticket_generation_allowed:
            return self._deny(
                AuthorizationCode.TICKET_GENERATION_DISABLED,
                "Order-ticket generation permission is disabled.",
            )
        return self._deny(
            AuthorizationCode.LIVE_EXECUTION_NOT_IMPLEMENTED,
            "Live execution adapter is not implemented; live order actions remain blocked.",
        )

    @staticmethod
    def _deny(code: AuthorizationCode, reason: str) -> RiskDecision:
        return RiskDecision(allowed=False, code=code, reason=reason)
