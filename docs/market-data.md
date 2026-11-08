# Market data contract — M1

## Source and scope

- Venue: Binance Spot.
- REST base URL: `https://data-api.binance.vision`.
- Endpoints: `GET /api/v3/time` and `GET /api/v3/klines`.
- Authentication: none; no API key is sent.
- Symbols: BTCUSDT and ETHUSDT.
- Collected intervals: 15m, 1h, and 4h.
- Deferred interval: 1m, until a concrete research or execution-model need justifies the extra volume.

The public market-data hostname is intentionally used instead of an authenticated account/trading hostname. Binance documents chronological kline results, millisecond timestamps, a maximum kline limit of 1,000, and IP-based rate limiting. HTTP 429 requires backoff; repeated violations can lead to HTTP 418 bans.

## Candle acceptance

A row is accepted only if:

1. The response row has the expected Binance kline fields.
2. The symbol and interval are in the configured allowlist.
3. The open time is aligned to the UTC interval.
4. The close time equals open time plus interval duration minus one millisecond.
5. OHLC prices are positive and satisfy high/low constraints.
6. Volumes are finite and non-negative; taker-buy volumes do not exceed totals.
7. The candle is closed according to Binance server time.
8. Rows are strictly chronological and unique within the page.

Open candles are discarded. Decimal values remain decimal strings in SQLite; no binary float conversion is used.

## Pagination and recovery

- REST requests use a maximum page size of 1,000.
- The next page begins at the previous page's last open time plus one millisecond.
- Incremental runs overlap the latest three bars to recheck recent data.
- Existing identical candles are ignored.
- A different payload for an existing `(venue, symbol, interval, open_time_ms)` key raises a data-conflict error. Historical rows are not silently overwritten.
- HTTP 429 honors a bounded `Retry-After`; if the wait exceeds the configured limit, the run stops for manual retry.
- HTTP 418 stops immediately. The client does not retry through an IP ban.

## SQLite contract

The database uses:

- WAL journal mode.
- Full synchronous writes.
- A composite primary key on venue, symbol, interval, and open time.
- Exact decimal text fields.
- Transactional batch inserts.
- An ingestion-run table with server timestamp, row counts, SHA-256 payload hash, and source metadata.

A repeated download with no new candles does not create a redundant ingestion-run record.

## Data-quality audit

The audit reports row count, first/last open times, and missing interval counts. Gaps are reported, not filled with synthetic candles. A gap must be investigated against the source and the strategy's required sampling before research uses that series.

## Current non-goals

- No WebSocket stream yet.
- No account, balance, order, or user-data endpoint.
- No LLM in the ingestion path.
- No signal generation, backtest, paper broker, or live execution.

## Official references

- [Binance Spot market-data-only URLs](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)
- [Binance Spot REST API — kline/candlestick data and rate limits](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#klinecandlestick-data)
