"""Build recommendations from one owned saved discovery and verified places."""

import time
from collections import OrderedDict
from threading import RLock
from typing import Callable

from app.core.exceptions import AppError
from app.repositories.youtube_saved_discovery_repository import (
    YouTubeSavedDiscoveryRepository,
)
from app.schemas.youtube_saved_discovery import (
    DestinationRecommendationPlace,
    DestinationRecommendationsResponse,
)
from app.services.external.place.tour_destination_image_provider import (
    DestinationImageCandidate,
    TourDestinationImageProvider,
)
from app.services.youtube_destination_resolver import YouTubeDestinationResolver
from app.services.youtube_destination_recommendation_selector import (
    YouTubeDestinationRecommendationSelector,
)


class YouTubeDestinationRecommendationService:
    # Keyed by (video, destination): every save of the same video (one per
    # pause) shares one result instead of a fresh ~50 s EXAONE selection.
    _cache: OrderedDict[
        tuple[str, str], tuple[float, DestinationRecommendationsResponse]
    ] = OrderedDict()
    _cache_lock = RLock()
    _cache_ttl_seconds = 6 * 3600
    _cache_max_entries = 256

    def __init__(
        self,
        session,
        candidate_provider: TourDestinationImageProvider,
        selector_factory: Callable[[], YouTubeDestinationRecommendationSelector],
        content_provider,
    ):
        self.discoveries = YouTubeSavedDiscoveryRepository(session)
        self.candidate_provider = candidate_provider
        self.selector_factory = selector_factory
        self.content_provider = content_provider
        self.destination_resolver = YouTubeDestinationResolver()

    @classmethod
    def _cached(
        cls,
        key: tuple[str, str],
    ) -> DestinationRecommendationsResponse | None:
        now = time.monotonic()
        with cls._cache_lock:
            entry = cls._cache.get(key)
            if entry is None:
                return None
            expires_at, response = entry
            if expires_at <= now:
                del cls._cache[key]
                return None
            cls._cache.move_to_end(key)
            return response

    @classmethod
    def _cache_response(
        cls,
        key: tuple[int, str, str],
        response: DestinationRecommendationsResponse,
    ) -> None:
        with cls._cache_lock:
            cls._cache[key] = (time.monotonic() + cls._cache_ttl_seconds, response)
            cls._cache.move_to_end(key)
            while len(cls._cache) > cls._cache_max_entries:
                cls._cache.popitem(last=False)

    @staticmethod
    def _category_key(candidate: DestinationImageCandidate) -> str | None:
        # Only use TourAPI's supplied hierarchy. Missing categories do not
        # receive an inferred type and do not participate in the cap.
        return candidate.cat3 or candidate.cat2

    @classmethod
    def _diversify(
        cls,
        ordered_candidates: list[DestinationImageCandidate],
        limit: int = 6,
    ) -> list[DestinationImageCandidate]:
        selected = []
        category_counts: dict[str, int] = {}
        for candidate in ordered_candidates:
            category = cls._category_key(candidate)
            if category is not None and category_counts.get(category, 0) >= 2:
                continue
            selected.append(candidate)
            if category is not None:
                category_counts[category] = category_counts.get(category, 0) + 1
            if len(selected) == limit:
                break
        return selected

    @staticmethod
    def _to_place(candidate: DestinationImageCandidate):
        return DestinationRecommendationPlace(
            content_id=candidate.content_id,
            title=candidate.title,
            image_url=candidate.image_url,
            # The provider request is constrained to contentTypeId=12.
            category="관광지",
            address=candidate.address,
            content_type_id=(
                int(candidate.content_type_id)
                if candidate.content_type_id and candidate.content_type_id.isdigit()
                else None
            ),
            cat1=candidate.cat1,
            cat2=candidate.cat2,
            cat3=candidate.cat3,
            map_x=candidate.map_x,
            map_y=candidate.map_y,
        )

    @staticmethod
    def _validate_ranked(ranked, candidate_ids: set[str]) -> None:
        if not ranked or len(ranked) > 6:
            raise ValueError("selector returned an invalid number of candidates")

        seen_ids = set()
        for item in ranked:
            if (
                not isinstance(item.content_id, str)
                or item.content_id not in candidate_ids
                or item.content_id in seen_ids
            ):
                raise ValueError("selector returned an invalid candidate id")
            values = (
                item.video_relevance,
                item.regional_representativeness,
                item.diversity_score,
                item.total_score,
            )
            if any(type(value) is not int for value in values):
                raise ValueError("selector returned invalid score values")
            if not 0 <= item.video_relevance <= 50:
                raise ValueError("selector returned invalid video relevance")
            if not 0 <= item.regional_representativeness <= 30:
                raise ValueError("selector returned invalid regional score")
            if not 0 <= item.diversity_score <= 20:
                raise ValueError("selector returned invalid diversity score")
            if item.total_score != (
                item.video_relevance
                + item.regional_representativeness
                + item.diversity_score
            ):
                raise ValueError("selector returned invalid total score")
            seen_ids.add(item.content_id)

    def recommend(
        self,
        user_id: int,
        saved_discovery_id: int,
        requested_destination: str,
    ) -> DestinationRecommendationsResponse:
        discovery = self.discoveries.get(saved_discovery_id)
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

        destination = (
            (discovery.destination_name or "").strip()
            or self.destination_resolver.resolve(discovery.title)
            or self.destination_resolver.resolve(requested_destination)
            or requested_destination.strip()
        )
        cache_key = (discovery.video_id, destination)
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        # Database metadata is authoritative. Use existing YouTube provider
        # only for fields that the saved row does not store.
        video_description = None
        video_tags: list[str] = []
        try:
            metadata = self.content_provider.get_video(discovery.video_id)
            video_description = metadata.description
            video_tags = list(metadata.tags)
        except AppError as error:
            print(
                "[YouTube Destination Recommendations]",
                f"metadata unavailable code={error.code}",
            )
        except Exception as error:
            print(
                "[YouTube Destination Recommendations]",
                "metadata unavailable",
                f"reason={type(error).__name__}",
            )

        raw_candidates = self.candidate_provider.search_candidates(
            destination,
            limit=40,
        )
        candidates = []
        seen_candidate_ids = set()
        for candidate in raw_candidates:
            if candidate.content_id not in seen_candidate_ids:
                seen_candidate_ids.add(candidate.content_id)
                candidates.append(candidate)
        if not candidates:
            # Not cached: an empty result is retried once the region or
            # TourAPI lookup is fixed.
            return DestinationRecommendationsResponse(
                destination_name=destination,
                themes=[],
                places=[],
            )

        candidate_by_id = {candidate.content_id: candidate for candidate in candidates}
        selection_succeeded = False
        try:
            ranked = self.selector_factory().rank(
                destination_name=destination,
                video_id=discovery.video_id,
                video_title=discovery.title,
                channel_title=discovery.channel_title,
                video_description=video_description,
                video_tags=video_tags,
                candidates=candidates,
            )

            # Defense in depth: only verified TourAPI ids may leave this layer.
            self._validate_ranked(ranked, set(candidate_by_id))

            ordered = [candidate_by_id[item.content_id] for item in ranked]
            selected = self._diversify(ordered)
            selection_succeeded = True
        except Exception as error:
            # Selection problems never make the region detail unusable. The
            # fallback consists only of TourAPI candidates and is not labeled
            # as an AI selection in the response.
            selected = self._diversify(candidates)
            print(
                "[YouTube Destination Recommendations]",
                "selection=fallback",
                f"reason={type(error).__name__}",
                f"candidate_count={len(candidates)}",
            )

        if selection_succeeded:
            print(
                "[YouTube Destination Recommendations]",
                "selection=exaone",
                f"candidate_count={len(candidates)}",
                f"selected_count={len(selected)}",
            )

        response = DestinationRecommendationsResponse(
            destination_name=destination,
            themes=[],
            places=[self._to_place(candidate) for candidate in selected],
        )
        self._cache_response(cache_key, response)
        return response
