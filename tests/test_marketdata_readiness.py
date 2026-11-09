from decimal import Decimal

import pytest

from ata.marketdata.models import INTERVAL_MS, Kline
from ata.marketdata.readiness import DAY_MS, REQUIRED_INTERVALS, REQUIRED_SYMBOLS, verify_m1
from ata.marketdata.storage import MarketDataRepository


def candle(symbol: str, interval: str, open_time_ms: int) -> Kline:
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_ms=open_time_ms,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("101"),
        volume=Decimal("10"),
        close_time_ms=open_time_ms + INTERVAL_MS[interval] - 1,
        quote_asset_volume=Decimal("1000"),
        number_of_trades=10,
        taker_buy_base_asset_volume=Decimal("4"),
        taker_buy_quote_asset_volume=Decimal("400"),
    )


@pytest.fixture
def seeded_database(tmp_path):
    now_ms = 400 * DAY_MS
    path = tmp_path / "market.sqlite3"
    repository = MarketDataRepository(path)
    for symbol in REQUIRED_SYMBOLS:
        for interval in REQUIRED_INTERVALS:
            width = INTERVAL_MS[interval]
            last_closed = (now_ms // width - 1) * width
            rows = [
                candle(symbol, interval, last_closed - width * i)
                for i in (2, 1, 0)
            ]
            repository.insert_batch(rows, fetched_at_server_ms=now_ms)
    return path, now_ms


def test_six_streams_pass_readiness_on_complete_fresh_history(seeded_database) -> None:
    path, now_ms = seeded_database

    report = verify_m1(path, now_ms=now_ms, min_history_days=0)

    assert report.passed is True
    assert report.to_dict()["status"] == "PASS"
    assert len(report.series) == 6
    assert not report.database_issues
    assert all(s.rows == 3 and s.missing_bars == 0 and s.lag_bars == 0 for s in report.series)


def test_history_threshold_fails_when_backfill_is_too_short(seeded_database) -> None:
    path, now_ms = seeded_database

    report = verify_m1(path, now_ms=now_ms, min_history_days=1)

    assert not report.passed
    assert all("INSUFFICIENT_HISTORY" in s.issues for s in report.series)


def test_missing_interval_is_reported_without_fabricating_data(seeded_database) -> None:
    path, now_ms = seeded_database
    import sqlite3

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT open_time_ms FROM klines WHERE symbol='BTCUSDT' AND interval='15m' "
            "ORDER BY open_time_ms LIMIT 1 OFFSET 1"
        ).fetchone()
        connection.execute(
            "DELETE FROM klines WHERE symbol='BTCUSDT' AND interval='15m' "
            "AND open_time_ms=?",
            (row[0],),
        )

    report = verify_m1(path, now_ms=now_ms, min_history_days=0)
    target = next(s for s in report.series if s.symbol == "BTCUSDT" and s.interval == "15m")

    assert not report.passed
    assert target.missing_bars == 1
    assert "MISSING_BARS" in target.issues


def test_stale_data_is_reported(seeded_database) -> None:
    path, now_ms = seeded_database

    report = verify_m1(
        path,
        now_ms=now_ms + 12 * INTERVAL_MS["4h"],
        min_history_days=0,
        max_lag_bars=2,
    )

    assert not report.passed
    assert all("STALE_DATA" in s.issues for s in report.series)


def test_missing_database_is_not_automatically_created(tmp_path) -> None:
    path = tmp_path / "absent.sqlite3"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        verify_m1(path, now_ms=400 * DAY_MS)
    assert not path.exists()


def test_readiness_does_not_write_any_new_rows(seeded_database) -> None:
    path, now_ms = seeded_database
    import sqlite3

    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]

    verify_m1(path, now_ms=now_ms, min_history_days=0)

    with sqlite3.connect(path) as connection:
        after = connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0]
    assert before == after == 6


def test_invalid_threshold_is_rejected(seeded_database) -> None:
    path, now_ms = seeded_database
    with pytest.raises(ValueError, match="thresholds"):
        verify_m1(path, now_ms=now_ms, min_history_days=-1)
