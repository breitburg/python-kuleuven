from datetime import UTC, datetime

from kuleuven.shibboleth import find_form, parse_session_summary


class TestFindForm:
    def test_returns_action_and_fields_when_predicate_matches(self):
        html = """
        <form action="/login" method="post">
            <input name="username" value="">
            <input name="password" value="">
        </form>
        """
        result = find_form(html, lambda names: {"username", "password"} <= names)
        assert result is not None
        action, fields = result
        assert action == "/login"
        assert fields == {"username": "", "password": ""}

    def test_returns_none_when_no_form_matches(self):
        html = '<form action="/x"><input name="foo"></form>'
        assert find_form(html, lambda names: "bar" in names) is None

    def test_picks_first_matching_form_when_multiple(self):
        html = """
        <form action="/a"><input name="token" value="A"></form>
        <form action="/b"><input name="token" value="B"></form>
        """
        action, fields = find_form(html, lambda names: "token" in names)
        assert action == "/a"
        assert fields["token"] == "A"


class TestParseSessionSummary:
    def test_extracts_miscellaneous_and_attributes(self):
        html = """
        <pre>
        Miscellaneous
        Session Expiration (barring inactivity): 2879 minute(s)
        Authentication Time: 2026-05-26T12:28:29Z
        Authentication Context Class: urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract
        Attributes
        uid: r0123456
        affiliation: member@kuleuven.be;student@kuleuven.be
        </pre>
        """
        summary = parse_session_summary(html)
        assert summary is not None
        assert summary["attributes"]["uid"] == "r0123456"
        assert summary["expires_in_minutes"] == 2879
        assert summary["authenticated_at"] == datetime(
            2026, 5, 26, 12, 28, 29, tzinfo=UTC
        )
        assert summary["authentication_context_class"].endswith(
            "MobileTwoFactorContract"
        )

    def test_returns_none_when_no_attributes(self):
        # The IdP serves a Miscellaneous-only page during the storage probe
        # bounce. parse_session_summary must distinguish that from a real
        # signed-in summary.
        html = "<pre>Miscellaneous\nSession Expiration (barring inactivity): 0 minute(s)\n</pre>"
        assert parse_session_summary(html) is None

    def test_returns_none_when_no_pre(self):
        assert parse_session_summary("<html><body>not the summary page</body></html>") is None
