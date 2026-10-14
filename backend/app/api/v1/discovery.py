import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.dependencies import CurrentUser
from app.db.session import get_db
from app.core.exceptions import AppError
from app.schemas.scene_image import SceneImageResponse
from app.schemas.youtube_saved_discovery import (
    DestinationRecommendationsResponse,
    TourPlaceDetailResponse,
    YouTubeSavedDiscoveryCreate,
    YouTubeSavedDiscoveryListResponse,
    YouTubeSavedDiscoveryResponse,
)
from app.services.external.factory import (
    get_content_provider,
    get_place_provider,
    get_scene_recognition_provider,
    get_tour_destination_image_provider,
    get_youtube_destination_recommendation_selector,
)
from app.services.scene_image_service import SceneImageService
from app.services.external.place.tour_destination_image_provider import (
    TourDestinationImageProvider,
)
from app.services.youtube_destination_recommendation_service import (
    YouTubeDestinationRecommendationService,
)

router = APIRouter(tags=["discovery"])


def get_scene_image_service() -> SceneImageService:
    return SceneImageService(get_scene_recognition_provider(), get_place_provider())


SceneImageServiceDependency = Annotated[
    SceneImageService, Depends(get_scene_image_service)
]


@router.post(
    "/discovery/scene-image",
    response_model=SceneImageResponse,
    response_model_exclude_none=True,
)
async def receive_scene_image(
    user: CurrentUser,
    service: SceneImageServiceDependency,
    file: UploadFile = File(...),
    analyze: bool = Form(False),
) -> SceneImageResponse:
    """Receive a TV-scene image and optionally recognize place candidates once."""
    image_bytes = await file.read()
    return service.receive(
        filename=file.filename,
        content_type=file.content_type,
        image_bytes=image_bytes,
        analyze=analyze,
    )


from fastapi import WebSocket, WebSocketDisconnect

from app.schemas.youtube_bridge import YouTubePauseEvent
from app.services.youtube_bridge_manager import youtube_bridge_manager

bridge_logger = logging.getLogger("app.youtube_bridge")
from app.services.youtube_saved_discovery_service import (
    YouTubeSavedDiscoveryService,
)



def get_youtube_saved_discovery_service(
    db=Depends(get_db),
) -> YouTubeSavedDiscoveryService:
    return YouTubeSavedDiscoveryService(db)


YouTubeSavedDiscoveryServiceDependency = Annotated[
    YouTubeSavedDiscoveryService,
    Depends(get_youtube_saved_discovery_service),
]


def get_tour_destination_provider() -> TourDestinationImageProvider:
    return get_tour_destination_image_provider()


TourDestinationProviderDependency = Annotated[
    TourDestinationImageProvider,
    Depends(get_tour_destination_provider),
]


def get_youtube_destination_recommendation_service(
    db=Depends(get_db),
    candidate_provider=Depends(get_tour_destination_provider),
) -> YouTubeDestinationRecommendationService:
    return YouTubeDestinationRecommendationService(
        db,
        candidate_provider,
        get_youtube_destination_recommendation_selector,
        get_content_provider(),
    )


YouTubeDestinationRecommendationServiceDependency = Annotated[
    YouTubeDestinationRecommendationService,
    Depends(get_youtube_destination_recommendation_service),
]


@router.post("/discovery/youtube-pause")
async def receive_youtube_pause(
    payload: YouTubePauseEvent,
):
    """Receive a YouTube pause event from the demo playback device."""
    event_id = payload.event_id or uuid.uuid4().hex
    bridge_logger.info(
        "youtube_bridge EVENT_RECEIVED event_id=%s video_id=%s position_sec=%s",
        event_id, payload.video_id, payload.position_sec,
    )

    title = None
    channel_title = None
    thumbnail_url = None

    try:
        provider = get_content_provider()
        metadata = await asyncio.to_thread(
            provider.get_video,
            payload.video_id,
        )
        title = metadata.title
        channel_title = metadata.channel_title
        thumbnail_url = metadata.thumbnail_url

        bridge_logger.info("youtube_bridge METADATA_OK event_id=%s", event_id)
    except AppError as error:
        bridge_logger.info("youtube_bridge METADATA_FAILED event_id=%s code=%s", event_id, error.code)

    message = {
        "event": payload.event,
        "video_id": payload.video_id,
        "position_sec": payload.position_sec,
        "page_url": payload.page_url,
        "title": title,
        "channel_title": channel_title,
        "thumbnail_url": thumbnail_url,
        "event_id": event_id,
        "detected_at": payload.detected_at,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    delivered = await youtube_bridge_manager.broadcast(message)
    bridge_logger.info("youtube_bridge EVENT_DELIVERED event_id=%s clients=%s", event_id, delivered)

    return {
        "received": True,
        "event_id": event_id,
        "delivered_clients": delivered,
        "event": payload.event,
        "video_id": payload.video_id,
        "position_sec": payload.position_sec,
    }




@router.post(
    "/discovery/youtube-saved",
    response_model=YouTubeSavedDiscoveryResponse,
)
def save_youtube_discovery(
    request: YouTubeSavedDiscoveryCreate,
    user: CurrentUser,
    service: YouTubeSavedDiscoveryServiceDependency,
):
    return service.save(user.user_id, request)


@router.get(
    "/discovery/youtube-saved",
    response_model=YouTubeSavedDiscoveryListResponse,
)
def list_youtube_discoveries(
    user: CurrentUser,
    service: YouTubeSavedDiscoveryServiceDependency,
):
    return YouTubeSavedDiscoveryListResponse(
        items=service.list(user.user_id),
    )


@router.delete("/discovery/youtube-saved/{saved_discovery_id}")
def delete_youtube_discovery(
    saved_discovery_id: int,
    user: CurrentUser,
    service: YouTubeSavedDiscoveryServiceDependency,
):
    service.delete(user.user_id, saved_discovery_id)
    return {"deleted": True}


@router.get(
    "/discovery/destinations/{destination_name}/recommendations",
    response_model=DestinationRecommendationsResponse,
)
def get_destination_recommendations(
    destination_name: str,
    user: CurrentUser,
    service: YouTubeDestinationRecommendationServiceDependency,
    saved_discovery_id: int = Query(gt=0),
):
    destination = destination_name.strip()
    if not destination:
        raise AppError("INVALID_DESTINATION", "destination_name is required", 400)

    return service.recommend(
        user.user_id,
        saved_discovery_id,
        destination,
    )


@router.get(
    "/discovery/tour-places/{content_id}",
    response_model=TourPlaceDetailResponse,
    response_model_exclude_none=True,
)
def get_tour_place_detail(
    content_id: str,
    user: CurrentUser,
    provider: TourDestinationProviderDependency,
    content_type_id: int = Query(default=12, ge=1),
):
    # Auth matches the recommendations flow; all factual fields come from TourAPI.
    return provider.get_place_detail(content_id, content_type_id)

@router.websocket("/discovery/youtube-events")
async def youtube_events(websocket: WebSocket):
    """Stream YouTube playback events to the companion app."""
    await youtube_bridge_manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        youtube_bridge_manager.disconnect(websocket)


