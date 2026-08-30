import sys
from datetime import UTC, datetime
from typing import Annotated

import httpx
import typer

from kuleuven.cli import storage
from kuleuven.cli.output import emit
from kuleuven.nextauth import NextauthDevice
from kuleuven.session import KuleuvenSession
from kuleuven.exceptions import (
    AuthApprovalTimeoutError,
    AuthenticationError,
    InvalidCredentialsError,
)

session_app = typer.Typer(no_args_is_help=True, help="Manage your KU Leuven session")


class CliAuthenticationProvider:
    def __init__(self, totp: str | None, device: str) -> None:
        self.totp = totp
        self.device = device

    def provide_totp(self) -> str:
        if self.totp:
            return self.totp
        if sys.stdin.isatty():
            return typer.prompt("TOTP code")
        emit(
            {
                "status": "error",
                "code": "totp_required",
                "message": "IdP demands TOTP; set KULEUVEN_TOTP or pass --totp.",
            },
            exit_code=1,
        )

    def select_device(self, devices: list[NextauthDevice]) -> NextauthDevice:
        chosen = self._match_device(devices)
        if chosen is None:
            emit(
                {
                    "status": "error",
                    "code": "unknown_device",
                    "message": f"No KU Leuven Authenticator device matches {self.device!r}.",
                    "devices": [_device_summary(device) for device in devices],
                },
                exit_code=2,
            )
        return chosen

    def awaiting_approval(self, device_name: str) -> None:
        print(f"Waiting for approval on {device_name}...", file=sys.stderr)

    def _match_device(self, devices: list[NextauthDevice]) -> NextauthDevice | None:
        if self.device == "most-recent":
            return max(devices, key=_recency_key)
        if self.device.isdigit():
            index = int(self.device) - 1
            if 0 <= index < len(devices):
                return devices[index]
            return None
        for device in devices:
            if device.name.casefold() == self.device.casefold():
                return device
        return None


def _recency_key(device: NextauthDevice) -> datetime:
    # A device that has never logged in (no timestamp) sorts oldest.
    return device.last_login or datetime.min.replace(tzinfo=UTC)


def _device_summary(device: NextauthDevice) -> dict:
    return {"name": device.name, "last_login": device.last_login}


@session_app.command()
def start(
    ctx: typer.Context,
    username: Annotated[str | None, typer.Option(envvar="KULEUVEN_USERNAME")] = None,
    password: Annotated[str | None, typer.Option(envvar="KULEUVEN_PASSWORD")] = None,
    totp: Annotated[
        str | None,
        typer.Option(
            envvar="KULEUVEN_TOTP",
            help="6-digit TOTP code; prompted if needed and not provided",
        ),
    ] = None,
    device: Annotated[
        str,
        typer.Option(
            envvar="KULEUVEN_AUTH_DEVICE",
            help='KU Leuven Authenticator device name, 1-based index, or "most-recent"',
        ),
    ] = "most-recent",
) -> None:
    """Authenticate and persist a new KU Leuven session."""
    if not username and sys.stdin.isatty():
        username = typer.prompt("Username")
    if not password and sys.stdin.isatty():
        password = typer.prompt("Password", hide_input=True)
    if not username or not password:
        missing = [
            name
            for name, value in [("username", username), ("password", password)]
            if not value
        ]
        emit(
            {
                "status": "error",
                "code": "missing_credentials",
                "message": f"Missing {', '.join(missing)}. Set KULEUVEN_USERNAME/KULEUVEN_PASSWORD or pass --username/--password.",
            },
            exit_code=2,
        )

    provider = CliAuthenticationProvider(totp=totp, device=device)

    client: KuleuvenSession = ctx.obj
    try:
        client.sign_in(username, password, provider)
    except InvalidCredentialsError as error:
        emit(
            {"status": "error", "code": "invalid_credentials", "message": str(error)},
            exit_code=1,
        )
    except AuthApprovalTimeoutError as error:
        emit(
            {"status": "error", "code": "approval_timeout", "message": str(error)},
            exit_code=1,
        )
    except AuthenticationError as error:
        emit(
            {"status": "error", "code": "auth_failed", "message": str(error)},
            exit_code=1,
        )
    except httpx.HTTPError as error:
        emit(
            {"status": "error", "code": "http_error", "message": str(error)},
            exit_code=1,
        )

    storage.save_cookies(client.http_client)
    emit({"status": "ok", "session": client.session_info()})


@session_app.command()
def status(ctx: typer.Context) -> None:
    """Report whether a valid KU Leuven session exists."""
    if not storage.cookies_path().exists():
        emit({"authenticated": False, "reason": "no_session"}, exit_code=1)

    client: KuleuvenSession = ctx.obj
    info = client.session_info()
    if info is None:
        emit({"authenticated": False, "reason": "expired"}, exit_code=1)
    emit({"authenticated": True, "session": info})


@session_app.command()
def end() -> None:
    """Delete the persisted KU Leuven session."""
    removed = storage.clear_cookies()
    emit({"status": "ok", "removed": removed})
