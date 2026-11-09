"""Strict data contracts for prospective shadow forecasts (never order intents)."""

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

PROMPT_VERSION = "m4-shadow-v1"
FIRST_PROSPECTIVE_DAY_MS = 1794268800000  # 2026-11-10 00:00:00 UTC
DAY_MS = 86_400_000
HOUR_MS = 3_600_000


class ShadowChoice(StrEnum):
    BTCUSDT = "BTCUSDT"
    ETHUSDT = "ETHUSDT"
    USDT = "USDT"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True, slots=True)
class ShadowForecast:
    choice: ShadowChoice
    p_btc_up: Decimal
    p_eth_up: Decimal
    reason_code: str
    hypothesis: str

    @classmethod
    def from_payload(cls, payload: Any) -> "ShadowForecast":
        if not isinstance(payload, dict):
            raise ValueError("forecast must be a JSON object")
        required = {"choice", "p_btc_up", "p_eth_up", "reason_code", "hypothesis"}
        if set(payload) != required:
            raise ValueError("forecast keys do not match the required schema")
        try:
            choice = ShadowChoice(payload["choice"])
        except (ValueError, TypeError) as error:
            raise ValueError("forecast choice is not allowed") from error

        def probability(key: str) -> Decimal:
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"{key} must be a probability")
            try:
                number = Decimal(str(value))
            except InvalidOperation as error:
                raise ValueError(f"{key} must be a probability") from error
            if not number.is_finite() or not Decimal(0) <= number <= Decimal(1):
                raise ValueError(f"{key} must be within [0,1]")
            return number

        reason = payload["reason_code"]
        hypothesis = payload["hypothesis"]
        if not isinstance(reason, str) or not 1 <= len(reason) <= 40:
            raise ValueError("reason_code must be 1-40 characters")
        if not reason.replace("_", "").isalnum() or reason.upper() != reason:
            raise ValueError("reason_code must be uppercase letters/digits/underscores")
        if not isinstance(hypothesis, str) or not 1 <= len(hypothesis) <= 240:
            raise ValueError("hypothesis must be 1-240 characters")
        return cls(choice, probability("p_btc_up"), probability("p_eth_up"), reason, hypothesis)

    def to_dict(self) -> dict[str, str]:
        return {
            "choice": self.choice.value,
            "p_btc_up": format(self.p_btc_up, "f"),
            "p_eth_up": format(self.p_eth_up, "f"),
            "reason_code": self.reason_code,
            "hypothesis": self.hypothesis,
        }


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def brier(probability: Decimal, realized: bool) -> str:
    score = (float(probability) - (1.0 if realized else 0.0)) ** 2
    if not math.isfinite(score):
        raise ValueError("non-finite Brier score")
    return f"{score:.8f}"
