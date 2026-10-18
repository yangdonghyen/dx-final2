"""Create pending regeneration previews without modifying the current itinerary."""

from dataclasses import replace
from datetime import date, datetime, timedelta
import logging
from time import monotonic
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.request_logging import current_request_id
from app.repositories.plan_repository import PlanItemRepository, PlanRegenerationPreviewRepository, PlanRepository
from app.repositories.trip_repository import TripRepository
from app.schemas.plan import PlanRegenerateRequest, PlanRegenerationPreviewResponse
from app.services.place_temporal_validation import verified_hours
from app.services.plan_generation_service import PlanGenerationService, _is_dessert_shop, _is_food_or_cafe
from app.services.plan_quality_rules import distance_meters, is_restaurant
from app.services.plan_travel_time import travel_columns


logger = logging.getLogger("app.plan_regeneration")
MAX_FEEDBACK_GOAL_PROVIDER_CALLS = 2



def candidate_row(place, anchor_ids, indoor=False):
    row = {
        "place_id": place.place_id,
        "name": place.name,
        "category": place.category,
        "region": place.region,
        "address": place.address,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "is_anchor": place.place_id in anchor_ids,
        "activity_kind": "FOOD_OR_CAFE" if _is_food_or_cafe(place) else "NON_FOOD_ACTIVITY",
        "opening_hours": verified_hours(place),
        "event_start_date": getattr(place, "event_start_date", None),
        "event_end_date": getattr(place, "event_end_date", None),
    }
    if indoor:
        row["indoor"] = True
    return row


def with_indoor_places(generation, candidates, candidate_places, anchor_ids, trip):
    """Rain or heat: add verified indoor places of the destination so the
    model has somewhere indoors to move outdoor stops (trip 107: the pool had
    beaches and parks only, and the rain proposal could not go indoors)."""
    finder = getattr(generation, "indoor_candidates", None)
    if finder is None:
        return candidates, candidate_places
    candidates, candidate_places = [dict(row) for row in candidates], dict(candidate_places)
    for row in candidates:
        place = candidate_places.get(row.get("place_id"))
        if place is not None and PlanGenerationService.is_indoor(place):
            row["indoor"] = True
    for place in finder(trip, set(candidate_places)):
        candidate_places[place.place_id] = place
        candidates.append(candidate_row(place, anchor_ids, indoor=True))
    return candidates, candidate_places


def rain_day(trip, today=None):
    """The day a weather proposal is about: today while the trip is on,
    otherwise its first day (what the app's 날씨별 오늘 일정 shows)."""
    today = today or date.today()
    start, end = getattr(trip, "start_date", None), getattr(trip, "end_date", None)
    if start is not None and end is not None and start <= today <= end:
        return today
    return start


def swap_outdoor_for_indoor(days, candidate_places, anchor_ids, target_date):
    """Rain or heat: on ``target_date`` move each outdoor sight to the nearest
    unused verified indoor place, keeping its time slot.  The model often
    leaves the beach in place (plan 55); this makes the proposal do what it
    says.  Anchors, meals and cafes stay.  Returns ``days`` itself when
    nothing changed; the caller validates the result like any draft."""
    used = {item.place_id for _, rows in days for item, _, _ in rows if item.place_id is not None}
    used_places = [candidate_places[place_id] for place_id in used if place_id in candidate_places]
    indoor = [
        place for place_id, place in candidate_places.items()
        if place_id not in used and place_id not in anchor_ids
        and PlanGenerationService.is_indoor(place) and not _is_food_or_cafe(place)
        and getattr(place, "latitude", None) is not None and getattr(place, "longitude", None) is not None
        and not any(same_site(place, other) for other in used_places)
    ]

    def distance(a, b):
        return (float(a.latitude) - float(b.latitude)) ** 2 + (float(a.longitude) - float(b.longitude)) ** 2

    changed = False
    result = []
    for visit_date, rows in days:
        if visit_date != target_date:
            result.append((visit_date, rows))
            continue
        new_rows = []
        for item, start, end in rows:
            place = candidate_places.get(item.place_id) if item.place_id is not None else None
            if (indoor and place is not None and item.item_type == "PLACE" and item.place_id not in anchor_ids
                    and not PlanGenerationService.is_indoor(place) and not _is_food_or_cafe(place)
                    and getattr(place, "latitude", None) is not None and getattr(place, "longitude", None) is not None):
                pick = min(indoor, key=lambda candidate: distance(candidate, place))
                indoor.remove(pick)
                # Two halls of one museum (부산박물관 / 부산박물관 부산관) are one visit.
                indoor = [candidate for candidate in indoor if not same_site(candidate, pick)]
                logger.info("weather_indoor_swap visit_date=%s from_place_id=%s to_place_id=%s", visit_date, item.place_id, pick.place_id)
                item = replace(item, place_id=pick.place_id, title=pick.name, recommendation_reason="비 예보가 있어 가까운 실내 장소로 바꿨어요.")
                changed = True
            new_rows.append((item, start, end))
        result.append((visit_date, new_rows))
    return result if changed else days


def same_site(first, second) -> bool:
    """One place under two Kakao rows: a name that starts with the other's
    name, or two entries within 150 m with the same first word."""
    a = (getattr(first, "name", "") or "").replace(" ", "")
    b = (getattr(second, "name", "") or "").replace(" ", "")
    if not a or not b:
        return False
    if a.startswith(b) or b.startswith(a):
        return True
    meters = distance_meters(first, second)
    first_word = lambda value: (value or "").split(" ")[0]
    return meters is not None and meters < 150 and first_word(getattr(first, "name", "")) == first_word(getattr(second, "name", ""))


def replace_dessert_meals(days, candidate_places, anchor_ids):
    """A weather proposal keeps the stored stops, including a dessert shop
    saved as lunch by an older plan (팥빙수 at 12:30).  Each such meal becomes
    the nearest unused real restaurant in the same time slot.  Returns
    ``days`` itself when nothing changed."""
    used = {item.place_id for _, rows in days for item, _, _ in rows if item.place_id is not None}
    restaurants = [
        place for place_id, place in candidate_places.items()
        if place_id not in used and is_restaurant(place) and not _is_dessert_shop(place)
        and getattr(place, "latitude", None) is not None and getattr(place, "longitude", None) is not None
    ]
    changed = False
    result = []
    for visit_date, rows in days:
        new_rows = []
        for item, start, end in rows:
            place = candidate_places.get(item.place_id) if item.place_id is not None else None
            if (restaurants and place is not None and item.item_type == "MEAL" and item.place_id not in anchor_ids
                    and _is_dessert_shop(place) and getattr(place, "latitude", None) is not None):
                pick = min(restaurants, key=lambda candidate: distance_meters(candidate, place) or 1e9)
                restaurants.remove(pick)
                logger.info("preview_dessert_meal_replaced visit_date=%s from_place_id=%s to_place_id=%s", visit_date, item.place_id, pick.place_id)
                item = replace(item, place_id=pick.place_id, title=pick.name, recommendation_reason="식사 시간이라 가까운 식당으로 바꿨어요.")
                changed = True
            new_rows.append((item, start, end))
        result.append((visit_date, new_rows))
    return result if changed else days


def with_current_places(generation, current, candidates, candidate_places, anchor_ids, trip):
    """Add the places of the stored itinerary to the preview's candidates.

    A preview rebuilds the candidate pool, which does not contain places
    added after generation (rest cafes, recovered lunches).  Without them
    the model cannot keep an unchanged item (the schema only allows
    candidate ids), so it swapped titles and ids or failed validation
    (plan 36: 609, 876, 907, 911 were missing).  Only stored places with
    coordinates that are eligible on the trip dates are added; anything
    else stays out, exactly as before.
    """
    generation_places = getattr(generation, "places", None)
    if generation_places is None:
        return candidates, candidate_places
    candidates, candidate_places = list(candidates), dict(candidate_places)
    added = []
    for place_id in dict.fromkeys(row.get("place_id") for row in current):
        if place_id is None or place_id in candidate_places:
            continue
        place = generation_places.get(place_id)
        if place is None or getattr(place, "latitude", None) is None or getattr(place, "longitude", None) is None:
            continue
        if not PlanGenerationService._is_temporally_eligible(place, trip):
            continue
        candidate_places[place_id] = place
        candidates.append(candidate_row(place, anchor_ids))
        added.append(place_id)
    if added:
        logger.info("preview_current_places_added request_id=%s place_ids=%s", current_request_id(), added)
    return candidates, candidate_places


class PlanRegenerationPreviewService:
    def __init__(self, session, provider, route_provider=None, place_provider=None):
        self.session = session; self.provider = provider
        self.plans = PlanRepository(session); self.items = PlanItemRepository(session)
        self.previews = PlanRegenerationPreviewRepository(session); self.trips = TripRepository(session)
        # Candidate discovery can upsert places. A preview rebuilds the same
        # pool as generation without searching ...
        self.generation = PlanGenerationService(session, provider, place_provider=None, route_provider=route_provider)
        # ... except the indoor search of a weather (rain/heat) proposal; the
        # verified places it finds are stored with the preview.
        self.indoor = PlanGenerationService(session, provider, place_provider=place_provider) if place_provider is not None else None

    def _owned_plan(self, user_id, plan_id):
        plan = self.plans.get(plan_id)
        if plan is None: raise AppError("PLAN_NOT_FOUND", "Plan not found", 404)
        trip = self.trips.get(plan.trip_id)
        if trip is None: raise AppError("TRIP_NOT_FOUND", "Trip not found", 404)
        if trip.user_id != user_id: raise AppError("FORBIDDEN", "You do not own this trip", 403)
        if trip.status == "ARCHIVED" or plan.status == "ARCHIVED": raise AppError("PLAN_ARCHIVED", "Plan is archived", 400)
        return plan, trip

    @staticmethod
    def _snapshot_item(item) -> dict[str, Any]:
        return {"item_id": item.item_id, "place_id": item.place_id, "visit_date": item.visit_date.isoformat(), "sequence_no": item.sequence_no, "item_type": item.item_type, "title": item.title, "start_time": item.start_time.isoformat() if item.start_time else None, "end_time": item.end_time.isoformat() if item.end_time else None, "validation_status": item.validation_status}

    @staticmethod
    def _proposed_item(item, visit_date, start_time, end_time, estimate=None) -> dict[str, Any]:
        # Travel values are stored with the proposal so approval applies these exact facts.
        travel = travel_columns(estimate)
        return {"place_id": item.place_id, "visit_date": visit_date.isoformat(), "sequence_no": item.sequence, "item_type": item.item_type, "title": item.title, "start_time": start_time.isoformat() if start_time else None, "end_time": end_time.isoformat() if end_time else None, "recommendation_reason": item.recommendation_reason, "transport_mode_from_previous": travel["transport_mode_from_previous"], "travel_minutes_from_previous": travel["travel_minutes_from_previous"], "travel_distance_meters_from_previous": travel["travel_distance_meters_from_previous"]}

    def _with_current_places(self, current, candidates, candidate_places, anchor_ids, trip):
        return with_current_places(self.generation, current, candidates, candidate_places, anchor_ids, trip)

    @staticmethod
    def _validate_no_time_overlap(days) -> None:
        for _, items in days:
            timed = sorted((entry for entry in items if entry[1] and entry[2]), key=lambda entry: entry[1])
            if any(current[1] < previous[2] for previous, current in zip(timed, timed[1:])):
                raise AppError("TIME_CONFLICT", "Preview itinerary items overlap", 422)

    @staticmethod
    def _optional_activity_count(items, candidate_places, anchor_ids):
        """Count non-anchor activity places, excluding known cafes."""
        selected = set()
        anchors = set(anchor_ids)

        for item in items:
            if item.get("item_type") != "PLACE":
                continue

            place_id = item.get("place_id")

            if place_id is None or place_id in anchors:
                continue

            candidate = candidate_places.get(place_id)

            if candidate is None:
                candidate = candidate_places.get(str(place_id))

            if isinstance(candidate, dict):
                category = candidate.get("category")
            else:
                category = getattr(candidate, "category", None)

            category_text = str(category or "").casefold()

            if any(word in category_text for word in (
                "ce7", "cafe", "??", "?????"
            )):
                continue

            selected.add(place_id)

        return len(selected)

    @staticmethod
    def _rest_minutes(items):
        """Measure explicit REST time in minutes."""
        total = 0.0

        for item in items:
            if item.get("item_type") != "REST":
                continue

            start_value = item.get("start_time")
            end_value = item.get("end_time")

            if not isinstance(start_value, str) or not isinstance(end_value, str):
                raise AppError(
                    "FEEDBACK_GOAL_UNVERIFIABLE",
                    "REST time is missing",
                    422,
                )

            try:
                start = datetime.fromisoformat("2000-01-01T" + start_value)
                end = datetime.fromisoformat("2000-01-01T" + end_value)
            except ValueError as exc:
                raise AppError(
                    "FEEDBACK_GOAL_UNVERIFIABLE",
                    "REST time is invalid",
                    422,
                ) from exc

            if start.tzinfo is not None or end.tzinfo is not None or end <= start:
                raise AppError(
                    "FEEDBACK_GOAL_UNVERIFIABLE",
                    "REST time interval is invalid",
                    422,
                )

            total += (end - start).total_seconds() / 60

        return total

    @staticmethod
    def _candidate_value(candidate, name):
        if isinstance(candidate, dict):
            return candidate.get(name)
        return getattr(candidate, name, None)

    @classmethod
    def _route_burden(
        cls, items, candidate_places, route_provider, transport_mode, metric
    ):
        """Sum only facts returned for every scheduled place-to-place leg.

        ``walking_seconds`` and ``duration_seconds`` are intentionally kept
        separate.  Coordinates, a missing provider result, or a partial route
        result are not enough evidence to infer either burden.
        """
        if route_provider is None:
            return None

        by_date = {}
        for item in items:
            place_id = item.get("place_id")
            if place_id is None:
                continue
            visit_date = item.get("visit_date")
            start_value = item.get("start_time")
            place = candidate_places.get(place_id)
            if (
                not isinstance(visit_date, str)
                or not isinstance(start_value, str)
                or place is None
            ):
                return None
            try:
                start = datetime.fromisoformat("2000-01-01T" + start_value)
            except ValueError:
                return None
            latitude = cls._candidate_value(place, "latitude")
            longitude = cls._candidate_value(place, "longitude")
            if latitude is None or longitude is None:
                return None
            try:
                latitude = float(latitude)
                longitude = float(longitude)
            except (TypeError, ValueError):
                return None
            by_date.setdefault(visit_date, []).append(
                (start, latitude, longitude)
            )

        total = 0
        legs = 0
        for visits in by_date.values():
            visits.sort(key=lambda visit: visit[0])
            for previous, current in zip(visits, visits[1:]):
                try:
                    estimate = route_provider.route(
                        previous[1], previous[2], current[1], current[2],
                        transport_mode,
                    )
                except Exception:
                    return None
                if estimate is None:
                    return None
                value = (
                    getattr(estimate, "walking_seconds", None)
                    if metric == "walking"
                    else getattr(estimate, "duration_seconds", None)
                )
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    return None
                total += value
                legs += 1
        return total if legs else None

    @classmethod
    def _validate_feedback_goal(
        cls, current, proposed, feedback_codes,
        candidate_places, anchor_ids, route_provider=None, transport_mode=None,
    ):
        """Verify measurable selected feedback goals."""
        codes = set(feedback_codes)

        if "places" in codes:
            before = cls._optional_activity_count(
                current, candidate_places, anchor_ids
            )
            after = cls._optional_activity_count(
                proposed, candidate_places, anchor_ids
            )

            if before == 0:
                raise AppError(
                    "FEEDBACK_GOAL_UNACHIEVABLE",
                    "No optional activity places are available to remove",
                    422,
                )

            if after >= before:
                raise AppError(
                    "FEEDBACK_GOAL_NOT_MET",
                    "The revised itinerary did not reduce optional activity places",
                    422,
                )

        if "rest" in codes:
            before_rest = cls._rest_minutes(current)
            after_rest = cls._rest_minutes(proposed)

            if after_rest <= before_rest:
                raise AppError(
                    "FEEDBACK_GOAL_NOT_MET",
                    "The revised itinerary did not increase REST time",
                    422,
                )

        for code, metric, description in (
            ("walking", "walking", "walking burden"),
            ("travel", "travel", "travel time"),
        ):
            if code not in codes:
                continue
            before = cls._route_burden(
                current, candidate_places, route_provider, transport_mode, metric
            )
            after = cls._route_burden(
                proposed, candidate_places, route_provider, transport_mode, metric
            )
            # Incomplete directions facts remain UNKNOWN; never estimate from
            # coordinates or reject a preview on an invented comparison.
            if before is not None and after is not None and after >= before:
                raise AppError(
                    "FEEDBACK_GOAL_NOT_MET",
                    f"The revised itinerary did not reduce verified {description}",
                    422,
                )

    @staticmethod
    def _changed(old, new) -> bool:
        return any(old.get(key) != new.get(key) for key in ("visit_date", "start_time", "end_time"))

    def _diff(self, current, proposed):
        remaining, result = list(current), []
        for candidate in proposed:
            if candidate["place_id"] is not None:
                match = next((row for row in remaining if row["place_id"] == candidate["place_id"] and row["item_type"] == candidate["item_type"]), None)
                kind = "ADDED" if match is None else ("RESCHEDULED" if self._changed(match, candidate) else "UNCHANGED")
            else:
                match = next((row for row in remaining if row["place_id"] is None and row["item_type"] in {"REST", "FREE_TIME"} and row["sequence_no"] == candidate["sequence_no"]), None)
                kind = "ADDED" if match is None else ("REST_CHANGED" if self._changed(match, candidate) else "UNCHANGED")
            if match is not None: remaining.remove(match)
            result.append({"change_type": kind, "before": match, "after": candidate})
        result.extend({"change_type": "REMOVED", "before": item, "after": None} for item in remaining)
        return result

    @classmethod
    def _feedback_retry_instruction(
        cls, instruction, feedback_codes, current, proposed, candidate_places, anchor_ids,
    ):
        """Add only server-verified feedback facts to the one retry prompt."""
        facts = ["Backend verification found that the requested feedback goal was not met."]
        codes = set(feedback_codes)
        if "places" in codes:
            facts.append(
                "Verified optional activity place count: "
                f"before={cls._optional_activity_count(current, candidate_places, anchor_ids)}, "
                f"latest_draft={cls._optional_activity_count(proposed, candidate_places, anchor_ids)}. "
                "The revised count must be lower."
            )
        if "rest" in codes:
            facts.append(
                "Verified REST minutes: "
                f"before={cls._rest_minutes(current):g}, latest_draft={cls._rest_minutes(proposed):g}. "
                "The revised REST minutes must be higher."
            )
        facts.append("Keep every required anchor and return only the existing output schema.")
        return instruction.strip() + "\n\n" + " ".join(facts)

    @classmethod
    def _has_retryable_feedback_shortfall(
        cls, feedback_codes, current, proposed, candidate_places, anchor_ids,
    ):
        """Only retry goals for which this service can state exact facts.

        Route goals deliberately remain a one-shot validation: incomplete route
        facts must not be replaced by a guessed retry instruction.
        """
        codes = set(feedback_codes)
        return (
            "places" in codes
            and cls._optional_activity_count(proposed, candidate_places, anchor_ids)
            >= cls._optional_activity_count(current, candidate_places, anchor_ids)
        ) or (
            "rest" in codes
            and cls._rest_minutes(proposed) <= cls._rest_minutes(current)
        )

    @staticmethod
    def _provider_model(provider):
        model = getattr(provider, "model", None)
        return model if isinstance(model, str) and model else type(provider).__name__

    def create(self, user_id, plan_id, request: PlanRegenerateRequest):
        started_at = monotonic()
        plan, trip = self._owned_plan(user_id, plan_id)
        current = [self._snapshot_item(item) for item in self.items.list(plan.plan_id)]
        provider_calls = 0
        feedback_retry_used = False
        try:
            trip_input, preferences, companions, interests, context, candidates, anchor_ids, candidate_places = self.generation._input(trip)
            candidates, candidate_places = self._with_current_places(current, candidates, candidate_places, anchor_ids, trip)
            if request.reason == "WEATHER_CHANGE":
                candidates, candidate_places = with_indoor_places(getattr(self, "indoor", None) or self.generation, candidates, candidate_places, anchor_ids, trip)
            retry_instruction = request.instruction
            for attempt in range(MAX_FEEDBACK_GOAL_PROVIDER_CALLS):
                provider_started_at = monotonic()
                provider_calls += 1
                try:
                    preview_regenerator = getattr(self.provider, "regenerate_preview_plan", None)
                    regenerate = preview_regenerator if callable(preview_regenerator) else self.provider.regenerate_plan
                    draft = regenerate(trip_input, preferences, companions, interests, context, candidates, request.reason, retry_instruction, current, request.feedback_codes)
                finally:
                    logger.info(
                        "preview_provider_call request_id=%s plan_id=%s model=%s call=%s/%s elapsed_ms=%s",
                        current_request_id(), plan.plan_id, self._provider_model(self.provider), provider_calls,
                        MAX_FEEDBACK_GOAL_PROVIDER_CALLS, round((monotonic() - provider_started_at) * 1000),
                    )
                draft = self.generation._normalize_draft_dates(draft, trip)
                # The trip's preferences, as in initial generation: a SLOW or
                # rest-heavy trip keeps its REST slots out of meal repair.
                days = self.generation._validate_draft(self.generation._prepare_draft(draft, candidate_places, anchor_ids, trip, preferences), set(candidate_places))
                adjuster = getattr(self.generation, "_adjust_route_timing", None)

                def finish(days):
                    # Same bounded repair as initial generation (reorder sights,
                    # trim flexible time, a verified closer restaurant, drop an
                    # optional sight); anchors are never touched and the result is
                    # revalidated below and by the feedback goal before saving.
                    days = adjuster(days, candidate_places, trip, anchor_ids, preferences, repair=True) if adjuster is not None else days
                    self._validate_no_time_overlap(days); self.generation._validate_temporal_draft(days, candidate_places)
                    legs = self.generation._validate_route_timing(days, candidate_places, trip) or {}; self.generation._validate_activity_diversity(days, candidate_places, trip)
                    return days, legs

                weather_days = None
                if request.reason == "WEATHER_CHANGE":
                    weather_days = swap_outdoor_for_indoor(days, candidate_places, anchor_ids, rain_day(trip))
                    weather_days = replace_dessert_meals(weather_days, candidate_places, anchor_ids)
                    # Same final tidy as a new plan: no meal right after a
                    # meal, usual stay lengths, lunch before the cafe, no
                    # visit or free time after dinner.
                    for step in ("_drop_late_visits", "_tidy_meals_and_stays", "_lunch_before_cafe"):
                        tidy = getattr(self.generation, step, None)
                        if callable(tidy):
                            weather_days = (
                                tidy(weather_days, anchor_ids, trip) if step == "_drop_late_visits"
                                else tidy(weather_days, candidate_places, anchor_ids, trip)
                            )
                    if weather_days is days:
                        weather_days = None
                if weather_days is not None:
                    try:
                        days, legs = finish(weather_days)
                    except AppError as exc:
                        # The indoor version did not validate (hours, route);
                        # keep the model's own proposal, checked as before.
                        logger.info("weather_indoor_swap_rejected plan_id=%s code=%s", plan.plan_id, exc.code)
                        days, legs = finish(days)
                else:
                    days, legs = finish(days)
                included_anchors = {item.place_id for _, rows in days for item, _, _ in rows if item.place_id is not None}
                if not anchor_ids.issubset(included_anchors): raise self.generation._provider_error()
                proposed_items = [self._proposed_item(item, visit_date, start, end, legs.get((visit_date, item.sequence))) for visit_date, rows in days for item, start, end in rows]
                if request.reason != "USER_FATIGUE":
                    break
                try:
                    self._validate_feedback_goal(
                        current, proposed_items, request.feedback_codes, candidate_places, anchor_ids,
                        getattr(self.generation, "route_provider", None), getattr(trip, "transport_mode", None),
                    )
                except AppError as exc:
                    if (
                        exc.code != "FEEDBACK_GOAL_NOT_MET"
                        or attempt + 1 == MAX_FEEDBACK_GOAL_PROVIDER_CALLS
                        or not self._has_retryable_feedback_shortfall(
                            request.feedback_codes, current, proposed_items, candidate_places, anchor_ids,
                        )
                    ):
                        raise
                    feedback_retry_used = True
                    retry_instruction = self._feedback_retry_instruction(
                        request.instruction, request.feedback_codes, current, proposed_items, candidate_places, anchor_ids,
                    )
                    logger.info(
                        "preview_feedback_goal request_id=%s plan_id=%s result=RETRYING code=%s "
                        "places_before=%s places_after=%s rest_minutes_before=%s rest_minutes_after=%s",
                        current_request_id(), plan.plan_id, exc.code,
                        self._optional_activity_count(current, candidate_places, anchor_ids),
                        self._optional_activity_count(proposed_items, candidate_places, anchor_ids),
                        self._rest_minutes(current), self._rest_minutes(proposed_items),
                    )
                    continue
                logger.info(
                    "preview_feedback_goal request_id=%s plan_id=%s result=PASSED retry_used=%s feedback_codes=%s "
                    "places_before=%s places_after=%s rest_minutes_before=%s rest_minutes_after=%s",
                    current_request_id(), plan.plan_id, feedback_retry_used, ",".join(sorted(request.feedback_codes)),
                    self._optional_activity_count(current, candidate_places, anchor_ids),
                    self._optional_activity_count(proposed_items, candidate_places, anchor_ids),
                    self._rest_minutes(current), self._rest_minutes(proposed_items),
                )
                break
            diff = self._diff(current, proposed_items)
            if all(row["change_type"] == "UNCHANGED" for row in diff):
                # TC-08: plan 38's rain proposal kept all 16 items (no indoor
                # candidates).  An identical "proposal" only confuses; say so.
                code = "WEATHER_NO_ALTERNATIVE" if request.reason == "WEATHER_CHANGE" else "PREVIEW_NO_CHANGES"
                raise AppError(code, "The proposal is identical to the current itinerary", 422)
            preview = self.previews.create(plan_id=plan.plan_id, user_id=user_id, base_version=plan.current_version, reason=request.reason, feedback_codes=list(request.feedback_codes), current_itinerary_snapshot={"items": current}, proposed_itinerary={"items": proposed_items}, diff=diff, expires_at=datetime.utcnow() + timedelta(minutes=get_settings().plan_regeneration_preview_ttl_minutes))
            self.session.commit()
        except AppError as exc:
            self.session.rollback()
            logger.info(
                "preview_create_failed request_id=%s plan_id=%s code=%s provider_calls=%s preview_saved=false total_elapsed_ms=%s",
                current_request_id(), plan_id, exc.code, provider_calls, round((monotonic() - started_at) * 1000),
            )
            raise
        except SQLAlchemyError as exc:
            self.session.rollback()
            logger.info("preview_create_failed request_id=%s plan_id=%s code=PREVIEW_STORAGE_UNAVAILABLE provider_calls=%s preview_saved=false total_elapsed_ms=%s", current_request_id(), plan_id, provider_calls, round((monotonic() - started_at) * 1000))
            raise AppError("PREVIEW_STORAGE_UNAVAILABLE", "Preview storage is unavailable", 503) from exc
        except Exception:
            self.session.rollback()
            logger.info("preview_create_failed request_id=%s plan_id=%s code=UNKNOWN provider_calls=%s preview_saved=false total_elapsed_ms=%s", current_request_id(), plan_id, provider_calls, round((monotonic() - started_at) * 1000))
            raise
        # Route and opening-hours providers can be unavailable.  Hard failures
        # above are rejected, but do not claim a fully verified itinerary here.
        logger.info(
            "preview_create_succeeded request_id=%s plan_id=%s preview_id=%s version=%s model=%s provider_calls=%s "
            "provider_call_limit=%s feedback_retry_used=%s preview_saved=true places_before=%s places_after=%s "
            "rest_minutes_before=%s rest_minutes_after=%s total_elapsed_ms=%s",
            current_request_id(), preview.plan_id, preview.preview_id, preview.base_version,
            self._provider_model(self.provider), provider_calls, MAX_FEEDBACK_GOAL_PROVIDER_CALLS, feedback_retry_used,
            self._optional_activity_count(current, candidate_places, anchor_ids),
            self._optional_activity_count(proposed_items, candidate_places, anchor_ids),
            self._rest_minutes(current), self._rest_minutes(proposed_items),
            round((monotonic() - started_at) * 1000),
        )
        return PlanRegenerationPreviewResponse(preview_id=preview.preview_id, plan_id=preview.plan_id, base_version=preview.base_version, status=preview.status, proposed_itinerary=preview.proposed_itinerary, diff=preview.diff, validation_status="UNKNOWN", expires_at=preview.expires_at)
