from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.session import get_db
from app.dependencies import CurrentUser
from app.schemas.trip import (PreferenceAnalysisResponse, SharedTripResponse, SourceDeactivateResponse,
                              TripCreate, TripCreateResponse, TripDeleteResponse,
                              TripDetailResponse, TripJoinResponse, TripListResponse,
                              TripShareLinkCreate, TripShareLinkResponse, TripUpdate,
                              YouTubeSourceRequest, YouTubeSourceResponse)
from app.services.external.factory import get_tour_destination_image_provider, provide_content_provider, provide_preference_analysis_provider
from app.services.preference_analysis_service import PreferenceAnalysisService
from app.services.trip_service import TripService
from app.services.trip_share_service import TripShareService
from app.services.youtube_source_service import YouTubeSourceService

router = APIRouter(tags=["trips"])

# The Flutter app registers this scheme in AndroidManifest.xml to open invite links.
APP_INVITE_URL = "bogogago://invite"


def get_service(db=Depends(get_db)): return TripService(db)
def get_share_service(db=Depends(get_db)): return TripShareService(db)
def get_youtube_source_service(db=Depends(get_db), provider=Depends(provide_content_provider)): return YouTubeSourceService(db, provider)
def get_preference_analysis_service(db=Depends(get_db), provider=Depends(provide_preference_analysis_provider)): return PreferenceAnalysisService(db, provider)


Service = Annotated[TripService, Depends(get_service)]
ShareService = Annotated[TripShareService, Depends(get_share_service)]
SourceService = Annotated[YouTubeSourceService, Depends(get_youtube_source_service)]
AnalysisService = Annotated[PreferenceAnalysisService, Depends(get_preference_analysis_service)]


@router.post("/trips", response_model=TripCreateResponse, status_code=status.HTTP_201_CREATED)
def create_trip(request: TripCreate, user: CurrentUser, service: Service):
    trip = service.create(user.user_id, request)
    return TripCreateResponse(trip_id=trip.trip_id, status=trip.status)


@router.get("/trips", response_model=TripListResponse)
def list_trips(user: CurrentUser, service: Service): return TripListResponse(trips=service.list(user.user_id))


@router.get("/trips/{trip_id}", response_model=TripDetailResponse)
def get_trip(trip_id: int, user: CurrentUser, service: Service): return service.detail(user.user_id, trip_id)


@router.patch("/trips/{trip_id}", response_model=TripDetailResponse)
def update_trip(trip_id: int, request: TripUpdate, user: CurrentUser, service: Service): return service.update(user.user_id, trip_id, request)


@router.delete("/trips/{trip_id}", response_model=TripDeleteResponse)
def delete_trip(trip_id: int, user: CurrentUser, service: Service):
    service.archive(user.user_id, trip_id)
    return TripDeleteResponse()


# Destination -> representative image URL (or None).  Past-trip cards ask for
# the same few regions again and again, so one TourAPI call per region per process.
_DESTINATION_IMAGES: dict[str, str | None] = {}


def get_destination_images(): return get_tour_destination_image_provider()


@router.get("/destination-image")
def destination_image(user: CurrentUser, destination: str = Query(min_length=1, max_length=100), provider=Depends(get_destination_images)):
    """Representative TourAPI (한국관광공사) photo of a region."""
    key = destination.strip()
    if key not in _DESTINATION_IMAGES:
        try:
            _DESTINATION_IMAGES[key] = provider.search_destination_image(key)
        except AppError:
            return {"destination": key, "image_url": None}  # the card keeps its plain cover; not cached, retried later
    return {"destination": key, "image_url": _DESTINATION_IMAGES[key]}


@router.post("/trips/{trip_id}/sources/youtube", response_model=YouTubeSourceResponse, status_code=status.HTTP_201_CREATED)
def add_youtube_source(trip_id: int, request: YouTubeSourceRequest, user: CurrentUser, service: SourceService):
    return service.add(user.user_id, trip_id, request.youtube_url)


@router.delete("/trips/{trip_id}/sources/{source_id}", response_model=SourceDeactivateResponse)
def deactivate_source(trip_id: int, source_id: int, user: CurrentUser, service: SourceService):
    service.deactivate(user.user_id, trip_id, source_id)
    return SourceDeactivateResponse()


@router.post("/trips/{trip_id}/analyze-preferences", response_model=PreferenceAnalysisResponse)
def analyze_preferences(trip_id: int, user: CurrentUser, service: AnalysisService):
    return service.analyze(user.user_id, trip_id)


@router.post("/trips/{trip_id}/share-links", response_model=TripShareLinkResponse, status_code=status.HTTP_201_CREATED)
def create_share_link(trip_id: int, body: TripShareLinkCreate, request: Request, user: CurrentUser, service: ShareService):
    base_url = get_settings().public_share_base_url.strip() or str(request.base_url)
    return service.create_link(user.user_id, trip_id, body.link_type, base_url)


@router.get("/shared-trips/{token}", response_model=SharedTripResponse)
def get_shared_trip(token: str, request: Request, service: ShareService):
    wants_html = "text/html" in request.headers.get("accept", "")
    try:
        shared = service.shared_trip(token)
    except AppError as error:
        # A browser (KakaoTalk, Chrome) gets a readable page, same status code.
        if wants_html and error.code in SHARE_LINK_ERROR_PAGES:
            return HTMLResponse(render_share_link_error_page(error.code), status_code=error.status_code)
        raise
    if wants_html:
        return HTMLResponse(render_shared_trip_page(shared, token))
    return shared


SHARE_LINK_ERROR_PAGES = {
    "SHARE_LINK_EXPIRED": ("만료된 공유 링크예요", "이 링크는 사용 기간이 지나 더 이상 열 수 없어요. 여행을 만든 분께 새 링크를 요청해 주세요."),
    "SHARE_LINK_NOT_FOUND": ("열 수 없는 공유 링크예요", "링크가 잘못되었거나 공유가 취소되었어요. 여행을 만든 분께 확인해 주세요."),
}


def render_share_link_error_page(code: str) -> str:
    title, detail = SHARE_LINK_ERROR_PAGES[code]
    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{font-family:sans-serif;margin:0;padding:24px;background:#f7f8fc;color:#111;font-size:18px;line-height:1.5}}
.card{{background:#fff;border-radius:16px;padding:24px;margin-top:40px;text-align:center}}h1{{font-size:24px;margin:12px 0 8px}}.muted{{color:#6b7280}}</style></head><body>
<div class=card><div style="font-size:48px">🔒</div><h1>{title}</h1><p class=muted>{detail}</p></div></body></html>"""


@router.delete("/trips/{trip_id}/membership")
def leave_shared_trip(trip_id: int, user: CurrentUser, service: ShareService):
    """공유받은 여행에서 나가기."""
    return service.leave(user, trip_id)


@router.post("/shared-trips/{token}/join", response_model=TripJoinResponse)
def join_shared_trip(token: str, user: CurrentUser, service: ShareService):
    return service.join(user, token)


def render_shared_trip_page(shared: SharedTripResponse, token: str = "") -> str:
    """Minimal page for people who open the link in KakaoTalk or a browser."""
    title = escape(shared.title or (f"{shared.destination} 여행" if shared.destination else "여행 일정"))
    dates = " ~ ".join(str(value) for value in (shared.start_date, shared.end_date) if value) or "날짜 미정"
    companions = "".join(f"<li>{escape(row.name)}</li>" for row in shared.companions) or "<li>아직 동행자가 없어요</li>"
    places = "".join(f"<li>{escape(name)}</li>" for name in shared.selected_places) or "<li>아직 선택한 장소가 없어요</li>"
    labels = {"MEAL": "🍽️ ", "REST": "☕ ", "FREE_TIME": "🕊️ "}
    days = "".join(
        f"<div class=card><h2>DAY {day.day} · {day.visit_date.month}월 {day.visit_date.day}일</h2><ul class=plan>"
        + "".join(
            f"<li><b>{escape(stop.start_time or '--:--')}</b> {labels.get(stop.item_type, '📍 ')}{escape(stop.title)}"
            + (f"<br><span class=muted>{escape(stop.note)}</span>" if stop.note else "") + "</li>"
            for stop in day.stops
        )
        + "</ul></div>"
        for day in shared.days
    )
    owner = escape(shared.owner_nickname) + "님의 " if shared.owner_nickname else ""
    invite = ""
    if shared.link_type == "INVITE":
        invite = "<p class=invite>동행자 초대 링크예요.</p>"
        if token:
            app_url = escape(f"{APP_INVITE_URL}?token={quote(token, safe='')}")
            invite += f'<a class=join href="{app_url}">보고가고 앱에서 참여하기</a>'
            invite += "<p class=muted>앱이 설치된 휴대폰에서 눌러주세요.</p>"
    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{font-family:sans-serif;margin:0;padding:24px;background:#f7f8fc;color:#111;font-size:18px;line-height:1.5}}
h1{{font-size:26px;margin:0 0 4px}}.card{{background:#fff;border-radius:16px;padding:18px;margin-top:16px}}h2{{font-size:18px;margin:0 0 8px}}
.muted{{color:#6b7280}}.invite{{background:#fff3e0;border-radius:12px;padding:12px;font-weight:700}}
.plan{{list-style:none;padding:0;margin:0}}.plan li{{padding:8px 0;border-bottom:1px solid #eef0f4}}
.join{{display:block;margin-top:12px;padding:16px;border-radius:14px;background:#4169d8;color:#fff;text-align:center;font-weight:700;text-decoration:none}}</style></head><body>
<p class=muted>{owner}여행 일정</p><h1>{title}</h1><p class=muted>{escape(dates)}</p>{invite}
{days}<div class=card><h2>동행자</h2><ul>{companions}</ul></div>{"" if shared.days else f'<div class=card><h2>방문할 장소</h2><ul>{places}</ul></div>'}</body></html>"""
