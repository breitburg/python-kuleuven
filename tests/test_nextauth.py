from datetime import UTC, datetime

import pytest
import typer

from kuleuven.cli.session import CliAuthenticationProvider
from kuleuven.exceptions import AuthenticationError
from kuleuven.nextauth import (
    NextauthDevice,
    parse_device_picker,
    parse_wait_params,
)

# Mirrors the real e1s5 device picker structure with fabricated identifiers.
DEVICE_PICKER_HTML = """
<form action="/idp/profile/SAML2/POST/SSO?execution=e1s5" method="post" id="loginformnextauth">
  <div>Select the device you want to login with:
    <button type="button" data-device-name="Tablet" data-account-id="acct-tablet-0001">
      Tablet
    </button>
    <div><small>Last login at: Mon, 1 Jan 2024 00:00:00 GMT</small></div>
    <button type="button" data-device-name="Phone" data-account-id="acct-phone-0002">
      Phone
    </button>
    <div><small>Last login at: Wed, 1 Jan 2025 00:00:00 GMT</small></div>
  </div>
  <input type="hidden" name="_eventId_proceed" value="">
  <a href="https://account.kuleuven.be/mfa">Manage devices</a>
</form>
"""

# The real picker page wires the socket in <body onload>, with the wss host
# HTML-entity-encoded and knownstatus as a bare boolean.
WAIT_PAGE_HTML = (
    "<body onload=\"nextauthwsinit('server-abc','register-xyz',false,"
    "'wss&#x3a;&#x2f;&#x2f;authenticator-wss.icts.kuleuven.be');\">"
    "</body>"
)


class TestParseDevicePicker:
    def test_extracts_action_and_devices(self):
        result = parse_device_picker(DEVICE_PICKER_HTML)
        assert result is not None
        action, devices = result
        assert action == "/idp/profile/SAML2/POST/SSO?execution=e1s5"
        assert [device.name for device in devices] == ["Tablet", "Phone"]
        assert devices[0].account_id == "acct-tablet-0001"
        assert devices[1].last_login == datetime(2025, 1, 1, tzinfo=UTC)

    def test_returns_none_without_device_buttons(self):
        assert parse_device_picker('<form id="x"><input name="username"></form>') is None

    def test_unparseable_last_login_fails_loudly(self):
        # A format we don't understand must not silently become "never logged
        # in", which would mis-rank the most recent device.
        html = DEVICE_PICKER_HTML.replace(
            "Mon, 1 Jan 2024 00:00:00 GMT", "whenever, really"
        )
        with pytest.raises(AuthenticationError):
            parse_device_picker(html)


class TestParseWaitParams:
    def test_extracts_websocket_params(self):
        params = parse_wait_params(WAIT_PAGE_HTML)
        assert params.server_id == "server-abc"
        assert params.register_id == "register-xyz"
        assert params.host == "wss://authenticator-wss.icts.kuleuven.be"

    def test_raises_when_no_init_call(self):
        with pytest.raises(AuthenticationError):
            parse_wait_params("<html><body>no script here</body></html>")


def _devices():
    return [
        NextauthDevice("acct-tablet-0001", "Tablet", datetime(2024, 1, 1, tzinfo=UTC)),
        NextauthDevice("acct-phone-0002", "Phone", datetime(2025, 1, 1, tzinfo=UTC)),
    ]


class TestDeviceSelection:
    def test_most_recent_picks_newest_last_login(self):
        provider = CliAuthenticationProvider(totp=None, device="most-recent")
        assert provider.select_device(_devices()).name == "Phone"

    def test_index_selects_one_based(self):
        provider = CliAuthenticationProvider(totp=None, device="1")
        assert provider.select_device(_devices()).name == "Tablet"

    def test_name_match_is_case_insensitive(self):
        provider = CliAuthenticationProvider(totp=None, device="phone")
        assert provider.select_device(_devices()).name == "Phone"

    def test_unknown_device_exits_with_code_two(self):
        provider = CliAuthenticationProvider(totp=None, device="laptop")
        with pytest.raises(typer.Exit) as excinfo:
            provider.select_device(_devices())
        assert excinfo.value.exit_code == 2

    def test_device_without_last_login_sorts_oldest(self):
        provider = CliAuthenticationProvider(totp=None, device="most-recent")
        devices = [*_devices(), NextauthDevice("acct-new-0003", "Laptop", None)]
        assert provider.select_device(devices).name == "Phone"
