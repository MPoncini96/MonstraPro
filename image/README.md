# Monstra.Pro Box — image/

Foundation for the reproducible Raspberry Pi OS Lite (64-bit) image and
first-boot Wi-Fi onboarding described in Objectives.txt. This directory
does **not** build a real image yet - see "What remains" at the bottom.
It contains everything that's OS/deployment-specific and doesn't belong in
`packages/`/`services/` themselves: install-time provisioning, first-boot
bootstrap, systemd units, and config templates.

This supersedes the placeholder `deploy/systemd/` from the earlier
architecture scaffold, which used a three-service, no-onboarding boot order.
`deploy/systemd/` has been removed; `image/systemd/` is now the only copy.

## Layout

```
image/
  README.md            this file
  config/
    monstrapro.toml               template for /etc/monstrapro/config.toml
    dnsmasq-setup-domain.conf     setup.monstra -> AP gateway DNS override
    image.toml                    declarative base-image spec (docs only, not executed)
  systemd/
    monstrapro-firstboot.service  one-shot bootstrap, runs once, as root
    monstrapro-lcd-setup.service  3.5in LCD driver install, idempotent, as root
    monstrapro-agent.service      device_agent: first-boot Wi-Fi onboarding
    monstrapro-display.service    display: always-on status screen
    monstrapro-worker.service     trading_worker: activation + trading loop
    monstrapro-portfolio-web.service  portfolio_web: always-on local portfolio page
    monstrapro-updater.service    updater: one-shot, triggered by the timer
    monstrapro-updater.timer      hourly trigger for the updater
  scripts/
    install.sh            provisions a real Linux host (Pi 5 or otherwise)
    first-boot.sh          idempotent bootstrap run by monstrapro-firstboot.service
    lcd-setup.sh            idempotent MHS35 LCD driver install + rotation
  tests/
    test_systemd_units.py     static assertions on the unit files
    test_install_script.py    static assertions on install.sh/first-boot.sh
    test_lcd_setup_script.py  static assertions on lcd-setup.sh
```

## Why a new `device_agent` service

ARCHITECTURE.md's original V1 design had three services (`trading_worker`,
`display`, `updater`) and folded activation-status polling into
`trading_worker`. Wi-Fi onboarding is a materially different concern - it
has to run *before* there's any network at all, drive a temporary access
point, and host a local web page - so it's its own service
(`services/device_agent`) rather than more responsibility bolted onto
`trading_worker`. It hands off to `trading_worker`'s existing
`awaiting_activation` flow once the device is online and knows nothing
about activation or pairing codes itself - see
`services/device_agent/src/device_agent/onboarding.py`'s docstring.

## Local portfolio editing (`portfolio_web`)

A second, deliberately different kind of local web service from
`device_agent`'s: that one is temporary (torn down once Wi-Fi is
configured); `portfolio_web` stays up permanently so the owner can revisit
`http://monstrapro.local` anytime from a browser on the same home network,
not just during first boot. ARCHITECTURE.md section 9 previously ruled out
an ongoing local HTTP API for V1 - this reverses that, deliberately, for
this one feature.

- **PIN-gated.** The device generates a 6-digit PIN once
  (`device_core.repositories.device.DeviceRepository.get_or_create_local_pin`)
  and `display` shows it as a small permanent footer on all three
  idle-rotation screens ("monstrapro.local  PIN 482913"). Anyone editing
  the portfolio needs to have read it off the physical device first.
  Sessions are PIN-then-cookie (`services/portfolio_web/src/portfolio_web/auth.py`),
  30 minutes, in-memory only - a service restart requires re-entering the
  PIN, an intentional, safe-by-default tradeoff for a low-stakes local
  convenience feature.
- **Bots**: toggle the three available strategies (force/aptet/draco) on
  or off. The owner doesn't set weights directly - each bot's own
  algorithm decides its allocation once active, same as monstra.pro's
  existing bot-picker.
- **Locked stocks**: add an individual symbol with a target share quantity
  that no bot will ever buy or sell - see "Locked individual stocks"
  below for the safety mechanics.
- **Local-only for this pass.** Edits write to the device's own
  `strategy_config`/`manual_holding` tables (`source="local"`) and are
  never synced to or reconciled with monstra.pro's own bot-picker
  (Track B, NextJS_Monsta) - a device edited both ways can end up with
  two disagreeing sources of truth. Flagged here deliberately rather than
  silently resolved; see "What remains" below.

## Locked individual stocks

`manual_holding` rows (`device_core.db.models.ManualHolding`) are
individually-held stocks the owner wants completely outside of algorithmic
control:

- **Acquiring one only ever buys.** `trading_worker`'s
  `manual_holdings.reconcile_manual_holdings` runs every trading cycle,
  compares each holding's `target_qty` against however many shares Alpaca
  actually reports currently held, and submits a buy for the shortfall.
  It never sells - if more shares are held than `target_qty` (e.g. bought
  separately in the Alpaca app), that's left alone.
- **Bots never touch a locked symbol.** This is the safety-critical half:
  without it, a locked position with no corresponding bot target weight
  looks - to the rebalancing math alone - exactly like a position that
  should be fully sold. `trading_worker/src/trading_worker/loop.py`
  excludes every locked symbol from a bot's target weights (renormalized
  back to sum ~1.0), from what the bot sees as its current holdings, and
  subtracts the locked value from the equity the bot is allowed to
  allocate against. See `services/trading_worker/tests/test_rebalance.py`'s
  `test_locked_position_would_otherwise_be_sold_without_exclusion` for the
  concrete failure mode this prevents.
- **Removing a locked holding never sells either.** It only stops
  protecting that symbol going forward - the shares stay in the account,
  now available for a bot's own strategy to manage if it happens to want
  that symbol too.

## Boot order

```
boot
 └─ systemd
     ├─ monstrapro-firstboot.service   (After=local-fs.target; runs once, as root)
     │    Before= lcd-setup/agent/worker/display - fixes /opt+/var/lib
     │    ownership before any non-root service tries to write to them.
     │
     ├─ monstrapro-lcd-setup.service   (After=local-fs.target, firstboot; runs once, as root)
     │    Before= agent/worker/display (ordered, not required - a failure
     │    here doesn't block the rest). Installs the 3.5in LCD driver from
     │    an offline-vendored copy - see "LCD display setup" below. May
     │    reboot the Pi the very first time it runs; a no-op after that.
     │
     ├─ monstrapro-display.service     (After=local-fs.target, firstboot, lcd-setup)
     │    Starts immediately - does NOT wait on networking, matching
     │    Objectives.txt: "Starts the display immediately while networking
     │    and other services initialize."
     │
     ├─ monstrapro-agent.service       (After=NetworkManager.service, firstboot, lcd-setup)
     │    Deliberately after the *daemon*, not network-online.target - its
     │    job is to CREATE connectivity when none exists, so waiting for
     │    "network is online" would deadlock on a genuine first boot.
     │
     ├─ monstrapro-worker.service      (After=network-online.target, firstboot, lcd-setup)
     │    Its own activation-poll loop already tolerates "not online yet"
     │    (LocalActivationClient never makes a network call) - by the time
     │    it does reach monstra.pro, either a saved connection existed, or
     │    monstrapro-agent has already joined one.
     │
     ├─ monstrapro-portfolio-web.service (After=network-online.target, firstboot)
     │    Always-on, unlike monstrapro-agent - stays up so the owner can
     │    reach http://monstrapro.local anytime, not just during first
     │    boot. See "Local portfolio editing" below.
     │
     └─ monstrapro-updater.timer       (OnBootSec=5min, OnUnitActiveSec=1h)
          -> monstrapro-updater.service (After=network-online.target, firstboot)
```

`monstrapro-display.service` and `monstrapro-agent.service` are the two
that must not be blocked by network availability - both are ordered off
`local-fs.target`/`NetworkManager.service` only, never
`network-online.target`. `monstrapro-lcd-setup.service` is ordered off
`local-fs.target` too, for the same reason plus one more: it must not wait
on the very Wi-Fi that `device_agent`'s onboarding screen (rendered on this
LCD) is trying to establish - see "LCD display setup" below.

## First-boot state flow

```
power on
 -> monstrapro-firstboot.service (root): chown /opt+/var/lib to monstrapro, touch marker
 -> monstrapro-lcd-setup.service (root): LCD driver marker missing -> installs
    MHS35 driver from the offline-vendored copy -> Pi reboots
    -> (after that one reboot) markers now present -> no-op on every boot after
 -> monstrapro-display.service starts, renders whatever device_event log
    already says (nothing yet on a truly first boot -> idle/blank-ish
    default screen for a moment) - now rendering to the configured LCD
    once the one-time driver-install reboot above has happened
 -> monstrapro-agent.service starts:
      connectivity.has_usable_connection()?
        yes -> no-op, process idles/exits cleanly (already-provisioned
               device, e.g. a reboot)
        no  -> start temporary AP "MonstraPro-XXXX" (XXXX = hash of the
               device serial, never the serial itself)
               -> publish `wifi_onboarding_started` {ap_ssid, setup_url}
               -> display switches to WIFI_SETUP screen:
                    "Connect your phone to MonstraPro-XXXX"
                    "Then visit setup.monstra"
               -> setup_server.py hosts the local page (port 80): lists
                  nearby networks (WifiScanner.scan()), accepts ssid+password
               -> customer submits -> connector.connect_and_save() via
                  NetworkManager -> on success: stop the AP, publish
                  `wifi_connected`
               -> display returns to idle
 -> monstrapro-worker.service (running the whole time): its activation
    poll loop reaches monstra.pro now that the device is online, publishes
    `awaiting_activation` {device_serial} once it gets a response
 -> display's state machine: idle -> awaiting_activation (device
    registration + pairing-code screen) - this is the "transition the
    display to device registration and pairing-code status" step; device_agent
    itself never touches activation/pairing, by design.
```

## Local-credentials architecture (preserved)

The customer's Wi-Fi password only ever reaches this device's own
NetworkManager, through `device_agent.network.WifiConnector.connect_and_save`.
It is never logged (`setup_server.py`'s request handler suppresses its own
access log for exactly this reason), never written to disk by this
package, and never sent to any Monstra server. The same is already true of
Alpaca credentials (`device_core.vault`) and local trading commands
(`trading_worker` only calls Alpaca directly, per ARCHITECTURE.md section
9) - device_agent doesn't change that boundary, it just extends the same
principle to Wi-Fi.

## LCD display setup

Automates what was previously a manual step run once by hand on every unit:

```bash
cd ~ && git clone https://github.com/goodtft/LCD-show.git
cd LCD-show && sudo ./MHS35-show      # installs driver + reboots
sudo ./rotate.sh 180                  # rotation correction, if needed
```

`image/scripts/lcd-setup.sh` (run by `monstrapro-lcd-setup.service`, as
root, very early in boot) wraps this into something idempotent and
unattended:

- **Idempotent by marker file.** `/var/lib/monstrapro/.lcd-driver-installed`
  is written *before* `MHS35-show` runs; `/var/lib/monstrapro/.lcd-rotation-<N>`
  (rotation baked into the filename) is written *before* `rotate.sh <N>`
  runs. On every later boot, both markers already exist and the whole
  script is a no-op - no repeated reboots, no re-running an already-applied
  driver install. Requesting a *different* rotation later only re-runs the
  lighter `rotate.sh` step, not the full driver install.
- **Why the marker is written *before* the step, not after:** `MHS35-show`
  (and possibly `rotate.sh`) reboot the Pi unconditionally when they finish
  - this wrapper can't prevent that without patching third-party vendor
    code, and doesn't try to. If the marker were written *after*, a reboot
  mid-step would mean the marker is never written and the step re-runs
  forever. Writing it *before* means the worst case is skipping a step that
  technically didn't finish - acceptable for a driver install step that is
  itself idempotent/re-runnable by design, and far better than a reboot
  loop. Confirming this holds on real hardware is a "what must be tested on
  the physical Raspberry Pi" item below.
- **Configurable rotation, defaulting to 180** for this enclosure - override
  with `--rotation` or `MONSTRAPRO_LCD_ROTATION` in `/etc/monstrapro/env`
  (same override mechanism the other systemd units already use). Valid
  values: `0`, `90`, `180`, `270`, matching `rotate.sh`'s own.
- **Linux-only, dry-run supported.** Same `uname -s` guard and `run()`
  dry-run wrapper as `install.sh` - refuses to do anything on a non-Linux
  host, and `--dry-run` prints every command it would run (including the
  `git clone`) without executing any of them.
- **Runs before the network is needed, and before `display`/`agent`/`worker`.**
  `device_agent`'s Wi-Fi onboarding instructions ("Connect your phone to
  MonstraPro-XXXX...") are shown *on this LCD* - so the LCD driver can't
  wait on the Wi-Fi that onboarding itself is establishing. `lcd-setup.sh`
  resolves this by operating entirely offline: `image/scripts/install.sh`
  vendors `goodtft/LCD-show` into `/opt/monstrapro/vendor/LCD-show` once,
  at provisioning time (on a networked build host), so no runtime GitHub
  access is ever needed on a customer's device. `lcd-setup.sh` also falls
  back to cloning it itself if that vendor directory is somehow missing,
  keeping the script independently correct, but the intended path never
  needs to.
- **HDMI is not required after setup.** Once the driver and rotation are
  applied, the 3.5in LCD is the primary display via the framebuffer/console
  config `MHS35-show` installs - nothing in `services/display` or systemd
  depends on an HDMI connection existing. The physical HDMI cable, if any,
  should be disconnected once setup is confirmed working; leaving it
  connected is harmless but unnecessary.

## Local development / simulation (Windows-safe)

Nothing under `image/` executes real NetworkManager, access-point, or
disk-image commands during development - all of that is Linux-only shell
(`image/scripts/*.sh`, never invoked by this repo's tooling) or gated
behind `device_agent.network.NetworkManagerClient`, which is only
constructed when `platform.system() == "Linux"`.

To exercise `device_agent` locally, on any OS:

```bash
cd services/device_agent
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt -e .
.venv/Scripts/pytest -q          # 21 tests, all offline: identity, simulated
                                  # network, onboarding orchestration, and a
                                  # real (loopback-only) setup_server
```

`device_agent.main._build_network_manager()` picks `SimulatedNetworkManager`
automatically on any non-Linux host, or on Linux when
`DEVICE_AGENT_SIMULATE=1` is set (useful for testing the onboarding flow on
real Linux dev hardware without touching its actual Wi-Fi). Running
`python -m device_agent.main` under simulation starts a real local HTTP
setup page on `127.0.0.1:80` (or whatever `SETUP_SERVER_PORT` is set to) so
the page itself can be clicked through in a browser even off-device.

## Installing on a real Raspberry Pi 5 (once the base image exists)

This repeats what `image/scripts/install.sh` automates - documented
separately so it can be sanity-checked line by line the first time:

1. Flash Raspberry Pi OS Lite (64-bit) to a microSD card, enable SSH.
2. Boot the Pi, `git clone`/copy this repo onto it (or, once a real release
   pipeline exists, download a signed release artifact instead).
3. `sudo image/scripts/install.sh --dry-run` first, read the output.
4. `sudo image/scripts/install.sh` for real. This creates the `monstrapro`
   user, `/opt/monstrapro/releases/<version>/` with a venv per service,
   `/opt/monstrapro/current` symlinked at it, `/etc/monstrapro/config.toml`,
   the dnsmasq `setup.monstra` override, an offline-vendored copy of
   `goodtft/LCD-show` at `/opt/monstrapro/vendor/LCD-show`, and
   installs+enables all six systemd units (five `.service` + one `.timer`).
5. Reboot. Expect a *second*, automatic reboot shortly after this one -
   `monstrapro-lcd-setup.service` installs the LCD driver on its first run,
   which reboots the Pi unconditionally (this is normal, not a failure; see
   "LCD display setup" above). After that second reboot, connect the LCD
   (if not already) and disconnect HDMI - it's no longer needed.
6. `journalctl -u monstrapro-lcd-setup -f`, `journalctl -u monstrapro-agent -f`,
   and `journalctl -u monstrapro-display -f` to watch first boot happen.
7. From a phone: join `MonstraPro-XXXX`, visit `http://setup.monstra`,
   submit the home Wi-Fi network. Confirm the Pi joins it and the display
   moves to the activation/pairing screen.

## What remains before the first real Raspberry Pi image can be flashed

- **A real base image build.** `image/config/image.toml` is a declarative
  spec, not an executable pi-gen/rpi-image-gen stage - nothing produces a
  `.img` file yet.
- **`portfolio_web` is plaintext HTTP.** The PIN travels in cleartext on
  login, same trust model as `device_agent`'s existing setup page. Fine
  for a same-household LAN in this pass; not evaluated against a hostile
  local network (e.g. a compromised IoT device on the same Wi-Fi).
- **`monstrapro.local` depends on the home router/network supporting mDNS.**
  Stock Raspberry Pi OS advertises it via `avahi-daemon` out of the box,
  but some routers, guest networks, or VLAN setups block mDNS - not tested
  against real household network variety yet. Falling back to the device's
  IP address is always possible but isn't documented anywhere user-facing.
- **Local portfolio edits vs. monstra.pro's bot-picker: two sources of
  truth, deliberately not reconciled.** See "Local portfolio editing"
  above - a device edited from both places can disagree with itself.
- **NetworkManager polkit policy.** `monstrapro-agent.service` grants the
  non-root `monstrapro` user `CAP_NET_ADMIN` so `nmcli` can reach
  NetworkManager over D-Bus, but NetworkManager's own polkit rules may still
  require an explicit `org.freedesktop.NetworkManager.*` allow rule for a
  non-console user to create a hotspot / modify system connections. Needs
  verifying against Raspberry Pi OS's actual shipped polkit config.
- **`systemctl restart` polkit/sudoers rule.** `services/updater`'s
  release-apply flow calls `systemctl restart monstrapro-worker.service
  monstrapro-display.service` as the `monstrapro` user - needs an explicit
  polkit rule or a narrowly-scoped sudoers entry; not yet written.
- **Real `nmcli -t` output validation.** `device_agent.network.NetworkManagerClient`'s
  colon-delimited parsing is written against documented `nmcli` behavior,
  not verified against the exact NetworkManager version Raspberry Pi OS
  Lite ships.
- **Hardware display target.** `services/display` still targets a
  constructor-supplied resolution (`pygame_renderer.DEFAULT_SIZE`); the
  real panel's size/orientation/SDL_VIDEODRIVER=kmsdrm behavior needs
  verifying on actual Pi 5 hardware. Confirmed via headless render during
  development: the idle screen's header + bots list + candle performance
  chart fit comfortably at the 800x480 code default, but are tight at
  480x320 (the size commonly quoted for this panel) once 3 bots are
  active - see `pygame_renderer.py`'s module docstring. Worth resolving
  once the real resolution is confirmed, not guessed at further now.
- **`goodtft/LCD-show` compatibility with Raspberry Pi 5.** That repo
  predates the Pi 5's `/boot/firmware` layout and current kernel; whether
  `MHS35-show`/`rotate.sh` work unmodified needs verifying on real hardware,
  and if not, `image/scripts/lcd-setup.sh` (or a Pi-5-specific fork/patch of
  the vendored driver) will need adjusting. Tracked here rather than assumed.
- **Whether `rotate.sh` itself reboots.** `lcd-setup.sh`'s marker-before-step
  ordering is written to be correct either way, but which of the two vendor
  scripts actually triggers the reboot(s) - and how many - is unconfirmed
  until run on real hardware.
- **Release artifact pipeline.** `install.sh` copies this repo's working
  tree directly into the first release directory - there's still no signed
  release-artifact build/publish pipeline for `services/updater` to consume
  after that (tracked in SESSION_SUMMARY.txt as a pre-existing gap).
- **A real base image's public key.** `services/updater/src/updater/main.py`
  expects `release_signing_key.pub` baked into the release root; nothing
  provisions that file yet.
- **Real hardware bring-up.** Everything here is designed and unit-tested
  against injected/simulated interfaces; nothing has run on an actual
  Raspberry Pi 5 yet.
