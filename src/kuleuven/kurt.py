from datetime import date, time
from typing import Any

import httpx

from kuleuven.exceptions import SessionExpiredError
from kuleuven.models import (
    Account,
    AvailabilitySearchResult,
    Favorite,
    Location,
    Occupancy,
    Reservation,
    ReservationOrText,
    Resource,
    ResourceType,
    TileGroup,
    UserInfo,
)


KURT_ORIGIN = "https://kurt3.ghum.kuleuven.be"
# /login is the Shibboleth SP bootstrap that emits the SAMLRequest form.
# The bare origin serves the Angular SPA and never redirects to the IdP.
KURT_ENTRY_URL = f"{KURT_ORIGIN}/login"
API_BASE = f"{KURT_ORIGIN}/api"


def has_session(http_client: httpx.Client) -> bool:
    return any(
        "kurt3.ghum.kuleuven.be" in cookie.domain
        and cookie.name.startswith("_shibsession_")
        for cookie in http_client.cookies.jar
    )


class KurtClient:
    def __init__(self, session) -> None:
        self.http_client: httpx.Client = session.http_client

    def get_user_info(self) -> UserInfo:
        return UserInfo.model_validate(self._get_json("/information"))

    def get_account(self) -> Account:
        # Superset of /information that adds the per-resource-type quota
        # array (usageDay, usageWeek, maxUsageDay, maxUsageWeek; -1 = unlimited).
        return Account.model_validate(self._get_json("/account"))

    def list_tiles(self) -> list[TileGroup]:
        return [TileGroup.model_validate(item) for item in self._get_json("/tiles")]

    def get_location(self, location_id: int) -> Location:
        return Location.model_validate(self._get_json(f"/locations/{location_id}"))

    def list_resource_types(self, location_id: int) -> list[ResourceType]:
        items = self._get_json("/resourcetypes", params={"locationId": location_id})
        return [ResourceType.model_validate(item) for item in items]

    def get_occupancy(self, location_id: int) -> Occupancy:
        return Occupancy.model_validate(self._get_json(f"/occupancies/{location_id}"))

    def list_favorites(self) -> list[Favorite]:
        items = self._get_json("/favorites", params={"forHomePage": "true"})
        return [Favorite.model_validate(item) for item in items]

    def get_resource(self, resource_id: int, with_details: bool = True) -> Resource:
        return Resource.model_validate(
            self._get_json(
                f"/resources/{resource_id}",
                params={"withDetails": "true" if with_details else "false"},
            )
        )

    def search_availability(
        self,
        location_id: int,
        resource_type_id: int,
        start_date: date,
        end_date: date,
        start_time: time | None = None,
        end_time: time | None = None,
        zone_id: int = -1,
        participant_count: int = 1,
        page_number: int = 0,
        tag_ids: str = "",
        exact_match: bool = True,
        only_favorites: bool = False,
        resource_name_infix: str = "",
    ) -> AvailabilitySearchResult:
        return AvailabilitySearchResult.model_validate(
            self._get_json(
                "/resourcetypeavailabilities",
                params={
                    "locationId": location_id,
                    "zoneId": zone_id,
                    "resourceTypeId": resource_type_id,
                    "pageNumber": page_number,
                    "startDate": start_date.isoformat(),
                    "startTime": _wall_clock(start_time),
                    "endDate": end_date.isoformat(),
                    "endTime": _wall_clock(end_time),
                    "participantCount": participant_count,
                    "tagIds": tag_ids,
                    "exactMatch": "true" if exact_match else "false",
                    "onlyFavorites": "true" if only_favorites else "false",
                    "resourceNameInfix": resource_name_infix,
                    "version": "2.0",
                },
            )
        )

    def list_reservations(self, only_today: bool = False) -> list[Reservation]:
        params = {"onlyToday": "true"} if only_today else None
        items = self._get_json("/reservations", params=params)
        return [Reservation.model_validate(item) for item in items]

    def get_reservation(self, reservation_id: int) -> Reservation:
        return Reservation.model_validate(
            self._get_json(f"/reservations/{reservation_id}")
        )

    def create_reservation(
        self,
        resource_id: int,
        resource_name: str,
        start_date: date,
        end_date: date,
        start_time: time,
        end_time: time,
        subject: str = "",
        purpose: str = "",
        participants: list[dict] | None = None,
    ) -> ReservationOrText:
        # KURT rejects POST /reservations with a bare 400 (no body) unless
        # resourceName is echoed back — it's not optional despite not being a
        # logical input. Callers can pull it from a prior search/get_resource.
        payload = {
            "subject": subject,
            "purpose": purpose,
            "resourceId": resource_id,
            "resourceName": resource_name,
            "startDate": start_date.isoformat(),
            "startTime": _wall_clock(start_time),
            "endDate": end_date.isoformat(),
            "endTime": _wall_clock(end_time),
            "participants": participants or [],
            "isMultiDayReservable": False,
        }
        response = self.http_client.post(f"{API_BASE}/reservations/", json=payload)
        response.raise_for_status()
        return ReservationOrText.from_response(_maybe_json(response))

    def update_reservation(self, reservation: dict | Reservation) -> ReservationOrText:
        # KURT expects the full reservation object echoed back (the same shape
        # returned by GET /reservations/{id}), with edited fields applied.
        if isinstance(reservation, Reservation):
            payload = reservation.model_dump(by_alias=True, exclude_none=True)
        else:
            payload = reservation
        response = self.http_client.put(f"{API_BASE}/reservations/", json=payload)
        response.raise_for_status()
        return ReservationOrText.from_response(_maybe_json(response))

    def cancel_reservation(self, reservation_id: int) -> None:
        response = self.http_client.delete(f"{API_BASE}/reservations/{reservation_id}")
        response.raise_for_status()

    def close(self) -> None:
        self.http_client.close()

    def __enter__(self) -> "KurtClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _get_json(self, path: str, params: dict | None = None) -> Any:
        response = self.http_client.get(
            f"{API_BASE}{path}",
            params=params,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        _raise_if_session_bounce(response)
        return response.json()


def _wall_clock(value: time | None) -> str:
    # KURT wants `HH:MM`, and an empty string to mean "any time".
    return value.strftime("%H:%M") if value is not None else ""


def _maybe_json(response: httpx.Response) -> Any:
    _raise_if_session_bounce(response)
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return response.json()
    return response.text


def _raise_if_session_bounce(response: httpx.Response) -> None:
    # KURT serves the Shibboleth IdP "Loading Session Information" bounce
    # page (200 OK, text/html) once the SP session lapses — it never returns
    # 401, so content-type is the only signal that the request was answered
    # by the auth layer instead of the API.
    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith("text/html"):
        raise SessionExpiredError(
            "KURT session expired; run `kuleuven session start`."
        )
