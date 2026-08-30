from datetime import date, time
from typing import Annotated

import httpx
import typer

from kuleuven.cli import storage
from kuleuven.cli.output import emit
from kuleuven.exceptions import SessionExpiredError
from kuleuven.kurt import KurtClient

kurt_app = typer.Typer(
    no_args_is_help=True,
    help="KU Leuven KURT study-space reservations",
)
locations_app = typer.Typer(no_args_is_help=True, help="Browse KURT locations")
resources_app = typer.Typer(no_args_is_help=True, help="Search, book, and manage KURT resources")
kurt_app.add_typer(locations_app, name="locations")
kurt_app.add_typer(resources_app, name="resources")


def _client(ctx: typer.Context) -> KurtClient:
    return KurtClient(ctx.obj)


def _http_error(error: httpx.HTTPError) -> None:
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
        emit(
            {
                "status": "error",
                "code": "no_session",
                "message": "KURT session expired; run `kuleuven session start`.",
            },
            exit_code=1,
        )
    emit({"status": "error", "code": "http_error", "message": str(error)}, exit_code=1)


def _run(client: KurtClient, call):
    try:
        return call()
    except SessionExpiredError as error:
        emit(
            {"status": "error", "code": "no_session", "message": str(error)},
            exit_code=1,
        )
    except httpx.HTTPError as error:
        _http_error(error)


@locations_app.command("list")
def locations_list_command(ctx: typer.Context) -> None:
    """List all KURT tiles (cities) and the locations under each."""
    client = _client(ctx)
    tiles = _run(client, client.list_tiles)
    storage.save_cookies(client.http_client)
    emit({"status": "ok", "count": len(tiles), "tiles": tiles})


@locations_app.command("show")
def locations_show_command(
    ctx: typer.Context,
    location_id: Annotated[int, typer.Argument(help="Numeric location id from `locations list`")],
    occupancy: Annotated[
        bool,
        typer.Option("--occupancy/--no-occupancy", help="Include current occupancy"),
    ] = True,
) -> None:
    """Show one location with its zones and bookable resource types."""
    client = _client(ctx)
    detail = _run(client, lambda: client.get_location(location_id))
    resource_types = _run(client, lambda: client.list_resource_types(location_id))
    occupancy_payload = (
        _run(client, lambda: client.get_occupancy(location_id)) if occupancy else None
    )
    storage.save_cookies(client.http_client)
    emit(
        {
            "status": "ok",
            "location": detail,
            "resource_types": resource_types,
            "occupancy": occupancy_payload,
        }
    )


@resources_app.command("quotas")
def resources_quotas_command(ctx: typer.Context) -> None:
    """Show per-resource-type usage and limits for the signed-in user."""
    client = _client(ctx)
    account = _run(client, client.get_account)
    storage.save_cookies(client.http_client)
    emit({"status": "ok", "quotas": account.quota})


@resources_app.command("favorites")
def resources_favorites_command(ctx: typer.Context) -> None:
    """List the user's favourited resources."""
    client = _client(ctx)
    items = _run(client, client.list_favorites)
    storage.save_cookies(client.http_client)
    emit({"status": "ok", "count": len(items), "items": items})


@resources_app.command("search")
def resources_search_command(
    ctx: typer.Context,
    location_id: Annotated[int, typer.Option("--location", help="Location id")],
    resource_type_id: Annotated[int, typer.Option("--type", help="Resource type id")],
    start_date: Annotated[
        date,
        typer.Option(
            "--date",
            parser=date.fromisoformat,
            metavar="YYYY-MM-DD",
            help="Day to search, YYYY-MM-DD",
        ),
    ],
    end_date: Annotated[
        date | None,
        typer.Option(
            "--end-date",
            parser=date.fromisoformat,
            metavar="YYYY-MM-DD",
            help="Last day of the window, YYYY-MM-DD; defaults to --date",
        ),
    ] = None,
    start_time: Annotated[
        time | None,
        typer.Option(
            "--start",
            parser=time.fromisoformat,
            metavar="HH:MM",
            help="Earliest start time, HH:MM; omit for any",
        ),
    ] = None,
    end_time: Annotated[
        time | None,
        typer.Option(
            "--end",
            parser=time.fromisoformat,
            metavar="HH:MM",
            help="Latest end time, HH:MM; omit for any",
        ),
    ] = None,
    zone_id: Annotated[int, typer.Option("--zone", help="Zone id, -1 for any")] = -1,
    participants: Annotated[int, typer.Option("--participants")] = 1,
    only_favorites: Annotated[bool, typer.Option("--only-favorites")] = False,
    name_contains: Annotated[str, typer.Option("--name", help="Substring filter")] = "",
) -> None:
    """Search bookable resources at a location."""
    client = _client(ctx)
    payload = _run(
        client,
        lambda: client.search_availability(
            location_id=location_id,
            resource_type_id=resource_type_id,
            start_date=start_date,
            end_date=end_date or start_date,
            start_time=start_time,
            end_time=end_time,
            zone_id=zone_id,
            participant_count=participants,
            only_favorites=only_favorites,
            resource_name_infix=name_contains,
        ),
    )
    storage.save_cookies(client.http_client)
    emit(
        {
            "status": "ok",
            "count": len(payload.availabilities),
            "message": payload.message,
            "items": payload.availabilities,
        }
    )


@resources_app.command("reservations")
def resources_reservations_command(
    ctx: typer.Context,
    only_today: Annotated[bool, typer.Option("--today")] = False,
) -> None:
    """List your KURT reservations."""
    client = _client(ctx)
    items = _run(client, lambda: client.list_reservations(only_today=only_today))
    storage.save_cookies(client.http_client)
    emit({"status": "ok", "count": len(items), "items": items})


@resources_app.command("book")
def resources_book_command(
    ctx: typer.Context,
    resource_id: Annotated[int, typer.Option("--resource", help="Resource id to book")],
    start_date: Annotated[
        date,
        typer.Option(
            "--date",
            parser=date.fromisoformat,
            metavar="YYYY-MM-DD",
            help="Day to book, YYYY-MM-DD",
        ),
    ],
    start_time: Annotated[
        time,
        typer.Option(
            "--start",
            parser=time.fromisoformat,
            metavar="HH:MM",
            help="Start time, HH:MM",
        ),
    ],
    end_time: Annotated[
        time,
        typer.Option(
            "--end",
            parser=time.fromisoformat,
            metavar="HH:MM",
            help="End time, HH:MM",
        ),
    ],
    end_date: Annotated[
        date | None,
        typer.Option(
            "--end-date",
            parser=date.fromisoformat,
            metavar="YYYY-MM-DD",
            help="Last day of the window, YYYY-MM-DD; defaults to --date",
        ),
    ] = None,
    subject: Annotated[str, typer.Option("--subject")] = "Productivity Session",
    purpose: Annotated[str, typer.Option("--purpose")] = "",
    participant: Annotated[
        list[str] | None,
        typer.Option(
            "--participant",
            help="Additional participant as `uid:email`. Repeat for group rooms.",
        ),
    ] = None,
) -> None:
    """Create a reservation. The signed-in user is always added as a participant."""
    client = _client(ctx)
    user = _run(client, client.get_user_info)
    resource = _run(client, lambda: client.get_resource(resource_id, with_details=False))
    participants = [{"uid": user.uid, "email": user.email}]
    for entry in participant or []:
        if ":" not in entry:
            emit(
                {
                    "status": "error",
                    "code": "bad_participant",
                    "message": f"--participant must be `uid:email`, got {entry!r}.",
                },
                exit_code=2,
            )
        uid, email = entry.split(":", 1)
        participants.append({"uid": uid.strip(), "email": email.strip()})

    result = _run(
        client,
        lambda: client.create_reservation(
            resource_id=resource_id,
            resource_name=resource.name,
            start_date=start_date,
            end_date=end_date or start_date,
            start_time=start_time,
            end_time=end_time,
            subject=subject,
            purpose=purpose,
            participants=participants,
        ),
    )
    storage.save_cookies(client.http_client)
    emit({"status": "ok", "reservation": result})


@resources_app.command("unbook")
def resources_unbook_command(
    ctx: typer.Context,
    reservation_id: Annotated[int, typer.Argument(help="Reservation id to cancel")],
) -> None:
    """Cancel a reservation."""
    client = _client(ctx)
    _run(client, lambda: client.cancel_reservation(reservation_id))
    storage.save_cookies(client.http_client)
    emit({"status": "ok", "cancelled": reservation_id})
