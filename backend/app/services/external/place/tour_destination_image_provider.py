"""TourAPI adapter for destination image candidates."""

import json
import logging
import re
import socket
from html import unescape
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


@dataclass
class DestinationImageCandidate:
    title: str
    address: str | None
    image_url: str
    content_id: str
    content_type_id: str | None = None
    cat1: str | None = None
    cat2: str | None = None
    cat3: str | None = None
    map_x: float | None = None
    map_y: float | None = None


class TourDestinationImageProvider:
    def __init__(self, api_key: str, base_url: str, timeout: float):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_sampled_page_numbers: list[int] = []
        self.last_total_count: int | None = None

    def _get_json(self, endpoint: str, params: dict) -> dict:
        if not self.api_key:
            raise AppError(
                "TOUR_API_KEY_NOT_CONFIGURED",
                "Tour API key is not configured",
                503,
            )

        if not self.base_url:
            raise AppError(
                "TOUR_API_BASE_URL_NOT_CONFIGURED",
                "Tour API base URL is not configured",
                503,
            )

        common = {
            "serviceKey": self.api_key,
            "MobileOS": "ETC",
            "MobileApp": "TravelMate",
            "_type": "json",
        }

        query = {**common, **params}
        url = f"{self.base_url}/{endpoint}?{urlencode(query)}"

        request = Request(url, method="GET")

        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                content_type = response.headers.get("Content-Type")
                body = response.read()
        except HTTPError as error:
            status = error.code
            content_type = error.headers.get("Content-Type") if error.headers else None
            try:
                body = error.read()
            except OSError:
                body = b""
        except (TimeoutError, socket.timeout):
            self._log_detail_response(
                endpoint, params, "timeout", None, "request timed out"
            )
            raise AppError(
                "TOUR_API_TIMEOUT",
                "Tour API request timed out",
                504,
            ) from None
        except URLError:
            self._log_detail_response(
                endpoint, params, "network_error", None, "network unavailable"
            )
            raise AppError(
                "TOUR_API_NETWORK_ERROR",
                "Tour API is unavailable",
                502,
            ) from None

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._log_json_decode_failure(
                endpoint, params, status, content_type, error, body
            )
            if status >= 500:
                raise AppError(
                    "TOUR_API_SERVER_ERROR",
                    "Tour API request failed",
                    502,
                ) from None
            if status < 200 or status >= 300:
                raise AppError(
                    "TOUR_API_ERROR",
                    "Tour API request failed",
                    502,
                ) from None
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None

        self._log_detail_shape(
            endpoint, params, status, content_type, payload
        )
        if not isinstance(payload, dict):
            self._log_detail_parse_failure(
                endpoint,
                params,
                "response_envelope",
                TypeError,
                "JSON payload must be an object",
            )
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None

        response_data = payload.get("response") or payload
        if not isinstance(response_data, dict):
            self._log_detail_parse_failure(
                endpoint,
                params,
                "response_envelope",
                TypeError,
                "response must be an object",
            )
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None

        header = response_data.get("header") or {}
        if not isinstance(header, dict):
            self._log_detail_parse_failure(
                endpoint,
                params,
                "response_header",
                TypeError,
                "header must be an object",
            )
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None

        raw_result_code = header.get("resultCode")
        result_code = str(raw_result_code) if raw_result_code is not None else None
        result_message = header.get("resultMsg")

        self._log_detail_response(
            endpoint, params, status, result_code, result_message
        )

        if status >= 500:
            raise AppError(
                "TOUR_API_SERVER_ERROR",
                "Tour API request failed",
                502,
            )

        if status < 200 or status >= 300:
            raise AppError(
                "TOUR_API_ERROR",
                "Tour API request failed",
                502,
            )

        if result_code is not None and result_code not in {"0000", "00"}:
            raise AppError(
                "TOUR_API_RESULT_ERROR",
                f"Tour API returned resultCode={result_code}",
                502,
            )

        return payload

    def _redact_log_text(self, value: str) -> str:
        safe = value
        if self.api_key:
            safe = safe.replace(self.api_key, "[REDACTED]")
            safe = safe.replace(quote_plus(self.api_key), "[REDACTED]")
        safe = re.sub(
            r"(?i)(['\"]?service[_]?key['\"]?\s*[=:]\s*['\"]?)[^&\s,'\"}]+",
            r"\1[REDACTED]",
            safe,
        )
        return safe.replace("\r", " ").replace("\n", " ")

    def _safe_log_value(self, value):
        if isinstance(value, dict):
            return {
                str(key): (
                    "[REDACTED]"
                    if re.search(r"(?i)(key|secret|token|authorization)", str(key))
                    else self._safe_log_value(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._safe_log_value(item) for item in value]
        if isinstance(value, str):
            return self._redact_log_text(value)
        return value

    def _log_json_decode_failure(
        self, endpoint, params, status, content_type, error, body
    ) -> None:
        if not endpoint.startswith("detail"):
            return
        try:
            body_head = body[:500].decode("utf-8", errors="replace")
        except Exception:
            body_head = "<unavailable>"
        logger.warning(
            "[TourAPI Detail] stage=json_decode content_id=%s status=%s "
            "content_type=%s error_type=%s body_head=%s",
            params.get("contentId", "-"),
            status,
            self._redact_log_text(str(content_type or "-")),
            type(error).__name__,
            self._redact_log_text(body_head),
        )

    def _log_detail_parse_failure(
        self, endpoint, params, stage, error_type, message
    ) -> None:
        if not endpoint.startswith("detail"):
            return
        logger.warning(
            "[TourAPI Detail] stage=parse_%s content_id=%s "
            "error_type=%s message=%s",
            stage,
            params.get("contentId", "-"),
            getattr(error_type, "__name__", str(error_type)),
            self._redact_log_text(str(message))[:240],
        )

    def _log_detail_shape(self, endpoint, params, status, content_type, payload):
        if not endpoint.startswith("detail"):
            return
        top_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        response_exists = isinstance(payload, dict) and "response" in payload

        if isinstance(payload, dict) and "response" not in payload:
            logger.warning(
                "[TourAPI Detail] stage=top_level_error "
                "endpoint=%s content_id=%s resultCode=%s resultMsg=%s",
                endpoint,
                params.get("contentId"),
                payload.get("resultCode"),
                payload.get("resultMsg"),
            )

        logger.info(
            "[TourAPI Detail] stage=top_level_result "
            "endpoint=%s content_id=%s resultCode=%s resultMsg=%s",
            endpoint,
            params.get("contentId"),
            payload.get("resultCode") if isinstance(payload, dict) else None,
            payload.get("resultMsg") if isinstance(payload, dict) else None,
        )
        response_data = (payload.get("response") or payload) if isinstance(payload, dict) else None
        header = response_data.get("header") if isinstance(response_data, dict) else None
        body_data = response_data.get("body") if isinstance(response_data, dict) else None
        body_keys = sorted(body_data.keys()) if isinstance(body_data, dict) else []
        items = body_data.get("items") if isinstance(body_data, dict) else None
        item = items.get("item") if isinstance(items, dict) else None
        if isinstance(item, list):
            item_count = sum(isinstance(row, dict) for row in item)
        elif isinstance(item, dict):
            item_count = 1
        else:
            item_count = 0
        try:
            safe_header = json.dumps(
                self._safe_log_value(header), ensure_ascii=False, default=str
            )
        except (TypeError, ValueError):
            safe_header = repr(type(header).__name__)
        safe_header = self._redact_log_text(safe_header)[:500]
        logger.info(
            "[TourAPI Detail] stage=response_shape endpoint=%s content_id=%s "
            "status=%s content_type=%s json_decode=true top_keys=%s "
            "response_key_exists=%s header=%s body_keys=%s "
            "items_type=%s item_type=%s item_count=%s",
            endpoint,
            params.get("contentId", "-"),
            status,
            self._redact_log_text(str(content_type or "-")),
            top_keys,
            response_exists,
            safe_header,
            body_keys,
            type(items).__name__,
            type(item).__name__,
            item_count,
        )

    def _log_detail_response(
        self,
        endpoint: str,
        params: dict,
        status,
        result_code,
        result_message,
    ) -> None:
        if not endpoint.startswith("detail"):
            return
        message = self._redact_log_text(str(result_message or ""))[:240]
        log = (
            logger.warning
            if not isinstance(status, int)
            or status < 200
            or status >= 300
            or (result_code is not None and str(result_code) != "0000")
            else logger.info
        )
        log(
            "[TourAPI Detail] endpoint=%s content_id=%s status=%s "
            "resultCode=%s resultMsg=%s",
            endpoint,
            params.get("contentId", "-"),
            status,
            result_code or "-",
            message or "-",
        )

    def _area_rows(self, area_code: str | None = None) -> list[tuple[str, str]]:
        params = {"pageNo": 1, "numOfRows": 100}
        if area_code is not None:
            params["areaCode"] = area_code
        rows = self._response_rows(self._get_json("areaCode2", params))
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            code = str(row.get("code") or "").strip()
            if name and code:
                result.append((name, code))
        return result

    def _resolve_area_code(self, destination_name: str) -> tuple[str, str | None] | None:
        """(areaCode, sigunguCode) from TourAPI's own area lists, or None.

        Province-level names match by prefix (세종 -> 세종특별자치시). City-level
        names such as 수원 are looked up inside their known province.
        """
        from app.services.youtube_destination_resolver import YouTubeDestinationResolver

        destination = destination_name.strip()
        areas = self._area_rows()
        for name, code in areas:
            if name == destination:
                return code, None
        provinces = YouTubeDestinationResolver.PROVINCES.get(destination)
        if provinces is None:
            for name, code in areas:
                if len(destination) >= 2 and name.startswith(destination):
                    return code, None
            return None
        area_code = next(
            (code for name, code in areas if name.startswith(provinces)),
            None,
        )
        if area_code is None:
            return None
        sigungu_code = next(
            (code for name, code in self._area_rows(area_code) if name.startswith(destination)),
            None,
        )
        if sigungu_code is None:
            return None
        return area_code, sigungu_code

    @staticmethod
    def _response_rows(payload: dict) -> list[dict]:
        if not isinstance(payload, dict):
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None

        response = payload.get("response") or payload
        if not isinstance(response, dict):
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None

        header = response.get("header") or {}
        if isinstance(header, dict):
            code = header.get("resultCode")
            if code is not None and str(code) not in {"0000", "00"}:
                raise AppError(
                    "TOUR_API_RESULT_ERROR",
                    f"Tour API returned resultCode={code}",
                    502,
                )

        body = response.get("body") or {}
        if not isinstance(body, dict):
            return []
        items = body.get("items")
        if not items or not isinstance(items, dict):
            return []
        item = items.get("item")
        if item is None:
            return []
        if isinstance(item, dict):
            return [item]
        if isinstance(item, list):
            return [row for row in item if isinstance(row, dict)]
        return []

    @staticmethod
    def _normalize_image_url(url: str) -> str:
        value = url.strip()

        if value.startswith("http://tong.visitkorea.or.kr/"):
            return "https://" + value[len("http://"):]

        return value

    @staticmethod
    def _total_count(payload: dict) -> int:
        try:
            value = payload["response"]["body"]["totalCount"]
            total_count = int(value)
        except (KeyError, TypeError, ValueError):
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None

        if total_count < 0:
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            )

        return total_count

    @staticmethod
    def _sample_page_numbers(total_pages: int) -> list[int]:
        if total_pages <= 0:
            return []

        sample_count = min(total_pages, 5)
        if sample_count == total_pages:
            return list(range(1, total_pages + 1))

        # Include the first, last, and evenly-spaced interior pages without
        # assuming any destination-specific ordering of TourAPI results.
        return [
            1 + (index * (total_pages - 1)) // (sample_count - 1)
            for index in range(sample_count)
        ]

    def _candidate_rows(
        self,
        rows: list[dict],
        seen_content_ids: set[str],
    ) -> list[DestinationImageCandidate]:
        candidates = []

        for row in rows:
            if not isinstance(row, dict):
                continue

            title = str(row.get("title") or "").strip()
            image_url = str(row.get("firstimage") or "").strip()
            content_id = str(row.get("contentid") or "").strip()
            address = str(row.get("addr1") or "").strip() or None
            content_type_id = str(row.get("contenttypeid") or "").strip() or None
            cat1 = str(row.get("cat1") or "").strip() or None
            cat2 = str(row.get("cat2") or "").strip() or None
            cat3 = str(row.get("cat3") or "").strip() or None
            map_x = self._optional_float(row.get("mapx"))
            map_y = self._optional_float(row.get("mapy"))

            if (
                not title
                or not image_url
                or not content_id
                or content_id in seen_content_ids
            ):
                continue

            seen_content_ids.add(content_id)
            candidates.append(
                DestinationImageCandidate(
                    title=title,
                    address=address,
                    image_url=self._normalize_image_url(image_url),
                    content_id=content_id,
                    content_type_id=content_type_id,
                    cat1=cat1,
                    cat2=cat2,
                    cat3=cat3,
                    map_x=map_x,
                    map_y=map_y,
                )
            )

        return candidates

    @staticmethod
    def _optional_text(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _plain_overview(value) -> str | None:
        text = TourDestinationImageProvider._optional_text(value)
        if text is None:
            return None
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p\s*>", "\n", text)
        text = re.sub(r"<[^>]*>", "", text)
        text = unescape(text).strip()
        return text or None

    @staticmethod
    def _homepage(value) -> str | None:
        text = TourDestinationImageProvider._optional_text(value)
        if text is None:
            return None
        match = re.search(r'''href=["']([^"']+)["']''', text, flags=re.IGNORECASE)
        return unescape(match.group(1)).strip() if match else text

    @staticmethod
    def _optional_float(value) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number == number and abs(number) != float("inf") else None

    def _display_text(self, value) -> str | None:
        text = self._optional_text(value)
        if text is None:
            return None

        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)

        lines = [line.strip() for line in text.splitlines()]
        text = "\n".join(line for line in lines if line)

        return text.strip() or None
    def get_place_detail(
        self,
        content_id: str,
        content_type_id: int = 12,
        include_images: bool = True,
    ) -> dict:
        """Fetch verified place details from TourAPI common/intro/image data."""
        normalized_id = str(content_id).strip()
        if not normalized_id.isdigit():
            raise AppError("INVALID_TOUR_CONTENT_ID", "Invalid content id", 400)

        common_payload = self._get_json(
            "detailCommon2",
            {
                "contentId": normalized_id,
            },
        )
        try:
            common_rows = self._response_rows(common_payload)
        except AppError as error:
            if error.code != "TOUR_API_RESULT_ERROR":
                self._log_detail_parse_failure(
                    "detailCommon2",
                    {"contentId": normalized_id},
                    "common",
                    type(error),
                    error.code,
                )
            raise
        except Exception as error:
            self._log_detail_parse_failure(
                "detailCommon2",
                {"contentId": normalized_id},
                "common",
                type(error),
                error,
            )
            raise AppError(
                "TOUR_API_MALFORMED_RESPONSE",
                "Tour API returned an invalid response",
                502,
            ) from None
        if not common_rows or not isinstance(common_rows[0], dict):
            self._log_detail_parse_failure(
                "detailCommon2",
                {"contentId": normalized_id},
                "common",
                "EmptyResult",
                "no valid place item",
            )
            raise AppError("TOUR_PLACE_NOT_FOUND", "Tour place not found", 404)
        common = common_rows[0]
        returned_id = self._optional_text(common.get("contentid"))
        if returned_id != normalized_id:
            raise AppError("TOUR_PLACE_NOT_FOUND", "Tour place not found", 404)

        # A trusted content ID can represent an attraction, restaurant, or
        # another TourAPI type.  detailIntro2 requires that type, so prefer the
        # authoritative value returned by detailCommon2 over the legacy caller
        # default.  This is essential for restaurant hours.
        resolved_content_type_id = self._optional_int(common.get("contenttypeid")) or content_type_id
        intro: dict = {}
        try:
            intro_payload = self._get_json(
                "detailIntro2",
                {
                    "contentId": normalized_id,
                    "contentTypeId": resolved_content_type_id,
                },
            )
            intro_rows = self._response_rows(intro_payload)
            if intro_rows and isinstance(intro_rows[0], dict):
                intro = intro_rows[0]
        except AppError as error:
            # Common information remains useful when the optional intro call
            # is unavailable; unavailable values are represented as null.
            self._log_detail_parse_failure(
                "detailIntro2",
                {"contentId": normalized_id},
                "intro",
                type(error),
                error.code,
            )
            intro = {}
        except Exception as error:
            self._log_detail_parse_failure(
                "detailIntro2",
                {"contentId": normalized_id},
                "intro",
                type(error),
                error,
            )
            intro = {}

        image_url = self._optional_text(common.get("firstimage")) if include_images else None
        if image_url:
            image_url = self._normalize_image_url(image_url)
        elif include_images:
            try:
                image_payload = self._get_json(
                    "detailImage2",
                    {
                        "contentId": normalized_id,
                        "imageYN": "Y",
                        "subImageYN": "Y",
                    },
                )
                image_rows = self._response_rows(image_payload)
                for row in image_rows:
                    if isinstance(row, dict):
                        image_url = self._optional_text(row.get("originimgurl"))
                        if image_url:
                            image_url = self._normalize_image_url(image_url)
                            break
            except AppError as error:
                self._log_detail_parse_failure(
                    "detailImage2",
                    {"contentId": normalized_id},
                    "image",
                    type(error),
                    error.code,
                )
                image_url = None
            except Exception as error:
                self._log_detail_parse_failure(
                    "detailImage2",
                    {"contentId": normalized_id},
                    "image",
                    type(error),
                    error,
                )
                image_url = None

        return {
            "content_id": normalized_id,
            "content_type_id": resolved_content_type_id,
            "title": self._optional_text(common.get("title")),
            "address": self._optional_text(common.get("addr1")),
            "image_url": image_url,
            "overview": self._plain_overview(common.get("overview")),
            "homepage": self._homepage(common.get("homepage")),
            "map_x": self._optional_float(common.get("mapx")),
            "map_y": self._optional_float(common.get("mapy")),
            "cat1": self._optional_text(common.get("cat1")),
            "cat2": self._optional_text(common.get("cat2")),
            "cat3": self._optional_text(common.get("cat3")),
            "operating_hours": self._display_text(
                intro.get("usetime") or intro.get("usetimeculture")
            ),
            "rest_date": self._display_text(
                intro.get("restdate") or intro.get("restdateculture")
            ),
            "use_fee": self._display_text(
                intro.get("usefee") or intro.get("usefeeculture")
            ),
            "parking": self._display_text(intro.get("parking")),
            "info_center": self._display_text(
                intro.get("infocenter") or intro.get("infocenterculture")
            ),
        }

    @staticmethod
    def _optional_int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def search_candidates(
        self,
        destination_name: str,
        limit: int = 90,
    ) -> list[DestinationImageCandidate]:
        self.last_sampled_page_numbers = []
        self.last_total_count = None

        if not destination_name or not destination_name.strip():
            return []

        area = self._resolve_area_code(destination_name)

        if area is None:
            return []

        area_code, sigungu_code = area
        area_params = {"areaCode": area_code, "contentTypeId": 12}
        if sigungu_code is not None:
            area_params["sigunguCode"] = sigungu_code

        page_size = 100
        first_payload = self._get_json(
            "areaBasedList2",
            {
                "pageNo": 1,
                "numOfRows": page_size,
                **area_params,
            },
        )
        total_count = self._total_count(first_payload)
        total_pages = (total_count + page_size - 1) // page_size
        page_numbers = self._sample_page_numbers(total_pages)
        self.last_total_count = total_count
        self.last_sampled_page_numbers = page_numbers

        if not page_numbers:
            return []

        page_candidates: list[list[DestinationImageCandidate]] = []
        seen_content_ids: set[str] = set()

        for page_no in page_numbers:
            payload = (
                first_payload
                if page_no == 1
                else self._get_json(
                    "areaBasedList2",
                    {
                        "pageNo": page_no,
                        "numOfRows": page_size,
                        **area_params,
                    },
                )
            )

            rows = self._response_rows(payload)
            page_candidates.append(
                self._candidate_rows(rows, seen_content_ids)
            )

        # Interleave page candidates so the final limit does not silently
        # revert to a first-page/title-order bias.
        candidates = []
        row_index = 0
        while len(candidates) < limit:
            added = False
            for candidates_for_page in page_candidates:
                if row_index < len(candidates_for_page):
                    candidates.append(candidates_for_page[row_index])
                    added = True
                    if len(candidates) >= limit:
                        break
            if not added:
                break
            row_index += 1

        return candidates

    def search_destination_image(self, destination_name: str) -> str | None:
        """Representative TourAPI photo of a region (KTO, 공공누리).

        Tourist spots named "<region> ..." are the region's own landmarks
        (강릉 경포대, 수원 화성, 부산 감천문화마을); the first with a photo wins,
        otherwise the first tourist spot with a photo.
        """
        name = (destination_name or "").strip()
        if not name:
            return None
        payload = self._get_json(
            "searchKeyword2",
            {"keyword": name, "contentTypeId": 12, "arrange": "Q", "numOfRows": 40, "pageNo": 1},
        )
        rows = [row for row in self._response_rows(payload) if str(row.get("firstimage") or "").strip()]
        named = [row for row in rows if str(row.get("title") or "").startswith(f"{name} ")]
        chosen = (named or rows or [None])[0]
        return self._normalize_image_url(str(chosen["firstimage"])) if chosen else None
