# Monstra.Pro Box — Architecture

Status: **V1 design, foundational scaffold in place, services not yet implemented.**

## 1. Purpose and design philosophy

Monstra.Pro Box is a dedicated Linux trading appliance. The customer buys the
hardware once, activates it at monstra.pro, and from then on **the device
executes trades locally, on hardware the customer owns**. Monstra servers
never execute trades on the customer's behalf and never see the customer's
Alpaca credentials.

Monstra.Pro Box is not a replacement for Monstra.bot. Monstra.bot stays the
strategy-creation / backtesting / research / community / subscription
product. The Pro Box is local execution, privacy, and always-on automation on
dedicated hardware, with a physical status display. Both products share the
same strategy engine wherever possible.

Design priorities, in order: **simplicity, reliability, recoverability,
local-first execution, minimal dependencies, clear modular boundaries.**
Enterprise scale is explicitly out of scope — each box has exactly one owner.

Hardware target: Raspberry Pi 5 (2GB/4GB) for V1 development, but no service
may depend on Pi-specific APIs directly. Anything hardware-specific (the
display renderer's framebuffer/DRM access) sits behind an interface so the
same code can later run on an Intel mini PC, a Compute Module, or in Docker.

## 2. What's reused from the existing Monstra codebase

Investigated before designing this, since the brief calls for sharing the
strategy engine with Monstra.bot:

| Existing code | Reused? | Why |
|---|---|---|
| `Monstra-Worker/bots/*.py` (`run_alpha1`, `run_alpha2`, ...) | **Yes, ported** | Already near-pure functions: `run_<bot>(config, state=None) -> signal dict`, depending only on price data + config. This *is* the strategy engine. |
| `Monstra-Worker/algorithm_registry.py` | **Yes, pattern ported** | Clean slug → metadata → lazy-runner registry. Reused as-is in `strategy_engine/registry.py`. |
| `Monstra-Worker/market_data_provider.py` | **Yes, ported** | Alpaca-primary / yfinance-fallback bar fetching, already provider-agnostic. |
| `Monstra-Worker/worker.py`, `db.py` | **No** | Tightly coupled to Postgres `trading.*` schema, Next.js internal webhooks, leaderboard snapshots, push notifications — all multi-tenant SaaS concerns that don't exist on a single-owner appliance. The Pro Box `trading_worker` service is a new, much smaller orchestrator. |
| `NextJS_Monsta` Alpaca rebalance/connection modules (TypeScript) | **Reference only** | Confirms the "diff target allocation vs current holdings, submit orders" logic Alpaca-side; reimplemented in Python for the device, not reused directly (different runtime). |

Porting the actual bot files (copying `bots/alpha1.py` etc. into
`strategy_engine/bots/`) is deliberately **not done in this pass** — that's
the first "foundational service" to implement next, not part of the
architecture scaffold. `strategy_engine/bots/` currently contains a
placeholder explaining what goes there.

Until there's a proper shared package, keep syncing strategy code the same
way `MonstraBackfill` already does with `Monstra-Worker` (manual copy after
changes) — documented in `strategy_engine/README` intent, not automated, for
V1.

## 3. Repository layout

```
monstraPro/
  ARCHITECTURE.md            # this file
  README.md
  .gitignore
  .env.example
  packages/
    strategy_engine/         # portable trading logic — shareable with Monstra.bot
      src/strategy_engine/
        registry.py           # algorithm registry (slug -> AlgorithmEntry)
        bot_identity.py        # bot id / bot-type constants and helpers
        signals.py             # Signal dataclass, shared shape worker <-> engine
        market_data/provider.py
        bots/                  # one module per strategy, ported from Monstra-Worker
    device_core/              # shared appliance infrastructure, not trading-specific
      src/device_core/
        config.py              # layered config loader
        crypto.py               # secret encryption at rest
        logging.py              # structured logging
        events.py               # local pub/sub (device_event table)
        db/
          engine.py              # SQLAlchemy engine factory (sqlite -> postgres later)
          models.py               # table definitions = the schema
          migrations/             # Alembic
  services/
    trading_worker/           # scheduler, activation state machine, order execution
    display/                  # native renderer + idle/wake/trade/error state machine
    updater/                  # release check/download/verify/apply
  deploy/
    systemd/                  # unit + timer files for the three services
```

Each package/service is independently installable (`requirements.txt` +
`src/` layout), matching the plain `venv` + `pip` convention already used by
`Monstra-Worker` and `MonstraBackfill` — no new build tooling (poetry/uv)
introduced for this project.

`strategy_engine` and `device_core` are libraries with no `main.py`; the
three entries under `services/` are the things systemd actually runs.

## 4. Services

### 4.1 `trading_worker`

The core service. Responsibilities:

- Owns the **activation state machine**. On startup, checks
  `device.activated_at` in the local DB.
  - **Not activated:** polls a monstra.pro device-status endpoint on an
    interval, publishes an `awaiting_activation` `device_event` for the
    display to render. Does not run any strategy or touch Alpaca.
  - **Activated:** pulls the owner's strategy configuration and Alpaca link
    (established during the monstra.pro activation flow), then enters
    trading mode.
- In trading mode, runs a scheduling loop (a much simpler descendant of
  `Monstra-Worker/worker.py`'s `main_loop`, stripped of every multi-tenant
  concern):
  1. Fetch market data for the owner's configured symbols via
     `strategy_engine.market_data.provider`.
  2. Run the owner's strategy function(s) through the registry to get a
     signal (target weights).
  3. Diff target weights vs. current Alpaca positions to compute an order
     plan (Python port of the logic in
     `NextJS_Monsta/src/lib/server/portfolioAutomationRebalanceExecution.ts`).
  4. Submit orders directly to Alpaca's Trading API.
  5. Persist `signal`, `order`, and `execution_log` rows locally.
  6. Emit a `trade_executed` `device_event` when an order is placed.
- No inbound network surface. It only makes outbound calls (monstra.pro,
  Alpaca).

There is deliberately **no separate provisioning/activation daemon** —
folding that into `trading_worker`'s startup state avoids a fourth
always-on process for a concern that's only active before the owner finishes
activation.

### 4.2 `display`

Drives the always-on physical display. Responsibilities:

- Native Python renderer targeting the framebuffer/DRM directly (e.g.
  pygame in KMSDRM mode) — no browser, no window manager. Chosen over a
  Chromium kiosk to keep boot time and RAM/CPU footprint low on a 2GB Pi 5,
  and because it's one fewer moving part to update and secure.
- A small state machine drives what's on screen:
  - `idle` (default): connection status, portfolio value, today's P/L,
    market open/closed, last sync time.
  - `awaiting_activation`: "activate this device at monstra.pro" + the
    device's activation/pairing code.
  - `trade_wake`: on a `trade_executed` event, wakes the screen, plays an
    animated notification, rotates through recently executed trades, shows
    allocation + recent activity, then returns to `idle` after ~30 minutes
    of no new trades.
  - `connection_error`: Wi-Fi disconnected / Alpaca disconnected / update
    available — rendered as a persistent, clearly visible banner over
    whatever state is active, not a state of its own.
- Reads state purely from `device_core.events` (subscribing to
  `device_event` rows) and periodic local connectivity/health checks. It has
  **no direct dependency on `trading_worker` internals** — the two only
  communicate through the DB-backed event log. This keeps the display
  replaceable per hardware target without touching trading logic, and keeps
  the worker running even if the display crashes.

### 4.3 `updater`

Handles the update mechanism, triggered by a systemd timer (hourly for V1)
rather than running continuously:

1. Request the current release manifest from monstra.pro (device-token
   authenticated), which includes strategy definitions and/or software
   version updates.
2. Compare against the installed version (`software_release` table).
3. If newer: download the signed release artifact, verify its signature
   against a public key baked into the base image, and extract it into
   `releases/<version>/` (never overwrite the running release in place).
4. Atomically repoint a `current` symlink at the new release directory, run
   any pending DB migration, and restart `trading_worker` + `display` via
   `systemctl restart` — the actual "apply" step is a process restart, not
   in-process hot-reload.
5. After restart, wait for a health grace period; if `trading_worker`
   doesn't report healthy in time, flip the `current` symlink back to the
   previous release and restart again. Keep the last 3 releases on disk for
   rollback; prune older ones after a successful, stable update.

This is an application-level updater (versioned release directories + a
symlink), not a full OS image A/B scheme — appropriate for V1's "prove the
concept" scope, and simple enough to reason about and recover from by hand
if it ever gets stuck. Full image-level A/B updates are a plausible future
upgrade if reliability data ever calls for it, not a V1 requirement.

## 5. Startup process

```
boot
 └─ systemd
     ├─ network-online.target
     ├─ monstrapro-worker.service   (After=network-online.target)
     ├─ monstrapro-display.service  (independent of worker; starts in parallel)
     └─ monstrapro-updater.timer    (OnUnitActiveSec=1h, first run OnBootSec=5min)

trading_worker startup:
  load device_core.config
   -> open SQLite, run pending Alembic migrations
   -> read device.activated_at
      -> unset: poll monstra.pro device-status -> emit awaiting_activation -> repeat
      -> set:   pull strategy_config + Alpaca link -> enter trading loop

display startup:
  init renderer (framebuffer/DRM)
   -> render idle/awaiting_activation screen (whichever device_event log says)
   -> subscribe to device_event, drive state machine
```

Both `trading_worker` and `display` are `Restart=on-failure` systemd
services, so a crash self-heals without operator intervention — this is the
"recoverability" principle in practice.

## 6. Configuration model

Layered, evaluated in this order (later layers override earlier ones):

1. **Code defaults** — safe fallback values compiled into `device_core.config`.
2. **`/etc/monstrapro/config.toml`** — device-level, non-secret settings:
   data directory paths, log level, poll intervals, the monstra.pro base URL.
   Safe to ship a template of this file in the disk image / commit to git.
3. **SQLite `device`/`settings` rows** — anything mutable at runtime or
   pushed down from monstra.pro: activation state, strategy configuration,
   feature flags.
4. **Environment variables** — dev-only overrides (e.g. pointing at a local
   monstra.pro dev server); not how secrets reach the device in production.

**Secrets never live in the TOML file.** Alpaca API key/secret are written
only to the `alpaca_credentials` table, encrypted at rest (see §8).

## 7. Database schema (SQLite for V1, Postgres-portable later)

Defined via SQLAlchemy Core table objects in `device_core/db/models.py` and
managed with Alembic migrations, specifically so that migrating the storage
backend to Postgres later is a dialect/connection-string change, not a
rewrite. V1 tables:

| Table | Purpose |
|---|---|
| `device` | Device identity: serial, activation state, owner reference, disclosures-accepted timestamp, installed software version. |
| `alpaca_credentials` | Encrypted API key/secret, base URL, paper/live mode, connected-at timestamp. |
| `strategy_config` | Bot slug, display name, strategy params, target allocation, active flag, source (monstra.pro vs local). |
| `portfolio_allocation` | Historical target vs. current weights per bot, timestamped. |
| `signal` | Signal history per bot — same shape as `Monstra-Worker`'s `trading.<bot>` signal rows, so engine output stays familiar. |
| `order` | Every order submitted to Alpaca: id, symbol, side, qty/notional, status, timestamps, raw response. |
| `execution_log` | Structured application log persisted for support/debugging, independent of journald retention. |
| `market_data_cache` | Cached OHLCV bars, pruned on a rolling window, so the device isn't fully dependent on live connectivity for every cycle. |
| `software_release` | Installed/staged release versions and their status (staged/active/rolled_back), used by the updater. |
| `device_event` | Append-only local event log (`trade_executed`, `awaiting_activation`, `connectivity_changed`, `update_available`, ...) — the pub/sub channel `display` tails. |

Only table *names and purpose* are locked in by this scaffold; full column
definitions land when `device_core.db` is implemented as a foundational
service.

## 8. Security notes

- Alpaca credentials are encrypted at rest with a device-local symmetric key
  (Fernet/AES-GCM), generated at first boot and stored with restrictive file
  permissions outside the SQLite file itself — so a copy of the DB file
  alone isn't enough to recover credentials. A hardware-backed secure
  element is a reasonable future upgrade, not required for V1.
- Device → monstra.pro calls are authenticated with a per-device token
  issued during activation, not the activation code itself (the activation
  code is single-use, to bind a device serial to a customer account).
- Release artifacts are signature-verified before being applied; the
  updater refuses to extract/activate an unsigned or badly-signed release.

## 9. API boundaries

- **Device → monstra.pro** (outbound HTTPS, device-token auth): activation
  status, strategy configuration pull, signed release manifests/artifacts.
  No trade data leaves the device in V1.
- **Device → Alpaca** (outbound HTTPS, owner's credentials, decrypted only
  in-memory): market data and order submission, direct from the device.
  Never proxied through Monstra servers — this is the core design
  philosophy, not just an implementation detail.
- **`trading_worker` ↔ `display`**: local-only, via the `device_event` table
  in SQLite (polled). No sockets or HTTP between them in V1; a Unix domain
  socket is a documented future optimization if polling latency ever
  matters.
- **`updater` ↔ `trading_worker`/`display`**: via `systemctl restart`, not
  an in-process call — keeps the update mechanism decoupled from whatever
  state the running services are in.
- **No local HTTP API in V1.** The product vision is explicit that
  configuration happens entirely through monstra.pro; there's no on-device
  configuration surface to expose yet.

## 10. What's explicitly deferred (not V1)

- Porting the actual bot strategy files into `strategy_engine/bots/`.
- A real `StrategyEngine` protocol/interface in `device_core` (today the
  registry pattern from `algorithm_registry.py` is the plan, not yet coded).
- Full OS image A/B updates (application-level release-directory updates are
  the V1 mechanism).
- Any on-device configuration UI or local HTTP API.
- Multi-strategy portfolio blending beyond what a single owner's configured
  bot(s) produce.
- Optional anonymized telemetry back to Monstra (the API boundary is left
  open for this, but nothing sends yet).
