from typing import Callable, Protocol

import httpx
from bs4 import BeautifulSoup

from kuleuven import nextauth
from kuleuven.exceptions import AuthenticationError, InvalidCredentialsError
from kuleuven.nextauth import NextauthDevice

MAX_WEBFLOW_ITERATIONS = 8


class AuthenticationProvider(Protocol):
    # The caller supplies whichever second factor the IdP demands: a TOTP code
    # for tokencode-enrolled accounts, or a device choice + approval wait for
    # accounts on the KU Leuven Authenticator (n-Auth push). See docs/AUTH.md §3.
    def provide_totp(self) -> str: ...

    def select_device(self, devices: list[NextauthDevice]) -> NextauthDevice: ...

    def awaiting_approval(self, device_name: str) -> None: ...

# Spoofs "localStorage works, no prior session" so the IdP routes us to the
# interactive login path. See docs/AUTH.md §3.2.
STORAGE_PROBE_PAYLOAD = {
    "shib_idp_ls_exception.shib_idp_session_ss": "",
    "shib_idp_ls_success.shib_idp_session_ss": "true",
    "shib_idp_ls_value.shib_idp_session_ss": "",
    "shib_idp_ls_exception.shib_idp_persistent_ss": "",
    "shib_idp_ls_success.shib_idp_persistent_ss": "true",
    "shib_idp_ls_value.shib_idp_persistent_ss": "",
    "shib_idp_ls_supported": "true",
    "_eventId_proceed": "",
}


def find_form(html, predicate):
    for form in BeautifulSoup(html, "html.parser").find_all("form"):
        fields = {
            element.get("name"): element.get("value", "")
            for element in form.find_all(["input", "textarea"])
            if element.get("name")
        }
        if predicate(set(fields)):
            return form.get("action", ""), fields
    return None


def parse_session_summary(html: str) -> dict | None:
    pre = BeautifulSoup(html, "html.parser").find("pre")
    if pre is None:
        return None

    miscellaneous: dict[str, str] = {}
    attributes: dict[str, str] = {}
    current_section: dict[str, str] | None = None
    for raw_line in pre.get_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "Miscellaneous":
            current_section = miscellaneous
            continue
        if line == "Attributes":
            current_section = attributes
            continue
        if current_section is None or ":" not in line:
            continue
        label, value = line.split(":", 1)
        current_section[label.strip()] = value.strip()

    if not attributes:
        return None

    result: dict = {"attributes": attributes}
    expiration_raw = miscellaneous.get("Session Expiration (barring inactivity)")
    if expiration_raw:
        digits = "".join(character for character in expiration_raw if character.isdigit())
        if digits:
            result["expires_in_minutes"] = int(digits)
    if "Authentication Time" in miscellaneous:
        result["authenticated_at"] = miscellaneous["Authentication Time"]
    if "Authentication Context Class" in miscellaneous:
        result["authentication_context_class"] = miscellaneous["Authentication Context Class"]
    return result


def sign_in_via_saml(
    http_client: httpx.Client,
    bootstrap_url: str,
    success_check: Callable[[], bool],
    success_label: str,
    username: str,
    password: str,
    provider: "AuthenticationProvider",
) -> None:
    bootstrap_response = http_client.get(bootstrap_url)
    bootstrap_response.raise_for_status()

    # Two SP bindings exist: POST (Toledo, Ultra) returns a SAMLRequest form
    # the client must submit; Redirect (KURT) issues a 302 directly to the IdP
    # that httpx has already followed. In the redirect case the bootstrap
    # response IS the IdP webflow page, so skip the SAMLRequest POST step.
    saml_request_form = find_form(
        bootstrap_response.text, lambda names: "SAMLRequest" in names
    )
    if saml_request_form is not None:
        idp_action, idp_fields = saml_request_form
        current_response = http_client.post(idp_action, data=idp_fields)
        current_response.raise_for_status()
    else:
        current_response = bootstrap_response

    acs_action, acs_fields = _walk_webflow(
        http_client, current_response, username, password, provider
    )

    # KURT's SessionInitiator redirects back to /login after the ACS sets the
    # SP cookie, and /login 404s once auth is complete. The SP cookie is the
    # real success signal, so defer to success_check instead of HTTP status.
    http_client.post(acs_action, data=acs_fields)

    if not success_check():
        raise AuthenticationError(
            f"ACS accepted SAMLResponse but {success_label} session cookie was not issued"
        )


def _walk_webflow(
    http_client: httpx.Client,
    current_response: httpx.Response,
    username: str,
    password: str,
    provider: "AuthenticationProvider",
) -> tuple[str, dict[str, str]]:
    credentials_already_submitted = False

    for _ in range(MAX_WEBFLOW_ITERATIONS):
        saml_response_form = find_form(
            current_response.text, lambda names: "SAMLResponse" in names
        )
        if saml_response_form is not None:
            return saml_response_form

        password_form = find_form(
            current_response.text,
            lambda names: {"username", "password"}.issubset(names),
        )
        if password_form is not None:
            if credentials_already_submitted:
                raise InvalidCredentialsError("IdP rejected the username or password")
            current_response = _post_form(http_client, current_response, password_form, {
                "username": username,
                "password": password,
                "_eventId": "proceed",
                "rememberlogin": "1",
            })
            credentials_already_submitted = True
            continue

        totp_form = find_form(
            current_response.text, lambda names: "tokencode" in names
        )
        if totp_form is not None:
            current_response = _post_form(http_client, current_response, totp_form, {
                "tokencode": provider.provide_totp(),
                "_eventId": "proceed",
            })
            continue

        device_picker = nextauth.parse_device_picker(current_response.text)
        if device_picker is not None:
            form_action, devices = device_picker
            wait_params = nextauth.parse_wait_params(current_response.text)
            chosen = provider.select_device(devices)
            continue_url = nextauth.send_push(
                http_client,
                httpx.URL(current_response.url).join(form_action),
                chosen.account_id,
            )
            provider.awaiting_approval(chosen.name)
            nextauth.wait_for_approval(wait_params)
            current_response = nextauth.complete_push_login(
                http_client, httpx.URL(current_response.url).join(continue_url)
            )
            continue

        storage_probe_form = find_form(
            current_response.text,
            lambda names: any(name.startswith("shib_idp_ls_") for name in names),
        )
        if storage_probe_form is not None:
            current_response = _post_form(
                http_client, current_response, storage_probe_form, STORAGE_PROBE_PAYLOAD
            )
            continue

        raise AuthenticationError(f"unrecognized IdP form at {current_response.url}")

    raise AuthenticationError("IdP WebFlow exceeded iteration limit")


def _post_form(
    http_client: httpx.Client,
    current_response: httpx.Response,
    form_match: tuple[str, dict[str, str]],
    payload: dict[str, str],
) -> httpx.Response:
    form_action, _ = form_match
    next_response = http_client.post(
        httpx.URL(current_response.url).join(form_action),
        data=payload,
    )
    next_response.raise_for_status()
    return next_response
