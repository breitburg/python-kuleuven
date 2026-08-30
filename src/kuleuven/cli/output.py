import json
from datetime import date, time
from typing import Any

import typer
from pydantic import BaseModel
from pydantic_core import to_jsonable_python


def _json_default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    # date covers datetime too. Serialize through pydantic so a timestamp in a
    # hand-built payload renders exactly like one inside a model (ISO 8601,
    # UTC as `Z`).
    if isinstance(obj, (date, time)):
        return to_jsonable_python(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, default=_json_default))
    raise typer.Exit(code=exit_code)
