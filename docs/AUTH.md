# KU Leuven Toledo authentication, reverse-engineered

This document describes the authentication flow between the **Toledo** virtual
learning environment (`toledo.kuleuven.be`) and the **KU Leuven identity
provider** (`idp.kuleuven.be`) in enough detail to reimplement a programmatic
client in any language.

Everything here was observed empirically through a real browser session — no
internal documentation was consulted. Field names, request bodies and
expiration windows are reproduced verbatim from captured traffic.

---

## 1. The players

| Component | URL | Software | Role |
|---|---|---|---|
| **Service Provider (SP)** | `https://toledo.kuleuven.be/portal/` | Shibboleth SP behind Apache | Consumes SAML assertions, issues local session cookie |
| **Identity Provider (IdP)** | `https://idp.kuleuven.be/idp/` | Shibboleth IdP (Spring WebFlow) | Authenticates the user, issues signed SAML response |
| **REST backend** | `https://toledo.kuleuven.be/portal/api/*` | Plone-based JSON API | The actual data API; gated by SP session cookie |

The Toledo portal is a Vue SPA backed by a Plone CMS (giveaway: `++plone++`
and `++webresource++` paths in static assets). After authentication, the SPA
talks to `/portal/api/*` endpoints over plain HTTP+cookies — no bearer
tokens, no CSRF tokens on GET.

---

## 2. Top-level SAML2 flow

This is a textbook **SAML2 HTTP-POST binding** with a twist: the IdP uses
Spring WebFlow and interleaves two **localStorage probe** steps that look
like real auth steps but aren't.

```
Browser                          Toledo SP                    IdP
   │                                 │                          │
   │  GET /portal/                   │                          │
   │────────────────────────────────>│                          │
   │  HTML with auto-POST form       │                          │
   │<────────────────────────────────│                          │
   │                                                            │
   │  POST /idp/.../SSO              │                          │
   │  body: SAMLRequest=<base64>,    │                          │
   │        RelayState=<opaque>      │                          │
   │───────────────────────────────────────────────────────────>│
   │                                                            │
   │  4 WebFlow states (e1s1..e1s4) — see §3                    │
   │<══════════════════════════════════════════════════════════>│
   │                                                            │
   │  HTML with auto-POST form       │                          │
   │<───────────────────────────────────────────────────────────│
   │                                                            │
   │  POST /portal/Shibboleth.sso/SAML2/POST                    │
   │  body: SAMLResponse=<signed>,   │                          │
   │        RelayState=<echoed>      │                          │
   │────────────────────────────────>│                          │
   │  302 + Set-Cookie: _shibsession_*=…                        │
   │<────────────────────────────────│                          │
   │                                                            │
   │  GET /portal/api/*  (cookie attached)                      │
   │────────────────────────────────>│                          │
   │  200 application/json           │                          │
   │<────────────────────────────────│                          │
```

---

## 3. Walking the IdP WebFlow

Every IdP request is to the same URL with a different `execution=` token in
the query string. The token is bound to the IdP `JSESSIONID` cookie; you
cannot reorder steps or skip them.

```
POST /idp/profile/SAML2/POST/SSO            # initial AuthnRequest landing
GET  /idp/profile/SAML2/POST/SSO?execution=e1s1
POST /idp/profile/SAML2/POST/SSO?execution=e1s1
GET  /idp/profile/SAML2/POST/SSO?execution=e1s2
POST /idp/profile/SAML2/POST/SSO?execution=e1s2
GET  /idp/profile/SAML2/POST/SSO?execution=e1s3
POST /idp/profile/SAML2/POST/SSO?execution=e1s3
GET  /idp/profile/SAML2/POST/SSO?execution=e1s4
POST /idp/profile/SAML2/POST/SSO?execution=e1s4
```

In practice, **trust the redirects** and don't hard-code state names — the
WebFlow handles routing for you via `Location:` headers. Detect each step by
inspecting the HTML form fields.

### 3.1 Bootstrap: extracting the SAMLRequest

```
GET https://toledo.kuleuven.be/portal/
```

Response is a small HTML page with an **auto-submitting form**:

```html
<form action="https://idp.kuleuven.be/idp/profile/SAML2/POST/SSO" method="post">
  <input name="RelayState" value="ss:mem:b502810…">
  <input name="SAMLRequest" value="PHNhbWxwOkF1dGhuU…">
</form>
```

- `SAMLRequest` is **base64-encoded XML** (`<samlp:AuthnRequest>`) containing
  `AssertionConsumerServiceURL=https://toledo.kuleuven.be/portal/Shibboleth.sso/SAML2/POST`
  and `Destination=https://idp.kuleuven.be/idp/profile/SAML2/POST/SSO`.
- `RelayState` is opaque to us; the IdP echoes it back unchanged in step 5.

Extract both fields, POST them to the form's `action` URL.

### 3.2 e1s1 — localStorage probe (storage service)

The IdP serves `IdPSessionStorageService.html`. The page **looks empty** to
a non-JS client because its JavaScript reads two values from
`localStorage` (`shib_idp_session_ss` and `shib_idp_persistent_ss`) and
auto-submits them back. A scriptable client can spoof the "no value, but
storage works" path:

**POST body:**
```
shib_idp_ls_exception.shib_idp_session_ss=
shib_idp_ls_success.shib_idp_session_ss=true
shib_idp_ls_value.shib_idp_session_ss=
shib_idp_ls_exception.shib_idp_persistent_ss=
shib_idp_ls_success.shib_idp_persistent_ss=true
shib_idp_ls_value.shib_idp_persistent_ss=
shib_idp_ls_supported=true
_eventId_proceed=
```

**Detect this step** by the presence of any input whose name starts with
`shib_idp_ls_`.

### 3.3 e1s2 — credentials

The HTML at e1s2 contains **two forms simultaneously**:

| Form id | Submit field | Purpose |
|---|---|---|
| `nextauthLoginForm` | `_eventId_UseNextauth` | Push-notification ("KU Leuven Authenticator") path |
| `pwdLoginForm` | `_eventId=proceed` (hidden) | Password path |

Both POST to the same URL (`?execution=e1s2`). The IdP routes based on
which `_eventId*` parameter is present in the body. **Pick the form that
contains `<input name="username">` and `<input name="password">`.**

**POST body (password path):**
```
username=r0123456
password=…
_eventId=proceed
rememberlogin=1    ← optional; opt in to "Remember my device"
```

`rememberlogin=1` triggers the IdP to set a long-lived device-trust cookie
(see §5).

### 3.4 e1s3 — TOTP (skipped if device is trusted)

If the user has MFA enrolled, the IdP serves a form containing
`<input name="tokencode">`. The label says "KU Leuven Authenticator" but
the actual mechanism is **TOTP (RFC 6238)** — any standards-compliant
authenticator app or pre-computed code works.

**POST body:**
```
tokencode=716173
_eventId=proceed
```

**If e1s3 is missing**, the IdP recognized a persistent device-trust cookie
from a previous `rememberlogin=1` session and skipped 2FA. The state machine
should not assume e1s3 exists — instead, detect it by the presence of
`<input name="tokencode">` in the response and only POST a code when seen.

### 3.5 e1s4 — second localStorage probe (write-back)

Same shape as e1s1 but with fewer fields — this one **writes** the new
session state back to the user's localStorage for next time.

**POST body:**
```
shib_idp_ls_exception.shib_idp_session_ss=
shib_idp_ls_success.shib_idp_session_ss=true
_eventId_proceed=
```

The response from this POST is the SAMLResponse auto-POST form.

### 3.6 Final POST to Toledo's ACS

The IdP's last response contains another auto-submit form:

```html
<form action="https://toledo.kuleuven.be/portal/Shibboleth.sso/SAML2/POST" method="post">
  <input name="RelayState" value="…echoed…">
  <input name="SAMLResponse" value="PD94bWwgdmVy…">
</form>
```

`SAMLResponse` is base64 of a signed `<saml2p:Response>` containing an
`<saml2:EncryptedAssertion>` (AES-128-CBC over an RSA-OAEP-wrapped key,
encrypted to Toledo's public key). **You do not need to decrypt it** — just
relay the form fields.

POST these to Toledo's ACS. The response is `302 Location: /portal/` with
`Set-Cookie: _shibsession_<id>=<opaque>; HttpOnly; Secure`. That cookie is
your session.

### 3.7 The KU Leuven Authenticator (n-Auth push) — the interactive 2FA branch

§3.4 covers the **TOTP** second factor (`tokencode`). Accounts enrolled in
the **KU Leuven Authenticator** smartphone app instead go through a
fundamentally different, **interactive** branch called *n-Auth*. There is no
code to type — the user approves a push on a registered device and a
WebSocket tells the browser to proceed. The two branches are mutually
exclusive per enrollment: this account never saw a `tokencode` form.

Note the binding also differs in this capture: an SP-initiated login
(`GET https://toledo.kuleuven.be/webcms/Shibboleth.sso/Login?target=…`) lands
on the **Redirect** binding (`/idp/profile/SAML2/Redirect/SSO?execution=…`),
not the POST binding of §3. The `execution=` step numbers below are from that
session and are illustrative — dispatch on form fields, not numbers.

**Method selector (e1s2).** Same page that carries the password form (§3.3)
also carries the Authenticator form:

| Form id | Submit field | Extra field | Purpose |
|---|---|---|---|
| `nextauthLoginForm` | `_eventId_UseNextauth` | `__Host-rememberDevice=true` (checkbox) | Passwordless Authenticator login |
| `pwdLoginForm` | `_eventId=proceed` | `username`, `password`, `rememberlogin=1` | Password login |

The Authenticator's "Remember my device" checkbox is `__Host-rememberDevice`,
**not** the password form's `rememberlogin` — different field, same goal.

There are two ways into the push flow:

1. **Passwordless** — POST `nextauthLoginForm` (`_eventId_UseNextauth`). The
   IdP jumps straight to a **QR-scan** screen whose challenge is served at
   `https://icts.kuleuven.be/apps/authenticator/<token>`. No username is
   collected up front.
2. **Password first, then push** — POST `pwdLoginForm` as in §3.3. If the
   account is Authenticator-secured, the next page is a **device picker**
   (below) rather than a `tokencode` form.

**Device picker.** A single form, `loginformnextauth`, with one `<button>` per
registered device (`data-account-id` + `data-device-name`) and a hidden
`_eventId_proceed`. The "Last login at: …" timestamp for each device sits in a
sibling element after its button. There is **no `csrf_token`** on this IdP's
forms — `getCSRFToken()` finds no such input, so requests omit it (just like the
password and storage POSTs of §3).

```html
<body onload="nextauthwsinit('<serverid>','<registerid>',false,'wss&#x3a;&#x2f;&#x2f;authenticator-wss.icts.kuleuven.be');">
  ...
  <form action="/idp/profile/SAML2/POST/SSO?execution=e1s3" method="post" id="loginformnextauth">
    <button data-account-id="<account-id-1>" data-device-name="<device-name-1>">…</button>
    <div><small>Last login at: <RFC 1123 timestamp></small></div>
    <button data-account-id="<account-id-2>" data-device-name="<device-name-2>">…</button>
    <div><small>Last login at: <RFC 1123 timestamp></small></div>
    <input type="hidden" name="_eventId_proceed" value="">
  </form>
```

Note the WebSocket is wired in the **picker page's own `<body onload>`** — there
is no separate "waiting page". Picking a device sends the push with a POST to the
form action:

```
nextauthAccountId=<account-id>&_eventId_PushLoginOnAccount=
```

This answers with **JSON**, not a redirect:

```json
{"url": "/idp/profile/SAML2/POST/SSO?execution=e1s4", "error": ""}
```

`url` is where the continuation form is submitted once the device approves;
`error` is non-empty if the push could not be sent (the browser then offers the
QR fallback). A sibling action, `_eventId_PushLoginOnSession` (no
`nextauthAccountId`), pushes to all registered devices and backs the generic
"Log in via KU Leuven Authenticator" button.

**The WebSocket.** `nextauthwsinit(serverid, registerid, knownstatus, host)`
opens a raw-text WebSocket to `host` —
`wss://authenticator-wss.icts.kuleuven.be`, a **separate origin** from the IdP,
so the IdP `JSESSIONID` is not needed; the `registerid`/`serverid` pair is the
correlation token. `host` is HTML-entity-encoded in the `onload` attribute
(`wss&#x3a;&#x2f;&#x2f;…`), so decode it. `knownstatus` is `false` (the browser
believes it is logged out).

| Direction | Message | Meaning |
|---|---|---|
| client → server (on open) | `REGISTER <registerid> <serverid>` | subscribe to the pending challenge |
| client → server (every 50 s) | `PING` | keepalive |
| server → client | `LOGOUT…` | current status on connect (still logged out) — **ignore** |
| server → client | `CONFIRMPROVOKE…` | push delivered to the device — informational |
| server → client | `LOGIN…` | user approved → submit `loginformnextauth` |

Because `knownstatus` is false, only a `LOGIN` message means "approved"; the
`LOGOUT` the server sends on connect is just the initial state and must be
ignored. On `LOGIN`, POST `_eventId_proceed=` to the `url` from the push JSON;
the IdP returns the SAMLResponse auto-POST form of §3.6 and the flow completes
exactly like any other login. If no push arrives, the browser UI falls back to a
QR screen at `https://icts.kuleuven.be/apps/authenticator/<token>`.

**Auth context class.** A push login reports
`Authentication Context Class: https://nextauth.com` from the introspection
endpoint (§5) — **not** the `MobileTwoFactorContract` of the TOTP path.

**Automation.** This branch is scriptable, with the caveat that it needs a
real-time approval on a physical device (there is no code to inject) plus a
WebSocket client. `src/kuleuven/nextauth.py` implements it: parse the device
list and `nextauthwsinit` args from the picker page, POST the push, open the
WebSocket and block until `LOGIN`, then POST the continuation. The CLI exposes
device choice via `--device` (a name, 1-based index, or `most-recent`); see the
README. A persisted `__Host-rememberDevice` device-trust cookie (§6.2) still
skips 2FA entirely on later runs.

---

## 4. Picking the right form on each page

Because the IdP serves both e1s2 forms together, and because skipping 2FA
makes the state numbering vary, **don't dispatch on URL — dispatch on form
fields**. The decision table:

| If the page contains a form with… | Then this step is… | And you should POST… |
|---|---|---|
| `SAMLResponse` | the final ACS landing | the form fields as-is to Toledo |
| `SAMLRequest` | the SP bootstrap | the form fields as-is to the IdP |
| `username` **and** `password` | the credentials prompt | `username`, `password`, `_eventId=proceed` (+ optional `rememberlogin=1`) |
| `tokencode` | the TOTP prompt | `tokencode`, `_eventId=proceed` |
| any name starting with `shib_idp_ls_` | a localStorage probe | the spoofed payload from §3.2 |
| button with `data-account-id` (form `loginformnextauth`) | the KU Leuven Authenticator device picker | pick a device, POST the push, wait on the WebSocket — see §3.7 |

A loop that picks the first matching rule and re-POSTs handles the full
flow with no hard-coded state names. The `loginformnextauth` row is the one
exception to "just re-POST": it is the interactive n-Auth branch (§3.7), which
sends a push and blocks on a WebSocket until the user approves on a device.

---

## 5. Cookies

Three relevant cookies emerge from a successful login:

| Cookie | Domain | HttpOnly | Lifetime | Meaning |
|---|---|---|---|---|
| `JSESSIONID` | `idp.kuleuven.be` | yes | session-only (cleared on tab close) | Binds the WebFlow `execution=…` tokens to your conversation |
| `__Host-rememberDevice` (or similar) | `idp.kuleuven.be` | yes | weeks (issued only if `rememberlogin=1` was sent) | Skips 2FA on future logins from the same client |
| `_shibsession_<id>` | `toledo.kuleuven.be` | yes | **48h absolute** (+ inactivity timeout) | The Toledo SP session — *the only cookie needed for `/portal/api/*` calls* |

The `_shibsession_*` cookie is opaque server-side — Shibboleth SP keeps the
real session state on disk and the cookie is just a lookup key.

### Session introspection

Toledo's SP exposes the standard Shibboleth introspection endpoint:

```
GET https://toledo.kuleuven.be/portal/Shibboleth.sso/Session
```

Returns a small HTML page (or JSON with `?contentType=application/json`)
showing time remaining, authentication context class, and released
attributes:

```
Session Expiration (barring inactivity): 2867 minute(s)
Authentication Context Class: urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract
uid: r0123456
affiliation: member@kuleuven.be;student@kuleuven.be
entitlement: urn:mace:kuleuven.be:entitlement:toledo
```

`Authentication Context Class = MobileTwoFactorContract` confirms the
session was 2FA-elevated via TOTP. A KU Leuven Authenticator (n-Auth push)
login instead reports `Authentication Context Class = https://nextauth.com`
(see §3.7); either value confirms a second factor was satisfied.

---

## 6. Optimizations

### 6.1 Reusing the SP session across runs

Persist the cookie jar to disk after a successful login. On the next run,
restore it and ping `/portal/api/info?language=en`:

- **200 with `Content-Type: application/json`** → session still valid, skip
  login entirely.
- **Any other response** (typically a 302 that follows to the IdP) → session
  expired, run a fresh login.

This costs zero round-trips when the session is valid and saves 8 HTTP
requests + a 2FA code per script invocation when reused.

### 6.2 `rememberlogin=1` for unattended re-auth

Sending `rememberlogin=1` with the credentials causes the IdP to set a
long-lived device-trust cookie. **You must persist your cookie jar between
runs** for this to do anything — `rememberlogin=1` without cookie
persistence is wasted work, since the device-trust cookie is discarded the
moment your process exits.

On the next login (with the cookie restored):

- The e1s1 storage probe finds an existing device trust.
- The IdP routes you **directly to e1s4** after the password POST — the
  `tokencode` form is never served.
- Your script only needs to know username + password.

The window slides on each successful re-auth, so for any user logging in at
least monthly this is effectively permanent until the cookie is cleared or
the policy revokes it.

### 6.3 Combining the two

In practice:

```
loaded cookies + valid SP session   →  zero auth requests
loaded cookies + expired SP session →  ~8 requests, no 2FA (rememberDevice)
no cookies (cold)                   →  ~8 requests + 2FA prompt
```

---

## 7. Observations & gotchas

- **Order matters.** The WebFlow `JSESSIONID` cookie locks each `execution=`
  token to a specific position. Concurrent logins from the same cookie jar
  will trample each other. Use one fresh `httpx.Client` per login.
- **Follow redirects.** The IdP uses 302s between WebFlow states; if you
  disable redirect-following, you have to chase `Location:` headers yourself
  for no benefit.
- **`User-Agent` matters minimally.** A modern Chrome UA works; an empty UA
  may trip Shibboleth's bot heuristics, but most reasonable strings pass.
- **The released `entitlement` attribute** (`urn:mace:kuleuven.be:entitlement:toledo`)
  is what authorises access to Toledo. A user without that entitlement gets a
  valid SAML assertion but a 403 from `/portal/api/*`.
- **`/portal/ltc/<hash>`** endpoints (seen in the SPA traffic) are LTI
  course-launch tokens that bounce the user into Blackboard Learn Ultra at
  `ultra.edu.kuleuven.cloud` — a separate auth context, beyond the scope of
  this document.

---

## 8. The discovered REST surface

All gated by `_shibsession_*` on `toledo.kuleuven.be`:

| Endpoint | Returns |
|---|---|
| `GET /portal/api/info?language=en` | personal info |
| `GET /portal/api/links` | quick links |
| `GET /portal/api/activities` | recent activities |
| `GET /portal/api/events` | calendar events |
| `GET /portal/api/enrollments` | enrolled courses |
| `GET /portal/api/upcoming` | upcoming deadlines |
| `GET /portal/api/emails/unread` | unread email count |
| `GET /portal/ltc/<hash>` | LTI launch into a specific course |

Plain JSON, no pagination cursors seen, no CSRF tokens required on GET.
Write endpoints have not been investigated.

---

## 9. Portability notes

The algorithm uses only:

- **HTTP/1.1** with cookies and redirect-following
- **HTML form parsing** (a single `<form>`/`<input>` scan is enough)
- **base64** of opaque blobs (you don't decode them — they're relayed)
- **No cryptography** on the client side; SAML signature verification happens
  inside Toledo
- A **WebSocket client** — only for the KU Leuven Authenticator push wait (§3.7);
  the password and TOTP paths need none

Translating to Go, Rust, Node, etc. is straightforward: any HTTP client with a
cookie jar, a tolerant HTML parser, and (for push) a WebSocket client will do.
The reference implementation lives in `src/kuleuven/` —
`shibboleth.py` walks the WebFlow and `nextauth.py` handles the push branch.
