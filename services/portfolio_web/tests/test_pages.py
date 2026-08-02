from portfolio_web.pages import render_login_page, render_portfolio_page


class TestRenderLoginPage:
    def test_renders_without_error_by_default(self):
        assert b"PIN" in render_login_page()

    def test_includes_error_message_when_given(self):
        body = render_login_page(error="Incorrect PIN.")
        assert b"Incorrect PIN." in body

    def test_escapes_error_message(self):
        body = render_login_page(error="<script>alert(1)</script>")
        assert b"<script>alert(1)</script>" not in body
        assert b"&lt;script&gt;" in body


class TestRenderPortfolioPage:
    def test_lists_each_bot_with_its_active_state(self):
        bots = [
            {"slug": "force", "display_name": "Force", "is_active": True},
            {"slug": "aptet", "display_name": "Aptet", "is_active": False},
        ]
        body = render_portfolio_page(bots=bots, holdings=[])

        assert b"Force" in body
        assert b"Aptet" in body
        # The active bot's checkbox is checked, the inactive one's isn't.
        force_idx = body.index(b'value="force"')
        aptet_idx = body.index(b'value="aptet"')
        assert b"checked" in body[force_idx : force_idx + 40]
        assert b"checked" not in body[aptet_idx : aptet_idx + 40]

    def test_no_holdings_shows_empty_state(self):
        body = render_portfolio_page(bots=[], holdings=[])
        assert b"No locked stocks added yet." in body

    def test_lists_each_locked_holding_with_a_remove_form(self):
        holdings = [{"symbol": "AAPL", "target_qty": 10.0}]
        body = render_portfolio_page(bots=[], holdings=holdings)

        assert b"AAPL" in body
        assert b'action="/portfolio/holdings/remove"' in body
        assert b'value="AAPL"' in body

    def test_message_is_shown_and_escaped(self):
        body = render_portfolio_page(bots=[], holdings=[], message="<b>hi</b>")
        assert b"<b>hi</b>" not in body
        assert b"&lt;b&gt;hi&lt;/b&gt;" in body

    def test_symbol_and_display_name_are_escaped(self):
        bots = [{"slug": "force", "display_name": "<img src=x>", "is_active": True}]
        body = render_portfolio_page(bots=bots, holdings=[])
        assert b"<img src=x>" not in body
