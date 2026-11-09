"""Optional HTTPS research-only LLM adapter, with strict JSON response validation.

No tools, no execution functions, no repository mutation, no Binance trading clients.
"""

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ata.shadow.models import ShadowForecast, canonical_json


class _RejectRedirects(HTTPRedirectHandler):
    """Do not forward a provider bearer token to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_without_redirects(request: Request, *, timeout: float):
    return build_opener(_RejectRedirects).open(request, timeout=timeout)


SYSTEM_PROMPT = (
    "You are a research forecaster, NOT a trader. Only describe your uncertainty. "
    "You cannot submit orders or alter risk limits. Return one JSON object with "
    "exactly: choice (BTCUSDT, ETHUSDT, USDT, or ABSTAIN), "
    "p_btc_up (probability BTC 24h forward close-to-close return > 0), "
    "p_eth_up (probability ETH 24h forward close-to-close return > 0), "
    "reason_code (UPPERCASE_IDENTIFIER up to 40 characters), and "
    "hypothesis (one concise explanation up to 240 characters). "
    "If evidence is weak, prefer ABSTAIN. No Markdown. No future information."
)


@dataclass(frozen=True, slots=True)
class LLMSettings:
    url: str
    model: str
    api_key: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_environment(cls) -> "LLMSettings":
        base = os.getenv("ATA_LLM_BASE_URL", "").rstrip("/")
        key = os.getenv("ATA_LLM_API_KEY", "")
        model = os.getenv("ATA_LLM_MODEL", "")
        if not base or not key or not model:
            raise ValueError("LLM disabled: ATA_LLM_BASE_URL, ATA_LLM_MODEL and API key required")
        return cls(url=base + "/chat/completions", model=model, api_key=key)

    def __post_init__(self) -> None:
        parts = urlsplit(self.url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("LLM endpoint must be a clean HTTPS URL")
        if not self.model or not self.api_key or not 0 < self.timeout_seconds <= 30:
            raise ValueError("invalid LLM model, credential or timeout")


def forecast_with_llm(
    snapshot: dict[str, object],
    settings: LLMSettings,
    *,
    opener: Any = _open_without_redirects,
) -> ShadowForecast:
    """One bounded, non-retried OpenAI-compatible chat completion request."""
    body = canonical_json(
        {
            "model": settings.model,
            "temperature": 0,
            "max_tokens": 240,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Data available at decision time (closed candles only): "
                    + canonical_json(snapshot),
                },
            ],
        }
    ).encode("utf-8")
    request = Request(
        settings.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.api_key}",
        },
    )
    try:
        with opener(request, timeout=settings.timeout_seconds) as response:
            data = response.read(32_769)
            if len(data) > 32_768:
                raise ValueError("LLM response exceeds maximum size")
    except (HTTPError, URLError, OSError, TimeoutError):
        # Never propagate remote bodies, headers or URLs, which may contain secrets.
        raise ValueError("LLM provider request failed; no forecast accepted") from None

    try:
        response_object = json.loads(data)
        choices = response_object["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("expected exactly one completion")
        content = choices[0]["message"]["content"]
        return ShadowForecast.from_payload(json.loads(content))
    except (KeyError, TypeError, IndexError, json.JSONDecodeError):
        raise ValueError("LLM returned an invalid structured forecast") from None
