"""Paginated historical market-data synchronization."""

from dataclasses import dataclass

from ata.marketdata.binance import BinancePublicClient
from ata.marketdata.models import INTERVAL_MS, Kline, MarketDataError, parse_klines
from ata.marketdata.storage import MarketDataRepository


@dataclass(frozen=True, slots=True)
class SyncSummary:
    symbol: str
    interval: str
    start_time_ms: int
    end_time_ms: int
    server_time_ms: int
    pages: int
    rows_received: int
    rows_inserted: int
    payload_hashes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "server_time_ms": self.server_time_ms,
            "pages": self.pages,
            "rows_received": self.rows_received,
            "rows_inserted": self.rows_inserted,
            "rows_unchanged": self.rows_received - self.rows_inserted,
            "payload_hashes": list(self.payload_hashes),
        }


class MarketDataCollector:
    """Fetch, validate, and persist completed Binance Spot candles."""

    def __init__(
        self,
        client: BinancePublicClient,
        repository: MarketDataRepository,
        *,
        page_size: int = 1000,
        max_pages: int = 10_000,
    ) -> None:
        if not 1 <= page_size <= 1000 or max_pages < 1:
            raise ValueError("collector pagination settings are invalid")
        self.client = client
        self.repository = repository
        self.page_size = page_size
        self.max_pages = max_pages

    def sync(
        self,
        *,
        symbol: str,
        interval: str,
        server_time_ms: int,
        lookback_days: int = 3,
        overlap_bars: int = 3,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> SyncSummary:
        if lookback_days < 1 or overlap_bars < 0:
            raise ValueError("lookback_days/overlap_bars are invalid")
        interval_ms = INTERVAL_MS[interval]
        final_end = min(end_time_ms or server_time_ms - 1, server_time_ms - 1)
        latest = self.repository.latest_open_time(symbol, interval)

        if start_time_ms is not None:
            cursor = start_time_ms
        elif latest is not None:
            cursor = max(0, latest - overlap_bars * interval_ms)
        else:
            cursor = max(0, server_time_ms - lookback_days * 86_400_000)

        requested_start = cursor
        if cursor > final_end:
            return SyncSummary(
                symbol, interval, requested_start, final_end, server_time_ms, 0, 0, 0, ()
            )

        pages = 0
        rows_received = 0
        rows_inserted = 0
        hashes: list[str] = []

        while cursor <= final_end:
            if pages >= self.max_pages:
                raise MarketDataError("maximum page count reached; split the requested history")
            payload = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                start_time_ms=cursor,
                end_time_ms=final_end,
                limit=self.page_size,
            )
            pages += 1
            if not payload:
                break

            parsed: list[Kline] = parse_klines(
                payload,
                symbol=symbol,
                interval=interval,
                server_time_ms=server_time_ms,
            )
            if parsed:
                result = self.repository.insert_batch(
                    parsed,
                    fetched_at_server_ms=server_time_ms,
                )
                rows_received += result.rows_received
                rows_inserted += result.rows_inserted
                hashes.append(result.payload_sha256)

            try:
                last_raw_open_time = int(payload[-1][0])
            except (TypeError, ValueError, IndexError) as error:
                raise MarketDataError("last Binance kline row has no valid open time") from error
            next_cursor = last_raw_open_time + 1
            if next_cursor <= cursor:
                raise MarketDataError("Binance pagination did not advance")
            if len(payload) < self.page_size or next_cursor > final_end:
                break
            cursor = next_cursor

        return SyncSummary(
            symbol=symbol,
            interval=interval,
            start_time_ms=requested_start,
            end_time_ms=final_end,
            server_time_ms=server_time_ms,
            pages=pages,
            rows_received=rows_received,
            rows_inserted=rows_inserted,
            payload_hashes=tuple(hashes),
        )
