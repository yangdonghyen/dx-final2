"""Off-route meals (trip 86 / plan 32, 2026-10-27).

Real case: after 올레길 1코스 and a cafe in 성산, lunch was 제주김만복김밥
서귀포점 in 강정 — 87 minutes by car — while 시흥해녀의집 was 210 m away.
A flagged meal is replaced only by a verified, clearly closer restaurant.
"""

import logging
from datetime import date
from math import asin, cos, radians, sin, sqrt

from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.cached_provider import CachedRouteProvider
from app.services.external.routing.provider import RouteEstimate
from tests.unit.test_plan_generation_service import Place, service  # noqa: F401  (pytest fixture)

DAY = date(2026, 10, 27)  # Tuesday
TRIP = type("Trip", (), {"transport_mode": "CAR", "trip_id": 86})()

OLLE = Place(592, "올레길 1코스(시흥-광치기 올레)", category="여행 > 도보여행 > 올레길", latitude=33.4895, longitude=126.9085)
CAFE = Place(626, "갤러리카페 마리안느", category="음식점 > 카페 > 갤러리카페", latitude=33.4870, longitude=126.9050)
FAR = Place(613, "제주김만복김밥 서귀포점", category="음식점 > 분식", latitude=33.2450, longitude=126.4800)
HAENYEO = Place(612, "시흥해녀의집", category="음식점 > 한식 > 해물,생선", latitude=33.4880, longitude=126.9070)
TTUK = Place(620, "제주뚝배기", category="음식점 > 한식 > 찌개,전골", latitude=33.4600, longitude=126.9300)
AFTERNOON = Place(700, "성산일출봉", category="여행 > 관광,명소", latitude=33.4580, longitude=126.9420)


def meters(a, b):
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


class Roads:
    """About 10 m/s plus a minute per leg; ``blocked`` places have no route fact."""

    def __init__(self, blocked=(), slow=()):
        self.blocked, self.slow, self.calls = list(blocked), list(slow), 0

    def route(self, lat1, lon1, lat2, lon2, _mode):
        self.calls += 1
        ends = {(round(lat1, 4), round(lon1, 4)), (round(lat2, 4), round(lon2, 4))}
        if any((round(p.latitude, 4), round(p.longitude, 4)) in ends for p in self.blocked):
            return None
        seconds = 60 + int(meters((lat1, lon1), (lat2, lon2)) / 10)
        if any((round(p.latitude, 4), round(p.longitude, 4)) in ends for p in self.slow):
            seconds += 3 * 3600  # a closer place whose real road is far longer
        return RouteEstimate(seconds, "CAR")


def plan(meal=FAR, *, after=None):
    items = [
        PlanDraftItem(1, "PLACE", OLLE.name, OLLE.place_id, "09:00", "11:50", "r"),
        PlanDraftItem(2, "PLACE", CAFE.name, CAFE.place_id, "11:53", "12:33", "r"),
        PlanDraftItem(3, "MEAL", meal.name, meal.place_id, "13:30", "15:00", "r"),
    ]
    if after is not None:
        items.append(PlanDraftItem(4, "PLACE", after.name, after.place_id, "15:30", "17:00", "r"))
    return GeneratedPlanDraft([PlanDraftDay(DAY, items)])


def places(*extra):
    return {p.place_id: p for p in (OLLE, CAFE, FAR, HAENYEO, TTUK, AFTERNOON, *extra)}


def review(generator, draft, roads, anchors=frozenset(), candidate_places=None):
    generator.route_provider = CachedRouteProvider(roads)
    result = generator._replace_far_meals(draft, candidate_places or places(), set(anchors), TRIP)
    return result.days[0].items, generator.last_far_meal_review


def test_trip86_far_lunch_is_replaced_by_the_verified_nearby_restaurant(service, caplog):
    generator, *_ = service
    with caplog.at_level(logging.INFO):
        items, report = review(generator, plan(), Roads())
    lunch = items[2]
    assert (lunch.place_id, lunch.title, lunch.item_type, lunch.start_time, lunch.end_time) == (
        612, "시흥해녀의집", "MEAL", "13:30", "15:00",
    )
    assert report[0]["result"] == "REPLACED" and report[0]["replaced_by"] == 612
    assert report[0]["original_route_seconds"] > 60 * 60 > report[0]["best_route_seconds"]
    assert any("plan_far_meal_review" in record.getMessage() for record in caplog.records)


def test_a_meal_near_its_neighbours_is_never_reviewed(service):
    generator, *_ = service
    roads = Roads()
    items, report = review(generator, plan(meal=TTUK), roads)
    assert items[2].place_id == 620 and report == [] and roads.calls == 0


def test_an_anchor_meal_is_never_replaced(service):
    generator, *_ = service
    items, report = review(generator, plan(), Roads(), anchors={613})
    assert items[2].place_id == 613 and report[0]["result"] == "KEPT_ANCHOR"


def test_without_a_verified_alternative_the_meal_is_kept_and_recorded(service):
    generator, *_ = service
    items, report = review(generator, plan(), Roads(blocked=[HAENYEO, TTUK]))
    assert items[2].place_id == 613 and report[0]["result"] == "KEPT_NO_VERIFIED_ALTERNATIVE"


def test_a_closer_place_with_a_longer_real_road_is_not_used(service):
    generator, *_ = service
    items, report = review(generator, plan(), Roads(slow=[HAENYEO, TTUK]))
    assert items[2].place_id == 613 and report[0]["result"] == "KEPT_NOT_CLEARLY_CLOSER"


def test_an_alternative_closed_at_that_time_is_skipped(service):
    generator, *_ = service
    closed = Place(612, "시흥해녀의집", category="음식점 > 한식 > 해물,생선", latitude=33.4880, longitude=126.9070,
                   opening_hours={"tuesday": {"closed": True}}, verification_status="VERIFIED")
    items, _ = review(generator, plan(), Roads(), candidate_places={**places(), 612: closed})
    assert items[2].place_id == 620  # the next verified, open restaurant


def test_unknown_route_for_the_original_meal_keeps_it(service):
    generator, *_ = service
    items, report = review(generator, plan(), Roads(blocked=[FAR]))
    assert items[2].place_id == 613 and report[0]["result"] == "KEPT_ORIGINAL_ROUTE_UNKNOWN"


def test_both_neighbours_are_used_to_judge_the_replacement(service):
    generator, *_ = service
    items, report = review(generator, plan(after=AFTERNOON), Roads())
    assert report and report[0]["result"] == "REPLACED"
    assert items[2].place_id in {612, 620} and items[3].place_id == 700
