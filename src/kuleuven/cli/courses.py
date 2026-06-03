from typing import Annotated

import httpx
import typer

from kuleuven.cli import storage
from kuleuven.cli.output import emit
from kuleuven.models import Course, Person
from kuleuven.session import KuleuvenSession
from kuleuven.toledo import ToledoClient

courses_app = typer.Typer(
    no_args_is_help=True,
    help="Browse and manage Toledo courses and communities",
)


def _http_error(error: Exception) -> None:
    emit({"status": "error", "code": "http_error", "message": str(error)}, exit_code=1)


def _expired(error: httpx.HTTPStatusError) -> bool:
    return error.response.status_code in (401, 403)


def _load_courses(session: KuleuvenSession, *, source: str) -> list[Course]:
    toledo = ToledoClient(session)
    try:
        if source == "portal":
            return toledo.list_portal_courses()
        return toledo.list_ultra_courses()
    except httpx.HTTPStatusError as error:
        if not _expired(error):
            _http_error(error)
        emit(
            {
                "status": "error",
                "code": "no_session",
                "message": "KU Leuven session expired; run `kuleuven session start`.",
            },
            exit_code=1,
        )
    except httpx.HTTPError as error:
        _http_error(error)


def _resolve_one(courses: list[Course], ref: str) -> Course:
    matches = ToledoClient.resolve(courses, ref)
    if not matches:
        emit(
            {
                "status": "error",
                "code": "not_found",
                "message": f"No course matches {ref!r}.",
            },
            exit_code=2,
        )
    if len(matches) > 1:
        emit(
            {
                "status": "error",
                "code": "ambiguous",
                "message": (
                    f"{len(matches)} courses match {ref!r}; "
                    "pass the full batchUid or BB pk to disambiguate."
                ),
                "candidates": [
                    {
                        "batch_uid": match.batch_uid,
                        "display_name": match.display_name,
                        "academic_year": match.academic_year,
                    }
                    for match in matches
                ],
            },
            exit_code=2,
        )
    return matches[0]


def resolve_with_pk(client: KuleuvenSession, ref: str) -> Course:
    # Resolve against the curated portal list first (29 active enrollments,
    # course-code disambiguation works), then merge in the Ultra membership
    # to obtain the Blackboard PK. Fall back to Ultra-only when the portal
    # doesn't surface the course (archived, hidden, ...).
    portal_courses = _load_courses(client, source="portal")
    ultra_courses = _load_courses(client, source="ultra")
    portal_matches = ToledoClient.resolve(portal_courses, ref)
    if not portal_matches:
        return _resolve_one(ultra_courses, ref)
    course = (
        portal_matches[0]
        if len(portal_matches) == 1
        else _resolve_one(portal_courses, ref)
    )
    ultra_match = next(
        (item for item in ultra_courses if item.batch_uid == course.batch_uid), None
    )
    if ultra_match is not None:
        return course.merge(ultra_match)
    emit(
        {
            "status": "error",
            "code": "no_ultra_mapping",
            "message": (
                f"Could not resolve {course.batch_uid} to a Blackboard PK; "
                "the course may not be available in Ultra."
            ),
        },
        exit_code=1,
    )


@courses_app.command("list")
def list_command(
    ctx: typer.Context,
    favorite: Annotated[
        bool, typer.Option("--favorite", help="Only courses marked as favourite")
    ] = False,
    course_type: Annotated[
        str | None,
        typer.Option("--type", help="Filter by type, e.g. course or community"),
    ] = None,
    semester: Annotated[
        str | None,
        typer.Option(
            "--semester", help="Filter by semester (SEMESTER1, SEMESTER2, UNKNOWN)"
        ),
    ] = None,
    year: Annotated[
        int | None,
        typer.Option(
            "--year", help="Filter by academic year code, e.g. 2526 for 2025/2026"
        ),
    ] = None,
    all_memberships: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Use Ultra memberships instead of the portal — includes archived and hidden entries.",
        ),
    ] = False,
) -> None:
    """List the user's courses and communities."""
    client: KuleuvenSession = ctx.obj
    courses = _load_courses(client, source="ultra" if all_memberships else "portal")
    storage.save_cookies(client.http_client)

    filtered = courses
    if favorite:
        filtered = [item for item in filtered if item.favorite]
    if course_type is not None:
        filtered = [item for item in filtered if item.type == course_type]
    if semester is not None:
        filtered = [item for item in filtered if item.semester == semester]
    if year is not None:
        filtered = [item for item in filtered if item.academic_year == year]

    emit(
        {
            "status": "ok",
            "count": len(filtered),
            "items": filtered,
        }
    )


def _resolve_for_show(
    portal_courses: list[Course], ultra_courses: list[Course], ref: str
) -> Course:
    matches = ToledoClient.resolve(portal_courses, ref)
    if not matches:
        return _resolve_one(ultra_courses, ref)
    course = matches[0] if len(matches) == 1 else _resolve_one(portal_courses, ref)
    ultra_match = next(
        (item for item in ultra_courses if item.batch_uid == course.batch_uid), None
    )
    if ultra_match is None:
        return course
    return course.merge(ultra_match)


def _merge_instructors(
    portal_instructors: list[Person], ultra_instructors: list[Person]
) -> list[Person]:
    if not ultra_instructors:
        return portal_instructors
    by_q_uid: dict[str | None, Person] = {p.q_uid: p for p in portal_instructors}
    for person in ultra_instructors:
        by_q_uid[person.q_uid] = person
    return list(by_q_uid.values())


@courses_app.command("show")
def show_command(
    ctx: typer.Context,
    ref: Annotated[
        str,
        typer.Argument(
            help="Course code, batchUid, Blackboard PK, portal UUID, or course UUID"
        ),
    ],
) -> None:
    """Show one course with portal + ultra details, instructors, and admin URLs."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    portal_courses = _load_courses(session, source="portal")
    ultra_courses = _load_courses(session, source="ultra")
    merged = _resolve_for_show(portal_courses, ultra_courses, ref)

    portal_detail = None
    try:
        portal_detail = toledo.fetch_portal_detail(merged.batch_uid)
    except httpx.HTTPStatusError:
        portal_detail = None
    except httpx.HTTPError as error:
        _http_error(error)

    ultra_detail = None
    if merged.pk is not None:
        try:
            ultra_detail = toledo.fetch_ultra_course(merged.pk)
        except httpx.HTTPError as error:
            _http_error(error)
        merged = merged.merge(ultra_detail.course)

    storage.save_cookies(session.http_client)

    portal_instructors = portal_detail.instructors if portal_detail else []
    ultra_instructors = ultra_detail.instructors if ultra_detail else []
    instructors = _merge_instructors(portal_instructors, ultra_instructors)

    payload = merged.model_dump(mode="json")
    payload["description"] = merged.description or (
        portal_detail.description if portal_detail else None
    )
    payload["instructors"] = instructors
    payload["admin_urls"] = (
        portal_detail.admin_urls.model_dump(mode="json", exclude_none=True)
        if portal_detail
        else {}
    )
    emit({"status": "ok", "course": payload})


@courses_app.command("favorite")
def favorite_command(
    ctx: typer.Context,
    ref: Annotated[
        str,
        typer.Argument(help="Course code, batchUid, or portal UUID"),
    ],
    off: Annotated[
        bool, typer.Option("--off", help="Unfavourite instead of favourite")
    ] = False,
) -> None:
    """Pin or unpin a course on the portal dashboard."""
    session: KuleuvenSession = ctx.obj
    portal_courses = _load_courses(session, source="portal")
    course = _resolve_one(portal_courses, ref)
    if course.portal_uuid is None:
        emit(
            {
                "status": "error",
                "code": "not_in_portal",
                "message": (
                    f"{course.batch_uid} is not in the portal enrollment list; "
                    "only portal-visible courses can be favourited."
                ),
            },
            exit_code=2,
        )
    target = not off
    try:
        ToledoClient(session).set_favorite(course.portal_uuid, target)
    except httpx.HTTPError as error:
        _http_error(error)
    storage.save_cookies(session.http_client)

    emit(
        {
            "status": "ok",
            "course": {
                "portal_uuid": course.portal_uuid,
                "batch_uid": course.batch_uid,
                "display_name": course.display_name,
                "favorite": target,
            },
        }
    )


@courses_app.command("members")
def members_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    role_bucket: Annotated[
        str | None,
        typer.Option(
            "--role-bucket",
            help="Filter by Ultra's role bucket (e.g. TEACHING, LEARNING); passed through verbatim",
        ),
    ] = None,
    available: Annotated[
        bool,
        typer.Option(
            "--available/--all-members",
            help="Only available memberships (the default) or include disabled ones",
        ),
    ] = True,
) -> None:
    """List members of a course, optionally filtered by role bucket."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)

    try:
        memberships = toledo.fetch_members(
            course.pk,
            role_bucket=role_bucket,
            available=available,
        )
        counts = toledo.fetch_member_counts(course.pk)
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
            "counts": counts.results,
            "total": counts.count,
            "count": len(memberships),
            "items": memberships,
        }
    )


@courses_app.command("announcements")
def announcements_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    unread: Annotated[
        bool,
        typer.Option("--unread", help="Only announcements the user has not read yet"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of announcements to fetch"),
    ] = 100,
) -> None:
    """List announcements for a course, with bodies rendered as markdown."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        announcements = toledo.fetch_announcements(course.pk, limit=limit)
        counts = toledo.fetch_announcement_counts(course.pk)
    except httpx.HTTPError as error:
        _http_error(error)
    storage.save_cookies(session.http_client)

    selected = (
        [item for item in announcements if item.is_read is False]
        if unread
        else announcements
    )

    items = []
    for announcement in selected:
        record = announcement.model_dump(mode="json")
        record["body"] = ToledoClient.render_markdown(announcement.body_html)
        items.append(record)

    emit(
        {
            "status": "ok",
            "course": {
                "pk": course.pk,
                "batch_uid": course.batch_uid,
                "display_name": course.display_name,
            },
            "counts": counts,
            "count": len(items),
            "items": items,
        }
    )


@courses_app.command("schedule")
def schedule_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    start: Annotated[
        str | None,
        typer.Option("--from", help="ISO timestamp; inclusive start of window"),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option("--to", help="ISO timestamp; exclusive end of window"),
    ] = None,
) -> None:
    """Show the per-course calendar. Often empty — `/portal/api/upcoming` is the user-wide source."""
    session: KuleuvenSession = ctx.obj
    course = resolve_with_pk(session, ref)
    try:
        items = ToledoClient(session).fetch_schedule(course.pk, start=start, end=end)
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
            "items": items,
        }
    )


@courses_app.command("grades")
def grades_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    user: Annotated[
        str | None,
        typer.Option(
            "--user",
            help="Blackboard user pk; defaults to the signed-in user. Most accounts can only query themselves.",
        ),
    ] = None,
) -> None:
    """List per-item grades for a user in this course (the caller by default)."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        user_pk = user or toledo.fetch_user_pk()
        items = toledo.fetch_user_grades(course.pk, user_pk)
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
            "user_pk": user_pk,
            "count": len(items),
            "items": items,
        }
    )
