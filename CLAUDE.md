# CLAUDE.md

Conventions for working on this repo. Read before making changes.

## Layout

The package is `kuleuven`, the umbrella for KU Leuven services that share the Shibboleth IdP. `src/kuleuven/session.py` holds `KuleuvenSession` — owns the `httpx.Client` and runs the three-leg SAML sign-in (Toledo portal + Ultra + KURT). `src/kuleuven/toledo.py` holds `ToledoClient` — constructed from a `KuleuvenSession`, exposes every Toledo/Ultra endpoint (courses, content, files) as methods. `src/kuleuven/kurt.py` holds `KurtClient` — same shape, KURT endpoints. `src/kuleuven/shibboleth.py` owns the shared SAML helpers (`sign_in_via_saml`, `find_form`, `parse_session_summary`, `STORAGE_PROBE_PAYLOAD`). `src/kuleuven/exceptions.py` holds the auth exceptions. `src/kuleuven/cli/` is the Typer CLI and is the only place that knows about cookie persistence (`kuleuven.cli.storage`). The CLI groups commands by service: `kuleuven session ...` (with `kuleuven session raw` as the cookie-jar escape hatch), `kuleuven toledo ...`, `kuleuven kurt ...`.

Adding a new KU Leuven service (KU Loket, Ad Valvas, …) is symmetric: add `src/kuleuven/<service>.py` with a `<Service>Client(session)` class, add `KuleuvenSession.sign_in()` round-trip for its SP, add `src/kuleuven/cli/<service>.py` mounted on `app` as `<service>`. No new helpers.py / utils.py — name a new module for the concern.

## Library vs CLI

The library (`kuleuven.session`, `kuleuven.toledo`, `kuleuven.kurt`, `kuleuven.shibboleth`, `kuleuven.exceptions`) is pure: HTTP in, HTTP out, no disk I/O, no environment reads, no prompting. Cookie persistence, `.env` loading, TTY detection, and JSON output all live in `kuleuven.cli`. Keep it that way when adding features.

## CLI output contract

Every CLI command prints exactly one JSON object to stdout and exits with `0` on success, `1` on auth or session failure, `2` on missing input. Errors are JSON on stdout too, not stderr — agents need to parse one stream. Read credentials and other secrets from flags or env vars; prompt only if stdin is a TTY, otherwise emit an error JSON and exit. Never persist credentials to disk. The only thing that gets saved is the session cookie jar, at `platformdirs.user_data_path("kuleuven") / "cookies.json"` with `0600` permissions.

## Code style

Write no-nonsense code. No decorative docstrings or section banners. Comments only when the *why* is non-obvious (a hidden constraint, a SAML quirk, a workaround). Use full descriptive variable names — `current_response`, not `r`. Prefer early returns over `else`; if a loop needs `for/else`, factor the loop into a method that returns on success and raises after it. Do not introduce abstractions for hypothetical reuse — three similar lines is fine.

## Dependencies

Use `uv add` and `uv remove`. Do not edit the `dependencies` list in `pyproject.toml` by hand. For one-off Python, use `uv run python -c '...'`.

## Documentation

`README.md` documents the CLI and the Python API. `docs/AUTH.md` documents the SAML flow. `docs/DATA.md` documents the REST surface. Any change that a user can observe — new or renamed commands, flags, env vars, output shape, exit codes, public Python API on `KuleuvenSession`/`ToledoClient`/`KurtClient`, exception types, storage paths — must be reflected in `README.md` in the same change. Internal refactors that do not change observable behavior do not need a README update.

Style for `README.md` and other user-facing docs: use a structured layout. Each CLI command and each public API method gets its own subsection. Within those subsections, prefer a consistent shape — short prose description, then synopsis, options, example, exit codes — over one long paragraph. Bullet lists and tables are fine where the content is genuinely list-shaped (flag tables, exit code tables, env var lists, model field lists). Reserve prose for descriptions and concept explanations. No emojis, no marketing voice, no flowery taglines, no badges. Short sentences. Reference docs link out to `docs/AUTH.md` and `docs/DATA.md` rather than duplicating their content.
