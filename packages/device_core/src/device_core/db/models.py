"""Database schema (table definitions).

Placeholder. Full column definitions land with the device_core
foundational-services pass. Table names and purpose are locked in by
ARCHITECTURE.md section 7:

    device                 - identity, activation state, owner ref, version
    alpaca_credentials     - encrypted API key/secret, base URL, mode
    strategy_config        - bot slug, params, target allocation, active flag
    portfolio_allocation   - historical target vs current weights
    signal                 - signal history per bot
    order                  - orders submitted to Alpaca
    execution_log          - persisted structured application log
    market_data_cache      - cached OHLCV bars
    software_release       - installed/staged release versions
    device_event           - append-only local event log (see events.py)
"""
