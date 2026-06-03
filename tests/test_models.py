import pytest

from kuleuven.models import (
    Account,
    Announcement,
    AnnouncementCounts,
    ContentItem,
    ContentNode,
    Course,
    Embed,
    FileItem,
    MemberCounts,
    Membership,
    Person,
    Reservation,
    ReservationOrText,
    TileGroup,
)


class TestCourse:
    def test_from_portal(self, portal_course_payload):
        course = Course.from_portal(portal_course_payload)
        assert course.batch_uid == "ULTRA-B-KUL-EX101a-2526"
        assert course.portal_uuid == "00000000-0000-0000-0000-000000000001"
        assert course.display_name == "Example Course [EX101a]"
        assert course.is_available is True
        assert course.academic_year == 2526
        assert course.role == "Learner"

    def test_from_portal_unknown_type_defaults_to_course(self):
        # Portal omits `type` for the implicit course case.
        raw = {"learningUnitId": "ULTRA-B-KUL-XX-2526", "id": "u1", "title": "X"}
        assert Course.from_portal(raw).type == "course"

    def test_from_ultra_membership(self, ultra_membership_payload):
        course = Course.from_ultra_membership(ultra_membership_payload)
        assert course.batch_uid == "ULTRA-B-KUL-EX101a-2526"
        assert course.pk == "_100001_1"
        assert course.course_uuid == "course-uuid"
        assert course.role == "S"

    def test_from_ultra_membership_empty_description_stripped(self, ultra_membership_payload):
        ultra_membership_payload["course"]["description"] = ""
        course = Course.from_ultra_membership(ultra_membership_payload)
        assert course.description is None

    def test_from_ultra_course_organization_becomes_community(self):
        raw = {"courseId": "ORG-X", "id": "_org_1", "isOrganization": True}
        assert Course.from_ultra_course(raw).type == "community"

    def test_course_code_real_course(self):
        course = Course(batch_uid="ULTRA-B-KUL-EX101a-2526", type="course")
        assert course.course_code == "EX101a"

    def test_course_code_community_returns_none(self):
        course = Course(batch_uid="ULTRA-B-KUL-X-2526", type="community")
        assert course.course_code is None

    def test_course_code_non_ultra_batchuid_returns_none(self):
        course = Course(batch_uid="LEGACY-EX101a", type="course")
        assert course.course_code is None

    def test_merge_self_wins_when_non_empty(self):
        a = Course(batch_uid="X", pk="p1", display_name="A")
        b = Course(batch_uid="X", pk="p2", display_name="B", description="from b")
        merged = a.merge(b)
        assert merged.pk == "p1"
        assert merged.display_name == "A"
        # b fills in what a is missing
        assert merged.description == "from b"

    def test_merge_empty_string_is_treated_as_missing(self):
        a = Course(batch_uid="X", display_name="")
        b = Course(batch_uid="X", display_name="B")
        assert a.merge(b).display_name == "B"

    def test_dump_is_snake_case_and_includes_course_code(self):
        course = Course(batch_uid="ULTRA-B-KUL-EX101a-2526", display_name="Foo")
        data = course.model_dump(mode="json")
        assert data["batch_uid"] == "ULTRA-B-KUL-EX101a-2526"
        assert data["display_name"] == "Foo"
        assert data["course_code"] == "EX101a"
        # No camelCase keys leak through
        assert "displayName" not in data


class TestPerson:
    def test_from_portal_instructor(self):
        person = Person.from_portal_instructor(
            {"id": "q1", "firstName": "Ada", "lastName": "Lovelace"}
        )
        assert person.q_uid == "q1"
        assert person.given_name == "Ada"
        assert person.family_name == "Lovelace"
        # Portal omits the rest
        assert person.pk is None
        assert person.email is None

    def test_from_ultra_user(self):
        person = Person.from_ultra_user(
            {
                "id": "_u_1",
                "userName": "q1",
                "givenName": "Ada",
                "familyName": "Lovelace",
                "emailAddress": "ada@example.invalid",
                "foundationsId": "f1",
                "uuid": "uuu",
            }
        )
        assert person.pk == "_u_1"
        assert person.email == "ada@example.invalid"
        assert person.uuid == "uuu"


class TestMembership:
    def test_from_ultra(self, membership_payload):
        membership = Membership.from_ultra(membership_payload)
        assert membership.pk == "_mem_42_1"
        assert membership.course_pk == "_100001_1"
        assert membership.role == "S"
        assert membership.role_bucket == "TAKING"
        assert membership.user.given_name == "Jane"

    def test_dump_nests_user(self, membership_payload):
        dumped = Membership.from_ultra(membership_payload).model_dump(mode="json")
        assert dumped["user"]["q_uid"] == "q1234567"
        assert dumped["role"] == "S"


class TestAnnouncement:
    def test_from_ultra(self, announcement_payload):
        ann = Announcement.from_ultra(announcement_payload)
        assert ann.id == "_ann_1"
        assert ann.title == "Welcome"
        assert ann.body_html == "<p>Hello world</p>"
        assert ann.is_read is False

    def test_body_html_excluded_from_dump(self, announcement_payload):
        # body_html is meant to be rendered to markdown at the call site;
        # dumping it as raw HTML in the CLI output would be misleading.
        ann = Announcement.from_ultra(announcement_payload)
        assert "body_html" not in ann.model_dump(mode="json")


class TestEmbed:
    def test_lti_branch_by_bbtype(self):
        embed = Embed.from_anchor(
            {"title": "Lecture", "url": "https://x/"}, bb_type="embedded-app"
        )
        assert embed.kind == "lti"
        assert embed.title == "Lecture"

    def test_lti_branch_by_linktype_field(self):
        embed = Embed.from_anchor({"linkType": "LTI", "url": "https://x/"})
        assert embed.kind == "lti"

    def test_file_with_resource_url(self):
        embed = Embed.from_anchor(
            {
                "displayName": "Notes.pdf",
                "resourceUrl": "https://x/notes.pdf",
                "mimeType": "application/pdf",
            }
        )
        assert embed.kind == "file"
        assert embed.url == "https://x/notes.pdf"
        assert embed.mime_type == "application/pdf"

    def test_file_falls_back_to_viewerurl_stripping_query(self):
        # No resourceUrl: viewerUrl path is used and the query string
        # (the inline-render React viewer params) is dropped so GET returns
        # the raw file bytes.
        embed = Embed.from_anchor(
            {
                "linkName": "doc.pdf",
                "viewerUrl": "https://x/bbcswebdav/path/doc.pdf?inline=true",
            }
        )
        assert embed.url == "https://x/bbcswebdav/path/doc.pdf"


class TestContentNode:
    def test_from_ultra_detects_bb_page(self, bb_page_payload):
        node = ContentNode.from_ultra(bb_page_payload, depth=2)
        assert node.is_bb_page is True
        assert node.depth == 2
        assert node.handler == "resource/x-bb-folder"

    def test_from_ultra_default_is_not_bb_page(self, content_item_payload):
        node = ContentNode.from_ultra(content_item_payload, depth=0)
        assert node.is_bb_page is False


class TestContentItem:
    def test_round_trip_preserves_camelcase(self, content_item_payload):
        item = ContentItem.model_validate(content_item_payload)
        dumped = item.model_dump(mode="json")
        # ApiEchoModel: keys come back in camelCase
        assert dumped["parentId"] == "ROOT"
        assert dumped["contentHandler"] == "resource/x-bb-folder"
        assert dumped["modifiedDate"] == "2026-05-01T00:00:00Z"

    def test_modified_date_accepts_epoch_ms_int(self):
        # /contents/{parent}/children?@view=Summary returns ms-since-epoch.
        # The model has to accept both shapes.
        item = ContentItem.model_validate(
            {
                "id": "_x_1",
                "title": "X",
                "contentHandler": "resource/x-bb-folder",
                "modifiedDate": 1775144522018,
            }
        )
        assert item.modified_date == 1775144522018


class TestApiEchoVsCurated:
    def test_member_counts_keeps_api_shape(self):
        counts = MemberCounts.model_validate(
            {"results": {"STUDENT": 501, "INSTRUCTOR": 3}, "count": 504}
        )
        dumped = counts.model_dump(mode="json")
        assert dumped == {
            "results": {"STUDENT": 501, "INSTRUCTOR": 3},
            "count": 504,
        }

    def test_announcement_counts_aliases_round_trip(self):
        counts = AnnouncementCounts.model_validate(
            {"postedCount": 5, "unreadCount": 2}
        )
        assert counts.posted_count == 5
        assert counts.unread_count == 2
        # Dump preserves camelCase
        assert counts.model_dump(mode="json") == {
            "postedCount": 5,
            "unreadCount": 2,
        }

    def test_curated_filetem_dumps_snake_case(self):
        item = FileItem(
            id="x",
            kind="file",
            title="t",
            filename="t.pdf",
            source_content_id="x",
            source_path=["A", "B"],
        )
        dumped = item.model_dump(mode="json")
        assert dumped["source_path"] == ["A", "B"]
        assert "sourcePath" not in dumped


class TestReservationOrText:
    def test_dict_response_becomes_reservation(self, kurt_reservation_payload):
        result = ReservationOrText.from_response(kurt_reservation_payload)
        assert isinstance(result.reservation, Reservation)
        assert result.reservation.id == 42
        assert result.message is None

    def test_string_response_becomes_message(self):
        result = ReservationOrText.from_response("Room not available")
        assert result.reservation is None
        assert result.message == "Room not available"

    def test_none_response_is_none_message(self):
        result = ReservationOrText.from_response(None)
        assert result.message is None
        assert result.reservation is None


class TestKurtModels:
    def test_account_with_quota(self):
        account = Account.model_validate(
            {
                "uid": "r1",
                "email": "x@example.invalid",
                "quota": [
                    {
                        "resourceTypeId": 302,
                        "usageDay": 0,
                        "usageWeek": 0,
                        "maxUsageDay": -1,
                        "maxUsageWeek": 48,
                    }
                ],
            }
        )
        assert account.uid == "r1"
        assert account.quota[0].resource_type_id == 302
        assert account.quota[0].max_usage_week == 48

    def test_tile_group_uses_locations_field(self):
        # KURT calls the nested list `locations` despite the wrapper being a
        # `tile group`. Regression test for the earlier `tiles` mismatch.
        group = TileGroup.model_validate(
            {
                "name": "Leuven",
                "id": 1,
                "locations": [
                    {"id": 1, "unit": "Arenberg", "city": "Leuven"},
                ],
            }
        )
        assert len(group.locations) == 1
        assert group.locations[0].unit == "Arenberg"

    def test_reservation_alias_round_trip(self, kurt_reservation_payload):
        reservation = Reservation.model_validate(kurt_reservation_payload)
        assert reservation.resource_id == 7
        assert reservation.start_time == "10:00"
        # Dump in camelCase, matching the upstream contract used in PUT bodies
        dumped = reservation.model_dump(by_alias=True)
        assert dumped["resourceId"] == 7
        assert dumped["startTime"] == "10:00"
