from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.plan import PlanItem, PlanRegenerationPreview, PlanRevision, PlanValidationIssue, TravelPlan
class PlanRepository:
    def __init__(self, session: Session): self.session = session
    def get(self, plan_id): return self.session.get(TravelPlan, plan_id)
    def get_for_update(self, plan_id): return self.session.scalar(select(TravelPlan).where(TravelPlan.plan_id == plan_id).with_for_update())
    def get_by_trip_id(self, trip_id: int): return self.session.scalar(select(TravelPlan).where(TravelPlan.trip_id == trip_id))
    def create(self, trip_id: int):
        plan = TravelPlan(trip_id=trip_id, status="DRAFT", generated_at=datetime.utcnow()); self.session.add(plan); self.session.flush(); return plan
class PlanItemRepository:
    def __init__(self, session: Session): self.session = session
    def get(self, item_id): return self.session.get(PlanItem, item_id)
    def list(self, plan_id): return list(self.session.scalars(select(PlanItem).where(PlanItem.plan_id == plan_id).order_by(PlanItem.visit_date, PlanItem.sequence_no, PlanItem.item_id)))
    def create(self, plan_id, **fields):
        item = PlanItem(plan_id=plan_id, **fields); self.session.add(item); self.session.flush(); return item
    def delete(self, item): self.session.delete(item); self.session.flush()
    def update(self, item, **fields):
        for field, value in fields.items(): setattr(item, field, value)
        self.session.flush(); return item
class PlanRevisionRepository:
    def __init__(self, session: Session): self.session = session
    def create(self, plan_id, **fields):
        revision = PlanRevision(plan_id=plan_id, **fields); self.session.add(revision); self.session.flush(); return revision
    def list_newest_first(self, plan_id):
        return list(self.session.scalars(select(PlanRevision).where(PlanRevision.plan_id == plan_id).order_by(PlanRevision.revision_id.desc())))
class PlanRegenerationPreviewRepository:
    def __init__(self, session: Session): self.session = session
    def create(self, **fields):
        preview = PlanRegenerationPreview(**fields); self.session.add(preview); self.session.flush(); return preview
    def get(self, preview_id): return self.session.get(PlanRegenerationPreview, preview_id)
    def list_for_plan(self, plan_id): return list(self.session.scalars(select(PlanRegenerationPreview).where(PlanRegenerationPreview.plan_id == plan_id).order_by(PlanRegenerationPreview.created_at.desc())))
    def get_for_update(self, preview_id): return self.session.scalar(select(PlanRegenerationPreview).where(PlanRegenerationPreview.preview_id == preview_id).with_for_update())
    @staticmethod
    def is_expired(preview, now): return preview.expires_at <= now
    def set_status(self, preview, status, **fields):
        preview.status = status
        for key, value in fields.items(): setattr(preview, key, value)
        self.session.flush(); return preview
class PlanValidationIssueRepository:
    def __init__(self, session: Session): self.session = session
    def list_open(self, plan_id): return list(self.session.scalars(select(PlanValidationIssue).where(PlanValidationIssue.plan_id == plan_id, PlanValidationIssue.resolved_at.is_(None))))
    def resolve_open(self, plan_id):
        for issue in self.list_open(plan_id): issue.resolved_at = datetime.utcnow()
        self.session.flush()
    def create(self, plan_id, **fields):
        issue = PlanValidationIssue(plan_id=plan_id, **fields); self.session.add(issue); self.session.flush(); return issue
