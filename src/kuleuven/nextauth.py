import re
import time
from dataclasses import dataclass
from html import unescape

import httpx
import websocket
from bs4 import BeautifulSoup

from kuleuven.exceptions import (
    AuthApprovalFailedError,
    AuthApprovalTimeoutError,
    AuthenticationError,
)

# Seconds to wait for the user to approve the push on their device, and the
# keepalive cadence the IdP's own page uses (nextauth-ws.js pings every 50s).
NEXTAUTH_APPROVAL_TIMEOUT = 120.0
NEXTAUTH_PING_INTERVAL = 50.0

IDP_ORIGIN = "https://idp.kuleuven.be"


@dataclass(frozen=True)
class NextauthDevice:
    account_id: str
    name: str
    last_login: str | None


@dataclass(frozen=True)
class NextauthWaitParams:
    server_id: str
    register_id: str
    host: str


def parse_device_picker(html: str) -> tuple[str, list[NextauthDevice]] | None:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="loginformnextauth")
    if form is None:
        form = next(
            (f for f in soup.find_all("form") if f.find("button", attrs={"data-account-id": True})),
            None,
        )
    if form is None:
        return None

    devices = []
    for button in form.find_all("button", attrs={"data-account-id": True}):
        # The "Last login at:" line sits in a sibling element that follows each
        # device button, up to the next button.
        last_login = None
        for sibling in button.find_next_siblings():
            if sibling.name == "button":
                break
            text = sibling.get_text(" ", strip=True)
            if "Last login at:" in text:
                last_login = text.split("Last login at:", 1)[1].strip() or None
                break
        devices.append(
            NextauthDevice(
                account_id=button["data-account-id"],
                name=button.get("data-device-name", button["data-account-id"]),
                last_login=last_login,
            )
        )

    if not devices:
        return None
    return form.get("action", ""), devices


# The device-picker page wires the WebSocket in its <body onload> via
# nextauthwsinit(serverid, registerid, knownstatus, host) — the last arg is the
# wss URL (HTML-entity-encoded in the attribute). See docs/AUTH.md §3.7.
_WSINIT_CALL = re.compile(
    r"nextauthwsinit\(\s*"
    r"(['\"])(?P<server>.*?)\1\s*,\s*"
    r"(['\"])(?P<register>.*?)\3\s*,\s*"
    r"(?P<known>[^,]*?)\s*,\s*"
    r"(['\"])(?P<host>.*?)\6\s*\)",
    re.DOTALL,
)


def parse_wait_params(html: str) -> NextauthWaitParams:
    match = _WSINIT_CALL.search(html)
    if match is None:
        raise AuthenticationError("could not parse nextauth WebSocket parameters")
    return NextauthWaitParams(
        server_id=unescape(match.group("server")),
        register_id=unescape(match.group("register")),
        host=unescape(match.group("host")),
    )


def send_push(http_client: httpx.Client, push_url: httpx.URL, account_id: str) -> str:
    # The push POST answers with JSON {url, error}, not a redirect. `url` is
    # where the continuation form must be submitted once the device approves.
    response = http_client.post(
        push_url,
        data={
            "nextauthAccountId": account_id,
            "_eventId_PushLoginOnAccount": "",
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise AuthApprovalFailedError(f"nextauth push rejected: {payload['error']}")
    continue_url = payload.get("url")
    if not continue_url:
        raise AuthenticationError("nextauth push response had no continuation url")
    return continue_url


def wait_for_approval(
    wait_params: NextauthWaitParams,
    timeout_seconds: float = NEXTAUTH_APPROVAL_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    connection = websocket.create_connection(
        wait_params.host,
        timeout=NEXTAUTH_PING_INTERVAL,
        origin=IDP_ORIGIN,
    )
    try:
        connection.send(f"REGISTER {wait_params.register_id} {wait_params.server_id}")
        last_ping = time.monotonic()
        while True:
            if time.monotonic() >= deadline:
                raise AuthApprovalTimeoutError(
                    f"no KU Leuven Authenticator approval within {int(timeout_seconds)}s"
                )
            try:
                message = connection.recv()
            except websocket.WebSocketTimeoutException:
                message = ""
            if isinstance(message, bytes):
                message = message.decode("utf-8", "replace")
            # Only LOGIN means "approved". The server also emits the current
            # status (LOGOUT) on connect and CONFIRMPROVOKE when the push is
            # delivered — both are progress, not the approval, so keep waiting.
            if message.startswith("LOGIN"):
                return
            if time.monotonic() - last_ping >= NEXTAUTH_PING_INTERVAL:
                connection.send("PING")
                last_ping = time.monotonic()
    except websocket.WebSocketException as error:
        raise AuthApprovalFailedError(f"WebSocket error during approval: {error}")
    finally:
        connection.close()


def complete_push_login(http_client: httpx.Client, continue_url: httpx.URL) -> httpx.Response:
    response = http_client.post(continue_url, data={"_eventId_proceed": ""})
    response.raise_for_status()
    return response
