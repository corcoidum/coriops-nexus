"""담당별 할 일은 기한·역할·처리 상태만 보여주고 원본 업무로 연결한다."""

from contextlib import nullcontext
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.kernel.auth import Actor
from app.kernel.tasks import Candidate, MemoryTaskStore, RuleBook, TaskEngine
from app.kernel.web import UserError
from app.main import create_app
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService
from app.task_dashboard import TaskDashboardService
from ledger_helpers import FixedClock


def actor(*roles):
    return Actor(uuid4(), "testnurse", "테스트 간호", frozenset(roles), "test-csrf")


@pytest.fixture
def service():
    clock = FixedClock()
    now = clock.now()
    candidates = [Candidate("PATH.L01", "exam", uuid4(), str(i), moment) for i, moment in enumerate(
        (now - timedelta(seconds=1), now, now + timedelta(days=1)))]
    candidates.append(Candidate("PATH.L04", "exam", uuid4(), "other", now))
    engine = TaskEngine(MemoryTaskStore(), RuleBook.load(), lambda _: candidates, clock)
    engine.run()
    return TaskDashboardService(engine, lambda t: "/dashboard?selected_id=" + str(t.subject_id), nullcontext)


def test_role_union_counts_and_boundary(service):
    nurse = actor("NURSE")
    snap = service.snapshot(nurse)
    assert snap["counts"] == {"overdue": 1, "today": 1, "pending": 1, "done": 0}
    assert len(service.snapshot(actor("NURSE", "ADMIN"))["rows"]) == 4
    all_roles = service.snapshot(nurse, scope="all")
    assert len(all_roles["rows"]) == 4
    assert sum(row["can_close"] for row in all_roles["rows"]) == 3


def test_close_records_actor_and_does_not_reopen(service):
    nurse = actor("NURSE")
    row = service.snapshot(nurse)["rows"][0]
    task_id = row["task"].id
    service.close(nurse, task_id, "DONE", "")
    service.engine.run()
    done = service.snapshot(nurse, "done")["rows"][0]["task"]
    assert done.id == task_id and done.resolved_by == nurse.username
    with pytest.raises(UserError) as error:
        service.close(nurse, task_id, "DONE", "")
    assert error.value.status_code == 409


def test_other_role_is_forbidden_and_reason_is_required(service):
    task = service.snapshot(actor("NURSE"))["rows"][0]["task"]
    with pytest.raises(UserError) as error:
        service.close(actor("ADMIN"), task.id, "DONE", "")
    assert error.value.status_code == 403
    for status, reason in (("DISMISSED", ""), ("OPEN", ""), ("DONE", "x" * 121)):
        with pytest.raises(UserError) as error:
            service.close(actor("NURSE"), task.id, status, reason)
        assert error.value.status_code == 422
    service.close(actor("NURSE"), task.id, "DISMISSED", "테스트 중복 확인")
    assert service.snapshot(actor("NURSE"), "done")["rows"][0]["task"].status == "DISMISSED"


def test_task_links_and_http_filters():
    app = create_app(ManualDashboardService(clock=FixedClock()))
    with TestClient(app) as client:
        assert 'href="/tasks"' in client.get("/").text
        page = client.get("/tasks")
        assert page.status_code == 200 and "내 역할의 할 일" in page.text
        assert "테스트환자" not in page.text
        for row in app.state.task_service.snapshot(actor("NURSE", "ADMIN", "DOCTOR"))["rows"]:
            assert client.get(row["source"]).status_code == 200
        assert client.get("/tasks?bucket=NOPE").status_code == 422
        assert client.get("/tasks?scope=DOCTOR").status_code == 422


def test_http_close_requires_csrf_and_preserves_filter():
    app = create_app(ManualDashboardService(clock=FixedClock()))
    with TestClient(app) as client:
        row = app.state.task_service.snapshot(actor("NURSE", "ADMIN", "DOCTOR"))["rows"][0]
        path = f'/tasks/{row["task"].id}/close'
        assert client.post(path, data={"status": "DONE"}).status_code == 403
        response = client.post(path, data={"status": "DONE", "csrf_token": app.state.csrf_token,
                                          "bucket": "overdue", "scope": "all"}, follow_redirects=False)
        assert response.status_code == 303 and "bucket=overdue&scope=all" in response.headers["location"]
