import json
from typing import Any

import typer
from pydantic import BaseModel


def _json_default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def emit(payload: dict, exit_code: int = 0) -> None:
    print(json.dumps(payload, default=_json_default))
    raise typer.Exit(code=exit_code)
