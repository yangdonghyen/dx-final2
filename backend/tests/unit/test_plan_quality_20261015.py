"""Quality fixes from the 2026-10-15 app check (trip 109, 강릉 1박 2일)."""

from datetime import date, time
from types import SimpleNamespace

from app.services.external.ai.provider import PlanDraftItem
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_generation_service import PlanGenerationService, _is_usable_plan_candidate

DAY = date(2026, 10, 24)


def place(place_id, name, category, lat, lon):
    return SimpleNamespace(place_id=place_id, name=name, category=category, latitude=lat, longitude=lon,
                           opening_hours=None, verification_status="UNKNOWN", event_start_date=None, event_end_date=None)


def test_bars_are_never_plan_candidates():
    bar = place(198, "안목해변술집 문문", "음식점 > 일식", 37.77, 128.95)
    sushi = place(199, "안목 초밥", "음식점 > 일식", 37.77, 128.95)
    assert not _is_usable_plan_candidate(bar) and _is_usable_plan_candidate(sushi)


class Roads:
    def route(self, lat1, lon1, lat2, lon2, mode):
        return RouteEstimate(15 * 60, "CAR")


def service():
    svc = PlanGenerationService.__new__(PlanGenerationService)
    svc.route_provider = Roads()
    return svc


def row(sequence, kind, place_id, start, end):
    return (PlanDraftItem(sequence, kind, f"p{place_id}", place_id, start.strftime("%H:%M"), end.strftime("%H:%M"), "r"), start, end)


def test_a_long_afternoon_gap_gets_one_verified_sight():
    cafe = place(1, "스타벅스", "음식점 > 카페", 37.77, 128.95)
    dinner = place(2, "식당", "음식점 > 한식", 37.78, 128.95)
    museum = place(3, "강릉시립미술관", "문화,예술 > 문화시설 > 미술관", 37.76, 128.90)
    places = {1: cafe, 2: dinner, 3: museum}
    days = [(DAY, [row(1, "PLACE", 1, time(14), time(15)), row(2, "MEAL", 2, time(17, 30), time(18, 30))])]

    filled = service()._fill_long_gaps(days, places, SimpleNamespace(trip_id=109, transport_mode="CAR"))

    rows = filled[0][1]
    assert [(item.place_id, item.sequence, str(start), str(end)) for item, start, end in rows] == [
        (1, 1, "14:00:00", "15:00:00"), (3, 2, "15:15:00", "16:45:00"), (2, 3, "17:30:00", "18:30:00"),
    ]


def test_short_gaps_and_missing_routes_leave_the_day_unchanged():
    cafe = place(1, "카페", "음식점 > 카페", 37.77, 128.95)
    dinner = place(2, "식당", "음식점 > 한식", 37.78, 128.95)
    museum = place(3, "박물관", "문화,예술 > 문화시설 > 박물관", 37.76, 128.90)
    places = {1: cafe, 2: dinner, 3: museum}
    # 60 minutes: below GAP_FILL_MIN_MINUTES (85).
    short = [(DAY, [row(1, "PLACE", 1, time(14), time(15)), row(2, "MEAL", 2, time(16), time(17))])]
    svc = service()
    assert svc._fill_long_gaps(short, places, SimpleNamespace(trip_id=1, transport_mode="CAR")) is short

    svc.route_provider = SimpleNamespace(route=lambda *args: None)  # no verified legs
    long = [(DAY, [row(1, "PLACE", 1, time(14), time(15)), row(2, "MEAL", 2, time(17, 30), time(18, 30))])]
    assert svc._fill_long_gaps(long, places, SimpleNamespace(trip_id=1, transport_mode="CAR")) is long


def test_far_dinner_review_can_look_up_restaurants_near_the_previous_stop(monkeypatch):
    import app.services.plan_generation_service as module

    near = place(10, "경포 막국수", "음식점 > 한식", 37.79, 128.91)
    bar = place(11, "경포 호프", "음식점 > 술집 > 호프", 37.79, 128.91)
    stored = {10: near, 11: bar}

    class Search:
        def __init__(self, *args, **kwargs): pass
        def upsert_candidates(self, found, destination): return [SimpleNamespace(place_id=p.place_id) for p in found]

    monkeypatch.setattr(module, "PlaceSearchService", Search)
    svc = service()
    svc.session = None
    svc.places = SimpleNamespace(get=stored.get)
    asked = []
    svc.place_provider = SimpleNamespace(search_nearby=lambda lat, lon, radius, codes, limit: asked.append((radius, codes)) or [near, bar])
    svc._is_temporally_eligible = lambda place, trip: True

    found = svc._restaurants_near(place(1, "수목원", "여행 > 수목원", 37.78, 128.90), SimpleNamespace(destination="강릉"), set())

    assert [p.place_id for p in found] == [10] and asked == [(3000, ["FD6"])]  # the bar is filtered out


def test_sights_after_dinner_are_dropped_but_meals_and_anchors_stay():
    svc = service()
    days = [(DAY, [
        row(1, "PLACE", 1, time(9), time(11)),
        row(2, "MEAL", 2, time(18), time(19)),
        row(3, "PLACE", 3, time(20), time(21)),   # 오죽헌 at 20:00
        row(4, "PLACE", 4, time(20, 30), time(21, 30)),  # anchor
    ])]
    kept = svc._drop_late_visits(days, {4}, SimpleNamespace(trip_id=1))
    assert [(item.place_id, item.sequence) for item, _, _ in kept[0][1]] == [(1, 1), (2, 2), (4, 3)]
    early = [(DAY, [row(1, "PLACE", 1, time(9), time(11)), row(2, "MEAL", 2, time(18), time(19))])]
    assert svc._drop_late_visits(early, set(), SimpleNamespace(trip_id=1)) is early
