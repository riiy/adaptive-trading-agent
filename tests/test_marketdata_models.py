from ata.marketdata.models import INTERVAL_MS, MarketDataError, parse_klines


def raw_kline(open_time_ms: int, interval: str = "1m") -> list[object]:
    return [
        open_time_ms,
        "100.00000001",
        "102.0",
        "99.0",
        "101.0",
        "10.25",
        open_time_ms + INTERVAL_MS[interval] - 1,
        "1025.0",
        5,
        "4.0",
        "400.0",
        "0",
    ]


def test_parse_klines_preserves_decimal_precision_and_order() -> None:
    rows = [raw_kline(0), raw_kline(60_000)]
    parsed = parse_klines(
        rows,
        symbol="BTCUSDT",
        interval="1m",
        server_time_ms=120_000,
    )

    assert len(parsed) == 2
    assert str(parsed[0].open) == "100.00000001"
    assert parsed[1].open_time_ms == 60_000


def test_parse_klines_discards_unfinished_candle() -> None:
    rows = [raw_kline(0), raw_kline(60_000)]
    parsed = parse_klines(
        rows,
        symbol="BTCUSDT",
        interval="1m",
        server_time_ms=90_000,
    )

    assert [item.open_time_ms for item in parsed] == [0]


def test_parse_klines_rejects_bad_ohlc() -> None:
    row = raw_kline(0)
    row[2] = "98.0"

    try:
        parse_klines([row], symbol="BTCUSDT", interval="1m", server_time_ms=60_000)
    except MarketDataError as error:
        assert "high" in str(error)
    else:
        raise AssertionError("invalid OHLC must be rejected")


def test_parse_klines_rejects_duplicate_or_out_of_order_rows() -> None:
    rows = [raw_kline(60_000), raw_kline(0)]
    try:
        parse_klines(rows, symbol="BTCUSDT", interval="1m", server_time_ms=120_000)
    except MarketDataError as error:
        assert "chronological" in str(error)
    else:
        raise AssertionError("out-of-order rows must be rejected")


def test_parse_klines_rejects_unsupported_symbol() -> None:
    try:
        parse_klines([], symbol="SOLUSDT", interval="1m", server_time_ms=1)
    except MarketDataError as error:
        assert "unsupported symbol" in str(error)
    else:
        raise AssertionError("unsupported symbol must be rejected")
