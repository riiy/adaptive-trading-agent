"""Write-once shadow forecasts and append-only feedback, isolated from market data."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ata.shadow.models import ShadowForecast, canonical_json, sha256_json


@dataclass(frozen=True, slots=True)
class PendingForecast:
    day_ms: int
    source: str
    forecast: ShadowForecast
    snapshot: dict[str, Any]


class ShadowStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS shadow_forecasts (
                    day_ms INTEGER NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('baseline', 'llm')),
                    created_ms INTEGER NOT NULL,
                    model_id TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    forecast_json TEXT NOT NULL,
                    PRIMARY KEY (day_ms, source)
                );
                CREATE TABLE IF NOT EXISTS shadow_feedback (
                    day_ms INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    settled_ms INTEGER NOT NULL,
                    btc_return TEXT NOT NULL,
                    eth_return TEXT NOT NULL,
                    selected_return TEXT,
                    brier_btc TEXT NOT NULL,
                    brier_eth TEXT NOT NULL,
                    PRIMARY KEY (day_ms, source),
                    FOREIGN KEY (day_ms, source)
                        REFERENCES shadow_forecasts(day_ms, source)
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def has_forecast(self, day_ms: int, source: str) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM shadow_forecasts WHERE day_ms=? AND source=?",
                (day_ms, source),
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def append_forecast(
        self,
        *,
        day_ms: int,
        source: str,
        created_ms: int,
        model_id: str,
        prompt_version: str,
        snapshot_hash: str,
        snapshot: dict[str, Any],
        forecast: ShadowForecast,
    ) -> None:
        if source not in ("baseline", "llm"):
            raise ValueError("invalid forecast source")
        if not day_ms <= created_ms < day_ms + 45 * 60_000:
            raise ValueError("shadow forecast must be issued within 45 minutes of cutoff")
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO shadow_forecasts (
                        day_ms, source, created_ms, model_id, prompt_version,
                        snapshot_hash, snapshot_json, forecast_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        day_ms,
                        source,
                        created_ms,
                        model_id,
                        prompt_version,
                        snapshot_hash,
                        canonical_json(snapshot),
                        canonical_json(forecast.to_dict()),
                    ),
                )
        finally:
            connection.close()

    def pending(self) -> list[PendingForecast]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT f.day_ms, f.source, f.forecast_json, f.snapshot_json,
                       f.snapshot_hash
                FROM shadow_forecasts f
                LEFT JOIN shadow_feedback b
                  ON b.day_ms=f.day_ms AND b.source=f.source
                WHERE b.day_ms IS NULL
                ORDER BY f.day_ms, f.source
                """
            ).fetchall()
        finally:
            connection.close()

        pending: list[PendingForecast] = []
        for day_ms, source, forecast_json, snapshot_json, snapshot_hash in rows:
            snapshot = json.loads(snapshot_json)
            if sha256_json(snapshot) != snapshot_hash:
                raise ValueError("SHADOW_SNAPSHOT_HASH_MISMATCH")
            pending.append(
                PendingForecast(
                    day_ms=day_ms,
                    source=source,
                    forecast=ShadowForecast.from_payload(json.loads(forecast_json)),
                    snapshot=snapshot,
                )
            )
        return pending

    def append_feedback(
        self,
        *,
        day_ms: int,
        source: str,
        settled_ms: int,
        btc_return: str,
        eth_return: str,
        selected_return: str | None,
        brier_btc: str,
        brier_eth: str,
    ) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO shadow_feedback (
                        day_ms, source, settled_ms, btc_return, eth_return,
                        selected_return, brier_btc, brier_eth
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        day_ms,
                        source,
                        settled_ms,
                        btc_return,
                        eth_return,
                        selected_return,
                        brier_btc,
                        brier_eth,
                    ),
                )
        finally:
            connection.close()

    def settled(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT f.day_ms, f.source, f.forecast_json, b.btc_return,
                       b.eth_return, b.selected_return, b.brier_btc, b.brier_eth
                FROM shadow_forecasts f
                JOIN shadow_feedback b
                  ON b.day_ms=f.day_ms AND b.source=f.source
                ORDER BY f.day_ms, f.source
                """
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "day_ms": row[0],
                "source": row[1],
                "forecast": json.loads(row[2]),
                "btc_return": row[3],
                "eth_return": row[4],
                "selected_return": row[5],
                "brier_btc": row[6],
                "brier_eth": row[7],
            }
            for row in rows
        ]
