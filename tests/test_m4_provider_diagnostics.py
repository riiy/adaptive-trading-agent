"""M4 provider diagnostics must be actionable without exposing credentials."""

import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from ata import cli
from ata.shadow.llm import LLMSettings, forecast_with_llm
from ata.shadow.models import ShadowForecast


def settings() -> LLMSettings:
    return LLMSettings(
        url="https://provider.example/v1/chat/completions",
        model="test-model",
        api_key="private-test-token",
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502])
def test_provider_http_error_exposes_status_only(status: int) -> None:
    def opener(request, timeout):
        raise HTTPError(
            "https://provider.example/path?secret=private-test-token",
            status,
            "reason-contains-private-test-token",
            {"Authorization": "private-test-token"},
            io.BytesIO(b"response-secret-private-test-token"),
        )

    with pytest.raises(ValueError, match=f"LLM_PROVIDER_HTTP_{status}") as error:
        forecast_with_llm({"scope": "TEST"}, settings(), opener=opener)

    assert "private-test-token" not in str(error.value)
    assert "provider.example" not in str(error.value)
    assert "reason-contains" not in str(error.value)


def test_network_failure_message_does_not_leak_exception_reason() -> None:
    def opener(request, timeout):
        raise URLError("sensitive-network-detail-private-test-token")

    with pytest.raises(ValueError, match="LLM_PROVIDER_NETWORK_ERROR") as error:
        forecast_with_llm({"scope": "TEST"}, settings(), opener=opener)

    assert "private-test-token" not in str(error.value)


def test_full_completions_url_is_rejected_before_request(monkeypatch) -> None:
    monkeypatch.setenv(
        "ATA_LLM_BASE_URL",
        "https://provider.example/v1/chat/completions",
    )
    monkeypatch.setenv("ATA_LLM_API_KEY", "private-test-token")
    monkeypatch.setenv("ATA_LLM_MODEL", "test-model")

    with pytest.raises(ValueError, match="must be the API base"):
        LLMSettings.from_environment()


def test_provider_probe_uses_no_database_or_market_history(
    monkeypatch, tmp_path, capsys
) -> None:
    captured = []

    def fake_forecast(snapshot, config):
        captured.append((snapshot, config))
        return ShadowForecast.from_payload(
            {
                "choice": "ABSTAIN",
                "p_btc_up": "0.5",
                "p_eth_up": "0.5",
                "reason_code": "NO_MARKET_DATA",
                "hypothesis": "Test-only request.",
            }
        )

    monkeypatch.setattr(
        cli,
        "LLMSettings",
        SimpleNamespace(from_environment=settings),
    )
    monkeypatch.setattr(cli, "forecast_with_llm", fake_forecast)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["shadow", "probe-llm"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PASS"
    assert output["forecast_recorded"] is False
    assert output["database_mutated"] is False
    assert len(captured) == 1
    assert captured[0][0]["scope"] == "LLM_CONNECTIVITY_PROBE_ONLY"
    assert list(tmp_path.iterdir()) == []
