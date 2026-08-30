from datetime import datetime
from typing import Any, Self

from pydantic import Field, computed_field

from kuleuven.models._base import ApiEchoModel, KuleuvenModel
from kuleuven.models.common import Person


def _strip_empty(text: str | None) -> str | None:
    if text is None or text == "":
        return None
    return text


class Course(KuleuvenModel):
    batch_uid: str
    pk: str | None = None
    portal_uuid: str | None = None
    course_uuid: str | None = None
    foundations_id: str | None = None

    display_name: str = ""
    description: str | None = None
    image_url: str | None = None
    external_access_url: str | None = None

    type: str = "course"
    is_available: bool | None = None
    effective_availability: bool | None = None

    academic_year: int | None = None
    semester: str | None = None
    locale: str | None = None
    ultra_status: str | None = None
    course_view_option: str | None = None

    # User-relative (populated when sourced from a membership-shaped endpoint).
    # Role values are surfaced raw: the portal returns long names ("Learner",
    # "Instructor"); Ultra returns single-letter identifiers ("S", "P", "T").
    role: str | None = None
    favorite: bool | None = None
    color: int | None = None
    last_accessed: datetime | None = None
    enrolled_at: datetime | None = None
    user_hidden: bool | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def course_code(self) -> str | None:
        # batchUid format ULTRA-{type}-{realm}-{code}-{year}. The {code}
        # segment is only meaningful for real courses; communities put a
        # placeholder there (often a single letter) we should not surface.
        if self.type != "course":
            return None
        parts = self.batch_uid.split("-")
        if len(parts) >= 5 and parts[0] == "ULTRA":
            return parts[3]
        return None

    @classmethod
    def from_portal(cls, raw: dict) -> Self:
        return cls(
            batch_uid=raw["learningUnitId"],
            portal_uuid=raw["id"],
            display_name=raw["title"],
            image_url=raw.get("imageUrl"),
            external_access_url=raw.get("link"),
            type=raw.get("type", "course"),
            is_available=raw.get("available"),
            academic_year=raw.get("academicYear"),
            semester=raw.get("semester"),
            role=raw.get("role"),
            favorite=raw.get("favorite"),
            color=raw.get("color"),
        )

    @classmethod
    def from_ultra_membership(cls, raw: dict) -> Self:
        course = raw.get("course") or {}
        return cls(
            batch_uid=course.get("batchUid") or course.get("courseId", ""),
            pk=course.get("id"),
            course_uuid=course.get("uuid"),
            foundations_id=course.get("foundationsId"),
            display_name=course.get("displayName") or course.get("name", ""),
            description=_strip_empty(course.get("description")),
            external_access_url=course.get("externalAccessUrl"),
            type="community" if course.get("isOrganization") else "course",
            is_available=course.get("isAvailable"),
            effective_availability=course.get("effectiveAvailability"),
            locale=course.get("locale"),
            ultra_status=course.get("ultraStatus"),
            course_view_option=course.get("courseViewOption"),
            role=raw.get("role"),
            color=raw.get("courseCardColorIndex"),
            last_accessed=raw.get("lastAccessDate"),
            enrolled_at=raw.get("enrollmentDate"),
            user_hidden=raw.get("userHasHidden"),
        )

    @classmethod
    def from_ultra_course(cls, raw: dict) -> Self:
        return cls(
            batch_uid=raw.get("courseId", ""),
            pk=raw.get("id"),
            foundations_id=raw.get("foundationsId"),
            display_name=raw.get("displayName") or raw.get("name", ""),
            description=_strip_empty(raw.get("description")),
            external_access_url=raw.get("externalAccessUrl"),
            type="community" if raw.get("isOrganization") else "course",
            is_available=raw.get("isAvailable"),
            effective_availability=raw.get("effectiveAvailability"),
            locale=raw.get("locale"),
            ultra_status=raw.get("ultraStatus"),
            course_view_option=raw.get("courseViewOption"),
        )

    def merge(self, other: "Course") -> "Course":
        # Field-wise union: self wins where it has a value; other fills in
        # the gaps. Used to join portal + ultra views of the same course.
        merged: dict = {}
        for name in type(self).model_fields:
            self_value = getattr(self, name)
            other_value = getattr(other, name)
            merged[name] = (
                self_value
                if self_value is not None and self_value != ""
                else other_value
            )
        return self.model_copy(update=merged)


class Membership(KuleuvenModel):
    pk: str
    course_pk: str
    user: Person
    role: str | None
    role_bucket: str | None
    is_available: bool | None

    @classmethod
    def from_ultra(cls, raw: dict) -> Self:
        course_role = raw.get("courseRole") or {}
        return cls(
            pk=raw["id"],
            course_pk=raw.get("courseId", ""),
            user=Person.from_ultra_user(raw.get("user") or {}),
            role=course_role.get("identifier") or raw.get("role"),
            role_bucket=course_role.get("roleBucket"),
            is_available=raw.get("isAvailable"),
        )


class Announcement(KuleuvenModel):
    id: str
    course_pk: str
    title: str
    # Raw HTML body (Blackboard's rich-text dialect); render with
    # `toledo.content.render_markdown` for human-readable output.
    body_html: str = Field(exclude=True)
    is_read: bool | None = None
    is_draft: bool | None = None
    created_date: datetime | None = None
    modified_date: datetime | None = None
    creator_user_id: str | None = None
    type: str | None = None
    start_date_restriction: datetime | None = None
    end_date_restriction: datetime | None = None
    position: int | None = None
    permanent: bool | None = None
    push_notify: bool | None = None
    read_tracking: bool | None = None

    @classmethod
    def from_ultra(cls, raw: dict) -> Self:
        body = raw.get("body") or {}
        read_status = raw.get("readStatus") or {}
        return cls(
            id=raw["id"],
            course_pk=raw.get("courseId", ""),
            title=raw.get("title", ""),
            body_html=body.get("rawText", "") or "",
            is_read=read_status.get("isRead"),
            is_draft=raw.get("isDraft"),
            created_date=raw.get("createdDate"),
            modified_date=raw.get("modifiedDate"),
            creator_user_id=raw.get("creatorUserId"),
            type=raw.get("type"),
            start_date_restriction=raw.get("startDateRestriction"),
            end_date_restriction=raw.get("endDateRestriction"),
            position=raw.get("position"),
            permanent=raw.get("permanent"),
            push_notify=raw.get("pushNotify"),
            read_tracking=raw.get("readTracking"),
        )


class Embed(KuleuvenModel):
    # `kind` is derived from the anchor attributes that surround the embed JSON:
    # data-bbtype="embedded-app" carries LTI launch info (Kaltura, etc.); a
    # plain data-bbfile anchor with no bbtype is a file reference. Anything
    # else is passed through as-is so a schema change doesn't drop data.
    kind: str
    title: str
    url: str | None = None
    mime_type: str | None = None
    raw: dict = Field(default_factory=dict)

    @classmethod
    def from_anchor(cls, payload: dict, *, bb_type: str = "") -> Self:
        if bb_type == "embedded-app" or "linkType" in payload:
            return cls(
                kind="lti",
                title=(
                    payload.get("title")
                    or payload.get("displayName")
                    or payload.get("linkName")
                    or ""
                ),
                url=payload.get("url"),
                raw=payload,
            )
        # Many embeds only carry `viewerUrl` (the inline-render path that
        # serves the React document viewer HTML, not the file bytes). Strip
        # the query string when falling back to it so a plain GET on the
        # bbcswebdav path returns the underlying file.
        url = payload.get("resourceUrl")
        if not url:
            viewer = payload.get("viewerUrl")
            if viewer:
                url = viewer.split("?", 1)[0]
        return cls(
            kind="file",
            title=payload.get("displayName") or payload.get("linkName") or "",
            url=url,
            mime_type=payload.get("mimeType"),
            raw=payload,
        )


class FileItem(KuleuvenModel):
    # One downloadable thing — either a Blackboard file (the `resource/x-bb-file`
    # leaf or a `data-bbfile` embed inside a document body), or a Kaltura video
    # surfaced through a `resource/x-bb-blti-link` content item or an
    # `embedded-app` anchor inside a body. The `id` is synthetic: the content PK
    # alone for top-level items, `<content_pk>@<index>` for body embeds, so the
    # CLI can address every downloadable with a single argument. `source_path`
    # is a list rather than a joined string because content titles regularly
    # contain `/` (dates like 26/2/2026).
    id: str
    kind: str
    title: str
    filename: str
    source_content_id: str
    source_path: list[str] = Field(default_factory=list)
    embed_index: int | None = None
    mime_type: str | None = None
    size: int | None = None
    url: str | None = None
    kaltura_entry_id: str | None = None


class ContentNode(KuleuvenModel):
    id: str
    parent_id: str | None
    title: str
    handler: str
    is_bb_page: bool
    depth: int
    position: int | None = None

    @classmethod
    def from_ultra(cls, raw: dict, depth: int) -> Self:
        is_bb_page = (
            raw.get("contentDetail", {})
            .get("resource/x-bb-folder", {})
            .get("isBbPage", False)
        )
        return cls(
            id=raw["id"],
            parent_id=raw.get("parentId"),
            title=raw["title"],
            handler=raw["contentHandler"],
            is_bb_page=bool(is_bb_page),
            depth=depth,
            position=raw.get("position"),
        )


class PortalAdminUrls(ApiEchoModel):
    # Portal admin URLs for one course. Every field is optional because the
    # portal omits ones the user can't act on. ApiEchoModel preserves the
    # camelCase keys the portal returns (and the CLI used to pass through).
    unenroll_url: str | None = Field(default=None, alias="unenrollUrl")
    availability_url: str | None = Field(default=None, alias="availabilityUrl")
    manage_url: str | None = Field(default=None, alias="manageUrl")
    users_url: str | None = Field(default=None, alias="usersUrl")
    notifications_url: str | None = Field(default=None, alias="notificationsUrl")
    grade_center_tool_url: str | None = Field(default=None, alias="gradeCenterToolUrl")
    attempts_download_url: str | None = Field(default=None, alias="attemptsDownloadUrl")
    bizz_ui_language_url: str | None = Field(default=None, alias="bizzUILanguageUrl")
    bizz_ui_enrollments_url: str | None = Field(default=None, alias="bizzUIEnrollmentsUrl")
    bizz_ui_title_and_description_url: str | None = Field(
        default=None, alias="bizzUITitleAndDescriptionUrl"
    )
    bizz_ui_enroll_as_student_url: str | None = Field(
        default=None, alias="bizzUIEnrollAsStudentUrl"
    )
    impex_url: str | None = Field(default=None, alias="impexUrl")
    ects_link: str | None = Field(default=None, alias="ectsLink")
    stm_link: str | None = Field(default=None, alias="stmLink")
    stm_docent_link: str | None = Field(default=None, alias="stmDocentLink")
    migrate_url: str | None = Field(default=None, alias="migrateUrl")


class PortalCourseDetail(KuleuvenModel):
    # Wraps GET /portal/api/enrollments/{batchUid}/{lang}. Most fields land on
    # PortalAdminUrls; the few we care about beyond URLs are lifted onto the
    # top level.
    description: str | None = None
    instructors: list[Person] = Field(default_factory=list)
    admin_urls: PortalAdminUrls = Field(default_factory=PortalAdminUrls)

    @classmethod
    def from_raw(cls, raw: dict) -> Self:
        return cls(
            description=raw.get("description"),
            instructors=[
                Person.from_portal_instructor(item)
                for item in raw.get("instructors") or []
            ],
            admin_urls=PortalAdminUrls.model_validate(raw),
        )


class UltraCourseDetail(KuleuvenModel):
    # Wraps GET /learn/api/v1/courses/{pk}?expand=instructorsMembership,...
    # Carries the same core fields as Course (so callers can merge into the
    # cross-system identity) plus the expanded instructor memberships.
    course: Course
    instructors: list[Person] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict) -> Self:
        return cls(
            course=Course.from_ultra_course(raw),
            instructors=[
                Person.from_ultra_user(item.get("user") or {})
                for item in raw.get("instructorsMembership") or []
            ],
        )


class DownloadResult(KuleuvenModel):
    path: str
    bytes: int
    server_filename: str | None = None


class MemberCounts(ApiEchoModel):
    results: dict[str, int] = Field(default_factory=dict)
    count: int | None = None


class ScheduleItem(ApiEchoModel):
    pass


class AnnouncementCounts(ApiEchoModel):
    posted_count: int | None = Field(default=None, alias="postedCount")
    unread_count: int | None = Field(default=None, alias="unreadCount")


class GradeEntry(ApiEchoModel):
    pass


class DiscussionGenericData(ApiEchoModel):
    # The `genericReadOnlyData` blob on a forum-link content item. Only the
    # due date is typed; the rest rides along on extra="allow".
    due_date: datetime | None = Field(default=None, alias="dueDate")


class DiscussionItem(ApiEchoModel):
    modified_date: datetime | None = Field(default=None, alias="modifiedDate")
    generic_read_only_data: DiscussionGenericData = Field(
        default_factory=DiscussionGenericData, alias="genericReadOnlyData"
    )


class Forum(ApiEchoModel):
    pass


class ForumCounts(ApiEchoModel):
    pass


class ForumMessage(ApiEchoModel):
    pass


class MessageRepliesPaging(ApiEchoModel):
    count: int | None = None
    offset: int | None = None
    limit: int | None = None
    next_page: str | None = Field(default=None, alias="nextPage")


class MessageRepliesPage(ApiEchoModel):
    paging: MessageRepliesPaging = Field(default_factory=MessageRepliesPaging)
    results: list[ForumMessage] = Field(default_factory=list)


class ContentItem(ApiEchoModel):
    # Raw content item shape from /courses/{pk}/contents/{id}. ApiEchoModel
    # because the contentDetail blob is handler-discriminated and the CLI
    # passes it through; preserving camelCase keeps the existing JSON output.
    id: str | None = None
    parent_id: str | None = Field(default=None, alias="parentId")
    title: str | None = None
    content_handler: str | None = Field(default=None, alias="contentHandler")
    content_detail: dict[str, Any] = Field(
        default_factory=dict, alias="contentDetail"
    )
    body: dict[str, Any] = Field(default_factory=dict)
    visibility: str | None = None
    # /contents/{id} returns an ISO string; the children @view=Summary endpoint
    # returns epoch milliseconds. Pydantic parses both into a datetime.
    modified_date: datetime | None = Field(default=None, alias="modifiedDate")
    position: int | None = None
    description: str | None = None
    state: str | None = None


class BodyResolution(KuleuvenModel):
    # Curated pair: (original, body_item). For a BB Page the body_item is
    # the single child with the HTML; for everything else they coincide.
    original: ContentItem
    body_item: ContentItem


class BodyAndEmbeds(KuleuvenModel):
    original: ContentItem
    body_item: ContentItem
    markdown: str = ""
    embeds: list[Embed] = Field(default_factory=list)


class KalturaEntry(ApiEchoModel):
    # Kaltura entry metadata as returned by baseEntry.get. Lots of fields;
    # leave it as a permissive echo and surface the two we read directly.
    id: str | None = None
    download_url: str | None = Field(default=None, alias="downloadUrl")
    name: str | None = None
