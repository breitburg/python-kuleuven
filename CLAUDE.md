# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Conventions for working on this repo. Read before making changes.

## Commands

Requires Python >=3.13 and `uv`. CI runs only `uv run pytest -ra`; there is no linter or formatter configured.

```
uv sync                              # install deps + dev group into .venv
uv run pytest                        # full test suite
uv run pytest tests/test_kurt.py     # one file
uv run pytest -k availability        # tests matching an expression
uv run kuleuven --help               # run the CLI from source
uv run python -c '...'               # one-off Python
uv add <pkg> / uv remove <pkg>       # change dependencies — never hand-edit pyproject.toml
```

Tests use `respx` to mock `httpx`; they never hit the live KU Leuven hosts. `tests/conftest.py` holds the shared fixtures.

## Layout

The package is `kuleuven`, the umbrella for KU Leuven services that share the Shibboleth IdP.

- `src/kuleuven/session.py` — `KuleuvenSession` owns the `httpx.Client` and runs the multi-leg SAML sign-in. `sign_in()` does three independent SAML handshakes (Toledo portal, Blackboard Ultra, KURT), each a separate SP with its own cookie jar; only the first prompts for credentials/2FA, the rest reuse the IdP SSO session.
- `src/kuleuven/shibboleth.py` — shared SAML machinery: `sign_in_via_saml`, the webflow walker, `find_form`, `parse_session_summary`, `STORAGE_PROBE_PAYLOAD`, and the `AuthenticationProvider` Protocol (the second-factor strategy injected into a sign-in).
- `src/kuleuven/nextauth.py` — `NextauthDevice` and the push-approval second factor (opens a websocket to `idp.kuleuven.be` and waits for the user to approve on their phone). This is one implementation of `AuthenticationProvider`.
- `src/kuleuven/toledo.py` — `ToledoClient(session)`, every Toledo/Ultra endpoint (courses, content, files, discussions) as methods.
- `src/kuleuven/kurt.py` — `KurtClient(session)`, KURT study-space reservation endpoints, same shape.
- `src/kuleuven/exceptions.py` — the auth exception hierarchy (`AuthenticationError` and subclasses).
- `src/kuleuven/models/` — Pydantic response models, one module per service (`toledo.py`, `kurt.py`, `common.py`) re-exported from `models/__init__.py`. See model conventions below.
- `src/kuleuven/cli/` — the Typer CLI; the only place that knows about disk I/O, env, and prompting.

Adding a new KU Leuven service (KU Loket, Ad Valvas, …) is symmetric: add `src/kuleuven/<service>.py` with a `<Service>Client(session)` class, add a sign-in round-trip for its SP in `KuleuvenSession.sign_in()`, add `src/kuleuven/models/<service>.py`, and add `src/kuleuven/cli/<service>.py` mounted on `app`. No new `helpers.py` / `utils.py` — name a new module for the concern.

## Library vs CLI

The library (`kuleuven.session`, `kuleuven.toledo`, `kuleuven.kurt`, `kuleuven.shibboleth`, `kuleuven.nextauth`, `kuleuven.models`, `kuleuven.exceptions`) is pure: HTTP in, models out, no disk I/O, no environment reads, no prompting. Cookie persistence, `.env` loading, TTY detection, and JSON output all live in `kuleuven.cli`. Keep it that way when adding features. The public API surface is whatever `src/kuleuven/__init__.py` re-exports.

## CLI structure

`cli/__init__.py` builds the command tree. The `@app.callback()` constructs one `httpx.Client`, loads saved cookies into it, and stashes a `KuleuvenSession` on the Typer context (`ctx.obj`) for every command. Top-level groups: `session`, `toledo`, `kurt`, `mcp`. Toledo is course-scoped, so `content`, `files`, and `discussions` nest *under* `toledo courses` rather than sitting as peers. `session raw` is the cookie-jar escape hatch.

`cli/output.py` `emit(payload, exit_code)` is the single exit path — it prints one JSON line (serializing Pydantic models via `model_dump(mode="json")`) and raises `typer.Exit`. Always exit through `emit`, never bare `print` + `raise`.

`cli/mcp.py` exposes the CLI as an MCP server for Claude Desktop (`kuleuven mcp start|install|uninstall`) via `pycli-mcp`. It dynamically reflects the Typer app into MCP tools; the `start` handler rewrites dotted tool names to underscores (Claude Desktop's name regex) and excludes disk-writing commands (`files sync`, `files fetch`).

## CLI output contract

Every CLI command prints exactly one JSON object to stdout and exits with `0` on success, `1` on auth or session failure, `2` on missing input. Errors are JSON on stdout too, not stderr — agents need to parse one stream. Read credentials and other secrets from flags or env vars; prompt only if stdin is a TTY, otherwise emit an error JSON and exit. Never persist credentials to disk. The only thing saved is the session cookie jar, at `platformdirs.user_data_path("kuleuven") / "cookies.json"` with `0600` permissions.

## Models

Responses are Pydantic models under `kuleuven.models`, all extending `KuleuvenModel` (`models/_base.py`): `populate_by_name=True`, `extra="ignore"` for forward-compat. Python attributes are snake_case; field aliases map upstream camelCase. `ApiEchoModel` is the variant for shapes that must be echoed back verbatim — it uses `extra="allow"` and `serialize_by_alias=True` so `model_dump()` preserves the original camelCase keys. Use a typed model when the consumer reads specific fields; use `ApiEchoModel` (or a raw dict) when you only pass the payload straight through to output.

## Code style

Write no-nonsense code. No decorative docstrings or section banners. Comments only when the *why* is non-obvious (a hidden constraint, a SAML quirk, a workaround) — the existing comments in `session.py` and `mcp.py` are the model. Use full descriptive variable names — `current_response`, not `r`. Prefer early returns over `else`; if a loop needs `for/else`, factor the loop into a method that returns on success and raises after it. Do not introduce abstractions for hypothetical reuse — three similar lines is fine.

## Documentation

`README.md` documents the CLI and the Python API. `docs/AUTH.md` documents the SAML flow. `docs/DATA.md` documents the REST surface. Any change a user can observe — new or renamed commands, flags, env vars, output shape, exit codes, public Python API, exception types, storage paths — must be reflected in `README.md` in the same change. Internal refactors that do not change observable behavior do not need a README update.

Style for `README.md` and user-facing docs: structured layout. Each CLI command and public API method gets its own subsection with a consistent shape — short prose description, then synopsis, options, example, exit codes. Bullet lists and tables where the content is genuinely list-shaped (flag tables, exit-code tables, env-var lists, model field lists); prose for descriptions and concepts. No emojis, no marketing voice, no badges. Short sentences. Reference docs link out to `docs/AUTH.md` and `docs/DATA.md` rather than duplicating them.
