from dataclasses import replace
from decimal import Decimal

import pytest

from ata.marketdata.models import DataConflictError, Kline
from ata.marketdata.storage import MarketDataRepository


def candle(open_time_ms: int, close: str = "101") -> Kline:
    return Kline(
        symbol="BTCUSDT",
        interval="1m",
        open_time_ms=open_time_ms,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("10"),
        close_time_ms=open_time_ms + 59_999,
        quote_asset_volume=Decimal("1000"),
        number_of_trades=5,
        taker_buy_base_asset_volume=Decimal("4"),
        taker_buy_quote_asset_volume=Decimal("400"),
    )


def test_insert_batch_is_idempotent_and_records_provenance(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    batch = [candle(0), candle(60_000)]

    first = repository.insert_batch(batch, fetched_at_server_ms=120_000)
    second = repository.insert_batch(batch, fetched_at_server_ms=180_000)

    assert first.rows_received == 2
    assert first.rows_inserted == 2
    assert first.run_id is not None
    assert second.rows_received == 2
    assert second.rows_inserted == 0
    assert second.run_id is None
    assert repository.audit("BTCUSDT", "1m").rows == 2


def test_conflicting_existing_candle_rolls_back_batch(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    repository.insert_batch(
        [candle(0), candle(120_000)],
        fetched_at_server_ms=180_000,
    )

    with pytest.raises(DataConflictError, match="stored candle changed"):
        repository.insert_batch(
            [candle(60_000), candle(120_000, close="100.5")],
            fetched_at_server_ms=180_000,
        )

    report = repository.audit("BTCUSDT", "1m")
    assert report.rows == 2
    assert report.last_open_time_ms == 120_000
    assert report.missing_intervals == 1


def test_audit_reports_missing_intervals_without_fabricating_rows(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    repository.insert_batch(
        [candle(0), candle(60_000), candle(240_000)],
        fetched_at_server_ms=300_000,
    )

    report = repository.audit("BTCUSDT", "1m")
    assert report.rows == 3
    assert report.missing_intervals == 2
    assert report.gap_examples == ((60_000, 240_000),)


def test_latest_open_time_returns_none_for_empty_series(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    assert repository.latest_open_time("BTCUSDT", "1m") is None


def test_candle_data_conflict_is_not_hidden_by_decimal_formatting(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    repository.insert_batch([candle(0)], fetched_at_server_ms=60_000)

    changed = replace(candle(0), close=Decimal("100.9"))
    with pytest.raises(DataConflictError):
        repository.insert_batch([changed], fetched_at_server_ms=120_000)

def test_insert_batch_rejects_unclosed_candles(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market.sqlite3")

    with pytest.raises(ValueError, match="only candles closed"):
        repository.insert_batch([candle(0)], fetched_at_server_ms=59_999)


def test_insert_batch_rejects_unordered_rows(tmp_path) -> None:
    repository = MarketDataRepository(tmp_path / "market.sqlite3")

    with pytest.raises(ValueError, match="strictly chronological"):
        repository.insert_batch(
            [candle(60_000), candle(0)],
            fetched_at_server_ms=180_000,
        )
