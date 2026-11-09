"""M3-H001: frozen, non-executable, daily 7-day momentum diagnostic.

This is signal research, NOT an account, fill, or strategy backtest.
The historical cutoff, rule, chronological partitions and bootstrap seed are fixed.
"""

import math
import random
import sqlite3
import statistics
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from ata.marketdata.models import INTERVAL_MS

HOUR_MS = INTERVAL_MS["1h"]
DAY_MS = 24 * HOUR_MS
LOOKBACK_DAYS = 7
HISTORY_DAYS = 365
FROZEN_ASOF_MS = 1794206779012
MIN_HISTORY_DAYS = 350
MIN_VALIDATION_SAMPLES = 40
BOOTSTRAP_SEED = 20261109
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_BLOCK_DAYS = 7
SYMBOLS = ("BTCUSDT", "ETHUSDT")


@dataclass(frozen=True, slots=True)
class DailyDiagnostic:
    decision_time_ms: int
    selected: str
    candidate_return: float
    btc_return: float
    eth_return: float


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("NON_FINITE_RESEARCH_METRIC")
    return f"{value * 100:.6f}"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def _block_ci(values: list[float]) -> tuple[float, float]:
    """Fixed-seed, circular seven-day moving-block bootstrap of daily mean."""
    rng = random.Random(BOOTSTRAP_SEED)
    length = len(values)
    means: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample: list[float] = []
        while len(sample) < length:
            first = rng.randrange(length)
            sample.extend(
                values[(first + offset) % length] for offset in range(BOOTSTRAP_BLOCK_DAYS)
            )
        means.append(_mean(sample[:length]))
    return _quantile(means, 0.025), _quantile(means, 0.975)


def _load_closed_hourly(
    connection: sqlite3.Connection,
    *,
    symbol: str,
) -> dict[int, Decimal]:
    start_ms = FROZEN_ASOF_MS - HISTORY_DAYS * DAY_MS
    records = connection.execute(
        """
        SELECT open_time_ms, close
        FROM klines
        WHERE venue='binance_spot' AND symbol=? AND interval='1h'
          AND open_time_ms>=? AND close_time_ms<?
        ORDER BY open_time_ms
        """,
        (symbol, start_ms, FROZEN_ASOF_MS),
    ).fetchall()

    if len(records) < MIN_HISTORY_DAYS * 24:
        raise ValueError(f"INSUFFICIENT_FROZEN_HISTORY:{symbol}")

    result: dict[int, Decimal] = {}
    previous: int | None = None
    for stamp, raw_close in records:
        stamp = int(stamp)
        if previous is not None and stamp - previous != HOUR_MS:
            raise ValueError(f"NONCONTIGUOUS_HISTORY:{symbol}")
        value = Decimal(raw_close)
        if not value.is_finite() or value <= 0:
            raise ValueError(f"INVALID_CLOSE:{symbol}")
        result[stamp] = value
        previous = stamp
    return result


def _daily_observations(btc: dict[int, Decimal], eth: dict[int, Decimal]) -> list[DailyDiagnostic]:
    if btc.keys() != eth.keys():
        raise ValueError("UNALIGNED_BTC_ETH_TIMESTAMPS")
    timestamps = list(btc)
    first = timestamps[0]
    last = timestamps[-1]
    earliest_decision = first + LOOKBACK_DAYS * DAY_MS + HOUR_MS
    decision = ((earliest_decision + DAY_MS - 1) // DAY_MS) * DAY_MS
    latest_decision = last - (DAY_MS - HOUR_MS)

    observations: list[DailyDiagnostic] = []
    while decision <= latest_decision:
        reference = decision - HOUR_MS
        past = reference - LOOKBACK_DAYS * DAY_MS
        outcome = decision + DAY_MS - HOUR_MS

        btc_strength = float(btc[reference] / btc[past] - 1)
        eth_strength = float(eth[reference] / eth[past] - 1)
        btc_outcome = float(btc[outcome] / btc[reference] - 1)
        eth_outcome = float(eth[outcome] / eth[reference] - 1)

        if btc_strength <= 0 and eth_strength <= 0:
            selected = "USDT"
            candidate = 0.0
        elif btc_strength >= eth_strength:
            selected = "BTCUSDT"
            candidate = btc_outcome
        else:
            selected = "ETHUSDT"
            candidate = eth_outcome

        observations.append(
            DailyDiagnostic(
                decision_time_ms=decision,
                selected=selected,
                candidate_return=candidate,
                btc_return=btc_outcome,
                eth_return=eth_outcome,
            )
        )
        decision += DAY_MS
    return observations


def _describe(records: list[DailyDiagnostic]) -> dict[str, object]:
    if len(records) < MIN_VALIDATION_SAMPLES:
        raise ValueError("INSUFFICIENT_SEGMENT_SAMPLES")
    candidate = [r.candidate_return for r in records]
    btc = [r.btc_return for r in records]
    eth = [r.eth_return for r in records]
    excess = {
        "USDT": candidate,
        "BTCUSDT": [a - b for a, b in zip(candidate, btc, strict=True)],
        "ETHUSDT": [a - b for a, b in zip(candidate, eth, strict=True)],
    }
    counts = {
        asset: sum(r.selected == asset for r in records) for asset in ("USDT", "BTCUSDT", "ETHUSDT")
    }
    return {
        "days": len(records),
        "first_decision_time_ms": records[0].decision_time_ms,
        "last_decision_time_ms": records[-1].decision_time_ms,
        "selection_counts": counts,
        "candidate_mean_forward_24h_pct": _number(_mean(candidate)),
        "candidate_median_forward_24h_pct": _number(statistics.median(candidate)),
        "candidate_p05_forward_24h_pct": _number(_quantile(candidate, 0.05)),
        "candidate_p95_forward_24h_pct": _number(_quantile(candidate, 0.95)),
        "candidate_positive_day_fraction": f"{sum(v > 0 for v in candidate) / len(candidate):.6f}",
        "benchmarks_mean_forward_24h_pct": {
            "USDT": "0.000000",
            "BTCUSDT": _number(_mean(btc)),
            "ETHUSDT": _number(_mean(eth)),
        },
        "mean_excess_forward_24h_pct": {
            name: _number(_mean(values)) for name, values in excess.items()
        },
        "bootstrap_95pct_mean_excess_ci_pct": {
            name: [_number(lower), _number(upper)]
            for name, values in excess.items()
            for lower, upper in [_block_ci(values)]
        },
        "bootstrap_block_days": BOOTSTRAP_BLOCK_DAYS,
        "approximate_nonoverlapping_week_blocks": len(records) // BOOTSTRAP_BLOCK_DAYS,
    }


def _passes_predeclared_gate(
    development: dict[str, object],
    validation: dict[str, object],
) -> bool:
    for report in (development, validation):
        excess = report["mean_excess_forward_24h_pct"]
        if not isinstance(excess, dict):
            return False
        if any(float(excess[name]) <= 0 for name in ("USDT", "BTCUSDT", "ETHUSDT")):
            return False
    ci = validation["bootstrap_95pct_mean_excess_ci_pct"]
    if not isinstance(ci, dict):
        return False
    return all(float(ci[name][0]) > 0 for name in ("USDT", "BTCUSDT", "ETHUSDT"))


def diagnose_h001(database_path: str | Path) -> dict[str, object]:
    """Return only development/validation outcomes; reserve the historical test set."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"market database does not exist: {path}")

    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        btc = _load_closed_hourly(connection, symbol=SYMBOLS[0])
        eth = _load_closed_hourly(connection, symbol=SYMBOLS[1])
    finally:
        connection.close()

    observations = _daily_observations(btc, eth)
    length = len(observations)
    # Frozen chronological 60%/20%/20%. No random time shuffle.
    development_end = length * 60 // 100
    validation_end = length * 80 // 100
    development = _describe(observations[:development_end])
    validation = _describe(observations[development_end:validation_end])
    decision = (
        "REVIEW_BEFORE_HISTORICAL_TEST"
        if _passes_predeclared_gate(development, validation)
        else "STOP_NO_SUFFICIENT_EVIDENCE"
    )
    return {
        "experiment_id": "M3-H001",
        "status": "HISTORICAL_SIGNAL_DIAGNOSTIC_ONLY",
        "rule": "At each 00:00 UTC, choose strongest positive 7d BTC/ETH momentum, else USDT.",
        "frozen_asof_time_ms": FROZEN_ASOF_MS,
        "observation_days": length,
        "development": development,
        "validation": validation,
        "reserved_historical_test": {
            "status": "SEALED",
            "days": length - validation_end,
            "caveat": (
                "Historical holdout may have indirect exposure via M2 aggregate results. "
                "True prospective evidence must be collected after 2026-11-10 UTC."
            ),
        },
        "predeclared_decision": decision,
        "limitations": [
            "No orders, position sizing, turnover costs, or account equity are modeled.",
            "Forward close-to-close returns are labels, not executable returns.",
            "Bootstrap intervals describe sampling uncertainty, not strategy robustness.",
            "Historical selection is exposed to market-regime instability and selection bias.",
            "A positive result is not authorization for simulation or real trading.",
        ],
        "execution_allowed": False,
        "account_simulation_allowed": False,
        "ticket_generation_allowed": False,
    }
