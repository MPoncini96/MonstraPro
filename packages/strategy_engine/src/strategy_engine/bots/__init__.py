"""Strategy implementations, one module per bot.

Placeholder. Each module ports one bot from Monstra-Worker/bots/ (e.g.
alpha1.py -> run_alpha1) with its pure-function signature preserved:
run_<bot>(config, state=None) -> signal dict. No DB, no HTTP beyond the
shared market_data provider, no Postgres/Next.js coupling — that coupling
lives in Monstra-Worker's worker.py/db.py and must not be ported.

Which bot(s) ship first is a product decision for the foundational-services
pass, not this scaffold.
"""
