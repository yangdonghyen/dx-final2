from datetime import date, datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

AgeGroup = Literal["UNDER_20", "20S", "30S", "40S", "50S", "60S", "70S_PLUS"]
CompanionRelation = Literal["FATHER", "MOTHER", "SPOUSE", "CHILD", "FRIEND", "OTHER"]
WalkingTolerance = Literal["VERY_LOW", "LOW", "NORMAL", "HIGH"]
RestFrequency = Literal["LOW", "NORMAL", "HIGH"]
TravelStyle = Literal["SLOW", "STANDARD", "FOOD_FOCUSED"]
TransportMode = Literal["PUBLIC_TRANSIT", "CAR", "WALK", "MIXED", "OTHER"]
TripStatus = Literal["DRAFT", "PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "ARCHIVED"]
InterestSource = Literal["PROFILE", "CONTENT_AI", "USER"]
ShareLinkType = Literal["VIEW", "INVITE"]


class TripPreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    walking_tolerance: WalkingTolerance | None = None
    rest_frequency: RestFrequency | None = None
    avoid_stairs: bool | None = None
    avoid_hills: bool | None = None
    taxi_allowed: bool | None = None
    # This is an itinerary-scoped choice, stored in trip_preferences rather
    # than changing the user's profile preference.
    travel_style: TravelStyle | None = None


class TripCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    title: str | None = Field(default=None, max_length=100)
    departure: str | None = Field(default=None, max_length=100)
    destination: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    budget_krw: int | None = Field(default=None, ge=0)
    transport_mode: TransportMode | None = None
    companion_ids: list[int] = Field(default_factory=list)
    trip_preferences: TripPreferenceInput | None = None
    interest_codes: list[str] | None = Field(default=None, validation_alias=AliasChoices("interest_codes", "interests"))

    @model_validator(mode="after")
    def validate_request(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if len(self.companion_ids) != len(set(self.companion_ids)):
            raise ValueError("Companion IDs must be unique")
        if self.interest_codes is not None:
            self.interest_codes = [code.strip().upper() for code in self.interest_codes]
            if len(self.interest_codes) != len(set(self.interest_codes)):
                raise ValueError("Interest codes must be unique")
        return self


class TripUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    title: str | None = Field(default=None, max_length=100)
    departure: str | None = Field(default=None, max_length=100)
    destination: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    budget_krw: int | None = Field(default=None, ge=0)
    transport_mode: TransportMode | None = None
    companion_ids: list[int] | None = None
    trip_preferences: TripPreferenceInput | None = None
    interest_codes: list[str] | None = Field(default=None, validation_alias=AliasChoices("interest_codes", "interests"))

    @model_validator(mode="after")
    def validate_request(self):
        if not self.model_fields_set:
            raise ValueError("At least one trip field is required")
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.companion_ids is not None and len(self.companion_ids) != len(set(self.companion_ids)):
            raise ValueError("Companion IDs must be unique")
        if self.interest_codes is not None:
            self.interest_codes = [code.strip().upper() for code in self.interest_codes]
            if len(self.interest_codes) != len(set(self.interest_codes)):
                raise ValueError("Interest codes must be unique")
        return self


class TripPreferenceResponse(BaseModel):
    walking_tolerance: WalkingTolerance | None
    rest_frequency: RestFrequency | None
    avoid_stairs: bool
    avoid_hills: bool
    taxi_allowed: bool
    travel_style: TravelStyle | None = None


class TripCompanionResponse(BaseModel):
    companion_id: int | None
    name: str
    relation: CompanionRelation
    age_group: AgeGroup | None
    preferences: TripPreferenceResponse
    interests: list[str]
    joined_by_invite: bool = False


class TripInterestResponse(BaseModel):
    interest_code: str
    source_type: InterestSource
    is_confirmed: bool


class TripSelectedPlaceResponse(BaseModel):
    place_id: int
    name: str
    region: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    category: str | None
    selected_order: int


class TripCreateResponse(BaseModel):
    trip_id: int
    status: TripStatus


class TripListItemResponse(BaseModel):
    trip_id: int
    title: str | None
    departure: str | None
    destination: str | None
    start_date: date | None
    end_date: date | None
    status: TripStatus
    # OWNER for the user's own trips, MEMBER for trips joined by invite.
    role: Literal["OWNER", "MEMBER"] = "OWNER"


class TripListResponse(BaseModel):
    trips: list[TripListItemResponse]


class TripDetailResponse(TripListItemResponse):
    budget_krw: int | None
    transport_mode: TransportMode | None
    preferences: TripPreferenceResponse
    companions: list[TripCompanionResponse]
    interests: list[TripInterestResponse]
    selected_places: list[TripSelectedPlaceResponse] = Field(default_factory=list)


class TripDeleteResponse(BaseModel):
    message: Literal["trip_archived"] = "trip_archived"


class TripShareLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link_type: ShareLinkType


class TripShareLinkResponse(BaseModel):
    link_type: ShareLinkType
    url: str
    expires_at: datetime | None


class SharedTripCompanionResponse(BaseModel):
    name: str
    relation: CompanionRelation


class SharedTripStop(BaseModel):
    start_time: str | None
    title: str
    item_type: str
    note: str | None = None


class SharedTripDay(BaseModel):
    day: int
    visit_date: date
    stops: list[SharedTripStop]


class SharedTripResponse(BaseModel):
    link_type: ShareLinkType
    title: str | None
    destination: str | None
    start_date: date | None
    end_date: date | None
    owner_nickname: str | None
    companions: list[SharedTripCompanionResponse]
    selected_places: list[str]
    # The saved itinerary (empty when no plan was made yet).
    days: list[SharedTripDay] = []


class TripJoinResponse(BaseModel):
    trip_id: int
    already_joined: bool

class YouTubeSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    youtube_url: str = Field(min_length=1, max_length=1000)


class YouTubeSourceResponse(BaseModel):
    source_id: int
    type: Literal["YOUTUBE"] = "YOUTUBE"
    video_id: str
    title: str | None
    description: str | None
    tags: list[str]


class SourceDeactivateResponse(BaseModel):
    message: Literal["source_deactivated"] = "source_deactivated"


class AnalysisEvidence(BaseModel):
    source: Literal["YOUTUBE"]
    text: str


class PreferenceAnalysisResponse(BaseModel):
    inferred_preferences: list[str]
    destination_candidates: list[str]
    evidence: list[AnalysisEvidence]
