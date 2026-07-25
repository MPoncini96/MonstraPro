"""Structured logging setup, shared by all services.

Placeholder — mirrors the structured-logging approach in
Monstra-Worker/worker_logging.py (status/error/context fields), but also
persists to the execution_log table via device_core.db so logs survive
independent of journald retention (ARCHITECTURE.md section 7).
"""
