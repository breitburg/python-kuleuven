import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterator

import httpx
from bs4 import BeautifulSoup
from markitdown import MarkItDown

from kuleuven.models import (
    Announcement,
    AnnouncementCounts,
    BodyAndEmbeds,
    BodyResolution,
    ContentItem,
    ContentNode,
    Course,
    DiscussionItem,
    DownloadResult,
    Embed,
    FileItem,
    Forum,
    ForumCounts,
    ForumMessage,
    GradeEntry,
    KalturaEntry,
    MemberCounts,
    Membership,
    MessageRepliesPage,
    PortalCourseDetail,
    ScheduleItem,
    UltraCourseDetail,
)
from kuleuven.session import TOLEDO_ORIGIN, ULTRA_ORIGIN

PORTAL_ENROLLMENTS_URL = f"{TOLEDO_ORIGIN}/portal/api/enrollments"
ULTRA_API = f"{ULTRA_ORIGIN}/learn/api/v1"
KALTURA_PARTNER_ID = 2375821
KALTURA_API = "https://www.kaltura.com/api_v3/service"
KALTURA_CDN = "https://cdnapisec.kaltura.com"

_markitdown = MarkItDown()
_ENTRY_ID_PATTERN = re.compile(r"/entryid/([^/]+)/?")
_FILENAME_HEADER_PATTERN = re.compile(
    r"filename\*=UTF-8''(?P<utf8>[^;]+)|filename=\"?(?P<plain>[^\";]+)\"?", re.IGNORECASE
)


def _kaltura_entry_id(url: str | None) -> str | None:
    if not url:
        return None
    match = _ENTRY_ID_PATTERN.search(url)
    return match.group(1) if match else None


def _filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    match = _FILENAME_HEADER_PATTERN.search(value)
    if match is None:
        return None
    encoded = match.group("utf8")
    if encoded:
        from urllib.parse import unquote

        return unquote(encoded)
    return match.group("plain")


class ToledoClient:
    def __init__(self, session) -> None:
        self.http_client: httpx.Client = session.http_client

    def fetch_user_pk(self) -> str:
        response = self.http_client.get(f"{ULTRA_API}/users/me")
        response.raise_for_status()
        return response.json()["id"]

    def list_portal_courses(self) -> list[Course]:
        response = self.http_client.get(PORTAL_ENROLLMENTS_URL)
        response.raise_for_status()
        return [Course.from_portal(item) for item in response.json()]

    def list_ultra_courses(self, user_pk: str | None = None) -> list[Course]:
        if user_pk is None:
            user_pk = self.fetch_user_pk()
        response = self.http_client.get(
            f"{ULTRA_API}/users/{user_pk}/memberships",
            params={
                "expand": "course.effectiveAvailability,course.permissions,courseRole",
                "includeCount": "true",
                "limit": "10000",
            },
        )
        response.raise_for_status()
        return [Course.from_ultra_membership(item) for item in response.json()["results"]]

    def fetch_portal_detail(
        self, batch_uid: str, language: str = "en"
    ) -> PortalCourseDetail:
        response = self.http_client.get(
            f"{PORTAL_ENROLLMENTS_URL}/{batch_uid}/{language}"
        )
        response.raise_for_status()
        return PortalCourseDetail.from_raw(response.json())

    def fetch_ultra_course(self, course_pk: str) -> UltraCourseDetail:
        # Use the expanded shape so callers get instructorsMembership in one round-trip.
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}",
            params={
                "expand": "instructorsMembership,instructorsMembership.courseRole,effectiveAvailability,isChild"
            },
        )
        response.raise_for_status()
        return UltraCourseDetail.from_raw(response.json())

    def fetch_members(
        self,
        course_pk: str,
        *,
        role_bucket: str | None = None,
        available: bool | None = None,
        limit: int = 1000,
    ) -> list[Membership]:
        params: dict = {
            "expand": "user.profile,courseRole",
            "limit": str(limit),
        }
        if role_bucket is not None:
            params["roleBucket"] = role_bucket
        if available is not None:
            params["membershipAvailable"] = "true" if available else "false"
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/memberships", params=params
        )
        response.raise_for_status()
        return [Membership.from_ultra(item) for item in response.json()["results"]]

    def fetch_member_counts(self, course_pk: str) -> MemberCounts:
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/memberships/counts",
            params={"membershipAvailable": "true"},
        )
        response.raise_for_status()
        return MemberCounts.model_validate(response.json())

    def fetch_schedule(
        self,
        course_pk: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[ScheduleItem]:
        params: dict = {"sort": "location(desc)"}
        if start is not None:
            params["startTime"] = start.isoformat()
        if end is not None:
            params["endTime"] = end.isoformat()
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/schedule", params=params
        )
        response.raise_for_status()
        return [
            ScheduleItem.model_validate(item)
            for item in response.json().get("results", [])
        ]

    def fetch_announcements(
        self, course_pk: str, *, limit: int = 100, offset: int = 0
    ) -> list[Announcement]:
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/announcements",
            params={"limit": str(limit), "offset": str(offset)},
        )
        response.raise_for_status()
        return [
            Announcement.from_ultra(item)
            for item in response.json().get("results", [])
        ]

    def fetch_announcement_counts(self, course_pk: str) -> AnnouncementCounts:
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/announcements/counts"
        )
        response.raise_for_status()
        return AnnouncementCounts.model_validate(response.json())

    def fetch_user_grades(
        self,
        course_pk: str,
        user_pk: str,
        *,
        include_no_grade_items: bool = True,
        limit: int = 200,
    ) -> list[GradeEntry]:
        # Each result merges per-user grade state (displayGrade, lastAttempt,
        # submissionStatus) with the column it belongs to (expanded inline).
        # `includeNoGradeItems=true` surfaces ungraded items so a student can
        # see "Unopened" rows the same way the Ultra UI does.
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/gradebook/grades",
            params={
                "userId": user_pk,
                "limit": str(limit),
                "offset": "0",
                "includeNoGradeItems": "true" if include_no_grade_items else "false",
                "expand": "lastAttempt,column,submissionStatus,hasAttemptOrGradeFeedback,attemptsLeft",
            },
        )
        response.raise_for_status()
        return [
            GradeEntry.model_validate(item)
            for item in response.json().get("results", [])
        ]

    def fetch_my_grades(self, course_pk: str, **kwargs) -> list[GradeEntry]:
        return self.fetch_user_grades(course_pk, self.fetch_user_pk(), **kwargs)

    def list_discussions(
        self, course_pk: str, *, limit: int = 100
    ) -> list[DiscussionItem]:
        # Ultra surfaces course discussions as content items under the virtual
        # `INTERACTIVE` parent, with handler `resource/x-bb-forumlink`. The
        # nested contentDetail carries `conferenceId` (discussion board) and
        # `id` (forumId), which the /discussionboards/.../forums endpoints
        # consume. The discussionboard segment can be `default` regardless of
        # the actual conferenceId — Ultra resolves it server-side.
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/contents/INTERACTIVE/children",
            params={"@view": "Summary", "limit": str(limit)},
        )
        response.raise_for_status()
        return [
            DiscussionItem.model_validate(item)
            for item in response.json().get("results", [])
            if item.get("contentHandler") == "resource/x-bb-forumlink"
        ]

    def fetch_forum(self, course_pk: str, forum_id: str) -> Forum:
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/discussionboards/default/forums/{forum_id}"
        )
        response.raise_for_status()
        return Forum.model_validate(response.json())

    def fetch_forum_counts(self, course_pk: str, forum_id: str) -> ForumCounts:
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/discussionboards/default/forums/{forum_id}/counts"
        )
        response.raise_for_status()
        return ForumCounts.model_validate(response.json())

    def list_forum_messages(
        self, course_pk: str, forum_id: str, *, limit: int = 1000
    ) -> list[ForumMessage]:
        # Top-level messages in the forum. For threaded discussions the root
        # message's `messageStatus.totalCount` gives the full descendant count;
        # use list_message_replies() to drill in.
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/discussionboards/default/forums/{forum_id}/messages",
            params={"limit": str(limit)},
        )
        response.raise_for_status()
        return [
            ForumMessage.model_validate(item)
            for item in response.json().get("results", [])
        ]

    def list_message_replies(
        self,
        course_pk: str,
        forum_id: str,
        message_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        sort: str = "draft(desc),postDate(desc)",
    ) -> MessageRepliesPage:
        # Returns the full envelope (with `paging.nextPage`) so callers can
        # page through long threads without re-deriving the URL.
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/discussionboards/default/forums/{forum_id}/messages/{message_id}/replies",
            params={"limit": str(limit), "offset": str(offset), "sort": sort},
        )
        response.raise_for_status()
        return MessageRepliesPage.model_validate(response.json())

    def set_favorite(self, portal_uuid: str, favorite: bool) -> None:
        response = self.http_client.patch(
            f"{PORTAL_ENROLLMENTS_URL}/{portal_uuid}",
            json={"favorite": favorite},
        )
        response.raise_for_status()

    @staticmethod
    def resolve(courses: list[Course], ref: str) -> list[Course]:
        matches: list[Course] = []
        for course in courses:
            if (
                course.portal_uuid == ref
                or course.batch_uid == ref
                or course.pk == ref
                or (course.course_uuid is not None and course.course_uuid == ref)
            ):
                return [course]
            code = course.course_code
            if code is not None and code.lower() == ref.lower():
                matches.append(course)
        return matches

    def fetch_content(self, course_pk: str, content_id: str) -> ContentItem:
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/contents/{content_id}",
            params={"@view": "Summary"},
        )
        response.raise_for_status()
        return ContentItem.model_validate(response.json())

    def fetch_children(
        self,
        course_pk: str,
        parent_id: str,
        *,
        limit: int = 1000,
    ) -> list[ContentItem]:
        response = self.http_client.get(
            f"{ULTRA_API}/courses/{course_pk}/contents/{parent_id}/children",
            params={"@view": "Summary", "limit": str(limit)},
        )
        response.raise_for_status()
        return [
            ContentItem.model_validate(item)
            for item in response.json().get("results", [])
        ]

    @staticmethod
    def is_bb_page(item: ContentItem) -> bool:
        return bool(
            (item.content_detail or {})
            .get("resource/x-bb-folder", {})
            .get("isBbPage", False)
        )

    def resolve_body_item(
        self, course_pk: str, content_id: str
    ) -> BodyResolution:
        # For a BB Page, body_item is the single child that holds the HTML.
        # For everything else the two are the same.
        original = self.fetch_content(course_pk, content_id)
        if not ToledoClient.is_bb_page(original):
            return BodyResolution(original=original, body_item=original)
        body_child = ToledoClient.pick_bb_page_child(
            self.fetch_children(course_pk, content_id, limit=10)
        )
        if body_child is None:
            return BodyResolution(original=original, body_item=original)
        return BodyResolution(original=original, body_item=body_child)

    @staticmethod
    def pick_bb_page_child(children: list[ContentItem]) -> ContentItem | None:
        # The classic BB Page has one child literally titled `ultraDocumentBody`.
        # Some courses, though, wrap a real `resource/x-bb-document` (with its
        # own title — often the same as the page) as the sole child instead.
        # Either shape is a single-child wrapper, so fall back to the sole child
        # when the named marker isn't present. Multiple children is ambiguous
        # and not a shape Blackboard emits for BB Pages, so leave it untouched.
        for child in children:
            if child.title == "ultraDocumentBody":
                return child
        if len(children) == 1:
            return children[0]
        return None

    @staticmethod
    def extract_embeds(html: str) -> tuple[str, list[Embed]]:
        # Walks the BB rich-text dialect, lifts embedded files / LTI launches out
        # into structured records, and rewrites the inert <a data-bbfile> markers
        # into normal <a href> anchors so the markdown conversion produces a
        # readable link instead of an empty placeholder.
        if not html:
            return "", []
        soup = BeautifulSoup(html, "html.parser")
        embeds: list[Embed] = []
        for anchor in soup.find_all("a", attrs={"data-bbfile": True}):
            try:
                payload = json.loads(anchor["data-bbfile"])
            except json.JSONDecodeError:
                continue
            embed = Embed.from_anchor(payload, bb_type=anchor.get("data-bbtype", ""))
            embeds.append(embed)
            anchor.string = embed.title or embed.url or ""
            if embed.url:
                anchor["href"] = embed.url
            del anchor["data-bbfile"]
            if anchor.has_attr("data-bbtype"):
                del anchor["data-bbtype"]
        return str(soup), embeds

    @staticmethod
    def render_markdown(html: str) -> str:
        cleaned, _ = ToledoClient.extract_embeds(html)
        if not cleaned.strip():
            return ""
        result = _markitdown.convert_stream(
            BytesIO(cleaned.encode("utf-8")), file_extension=".html"
        )
        return result.text_content.strip()

    def fetch_body_and_embeds(
        self, course_pk: str, content_id: str
    ) -> BodyAndEmbeds:
        # Convenience for the CLI: one round-trip pair that returns the original
        # item, the body-bearing item (post-descent), the rendered markdown, and
        # the parsed embeds. Items without HTML bodies return ("", []).
        resolution = self.resolve_body_item(course_pk, content_id)
        raw_text = (resolution.body_item.body or {}).get("rawText", "") or ""
        cleaned, embeds = ToledoClient.extract_embeds(raw_text)
        markdown = ""
        if cleaned.strip():
            result = _markitdown.convert_stream(
                BytesIO(cleaned.encode("utf-8")), file_extension=".html"
            )
            markdown = result.text_content.strip()
        return BodyAndEmbeds(
            original=resolution.original,
            body_item=resolution.body_item,
            markdown=markdown,
            embeds=embeds,
        )

    def walk_contents(
        self,
        course_pk: str,
        *,
        parent_id: str = "ROOT",
        max_depth: int | None = None,
    ) -> Iterator[ContentNode]:
        yield from self._walk(course_pk, parent_id, depth=0, max_depth=max_depth)

    def _walk(
        self,
        course_pk: str,
        parent_id: str,
        depth: int,
        max_depth: int | None,
    ) -> Iterator[ContentNode]:
        if max_depth is not None and depth >= max_depth:
            return
        for item in self.fetch_children(course_pk, parent_id):
            node = _content_item_to_node(item, depth=depth)
            yield node
            if node.handler == "resource/x-bb-lesson" or (
                node.handler == "resource/x-bb-folder" and not node.is_bb_page
            ):
                yield from self._walk(course_pk, node.id, depth + 1, max_depth)

    def discover_files(self, course_pk: str) -> list[FileItem]:
        # One-pass walk that classifies every downloadable: native file leaves,
        # files embedded in document bodies, and Kaltura videos reached either
        # through a top-level BLTI link or an embedded-app anchor inside a body.
        # `source_path` is the slash-joined title chain so `files sync` can
        # mirror the course structure on disk.
        items: list[FileItem] = []

        def visit(parent_id: str, parent_titles: list[str]) -> None:
            children = self.fetch_children(course_pk, parent_id)
            for child in children:
                node = _content_item_to_node(child, depth=len(parent_titles))
                chain = parent_titles + [node.title]

                if node.handler == "resource/x-bb-file":
                    items.append(_from_file_leaf(child, node, parent_titles))
                    continue

                if node.handler == "resource/x-bb-blti-link":
                    blti_item = _from_blti_link(child, node, parent_titles)
                    if blti_item is not None:
                        items.append(blti_item)
                    continue

                if node.handler == "resource/x-bb-document":
                    body = (child.body or {}).get("rawText", "") or ""
                    items.extend(_from_body_embeds(node, body, chain))
                    continue

                if node.handler == "resource/x-bb-folder" and ToledoClient.is_bb_page(child):
                    inner = ToledoClient.pick_bb_page_child(
                        self.fetch_children(course_pk, node.id, limit=10)
                    )
                    if inner is not None:
                        body = (inner.body or {}).get("rawText", "") or ""
                        items.extend(_from_body_embeds(node, body, chain))
                    continue

                if node.handler in {"resource/x-bb-folder", "resource/x-bb-lesson"}:
                    visit(node.id, chain)

        visit("ROOT", [])
        return items

    def kaltura_widget_session(self) -> str:
        response = self.http_client.post(
            f"{KALTURA_API}/session/action/startWidgetSession",
            data={"widgetId": f"_{KALTURA_PARTNER_ID}", "format": "1"},
        )
        response.raise_for_status()
        return response.json()["ks"]

    def kaltura_entry_info(self, entry_id: str) -> KalturaEntry:
        ks = self.kaltura_widget_session()
        response = self.http_client.post(
            f"{KALTURA_API}/baseEntry/action/get",
            data={"entryId": entry_id, "ks": ks, "format": "1"},
        )
        response.raise_for_status()
        return KalturaEntry.model_validate(response.json())

    def resolve_download_url(self, item: FileItem) -> str:
        if item.kind == "video":
            if item.kaltura_entry_id is None:
                raise ValueError(
                    f"FileItem {item.id} has kind=video but no kaltura_entry_id"
                )
            info = self.kaltura_entry_info(item.kaltura_entry_id)
            if not info.download_url:
                raise RuntimeError(
                    f"Kaltura entry {item.kaltura_entry_id} has no downloadUrl"
                )
            return info.download_url
        if item.url is None:
            raise ValueError(f"FileItem {item.id} has kind=file but no url")
        return item.url

    def resolve_signed_url(self, item: FileItem) -> str:
        # Resolve a standalone download URL — one that can be fetched without our
        # session cookies. Kaltura already returns CDN URLs; bbcswebdav 302s through
        # to a short-lived signed S3 URL, so HEAD-follow and return the final hop.
        download_url = self.resolve_download_url(item)
        if item.kind == "video":
            return download_url
        response = self.http_client.head(download_url, follow_redirects=True)
        response.raise_for_status()
        return str(response.url)

    def stream_response(
        self, url: str, dest_writable
    ) -> tuple[int, str | None]:
        # Stream a URL's body into any binary writable (a file, sys.stdout.buffer,
        # an io.BytesIO). Returns (bytes_written, server_supplied_filename_or_None).
        # Bb's bbcswebdav URLs 302 to a per-tenant `alt-*.blackboard.com` host, so
        # opt in to redirect following per-request — works whether or not the
        # caller's client has follow_redirects enabled.
        with self.http_client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            server_filename = _filename_from_content_disposition(
                response.headers.get("content-disposition")
            )
            written = 0
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                dest_writable.write(chunk)
                written += len(chunk)
        return written, server_filename

    def stream_download(self, url: str, dest_path: Path) -> tuple[int, str | None]:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as output:
            return self.stream_response(url, output)

    def download_file_item(self, item: FileItem, dest_path: Path) -> DownloadResult:
        download_url = self.resolve_download_url(item)
        written, server_filename = self.stream_download(download_url, dest_path)
        return DownloadResult(
            path=str(dest_path),
            bytes=written,
            server_filename=server_filename,
        )

    def stream_file_item(
        self, item: FileItem, dest_writable
    ) -> tuple[int, str | None]:
        download_url = self.resolve_download_url(item)
        return self.stream_response(download_url, dest_writable)

    @staticmethod
    def find_item(items: list[FileItem], file_id: str) -> FileItem | None:
        for item in items:
            if item.id == file_id:
                return item
        return None


def _content_item_to_node(item: ContentItem, depth: int) -> ContentNode:
    detail = item.content_detail or {}
    is_bb_page = bool(
        (detail.get("resource/x-bb-folder") or {}).get("isBbPage", False)
    )
    return ContentNode(
        id=item.id or "",
        parent_id=item.parent_id,
        title=item.title or "",
        handler=item.content_handler or "",
        is_bb_page=is_bb_page,
        depth=depth,
        position=item.position,
    )


def _from_file_leaf(item: ContentItem, node: ContentNode, path: list[str]) -> FileItem:
    file_meta = (
        (item.content_detail or {}).get("resource/x-bb-file") or {}
    ).get("file") or {}
    permanent_url = file_meta.get("permanentUrl", "")
    return FileItem(
        id=node.id,
        kind="file",
        title=node.title,
        filename=file_meta.get("fileName") or node.title,
        source_content_id=node.id,
        source_path=list(path),
        embed_index=None,
        mime_type=file_meta.get("mimeType"),
        size=file_meta.get("fileSize"),
        url=(ULTRA_ORIGIN + permanent_url) if permanent_url else None,
        kaltura_entry_id=None,
    )


def _from_blti_link(
    item: ContentItem, node: ContentNode, path: list[str]
) -> FileItem | None:
    blti = (item.content_detail or {}).get("resource/x-bb-blti-link") or {}
    entry_id = _kaltura_entry_id(blti.get("url"))
    if entry_id is None:
        return None
    return FileItem(
        id=node.id,
        kind="video",
        title=node.title,
        filename="",
        source_content_id=node.id,
        source_path=list(path),
        embed_index=None,
        mime_type="video/mp4",
        size=None,
        url=None,
        kaltura_entry_id=entry_id,
    )


def _from_body_embeds(
    node: ContentNode, body_html: str, path: list[str]
) -> list[FileItem]:
    _, embeds = ToledoClient.extract_embeds(body_html)
    items: list[FileItem] = []
    for index, embed in enumerate(embeds):
        synthetic_id = f"{node.id}@{index}"
        if embed.kind == "file":
            link_name = embed.raw.get("linkName") if embed.raw else None
            items.append(
                FileItem(
                    id=synthetic_id,
                    kind="file",
                    title=embed.title,
                    filename=link_name or embed.title or "",
                    source_content_id=node.id,
                    source_path=list(path),
                    embed_index=index,
                    mime_type=embed.mime_type,
                    size=None,
                    url=embed.url,
                    kaltura_entry_id=None,
                )
            )
            continue
        if embed.kind == "lti":
            entry_id = _kaltura_entry_id(embed.url)
            if entry_id is None:
                continue
            items.append(
                FileItem(
                    id=synthetic_id,
                    kind="video",
                    title=embed.title,
                    filename="",
                    source_content_id=node.id,
                    source_path=list(path),
                    embed_index=index,
                    mime_type="video/mp4",
                    size=None,
                    url=None,
                    kaltura_entry_id=entry_id,
                )
            )
    return items
