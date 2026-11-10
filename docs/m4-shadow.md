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

### Investigate an LLM provider failure (no forecast backfill)

On 2026-11-10 00:15 UTC, the first scheduled observer started but exited after
`LLM provider request failed`. In the current implementation, the baseline is
written **before** the optional LLM call. A nonzero service exit does not
necessarily mean the baseline forecast is missing. `ata shadow score`
reports **settled feedback only**, not the count of pending forecasts.

To inspect the existing records (only safe metadata, no API keys or raw responses):

```bash
sudo -u ata /opt/ata/venv/bin/python - <<'PY'
import sqlite3

db = sqlite3.connect("file:/var/lib/ata/shadow.sqlite3?mode=ro", uri=True)
for day_ms, source, created_ms, model in db.execute(
    "SELECT day_ms, source, created_ms, model_id "
    "FROM shadow_forecasts ORDER BY day_ms, source"
):
    print(day_ms, source, created_ms, model)
db.close()
PY
```

The LLM client deliberately suppresses remote error bodies/headers/URLs because
they may contain API tokens. New diagnostics show **only** a safe numeric HTTP
status (e.g. `LLM_PROVIDER_HTTP_401`, `HTTP_404`, `HTTP_429`) or the
`LLM_PROVIDER_NETWORK_ERROR` / `LLM_PROVIDER_TIMEOUT` categories.

After this PR has merged and the Ubuntu installation is updated, use the
following **separate, non-mutating provider probe**. It makes **one paid API
request**, loads `/etc/ata/shadow.env` through systemd as the real
`ata` user, and does **not** create a forecast or affect SQLite:

```bash
sudo systemd-run --unit=ata-llm-probe --wait --pipe --collect \
  --uid=ata \
  --property=EnvironmentFile=/etc/ata/shadow.env \
  /opt/ata/venv/bin/ata shadow probe-llm
```

Do not paste the environment file, bearer token, request body, HTTP response body,
or credentials into logs, shell commands or support messages.

Interpretation of sanitized errors:

| Result | First check |
|---|---|
| `LLM_PROVIDER_HTTP_400` | Provider/model compatibility; request parameter support (e.g. temperature, token limit) |
| `LLM_PROVIDER_HTTP_401` | API key / account authorization |
| `LLM_PROVIDER_HTTP_403` | Access policy, region, provider account/organization permissions |
| `LLM_PROVIDER_HTTP_404` | Base URL must be an API prefix such as `https://host/v1`, **not** the full `/chat/completions` endpoint; also check model ID |
| `LLM_PROVIDER_HTTP_429` | Rate limits, quota or billing restrictions |
| `LLM_PROVIDER_HTTP_5xx` | Provider-side transient outage |
| `LLM_PROVIDER_NETWORK_ERROR` | DNS, TLS, proxy, firewall, server egress |
| `LLM_PROVIDER_TIMEOUT` | Connection/response exceeded the bounded timeout |
| `LLM returned an invalid structured forecast` | Response format is incompatible with the strict Chat Completions schema |

The command prints only a sanitized success/error result. In particular,
`ATA_LLM_BASE_URL` must be the **base** URL: the adapter adds
`/chat/completions`. The active systemd service reads the root-owned
environment file; running `sudo -u ata ata ...` manually will **not**
automatically load the file.

If the first day's 00:05–00:45 UTC issue window has passed, **do not**
rerun `ata shadow observe` with a forged clock or backfill an LLM forecast.
Record a missing LLM observation. The next eligible day remains at 00:15 UTC.

### Responses-only providers (M4 protocol compatibility)

The first Ubuntu observation on **2026-11-10 00:15 UTC** preserved the
deterministic baseline but the LLM adapter's `/chat/completions` call returned
HTTP 403. The operator separately demonstrated that their provider and model
accept `POST /v1/responses` using the Responses `model` / `input` shape.
This indicates **API route compatibility is a strong suspect**, not that the
LLM key or account has been proved invalid.

The M4 LLM adapter now has an **explicit**, fail-closed choice:

- `ATA_LLM_API_STYLE=chat_completions` (default; original behavior)
- `ATA_LLM_API_STYLE=responses` (uses `/responses`, `input`, and parses
  the returned assistant `output_text` blocks)

In the root-owned server file `/etc/ata/shadow.env`, retain the valid existing
`ATA_LLM_BASE_URL`, `ATA_LLM_MODEL`, and `ATA_LLM_API_KEY`, then add:

```ini
ATA_LLM_API_STYLE=responses
```

The base URL should end in the API prefix (for this operator, `/v1`), not in
`/responses` or `/chat/completions`. The adapter constructs the endpoint.

After this PR is merged, update the installation, then run the existing
**non-mutating** provider probe via `systemd-run` as documented below.
The test sends a **synthetic, non-market** request and may consume tokens.
The observer and LLM adapter do not automatically retry or switch protocols:
a failed response leaves a real missing-forecast day for audit.

The Responses implementation uses strict JSON validation and does **not**
accept tool-call output, reasoning text, incomplete results, or extra forecast
fields as valid shadow forecasts. This is not evidence of investment quality.

### Provider-edge User-Agent compatibility (verified 2026-11-10)

On the operator's infrastructure, a minimal Python `urllib` request to
`/v1/responses` using the correct host, model, HTTPS route, and environment
returns HTTP 403 **without any Nginx access log**. A repeat with **only**
`User-Agent: curl/8.5.0` changed returns **HTTP 200** and reaches Nginx.
This supports client-header-dependent filtering **before the logged Nginx
access point**, not a proven LiteLLM API permission fault. The precise edge
component (CDN/WAF/reverse proxy/other filter) remains unknown.

For a short-term operator-approved compatibility workaround, the adapter accepts
a validated, **opt-in** User-Agent. In `/etc/ata/shadow.env`:

```ini
ATA_LLM_USER_AGENT=curl/8.5.0
```

The standard `urllib` behavior remains unchanged if this is not set. ASCII
control characters and overlong header values are rejected. The override is
applied to both `probe-llm` and the research-only daily observation; it
does not enable any trading APIs.

After merging/installing the PR, run **one** non-mutating provider probe using
the existing systemd command below. A successful probe confirms network/API
compatibility but **not** tomorrow's forecast creation or model accuracy.

Long-term, investigate the security events before Nginx and allow a distinct
ATA research-client identity using narrowly scoped origin/edge rules. Do **not**
globally disable bot protection or grant an unrestricted path bypass. The
`curl` User-Agent override is a compatibility measure, not a security fix.

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
