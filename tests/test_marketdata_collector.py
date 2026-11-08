from ata.marketdata.collector import MarketDataCollector
from ata.marketdata.models import INTERVAL_MS
from ata.marketdata.storage import MarketDataRepository


def raw_kline(open_time_ms: int) -> list[object]:
    return [
        open_time_ms,
        "100",
        "102",
        "99",
        "101",
        "10",
        open_time_ms + INTERVAL_MS["1m"] - 1,
        "1000",
        5,
        "4",
        "400",
        "0",
    ]


class FakeClient:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows
        self.calls = []

    def get_klines(self, **kwargs):
        self.calls.append(kwargs)
        return [
            row
            for row in self.rows
            if kwargs["start_time_ms"] <= int(row[0]) <= kwargs["end_time_ms"]
        ][: kwargs["limit"]]


def test_sync_paginates_and_persists_only_closed_candles(tmp_path) -> None:
    rows = [raw_kline(0), raw_kline(60_000), raw_kline(120_000)]
    client = FakeClient(rows)
    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    collector = MarketDataCollector(client, repository, page_size=2)

    summary = collector.sync(
        symbol="BTCUSDT",
        interval="1m",
        server_time_ms=180_000,
        start_time_ms=0,
    )

    assert summary.pages == 2
    assert summary.rows_received == 3
    assert summary.rows_inserted == 3
    assert len(client.calls) == 2
    assert client.calls[1]["start_time_ms"] == 60_001
    assert repository.audit("BTCUSDT", "1m").rows == 3


def test_incremental_sync_overlaps_recent_bars_and_is_idempotent(tmp_path) -> None:
    rows = [raw_kline(0), raw_kline(60_000), raw_kline(120_000)]
    client = FakeClient(rows)
    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    collector = MarketDataCollector(client, repository)

    collector.sync(
        symbol="BTCUSDT",
        interval="1m",
        server_time_ms=180_000,
        start_time_ms=0,
    )
    second = collector.sync(
        symbol="BTCUSDT",
        interval="1m",
        server_time_ms=180_000,
        overlap_bars=2,
    )

    assert second.rows_received == 3
    assert second.rows_inserted == 0
    assert second.start_time_ms == 0
    assert repository.latest_open_time("BTCUSDT", "1m") == 120_000

def test_sync_rejects_rows_outside_requested_range(tmp_path) -> None:
    class OutOfRangeClient:
        def get_klines(self, **_kwargs):
            return [raw_kline(0)]

    repository = MarketDataRepository(tmp_path / "market.sqlite3")
    collector = MarketDataCollector(OutOfRangeClient(), repository)

    try:
        collector.sync(
            symbol="BTCUSDT",
            interval="1m",
            server_time_ms=120_000,
            start_time_ms=60_000,
        )
    except ValueError as error:
        assert "outside the requested time range" in str(error)
    else:
        raise AssertionError("out-of-range candle must be rejected")
