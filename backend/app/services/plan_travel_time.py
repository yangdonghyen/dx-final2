"""Travel time between scheduled places, stored only from route facts.

A leg is two consecutive timed place items on the same day, ordered by start
time (the same legs ``_validate_route_timing`` checks).  REST and FREE_TIME
items are not legs, so their time is never added to a travel value.
"""

from dataclasses import replace
from datetime import time
from math import ceil

ROUTE_MODES = {"WALK", "PUBLIC_TRANSIT", "CAR", "TAXI", "OTHER"}  # plan_items enum
EMPTY_TRAVEL = {
    "transport_mode_from_previous": None,
    "travel_minutes_from_previous": None,
    "travel_distance_meters_from_previous": None,
}


def travel_columns(estimate):
    """Columns for a leg; a missing or malformed fact stays NULL, never 0."""
    duration = getattr(estimate, "duration_seconds", None)
    mode = getattr(estimate, "mode", None)
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0 or mode not in ROUTE_MODES:
        return dict(EMPTY_TRAVEL)
    distance = getattr(estimate, "distance_meters", None)
    distance = distance if isinstance(distance, int) and not isinstance(distance, bool) and distance > 0 else None
    return {
        **EMPTY_TRAVEL,
        "transport_mode_from_previous": mode,
        "travel_minutes_from_previous": ceil(duration / 60),
        "travel_distance_meters_from_previous": distance,
    }


def stored_travel_columns(raw):
    """Re-read travel values saved in a preview proposal without changing them."""
    if not isinstance(raw, dict):
        return dict(EMPTY_TRAVEL)
    mode = raw.get("transport_mode_from_previous")
    minutes = raw.get("travel_minutes_from_previous")
    distance = raw.get("travel_distance_meters_from_previous")
    if mode not in ROUTE_MODES or isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        return dict(EMPTY_TRAVEL)
    distance = distance if isinstance(distance, int) and not isinstance(distance, bool) and distance > 0 else None
    return {**EMPTY_TRAVEL, "transport_mode_from_previous": mode, "travel_minutes_from_previous": minutes, "travel_distance_meters_from_previous": distance}


def route_legs(rows):
    """Yield (previous, current) pairs of timed place rows ``(item, start, end)``."""
    ordered = sorted((row for row in rows if row[0].place_id is not None and row[1] and row[2]), key=lambda row: row[1])
    return list(zip(ordered, ordered[1:]))


def travel_statuses(items):
    """KNOWN / UNKNOWN / NONE per stored item of one day, keyed by object id.

    NONE: not a place, or the day's first place (no leg before it).
    KNOWN: a stored route fact.  UNKNOWN: a leg exists but no fact was stored.
    """
    places = sorted(
        (item for item in items if item.place_id is not None),
        key=lambda item: (item.start_time is None, item.start_time or time.min, item.sequence_no),
    )
    first_id = id(places[0]) if places else None
    statuses = {}
    for item in items:
        if item.place_id is None or id(item) == first_id:
            statuses[id(item)] = "NONE"
        elif getattr(item, "travel_minutes_from_previous", None) is not None:
            statuses[id(item)] = "KNOWN"
        else:
            statuses[id(item)] = "UNKNOWN"
    return statuses


def travel_response_fields(item, status):
    return {
        "transport_mode_from_previous": getattr(item, "transport_mode_from_previous", None),
        "travel_minutes_from_previous": getattr(item, "travel_minutes_from_previous", None),
        "travel_distance_meters_from_previous": getattr(item, "travel_distance_meters_from_previous", None),
        "travel_status": status,
    }


# --- Automatic time shift for verified travel (Task 7.5k) -----------------
DAY_END = time(22, 0)
MEAL_WINDOWS = ((time(11, 30), time(13, 30)), (time(17, 30), time(19, 30)))


class TravelShiftConflict(Exception):
    """Shifting later items cannot make room for a verified leg.

    ``index`` is the conflicting row in the ``rows`` given to the shift,
    ``kind`` is ``MEAL_WINDOW`` or ``DAY_END`` and ``overflow_seconds`` is how
    far past the limit the verified travel pushed it.
    """

    def __init__(self, message, kind=None, index=None, overflow_seconds=None, detail=None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.index = index
        self.overflow_seconds = overflow_seconds
        # Diagnostic facts only (ids, times, minutes); never names or secrets.
        self.detail = detail or {}


def _seconds(value):
    return value.hour * 3600 + value.minute * 60 + value.second


def _time(seconds):
    return time(seconds // 3600, seconds % 3600 // 60, seconds % 60)


def _text(value):
    return value.isoformat(timespec="minutes" if value.second == 0 else "seconds")


def _meal_window(start, windows=MEAL_WINDOWS):
    return next((window for window in windows if window[0] <= start <= window[1]), None)


def shift_day_for_travel(rows, travel_seconds, meal_windows=MEAL_WINDOWS, fixed_place_ids=frozenset()):
    """Return ``rows`` with later items moved so every verified leg fits.

    ``rows`` are ``(item, start, end)`` tuples of one day; ``travel_seconds``
    returns the verified seconds between two place items, or ``None``.
    Only start/end move: durations, order, places and days never change.
    The time needed before a place is the previous place's end, plus the
    REST/FREE_TIME time scheduled between them, plus the travel itself, so a
    rest is never counted as travel.  An UNKNOWN leg adds nothing.
    A delay is carried only as far as it overlaps the next item: a gap the
    draft already left between two items absorbs it, so one late leg does
    not push every later stop (and a later meal) by the full amount.
    ``meal_windows`` are ``(start, end)`` pairs a moved meal must still start
    in; plan generation passes the same windows its meal rules use.
    """
    timed = sorted((index for index, row in enumerate(rows) if row[1] and row[2]), key=lambda index: rows[index][1])
    shifted = list(rows)
    # Always retain the preceding end: model drafts may already overlap before
    # a route estimate is considered, and the same shift must repair that
    # factual timing conflict without inventing travel.
    pushed_end = None
    previous_place = None
    between = 0
    last_travel = None
    for index in timed:
        item, start, end = rows[index]
        length = _seconds(end) - _seconds(start)
        new_start = _seconds(start)
        if pushed_end is not None and new_start < pushed_end:
            new_start = pushed_end
        new_end = new_start + length
        if item.place_id is not None:
            if previous_place is not None:
                previous_item, _, previous_end = shifted[previous_place]
                travel = travel_seconds(previous_item, item)
                last_travel = travel
                if travel is not None:
                    travel_minutes = -(-travel // 60)
                    required = _seconds(previous_end) + between + travel_minutes * 60
                    if new_start < required:
                        new_start, new_end = required, required + length
            previous_place = index
            between = 0
        elif previous_place is not None:
            between += new_end - new_start
        pushed_end = new_end
        if new_start != _seconds(start):
            detail = {
                "sequence": getattr(item, "sequence", None),
                "place_id": item.place_id,
                "item_type": item.item_type,
                "original_start": _text(start),
                "original_end": _text(end),
                "travel_minutes": -(-last_travel // 60) if item.place_id is not None and last_travel else None,
                "arrival_seconds": new_start,
            }
            if item.place_id in fixed_place_ids:
                raise TravelShiftConflict(
                    f"Fixed anchor '{item.title}' cannot be moved to resolve a time conflict",
                    "ANCHOR_TIME_CONFLICT", index, new_start - _seconds(start),
                    {**detail, "fixed_anchor": True},
                )
            if new_end >= 24 * 3600 or new_end > _seconds(DAY_END):
                raise TravelShiftConflict(
                    f"Verified travel time pushes '{item.title}' past {_text(DAY_END)}",
                    "DAY_END", index, new_end - _seconds(DAY_END),
                    {**detail, "limit": _text(DAY_END)},
                )
            window = _meal_window(start, meal_windows) if item.item_type == "MEAL" else None
            if window is not None and not (new_start < 24 * 3600 and window[0] <= _time(new_start) <= window[1]):
                raise TravelShiftConflict(
                    f"Verified travel time moves meal '{item.title}' outside its meal window",
                    "MEAL_WINDOW", index, new_start - _seconds(window[1]),
                    {**detail, "meal_window": f"{_text(window[0])}-{_text(window[1])}"},
                )
            moved_start, moved_end = _time(new_start), _time(new_end)
            shifted[index] = (
                replace(item, start_time=_text(moved_start), end_time=_text(moved_end)),
                moved_start,
                moved_end,
            )
    return shifted


# --- Bounded repair when a verified leg still does not fit -----------------
# Each trim is re-checked against the whole day, so the work per day is
# bounded by (rows x rounds) shift runs on cached route facts.
MAX_FIT_ROUNDS = 8


def _shorten(rows, index, seconds, before=None, movable=None):
    """Return rows with ``rows[index]`` ending ``seconds`` earlier (start unchanged).

    Flexible timed rows right after it that start before ``before`` (the
    conflicting row) move earlier by the same amount, so the freed time
    reaches the conflict instead of becoming a gap.  Moving stops at the
    first row ``movable`` rejects (a meal, an anchor, a restaurant): those
    never move earlier.  The conflicting row and everything after it keep
    their times; the shift re-run decides where they land.
    """
    item, start, end = rows[index]
    new_end = _time(_seconds(end) - seconds)
    shortened = list(rows)
    shortened[index] = (replace(item, end_time=_text(new_end)), start, new_end)
    if before is not None and movable is not None:
        following = sorted(
            (position for position, row in enumerate(rows)
             if position != index and row[1] and row[2] and start < row[1] < before),
            key=lambda position: rows[position][1],
        )
        for position in following:
            other, other_start, other_end = rows[position]
            if not movable(other):
                break
            moved_start = _time(_seconds(other_start) - seconds)
            moved_end = _time(_seconds(other_end) - seconds)
            shortened[position] = (
                replace(other, start_time=_text(moved_start), end_time=_text(moved_end)),
                moved_start, moved_end,
            )
    return shortened


def _conflict(rows, travel_seconds, meal_windows=MEAL_WINDOWS):
    try:
        return shift_day_for_travel(rows, travel_seconds, meal_windows), None
    except TravelShiftConflict as conflict:
        return None, conflict


def fit_day_for_travel(rows, travel_seconds, minimum_minutes, trim=True, meal_windows=MEAL_WINDOWS):
    """``shift_day_for_travel`` that may shorten flexible time before a conflict.

    When a verified leg pushes a meal out of its window (or an item past the
    day end), items scheduled before it are shortened, nearest first, within
    ``minimum_minutes(item)`` (``None``: never shorten, e.g. anchors and
    meals).  A shortening is kept only when the re-run of the whole day shows
    it actually reduced that conflict, so no useless gap is left behind.
    Travel time itself is never shortened, and every round recomputes all
    later arrivals.  Returns ``(rows, trimmed_seconds)``; raises the
    remaining ``TravelShiftConflict`` when no allowed shortening resolves it.
    """
    current, trimmed_total = list(rows), 0
    shifted, conflict = _conflict(current, travel_seconds, meal_windows)
    for _ in range(MAX_FIT_ROUNDS):
        if conflict is None:
            return shifted, trimmed_total
        if not trim or conflict.index is None or not conflict.overflow_seconds or conflict.overflow_seconds <= 0:
            raise conflict
        target_start = current[conflict.index][1]
        earlier = sorted(
            (index for index, row in enumerate(current)
             if row[1] and row[2] and index != conflict.index and row[1] < target_start),
            key=lambda index: current[index][1],
            reverse=True,
        )
        improved = False
        for index in earlier:
            item, start, end = current[index]
            minimum = minimum_minutes(item)
            if minimum is None:
                continue
            spare = _seconds(end) - _seconds(start) - minimum * 60
            if spare <= 0:
                continue
            # Whole minutes keep stored times readable; never beyond the minimum.
            cut = min(spare, -(-conflict.overflow_seconds // 60) * 60)
            candidate = _shorten(
                current, index, cut, before=target_start,
                movable=lambda other: minimum_minutes(other) is not None,
            )
            candidate_shifted, candidate_conflict = _conflict(candidate, travel_seconds, meal_windows)
            # Progress: resolved, a smaller overflow on the same row, or the
            # remaining conflict is now a later row of the day.
            if candidate_conflict is None or (
                candidate_conflict.index == conflict.index
                and candidate_conflict.overflow_seconds < conflict.overflow_seconds
            ) or (
                candidate_conflict.index is not None
                and candidate[candidate_conflict.index][1] > target_start
            ):
                current, shifted, conflict = candidate, candidate_shifted, candidate_conflict
                trimmed_total += cut
                improved = True
                break
        if not improved:
            raise conflict
    if conflict is not None:
        raise conflict
    return shifted, trimmed_total
