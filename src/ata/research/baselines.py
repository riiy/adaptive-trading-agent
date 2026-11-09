"""Causal market description and non-trading buy-and-hold benchmarks.

This module opens the existing M1 database read-only and has no order adapter.
"""

import math
import sqlite3
import statistics
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from ata.marketdata.models import INTERVAL_MS

HOUR_MS = INTERVAL_MS["1h"]
HOURS_PER_YEAR = 365 * 24
SYMBOLS = ("BTCUSDT", "ETHUSDT")
LOOKBACK_HOURS = 7 * 24


@dataclass(frozen=True, slots=True)
class HourlyBar:
    open_time_ms: int
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class SymbolFeatures:
    symbol: str
    momentum_24h_pct: str
    momentum_7d_pct: str
    realized_vol_7d_annualized_pct: str
    volume_last24h_vs_previous144h: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "symbol": self.symbol,
            "momentum_24h_pct": self.momentum_24h_pct,
            "momentum_7d_pct": self.momentum_7d_pct,
            "realized_vol_7d_annualized_pct": self.realized_vol_7d_annualized_pct,
            "volume_last24h_vs_previous144h": self.volume_last24h_vs_previous144h,
        }


@dataclass(frozen=True, slots=True)
class ResearchSnapshot:
    asof_time_ms: int
    last_closed_open_time_ms: int
    benchmark_days: int
    fee_bps_per_side: str
    slippage_bps_per_side: str
    features: tuple[SymbolFeatures, ...]
    buy_and_hold_net_return_pct: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "DESCRIPTIVE_ONLY",
            "system_mode": "RESEARCH_ONLY",
            "execution_allowed": False,
            "asof_time_ms": self.asof_time_ms,
            "last_closed_open_time_ms": self.last_closed_open_time_ms,
            "benchmark_days": self.benchmark_days,
            "features": [item.to_dict() for item in self.features],
            "buy_and_hold_net_return_pct": self.buy_and_hold_net_return_pct,
            "cost_assumptions": {
                "fee_bps_per_side": self.fee_bps_per_side,
                "slippage_bps_per_side": self.slippage_bps_per_side,
                "note": "Illustrative assumptions, not actual exchange fees or executable fills.",
            },
            "interpretation": (
                "Descriptive observations and passive benchmarks only. "
                "No strategy has been validated; no trading action is authorized."
            ),
        }


def _format_decimal(value: Decimal, places: int = 6) -> str:
    return f"{value:.{places}f}"


def _hourly_rows(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    end_open_time_ms: int,
    expected_rows: int,
) -> list[HourlyBar]:
    records = connection.execute(
        """
        SELECT open_time_ms, close, volume
        FROM klines
        WHERE venue='binance_spot' AND symbol=? AND interval='1h'
          AND open_time_ms<=?
        ORDER BY open_time_ms DESC LIMIT ?
        """,
        (symbol, end_open_time_ms, expected_rows),
    ).fetchall()

    if len(records) != expected_rows:
        raise ValueError(
            f"INSUFFICIENT_HISTORY:{symbol}: expected {expected_rows} rows, got {len(records)}"
        )

    rows = [
        HourlyBar(int(t), Decimal(close), Decimal(volume))
        for t, close, volume in reversed(records)
    ]
    if rows[-1].open_time_ms != end_open_time_ms:
        raise ValueError(f"STALE_OR_UNALIGNED_SERIES:{symbol}")
    if any(
        current.open_time_ms - previous.open_time_ms != HOUR_MS
        for previous, current in zip(rows, rows[1:], strict=False)
    ):
        raise ValueError(f"MISSING_OR_UNORDERED_BARS:{symbol}")
    if any(row.close <= 0 or not row.close.is_finite() for row in rows):
        raise ValueError(f"INVALID_CLOSE:{symbol}")
    if any(row.volume < 0 or not row.volume.is_finite() for row in rows):
        raise ValueError(f"INVALID_VOLUME:{symbol}")
    return rows


def _features(symbol: str, rows: list[HourlyBar]) -> SymbolFeatures:
    tail = rows[-(LOOKBACK_HOURS + 1):]
    closes = [row.close for row in tail]
    last = closes[-1]
    momentum_24h = (last / closes[-25] - 1) * 100
    momentum_7d = (last / closes[0] - 1) * 100

    # Historical realized volatility on *past* closed-bar returns only.
    log_returns = [
        math.log(float(current / previous))
        for previous, current in zip(closes, closes[1:], strict=False)
    ]
    annual_vol_pct = Decimal(str(statistics.stdev(log_returns) * math.sqrt(HOURS_PER_YEAR) * 100))

    # Latest 24 hours versus the 144 hours immediately preceding them.
    trailing_volumes = [row.volume for row in tail[1:]]
    recent = sum(trailing_volumes[-24:], Decimal("0")) / 24
    prior = sum(trailing_volumes[:-24], Decimal("0")) / 144
    volume_ratio = recent / prior if prior > 0 else None
    return SymbolFeatures(
        symbol=symbol,
        momentum_24h_pct=_format_decimal(momentum_24h),
        momentum_7d_pct=_format_decimal(momentum_7d),
        realized_vol_7d_annualized_pct=_format_decimal(annual_vol_pct),
        volume_last24h_vs_previous144h=(
            _format_decimal(volume_ratio) if volume_ratio is not None else None
        ),
    )


def _buy_hold_net_return_pct(
    rows: list[HourlyBar],
    *,
    fee_bps: Decimal,
    slippage_bps: Decimal,
) -> str:
    side_cost = (fee_bps + slippage_bps) / Decimal("10000")
    gross_multiplier = rows[-1].close / rows[0].close
    net_multiplier = gross_multiplier * (1 - side_cost) * (1 - side_cost)
    return _format_decimal((net_multiplier - 1) * 100)


def research_snapshot(
    database_path: str | Path,
    *,
    asof_time_ms: int,
    benchmark_days: int = 180,
    fee_bps_per_side: Decimal = Decimal("10"),
    slippage_bps_per_side: Decimal = Decimal("5"),
    max_lag_bars: int | None = 2,
) -> ResearchSnapshot:
    """Produce a point-in-time read-only comparison from completed 1h candles.

    As-of is exclusive: no candle whose close is not strictly before asof is used.
    For historical replays, set max_lag_bars=None to disable *current* freshness.
    """
    if asof_time_ms <= HOUR_MS:
        raise ValueError("asof_time_ms must be after the first possible closed hour")
    if benchmark_days < 7 or benchmark_days > 365:
        raise ValueError("benchmark_days must be between 7 and 365")
    if max_lag_bars is not None and max_lag_bars < 0:
        raise ValueError("max_lag_bars must be non-negative")
    for amount in (fee_bps_per_side, slippage_bps_per_side):
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
            raise ValueError("fees and slippage must be finite non-negative decimals")
    if (fee_bps_per_side + slippage_bps_per_side) >= Decimal("10000"):
        raise ValueError("combined fee and slippage per side must be below 10000 bps")

    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"market database does not exist: {path}")

    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        latest_closed: dict[str, int] = {}
        for symbol in SYMBOLS:
            record = connection.execute(
                """
                SELECT MAX(open_time_ms)
                FROM klines
                WHERE venue='binance_spot' AND symbol=? AND interval='1h'
                  AND close_time_ms < ?
                """,
                (symbol, asof_time_ms),
            ).fetchone()
            if record is None or record[0] is None:
                raise ValueError(f"NO_CLOSED_HOURLY_DATA:{symbol}")
            latest_closed[symbol] = int(record[0])
        common_end = min(latest_closed.values())
        expected_last = (asof_time_ms // HOUR_MS - 1) * HOUR_MS
        if max_lag_bars is not None and expected_last - common_end > max_lag_bars * HOUR_MS:
            raise ValueError("STALE_MARKET_DATA")

        rows_needed = benchmark_days * 24 + 1
        aligned = {
            symbol: _hourly_rows(
                connection,
                symbol=symbol,
                end_open_time_ms=common_end,
                expected_rows=rows_needed,
            )
            for symbol in SYMBOLS
        }
    finally:
        connection.close()

    result_features = tuple(_features(symbol, aligned[symbol]) for symbol in SYMBOLS)
    baselines = {"USDT": "0.000000"}
    for symbol in SYMBOLS:
        baselines[symbol] = _buy_hold_net_return_pct(
            aligned[symbol],
            fee_bps=fee_bps_per_side,
            slippage_bps=slippage_bps_per_side,
        )
    return ResearchSnapshot(
        asof_time_ms=asof_time_ms,
        last_closed_open_time_ms=common_end,
        benchmark_days=benchmark_days,
        fee_bps_per_side=_format_decimal(fee_bps_per_side, 2),
        slippage_bps_per_side=_format_decimal(slippage_bps_per_side, 2),
        features=result_features,
        buy_and_hold_net_return_pct=baselines,
    )
