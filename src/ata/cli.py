"""ATA command-line interface."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from ata.domain import Action
from ata.marketdata.binance import BinanceAPIError, BinancePublicClient
from ata.marketdata.collector import MarketDataCollector
from ata.marketdata.models import (
    SUPPORTED_INTERVALS,
    SUPPORTED_SYMBOLS,
    MarketDataError,
)
from ata.marketdata.storage import MarketDataRepository
from ata.risk import RiskContext, RiskGovernor, RiskPolicy


def _utc_milliseconds(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _database_argument(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ata", description="Adaptive Trading Agent")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("status", help="show system permission status")
    market = commands.add_parser("market", help="market-data operations")
    market_commands = market.add_subparsers(dest="market_command", required=True)

    sync = market_commands.add_parser("sync", help="sync closed Binance Spot candles")
    sync.add_argument(
        "--symbols",
        nargs="+",
        choices=sorted(SUPPORTED_SYMBOLS),
        default=["BTCUSDT", "ETHUSDT"],
    )
    sync.add_argument(
        "--intervals",
        nargs="+",
        choices=sorted(SUPPORTED_INTERVALS),
        default=["15m", "1h", "4h"],
    )
    sync.add_argument("--lookback-days", type=int, default=3)
    sync.add_argument("--overlap-bars", type=int, default=3)
    sync.add_argument("--start", type=_utc_milliseconds)
    sync.add_argument("--end", type=_utc_milliseconds)
    sync.add_argument("--db", type=_database_argument, default=Path(
        os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")
    ))
    sync.add_argument(
        "--base-url",
        default=os.environ.get("ATA_BINANCE_BASE_URL", "https://data-api.binance.vision"),
    )

    audit = market_commands.add_parser("audit", help="audit stored candle continuity")
    audit.add_argument("--symbol", choices=sorted(SUPPORTED_SYMBOLS), required=True)
    audit.add_argument("--interval", choices=sorted(SUPPORTED_INTERVALS), required=True)
    audit.add_argument(
        "--db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")),
    )

    return parser


def _status() -> int:
    result = RiskGovernor(RiskPolicy()).authorize(
        Action.BUY_BTC,
        "BTCUSDT",
        RiskContext(data_healthy=True),
    )
    print("Adaptive Trading Agent")
    print("mode=RESEARCH_ONLY")
    print("trading_allowed=false")
    print("account_simulation_allowed=false")
    print("ticket_generation_allowed=false")
    print(f"sample_buy_authorized={str(result.allowed).lower()}")
    print(f"sample_buy_reason={result.code.value}")
    return 0


def _sync(args: argparse.Namespace) -> int:
    if args.lookback_days < 1 or args.overlap_bars < 0:
        raise ValueError("lookback-days must be positive and overlap-bars non-negative")
    if args.start is not None and args.end is not None and args.end < args.start:
        raise ValueError("--end must be later than or equal to --start")

    client = BinancePublicClient(base_url=args.base_url)
    repository = MarketDataRepository(args.db)
    collector = MarketDataCollector(client, repository)
    server_time_ms = client.get_server_time()
    results = []

    for symbol in args.symbols:
        for interval in args.intervals:
            result = collector.sync(
                symbol=symbol,
                interval=interval,
                server_time_ms=server_time_ms,
                lookback_days=args.lookback_days,
                overlap_bars=args.overlap_bars,
                start_time_ms=args.start,
                end_time_ms=args.end,
            )
            results.append(result.to_dict())

    print(json.dumps({"status": "ok", "results": results}, indent=2, sort_keys=True))
    return 0


def _audit(args: argparse.Namespace) -> int:
    repository = MarketDataRepository(args.db)
    report = repository.audit(args.symbol, args.interval)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.missing_intervals == 0 else 1


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        arguments = ["status"]
    parser = build_parser()
    args = parser.parse_args(arguments)

    try:
        if args.command == "market" and args.market_command == "sync":
            return _sync(args)
        if args.command == "market" and args.market_command == "audit":
            return _audit(args)
        return _status()
    except (BinanceAPIError, MarketDataError, OSError, sqlite3.Error, ValueError) as error:
        print(f"ata: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
