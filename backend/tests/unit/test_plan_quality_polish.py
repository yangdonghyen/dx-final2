from datetime import date, time
from types import SimpleNamespace

from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.plan_generation_service import PlanGenerationService, _is_dessert_shop, _is_usable_plan_candidate


def place(place_id, name, category):
    return SimpleNamespace(place_id=place_id, name=name, category=category, latitude=35.1, longitude=129.1)


def test_dessert_shops_are_not_meal_candidates_but_cafes_stay():
    bingsu = place(1, "할매팥빙수단팥죽 용호동본점", "음식점 > 한식 > 죽")
    bakery = place(2, "동네빵집", "음식점 > 간식 > 제과,베이커리")
    cafe = place(3, "구딩", "음식점 > 카페 > 테마카페 > 디저트카페")
    noodle = place(4, "공원칼국수", "음식점 > 한식 > 국수 > 칼국수")
    assert _is_dessert_shop(bingsu) and _is_dessert_shop(bakery)
    assert not _is_dessert_shop(cafe) and not _is_dessert_shop(noodle)
    assert not _is_usable_plan_candidate(bingsu) and _is_usable_plan_candidate(noodle)


def test_long_beach_and_meal_slots_are_shortened_anchors_kept():
    places = {
        1: place(1, "광안리해수욕장", "여행 > 관광,명소 > 해수욕장,해변"),
        2: place(2, "공원칼국수", "음식점 > 한식 > 국수 > 칼국수"),
        3: place(3, "해운대", "여행 > 관광,명소 > 해수욕장,해변"),
    }
    draft = GeneratedPlanDraft(days=[PlanDraftDay(visit_date=date(2026, 10, 20), items=[
        PlanDraftItem(1, "PLACE", "광안리", 1, "09:00", "12:00", ""),
        PlanDraftItem(2, "MEAL", "칼국수", 2, "12:30", "14:30", ""),
        PlanDraftItem(3, "PLACE", "해운대", 3, "15:00", "18:00", ""),
    ])])
    PlanGenerationService._normalize_stay_durations(draft, places, anchor_ids={3})
    items = draft.days[0].items
    assert (items[0].start_time, items[0].end_time) == ("09:00", "10:30")
    assert (items[1].start_time, items[1].end_time) == ("12:30", "14:00")
    assert (items[2].start_time, items[2].end_time) == ("15:00", "18:00")  # anchor


def test_lunch_after_a_cafe_moves_before_it():
    places = {
        1: place(1, "광안리해수욕장", "여행 > 관광,명소 > 해수욕장,해변"),
        2: place(2, "스타벅스 광안비치점", "음식점 > 카페 > 커피전문점 > 스타벅스"),
        3: place(3, "공원칼국수", "음식점 > 한식 > 국수 > 칼국수"),
        4: place(4, "이기대공원", "여행 > 공원"),
    }
    rows = [
        (PlanDraftItem(1, "PLACE", "광안리", 1, "09:00", "11:00", ""), time(9), time(11)),
        (PlanDraftItem(2, "PLACE", "스타벅스", 2, "12:30", "13:30", ""), time(12, 30), time(13, 30)),
        (PlanDraftItem(3, "MEAL", "칼국수", 3, "14:00", "15:00", ""), time(14), time(15)),
        (PlanDraftItem(4, "PLACE", "공원", 4, "16:00", "17:00", ""), time(16), time(17)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    days = [(date(2026, 10, 20), rows)]
    result = service._lunch_before_cafe(days, places, set(), SimpleNamespace(trip_id=1))
    out = [(item.place_id, start, end) for item, start, end in result[0][1]]
    assert out == [(1, time(9), time(11)), (3, time(12, 30), time(13, 30)), (2, time(13, 30), time(14, 30)), (4, time(16), time(17))]
    assert service._lunch_before_cafe(result, places, set(), SimpleNamespace(trip_id=1)) is result


def test_second_meal_right_after_lunch_is_dropped_and_long_dinner_shortened():
    places = {
        1: place(1, "신선식당", "음식점 > 한식"),
        2: place(2, "해변밀면보쌈", "음식점 > 한식 > 냉면"),
        3: place(3, "명가참치", "음식점 > 일식 > 참치회"),
    }
    rows = [
        (PlanDraftItem(1, "MEAL", "신선식당", 1, "12:30", "14:00", ""), time(12, 30), time(14)),
        (PlanDraftItem(2, "MEAL", "밀면", 2, "14:30", "16:00", ""), time(14, 30), time(16)),
        (PlanDraftItem(3, "MEAL", "참치", 3, "17:40", "19:40", ""), time(17, 40), time(19, 40)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    result = service._tidy_meals_and_stays([(date(2026, 10, 22), rows)], places, set(), SimpleNamespace(trip_id=1))
    assert [(item.place_id, item.sequence, start, end) for item, start, end in result[0][1]] == [
        (1, 1, time(12, 30), time(14)), (3, 2, time(17, 40), time(19, 10)),
    ]


def test_free_time_after_dinner_is_dropped():
    places = {1: place(1, "거대갈비", "음식점 > 한식 > 육류,고기")}
    rows = [
        (PlanDraftItem(1, "MEAL", "거대갈비", 1, "19:00", "20:30", ""), time(19), time(20, 30)),
        (PlanDraftItem(2, "FREE_TIME", "자유 시간", None, "20:30", "22:00", ""), time(20, 30), time(22)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    result = service._tidy_meals_and_stays([(date(2026, 10, 26), rows)], places, set(), SimpleNamespace(trip_id=1))
    assert [item.item_type for item, _, _ in result[0][1]] == ["MEAL"]


def test_short_day_gets_a_nearby_sight_and_dinner():
    places = {
        1: place(1, "광안리해수욕장", "여행 > 관광,명소 > 해수욕장,해변"),
        2: place(2, "송담추어탕", "음식점 > 한식 > 해물,생선 > 추어"),
        3: place(3, "부산시립미술관", "문화,예술 > 미술관"),
        4: place(4, "우리횟집", "음식점 > 한식 > 해물,생선 > 회"),
        5: place(5, "부산박물관", "문화,예술 > 문화시설 > 박물관"),
    }
    rows = [
        (PlanDraftItem(1, "PLACE", "광안리", 1, "09:00", "10:30", ""), time(9), time(10, 30)),
        (PlanDraftItem(2, "MEAL", "추어탕", 2, "12:30", "14:00", ""), time(12, 30), time(14)),
    ]
    other = [(PlanDraftItem(1, "PLACE", "박물관", 5, "09:00", "10:30", ""), time(9), time(10, 30))]
    service = PlanGenerationService.__new__(PlanGenerationService)
    service.route_provider = SimpleNamespace()
    service.place_provider = None
    service._route_estimate = lambda first, second, mode: SimpleNamespace(duration_seconds=600)
    trip = SimpleNamespace(trip_id=1, transport_mode="CAR")
    result = service._extend_short_days([(date(2026, 10, 16), rows), (date(2026, 10, 17), other)], places, trip)
    day1 = [(item.item_type, item.place_id, start) for item, start, _ in result[0][1]]
    assert day1[2] == ("PLACE", 3, time(14, 10))
    assert day1[3][0] == "MEAL" and day1[3][1] == 4 and day1[3][2] >= time(17, 30)


def test_late_dinner_moves_earlier_without_the_evening_sights_before_it():
    places = {
        1: place(1, "호산붓박물관", "문화,예술 > 박물관"),
        2: place(2, "신촌피아노거리", "여행 > 관광,명소"),
        3: place(3, "연세로", "여행 > 관광,명소"),
        4: place(4, "인사동수제비", "음식점 > 한식 > 수제비"),
    }
    rows = [
        (PlanDraftItem(1, "PLACE", "박물관", 1, "15:00", "16:30", ""), time(15), time(16, 30)),
        (PlanDraftItem(2, "PLACE", "피아노거리", 2, "17:10", "18:40", ""), time(17, 10), time(18, 40)),
        (PlanDraftItem(3, "PLACE", "연세로", 3, "19:13", "20:16", ""), time(19, 13), time(20, 16)),
        (PlanDraftItem(4, "MEAL", "수제비", 4, "20:45", "22:00", ""), time(20, 45), time(22)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    service._route_estimate = lambda first, second, mode: SimpleNamespace(duration_seconds=20 * 60)
    result = service._tidy_meals_and_stays([(date(2026, 12, 10), rows)], places, set(), SimpleNamespace(trip_id=1))
    out = [(item.place_id, start, end) for item, start, end in result[0][1]]
    assert out == [(1, time(15), time(16, 30)), (4, time(17, 30), time(18, 45))]


def test_missing_lunch_goes_into_the_midday_gap():
    places = {
        1: place(1, "올레길 7코스", "여행 > 관광,명소 > 도보여행"),
        2: place(2, "강정천유원지", "여행 > 관광,명소 > 유원지"),
        3: place(3, "강정해녀의집", "음식점 > 한식 > 해물,생선"),
    }
    rows = [
        (PlanDraftItem(1, "PLACE", "올레길", 1, "09:00", "11:30", ""), time(9), time(11, 30)),
        (PlanDraftItem(2, "PLACE", "강정천", 2, "13:30", "15:00", ""), time(13, 30), time(15)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    service.route_provider = object()
    service._route_estimate = lambda first, second, mode: SimpleNamespace(duration_seconds=10 * 60)
    service._restaurants_near = lambda origin, trip, used: []
    trip = SimpleNamespace(trip_id=1, transport_mode="CAR")
    result = service._insert_missing_lunch([(date(2026, 12, 4), rows)], places, trip)
    out = [(item.place_id, item.item_type, start, end) for item, start, end in result[0][1]]
    assert out[1] == (3, "MEAL", time(11, 40), time(12, 40))
    assert service._insert_missing_lunch(result, places, trip) is result


def test_sights_trade_days_so_each_day_stays_in_one_area():
    def spot(place_id, name, longitude):
        return SimpleNamespace(place_id=place_id, name=name, category="여행 > 관광,명소", latitude=35.1, longitude=longitude)
    places = {1: spot(1, "광안리", 129.12), 2: spot(2, "감천", 129.01), 3: spot(3, "송도", 129.02), 4: spot(4, "오륙도", 129.13)}
    draft = GeneratedPlanDraft(days=[
        PlanDraftDay(visit_date=date(2026, 11, 5), items=[
            PlanDraftItem(1, "PLACE", "광안리", 1, "09:00", "10:30", ""),
            PlanDraftItem(2, "PLACE", "감천", 2, "14:00", "15:30", ""),
        ]),
        PlanDraftDay(visit_date=date(2026, 11, 6), items=[
            PlanDraftItem(1, "PLACE", "송도", 3, "09:00", "10:30", ""),
            PlanDraftItem(2, "PLACE", "오륙도", 4, "14:00", "15:30", ""),
        ]),
    ])
    service = PlanGenerationService.__new__(PlanGenerationService)
    service._checked = lambda candidate, baseline, places, trip, route_seconds=None: None
    result = service._regroup_days(draft, places, set(), SimpleNamespace(trip_id=1))
    days = [sorted(item.place_id for item in day.items) for day in result.days]
    assert days in ([[1, 4], [2, 3]], [[2, 3], [1, 4]])
    assert [item.start_time for item in result.days[0].items] == ["09:00", "14:00"]


def test_a_long_stay_over_lunch_gives_way_to_lunch():
    places = {
        1: place(1, "요기저수지", "여행 > 관광,명소 > 저수지"),
        2: place(2, "카페가배당", "음식점 > 카페"),
        3: place(3, "거지국밥", "음식점 > 한식 > 국밥"),
    }
    rows = [
        (PlanDraftItem(1, "PLACE", "요기저수지", 1, "11:30", "13:30", ""), time(11, 30), time(13, 30)),
        (PlanDraftItem(2, "PLACE", "카페가배당", 2, "13:40", "14:40", ""), time(13, 40), time(14, 40)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    service.route_provider = object()
    service._route_estimate = lambda first, second, mode: SimpleNamespace(duration_seconds=5 * 60)
    service._restaurants_near = lambda origin, trip, used: []
    result = service._insert_missing_lunch([(date(2026, 11, 20), rows)], places, SimpleNamespace(trip_id=1, transport_mode="CAR"))
    out = [(item.place_id, start, end) for item, start, end in result[0][1]]
    assert out[:2] == [(1, time(11, 30), time(12, 30)), (3, time(12, 35), time(13, 35))]


def test_outdoor_sights_stay_out_of_the_dark():
    places = {
        1: place(1, "노고산", "여행 > 관광,명소 > 산"),
        2: place(2, "안목해변", "여행 > 관광,명소 > 해수욕장,해변"),
        3: place(3, "부산박물관", "문화,예술 > 박물관"),
    }
    day = date(2026, 11, 26)  # sunset 17:25
    rows = [
        (PlanDraftItem(1, "PLACE", "노고산", 1, "15:30", "17:30", ""), time(15, 30), time(17, 30)),
        (PlanDraftItem(2, "PLACE", "안목해변", 2, "17:00", "18:30", ""), time(17), time(18, 30)),
        (PlanDraftItem(3, "PLACE", "박물관", 3, "18:40", "19:20", ""), time(18, 40), time(19, 20)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    result = service._tidy_meals_and_stays([(day, rows)], places, set(), SimpleNamespace(trip_id=1))
    out = [(item.place_id, start, end) for item, start, end in result[0][1]]
    assert out == [(1, time(15, 30), time(17, 25)), (3, time(18, 40), time(19, 20))]


def test_a_night_visit_is_dropped_before_travel_times():
    rows = [
        (PlanDraftItem(1, "PLACE", "오동도", 1, "09:00", "11:00", ""), time(9), time(11)),
        (PlanDraftItem(2, "MEAL", "식당", 2, "18:00", "19:00", ""), time(18), time(19)),
        (PlanDraftItem(3, "PLACE", "야경", 3, "19:00", "21:00", ""), time(19), time(21)),
    ]
    service = PlanGenerationService.__new__(PlanGenerationService)
    result = service._drop_night_visits([(date(2026, 11, 14), rows)], set(), SimpleNamespace(trip_id=1))
    assert [item.place_id for item, _, _ in result[0][1]] == [1, 2]
    anchored = service._drop_night_visits([(date(2026, 11, 14), rows)], {3}, SimpleNamespace(trip_id=1))
    assert [item.place_id for item, _, _ in anchored[0][1]] == [1, 2, 3]
