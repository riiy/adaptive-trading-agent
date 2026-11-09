"""Frozen M3-H001 diagnostic tests. No trading simulation or order execution."""

import math
import sqlite3

import pytest

from ata.research.momentum_diagnostic import (
    DAY_MS,
    FROZEN_ASOF_MS,
    HOUR_MS,
    MIN_VALIDATION_SAMPLES,
    DailyDiagnostic,
    _block_ci,
    _daily_observations,
    _describe,
    _passes_predeclared_gate,
    diagnose_h001,
)


@pytest.fixture(scope="module")
def synthetic_m3_database(tmp_path_factory):
    path = tmp_path_factory.mktemp("m3") / "historical.sqlite3"
    last_open = (FROZEN_ASOF_MS // HOUR_MS - 1) * HOUR_MS
    first_open = last_open - 355 * DAY_MS
    assert first_open % HOUR_MS == 0

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE klines (
                venue TEXT,
                symbol TEXT,
                interval TEXT,
                open_time_ms INTEGER,
                close TEXT,
                close_time_ms INTEGER
            )
            """
        )
        for symbol in ("BTCUSDT", "ETHUSDT"):
            start_price = 100.0 if symbol == "BTCUSDT" else 200.0
            rows = []
            for hour in range(355 * 24 + 1):
                timestamp = first_open + hour * HOUR_MS
                close = start_price * (1.0 + hour * 0.00002 + 0.03 * math.sin(hour / 240.0))
                rows.append(
                    (
                        "binance_spot",
                        symbol,
                        "1h",
                        timestamp,
                        f"{close:.12f}",
                        timestamp + HOUR_MS - 1,
                    )
                )
            conn.executemany(
                "INSERT INTO klines VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
    return path


def test_m3_diagnostic_is_frozen_and_hides_historical_test(synthetic_m3_database) -> None:
    result = diagnose_h001(synthetic_m3_database)

    assert result["experiment_id"] == "M3-H001"
    assert result["frozen_asof_time_ms"] == FROZEN_ASOF_MS
    assert result["execution_allowed"] is False
    assert result["account_simulation_allowed"] is False
    assert result["ticket_generation_allowed"] is False
    assert result["reserved_historical_test"]["status"] == "SEALED"
    assert result["reserved_historical_test"]["days"] > 40
    assert result["development"]["days"] > MIN_VALIDATION_SAMPLES
    assert result["validation"]["days"] > MIN_VALIDATION_SAMPLES
    assert (
        result["development"]["days"]
        + result["validation"]["days"]
        + result["reserved_historical_test"]["days"]
        == result["observation_days"]
    )
    assert "return" not in result["reserved_historical_test"]


def test_m3_database_is_read_only_and_future_extension_ignored(synthetic_m3_database) -> None:
    with sqlite3.connect(synthetic_m3_database) as connection:
        before = connection.execute("SELECT COUNT(*) FROM klines").fetchone()[0]

    initial = diagnose_h001(synthetic_m3_database)
    with sqlite3.connect(synthetic_m3_database) as connection:
        after = connection.execute("SELECT COUNT(*) FROM klines").fetchone()[0]
        for symbol in ("BTCUSDT", "ETHUSDT"):
            connection.execute(
                "INSERT INTO klines VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "binance_spot",
                    symbol,
                    "1h",
                    (FROZEN_ASOF_MS // HOUR_MS) * HOUR_MS,
                    "99999999",
                    (FROZEN_ASOF_MS // HOUR_MS + 1) * HOUR_MS - 1,
                ),
            )

    assert before == after
    assert diagnose_h001(synthetic_m3_database) == initial


def test_signals_only_depend_on_history_at_decision_time() -> None:
    from decimal import Decimal

    bars = {}
    decision = 30 * DAY_MS
    for hour in range(0, 32 * 24):
        bars[hour * HOUR_MS] = Decimal("100")
    other = dict(bars)

    reference = decision - HOUR_MS
    prior = reference - 7 * DAY_MS
    bars[prior] = Decimal("90")
    other[prior] = Decimal("110")

    first = next(
        row for row in _daily_observations(bars, other) if row.decision_time_ms == decision
    )
    assert first.selected == "BTCUSDT"

    # A change in the next-day outcome must not alter the earlier selection.
    bars[decision + 23 * HOUR_MS] = Decimal("999")
    second = next(
        row for row in _daily_observations(bars, other) if row.decision_time_ms == decision
    )
    assert second.selected == first.selected
    assert second.candidate_return != first.candidate_return


def test_cash_selected_when_both_momentum_scores_non_positive() -> None:
    from decimal import Decimal

    bars = {hour * HOUR_MS: Decimal("100") for hour in range(35 * 24)}
    obs = _daily_observations(bars, dict(bars))
    assert len(obs) > 0
    assert all(row.selected == "USDT" for row in obs)
    assert all(row.candidate_return == 0 for row in obs)


def test_bootstrap_is_reproducible_and_has_ordered_bounds() -> None:
    values = [math.sin(index) / 100 for index in range(75)]
    first = _block_ci(values)
    assert first == _block_ci(values)
    assert first[0] <= first[1]


def test_description_includes_baseline_and_uncertainty() -> None:
    observations = [
        DailyDiagnostic(
            decision_time_ms=index * DAY_MS,
            selected="BTCUSDT",
            candidate_return=0.01 if index % 2 else -0.005,
            btc_return=0.01 if index % 2 else -0.005,
            eth_return=0.0,
        )
        for index in range(70)
    ]
    result = _describe(observations)
    assert result["days"] == 70
    assert result["selection_counts"]["BTCUSDT"] == 70
    assert result["mean_excess_forward_24h_pct"]["BTCUSDT"] == "0.000000"
    assert len(result["bootstrap_95pct_mean_excess_ci_pct"]["USDT"]) == 2


def test_predeclared_gate_requires_positive_excess_vs_every_baseline() -> None:
    favorable = {
        "mean_excess_forward_24h_pct": {
            "USDT": "0.1",
            "BTCUSDT": "0.1",
            "ETHUSDT": "0.1",
        },
        "bootstrap_95pct_mean_excess_ci_pct": {
            asset: ["0.01", "0.20"] for asset in ("USDT", "BTCUSDT", "ETHUSDT")
        },
    }
    assert _passes_predeclared_gate(favorable, favorable)

    insufficient = {
        **favorable,
        "bootstrap_95pct_mean_excess_ci_pct": {
            **favorable["bootstrap_95pct_mean_excess_ci_pct"],
            "BTCUSDT": ["-0.01", "0.20"],
        },
    }
    assert not _passes_predeclared_gate(favorable, insufficient)


def test_missing_database_fails_without_creation(tmp_path) -> None:
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        diagnose_h001(path)
    assert not path.exists()


def test_stale_frozen_history_is_rejected(synthetic_m3_database, tmp_path) -> None:
    import shutil

    path = tmp_path / "stale.sqlite3"
    shutil.copy2(synthetic_m3_database, path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM klines WHERE open_time_ms > ?",
            (FROZEN_ASOF_MS - 10 * HOUR_MS,),
        )

    with pytest.raises(ValueError, match="STALE_FROZEN_HISTORY"):
        diagnose_h001(path)
