"""M2 must be reproducible, causal, read-only, and non-executable."""

import sqlite3
from decimal import Decimal

import pytest

from ata.marketdata.models import INTERVAL_MS, Kline
from ata.marketdata.storage import MarketDataRepository
from ata.research.baselines import HOUR_MS, research_snapshot


def make_kline(symbol: str, open_time_ms: int, close: Decimal) -> Kline:
    return Kline(
        symbol=symbol,
        interval="1h",
        open_time_ms=open_time_ms,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("10"),
        close_time_ms=open_time_ms + INTERVAL_MS["1h"] - 1,
        quote_asset_volume=Decimal("1000"),
        number_of_trades=10,
        taker_buy_base_asset_volume=Decimal("4"),
        taker_buy_quote_asset_volume=Decimal("400"),
    )


@pytest.fixture
def research_database(tmp_path):
    path = tmp_path / "market.sqlite3"
    repo = MarketDataRepository(path)
    last_open = 300 * HOUR_MS
    candles_count = 8 * 24 + 1
    for symbol in ("BTCUSDT", "ETHUSDT"):
        base = Decimal("100") if symbol == "BTCUSDT" else Decimal("200")
        bars = [
            make_kline(
                symbol,
                last_open - (candles_count - 1 - index) * HOUR_MS,
                base + Decimal(index) / 10,
            )
            for index in range(candles_count)
        ]
        repo.insert_batch(bars, fetched_at_server_ms=last_open + HOUR_MS)
    return path, last_open + HOUR_MS


def test_features_and_benchmarks_only_use_closed_hourly_bars(research_database) -> None:
    path, asof = research_database
    report = research_snapshot(
        path,
        asof_time_ms=asof,
        benchmark_days=7,
        max_lag_bars=0,
    )
    output = report.to_dict()

    assert output["status"] == "DESCRIPTIVE_ONLY"
    assert output["execution_allowed"] is False
    assert output["system_mode"] == "RESEARCH_ONLY"
    assert output["last_closed_open_time_ms"] == asof - HOUR_MS
    assert output["buy_and_hold_net_return_pct"]["USDT"] == "0.000000"
    assert len(output["features"]) == 2
    for feature in output["features"]:
        assert Decimal(feature["momentum_24h_pct"]) > 0
        assert Decimal(feature["momentum_7d_pct"]) > 0
        assert Decimal(feature["volume_last24h_vs_previous144h"]) == 1


def test_higher_cost_assumptions_reduce_passive_net_return(research_database) -> None:
    path, asof = research_database
    free = research_snapshot(
        path,
        asof_time_ms=asof,
        benchmark_days=7,
        fee_bps_per_side=Decimal("0"),
        slippage_bps_per_side=Decimal("0"),
    )
    costly = research_snapshot(
        path,
        asof_time_ms=asof,
        benchmark_days=7,
        fee_bps_per_side=Decimal("20"),
        slippage_bps_per_side=Decimal("10"),
    )
    for symbol in ("BTCUSDT", "ETHUSDT"):
        assert Decimal(costly.buy_and_hold_net_return_pct[symbol]) < Decimal(
            free.buy_and_hold_net_return_pct[symbol]
        )


def test_future_candles_do_not_change_historical_snapshot(research_database) -> None:
    path, asof = research_database
    baseline = research_snapshot(path, asof_time_ms=asof, benchmark_days=7)

    repo = MarketDataRepository(path)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        repo.insert_batch(
            [make_kline(symbol, asof, Decimal("999999"))],
            fetched_at_server_ms=asof + HOUR_MS,
        )

    replay = research_snapshot(path, asof_time_ms=asof, benchmark_days=7)
    assert replay == baseline


def test_missing_hour_causes_explicit_failure(research_database) -> None:
    path, asof = research_database
    with sqlite3.connect(path) as connection:
        connection.execute(
            "DELETE FROM klines WHERE symbol='BTCUSDT' AND interval='1h' "
            "AND open_time_ms=?",
            (asof - HOUR_MS * 24,),
        )

    with pytest.raises(ValueError, match="MISSING_OR_UNORDERED_BARS"):
        research_snapshot(path, asof_time_ms=asof, benchmark_days=7)


def test_insufficient_history_fails_instead_of_shortening_period(research_database) -> None:
    path, asof = research_database
    with pytest.raises(ValueError, match="INSUFFICIENT_HISTORY"):
        research_snapshot(path, asof_time_ms=asof, benchmark_days=14)


def test_stale_data_is_rejected_in_live_mode(research_database) -> None:
    path, asof = research_database
    with pytest.raises(ValueError, match="STALE_MARKET_DATA"):
        research_snapshot(path, asof_time_ms=asof + 6 * HOUR_MS, benchmark_days=7)


def test_research_snapshot_never_writes_to_market_database(research_database) -> None:
    path, asof = research_database
    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]

    research_snapshot(path, asof_time_ms=asof, benchmark_days=7)

    with sqlite3.connect(path) as connection:
        after = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]
    assert before == after == 2


def test_missing_database_is_not_created(tmp_path) -> None:
    path = tmp_path / "not-created.sqlite3"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        research_snapshot(path, asof_time_ms=300 * HOUR_MS, benchmark_days=7)
    assert not path.exists()


@pytest.mark.parametrize(
    "fee,slippage",
    [
        (Decimal("-1"), Decimal("5")),
        (Decimal("NaN"), Decimal("1")),
        (Decimal("10000"), Decimal("1")),
    ],
)
def test_invalid_cost_assumptions_are_rejected(research_database, fee, slippage) -> None:
    path, asof = research_database
    with pytest.raises(ValueError, match="fees and slippage|combined fee"):
        research_snapshot(
            path,
            asof_time_ms=asof,
            benchmark_days=7,
            fee_bps_per_side=fee,
            slippage_bps_per_side=slippage,
        )
