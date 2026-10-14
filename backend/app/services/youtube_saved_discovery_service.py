from sqlalchemy.exc import IntegrityError
from app.core.exceptions import AppError
from app.repositories.youtube_saved_discovery_repository import (
    YouTubeSavedDiscoveryRepository,
)
from app.services.external.factory import (
    get_destination_image_provider,
    get_tour_destination_image_provider,
    get_youtube_representative_selector,
)
from app.services.youtube_destination_resolver import YouTubeDestinationResolver
from app.services.youtube_region_resolver import YouTubeRegionResolver


class YouTubeSavedDiscoveryService:
    def __init__(self, session, region_resolver: YouTubeRegionResolver | None = None):
        self.session = session
        self.saved_discoveries = YouTubeSavedDiscoveryRepository(session)
        self.destination_resolver = YouTubeDestinationResolver()
        self.region_resolver = region_resolver or YouTubeRegionResolver.from_settings()
        self.destination_images = get_destination_image_provider()

    @staticmethod
    def _log_enrichment_failure(destination_name: str, error: AppError) -> None:
        print(
            "[YouTube Saved Image]",
            f"destination={destination_name}",
            f"lookup failed code={error.code}",
        )

    def _representative_image(self, destination_name: str) -> str | None:
        try:
            candidates = get_tour_destination_image_provider().search_candidates(
                destination_name,
                limit=90,
            )
            selected = get_youtube_representative_selector().select(
                destination_name,
                candidates,
                group_size=30,
            )
            if selected is not None:
                return selected.image_url
        except AppError as error:
            self._log_enrichment_failure(destination_name, error)

        try:
            return self.destination_images.search_destination_image(destination_name)
        except AppError as error:
            self._log_enrichment_failure(destination_name, error)
            return None

    def _enriched_destination_fields(
        self,
        title: str | None,
        existing_destination_name: str | None = None,
        video_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        # 제목 키워드 -> 영상 태그/설명 키워드 -> EXAONE(알려진 지역만 허용) 순서.
        destination_name = (
            existing_destination_name
            or self.region_resolver.resolve(video_id, title)
        )
        representative_image_url = (
            self._representative_image(destination_name)
            if destination_name is not None
            else None
        )
        return destination_name, representative_image_url

    def save(self, user_id: int, request):
        title = request.title or "\uc5ec\ud589 \uc601\uc0c1\uc744 \ubc1c\uacac\ud588\uc5b4\uc694"

        existing = self.saved_discoveries.get_by_user_video_position(
            user_id=user_id,
            video_id=request.video_id,
            position_sec=request.position_sec,
        )

        # 예전에 저장한 데이터라도 지역 정보가 없으면 다시 채운다.
        if existing is not None:
            if (
                existing.destination_name is None
                or existing.representative_image_url is None
            ):
                destination_name, representative_image_url = (
                    self._enriched_destination_fields(
                        title,
                        existing.destination_name,
                        request.video_id,
                    )
                )

                try:
                    self.saved_discoveries.update(
                        existing,
                        destination_name=destination_name,
                        representative_image_url=representative_image_url,
                    )
                    self.session.commit()
                    self.session.refresh(existing)
                except Exception:
                    self.session.rollback()
                    raise

            return existing

        destination_name, representative_image_url = (
            self._enriched_destination_fields(title, video_id=request.video_id)
        )

        try:
            discovery = self.saved_discoveries.create(
                user_id=user_id,
                video_id=request.video_id,
                position_sec=request.position_sec,
                page_url=request.page_url,
                title=title,
                channel_title=request.channel_title,
                thumbnail_url=request.thumbnail_url,
                destination_name=destination_name,
                representative_image_url=representative_image_url,
            )

            self.session.commit()
            self.session.refresh(discovery)

            print(
                "[YouTube Saved]",
                f"id={discovery.saved_discovery_id}",
                f"destination={destination_name}",
                f"representative_image={'yes' if representative_image_url else 'no'}",
            )

            return discovery

        except IntegrityError:
            # Two taps (저장하기 + 여행 계획하기) save the same video and
            # position at once; the slower one returns the row the first made.
            self.session.rollback()
            existing = self.saved_discoveries.get_by_user_video_position(
                user_id=user_id,
                video_id=request.video_id,
                position_sec=request.position_sec,
            )
            if existing is None:
                raise
            return existing
        except Exception:
            self.session.rollback()
            raise

    def list(self, user_id: int):
        return self.saved_discoveries.list_for_user(user_id)

    def delete(self, user_id: int, saved_discovery_id: int):
        discovery = self.saved_discoveries.get(saved_discovery_id)

        if discovery is None:
            raise AppError(
                "YOUTUBE_SAVED_DISCOVERY_NOT_FOUND",
                "Saved YouTube discovery not found",
                404,
            )

        if discovery.user_id != user_id:
            raise AppError(
                "FORBIDDEN",
                "You do not own this saved discovery",
                403,
            )

        try:
            self.saved_discoveries.delete(discovery)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
