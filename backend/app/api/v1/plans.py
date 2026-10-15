from typing import Annotated
from fastapi import APIRouter, Depends
from app.db.session import get_db
from app.dependencies import CurrentUser
from app.schemas.plan import PlanConfirmResponse, PlanDetailResponse, PlanEditRequest, PlanEditResponse, PlanGenerateRequest, PlanGenerateResponse, PlanRegenerateRequest, PlanRegenerationPreviewResponse, PlanRegenerationPreviewApplyResponse
from app.core.config import get_settings
from app.services.external.factory import provide_place_provider, provide_plan_generation_provider, provide_plan_regeneration_preview_provider, provide_route_provider, provide_naver_cafe_evidence_provider, provide_tour_destination_image_provider
from app.services.plan_edit_service import PlanEditService
from app.services.plan_generation_service import PlanGenerationService
from app.services.plan_revision_service import PlanRevisionService
from app.services.plan_regeneration_preview_service import PlanRegenerationPreviewService
from app.services.plan_regeneration_approval_service import PlanRegenerationApprovalService
router = APIRouter(tags=["plans"])
def get_service(db=Depends(get_db), provider=Depends(provide_plan_generation_provider), place_provider=Depends(provide_place_provider), route_provider=Depends(provide_route_provider), naver_cafe_provider=Depends(provide_naver_cafe_evidence_provider), tour_hours_provider=Depends(provide_tour_destination_image_provider)): return PlanGenerationService(db, provider, place_provider, route_provider, naver_cafe_provider, tour_hours_provider, get_settings().tour_hours_max_places_per_request)
def get_edit_service(db=Depends(get_db)): return PlanEditService(db)
def get_revision_service(db=Depends(get_db), provider=Depends(provide_plan_generation_provider), place_provider=Depends(provide_place_provider), route_provider=Depends(provide_route_provider)): return PlanRevisionService(db, provider, place_provider, route_provider)
def get_preview_service(db=Depends(get_db), provider=Depends(provide_plan_regeneration_preview_provider), route_provider=Depends(provide_route_provider), place_provider=Depends(provide_place_provider)): return PlanRegenerationPreviewService(db, provider, route_provider=route_provider, place_provider=place_provider)
def get_approval_service(db=Depends(get_db), provider=Depends(provide_plan_generation_provider), route_provider=Depends(provide_route_provider)): return PlanRegenerationApprovalService(db, provider, route_provider=route_provider)
Service = Annotated[PlanGenerationService, Depends(get_service)]
EditService = Annotated[PlanEditService, Depends(get_edit_service)]
RevisionService = Annotated[PlanRevisionService, Depends(get_revision_service)]
PreviewService = Annotated[PlanRegenerationPreviewService, Depends(get_preview_service)]
ApprovalService = Annotated[PlanRegenerationApprovalService, Depends(get_approval_service)]
@router.post("/trips/{trip_id}/plans/generate", response_model=PlanGenerateResponse)
def generate_plan(trip_id: int, request: PlanGenerateRequest, user: CurrentUser, service: Service): return service.generate(user.user_id, trip_id, request.selected_place_ids)
@router.post("/plans/{plan_id}/redraft", response_model=PlanGenerateResponse)
def redraft_plan(plan_id: int, user: CurrentUser, service: Service): return service.redraft(user.user_id, plan_id)
@router.post("/plans/{plan_id}/edit", response_model=PlanEditResponse)
def edit_plan(plan_id: int, request: PlanEditRequest, user: CurrentUser, service: EditService): return service.edit(user.user_id, plan_id, request)
@router.get("/trips/{trip_id}/plan", response_model=PlanDetailResponse)
def get_trip_plan(trip_id: int, user: CurrentUser, service: RevisionService): return service.get_for_trip(user.user_id, trip_id)
@router.get("/plans/{plan_id}", response_model=PlanDetailResponse)
def get_plan(plan_id: int, user: CurrentUser, service: RevisionService): return service.get(user.user_id, plan_id)
@router.post("/plans/{plan_id}/regenerate", response_model=PlanDetailResponse)
def regenerate_plan(plan_id: int, request: PlanRegenerateRequest, user: CurrentUser, service: RevisionService): return service.regenerate(user.user_id, plan_id, request)
@router.post("/plans/{plan_id}/regeneration-previews", response_model=PlanRegenerationPreviewResponse)
def create_regeneration_preview(plan_id: int, request: PlanRegenerateRequest, user: CurrentUser, service: PreviewService): return service.create(user.user_id, plan_id, request)
@router.post("/plans/{plan_id}/regeneration-previews/{preview_id}/approve", response_model=PlanRegenerationPreviewApplyResponse)
def approve_regeneration_preview(plan_id: int, preview_id: int, user: CurrentUser, service: ApprovalService): return service.approve(user.user_id, plan_id, preview_id)
@router.post("/plans/{plan_id}/regeneration-previews/{preview_id}/cancel", response_model=PlanRegenerationPreviewApplyResponse)
def cancel_regeneration_preview(plan_id: int, preview_id: int, user: CurrentUser, service: ApprovalService): return service.cancel(user.user_id, plan_id, preview_id)
@router.post("/plans/{plan_id}/confirm", response_model=PlanConfirmResponse)
def confirm_plan(plan_id: int, user: CurrentUser, service: RevisionService): return service.confirm(user.user_id, plan_id)
