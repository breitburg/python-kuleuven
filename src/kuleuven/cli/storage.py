import http.cookiejar
import json
import os
from pathlib import Path

import httpx
import platformdirs


def cookies_path() -> Path:
    return platformdirs.user_data_path("kuleuven") / "cookies.json"


def load_cookies(http_client: httpx.Client) -> None:
    path = cookies_path()
    if not path.exists():
        return
    for entry in json.loads(path.read_text()):
        http_client.cookies.jar.set_cookie(
            http.cookiejar.Cookie(
                version=0,
                name=entry["name"],
                value=entry["value"],
                port=None,
                port_specified=False,
                domain=entry["domain"],
                domain_specified=bool(entry["domain"]),
                domain_initial_dot=entry["domain"].startswith("."),
                path=entry["path"],
                path_specified=bool(entry["path"]),
                secure=entry["secure"],
                expires=entry["expires"],
                discard=False,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )


def save_cookies(http_client: httpx.Client) -> None:
    path = cookies_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(
        json.dumps(
            [
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "expires": cookie.expires,
                    "secure": cookie.secure,
                }
                for cookie in http_client.cookies.jar
            ]
        )
    )
    os.chmod(path, 0o600)


def clear_cookies() -> bool:
    path = cookies_path()
    if not path.exists():
        return False
    path.unlink()
    return True
