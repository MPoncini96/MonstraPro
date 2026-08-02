# Monstra.Pro Box

A dedicated Linux trading appliance that executes Monstra strategies locally
on customer-owned hardware. See [ARCHITECTURE.md](ARCHITECTURE.md) for the
full design — project layout, services, database schema, update mechanism,
and API boundaries.

Not a replacement for Monstra.bot. Monstra.bot stays the strategy-creation /
research / community product; the Pro Box is local execution on dedicated,
always-on hardware. Monstra servers never execute trades or see Alpaca
credentials — everything trading-related happens on the device.

## Status

Architecture implemented and tested (see SESSION_SUMMARY.txt for the full
history). `image/` now provides the Raspberry Pi OS Lite boot foundation —
systemd units, first-boot bootstrap, and Wi-Fi onboarding — but no real
bootable image has been built or flashed yet; see
[image/README.md](image/README.md) for what remains.

## Layout

- `packages/strategy_engine` — portable strategy/bot logic, shareable with
  Monstra.bot.
- `packages/device_core` — shared appliance infrastructure (config, DB,
  crypto, logging, local eventing).
- `services/device_agent` — first-boot Wi-Fi onboarding: temporary access
  point + local setup page + NetworkManager join.
- `services/trading_worker` — scheduler, activation state machine, order
  execution against Alpaca.
- `services/display` — always-on status display renderer.
- `services/updater` — checks monstra.pro for releases and applies updates.
- `image/` — Raspberry Pi image configuration, systemd units, install/
  first-boot scripts, and docs. See [image/README.md](image/README.md).

## Local development

Each package/service has its own `requirements.txt` and `src/` layout,
matching the `venv` + `pip` convention used across the other Monstra repos
(no poetry/uv). To work on one, e.g. `device_core`:

```bash
cd packages/device_core
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

There is no root-level install — packages are developed and tested
independently, then wired together via `services/*/requirements.txt`
referencing them as local/editable installs once real code lands.
