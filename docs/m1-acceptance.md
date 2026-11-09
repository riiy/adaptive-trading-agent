# M1 operational acceptance — Ubuntu 24.04

M1 is **not complete** merely because Binance downloads return successfully. The local database must pass the checks below, and the systemd timer must be confirmed to run.

## 1. Read-only data quality gate

Run on the actual server, under the `ata` system user:

```bash
sudo -u ata /opt/ata/venv/bin/ata market verify \
  --db /var/lib/ata/market.sqlite3 \
  --min-history-days 350 \
  --max-lag-bars 2
```

The command checks all six configured streams (BTCUSDT and ETHUSDT, each at 15m, 1h and 4h) and returns a JSON report.

- Exit 0 / `PASS`: database integrity and all six series pass the checks.
- Exit 1 / `FAIL`: a data-quality condition failed.
- Exit 2: an operational error occurred (such as database unavailable).

The validator opens SQLite in read-only mode. It never creates or modifies the database, fetches new data, adjusts positions, or creates order tickets.

The default history threshold of 350 days permits a modest margin around the intended 365-day backfill. This is an **engineering readiness** threshold, not evidence that a strategy is profitable.

### Quality checks

- All six expected symbol/interval series have rows.
- Each has at least 350 days between the first and last stored candles.
- There are no missing time intervals within each series.
- Latest completed candle is no more than two bars behind what local UTC clock implies.
- No future/currently-open candles are stored.
- SQLite quick integrity check, schema version and ingestion provenance foreign keys pass.

The check relies on the server clock. Keep it synchronized (normally via Ubuntu's time synchronization service). A future update may add exchange-time drift checks.

## 2. Confirm the timer

```bash
systemctl is-enabled ata-market-sync.timer
systemctl is-active ata-market-sync.timer
systemctl list-timers ata-market-sync.timer
sudo journalctl -u ata-market-sync.service --since "1 hour ago" --no-pager
```

Confirm the timer is enabled and active, and that the service has successfully run multiple times without repeated errors. A one-time manual sync does not prove ongoing reliability.

## 3. Idempotence

Idempotence is covered by unit tests. For an additional server-level smoke test, execute the same synchronization twice close together. The second run should usually report zero inserted rows unless a new candle closes between runs. Compare the affected period and the returned row counts rather than assuming clock time is frozen.

## 4. Acceptance record

Save a copy of the JSON verification output and timer/journal status outside the public repository (for example in a private operational notes location). The public `STATE.md` should record the **pass/fail conclusion and date**, not account keys, server secrets, personal information, or internal access details.

### Stop rule

If verification fails, do not proceed to M2 research using that dataset. Diagnose only the failed series/condition and rerun the gate after a minimal repair. Do not reopen broad raw/qfq-style infrastructure work unrelated to a research decision.
