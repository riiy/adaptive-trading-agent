"""Prospective-only research decision and delayed feedback loop; never sends orders."""

import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from ata.research.baselines import research_snapshot
from ata.shadow.llm import LLMSettings, forecast_with_llm
from ata.shadow.models import (
    DAY_MS,
    FIRST_PROSPECTIVE_DAY_MS,
    HOUR_MS,
    PROMPT_VERSION,
    ShadowChoice,
    ShadowForecast,
    brier,
    sha256_json,
)
from ata.shadow.store import ShadowStore

OBSERVE_MIN_MINUTES = 5
OBSERVE_MAX_MINUTES = 45
SOURCE_BASELINE = "baseline"
SOURCE_LLM = "llm"


def _market_connection(market_db: str | Path) -> sqlite3.Connection:
    path = Path(market_db).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"market database missing: {path}")
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10.0)


def _close(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    open_ms: int,
    available_at_ms: int,
) -> Decimal | None:
    record = connection.execute(
        """
        SELECT close, close_time_ms
        FROM klines
        WHERE venue='binance_spot' AND symbol=? AND interval='1h' AND open_time_ms=?
        """,
        (symbol, open_ms),
    ).fetchone()
    if record is None or int(record[1]) >= available_at_ms:
        return None
    value = Decimal(record[0])
    if not value.is_finite() or value <= 0:
        raise ValueError(f"INVALID_MARKET_CLOSE:{symbol}")
    return value


def _observation_snapshot(market_db: str | Path, *, day_ms: int) -> dict[str, object]:
    snapshot = research_snapshot(
        market_db,
        asof_time_ms=day_ms,
        benchmark_days=7,
        max_lag_bars=0,
    ).to_dict()
    if snapshot["last_closed_open_time_ms"] != day_ms - HOUR_MS:
        raise ValueError("LATEST_CANDLE_NOT_AT_DECISION_CUTOFF")

    connection = _market_connection(market_db)
    try:
        prices: dict[str, str] = {}
        for symbol in ("BTCUSDT", "ETHUSDT"):
            value = _close(
                connection,
                symbol=symbol,
                open_ms=day_ms - HOUR_MS,
                available_at_ms=day_ms,
            )
            if value is None:
                raise ValueError(f"DECISION_REFERENCE_CLOSE_UNAVAILABLE:{symbol}")
            prices[symbol] = format(value, "f")
    finally:
        connection.close()

    snapshot["decision_time_ms"] = day_ms
    snapshot["reference_close_prices"] = prices
    snapshot["evaluation_horizon_hours"] = 24
    snapshot["scope"] = "PROSPECTIVE_SHADOW_RESEARCH_ONLY"
    return snapshot


def observe_once(
    market_db: str | Path,
    shadow_db: str | Path,
    *,
    now_ms: int | None = None,
    enable_llm: bool = False,
    settings: LLMSettings | None = None,
    forecaster=forecast_with_llm,
) -> dict[str, object]:
    """Run once near 00:15 UTC. No past-day creation, execution or account access."""
    now = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    day = now // DAY_MS * DAY_MS
    elapsed_minutes = (now - day) / 60_000
    if day < FIRST_PROSPECTIVE_DAY_MS:
        raise ValueError("M4 shadow forecasting begins on 2026-11-10 UTC")
    if not OBSERVE_MIN_MINUTES <= elapsed_minutes < OBSERVE_MAX_MINUTES:
        raise ValueError("NOT_IN_PROSPECTIVE_UTC_DECISION_WINDOW")

    store = ShadowStore(shadow_db)
    want_baseline = not store.has_forecast(day, SOURCE_BASELINE)
    want_llm = enable_llm and not store.has_forecast(day, SOURCE_LLM)
    if not want_baseline and not want_llm:
        return {"status": "ALREADY_RECORDED", "day_ms": day, "llm_enabled": enable_llm}

    # The snapshot is strictly as-of day 00:00 UTC, NOT as of the later API call.
    snapshot = _observation_snapshot(market_db, day_ms=day)
    digest = sha256_json(snapshot)
    sources_recorded: list[str] = []

    if want_baseline:
        store.append_forecast(
            day_ms=day,
            source=SOURCE_BASELINE,
            created_ms=now,
            model_id="fixed_usdt_p50_v1",
            prompt_version="deterministic-baseline-v1",
            snapshot_hash=digest,
            snapshot=snapshot,
            forecast=ShadowForecast.from_payload(
                {
                    "choice": "USDT",
                    "p_btc_up": "0.5",
                    "p_eth_up": "0.5",
                    "reason_code": "FIXED_UNINFORMED_BASELINE",
                    "hypothesis": "Fixed cash and 0.5 direction probability; no prediction edge.",
                }
            ),
        )
        sources_recorded.append(SOURCE_BASELINE)

    if want_llm:
        config = settings or LLMSettings.from_environment()
        llm_forecast = forecaster(snapshot, config)
        created = time.time_ns() // 1_000_000 if now_ms is None else now
        if not day <= created < day + OBSERVE_MAX_MINUTES * 60_000:
            raise ValueError("LLM_FORECAST_MISSED_PROSPECTIVE_WINDOW")
        store.append_forecast(
            day_ms=day,
            source=SOURCE_LLM,
            created_ms=created,
            model_id=config.model,
            prompt_version=PROMPT_VERSION,
            snapshot_hash=digest,
            snapshot=snapshot,
            forecast=llm_forecast,
        )
        sources_recorded.append(SOURCE_LLM)

    return {
        "status": "RECORDED",
        "day_ms": day,
        "snapshot_hash": digest,
        "sources_recorded": sources_recorded,
        "llm_enabled": enable_llm,
        "execution_allowed": False,
    }


def settle_pending(
    market_db: str | Path,
    shadow_db: str | Path,
    *,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Append an outcome only when both realized next-day closes exist."""
    now = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    store = ShadowStore(shadow_db)
    pending = store.pending()
    settled = 0
    outstanding = 0
    market = _market_connection(market_db)
    try:
        for item in pending:
            if now < item.day_ms + DAY_MS:
                outstanding += 1
                continue

            results: dict[str, str] = {}
            for symbol in ("BTCUSDT", "ETHUSDT"):
                reference = _close(
                    market,
                    symbol=symbol,
                    open_ms=item.day_ms - HOUR_MS,
                    available_at_ms=item.day_ms,
                )
                future = _close(
                    market,
                    symbol=symbol,
                    open_ms=item.day_ms + DAY_MS - HOUR_MS,
                    available_at_ms=now,
                )
                if reference is None:
                    raise ValueError(f"MISSING_FROZEN_REFERENCE_CLOSE:{symbol}")
                frozen = item.snapshot.get("reference_close_prices", {}).get(symbol)
                if format(reference, "f") != frozen:
                    raise ValueError(f"REFERENCE_CANDLE_CHANGED:{symbol}")
                if future is None:
                    break
                results[symbol] = format(future / reference - 1, "f")
            if len(results) != 2:
                outstanding += 1
                continue

            choice = item.forecast.choice
            selected = (
                None
                if choice is ShadowChoice.ABSTAIN
                else ("0" if choice is ShadowChoice.USDT else results[choice.value])
            )
            store.append_feedback(
                day_ms=item.day_ms,
                source=item.source,
                settled_ms=now,
                btc_return=results["BTCUSDT"],
                eth_return=results["ETHUSDT"],
                selected_return=selected,
                brier_btc=brier(item.forecast.p_btc_up, Decimal(results["BTCUSDT"]) > 0),
                brier_eth=brier(item.forecast.p_eth_up, Decimal(results["ETHUSDT"]) > 0),
            )
            settled += 1
    finally:
        market.close()

    return {
        "status": "SETTLEMENT_PASS",
        "newly_settled": settled,
        "still_pending": outstanding,
        "execution_allowed": False,
    }
