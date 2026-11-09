# Ubuntu 24.04 deployment

This deployment runs a small Python service under systemd. It uses Binance's public market-data REST endpoint and does not require an API key.

## Preconditions

- Ubuntu 24.04 LTS.
- Outbound HTTPS access to `data-api.binance.vision`.
- A GitHub account is not required to clone the public repository.
- Merge the M0 and M1 pull requests before deploying from `main`.

No inbound application port is opened. Do not change UFW rules blindly; preserve the SSH port actually used by the server.

## Install

From a clean server:

```bash
git clone https://github.com/riiy/adaptive-trading-agent.git
cd adaptive-trading-agent
sudo bash deploy/ubuntu24/install.sh
```

The installer uses `main` by default. To test a review branch intentionally, set `ATA_GIT_REF`:

```bash
sudo ATA_GIT_REF=feat/m1-market-data bash deploy/ubuntu24/install.sh
```

The installer creates a non-login `ata` system user, a Python 3.12 virtual environment, a root-owned application directory, a data directory at `/var/lib/ata`, and systemd service/timer units. It does not enable the timer automatically.

## Initial historical backfill

The first run downloads one year of completed 15m, 1h, and 4h candles for BTCUSDT and ETHUSDT:

```bash
sudo -u ata /opt/ata/venv/bin/ata market sync \
  --symbols BTCUSDT ETHUSDT \
  --intervals 15m 1h 4h \
  --lookback-days 365 \
  --db /var/lib/ata/market.sqlite3
```

For a longer research history, increase `--lookback-days` explicitly. The collector paginates requests and never treats the currently open candle as closed.

## Enable periodic synchronization

```bash
sudo systemctl enable --now ata-market-sync.timer
systemctl list-timers ata-market-sync.timer
```

The timer runs a small overlapping sync every five minutes. The overlap is intentional: it rechecks recent bars, while the SQLite primary key makes identical downloads idempotent.

## Inspect service and data

```bash
sudo systemctl start ata-market-sync.service
sudo systemctl status ata-market-sync.service
sudo journalctl -u ata-market-sync.service -n 100 --no-pager

sudo -u ata /opt/ata/venv/bin/ata market audit \
  --symbol BTCUSDT --interval 1h \
  --db /var/lib/ata/market.sqlite3
```

The audit reports missing time intervals. It does not invent candles or silently fill gaps.

## Operational notes

- SQLite stores decimal values as text, not binary floating-point numbers.
- Database writes are transactional and use WAL mode.
- Each non-empty inserted batch records source, server timestamp, row counts, and a SHA-256 payload hash.
- If the same candle key later arrives with different OHLCV content, ingestion fails with a data-conflict error instead of overwriting history.
- HTTP 429 honors a bounded `Retry-After`; HTTP 418 stops requests immediately.
- Logs go to journald. The service is restricted to writing under `/var/lib/ata`.
- This service only ingests public market data. It cannot access account endpoints or place orders.
- The 1m interval is deliberately deferred until a concrete strategy or execution-model requirement justifies its additional data volume.
