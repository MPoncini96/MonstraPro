"""Bot type constants for the three algorithms ported to Monstra.Pro Box.

Ported from Monstra-Worker/bot_identity.py, trimmed to the bots this device
runs (alpha1/"force", aptet, draco). No suffix-stripping/inference is needed
here the way Monstra-Worker's multi-tenant worker needs it: a Pro Box's
strategy_config rows are keyed by slug directly, not by a legacy
`<name>_<bot_type>` composite id.
"""

from __future__ import annotations

BOT_TYPE_ALPHA1 = "alpha1"
BOT_TYPE_APTET = "aptet"
BOT_TYPE_DRACO = "draco"
