# Toledo data surface, reverse-engineered

Companion to [`AUTH.md`](AUTH.md) (which covers SSO/auth). This document
catalogues the REST APIs reached through the shared KU Leuven IdP — the
Toledo portal, Blackboard Ultra, and KURT3 — along with their data shapes
and the relationships between objects.

Observed by clicking through the live UI in a real browser and capturing all
XHR traffic. Every endpoint, field name, and enum value is reproduced from
actual responses.

---

## 1. Two systems, one front door

What "Toledo" actually is, in practice:

```
┌────────────────────────────────────────────────────────────────────────┐
│                  toledo.kuleuven.be/portal/  (Vue SPA)                 │
│  - dashboard: enrollments grid, updates feed, timetable, links         │
│  - backend: Plone — REST API at /portal/api/*                          │
│  - authn: Shibboleth SP, _shibsession_* cookie  (see AUTH.md)          │
└────────────────────────────────────────────────────────────────────────┘
                          │  click into a course
                          ▼  (LTI launch)
┌────────────────────────────────────────────────────────────────────────┐
│   icts-p-toledo-journey.cloud.icts.kuleuven.be/learningUnits/ultraLink │
│   ?batchUid=ULTRA-...                                                  │
│  - thin redirector: maps batchUid → Blackboard course ID, then 302s    │
└────────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────────────┐
│              ultra.edu.kuleuven.cloud  (Blackboard Learn Ultra)        │
│  - actual LMS: content, assignments, grades, messages, calendar        │
│  - backend: Blackboard Learn REST — /learn/api/v1/* + /public/v1/*     │
│  - authn: own session cookie, established via SAML+LTI from KU Leuven  │
└────────────────────────────────────────────────────────────────────────┘
```

The Toledo portal is a thin **gateway and notification aggregator**. The
actual learning content lives in Blackboard Ultra. To do anything beyond
listing courses and reading the activity feed, you must launch into Ultra
and use its API.

---

## 2. Toledo portal API (`toledo.kuleuven.be/portal/api`)

All endpoints gated by `_shibsession_*` cookie. All responses are JSON.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/portal/api/info?language=en` | Structured navigation links (the dropdown menus) |
| GET | `/portal/api/links` | List of enabled UI feature IDs |
| GET | `/portal/api/enrollments` | All courses + communities the user is in |
| GET | `/portal/api/enrollments/<learningUnitId>/<lang>` | Enrollment detail (instructors, admin URLs) |
| PATCH | `/portal/api/enrollments/<enrollment-uuid>` | Toggle favourite (`{"favorite":true\|false}`) |
| GET | `/portal/api/upcoming` | Upcoming calendar events (timetable next few days) |
| GET | `/portal/api/events` | Notification feed |
| GET | `/portal/api/activities` | Same shape as `/events` |
| PATCH | `/portal/api/batch/events` | Mark notifications as seen (batch) |
| GET | `/portal/api/emails/unread` | Unread email count |
| GET | `/portal/api/emails/unread/cloud/initialize` | Microsoft Graph link bootstrap |
| GET | `/portal/api/monitor/links/<id>` | Telemetry beacon (returns 204) |

### 2.1 `GET /portal/api/enrollments`

Returns an array of enrollments. Every item is either a `course` (real
academic course) or a `community` (administrative group, library, study
support, etc.).

```json
{
  "id": "00000000-0000-0000-0000-000000000001",
  "academicYear": 2526,
  "available": true,
  "color": 10,
  "learningUnitId": "ULTRA-B-KUL-EX101a-2526",
  "favorite": false,
  "official": true,
  "officialReference": null,
  "title": "Example Course [EX101a]",
  "type": "course",
  "link": "https://icts-p-toledo-journey.cloud.icts.kuleuven.be/learningUnits/ultraLink?batchUid=ULTRA-B-KUL-EX101a-2526",
  "role": "Learner",
  "imageUrl": "ltc/ec4ad782a4f8e08b97fc5f1dd1246489",
  "studentEnrollPolicy": "OPEN",
  "staffEnrollPolicy": "OPEN",
  "semester": "SEMESTER2",
  "platform": "BB_CLOUD",
  "production": true
}
```

Field reference:

| Field | Notes |
|---|---|
| `id` | Portal-side UUID. Used as the path segment for the favourite-toggle PATCH. |
| `learningUnitId` | The **batchUid**. Format: `ULTRA-{type}-{realm}-{code}-{year}` where type is `B` (regular course), `C` (community), `S` (sandbox); realm is `KUL` or numeric tenant; year is `YYYY` (e.g. `2526` = 2025/2026). |
| `academicYear` | Year code matching the batchUid suffix, or `0` for evergreen communities. |
| `available` | `false` means the course exists but the instructor has hidden it from students. |
| `color` | Integer 1–16; index into the SPA's palette for the tile colour. |
| `type` | `"course"` or `"community"`. |
| `link` | Direct LTI launch URL — pasting this in a browser navigates straight to the course in Ultra. |
| `imageUrl` | Relative path (`ltc/<hash>`). Resolves to `/portal/ltc/<hash>` for the course tile thumbnail. |
| `studentEnrollPolicy` / `staffEnrollPolicy` | `OPEN` / `CLOSED`. Whether self-enrollment is allowed. |
| `semester` | `SEMESTER1`, `SEMESTER2`, or `UNKNOWN` (for year-round communities). |
| `platform` | Always `BB_CLOUD` in current state (legacy values: `ON_PREMISE` for pre-migration courses — none observed). |
| `role` | The user's role in this enrollment — `Learner`, `Instructor`, `TeachingAssistant`, etc. |

### 2.2 `GET /portal/api/enrollments/<learningUnitId>/<lang>`

The detail endpoint, keyed by `learningUnitId` (the batchUid, **not** the
portal UUID). Returns instructor list + administrative URLs that bounce
through `p.cygnus.cc.kuleuven.be` (legacy SP) or
`icts-p-toledo-journey.cloud.icts.kuleuven.be` (new Bizz UI).

```json
{
  "ectsLink": null,
  "description": "Shared Toledo community for ...",
  "instructors": [
    { "id": "q0017547", "firstName": "Johan", "lastName": "Eyckmans" },
    { "id": "q0409843", "firstName": "Nicky",  "lastName": "Dries"   }
  ],
  "unenrollUrl":           "https://p.cygnus.cc.kuleuven.be/...",
  "availabilityUrl":       "https://p.cygnus.cc.kuleuven.be/...",
  "manageUrl":             "https://p.cygnus.cc.kuleuven.be/...",
  "usersUrl":              "https://p.cygnus.cc.kuleuven.be/...",
  "notificationsUrl":      "https://p.cygnus.cc.kuleuven.be/...",
  "gradeCenterToolUrl":    "https://icts-p-toledo-journey.cloud.icts.kuleuven.be/export/ultra/grades?batchUid=...",
  "attemptsDownloadUrl":   "https://icts-p-toledo-journey.cloud.icts.kuleuven.be/export/ultra/attempts?batchUid=...",
  "bizzUILanguageUrl":     "https://icts-p-toledo-journey.cloud.icts.kuleuven.be/learningUnits/language?batchUid=...",
  "bizzUIEnrollmentsUrl":  "https://icts-p-toledo-journey.cloud.icts.kuleuven.be/learningUnits/enrollments?batchUid=...",
  "bizzUITitleAndDescriptionUrl": "...",
  "bizzUIEnrollAsStudentUrl":     "...",
  "impexUrl":              "https://icts-p-toledo-journey.cloud.icts.kuleuven.be/impex/learningUnits?batchUid=...",
  "canPersist": true,
  "stmLink": null,
  "stmDocentLink": null,
  "migrateUrl": ""
}
```

`instructors[].id` is a **`q*` uid** — distinct from the student-facing
`r*` uid (e.g. `r0123456`). Both refer to the same KU Leuven person record.

### 2.3 `GET /portal/api/upcoming`

Calendar events (lectures, labs) for the next few days. Times are
**milliseconds since epoch UTC**.

```json
{
  "start": 1779179400000,
  "end":   1779186600000,
  "name":  "Dutch 2",
  "description": null,
  "location": {
    "url":        "https://www.kuleuven.be/lokalen/51922216.htm",
    "mnemonic":   "HER1",
    "roomNumber": "05.5212"
  },
  "source": {
    "learningUnitId": "ULTRA-B-KUL-EX102a-2526",
    "link":           "https://icts-p-toledo-journey.cloud.icts.kuleuven.be/learningUnits/ultraLink?batchUid=ULTRA-B-KUL-EX102a-2526",
    "color":          13
  }
}
```

`source.color` matches the corresponding enrollment's `color` — that's how
the SPA paints calendar entries.

The window is hard-coded server-side; no query parameters were observed to
shift it. For arbitrary date ranges, use Ultra's
`/learn/api/v1/calendars/items` instead (§3.5).

### 2.4 `GET /portal/api/events` and `/portal/api/activities`

Same shape: the unified notification feed. Activities include posted
content, due dates, announcements, tests, and Ad Valvas messages.

```json
{
  "id":         "ultra~_555227485_1",
  "type":       "notifications",
  "subType":    "due",
  "eventType":  "update",
  "title":      "ASSIGNMENT: (exam-alike) Multiple Choice Questions (due date 22/5/26)",
  "source":     "ICT Management 3B BA [HBA22c]",
  "sourceId":   "ULTRA-B-KUL-HBA22c-2526",
  "author":     "Almer Güngör",
  "color":      2,
  "date":       1779487140000,
  "read":       false,
  "seen":       false,
  "dismissed":  false,
  "url":        "https://ultra.edu.kuleuven.cloud/ultra/redirect?redirectType=nautilus&courseId=_124066_1&contentId=_8678338_1&parentId=_8293843_1"
}
```

Enum values seen:

| Field | Values |
|---|---|
| `type` | `notifications`, `advalvas` |
| `eventType` | `update`, `message` |
| `subType` | `content`, `due`, `course`, `test`, `announcement`, `advalvas`, `other` |

Distribution from a real account (413 items):

```
('notifications', 'update',  'content'):       318
('notifications', 'message', 'announcement'):  59
('notifications', 'update',  'test'):          22
('notifications', 'update',  'course'):        7
('advalvas',      'message', 'advalvas'):      5
('notifications', 'update',  'due'):           1
('notifications', 'update',  'other'):         1
```

The `url` field is a `ultra/redirect?redirectType=nautilus&courseId=...&contentId=...&parentId=...`
deep link — the legacy notification redirector. Path components reference
Blackboard internal IDs (`_NUMBER_1`).

### 2.5 `PATCH /portal/api/batch/events`

Marks notifications as seen. Body is an array of `{id, type, subType,
seen}` objects (same shape as the items returned from `/events`, projected
to those four fields). Response is 200 with empty body.

```json
[
  {"id":"ultra~_555227485_1","type":"notifications","subType":"due","seen":true},
  {"id":"ultra~_614173702_1","type":"notifications","subType":"content","seen":true}
]
```

The SPA batches every visible notification on the updates view in a single
PATCH call.

### 2.6 `PATCH /portal/api/enrollments/<uuid>`

```json
{ "favorite": true }
```

Returns 200. The next `GET /enrollments` will show `favorite: true` for
that enrollment, and the SPA pins it to the top of the grid.

### 2.7 `GET /portal/api/info?language=en`

Top-level navigation, grouped by sidebar label. Each link is either a URL
or a client-side action.

```json
[
  {
    "label": "KULOKET",
    "links": [
      { "label": "KULOKET-STUDENT",          "translation": "KU Loket",         "ordernr": 12, "url": "https://www.kuleuven.be/kuloket", "action": null },
      { "label": "KULOKET-STUDENT-DOSSIER",  "translation": "Student record",   "ordernr": 30, "url": "https://www.kuleuven.be/kuloket", "action": null },
      { "label": "KULOKET-UURROOSTER",       "translation": "Schedule",         "ordernr": 40, "url": "https://kuleuven.be/kuloket/zr_0367?sap-language=EN", "action": null }
    ]
  }
]
```

Observed groups: `OTHER`, `HELP`, `UPCOMING`, `MY-INSTITUTION`, `KULOKET`,
`TOOLS`, `FILES-AND-PORTFOLIOS`.

Interesting links to know:

| Label | URL | What it is |
|---|---|---|
| `KULOKET-UURROOSTER` | `kuleuven.be/kuloket/zr_0367` | Authoritative timetable (SAP backend) |
| `KULOKET-ISP` | `kuleuven.be/kuloket/zr_0442` | Individual study plan |
| `KULOKET-PROGRESS` | `kuleuven.be/kuloket/zr_1017` | Academic progress file |
| `KULOKET-STUDYTRACKER` | `kuleuven.be/kuloket/zr_0184` | Study analytics |
| `LOGOUT` | `Shibboleth.sso/Logout` | Terminate SP session |
| `BB-GRADES-ULTRA` | `ultra.edu.kuleuven.cloud/ultra/grades` | Cross-course grades view |
| `BB-CALENDAR-ULTRA` | `ultra.edu.kuleuven.cloud/ultra/calendar` | Cross-course calendar |
| `BB-MESSAGES-ULTRA` | `ultra.edu.kuleuven.cloud/ultra/messages` | Cross-course inbox |

### 2.8 `GET /portal/api/links`

Returns an array of feature-flag IDs that should be **enabled** in the UI.

```json
[
  "link-ultra-calendar", "link-kul-privacy", "vue-upcomings-component",
  "link-ultra-messages", "vue-enrollment-info-component", "vue-enrollments-component",
  "link-bb-grades", "link-kaltura-mymedia", "vue-info-component", "upcoming-module"
]
```

Acts as a server-driven feature flagger. Items not in the list are hidden
in the SPA.

### 2.9 `GET /portal/api/emails/unread`

```json
{ "value": 140, "origin": "MSCLOUD" }
```

`origin: "MSCLOUD"` indicates the count comes from Microsoft 365 / Outlook,
via the `/portal/api/emails/unread/cloud/initialize` linking endpoint.

---

## 3. Blackboard Ultra API (`ultra.edu.kuleuven.cloud/learn`)

Gated by Blackboard's own session cookie (established via the SAML+LTI
launch from the Toledo SP). All paths under `/learn/api/v1/*` are the
**Blackboard Learn REST API** — documented publicly by Blackboard at
`developer.blackboard.com`. Below are only the endpoints exercised by the
Ultra SPA in practice.

### 3.1 ID systems used here

Blackboard uses several distinct ID schemes — they are **not
interchangeable**:

| ID type | Example | Where used |
|---|---|---|
| Blackboard course PK | `_157246_1` | All `/learn/api/v1/courses/<id>/...` paths |
| Blackboard user PK | `_544865_1` | All `/learn/api/v1/users/<id>/...` paths |
| Blackboard content PK | `_10550931_1` | Content children, lessons, items |
| `batchUid` | `ULTRA-C-26738544-K-2526` | LTI launch URL — Toledo's identifier |
| `displayId` | `ULTRA-C-26738544-K-2526` | Same as batchUid in current setup |
| UUIDs | `169f0e51dd50470abe94098cd10ab7ca` | User profile, content references |
| `foundationsId` | `e9d942b8-5ce9-11f0-95b5-0f4a13ec4b12` | Cross-region Anthology Foundations identifier |
| `userName` | `q1686864` | The KU Leuven q-uid (matches portal `instructors[].id`) |
| `studentId` | `00971578` | Student number (without `r0` prefix from auth) |

The `learningUnitId` from `/portal/api/enrollments` → resolved into the
`_NUMBER_1` Blackboard PK by the LTI launch redirector. There is no portal
endpoint to look up the mapping directly — you must follow the LTI launch
once and capture the resulting `/ultra/courses/_NNNN_1/outline` URL.

### 3.2 Current user

```
GET /learn/api/v1/users/me?expand=systemRoles,insRoles
```

```json
{
  "id":          "_544865_1",
  "uuid":       "169f0e51dd50470abe94098cd10ab7ca",
  "foundationsId": "e7f9cf49-35bb-11ee-b6a4-e5a82809bdfd",
  "userName":   "q1686864",
  "studentId":  "00971578",
  "givenName":  "Jane",
  "familyName": "Doe",
  "emailAddress": "...@student.kuleuven.be",
  "locale":     "en_US",
  "systemRoles":["USER"],
  "insRoles":   ["STUDENT","BbMobile"],
  "landingPage":"ActivityStream",
  "avatar": { "permanentUrl": "https://ultra.edu.kuleuven.cloud/avatar/user/_544865_1?ts=..." },
  "permissions": { ... },
  "pronouns": "he/him/his",
  ...
}
```

### 3.3 Course memberships (all enrollments)

```
GET /learn/api/v1/users/<userPk>/memberships
    ?expand=course.effectiveAvailability,course.permissions,courseRole
    &includeCount=true
    &limit=10000
```

Returns the user's enrollments from Blackboard's perspective. Use this
**instead of** the portal's `/enrollments` when you're already in the
Ultra context — it's richer (includes course PKs, permissions, availability).

### 3.4 Course detail

```
GET /learn/api/v1/courses/<coursePk>
GET /learn/api/v1/courses/<coursePk>?expand=instructorsMembership,instructorsMembership.courseRole,effectiveAvailability,isChild
```

```json
{
  "id":           "_157246_1",
  "courseId":     "ULTRA-C-26738544-K-2526",
  "displayId":    "ULTRA-C-26738544-K-2526",
  "displayName":  "Basic Principles of Sustainable and Responsible Economy and Business",
  "name":         "Basic Principles of Sustainable and Responsible Economy and Business",
  "description":  "Shared Toledo community for ...",
  "ultraStatus":  "ULTRA",
  "courseViewOption": "CHOOSE_ULTRA",
  "isAvailable": true,
  "isOrganization": true,
  "serviceLevelType": "COMMUNITY",
  "durationType":    "CONTINUOUS",
  "enrollmentType":  "INSTRUCTOR_LED",
  "paceType":        "INSTRUCTOR_LED",
  "locale":          "en_GB",
  "isLocaleEnforced": true,
  "externalAccessUrl": "https://ultra.edu.kuleuven.cloud/ultra/courses/_157246_1/outline",
  "foundationsId":   "e9d942b8-5ce9-11f0-95b5-0f4a13ec4b12",
  "permissions": { ... },
  "modifiedDate": "2025-10-08T04:22:18.657Z"
}
```

### 3.5 Course content tree

Content is **recursive**. Each item has a `parentId` chain rooted at
`ROOT`.

```
GET /learn/api/v1/courses/<coursePk>/contents/ROOT
GET /learn/api/v1/courses/<coursePk>/contents/ROOT/children
    ?@view=Summary
    &expand=assignedGroups,selfEnrollmentGroups.group,gradebookCategory
    &includeInActivityTracking=true
    &limit=10
```

```json
{
  "results": [
    {
      "id":             "_10550931_1",
      "parentId":       "_10495253_1",
      "title":          "Session 1: Introduction",
      "courseId":       "_157246_1",
      "contentHandler": "resource/x-bb-folder",
      "contentDetail":  { "resource/x-bb-folder": { "isBbPage": false, "isFolder": true } },
      "renderType":     "REG",
      "visibility":     "VISIBLE",
      "state":          "Started",
      "stateCompletion": { "total": 4, "completed": 0, "started": 4 },
      "position":       0,
      "modifiedDate":   1758372243546,
      "iconUrl":        "/images/ci/sets/set12/folder_on.svg",
      "launchInNewWindow": true,
      "body":           { "rawText": "", "displayText": "", "webLocation": "...", "fileLocation": "..." },
      "permissions":    { ... }
    }
  ],
  "paging": { "limit": 10, "count": 6, "offset": 0, "previousPage": "", "nextPage": "" }
}
```

To walk the full tree: start with `parentId = ROOT`, recurse on each
child's `id` (`/contents/<id>/children`) until a leaf is hit. Leaves have
specific `contentHandler` values:

| `contentHandler` | Meaning |
|---|---|
| `resource/x-bb-folder` | Folder (recurse into children) — but **see §3.5.1** for the Ultra Document gotcha |
| `resource/x-bb-lesson` | Lesson container |
| `resource/x-bb-document` | Text/HTML document — `body.rawText` is the content |
| `resource/x-bb-file` | Uploaded file (link via `attachment`) |
| `resource/x-bb-asmt-test-link` | Test/quiz |
| `resource/x-bb-assignment` | Assignment |
| `resource/x-bb-blti-link` | External LTI tool |

(Not all observed in the sampled course; list reflects Blackboard's
generic types.)

### 3.5.1 Ultra Documents and embedded media (the BB Page pattern)

**Gotcha:** when a content item has `contentHandler: resource/x-bb-folder`
**and** `contentDetail."resource/x-bb-folder".isBbPage: true`, it is **not
really a folder** — it's an **Ultra Document** (the "BB Page" type the UI
calls "Document"). It always has exactly one child:

```
parent (resource/x-bb-folder, isBbPage:true)   "Systems Thinking: Video Recording"
   └─ child (resource/x-bb-document)            title="ultraDocumentBody"
          └─ body.rawText                       the actual HTML payload
```

The child's `title` is always the sentinel `"ultraDocumentBody"`. Detect a
BB Page like this:

```python
is_ultra_document = (
    item["contentHandler"] == "resource/x-bb-folder"
    and item.get("contentDetail", {}).get("resource/x-bb-folder", {}).get("isBbPage")
)
```

When walking the tree, treat BB Pages as leaves — descend into their one
child to get the body, but don't recurse further.

#### Embedded LTI media (Kaltura, etc.)

The document's `body.rawText` is **Blackboard's rich text dialect**, not
plain HTML. Media is embedded as `<a data-bbtype="embedded-app">` tags
whose `data-bbfile` attribute is **a JSON object encoded as HTML
attribute** (double quotes escaped as `&quot;`).

Real example from a Kaltura lecture recording:

```html
<a data-bbtype="embedded-app" data-bbfile='{
  "linkType":      "resource/x-bb-blti-link",
  "linkRefId":     "_20_1",
  "url":           "https://kaltura-kaf.edu.kuleuven.cloud/browseandembed/index/media/entryid/1_hbdhta00/showDescription/false/showTitle/false/showTags/false/showDuration/false/showOwner/false/showUploadDate/false/playerSize/960x540/playerSkin/55962282/",
  "launchInNewWindow": false,
  "deploymentId":  "a4008a3e-c531-4243-a788-9ff142bf3707",
  "linkRefUuid":   "ce2953bf-9266-4fe2-8d2c-f73264d2b204",
  "height": 540, "width": 960,
  "bbtype":        "embedded-app",
  "title":         "ZI Aula 02.21 2025-11-12 11:10"
}'>undefined</a>
```

Field reference (LTI embed):

| Field | Meaning |
|---|---|
| `linkType` | `resource/x-bb-blti-link` for LTI tool launches |
| `linkRefId` | LTI placement PK in this Blackboard tenant (`_20_1` = the Kaltura placement) |
| `linkRefUuid` | Stable UUID for the embed instance |
| `url` | The LTI tool's target URL — contains the **tool-native asset ID** as a path segment |
| `deploymentId` | LTI 1.3 `deployment_id` claim for the launch |
| `title` | Original asset title from the source system |

#### Extracting the Kaltura entry ID

The `url` path encodes the Kaltura entry ID as `entryid/<id>`. Quick regex:

```python
import re, json, html

def extract_embeds(raw_text: str) -> list[dict]:
    """Pull every embedded-app JSON out of an Ultra Document body."""
    embeds = []
    for match in re.finditer(r'data-bbfile="([^"]+)"', raw_text):
        unescaped = html.unescape(match.group(1))
        embeds.append(json.loads(unescaped))
    return embeds

def kaltura_entry_id(embed: dict) -> str | None:
    match = re.search(r"/entryid/([^/]+)/", embed.get("url", ""))
    return match.group(1) if match else None
```

For the example above: `kaltura_entry_id(...)` → `"1_hbdhta00"`.

#### Fetching the actual video from Kaltura

Two layers further out, in a separate system (`kaltura.com` /
`kaltura-kaf.edu.kuleuven.cloud`):

1. **Obtain a Kaltura session token (`ks`).** The browser does this via
   an LTI 1.3 OIDC launch: GET
   `https://kaltura-kaf.edu.kuleuven.cloud/hosted/index/oidc-init?iss=https://blackboard.com&login_hint=...&target_link_uri=...&lti_message_hint=<base64-JSON>&client_id=e9e0c690-3c98-4cf7-8c54-b03f8360ef7f&lti_deployment_id=<from-embed>&...`
   — Blackboard signs a JWT, Kaltura verifies it and issues a session.
2. **Resolve the entry to a playback manifest.** With the `ks`, call:
   ```
   POST https://www.kaltura.com/api_v3/service/baseEntry/action/get
        ?entryId=1_hbdhta00&ks=<token>&format=1
   ```
   Returns the entry metadata, including flavor IDs. The `cdnapisec.kaltura.com`
   and `cfvod.kaltura.com` URLs are signed.

The KU Leuven Kaltura partner ID is **`2375821`** (visible in the analytics
calls). For **public** entries you can replace step 1 with an anonymous
widget session:

```
POST https://www.kaltura.com/api_v3/service/session/action/startWidgetSession
     {widgetId: "_2375821"}
```

Lecture recordings are usually restricted to enrolled users, so the
anonymous widget session will not work for them — you'll need the LTI-issued
`ks`. The full LTI 1.3 OIDC replay from a non-browser context is a separate
problem (you need access to a tool-side signing key, which only Blackboard
has) — practically, the simplest path is to perform the OIDC dance in a
headless browser and capture the resulting Kaltura cookies.

#### Non-Kaltura embeds

The same `data-bbfile` pattern is used for other LTI tools. The `url` field
points to the tool's deep-link URL; the path encodes a tool-specific asset
identifier:

| Tool | Hostname | Asset path |
|---|---|---|
| Kaltura | `kaltura-kaf.edu.kuleuven.cloud` | `…/entryid/<entry_id>/…` |
| Generic LTI | varies | tool-specific |

### 3.5.2 Downloading files (`resource/x-bb-file`)

The most common leaf type. Lecture slides, reading-list PDFs, problem
sheets — all served from Blackboard's underlying Xythos file storage,
through three layers of redirects. The good news: a single GET against the
URL Blackboard hands you in the content metadata, with the Ultra session
cookie attached, follows the chain end-to-end.

Content item shape:

```json
{
  "id":             "_11282568_1",
  "parentId":       "_10550935_1",
  "title":          "Review Questions ",
  "contentHandler": "resource/x-bb-file",
  "contentDetail": {
    "resource/x-bb-file": {
      "file": {
        "fileName":              "Review Questions Inequality.docx",
        "mimeType":              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "fileSize":              562811,
        "isMedia":               false,
        "forceDownload":         false,
        "xid":                   "xid-67666194_1",
        "existingFileReference": "_5892182_1",
        "permanentUrl": "/bbcswebdav/pid-11282568-dt-content-rid-67666194_1/xid-67666194_1",
        "viewerUrl":    "/bbcswebdav/pid-11282568-dt-content-rid-67666194_1/xid-67666194_1?locale=en_GB&isInlineRender=true&xythos-download=true&render=inline"
      },
      "fileAssociationMode": "EMBED"
    }
  }
}
```

Field reference:

| Field | Meaning |
|---|---|
| `permanentUrl` | Server-relative path. Prepend `https://ultra.edu.kuleuven.cloud` and GET — that's all. |
| `viewerUrl` | Same path with viewer query params; serves with `Content-Disposition: inline` to render in the browser. |
| `fileName` | Original filename as uploaded. |
| `mimeType` | Real MIME type of the bytes (not the redirect chain). |
| `fileSize` | Bytes. |
| `forceDownload` | `true` → SP returns `attachment` disposition; `false` → `inline`. |
| `isMedia` | `true` for video/audio — may resolve differently in the Ultra UI. |
| `xid`, `existingFileReference` | Xythos file ID and Blackboard FK — already baked into `permanentUrl`. |
| `fileAssociationMode` | `EMBED` (file is the content) vs `ATTACH` (file is attached to a document). |

#### The redirect chain (informational)

Following `permanentUrl` produces four sequential requests:

```
GET https://ultra.edu.kuleuven.cloud/bbcswebdav/pid-<pid>-dt-content-rid-<rid>/xid-<xid>
   → 302 (uses your Blackboard session cookie to mint a one-time token)
GET https://alt-<tenant>.blackboard.com/bbcswebdav/pid-<pid>-dt-content-rid-<rid>/xid-<xid>
        ?one_hash=<hex>&f_hash=<hex>
   → 302 (resolves to the canonical org-rooted path)
GET https://alt-<tenant>.blackboard.com/bbcswebdav/.../orgs/<batchUid>/READ_ONLY/content/<folderPk>/<fileName>
        ?one_hash=<hex>&f_hash=<hex>
   → 302 (issues an AWS-signed CDN URL)
GET https://learn-<region>-prod-fleet01-xythos.content.blackboardcdn.com/<tenant>/<numericId>
        ?X-Blackboard-Signature=...&X-Amz-Signature=...&X-Amz-Expires=21600&...
   → 200  <file bytes>
```

The final URL is **AWS S3 presigned**, valid for 6 hours
(`X-Amz-Expires=21600`). It is **not portable** across users — the bucket
and signature are bound to the requesting Ultra session.

Don't try to construct the final CDN URL yourself; just GET the
`permanentUrl` and let your HTTP client follow the 302s.

#### Programmatic download

```python
import re
import httpx

PORTAL_BASE = "https://ultra.edu.kuleuven.cloud"

def is_file(item: dict) -> bool:
    return item["contentHandler"] == "resource/x-bb-file"

def download_url(item: dict) -> str:
    return PORTAL_BASE + item["contentDetail"]["resource/x-bb-file"]["file"]["permanentUrl"]

def download_file(ultra_client: httpx.Client, item: dict, dest_dir: str) -> str:
    file_meta = item["contentDetail"]["resource/x-bb-file"]["file"]
    target_filename = file_meta["fileName"]
    target_path = f"{dest_dir}/{target_filename}"
    with ultra_client.stream("GET", download_url(item)) as response:
        response.raise_for_status()
        with open(target_path, "wb") as output:
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                output.write(chunk)
    return target_path
```

`ultra_client` must already hold the Blackboard session cookie (i.e. you
launched into Ultra at least once via the LTI redirector). `httpx.Client(
follow_redirects=True)` handles the entire chain automatically.

#### Bulk-downloading a course

Combine the content-tree walker (§6.2) with the file detector:

```python
for item in walk(course_pk):
    if is_file(item):
        download_file(ultra_client, item, dest_dir="downloads/")
```

#### Attachments inside Documents

A `resource/x-bb-document` can also carry attached files. When the
document is rendered, attachments appear under
`contentDetail."resource/x-bb-document".attachments[]` with the same
shape (`fileName`, `permanentUrl`, etc.) — the download mechanism is
identical. None were observed in the sampled course; verify against your
own data if relying on this.

### 3.6 Per-course supporting endpoints

| Endpoint | Returns |
|---|---|
| `/courses/<id>/schedule?sort=location(desc)` | Calendar items scoped to this course |
| `/courses/<id>/tools` | Enabled tools (announcements, groups, messages, etc.) |
| `/courses/<id>/tools/<name>` | Per-tool config (`announcements`, `groups`, `messages`, `discussion_board`, `bb-attendance`, `bb-achievements-ultra`, `bb-course-automations`) |
| `/courses/<id>/entitlements` | Bitmask of what this user can do |
| `/courses/<id>/memberships` | List of all members in the course |
| `/courses/<id>/memberships?roleBucket=TEACHING&membershipAvailable=true` | Just instructors/TAs |
| `/courses/<id>/memberships/counts?membershipAvailable=true` | Member counts by role |
| `/courses/<id>/users/<userPk>?expand=courseRole` | This user's membership in the course |
| `/courses/<id>/announcements?limit=N&offset=N` | Announcement list — body in `body.rawText` (BB rich-text dialect), `readStatus.isRead`, `creatorUserId` is a BB user PK, `position` orders newest-first |
| `/courses/<id>/announcements/counts` | `{ "postedCount": N, "unreadCount": N }` |
| `/courses/<id>/gradebook/unreadGradesCount` | Pending grade notifications |
| `/courses/<id>/conversations/counts` | Unread messages |
| `/courses/<id>/conversations/options` | Conversation feature config |
| `/courses/<id>/discussionboards/count` | Discussion board count |
| `/courses/<id>/contents/indicators` | New/changed-content badges |
| `/courses/<id>/progress/configuration` | Progress-tracking settings |
| `/courses/<id>/collabultra/sessions?expand=sessionInstances&startTime=<iso>` | Collaborate Ultra video sessions |
| `/courses/<id>/preferences/<key>` | Per-course preferences (404 if unset) |

### 3.6.1 Gradebook

The Ultra gradebook is column-oriented: every gradable thing in a course (attendance, an assignment, a test, a discussion, the final-grade calculator) is a **column**, grouped into one of a handful of system-defined **categories** (`Assignment`, `Test`, `Survey`, `Discussion`, `Journal`, `Exam`, `Attendance`, …). Each student has one **grade** record per column. Columns reference a **grading schema** (Letter, Score, …) that translates a numeric score into a displayed symbol.

| Endpoint | Returns |
|---|---|
| `/courses/<id>/gradebook/columns?limit=1000` | All columns. Each carries `id`, `effectiveColumnName`, `possible` (max points), `gradebookCategoryId`, `gradingSchemaId`, `aggregationModel` (`LAST`/`HIGHEST`/`LOWEST`/`AVERAGE`/`FIRST`), `calculationType` (`NON_CALCULATED`/`CALCULATED`), `dueDate`, `enforceDueDate`, `gradesReleased`, `visible`, `visibleInBook`, `position`. |
| `/courses/<id>/gradebook/columns/<columnId>?expand=associatedRubrics,gradebookCategory` | One column with rubrics and category expanded. |
| `/courses/<id>/gradebook/categories` | Category dictionary (10 entries: the system-defined types plus user-defined). Each has `id`, `title`, `localizableTitle.{languageKey,bundle}`, `isUserDefined`. |
| `/courses/<id>/gradebook/schemas` | All grading schemas in the course. Each has `id`, `localizableTitle`, `scaleType` (`TABULAR`/`SCORE`/`COMPLETE_INCOMPLETE`/`PERCENTAGE`), and `symbols` (the lookup table mapping `symbol` → `absoluteTranslation`). |
| `/courses/<id>/gradebook/schemas/<schemaId>` | One schema. |
| `/courses/<id>/gradebook/grades?userId=<userPk>&expand=column,submissionStatus,lastAttempt,hasAttemptOrGradeFeedback,attemptsLeft&includeNoGradeItems=true` | Per-user grade records, one per column. The `column` expand inlines the column object so a single round-trip gives a full student view. Each result carries `columnId`, `displayGrade` (when scored), `lastAttempt`, `submissionStatus.status` (`UNOPENED`/`IN_PROGRESS`/`READY_TO_POST`/…), `hasAttemptOrGradeFeedback`, `attemptsLeft`. |
| `/courses/<id>/gradebook/columns/<columnId>/attempts` | All attempts for a column (instructor-side; students get `{ "lookup": {} }` for their own columns unless they have entitlements). |
| `/courses/<id>/gradebook/settings` | Mastery/outcomes visibility config (`masteryGradebookVisibility`, `outcomesVisibility`). |
| `/courses/<id>/gradebook/unreadGradesCount` | `{ "count": N }` of grades the student hasn't viewed yet — the badge on the Gradebook tab. |
| `/courses/<id>/gradebook/memberships/<membershipId>/exceptions?offset=0&limit=1000` | Per-membership grade exceptions (extensions, accommodations). |
| `/learn/api/v1/gradebook/utilities/gradeScales` | Tenant-wide schema presets (not course-specific). |

The `finalGrade` virtual column id is documented in the Bb v3 REST reference but `/columns/finalGrade?expand=…` returns 404 on this tenant — the final-grade column shows up in the normal `columns` listing if the course has one (`calculationType: "CALCULATED"`).

### 3.6.2 Discussions

A course's discussion forums sit inside the content tree under the virtual `INTERACTIVE` parent. Listing that parent returns content items with `contentHandler: "resource/x-bb-forumlink"`; each item's `contentDetail."resource/x-bb-forumlink"` carries `id` (forumId — the API key) and `conferenceId` (discussion-board id). The API path always uses the literal `default` for the discussion-board segment; Ultra resolves it to the course's actual board.

| Endpoint | Returns |
|---|---|
| `/courses/<id>/contents/INTERACTIVE/children?@view=Summary&limit=N` | Discussion-forum content items. Filter results to `contentHandler == "resource/x-bb-forumlink"`. |
| `/courses/<id>/discussionboards/default/forums/<forumId>` | Forum metadata: `title`, `startDate`/`endDate`, `properties` (`allowAnonymousPosts`, `allowAttachment`, `allowMembersToCreateNewThreads`, `enforceModeration`, `forumGroupPersistenceMode`, …), `permissions`, `position`. |
| `/courses/<id>/discussionboards/default/forums/<forumId>/counts` | `{ commentCount, totalCount, readCount, draftCount, replyCount }`. |
| `/courses/<id>/discussionboards/default/forums/<forumId>/messages?limit=N` | Top-level messages (root threads). Each carries `body.{rawText,displayText}` (BB rich-text dialect), `lifecycle` (`PUBLISHED`/`DRAFT`/…), `postDate`, `editDate`, `givenName`/`familyName`/`postedName`, `messageStatus.{totalCount,readCount,numberOfChildren,isRead,…}`, `gradedColumn` (when forum is graded). |
| `/courses/<id>/discussionboards/default/forums/<forumId>/messages/<messageId>/replies?limit=N&offset=N&sort=draft(desc),postDate(desc)` | Paginated replies. `paging.nextPage` is a relative URL to the next slice. |
| `/courses/<id>/discussionboards/default/forums/<forumId>/messages/<messageId>/states` | Per-user read state for one message. |
| `/courses/<id>/discussionboards/default/forums/<forumId>/usercounts?limit=N&offset=N&expand=includeParticipationCount` | Per-user participation counts with full user `data` blob (avatar URL, email, q-uid, foundationsId, pronouns, …). |
| `/courses/<id>/discussionboards/default/forums/<forumId>/anonymous` | Anonymous-posting config. |
| `/courses/<id>/discussionboards/settings` | Whether students can create new discussion items in this course. |
| `/courses/<id>/discussionboards/count` | `{ unreadCount }` — the badge on the Discussions tab. |
| `/courses/<id>/tools/discussion_board` | Tool-level config (enabled/disabled, position). |

The Ultra SPA URL `/ultra/courses/<courseId>/engagement/discussion/<contentId>` uses the **content** id, not the forumId. Map between them via the `/contents/INTERACTIVE/children` listing: `id` is the content id and `contentDetail.resource/x-bb-forumlink.id` is the forumId.

### 3.7 Cross-course endpoints

| Endpoint | Returns |
|---|---|
| `POST /learn/api/v1/streams/ultra` | The activity stream (the "Stream" tab in Ultra) — POST body contains stream filter |
| `/learn/api/v1/terms` | All academic terms |
| `/learn/api/v1/themes/_1_1/settings` | Tenant theming |
| `/learn/api/v1/featureFlags/<flag-name>` | Per-flag boolean |
| `/learn/api/v1/utilities/entitlements` | Global entitlements |
| `/learn/api/v1/utilities/timeUntilBbSessionInactive?forceLogout=false` | Remaining session seconds |
| `/learn/api/v1/foundationsToken/context` | Cross-region capabilities & expiry |
| `/learn/api/v1/gradebook/utilities/gradeScales` | Grade scale presets |
| `/learn/api/v1/ally/config` | Ally accessibility tool config |
| `PUT /learn/api/v1/utilities/batch` | Batch op runner |
| `/learn/api/public/v1/lti/placements?type=UltraUI` | LTI tool placements |
| `/learn/api/public/v1/uploads/settings` | File upload limits |
| `/learn/api/public/v1/administration/notifications/settings` | Notification preferences |
| `/learn/api/public/v1/oauth2/tokeninfo?access_token=<token>` | Inspect an OAuth2 access token |

### 3.8 `foundationsToken/context`

Interesting one — returns the user's cross-region routing info for
Anthology Foundations services (the underlying capability platform):

```json
{
  "tenantId":  "f07960c1-0fd0-4e1a-abb7-e46db8c0ca2b",
  "personId":  "e7f9cf49-35bb-11ee-b6a4-e5a82809bdfd",
  "expiresAt": 1779153114303,
  "capabilities": [
    { "capability": "eu",           "region": "foundations",       "stage": "prod" },
    { "capability": "sso",          "region": "eu",                "stage": "prod" },
    { "capability": "authz",        "region": "eu",                "stage": "prod" },
    { "capability": "notifications","region": "notif-websockets-eu-central-1.prod", "stage": "prod" },
    { "capability": "video-studio", "region": "eu",                "stage": "prod" },
    { "capability": "ai-gateway",   "region": "eu",                "stage": "prod" },
    { "capability": "attendance",   "region": "eu.prod",           "stage": "prod" }
  ]
}
```

`personId` is the same UUID used for `foundationsId` in `/users/me`. Useful
for cross-referencing identity across Blackboard and AnthologyAI services.

---

## 4. KURT reservation API (`kurt3.ghum.kuleuven.be/api`)

KURT3 is the reservation system for KU Leuven study spaces, group rooms, and AV/Learning Lab equipment. The frontend is an Angular SPA at `kurt3.ghum.kuleuven.be`; the backend is an ASP.NET service at `/api`. Auth is Shibboleth, but the SP uses the SAML Redirect binding (not POST like Toledo or Ultra), so bootstrap is `GET /login` → `302` to `idp.kuleuven.be/idp/profile/SAML2/Redirect/SSO?SAMLRequest=...`. After the ACS round-trip sets `_shibsession_*` on `kurt3.ghum.kuleuven.be`, the redirect target (`/login`) returns `404` — the SP cookie is the real success signal, not the HTTP status of the final hop.

All endpoints return JSON. None require a CSRF token; the Shibboleth cookie is the only credential.

### 4.1 Identity and metadata

```
GET /api/information
  → { uid, email, commonName, firstName, lastName, apiVersion, webAppVersion, frontEnd }
GET /api/account
  → identity fields above plus
    { quota: [{ resourceType, resourceTypeId, usageDay, usageWeek,
                maxUsageDay, maxUsageWeek }, ...] }
    # max* of -1 means unlimited
GET /api/news
  → { id, title, message }            # site-wide banner, Markdown body
GET /api/news?locationId=ID
  → location-specific banner
GET /api/news?locationId=ID&resourceTypeId=ID
  → location+type-specific banner
GET /api/preferences/<int>
  → user preference slot
```

### 4.2 Locations and resources

```
GET /api/tiles
  → [{ id, tileGroup, name, thumbnailUrl, locations: [{ id, unit, city, thumbnailUrl }] }, ...]
```

Tiles group locations by city or special category (Learning Lab). `locations[].id` is the numeric location key used everywhere else.

```
GET /api/locations/<id>
  → { id, unit, address, fullImageUrl, navigationUrl, openingHoursToday,
      closedToday, zones: [{ id, name, floorPlanId, resourceTypeIds }] }
GET /api/resourcetypes?locationId=<id>
  → [{ id, name, icon, sortOrder }, ...]
GET /api/tags?locationId=<id>&resourceTypeId=<id>
  → tag dictionary used in availability filters
GET /api/locations?peerLocationId=<id>&resourceTypeId=<id>
  → peer locations that offer the same resource type
GET /api/parameters?locationId=<id>&resourceTypeId=<id>
  → booking constraints (min/max duration, allowed times, ...)
GET /api/occupancies/<locationId>
  → { locationId, unit, capacity, occupancy, captureTime, closed }
GET /api/resources/<resourceId>?withDetails=true
  → { id, name, locationId, unit, resourceTypeId, resourceTypeName, icon,
      minParticipants, maxParticipants, isMultiDayReservable,
      reservationRequestRequired, subjectIsRequired, subjectLabel,
      purposeIsRequired, purposeLabel, legalTextCheckboxIsRequired,
      legalText, conditionsOfUseEnUrl, conditionsOfUseNlUrl }
```

### 4.3 Availability search

```
GET /api/resourcetypeavailabilities
    ?locationId=&zoneId=&resourceTypeId=
    &pageNumber=0
    &startDate=YYYY-MM-DD&startTime=HH:MM
    &endDate=YYYY-MM-DD&endTime=HH:MM
    &participantCount=&tagIds=
    &exactMatch=true&onlyFavorites=false
    &resourceNameInfix=
    &version=2.0
  → { availabilities: [Availability], message }
```

`zoneId=-1` means any zone. `tagIds` is a comma-separated string of tag ids; empty means any. `exactMatch=false` widens the search to overlapping windows. Empty `startTime`/`endTime` returns every resource regardless of free time.

Each `Availability` carries the resource's identity, the resolved window, capacity and duration constraints, the resource tags, and `slotAllocation` — a 24-character string covering hours 0–23 where `A` is free, `B` is booked, `C` is closed, and `startSlotAllocation` is the index of the search window's start. The frontend renders the per-row strip from this.

### 4.4 Reservations

```
GET /api/reservations
  → [Reservation, ...]   # all current and future reservations for the user
GET /api/reservations?onlyToday=true
  → only reservations whose window intersects today
GET /api/reservations/<id>
  → Reservation with editable-window metadata (possibleStartDates, possibleEndDates)
POST /api/reservations/
  body: { subject, purpose, resourceId, resourceName, startDate, startTime,
          endDate, endTime, participants: [{ uid, email }, ...],
          isMultiDayReservable }
  → "Reservation created successfully." or detail object
  Note: `resourceName` must echo the resource's `name`. Omitting it (or any
  other listed field) yields a bare 400 with no body. Other fields from the
  Reservation shape — `id`, `ownerUserNumber`, `status`, etc. — are ignored.
PUT /api/reservations/
  body: full Reservation object (same shape as GET /api/reservations/<id>)
  → "Your changes have been saved"
DELETE /api/reservations/<id>
  → 200 OK
```

A `Reservation` looks like:

```json
{
  "id": 3963083203,
  "ownerUserNumber": "r0123456",
  "subject": "Study session",
  "purpose": "",
  "resourceId": 301108,
  "resourceName": "Example - Study Seat 000 Placeholder",
  "startDate": "2026-05-25",
  "startTime": "09:00",
  "endDate": "2026-05-25",
  "endTime": "12:00",
  "participants": [{ "uid": "r0123456", "email": "first.last@student.kuleuven.be" }],
  "minDurationMinutes": 60,
  "maxDurationMinutes": 960,
  "isMultiDayReservable": false,
  "isEditable": true,
  "status": "Booked",
  "withCheckIn": false
}
```

The frontend always sends `participants` containing the current user; multi-participant resources accept additional entries with the same shape. Resource types with `reservationRequestRequired: true` (staff approval flow) take a different path that was not explored.

### 4.5 Favourites

```
GET /api/favorites?forHomePage=true
  → [{ id, resourceId, locationId, resourceTypeId, resourceName, icon }, ...]
```

---

## 5. The LTI launch (Portal → Ultra)

Clicking a course from the portal goes through one intermediate hop:

```
1. GET https://icts-p-toledo-journey.cloud.icts.kuleuven.be/learningUnits/ultraLink?batchUid=ULTRA-...
   → 302 Location: https://ultra.edu.kuleuven.cloud/ultra/courses/_NNNN_1/outline

2. GET https://ultra.edu.kuleuven.cloud/ultra/courses/_NNNN_1/outline
   → 200 (the Ultra SPA boots, makes all the /learn/api/v1/* calls above)
```

The journey service knows how to resolve `batchUid → coursePk`. It also
handles new-session bootstrap if the Ultra cookie is missing (full LTI
1.3 launch with `id_token` and signed JWT — not captured here because
the Ultra session was already alive).

**Implication for scripting:** you only need to call the `ultraLink` URL
once per course to learn its `_NNNN_1` PK. Cache the mapping; future
calls can hit `/learn/api/v1/courses/_NNNN_1` directly.

---

## 6. Relationships between objects

```
Portal Enrollment                Blackboard Course
─────────────────                ──────────────────
id            (uuid)             id              (_NNNN_1, internal PK)
learningUnitId ─────[batchUid]──> courseId       (mirrors batchUid)
title                            displayName
                                 foundationsId   (cross-region identity)
                                 ultraStatus     (CLASSIC | ULTRA)

Portal Notification              Blackboard Content
─────────────────────            ────────────────────
id            "ultra~_NNNN_1"    id              (_NNNN_1)
sourceId      (batchUid)     ─── courseId        (_NNNN_1) via the launch
url           ?contentId=_X_1 ──> contents/_X_1

Portal User                      Blackboard User
─────────────                    ───────────────────
(SAML uid: r0123456)             id              (_NNNN_1)
                                 userName        (q1686864 — q-uid)
                                 studentId       (00971578)
                                 uuid
                                 foundationsId   (matches personId)

Portal Instructor                Blackboard Membership
─────────────────                ─────────────────────
id (q-uid)               ──────> userName (q-uid)
                                 courseId
                                 courseRole
```

The **q-uid** (`q1686864`) is the join key across portal-issued and
Blackboard-issued identity records.

---

## 7. Practical recipes

### 6.1 "What's on my schedule next week?"

Combine portal `/upcoming` with course `/schedule`:

```python
upcoming  = portal_client.get("/portal/api/upcoming").json()
for event in upcoming:
    course_pk = batchuid_to_pk(event["source"]["learningUnitId"])
    # ... cross-reference with /learn/api/v1/courses/<course_pk>/schedule
```

### 6.2 "Walk the full content tree of a course"

```python
def walk(course_pk: str, parent_id: str = "ROOT"):
    response = ultra_client.get(
        f"/learn/api/v1/courses/{course_pk}/contents/{parent_id}/children",
        params={"@view": "Summary", "limit": 1000},
    ).json()
    for item in response["results"]:
        yield item
        # Real folders recurse; BB Pages (isBbPage:true) don't — see §3.5.1
        is_bb_page = item.get("contentDetail", {}) \
            .get("resource/x-bb-folder", {}) \
            .get("isBbPage", False)
        if item["contentHandler"] == "resource/x-bb-folder" and not is_bb_page:
            yield from walk(course_pk, item["id"])
```

### 6.3 "Mark all new notifications as seen"

```python
events = portal_client.get("/portal/api/events").json()
unseen = [
    {"id": item["id"], "type": item["type"], "subType": item["subType"], "seen": True}
    for item in events
    if not item["seen"]
]
portal_client.patch("/portal/api/batch/events", json=unseen)
```

### 6.4 "Get all instructors across all enrollments"

```python
enrollments = portal_client.get("/portal/api/enrollments").json()
instructors_by_uid = {}
for enrollment in enrollments:
    detail = portal_client.get(
        f"/portal/api/enrollments/{enrollment['learningUnitId']}/en"
    ).json()
    for instructor in detail["instructors"]:
        instructors_by_uid[instructor["id"]] = instructor
```

---

## 8. Gotchas

- **Two cookie jars.** `_shibsession_*` on `toledo.kuleuven.be` gets you the
  portal API. Blackboard's own session cookie on `ultra.edu.kuleuven.cloud`
  gets you the Ultra API. They are independent — visiting `/portal/api/*`
  does **not** establish the Ultra session, and vice versa. Trigger the
  LTI launch (`ultraLink?batchUid=...`) once to bootstrap Ultra.
- **`events` and `activities` overlap.** They return the same shape and
  largely the same data in practice. The SPA hits both during page boot;
  prefer `/activities` for the canonical feed.
- **Timestamps are mostly milliseconds since epoch.** Some Blackboard
  endpoints return ISO 8601 strings instead (`modifiedDate`, `expiresAt`
  in `foundationsToken/context`). Check field-by-field.
- **`available: false` is silent.** A course that's hidden by the
  instructor is still in `/portal/api/enrollments` but the LTI launch may
  return an error or empty content tree.
- **`/learn/api/v1/users/me/preferences/<key>` returns 404 for unset
  preferences.** Treat 404 as "default value", not an error.
- **The Ultra session has its own inactivity timer**, distinct from the
  Toledo SP session — query it at
  `/learn/api/v1/utilities/timeUntilBbSessionInactive?forceLogout=false`.
- **`/portal/api/monitor/links/<id>` is fire-and-forget telemetry.** Skip
  it; the API works without these.
- **Rate limiting.** Not formally observed, but the SPA self-batches all
  notification updates into one PATCH and avoids polling — implies servers
  are not built for high-frequency clients. Stay below ~1 req/sec per
  endpoint.

---

## 9. What was NOT explored

- **Assignment submission** (`POST /learn/api/v1/courses/<id>/gradebook/columns/<col>/attempts`)
- **Grades retrieval** at the leaf level
- **Discussion board threads** (would require a course with active forums)
- **Message sending** (`/conversations`)
- **Content file downloads** (`webLocation` resolution and signed URLs)
- **The journey service's own API** (`icts-p-toledo-journey.cloud.icts.kuleuven.be`) — only the launch redirect was observed
- **OAuth2 client_credentials flow** (`POST /learn/api/public/v1/oauth2/token`) — would let a backend script call Ultra without the Shibboleth dance, but requires a registered application key
- **Ad Valvas** (`icts-p-toledo-valvas.cloud.icts.kuleuven.be/student/messages`) — its own SPA, separate API surface
- **KU Loket / SAP** endpoints (timetable, ISP, progress) — separate SAP-backed system, different auth context
