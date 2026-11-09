# M4 — Prospective research-and-feedback MVP

**Status:** Implementation / server acceptance pending.  
**Safety:** RESEARCH_ONLY; no account simulation, orders, tickets, strategy promotion, or trade credentials.

## Purpose and scope

M3-H001 is permanently archived after its predeclared failure. The 72-day historical
test remains sealed; do not use it for agent prompt engineering or backtest optimization.

M4 is a **different research capability**, not an H001 strategy revival:
record one *future-time* research forecast per day, read the realized next-24h outcome,
score the forecast versus static baselines, and keep a versioned hypothesis for review.
It does not create investable strategies and does not automatically revise prompts.

## Fixed prospective protocol

- First permissible day: **2026-11-10 00:00 UTC**. No historical backfilling.
- Daily decision timestamp T: 00:00 UTC.
- Observation executable window: T+05m through strictly before T+45m.
- Automated systemd observation: **00:15 UTC**.
- Context: only completed, aligned BTCUSDT/ETHUSDT 1h candles known before T,
  with prior 24h/7d momentum, 7d realized volatility and volume ratio.
- Actual forecast creation time and SHA-256 of the as-of context are saved.
- Strict choices: `BTCUSDT`, `ETHUSDT`, `USDT`, `ABSTAIN`.
- Probabilities: `p_btc_up` and `p_eth_up` for positive next-24h
  **close-to-close** returns. Arbitrary JSON and executable instructions are rejected.
- Each daily observation includes a deterministic baseline: always USDT, with
  fixed 0.5 direction probability for each asset.
- Optional research LLM is versioned `m4-shadow-v1` and uses **one** bounded
  HTTPS chat-completions call per day; no tool or order API is available.
- The market database is read-only for the shadow service; forecast and feedback
  are written only to `/var/lib/ata/shadow.sqlite3`.
- The uniqueness constraint (decision day, source) prevents duplicate records;
  feedback is separately appended exactly once.

## Future outcome / scoring

At or after T+24h, when both next-day hourly closes are available:

- BTC/ETH labels: `close(T+23h) / close(T-1h) - 1`.
- Probabilities: Brier score versus positive/nonpositive daily direction.
  Reference fixed p=0.5 Brier = 0.25.
- Choice: descriptive *gross future close-to-close return* versus same-day USDT,
  unconditional BTC and unconditional ETH.
- `ABSTAIN` is excluded from selected-return statistics; it is **not**
  silently counted as cash or a win.
- All results carry explicit non-executable/no-account status.

**Crucial:** the outcome starts at the T-1h closing price even though the actual
forecast is issued at T+15m. This is a **prediction-label convention, not an
achievable entry price**. The gross selected-return metric must never be called
a strategy backtest or account P&L.

The scorer displays preliminary statistics at any sample count, but labels fewer
than 30 prospective days `EXPLORATORY_ONLY` and fewer than 60
`MORE_PROSPECTIVE_EVIDENCE_REQUIRED`. Reaching 60 days means
`READY_FOR_SEPARATE_STATISTICAL_REVIEW`, **not** pass/trading permission.
A genuine statistical review should check block uncertainty, paired evidence
versus BTC/ETH/cash, model revisions, cost/exposure and worst-case outcomes.

## Low-cost Ubuntu installation (after PR merge)

Update the existing installation:

```bash
sudo ATA_GIT_REF=main bash /opt/ata/app/deploy/ubuntu24/install.sh
```

The installer copies the M4 units **but does not enable them**. Explicitly enable
both timers when ready:

```bash
sudo systemctl enable --now ata-shadow-observe.timer ata-shadow-settle.timer
systemctl list-timers 'ata-shadow*'
```

The observer records only the deterministic baseline unless explicitly opted
into LLM via a server-side environment file.

### Optional LLM activation

The adapter expects an OpenAI-compatible HTTPS **API base URL** ending in
`/v1`; it adds `/chat/completions`. Compatibility is provider-dependent and
must be smoke-tested. Never paste the token into a shell command, issue tracker,
GitHub repo or chat. Configure only on the server in a root-owned file
`/etc/ata/shadow.env` (mode 0600), for example:

```ini
ATA_SHADOW_ENABLE_LLM=1
ATA_LLM_BASE_URL=https://your-compatible-provider.example/v1
ATA_LLM_MODEL=your-model-id
ATA_LLM_API_KEY=PUT_REAL_SECRET_HERE_LOCALLY_ONLY
```

This is a template; **do not commit it or copy its real values into output**.
The service accesses the file using systemd's `EnvironmentFile`.
Do not activate LLM until connectivity and billing controls are checked.
Provider failure leaves the deterministic baseline intact; no fabricated LLM
forecast is recorded. An unsuccessful LLM call can still consume tokens.

### Check results

```bash
sudo -u ata /opt/ata/venv/bin/ata shadow score \
  --shadow-db /var/lib/ata/shadow.sqlite3
journalctl -u ata-shadow-observe.service -n 50 --no-pager
journalctl -u ata-shadow-settle.service -n 50 --no-pager
```

The timer at 00:15 UTC will not retrospectively fabricate a decision for a
missed day. To diagnose failed observations, check UTC time, last closed hourly
bars, permissions, and sanitized provider errors.

## M4 engineering acceptance

1. CI: strict forecast JSON validation; no backdating/future inputs; duplicate
   suppression; outcome not written before horizon; abstention semantics.
2. Real Ubuntu: one genuine future daily observation, the **same snapshot hash**
   for baseline and LLM (if enabled), then delayed settlement.
3. Next-day settle is appended once, score computed and market database untouched.
4. Model/provider outages fail closed; no trading permission changes.
5. Human review before any prompt version changes, strategy experiments or
   increased spending.

## Stop conditions

- If LLM adds no measurable prediction/research quality after a sufficient
  prospective sample versus the fixed baselines, disable its daily invocation
  rather than adding agents.
- If daily prospective observation/settlement is unreliable after targeted
  repair, pause M4 rather than engineering a distributed platform.
- H001 stays archived and its held-out history sealed.
