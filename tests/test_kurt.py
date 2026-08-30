from datetime import date, time

import pytest

from kuleuven.exceptions import SessionExpiredError
from kuleuven.kurt import API_BASE
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


class TestKurtReadEndpoints:
    def test_get_user_info(self, kurt, respx_mock):
        respx_mock.get(f"{API_BASE}/information").respond(
            json={"uid": "r1", "email": "x@example.invalid"}
        )
        user = kurt.get_user_info()
        assert isinstance(user, UserInfo)
        assert user.uid == "r1"

    def test_get_account_parses_quota(self, kurt, respx_mock):
        respx_mock.get(f"{API_BASE}/account").respond(
            json={
                "uid": "r1",
                "quota": [
                    {
                        "resourceTypeId": 302,
                        "usageDay": 0,
                        "maxUsageDay": -1,
                        "maxUsageWeek": 48,
                    }
                ],
            }
        )
        account = kurt.get_account()
        assert isinstance(account, Account)
        assert account.quota[0].resource_type_id == 302
        assert account.quota[0].max_usage_week == 48

    def test_list_tiles(self, kurt, respx_mock):
        respx_mock.get(f"{API_BASE}/tiles").respond(
            json=[
                {
                    "id": 1,
                    "name": "Leuven",
                    "locations": [{"id": 1, "unit": "Arenberg", "city": "Leuven"}],
                }
            ]
        )
        tiles = kurt.list_tiles()
        assert isinstance(tiles[0], TileGroup)
        assert tiles[0].locations[0].unit == "Arenberg"

    def test_get_location(self, kurt, respx_mock):
        respx_mock.get(f"{API_BASE}/locations/5").respond(
            json={
                "id": 5,
                "name": "Loc",
                "zones": [{"id": 10, "name": "Z1", "locationId": 5}],
            }
        )
        loc = kurt.get_location(5)
        assert isinstance(loc, Location)
        assert loc.zones[0].id == 10

    def test_list_resource_types(self, kurt, respx_mock):
        route = respx_mock.get(f"{API_BASE}/resourcetypes").respond(
            json=[{"id": 302, "name": "Study Seat"}]
        )
        types = kurt.list_resource_types(5)
        assert isinstance(types[0], ResourceType)
        assert dict(route.calls[0].request.url.params) == {"locationId": "5"}

    def test_get_occupancy(self, kurt, respx_mock):
        respx_mock.get(f"{API_BASE}/occupancies/5").respond(
            json={"locationId": 5, "occupancy": 12, "capacity": 100}
        )
        occ = kurt.get_occupancy(5)
        assert isinstance(occ, Occupancy)
        assert occ.occupancy == 12

    def test_list_favorites(self, kurt, respx_mock):
        respx_mock.get(f"{API_BASE}/favorites").respond(
            json=[{"resourceId": 1, "resourceName": "Seat 1"}]
        )
        favs = kurt.list_favorites()
        assert isinstance(favs[0], Favorite)

    def test_get_resource(self, kurt, respx_mock):
        respx_mock.get(f"{API_BASE}/resources/5").respond(
            json={"id": 5, "name": "Group Room A"}
        )
        resource = kurt.get_resource(5)
        assert isinstance(resource, Resource)
        assert resource.name == "Group Room A"

    def test_search_availability_serializes_params(self, kurt, respx_mock):
        route = respx_mock.get(f"{API_BASE}/resourcetypeavailabilities").respond(
            json={"availabilities": [], "message": ""}
        )
        result = kurt.search_availability(
            location_id=5,
            resource_type_id=302,
            start_date=date(2026, 5, 26),
            end_date=date(2026, 5, 26),
            start_time=time(10, 0),
            only_favorites=True,
        )
        assert isinstance(result, AvailabilitySearchResult)
        params = dict(route.calls[0].request.url.params)
        assert params["onlyFavorites"] == "true"
        assert params["exactMatch"] == "true"
        # KURT's own formats: dates as YYYY-MM-DD, times as HH:MM, and an
        # empty string for the time it was not given.
        assert params["startDate"] == "2026-05-26"
        assert params["startTime"] == "10:00"
        assert params["endTime"] == ""


class TestKurtReservations:
    def test_list_reservations(self, kurt, respx_mock, kurt_reservation_payload):
        respx_mock.get(f"{API_BASE}/reservations").respond(
            json=[kurt_reservation_payload]
        )
        items = kurt.list_reservations()
        assert isinstance(items[0], Reservation)
        assert items[0].id == 42

    def test_list_reservations_only_today_param(self, kurt, respx_mock):
        route = respx_mock.get(f"{API_BASE}/reservations").respond(json=[])
        kurt.list_reservations(only_today=True)
        assert dict(route.calls[0].request.url.params) == {"onlyToday": "true"}

    def test_get_reservation(self, kurt, respx_mock, kurt_reservation_payload):
        respx_mock.get(f"{API_BASE}/reservations/42").respond(
            json=kurt_reservation_payload
        )
        assert kurt.get_reservation(42).id == 42

    def test_create_reservation_json_success(
        self, kurt, respx_mock, kurt_reservation_payload
    ):
        route = respx_mock.post(f"{API_BASE}/reservations/").respond(
            json=kurt_reservation_payload
        )
        result = kurt.create_reservation(
            resource_id=7,
            resource_name="Group Room A",
            start_date=date(2026, 5, 26),
            end_date=date(2026, 5, 26),
            start_time=time(10, 0),
            end_time=time(12, 0),
            participants=[{"uid": "r1", "email": "a@b.c"}],
        )
        assert isinstance(result, ReservationOrText)
        assert result.reservation.id == 42
        assert result.message is None
        # `resourceName` must be echoed back in the POST body — KURT 400s
        # otherwise. Confirm it's there.
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["resourceName"] == "Group Room A"
        assert body["startDate"] == "2026-05-26"
        assert body["startTime"] == "10:00"

    def test_create_reservation_text_fallback(self, kurt, respx_mock):
        respx_mock.post(f"{API_BASE}/reservations/").respond(
            content=b"Resource not available",
            headers={"content-type": "text/plain"},
        )
        result = kurt.create_reservation(
            resource_id=7,
            resource_name="X",
            start_date=date(2026, 5, 26),
            end_date=date(2026, 5, 26),
            start_time=time(10, 0),
            end_time=time(12, 0),
        )
        assert result.reservation is None
        assert result.message == "Resource not available"

    def test_update_reservation_accepts_reservation_instance(
        self, kurt, respx_mock, kurt_reservation_payload
    ):
        route = respx_mock.put(f"{API_BASE}/reservations/").respond(
            json=kurt_reservation_payload
        )
        reservation = Reservation.model_validate(kurt_reservation_payload)
        reservation.subject = "Updated"
        result = kurt.update_reservation(reservation)
        assert isinstance(result, ReservationOrText)
        # The PUT body must echo the upstream camelCase shape.
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["subject"] == "Updated"
        assert body["resourceId"] == 7
        # The window has to survive the round trip in KURT's wire format, not
        # as the date/time objects the model holds.
        assert body["startDate"] == "2026-05-26"
        assert body["endTime"] == "12:00"

    def test_cancel_reservation(self, kurt, respx_mock):
        route = respx_mock.delete(f"{API_BASE}/reservations/42").respond(status_code=200)
        kurt.cancel_reservation(42)
        assert route.called


class TestKurtSessionBounce:
    def test_html_response_raises_session_expired(self, kurt, respx_mock):
        # KURT's session-expired bounce is a 200 OK with text/html — the only
        # signal the SP timed out. _get_json must raise SessionExpiredError
        # instead of silently returning the (unparseable) login page.
        respx_mock.get(f"{API_BASE}/information").respond(
            content=b"<html>Login...</html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
        with pytest.raises(SessionExpiredError):
            kurt.get_user_info()
