from typing import Self

from kuleuven.models._base import KuleuvenModel


class Person(KuleuvenModel):
    q_uid: str | None = None
    given_name: str = ""
    family_name: str = ""
    pk: str | None = None
    email: str | None = None
    foundations_id: str | None = None
    uuid: str | None = None

    @classmethod
    def from_portal_instructor(cls, raw: dict) -> Self:
        return cls(
            q_uid=raw.get("id"),
            given_name=raw.get("firstName", ""),
            family_name=raw.get("lastName", ""),
        )

    @classmethod
    def from_ultra_user(cls, raw: dict) -> Self:
        return cls(
            q_uid=raw.get("userName"),
            given_name=raw.get("givenName", ""),
            family_name=raw.get("familyName", ""),
            pk=raw.get("id"),
            email=raw.get("emailAddress"),
            foundations_id=raw.get("foundationsId"),
            uuid=raw.get("uuid"),
        )
