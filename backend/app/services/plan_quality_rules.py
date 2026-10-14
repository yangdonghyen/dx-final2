"""Deterministic checks for whether a day of a plan is actually travelable.

The model drafts the itinerary; these rules decide on the server whether its
meals sit at meal times, whether a day is only restaurants, whether places
repeat, and whether a stay or a long unverified leg looks unrealistic.  They
only use stored facts (times, Kakao categories, coordinates, verified travel
minutes).  Unknown facts such as opening hours are never assumed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from datetime import time

DEFAULT_BREAKFAST_WINDOW = "07:00-09:30"
DEFAULT_LUNCH_WINDOW = "11:00-14:00"
DEFAULT_DINNER_WINDOW = "17:00-20:00"
MIN_MEAL_EXPECTATION_MINUTES = 30
_WINDOW_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def parse_window(value: str) -> tuple[time, time]:
    if not isinstance(value, str) or not _WINDOW_PATTERN.match(value.strip()):
        raise ValueError("Meal window must look like HH:MM-HH:MM")
    start, end = (time.fromisoformat(part) for part in value.strip().split("-"))
    if end <= start:
        raise ValueError("Meal window must end after it starts")
    return start, end


@dataclass(frozen=True)
class MealWindow:
    name: str
    label: str
    start: time
    end: time

    def contains(self, value: time | None) -> bool:
        return value is not None and self.start <= value <= self.end

    @property
    def text(self) -> str:
        return f"{self.label}({self.start:%H:%M}~{self.end:%H:%M})"


@dataclass(frozen=True)
class PlanQualityRules:
    """Meal windows apply to a meal's start time.

    Windows come from settings (PLAN_*_WINDOW) so they can follow the user or
    the trip.  A meal is expected when a day reaches at least 30 minutes into
    that window; a cafe that ends before the window's end is not a reason to
    hide a missing dinner, while a 17:19 finish is not treated as dinner time.
    """

    breakfast: MealWindow = field(default_factory=lambda: MealWindow("BREAKFAST", "아침", *parse_window(DEFAULT_BREAKFAST_WINDOW)))
    lunch: MealWindow = field(default_factory=lambda: MealWindow("LUNCH", "점심", *parse_window(DEFAULT_LUNCH_WINDOW)))
    dinner: MealWindow = field(default_factory=lambda: MealWindow("DINNER", "저녁", *parse_window(DEFAULT_DINNER_WINDOW)))
    max_meals_per_day: int = 3
    max_meal_minutes: int = 120
    # A verified drive longer than this immediately before a meal is a travel
    # burden worth surfacing, especially in a SLOW itinerary.  UNKNOWN legs
    # are never measured or converted to this finding.
    max_meal_travel_minutes: int = 30
    max_place_minutes: int = 240
    min_place_minutes: int = 20
    # Places on a later day this close to an earlier day's places repeat that area.
    repeat_area_meters: int = 1000
    # A leg longer than this with no verified travel time cannot be checked.
    unverified_leg_meters: int = 5000
    # Sights in a row with no meal, cafe or rest between them tire walkers.
    max_consecutive_sights: int = 3
    # Sightseeing minutes in one day above this are a crowded day.
    max_sight_minutes_per_day: int = 360
    # Only days whose schedule spans this long are compared for balance, so a
    # short arrival or departure day is never called uneven.
    full_day_span_minutes: int = 360
    uneven_day_minutes: int = 180

    @classmethod
    def from_windows(cls, breakfast: str, lunch: str, dinner: str) -> "PlanQualityRules":
        return cls(
            breakfast=MealWindow("BREAKFAST", "아침", *parse_window(breakfast)),
            lunch=MealWindow("LUNCH", "점심", *parse_window(lunch)),
            dinner=MealWindow("DINNER", "저녁", *parse_window(dinner)),
        )

    @classmethod
    def from_settings(cls) -> "PlanQualityRules":
        from app.core.config import get_settings

        settings = get_settings()
        return cls.from_windows(
            settings.plan_breakfast_window, settings.plan_lunch_window, settings.plan_dinner_window
        )

    @property
    def meal_windows(self) -> tuple[MealWindow, ...]:
        return (self.breakfast, self.lunch, self.dinner)

    def meal_window(self, start: time | None) -> MealWindow | None:
        return next((window for window in self.meal_windows if window.contains(start)), None)

    @staticmethod
    def expects_meal(day_start: time, day_end: time, window: MealWindow) -> bool:
        """Whether the schedule gives a meal window a usable minimum duration."""
        return (
            day_start <= window.start
            and _minutes(day_end) >= _minutes(window.start) + MIN_MEAL_EXPECTATION_MINUTES
        )


@dataclass(frozen=True)
class QualityFinding:
    code: str
    issue_type: str  # an existing plan_validation_issues.issue_type value
    severity: str
    message: str
    sequence: int | None = None
    day: str | None = None


@dataclass(frozen=True)
class DayStop:
    sequence: int
    item_type: str | None
    start: time | None
    end: time | None
    place: object | None = None
    travel_minutes: int | None = None


def _category(place) -> str:
    return (getattr(place, "category", None) or "").casefold().replace(" ", "")


def is_cafe(place) -> bool:
    category = _category(place)
    return "ce7" in category or "카페" in category or "cafe" in category


def is_restaurant(place) -> bool:
    """A meal venue by verified category (cafes are visits, not meals)."""
    if place is None or is_cafe(place):
        return False
    category = _category(place)
    return "fd6" in category or any(
        word in category for word in ("음식", "식당", "맛집", "한식", "양식", "중식", "일식", "restaurant")
    )


def is_food_or_cafe(place) -> bool:
    return is_restaurant(place) or is_cafe(place)


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _duration(stop: DayStop) -> int | None:
    if stop.start is None or stop.end is None:
        return None
    return _minutes(stop.end) - _minutes(stop.start)


def _coordinates(place):
    latitude = getattr(place, "latitude", None)
    longitude = getattr(place, "longitude", None)
    if latitude is None or longitude is None:
        return None
    try:
        return float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None


def distance_meters(first, second) -> float | None:
    a, b = _coordinates(first), _coordinates(second)
    if a is None or b is None:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    hav = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(hav))


def same_location(first, second) -> bool:
    """Two place rows at one full address (e.g. two Kakao entries, one building).

    Only an address with a lot number names one spot; "부산 수영구 광안동" does
    not.  Coordinates alone are not used: neighbouring shops can share them.
    """
    address_a = re.sub(r"\s+", "", getattr(first, "address", None) or "")
    address_b = re.sub(r"\s+", "", getattr(second, "address", None) or "")
    return bool(address_a) and address_a == address_b and re.search(r"\d", address_a) is not None


def _is_meal(stop: DayStop) -> bool:
    return stop.item_type == "MEAL" or (stop.item_type == "PLACE" and is_restaurant(stop.place))


def _is_sight(stop: DayStop) -> bool:
    return stop.item_type == "PLACE" and stop.place is not None and not is_food_or_cafe(stop.place)


def _span_minutes(stops: list[DayStop]) -> int:
    timed = [stop for stop in stops if stop.start is not None and stop.end is not None]
    if not timed:
        return 0
    return _minutes(max(stop.end for stop in timed)) - _minutes(min(stop.start for stop in timed))


def review_day(stops: list[DayStop], rules: PlanQualityRules, day_label: str) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    ordered = sorted(stops, key=lambda stop: (stop.start is None, stop.start or time(0), stop.sequence))
    meals = [stop for stop in ordered if _is_meal(stop)]

    used_windows: dict[str, DayStop] = {}
    for stop in meals:
        window = rules.meal_window(stop.start)
        if window is None:
            if stop.start is not None:
                findings.append(QualityFinding(
                    "MEAL_OUTSIDE_WINDOW", "OTHER", "WARNING",
                    f"{day_label} {stop.start:%H:%M} 식사는 일반적인 식사 시간"
                    f"({', '.join(w.text for w in rules.meal_windows)})이 아니에요.",
                    stop.sequence,
                ))
            continue
        if window.name in used_windows:
            findings.append(QualityFinding(
                "DUPLICATE_MEAL", "OTHER", "WARNING",
                f"{day_label} {window.label} 시간대에 식사가 두 번 들어 있어요.",
                stop.sequence,
            ))
        used_windows.setdefault(window.name, stop)
        if stop.travel_minutes is not None and stop.travel_minutes > rules.max_meal_travel_minutes:
            findings.append(QualityFinding(
                "LONG_MEAL_TRAVEL", "OTHER", "WARNING",
                f"{day_label} 식사 전 실제 이동시간이 {stop.travel_minutes}분으로 길어요.",
                stop.sequence,
            ))
    if len(meals) > rules.max_meals_per_day:
        findings.append(QualityFinding(
            "TOO_MANY_MEALS", "OTHER", "WARNING",
            f"{day_label} 식사 일정이 {len(meals)}번이에요(최대 {rules.max_meals_per_day}번).",
        ))

    # Meals right after each other with nothing to do in between.
    visits = [stop for stop in ordered if stop.item_type in {"PLACE", "MEAL"}]
    if visits and all(stop.place is not None and is_food_or_cafe(stop.place) for stop in visits):
        findings.append(QualityFinding(
            "FOOD_ONLY_DAY", "OTHER", "WARNING",
            f"{day_label} 일정이 식당·카페로만 채워져 있어요.",
        ))
    for previous, current in zip(visits, visits[1:]):
        if _is_meal(previous) and _is_meal(current):
            findings.append(QualityFinding(
                "BACK_TO_BACK_MEALS", "OTHER", "WARNING",
                f"{day_label} 식사 다음 일정이 다시 식사예요.",
                current.sequence,
            ))

    timed = [stop for stop in ordered if stop.start is not None and stop.end is not None]
    if timed:
        day_start = min(stop.start for stop in timed)
        day_end = max(stop.end for stop in timed)
        for window in (rules.lunch, rules.dinner):
            spans_window = rules.expects_meal(day_start, day_end, window)
            if spans_window and window.name not in used_windows:
                findings.append(QualityFinding(
                    f"MISSING_{window.name}", "OTHER", "WARNING",
                    f"{day_label} {window.text} 식사 일정이 없어요.",
                ))

    for stop in ordered:
        minutes = _duration(stop)
        if minutes is None or stop.item_type not in {"PLACE", "MEAL"}:
            continue
        if _is_meal(stop) and minutes > rules.max_meal_minutes:
            findings.append(QualityFinding(
                "LONG_MEAL", "OTHER", "WARNING",
                f"{day_label} 식사가 {minutes}분으로 너무 길어요.", stop.sequence,
            ))
        elif not _is_meal(stop) and minutes > rules.max_place_minutes:
            findings.append(QualityFinding(
                "LONG_STAY", "OTHER", "WARNING",
                f"{day_label} 한 장소에 {minutes}분 머무는 일정이에요.", stop.sequence,
            ))
        elif not _is_meal(stop) and minutes < rules.min_place_minutes:
            findings.append(QualityFinding(
                "SHORT_STAY", "OTHER", "WARNING",
                f"{day_label} 방문 시간이 {minutes}분뿐이에요.", stop.sequence,
            ))

    run = 0
    for stop in ordered:
        if _is_sight(stop):
            run += 1
            if run == rules.max_consecutive_sights + 1:
                findings.append(QualityFinding(
                    "CONSECUTIVE_SIGHTS", "OTHER", "WARNING",
                    f"{day_label} 관광지가 쉬는 시간 없이 {run}곳 이상 이어져요.", stop.sequence,
                ))
        # FREE_TIME has neither a place nor a verified activity. It may be a
        # flexible gap, a later user choice, or an AI-labelled walk; treating
        # it as a confirmed rest would hide a continuous activity burden.
        # Only a declared REST, a meal, or a verified food/cafe stop resets
        # the sightseeing run.
        elif stop.item_type in {"MEAL", "REST"} or (stop.place is not None and is_food_or_cafe(stop.place)):
            run = 0
    sight_minutes = sum(_duration(stop) or 0 for stop in ordered if _is_sight(stop))
    if sight_minutes > rules.max_sight_minutes_per_day:
        findings.append(QualityFinding(
            "CROWDED_DAY", "OTHER", "WARNING",
            f"{day_label} 관광 일정이 {sight_minutes}분으로 많아요(기준 {rules.max_sight_minutes_per_day}분).",
        ))

    located = [stop for stop in visits if stop.place is not None]
    for previous, current in zip(located, located[1:]):
        if current.travel_minutes is not None:
            continue
        distance = distance_meters(previous.place, current.place)
        if distance is not None and distance > rules.unverified_leg_meters:
            findings.append(QualityFinding(
                "UNVERIFIED_LONG_LEG", "TRAVEL_TIME_UNKNOWN", "WARNING",
                f"{day_label} {getattr(current.place, 'name', '다음 장소')}까지 직선 {distance / 1000:.1f}km라 "
                "이동시간을 확인해야 해요.",
                current.sequence,
            ))
    return findings


def review_plan(days: list[tuple[str, list[DayStop]]], rules: PlanQualityRules) -> list[QualityFinding]:
    """Per-day checks plus repeats across days (same spot, same small area)."""
    findings: list[QualityFinding] = []
    earlier: list[object] = []
    visited: list[object] = []
    for day_label, stops in days:
        findings.extend(replace(finding, day=day_label) for finding in review_day(stops, rules, day_label))
        for stop in stops:
            if stop.place is None:
                continue
            twin = next((
                place for place in visited
                if getattr(place, "place_id", None) != getattr(stop.place, "place_id", None)
                and same_location(place, stop.place)
            ), None)
            if twin is not None:
                findings.append(QualityFinding(
                    "DUPLICATE_LOCATION", "OTHER", "WARNING",
                    f"{day_label} {getattr(stop.place, 'name', '장소')}은(는) "
                    f"{getattr(twin, 'name', '다른 장소')}와 같은 위치예요.",
                    stop.sequence,
                    day_label,
                ))
            visited.append(stop.place)
        places = [stop.place for stop in stops if stop.place is not None and not is_food_or_cafe(stop.place)]
        located = [place for place in places if _coordinates(place) is not None]
        if located and earlier and all(
            any((distance_meters(place, previous) or math.inf) <= rules.repeat_area_meters for previous in earlier)
            for place in located
        ):
            findings.append(QualityFinding(
                "REPEATED_AREA", "OTHER", "WARNING",
                f"{day_label} 관광지가 모두 이전 날과 같은 지역(반경 {rules.repeat_area_meters / 1000:g}km)이에요.",
                day=day_label,
            ))
        earlier.extend(located)
    full_days = [
        (day_label, sum(_duration(stop) or 0 for stop in stops if _is_sight(stop)))
        for day_label, stops in days
        if _span_minutes(stops) >= rules.full_day_span_minutes
    ]
    if len(full_days) >= 2:
        busiest = max(minutes for _, minutes in full_days)
        for day_label, minutes in full_days:
            if busiest - minutes >= rules.uneven_day_minutes:
                findings.append(QualityFinding(
                    "UNEVEN_DAYS", "OTHER", "WARNING",
                    f"{day_label} 관광 일정이 {minutes}분으로 다른 날({busiest}분)보다 크게 적어요.",
                    day=day_label,
                ))
    return findings


# Non-food candidates closer than this form one sightseeing area.
CANDIDATE_AREA_METERS = 2000


def _sight_type(place) -> str:
    return (_category(place).split(">")[-1] or "").strip()


# One activity type (the last Kakao category segment) above this share of at
# least SIGHT_TYPE_MIN_SIGHTS sights is a skewed pool: most days would get
# the same kind of activity.  A share, not a cap, so real supply still wins.
SIGHT_TYPE_MAX_SHARE = 0.6
SIGHT_TYPE_MIN_SIGHTS = 3


def sight_type_counts(sights) -> dict[str, int]:
    counts: dict[str, int] = {}
    for place in sights:
        kind = _sight_type(place) or "UNKNOWN"
        counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items(), key=lambda row: (-row[1], row[0])))


def sight_types_skewed(sights) -> bool:
    """Whether one activity type dominates these non-food candidates."""
    sights = list(sights)
    if len(sights) < SIGHT_TYPE_MIN_SIGHTS:
        return False
    return max(sight_type_counts(sights).values()) / len(sights) > SIGHT_TYPE_MAX_SHARE


def candidate_supply(places, trip_days: int, area_meters: int = CANDIDATE_AREA_METERS, targets: dict | None = None) -> dict:
    """How much real sightseeing the candidate pool can carry, before generation.

    Counts only stored facts: Kakao categories and coordinates.  Areas group
    non-food candidates within ``area_meters`` of an area's first place, so a
    beach, a square and a theme street on one shore are one area, not three
    sights in three places.  Places without coordinates are counted but never
    placed in an area, and nothing about access or character is inferred.
    ``targets`` (sights, restaurants, areas) gives the shortfall to search for.
    """
    sights = [place for place in places if not is_food_or_cafe(place)]
    areas: list[list[object]] = []
    for place in sights:
        if _coordinates(place) is None:
            continue
        home = next((area for area in areas if (distance_meters(area[0], place) or math.inf) <= area_meters), None)
        if home is None:
            areas.append([place])
        else:
            home.append(place)
    targets = targets or {"sights": trip_days * 2, "restaurants": trip_days * 2, "areas": min(trip_days, 2)}
    wanted = targets["sights"]
    restaurants = sum(is_restaurant(place) for place in places)
    problems = []
    if len(sights) < trip_days:
        problems.append("SIGHTS_FEWER_THAN_DAYS")
    elif len(sights) < wanted:
        problems.append("SIGHTS_BELOW_TWO_PER_DAY")
    if trip_days >= 2 and len(areas) < targets["areas"]:
        problems.append("SINGLE_AREA")
    if restaurants < targets["restaurants"]:
        problems.append("RESTAURANTS_FEWER_THAN_MEALS")
    if sights and len(sights) - sum(len(area) for area in areas):
        problems.append("SIGHTS_WITHOUT_COORDINATES")
    if sight_types_skewed(sights):
        problems.append("LOW_SIGHT_TYPE_DIVERSITY")
    return {
        "total": len(places),
        "sights": len(sights),
        "restaurants": restaurants,
        "cafes": sum(is_cafe(place) for place in places),
        "sight_types": sorted({_sight_type(place) for place in sights} - {""}),
        "sight_type_counts": sight_type_counts(sights),
        "areas": len(areas),
        "area_sizes": [len(area) for area in areas],
        "trip_days": trip_days,
        "recommended_sights": wanted,
        "targets": targets,
        "shortfall": {
            "sights": max(0, wanted - len(sights)),
            "restaurants": max(0, targets["restaurants"] - restaurants),
            "areas": max(0, targets["areas"] - len(areas)) if trip_days >= 2 else 0,
        },
        "problems": problems,
    }
