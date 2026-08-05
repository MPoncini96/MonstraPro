# Monstra.Pro Box — Architecture

Status: **V1 design implemented and tested (see SESSION_SUMMARY.txt). The
`image/` directory now provides the Raspberry Pi OS Lite boot foundation -
systemd units, first-boot bootstrap, and the `device_agent` Wi-Fi onboarding
service - but no real bootable image has been built or flashed yet; see
image/README.md "What remains".**

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
    device_agent/             # first-boot Wi-Fi onboarding (temporary AP + local setup page)
    trading_worker/           # scheduler, activation state machine, order execution
    display/                  # native renderer + idle/wake/trade/error state machine
    updater/                  # release check/download/verify/apply
  image/
    config/                   # /etc/monstrapro/config.toml template, dnsmasq override, image spec
    systemd/                  # unit + timer files for all four services + first-boot bootstrap
    scripts/                  # install.sh (provisioning) + first-boot.sh (idempotent bootstrap)
    tests/                    # static validation of the above
```

`deploy/systemd/` (the earlier three-service placeholder scaffold) has been
removed - `image/systemd/` supersedes it. See image/README.md for the full
picture: boot order, first-boot state flow, and how these pieces will later
be installed/tested on real Raspberry Pi 5 hardware.

Each package/service is independently installable (`requirements.txt` +
`src/` layout), matching the plain `venv` + `pip` convention already used by
`Monstra-Worker` and `MonstraBackfill` — no new build tooling (poetry/uv)
introduced for this project.

`strategy_engine` and `device_core` are libraries with no `main.py`; the
three entries under `services/` are the things systemd actually runs.

## 4. Services

### 4.1 `device_agent`

First-boot Wi-Fi onboarding, and the reason there are four services instead
of the three originally scoped here. Responsibilities (image/README.md has
the full first-boot state flow):

- On startup, checks whether a usable saved Wi-Fi connection already exists
  (`ConnectivityChecker`). If so: no-op, exits/idles - this is the normal
  case on every boot after the first.
- If not: starts a temporary access point named `MonstraPro-XXXX`, where
  `XXXX` is derived from (a hash of, not literally) the device's serial, and
  publishes a `wifi_onboarding_started` device_event so `display` shows
  "Connect your phone to MonstraPro-XXXX / Then visit setup.monstra".
- Hosts a minimal local HTTP page (stdlib `http.server`, no framework) at
  that address, listing nearby networks and accepting a submitted
  ssid+password.
- Saves the connection via NetworkManager and shuts down the temporary
  access point, then publishes `wifi_connected`.

Deliberately knows nothing about device activation or pairing codes -
`trading_worker`'s own `awaiting_activation` polling (4.2) is what actually
drives the display to "device registration and pairing-code status" once
the device is online; `device_agent`'s only job is getting it online. All
NetworkManager/access-point/HTTP-server I/O sits behind injectable
interfaces (`services/device_agent/src/device_agent/network.py`) so the
whole flow is unit-testable without touching a real network stack - a
`SimulatedNetworkManager` stands in for local development and CI.

The customer's Wi-Fi password follows the same rule as Alpaca credentials
(section 8) and local trading commands (section 9): it reaches this
device's own NetworkManager and nothing else. It is never logged, never
written to disk by this service, and never sent to any Monstra server.

### 4.2 `trading_worker`

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
- Before each cycle, reconciles `manual_holding` rows (individual stocks
  the owner locked via `portfolio_web`, 4.5): buys up to each holding's
  `target_qty` if under-held, never sells. Every bot's own rebalance math
  then excludes every locked symbol entirely - dropped from the bot's
  target weights (renormalized), from what it sees as its current
  holdings, and its value subtracted from the equity the bot may allocate
  against. Without this a locked position with no bot target weight looks,
  to the diff math alone, exactly like a position that should be fully
  sold - see `services/trading_worker/src/trading_worker/loop.py`'s module
  docstring and `manual_holdings.py`.
- Independent of that (slower, market-hours-only) cycle, polls Alpaca
  account equity and positions roughly once a minute and records three
  local snapshot rows every time - including while the market's closed,
  since a flat equity line during closed hours is real data, not a gap to
  skip:
    - `account_snapshot`: total equity/cash.
    - `position_snapshot`: one row per currently-held symbol, with
      Alpaca's own unrealized P&L fields (not a locally-derived proxy).
    - `bot_value_snapshot`: for each bot that's rebalanced at least once, a
      target-weighted price index of its own chosen symbols (not a dollar
      amount actually invested - Alpaca doesn't segregate positions by
      originating bot).
  This faster cadence is what feeds `display`'s idle-screen rotation (4.3)
  its "updated every minute or so" data, without the display itself ever
  calling Alpaca.
- No inbound network surface. It only makes outbound calls (monstra.pro,
  Alpaca).

There is deliberately **no separate provisioning/activation daemon** —
folding that into `trading_worker`'s startup state avoids a fourth
always-on process for a concern that's only active before the owner finishes
activation.

### 4.3 `display`

Drives the always-on physical display. Responsibilities:

- Native Python renderer targeting the framebuffer/DRM directly (e.g.
  pygame in KMSDRM mode) — no browser, no window manager. Chosen over a
  Chromium kiosk to keep boot time and RAM/CPU footprint low on a 2GB Pi 5,
  and because it's one fewer moving part to update and secure.
- A small state machine drives what's on screen:
  - `idle` (default): rotates through three candlestick sub-views on a
    fixed cadence (`display.idle_rotation`, 40-second cycle) rather than
    one static screen:
      1. **Portfolio (15s):** equity, today's P/L, market open/closed,
         last sync time, the most recent order's symbol/side and (if
         still held) its unrealized gain/loss, and a candlestick chart of
         the connected Alpaca account's recent equity (`display.candles`,
         built from `account_snapshot` history).
      2. **Bot (15s):** one active bot's latest signal and its approximate
         value-index chart (`display.bot_view`, from `bot_value_snapshot`)
         - a different bot each time the 40s cycle repeats.
      3. **Stock (10s):** one of the top-3 currently-held movers (ranked by
         Alpaca's intraday P&L%, `display.stock_view.top_movers`), its
         today's-move percentage, and a price candlestick chart built from
         `position_snapshot` history - a different stock each cycle.
    All three chart sources bucket several ~1-minute snapshots into each
    candle (a true 1-minute bucket would be a single flat tick, not a real
    candle); the rightmost bar keeps extending as each new snapshot lands,
    so every view visibly updates about once a minute even though each bar
    spans longer. None of this touches Alpaca directly - `display` only
    ever reads local device_core tables trading_worker already populates.
    All three sub-views also show a small permanent footer -
    "monstrapro.local  PIN &lt;code&gt;" - the local PIN
    (`device.local_pin`, `DeviceRepository.get_or_create_local_pin`)
    needed to reach `portfolio_web` (4.5), so it's always readable off the
    physical device regardless of which sub-view happens to be showing.
  - `wifi_setup`: first-boot Wi-Fi onboarding in progress (4.1) - AP name +
    setup URL. Entered on `wifi_onboarding_started`, left for `idle` on
    `wifi_connected`.
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

### 4.4 `updater`

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

### 4.5 `portfolio_web`

An always-on local web page, deliberately different in lifetime from
`device_agent`'s (4.1) temporary setup page: it stays running so the owner
can revisit `http://monstrapro.local` anytime from the same home network,
not just during first boot. This is a reversal of this document's earlier
V1 position (section 9 used to rule out any ongoing local HTTP API) —
made deliberately, for this one feature, not by accident.

- **PIN-gated.** `display` (4.3) shows a 6-digit PIN generated once per
  device; the page requires it (timing-safe compared) before granting a
  short-lived, in-memory session cookie. No PIN, no edits.
- **Bots**: toggle the three available strategies (force/aptet/draco) on
  or off (`strategy_config.source = "local"`). The owner doesn't set
  weights directly — each bot's own algorithm decides its allocation.
- **Locked stocks**: add an individual symbol with a target share quantity
  (`manual_holding`) that no bot will ever trade — see 4.2's rebalance
  exclusion and `manual_holdings.reconcile_manual_holdings` for the buy
  side.
- **Local-only, not reconciled with monstra.pro.** Edits here and edits
  via monstra.pro's own bot-picker (Track B, NextJS_Monsta) are two
  independent sources of truth for the same device in this pass — flagged
  explicitly (section 10), not silently resolved.
- Stdlib `http.server`, no framework — same "minimal dependencies"
  principle as `device_agent`'s setup page.

## 5. Startup process

See image/README.md for the full boot-order diagram and first-boot state
flow. Summary:

```
boot
 └─ systemd
     ├─ monstrapro-firstboot.service  (After=local-fs.target; runs once, as
     │                                 root, before the four services below -
     │                                 fixes /opt+/var/lib ownership)
     ├─ monstrapro-display.service    (After=local-fs.target only - starts
     │                                 immediately, never waits on network)
     ├─ monstrapro-agent.service      (After=NetworkManager.service, not
     │                                 network-online.target - its job is to
     │                                 CREATE connectivity when none exists)
     ├─ monstrapro-worker.service     (After=network-online.target)
     └─ monstrapro-updater.timer      (OnUnitActiveSec=1h, first run OnBootSec=5min)

device_agent startup:
  has a usable saved Wi-Fi connection? -> yes: no-op, exit
                                       -> no: start temporary AP -> emit
                                          wifi_onboarding_started -> host local
                                          setup page -> save+join via
                                          NetworkManager -> emit wifi_connected

trading_worker startup:
  load device_core.config
   -> open SQLite, run pending Alembic migrations
   -> read device.activated_at
      -> unset: poll monstra.pro device-status -> emit awaiting_activation -> repeat
      -> set:   pull strategy_config + Alpaca link -> enter trading loop

display startup:
  init renderer (framebuffer/DRM)
   -> render idle/wifi_setup/awaiting_activation screen (whichever
      device_event log says)
   -> subscribe to device_event, drive state machine
```

`device_agent`, `trading_worker`, and `display` are all `Restart=on-failure`
systemd services, so a crash self-heals without operator intervention — this
is the "recoverability" principle in practice. `monstrapro-firstboot.service`
is the one exception (a one-shot bootstrap, not restarted).

## 6. Configuration model

Layered, evaluated in this order (later layers override earlier ones):

1. **Code defaults** — safe fallback values compiled into `device_core.config`.
2. **`/etc/monstrapro/config.toml`** — device-level, non-secret settings:
   data directory paths, log level, poll intervals, the monstra.pro base URL.
   Safe to ship a template of this file in the disk image / commit to git
   (see image/config/monstrapro.toml).

   `data_dir` and `release_dir` default to two separate trees on Linux -
   `/var/lib/monstrapro` (persistent customer/device data: DB, encryption
   key, market data cache) and `/opt/monstrapro` (replaceable application
   code: the updater's `releases/<version>/` + `current` symlink) - so
   applying a software update never touches device/customer state.
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
| `device` | Device identity: serial, activation state, owner reference, disclosures-accepted timestamp, installed software version, local portfolio-page PIN (plaintext — see section 8). |
| `alpaca_credentials` | Encrypted API key/secret, base URL, paper/live mode, connected-at timestamp. |
| `strategy_config` | Bot slug, display name, strategy params, target allocation, active flag, source (monstra.pro vs local). |
| `portfolio_allocation` | Historical target vs. current weights per bot, timestamped. |
| `signal` | Signal history per bot — same shape as `Monstra-Worker`'s `trading.<bot>` signal rows, so engine output stays familiar. |
| `order` | Every order submitted to Alpaca: id, symbol, side, qty/notional, status, timestamps, raw response. |
| `execution_log` | Structured application log persisted for support/debugging, independent of journald retention. |
| `account_snapshot` | Equity/cash snapshots, ~1/minute — `display`'s portfolio candlestick chart, draco's circuit breaker. |
| `position_snapshot` | Currently-held-position snapshots with Alpaca's own unrealized P&L, ~1/minute — `display`'s last-trade P&L. No longer feeds a stock chart; see `market_data_cache` below. |
| `bot_value_snapshot` | Per-bot target-weighted price index, ~1/minute. No longer rendered as a chart — `display`'s per-bot idle screen dropped its candlestick in favor of showing the bot's full target-weights breakdown and recent trade activity instead; see `device_core/db/models.py`'s `BotValueSnapshot` docstring. |
| `bot_state` | Cross-run state a stateful bot (e.g. draco's circuit breaker) needs carried between `trading_worker` cycles. |
| `manual_holding` | Individually-held, locked-quantity stocks added via `portfolio_web` (4.5) — `trading_worker` buys up to `target_qty`, never sells, and every bot's rebalance math excludes these symbols entirely. |
| `market_data_cache` | Cached OHLC bars per (symbol, slide ∈ {1h, 1d, 1y}), refreshed by `trading_worker/stock_bar_sync.py` from Alpaca's market-data API on its own slower cadence. Originally scoped here and deferred at migration 0004 in favor of reusing `position_snapshot`; implemented at migration 0009 once the owner asked for a real per-stock 1-hour/1-trading-day/1-year chart, which current-price-only samples can't produce. Powers `display`'s per-stock idle screen (top 3 symbols by position size + top 2 by prior-day movement, 3 slides each). |
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
- `device.local_pin` is stored in plaintext, unlike Alpaca credentials —
  a deliberately different security model, not an oversight: it must be
  displayable in plaintext on the LCD for the owner to read off, is
  generated on-device, and is never transmitted anywhere (not to Alpaca,
  not to Monstra). `portfolio_web` compares it timing-safely
  (`hmac.compare_digest`) but the page itself is plain HTTP, not TLS — see
  image/README.md "What remains" for the same-LAN trust assumption this
  currently relies on.

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
- **Two local HTTP surfaces, deliberately different lifetimes.**
  `device_agent`'s setup page (4.1) is temporary — first-boot Wi-Fi
  onboarding only, torn down the moment the device joins a network.
  `portfolio_web` (4.5) is an ongoing, PIN-gated exception to this
  document's original "configuration happens entirely through monstra.pro"
  V1 position — added deliberately for local bot toggling and locked
  individual-stock holdings, not a general device-configuration surface
  beyond that.

## 10. What's explicitly deferred (not V1)

- Porting the actual bot strategy files into `strategy_engine/bots/`.
- A real `StrategyEngine` protocol/interface in `device_core` (today the
  registry pattern from `algorithm_registry.py` is the plan, not yet coded).
- Full OS image A/B updates (application-level release-directory updates are
  the V1 mechanism).
- True per-bot order attribution once multiple bots' trades are netted
  together (a virtual per-bot sub-account ledger, so a combined order could
  be split back into per-bot trade history) - basic equity-weighted netting
  itself IS implemented (trading_worker/loop.py: each active bot gets a
  configurable relative share of the account, and overlapping bot trades on
  the same symbol combine into one net order instead of racing each other),
  but a netted order is recorded under a synthetic bot_slug rather than
  attributed back to the contributing bots.
- Optional anonymized telemetry back to Monstra (the API boundary is left
  open for this, but nothing sends yet).
- A real, buildable Raspberry Pi OS image (`.img` file). `image/` provides
  the systemd units, first-boot bootstrap, and a Linux provisioning script,
  but no pi-gen/rpi-image-gen stage exists yet - see image/README.md "What
  remains before the first real Raspberry Pi image can be flashed".
- Reconciling `portfolio_web`'s local edits with monstra.pro's own
  bot-picker (Track B, NextJS_Monsta) - a device edited from both places
  currently ends up with two independent, disagreeing sources of truth.
  Flagged in 4.5, not silently resolved.
- TLS and stronger auth for `portfolio_web` beyond a PIN over plain HTTP -
  see image/README.md "What remains" for the same-LAN trust assumption
  this currently relies on.
