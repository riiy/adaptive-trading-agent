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
    api_style: str = "chat_completions"
    user_agent: str | None = None

    @classmethod
    def from_environment(cls) -> "LLMSettings":
        base = os.getenv("ATA_LLM_BASE_URL", "").rstrip("/")
        key = os.getenv("ATA_LLM_API_KEY", "")
        model = os.getenv("ATA_LLM_MODEL", "")
        api_style = os.getenv("ATA_LLM_API_STYLE", "chat_completions").strip()
        user_agent = os.getenv("ATA_LLM_USER_AGENT") or None
        if not base or not key or not model:
            raise ValueError("LLM disabled: ATA_LLM_BASE_URL, ATA_LLM_MODEL and API key required")
        if api_style not in ("chat_completions", "responses"):
            raise ValueError("ATA_LLM_API_STYLE must be chat_completions or responses")
        if base.endswith(("/chat/completions", "/responses")):
            raise ValueError("ATA_LLM_BASE_URL must be the API base, without endpoint suffix")
        suffix = "/responses" if api_style == "responses" else "/chat/completions"
        return cls(
            url=base + suffix,
            model=model,
            api_key=key,
            api_style=api_style,
            user_agent=user_agent,
        )

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
        if self.api_style not in ("chat_completions", "responses"):
            raise ValueError("invalid LLM API style")
        expected_suffix = "/responses" if self.api_style == "responses" else "/chat/completions"
        if not parts.path.endswith(expected_suffix):
            raise ValueError("LLM endpoint and API style do not match")
        # A User-Agent can be opted in for restrictive trusted reverse proxies.
        # Never allow CR/LF or any other control characters into HTTP headers.
        if self.user_agent is not None and (
            not 1 <= len(self.user_agent) <= 128
            or not self.user_agent.isascii()
            or any(not 32 <= ord(character) <= 126 for character in self.user_agent)
        ):
            raise ValueError("ATA_LLM_USER_AGENT must be printable ASCII (1-128 characters)")


def _response_text(payload: object, *, api_style: str) -> str:
    """Extract only assistant text, never provider tool/reasoning records."""
    if not isinstance(payload, dict):
        raise ValueError("LLM returned an invalid structured forecast")

    if api_style == "responses":
        if payload.get("status") not in (None, "completed"):
            raise ValueError("LLM response incomplete; no forecast accepted")

        text_parts: list[str] = []
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "message" or item.get("role") != "assistant":
                    continue
                blocks = item.get("content")
                if not isinstance(blocks, list):
                    continue
                for block in blocks:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "output_text"
                        and isinstance(block.get("text"), str)
                    ):
                        text_parts.append(block["text"])

        if text_parts:
            return "".join(text_parts)
        # Some compatible gateways expose an SDK-like top-level convenience field.
        flat = payload.get("output_text")
        if isinstance(flat, str) and flat:
            return flat
        raise ValueError("LLM returned no assistant output_text")

    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("LLM returned an invalid structured forecast")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("LLM returned an invalid structured forecast")
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("LLM returned an invalid structured forecast")
    return message["content"]


def forecast_with_llm(
    snapshot: dict[str, object],
    settings: LLMSettings,
    *,
    opener: Any = _open_without_redirects,
) -> ShadowForecast:
    """Call one selected HTTPS API endpoint without tools, retries or database writes."""
    context = "Data available at decision time (closed candles only): " + canonical_json(snapshot)
    if settings.api_style == "responses":
        # Responses models may not support chat-specific temperature/max_tokens.
        request_payload = {
            "model": settings.model,
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            "max_output_tokens": 512,
        }
    else:
        request_payload = {
            "model": settings.model,
            "temperature": 0,
            "max_tokens": 240,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
        }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.api_key}",
    }
    if settings.user_agent is not None:
        headers["User-Agent"] = settings.user_agent
    request = Request(
        settings.url,
        data=canonical_json(request_payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with opener(request, timeout=settings.timeout_seconds) as response:
            data = response.read(32_769)
            if len(data) > 32_768:
                raise ValueError("LLM response exceeds maximum size")
    except HTTPError as error:
        # Expose ONLY numeric HTTP status, never headers/body/URL/exception reason.
        status = error.code if isinstance(error.code, int) and 100 <= error.code <= 599 else 0
        raise ValueError(f"LLM_PROVIDER_HTTP_{status}; no forecast accepted") from None
    except TimeoutError:
        raise ValueError("LLM_PROVIDER_TIMEOUT; no forecast accepted") from None
    except (URLError, OSError):
        raise ValueError("LLM_PROVIDER_NETWORK_ERROR; no forecast accepted") from None

    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("LLM returned invalid JSON") from None

    message = _response_text(payload, api_style=settings.api_style)
    try:
        forecast_payload = json.loads(message)
    except json.JSONDecodeError:
        raise ValueError("LLM assistant text is not a JSON forecast") from None
    return ShadowForecast.from_payload(forecast_payload)
