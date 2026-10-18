from datetime import date, time
from types import SimpleNamespace

from app.services.external.ai.provider import PlanDraftItem
from app.services.plan_regeneration_preview_service import rain_day, swap_outdoor_for_indoor


def place(place_id, name, category, lat, lon):
    return SimpleNamespace(place_id=place_id, name=name, category=category, latitude=lat, longitude=lon)


def item(sequence, place_id, item_type="PLACE"):
    return PlanDraftItem(sequence, item_type, f"p{place_id}", place_id, "09:00", "11:00", "")


def test_rain_day_is_today_during_trip_else_first_day():
    trip = SimpleNamespace(start_date=date(2026, 10, 15), end_date=date(2026, 10, 17))
    assert rain_day(trip, today=date(2026, 10, 16)) == date(2026, 10, 16)
    assert rain_day(trip, today=date(2026, 10, 1)) == date(2026, 10, 15)


def test_outdoor_sight_on_rain_day_moves_to_nearest_indoor_place():
    places = {
        1: place(1, "광안리해수욕장", "여행 > 관광,명소 > 해수욕장,해변", 35.15, 129.11),
        2: place(2, "식당", "음식점 > 한식", 35.15, 129.11),
        3: place(3, "부산박물관", "문화,예술 > 박물관", 35.13, 129.09),
        4: place(4, "먼 미술관", "문화,예술 > 미술관", 35.50, 129.50),
        5: place(5, "해운대", "여행 > 관광,명소 > 해수욕장,해변", 35.16, 129.16),
    }
    day1, day2 = date(2026, 10, 20), date(2026, 10, 21)
    days = [
        (day1, [(item(1, 1), time(9), time(11)), (item(2, 2, "MEAL"), time(12), time(13))]),
        (day2, [(item(1, 5), time(9), time(11))]),
    ]
    swapped = swap_outdoor_for_indoor(days, places, set(), day1)
    assert swapped[0][1][0][0].place_id == 3
    assert swapped[0][1][0][0].title == "부산박물관"
    assert swapped[0][1][1][0].place_id == 2  # meals stay
    assert swapped[1][1][0][0].place_id == 5  # other days stay
    assert swap_outdoor_for_indoor(days, places, {1}, day1) is days  # anchors stay


def test_two_halls_of_one_museum_are_not_both_used():
    places = {
        1: place(1, "광안리해수욕장", "여행 > 관광,명소 > 해수욕장,해변", 35.15, 129.11),
        2: place(2, "부산박물관", "문화,예술 > 박물관", 35.13, 129.09),
        3: place(3, "부산박물관 부산관", "문화,예술 > 박물관", 35.131, 129.091),
        4: place(4, "부산시립미술관", "문화,예술 > 미술관", 35.16, 129.13),
    }
    day = date(2026, 10, 16)
    days = [(day, [(item(1, 1), time(9), time(10, 30)), (item(2, 2), time(16), time(17))])]
    swapped = swap_outdoor_for_indoor(days, places, set(), day)
    assert swapped[0][1][0][0].place_id == 4  # not the second hall of 부산박물관


def test_dessert_lunch_becomes_the_nearest_restaurant():
    from app.services.plan_regeneration_preview_service import replace_dessert_meals
    places = {
        1: place(1, "할매팥빙수단팥죽", "음식점 > 한식 > 죽", 35.13, 129.11),
        2: place(2, "공원칼국수", "음식점 > 한식 > 국수", 35.131, 129.111),
        3: place(3, "먼식당", "음식점 > 한식", 35.5, 129.5),
    }
    day = date(2026, 10, 16)
    days = [(day, [(item(1, 1, "MEAL"), time(12, 30), time(14))])]
    result = replace_dessert_meals(days, places, set())
    assert result[0][1][0][0].place_id == 2
