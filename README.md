# python-kuleuven

CLI, MCP server, and Python client for KU Leuven. Signs in through the SAML2 SSO flow at `idp.kuleuven.be` and gives you one session that works against the Toledo portal, Blackboard Ultra, and the KURT study-space reservation system.

See [`docs/AUTH.md`](docs/AUTH.md) for the sign-in flow and [`docs/DATA.md`](docs/DATA.md) for the REST surface. New to the command line? [`docs/index.md`](docs/index.md) walks through the Claude Desktop setup from zero.

## Installation

Requires Python 3.13 or newer and [uv](https://docs.astral.sh/uv/). To install the `kuleuven` command globally:

```sh
uv tool install git+https://github.com/breitburg/python-kuleuven
```

To work on the project itself, clone it and run `uv sync` instead. The command is then available inside the project environment as `uv run kuleuven …`.

## Quickstart

Sign in once. Credentials can also come from `$KULEUVEN_USERNAME` / `$KULEUVEN_PASSWORD` or a `.env` file:

```sh
kuleuven session start
```

Then use any command. The JSON output pipes straight into `jq`:

```sh
kuleuven toledo courses list --type course | jq '.items[].course_code'
```

To pull all the files of a course onto disk:

```sh
kuleuven toledo courses files sync EX101a --into ./downloads --skip-videos
```

### AI agents

The interface is built for agents. Every command prints exactly one JSON object to stdout, errors included, and `kuleuven docs` emits the full command reference so an agent can learn the whole surface in a single call.

To let Claude book your study spaces and read your courses, register the MCP server and restart Claude Desktop:

```sh
kuleuven mcp install
```

Claude then gets every command as a tool and reuses your signed-in session. See the [Claude Desktop](#claude-desktop) section for details.

## CLI

Every command exits `0` on success, `1` on auth or HTTP failure, and `2` on bad input. Errors are printed as JSON on stdout too, so a pipeline only parses one stream.

### `kuleuven docs`

Prints Markdown documentation for the whole command tree, generated from the live CLI, with the usage, arguments, and options of every command. Unlike every other command it prints raw Markdown, meant to be read or piped to a file:

```sh
kuleuven docs > COMMANDS.md
```

### Session

#### `kuleuven session start`

Signs in to the portal, Ultra, and KURT and saves the cookies. Credentials come from `--username` and `--password`, the matching `KULEUVEN_*` environment variables (`KULEUVEN_USERNAME`, `KULEUVEN_PASSWORD`, `KULEUVEN_TOTP`, `KULEUVEN_AUTH_DEVICE`), or a `.env` file, and are prompted for only on a TTY.

The second factor depends on your account: TOTP accounts pass `--totp` (or get prompted), accounts on the KU Leuven Authenticator app get a push sent to the device chosen with `--device` and the command waits up to 120 seconds for approval.

```sh
kuleuven session start --device "My phone"
```

On success it prints your session attributes and expiry:

```json
{
  "status": "ok",
  "session": {
    "attributes": { "uid": "r0123456", "KULMoreUnifiedUID": "q1234567", "...": "..." },
    "expires_in_minutes": 2880,
    "authenticated_at": "2026-01-01T12:00:00.000Z"
  }
}
```

The IdP remembers your device, so 2FA only happens once per machine. Credentials are never written to disk. The only thing saved is the session cookie jar, at `platformdirs.user_data_path("kuleuven") / "cookies.json"` with `0600` permissions.

#### `kuleuven session status`

Checks whether the saved session still works:

```sh
kuleuven session status
```

Exits `1` with `reason: "no_session"` or `reason: "expired"` when it doesn't. An `authentication_context_class` of `MobileTwoFactorContract` in the output confirms the session was 2FA-elevated.

#### `kuleuven session end`

Deletes the saved session:

```sh
kuleuven session end
```

Idempotent: `removed` is `false` if there was nothing to delete.

#### `kuleuven session raw`

Sends a pre-authenticated request to any URL, using the saved cookies. This is the escape hatch for endpoints the higher-level commands don't cover:

```sh
kuleuven session raw GET 'https://toledo.kuleuven.be/portal/api/upcoming'
```

The response comes back wrapped, with the status code, final URL, headers, and parsed body:

```json
{
  "status": "ok",
  "response": {
    "status_code": 200,
    "url": "https://toledo.kuleuven.be/portal/api/upcoming",
    "body_kind": "json",
    "body": [ { "name": "Other Example", "start": 1900000000000, "...": "..." } ]
  }
}
```

Pass `--body` to send a JSON body. Query parameters belong in the URL. Non-2xx responses are returned the same way, not treated as errors.

### Toledo

Toledo commands live under `kuleuven toledo courses`, with `content`, `files`, and `discussions` nested per course. The `<ref>` argument takes any identifier of a course, most conveniently the case-insensitive course code like `EX101a`. The batchUid, Blackboard pk, and UUIDs work too, and when a code matches several academic years the command exits `2` and lists the candidates.

#### `kuleuven toledo courses list`

Lists your courses and communities. Filter with `--favorite`, `--type course|community`, `--semester`, or `--year 2526`. Add `--all` to include archived and hidden enrollments.

```sh
kuleuven toledo courses list --type course
```

Each item carries the course's identifiers, name, year, semester, and role:

```json
{
  "status": "ok",
  "count": 15,
  "items": [
    {
      "course_code": "EX101a",
      "batch_uid": "ULTRA-B-KUL-EX101a-2526",
      "display_name": "Example Course [EX101a]",
      "academic_year": 2526,
      "semester": "SEMESTER2",
      "role": "Learner",
      "favorite": false
    }
  ]
}
```

#### `kuleuven toledo courses show`

Shows everything known about one course as a single merged record, including its instructors:

```sh
kuleuven toledo courses show EX101a
```

The output adds the Blackboard pk, UUIDs, availability, locale, and an `instructors` list with names and emails.

#### `kuleuven toledo courses favorite`

Pins a course on the portal dashboard, or unpins it with `--off`:

```sh
kuleuven toledo courses favorite EX101a
```

Only portal-visible courses can be favourited. An Ultra-only course exits `2` with `code: "not_in_portal"`.

#### `kuleuven toledo courses members`

Lists who is enrolled, with per-role counts. Filter with `--role-bucket TEACHING|LEARNING|SUPPORT`, or add `--all-members` to include disabled memberships:

```sh
kuleuven toledo courses members EX101a --role-bucket TEACHING
```

Each item has the person's q-uid, name, and email, plus the raw role codes from Ultra.

#### `kuleuven toledo courses announcements`

Lists announcements, with bodies rendered to markdown. `--unread` keeps only what you haven't read, and `--limit` caps the fetch (default 100):

```sh
kuleuven toledo courses announcements EX101a --unread
```

The response includes `counts` with `postedCount` and `unreadCount`, so an unread badge is one call.

#### `kuleuven toledo courses schedule`

Returns the course's own calendar items, optionally windowed with `--from` and `--to` (ISO timestamps):

```sh
kuleuven toledo courses schedule EX101a
```

In practice this endpoint is sparsely populated. For "what's next", use `session raw GET …/portal/api/upcoming` instead.

#### `kuleuven toledo courses grades`

Lists your per-item grades in a course. Instructors can pass `--user` with a Blackboard user pk to query a student:

```sh
kuleuven toledo courses grades EX102a
```

Each item is a gradebook record with `displayGrade`, `submissionStatus`, attempts, and the column's name, points, and due date.

#### `kuleuven toledo courses content tree`

Walks the content tree and emits every node in pre-order, and `--depth N` bounds the recursion:

```sh
kuleuven toledo courses content tree EX101a --depth 1
```

Each node carries its id, parent, title, and handler:

```json
{
  "status": "ok",
  "count": 16,
  "items": [
    { "id": "_10000_1", "title": "Lecture recordings", "handler": "resource/x-bb-folder", "is_bb_page": false, "depth": 0 },
    { "id": "_10002_1", "title": "Lecture 1: Introduction", "handler": "resource/x-bb-folder", "is_bb_page": true, "depth": 0 }
  ]
}
```

Items with `is_bb_page: true` are Ultra Documents, which are pages rather than folders. The tree treats them as leaves, and `content show` reads their body for you.

#### `kuleuven toledo courses content show`

Shows one content item by the id from `content tree`. For documents you also get the body as markdown and the parsed embeds:

```sh
kuleuven toledo courses content show EX101a _10002_1
```

The `embeds` array lists each attachment or LTI launch found in the body, with its title, URL, and mime type.

#### `kuleuven toledo courses content embeds`

Lists just the embeds of one item, handy when you don't need the body:

```sh
kuleuven toledo courses content embeds EX101a _10002_1
```

Each embed has a `kind` (`file` or `lti`), a `title`, a `url`, and the full raw payload from Blackboard.

#### `kuleuven toledo courses files list`

Lists every downloadable in the course as one flat list, covering file leaves in the tree, attachments embedded in document bodies, and Kaltura videos:

```sh
kuleuven toledo courses files list EX101a
```

Each item has a synthetic `id` to pass to `fetch` or `resolve` (`<content_pk>@<index>` for body embeds), a `kind` of `file` or `video`, a filename, and a `source_path` with the folder chain it lives under.

#### `kuleuven toledo courses files fetch`

Downloads one file or video by its id. `--out` takes a file path, an existing directory, or `-` to stream raw bytes to stdout. When omitted, the file is written to the current directory under its own name:

```sh
kuleuven toledo courses files fetch EX101a '_10002_1@0' --out lecture-1.pdf
```

Streaming works for videos too:

```sh
kuleuven toledo courses files fetch EX101a '_10100_1' --out - > lecture-1.mp4
```

#### `kuleuven toledo courses files resolve`

Resolves a short-lived URL that any HTTP client can fetch without authentication, useful for handing a download to another tool:

```sh
kuleuven toledo courses files resolve EX101a '_10000_1@0'
```

The returned URL stays valid for a few hours.

#### `kuleuven toledo courses files sync`

Downloads every file and video in a course, mirroring the folder structure on disk. `--into` picks the destination (default: a directory named after the course code), `--skip-videos` skips Kaltura videos, and `--dry-run` reports the plan without writing:

```sh
kuleuven toledo courses files sync EX101a --into ./downloads --skip-videos
```

Already-existing files are kept, and per-item failures land in a `failures` array instead of aborting the run, and `status` becomes `"partial"` when some items failed.

#### `kuleuven toledo courses discussions list`

Lists the discussion forums of a course, with the `forum_id` the other discussion commands need:

```sh
kuleuven toledo courses discussions list EX103c
```

#### `kuleuven toledo courses discussions show`

Shows one forum's metadata, read/reply counts, and its root threads:

```sh
kuleuven toledo courses discussions show EX103c _99089_1
```

Each thread's `messageStatus.totalCount` tells you how many replies to expect underneath.

#### `kuleuven toledo courses discussions replies`

Lists the replies to one message, paginated with `--limit` and `--offset`:

```sh
kuleuven toledo courses discussions replies EX103c _99089_1 _565094_1 --limit 25
```

Follow `next_page` in the response while more remain.

### KURT

The `kuleuven kurt` commands book study seats, group rooms, and equipment. Dates are `YYYY-MM-DD` and times are `HH:MM` on the hour. A new day becomes bookable each evening one week out.

#### `kuleuven kurt locations list`

Lists every bookable location, grouped into city tiles:

```sh
kuleuven kurt locations list | jq '.tiles[].locations[] | {id, unit}'
```

The numeric `id` is what the other commands take.

#### `kuleuven kurt locations show`

Shows one location with its zones, its bookable resource types, and a live occupancy snapshot (skip it with `--no-occupancy`):

```sh
kuleuven kurt locations show 10
```

The resource type ids listed here feed into `resources search`.

#### `kuleuven kurt resources search`

Searches what's bookable at a location for a window. `--location`, `--type`, and `--date` are required. Narrow with `--start`/`--end`, `--zone`, `--participants`, `--name`, or `--only-favorites`. Leave the times blank to see every resource regardless of availability:

```sh
kuleuven kurt resources search --location 10 --type 302 --date 2026-05-25 --start 09:00 --end 12:00
```

Each result includes `slotAllocation`, a 24-character string with one letter per hour: `A` free, `B` booked, `C` closed.

#### `kuleuven kurt resources quotas`

Shows your usage and limits per resource type, per day and week:

```sh
kuleuven kurt resources quotas
```

A `-1` in a `max*` field means unlimited.

#### `kuleuven kurt resources favorites`

Lists the resources you've starred in KURT:

```sh
kuleuven kurt resources favorites
```

#### `kuleuven kurt resources reservations`

Lists your current and future reservations, and `--today` keeps only those whose window includes today:

```sh
kuleuven kurt resources reservations
```

The reservation ids here are what `unbook` takes.

#### `kuleuven kurt resources book`

Books a resource for a window. Add `--subject` and `--purpose` where the resource type requires them, and repeat `--participant uid:email` for group rooms (you are always included):

```sh
kuleuven kurt resources book --resource 301108 --date 2026-05-25 --start 09:00 --end 12:00
```

A group room with extra participants looks like:

```sh
kuleuven kurt resources book --resource 200001 --date 2026-05-26 --start 14:00 --end 16:00 \
  --participant r0000001:first.collab@kuleuven.be \
  --participant r0000002:second.collab@kuleuven.be
```

#### `kuleuven kurt resources unbook`

Cancels a reservation by id:

```sh
kuleuven kurt resources unbook 3963083203
```

### Claude Desktop

The `kuleuven mcp` commands expose the CLI as an MCP server. The tools mirror the CLI verbs one-for-one (`kuleuven_toledo_courses_list`, `kuleuven_kurt_resources_search`, and so on) with the same arguments, JSON output, and cookie jar. Sign in once with `kuleuven session start` in a terminal and Claude Desktop reuses the session. For a from-scratch walkthrough aimed at non-developers, see [`docs/index.md`](docs/index.md).

#### `kuleuven mcp install`

Registers the server in Claude Desktop's config. Restart Claude Desktop afterwards. Use `--name` to register more than one instance:

```sh
kuleuven mcp install
```

If you set `KULEUVEN_USERNAME` and `KULEUVEN_PASSWORD` in the server's `env` block in `claude_desktop_config.json`, Claude can refresh expired sessions on its own.

#### `kuleuven mcp uninstall`

Removes the entry again:

```sh
kuleuven mcp uninstall
```

#### `kuleuven mcp start`

The stdio server itself, invoked by Claude Desktop rather than by humans:

```sh
kuleuven mcp start
```

It exposes every CLI command except the disk-writing ones (`files fetch`, `files sync`). Claude gets `files resolve` instead.

## Python API

The library is pure: HTTP in, Pydantic models out, with no disk I/O, environment reads, or prompting. `KuleuvenSession` owns the `httpx.Client` and the sign-in. `ToledoClient` and `KurtClient` are built from it and share its cookies.

```python
from kuleuven import KuleuvenSession, ToledoClient, KurtClient

class Authenticator:
    # Satisfies the AuthenticationProvider protocol. Each method is called only
    # if the IdP demands it: provide_totp for a TOTP form, select_device and
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

The library does not persist cookies. That part lives in the CLI. To reuse a saved session in your own code, build an `httpx.Client` with the cookies loaded yourself and pass it as `KuleuvenSession(http_client=...)`. Check `session.session_info()` to see whether it still works.

### Working with courses

`ToledoClient` covers the portal and Ultra. `list_portal_courses()` returns your dashboard courses, and `list_ultra_courses()` returns everything Blackboard knows about, archived included. `ToledoClient.resolve(courses, ref)` matches any identifier form against a course list, the same way the CLI does:

```python
courses = toledo.list_portal_courses()
course = ToledoClient.resolve(courses, "EX101a")[0]
```

Everything else hangs off the course's `pk`, with one `fetch_*` method per CLI command:

```python
teachers = toledo.fetch_members(course.pk, role_bucket="TEACHING")
announcements = toledo.fetch_announcements(course.pk)
grades = toledo.fetch_my_grades(course.pk)
```

### Content and files

`walk_contents(course_pk)` generates the content tree in pre-order, handling the Ultra Document wrinkle for you. For one document, `fetch_body_and_embeds(course_pk, content_id)` returns the body as markdown plus the parsed embeds in one call:

```python
for node in toledo.walk_contents(course.pk, max_depth=2):
    print("  " * node.depth, node.title)
```

Downloads start from `discover_files(course_pk)`, which returns every downloadable in the course as a flat `list[FileItem]`, Kaltura videos included:

```python
from pathlib import Path

files = toledo.discover_files(course.pk)
slides = next(f for f in files if f.filename.endswith(".pdf"))
toledo.download_file_item(slides, Path(slides.filename))
```

To write somewhere other than a file, `stream_file_item(item, writable)` streams into any binary writable. `resolve_signed_url(item)` returns the same standalone URL as `files resolve`.

### KURT

`KurtClient` mirrors the KURT commands. Find a location and resource type with `list_tiles()`, `get_location(id)`, and `list_resource_types(id)`, then search for a free slot and book it:

```python
result = kurt.search_availability(
    location_id=10,
    resource_type_id=302,
    start_date="2026-05-25",
    end_date="2026-05-25",
    start_time="09:00",
    end_time="12:00",
)
seat = result.availabilities[0]

kurt.create_reservation(
    resource_id=seat.resource_id,
    resource_name=seat.resource_name,
    start_date="2026-05-25",
    end_date="2026-05-25",
    start_time="09:00",
    end_time="12:00",
)
```

Passing `resource_name` is not optional. KURT rejects the request with a bare 400 unless it echoes the resource's name exactly, which is why the example takes it from the search result.

Manage what you booked with `list_reservations()`, `update_reservation(...)`, and `cancel_reservation(id)`, and check your booking limits with `get_account()`.

### Models

Responses are Pydantic models in `kuleuven.models`. Call `.model_dump(mode="json")` to get the same shape the CLI prints. Curated models like `Course`, `Person`, and `FileItem` use snake_case fields, while API-echo models like `Reservation` and `Location` mirror the upstream JSON verbatim. Role values and content handlers come through raw, untranslated.

### Exceptions

Auth failures raise `kuleuven.AuthenticationError` or one of its subclasses:

- `InvalidCredentialsError`: the IdP rejected the username or password
- `AuthApprovalTimeoutError`: the Authenticator push wasn't approved within 120 s
- `AuthApprovalFailedError`: the push was rejected or the WebSocket errored
- `SessionExpiredError`: an API call hit a re-auth bounce, so sign in again

`httpx.HTTPError` from the HTTP layer is propagated, not wrapped.

## Tests

The suite is offline. HTTP is mocked at the transport layer with [respx](https://lundberg.github.io/respx/), and CLI tests redirect the cookie jar to a temp path, so nothing touches the live hosts or your saved session:

```sh
uv run pytest
```
