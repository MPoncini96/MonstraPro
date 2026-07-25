"""SQLAlchemy engine factory.

Placeholder. Builds a SQLite engine from device_core.config for V1;
swapping to Postgres later should only require changing the connection
string this factory builds, since all queries go through SQLAlchemy Core
(see models.py) rather than raw SQLite-specific SQL.
"""
