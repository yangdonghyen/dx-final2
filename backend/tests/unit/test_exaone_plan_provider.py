import json
import logging
from datetime import date

import pytest

from app.core.exceptions import AppError
from app.services.external.ai.exaone_plan_provider import ExaonePlanGenerationProvider, MAX_RAW_RESPONSE_LOG_CHARS, PLAN_FORMAT, PLAN_SYSTEM_PROMPT, REGENERATION_PROMPT


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {"message": {"content": self.response}}


def _plan(days=None):
    return json.dumps({"days": days or [{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "PLACE", "title": "부산 미술관", "place_id": 101, "start_time": "10:00", "end_time": "11:00", "recommendation_reason": "CULTURE 관심사"},
        {"sequence": 2, "item_type": "REST", "title": "휴식", "place_id": None, "start_time": "11:00", "end_time": "11:30", "recommendation_reason": "휴식 선호"},
    ]}]}, ensure_ascii=False)


def _provider(response=None):
    client = Client(response or _plan())
    return ExaonePlanGenerationProvider("http://127.0.0.1:11434", "exaone-test", 2, client), client


def _inputs(end_date="2026-10-10"):
    return (
        {"destination": "부산", "start_date": "2026-10-10", "end_date": end_date, "budget_krw": 300000},
        {"walking_tolerance": "LOW", "rest_frequency": "HIGH", "taxi_allowed": True, "travel_style": "SLOW"},
        [], ["CULTURE"], {"raw_interest_codes": []},
        [
            {"place_id": 101, "name": "부산 미술관", "category": "CULTURE", "region": "부산광역시", "address": "부산광역시 해운대구"},
            {"place_id": 202, "name": "광주 미술관", "category": "CULTURE", "region": "광주광역시", "address": "광주광역시"},
        ],
    )


def test_generates_valid_multiday_draft_and_preserves_korean_and_null_place_ids():
    days = [
        {"visit_date": "2026-10-10", "items": [{"sequence": 1, "item_type": "PLACE", "title": "부산 미술관", "place_id": 101, "start_time": "10:00", "end_time": "11:00", "recommendation_reason": "문화 관심사"}]},
        {"visit_date": "2026-10-11", "items": [{"sequence": 1, "item_type": "FREE_TIME", "title": "자유 시간", "place_id": None, "start_time": "12:00", "end_time": "13:00", "recommendation_reason": "여유 일정"}]},
    ]
    provider, client = _provider(_plan(days))
    draft = provider.generate_plan(*_inputs("2026-10-11"))
    assert [day.visit_date for day in draft.days] == [date(2026, 10, 10), date(2026, 10, 11)]
    assert draft.days[0].items[0].title == "부산 미술관"
    assert draft.days[1].items[0].place_id is None
    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert [place["place_id"] for place in payload["places"]] == [101]
    format_schema = client.calls[0]["format_schema"]
    place_id_schema = (
        format_schema["properties"]["days"]["items"]["properties"]["items"]
        ["items"]["properties"]["place_id"]
    )
    assert place_id_schema == {
        "type": ["integer", "null"],
        "enum": [101, None],
    }
    assert (
        PLAN_FORMAT["properties"]["days"]["items"]["properties"]["items"]
        ["items"]["properties"]["place_id"]
    ) == {"type": ["integer", "null"]}


def test_repairs_missing_model_trip_date_with_non_factual_free_time():
    provider, _ = _provider(_plan([{
        "visit_date": "2026-10-10",
        "items": [{"sequence": 1, "item_type": "PLACE", "title": "Museum", "place_id": 101, "start_time": "10:00", "end_time": "11:00"}],
    }]))

    draft = provider.generate_plan(*_inputs("2026-10-11"))

    assert [day.visit_date for day in draft.days] == [date(2026, 10, 10), date(2026, 10, 11)]
    assert draft.days[1].items[0].item_type == "FREE_TIME"
    assert draft.days[1].items[0].place_id is None


def test_kakao_ce7_cafe_is_canonical_place_even_when_model_calls_it_meal():
    trip, preferences, companions, interests, preference_context, places = _inputs()
    places[0]["category"] = "CE7 > Food > Cafe"
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "MEAL", "title": "Cafe", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
    ]}])
    provider, _ = _provider(response)

    draft = provider.generate_plan(trip, preferences, companions, interests, preference_context, places)

    assert draft.days[0].items[0].item_type == "PLACE"


def test_uses_address_fallback_and_rejects_missing_destination_candidates_without_calling_ollama():
    provider, client = _provider()
    trip, preferences, companions, interests, preference_context, places = _inputs()
    places[0]["region"] = None
    provider.generate_plan(trip, preferences, companions, interests, preference_context, places)
    assert [place["place_id"] for place in json.loads(client.calls[0]["messages"][1]["content"])["places"]] == [101]

    provider, client = _provider(_plan())
    places[0]["address"] = "서울특별시"
    with pytest.raises(AppError) as error:
        provider.generate_plan(trip, preferences, companions, interests, preference_context, places)
    assert error.value.code == "PLACE_NOT_FOUND" and error.value.status_code == 404
    assert client.calls == []


def test_rejects_days_that_cover_the_trip_range_in_the_wrong_order():
    days = [
        {"visit_date": "2026-10-11", "items": [{"sequence": 1, "item_type": "PLACE", "title": "장소", "place_id": 101, "start_time": "10:00", "end_time": "11:00", "recommendation_reason": "이유"}]},
        {"visit_date": "2026-10-10", "items": [{"sequence": 1, "item_type": "REST", "title": "휴식", "place_id": None, "start_time": "10:00", "end_time": "11:00", "recommendation_reason": "이유"}]},
    ]
    provider, _ = _provider(_plan(days))
    with pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs("2026-10-11"))
    assert error.value.code == "EXAONE_INVALID_RESPONSE"


def test_rejects_sequence_that_is_not_in_chronological_time_order():
    items = [
        {"sequence": 1, "item_type": "PLACE", "title": "점심", "place_id": 101, "start_time": "12:00", "end_time": "13:30", "recommendation_reason": "FOOD 관심사"},
        {"sequence": 2, "item_type": "REST", "title": "저녁 전 휴식", "place_id": None, "start_time": "18:00", "end_time": "19:30", "recommendation_reason": "휴식 선호"},
        {"sequence": 3, "item_type": "FREE_TIME", "title": "오후 일정", "place_id": None, "start_time": "14:00", "end_time": "15:00", "recommendation_reason": "여유 일정"},
    ]
    provider, client = _provider(_plan([{"visit_date": "2026-10-10", "items": items}]))
    with pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs())
    assert error.value.code == "EXAONE_INVALID_RESPONSE"


def test_preview_regeneration_defers_only_forward_time_overlap_and_records_context(caplog):
    items = [
        {"sequence": 1, "item_type": "PLACE", "title": "부산 미술관", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
        {"sequence": 2, "item_type": "REST", "title": "휴식", "place_id": None, "start_time": "10:30", "end_time": "11:30"},
    ]
    provider, client = _provider(_plan([{"visit_date": "2026-10-10", "items": items}]))
    with caplog.at_level(logging.INFO):
        draft = provider.regenerate_preview_plan(*_inputs(), "USER_FATIGUE", "휴식을 늘려주세요")

    assert [item.start_time for item in draft.days[0].items] == ["10:00", "10:30"]
    assert len(client.calls) == 1
    message = next(record.getMessage() for record in caplog.records if "exaone_time_overlap_detected" in record.getMessage())
    assert "visit_date" in message and "sequence" in message and "place_id" in message and "is_anchor" in message


def test_preview_regeneration_rejects_an_out_of_order_time_even_when_overlap_repair_is_enabled():
    items = [
        {"sequence": 1, "item_type": "PLACE", "title": "부산 미술관", "place_id": 101, "start_time": "11:00", "end_time": "12:00"},
        {"sequence": 2, "item_type": "REST", "title": "휴식", "place_id": None, "start_time": "10:30", "end_time": "11:30"},
    ]
    provider, _ = _provider(_plan([{"visit_date": "2026-10-10", "items": items}]))
    with pytest.raises(AppError) as error:
        provider.regenerate_preview_plan(*_inputs(), "USER_FATIGUE", "휴식을 늘려주세요")
    assert error.value.code == "EXAONE_INVALID_RESPONSE"


def test_backend_generates_reasons_when_model_omits_or_supplies_its_own_reason():
    items = [
        {"sequence": 1, "item_type": "PLACE", "title": "미술관", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
        {"sequence": 2, "item_type": "REST", "title": "휴식", "place_id": None, "start_time": "11:00", "end_time": "11:30", "recommendation_reason": "임의의 모델 근거"},
        {"sequence": 3, "item_type": "FREE_TIME", "title": "자유 시간", "place_id": None, "start_time": "12:00", "end_time": "13:00"},
    ]
    provider, client = _provider(_plan([{"visit_date": "2026-10-10", "items": items}]))
    draft = provider.generate_plan(*_inputs())
    assert [item.recommendation_reason for item in draft.days[0].items] == [
        "CULTURE 관심사를 반영한 후보 장소입니다.",
        "높은 휴식 빈도를 반영해 휴식 시간을 포함했습니다.",
        "여행 일정 후보로 선택된 장소입니다.",
    ]
    item_schema = client.calls[0]["format_schema"]["properties"]["days"]["items"]["properties"]["items"]["items"]
    assert "recommendation_reason" not in item_schema["properties"]


def test_canonicalizes_candidate_name_and_item_type_without_trusting_model_title():
    trip, preferences, companions, interests, preference_context, places = _inputs()
    places[0].update({"name": "광안리해수욕장", "category": "AT4 관광명소"})
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "MEAL", "title": "부산불꽃축제", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
    ]}])
    provider, _ = _provider(response)

    draft = provider.generate_plan(trip, preferences, companions, interests, preference_context, places)

    assert (draft.days[0].items[0].title, draft.days[0].items[0].item_type) == ("광안리해수욕장", "PLACE")


def test_removes_only_an_explicit_non_place_id_and_avoids_a_retry(caplog):
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "PLACE", "title": "부산 미술관", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
        {"sequence": 2, "item_type": "REST", "title": "휴식 시간", "place_id": 101, "start_time": "11:00", "end_time": "12:00"},
    ]}])
    provider, client = _provider(response)

    with caplog.at_level(logging.INFO):
        draft = provider.generate_plan(*_inputs())

    assert draft.days[0].items[1].place_id is None
    assert draft.days[0].items[1].item_type == "REST"
    assert len(client.calls) == 1
    assert any("exaone_non_place_id_removed" in record.getMessage() for record in caplog.records)


def test_keeps_a_real_candidate_id_by_correcting_its_non_place_type():
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "FREE_TIME", "title": "부산 미술관", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
    ]}])
    provider, _ = _provider(response)

    draft = provider.generate_plan(*_inputs())

    assert (draft.days[0].items[0].place_id, draft.days[0].items[0].item_type) == (101, "PLACE")


def test_corrects_verified_rest_visit_id_before_canonicalizing_its_type(caplog):
    trip, preferences, companions, interests, context, places = _inputs()
    places[0].update({"name": "Seaside Drive", "category": "AT4"})
    places[1].update({
        "name": "Quiet Museum", "category": "AT4",
        "region": trip["destination"], "address": trip["destination"],
    })
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "REST", "title": "Quiet Museum", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
    ]}])
    provider, client = _provider(response)

    with caplog.at_level(logging.INFO):
        draft = provider.generate_plan(trip, preferences, companions, interests, context, places)

    item = draft.days[0].items[0]
    assert (item.place_id, item.title, item.item_type) == (202, "Quiet Museum", "PLACE")
    assert len(client.calls) == 1
    message = next(record.getMessage() for record in caplog.records if "exaone_non_place_id_type_corrected" in record.getMessage())
    assert "model_place_id" in message and "resolved_place_id" in message and "candidate_name" in message


def test_rejects_non_candidate_rest_id_with_structured_diagnostic(caplog):
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "REST", "title": "Unknown rest", "place_id": 999, "start_time": "10:00", "end_time": "11:00"},
    ]}])
    provider, _ = _provider(response)

    with caplog.at_level(logging.INFO), pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs())

    assert error.value.code == "EXAONE_INVALID_RESPONSE"
    message = next(record.getMessage() for record in caplog.records if "exaone_place_id_rejected" in record.getMessage())
    assert "candidate_in_pool" in message and "title" in message and "model_place_id" in message


@pytest.mark.parametrize("title,anchor", [("알 수 없는 일정", False), ("휴식", True)])
def test_rejects_non_place_id_when_safe_normalization_would_be_ambiguous_or_remove_anchor(title, anchor):
    trip, preferences, companions, interests, context, places = _inputs()
    places[0]["is_anchor"] = anchor
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "REST", "title": title, "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
    ]}])
    provider, _ = _provider(response)

    with pytest.raises(AppError) as error:
        provider.generate_plan(trip, preferences, companions, interests, context, places)

    assert error.value.code == "EXAONE_INVALID_RESPONSE"


def test_rejects_duplicate_ids_after_retry():
    days = [{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "PLACE", "title": "부산 미술관", "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
        {"sequence": 2, "item_type": "PLACE", "title": "부산 미술관", "place_id": 101, "start_time": "11:30", "end_time": "12:30"},
    ]}]
    provider, _ = _provider(_plan(days))

    import pytest
    from app.core.exceptions import AppError

    with pytest.raises(AppError) as exc_info:
        provider.generate_plan(*_inputs())

    assert exc_info.value.code == "EXAONE_INVALID_RESPONSE"



def test_canonicalizes_restaurant_returned_as_place_to_meal():
    trip, preferences, companions, interests, preference_context, places = _inputs()
    places.append({"place_id": 303, "name": "자갈치횟집", "category": "FD6 음식점", "region": "부산광역시", "address": "부산광역시 중구"})
    response = _plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "PLACE", "title": "관광지", "place_id": 303, "start_time": "12:00", "end_time": "13:00"},
    ]}])
    provider, _ = _provider(response)

    draft = provider.generate_plan(trip, preferences, companions, interests, preference_context, places)

    assert (draft.days[0].items[0].title, draft.days[0].items[0].item_type) == ("자갈치횟집", "MEAL")
def test_backend_uses_user_fatigue_reason_for_rest_during_regeneration():
    items = [{"sequence": 1, "item_type": "REST", "title": "휴식", "place_id": None, "start_time": "10:00", "end_time": "10:30"}]
    provider, _ = _provider(_plan([{"visit_date": "2026-10-10", "items": items}]))
    draft = provider.regenerate_plan(*_inputs(), "USER_FATIGUE", "휴식을 추가해 주세요")
    assert draft.days[0].items[0].recommendation_reason == "USER_FATIGUE 요청을 반영해 휴식 시간을 포함했습니다."


@pytest.mark.parametrize("content", [
    "not-json",
    json.dumps({}),
    json.dumps({"days": []}),
    _plan([{"visit_date": "2026-10-10", "items": [{"sequence": 1, "item_type": "OTHER", "title": "x", "place_id": None, "start_time": "10:00", "end_time": "11:00", "recommendation_reason": "x"}]}]),
    _plan([{"visit_date": "2026-10-10", "items": [{"sequence": 1, "item_type": "PLACE", "title": " ", "place_id": 101, "start_time": "10:00", "end_time": "11:00", "recommendation_reason": "x"}]}]),
    _plan([{"visit_date": "2026-10-10", "items": [{"sequence": 1, "item_type": "PLACE", "title": "x", "place_id": 202, "start_time": "10:00", "end_time": "11:00", "recommendation_reason": "x"}]}]),
])
def test_rejects_invalid_model_responses(content):
    provider, _ = _provider(content)
    with pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs())
    assert error.value.code == "EXAONE_INVALID_RESPONSE"


def test_does_not_log_raw_content_and_keeps_parse_diagnostic(caplog):
    raw_content = "x" * (MAX_RAW_RESPONSE_LOG_CHARS + 1)
    provider, _ = _provider(raw_content)
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    with pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs())

    assert error.value.code == "EXAONE_INVALID_RESPONSE"

    messages = [record.getMessage() for record in caplog.records]

    # AI 응답 원문은 로그에 기록하지 않는다.
    assert not any(
        "EXAONE raw response content:" in message
        for message in messages
    )
    assert not any("x" * 100 in message for message in messages)

    # 원문 대신 파싱 오류 진단은 유지한다.
    assert sum(
        message.startswith("EXAONE response validation failed:")
        for message in messages
    ) == 2

    diagnostic_records = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage() == "EXAONE response validation failed: json_decode"
    ]
    assert len(diagnostic_records) == 2

    assert any(
        record.getMessage() == "EXAONE plan failed strict validation; retrying once"
        for record in caplog.records
    )


@pytest.mark.parametrize("trip", [None, {"destination": "부산", "start_date": "bad", "end_date": "2026-10-10"}, {"destination": "부산", "start_date": "2026-10-11", "end_date": "2026-10-10"}])
def test_validates_trip_input(trip):
    provider, _ = _provider()
    _, preferences, companions, interests, preference_context, places = _inputs()
    with pytest.raises(AppError) as error:
        provider.generate_plan(trip, preferences, companions, interests, preference_context, places)
    assert error.value.code == "INVALID_PROVIDER_INPUT"


def test_keeps_strict_validation_for_noncanonical_interest_codes():
    provider, client = _provider()
    trip, preferences, companions, _, preference_context, places = _inputs()

    with pytest.raises(AppError) as error:
        provider.generate_plan(trip, preferences, companions, ["SEA"], preference_context, places)

    assert error.value.code == "INVALID_PROVIDER_INPUT"
    assert client.calls == []


def test_payload_keeps_raw_setup_interests_separate_from_canonical_interests():
    provider, client = _provider()
    trip, preferences, companions, _, _, places = _inputs()

    provider.generate_plan(
        trip,
        preferences,
        companions,
        ["FOOD", "CAFE", "NATURE"],
        {"raw_interest_codes": ["SEA", "CITY", "REST"]},
        places,
    )

    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["canonical_interests"] == ["FOOD", "CAFE", "NATURE"]
    assert payload["preference_context"] == {"raw_interest_codes": ["SEA", "CITY", "REST"]}


@pytest.mark.parametrize("style", ["SLOW", "STANDARD", "FOOD_FOCUSED"])
def test_payload_includes_each_travel_style(style):
    provider, client = _provider()
    trip, preferences, companions, interests, preference_context, places = _inputs()
    preferences["travel_style"] = style

    provider.generate_plan(trip, preferences, companions, interests, preference_context, places)

    assert json.loads(client.calls[0]["messages"][1]["content"])["preferences"]["travel_style"] == style


def test_payload_marks_verified_non_food_and_food_candidates_for_diverse_planning():
    trip, preferences, companions, interests, preference_context, places = _inputs()
    places[0]["activity_kind"] = "NON_FOOD_ACTIVITY"
    places[1]["activity_kind"] = "FOOD_OR_CAFE"
    places[1]["region"] = places[0]["region"]
    places[1]["address"] = places[0]["address"]
    preferences["travel_style"] = "FOOD_FOCUSED"
    provider, client = _provider(_plan([{"visit_date": "2026-10-10", "items": [
        {"sequence": 1, "item_type": "PLACE", "title": places[0]["name"], "place_id": 101, "start_time": "10:00", "end_time": "11:00"},
    ]}]))

    provider.generate_plan(trip, preferences, companions, interests, preference_context, places)

    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert [place["activity_kind"] for place in payload["places"]] == ["NON_FOOD_ACTIVITY", "FOOD_OR_CAFE"]


def test_regeneration_includes_context_and_validates_reason_and_instruction():
    provider, client = _provider()
    provider.regenerate_plan(*_inputs(), "USER_FATIGUE", "휴식 시간을 늘려 주세요")
    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["regeneration"]["reason"] == "USER_FATIGUE"
    assert payload["regeneration"]["instruction"]
    assert payload["regeneration"]["current_itinerary"] == []
    assert payload["regeneration"]["feedback_codes"] == []
    assert payload["preferences"]["travel_style"] == "SLOW"
    assert payload["preference_context"] == {"raw_interest_codes": []}
    with pytest.raises(AppError):
        provider.regenerate_plan(*_inputs(), "OTHER", "x")
    with pytest.raises(AppError):
        provider.regenerate_plan(*_inputs(), "WEATHER_CHANGE", " ")


@pytest.mark.parametrize(
    ("reason", "feedback_codes"),
    [
        ("USER_FATIGUE", ["walking"]),
        ("USER_FATIGUE", ["places"]),
        ("USER_FATIGUE", ["travel"]),
        ("USER_FATIGUE", ["rest"]),
        ("USER_FATIGUE", ["walking", "rest"]),
        ("USER_FATIGUE", ["places", "travel"]),
        ("USER_FATIGUE", ["walking", "places", "travel", "rest"]),
        ("WEATHER_CHANGE", []),
    ],
)
def test_regeneration_payload_preserves_actual_snapshot_and_selected_feedback(
    reason, feedback_codes
):
    provider, client = _provider()
    current_itinerary = [
        {
            "item_id": 900,
            "place_id": 101,
            "visit_date": "2026-10-10",
            "sequence_no": 1,
            "item_type": "PLACE",
            "title": "부산미술관",
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "validation_status": "VALID",
        },
        {
            "item_id": 901,
            "place_id": None,
            "visit_date": "2026-10-10",
            "sequence_no": 2,
            "item_type": "REST",
            "title": "휴식",
            "start_time": "11:00:00",
            "end_time": "11:30:00",
            "validation_status": "UNKNOWN",
        },
    ]

    provider.regenerate_plan(
        *_inputs(),
        reason,
        "Revise only what the selected feedback requires.",
        current_itinerary,
        feedback_codes,
    )

    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["regeneration"] == {
        "reason": reason,
        "instruction": "Revise only what the selected feedback requires.",
        "feedback_codes": feedback_codes,
        "current_itinerary": [
            {
                "place_id": 101,
                "visit_date": "2026-10-10",
                "sequence_no": 1,
                "item_type": "PLACE",
                "title": "부산미술관",
                "start_time": "10:00:00",
                "end_time": "11:00:00",
            },
            {
                "place_id": None,
                "visit_date": "2026-10-10",
                "sequence_no": 2,
                "item_type": "REST",
                "title": "휴식",
                "start_time": "11:00:00",
                "end_time": "11:30:00",
            },
        ],
    }
    assert client.calls[0]["messages"][0]["content"].endswith(REGENERATION_PROMPT)


def test_regeneration_prompt_names_revision_rules_and_existing_output_schema():
    for required_text in (
        "partial itinerary revision, not a fresh itinerary",
        "current_itinerary",
        "place_id, visit_date, sequence_no",
        "`walking`",
        "`places`",
        "`travel`",
        "`rest`",
        "`WEATHER_CHANGE`",
        "is_anchor=true",
        "REST and FREE_TIME must have place_id null",
        "every non-null place_id unique",
        "a diff",
    ):
        assert required_text in REGENERATION_PROMPT


def test_initial_prompt_distinguishes_rest_from_location_unknown_free_time():
    for required_text in (
        "REST is a planned interval",
        "FREE_TIME is location-unknown flexible time",
        "restful visit to a supplied cafe",
        "do not claim route feasibility",
    ):
        assert required_text in PLAN_SYSTEM_PROMPT


def test_payload_preserves_anchor_metadata_for_the_model_prompt():
    provider, client = _provider()
    trip, preferences, companions, interests, preference_context, places = _inputs()
    places[0]["is_anchor"] = True
    places[1]["is_anchor"] = False
    provider.generate_plan(trip, preferences, companions, interests, preference_context, places)
    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["places"] == [
        {
            "place_id": 101,
            "name": places[0]["name"],
            "category": places[0]["category"],
            "is_anchor": True,
        }
    ]


def test_request_sets_context_size_and_limits_days_to_trip_dates():
    provider, client = _provider(_plan([_day("2026-10-10"), _day("2026-10-11", None, "REST")]))

    provider.generate_plan(*_inputs("2026-10-11"))

    call = client.calls[0]
    assert call["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 256 + 2 * 512}
    days_schema = call["format_schema"]["properties"]["days"]
    assert days_schema["minItems"] == days_schema["maxItems"] == 2
    assert days_schema["items"]["properties"]["visit_date"]["enum"] == ["2026-10-10", "2026-10-11"]


def _day(visit_date, place_id=101, item_type="PLACE"):
    return {"visit_date": visit_date, "items": [{"sequence": 1, "item_type": item_type, "title": "장소", "place_id": place_id, "start_time": "10:00", "end_time": "11:00"}]}


def test_uses_trip_dates_in_order_when_model_dates_are_outside_the_trip():
    provider, _ = _provider(_plan([_day("2023-04-05"), _day("2023-04-06", None, "REST")]))

    draft = provider.generate_plan(*_inputs("2026-10-11"))

    assert [day.visit_date for day in draft.days] == [date(2026, 10, 10), date(2026, 10, 11)]
    assert draft.days[0].items[0].place_id == 101


def test_still_rejects_out_of_range_dates_when_day_count_differs_from_trip():
    provider, _ = _provider(_plan([_day("2023-04-05")]))
    with pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs("2026-10-11"))
    assert error.value.code == "EXAONE_INVALID_RESPONSE"


def test_duplicate_place_id_retry_recovers_on_second_response():
    class SequencedClient(Client):
        def __init__(self, responses):
            super().__init__(responses[0])
            self.responses = iter(responses)

        def chat(self, **kwargs):
            self.response = next(self.responses)
            return super().chat(**kwargs)

    title = _inputs()[5][0]["name"]

    first_day = {
        "visit_date": "2026-10-10",
        "items": [{
            "sequence": 1,
            "item_type": "PLACE",
            "title": title,
            "place_id": 101,
            "start_time": "10:00",
            "end_time": "11:00",
        }],
    }

    duplicate_day = {
        "visit_date": "2026-10-11",
        "items": [{
            "sequence": 1,
            "item_type": "PLACE",
            "title": title,
            "place_id": 101,
            "start_time": "10:00",
            "end_time": "11:00",
        }],
    }

    corrected_day = {
        "visit_date": "2026-10-11",
        "items": [{
            "sequence": 1,
            "item_type": "FREE_TIME",
            "title": "Free time",
            "place_id": None,
            "start_time": "10:00",
            "end_time": "11:00",
        }],
    }

    client = SequencedClient([
        _plan([first_day, duplicate_day]),
        _plan([first_day, corrected_day]),
    ])

    provider = ExaonePlanGenerationProvider(
        "http://127.0.0.1:11434",
        "exaone-test",
        2,
        client,
    )

    draft = provider.generate_plan(*_inputs("2026-10-11"))

    assert len(client.calls) == 2
    assert len(draft.days) == 2

    ids = [
        item.place_id
        for day in draft.days
        for item in day.items
        if item.place_id is not None
    ]

    assert ids == [101]
    assert draft.days[1].items[0].item_type == "FREE_TIME"

    retry_prompt = client.calls[1]["messages"][0]["content"]

    assert "Never reuse the same non-null place_id" in retry_prompt
    assert "duplicate_place_id:101" in retry_prompt
    assert "first_date=2026-10-10" in retry_prompt
    assert "again_date=2026-10-11" in retry_prompt


def test_duplicate_place_id_cross_day_rejected_after_two_attempts():
    title = _inputs()[5][0]["name"]

    days = [
        {
            "visit_date": visit_date,
            "items": [{
                "sequence": 1,
                "item_type": "PLACE",
                "title": title,
                "place_id": 101,
                "start_time": "10:00",
                "end_time": "11:00",
            }],
        }
        for visit_date in ("2026-10-10", "2026-10-11")
    ]

    provider, client = _provider(_plan(days))

    with pytest.raises(AppError) as error:
        provider.generate_plan(*_inputs("2026-10-11"))

    assert error.value.code == "EXAONE_INVALID_RESPONSE"
    assert len(client.calls) == 2


def _jeju_inputs(anchor=None):
    trip = {"destination": "제주", "start_date": "2026-10-27", "end_date": "2026-10-27", "budget_krw": 300000}
    places = [
        {"place_id": 592, "name": "올레길 1코스(시흥-광치기 올레)", "category": "여행 > 관광,명소 > 도보여행 > 올레길", "region": "제주특별자치도", "address": "제주특별자치도 서귀포시 성산읍 시흥리"},
        {"place_id": 612, "name": "시흥해녀의집", "category": "음식점 > 한식 > 해물,생선", "region": "제주특별자치도", "address": "제주특별자치도 서귀포시 성산읍 시흥리 12-64"},
        {"place_id": 613, "name": "제주김만복김밥 서귀포점", "category": "음식점 > 분식", "region": "제주특별자치도", "address": "제주특별자치도 서귀포시 강정동 428-4"},
    ]
    for place in places:
        place["is_anchor"] = place["place_id"] == anchor
    return trip, {"travel_style": "SLOW"}, [], ["CAFE"], {"raw_interest_codes": []}, places


def _jeju_plan(title="시흥해녀의집", place_id=613):
    return json.dumps({"days": [{"visit_date": "2026-10-27", "items": [
        {"sequence": 1, "item_type": "PLACE", "title": "올레길 1코스(시흥-광치기 올레)", "place_id": 592, "start_time": "09:00", "end_time": "12:00"},
        {"sequence": 2, "item_type": "PLACE", "title": title, "place_id": place_id, "start_time": "13:00", "end_time": "14:00"},
    ]}]}, ensure_ascii=False)


def test_trip86_exact_title_of_another_candidate_corrects_the_place_id(caplog):
    provider, _ = _provider(_jeju_plan())
    with caplog.at_level(logging.INFO):
        draft = provider.generate_plan(*_jeju_inputs())
    lunch = draft.days[0].items[1]
    assert (lunch.place_id, lunch.title, lunch.item_type) == (612, "시흥해녀의집", "MEAL")
    assert any("place_id corrected by exact title: model_place_id=613 corrected_place_id=612" in r.getMessage() for r in caplog.records)


def test_matching_title_and_id_are_left_alone():
    provider, _ = _provider(_jeju_plan(title="제주김만복김밥 서귀포점", place_id=613))
    draft = provider.generate_plan(*_jeju_inputs())
    assert draft.days[0].items[1].place_id == 613


def test_unmatched_or_partial_title_keeps_the_id_and_canonical_name():
    provider, _ = _provider(_jeju_plan(title="시흥해녀", place_id=613))
    draft = provider.generate_plan(*_jeju_inputs())
    assert (draft.days[0].items[1].place_id, draft.days[0].items[1].title) == (613, "제주김만복김밥 서귀포점")


def test_duplicated_candidate_name_is_never_used_to_change_the_id():
    trip, preferences, companions, interests, context, places = _jeju_inputs()
    places.append({"place_id": 700, "name": "시흥해녀의집", "category": "음식점 > 한식", "region": "제주특별자치도", "address": "제주특별자치도 서귀포시 성산읍 시흥리 1", "is_anchor": False})
    provider, _ = _provider(_jeju_plan())
    draft = provider.generate_plan(trip, preferences, companions, interests, context, places)
    assert draft.days[0].items[1].place_id == 613


def test_an_anchor_id_is_never_replaced_by_a_title_match():
    provider, _ = _provider(_jeju_plan())
    draft = provider.generate_plan(*_jeju_inputs(anchor=613))
    assert draft.days[0].items[1].place_id == 613
