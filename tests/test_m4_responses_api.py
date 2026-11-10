"""Explicit Responses API support stays isolated from trading and database writes."""

import json
from urllib.request import Request

import pytest

from ata.shadow.llm import LLMSettings, forecast_with_llm

FORECAST_JSON = {
    "choice": "ABSTAIN",
    "p_btc_up": "0.5",
    "p_eth_up": "0.5",
    "reason_code": "NO_MARKET_DATA",
    "hypothesis": "Provider compatibility probe only.",
}


class FakeResponse:
    def __init__(self, value):
        self.payload = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.payload


def test_responses_environment_builds_correct_endpoint(monkeypatch):
    monkeypatch.setenv("ATA_LLM_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("ATA_LLM_MODEL", "chatgpt/test-model")
    monkeypatch.setenv("ATA_LLM_API_KEY", "test-token")
    monkeypatch.setenv("ATA_LLM_API_STYLE", "responses")

    settings = LLMSettings.from_environment()
    assert settings.url == "https://proxy.example/v1/responses"
    assert settings.api_style == "responses"


def test_chat_completions_remains_backward_compatible(monkeypatch):
    monkeypatch.setenv("ATA_LLM_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("ATA_LLM_MODEL", "chatgpt/test-model")
    monkeypatch.setenv("ATA_LLM_API_KEY", "test-token")
    monkeypatch.delenv("ATA_LLM_API_STYLE", raising=False)

    settings = LLMSettings.from_environment()
    assert settings.url == "https://proxy.example/v1/chat/completions"
    assert settings.api_style == "chat_completions"


@pytest.mark.parametrize("value", ["unknown", "response", "chat", ""])
def test_invalid_api_style_rejected(monkeypatch, value):
    monkeypatch.setenv("ATA_LLM_BASE_URL", "https://proxy.example/v1")
    monkeypatch.setenv("ATA_LLM_MODEL", "m")
    monkeypatch.setenv("ATA_LLM_API_KEY", "test-token")
    monkeypatch.setenv("ATA_LLM_API_STYLE", value)

    with pytest.raises(ValueError, match="ATA_LLM_API_STYLE"):
        LLMSettings.from_environment()


@pytest.mark.parametrize(
    "suffix", ["/responses", "/chat/completions"]
)
def test_base_url_must_not_include_endpoint(monkeypatch, suffix):
    monkeypatch.setenv("ATA_LLM_BASE_URL", "https://proxy.example/v1" + suffix)
    monkeypatch.setenv("ATA_LLM_MODEL", "m")
    monkeypatch.setenv("ATA_LLM_API_KEY", "test-token")
    monkeypatch.setenv("ATA_LLM_API_STYLE", "responses")

    with pytest.raises(ValueError, match="API base"):
        LLMSettings.from_environment()


def test_responses_request_and_structured_output():
    captured = []

    def opener(request: Request, timeout):
        captured.append((request, timeout))
        return FakeResponse(
            {
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": json.dumps(FORECAST_JSON)}
                        ],
                    },
                ],
            }
        )

    config = LLMSettings(
        url="https://proxy.example/v1/responses",
        model="chatgpt/test-model",
        api_key="test-token",
        api_style="responses",
    )
    forecast = forecast_with_llm({"scope": "TEST"}, config, opener=opener)
    assert forecast.choice.value == "ABSTAIN"
    request, timeout = captured[0]
    assert timeout == 20
    assert request.full_url == "https://proxy.example/v1/responses"
    assert request.get_method() == "POST"
    payload = json.loads(request.data)
    assert payload["model"] == "chatgpt/test-model"
    assert payload["max_output_tokens"] == 512
    assert payload["input"][0]["role"] == "system"
    assert payload["input"][1]["role"] == "user"
    assert "messages" not in payload
    assert "temperature" not in payload


def test_responses_output_text_gateway_fallback():
    config = LLMSettings(
        url="https://proxy.example/v1/responses",
        model="m",
        api_key="test",
        api_style="responses",
    )
    forecast = forecast_with_llm(
        {"scope": "TEST"},
        config,
        opener=lambda *_args, **_kwargs: FakeResponse(
            {"output_text": json.dumps(FORECAST_JSON)}
        ),
    )
    assert forecast.reason_code == "NO_MARKET_DATA"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "incomplete", "output": []},
        {"status": "failed", "output_text": json.dumps(FORECAST_JSON)},
        {"status": "completed", "output": [{"type": "tool_call"}]},
        {"status": "completed", "output": [{"type": "reasoning"}]},
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "not json"}],
                }
            ],
        },
    ],
)
def test_responses_incomplete_or_non_forecast_fails_closed(payload):
    config = LLMSettings(
        url="https://proxy.example/v1/responses",
        model="m",
        api_key="test",
        api_style="responses",
    )
    with pytest.raises(ValueError):
        forecast_with_llm(
            {"scope": "TEST"},
            config,
            opener=lambda *_args, **_kwargs: FakeResponse(payload),
        )


def test_response_api_style_cannot_be_mismatched_with_url():
    with pytest.raises(ValueError, match="do not match"):
        LLMSettings(
            url="https://proxy.example/v1/chat/completions",
            model="m",
            api_key="test",
            api_style="responses",
        )
