import httpx

from kuleuven.kurt import KURT_ENTRY_URL, has_session as has_kurt_session
from kuleuven.shibboleth import (
    AuthenticationProvider,
    parse_session_summary,
    sign_in_via_saml,
)

TOLEDO_ORIGIN = "https://toledo.kuleuven.be"
PORTAL_URL = f"{TOLEDO_ORIGIN}/portal/"
ULTRA_ORIGIN = "https://ultra.edu.kuleuven.cloud"
ULTRA_ENTRY_URL = f"{ULTRA_ORIGIN}/ultra/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


class KuleuvenSession:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self.http_client = http_client or httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )

    def sign_in(
        self,
        username: str,
        password: str,
        provider: AuthenticationProvider,
    ) -> None:
        # Drop any existing portal and Ultra sessions so both bootstraps run
        # against fresh SAMLRequest forms. IdP cookies (rememberDevice) are
        # kept so 2FA stays skipped if the device is remembered.
        for cookie in list(self.http_client.cookies.jar):
            if (
                "toledo.kuleuven.be" in cookie.domain
                or "ultra.edu.kuleuven.cloud" in cookie.domain
                or "kurt3.ghum.kuleuven.be" in cookie.domain
            ):
                self.http_client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)

        sign_in_via_saml(
            http_client=self.http_client,
            bootstrap_url=PORTAL_URL,
            success_check=lambda: any(
                name.startswith("_shibsession_")
                for name in self.http_client.cookies.keys()
            ),
            success_label="_shibsession_",
            username=username,
            password=password,
            provider=provider,
        )

        # Blackboard Ultra has an independent SAML SP and cookie jar; without
        # this second handshake /learn/api/v1/* responds 401 even with the
        # portal session live. The IdP recognises the just-issued session, so
        # this round-trip carries no second password/TOTP prompt.
        sign_in_via_saml(
            http_client=self.http_client,
            bootstrap_url=ULTRA_ENTRY_URL,
            success_check=self.has_ultra_session,
            success_label="Blackboard Ultra",
            username=username,
            password=password,
            provider=provider,
        )

        # KURT is a third Shibboleth SP scoped to its own host; without this
        # round-trip the /api endpoints respond 401. The IdP SSO from the
        # earlier handshakes means no extra password/TOTP prompt fires.
        sign_in_via_saml(
            http_client=self.http_client,
            bootstrap_url=KURT_ENTRY_URL,
            success_check=lambda: has_kurt_session(self.http_client),
            success_label="KURT",
            username=username,
            password=password,
            provider=provider,
        )

    def session_info(self) -> dict | None:
        response = self.http_client.get(f"{PORTAL_URL}Shibboleth.sso/Session")
        if response.status_code != 200:
            return None
        return parse_session_summary(response.text)

    def has_ultra_session(self) -> bool:
        return any(
            "ultra.edu.kuleuven.cloud" in cookie.domain
            for cookie in self.http_client.cookies.jar
        )

    def close(self) -> None:
        self.http_client.close()

    def __enter__(self) -> "KuleuvenSession":
        return self

    def __exit__(self, *_) -> None:
        self.close()
