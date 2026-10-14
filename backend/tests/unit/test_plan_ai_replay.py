"""Replay EXAONE plan answers through the real parser without calling the model.

Fixtures live in tests/fixtures/plan_ai/<source>/ where <source> is
``synthetic`` (hand-written from logs; no raw answer existed) or ``captured``
(sanitised by plan_ai_fixture.capture with PLAN_AI_FIXTURE_DIR, then reviewed
and copied in).  Each fixture states its expected outcome.
"""

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from app.core.exceptions import AppError
from app.services.external.ai import plan_ai_fixture
from app.services.external.ai.exaone_plan_provider import ExaonePlanGenerationProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plan_ai"
ALL = sorted(FIXTURES.glob("*/*.json"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse(fixture):
    response, start, end, candidates = plan_ai_fixture.replay_inputs(fixture)
    return ExaonePlanGenerationProvider._parse(response, start, end, candidates, {}, [], None, [])


@pytest.mark.parametrize("path", ALL, ids=[f"{p.parent.name}/{p.stem}" for p in ALL])
def test_fixture_replays_to_its_expected_outcome(path):
    fixture = load(path)
    assert fixture["source"] == path.parent.name  # synthetic and captured never mix
    expected = fixture["expected"]
    if expected["outcome"] == "rejected":
        with pytest.raises(AppError) as error:
            parse(fixture)
        assert error.value.code == "EXAONE_INVALID_RESPONSE"
        if expected.get("validation_reason"):
            assert error.value.validation_reason == expected["validation_reason"]
        return
    draft = parse(fixture)
    if "items" in expected:
        assert [[item.place_id, item.item_type] for day in draft.days for item in day.items if item.place_id is not None] == expected["items"]


def test_trip94_shape_failed_under_the_previous_rule(monkeypatch):
    """The synthetic trip 94 answer reproduces the original 502 without the activity rule."""
    fixture = load(FIXTURES / "synthetic" / "trip94_rest_place_drive.json")
    monkeypatch.setattr(plan_ai_fixture, "activity_suffix", lambda *_args: None)
    with pytest.raises(AppError) as error:
        parse(fixture)
    assert error.value.validation_reason == "non_place_item_has_place_id"


def test_trip94_shape_keeps_the_verified_visit_and_logs_the_purpose(caplog):
    fixture = load(FIXTURES / "synthetic" / "trip94_rest_place_drive.json")
    with caplog.at_level(logging.INFO):
        draft = parse(fixture)
    visit = next(item for item in draft.days[0].items if item.place_id == 211)
    assert (visit.item_type, visit.title) == ("PLACE", "애월해안도로")  # verified name, category type
    message = next(r.getMessage() for r in caplog.records if "type_corrected_activity" in r.getMessage())
    assert "'activity': ['드라이브']" in message


# --- sanitising and opt-in capture --------------------------------------------------------

CANDIDATES = {
    211: {"place_id": 211, "name": "애월해안도로", "category": "드라이브코스", "is_anchor": False,
          "latitude": 33.47, "longitude": 126.36, "address": "제주 애월읍", "secret": "x"},
}
ANSWER = json.dumps({"days": [{"visit_date": "2026-10-26", "items": [
    {"sequence": 1, "item_type": "REST", "title": "엄마랑 애월에서 쉬기", "place_id": 211,
     "start_time": "09:00", "end_time": "10:00", "recommendation_reason": "엄마 생신 여행"},
    {"sequence": 2, "item_type": "PLACE", "title": "애월해안도로 드라이브", "place_id": 211,
     "start_time": "10:00", "end_time": "11:00", "note": "010-1234-5678"},
    {"sequence": 3, "item_type": "FREE_TIME", "title": "자유 시간", "place_id": None,
     "start_time": "lunch-ish", "end_time": "12:00"},
]}]}, ensure_ascii=False)


def test_sanitize_keeps_only_parser_facts_and_no_personal_text():
    fixture = plan_ai_fixture.sanitize(ANSWER, date(2026, 10, 26), date(2026, 10, 28), CANDIDATES)
    text = json.dumps(fixture, ensure_ascii=False)
    for personal in ("엄마", "생신", "010-1234-5678", "2026-10", "제주 애월읍", "secret"):
        assert personal not in text
    items = fixture["response"]["days"][0]["items"]
    assert [item["title"] for item in items] == [plan_ai_fixture.REDACTED_TITLE, "애월해안도로 드라이브", "자유 시간"]
    assert set(items[0]) == {"sequence", "item_type", "place_id", "start_time", "end_time", "title"}
    assert items[2]["start_time"] == "INVALID_TIME"  # an invalid value keeps failing the same way
    assert fixture["trip"] == {"start_date": "2030-01-07", "end_date": "2030-01-09"}
    assert fixture["response"]["days"][0]["visit_date"] == "2030-01-07"


def test_non_json_answer_keeps_only_a_marker():
    fixture = plan_ai_fixture.sanitize("엄마랑 여행 {", date(2026, 10, 26), date(2026, 10, 26), CANDIDATES)
    assert fixture["response"] == {"unparseable": True} and "엄마" not in json.dumps(fixture, ensure_ascii=False)


def test_capture_is_off_by_default_and_writes_a_replayable_fixture_when_enabled(tmp_path):
    common = dict(content=ANSWER, start_date=date(2026, 10, 26), end_date=date(2026, 10, 26),
                  candidates=CANDIDATES, outcome="rejected", error_code="EXAONE_INVALID_RESPONSE",
                  validation_reason="non_place_item_has_place_id", regeneration=False)
    assert plan_ai_fixture.capture(None, **common) is None

    path = plan_ai_fixture.capture(str(tmp_path), **common)
    fixture = load(path)
    assert fixture["source"] == "captured" and fixture["expected"]["outcome"] == "rejected"
    with pytest.raises(AppError) as error:
        parse(fixture)
    assert error.value.validation_reason == "non_place_item_has_place_id"


def test_capture_never_breaks_generation(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a folder")
    assert plan_ai_fixture.capture(str(blocked), content=ANSWER, start_date=date(2026, 10, 26),
                                   end_date=date(2026, 10, 26), candidates=CANDIDATES, outcome="accepted",
                                   error_code=None, validation_reason=None, regeneration=False) is None


def test_parser_and_fixture_share_the_generic_interval_words():
    for word in plan_ai_fixture.GENERIC_INTERVAL_TITLES:
        assert ExaonePlanGenerationProvider._is_explicit_non_place_title(word)
