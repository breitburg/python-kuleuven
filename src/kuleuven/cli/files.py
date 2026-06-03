import json
import re
import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer

from kuleuven.cli import storage
from kuleuven.cli.courses import resolve_with_pk
from kuleuven.cli.output import emit
from kuleuven.models import FileItem
from kuleuven.session import KuleuvenSession
from kuleuven.toledo import ToledoClient

files_app = typer.Typer(
    no_args_is_help=True, help="Discover and download files and videos from a course"
)

_UNSAFE_PATH_CHARACTERS = re.compile(r"[\x00-\x1f<>:\"/\\|?*]")


def _http_error(error: Exception) -> None:
    emit({"status": "error", "code": "http_error", "message": str(error)}, exit_code=1)


def _safe_path_segment(value: str) -> str:
    # Strip the few characters that break Linux / macOS / Windows filesystems
    # and collapse whitespace so paths like "Lecture 1 / Slides" don't end up
    # with stray leading or trailing spaces in directory names.
    return _UNSAFE_PATH_CHARACTERS.sub("_", value).strip() or "untitled"


def _safe_source_path(source_path: list[str]) -> Path:
    parts = [_safe_path_segment(segment) for segment in source_path if segment]
    if not parts:
        return Path()
    return Path(*parts)


def _default_filename(item: FileItem) -> str:
    if item.filename:
        return item.filename
    if item.kind == "video":
        return f"{item.title or item.id}.mp4"
    return item.title or item.id


def _course_dict(course) -> dict:
    return {
        "pk": course.pk,
        "batch_uid": course.batch_uid,
        "display_name": course.display_name,
    }


def _resolve_filename(item: FileItem, server_filename: str | None) -> str:
    return server_filename or item.filename or item.title or item.id


@files_app.command("list")
def list_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
) -> None:
    """List every downloadable in a course — files, document-embedded attachments, and Kaltura videos."""
    session: KuleuvenSession = ctx.obj
    course = resolve_with_pk(session, ref)
    try:
        items = ToledoClient(session).discover_files(course.pk)
    except httpx.HTTPError as error:
        _http_error(error)
    storage.save_cookies(session.http_client)
    emit(
        {
            "status": "ok",
            "course": _course_dict(course),
            "count": len(items),
            "items": items,
        }
    )


@files_app.command("fetch")
def fetch_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    file_id: Annotated[
        str,
        typer.Argument(
            help="File identifier from `toledo courses files list` — a content PK or <content_pk>@<embed_index>"
        ),
    ],
    out: Annotated[
        str | None,
        typer.Option(
            "--out",
            help=(
                "Output path. Accepts a file path, an existing directory "
                "(the default filename is appended), or `-` to stream the "
                "raw bytes to stdout. Defaults to the filename in the cwd."
            ),
        ),
    ] = None,
) -> None:
    """Download one file or video to disk, into a directory, or to stdout."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        items = toledo.discover_files(course.pk)
    except httpx.HTTPError as error:
        _http_error(error)
    item = ToledoClient.find_item(items, file_id)
    if item is None:
        emit(
            {
                "status": "error",
                "code": "not_found",
                "message": f"No file matches {file_id!r}; check `toledo courses files list` output.",
            },
            exit_code=2,
        )

    if out == "-":
        try:
            written, _ = toledo.stream_file_item(item, sys.stdout.buffer)
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "code": "download_failed",
                        "message": str(error),
                    }
                ),
                file=sys.stderr,
            )
            raise typer.Exit(code=1)
        sys.stdout.buffer.flush()
        storage.save_cookies(session.http_client)
        raise typer.Exit(code=0)

    out_path = Path(out) if out is not None else None
    if out_path is None:
        dest = Path(_safe_path_segment(_default_filename(item)))
    elif out_path.is_dir():
        dest = out_path / _safe_path_segment(_default_filename(item))
    else:
        dest = out_path

    try:
        result = toledo.download_file_item(item, dest)
    except httpx.HTTPError as error:
        _http_error(error)
    except (RuntimeError, ValueError) as error:
        emit(
            {"status": "error", "code": "download_failed", "message": str(error)},
            exit_code=1,
        )
    storage.save_cookies(session.http_client)

    final_filename = _resolve_filename(item, result.server_filename)
    if result.server_filename and out_path is None:
        renamed = Path(_safe_path_segment(final_filename))
        if renamed != dest:
            dest.replace(renamed)
            result.path = str(renamed)

    emit(
        {
            "status": "ok",
            "course": _course_dict(course),
            "item": item,
            "download": result,
        }
    )


@files_app.command("resolve")
def resolve_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    file_id: Annotated[
        str,
        typer.Argument(
            help="File identifier from `toledo courses files list` — a content PK or <content_pk>@<embed_index>"
        ),
    ],
) -> None:
    """Resolve a short-lived, standalone-fetchable download URL for one file or video.

    For Blackboard files, follows the bbcswebdav redirect chain to the signed S3
    URL. For Kaltura videos, returns the CDN download URL. The returned URL can
    be fetched by anyone without further authentication until it expires.
    """
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        items = toledo.discover_files(course.pk)
    except httpx.HTTPError as error:
        _http_error(error)
    item = ToledoClient.find_item(items, file_id)
    if item is None:
        emit(
            {
                "status": "error",
                "code": "not_found",
                "message": f"No file matches {file_id!r}; check `toledo courses files list` output.",
            },
            exit_code=2,
        )

    try:
        url = toledo.resolve_signed_url(item)
    except httpx.HTTPError as error:
        _http_error(error)
    except (RuntimeError, ValueError) as error:
        emit(
            {"status": "error", "code": "resolve_failed", "message": str(error)},
            exit_code=1,
        )
    storage.save_cookies(session.http_client)

    emit(
        {
            "status": "ok",
            "course": _course_dict(course),
            "item": item,
            "url": url,
        }
    )


@files_app.command("sync")
def sync_command(
    ctx: typer.Context,
    ref: Annotated[
        str, typer.Argument(help="Course code, batchUid, BB pk, or portal UUID")
    ],
    into: Annotated[
        Path,
        typer.Option(
            "--into", help="Destination directory; defaults to the course code or batchUid"
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Plan the downloads without writing anything to disk"
        ),
    ] = False,
    skip_videos: Annotated[
        bool,
        typer.Option(
            "--skip-videos",
            help="Skip Kaltura video downloads; useful when bandwidth is limited",
        ),
    ] = False,
) -> None:
    """Bulk-download every file and video in a course, mirroring the content tree on disk."""
    session: KuleuvenSession = ctx.obj
    toledo = ToledoClient(session)
    course = resolve_with_pk(session, ref)
    try:
        items = toledo.discover_files(course.pk)
    except httpx.HTTPError as error:
        _http_error(error)
    storage.save_cookies(session.http_client)

    destination_root = into if into is not None else Path(
        _safe_path_segment(course.course_code or course.batch_uid)
    )

    plan = []
    skipped = []
    for item in items:
        if item.kind == "video" and skip_videos:
            skipped.append({"id": item.id, "reason": "skip_videos"})
            continue
        source_dir = _safe_source_path(item.source_path or [])
        target = destination_root / source_dir / _safe_path_segment(_default_filename(item))
        plan.append({"id": item.id, "kind": item.kind, "target": target, "item": item})

    if dry_run:
        emit(
            {
                "status": "ok",
                "course": _course_dict(course),
                "destination": str(destination_root),
                "count": len(plan),
                "skipped": skipped,
                "items": [
                    {
                        "id": entry["id"],
                        "kind": entry["kind"],
                        "target": str(entry["target"]),
                    }
                    for entry in plan
                ],
            }
        )

    results: list[dict] = []
    failures: list[dict] = []
    for entry in plan:
        item: FileItem = entry["item"]
        target: Path = entry["target"]
        if target.exists() and target.stat().st_size > 0:
            results.append({"id": item.id, "target": str(target), "status": "exists"})
            continue
        try:
            outcome = toledo.download_file_item(item, target)
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            failures.append({"id": item.id, "target": str(target), "error": str(error)})
            continue
        # Intentionally do not rename to the server-supplied filename: the
        # embed's linkName is the authoritative on-disk name, and renaming
        # would make subsequent syncs see a missing target and re-download.
        results.append(
            {
                "id": item.id,
                "target": outcome.path or str(target),
                "bytes": outcome.bytes,
                "status": "downloaded",
            }
        )

    storage.save_cookies(session.http_client)
    emit(
        {
            "status": "ok" if not failures else "partial",
            "course": _course_dict(course),
            "destination": str(destination_root),
            "downloaded": sum(1 for r in results if r["status"] == "downloaded"),
            "existing": sum(1 for r in results if r["status"] == "exists"),
            "skipped": skipped,
            "failures": failures,
            "items": results,
        }
    )
