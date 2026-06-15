# python-kuleuven

CLI, MCP server, and Python client for KU Leuven. Signs in via the reverse-engineered SAML2 SSO flow against `idp.kuleuven.be` and gives you one session that works against `toledo.kuleuven.be/portal/api/*` (the portal), `ultra.edu.kuleuven.cloud/learn/api/v1/*` (Blackboard Ultra), and `kurt3.ghum.kuleuven.be/api/*` (the KURT study-space reservation system).

See [`docs/AUTH.md`](docs/AUTH.md) for the SAML flow and [`docs/DATA.md`](docs/DATA.md) for the REST surface.

## Installation

Requires Python 3.13 or newer. The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```sh
uv sync
```

The `kuleuven` command becomes available inside the project environment. Run it with `uv run kuleuven …` or activate the venv first.

## Quickstart

Sign in, list your courses, and pull the files for one of them.

```sh
# 1. Authenticate. Credentials can also come from $KULEUVEN_USERNAME / $KULEUVEN_PASSWORD or a .env file.
kuleuven session start

# 2. List the courses on your portal dashboard.
kuleuven toledo courses list --type course

# 3. Download every file and video in a course, mirroring its tree on disk.
kuleuven toledo courses files sync EX101a --into ./downloads --skip-videos
```

Every command writes one JSON object to stdout, success or failure, so the output is pipeline-friendly:

```sh
kuleuven toledo courses list --type course | jq '.items[].course_code'
```

## Concepts

### Two backends, one session

Toledo is a single front door over two backends. The portal at `toledo.kuleuven.be` is a thin Plone-backed dashboard that hosts the curated course grid, the notification feed, and the upcoming-events list. Clicking into any course launches Blackboard Ultra at `ultra.edu.kuleuven.cloud`, which is where the actual content tree, assignments, members, grades, and files live. Each backend has its own session cookie and its own REST surface. The CLI hides this split for everyday use — one `kuleuven session start` establishes both — but exposes both as needed.

### Identifier zoo

The two systems share data but speak different vocabularies. The same course is identified by `learning_unit_id` on the portal (a string like `ULTRA-B-KUL-EX101a-2526`, called the batchUid) and by `id` in Blackboard (a primary key like `_100000_1`). The portal additionally has its own UUID per enrollment, and Ultra additionally has a UUID per course. The library treats all five as valid references to the same `Course` object; `kuleuven toledo courses show` accepts any of them. Course codes like `EX101a` are derived from the batchUid and are accepted case-insensitively. The course-code form is convenient but ambiguous when both an active and an archived year exist; the CLI resolves to the portal-visible course first, then falls back to Ultra if no portal match is found.

People are identified by their KU Leuven q-uid (the `userName` in Blackboard, e.g. `q1234567`). The portal also surfaces the student-facing r-uid (`r0123456`) on the SAML side, and Blackboard adds its own primary key plus a UUID and a foundations identifier. The q-uid is the join key across portal-issued and Blackboard-issued identity records.

### Content tree

The content tree of a course is recursive. Each item has a `parentId` chain rooted at `ROOT` and a `contentHandler` that classifies it (`resource/x-bb-folder`, `resource/x-bb-document`, `resource/x-bb-file`, `resource/x-bb-blti-link`, `resource/x-bb-lesson`, etc.). A particular wrinkle: a content item with `contentHandler: resource/x-bb-folder` and `contentDetail."resource/x-bb-folder".isBbPage: true` is not really a folder — it is an Ultra Document, a single-child wrapper around the inner payload. The classic shape carries an HTML child literally titled `ultraDocumentBody`; some courses instead wrap a real `resource/x-bb-document` whose title mirrors the page. The tree walker treats Ultra Documents as leaves and `kuleuven toledo courses content show`, `kuleuven toledo courses content embeds`, and `kuleuven toledo courses files list` descend into the inner child in either shape automatically.

## CLI reference

### Conventions

Every CLI command writes exactly one JSON object to stdout. Success is wrapped as `{"status": "ok", ...}`. Failures are wrapped as `{"status": "error", "code": "<stable code>", ...}` and use these exit codes:

| Exit code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Auth or session failure, downstream HTTP error, or download failure. |
| `2` | Bad input — unknown reference, ambiguous match, missing argument. |

Errors go to stdout, not stderr, so a pipeline only needs to parse one stream. The one exception is `kuleuven toledo courses files fetch --out -`, which streams binary bytes to stdout and reports errors on stderr.

Credentials and the TOTP code are accepted via flags, environment variables, or a `.env` file in the current directory. They are never written to disk. The only thing persisted is the session cookie jar, at `platformdirs.user_data_path("kuleuven") / "cookies.json"` with `0600` permissions.

The global environment variables:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `KULEUVEN_USERNAME` | `session start` | KU Leuven username (r-uid or q-uid). |
| `KULEUVEN_PASSWORD` | `session start` | KU Leuven password. |
| `KULEUVEN_TOTP` | `session start` | 6-digit TOTP code for two-factor sign-in. |
| `KULEUVEN_AUTH_DEVICE` | `session start` | KU Leuven Authenticator device to push to: a name, 1-based index, or `most-recent`. |

### Session

#### `kuleuven session start`

Signs in to the portal, Ultra, and KURT and persists the session cookies.

```text
kuleuven session start [--username U] [--password P] [--totp CODE] [--device D]
```

| Flag | Env var | Default | Description |
| --- | --- | --- | --- |
| `--username` | `KULEUVEN_USERNAME` | prompted on TTY | KU Leuven r-uid or q-uid. |
| `--password` | `KULEUVEN_PASSWORD` | prompted on TTY | Account password. |
| `--totp` | `KULEUVEN_TOTP` | prompted on TTY | 6-digit TOTP, only used when the IdP serves a TOTP form. |
| `--device` | `KULEUVEN_AUTH_DEVICE` | `most-recent` | KU Leuven Authenticator device to push to: a device name (case-insensitive), a 1-based index, or `most-recent`. |

Sign-in walks three SAML handshakes in sequence: the Toledo portal SP (sets `_shibsession_*` on `toledo.kuleuven.be`), the Blackboard Ultra SP (sets `BbRouter` and friends on `ultra.edu.kuleuven.cloud`), and the KURT SP (sets `_shibsession_*` on `kurt3.ghum.kuleuven.be`). All three sessions are required to reach the full API surface, so they are established together. The Ultra and KURT round-trips reuse the IdP session minted by the portal step and do not prompt for credentials a second time. Every call runs fresh SAML flows — any existing SP cookies are dropped before bootstrap so credentials are actually re-submitted. The IdP's `rememberDevice` cookie is kept across runs, so 2FA only happens once per device.

The second factor depends on the account's enrolment. A TOTP-enrolled account is served a code form and consumes `--totp`. An account on the **KU Leuven Authenticator** smartphone app is served a device picker: the command sends a push to the chosen device (`--device`), prints `Waiting for approval on <device>...` to stderr, and blocks until you approve on the device, then completes. The wait times out after 120 seconds. Progress text goes to stderr; stdout stays a single JSON object.

Exit codes: `0` on success; `1` with `code: "invalid_credentials"`, `"auth_failed"`, `"totp_required"`, `"approval_timeout"`, `"unparseable_device_timestamp"`, or `"http_error"`; `2` with `code: "missing_credentials"` (stdin is not a TTY and neither flags nor env vars supply credentials) or `"unknown_device"` (`--device` matches no enrolled device — the error JSON lists the devices).

```sh
kuleuven session start --device "My phone"
```

```json
{
  "status": "ok",
  "session": {
    "attributes": {
      "KULMoreUnifiedUID": "q1234567",
      "affiliation": "member@kuleuven.be;student@kuleuven.be",
      "entitlement": "urn:mace:kuleuven.be:entitlement:toledo",
      "uid": "r0123456",
      "unscoped-affiliation": "member;student"
    },
    "expires_in_minutes": 2880,
    "authenticated_at": "2026-01-01T12:00:00.000Z",
    "authentication_context_class": "https://nextauth.com"
  }
}
```

#### `kuleuven session status`

Reports whether the persisted session is still valid.

```text
kuleuven session status
```

The `authentication_context_class` field is the canonical signal for whether the session was 2FA-elevated; `MobileTwoFactorContract` confirms it was. Exits `1` with `reason: "no_session"` if nothing is saved, or `reason: "expired"` if the saved session no longer works.

```json
{
  "authenticated": true,
  "session": {
    "attributes": { "uid": "r0123456", "...": "..." },
    "expires_in_minutes": 2845,
    "authenticated_at": "2026-01-01T12:00:00.000Z",
    "authentication_context_class": "urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract"
  }
}
```

#### `kuleuven session end`

Deletes the saved session. Idempotent — `removed` is `false` if there was nothing to delete.

```text
kuleuven session end
```

```json
{ "status": "ok", "removed": true }
```

#### `kuleuven session raw`

Sends a pre-authenticated HTTP request to any URL and prints the response as JSON. The escape hatch for endpoints the higher-level commands do not cover yet. Lives under `session` because it uses the persisted session cookies and works against any host the cookie jar can authenticate against (Toledo, Ultra, KURT, …).

```text
kuleuven session raw <METHOD> <URL> [--body STRING]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--body` | — | Request body, sent as `application/json`. Query parameters belong in the URL. |

The saved cookie jar is attached to the request; cookies set by the response are persisted back. The response is wrapped as `{"status": "ok", "response": {…}}`, where the inner object carries `status_code`, the final `url`, all response `headers`, and the body. The body is parsed JSON when the response content type is JSON, kept as text for textual responses, and reported as `{"body_kind": "binary", "size": N}` for everything else. Non-2xx HTTP responses are returned the same way — they are not CLI errors. Exits `1` with `code: "http_error"` only for network failures. Authentication state is not checked; whatever the server returns to the cookies you have is what you get.

```sh
kuleuven session raw GET 'https://toledo.kuleuven.be/portal/api/upcoming'
```

```json
{
  "status": "ok",
  "response": {
    "status_code": 200,
    "url": "https://toledo.kuleuven.be/portal/api/upcoming",
    "headers": { "content-type": "application/json;charset=UTF-8" },
    "body_kind": "json",
    "body": [
      {
        "start": 1900000000000,
        "end":   1900007200000,
        "name":  "Other Example",
        "location": { "url": "...", "mnemonic": "BLD1", "roomNumber": "01.1234" },
        "source": { "learningUnitId": "ULTRA-B-KUL-EX102a-2526", "color": 13 }
      }
    ]
  }
}
```

### Toledo

The `kuleuven toledo` group covers the Toledo portal and Blackboard Ultra: courses, content, and files. A note on course references: every course command takes a single positional `<ref>` that accepts any of the five identifier forms — course code, batchUid, Blackboard PK, portal UUID, or Ultra course UUID. When the same code matches multiple academic years, the command exits `2` with `code: "ambiguous"` and lists the candidates so a more specific reference can be chosen.

#### `kuleuven toledo courses list`

Lists the courses and communities the user is enrolled in.

```text
kuleuven toledo courses list [--favorite] [--type course|community] [--semester SEMESTER1|SEMESTER2|UNKNOWN] [--year YYYY] [--all]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--favorite` | off | Only courses marked as favourite on the portal. |
| `--type` | — | Filter by `course` or `community`. |
| `--semester` | — | `SEMESTER1`, `SEMESTER2`, or `UNKNOWN`. |
| `--year` | — | Academic year code, e.g. `2526` for 2025/2026. |
| `--all` | off | Use Ultra memberships instead of the portal set; includes archived and hidden entries. |

By default this hits the portal's curated set of around 29 entries — the same set the dashboard grid shows. `--all` falls back to Ultra memberships and returns every enrollment Blackboard knows about (around 47 in a typical account). Role values come through raw: the portal calls it `Learner`, Ultra returns the short code `S`.

```sh
kuleuven toledo courses list --type course
```

```json
{
  "status": "ok",
  "count": 15,
  "items": [
    {
      "batch_uid": "ULTRA-B-KUL-EX101a-2526",
      "course_code": "EX101a",
      "pk": null,
      "portal_uuid": "00000000-0000-0000-0000-000000000001",
      "course_uuid": null,
      "display_name": "Example Course [EX101a]",
      "type": "course",
      "is_available": true,
      "academic_year": 2526,
      "semester": "SEMESTER2",
      "role": "Learner",
      "favorite": false,
      "color": 10
    }
  ]
}
```

#### `kuleuven toledo courses show`

Returns everything that can be known about one course as a single merged record.

```text
kuleuven toledo courses show <ref>
```

The portal list, the portal detail endpoint, the Ultra membership row, and the Ultra course detail endpoint are all merged into one `Course` payload. The response also includes the instructor list (deduplicated by q-uid, with Ultra-side records preferred so emails are populated when available) and the portal's administrative URLs.

```sh
kuleuven toledo courses show EX101a
```

```json
{
  "status": "ok",
  "course": {
    "batch_uid": "ULTRA-B-KUL-EX101a-2526",
    "course_code": "EX101a",
    "pk": "_100000_1",
    "portal_uuid": "00000000-0000-0000-0000-000000000001",
    "course_uuid": "00000000000000000000000000000001",
    "foundations_id": "00000000-0000-0000-0000-000000000002",
    "display_name": "Example Course [EX101a]",
    "type": "course",
    "is_available": true,
    "effective_availability": true,
    "academic_year": 2526,
    "semester": "SEMESTER2",
    "locale": "en_GB",
    "ultra_status": "ULTRA",
    "role": "Learner",
    "favorite": false,
    "description": null,
    "instructors": [
      { "q_uid": "q0000001", "given_name": "Jane", "family_name": "Doe", "pk": "_30000_1", "email": "jane.doe@example.edu" }
    ],
    "admin_urls": {
      "unenrollUrl": "...",
      "manageUrl": "...",
      "gradeCenterToolUrl": "...",
      "impexUrl": "..."
    }
  }
}
```

#### `kuleuven toledo courses favorite`

Pins or unpins a course on the portal dashboard.

```text
kuleuven toledo courses favorite <ref> [--off]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--off` | off | Unpin instead of pin. |

Sends `PATCH /portal/api/enrollments/<uuid>`. Only portal-visible courses can be favourited; trying to favourite an Ultra-only course exits `2` with `code: "not_in_portal"`.

```sh
kuleuven toledo courses favorite EX101a
```

```json
{
  "status": "ok",
  "course": {
    "portal_uuid": "00000000-0000-0000-0000-000000000001",
    "batch_uid": "ULTRA-B-KUL-EX101a-2526",
    "display_name": "Example Course [EX101a]",
    "favorite": true
  }
}
```

#### `kuleuven toledo courses members`

Lists the people enrolled in a course, plus per-bucket counts.

```text
kuleuven toledo courses members <ref> [--role-bucket BUCKET] [--all-members]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--role-bucket` | — | Filter by Ultra's role bucket, e.g. `TEACHING`, `LEARNING`, `SUPPORT`. Passed through verbatim. |
| `--all-members` | off | Include disabled memberships; default keeps only available ones. |

Each item is a Membership: a `pk`, a `role` and `role_bucket` (passed through from Ultra verbatim — typically `S`/`P`/`T` and `LEARNING`/`TEACHING`/`SUPPORT`), an `is_available` flag, and a nested `user`. The response also includes per-bucket counts from `/memberships/counts`, so a roster summary is one call.

```sh
kuleuven toledo courses members EX101a --role-bucket TEACHING
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "counts": { "INSTRUCTOR": 3, "TEACHING_ASSISTANT": 1, "STUDENT": 501 },
  "total": 505,
  "count": 3,
  "items": [
    {
      "pk": "_20000_1",
      "course_pk": "_100000_1",
      "role": "P",
      "role_bucket": "TEACHING",
      "user": {
        "q_uid": "q0000002",
        "given_name": "John",
        "family_name": "Roe",
        "pk": "_30001_1",
        "email": "john.roe@example.edu"
      }
    }
  ]
}
```

#### `kuleuven toledo courses announcements`

Lists announcements for a course, with bodies rendered as markdown.

```text
kuleuven toledo courses announcements <ref> [--unread] [--limit N]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--unread` | off | Only announcements the user has not read yet. |
| `--limit` | `100` | Maximum number of announcements to fetch. |

Each item carries the announcement `id`, the `title`, the `body` (markdown, converted via `markitdown` from Blackboard's rich-text dialect), `is_read`, the create/modify dates, the `creator_user_id` (a Blackboard user PK; cross-reference with `kuleuven toledo courses members` to resolve to a person), the start/end visibility dates, and the `permanent`/`push_notify`/`read_tracking` flags. The response also includes a `counts` object from `/announcements/counts` (`postedCount`, `unreadCount`) so a unread badge is one call.

```sh
kuleuven toledo courses announcements EX101a --unread
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "counts": { "postedCount": 4, "unreadCount": 2 },
  "count": 2,
  "items": [
    {
      "id": "_500000_1",
      "course_pk": "_100000_1",
      "title": "Class cancelled",
      "body": "Dear students,\n\nDue to illness, today's class is cancelled. …",
      "is_read": false,
      "is_draft": false,
      "created_date": "2026-01-15T09:00:00.000Z",
      "modified_date": "2026-01-15T09:00:00.000Z",
      "creator_user_id": "_30000_1",
      "type": "COURSE",
      "start_date_restriction": "2026-01-15T09:00:00.000Z",
      "end_date_restriction": null,
      "position": 1,
      "permanent": true,
      "push_notify": true,
      "read_tracking": true
    }
  ]
}
```

#### `kuleuven toledo courses schedule`

Returns the course's own calendar items.

```text
kuleuven toledo courses schedule <ref> [--from ISO] [--to ISO]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--from` | — | ISO timestamp; inclusive start of window. |
| `--to` | — | ISO timestamp; exclusive end of window. |

In practice this endpoint is sparsely populated — for everyday "what's next" use `/portal/api/upcoming` via `kuleuven session raw` for now.

```sh
kuleuven toledo courses schedule EX101a
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "count": 0,
  "items": []
}
```

#### `kuleuven toledo courses content tree`

Walks the content tree of a course and emits every node in pre-order.

```text
kuleuven toledo courses content tree <ref> [--depth N]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--depth` | unlimited | Bound the recursion to N levels. |

The CLI flag is one call; under the hood there is one HTTP call per non-leaf node. Real folders and lessons are descended into; Ultra Documents (BB Pages) are emitted as leaves.

```sh
kuleuven toledo courses content tree EX101a --depth 1
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "count": 16,
  "items": [
    { "id": "_10000_1", "parent_id": "_99999_1", "title": "Lecture recordings",      "handler": "resource/x-bb-folder", "is_bb_page": false, "depth": 0, "position": 0 },
    { "id": "_10001_1", "parent_id": "_99999_1", "title": "Course overview",         "handler": "resource/x-bb-folder", "is_bb_page": true,  "depth": 0, "position": 1 },
    { "id": "_10002_1", "parent_id": "_99999_1", "title": "Lecture 1: Introduction", "handler": "resource/x-bb-folder", "is_bb_page": true,  "depth": 0, "position": 2 }
  ]
}
```

#### `kuleuven toledo courses content show`

Shows one content item's metadata, plus body markdown and parsed embeds for documents.

```text
kuleuven toledo courses content show <ref> <content_id>
```

The second positional is the Blackboard content PK (e.g. `_10003_1`) as it appears in `kuleuven toledo courses content tree` output. The response carries the common fields (`id`, `parent_id`, `title`, `handler`, `is_bb_page`, `visibility`, `modified_date`, `position`, `description`) plus the raw `detail` dict from the API so handler-specific fields come through verbatim. For documents and Ultra Documents the response also carries `body` (markdown, converted via the `markitdown` package) and `embeds` (structured records lifted out of the HTML, see [`kuleuven toledo courses content embeds`](#kuleuven-toledo-courses-content-embeds)).

```sh
kuleuven toledo courses content show EX101a _10002_1
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "item": {
    "id": "_10002_1",
    "parent_id": "_99999_1",
    "title": "Lecture 1: Introduction",
    "handler": "resource/x-bb-folder",
    "is_bb_page": true,
    "visibility": "VISIBLE",
    "detail": { "resource/x-bb-folder": { "isBbPage": true, "isFolder": true } },
    "body": "Welcome to the first lecture. Required reading is *Example Textbook* by Doe (2024). …",
    "embeds": [
      { "kind": "file", "title": "Lecture 1: slides", "mime_type": "application/pdf", "url": "https://ultra.edu.kuleuven.cloud/bbcswebdav/pid-10003-dt-content-rid-55555_1/xid-55555_1" }
    ]
  }
}
```

#### `kuleuven toledo courses content embeds`

Lists the structured records lifted out of the HTML body — file attachments and LTI launches.

```text
kuleuven toledo courses content embeds <ref> <content_id>
```

Each item has a `kind` (`file` for `data-bbfile` plain attachments, `lti` for `data-bbtype="embedded-app"` LTI launches), a `title`, a `url` (the resource URL for files, the launch URL for LTI), an optional `mime_type` for files, and the full `raw` payload from the JSON-in-attribute the BB rich-text dialect encodes.

```sh
kuleuven toledo courses content embeds EX101a _10002_1
```

```json
{
  "status": "ok",
  "count": 2,
  "items": [
    {
      "kind": "file",
      "title": "Lecture 1: slides",
      "url": "https://ultra.edu.kuleuven.cloud/bbcswebdav/pid-10003-dt-content-rid-55555_1/xid-55555_1",
      "mime_type": "application/pdf",
      "raw": { "linkName": "lecture-1-slides.pdf", "displayName": "Lecture 1: slides", "mimeType": "application/pdf", "render": "inline", "resourceUrl": "...", "viewerUrl": "..." }
    }
  ]
}
```

Files come from three places in a course. Some are content-tree leaves with `contentHandler: resource/x-bb-file` — those carry their own `permanentUrl` and download in one HTTP GET. Most are embedded inside document bodies as `<a data-bbfile>` JSON-in-attribute markers; the library lifts each one out, points its `resourceUrl` at the underlying Xythos blob, and identifies it by `<document_pk>@<embed_index>` so the CLI can address it. Videos live in Kaltura, reached either through a top-level `resource/x-bb-blti-link` content item or an `embedded-app` anchor inside a body; the library starts an anonymous Kaltura widget session, fetches the entry's `downloadUrl`, and streams the resulting MP4. All three paths are unified into one `FileItem` shape so `kuleuven toledo courses files list` returns a single flat list.

#### `kuleuven toledo courses files list`

Walks the content tree and emits every downloadable in pre-order.

```text
kuleuven toledo courses files list <ref>
```

Each item carries a synthetic `id` (a bare content PK for leaves and BLTI links, `<content_pk>@<index>` for body embeds), a `kind` (`file` or `video`), the original `title`, the on-disk `filename` (empty for videos — Kaltura supplies it on download), `mime_type` and `size` when known, the resolved `url` for Blackboard files (Kaltura resolves on fetch), the `kaltura_entry_id` for videos, and a `source_path` array carrying the chain of folder titles down to the file's container so `sync` can mirror the structure on disk.

```sh
kuleuven toledo courses files list EX101a
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "count": 34,
  "items": [
    {
      "id": "_10002_1@0",
      "kind": "file",
      "title": "Lecture 1: slides",
      "filename": "lecture-1-slides.pdf",
      "source_content_id": "_10002_1",
      "source_path": ["Lecture 1: Introduction"],
      "embed_index": 0,
      "mime_type": "application/pdf",
      "size": null,
      "url": "https://ultra.edu.kuleuven.cloud/bbcswebdav/pid-10003-dt-content-rid-55555_1/xid-55555_1",
      "kaltura_entry_id": null
    },
    {
      "id": "_10100_1",
      "kind": "video",
      "title": "Lecture 1 recording",
      "filename": "",
      "source_content_id": "_10100_1",
      "source_path": ["Lecture recordings"],
      "embed_index": null,
      "mime_type": "video/mp4",
      "size": null,
      "url": null,
      "kaltura_entry_id": "1_examplekt"
    }
  ]
}
```

#### `kuleuven toledo courses files fetch`

Downloads one file or video. Writes to disk, to a chosen directory, or streams to stdout.

```text
kuleuven toledo courses files fetch <ref> <file_id> [--out PATH | DIR | -]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--out` | `item.filename` in cwd | File path (writes there), existing directory (writes into it with the default filename), or `-` (streams raw bytes to stdout). |

When `--out` is omitted the file is written to the cwd using `item.filename`, with Kaltura videos defaulting to `<title>.mp4`. Streaming to stdout writes errors to stderr as JSON and exits non-zero; the disk modes use the normal JSON envelope.

```sh
kuleuven toledo courses files fetch EX101a '_10002_1@0' --out lecture-1.pdf
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "item": {
    "id": "_10002_1@0",
    "kind": "file",
    "title": "Lecture 1: slides",
    "filename": "lecture-1-slides.pdf",
    "source_content_id": "_10002_1",
    "source_path": ["Lecture 1: Introduction"],
    "embed_index": 0,
    "mime_type": "application/pdf",
    "size": null,
    "url": "https://ultra.edu.kuleuven.cloud/bbcswebdav/pid-10003-dt-content-rid-55555_1/xid-55555_1",
    "kaltura_entry_id": null
  },
  "download": {
    "path": "lecture-1.pdf",
    "bytes": 802583,
    "server_filename": "lecture-1-slides.pdf"
  }
}
```

Streaming a video to stdout:

```sh
kuleuven toledo courses files fetch EX101a '_10100_1' --out - > lecture-1.mp4
```

#### `kuleuven toledo courses files resolve`

Resolves a short-lived, standalone-fetchable URL for one file or video. For Blackboard files, follows the bbcswebdav redirect chain to the signed S3 URL. For Kaltura videos, returns the CDN download URL. The returned URL can be fetched by any HTTP client without further authentication until it expires (around six hours for files).

```text
kuleuven toledo courses files resolve <ref> <file_id>
```

```sh
kuleuven toledo courses files resolve EX101a '_10000_1@0'
```

```json
{
  "status": "ok",
  "course": { "pk": "_1_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course" },
  "item": { "id": "_10000_1@0", "kind": "file", "mime_type": "application/pdf", "...": "..." },
  "url": "https://learn-eu-central-1-prod-fleet01-xythos.content.blackboardcdn.com/..."
}
```

#### `kuleuven toledo courses files sync`

Bulk-downloads every file and video in a course, mirroring the content tree on disk.

```text
kuleuven toledo courses files sync <ref> [--into DIR] [--dry-run] [--skip-videos]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--into` | `<course code>` in cwd | Destination directory; falls back to batchUid if no course code can be derived. |
| `--dry-run` | off | Report the plan without writing anything. |
| `--skip-videos` | off | Skip Kaltura videos — the usual setting on bandwidth-limited networks. |

Already-existing non-empty files are kept; failures are surfaced in a `failures` array with the underlying error rather than aborting the whole run. Overall `status` is `"ok"` when every item downloaded or already existed, `"partial"` when some items failed.

```sh
kuleuven toledo courses files sync EX101a --into ./downloads --skip-videos
```

```json
{
  "status": "ok",
  "course": { "pk": "_100000_1", "batch_uid": "ULTRA-B-KUL-EX101a-2526", "display_name": "Example Course [EX101a]" },
  "destination": "downloads",
  "downloaded": 27,
  "existing": 0,
  "skipped": [{ "id": "_10100_1", "reason": "skip_videos" }],
  "failures": [],
  "items": [
    { "id": "_10002_1@0", "target": "downloads/Lecture 1: Introduction/lecture-1-slides.pdf", "bytes": 802583, "status": "downloaded" }
  ]
}
```

#### `kuleuven toledo courses grades`

Lists per-item grades for one user in a course. Defaults to the signed-in user; most accounts can only query themselves.

```text
kuleuven toledo courses grades <ref> [--user <userId>]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--user` | signed-in user | Blackboard user pk to look up. Instructors with the right entitlements can query students. |

The response carries the course identity, the `user_pk` that was queried, and one item per gradebook column. Each item is the raw API record: `columnId`, `displayGrade` (when scored), `lastAttempt`, `submissionStatus.status` (`UNOPENED`, `IN_PROGRESS`, `READY_TO_POST`, …), `hasAttemptOrGradeFeedback`, `attemptsLeft`, and a nested `column` with the column's metadata (name, max `possible` points, due date, category, grading schema). Use `jq '.items[].column'` to extract just the gradebook structure.

```sh
kuleuven toledo courses grades EX102a
```

A course's discussion forums sit as content items under a virtual `INTERACTIVE` parent in the content tree. Each forum has a `forum_id` (the API key) and a `content_id` (what URLs in the Ultra SPA use). The discussion-board path segment in the API is always `default`; Ultra resolves it to the course's discussion board server-side, so callers don't need the `conference_id`.

#### `kuleuven toledo courses discussions list`

Lists every discussion forum in a course with the ids and dates the other discussion commands need.

```text
kuleuven toledo courses discussions list <ref>
```

Each item carries `content_id`, `forum_id`, `conference_id`, `title`, `due_date`, `modified_date`, `visibility`, `has_grade_column`, `has_participation_requirements`, `is_created_by_student`, `is_group_content`, `web_location`.

```sh
kuleuven toledo courses discussions list EX103c
```

#### `kuleuven toledo courses discussions show`

Shows one forum's metadata, read/reply counts, and the top-level messages (root threads). For threaded discussions each message's `messageStatus.totalCount` gives the full descendant count — use `discussions replies` to drill in.

```text
kuleuven toledo courses discussions show <ref> <forum_id>
```

```sh
kuleuven toledo courses discussions show EX103c _99089_1
```

#### `kuleuven toledo courses discussions replies`

Lists replies to one message, in Blackboard's default sort (drafts first, then most recent post date). Paginated; pass `--limit`/`--offset` and follow `next_page` in the response.

```text
kuleuven toledo courses discussions replies <ref> <forum_id> <message_id> [--limit N] [--offset N]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--limit` | 100 | Page size. |
| `--offset` | 0 | Starting index into the reply list. |

The response carries `total` (descendant count), the current `offset`/`limit`, a `next_page` URL when more remain, and `items` with each reply's body (`body.rawText` is the BB rich-text dialect; `body.displayText` is sanitised HTML), author fields, `postDate`, `editDate`, and a `messageStatus` block.

```sh
kuleuven toledo courses discussions replies EX103c _99089_1 _565094_1 --limit 25
```

### KURT

The `kuleuven kurt` commands cover KU Leuven's KURT3 reservation system at `kurt3.ghum.kuleuven.be` — study seats, group rooms, audio-visual kits, and the learning-lab equipment. Locations have numeric ids surfaced by `kuleuven kurt locations list`; resource types and zones live one level deeper under each location. Dates are `YYYY-MM-DD`, times are `HH:MM` on the hour (the booking grid is hour-slotted). Reservations are owned by the signed-in user; a new day becomes bookable each evening for the same time one week out.

The verbs are split between two subgroups: `locations` for browsing the venue tree, and `resources` for everything you do with individual resources (search, favourites, reservations).

#### `kuleuven kurt locations list`

Lists every bookable location, grouped into tiles (cities and special categories like the Learning Lab).

```text
kuleuven kurt locations list
```

```sh
kuleuven kurt locations list | jq '.tiles[].locations[] | {id, unit}'
```

#### `kuleuven kurt locations show`

Shows one location with its zones (floor plans), its bookable resource types, and current occupancy.

```text
kuleuven kurt locations show <ID> [--no-occupancy]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--occupancy` / `--no-occupancy` | on | Include the live occupancy snapshot. |

```sh
kuleuven kurt locations show 10
```

#### `kuleuven kurt resources search`

Searches bookable resources at a location for a given window. Leave `--start` and `--end` blank to see every resource regardless of availability.

```text
kuleuven kurt resources search --location ID --type ID --date YYYY-MM-DD [--end-date YYYY-MM-DD] [--start HH:MM] [--end HH:MM] [--zone ID] [--participants N] [--only-favorites] [--name SUBSTRING]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--location` | required | Location id from `locations list`. |
| `--type` | required | Resource type id from `locations show`. |
| `--date` | required | Window start date. |
| `--end-date` | same as `--date` | Window end date for multi-day resources. |
| `--start` / `--end` | empty | Window times. Leave blank for any. |
| `--zone` | `-1` | Restrict to one zone id, `-1` for any. |
| `--participants` | `1` | Required capacity. |
| `--only-favorites` | off | Restrict to favourited resources. |
| `--name` | empty | Case-insensitive substring filter on resource name. |

The response carries the raw availability records, including `slotAllocation` — a 24-character string where `A` means free, `B` means booked, and `C` means closed (one character per hour).

```sh
kuleuven kurt resources search --location 10 --type 302 --date 2026-05-25 --start 09:00 --end 12:00
```

#### `kuleuven kurt resources quotas`

Reports per-resource-type usage and limits for the signed-in user (day and week). `-1` in a `max*` field means unlimited.

```text
kuleuven kurt resources quotas
```

```json
{
  "status": "ok",
  "quotas": [
    {
      "resourceType": "Study Seat",
      "resourceTypeId": 302,
      "usageDay": 0,
      "usageWeek": 0,
      "maxUsageDay": -1,
      "maxUsageWeek": 48
    }
  ]
}
```

#### `kuleuven kurt resources favorites`

Lists the resources the user has favourited in KURT.

```text
kuleuven kurt resources favorites
```

#### `kuleuven kurt resources reservations`

Lists the signed-in user's current and future KURT reservations.

```text
kuleuven kurt resources reservations [--today]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--today` | off | Restrict to reservations whose window includes today. |

```sh
kuleuven kurt resources reservations
```

#### `kuleuven kurt resources book`

Creates a reservation on a specific resource.

```text
kuleuven kurt resources book --resource ID --date YYYY-MM-DD --start HH:MM --end HH:MM [--end-date YYYY-MM-DD] [--subject TEXT] [--purpose TEXT] [--participant uid:email]...
```

| Flag | Default | Description |
| --- | --- | --- |
| `--resource` | required | Resource id from `resources search`. |
| `--date` | required | Reservation date. |
| `--start` / `--end` | required | Reservation times on the hour. |
| `--end-date` | same as `--date` | Only set for multi-day-reservable resources. |
| `--subject` | `Productivity Session` | Subject string shown on the reservation. |
| `--purpose` | empty | Purpose string; required by some resource types. |
| `--participant` | — | Additional participant as `uid:email`. Repeat for group rooms; the signed-in user is always added. |

Resource types with `reservationRequestRequired` (rare; staff approval flow) are not yet supported.

```sh
kuleuven kurt resources book --resource 301108 --date 2026-05-25 --start 09:00 --end 12:00

# group work room with extra participants
kuleuven kurt resources book --resource 200001 --date 2026-05-26 --start 14:00 --end 16:00 \
  --participant r0000001:first.collab@kuleuven.be \
  --participant r0000002:second.collab@kuleuven.be
```

#### `kuleuven kurt resources unbook`

Cancels a reservation by id.

```text
kuleuven kurt resources unbook <RESERVATION_ID>
```

```sh
kuleuven kurt resources unbook 3963083203
```

### Claude Desktop

The `kuleuven mcp` commands run an MCP server backed by the same CLI you see here and manage its registration in Claude Desktop's config. The MCP tools mirror the CLI verbs one-for-one — `kuleuven_toledo_courses_list`, `kuleuven_toledo_courses_content_show`, `kuleuven_kurt_resources_search`, and so on — with the same arguments, the same JSON output, and the same cookie jar. Tool names use underscores because Claude Desktop validates tool names against `^[a-zA-Z0-9_-]{1,64}$`. Sign in once with `kuleuven session start` in a terminal; Claude Desktop reuses the persisted session.

The MCP server exposes every CLI command except `kuleuven toledo courses files fetch` and `kuleuven toledo courses files sync` (which write to local disk — use `kuleuven toledo courses files resolve` to get a fetchable URL instead) and the `mcp` commands themselves. `session start` is included with `username`, `password`, and `totp` as optional fields; if the MCP server's environment has `KULEUVEN_USERNAME` and `KULEUVEN_PASSWORD` set, Claude can refresh expired sessions without prompting. Set those via the `env` block in Claude Desktop's `claude_desktop_config.json` if you want that behaviour. TOTP rotates every 30 seconds so a static `KULEUVEN_TOTP` is rarely useful.

#### `kuleuven mcp start`

Runs a stdio MCP server. Invoked by Claude Desktop, not by humans — it speaks JSON-RPC on stdin and stdout and produces no human-readable output. No flags. Exits with `0` on clean shutdown.

#### `kuleuven mcp install`

Adds a `kuleuven` entry to Claude Desktop's `claude_desktop_config.json` pointing at the `kuleuven` executable on `PATH`. Atomic write; other entries in the config are preserved.

```text
kuleuven mcp install [--name NAME]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--name` | `kuleuven` | Name of the MCP server entry; use a different name to register multiple instances. |

The response carries the resolved config path, the absolute command path written, and `restart_required: true` when the config was modified. If the `kuleuven` executable cannot be found on `PATH`, exits `1` with `code: "kuleuven_not_on_path"`. Restart Claude Desktop after installation for the change to take effect.

```sh
kuleuven mcp install
```

```json
{
  "status": "ok",
  "config_path": "/Users/you/Library/Application Support/Claude/claude_desktop_config.json",
  "name": "kuleuven",
  "command": "/Users/you/.local/bin/kuleuven",
  "changed": true,
  "restart_required": true
}
```

#### `kuleuven mcp uninstall`

Removes the entry from Claude Desktop's config. No-op if the entry was not present (`removed: false`).

```text
kuleuven mcp uninstall [--name NAME]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--name` | `kuleuven` | Name of the MCP server entry to remove. |

```sh
kuleuven mcp uninstall
```

```json
{
  "status": "ok",
  "config_path": "/Users/you/Library/Application Support/Claude/claude_desktop_config.json",
  "name": "kuleuven",
  "removed": true
}
```

## Python API

The library is split along the same axis as the CLI: `kuleuven.session.KuleuvenSession` owns the `httpx.Client` and the SAML handshake; `kuleuven.toledo.ToledoClient` exposes Toledo/Ultra endpoints as methods; `kuleuven.kurt.KurtClient` exposes the KURT endpoints. Both per-service clients are constructed from a `KuleuvenSession` and share its cookie jar. Pydantic models in `kuleuven.models` represent the domain.

The library does not persist cookies — that lives in `kuleuven.cli.storage` and is only wired up by the CLI. To reuse a saved session in your own code, build an `httpx.Client` with cookies you loaded yourself and pass it as `KuleuvenSession(http_client=...)`.

```python
from kuleuven import KuleuvenSession, ToledoClient, KurtClient

class Authenticator:
    # Satisfies the AuthenticationProvider protocol. Each method is called only
    # if the IdP demands it: provide_totp for a TOTP form; select_device +
    # awaiting_approval for the KU Leuven Authenticator push.
    def provide_totp(self):
        return "123456"

    def select_device(self, devices):
        return devices[0]

    def awaiting_approval(self, device_name):
        print(f"approve the push on {device_name}")

with KuleuvenSession() as session:
    session.sign_in(username="r0123456", password="...", provider=Authenticator())
    toledo = ToledoClient(session)
    kurt = KurtClient(session)

    courses = toledo.list_portal_courses()
    reservations = kurt.list_reservations()
```

### `KuleuvenSession`

Owns the `httpx.Client` and runs the three-leg SAML sign-in (portal + Ultra + KURT). No per-service endpoints live here.

| Method | Signature | Returns | Description |
| --- | --- | --- | --- |
| `__init__` | `KuleuvenSession(http_client: httpx.Client \| None = None)` | — | Optionally bring your own `httpx.Client` (e.g. with pre-loaded cookies). |
| `sign_in` | `sign_in(username, password, provider: AuthenticationProvider)` | `None` | Walks the portal, Ultra, and KURT SAML flows in sequence. `provider` supplies the second factor on demand (TOTP code, or Authenticator device choice + approval wait). |
| `session_info` | `session_info()` | `dict \| None` | Same shape as `kuleuven session status`; `None` if the portal session is gone. |
| `has_ultra_session` | `has_ultra_session()` | `bool` | Cheap cookie-jar check for whether the Ultra handshake completed. |
| `close` | `close()` | `None` | Closes the underlying `httpx.Client`. Also called by `__exit__`. |

### `AuthenticationProvider`

A Protocol (in `kuleuven.shibboleth`, re-exported from `kuleuven`) that `sign_in` calls to satisfy the second factor. Implement the methods the IdP will use for your account; methods are only invoked when their form appears.

| Method | Signature | Called when | Description |
| --- | --- | --- | --- |
| `provide_totp` | `provide_totp() -> str` | the IdP serves a `tokencode` form | Return a 6-digit TOTP code. |
| `select_device` | `select_device(devices: list[NextauthDevice]) -> NextauthDevice` | the IdP serves the Authenticator device picker | Choose which device to push to. |
| `awaiting_approval` | `awaiting_approval(device_name: str) -> None` | right after the push is sent | Notify the user (e.g. print "Waiting for approval on …"). Return immediately; `sign_in` then blocks on the WebSocket. |

`NextauthDevice` (in `kuleuven.nextauth`) is a frozen dataclass with `account_id: str`, `name: str`, and `last_login: str | None` (the raw "Last login at:" text, or `None`).

Push-related exceptions, both subclassing `AuthenticationError`: `AuthApprovalTimeoutError` (no approval within 120 s) and `AuthApprovalFailedError` (the push was rejected or the WebSocket errored).

### Data model

The Pydantic models in `kuleuven.models`. Two kinds: *curated* models like `Course` / `Person` / `Membership` / `FileItem` (snake_case fields we chose) and *API echo* models like `MemberCounts` / `Reservation` / `Location` (mirror the upstream JSON; `model_dump()` preserves the camelCase keys). All inherit from `kuleuven.models.KuleuvenModel` (or `ApiEchoModel`) — call `.model_dump(mode="json")` to get the same shape the CLI emits. Role values and content handlers come through raw — the library does not maintain a translation table that could fall behind Blackboard's vocabulary.

#### `Course`

Collects cross-system identity (`batch_uid`, `pk`, `portal_uuid`, `course_uuid`, `foundations_id`), display fields, type and availability, academic fields, and user-relative fields like `role`, `favorite`, and `last_accessed`. Three constructors — `Course.from_portal`, `Course.from_ultra_membership`, `Course.from_ultra_course` — each populate what their source carries; `.merge(other)` joins two views field-wise so the CLI can present a single record. The `course_code` property returns the `EX101a`-style segment parsed out of the batchUid for real courses, and `None` for communities and anything that does not match the `ULTRA-…` shape.

#### `Person`

Carries q-uid, given and family name, and (when sourced from Ultra) the BB pk, email, foundations id, and uuid. `Person.from_portal_instructor` and `Person.from_ultra_user` cover the two source shapes.

#### `Membership`

Wraps a `pk`, the `course_pk`, a nested `Person`, the raw `role` and `role_bucket` strings, and `is_available`. `Membership.from_ultra` builds it from a `/courses/<pk>/memberships` item.

#### `Announcement`

Carries the announcement `id`, the `course_pk`, the `title`, the raw HTML body as `body_html` (Blackboard's rich-text dialect; render with `ToledoClient.render_markdown`), `is_read`, `is_draft`, create/modify dates, the `creator_user_id` (Blackboard user PK), the start/end visibility dates, and the `permanent`/`push_notify`/`read_tracking` flags. `Announcement.from_ultra` builds it from a `/courses/<pk>/announcements` item. `model_dump()` excludes `body_html` — render to markdown at the call site and add it back under whatever key you prefer.

#### `ContentNode`

The per-node record `walk_contents` yields: `id`, `parent_id`, `title`, `handler`, `is_bb_page`, `depth`, `position`.

#### `Embed`

A parsed embed lifted out of an HTML body. `Embed.from_anchor(payload, bb_type=...)` classifies the anchor as `file` or `lti` based on the surrounding `data-bbtype` attribute and the payload fields, exposes `title`/`url`/`mime_type`, and keeps the full `raw` payload so nothing is lost. When an embed only carries `viewerUrl` (no `resourceUrl`), the query string is stripped so the resulting URL points at the raw file rather than the inline-render React viewer.

#### `FileItem`

The unified record `kuleuven toledo courses files list` emits. The `id` is synthetic (a bare content PK or `<content_pk>@<index>`), `kind` is either `file` or `video`, and `source_path` is a list of folder titles down to the container so `kuleuven toledo courses files sync` can mirror the tree on disk. `kaltura_entry_id` is populated for videos; `kuleuven toledo courses files fetch` resolves it through an anonymous Kaltura widget session at download time and follows the resulting `downloadUrl`.

### `ToledoClient`

Constructed from a `KuleuvenSession`. Exposes every Toledo portal + Blackboard Ultra endpoint the CLI uses, plus a handful of pure helpers as `@staticmethod`. Module-level constant `KALTURA_PARTNER_ID = 2375821`.

```python
from kuleuven import KuleuvenSession, ToledoClient

with KuleuvenSession() as session:
    session.sign_in("r0123456", "...", provider=Authenticator())
    toledo = ToledoClient(session)
    for course in toledo.list_portal_courses():
        print(course.course_code, course.display_name)
```

| Method | Description |
| --- | --- |
| **courses** | |
| `fetch_user_pk()` | Calls `/learn/api/v1/users/me` and returns the caller's Blackboard PK. |
| `list_portal_courses()` | Curated ~29 portal entries as `list[Course]`. |
| `list_ultra_courses(user_pk=None)` | Full Ultra-side set. When `user_pk` is omitted, fetches it first. |
| `fetch_portal_detail(batch_uid, language="en")` | `PortalCourseDetail` — description, `list[Person]` instructors, and a nested `PortalAdminUrls`. |
| `fetch_ultra_course(course_pk)` | `UltraCourseDetail` — wraps a `Course` plus `list[Person]` instructor memberships. |
| `fetch_members(course_pk, *, role_bucket=None, available=None, limit=1000)` | `list[Membership]`. |
| `fetch_member_counts(course_pk)` | `MemberCounts` mirroring the `/memberships/counts` summary. |
| `fetch_schedule(course_pk, *, start=None, end=None)` | `list[ScheduleItem]` — per-course calendar items. |
| `fetch_announcements(course_pk, *, limit=100, offset=0)` | `list[Announcement]`. |
| `fetch_announcement_counts(course_pk)` | `AnnouncementCounts` with `postedCount` and `unreadCount`. |
| `set_favorite(portal_uuid, favorite)` | Patches the favourite flag. Returns `None`. |
| `fetch_user_grades(course_pk, user_pk, *, include_no_grade_items=True, limit=200)` | `list[GradeEntry]` — per-column grade records for one user, with `column` / `submissionStatus` / `lastAttempt` / `hasAttemptOrGradeFeedback` / `attemptsLeft` expanded inline. The column expansion means each result is a full student-view record in one round-trip. |
| `fetch_my_grades(course_pk, **kwargs)` | Convenience: resolves the signed-in user's pk and calls `fetch_user_grades`. |
| **discussions** | |
| `list_discussions(course_pk, *, limit=100)` | `list[DiscussionItem]` — discussion-forum content items from the virtual `INTERACTIVE` parent. Each carries `contentDetail.resource/x-bb-forumlink` with `id` (forumId) and `conferenceId`. |
| `fetch_forum(course_pk, forum_id)` | `Forum` — title, dates, `properties` (allowAnonymousPosts, allowAttachment, …), permissions. |
| `fetch_forum_counts(course_pk, forum_id)` | `ForumCounts` — `commentCount`, `totalCount`, `readCount`, `draftCount`, `replyCount`. |
| `list_forum_messages(course_pk, forum_id, *, limit=1000)` | `list[ForumMessage]` — top-level messages (root threads). |
| `list_message_replies(course_pk, forum_id, message_id, *, limit=100, offset=0, sort="draft(desc),postDate(desc)")` | `MessageRepliesPage` — full paging envelope (`paging.count`, `offset`, `limit`, `next_page`, `results`). |
| `@staticmethod resolve(courses, ref)` | Every course whose portal UUID, batchUid, BB pk, course UUID, or course code matches `ref`. Case-insensitive on course codes. May return multiple matches across academic years. |
| **content** | |
| `fetch_content(course_pk, content_id)` | `ContentItem` for one item. |
| `fetch_children(course_pk, parent_id, *, limit=1000)` | `list[ContentItem]` children for one parent. |
| `walk_contents(course_pk, *, parent_id="ROOT", max_depth=None)` | Generator yielding `ContentNode` records in pre-order, with the BB Page short-circuit baked in. |
| `resolve_body_item(course_pk, content_id)` | `BodyResolution` (`.original`, `.body_item`), descending into the BB Page's inner child when the original is a BB Page. |
| `fetch_body_and_embeds(course_pk, content_id)` | `BodyAndEmbeds` (`.original`, `.body_item`, `.markdown`, `.embeds`) — descends the BB Page wrapper, renders the markdown, and parses embeds in one call. |
| `@staticmethod is_bb_page(item)` | Predicate for the Ultra Document gotcha. Takes a `ContentItem`. |
| `@staticmethod pick_bb_page_child(children)` | Picks the inner child of a BB Page from its `fetch_children` results. Prefers the literal `ultraDocumentBody` child, falls back to the sole child when the named marker is absent, returns `None` when the shape is ambiguous. |
| `@staticmethod extract_embeds(html)` | Returns `(rewritten_html, list[Embed])`. Parses the BB rich-text dialect, lifts `<a data-bbfile>` and `<a data-bbtype="embedded-app">` records out, and replaces inert anchors with normal `<a href>` links. |
| `@staticmethod render_markdown(html)` | Runs the embed rewrite, then `markitdown`. |
| **files** | |
| `discover_files(course_pk)` | Walks the content tree and returns `list[FileItem]` covering native file leaves, files embedded in document bodies, and Kaltura videos reached via top-level BLTI links or embedded-app anchors. |
| `resolve_download_url(item)` | URL for one item. Fetches Kaltura entry metadata through an anonymous widget session when the item is a video. |
| `resolve_signed_url(item)` | Resolves a standalone-fetchable URL (HEAD-follows bbcswebdav to the signed S3 URL; Kaltura URLs are already standalone). |
| `kaltura_widget_session()` | Starts an anonymous Kaltura widget session. |
| `kaltura_entry_info(entry_id)` | `KalturaEntry` — `downloadUrl` and friends for one Kaltura entry. |
| `stream_response(url, dest_writable)` | Streams a URL into any binary writable (a file, `sys.stdout.buffer`, an `io.BytesIO`); returns `(bytes_written, server_filename_or_None)`. |
| `stream_download(url, dest_path)` | File-targeted convenience wrapping `stream_response`. |
| `download_file_item(item, dest_path)` | `DownloadResult` (`.path`, `.bytes`, `.server_filename`). `FileItem`-aware wrapper used by `kuleuven toledo courses files fetch`. |
| `stream_file_item(item, dest_writable)` | `FileItem`-aware wrapper for `--out -` and `kuleuven toledo courses files sync`. |
| `@staticmethod find_item(items, file_id)` | Looks one `FileItem` up by its synthetic `id`. |

### `KurtClient`

Constructed from a `KuleuvenSession`. Wraps `kurt3.ghum.kuleuven.be/api`; auth is already on the session's cookie jar.

```python
from kuleuven import KuleuvenSession, KurtClient

with KuleuvenSession() as session:
    session.sign_in("r0123456", "...", provider=Authenticator())
    kurt = KurtClient(session)
    reservations = kurt.list_reservations()
```

| Method | Returns | Description |
| --- | --- | --- |
| `get_user_info()` | `UserInfo` | uid, email, common name. |
| `get_account()` | `Account` | Superset of `get_user_info` that adds `list[Quota]` (`usageDay`, `usageWeek`, `maxUsageDay`, `maxUsageWeek`; `-1` is unlimited). |
| `list_tiles()` | `list[TileGroup]` | Tile groups (cities and special categories) with the `list[Tile]` under each. |
| `get_location(location_id)` | `Location` | Address, opening hours, and `list[Zone]` for one location. |
| `list_resource_types(location_id)` | `list[ResourceType]` | Bookable resource types (study seat, group room, …) at a location. |
| `get_occupancy(location_id)` | `Occupancy` | Current occupancy snapshot. |
| `list_favorites()` | `list[Favorite]` | Resources the user has starred. |
| `get_resource(resource_id, with_details=True)` | `Resource` | Resource detail with constraints (min/max participants, subject/purpose requirements, legal text). |
| `search_availability(...)` | `AvailabilitySearchResult` | Searches `/resourcetypeavailabilities` with the same flag shape the `kuleuven kurt resources search` CLI exposes; returns `list[AvailabilitySlot]` under `.availabilities`. |
| `list_reservations(only_today=False)` | `list[Reservation]` | The user's reservations. |
| `get_reservation(reservation_id)` | `Reservation` | One reservation with editable-window metadata. |
| `create_reservation(resource_id, resource_name, start_date, end_date, start_time, end_time, subject="", purpose="", participants=None)` | `ReservationOrText` | POSTs to `/reservations/`. `resource_name` must echo the resource's `name` field; KURT rejects the request with a bare 400 otherwise. Returns `.reservation` on JSON success or `.message` when KURT replies with text. |
| `update_reservation(reservation)` | `ReservationOrText` | PUTs a full reservation object (a `Reservation` or its dict form) with edited fields applied. |
| `cancel_reservation(reservation_id)` | `None` | DELETEs the reservation. |

The module also exposes `has_session(http_client) -> bool` — a cookie-jar check used by `KuleuvenSession.sign_in` to confirm the KURT handshake completed.

### Exceptions

The library raises these:

| Exception | When |
| --- | --- |
| `kuleuven.AuthenticationError` | Any failure in the SAML or per-SP bootstrap flow. Base class for the auth exceptions below. |
| `kuleuven.InvalidCredentialsError` | The IdP rejected the username or password. Inherits from `AuthenticationError`. |
| `kuleuven.AuthApprovalTimeoutError` | The KU Leuven Authenticator push was not approved within 120 s. Inherits from `AuthenticationError`. |
| `kuleuven.AuthApprovalFailedError` | The push was rejected or the WebSocket errored. Inherits from `AuthenticationError`. |
| `kuleuven.SessionExpiredError` | An API call hit a Shibboleth re-auth bounce instead of the real endpoint — the SP session expired. Raised by `KurtClient`. Inherits from `AuthenticationError`. |
| `httpx.HTTPError` | Raised by the per-domain helpers and the underlying HTTP layer. Propagated, not wrapped. |

## Cookie storage

Cookies live at `platformdirs.user_data_path("kuleuven") / "cookies.json"` with `0600` permissions. On macOS that resolves to `~/Library/Application Support/kuleuven/cookies.json`, on Linux to `~/.local/share/kuleuven/cookies.json`. The file holds portal, Ultra, and KURT cookies in one jar; all three are loaded into the `httpx.Client` automatically by the CLI callback before any subcommand runs.

## Tests

```
uv run pytest
```

The suite is offline: HTTP is mocked with [respx](https://lundberg.github.io/respx/) at the transport layer, so no real KU Leuven request goes out. CLI tests use Typer's `CliRunner` and monkeypatch `kuleuven.cli.storage.cookies_path` onto `tmp_path` so the on-disk cookie jar is never touched. Tests live in `tests/` with shared fixtures (sample payloads, a session/client pair) in `tests/conftest.py`.
