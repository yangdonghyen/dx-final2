"""Import every mapped class so Alembic sees the complete service schema."""

from app.models.user import (
    User,
    UserPreference,
    InterestCode,
    UserInterest,
)
from app.models.auth import (
    UserAuth,
    RefreshToken,
)
from app.models.companion import (
    Companion,
    CompanionPreference,
    CompanionInterest,
)
from app.models.trip import (
    Trip,
    TripPreference,
    TripSelectedPlace,
    TripCompanion,
    TripInterest,
    TripSource,
    TripShareLink,
)
from app.models.place import (
    Place,
    SourcePlace,
)
from app.models.plan import (
    TravelPlan,
    PlanItem,
    PlanRevision,
    PlanRegenerationPreview,
    PlanValidationIssue,
)
from app.models.youtube_saved_discovery import YouTubeSavedDiscovery
from app.models.user_notification import UserNotification
from app.models.docent import (
    DocentAnalysis,
    DocentCandidate,
)

__all__ = [
    'User',
    'UserPreference',
    'InterestCode',
    'UserInterest',
    'UserAuth',
    'RefreshToken',
    'Companion',
    'CompanionPreference',
    'CompanionInterest',
    'Trip',
    'TripPreference',
    'TripSelectedPlace',
    'TripCompanion',
    'TripInterest',
    'TripSource',
    'TripShareLink',
    'Place',
    'SourcePlace',
    'TravelPlan',
    'PlanItem',
    'PlanRevision',
    'PlanRegenerationPreview',
    'PlanValidationIssue',
    'DocentAnalysis',
    'DocentCandidate',
    'YouTubeSavedDiscovery',
    'UserNotification',
]

