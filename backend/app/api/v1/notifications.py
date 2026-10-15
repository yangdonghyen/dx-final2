from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db.session import get_db
from app.dependencies import CurrentUser
from app.services.notification_service import NotificationService

router = APIRouter(tags=["notifications"])


class NotificationItem(BaseModel):
    notification_id: int
    trip_id: int | None
    kind: str
    title: str
    body: str
    created_at: datetime
    read: bool


class NotificationListResponse(BaseModel):
    notifications: list[NotificationItem]


def get_notification_service(db=Depends(get_db)): return NotificationService(db)


@router.get("/notifications", response_model=NotificationListResponse)
def list_notifications(user: CurrentUser, service: NotificationService = Depends(get_notification_service)):
    return NotificationListResponse(notifications=service.list(user.user_id))


@router.post("/notifications/read-all", response_model=NotificationListResponse)
def read_all_notifications(user: CurrentUser, service: NotificationService = Depends(get_notification_service)):
    service.mark_all_read(user.user_id)
    return NotificationListResponse(notifications=service.list(user.user_id))
