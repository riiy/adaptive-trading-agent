"""Read-only M1 market-data quality gate.

This gate checks local persisted history; it never calls Binance or changes the database.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from ata.marketdata.models import INTERVAL_MS

DAY_MS = 86_400_000
REQUIRED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
REQUIRED_INTERVALS = ("15m", "1h", "4h")


@dataclass(frozen=True, slots=True)
class SeriesReadiness:
    symbol: str
    interval: str
    rows: int
    first_open_time_ms: int | None
    last_open_time_ms: int | None
    history_days: float
    missing_bars: int
    lag_bars: int | None
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "status": "PASS" if not self.issues else "FAIL",
            "rows": self.rows,
            "first_open_time_ms": self.first_open_time_ms,
            "last_open_time_ms": self.last_open_time_ms,
            "history_days": round(self.history_days, 3),
            "missing_bars": self.missing_bars,
            "lag_bars": self.lag_bars,
            "issues": list(self.issues),
        }


@dataclass(frozen=True, slots=True)
class M1Readiness:
    database_path: str
    database_issues: tuple[str, ...]
    series: tuple[SeriesReadiness, ...]

    @property
    def passed(self) -> bool:
        return not self.database_issues and all(not row.issues for row in self.series)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "scope": "M1_DATA_ONLY",
            "database": self.database_path,
            "database_issues": list(self.database_issues),
            "series": [row.to_dict() for row in self.series],
            "note": "Server timer, journal, and repeated-sync operation require separate checks.",
        }


def _read_series(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    interval: str,
    now_ms: int,
    min_history_days: int,
    max_lag_bars: int,
) -> SeriesReadiness:
    interval_ms = INTERVAL_MS[interval]
    timestamps = [
        int(row[0])
        for row in connection.execute(
            """
            SELECT open_time_ms FROM klines
            WHERE venue='binance_spot' AND symbol=? AND interval=?
            ORDER BY open_time_ms
            """,
            (symbol, interval),
        )
    ]
    issues: list[str] = []
    rows = len(timestamps)
    if not timestamps:
        issues.append("EMPTY_SERIES")
        return SeriesReadiness(symbol, interval, 0, None, None, 0.0, 0, None, tuple(issues))

    first = timestamps[0]
    last = timestamps[-1]
    history_days = (last - first) / DAY_MS
    missing = 0
    for previous, current in zip(timestamps, timestamps[1:], strict=False):
        difference = current - previous
        if difference <= 0 or difference % interval_ms != 0:
            issues.append("INVALID_TIME_SEQUENCE")
        elif difference > interval_ms:
            missing += difference // interval_ms - 1
    if missing:
        issues.append("MISSING_BARS")
    if history_days < min_history_days:
        issues.append("INSUFFICIENT_HISTORY")

    # The bar currently forming at now_ms is not expected to be stored yet.
    expected_last_closed_open = (now_ms // interval_ms - 1) * interval_ms
    lag_bars = (expected_last_closed_open - last) // interval_ms
    if last > expected_last_closed_open:
        issues.append("FUTURE_OR_OPEN_CANDLE")
    elif lag_bars > max_lag_bars:
        issues.append("STALE_DATA")

    return SeriesReadiness(
        symbol,
        interval,
        rows,
        first,
        last,
        history_days,
        missing,
        lag_bars,
        tuple(issues),
    )


def verify_m1(
    database_path: str | Path,
    *,
    now_ms: int,
    min_history_days: int = 350,
    max_lag_bars: int = 2,
) -> M1Readiness:
    """Check all six expected streams using a strictly read-only SQLite connection."""
    if now_ms <= 0 or min_history_days < 0 or max_lag_bars < 0:
        raise ValueError("verification time and thresholds must be non-negative")
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"market database does not exist: {path}")

    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        database_issues: list[str] = []
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if schema_version != 1:
            database_issues.append(f"UNEXPECTED_SCHEMA_VERSION:{schema_version}")
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or quick_check[0] != "ok":
            database_issues.append("SQLITE_QUICK_CHECK_FAILED")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            database_issues.append("BROKEN_INGESTION_PROVENANCE")

        series: list[SeriesReadiness] = []
        for symbol in REQUIRED_SYMBOLS:
            for interval in REQUIRED_INTERVALS:
                series.append(
                    _read_series(
                        connection,
                        symbol=symbol,
                        interval=interval,
                        now_ms=now_ms,
                        min_history_days=min_history_days,
                        max_lag_bars=max_lag_bars,
                    )
                )
        return M1Readiness(str(path), tuple(database_issues), tuple(series))
    finally:
        connection.close()
