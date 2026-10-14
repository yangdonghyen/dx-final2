"""Who may do what on a trip.

The owner manages everything.  A member who joined through an invite link
(trip_companions.member_user_id) may read the plan and edit its items, and
nothing else: ownership, share links, regeneration, confirmation and deleting
the trip stay owner only, because those services keep their own owner check.
"""

from app.core.exceptions import AppError


def require_plan_member(companions, trip, user_id) -> None:
    """companions: a TripCompanionRepository."""
    if trip.user_id == user_id: return
    if companions.get_member(trip.trip_id, user_id) is None:
        raise AppError("FORBIDDEN", "You do not own this trip", 403)
