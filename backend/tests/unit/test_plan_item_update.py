"""Demo feature 5: time / description edits are saved on the server (UPDATE_ITEM)."""

import pytest

from app.core.exceptions import AppError
from tests.unit.test_plan_edit_service import edit, request, row  # noqa: F401  (fixture)


def test_time_and_note_are_saved_with_the_duration_kept(edit):
    service, s = edit  # day 1: item 101 at 01:00-02:00, item 102 at 02:00-03:00
    s.items[0].start_time, s.items[0].end_time = row(0, 0, 9).start_time, row(0, 0, 10).start_time
    s.items[1].start_time, s.items[1].end_time = row(0, 0, 12).start_time, row(0, 0, 13).start_time
    result = service.edit(1, 10, request("UPDATE_ITEM", item_id=101, start_time="10:30", note="사진 찍기 좋은 곳"))
    item = result.days[0].items[0]
    assert (str(item.start_time), str(item.end_time), item.note) == ("10:30:00", "11:30:00", "사진 찍기 좋은 곳")
    assert result.current_version == 2 and s.revisions[0].revision_type == "USER_EDIT"


def test_overlap_and_place_rename_are_refused_without_changes(edit):
    service, s = edit
    s.items[0].start_time, s.items[0].end_time = row(0, 0, 9).start_time, row(0, 0, 10).start_time
    s.items[1].start_time, s.items[1].end_time = row(0, 0, 12).start_time, row(0, 0, 13).start_time
    for values, code in [({"start_time": "11:30"}, "EDIT_TIME_OVERLAP"), ({"title": "다른 곳"}, "PLACE_TITLE_LOCKED")]:
        with pytest.raises(AppError) as error:
            service.edit(1, 10, request("UPDATE_ITEM", item_id=101, **values))
        assert error.value.code == code and s.plan.current_version == 1 and s.rollbacks >= 1
    assert str(s.items[0].start_time) == "09:00:00" and s.items[0].title == "Place 101"
