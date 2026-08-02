"""PIN-based session auth for the local portfolio page.

The PIN itself (device_core `device.local_pin`) is generated once per
device and displayed on the LCD (services/display) - see
device_core.db.models.Device's docstring for why it's stored in plaintext
rather than hashed like Alpaca credentials. This module only turns a
correctly-submitted PIN into a short-lived session, using a timing-safe
comparison (hmac.compare_digest) so a network observer can't exploit
response-time differences to guess the PIN character by character.

Sessions are intentionally in-memory, not persisted: a service restart
forcing PIN re-entry is an acceptable, safe-by-default tradeoff for a
low-stakes local convenience feature, not a bug.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

SESSION_COOKIE_NAME = "monstrapro_session"
DEFAULT_SESSION_TTL_SECONDS = 1800  # 30 minutes


def verify_pin(submitted: str, actual: str) -> bool:
    return hmac.compare_digest(submitted.strip(), actual)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SessionStore:
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    now: Callable[[], datetime] = field(default=_utcnow)
    _expires_at: dict[str, datetime] = field(default_factory=dict, init=False)

    def create(self) -> str:
        token = secrets.token_urlsafe(24)
        self._expires_at[token] = self.now() + timedelta(seconds=self.ttl_seconds)
        return token

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        expires_at = self._expires_at.get(token)
        if expires_at is None:
            return False
        if self.now() >= expires_at:
            del self._expires_at[token]
            return False
        return True

    def invalidate(self, token: str | None) -> None:
        if token:
            self._expires_at.pop(token, None)
