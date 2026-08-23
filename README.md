# python-kuleuven

CLI, MCP server, and Python client for KU Leuven. Signs in through the SAML2 SSO flow at `idp.kuleuven.be` and gives you one session that works against the Toledo portal, Blackboard Ultra, and the KURT study-space reservation system.

- [`docs/AUTH.md`](docs/AUTH.md) — how the SAML sign-in flow works
- [`docs/DATA.md`](docs/DATA.md) — the REST surface behind the clients

## Installation

Requires Python 3.13 or newer and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run kuleuven --help
```

## Quickstart

```sh
# Authenticate. Credentials can also come from $KULEUVEN_USERNAME /
# $KULEUVEN_PASSWORD or a .env file.
kuleuven session start

# List the courses on your portal dashboard.
kuleuven toledo courses list --type course

# Download every file in a course, mirroring its tree on disk.
kuleuven toledo courses files sync EX101a --into ./downloads --skip-videos
```

Every command prints exactly one JSON object to stdout, success or failure, so output is pipeline-friendly:

```sh
kuleuven toledo courses list --type course | jq '.items[].course_code'
```

## How it fits together

**Two backends, one session.** Toledo is a single front door over two systems. The portal at `toledo.kuleuven.be` hosts the curated course grid and notification feed; the actual content, files, members, and grades live in Blackboard Ultra at `ultra.edu.kuleuven.cloud`. Each has its own cookies and its own REST API. One `kuleuven session start` establishes both, plus the KURT session at `kurt3.ghum.kuleuven.be`.

**Course references.** The two systems name the same course differently: the portal uses a batchUid like `ULTRA-B-KUL-EX101a-2526`, Blackboard a primary key like `_100000_1`, and each side adds its own UUID. Every course command takes a single `<ref>` that accepts any of these — or simply the course code, `EX101a`, case-insensitively. When a code matches multiple academic years the command exits `2` with the candidates listed so you can pick a more specific reference.

**The content tree.** Course content is recursive: folders, documents, files, LTI links. One wrinkle: an item that claims to be a folder but has `isBbPage: true` is really an Ultra Document — a wrapper around a single inner payload. The tree walker treats these as leaves and the `content` and `files` commands descend into the inner child automatically, so you generally don't have to care.

## CLI

`kuleuven docs` prints Markdown documentation for the whole command tree — every command with its usage, arguments, and options, generated from the live Typer app so it never drifts. What follows is the short version.

### Conventions

Every command writes one JSON object to stdout and exits:

| Exit code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Auth or session failure, downstream HTTP error, or download failure. |
| `2` | Bad input — unknown reference, ambiguous match, missing argument. |

Errors are JSON on stdout too, not stderr, so a pipeline only parses one stream. The exceptions are `docs` (raw Markdown) and `files fetch --out -` (binary bytes, errors on stderr).

Credentials come from flags, environment variables, or a `.env` file in the current directory, and are prompted for only on a TTY. They are never written to disk; the only thing persisted is the session cookie jar, at `platformdirs.user_data_path("kuleuven") / "cookies.json"` (`~/.local/share/kuleuven/cookies.json` on Linux, `~/Library/Application Support/kuleuven/cookies.json` on macOS) with `0600` permissions.

| Variable | Purpose |
| --- | --- |
| `KULEUVEN_USERNAME` | KU Leuven username (r-uid or q-uid). |
| `KULEUVEN_PASSWORD` | KU Leuven password. |
| `KULEUVEN_TOTP` | 6-digit TOTP code, when the account is TOTP-enrolled. |
| `KULEUVEN_AUTH_DEVICE` | KU Leuven Authenticator device to push to: a name, 1-based index, or `most-recent` (the default). |

### `kuleuven session`

| Command | Does |
| --- | --- |
| `session start` | Signs in to the portal, Ultra, and KURT and persists the cookies. |
| `session status` | Reports whether the persisted session is still valid. |
| `session end` | Deletes the saved session. |
| `session raw <METHOD> <URL> [--body JSON]` | Sends a pre-authenticated request to any URL — the escape hatch for endpoints the higher-level commands don't cover. |

`session start` runs three SAML handshakes in sequence; only the first prompts for credentials, the rest reuse the IdP session. The second factor depends on your enrolment: a TOTP account is asked for a code (`--totp`), an account on the KU Leuven Authenticator app gets a push to the chosen device (`--device`) and the command blocks until you approve, with a 120-second timeout. The IdP's `rememberDevice` cookie is kept, so 2FA happens once per device.

```sh
kuleuven session start --device "My phone"
kuleuven session raw GET 'https://toledo.kuleuven.be/portal/api/upcoming'
```

### `kuleuven toledo courses`

Everything is scoped to a course, so `content`, `files`, and `discussions` nest under `courses`. `<ref>` is any course identifier (see above).

| Command | Does |
| --- | --- |
| `courses list` | Courses and communities you're enrolled in. Filter with `--favorite`, `--type`, `--semester`, `--year`; `--all` switches from the portal's curated set to every Ultra membership, archived ones included. |
| `courses show <ref>` | One merged record from all four backend views: identity, availability, instructors, admin URLs. |
| `courses favorite <ref> [--off]` | Pins or unpins a course on the portal dashboard. |
| `courses members <ref>` | Roster with per-bucket counts. Filter with `--role-bucket TEACHING\|LEARNING\|SUPPORT`. |
| `courses announcements <ref> [--unread]` | Announcements with bodies rendered to markdown, plus read counts. |
| `courses schedule <ref>` | The course's own calendar items. Sparsely populated in practice — for "what's next" use `session raw GET .../portal/api/upcoming`. |
| `courses grades <ref>` | Per-column gradebook records for the signed-in user (`--user` for instructors). |
| `courses content tree <ref> [--depth N]` | Every content node in pre-order. |
| `courses content show <ref> <id>` | One item's metadata, plus body markdown and parsed embeds for documents. |
| `courses content embeds <ref> <id>` | Just the structured records lifted out of a document body: file attachments and LTI launches. |
| `courses files list <ref>` | Every downloadable in the course as one flat list. |
| `courses files fetch <ref> <id> [--out PATH\|DIR\|-]` | Downloads one file or video; `-` streams to stdout. |
| `courses files resolve <ref> <id>` | A short-lived URL fetchable by any HTTP client without auth. |
| `courses files sync <ref> [--into DIR] [--dry-run] [--skip-videos]` | Bulk download, mirroring the content tree on disk. Existing files are kept; failures are reported per-item instead of aborting. |
| `courses discussions list <ref>` | The course's discussion forums with their ids. |
| `courses discussions show <ref> <forum_id>` | One forum's metadata, counts, and root threads. |
| `courses discussions replies <ref> <forum_id> <message_id>` | Paginated replies to one message. |

Files come from three places — native file leaves in the content tree, attachments embedded in document bodies, and Kaltura videos — and `files list` unifies them into one shape. File ids are a content PK for leaves and `<content_pk>@<index>` for body embeds; use them verbatim in `fetch` and `resolve`.

```sh
kuleuven toledo courses show EX101a
kuleuven toledo courses files fetch EX101a '_10002_1@0' --out lecture-1.pdf
```

### `kuleuven kurt`

Covers KURT, the reservation system for study seats, group rooms, and equipment. Locations have numeric ids; resource types and zones live under each location. Dates are `YYYY-MM-DD`, times are `HH:MM` on the hour. A new day becomes bookable each evening one week out.

| Command | Does |
| --- | --- |
| `locations list` | Every bookable location, grouped into city tiles. |
| `locations show <id>` | One location with its zones, resource types, and live occupancy. |
| `resources search --location ID --type ID --date D` | Availability search. Narrow with `--start`/`--end`, `--zone`, `--participants`, `--name`; the response includes `slotAllocation`, a 24-character per-hour string (`A` free, `B` booked, `C` closed). |
| `resources quotas` | Your per-resource-type usage and limits (`-1` means unlimited). |
| `resources favorites` | Resources you've starred in KURT. |
| `resources reservations [--today]` | Your current and future reservations. |
| `resources book --resource ID --date D --start T --end T` | Creates a reservation. `--participant uid:email` (repeatable) for group rooms; `--subject`/`--purpose` where the resource type requires them. |
| `resources unbook <id>` | Cancels a reservation. |

```sh
kuleuven kurt resources search --location 10 --type 302 --date 2026-05-25 --start 09:00 --end 12:00
kuleuven kurt resources book --resource 301108 --date 2026-05-25 --start 09:00 --end 12:00
```

### `kuleuven mcp` (Claude Desktop)

Runs the same CLI as an MCP server and manages its registration in Claude Desktop.

| Command | Does |
| --- | --- |
| `mcp install [--name NAME]` | Adds the server to `claude_desktop_config.json`. Restart Claude Desktop afterwards. |
| `mcp uninstall [--name NAME]` | Removes it again. |
| `mcp start` | The stdio server itself — invoked by Claude Desktop, not by humans. |

The MCP tools mirror the CLI verbs one-for-one (`kuleuven_toledo_courses_list`, `kuleuven_kurt_resources_search`, …) with the same arguments, JSON output, and cookie jar. Sign in once with `kuleuven session start` in a terminal; Claude Desktop reuses the persisted session. The disk-writing commands (`files fetch`, `files sync`) are excluded — Claude gets `files resolve` instead. If you set `KULEUVEN_USERNAME` and `KULEUVEN_PASSWORD` in the server's `env` block, Claude can refresh expired sessions on its own.

## Python API

The library is pure: HTTP in, models out — no disk I/O, no environment reads, no prompting. `KuleuvenSession` owns the `httpx.Client` and the SAML handshake; `ToledoClient` and `KurtClient` are constructed from it and share its cookie jar. Cookie persistence lives only in the CLI; to reuse a saved session in your own code, build an `httpx.Client` with the cookies yourself and pass it as `KuleuvenSession(http_client=...)`.

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

| Method | Description |
| --- | --- |
| `KuleuvenSession(http_client=None)` | Optionally bring your own `httpx.Client`, e.g. with pre-loaded cookies. |
| `sign_in(username, password, provider)` | Walks the portal, Ultra, and KURT SAML flows. `provider` supplies the second factor on demand. |
| `session_info()` | Session attributes and expiry, same shape as `kuleuven session status`; `None` if the portal session is gone. |
| `has_ultra_session()` | Cheap cookie-jar check for whether the Ultra handshake completed. |
| `close()` | Closes the underlying client. Also called by `__exit__`. |

`AuthenticationProvider` is a Protocol with three methods, each invoked only when the IdP serves the corresponding form: `provide_totp() -> str`, `select_device(devices) -> NextauthDevice`, and `awaiting_approval(device_name)` (notify the user, return immediately; `sign_in` then blocks on the approval WebSocket, timing out after 120 seconds).

### `ToledoClient`

Every Toledo portal and Blackboard Ultra endpoint the CLI uses, plus pure helpers as `@staticmethod`.

| Method | Description |
| --- | --- |
| **courses** | |
| `fetch_user_pk()` | The caller's Blackboard PK. |
| `list_portal_courses()` | The portal's curated enrollments as `list[Course]`. |
| `list_ultra_courses(user_pk=None)` | The full Ultra-side set, archived and hidden included. |
| `fetch_portal_detail(batch_uid)` | Description, instructors, and admin URLs from the portal. |
| `fetch_ultra_course(course_pk)` | Ultra course detail with instructor memberships. |
| `fetch_members(course_pk, ...)` / `fetch_member_counts(course_pk)` | Roster and per-bucket counts. |
| `fetch_announcements(course_pk, ...)` / `fetch_announcement_counts(course_pk)` | Announcements and read counts. |
| `fetch_schedule(course_pk, ...)` | Per-course calendar items. |
| `fetch_user_grades(course_pk, user_pk, ...)` / `fetch_my_grades(course_pk)` | Per-column grade records with column metadata expanded inline. |
| `set_favorite(portal_uuid, favorite)` | Pins or unpins a course. |
| `resolve(courses, ref)` | Static. Every course matching a reference in any of its identifier forms. |
| **content** | |
| `fetch_content(course_pk, content_id)` / `fetch_children(course_pk, parent_id)` | One item / one item's children. |
| `walk_contents(course_pk, max_depth=None)` | Generator over the tree in pre-order, with the Ultra Document short-circuit baked in. |
| `fetch_body_and_embeds(course_pk, content_id)` | Descends the Ultra Document wrapper, renders markdown, and parses embeds in one call. |
| `is_bb_page(item)` / `pick_bb_page_child(children)` | Static helpers for the Ultra Document shape. |
| `extract_embeds(html)` / `render_markdown(html)` | Static. Lift structured embeds out of Blackboard's rich-text dialect / render it to markdown via `markitdown`. |
| **discussions** | |
| `list_discussions(course_pk)` | Discussion-forum content items with their forum ids. |
| `fetch_forum(course_pk, forum_id)` / `fetch_forum_counts(...)` | One forum's metadata and counts. |
| `list_forum_messages(course_pk, forum_id)` | Root threads. |
| `list_message_replies(course_pk, forum_id, message_id, ...)` | One message's replies as a paging envelope. |
| **files** | |
| `discover_files(course_pk)` | Every downloadable as `list[FileItem]`: file leaves, body embeds, and Kaltura videos. |
| `resolve_download_url(item)` / `resolve_signed_url(item)` | A session-bound / standalone-fetchable URL for one item. |
| `download_file_item(item, dest_path)` / `stream_file_item(item, writable)` | Download to disk or stream to any binary writable. |
| `find_item(items, file_id)` | Static. Look a `FileItem` up by its synthetic id. |

### `KurtClient`

Wraps `kurt3.ghum.kuleuven.be/api`; auth is already on the session's cookie jar.

| Method | Description |
| --- | --- |
| `get_user_info()` / `get_account()` | Who you are; `get_account` adds your quotas (`-1` is unlimited). |
| `list_tiles()` | Locations grouped into city tiles. |
| `get_location(id)` / `list_resource_types(id)` / `get_occupancy(id)` | One location's zones, bookable resource types, and live occupancy. |
| `get_resource(id)` | Resource detail with booking constraints. |
| `search_availability(...)` | Availability search, same shape as the CLI flags. |
| `list_favorites()` | Starred resources. |
| `list_reservations(only_today=False)` / `get_reservation(id)` | Your reservations. |
| `create_reservation(resource_id, resource_name, ...)` | Books. `resource_name` must echo the resource's `name` field — KURT rejects the request with a bare 400 otherwise. |
| `update_reservation(reservation)` / `cancel_reservation(id)` | Edit or cancel. |

### Models

Responses are Pydantic models in `kuleuven.models`; call `.model_dump(mode="json")` to get the same shape the CLI emits. Two kinds: curated models with chosen snake_case fields (`Course`, `Person`, `Membership`, `Announcement`, `FileItem`, `Embed`, …) and API-echo models that mirror the upstream JSON verbatim, camelCase keys preserved (`Reservation`, `Location`, `MemberCounts`, …). Role values and content handlers come through raw — the library does not maintain a translation table that could fall behind Blackboard's vocabulary.

`Course` deserves a note: it collects the cross-system identity (`batch_uid`, `pk`, `portal_uuid`, `course_uuid`, `foundations_id`), has one constructor per source view, and `.merge(other)` joins two views field-wise — which is how `courses show` builds its single record. `course_code` is parsed out of the batchUid.

### Exceptions

| Exception | When |
| --- | --- |
| `AuthenticationError` | Any failure in the SAML or per-SP bootstrap flow. Base class of the rest. |
| `InvalidCredentialsError` | The IdP rejected the username or password. |
| `AuthApprovalTimeoutError` | The Authenticator push was not approved within 120 s. |
| `AuthApprovalFailedError` | The push was rejected or the WebSocket errored. |
| `SessionExpiredError` | An API call hit a Shibboleth re-auth bounce — the SP session expired. |

`httpx.HTTPError` from the underlying HTTP layer is propagated, not wrapped.

## Tests

```sh
uv run pytest
```

The suite is offline: HTTP is mocked with [respx](https://lundberg.github.io/respx/) at the transport layer, and CLI tests redirect the cookie jar to a temp path, so no real KU Leuven request goes out and your on-disk session is never touched.
