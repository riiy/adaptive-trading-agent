"""SQLite storage with immutable candle keys and ingestion provenance."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ata.marketdata.models import INTERVAL_MS, DataConflictError, Kline, decimal_text


@dataclass(frozen=True, slots=True)
class BatchInsertResult:
    run_id: str | None
    rows_received: int
    rows_inserted: int
    payload_sha256: str


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    symbol: str
    interval: str
    rows: int
    first_open_time_ms: int | None
    last_open_time_ms: int | None
    missing_intervals: int
    gap_examples: tuple[tuple[int, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "rows": self.rows,
            "first_open_time_ms": self.first_open_time_ms,
            "last_open_time_ms": self.last_open_time_ms,
            "missing_intervals": self.missing_intervals,
            "gap_examples": [
                {"previous_open_time_ms": left, "next_open_time_ms": right}
                for left, right in self.gap_examples
            ],
        }


class MarketDataRepository:
    """Persist closed candles as exact decimal strings in SQLite."""

    _CANDLE_COLUMNS = (
        "open_time_ms, open, high, low, close, volume, close_time_ms, "
        "quote_asset_volume, number_of_trades, taker_buy_base_asset_volume, "
        "taker_buy_quote_asset_volume"
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    source TEXT NOT NULL,
                    fetched_at_server_ms INTEGER NOT NULL,
                    first_open_time_ms INTEGER NOT NULL,
                    last_open_time_ms INTEGER NOT NULL,
                    rows_received INTEGER NOT NULL,
                    rows_inserted INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS klines (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER NOT NULL,
                    open TEXT NOT NULL,
                    high TEXT NOT NULL,
                    low TEXT NOT NULL,
                    close TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    close_time_ms INTEGER NOT NULL,
                    quote_asset_volume TEXT NOT NULL,
                    number_of_trades INTEGER NOT NULL,
                    taker_buy_base_asset_volume TEXT NOT NULL,
                    taker_buy_quote_asset_volume TEXT NOT NULL,
                    source_run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
                    PRIMARY KEY (venue, symbol, interval, open_time_ms)
                );

                CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_time
                    ON klines(symbol, interval, open_time_ms);
                """
            )
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f"unsupported ATA market database schema version: {version}")
            connection.execute("PRAGMA user_version=1")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def latest_open_time(self, symbol: str, interval: str) -> int | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT MAX(open_time_ms)
                FROM klines
                WHERE venue='binance_spot' AND symbol=? AND interval=?
                """,
                (symbol, interval),
            ).fetchone()
        return row[0] if row and row[0] is not None else None

    def insert_batch(
        self,
        klines: list[Kline],
        *,
        fetched_at_server_ms: int,
    ) -> BatchInsertResult:
        if not klines:
            return BatchInsertResult(None, 0, 0, hashlib.sha256(b"[]").hexdigest())

        symbol = klines[0].symbol
        interval = klines[0].interval
        if any(item.symbol != symbol or item.interval != interval for item in klines):
            raise ValueError("one ingestion batch must contain a single symbol and interval")
        if any(item.close_time_ms >= fetched_at_server_ms for item in klines):
            raise ValueError("only candles closed by the recorded Binance server time may be stored")
        if any(
            current.open_time_ms <= previous.open_time_ms
            for previous, current in zip(klines, klines[1:], strict=False)
        ):
            raise ValueError("ingestion batch must be strictly chronological and unique")

        canonical = [item.to_dict() for item in klines]
        payload_bytes = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        run_id = uuid4().hex
        inserted = 0

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO ingestion_runs (
                    run_id, venue, symbol, interval, source, fetched_at_server_ms,
                    first_open_time_ms, last_open_time_ms, rows_received, rows_inserted,
                    payload_sha256, created_at_utc
                ) VALUES (?, 'binance_spot', ?, ?, 'binance_public_rest', ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    run_id,
                    symbol,
                    interval,
                    fetched_at_server_ms,
                    klines[0].open_time_ms,
                    klines[-1].open_time_ms,
                    len(klines),
                    payload_hash,
                    datetime.now(UTC).isoformat(),
                ),
            )

            select_sql = (
                f"SELECT {self._CANDLE_COLUMNS} FROM klines "
                "WHERE venue='binance_spot' AND symbol=? AND interval=? AND open_time_ms=?"
            )
            insert_sql = """
                INSERT INTO klines (
                    venue, symbol, interval, open_time_ms, open, high, low, close,
                    volume, close_time_ms, quote_asset_volume, number_of_trades,
                    taker_buy_base_asset_volume, taker_buy_quote_asset_volume, source_run_id
                ) VALUES (
                    'binance_spot', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """

            for item in klines:
                expected = (
                    item.open_time_ms,
                    decimal_text(item.open),
                    decimal_text(item.high),
                    decimal_text(item.low),
                    decimal_text(item.close),
                    decimal_text(item.volume),
                    item.close_time_ms,
                    decimal_text(item.quote_asset_volume),
                    item.number_of_trades,
                    decimal_text(item.taker_buy_base_asset_volume),
                    decimal_text(item.taker_buy_quote_asset_volume),
                )
                existing = connection.execute(
                    select_sql,
                    (symbol, interval, item.open_time_ms),
                ).fetchone()
                if existing is not None:
                    if tuple(existing) != expected:
                        raise DataConflictError(
                            f"stored candle changed: {symbol} {interval} {item.open_time_ms}"
                        )
                    continue

                connection.execute(
                    insert_sql,
                    (
                        symbol,
                        interval,
                        item.open_time_ms,
                        decimal_text(item.open),
                        decimal_text(item.high),
                        decimal_text(item.low),
                        decimal_text(item.close),
                        decimal_text(item.volume),
                        item.close_time_ms,
                        decimal_text(item.quote_asset_volume),
                        item.number_of_trades,
                        decimal_text(item.taker_buy_base_asset_volume),
                        decimal_text(item.taker_buy_quote_asset_volume),
                        run_id,
                    ),
                )
                inserted += 1

            if inserted == 0:
                connection.rollback()
                return BatchInsertResult(None, len(klines), 0, payload_hash)

            connection.execute(
                "UPDATE ingestion_runs SET rows_inserted=? WHERE run_id=?",
                (inserted, run_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return BatchInsertResult(run_id, len(klines), inserted, payload_hash)

    def audit(self, symbol: str, interval: str) -> DataQualityReport:
        interval_ms = INTERVAL_MS[interval]
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT open_time_ms
                FROM klines
                WHERE venue='binance_spot' AND symbol=? AND interval=?
                ORDER BY open_time_ms
                """,
                (symbol, interval),
            ).fetchall()

        timestamps = [row[0] for row in rows]
        missing = 0
        examples: list[tuple[int, int]] = []
        for previous, current in zip(timestamps, timestamps[1:], strict=False):
            delta = current - previous
            if delta > interval_ms:
                missing += max(0, delta // interval_ms - 1)
                if len(examples) < 20:
                    examples.append((previous, current))

        return DataQualityReport(
            symbol=symbol,
            interval=interval,
            rows=len(timestamps),
            first_open_time_ms=timestamps[0] if timestamps else None,
            last_open_time_ms=timestamps[-1] if timestamps else None,
            missing_intervals=missing,
            gap_examples=tuple(examples),
        )
