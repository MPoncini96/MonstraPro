"""Layered configuration loader.

Placeholder. Layers, lowest to highest precedence (see ARCHITECTURE.md
section 6):

    1. code defaults
    2. /etc/monstrapro/config.toml (non-secret device settings)
    3. SQLite device/settings rows (activation state, strategy config)
    4. environment variables (dev-only overrides)

Secrets (Alpaca credentials) are never read from the TOML layer - only from
the encrypted alpaca_credentials table via device_core.crypto.
"""
