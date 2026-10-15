"""Sanitised EXAONE plan responses for replay tests (opt-in capture).

A fixture keeps exactly what the parser decides on, and nothing personal:

* trip dates are rebased to ``FIXTURE_START_DATE`` (only day offsets remain);
* each item keeps ``sequence``, ``item_type``, ``place_id``, ``start_time``,
  ``end_time`` and a title that passes an allow-list: a supplied candidate's
  exact name, a generic interval word, or a candidate name followed only by
  allow-listed activity words.  Any other title becomes ``REDACTED_TITLE``
  (it can neither match a candidate nor count as a generic interval, so the
  parser's decision for that item is unchanged);
* candidates keep public place facts only (id, name, category, region,
  coordinates, anchor flag, opening hours);
* the request payload, prompts, companions, user ids, preferences and the
  model's free text are never stored.  An answer that is not JSON keeps only
  its error marker.

Capture runs only when ``PLAN_AI_FIXTURE_DIR`` is set (default: off) and never
affects generation: every failure is logged and ignored.
"""

import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FIXTURE_VERSION = 1
FIXTURE_START_DATE = date(2030, 1, 7)
REDACTED_TITLE = "REDACTED_TITLE"
SOURCE_CAPTURED = "captured"
SOURCE_SYNTHETIC = "synthetic"
CANDIDATE_KEYS = ("place_id", "name", "category", "region", "latitude", "longitude", "is_anchor", "opening_hours")

# Generic interval titles (kept verbatim) and activity words that may follow a
# candidate name ("애월해안도로 드라이브").  Shared with the parser so a fixture
# keeps every title the parser could act on.
GENERIC_INTERVAL_TITLES = frozenset({
    "rest", "freetime", "traveltime", "travel", "transfer",
    "휴식", "휴식시간", "자유시간", "이동", "이동시간", "이동중",
})
ACTIVITY_WORDS = frozenset({"드라이브", "산책", "휴식", "구경", "관람", "감상", "걷기", "쉬기", "실내"})
ITEM_TYPES = frozenset({"PLACE", "MEAL", "REST", "FREE_TIME"})
_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def _safe_item(item: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """Only typed values survive; free text never does (invalid values keep failing)."""
    def integer(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def clock(value):
        return value if isinstance(value, str) and _TIME.match(value) else "INVALID_TIME"

    item_type = item.get("item_type")
    return {
        "sequence": integer(item.get("sequence")),
        "item_type": item_type if item_type in ITEM_TYPES else "INVALID_TYPE",
        "place_id": integer(item.get("place_id")),
        "start_time": clock(item.get("start_time")),
        "end_time": clock(item.get("end_time")),
        "title": _safe_title(item.get("title"), names),
    }


def compact(value: str) -> str:
    return "".join(value.casefold().split())


def normalized_name(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def activity_suffix(title: str, name: str) -> list[str] | None:
    """Activity words after a candidate's exact name, or None when the title is anything else."""
    title, name = normalized_name(title), normalized_name(name)
    if not name or not title.startswith(f"{name} "):
        return None
    # "강릉시립미술관 교동 (실내 휴식)" (heat proposal, 2026-10-15): brackets
    # around the activity words are only punctuation.
    words = re.sub(r"[()\[\]·,]", " ", title[len(name):]).split()
    return words if words and all(word in ACTIVITY_WORDS for word in words) else None


def _safe_title(title: Any, names: list[str]) -> str:
    if not isinstance(title, str):
        return REDACTED_TITLE
    if normalized_name(title) in {normalized_name(name) for name in names}:
        return normalized_name(title)
    if compact(title) in GENERIC_INTERVAL_TITLES:
        return title.strip()
    if any(activity_suffix(title, name) is not None for name in names):
        return normalized_name(title)
    return REDACTED_TITLE


def sanitize(content: Any, start_date: date, end_date: date, candidates: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """The parser-relevant, non-personal part of one model answer."""
    names = [candidate.get("name") for candidate in candidates.values() if isinstance(candidate.get("name"), str)]
    offset = (FIXTURE_START_DATE - start_date).days

    def shift(value: Any) -> Any:
        try:
            return (date.fromisoformat(value) + timedelta(days=offset)).isoformat()
        except (TypeError, ValueError):
            return None

    try:
        payload = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("days"), list):
        days = None
    else:
        days = []
        for row in payload["days"]:
            if not isinstance(row, dict):
                days.append(None)
                continue
            items = row.get("items") if isinstance(row.get("items"), list) else []
            days.append({
                "visit_date": shift(row.get("visit_date")),
                "items": [_safe_item(item, names) if isinstance(item, dict) else None for item in items],
            })
    return {
        "version": FIXTURE_VERSION,
        "trip": {"start_date": FIXTURE_START_DATE.isoformat(), "end_date": (FIXTURE_START_DATE + timedelta(days=(end_date - start_date).days)).isoformat()},
        "candidates": [
            {key: candidate.get(key) for key in CANDIDATE_KEYS if key in candidate}
            for _, candidate in sorted(candidates.items())
        ],
        "response": {"days": days} if days is not None else {"unparseable": True},
    }


def capture(directory: str | None, *, content: Any, start_date: date, end_date: date,
            candidates: dict[int, dict[str, Any]], outcome: str, error_code: str | None,
            validation_reason: str | None, regeneration: bool) -> Path | None:
    """Write one sanitised fixture when capture is enabled; never raises."""
    if not directory:
        return None
    try:
        fixture = sanitize(content, start_date, end_date, candidates)
        fixture.update(
            source=SOURCE_CAPTURED,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            kind="regeneration" if regeneration else "generation",
            expected={"outcome": outcome, "error_code": error_code, "validation_reason": validation_reason},
        )
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{fixture['captured_at'][:10]}-{outcome}-{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.info("plan_ai_fixture_captured path=%s outcome=%s reason=%s", path.name, outcome, validation_reason)
        return path
    except Exception as error:  # capture is diagnostic only
        logger.info("plan_ai_fixture_capture_failed error=%s", type(error).__name__)
        return None


def replay_inputs(fixture: dict[str, Any]) -> tuple[dict[str, Any], date, date, dict[int, dict[str, Any]]]:
    """(Ollama-shaped response, start, end, candidate map) for ``_parse``."""
    response = fixture["response"]
    content = "{not json" if response.get("unparseable") else json.dumps(response, ensure_ascii=False)
    candidates = {row["place_id"]: dict(row) for row in fixture["candidates"]}
    return (
        {"message": {"content": content}},
        date.fromisoformat(fixture["trip"]["start_date"]),
        date.fromisoformat(fixture["trip"]["end_date"]),
        candidates,
    )
