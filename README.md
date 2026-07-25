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

Architecture designed, foundational scaffold in place. Services under
`services/` are stubs (`NotImplementedError`) pending implementation.

## Layout

- `packages/strategy_engine` — portable strategy/bot logic, shareable with
  Monstra.bot.
- `packages/device_core` — shared appliance infrastructure (config, DB,
  crypto, logging, local eventing).
- `services/trading_worker` — scheduler, activation state machine, order
  execution against Alpaca.
- `services/display` — always-on status display renderer.
- `services/updater` — checks monstra.pro for releases and applies updates.
- `deploy/systemd` — unit/timer files for the three services.

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
