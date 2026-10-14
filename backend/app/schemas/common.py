from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ErrorDetail(BaseModel):
    code: str
    message: str
    # Only safe identifiers (e.g. an existing plan_id) or lists of finding
    # codes (e.g. {"codes": ["MISSING_LUNCH"]}); omitted when empty.
    details: dict[str, int | str | list[str]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
