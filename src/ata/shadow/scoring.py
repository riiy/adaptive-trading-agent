"""Prospective shadow forecast report; no simulated account or execution P&L."""

import statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from ata.shadow.store import ShadowStore

MIN_INTERPRETABLE_DAYS = 30
MIN_COMPARISON_DAYS = 60


def _percent(mean: Decimal) -> str:
    return f"{mean * 100:.6f}"


def _average(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / len(values)


def shadow_score(shadow_db: str | Path) -> dict[str, object]:
    """Report prospective Brier and descriptive outcome metrics per frozen source."""
    store = ShadowStore(shadow_db)
    rows = store.settled()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[row["source"]].append(row)

    reports: dict[str, dict[str, object]] = {}
    for source in ("baseline", "llm"):
        data = groups[source]
        if not data:
            reports[source] = {"settled_days": 0, "status": "NO_PROSPECTIVE_FEEDBACK"}
            continue
        issued = len(data)
        abstained = sum(row["forecast"]["choice"] == "ABSTAIN" for row in data)
        active = [row for row in data if row["selected_return"] is not None]
        reports[source] = {
            "settled_days": issued,
            "first_day_ms": data[0]["day_ms"],
            "last_day_ms": data[-1]["day_ms"],
            "abstained_days": abstained,
            "status": (
                "EXPLORATORY_ONLY"
                if issued < MIN_INTERPRETABLE_DAYS
                else (
                    "MORE_PROSPECTIVE_EVIDENCE_REQUIRED"
                    if issued < MIN_COMPARISON_DAYS
                    else "READY_FOR_SEPARATE_STATISTICAL_REVIEW"
                )
            ),
            "mean_brier_btc": f"{_average([Decimal(r['brier_btc']) for r in data]):.8f}",
            "mean_brier_eth": f"{_average([Decimal(r['brier_eth']) for r in data]):.8f}",
            "reference_brier_p50": "0.25000000",
            "choice_days_excluding_abstentions": len(active),
            "mean_choice_gross_forward_24h_pct": (
                _percent(_average([Decimal(r["selected_return"]) for r in active]))
                if active
                else None
            ),
            "median_choice_gross_forward_24h_pct": (
                _percent(
                    Decimal(str(statistics.median([Decimal(r["selected_return"]) for r in active])))
                )
                if active
                else None
            ),
            "mean_choice_excess_vs_cash_pct": (
                _percent(_average([Decimal(r["selected_return"]) for r in active]))
                if active
                else None
            ),
            "mean_choice_excess_vs_btc_pct": (
                _percent(
                    _average(
                        [Decimal(r["selected_return"]) - Decimal(r["btc_return"]) for r in active]
                    )
                )
                if active
                else None
            ),
            "mean_choice_excess_vs_eth_pct": (
                _percent(
                    _average(
                        [Decimal(r["selected_return"]) - Decimal(r["eth_return"]) for r in active]
                    )
                )
                if active
                else None
            ),
        }

    return {
        "status": "NON_EXECUTABLE_PROSPECTIVE_FEEDBACK",
        "sources": reports,
        "baseline_definition": "Always USDT and 50% probability of BTC/ETH positive 24h returns",
        "warnings": [
            "Gross close-to-close outcome labels, NOT executable trades or account P&L.",
            "Abstentions are excluded from selected-return statistics, not counted as 0 return.",
            "This report is descriptive; 60 observations are not a strategy pass condition.",
            "Model revisions must be versioned; do not optimize against prospective holdout.",
            "Brier p=0.5 fixed benchmark is 0.25, not a calibrated historical base-rate.",
        ],
        "trading_allowed": False,
        "account_simulation_allowed": False,
        "ticket_generation_allowed": False,
    }
