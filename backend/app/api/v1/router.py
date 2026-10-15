from fastapi import APIRouter

from app.api.v1 import auth, companions, discovery, docent, notifications, places, plans, trips, users, weather
from app.schemas.common import HealthResponse

api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Application liveness only; does not probe MySQL or external providers."""
    return HealthResponse()


for router in (auth.router, users.router, companions.router, trips.router,
               places.router, plans.router, docent.router, weather.router, notifications.router):
    api_router.include_router(router)

api_router.include_router(discovery.router)
