from datetime import datetime, timedelta, timezone

from portfolio_web.auth import SessionStore, verify_pin


class TestVerifyPin:
    def test_matching_pin_is_valid(self):
        assert verify_pin("482913", "482913") is True

    def test_mismatched_pin_is_invalid(self):
        assert verify_pin("000000", "482913") is False

    def test_whitespace_around_submission_is_trimmed(self):
        assert verify_pin("  482913  ", "482913") is True


class TestSessionStore:
    def test_created_token_is_valid(self):
        store = SessionStore()
        token = store.create()
        assert store.is_valid(token) is True

    def test_unknown_token_is_invalid(self):
        store = SessionStore()
        assert store.is_valid("not-a-real-token") is False

    def test_none_or_empty_token_is_invalid(self):
        store = SessionStore()
        assert store.is_valid(None) is False
        assert store.is_valid("") is False

    def test_token_expires_after_ttl(self):
        clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        store = SessionStore(ttl_seconds=1800, now=lambda: clock["now"])
        token = store.create()

        clock["now"] += timedelta(seconds=1799)
        assert store.is_valid(token) is True

        clock["now"] += timedelta(seconds=2)
        assert store.is_valid(token) is False

    def test_invalidate_revokes_a_token_immediately(self):
        store = SessionStore()
        token = store.create()

        store.invalidate(token)

        assert store.is_valid(token) is False

    def test_invalidate_none_is_a_noop(self):
        store = SessionStore()
        store.invalidate(None)  # must not raise

    def test_each_created_token_is_unique(self):
        store = SessionStore()
        tokens = {store.create() for _ in range(20)}
        assert len(tokens) == 20
