from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.youtube_saved_discovery import YouTubeSavedDiscovery


class YouTubeSavedDiscoveryRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, saved_discovery_id: int):
        return self.session.get(YouTubeSavedDiscovery, saved_discovery_id)

    def get_by_user_video_position(
        self,
        user_id: int,
        video_id: str,
        position_sec: int,
    ):
        return self.session.scalar(
            select(YouTubeSavedDiscovery).where(
                YouTubeSavedDiscovery.user_id == user_id,
                YouTubeSavedDiscovery.video_id == video_id,
                YouTubeSavedDiscovery.position_sec == position_sec,
            )
        )

    def known_representative_image(self, destination_name: str) -> str | None:
        """An image already chosen for this region by an earlier save, if any."""
        return self.session.scalar(
            select(YouTubeSavedDiscovery.representative_image_url)
            .where(
                YouTubeSavedDiscovery.destination_name == destination_name,
                YouTubeSavedDiscovery.representative_image_url.is_not(None),
            )
            .order_by(YouTubeSavedDiscovery.saved_discovery_id.desc())
            .limit(1)
        )

    def list_for_user(self, user_id: int):
        return list(
            self.session.scalars(
                select(YouTubeSavedDiscovery)
                .where(YouTubeSavedDiscovery.user_id == user_id)
                .order_by(
                    YouTubeSavedDiscovery.created_at.desc(),
                    YouTubeSavedDiscovery.saved_discovery_id.desc(),
                )
            )
        )

    def create(self, user_id: int, **fields):
        discovery = YouTubeSavedDiscovery(
            user_id=user_id,
            **fields,
        )
        self.session.add(discovery)
        self.session.flush()
        return discovery

    def update(self, discovery, **fields):
        for field, value in fields.items():
            setattr(discovery, field, value)
        self.session.flush()
        return discovery
    def delete(self, discovery):
        self.session.delete(discovery)
        self.session.flush()
