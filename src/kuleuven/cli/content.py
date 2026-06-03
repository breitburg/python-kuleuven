from typing import Annotated

import httpx
import typer

from kuleuven.cli import storage
from kuleuven.cli.courses import resolve_with_pk
from kuleuven.cli.output import emit
from kuleuven.models import ContentItem
from kuleuven.session import KuleuvenSession
from kuleuven.toledo import ToledoClient

content_app = typer.Typer(
    no_args_is_help=True, help="Browse course content trees and items"
)


def _http_error(error: Exception) -> None:
    emit({"status": "error", "code": "http_error", "message": str(error)}, exit_code=1)


def _summarize_item(item: ContentItem) -> dict:
    # Lift the fields callers commonly want into a flat, snake_case shape and
    # keep the handler-specific contentDetail blob under `detail` so handler
    # variants aren't enumerated here.
    return {
        "id": item.id,
        "parent_id": item.parent_id,
        "title": item.title,
        "handler": item.content_handler,
        "is_bb_page": ToledoClient.is_bb_page(item),
        "visibility": item.visibility,
        "modified_date": item.modified_date,
        "position": item.position,
        "description": item.description or None,
        "state": item.state,
        "detail": item.content_detail or {},
    }


@content_app.command("tree")
def tree_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    depth: Annotated[
        int | None,
        typer.Option("--depth", help="Maximum recursion depth; unlimited if omitted"),
    ] = None,
) -> None:
    """Walk the content tree of a course. One CLI call, many HTTP calls."""
    session: KuleuvenSession = ctx.obj
    course = resolve_with_pk(session, ref)
    try:
        nodes = list(ToledoClient(session).walk_contents(course.pk, max_depth=depth))
    except httpx.HTTPError as error:
        _http_error(error)
    storage.save_cookies(session.http_client)

    emit(
        {
            "status": "ok",
            "course": {
                "pk": course.pk,
                "batch_uid": course.batch_uid,
                "display_name": course.display_name,
            },
            "count": len(nodes),
            "items": nodes,
        }
    )


@content_app.command("show")
def show_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    content_id: Annotated[
        str, typer.Argument(help="Blackboard content PK, e.g. _8676389_1")
    ],
) -> None:
    """Show a content item's metadata, plus body markdown and embeds for documents."""
    session: KuleuvenSession = ctx.obj
    course = resolve_with_pk(session, ref)
    try:
        result = ToledoClient(session).fetch_body_and_embeds(course.pk, content_id)
    except httpx.HTTPError as error:
        _http_error(error)
    storage.save_cookies(session.http_client)

    item = _summarize_item(result.original)
    if result.markdown:
        item["body"] = result.markdown
    if result.embeds:
        item["embeds"] = result.embeds
    emit(
        {
            "status": "ok",
            "course": {
                "pk": course.pk,
                "batch_uid": course.batch_uid,
                "display_name": course.display_name,
            },
            "item": item,
        }
    )


@content_app.command("embeds")
def embeds_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    content_id: Annotated[
        str, typer.Argument(help="Blackboard content PK, e.g. _8676389_1")
    ],
) -> None:
    """List embedded files and LTI launches inside a document body."""
    session: KuleuvenSession = ctx.obj
    course = resolve_with_pk(session, ref)
    try:
        result = ToledoClient(session).fetch_body_and_embeds(course.pk, content_id)
    except httpx.HTTPError as error:
        _http_error(error)
    storage.save_cookies(session.http_client)
    emit(
        {
            "status": "ok",
            "count": len(result.embeds),
            "items": result.embeds,
        }
    )
