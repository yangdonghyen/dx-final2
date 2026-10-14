"""TC-08: KMA answered resultCode 03 (NO_DATA) for the 11:00 issue and the app got a 502."""

import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest

import app.services.external.weather.kma_provider as kma
from app.core.exceptions import AppError

NOW = datetime(2026, 10, 14, 11, 40, tzinfo=kma.SEOUL)  # newest issue: 11:00


class Response:
    def __init__(self, code):
        self.status = 200
        items = {"item": [{"category": "TMP", "fcstValue": "20"}]} if code == "00" else {}
        self.body = json.dumps({"response": {"header": {"resultCode": code}, "body": {"items": items}}}).encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *_): return False


def provider(monkeypatch, codes):
    asked = []
    def urlopen(request, timeout):
        asked.append(parse_qs(urlparse(request.full_url).query)["base_time"][0])
        return Response(codes[len(asked) - 1])
    monkeypatch.setattr(kma, "urlopen", urlopen)
    return kma.KmaProvider("key", "http://kma.test", 3), asked


def test_no_data_falls_back_to_the_previous_issue(monkeypatch):
    weather, asked = provider(monkeypatch, ["03", "00"])
    forecast = weather.short_forecast(60, 127, NOW)
    assert asked == ["1100", "0800"] and forecast.base_at.hour == 8 and forecast.items


def test_real_case_two_missing_issues_use_the_third(monkeypatch):
    # 2026-10-14 15:2x: 14:00 and 11:00 were NO_DATA, 08:00 answered.
    weather, asked = provider(monkeypatch, ["03", "03", "00"])
    assert weather.short_forecast(60, 127, NOW.replace(hour=15, minute=20)).base_at.hour == 8
    assert asked == ["1400", "1100", "0800"]


def test_no_data_everywhere_is_a_clear_error_after_four_calls(monkeypatch):
    weather, asked = provider(monkeypatch, ["03"] * 4)
    with pytest.raises(AppError) as error: weather.short_forecast(60, 127, NOW)
    assert error.value.code == "KMA_NO_DATA" and asked == ["1100", "0800", "0500", "0200"]


def test_other_rejections_are_not_retried(monkeypatch):
    weather, asked = provider(monkeypatch, ["30"])
    with pytest.raises(AppError) as error: weather.short_forecast(60, 127, NOW)
    assert error.value.code == "KMA_RESULT_ERROR" and asked == ["1100"]
