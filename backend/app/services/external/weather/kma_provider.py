"""KMA short-forecast adapter and deterministic forecast helpers."""

from __future__ import annotations

import json
import math
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import AppError


try:
    SEOUL = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    # Windows development environments may not ship IANA tzdata. Korea has no
    # daylight-saving transition, so this preserves the required KST behavior.
    SEOUL = timezone(timedelta(hours=9), name="Asia/Seoul")
_BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
# resultCode 03 (NO_DATA): the newest issue is not served yet even after the
# 30-minute lag.  Seen on 2026-10-14: 14:00 and 11:00 both NO_DATA while 08:00
# answered, so up to three earlier issues (3 hours apart) are tried.
KMA_NO_DATA = "03"
PREVIOUS_ISSUE = timedelta(hours=3)
NO_DATA_FALLBACK_ISSUES = 3


class _NoData(Exception):
    pass


def latest_short_forecast_base(now: datetime | None = None) -> datetime:
    """Return the latest KST short-forecast issue time, with a 30-minute lag."""
    current = (now or datetime.now(SEOUL)).astimezone(SEOUL) - timedelta(minutes=30)
    candidates = [current.replace(hour=hour, minute=0, second=0, microsecond=0) for hour in _BASE_HOURS]
    available = [candidate for candidate in candidates if candidate <= current]
    if available:
        return available[-1]
    return (current - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)


def latlon_to_kma_grid(latitude: float, longitude: float) -> tuple[int, int]:
    """Convert WGS84 latitude/longitude to the KMA DFS Lambert grid."""
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("latitude and longitude must be valid WGS84 coordinates")
    re, grid, slat1, slat2, olon, olat, xo, yo = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43.0, 136.0
    deg = math.pi / 180.0
    sn = math.tan(math.pi * 0.25 + slat2 * deg * 0.5) / math.tan(math.pi * 0.25 + slat1 * deg * 0.5)
    sn = math.log(math.cos(slat1 * deg) / math.cos(slat2 * deg)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * deg * 0.5) ** sn * math.cos(slat1 * deg) / sn
    ro = math.tan(math.pi * 0.25 + olat * deg * 0.5) ** sn
    ro = re / grid * sf / ro
    ra = math.tan(math.pi * 0.25 + latitude * deg * 0.5) ** sn
    ra = re / grid * sf / ra
    theta = longitude * deg - olon * deg
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    return int(math.floor(ra * math.sin(theta) + xo + 0.5)), int(math.floor(ro - ra * math.cos(theta) + yo + 0.5))


def condition_from_codes(pty: str | None, sky: str | None) -> str | None:
    precipitation = {"1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}
    if pty in precipitation:
        return precipitation[pty]
    return {"1": "맑음", "3": "구름많음", "4": "흐림"}.get(sky)


@dataclass(frozen=True)
class KmaForecast:
    base_at: datetime
    items: list[dict]


class KmaProvider:
    def __init__(self, api_key: str, base_url: str, timeout: float):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def short_forecast(self, nx: int, ny: int, now: datetime | None = None) -> KmaForecast:
        if not self.api_key:
            raise AppError("KMA_API_KEY_NOT_CONFIGURED", "KMA API key is not configured", 503)
        if not self.base_url:
            raise AppError("KMA_API_BASE_URL_NOT_CONFIGURED", "KMA API base URL is not configured", 503)
        base_at = latest_short_forecast_base(now)
        for step in range(NO_DATA_FALLBACK_ISSUES + 1):
            issue = base_at - PREVIOUS_ISSUE * step
            try:
                return KmaForecast(base_at=issue, items=self._items(nx, ny, issue))
            except _NoData:
                continue
        raise AppError("KMA_NO_DATA", "KMA has no forecast for this time yet", 502)

    def _items(self, nx: int, ny: int, base_at: datetime) -> list[dict]:
        key_name = "authKey" if "apihub.kma.go.kr" in self.base_url else "serviceKey"
        params = {
            key_name: self.api_key, "pageNo": 1, "numOfRows": 1000,
            "dataType": "JSON", "base_date": base_at.strftime("%Y%m%d"),
            "base_time": base_at.strftime("%H%M"), "nx": nx, "ny": ny,
        }
        try:
            request = Request(f"{self.base_url}/getVilageFcst?{urlencode(params)}", method="GET")
            with urlopen(request, timeout=self.timeout) as response:
                status, body = response.status, response.read()
        except HTTPError as error:
            status, body = error.code, error.read()
        except (TimeoutError, socket.timeout):
            raise AppError("KMA_TIMEOUT", "KMA forecast request timed out", 504) from None
        except URLError:
            raise AppError("KMA_NETWORK_ERROR", "KMA forecast service is unavailable", 502) from None
        if status >= 500:
            raise AppError("KMA_SERVER_ERROR", "KMA forecast service failed", 502)
        if status < 200 or status >= 300:
            raise AppError("KMA_API_ERROR", "KMA forecast request failed", 502)
        try:
            payload = json.loads(body.decode("utf-8"))
            response = payload["response"]
            header = response["header"]
            if str(header.get("resultCode")) == KMA_NO_DATA:
                raise _NoData
            if str(header.get("resultCode")) != "00":
                raise AppError("KMA_RESULT_ERROR", "KMA forecast request was rejected", 502)
            items = response["body"]["items"]["item"]
            if not isinstance(items, list):
                raise ValueError
        except (AppError, _NoData):
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise AppError("KMA_MALFORMED_RESPONSE", "KMA returned an invalid forecast response", 502) from None
        return items
