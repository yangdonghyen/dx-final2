"""Request-scoped route cache with an external-call budget.

One instance must live for exactly one HTTP request (see
``factory.provide_route_provider``).  It never estimates a route: a cache
miss beyond the budget is reported as ``None`` (UNKNOWN), the same contract
as a provider that has no route fact.
"""

from contextlib import contextmanager

from app.services.external.routing.provider import RouteEstimate, RouteProvider

DEFAULT_MAX_CALLS_PER_REQUEST = 40
DEFAULT_MAX_CANDIDATE_CALLS_PER_REQUEST = 16
# KakaoMobilityRouteProvider sends a request only for these modes; MIXED,
# OTHER and an unset mode return None locally, so they must not use budget.
EXTERNAL_ROUTE_MODES = frozenset({"CAR", "WALK", "PUBLIC_TRANSIT"})


class CachedRouteProvider:
    """Cache directed legs and cap real provider calls for one request.

    - The key is directional: A->B and B->A are different legs.
    - Successful results and provider ``None`` results are both cached.
    - A budget-denied lookup returns ``None`` but is not cached, so a later
      itinerary-validation leg can still use the remaining budget.
    - Calls made inside ``candidate_phase()`` have their own smaller cap so
      candidate filtering cannot consume the budget reserved for validating
      the final itinerary.
    - ``limited_phase(n)`` gives one step (e.g. rest-cafe checks) its own
      allowance of ``n`` calls inside the overall cap, so an earlier candidate
      phase cannot leave it with no route facts at all.
    - ``denied`` counts lookups refused by a budget, so callers can tell a
      budget limit apart from a provider that had no route.
    """

    def __init__(
        self,
        inner: RouteProvider,
        max_calls: int = DEFAULT_MAX_CALLS_PER_REQUEST,
        max_candidate_calls: int = DEFAULT_MAX_CANDIDATE_CALLS_PER_REQUEST,
    ) -> None:
        self.inner = inner
        self.max_calls = max(0, max_calls)
        self.max_candidate_calls = max(0, min(max_candidate_calls, self.max_calls))
        self.calls = 0
        self.candidate_calls = 0
        self._candidate_depth = 0
        self._limits: list[list[int]] = []
        self.denied = 0
        self._cache: dict[tuple, RouteEstimate | None] = {}

    @contextmanager
    def candidate_phase(self):
        self._candidate_depth += 1
        try:
            yield self
        finally:
            self._candidate_depth -= 1

    @contextmanager
    def limited_phase(self, max_calls: int):
        """Allow at most ``max_calls`` new provider calls inside this block.

        These calls count toward the overall cap but not the candidate cap.
        """
        limit = [max(0, max_calls), 0]
        self._limits.append(limit)
        try:
            yield self
        finally:
            self._limits.remove(limit)

    def _options(self) -> tuple:
        # Settings that change the inner provider's request for the same leg.
        return (type(self.inner).__name__, getattr(self.inner, "walking_route_mode", None))

    def _budget_available(self) -> bool:
        if self.calls >= self.max_calls:
            return False
        if self._limits:
            allowed, used = self._limits[-1]
            return used < allowed
        return not (self._candidate_depth and self.candidate_calls >= self.max_candidate_calls)

    def route(
        self,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
        transport_mode: str | None,
    ) -> RouteEstimate | None:
        key = (
            origin_latitude, origin_longitude, destination_latitude, destination_longitude,
            transport_mode, self._options(),
        )
        if key in self._cache:
            return self._cache[key]
        if transport_mode not in EXTERNAL_ROUTE_MODES:
            estimate = self.inner.route(
                origin_latitude, origin_longitude, destination_latitude, destination_longitude, transport_mode
            )
            self._cache[key] = estimate
            return estimate
        if not self._budget_available():
            self.denied += 1
            return None
        self.calls += 1
        if self._limits:
            self._limits[-1][1] += 1
        elif self._candidate_depth:
            self.candidate_calls += 1
        estimate = self.inner.route(
            origin_latitude, origin_longitude, destination_latitude, destination_longitude, transport_mode
        )
        self._cache[key] = estimate
        return estimate
