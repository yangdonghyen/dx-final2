from datetime import date, time
from types import SimpleNamespace
import pytest
from app.core.exceptions import AppError
from app.schemas.plan import PlanEditRequest

class Session:
    def __init__(self):
        self.plan=SimpleNamespace(plan_id=10,trip_id=1,status="DRAFT",current_version=1); self.trip=SimpleNamespace(trip_id=1,user_id=1,status="DRAFT",start_date=date(2026,1,1),end_date=date(2026,1,2)); self.items=[row(101,1,1),row(102,2,2),row(103,1,3,plan_id=11)]; self.places={1:SimpleNamespace(place_id=1,name="Museum"),2:SimpleNamespace(place_id=2,name="Cafe")}; self.revisions=[]; self.commits=0; self.rollbacks=0; self.validations=0
    def flush(self): pass
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
def row(item_id, sequence, hour, plan_id=10): return SimpleNamespace(item_id=item_id,plan_id=plan_id,place_id=1,visit_date=date(2026,1,1),sequence_no=sequence,item_type="PLACE",title=f"Place {item_id}",start_time=time(hour),end_time=time(hour+1),transport_mode_from_previous=None,travel_minutes_from_previous=None,travel_distance_meters_from_previous=None,recommendation_reason=None,validation_status="UNKNOWN")
class Plans:
    def __init__(self,s): self.s=s
    def get(self, plan_id): return self.s.plan if plan_id==10 else None
class Trips:
    def __init__(self,s): self.s=s
    def get(self, trip_id): return self.s.trip if trip_id==1 else None
class Items:
    def __init__(self,s): self.s=s
    def get(self,item_id): return next((x for x in self.s.items if x.item_id==item_id),None)
    def list(self,plan_id): return sorted([x for x in self.s.items if x.plan_id==plan_id],key=lambda x:(x.visit_date,x.sequence_no,x.item_id))
    def create(self,plan_id,**fields):
        item=SimpleNamespace(**{"item_id":max(x.item_id for x in self.s.items)+1,"plan_id":plan_id,"transport_mode_from_previous":None,"travel_minutes_from_previous":None,"travel_distance_meters_from_previous":None,"recommendation_reason":None,**fields}); self.s.items.append(item); return item
    def delete(self,item): self.s.items.remove(item)
    def update(self,item,**fields):
        for key,value in fields.items(): setattr(item,key,value)
        return item
class Revisions:
    def __init__(self,s): self.s=s
    def create(self,plan_id,**fields): self.s.revisions.append(SimpleNamespace(plan_id=plan_id,**fields))
class Places:
    def __init__(self,s): self.s=s
    def get(self,place_id): return self.s.places.get(place_id)
class Validation:
    def __init__(self,s): self.s=s
    def validate(self,plan,trip): self.s.validations+=1; return []
class NoMembers:
    def __init__(self,s): pass
    def get_member(self,trip_id,user_id): return None
@pytest.fixture
def edit(monkeypatch):
    import app.services.plan_edit_service as mod
    for name, value in {"PlanRepository":Plans,"TripRepository":Trips,"PlanItemRepository":Items,"PlanRevisionRepository":Revisions,"PlaceRepository":Places,"PlanValidationService":Validation,"TripCompanionRepository":NoMembers}.items(): monkeypatch.setattr(mod,name,value)
    session=Session(); return mod.PlanEditService(session),session

def request(operation,**values): return PlanEditRequest(operation=operation,**values)
def test_delete_reorders_saves_revision_validates_and_increments_version(edit):
    service,s=edit; result=service.edit(1,10,request("DELETE_PLACE",item_id=101))
    assert [item.item_id for item in s.items if item.plan_id==10]==[102] and s.items[0].sequence_no==1
    assert result.current_version==2 and s.validations==1 and s.commits==1 and s.revisions[0].revision_type=="USER_EDIT" and s.revisions[0].snapshot["items"][0]["item_id"]==101
def test_delete_rejects_missing_and_other_plan_items_without_version_change(edit):
    service,s=edit
    for item_id,code in [(999,"PLAN_ITEM_NOT_FOUND"),(103,"PLAN_ITEM_PLAN_MISMATCH")]:
        with pytest.raises(AppError) as error: service.edit(1,10,request("DELETE_PLACE",item_id=item_id))
        assert error.value.code==code and s.plan.current_version==1

def test_replace_changes_only_requested_item_and_rejects_unknown_place(edit):
    service,s=edit; service.edit(1,10,request("REPLACE_PLACE",item_id=101,new_place_id=2))
    assert s.items[0].place_id==2 and s.items[0].title=="Cafe" and s.items[1].place_id==1
    with pytest.raises(AppError) as error: service.edit(1,10,request("REPLACE_PLACE",item_id=102,new_place_id=999))
    assert error.value.code=="PLACE_NOT_FOUND" and s.plan.current_version==2

def test_add_rest_inserts_after_item_and_runs_validation(edit):
    service,s=edit; result=service.edit(1,10,request("ADD_REST",day=1,after_item_id=101,duration_minutes=30))
    rows=sorted((x for x in s.items if x.plan_id==10), key=lambda x:x.sequence_no); assert [(x.item_type,x.sequence_no) for x in rows]==[("PLACE",1),("REST",2),("PLACE",3)]
    assert rows[1].place_id is None and rows[1].start_time==time(2) and rows[1].end_time==time(2,30) and result.current_version==2 and s.validations==1
def test_add_rest_validation_issue_is_preserved(edit,monkeypatch):
    service,s=edit
    def warning(plan,trip): s.validations+=1; return [(s.items[0],"TIME_CONFLICT","CRITICAL","Plan items overlap")]
    service.validation.validate=warning; service.edit(1,10,request("ADD_REST",day=1,after_item_id=101,duration_minutes=30))
    assert s.validations==1 and s.plan.current_version==2

def test_add_rest_time_conflict_reaches_validation_service(edit):
    service,s=edit; s.items[1].start_time=time(2,15); s.items[1].end_time=time(3)
    captured=[]
    def validate(plan,trip):
        captured.append((plan,trip)); return [(s.items[1],"TIME_CONFLICT","CRITICAL","Plan items overlap")]
    service.validation.validate=validate
    service.edit(1,10,request("ADD_REST",day=1,after_item_id=101,duration_minutes=30))
    assert captured and s.plan.current_version==2
def test_reorder_requires_complete_unique_day_item_list(edit):
    service,s=edit; service.edit(1,10,request("REORDER",day=1,item_ids=[102,101]))
    assert [(x.item_id,x.sequence_no) for x in sorted((x for x in s.items if x.plan_id==10), key=lambda x:x.sequence_no)]==[(102,1),(101,2)]
    for ids in ([101,101],[101]):
        with pytest.raises(AppError) as error: service.edit(1,10,request("REORDER",day=1,item_ids=ids))
        assert error.value.code=="INVALID_EDIT_PAYLOAD"
def test_owner_archived_and_failed_edits_rollback(edit):
    service,s=edit
    with pytest.raises(AppError) as error: service.edit(2,10,request("DELETE_PLACE",item_id=101))
    assert error.value.code=="FORBIDDEN" and s.rollbacks==0
    s.trip.status="ARCHIVED"
    with pytest.raises(AppError) as error: service.edit(1,10,request("DELETE_PLACE",item_id=101))
    assert error.value.code=="TRIP_ARCHIVED" and s.rollbacks==0
    s.trip.status="DRAFT"
    with pytest.raises(AppError): service.edit(1,10,request("ADD_REST",day=1,after_item_id=101,duration_minutes=2000))
    assert s.plan.current_version==1 and s.rollbacks==1
def test_edit_endpoint_is_registered_and_requires_authentication(client):
    assert "/api/v1/plans/{plan_id}/edit" in client.get("/openapi.json").json()["paths"]
    assert client.post("/api/v1/plans/1/edit",json={"operation":"DELETE_PLACE","item_id":1}).status_code==401

def test_add_place_inserts_after_item_and_pushes_later_stops(edit):
    service,s=edit; result=service.edit(1,10,request("ADD_PLACE",day=1,after_item_id=101,new_place_id=2,duration_minutes=60))
    rows=sorted((x for x in s.items if x.plan_id==10), key=lambda x:x.sequence_no)
    assert [(x.title,x.sequence_no,x.start_time,x.end_time) for x in rows]==[("Place 101",1,time(1),time(2)),("Cafe",2,time(2),time(3)),("Place 102",3,time(3),time(4))]
    assert result.current_version==2 and s.validations==1

def test_add_place_rejects_unknown_place_and_missing_fields(edit):
    service,s=edit
    with pytest.raises(AppError) as error: service.edit(1,10,request("ADD_PLACE",day=1,after_item_id=101,new_place_id=999))
    assert error.value.code=="PLACE_NOT_FOUND"
    with pytest.raises(AppError) as error: service.edit(1,10,request("ADD_PLACE",day=1,after_item_id=101))
    assert error.value.code=="INVALID_EDIT_PAYLOAD" and s.plan.current_version==1

def test_add_place_uses_chosen_time_and_note(edit):
    service,s=edit; service.edit(1,10,request("ADD_PLACE",day=1,after_item_id=101,new_place_id=2,start_time="03:30",note="부산 주소"))
    added=next(x for x in s.items if x.title=="Cafe")
    assert added.start_time==time(3,30) and added.end_time==time(4,30) and added.user_note=="부산 주소"

def test_add_place_time_inside_a_stop_starts_when_it_ends(edit):
    service,s=edit; service.edit(1,10,request("ADD_PLACE",day=1,new_place_id=2,start_time="01:30"))
    rows=sorted((x for x in s.items if x.plan_id==10), key=lambda x:x.sequence_no)
    assert [(x.title,x.start_time) for x in rows]==[("Place 101",time(1)),("Cafe",time(2)),("Place 102",time(3))]

def test_add_place_before_the_first_stop(edit):
    service,s=edit; service.edit(1,10,request("ADD_PLACE",day=1,new_place_id=2,start_time="00:00"))
    rows=sorted((x for x in s.items if x.plan_id==10), key=lambda x:x.sequence_no)
    assert [(x.title,x.start_time) for x in rows]==[("Cafe",time(0)),("Place 101",time(1)),("Place 102",time(2))]

def test_removing_an_added_place_puts_later_stops_back(edit):
    service,s=edit
    snapshots=[]
    service.revisions.create=lambda plan_id,**fields: snapshots.append(SimpleNamespace(plan_id=plan_id,**fields))
    service.revisions.list_newest_first=lambda plan_id: list(reversed(snapshots))
    service.edit(1,10,request("ADD_PLACE",day=1,new_place_id=2,start_time="01:30"))
    rows=sorted((x for x in s.items if x.plan_id==10), key=lambda x:x.sequence_no)
    assert [(x.title,x.start_time) for x in rows]==[("Place 101",time(1)),("Cafe",time(2)),("Place 102",time(3))]
    added=rows[1]
    service.edit(1,10,request("DELETE_PLACE",item_id=added.item_id))
    rows=sorted((x for x in s.items if x.plan_id==10), key=lambda x:x.sequence_no)
    assert [(x.title,x.start_time,x.end_time) for x in rows]==[("Place 101",time(1),time(2)),("Place 102",time(2),time(3))]
