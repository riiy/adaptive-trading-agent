"""Typed domain records shared by decision, risk, and audit components."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4


class SystemMode(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    LIVE_APPROVAL = "LIVE_APPROVAL"
    LIVE_GUARDED = "LIVE_GUARDED"
    LIVE_AUTONOMOUS = "LIVE_AUTONOMOUS"


class Action(StrEnum):
    BUY_BTC = "BUY_BTC"
    BUY_ETH = "BUY_ETH"
    HOLD = "HOLD"
    EXIT = "EXIT"
    STAY_CASH = "STAY_CASH"
    ABSTAIN = "ABSTAIN"


ORDER_ACTIONS = frozenset({Action.BUY_BTC, Action.BUY_ETH, Action.EXIT})


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Immutable, timestamped record of what the system decided and why."""

    action: Action
    reason_code: str
    rationale: str
    snapshot_id: str
    strategy_version: str
    symbol: str | None = None
    mode: SystemMode = SystemMode.RESEARCH_ONLY
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decision_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be timezone-aware UTC")
        for name in ("reason_code", "rationale", "snapshot_id", "strategy_version", "decision_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if self.symbol is not None and self.symbol != self.symbol.upper():
            raise ValueError("symbol must be uppercase")
        if self.action is Action.BUY_BTC and self.symbol != "BTCUSDT":
            raise ValueError("BUY_BTC requires symbol=BTCUSDT")
        if self.action is Action.BUY_ETH and self.symbol != "ETHUSDT":
            raise ValueError("BUY_ETH requires symbol=ETHUSDT")
        if self.action is Action.EXIT and self.symbol is None:
            raise ValueError("EXIT requires an explicit symbol")

    def to_dict(self) -> dict[str, str | None]:
        """Return a stable JSON-compatible representation."""
        return {
            "decision_id": self.decision_id,
            "created_at": self.created_at.isoformat(),
            "mode": self.mode.value,
            "action": self.action.value,
            "symbol": self.symbol,
            "reason_code": self.reason_code,
            "rationale": self.rationale,
            "snapshot_id": self.snapshot_id,
            "strategy_version": self.strategy_version,
        }
