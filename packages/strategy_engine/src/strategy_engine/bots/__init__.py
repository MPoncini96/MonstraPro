"""Strategy implementations, one module per bot.

Each module ports one bot from Monstra-Worker/bots/ with its pure-function
signature preserved: run_<bot>(config, state=None) -> signal dict. No DB, no
HTTP beyond the shared market_data provider, no Postgres/Next.js coupling —
that coupling lives in Monstra-Worker's worker.py/db.py and was not ported.

Ships with three bots for now: alpha1 ("force"), aptet, draco.
"""
