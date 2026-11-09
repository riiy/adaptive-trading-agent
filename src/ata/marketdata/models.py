"""Validated Binance Spot kline domain model."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

SUPPORTED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})
INTERVAL_MS = {
    "1m": 60_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}
SUPPORTED_INTERVALS = frozenset(INTERVAL_MS)


class MarketDataError(ValueError):
    """Raised when public market data is malformed or inconsistent."""


class DataConflictError(MarketDataError):
    """Raised when a previously stored candle changes for the same primary key."""


def _integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise MarketDataError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as error:
            raise MarketDataError(f"{field_name} must be an integer") from error
    raise MarketDataError(f"{field_name} must be an integer")


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, float):
        raise MarketDataError(f"{field_name} must be provided as a decimal string")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise MarketDataError(f"{field_name} is not a valid decimal") from error
    if not result.is_finite():
        raise MarketDataError(f"{field_name} must be finite")
    return result


def decimal_text(value: Decimal) -> str:
    """Serialize decimals without binary-float conversion or exponent notation."""
    return format(value, "f")


@dataclass(frozen=True, slots=True)
class Kline:
    symbol: str
    interval: str
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time_ms: int
    quote_asset_volume: Decimal
    number_of_trades: int
    taker_buy_base_asset_volume: Decimal
    taker_buy_quote_asset_volume: Decimal

    def __post_init__(self) -> None:
        if self.symbol not in SUPPORTED_SYMBOLS:
            raise MarketDataError(f"unsupported symbol: {self.symbol}")
        if self.interval not in SUPPORTED_INTERVALS:
            raise MarketDataError(f"unsupported interval: {self.interval}")
        if (
            isinstance(self.open_time_ms, bool)
            or not isinstance(self.open_time_ms, int)
            or isinstance(self.close_time_ms, bool)
            or not isinstance(self.close_time_ms, int)
            or self.open_time_ms < 0
            or self.close_time_ms <= self.open_time_ms
        ):
            raise MarketDataError("kline timestamps are invalid")
        decimal_fields = (
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.quote_asset_volume,
            self.taker_buy_base_asset_volume,
            self.taker_buy_quote_asset_volume,
        )
        if any(not isinstance(value, Decimal) or not value.is_finite() for value in decimal_fields):
            raise MarketDataError("all price and volume fields must be finite decimals")
        if isinstance(self.number_of_trades, bool) or not isinstance(self.number_of_trades, int):
            raise MarketDataError("number_of_trades must be an integer")
        if self.open_time_ms % INTERVAL_MS[self.interval] != 0:
            raise MarketDataError("kline open time is not aligned to its UTC interval")
        if self.close_time_ms != self.open_time_ms + INTERVAL_MS[self.interval] - 1:
            raise MarketDataError("kline close time does not match its interval")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise MarketDataError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise MarketDataError("high is below another OHLC price")
        if self.low > min(self.open, self.close, self.high):
            raise MarketDataError("low is above another OHLC price")
        if (
            min(
                self.volume,
                self.quote_asset_volume,
                self.taker_buy_base_asset_volume,
                self.taker_buy_quote_asset_volume,
            )
            < 0
        ):
            raise MarketDataError("volume fields must be non-negative")
        if self.taker_buy_base_asset_volume > self.volume:
            raise MarketDataError("taker-buy base volume exceeds total base volume")
        if self.taker_buy_quote_asset_volume > self.quote_asset_volume:
            raise MarketDataError("taker-buy quote volume exceeds total quote volume")
        if self.number_of_trades < 0:
            raise MarketDataError("number_of_trades must be non-negative")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "open_time_ms": self.open_time_ms,
            "open": decimal_text(self.open),
            "high": decimal_text(self.high),
            "low": decimal_text(self.low),
            "close": decimal_text(self.close),
            "volume": decimal_text(self.volume),
            "close_time_ms": self.close_time_ms,
            "quote_asset_volume": decimal_text(self.quote_asset_volume),
            "number_of_trades": self.number_of_trades,
            "taker_buy_base_asset_volume": decimal_text(self.taker_buy_base_asset_volume),
            "taker_buy_quote_asset_volume": decimal_text(self.taker_buy_quote_asset_volume),
        }


def parse_klines(
    payload: Any,
    *,
    symbol: str,
    interval: str,
    server_time_ms: int,
) -> list[Kline]:
    """Parse Binance's positional kline payload and discard the unfinished candle."""
    if symbol not in SUPPORTED_SYMBOLS:
        raise MarketDataError(f"unsupported symbol: {symbol}")
    if interval not in SUPPORTED_INTERVALS:
        raise MarketDataError(f"unsupported interval: {interval}")
    if not isinstance(payload, list):
        raise MarketDataError("Binance kline response must be a list")

    parsed: list[Kline] = []
    for index, row in enumerate(payload):
        if not isinstance(row, list) or len(row) < 11:
            raise MarketDataError(f"kline row {index} has an invalid shape")
        try:
            open_time_ms = _integer(row[0], "open_time_ms")
            close_time_ms = _integer(row[6], "close_time_ms")
            candle = Kline(
                symbol=symbol,
                interval=interval,
                open_time_ms=open_time_ms,
                open=_decimal(row[1], "open"),
                high=_decimal(row[2], "high"),
                low=_decimal(row[3], "low"),
                close=_decimal(row[4], "close"),
                volume=_decimal(row[5], "volume"),
                close_time_ms=close_time_ms,
                quote_asset_volume=_decimal(row[7], "quote_asset_volume"),
                number_of_trades=_integer(row[8], "number_of_trades"),
                taker_buy_base_asset_volume=_decimal(row[9], "taker_buy_base_asset_volume"),
                taker_buy_quote_asset_volume=_decimal(row[10], "taker_buy_quote_asset_volume"),
            )
        except (TypeError, ValueError, OverflowError) as error:
            if isinstance(error, MarketDataError):
                raise
            raise MarketDataError(f"kline row {index} contains an invalid value") from error

        if candle.close_time_ms < server_time_ms:
            parsed.append(candle)

    previous_open_time: int | None = None
    for candle in parsed:
        if previous_open_time is not None and candle.open_time_ms <= previous_open_time:
            raise MarketDataError("kline rows must be strictly chronological and unique")
        previous_open_time = candle.open_time_ms

    return parsed
