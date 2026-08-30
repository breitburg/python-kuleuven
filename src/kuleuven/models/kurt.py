from datetime import date, time
from typing import Annotated, Any

from pydantic import Field, PlainSerializer

from kuleuven.models._base import ApiEchoModel

# KURT splits a booking window into a date and a wall-clock time, and it only
# accepts them back in its own formats: `YYYY-MM-DD` and `HH:MM` (no seconds,
# which `time.isoformat()` would emit). Serialize on the way out in both
# python and JSON mode, because `update_reservation` posts `model_dump()`
# straight to the API.
KurtDate = Annotated[
    date, PlainSerializer(lambda value: value.isoformat(), return_type=str)
]
KurtTime = Annotated[
    time, PlainSerializer(lambda value: value.strftime("%H:%M"), return_type=str)
]


class UserInfo(ApiEchoModel):
    uid: str | None = None
    email: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    user_type: str | None = Field(default=None, alias="userType")


class Quota(ApiEchoModel):
    # Per-resource-type usage and limit. `-1` means unlimited.
    resource_type_id: int | None = Field(default=None, alias="resourceTypeId")
    resource_type_name: str | None = Field(default=None, alias="resourceTypeName")
    usage_day: int | None = Field(default=None, alias="usageDay")
    usage_week: int | None = Field(default=None, alias="usageWeek")
    max_usage_day: int | None = Field(default=None, alias="maxUsageDay")
    max_usage_week: int | None = Field(default=None, alias="maxUsageWeek")


class Account(ApiEchoModel):
    uid: str | None = None
    email: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    user_type: str | None = Field(default=None, alias="userType")
    quota: list[Quota] = Field(default_factory=list)


class Tile(ApiEchoModel):
    # One location entry inside a TileGroup. KURT returns a sparse summary
    # ({id, unit, city, thumbnailUrl}); the full shape lives on /locations/{id}.
    id: int | None = None
    unit: str | None = None
    city: str | None = None
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")


class TileGroup(ApiEchoModel):
    # /tiles returns a list of {name, locations[]} groups keyed by city
    # or special category (e.g. "Favorites").
    id: int | None = None
    name: str | None = None
    tile_group: int | None = Field(default=None, alias="tileGroup")
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")
    locations: list[Tile] = Field(default_factory=list)


class Zone(ApiEchoModel):
    id: int | None = None
    name: str | None = None
    description: str | None = None
    location_id: int | None = Field(default=None, alias="locationId")


class Location(ApiEchoModel):
    id: int | None = None
    name: str | None = None
    description: str | None = None
    address: str | None = None
    zones: list[Zone] = Field(default_factory=list)


class ResourceType(ApiEchoModel):
    id: int | None = None
    name: str | None = None
    description: str | None = None
    location_id: int | None = Field(default=None, alias="locationId")


class Occupancy(ApiEchoModel):
    location_id: int | None = Field(default=None, alias="locationId")
    occupancy: int | None = None
    capacity: int | None = None


class Favorite(ApiEchoModel):
    resource_id: int | None = Field(default=None, alias="resourceId")
    resource_name: str | None = Field(default=None, alias="resourceName")
    location_id: int | None = Field(default=None, alias="locationId")
    resource_type_id: int | None = Field(default=None, alias="resourceTypeId")


class Resource(ApiEchoModel):
    id: int | None = None
    name: str | None = None
    description: str | None = None
    location_id: int | None = Field(default=None, alias="locationId")
    resource_type_id: int | None = Field(default=None, alias="resourceTypeId")
    zone_id: int | None = Field(default=None, alias="zoneId")
    capacity: int | None = None


class AvailabilitySlot(ApiEchoModel):
    resource_id: int | None = Field(default=None, alias="resourceId")
    resource_name: str | None = Field(default=None, alias="resourceName")
    # `start`/`end` stay strings: unlike the reservation window, KURT's format
    # for them was never captured, so parsing them into date/time objects
    # would risk rejecting a live response. extra="allow" passes them through
    # either way.
    start: str | None = None
    end: str | None = None
    available: bool | None = None


class AvailabilitySearchResult(ApiEchoModel):
    availabilities: list[AvailabilitySlot] = Field(default_factory=list)
    message: str = ""
    page_number: int | None = Field(default=None, alias="pageNumber")
    total_pages: int | None = Field(default=None, alias="totalPages")


class ReservationParticipant(ApiEchoModel):
    uid: str | None = None
    email: str | None = None


class Reservation(ApiEchoModel):
    id: int | None = None
    subject: str | None = None
    purpose: str | None = None
    resource_id: int | None = Field(default=None, alias="resourceId")
    resource_name: str | None = Field(default=None, alias="resourceName")
    start_date: KurtDate | None = Field(default=None, alias="startDate")
    end_date: KurtDate | None = Field(default=None, alias="endDate")
    start_time: KurtTime | None = Field(default=None, alias="startTime")
    end_time: KurtTime | None = Field(default=None, alias="endTime")
    participants: list[ReservationParticipant] = Field(default_factory=list)
    is_multi_day_reservable: bool | None = Field(
        default=None, alias="isMultiDayReservable"
    )


class ReservationOrText(ApiEchoModel):
    # KURT occasionally returns a plain text body for create/update (a
    # validation message), and a JSON Reservation otherwise. Wrap the two
    # cases so callers can branch on .reservation vs .message.
    reservation: Reservation | None = None
    message: str | None = None

    @classmethod
    def from_response(cls, value: Any) -> "ReservationOrText":
        if isinstance(value, dict):
            return cls(reservation=Reservation.model_validate(value))
        return cls(message=str(value) if value is not None else None)
