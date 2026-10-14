"""Opt-in verification against a disposable MySQL database.

Set PLAN_REGENERATION_MYSQL_TEST_URL to a 127.0.0.1, non-3306 MySQL URL whose
database name contains "test", and set PLAN_REGENERATION_MYSQL_TEST_DATADIR to
that isolated server's datadir. The test upgrades to head, verifies revisions
010/011 and their safe downgrade behavior, and only creates a private
user/trip/plan fixture that it deletes at the end.
"""

from datetime import date, datetime, time, timedelta
import logging
import os
from pathlib import Path
from threading import Barrier, Thread
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
import pymysql
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT, get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.core.exceptions import AppError
from app.models.place import Place
from app.models.plan import PlanItem, PlanRegenerationPreview, PlanRevision, TravelPlan
from app.models.trip import Trip, TripSelectedPlace
from app.models.user import User
from app.repositories.plan_repository import PlanItemRepository, PlanRegenerationPreviewRepository
from app.schemas.plan import PlanRegenerateRequest
from app.services.external.ai.provider import GeneratedPlanDraft, PlanDraftDay, PlanDraftItem
from app.services.external.routing.provider import RouteEstimate
from app.services.plan_regeneration_approval_service import PlanRegenerationApprovalService
from app.services.plan_regeneration_preview_service import PlanRegenerationPreviewService


_REAL_PYMYSQL_CONNECT = pymysql.connect


@pytest.fixture
def mysql_engine(mysql_test_url):
    """A head-schema engine whose target was verified by ``mysql_test_url``."""
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    engine = create_engine(mysql_test_url, pool_pre_ping=True, pool_size=5, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


def _draft() -> GeneratedPlanDraft:
    return GeneratedPlanDraft([PlanDraftDay(date(2026, 1, 1), [
        PlanDraftItem(1, "REST", "Revised rest", None, "11:00", "12:00", "mocked draft"),
    ])])


def _generation(draft: GeneratedPlanDraft):
    def validate(value, _place_ids):
        return [
            (day.visit_date, [
                (item, time.fromisoformat(item.start_time), time.fromisoformat(item.end_time))
                for item in day.items
            ])
            for day in value.days
        ]

    return SimpleNamespace(
        route_provider=None,
        _input=lambda _trip: ({}, {}, [], [], {}, [], set(), {}),
        _normalize_draft_dates=lambda value, _trip: value,
        _prepare_draft=lambda value, _places, _anchors, _trip, _preferences=None: value,
        _validate_draft=validate,
        _validate_temporal_draft=lambda *_args: None,
        _validate_route_timing=lambda *_args: None,
        _validate_activity_diversity=lambda *_args: None,
        _date_skeleton=lambda _trip: [date(2026, 1, 1)],
        _canonical_item_type=lambda _place: "PLACE",
        _provider_error=lambda: RuntimeError("mocked draft validation failed"),
    )


def _preview_service(session):
    service = PlanRegenerationPreviewService(
        session,
        SimpleNamespace(regenerate_plan=lambda *_args: _draft()),
    )
    service.generation = _generation(_draft())
    return service


def _approval_service(session):
    service = PlanRegenerationApprovalService(session, SimpleNamespace())
    service.generation = _generation(_draft())
    return service


def _create_plan_fixture(engine, nickname_suffix: str):
    with Session(engine) as session:
        user = User(nickname=f"task72-{nickname_suffix}")
        session.add(user)
        session.flush()
        trip = Trip(
            user_id=user.user_id,
            title="Task 7.2 isolated service fixture",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 1),
            transport_mode="OTHER",
        )
        session.add(trip)
        session.flush()
        plan = TravelPlan(trip_id=trip.trip_id, status="DRAFT", current_version=1)
        session.add(plan)
        session.flush()
        PlanItemRepository(session).create(
            plan.plan_id,
            place_id=None,
            visit_date=date(2026, 1, 1),
            sequence_no=1,
            item_type="REST",
            title="Original rest",
            start_time=time(10),
            end_time=time(10, 30),
            recommendation_reason="original",
            validation_status="UNKNOWN",
        )
        session.commit()
        return user.user_id, plan.plan_id


def _create_preview(engine, user_id, plan_id):
    with Session(engine) as session:
        response = _preview_service(session).create(
            user_id,
            plan_id,
            PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Use mocked draft"),
        )
        return response.preview_id


def _cleanup_user(engine, user_id):
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is not None:
            session.delete(user)
            session.commit()


@pytest.fixture
def mysql_test_url(monkeypatch):
    raw_url = os.environ.get("PLAN_REGENERATION_MYSQL_TEST_URL")
    if not raw_url:
        pytest.skip("PLAN_REGENERATION_MYSQL_TEST_URL is not configured")
    url = make_url(raw_url)
    expected_datadir = os.environ.get("PLAN_REGENERATION_MYSQL_TEST_DATADIR")
    if (
        not url.drivername.startswith("mysql")
        or "test" not in (url.database or "").lower()
        or url.host != "127.0.0.1"
        or not url.port
        or url.port == 3306
        or not expected_datadir
    ):
        pytest.fail(
            "MySQL integration requires a 127.0.0.1 non-3306 test URL and "
            "PLAN_REGENERATION_MYSQL_TEST_DATADIR "
            f"(mysql={url.drivername.startswith('mysql')}; test_database={'test' in (url.database or '').lower()}; "
            f"loopback={url.host == '127.0.0.1'}; nondefault_port={bool(url.port and url.port != 3306)}; "
            f"declared_datadir={bool(expected_datadir)})"
        )

    # This opt-in test has independently verified its target. Restore the normal
    # driver before opening the read-only verification connection.
    monkeypatch.setattr(pymysql, "connect", _REAL_PYMYSQL_CONNECT)

    # A test-looking database name alone cannot prove that a server is disposable.
    # Verify the connected server's own datadir before Alembic is allowed to write.
    verification_engine = create_engine(url, pool_pre_ping=True)
    try:
        with verification_engine.connect() as connection:
            actual_datadir = connection.scalar(text("SELECT @@datadir"))
            actual_port = connection.scalar(text("SELECT @@port"))
            actual_database = connection.scalar(text("SELECT DATABASE()"))
    finally:
        verification_engine.dispose()
    if (
        actual_port != url.port
        or actual_database != url.database
        or Path(actual_datadir).resolve() != Path(expected_datadir).resolve()
    ):
        pytest.fail("MySQL integration target is not the declared isolated instance")
    monkeypatch.setenv("MYSQL_HOST", url.host or "")
    monkeypatch.setenv("MYSQL_PORT", str(url.port or 3306))
    monkeypatch.setenv("MYSQL_DATABASE", url.database or "")
    monkeypatch.setenv("MYSQL_USER", url.username or "")
    monkeypatch.setenv("MYSQL_PASSWORD", url.password or "")
    get_settings.cache_clear()
    try:
        yield url
    finally:
        get_settings.cache_clear()


@pytest.mark.mysql_integration
def test_plan_regeneration_preview_repository_on_mysql(mysql_test_url):
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(mysql_test_url, pool_pre_ping=True)
    try:
        schema = inspect(engine)
        assert "plan_regeneration_previews" in schema.get_table_names()
        columns = {column["name"]: column for column in schema.get_columns("plan_regeneration_previews")}
        json_columns = {"feedback_codes", "current_itinerary_snapshot", "proposed_itinerary", "diff"}
        assert json_columns <= set(columns)
        assert all(str(columns[name]["type"]).upper() == "JSON" for name in json_columns)
        assert {foreign_key["name"] for foreign_key in schema.get_foreign_keys("plan_regeneration_previews")} == {
            "fk_plan_regeneration_previews_plan", "fk_plan_regeneration_previews_user",
        }
        # InnoDB can expose a supporting index it created for an FK. Require the
        # migration's two query indexes without rejecting that engine detail.
        assert {
            "ix_plan_regeneration_previews_plan_status", "ix_plan_regeneration_previews_expires_at",
        } <= {index["name"] for index in schema.get_indexes("plan_regeneration_previews")}
        assert set(columns["status"]["type"].enums) == {"PENDING", "APPLIED", "CANCELLED", "EXPIRED"}
        assert set(columns["reason"]["type"].enums) == {"USER_FATIGUE", "WEATHER_CHANGE"}

        command.downgrade(config, "009_trip_share_links")
        assert "plan_regeneration_previews" not in inspect(engine).get_table_names()
        command.upgrade(config, "010_plan_regeneration_previews")

        with Session(engine) as setup:
            user = User(nickname="task1-preview-mysql")
            setup.add(user)
            setup.flush()
            trip = Trip(user_id=user.user_id, title="Task 1 isolated preview", transport_mode="OTHER")
            mixed_trip = Trip(user_id=user.user_id, title="Task 1 mixed mode", transport_mode="MIXED")
            null_mode_trip = Trip(user_id=user.user_id, title="Task 1 null mode", transport_mode=None)
            setup.add_all([trip, mixed_trip, null_mode_trip])
            setup.flush()
            plan = TravelPlan(trip_id=trip.trip_id)
            setup.add(plan)
            setup.commit()
            user_id, plan_id = user.user_id, plan.plan_id
            legacy_trip_ids = (trip.trip_id, mixed_trip.trip_id, null_mode_trip.trip_id)

        # These rows predate revision 011. The enum expansion must retain their
        # exact values, including a nullable legacy row.
        command.upgrade(config, "head")
        with Session(engine) as session:
            other, mixed, null_mode = (session.get(Trip, trip_id) for trip_id in legacy_trip_ids)
            assert other.transport_mode == "OTHER"
            assert mixed.transport_mode == "MIXED"
            assert null_mode.transport_mode is None
            walk_trip = Trip(user_id=user_id, title="Task 1 walk mode", transport_mode="WALK")
            session.add(walk_trip)
            session.flush()
            walk_trip.transport_mode = "CAR"
            session.flush()
            walk_trip.transport_mode = "WALK"
            session.commit()
        transport_mode_column = next(
            column for column in inspect(engine).get_columns("trips") if column["name"] == "transport_mode"
        )
        assert set(transport_mode_column["type"].enums) == {
            "PUBLIC_TRANSIT", "CAR", "WALK", "MIXED", "OTHER"
        }

        payload = {
            "plan_id": plan_id, "user_id": user_id, "base_version": 1,
            "reason": "USER_FATIGUE", "feedback_codes": ["TOO_DENSE"],
            "current_itinerary_snapshot": {"items": [{"title": "before"}]},
            "proposed_itinerary": {"items": [{"title": "after"}]},
            "diff": {"changed": ["items"]},
            "expires_at": datetime.utcnow() + timedelta(minutes=30),
        }
        with Session(engine) as session:
            repository = PlanRegenerationPreviewRepository(session)
            rolled_back = repository.create(**payload)
            assert session.in_transaction()
            rolled_back_id = rolled_back.preview_id
            with Session(engine) as observer:
                assert observer.get(PlanRegenerationPreview, rolled_back_id) is None
            session.rollback()

        with Session(engine) as session:
            repository = PlanRegenerationPreviewRepository(session)
            first = repository.create(**payload)
            second = repository.create(**{**payload, "reason": "WEATHER_CHANGE"})
            repository.set_status(first, "CANCELLED")
            session.commit()
            first_id, second_id = first.preview_id, second.preview_id

        with Session(engine) as session:
            repository = PlanRegenerationPreviewRepository(session)
            first = repository.get(first_id)
            assert [preview.preview_id for preview in repository.list_for_plan(plan_id)] == [second_id, first_id]
            assert first.status == "CANCELLED"
            assert first.proposed_itinerary == payload["proposed_itinerary"]
            assert not repository.is_expired(first, datetime.utcnow())
            assert repository.is_expired(first, first.expires_at)
            assert session.get(TravelPlan, plan_id).current_version == 1
            assert session.scalars(select(PlanItem).where(PlanItem.plan_id == plan_id)).all() == []
            assert session.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all() == []
            with pytest.raises(IntegrityError):
                repository.create(**{**payload, "plan_id": plan_id + 9_999_999})
            session.rollback()

        # 011 intentionally refuses a lossy downgrade while a WALK row exists.
        with pytest.raises(RuntimeError, match="contains WALK"):
            command.downgrade(config, "010_plan_regeneration_previews")

        with Session(engine) as cleanup:
            cleanup.delete(cleanup.get(User, user_id))
            cleanup.commit()

        command.downgrade(config, "010_plan_regeneration_previews")
        transport_mode_column = next(
            column for column in inspect(engine).get_columns("trips") if column["name"] == "transport_mode"
        )
        assert "WALK" not in transport_mode_column["type"].enums
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.mysql_integration
def test_preview_service_persists_pending_without_mutating_current_plan(mysql_engine):
    user_id, plan_id = _create_plan_fixture(mysql_engine, "preview")
    try:
        preview_id = _create_preview(mysql_engine, user_id, plan_id)
        # A new connection proves the preview service committed only the preview.
        with Session(mysql_engine) as observer:
            preview = observer.get(PlanRegenerationPreview, preview_id)
            plan = observer.get(TravelPlan, plan_id)
            items = PlanItemRepository(observer).list(plan_id)
            revisions = observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()
            assert preview.status == "PENDING"
            assert preview.current_itinerary_snapshot["items"][0]["title"] == "Original rest"
            assert preview.proposed_itinerary["items"][0]["title"] == "Revised rest"
            assert plan.current_version == 1
            assert [item.title for item in items] == ["Original rest"]
            assert revisions == []
    finally:
        _cleanup_user(mysql_engine, user_id)


@pytest.mark.mysql_integration
def test_approval_service_replaces_items_and_creates_single_revision(mysql_engine):
    user_id, plan_id = _create_plan_fixture(mysql_engine, "approve")
    try:
        preview_id = _create_preview(mysql_engine, user_id, plan_id)
        with Session(mysql_engine) as session:
            response = _approval_service(session).approve(user_id, plan_id, preview_id)
            assert response.status == "APPLIED"
            assert response.current_version == 2
        with Session(mysql_engine) as observer:
            plan = observer.get(TravelPlan, plan_id)
            preview = observer.get(PlanRegenerationPreview, preview_id)
            items = PlanItemRepository(observer).list(plan_id)
            revisions = observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()
            assert plan.current_version == 2
            assert preview.status == "APPLIED" and preview.applied_at is not None
            assert [(item.title, item.start_time, item.end_time) for item in items] == [
                ("Revised rest", time(11), time(12))
            ]
            assert len(revisions) == 1
            assert revisions[0].revision_no == 1
            assert revisions[0].snapshot["items"][0]["title"] == "Original rest"
    finally:
        _cleanup_user(mysql_engine, user_id)


@pytest.mark.mysql_integration
def test_cancel_service_changes_only_preview_status(mysql_engine):
    user_id, plan_id = _create_plan_fixture(mysql_engine, "cancel")
    try:
        preview_id = _create_preview(mysql_engine, user_id, plan_id)
        with Session(mysql_engine) as session:
            response = _approval_service(session).cancel(user_id, plan_id, preview_id)
            assert response.status == "CANCELLED"
        with Session(mysql_engine) as observer:
            plan = observer.get(TravelPlan, plan_id)
            preview = observer.get(PlanRegenerationPreview, preview_id)
            items = PlanItemRepository(observer).list(plan_id)
            revisions = observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()
            assert preview.status == "CANCELLED"
            assert plan.current_version == 1
            assert [item.title for item in items] == ["Original rest"]
            assert revisions == []
    finally:
        _cleanup_user(mysql_engine, user_id)


@pytest.mark.mysql_integration
def test_concurrent_approval_allows_exactly_one_commit(mysql_engine):
    user_id, plan_id = _create_plan_fixture(mysql_engine, "concurrent")
    try:
        preview_id = _create_preview(mysql_engine, user_id, plan_id)
        sessions = sessionmaker(bind=mysql_engine, expire_on_commit=False)
        gate = Barrier(2)
        outcomes = []

        def approve_once():
            session = sessions()
            try:
                gate.wait(timeout=5)
                response = _approval_service(session).approve(user_id, plan_id, preview_id)
                outcomes.append(("ok", response.current_version))
            except Exception as exc:  # Both expected AppError and unexpected failures are inspected below.
                outcomes.append(("error", getattr(exc, "code", type(exc).__name__)))
            finally:
                session.close()

        workers = [Thread(target=approve_once, daemon=True) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        assert not any(worker.is_alive() for worker in workers), "approval threads exceeded the deadlock timeout"
        assert sorted(kind for kind, _ in outcomes) == ["error", "ok"]
        assert {value for kind, value in outcomes if kind == "error"} <= {"PREVIEW_NOT_PENDING", "PREVIEW_VERSION_CONFLICT"}
        with Session(mysql_engine) as observer:
            assert observer.get(TravelPlan, plan_id).current_version == 2
            assert observer.get(PlanRegenerationPreview, preview_id).status == "APPLIED"
            assert len(observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()) == 1
    finally:
        _cleanup_user(mysql_engine, user_id)


@pytest.mark.mysql_integration
def test_approval_rollback_restores_all_rows_after_mid_transaction_error(mysql_engine):
    user_id, plan_id = _create_plan_fixture(mysql_engine, "rollback")
    try:
        preview_id = _create_preview(mysql_engine, user_id, plan_id)
        with Session(mysql_engine) as session:
            service = _approval_service(session)
            def fail_create(*_args, **_kwargs):
                raise SQLAlchemyError("injected plan item insert failure")
            service.items.create = fail_create
            with pytest.raises(Exception) as failure:
                service.approve(user_id, plan_id, preview_id)
            assert getattr(failure.value, "code", None) == "PREVIEW_STORAGE_UNAVAILABLE"
        with Session(mysql_engine) as observer:
            plan = observer.get(TravelPlan, plan_id)
            preview = observer.get(PlanRegenerationPreview, preview_id)
            items = PlanItemRepository(observer).list(plan_id)
            revisions = observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()
            assert plan.current_version == 1
            assert preview.status == "PENDING" and preview.applied_at is None
            assert [item.title for item in items] == ["Original rest"]
            assert revisions == []
    finally:
        _cleanup_user(mysql_engine, user_id)


@pytest.mark.mysql_integration
def test_preview_table_primary_key_foreign_keys_json_and_indexes(mysql_engine):
    schema = inspect(mysql_engine)
    table = "plan_regeneration_previews"
    assert schema.get_pk_constraint(table)["constrained_columns"] == ["preview_id"]
    assert {foreign_key["name"] for foreign_key in schema.get_foreign_keys(table)} == {
        "fk_plan_regeneration_previews_plan", "fk_plan_regeneration_previews_user",
    }
    columns = {column["name"]: column for column in schema.get_columns(table)}
    assert all(str(columns[name]["type"]).upper() == "JSON" for name in {
        "feedback_codes", "current_itinerary_snapshot", "proposed_itinerary", "diff",
    })
    assert {"ix_plan_regeneration_previews_plan_status", "ix_plan_regeneration_previews_expires_at"} <= {
        index["name"] for index in schema.get_indexes(table)
    }


def _place_draft(items):
    return GeneratedPlanDraft([PlanDraftDay(date(2026, 1, 1), items)])


def _place_services(session, draft, candidates, anchor_ids, route_provider=None):
    provider = SimpleNamespace(regenerate_plan=lambda *_args: draft)
    preview = PlanRegenerationPreviewService(session, provider, route_provider=route_provider)
    approval = PlanRegenerationApprovalService(session, SimpleNamespace(), route_provider=route_provider)
    inputs = ({}, {}, [], [], {}, [], anchor_ids, candidates)
    # Candidate and anchor discovery is fixed to data created in this test.
    # All canonicalization and constraint validation remain production methods.
    preview.generation._input = lambda _trip: inputs
    approval.generation._input = lambda _trip: inputs
    return preview, approval


def _create_place_plan_fixture(engine, suffix):
    with Session(engine) as session:
        user = User(nickname=f"task73-{suffix}")
        session.add(user)
        session.flush()
        places = [
            Place(name="Task73 Anchor Museum", category="AT4 관광명소", region="서울", address="서울특별시 중구", latitude=37.5665, longitude=126.9780),
            Place(name="Task73 Optional Gallery", category="AT4 관광명소", region="서울", address="서울특별시 중구", latitude=37.5670, longitude=126.9790),
            Place(name="Task73 Cafe", category="CE7 카페", region="서울", address="서울특별시 중구", latitude=37.5680, longitude=126.9800),
            Place(name="Task73 Restaurant", category="FD6 음식점", region="서울", address="서울특별시 중구", latitude=37.5690, longitude=126.9810),
        ]
        session.add_all(places)
        session.flush()
        anchor, optional, cafe, restaurant = places
        trip = Trip(
            user_id=user.user_id,
            title="Task 7.3 place fixture",
            destination="서울",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 1),
            transport_mode="PUBLIC_TRANSIT",
        )
        session.add(trip)
        session.flush()
        session.add(TripSelectedPlace(trip_id=trip.trip_id, place_id=anchor.place_id, selected_order=1))
        plan = TravelPlan(trip_id=trip.trip_id, status="DRAFT", current_version=1)
        session.add(plan)
        session.flush()
        rows = [
            (anchor, "PLACE", "09:00", "10:00"),
            (optional, "PLACE", "10:30", "11:30"),
            (cafe, "PLACE", "12:00", "13:00"),
            (restaurant, "MEAL", "13:30", "14:30"),
        ]
        for sequence, (place, item_type, start, end) in enumerate(rows, start=1):
            PlanItemRepository(session).create(
                plan.plan_id, place_id=place.place_id, visit_date=date(2026, 1, 1),
                sequence_no=sequence, item_type=item_type, title=place.name,
                start_time=time.fromisoformat(start), end_time=time.fromisoformat(end),
                recommendation_reason="original", validation_status="UNKNOWN",
            )
        PlanItemRepository(session).create(
            plan.plan_id, place_id=None, visit_date=date(2026, 1, 1), sequence_no=5,
            item_type="REST", title="Original rest", start_time=time(15), end_time=time(15, 30),
            recommendation_reason="original", validation_status="UNKNOWN",
        )
        session.commit()
        return user.user_id, plan.plan_id, {place.name: place.place_id for place in places}


def _cleanup_place_fixture(engine, user_id, place_ids):
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is not None:
            session.delete(user)
            session.flush()
        for place_id in place_ids:
            place = session.get(Place, place_id)
            if place is not None:
                session.delete(place)
        session.commit()


def _place_items(ids, *, include_optional=False, rest_end="16:00"):
    entries = [
        PlanDraftItem(1, "PLACE", "model title ignored", ids["Task73 Anchor Museum"], "09:00", "10:00", "anchor"),
    ]
    if include_optional:
        entries.append(PlanDraftItem(2, "PLACE", "model title ignored", ids["Task73 Optional Gallery"], "10:30", "11:30", "optional"))
    entries.extend([
        PlanDraftItem(3, "PLACE", "model title ignored", ids["Task73 Cafe"], "12:00", "13:00", "cafe"),
        PlanDraftItem(4, "MEAL", "model title ignored", ids["Task73 Restaurant"], "13:30", "14:30", "meal"),
        PlanDraftItem(5, "REST", "More rest", None, "15:00", rest_end, "rest"),
    ])
    return entries


@pytest.mark.mysql_integration
def test_place_based_places_preview_and_approval_preserve_anchor_and_foreign_keys(mysql_engine):
    user_id, plan_id, ids = _create_place_plan_fixture(mysql_engine, "places")
    try:
        draft = _place_draft(_place_items(ids, include_optional=False))
        with Session(mysql_engine) as session:
            preview_service, _ = _place_services(session, draft, {
                place_id: session.get(Place, place_id) for place_id in ids.values()
            }, {ids["Task73 Anchor Museum"]})
            response = preview_service.create(user_id, plan_id, PlanRegenerateRequest(
                reason="USER_FATIGUE", instruction="Fewer optional places", feedback_codes=["places"],
            ))
            # UNKNOWN is an honest availability signal, not an approval ban:
            # approval revalidates the persisted draft in the same transaction.
            assert response.validation_status == "UNKNOWN"
            preview_id = response.preview_id
        with Session(mysql_engine) as observer:
            plan = observer.get(TravelPlan, plan_id)
            preview = observer.get(PlanRegenerationPreview, preview_id)
            current_items = PlanItemRepository(observer).list(plan_id)
            assert preview.status == "PENDING"
            assert ids["Task73 Anchor Museum"] in {
                item["place_id"] for item in preview.proposed_itinerary["items"]
            }
            assert ids["Task73 Optional Gallery"] not in {
                item["place_id"] for item in preview.proposed_itinerary["items"]
            }
            assert plan.current_version == 1
            assert {item.place_id for item in current_items if item.place_id} == set(ids.values())
        with Session(mysql_engine) as session:
            _, approval_service = _place_services(session, draft, {
                place_id: session.get(Place, place_id) for place_id in ids.values()
            }, {ids["Task73 Anchor Museum"]})
            approved = approval_service.approve(user_id, plan_id, preview_id)
            assert approved.current_version == 2
        with Session(mysql_engine) as observer:
            plan = observer.get(TravelPlan, plan_id)
            items = PlanItemRepository(observer).list(plan_id)
            revisions = observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()
            assert plan.current_version == 2 and len(revisions) == 1
            assert ids["Task73 Anchor Museum"] in {item.place_id for item in items}
            assert ids["Task73 Optional Gallery"] not in {item.place_id for item in items}
            assert next(item for item in items if item.place_id == ids["Task73 Cafe"]).item_type == "PLACE"
            assert next(item for item in items if item.place_id == ids["Task73 Restaurant"]).item_type == "MEAL"
            assert all(item.place_id is None or observer.get(Place, item.place_id) is not None for item in items)
            assert revisions[0].snapshot["current_version"] == 1
            assert revisions[0].snapshot["items"][0]["place_id"] == ids["Task73 Anchor Museum"]
    finally:
        _cleanup_place_fixture(mysql_engine, user_id, ids.values())


@pytest.mark.mysql_integration
def test_place_based_places_and_rest_goals_reject_unmet_drafts_without_preview(mysql_engine):
    user_id, plan_id, ids = _create_place_plan_fixture(mysql_engine, "goals")
    try:
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            same_places = _place_draft(_place_items(ids, include_optional=True))
            preview_service, _ = _place_services(session, same_places, candidates, {ids["Task73 Anchor Museum"]})
            with pytest.raises(AppError, match="did not reduce"):
                preview_service.create(user_id, plan_id, PlanRegenerateRequest(
                    reason="USER_FATIGUE", instruction="Fewer places", feedback_codes=["places"],
                ))
            assert not session.scalars(select(PlanRegenerationPreview).where(PlanRegenerationPreview.plan_id == plan_id)).all()
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            unchanged_rest = _place_draft(_place_items(ids, include_optional=True, rest_end="15:30"))
            preview_service, _ = _place_services(session, unchanged_rest, candidates, {ids["Task73 Anchor Museum"]})
            with pytest.raises(AppError, match="did not increase"):
                preview_service.create(user_id, plan_id, PlanRegenerateRequest(
                    reason="USER_FATIGUE", instruction="More rest", feedback_codes=["rest"],
                ))
            assert not session.scalars(select(PlanRegenerationPreview).where(PlanRegenerationPreview.plan_id == plan_id)).all()
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            increased_rest = _place_draft(_place_items(ids, include_optional=True, rest_end="16:00"))
            preview_service, _ = _place_services(session, increased_rest, candidates, {ids["Task73 Anchor Museum"]})
            response = preview_service.create(user_id, plan_id, PlanRegenerateRequest(
                reason="USER_FATIGUE", instruction="More rest", feedback_codes=["rest"],
            ))
            assert response.status == "PENDING"
        with Session(mysql_engine) as observer:
            assert observer.get(TravelPlan, plan_id).current_version == 1
            assert len(PlanItemRepository(observer).list(plan_id)) == 5
            assert len(observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()) == 0
            assert len(observer.scalars(select(PlanRegenerationPreview).where(PlanRegenerationPreview.plan_id == plan_id)).all()) == 1
    finally:
        _cleanup_place_fixture(mysql_engine, user_id, ids.values())


@pytest.mark.mysql_integration
def test_place_constraints_and_mocked_route_facts_do_not_fabricate_results(mysql_engine):
    user_id, plan_id, ids = _create_place_plan_fixture(mysql_engine, "constraints")
    try:
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            unknown = _place_draft([PlanDraftItem(1, "PLACE", "Unknown", 999999999, "09:00", "10:00", "bad")])
            preview_service, _ = _place_services(session, unknown, candidates, {ids["Task73 Anchor Museum"]})
            with pytest.raises(AppError):
                preview_service.create(user_id, plan_id, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Reject unknown place"))
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            missing_anchor = _place_draft([PlanDraftItem(1, "PLACE", "Optional", ids["Task73 Optional Gallery"], "09:00", "10:00", "missing")])
            preview_service, _ = _place_services(session, missing_anchor, candidates, {ids["Task73 Anchor Museum"]})
            with pytest.raises(AppError):
                preview_service.create(user_id, plan_id, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Reject missing anchor"))
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            overlapping = _place_draft([
                PlanDraftItem(1, "PLACE", "Anchor", ids["Task73 Anchor Museum"], "09:00", "10:00", "anchor"),
                PlanDraftItem(2, "PLACE", "Optional", ids["Task73 Optional Gallery"], "09:30", "10:30", "overlap"),
            ])
            preview_service, _ = _place_services(session, overlapping, candidates, {ids["Task73 Anchor Museum"]})
            with pytest.raises(AppError) as error:
                preview_service.create(user_id, plan_id, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Reject overlap"))
            assert error.value.code == "TIME_CONFLICT"
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            duplicate = _place_draft([
                PlanDraftItem(1, "PLACE", "Anchor", ids["Task73 Anchor Museum"], "09:00", "10:00", "anchor"),
                PlanDraftItem(2, "PLACE", "Optional", ids["Task73 Optional Gallery"], "10:30", "11:30", "optional"),
                PlanDraftItem(3, "PLACE", "Duplicate", ids["Task73 Optional Gallery"], "11:35", "11:50", "duplicate"),
                PlanDraftItem(4, "PLACE", "Cafe", ids["Task73 Cafe"], "12:00", "13:00", "cafe"),
                PlanDraftItem(5, "MEAL", "Restaurant", ids["Task73 Restaurant"], "13:30", "14:30", "meal"),
            ])
            preview_service, _ = _place_services(session, duplicate, candidates, {ids["Task73 Anchor Museum"]})
            response = preview_service.create(user_id, plan_id, PlanRegenerateRequest(reason="WEATHER_CHANGE", instruction="Normalize duplicate"))
            proposed = response.proposed_itinerary["items"]
            proposed_place_ids = [item["place_id"] for item in proposed if item["place_id"] is not None]
            assert len(proposed_place_ids) == len(set(proposed_place_ids))
            assert any(item["item_type"] == "FREE_TIME" and item["place_id"] is None for item in proposed)
        class VerifiedRoutes:
            def route(self, *_args):
                return RouteEstimate(100, "PUBLIC_TRANSIT", walking_seconds=50)
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            draft = _place_draft(_place_items(ids, include_optional=False))
            preview_service, _ = _place_services(session, draft, candidates, {ids["Task73 Anchor Museum"]}, VerifiedRoutes())
            response = preview_service.create(user_id, plan_id, PlanRegenerateRequest(
                reason="USER_FATIGUE", instruction="Reduce walking and travel", feedback_codes=["walking", "travel"],
            ))
            assert response.status == "PENDING" and response.validation_status == "UNKNOWN"
        class PartialRoutes:
            def route(self, *_args):
                return None
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            draft = _place_draft(_place_items(ids, include_optional=False))
            preview_service, _ = _place_services(session, draft, candidates, {ids["Task73 Anchor Museum"]}, PartialRoutes())
            response = preview_service.create(user_id, plan_id, PlanRegenerateRequest(
                reason="USER_FATIGUE", instruction="Reduce walking and travel", feedback_codes=["walking", "travel"],
            ))
            assert response.validation_status == "UNKNOWN"
        with Session(mysql_engine) as observer:
            assert observer.get(TravelPlan, plan_id).current_version == 1
            assert [item.title for item in PlanItemRepository(observer).list(plan_id)][0] == "Task73 Anchor Museum"
            assert len(observer.scalars(select(PlanRegenerationPreview).where(PlanRegenerationPreview.plan_id == plan_id)).all()) == 3
    finally:
        _cleanup_place_fixture(mysql_engine, user_id, ids.values())


@pytest.mark.mysql_integration
def test_flutter_regeneration_preview_http_contract_on_mysql(mysql_engine, monkeypatch, caplog):
    """Real FastAPI routes + JWT + MySQL; only AI/route providers are deterministic mocks."""
    from app.api.v1 import plans as plan_routes
    from app.services.plan_regeneration_approval_service import PlanRegenerationApprovalService
    from app.services.plan_regeneration_preview_service import PlanRegenerationPreviewService

    user_id, plan_id, ids = _create_place_plan_fixture(mysql_engine, "http")
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("JWT_SECRET_KEY", "task74b-http-test-secret")
    get_settings.cache_clear()
    candidates = {place_id: None for place_id in ids.values()}
    with Session(mysql_engine) as session:
        candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}

    def draft_for(instruction):
        unchanged_rest = instruction == "unchanged rest"
        rest_end = "15:30" if unchanged_rest else ("16:30" if instruction == "fewer places again" else "16:00")
        return _place_draft(_place_items(
            ids, include_optional=unchanged_rest,
            rest_end=rest_end,
        ))

    class DeterministicProvider:
        def regenerate_plan(self, *_args):
            return draft_for(_args[7])

    def service_inputs(_trip):
        return {}, {}, [], [], {}, [], {ids["Task73 Anchor Museum"]}, candidates

    def preview_service():
        session = Session(mysql_engine)
        service = PlanRegenerationPreviewService(session, DeterministicProvider())
        service.generation._input = service_inputs
        try:
            yield service
        finally:
            session.close()

    def approval_service():
        session = Session(mysql_engine)
        service = PlanRegenerationApprovalService(session, DeterministicProvider())
        service.generation._input = service_inputs
        try:
            yield service
        finally:
            session.close()

    def database_session():
        session = Session(mysql_engine)
        try:
            yield session
        finally:
            session.close()

    application = create_app(get_settings())
    application.dependency_overrides[get_db] = database_session
    # The HTTP route, schemas, database session, and JWT authentication remain
    # production code. These overrides only prevent EXAONE/Kakao network calls.
    application.dependency_overrides[plan_routes.get_preview_service] = preview_service
    application.dependency_overrides[plan_routes.get_approval_service] = approval_service
    token = create_access_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}", "X-Request-ID": "task74b-http"}
    try:
        with TestClient(application) as client:
            unauthenticated = client.get(f"/api/v1/plans/{plan_id}")
            assert unauthenticated.status_code == 401
            assert unauthenticated.json()["error"]["code"] == "UNAUTHORIZED"

            before = client.get(f"/api/v1/plans/{plan_id}", headers=headers)
            assert before.status_code == 200
            assert before.json()["current_version"] == 1
            assert len(before.json()["days"][0]["items"]) == 5

            preview = client.post(
                f"/api/v1/plans/{plan_id}/regeneration-previews", headers=headers,
                json={"reason": "USER_FATIGUE", "instruction": "fewer places", "feedback_codes": ["places", "rest"]},
            )
            assert preview.status_code == 200
            preview_body = preview.json()
            preview_id = preview_body["preview_id"]
            assert preview_body["base_version"] == 1
            assert preview_body["status"] == "PENDING"

            with Session(mysql_engine) as observer:
                assert observer.get(TravelPlan, plan_id).current_version == 1
                assert len(PlanItemRepository(observer).list(plan_id)) == 5

            approved = client.post(
                f"/api/v1/plans/{plan_id}/regeneration-previews/{preview_id}/approve", headers=headers,
            )
            assert approved.status_code == 200
            assert approved.json() == {"preview_id": preview_id, "plan_id": plan_id, "status": "APPLIED", "current_version": 2, "approved": True}
            duplicate = client.post(
                f"/api/v1/plans/{plan_id}/regeneration-previews/{preview_id}/approve", headers=headers,
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["error"]["code"] == "PREVIEW_NOT_PENDING"

            after = client.get(f"/api/v1/plans/{plan_id}", headers=headers)
            assert after.status_code == 200
            assert after.json()["current_version"] == 2
            assert len(after.json()["days"][0]["items"]) == 4

            cancellation_preview = client.post(
                f"/api/v1/plans/{plan_id}/regeneration-previews", headers=headers,
                json={"reason": "USER_FATIGUE", "instruction": "fewer places again", "feedback_codes": ["rest"]},
            )
            assert cancellation_preview.status_code == 200
            cancellation_id = cancellation_preview.json()["preview_id"]
            cancelled = client.post(
                f"/api/v1/plans/{plan_id}/regeneration-previews/{cancellation_id}/cancel", headers=headers,
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "CANCELLED"
            with Session(mysql_engine) as observer:
                assert observer.get(TravelPlan, plan_id).current_version == 2
                assert len(PlanItemRepository(observer).list(plan_id)) == 4

            unmet_goal = client.post(
                f"/api/v1/plans/{plan_id}/regeneration-previews", headers=headers,
                json={"reason": "USER_FATIGUE", "instruction": "unchanged rest", "feedback_codes": ["rest"]},
            )
            assert unmet_goal.status_code == 422
            assert unmet_goal.json()["error"]["code"] == "FEEDBACK_GOAL_NOT_MET"

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "request_id=task74b-http" in messages
        assert "preview_create_succeeded" in messages
        assert "preview_approved" in messages and "preview_cancelled" in messages
        assert "preview_create_failed" in messages and "FEEDBACK_GOAL_NOT_MET" in messages
    finally:
        application.dependency_overrides.clear()
        _cleanup_place_fixture(mysql_engine, user_id, ids.values())


@pytest.mark.mysql_integration
def test_preview_travel_minutes_are_stored_and_reloaded_after_approval(mysql_engine):
    """Fake route facts only: KNOWN legs persist exactly as previewed, UNKNOWN stays NULL."""
    from app.services.external.routing.cached_provider import CachedRouteProvider
    from app.services.plan_revision_service import PlanRevisionService

    user_id, plan_id, ids = _create_place_plan_fixture(mysql_engine, "travel")

    class DestinationRoutes:
        """Known only for the leg ending at the cafe; no fact for the restaurant leg."""

        def __init__(self, cafe_seconds):
            self.cafe_seconds = cafe_seconds
            self.calls = 0

        def route(self, _origin_lat, _origin_lng, dest_lat, dest_lng, mode):
            self.calls += 1
            if (round(dest_lat, 4), round(dest_lng, 4)) == (37.568, 126.98):
                return RouteEstimate(self.cafe_seconds, mode, walking_seconds=300, transfer_count=0)
            return None

    try:
        draft = _place_draft(_place_items(ids, include_optional=False))
        preview_routes = DestinationRoutes(cafe_seconds=1250)  # 20.8 min -> 21
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            preview_service, _ = _place_services(
                session, draft, candidates, {ids["Task73 Anchor Museum"]}, CachedRouteProvider(preview_routes),
            )
            response = preview_service.create(user_id, plan_id, PlanRegenerateRequest(
                reason="USER_FATIGUE", instruction="Fewer optional places", feedback_codes=["places"],
            ))
            preview_id = response.preview_id
        assert preview_routes.calls == 2  # anchor->cafe and cafe->restaurant, once each

        with Session(mysql_engine) as observer:
            proposed = {
                item["place_id"]: item
                for item in observer.get(PlanRegenerationPreview, preview_id).proposed_itinerary["items"]
            }
            cafe = proposed[ids["Task73 Cafe"]]
            restaurant = proposed[ids["Task73 Restaurant"]]
            anchor = proposed[ids["Task73 Anchor Museum"]]
            assert (cafe["transport_mode_from_previous"], cafe["travel_minutes_from_previous"]) == ("PUBLIC_TRANSIT", 21)
            assert (restaurant["transport_mode_from_previous"], restaurant["travel_minutes_from_previous"]) == (None, None)
            assert (anchor["transport_mode_from_previous"], anchor["travel_minutes_from_previous"]) == (None, None)
            assert {item.travel_minutes_from_previous for item in PlanItemRepository(observer).list(plan_id)} == {None}

        # Approval revalidates with a different live value; the previewed value must be stored.
        with Session(mysql_engine) as session:
            candidates = {place_id: session.get(Place, place_id) for place_id in ids.values()}
            _, approval_service = _place_services(
                session, draft, candidates, {ids["Task73 Anchor Museum"]}, CachedRouteProvider(DestinationRoutes(cafe_seconds=3000)),
            )
            assert approval_service.approve(user_id, plan_id, preview_id).current_version == 2

        with Session(mysql_engine) as observer:
            items = {item.place_id: item for item in PlanItemRepository(observer).list(plan_id)}
            revisions = observer.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id)).all()
            cafe, restaurant = items[ids["Task73 Cafe"]], items[ids["Task73 Restaurant"]]
            assert (cafe.transport_mode_from_previous, cafe.travel_minutes_from_previous, cafe.travel_distance_meters_from_previous) == ("PUBLIC_TRANSIT", 21, None)
            assert (restaurant.transport_mode_from_previous, restaurant.travel_minutes_from_previous) == (None, None)
            assert items[ids["Task73 Anchor Museum"]].travel_minutes_from_previous is None
            assert items[None].item_type == "REST" and items[None].travel_minutes_from_previous is None
            assert ids["Task73 Optional Gallery"] not in items
            assert observer.get(TravelPlan, plan_id).current_version == 2 and len(revisions) == 1
            assert revisions[0].snapshot["current_version"] == 1

        # Reload through the plan detail response used by GET /plans/{plan_id}.
        with Session(mysql_engine) as session:
            detail = PlanRevisionService(session, SimpleNamespace()).get(user_id, plan_id)
            statuses = {item.place_id: (item.travel_status, item.travel_minutes_from_previous) for item in detail.days[0].items}
            assert statuses == {
                ids["Task73 Anchor Museum"]: ("NONE", None),
                ids["Task73 Cafe"]: ("KNOWN", 21),
                ids["Task73 Restaurant"]: ("UNKNOWN", None),
                None: ("NONE", None),
            }
    finally:
        _cleanup_place_fixture(mysql_engine, user_id, ids.values())
