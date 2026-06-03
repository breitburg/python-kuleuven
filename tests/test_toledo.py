from io import BytesIO

import pytest

from kuleuven.models import (
    Announcement,
    AnnouncementCounts,
    BodyAndEmbeds,
    BodyResolution,
    ContentItem,
    Course,
    DownloadResult,
    FileItem,
    KalturaEntry,
    MemberCounts,
    Membership,
    MessageRepliesPage,
    PortalCourseDetail,
    UltraCourseDetail,
)
from kuleuven.toledo import (
    KALTURA_API,
    PORTAL_ENROLLMENTS_URL,
    ULTRA_API,
    ULTRA_ORIGIN,
    ToledoClient,
)


class TestCoursesEndpoints:
    def test_fetch_user_pk(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/users/me").respond(json={"id": "_me_1"})
        assert toledo.fetch_user_pk() == "_me_1"

    def test_list_portal_courses(self, toledo, respx_mock, portal_course_payload):
        respx_mock.get(PORTAL_ENROLLMENTS_URL).respond(json=[portal_course_payload])
        courses = toledo.list_portal_courses()
        assert len(courses) == 1
        assert isinstance(courses[0], Course)
        assert courses[0].course_code == "EX101a"

    def test_list_ultra_courses_resolves_user_pk(
        self, toledo, respx_mock, ultra_membership_payload
    ):
        respx_mock.get(f"{ULTRA_API}/users/me").respond(json={"id": "_me_1"})
        respx_mock.get(f"{ULTRA_API}/users/_me_1/memberships").respond(
            json={"results": [ultra_membership_payload]}
        )
        courses = toledo.list_ultra_courses()
        assert courses[0].pk == "_100001_1"
        assert courses[0].role == "S"

    def test_list_ultra_courses_with_explicit_pk_skips_lookup(
        self, toledo, respx_mock, ultra_membership_payload
    ):
        # Caller provides user_pk: the /users/me probe must be skipped.
        memberships = respx_mock.get(
            f"{ULTRA_API}/users/_given_1/memberships"
        ).respond(json={"results": [ultra_membership_payload]})
        toledo.list_ultra_courses(user_pk="_given_1")
        assert memberships.call_count == 1
        # No request was made to /users/me — proven by respx not having to
        # serve one (its assert_all_called=False fixture would otherwise hide
        # the issue, but a stray request would still fail with no route).

    def test_fetch_portal_detail_groups_admin_urls(self, toledo, respx_mock):
        respx_mock.get(f"{PORTAL_ENROLLMENTS_URL}/BU-1/en").respond(
            json={
                "description": "course desc",
                "instructors": [
                    {"id": "q1", "firstName": "Ada", "lastName": "Lovelace"}
                ],
                "unenrollUrl": "/u",
                "manageUrl": "/m",
                "ectsLink": "https://ects/x",
            }
        )
        detail = toledo.fetch_portal_detail("BU-1")
        assert isinstance(detail, PortalCourseDetail)
        assert detail.description == "course desc"
        assert len(detail.instructors) == 1
        assert detail.instructors[0].given_name == "Ada"
        # PortalAdminUrls is an ApiEchoModel → camelCase preserved on dump
        dumped = detail.admin_urls.model_dump(mode="json", exclude_none=True)
        assert dumped["unenrollUrl"] == "/u"
        assert dumped["manageUrl"] == "/m"
        assert dumped["ectsLink"] == "https://ects/x"

    def test_fetch_ultra_course(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1").respond(
            json={
                "id": "_pk_1",
                "courseId": "ULTRA-B-KUL-X-2526",
                "displayName": "X",
                "isOrganization": False,
                "instructorsMembership": [
                    {
                        "user": {
                            "id": "_u_1",
                            "givenName": "Ada",
                            "familyName": "Lovelace",
                        }
                    }
                ],
            }
        )
        detail = toledo.fetch_ultra_course("_pk_1")
        assert isinstance(detail, UltraCourseDetail)
        assert detail.course.pk == "_pk_1"
        assert detail.instructors[0].given_name == "Ada"

    def test_fetch_members_passes_filters_through(
        self, toledo, respx_mock, membership_payload
    ):
        route = respx_mock.get(f"{ULTRA_API}/courses/_pk_1/memberships").respond(
            json={"results": [membership_payload]}
        )
        members = toledo.fetch_members(
            "_pk_1", role_bucket="TEACHING", available=False, limit=5
        )
        assert isinstance(members[0], Membership)
        params = dict(route.calls[0].request.url.params)
        assert params["roleBucket"] == "TEACHING"
        assert params["membershipAvailable"] == "false"
        assert params["limit"] == "5"

    def test_fetch_member_counts(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/memberships/counts").respond(
            json={"results": {"STUDENT": 5}, "count": 5}
        )
        counts = toledo.fetch_member_counts("_pk_1")
        assert isinstance(counts, MemberCounts)
        assert counts.results == {"STUDENT": 5}
        assert counts.count == 5

    def test_fetch_announcements(self, toledo, respx_mock, announcement_payload):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/announcements").respond(
            json={"results": [announcement_payload]}
        )
        anns = toledo.fetch_announcements("_pk_1")
        assert isinstance(anns[0], Announcement)
        assert anns[0].title == "Welcome"
        assert anns[0].body_html == "<p>Hello world</p>"

    def test_fetch_announcement_counts(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/announcements/counts").respond(
            json={"postedCount": 3, "unreadCount": 1}
        )
        counts = toledo.fetch_announcement_counts("_pk_1")
        assert isinstance(counts, AnnouncementCounts)
        assert counts.posted_count == 3
        assert counts.unread_count == 1

    def test_fetch_schedule_omits_optional_params(self, toledo, respx_mock):
        route = respx_mock.get(f"{ULTRA_API}/courses/_pk_1/schedule").respond(
            json={"results": []}
        )
        toledo.fetch_schedule("_pk_1")
        params = dict(route.calls[0].request.url.params)
        assert params == {"sort": "location(desc)"}

    def test_fetch_user_grades(self, toledo, respx_mock):
        route = respx_mock.get(f"{ULTRA_API}/courses/_pk_1/gradebook/grades").respond(
            json={"results": [{"columnId": "_col_1", "courseId": "_pk_1"}]}
        )
        grades = toledo.fetch_user_grades("_pk_1", "_user_1")
        assert len(grades) == 1
        params = dict(route.calls[0].request.url.params)
        assert params["userId"] == "_user_1"
        assert params["includeNoGradeItems"] == "true"

    def test_set_favorite_patches(self, toledo, respx_mock):
        route = respx_mock.patch(f"{PORTAL_ENROLLMENTS_URL}/p-uuid").respond(
            status_code=200
        )
        toledo.set_favorite("p-uuid", True)
        assert route.called

    def test_resolve_matches_by_batch_uid(self):
        courses = [
            Course(batch_uid="ULTRA-B-KUL-EX101a-2526"),
            Course(batch_uid="ULTRA-B-KUL-EX101a-2425"),
        ]
        match = ToledoClient.resolve(courses, "ULTRA-B-KUL-EX101a-2526")
        assert len(match) == 1
        assert match[0].batch_uid.endswith("-2526")

    def test_resolve_returns_all_course_code_matches(self):
        # Two years of the same course code → resolve returns both for the
        # caller to disambiguate.
        courses = [
            Course(batch_uid="ULTRA-B-KUL-EX101a-2526", type="course"),
            Course(batch_uid="ULTRA-B-KUL-EX101a-2425", type="course"),
        ]
        assert len(ToledoClient.resolve(courses, "ex101a")) == 2

    def test_resolve_no_match_returns_empty(self):
        assert ToledoClient.resolve([Course(batch_uid="X")], "missing") == []


class TestDiscussionsEndpoints:
    def test_list_discussions_filters_to_forumlinks(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/INTERACTIVE/children").respond(
            json={
                "results": [
                    {
                        "id": "_forum_1",
                        "title": "Forum",
                        "contentHandler": "resource/x-bb-forumlink",
                    },
                    {
                        # Non-forum item gets filtered out
                        "id": "_doc_1",
                        "title": "Doc",
                        "contentHandler": "resource/x-bb-document",
                    },
                ]
            }
        )
        items = toledo.list_discussions("_pk_1")
        assert len(items) == 1
        assert items[0].model_dump(mode="json")["id"] == "_forum_1"

    def test_list_message_replies_returns_envelope(self, toledo, respx_mock):
        respx_mock.get(
            f"{ULTRA_API}/courses/_pk_1/discussionboards/default/forums/_f_1/messages/_m_1/replies"
        ).respond(
            json={
                "paging": {"count": 7, "offset": 0, "limit": 100, "nextPage": None},
                "results": [{"id": "_r_1"}],
            }
        )
        page = toledo.list_message_replies("_pk_1", "_f_1", "_m_1")
        assert isinstance(page, MessageRepliesPage)
        assert page.paging.count == 7
        assert len(page.results) == 1


class TestContentEndpoints:
    def test_fetch_content_returns_typed_item(
        self, toledo, respx_mock, content_item_payload
    ):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/_c_1").respond(
            json=content_item_payload
        )
        item = toledo.fetch_content("_pk_1", "_c_1")
        assert isinstance(item, ContentItem)
        assert item.parent_id == "ROOT"

    def test_fetch_children_returns_typed_list(
        self, toledo, respx_mock, content_item_payload
    ):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={"results": [content_item_payload]}
        )
        children = toledo.fetch_children("_pk_1", "ROOT")
        assert all(isinstance(c, ContentItem) for c in children)

    def test_is_bb_page_predicate(self, bb_page_payload, content_item_payload):
        assert ToledoClient.is_bb_page(ContentItem.model_validate(bb_page_payload)) is True
        assert (
            ToledoClient.is_bb_page(ContentItem.model_validate(content_item_payload))
            is False
        )

    def test_pick_bb_page_child_prefers_named_marker(self):
        children = [
            ContentItem(id="_a", title="Other"),
            ContentItem(id="_b", title="ultraDocumentBody"),
        ]
        picked = ToledoClient.pick_bb_page_child(children)
        assert picked.id == "_b"

    def test_pick_bb_page_child_falls_back_to_sole_child(self):
        children = [ContentItem(id="_only", title="Sole child")]
        assert ToledoClient.pick_bb_page_child(children).id == "_only"

    def test_pick_bb_page_child_returns_none_when_ambiguous(self):
        children = [ContentItem(id="_a", title="A"), ContentItem(id="_b", title="B")]
        assert ToledoClient.pick_bb_page_child(children) is None

    def test_resolve_body_item_descends_into_bb_page(
        self, toledo, respx_mock, bb_page_payload
    ):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/_page_1").respond(
            json=bb_page_payload
        )
        respx_mock.get(
            f"{ULTRA_API}/courses/_pk_1/contents/_page_1/children"
        ).respond(
            json={
                "results": [
                    {
                        "id": "_inner_1",
                        "title": "ultraDocumentBody",
                        "contentHandler": "resource/x-bb-document",
                        "body": {"rawText": "<p>inside</p>"},
                    }
                ]
            }
        )
        resolution = toledo.resolve_body_item("_pk_1", "_page_1")
        assert isinstance(resolution, BodyResolution)
        assert resolution.original.id == "_bbpage_1"
        assert resolution.body_item.id == "_inner_1"

    def test_resolve_body_item_passthrough_for_normal_item(
        self, toledo, respx_mock, content_item_payload
    ):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/_c_1").respond(
            json=content_item_payload
        )
        resolution = toledo.resolve_body_item("_pk_1", "_c_1")
        # No descent: original and body_item are the same instance
        assert resolution.original is resolution.body_item

    def test_extract_embeds_rewrites_anchors(self):
        html = (
            '<a data-bbfile=\'{"displayName": "Notes", "resourceUrl": "https://x/n"}\''
            ' data-bbtype="file">placeholder</a>'
        )
        rewritten, embeds = ToledoClient.extract_embeds(html)
        assert len(embeds) == 1
        assert embeds[0].url == "https://x/n"
        # The data-bbfile marker is gone and href is set
        assert "data-bbfile" not in rewritten
        assert 'href="https://x/n"' in rewritten

    def test_extract_embeds_empty_html(self):
        assert ToledoClient.extract_embeds("") == ("", [])

    def test_fetch_body_and_embeds_full_flow(
        self, toledo, respx_mock, content_item_payload
    ):
        body_html = (
            '<p>before</p>'
            '<a data-bbfile=\'{"displayName":"N","resourceUrl":"https://x/n"}\' '
            'data-bbtype="file">x</a>'
            '<p>after</p>'
        )
        content_item_payload["body"] = {"rawText": body_html}
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/_c_1").respond(
            json=content_item_payload
        )
        result = toledo.fetch_body_and_embeds("_pk_1", "_c_1")
        assert isinstance(result, BodyAndEmbeds)
        assert "before" in result.markdown
        assert len(result.embeds) == 1


class TestWalkContents:
    def test_walks_pre_order_and_recurses_into_folders(self, toledo, respx_mock):
        # ROOT has one folder + one file. The folder has one nested file.
        # walk_contents should yield three nodes, depth 0/0/1.
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={
                "results": [
                    {
                        "id": "_folder_1",
                        "title": "Folder",
                        "contentHandler": "resource/x-bb-folder",
                        "contentDetail": {"resource/x-bb-folder": {"isBbPage": False}},
                    },
                    {
                        "id": "_leaf_root",
                        "title": "Top file",
                        "contentHandler": "resource/x-bb-file",
                    },
                ]
            }
        )
        respx_mock.get(
            f"{ULTRA_API}/courses/_pk_1/contents/_folder_1/children"
        ).respond(
            json={
                "results": [
                    {
                        "id": "_nested_1",
                        "title": "Nested",
                        "contentHandler": "resource/x-bb-file",
                    }
                ]
            }
        )
        nodes = list(toledo.walk_contents("_pk_1"))
        assert [n.id for n in nodes] == ["_folder_1", "_nested_1", "_leaf_root"]
        assert nodes[0].depth == 0
        assert nodes[1].depth == 1
        assert nodes[2].depth == 0

    def test_walk_stops_at_max_depth(self, toledo, respx_mock):
        # Same shape, but max_depth=1 caps the recursion at top-level children.
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={
                "results": [
                    {
                        "id": "_f",
                        "title": "F",
                        "contentHandler": "resource/x-bb-folder",
                    }
                ]
            }
        )
        nodes = list(toledo.walk_contents("_pk_1", max_depth=1))
        assert [n.id for n in nodes] == ["_f"]

    def test_walk_does_not_descend_into_bb_pages(self, toledo, respx_mock, bb_page_payload):
        # BB Pages are leaves from a navigation point of view — their single
        # ultraDocumentBody child is handled by fetch_body_and_embeds, not the
        # tree walk.
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={"results": [bb_page_payload]}
        )
        nodes = list(toledo.walk_contents("_pk_1"))
        assert [n.id for n in nodes] == ["_bbpage_1"]


class TestDiscoverFiles:
    def test_classifies_file_leaf(self, toledo, respx_mock, file_leaf_payload):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={"results": [file_leaf_payload]}
        )
        items = toledo.discover_files("_pk_1")
        assert len(items) == 1
        assert items[0].kind == "file"
        assert items[0].filename == "lecture.pdf"
        assert items[0].url == f"{ULTRA_ORIGIN}/bbcswebdav/xid-1"

    def test_classifies_blti_link_as_video_when_kaltura(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={
                "results": [
                    {
                        "id": "_blti_1",
                        "title": "Lecture",
                        "contentHandler": "resource/x-bb-blti-link",
                        "contentDetail": {
                            "resource/x-bb-blti-link": {
                                "url": "https://kaltura/entryid/1_abc/something"
                            }
                        },
                    }
                ]
            }
        )
        items = toledo.discover_files("_pk_1")
        assert items[0].kind == "video"
        assert items[0].kaltura_entry_id == "1_abc"

    def test_blti_link_without_kaltura_url_is_skipped(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={
                "results": [
                    {
                        "id": "_blti_1",
                        "title": "External",
                        "contentHandler": "resource/x-bb-blti-link",
                        "contentDetail": {"resource/x-bb-blti-link": {"url": "https://other/"}},
                    }
                ]
            }
        )
        assert toledo.discover_files("_pk_1") == []

    def test_extracts_embedded_files_from_document_body(self, toledo, respx_mock):
        respx_mock.get(f"{ULTRA_API}/courses/_pk_1/contents/ROOT/children").respond(
            json={
                "results": [
                    {
                        "id": "_doc_1",
                        "title": "Notes",
                        "contentHandler": "resource/x-bb-document",
                        "body": {
                            "rawText": (
                                '<a data-bbfile=\'{"displayName":"a.pdf",'
                                '"resourceUrl":"https://x/a.pdf",'
                                '"linkName":"a.pdf"}\' data-bbtype="file">a</a>'
                            )
                        },
                    }
                ]
            }
        )
        items = toledo.discover_files("_pk_1")
        assert len(items) == 1
        assert items[0].id == "_doc_1@0"
        assert items[0].source_content_id == "_doc_1"
        assert items[0].embed_index == 0

    def test_find_item(self):
        items = [
            FileItem(
                id="a", kind="file", title="A", filename="a", source_content_id="a"
            ),
            FileItem(
                id="b", kind="file", title="B", filename="b", source_content_id="b"
            ),
        ]
        assert ToledoClient.find_item(items, "b").id == "b"
        assert ToledoClient.find_item(items, "missing") is None


class TestKalturaAndDownloads:
    def test_kaltura_widget_session(self, toledo, respx_mock):
        respx_mock.post(f"{KALTURA_API}/session/action/startWidgetSession").respond(
            json={"ks": "ks-token"}
        )
        assert toledo.kaltura_widget_session() == "ks-token"

    def test_kaltura_entry_info(self, toledo, respx_mock):
        respx_mock.post(f"{KALTURA_API}/session/action/startWidgetSession").respond(
            json={"ks": "ks-token"}
        )
        respx_mock.post(f"{KALTURA_API}/baseEntry/action/get").respond(
            json={"id": "1_abc", "downloadUrl": "https://cdn/abc.mp4"}
        )
        entry = toledo.kaltura_entry_info("1_abc")
        assert isinstance(entry, KalturaEntry)
        assert entry.download_url == "https://cdn/abc.mp4"

    def test_resolve_download_url_for_file(self, toledo):
        item = FileItem(
            id="x",
            kind="file",
            title="x",
            filename="x.pdf",
            source_content_id="x",
            url="https://bb/x.pdf",
        )
        assert toledo.resolve_download_url(item) == "https://bb/x.pdf"

    def test_resolve_download_url_for_video_calls_kaltura(self, toledo, respx_mock):
        respx_mock.post(f"{KALTURA_API}/session/action/startWidgetSession").respond(
            json={"ks": "ks-token"}
        )
        respx_mock.post(f"{KALTURA_API}/baseEntry/action/get").respond(
            json={"downloadUrl": "https://cdn/v.mp4"}
        )
        item = FileItem(
            id="v",
            kind="video",
            title="v",
            filename="",
            source_content_id="v",
            kaltura_entry_id="1_abc",
        )
        assert toledo.resolve_download_url(item) == "https://cdn/v.mp4"

    def test_resolve_download_url_video_without_entry_raises(self, toledo):
        item = FileItem(
            id="v", kind="video", title="v", filename="", source_content_id="v"
        )
        with pytest.raises(ValueError, match="kaltura_entry_id"):
            toledo.resolve_download_url(item)

    def test_resolve_download_url_file_without_url_raises(self, toledo):
        item = FileItem(
            id="x", kind="file", title="x", filename="x", source_content_id="x"
        )
        with pytest.raises(ValueError, match="kind=file"):
            toledo.resolve_download_url(item)

    def test_stream_response_writes_bytes_and_returns_filename(
        self, toledo, respx_mock
    ):
        respx_mock.get("https://bb/lecture.pdf").respond(
            content=b"PDF-bytes",
            headers={"content-disposition": 'attachment; filename="real.pdf"'},
        )
        buffer = BytesIO()
        written, server_filename = toledo.stream_response("https://bb/lecture.pdf", buffer)
        assert buffer.getvalue() == b"PDF-bytes"
        assert written == len(b"PDF-bytes")
        assert server_filename == "real.pdf"

    def test_download_file_item_writes_to_disk(self, toledo, respx_mock, tmp_path):
        respx_mock.get("https://bb/x.pdf").respond(content=b"hello")
        item = FileItem(
            id="x",
            kind="file",
            title="x",
            filename="x.pdf",
            source_content_id="x",
            url="https://bb/x.pdf",
        )
        dest = tmp_path / "x.pdf"
        result = toledo.download_file_item(item, dest)
        assert isinstance(result, DownloadResult)
        assert dest.read_bytes() == b"hello"
        assert result.bytes == 5
        assert result.path == str(dest)
