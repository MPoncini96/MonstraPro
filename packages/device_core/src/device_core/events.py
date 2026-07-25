"""Local pub/sub between services, backed by the device_event table.

Placeholder. trading_worker publishes (trade_executed, awaiting_activation,
connectivity_changed, ...); display subscribes by polling. Deliberately not
a socket/HTTP mechanism in V1 - see ARCHITECTURE.md section 9 for why.
"""
