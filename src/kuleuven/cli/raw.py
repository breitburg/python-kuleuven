from typing import Annotated

import httpx
import typer

from kuleuven.cli import storage
from kuleuven.cli.output import emit
from kuleuven.session import KuleuvenSession


def _summarize_response(response: httpx.Response) -> dict:
    content_type = response.headers.get("content-type", "")
    summary: dict = {
        "status_code": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
    }
    if content_type.startswith("application/json"):
        try:
            summary["body"] = response.json()
            summary["body_kind"] = "json"
            return summary
        except ValueError:
            summary["body"] = response.text
            summary["body_kind"] = "text"
            return summary
    if content_type.startswith("text/") or "xml" in content_type:
        summary["body"] = response.text
        summary["body_kind"] = "text"
        return summary
    summary["body_kind"] = "binary"
    summary["size"] = len(response.content)
    return summary


def raw(
    ctx: typer.Context,
    method: Annotated[str, typer.Argument(help="HTTP method (GET, POST, PATCH, ...)")],
    url: Annotated[str, typer.Argument(help="Absolute URL to request")],
    body: Annotated[
        str | None,
        typer.Option("--body", help="Request body, sent as application/json"),
    ] = None,
) -> None:
    """Send a pre-authenticated HTTP request to any URL and print the response as JSON."""
    session: KuleuvenSession = ctx.obj
    request_kwargs: dict = {}
    if body is not None:
        request_kwargs["content"] = body
        request_kwargs["headers"] = {"Content-Type": "application/json"}

    try:
        response = session.http_client.request(method.upper(), url, **request_kwargs)
    except httpx.HTTPError as error:
        emit(
            {"status": "error", "code": "http_error", "message": str(error)},
            exit_code=1,
        )

    storage.save_cookies(session.http_client)
    emit({"status": "ok", "response": _summarize_response(response)})
