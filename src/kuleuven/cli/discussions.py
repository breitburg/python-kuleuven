from typing import Annotated

import httpx
import typer

from kuleuven.cli import storage
from kuleuven.cli.courses import resolve_with_pk
from kuleuven.cli.output import emit
from kuleuven.models import DiscussionItem
from kuleuven.session import KuleuvenSession
from kuleuven.toledo import ToledoClient

discussions_app = typer.Typer(
    no_args_is_help=True,
    help="Browse discussion forums and threads in a course",
)


def _http_error(error: Exception) -> None:
    emit({"status": "error", "code": "http_error", "message": str(error)}, exit_code=1)


def _summary(item: DiscussionItem) -> dict:
    # The /contents/INTERACTIVE/children record is wide; lift the fields
    # callers actually want into a flat shape.
    raw = item.model_dump()
    detail = (raw.get("contentDetail") or {}).get("resource/x-bb-forumlink") or {}
    generic = raw.get("genericReadOnlyData") or {}
    return {
        "content_id": raw.get("id"),
        "forum_id": detail.get("id"),
        "conference_id": detail.get("conferenceId"),
        "title": raw.get("title"),
        "due_date": generic.get("dueDate"),
        "modified_date": raw.get("modifiedDate"),
        "visibility": raw.get("visibility"),
        "has_grade_column": generic.get("hasGradeColumn"),
        "has_participation_requirements": detail.get("hasParticipationRequirements"),
        "is_created_by_student": detail.get("isDiscussionCreatedByStudent"),
        "is_group_content": raw.get("isGroupContent"),
        "web_location": (raw.get("body") or {}).get("webLocation"),
    }


@discussions_app.command("list")
def list_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
) -> None:
    """List all discussion forums in a course."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        items = toledo.list_discussions(course.pk)
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
            "count": len(items),
            "items": [_summary(item) for item in items],
        }
    )


@discussions_app.command("show")
def show_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    forum_id: Annotated[
        str,
        typer.Argument(
            help="Forum id from `discussions list` (the `forum_id` field, e.g. `_99089_1`)"
        ),
    ],
) -> None:
    """Show a forum's metadata, read/reply counts, and top-level messages."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        forum = toledo.fetch_forum(course.pk, forum_id)
        counts = toledo.fetch_forum_counts(course.pk, forum_id)
        messages = toledo.list_forum_messages(course.pk, forum_id)
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
            "forum": forum,
            "counts": counts,
            "messages": messages,
        }
    )


@discussions_app.command("replies")
def replies_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    forum_id: Annotated[str, typer.Argument(help="Forum id (e.g. `_99089_1`)")],
    message_id: Annotated[
        str,
        typer.Argument(
            help="Message id from `discussions show` (e.g. the root message's `id`)"
        ),
    ],
    limit: Annotated[int, typer.Option("--limit")] = 100,
    offset: Annotated[int, typer.Option("--offset")] = 0,
) -> None:
    """List replies to one message in a forum, in BB's default sort order."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        page = toledo.list_message_replies(
            course.pk, forum_id, message_id, limit=limit, offset=offset
        )
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
            "total": page.paging.count,
            "offset": page.paging.offset,
            "limit": page.paging.limit,
            "next_page": page.paging.next_page,
            "items": page.results,
        }
    )
