from collections.abc import Iterator

import httpx
import pytest
import respx

from kuleuven.kurt import KurtClient
from kuleuven.session import KuleuvenSession
from kuleuven.toledo import ToledoClient


@pytest.fixture
def http_client() -> Iterator[httpx.Client]:
    # Bare httpx.Client (no SAML cookies, no real network). respx intercepts
    # at the transport level so any request from this client is mocked.
    with httpx.Client(follow_redirects=False) as client:
        yield client


@pytest.fixture
def session(http_client: httpx.Client) -> KuleuvenSession:
    return KuleuvenSession(http_client=http_client)


@pytest.fixture
def toledo(session: KuleuvenSession) -> ToledoClient:
    return ToledoClient(session)


@pytest.fixture
def kurt(session: KuleuvenSession) -> KurtClient:
    return KurtClient(session)


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


# Sample API payloads. Trimmed to the fields the code reads — anything extra
# the upstream API sends is ignored by the models (extra="ignore"/"allow").


@pytest.fixture
def portal_course_payload() -> dict:
    return {
        "learningUnitId": "ULTRA-B-KUL-EX101a-2526",
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Example Course [EX101a]",
        "imageUrl": "ltc/abc",
        "link": "https://example.invalid/link",
        "type": "course",
        "available": True,
        "academicYear": 2526,
        "semester": "SEMESTER2",
        "role": "Learner",
        "favorite": False,
        "color": 7,
    }


@pytest.fixture
def ultra_membership_payload() -> dict:
    return {
        "id": "_mem_1",
        "role": "S",
        "courseCardColorIndex": 7,
        "lastAccessDate": "2026-05-01T00:00:00Z",
        "enrollmentDate": "2025-09-01T00:00:00Z",
        "userHasHidden": False,
        "courseRole": {"identifier": "S", "roleBucket": "TAKING"},
        "course": {
            "id": "_100001_1",
            "batchUid": "ULTRA-B-KUL-EX101a-2526",
            "uuid": "course-uuid",
            "foundationsId": "fid-1",
            "displayName": "Example Course [EX101a]",
            "description": "  ",
            "externalAccessUrl": "https://example.invalid/x",
            "isOrganization": False,
            "isAvailable": True,
            "effectiveAvailability": True,
            "locale": "en",
            "ultraStatus": "Ultra",
            "courseViewOption": "ULTRA",
        },
    }


@pytest.fixture
def membership_payload() -> dict:
    return {
        "id": "_mem_42_1",
        "courseId": "_100001_1",
        "isAvailable": True,
        "courseRole": {"identifier": "S", "roleBucket": "TAKING"},
        "user": {
            "id": "_user_1",
            "userName": "q1234567",
            "givenName": "Jane",
            "familyName": "Doe",
            "emailAddress": "jane.doe@example.invalid",
            "foundationsId": "f1",
            "uuid": "user-uuid",
        },
    }


@pytest.fixture
def announcement_payload() -> dict:
    return {
        "id": "_ann_1",
        "courseId": "_100001_1",
        "title": "Welcome",
        "body": {"rawText": "<p>Hello world</p>"},
        "readStatus": {"isRead": False},
        "isDraft": False,
        "createdDate": "2026-01-10T00:00:00Z",
        "modifiedDate": "2026-01-10T00:00:00Z",
        "creatorUserId": "_creator_1",
        "type": "COURSE",
        "position": 1,
        "permanent": False,
        "pushNotify": True,
        "readTracking": True,
    }


@pytest.fixture
def content_item_payload() -> dict:
    return {
        "id": "_content_1",
        "parentId": "ROOT",
        "title": "My Folder",
        "contentHandler": "resource/x-bb-folder",
        "contentDetail": {"resource/x-bb-folder": {"isBbPage": False}},
        "visibility": "VISIBLE",
        "modifiedDate": "2026-05-01T00:00:00Z",
        "position": 1,
    }


@pytest.fixture
def bb_page_payload() -> dict:
    return {
        "id": "_bbpage_1",
        "parentId": "ROOT",
        "title": "Slides",
        "contentHandler": "resource/x-bb-folder",
        "contentDetail": {"resource/x-bb-folder": {"isBbPage": True}},
        "position": 0,
    }


@pytest.fixture
def file_leaf_payload() -> dict:
    return {
        "id": "_file_1",
        "parentId": "ROOT",
        "title": "lecture.pdf",
        "contentHandler": "resource/x-bb-file",
        "contentDetail": {
            "resource/x-bb-file": {
                "file": {
                    "fileName": "lecture.pdf",
                    "mimeType": "application/pdf",
                    "fileSize": 12345,
                    "permanentUrl": "/bbcswebdav/xid-1",
                }
            }
        },
    }


@pytest.fixture
def kurt_reservation_payload() -> dict:
    return {
        "id": 42,
        "subject": "Study session",
        "purpose": "Group work",
        "resourceId": 7,
        "resourceName": "Group Room A",
        "startDate": "2026-05-26",
        "endDate": "2026-05-26",
        "startTime": "10:00",
        "endTime": "12:00",
        "participants": [{"uid": "r0123456", "email": "me@example.invalid"}],
        "isMultiDayReservable": False,
    }
