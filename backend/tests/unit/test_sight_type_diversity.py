"""Activity-type diversity of the sight candidates (trip 86: 6 of 7 sights
were one trail type because cached rows with lower ids came first).
Generic categories only; no place-specific rule."""

from app.services.plan_generation_service import PlanGenerationService
from app.services.plan_quality_rules import candidate_supply
from tests.unit.test_phase3b_candidate_supply import SearchProvider, found, restaurant, two_days
from tests.unit.test_plan_generation_service import Place, service  # noqa: F401  (fixture)


def typed(place_id, kind, step):
    # Each place sits in its own area (about 4 km apart), so only the type differs.
    return Place(place_id, f"장소 {place_id}", f"여행 > 관광,명소 > {kind}", address=f"Seoul Jongno-gu {place_id}",
                 latitude=37.40 + step * 0.04, longitude=126.90, kakao_place_id=f"sight-{place_id}")


def cached_trails(count=8, start=100):
    return [typed(start + i, "도보여행코스", i) for i in range(count)]


def test_one_cached_type_no_longer_fills_the_front_of_the_order():
    others = [typed(200, "해수욕장", 20), typed(201, "산봉우리", 21), typed(202, "미술관", 22)]
    ordered = PlanGenerationService._interleave_by_area(cached_trails() + others)
    head = ordered[:7]
    assert {place.place_id for place in others} <= {place.place_id for place in head}
    assert len(ordered) == 11  # nothing is dropped, a type only moves later


def test_a_single_available_type_is_kept_not_capped():
    ordered = PlanGenerationService._interleave_by_area(cached_trails(5))
    assert [place.place_id for place in ordered] == [100, 101, 102, 103, 104]


def test_supply_reports_type_distribution_and_low_diversity():
    skewed = cached_trails(6) + [typed(200, "해수욕장", 20)]
    supply = candidate_supply(skewed, trip_days=3)
    assert supply["sight_type_counts"] == {"도보여행코스": 6, "해수욕장": 1}
    assert "LOW_SIGHT_TYPE_DIVERSITY" in supply["problems"]
    varied = cached_trails(3) + [typed(200, "해수욕장", 20), typed(201, "산봉우리", 21), typed(202, "미술관", 22)]
    assert "LOW_SIGHT_TYPE_DIVERSITY" not in candidate_supply(varied, trip_days=3)["problems"]


def test_other_cached_types_are_used_before_any_search(service):
    generator, session, _, _ = service
    trip = two_days(session.trips[1])
    # By car: these places sit in a 40 km line, which a trip without a car
    # would narrow to one area per day (test_transit_days_keep_one_area).
    trip.transport_mode = "CAR"
    session.places = cached_trails() + [typed(200, "해수욕장", 20), typed(201, "산봉우리", 21), typed(202, "미술관", 22)] + [
        restaurant(300 + i, f"식당 {i}") for i in range(4)
    ]
    provider = SearchProvider({})
    generator.place_provider = provider

    pool = generator._candidate_places(trip, [], {"travel_style": "SLOW"})

    assert provider.searches == []
    sights = [place for place in pool if place.place_id < 300]
    assert {200, 201, 202} <= {place.place_id for place in sights}


def test_persistent_skew_searches_a_little_for_other_activity_types(service):
    generator, session, _, _ = service
    trip = two_days(session.trips[1])
    # By car: these places sit in a 40 km line, which a trip without a car
    # would narrow to one area per day (test_transit_days_keep_one_area).
    trip.transport_mode = "CAR"
    session.places = cached_trails() + [restaurant(300 + i, f"식당 {i}") for i in range(4)]
    provider = SearchProvider({
        "관광지": [found("museum-1", "미술관", "AT4 여행 > 관광,명소 > 미술관", (37.90, 126.90))],
        "문화시설": [found("palace-1", "고궁", "AT4 여행 > 관광,명소 > 고궁", (37.94, 126.90))],
    })
    generator.place_provider = provider

    pool = generator._candidate_places(trip, [], {"travel_style": "SLOW"})

    assert provider.searches[:2] == ["관광지", "문화시설"] and len(provider.searches) <= 2
    names = {place.name for place in pool}
    assert {"미술관", "고궁"} <= names


def test_transit_days_keep_one_area(service):
    generator, session, _, _ = service
    trip = two_days(session.trips[1])
    session.places = cached_trails() + [restaurant(300 + i, f"식당 {i}") for i in range(4)]
    generator.place_provider = SearchProvider({})

    def span(mode):
        trip.transport_mode = mode
        lats = [float(place.latitude) for place in generator._candidate_places(trip, [], {"travel_style": "SLOW"}) if place.place_id < 300]
        return max(lats) - min(lats)

    # The trails sit 4.4 km apart in a line: by car all of them stay, by
    # transit only the ones around each day's centre.
    assert span("PUBLIC_TRANSIT") < span("CAR")
