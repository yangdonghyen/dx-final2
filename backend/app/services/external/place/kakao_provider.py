"""Kakao Local keyword-search adapter; no provider credentials are logged."""

import json
import socket
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from app.core.exceptions import AppError
from app.services.external.place.provider import PlaceCandidate
from app.services.external.place.region_resolver import RegionResolver, normalize_administrative_name


KAKAO_KEYWORD_ENDPOINT = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_CATEGORY_ENDPOINT = "https://dapi.kakao.com/v2/local/search/category.json"
KAKAO_ADDRESS_ENDPOINT = "https://dapi.kakao.com/v2/local/search/address.json"


_DIRECT_OPENER = build_opener(ProxyHandler({}))


def _urlopen_get(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    """Call Kakao directly, not through unrelated process proxy settings.

    Kakao Local credentials are sent only to the fixed HTTPS Kakao endpoint.
    A stale localhost HTTP(S)_PROXY otherwise turns a valid Kakao response
    into URLError before the provider can classify its HTTP status.
    """
    request = Request(url, headers=headers, method="GET")
    with _DIRECT_OPENER.open(request, timeout=timeout) as response:
        return response.status, response.read()


class KakaoPlaceProvider:
    def __init__(self, api_key: str, timeout: float, http_get: Callable[[str, dict[str, str], float], tuple[int, bytes]] | None = None, region_resolver: RegionResolver | None = None):
        self.api_key = api_key
        self.timeout = timeout
        self.http_get = http_get or _urlopen_get
        self.regions = region_resolver or RegionResolver()

    def _request(self, query: str, rectangle: tuple[float, float, float, float] | None) -> list[PlaceCandidate]:
        if not self.api_key:
            raise AppError("KAKAO_API_KEY_NOT_CONFIGURED", "Kakao API key is not configured", 503)
        params = {"query": query, "size": 15}
        if rectangle is not None:
            params["rect"] = ",".join(f"{value:.12f}" for value in rectangle)
        try:
            status, body = self.http_get(f"{KAKAO_KEYWORD_ENDPOINT}?{urlencode(params)}", {"Authorization": f"KakaoAK {self.api_key}"}, self.timeout)
        except HTTPError as error:
            status, body = error.code, b""
        except (TimeoutError, socket.timeout):
            raise AppError("KAKAO_TIMEOUT", "Kakao place search timed out", 504) from None
        except URLError:
            raise AppError("KAKAO_NETWORK_ERROR", "Kakao place search is unavailable", 502) from None
        if status in {401, 403}:
            raise AppError("KAKAO_AUTH_FAILED", "Kakao API authentication failed", 502)
        if status == 429:
            raise AppError("KAKAO_RATE_LIMITED", "Kakao API rate limit exceeded", 429)
        if status >= 500:
            raise AppError("KAKAO_SERVER_ERROR", "Kakao place search failed", 502)
        if status < 200 or status >= 300:
            raise AppError("KAKAO_API_ERROR", "Kakao place search failed", 502)
        try:
            payload = json.loads(body.decode("utf-8"))
            documents = payload["documents"]
            if not isinstance(documents, list):
                raise ValueError
            return [self._candidate(document) for document in documents]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise AppError("KAKAO_MALFORMED_RESPONSE", "Kakao returned an invalid place response", 502) from None

    @staticmethod
    def _candidate(document: dict) -> PlaceCandidate:
        required = ("id", "place_name", "category_name", "address_name", "x", "y", "phone", "place_url")
        if not isinstance(document, dict) or any(field not in document for field in required):
            raise ValueError
        longitude, latitude = float(document["x"]), float(document["y"])
        if not document["id"] or not document["place_name"] or not document["address_name"]:
            raise ValueError
        road_address = document.get("road_address_name")
        if road_address is not None and not isinstance(road_address, str):
            raise ValueError
        return PlaceCandidate("KAKAO", str(document["id"]), str(document["place_name"]), str(document["category_name"]), str(document["address_name"]), latitude, longitude, str(document["phone"]) or None, str(document["place_url"]) or None, road_address or None)

    def search(self, query: str, region: str | None = None) -> list[PlaceCandidate]:
        if not isinstance(query, str) or not query.strip():
            raise AppError("INVALID_PROVIDER_INPUT", "query is required", 400)
        if region is not None and (not isinstance(region, str) or not region.strip()):
            raise AppError("INVALID_PROVIDER_INPUT", "region must not be blank", 400)
        search_query = self.regions.search_query(query.strip(), region)
        candidates = [candidate for rectangle in self.regions.grid_rectangles(region) for candidate in self._request(search_query, rectangle)]
        unique, seen = [], set()
        for candidate in candidates:
            if candidate.external_id not in seen:
                seen.add(candidate.external_id)
                unique.append(candidate)
        return self.regions.filter(unique, region)

    def resolve_region(self, destination: str) -> tuple[float, float]:
        """Resolve an explicitly named administrative region to WGS84 coordinates.

        Keyword results identify businesses and attractions, so they are not safe
        representatives of a trip destination.  This deliberately accepts only
        Kakao address-search results classified as a region whose normalized
        administrative name exactly matches the requested destination.
        """
        if not isinstance(destination, str) or not destination.strip():
            raise AppError("INVALID_DESTINATION", "destination is required", 400)
        if not self.api_key:
            raise AppError("KAKAO_API_KEY_NOT_CONFIGURED", "Kakao API key is not configured", 503)

        destination = destination.strip()
        try:
            status, body = self.http_get(
                f"{KAKAO_ADDRESS_ENDPOINT}?{urlencode({'query': destination, 'analyze_type': 'exact'})}",
                {"Authorization": f"KakaoAK {self.api_key}"},
                self.timeout,
            )
        except HTTPError as error:
            status, body = error.code, b""
        except (TimeoutError, socket.timeout):
            raise AppError("KAKAO_TIMEOUT", "Kakao address search timed out", 504) from None
        except URLError:
            raise AppError("KAKAO_NETWORK_ERROR", "Kakao address search is unavailable", 502) from None

        if status in {401, 403}:
            raise AppError("KAKAO_AUTH_FAILED", "Kakao API authentication failed", 502)
        if status == 429:
            raise AppError("KAKAO_RATE_LIMITED", "Kakao API rate limit exceeded", 429)
        if status >= 500:
            raise AppError("KAKAO_SERVER_ERROR", "Kakao address search failed", 502)
        if status < 200 or status >= 300:
            raise AppError("KAKAO_API_ERROR", "Kakao address search failed", 502)

        try:
            documents = json.loads(body.decode("utf-8"))["documents"]
            matches = []
            for document in documents:
                if not isinstance(document, dict) or document.get("address_type") != "REGION":
                    continue
                address_name = document.get("address_name")
                longitude = float(document["x"])
                latitude = float(document["y"])
                if (
                    isinstance(address_name, str)
                    and normalize_administrative_name(address_name) == normalize_administrative_name(destination)
                    and -90 <= latitude <= 90
                    and -180 <= longitude <= 180
                ):
                    matches.append((latitude, longitude))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise AppError("KAKAO_MALFORMED_RESPONSE", "Kakao returned an invalid address response", 502) from None

        unique = list(dict.fromkeys(matches))
        if len(unique) != 1:
            raise AppError("DESTINATION_COORDINATES_NOT_FOUND", "Destination coordinates could not be verified", 404)
        return unique[0]

    def search_nearby(self, latitude: float, longitude: float, radius_meters: int, category_codes: list[str], limit_per_category: int) -> list[PlaceCandidate]:
        if not self.api_key:
            raise AppError("KAKAO_API_KEY_NOT_CONFIGURED", "Kakao API key is not configured", 503)
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise AppError("INVALID_PROVIDER_INPUT", "valid coordinates are required", 400)
        if not isinstance(radius_meters, int) or radius_meters < 1 or radius_meters > 20000:
            raise AppError("INVALID_PROVIDER_INPUT", "radius_meters is invalid", 400)
        if not isinstance(limit_per_category, int) or not 1 <= limit_per_category <= 15:
            raise AppError("INVALID_PROVIDER_INPUT", "limit_per_category is invalid", 400)
        if not isinstance(category_codes, list) or not category_codes or any(not isinstance(code, str) or not code.strip() for code in category_codes):
            raise AppError("INVALID_PROVIDER_INPUT", "category_codes are required", 400)
        candidates = []
        for category_code in dict.fromkeys(category_codes):
            params = {"category_group_code": category_code, "x": f"{longitude:.12f}", "y": f"{latitude:.12f}", "radius": radius_meters, "size": limit_per_category, "sort": "distance"}
            try:
                status, body = self.http_get(f"{KAKAO_CATEGORY_ENDPOINT}?{urlencode(params)}", {"Authorization": f"KakaoAK {self.api_key}"}, self.timeout)
            except HTTPError as error:
                status, body = error.code, b""
            except (TimeoutError, socket.timeout):
                raise AppError("KAKAO_TIMEOUT", "Kakao place search timed out", 504) from None
            except URLError:
                raise AppError("KAKAO_NETWORK_ERROR", "Kakao place search is unavailable", 502) from None
            if status in {401, 403}:
                raise AppError("KAKAO_AUTH_FAILED", "Kakao API authentication failed", 502)
            if status == 429:
                raise AppError("KAKAO_RATE_LIMITED", "Kakao API rate limit exceeded", 429)
            if status >= 500:
                raise AppError("KAKAO_SERVER_ERROR", "Kakao place search failed", 502)
            if status < 200 or status >= 300:
                raise AppError("KAKAO_API_ERROR", "Kakao place search failed", 502)
            try:
                payload = json.loads(body.decode("utf-8"))
                documents = payload["documents"]
                if not isinstance(documents, list):
                    raise ValueError
                candidates.extend(self._candidate(document) for document in documents)
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                raise AppError("KAKAO_MALFORMED_RESPONSE", "Kakao returned an invalid place response", 502) from None
        unique, seen = [], set()
        for candidate in candidates:
            if candidate.external_id not in seen:
                seen.add(candidate.external_id)
                unique.append(candidate)
        return unique
