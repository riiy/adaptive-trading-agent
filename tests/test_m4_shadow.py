"""M4 tests: only genuine prospective timestamped shadow records may be scored."""

import json
import sqlite3
from decimal import Decimal

import pytest

from ata.marketdata.models import Kline
from ata.marketdata.storage import MarketDataRepository
from ata.shadow.engine import observe_once, settle_pending
from ata.shadow.llm import LLMSettings, forecast_with_llm
from ata.shadow.models import (
    DAY_MS,
    FIRST_PROSPECTIVE_DAY_MS,
    HOUR_MS,
    ShadowForecast,
)
from ata.shadow.scoring import shadow_score
from ata.shadow.store import ShadowStore

DAY = FIRST_PROSPECTIVE_DAY_MS + 2 * DAY_MS


def _candle(symbol: str, hour: int, close: Decimal) -> Kline:
    return Kline(
        symbol=symbol,
        interval="1h",
        open_time_ms=hour,
        open=close,
        high=close + Decimal(1),
        low=close - Decimal(1),
        close=close,
        volume=Decimal("10"),
        close_time_ms=hour + HOUR_MS - 1,
        quote_asset_volume=Decimal("1000"),
        number_of_trades=10,
        taker_buy_base_asset_volume=Decimal(4),
        taker_buy_quote_asset_volume=Decimal(400),
    )


@pytest.fixture
def fixture_db(tmp_path):
    market_db = tmp_path / "market.sqlite3"
    shadow_db = tmp_path / "shadow.sqlite3"
    repo = MarketDataRepository(market_db)
    # Eight days before the decision, plus the following day. Snapshot must
    # never include future bars even if their data are already in the test DB.
    start = DAY - (8 * 24 + 1) * HOUR_MS
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rows = [
            _candle(
                symbol,
                start + i * HOUR_MS,
                Decimal("100") + (Decimal(i) / 20 if symbol == "BTCUSDT" else -Decimal(i) / 25),
            )
            for i in range(9 * 24 + 1)
        ]
        repo.insert_batch(rows, fetched_at_server_ms=DAY + 2 * DAY_MS)
    return market_db, shadow_db


def _test_settings() -> LLMSettings:
    return LLMSettings(
        url="https://llm.example/v1/chat/completions",
        model="mock-model",
        api_key="not-a-real-token",
    )


def _fake_llm(_snapshot, _settings) -> ShadowForecast:
    return ShadowForecast.from_payload(
        {
            "choice": "BTCUSDT",
            "p_btc_up": "0.8",
            "p_eth_up": "0.2",
            "reason_code": "MOCK_FORECAST",
            "hypothesis": "Test-only forecast; never a trading signal.",
        }
    )


def test_prospective_observe_once_writes_frozen_baseline_and_llm(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    observed = observe_once(
        market_db,
        shadow_db,
        now_ms=DAY + 15 * 60_000,
        enable_llm=True,
        settings=_test_settings(),
        forecaster=_fake_llm,
    )
    assert observed["sources_recorded"] == ["baseline", "llm"]
    assert observed["execution_allowed"] is False
    store = ShadowStore(shadow_db)
    forecasts = store.pending()
    assert len(forecasts) == 2
    assert forecasts[0].snapshot["decision_time_ms"] == DAY
    assert forecasts[0].snapshot["last_closed_open_time_ms"] == DAY - HOUR_MS
    assert all(r.snapshot["reference_close_prices"]["BTCUSDT"] for r in forecasts)
    assert forecasts[0].snapshot == forecasts[1].snapshot


def test_duplicate_run_does_not_call_llm_twice(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    counter = []

    def counted(snapshot, settings):
        counter.append(1)
        return _fake_llm(snapshot, settings)

    first = observe_once(
        market_db,
        shadow_db,
        now_ms=DAY + 15 * 60_000,
        enable_llm=True,
        settings=_test_settings(),
        forecaster=counted,
    )
    second = observe_once(
        market_db,
        shadow_db,
        now_ms=DAY + 16 * 60_000,
        enable_llm=True,
        settings=_test_settings(),
        forecaster=counted,
    )
    assert first["status"] == "RECORDED"
    assert second["status"] == "ALREADY_RECORDED"
    assert counter == [1]


@pytest.mark.parametrize("minutes", [0, 4, 45, 90, 300])
def test_outside_forecast_window_fails_closed(fixture_db, minutes) -> None:
    market_db, shadow_db = fixture_db
    with pytest.raises(ValueError, match="NOT_IN_PROSPECTIVE_UTC_DECISION_WINDOW"):
        observe_once(market_db, shadow_db, now_ms=DAY + minutes * 60_000)


def test_no_backdated_predictions(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    with pytest.raises(ValueError, match="begins on 2026-11-10"):
        observe_once(
            market_db,
            shadow_db,
            now_ms=FIRST_PROSPECTIVE_DAY_MS - DAY_MS + 15 * 60_000,
        )


def test_settle_only_after_horizon_and_preserves_abstention(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    observe_once(
        market_db,
        shadow_db,
        now_ms=DAY + 15 * 60_000,
        enable_llm=True,
        settings=_test_settings(),
        forecaster=lambda _snapshot, _settings: ShadowForecast.from_payload(
            {
                "choice": "ABSTAIN",
                "p_btc_up": "0.5",
                "p_eth_up": "0.5",
                "reason_code": "WEAK_EVIDENCE",
                "hypothesis": "No calibrated advantage detected.",
            }
        ),
    )
    early = settle_pending(market_db, shadow_db, now_ms=DAY + 23 * HOUR_MS)
    assert early["newly_settled"] == 0
    assert early["still_pending"] == 2

    final = settle_pending(market_db, shadow_db, now_ms=DAY + DAY_MS + 10 * 60_000)
    assert final["newly_settled"] == 2
    assert (
        settle_pending(market_db, shadow_db, now_ms=DAY + DAY_MS + 11 * 60_000)["newly_settled"]
        == 0
    )

    rows = ShadowStore(shadow_db).settled()
    assert len(rows) == 2
    assert rows[0]["selected_return"] == "0"
    assert rows[1]["selected_return"] is None
    assert shadow_score(shadow_db)["sources"]["llm"]["choice_days_excluding_abstentions"] == 0


def test_scoring_reports_gross_benchmarks_and_probability_calibration(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    observe_once(
        market_db,
        shadow_db,
        now_ms=DAY + 15 * 60_000,
        enable_llm=True,
        settings=_test_settings(),
        forecaster=_fake_llm,
    )
    settle_pending(market_db, shadow_db, now_ms=DAY + DAY_MS + 10 * 60_000)
    report = shadow_score(shadow_db)
    assert report["trading_allowed"] is False
    assert report["account_simulation_allowed"] is False
    assert report["sources"]["baseline"]["mean_choice_gross_forward_24h_pct"] == "0.000000"
    assert report["sources"]["llm"]["settled_days"] == 1
    assert report["sources"]["llm"]["status"] == "EXPLORATORY_ONLY"
    assert report["sources"]["llm"]["mean_choice_gross_forward_24h_pct"] is not None
    assert Decimal(report["sources"]["llm"]["mean_brier_btc"]) < Decimal("0.25")


def test_llm_failure_retains_baseline_without_faking_forecast(fixture_db) -> None:
    market_db, shadow_db = fixture_db

    def broken(_snapshot, _settings):
        raise ValueError("provider failed")

    with pytest.raises(ValueError, match="provider failed"):
        observe_once(
            market_db,
            shadow_db,
            now_ms=DAY + 15 * 60_000,
            enable_llm=True,
            settings=_test_settings(),
            forecaster=broken,
        )
    pending = ShadowStore(shadow_db).pending()
    assert len(pending) == 1
    assert pending[0].source == "baseline"


def test_reject_forecast_schema_injection() -> None:
    payload = {
        "choice": "BTCUSDT",
        "p_btc_up": "0.7",
        "p_eth_up": "0.6",
        "reason_code": "RESEARCH",
        "hypothesis": "A bounded research explanation.",
    }
    for bad in [
        {**payload, "choice": "BUY_BTC"},
        {**payload, "p_btc_up": "NaN"},
        {**payload, "p_btc_up": "1.1"},
        {**payload, "order_api_key": "secret"},
        {**payload, "reason_code": "run shell"},
    ]:
        with pytest.raises(ValueError):
            ShadowForecast.from_payload(bad)


def test_llm_adapter_validates_response_without_network_access() -> None:
    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, max_bytes):
            assert max_bytes == 32769
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "choice": "ABSTAIN",
                                        "p_btc_up": 0.5,
                                        "p_eth_up": 0.5,
                                        "reason_code": "TEST",
                                        "hypothesis": "This is not an order.",
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    def opener(request, timeout):
        assert timeout == 20
        assert request.full_url.endswith("/chat/completions")
        assert request.get_header("Authorization").startswith("Bearer ")
        return MockResponse()

    forecast = forecast_with_llm(
        {"features": []},
        _test_settings(),
        opener=opener,
    )
    assert forecast.choice.value == "ABSTAIN"


def test_llm_settings_require_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        LLMSettings(url="http://127.0.0.1/v1/chat/completions", model="x", api_key="secret")


def test_repeated_feedback_is_write_once(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    observe_once(market_db, shadow_db, now_ms=DAY + 15 * 60_000)
    settle_pending(market_db, shadow_db, now_ms=DAY + DAY_MS + 10 * 60_000)
    with sqlite3.connect(shadow_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM shadow_feedback").fetchone()[0] == 1


def test_missing_hourly_bar_in_label_horizon_prevents_feedback(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    observe_once(market_db, shadow_db, now_ms=DAY + 15 * 60_000)
    with sqlite3.connect(market_db) as connection:
        connection.execute(
            "DELETE FROM klines WHERE symbol='BTCUSDT' AND interval='1h' "
            "AND open_time_ms=?",
            (DAY + 12 * HOUR_MS,),
        )

    result = settle_pending(market_db, shadow_db, now_ms=DAY + DAY_MS + 60_000)
    assert result["newly_settled"] == 0
    assert result["still_pending"] == 1
    assert ShadowStore(shadow_db).settled() == []


def test_snapshot_integrity_is_checked_before_scoring(fixture_db) -> None:
    market_db, shadow_db = fixture_db
    observe_once(market_db, shadow_db, now_ms=DAY + 15 * 60_000)
    with sqlite3.connect(shadow_db) as connection:
        connection.execute(
            "UPDATE shadow_forecasts SET snapshot_json='{}' WHERE source='baseline'"
        )

    with pytest.raises(ValueError, match="SHADOW_SNAPSHOT_HASH_MISMATCH"):
        settle_pending(market_db, shadow_db, now_ms=DAY + DAY_MS + 60_000)
