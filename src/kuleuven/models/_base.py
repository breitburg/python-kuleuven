from typing import Any

from pydantic import BaseModel, ConfigDict


class KuleuvenModel(BaseModel):
    # Internal Python attributes are snake_case; field aliases (when set) map
    # the upstream camelCase keys. populate_by_name=True lets factory code
    # construct models with either the snake_case name or the alias, so
    # `Model.model_validate(raw_api_dict)` works whenever aliases match the
    # upstream keys. extra="ignore" keeps us forward-compatible with new
    # fields the upstream API may add.
    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
    )


class ApiEchoModel(KuleuvenModel):
    # Mirrors an upstream JSON shape verbatim. model_dump() preserves the
    # camelCase aliases so existing CLI output (which used to pass raw dicts
    # straight to json.dumps) does not change shape.
    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
        serialize_by_alias=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)
