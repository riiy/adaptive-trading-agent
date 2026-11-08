"""Unauthenticated Binance Spot REST client with bounded retry behavior."""

import json
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ata.marketdata.models import SUPPORTED_INTERVALS, SUPPORTED_SYMBOLS, MarketDataError


class BinanceAPIError(RuntimeError):
    """Raised for Binance HTTP, transport, or response errors."""


class BinanceRateLimitError(BinanceAPIError):
    """Raised when rate limits require the collector to stop."""


class BinancePublicClient:
    """Read-only client for Binance's market-data-only REST hostname."""

    def __init__(
        self,
        *,
        base_url: str = "https://data-api.binance.vision",
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        max_retry_after_seconds: float = 60.0,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0 or max_retries < 0 or max_retry_after_seconds < 0:
            raise ValueError("timeout and retry settings are invalid")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_retry_after_seconds = max_retry_after_seconds
        self._opener = opener or urlopen
        self._sleeper = sleeper

    def get_server_time(self) -> int:
        payload = self._get_json("/api/v3/time", {})
        if not isinstance(payload, dict) or not isinstance(payload.get("serverTime"), int):
            raise BinanceAPIError("Binance server-time response has an invalid shape")
        return payload["serverTime"]

    def get_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> list[list[Any]]:
        if symbol not in SUPPORTED_SYMBOLS:
            raise MarketDataError(f"unsupported symbol: {symbol}")
        if interval not in SUPPORTED_INTERVALS:
            raise MarketDataError(f"unsupported interval: {interval}")
        if start_time_ms < 0 or end_time_ms < start_time_ms:
            raise ValueError("start_time_ms/end_time_ms range is invalid")
        if not 1 <= limit <= 1000:
            raise ValueError("Binance kline limit must be between 1 and 1000")

        payload = self._get_json(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "limit": limit,
            },
        )
        if not isinstance(payload, list):
            raise BinanceAPIError("Binance kline response must be a list")
        return payload

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        query = urlencode(params)
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "AdaptiveTradingAgent/0.1",
            },
            method="GET",
        )

        for attempt in range(self.max_retries + 1):
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    status = getattr(response, "status", response.getcode())
                    body = response.read()
                if status != 200:
                    raise BinanceAPIError(f"unexpected Binance HTTP status: {status}")
                try:
                    return json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise BinanceAPIError("Binance returned invalid JSON") from error
            except HTTPError as error:
                if error.code == 418:
                    raise BinanceRateLimitError(
                        "Binance returned HTTP 418; stop requests until the ban expires"
                    ) from error
                if error.code == 429:
                    retry_after = self._retry_after(error)
                    if attempt >= self.max_retries:
                        raise BinanceRateLimitError(
                            "Binance HTTP 429 persisted after bounded retries"
                        ) from error
                    if retry_after > self.max_retry_after_seconds:
                        raise BinanceRateLimitError(
                            "Binance Retry-After exceeds the configured wait; retry manually later"
                        ) from error
                    self._sleeper(retry_after)
                    continue
                if 500 <= error.code < 600 and attempt < self.max_retries:
                    self._sleeper(min(2**attempt, 8))
                    continue
                detail = error.read(512).decode("utf-8", errors="replace")
                raise BinanceAPIError(
                    f"Binance HTTP {error.code}: {detail or error.reason}"
                ) from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt >= self.max_retries:
                    raise BinanceAPIError("Binance request failed after bounded retries") from error
                self._sleeper(min(2**attempt, 8))

        raise BinanceAPIError("Binance request exhausted retries")

    @staticmethod
    def _retry_after(error: HTTPError) -> float:
        value = error.headers.get("Retry-After") if error.headers else None
        if value is None:
            return 1.0
        try:
            return max(0.0, float(value))
        except ValueError:
            return 1.0
