"""Plan models matching docs/03_database/03_db_schema.md."""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime,
                        Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text,
                        Time, UniqueConstraint, text)
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TravelPlan(Base):
    __tablename__ = 'travel_plans'
    __table_args__ = (
        UniqueConstraint('trip_id', name='uq_travel_plans_trip'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'},
    )

    plan_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, nullable=False
    )
    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('trips.trip_id', name='fk_travel_plans_trip', ondelete='CASCADE'), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum('DRAFT', 'CONFIRMED', 'ARCHIVED', validate_strings=True), nullable=False, server_default=text("'DRAFT'")
    )
    current_version: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False, server_default=text('1')
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')
    )

    # Unidirectional navigation only; deletion semantics belong to DB foreign keys.
    trip = relationship('Trip', foreign_keys=[trip_id])

class PlanItem(Base):
    __tablename__ = 'plan_items'
    __table_args__ = (
        UniqueConstraint('plan_id', 'visit_date', 'sequence_no', name='uq_plan_items_order'),
        CheckConstraint('end_time IS NULL OR start_time IS NULL OR end_time >= start_time', name='chk_plan_items_time'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'},
    )

    item_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('travel_plans.plan_id', name='fk_plan_items_plan', ondelete='CASCADE'), nullable=False
    )
    place_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey('places.place_id', name='fk_plan_items_place', ondelete='SET NULL'), nullable=True
    )
    visit_date: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False
    )
    item_type: Mapped[str] = mapped_column(
        Enum('PLACE', 'MEAL', 'REST', 'FREE_TIME', validate_strings=True), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    start_time: Mapped[time | None] = mapped_column(
        Time, nullable=True
    )
    end_time: Mapped[time | None] = mapped_column(
        Time, nullable=True
    )
    transport_mode_from_previous: Mapped[str | None] = mapped_column(
        Enum('WALK', 'PUBLIC_TRANSIT', 'CAR', 'TAXI', 'OTHER', validate_strings=True), nullable=True
    )
    travel_minutes_from_previous: Mapped[int | None] = mapped_column(
        INTEGER(unsigned=True), nullable=True
    )
    travel_distance_meters_from_previous: Mapped[int | None] = mapped_column(
        INTEGER(unsigned=True), nullable=True
    )
    recommendation_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    # The traveler's own description (UPDATE_ITEM); shown instead of the
    # address line when set.  Migration 012.
    user_note: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    validation_status: Mapped[str] = mapped_column(
        Enum('VALID', 'WARNING', 'UNKNOWN', validate_strings=True), nullable=False, server_default=text("'UNKNOWN'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')
    )

    # Unidirectional navigation only; deletion semantics belong to DB foreign keys.
    plan = relationship('TravelPlan', foreign_keys=[plan_id])
    place = relationship('Place', foreign_keys=[place_id])

class PlanRevision(Base):
    __tablename__ = 'plan_revisions'
    __table_args__ = (
        UniqueConstraint('plan_id', 'revision_no', name='uq_plan_revisions_plan_no'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'},
    )

    revision_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('travel_plans.plan_id', name='fk_plan_revisions_plan', ondelete='CASCADE'), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(
        INTEGER(unsigned=True), nullable=False
    )
    revision_type: Mapped[str] = mapped_column(
        Enum('USER_EDIT', 'AI_REGENERATE', 'USER_FATIGUE', 'WEATHER_CHANGE', 'OTHER', validate_strings=True), nullable=False
    )
    instruction: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    snapshot: Mapped[Any] = mapped_column(
        JSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')
    )

    # Unidirectional navigation only; deletion semantics belong to DB foreign keys.
    plan = relationship('TravelPlan', foreign_keys=[plan_id])

class PlanRegenerationPreview(Base):
    __tablename__ = 'plan_regeneration_previews'
    __table_args__ = (
        Index('ix_plan_regeneration_previews_plan_status', 'plan_id', 'status'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'},
    )
    preview_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('travel_plans.plan_id', name='fk_plan_regeneration_previews_plan', ondelete='CASCADE'), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.user_id', name='fk_plan_regeneration_previews_user', ondelete='CASCADE'), nullable=False)
    base_version: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    status: Mapped[str] = mapped_column(Enum('PENDING', 'APPLIED', 'CANCELLED', 'EXPIRED', validate_strings=True), nullable=False, server_default=text("'PENDING'"))
    reason: Mapped[str] = mapped_column(Enum('USER_FATIGUE', 'WEATHER_CHANGE', validate_strings=True), nullable=False)
    feedback_codes: Mapped[Any] = mapped_column(JSON, nullable=False)
    current_itinerary_snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
    proposed_itinerary: Mapped[Any] = mapped_column(JSON, nullable=False)
    diff: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan = relationship('TravelPlan', foreign_keys=[plan_id])
    user = relationship('User', foreign_keys=[user_id])

class PlanValidationIssue(Base):
    __tablename__ = 'plan_validation_issues'
    __table_args__ = (
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'},
    )

    validation_issue_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('travel_plans.plan_id', name='fk_validation_issues_plan', ondelete='CASCADE'), nullable=False
    )
    item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey('plan_items.item_id', name='fk_validation_issues_item', ondelete='SET NULL'), nullable=True
    )
    issue_type: Mapped[str] = mapped_column(
        Enum('PLACE_NOT_FOUND', 'OPENING_HOURS_UNKNOWN', 'PLACE_CLOSED', 'TRAVEL_TIME_UNKNOWN', 'TIME_CONFLICT', 'WEATHER_WARNING', 'ACCESSIBILITY_WARNING', 'OTHER', validate_strings=True), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        Enum('INFO', 'WARNING', 'CRITICAL', validate_strings=True), nullable=False
    )
    message: Mapped[str] = mapped_column(
        String(1000), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')
    )

    # Unidirectional navigation only; deletion semantics belong to DB foreign keys.
    plan = relationship('TravelPlan', foreign_keys=[plan_id])
    item = relationship('PlanItem', foreign_keys=[item_id])
