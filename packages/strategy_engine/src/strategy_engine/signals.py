"""Signal shape shared between strategy_engine and trading_worker.

Placeholder. When implemented, defines the Signal dataclass returned by
every run_<bot>(config, state=None) function: bot_id, bot_type, ts, signal,
note, payload (including target_weights), and optional updated state. Keep
the field names aligned with Monstra-Worker's signal dict shape
(see Monstra-Worker/bots/alpha1.py and worker.py::run_bot) so ported bot
code doesn't need reshaping.
"""
