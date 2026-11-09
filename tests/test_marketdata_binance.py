import io
import json
from urllib.error import HTTPError

import pytest

from ata.marketdata.binance import (
    BinanceAPIError,
    BinancePublicClient,
    BinanceRateLimitError,
)


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


def test_get_klines_uses_market_data_only_host_and_query_parameters() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse([])

    client = BinancePublicClient(opener=opener)
    result = client.get_klines(
        symbol="BTCUSDT",
        interval="1h",
        start_time_ms=1000,
        end_time_ms=2000,
        limit=100,
    )

    assert result == []
    assert captured["url"].startswith("https://data-api.binance.vision/api/v3/klines?")
    assert "symbol=BTCUSDT" in captured["url"]
    assert "interval=1h" in captured["url"]
    assert "startTime=1000" in captured["url"]
    assert "endTime=2000" in captured["url"]
    assert captured["timeout"] == 10.0


def test_http_429_honors_retry_after_then_retries() -> None:
    calls = []
    waits = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "0"},
                io.BytesIO(b"rate limited"),
            )
        return FakeResponse({"serverTime": 123})

    client = BinancePublicClient(opener=opener, sleeper=waits.append)
    assert client.get_server_time() == 123
    assert len(calls) == 2
    assert waits == [0.0]


def test_http_418_stops_without_retry() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 418, "IP banned", {}, io.BytesIO(b"banned"))

    client = BinancePublicClient(opener=opener, sleeper=lambda _delay: None)
    with pytest.raises(BinanceRateLimitError, match="HTTP 418"):
        client.get_server_time()
    assert len(calls) == 1


def test_http_429_with_long_retry_after_stops_without_sleeping() -> None:
    def opener(request, timeout):
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "120"},
            io.BytesIO(b"rate limited"),
        )

    waits = []
    client = BinancePublicClient(opener=opener, sleeper=waits.append)
    with pytest.raises(BinanceRateLimitError, match="Retry-After exceeds"):
        client.get_server_time()
    assert waits == []


def test_invalid_json_is_reported() -> None:
    class InvalidResponse(FakeResponse):
        def read(self, *_args):
            return b"not-json"

    client = BinancePublicClient(opener=lambda *_args, **_kwargs: InvalidResponse([]))
    with pytest.raises(BinanceAPIError, match="invalid JSON"):
        client.get_server_time()
