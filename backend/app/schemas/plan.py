from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.trip import TripSelectedPlaceResponse


PlanStatus = Literal["DRAFT", "CONFIRMED", "ARCHIVED"]
PlanValidationStatus = Literal["VALID", "WARNING", "UNKNOWN"]
TravelStatus = Literal["KNOWN", "UNKNOWN", "NONE"]
PlanEditOperation = Literal[
    "DELETE_PLACE",
    "REPLACE_PLACE",
    "ADD_REST",
    "REORDER",
    "UPDATE_ITEM",
]


class PlanItemResponse(BaseModel):
    item_id: int
    place_id: int | None
    name: str
    start_time: time | None
    end_time: time | None
    validation_status: PlanValidationStatus
    item_type: str | None = None
    region: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    category: str | None = None
    note: str | None = None
    # Optional route facts; NULL minutes mean UNKNOWN, never zero.
    transport_mode_from_previous: str | None = None
    travel_minutes_from_previous: int | None = None
    travel_distance_meters_from_previous: int | None = None
    travel_status: TravelStatus | None = None


class PlanDayResponse(BaseModel):
    day: int
    visit_date: date
    items: list[PlanItemResponse]


class PlanGenerateResponse(BaseModel):
    plan_id: int
    status: PlanStatus
    days: list[PlanDayResponse]
    warnings: list[str]


class PlanEditRequest(BaseModel):
    operation: PlanEditOperation
    item_id: int | None = None
    new_place_id: int | None = None
    day: int | None = Field(default=None, ge=1)
    after_item_id: int | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    item_ids: list[int] | None = None
    # UPDATE_ITEM: new start "HH:MM" (duration kept), a rest's title, the note.
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    title: str | None = Field(default=None, min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=255)


class PlanEditResponse(BaseModel):
    plan_id: int
    status: PlanStatus
    current_version: int
    days: list[PlanDayResponse]
    warnings: list[str]
    selected_places: list[TripSelectedPlaceResponse] = Field(default_factory=list)


class PlanGenerateRequest(BaseModel):
    # ``None`` means the client did not make an anchor selection.  It is
    # intentionally different from ``[]``: an explicit empty list clears the
    # anchors for a newly-created citywide trip, while an omitted field must
    # not erase anchors already stored on an existing trip.
    selected_place_ids: list[int] | None = Field(default=None, max_length=24)


class PlanDetailResponse(PlanGenerateResponse):
    current_version: int
    validation_status: PlanValidationStatus


class PlanRegenerateRequest(BaseModel):
    reason: Literal["USER_FATIGUE", "WEATHER_CHANGE"]
    instruction: str = Field(min_length=1, max_length=5000)
    feedback_codes: list[Literal["walking", "places", "travel", "rest"]] = Field(default_factory=list, max_length=4)


class PlanRegenerationPreviewResponse(BaseModel):
    preview_id: int
    plan_id: int
    base_version: int
    status: Literal["PENDING", "APPLIED", "CANCELLED", "EXPIRED"]
    proposed_itinerary: dict[str, Any]
    diff: list[dict[str, Any]]
    validation_status: PlanValidationStatus
    expires_at: datetime


class PlanRegenerationPreviewApplyResponse(BaseModel):
    preview_id: int
    plan_id: int
    status: Literal["APPLIED", "CANCELLED"]
    current_version: int | None = None
    approved: bool = False


class PlanConfirmResponse(BaseModel):
    plan_id: int
    status: Literal["CONFIRMED"]
