"""A provider-edge User-Agent override must be explicit and header-safe."""

import json

import pytest

from ata.shadow.llm import LLMSettings, forecast_with_llm

FORECAST = {
    "choice": "ABSTAIN",
    "p_btc_up": "0.5",
    "p_eth_up": "0.5",
    "reason_code": "NO_EDGE",
    "hypothesis": "Connectivity verification only.",
}


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return json.dumps({"output_text": json.dumps(FORECAST)}).encode()


def test_opt_in_user_agent_used_for_responses_requests(monkeypatch):
    monkeypatch.setenv("ATA_LLM_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("ATA_LLM_MODEL", "mock-model")
    monkeypatch.setenv("ATA_LLM_API_KEY", "private-token")
    monkeypatch.setenv("ATA_LLM_API_STYLE", "responses")
    monkeypatch.setenv("ATA_LLM_USER_AGENT", "curl/8.5.0")

    settings = LLMSettings.from_environment()
    assert settings.user_agent == "curl/8.5.0"
    observed = []

    def opener(request, timeout):
        observed.append((request, timeout))
        return Response()

    forecast = forecast_with_llm({"scope": "TEST"}, settings, opener=opener)
    assert forecast.choice.value == "ABSTAIN"
    request, timeout = observed[0]
    assert timeout == 20
    assert request.get_header("User-agent") == "curl/8.5.0"
    assert request.get_header("Authorization") == "Bearer private-token"
    assert request.full_url == "https://proxy.example/v1/responses"
    assert json.loads(request.data)["model"] == "mock-model"


def test_default_behavior_has_no_explicit_user_agent(monkeypatch):
    monkeypatch.setenv("ATA_LLM_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("ATA_LLM_API_STYLE", "responses")
    monkeypatch.setenv("ATA_LLM_MODEL", "mock-model")
    monkeypatch.setenv("ATA_LLM_API_KEY", "private-token")
    monkeypatch.delenv("ATA_LLM_USER_AGENT", raising=False)

    settings = LLMSettings.from_environment()
    assert settings.user_agent is None
    seen = []

    def opener(request, timeout):
        seen.append(request)
        return Response()

    forecast_with_llm({"scope": "TEST"}, settings, opener=opener)
    assert seen[0].get_header("User-agent") is None


@pytest.mark.parametrize(
    "agent",
    [
        "curl/8.5.0\r\nAuthorization: stolen",
        "curl/8.5.0\nHost: wrong.example",
        "curl/8.5.0\t",
        "\x00",
        "字节",
        "x" * 129,
    ],
)
def test_reject_control_non_ascii_or_overlong_user_agent(agent):
    with pytest.raises(ValueError, match="ATA_LLM_USER_AGENT"):
        LLMSettings(
            url="https://proxy.example/v1/responses",
            model="mock-model",
            api_key="private-token",
            api_style="responses",
            user_agent=agent,
        )
