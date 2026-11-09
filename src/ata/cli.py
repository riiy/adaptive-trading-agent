"""ATA command-line interface."""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ata.domain import Action
from ata.marketdata.binance import BinanceAPIError, BinancePublicClient
from ata.marketdata.collector import MarketDataCollector
from ata.marketdata.models import (
    SUPPORTED_INTERVALS,
    SUPPORTED_SYMBOLS,
    MarketDataError,
)
from ata.marketdata.readiness import verify_m1
from ata.marketdata.storage import MarketDataRepository
from ata.research.baselines import research_snapshot
from ata.research.momentum_diagnostic import diagnose_h001
from ata.risk import RiskContext, RiskGovernor, RiskPolicy
from ata.shadow.engine import observe_once, settle_pending
from ata.shadow.scoring import shadow_score


def _utc_milliseconds(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    utc_value = parsed.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = utc_value - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


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
    sync.add_argument(
        "--db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")),
    )
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

    verify = market_commands.add_parser("verify", help="read-only M1 six-stream quality gate")
    verify.add_argument(
        "--db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")),
    )
    verify.add_argument("--min-history-days", type=int, default=350)
    verify.add_argument("--max-lag-bars", type=int, default=2)

    research = commands.add_parser("research", help="read-only research tools")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    snapshot = research_commands.add_parser(
        "snapshot", help="causal market features and passive benchmarks"
    )
    snapshot.add_argument(
        "--db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")),
    )
    snapshot.add_argument("--days", type=int, default=180)
    snapshot.add_argument("--asof", type=_utc_milliseconds)
    snapshot.add_argument("--fee-bps", type=Decimal, default=Decimal("10"))
    snapshot.add_argument("--slippage-bps", type=Decimal, default=Decimal("5"))

    m3 = research_commands.add_parser(
        "m3-h001", help="frozen, non-executable seven-day momentum diagnostic"
    )
    m3.add_argument(
        "--db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")),
    )

    shadow = commands.add_parser("shadow", help="prospective-only non-executable research")
    shadow_commands = shadow.add_subparsers(dest="shadow_command", required=True)

    observe = shadow_commands.add_parser("observe", help="record today's UTC decision window")
    observe.add_argument(
        "--market-db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")),
    )
    observe.add_argument(
        "--shadow-db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_SHADOW_DB_PATH", "data/shadow.sqlite3")),
    )
    observe.add_argument("--llm", action="store_true", help="opt in to one LLM call")

    settle = shadow_commands.add_parser("settle", help="append ready 24h feedback")
    settle.add_argument(
        "--market-db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_DB_PATH", "data/ata.sqlite3")),
    )
    settle.add_argument(
        "--shadow-db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_SHADOW_DB_PATH", "data/shadow.sqlite3")),
    )

    score = shadow_commands.add_parser("score", help="summarize prospective feedback")
    score.add_argument(
        "--shadow-db",
        type=_database_argument,
        default=Path(os.environ.get("ATA_SHADOW_DB_PATH", "data/shadow.sqlite3")),
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


def _verify(args: argparse.Namespace) -> int:
    report = verify_m1(
        args.db,
        now_ms=time.time_ns() // 1_000_000,
        min_history_days=args.min_history_days,
        max_lag_bars=args.max_lag_bars,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


def _research_snapshot(args: argparse.Namespace) -> int:
    now_ms = time.time_ns() // 1_000_000
    if args.asof is not None and args.asof > now_ms:
        raise ValueError("--asof cannot be in the future")
    report = research_snapshot(
        args.db,
        asof_time_ms=now_ms if args.asof is None else args.asof,
        benchmark_days=args.days,
        fee_bps_per_side=args.fee_bps,
        slippage_bps_per_side=args.slippage_bps,
        max_lag_bars=2 if args.asof is None else None,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


def _m3_h001(args: argparse.Namespace) -> int:
    report = diagnose_h001(args.db)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _shadow_observe(args: argparse.Namespace) -> int:
    enabled = args.llm or os.getenv("ATA_SHADOW_ENABLE_LLM") == "1"
    report = observe_once(args.market_db, args.shadow_db, enable_llm=enabled)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _shadow_settle(args: argparse.Namespace) -> int:
    report = settle_pending(args.market_db, args.shadow_db)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _shadow_score(args: argparse.Namespace) -> int:
    report = shadow_score(args.shadow_db)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


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
        if args.command == "market" and args.market_command == "verify":
            return _verify(args)
        if args.command == "research" and args.research_command == "snapshot":
            return _research_snapshot(args)
        if args.command == "research" and args.research_command == "m3-h001":
            return _m3_h001(args)
        if args.command == "shadow" and args.shadow_command == "observe":
            return _shadow_observe(args)
        if args.command == "shadow" and args.shadow_command == "settle":
            return _shadow_settle(args)
        if args.command == "shadow" and args.shadow_command == "score":
            return _shadow_score(args)
        return _status()
    except (BinanceAPIError, MarketDataError, OSError, sqlite3.Error, ValueError) as error:
        print(f"ata: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
